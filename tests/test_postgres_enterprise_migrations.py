"""Real current-head migration/rollback and no automatic operating privileges."""

from __future__ import annotations

import os
import subprocess  # nosec B404
import sys
from pathlib import Path
from uuid import uuid4

import psycopg

from reconforge.infrastructure.postgres import PostgresTenantBoundary
from reconforge.infrastructure.postgres_identity import PostgresIdentityRepository
from reconforge.infrastructure.postgres_operations import POSTGRES_MIGRATION_REVISIONS
from tests.postgres_seed_contract import CURRENT_TENANT_SEEDED_PERMISSIONS
from tests.test_postgres_inventory_receipt_posting import create_receipt_runtime
from tests.test_postgres_inventory_receipt_posting import receipt_database as enterprise_database

_ = enterprise_database
ROOT = Path(__file__).parents[1]
HEAD = "0148_pg_partial_return_rounding"
TABLES = (
    "customer_partial_return_allocation_witnesses",
    "customer_partial_return_sources", "customer_partial_return_plans", "customer_partial_return_events",
    "customer_partial_return_history", "customer_partial_return_restorations", "customer_partial_return_commands",
    "inventory_transfer_sources", "inventory_transfer_claims", "inventory_transfer_releases",
    "inventory_transfer_events", "inventory_transfer_commands",
    "manufacturing_supply_plans", "manufacturing_supply_requirements", "manufacturing_supply_stock_claims",
    "manufacturing_supply_stock_releases", "manufacturing_supply_procurement_claims", "manufacturing_supply_events",
    "manufacturing_supply_commands", "inventory_quantity_source_guards", "inventory_quantity_source_releases",
    "inventory_quantity_claim_gates", "pb_prices", "pb_plans", "pb_commands", "pb_time_claims", "pb_claim_events",
    "pb_claim_heads", "pb_account_pins",
    "accrual_deferral_sources", "accrual_deferral_plans", "accrual_deferral_account_pins", "accrual_deferral_period_pins",
    "accrual_deferral_phase_events", "accrual_deferral_claim_events", "accrual_deferral_claim_heads",
    "accrual_deferral_original_claims", "accrual_deferral_original_releases", "accrual_deferral_commands",
    "financial_effect_claim_gates", "financial_effect_ownership_guards", "financial_effect_ownership_releases",
    "manufacturing_execution_v2_definitions", "manufacturing_execution_v2_orders", "manufacturing_execution_v2_cost_claims",
    "manufacturing_execution_v2_cost_releases", "manufacturing_execution_v2_productions", "manufacturing_execution_v2_inspections",
    "manufacturing_execution_v2_events", "manufacturing_execution_v2_commands", "intercompany_fx_sources", "intercompany_fx_plans",
    "intercompany_fx_reviews", "intercompany_fx_links", "intercompany_fx_post_evidence", "intercompany_fx_commands",
    "hc_employees", "hc_employee_private", "hc_employments", "hc_rates", "hc_projects", "hc_times", "hc_payruns",
    "hc_payrun_private", "hc_payments", "hc_payment_private", "hc_time_claims", "hc_claim_events", "hc_claim_heads", "hc_commands",
)


def migrate(dsn: str, operation: str, revision: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "alembic", operation, revision], cwd=ROOT,
        env={**os.environ, "RECONFORGE_POSTGRES_DSN": dsn}, capture_output=True, text=True, timeout=180, check=False,
    )  # nosec B603


def test_actual_empty_current_head_roundtrip_preserves_original_core(enterprise_database: tuple[str, str]) -> None:
    admin, app = enterprise_database
    assert len(POSTGRES_MIGRATION_REVISIONS) == 147 and POSTGRES_MIGRATION_REVISIONS[-1] == HEAD
    assert not any(revision.startswith("0137_") for revision in POSTGRES_MIGRATION_REVISIONS)
    with psycopg.connect(admin) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (HEAD,)
        flags = connection.execute(
            "SELECT relname,relrowsecurity,relforcerowsecurity FROM pg_class WHERE relnamespace='reconforge'::regnamespace AND relname=ANY(%s)",
            (list(TABLES),),
        ).fetchall()
        assert len(flags) == len(TABLES) and all(row[1:] == (True, True) for row in flags)
        assert connection.execute("SELECT rolcanlogin,rolsuper,rolbypassrls,rolcreaterole,rolcreatedb,rolinherit,rolreplication FROM pg_roles WHERE rolname='reconforge_personnel_runtime'").fetchone() == (False,) * 7
    result = migrate(admin, "downgrade", "0136_pg_inventory_scope")
    assert result.returncode == 0, result.stderr
    with psycopg.connect(admin) as connection:
        assert all(connection.execute("SELECT to_regclass(%s)", ("reconforge." + table,)).fetchone()[0] is None for table in TABLES)
        assert connection.execute("SELECT to_regprocedure('reconforge.fx_convert_inverse(numeric,numeric,integer,integer)')").fetchone() == (None,)
        assert connection.execute("SELECT to_regclass('reconforge.manufacturing_execution_orders')").fetchone()[0] is not None
        assert connection.execute("SELECT to_regprocedure('reconforge.me1_close(text,text)')").fetchone()[0] is not None
    result = migrate(admin, "upgrade", HEAD)
    assert result.returncode == 0, result.stderr
    with psycopg.connect(app) as connection:
        assert connection.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=session_user").fetchone() == (False, False)
        assert connection.execute("SELECT pg_has_role(session_user,'reconforge_personnel_runtime','MEMBER')").fetchone() == (False,)


def test_current_head_catalog_grants_nothing_and_refuses_retained_privileges(enterprise_database: tuple[str, str]) -> None:
    runtime = create_receipt_runtime(enterprise_database)
    namespaces = ("manufacturing_execution_v2.", "intercompany_fx.", "people_project_payroll.", "accrual_deferral.",
                  "manufacturing_supply_plan.", "project_time_billing.", "inventory_transfer.")
    with PostgresTenantBoundary(runtime.factory).transaction(runtime.tenant) as connection:
        names = {row["name"] for row in connection.execute("SELECT name FROM reconforge.identity_permissions WHERE tenant_id=%s", (runtime.tenant,))}
        assert names >= CURRENT_TENANT_SEEDED_PERMISSIONS
        grants = {row["permission_name"] for row in connection.execute("SELECT permission_name FROM reconforge.identity_role_permissions WHERE tenant_id=%s", (runtime.tenant,))}
        assert not any(name.startswith(namespaces) for name in grants)
        identity = PostgresIdentityRepository(connection)
        role = "reviewed-personnel-" + uuid4().hex[:8]
        identity.create_role(tenant_id=runtime.tenant, role_name=role)
        identity.grant_permission(tenant_id=runtime.tenant, role_name=role, permission_name="people_project_payroll.read_sensitive")
    result = migrate(enterprise_database[0], "downgrade", "0139_pg_intercompany_fx")
    assert result.returncode != 0 and "Retained permission grants prevent downgrade" in result.stderr
    with psycopg.connect(enterprise_database[0]) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (HEAD,)
        assert all(connection.execute("SELECT to_regclass(%s)", ("reconforge." + table,)).fetchone()[0] is not None for table in TABLES)
