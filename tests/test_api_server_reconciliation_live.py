from __future__ import annotations

import os
import re
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from reconforge.api import create_api_app
from reconforge.db import run_migrations
from reconforge.infrastructure.postgres import (
    PostgresConnectionFactory,
    PostgresSettings,
    PostgresTenantBoundary,
    install_postgres_rls_schema,
)
from reconforge.infrastructure.postgres_identity import POSTGRES_IDENTITY_SCHEMA_SQL
from reconforge.infrastructure.postgres_master_data import POSTGRES_MASTER_DATA_SCHEMA_SQL
from reconforge.infrastructure.postgres_reconciliation import POSTGRES_RECONCILIATION_SCHEMA_SQL
from reconforge.infrastructure.postgres_scope_authority import (
    POSTGRES_SCOPE_AUTHORITY_SCHEMA_SQL,
    PostgresScopeAuthorityRepository,
)
from reconforge.infrastructure.postgres_service_accounts import (
    POSTGRES_SERVICE_ACCOUNT_SCHEMA_SQL,
    PostgresServiceAccountRepository,
)


@pytest.mark.skipif(not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"), reason="requires live PostgreSQL")
def test_live_server_reconciliation_http_routes_are_rls_scoped(tmp_path: Path) -> None:
    """Exercise the real PostgreSQL reconciliation API boundary over HTTP."""

    pytest.importorskip("psycopg")
    dsn = os.environ["RECONFORGE_TEST_POSTGRES_DSN"]
    admin_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN", dsn)
    app_user = os.environ.get("RECONFORGE_TEST_POSTGRES_APP_USER", "")
    if not app_user:
        pytest.skip("requires a non-privileged application role")
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", app_user):
        pytest.fail("RECONFORGE_TEST_POSTGRES_APP_USER contains unsafe characters")

    tenant_a = "recon_http_a_" + uuid4().hex[:8]
    tenant_b = "recon_http_b_" + uuid4().hex[:8]
    workspace = "reconciliation-http-workspace"
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
            admin.execute(POSTGRES_MASTER_DATA_SCHEMA_SQL)
            admin.execute(POSTGRES_SCOPE_AUTHORITY_SCHEMA_SQL)
            admin.execute(POSTGRES_RECONCILIATION_SCHEMA_SQL)
            admin.execute(f"GRANT USAGE ON SCHEMA reconforge TO {app_user}")
            admin.execute(
                f"GRANT SELECT, INSERT, UPDATE ON reconforge.tenants, reconforge.identity_permissions, "
                f"reconforge.service_accounts, reconforge.service_account_permissions, "
                f"reconforge.service_account_credentials, reconforge.service_account_events TO {app_user}"
            )
            admin.execute(
                f"GRANT SELECT, INSERT, UPDATE ON reconforge.principal_scope_grants, "
                f"reconforge.reconciliation_runs, reconforge.reconciliation_inputs, "
                f"reconforge.reconciliation_results, reconforge.reconciliation_exceptions, "
                f"reconforge.reconciliation_execution_checkpoints TO {app_user}"
            )
            admin.execute(
                f"GRANT SELECT, INSERT, UPDATE ON reconforge.audit_events, reconforge.outbox_events TO {app_user}"
            )
            admin.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA reconforge TO {app_user}")
            admin.execute(f"GRANT SELECT ON reconforge.domain_workspaces TO {app_user}")
            admin.execute(
                "INSERT INTO reconforge.tenants(id,name) VALUES (%s,%s),(%s,%s)",
                (tenant_a, tenant_a, tenant_b, tenant_b),
            )
            admin.execute(
                "INSERT INTO reconforge.domain_workspaces(tenant_id,id,name) VALUES (%s,%s,%s)",
                (tenant_a, workspace, "Reconciliation HTTP workspace"),
            )
            admin.execute(
                "INSERT INTO reconforge.identity_permissions(tenant_id,name,description) VALUES "
                "(%s,'reconciliation.read','Reconciliation evidence read'), "
                "(%s,'reconciliation.manage','Reconciliation run management')",
                (tenant_a, tenant_a),
            )

        with PostgresTenantBoundary(app_factory).transaction(tenant_a, workspace_id=workspace) as connection:
            service_accounts = PostgresServiceAccountRepository(connection)
            service_accounts.create_account(
                tenant_id=tenant_a,
                account_id="svc-reconciliation-http",
                name="reconciliation-http",
                display_name="Reconciliation HTTP operator",
                permissions=frozenset({"reconciliation.read", "reconciliation.manage"}),
                actor_id="security-admin",
            )
            credential = service_accounts.issue_credential(
                tenant_id=tenant_a,
                account_id="svc-reconciliation-http",
                actor_id="security-admin",
                ttl=timedelta(hours=1),
            )
            PostgresScopeAuthorityRepository(connection).grant(
                tenant_id=tenant_a,
                grant_id="grant-reconciliation-http-workspace",
                principal_type="service_account",
                principal_id="svc-reconciliation-http",
                scope_type="workspace",
                scope_id=workspace,
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
            "X-ReconForge-Workspace": workspace,
            "Authorization": f"Bearer {credential.token}",
        }
        payload = {
            "run_id": "run-http-001",
            "name": "Bank to GL HTTP control",
            "left_source": "bank.csv",
            "right_source": "gl.csv",
            "algorithm_version": "global-assignment-v1",
            "rule": {"amount_tolerance": "0.01"},
            "input_hash": "a" * 64,
            "inputs": [
                {
                    "side": "Left",
                    "source_id": "bank-001",
                    "record_hash": "b" * 64,
                    "amount": "10.00",
                    "currency_code": "USD",
                    "reference_normalized": "INV-1",
                },
                {
                    "side": "Right",
                    "source_id": "ledger-001",
                    "record_hash": "c" * 64,
                    "amount": "10.00",
                    "currency_code": "USD",
                    "reference_normalized": "INV-1",
                },
            ],
        }

        with TestClient(app) as client:
            submitted = client.post(
                "/api/v1/reconciliations/runs",
                headers={**headers, "Idempotency-Key": "reconciliation-http-submit-1"},
                json=payload,
            )
            assert submitted.status_code == 202, submitted.text
            assert submitted.json()["source"] == {
                "kind": "postgresql-reconciliation-results",
                "server_mode": True,
            }
            assert submitted.json()["run"]["id"] == payload["run_id"]
            assert submitted.json()["input_count"] == 2

            listed = client.get("/api/v1/reconciliations/runs", headers=headers)
            assert listed.status_code == 200, listed.text
            assert [item["id"] for item in listed.json()["runs"]] == [payload["run_id"]]
            assert listed.json()["source"]["server_mode"] is True

            detail = client.get(f"/api/v1/reconciliations/runs/{payload['run_id']}", headers=headers)
            assert detail.status_code == 200, detail.text
            assert detail.json()["run"]["rule_json"]["amount_tolerance"] == "0.01"

            inputs = client.get(f"/api/v1/reconciliations/runs/{payload['run_id']}/inputs", headers=headers)
            assert inputs.status_code == 200, inputs.text
            assert [item["source_id"] for item in inputs.json()["inputs"]] == ["bank-001", "ledger-001"]
            assert all(Decimal(item["amount_decimal"]) == Decimal("10.00") for item in inputs.json()["inputs"])
            assert all(isinstance(item["amount_decimal"], str) for item in inputs.json()["inputs"])

            denied_workspace = client.get(
                "/api/v1/reconciliations/runs",
                headers={**headers, "X-ReconForge-Workspace": "other-workspace"},
            )
            assert denied_workspace.status_code == 403

            cross_tenant = client.get(
                "/api/v1/reconciliations/runs",
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
                        "reconciliation_execution_checkpoints",
                        "reconciliation_exceptions",
                        "reconciliation_results",
                        "reconciliation_inputs",
                        "reconciliation_runs",
                        "principal_scope_grants",
                        "service_account_events",
                    ):
                        admin.execute(f"ALTER TABLE reconforge.{table} DISABLE TRIGGER ALL")
                    for table in (
                        "reconciliation_execution_checkpoints",
                        "reconciliation_exceptions",
                        "reconciliation_results",
                        "reconciliation_inputs",
                        "reconciliation_runs",
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
                        "reconciliation_execution_checkpoints",
                        "reconciliation_exceptions",
                        "reconciliation_results",
                        "reconciliation_inputs",
                        "reconciliation_runs",
                        "principal_scope_grants",
                        "service_account_events",
                    ):
                        admin.execute(f"ALTER TABLE reconforge.{table} ENABLE TRIGGER ALL")
            finally:
                admin.close()
