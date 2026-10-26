"""Real current-head migration/rollback and no automatic operating privileges."""

from __future__ import annotations

import os
import subprocess  # nosec B404
import sys
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest

from reconforge.domain.crm_contracts import CustomerQuotation, QuotationLineItem
from reconforge.infrastructure.postgres import PostgresTenantBoundary
from reconforge.infrastructure.postgres_crm_contracts import PostgresCRMContractsRepository
from reconforge.infrastructure.postgres_enterprise_modules_schema import REGISTERED_MODULE_TABLES
from reconforge.infrastructure.postgres_hcm_leave import POSTGRES_HCM_LEAVE_SCHEMA_SQL
from reconforge.infrastructure.postgres_identity import PostgresIdentityRepository
from reconforge.infrastructure.postgres_operations import POSTGRES_MIGRATION_REVISIONS
from tests.postgres_seed_contract import CURRENT_TENANT_SEEDED_PERMISSIONS
from tests.test_postgres_inventory_receipt_posting import create_receipt_runtime
from tests.test_postgres_inventory_receipt_posting import receipt_database as _receipt_database


@pytest.fixture
def enterprise_database() -> Iterator[tuple[str, str]]:
    """Each migration history owns a database; populated downgrade guards persist."""
    yield from _receipt_database.__wrapped__()


ROOT = Path(__file__).parents[1]
HEAD = "0157_pg_quality_actor_authority"
TABLES = (
    "stock_sales_monetary_origins", "customer_partial_return_monetary_plans", "customer_partial_return_monetary_entries",
    "customer_partial_return_monetary_events", "customer_partial_return_monetary_history",
    "customer_partial_return_monetary_restorations", "customer_partial_return_monetary_commands",
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
    "shop_floor_lots", "shop_floor_lot_genealogy", "shop_floor_dispatches", "shop_floor_steps",
    "project_wbs_tasks", "project_resource_rate_cards", "project_milestones", "project_milestone_invoices", "project_time_logs",
    "mps_plans", "mps_sourcing_requisitions",
    "consolidated_statement_runs",
    "intercompany_profit_in_stock_rules", "intercompany_profit_in_stock_eliminations",
)


def migrate(dsn: str, operation: str, revision: str) -> subprocess.CompletedProcess[str]:
    runner = "import sys, os; sys.path = [p for p in sys.path if os.path.abspath(p) != os.getcwd()] + [os.getcwd()]; from alembic.config import CommandLine; CommandLine().main()"
    return subprocess.run(
        [sys.executable, "-c", runner, operation, revision], cwd=ROOT,
        env={**os.environ, "RECONFORGE_POSTGRES_DSN": dsn}, capture_output=True, text=True, timeout=180, check=False,
    )  # nosec B603


def test_actual_empty_current_head_roundtrip_preserves_original_core(enterprise_database: tuple[str, str]) -> None:
    admin, app = enterprise_database
    assert len(POSTGRES_MIGRATION_REVISIONS) == 156 and POSTGRES_MIGRATION_REVISIONS[-1] == HEAD
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
        assert connection.execute("SELECT to_regclass('reconforge.intercompany_elimination_artifacts')").fetchone()[0] is not None
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


def test_populated_historical_modules_upgrade_preserves_records_and_refuses_data_loss(
    enterprise_database: tuple[str, str],
) -> None:
    admin, _ = enterprise_database
    runtime = create_receipt_runtime(enterprise_database)
    result = migrate(admin, "downgrade", "0152_pg_performance_indexes")
    assert result.returncode == 0, result.stderr
    with psycopg.connect(admin) as connection:
        connection.execute("""INSERT INTO reconforge.project_milestones
            (tenant_id,workspace_id,milestone_id,project_id,contract_line_id,title,milestone_amount_minor,currency,due_date,status)
            VALUES(%s,'work','legacy-ms','legacy-project','line','Retained source',3001,'USD','2026-10-25','pending')""", (runtime.tenant,))
        connection.execute("""INSERT INTO reconforge.intercompany_elimination_artifacts
            (tenant_id,id,workspace_id,reporting_currency,version,request_digest,result_digest,request_payload,result_payload,prepared_by,prepared_at)
            VALUES(%s,%s,'work','USD','1.0.0',%s,%s,'{}','{}',%s,'2026-10-25T00:00:00Z')""",
            (runtime.tenant, "ice-" + uuid4().hex, "1" * 64, "2" * 64,
             connection.execute("SELECT id FROM reconforge.identity_users WHERE tenant_id=%s AND username='maker'", (runtime.tenant,)).fetchone()[0]))
        original_artifact = connection.execute("SELECT to_jsonb(t) FROM reconforge.intercompany_elimination_artifacts t WHERE tenant_id=%s", (runtime.tenant,)).fetchone()[0]
    result = migrate(admin, "downgrade", "0150_pg_native_query_plans")
    assert result.returncode != 0 and "Populated enterprise records prevent downgrade" in result.stderr
    with psycopg.connect(admin) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0152_pg_performance_indexes"
        connection.execute(POSTGRES_HCM_LEAVE_SCHEMA_SQL)
        connection.execute("""INSERT INTO reconforge.hcm_leave_entitlement_balances
            (tenant_id,workspace_id,employee_id,leave_type,annual_entitlement_days,accrued_days,consumed_days)
            VALUES(%s,'work','legacy-employee','Annual',30,20,3)""", (runtime.tenant,))
        before = connection.execute("SELECT to_jsonb(t) FROM reconforge.hcm_leave_entitlement_balances t WHERE tenant_id=%s", (runtime.tenant,)).fetchone()[0]
    result = migrate(admin, "upgrade", HEAD)
    assert result.returncode == 0, result.stderr
    with psycopg.connect(admin) as connection:
        assert connection.execute("SELECT to_jsonb(t) FROM reconforge.hcm_leave_entitlement_balances t WHERE tenant_id=%s", (runtime.tenant,)).fetchone()[0] == before
        assert connection.execute("SELECT milestone_amount_minor,organization_id,legal_entity_id FROM reconforge.project_milestones WHERE tenant_id=%s AND milestone_id='legacy-ms'", (runtime.tenant,)).fetchone() == (3001, None, None)
        assert connection.execute("SELECT to_jsonb(t) FROM reconforge.intercompany_elimination_artifacts t WHERE tenant_id=%s", (runtime.tenant,)).fetchone()[0] == original_artifact
        flags = connection.execute("SELECT relname,relrowsecurity,relforcerowsecurity FROM pg_class WHERE relnamespace='reconforge'::regnamespace AND relname=ANY(%s)", (list(REGISTERED_MODULE_TABLES),)).fetchall()
        assert len(flags) == len(REGISTERED_MODULE_TABLES) and all(row[1:] == (True, True) for row in flags)
    result = migrate(admin, "downgrade", "0152_pg_performance_indexes")
    assert result.returncode != 0 and "Populated leave records prevent scope downgrade" in result.stderr
    with psycopg.connect(admin) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone()[0] == HEAD
        assert connection.execute("SELECT to_jsonb(t) FROM reconforge.hcm_leave_entitlement_balances t WHERE tenant_id=%s", (runtime.tenant,)).fetchone()[0] == before


def test_0155_upgrades_existing_0154_without_inventing_legacy_authorship(enterprise_database: tuple[str, str]) -> None:
    runtime = create_receipt_runtime(enterprise_database)
    # Prior down/up cases deliberately recreate module tables without operating
    # grants. Deployment ACLs are explicit, never installed by migrations.
    from psycopg import sql
    app_user = psycopg.conninfo.conninfo_to_dict(enterprise_database[1])["user"]
    with psycopg.connect(enterprise_database[0]) as connection:
        connection.execute(sql.SQL("GRANT SELECT,INSERT,UPDATE,DELETE ON reconforge.crm_quotations,reconforge.crm_quotation_lines TO {}").format(sql.Identifier(app_user)))
    result = migrate(enterprise_database[0], "downgrade", "0154_pg_enterprise_finance")
    assert result.returncode == 0, result.stderr
    with PostgresTenantBoundary(runtime.factory).transaction(runtime.tenant, workspace_id="work") as connection:
        repository = PostgresCRMContractsRepository(connection, runtime.tenant)
        repository.save_quotation(CustomerQuotation(
            "Q-LEGACY-155", "OP", "work", "CUSTOMER", "USD", "2026-12-31",
            "historical-display-name", "draft", (QuotationLineItem(1, "SERVICE", "Synthetic legacy", 1, 1001),),
        ))
        original = repository.get_quotation("work", "Q-LEGACY-155")
    result = migrate(enterprise_database[0], "upgrade", HEAD)
    assert result.returncode == 0, result.stderr
    with psycopg.connect(enterprise_database[0]) as connection:
        connection.execute(sql.SQL("GRANT SELECT,INSERT,UPDATE,DELETE ON reconforge.crm_quotation_authorities TO {}").format(sql.Identifier(app_user)))
    with PostgresTenantBoundary(runtime.factory).transaction(runtime.tenant, workspace_id="work") as connection:
        repository = PostgresCRMContractsRepository(connection, runtime.tenant)
        assert repository.get_quotation("work", "Q-LEGACY-155") == original
        assert repository.quotation_author_id("work", "Q-LEGACY-155") is None
