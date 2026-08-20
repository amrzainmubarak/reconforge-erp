from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from reconforge.connectors.erpnext_payment_writeback import (
    ERP_NEXT_PAYMENT_ENTRY_WRITEBACK_ENDPOINT,
    ERP_NEXT_PAYMENT_ENTRY_WRITEBACK_OPERATION,
    ErpNextPaymentEntryDraft,
    build_erpnext_payment_entry_payload,
    erpnext_payment_entry_writeback_registration,
)
from reconforge.connectors.writeback import WritebackIntent, WritebackPolicy, approve_writeback, dispatch_writeback
from reconforge.connectors.writeback_network import (
    WritebackNetworkError,
    WritebackNetworkExecutor,
    WritebackNetworkResponse,
)

NOW = datetime(2026, 8, 11, 10, 0, tzinfo=UTC)
CONNECTOR_ID = "erpnext-payment-entry-writeback"
POLICY = WritebackPolicy(
    connector_id=CONNECTOR_ID,
    allowed_operations=frozenset({ERP_NEXT_PAYMENT_ENTRY_WRITEBACK_OPERATION}),
    feature_enabled=True,
)


def _draft() -> ErpNextPaymentEntryDraft:
    return ErpNextPaymentEntryDraft(
        company="Acme",
        posting_date="2026-08-11",
        paid_from="1100 - Cash",
        paid_to="2100 - Supplier Payables",
        paid_amount="125.00",
        received_amount="0.00",
        paid_from_account_currency="USD",
        paid_to_account_currency="USD",
        party_type="Supplier",
        party="SUP-001",
        reference_no="PAY-2026-001",
        remarks="Synthetic provider-compatible draft",
    )


def _intent(payload_digest: str) -> WritebackIntent:
    return WritebackIntent(
        schema_version="connector-writeback-intent-v1",
        intent_id="erpnext-payment-writeback-1",
        tenant_id="tenant-a",
        workspace_id="workspace-a",
        connector_id=CONNECTOR_ID,
        operation=ERP_NEXT_PAYMENT_ENTRY_WRITEBACK_OPERATION,
        payload_digest=payload_digest,
        idempotency_key="erpnext-payment-writeback-1",
        requested_by="maker-1",
        requested_at=NOW,
        feature_enabled=True,
    )


def _provider_body(idempotency_key: str) -> bytes:
    fields = {
        "accepted": True,
        "idempotency_key": idempotency_key,
        "provider_reference": "ERPNext-PAY-DRAFT-1",
    }
    response_digest = hashlib.sha256(
        json.dumps(fields, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("ascii")
    ).hexdigest()
    return json.dumps(
        {**fields, "response_digest": response_digest},
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")


@dataclass
class _Secrets:
    def resolve(self, reference: str) -> bytes:
        assert reference == "vault://tenant-a/erpnext"
        return b"api-key:api-secret"


@dataclass
class _Transport:
    response: WritebackNetworkResponse
    calls: list[tuple[str, dict[str, str], bytes]] = field(default_factory=list)

    def post(
        self,
        endpoint: str,
        *,
        headers: dict[str, str],
        body: bytes,
        timeout_seconds: int,
        maximum_response_bytes: int,
    ) -> WritebackNetworkResponse:
        del timeout_seconds, maximum_response_bytes
        self.calls.append((endpoint, dict(headers), body))
        return self.response


def test_payment_entry_payload_is_exact_balanced_and_deterministic() -> None:
    first = build_erpnext_payment_entry_payload(_draft())
    second = build_erpnext_payment_entry_payload(_draft())

    assert first.operation == ERP_NEXT_PAYMENT_ENTRY_WRITEBACK_OPERATION
    assert first.payload == second.payload
    assert first.payload_digest == second.payload_digest
    document = json.loads(first.payload)
    assert document == {
        "company": "Acme",
        "doctype": "Payment Entry",
        "docstatus": 0,
        "paid_amount": "125.00",
        "paid_from": "1100 - Cash",
        "paid_from_account_currency": "USD",
        "paid_to": "2100 - Supplier Payables",
        "paid_to_account_currency": "USD",
        "party": "SUP-001",
        "party_type": "Supplier",
        "posting_date": "2026-08-11",
        "received_amount": "0.00",
        "reference_no": "PAY-2026-001",
        "remarks": "Synthetic provider-compatible draft",
    }
    assert hashlib.sha256(first.payload).hexdigest() == first.payload_digest


@pytest.mark.parametrize(
    "updates",
    [
        {"paid_amount": "0", "received_amount": "0"},
        {"paid_amount": "1", "received_amount": "2"},
        {"paid_amount": "NaN"},
        {"paid_amount": "-1"},
        {"paid_from": "1100 - Cash", "paid_to": "1100 - Cash"},
        {"paid_from_account_currency": "usd"},
    ],
)
def test_payment_entry_draft_rejects_ambiguous_or_unsafe_financial_inputs(updates: dict[str, str]) -> None:
    values = _draft().model_dump()
    values.update(updates)
    with pytest.raises(ValidationError):
        ErpNextPaymentEntryDraft.model_validate(values)


def test_payment_entry_registration_is_disabled_and_endpoint_hardened() -> None:
    registration = erpnext_payment_entry_writeback_registration(credential_reference="vault://tenant-a/erpnext")
    assert registration.feature_enabled is False
    assert registration.credential_auth_scheme == "token"
    assert registration.endpoint == ERP_NEXT_PAYMENT_ENTRY_WRITEBACK_ENDPOINT
    assert registration.allowed_operations == frozenset({ERP_NEXT_PAYMENT_ENTRY_WRITEBACK_OPERATION})
    for endpoint in (
        "http://erpnext.example.test/api/resource/Payment%20Entry",
        "https://erpnext.example.test/api/resource/Journal%20Entry",
        "https://erpnext.example.test/api/resource/Payment%20Entry?x=1",
        "https://user:pass@erpnext.example.test/api/resource/Payment%20Entry",
    ):
        with pytest.raises(WritebackNetworkError, match="endpoint_invalid"):
            erpnext_payment_entry_writeback_registration(
                credential_reference="vault://tenant-a/erpnext", endpoint=endpoint
            )


def test_payment_entry_dispatch_requires_enablement_and_keeps_secret_out_of_receipt() -> None:
    payload = build_erpnext_payment_entry_payload(_draft())
    approved = approve_writeback(
        _intent(payload.payload_digest),
        policy=POLICY,
        actor_id="checker-1",
        approved_at=NOW,
        assurance="mfa",
        reason="independent payment review",
    )
    dispatched = dispatch_writeback(approved, policy=POLICY)
    registration = erpnext_payment_entry_writeback_registration(
        credential_reference="vault://tenant-a/erpnext"
    ).model_copy(update={"feature_enabled": True})

    class Payloads:
        def resolve(self, _intent: object) -> bytes:
            return payload.payload

    transport = _Transport(WritebackNetworkResponse(201, _provider_body(dispatched.idempotency_key)))
    receipt = WritebackNetworkExecutor(
        transport,
        payload_resolver=Payloads(),
        secret_resolver=_Secrets(),
    ).dispatch(dispatched, registration=registration, policy=POLICY)

    assert receipt.intent.acknowledgement is not None
    assert receipt.intent.acknowledgement.provider_reference == "ERPNext-PAY-DRAFT-1"
    endpoint, headers, body = transport.calls[0]
    assert endpoint == ERP_NEXT_PAYMENT_ENTRY_WRITEBACK_ENDPOINT
    assert headers["Authorization"] == "token api-key:api-secret"
    assert headers["Idempotency-Key"] == dispatched.idempotency_key
    assert headers["X-ReconForge-Operation"] == ERP_NEXT_PAYMENT_ENTRY_WRITEBACK_OPERATION
    assert body == payload.payload
    assert b"api-key:api-secret" not in receipt.intent.model_dump_json().encode("utf-8")


def test_payment_entry_writeback_contract_is_packaged() -> None:
    root = Path(__file__).resolve().parents[1]
    manifest = (root / "MANIFEST.in").read_text(encoding="utf-8")
    assert "include reconforge/connectors/erpnext_payment_writeback.py" in manifest
    assert "include tests/test_connector_erpnext_payment_writeback.py" in manifest
    assert "include docs/connectors/erpnext-payment-entry-writeback.md" in manifest
    assert "include docs/adr/0511-erpnext-payment-entry-writeback.md" in manifest
    assert "include docs/adr/0512-erpnext-payment-entry-api-replay-fence.md" in manifest
