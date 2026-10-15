"""Independent finite zero-cost-original proof, separate from positive originals.

Input dictionaries must come from all-table original SQL captures. This binds
the new explicit factual proof to the actual issued rows and the prior zero
restitution pool. It does not assert current authorization or native execution.
The selected synthetic vector is 0.1 units at unit price1000, gross100/cost0.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

POLICY = "partial-return-restituted-v1"
OUTBOX_FIELDS = frozenset({"tenant_id", "event_id", "event_type", "aggregate_type", "aggregate_id", "workspace_id",
                           "organization_id", "legal_entity_id", "payload", "created_at"})


def require(value: bool) -> None:
    if not value:
        raise ValueError("Independent restituted-cost original refused.")


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    ).hexdigest()


def _integers(value: Any, *keys: str) -> None:
    require(type(value) is dict and all(type(value[key]) is int for key in keys))


def one(rows: list[dict[str, Any]], **keys: Any) -> dict[str, Any]:
    values = [row for row in rows if all(row.get(key) == value for key, value in keys.items())]
    require(len(values) == 1)
    return values[0]


def verify_restituted_original(
    prior: dict[str, list[dict[str, Any]]],
    issued: dict[str, list[dict[str, Any]]],
    source: dict[str, Any],
    *,
    tenant_id: str,
    original_source_order_id: str,
    resale_source_order_id: str,
) -> dict[str, Any]:
    require(type(tenant_id) is str and original_source_order_id != resale_source_order_id)
    stock = one(issued["stock_sales_orders"], id=resale_source_order_id)
    invoice = one(issued["ar_invoices"], id=stock["invoice_id"])
    _integers(stock, "quantity_scaled", "quantity_precision", "total_minor")
    _integers(invoice, "total_minor", "tax_minor")
    payload = source["source_payload"]
    proof = payload["original_source"]["cost_admission"]
    require(
        type(proof) is dict
        and set(proof)
        == {
            "schema_version",
            "stock_order_id",
            "issue_plan",
            "valuation_document",
            "valuation_lines",
            "consumptions",
            "posting_effect",
        }
        and proof["schema_version"] == "stock-sales-restituted-cost-v1"
        and proof["stock_order_id"] == resale_source_order_id
        and proof["issue_plan"] == stock["issue_plan"]
    )
    require(
        source["tenant_id"] == stock["tenant_id"] == invoice["tenant_id"] == tenant_id
        and source["source_order_id"] == resale_source_order_id
        and source["invoice_id"] == invoice["id"]
        and payload["allocation_policy"] == "remaining-original-v1"
    )
    require(
        type(stock["quantity_scaled"]) is int
        and stock["quantity_scaled"] == 1
        and stock["quantity_precision"] == 1
        and stock["status"] in {"Invoiced", "Paid"}
        and stock["source"]["net_unit_price_minor"] == 1000
        and invoice["total_minor"] == stock["total_minor"] == 100
        and invoice["tax_minor"] == 0
    )
    issue = proof["issue_plan"]
    require(
        issue["schema_version"] == "stock-sales-issue-v2"
        and issue["cost_admission_policy"] == POLICY
        and type(issue["total_cost_minor"]) is int
        and issue["total_cost_minor"] == 0
        and issue["entry_id"] is stock["cogs_entry_id"] is stock["cogs_effect_id"] is proof["posting_effect"] is None
    )
    valuation = one(issued["inventory_valuation_documents"], id=stock["valuation_id"])
    lines = [row for row in issued["inventory_valuation_lines"] if row["valuation_document_id"] == valuation["id"]]
    _integers(valuation, "total_value_minor")
    _integers(proof["valuation_document"], "total_value_minor")
    for line in (*lines, *proof["valuation_lines"]):
        _integers(line, "quantity_scaled", "value_minor")
    require(
        proof["valuation_document"] == valuation
        and proof["valuation_lines"] == lines
        and len(lines) == 1
        and valuation["finance_entry_id"] is None
        and valuation["status"] == "Approved"
        and type(valuation["total_value_minor"]) is int
        and valuation["total_value_minor"] == 0
        and lines[0]["flow_direction"] == "Outbound"
        and lines[0]["quantity_scaled"] == 1
        and lines[0]["value_minor"] == 0
    )
    consumed = [row for row in issued["inventory_layer_consumptions"] if row["valuation_line_id"] == lines[0]["id"]]
    for row in (*consumed, *proof["consumptions"]):
        _integers(row, "quantity_scaled", "value_minor")
    require(
        proof["consumptions"] == consumed
        and len(consumed) == len(issue["allocations"]) == 1
        and consumed[0]["tenant_id"] == tenant_id
        and consumed[0]["quantity_scaled"] == 1
        and type(consumed[0]["value_minor"]) is int
        and consumed[0]["value_minor"] == 0
    )
    allocation = issue["allocations"][0]
    _integers(allocation, "quantity_scaled", "value_minor")
    require(
        (allocation["cost_layer_id"], allocation["quantity_scaled"], allocation["value_minor"])
        == (consumed[0]["cost_layer_id"], 1, 0)
    )
    require(all(row.get("external_reference") != resale_source_order_id for row in issued["finance_entries"]))
    require(all(row.get("source_id") != resale_source_order_id for row in issued["finance_posting_effects"]))
    snapshot = issue["restitution_cost_snapshot"]
    policy = issue["currency_policy"]
    captured_policy = {
        "currency_code": policy["currency_code"],
        "currency_precision": policy["precision"],
        "currency_rounding_policy": policy["rounding_policy"],
        "currency_registry_version": policy["registry_version"],
        "currency_registry_digest": policy["registry_digest"],
    }
    require(
        type(snapshot) is dict
        and set(snapshot)
        == {"schema_version", "monetary_policy", "remaining_quantity_scaled", "remaining_value_minor", "sources"}
        and snapshot["schema_version"] == "inventory-transfer-cost-v3"
        and snapshot["remaining_quantity_scaled"] == 1
        and snapshot["remaining_value_minor"] == 0
        and type(snapshot["sources"]) is list
        and len(snapshot["sources"]) == 1
        and snapshot["monetary_policy"] == captured_policy
    )
    captured = snapshot["sources"][0]
    layer = one(prior["inventory_cost_layers"], id=consumed[0]["cost_layer_id"])
    for row in (snapshot, layer, captured["layer"]):
        _integers(row, "remaining_quantity_scaled", "remaining_value_minor")
    require(
        captured["layer"] == layer and layer["remaining_quantity_scaled"] == 1 and layer["remaining_value_minor"] == 0
    )
    before_consumed = [row for row in prior["inventory_layer_consumptions"] if row["cost_layer_id"] == layer["id"]]
    for row in (*before_consumed, *captured["consumptions"]):
        _integers(row, "quantity_scaled", "value_minor")
    require(
        captured["consumptions"] == before_consumed
        and len(before_consumed) == 1
        and before_consumed[0]["quantity_scaled"] == 3
        and before_consumed[0]["value_minor"] == 1
        and all(row in issued["inventory_layer_consumptions"] for row in before_consumed)
    )
    corrections = captured["partial_return_corrections"]
    require(type(corrections) is list and len(corrections) == 1)
    correction = corrections[0]
    require(
        set(correction)
        == {
            "restoration",
            "source",
            "plan",
            "entry",
            "effect",
            "lines",
            "dimensions",
            "physical",
            "history_sequence",
            "allocation_policy",
            "allocation_witness",
        }
        and correction["allocation_policy"] == "remaining-original-v1"
        and correction["history_sequence"] == 1
        and correction["entry"] is correction["effect"] is None
        and correction["lines"] == correction["dimensions"] == []
    )
    old_source = one(prior["customer_partial_return_sources"], source_order_id=original_source_order_id)
    old_plan = one(prior["customer_partial_return_plans"], id=correction["plan"]["id"])
    restoration = one(prior["customer_partial_return_restorations"], plan_id=old_plan["id"], position=1)
    witness = one(prior["customer_partial_return_allocation_witnesses"], plan_id=old_plan["id"], position=1)
    _integers(old_source, "quantity_precision")
    _integers(correction["source"], "quantity_precision")
    for row in (witness, correction["allocation_witness"]):
        _integers(row, "before_quantity_scaled", "before_value_minor")
    for row in (restoration, correction["restoration"]):
        _integers(row, "position", "quantity_scaled", "value_minor", "direction")
    _integers(correction, "history_sequence")
    require(
        correction["restoration"] == restoration
        and restoration["source_id"] == old_source["id"]
        and old_plan["source_id"] == old_source["id"]
        and old_plan["phase"] == 2
        and old_plan["operation"] == "Return"
        and old_plan["quantity_scaled"] == 1
        and old_plan["credit_minor"] == old_plan["cogs_restored_minor"] == 0
    )
    require(
        correction["source"]
        == {
            key: old_source[key]
            for key in (
                "id",
                "source_fingerprint",
                "workspace_id",
                "organization_id",
                "legal_entity_id",
                "item_id",
                "uom_id",
                "quantity_precision",
                "location_id",
                "original_cogs_effect_id",
            )
        }
    )
    require(
        correction["plan"]
        == {
            key: old_plan[key]
            for key in ("id", "source_id", "operation", "phase", "plan_digest", "cogs_restored_minor")
        }
    )
    require(
        correction["allocation_witness"] == {"before_quantity_scaled": 3, "before_value_minor": 1}
        and (witness["before_quantity_scaled"], witness["before_value_minor"]) == (3, 1)
        and (
            restoration["cost_layer_id"],
            restoration["original_consumption_id"],
            restoration["quantity_scaled"],
            restoration["value_minor"],
            restoration["direction"],
            restoration["correction_effect_id"],
        )
        == (layer["id"], before_consumed[0]["id"], 1, 0, 1, None)
    )
    native = correction["physical"]
    require(
        set(native) == {"head", "lines", "audit", "outbox"}
        and native["head"] == one(prior["inventory_movements"], id=restoration["physical_movement_id"])
        and native["head"]["status"] == "Posted"
        and native["head"]["source_reference"] == old_plan["id"]
        and native["lines"]
        == [row for row in prior["inventory_movement_lines"] if row["movement_id"] == native["head"]["id"]]
        and len(native["lines"]) == 1
        and native["lines"][0]["quantity_scaled"] == 1
    )
    require(
        all(row in prior["domain_audit_events"] for row in native["audit"])
        and native["audit"]
        and native["outbox"]
    )
    # Native IT1 snapshots deliberately capture this closed immutable projection.
    # The all-table original still retains the complete delivery row separately.
    for captured in native["outbox"]:
        retained = one(prior["outbox_events"], tenant_id=tenant_id, event_id=captured["event_id"])
        require(set(captured) == OUTBOX_FIELDS and captured == {key: retained[key] for key in OUTBOX_FIELDS})
    typed = payload["typed_source"]
    require(
        typed["original_cogs"] is None
        and typed["original_cost_admission"] == {"evidence_digest": digest(proof)}
        and source["original_cogs_effect_id"] is None
    )
    fingerprint = payload["fingerprint_payload"]
    _integers(fingerprint, "quantity_scaled", "gross_minor")
    for row in fingerprint["consumptions"]:
        _integers(row, "quantity_scaled", "value_minor")
    require(
        fingerprint["currency"] == captured_policy["currency_code"]
        and fingerprint["policy"] == {key: value for key, value in captured_policy.items() if key != "currency_code"}
    )
    require(
        fingerprint["contract"] == "customer-partial-return-original-v2"
        and fingerprint["original_cogs"] is None
        and fingerprint["original_cost_admission"] == ["stock-sales-restituted-cost-v1", digest(proof)]
        and source["source_fingerprint"] == digest(fingerprint)
        and (
            fingerprint["source_order_id"],
            fingerprint["invoice_id"],
            fingerprint["quantity_scaled"],
            fingerprint["gross_minor"],
        )
        == (resale_source_order_id, invoice["id"], 1, 100)
    )
    require(
        [
            (
                row["consumption_id"],
                row["valuation_line_id"],
                row["cost_layer_id"],
                row["quantity_scaled"],
                row["value_minor"],
            )
            for row in fingerprint["consumptions"]
        ]
        == [(consumed[0]["id"], lines[0]["id"], layer["id"], 1, 0)]
    )
    for row in (stock, invoice, valuation, lines[0], consumed[0]):
        require(row["tenant_id"] == tenant_id)
    for row in (stock, invoice, valuation):
        require(all(row[key] == source[key] for key in ("workspace_id", "organization_id", "legal_entity_id")))
    return {
        "schema_version": "independent-finite-restituted-original-v1",
        "explicit_original_cost_admission": True,
        "original_cost_admission_sha256": digest(proof),
        "original_cogs_effect_absent": True,
        "original_quantity_scaled": 1,
        "original_gross_minor": 100,
        "original_cost_minor": 0,
        "prior_zero_physical_quantity_scaled": 1,
        "prior_zero_physical_value_minor": 0,
        "current_authorization_proven": False,
        "native_execution_proven": False,
    }
