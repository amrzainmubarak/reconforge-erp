"""Contract and optional live isolation tests for PostgreSQL master data."""

from __future__ import annotations

import os
import re
from typing import Any

import pytest

from reconforge.infrastructure.postgres import PostgresConnectionFactory, PostgresSettings, PostgresTenantBoundary
from reconforge.infrastructure.postgres_master_data import (
    POSTGRES_FISCAL_PERIOD_SCHEMA_SQL,
    POSTGRES_MASTER_DATA_SCHEMA_SQL,
    PostgresMasterDataRepository,
    PostgresMasterDataValidationError,
)


class _Cursor:
    def __init__(self, row: tuple[Any, ...] | None = None, rows: list[tuple[Any, ...]] | None = None) -> None:
        self.row = row
        self.rows = rows or []

    def fetchone(self) -> tuple[Any, ...] | None:
        return self.row

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self.rows


class _FakeConnection:
    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple[Any, ...] | None]] = []
        self.commits = 0
        self._rows: list[tuple[Any, ...]] = []

    def queue_rows(self, *rows: tuple[Any, ...]) -> None:
        self._rows = list(rows)

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> _Cursor:
        self.executed.append((sql, params))
        if "RETURNING" in sql:
            return _Cursor(row=self._rows.pop(0) if self._rows else None)
        return _Cursor(rows=list(self._rows))

    def commit(self) -> None:
        self.commits += 1


class _EvidenceConnection(_FakeConnection):
    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> _Cursor:
        self.executed.append((sql, params))
        if "FROM reconforge.audit_events" in sql:
            return _Cursor(row=None)
        if "FROM reconforge.currencies" in sql and "RETURNING" not in sql:
            return _Cursor(row=None)
        if "RETURNING" in sql:
            return _Cursor(row=self._rows.pop(0) if self._rows else None)
        return _Cursor()


class _PeriodConnection(_FakeConnection):
    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> _Cursor:
        self.executed.append((sql, params))
        if "RETURNING" in sql:
            return _Cursor(row=self._rows.pop(0) if self._rows else None)
        return _Cursor(row=None)


def test_master_data_schema_is_tenant_scoped_and_constraint_backed() -> None:
    assert "CREATE TABLE IF NOT EXISTS reconforge.currencies" in POSTGRES_MASTER_DATA_SCHEMA_SQL
    assert "CREATE TABLE IF NOT EXISTS reconforge.legal_entities" in POSTGRES_MASTER_DATA_SCHEMA_SQL
    assert "CREATE TABLE IF NOT EXISTS reconforge.branches" in POSTGRES_MASTER_DATA_SCHEMA_SQL
    assert "CREATE TABLE IF NOT EXISTS reconforge.fiscal_periods" in POSTGRES_FISCAL_PERIOD_SCHEMA_SQL
    assert "organizations_tenant_base_currency_fk" in POSTGRES_MASTER_DATA_SCHEMA_SQL
    assert "FOREIGN KEY (tenant_id, organization_id)" in POSTGRES_MASTER_DATA_SCHEMA_SQL
    assert "ENABLE ROW LEVEL SECURITY" in POSTGRES_MASTER_DATA_SCHEMA_SQL
    assert "FORCE ROW LEVEL SECURITY" in POSTGRES_MASTER_DATA_SCHEMA_SQL
    assert "current_setting('app.tenant_id', true)" in POSTGRES_MASTER_DATA_SCHEMA_SQL


def test_master_data_repository_parameterizes_tenant_and_does_not_commit() -> None:
    connection = _FakeConnection()
    connection.queue_rows(("tenant_a", "org-a", "ORG_A", "North", "USD", True, "created", "updated"))
    repository = PostgresMasterDataRepository(connection)

    record = repository.upsert_organization(
        tenant_id="TENANT_A",
        organization_id="ORG-A",
        organization_code="org_a",
        name="North",
        base_currency="usd",
    )

    assert record["tenant_id"] == "tenant_a"
    assert record["id"] == "org-a"
    assert connection.executed[0][1] == ("tenant_a", "org-a", "ORG_A", "North", "USD", True)
    assert connection.commits == 0


def test_master_data_mutation_can_append_audit_and_outbox_evidence_in_caller_transaction() -> None:
    connection = _EvidenceConnection()
    connection.queue_rows(("tenant_a", "USD", "US Dollar", 2, True, "created", "updated"))

    record = PostgresMasterDataRepository(connection).upsert_currency(
        tenant_id="tenant_a",
        code="USD",
        name="US Dollar",
        actor_id="user-a",
        request_id="request-a",
        metadata={"source": "test"},
    )

    assert record["code"] == "USD"
    sql = [statement for statement, _ in connection.executed]
    assert any("INSERT INTO reconforge.audit_events" in statement for statement in sql)
    assert any("INSERT INTO reconforge.outbox_events" in statement for statement in sql)
    assert connection.commits == 0


def test_master_data_repository_lists_rows_deterministically() -> None:
    connection = _FakeConnection()
    connection.queue_rows(
        ("tenant_a", "org-a", "ORG_A", "North", "USD", True, "created", "updated"),
        ("tenant_a", "org-b", "ORG_B", "South", "EGP", True, "created", "updated"),
    )
    rows = PostgresMasterDataRepository(connection).list_organizations(tenant_id="tenant_a")

    assert [row["id"] for row in rows] == ["org-a", "org-b"]
    assert "ORDER BY organization_code NULLS LAST, id" in connection.executed[0][0]
    assert connection.executed[0][1] == ("tenant_a",)


def test_master_data_repository_upserts_non_overlapping_fiscal_periods_without_committing() -> None:
    connection = _PeriodConnection()
    connection.queue_rows(
        ("tenant_a", "period-a", "2026-07", "2026-07-01", "2026-07-31", "Open", "created", 2026, 7, "", "updated")
    )

    record = PostgresMasterDataRepository(connection).upsert_period(
        tenant_id="tenant_a",
        period_id="period-a",
        name="2026-07",
        start_date="2026-07-01",
        end_date="2026-07-31",
    )

    assert record["status"] == "Open"
    assert any("pg_advisory_xact_lock" in statement for statement, _ in connection.executed)
    assert any("start_date <= %s" in statement for statement, _ in connection.executed)
    assert connection.commits == 0


@pytest.mark.parametrize(
    ("method", "kwargs"),
    [
        ("upsert_currency", {"tenant_id": "tenant_a", "code": "US", "name": "Dollar"}),
        (
            "upsert_organization",
            {"tenant_id": "tenant_a", "organization_id": "../other", "organization_code": "ORG", "name": "North"},
        ),
        (
            "upsert_legal_entity",
            {
                "tenant_id": "tenant_a",
                "organization_id": "org-a",
                "entity_id": "le-a",
                "entity_code": "LE",
                "name": "North Ltd",
                "currency_code": "US",
            },
        ),
        (
            "upsert_period",
            {
                "tenant_id": "tenant_a",
                "period_id": "period-a",
                "name": "2026-07",
                "start_date": "2026/07/01",
                "end_date": "2026-07-31",
            },
        ),
    ],
)
def test_master_data_repository_rejects_invalid_values(method: str, kwargs: dict[str, object]) -> None:
    repository = PostgresMasterDataRepository(_FakeConnection())
    with pytest.raises(PostgresMasterDataValidationError):
        getattr(repository, method)(**kwargs)


@pytest.mark.skipif(not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"), reason="requires a live PostgreSQL service")
def test_live_postgres_master_data_isolation_and_constraints() -> None:
    psycopg = pytest.importorskip("psycopg")
    from reconforge.infrastructure.postgres import install_postgres_rls_schema

    dsn = os.environ["RECONFORGE_TEST_POSTGRES_DSN"]
    admin_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN", dsn)
    app_user = os.environ.get("RECONFORGE_TEST_POSTGRES_APP_USER", "")
    if app_user and not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", app_user):
        pytest.fail("RECONFORGE_TEST_POSTGRES_APP_USER contains unsafe characters")

    factory = PostgresConnectionFactory(PostgresSettings(dsn=dsn, require_tls=False))
    admin_factory = PostgresConnectionFactory(PostgresSettings(dsn=admin_dsn, require_tls=False))
    admin = admin_factory.connect()
    app = factory.connect()
    tenant_a = "master_data_a"
    tenant_b = "master_data_b"
    try:
        with admin.transaction():
            install_postgres_rls_schema(admin)
            admin.execute(POSTGRES_MASTER_DATA_SCHEMA_SQL)
            if app_user:
                admin.execute(f"GRANT USAGE ON SCHEMA reconforge TO {app_user}")
                admin.execute(
                    f"GRANT SELECT, INSERT, UPDATE, DELETE ON reconforge.tenants, reconforge.organizations, "
                    f"reconforge.currencies, reconforge.legal_entities, reconforge.branches TO {app_user}"
                )

        role = app.execute(
            "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user"
        ).fetchone()
        if role is None or bool(role[0]) or bool(role[1]):
            pytest.skip("live RLS test requires a non-superuser, non-BYPASSRLS application role")

        with PostgresTenantBoundary(factory).transaction(tenant_a) as connection:
            connection.execute(
                "INSERT INTO reconforge.tenants (id, name) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (tenant_a, "Master A"),
            )
        with PostgresTenantBoundary(factory).transaction(tenant_b) as connection:
            connection.execute(
                "INSERT INTO reconforge.tenants (id, name) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (tenant_b, "Master B"),
            )
        with PostgresTenantBoundary(factory).transaction(tenant_a) as connection:
            repository = PostgresMasterDataRepository(connection)
            repository.upsert_currency(tenant_id=tenant_a, code="USD", name="US Dollar")
            repository.upsert_organization(
                tenant_id=tenant_a,
                organization_id="org-a",
                organization_code="ORG_A",
                name="North",
                base_currency="USD",
            )
            repository.upsert_legal_entity(
                tenant_id=tenant_a,
                organization_id="org-a",
                entity_id="le-a",
                entity_code="LE_A",
                name="North Ltd",
                currency_code="USD",
            )
            repository.upsert_branch(
                tenant_id=tenant_a,
                organization_id="org-a",
                branch_id="branch-a",
                branch_code="BR_A",
                name="Cairo",
                legal_entity_id="le-a",
            )
            assert [row["id"] for row in repository.list_organizations(tenant_id=tenant_a)] == ["org-a"]
            assert [row["id"] for row in repository.list_branches(tenant_id=tenant_a)] == ["branch-a"]
        with PostgresTenantBoundary(factory).transaction(tenant_b) as connection:
            repository = PostgresMasterDataRepository(connection)
            assert repository.list_organizations(tenant_id=tenant_b) == []
            assert repository.list_legal_entities(tenant_id=tenant_b) == []
            assert repository.list_branches(tenant_id=tenant_b) == []
    finally:
        for tenant_id in (tenant_a, tenant_b):
            try:
                with PostgresTenantBoundary(factory).transaction(tenant_id) as connection:
                    connection.execute("DELETE FROM reconforge.tenants WHERE id = %s", (tenant_id,))
            except psycopg.Error:
                pass
        app.close()
        admin.close()
