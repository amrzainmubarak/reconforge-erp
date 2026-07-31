from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from reconforge.api import create_api_app
from reconforge.api.server_identity import AuthenticatedServerRequest, request_tenant_id
from reconforge.application.security_governance import (
    EvidenceRetentionChange,
    IntegrationDisableChange,
    IntegrationPage,
    IntegrationSummary,
    RetentionPolicyChange,
    RetentionPolicyPage,
    RetentionPolicySummary,
)
from reconforge.auth import LocalAuthService
from reconforge.auth.models import LocalUser
from reconforge.auth.webauthn_config import WebAuthnRuntime
from reconforge.db import connect, run_migrations


def _integration(*, kind: str = "service_account", identifier: str = "svc-worker", status: str = "active") -> IntegrationSummary:
    return IntegrationSummary(  # type: ignore[arg-type]
        kind,
        identifier,
        status,
        1,
        2,
        1 if status == "active" else 0,
        "2026-07-30T00:00:00Z",
        None,
        None,
        "a" * 64,
        "b" * 64,
    )


def _policy(*, version: int = 1, active: bool = True) -> RetentionPolicySummary:
    return RetentionPolicySummary(
        "rtp-" + "a" * 32,
        "audit-evidence",
        "Audit evidence",
        "restricted",
        365,
        active,
        version,
        "2026-07-30T00:00:00Z",
        "2026-07-30T00:00:00Z",
        None if active else "2026-07-30T01:00:00Z",
        "c" * 64,
    )


class _Repository:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def list_integrations(self, **kwargs: object) -> IntegrationPage:
        self.calls.append(("list_integrations", kwargs))
        if kwargs["after_kind"] is None:
            return IntegrationPage((_integration(),), "service_account", "svc-worker")
        return IntegrationPage((_integration(kind="scim_credential", identifier="scc-" + "a" * 32),))

    def disable_integration(self, **kwargs: object) -> IntegrationDisableChange:
        self.calls.append(("disable_integration", kwargs))
        return IntegrationDisableChange(_integration(status="disabled"), True, 1, "AE-1")

    def list_retention_policies(self, **kwargs: object) -> RetentionPolicyPage:
        self.calls.append(("list_retention_policies", kwargs))
        if kwargs["after_name"] is None:
            return RetentionPolicyPage((_policy(),), "audit-evidence", "rtp-" + "a" * 32)
        return RetentionPolicyPage((_policy(),))

    def create_retention_policy(self, **kwargs: object) -> RetentionPolicyChange:
        self.calls.append(("create_retention_policy", kwargs))
        return RetentionPolicyChange(_policy(), True, "AE-2")

    def update_retention_policy(self, **kwargs: object) -> RetentionPolicyChange:
        self.calls.append(("update_retention_policy", kwargs))
        return RetentionPolicyChange(_policy(version=2), True, "AE-3")

    def apply_retention_policy(self, **kwargs: object) -> EvidenceRetentionChange:
        self.calls.append(("apply_retention_policy", kwargs))
        return EvidenceRetentionChange(
            "evidence-1",
            "rtp-" + "a" * 32,
            1,
            2,
            None,
            "2027-07-30T00:00:00Z",
            "2027-07-30T00:00:00Z",
            True,
            True,
            "AE-4",
            "d" * 64,
        )


def test_security_governance_http_is_human_mfa_governed_paginated_and_redacted(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    import reconforge.api.app as app_module
    import reconforge.api.dependencies as dependencies
    import reconforge.api.routes.security_governance as routes

    repository = _Repository()
    user = LocalUser(id="user-admin", username="admin", display_name="Admin")

    def authenticate(request: Any, token: str) -> AuthenticatedServerRequest | None:
        assert request_tenant_id(request) == "tenant-a"
        profiles = {
            "human-ok": ("user", frozenset({"security.policy.manage"}), True, "webauthn_user_verified"),
            "human-no-permission": ("user", frozenset(), True, "webauthn_user_verified"),
            "human-no-step-up": ("user", frozenset({"security.policy.manage"}), False, None),
            "human-password-only": (
                "user",
                frozenset({"security.policy.manage"}),
                True,
                "password_reauthentication",
            ),
            "service": (
                "service_account",
                frozenset({"security.policy.manage"}),
                True,
                "webauthn_user_verified",
            ),
        }
        profile = profiles.get(token)
        if profile is None:
            return None
        principal_type, permissions, active, method = profile
        return AuthenticatedServerRequest(
            user=user,
            permissions=permissions,
            principal_type=principal_type,
            session_id="session-admin",
            step_up_active=active,
            step_up_method=method,
        )

    def execute(request: Any, operation: Any) -> Any:
        return operation(repository, request_tenant_id(request))

    monkeypatch.setattr(app_module, "authenticate_server_request", authenticate)
    monkeypatch.setattr(dependencies, "authenticate_server_request", authenticate)
    monkeypatch.setattr(routes, "execute_postgres_security_governance", execute)
    root = tmp_path / "tenants"
    root.mkdir()
    client = TestClient(
        create_api_app(
            tmp_path / "missing-control.db",
            tenant_db_root=root,
            postgres_dsn="postgresql://identity.test/postgres",
            postgres_require_tls=False,
            cursor_signing_key=b"security-governance-test-key-32-bytes",
            webauthn_runtime=WebAuthnRuntime(
                rp_id="example.test",
                rp_name="ReconForge",
                allowed_origins=("https://admin.example.test",),
            ),
        )
    )

    def headers(token: str) -> dict[str, str]:
        return {"X-ReconForge-Tenant": "tenant-a", "Authorization": f"Bearer {token}"}

    path = "/api/v1/admin/security/integrations"
    assert client.get(path, headers=headers("human-no-permission")).status_code == 403
    assert client.get(path, headers=headers("human-no-step-up")).json()["error"]["code"] == "step_up_required"
    assert client.get(path, headers=headers("human-password-only")).json()["error"]["code"] == "mfa_required"
    assert client.get(path, headers=headers("service")).status_code == 403

    first = client.get(path, params={"limit": 1}, headers=headers("human-ok"))
    assert first.status_code == 200, first.text
    cursor = first.json()["pagination"]["next_cursor"]
    second = client.get(path, params={"limit": 1, "cursor": cursor}, headers=headers("human-ok"))
    assert second.status_code == 200 and second.json()["integrations"][0]["kind"] == "scim_credential"
    mismatch = client.get(
        path,
        params={"cursor": cursor, "include_inactive": True},
        headers=headers("human-ok"),
    )
    assert mismatch.status_code == 400 and mismatch.json()["error"]["code"] == "cursor_context_mismatch"

    disabled = client.post(
        "/api/v1/admin/security/integrations/service_account/svc-worker/disable",
        headers=headers("human-ok"),
        json={"expected_state_digest": "b" * 64, "reason_code": "security_response"},
    )
    assert disabled.status_code == 200 and disabled.json()["revoked_credentials"] == 1
    policies = client.get(
        "/api/v1/admin/security/retention-policies",
        params={"limit": 1},
        headers=headers("human-ok"),
    )
    assert policies.status_code == 200 and policies.json()["policies"][0]["name"] == "audit-evidence"
    created = client.post(
        "/api/v1/admin/security/retention-policies",
        headers=headers("human-ok"),
        json={
            "name": "audit-evidence",
            "description": "Audit evidence",
            "data_classification": "restricted",
            "duration_days": 365,
        },
    )
    assert created.status_code == 200 and created.json()["transitioned"] is True
    updated = client.patch(
        "/api/v1/admin/security/retention-policies/rtp-" + "a" * 32,
        headers=headers("human-ok"),
        json={"expected_lifecycle_version": 1, "reason_code": "policy_change", "duration_days": 730},
    )
    assert updated.status_code == 200 and updated.json()["policy"]["lifecycle_version"] == 2
    applied = client.post(
        "/api/v1/admin/security/retention-policies/rtp-" + "a" * 32 + "/evidence/evidence-1",
        headers=headers("human-ok"),
        json={"expected_retention_version": 1, "reason_code": "policy_application"},
    )
    assert applied.status_code == 200 and applied.json()["retention_extended"] is True
    hostile = client.post(
        "/api/v1/admin/security/retention-policies",
        headers=headers("human-ok"),
        json={
            "name": "audit-evidence",
            "data_classification": "restricted",
            "duration_days": 365,
            "secret": "not-accepted",
        },
    )
    assert hostile.status_code == 422

    serialized = first.text + second.text + disabled.text + policies.text + created.text + updated.text + applied.text
    for forbidden in (
        "token_hash",
        "destination",
        "secret_ref",
        "external_subject_hash",
        "password",
        "email",
        "client_ip",
        "user_agent",
    ):
        assert forbidden not in serialized.casefold()


def test_security_governance_requires_server_profile(tmp_path: Path) -> None:
    db_path = tmp_path / "local.db"
    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    try:
        LocalAuthService(connection).init_admin(username="admin", password="Secret-123")
        connection.execute(
            "INSERT OR IGNORE INTO permissions(name,description) VALUES (?,?)",
            ("security.policy.manage", "Manage security policy."),
        )
        connection.execute(
            """INSERT OR IGNORE INTO role_permissions(role_id,permission_name)
               SELECT id,'security.policy.manage' FROM roles WHERE name='administrator'"""
        )
        connection.commit()
    finally:
        connection.close()
    client = TestClient(create_api_app(db_path))
    login = client.post("/api/v1/auth/login", json={"username": "admin", "password": "Secret-123"})
    unavailable = client.get(
        "/api/v1/admin/security/integrations",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
    )
    assert unavailable.status_code == 403
