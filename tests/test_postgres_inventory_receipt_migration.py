"""Additive receipt migration: historical preservation, atomic collision refusal and rollback."""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import pytest

from reconforge.infrastructure.postgres_inventory_receipt_posting_schema import (
    POSTGRES_INVENTORY_RECEIPT_POSTING_SCHEMA_SQL,
)
from tests.test_postgres_inventory_receipt_posting import ReceiptRuntime
from tests.test_postgres_inventory_receipt_posting import receipt_runtime as runtime_factory
from tests.test_postgres_inventory_receipt_schema import committed, ordinary

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "alembic/versions/0100_postgres_inventory_receipt_posting.py"
pytestmark = pytest.mark.skipif(not os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN"), reason="requires owned live PostgreSQL fixture")


def migrate(dsn: str, action: str, target: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "-m", "alembic", action, target], cwd=ROOT,
        env={**os.environ, "RECONFORGE_POSTGRES_DSN": dsn}, capture_output=True, text=True, timeout=120)


@pytest.fixture
def old_database() -> Iterator[tuple[str, str]]:
    import psycopg
    from psycopg import sql
    database = "reconforge_irp_migration_" + uuid4().hex[:12]
    control_dsn = psycopg.conninfo.make_conninfo(os.environ["RECONFORGE_TEST_POSTGRES_ADMIN_DSN"], dbname="postgres", connect_timeout=5)
    admin_dsn = urlunsplit(urlsplit(os.environ["RECONFORGE_TEST_POSTGRES_ADMIN_DSN"])._replace(path="/" + database))
    app_dsn = psycopg.conninfo.make_conninfo(os.environ["RECONFORGE_TEST_POSTGRES_DSN"], dbname=database)
    with psycopg.connect(control_dsn, autocommit=True) as control:
        control.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
    try:
        result = migrate(admin_dsn, "upgrade", "0099_pg_receivables_policy")
        assert result.returncode == 0, result.stderr
        with psycopg.connect(admin_dsn) as admin:
            role = psycopg.conninfo.conninfo_to_dict(app_dsn)["user"]
            admin.execute(sql.SQL("GRANT USAGE ON SCHEMA reconforge TO {}").format(sql.Identifier(role)))
            admin.execute(sql.SQL("GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA reconforge TO {}").format(sql.Identifier(role)))
            admin.execute(sql.SQL("GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA reconforge TO {}").format(sql.Identifier(role)))
        yield admin_dsn, app_dsn
    finally:
        with psycopg.connect(control_dsn, autocommit=True) as control:
            control.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database)))
            assert control.execute("SELECT 1 FROM pg_database WHERE datname=%s", (database,)).fetchone() is None


def current_revision(admin) -> str:
    return admin.execute("SELECT version_num FROM alembic_version").fetchone()[0]


def test_frozen_migration_matches_current_installer_bytes() -> None:
    spec = importlib.util.spec_from_file_location("receipt_frozen_migration", MIGRATION)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.UPGRADE_SQL == POSTGRES_INVENTORY_RECEIPT_POSTING_SCHEMA_SQL
    assert module.revision == "0100_pg_inventory_receipt"
    assert module.down_revision == "0099_pg_receivables_policy"


def test_empty_upgrade_and_downgrade_preserve_original_finance_guard(old_database: tuple[str, str]) -> None:
    import psycopg
    admin_dsn, _ = old_database
    with psycopg.connect(admin_dsn) as admin:
        original = admin.execute("SELECT pg_get_functiondef('reconforge.guard_finance_posting_effect()'::regprocedure)").fetchone()[0]
    result = migrate(admin_dsn, "upgrade", "0100_pg_inventory_receipt")
    assert result.returncode == 0, result.stderr
    with psycopg.connect(admin_dsn) as admin:
        assert current_revision(admin) == "0100_pg_inventory_receipt"
        assert admin.execute("SELECT pg_get_functiondef('reconforge.guard_finance_posting_effect()'::regprocedure)").fetchone()[0] == original
    result = migrate(admin_dsn, "downgrade", "0099_pg_receivables_policy")
    assert result.returncode == 0, result.stderr
    with psycopg.connect(admin_dsn) as admin:
        assert current_revision(admin) == "0099_pg_receivables_policy"
        assert admin.execute("SELECT to_regclass('reconforge.inventory_receipt_plans')").fetchone()[0] is None
        assert admin.execute("SELECT pg_get_functiondef('reconforge.guard_finance_posting_effect()'::regprocedure)").fetchone()[0] == original
        assert admin.execute("SELECT count(*) FROM pg_constraint WHERE conrelid='reconforge.finance_posting_effects'::regclass AND conname IN ('finance_posting_effects_source_kind_check','finance_posting_effects_check')").fetchone()[0] == 2


@pytest.mark.parametrize("field", ["id", "movement_number"])
def test_historical_casefolded_namespace_collision_refuses_atomic_upgrade(old_database: tuple[str, str], field: str) -> None:
    import psycopg
    from psycopg import sql
    admin_dsn, _ = old_database
    runtime: ReceiptRuntime = runtime_factory.__wrapped__(old_database)
    identifier = ordinary(runtime)
    with psycopg.connect(admin_dsn) as admin:
        if field == "movement_number":
            admin.execute("UPDATE reconforge.inventory_movements SET movement_number='iRp1-HISTORICAL' WHERE tenant_id=%s AND id=%s", (runtime.tenant, identifier))
        else:
            admin.execute("INSERT INTO reconforge.inventory_movements SELECT (jsonb_populate_record(NULL::reconforge.inventory_movements,to_jsonb(m)||jsonb_build_object('id','iRp1-HISTORICAL','movement_number','HISTORICAL-2'))).* FROM reconforge.inventory_movements m WHERE tenant_id=%s AND id=%s", (runtime.tenant, identifier))
        before = admin.execute("SELECT jsonb_agg(to_jsonb(m) ORDER BY id) FROM reconforge.inventory_movements m").fetchone()[0]
    result = migrate(admin_dsn, "upgrade", "0100_pg_inventory_receipt")
    assert result.returncode != 0 and "namespace is occupied" in result.stderr
    with psycopg.connect(admin_dsn) as admin:
        assert current_revision(admin) == "0099_pg_receivables_policy"
        assert admin.execute("SELECT to_regclass('reconforge.inventory_receipt_plans')").fetchone()[0] is None
        assert admin.execute("SELECT jsonb_agg(to_jsonb(m) ORDER BY id) FROM reconforge.inventory_movements m").fetchone()[0] == before
        assert admin.execute(f"SELECT count(*) FROM reconforge.inventory_movements WHERE {sql.Identifier(field).as_string(admin)}='iRp1-HISTORICAL'").fetchone()[0] == 1


def test_populated_source_downgrade_refuses_without_losing_history(old_database: tuple[str, str]) -> None:
    import psycopg
    from psycopg import sql
    admin_dsn, app_dsn = old_database
    assert migrate(admin_dsn, "upgrade", "0100_pg_inventory_receipt").returncode == 0
    with psycopg.connect(admin_dsn) as admin:
        admin.execute(sql.SQL("GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA reconforge TO {}").format(sql.Identifier(psycopg.conninfo.conninfo_to_dict(app_dsn)["user"])))
    runtime: ReceiptRuntime = runtime_factory.__wrapped__(old_database)
    plan, _, effect = committed(runtime)
    with psycopg.connect(admin_dsn) as admin:
        before = admin.execute("SELECT jsonb_agg(to_jsonb(p) ORDER BY id) FROM reconforge.inventory_receipt_plans p").fetchone()[0]
        revision = current_revision(admin)
    result = migrate(admin_dsn, "downgrade", "0099_pg_receivables_policy")
    assert result.returncode != 0 and "history prevents downgrade" in result.stderr
    with psycopg.connect(admin_dsn) as admin:
        assert current_revision(admin) == revision
        assert admin.execute("SELECT jsonb_agg(to_jsonb(p) ORDER BY id) FROM reconforge.inventory_receipt_plans p").fetchone()[0] == before
    with runtime.actor("poster") as (_, repository, actor):
        assert repository.get_effect(plan["plan_id"], actor=actor) == effect
