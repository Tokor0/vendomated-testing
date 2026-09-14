"""The machine itself: credit, purchases, change, service mode and sales.

:class:`VendingMachine` ties an :class:`~vendomatic.inventory.Inventory`
together with a coin bank and a sales log.  It is the object a customer
"talks to": insert coins, make a selection, take the change, or press refund
and walk away.

Customer side
-------------
:meth:`~VendingMachine.insert_coin`, :meth:`~VendingMachine.select`,
:meth:`~VendingMachine.refund`.  Credit only exists between the first coin and
the purchase or refund that clears it.

Service side
------------
Restocking, adding slots, loading change and emptying the cash box are locked
behind a PIN.  :meth:`~VendingMachine.unlock` opens service mode,
:meth:`~VendingMachine.lock` closes it, and every service operation raises
:class:`~vendomatic.errors.MachineLockedError` while the machine is locked.

Order of checks in a purchase
-----------------------------
:meth:`~VendingMachine.select` validates in a fixed order, so the failure a
customer sees is always the most relevant one:

1. the slot code is well formed, and the slot exists;
2. the slot is not sold out;
3. the credit covers the price;
4. the coin bank can make the change.

A purchase that fails at any step changes nothing at all -- no item leaves the
slot, no coin moves, and the inserted credit stays where it is so the customer
can add more coins or press refund.

Time
----
Sales are timestamped.  The machine gets the time from a ``clock`` callable
that defaults to :func:`datetime.datetime.now` in UTC; pass your own to make
timestamps predictable.

Thread safety
-------------
Public methods hold a re-entrant lock, so a machine can be driven from several
threads at once (which is what :mod:`vendomatic.server` and
:mod:`vendomatic.maintenance` do).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Mapping

from .errors import (
    ExactChangeError,
    InsufficientCreditError,
    MachineLockedError,
    SoldOutError,
)
from .inventory import DEFAULT_CAPACITY, Inventory, Slot
from .money import add_coins, coin_total, format_price, make_change, validate_coin

__all__ = ["DEFAULT_SERVICE_PIN", "Purchase", "VendingMachine"]

#: The PIN a machine ships with when none is given.
DEFAULT_SERVICE_PIN = "0000"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class Purchase:
    """The receipt for one completed sale.

    :param slot_code: which slot was emptied by one item.
    :param item_name: the product's name at the time of sale.
    :param price_cents: what it cost.
    :param paid_cents: what the customer had inserted.
    :param change: the coin purse handed back; empty if payment was exact.
    :param at: when the sale completed.
    """

    slot_code: str
    item_name: str
    price_cents: int
    paid_cents: int
    change: dict[int, int]
    at: datetime

    @property
    def change_cents(self) -> int:
        """Total value of the change handed back."""
        return coin_total(self.change)

    def to_dict(self) -> dict:
        """A plain-dict view of the receipt, safe to serialise to JSON."""
        return {
            "slot_code": self.slot_code,
            "item_name": self.item_name,
            "price_cents": self.price_cents,
            "paid_cents": self.paid_cents,
            "change": {str(coin): count for coin, count in self.change.items()},
            "at": self.at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Purchase":
        """Rebuild a receipt from :meth:`to_dict` output."""
        return cls(
            slot_code=data["slot_code"],
            item_name=data["item_name"],
            price_cents=int(data["price_cents"]),
            paid_cents=int(data["paid_cents"]),
            change={int(coin): int(count) for coin, count in data.get("change", {}).items()},
            at=datetime.fromisoformat(data["at"]),
        )


class VendingMachine:
    """A vending machine.

    :param inventory: the slots to start with; a fresh empty one by default.
    :param coin_bank: coins available for change at power-on.
    :param service_pin: the PIN :meth:`unlock` expects.
    :param clock: a zero-argument callable returning a :class:`~datetime.datetime`,
        used to timestamp sales.
    """

    def __init__(
        self,
        inventory: Inventory | None = None,
        coin_bank: Mapping[int, int] | None = None,
        service_pin: str = DEFAULT_SERVICE_PIN,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self.inventory = inventory if inventory is not None else Inventory()
        self._bank: dict[int, int] = {}
        self._inserted: dict[int, int] = {}
        self._sales: list[Purchase] = []
        self._service_pin = str(service_pin)
        self._unlocked = False
        self._clock = clock or _utc_now
        if coin_bank:
            for coin, count in coin_bank.items():
                validate_coin(int(coin))
                if int(count) < 0:
                    raise ValueError(f"Coin count must not be negative: {coin}={count}")
            self._bank = add_coins({}, coin_bank)

    # ---------------------------------------------------------------- state

    @property
    def credit_cents(self) -> int:
        """Value of the coins the customer has inserted and not spent."""
        with self._lock:
            return coin_total(self._inserted)

    @property
    def credit(self) -> str:
        """Inserted credit as a display string, e.g. ``"$1.25"``."""
        return format_price(self.credit_cents)

    @property
    def inserted_coins(self) -> dict[int, int]:
        """A copy of the coins currently held in the escrow."""
        with self._lock:
            return dict(self._inserted)

    @property
    def coin_bank(self) -> dict[int, int]:
        """A copy of the coins available for making change."""
        with self._lock:
            return dict(self._bank)

    @property
    def bank_cents(self) -> int:
        """Total value of the coin bank."""
        return coin_total(self.coin_bank)

    @property
    def is_locked(self) -> bool:
        """Whether service mode is closed."""
        with self._lock:
            return not self._unlocked

    @property
    def sales(self) -> list[Purchase]:
        """A copy of the sales log, oldest first."""
        with self._lock:
            return list(self._sales)

    # ------------------------------------------------------------- customer

    def insert_coin(self, value: int) -> int:
        """Accept one coin and return the new credit in cents.

        :raises InvalidCoinError: if the denomination is not accepted; the coin
            is "returned" and credit is unchanged.
        """
        coin = validate_coin(value)
        with self._lock:
            self._inserted[coin] = self._inserted.get(coin, 0) + 1
            return coin_total(self._inserted)

    def insert_coins(self, *values: int) -> int:
        """Accept several coins in one go and return the new credit in cents.

        Coins are taken in order and an invalid one stops the run, so the coins
        before it stay inserted.
        """
        total = self.credit_cents
        for value in values:
            total = self.insert_coin(value)
        return total

    def refund(self) -> dict[int, int]:
        """Return the inserted coins and clear the credit.

        The exact coins that went in come back out -- the bank is not touched
        -- so refunding never fails.  With no credit, the result is ``{}``.
        """
        with self._lock:
            coins = dict(self._inserted)
            self._inserted = {}
            return dict(sorted(coins.items(), reverse=True))

    def select(self, code: str) -> Purchase:
        """Buy the item in slot ``code`` and return the receipt.

        On success: one item leaves the slot, the inserted coins move into the
        bank, the change comes out of the bank, credit returns to zero and the
        sale is appended to the log.

        :raises InvalidSlotCodeError: the code is malformed.
        :raises SlotNotFoundError: no such slot.
        :raises SoldOutError: the slot is empty.
        :raises InsufficientCreditError: the credit is below the price.
        :raises ExactChangeError: the bank cannot make the change owed.
        """
        with self._lock:
            slot = self.inventory.get_slot(code)
            if slot.is_sold_out:
                raise SoldOutError(f"Slot {slot.code} ({slot.name}) is sold out")

            paid = coin_total(self._inserted)
            if paid < slot.price_cents:
                raise InsufficientCreditError(
                    f"Slot {slot.code} ({slot.name}) costs {format_price(slot.price_cents)}, "
                    f"credit is {format_price(paid)}"
                )

            owed = paid - slot.price_cents
            after_payment = add_coins(self._bank, self._inserted)
            try:
                change = make_change(owed, after_payment)
            except ExactChangeError:
                raise ExactChangeError(
                    f"Cannot return {format_price(owed)} in change. "
                    f"Insert exact payment of {format_price(slot.price_cents)} or press refund"
                ) from None

            self.inventory.dispense(slot.code)
            self._bank = add_coins(after_payment, {coin: -count for coin, count in change.items()})
            self._inserted = {}

            purchase = Purchase(
                slot_code=slot.code,
                item_name=slot.name,
                price_cents=slot.price_cents,
                paid_cents=paid,
                change=change,
                at=self._clock(),
            )
            self._sales.append(purchase)
            return purchase

    # -------------------------------------------------------------- service

    def unlock(self, pin: str) -> None:
        """Open service mode.

        :raises MachineLockedError: if the PIN is wrong; the machine stays
            locked.
        """
        with self._lock:
            if str(pin) != self._service_pin:
                raise MachineLockedError("Incorrect service PIN")
            self._unlocked = True

    def lock(self) -> None:
        """Close service mode.  Locking an already-locked machine is fine."""
        with self._lock:
            self._unlocked = False

    def _require_service_mode(self, what: str) -> None:
        if not self._unlocked:
            raise MachineLockedError(f"{what} requires service mode; unlock the machine first")

    def add_slot(
        self,
        code: str,
        name: str,
        price_cents: int,
        quantity: int = 0,
        capacity: int = DEFAULT_CAPACITY,
    ) -> Slot:
        """Install a new slot.  Service mode only."""
        with self._lock:
            self._require_service_mode("Adding a slot")
            return self.inventory.add_slot(code, name, price_cents, quantity, capacity)

    def restock(self, code: str, quantity: int = 1) -> Slot:
        """Add items to a slot.  Service mode only."""
        with self._lock:
            self._require_service_mode("Restocking")
            return self.inventory.restock(code, quantity)

    def load_coins(self, coins: Mapping[int, int]) -> dict[int, int]:
        """Put change into the coin bank and return the bank's new contents.

        Service mode only.  Counts must be positive; use :meth:`collect_cash`
        to take money out.
        """
        with self._lock:
            self._require_service_mode("Loading coins")
            for coin, count in coins.items():
                validate_coin(int(coin))
                if int(count) < 1:
                    raise ValueError(f"Coin count must be positive: {coin}={count}")
            self._bank = add_coins(self._bank, coins)
            return dict(self._bank)

    def collect_cash(self) -> dict[int, int]:
        """Empty the coin bank and return what was in it.  Service mode only.

        Inserted credit belongs to the customer and is never collected.
        """
        with self._lock:
            self._require_service_mode("Collecting cash")
            coins = dict(self._bank)
            self._bank = {}
            return dict(sorted(coins.items(), reverse=True))

    def set_service_pin(self, current_pin: str, new_pin: str) -> None:
        """Change the service PIN.

        :raises MachineLockedError: if ``current_pin`` is wrong.
        :raises ValueError: if the new PIN is not four digits.
        """
        with self._lock:
            if str(current_pin) != self._service_pin:
                raise MachineLockedError("Incorrect service PIN")
            candidate = str(new_pin)
            if len(candidate) != 4 or not candidate.isdigit():
                raise ValueError("Service PIN must be exactly four digits")
            self._service_pin = candidate

    # --------------------------------------------------------------- report

    def revenue_cents(self) -> int:
        """Total value of everything sold since the log was last cleared."""
        with self._lock:
            return sum(sale.price_cents for sale in self._sales)

    def sales_report(self) -> dict:
        """A summary of the sales log.

        Returns a dict with ``items_sold``, ``revenue_cents``, ``revenue``
        (formatted) and ``by_item`` -- a mapping of product name to
        ``{"count": ..., "revenue_cents": ...}``, ordered by revenue, highest
        first.
        """
        with self._lock:
            by_item: dict[str, dict[str, int]] = {}
            for sale in self._sales:
                entry = by_item.setdefault(sale.item_name, {"count": 0, "revenue_cents": 0})
                entry["count"] += 1
                entry["revenue_cents"] += sale.price_cents
            ranked = dict(
                sorted(by_item.items(), key=lambda kv: (-kv[1]["revenue_cents"], kv[0]))
            )
            revenue = sum(sale.price_cents for sale in self._sales)
            return {
                "items_sold": len(self._sales),
                "revenue_cents": revenue,
                "revenue": format_price(revenue),
                "by_item": ranked,
            }

    def clear_sales(self) -> int:
        """Wipe the sales log and return how many entries were removed.

        Service mode only.
        """
        with self._lock:
            self._require_service_mode("Clearing the sales log")
            count = len(self._sales)
            self._sales = []
            return count

    def status(self) -> dict:
        """A snapshot of everything a display panel would show."""
        with self._lock:
            return {
                "credit_cents": self.credit_cents,
                "credit": self.credit,
                "locked": self.is_locked,
                "bank_cents": self.bank_cents,
                "slots": len(self.inventory),
                "items": self.inventory.total_items(),
                "items_sold": len(self._sales),
                "revenue_cents": self.revenue_cents(),
            }

    # ---------------------------------------------------------- persistence

    def to_dict(self) -> dict:
        """A plain-dict view of the whole machine, safe to serialise to JSON.

        Service mode is deliberately *not* part of the snapshot: a machine
        restored from disk always comes back locked.
        """
        with self._lock:
            return {
                "inventory": self.inventory.to_dict(),
                "coin_bank": {str(coin): count for coin, count in self._bank.items()},
                "inserted": {str(coin): count for coin, count in self._inserted.items()},
                "sales": [sale.to_dict() for sale in self._sales],
                "service_pin": self._service_pin,
            }

    @classmethod
    def from_dict(cls, data: dict, clock: Callable[[], datetime] | None = None) -> "VendingMachine":
        """Rebuild a machine from :meth:`to_dict` output."""
        machine = cls(
            inventory=Inventory.from_dict(data.get("inventory", {})),
            service_pin=str(data.get("service_pin", DEFAULT_SERVICE_PIN)),
            clock=clock,
        )
        machine._bank = {int(c): int(n) for c, n in data.get("coin_bank", {}).items()}
        machine._inserted = {int(c): int(n) for c, n in data.get("inserted", {}).items()}
        machine._sales = [Purchase.from_dict(raw) for raw in data.get("sales", [])]
        return machine


def demo_machine(clock: Callable[[], datetime] | None = None) -> VendingMachine:
    """A machine stocked with six products and a modest float of change.

    Handy as a starting point: PIN ``1234``, every slot stocked, and a coin
    bank that can make change for most -- but deliberately not all -- payments.
    """
    inventory = Inventory()
    inventory.add_slot("A1", "Salted Crisps", 125, quantity=5)
    inventory.add_slot("A2", "Chocolate Bar", 150, quantity=4)
    inventory.add_slot("B1", "Still Water", 100, quantity=8, capacity=12)
    inventory.add_slot("B2", "Cola", 175, quantity=6)
    inventory.add_slot("C1", "Trail Mix", 225, quantity=2)
    inventory.add_slot("C2", "Energy Drink", 250, quantity=0)
    return VendingMachine(
        inventory=inventory,
        coin_bank={25: 8, 10: 5, 5: 4, 100: 2},
        service_pin="1234",
        clock=clock,
    )
