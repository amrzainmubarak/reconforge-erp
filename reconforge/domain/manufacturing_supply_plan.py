"""Exact pre-stock manufacturing demand and exclusive native supply claims."""
from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from reconforge.domain.finance_posting import text
from reconforge.domain.inventory_receipt_posting import COMMIT_PERMISSIONS, PREPARE_PERMISSIONS, REVIEW_PERMISSIONS
from reconforge.domain.manufacturing_execution import (
    MAX_COMPONENTS,
    MAX_INTEGER,
    OrderPreparation,
    exact_integer,
    expand_requirements,
    fail,
)
from reconforge.domain.procurement_sourcing import PERMISSIONS as SOURCING_PERMISSIONS
from reconforge.platform.inventory_values import scaled_to_text

SCHEMA_VERSION = "manufacturing-supply-plan-v1"
REQUIREMENT_SCHEMA_VERSION = "manufacturing-planned-requirement-v1"
MAX_PROCUREMENT_CLAIMS = 100
PLAN_PHASES = ("Draft", "Approved", "HandedOff", "Cancelled")
READ = frozenset({"manufacturing_supply_plan.read", "manufacturing_execution_v2.read", "manufacturing_execution.read", "inventory.read", "finance_core.read", "budget_control.read"})
PERMISSIONS = {
    "create": READ | {"manufacturing_supply_plan.manage"},
    "approve": READ | {"manufacturing_supply_plan.approve", "inventory.manage"},
    "source": READ | {"manufacturing_supply_plan.manage", "procurement_sourcing.read"},
    "receive": READ | {"manufacturing_supply_plan.post", "inventory.post", "payables.read"},
    "handoff": READ | {"manufacturing_supply_plan.manage", "manufacturing_execution_v2.manage", "manufacturing_execution.manage", "inventory.manage"},
    "cancel": READ | {"manufacturing_supply_plan.approve", "inventory.manage"},
}
PURCHASE_OPERATIONS = {
    "purchase-submit": "submit-order", "purchase-approve": "approve-order",
    "receive-prepare": "prepare-receipt-line", "receive-review": "review-receipt", "receive-commit": "receive",
    "invoice-match": "match-invoice-lines", "invoice-approve": "approve-invoice",
    "invoice-prepare": "prepare-accrual", "invoice-review": "review-accrual", "invoice-post": "post-accrual",
}
_PURCHASE_AUTHORITY = {
    "submit-order": {"payables.manage"}, "approve-order": {"payables.approve"},
    "prepare-receipt": {"payables.manage"} | PREPARE_PERMISSIONS,
    "review-receipt": {"payables.approve"} | REVIEW_PERMISSIONS,
    "receive": {"payables.manage"} | COMMIT_PERMISSIONS,
    "match-invoice": {"payables.manage", "payables.match"}, "approve-invoice": {"payables.approve"},
    "prepare-accrual": {"payables.manage", "finance_core.manage"},
    "review-accrual": {"payables.approve", "finance_core.validate"},
    "post-accrual": {"payables.approve", "finance_core.post"},
}
for _owner_operation, _purchase_operation in PURCHASE_OPERATIONS.items():
    _authority_operation = {"prepare-receipt-line": "prepare-receipt", "match-invoice-lines": "match-invoice"}.get(
        _purchase_operation, _purchase_operation)
    _owner_permission = "approve" if _owner_operation in {"purchase-approve", "receive-review", "invoice-approve", "invoice-review"} else (
        "post" if _owner_operation in {"receive-commit", "invoice-post"} else "manage")
    PERMISSIONS[_owner_operation] = READ | _PURCHASE_AUTHORITY[_authority_operation] | {
        "manufacturing_supply_plan." + _owner_permission, "budget_control.manage"}
for _native_operation in ("create", "open-rfq", "quote", "review-selection", "award", "cancel"):
    _owner_permission = ("approve" if _native_operation in {"open-rfq", "review-selection", "cancel"}
                         else "post" if _native_operation == "award" else "manage")
    PERMISSIONS["source-" + _native_operation] = READ | SOURCING_PERMISSIONS["read"] | SOURCING_PERMISSIONS[_native_operation] | {
        "manufacturing_supply_plan." + _owner_permission}


@dataclass(frozen=True)
class SupplyPlanPreparation:
    material: OrderPreparation
    routing_id: str
    budget_id: str
    unit_price_ceilings_minor: Mapping[str, int]

    def payload(self) -> dict[str, Any]:
        material = self.material.payload()
        if not isinstance(self.unit_price_ceilings_minor, Mapping) or not 1 <= len(self.unit_price_ceilings_minor) <= MAX_COMPONENTS:
            fail("A planned BOM requires an exact unit-price ceiling for every native component.", "manufacturing_supply_plan_invalid")
        ceilings = {text(key, "component_item_code", maximum=64): exact_integer(value, positive=True)
                    for key, value in self.unit_price_ceilings_minor.items()}
        if len(ceilings) != len(self.unit_price_ceilings_minor):
            fail("Canonical component price-ceiling identities must be distinct.", "manufacturing_supply_plan_invalid")
        return {"schema_version": SCHEMA_VERSION, "material": material,
                "routing_id": text(self.routing_id, "routing_id"), "budget_id": text(self.budget_id, "budget_id"),
                "unit_price_ceilings_minor": dict(sorted(ceilings.items()))}


def plan_requirements(components: Sequence[Mapping[str, Any]], *, batch_output_scaled: int,
                      planned_output_scaled: int, available_scaled: Mapping[str, int],
                      active_reserved_scaled: Mapping[str, int], fifo_free_scaled: Mapping[str, int]) -> list[dict[str, Any]]:
    """Retain exact gross demand, exclusively claim free on-hand, and expose its residual.

    Availability is a native physical stock observation under the same pool
    locks as sales/ME1. The caller persists on-hand claims in that transaction;
    an observation alone is not a reservation or proof of future availability.
    """
    requirements = expand_requirements(components, batch_output_scaled, planned_output_scaled)
    expected = {line["item_id"] for line in requirements}
    if set(available_scaled) != expected or set(active_reserved_scaled) != expected or set(fifo_free_scaled) != expected:
        fail("The complete original BOM population requires one exact native availability/reservation observation per item.",
             "manufacturing_supply_plan_invalid")
    result = []
    for line in requirements:
        available = exact_integer(available_scaled[line["item_id"]])
        reserved = exact_integer(active_reserved_scaled[line["item_id"]])
        if reserved > available:
            fail("Existing native reservations exceed physical stock; refuse a new shortage plan.", "manufacturing_supply_capacity_invalid")
        free = available - reserved
        fifo_free = exact_integer(fifo_free_scaled[line["item_id"]])
        gross = line["required_quantity_scaled"]
        on_hand = min(gross, free, fifo_free)
        shortage = gross - on_hand
        result.append({**line, "gross_quantity_scaled": gross,
                       "observed_available_scaled": available, "observed_reserved_scaled": reserved,
                       "observed_fifo_free_scaled": fifo_free,
                       "onhand_reserved_scaled": on_hand, "shortage_quantity_scaled": shortage,
                       "shortage_quantity": scaled_to_text(shortage, decimal_places=line["quantity_precision"])})
    return result


def procurement_headroom(shortage_scaled: int, active_claim_quantities: Sequence[int]) -> int:
    """A second PR can claim only the original net shortage that is still unclaimed."""
    shortage = exact_integer(shortage_scaled)
    if not isinstance(active_claim_quantities, (tuple, list)) or len(active_claim_quantities) > MAX_PROCUREMENT_CLAIMS:
        fail("A bounded complete active procurement-claim population is required.", "manufacturing_supply_claim_invalid")
    claimed = sum(exact_integer(value, positive=True) for value in active_claim_quantities)
    if claimed > shortage:
        fail("Active procurement claims exceed the original exclusive net shortage.", "manufacturing_supply_claim_invalid")
    return shortage - claimed


def require_complete_handoff(gross_scaled: int, onhand_claim_scaled: int, received_claim_quantities: Sequence[int]) -> None:
    """Only fully covered native stock can transfer atomically into ME1/ME2 reservation."""
    gross = exact_integer(gross_scaled, positive=True)
    onhand = exact_integer(onhand_claim_scaled)
    if not isinstance(received_claim_quantities, (tuple, list)) or len(received_claim_quantities) > MAX_PROCUREMENT_CLAIMS:
        fail("A bounded complete original received-claim population is required.", "manufacturing_supply_handoff_invalid")
    received = sum(exact_integer(value, positive=True) for value in received_claim_quantities)
    if onhand + received != gross or onhand > gross or received > MAX_INTEGER:
        fail("Full source-owned on-hand and actual received quantities must equal original gross BOM demand.", "manufacturing_supply_handoff_invalid")


def planned_requirement_payload(*, identifier: str, plan: Mapping[str, Any], component: Mapping[str, Any],
                                sequence: int) -> dict[str, Any]:
    """Immutable pre-stock engineering demand, separate from ME1's stock reservation."""
    exact_integer(sequence, positive=True)
    return {"schema_version": REQUIREMENT_SCHEMA_VERSION, "id": identifier, "plan_id": plan["id"],
            "plan_digest": plan["source_digest"], "bom_version_id": plan["bom_version_id"],
            "bom_digest": plan["bom_digest"], "routing_id": plan["routing_id"], "routing_digest": plan["routing_digest"],
            "scope": {key: plan[key] for key in ("workspace_id", "organization_id", "legal_entity_id")},
            "sequence": sequence, "location_id": plan["component_location_id"],
            **{key: component[key] for key in ("item_id", "item_code", "uom_id", "uom_code", "quantity_precision",
                                             "inventory_account_id")},
            "gross_quantity_scaled": component["required_quantity_scaled"],
            "gross_quantity": component["required_quantity"]}


def coverage_payload(requirement: Mapping[str, Any], observations: Mapping[str, Any]) -> dict[str, Any]:
    keys = ("observed_available_scaled", "observed_reserved_scaled", "observed_fifo_free_scaled",
            "onhand_reserved_scaled", "shortage_quantity_scaled")
    values = {key: exact_integer(observations[key]) for key in keys}
    gross = exact_integer(requirement["gross_quantity_scaled"], positive=True)
    if values["onhand_reserved_scaled"] + values["shortage_quantity_scaled"] != gross:
        fail("Original coverage must conserve the complete engineering demand.", "manufacturing_supply_capacity_invalid")
    if values["observed_reserved_scaled"] > values["observed_available_scaled"] or values["onhand_reserved_scaled"] != min(
            gross, values["observed_available_scaled"] - values["observed_reserved_scaled"], values["observed_fifo_free_scaled"]):
        fail("Original on-hand claim must reproduce physical and unallocated FIFO observations.", "manufacturing_supply_capacity_invalid")
    return {"schema_version": "manufacturing-supply-coverage-v1", "requirement_id": requirement["id"],
            "requirement_digest": requirement["source_digest"], "gross_quantity_scaled": gross, **values}


@dataclass(frozen=True)
class MRPShortageRequisition:
    """A governed purchase requisition generated from net MRP shortage."""

    requisition_id: str
    plan_id: str
    item_id: str
    shortage_quantity_scaled: int
    planned_order_quantity_scaled: int
    unit_price_minor: int
    required_date: str
    idempotency_key: str
    currency: str = "USD"
    status: str = "approved"

    def __post_init__(self) -> None:
        text(self.requisition_id, "requisition_id", maximum=64)
        text(self.plan_id, "plan_id", maximum=64)
        text(self.item_id, "item_id", maximum=64)
        exact_integer(self.shortage_quantity_scaled, positive=False)
        if self.shortage_quantity_scaled < 0:
            fail("Shortage quantity must be non-negative.", "mrp_requisition_invalid")
        exact_integer(self.planned_order_quantity_scaled, positive=True)
        exact_integer(self.unit_price_minor, positive=False)
        if self.unit_price_minor < 0:
            fail("Unit price minor must be non-negative.", "mrp_requisition_invalid")
        try:
            date.fromisoformat(self.required_date)
        except ValueError:
            fail(f"Invalid required date: {self.required_date}", "mrp_requisition_date_invalid")
        text(self.idempotency_key, "idempotency_key", maximum=128)
        text(self.currency, "currency", maximum=8)
        text(self.status, "status", maximum=32)


def generate_mrp_shortage_requisitions(
    plan_id: str,
    requirements: Sequence[Any],
    *,
    existing_claims: Mapping[str, Sequence[int]] | None = None,
    unit_prices_minor: Mapping[str, int] | None = None,
    required_date: str,
    currency: str = "USD",
) -> list[MRPShortageRequisition]:
    """Generates governed purchase requisitions for net shortages with headroom deduplication.

    Enforces procurement_headroom() to suppress duplicate supply generation when
    prior active claims already cover the shortage. Produces deterministic idempotency keys.
    """
    text(plan_id, "plan_id", maximum=64)
    try:
        date.fromisoformat(required_date)
    except ValueError:
        fail(f"Invalid required date: {required_date}", "mrp_requisition_date_invalid")
    claims_map = existing_claims or {}
    prices_map = unit_prices_minor or {}

    requisitions: list[MRPShortageRequisition] = []

    for req in requirements:
        if isinstance(req, Mapping):
            item_id = str(req.get("item_id", ""))
            shortage = exact_integer(req.get("shortage_quantity_scaled", req.get("shortage", 0)))
            planned_qty = exact_integer(req.get("planned_order_quantity_scaled", req.get("planned_order_quantity", shortage)))
        elif hasattr(req, "item_id"):
            item_id = str(req.item_id)
            shortage = exact_integer(getattr(req, "net_shortage", getattr(req, "shortage_quantity_scaled", 0)))
            planned_qty = exact_integer(getattr(req, "planned_order_quantity", getattr(req, "planned_order_quantity_scaled", shortage)))
        else:
            fail("Invalid requirement record structure.", "mrp_requisition_invalid")

        text(item_id, "item_id", maximum=64)
        if shortage <= 0:
            continue

        item_claims = claims_map.get(item_id, ())
        headroom = procurement_headroom(shortage, item_claims)

        if headroom <= 0:
            # Shortage is already fully covered by active claims; suppress duplicate requisition!
            continue

        # Planned quantity capped by headroom
        actual_req_qty = min(planned_qty, headroom) if planned_qty > 0 else headroom
        unit_price = prices_map.get(item_id, 0)
        exact_integer(unit_price, positive=False)

        raw_key = f"{plan_id}:{item_id}:{headroom}:{required_date}:{currency}"
        idempotency_key = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
        req_id = f"REQ-{item_id}-{idempotency_key[:8].upper()}"

        requisitions.append(
            MRPShortageRequisition(
                requisition_id=req_id,
                plan_id=plan_id,
                item_id=item_id,
                shortage_quantity_scaled=headroom,
                planned_order_quantity_scaled=actual_req_qty,
                unit_price_minor=unit_price,
                required_date=required_date,
                idempotency_key=idempotency_key,
                currency=currency,
                status="approved",
            )
        )

    return sorted(requisitions, key=lambda r: (r.required_date, r.item_id, r.requisition_id))
