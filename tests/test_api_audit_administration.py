from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from reconforge.api import create_api_app
from reconforge.api.browser_session import BROWSER_SESSION_COOKIE
from reconforge.api.server_identity import AuthenticatedServerRequest, request_tenant_id
from reconforge.application.audit_browsing import (
    AuditChainVerification,
    AuditVerificationSummary,
    RedactedAuditEvent,
)
from reconforge.auth.models import LocalUser


def _event(*, event_id: str, source: str, sequence: int) -> RedactedAuditEvent:
    return RedactedAuditEvent(  # type: ignore[arg-type]
        source,
        event_id,
        sequence,
        f"2026-07-30T00:00:0{sequence}Z",
        "identity.user.disabled",
        "identity_user",
        "a" * 64,
        "b" * 64,
        "c" * 64,
        "d" * 64,
        "e" * 64,
        None,
        None,
    )


class _Repository:
    def list_redacted_events(self, **kwargs: object) -> tuple[RedactedAuditEvent, ...]:
        if kwargs["after_occurred_at"] is None:
            return (
                _event(event_id="AE-sensitive-one", source="domain", sequence=1),
                _event(event_id="LE-sensitive-two", source="ledger_control", sequence=2),
            )
        return (_event(event_id="LE-sensitive-two", source="ledger_control", sequence=2),)

    def verify_chains(self) -> AuditVerificationSummary:
        return AuditVerificationSummary(
            True,
            (
                AuditChainVerification("domain", True, 1, "d" * 64, ()),
                AuditChainVerification("ledger_control", True, 1, "e" * 64, ()),
            ),
        )


def test_audit_administration_http_requires_human_assurance_and_redacts(tmp_path: Path, monkeypatch: Any) -> None:
    import reconforge.api.app as app_module
    import reconforge.api.dependencies as dependencies
    import reconforge.api.routes.audit_administration as routes

    user = LocalUser(id="user-admin", username="admin", display_name="Admin")
    policy_calls: list[tuple[str, str, None]] = []

    def enforce_policy(
        _request: Any, *, permissions: frozenset[str], tenant_id: str, workspace_id: None
    ) -> None:
        policy_calls.append((next(iter(permissions)), tenant_id, workspace_id))

    def authenticate(request: Any, token: str) -> AuthenticatedServerRequest | None:
        assert request_tenant_id(request) == "tenant-a"
        profiles = {
            "human-ok": ("user", frozenset({"audit.read", "audit.verify"}), True),
            "human-no-permission": ("user", frozenset(), True),
            "human-no-step-up": ("user", frozenset({"audit.read"}), False),
            "service": ("service_account", frozenset({"audit.read", "audit.verify"}), True),
        }
        profile = profiles.get(token)
        if profile is None:
            return None
        principal_type, permissions, step_up_active = profile
        return AuthenticatedServerRequest(
            user=user,
            permissions=permissions,
            principal_type=principal_type,
            session_id="session-admin",
            step_up_active=step_up_active,
        )

    repository = _Repository()

    def execute(request: Any, operation: Any) -> Any:
        return operation(repository, request_tenant_id(request))

    monkeypatch.setattr(app_module, "authenticate_server_request", authenticate)
    monkeypatch.setattr(dependencies, "authenticate_server_request", authenticate)
    monkeypatch.setattr(routes, "execute_postgres_audit_administration", execute)
    monkeypatch.setattr(routes, "enforce_server_scoped_permissions", enforce_policy)
    root = tmp_path / "tenants"
    root.mkdir()
    client = TestClient(
        create_api_app(
            tmp_path / "control.db",
            tenant_db_root=root,
            postgres_dsn="postgresql://identity.test/postgres",
            postgres_require_tls=False,
            cursor_signing_key=b"audit-administration-test-key-32-bytes",
        ),
        base_url="https://testserver",
    )

    def headers(token: str) -> dict[str, str]:
        return {"X-ReconForge-Tenant": "tenant-a", "Authorization": f"Bearer {token}"}

    path = "/api/v1/admin/audit/events"
    assert client.get(path, headers=headers("human-no-permission")).status_code == 403
    assert client.get(path, headers=headers("human-no-step-up")).json()["error"]["code"] == "step_up_required"
    assert client.get(path, headers=headers("service")).status_code == 403

    first = client.get(path, params={"limit": 1}, headers=headers("human-ok"))
    assert first.status_code == 200, first.text
    payload = first.json()
    assert payload["pagination"]["next_cursor"] is not None
    assert payload["disclosure"] == "redacted_no_raw_subject_object_reason_or_metadata"
    assert payload["chain_model"] == "independent_source_chains_no_global_chain"
    second = client.get(path, params={"limit": 1, "cursor": payload["pagination"]["next_cursor"]}, headers=headers("human-ok"))
    assert second.status_code == 200, second.text
    hostile = client.get(path, params={"cursor": payload["pagination"]["next_cursor"] + "x"}, headers=headers("human-ok"))
    assert hostile.status_code == 400

    verification = client.get("/api/v1/admin/audit/verify", headers=headers("human-ok"))
    assert verification.status_code == 200 and verification.json()["ok"] is True
    assert policy_calls[0] == ("audit.read", "tenant-a", None)
    assert ("audit.verify", "tenant-a", None) in policy_calls
    client.cookies.set(BROWSER_SESSION_COOKIE, "human-ok")
    browser_cookie_read = client.get(path, headers={"X-ReconForge-Tenant": "tenant-a"})
    assert browser_cookie_read.status_code == 200
    serialized = first.text + second.text + verification.text
    for forbidden in ("sensitive-user-id", "sensitive-object-id"):
        assert forbidden not in serialized.casefold()
    assert {"reason", "metadata_text", "request_id"}.isdisjoint(payload["events"][0])
