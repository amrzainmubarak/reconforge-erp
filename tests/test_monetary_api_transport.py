"""Real app registration and strict request models; no native posting claim."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from reconforge.api import create_api_app
from reconforge.api.routes import customer_partial_returns_v3 as partial
from reconforge.api.routes import stock_sales_v2 as stock
from reconforge.db import run_migrations
from tests.api_route_registration import registered_http_operations

HISTORY = {"command_id": "synthetic-command", "expected_history_version": 0, "period_id": "period", "posting_date": "2026-10-15", "reason": "Explicit actual intent"}
RETURN = {**HISTORY, "source_order_id": "original-monetary-stock", "quantity_scaled": "1"}
COLLECTION = {"command_id": "synthetic-command", "expected_version": 10, "reason": "Explicit collection intent", "receipt_number": "CASH", "receipt_date": "2026-10-15", "period_id": "period", "amount_minor": "1", "settlement_rate": None}
INVOICE = {"command_id": "synthetic-command", "expected_version": 7, "reason": "Explicit origin intent", "invoice_number": "INVOICE", "invoice_date": "2026-10-15", "due_date": "2026-10-31", "period_id": "period", "journal_code": "SALES",
           "receivable_account_code": "AR", "revenue_account_code": "REVENUE", "cash_account_code": "CASH", "refund_liability_account_code": "REFUND", "gain_account_code": "GAIN", "loss_account_code": "LOSS", "country_code": "ZZ", "transaction_class": "synthetic-merchandise", "taxes": [], "original_rate": None}


def test_real_app_registers_exactly_31_fixed_monetary_routes_and_preserves_legacy_contracts(tmp_path: Path) -> None:
    app = create_api_app(tmp_path / "unopened.db")
    operations = registered_http_operations(app)
    contracts = {(row.method, row.path): row for row in app.state.authorization_contracts}
    added = {key: value for key, value in contracts.items() if key[1].startswith(("/api/v2/stock-sales/", "/api/v3/customer-partial-returns/"))}
    assert len(added) == 31 and all(operations[key] == 1 and row.mode == "all" for key, row in added.items())
    valuation_root = "/api/v2/stock-sales/orders/{identifier}/"
    valuation_permissions = {
        ("POST", valuation_root + "valuations"): {"finance_core.manage", "receivables.manage"},
        ("POST", valuation_root + "valuation-reversals"): {"finance_core.manage", "receivables.manage", "finance_core.reverse"},
        ("GET", valuation_root + "fx-plans/{plan_id}"): set(),
        ("POST", valuation_root + "fx-plans/{plan_id}/review"): {"finance_core.validate", "receivables.approve"},
        ("POST", valuation_root + "fx-plans/{plan_id}/post"): {"finance_core.post", "receivables.manage"},
    }
    for (method, path), row in added.items():
        if (method, path) in valuation_permissions:
            assert set(row.permissions) == {"sales.read", "inventory.read", "receivables.read", "finance_core.read"} | valuation_permissions[(method, path)]
            continue
        old_path = path.replace("/api/v2/stock-sales/", "/api/v1/stock-sales/").replace("/api/v3/customer-partial-returns/", "/api/v1/customer-partial-returns/")
        expected = set(contracts[(method, old_path)].permissions)
        if path.endswith("/collection/prepare"):
            expected.add("receivables.manage")
        if path.endswith("/collection/review"):
            expected.add("receivables.approve")
        assert set(row.permissions) == expected
    assert not any("/api/v2/stock-sales/commerce/" in path for _method, path in operations)


def test_real_registered_monetary_surfaces_require_identity_before_native_execution(tmp_path: Path) -> None:
    db_path = tmp_path / "auth.db"
    run_migrations(db_path)
    app = create_api_app(db_path)
    with TestClient(app) as client:
        for path in ("/api/v2/stock-sales/options", "/api/v2/stock-sales/orders", "/api/v3/customer-partial-returns/plans"):
            response = client.get(path)
            assert response.status_code == 401 and response.json()["error"]["code"] == "auth_required"
        response = client.post("/api/v3/customer-partial-returns/plans", json=RETURN)
        assert response.status_code == 401 and response.json()["error"]["code"] == "auth_required"


@pytest.mark.parametrize("model,payload,field", [(partial.ReturnRequest, RETURN, "quantity_scaled"), (partial.RefundRequest, {**HISTORY, "amount_minor": "1", "settlement_rate": None}, "amount_minor"), (stock.CollectionRequest, COLLECTION, "amount_minor")])
@pytest.mark.parametrize("bad", [True, False, 1, 1.0, "01", "+1", "1.0", "1e3", "0", "9000000000000000001"])
def test_new_monetary_request_amounts_never_coerce_numeric_or_noncanonical_values(model, payload, field, bad) -> None:
    with pytest.raises(ValidationError):
        model.model_validate({**payload, field: bad})


@pytest.mark.parametrize("extra", [{"actor_id": "spoof"}, {"workspace_id": "foreign"}, {"allocation_policy": "client-policy"}, {"journal_code": "different"}, {"refund_liability_account_code": "override"}, {"transaction_credit_minor": "100"}])
def test_cr3_returns_take_intent_and_server_scope_without_client_accounting_authority(extra) -> None:
    with pytest.raises(ValidationError):
        partial.ReturnRequest.model_validate({**RETURN, **extra})


@pytest.mark.parametrize("model,payload,field", [(stock.InvoiceRequest, INVOICE, "original_rate"), (stock.CollectionRequest, COLLECTION, "settlement_rate"), (partial.RefundRequest, {**HISTORY, "amount_minor": "1", "settlement_rate": None}, "settlement_rate")])
def test_currency_identity_requires_explicit_null_rate_and_never_a_missing_default(model, payload, field) -> None:
    assert getattr(model.model_validate(payload), field) is None
    with pytest.raises(ValidationError):
        model.model_validate({key: value for key, value in payload.items() if key != field})


@pytest.mark.parametrize("model,payload,field", [(stock.InvoiceRequest, INVOICE, "invoice_number"), (stock.CollectionRequest, COLLECTION, "receipt_number")])
def test_document_request_leaves_room_for_actual_fx_native_number_prefix(model, payload, field) -> None:
    assert getattr(model.model_validate({**payload, field: "D" * 60}), field) == "D" * 60
    with pytest.raises(ValidationError):
        model.model_validate({**payload, field: "D" * 61})


def test_large_minor_and_scaled_units_survive_exactly_and_reversal_has_no_rate_selector() -> None:
    assert partial.ReturnRequest.model_validate({**RETURN, "quantity_scaled": "9007199254740993"}).quantity_scaled == "9007199254740993"
    assert stock.CollectionRequest.model_validate({**COLLECTION, "amount_minor": "9007199254740993"}).amount_minor == "9007199254740993"
    with pytest.raises(ValidationError):
        partial.legacy.ReversalRequest.model_validate({**HISTORY, "settlement_rate": None})


@pytest.mark.parametrize("extra", [{"amount_minor": "140"}, {"source_order_id": "spoof"}, {"functional_valued_outstanding_minor": "840"}, {"transaction_policy": {}}, {"actor_id": "spoof"}])
def test_source_valuation_requests_never_accept_client_amount_or_authority(extra) -> None:
    body = {"command_id": "synthetic-command", "closing_rate": {"rate": "1.50", "source": "Synthetic observation", "effective_at": "2026-10-15T12:00:00Z"}, "period_id": "period", "posting_date": "2026-10-15", "reason": "Close current source residual", "unrealized_gain_account_code": "GAIN", "unrealized_loss_account_code": "LOSS"}
    with pytest.raises(ValidationError):
        stock.ValuationRequest.model_validate({**body, **extra})


def test_source_valuation_inverse_takes_no_new_rate_and_requires_an_actual_fx_plan_identity() -> None:
    body = {"command_id": "synthetic-command", "original_revaluation_id": "FX1-" + "1" * 32, "period_id": "period", "posting_date": "2026-10-16", "reason": "Exact inverse"}
    assert stock.ValuationReversalRequest.model_validate(body).original_revaluation_id == body["original_revaluation_id"]
    for change in ({"closing_rate": None}, {"original_revaluation_id": "CR3-" + "1" * 32}, {"posting_date": "2026-02-30"}):
        with pytest.raises(ValidationError):
            stock.ValuationReversalRequest.model_validate({**body, **change})
