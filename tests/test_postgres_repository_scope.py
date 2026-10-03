"""Financial adapters must preserve the authority of the caller's transaction."""
from __future__ import annotations

import os
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest

from reconforge.infrastructure.postgres import (
    PostgresRuntimePooledConnectionFactory,
    PostgresSettings,
    PostgresTenantBoundary,
)
from reconforge.infrastructure.postgres_finance_core import PostgresFinanceCoreError, PostgresFinanceCoreRepository
from reconforge.infrastructure.postgres_inventory_core import PostgresInventoryCoreRepository
from reconforge.infrastructure.postgres_inventory_planning import PostgresInventoryPlanningRepository
from reconforge.infrastructure.postgres_inventory_valuation import PostgresInventoryValuationRepository
from reconforge.infrastructure.postgres_inventory_valuation_reversal import PostgresInventoryValuationReversalRepository
from reconforge.infrastructure.postgres_master_data_application import PostgresMasterDataApplicationRepository
from reconforge.infrastructure.postgres_payables import PostgresPayablesRepository
from reconforge.infrastructure.postgres_receivables import PostgresReceivablesRepository
from reconforge.infrastructure.postgres_repository_scope import (
    PostgresRepositoryScopeError,
    ensure_repository_tenant_scope,
)
from reconforge.platform.common import PlatformError
from tests.test_alembic_postgres import isolated_postgres_migration_dsn as _isolated_postgres_migration_dsn

isolated_postgres_migration_dsn = _isolated_postgres_migration_dsn


class _ScopeConnection:
    def __init__(self, values: tuple[object, ...] | None) -> None:
        self.values = values
        self.statements: list[tuple[str, object]] = []

    def execute(self, statement: str, parameters: object = ()) -> _ScopeConnection:
        self.statements.append((statement, parameters))
        return self

    def fetchone(self) -> tuple[object, ...] | None:
        return self.values


def test_repository_scope_initializes_only_a_completely_unbound_transaction() -> None:
    connection = _ScopeConnection((None, "", None, "", ""))
    ensure_repository_tenant_scope(connection, "tenant_a")
    writes = [(statement, parameters) for statement, parameters in connection.statements if "set_config" in statement]
    assert len(connection.statements) == 6
    assert len(writes) == 5
    assert writes[0][1] == ("tenant_a",)
    assert all(parameters == ("",) for _statement, parameters in writes[1:])


def test_repository_scope_preserves_every_value_and_rechecks_each_call() -> None:
    connection = _ScopeConnection(("tenant_a", "org", "workspace", "entity", "entity"))
    ensure_repository_tenant_scope(connection, "tenant_a")
    assert len(connection.statements) == 1
    connection.values = ("tenant_b", "org", "workspace", "entity", "entity")
    with pytest.raises(PostgresRepositoryScopeError, match="does not match"):
        ensure_repository_tenant_scope(connection, "tenant_a")
    assert len(connection.statements) == 2
    assert all("set_config" not in statement for statement, _parameters in connection.statements)


@pytest.mark.parametrize("values", (
    None,
    (None, None, "stale_workspace", None, None),
    (None, "stale_org", None, None, None),
    ("tenant_a", "org", "workspace", "entity", "other_entity"),
    ("tenant_a", "org", "workspace", "entity", None),
    ("tenant_a", "org", "workspace", None, "entity"),
    ("tenant_a", None, "workspace", "entity", "entity"),
    ("tenant_a", "org", "../workspace", None, None),
    ("tenant_a", "org", "workspace", None),
))
def test_repository_scope_rejects_partial_or_inconsistent_state_without_mutation(values: Any) -> None:
    connection = _ScopeConnection(values)
    with pytest.raises(PostgresRepositoryScopeError, match="repository scope"):
        ensure_repository_tenant_scope(connection, "tenant_a")
    assert len(connection.statements) == 1
    assert "set_config" not in connection.statements[0][0]


def _scope(connection: Any) -> tuple[object, ...]:
    return tuple(connection.execute(
        "SELECT current_setting('app.tenant_id',true),current_setting('app.organization_id',true),"
        "current_setting('app.workspace_id',true),current_setting('app.legal_entity_id',true),"
        "current_setting('app.entity_id',true)"
    ).fetchone())


def _visible(connection: Any) -> tuple[list[str], list[str], list[str]]:
    return (
        [str(row[0]) for row in connection.execute("SELECT id FROM reconforge.domain_workspaces ORDER BY id")],
        [str(row[0]) for row in connection.execute("SELECT id FROM reconforge.organizations ORDER BY id")],
        [str(row[0]) for row in connection.execute("SELECT id FROM reconforge.legal_entities ORDER BY id")],
    )


@pytest.fixture
def scoped_financial_database(isolated_postgres_migration_dsn: str):
    import psycopg
    from alembic.config import Config

    from alembic import command

    app_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_DSN")
    if not app_dsn:
        pytest.skip("requires a nonowner PostgreSQL application DSN")
    command.upgrade(Config(str(Path("alembic.ini").resolve())), "head")
    params = psycopg.conninfo.conninfo_to_dict(app_dsn)
    params["dbname"] = psycopg.conninfo.conninfo_to_dict(isolated_postgres_migration_dsn)["dbname"]
    with psycopg.connect(isolated_postgres_migration_dsn, autocommit=True) as admin:
        role = psycopg.sql.Identifier(params["user"])
        admin.execute(psycopg.sql.SQL("GRANT USAGE ON SCHEMA reconforge TO {}").format(role))
        admin.execute(psycopg.sql.SQL("GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA reconforge TO {}").format(role))
        admin.execute(psycopg.sql.SQL("GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA reconforge TO {}").format(role))
        for tenant, suffixes in (("scope_a", ("one", "two")), ("scope_b", ("foreign",))):
            admin.execute("INSERT INTO reconforge.tenants(id,name) VALUES (%s,%s)", (tenant, tenant))
            admin.execute("INSERT INTO reconforge.currencies(tenant_id,code,name,minor_units) VALUES(%s,'EGP','Synthetic',2)", (tenant,))
            for suffix in suffixes:
                admin.execute("INSERT INTO reconforge.domain_workspaces(tenant_id,id,name) VALUES(%s,%s,%s)", (tenant, f"ws_{suffix}", suffix.title()))
                admin.execute(
                    "INSERT INTO reconforge.organizations(tenant_id,id,organization_code,name,base_currency,application_workspace_id) VALUES(%s,%s,%s,%s,'EGP',%s)",
                    (tenant, f"org_{suffix}", suffix.upper(), suffix.title(), f"ws_{suffix}"),
                )
                admin.execute(
                    "INSERT INTO reconforge.master_data_workspace_organizations(tenant_id,workspace_id,organization_id) VALUES(%s,%s,%s)",
                    (tenant, f"ws_{suffix}", f"org_{suffix}"),
                )
                admin.execute(
                    "INSERT INTO reconforge.legal_entities(tenant_id,id,organization_id,entity_code,name,currency_code) VALUES(%s,%s,%s,%s,%s,'EGP')",
                    (tenant, f"entity_{suffix}", f"org_{suffix}", suffix.upper(), suffix.title()),
                )
    factory = PostgresRuntimePooledConnectionFactory(
        PostgresSettings(dsn=psycopg.conninfo.make_conninfo(**params), require_tls=False), max_size=1,
    )
    try:
        boundary = PostgresTenantBoundary(factory)
        for tenant, suffixes in (("scope_a", ("one", "two")), ("scope_b", ("foreign",))):
            with boundary.transaction(tenant) as connection:
                assert tuple(connection.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone()) == (False, False)
                for suffix in suffixes:
                    PostgresFinanceCoreRepository(connection, tenant).upsert_chart(
                        chart_code=suffix.upper(), name="Synthetic " + suffix,
                        workspace=suffix.title(), organization_code=suffix.upper(),
                    )
        yield factory, boundary
    finally:
        factory.close()


_READERS = (
    (PostgresFinanceCoreRepository, "list_charts"),
    (PostgresReceivablesRepository, "list_customers"),
    (PostgresPayablesRepository, "list_suppliers"),
    (PostgresInventoryCoreRepository, "list_items"),
    (PostgresInventoryPlanningRepository, "list_count_sessions"),
    (PostgresInventoryValuationRepository, "list_documents"),
    (PostgresInventoryValuationReversalRepository, "list_reversals"),
    (PostgresMasterDataApplicationRepository, "list_organizations"),
)


def test_live_financial_adapters_preserve_scope_and_deny_sibling_or_cross_tenant_reads(
    scoped_financial_database: Any,
) -> None:
    _factory, boundary = scoped_financial_database
    expected_scope = ("scope_a", "org_one", "ws_one", "entity_one", "entity_one")
    expected_visible = (["ws_one"], ["org_one"], ["entity_one"])
    for repository_type, method in _READERS:
        with boundary.transaction("scope_a", organization_id="org_one", workspace_id="ws_one", legal_entity_id="entity_one") as connection:
            repository = repository_type(connection, "scope_a")
            assert _scope(connection) == expected_scope
            getattr(repository, method)(workspace="One")
            assert _scope(connection) == expected_scope, repository_type.__name__
            assert _visible(connection) == expected_visible
            try:
                sibling = getattr(repository, method)(workspace="Two")
            except PlatformError:
                sibling = []
            assert sibling == [], repository_type.__name__
            assert _scope(connection) == expected_scope
            with pytest.raises(PlatformError, match="repository scope"):
                getattr(repository_type(connection, "scope_b"), method)(workspace="Foreign")
            assert _scope(connection) == expected_scope
            assert _visible(connection) == expected_visible


def test_live_nested_success_failure_retry_and_sibling_write_preserve_scope(
    scoped_financial_database: Any,
) -> None:
    factory, boundary = scoped_financial_database
    with boundary.transaction("scope_a", organization_id="org_one", workspace_id="ws_one", legal_entity_id="entity_one") as connection:
        pid = connection.execute("SELECT pg_backend_pid()").fetchone()[0]
        before = _scope(connection)
        finance = PostgresFinanceCoreRepository(connection, "scope_a")
        with pytest.raises(PostgresFinanceCoreError, match="workspace"):
            finance.upsert_chart(chart_code="SIBLING-DENIED", name="Must not exist", workspace="Two", organization_code="TWO")
        assert _scope(connection) == before
        with pytest.raises(PlatformError, match="Chart name"):
            finance.upsert_chart(chart_code="INVALID", name="", workspace="One", organization_code="ONE")
        assert _scope(connection) == before
        finance.upsert_chart(chart_code="ALLOWED", name="Scoped write", workspace="One", organization_code="ONE")
        assert _scope(connection) == before
        assert {row["chart_code"] for row in finance.list_charts(workspace="One")} == {"ONE", "ALLOWED"}
        assert _visible(connection) == (["ws_one"], ["org_one"], ["entity_one"])
    with closing(factory.connect()) as connection:
        assert connection.execute("SELECT pg_backend_pid()").fetchone()[0] == pid
        assert all(value in (None, "") for value in _scope(connection))
        connection.rollback()
        # Existing standalone repository usage owns and initializes its transaction.
        assert [row["chart_code"] for row in PostgresFinanceCoreRepository(connection, "scope_a").list_charts(workspace="Two")] == ["TWO"]
        assert all(value in (None, "") for value in _scope(connection))
    with boundary.transaction("scope_b", organization_id="org_foreign", workspace_id="ws_foreign", legal_entity_id="entity_foreign") as connection:
        assert connection.execute("SELECT pg_backend_pid()").fetchone()[0] == pid
        assert [row["chart_code"] for row in PostgresFinanceCoreRepository(connection, "scope_b").list_charts(workspace="Foreign")] == ["FOREIGN"]
        assert _visible(connection) == (["ws_foreign"], ["org_foreign"], ["entity_foreign"])


def test_live_outer_rollback_removes_nested_business_audit_and_outbox_effects(scoped_financial_database: Any) -> None:
    _factory, boundary = scoped_financial_database
    with boundary.transaction("scope_a") as connection:
        baseline = tuple(connection.execute(
            "SELECT (SELECT count(*) FROM reconforge.finance_charts),"
            "(SELECT count(*) FROM reconforge.domain_audit_events),"
            "(SELECT count(*) FROM reconforge.outbox_events)"
        ).fetchone())
    with (
        pytest.raises(RuntimeError, match="synthetic outer failure"),
        boundary.transaction("scope_a", organization_id="org_one", workspace_id="ws_one", legal_entity_id="entity_one") as connection,
    ):
        PostgresFinanceCoreRepository(connection, "scope_a").upsert_chart(
            chart_code="ROLLBACK", name="Must roll back", workspace="One", organization_code="ONE",
        )
        raise RuntimeError("synthetic outer failure")
    with boundary.transaction("scope_a") as connection:
        assert tuple(connection.execute(
            "SELECT (SELECT count(*) FROM reconforge.finance_charts),"
            "(SELECT count(*) FROM reconforge.domain_audit_events),"
            "(SELECT count(*) FROM reconforge.outbox_events)"
        ).fetchone()) == baseline
