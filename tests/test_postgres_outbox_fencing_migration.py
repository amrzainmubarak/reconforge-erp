"""Registered PostgreSQL 0103 outbox-fencing migration acceptance."""

from __future__ import annotations

import ast
import importlib.util
import os
import subprocess
import sys
from collections.abc import Iterator
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "alembic/versions/0103_postgres_outbox_fencing.py"
PREVIOUS = "0102_pg_budget_control"
CURRENT = "0103_pg_outbox_fencing"
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

    database = "reconforge_outbox_fencing_migration_" + uuid4().hex[:12]
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


def current_revision(connection: object) -> str:
    row = connection.execute("SELECT version_num FROM alembic_version").fetchone()  # type: ignore[attr-defined]
    assert row is not None
    return str(row[0])


def test_outbox_fencing_migration_is_frozen_and_has_no_runtime_schema_dependency() -> None:
    spec = importlib.util.spec_from_file_location("outbox_fencing_frozen_migration", MIGRATION)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.revision == CURRENT
    assert module.down_revision == PREVIOUS
    tree = ast.parse(MIGRATION.read_text(encoding="utf-8"))
    assignments = {
        target.id: node.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }
    for name in ("UPGRADE_SQL", "DOWNGRADE_SQL"):
        value = assignments.get(name)
        assert isinstance(value, ast.Constant)
        assert isinstance(value.value, str)
    assert sha256(module.UPGRADE_SQL.encode("utf-8")).hexdigest() == (
        "6742413f1c92bdf694b5bacd975f72a2708e60192fad98b0fb0b732dbcab6355"
    )
    assert sha256(module.DOWNGRADE_SQL.encode("utf-8")).hexdigest() == (
        "f8358678b9f5584fa4c44cfe6c62ca5c06d602640888fd3f9dc5fd5682118fe2"
    )
    source = MIGRATION.read_text(encoding="utf-8")
    assert "outbox_fencing_schema" not in source
    assert "ACCESS EXCLUSIVE MODE" in module.UPGRADE_SQL
    assert "op.execute(UPGRADE_SQL)" in source


def _insert_legacy_delivery_states(connection: object) -> None:
    execute = connection.execute  # type: ignore[attr-defined]
    execute("INSERT INTO reconforge.tenants(id,name) VALUES ('outbox-existing','Outbox existing')")
    execute(
        """INSERT INTO reconforge.outbox_events
        (tenant_id,event_id,event_type,aggregate_type,aggregate_id,payload,status,attempt_count,claimed_at,claimed_by,
         published_at,last_error,dead_lettered_at)
        VALUES
        ('outbox-existing','pending','test','test','pending','{}'::jsonb,'Pending',0,NULL,NULL,NULL,NULL,NULL),
        ('outbox-existing','claimed','test','test','claimed','{}'::jsonb,'Claimed',3,clock_timestamp()+interval '1 hour','legacy-worker',NULL,NULL,NULL),
        ('outbox-existing','published','test','test','published','{}'::jsonb,'Published',1,NULL,NULL,clock_timestamp(),NULL,NULL),
        ('outbox-existing','dead','test','test','dead','{}'::jsonb,'Dead',4,NULL,NULL,NULL,'LEGACY_FAILURE',clock_timestamp())"""
    )


def test_registered_outbox_fencing_upgrade_watermarks_all_legacy_states_and_refuses_lossy_downgrade(
    prior_database: str,
) -> None:
    import psycopg

    with psycopg.connect(prior_database, autocommit=True) as administrator:
        _insert_legacy_delivery_states(administrator)
    result = migrate(prior_database, "upgrade", CURRENT)
    assert result.returncode == 0, result.stderr
    with psycopg.connect(prior_database, autocommit=True) as administrator:
        assert current_revision(administrator) == CURRENT
        states = tuple(
            administrator.execute(
                "SELECT event_id,status,lease_generation,lease_generation_floor FROM reconforge.outbox_events "
                "WHERE tenant_id='outbox-existing' ORDER BY event_id"
            ).fetchall()
        )
        assert states == (
            ("claimed", "Claimed", 2, 2),
            ("dead", "Dead", 2, 2),
            ("pending", "Pending", 2, 2),
            ("published", "Published", 2, 2),
        )
        evidence_table = administrator.execute(
            "SELECT relrowsecurity,relforcerowsecurity FROM pg_catalog.pg_class "
            "WHERE oid='reconforge.outbox_delivery_evidence'::regclass"
        ).fetchone()
        assert evidence_table == (True, True)
        evidence_count = administrator.execute("SELECT COUNT(*) FROM reconforge.outbox_delivery_evidence").fetchone()
        assert evidence_count is not None and evidence_count[0] == 0

    result = migrate(prior_database, "downgrade", PREVIOUS)
    assert result.returncode != 0
    assert "outbox fencing downgrade refused" in result.stderr
    with psycopg.connect(prior_database, autocommit=True) as administrator:
        assert current_revision(administrator) == CURRENT
        watermarked = administrator.execute(
            "SELECT COUNT(*) FROM reconforge.outbox_events WHERE lease_generation=2 AND lease_generation_floor=2"
        ).fetchone()
        assert watermarked is not None and watermarked[0] == 4


def test_registered_outbox_fencing_empty_upgrade_downgrade_and_reupgrade_are_reversible(prior_database: str) -> None:
    import psycopg

    result = migrate(prior_database, "upgrade", CURRENT)
    assert result.returncode == 0, result.stderr
    result = migrate(prior_database, "downgrade", PREVIOUS)
    assert result.returncode == 0, result.stderr
    with psycopg.connect(prior_database, autocommit=True) as administrator:
        assert current_revision(administrator) == PREVIOUS
        columns = tuple(
            row[0]
            for row in administrator.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='reconforge' AND table_name='outbox_events' ORDER BY column_name"
            ).fetchall()
        )
        assert "lease_generation" not in columns
        evidence_table = administrator.execute("SELECT to_regclass('reconforge.outbox_delivery_evidence')").fetchone()
        assert evidence_table is not None and evidence_table[0] is None
    result = migrate(prior_database, "upgrade", CURRENT)
    assert result.returncode == 0, result.stderr


def test_non_bypass_application_identity_cannot_run_the_registered_watermark_migration(prior_database: str) -> None:
    import psycopg
    from psycopg import sql

    app_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_DSN")
    if not app_dsn:
        pytest.skip("requires a separate nonowner application DSN")
    app_user = str(psycopg.conninfo.conninfo_to_dict(app_dsn)["user"])
    with psycopg.connect(prior_database, autocommit=True) as administrator:
        administrator.execute(sql.SQL("GRANT SELECT ON TABLE alembic_version TO {}").format(sql.Identifier(app_user)))
    app_target_dsn = urlunsplit(urlsplit(app_dsn)._replace(path=urlsplit(prior_database).path))
    result = migrate(app_target_dsn, "upgrade", CURRENT)
    assert result.returncode != 0
    assert "outbox fencing migration requires a role that bypasses forced row security" in result.stderr
    with psycopg.connect(prior_database, autocommit=True) as administrator:
        assert current_revision(administrator) == PREVIOUS
        columns = tuple(
            row[0]
            for row in administrator.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='reconforge' AND table_name='outbox_events' ORDER BY column_name"
            ).fetchall()
        )
        assert "lease_generation" not in columns
