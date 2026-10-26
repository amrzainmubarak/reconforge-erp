"""Typed quality-record serialization shared by the two persistence adapters."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import asdict
from datetime import datetime
from typing import Any

from reconforge.domain.manufacturing_quality_rework import (
    NonConformanceReport,
    QualityInspectionPlan,
    QualitySpecification,
    ReworkOrder,
    ReworkRoutingStep,
)

NCR_FIELDS = (
    "ncr_id",
    "lot_id",
    "work_order_id",
    "defect_code",
    "defect_severity",
    "inspector_id",
    "quarantined_quantity_scaled",
    "status",
    "disposition",
    "disposition_notes",
    "disposition_by",
    "disposition_at",
    "created_at",
)
REWORK_FIELDS = (
    "rework_order_id",
    "parent_work_order_id",
    "ncr_id",
    "item_id",
    "rework_quantity_scaled",
    "rework_routing_steps",
    "rework_cost_center",
    "status",
    "accumulated_rework_cost_minor",
    "created_at",
    "completed_at",
)


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def plan_values(plan: QualityInspectionPlan) -> tuple[object, ...]:
    return (
        plan.plan_id,
        plan.item_id,
        plan.revision,
        plan.name,
        plan.sample_size_units,
        canonical_json([asdict(spec) for spec in plan.specifications]),
    )


def plan_from_row(row: Sequence[Any]) -> QualityInspectionPlan:
    return QualityInspectionPlan(
        plan_id=row[0],
        item_id=row[1],
        revision=row[2],
        name=row[3],
        sample_size_units=row[4],
        specifications=tuple(QualitySpecification(**spec) for spec in json.loads(row[5])),
    )


def ncr_values(ncr: NonConformanceReport) -> tuple[object, ...]:
    return tuple(asdict(ncr)[name] for name in NCR_FIELDS)


def ncr_from_row(row: Sequence[Any]) -> NonConformanceReport:
    values = dict(zip(NCR_FIELDS, row, strict=True))
    for name in ("created_at", "disposition_at"):
        if isinstance(values[name], datetime):
            values[name] = values[name].isoformat()
    return NonConformanceReport(**values)


def rework_values(rework: ReworkOrder) -> tuple[object, ...]:
    values = asdict(rework)
    values["rework_routing_steps"] = canonical_json(values["rework_routing_steps"])
    return tuple(values[name] for name in REWORK_FIELDS)


def rework_from_row(row: Sequence[Any]) -> ReworkOrder:
    values = dict(zip(REWORK_FIELDS, row, strict=True))
    values["rework_routing_steps"] = tuple(
        ReworkRoutingStep(**step) for step in json.loads(values["rework_routing_steps"])
    )
    for name in ("created_at", "completed_at"):
        if isinstance(values[name], datetime):
            values[name] = values[name].isoformat()
    return ReworkOrder(**values)
