from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from reconforge.connectors.erpnext_writeback import (
    ERP_NEXT_JOURNAL_ENTRY_ENDPOINT,
    ERP_NEXT_JOURNAL_ENTRY_OPERATION,
    ErpNextJournalEntryDraft,
    ErpNextJournalEntryLine,
    build_erpnext_journal_entry_payload,
    erpnext_writeback_registration,
)
from reconforge.connectors.writeback import WritebackIntent, WritebackPolicy, approve_writeback, dispatch_writeback
from reconforge.connectors.writeback_network import (
    WritebackNetworkError,
    WritebackNetworkExecutor,
    WritebackNetworkRegistration,
    WritebackNetworkResponse,
)

NOW = datetime(2026, 8, 7, 10, 0, tzinfo=UTC)
CONNECTOR_ID = "erpnext-journal-entry-writeback"
POLICY = WritebackPolicy(
    connector_id=CONNECTOR_ID,
    allowed_operations=frozenset({ERP_NEXT_JOURNAL_ENTRY_OPERATION}),
    feature_enabled=True,
)


def _draft() -> ErpNextJournalEntryDraft:
    return ErpNextJournalEntryDraft(
        company="Acme",
        posting_date="2026-08-07",
        accounts=(
            ErpNextJournalEntryLine(
                account="1100 - Cash",
                debit="100.00",
                credit="0.00",
                account_currency="USD",
            ),
            ErpNextJournalEntryLine(
                account="4000 - Revenue",
                debit="0.00",
                credit="100.00",
                account_currency="USD",
            ),
        ),
        user_remark="Approved reconciliation adjustment",
    )


def _intent(payload_digest: str) -> WritebackIntent:
    return WritebackIntent(
        schema_version="connector-writeback-intent-v1",
        intent_id="erpnext-intent-1",
        tenant_id="tenant-a",
        workspace_id="workspace-a",
        connector_id=CONNECTOR_ID,
        operation=ERP_NEXT_JOURNAL_ENTRY_OPERATION,
        payload_digest=payload_digest,
        idempotency_key="erpnext-writeback-1",
        requested_by="maker-1",
        requested_at=NOW,
        feature_enabled=True,
    )


def _provider_body(idempotency_key: str) -> bytes:
    fields = {
        "accepted": True,
        "idempotency_key": idempotency_key,
        "provider_reference": "JV-DRAFT-1",
    }
    response_digest = hashlib.sha256(json.dumps(fields, sort_keys=True, separators=(",", ":")).encode("ascii")).hexdigest()
    return json.dumps({**fields, "response_digest": response_digest}, sort_keys=True, separators=(",", ":")).encode("ascii")


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


@dataclass
class _Payloads:
    payload: bytes

    def resolve(self, _intent: object) -> bytes:
        return self.payload


def test_erpnext_draft_payload_is_balanced_exact_and_deterministic() -> None:
    payload = build_erpnext_journal_entry_payload(_draft())

    assert payload.operation == ERP_NEXT_JOURNAL_ENTRY_OPERATION
    assert json.loads(payload.payload) == {
        "accounts": [
            {"account": "1100 - Cash", "account_currency": "USD", "credit": "0.00", "debit": "100.00"},
            {"account": "4000 - Revenue", "account_currency": "USD", "credit": "100.00", "debit": "0.00"},
        ],
        "company": "Acme",
        "docstatus": 0,
        "doctype": "Journal Entry",
        "posting_date": "2026-08-07",
        "user_remark": "Approved reconciliation adjustment",
    }
    assert payload.payload_digest == hashlib.sha256(payload.payload).hexdigest()


@pytest.mark.parametrize(
    "line",
    [
        {"account": "Cash", "debit": "1", "credit": "1"},
        {"account": "Cash", "debit": "0", "credit": "0"},
        {"account": "Cash", "debit": "NaN", "credit": "0"},
    ],
)
def test_erpnext_journal_lines_reject_ambiguous_amounts(line: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        ErpNextJournalEntryLine.model_validate(line)


def test_erpnext_draft_rejects_unbalanced_documents() -> None:
    with pytest.raises(ValidationError, match="must balance exactly"):
        ErpNextJournalEntryDraft(
            company="Acme",
            posting_date="2026-08-07",
            accounts=(
                ErpNextJournalEntryLine(account="Cash", debit="100", credit="0"),
                ErpNextJournalEntryLine(account="Revenue", debit="0", credit="99"),
            ),
        )


def test_erpnext_writeback_registration_is_disabled_and_endpoint_hardened() -> None:
    registration = erpnext_writeback_registration(credential_reference="vault://tenant-a/erpnext")
    assert registration.feature_enabled is False
    assert registration.credential_auth_scheme == "token"
    assert registration.endpoint == ERP_NEXT_JOURNAL_ENTRY_ENDPOINT
    bearer_values = registration.model_dump(mode="python")
    bearer_values["credential_auth_scheme"] = "bearer"
    bearer = WritebackNetworkRegistration.model_validate(bearer_values)
    legacy_values = dict(bearer_values)
    legacy_values.pop("credential_auth_scheme")
    legacy = WritebackNetworkRegistration.model_validate(legacy_values)
    assert bearer.digest == legacy.digest
    for endpoint in (
        "http://erpnext.example.test/api/resource/Journal%20Entry",
        "https://erpnext.example.test/api/resource/GL%20Entry",
        "https://erpnext.example.test/api/resource/Journal%20Entry?x=1",
        "https://user:pass@erpnext.example.test/api/resource/Journal%20Entry",
    ):
        with pytest.raises(WritebackNetworkError, match="endpoint_invalid"):
            erpnext_writeback_registration(credential_reference="vault://tenant-a/erpnext", endpoint=endpoint)


def test_erpnext_writeback_uses_token_auth_only_after_human_approval_and_feature_enablement() -> None:
    payload = build_erpnext_journal_entry_payload(_draft())
    registration = erpnext_writeback_registration(credential_reference="vault://tenant-a/erpnext").model_copy(
        update={"feature_enabled": True}
    )
    intent = _intent(payload.payload_digest)
    approved = approve_writeback(
        intent,
        policy=POLICY,
        actor_id="checker-1",
        approved_at=NOW,
        assurance="mfa",
        reason="independent close review",
    )
    dispatched = dispatch_writeback(approved, policy=POLICY)
    disabled_transport = _Transport(WritebackNetworkResponse(201, _provider_body(dispatched.idempotency_key)))
    disabled_executor = WritebackNetworkExecutor(
        disabled_transport,
        payload_resolver=_Payloads(payload.payload),
        secret_resolver=_Secrets(),
    )
    with pytest.raises(WritebackNetworkError, match="feature_disabled"):
        disabled_executor.dispatch(
            dispatched,
            registration=erpnext_writeback_registration(credential_reference="vault://tenant-a/erpnext"),
            policy=POLICY,
        )
    assert disabled_transport.calls == []

    transport = _Transport(WritebackNetworkResponse(201, _provider_body(dispatched.idempotency_key)))
    executor = WritebackNetworkExecutor(
        transport,
        payload_resolver=_Payloads(payload.payload),
        secret_resolver=_Secrets(),
    )

    receipt = executor.dispatch(dispatched, registration=registration, policy=POLICY)

    assert receipt.intent.acknowledgement is not None
    assert receipt.intent.acknowledgement.provider_reference == "JV-DRAFT-1"
    endpoint, headers, body = transport.calls[0]
    assert endpoint == ERP_NEXT_JOURNAL_ENTRY_ENDPOINT
    assert headers["Authorization"] == "token api-key:api-secret"
    assert headers["Idempotency-Key"] == dispatched.idempotency_key
    assert body == payload.payload
    assert b"api-key:api-secret" not in receipt.intent.model_dump_json().encode("utf-8")


def test_erpnext_writeback_contract_is_packaged() -> None:
    root = Path(__file__).resolve().parents[1]
    manifest = (root / "MANIFEST.in").read_text(encoding="utf-8")
    assert "include reconforge/connectors/erpnext_writeback.py" in manifest
    assert "include tests/test_connector_erpnext_writeback.py" in manifest
