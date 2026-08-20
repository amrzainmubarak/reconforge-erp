from __future__ import annotations

import os
import re
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from reconforge.api import create_api_app
from reconforge.application.bank_statement_control import (
    run_bank_statement_control_files,
    verify_bank_statement_report,
    write_bank_statement_report,
)
from reconforge.db import run_migrations
from reconforge.infrastructure.postgres import (
    PostgresConnectionFactory,
    PostgresSettings,
    PostgresTenantBoundary,
    install_postgres_rls_schema,
)
from reconforge.infrastructure.postgres_bank_statement import POSTGRES_BANK_STATEMENT_SCHEMA_SQL
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
from reconforge.infrastructure.postgres_workspace_attribution import POSTGRES_WORKSPACE_ATTRIBUTION_SCHEMA_SQL

ROOT = Path(__file__).resolve().parents[1]
STATEMENT = ROOT / "examples/bank_statement_control/statement.xml"
LEDGER = ROOT / "examples/bank_statement_control/ledger.json"


def _report(tmp_path: Path) -> dict[str, object]:
    path = tmp_path / "bank-http-report.json"
    run = run_bank_statement_control_files(STATEMENT, LEDGER, currency="EUR", tolerance="0.01")
    write_bank_statement_report(run, path)
    return verify_bank_statement_report(path)


def test_local_bank_statement_server_profile_refuses_sqlite_fallback(tmp_path: Path) -> None:
    db_path = tmp_path / "local.db"
    run_migrations(db_path)
    app = create_api_app(db_path, postgres_dsn="postgresql://identity.example/postgres", tenant_db_root=tmp_path / "tenants")
    assert app.state.postgres_bank_statement_factory is not None


@pytest.mark.skipif(not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"), reason="requires live PostgreSQL")
def test_live_server_bank_statement_http_routes_are_rls_scoped(tmp_path: Path) -> None:
    pytest.importorskip("psycopg")
    dsn = os.environ["RECONFORGE_TEST_POSTGRES_DSN"]
    admin_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN", dsn)
    app_user = os.environ.get("RECONFORGE_TEST_POSTGRES_APP_USER", "")
    if not app_user:
        pytest.skip("requires a non-privileged application role")
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", app_user):
        pytest.fail("RECONFORGE_TEST_POSTGRES_APP_USER contains unsafe characters")
    tenant_a = "bank_http_a_" + uuid4().hex[:8]
    tenant_b = "bank_http_b_" + uuid4().hex[:8]
    workspace = "bank-http-workspace"
    root = tmp_path / "tenants"
    root.mkdir()
    run_migrations(root / f"{tenant_a}.db")
    run_migrations(root / f"{tenant_b}.db")
    report = _report(tmp_path)
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
            admin.execute(POSTGRES_WORKSPACE_ATTRIBUTION_SCHEMA_SQL)
            admin.execute(POSTGRES_SCOPE_AUTHORITY_SCHEMA_SQL)
            admin.execute(POSTGRES_BANK_STATEMENT_SCHEMA_SQL)
            admin.execute(f"GRANT USAGE ON SCHEMA reconforge TO {app_user}")
            admin.execute(
                f"GRANT SELECT, INSERT, UPDATE ON reconforge.tenants, reconforge.identity_permissions, "
                f"reconforge.service_accounts, reconforge.service_account_permissions, "
                f"reconforge.service_account_credentials, reconforge.service_account_events TO {app_user}"
            )
            admin.execute(
                f"GRANT SELECT, INSERT ON reconforge.principal_scope_grants, "
                f"reconforge.bank_statement_control_runs TO {app_user}"
            )
            admin.execute(f"GRANT SELECT ON reconforge.domain_workspaces TO {app_user}")
            admin.execute(
                f"GRANT SELECT ON reconforge.organizations, reconforge.currencies, reconforge.legal_entities TO {app_user}"
            )
            admin.execute(
                "INSERT INTO reconforge.tenants(id,name) VALUES (%s,%s),(%s,%s)",
                (tenant_a, tenant_a, tenant_b, tenant_b),
            )
            admin.execute(
                "INSERT INTO reconforge.domain_workspaces(tenant_id,id,name) VALUES (%s,%s,%s)",
                (tenant_a, workspace, "Bank HTTP workspace"),
            )
            admin.execute(
                "INSERT INTO reconforge.identity_permissions(tenant_id,name,description) "
                "VALUES (%s,'finance_core.read','Bank evidence read')",
                (tenant_a,),
            )
        with PostgresTenantBoundary(app_factory).transaction(tenant_a) as connection:
            service_accounts = PostgresServiceAccountRepository(connection)
            service_accounts.create_account(
                tenant_id=tenant_a,
                account_id="svc-bank-http",
                name="bank-http",
                display_name="Bank HTTP reader",
                permissions=frozenset({"finance_core.read"}),
                actor_id="security-admin",
            )
            credential = service_accounts.issue_credential(
                tenant_id=tenant_a, account_id="svc-bank-http", actor_id="security-admin", ttl=timedelta(hours=1)
            )
            PostgresScopeAuthorityRepository(connection).grant(
                tenant_id=tenant_a,
                grant_id="grant-bank-http-workspace",
                principal_type="service_account",
                principal_id="svc-bank-http",
                scope_type="workspace",
                scope_id=workspace,
                actor_id="security-admin",
            )
            from reconforge.infrastructure.postgres_bank_statement import PostgresBankStatementRepository

            PostgresBankStatementRepository(connection).put_payload(
                report, tenant_id=tenant_a, workspace_id=workspace, actor_label="server-fixture"
            )
        app = create_api_app(
            tmp_path / "unused.db", tenant_db_root=root, postgres_dsn=dsn, postgres_require_tls=False
        )
        with TestClient(app) as client:
            headers = {
                "X-ReconForge-Tenant": tenant_a,
                "X-ReconForge-Workspace": workspace,
                "Authorization": f"Bearer {credential.token}",
            }
            listed = client.get("/api/v1/bank/statement-controls", headers=headers)
            assert listed.status_code == 200, listed.text
            assert listed.json()["source"] == {"kind": "postgresql-bank-statement-control", "server_mode": True}
            assert [item["decision_digest"] for item in listed.json()["bank_statements"]] == [report["decision_digest"]]
            digest = str(report["decision_digest"])
            read = client.get(f"/api/v1/bank/statement-controls/{digest}", headers=headers)
            assert read.status_code == 200, read.text
            assert read.json()["bank_statement"]["report"]["artifact_digest"] == report["artifact_digest"]
            assert client.get(
                "/api/v1/bank/statement-controls", params={"workspace": "other-workspace"}, headers=headers
            ).status_code == 403
            assert client.get(
                "/api/v1/bank/statement-controls",
                headers={
                    "X-ReconForge-Tenant": tenant_b,
                    "X-ReconForge-Workspace": workspace,
                    "Authorization": f"Bearer {credential.token}",
                },
            ).status_code == 401
    finally:
        if admin is not None:
            try:
                with admin.transaction():
                    admin.execute("ALTER TABLE reconforge.bank_statement_control_runs DISABLE TRIGGER bank_statement_control_runs_guard")
                    admin.execute("ALTER TABLE reconforge.principal_scope_grants DISABLE TRIGGER principal_scope_grants_guard")
                    admin.execute("ALTER TABLE reconforge.service_account_events DISABLE TRIGGER trg_service_account_events_append_only")
                    for table in (
                        "bank_statement_control_runs",
                        "principal_scope_grants",
                        "service_account_events",
                        "service_account_credentials",
                        "service_account_permissions",
                        "service_accounts",
                        "identity_permissions",
                        "domain_workspaces",
                    ):
                        admin.execute(f"DELETE FROM reconforge.{table} WHERE tenant_id IN (%s, %s)", (tenant_a, tenant_b))
                    admin.execute("DELETE FROM reconforge.tenants WHERE id IN (%s, %s)", (tenant_a, tenant_b))
                    admin.execute("ALTER TABLE reconforge.bank_statement_control_runs ENABLE TRIGGER bank_statement_control_runs_guard")
                    admin.execute("ALTER TABLE reconforge.principal_scope_grants ENABLE TRIGGER principal_scope_grants_guard")
                    admin.execute("ALTER TABLE reconforge.service_account_events ENABLE TRIGGER trg_service_account_events_append_only")
            finally:
                admin.close()
