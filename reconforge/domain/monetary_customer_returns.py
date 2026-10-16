"""Ordered dual-currency merchandise corrections over captured native originals.

This module allocates existing original amounts. Money owns revenue rounding,
the FIFO allocator owns cost rounding, and the FX owner owns spot conversion.
The native owner must bind every identity, policy and before-value witness to
its actual reviewed source; these immutable values grant no posting authority.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields, replace
from typing import Any, Literal, NoReturn

from reconforge.domain.customer_partial_returns import MAX_CONSUMPTIONS, MAX_HISTORY_EVENTS, _digest, _ref
from reconforge.domain.finance_policy import FinanceCurrencyPolicy
from reconforge.domain.finance_posting import FinancePostingError, canonical_json, digest_payload
from reconforge.domain.inventory_costing import allocate_fifo_value
from reconforge.domain.operational_fx_tax import HistoricalRate, canonical_day, convert_minor, exact_minor
from reconforge.utils.money import CurrencyRegistryContext, Money

ALLOCATION_POLICY = "remaining-dual-currency-v1"
ALIGNMENT_POLICY = "historical-carrying-component-alignment-v1"
SOURCE_VERSION = "customer-partial-return-monetary-original-v3"
Kind = Literal["Return", "Collection", "Refund", "ReverseReturn", "ReverseRefund"]


def _refuse() -> NoReturn:
    raise FinancePostingError("monetary_return_evidence_invalid", "Dual-currency original or ordered evidence refused.")


def _minor(value: object, *, positive: bool = False) -> int:
    return exact_minor(value, "retained monetary amount", zero=not positive)


def _sum(values: Any) -> int:
    return _minor(sum(values))


def allocate_revenue(value: int, quantity: int, selected: int, *, currency: str,
                     context: CurrencyRegistryContext) -> int:
    """Existing captured Money HALF_UP with exact final residual, including zero."""
    _minor(value)
    _minor(quantity, positive=True)
    _minor(selected, positive=True)
    captured = FinanceCurrencyPolicy.capture(currency, context)
    if captured.rounding_policy != "ROUND_HALF_UP" or selected > quantity:
        _refuse()
    if selected == quantity:
        return value
    result = Money.from_minor_units(value, currency, registry_context=context).multiply_exact(selected).divide_exact(quantity).to_minor_units()
    if not 0 <= result <= value:
        _refuse()
    return _minor(result)


@dataclass(frozen=True, slots=True)
class MonetaryComponent:
    position: int
    kind: Literal["Net", "Tax"]
    account_id: str
    transaction_minor: int
    functional_minor: int
    policy_digest: str

    def __post_init__(self) -> None:
        if type(self.position) is not int or not 0 <= self.position <= 8:
            _refuse()
        if type(self.kind) is not str or self.kind != ("Net" if self.position == 0 else "Tax"):
            _refuse()
        _ref(self.account_id, "original component account")
        _digest(self.policy_digest, "original component policy")
        _minor(self.transaction_minor, positive=self.kind == "Net")
        _minor(self.functional_minor, positive=self.kind == "Net")


@dataclass(frozen=True, slots=True)
class MonetaryConsumption:
    position: int
    original_consumption_id: str
    original_valuation_line_id: str
    cost_layer_id: str
    quantity_scaled: int
    value_minor: int

    def __post_init__(self) -> None:
        if type(self.position) is not int or not 1 <= self.position <= MAX_CONSUMPTIONS:
            _refuse()
        for value in (self.original_consumption_id, self.original_valuation_line_id, self.cost_layer_id):
            _ref(value, "original native consumption")
        _minor(self.quantity_scaled, positive=True)
        _minor(self.value_minor)


@dataclass(frozen=True, slots=True)
class MonetaryReturnSource:
    source_id: str
    source_order_id: str
    invoice_id: str
    posting_date: str
    native_origin_digest: str
    quantity_scaled: int
    quantity_precision: int
    transaction_policy: FinanceCurrencyPolicy
    functional_policy: FinanceCurrencyPolicy
    registry_context: CurrencyRegistryContext
    components: tuple[MonetaryComponent, ...]
    consumptions: tuple[MonetaryConsumption, ...]
    original_cost_admission_digest: str | None
    allocation_policy: str = ALLOCATION_POLICY
    alignment_policy: str = ALIGNMENT_POLICY

    def __post_init__(self) -> None:
        for value in (self.source_id, self.source_order_id, self.invoice_id):
            _ref(value, "native monetary origin")
        _digest(self.native_origin_digest, "native monetary origin")
        canonical_day(self.posting_date, "original monetary recognition date")
        _minor(self.quantity_scaled, positive=True)
        if type(self.quantity_precision) is not int or not 0 <= self.quantity_precision <= 6:
            _refuse()
        if type(self.registry_context) is not CurrencyRegistryContext:
            _refuse()
        for policy in (self.transaction_policy, self.functional_policy):
            if type(policy) is not FinanceCurrencyPolicy:
                _refuse()
            policy.require_compatible(FinanceCurrencyPolicy.capture(policy.currency_code, self.registry_context))
            if policy.rounding_policy != "ROUND_HALF_UP" or not 0 <= policy.precision <= 8:
                _refuse()
        if (type(self.components) is not tuple or not 1 <= len(self.components) <= 9
                or type(self.consumptions) is not tuple or not 1 <= len(self.consumptions) <= MAX_CONSUMPTIONS
                or type(self.allocation_policy) is not str or self.allocation_policy != ALLOCATION_POLICY
                or type(self.alignment_policy) is not str or self.alignment_policy != ALIGNMENT_POLICY):
            _refuse()
        for position, component in enumerate(self.components):
            if type(component) is not MonetaryComponent or component.position != position:
                _refuse()
            component.__post_init__()
        for position, consumption in enumerate(self.consumptions, 1):
            if type(consumption) is not MonetaryConsumption or consumption.position != position:
                _refuse()
            consumption.__post_init__()
        if len({part.original_consumption_id for part in self.consumptions}) != len(self.consumptions):
            _refuse()
        if _sum(part.quantity_scaled for part in self.consumptions) != self.quantity_scaled:
            _refuse()
        for attribute in ("transaction_minor", "functional_minor"):
            _minor(_sum(getattr(part, attribute) for part in self.components), positive=True)
        _sum(part.value_minor for part in self.consumptions)
        if any(part.value_minor == 0 for part in self.consumptions) or self.original_cost_admission_digest is not None:
            _digest(self.original_cost_admission_digest, "explicit original cost admission")
        if (self.transaction_policy.currency_code == self.functional_policy.currency_code
                and any(part.transaction_minor != part.functional_minor for part in self.components)):
            _refuse()

    @property
    def fingerprint(self) -> str:
        self.__post_init__()
        values = {field.name: getattr(self, field.name) for field in fields(self)
                  if field.name not in {"registry_context", "components", "consumptions", "transaction_policy", "functional_policy"}}
        return digest_payload({"schema_version": SOURCE_VERSION, **values,
            "components": [asdict(part) for part in self.components], "consumptions": [asdict(part) for part in self.consumptions],
            "transaction_policy": asdict(self.transaction_policy), "functional_policy": asdict(self.functional_policy),
            "registry_digest": self.registry_context.registry_manifest.digest})


@dataclass(frozen=True, slots=True)
class ComponentCut:
    position: int
    before_quantity_scaled: int
    before_transaction_minor: int
    before_functional_minor: int
    transaction_minor: int
    functional_minor: int


@dataclass(frozen=True, slots=True)
class CostCut:
    position: int
    original_consumption_id: str
    original_valuation_line_id: str
    cost_layer_id: str
    before_quantity_scaled: int
    before_value_minor: int
    quantity_scaled: int
    value_minor: int


@dataclass(frozen=True, slots=True)
class MonetaryPosition:
    remaining_quantity_scaled: int
    component_transaction_minor: tuple[int, ...]
    component_functional_minor: tuple[int, ...]
    consumption_quantity_scaled: tuple[int, ...]
    consumption_value_minor: tuple[int, ...]
    transaction_outstanding_minor: int
    functional_outstanding_minor: int
    transaction_refund_due_minor: int
    functional_refund_due_minor: int
    transaction_collected_minor: int
    transaction_credited_minor: int
    transaction_refunded_minor: int
    functional_refund_released_minor: int


@dataclass(frozen=True, slots=True)
class MonetaryMovement:
    transaction_net_minor: int = 0
    transaction_tax_minor: int = 0
    transaction_credit_minor: int = 0
    functional_net_minor: int = 0
    functional_tax_minor: int = 0
    functional_credit_minor: int = 0
    functional_cost_minor: int = 0
    transaction_receivable_released_minor: int = 0
    functional_receivable_released_minor: int = 0
    transaction_refund_delta_minor: int = 0
    functional_refund_delta_minor: int = 0
    transaction_refund_minor: int = 0
    functional_refund_released_minor: int = 0
    functional_cash_minor: int = 0
    functional_fx_gain_minor: int = 0
    functional_fx_loss_minor: int = 0
    functional_alignment_gain_minor: int = 0
    functional_alignment_loss_minor: int = 0
    functional_turnover_minor: int = 0


@dataclass(frozen=True, slots=True)
class MonetaryEvent:
    kind: Kind
    sequence: int
    source_fingerprint: str
    previous_history_fingerprint: str
    posting_date: str
    quantity_scaled: int
    amount_minor: int
    settlement_rate: HistoricalRate | None
    original_sequence: int | None
    before: MonetaryPosition
    after: MonetaryPosition
    monetary: MonetaryMovement
    components: tuple[ComponentCut, ...]
    portions: tuple[CostCut, ...]

    @property
    def fingerprint(self) -> str:
        return digest_payload(asdict(self))


@dataclass(frozen=True, slots=True)
class MonetaryHistory:
    source: MonetaryReturnSource
    events: tuple[MonetaryEvent, ...] = ()

    def __post_init__(self) -> None:
        if type(self.source) is not MonetaryReturnSource or type(self.events) is not tuple or len(self.events) > MAX_HISTORY_EVENTS:
            _refuse()
        self.source.__post_init__()

    @property
    def seed_fingerprint(self) -> str:
        return digest_payload({"contract": SOURCE_VERSION, "source_fingerprint": self.source.fingerprint,
                               "allocation_policy": ALLOCATION_POLICY, "alignment_policy": ALIGNMENT_POLICY})


def _initial(source: MonetaryReturnSource) -> MonetaryPosition:
    return MonetaryPosition(source.quantity_scaled, tuple(part.transaction_minor for part in source.components),
        tuple(part.functional_minor for part in source.components), tuple(part.quantity_scaled for part in source.consumptions),
        tuple(part.value_minor for part in source.consumptions), _sum(part.transaction_minor for part in source.components),
        _sum(part.functional_minor for part in source.components), 0, 0, 0, 0, 0, 0)


def _ratio(value: int, quantity: int, selected: int, source: MonetaryReturnSource, *, functional: bool) -> int:
    policy = source.functional_policy if functional else source.transaction_policy
    return allocate_revenue(value, quantity, selected, currency=policy.currency_code, context=source.registry_context)


def _position_valid(position: MonetaryPosition, source: MonetaryReturnSource) -> None:
    if type(position) is not MonetaryPosition:
        _refuse()
    for value in asdict(position).values():
        if type(value) is tuple:
            for amount in value:
                _minor(amount)
        else:
            _minor(value)
    if (len(position.component_transaction_minor) != len(source.components)
            or len(position.component_functional_minor) != len(source.components)
            or len(position.consumption_quantity_scaled) != len(source.consumptions)
            or len(position.consumption_value_minor) != len(source.consumptions)
            or _sum(position.consumption_quantity_scaled) != position.remaining_quantity_scaled
            or position.remaining_quantity_scaled > source.quantity_scaled
            or (position.transaction_outstanding_minor == 0 and position.functional_outstanding_minor != 0)
            or (position.transaction_refund_due_minor == 0 and position.functional_refund_due_minor != 0)
            or any(q == 0 and v != 0 for q, v in zip(position.consumption_quantity_scaled, position.consumption_value_minor, strict=True))
            or (position.remaining_quantity_scaled == 0 and
                any(position.component_transaction_minor + position.component_functional_minor))):
        _refuse()


def _return(source: MonetaryReturnSource, before: MonetaryPosition, quantity: int) -> tuple[MonetaryPosition, MonetaryMovement, tuple[ComponentCut, ...], tuple[CostCut, ...]]:
    _minor(quantity, positive=True)
    if quantity > before.remaining_quantity_scaled:
        _refuse()
    components = tuple(ComponentCut(part.position, before.remaining_quantity_scaled,
        before.component_transaction_minor[index], before.component_functional_minor[index],
        _ratio(before.component_transaction_minor[index], before.remaining_quantity_scaled, quantity, source, functional=False),
        _ratio(before.component_functional_minor[index], before.remaining_quantity_scaled, quantity, source, functional=True))
        for index, part in enumerate(source.components))
    transaction = _sum(part.transaction_minor for part in components)
    functional = _sum(part.functional_minor for part in components)
    ar_foreign = min(transaction, before.transaction_outstanding_minor)
    ar_local = (_ratio(before.functional_outstanding_minor, before.transaction_outstanding_minor, ar_foreign, source,
                       functional=True) if ar_foreign else 0)
    entitlement_foreign = transaction - ar_foreign
    entitlement_local = (_ratio(functional, transaction, entitlement_foreign, source, functional=True)
                         if entitlement_foreign else 0)
    alignment = functional - ar_local - entitlement_local
    remaining, cost, portions = quantity, 0, []
    qvalues, vvalues = list(before.consumption_quantity_scaled), list(before.consumption_value_minor)
    for index, part in enumerate(source.consumptions):
        if not remaining:
            break
        if not qvalues[index]:
            continue
        selected = min(remaining, qvalues[index])
        allocated = allocate_fifo_value(vvalues[index], qvalues[index], selected, allow_zero=True)
        portions.append(CostCut(part.position, part.original_consumption_id, part.original_valuation_line_id,
            part.cost_layer_id, qvalues[index], vvalues[index], selected, allocated))
        qvalues[index] -= selected
        vvalues[index] -= allocated
        cost += allocated
        remaining -= selected
    if remaining:
        _refuse()
    movement = MonetaryMovement(components[0].transaction_minor, _sum(part.transaction_minor for part in components[1:]),
        transaction, components[0].functional_minor, _sum(part.functional_minor for part in components[1:]), functional,
        _minor(cost), ar_foreign, ar_local, entitlement_foreign, entitlement_local,
        functional_alignment_gain_minor=max(alignment, 0), functional_alignment_loss_minor=max(-alignment, 0),
        functional_turnover_minor=_minor(functional + max(-alignment, 0) + cost))
    after = replace(before, remaining_quantity_scaled=before.remaining_quantity_scaled - quantity,
        component_transaction_minor=tuple(value - part.transaction_minor for value, part in zip(before.component_transaction_minor, components, strict=True)),
        component_functional_minor=tuple(value - part.functional_minor for value, part in zip(before.component_functional_minor, components, strict=True)),
        consumption_quantity_scaled=tuple(qvalues), consumption_value_minor=tuple(vvalues),
        transaction_outstanding_minor=before.transaction_outstanding_minor - ar_foreign,
        functional_outstanding_minor=before.functional_outstanding_minor - ar_local,
        transaction_refund_due_minor=_minor(before.transaction_refund_due_minor + entitlement_foreign),
        functional_refund_due_minor=_minor(before.functional_refund_due_minor + entitlement_local),
        transaction_credited_minor=_minor(before.transaction_credited_minor + transaction))
    return after, movement, components, tuple(portions)


def _cash(source: MonetaryReturnSource, before: MonetaryPosition, amount: int, day: str,
          rate: HistoricalRate | None, *, refund: bool) -> tuple[MonetaryPosition, MonetaryMovement]:
    _minor(amount, positive=True)
    foreign_before = before.transaction_refund_due_minor if refund else before.transaction_outstanding_minor
    local_before = before.functional_refund_due_minor if refund else before.functional_outstanding_minor
    if amount > foreign_before:
        _refuse()
    released = _ratio(local_before, foreign_before, amount, source, functional=True)
    foreign, local = source.transaction_policy.currency_code, source.functional_policy.currency_code
    if foreign == local:
        if rate is not None:
            _refuse()
        cash = amount
    else:
        if type(rate) is not HistoricalRate:
            _refuse()
        cash = convert_minor(amount, rate.resolve(foreign, local, source.registry_context, day), source.registry_context)
    difference = released - cash if refund else cash - released
    movement = MonetaryMovement(transaction_refund_minor=amount if refund else 0,
        transaction_receivable_released_minor=0 if refund else amount,
        functional_receivable_released_minor=0 if refund else released,
        functional_refund_released_minor=released if refund else 0, functional_cash_minor=cash,
        functional_fx_gain_minor=max(difference, 0), functional_fx_loss_minor=max(-difference, 0),
        functional_turnover_minor=max(released, cash))
    after = (replace(before, transaction_refund_due_minor=foreign_before - amount, functional_refund_due_minor=local_before - released,
             transaction_refunded_minor=_minor(before.transaction_refunded_minor + amount),
             functional_refund_released_minor=_minor(before.functional_refund_released_minor + released)) if refund else
             replace(before, transaction_outstanding_minor=foreign_before - amount, functional_outstanding_minor=local_before - released,
                     transaction_collected_minor=_minor(before.transaction_collected_minor + amount)))
    return after, movement


def _derive(source: MonetaryReturnSource, before: MonetaryPosition, events: tuple[MonetaryEvent, ...],
            kind: Kind, quantity: int, amount: int, day: str, rate: HistoricalRate | None,
            original_sequence: int | None) -> tuple[MonetaryPosition, MonetaryMovement, tuple[ComponentCut, ...], tuple[CostCut, ...]]:
    _position_valid(before, source)
    if type(kind) is not str or kind not in {"Return", "Collection", "Refund", "ReverseReturn", "ReverseRefund"}:
        _refuse()
    canonical_day(day, "monetary posting date")
    _minor(quantity)
    _minor(amount)
    if day < source.posting_date or (events and day < events[-1].posting_date):
        _refuse()
    if kind == "Return":
        if amount != 0 or rate is not None or original_sequence is not None:
            _refuse()
        return _return(source, before, quantity)
    if kind in {"Collection", "Refund"}:
        if quantity != 0 or original_sequence is not None:
            _refuse()
        after, movement = _cash(source, before, amount, day, rate, refund=kind == "Refund")
        return after, movement, (), ()
    if kind not in {"ReverseReturn", "ReverseRefund"} or type(original_sequence) is not int or rate is not None:
        _refuse()
    active: list[MonetaryEvent] = []
    for event in events:
        if event.kind.startswith("Reverse"):
            if not active or active[-1].sequence != event.original_sequence:
                _refuse()
            active.pop()
        else:
            active.append(event)
    if not active or active[-1].sequence != original_sequence:
        _refuse()
    original = active[-1]
    if (kind != "Reverse" + original.kind or before != original.after
            or quantity != original.quantity_scaled or amount != original.amount_minor):
        _refuse()
    return original.before, original.monetary, original.components, original.portions


def replay_monetary_history(history: MonetaryHistory) -> tuple[MonetaryPosition, str]:
    history.__post_init__()
    position, chain = _initial(history.source), history.seed_fingerprint
    source_fingerprint = history.source.fingerprint
    accepted: tuple[MonetaryEvent, ...] = ()
    for sequence, event in enumerate(history.events, 1):
        if (type(event) is not MonetaryEvent or type(event.sequence) is not int or event.sequence != sequence
                or event.source_fingerprint != source_fingerprint or event.previous_history_fingerprint != chain
                or event.before != position):
            _refuse()
        _position_valid(event.before, history.source)
        _position_valid(event.after, history.source)
        if type(event.monetary) is not MonetaryMovement or type(event.components) is not tuple or type(event.portions) is not tuple:
            _refuse()
        for value in asdict(event.monetary).values():
            _minor(value)
        after, movement, components, portions = _derive(history.source, position, accepted, event.kind,
            event.quantity_scaled, event.amount_minor, event.posting_date, event.settlement_rate, event.original_sequence)
        if (any(type(part) is not ComponentCut for part in event.components) or any(type(part) is not CostCut for part in event.portions)
                or canonical_json({"after": asdict(event.after), "monetary": asdict(event.monetary),
                                   "components": [asdict(part) for part in event.components], "portions": [asdict(part) for part in event.portions]})
                != canonical_json({"after": asdict(after), "monetary": asdict(movement),
                                   "components": [asdict(part) for part in components], "portions": [asdict(part) for part in portions]})):
            _refuse()
        _position_valid(after, history.source)
        position, chain = after, event.fingerprint
        accepted += (event,)
    return position, chain


def prepare_monetary_event(history: MonetaryHistory, kind: Kind, *, posting_date: str, quantity_scaled: int = 0,
                           amount_minor: int = 0, settlement_rate: HistoricalRate | None = None,
                           original_sequence: int | None = None) -> MonetaryEvent:
    position, chain = replay_monetary_history(history)
    if len(history.events) >= MAX_HISTORY_EVENTS:
        raise FinancePostingError("monetary_return_history_full", "The bounded monetary history is full.")
    after, movement, components, portions = _derive(history.source, position, history.events, kind, quantity_scaled,
        amount_minor, posting_date, settlement_rate, original_sequence)
    _position_valid(after, history.source)
    return MonetaryEvent(kind, len(history.events) + 1, history.source.fingerprint, chain, posting_date,
        quantity_scaled, amount_minor, settlement_rate, original_sequence, position, after, movement, components, portions)


def apply_monetary_event(history: MonetaryHistory, event: MonetaryEvent) -> MonetaryHistory:
    result = replace(history, events=history.events + (event,))
    replay_monetary_history(result)
    return result
