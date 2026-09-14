"""Exception hierarchy for Vendomatic.

Every error the library raises on purpose derives from :class:`VendingError`,
so a caller can catch the whole family with one ``except`` clause::

    try:
        machine.select("A1")
    except VendingError as exc:
        print(exc)

Error messages are stable and deterministic: they are part of the public
behaviour of the library, not debug output.  Where an amount of money appears
in a message it is always formatted by :func:`vendomatic.money.format_price`,
e.g. ``"$1.25"``.
"""

from __future__ import annotations

__all__ = [
    "VendingError",
    "InvalidPriceError",
    "InvalidCoinError",
    "ExactChangeError",
    "InvalidSlotCodeError",
    "SlotNotFoundError",
    "DuplicateSlotError",
    "CapacityExceededError",
    "SoldOutError",
    "InsufficientCreditError",
    "MachineLockedError",
    "StorageError",
    "JobNotFoundError",
]


class VendingError(Exception):
    """Base class for every deliberate failure in this library."""


class InvalidPriceError(VendingError):
    """A price string could not be parsed, or a price was negative."""


class InvalidCoinError(VendingError):
    """A coin was offered that the machine does not accept."""


class ExactChangeError(VendingError):
    """The coin bank cannot make up the change a purchase would require.

    Raised *before* anything is dispensed: the purchase is abandoned and the
    inserted credit is left untouched.
    """


class InvalidSlotCodeError(VendingError):
    """A slot code is not one uppercase letter followed by one digit 1-9."""


class SlotNotFoundError(VendingError):
    """No slot with that code exists in the inventory."""


class DuplicateSlotError(VendingError):
    """A slot with that code already exists in the inventory."""


class CapacityExceededError(VendingError):
    """A restock would push a slot past its capacity."""


class SoldOutError(VendingError):
    """The selected slot exists but its quantity is zero."""


class InsufficientCreditError(VendingError):
    """The inserted credit does not cover the price of the selection."""


class MachineLockedError(VendingError):
    """A service-only operation was attempted while the machine was locked."""


class StorageError(VendingError):
    """A state file is missing, unreadable, or not valid machine state."""


class JobNotFoundError(VendingError):
    """No background job with that id is known to the runner."""
