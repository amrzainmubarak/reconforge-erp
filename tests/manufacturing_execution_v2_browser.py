"""Actual ME2 native proof and browser seed; no identity/credential export."""
from typing import Any

from reconforge.infrastructure.postgres import PostgresTenantBoundary
from reconforge.infrastructure.postgres_identity import PostgresIdentityRepository
from tests.erp_browser_seed import seed_erp_browser_principals
from tests.manufacturing_execution_browser import MANUFACTURING_EXECUTION_TABLES
from tests.test_postgres_manufacturing_execution_v2 import approved_bom, original_expense, system

MANUFACTURING_EXECUTION_V2_TABLES = (*MANUFACTURING_EXECUTION_TABLES,
    *("manufacturing_execution_v2_" + name for name in (
        "definitions", "orders", "cost_claims", "cost_releases", "productions", "inspections", "events", "commands")),
    "financial_effect_claim_gates", "financial_effect_ownership_guards", "financial_effect_ownership_releases")
MANUFACTURING_EXECUTION_V2_WORKSPACE_PROBE_TABLES = tuple(
    name for name in MANUFACTURING_EXECUTION_V2_TABLES if name != "domain_audit_events")
MANUFACTURING_EXECUTION_V2_TAMPER = (
    "UPDATE reconforge.manufacturing_execution_v2_cost_claims SET amount_minor=amount_minor+1 WHERE tenant_id=%s",
    "UPDATE reconforge.manufacturing_execution_v2_inspections SET receipt_effect=NULL WHERE tenant_id=%s AND phase=2",
    "DELETE FROM reconforge.manufacturing_execution_v2_commands WHERE tenant_id=%s",
)


def manufacturing_execution_v2_proof(runtime: Any, *, actor_name: str = "browser-poster") -> dict[str, Any]:
    from psycopg import sql

    with runtime.actor(actor_name) as (connection, _, _):
        populations = {}
        for name in (*MANUFACTURING_EXECUTION_V2_TABLES, "finance_accounts"):
            statement = sql.SQL("SELECT to_jsonb(t) payload FROM reconforge.{} t WHERE tenant_id=%s ORDER BY to_jsonb(t)::text").format(sql.Identifier(name))
            populations[name] = [row["payload"] for row in connection.execute(statement, (runtime.tenant,)).fetchall()]
    return {"schema_version": "manufacturing-execution-proof-v2", "tenant_id": runtime.tenant, "populations": populations}


def seed_manufacturing_execution_v2_browser(admin_dsn: str, app_dsn: str) -> Any:
    runtime = system((admin_dsn, app_dsn))
    approved_bom(runtime)
    original_expense(runtime, "LABOR", "LABOR-SOURCE", "20.00")
    original_expense(runtime, "OVERHEAD", "OH-SOURCE", "10.00")
    with PostgresTenantBoundary(runtime.factory).transaction(runtime.tenant) as connection:
        identity = PostgresIdentityRepository(connection)
        for permission in ("audit.read", "users.manage", "roles.manage", "security.center.read", "security.integrations.manage", "security.retention.manage"):
            identity.create_permission(tenant_id=runtime.tenant, permission_name=permission)
            identity.grant_permission(tenant_id=runtime.tenant, role_name="receipt-operator", permission_name=permission)
    seed_erp_browser_principals(runtime)
    return runtime


def manufacturing_execution_v2_browser_configuration(runtime: Any) -> dict[str, Any]:
    with runtime.actor("browser-poster") as (connection, _, _):
        bom = connection.execute("SELECT id FROM reconforge.manufacturing_execution_boms WHERE tenant_id=%s AND phase=1", (runtime.tenant,)).fetchone()
        claims = connection.execute("""SELECT e.id effect_id,l.id line_id,a.account_code
            FROM reconforge.finance_posting_effects e JOIN reconforge.finance_entry_lines l ON l.tenant_id=e.tenant_id AND l.entry_id=e.entry_id
            JOIN reconforge.finance_accounts a ON a.tenant_id=l.tenant_id AND a.id=l.account_id
            WHERE e.tenant_id=%s AND a.account_code IN('LABOR','OVERHEAD') AND l.debit_minor>0 ORDER BY a.account_code""", (runtime.tenant,)).fetchall()
    return {"bom_version_id": bom["id"], "cost_claims": [{"effect_id": row["effect_id"], "line_id": row["line_id"],
        "kind": "Labor" if row["account_code"] == "LABOR" else "Overhead", "operation_sequence": 1,
        "minutes": 60 if row["account_code"] == "LABOR" else 30, "rate_minor_per_hour": "600"} for row in claims]}


def verify_manufacturing_execution_v2_browser(runtime: Any) -> dict[str, Any]:
    """Verify exported native rows independently after the scoped reader closes."""
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / ".github/scripts/verify_manufacturing_v2_cycle_oracle.py"
    spec = importlib.util.spec_from_file_location("me2_independent_native_oracle", path)
    if spec is None or spec.loader is None:
        raise AssertionError("The original stdlib manufacturing verifier is unavailable")
    oracle = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(oracle)
    proof = manufacturing_execution_v2_proof(runtime)
    result = oracle.verify_proof(proof)
    amounts = tuple(result[key] for key in ("issued_material_minor", "claimed_expense_minor", "finished_cost_minor", "abnormal_loss_minor", "remaining_wip_minor"))
    if amounts != ("2900", "900", "3420", "380", "0"):
        raise AssertionError("Actual original browser manufacture differs from the independent synthetic golden")
    actors = {row["operation"]: row["actor_id"] for row in proof["populations"]["manufacturing_execution_v2_commands"] if row["object_id"] == result["order_id"]}
    if (actors["prepare"], actors["review"], actors["post"]) != ("erp-maker", "erp-checker", "erp-poster"):
        raise AssertionError("The original browser costing source requires the three actual ERP humans")
    return {**result, "independent_financial_proof": proof}
