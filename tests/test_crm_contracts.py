"""Tests for CRM Opportunity pipeline, tiered quotation approvals, and customer contracts."""

import pytest

from reconforge.domain.crm_contracts import (
    CustomerQuotation,
    Opportunity,
    QuotationLineItem,
    convert_quote_to_contract,
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
