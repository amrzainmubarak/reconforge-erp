"""Bounded actual-material production; no implicit quantities, yields or costs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any, NoReturn

from reconforge.domain.finance_posting import FinancePostingError, digest_payload, text
from reconforge.domain.inventory_costing import allocate_fifo_value
from reconforge.platform.inventory_values import quantity_to_scaled, scaled_to_text

MAX_COMPONENTS = 100
MAX_COMPLETIONS = 200
MAX_INTEGER = 9_000_000_000_000_000_000

READ = frozenset({"manufacturing_execution.read", "inventory.read", "finance_core.read"})
PERMISSIONS = {
    "create": READ | {"manufacturing_execution.manage", "inventory.manage"},
    "approve-bom": READ | {"manufacturing_execution.approve"},
    "prepare": READ | {"manufacturing_execution.manage", "inventory.manage", "inventory.valuation.manage", "finance_core.manage"},
    "review": READ | {"manufacturing_execution.approve", "inventory.post", "inventory.valuation.approve", "finance_core.validate"},
    "post": READ | {"manufacturing_execution.post", "inventory.post", "inventory.valuation.approve", "finance_core.post"},
    "cancel": READ | {"manufacturing_execution.approve"},
}


def fail(message: str, code: str = "manufacturing_execution_invalid") -> NoReturn:
    raise FinancePostingError(code, message)


def exact_integer(value: object, *, positive: bool = False) -> int:
    if type(value) is not int or not (1 if positive else 0) <= value <= MAX_INTEGER:
        fail("An exact bounded nonnegative integer is required.")
    return value


def business_date(value: object) -> str:
    selected = text(value, "posting_date", maximum=10)
    try:
        if date.fromisoformat(selected).isoformat() != selected:
            raise ValueError
    except ValueError as exc:
        raise FinancePostingError("manufacturing_execution_date_invalid", "A canonical business date is required.") from exc
    return selected


def quantity(value: object, precision: int) -> int:
    if not isinstance(value, str):
        fail("Quantities require exact decimal text.")
    result = quantity_to_scaled(value, decimal_places=precision)
    return exact_integer(result, positive=True)


def expand_requirements(components: Sequence[Mapping[str, Any]], batch_output_scaled: int,
                        order_output_scaled: int) -> list[dict[str, Any]]:
    """Expand a versioned base-UOM BOM only when every component divides exactly."""
    exact_integer(batch_output_scaled, positive=True)
    exact_integer(order_output_scaled, positive=True)
    if not 1 <= len(components) <= MAX_COMPONENTS:
        fail("A BOM requires between one and one hundred component lines.")
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for component in components:
        item = text(component["item_id"], "item_id")
        if item in seen:
            fail("A BOM contains each canonical component item once.")
        seen.add(item)
        numerator = exact_integer(component["quantity_scaled"], positive=True) * order_output_scaled
        required, remainder = divmod(numerator, batch_output_scaled)
        if remainder:
            fail("Order quantity cannot represent every BOM component exactly in its canonical UOM.")
        exact_integer(required, positive=True)
        result.append({**dict(component), "required_quantity_scaled": required,
                       "required_quantity": scaled_to_text(required, decimal_places=component["quantity_precision"])})
    return sorted(result, key=lambda line: line["item_id"])


def allocate_disposition(*, original_quantity: int, original_cost: int, disposed_quantity: int,
                         released_cost: int, good_quantity: int, scrap_quantity: int) -> dict[str, int]:
    """Consume retained WIP proportionally; final disposition receives every residual minor unit.

    One stage applies the existing FIFO allocator to the remaining homogeneous
    production batch, then allocates its value to good and abnormal scrap. This
    is explicit actual-material accounting, without normal-yield or overhead.
    """
    exact_integer(original_quantity, positive=True)
    exact_integer(original_cost, positive=True)
    for value in (disposed_quantity, released_cost, good_quantity, scrap_quantity):
        exact_integer(value)
    stage = good_quantity + scrap_quantity
    remaining_quantity, remaining_cost = original_quantity - disposed_quantity, original_cost - released_cost
    if remaining_quantity <= 0 or remaining_cost <= 0 or not 0 < stage <= remaining_quantity:
        fail("Disposition exceeds the current retained production quantity or WIP.")
    value = allocate_fifo_value(remaining_cost, remaining_quantity, stage)
    good = allocate_fifo_value(value, stage, good_quantity) if good_quantity else 0
    scrap = value - good
    if (good_quantity and not good) or (scrap_quantity and not scrap):
        fail("A positive good or scrap quantity cannot have a zero-valued financial disposition.")
    return {"good_quantity_scaled": good_quantity, "scrap_quantity_scaled": scrap_quantity,
            "stage_quantity_scaled": stage, "good_cost_minor": good, "scrap_cost_minor": scrap,
            "released_cost_minor": value, "wip_after_minor": remaining_cost - value,
            "disposed_before_scaled": disposed_quantity, "released_before_minor": released_cost}


def requirement_payload(*, requirement_id: str, order: Mapping[str, Any], bom: Mapping[str, Any],
                        component: Mapping[str, Any]) -> dict[str, Any]:
    return {"schema_version": "manufacturing-requirement-v1", "requirement_id": requirement_id,
            "order_id": order["id"], "bom_version_id": bom["id"], "order_source_digest": order["source_digest"],
            "bom_digest": bom["source_digest"], "scope": {key: order[key] for key in
            ("workspace_id", "organization_id", "legal_entity_id")},
            **{key: component[key] for key in ("item_id", "item_code", "uom_id", "uom_code", "quantity_precision",
                                              "required_quantity_scaled", "required_quantity")}}


@dataclass(frozen=True)
class BomPreparation:
    number: str
    version: int
    output_item_code: str
    output_quantity: str
    components: Sequence[Mapping[str, Any]]
    workspace_id: str
    organization_id: str
    legal_entity_id: str
    organization_code: str
    entity_code: str
    reason: str

    def payload(self) -> dict[str, Any]:
        exact_integer(self.version, positive=True)
        if not 1 <= len(self.components) <= MAX_COMPONENTS:
            fail("A bounded BOM requires one to one hundred actual component lines.")
        components = []
        for line in self.components:
            if set(line) != {"item_code", "quantity"}:
                fail("A BOM component requires exactly item_code and base-UOM quantity.")
            components.append({"item_code": text(line["item_code"], "item_code", maximum=64),
                               "quantity": text(line["quantity"], "quantity", maximum=40)})
        return {"schema_version": "manufacturing-bom-v1", "number": text(self.number, "number", maximum=64),
                "version": self.version, "output_item_code": text(self.output_item_code, "output_item_code", maximum=64),
                "output_quantity": text(self.output_quantity, "output_quantity", maximum=40), "components": components,
                **{key: text(getattr(self, key), key) for key in ("workspace_id", "organization_id", "legal_entity_id",
                                                                  "organization_code", "entity_code")},
                "reason": text(self.reason, "reason", maximum=500)}


@dataclass(frozen=True)
class OrderPreparation:
    number: str
    bom_version_id: str
    output_quantity: str
    component_location_code: str
    finished_location_code: str
    component_policy_code: str
    finished_policy_code: str
    journal_code: str
    wip_account_code: str
    scrap_account_code: str
    period_id: str
    posting_date: str
    workspace_id: str
    organization_id: str
    legal_entity_id: str
    organization_code: str
    entity_code: str
    reason: str

    def payload(self) -> dict[str, Any]:
        return {"schema_version": "manufacturing-order-v1", **{key: text(getattr(self, key), key, maximum=160)
                for key in self.__dataclass_fields__ if key not in {"posting_date", "reason"}},
                "posting_date": business_date(self.posting_date), "reason": text(self.reason, "reason", maximum=500)}


def source_digest(payload: Mapping[str, Any]) -> str:
    return digest_payload(dict(payload))
