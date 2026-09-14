"""Command line front end.

Each invocation is a complete transaction: read the state file, do one thing,
write the state file back.  Nothing is kept in memory between runs, so the
state file *is* the machine.

    $ vendomatic reset
    $ vendomatic insert 100 25
    $ vendomatic buy A1

Where the state lives
---------------------
``--state PATH`` wins, then the ``VENDOMATIC_STATE`` environment variable,
then ``vendomatic-state.json`` in the working directory.  Every command except
``reset`` needs the file to exist already.

Output
------
Human-readable text on stdout by default; ``--json`` switches to a single JSON
object instead, which every command supports.  ``--state`` and ``--json`` may
appear before or after the command name.  Errors go to stderr as
``error: <message>`` (or, with ``--json``, as ``{"error": ..., "type": ...}``).

Exit codes
----------
=====  =========================================================
   0   the command succeeded
   1   the machine refused: sold out, not enough credit, locked …
   2   bad command line -- unknown command, missing or wrong args
   3   the state file is missing, unreadable or corrupt
=====  =========================================================
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from .errors import StorageError, VendingError
from .machine import VendingMachine, demo_machine
from .money import format_price
from .storage import (
    DEFAULT_STATE_FILENAME,
    STATE_ENV_VAR,
    export_sales_csv,
    load_machine,
    save_machine,
    state_path_from_env,
)

__all__ = ["main", "run", "build_parser"]

#: Exit status for a machine-level refusal.
EXIT_VENDING_ERROR = 1
#: Exit status for a command line mistake (argparse's own convention).
EXIT_USAGE = 2
#: Exit status for a state file problem.
EXIT_STORAGE_ERROR = 3


def build_parser() -> argparse.ArgumentParser:
    """Construct the argument parser, commands and all."""
    state_help = f"state file to use (default: ${STATE_ENV_VAR} or ./{DEFAULT_STATE_FILENAME})"
    json_help = "print a JSON object instead of text"

    # Two separate parsers carrying the same two options, rather than one
    # shared via `parents`: a parent hands out its *action objects*, so the two
    # parsers would share -- and overwrite -- each other's defaults.  Here the
    # subcommand copy defaults to SUPPRESS, which leaves the value parsed
    # before the command name alone unless the option is given again after it.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--state", metavar="PATH", default=argparse.SUPPRESS, help=state_help)
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help=json_help)

    parser = argparse.ArgumentParser(
        prog="vendomatic",
        description="Drive a Vendomatic vending machine from the command line.",
    )
    parser.add_argument("--state", metavar="PATH", default=None, help=state_help)
    parser.add_argument("--json", action="store_true", help=json_help)
    commands = parser.add_subparsers(dest="command", metavar="COMMAND")

    reset = commands.add_parser(
        "reset", parents=[common], help="write a fresh state file, overwriting any existing one"
    )
    reset.add_argument(
        "--empty", action="store_true", help="start with no slots instead of the demo stock"
    )
    reset.add_argument(
        "--pin", default="1234", help="service PIN for the new machine (default: 1234)"
    )

    commands.add_parser("status", parents=[common], help="show credit, stock and takings")
    commands.add_parser("slots", parents=[common], help="list every slot")

    slot = commands.add_parser("slot", parents=[common], help="show one slot")
    slot.add_argument("code", help="slot code, e.g. A1")

    insert = commands.add_parser("insert", parents=[common], help="insert one or more coins")
    insert.add_argument("values", nargs="+", type=int, metavar="CENTS", help="coin values in cents")

    buy = commands.add_parser("buy", parents=[common], help="buy the item in a slot")
    buy.add_argument("code", help="slot code, e.g. A1")

    commands.add_parser("refund", parents=[common], help="return the inserted coins")

    restock = commands.add_parser("restock", parents=[common], help="add stock to a slot")
    restock.add_argument("code", help="slot code, e.g. A1")
    restock.add_argument("quantity", type=int, help="how many items to add")
    restock.add_argument("--pin", required=True, help="service PIN")

    collect = commands.add_parser("collect", parents=[common], help="empty the coin bank")
    collect.add_argument("--pin", required=True, help="service PIN")

    report = commands.add_parser("report", parents=[common], help="summarise sales")
    report.add_argument("--csv", metavar="PATH", help="also write the sales log to this CSV file")

    serve = commands.add_parser("serve", parents=[common], help="run the HTTP API")
    serve.add_argument("--port", type=int, default=8080, help="port to listen on (default: 8080)")
    serve.add_argument("--host", default="127.0.0.1", help="address to bind (default: 127.0.0.1)")
    serve.add_argument("--token", default="service-token", help="value the API requires in the X-Service-Token header")

    return parser


def _emit(payload: dict, text: str, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2))
    elif text:
        print(text)


def _slot_line(slot) -> str:
    stock = "sold out" if slot.is_sold_out else f"{slot.quantity}/{slot.capacity}"
    return f"{slot.code}  {slot.name:<16} {slot.price:>8}  {stock}"


def _purse_text(purse: dict[int, int]) -> str:
    if not purse:
        return "no coins"
    return ", ".join(f"{count} x {format_price(coin)}" for coin, count in purse.items())


def main(argv: Sequence[str] | None = None) -> int:
    """Run one command and return the process exit code.

    ``argv`` defaults to :data:`sys.argv[1:]`.  Nothing is printed to stderr
    unless something went wrong, and the return value is the exit code rather
    than an exception, so this is callable in-process as well as from a shell.
    """
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    as_json = bool(getattr(args, "json", False))

    if not args.command:
        parser.print_help()
        return EXIT_USAGE

    path = state_path_from_env(getattr(args, "state", None))

    try:
        return _dispatch(args, path, as_json)
    except StorageError as exc:
        _fail(str(exc), type(exc).__name__, as_json)
        return EXIT_STORAGE_ERROR
    except VendingError as exc:
        _fail(str(exc), type(exc).__name__, as_json)
        return EXIT_VENDING_ERROR
    except ValueError as exc:
        _fail(str(exc), type(exc).__name__, as_json)
        return EXIT_VENDING_ERROR


def _fail(message: str, kind: str, as_json: bool) -> None:
    if as_json:
        print(json.dumps({"error": message, "type": kind}, indent=2), file=sys.stderr)
    else:
        print(f"error: {message}", file=sys.stderr)


def _dispatch(args: argparse.Namespace, path: Path, as_json: bool) -> int:
    command = args.command

    if command == "reset":
        machine = (
            VendingMachine(service_pin=args.pin)
            if args.empty
            else demo_machine()
        )
        if not args.empty and args.pin != "1234":
            machine.set_service_pin("1234", args.pin)
        save_machine(machine, path)
        _emit(
            {"state": str(path), "slots": len(machine.inventory), "empty": bool(args.empty)},
            f"Wrote fresh state to {path} ({len(machine.inventory)} slots)",
            as_json,
        )
        return 0

    machine = load_machine(path)

    if command == "status":
        status = machine.status()
        text = "\n".join(
            [
                f"Credit:  {status['credit']}",
                f"Slots:   {status['slots']} ({status['items']} items)",
                f"Bank:    {format_price(status['bank_cents'])}",
                f"Sold:    {status['items_sold']} items, "
                f"{format_price(status['revenue_cents'])}",
                f"Service: {'locked' if status['locked'] else 'unlocked'}",
            ]
        )
        _emit(status, text, as_json)
        return 0

    if command == "slots":
        slots = machine.inventory.list_slots()
        _emit(
            {"slots": [slot.to_dict() for slot in slots]},
            "\n".join(_slot_line(slot) for slot in slots) or "No slots",
            as_json,
        )
        return 0

    if command == "slot":
        slot = machine.inventory.get_slot(args.code)
        _emit(slot.to_dict(), _slot_line(slot), as_json)
        return 0

    if command == "insert":
        for value in args.values:
            machine.insert_coin(value)
        save_machine(machine, path)
        _emit(
            {"credit_cents": machine.credit_cents, "credit": machine.credit},
            f"Credit: {machine.credit}",
            as_json,
        )
        return 0

    if command == "buy":
        purchase = machine.select(args.code)
        save_machine(machine, path)
        text = f"Dispensed {purchase.item_name} ({purchase.slot_code}) for {format_price(purchase.price_cents)}"
        if purchase.change:
            text += f"\nChange: {format_price(purchase.change_cents)} ({_purse_text(purchase.change)})"
        _emit(purchase.to_dict(), text, as_json)
        return 0

    if command == "refund":
        coins = machine.refund()
        save_machine(machine, path)
        from .money import coin_total

        _emit(
            {
                "refunded_cents": coin_total(coins),
                "coins": {str(coin): count for coin, count in coins.items()},
            },
            f"Refunded {format_price(coin_total(coins))} ({_purse_text(coins)})",
            as_json,
        )
        return 0

    if command == "restock":
        machine.unlock(args.pin)
        try:
            slot = machine.restock(args.code, args.quantity)
        finally:
            machine.lock()
        save_machine(machine, path)
        _emit(slot.to_dict(), f"{slot.code} now holds {slot.quantity}/{slot.capacity}", as_json)
        return 0

    if command == "collect":
        machine.unlock(args.pin)
        try:
            coins = machine.collect_cash()
        finally:
            machine.lock()
        save_machine(machine, path)
        from .money import coin_total

        _emit(
            {
                "collected_cents": coin_total(coins),
                "coins": {str(coin): count for coin, count in coins.items()},
            },
            f"Collected {format_price(coin_total(coins))} ({_purse_text(coins)})",
            as_json,
        )
        return 0

    if command == "report":
        report = machine.sales_report()
        if args.csv:
            report["csv_rows"] = export_sales_csv(machine, args.csv)
            report["csv_path"] = str(args.csv)
        lines = [f"Sold {report['items_sold']} items for {report['revenue']}"]
        lines += [
            f"  {name:<16} {entry['count']:>3} x  {format_price(entry['revenue_cents'])}"
            for name, entry in report["by_item"].items()
        ]
        if args.csv:
            lines.append(f"Wrote {report['csv_rows']} rows to {args.csv}")
        _emit(report, "\n".join(lines), as_json)
        return 0

    if command == "serve":
        from .server import serve_forever

        serve_forever(path, host=args.host, port=args.port, token=args.token)
        return 0

    raise AssertionError(f"unhandled command: {command}")  # pragma: no cover


def run() -> None:
    """Console-script entry point: run :func:`main` and exit with its code."""
    sys.exit(main())


if __name__ == "__main__":  # pragma: no cover
    run()
