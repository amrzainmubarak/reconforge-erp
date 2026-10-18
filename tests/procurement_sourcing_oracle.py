"""Raw SQL evidence export for the separate stdlib oracle; no business calculations."""
from __future__ import annotations

from typing import Any


def raw_sourcing_evidence(connection: Any, tenant: str, source_id: str) -> dict[str, Any]:
    """Caller supplies its current authorized restricted-role transaction, never a bypass DSN."""
    def rows(table: str, predicate: str, values: tuple[Any, ...], *, omit: tuple[str, ...] = ()) -> list[dict[str, Any]]:
        # Both identifiers/predicate are internal constants; every external value is parameterized.
        expression = "to_jsonb(t)" + "".join("-'" + key + "'" for key in omit)
        result = connection.execute("SELECT " + expression + " value FROM reconforge." + table +
            " t WHERE tenant_id=%s AND " + predicate + " ORDER BY to_jsonb(t)::text", (tenant, *values)).fetchall()
        return [record["value"] if isinstance(record, dict) else record[0] for record in result]

    role = connection.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone()
    if tuple(role) != (False, False):
        raise ValueError("Raw evidence export requires a restricted role without RLS bypass")
    source, = rows("procurement_sourcing_requisitions", "id=%s", (source_id,))
    order_id, budget_id = source["order_id"], source["budget_id"]
    events = rows("procurement_sourcing_events", "requisition_id=%s", (source_id,))
    receipts = rows("procurement_partial_receipts", "order_id=%s", (order_id,), omit=("quantity",))
    plans = rows("inventory_receipt_plans", "id=ANY(%s)", ([row["receipt_plan_id"] for row in receipts],))
    links = rows("inventory_receipt_links", "plan_id=ANY(%s)", ([row["id"] for row in plans],))
    layers = rows("inventory_cost_layers", "id=ANY(%s)", ([row["cost_layer_id"] for row in links],))
    invoices = rows("procurement_partial_invoices", "order_id=%s", (order_id,), omit=("quantity",))
    native_ids = [row["native_invoice_id"] for row in invoices]
    payments = rows("ap_payment_links", "supplier_invoice_id=ANY(%s)", (native_ids,))
    # This alias preserves the original raw finance_effect_id alongside the canonical link name.
    payments = [{**payment, "posting_effect_id": payment["finance_effect_id"]} for payment in payments]
    effect_ids = [row["posting_effect_id"] for row in links] + [row["accrual_effect_id"] for row in invoices] + [row["finance_effect_id"] for row in payments]
    effects = rows("finance_posting_effects", "id=ANY(%s)", (effect_ids,))
    accounts = rows("finance_accounts", "id=ANY(%s)", (list({line["account_id"] for effect in effects for line in effect["snapshot_json"]["lines"]}),))
    commitment, = rows("procurement_commitment_plans", "order_id=%s", (order_id,))
    budget, = rows("budget_envelopes", "id=%s", (budget_id,))
    order, = rows("procurement_partial_orders", "id=%s", (order_id,))
    return {"schema_version": "sourcing-oracle-v1", "source": source,
        "quotes": rows("procurement_sourcing_quotes", "requisition_id=%s", (source_id,)), "source_events": events,
        "source_commands": rows("procurement_sourcing_commands", "requisition_id=%s", (source_id,)),
        "source_audits": rows("domain_audit_events", "id=ANY(%s)", ([row["audit_event_id"] for row in events],)),
        "source_outbox": rows("outbox_events", "event_id=ANY(%s)", ([row["outbox_event_id"] for row in events],)),
        "commitment": commitment, "commitment_commands": rows("procurement_commitment_commands", "order_id=%s", (order_id,)),
        "budget": budget, "budget_events": rows("budget_commitment_events", "budget_id=%s", (budget_id,)),
        "native": {"order": order, "lines": rows("procurement_partial_order_lines", "order_id=%s", (order_id,), omit=("quantity",)),
            "receipts": receipts, "receipt_plans": plans, "receipt_links": links, "layers": layers,
            "layer_consumptions": rows("inventory_layer_consumptions", "cost_layer_id=ANY(%s)", ([row["id"] for row in layers],)),
            "invoices": invoices, "invoice_lines": rows("procurement_partial_invoice_lines", "order_id=%s", (order_id,), omit=("quantity",)),
            "native_invoices": rows("ap_supplier_invoices", "id=ANY(%s)", (native_ids,)), "payments": payments,
            "effects": effects, "accounts": accounts}}


def independent_sourcing_oracle(connection: Any, tenant: str, source_id: str) -> dict[str, Any]:
    """Run the separate script under Python -I; persist synthetic evidence when explicitly configured."""
    import hashlib
    import json
    import os
    import subprocess
    import sys
    from pathlib import Path
    from tempfile import TemporaryDirectory

    packet = raw_sourcing_evidence(connection, tenant, source_id)
    script = Path(__file__).resolve().parents[1] / ".github/scripts/verify_procurement_sourcing_oracle.py"
    with TemporaryDirectory(prefix="reconforge-sourcing-oracle-") as temporary:
        configured = os.environ.get("RECONFORGE_SOURCING_ORACLE_EVIDENCE_DIR")
        folder = Path(configured) if configured else Path(temporary)
        folder.mkdir(parents=True, exist_ok=True)
        evidence = folder / ("sourcing-oracle-" + source_id + ".json")
        evidence.write_text(json.dumps(packet, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False), encoding="utf-8")
        result = subprocess.run([sys.executable, "-I", str(script), "--input", str(evidence)], capture_output=True, text=True, timeout=30)
        if configured:
            evidence.with_suffix(".result.json").write_text(result.stdout, encoding="utf-8")
        if result.returncode:
            raise AssertionError("Independent sourcing oracle refused the raw evidence: " + result.stdout + result.stderr)
        verified = json.loads(result.stdout)
        if verified.get("verified") is not True:
            raise AssertionError("Independent sourcing oracle did not verify the raw evidence")
        return {**verified, "oracle_script_sha256": hashlib.sha256(script.read_bytes()).hexdigest()}
