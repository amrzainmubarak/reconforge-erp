"""Explicit factual zero-original controls; no native ownership is inferred."""

from copy import deepcopy
from dataclasses import asdict, replace
from typing import Any

import pytest

from reconforge.domain.customer_partial_return_cost_evidence import (
    OriginalRestitutedCostEvidence,
    restituted_source_money_context,
)
from reconforge.domain.customer_partial_return_rounding import RemainingReturnHistory, prepare_remaining_return
from reconforge.domain.customer_partial_return_rounding_posting import build_remaining_posting_contract
from reconforge.domain.customer_partial_returns import (
    OriginalConsumption,
    PartialReturnHistory,
    RestitutedOriginalConsumption,
    partial_return_balance,
)
from reconforge.domain.finance_posting import FinancePostingError, canonical_json, digest_payload
from reconforge.domain.stock_sales import freeze_fifo
from tests.test_customer_partial_return_design import DESIGN
from tests.test_customer_partial_return_posting import INTENT, roles_for
from tests.test_customer_partial_returns_domain import source_for


def zero_original() -> tuple[Any, dict[str, Any]]:
    case = deepcopy(DESIGN["cases"][0])
    case.update(quantity_precision=1, quantity_scaled=1, gross_minor=100, net_unit_price_minor=1000, collected_minor=0)
    case["consumptions"] = [{"id": "ZERO-CONSUMPTION", "layer_id": "RESTORED-LAYER", "quantity_scaled": 1, "value_minor": 1}]
    original = source_for(case)
    consumed = RestitutedOriginalConsumption(**{**asdict(original.consumptions[0]), "scope": original.scope, "value_minor": 0})
    allocation = {"cost_layer_id": consumed.cost_layer_id, "row_version": 4, "remaining_quantity_scaled": 1,
                  "remaining_value_minor": 0, "quantity_scaled": 1, "value_minor": 0}
    issue = {"schema_version": "stock-sales-issue-v2", "cost_admission_policy": "partial-return-restituted-v1",
             "restitution_cost_snapshot": {"schema_version": "inventory-transfer-cost-v3"}, "entry_id": None,
             "allocations": [allocation], "total_cost_minor": 0, "cogs_account_id": "COGS", "inventory_account_id": "INVENTORY",
             "currency_policy": asdict(original.currency_policy)}
    document = {"id": original.valuation_document_id, "workspace_id": original.scope.workspace_id,
                "organization_id": original.scope.organization_id, "legal_entity_id": original.scope.legal_entity_id,
                "status": "Approved", "total_value_minor": 0, "finance_entry_id": None}
    line = {"id": consumed.valuation_line_id, "item_id": original.scope.item_id, "uom_id": original.scope.uom_id,
            "flow_direction": "Outbound", "quantity_scaled": 1, "quantity_precision": 1, "value_minor": 0}
    fact = {"schema_version": "stock-sales-restituted-cost-v1", "stock_order_id": original.source_order_id, "issue_plan": issue,
            "valuation_document": document, "valuation_lines": [line], "posting_effect": None,
            "consumptions": [{"id": consumed.consumption_id, "valuation_line_id": consumed.valuation_line_id,
                              "cost_layer_id": consumed.cost_layer_id, "quantity_scaled": 1, "value_minor": 0}]}
    evidence = OriginalRestitutedCostEvidence(canonical_json(fact), digest_payload(fact))
    return replace(original, original_cogs=None, consumptions=(consumed,), original_cost_admission=evidence), fact


def test_explicit_zero_original_preserves_real_revenue_and_omits_only_absent_cost_template() -> None:
    source, _ = zero_original()
    before = source.fingerprint
    plan = prepare_remaining_return(RemainingReturnHistory(source), 1)
    result = build_remaining_posting_contract(plan, roles=roles_for(source), intent=INTENT).payload()
    assert (plan.credit_minor, plan.cogs_restored_minor, plan.receivable_released_minor) == (100, 0, 100)
    assert [part["purpose"] for part in result["templates"]] == ["RevenueCredit"]
    assert [(line["account_id"], line["debit_minor"], line["credit_minor"]) for line in result["templates"][0]["lines"]] == [
        ("REVENUE", 100, 0), ("AR", 0, 100)]
    assert source.fingerprint == before and source.fingerprint_payload["original_cogs"] is None
    assert source.fingerprint_payload["contract"] == "customer-partial-return-original-v2"
    with pytest.raises(FinancePostingError):
        partial_return_balance(PartialReturnHistory(source))


@pytest.mark.parametrize("corruption", ["missing", "effect", "total", "quantity", "order", "bool", "foreign_scope"])
def test_coherently_resealed_bad_factual_cost_proof_is_refused(corruption: str) -> None:
    source, fact = zero_original()
    changed = deepcopy(fact)
    if corruption == "missing":
        del changed["posting_effect"]
    elif corruption == "effect":
        changed["posting_effect"] = {"id": "COUNTERFEIT"}
    elif corruption == "total":
        changed["issue_plan"]["total_cost_minor"] = 1
    elif corruption == "quantity":
        changed["consumptions"][0]["quantity_scaled"] = 2
    elif corruption == "order":
        changed["issue_plan"]["allocations"][0]["cost_layer_id"] = "FOREIGN-LAYER"
    elif corruption == "bool":
        changed["consumptions"][0]["value_minor"] = False
    else:
        changed["valuation_document"]["legal_entity_id"] = "FOREIGN-ENTITY"
    with pytest.raises(FinancePostingError):
        evidence = OriginalRestitutedCostEvidence(canonical_json(changed), digest_payload(changed))
        replace(source, original_cost_admission=evidence)


def test_absent_evidence_never_upgrades_old_source_or_original_consumption_constructor() -> None:
    source, _ = zero_original()
    with pytest.raises(FinancePostingError):
        replace(source, original_cost_admission=None)
    with pytest.raises(FinancePostingError):
        OriginalConsumption(**{**asdict(source.consumptions[0]), "scope": source.scope})
    fact = source.original_cost_admission.snapshot()
    fact["issue_plan"]["total_cost_minor"] = 999
    assert source.original_cost_admission.snapshot()["issue_plan"]["total_cost_minor"] == 0


def test_new_monetary_projection_retains_original_unit_price_sensitivity_without_fake_cogs() -> None:
    source, fact = zero_original()
    policy = source.currency_policy
    original = {"cost_admission": fact, "allocated_minor": 0, "cogs": None,
                "consumptions": fact["consumptions"], "revenue": {"snapshot_json": source.original_revenue.snapshot(),
                "currency_code": policy.currency_code, **policy.metadata()},
                "invoice": {"currency_code": policy.currency_code, **policy.metadata(), "subtotal_minor": 100, "tax_minor": 0, "total_minor": 100},
                "stock": {"id": source.source_order_id, "currency_code": policy.currency_code, "total_minor": 100,
                "issue_plan": fact["issue_plan"], "source": {"currency_code": policy.currency_code, "monetary_policy": asdict(policy),
                "unit_price_minor": 1000, "net_unit_price_minor": 1000, "total_minor": 100, "tax_minor": 0}}}
    context = {"source_snapshot": original, "currency_code": policy.currency_code, "currency_precision": policy.precision,
               "amount_minor": 100, "entries": []}
    assert restituted_source_money_context(context)["amount_minor"] == 1000
    changed = deepcopy(context)
    changed["source_snapshot"]["stock"]["issue_plan"]["currency_policy"]["precision"] = 3
    with pytest.raises(FinancePostingError):
        restituted_source_money_context(changed)


@pytest.mark.parametrize("value,quantity,selected,expected", [(0, 1, 1, 0), (1, 3, 1, 0), (1, 3, 2, 1)])
def test_explicit_shared_fifo_option_supports_zero_without_changing_default(value: int, quantity: int, selected: int, expected: int) -> None:
    layer = {"id": "ORIGINAL-LAYER", "row_version": 4, "remaining_quantity_scaled": quantity, "remaining_value_minor": value}
    rows, total = freeze_fifo([layer], selected, allow_zero=True)
    assert total == rows[0]["value_minor"] == expected
    with pytest.raises((FinancePostingError, ValueError)):
        freeze_fifo([layer], selected)


@pytest.mark.parametrize("flag", [0, 1, None, "yes"])
def test_zero_fifo_admission_flag_is_an_explicit_boolean(flag: Any) -> None:
    with pytest.raises(FinancePostingError):
        freeze_fifo([], 1, allow_zero=flag)
