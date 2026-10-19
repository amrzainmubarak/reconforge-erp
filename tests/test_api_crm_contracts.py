"""Level 2 integration tests for CRM Contracts API schemas and SQLite repository."""

import sqlite3

import pytest
from pydantic import ValidationError

from reconforge.api.routes.crm_contracts import (
    ContractConversionPayload,
    ContractTerminationPayload,
    OpportunityPayload,
    QuotationLinePayload,
    QuotationPayload,
    QuoteApprovalPayload,
)
from reconforge.domain.crm_contracts import (
    CustomerQuotation,
    Opportunity,
    QuotationLineItem,
    convert_quote_to_contract,
    terminate_contract,
)
from reconforge.domain.finance_posting import FinancePostingError
from reconforge.infrastructure.sqlite_crm_contracts import (
    SqliteCRMContractsRepository,
)


def test_crm_schema_strictness() -> None:
    valid_opp = {
        "opportunity_id": "OPP-101",
        "organization_id": "ORG-01",
        "customer_id": "CUST-500",
        "title": "Cloud ERP Migration",
        "stage": "qualified",
        "estimated_close_date": "2026-12-31",
        "currency": "USD",
        "projected_amount_minor": 5000000,
        "win_probability_bps": 6000,
    }
    opp = OpportunityPayload.model_validate(valid_opp)
    assert opp.currency == "USD"
    assert opp.win_probability_bps == 6000

    # Reject win probability > 10000
    with pytest.raises(ValidationError):
        OpportunityPayload.model_validate({**valid_opp, "win_probability_bps": 12000})

    # Reject negative amount
    with pytest.raises(ValidationError):
        OpportunityPayload.model_validate({**valid_opp, "projected_amount_minor": -100})

    valid_line = {
        "line_number": 1,
        "item_id": "SKU-ERP-SUB",
        "description": "Annual SaaS Subscription",
        "quantity": 10,
        "unit_price_minor": 100000,
        "discount_bps": 1500,
    }
    line = QuotationLinePayload.model_validate(valid_line)
    assert line.unit_price_minor == 100000

    # Reject discount bps > 10000
    with pytest.raises(ValidationError):
        QuotationLinePayload.model_validate({**valid_line, "discount_bps": 15000})

    valid_quote = {
        "quote_id": "Q-001",
        "opportunity_id": "OPP-101",
        "customer_id": "CUST-500",
        "currency": "USD",
        "valid_until": "2026-12-15",
        "lines": [valid_line],
    }
    quote = QuotationPayload.model_validate(valid_quote)
    assert quote.quote_id == "Q-001"

    # Reject empty lines
    with pytest.raises(ValidationError):
        QuotationPayload.model_validate({**valid_quote, "lines": []})

    valid_conv = {
        "contract_id": "CTR-001",
        "organization_id": "ORG-01",
        "start_date": "2026-11-01",
        "end_date": "2027-10-31",
        "billing_frequency": "annual",
        "as_of_date": "2026-11-01",
    }
    conv = ContractConversionPayload.model_validate(valid_conv)
    assert conv.billing_frequency == "annual"

    valid_term = {
        "termination_date": "2027-04-30",
        "early_termination_fee_minor": 50000,
        "approver_id": "director_bob",
    }
    term = ContractTerminationPayload.model_validate(valid_term)
    assert term.early_termination_fee_minor == 50000

    approval = QuoteApprovalPayload.model_validate({"approver_role": "sales_manager"})
    assert approval.approver_role == "sales_manager"


def test_sqlite_crm_contracts_repository_lifecycle() -> None:
    conn = sqlite3.connect(":memory:")
    repo = SqliteCRMContractsRepository(conn)
    ws_id = "ws_test"

    # 1. Opportunity
    opp = Opportunity(
        opportunity_id="OPP-001",
        workspace_id=ws_id,
        organization_id="ORG-1",
        customer_id="CUST-1",
        title="Warehouse Automation Deal",
        stage="proposal",
        estimated_close_date="2026-12-31",
        currency="SAR",
        projected_amount_minor=1_000_000_00,
        win_probability_bps=7500,
    )
    repo.save_opportunity(opp)

    retrieved_opp = repo.get_opportunity(ws_id, "OPP-001")
    assert retrieved_opp is not None
    assert retrieved_opp.weighted_pipeline_value_minor == 750_000_00

    # 2. Quotation
    lines = (
        QuotationLineItem(1, "LIC-100", "Enterprise License", 1, 800_000_00, discount_bps=1500),  # 15% discount
        QuotationLineItem(2, "SRV-200", "Implementation", 1, 200_000_00, discount_bps=500),      # 5% discount
    )
    quote = CustomerQuotation(
        quote_id="Q-001",
        opportunity_id="OPP-001",
        workspace_id=ws_id,
        customer_id="CUST-1",
        currency="SAR",
        valid_until="2026-12-15",
        submitter_user_id="sales_alice",
        status="draft",
        lines=lines,
    )
    repo.save_quotation(quote)

    retrieved_quote = repo.get_quotation(ws_id, "Q-001")
    assert retrieved_quote is not None
    assert len(retrieved_quote.lines) == 2
    assert retrieved_quote.total_gross_minor == 1_000_000_00
    # 800k * 15% = 120k; 200k * 5% = 10k -> total discount 130k
    assert retrieved_quote.total_discount_minor == 130_000_00
    assert retrieved_quote.total_net_minor == 870_000_00
    assert retrieved_quote.effective_discount_bps == 1300

    # SoD: Submitter cannot approve
    with pytest.raises(FinancePostingError) as exc_info:
        retrieved_quote.approve(approver_user_id="sales_alice", approver_role="sales_manager")
    assert "crm_sod_violation" in str(exc_info.value.code)

    # 13% discount requires at least sales_manager (threshold 1000 bps)
    with pytest.raises(FinancePostingError) as exc_info:
        retrieved_quote.approve(approver_user_id="rep_charlie", approver_role="sales_rep")
    assert "crm_authorization_insufficient" in str(exc_info.value.code)

    # Sales manager approves
    approved_quote = retrieved_quote.approve(approver_user_id="manager_bob", approver_role="sales_manager")
    assert approved_quote.status == "approved"
    assert approved_quote.approved_by_user_id == "manager_bob"
    repo.save_quotation(approved_quote)

    # 3. Convert to Contract
    contract = convert_quote_to_contract(
        quote=approved_quote,
        contract_id="CTR-001",
        organization_id="ORG-1",
        start_date="2026-11-01",
        end_date="2027-10-31",
        billing_frequency="annual",
        as_of_date="2026-11-01",
    )
    assert contract.status == "active"
    assert contract.total_contract_value_minor == 870_000_00
    repo.save_contract(contract)

    retrieved_ctr = repo.get_contract(ws_id, "CTR-001")
    assert retrieved_ctr is not None
    assert retrieved_ctr.status == "active"
    assert retrieved_ctr.billing_frequency == "annual"

    # 4. Terminate Contract (Maker-Checker enforced)
    with pytest.raises(FinancePostingError) as exc_info:
        terminate_contract(
            contract=retrieved_ctr,
            termination_date="2027-03-31",
            early_termination_fee_minor=50_000_00,
            actor_id="director_dan",
            approver_id="director_dan",
        )
    assert "crm_sod_violation" in str(exc_info.value.code)

    terminated, fee = terminate_contract(
        contract=retrieved_ctr,
        termination_date="2027-03-31",
        early_termination_fee_minor=50_000_00,
        actor_id="manager_bob",
        approver_id="director_dan",
    )
    assert terminated.status == "terminated"
    assert fee == 50_000_00
    repo.save_contract(terminated)

    final_ctr = repo.get_contract(ws_id, "CTR-001")
    assert final_ctr is not None
    assert final_ctr.status == "terminated"
    assert final_ctr.end_date == "2027-03-31"
