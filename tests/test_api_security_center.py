from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from reconforge.api import create_api_app
from reconforge.api.server_identity import AuthenticatedServerRequest, request_tenant_id
from reconforge.application.security_center import SecurityCenterCounts
from reconforge.auth.models import LocalUser
from reconforge.auth.webauthn_config import WebAuthnRuntime
from reconforge.db import run_migrations


def test_security_center_requires_human_permission_mfa_and_returns_only_closed_counts(
    tmp_path: Path, monkeypatch: Any
) -> None:
    import reconforge.api.app as app_module
    import reconforge.api.dependencies as dependencies
    import reconforge.api.routes.security_center as routes

    user = LocalUser(id="admin-a", username="admin", display_name="Admin")
    policy_calls: list[tuple[frozenset[str], str, None]] = []

    def enforce_policy(
        _request: Any, *, permissions: frozenset[str], tenant_id: str, workspace_id: None
    ) -> None:
        policy_calls.append((permissions, tenant_id, workspace_id))

    def authenticate(request: Any, token: str) -> AuthenticatedServerRequest | None:
        assert request_tenant_id(request) == "tenant-a"
        profiles = {
            "human-ok": ("user", frozenset({"security.center.read"}), True, "webauthn_user_verified"),
            "human-no-permission": ("user", frozenset(), True, "webauthn_user_verified"),
            "human-no-step-up": ("user", frozenset({"security.center.read"}), False, None),
            "human-password-only": ("user", frozenset({"security.center.read"}), True, "password_reauthentication"),
            "service": ("service_account", frozenset({"security.center.read"}), True, "webauthn_user_verified"),
        }
        profile = profiles.get(token)
        if profile is None:
            return None
        principal_type, permissions, active, method = profile
        return AuthenticatedServerRequest(
            user=user,
            permissions=permissions,
            principal_type=principal_type,
            step_up_active=active,
            step_up_method=method,
        )

    class Repository:
        def read_counts(self, *, tenant_id: str, as_of: Any) -> SecurityCenterCounts:
            assert tenant_id == "tenant-a"
            assert as_of.tzinfo is not None and as_of.microsecond == 0
            return SecurityCenterCounts(total_users=1, active_users=1, active_users_without_roles=1)

    def execute(request: Any, operation: Any) -> Any:
        return operation(Repository(), request_tenant_id(request))

    monkeypatch.setattr(app_module, "authenticate_server_request", authenticate)
    monkeypatch.setattr(dependencies, "authenticate_server_request", authenticate)
    monkeypatch.setattr(routes, "execute_postgres_security_center", execute)
    monkeypatch.setattr(routes, "enforce_server_scoped_permissions", enforce_policy)
    root = tmp_path / "tenants"
    root.mkdir()
    run_migrations(root / "tenant-a.db")
    client = TestClient(
        create_api_app(
            tmp_path / "unused.db",
            tenant_db_root=root,
            postgres_dsn="postgresql://security.test/postgres",
            postgres_require_tls=False,
            webauthn_runtime=WebAuthnRuntime(
                rp_id="example.test",
                rp_name="ReconForge",
                allowed_origins=("https://admin.example.test",),
            ),
        )
    )

    def read(token: str) -> Any:
        return client.get(
            "/api/v1/admin/security/overview",
            headers={"X-ReconForge-Tenant": "tenant-a", "Authorization": f"Bearer {token}"},
        )

    assert read("human-no-permission").status_code == 403
    assert read("human-no-step-up").json()["error"]["code"] == "step_up_required"
    assert read("human-password-only").json()["error"]["code"] == "mfa_required"
    assert read("service").status_code == 403
    response = read("human-ok")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert set(payload) == {
        "schema_version",
        "as_of",
        "tenant_scope_digest",
        "posture",
        "claim_boundary",
        "identity",
        "sessions",
        "integrations",
        "policy",
        "retention",
        "audit",
        "attention_items",
        "snapshot_digest",
    }
    assert payload["identity"]["total_users"] == 1
    assert payload["integrations"]["webauthn_required_for_privileged_actions"] is True
    assert payload["claim_boundary"] == "operational_snapshot_not_security_assurance"
    assert set(payload["audit"]) == {"audit_events", "chain_verification"}
    serialized = response.text
    for forbidden in (
        "password_hash",
        "token_hash",
        "client_ip",
        "user_agent",
        "destination",
        "secret_ref",
        "event_sequence",
    ):
        assert forbidden not in serialized
    assert policy_calls[-1] == (frozenset({"security.center.read"}), "tenant-a", None)
