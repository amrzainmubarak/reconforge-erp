"""Real app registration and strict request models; no native posting claim."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from reconforge.api import create_api_app
from reconforge.api.routes import customer_partial_returns_v3 as partial
from reconforge.api.routes import stock_sales_v2 as stock
from tests.api_route_registration import registered_http_operations

HISTORY = {"command_id": "synthetic-command", "expected_history_version": 0, "period_id": "period", "posting_date": "2026-10-15", "reason": "Explicit actual intent"}
RETURN = {**HISTORY, "source_order_id": "original-monetary-stock", "quantity_scaled": "1"}
COLLECTION = {"command_id": "synthetic-command", "expected_version": 10, "reason": "Explicit collection intent", "receipt_number": "CASH", "receipt_date": "2026-10-15", "period_id": "period", "amount_minor": "1", "settlement_rate": None}
INVOICE = {"command_id": "synthetic-command", "expected_version": 7, "reason": "Explicit origin intent", "invoice_number": "INVOICE", "invoice_date": "2026-10-15", "due_date": "2026-10-31", "period_id": "period", "journal_code": "SALES",
           "receivable_account_code": "AR", "revenue_account_code": "REVENUE", "cash_account_code": "CASH", "refund_liability_account_code": "REFUND", "gain_account_code": "GAIN", "loss_account_code": "LOSS", "country_code": "ZZ", "transaction_class": "synthetic-merchandise", "taxes": [], "original_rate": None}


def test_real_app_registers_exactly_26_fixed_monetary_routes_and_preserves_legacy_contracts(tmp_path: Path) -> None:
    app = create_api_app(tmp_path / "unopened.db")
    operations = registered_http_operations(app)
    contracts = {(row.method, row.path): row for row in app.state.authorization_contracts}
    added = {key: value for key, value in contracts.items() if key[1].startswith(("/api/v2/stock-sales/", "/api/v3/customer-partial-returns/"))}
    assert len(added) == 26 and all(operations[key] == 1 and row.mode == "all" for key, row in added.items())
    for (method, path), row in added.items():
        old_path = path.replace("/api/v2/stock-sales/", "/api/v1/stock-sales/").replace("/api/v3/customer-partial-returns/", "/api/v1/customer-partial-returns/")
        expected = set(contracts[(method, old_path)].permissions)
        if path.endswith("/collection/prepare"):
            expected.add("receivables.manage")
        if path.endswith("/collection/review"):
            expected.add("receivables.approve")
        assert set(row.permissions) == expected
    assert not any("/api/v2/stock-sales/commerce/" in path for _method, path in operations)


def test_real_registered_monetary_surfaces_refuse_local_fallback_before_native_execution(tmp_path: Path) -> None:
    app = create_api_app(tmp_path / "auth.db")
    with TestClient(app) as client:
        for path in ("/api/v2/stock-sales/options", "/api/v2/stock-sales/orders", "/api/v3/customer-partial-returns/plans"):
            response = client.get(path)
            assert response.status_code == 503
            assert response.json()["error"]["code"] in {"stock_monetary_backend_unavailable", "monetary_partial_return_backend_unavailable"}
        response = client.post("/api/v3/customer-partial-returns/plans", json=RETURN)
        assert response.status_code == 503 and response.json()["error"]["code"] == "monetary_partial_return_backend_unavailable"


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
