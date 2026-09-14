"""Vendomatic -- a vending machine you can drive from anywhere.

The library is built in layers, each adding one kind of moving part:

=========================  ==================================================
:mod:`vendomatic.money`      pure functions: prices, coins, making change
:mod:`vendomatic.inventory`  slots and stock levels
:mod:`vendomatic.machine`    credit, purchases, service mode, sales log
:mod:`vendomatic.storage`    saving and loading state as JSON and CSV
:mod:`vendomatic.cli`        the ``vendomatic`` command line program
:mod:`vendomatic.server`     a JSON-over-HTTP API
:mod:`vendomatic.maintenance` background jobs and a slow cabinet thermometer
=========================  ==================================================

Nothing outside the standard library is needed to run any of it.

A machine in five lines::

    from vendomatic import demo_machine

    machine = demo_machine()
    machine.insert_coins(100, 25, 10)
    receipt = machine.select("A1")
    print(receipt.item_name, receipt.change)

:mod:`vendomatic.errors` holds every exception the library raises on purpose;
they all derive from :class:`~vendomatic.errors.VendingError`.
"""

from __future__ import annotations

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
    StorageError,
    VendingError,
)
from .inventory import Inventory, Slot
from .machine import Purchase, VendingMachine, demo_machine
from .money import COIN_VALUES, add_coins, coin_total, format_price, make_change, parse_price

__version__ = "1.0.0"

__all__ = [
    "__version__",
    "COIN_VALUES",
    "Inventory",
    "Purchase",
    "Slot",
    "VendingMachine",
    "add_coins",
    "coin_total",
    "demo_machine",
    "format_price",
    "make_change",
    "parse_price",
    "CapacityExceededError",
    "DuplicateSlotError",
    "ExactChangeError",
    "InsufficientCreditError",
    "InvalidCoinError",
    "InvalidPriceError",
    "InvalidSlotCodeError",
    "JobNotFoundError",
    "MachineLockedError",
    "SlotNotFoundError",
    "SoldOutError",
    "StorageError",
    "VendingError",
]
