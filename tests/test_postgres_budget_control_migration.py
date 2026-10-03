"""Registered PostgreSQL migration acceptance for governed budget control."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import pytest

from reconforge.infrastructure.postgres_budget_control_schema import POSTGRES_BUDGET_CONTROL_SCHEMA_SQL

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "alembic/versions/0102_postgres_budget_control.py"
PREVIOUS = "0101_pg_notification_inbox"
CURRENT = "0102_pg_budget_control"
pytestmark = pytest.mark.skipif(
    not os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN"),
    reason="requires owned live PostgreSQL fixture",
)


def migrate(dsn: str, action: str, target: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "alembic", action, target],
        cwd=ROOT,
        env={**os.environ, "RECONFORGE_POSTGRES_DSN": dsn},
        capture_output=True,
        text=True,
        timeout=120,
    )


@pytest.fixture
def prior_database() -> Iterator[str]:
    import psycopg
    from psycopg import sql

    database = "reconforge_budget_migration_" + uuid4().hex[:12]
    control_dsn = psycopg.conninfo.make_conninfo(
        os.environ["RECONFORGE_TEST_POSTGRES_ADMIN_DSN"],
        dbname="postgres",
        connect_timeout=5,
    )
    admin_dsn = urlunsplit(
        urlsplit(os.environ["RECONFORGE_TEST_POSTGRES_ADMIN_DSN"])._replace(path="/" + database)
    )
    with psycopg.connect(control_dsn, autocommit=True) as control:
        control.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
    try:
        result = migrate(admin_dsn, "upgrade", PREVIOUS)
        assert result.returncode == 0, result.stderr
        yield admin_dsn
    finally:
        with psycopg.connect(control_dsn, autocommit=True) as control:
            control.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database)))
            assert control.execute("SELECT 1 FROM pg_database WHERE datname=%s", (database,)).fetchone() is None


def current_revision(connection: Any) -> str:
    row = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    assert row is not None
    return str(row[0])


def test_budget_migration_is_frozen_against_the_registered_schema() -> None:
    spec = importlib.util.spec_from_file_location("budget_frozen_migration", MIGRATION)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.revision == CURRENT
    assert module.down_revision == PREVIOUS
    assert module.POSTGRES_BUDGET_CONTROL_SCHEMA_SQL == POSTGRES_BUDGET_CONTROL_SCHEMA_SQL


def test_registered_budget_upgrade_is_forced_rls_and_downgrade_preserves_retained_evidence(prior_database: str) -> None:
    import psycopg

    result = migrate(prior_database, "upgrade", CURRENT)
    assert result.returncode == 0, result.stderr
    with psycopg.connect(prior_database, autocommit=True) as administrator:
        assert current_revision(administrator) == CURRENT
        tables = tuple(
            administrator.execute(
                "SELECT c.relname,c.relrowsecurity,c.relforcerowsecurity "
                "FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname='reconforge' AND c.relname=ANY(%s) ORDER BY c.relname",
                (["budget_envelopes", "budget_commitment_events", "budget_commands"],),
            )
        )
        assert tables == (
            ("budget_commands", True, True),
            ("budget_commitment_events", True, True),
            ("budget_envelopes", True, True),
        )

    result = migrate(prior_database, "downgrade", PREVIOUS)
    assert result.returncode == 0, result.stderr
    with psycopg.connect(prior_database, autocommit=True) as administrator:
        assert current_revision(administrator) == PREVIOUS
        removed = administrator.execute("SELECT to_regclass('reconforge.budget_envelopes')").fetchone()
        assert removed is not None and removed[0] is None

    result = migrate(prior_database, "upgrade", CURRENT)
    assert result.returncode == 0, result.stderr
    with psycopg.connect(prior_database, autocommit=True) as administrator:
        # The downgrade gate is independent of normal lifecycle admission.  The
        # synthetic retained row models evidence an older reader must not discard.
        administrator.execute("SET session_replication_role=replica")
        try:
            administrator.execute(
                "INSERT INTO reconforge.budget_envelopes "
                "(tenant_id,id,workspace_id,organization_id,legal_entity_id,period_id,budget_code,name,currency_code,"
                "limit_minor,reserved_minor,consumed_minor,currency_precision,currency_rounding_policy,"
                "currency_registry_version,currency_registry_digest,status,created_by,submitted_by,approved_by,"
                "reason,created_at,updated_at,row_version) "
                "VALUES ('retained','retained','workspace','organization','entity','period','RETAINED','Retained',"
                "'EGP',1,0,0,2,'half_even','synthetic','digest','Draft','maker',NULL,NULL,'retained',"
                "'2026-10-03T00:00:00Z','2026-10-03T00:00:00Z',1)"
            )
        finally:
            administrator.execute("SET session_replication_role=origin")
        retained_before = administrator.execute(
            "SELECT tenant_id,id,budget_code,limit_minor,row_version FROM reconforge.budget_envelopes"
        ).fetchone()

    result = migrate(prior_database, "downgrade", PREVIOUS)
    assert result.returncode != 0
    assert "Budget evidence history prevents downgrade" in result.stderr
    with psycopg.connect(prior_database, autocommit=True) as administrator:
        assert current_revision(administrator) == CURRENT
        retained_after = administrator.execute(
            "SELECT tenant_id,id,budget_code,limit_minor,row_version FROM reconforge.budget_envelopes"
        ).fetchone()
        assert retained_after == retained_before
