from __future__ import annotations

import ast
import json
from functools import partial
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from reconforge.auth import LocalAuthService
from reconforge.db import connect, run_migrations
from reconforge.io import persisted as persisted_module
from reconforge.io.persisted import (
    FINANCIAL_IDEMPOTENCY_JSON_POLICY,
    FINANCIAL_IDEMPOTENCY_JSON_PROFILE,
    FINANCIAL_IDEMPOTENCY_RESPONSE_SCHEMA,
    PersistedJsonError,
    decode_financial_idempotency_response,
    encode_financial_idempotency_response,
)
from reconforge.io.structured import StructuredDocumentPolicy
from reconforge.platform.common import PlatformError
from reconforge.platform.payables import PayablesService, PurchaseOrderLineInput
from reconforge.platform.receivables import ReceivableInvoiceLineInput, ReceivablesService

ROOT = Path(__file__).resolve().parents[1]


def test_financial_idempotency_round_trip_is_canonical_bounded_and_schema_valid() -> None:
    payload = {
        "id": "INV-1",
        "total_minor": 1234,
        "quantity": "2.500",
        "lines": [{"line_total_minor": 1234}],
    }

    encoded = encode_financial_idempotency_response(payload)
    decoded = decode_financial_idempotency_response(encoded.text)
    schema = json.loads(
        (ROOT / "docs/schemas/financial_idempotency_response.schema.json").read_text(encoding="utf-8")
    )

    assert encoded.text == '{"id":"INV-1","lines":[{"line_total_minor":1234}],"quantity":"2.500","total_minor":1234}'
    assert decoded.payload == payload
    assert decoded.size_bytes == len(encoded.text.encode("utf-8"))
    assert decoded.checksum_sha256 == encoded.checksum_sha256
    assert decoded.profile_id == FINANCIAL_IDEMPOTENCY_JSON_PROFILE
    assert decoded.schema_id == FINANCIAL_IDEMPOTENCY_RESPONSE_SCHEMA
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(decoded.payload)


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ('{"id":"1","id":"2"}', "persisted_json_duplicate_key"),
        ('{"amount":1.25}', "persisted_document_fractional_number_forbidden"),
        ('{"amount":1e2}', "persisted_document_fractional_number_forbidden"),
        ('{"amount":NaN}', "persisted_document_non_finite_number"),
        ('[]', "persisted_json_object_required"),
    ],
)
def test_financial_idempotency_decoder_rejects_ambiguous_or_unsafe_values(text: str, code: str) -> None:
    with pytest.raises(PersistedJsonError) as captured:
        decode_financial_idempotency_response(text)
    assert captured.value.code == code


def test_financial_idempotency_encoder_rejects_binary_float_and_cycles() -> None:
    with pytest.raises(PersistedJsonError) as captured:
        encode_financial_idempotency_response({"amount": 1.25})
    assert captured.value.code == "persisted_json_fractional_number_forbidden"

    cyclic: dict[str, object] = {}
    cyclic["self"] = cyclic
    with pytest.raises(PersistedJsonError) as captured:
        encode_financial_idempotency_response(cyclic)
    assert captured.value.code == "persisted_json_cycle_forbidden"


def test_financial_idempotency_runtime_policy_bounds_bytes_and_graph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        persisted_module,
        "FINANCIAL_IDEMPOTENCY_JSON_POLICY",
        StructuredDocumentPolicy(
            max_file_bytes=32,
            max_nodes=4,
            max_depth=2,
            max_collection_items=2,
            max_scalar_characters=8,
            max_yaml_aliases=1,
        ),
    )
    with pytest.raises(PersistedJsonError):
        decode_financial_idempotency_response('{"value":"more-than-eight"}')
    with pytest.raises(PersistedJsonError):
        encode_financial_idempotency_response({"nested": {"value": "x"}})


def _ap_service(tmp_path: Path) -> tuple[object, PayablesService]:
    path = tmp_path / "ap.db"
    run_migrations(path)
    connection = connect(path, require_exists=True)
    service = PayablesService(connection)
    service.upsert_supplier(supplier_code="SUP-JSON", name="Synthetic Supplier", currency_code="USD")
    return connection, service


def _create_purchase_order(service: PayablesService) -> dict[str, object]:
    return service.create_purchase_order(
        po_number="PO-JSON",
        supplier_code="SUP-JSON",
        order_date="2026-07-26",
        currency_code="USD",
        lines=[PurchaseOrderLineInput(item_code="ITEM-1", ordered_quantity="1.000", unit_price_minor=125)],
        idempotency_key="ap-json-key",
    )


def _ar_service(tmp_path: Path) -> tuple[object, ReceivablesService]:
    path = tmp_path / "ar.db"
    run_migrations(path)
    connection = connect(path, require_exists=True)
    auth = LocalAuthService(connection)
    auth.init_admin(username="admin", password="Secret-123")
    auth.create_user(username="prep", password="Secret-123", role="preparer")
    service = ReceivablesService(connection)
    service.upsert_customer(
        customer_code="CUS-JSON",
        name="Synthetic Customer",
        currency_code="USD",
        credit_limit_minor=10_000,
        actor_label="prep",
    )
    return connection, service


def _create_invoice(service: ReceivablesService) -> dict[str, object]:
    return service.create_invoice(
        invoice_number="AR-JSON",
        customer_code="CUS-JSON",
        invoice_date="2026-07-26",
        currency_code="USD",
        tax_minor=0,
        lines=[
            ReceivableInvoiceLineInput(
                description="Synthetic line",
                quantity="1.000",
                unit_price_minor=125,
                line_total_minor=125,
            )
        ],
        idempotency_key="ar-json-key",
        actor_label="prep",
    )


@pytest.mark.parametrize("domain", ["ap", "ar"])
def test_corrupt_stored_financial_idempotency_response_rejects_before_new_business_effect(
    tmp_path: Path,
    domain: str,
) -> None:
    if domain == "ap":
        connection, service = _ap_service(tmp_path)
        create = partial(_create_purchase_order, service)
        table = "ap_idempotency_keys"
        business_table = "ap_purchase_orders"
    else:
        connection, service = _ar_service(tmp_path)
        create = partial(_create_invoice, service)
        table = "ar_idempotency_keys"
        business_table = "ar_invoices"
    try:
        create()
        connection.execute(f"UPDATE {table} SET response_json = ?", ('{"id":"first","id":"second"}',))
        connection.commit()
        before = {
            "business": connection.execute(f"SELECT COUNT(*) AS count FROM {business_table}").fetchone()["count"],
            "audit": connection.execute("SELECT COUNT(*) AS count FROM audit_events").fetchone()["count"],
            "outbox": connection.execute("SELECT COUNT(*) AS count FROM outbox_events").fetchone()["count"],
        }

        with pytest.raises(PlatformError, match="Stored .*idempotency response is invalid"):
            create()

        after = {
            "business": connection.execute(f"SELECT COUNT(*) AS count FROM {business_table}").fetchone()["count"],
            "audit": connection.execute("SELECT COUNT(*) AS count FROM audit_events").fetchone()["count"],
            "outbox": connection.execute("SELECT COUNT(*) AS count FROM outbox_events").fetchone()["count"],
        }
        assert after == before
    finally:
        connection.close()


@pytest.mark.parametrize("domain", ["ap", "ar"])
def test_oversized_new_financial_idempotency_response_rolls_back_whole_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    domain: str,
) -> None:
    monkeypatch.setattr(
        persisted_module,
        "FINANCIAL_IDEMPOTENCY_JSON_POLICY",
        StructuredDocumentPolicy(max_file_bytes=16),
    )
    if domain == "ap":
        connection, service = _ap_service(tmp_path)
        create = partial(_create_purchase_order, service)
        idempotency_table = "ap_idempotency_keys"
        business_table = "ap_purchase_orders"
        message = "Idempotency response failed safety validation"
    else:
        connection, service = _ar_service(tmp_path)
        create = partial(_create_invoice, service)
        idempotency_table = "ar_idempotency_keys"
        business_table = "ar_invoices"
        message = "Receivables idempotency response failed safety validation"
    try:
        before_audit = connection.execute("SELECT COUNT(*) AS count FROM audit_events").fetchone()["count"]
        before_outbox = connection.execute("SELECT COUNT(*) AS count FROM outbox_events").fetchone()["count"]
        with pytest.raises(PlatformError, match=message):
            create()
        assert connection.execute(f"SELECT COUNT(*) AS count FROM {business_table}").fetchone()["count"] == 0
        assert connection.execute(f"SELECT COUNT(*) AS count FROM {idempotency_table}").fetchone()["count"] == 0
        assert connection.execute("SELECT COUNT(*) AS count FROM audit_events").fetchone()["count"] == before_audit
        assert connection.execute("SELECT COUNT(*) AS count FROM outbox_events").fetchone()["count"] == before_outbox
    finally:
        connection.close()


def test_financial_idempotency_call_sites_have_no_direct_json_parser() -> None:
    forbidden: list[str] = []
    for relative in ("reconforge/platform/payables.py", "reconforge/platform/receivables.py"):
        tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"), filename=relative)
        for call in (node for node in ast.walk(tree) if isinstance(node, ast.Call)):
            if ast.unparse(call.func) in {"json.load", "json.loads"}:
                forbidden.append(f"{relative}:{call.lineno}")
    assert forbidden == []


def test_financial_idempotency_policy_is_intentionally_narrower_than_file_default() -> None:
    policy = FINANCIAL_IDEMPOTENCY_JSON_POLICY
    assert policy.max_file_bytes == 4 * 1024 * 1024
    assert policy.max_nodes == 100_000
    assert policy.max_depth == 32
    assert policy.max_collection_items == 25_000
    assert policy.max_scalar_characters == 256 * 1024
