"""Independent external oracle adversaries; synthetic rows do not claim native acceptance."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / ".github/scripts/verify_manufacturing_cycle_oracle.py"
spec = importlib.util.spec_from_file_location("me_external_oracle", SCRIPT)
assert spec and spec.loader
oracle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(oracle)


def proof_fixture() -> dict[str, Any]:
    """Hand-built original inputs and native output rows; no application imports."""
    scope = {"workspace_id": "work", "organization_id": "org", "legal_entity_id": "entity"}
    policy = {"precision": 2, "rounding_policy": "ROUND_HALF_UP", "registry_version": "synthetic-v1", "registry_digest": "a" * 64}
    names = ["manufacturing_execution_orders", "manufacturing_execution_boms", "manufacturing_execution_requirements",
             "manufacturing_execution_completions", "manufacturing_execution_commands", "manufacturing_execution_events",
             "inventory_cost_layers", "inventory_layer_consumptions", "inventory_receipt_plans", "inventory_receipt_links",
             "finance_entries", "finance_entry_lines", "finance_entry_line_dimensions", "finance_posting_effects",
             "finance_accounts", "domain_audit_events", "outbox_events", "inventory_valuation_documents", "inventory_valuation_lines", "inventory_movements", "inventory_movement_lines"]
    tables: dict[str, list[dict[str, Any]]] = {name: [] for name in names}

    def add(name: str, row: dict[str, Any]) -> dict[str, Any]:
        row["tenant_id"] = "synthetic"
        tables[name].append(row)
        return row

    for code in ("WIP", "FG", "SCRAP", "INVENTORY", "CLEARING"):
        add("finance_accounts", {"id": code, "account_code": code})

    def journal(identifier: str, lines: list[tuple[str, int, int]], *, posted: bool = True) -> dict[str, Any]:
        header = {"id": identifier, **scope, "organization_code": "ORG", "entity_code": "ENTITY", "preparer_actor_id": "maker",
                  "journal_id": "JOURNAL", "period_id": "period", "entry_number": identifier, "posting_date": "2026-10-03", "description": "Original source", "external_reference": identifier, "source_type": "Generated", "reverses_posting_id": None,
                  "currency_code": "USD", "currency_precision": 2, "currency_rounding_policy": policy["rounding_policy"],
                  "currency_registry_version": policy["registry_version"], "currency_registry_digest": policy["registry_digest"]}
        saved = [{"line_number": n, "account_id": account, "description": "Original source", "debit_minor": dr, "credit_minor": cr, "dimensions": {}}
                 for n, (account, dr, cr) in enumerate(lines, 1)]
        snapshot = {"schema_version": "finance-entry-review-v1", "entry": {key: value for key, value in header.items() if key not in {"organization_code", "entity_code"}}, "lines": saved}
        digest = oracle.sha(snapshot)
        add("finance_entries", {**{key: value for key, value in header.items() if key not in {"organization_id", "legal_entity_id"}},
                                "status": "Validated" if posted else "Voided", "total_debit_minor": sum(line[1] for line in lines),
                                "total_credit_minor": sum(line[2] for line in lines), "validation_digest": digest, "validator_actor_id": "checker"})
        for n, line in enumerate(saved, 1):
            add("finance_entry_lines", {**{key: value for key, value in line.items() if key != "dimensions"}, "entry_id": identifier, "id": identifier + str(n), "currency_code": "USD"})
        if posted:
            add("finance_posting_effects", {"id": "effect-" + identifier, "entry_id": identifier, "snapshot_json": snapshot, "validation_digest": digest, "posted_actor_id": "poster"})
        return {"entry_id": identifier, "snapshot": snapshot, "validation_digest": digest}

    def receipt(identifier: str, item: str, uom: str, quantity: int, cost: int, inventory: str, offset: str, *, posted: bool = True) -> dict[str, Any]:
        entry = journal("entry-" + identifier, [(inventory, cost, 0), (offset, 0, cost)], posted=True) if posted else None
        plan = {"plan_id": "plan-" + identifier, "source": {"number": identifier, "total_value_minor": cost},
                "finance_snapshot": entry["snapshot"] if entry else {}, "artifacts": {"posting_effect_id": "effect-entry-" + identifier}}
        plan["plan_digest"] = oracle.sha(plan)
        add("inventory_receipt_plans", {"id": plan["plan_id"], "source_number": identifier, "operation": "Receipt", "plan_json": plan,
                                      **scope, "location_id": "location", "valuation_line_id": "vl-" + identifier, "valuation_document_id": "vd-" + identifier,
                                      "movement_id": "move-" + identifier, "movement_line_id": "ml-" + identifier,
                                      "plan_digest": plan["plan_digest"], "cost_layer_id": "layer-" + identifier, "item_id": item, "uom_id": uom,
                                      "quantity_scaled": quantity, "total_value_minor": cost, "inventory_account_id": inventory,
                                      "receipt_clearing_account_id": offset, "posting_effect_id": "effect-entry-" + identifier, "finance_entry_id": "entry-" + identifier})
        if posted:
            add("inventory_receipt_links", {"id": plan["plan_id"], "plan_id": plan["plan_id"], "posting_effect_id": "effect-entry-" + identifier, "finance_entry_id": "entry-" + identifier})
            add("inventory_cost_layers", {"id": "layer-" + identifier, "item_id": item, "uom_id": uom, "created_at": "2026-10-03",
                                         "workspace_id": scope["workspace_id"], "legal_entity_id": scope["legal_entity_id"], "source_valuation_line_id": "vl-" + identifier,
                                         "original_quantity_scaled": quantity, "remaining_quantity_scaled": quantity,
                                         "original_value_minor": cost, "remaining_value_minor": cost})
            add("inventory_valuation_documents", {"id": "vd-" + identifier, **scope, "movement_id": "move-" + identifier, "status": "Approved"})
            add("inventory_valuation_lines", {"id": "vl-" + identifier, "valuation_document_id": "vd-" + identifier, "item_id": item, "uom_id": uom,
                                              "quantity_scaled": quantity, "value_minor": cost, "flow_direction": "Inbound", "inventory_account_id": inventory, "offset_account_id": offset})
            add("inventory_movements", {"id": "move-" + identifier, **scope, "status": "Posted", "movement_type": "Receipt"})
            add("inventory_movement_lines", {"id": "ml-" + identifier, "movement_id": "move-" + identifier, "item_id": item, "uom_id": uom,
                                            "quantity_scaled": quantity, "from_location_id": None, "to_location_id": "location"})
        return plan

    source = {"id": "ME1-order", **scope, "organization_code": "ORG", "entity_code": "ENTITY", "currency_code": "USD", "monetary_policy": policy,
              "bom_version_id": "ME1B-recipe", "output_quantity_scaled": 10, "output_item_id": "PRODUCT", "wip_account_id": "WIP", "scrap_account_id": "SCRAP",
              "command_request": {"number": "PRODUCTION-1", "reason": "Synthetic lifecycle"}}
    components, issue_components = [], []
    for item, uom, precision, original_q, original_v, required_q in (("ITEM", "EA", 0, 10, 12000, 2), ("MATERIAL", "KG", 3, 20000, 3333, 3000)):
        receipt(item, item, uom, original_q, original_v, "INVENTORY", "CLEARING")
        component = {"item_id": item, "item_code": item, "uom_id": uom, "uom_code": uom, "quantity_precision": precision, "quantity_scaled": required_q}
        components.append(component)
        cost = 2400 if item == "ITEM" else 500  # Independent original integer golden inputs.
        issue_components.append({**component, "required_quantity_scaled": required_q, "inventory_account_id": "INVENTORY", "value_minor": cost,
                                 "allocations": [{"cost_layer_id": "layer-" + item, "quantity_scaled": required_q, "value_minor": cost,
                                                  "remaining_quantity_scaled": original_q, "remaining_value_minor": original_v}]})
        layer = tables["inventory_cost_layers"][-1]
        layer.update(remaining_quantity_scaled=original_q - required_q, remaining_value_minor=original_v - cost)
        add("inventory_layer_consumptions", {"id": "consumed-" + item, "cost_layer_id": layer["id"], "quantity_scaled": required_q, "value_minor": cost})
    recipe = {"id": "ME1B-recipe", **scope, "components": components, "output_quantity_scaled": 10, "command_request": {"number": "BOM-1", "reason": "Synthetic lifecycle"}}
    bom = add("manufacturing_execution_boms", {"id": recipe["id"], "payload": recipe, "phase": 1, "source_digest": oracle.sha(recipe), "reviewer_id": "checker"})
    source["bom_digest"] = bom["source_digest"]
    source_digest = oracle.sha(source)
    issue = {"source_digest": source_digest, "components": issue_components, "total_cost_minor": 2900, "preparer_actor_id": "maker",
             "entry": journal("issue", [("WIP", 2900, 0), ("INVENTORY", 0, 2900)])}
    order = add("manufacturing_execution_orders", {"id": source["id"], "payload": source, "phase": 4, "source_digest": source_digest,
                                                  "issue_plan": issue, "issue_digest": oracle.sha(issue), "issue_effect_id": "effect-issue", "issue_reviewer_id": "checker",
                                                  "disposed_quantity_scaled": 10, "released_cost_minor": 2900, "valuation_id": "issued-valuation"})
    for component in components:
        identifier, required = "require-" + component["item_id"], component["quantity_scaled"]
        payload = {"schema_version": "manufacturing-requirement-v1", "requirement_id": identifier, "order_id": order["id"], "bom_version_id": bom["id"],
                   "order_source_digest": source_digest, "bom_digest": bom["source_digest"], "scope": scope,
                   **{key: component[key] for key in ("item_id", "item_code", "uom_id", "uom_code", "quantity_precision")},
                   "required_quantity_scaled": required, "required_quantity": oracle.fixed(required, component["quantity_precision"])}
        add("manufacturing_execution_requirements", {"id": identifier, "item_id": component["item_id"], "uom_id": component["uom_id"],
                                                    "required_quantity_scaled": required, "requirement_json": payload, "requirement_digest": oracle.sha(payload)})
    for identifier, phase, good, scrap, before_q, before_v, good_v, scrap_v in (("ME1C-cancelled", 3, 3, 1, 0, 0, 870, 290), ("ME1C-first", 2, 3, 1, 0, 0, 870, 290), ("ME1C-final", 2, 6, 0, 4, 1160, 1740, 0)):
        child = {"id": identifier, "order_id": order["id"], **scope, "order_digest": source_digest, "issue_digest": order["issue_digest"], "preparer_actor_id": "maker",
                 "command_request": {"id": order["id"], "good": good, "scrap": scrap, "reason": "Synthetic lifecycle"}, "good_quantity_scaled": good, "scrap_quantity_scaled": scrap,
                 "stage_quantity_scaled": good + scrap, "disposed_before_scaled": before_q, "released_before_minor": before_v,
                 "good_cost_minor": good_v, "scrap_cost_minor": scrap_v, "released_cost_minor": good_v + scrap_v, "wip_after_minor": 2900 - before_v - good_v - scrap_v,
                 "receipt_plan": receipt(identifier, "PRODUCT", "EA", good, good_v, "FG", "WIP", posted=phase == 2),
                 "scrap_entry": journal("scrap-" + identifier, [("SCRAP", scrap_v, 0), ("WIP", 0, scrap_v)], posted=phase == 2) if scrap else None}
        effect = {"effect_id": "effect-entry-" + identifier, "entry_id": "entry-" + identifier, "posted_actor_id": "poster"}
        add("manufacturing_execution_completions", {"id": identifier, "order_id": order["id"], "payload": child, "source_digest": oracle.sha(child), "phase": phase,
                                                    "reviewer_id": "checker", "receipt_effect": {**effect, "effect_digest": oracle.sha(effect)} if phase == 2 else None,
                                                    "scrap_effect_id": "effect-scrap-" + identifier if scrap and phase == 2 else None})
    for row in [bom, order, *tables["manufacturing_execution_completions"]]:
        operations = ("create", "approve-bom") if row is bom else ("create", "prepare", "review", "post") if row is order else ("create", "review", "post" if row["phase"] == 2 else "cancel")
        for operation in operations:
            actor = "checker" if operation in {"review", "approve-bom", "cancel"} else "poster" if operation == "post" else "maker"
            event_id = row["id"] + operation
            request = row["payload"]["command_request"] if operation == "create" else {"id": row["id"], "expected_digest": row["source_digest"], "reason": "Synthetic lifecycle"}
            wire = {"operation": operation, "actor_id": actor, "request": request}
            kind = "bom" if row is bom else "order" if row is order else "completion"
            ack = oracle.historical_ack(row, kind, operation)
            metadata = {"source_digest": row["source_digest"], "phase": ack["phase"], "reason": "Synthetic lifecycle"}
            add("manufacturing_execution_commands", {"id": event_id, "object_id": row["id"], "operation": operation, "actor_id": actor,
                                                     "workspace_id": "work", "request_json": wire, "request_digest": oracle.sha(wire), "response_json": ack})
            add("manufacturing_execution_events", {"id": event_id, "object_id": row["id"], "operation": operation, "actor_id": actor, "reason": "Synthetic lifecycle",
                                                   "metadata": metadata, "audit_event_id": "audit-" + event_id, "outbox_event_id": "outbox-" + event_id})
            add("domain_audit_events", {"id": "audit-" + event_id, "actor_user_id": actor, "object_id": row["id"], "object_type": "manufacturing_execution", "action": "manufacturing_execution." + operation, "metadata_json": metadata})
            add("outbox_events", {"event_id": "outbox-" + event_id, "aggregate_id": row["id"], "event_type": "manufacturing_execution." + operation,
                                  "aggregate_type": "manufacturing_execution", "payload": {**metadata, "audit_event_id": "audit-" + event_id}, **scope})
    return {"schema_version": "manufacturing-execution-proof-v1", "tenant_id": "synthetic", "populations": tables}


def test_complete_native_population_golden() -> None:
    result = oracle.verify_proof(proof_fixture())
    assert (result["issued_material_minor"], result["finished_cost_minor"], result["abnormal_scrap_minor"], result["remaining_wip_minor"]) == ("2900", "2610", "290", "0")
    assert result["posting_effects"] == 6 and result["balanced_turnover_minor"] == "21133"
    assert result["performance_accepted"] is False and result["external_attestation"] is False


@pytest.mark.parametrize("target", ["cost", "quantity", "effect", "header", "dimension", "requirement", "orphan", "cancel", "line", "link", "actor", "tenant", "ack", "orphan_pair", "layer_scope", "component_duplicate"])
def test_rehashed_financial_or_source_population_adversaries_refused(target: str) -> None:
    proof = proof_fixture()
    rows = proof["populations"]
    if target == "cost":
        rows["inventory_layer_consumptions"][0]["value_minor"] += 1
    elif target == "quantity":
        rows["inventory_cost_layers"][0]["remaining_quantity_scaled"] += 1
    elif target == "effect":
        rows["finance_posting_effects"][-1]["id"] = "unique-invented-effect"
    elif target == "header":
        rows["finance_entries"][0]["entity_code"] = "FOREIGN"
    elif target == "dimension":
        rows["finance_entry_line_dimensions"].append({"tenant_id": "synthetic", "dimension_id": "hidden"})
    elif target == "requirement":
        row = rows["manufacturing_execution_requirements"][0]
        row["requirement_json"]["item_code"] = "FOREIGN"
        row["requirement_digest"] = oracle.sha(row["requirement_json"])
    elif target == "orphan":
        rows["manufacturing_execution_events"].append(copy.deepcopy(rows["manufacturing_execution_events"][0]))
    elif target == "cancel":
        rows["finance_entries"][3]["status"] = "Validated"
    elif target == "line":
        rows["finance_entry_lines"].append(copy.deepcopy(rows["finance_entry_lines"][0]))
    elif target == "link":
        rows["inventory_receipt_links"][0]["posting_effect_id"] = "unique-invented-effect"
    elif target == "actor":
        rows["finance_posting_effects"][-1]["posted_actor_id"] = "maker"
    elif target == "ack":
        rows["manufacturing_execution_commands"][0]["response_json"].update(phase=999, wip_minor=999999999)
    elif target == "orphan_pair":
        for name in ("manufacturing_execution_commands", "manufacturing_execution_events"):
            row = copy.deepcopy(rows[name][0])
            row.update(id="orphan", object_id="ME1-orphan-owner")
            rows[name].append(row)
    elif target == "layer_scope":
        rows["inventory_cost_layers"][0].update(workspace_id="foreign", legal_entity_id="foreign")
    elif target == "component_duplicate":
        order = rows["manufacturing_execution_orders"][0]
        order["issue_plan"]["components"].append(copy.deepcopy(order["issue_plan"]["components"][0]))
        order["issue_digest"] = oracle.sha(order["issue_plan"])
    else:
        rows["finance_accounts"][0]["tenant_id"] = "foreign"
    with pytest.raises((ValueError, KeyError)):
        oracle.verify_proof(proof)


def test_independent_rounding_and_final_residual_conservation() -> None:
    assert [oracle.even(Fraction(n, 2)) for n in (1, 3, 5, 7)] == [0, 2, 2, 4]
    for cost in (7, 11, 101, 2900, 9_000_000_000_000_000_000):
        disposed = released = 0
        for good, scrap in ((2, 0), (2, 1), (5, 0)):
            part = oracle.disposition(10, cost, disposed, released, good, scrap)
            disposed += part["stage_quantity_scaled"]
            released += part["released_cost_minor"]
        assert disposed == 10 and released == cost and part["wip_after_minor"] == 0
    for args in ((1, 1, 0, 0, True, 0), (1, 1, 0, 0, 0, 0), (3, 1, 0, 0, 1, 0), (10, 100, 11, 0, 1, 0)):
        with pytest.raises(ValueError):
            oracle.disposition(*args)


@pytest.mark.parametrize("optimized", [False, True])
def test_outside_checkout_isolated_cli_and_separately_trusted_raw_bytes(tmp_path: Path, optimized: bool) -> None:
    raw = json.dumps(proof_fixture(), indent=2).encode()
    proof = tmp_path / "original.json"
    proof.write_bytes(raw)
    output = tmp_path / "oracle.json"
    args = [sys.executable, "-I", *(["-O"] if optimized else []), str(SCRIPT), "--proof", str(proof), "--proof-sha256", hashlib.sha256(raw).hexdigest(), "--output", str(output)]
    result = subprocess.run(args, cwd=tmp_path, capture_output=True, text=True, check=False, timeout=10)
    assert result.returncode == 0, result.stderr
    assert json.loads(output.read_text())["financial_verification"] == "passed"
    proof.write_bytes(raw + b" ")
    assert subprocess.run(args, cwd=tmp_path, capture_output=True, check=False, timeout=10).returncode != 0


def test_original_duplicate_json_members_refused() -> None:
    with pytest.raises(ValueError, match="Duplicate"):
        json.loads('{"id":"original","id":"replacement"}', object_pairs_hook=oracle.unique_object)
