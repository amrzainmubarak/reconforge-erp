"""Independent rational oracle for the versioned remaining-original return policy.

No production imports, Decimal context, binary floating point, SQL, or browser.
This models ordered synthetic facts; native custody and authorization are separate.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Literal, cast

POLICY = "remaining-original-v1"


class RemainderRefusal(ValueError):
    pass


def require(condition: bool) -> None:
    if not condition:
        raise RemainderRefusal("Independent remainder witness refused.")


def amount(value: int, *, positive: bool = False) -> int:
    require(type(value) is int and value >= (1 if positive else 0))
    return value


def identifier(value: str) -> str:
    require(type(value) is str and bool(value.strip()))
    return value


def nearest(value: Fraction, tie: Literal["HALF_UP", "HALF_EVEN"]) -> int:
    """Select the nearest neighboring integer by exact distances, then the captured tie rule."""
    require(type(value) is Fraction and value >= 0 and tie in ("HALF_UP", "HALF_EVEN"))
    lower = value.numerator // value.denominator
    upper = lower + 1
    low_distance, high_distance = value - lower, upper - value
    if low_distance < high_distance:
        return lower
    if high_distance < low_distance:
        return upper
    return upper if tie == "HALF_UP" or lower % 2 else lower


@dataclass(frozen=True)
class Consumption:
    id: str
    quantity_scaled: int
    value_minor: int

    def __post_init__(self) -> None:
        identifier(self.id)
        amount(self.quantity_scaled, positive=True)
        amount(self.value_minor, positive=True)


@dataclass(frozen=True)
class Birth:
    quantity_scaled: int
    revenue_minor: int
    collected_minor: int
    consumptions: tuple[Consumption, ...]
    source_fingerprint: str
    allocation_policy: str
    revenue_rounding: str
    fifo_rounding: str

    def __post_init__(self) -> None:
        amount(self.quantity_scaled, positive=True)
        amount(self.revenue_minor, positive=True)
        amount(self.collected_minor)
        require(self.collected_minor <= self.revenue_minor and type(self.consumptions) is tuple
                and 0 < len(self.consumptions) <= 32 and all(type(c) is Consumption for c in self.consumptions))
        require(sum(c.quantity_scaled for c in self.consumptions) == self.quantity_scaled
                and len({c.id for c in self.consumptions}) == len(self.consumptions))
        require(type(self.source_fingerprint) is str and len(self.source_fingerprint) == 64
                and all(c in "0123456789abcdef" for c in self.source_fingerprint))
        require(self.allocation_policy == POLICY and self.revenue_rounding == "HALF_UP"
                and self.fifo_rounding == "HALF_EVEN")


@dataclass(frozen=True)
class Portion:
    consumption_id: str
    offset_quantity_scaled: int
    quantity_scaled: int
    value_minor: int
    before_quantity_scaled: int
    before_value_minor: int

    def __post_init__(self) -> None:
        identifier(self.consumption_id)
        amount(self.offset_quantity_scaled)
        amount(self.quantity_scaled, positive=True)
        amount(self.value_minor)
        amount(self.before_quantity_scaled, positive=True)
        amount(self.before_value_minor)
        require(self.quantity_scaled <= self.before_quantity_scaled and self.value_minor <= self.before_value_minor)


@dataclass(frozen=True)
class ReturnWitness:
    id: str
    source_fingerprint: str
    allocation_policy: str
    history_version: int
    quantity_scaled: int
    credit_minor: int
    cost_minor: int
    receivable_released_minor: int
    refund_delta_minor: int
    revenue_before_quantity_scaled: int
    revenue_before_value_minor: int
    portions: tuple[Portion, ...]

    def __post_init__(self) -> None:
        identifier(self.id)
        for value in (self.history_version, self.credit_minor, self.cost_minor,
                      self.receivable_released_minor, self.refund_delta_minor, self.revenue_before_value_minor):
            amount(value)
        amount(self.quantity_scaled, positive=True)
        amount(self.revenue_before_quantity_scaled, positive=True)
        require(type(self.portions) is tuple and all(type(p) is Portion for p in self.portions)
                and sum(p.quantity_scaled for p in self.portions) == self.quantity_scaled
                and sum(p.value_minor for p in self.portions) == self.cost_minor
                and self.receivable_released_minor + self.refund_delta_minor == self.credit_minor)


Line = tuple[str, int, int]
Entry = tuple[str, tuple[Line, ...]]


def return_entries(witness: ReturnWitness, *, reverse: bool = False) -> tuple[Entry, ...]:
    entries: list[Entry] = []
    if witness.credit_minor:
        lines: list[Line] = [("REVENUE", witness.credit_minor, 0)]
        if witness.receivable_released_minor:
            lines.append(("AR", 0, witness.receivable_released_minor))
        if witness.refund_delta_minor:
            lines.append(("REFUND", 0, witness.refund_delta_minor))
        entries.append(("RevenueCredit", tuple(lines)))
    if witness.cost_minor:
        entries.append(("CostRestoration", (("INVENTORY", witness.cost_minor, 0), ("COGS", 0, witness.cost_minor))))
    if reverse:
        return tuple(("Reverse" + purpose, tuple((code, right, left) for code, left, right in lines)) for purpose, lines in entries)
    return tuple(entries)


@dataclass(frozen=True)
class Event:
    id: str
    kind: Literal["Return", "Collection", "Refund"]
    amount_minor: int = 0
    witness: ReturnWitness | None = None


class History:
    """Exact ordered history with immutable original cuts and latest-active reversal."""

    def __init__(self, birth: Birth):
        require(type(birth) is Birth)
        self.birth = birth
        self.version = 0
        self.returned = self.credited = self.restored_cost = self.refunded = 0
        self.collected = birth.collected_minor
        self.remaining = tuple((c.quantity_scaled, c.value_minor) for c in birth.consumptions)
        self.active: tuple[Event, ...] = ()
        self.seen: frozenset[str] = frozenset()

    def _admit(self, operation_id: str, expected_version: int) -> None:
        identifier(operation_id)
        amount(expected_version)
        require(operation_id not in self.seen and expected_version == self.version and self.version < 256)

    def _record(self, operation_id: str) -> None:
        self.seen |= {operation_id}
        self.version += 1

    @property
    def outstanding(self) -> int:
        return max(self.birth.revenue_minor - self.collected - self.credited, 0)

    @property
    def refund_due(self) -> int:
        return max(self.collected + self.credited - self.birth.revenue_minor, 0) - self.refunded

    def propose_return(self, operation_id: str, quantity_scaled: int, expected_version: int) -> ReturnWitness:
        self._admit(operation_id, expected_version)
        amount(quantity_scaled, positive=True)
        before_q, before_v = self.birth.quantity_scaled - self.returned, self.birth.revenue_minor - self.credited
        require(quantity_scaled <= before_q)
        credit = nearest(Fraction(before_v * quantity_scaled, before_q), "HALF_UP")
        unassigned = quantity_scaled
        portions = []
        for original, (remaining_q, remaining_v) in zip(self.birth.consumptions, self.remaining, strict=True):
            if unassigned and remaining_q:
                take = min(unassigned, remaining_q)
                value = nearest(Fraction(remaining_v * take, remaining_q), "HALF_EVEN")
                portions.append(Portion(original.id, original.quantity_scaled - remaining_q, take, value, remaining_q, remaining_v))
                unassigned -= take
        require(unassigned == 0)
        release = min(credit, self.outstanding)
        return ReturnWitness(operation_id, self.birth.source_fingerprint, POLICY, self.version, quantity_scaled,
                             credit, sum(p.value_minor for p in portions), release, credit - release,
                             before_q, before_v, tuple(portions))

    def post_return(self, witness: ReturnWitness) -> None:
        require(type(witness) is ReturnWitness
                and witness == self.propose_return(witness.id, witness.quantity_scaled, witness.history_version))
        remaining = dict(zip((c.id for c in self.birth.consumptions), self.remaining, strict=True))
        for portion in witness.portions:
            require(remaining[portion.consumption_id] == (portion.before_quantity_scaled, portion.before_value_minor))
            remaining[portion.consumption_id] = (portion.before_quantity_scaled - portion.quantity_scaled,
                                                 portion.before_value_minor - portion.value_minor)
        self.remaining = tuple(remaining[c.id] for c in self.birth.consumptions)
        self.returned += witness.quantity_scaled
        self.credited += witness.credit_minor
        self.restored_cost += witness.cost_minor
        self.active += (Event(witness.id, "Return", witness=witness),)
        self._record(witness.id)

    def collect(self, operation_id: str, value: int, expected_version: int) -> None:
        self._admit(operation_id, expected_version)
        amount(value, positive=True)
        require(value <= self.outstanding)
        self.collected += value
        self.active += (Event(operation_id, "Collection", value),)
        self._record(operation_id)

    def refund(self, operation_id: str, return_id: str, value: int, expected_version: int) -> None:
        self._admit(operation_id, expected_version)
        amount(value, positive=True)
        require(any(event.id == return_id and event.kind == "Return" for event in self.active) and value <= self.refund_due)
        self.refunded += value
        self.active += (Event(operation_id, "Refund", value),)
        self._record(operation_id)

    def reverse_latest(self, operation_id: str, original_id: str, expected_version: int) -> Event:
        self._admit(operation_id, expected_version)
        require(bool(self.active) and self.active[-1].id == original_id and self.active[-1].kind in ("Return", "Refund"))
        original = self.active[-1]
        if original.kind == "Return":
            require(original.witness is not None)
            witness = cast(ReturnWitness, original.witness)
            remaining = dict(zip((c.id for c in self.birth.consumptions), self.remaining, strict=True))
            for portion in witness.portions:
                require(remaining[portion.consumption_id] == (portion.before_quantity_scaled - portion.quantity_scaled,
                                                             portion.before_value_minor - portion.value_minor))
                remaining[portion.consumption_id] = (portion.before_quantity_scaled, portion.before_value_minor)
            self.remaining = tuple(remaining[c.id] for c in self.birth.consumptions)
            self.returned -= witness.quantity_scaled
            self.credited -= witness.credit_minor
            self.restored_cost -= witness.cost_minor
        else:
            self.refunded -= original.amount_minor
        self.active = self.active[:-1]
        self._record(operation_id)
        return original
