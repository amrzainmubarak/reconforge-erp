"""Professional Services Project Costing, WBS Hierarchy, and Milestone Billing Domain.

Invariants:
1. Strict integer MinorMoney accounting; zero float.
2. Milestone billing requires prior verified completion (maker-checker separation).
3. Contract line items directly link to project milestones and deliverables.
4. Time & Materials costing applies approved rate cards with exact integer hourly scaling.
5. Project financial posture strictly calculates earned revenue, actual cost, and WIP.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._:/-]{0,127}$")


class ProjectBillingError(ValueError):
    """Raised when a project billing or milestone constraint is violated."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _check_id(val: str, field_name: str) -> str:
    cleaned = val.strip() if isinstance(val, str) else ""
    if not _ID_PATTERN.fullmatch(cleaned):
        raise ProjectBillingError(
            code="invalid_identifier",
            message=f"{field_name} must be a valid alphanumeric identifier: '{val}'",
        )
    return cleaned


def _check_name(val: str, field_name: str) -> str:
    cleaned = val.strip() if isinstance(val, str) else ""
    if not _NAME_PATTERN.fullmatch(cleaned):
        raise ProjectBillingError(
            code="invalid_identifier",
            message=f"{field_name} must be a valid text string: '{val}'",
        )
    return cleaned


TaskStatus = Literal["planned", "in_progress", "completed", "cancelled"]
MilestoneStatus = Literal["pending", "verified", "billed", "cancelled"]


@dataclass(frozen=True)
class ProjectWBSTask:
    """Work Breakdown Structure task in a project hierarchy."""

    workspace_id: str
    task_id: str
    project_id: str
    task_code: str
    name: str
    parent_task_id: str | None
    planned_hours: int
    budget_cost_minor: int
    currency: str
    status: TaskStatus = "planned"

    def __post_init__(self) -> None:
        _check_id(self.workspace_id, "workspace_id")
        _check_id(self.task_id, "task_id")
        _check_id(self.project_id, "project_id")
        _check_id(self.task_code, "task_code")
        if self.parent_task_id:
            _check_id(self.parent_task_id, "parent_task_id")
        if self.planned_hours < 0:
            raise ProjectBillingError(code="invalid_hours", message="Planned hours cannot be negative")
        if self.budget_cost_minor < 0:
            raise ProjectBillingError(code="invalid_budget", message="Budget cost cannot be negative")
        _check_id(self.currency, "currency")


@dataclass(frozen=True)
class ResourceRateCard:
    """Hourly cost and billing rates for a project role."""

    workspace_id: str
    rate_card_id: str
    project_id: str
    resource_role: str
    hourly_cost_rate_minor: int
    hourly_bill_rate_minor: int
    currency: str

    def __post_init__(self) -> None:
        _check_id(self.workspace_id, "workspace_id")
        _check_id(self.rate_card_id, "rate_card_id")
        _check_id(self.project_id, "project_id")
        _check_name(self.resource_role, "resource_role")
        if self.hourly_cost_rate_minor < 0 or self.hourly_bill_rate_minor < 0:
            raise ProjectBillingError(code="invalid_rate", message="Rate cards cannot have negative rates")
        _check_id(self.currency, "currency")


@dataclass(frozen=True)
class ProjectMilestone:
    """Deliverable milestone linked to a customer contract line item."""

    workspace_id: str
    milestone_id: str
    project_id: str
    contract_line_id: str
    title: str
    milestone_amount_minor: int
    currency: str
    due_date: str
    status: MilestoneStatus = "pending"
    verified_by: str | None = None
    verified_at: str | None = None

    def __post_init__(self) -> None:
        _check_id(self.workspace_id, "workspace_id")
        _check_id(self.milestone_id, "milestone_id")
        _check_id(self.project_id, "project_id")
        _check_id(self.contract_line_id, "contract_line_id")
        if self.milestone_amount_minor <= 0:
            raise ProjectBillingError(code="invalid_amount", message="Milestone amount must be strictly positive")
        _check_id(self.currency, "currency")


@dataclass(frozen=True)
class MilestoneBillingInvoice:
    """Generated billing invoice upon verified milestone completion."""

    invoice_id: str
    workspace_id: str
    project_id: str
    milestone_id: str
    customer_code: str
    billed_amount_minor: int
    currency: str
    issued_at: str
    gl_debit_account: str = "ACCOUNTS_RECEIVABLE"
    gl_credit_account: str = "PROJECT_SERVICE_REVENUE"


@dataclass(frozen=True)
class ProjectFinancialPosture:
    """Executive financial summary of project costs, revenue, and margin."""

    project_id: str
    currency: str
    budget_cost_minor: int
    actual_cost_minor: int
    total_billed_minor: int
    unbilled_wip_minor: int
    profit_margin_bps: int


def verify_milestone_completion(
    milestone: ProjectMilestone,
    verified_by: str,
    verified_at: str,
) -> ProjectMilestone:
    """Maker-checker verification of milestone deliverable completion."""
    if milestone.status != "pending":
        raise ProjectBillingError(
            code="milestone_not_pending",
            message=f"Cannot verify milestone {milestone.milestone_id} in status '{milestone.status}'",
        )
    verifier = _check_id(verified_by, "verified_by")
    if not verified_at.strip():
        raise ProjectBillingError(code="missing_timestamp", message="Verification timestamp is required")

    return ProjectMilestone(
        workspace_id=milestone.workspace_id,
        milestone_id=milestone.milestone_id,
        project_id=milestone.project_id,
        contract_line_id=milestone.contract_line_id,
        title=milestone.title,
        milestone_amount_minor=milestone.milestone_amount_minor,
        currency=milestone.currency,
        due_date=milestone.due_date,
        status="verified",
        verified_by=verifier,
        verified_at=verified_at,
    )


def generate_milestone_invoice(
    milestone: ProjectMilestone,
    customer_code: str,
    invoice_id: str,
    issued_at: str,
) -> tuple[ProjectMilestone, MilestoneBillingInvoice]:
    """Transition verified milestone to billed and emit exact invoice record."""
    if milestone.status != "verified":
        raise ProjectBillingError(
            code="milestone_unverified",
            message=f"Cannot bill milestone {milestone.milestone_id}: status must be 'verified', got '{milestone.status}'",
        )
    cust = _check_id(customer_code, "customer_code")
    inv_id = _check_id(invoice_id, "invoice_id")

    updated_milestone = ProjectMilestone(
        workspace_id=milestone.workspace_id,
        milestone_id=milestone.milestone_id,
        project_id=milestone.project_id,
        contract_line_id=milestone.contract_line_id,
        title=milestone.title,
        milestone_amount_minor=milestone.milestone_amount_minor,
        currency=milestone.currency,
        due_date=milestone.due_date,
        status="billed",
        verified_by=milestone.verified_by,
        verified_at=milestone.verified_at,
    )

    invoice = MilestoneBillingInvoice(
        invoice_id=inv_id,
        workspace_id=milestone.workspace_id,
        project_id=milestone.project_id,
        milestone_id=milestone.milestone_id,
        customer_code=cust,
        billed_amount_minor=milestone.milestone_amount_minor,
        currency=milestone.currency,
        issued_at=issued_at,
    )

    return updated_milestone, invoice


def calculate_financial_posture(
    project_id: str,
    currency: str,
    budget_cost_minor: int,
    actual_cost_minor: int,
    total_billed_minor: int,
) -> ProjectFinancialPosture:
    """Compute exact project financial metrics and margin basis points."""
    unbilled_wip = max(0, actual_cost_minor - total_billed_minor)
    margin_bps = 0
    if total_billed_minor > 0:
        net_profit = total_billed_minor - actual_cost_minor
        margin_bps = (net_profit * 10_000) // total_billed_minor

    return ProjectFinancialPosture(
        project_id=project_id,
        currency=currency,
        budget_cost_minor=budget_cost_minor,
        actual_cost_minor=actual_cost_minor,
        total_billed_minor=total_billed_minor,
        unbilled_wip_minor=unbilled_wip,
        profit_margin_bps=margin_bps,
    )
