"""Native populated restore retains Finance values and canonical authority."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from collections.abc import Callable
from typing import Any
from uuid import uuid4

import pytest

from reconforge.infrastructure.postgres import PostgresConnectionFactory, PostgresSettings, PostgresTenantBoundary
from reconforge.infrastructure.postgres_finance_core import PostgresFinanceCoreRepository
from reconforge.platform.common import PlatformError
from tests.test_postgres_finance_scope import (
    TABLES,
    _entry,
    _policies,
    _scope,
)
from tests.test_postgres_finance_scope import (
    finance_database as _finance_database,
)
from tests.test_postgres_finance_scope import (
    isolated_postgres_migration_dsn as _isolated_postgres_migration_dsn,
)

finance_database = _finance_database
isolated_postgres_migration_dsn = _isolated_postgres_migration_dsn
NativeTool = Callable[[str, list[str], bytes | None], bytes]


@pytest.fixture
def native_tools(finance_database: dict[str, Any]) -> NativeTool:
    import psycopg

    if not all(shutil.which(tool) for tool in ("pg_dump", "pg_restore")):
        pytest.skip("requires native PostgreSQL pg_dump and pg_restore client tools")
    parameters = psycopg.conninfo.conninfo_to_dict(finance_database["admin"])
    environment = {
        **os.environ,
        "PGHOST": parameters["host"],
        "PGPORT": parameters.get("port", "5432"),
        "PGUSER": parameters["user"],
        "PGPASSWORD": parameters.get("password", ""),
    }

    def run(tool: str, arguments: list[str], data: bytes | None = None) -> bytes:
        assert tool in ("pg_dump", "pg_restore")
        completed = subprocess.run(
            [tool, *arguments], input=data, capture_output=True, env=environment, timeout=120, check=False,
        )
        assert completed.returncode == 0, completed.stderr.decode("utf-8", errors="replace")
        return completed.stdout

    return run


def _history(connection: Any) -> dict[str, str]:
    from psycopg import sql

    tables = (*TABLES, "currencies", "organizations", "legal_entities", "fiscal_periods", "domain_audit_events", "domain_audit_ledger_state", "outbox_events")
    result = {}
    for table in tables:
        rows = connection.execute(sql.SQL("SELECT to_jsonb(t) FROM {} t").format(sql.Identifier("reconforge", table)))
        values = sorted(json.dumps(row[0], sort_keys=True, separators=(",", ":")) for row in rows)
        result[table] = hashlib.sha256(json.dumps(values, separators=(",", ":")).encode()).hexdigest()
    return result


def verify_native_finance_restore(db: dict[str, Any], native: NativeTool) -> dict[str, Any]:
    """Use real native tools; transport may be local executables or Docker exec."""
    import psycopg
    from psycopg import sql

    original = psycopg.conninfo.conninfo_to_dict(db["admin"])
    database = "reconforge_finance_restore_" + uuid4().hex[:20]
    with psycopg.connect(db["admin"], autocommit=True) as admin:
        before = _history(admin)
        policies = _policies(admin)
        revision = admin.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        assert admin.execute("SELECT 1 FROM pg_database WHERE datname=%s", (database,)).fetchone() is None
        dump = native("pg_dump", ["--format=custom", "--dbname", original["dbname"]], None)
        assert dump.startswith(b"PGDMP")
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
    try:
        native("pg_restore", ["--exit-on-error", "--no-owner", "--dbname", database], dump)
        restored_admin = psycopg.conninfo.make_conninfo(**{**original, "dbname": database})
        with psycopg.connect(restored_admin) as admin:
            runtime_role = psycopg.conninfo.conninfo_to_dict(os.environ["RECONFORGE_TEST_POSTGRES_DSN"])["user"]
            assert admin.execute(
                "SELECT has_table_privilege(%s,'reconforge.operational_finance_plans','SELECT'),"
                "has_table_privilege(%s,'reconforge.operational_finance_plans','INSERT'),"
                "has_table_privilege(%s,'reconforge.operational_finance_plans','UPDATE'),"
                "has_table_privilege(%s,'reconforge.operational_finance_plans','DELETE')",
                (runtime_role,) * 4,
            ).fetchone() == (True, False, False, False)
            assert admin.execute("SELECT version_num FROM alembic_version").fetchone()[0] == revision
            assert _history(admin) == before
            assert _policies(admin) == policies
            assert admin.execute("SELECT application_workspace_id FROM reconforge.organizations WHERE id='org_legacy'").fetchone() == (None,)
            assert admin.execute("SELECT convalidated FROM pg_constraint WHERE conname='finance_accounts_parent_scope_fk'").fetchone() == (False,)
            assert admin.execute("SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='reconforge' AND c.relname=ANY(%s) AND c.relrowsecurity AND c.relforcerowsecurity", (list(TABLES),)).fetchone() == (8,)
        app = psycopg.conninfo.conninfo_to_dict(os.environ["RECONFORGE_TEST_POSTGRES_DSN"])
        app["dbname"] = database
        boundary = PostgresTenantBoundary(PostgresConnectionFactory(PostgresSettings(dsn=psycopg.conninfo.make_conninfo(**app), require_tls=False)))
        with boundary.transaction("finance_scope", organization_id="org_a", workspace_id="shared", legal_entity_id="entity_a1") as connection:
            scope = _scope(connection)
            assert tuple(connection.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone()) == (False, False)
            finance = PostgresFinanceCoreRepository(connection, "finance_scope")
            assert [row["id"] for row in finance.list_entries(workspace="Shared")] == [db["entries"]["A1"]]
            entry = finance.get_entry(db["entries"]["A1"])
            assert entry["total_debit_minor"] == entry["total_credit_minor"] == 10000
            assert entry["total_debit"] == "100.00" and len(entry["currency_registry_digest"]) == 64
            for sibling in ("A2", "B1", "LEGACY"):
                with pytest.raises(PlatformError):
                    finance.get_entry(db["entries"][sibling])
            with pytest.raises(psycopg.Error), connection.transaction():
                connection.execute("UPDATE reconforge.finance_entries SET entity_code='A2' WHERE id=%s", (db["entries"]["A1"],))
            with pytest.raises(psycopg.Error), connection.transaction():
                connection.execute("DELETE FROM reconforge.legal_entities WHERE id='entity_a1'")
            draft = _entry(finance, "RESTORED-PERMITTED-DRAFT")
            assert draft["status"] == "Draft" and draft["total_debit_minor"] == 10000
            assert _scope(connection) == scope
        with psycopg.connect(db["admin"]) as admin:
            assert _history(admin) == before  # Restored writes cannot affect the source.
    finally:
        with psycopg.connect(db["admin"], autocommit=True) as admin:
            admin.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=%s AND pid<>pg_backend_pid()", (database,))
            admin.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(database)))
            assert admin.execute("SELECT 1 FROM pg_database WHERE datname=%s", (database,)).fetchone() is None
    return {"revision": revision, "dump_sha256": hashlib.sha256(dump).hexdigest(), "dump_bytes": len(dump), "table_digests": before, "policies_equal": True, "values_equal": True, "scoped_denials_verified": True, "permitted_write_verified": True, "source_unchanged": True, "restored_database_removed": True}


def test_live_populated_finance_native_restore(finance_database: dict[str, Any], native_tools: NativeTool) -> None:
    verify_native_finance_restore(finance_database, native_tools)
