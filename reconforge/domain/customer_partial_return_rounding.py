"""Versioned remaining-original allocation; factual source v1 stays unchanged.

The immutable source-birth policy applies only to new native v2 owners. Original
consumption values are replayed from signed history, never from current physical
layers. Zero financial legs still retain positive physical quantities/history.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from typing import Any, Literal, NoReturn

from reconforge.domain.customer_partial_returns import (
    MAX_CONSUMPTIONS,
    MAX_HISTORY_EVENTS,
    OriginalPartialReturnSource,
    PartialReturnBalance,
    _digest,
    _integer,
    _ref,
)
from reconforge.domain.finance_posting import FinancePostingError, canonical_json, digest_payload
from reconforge.domain.inventory_costing import allocate_fifo_value
from reconforge.utils.money import Money

ALLOCATION_POLICY = "remaining-original-v1"
CONTRACT_VERSION = "customer-partial-return-domain-v2"


def _refuse() -> NoReturn:
    raise FinancePostingError("partial_return_rounding_invalid", "Remaining-original allocation evidence refused.")


@dataclass(frozen=True, slots=True)
class RemainingConsumptionPortion:
    position: int
    original_consumption_id: str
    original_valuation_line_id: str
    cost_layer_id: str
    offset_quantity_scaled: int
    quantity_scaled: int
    value_minor: int
    before_quantity_scaled: int
    before_value_minor: int

    def __post_init__(self) -> None:
        _integer(self.position, "original position", maximum=MAX_CONSUMPTIONS)
        for key in ("original_consumption_id", "original_valuation_line_id", "cost_layer_id"):
            _ref(getattr(self, key), key)
        for key in ("quantity_scaled", "before_quantity_scaled"):
            _integer(getattr(self, key), key)
        for key in ("offset_quantity_scaled", "value_minor", "before_value_minor"):
            _integer(getattr(self, key), key, zero=True)
        if self.quantity_scaled > self.before_quantity_scaled or self.value_minor > self.before_value_minor:
            _refuse()


@dataclass(frozen=True, slots=True)
class RemainingReturnValues:
    quantity_before_scaled: int
    quantity_scaled: int
    returned_quantity_scaled: int
    credit_minor: int
    cogs_restored_minor: int
    receivable_released_minor: int
    refund_entitlement_delta_minor: int
    outstanding_after_minor: int
    portions: tuple[RemainingConsumptionPortion, ...]
    allocation_policy: str
    revenue_before_quantity_scaled: int
    revenue_before_value_minor: int

    def __post_init__(self) -> None:
        for key in (field.name for field in fields(RemainingReturnValues)):
            if key in {"portions", "allocation_policy"}:
                continue
            _integer(getattr(self, key), key, zero=key not in {
                "quantity_scaled", "returned_quantity_scaled", "revenue_before_quantity_scaled"})
        if (self.allocation_policy != ALLOCATION_POLICY or type(self.allocation_policy) is not str
            or type(self.portions) is not tuple or not 1 <= len(self.portions) <= MAX_CONSUMPTIONS):
            _refuse()
        for part in self.portions:
            if type(part) is not RemainingConsumptionPortion:
                _refuse()
            part.__post_init__()


@dataclass(frozen=True, slots=True)
class RemainingReturnEvent:
    kind: Literal["Return", "Collection", "Refund", "ReverseReturn", "ReverseRefund"]
    sequence: int
    source_fingerprint: str
    previous_history_fingerprint: str
    amount_minor: int = 0
    return_values: RemainingReturnValues | None = None
    original_sequence: int | None = None

    def __post_init__(self) -> None:
        if type(self.kind) is not str or self.kind not in {"Return", "Collection", "Refund", "ReverseReturn", "ReverseRefund"}:
            _refuse()
        _integer(self.sequence, "sequence", maximum=MAX_HISTORY_EVENTS)
        _digest(self.source_fingerprint, "source")
        _digest(self.previous_history_fingerprint, "previous history")
        _integer(self.amount_minor, "event amount", zero=self.kind in {"Return", "ReverseReturn"})
        if self.kind in {"Return", "ReverseReturn"}:
            if self.amount_minor != 0 or type(self.return_values) is not RemainingReturnValues:
                _refuse()
            self.return_values.__post_init__()
        elif self.return_values is not None:
            _refuse()
        if self.kind.startswith("Reverse"):
            _integer(self.original_sequence, "original sequence", maximum=MAX_HISTORY_EVENTS)
        elif self.original_sequence is not None:
            _refuse()


@dataclass(frozen=True, slots=True)
class RemainingReturnHistory:
    source: OriginalPartialReturnSource
    events: tuple[RemainingReturnEvent, ...] = ()
    allocation_policy: str = ALLOCATION_POLICY

    def __post_init__(self) -> None:
        if (type(self.source) is not OriginalPartialReturnSource or type(self.events) is not tuple
            or len(self.events) > MAX_HISTORY_EVENTS or type(self.allocation_policy) is not str
            or self.allocation_policy != ALLOCATION_POLICY or any(type(event) is not RemainingReturnEvent for event in self.events)):
            _refuse()


@dataclass(frozen=True, slots=True)
class RemainingReturnPlan(RemainingReturnValues):
    history: RemainingReturnHistory
    source_fingerprint: str
    history_fingerprint: str
    expected_version: int

    @property
    def source(self) -> OriginalPartialReturnSource:
        return self.history.source

    def __post_init__(self) -> None:
        RemainingReturnValues.__post_init__(self)
        if type(self.history) is not RemainingReturnHistory:
            _refuse()
        _digest(self.source_fingerprint, "source")
        _digest(self.history_fingerprint, "history")
        _integer(self.expected_version, "expected version", zero=True, maximum=MAX_HISTORY_EVENTS)

    def payload(self) -> dict[str, Any]:
        self.__post_init__()
        return {"schema_version": CONTRACT_VERSION, "source_fingerprint": self.source_fingerprint,
                "history_fingerprint": self.history_fingerprint, "expected_version": self.expected_version,
                **asdict(_values(self))}

    @property
    def fingerprint(self) -> str:
        return digest_payload(self.payload())


def _values(plan: RemainingReturnValues) -> RemainingReturnValues:
    return RemainingReturnValues(**{field.name: getattr(plan, field.name) for field in fields(RemainingReturnValues)})


def _calculate(source: OriginalPartialReturnSource, returned: int, credited: int, collected: int,
               restored: dict[str, tuple[int, int]], quantity: int) -> RemainingReturnValues:
    _integer(quantity, "return quantity")
    remaining_quantity, remaining_revenue = source.quantity_scaled - returned, source.gross_minor - credited
    if quantity > remaining_quantity:
        raise FinancePostingError("partial_return_quantity_exceeded", "Return exceeds the remaining original delivery.")
    credit = remaining_revenue if quantity == remaining_quantity else Money.from_minor_units(
        remaining_revenue * quantity, source.currency_policy.currency_code,
        registry_context=source.registry_context).divide_exact(remaining_quantity).to_minor_units()
    _integer(credit, "return credit", zero=True)
    pending, portions = quantity, []
    for row in source.consumptions:
        old_quantity, old_value = restored.get(row.consumption_id, (0, 0))
        before_quantity, before_value = row.quantity_scaled - old_quantity, row.value_minor - old_value
        if before_quantity < 0 or before_value < 0 or (before_quantity == 0 and before_value != 0):
            _refuse()
        take = min(pending, before_quantity)
        if take:
            value = allocate_fifo_value(before_value, before_quantity, take, allow_zero=True)
            portions.append(RemainingConsumptionPortion(row.position, row.consumption_id, row.valuation_line_id,
                row.cost_layer_id, old_quantity, take, value, before_quantity, before_value))
            pending -= take
        if not pending:
            break
    if pending:
        _refuse()
    release = min(credit, max(source.gross_minor - credited - collected, 0))
    return RemainingReturnValues(returned, quantity, returned + quantity, credit, sum(part.value_minor for part in portions),
        release, credit - release, max(remaining_revenue - credit - collected, 0), tuple(portions), ALLOCATION_POLICY,
        remaining_quantity, remaining_revenue)


def _replay(history: RemainingReturnHistory) -> tuple[PartialReturnBalance, dict[str, tuple[int, int]]]:
    if type(history) is not RemainingReturnHistory:
        _refuse()
    history.__post_init__()
    source = history.source
    source.__post_init__()
    chain = digest_payload({"contract": CONTRACT_VERSION, "source": source.fingerprint, "allocation_policy": ALLOCATION_POLICY})
    returned = credited = cost = released = liability = refunded = 0
    collected = source.collected_minor
    restored: dict[str, tuple[int, int]] = {}
    active: list[RemainingReturnEvent] = []
    for sequence, event in enumerate(history.events, 1):
        event.__post_init__()
        if event.sequence != sequence or event.source_fingerprint != source.fingerprint or event.previous_history_fingerprint != chain:
            _refuse()
        if event.kind == "Return":
            retained = event.return_values
            if retained is None:
                _refuse()
            values = _calculate(source, returned, credited, collected, restored, retained.quantity_scaled)
            if canonical_json(asdict(retained)) != canonical_json(asdict(values)):
                _refuse()
            returned += values.quantity_scaled
            credited += values.credit_minor
            cost += values.cogs_restored_minor
            released += values.receivable_released_minor
            liability += values.refund_entitlement_delta_minor
            for part in values.portions:
                oldq, oldv = restored.get(part.original_consumption_id, (0, 0))
                restored[part.original_consumption_id] = oldq + part.quantity_scaled, oldv + part.value_minor
            active.append(event)
        elif event.kind == "Collection":
            if event.amount_minor > max(source.gross_minor - credited - collected, 0):
                _refuse()
            collected += event.amount_minor
            active.append(event)
        elif event.kind == "Refund":
            if event.amount_minor > liability - refunded:
                _refuse()
            refunded += event.amount_minor
            active.append(event)
        else:
            if not active or active[-1].sequence != event.original_sequence or event.kind != "Reverse" + active[-1].kind:
                _refuse()
            original = active.pop()
            if event.amount_minor != original.amount_minor or event.return_values != original.return_values:
                _refuse()
            if event.kind == "ReverseRefund":
                refunded -= event.amount_minor
            else:
                reversed_values = event.return_values
                if reversed_values is None or liability - reversed_values.refund_entitlement_delta_minor < refunded:
                    _refuse()
                returned -= reversed_values.quantity_scaled
                credited -= reversed_values.credit_minor
                cost -= reversed_values.cogs_restored_minor
                released -= reversed_values.receivable_released_minor
                liability -= reversed_values.refund_entitlement_delta_minor
                for part in reversed_values.portions:
                    oldq, oldv = restored[part.original_consumption_id]
                    restored[part.original_consumption_id] = oldq - part.quantity_scaled, oldv - part.value_minor
        chain = digest_payload({"previous": chain, "event": asdict(event)})
    return PartialReturnBalance(returned, credited, cost, collected, released, liability, refunded,
        max(source.gross_minor - credited - collected, 0), liability - refunded, chain, len(history.events)), restored


def remaining_return_balance(history: RemainingReturnHistory) -> PartialReturnBalance:
    return _replay(history)[0]


def prepare_remaining_return(history: RemainingReturnHistory, quantity_scaled: int) -> RemainingReturnPlan:
    balance, restored = _replay(history)
    if balance.version >= MAX_HISTORY_EVENTS:
        raise FinancePostingError("partial_return_history_full", "The finite history budget is exhausted.")
    values = _calculate(history.source, balance.returned_quantity_scaled, balance.credited_minor, balance.collected_minor, restored, quantity_scaled)
    return RemainingReturnPlan(**{field.name: getattr(values, field.name) for field in fields(RemainingReturnValues)},
        history=history, source_fingerprint=history.source.fingerprint, history_fingerprint=balance.history_fingerprint, expected_version=balance.version)


def verify_remaining_return_plan(plan: RemainingReturnPlan) -> None:
    if type(plan) is not RemainingReturnPlan:
        _refuse()
    plan.__post_init__()
    if canonical_json(plan.payload()) != canonical_json(prepare_remaining_return(plan.history, plan.quantity_scaled).payload()):
        _refuse()


def _append(history: RemainingReturnHistory, kind: Any, amount: int = 0, values: RemainingReturnValues | None = None,
            original_sequence: int | None = None) -> RemainingReturnHistory:
    balance = remaining_return_balance(history)
    event = RemainingReturnEvent(kind, balance.version + 1, history.source.fingerprint, balance.history_fingerprint,
                                amount, values, original_sequence)
    result = RemainingReturnHistory(history.source, (*history.events, event))
    remaining_return_balance(result)
    return result


def apply_remaining_return(history: RemainingReturnHistory, plan: RemainingReturnPlan) -> RemainingReturnHistory:
    verify_remaining_return_plan(plan)
    current = remaining_return_balance(history)
    if (history.source.fingerprint, current.history_fingerprint, current.version) != (
        plan.source_fingerprint, plan.history_fingerprint, plan.expected_version):
        _refuse()
    return _append(history, "Return", values=_values(plan))


def collect_remaining_return(history: RemainingReturnHistory, amount_minor: int) -> RemainingReturnHistory:
    return _append(history, "Collection", _integer(amount_minor, "collection"))


def refund_remaining_return(history: RemainingReturnHistory, amount_minor: int) -> RemainingReturnHistory:
    return _append(history, "Refund", _integer(amount_minor, "refund"))


def reverse_remaining_return(history: RemainingReturnHistory, original_sequence: int) -> RemainingReturnHistory:
    balance = remaining_return_balance(history)
    _integer(original_sequence, "original sequence", maximum=balance.version)
    original = history.events[original_sequence - 1]
    if original.kind not in {"Return", "Refund"}:
        _refuse()
    return _append(history, "Reverse" + original.kind, original.amount_minor, original.return_values, original_sequence)
