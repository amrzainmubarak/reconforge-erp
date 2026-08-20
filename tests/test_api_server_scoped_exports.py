"""Contract tests for the authenticated PostgreSQL scoped-export API."""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from reconforge.api import create_api_app
from reconforge.api.errors import APIError
from reconforge.api.server_identity import RequestExecutionScope, request_tenant_id
from reconforge.application.scoped_exports import (
    ScopedExportDataset,
    ScopedExportScope,
    ScopedExportSnapshot,
)
from reconforge.auth.models import LocalUser
from reconforge.db import run_migrations
from reconforge.infrastructure.postgres import (
    PostgresConnectionFactory,
    PostgresSettings,
    PostgresTenantBoundary,
)
from reconforge.infrastructure.postgres_scope_authority import PostgresScopeAuthorityRepository
from reconforge.infrastructure.postgres_service_accounts import PostgresServiceAccountRepository


def test_scoped_export_boundary_is_server_only_and_has_no_sqlite_fallback(tmp_path: Path) -> None:
    import reconforge.api.server_scoped_exports as export_boundary

    app = create_api_app(tmp_path / "local.db")
    request = SimpleNamespace(app=app)

    with pytest.raises(APIError) as raised:
        export_boundary.execute_postgres_scoped_export(request, lambda _repository, _scope: None)

    assert raised.value.status_code == 501
    assert raised.value.code == "scoped_export_server_only"


def test_scoped_export_route_is_authenticated_hierarchy_bound_and_deterministic(
    tmp_path: Path, monkeypatch: Any
) -> None:
    import reconforge.api.app as app_module
    import reconforge.api.dependencies as dependencies
    import reconforge.api.routes.scoped_exports as export_routes
    import reconforge.api.server_scoped_exports as export_boundary

    user = LocalUser(id="user-a", username="alice", display_name="Alice")
    permissions = frozenset({"reports.read"})
    expected_scope = ScopedExportScope(
        tenant_id="tenant-a",
        workspace_id="workspace-a",
        organization_id="org-a",
        entity_id="entity-a",
    )
    observed_permissions: list[dict[str, object]] = []

    def authenticate(request: Any, token: str) -> tuple[LocalUser, frozenset[str]] | None:
        assert request_tenant_id(request) == "tenant-a"
        return (user, permissions) if token == "server-token" else None

    class FakeRepository:
        def snapshot(self, scope: ScopedExportScope) -> ScopedExportSnapshot:
            assert scope == expected_scope
            return ScopedExportSnapshot(
                scope=scope,
                datasets=(
                    ScopedExportDataset(
                        name="organizations",
                        rows=({"id": "org-a", "workspace_id": "workspace-a"},),
                    ),
                ),
            )

    def execute(request: Any, operation: Any) -> dict[str, object]:
        assert request_tenant_id(request) == "tenant-a"
        return operation(FakeRepository(), expected_scope)

    monkeypatch.setattr(app_module, "authenticate_server_request", authenticate)
    monkeypatch.setattr(dependencies, "authenticate_server_request", authenticate)
    monkeypatch.setattr(export_routes, "request_execution_scope", lambda _request: RequestExecutionScope(
        "tenant-a", "workspace-a", "org-a", "entity-a"
    ))
    monkeypatch.setattr(export_boundary, "request_execution_scope", lambda _request: RequestExecutionScope(
        "tenant-a", "workspace-a", "org-a", "entity-a"
    ))
    monkeypatch.setattr(
        export_routes,
        "enforce_server_scoped_permission",
        lambda _request, **kwargs: observed_permissions.append(kwargs),
    )
    monkeypatch.setattr(export_routes, "server_scoped_exports_enabled", lambda _request: True)
    monkeypatch.setattr(export_routes, "execute_postgres_scoped_export", execute)

    tenant_root = tmp_path / "tenants"
    tenant_root.mkdir()
    run_migrations(tenant_root / "tenant-a.db")
    client = TestClient(
        create_api_app(
            tmp_path / "unused.db",
            tenant_db_root=tenant_root,
            postgres_dsn="postgresql://exports.test/postgres",
            postgres_require_tls=False,
            cursor_signing_key=b"scoped-export-cursor-test-key-32-bytes",
        )
    )
    headers = {
        "X-ReconForge-Tenant": "tenant-a",
        "X-ReconForge-Workspace": "workspace-a",
        "X-ReconForge-Organization": "org-a",
        "X-ReconForge-Legal-Entity": "entity-a",
        "Authorization": "Bearer server-token",
    }

    response = client.get("/api/v1/exports/scoped", headers=headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["digest"] == body["export"]["artifact_digest"]
    assert len(body["digest"]) == hashlib.sha256(b"").digest_size * 2
    assert body["byte_size"] > 0
    assert body["source"] == {
        "kind": "postgresql-scoped-control-plane-export",
        "server_mode": True,
    }
    assert body["export"]["scope"] == {
        "entity_id": "entity-a",
        "organization_id": "org-a",
        "tenant_id": "tenant-a",
        "workspace_id": "workspace-a",
    }
    assert observed_permissions == [
        {
            "permission": "reports.read",
            "tenant_id": "tenant-a",
            "workspace_id": "workspace-a",
            "entity_id": "entity-a",
        }
    ]


@pytest.mark.skipif(
    not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"),
    reason="requires live PostgreSQL",
)
def test_live_server_scoped_export_http_is_service_scoped_and_tenant_isolated(tmp_path: Path) -> None:
    """Exercise the real authenticated export route beneath PostgreSQL RLS."""

    pytest.importorskip("psycopg")
    dsn = os.environ["RECONFORGE_TEST_POSTGRES_DSN"]
    admin_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN", dsn)
    app_user = os.environ.get("RECONFORGE_TEST_POSTGRES_APP_USER", "")
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", app_user):
        pytest.fail("RECONFORGE_TEST_POSTGRES_APP_USER is required and must be a safe role name")

    token = uuid4().hex[:8]
    tenant_a = f"export_http_a_{token}"
    tenant_b = f"export_http_b_{token}"
    workspace_a, workspace_b = f"export_ws_a_{token}", f"export_ws_b_{token}"
    organization_a, organization_b = f"export_org_a_{token}", f"export_org_b_{token}"
    entity_a, entity_b = f"export_ent_a_{token}", f"export_ent_b_{token}"
    account_id = f"svc-export-http-{token}"
    account_name = f"export-http-{token}"
    admin_factory = PostgresConnectionFactory(PostgresSettings(dsn=admin_dsn, require_tls=False))
    app_factory = PostgresConnectionFactory(PostgresSettings(dsn=dsn, require_tls=False))
    admin = admin_factory.connect()
    credential_token = ""
    root = tmp_path / "tenants"
    root.mkdir()
    run_migrations(root / f"{tenant_a}.db")
    run_migrations(root / f"{tenant_b}.db")
    try:
        with admin.transaction():
            admin.execute(f"GRANT USAGE ON SCHEMA reconforge TO {app_user}")
            admin.execute(
                f"GRANT SELECT ON reconforge.tenants,reconforge.domain_workspaces,reconforge.domain_periods,"
                f"reconforge.organizations,reconforge.legal_entities,reconforge.branches,"
                f"reconforge.durable_jobs,reconforge.evidence_application_registry TO {app_user}"
            )
            admin.execute(
                f"GRANT SELECT, INSERT, UPDATE ON reconforge.identity_permissions,"
                f"reconforge.service_accounts,reconforge.service_account_permissions,"
                f"reconforge.service_account_credentials,reconforge.service_account_events,"
                f"reconforge.principal_scope_grants TO {app_user}"
            )
            admin.execute(
                "INSERT INTO reconforge.tenants(id,name) VALUES(%s,%s),(%s,%s)",
                (tenant_a, tenant_a, tenant_b, tenant_b),
            )
            for workspace, organization, entity, code in (
                (workspace_a, organization_a, entity_a, "EA"),
                (workspace_b, organization_b, entity_b, "EB"),
            ):
                tenant = tenant_a
                admin.execute(
                    "INSERT INTO reconforge.domain_workspaces(tenant_id,id,name) VALUES(%s,%s,%s)",
                    (tenant, workspace, workspace),
                )
                admin.execute(
                    "INSERT INTO reconforge.organizations"
                    "(tenant_id,id,name,organization_code,application_workspace_id) "
                    "VALUES(%s,%s,%s,%s,%s)",
                    (tenant, organization, organization, code, workspace),
                )
                admin.execute(
                    "INSERT INTO reconforge.currencies(tenant_id,code,name,minor_units) "
                    "VALUES(%s,'USD','US Dollar',2) ON CONFLICT (tenant_id,code) DO NOTHING",
                    (tenant,),
                )
                admin.execute(
                    "INSERT INTO reconforge.legal_entities"
                    "(tenant_id,id,organization_id,entity_code,name,currency_code) "
                    "VALUES(%s,%s,%s,%s,%s,'USD')",
                    (tenant, entity, organization, code, entity),
                )
                admin.execute(
                    "INSERT INTO reconforge.branches"
                    "(tenant_id,id,organization_id,legal_entity_id,branch_code,name) "
                    "VALUES(%s,%s,%s,%s,%s,%s)",
                    (tenant, f"branch-{entity}", organization, entity, code, entity),
                )
            admin.execute(
                "INSERT INTO reconforge.identity_permissions(tenant_id,name,description) "
                "VALUES(%s,'reports.read','Scoped control-plane export read')",
                (tenant_a,),
            )

        with PostgresTenantBoundary(app_factory).transaction(tenant_a) as connection:
            service_accounts = PostgresServiceAccountRepository(connection)
            service_accounts.create_account(
                tenant_id=tenant_a,
                account_id=account_id,
                name=account_name,
                display_name="Scoped export HTTP reader",
                permissions=frozenset({"reports.read"}),
                actor_id="security-admin",
            )
            credential = service_accounts.issue_credential(
                tenant_id=tenant_a,
                account_id=account_id,
                actor_id="security-admin",
                ttl=timedelta(hours=1),
            )
            credential_token = credential.token
            authority = PostgresScopeAuthorityRepository(connection)
            authority.grant(
                tenant_id=tenant_a,
                grant_id=f"grant-ws-{token}",
                principal_type="service_account",
                principal_id=account_id,
                scope_type="workspace",
                scope_id=workspace_a,
                actor_id="security-admin",
            )
            authority.grant(
                tenant_id=tenant_a,
                grant_id=f"grant-org-{token}",
                principal_type="service_account",
                principal_id=account_id,
                scope_type="organization",
                scope_id=organization_a,
                actor_id="security-admin",
            )
            authority.grant(
                tenant_id=tenant_a,
                grant_id=f"grant-entity-{token}",
                principal_type="service_account",
                principal_id=account_id,
                scope_type="legal_entity",
                scope_id=entity_a,
                actor_id="security-admin",
            )

        app = create_api_app(
            tmp_path / "unused.db",
            tenant_db_root=root,
            postgres_dsn=dsn,
            postgres_require_tls=False,
        )
        headers = {
            "X-ReconForge-Tenant": tenant_a,
            "X-ReconForge-Workspace": workspace_a,
            "X-ReconForge-Organization": organization_a,
            "X-ReconForge-Legal-Entity": entity_a,
            "Authorization": f"Bearer {credential_token}",
        }
        with TestClient(app) as client:
            response = client.get("/api/v1/exports/scoped", headers=headers)
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["digest"] == body["export"]["artifact_digest"]
            assert body["source"] == {
                "kind": "postgresql-scoped-control-plane-export",
                "server_mode": True,
            }
            payload = json.dumps(body["export"], sort_keys=True)
            assert workspace_a in payload and organization_a in payload and entity_a in payload
            assert workspace_b not in payload and organization_b not in payload and entity_b not in payload

            sibling = client.get(
                "/api/v1/exports/scoped",
                headers={**headers, "X-ReconForge-Workspace": workspace_b},
            )
            assert sibling.status_code == 403, sibling.text
            foreign_tenant = client.get(
                "/api/v1/exports/scoped",
                headers={**headers, "X-ReconForge-Tenant": tenant_b},
            )
            assert foreign_tenant.status_code == 401, foreign_tenant.text
    finally:
        try:
            with admin.transaction():
                admin.execute("ALTER TABLE reconforge.principal_scope_grants DISABLE TRIGGER principal_scope_grants_guard")
                admin.execute("ALTER TABLE reconforge.service_account_events DISABLE TRIGGER trg_service_account_events_append_only")
                for table in (
                    "principal_scope_grants",
                    "service_account_credentials",
                    "service_account_permissions",
                    "service_account_events",
                    "service_accounts",
                    "identity_permissions",
                    "branches",
                    "legal_entities",
                    "organizations",
                    "currencies",
                    "domain_workspaces",
                ):
                    admin.execute(f"DELETE FROM reconforge.{table} WHERE tenant_id IN (%s,%s)", (tenant_a, tenant_b))
                admin.execute("DELETE FROM reconforge.tenants WHERE id IN (%s,%s)", (tenant_a, tenant_b))
                admin.execute("ALTER TABLE reconforge.principal_scope_grants ENABLE TRIGGER principal_scope_grants_guard")
                admin.execute("ALTER TABLE reconforge.service_account_events ENABLE TRIGGER trg_service_account_events_append_only")
        finally:
            admin.close()
