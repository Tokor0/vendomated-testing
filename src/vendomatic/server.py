"""A small JSON-over-HTTP API in front of a machine.

Built on :mod:`http.server` from the standard library -- no third-party
dependencies, no framework.  Requests and responses are JSON.

Endpoints
---------
======  ==========================  ================================================
GET     ``/health``                 liveness probe; always ``200``
GET     ``/slots``                  every slot
GET     ``/slots/{code}``           one slot
GET     ``/credit``                 the credit currently inserted
POST    ``/coins``                  insert a coin -- body ``{"value": 25}``
POST    ``/refund``                 return the inserted coins
POST    ``/purchase``               buy -- body ``{"code": "A1"}``
GET     ``/sales``                  the sales report
POST    ``/admin/restock``          add stock -- body ``{"code": "A1", "quantity": 3}``
POST    ``/admin/collect``          empty the coin bank
POST    ``/admin/jobs/restock``     queue a restock; returns ``202`` and a job id
GET     ``/jobs/{id}``              how a queued job is getting on
======  ==========================  ================================================

Everything under ``/admin`` requires the header ``X-Service-Token`` to match
the server's token, and answers ``401`` when it does not.

Status codes
------------
``200`` fine, ``201`` a coin was accepted, ``202`` a job was queued, ``400``
malformed request or bad JSON, ``401`` missing or wrong service token, ``404``
unknown path, slot or job, ``405`` wrong method for a known path, ``409`` the
machine refused (sold out, not enough credit, no change, slot full).

Error bodies always look like ``{"error": "...", "type": "SoldOutError"}``.

State
-----
The server keeps one :class:`~vendomatic.machine.VendingMachine` in memory and
serves every request from it.  Given a ``state_path`` it loads that file at
start-up and writes it back after each change, so the API and the command line
can drive the same machine.
"""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .errors import (
    CapacityExceededError,
    DuplicateSlotError,
    ExactChangeError,
    InsufficientCreditError,
    InvalidCoinError,
    InvalidPriceError,
    InvalidSlotCodeError,
    JobNotFoundError,
    MachineLockedError,
    SlotNotFoundError,
    SoldOutError,
    VendingError,
)
from .machine import VendingMachine, demo_machine
from .maintenance import JobRunner
from .money import coin_total
from .storage import load_machine, save_machine

__all__ = ["DEFAULT_SERVICE_TOKEN", "VendomaticServer", "create_server", "serve_forever"]

#: Token the API expects in ``X-Service-Token`` when none is configured.
DEFAULT_SERVICE_TOKEN = "service-token"

#: Header carrying the service token.
SERVICE_TOKEN_HEADER = "X-Service-Token"

#: Maps machine errors to the HTTP status that best describes them.
_STATUS_BY_ERROR: dict[type[BaseException], int] = {
    InvalidSlotCodeError: 400,
    InvalidCoinError: 400,
    InvalidPriceError: 400,
    SlotNotFoundError: 404,
    JobNotFoundError: 404,
    MachineLockedError: 403,
    SoldOutError: 409,
    InsufficientCreditError: 409,
    ExactChangeError: 409,
    CapacityExceededError: 409,
    DuplicateSlotError: 409,
}


def _status_for(exc: BaseException) -> int:
    for error_type, status in _STATUS_BY_ERROR.items():
        if isinstance(exc, error_type):
            return status
    return 409 if isinstance(exc, VendingError) else 400


class VendomaticServer(ThreadingHTTPServer):
    """An HTTP server holding one machine, its job runner and its token.

    :param machine: the machine every request operates on.
    :param token: the value ``/admin`` endpoints require.
    :param state_path: where to persist after each change; ``None`` keeps the
        machine in memory only.
    :param service_pin: PIN the server uses internally for service operations
        once a request has presented a valid token.
    """

    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        server_address: tuple[str, int],
        machine: VendingMachine,
        token: str = DEFAULT_SERVICE_TOKEN,
        state_path: str | os.PathLike | None = None,
        service_pin: str = "1234",
    ) -> None:
        super().__init__(server_address, _Handler)
        self.machine = machine
        self.token = str(token)
        self.state_path = Path(state_path) if state_path else None
        self.service_pin = str(service_pin)
        self.jobs = JobRunner(default_delay=2.0)

    @property
    def port(self) -> int:
        """The port actually bound -- useful when asking for port ``0``."""
        return self.server_address[1]

    @property
    def url(self) -> str:
        """Base URL of the server, e.g. ``http://127.0.0.1:8080``."""
        host, port = self.server_address[0], self.server_address[1]
        return f"http://{host}:{port}"

    def persist(self) -> None:
        """Write the machine back to its state file, if it has one."""
        if self.state_path is not None:
            save_machine(self.machine, self.state_path)

    def server_close(self) -> None:  # noqa: D102 - inherited behaviour plus cleanup
        try:
            self.jobs.shutdown(timeout=2.0)
        finally:
            super().server_close()


class _Handler(BaseHTTPRequestHandler):
    """Routes one request.  Instantiated per request by the server."""

    server_version = "Vendomatic/1.0"
    protocol_version = "HTTP/1.1"

    # ------------------------------------------------------------- plumbing

    def log_message(self, fmt: str, *args: Any) -> None:
        """Stay quiet unless ``VENDOMATIC_HTTP_LOG`` is set in the environment."""
        if os.environ.get("VENDOMATIC_HTTP_LOG"):
            super().log_message(fmt, *args)

    def _send(self, status: int, payload: dict | list) -> None:
        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_error(self, status: int, message: str, kind: str = "Error") -> None:
        self._send(status, {"error": message, "type": kind})

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"Request body is not valid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError("Request body must be a JSON object")
        return payload

    def _authorised(self) -> bool:
        return self.headers.get(SERVICE_TOKEN_HEADER) == self.server.token

    # --------------------------------------------------------------- routes

    def do_GET(self) -> None:  # noqa: N802 - name mandated by BaseHTTPRequestHandler
        """Handle a read request."""
        self._route("GET")

    def do_POST(self) -> None:  # noqa: N802 - name mandated by BaseHTTPRequestHandler
        """Handle a write request."""
        self._route("POST")

    def _route(self, method: str) -> None:
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        machine: VendingMachine = self.server.machine
        try:
            if path == "/health":
                self._require(method, "GET")
                return self._send(200, {"status": "ok", "slots": len(machine.inventory)})

            if path == "/slots":
                self._require(method, "GET")
                return self._send(
                    200, {"slots": [slot.to_dict() for slot in machine.inventory.list_slots()]}
                )

            if path.startswith("/slots/"):
                self._require(method, "GET")
                code = path[len("/slots/") :]
                return self._send(200, machine.inventory.get_slot(code).to_dict())

            if path == "/credit":
                self._require(method, "GET")
                return self._send(
                    200,
                    {
                        "credit_cents": machine.credit_cents,
                        "credit": machine.credit,
                        "coins": {str(c): n for c, n in machine.inserted_coins.items()},
                    },
                )

            if path == "/coins":
                self._require(method, "POST")
                body = self._read_json()
                if "value" not in body:
                    raise ValueError("Body must contain 'value'")
                machine.insert_coin(body["value"])
                self.server.persist()
                return self._send(
                    201, {"credit_cents": machine.credit_cents, "credit": machine.credit}
                )

            if path == "/refund":
                self._require(method, "POST")
                coins = machine.refund()
                self.server.persist()
                return self._send(
                    200,
                    {
                        "refunded_cents": coin_total(coins),
                        "coins": {str(c): n for c, n in coins.items()},
                    },
                )

            if path == "/purchase":
                self._require(method, "POST")
                body = self._read_json()
                if "code" not in body:
                    raise ValueError("Body must contain 'code'")
                purchase = machine.select(body["code"])
                self.server.persist()
                return self._send(200, purchase.to_dict())

            if path == "/sales":
                self._require(method, "GET")
                report = machine.sales_report()
                report["sales"] = [sale.to_dict() for sale in machine.sales]
                return self._send(200, report)

            if path.startswith("/jobs/"):
                self._require(method, "GET")
                job_id = path[len("/jobs/") :]
                return self._send(200, self.server.jobs.get_job(job_id).to_dict())

            if path.startswith("/admin/"):
                return self._admin(method, path)

            return self._send_error(404, f"No such endpoint: {path}", "NotFound")

        except _MethodNotAllowed as exc:
            self.send_response(405)
            self.send_header("Allow", exc.allowed)
            body = json.dumps(
                {"error": f"{method} not allowed on {path}", "type": "MethodNotAllowed"}
            ).encode("utf-8")
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except VendingError as exc:
            self._send_error(_status_for(exc), str(exc), type(exc).__name__)
        except ValueError as exc:
            self._send_error(400, str(exc), type(exc).__name__)

    def _admin(self, method: str, path: str) -> None:
        if not self._authorised():
            return self._send_error(
                401, f"Missing or invalid {SERVICE_TOKEN_HEADER} header", "Unauthorized"
            )

        machine: VendingMachine = self.server.machine
        pin = self.server.service_pin

        if path == "/admin/restock":
            self._require(method, "POST")
            body = self._read_json()
            if "code" not in body:
                raise ValueError("Body must contain 'code'")
            quantity = int(body.get("quantity", 1))
            machine.unlock(pin)
            try:
                slot = machine.restock(body["code"], quantity)
            finally:
                machine.lock()
            self.server.persist()
            return self._send(200, slot.to_dict())

        if path == "/admin/collect":
            self._require(method, "POST")
            machine.unlock(pin)
            try:
                coins = machine.collect_cash()
            finally:
                machine.lock()
            self.server.persist()
            return self._send(
                200,
                {
                    "collected_cents": coin_total(coins),
                    "coins": {str(c): n for c, n in coins.items()},
                },
            )

        if path == "/admin/jobs/restock":
            self._require(method, "POST")
            body = self._read_json()
            if "code" not in body:
                raise ValueError("Body must contain 'code'")
            job_id = self.server.jobs.schedule_restock(
                machine,
                body["code"],
                int(body.get("quantity", 1)),
                pin=pin,
                delay=float(body.get("delay", 2.0)),
            )
            return self._send(202, {"job_id": job_id, "status": "pending"})

        return self._send_error(404, f"No such endpoint: {path}", "NotFound")

    def _require(self, method: str, allowed: str) -> None:
        if method != allowed:
            raise _MethodNotAllowed(allowed)


class _MethodNotAllowed(Exception):
    """Internal signal that a known path was asked for with the wrong verb."""

    def __init__(self, allowed: str) -> None:
        super().__init__(allowed)
        self.allowed = allowed


def create_server(
    machine: VendingMachine | None = None,
    host: str = "127.0.0.1",
    port: int = 0,
    token: str = DEFAULT_SERVICE_TOKEN,
    state_path: str | os.PathLike | None = None,
    service_pin: str = "1234",
) -> VendomaticServer:
    """Build a server without starting it.

    Port ``0`` asks the operating system for a free port, which the returned
    server reports as :attr:`VendomaticServer.port`.  Call ``serve_forever()``
    on the result -- usually on a thread -- and ``server_close()`` when done.
    """
    if machine is None:
        machine = load_machine(state_path) if state_path else demo_machine()
    return VendomaticServer(
        (host, int(port)),
        machine=machine,
        token=token,
        state_path=state_path,
        service_pin=service_pin,
    )


def serve_forever(
    state_path: str | os.PathLike | None = None,
    host: str = "127.0.0.1",
    port: int = 8080,
    token: str = DEFAULT_SERVICE_TOKEN,
) -> None:
    """Start a server and block until interrupted.

    This is what ``vendomatic serve`` calls.  It prints the URL it is
    listening on, so a caller watching stdout knows when it is ready.
    """
    server = create_server(host=host, port=port, token=token, state_path=state_path)
    print(f"Vendomatic listening on {server.url}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - thin wrapper
    """``python -m vendomatic.server`` entry point."""
    import argparse

    parser = argparse.ArgumentParser(prog="vendomatic.server", description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--token", default=DEFAULT_SERVICE_TOKEN)
    parser.add_argument("--state", default=None, help="state file to load and persist to")
    args = parser.parse_args(argv)
    serve_forever(state_path=args.state, host=args.host, port=args.port, token=args.token)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
