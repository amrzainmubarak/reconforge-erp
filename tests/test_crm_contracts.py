"""Tests for CRM Opportunity pipeline, tiered quotation approvals, and customer contracts."""

import pytest

from reconforge.domain.crm_contracts import (
    CustomerContract,
    CustomerQuotation,
    Opportunity,
    QuotationLineItem,
    Subscription,
    SubscriptionPlan,
    calculate_day_proration,
    calculate_plan_change_proration,
    cancel_subscription_with_refund,
    convert_quote_to_contract,
    renew_contract,
    resume_contract,
    suspend_contract,
    terminate_contract,
)
from reconforge.domain.finance_posting import FinancePostingError


def test_opportunity_weighted_pipeline() -> None:
    opp = Opportunity(
        opportunity_id="OPP-001",
        workspace_id="ws_01",
        organization_id="org_01",
        customer_id="cust_100",
        title="Enterprise ERP Expansion",
        stage="proposal",
        estimated_close_date="2026-12-31",
        currency="SAR",
        projected_amount_minor=1_000_000_00,  # 1,000,000.00 SAR
        win_probability_bps=6_000,  # 60%
    )
    # Weighted value should be 600,000.00 SAR
    assert opp.weighted_pipeline_value_minor == 600_000_00


def test_quote_discount_calculation() -> None:
    lines = (
        QuotationLineItem(
            line_number=1,
            item_id="SRV-IMP",
            description="ERP Implementation Service",
            quantity=100,
            unit_price_minor=1_000_00,  # 1,000.00 each -> Gross 100,000.00
            discount_bps=1_500,  # 15.00% discount -> Discount 15,000.00, Net 85,000.00
        ),
        QuotationLineItem(
            line_number=2,
            item_id="LIC-USR",
            description="Enterprise User License",
            quantity=50,
            unit_price_minor=200_00,  # 200.00 each -> Gross 10,000.00
            discount_bps=500,  # 5.00% discount -> Discount 500.00, Net 9,500.00
        ),
    )

    quote = CustomerQuotation(
        quote_id="QT-2026-001",
        opportunity_id="OPP-001",
        workspace_id="ws_01",
        customer_id="cust_100",
        currency="SAR",
        valid_until="2026-11-30",
        submitter_user_id="sales_rep_amr",
        status="submitted",
        lines=lines,
    )

    # Gross: 100,000 + 10,000 = 110,000.00
    assert quote.total_gross_minor == 110_000_00
    # Discount: 15,000 + 500 = 15,500.00
    assert quote.total_discount_minor == 15_500_00
    # Net: 85,000 + 9,500 = 94,500.00
    assert quote.total_net_minor == 94_500_00

    # Effective discount: 15,500 / 110,000 = 14.0909% -> 1409 bps
    assert quote.effective_discount_bps == 1409


def test_quote_approval_maker_checker_and_role_thresholds() -> None:
    lines = (
        QuotationLineItem(
            line_number=1,
            item_id="LIC-ENT",
            description="ERP Subscription",
            quantity=10,
            unit_price_minor=10_000_00,
            discount_bps=2_500,  # 25% discount! Requires commercial director / CFO
        ),
    )

    quote = CustomerQuotation(
        quote_id="QT-HIGH-DISCOUNT",
        opportunity_id="OPP-002",
        workspace_id="ws_01",
        customer_id="cust_200",
        currency="SAR",
        valid_until="2026-11-30",
        submitter_user_id="sales_rep_1",
        status="submitted",
        lines=lines,
    )

    # 1. Submitter cannot approve their own quote (SoD)
    with pytest.raises(FinancePostingError, match="Submitter cannot approve"):
        quote.approve("sales_rep_1", "commercial_director")

    # 2. Sales manager cannot approve > 20% discount
    with pytest.raises(FinancePostingError, match="require Commercial Director or CFO"):
        quote.approve("manager_bob", "sales_manager")

    # 3. Commercial director successfully approves
    approved = quote.approve("director_sarah", "commercial_director")
    assert approved.status == "approved"
    assert approved.approved_by_user_id == "director_sarah"


def test_quote_to_contract_conversion() -> None:
    lines = (
        QuotationLineItem(
            line_number=1,
            item_id="PRD-01",
            description="Cloud Hosting",
            quantity=12,
            unit_price_minor=5_000_00,
            discount_bps=1_000,  # 10% discount -> 500.00 off per month -> Net 4,500 * 12 = 54,000.00
        ),
    )

    quote = CustomerQuotation(
        quote_id="QT-HOSTING",
        opportunity_id="OPP-003",
        workspace_id="ws_01",
        customer_id="cust_300",
        currency="SAR",
        valid_until="2026-11-30",
        submitter_user_id="rep_1",
        status="draft",
        lines=lines,
    )

    # Cannot convert unapproved quote
    with pytest.raises(FinancePostingError, match="Only approved quotations"):
        convert_quote_to_contract(
            quote, "CTR-001", "org_01", "2026-12-01", "2027-11-30", "monthly", "2026-11-15"
        )

    # Approve quote
    approved = quote.approve("manager_2", "sales_manager")

    # Cannot convert if as_of_date is expired
    with pytest.raises(FinancePostingError, match="Quotation expired"):
        convert_quote_to_contract(
            approved, "CTR-001", "org_01", "2026-12-01", "2027-11-30", "monthly", "2026-12-01"  # Valid until was Nov 30!
        )

    # Successfully convert within validity
    contract = convert_quote_to_contract(
        approved, "CTR-001", "org_01", "2026-12-01", "2027-11-30", "monthly", "2026-11-20"
    )

    assert contract.contract_id == "CTR-001"
    assert contract.total_contract_value_minor == 54_000_00
    assert contract.status == "active"
    assert contract.billing_frequency == "monthly"


def test_contract_lifecycle_suspend_resume_terminate() -> None:
    contract = CustomerContract(
        contract_id="CTR-2026-X",
        quote_id="QT-001",
        workspace_id="ws_01",
        organization_id="org_01",
        customer_id="cust_100",
        currency="SAR",
        start_date="2026-01-01",
        end_date="2026-12-31",
        billing_frequency="annual",
        total_contract_value_minor=120_000_00,
        status="active",
    )

    # 1. Suspend active contract
    suspended = suspend_contract(contract, reason="Late payment audit", actor_id="collector_1")
    assert suspended.status == "suspended"

    # Cannot suspend already suspended contract
    with pytest.raises(FinancePostingError, match="Cannot suspend contract in status 'suspended'"):
        suspend_contract(suspended, reason="Again", actor_id="collector_1")

    # 2. Resume suspended contract
    resumed = resume_contract(suspended, actor_id="manager_1")
    assert resumed.status == "active"

    # Cannot resume active contract
    with pytest.raises(FinancePostingError, match="Cannot resume contract in status 'active'"):
        resume_contract(resumed, actor_id="manager_1")

    # 3. Terminate contract with SoD violation (actor == approver)
    with pytest.raises(FinancePostingError, match="Contract termination requires independent maker-checker"):
        terminate_contract(
            resumed,
            termination_date="2026-06-30",
            early_termination_fee_minor=10_000_00,
            actor_id="admin_1",
            approver_id="admin_1",
        )

    # 4. Terminate contract with date out of bounds
    with pytest.raises(FinancePostingError, match="Termination date"):
        terminate_contract(
            resumed,
            termination_date="2027-01-15",
            early_termination_fee_minor=10_000_00,
            actor_id="rep_1",
            approver_id="cfo_1",
        )

    # 5. Valid termination
    terminated, fee = terminate_contract(
        resumed,
        termination_date="2026-06-30",
        early_termination_fee_minor=10_000_00,
        actor_id="rep_1",
        approver_id="cfo_1",
    )
    assert terminated.status == "terminated"
    assert terminated.end_date == "2026-06-30"
    assert fee == 10_000_00


def test_contract_renewal() -> None:
    contract = CustomerContract(
        contract_id="CTR-RENEW-01",
        quote_id="QT-002",
        workspace_id="ws_01",
        organization_id="org_01",
        customer_id="cust_200",
        currency="SAR",
        start_date="2026-01-01",
        end_date="2026-12-31",
        billing_frequency="annual",
        total_contract_value_minor=100_000_00,
        status="active",
    )

    # 1. Cannot renew if new end date is not strictly after current end date
    with pytest.raises(FinancePostingError, match="New end date"):
        renew_contract(contract, new_end_date="2026-12-31", price_adjustment_bps=500, approver_id="mgr_1")

    # 2. Renew with 5% (500 bps) increase -> 100,000 + 5,000 = 105,000 SAR
    renewed_up = renew_contract(
        contract,
        new_end_date="2027-12-31",
        price_adjustment_bps=500,
        approver_id="director_1",
    )
    assert renewed_up.status == "active"
    assert renewed_up.start_date == "2026-12-31"
    assert renewed_up.end_date == "2027-12-31"
    assert renewed_up.total_contract_value_minor == 105_000_00

    # 3. Renew with -10% (-1000 bps) loyalty discount -> 90,000 SAR
    renewed_down = renew_contract(
        contract,
        new_end_date="2027-12-31",
        price_adjustment_bps=-1_000,
        approver_id="cfo_1",
    )
    assert renewed_down.total_contract_value_minor == 90_000_00

    # 4. Cannot renew a terminated contract
    term_contract, _ = terminate_contract(
        contract,
        termination_date="2026-06-30",
        early_termination_fee_minor=0,
        actor_id="rep_1",
        approver_id="mgr_1",
    )
    with pytest.raises(FinancePostingError, match="Cannot renew a terminated contract"):
        renew_contract(term_contract, new_end_date="2027-12-31", price_adjustment_bps=0, approver_id="cfo_1")


def test_subscription_proration_day_calculations() -> None:
    # 30-day month, 1,000.00 SAR (100,000 minor)
    # 15 days active -> exactly 50,000 minor
    assert calculate_day_proration(100_000, total_period_days=30, active_days=15) == 50_000

    # 0 days active -> 0
    assert calculate_day_proration(100_000, total_period_days=30, active_days=0) == 0

    # 30 days active -> 100,000
    assert calculate_day_proration(100_000, total_period_days=30, active_days=30) == 100_000

    # Half-up rounding test: 100_000 over 30 days = 3333.333... per day
    # For 10 days: 100_000 * 10 / 30 = 33_333.333 -> rounds to 33_333
    assert calculate_day_proration(100_000, total_period_days=30, active_days=10) == 33_333
    # For 1 day: (100_000 * 1 + 15) // 30 = 100_015 // 30 = 3_333
    assert calculate_day_proration(100_000, total_period_days=30, active_days=1) == 3_333

    # Bounds errors
    with pytest.raises(FinancePostingError, match="total_period_days must be positive"):
        calculate_day_proration(100_000, total_period_days=0, active_days=0)
    with pytest.raises(FinancePostingError, match="active_days"):
        calculate_day_proration(100_000, total_period_days=30, active_days=35)


def test_subscription_plan_change_and_cancellation_refund() -> None:
    silver_plan = SubscriptionPlan(
        plan_id="PLAN-SILVER",
        name="Silver SaaS Tier",
        currency="SAR",
        billing_interval="monthly",
        unit_price_minor=300_00,  # 300.00 SAR per month
    )
    gold_plan = SubscriptionPlan(
        plan_id="PLAN-GOLD",
        name="Gold Enterprise SaaS Tier",
        currency="SAR",
        billing_interval="monthly",
        unit_price_minor=600_00,  # 600.00 SAR per month
    )

    # June has 30 days: 2026-06-01 to 2026-06-30
    # Customer upgrades on June 16 (midpoint): 15 days on Silver, 15 days on Gold
    proration = calculate_plan_change_proration(
        old_plan=silver_plan,
        new_plan=gold_plan,
        period_start="2026-06-01",
        period_end="2026-06-30",
        change_date="2026-06-16",
    )
    assert proration["total_period_days"] == 30
    assert proration["remaining_days"] == 15
    assert proration["unearned_credit_minor"] == 150_00  # 300 * 15 / 30 = 150.00 SAR credit
    assert proration["new_charge_minor"] == 300_00       # 600 * 15 / 30 = 300.00 SAR charge
    assert proration["net_payable_minor"] == 150_00      # 300 - 150 = 150.00 SAR net payable

    # Active subscription cancellation with unearned refund
    subscription = Subscription(
        subscription_id="SUB-001",
        customer_id="cust_100",
        contract_id="CTR-001",
        plan_id="PLAN-GOLD",
        currency="SAR",
        status="active",
        current_period_start="2026-06-01",
        current_period_end="2026-06-30",
        auto_renew=True,
    )

    cancelled_sub, refund = cancel_subscription_with_refund(
        subscription=subscription,
        plan=gold_plan,
        cancellation_date="2026-06-21",  # 10 days remaining: June 21 through June 30 inclusive
    )
    assert cancelled_sub.status == "cancelled"
    assert cancelled_sub.auto_renew is False
    # 600.00 * 10 / 30 = 200.00 SAR refund
    assert refund == 200_00


def test_quote_approval_sod_whitespace_padding_blocked() -> None:
    """Verify that leading or trailing whitespace cannot bypass maker-checker SoD in quotation approval."""
    lines = (
        QuotationLineItem(
            line_number=1,
            item_id="SRV-01",
            description="Consulting",
            quantity=10,
            unit_price_minor=10_000,
            discount_bps=500,  # 5% discount
        ),
    )
    quote = CustomerQuotation(
        quote_id="QT-SOD-WS-001",
        opportunity_id="OPP-001",
        workspace_id="ws_01",
        customer_id="cust_1",
        currency="SAR",
        valid_until="2026-12-31",
        submitter_user_id="sales_rep_amr",
        status="submitted",
        lines=lines,
    )
    # Padded with spaces -> trimmed by text(), matches submitter -> SoD violation
    with pytest.raises(FinancePostingError, match="Submitter cannot approve their own quotation"):
        quote.approve(approver_user_id="  sales_rep_amr  ", approver_role="sales_rep")

    with pytest.raises(FinancePostingError, match="Submitter cannot approve their own quotation"):
        quote.approve(approver_user_id="sales_rep_amr ", approver_role="sales_rep")

    # Non-printable control characters are rejected directly by text() sanitization
    with pytest.raises(FinancePostingError, match="must be nonempty printable text"):
        quote.approve(approver_user_id="\tsales_rep_amr\n", approver_role="sales_rep")


def test_customer_quotation_dataclass_whitespace_normalization() -> None:
    """Verify that CustomerQuotation normalizes string attributes via object.__setattr__ in __post_init__."""
    lines = (
        QuotationLineItem(
            line_number=1,
            item_id="  SRV-01  ",
            description="  Consulting  ",
            quantity=10,
            unit_price_minor=10_000,
            discount_bps=500,
        ),
    )
    quote = CustomerQuotation(
        quote_id="  QT-NORM-001  ",
        opportunity_id="  OPP-001  ",
        workspace_id="  ws_01  ",
        customer_id="  cust_1  ",
        currency="SAR",
        valid_until="2026-12-31",
        submitter_user_id="  sales_rep_amr  ",
        status="submitted",
        lines=lines,
    )
    assert quote.quote_id == "QT-NORM-001"
    assert quote.opportunity_id == "OPP-001"
    assert quote.workspace_id == "ws_01"
    assert quote.customer_id == "cust_1"
    assert quote.submitter_user_id == "sales_rep_amr"


def test_asymmetric_whitespace_quotation_self_approval_blocked() -> None:
    """Verify that asymmetric whitespace cannot bypass SoD in CustomerQuotation.approve."""
    lines = (
        QuotationLineItem(
            line_number=1,
            item_id="SRV-01",
            description="Consulting",
            quantity=10,
            unit_price_minor=10_000,
            discount_bps=500,
        ),
    )
    quote = CustomerQuotation(
        quote_id="QT-ASYMM-001",
        opportunity_id="OPP-001",
        workspace_id="ws_01",
        customer_id="cust_1",
        currency="SAR",
        valid_until="2026-12-31",
        submitter_user_id="sales_rep_amr",
        status="submitted",
        lines=lines,
    )
    with pytest.raises(FinancePostingError, match="Submitter cannot approve their own quotation"):
        quote.approve(approver_user_id="sales_rep_amr", approver_role="sales_rep")

    with pytest.raises(FinancePostingError, match="Submitter cannot approve their own quotation"):
        quote.approve(approver_user_id="  sales_rep_amr  ", approver_role="sales_rep")


def test_zero_width_formatting_characters_rejected_in_crm() -> None:
    """Verify that zero-width formatting characters (category 'Cf') are rejected in quotation operations."""
    lines = (
        QuotationLineItem(
            line_number=1,
            item_id="SRV-01",
            description="Consulting",
            quantity=10,
            unit_price_minor=10_000,
            discount_bps=500,
        ),
    )
    quote = CustomerQuotation(
        quote_id="QT-ZW-001",
        opportunity_id="OPP-001",
        workspace_id="ws_01",
        customer_id="cust_1",
        currency="SAR",
        valid_until="2026-12-31",
        submitter_user_id="sales_rep_amr",
        status="submitted",
        lines=lines,
    )
    zero_width_chars = ["\u200b", "\u200c", "\u200d", "\u2060", "\ufeff"]
    for zw in zero_width_chars:
        with pytest.raises(FinancePostingError, match="contains invalid formatting characters"):
            quote.approve(approver_user_id=f"{zw}sales_rep_amr", approver_role="sales_rep")

        with pytest.raises(FinancePostingError, match="contains invalid formatting characters"):
            quote.approve(approver_user_id=f"sales_rep_amr{zw}", approver_role="sales_rep")

        with pytest.raises(FinancePostingError, match="contains invalid formatting characters"):
            CustomerQuotation(
                quote_id=f"QT-{zw}001",
                opportunity_id="OPP-001",
                workspace_id="ws_01",
                customer_id="cust_1",
                currency="SAR",
                valid_until="2026-12-31",
                submitter_user_id="sales_rep_amr",
                status="submitted",
                lines=lines,
            )
