"""Executed147/148 upgrade boundaries with genuine retained v1/v2 source owners.

Fixture-only module: mandatory in the native CI shard, never optional acceptance.
Every case creates and removes its own synthetic database.
"""

from __future__ import annotations

import os
import subprocess  # nosec B404
import sys
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.rows import dict_row

from reconforge.infrastructure.postgres_customer_partial_return_rounding_schema import (
    install_customer_partial_return_rounding,
)
from reconforge.infrastructure.postgres_customer_partial_return_transfer_hooks import (
    install_postgres_customer_partial_return_transfer_hooks,
)
from tests.gfo_browser_restore import database_snapshot
from tests.test_postgres_customer_partial_returns import create_partial_runtime, posted, prepare_return, request

ROOT = Path(__file__).resolve().parents[1]
LEGACY = "0147_pg_customer_partial_returns"
HEAD = "0148_pg_partial_return_rounding"


def migrate(dsn: str, operation: str, revision: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "alembic", operation, revision], cwd=ROOT,
        env={**os.environ, "RECONFORGE_POSTGRES_DSN": dsn},
        capture_output=True, text=True, check=False, timeout=180,
    )  # nosec B603


def accepted_migration(dsn: str, operation: str, revision: str) -> None:
    result = migrate(dsn, operation, revision)
    assert result.returncode == 0, result.stderr


def function_oids(dsn: str) -> dict[str, int]:
    with psycopg.connect(dsn) as connection:
        return dict(connection.execute(
            "SELECT oid::regprocedure::text,oid FROM pg_proc WHERE pronamespace='reconforge'::regnamespace"
        ).fetchall())


@pytest.fixture
def legacy_database() -> Iterator[tuple[str, str]]:
    database = "reconforge_cr2_migration_" + uuid4().hex[:16]
    admin_url = urlsplit(os.environ["RECONFORGE_TEST_POSTGRES_ADMIN_DSN"])
    admin = urlunsplit(admin_url._replace(path="/" + database))
    app = psycopg.conninfo.make_conninfo(os.environ["RECONFORGE_TEST_POSTGRES_DSN"], dbname=database)
    control_dsn = psycopg.conninfo.make_conninfo(admin, dbname="postgres", connect_timeout=5)
    with psycopg.connect(control_dsn, autocommit=True) as control:
        control.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
    try:
        accepted_migration(admin, "upgrade", LEGACY)
        from reconforge.infrastructure.postgres_inventory_receipt_posting_schema import (
            install_postgres_inventory_receipt_posting_schema,
        )
        from reconforge.infrastructure.postgres_receipt_admission import install_postgres_receipt_admission

        with psycopg.connect(admin) as connection:
            install_postgres_inventory_receipt_posting_schema(connection)
            install_postgres_receipt_admission(connection)
            app_user = psycopg.conninfo.conninfo_to_dict(app)["user"]
            for statement in (
                "GRANT USAGE ON SCHEMA reconforge TO {}",
                "GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA reconforge TO {}",
                "GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA reconforge TO {}",
            ):
                connection.execute(sql.SQL(statement).format(sql.Identifier(app_user)))
        yield admin, app
    finally:
        with psycopg.connect(control_dsn, autocommit=True) as control:
            control.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database)))
            assert control.execute("SELECT 1 FROM pg_database WHERE datname=%s", (database,)).fetchone() is None


def test_empty147_148_147_roundtrip_restores_all_catalog_rows_and_function_identities(
    legacy_database: tuple[str, str],
) -> None:
    admin, app = legacy_database
    before, oids = database_snapshot(admin), function_oids(admin)
    accepted_migration(admin, "upgrade", HEAD)
    with psycopg.connect(admin) as connection:
        assert connection.execute("SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid="
                                  "'reconforge.customer_partial_return_allocation_witnesses'::regclass").fetchone() == (True, True)
        assert connection.execute("SELECT prosecdef FROM pg_proc WHERE oid="
                                  "'reconforge.customer_partial_return_v2_fifo(bigint,bigint,bigint)'::regprocedure").fetchone() == (False,)
    with psycopg.connect(app) as connection:
        assert connection.execute("SELECT rolsuper,rolbypassrls,rolcreaterole,rolcreatedb,rolreplication "
                                  "FROM pg_roles WHERE rolname=current_user").fetchone() == (False,) * 5
    accepted_migration(admin, "downgrade", LEGACY)
    assert database_snapshot(admin) == before
    assert function_oids(admin) == oids
    accepted_migration(admin, "upgrade", HEAD)
    retained = database_snapshot(admin)
    for row_factory in (None, dict_row):
        with psycopg.connect(admin, row_factory=row_factory) as connection:
            install_customer_partial_return_rounding(connection)
            install_postgres_customer_partial_return_transfer_hooks(connection)
    assert database_snapshot(admin) == retained


def test_retained_posted_v1_history_survives148_upgrade_and_safe147_downgrade(
    legacy_database: tuple[str, str],
) -> None:
    admin, _app = legacy_database
    runtime, source, _invoice = create_partial_runtime(legacy_database)
    initial = prepare_return(runtime, source, 3, command="retained-v1-migration-prepare")
    original = posted(runtime, initial)
    assert original["phase"] == 2
    before, oids = database_snapshot(admin), function_oids(admin)
    accepted_migration(admin, "upgrade", HEAD)
    upgraded = database_snapshot(admin)
    assert all(upgraded["tables"][name] == rows for name, rows in before["tables"].items())
    accepted_migration(admin, "downgrade", LEGACY)
    assert database_snapshot(admin) == before
    assert function_oids(admin) == oids
    # Lost-response acknowledgements retain the exact original147 response.
    assert prepare_return(runtime, source, 3, command="retained-v1-migration-prepare") == initial


def test_retained_v2_source_refuses_downgrade_before_any_catalog_or_data_mutation(
    legacy_database: tuple[str, str],
) -> None:
    from reconforge.infrastructure.postgres_customer_partial_returns import PostgresCustomerPartialReturnsRepository

    admin, _app = legacy_database
    accepted_migration(admin, "upgrade", HEAD)
    runtime, source, _invoice = create_partial_runtime(legacy_database)
    with runtime.actor("maker") as (connection, _receipt, actor):
        owner = PostgresCustomerPartialReturnsRepository(connection, runtime.tenant, protocol_version=2)
        prepared = owner.prepare(request(source, 3), command_id="retained-v2-migration-prepare", actor=actor)
        assert prepared["allocation_policy"] == "remaining-original-v1"
    before, oids = database_snapshot(admin), function_oids(admin)
    refused = migrate(admin, "downgrade", LEGACY)
    assert refused.returncode != 0
    assert "Retained" in refused.stderr and "downgrade" in refused.stderr
    assert database_snapshot(admin) == before
    assert function_oids(admin) == oids
