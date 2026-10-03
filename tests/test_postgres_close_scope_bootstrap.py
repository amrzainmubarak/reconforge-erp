"""Repeated current close installation preserves hierarchy constraints and RLS."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

import pytest

from reconforge.infrastructure.postgres import (
    PostgresConnectionFactory,
    PostgresSettings,
    PostgresTenantBoundary,
)
from reconforge.infrastructure.postgres_consolidation_close_scope import (
    POSTGRES_CONSOLIDATION_CLOSE_SCOPE_SCHEMA_SQL,
    install_postgres_consolidation_close_scope_schema,
)
from tests.test_alembic_postgres import isolated_postgres_migration_dsn as _isolated_dsn

isolated_postgres_migration_dsn = _isolated_dsn
TENANT = "close-bootstrap-synthetic"


def test_revision0078_close_sql_remains_byte_identical() -> None:
    # The current installer may evolve independently of the historical revision.
    assert hashlib.sha256(POSTGRES_CONSOLIDATION_CLOSE_SCOPE_SCHEMA_SQL.encode()).hexdigest() == (
        "041ffcb9e7eea3b505b7fcf73131d7d3146914584a5f8dfeac0bf9c660f49fd5"
    )


def _schema_fingerprint(connection: Any) -> tuple[Any, ...]:
    constraints = connection.execute(
        "SELECT c.conrelid::regclass::text,c.conname,pg_get_constraintdef(c.oid) "
        "FROM pg_constraint c JOIN pg_class t ON t.oid=c.conrelid "
        "JOIN pg_namespace n ON n.oid=t.relnamespace "
        "WHERE n.nspname='reconforge' AND t.relname LIKE 'consolidation_close_%' "
        "ORDER BY 1,2"
    ).fetchall()
    policies = connection.execute(
        "SELECT tablename,policyname,qual,with_check FROM pg_policies "
        "WHERE schemaname='reconforge' AND tablename LIKE 'consolidation_close_%' "
        "ORDER BY 1,2"
    ).fetchall()
    rls = connection.execute(
        "SELECT relname,relrowsecurity,relforcerowsecurity FROM pg_class "
        "WHERE relnamespace='reconforge'::regnamespace AND relname LIKE 'consolidation_close_%' "
        "AND relkind='r' ORDER BY 1"
    ).fetchall()
    return tuple(constraints), tuple(policies), tuple(rls)


def _period(connection: Any, record_id: str, organization: str, entity: str) -> None:
    connection.execute(
        "INSERT INTO reconforge.consolidation_close_periods "
        "(tenant_id,id,workspace_id,organization_id,legal_entity_id,group_code,period_name,"
        "reporting_currency,period_start_date,period_end_date,reporting_date,created_by) "
        "VALUES(%s,%s,'workspace',%s,%s,%s,'2026-10','USD','2026-10-01',"
        "'2026-10-31','2026-10-31','synthetic-maker')",
        (TENANT, record_id, organization, entity, "GROUP-"+organization),
    )


def test_live_current_close_bootstrap_repeats_without_losing_hierarchy_guards(
    isolated_postgres_migration_dsn: str,
) -> None:
    import psycopg
    from alembic.config import Config

    from alembic import command

    app_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_DSN")
    if not app_dsn:
        pytest.skip("requires a live PostgreSQL application role")
    command.upgrade(Config(str(Path("alembic.ini").resolve())), "head")
    parameters = psycopg.conninfo.conninfo_to_dict(app_dsn)
    parameters["dbname"] = psycopg.conninfo.conninfo_to_dict(isolated_postgres_migration_dsn)["dbname"]
    with psycopg.connect(isolated_postgres_migration_dsn) as admin:
        assert admin.execute("SHOW max_identifier_length").fetchone()[0] == "63"
        migrated = _schema_fingerprint(admin)
        install_postgres_consolidation_close_scope_schema(admin)
        installed = _schema_fingerprint(admin)
        assert installed == migrated
        for _ in range(2):
            install_postgres_consolidation_close_scope_schema(admin)
            assert _schema_fingerprint(admin) == installed
        assert installed[2] and all(enabled and forced for _, enabled, forced in installed[2])
        assert admin.execute(
            "SELECT count(*) FROM pg_constraint WHERE conrelid="
            "'reconforge.consolidation_close_ownership_change_links'::regclass "
            "AND conname=('consolidation_close_ownership_change_links_hierarchy_entity_unique')::name"
        ).fetchone()[0] == 1
        role = psycopg.sql.Identifier(parameters["user"])
        admin.execute(psycopg.sql.SQL("GRANT USAGE ON SCHEMA reconforge TO {}").format(role))
        admin.execute(psycopg.sql.SQL(
            "GRANT SELECT,INSERT ON reconforge.consolidation_close_periods TO {}"
        ).format(role))
        admin.execute("INSERT INTO reconforge.tenants(id,name) VALUES(%s,'Synthetic bootstrap')", (TENANT,))
        admin.execute("INSERT INTO reconforge.currencies(tenant_id,code,name,minor_units) VALUES(%s,'USD','US Dollar',2)", (TENANT,))
        admin.execute("INSERT INTO reconforge.domain_workspaces(tenant_id,id,name) VALUES(%s,'workspace','Synthetic')", (TENANT,))
        for suffix in ("a", "b"):
            admin.execute(
                "INSERT INTO reconforge.organizations(tenant_id,id,organization_code,name,base_currency) "
                "VALUES(%s,%s,%s,'Synthetic','USD')", (TENANT, "org-"+suffix, "ORG-"+suffix.upper()),
            )
            admin.execute(
                "INSERT INTO reconforge.legal_entities(tenant_id,id,organization_id,entity_code,name,currency_code) "
                "VALUES(%s,%s,%s,'ENTITY','Synthetic','USD')", (TENANT, "entity-"+suffix, "org-"+suffix),
            )
    factory = PostgresConnectionFactory(PostgresSettings(dsn=psycopg.conninfo.make_conninfo(**parameters), require_tls=False))
    boundary = PostgresTenantBoundary(factory)
    for suffix in ("a", "b"):
        with boundary.transaction(TENANT, organization_id="org-"+suffix, workspace_id="workspace", legal_entity_id="entity-"+suffix) as connection:
            assert tuple(connection.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone()) == (False, False)
            _period(connection, "period-"+suffix, "org-"+suffix, "entity-"+suffix)
            assert [row[0] for row in connection.execute("SELECT id FROM reconforge.consolidation_close_periods").fetchall()] == ["period-"+suffix]
            with pytest.raises(psycopg.errors.UniqueViolation), connection.transaction():
                _period(connection, "duplicate-"+suffix, "org-"+suffix, "entity-"+suffix)
            with pytest.raises(psycopg.errors.InsufficientPrivilege), connection.transaction():
                _period(connection, "sibling-write-"+suffix, "org-b" if suffix == "a" else "org-a", "entity-b" if suffix == "a" else "entity-a")
    with (
        boundary.transaction(TENANT, organization_id="missing-org", workspace_id="workspace", legal_entity_id="missing-entity") as connection,
        pytest.raises(psycopg.errors.ForeignKeyViolation),
        connection.transaction(),
    ):
        _period(connection, "unknown-parent", "missing-org", "missing-entity")
    with boundary.transaction("unrelated-bootstrap-tenant") as connection:
        assert connection.execute("SELECT id FROM reconforge.consolidation_close_periods").fetchall() == []
    with psycopg.connect(psycopg.conninfo.make_conninfo(**parameters)) as connection:
        assert connection.execute("SELECT id FROM reconforge.consolidation_close_periods").fetchall() == []
    with psycopg.connect(isolated_postgres_migration_dsn) as admin:
        assert admin.execute("SELECT id FROM reconforge.consolidation_close_periods ORDER BY id").fetchall() == [("period-a",), ("period-b",)]
        install_postgres_consolidation_close_scope_schema(admin)
        assert _schema_fingerprint(admin) == installed
        assert admin.execute("SELECT id FROM reconforge.consolidation_close_periods ORDER BY id").fetchall() == [("period-a",), ("period-b",)]
