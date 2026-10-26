"""Quality Inspection Plans, Non-Conformance Reports (NCR), and Rework Work Orders.

Enforces zero-float tolerance checking, material quarantine workflows,
MRB disposition governance, and exact integer rework cost accumulation.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

from reconforge.domain.finance_posting import FinancePostingError, text
from reconforge.domain.manufacturing_execution import exact_integer, fail
from reconforge.domain.models import utc_now_text

DefectSeverity = Literal["minor", "major", "critical"]
NCRStatus = Literal["open", "under_review", "dispositioned", "closed"]
NCRDisposition = Literal["scrap", "rework", "return_to_vendor", "use_as_is"]
ReworkStatus = Literal["draft", "released", "in_progress", "completed", "cancelled"]


class QualityReworkError(FinancePostingError):
    """Raised when quality inspection, NCR, or rework constraints are violated."""


def require_independent_quality_actor(creator_user_id: str | None, reviewer_user_id: str) -> None:
    """Compare verified stable identities; display labels are never authority."""
    if creator_user_id is None:
        raise QualityReworkError("quality_actor_authority_missing", "Verified NCR creator authority is required.")
    if text(creator_user_id, "creator_user_id") == text(reviewer_user_id, "reviewer_user_id"):
        raise QualityReworkError("quality_self_disposition_denied", "Independent NCR disposition is required.")


@dataclass(frozen=True)
class QualitySpecification:
    """Individual parameter specification and numeric tolerance band."""

    param_name: str
    target_value: int
    tolerance_lower: int  # Acceptable minimum (must be <= target_value)
    tolerance_upper: int  # Acceptable maximum (must be >= target_value)
    unit_of_measure: str = "scaled"
    is_critical: bool = True

    def __post_init__(self) -> None:
        text(self.param_name, "param_name", maximum=64)
        exact_integer(self.target_value)
        exact_integer(self.tolerance_lower)
        exact_integer(self.tolerance_upper)
        text(self.unit_of_measure, "unit_of_measure", maximum=16)
        if self.tolerance_lower > self.target_value:
            fail(
                f"Lower tolerance {self.tolerance_lower} cannot exceed target {self.target_value}.",
                "quality_tolerance_invalid",
            )
        if self.tolerance_upper < self.target_value:
            fail(
                f"Upper tolerance {self.tolerance_upper} cannot be less than target {self.target_value}.",
                "quality_tolerance_invalid",
            )

    def is_conforming(self, measured_value: int) -> bool:
        exact_integer(measured_value)
        return self.tolerance_lower <= measured_value <= self.tolerance_upper


@dataclass(frozen=True)
class QualityInspectionPlan:
    """Quality control plan for an item with parameter specifications."""

    plan_id: str
    item_id: str
    revision: str
    name: str
    sample_size_units: int
    specifications: tuple[QualitySpecification, ...]

    def __post_init__(self) -> None:
        text(self.plan_id, "plan_id", maximum=64)
        text(self.item_id, "item_id", maximum=64)
        text(self.revision, "revision", maximum=32)
        text(self.name, "name", maximum=160)
        exact_integer(self.sample_size_units, positive=True)
        if not self.specifications:
            fail("Inspection plan must specify at least one parameter.", "quality_specs_empty")

    def evaluate_measurements(self, measurements: dict[str, int]) -> tuple[bool, list[str]]:
        """Evaluates measured parameters against specifications.
        
        Returns (is_passed, list_of_defect_descriptions).
        """
        defects: list[str] = []
        for spec in self.specifications:
            if spec.param_name not in measurements:
                defects.append(f"Missing required inspection parameter: {spec.param_name}")
                continue
            measured = measurements[spec.param_name]
            if not spec.is_conforming(measured):
                defects.append(
                    f"Parameter '{spec.param_name}' measured {measured} outside tolerance "
                    f"[{spec.tolerance_lower}, {spec.tolerance_upper}]."
                )
        return len(defects) == 0, defects


@dataclass(frozen=True)
class NonConformanceReport:
    """Formal Non-Conformance Report (NCR) for quarantined material and MRB review."""

    ncr_id: str
    lot_id: str
    work_order_id: str
    defect_code: str
    defect_severity: DefectSeverity
    inspector_id: str
    quarantined_quantity_scaled: int
    status: NCRStatus = "open"
    disposition: NCRDisposition | None = None
    disposition_notes: str | None = None
    disposition_by: str | None = None
    disposition_at: str | None = None
    created_at: str = ""

    def __post_init__(self) -> None:
        text(self.ncr_id, "ncr_id", maximum=64)
        text(self.lot_id, "lot_id", maximum=64)
        text(self.work_order_id, "work_order_id", maximum=64)
        text(self.defect_code, "defect_code", maximum=64)
        text(self.inspector_id, "inspector_id", maximum=64)
        exact_integer(self.quarantined_quantity_scaled, positive=True)
        if not self.created_at:
            object.__setattr__(self, "created_at", utc_now_text())

    def disposition_ncr(
        self,
        *,
        disposition: NCRDisposition,
        notes: str,
        actor: str,
    ) -> NonConformanceReport:
        """Applies MRB disposition and transitions status."""
        if self.status not in ("open", "under_review"):
            raise QualityReworkError(
                "ncr_already_dispositioned",
                f"NCR '{self.ncr_id}' status '{self.status}' cannot be dispositioned.",
            )
        text(notes, "disposition_notes", maximum=255)
        text(actor, "disposition_by", maximum=64)
        return replace(
            self,
            status="dispositioned",
            disposition=disposition,
            disposition_notes=notes,
            disposition_by=actor,
            disposition_at=utc_now_text(),
        )

    def close_ncr(self, *, actor: str) -> NonConformanceReport:
        """Closes the NCR after disposition execution."""
        if self.status != "dispositioned":
            raise QualityReworkError(
                "ncr_not_dispositioned",
                f"NCR '{self.ncr_id}' cannot be closed before disposition (current status: '{self.status}').",
            )
        text(actor, "actor", maximum=64)
        return replace(self, status="closed")


@dataclass(frozen=True)
class ReworkRoutingStep:
    """Individual rework routing operation."""

    step_number: int
    work_center_id: str
    operation_description: str
    estimated_minutes: int
    actual_minutes: int = 0
    labor_rate_hourly_minor: int = 0  # In integer minor currency units

    def __post_init__(self) -> None:
        if self.step_number < 1:
            fail("Step number must be >= 1.", "rework_step_invalid")
        text(self.work_center_id, "work_center_id", maximum=64)
        text(self.operation_description, "operation_description", maximum=160)
        exact_integer(self.estimated_minutes, positive=True)
        exact_integer(self.actual_minutes)
        exact_integer(self.labor_rate_hourly_minor)


@dataclass(frozen=True)
class ReworkOrder:
    """Dedicated rework work order linked to an NCR with cost accumulation."""

    rework_order_id: str
    parent_work_order_id: str
    ncr_id: str
    item_id: str
    rework_quantity_scaled: int
    rework_routing_steps: tuple[ReworkRoutingStep, ...]
    rework_cost_center: str
    status: ReworkStatus = "draft"
    accumulated_rework_cost_minor: int = 0
    created_at: str = ""
    completed_at: str | None = None

    def __post_init__(self) -> None:
        text(self.rework_order_id, "rework_order_id", maximum=64)
        text(self.parent_work_order_id, "parent_work_order_id", maximum=64)
        text(self.ncr_id, "ncr_id", maximum=64)
        text(self.item_id, "item_id", maximum=64)
        exact_integer(self.rework_quantity_scaled, positive=True)
        text(self.rework_cost_center, "rework_cost_center", maximum=64)
        exact_integer(self.accumulated_rework_cost_minor)
        if not self.rework_routing_steps:
            fail("Rework order must define at least one routing step.", "rework_steps_empty")
        if not self.created_at:
            object.__setattr__(self, "created_at", utc_now_text())

    def release(self) -> ReworkOrder:
        if self.status != "draft":
            raise QualityReworkError("rework_not_draft", f"Rework order '{self.rework_order_id}' cannot be released from status '{self.status}'.")
        return replace(self, status="released")

    def log_rework_step(
        self,
        *,
        step_number: int,
        actual_minutes: int,
        labor_rate_hourly_minor: int,
    ) -> ReworkOrder:
        """Logs execution of a rework operation step and accumulates integer labor cost."""
        if self.status not in ("released", "in_progress"):
            raise QualityReworkError(
                "rework_invalid_status",
                f"Cannot log rework step on order in status '{self.status}'.",
            )
        exact_integer(actual_minutes, positive=True)
        exact_integer(labor_rate_hourly_minor, positive=True)

        found = False
        new_steps: list[ReworkRoutingStep] = []
        for step in self.rework_routing_steps:
            if step.step_number == step_number:
                found = True
                updated_step = replace(
                    step,
                    actual_minutes=step.actual_minutes + actual_minutes,
                    labor_rate_hourly_minor=labor_rate_hourly_minor,
                )
                new_steps.append(updated_step)
            else:
                new_steps.append(step)

        if not found:
            raise QualityReworkError(
                "rework_step_not_found",
                f"Step {step_number} not found in rework order '{self.rework_order_id}'.",
            )

        # Exact integer labor cost: (minutes * hourly_rate + 30) // 60 (rounded half-up)
        step_cost_minor = (actual_minutes * labor_rate_hourly_minor + 30) // 60

        return replace(
            self,
            status="in_progress",
            rework_routing_steps=tuple(new_steps),
            accumulated_rework_cost_minor=self.accumulated_rework_cost_minor + step_cost_minor,
        )

    def complete(self, *, actor: str) -> ReworkOrder:
        """Completes the rework order after all operations are completed."""
        if self.status not in ("released", "in_progress"):
            raise QualityReworkError(
                "rework_invalid_status",
                f"Rework order '{self.rework_order_id}' in status '{self.status}' cannot be completed.",
            )
        text(actor, "actor", maximum=64)
        return replace(
            self,
            status="completed",
            completed_at=utc_now_text(),
        )


__all__ = [
    "DefectSeverity",
    "NCRDisposition",
    "NCRStatus",
    "NonConformanceReport",
    "QualityInspectionPlan",
    "QualityReworkError",
    "QualitySpecification",
    "ReworkOrder",
    "ReworkRoutingStep",
    "ReworkStatus",
]
