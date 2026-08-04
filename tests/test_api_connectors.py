import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from reconforge.api import create_api_app
from reconforge.api.routes import connectors as routes
from reconforge.auth.service import LocalAuthService
from reconforge.connectors.writeback import WritebackPolicy, dispatch_writeback
from reconforge.connectors.writeback_network import (
    WritebackNetworkExecutor,
    WritebackNetworkRegistration,
    WritebackNetworkResponse,
)
from reconforge.db import connect, run_migrations
from reconforge.infrastructure.sqlite_writeback import SQLiteWritebackIntentRepository
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

    mismatched = {**payload, "requested_by": "different-actor"}
    denied = client.post("/api/v1/connectors/writeback/intents", json=mismatched, headers=headers)
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "writeback_actor_mismatch"

    check = connect(db_path)
    try:
        assert check.execute("SELECT COUNT(*) FROM connector_writeback_intents").fetchone()[0] == 4
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
            del endpoint, headers, body, timeout_seconds, maximum_response_bytes
            self.calls += 1
            response = {
                "accepted": True,
                "idempotency_key": payload["idempotency_key"],
                "provider_reference": "provider-1",
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
    dispatched = client.post(
        f"/api/v1/connectors/writeback/intents/{payload['intent_id']}/dispatch",
        json={"tenant_id": "tenant-a", "workspace_id": "workspace-a", "expected_version": 2},
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
