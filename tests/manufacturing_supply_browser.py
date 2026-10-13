"""Original scoped MSP/SRC/AP/ME2 rows, native browser inputs and restore probes."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
from typing import Any

from reconforge.infrastructure.postgres import PostgresTenantBoundary
from reconforge.infrastructure.postgres_identity import PostgresIdentityRepository
from tests.erp_browser_seed import seed_erp_browser_principals
from tests.manufacturing_execution_v2_browser import MANUFACTURING_EXECUTION_V2_TABLES
from tests.test_postgres_manufacturing_execution_v2 import original_expense
from tests.test_postgres_manufacturing_supply_plan import TABLES, planning_runtime, seed_partial_stock

MANUFACTURING_SUPPLY_TABLES = tuple(dict.fromkeys((*MANUFACTURING_EXECUTION_V2_TABLES, *TABLES,
    "inventory_quantity_claim_gates", "inventory_quantity_source_guards", "inventory_quantity_source_releases",
    "procurement_sourcing_requisitions", "procurement_sourcing_quotes", "procurement_sourcing_events", "procurement_sourcing_commands",
    "procurement_partial_orders", "procurement_partial_order_lines", "procurement_partial_receipts", "procurement_partial_invoices",
    "procurement_partial_invoice_lines", "procurement_partial_commands", "procurement_commitment_plans", "procurement_commitment_commands",
    "budget_envelopes", "budget_commands", "budget_commitment_events", "ap_purchase_orders", "ap_goods_receipts", "ap_supplier_invoices",
    "operational_finance_plans", "operational_finance_reviews", "operational_finance_commands", "operational_finance_links")))
MANUFACTURING_SUPPLY_WORKSPACE_PROBE_TABLES = tuple(name for name in MANUFACTURING_SUPPLY_TABLES if name != "domain_audit_events")
MANUFACTURING_SUPPLY_TAMPER = (
    "UPDATE reconforge.manufacturing_supply_requirements SET shortage_quantity_scaled=shortage_quantity_scaled+1,onhand_reserved_scaled=onhand_reserved_scaled-1 WHERE tenant_id=%s",
    "DELETE FROM reconforge.inventory_quantity_source_releases WHERE tenant_id=%s",
    "DELETE FROM reconforge.manufacturing_supply_commands WHERE tenant_id=%s AND operation='handoff'",
)
MASTER_TABLES = ("finance_accounts", "inventory_items", "inventory_units_of_measure", "inventory_locations", "inventory_warehouses")
ROOT = Path(__file__).resolve().parents[1]


def manufacturing_supply_proof(runtime: Any, *, actor_name: str = "browser-poster") -> dict[str, Any]:
    """Export original native rows through the ordinary tenant role; no business calculations.

    PostgreSQL NUMERIC columns retain their original exact SQL decimal text;
    BIGINT columns retain JSON integer tokens. No identities or credentials enter
    this packet. Restore tables deliberately omit nullable global master catalogs.
    """
    from psycopg import sql

    with runtime.actor(actor_name) as (connection, _, _):
        role = connection.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone()
        flags = list(role.values()) if isinstance(role, dict) else list(role)
        if flags != [False, False]:
            raise ValueError("Original supply evidence requires a role without tenant RLS bypass")
        populations = {}
        numeric_text_columns = {}
        for name in (*MANUFACTURING_SUPPLY_TABLES, *MASTER_TABLES):
            columns = connection.execute("""SELECT column_name FROM information_schema.columns
                WHERE table_schema='reconforge' AND table_name=%s AND data_type='numeric' ORDER BY ordinal_position""", (name,)).fetchall()
            names = [row["column_name"] for row in columns]
            numeric_text_columns[name] = names
            expression: sql.Composable = sql.SQL("to_jsonb(t)")
            for column in names:
                expression += sql.SQL(" || jsonb_build_object({},t.{}::text)").format(sql.Literal(column), sql.Identifier(column))
            query = sql.SQL("SELECT {} value FROM reconforge.{} t WHERE tenant_id=%s ORDER BY to_jsonb(t)::text").format(expression, sql.Identifier(name))
            populations[name] = [row["value"] for row in connection.execute(query, (runtime.tenant,)).fetchall()]
    paths = ("reconforge/infrastructure/postgres_manufacturing_supply_plan.py",
        "reconforge/infrastructure/postgres_manufacturing_supply_plan_schema.py",
        "reconforge/infrastructure/postgres_inventory_quantity_source_ownership.py",
        "tests/manufacturing_supply_browser.py", ".github/scripts/verify_manufacturing_supply_cycle_oracle.py",
        ".github/scripts/verify_manufacturing_v2_cycle_oracle.py", ".github/scripts/verify_procurement_sourcing_oracle.py")
    return {"schema_version": "manufacturing-supply-proof-v1", "tenant_id": runtime.tenant,
        "capture": {"role_superuser": False, "role_bypassrls": False,
            "numeric_text_columns": numeric_text_columns,
            "source_files_sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in paths}},
        "populations": populations}


def export_manufacturing_supply_proof(runtime: Any, *, actor_name: str = "poster") -> None:
    destination = os.environ.get("RECONFORGE_MSP_NATIVE_PROOF_DIR")
    if destination:
        path = Path(destination) / "native-supply-original-populations.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(manufacturing_supply_proof(runtime, actor_name=actor_name), handle, sort_keys=True, indent=2, allow_nan=False)
            handle.write("\n")


def seed_manufacturing_supply_browser(admin_dsn: str, app_dsn: str) -> Any:
    """Only approved original masters/budget, partial stock and posted expense inputs."""
    runtime, _ = planning_runtime((admin_dsn, app_dsn))
    seed_partial_stock(runtime)
    original_expense(runtime, "LABOR", "SUPPLY-LABOR-SOURCE", "20.00")
    original_expense(runtime, "OVERHEAD", "SUPPLY-OH-SOURCE", "10.00")
    with PostgresTenantBoundary(runtime.factory).transaction(runtime.tenant) as connection:
        identity = PostgresIdentityRepository(connection)
        for permission in ("audit.read", "users.manage", "roles.manage", "security.center.read", "security.integrations.manage", "security.retention.manage"):
            identity.create_permission(tenant_id=runtime.tenant, permission_name=permission)
            identity.grant_permission(tenant_id=runtime.tenant, role_name="receipt-operator", permission_name=permission)
        for name in (*TABLES, "procurement_sourcing_requisitions", "procurement_sourcing_quotes", "procurement_partial_orders",
                "manufacturing_execution_orders", "manufacturing_execution_v2_orders"):
            if connection.execute("SELECT count(*) n FROM reconforge." + name + " WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"]:
                raise AssertionError("The browser must create the original planning, purchase and production documents: " + name)
    seed_erp_browser_principals(runtime)
    return runtime


def manufacturing_supply_browser_configuration(runtime: Any) -> dict[str, Any]:
    with runtime.actor("browser-poster") as (connection, _, _):
        bom = connection.execute("SELECT id FROM reconforge.manufacturing_execution_boms WHERE tenant_id=%s AND phase=1", (runtime.tenant,)).fetchone()
        route = connection.execute("SELECT id FROM reconforge.manufacturing_execution_v2_definitions WHERE tenant_id=%s AND kind='Routing' AND phase=1", (runtime.tenant,)).fetchone()
        budget = connection.execute("SELECT id FROM reconforge.budget_envelopes WHERE tenant_id=%s", (runtime.tenant,)).fetchone()
        claims = connection.execute("""SELECT e.id effect_id,l.id line_id,a.account_code
            FROM reconforge.finance_posting_effects e JOIN reconforge.finance_entry_lines l ON l.tenant_id=e.tenant_id AND l.entry_id=e.entry_id
            JOIN reconforge.finance_accounts a ON a.tenant_id=l.tenant_id AND a.id=l.account_id
            WHERE e.tenant_id=%s AND a.account_code IN('LABOR','OVERHEAD') AND l.debit_minor>0 ORDER BY a.account_code""", (runtime.tenant,)).fetchall()
    return {"bom_version_id": bom["id"], "routing_id": route["id"], "budget_id": budget["id"],
        "cost_claims": [{"effect_id": row["effect_id"], "line_id": row["line_id"],
            "kind": "Labor" if row["account_code"] == "LABOR" else "Overhead", "operation_sequence": 1,
            "minutes": 60 if row["account_code"] == "LABOR" else 30, "rate_minor_per_hour": "600"} for row in claims]}


def verify_manufacturing_supply_browser(runtime: Any) -> dict[str, Any]:
    path = ROOT / ".github/scripts/verify_manufacturing_supply_cycle_oracle.py"
    spec = importlib.util.spec_from_file_location("msp_independent_native_oracle", path)
    if spec is None or spec.loader is None:
        raise AssertionError("The original stdlib supply verifier is unavailable")
    oracle = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(oracle)
    proof = manufacturing_supply_proof(runtime)
    result = oracle.verify_proof(proof)
    if tuple(result[key] for key in ("issued_material_minor", "total_cost_minor", "finished_cost_minor", "abnormal_loss_minor", "remaining_wip_minor")) != ("2700", "3600", "3240", "360", "0"):
        raise AssertionError("Original browser manufacture differs from the independent synthetic source arithmetic")
    populations = proof["populations"]
    if len(populations["procurement_partial_receipts"]) != 2 or len(populations["procurement_partial_invoices"]) != 2:
        raise AssertionError("The browser must retain two actual shortage receipts and two accrued AP documents")
    commands = populations["manufacturing_supply_commands"]
    actors = {row["operation"]: row["actor_id"] for row in commands}
    if (actors["create"], actors["approve"], actors["source-award"], actors["handoff"]) != ("erp-maker", "erp-checker", "erp-poster", "erp-maker"):
        raise AssertionError("The original browser plan, approval, award and handoff require the actual ERP humans")
    return {**result, "independent_financial_proof": proof}
