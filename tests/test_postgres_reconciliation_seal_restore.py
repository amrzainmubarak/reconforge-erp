"""Native restore retains reconciliation history and the child append boundary."""
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

from reconforge.infrastructure.postgres import (
    PostgresConnectionFactory,
    PostgresRuntimeConnectionFactory,
    PostgresSettings,
    PostgresTenantBoundary,
)
from reconforge.infrastructure.postgres_reconciliation import PostgresReconciliationRepository
from tests.test_postgres_reconciliation_input_seal import TENANT, _completed, _create, _raw_insert, _raw_output
from tests.test_postgres_reconciliation_input_seal import (
    isolated_postgres_migration_dsn as _isolated_postgres_migration_dsn,
)
from tests.test_postgres_reconciliation_input_seal import seal_database as _seal_database

isolated_postgres_migration_dsn = _isolated_postgres_migration_dsn
seal_database = _seal_database
NativeTool = Callable[[str, list[str], bytes | None], bytes]


@pytest.fixture
def native_tools(seal_database: dict[str, Any]) -> NativeTool:
    import psycopg

    if not all(shutil.which(tool) for tool in ("pg_dump", "pg_restore")):
        pytest.skip("requires native PostgreSQL pg_dump and pg_restore client tools")
    params = psycopg.conninfo.conninfo_to_dict(seal_database["admin"])
    environment = {**os.environ, "PGHOST": params["host"], "PGPORT": params.get("port", "5432"), "PGUSER": params["user"], "PGPASSWORD": params.get("password", "")}

    def run(tool: str, arguments: list[str], data: bytes | None = None) -> bytes:
        assert tool in ("pg_dump", "pg_restore")
        result = subprocess.run([tool, *arguments], input=data, capture_output=True, env=environment, timeout=120, check=False)
        assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
        return result.stdout

    return run


def _history(connection: Any) -> dict[str, str]:
    from psycopg import sql

    result = {}
    for table in ("reconciliation_runs", "reconciliation_inputs", "reconciliation_results", "reconciliation_exceptions", "audit_events", "outbox_events"):
        values = sorted(json.dumps(row[0], sort_keys=True, separators=(",", ":")) for row in connection.execute(sql.SQL("SELECT to_jsonb(t) FROM {} t").format(sql.Identifier("reconforge", table))))
        result[table] = hashlib.sha256(json.dumps(values, separators=(",", ":")).encode()).hexdigest()
    return result


def verify_native_reconciliation_restore(db: dict[str, Any], native: NativeTool) -> dict[str, Any]:
    """Exercise real pg_dump/pg_restore with injectable local or Docker transport."""
    import psycopg
    from psycopg import sql

    with db["boundary"].transaction(TENANT) as connection:
        completed = _completed(PostgresReconciliationRepository(connection), "native-complete")
    original = psycopg.conninfo.conninfo_to_dict(db["admin"])
    database = "reconforge_seal_restore_" + uuid4().hex[:20]
    trigger_query = "SELECT c.relname,t.tgname,t.tgenabled,pg_get_triggerdef(t.oid) FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='reconforge' AND t.tgname='reconciliation_child_write_guard' ORDER BY c.relname"
    with psycopg.connect(db["admin"], autocommit=True) as admin:
        before = _history(admin)
        triggers = list(admin.execute(trigger_query))
        assert len(triggers) == 3
        revision = admin.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        assert admin.execute("SELECT 1 FROM pg_database WHERE datname=%s", (database,)).fetchone() is None
        dump = native("pg_dump", ["--format=custom", "--dbname", original["dbname"]], None)
        assert dump.startswith(b"PGDMP")
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
    try:
        native("pg_restore", ["--exit-on-error", "--no-owner", "--dbname", database], dump)
        with psycopg.connect(psycopg.conninfo.make_conninfo(**{**original, "dbname": database})) as admin:
            assert _history(admin) == before
            assert list(admin.execute(trigger_query)) == triggers
            assert admin.execute("SELECT version_num FROM alembic_version").fetchone()[0] == revision
        app = psycopg.conninfo.conninfo_to_dict(os.environ["RECONFORGE_TEST_POSTGRES_DSN"])
        app["dbname"] = database
        factory = PostgresRuntimeConnectionFactory(PostgresConnectionFactory(PostgresSettings(dsn=psycopg.conninfo.make_conninfo(**app), require_tls=False)))
        try:
            with PostgresTenantBoundary(factory).transaction(TENANT) as connection:
                repository = PostgresReconciliationRepository(connection)
                assert repository.get_run(tenant_id=TENANT, run_id="native-complete")["input_manifest_hash"] == completed["input_manifest_hash"]
                for table in ("inputs", "results", "exceptions"):
                    with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState, match="sealed"), connection.transaction():
                        if table == "inputs":
                            _raw_insert(connection, "native-complete", "after-restore")
                        else:
                            _raw_output(connection, "native-complete", table)
                repository.register_input(tenant_id=TENANT, run_id="native-complete", side="Left", source_id="source", record_hash="synthetic-fingerprint", amount="1", currency_code="USD")
                _create(repository, "restored-new")
                _raw_insert(connection, "restored-new")
                assert len(repository.list_inputs(tenant_id=TENANT, run_id="restored-new")) == 1
        finally:
            factory.close()
        with psycopg.connect(db["admin"]) as admin:
            assert _history(admin) == before
    finally:
        with psycopg.connect(db["admin"], autocommit=True) as admin:
            admin.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=%s AND pid<>pg_backend_pid()", (database,))
            admin.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(database)))
            assert admin.execute("SELECT 1 FROM pg_database WHERE datname=%s", (database,)).fetchone() is None
    return {"revision": revision, "dump_sha256": hashlib.sha256(dump).hexdigest(), "dump_bytes": len(dump), "table_digests": before, "three_child_triggers_retained": True, "restricted_role_append_denials": True, "exact_replay_allowed": True, "new_queued_input_allowed": True, "source_database_unchanged": True, "restored_database_removed": True}


def test_live_native_reconciliation_restore(seal_database: dict[str, Any], native_tools: NativeTool) -> None:
    verify_native_reconciliation_restore(seal_database, native_tools)
