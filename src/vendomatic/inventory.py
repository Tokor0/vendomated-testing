"""Slots and stock levels.

A machine's front panel is a grid of **slots**.  Each slot has a code like
``A1``, holds one kind of product, and has a capacity it cannot be filled past.

:class:`Inventory` owns the slots and knows nothing about money changing hands
-- it can tell you that ``A1`` holds three bags of crisps at 125 cents each,
and it can take one out, but deciding whether a customer has paid is
:mod:`vendomatic.machine`'s job.

Slot codes
----------
A code is one uppercase letter ``A``-``Z`` followed by one digit ``1``-``9``.
Codes are normalised on the way in: ``"a1"`` and ``" A1 "`` both mean ``A1``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterator

from .errors import (
    CapacityExceededError,
    DuplicateSlotError,
    InvalidPriceError,
    InvalidSlotCodeError,
    SlotNotFoundError,
    SoldOutError,
)
from .money import format_price

__all__ = ["DEFAULT_CAPACITY", "Slot", "Inventory", "normalise_slot_code"]

#: How many items a slot holds when no capacity is given.
DEFAULT_CAPACITY = 10

_SLOT_CODE_PATTERN = re.compile(r"^[A-Z][1-9]$")


def normalise_slot_code(code: object) -> str:
    """Return ``code`` upper-cased and stripped, once it is known to be valid.

    :raises InvalidSlotCodeError: if it is not a letter followed by 1-9.
    """
    if not isinstance(code, str):
        raise InvalidSlotCodeError(f"Invalid slot code: {code!r}")
    candidate = code.strip().upper()
    if not _SLOT_CODE_PATTERN.match(candidate):
        raise InvalidSlotCodeError(
            f"Invalid slot code: {code!r}. Expected a letter A-Z followed by a digit 1-9"
        )
    return candidate


@dataclass
class Slot:
    """One product column in the machine.

    :param code: slot code, normalised on construction (``"a1"`` -> ``"A1"``).
    :param name: product name, e.g. ``"Salted Crisps"``.
    :param price_cents: price of one item, in cents; may not be negative.
    :param quantity: how many items are in the slot right now.
    :param capacity: how many items fit; ``quantity`` may never exceed it.
    """

    code: str
    name: str
    price_cents: int
    quantity: int = 0
    capacity: int = DEFAULT_CAPACITY

    def __post_init__(self) -> None:
        self.code = normalise_slot_code(self.code)
        self.name = str(self.name).strip()
        if not self.name:
            raise ValueError("Slot name must not be empty")
        self.price_cents = int(self.price_cents)
        if self.price_cents < 0:
            raise InvalidPriceError(f"Invalid price: {self.price_cents!r}")
        self.capacity = int(self.capacity)
        if self.capacity < 1:
            raise ValueError(f"Slot capacity must be at least 1, got {self.capacity!r}")
        self.quantity = int(self.quantity)
        if self.quantity < 0:
            raise ValueError(f"Slot quantity must not be negative, got {self.quantity!r}")
        if self.quantity > self.capacity:
            raise CapacityExceededError(
                f"Slot {self.code} holds {self.capacity}, cannot start with {self.quantity}"
            )

    @property
    def is_sold_out(self) -> bool:
        """Whether the slot is empty."""
        return self.quantity == 0

    @property
    def free_space(self) -> int:
        """How many more items the slot could take."""
        return self.capacity - self.quantity

    @property
    def price(self) -> str:
        """The price as a display string, e.g. ``"$1.25"``."""
        return format_price(self.price_cents)

    def to_dict(self) -> dict:
        """A plain-dict view of the slot, safe to serialise to JSON."""
        return {
            "code": self.code,
            "name": self.name,
            "price_cents": self.price_cents,
            "quantity": self.quantity,
            "capacity": self.capacity,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Slot":
        """Rebuild a slot from :meth:`to_dict` output."""
        return cls(
            code=data["code"],
            name=data["name"],
            price_cents=int(data["price_cents"]),
            quantity=int(data.get("quantity", 0)),
            capacity=int(data.get("capacity", DEFAULT_CAPACITY)),
        )


@dataclass
class Inventory:
    """A collection of slots, keyed by slot code.

    Slots keep the order they were added in, which is the order
    :meth:`list_slots` and iteration report them.
    """

    _slots: dict[str, Slot] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self._slots)

    def __iter__(self) -> Iterator[Slot]:
        return iter(self._slots.values())

    def __contains__(self, code: object) -> bool:
        try:
            return normalise_slot_code(code) in self._slots
        except InvalidSlotCodeError:
            return False

    def add_slot(
        self,
        code: str,
        name: str,
        price_cents: int,
        quantity: int = 0,
        capacity: int = DEFAULT_CAPACITY,
    ) -> Slot:
        """Install a new slot and return it.

        :raises DuplicateSlotError: if the code is already in use.
        :raises InvalidSlotCodeError: if the code is malformed.
        """
        slot = Slot(code, name, price_cents, quantity, capacity)
        if slot.code in self._slots:
            raise DuplicateSlotError(f"Slot {slot.code} already exists")
        self._slots[slot.code] = slot
        return slot

    def remove_slot(self, code: str) -> Slot:
        """Take a slot out of the machine and return it.

        :raises SlotNotFoundError: if no such slot exists.
        """
        slot = self.get_slot(code)
        del self._slots[slot.code]
        return slot

    def get_slot(self, code: str) -> Slot:
        """Return the slot with this code.

        :raises InvalidSlotCodeError: if the code is malformed.
        :raises SlotNotFoundError: if the code is well-formed but unknown.
        """
        key = normalise_slot_code(code)
        try:
            return self._slots[key]
        except KeyError:
            raise SlotNotFoundError(f"No such slot: {key}") from None

    def list_slots(self) -> list[Slot]:
        """All slots, in the order they were added."""
        return list(self._slots.values())

    def codes(self) -> list[str]:
        """All slot codes, in the order they were added."""
        return list(self._slots)

    def restock(self, code: str, quantity: int = 1) -> Slot:
        """Add ``quantity`` items to a slot and return it.

        :raises ValueError: if ``quantity`` is not positive.
        :raises CapacityExceededError: if the slot cannot hold that many more;
            nothing is added in that case.
        """
        slot = self.get_slot(code)
        amount = int(quantity)
        if amount < 1:
            raise ValueError(f"Restock quantity must be at least 1, got {quantity!r}")
        if amount > slot.free_space:
            raise CapacityExceededError(
                f"Slot {slot.code} has room for {slot.free_space} more, not {amount}"
            )
        slot.quantity += amount
        return slot

    def fill(self, code: str) -> Slot:
        """Top a slot up to its capacity and return it."""
        slot = self.get_slot(code)
        slot.quantity = slot.capacity
        return slot

    def dispense(self, code: str) -> Slot:
        """Remove one item from a slot and return the slot.

        :raises SoldOutError: if the slot is empty; the slot is left alone.
        """
        slot = self.get_slot(code)
        if slot.is_sold_out:
            raise SoldOutError(f"Slot {slot.code} ({slot.name}) is sold out")
        slot.quantity -= 1
        return slot

    def low_stock(self, threshold: int = 2) -> list[Slot]:
        """Slots at or below ``threshold`` items, neediest first.

        Ties keep insertion order, so the result is stable.
        """
        limit = int(threshold)
        needy = [slot for slot in self._slots.values() if slot.quantity <= limit]
        return sorted(needy, key=lambda slot: slot.quantity)

    def total_items(self) -> int:
        """How many items are in the machine across all slots."""
        return sum(slot.quantity for slot in self._slots.values())

    def total_value_cents(self) -> int:
        """What the loaded stock would be worth if it all sold at list price."""
        return sum(slot.quantity * slot.price_cents for slot in self._slots.values())

    def to_dict(self) -> dict:
        """A plain-dict view of the inventory, safe to serialise to JSON."""
        return {"slots": [slot.to_dict() for slot in self._slots.values()]}

    @classmethod
    def from_dict(cls, data: dict) -> "Inventory":
        """Rebuild an inventory from :meth:`to_dict` output."""
        inventory = cls()
        for raw in data.get("slots", []):
            slot = Slot.from_dict(raw)
            if slot.code in inventory._slots:
                raise DuplicateSlotError(f"Slot {slot.code} already exists")
            inventory._slots[slot.code] = slot
        return inventory
