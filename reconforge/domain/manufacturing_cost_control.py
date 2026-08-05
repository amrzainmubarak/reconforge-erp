"""Deterministic, non-posting manufacturing production-cost control.

The slice compares local production-order, material-issue, completion, and
scrap exports. It makes cost and quantity exceptions explicit without posting
inventory, WIP, or general-ledger entries.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal, cast

from reconforge.utils.money import Money, Quantity

MANUFACTURING_CONTROL_SCHEMA_VERSION = 1
MANUFACTURING_CONTROL_ALGORITHM_VERSION = "manufacturing-cost-control-v1"
ManufacturingStatus = Literal["reconciled", "exception", "unmatched"]
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,159}$")


class ManufacturingControlError(ValueError):
    """Raised when the closed manufacturing control contract is violated."""


def _identifier(value: object, field: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value.strip()):
        raise ManufacturingControlError(f"{field} is invalid.")
    return value.strip()


def _iso_date(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise ManufacturingControlError(f"{field} must be an ISO-8601 date.")
    try:
        return date.fromisoformat(value.strip()).isoformat()
    except ValueError as exc:
        raise ManufacturingControlError(f"{field} must be an ISO-8601 date.") from exc


def _quantity(value: object, unit: object, field: str, *, allow_zero: bool = True) -> Quantity:
    if isinstance(value, (bool, float)):
        raise ManufacturingControlError(f"{field} must use an exact decimal quantity.")
    if not isinstance(unit, str) or not unit.strip():
        raise ManufacturingControlError(f"{field} unit is invalid.")
    try:
        parsed = Quantity(cast(Decimal, value), unit.strip().upper())
    except Exception as exc:
        raise ManufacturingControlError(f"{field} is not a valid quantity.") from exc
    if not parsed.value.is_finite() or parsed.value < 0 or (not allow_zero and parsed.value == 0):
        raise ManufacturingControlError(f"{field} must be finite and non-negative.")
    return parsed


def _money(value: object, currency: object, field: str) -> Money:
    if isinstance(value, (bool, float)) or not isinstance(currency, str):
        raise ManufacturingControlError(f"{field} must use an exact decimal Money value.")
    try:
        parsed = Money.from_exact(value, currency.strip().upper())
    except Exception as exc:
        raise ManufacturingControlError(f"{field} is not a valid Money value.") from exc
    if not parsed.amount.is_finite():
        raise ManufacturingControlError(f"{field} must be finite.")
    return parsed


def _same_unit(left: Quantity, right: Quantity, field: str) -> None:
    if left.unit != right.unit:
        raise ManufacturingControlError(f"{field} units must match.")


def _money_dict(value: Money) -> dict[str, object]:
    return value.to_canonical_dict()


def _quantity_dict(value: Quantity) -> dict[str, object]:
    return {"scale": value.scale, "unit": value.unit, "value": str(value.value)}


def _digest(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    ).hexdigest()


@dataclass(frozen=True)
class ProductionOrder:
    order_id: str
    product_id: str
    planned_quantity: Quantity
    standard_unit_cost: Money
    source_reference: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "order_id", _identifier(self.order_id, "production order ID"))
        object.__setattr__(self, "product_id", _identifier(self.product_id, "product ID"))
        if not isinstance(self.planned_quantity, Quantity) or not self.planned_quantity.value.is_finite():
            raise ManufacturingControlError("planned quantity must be finite Quantity.")
        if not isinstance(self.standard_unit_cost, Money) or not self.standard_unit_cost.amount.is_finite():
            raise ManufacturingControlError("standard unit cost must be finite Money.")
        object.__setattr__(self, "source_reference", _identifier(self.source_reference, "order source reference"))


@dataclass(frozen=True)
class MaterialIssue:
    issue_id: str
    order_id: str
    item_id: str
    quantity: Quantity
    unit_cost: Money
    source_reference: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "issue_id", _identifier(self.issue_id, "material issue ID"))
        object.__setattr__(self, "order_id", _identifier(self.order_id, "issue order ID"))
        object.__setattr__(self, "item_id", _identifier(self.item_id, "material item ID"))
        if not isinstance(self.quantity, Quantity) or not self.quantity.value.is_finite():
            raise ManufacturingControlError("issue quantity must be finite Quantity.")
        if not isinstance(self.unit_cost, Money) or not self.unit_cost.amount.is_finite():
            raise ManufacturingControlError("issue unit cost must be finite Money.")
        object.__setattr__(self, "source_reference", _identifier(self.source_reference, "issue source reference"))

    @property
    def extended_cost(self) -> Money:
        return self.unit_cost.multiply_exact(self.quantity.value)


@dataclass(frozen=True)
class ProductionCompletion:
    completion_id: str
    order_id: str
    completion_date: str
    quantity: Quantity
    actual_cost: Money
    source_reference: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "completion_id", _identifier(self.completion_id, "completion ID"))
        object.__setattr__(self, "order_id", _identifier(self.order_id, "completion order ID"))
        object.__setattr__(self, "completion_date", _iso_date(self.completion_date, "completion date"))
        if not isinstance(self.quantity, Quantity) or not self.quantity.value.is_finite():
            raise ManufacturingControlError("completion quantity must be finite Quantity.")
        if not isinstance(self.actual_cost, Money) or not self.actual_cost.amount.is_finite():
            raise ManufacturingControlError("completion cost must be finite Money.")
        object.__setattr__(self, "source_reference", _identifier(self.source_reference, "completion source reference"))


@dataclass(frozen=True)
class ScrapEvent:
    scrap_id: str
    order_id: str
    scrap_date: str
    quantity: Quantity
    reason: str
    source_reference: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "scrap_id", _identifier(self.scrap_id, "scrap ID"))
        object.__setattr__(self, "order_id", _identifier(self.order_id, "scrap order ID"))
        object.__setattr__(self, "scrap_date", _iso_date(self.scrap_date, "scrap date"))
        if not isinstance(self.quantity, Quantity) or not self.quantity.value.is_finite():
            raise ManufacturingControlError("scrap quantity must be finite Quantity.")
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ManufacturingControlError("scrap reason is required.")
        object.__setattr__(self, "reason", self.reason.strip()[:160])
        object.__setattr__(self, "source_reference", _identifier(self.source_reference, "scrap source reference"))


@dataclass(frozen=True)
class ManufacturingDecision:
    order_id: str
    product_id: str
    status: ManufacturingStatus
    planned_quantity: Quantity
    issued_quantity: Quantity
    completed_quantity: Quantity
    scrap_quantity: Quantity
    expected_material_cost: Money
    actual_material_cost: Money
    completion_cost: Money
    material_cost_variance: Money
    completion_cost_variance: Money
    reason_codes: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "actual_material_cost": _money_dict(self.actual_material_cost),
            "completed_quantity": _quantity_dict(self.completed_quantity),
            "completion_cost": _money_dict(self.completion_cost),
            "completion_cost_variance": _money_dict(self.completion_cost_variance),
            "expected_material_cost": _money_dict(self.expected_material_cost),
            "issued_quantity": _quantity_dict(self.issued_quantity),
            "material_cost_variance": _money_dict(self.material_cost_variance),
            "order_id": self.order_id,
            "planned_quantity": _quantity_dict(self.planned_quantity),
            "product_id": self.product_id,
            "reason_codes": list(self.reason_codes),
            "scrap_quantity": _quantity_dict(self.scrap_quantity),
            "status": self.status,
        }


@dataclass(frozen=True)
class ManufacturingControlRun:
    schema_version: int
    algorithm_version: str
    amount_tolerance: Money
    max_scrap_quantity: Quantity
    input_digests: tuple[str, ...]
    decisions: tuple[ManufacturingDecision, ...]
    decision_digest: str

    @property
    def status_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for decision in self.decisions:
            counts[decision.status] = counts.get(decision.status, 0) + 1
        return dict(sorted(counts.items()))

    def to_dict(self) -> dict[str, object]:
        return {
            "algorithm_version": self.algorithm_version,
            "amount_tolerance": self.amount_tolerance.to_canonical_dict(),
            "decision_digest": self.decision_digest,
            "decisions": [decision.to_dict() for decision in self.decisions],
            "input_digests": list(self.input_digests),
            "max_scrap_quantity": _quantity_dict(self.max_scrap_quantity),
            "schema_version": self.schema_version,
            "status_counts": self.status_counts,
        }


def _zero_quantity(unit: str) -> Quantity:
    return Quantity(Decimal("0"), unit)


def _sum_quantities(values: list[Quantity], *, unit: str) -> Quantity:
    for value in values:
        if value.unit != unit:
            raise ManufacturingControlError("quantities within an order must use one unit.")
    total = sum((value.value for value in values), Decimal("0"))
    return Quantity(total, unit)


def _sum_money(values: list[Money], *, currency: str) -> Money:
    total = Money.from_exact("0", currency)
    for value in values:
        if value.currency != currency:
            raise ManufacturingControlError("all manufacturing costs must use one currency.")
        total = total + value
    return total


def run_manufacturing_cost_control(
    orders: tuple[ProductionOrder, ...],
    issues: tuple[MaterialIssue, ...],
    completions: tuple[ProductionCompletion, ...],
    scrap_events: tuple[ScrapEvent, ...],
    *,
    amount_tolerance: Money,
    max_scrap_quantity: Quantity,
    input_digests: tuple[str, ...] = (),
) -> ManufacturingControlRun:
    """Evaluate bounded production-order cost, quantity, completion, and scrap controls."""

    if not isinstance(amount_tolerance, Money) or amount_tolerance.amount < 0:
        raise ManufacturingControlError("amount tolerance must be non-negative Money.")
    if not isinstance(max_scrap_quantity, Quantity) or max_scrap_quantity.value < 0:
        raise ManufacturingControlError("maximum scrap quantity must be non-negative Quantity.")
    if not orders:
        raise ManufacturingControlError("manufacturing control requires at least one production order.")
    order_ids = [item.order_id for item in orders]
    if len(order_ids) != len(set(order_ids)):
        raise ManufacturingControlError("production order IDs must be unique.")
    for order in orders:
        if order.standard_unit_cost.currency != amount_tolerance.currency:
            raise ManufacturingControlError("all manufacturing costs must use one currency.")
        if order.planned_quantity.unit != max_scrap_quantity.unit:
            raise ManufacturingControlError("production and scrap quantities must use one unit.")
    for collection, label, id_attribute in (
        (issues, "material issue", "issue_id"),
        (completions, "completion", "completion_id"),
        (scrap_events, "scrap", "scrap_id"),
    ):
        ids = [getattr(item, id_attribute) for item in collection]
        if len(ids) != len(set(ids)):
            raise ManufacturingControlError(f"{label} IDs must be unique.")
    order_by_id = {item.order_id: item for item in orders}
    issues_by_order: dict[str, list[MaterialIssue]] = {}
    completions_by_order: dict[str, list[ProductionCompletion]] = {}
    scrap_by_order: dict[str, list[ScrapEvent]] = {}
    decisions: list[ManufacturingDecision] = []
    for issue in issues:
        issues_by_order.setdefault(issue.order_id, []).append(issue)
    for completion in completions:
        completions_by_order.setdefault(completion.order_id, []).append(completion)
    for scrap in scrap_events:
        scrap_by_order.setdefault(scrap.order_id, []).append(scrap)
    referenced_order_ids = set(issues_by_order) | set(completions_by_order) | set(scrap_by_order)
    for order_id in sorted(referenced_order_ids - set(order_by_id)):
        if order_id not in order_by_id:
            decisions.append(
                ManufacturingDecision(
                    order_id,
                    "UNKNOWN-PRODUCT",
                    "unmatched",
                    _zero_quantity(max_scrap_quantity.unit),
                    _zero_quantity(max_scrap_quantity.unit),
                    _zero_quantity(max_scrap_quantity.unit),
                    _zero_quantity(max_scrap_quantity.unit),
                    Money.from_exact("0", amount_tolerance.currency),
                    Money.from_exact("0", amount_tolerance.currency),
                    Money.from_exact("0", amount_tolerance.currency),
                    Money.from_exact("0", amount_tolerance.currency),
                    Money.from_exact("0", amount_tolerance.currency),
                    ("SOURCE_RECORD_REFERENCES_UNKNOWN_PRODUCTION_ORDER",),
                )
            )
    for order in sorted(orders, key=lambda item: item.order_id):
        order_issues = sorted(issues_by_order.get(order.order_id, []), key=lambda item: item.issue_id)
        order_completions = sorted(completions_by_order.get(order.order_id, []), key=lambda item: item.completion_id)
        order_scrap = sorted(scrap_by_order.get(order.order_id, []), key=lambda item: item.scrap_id)
        issued_quantity = _sum_quantities([item.quantity for item in order_issues], unit=order.planned_quantity.unit)
        completed_quantity = _sum_quantities([item.quantity for item in order_completions], unit=order.planned_quantity.unit)
        scrap_quantity = _sum_quantities([item.quantity for item in order_scrap], unit=order.planned_quantity.unit)
        expected_cost = order.standard_unit_cost.multiply_exact(order.planned_quantity.value)
        actual_cost = _sum_money([item.extended_cost for item in order_issues], currency=amount_tolerance.currency)
        completion_cost = _sum_money([item.actual_cost for item in order_completions], currency=amount_tolerance.currency)
        material_variance = actual_cost - expected_cost
        completion_variance = completion_cost - actual_cost
        reasons: list[str] = []
        if not order_issues and order_completions:
            reasons.append("ORDER_HAS_NO_MATERIAL_ISSUE")
        if order_issues and not order_completions:
            reasons.append("ORDER_HAS_NO_COMPLETION")
        if abs(material_variance.amount) > amount_tolerance.amount:
            reasons.append("MATERIAL_COST_VARIANCE")
        if order_completions and abs(completion_variance.amount) > amount_tolerance.amount:
            reasons.append("COMPLETION_COST_RECONCILIATION_VARIANCE")
        if completed_quantity.value > order.planned_quantity.value:
            reasons.append("COMPLETED_QUANTITY_EXCEEDS_PLAN")
        if scrap_quantity.value > max_scrap_quantity.value:
            reasons.append("SCRAP_EXCEEDS_CONTROL_LIMIT")
        decisions.append(
            ManufacturingDecision(
                order.order_id,
                order.product_id,
                "exception" if reasons else "reconciled",
                order.planned_quantity,
                issued_quantity,
                completed_quantity,
                scrap_quantity,
                expected_cost,
                actual_cost,
                completion_cost,
                material_variance,
                completion_variance,
                tuple(reasons) if reasons else ("MANUFACTURING_ORDER_RECONCILED",),
            )
        )
    ordered = tuple(sorted(decisions, key=lambda item: (item.order_id, item.status, item.reason_codes)))
    payload = {
        "algorithm_version": MANUFACTURING_CONTROL_ALGORITHM_VERSION,
        "amount_tolerance": amount_tolerance.to_canonical_dict(),
        "decisions": [item.to_dict() for item in ordered],
        "input_digests": sorted(set(input_digests)),
        "max_scrap_quantity": _quantity_dict(max_scrap_quantity),
        "schema_version": MANUFACTURING_CONTROL_SCHEMA_VERSION,
    }
    return ManufacturingControlRun(
        MANUFACTURING_CONTROL_SCHEMA_VERSION,
        MANUFACTURING_CONTROL_ALGORITHM_VERSION,
        amount_tolerance,
        max_scrap_quantity,
        tuple(sorted(set(input_digests))),
        ordered,
        _digest(payload),
    )


__all__ = [
    "MANUFACTURING_CONTROL_ALGORITHM_VERSION",
    "MANUFACTURING_CONTROL_SCHEMA_VERSION",
    "ManufacturingControlError",
    "ManufacturingControlRun",
    "ManufacturingDecision",
    "MaterialIssue",
    "ProductionCompletion",
    "ProductionOrder",
    "ScrapEvent",
    "run_manufacturing_cost_control",
]
