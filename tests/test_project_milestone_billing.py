"""Domain invariant tests for Professional Services Project Billing and Costing."""

from __future__ import annotations

import pytest

from reconforge.domain.project_milestone_billing import (
    ProjectBillingError,
    ProjectMilestone,
    ProjectWBSTask,
    calculate_financial_posture,
    generate_milestone_invoice,
    verify_milestone_completion,
)


def test_wbs_task_validation():
    """Verify task validation and negative constraints."""
    task = ProjectWBSTask(
        workspace_id="ws_main",
        task_id="TASK-01",
        project_id="PROJ-ERP-01",
        task_code="WBS.1.1",
        name="Architecture Design",
        parent_task_id=None,
        planned_hours=80,
        budget_cost_minor=800_000,
        currency="USD",
        status="planned",
    )
    assert task.task_code == "WBS.1.1"

    # Negative hours rejected
    with pytest.raises(ProjectBillingError, match="Planned hours cannot be negative"):
        ProjectWBSTask(
            workspace_id="ws_main",
            task_id="TASK-02",
            project_id="PROJ-ERP-01",
            task_code="WBS.1.2",
            name="Testing",
            parent_task_id=None,
            planned_hours=-10,
            budget_cost_minor=500,
            currency="USD",
        )


def test_milestone_verification_and_billing_lifecycle():
    """Verify maker-checker verification requirement prior to invoice generation."""
    milestone = ProjectMilestone(
        workspace_id="ws_main",
        milestone_id="MS-ALPHA",
        project_id="PROJ-ERP-01",
        contract_line_id="LINE-CONTRACT-101",
        title="Initial Architecture Signoff",
        milestone_amount_minor=5_000_000,  # 50,000.00 USD
        currency="USD",
        due_date="2026-11-15",
        status="pending",
    )

    # Cannot bill pending milestone
    with pytest.raises(ProjectBillingError, match="must be 'verified', got 'pending'"):
        generate_milestone_invoice(milestone, "CUST-ACME", "INV-MS-01", "2026-10-19T10:00:00Z")

    # Verify milestone
    verified = verify_milestone_completion(milestone, "auditor_bob", "2026-10-19T09:30:00Z")
    assert verified.status == "verified"
    assert verified.verified_by == "auditor_bob"

    # Cannot re-verify already verified milestone
    with pytest.raises(ProjectBillingError, match="in status 'verified'"):
        verify_milestone_completion(verified, "auditor_alice", "2026-10-19T09:35:00Z")

    # Generate invoice from verified milestone
    billed, invoice = generate_milestone_invoice(verified, "CUST-ACME", "INV-MS-01", "2026-10-19T10:00:00Z")
    assert billed.status == "billed"
    assert invoice.billed_amount_minor == 5_000_000
    assert invoice.customer_code == "CUST-ACME"
    assert invoice.currency == "USD"
    assert invoice.gl_debit_account == "ACCOUNTS_RECEIVABLE"
    assert invoice.gl_credit_account == "PROJECT_SERVICE_REVENUE"


def test_project_financial_posture_calculation():
    """Verify exact calculation of budget, cost, billed, WIP, and margin basis points."""
    # Scenario 1: Cost 60,000, Billed 100,000 -> Profit 40,000 (40.00% = 4000 bps), Unbilled WIP = 0
    posture1 = calculate_financial_posture(
        project_id="PROJ-01",
        currency="USD",
        budget_cost_minor=50_000_00,
        actual_cost_minor=60_000_00,
        total_billed_minor=100_000_00,
    )
    assert posture1.unbilled_wip_minor == 0
    assert posture1.profit_margin_bps == 4000

    # Scenario 2: Cost 80,000, Billed 50,000 -> Unbilled WIP = 30,000, Negative margin (-6000 bps)
    posture2 = calculate_financial_posture(
        project_id="PROJ-02",
        currency="USD",
        budget_cost_minor=70_000_00,
        actual_cost_minor=80_000_00,
        total_billed_minor=50_000_00,
    )
    assert posture2.unbilled_wip_minor == 30_000_00
    assert posture2.profit_margin_bps == -6000
