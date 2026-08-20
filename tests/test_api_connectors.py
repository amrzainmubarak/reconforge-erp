import hashlib
import http.client
import http.server
import json
import socket
import ssl
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from reconforge.api import create_api_app
from reconforge.api.routes import connectors as routes
from reconforge.auth.service import LocalAuthService
from reconforge.connectors.erpnext_payment_writeback import (
    ERP_NEXT_PAYMENT_ENTRY_WRITEBACK_OPERATION,
    ErpNextPaymentEntryDraft,
    build_erpnext_payment_entry_payload,
    erpnext_payment_entry_writeback_registration,
)
from reconforge.connectors.erpnext_writeback import (
    ERP_NEXT_JOURNAL_ENTRY_OPERATION,
    ErpNextJournalEntryDraft,
    ErpNextJournalEntryLine,
    build_erpnext_journal_entry_payload,
    erpnext_writeback_registration,
)
from reconforge.connectors.writeback import WritebackPolicy, dispatch_writeback
from reconforge.connectors.writeback_network import (
    PinnedHttpsPostTransport,
    PinnedHttpsRecoveryTransport,
    WritebackNetworkExecutor,
    WritebackNetworkRegistration,
    WritebackNetworkResponse,
)
from reconforge.db import connect, run_migrations
from reconforge.infrastructure.sqlite_writeback import SQLiteWritebackIntentRepository
from tests.https_runtime import create_localhost_certificate
from tests.test_connector_writeback import _intent


def test_writeback_intent_api_is_authenticated_actor_bound_and_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "connector-api.db"
    run_migrations(db_path)
    connection = connect(db_path)
    admin = LocalAuthService(connection).init_admin(username="admin", password="Secret-123")
    LocalAuthService(connection).create_user(username="controller", password="Secret-123", role="controller")
    connection.close()
    client = TestClient(create_api_app(db_path))

    payload = _intent().model_copy(update={"requested_by": admin.id}).model_dump(mode="json")
    assert client.post("/api/v1/connectors/writeback/intents", json=payload).status_code == 401
    login = client.post("/api/v1/auth/login", json={"username": "admin", "password": "Secret-123"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    first = client.post("/api/v1/connectors/writeback/intents", json=payload, headers=headers)
    second = client.post("/api/v1/connectors/writeback/intents", json=payload, headers=headers)
    assert first.status_code == second.status_code == 200, (first.text, second.text)
    assert first.json()["version"] == second.json()["version"] == 1
    assert first.json()["network_dispatch"] == "disabled"
    assert first.json()["digest"] == second.json()["digest"]

    controller_login = client.post(
        "/api/v1/auth/login", json={"username": "controller", "password": "Secret-123"}
    )
    controller_headers = {"Authorization": f"Bearer {controller_login.json()['access_token']}"}
    controller_id = client.get("/api/v1/auth/me", headers=controller_headers).json()["id"]
    approval = client.post(
        f"/api/v1/connectors/writeback/intents/{payload['intent_id']}/approve",
        json={"assurance": "mfa", "reason": "independent review", "tenant_id": "tenant-a", "workspace_id": "workspace-a"},
        headers=controller_headers,
    )
    assert approval.status_code == 200, approval.text
    assert approval.json()["version"] == 2
    assert approval.json()["intent"]["status"] == "approved"
    assert approval.json()["network_dispatch"] == "disabled"
    repeated = client.post(
        f"/api/v1/connectors/writeback/intents/{payload['intent_id']}/approve",
        json={"assurance": "mfa", "reason": "repeat", "tenant_id": "tenant-a", "workspace_id": "workspace-a"},
        headers=controller_headers,
    )
    assert repeated.status_code == 409

    # A provider adapter would persist the dispatched state after approved
    # transport hand-off; the API only reconciles that already-persisted state.
    dispatch_connection = connect(db_path)
    try:
        dispatch_repository = SQLiteWritebackIntentRepository(dispatch_connection)
        approved = dispatch_repository.get(
            intent_id=payload["intent_id"], tenant_id="tenant-a", workspace_id="workspace-a"
        )
        assert approved is not None
        dispatched = dispatch_writeback(
            approved["intent"],
            policy=WritebackPolicy(
                connector_id="reference-rest-readonly",
                allowed_operations=frozenset({"payment.create"}),
                feature_enabled=True,
            ),
        )
        dispatch_repository.put(dispatched, expected_version=2)
    finally:
        dispatch_connection.close()
    acknowledgement = client.post(
        f"/api/v1/connectors/writeback/intents/{payload['intent_id']}/acknowledge",
        json={
            "tenant_id": "tenant-a",
            "workspace_id": "workspace-a",
            "provider_reference": "provider-ref-1",
            "response_digest": "b" * 64,
            "idempotency_key": payload["idempotency_key"],
            "accepted": True,
        },
        headers=controller_headers,
    )
    assert acknowledgement.status_code == 200, acknowledgement.text
    assert acknowledgement.json()["version"] == 4
    assert acknowledgement.json()["intent"]["status"] == "acknowledged"
    mismatch_ack = client.post(
        f"/api/v1/connectors/writeback/intents/{payload['intent_id']}/acknowledge",
        json={
            "tenant_id": "tenant-a",
            "workspace_id": "workspace-a",
            "provider_reference": "provider-ref-2",
            "response_digest": "c" * 64,
            "idempotency_key": "wrong-key",
            "accepted": True,
        },
        headers=controller_headers,
    )
    assert mismatch_ack.status_code == 409
    assert mismatch_ack.json()["error"]["code"] == "writeback_idempotency_mismatch"

    compensation = client.post(
        f"/api/v1/connectors/writeback/intents/{payload['intent_id']}/compensate",
        json={
            "tenant_id": "tenant-a",
            "workspace_id": "workspace-a",
            "reason": "provider reversal required",
            "expected_version": 4,
        },
        headers=controller_headers,
    )
    assert compensation.status_code == 200, compensation.text
    assert compensation.json()["version"] == 5
    assert compensation.json()["intent"]["status"] == "compensation_requested"
    assert compensation.json()["intent"]["compensation_requested_by"] == controller_id
    replay_compensation = client.post(
        f"/api/v1/connectors/writeback/intents/{payload['intent_id']}/compensate",
        json={
            "tenant_id": "tenant-a",
            "workspace_id": "workspace-a",
            "reason": "provider reversal required",
            "expected_version": 4,
        },
        headers=controller_headers,
    )
    assert replay_compensation.status_code == 200, replay_compensation.text
    assert replay_compensation.json()["version"] == 5
    assert replay_compensation.json()["digest"] == compensation.json()["digest"]
    denied_compensation = client.post(
        f"/api/v1/connectors/writeback/intents/{payload['intent_id']}/compensate",
        json={
            "tenant_id": "tenant-a",
            "workspace_id": "workspace-a",
            "reason": "different actor attempt",
            "expected_version": 5,
        },
        headers=headers,
    )
    assert denied_compensation.status_code == 409
    assert denied_compensation.json()["error"]["code"] == "writeback_compensation_conflict"

    mismatched = {**payload, "requested_by": "different-actor"}
    denied = client.post("/api/v1/connectors/writeback/intents", json=mismatched, headers=headers)
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "writeback_actor_mismatch"

    check = connect(db_path)
    try:
        assert check.execute("SELECT COUNT(*) FROM connector_writeback_intents").fetchone()[0] == 5
    finally:
        check.close()


def test_writeback_api_uses_postgres_server_boundary_when_enabled(tmp_path: Path, monkeypatch: Any) -> None:
    db_path = tmp_path / "writeback-server-boundary.db"
    run_migrations(db_path)
    connection = connect(db_path)
    LocalAuthService(connection).init_admin(username="admin", password="Secret-123")
    connection.close()
    client = TestClient(create_api_app(db_path))
    login = client.post("/api/v1/auth/login", json={"username": "admin", "password": "Secret-123"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    actor_id = client.get("/api/v1/auth/me", headers=headers).json()["id"]

    calls: list[str] = []

    class Repository:
        def __init__(self) -> None:
            self.current = None
            self.version = 0

        def put(self, intent: object, *, expected_version: int | None = None) -> object:
            del expected_version
            self.current = intent
            self.version += 1
            return intent

        def get(self, **_: object) -> dict[str, object] | None:
            if self.current is None:
                return None
            return {"intent": self.current, "version": self.version}

    repository = Repository()

    def execute(_request: object, operation: object) -> object:
        calls.append("postgres")
        return operation(repository, "tenant-a", "workspace-a")  # type: ignore[operator]

    monkeypatch.setattr(routes, "server_writeback_enabled", lambda _request: True)
    monkeypatch.setattr(routes, "_require_server_scope", lambda _request, _tenant, _workspace: ("tenant-a", "workspace-a"))
    monkeypatch.setattr(routes, "execute_postgres_writeback", execute)

    payload = _intent(requested_by=actor_id).model_dump(mode="json")
    proposed = client.post("/api/v1/connectors/writeback/intents", headers=headers, json=payload)
    assert proposed.status_code == 200, proposed.text
    assert proposed.json()["source"]["server_mode"] is True
    assert calls == ["postgres"]


def test_writeback_dispatch_is_opt_in_server_scoped_and_idempotent(tmp_path: Path, monkeypatch: Any) -> None:
    db_path = tmp_path / "writeback-dispatch.db"
    run_migrations(db_path)
    connection = connect(db_path)
    admin = LocalAuthService(connection).init_admin(username="admin", password="Secret-123")
    LocalAuthService(connection).create_user(username="controller", password="Secret-123", role="controller")
    connection.close()
    app = create_api_app(db_path)
    client = TestClient(app)
    admin_login = client.post("/api/v1/auth/login", json={"username": "admin", "password": "Secret-123"})
    admin_headers = {"Authorization": f"Bearer {admin_login.json()['access_token']}"}
    controller_login = client.post(
        "/api/v1/auth/login", json={"username": "controller", "password": "Secret-123"}
    )
    controller_headers = {"Authorization": f"Bearer {controller_login.json()['access_token']}"}

    payload_bytes = b'{"amount":"10.00","currency":"USD","reference":"payment-1"}'
    compensation_payload_bytes = b'{"amount":"-10.00","currency":"USD","reference":"payment-1-reversal"}'
    connector_id = "reference-rest-writeback"
    payload = _intent(
        connector_id=connector_id,
        operation="payment.create",
        payload_digest=hashlib.sha256(payload_bytes).hexdigest(),
        requested_by=admin.id,
    ).model_dump(mode="json")
    proposed = client.post("/api/v1/connectors/writeback/intents", json=payload, headers=admin_headers)
    assert proposed.status_code == 200, proposed.text
    approved = client.post(
        f"/api/v1/connectors/writeback/intents/{payload['intent_id']}/approve",
        json={
            "assurance": "mfa",
            "reason": "independent provider review",
            "tenant_id": "tenant-a",
            "workspace_id": "workspace-a",
        },
        headers=controller_headers,
    )
    assert approved.status_code == 200, approved.text

    disabled = client.post(
        f"/api/v1/connectors/writeback/intents/{payload['intent_id']}/dispatch",
        json={"tenant_id": "tenant-a", "workspace_id": "workspace-a", "expected_version": 2},
        headers=controller_headers,
    )
    assert disabled.status_code == 503
    assert disabled.json()["error"]["code"] == "writeback_network_requires_server_profile"

    @dataclass
    class Transport:
        calls: int = 0

        def post(
            self,
            endpoint: str,
            *,
            headers: dict[str, str],
            body: bytes,
            timeout_seconds: int,
            maximum_response_bytes: int,
        ) -> WritebackNetworkResponse:
            del endpoint, body, timeout_seconds, maximum_response_bytes
            self.calls += 1
            idempotency_key = headers["Idempotency-Key"]
            response = {
                "accepted": True,
                "idempotency_key": idempotency_key,
                "provider_reference": "provider-compensation-1"
                if idempotency_key.endswith(":compensation")
                else "provider-1",
            }
            response_digest = hashlib.sha256(
                json.dumps(response, sort_keys=True, separators=(",", ":")).encode("ascii")
            ).hexdigest()
            return WritebackNetworkResponse(
                status=200,
                body=json.dumps({**response, "response_digest": response_digest}).encode("ascii"),
            )

    class Payloads:
        def resolve(self, intent: object) -> bytes:
            del intent
            return payload_bytes

    class Secrets:
        def resolve(self, reference: str) -> bytes:
            assert reference == "vault://tenant-a/writeback-token"
            return b"synthetic-writeback-token-123"

    transport = Transport()
    app.state.writeback_network_executor = WritebackNetworkExecutor(
        transport,
        payload_resolver=Payloads(),
        secret_resolver=Secrets(),
    )
    registration = WritebackNetworkRegistration.model_validate(
        {
            "registration_schema": "writeback-network-registration-v1",
            "connector_id": connector_id,
            "version": "1.0.0",
            "endpoint": "https://api.example.test/v1/writeback",
            "egress_destinations": ("https://api.example.test/v1/writeback",),
            "credential_reference": "vault://tenant-a/writeback-token",
            "allowed_operations": frozenset({"payment.create"}),
            "allowed_compensation_operations": frozenset({"payment.create"}),
            "feature_enabled": True,
            "synthetic_sandbox": True,
        }
    )
    app.state.writeback_network_registrations = {connector_id: registration}

    monkeypatch.setattr(routes, "server_writeback_enabled", lambda _request: True)
    monkeypatch.setattr(routes, "_require_server_scope", lambda _request, _tenant, _workspace: ("tenant-a", "workspace-a"))

    def execute(_request: object, operation: object) -> object:
        scoped = connect(db_path)
        try:
            return operation(SQLiteWritebackIntentRepository(scoped), "tenant-a", "workspace-a")  # type: ignore[operator]
        finally:
            scoped.close()

    monkeypatch.setattr(routes, "execute_postgres_writeback", execute)
    original_permission_check = routes.enforce_server_scoped_permission
    permission_calls = 0

    def revoke_before_provider(*args: object, **kwargs: object) -> None:
        nonlocal permission_calls
        permission_calls += 1
        if permission_calls == 2:
            raise routes.APIError(
                status_code=403,
                code="permission_revoked_before_writeback",
                message="Write-back dispatch permission was revoked before provider I/O.",
            )
        original_permission_check(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(routes, "enforce_server_scoped_permission", revoke_before_provider)
    denied_before_provider = client.post(
        f"/api/v1/connectors/writeback/intents/{payload['intent_id']}/dispatch",
        json={"tenant_id": "tenant-a", "workspace_id": "workspace-a", "expected_version": 2},
        headers=controller_headers,
    )
    assert denied_before_provider.status_code == 403, denied_before_provider.text
    assert denied_before_provider.json()["error"]["code"] == "permission_revoked_before_writeback"
    assert transport.calls == 0

    monkeypatch.setattr(routes, "enforce_server_scoped_permission", original_permission_check)
    dispatched = client.post(
        f"/api/v1/connectors/writeback/intents/{payload['intent_id']}/dispatch",
        json={"tenant_id": "tenant-a", "workspace_id": "workspace-a", "expected_version": 3},
        headers=controller_headers,
    )
    assert dispatched.status_code == 200, dispatched.text
    assert dispatched.json()["intent"]["status"] == "acknowledged"
    assert dispatched.json()["network_dispatch"] == "acknowledged"
    assert dispatched.json()["attempts"] == 1
    assert transport.calls == 1

    replay = client.post(
        f"/api/v1/connectors/writeback/intents/{payload['intent_id']}/dispatch",
        json={"tenant_id": "tenant-a", "workspace_id": "workspace-a", "expected_version": 4},
        headers=controller_headers,
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["network_dispatch"] == "already_acknowledged"
    assert transport.calls == 1

    requested_compensation = client.post(
        f"/api/v1/connectors/writeback/intents/{payload['intent_id']}/compensate",
        json={
            "tenant_id": "tenant-a",
            "workspace_id": "workspace-a",
            "reason": "provider reversal required",
            "expected_version": 4,
        },
        headers=controller_headers,
    )
    assert requested_compensation.status_code == 200, requested_compensation.text
    assert requested_compensation.json()["intent"]["status"] == "compensation_requested"
    assert requested_compensation.json()["version"] == 5

    class CompensationPayloads:
        def resolve(self, intent: object) -> bytes:
            del intent
            return compensation_payload_bytes

    missing_resolver = client.post(
        f"/api/v1/connectors/writeback/intents/{payload['intent_id']}/compensate/dispatch",
        json={
            "tenant_id": "tenant-a",
            "workspace_id": "workspace-a",
            "expected_version": 5,
            "payload_digest": hashlib.sha256(compensation_payload_bytes).hexdigest(),
        },
        headers=controller_headers,
    )
    assert missing_resolver.status_code == 503
    assert missing_resolver.json()["error"]["code"] == "writeback_compensation_payload_not_configured"
    assert transport.calls == 1
    app.state.writeback_compensation_payload_resolver = CompensationPayloads()
    compensated = client.post(
        f"/api/v1/connectors/writeback/intents/{payload['intent_id']}/compensate/dispatch",
        json={
            "tenant_id": "tenant-a",
            "workspace_id": "workspace-a",
            "expected_version": 5,
            "payload_digest": hashlib.sha256(compensation_payload_bytes).hexdigest(),
        },
        headers=controller_headers,
    )
    assert compensated.status_code == 200, compensated.text
    assert compensated.json()["intent"]["status"] == "compensated"
    assert compensated.json()["version"] == 6
    assert compensated.json()["network_dispatch"] == "compensated"
    assert compensated.json()["attempts"] == 1
    assert transport.calls == 2
    compensated_replay = client.post(
        f"/api/v1/connectors/writeback/intents/{payload['intent_id']}/compensate/dispatch",
        json={
            "tenant_id": "tenant-a",
            "workspace_id": "workspace-a",
            "expected_version": 6,
            "payload_digest": hashlib.sha256(compensation_payload_bytes).hexdigest(),
        },
        headers=controller_headers,
    )
    assert compensated_replay.status_code == 200, compensated_replay.text
    assert compensated_replay.json()["network_dispatch"] == "already_compensated"
    assert transport.calls == 2


def test_erpnext_writeback_api_dispatches_balanced_payload_and_replays_without_provider_call(
    tmp_path: Path, monkeypatch: Any
) -> None:
    db_path = tmp_path / "erpnext-writeback-api.db"
    run_migrations(db_path)
    connection = connect(db_path)
    admin = LocalAuthService(connection).init_admin(username="admin", password="Secret-123")
    LocalAuthService(connection).create_user(username="controller", password="Secret-123", role="controller")
    connection.close()
    app = create_api_app(db_path)
    client = TestClient(app)
    admin_login = client.post("/api/v1/auth/login", json={"username": "admin", "password": "Secret-123"})
    admin_headers = {"Authorization": f"Bearer {admin_login.json()['access_token']}"}
    controller_login = client.post(
        "/api/v1/auth/login", json={"username": "controller", "password": "Secret-123"}
    )
    controller_headers = {"Authorization": f"Bearer {controller_login.json()['access_token']}"}

    draft = ErpNextJournalEntryDraft(
        company="Acme",
        posting_date="2026-08-11",
        accounts=(
            ErpNextJournalEntryLine(account="1100 - Cash", debit="42.00", credit="0.00", account_currency="USD"),
            ErpNextJournalEntryLine(account="4000 - Revenue", debit="0.00", credit="42.00", account_currency="USD"),
        ),
        user_remark="API synthetic write-back",
    )
    payload = build_erpnext_journal_entry_payload(draft)
    connector_id = "erpnext-journal-entry-writeback"
    intent_payload = _intent(
        intent_id="erpnext-api-writeback-1",
        tenant_id="tenant-a",
        workspace_id="workspace-a",
        connector_id=connector_id,
        operation=ERP_NEXT_JOURNAL_ENTRY_OPERATION,
        payload_digest=payload.payload_digest,
        idempotency_key="erpnext-api-writeback-1",
        requested_by=admin.id,
    ).model_dump(mode="json")

    class Transport:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, str], bytes]] = []

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
            fields = {
                "accepted": True,
                "idempotency_key": headers["Idempotency-Key"],
                "provider_reference": "ERPNext-API-DRAFT-1",
            }
            response_digest = hashlib.sha256(
                json.dumps(fields, sort_keys=True, separators=(",", ":")).encode("ascii")
            ).hexdigest()
            return WritebackNetworkResponse(
                status=201,
                body=json.dumps({**fields, "response_digest": response_digest}).encode("ascii"),
            )

    class Payloads:
        def resolve(self, _intent: object) -> bytes:
            return payload.payload

    class Secrets:
        def resolve(self, reference: str) -> bytes:
            assert reference == "vault://tenant-a/erpnext"
            return b"synthetic-erpnext-api-token"

    transport = Transport()
    app.state.writeback_network_executor = WritebackNetworkExecutor(
        transport,
        payload_resolver=Payloads(),
        secret_resolver=Secrets(),
    )
    registration = erpnext_writeback_registration(
        credential_reference="vault://tenant-a/erpnext"
    ).model_copy(update={"feature_enabled": True})
    app.state.writeback_network_registrations = {connector_id: registration}

    monkeypatch.setattr(routes, "server_writeback_enabled", lambda _request: True)
    monkeypatch.setattr(routes, "_require_server_scope", lambda _request, _tenant, _workspace: ("tenant-a", "workspace-a"))

    def execute(_request: object, operation: object) -> object:
        scoped = connect(db_path)
        try:
            return operation(SQLiteWritebackIntentRepository(scoped), "tenant-a", "workspace-a")  # type: ignore[operator]
        finally:
            scoped.close()

    monkeypatch.setattr(routes, "execute_postgres_writeback", execute)

    proposed = client.post(
        "/api/v1/connectors/writeback/intents", json=intent_payload, headers=admin_headers
    )
    assert proposed.status_code == 200, proposed.text
    approved = client.post(
        f"/api/v1/connectors/writeback/intents/{intent_payload['intent_id']}/approve",
        json={
            "assurance": "mfa",
            "reason": "ERPNext draft independently reviewed",
            "tenant_id": "tenant-a",
            "workspace_id": "workspace-a",
        },
        headers=controller_headers,
    )
    assert approved.status_code == 200, approved.text
    dispatched = client.post(
        f"/api/v1/connectors/writeback/intents/{intent_payload['intent_id']}/dispatch",
        json={"tenant_id": "tenant-a", "workspace_id": "workspace-a", "expected_version": 2},
        headers=controller_headers,
    )
    assert dispatched.status_code == 200, dispatched.text
    assert dispatched.json()["intent"]["status"] == "acknowledged"
    assert dispatched.json()["network_dispatch"] == "acknowledged"
    assert dispatched.json()["attempts"] == 1
    assert len(transport.calls) == 1
    endpoint, headers, body = transport.calls[0]
    assert endpoint.endswith("/api/resource/Journal%20Entry")
    assert headers["Authorization"] == "token synthetic-erpnext-api-token"
    assert headers["X-ReconForge-Operation"] == ERP_NEXT_JOURNAL_ENTRY_OPERATION
    assert headers["Idempotency-Key"] == intent_payload["idempotency_key"]
    assert body == payload.payload
    assert b"synthetic-erpnext-api-token" not in dispatched.content

    replay = client.post(
        f"/api/v1/connectors/writeback/intents/{intent_payload['intent_id']}/dispatch",
        json={"tenant_id": "tenant-a", "workspace_id": "workspace-a", "expected_version": 4},
        headers=controller_headers,
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["network_dispatch"] == "already_acknowledged"
    assert len(transport.calls) == 1


def test_erpnext_payment_writeback_api_dispatches_one_sided_payload_and_replays_without_provider_call(
    tmp_path: Path, monkeypatch: Any
) -> None:
    db_path = tmp_path / "erpnext-payment-writeback-api.db"
    run_migrations(db_path)
    connection = connect(db_path)
    admin = LocalAuthService(connection).init_admin(username="admin", password="Secret-123")
    LocalAuthService(connection).create_user(username="controller", password="Secret-123", role="controller")
    connection.close()
    app = create_api_app(db_path)
    client = TestClient(app)
    admin_login = client.post("/api/v1/auth/login", json={"username": "admin", "password": "Secret-123"})
    admin_headers = {"Authorization": f"Bearer {admin_login.json()['access_token']}"}
    controller_login = client.post(
        "/api/v1/auth/login", json={"username": "controller", "password": "Secret-123"}
    )
    controller_headers = {"Authorization": f"Bearer {controller_login.json()['access_token']}"}

    draft = ErpNextPaymentEntryDraft(
        company="Acme",
        posting_date="2026-08-11",
        paid_from="1100 - Cash",
        paid_to="2100 - Supplier Payables",
        paid_amount="42.00",
        received_amount="0.00",
        paid_from_account_currency="USD",
        paid_to_account_currency="USD",
        party_type="Supplier",
        party="SUP-001",
        reference_no="PAY-API-001",
        remarks="API synthetic payment draft",
    )
    payload = build_erpnext_payment_entry_payload(draft)
    connector_id = "erpnext-payment-entry-writeback"
    intent_payload = _intent(
        intent_id="erpnext-payment-api-writeback-1",
        tenant_id="tenant-a",
        workspace_id="workspace-a",
        connector_id=connector_id,
        operation=ERP_NEXT_PAYMENT_ENTRY_WRITEBACK_OPERATION,
        payload_digest=payload.payload_digest,
        idempotency_key="erpnext-payment-api-writeback-1",
        requested_by=admin.id,
    ).model_dump(mode="json")

    class Transport:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, str], bytes]] = []

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
            fields = {
                "accepted": True,
                "idempotency_key": headers["Idempotency-Key"],
                "provider_reference": "ERPNext-PAYMENT-API-DRAFT-1",
            }
            response_digest = hashlib.sha256(
                json.dumps(fields, sort_keys=True, separators=(",", ":")).encode("ascii")
            ).hexdigest()
            return WritebackNetworkResponse(
                status=201,
                body=json.dumps({**fields, "response_digest": response_digest}).encode("ascii"),
            )

    class Payloads:
        def resolve(self, _intent: object) -> bytes:
            return payload.payload

    class Secrets:
        def resolve(self, reference: str) -> bytes:
            assert reference == "vault://tenant-a/erpnext"
            return b"synthetic-erpnext-payment-api-token"

    transport = Transport()
    app.state.writeback_network_executor = WritebackNetworkExecutor(
        transport,
        payload_resolver=Payloads(),
        secret_resolver=Secrets(),
    )
    registration = erpnext_payment_entry_writeback_registration(
        credential_reference="vault://tenant-a/erpnext"
    ).model_copy(update={"feature_enabled": True})
    app.state.writeback_network_registrations = {connector_id: registration}

    monkeypatch.setattr(routes, "server_writeback_enabled", lambda _request: True)
    monkeypatch.setattr(routes, "_require_server_scope", lambda _request, _tenant, _workspace: ("tenant-a", "workspace-a"))

    def execute(_request: object, operation: object) -> object:
        scoped = connect(db_path)
        try:
            return operation(SQLiteWritebackIntentRepository(scoped), "tenant-a", "workspace-a")  # type: ignore[operator]
        finally:
            scoped.close()

    monkeypatch.setattr(routes, "execute_postgres_writeback", execute)

    proposed = client.post(
        "/api/v1/connectors/writeback/intents", json=intent_payload, headers=admin_headers
    )
    assert proposed.status_code == 200, proposed.text
    approved = client.post(
        f"/api/v1/connectors/writeback/intents/{intent_payload['intent_id']}/approve",
        json={
            "assurance": "mfa",
            "reason": "ERPNext payment draft independently reviewed",
            "tenant_id": "tenant-a",
            "workspace_id": "workspace-a",
        },
        headers=controller_headers,
    )
    assert approved.status_code == 200, approved.text
    dispatched = client.post(
        f"/api/v1/connectors/writeback/intents/{intent_payload['intent_id']}/dispatch",
        json={"tenant_id": "tenant-a", "workspace_id": "workspace-a", "expected_version": 2},
        headers=controller_headers,
    )
    assert dispatched.status_code == 200, dispatched.text
    assert dispatched.json()["intent"]["status"] == "acknowledged"
    assert dispatched.json()["network_dispatch"] == "acknowledged"
    assert dispatched.json()["attempts"] == 1
    assert len(transport.calls) == 1
    endpoint, headers, body = transport.calls[0]
    assert endpoint.endswith("/api/resource/Payment%20Entry")
    assert headers["Authorization"] == "token synthetic-erpnext-payment-api-token"
    assert headers["X-ReconForge-Operation"] == ERP_NEXT_PAYMENT_ENTRY_WRITEBACK_OPERATION
    assert headers["Idempotency-Key"] == intent_payload["idempotency_key"]
    assert json.loads(body)["paid_amount"] == "42.00"
    assert json.loads(body)["received_amount"] == "0.00"
    assert json.loads(body)["docstatus"] == 0
    assert body == payload.payload
    assert b"synthetic-erpnext-payment-api-token" not in dispatched.content

    replay = client.post(
        f"/api/v1/connectors/writeback/intents/{intent_payload['intent_id']}/dispatch",
        json={"tenant_id": "tenant-a", "workspace_id": "workspace-a", "expected_version": 4},
        headers=controller_headers,
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["network_dispatch"] == "already_acknowledged"
    assert len(transport.calls) == 1


def test_writeback_recovery_api_reads_provider_status_without_post(tmp_path: Path, monkeypatch: Any) -> None:
    db_path = tmp_path / "writeback-recovery.db"
    run_migrations(db_path)
    connection = connect(db_path)
    admin = LocalAuthService(connection).init_admin(username="admin", password="Secret-123")
    LocalAuthService(connection).create_user(username="controller", password="Secret-123", role="controller")
    connection.close()
    app = create_api_app(db_path)
    client = TestClient(app)
    admin_login = client.post("/api/v1/auth/login", json={"username": "admin", "password": "Secret-123"})
    admin_headers = {"Authorization": f"Bearer {admin_login.json()['access_token']}"}
    controller_login = client.post(
        "/api/v1/auth/login", json={"username": "controller", "password": "Secret-123"}
    )
    controller_headers = {"Authorization": f"Bearer {controller_login.json()['access_token']}"}
    payload = _intent(requested_by=admin.id).model_dump(mode="json")
    proposed = client.post("/api/v1/connectors/writeback/intents", json=payload, headers=admin_headers)
    assert proposed.status_code == 200, proposed.text
    approved = client.post(
        f"/api/v1/connectors/writeback/intents/{payload['intent_id']}/approve",
        json={
            "assurance": "mfa",
            "reason": "independent provider review",
            "tenant_id": "tenant-a",
            "workspace_id": "workspace-a",
        },
        headers=controller_headers,
    )
    assert approved.status_code == 200, approved.text

    staged_connection = connect(db_path)
    try:
        repository = SQLiteWritebackIntentRepository(staged_connection)
        current = repository.get(intent_id=payload["intent_id"], tenant_id="tenant-a", workspace_id="workspace-a")
        assert current is not None
        staged = dispatch_writeback(
            current["intent"],
            policy=WritebackPolicy(
                connector_id="reference-rest-readonly",
                allowed_operations=frozenset({"payment.create"}),
                feature_enabled=True,
            ),
        )
        repository.put(staged, expected_version=2)
    finally:
        staged_connection.close()

    @dataclass
    class PostTransport:
        calls: int = 0

        def post(self, *args: object, **kwargs: object) -> WritebackNetworkResponse:
            del args, kwargs
            self.calls += 1
            raise AssertionError("recovery must not call POST")

    @dataclass
    class RecoveryTransport:
        calls: int = 0

        def recover(
            self,
            endpoint: str,
            *,
            headers: dict[str, str],
            idempotency_key: str,
            timeout_seconds: int,
            maximum_response_bytes: int,
        ) -> WritebackNetworkResponse:
            del endpoint, headers, timeout_seconds, maximum_response_bytes
            self.calls += 1
            response = {
                "accepted": True,
                "idempotency_key": idempotency_key,
                "provider_reference": "provider-recovered-1",
            }
            digest = hashlib.sha256(json.dumps(response, sort_keys=True, separators=(",", ":")).encode("ascii")).hexdigest()
            return WritebackNetworkResponse(status=200, body=json.dumps({**response, "response_digest": digest}).encode("ascii"))

    post_transport = PostTransport()
    recovery_transport = RecoveryTransport()

    class Payloads:
        def resolve(self, intent: object) -> bytes:
            raise AssertionError("recovery must not resolve a payload")

    class Secrets:
        def resolve(self, reference: str) -> bytes:
            assert reference == "vault://tenant-a/writeback-token"
            return b"synthetic-writeback-token-123"

    app.state.writeback_network_executor = WritebackNetworkExecutor(
        post_transport,
        payload_resolver=Payloads(),
        secret_resolver=Secrets(),
    )
    app.state.writeback_recovery_transport = recovery_transport
    app.state.writeback_network_registrations = {
        "reference-rest-readonly": WritebackNetworkRegistration.model_validate(
            {
                "registration_schema": "writeback-network-registration-v1",
                "connector_id": "reference-rest-readonly",
                "version": "1.0.0",
                "endpoint": "https://api.example.test/v1/writeback",
                "egress_destinations": ("https://api.example.test/v1/writeback",),
                "credential_reference": "vault://tenant-a/writeback-token",
                "allowed_operations": frozenset({"payment.create"}),
                "feature_enabled": True,
            }
        )
    }
    monkeypatch.setattr(routes, "server_writeback_enabled", lambda _request: True)
    monkeypatch.setattr(routes, "_require_server_scope", lambda _request, _tenant, _workspace: ("tenant-a", "workspace-a"))

    def execute(_request: object, operation: object) -> object:
        scoped = connect(db_path)
        try:
            return operation(SQLiteWritebackIntentRepository(scoped), "tenant-a", "workspace-a")  # type: ignore[operator]
        finally:
            scoped.close()

    monkeypatch.setattr(routes, "execute_postgres_writeback", execute)
    original_permission_check = routes.enforce_server_scoped_permission
    permission_calls = 0

    def revoke_before_recovery(*args: object, **kwargs: object) -> None:
        nonlocal permission_calls
        permission_calls += 1
        if permission_calls == 2:
            raise routes.APIError(
                status_code=403,
                code="permission_revoked_before_recovery",
                message="Write-back reconciliation permission was revoked before provider status I/O.",
            )
        original_permission_check(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(routes, "enforce_server_scoped_permission", revoke_before_recovery)
    denied_before_recovery = client.post(
        f"/api/v1/connectors/writeback/intents/{payload['intent_id']}/recover",
        json={"tenant_id": "tenant-a", "workspace_id": "workspace-a", "expected_version": 3},
        headers=controller_headers,
    )
    assert denied_before_recovery.status_code == 403, denied_before_recovery.text
    assert denied_before_recovery.json()["error"]["code"] == "permission_revoked_before_recovery"
    assert recovery_transport.calls == 0
    check = connect(db_path)
    try:
        current = SQLiteWritebackIntentRepository(check).get(
            intent_id=payload["intent_id"], tenant_id="tenant-a", workspace_id="workspace-a"
        )
        assert current is not None
        assert current["intent"].status.value == "dispatched"
        assert current["version"] == 3
    finally:
        check.close()

    monkeypatch.setattr(routes, "enforce_server_scoped_permission", original_permission_check)
    recovered = client.post(
        f"/api/v1/connectors/writeback/intents/{payload['intent_id']}/recover",
        json={"tenant_id": "tenant-a", "workspace_id": "workspace-a", "expected_version": 3},
        headers=controller_headers,
    )
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["intent"]["status"] == "acknowledged"
    assert recovered.json()["network_dispatch"] == "recovered"
    assert recovered.json()["version"] == 4
    assert recovery_transport.calls == 1
    assert post_transport.calls == 0
    replay = client.post(
        f"/api/v1/connectors/writeback/intents/{payload['intent_id']}/recover",
        json={"tenant_id": "tenant-a", "workspace_id": "workspace-a", "expected_version": 3},
        headers=controller_headers,
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["network_dispatch"] == "already_acknowledged"
    assert recovery_transport.calls == 1
    assert post_transport.calls == 0


def test_writeback_recovery_api_uses_real_pinned_https_status_lookup_without_post(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """Prove API recovery crosses the real TLS transport and replay fence.

    The provider is a disposable local HTTPS status endpoint.  The production
    resolver still receives a public test address, while the injected factory
    pins the socket to the loopback listener.  A recovery must perform one GET
    for the original idempotency key, persist the acknowledgement, and replay
    without either a second GET or any POST mutation.
    """

    db_path = tmp_path / "writeback-api-tls-recovery.db"
    run_migrations(db_path)
    connection = connect(db_path)
    admin = LocalAuthService(connection).init_admin(username="admin", password="Secret-123")
    LocalAuthService(connection).create_user(username="controller", password="Secret-123", role="controller")
    connection.close()
    app = create_api_app(db_path)
    client = TestClient(app)
    admin_login = client.post("/api/v1/auth/login", json={"username": "admin", "password": "Secret-123"})
    admin_headers = {"Authorization": f"Bearer {admin_login.json()['access_token']}"}
    controller_login = client.post(
        "/api/v1/auth/login", json={"username": "controller", "password": "Secret-123"}
    )
    controller_headers = {"Authorization": f"Bearer {controller_login.json()['access_token']}"}
    intent_payload = _intent(
        intent_id="writeback-api-tls-recovery-1",
        idempotency_key="writeback-api-tls-recovery-1",
        requested_by=admin.id,
    ).model_dump(mode="json")
    proposed = client.post(
        "/api/v1/connectors/writeback/intents", json=intent_payload, headers=admin_headers
    )
    assert proposed.status_code == 200, proposed.text
    approved = client.post(
        f"/api/v1/connectors/writeback/intents/{intent_payload['intent_id']}/approve",
        json={
            "assurance": "mfa",
            "reason": "independent provider status recovery review",
            "tenant_id": "tenant-a",
            "workspace_id": "workspace-a",
        },
        headers=controller_headers,
    )
    assert approved.status_code == 200, approved.text

    staged_connection = connect(db_path)
    try:
        repository = SQLiteWritebackIntentRepository(staged_connection)
        current = repository.get(
            intent_id=intent_payload["intent_id"], tenant_id="tenant-a", workspace_id="workspace-a"
        )
        assert current is not None
        staged = dispatch_writeback(current["intent"], policy=WritebackPolicy(
            connector_id="reference-rest-readonly",
            allowed_operations=frozenset({"payment.create"}),
            feature_enabled=True,
        ))
        repository.put(staged, expected_version=2)
    finally:
        staged_connection.close()

    certificate, key = create_localhost_certificate(tmp_path)
    get_requests: list[dict[str, str]] = []
    post_requests: list[bytes] = []

    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:  # noqa: N802 - stdlib handler contract
            get_requests.append({"path": self.path, **dict(self.headers)})
            fields = {
                "accepted": True,
                "idempotency_key": self.headers.get("Idempotency-Key", ""),
                "provider_reference": "provider-api-tls-recovered-1",
            }
            response_digest = hashlib.sha256(
                json.dumps(fields, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("ascii")
            ).hexdigest()
            response_body = json.dumps(
                {**fields, "response_digest": response_digest},
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("ascii")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response_body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(response_body)

        def do_POST(self) -> None:  # noqa: N802 - mutation must never occur
            post_requests.append(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
            self.send_response(500)
            self.send_header("Content-Length", "0")
            self.send_header("Connection", "close")
            self.end_headers()

        def log_message(self, _format: str, *_args: object) -> None:
            return

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.load_cert_chain(certificate, key)
    server.socket = server_context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    class LocalPinnedConnection(http.client.HTTPSConnection):
        def __init__(self, host: str, port: int, timeout: int, context: ssl.SSLContext) -> None:
            super().__init__(host=host, port=port, timeout=timeout, context=context)
            self._create_connection = self._connect_local

        def _connect_local(
            self,
            _address: tuple[str, int],
            timeout: float | None = None,
            source_address: tuple[str, int] | None = None,
        ) -> socket.socket:
            return socket.create_connection(("127.0.0.1", self.port), timeout, source_address)

    def factory(
        host: str, port: int, address: str, timeout: int, context: ssl.SSLContext
    ) -> http.client.HTTPSConnection:
        del address
        return LocalPinnedConnection(host, port, timeout, context)

    endpoint = f"https://localhost:{server.server_port}/v1/writeback"
    recovery_endpoint = f"https://localhost:{server.server_port}/v1/status"
    client_context = ssl.create_default_context(cafile=str(certificate))
    registration = WritebackNetworkRegistration.model_validate(
        {
            "registration_schema": "writeback-network-registration-v1",
            "connector_id": "reference-rest-readonly",
            "version": "1.0.0",
            "endpoint": endpoint,
            "recovery_endpoint": recovery_endpoint,
            "egress_destinations": tuple(sorted((endpoint, recovery_endpoint))),
            "credential_reference": "vault://tenant-a/writeback-token",
            "allowed_operations": frozenset({"payment.create"}),
            "feature_enabled": True,
        }
    )

    class Payloads:
        def resolve(self, _intent: object) -> bytes:
            raise AssertionError("recovery must not resolve or POST a payload")

    class Secrets:
        def resolve(self, reference: str) -> bytes:
            assert reference == "vault://tenant-a/writeback-token"
            return b"synthetic-writeback-token-123"

    post_transport = PinnedHttpsPostTransport(
        resolver=lambda _host, _port: ("93.184.216.34",),
        connection_factory=factory,
        tls_context=client_context,
    )
    recovery_transport = PinnedHttpsRecoveryTransport(
        resolver=lambda _host, _port: ("93.184.216.34",),
        connection_factory=factory,
        tls_context=client_context,
    )
    app.state.writeback_network_executor = WritebackNetworkExecutor(
        post_transport,
        payload_resolver=Payloads(),
        secret_resolver=Secrets(),
    )
    app.state.writeback_recovery_transport = recovery_transport
    app.state.writeback_network_registrations = {"reference-rest-readonly": registration}
    monkeypatch.setattr(routes, "server_writeback_enabled", lambda _request: True)
    monkeypatch.setattr(routes, "_require_server_scope", lambda _request, _tenant, _workspace: ("tenant-a", "workspace-a"))

    def execute(_request: object, operation: object) -> object:
        scoped = connect(db_path)
        try:
            return operation(SQLiteWritebackIntentRepository(scoped), "tenant-a", "workspace-a")  # type: ignore[operator]
        finally:
            scoped.close()

    monkeypatch.setattr(routes, "execute_postgres_writeback", execute)
    try:
        recovered = client.post(
            f"/api/v1/connectors/writeback/intents/{intent_payload['intent_id']}/recover",
            json={"tenant_id": "tenant-a", "workspace_id": "workspace-a", "expected_version": 3},
            headers=controller_headers,
        )
        assert recovered.status_code == 200, recovered.text
        assert recovered.json()["intent"]["status"] == "acknowledged"
        assert recovered.json()["network_dispatch"] == "recovered"
        assert recovered.json()["attempts"] == 1
        assert recovered.json()["version"] == 4
        assert len(get_requests) == 1
        assert get_requests[0]["path"] == "/v1/status"
        assert get_requests[0]["Idempotency-Key"] == intent_payload["idempotency_key"]
        assert get_requests[0]["X-ReconForge-Recovery"] == "idempotency-status-v1"
        assert get_requests[0]["Authorization"] == "Bearer synthetic-writeback-token-123"
        assert post_requests == []

        replay = client.post(
            f"/api/v1/connectors/writeback/intents/{intent_payload['intent_id']}/recover",
            json={"tenant_id": "tenant-a", "workspace_id": "workspace-a", "expected_version": 3},
            headers=controller_headers,
        )
        assert replay.status_code == 200, replay.text
        assert replay.json()["network_dispatch"] == "already_acknowledged"
        assert len(get_requests) == 1
        assert post_requests == []
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
