"""Saving a machine to disk and reading it back.

State lives in a single JSON file.  :func:`save_machine` writes it atomically
-- to a temporary file in the same directory, then a rename -- so a reader
never sees a half-written file, and a crash mid-save leaves the previous state
intact.

Anything that goes wrong with a file is reported as
:class:`~vendomatic.errors.StorageError`: missing, unreadable, not JSON, or
JSON that is not machine state.  The underlying ``OSError`` or
``JSONDecodeError`` is kept as the exception's ``__cause__``.

The sales log can also be exported as CSV for a spreadsheet, which is a
one-way trip -- :func:`load_machine` only reads the JSON format.
"""

from __future__ import annotations

import csv
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Callable

from .errors import StorageError, VendingError
from .machine import VendingMachine
from .money import format_price

__all__ = [
    "STATE_FILE_VERSION",
    "save_machine",
    "load_machine",
    "export_sales_csv",
    "state_path_from_env",
]

#: Version stamped into every state file this library writes.
STATE_FILE_VERSION = 1

#: Environment variable :func:`state_path_from_env` consults.
STATE_ENV_VAR = "VENDOMATIC_STATE"

#: Where state goes when neither an argument nor the environment says.
DEFAULT_STATE_FILENAME = "vendomatic-state.json"

_SALES_CSV_COLUMNS = ["timestamp", "slot_code", "item_name", "price", "paid", "change"]


def state_path_from_env(explicit: str | os.PathLike | None = None) -> Path:
    """Decide which state file to use.

    In order of precedence: an ``explicit`` path, the ``VENDOMATIC_STATE``
    environment variable, then :data:`DEFAULT_STATE_FILENAME` in the current
    working directory.
    """
    if explicit:
        return Path(explicit)
    from_env = os.environ.get(STATE_ENV_VAR)
    if from_env:
        return Path(from_env)
    return Path.cwd() / DEFAULT_STATE_FILENAME


def save_machine(machine: VendingMachine, path: str | os.PathLike) -> Path:
    """Write ``machine`` to ``path`` as JSON and return the path written.

    Parent directories are created as needed.  The file is pretty-printed with
    two-space indentation and ends with a newline, so it reads well and diffs
    cleanly.

    :raises StorageError: if the file could not be written.
    """
    target = Path(path)
    payload = {"version": STATE_FILE_VERSION, "machine": machine.to_dict()}
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        )
        try:
            with handle:
                json.dump(payload, handle, indent=2, sort_keys=False)
                handle.write("\n")
            os.replace(handle.name, target)
        except BaseException:
            Path(handle.name).unlink(missing_ok=True)
            raise
    except OSError as exc:
        raise StorageError(f"Could not write state to {target}: {exc}") from exc
    return target


def load_machine(
    path: str | os.PathLike, clock: Callable[[], datetime] | None = None
) -> VendingMachine:
    """Read a machine back from ``path``.

    The machine comes back locked, whatever it was when it was saved.

    :raises StorageError: if the file is missing, unreadable, not JSON, or
        does not hold machine state this version understands.
    """
    source = Path(path)
    try:
        text = source.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise StorageError(f"No state file at {source}") from exc
    except OSError as exc:
        raise StorageError(f"Could not read state from {source}: {exc}") from exc

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise StorageError(f"State file {source} is not valid JSON: {exc}") from exc

    if not isinstance(payload, dict) or "machine" not in payload:
        raise StorageError(f"State file {source} does not contain machine state")

    version = payload.get("version")
    if version != STATE_FILE_VERSION:
        raise StorageError(
            f"State file {source} has version {version!r}, expected {STATE_FILE_VERSION}"
        )

    try:
        return VendingMachine.from_dict(payload["machine"], clock=clock)
    except (VendingError, KeyError, TypeError, ValueError) as exc:
        raise StorageError(f"State file {source} is corrupt: {exc}") from exc


def export_sales_csv(machine: VendingMachine, path: str | os.PathLike) -> int:
    """Write the sales log to ``path`` as CSV and return the number of rows.

    The header row is always written, even for a machine that has sold
    nothing, so the file is still a valid CSV with zero rows.  Columns:
    ``timestamp, slot_code, item_name, price, paid, change`` -- amounts are
    formatted for reading (``"$1.25"``), and ``change`` is a semicolon-joined
    list like ``"1 x $0.25; 2 x $0.10"``, empty when payment was exact.

    :raises StorageError: if the file could not be written.
    """
    target = Path(path)
    sales = machine.sales
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(_SALES_CSV_COLUMNS)
            for sale in sales:
                change = "; ".join(
                    f"{count} x {format_price(coin)}" for coin, count in sale.change.items()
                )
                writer.writerow(
                    [
                        sale.at.isoformat(),
                        sale.slot_code,
                        sale.item_name,
                        format_price(sale.price_cents),
                        format_price(sale.paid_cents),
                        change,
                    ]
                )
    except OSError as exc:
        raise StorageError(f"Could not write sales to {target}: {exc}") from exc
    return len(sales)
