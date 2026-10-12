"""Exact AR JSON ingress and closed historical-policy response contracts."""

from __future__ import annotations

import json
from copy import deepcopy

import pytest
from pydantic import ValidationError

from reconforge.api.routes.receivables import (
    CustomerRequest,
    InvoiceLineRequest,
    InvoiceRequest,
    ReceiptAllocationRequest,
    ReceiptRequest,
)
from reconforge.auth.field_access import (
    RECEIVABLES_MONETARY_POLICY_FIELDS,
    project_receivables_credit_exposure,
    project_receivables_customer,
    project_receivables_invoice,
    project_receivables_receipt,
)
from reconforge.domain.receivables_policy import verify_receivables_policy
from tests.test_receivables_monetary_policy import SNAPSHOT, record

REQUESTS = [
    (CustomerRequest, {"customer_code": "C", "name": "Synthetic", "currency_code": "JPY", "credit_limit_minor": 1}, "credit_limit_minor"),
    (InvoiceLineRequest, {"quantity": "1", "unit_price_minor": 1, "line_total_minor": 1}, "unit_price_minor"),
    (InvoiceLineRequest, {"quantity": "1", "unit_price_minor": 1, "line_total_minor": 1}, "line_total_minor"),
    (InvoiceLineRequest, {"quantity": "1", "unit_price_minor": 1, "line_total_minor": 1}, "tax_minor"),
    (InvoiceRequest, {"invoice_number": "I", "customer_code": "C", "invoice_date": "2026-10-03", "currency_code": "JPY", "lines": [{"quantity": "1", "unit_price_minor": 1, "line_total_minor": 1}]}, "tax_minor"),
    (ReceiptRequest, {"receipt_number": "R", "customer_code": "C", "receipt_date": "2026-10-03", "currency_code": "JPY", "amount_minor": 1}, "amount_minor"),
    (ReceiptAllocationRequest, {"invoice_id": "I", "amount_minor": 1}, "amount_minor"),
]


@pytest.mark.parametrize("model,base,field", REQUESTS)
@pytest.mark.parametrize("bad", [True, False, 1.0, 9007199254740993.0, "1.0", "1e3"])
def test_every_money_request_refuses_lossy_or_boolean_coercion(model, base, field, bad) -> None:
    with pytest.raises(ValidationError, match="exact integer"):
        model.model_validate_json(json.dumps({**base, field: bad}))


@pytest.mark.parametrize("model,base,field", REQUESTS)
def test_integer_json_and_integer_string_clients_retain_large_exact_value(model, base, field) -> None:
    amount = 9007199254740993
    for value in (amount, str(amount), " +" + str(amount) + " "):
        parsed = model.model_validate_json(json.dumps({**base, field: value}))
        assert getattr(parsed, field) == amount
        assert type(getattr(parsed, field)) is int


@pytest.mark.parametrize("currency,precision", [("JPY", 0), ("KWD", 3)])
def test_closed_policy_and_exact_text_follow_retained_record(currency, precision) -> None:
    policy = verify_receivables_policy(record(currency), snapshot=SNAPSHOT).public_metadata()
    injected = {**policy, "secret": "must-not-escape", "snapshot": {"private": "must-not-escape"}}
    amount = 9007199254740993
    customer = project_receivables_customer({"currency_code": currency, "credit_limit_minor": amount, "credit_limit_minor_text": "forged", "monetary_policy": injected}).visible
    invoice = project_receivables_invoice({"currency_code": currency, "total_minor": amount, "monetary_policy": injected, "lines": [{"unit_price_minor": amount, "line_total_minor": amount, "tax_minor": 0}]}).visible
    receipt = project_receivables_receipt({"currency_code": currency, "amount_minor": amount, "monetary_policy": injected, "allocations": [{"amount_minor": amount}]}).visible
    for result in (customer, invoice, receipt):
        assert result["monetary_policy"] == policy
        assert set(result["monetary_policy"]) == RECEIVABLES_MONETARY_POLICY_FIELDS
        assert result["monetary_policy"]["precision"] == precision
        assert "must-not-escape" not in str(result)
    assert customer["credit_limit_minor_text"] == str(amount)
    assert invoice["total_minor_text"] == str(amount)
    assert invoice["lines"][0]["unit_price_minor_text"] == str(amount)
    assert receipt["amount_minor_text"] == str(amount)
    assert receipt["allocations"][0]["amount_minor_text"] == str(amount)


def test_unverified_history_and_signed_raw_exposure_do_not_invent_scale() -> None:
    policy = verify_receivables_policy({"currency_code": "KWD"}).public_metadata()
    result = project_receivables_customer({"currency_code": "KWD", "credit_limit_minor": 1234, "monetary_policy": policy}).visible
    assert result["monetary_policy"] == policy
    assert result["monetary_policy"]["precision"] is None
    assert result["credit_limit_minor_text"] == "1234"
    raw = project_receivables_credit_exposure({"available_credit_minor": -9007199254740993, "monetary_policy": policy}).visible
    assert raw == {"available_credit_minor": -9007199254740993, "available_credit_minor_text": "-9007199254740993"}
    assert project_receivables_customer({"credit_limit_minor_text": "forged"}).visible == {}


@pytest.mark.parametrize("key,value", [("schema_version", True), ("status", "unknown"), ("currency_code", "USD"), ("precision", True), ("precision", 9), ("registry_digest", "invalid"), ("source", {"private": "secret"})])
def test_invalid_policy_shape_cannot_escape_as_authoritative_metadata(key, value) -> None:
    policy = verify_receivables_policy(record("KWD"), snapshot=SNAPSHOT).public_metadata()
    policy[key] = value
    with pytest.raises(TypeError):
        project_receivables_invoice({"currency_code": "KWD", "monetary_policy": policy})


def test_incomplete_and_falsely_interpreted_legacy_policy_are_rejected() -> None:
    legacy = verify_receivables_policy({"currency_code": "KWD"}).public_metadata()
    for policy in (None, [], {"status": "captured"}, {**legacy, "precision": 3}):
        with pytest.raises(TypeError):
            project_receivables_receipt({"currency_code": "KWD", "monetary_policy": policy})
    changed = deepcopy(legacy)
    changed["registry_version"] = "present-day-version"
    with pytest.raises(TypeError):
        project_receivables_receipt({"currency_code": "KWD", "monetary_policy": changed})


def test_lossy_storage_minor_values_are_not_promoted_to_exact_text() -> None:
    for value in (True, 1.0, "1"):
        with pytest.raises(TypeError):
            project_receivables_receipt({"amount_minor": value})
