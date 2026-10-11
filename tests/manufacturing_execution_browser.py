"""Actual ME1 HTTPS seed and an independent integer/Fraction populated-restore oracle."""
from fractions import Fraction
from typing import Any

from reconforge.infrastructure.postgres import PostgresTenantBoundary
from reconforge.infrastructure.postgres_identity import PostgresIdentityRepository
from reconforge.infrastructure.postgres_manufacturing_execution import PostgresManufacturingExecutionRepository
from tests.erp_browser_seed import seed_erp_browser_principals
from tests.gfo_browser_restore import require
from tests.test_postgres_inventory_receipt_posting import ReceiptRuntime
from tests.test_postgres_manufacturing_execution import runtime as create_manufacturing_runtime

MANUFACTURING_EXECUTION_TABLES = (
    "manufacturing_execution_boms", "manufacturing_execution_orders", "manufacturing_execution_requirements",
    "manufacturing_execution_reservations", "manufacturing_execution_completions", "manufacturing_execution_events",
    "manufacturing_execution_commands", "inventory_receipt_plans", "inventory_receipt_reviews", "inventory_receipt_commands",
    "inventory_receipt_links", "inventory_movements", "inventory_movement_lines", "inventory_valuation_documents",
    "inventory_valuation_lines", "inventory_cost_layers", "inventory_layer_consumptions", "finance_entries",
    "finance_entry_lines", "finance_entry_line_dimensions", "finance_posting_effects", "domain_audit_events", "outbox_events",
)
MANUFACTURING_EXECUTION_TAMPER = (
    "UPDATE reconforge.manufacturing_execution_orders SET released_cost_minor=released_cost_minor+1 WHERE tenant_id=%s",
    "UPDATE reconforge.manufacturing_execution_requirements SET requirement_json=jsonb_set(requirement_json,'{item_code}','\"FORGED\"'::jsonb) WHERE tenant_id=%s",
    "DELETE FROM reconforge.manufacturing_execution_commands WHERE tenant_id=%s",
)


def seed_manufacturing_execution_browser(admin_dsn: str, app_dsn: str) -> ReceiptRuntime:
    result = create_manufacturing_runtime((admin_dsn, app_dsn))
    with PostgresTenantBoundary(result.factory).transaction(result.tenant) as connection:
        identities = PostgresIdentityRepository(connection)
        for permission in ("audit.read", "users.manage", "roles.manage", "security.center.read", "security.integrations.manage", "security.retention.manage"):
            identities.create_permission(tenant_id=result.tenant, permission_name=permission)
            identities.grant_permission(tenant_id=result.tenant, role_name="receipt-operator", permission_name=permission)
    seed_erp_browser_principals(result)
    return result


def _even(value: Fraction) -> int:
    base, rest = divmod(value.numerator, value.denominator)
    return base + int(rest * 2 > value.denominator or rest * 2 == value.denominator and base % 2 == 1)


def manufacturing_execution_proof(runtime: ReceiptRuntime) -> dict[str, Any]:
    """Retain native input and output populations for a stdlib external oracle."""
    with runtime.actor("browser-poster") as (connection, _, _):
        from psycopg import sql
        populations = {}
        for name in MANUFACTURING_EXECUTION_TABLES:
            rows = connection.execute(sql.SQL("SELECT to_jsonb(t) payload FROM reconforge.{} t WHERE tenant_id=%s ORDER BY to_jsonb(t)::text").format(sql.Identifier(name)), (runtime.tenant,)).fetchall()
            populations[name] = [row["payload"] for row in rows]
        populations["finance_accounts"] = [row["payload"] for row in connection.execute("SELECT to_jsonb(a) payload FROM reconforge.finance_accounts a WHERE tenant_id=%s ORDER BY id", (runtime.tenant,)).fetchall()]
        return {"schema_version": "manufacturing-execution-proof-v1", "tenant_id": runtime.tenant, "populations": populations}


def verify_manufacturing_execution_browser(runtime: ReceiptRuntime) -> dict[str, Any]:
    original = _even(Fraction(12000 * 2, 10)) + _even(Fraction(3333 * 3000, 20000))
    first_release = _even(Fraction(original * 4, 10))
    first_good = _even(Fraction(first_release * 3, 4))
    scrap, good = first_release - first_good, first_good + original - first_release
    require((original, good, scrap) == (2900, 2610, 290), "Independent material arithmetic changed.")
    with runtime.actor("browser-poster") as (connection, _, actor):
        owner = PostgresManufacturingExecutionRepository(connection, runtime.tenant)
        rows = connection.execute("SELECT id FROM reconforge.manufacturing_execution_orders WHERE tenant_id=%s", (runtime.tenant,)).fetchall()
        require(len(rows) == 1, "Exactly one browser production order must remain.")
        order = owner.get_order(rows[0]["id"], actor=actor)
        require((order["phase"], order["disposed_quantity_scaled"], order["released_cost_minor"], order["wip_minor"]) == (4, 10, original, 0), "Complete physical and WIP conservation failed.")
        require(order["creator_id"] == order["issue_plan"]["preparer_actor_id"] == "erp-maker" and order["issue_reviewer_id"] == "erp-checker", "Material maker/reviewer identities changed.")
        require(len(order["completions"]) == 3 and sorted(part["phase"] for part in order["completions"]) == [2, 2, 3], "Cancelled reviewed native output and two posted partial outputs must remain.")
        for part in order["completions"]:
            require((part["preparer_actor_id"], part["reviewer_id"]) == ("erp-maker", "erp-checker"), "Output preparer/reviewer independence changed.")
            if part["phase"] == 2:
                require(part["receipt_effect"]["posted_actor_id"] == "erp-poster", "Actual output must have the third human native receipt effect.")
            else:
                require(part["receipt_effect"] is None and part["scrap_effect_id"] is None, "Cancelled output leaked a financial effect.")
        aggregates = connection.execute("""SELECT a.account_code,sum(l.debit_minor::numeric-l.credit_minor) balance
            FROM reconforge.finance_posting_effects f JOIN reconforge.finance_entry_lines l ON l.tenant_id=f.tenant_id AND l.entry_id=f.entry_id
            JOIN reconforge.finance_accounts a ON a.tenant_id=l.tenant_id AND a.id=l.account_id WHERE f.tenant_id=%s GROUP BY a.account_code""", (runtime.tenant,)).fetchall()
        positions = {row["account_code"]: int(row["balance"]) for row in aggregates}
        require(all(positions.get(code) == value for code, value in {"WIP": 0, "FG": good, "SCRAP": scrap, "INVENTORY": 15333 - original, "CLEARING": -15333}.items()), "Native independent material/output/scrap GL positions differ.")
        totals = connection.execute("SELECT count(*) n,sum(e.total_debit_minor::numeric) d,sum(e.total_credit_minor::numeric) c FROM reconforge.finance_posting_effects f JOIN reconforge.finance_entries e ON e.tenant_id=f.tenant_id AND e.id=f.entry_id WHERE f.tenant_id=%s", (runtime.tenant,)).fetchone()
        require((int(totals["n"]), int(totals["d"]), int(totals["c"])) == (6, 21133, 21133), "Six original native effects must balance at the independently computed turnover.")
        require(connection.execute("SELECT count(*) n FROM reconforge.inventory_layer_consumptions WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 2, "Exactly two original component FIFO consumptions must remain immutable.")
        layers = connection.execute("SELECT sum(remaining_quantity_scaled) q,sum(remaining_value_minor) v FROM reconforge.inventory_cost_layers WHERE tenant_id=%s AND item_id=%s", (runtime.tenant, order["output_item_id"])).fetchone()
        require((int(layers["q"]), int(layers["v"])) == (9, good), "Native finished FIFO quantity and cost differ.")
        require(connection.execute("SELECT count(*) n FROM reconforge.manufacturing_execution_commands WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 15, "Lost-response replay must not duplicate fifteen original lifecycle commands.")
        return {"production_order_id": order["id"], "issued_material_minor": str(original), "finished_quantity_scaled": "9", "finished_cost_minor": str(good), "abnormal_scrap_quantity_scaled": "1", "abnormal_scrap_minor": str(scrap), "remaining_wip_minor": "0", "posting_effects": 6, "balanced_turnover_minor": "21133", "native_component_consumptions": 2, "retained_output_dispositions": 3, "cancelled_reviewed_outputs": 1, "posted_partial_outputs": 2, "retained_commands": 15, "receipt_identity_candidates": [part["receipt_identity_candidates"] for part in order["completions"]], "independent_financial_proof": manufacturing_execution_proof(runtime)}
