"""Tests for Project Milestone Billing API schemas and SQLite repository."""

from __future__ import annotations

import sqlite3

import pytest
from pydantic import ValidationError

from reconforge.api.routes.project_milestone_billing import (
    MilestoneRequest,
    WBSTaskRequest,
)
from reconforge.domain.project_milestone_billing import (
    ProjectMilestone,
    ProjectWBSTask,
    ResourceRateCard,
    generate_milestone_invoice,
    verify_milestone_completion,
)
from reconforge.infrastructure.sqlite_project_billing import (
    SqliteProjectBillingRepository,
)


def test_project_billing_schemas():
    """Verify schema constraints and validations."""
    valid_task = {
        "task_id": "T-100",
        "project_id": "P-100",
        "task_code": "WBS.1",
        "name": "Design",
        "parent_task_id": None,
        "planned_hours": 40,
        "budget_cost_minor": 400000,
        "currency": "USD",
        "status": "planned",
    }
    req = WBSTaskRequest.model_validate(valid_task)
    assert req.task_code == "WBS.1"

    # Negative hours rejected
    with pytest.raises(ValidationError):
        WBSTaskRequest.model_validate({**valid_task, "planned_hours": -5})

    # Milestone non-positive amount rejected
    with pytest.raises(ValidationError):
        MilestoneRequest.model_validate(
            {
                "milestone_id": "MS-01",
                "project_id": "P-100",
                "contract_line_id": "CL-01",
                "title": "Kickoff",
                "milestone_amount_minor": 0,
                "currency": "USD",
                "due_date": "2026-11-01",
            }
        )


def test_sqlite_project_billing_repository_lifecycle():
    """Verify persistence of tasks, rate cards, milestones, billing, and time logs."""
    conn = sqlite3.connect(":memory:")
    repo = SqliteProjectBillingRepository(conn)

    # 1. Save WBS Tasks
    task1 = ProjectWBSTask(
        workspace_id="ws_main",
        task_id="TASK-WBS-1",
        project_id="PROJ-001",
        task_code="1.0",
        name="Discovery & Planning",
        parent_task_id=None,
        planned_hours=50,
        budget_cost_minor=500_000,
        currency="USD",
        status="completed",
    )
    repo.save_task(task1)

    tasks = repo.list_tasks("ws_main", "PROJ-001")
    assert len(tasks) == 1
    assert tasks[0].name == "Discovery & Planning"
    assert tasks[0].planned_hours == 50

    # 2. Save Rate Card
    rate_card = ResourceRateCard(
        workspace_id="ws_main",
        rate_card_id="RC-DEV",
        project_id="PROJ-001",
        resource_role="Senior Architect",
        hourly_cost_rate_minor=100_00,  # 100.00 USD/hr cost
        hourly_bill_rate_minor=200_00,  # 200.00 USD/hr bill
        currency="USD",
    )
    repo.save_rate_card(rate_card)

    retrieved_card = repo.get_rate_card("ws_main", "PROJ-001", "Senior Architect")
    assert retrieved_card is not None
    assert retrieved_card.hourly_bill_rate_minor == 200_00

    # 3. Log time
    cost, billable = repo.log_time(
        workspace_id="ws_main",
        log_id="LOG-01",
        project_id="PROJ-001",
        task_id="TASK-WBS-1",
        role="Senior Architect",
        hours=10,
        date="2026-10-19",
    )
    assert cost == 1_000_00  # 10 * 100.00 = 1,000.00 USD
    assert billable == 2_000_00  # 10 * 200.00 = 2,000.00 USD

    # 4. Milestone lifecycle and billing
    milestone = ProjectMilestone(
        workspace_id="ws_main",
        milestone_id="MS-DISCOVERY",
        project_id="PROJ-001",
        contract_line_id="CONTRACT-LINE-1",
        title="Discovery Signoff",
        milestone_amount_minor=5_000_00,  # 5,000.00 USD
        currency="USD",
        due_date="2026-10-20",
        status="pending",
    )
    repo.save_milestone(milestone)

    # Verify
    verified_m = verify_milestone_completion(milestone, "lead_consultant", "2026-10-19T10:00:00Z")
    repo.save_milestone(verified_m)

    # Bill
    billed_m, invoice = generate_milestone_invoice(verified_m, "CUST-GLOBAL", "INV-MS-001", "2026-10-19T11:00:00Z")
    repo.save_milestone_invoice(billed_m, invoice)

    retrieved_m = repo.get_milestone("ws_main", "MS-DISCOVERY")
    assert retrieved_m is not None
    assert retrieved_m.status == "billed"

    # 5. Financial posture
    posture = repo.get_financial_posture("ws_main", "PROJ-001", "USD")
    assert posture.budget_cost_minor == 500_000  # 5,000.00 USD
    assert posture.actual_cost_minor == 1_000_00  # 1,000.00 USD
    assert posture.total_billed_minor == 5_000_00  # 5,000.00 USD
    assert posture.unbilled_wip_minor == 0
    # Net profit: 5,000 - 1,000 = 4,000 USD on 5,000 billed = 80.00% = 8000 bps
    assert posture.profit_margin_bps == 8000
