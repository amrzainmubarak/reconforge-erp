"""Live PostgreSQL HTTP contract for account reconciliation."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from reconforge.api import create_api_app
from reconforge.api.server_identity import AuthenticatedServerRequest, PrincipalScopeSnapshot
from reconforge.auth.models import LocalUser
from reconforge.infrastructure.postgres import (
    PostgresConnectionFactory,
    PostgresSettings,
    install_postgres_rls_schema,
)
from reconforge.infrastructure.postgres_accounts import POSTGRES_ACCOUNTS_SCHEMA_SQL
from reconforge.infrastructure.postgres_domain import install_postgres_domain_schema


@pytest.mark.skipif(not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"), reason="requires live PostgreSQL")
def test_live_server_accounts_http_lifecycle_is_scoped_and_maker_checker_safe(
    tmp_path: Path, monkeypatch: Any
) -> None:
    psycopg = pytest.importorskip("psycopg")
    dsn = os.environ["RECONFORGE_TEST_POSTGRES_DSN"]
    admin_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN", dsn)
    app_user = os.environ.get("RECONFORGE_TEST_POSTGRES_APP_USER", "")
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", app_user):
        pytest.fail("RECONFORGE_TEST_POSTGRES_APP_USER is required and must be a safe role name")

    token = uuid4().hex[:8]
    tenant_id = f"accounts_http_{token}"
    workspace_id = f"workspace_{token}"
    reconciliation_id: str | None = None
    admin = PostgresConnectionFactory(PostgresSettings(dsn=admin_dsn, require_tls=False)).connect()
    try:
        with admin.transaction():
            install_postgres_rls_schema(admin)
            install_postgres_domain_schema(admin)
            admin.execute(POSTGRES_ACCOUNTS_SCHEMA_SQL)
            admin.execute(f"GRANT USAGE ON SCHEMA reconforge TO {app_user}")
            admin.execute(f"GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA reconforge TO {app_user}")
            admin.execute(
                "INSERT INTO reconforge.tenants(id,name) VALUES (%s,%s)",
                (tenant_id, tenant_id),
            )
            admin.execute(
                "INSERT INTO reconforge.domain_workspaces(tenant_id,id,name) VALUES (%s,%s,%s)",
                (tenant_id, workspace_id, workspace_id),
            )

        maker = LocalUser(id=f"maker-{token}", username=f"maker-{token}", display_name="Maker")
        reviewer = LocalUser(id=f"reviewer-{token}", username=f"reviewer-{token}", display_name="Reviewer")
        scope = PrincipalScopeSnapshot(workspace_ids=frozenset({workspace_id}))

        def authenticate(_request: Any, credential: str) -> AuthenticatedServerRequest | None:
            if credential == "maker-token":
                return AuthenticatedServerRequest(
                    user=maker,
                    permissions=frozenset({"accounts.read", "accounts.prepare"}),
                    principal_type="user",
                    scope_authority=scope,
                )
            if credential == "reviewer-token":
                return AuthenticatedServerRequest(
                    user=reviewer,
                    permissions=frozenset({"accounts.read", "accounts.review", "accounts.complete"}),
                    principal_type="user",
                    scope_authority=scope,
                )
            return None

        import reconforge.api.app as app_module
        import reconforge.api.dependencies as dependencies

        monkeypatch.setattr(app_module, "authenticate_server_request", authenticate)
        monkeypatch.setattr(dependencies, "authenticate_server_request", authenticate)
        monkeypatch.setattr(dependencies, "server_audit_administration_enabled", lambda _request: False)

        app = create_api_app(
            tmp_path / "unused.db",
            tenant_db_root=tmp_path / "tenants",
            postgres_dsn=dsn,
            postgres_require_tls=False,
        )
        with TestClient(app) as client:
            base_headers = {"X-ReconForge-Tenant": tenant_id, "X-ReconForge-Workspace": workspace_id}
            maker_headers = {**base_headers, "Authorization": "Bearer maker-token"}
            reviewer_headers = {**base_headers, "Authorization": "Bearer reviewer-token"}

            created = client.post(
                "/api/v1/accounts/reconciliations",
                headers=maker_headers,
                json={
                    "period_name": "2026-08",
                    "entity_code": "entity-a",
                    "account_code": "1000",
                    "account_name": "Cash",
                    "balance": "125000.250000000000001",
                    "preparer": "spoofed-preparer",
                    "reviewer": "spoofed-reviewer",
                },
            )
            assert created.status_code == 200, created.text
            reconciliation_id = str(created.json()["reconciliation"]["id"])
            assert created.json()["reconciliation"]["balance_decimal"] == "125000.250000000000001"
            assert created.json()["reconciliation"]["workspace_id"] == workspace_id
            assert created.json()["reconciliation"]["created_by"] == maker.id

            prepared = client.post(
                f"/api/v1/accounts/reconciliations/{reconciliation_id}/prepare",
                headers=maker_headers,
                json={},
            )
            submitted = client.post(
                f"/api/v1/accounts/reconciliations/{reconciliation_id}/submit",
                headers=maker_headers,
                json={},
            )
            reviewed = client.post(
                f"/api/v1/accounts/reconciliations/{reconciliation_id}/review",
                headers=reviewer_headers,
                json={"reviewer": "spoofed-reviewer"},
            )
            completed = client.post(
                f"/api/v1/accounts/reconciliations/{reconciliation_id}/complete",
                headers=reviewer_headers,
                json={},
            )
            listed = client.get("/api/v1/accounts/reconciliations", headers=reviewer_headers)

            assert prepared.status_code == 200, prepared.text
            assert submitted.status_code == 200, submitted.text
            assert reviewed.status_code == 200, reviewed.text
            assert completed.status_code == 200, completed.text
            assert listed.status_code == 200, listed.text
            assert completed.json()["reconciliation"]["status"] == "Complete"
            assert completed.json()["reconciliation"]["preparer"] == maker.id
            assert completed.json()["reconciliation"]["reviewer"] == reviewer.id
            assert listed.json()["reconciliations"][0]["balance_decimal"] == "125000.250000000000001"

            denied_workspace = client.get(
                "/api/v1/accounts/reconciliations",
                headers={**reviewer_headers, "X-ReconForge-Workspace": "workspace-not-granted"},
            )
            assert denied_workspace.status_code == 403
            assert denied_workspace.json()["error"]["code"] == "workspace_scope_denied"
    finally:
        try:
            with admin.transaction():
                admin.execute("DELETE FROM reconforge.tenants WHERE id=%s", (tenant_id,))
        except psycopg.Error:
            # Domain audit events are intentionally append-only. The disposable
            # tenant is therefore left for the test database's lifecycle cleanup.
            pass
        finally:
            admin.close()
