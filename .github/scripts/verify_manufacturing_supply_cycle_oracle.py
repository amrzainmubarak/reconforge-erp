"""File-only stdlib verification of one original MSP -> SRC/BPC/AP -> ME2 cycle.

The caller supplies the separately retained raw proof SHA. Companion stdlib
oracles are admitted only by their digests captured with that original proof.
No production accounting, quantity, repository or application module is loaded.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import re
from collections import Counter
from fractions import Fraction
from pathlib import Path
from typing import Any


def require(value: bool, message: str) -> None:
    if not value:
        raise ValueError(message)


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def sha(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def integer(value: Any, *, positive: bool = False) -> int:
    require(type(value) is int and int(positive) <= value <= 9_000_000_000_000_000_000, "Original bounded integer token required")
    return value


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        require(key not in result, "Duplicate original JSON member")
        result[key] = value
    return result


def indexed(rows: Any, key: str = "id") -> dict[Any, dict[str, Any]]:
    require(type(rows) is list and all(type(row) is dict for row in rows), "Original native population required")
    result = {row[key]: row for row in rows}
    require(len(result) == len(rows), "Duplicate original native identity")
    return result


def companion(proof: dict[str, Any], filename: str) -> Any:
    path = Path(__file__).with_name(filename)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    require(proof["capture"]["source_files_sha256"][".github/scripts/" + filename] == digest,
        "Captured independent companion source digest differs")
    spec = importlib.util.spec_from_file_location("independent_" + path.stem, path)
    if spec is None or spec.loader is None:
        raise ValueError("Captured independent companion unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sourcing_packet(tables: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    def rows(name: str, key: str, value: Any) -> list[dict[str, Any]]:
        return [row for row in tables[name] if row[key] == value]
    order, = rows("procurement_partial_orders", "id", source["order_id"])
    receipts = rows("procurement_partial_receipts", "order_id", order["id"])
    receipt_ids = {row["receipt_plan_id"] for row in receipts}
    links = [row for row in tables["inventory_receipt_links"] if row["plan_id"] in receipt_ids]
    layer_ids = {row["cost_layer_id"] for row in links}
    invoices = rows("procurement_partial_invoices", "order_id", order["id"])
    invoice_ids = {row["native_invoice_id"] for row in invoices}
    effect_ids = {row["posting_effect_id"] for row in links} | {row["accrual_effect_id"] for row in invoices}
    events = rows("procurement_sourcing_events", "requisition_id", source["id"])
    audit_ids, outbox_ids = ({row[field] for row in events} for field in ("audit_event_id", "outbox_event_id"))
    commitment, = rows("procurement_commitment_plans", "order_id", order["id"])
    budget, = rows("budget_envelopes", "id", source["budget_id"])
    return {"schema_version": "sourcing-oracle-v1", "source": source,
        "quotes": rows("procurement_sourcing_quotes", "requisition_id", source["id"]), "source_events": events,
        "source_commands": rows("procurement_sourcing_commands", "requisition_id", source["id"]),
        "source_audits": [row for row in tables["domain_audit_events"] if row["id"] in audit_ids],
        "source_outbox": [row for row in tables["outbox_events"] if row["event_id"] in outbox_ids],
        "commitment": commitment, "commitment_commands": rows("procurement_commitment_commands", "order_id", order["id"]),
        "budget": budget, "budget_events": rows("budget_commitment_events", "budget_id", budget["id"]),
        "native": {"order": order, "lines": rows("procurement_partial_order_lines", "order_id", order["id"]),
            "receipts": receipts, "receipt_plans": [row for row in tables["inventory_receipt_plans"] if row["id"] in receipt_ids],
            "receipt_links": links, "layers": [row for row in tables["inventory_cost_layers"] if row["id"] in layer_ids],
            "layer_consumptions": [row for row in tables["inventory_layer_consumptions"] if row["cost_layer_id"] in layer_ids],
            "invoices": invoices, "invoice_lines": rows("procurement_partial_invoice_lines", "order_id", order["id"]),
            "native_invoices": [row for row in tables["ap_supplier_invoices"] if row["id"] in invoice_ids], "payments": [],
            "effects": [row for row in tables["finance_posting_effects"] if row["id"] in effect_ids], "accounts": tables["finance_accounts"]}}


def original_ack(plan: dict[str, Any], tables: dict[str, Any], version: int) -> dict[str, Any]:
    """Derive historical original ACK from actual immutable source membership."""
    history = [row for row in tables["manufacturing_supply_events"] if row["version"] <= version]
    approved = next((row for row in history if row["operation"] == "approve"), None)
    handed = any(row["operation"] == "handoff" for row in history)
    releases = indexed([row for row in tables["manufacturing_supply_stock_releases"] if row["created_version"] <= version], "claim_id")
    claims = [{key: row[key] for key in ("id", "requirement_id", "quantity_scaled", "origin", "native_receipt_plan_id")}
        | {"state": "HandedOff" if row["id"] in releases else "Active"}
        for row in sorted(tables["manufacturing_supply_stock_claims"], key=lambda row: row["id"]) if row["created_version"] <= version]
    requirements = [{**row["payload"], "source_digest": row["source_digest"],
        "coverage": row["coverage_json"] if approved else None, "coverage_digest": row["coverage_digest"] if approved else None}
        for row in sorted(tables["manufacturing_supply_requirements"], key=lambda row: row["sequence"])]
    procurement = [{**row["payload"], "source_digest": row["source_digest"], "state": "HandedOff" if handed else "Active"}
        for row in sorted(tables["manufacturing_supply_procurement_claims"], key=lambda row: row["id"]) if row["created_version"] <= version]
    return {**plan["payload"], "source_digest": plan["source_digest"], "phase": 2 if handed else 1 if approved else 0,
        "row_version": version, "reviewer_actor_id": approved["actor_id"] if approved else None,
        "material_order_id": plan["material_order_id"] if handed else None,
        "manufacturing_order_id": plan["manufacturing_order_id"] if handed else None,
        "planned_requirements": requirements, "stock_claims": claims, "procurement_claims": procurement}


def verify_proof(proof: dict[str, Any]) -> dict[str, Any]:
    require(proof.get("schema_version") == "manufacturing-supply-proof-v1", "Unsupported original supply proof")
    capture, tables, tenant = proof["capture"], proof["populations"], proof["tenant_id"]
    require(capture["role_superuser"] is False and capture["role_bypassrls"] is False, "Original restricted source export required")
    for name, rows in tables.items():
        require(type(rows) is list and all(type(row) is dict and row.get("tenant_id") == tenant for row in rows), "Cross-tenant original population: " + name)
        for row in rows:
            for key, value in row.items():
                if key.endswith(("_minor", "_scaled")) and value is not None:
                    integer(value)
    plan, = tables["manufacturing_supply_plans"]
    source = plan["payload"]
    scope = {key: plan[key] for key in ("workspace_id", "organization_id", "legal_entity_id")}
    require(plan["phase"] == 2 and sha(source) == plan["source_digest"] and source["id"] == plan["id"]
        and all(source[key] == value for key, value in scope.items()), "Original handed-off plan source seal/identity differs")
    bom, = tables["manufacturing_execution_boms"]
    require(bom["phase"] == 1 and bom["id"] == plan["bom_version_id"] == source["bom_version_id"]
        and sha(bom["payload"]) == bom["source_digest"] == source["bom_digest"], "Original approved BOM seal differs")
    definitions = indexed(tables["manufacturing_execution_v2_definitions"])
    route = definitions[plan["routing_id"]]
    require(route["kind"] == "Routing" and route["phase"] == 1 and sha(route["payload"]) == route["source_digest"] == source["routing_digest"]
        and route["payload"]["bom_version_id"] == bom["id"] and all(route[key] == value for key, value in scope.items())
        and route["payload"]["effective_from"] <= source["posting_date"] <= route["payload"]["effective_until"], "Original approved effective routing differs")
    requirements = indexed(tables["manufacturing_supply_requirements"])
    components = indexed(bom["payload"]["components"], "item_id")
    require(len(requirements) == len(source["requirements"]) == len(components), "Complete original planned BOM population required")
    stock = indexed(tables["manufacturing_supply_stock_claims"])
    releases = indexed(tables["manufacturing_supply_stock_releases"], "claim_id")
    guards = indexed(tables["inventory_quantity_source_guards"])
    guard_releases = indexed(tables["inventory_quantity_source_releases"], "guard_id")
    require(set(stock) == set(releases) == set(guards) == set(guard_releases), "Exact original quantity guard/release membership differs")
    native_receipts = indexed(tables["inventory_receipt_plans"])
    native_links = indexed(tables["inventory_receipt_links"], "plan_id")
    purchases = tables["procurement_sourcing_requisitions"]
    require(len(purchases) == 1, "One bounded original shortage source required")
    purchase = purchases[0]
    procurement = indexed(tables["manufacturing_supply_procurement_claims"])
    receipt_ids = {row["receipt_plan_id"] for row in tables["procurement_partial_receipts"]}
    initial_inputs = [row for row in native_receipts.values() if row["item_id"] in components and row["id"] not in receipt_ids]
    require(len(initial_inputs) == len(components) and all(row["posting_date"] <= source["posting_date"] for row in initial_inputs),
        "Original starting stock must precede actual planned approval")
    starting: Counter[str] = Counter()
    for row in initial_inputs:
        require(row["id"] in native_links and row["operation"] == "Receipt", "Starting stock requires original committed receipt/FIFO")
        starting[row["item_id"]] += integer(row["quantity_scaled"], positive=True)
    net = {}
    for original in source["requirements"]:
        row = requirements[original["requirement_id"]]
        payload, coverage = row["payload"], row["coverage_json"]
        component = components[row["item_id"]]
        batch, planned = integer(bom["payload"]["output_quantity_scaled"], positive=True), integer(source["output_quantity_scaled"], positive=True)
        gross = Fraction(integer(component["quantity_scaled"], positive=True) * planned, batch)
        require(gross.denominator == 1 and gross == row["gross_quantity_scaled"] == original["required_quantity_scaled"], "Original exact BOM scaling differs")
        require(row["plan_id"] == plan["id"] and payload["plan_digest"] == plan["source_digest"]
            and sha(payload) == row["source_digest"] and sha(coverage) == row["coverage_digest"]
            and payload["id"] == coverage["requirement_id"] == row["id"]
            and payload["scope"] == scope and coverage["requirement_digest"] == row["source_digest"], "Original requirement/coverage identity seals differ")
        for field in ("item_id", "uom_id", "quantity_precision", "location_id"):
            require(payload[field] == row[field], "Original requirement native item/UOM/location differs")
        require((row["uom_id"], row["quantity_precision"]) == (component["uom_id"], component["quantity_precision"]), "Original BOM UOM/scale differs")
        observed = starting[row["item_id"]]
        onhand = min(int(gross), observed)
        shortage = int(gross) - onhand
        require((coverage["observed_available_scaled"], coverage["observed_reserved_scaled"], coverage["observed_fifo_free_scaled"],
            coverage["onhand_reserved_scaled"], coverage["shortage_quantity_scaled"])
            == (observed, 0, observed, onhand, shortage)
            and (row["onhand_reserved_scaled"], row["shortage_quantity_scaled"]) == (onhand, shortage), "Independent original starting-stock net quantity differs")
        owned = [claim for claim in stock.values() if claim["requirement_id"] == row["id"]]
        require(sum(claim["quantity_scaled"] for claim in owned if claim["origin"] == "OnHand") == onhand
            and sum(claim["quantity_scaled"] for claim in owned if claim["origin"] == "Receipt") == shortage, "Original onhand/received custody does not equal gross demand")
        purchased = [claim for claim in procurement.values() if claim["requirement_id"] == row["id"]]
        require(len(purchased) == 1 and purchased[0]["quantity_scaled"] == shortage
            and purchased[0]["requisition_id"] == purchase["id"] and sha(purchased[0]["payload"]) == purchased[0]["source_digest"], "Original procurement duplicates or exceeds exact shortage")
        native_line = next(line for line in tables["procurement_partial_order_lines"] if line["sequence"] == purchased[0]["source_line"])
        require(native_line["order_id"] == purchase["order_id"] and native_line["item_id"] == row["item_id"]
            and Fraction(native_line["quantity_text"]) * 10 ** row["quantity_precision"] == shortage
            and native_line["unit_price_minor"] <= source["unit_price_ceilings_minor"][payload["item_code"]], "Original native purchase must retain net shortage and price ceiling")
        net[payload["item_code"]] = {"uom_code": payload["uom_code"], "quantity_precision": row["quantity_precision"],
            "gross_scaled": str(gross.numerator), "starting_scaled": str(observed), "onhand_scaled": str(onhand), "shortage_scaled": str(shortage)}
    for claim in stock.values():
        row, guard, release = requirements[claim["requirement_id"]], guards[claim["id"]], releases[claim["id"]]
        item = indexed(tables["inventory_items"])[claim["item_id"]]
        unit = indexed(tables["inventory_units_of_measure"])[claim["uom_id"]]
        location = indexed(tables["inventory_locations"])[claim["location_id"]]
        warehouse = indexed(tables["inventory_warehouses"])[location["warehouse_id"]]
        item_key = "0" if item["organization_id"] is None else "1" + item["organization_id"]
        warehouse_key = "0" if warehouse["legal_entity_id"] is None else "1" + warehouse["legal_entity_id"]
        require(guard["warehouse_id"] == location["warehouse_id"] and guard["inventory_account_id"] == item["inventory_account_id"]
            and guard["item_type"] == item["item_type"] and guard["tracking_mode"] == item["tracking_mode"] == "None"
            and guard["item_organization_key"] == item_key and guard["warehouse_entity_key"] == warehouse_key
            and guard["quantity_precision"] == unit["decimal_places"] and item["uom_id"] == unit["id"]
            and guard["workspace_id"] == unit["workspace_id"] == item["workspace_id"] == warehouse["workspace_id"] == scope["workspace_id"],
            "Original guarded native master tuple differs")
        require(claim["plan_id"] == plan["id"] and claim["state"] == "HandedOff" and all(claim[key] == value for key, value in scope.items())
            and all(guard[key] == claim[key] == row[key] for key in ("item_id", "uom_id", "quantity_precision", "location_id"))
            and guard["owner_claim_id"] == claim["id"] and guard["owner_namespace"] == "MSP1" and guard["quantity_scaled"] == claim["quantity_scaled"]
            and release["purpose"] == "Handoff" and release["target_material_order_id"] == plan["material_order_id"]
            and guard_releases[claim["id"]]["release_id"] == release["id"], "Original custody cannot detach from actual native handoff")
        if claim["origin"] == "Receipt":
            receipt = native_receipts[claim["native_receipt_plan_id"]]
            require(receipt["id"] in receipt_ids and receipt["id"] in native_links and guard["source_receipt_plan_id"] == receipt["id"]
                and receipt["quantity_scaled"] == claim["quantity_scaled"] and receipt["item_id"] == claim["item_id"], "Original received custody requires exact actually committed stock")
        else:
            require(claim["native_receipt_plan_id"] is None and guard["source_receipt_plan_id"] is None, "Original onhand origin cannot be relabelled")
    events = sorted(tables["manufacturing_supply_events"], key=lambda row: row["version"])
    commands = indexed(tables["manufacturing_supply_commands"], "version")
    audits, outbox = indexed(tables["domain_audit_events"]), indexed(tables["outbox_events"], "event_id")
    require(len(events) == len(commands) == plan["row_version"] and [row["version"] for row in events] == list(range(1, plan["row_version"] + 1)), "Original complete supply command/event history differs")
    for event in events:
        command, audit, message = commands[event["version"]], audits[event["audit_event_id"]], outbox[event["outbox_event_id"]]
        require(command["plan_id"] == event["plan_id"] == plan["id"] and event["request_json"] == command["request_json"]
            and sha(command["request_json"]) == command["request_digest"] == event["request_digest"]
            and command["operation"] == event["operation"] == command["request_json"]["operation"]
            and command["actor_id"] == event["actor_id"] == command["request_json"]["actor_id"] == audit["actor_user_id"]
            and audit["object_id"] == message["aggregate_id"] == plan["id"]
            and message["payload"] == {**audit["metadata_json"], "audit_event_id": audit["id"]}, "Original exact supply audit/outbox/actor membership differs")
        require(command["response_json"]["source"] == original_ack(plan, tables, event["version"]), "Original historical supply ACK differs from native source membership")
        if command["native_kind"]:
            native_name, native_key = {"SRC": ("procurement_sourcing_commands", "requisition_id"),
                "PP": ("procurement_partial_commands", "order_id"), "BPC": ("procurement_commitment_commands", "order_id"),
                "ME2": ("manufacturing_execution_v2_commands", "object_id")}[command["native_kind"]]
            native = next(row for row in tables[native_name] if row["command_id"] == command["native_command_id"] and row[native_key] == command["native_owner_id"])
            require(native["actor_id"] == command["actor_id"] and native["response_json"] == command["response_json"]["native_response"], "Original native source ACK ownership differs")
    require(events[0]["operation"] == "create" and events[0]["actor_id"] == plan["creator_actor_id"]
        and events[1]["operation"] == "approve" and events[1]["actor_id"] == plan["reviewer_actor_id"]
        and plan["creator_actor_id"] != plan["reviewer_actor_id"] and events[-1]["operation"] == "handoff", "Original independent approved lifecycle differs")
    sourcing = companion(proof, "verify_procurement_sourcing_oracle.py").verify(sourcing_packet(tables, purchase))
    require(sourcing["received_minor"] == sourcing["consumed_minor"] and sourcing["source_reserved_minor"] == "0", "Original full receipt/AP/budget required before handoff")
    # Every AP effect is independently checked above. Remove precisely those
    # original AP accrual rows from the ME2 material/expense projection so its
    # strict complete native effect population can prove the rest independently.
    ap_ids = {row["accrual_effect_id"] for row in tables["procurement_partial_invoices"]}
    ap_entries = {row["entry_id"] for row in tables["finance_posting_effects"] if row["id"] in ap_ids}
    names = {"manufacturing_execution_boms", "manufacturing_execution_orders", "manufacturing_execution_requirements", "manufacturing_execution_reservations",
        "manufacturing_execution_completions", "manufacturing_execution_events", "manufacturing_execution_commands", "inventory_receipt_plans", "inventory_receipt_reviews",
        "inventory_receipt_commands", "inventory_receipt_links", "inventory_movements", "inventory_movement_lines", "inventory_valuation_documents", "inventory_valuation_lines",
        "inventory_cost_layers", "inventory_layer_consumptions", "finance_entries", "finance_entry_lines", "finance_entry_line_dimensions", "finance_posting_effects",
        "domain_audit_events", "outbox_events", "finance_accounts", "financial_effect_claim_gates", "financial_effect_ownership_guards", "financial_effect_ownership_releases",
        *("manufacturing_execution_v2_" + name for name in ("definitions", "orders", "cost_claims", "cost_releases", "productions", "inspections", "events", "commands"))}
    projected = {name: copy.deepcopy(tables[name]) for name in sorted(names)}
    projected["finance_posting_effects"] = [row for row in projected["finance_posting_effects"] if row["id"] not in ap_ids]
    projected["finance_entries"] = [row for row in projected["finance_entries"] if row["id"] not in ap_entries]
    projected["finance_entry_lines"] = [row for row in projected["finance_entry_lines"] if row["entry_id"] not in ap_entries]
    me2_proof = {"schema_version": "manufacturing-execution-proof-v2", "tenant_id": tenant, "populations": projected}
    manufacture = companion(proof, "verify_manufacturing_v2_cycle_oracle.py").verify_proof(me2_proof)
    require(manufacture["order_id"] == plan["manufacturing_order_id"]
        and tables["manufacturing_execution_orders"][0]["id"] == plan["material_order_id"], "Actual native production owner differs from supply target")
    accounts = indexed(tables["finance_accounts"])
    entries = indexed(tables["finance_entries"])
    positions: Counter[str] = Counter()
    turnover = 0
    for effect in tables["finance_posting_effects"]:
        entry = entries[effect["entry_id"]]
        lines = sorted((row for row in tables["finance_entry_lines"] if row["entry_id"] == entry["id"]), key=lambda row: row["line_number"])
        snapshot = effect["snapshot_json"]
        require(sha(snapshot) == effect["validation_digest"] == entry["validation_digest"]
            and len(lines) == len(snapshot["lines"])
            and all({key: row.get(key) for key in saved if key != "dimensions"} == {key: saved[key] for key in saved if key != "dimensions"}
                and saved["dimensions"] == {} for row, saved in zip(lines, snapshot["lines"], strict=True)), "Original entire AP/production GL line population differs")
        debit = sum(integer(line["debit_minor"]) for line in lines)
        credit = sum(integer(line["credit_minor"]) for line in lines)
        require(debit == credit == entry["total_debit_minor"] == entry["total_credit_minor"], "Original entire double entry differs")
        turnover += debit
        for line in lines:
            positions[accounts[line["account_id"]]["account_code"]] += line["debit_minor"] - line["credit_minor"]
    require(set(entries) == {row["entry_id"] for row in tables["finance_posting_effects"]}, "Detached native AP/production entry population")
    return {**manufacture, "schema_version": "manufacturing-supply-oracle-result-v1", "supply_plan_id": plan["id"],
        "supply_source_digest": plan["source_digest"], "net_quantities": net, "sourcing": sourcing,
        "quantity_claims": len(stock), "quantity_releases": len(releases), "supply_commands": len(commands),
        "posting_effects": len(tables["finance_posting_effects"]), "balanced_turnover_minor": str(turnover),
        "original_effect_ids": sorted(row["id"] for row in tables["finance_posting_effects"]),
        "native_positions_minor": {key: str(value) for key, value in sorted(positions.items())},
        "me2_projection_sha256": sha(me2_proof), "excluded_independently_verified_ap_effect_ids": sorted(ap_ids),
        "companion_sources_sha256": {key: value for key, value in capture["source_files_sha256"].items() if key.startswith(".github/scripts/")},
        "oracle_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "external_attestation": False, "performance_accepted": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--proof", required=True, type=Path)
    parser.add_argument("--proof-sha256", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    require(re.fullmatch("[0-9a-f]{64}", args.proof_sha256) is not None, "Separately retained original raw SHA required")
    require(args.proof.is_file() and args.proof.stat().st_size <= 32 * 1024 * 1024, "Bounded original proof file required")
    require(not args.output.exists() and args.output.resolve() != args.proof.resolve(), "Preserve all original proof/result files")
    raw = args.proof.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == args.proof_sha256, "Original raw proof bytes differ")
    result = {**verify_proof(json.loads(raw, object_pairs_hook=unique_object)), "original_proof_sha256": args.proof_sha256}
    args.output.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(canonical(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
