"""Adversarial transport contracts, not native tax/FX posting acceptance."""

from copy import deepcopy
from typing import Any

import pytest

from reconforge.api.monetary_partial_return_contract import (
    MONETARY_FIELDS,
    project_monetary_partial_balance,
    project_monetary_partial_plan,
    project_monetary_partial_response,
)
from reconforge.api.monetary_public_contract import MonetaryResponseError
from reconforge.api.monetary_stock_contract import project_monetary_stock, project_monetary_stock_response
from reconforge.domain.operational_fx_tax import TaxComponent

SCOPE = {"workspace_id": "work", "organization_id": "organization", "legal_entity_id": "entity"}
RATE = {"rate": "1.25", "source": "Synthetic spot observation", "effective_at": "2026-10-15T12:00:00Z"}


def captured_policy(currency: str) -> dict[str, Any]:
    return {"currency_code": currency, "currency_precision": 2, "currency_rounding_policy": "ROUND_HALF_UP",
            "currency_registry_version": "synthetic-v1", "currency_registry_digest": "a" * 64}


def monetary_balance() -> dict[str, Any]:
    return {"schema_version": "stock-monetary-balance-v1", "history_version": 0, "history_fingerprint": "b" * 64,
        "transaction_original_gross_minor": "1200", "functional_original_gross_minor": "1500", "transaction_collected_minor": "0",
        "transaction_credited_minor": "0", "transaction_outstanding_minor": "1200", "functional_outstanding_minor": "1500",
        "transaction_refund_entitlement_minor": "0", "functional_refund_entitlement_minor": "0", "transaction_refunded_minor": "0",
        "functional_refund_released_minor": "0", "transaction_refund_due_minor": "0", "functional_refund_due_minor": "0",
        "active_plan_id": None, "active_revaluation_plan_id": None}


def stock_fixture(stage: int = 9) -> dict[str, Any]:
    steps = [("create", "Draft", "maker"), ("submit", "Submitted", "maker"), ("approve", "Approved", "checker"),
        ("reserve", "Reserved", "maker"), ("prepare-issue", "IssuePrepared", "maker"), ("review-issue", "IssueReviewed", "checker"),
        ("deliver", "Delivered", "poster"), ("prepare-invoice", "InvoicePrepared", "maker"),
        ("review-invoice", "InvoiceReviewed", "checker"), ("invoice", "Invoiced", "poster")]
    issued, delivered, invoicing, recognized = stage >= 4, stage >= 6, stage >= 7, stage >= 9
    row: dict[str, Any] = {**SCOPE, "schema_version": "stock-sales-monetary-v2", "id": "monetary-stock", "number": "SYNTHETIC-SALE",
        "status": steps[stage][1], "row_version": stage + 1, "source_digest": "c" * 64, "customer_code": "CUSTOMER", "customer_reference": "REFERENCE",
        "item_code": "ITEM", "warehouse_code": "WAREHOUSE", "location_code": "LOCATION", "quantity": "10", "quantity_scaled": "10", "quantity_precision": 0,
        "unit_price_minor": "100", "discount_basis_points": 0, "net_unit_price_minor": "100", "transaction_net_minor": "1000", "description": "Synthetic merchandise",
        "order_date": "2026-10-15", "transaction_policy": captured_policy("EUR"), "functional_policy": captured_policy("USD"), "created_by": "maker",
        "approved_by": "checker" if stage >= 2 else None, "issue_preparer_id": "maker" if issued else None,
        "issue_reviewer_id": "checker" if stage >= 5 else None, "issue_digest": "d" * 64 if issued else None, "functional_cogs_minor": "400" if issued else None,
        "cogs_entry_id": "cost-entry" if issued else None, "cogs_effect_id": "cost-effect" if delivered else None,
        "movement_id": "delivery" if delivered else None, "valuation_id": "valuation" if delivered else None, "cost_admission_policy": None,
        "monetary_origin": None, "balance": monetary_balance() if recognized else None, "collection": None,
        "events": [{"version": i + 1, "actor_id": actor, "operation": operation, "reason": "Synthetic action", "status": status, "audit_event_id": "audit-" + str(i)}
                   for i, (operation, status, actor) in enumerate(steps[:stage + 1])]}
    if invoicing:
        tax = TaxComponent("SYNTHETIC-TAX", "ZZ", "Synthetic merchandise", "2026-01-01", "2026-12-31", "0.2", "TAX", "Synthetic declared rule", "1")
        row["monetary_origin"] = {"schema_version": "stock-monetary-origin-v1", "id": "origin", "fx_source_id": "fx-source", "recognition_plan_id": "recognition",
            "invoice_id": "invoice", "source_digest": "e" * 64, "country_code": "ZZ", "transaction_class": "Synthetic merchandise", "original_rate": RATE.copy(),
            "transaction_net_minor": "1000", "transaction_tax_minor": "200", "transaction_gross_minor": "1200", "functional_net_minor": "1250",
            "functional_tax_minor": "250", "functional_gross_minor": "1500", "tax_components": [{**tax.payload(day="2026-10-15", country="ZZ", transaction_class="Synthetic merchandise"),
                "transaction_tax_minor": "200", "functional_tax_minor": "250"}], "receivable_account_code": "AR", "revenue_account_code": "REVENUE", "cash_account_code": "CASH",
            "refund_liability_account_code": "REFUND", "gain_account_code": "GAIN", "loss_account_code": "LOSS", "journal_code": "GENERAL", "period_id": "PERIOD",
            "invoice_number": "SYNTHETIC-INVOICE", "invoice_date": "2026-10-15", "due_date": "2026-11-15", "preparer_actor_id": "maker",
            "reviewer_actor_id": "checker" if stage >= 8 else None, "posted_actor_id": "poster" if recognized else None,
            "entry_id": "revenue-entry", "posting_effect_id": "revenue-effect" if recognized else None}
    return row


def partial_fixture(operation: str = "Return", phase: int = 2, *, zero: bool = False) -> dict[str, Any]:
    prefixes = {"Return": "CR3", "Refund": "CRF3", "ReverseReturn": "CR3R", "ReverseRefund": "CRF3R"}
    is_return = operation in {"Return", "ReverseReturn"}
    money = dict.fromkeys(MONETARY_FIELDS, "0")
    if is_return:
        money.update(transaction_net_minor="500", transaction_tax_minor="100", transaction_credit_minor="600",
            transaction_receivable_released_minor="400", transaction_refund_delta_minor="200")
        if not zero:
            money.update(functional_net_minor="625", functional_tax_minor="125", functional_credit_minor="750", functional_cost_minor="200",
                functional_receivable_released_minor="500", functional_refund_delta_minor="250", functional_turnover_minor="950")
        purposes = [] if zero else ["MerchandiseCredit", "CostRestoration"]
    else:
        money["transaction_refund_minor"] = "200"
        if not zero:
            money.update(functional_refund_released_minor="250", functional_cash_minor="240", functional_fx_loss_minor="0", functional_fx_gain_minor="10", functional_turnover_minor="250")
        purposes = [] if zero else ["Refund"]
    if operation.startswith("Reverse"):
        purposes = ["Reverse" + name for name in purposes]
    return {**SCOPE, "schema_version": "customer-partial-return-monetary-v3", "id": prefixes[operation] + "-" + "1" * 32,
        "source_id": "origin", "source_order_id": "monetary-stock", "invoice_id": "invoice", "operation": operation,
        "status": ("Prepared", "Reviewed", "Posted", "Cancelled")[phase], "phase": phase, "quantity_scaled": "5" if is_return else "0", "quantity_precision": 0,
        "period_id": "PERIOD", "posting_date": "2026-10-15", "reason": "Synthetic retained intent", "source_fingerprint": "a" * 64,
        "history_fingerprint": "b" * 64, "expected_history_version": 0, "plan_digest": "c" * 64, "allocation_policy": "remaining-dual-currency-v1",
        "transaction_policy": captured_policy("EUR"), "functional_policy": captured_policy("USD"), "monetary": money,
        "entries": [{"purpose": name, "entry_id": "entry-" + str(i), "posting_effect_id": "effect-" + str(i) if phase == 2 else None, "validation_digest": "d" * 64}
                    for i, name in enumerate(purposes)], "movement_id": "receipt" if phase == 2 and is_return else None,
        "original_id": None if operation == "Return" else ("CRF3-" if operation == "ReverseRefund" else "CR3-") + "2" * 32,
        "preparer_actor_id": "maker", "reviewer_actor_id": "checker" if phase != 0 else None,
        "posted_actor_id": "poster" if phase == 2 else None, "cancelled_actor_id": "canceller" if phase == 3 else None}


@pytest.mark.parametrize("stage", range(10))
def test_stock_transport_keeps_distinct_currencies_and_exact_lifecycle(stage: int) -> None:
    raw = stock_fixture(stage)
    before = deepcopy(raw)
    result = project_monetary_stock(raw, SCOPE)
    assert result == raw == before
    assert "total_minor" not in result and "cogs_minor" not in result
    assert result["transaction_policy"]["currency_code"] == "EUR" and result["functional_policy"]["currency_code"] == "USD"


@pytest.mark.parametrize("value", [1000, 1.0, True, None, "01", "+1", "1.0", "1e3", "-1", "9000000000000000001"])
def test_new_money_transport_never_coerces_or_rounds(value: Any) -> None:
    with pytest.raises(MonetaryResponseError):
        project_monetary_stock({**stock_fixture(0), "transaction_net_minor": value}, SCOPE)


def test_large_minor_units_remain_exact_canonical_strings() -> None:
    raw = stock_fixture(0)
    raw.update(quantity="1", quantity_scaled="1", transaction_net_minor="9007199254740993", unit_price_minor="9007199254740993", net_unit_price_minor="9007199254740993")
    assert project_monetary_stock(raw, SCOPE)["transaction_net_minor"] == "9007199254740993"


@pytest.mark.parametrize("mutation", ["private", "scope", "gross", "tax", "rate-missing", "rate-date", "origin-owner", "reviewer", "effect", "zero-cost"])
def test_stock_source_and_governance_projection_refuse_coherent_looking_wrong_fields(mutation: str) -> None:
    raw = stock_fixture()
    origin = raw["monetary_origin"]
    if mutation == "private":
        origin["source_snapshot"] = {"private": "body"}
    elif mutation == "scope":
        raw["legal_entity_id"] = "other"
    elif mutation == "gross":
        origin["transaction_gross_minor"] = "1201"
    elif mutation == "tax":
        origin["tax_components"][0]["transaction_tax_minor"] = "199"
    elif mutation == "rate-missing":
        origin["original_rate"] = None
    elif mutation == "rate-date":
        origin["original_rate"]["effective_at"] = "2026-10-14T12:00:00Z"
    elif mutation == "origin-owner":
        origin["preparer_actor_id"] = "other"
    elif mutation == "reviewer":
        raw["issue_reviewer_id"] = "maker"
    elif mutation == "effect":
        origin["posting_effect_id"] = None
    else:
        raw.update(functional_cogs_minor="0", cogs_entry_id=None, cogs_effect_id=None)
    with pytest.raises(MonetaryResponseError):
        project_monetary_stock(raw, SCOPE)


def test_zero_stock_cost_requires_the_retained_native_admission_marker() -> None:
    raw = stock_fixture()
    raw.update(functional_cogs_minor="0", cogs_entry_id=None, cogs_effect_id=None, cost_admission_policy="partial-return-restituted-v1")
    assert project_monetary_stock(raw, SCOPE)["cogs_effect_id"] is None


@pytest.mark.parametrize("operation", ["Return", "Refund", "ReverseReturn", "ReverseRefund"])
@pytest.mark.parametrize("phase", range(4))
@pytest.mark.parametrize("zero", [False, True])
def test_v3_closed_zero_and_real_legs_preserve_governed_phases(operation: str, phase: int, zero: bool) -> None:
    raw = partial_fixture(operation, phase, zero=zero)
    before = deepcopy(raw)
    assert project_monetary_partial_plan(raw, SCOPE) == before == raw
    assert len(raw["entries"]) == (0 if zero else 2 if "Return" in operation else 1)


@pytest.mark.parametrize("mutation", ["policy", "legacy", "scope", "float", "bool", "credit", "alignment", "turnover", "purpose", "poster", "movement", "unknown"])
def test_v3_transport_refuses_malformed_amounts_private_data_and_governance(mutation: str) -> None:
    raw = partial_fixture()
    if mutation == "policy":
        raw["allocation_policy"] = "caller-rule"
    elif mutation == "legacy":
        raw["schema_version"] = "customer-partial-return-v2"
    elif mutation == "scope":
        raw["workspace_id"] = "other"
    elif mutation in {"float", "bool"}:
        raw["monetary"]["transaction_credit_minor"] = 600.0 if mutation == "float" else True
    elif mutation == "credit":
        raw["monetary"]["transaction_credit_minor"] = "601"
    elif mutation == "alignment":
        raw["monetary"].update(functional_alignment_gain_minor="1", functional_alignment_loss_minor="1")
    elif mutation == "turnover":
        raw["monetary"]["functional_turnover_minor"] = "951"
    elif mutation == "purpose":
        raw["entries"].reverse()
    elif mutation == "poster":
        raw["posted_actor_id"] = "checker"
    elif mutation == "movement":
        raw["movement_id"] = None
    else:
        raw["source_snapshot"] = {"private": "body"}
    with pytest.raises(MonetaryResponseError):
        project_monetary_partial_plan(raw, SCOPE)


def test_zero_journals_cannot_be_fabricated_for_positive_quantity_or_foreign_cash() -> None:
    for operation in ("Return", "Refund"):
        raw = partial_fixture(operation, zero=True)
        raw["entries"] = partial_fixture(operation)["entries"]
        with pytest.raises(MonetaryResponseError):
            project_monetary_partial_plan(raw, SCOPE)


def test_balance_retains_public_scope_quantity_and_dual_policy_without_source_bodies() -> None:
    raw = {**monetary_balance(), **SCOPE, "schema_version": "customer-partial-return-monetary-balance-v3", "source_id": "origin",
        "source_order_id": "monetary-stock", "invoice_id": "invoice", "source_fingerprint": "c" * 64,
        "transaction_policy": captured_policy("EUR"), "functional_policy": captured_policy("USD"), "quantity_precision": 0,
        "original_quantity_scaled": "10", "returned_quantity_scaled": "2", "remaining_quantity_scaled": "8"}
    assert project_monetary_partial_balance(raw, SCOPE) == raw
    for patch in ({"remaining_quantity_scaled": "9"}, {"history_version": True}, {"transaction_refund_due_minor": "1"}, {"original": {"private": "body"}}):
        with pytest.raises(MonetaryResponseError):
            project_monetary_partial_balance({**raw, **patch}, SCOPE)


def test_public_page_projection_is_closed_and_duplicate_ids_cannot_hide_commands() -> None:
    with pytest.raises(MonetaryResponseError):
        project_monetary_stock_response({"orders": [stock_fixture(), stock_fixture()]}, SCOPE, listing=True)
    for raw in ({"plans": [partial_fixture(), partial_fixture()]}, {"plan": partial_fixture(), "private": {}}, {"plans": [stock_fixture()]}):
        with pytest.raises(MonetaryResponseError):
            project_monetary_partial_response(raw, SCOPE)


def partial_balance_fixture() -> dict[str, Any]:
    return {**monetary_balance(), **SCOPE, "schema_version": "customer-partial-return-monetary-balance-v3", "source_id": "origin",
        "source_order_id": "monetary-stock", "invoice_id": "invoice", "source_fingerprint": "c" * 64,
        "transaction_policy": captured_policy("EUR"), "functional_policy": captured_policy("USD"), "quantity_precision": 0,
        "original_quantity_scaled": "10", "returned_quantity_scaled": "2", "remaining_quantity_scaled": "8"}


@pytest.mark.parametrize("field,value", [("transaction_outstanding_minor", "1199"), ("transaction_refund_entitlement_minor", "1"),
                                         ("functional_outstanding_minor", "1"), ("functional_refund_due_minor", "1")])
def test_balance_checks_foreign_equations_and_zero_residual_carrying_money(field: str, value: str) -> None:
    raw = partial_balance_fixture()
    if field.startswith("functional"):
        raw.update(transaction_credited_minor="1200", transaction_outstanding_minor="0", functional_outstanding_minor="0")
        if field == "functional_refund_due_minor":
            raw["functional_refund_entitlement_minor"] = "1"
    raw[field] = value
    with pytest.raises(MonetaryResponseError):
        project_monetary_partial_balance(raw, SCOPE)


def test_same_currency_balances_cannot_publish_different_carrying_amounts() -> None:
    raw = partial_balance_fixture()
    raw["transaction_policy"] = captured_policy("USD")
    # Every foreign equation remains coherent. The retained policies instead
    # prove identity currency, where 1200 cannot be carried as 1500.
    with pytest.raises(MonetaryResponseError):
        project_monetary_partial_balance(raw, SCOPE)
    raw.update(functional_original_gross_minor="1200", functional_outstanding_minor="1200")
    assert project_monetary_partial_balance(raw, SCOPE) == raw
    raw.update(transaction_collected_minor="1200", transaction_credited_minor="600", transaction_outstanding_minor="0", functional_outstanding_minor="0",
        transaction_refund_entitlement_minor="600", functional_refund_entitlement_minor="601", transaction_refunded_minor="100", functional_refund_released_minor="101",
        transaction_refund_due_minor="500", functional_refund_due_minor="500")
    with pytest.raises(MonetaryResponseError):
        project_monetary_partial_balance(raw, SCOPE)
    raw.update(functional_refund_entitlement_minor="600", functional_refund_released_minor="100")
    assert project_monetary_partial_balance(raw, SCOPE) == raw


def test_source_captured_policies_cannot_mix_registry_versions_or_identity_precision() -> None:
    raw = stock_fixture(0)
    raw["functional_policy"]["currency_registry_version"] = "other"
    with pytest.raises(MonetaryResponseError):
        project_monetary_stock(raw, SCOPE)
    raw = stock_fixture(0)
    raw["transaction_policy"] = captured_policy("USD")
    raw["functional_policy"]["currency_precision"] = 3
    with pytest.raises(MonetaryResponseError):
        project_monetary_stock(raw, SCOPE)


def test_identity_merchandise_credit_cannot_report_fx_or_mismatched_currency_amounts() -> None:
    raw = partial_fixture()
    raw["transaction_policy"] = captured_policy("USD")
    with pytest.raises(MonetaryResponseError):
        project_monetary_partial_plan(raw, SCOPE)
    raw["monetary"].update(functional_net_minor="500", functional_tax_minor="100", functional_credit_minor="600", functional_receivable_released_minor="400",
        functional_refund_delta_minor="200", functional_turnover_minor="800")
    assert project_monetary_partial_plan(raw, SCOPE) == raw
    raw["monetary"].update(functional_alignment_loss_minor="1", functional_alignment_gain_minor="0", functional_receivable_released_minor="401", functional_turnover_minor="801")
    with pytest.raises(MonetaryResponseError):
        project_monetary_partial_plan(raw, SCOPE)


@pytest.mark.parametrize("mutation", ["overcollection", "overentitlement", "zero-entitlement", "zero-refunded"])
def test_monetary_balance_refuses_impossible_captured_cash_or_refund_carrying_values(mutation: str) -> None:
    raw = partial_balance_fixture()
    raw.update(transaction_collected_minor="1200", transaction_credited_minor="600", transaction_outstanding_minor="0", functional_outstanding_minor="0",
        transaction_refund_entitlement_minor="600", functional_refund_entitlement_minor="750", transaction_refunded_minor="0", functional_refund_released_minor="0",
        transaction_refund_due_minor="600", functional_refund_due_minor="750")
    if mutation == "overcollection":
        raw.update(transaction_collected_minor="1201", transaction_credited_minor="0", transaction_refund_entitlement_minor="1", transaction_refund_due_minor="1",
            functional_refund_entitlement_minor="1", functional_refund_due_minor="1")
    elif mutation == "overentitlement":
        raw.update(transaction_credited_minor="1200", transaction_refund_entitlement_minor="1200", transaction_refund_due_minor="1200",
            functional_refund_entitlement_minor="1501", functional_refund_due_minor="1501")
    elif mutation == "zero-entitlement":
        raw.update(transaction_credited_minor="0", transaction_refund_entitlement_minor="0", transaction_refund_due_minor="0",
            functional_refund_entitlement_minor="1", functional_refund_released_minor="1", functional_refund_due_minor="0")
    else:
        raw.update(functional_refund_released_minor="1", functional_refund_due_minor="749")
    with pytest.raises(MonetaryResponseError):
        project_monetary_partial_balance(raw, SCOPE)


def test_monetary_balance_allows_refundable_credit_above_cash_residual_and_small_zero_functional_legs() -> None:
    raw = partial_balance_fixture()
    raw.update(transaction_collected_minor="1200", transaction_credited_minor="600", transaction_outstanding_minor="0", functional_outstanding_minor="0",
        transaction_refund_entitlement_minor="600", functional_refund_entitlement_minor="750", transaction_refunded_minor="100", functional_refund_released_minor="125",
        transaction_refund_due_minor="500", functional_refund_due_minor="625")
    assert project_monetary_partial_balance(raw, SCOPE) == raw
    raw.update(functional_refund_entitlement_minor="0", functional_refund_released_minor="0", functional_refund_due_minor="0")
    assert project_monetary_partial_balance(raw, SCOPE) == raw


def collection_stock_fixture(phase: int) -> dict[str, Any]:
    row = stock_fixture()
    steps = [("prepare-collection", "CollectionPrepared", "maker"), ("review-collection", "CollectionReviewed", "checker"), ("collect", "Invoiced", "poster")]
    row["events"] += [{"version": 11 + i, "actor_id": actor, "operation": operation, "reason": "Synthetic collection", "status": status, "audit_event_id": "cash-audit-" + str(i)}
                      for i, (operation, status, actor) in enumerate(steps[:phase + 1])]
    row.update(status=steps[phase][1], row_version=11 + phase)
    row["collection"] = {"id": "collection-plan", "sequence": 1, "status": ("Prepared", "Reviewed", "Posted")[phase], "plan_digest": "d" * 64,
        "amount_minor": "200", "functional_cash_minor": "260", "functional_receivable_released_minor": "250", "functional_fx_gain_minor": "10", "functional_fx_loss_minor": "0",
        "settlement_rate": {**RATE, "rate": "1.3"}, "receipt_number": "FX1-SYNTHETIC-RECEIPT", "receipt_date": "2026-10-15", "period_id": "PERIOD",
        "preparer_actor_id": "maker", "reviewer_actor_id": "checker" if phase > 0 else None, "posted_actor_id": "poster" if phase == 2 else None,
        "entry_id": "collection-entry", "posting_effect_id": "collection-effect" if phase == 2 else None, "receipt_id": "native-receipt" if phase == 2 else None}
    row["balance"]["active_plan_id"] = "collection-plan" if phase < 2 else None
    if phase == 2:
        row["balance"].update(transaction_collected_minor="200", transaction_outstanding_minor="1000", functional_outstanding_minor="1250")
    return row


@pytest.mark.parametrize("phase", [0, 1, 2])
def test_current_collection_phase_and_presence_are_bound_to_actual_stock_event_history(phase: int) -> None:
    raw = collection_stock_fixture(phase)
    assert project_monetary_stock(raw, SCOPE) == raw
    without_current = deepcopy(raw)
    without_current["collection"] = None
    with pytest.raises(MonetaryResponseError):
        project_monetary_stock(without_current, SCOPE)
    different = deepcopy(raw)
    different["collection"].update(status="Prepared" if phase else "Reviewed", reviewer_actor_id=None if phase else "checker", posted_actor_id=None, posting_effect_id=None, receipt_id=None)
    different["balance"]["active_plan_id"] = "collection-plan"
    with pytest.raises(MonetaryResponseError):
        project_monetary_stock(different, SCOPE)
