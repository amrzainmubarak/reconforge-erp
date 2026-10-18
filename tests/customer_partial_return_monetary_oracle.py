"""Independent Fraction reference for captured monetary-return witnesses.

This is test-side arithmetic, not a posting engine or native source admission.
It neither imports production money/FX/FIFO code nor invents an original rate,
tax amount, journal, account, authorization, or database ownership proof.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from fractions import Fraction

MAX_MINOR = 9_000_000_000_000_000_000


class MonetaryOracleError(ValueError):
    """Captured reference inputs are malformed or do not conserve their prefix."""


def integer(value: object, *, positive: bool = False) -> int:
    if type(value) is not int or not (1 if positive else 0) <= value <= MAX_MINOR:
        raise MonetaryOracleError("An exact bounded integer is required")
    return value


def nearest(value: Fraction, *, half_even: bool = False) -> int:
    """Choose a nearest integer by exact distances, with an explicit tie rule."""
    if type(value) is not Fraction or value < 0 or type(half_even) is not bool:
        raise MonetaryOracleError("A nonnegative exact fraction is required")
    low = value.numerator // value.denominator
    choices = (low, low + 1)
    result = min(choices, key=lambda n: (abs(value - n), n % 2 if half_even else -n))
    return integer(result)


def portion(value: int, remaining: int, selected: int, *, fifo: bool = False) -> int:
    integer(value)
    integer(remaining, positive=True)
    integer(selected)
    if type(fifo) is not bool or selected > remaining:
        raise MonetaryOracleError("The selected quantity exceeds its retained prefix")
    if selected == remaining:
        return value
    return nearest(Fraction(value * selected, remaining), half_even=fifo)


def _pairs(values: object, *, maximum: int) -> tuple[tuple[int, int], ...]:
    if type(values) is not tuple or not 1 <= len(values) <= maximum:
        raise MonetaryOracleError("A finite tuple of captured pairs is required")
    for pair in values:
        if type(pair) is not tuple or len(pair) != 2:
            raise MonetaryOracleError("Each captured pair must be closed")
        for value in pair:
            integer(value)
    return values


@dataclass(frozen=True)
class CreditWitness:
    component_cuts: tuple[tuple[int, int], ...]
    remaining_components: tuple[tuple[int, int], ...]
    fifo_cuts: tuple[tuple[int, int, int], ...]
    remaining_fifo: tuple[tuple[int, int], ...]
    foreign_credit: int
    functional_credit: int
    foreign_ar_release: int
    functional_ar_release: int
    foreign_liability: int
    functional_liability: int
    alignment_gain: int
    alignment_loss: int
    restored_cost: int
    functional_credit_journal_turnover: int


def reference_credit(*, remaining_quantity: int, selected_quantity: int,
                     components: tuple[tuple[int, int], ...],
                     fifo: tuple[tuple[int, int], ...], ar_foreign: int,
                     ar_functional: int) -> CreditWitness:
    """Re-derive a credit from actual before-values, never from per-unit FX."""
    integer(remaining_quantity, positive=True)
    integer(selected_quantity, positive=True)
    components = _pairs(components, maximum=9)  # One net and at most eight taxes.
    fifo = _pairs(fifo, maximum=32)
    integer(ar_foreign)
    integer(ar_functional)
    if (selected_quantity > remaining_quantity or sum(q for q, _ in fifo) != remaining_quantity
            or any(q == 0 and v != 0 for q, v in fifo)
            or ar_foreign > sum(f for f, _ in components)
            or ar_foreign == 0 and ar_functional != 0):
        raise MonetaryOracleError("The captured original/carrying prefix is inconsistent")
    integer(sum(f for f, _ in components))
    integer(sum(v for _, v in components))
    cuts = tuple((portion(f, remaining_quantity, selected_quantity),
                  portion(v, remaining_quantity, selected_quantity)) for f, v in components)
    left = tuple((f - df, v - dv) for (f, v), (df, dv) in zip(components, cuts, strict=True))
    foreign, functional = sum(f for f, _ in cuts), sum(v for _, v in cuts)
    af = min(foreign, ar_foreign)
    al = portion(ar_functional, ar_foreign, af) if af else 0
    ef = foreign - af
    el = portion(functional, foreign, ef) if ef else 0
    difference = functional - al - el
    fifo_left, fifo_cuts, pending = [], [], selected_quantity
    for index, (quantity, value) in enumerate(fifo):
        take = min(quantity, pending)
        restored = portion(value, quantity, take, fifo=True) if take else 0
        if take:
            fifo_cuts.append((index, take, restored))
        fifo_left.append((quantity - take, value - restored))
        pending -= take
    if pending:
        raise MonetaryOracleError("Returned quantity has no original FIFO membership")
    gain, loss = max(difference, 0), max(-difference, 0)
    cost = integer(sum(value for _, _, value in fifo_cuts))
    turnover = integer(functional + loss)
    if (ar_foreign - af == 0 and ar_functional - al != 0
            or ef == 0 and el != 0 or functional + loss != al + el + gain):
        raise MonetaryOracleError("The carrying/credit split leaves an unexplained remainder")
    return CreditWitness(cuts, left, tuple(fifo_cuts), tuple(fifo_left), foreign, functional,
                         af, al, ef, el, gain, loss, cost, turnover)


def converted_cash(amount: int, *, foreign_scale: int, functional_scale: int,
                   quote_per_foreign: str) -> int:
    integer(amount, positive=True)
    if (type(foreign_scale) is not int or type(functional_scale) is not int
            or not 0 <= foreign_scale <= 8 or not 0 <= functional_scale <= 8
            or type(quote_per_foreign) is not str or len(quote_per_foreign) > 96
            or re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", quote_per_foreign, re.ASCII) is None):
        raise MonetaryOracleError("An exact captured rate and currency scales are required")
    rate = Fraction(quote_per_foreign)
    if rate <= 0:
        raise MonetaryOracleError("The captured rate must be positive")
    return nearest(Fraction(amount * 10 ** functional_scale, 10 ** foreign_scale) * rate)


@dataclass(frozen=True)
class CashWitness:
    foreign_released: int
    functional_released: int
    functional_cash: int
    fx_gain: int
    fx_loss: int
    remaining_foreign: int
    remaining_functional: int
    journal_turnover: int


def reference_cash(*, carrying_foreign: int, carrying_functional: int,
                   selected_foreign: int, functional_cash: int, refund: bool) -> CashWitness:
    integer(carrying_foreign, positive=True)
    integer(carrying_functional)
    integer(selected_foreign, positive=True)
    integer(functional_cash)
    if type(refund) is not bool or selected_foreign > carrying_foreign:
        raise MonetaryOracleError("An exact bounded cash direction/amount is required")
    released = portion(carrying_functional, carrying_foreign, selected_foreign)
    difference = released - functional_cash if refund else functional_cash - released
    return CashWitness(selected_foreign, released, functional_cash, max(difference, 0),
                       max(-difference, 0), carrying_foreign - selected_foreign,
                       carrying_functional - released, max(released, functional_cash))
