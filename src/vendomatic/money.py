"""Money: parsing, formatting and making change.

Every amount in Vendomatic is an ``int`` number of **cents**.  Floating point
never touches money here -- ``0.1 + 0.2`` is not ``0.3`` and a vending machine
that believes otherwise will eventually short-change somebody.

The module is pure: no state, no I/O, no clock.  Each function takes values in
and gives values back.

Accepted coins
--------------
``COIN_VALUES`` is ``(5, 10, 25, 100)`` -- nickel, dime, quarter, dollar coin.
Anything else offered to the machine is rejected with
:class:`~vendomatic.errors.InvalidCoinError`.

A *coin purse* is a mapping of coin value to how many of that coin are held,
e.g. ``{25: 4, 10: 1}`` is four quarters and a dime, worth 110 cents.  Purses
are plain dicts, so they can be compared, merged and serialised freely.
"""

from __future__ import annotations

import re
from typing import Mapping

from .errors import ExactChangeError, InvalidCoinError, InvalidPriceError

__all__ = [
    "COIN_VALUES",
    "parse_price",
    "format_price",
    "is_valid_coin",
    "validate_coin",
    "coin_total",
    "add_coins",
    "make_change",
]

#: Coin denominations the machine accepts, smallest first.
COIN_VALUES: tuple[int, ...] = (5, 10, 25, 100)

_PRICE_PATTERN = re.compile(r"^\$?(\d+)(?:\.(\d{1,2}))?$")


def parse_price(text: str | int | float) -> int:
    """Convert a human-written price to an integer number of cents.

    Accepts an optional leading ``$``, an optional decimal part of one or two
    digits, and surrounding whitespace::

        parse_price("1.25")   -> 125
        parse_price("$0.75")  -> 75
        parse_price(" 2 ")    -> 200
        parse_price("1.5")    -> 150

    An ``int`` is taken to be a whole currency unit, so ``parse_price(2)`` is
    ``200`` cents -- the same as ``parse_price("2")``.

    :raises InvalidPriceError: on an unparseable string, a negative amount, or
        a fractional value finer than one cent.
    """
    if isinstance(text, bool):  # bool is an int; refuse it explicitly
        raise InvalidPriceError(f"Invalid price: {text!r}")
    if isinstance(text, int):
        if text < 0:
            raise InvalidPriceError(f"Invalid price: {text!r}")
        return text * 100
    if isinstance(text, float):
        cents = round(text * 100)
        if abs(text * 100 - cents) > 1e-6 or text < 0:
            raise InvalidPriceError(f"Invalid price: {text!r}")
        return int(cents)

    if not isinstance(text, str):
        raise InvalidPriceError(f"Invalid price: {text!r}")

    match = _PRICE_PATTERN.match(text.strip())
    if match is None:
        raise InvalidPriceError(f"Invalid price: {text!r}")

    whole, fraction = match.groups()
    fraction = (fraction or "0").ljust(2, "0")
    return int(whole) * 100 + int(fraction)


def format_price(cents: int) -> str:
    """Render an integer number of cents as ``"$1.25"``.

    Negative amounts keep the sign outside the symbol: ``-5`` becomes
    ``"-$0.05"``.
    """
    cents = int(cents)
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}${cents // 100}.{cents % 100:02d}"


def is_valid_coin(value: object) -> bool:
    """Return whether ``value`` is a denomination the machine accepts."""
    return isinstance(value, int) and not isinstance(value, bool) and value in COIN_VALUES


def validate_coin(value: object) -> int:
    """Return ``value`` as an accepted coin, or raise.

    :raises InvalidCoinError: if the denomination is not in :data:`COIN_VALUES`.
    """
    if not is_valid_coin(value):
        accepted = ", ".join(format_price(c) for c in COIN_VALUES)
        raise InvalidCoinError(f"Coin not accepted: {value!r}. Accepted coins: {accepted}")
    return int(value)


def coin_total(purse: Mapping[int, int]) -> int:
    """Sum a coin purse into a total number of cents.

    An empty purse is worth ``0``.  Counts are assumed non-negative; coin
    values are not validated here, so this also works on historical purses
    read back from a file.
    """
    return sum(int(coin) * int(count) for coin, count in purse.items())


def add_coins(purse: Mapping[int, int], other: Mapping[int, int]) -> dict[int, int]:
    """Merge two coin purses into a new one, summing the counts.

    Neither argument is modified.  Denominations that end up at zero are kept
    out of the result, so ``add_coins({25: 1}, {25: -1})`` is ``{}``.
    """
    merged: dict[int, int] = {}
    for source in (purse, other):
        for coin, count in source.items():
            merged[int(coin)] = merged.get(int(coin), 0) + int(count)
    return {coin: count for coin, count in sorted(merged.items(), reverse=True) if count != 0}


def make_change(amount_cents: int, available: Mapping[int, int] | None = None) -> dict[int, int]:
    """Work out which coins to pay back for ``amount_cents``.

    The result is a coin purse using the **fewest coins possible** drawn from
    ``available``.  Pass ``available=None`` for a machine with an unlimited
    supply of every denomination.

        make_change(40)                     -> {25: 1, 10: 1, 5: 1}
        make_change(40, {25: 0, 10: 4})     -> {10: 4}

    The second example is the interesting one: a greedy "always take the
    biggest coin" strategy would take a quarter it does not have, or strand
    itself needing a nickel.  This function searches, so it finds ``{10: 4}``
    whenever such a combination exists at all.

    :raises ValueError: if ``amount_cents`` is negative.
    :raises InvalidCoinError: if ``available`` mentions a denomination the
        machine does not accept.
    :raises ExactChangeError: if no combination of the available coins adds up
        to exactly ``amount_cents``.
    """
    amount = int(amount_cents)
    if amount < 0:
        raise ValueError(f"Cannot make change for a negative amount: {amount_cents!r}")
    if amount == 0:
        return {}

    if available is None:
        limits = {coin: amount // coin for coin in COIN_VALUES}
    else:
        limits = {}
        for coin, count in available.items():
            validate_coin(int(coin))
            if int(count) > 0:
                limits[int(coin)] = int(count)

    # Bounded-coin dynamic programme: one layer per denomination, each layer
    # deciding how many of that coin to use.  `best[a]` is the fewest coins
    # that reach exactly `a` cents using the denominations seen so far.
    unreachable = float("inf")
    best: list[float] = [unreachable] * (amount + 1)
    combos: list[dict[int, int] | None] = [None] * (amount + 1)
    best[0] = 0
    combos[0] = {}

    for coin in sorted(limits, reverse=True):
        limit = limits[coin]
        next_best = list(best)
        next_combos = list(combos)
        for subtotal in range(amount + 1):
            if best[subtotal] == unreachable:
                continue
            for used in range(1, limit + 1):
                reached = subtotal + coin * used
                if reached > amount:
                    break
                candidate = best[subtotal] + used
                if candidate < next_best[reached]:
                    next_best[reached] = candidate
                    combo = dict(combos[subtotal] or {})
                    combo[coin] = combo.get(coin, 0) + used
                    next_combos[reached] = combo
        best, combos = next_best, next_combos

    result = combos[amount]
    if result is None:
        raise ExactChangeError(f"Cannot make exact change for {format_price(amount)}")
    return dict(sorted(result.items(), reverse=True))
