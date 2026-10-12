"""Mandatory native linear upgrade/rollback and least-privilege catalog evidence."""
from __future__ import annotations

import os
import subprocess  # nosec B404
import sys
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest

from reconforge.infrastructure.postgres import PostgresTenantBoundary
from reconforge.infrastructure.postgres_identity import PostgresIdentityRepository
from tests.postgres_seed_contract import CURRENT_TENANT_SEEDED_PERMISSIONS
from tests.test_postgres_inventory_receipt_posting import create_receipt_runtime
from tests.test_postgres_inventory_receipt_posting import receipt_database as wave5_database

_ = wave5_database
ROOT = Path(__file__).parents[1]
HEAD = "0136_pg_inventory_scope"
PREFIXES = ("manufacturing_execution.", "intercompany_operations.", "procurement_sourcing.")
TABLES = (
    "manufacturing_execution_boms", "manufacturing_execution_orders", "manufacturing_execution_requirements",
    "manufacturing_execution_reservations", "manufacturing_execution_completions", "manufacturing_execution_events",
    "manufacturing_execution_commands", "intercompany_operation_sources", "intercompany_operation_plans",
    "intercompany_operation_reviews", "intercompany_operation_links", "intercompany_operation_post_evidence",
    "intercompany_operation_commands", "procurement_sourcing_requisitions", "procurement_sourcing_quotes",
    "procurement_sourcing_events", "procurement_sourcing_commands",
)


def migrate(dsn: str, operation: str, revision: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "-m", "alembic", operation, revision], cwd=ROOT,
                          env={**os.environ, "RECONFORGE_POSTGRES_DSN": dsn}, capture_output=True,
                          text=True, timeout=180, check=False)  # nosec B603


def test_actual_empty_wave5_roundtrip_preserves_original_capacity_and_rls(wave5_database: tuple[str, str]) -> None:
    admin_dsn, app_dsn = wave5_database
    with psycopg.connect(admin_dsn) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone()[0] == HEAD
        flags = connection.execute("""SELECT relname,relrowsecurity,relforcerowsecurity FROM pg_class
            WHERE relnamespace='reconforge'::regnamespace AND relname=ANY(%s) ORDER BY relname""", (list(TABLES),)).fetchall()
        assert len(flags) == len(TABLES) and all(row[1:] == (True, True) for row in flags)
        original = connection.execute("SELECT pg_get_functiondef('reconforge.stock_sales_capacity_pre_me1(text,text,text,text,text)'::regprocedure)").fetchone()[0]
    result = migrate(admin_dsn, "downgrade", "0132_pg_stock_inverse_dispatch")
    assert result.returncode == 0, result.stderr
    with psycopg.connect(admin_dsn) as connection:
        restored = connection.execute("SELECT pg_get_functiondef('reconforge.stock_sales_capacity(text,text,text,text,text)'::regprocedure)").fetchone()[0]
        assert restored == original.replace("stock_sales_capacity_pre_me1", "stock_sales_capacity", 1)
        assert all(connection.execute("SELECT to_regclass(%s)", ("reconforge." + name,)).fetchone()[0] is None for name in TABLES)
    result = migrate(admin_dsn, "upgrade", "head")
    assert result.returncode == 0, result.stderr
    with psycopg.connect(app_dsn) as connection:
        assert connection.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone() == (False, False)


def test_current_tenant_catalog_grants_nothing_and_retained_grant_refuses_downgrade(wave5_database: tuple[str, str]) -> None:
    system = create_receipt_runtime(wave5_database)
    with PostgresTenantBoundary(system.factory).transaction(system.tenant) as connection:
        names = {row["name"] for row in connection.execute("SELECT name FROM reconforge.identity_permissions WHERE tenant_id=%s", (system.tenant,))}
        assert names >= CURRENT_TENANT_SEEDED_PERMISSIONS
        granted = {row["permission_name"] for row in connection.execute("SELECT permission_name FROM reconforge.identity_role_permissions WHERE tenant_id=%s", (system.tenant,))}
        assert not any(name.startswith(PREFIXES) for name in granted)
        identity = PostgresIdentityRepository(connection)
        role = "reviewed-sourcing-" + uuid4().hex[:8]
        identity.create_role(tenant_id=system.tenant, role_name=role)
        identity.grant_permission(tenant_id=system.tenant, role_name=role, permission_name="procurement_sourcing.read")
    result = migrate(wave5_database[0], "downgrade", "0134_pg_intercompany_operations")
    assert result.returncode != 0 and "Retained permission grants prevent downgrade" in result.stderr
    with psycopg.connect(wave5_database[0]) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone()[0] == HEAD
        assert all(connection.execute("SELECT to_regclass(%s)", ("reconforge." + name,)).fetchone()[0] is not None for name in TABLES)
    with pytest.raises(KeyError):
        # Ordinary schema integrity uses parameterized names; caller SQL is never accepted.
        from reconforge.infrastructure.postgres_wave5_permission_schema import permission_upgrade_sql
        permission_upgrade_sql("untrusted_identifier")
