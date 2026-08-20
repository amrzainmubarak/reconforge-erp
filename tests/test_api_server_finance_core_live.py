from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest
from starlette.requests import Request

from reconforge.api import create_api_app, server_finance_core
from reconforge.api.errors import APIError
from reconforge.api.routes import finance_core as routes
from reconforge.api.server_identity import RequestExecutionScope
from reconforge.auth.models import LocalUser
from reconforge.db import run_migrations
from reconforge.infrastructure.postgres import (
    PostgresConnectionFactory,
    PostgresSettings,
    PostgresTenantBoundary,
    install_postgres_rls_schema,
)
from reconforge.infrastructure.postgres_domain import install_postgres_domain_schema
from reconforge.infrastructure.postgres_finance_core import install_postgres_finance_core_schema
from reconforge.infrastructure.postgres_master_data import (
    POSTGRES_FISCAL_PERIOD_SCHEMA_SQL,
    POSTGRES_MASTER_DATA_SCHEMA_SQL,
    PostgresMasterDataRepository,
)


@pytest.mark.skipif(not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"), reason="requires live PostgreSQL")
def test_live_server_finance_core_api_routes_are_workspace_scoped_and_lifecycle_exact(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    psycopg = pytest.importorskip("psycopg")
    dsn = os.environ["RECONFORGE_TEST_POSTGRES_DSN"]
    admin_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN", dsn)
    app_user = os.environ.get("RECONFORGE_TEST_POSTGRES_APP_USER", "")
    if not app_user:
        pytest.skip("requires a non-privileged application role")
    tenant_a = f"api_finance_a_{uuid4().hex[:8]}"
    tenant_b = f"api_finance_b_{uuid4().hex[:8]}"
    workspace_a = "workspace-api-a"
    workspace_b = "workspace-api-b"
    root = tmp_path / "tenants"
    root.mkdir()
    run_migrations(root / f"{tenant_a}.db")
    run_migrations(root / f"{tenant_b}.db")
    factory = PostgresConnectionFactory(PostgresSettings(dsn=dsn, require_tls=False))
    admin_factory = PostgresConnectionFactory(PostgresSettings(dsn=admin_dsn, require_tls=False))
    admin = admin_factory.connect()
    try:
        with admin.transaction():
            install_postgres_rls_schema(admin)
            install_postgres_domain_schema(admin)
            admin.execute(POSTGRES_MASTER_DATA_SCHEMA_SQL)
            admin.execute(POSTGRES_FISCAL_PERIOD_SCHEMA_SQL)
            install_postgres_finance_core_schema(admin)
            admin.execute(f"GRANT USAGE ON SCHEMA reconforge TO {app_user}")
            tables = (
                "tenants,organizations,currencies,legal_entities,fiscal_periods,domain_workspaces,"
                "domain_audit_ledger_state,domain_audit_events,outbox_events,finance_charts,finance_accounts,"
                "finance_dimensions,finance_dimension_values,finance_journals,finance_entries,"
                "finance_entry_lines,finance_entry_line_dimensions"
            )
            admin.execute(
                f"GRANT SELECT,INSERT,UPDATE,DELETE ON reconforge.{tables.replace(',', ',reconforge.')} TO {app_user}"
            )
            admin.execute(
                "INSERT INTO reconforge.tenants(id,name) VALUES (%s,%s),(%s,%s)",
                (tenant_a, tenant_a, tenant_b, tenant_b),
            )
        for tenant, workspace in ((tenant_a, workspace_a), (tenant_b, workspace_b)):
            with PostgresTenantBoundary(factory).transaction(tenant) as connection:
                connection.execute(
                    "INSERT INTO reconforge.domain_workspaces(tenant_id,id,name) VALUES (%s,%s,'Finance')",
                    (tenant, workspace),
                )
                master = PostgresMasterDataRepository(connection)
                master.upsert_currency(tenant_id=tenant, code="USD", name="US Dollar", minor_units=2)
                master.upsert_organization(
                    tenant_id=tenant,
                    organization_id=f"org-{tenant}",
                    organization_code="ORG-A",
                    name="API Organization",
                    base_currency="USD",
                )
                master.upsert_legal_entity(
                    tenant_id=tenant,
                    organization_id=f"org-{tenant}",
                    entity_id=f"entity-{tenant}",
                    entity_code="ENTITY-A",
                    name="API Entity",
                    currency_code="USD",
                )
                master.upsert_period(
                    tenant_id=tenant,
                    period_id="period-api",
                    name="2026-07",
                    start_date="2026-07-01",
                    end_date="2026-07-31",
                    fiscal_year=2026,
                    period_number=7,
                )

        app = create_api_app(
            tmp_path / "unused.db",
            tenant_db_root=root,
            postgres_dsn=dsn,
            postgres_require_tls=False,
        )
        request = Request(
            {"type": "http", "method": "GET", "path": "/api/v1/finance-core", "headers": [], "app": app}
        )
        scope = RequestExecutionScope(tenant_a, workspace_a, f"org-{tenant_a}", f"entity-{tenant_a}")
        monkeypatch.setattr(routes, "request_execution_scope", lambda _request: scope)
        monkeypatch.setattr(server_finance_core, "request_execution_scope", lambda _request: scope)
        monkeypatch.setattr(routes, "enforce_server_scoped_permission", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(routes, "enforce_server_scoped_permissions", lambda *_args, **_kwargs: None)
        maker = LocalUser(id="maker", username="maker", display_name="Maker")
        checker = LocalUser(id="checker", username="checker", display_name="Checker")

        chart = routes.upsert_chart(
            request,
            routes.ChartRequest(chart_code="DEFAULT", name="Default", organization_code="ORG-A"),
            maker,
            None,
        )
        assert chart["chart"]["workspace_id"] == workspace_a
        for code, name, account_type, normal_balance in (
            ("1000", "Cash", "Asset", "Debit"),
            ("3000", "Capital", "Equity", "Credit"),
        ):
            assert routes.upsert_account(
                request,
                routes.AccountRequest(
                    account_code=code,
                    name=name,
                    organization_code="ORG-A",
                    account_type=account_type,
                    normal_balance=normal_balance,
                ),
                maker,
                None,
            )["account"]["workspace_id"] == workspace_a
        routes.upsert_journal(
            request,
            routes.JournalRequest(
                journal_code="GENERAL",
                name="General",
                organization_code="ORG-A",
                currency_code="USD",
            ),
            maker,
            None,
        )
        created = routes.create_entry(
            request,
            routes.LedgerEntryRequest(
                entry_number="JE/API/001",
                organization_code="ORG-A",
                entity_code="ENTITY-A",
                period_id="period-api",
                journal_code="GENERAL",
                posting_date="2026-07-23",
                description="Live Finance Core API entry",
                lines=[
                    routes.LedgerLineRequest(account_code="1000", debit="100.00", credit="0"),
                    routes.LedgerLineRequest(account_code="3000", debit="0", credit="100.00"),
                ],
            ),
            maker,
            None,
        )
        entry_id = str(created["entry"]["id"])
        assert entry_id.startswith("GLE-")
        with pytest.raises(APIError) as own_review:
            routes.validate_entry(request, entry_id, routes.ReasonRequest(reason="Self review"), maker, None)
        assert own_review.value.code == "finance_core_request_invalid"
        validated = routes.validate_entry(
            request, entry_id, routes.ReasonRequest(reason="Independent review"), checker, None
        )
        assert validated["entry"]["status"] == "Validated"
        scope_b = RequestExecutionScope(tenant_b, workspace_b, f"org-{tenant_b}", f"entity-{tenant_b}")
        monkeypatch.setattr(routes, "request_execution_scope", lambda _request: scope_b)
        isolated = routes.list_charts(request, checker, None, workspace="default", limit=10, offset=0)
        assert isolated["charts"] == []
    finally:
        try:
            with admin.transaction():
                admin.execute("DELETE FROM reconforge.tenants WHERE id IN (%s,%s)", (tenant_a, tenant_b))
        except psycopg.Error:
            pass
        admin.close()
