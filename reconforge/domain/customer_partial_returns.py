"""Bounded, exact partial-return planning over immutable original evidence.

This is a pure domain foundation, not a posting, authorization or persistence
boundary. A caller must obtain the original source and history through a trusted
adapter. Digests bind supplied content; they do not attest database ownership.
The first scope is functional currency, zero tax and untracked base UOM, with
positive integral original minor-unit portions and no implicit rounding.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from typing import Any, Literal

from reconforge.domain.customer_partial_return_cost_evidence import OriginalRestitutedCostEvidence
from reconforge.domain.customer_returns import MAX_MINOR, minor
from reconforge.domain.finance_policy import FinanceCurrencyPolicy
from reconforge.domain.finance_posting import (
    FinancePostingError,
    canonical_json,
    digest_payload,
    text,
    validation_digest,
)
from reconforge.domain.quantities import ExactQuantity
from reconforge.domain.receivables_policy import verify_receivables_policy
from reconforge.domain.sales_revenue import SalesLine
from reconforge.io.structured import StructuredDocumentPolicy, parse_json_document
from reconforge.utils.money import CurrencyRegistryContext, MinorMoney

MAX_CONSUMPTIONS = 32
MAX_HISTORY_EVENTS = 256
MAX_ORIGINAL_SNAPSHOT_BYTES = 65_536
ORIGINAL_PARTIAL_RETURN_JSON_POLICY = StructuredDocumentPolicy(
    max_file_bytes=MAX_ORIGINAL_SNAPSHOT_BYTES, max_nodes=16_384, max_depth=24,
    max_collection_items=1024, max_scalar_characters=65_536, max_yaml_aliases=1,
)
CONTRACT_VERSION = "customer-partial-return-domain-v1"


def _ref(value: object, field: str) -> None:
    if type(value) is not str or text(value, field) != value:
        raise FinancePostingError("partial_return_invalid", f"{field} must retain its exact text identity.")


def _integer(value: object, field: str, *, zero: bool = False, maximum: int = MAX_MINOR) -> int:
    result = minor(value, field, zero=zero)
    if result > maximum:
        raise FinancePostingError("partial_return_invalid", f"{field} exceeds the bounded domain contract.")
    return result


def _digest(value: object, field: str) -> None:
    if type(value) is not str or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise FinancePostingError("partial_return_invalid", f"{field} must be an exact SHA-256 content digest.")


@dataclass(frozen=True, slots=True)
class PartialReturnScope:
    tenant_id: str
    workspace_id: str
    organization_id: str
    legal_entity_id: str
    item_id: str
    location_id: str
    uom_id: str

    def __post_init__(self) -> None:
        for field in fields(self):
            _ref(getattr(self, field.name), field.name)


@dataclass(frozen=True, slots=True)
class OriginalPostingEvidence:
    posting_effect_id: str
    scope: PartialReturnScope
    snapshot_json: str
    validation_digest: str

    def __post_init__(self) -> None:
        _ref(self.posting_effect_id, "original posting effect")
        _digest(self.validation_digest, "original validation digest")
        if type(self.scope) is not PartialReturnScope:
            raise FinancePostingError("partial_return_invalid", "Original posting requires an immutable scope.")
        self.scope.__post_init__()
        snapshot = self.snapshot()
        entry = snapshot["entry"]
        if any(entry[key] != getattr(self.scope, key) for key in (
            "workspace_id", "organization_id", "legal_entity_id",
        )):
            raise FinancePostingError("partial_return_source_mismatch", "Original posting scope differs from the source.")

    def snapshot(self) -> dict[str, Any]:
        """Return a fresh copy; no mutable financial mappings are retained."""
        try:
            if type(self.snapshot_json) is not str or len(self.snapshot_json.encode("utf-8")) > MAX_ORIGINAL_SNAPSHOT_BYTES:
                raise ValueError("original snapshot exceeds the finite domain scope")
            value = parse_json_document(self.snapshot_json, policy=ORIGINAL_PARTIAL_RETURN_JSON_POLICY,
                                        reject_fractional_numbers=True)
            if type(value) is not dict or canonical_json(value) != self.snapshot_json:
                raise ValueError("noncanonical original snapshot")
            if validation_digest(value) != self.validation_digest:
                raise ValueError("original validation seal differs")
            return value
        except (TypeError, ValueError, RecursionError) as exc:
            raise FinancePostingError("partial_return_evidence_invalid", "Original posting evidence is invalid.") from exc

    @property
    def entry_id(self) -> str:
        return str(self.snapshot()["entry"]["id"])


@dataclass(frozen=True, slots=True)
class OriginalConsumption:
    position: int
    consumption_id: str
    valuation_line_id: str
    cost_layer_id: str
    scope: PartialReturnScope
    quantity_precision: int
    quantity_scaled: int
    value_minor: int
    currency_code: str

    def __post_init__(self) -> None:
        self._validate(allow_zero=False)

    def _validate(self, *, allow_zero: bool) -> None:
        _integer(self.position, "original position", maximum=MAX_CONSUMPTIONS)
        _integer(self.quantity_precision, "original quantity precision", zero=True, maximum=6)
        _integer(self.quantity_scaled, "original consumed quantity")
        _integer(self.value_minor, "original consumed cost", zero=allow_zero)
        for field in ("consumption_id", "valuation_line_id", "cost_layer_id", "currency_code"):
            _ref(getattr(self, field), field)
        if type(self.scope) is not PartialReturnScope:
            raise FinancePostingError("partial_return_invalid", "Original consumption requires an immutable scope.")
        self.scope.__post_init__()


@dataclass(frozen=True, slots=True)
class RestitutedOriginalConsumption(OriginalConsumption):
    """Explicit new factual scope; the original positive-only constructor stays strict."""

    def __post_init__(self) -> None:
        self._validate(allow_zero=True)


@dataclass(frozen=True, slots=True)
class OriginalPartialReturnSource:
    scope: PartialReturnScope
    source_order_id: str
    invoice_id: str
    valuation_document_id: str
    original_revenue_plan_id: str
    quantity_precision: int
    quantity_scaled: int
    gross_minor: int
    net_unit_price_minor: int
    collected_minor: int
    currency_policy: FinanceCurrencyPolicy
    registry_context: CurrencyRegistryContext
    original_cogs: OriginalPostingEvidence | None
    original_revenue: OriginalPostingEvidence
    consumptions: tuple[OriginalConsumption, ...]
    functional_currency: str
    base_uom_id: str
    tax_minor: int
    inventory_lot_id: str | None
    serial_tracked: bool
    original_cost_admission: OriginalRestitutedCostEvidence | None = None

    def __post_init__(self) -> None:
        if type(self.scope) is not PartialReturnScope:
            raise FinancePostingError("partial_return_invalid", "The source requires an immutable scope.")
        self.scope.__post_init__()
        for field in ("source_order_id", "invoice_id", "valuation_document_id", "original_revenue_plan_id", "functional_currency", "base_uom_id"):
            _ref(getattr(self, field), field)
        for field in ("quantity_scaled", "gross_minor", "net_unit_price_minor"):
            _integer(getattr(self, field), field)
        _integer(self.quantity_precision, "quantity precision", zero=True, maximum=6)
        _integer(self.collected_minor, "original collections", zero=True)
        _integer(self.tax_minor, "original tax", zero=True)
        if type(self.currency_policy) is not FinanceCurrencyPolicy or type(self.registry_context) is not CurrencyRegistryContext:
            raise FinancePostingError("partial_return_invalid", "Explicit immutable captured currency evidence is required.")
        policy = verify_receivables_policy({
            "currency_code": self.currency_policy.currency_code, **self.currency_policy.metadata(),
        }, snapshot=self.registry_context).require_captured()
        policy.require_compatible(self.currency_policy)
        if (self.tax_minor != 0 or self.functional_currency != policy.currency_code or
            self.base_uom_id != self.scope.uom_id or self.inventory_lot_id is not None or
            type(self.serial_tracked) is not bool or self.serial_tracked):
            raise FinancePostingError("partial_return_scope_unsupported", "Only zero-tax functional-currency untracked base UOM is supported.")
        MinorMoney(self.gross_minor, policy.currency_code, registry_context=self.registry_context)
        # Original Stock/Sales already admits the shared per-line HALF_UP
        # quotation. Keep its posted gross; later return portions must still
        # be exact integral proportions of that original gross and FIFO cost.
        original_quote = SalesLine("Original retained merchandise", ExactQuantity(
            self.quantity_scaled, self.quantity_precision).text, self.net_unit_price_minor).priced()
        if self.collected_minor > self.gross_minor or original_quote["line_total_minor"] != self.gross_minor:
            raise FinancePostingError("partial_return_source_mismatch", "Original revenue or retained collection totals differ.")
        if type(self.consumptions) is not tuple or not 1 <= len(self.consumptions) <= MAX_CONSUMPTIONS:
            raise FinancePostingError("partial_return_invalid", "Original consumption order must be a bounded immutable tuple.")
        identities: set[str] = set()
        layers: set[str] = set()
        for position, row in enumerate(self.consumptions, 1):
            expected_type = OriginalConsumption if self.original_cost_admission is None else RestitutedOriginalConsumption
            if type(row) is not expected_type:
                raise FinancePostingError("partial_return_invalid", "Typed original consumption evidence is required.")
            row.__post_init__()
            if (row.position != position or row.consumption_id in identities or row.cost_layer_id in layers or
                row.scope != self.scope or row.quantity_precision != self.quantity_precision or row.currency_code != policy.currency_code):
                raise FinancePostingError("partial_return_source_mismatch", "Original consumption order, identity or source affinity differs.")
            identities.add(row.consumption_id)
            layers.add(row.cost_layer_id)
        admitted = self.original_cost_admission
        if admitted is not None and type(admitted) is not OriginalRestitutedCostEvidence:
            raise FinancePostingError("partial_return_source_mismatch", "Original restituted cost requires explicit immutable evidence.")
        total_cost = _integer(sum(row.value_minor for row in self.consumptions), "total original cost", zero=admitted is not None)
        if admitted is None and any(row.value_minor == 0 for row in self.consumptions):
            raise FinancePostingError("partial_return_source_mismatch", "Original legacy consumption cost must remain positive.")
        if sum(row.quantity_scaled for row in self.consumptions) != self.quantity_scaled:
            raise FinancePostingError("partial_return_source_mismatch", "Original consumed quantities do not match the delivered source.")
        if (type(self.original_revenue) is not OriginalPostingEvidence
            or (total_cost > 0 and type(self.original_cogs) is not OriginalPostingEvidence)
            or (total_cost == 0 and self.original_cogs is not None)):
            raise FinancePostingError("partial_return_invalid", "Typed original financial evidence is required.")
        evidences = [(self.original_revenue, self.gross_minor, self.original_revenue_plan_id)]
        if self.original_cogs is not None:
            evidences.append((self.original_cogs, total_cost, self.source_order_id))
        for evidence, amount, reference in evidences:
            evidence.__post_init__()
            snapshot = evidence.snapshot()
            entry, lines = snapshot["entry"], snapshot["lines"]
            original_policy = verify_receivables_policy(entry, snapshot=self.registry_context).require_captured()
            policy.require_compatible(original_policy)
            if (evidence.scope != self.scope or entry["source_type"] != "Manual" or entry["reverses_posting_id"] is not None or
                entry["external_reference"] != reference or len(lines) != 2 or
                sum(line["debit_minor"] for line in lines) != amount or len({line["account_id"] for line in lines}) != 2):
                raise FinancePostingError("partial_return_source_mismatch", "Original financial amounts, references or source affinity differ.")
        if self.original_cogs is not None and (self.original_cogs.posting_effect_id == self.original_revenue.posting_effect_id or self.original_cogs.entry_id == self.original_revenue.entry_id):
            raise FinancePostingError("partial_return_source_mismatch", "Distinct original cost and revenue evidence is required.")
        if admitted is not None:
            proof = admitted.snapshot()
            document, line = proof["valuation_document"], proof["valuation_lines"][0]
            if (proof["stock_order_id"] != self.source_order_id or document["id"] != self.valuation_document_id
                or document["total_value_minor"] != total_cost
                or any(document[key] != getattr(self.scope, key) for key in ("workspace_id", "organization_id", "legal_entity_id"))
                or any(line[key] != getattr(self.scope, key) for key in ("item_id", "uom_id"))
                or line["quantity_scaled"] != self.quantity_scaled or line["quantity_precision"] != self.quantity_precision
                or [(row["id"], row["valuation_line_id"], row["cost_layer_id"], row["quantity_scaled"], row["value_minor"]) for row in proof["consumptions"]]
                != [(row.consumption_id, row.valuation_line_id, row.cost_layer_id, row.quantity_scaled, row.value_minor) for row in self.consumptions]
                or (self.original_cogs is not None and proof["posting_effect"]["id"] != self.original_cogs.posting_effect_id)):
                raise FinancePostingError("partial_return_source_mismatch", "Original restituted-cost evidence differs from native source facts.")

    @property
    def fingerprint_payload(self) -> dict[str, Any]:
        return {
            "contract": CONTRACT_VERSION if self.original_cost_admission is None else "customer-partial-return-original-v2", "scope": asdict(self.scope),
            "source_order_id": self.source_order_id, "invoice_id": self.invoice_id,
            "valuation_document_id": self.valuation_document_id, "quantity_precision": self.quantity_precision,
            "original_revenue_plan_id": self.original_revenue_plan_id,
            "quantity_scaled": self.quantity_scaled, "gross_minor": self.gross_minor,
            "net_unit_price_minor": self.net_unit_price_minor, "collected_minor": self.collected_minor,
            "currency": self.currency_policy.currency_code, "policy": self.currency_policy.metadata(),
            "functional_currency": self.functional_currency, "base_uom_id": self.base_uom_id,
            "tax_minor": self.tax_minor, "inventory_lot_id": self.inventory_lot_id, "serial_tracked": self.serial_tracked,
            "consumptions": [asdict(row) for row in self.consumptions],
            "original_cogs": [self.original_cogs.posting_effect_id, self.original_cogs.validation_digest] if self.original_cogs is not None else None,
            "original_revenue": [self.original_revenue.posting_effect_id, self.original_revenue.validation_digest],
            **({"original_cost_admission": ["stock-sales-restituted-cost-v1", self.original_cost_admission.evidence_digest]}
               if self.original_cost_admission is not None else {}),
        }

    @property
    def fingerprint(self) -> str:
        return digest_payload(self.fingerprint_payload)


@dataclass(frozen=True, slots=True)
class ConsumptionPortion:
    position: int
    original_consumption_id: str
    original_valuation_line_id: str
    cost_layer_id: str
    offset_quantity_scaled: int
    quantity_scaled: int
    value_minor: int

    def __post_init__(self) -> None:
        _integer(self.position, "portion position", maximum=MAX_CONSUMPTIONS)
        for field in ("original_consumption_id", "original_valuation_line_id", "cost_layer_id"):
            _ref(getattr(self, field), field)
        _integer(self.offset_quantity_scaled, "portion offset", zero=True)
        _integer(self.quantity_scaled, "portion quantity")
        _integer(self.value_minor, "portion cost")


@dataclass(frozen=True, slots=True)
class _ReturnValues:
    quantity_before_scaled: int
    quantity_scaled: int
    returned_quantity_scaled: int
    credit_minor: int
    cogs_restored_minor: int
    receivable_released_minor: int
    refund_entitlement_delta_minor: int
    outstanding_after_minor: int
    portions: tuple[ConsumptionPortion, ...]

    def __post_init__(self) -> None:
        for field in fields(_ReturnValues):
            if field.name == "portions":
                continue
            _integer(getattr(self, field.name), field.name, zero=field.name in {
                "quantity_before_scaled", "receivable_released_minor", "refund_entitlement_delta_minor", "outstanding_after_minor",
            })
        if type(self.portions) is not tuple or not 1 <= len(self.portions) <= MAX_CONSUMPTIONS:
            raise FinancePostingError("partial_return_invalid", "Return portions must be a bounded immutable tuple.")
        for portion in self.portions:
            if type(portion) is not ConsumptionPortion:
                raise FinancePostingError("partial_return_invalid", "Typed original portions are required.")
            portion.__post_init__()


@dataclass(frozen=True, slots=True)
class PartialReturnEvent:
    kind: Literal["Return", "Collection", "Refund", "ReverseReturn", "ReverseRefund"]
    sequence: int
    source_fingerprint: str
    previous_history_fingerprint: str
    amount_minor: int = 0
    return_values: _ReturnValues | None = None
    original_sequence: int | None = None

    def __post_init__(self) -> None:
        if type(self.kind) is not str or self.kind not in {"Return", "Collection", "Refund", "ReverseReturn", "ReverseRefund"}:
            raise FinancePostingError("partial_return_history_invalid", "Unsupported partial-return history event.")
        _integer(self.sequence, "event sequence", maximum=MAX_HISTORY_EVENTS)
        _digest(self.source_fingerprint, "event source")
        _digest(self.previous_history_fingerprint, "previous history")
        _integer(self.amount_minor, "event amount", zero=self.kind in {"Return", "ReverseReturn"})
        if self.kind in {"Return", "ReverseReturn"}:
            if self.amount_minor != 0 or type(self.return_values) is not _ReturnValues:
                raise FinancePostingError("partial_return_history_invalid", "Return history requires exact original portions.")
            self.return_values.__post_init__()
        elif self.return_values is not None:
            raise FinancePostingError("partial_return_history_invalid", "Settlement history cannot carry return portions.")
        if self.kind.startswith("Reverse"):
            _integer(self.original_sequence, "reversed sequence", maximum=MAX_HISTORY_EVENTS)
        elif self.original_sequence is not None:
            raise FinancePostingError("partial_return_history_invalid", "Only a governed reversal may name an original event.")


@dataclass(frozen=True, slots=True)
class PartialReturnHistory:
    source: OriginalPartialReturnSource
    events: tuple[PartialReturnEvent, ...] = ()

    def __post_init__(self) -> None:
        if type(self.source) is not OriginalPartialReturnSource or type(self.events) is not tuple or len(self.events) > MAX_HISTORY_EVENTS:
            raise FinancePostingError("partial_return_history_invalid", "History requires a source and bounded immutable events.")
        if any(type(event) is not PartialReturnEvent for event in self.events):
            raise FinancePostingError("partial_return_history_invalid", "Typed history events are required.")


@dataclass(frozen=True, slots=True)
class PartialReturnPlan(_ReturnValues):
    history: PartialReturnHistory
    source_fingerprint: str
    history_fingerprint: str
    expected_version: int

    def __post_init__(self) -> None:
        _ReturnValues.__post_init__(self)
        if type(self.history) is not PartialReturnHistory:
            raise FinancePostingError("partial_return_invalid", "Plan requires its exact immutable history basis.")
        _digest(self.source_fingerprint, "plan source")
        _digest(self.history_fingerprint, "plan history")
        _integer(self.expected_version, "expected version", zero=True, maximum=MAX_HISTORY_EVENTS)

    @property
    def source(self) -> OriginalPartialReturnSource:
        return self.history.source

    def payload(self) -> dict[str, Any]:
        """Fresh finite command content, without the retained financial bodies."""
        return {
            "schema_version": CONTRACT_VERSION,
            "source_fingerprint": self.source_fingerprint,
            "history_fingerprint": self.history_fingerprint,
            "expected_version": self.expected_version,
            **asdict(_ReturnValues(**{field.name: getattr(self, field.name) for field in fields(_ReturnValues)})),
        }

    @property
    def fingerprint(self) -> str:
        return digest_payload(self.payload())


@dataclass(frozen=True, slots=True)
class PartialReturnBalance:
    returned_quantity_scaled: int
    credited_minor: int
    cogs_restored_minor: int
    collected_minor: int
    receivable_released_minor: int
    refund_entitlement_minor: int
    refunded_minor: int
    outstanding_minor: int
    refund_due_minor: int
    history_fingerprint: str
    version: int


def _exact_portion(value: int, selected: int, original: int, field: str) -> int:
    quotient, remainder = divmod(value * selected, original)
    if remainder or quotient <= 0:
        raise FinancePostingError("partial_return_nonintegral", f"{field} must be a positive integral original minor-unit portion.")
    return _integer(quotient, field)


def _calculate(source: OriginalPartialReturnSource, returned: int, credited: int, collected: int, quantity: int) -> _ReturnValues:
    _integer(quantity, "return quantity")
    if returned + quantity > source.quantity_scaled:
        raise FinancePostingError("partial_return_quantity_exceeded", "Return quantity exceeds the remaining original delivery.")
    credit = _exact_portion(source.gross_minor, quantity, source.quantity_scaled, "return credit")
    skip, pending, portions = returned, quantity, []
    for row in source.consumptions:
        offset = min(skip, row.quantity_scaled)
        skip -= offset
        take = min(pending, row.quantity_scaled - offset)
        if take:
            portions.append(ConsumptionPortion(
                row.position, row.consumption_id, row.valuation_line_id, row.cost_layer_id,
                offset, take, _exact_portion(row.value_minor, take, row.quantity_scaled, "restored cost"),
            ))
            pending -= take
        if not pending:
            break
    if pending:
        raise FinancePostingError("partial_return_source_mismatch", "Original consumption prefix is incomplete.")
    release = min(credit, max(source.gross_minor - credited - collected, 0))
    return _ReturnValues(
        returned, quantity, returned + quantity, credit, sum(portion.value_minor for portion in portions),
        release, credit - release, max(source.gross_minor - credited - credit - collected, 0), tuple(portions),
    )


def partial_return_balance(history: PartialReturnHistory) -> PartialReturnBalance:
    """Recompute all cumulative facts and validate the exact retained prefix."""
    if type(history) is not PartialReturnHistory:
        raise FinancePostingError("partial_return_history_invalid", "Typed partial-return history is required.")
    history.__post_init__()
    source = history.source
    source.__post_init__()
    if source.original_cost_admission is not None:
        raise FinancePostingError("partial_return_scope_unsupported", "Legacy history does not admit a new restituted-cost original.")
    source_digest = source.fingerprint
    chain = digest_payload({"contract": CONTRACT_VERSION, "source": source_digest})
    returned = credited = cost = released = liability = refunded = 0
    collected = source.collected_minor
    active: list[PartialReturnEvent] = []
    for sequence, event in enumerate(history.events, 1):
        event.__post_init__()
        if event.sequence != sequence or event.source_fingerprint != source_digest or event.previous_history_fingerprint != chain:
            raise FinancePostingError("partial_return_history_invalid", "History sequence, original source or retained prefix differs.")
        if event.kind == "Return":
            retained_values = event.return_values
            if retained_values is None:
                raise FinancePostingError("partial_return_history_invalid", "Return history requires exact original portions.")
            values = _calculate(source, returned, credited, collected, retained_values.quantity_scaled)
            if canonical_json(asdict(retained_values)) != canonical_json(asdict(values)):
                raise FinancePostingError("partial_return_history_invalid", "Retained return effects do not match original portions.")
            returned += values.quantity_scaled
            credited += values.credit_minor
            cost += values.cogs_restored_minor
            released += values.receivable_released_minor
            liability += values.refund_entitlement_delta_minor
            active.append(event)
        elif event.kind == "Collection":
            if event.amount_minor > max(source.gross_minor - credited - collected, 0):
                raise FinancePostingError("partial_return_collection_exceeded", "Collection exceeds current credit-adjusted invoice AR.")
            collected += event.amount_minor
            active.append(event)
        elif event.kind == "Refund":
            if event.amount_minor > liability - refunded:
                raise FinancePostingError("partial_return_refund_exceeded", "Refund exceeds the remaining retained entitlement.")
            refunded += event.amount_minor
            active.append(event)
        else:
            if not active or active[-1].sequence != event.original_sequence or event.kind != "Reverse" + active[-1].kind:
                raise FinancePostingError("partial_return_reversal_invalid", "Only the latest unreversed owned economic event may be reversed.")
            original = active.pop()
            if event.amount_minor != original.amount_minor or event.return_values != original.return_values:
                raise FinancePostingError("partial_return_reversal_invalid", "Reversal must preserve the exact original event magnitudes.")
            if event.kind == "ReverseRefund":
                refunded -= event.amount_minor
            else:
                reversed_values = event.return_values
                if reversed_values is None or liability - reversed_values.refund_entitlement_delta_minor < refunded:
                    raise FinancePostingError("partial_return_reversal_invalid", "A refunded credit cannot be reversed before its refund.")
                returned -= reversed_values.quantity_scaled
                credited -= reversed_values.credit_minor
                cost -= reversed_values.cogs_restored_minor
                released -= reversed_values.receivable_released_minor
                liability -= reversed_values.refund_entitlement_delta_minor
        chain = digest_payload({"previous": chain, "event": asdict(event)})
    return PartialReturnBalance(
        returned, credited, cost, collected, released, liability, refunded,
        max(source.gross_minor - credited - collected, 0), liability - refunded, chain, len(history.events),
    )


def prepare_partial_return(history: PartialReturnHistory, quantity_scaled: int) -> PartialReturnPlan:
    balance = partial_return_balance(history)
    if balance.version >= MAX_HISTORY_EVENTS:
        raise FinancePostingError("partial_return_history_full", "The finite history event budget is exhausted.")
    values = _calculate(history.source, balance.returned_quantity_scaled, balance.credited_minor, balance.collected_minor, quantity_scaled)
    return PartialReturnPlan(
        **{field.name: getattr(values, field.name) for field in fields(_ReturnValues)},
        history=history, source_fingerprint=history.source.fingerprint,
        history_fingerprint=balance.history_fingerprint, expected_version=balance.version,
    )


def verify_partial_return_plan(plan: PartialReturnPlan) -> None:
    if type(plan) is not PartialReturnPlan:
        raise FinancePostingError("partial_return_invalid", "Typed exact partial-return plan is required.")
    plan.__post_init__()
    expected = prepare_partial_return(plan.history, plan.quantity_scaled)
    actual_payload = {field.name: getattr(plan, field.name) for field in fields(_ReturnValues)}
    expected_payload = {field.name: getattr(expected, field.name) for field in fields(_ReturnValues)}
    if (plan.source_fingerprint != expected.source_fingerprint or plan.history_fingerprint != expected.history_fingerprint or
        plan.expected_version != expected.expected_version or canonical_json(asdict(_ReturnValues(**actual_payload))) != canonical_json(asdict(_ReturnValues(**expected_payload)))):
        raise FinancePostingError("partial_return_plan_changed", "Partial-return plan differs from its exact original history basis.")


def _append(history: PartialReturnHistory, event: PartialReturnEvent) -> PartialReturnHistory:
    result = PartialReturnHistory(history.source, (*history.events, event))
    partial_return_balance(result)
    return result


def apply_partial_return(history: PartialReturnHistory, plan: PartialReturnPlan) -> PartialReturnHistory:
    verify_partial_return_plan(plan)
    current = partial_return_balance(history)
    if (history.source.fingerprint != plan.source_fingerprint or current.history_fingerprint != plan.history_fingerprint or current.version != plan.expected_version):
        raise FinancePostingError("partial_return_plan_stale", "Reload the source and history before applying a stale plan.")
    values = _ReturnValues(**{field.name: getattr(plan, field.name) for field in fields(_ReturnValues)})
    return _append(history, PartialReturnEvent("Return", current.version + 1, plan.source_fingerprint, current.history_fingerprint, return_values=values))


def _settle(history: PartialReturnHistory, amount_minor: int, kind: Literal["Collection", "Refund"]) -> PartialReturnHistory:
    amount = _integer(amount_minor, "settlement amount")
    current = partial_return_balance(history)
    return _append(history, PartialReturnEvent(kind, current.version + 1, history.source.fingerprint, current.history_fingerprint, amount))


def collect_partial_return(history: PartialReturnHistory, amount_minor: int) -> PartialReturnHistory:
    return _settle(history, amount_minor, "Collection")


def refund_partial_return(history: PartialReturnHistory, amount_minor: int) -> PartialReturnHistory:
    return _settle(history, amount_minor, "Refund")


def reverse_partial_return_event(history: PartialReturnHistory, original_sequence: int) -> PartialReturnHistory:
    """Preserve the old event and append its exact, last-in-order correction.

    Native ownership must additionally prove that physical restored units and
    the owned correction effects have no downstream consumption/dependency.
    """
    balance = partial_return_balance(history)
    _integer(original_sequence, "original sequence", maximum=balance.version)
    original = history.events[original_sequence - 1]
    if original.kind not in {"Return", "Refund"}:
        raise FinancePostingError("partial_return_reversal_invalid", "Only an owned credit or refund can be reversed.")
    kind: Literal["ReverseReturn", "ReverseRefund"] = "ReverseReturn" if original.kind == "Return" else "ReverseRefund"
    return _append(history, PartialReturnEvent(kind, balance.version + 1, history.source.fingerprint,
        balance.history_fingerprint, original.amount_minor, original.return_values, original_sequence))
