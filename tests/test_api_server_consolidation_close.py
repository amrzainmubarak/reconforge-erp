from __future__ import annotations

import os
import re
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from reconforge.api import create_api_app
from reconforge.db import run_migrations
from reconforge.domain.consolidation_lifecycle import prepare_consolidation_worksheet
from reconforge.infrastructure.postgres import (
    PostgresConnectionFactory,
    PostgresSettings,
    PostgresTenantBoundary,
    install_postgres_rls_schema,
)
from reconforge.infrastructure.postgres_consolidation_close import PostgresConsolidationCloseRepository
from reconforge.infrastructure.postgres_domain import install_postgres_domain_schema
from reconforge.infrastructure.postgres_identity import POSTGRES_IDENTITY_SCHEMA_SQL
from reconforge.infrastructure.postgres_master_data import POSTGRES_MASTER_DATA_SCHEMA_SQL
from reconforge.infrastructure.postgres_scope_authority import (
    POSTGRES_SCOPE_AUTHORITY_SCHEMA_SQL,
    PostgresScopeAuthorityRepository,
)
from reconforge.infrastructure.postgres_service_accounts import (
    POSTGRES_SERVICE_ACCOUNT_SCHEMA_SQL,
    PostgresServiceAccountRepository,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"), reason="requires live PostgreSQL")
def test_live_server_consolidation_close_http_routes_are_rls_scoped(tmp_path: Path) -> None:
    """Exercise the real PostgreSQL identity, replay, and workspace boundary over HTTP."""

    pytest.importorskip("psycopg")
    from tests.test_sqlite_consolidation_close import _worksheet

    dsn = os.environ["RECONFORGE_TEST_POSTGRES_DSN"]
    admin_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN", dsn)
    app_user = os.environ.get("RECONFORGE_TEST_POSTGRES_APP_USER", "")
    if not app_user:
        pytest.skip("requires a non-privileged application role")
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", app_user):
        pytest.fail("RECONFORGE_TEST_POSTGRES_APP_USER contains unsafe characters")

    tenant_a = "close_http_a_" + uuid4().hex[:8]
    tenant_b = "close_http_b_" + uuid4().hex[:8]
    workspace = "consolidation-http-workspace"
    root = tmp_path / "tenants"
    root.mkdir()
    run_migrations(root / f"{tenant_a}.db")
    run_migrations(root / f"{tenant_b}.db")
    admin_factory = PostgresConnectionFactory(PostgresSettings(dsn=admin_dsn, require_tls=False))
    app_factory = PostgresConnectionFactory(PostgresSettings(dsn=dsn, require_tls=False))
    admin = None
    try:
        admin = admin_factory.connect()
        with admin.transaction():
            install_postgres_rls_schema(admin)
            admin.execute(POSTGRES_IDENTITY_SCHEMA_SQL)
            admin.execute(POSTGRES_SERVICE_ACCOUNT_SCHEMA_SQL)
            install_postgres_domain_schema(admin)
            admin.execute(POSTGRES_MASTER_DATA_SCHEMA_SQL)
            admin.execute(POSTGRES_SCOPE_AUTHORITY_SCHEMA_SQL)
            admin.execute(f"GRANT USAGE ON SCHEMA reconforge TO {app_user}")
            admin.execute(
                f"GRANT SELECT, INSERT, UPDATE ON reconforge.tenants, reconforge.identity_permissions, "
                f"reconforge.service_accounts, reconforge.service_account_permissions, "
                f"reconforge.service_account_credentials, reconforge.service_account_events TO {app_user}"
            )
            admin.execute(
                f"GRANT SELECT, INSERT ON reconforge.principal_scope_grants, "
                f"reconforge.consolidation_close_periods, reconforge.consolidation_close_runs, "
                f"reconforge.consolidation_close_run_lines TO {app_user}"
            )
            admin.execute(
                f"GRANT SELECT ON reconforge.consolidation_close_effects, "
                f"reconforge.consolidation_close_effect_lines, reconforge.consolidation_close_period_events, "
                f"reconforge.consolidation_close_intercompany_links, "
                f"reconforge.consolidation_close_impairment_links, "
                f"reconforge.consolidation_close_deferred_tax_links, "
                f"reconforge.consolidation_close_ppa_links, "
                f"reconforge.consolidation_close_ownership_change_links, "
                f"reconforge.intercompany_elimination_artifacts, "
                f"reconforge.consolidation_impairment_artifacts, "
                f"reconforge.consolidation_deferred_tax_artifacts, "
                f"reconforge.consolidation_ppa_artifacts, "
                f"reconforge.consolidation_ownership_change_artifacts TO {app_user}"
            )
            admin.execute(
                f"GRANT SELECT, INSERT, UPDATE ON reconforge.domain_audit_ledger_state, "
                f"reconforge.domain_audit_events, reconforge.outbox_events TO {app_user}"
            )
            admin.execute(f"GRANT SELECT ON reconforge.domain_workspaces TO {app_user}")
            admin.execute(
                "INSERT INTO reconforge.tenants(id,name) VALUES (%s,%s),(%s,%s)",
                (tenant_a, tenant_a, tenant_b, tenant_b),
            )
            admin.execute(
                "INSERT INTO reconforge.domain_workspaces(tenant_id,id,name) VALUES (%s,%s,%s)",
                (tenant_a, workspace, "Consolidation HTTP workspace"),
            )
            admin.execute(
                "INSERT INTO reconforge.identity_permissions(tenant_id,name,description) "
                "VALUES (%s,'finance_core.read','Consolidation evidence read')",
                (tenant_a,),
            )

        with PostgresTenantBoundary(app_factory).transaction(tenant_a, workspace_id=workspace) as connection:
            service_accounts = PostgresServiceAccountRepository(connection)
            service_accounts.create_account(
                tenant_id=tenant_a,
                account_id="svc-consolidation-http",
                name="consolidation-http",
                display_name="Consolidation HTTP reader",
                permissions=frozenset({"finance_core.read"}),
                actor_id="security-admin",
            )
            credential = service_accounts.issue_credential(
                tenant_id=tenant_a,
                account_id="svc-consolidation-http",
                actor_id="security-admin",
                ttl=timedelta(hours=1),
            )
            PostgresScopeAuthorityRepository(connection).grant(
                tenant_id=tenant_a,
                grant_id="grant-consolidation-http-workspace",
                principal_type="service_account",
                principal_id="svc-consolidation-http",
                scope_type="workspace",
                scope_id=workspace,
                actor_id="security-admin",
            )
            worksheet = prepare_consolidation_worksheet(_worksheet().request)
            repository = PostgresConsolidationCloseRepository(
                connection,
                tenant_a,
                workspace_id=workspace,
            )
            period = repository.create_period(
                group_code=worksheet.group_code,
                period_id=worksheet.period_id,
                reporting_currency=worksheet.reporting_currency,
                period_start_date=worksheet.period_start_date,
                period_end_date=worksheet.period_end_date,
                reporting_date=worksheet.reporting_date,
                workspace=workspace,
                actor_label=worksheet.prepared_by,
            )
            run = repository.prepare_run(
                run_number="RUN-HTTP-001",
                worksheet=worksheet,
                workspace=workspace,
                actor_label=worksheet.prepared_by,
            )

        app = create_api_app(
            tmp_path / "unused.db",
            tenant_db_root=root,
            postgres_dsn=dsn,
            postgres_require_tls=False,
        )
        with TestClient(app) as client:
            headers = {
                "X-ReconForge-Tenant": tenant_a,
                "X-ReconForge-Workspace": workspace,
                "Authorization": f"Bearer {credential.token}",
            }
            listed_periods = client.get("/api/v1/consolidation-close/periods", headers=headers)
            assert listed_periods.status_code == 200, listed_periods.text
            assert listed_periods.json()["source"] == {
                "kind": "postgresql-consolidation-close",
                "server_mode": True,
            }
            assert [item["id"] for item in listed_periods.json()["periods"]] == [period["id"]]

            listed_runs = client.get("/api/v1/consolidation-close/runs", headers=headers)
            assert listed_runs.status_code == 200, listed_runs.text
            assert [item["id"] for item in listed_runs.json()["runs"]] == [run["id"]]

            detail = client.get(f"/api/v1/consolidation-close/runs/{run['id']}", headers=headers)
            assert detail.status_code == 200, detail.text
            assert detail.json()["source"] == {
                "kind": "postgresql-consolidation-close",
                "server_mode": True,
            }
            assert detail.json()["run"]["worksheet"]["worksheet_id"] == worksheet.worksheet_id
            assert detail.json()["run"]["journal_lines"]
            assert detail.json()["run"]["translation_evidence"]["result_digest"]

            denied_workspace = client.get(
                "/api/v1/consolidation-close/periods",
                params={"workspace": "other-workspace"},
                headers=headers,
            )
            assert denied_workspace.status_code == 403

            cross_tenant = client.get(
                "/api/v1/consolidation-close/periods",
                headers={
                    "X-ReconForge-Tenant": tenant_b,
                    "X-ReconForge-Workspace": workspace,
                    "Authorization": f"Bearer {credential.token}",
                },
            )
            assert cross_tenant.status_code == 401
    finally:
        if admin is not None:
            try:
                with admin.transaction():
                    for table in (
                        "consolidation_close_effect_lines",
                        "consolidation_close_effects",
                        "consolidation_close_run_lines",
                        "consolidation_close_period_events",
                        "consolidation_close_runs",
                        "consolidation_close_periods",
                    ):
                        admin.execute(f"ALTER TABLE reconforge.{table} DISABLE TRIGGER ALL")
                    admin.execute("ALTER TABLE reconforge.principal_scope_grants DISABLE TRIGGER ALL")
                    admin.execute("ALTER TABLE reconforge.service_account_events DISABLE TRIGGER ALL")
                    for table in (
                        "consolidation_close_effect_lines",
                        "consolidation_close_effects",
                        "consolidation_close_run_lines",
                        "consolidation_close_period_events",
                        "consolidation_close_runs",
                        "consolidation_close_periods",
                        "principal_scope_grants",
                        "service_account_events",
                        "service_account_credentials",
                        "service_account_permissions",
                        "service_accounts",
                        "identity_permissions",
                        "domain_workspaces",
                    ):
                        admin.execute(
                            f"DELETE FROM reconforge.{table} WHERE tenant_id IN (%s, %s)",
                            (tenant_a, tenant_b),
                        )
                    admin.execute("DELETE FROM reconforge.tenants WHERE id IN (%s, %s)", (tenant_a, tenant_b))
                    for table in (
                        "consolidation_close_effect_lines",
                        "consolidation_close_effects",
                        "consolidation_close_run_lines",
                        "consolidation_close_period_events",
                        "consolidation_close_runs",
                        "consolidation_close_periods",
                    ):
                        admin.execute(f"ALTER TABLE reconforge.{table} ENABLE TRIGGER ALL")
                    admin.execute("ALTER TABLE reconforge.principal_scope_grants ENABLE TRIGGER ALL")
                    admin.execute("ALTER TABLE reconforge.service_account_events ENABLE TRIGGER ALL")
            finally:
                admin.close()


@pytest.mark.skipif(not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"), reason="requires live PostgreSQL")
def test_live_server_consolidation_close_http_lifecycle_is_alembic_head_maker_checker_and_rls(
    tmp_path: Path,
) -> None:
    """Exercise the authenticated close lifecycle over the supported migration path."""

    pytest.importorskip("psycopg")
    from alembic.config import Config

    from alembic import command
    from reconforge.infrastructure.postgres_identity import PostgresIdentityRepository
    from tests.test_sqlite_consolidation_close import _worksheet

    dsn = os.environ["RECONFORGE_TEST_POSTGRES_DSN"]
    admin_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN", dsn)
    app_user = os.environ.get("RECONFORGE_TEST_POSTGRES_APP_USER", "")
    if not app_user:
        pytest.skip("requires a non-privileged application role")
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", app_user):
        pytest.fail("RECONFORGE_TEST_POSTGRES_APP_USER contains unsafe characters")

    token = uuid4().hex[:8]
    tenant_a = f"close_api_a_{token}"
    tenant_b = f"close_api_b_{token}"
    workspace = f"close-workspace-{token}"
    root = tmp_path / "tenants"
    root.mkdir()
    run_migrations(root / f"{tenant_a}.db")
    run_migrations(root / f"{tenant_b}.db")
    admin_factory = PostgresConnectionFactory(PostgresSettings(dsn=admin_dsn, require_tls=False))
    app_factory = PostgresConnectionFactory(PostgresSettings(dsn=dsn, require_tls=False))
    admin = None
    try:
        admin = admin_factory.connect()
        previous_migration_dsn = os.environ.get("RECONFORGE_POSTGRES_DSN")
        os.environ["RECONFORGE_POSTGRES_DSN"] = admin_dsn
        try:
            command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
        finally:
            if previous_migration_dsn is None:
                os.environ.pop("RECONFORGE_POSTGRES_DSN", None)
            else:
                os.environ["RECONFORGE_POSTGRES_DSN"] = previous_migration_dsn

        with admin.transaction():
            admin.execute(f"GRANT USAGE ON SCHEMA reconforge TO {app_user}")
            admin.execute(
                f"GRANT SELECT, INSERT, UPDATE, DELETE ON reconforge.tenants, "
                f"reconforge.identity_roles, reconforge.identity_permissions, reconforge.identity_users, "
                f"reconforge.identity_user_roles, reconforge.identity_role_permissions, "
                f"reconforge.identity_sessions, reconforge.identity_step_up_assertions, "
                f"reconforge.emergency_access_requests, reconforge.emergency_access_permissions, "
                f"reconforge.emergency_access_events, reconforge.domain_workspaces, "
                f"reconforge.principal_scope_grants, reconforge.domain_audit_ledger_state, "
                f"reconforge.domain_audit_events, reconforge.outbox_events TO {app_user}"
            )
            admin.execute(
                f"GRANT SELECT, INSERT, UPDATE ON reconforge.consolidation_close_periods, "
                f"reconforge.consolidation_close_runs, reconforge.consolidation_close_run_lines, "
                f"reconforge.consolidation_close_period_events, reconforge.consolidation_close_effects, "
                f"reconforge.consolidation_close_effect_lines TO {app_user}"
            )
            admin.execute(
                f"GRANT SELECT ON reconforge.consolidation_close_intercompany_links, "
                f"reconforge.consolidation_close_impairment_links, "
                f"reconforge.consolidation_close_deferred_tax_links, "
                f"reconforge.consolidation_close_ppa_links, "
                f"reconforge.consolidation_close_ownership_change_links, "
                f"reconforge.intercompany_elimination_artifacts, "
                f"reconforge.consolidation_impairment_artifacts, "
                f"reconforge.consolidation_deferred_tax_artifacts, "
                f"reconforge.consolidation_ppa_artifacts, "
                f"reconforge.consolidation_ownership_change_artifacts TO {app_user}"
            )
            admin.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA reconforge TO {app_user}")
            admin.execute(
                "INSERT INTO reconforge.tenants(id,name) VALUES (%s,%s),(%s,%s)",
                (tenant_a, tenant_a, tenant_b, tenant_b),
            )
            admin.execute(
                "INSERT INTO reconforge.domain_workspaces(tenant_id,id,name) VALUES (%s,%s,%s)",
                (tenant_a, workspace, "Close lifecycle workspace"),
            )

        with PostgresTenantBoundary(app_factory).transaction(tenant_a, workspace_id=workspace) as connection:
            identity = PostgresIdentityRepository(connection)
            identity.create_role(tenant_id=tenant_a, role_name="Admin")
            for permission_name in ("finance_core.read", "finance_core.manage", "finance_core.validate"):
                identity.create_permission(tenant_id=tenant_a, permission_name=permission_name)
                identity.grant_permission(
                    tenant_id=tenant_a,
                    role_name="admin",
                    permission_name=permission_name,
                )
            for user_id, username in (
                ("api-preparer", "preparer"),
                ("api-reviewer", "reviewer"),
                ("api-poster", "poster"),
                ("api-reversal-reviewer", "reversal-reviewer"),
            ):
                identity.create_user(
                    tenant_id=tenant_a,
                    user_id=user_id,
                    username=username,
                    password="Strong-password-123",
                    role_name="admin",
                )
            scope_authority = PostgresScopeAuthorityRepository(connection)
            for user_id, suffix in (
                ("api-preparer", "preparer"),
                ("api-reviewer", "reviewer"),
                ("api-poster", "poster"),
                ("api-reversal-reviewer", "reversal-reviewer"),
            ):
                scope_authority.grant(
                    tenant_id=tenant_a,
                    grant_id=f"close-api-workspace-{suffix}-{token}",
                    principal_type="user",
                    principal_id=user_id,
                    scope_type="workspace",
                    scope_id=workspace,
                    actor_id="api-preparer",
                )

        app = create_api_app(
            tmp_path / "unused.db",
            tenant_db_root=root,
            postgres_dsn=dsn,
            postgres_require_tls=False,
        )
        with TestClient(app) as client:
            base = {"X-ReconForge-Tenant": tenant_a, "X-ReconForge-Workspace": workspace}

            def login(username: str) -> dict[str, str]:
                response = client.post(
                    "/api/v1/auth/login",
                    headers=base,
                    json={"username": username, "password": "Strong-password-123"},
                )
                assert response.status_code == 200, response.text
                headers = {**base, "Authorization": f"Bearer {response.json()['access_token']}"}
                step_up = client.post(
                    "/api/v1/auth/step-up",
                    headers=headers,
                    json={"password": "Strong-password-123"},
                )
                assert step_up.status_code == 200, step_up.text
                assert step_up.json()["method"] == "password_reauthentication"
                return headers

            preparer = login("preparer")
            reviewer = login("reviewer")
            poster = login("poster")
            reversal_reviewer = login("reversal-reviewer")

            period_payload = {
                "group_code": "GLOBAL-GROUP",
                "period_id": "2026-08",
                "reporting_currency": "USD",
                "period_start_date": "2026-08-01",
                "period_end_date": "2026-08-31",
                "reporting_date": "2026-08-01",
                "workspace": workspace,
            }
            created_period = client.post(
                "/api/v1/consolidation-close/periods", headers=preparer, json=period_payload
            )
            assert created_period.status_code == 200, created_period.text
            period_id = created_period.json()["period"]["id"]
            replay_period = client.post(
                "/api/v1/consolidation-close/periods", headers=preparer, json=period_payload
            )
            assert replay_period.status_code == 200, replay_period.text
            assert replay_period.json()["period"]["id"] == period_id

            worksheet = prepare_consolidation_worksheet(
                replace(_worksheet().request, prepared_by="api-preparer")
            )
            prepared = client.post(
                "/api/v1/consolidation-close/runs",
                headers=preparer,
                json={"run_number": "RUN-ALEMBIC-001", "workspace": workspace, "worksheet": worksheet.to_dict()},
            )
            assert prepared.status_code == 200, prepared.text
            run_id = prepared.json()["run"]["id"]
            assert prepared.json()["run"]["status"] == "Prepared"

            self_approval = client.post(
                f"/api/v1/consolidation-close/runs/{run_id}/approve",
                headers=preparer,
                json={"expected_version": 1, "reason": "Self approval must fail."},
            )
            assert self_approval.status_code in {400, 403}

            approved = client.post(
                f"/api/v1/consolidation-close/runs/{run_id}/approve",
                headers=reviewer,
                json={"expected_version": 1, "reason": "Independent worksheet review."},
            )
            assert approved.status_code == 200, approved.text
            assert approved.json()["run"]["status"] == "Approved"

            posted = client.post(
                f"/api/v1/consolidation-close/runs/{run_id}/post",
                headers=poster,
                json={"expected_version": 2, "reason": "Control journal posting approved."},
            )
            assert posted.status_code == 200, posted.text
            assert posted.json()["run"]["status"] == "Posted"

            reversal_requested = client.post(
                f"/api/v1/consolidation-close/runs/{run_id}/reversal/request",
                headers=poster,
                json={"expected_version": 3, "reason": "Synthetic reversal request."},
            )
            assert reversal_requested.status_code == 200, reversal_requested.text
            assert reversal_requested.json()["run"]["status"] == "ReversalPrepared"

            reversed_run = client.post(
                f"/api/v1/consolidation-close/runs/{run_id}/reversal/approve",
                headers=reversal_reviewer,
                json={"expected_version": 4, "reason": "Independent reversal approval."},
            )
            assert reversed_run.status_code == 200, reversed_run.text
            assert reversed_run.json()["run"]["status"] == "Reversed"

            locked = client.post(
                f"/api/v1/consolidation-close/periods/{period_id}/lock",
                headers=reviewer,
                json={"expected_version": 1, "reason": "Close period locked."},
            )
            assert locked.status_code == 200, locked.text
            assert locked.json()["period"]["status"] == "Locked"

            reopened = client.post(
                f"/api/v1/consolidation-close/periods/{period_id}/reopen",
                headers=preparer,
                json={"expected_version": 2, "reason": "Independent reopen review."},
            )
            assert reopened.status_code == 200, reopened.text
            assert reopened.json()["period"]["status"] == "Reopened"

            detail = client.get(f"/api/v1/consolidation-close/runs/{run_id}", headers=preparer)
            assert detail.status_code == 200, detail.text
            assert detail.json()["source"] == {
                "kind": "postgresql-consolidation-close",
                "server_mode": True,
            }
            assert detail.json()["run"]["status"] == "Reversed"
            assert detail.json()["run"]["journal_lines"]
            assert detail.json()["run"]["effects"]

            denied_workspace = client.get(
                "/api/v1/consolidation-close/periods",
                params={"workspace": "sibling-workspace"},
                headers=preparer,
            )
            assert denied_workspace.status_code == 403
            cross_tenant = client.get(
                "/api/v1/consolidation-close/periods",
                headers={
                    "X-ReconForge-Tenant": tenant_b,
                    "X-ReconForge-Workspace": workspace,
                    "Authorization": preparer["Authorization"],
                },
            )
            assert cross_tenant.status_code == 401
    finally:
        if admin is not None:
            try:
                with admin.transaction():
                    tables = (
                        "consolidation_close_effect_lines",
                        "consolidation_close_effects",
                        "consolidation_close_run_lines",
                        "consolidation_close_period_events",
                        "consolidation_close_runs",
                        "consolidation_close_periods",
                        "principal_scope_grants",
                        "identity_step_up_assertions",
                        "identity_sessions",
                        "identity_user_roles",
                        "identity_role_permissions",
                        "identity_users",
                        "identity_permissions",
                        "identity_roles",
                        "emergency_access_events",
                        "emergency_access_permissions",
                        "emergency_access_requests",
                        "domain_audit_events",
                        "domain_audit_ledger_state",
                        "outbox_events",
                        "domain_workspaces",
                    )
                    for table in tables:
                        admin.execute(f"ALTER TABLE reconforge.{table} DISABLE TRIGGER ALL")
                    for table in tables:
                        admin.execute(
                            f"DELETE FROM reconforge.{table} WHERE tenant_id IN (%s, %s)",
                            (tenant_a, tenant_b),
                        )
                    admin.execute("DELETE FROM reconforge.tenants WHERE id IN (%s, %s)", (tenant_a, tenant_b))
                    for table in tables:
                        admin.execute(f"ALTER TABLE reconforge.{table} ENABLE TRIGGER ALL")
            finally:
                admin.close()
