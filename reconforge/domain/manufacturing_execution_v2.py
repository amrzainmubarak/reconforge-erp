"""ME2: retained expense-backed actual costing and inspected production.

Material costing remains owned by ME1. These values describe the additional
manufacturing source, not a second stock, currency, or general-ledger engine.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from reconforge.domain.finance_posting import text
from reconforge.domain.manufacturing_execution import (
    PERMISSIONS as MATERIAL_PERMISSIONS,
)
from reconforge.domain.manufacturing_execution import (
    READ as MATERIAL_READ,
)
from reconforge.domain.manufacturing_execution import (
    OrderPreparation,
    allocate_disposition,
    business_date,
    exact_integer,
    fail,
)

MAX_OPERATIONS = 50
MAX_COST_CLAIMS = 100
MAX_PRODUCTIONS = 200
READ = MATERIAL_READ | {"manufacturing_execution_v2.read"}
PERMISSIONS = {
    "create": MATERIAL_PERMISSIONS["create"] | READ | {"manufacturing_execution_v2.manage"},
    "prepare": MATERIAL_PERMISSIONS["prepare"] | READ | {"manufacturing_execution_v2.manage"},
    "review": MATERIAL_PERMISSIONS["review"] | READ | {"manufacturing_execution_v2.approve"},
    "post": MATERIAL_PERMISSIONS["post"] | READ | {"manufacturing_execution_v2.post"},
    "approve": MATERIAL_PERMISSIONS["approve-bom"] | READ | {"manufacturing_execution_v2.approve"},
    "cancel": MATERIAL_PERMISSIONS["cancel"] | READ | {"manufacturing_execution_v2.approve"},
}
SCOPE_FIELDS = ("workspace_id", "organization_id", "legal_entity_id", "organization_code", "entity_code")


def scope_payload(scope: Mapping[str, Any]) -> dict[str, str]:
    return {key: text(scope[key], key) for key in SCOPE_FIELDS}


def effective_dates(start: object, end: object) -> tuple[str, str]:
    first, last = business_date(start), business_date(end)
    if date.fromisoformat(first) > date.fromisoformat(last):
        fail("A manufacturing revision needs an ordered effective-date interval.")
    return first, last


def claimed_cost(minutes: object, rate_minor_per_hour: object) -> int:
    """Exact HALF_EVEN rate/time valuation, subsequently capped by original expense."""
    duration = exact_integer(minutes, positive=True)
    rate = exact_integer(rate_minor_per_hour, positive=True)
    base, residual = divmod(duration * rate, 60)
    value = base + int(residual * 2 > 60 or residual * 2 == 60 and base % 2 == 1)
    return exact_integer(value, positive=True)


def cost_claims(values: Sequence[Mapping[str, Any]], operations: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    if not 1 <= len(values) <= MAX_COST_CLAIMS:
        fail("ME2 requires one to one hundred original posted labor/overhead expense claims.")
    sequences = {operation["sequence"] for operation in operations}
    seen: set[tuple[str, str]] = set()
    result = []
    for claim in values:
        if set(claim) != {"effect_id", "line_id", "kind", "operation_sequence", "minutes", "rate_minor_per_hour"}:
            fail("A cost claim needs its exact original effect/line, kind, operation, time and rate.")
        effect, line = text(claim["effect_id"], "effect_id"), text(claim["line_id"], "line_id")
        if (effect, line) in seen or claim["kind"] not in {"Labor", "Overhead"}:
            fail("Each original expense line is claimed once per order with explicit Labor or Overhead treatment.")
        sequence = exact_integer(claim["operation_sequence"], positive=True)
        if sequence not in sequences:
            fail("Claimed production cost must name an actual retained routing operation.")
        seen.add((effect, line))
        result.append({**dict(claim), "effect_id": effect, "line_id": line,
                       "amount_minor": claimed_cost(claim["minutes"], claim["rate_minor_per_hour"])})
    return sorted(result, key=lambda row: (row["effect_id"], row["line_id"]))


def routing_operations(values: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    if not 1 <= len(values) <= MAX_OPERATIONS:
        fail("A routing requires one to fifty ordered actual workcenter operations.")
    result = []
    for index, value in enumerate(values, 1):
        if set(value) != {"sequence", "workcenter_id", "name", "minutes_per_batch"}:
            fail("An operation requires sequence, approved workcenter, name and exact minutes per batch.")
        if exact_integer(value["sequence"], positive=True) != index:
            fail("Routing operations must be supplied in contiguous execution order starting at one.")
        result.append({"sequence": index, "workcenter_id": text(value["workcenter_id"], "workcenter_id"),
                       "name": text(value["name"], "name", maximum=160),
                       "minutes_per_batch": exact_integer(value["minutes_per_batch"], positive=True)})
    return result


def operation_reports(values: Sequence[Mapping[str, Any]], operations: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    if len(values) != len(operations):
        fail("Production evidence must retain every approved routing operation exactly once in order.")
    result = []
    for value, original in zip(values, operations, strict=True):
        if set(value) != {"sequence", "minutes", "evidence_reference"}:
            fail("Execution evidence requires exact operation sequence, actual minutes and source reference.")
        if type(value["sequence"]) is not int or value["sequence"] != original["sequence"]:
            fail("Actual execution cannot omit, duplicate or reorder the approved operations.")
        result.append({"sequence": original["sequence"], "minutes": exact_integer(value["minutes"], positive=True),
                       "evidence_reference": text(value["evidence_reference"], "evidence_reference", maximum=500)})
    return result


def held_allocation(*, output_quantity: int, total_cost: int, produced_quantity: int,
                    produced_cost: int, quantity: int) -> dict[str, int]:
    allocation = allocate_disposition(original_quantity=output_quantity, original_cost=total_cost,
        disposed_quantity=produced_quantity, released_cost=produced_cost, good_quantity=quantity, scrap_quantity=0)
    return {"quantity_scaled": allocation["stage_quantity_scaled"], "held_cost_minor": allocation["released_cost_minor"],
            "produced_before_scaled": produced_quantity, "produced_cost_before_minor": produced_cost}


def inspection_allocation(*, held_quantity: int, held_cost: int, accepted_quantity: int,
                          rejected_quantity: int) -> dict[str, int]:
    if exact_integer(accepted_quantity) + exact_integer(rejected_quantity) != exact_integer(held_quantity, positive=True):
        fail("An inspection must disposition its complete immutable held tranche exactly once.")
    allocation = allocate_disposition(original_quantity=held_quantity, original_cost=held_cost, disposed_quantity=0,
        released_cost=0, good_quantity=accepted_quantity, scrap_quantity=rejected_quantity)
    return {"accepted_quantity_scaled": accepted_quantity, "rejected_quantity_scaled": rejected_quantity,
            "accepted_cost_minor": allocation["good_cost_minor"], "rejected_cost_minor": allocation["scrap_cost_minor"],
            "released_cost_minor": allocation["released_cost_minor"]}


@dataclass(frozen=True)
class WorkcenterPreparation:
    code: str
    version: int
    name: str
    effective_from: str
    effective_until: str
    scope: Mapping[str, Any]
    reason: str

    def payload(self) -> dict[str, Any]:
        first, last = effective_dates(self.effective_from, self.effective_until)
        return {"schema_version": "manufacturing-workcenter-v2", "code": text(self.code, "code", maximum=64),
                "version": exact_integer(self.version, positive=True), "name": text(self.name, "name", maximum=160),
                "effective_from": first, "effective_until": last, **scope_payload(self.scope),
                "reason": text(self.reason, "reason", maximum=500)}


@dataclass(frozen=True)
class RoutingPreparation:
    number: str
    version: int
    bom_version_id: str
    effective_from: str
    effective_until: str
    operations: Sequence[Mapping[str, Any]]
    scope: Mapping[str, Any]
    reason: str

    def payload(self) -> dict[str, Any]:
        first, last = effective_dates(self.effective_from, self.effective_until)
        return {"schema_version": "manufacturing-routing-v2", "number": text(self.number, "number", maximum=64),
                "version": exact_integer(self.version, positive=True), "bom_version_id": text(self.bom_version_id, "bom_version_id"),
                "effective_from": first, "effective_until": last, "operations": routing_operations(self.operations),
                **scope_payload(self.scope), "reason": text(self.reason, "reason", maximum=500)}


@dataclass(frozen=True)
class ManufacturingOrderPreparation:
    material: OrderPreparation
    routing_id: str
    claims: Sequence[Mapping[str, Any]]

    def payload(self) -> dict[str, Any]:
        return {"schema_version": "manufacturing-order-v2", "material": self.material.payload(),
                "routing_id": text(self.routing_id, "routing_id"), "claims": [dict(value) for value in self.claims],
                **scope_payload(self.material.payload())}
