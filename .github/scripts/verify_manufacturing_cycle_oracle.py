"""Independent stdlib ME1 material/FIFO/WIP/output/scrap oracle over a trusted raw proof.

This tool reads files only. A caller supplies the separately retained original raw
SHA; an internal hash alone is not external attestation or a performance gate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from fractions import Fraction
from pathlib import Path
from typing import Any

HEADER_FIELDS = {"id", "workspace_id", "organization_id", "legal_entity_id", "journal_id", "period_id", "entry_number", "posting_date", "description", "external_reference", "source_type", "currency_code", "currency_precision", "currency_rounding_policy", "currency_registry_version", "currency_registry_digest", "preparer_actor_id", "reverses_posting_id"}
LINE_FIELDS = {"line_number", "account_id", "description", "debit_minor", "credit_minor", "dimensions"}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def sha(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        require(key not in result, "Duplicate original JSON member")
        result[key] = value
    return result


def fixed(value: int, precision: int) -> str:
    integer(value)
    require(type(precision) is int and 0 <= precision <= 8, "Original exact UOM precision required")
    digits = str(value).zfill(precision + 1)
    return digits if precision == 0 else digits[:-precision] + "." + digits[-precision:]


def integer(value: Any, *, positive: bool = False) -> int:
    require(type(value) is int and int(positive) <= value <= 9_000_000_000_000_000_000, "Exact bounded source integer required")
    return value


def even(value: Fraction) -> int:
    base, rest = divmod(value.numerator, value.denominator)
    return base + int(rest * 2 > value.denominator or rest * 2 == value.denominator and base % 2 == 1)


def disposition(quantity: int, cost: int, disposed: int, released: int, good: int, scrap: int) -> dict[str, int]:
    for value in (quantity, cost):
        integer(value, positive=True)
    for value in (disposed, released, good, scrap):
        integer(value)
    stage = good + scrap
    require(0 < stage <= quantity - disposed and 0 <= released < cost, "Original residual quantity/cost exhausted")
    value = cost - released if stage == quantity - disposed else even(Fraction((cost - released) * stage, quantity - disposed))
    good_cost = value if good == stage else even(Fraction(value * good, stage))
    require((good == 0 or good_cost > 0) and (scrap == 0 or value - good_cost > 0), "Positive financial disposition cannot have zero cost")
    return {"stage_quantity_scaled": stage, "released_cost_minor": value, "good_cost_minor": good_cost,
            "scrap_cost_minor": value - good_cost, "wip_after_minor": cost - released - value,
            "disposed_before_scaled": disposed, "released_before_minor": released}


def _map(rows: Any, field: str = "id") -> dict[str, dict[str, Any]]:
    require(type(rows) is list and all(type(row) is dict and type(row.get(field)) is str and row[field] for row in rows), "Native row identity required")
    result = {row[field]: row for row in rows}
    require(len(result) == len(rows), "Duplicate native population identity")
    return result


def historical_ack(row: dict[str, Any], kind: str, operation: str) -> dict[str, Any]:
    """Reconstruct immutable historical response rather than trust a replay seal."""
    phases = {"bom": {"create": 0, "approve-bom": 1}, "order": {"create": 0, "prepare": 1, "review": 2, "post": 3},
              "completion": {"create": 0, "review": 1, "post": 2, "cancel": 3}}
    phase = phases[kind][operation]
    response = {**row["payload"], "source_digest": row["source_digest"], "phase": phase}
    if kind == "bom":
        response["reviewer_id"] = row["reviewer_id"] if phase == 1 else None
    elif kind == "completion":
        response.update(reviewer_id=row["reviewer_id"] if phase else None,
                        receipt_effect=row["receipt_effect"] if phase == 2 else None,
                        scrap_effect_id=row["scrap_effect_id"] if phase == 2 else None)
    else:
        response.update(issue_plan=row["issue_plan"] if phase else None, issue_digest=row["issue_digest"] if phase else None,
                        issue_reviewer_id=row["issue_reviewer_id"] if phase >= 2 else None,
                        issue_effect_id=row["issue_effect_id"] if phase == 3 else None,
                        valuation_id=row["valuation_id"] if phase == 3 else None, disposed_quantity_scaled=0, released_cost_minor=0)
    return response


def verify_proof(proof: dict[str, Any]) -> dict[str, Any]:
    require(proof.get("schema_version") == "manufacturing-execution-proof-v1", "Unsupported manufacturing proof")
    tables, tenant = proof["populations"], proof["tenant_id"]
    require(type(tables) is dict and type(tenant) is str and bool(tenant), "Original tenant/populations required")
    for rows in tables.values():
        require(type(rows) is list and all(type(row) is dict and row.get("tenant_id") == tenant for row in rows), "Cross-tenant native source population")
    orders, boms = _map(tables["manufacturing_execution_orders"]), _map(tables["manufacturing_execution_boms"])
    require(len(orders) == len(boms) == 1, "This bounded oracle requires one complete original batch and BOM")
    order, bom = next(iter(orders.values())), next(iter(boms.values()))
    source, recipe, issue = order["payload"], bom["payload"], order["issue_plan"]
    require(integer(order["phase"]) == 4 and integer(bom["phase"]) == 1 and source["bom_version_id"] == bom["id"]
            and sha(source) == order["source_digest"] and sha(recipe) == bom["source_digest"] == source["bom_digest"]
            and sha(issue) == order["issue_digest"] and issue["source_digest"] == order["source_digest"], "Original complete source/BOM/issue seals differ")
    scope = {key: source[key] for key in ("workspace_id", "organization_id", "legal_entity_id")}
    require(all(recipe[key] == value for key, value in scope.items()), "Original BOM hierarchy differs")
    accounts = _map(tables["finance_accounts"])
    require(len({row["account_code"] for row in accounts.values()}) == len(accounts), "Duplicate original native account code")
    require(tables["finance_entry_line_dimensions"] == [], "Required or retained financial dimensions are outside this explicit oracle scope")
    layers, entries, effects = (_map(tables[name]) for name in ("inventory_cost_layers", "finance_entries", "finance_posting_effects"))
    receipts = _map(tables["inventory_receipt_plans"])
    valuations, valuation_lines, movements, movement_lines = (_map(tables[name]) for name in
        ("inventory_valuation_documents", "inventory_valuation_lines", "inventory_movements", "inventory_movement_lines"))
    links = {row["plan_id"]: row for row in tables["inventory_receipt_links"]}
    require(len(links) == len(tables["inventory_receipt_links"]), "Duplicate native receipt effect")
    expected_effects: dict[str, tuple[str, list[tuple[str, int, int]], dict[str, Any]]] = {}

    def verify_receipt_layer(row: dict[str, Any], layer: dict[str, Any]) -> None:
        require(all(row[key] == value for key, value in scope.items()) and layer["workspace_id"] == scope["workspace_id"]
                and layer["legal_entity_id"] == scope["legal_entity_id"], "Native original layer/receipt hierarchy differs")
        value = valuation_lines[row["valuation_line_id"]]
        document, movement, line = valuations[row["valuation_document_id"]], movements[row["movement_id"]], movement_lines[row["movement_line_id"]]
        require(layer["source_valuation_line_id"] == value["id"] and value["valuation_document_id"] == document["id"]
                and document["movement_id"] == movement["id"] and line["movement_id"] == movement["id"]
                and all(document[key] == movement[key] == selected for key, selected in scope.items())
                and document["status"] == "Approved" and movement["status"] == "Posted" and movement["movement_type"] == "Receipt",
                "Native original layer valuation/movement lineage differs")
        require((value["item_id"], value["uom_id"], value["quantity_scaled"], value["value_minor"], value["flow_direction"], value["inventory_account_id"], value["offset_account_id"])
                == (row["item_id"], row["uom_id"], row["quantity_scaled"], row["total_value_minor"], "Inbound", row["inventory_account_id"], row["receipt_clearing_account_id"])
                and (line["item_id"], line["uom_id"], line["quantity_scaled"], line["from_location_id"], line["to_location_id"])
                == (row["item_id"], row["uom_id"], row["quantity_scaled"], None, row["location_id"]), "Native original receipt item/UOM/quantity/cost/location differs")

    def retain(effect_id: str, entry_id: str, lines: list[tuple[str, int, int]], snapshot: dict[str, Any]) -> None:
        require(effect_id not in expected_effects, "Native effect population reused")
        expected_effects[effect_id] = (entry_id, lines, snapshot)

    original_inputs = [row for row in receipts.values() if not row["source_number"].startswith("ME1C-")]
    require(1 <= len(original_inputs) <= 100, "Actual original receipt inputs required")
    initial_layers: set[str] = set()
    for row in original_inputs:
        plan = row["plan_json"]
        require(row["id"] in links and row["operation"] == "Receipt", "Original input must have native receipt effect")
        require(sha({k: v for k, v in plan.items() if k not in {"plan_digest", "preparation_audit_event_id", "preparation_outbox_event_id"}}) == plan["plan_digest"] == row["plan_digest"], "Original input plan seal differs")
        layer = layers[row["cost_layer_id"]]
        verify_receipt_layer(row, layer)
        require((layer["original_quantity_scaled"], layer["original_value_minor"], layer["item_id"])
                == (integer(row["quantity_scaled"], positive=True), integer(row["total_value_minor"], positive=True), row["item_id"]), "Original native layer input differs")
        initial_layers.add(layer["id"])
        require(links[row["id"]]["posting_effect_id"] == row["posting_effect_id"] and links[row["id"]]["finance_entry_id"] == row["finance_entry_id"], "Original input native effect link differs")
        retain(row["posting_effect_id"], row["finance_entry_id"], [(row["inventory_account_id"], row["total_value_minor"], 0), (row["receipt_clearing_account_id"], 0, row["total_value_minor"])], plan["finance_snapshot"])
    requirements = {row["item_id"]: row for row in tables["manufacturing_execution_requirements"]}
    components = {line["item_id"]: line for line in recipe["components"]}
    issued = {line["item_id"]: line for line in issue["components"]}
    require(1 <= len(components) <= 100 and len(components) == len(recipe["components"]) == len(issue["components"])
            and set(requirements) == set(components) == set(issued) and len(requirements) == len(tables["manufacturing_execution_requirements"]), "Complete unique BOM/input population required")
    planned = integer(source["output_quantity_scaled"], positive=True)
    consumed_expected: Counter[tuple[str, int, int]] = Counter()
    layer_totals: dict[str, list[int]] = {}
    inventory_credits: dict[str, int] = {}
    total = 0
    for item, component in components.items():
        demand = Fraction(integer(component["quantity_scaled"], positive=True) * planned, integer(recipe["output_quantity_scaled"], positive=True))
        require(demand.denominator == 1, "Original base UOM expansion is fractional")
        requirement, material = requirements[item], issued[item]
        require(integer(requirement["required_quantity_scaled"], positive=True) == integer(material["required_quantity_scaled"], positive=True) == demand.numerator
                and requirement["item_id"] == material["item_id"] and requirement["uom_id"] == component["uom_id"] == material["uom_id"]
                and sha(requirement["requirement_json"]) == requirement["requirement_digest"], "Original exact BOM demand differs")
        expected_requirement = {"schema_version": "manufacturing-requirement-v1", "requirement_id": requirement["id"], "order_id": order["id"],
                                "bom_version_id": bom["id"], "order_source_digest": order["source_digest"], "bom_digest": bom["source_digest"], "scope": scope,
                                **{key: component[key] for key in ("item_id", "item_code", "uom_id", "uom_code", "quantity_precision")},
                                "required_quantity_scaled": demand.numerator, "required_quantity": fixed(demand.numerator, component["quantity_precision"])}
        require(requirement["requirement_json"] == expected_requirement, "Original canonical requirement differs from the BOM/UOM/scalar source")
        quantity = value = 0
        allocation_ids: set[str] = set()
        remaining = demand.numerator
        original_fifo = sorted((layers[identifier] for identifier in initial_layers if layers[identifier]["item_id"] == item), key=lambda row: (row["created_at"], row["id"]))
        expected_allocations = []
        for layer in original_fifo:
            if remaining == 0:
                break
            taken = min(remaining, integer(layer["original_quantity_scaled"], positive=True))
            expected_allocations.append((layer["id"], taken))
            remaining -= taken
        require(remaining == 0 and [(part["cost_layer_id"], part["quantity_scaled"]) for part in material["allocations"]] == expected_allocations, "Independent whole original FIFO allocation order differs")
        for allocation in material["allocations"]:
            identifier = allocation["cost_layer_id"]
            require(identifier in initial_layers and identifier not in allocation_ids, "Material must consume an original unique receipt layer")
            allocation_ids.add(identifier)
            layer = layers[identifier]
            require(layer["item_id"] == item and layer["uom_id"] == requirement["uom_id"], "Original material layer item/UOM differs")
            taken = integer(allocation["quantity_scaled"], positive=True)
            original_q, original_v = layer["original_quantity_scaled"], layer["original_value_minor"]
            require(0 < taken <= original_q and (allocation["remaining_quantity_scaled"], allocation["remaining_value_minor"]) == (original_q, original_v), "Independent original residual input differs")
            cost = original_v if taken == original_q else even(Fraction(original_v * taken, original_q))
            require(allocation["value_minor"] == cost, "Independent original FIFO cost differs")
            consumed_expected[(identifier, taken, cost)] += 1
            layer_totals[identifier] = [taken, cost]
            quantity += taken
            value += cost
        require(quantity == demand.numerator and material["value_minor"] == value, "Whole material quantity/cost differs")
        inventory_credits[material["inventory_account_id"]] = inventory_credits.get(material["inventory_account_id"], 0) + value
        total += value
    require(integer(issue["total_cost_minor"], positive=True) == total, "Independent original WIP differs")
    observed_consumptions = Counter((row["cost_layer_id"], row["quantity_scaled"], row["value_minor"]) for row in tables["inventory_layer_consumptions"])
    require(observed_consumptions == consumed_expected, "Native material consumption population differs")
    for identifier in initial_layers:
        layer = layers[identifier]
        taken, value = layer_totals.get(identifier, [0, 0])
        require((layer["remaining_quantity_scaled"], layer["remaining_value_minor"]) == (layer["original_quantity_scaled"] - taken, layer["original_value_minor"] - value), "Native original residual layer differs")
    retain(order["issue_effect_id"], issue["entry"]["entry_id"], [(source["wip_account_id"], total, 0), *((account, 0, amount) for account, amount in inventory_credits.items())], issue["entry"]["snapshot"])
    children = _map(tables["manufacturing_execution_completions"])
    require(1 <= len(children) <= 200, "Bounded original output population required")
    owner_rows = {**boms, **orders, **children}
    commands = {(row["object_id"], row["operation"]): row for row in tables["manufacturing_execution_commands"]}
    events = {(row["object_id"], row["operation"]): row for row in tables["manufacturing_execution_events"]}
    require(len(commands) == len(tables["manufacturing_execution_commands"]) == len(events) == len(tables["manufacturing_execution_events"])
            and set(commands) == set(events), "Original owner command/event bijection differs")
    expected_command_keys: set[tuple[str, str]] = set()
    audits, outbox = _map(tables["domain_audit_events"]), _map(tables["outbox_events"], "event_id")
    for identifier, row in owner_rows.items():
        expected_operations = {"create", "approve-bom"} if identifier == bom["id"] else {"create", "prepare", "review", "post"} if identifier == order["id"] else {"create", "review", "post" if row["phase"] == 2 else "cancel"}
        expected_command_keys.update((identifier, operation) for operation in expected_operations)
        require({operation for selected, operation in commands if selected == identifier} == expected_operations, "Original retained lifecycle command population differs")
        for operation in expected_operations:
            command, event = commands[(identifier, operation)], events[(identifier, operation)]
            request = row["payload"]["command_request"] if operation == "create" else {"id": identifier, "expected_digest": row["source_digest"], "reason": event["reason"]}
            ack = historical_ack(row, "bom" if identifier == bom["id"] else "order" if identifier == order["id"] else "completion", operation)
            require(command["request_json"] == {"operation": operation, "actor_id": command["actor_id"], "request": request}
                    and sha(command["request_json"]) == command["request_digest"] and command["actor_id"] == event["actor_id"]
                    and request["reason"] == event["reason"] and command["response_json"] == ack
                    and command["workspace_id"] == scope["workspace_id"]
                    and event["metadata"] == {"source_digest": row["source_digest"], "phase": ack["phase"], "reason": event["reason"]}, "Complete original owner historical request/ACK actor or seal differs")
            audit, message = audits[event["audit_event_id"]], outbox[event["outbox_event_id"]]
            require(audit["actor_user_id"] == command["actor_id"] and audit["object_id"] == message["aggregate_id"] == identifier
                    and audit["object_type"] == message["aggregate_type"] == "manufacturing_execution"
                    and audit["action"] == message["event_type"] == "manufacturing_execution." + operation
                    and audit["metadata_json"] == event["metadata"] and message["payload"] == {**event["metadata"], "audit_event_id": audit["id"]}
                    and all(message[key] == scope[key] for key in scope), "Original owner native audit/outbox differs")
    require(set(commands) == set(events) == expected_command_keys, "Every retained command/event must belong to an exact original source operation")
    issue_actors = [commands[(order["id"], operation)]["actor_id"] for operation in ("prepare", "review", "post")]
    require(len(set(issue_actors)) == 3 and issue_actors[0] == issue["preparer_actor_id"] and issue_actors[1] == order["issue_reviewer_id"]
            and issue_actors[2] == effects[order["issue_effect_id"]]["posted_actor_id"], "Original issue requires three distinct actual native humans")
    posted = sorted((row for row in children.values() if row["phase"] == 2), key=lambda row: row["payload"]["disposed_before_scaled"])
    disposed = released = good_total = scrap_total = 0
    output_layers: set[str] = set()
    expected_receipts = {row["id"] for row in original_inputs}
    expected_links = set(expected_receipts)
    cancelled_entries: set[str] = set()
    for row in children.values():
        child = row["payload"]
        require(row["order_id"] == order["id"] and sha(child) == row["source_digest"] and child["order_digest"] == order["source_digest"] and child["issue_digest"] == order["issue_digest"], "Original output source seal differs")
        integer(row["phase"])
        if child["receipt_plan"]:
            expected_receipts.add(child["receipt_plan"]["plan_id"])
        if row["phase"] != 2:
            require(row["phase"] == 3 and row["receipt_effect"] is None and row["scrap_effect_id"] is None, "Only posted or retained cancelled output permitted")
            if child["receipt_plan"]:
                require(child["receipt_plan"]["plan_id"] not in links and child["receipt_plan"]["artifacts"]["posting_effect_id"] not in effects, "Cancelled native output leaked effect")
            if child["scrap_entry"]:
                cancelled_entries.add(child["scrap_entry"]["entry_id"])
                require(entries[child["scrap_entry"]["entry_id"]]["status"] == "Voided", "Cancelled scrap draft must be voided")
    for row in posted:
        child = row["payload"]
        expected = disposition(planned, total, disposed, released, integer(child["good_quantity_scaled"]), integer(child["scrap_quantity_scaled"]))
        require(all(integer(child[key]) == value for key, value in expected.items()), "Independent cumulative good/scrap/residual cost differs")
        actors = [commands[(row["id"], operation)]["actor_id"] for operation in ("create", "review", "post")]
        require(len(set(actors)) == 3 and actors[0] == child["preparer_actor_id"] and actors[1] == row["reviewer_id"], "Original output requires three distinct native humans")
        good_total += expected["good_cost_minor"]
        scrap_total += expected["scrap_cost_minor"]
        disposed += expected["stage_quantity_scaled"]
        released += expected["released_cost_minor"]
        if child["good_quantity_scaled"]:
            plan, effect = child["receipt_plan"], row["receipt_effect"]
            require(sha({k: v for k, v in effect.items() if k != "effect_digest"}) == effect["effect_digest"] and plan["plan_id"] in links
                    and effect["posted_actor_id"] == effects[effect["effect_id"]]["posted_actor_id"] == actors[2], "Native finished effect seal/third human differs")
            native = receipts[plan["plan_id"]]
            expected_links.add(plan["plan_id"])
            require(native["plan_json"] == plan and effect["effect_id"] == native["posting_effect_id"]
                    and native["item_id"] == source["output_item_id"] and native["quantity_scaled"] == child["good_quantity_scaled"]
                    and native["total_value_minor"] == expected["good_cost_minor"] and native["receipt_clearing_account_id"] == source["wip_account_id"]
                    and links[plan["plan_id"]]["posting_effect_id"] == native["posting_effect_id"] and links[plan["plan_id"]]["finance_entry_id"] == native["finance_entry_id"], "Native finished receipt quantity/cost/WIP differs")
            output_layers.add(native["cost_layer_id"])
            layer = layers[native["cost_layer_id"]]
            verify_receipt_layer(native, layer)
            require((layer["original_quantity_scaled"], layer["remaining_quantity_scaled"], layer["original_value_minor"], layer["remaining_value_minor"])
                    == (child["good_quantity_scaled"], child["good_quantity_scaled"], expected["good_cost_minor"], expected["good_cost_minor"]), "Native finished FIFO differs")
            retain(effect["effect_id"], effect["entry_id"], [(native["inventory_account_id"], expected["good_cost_minor"], 0), (source["wip_account_id"], 0, expected["good_cost_minor"])], plan["finance_snapshot"])
        if child["scrap_quantity_scaled"]:
            require(effects[row["scrap_effect_id"]]["posted_actor_id"] == actors[2], "Abnormal scrap requires original third human")
            retain(row["scrap_effect_id"], child["scrap_entry"]["entry_id"], [(source["scrap_account_id"], expected["scrap_cost_minor"], 0), (source["wip_account_id"], 0, expected["scrap_cost_minor"])], child["scrap_entry"]["snapshot"])
    require(disposed == planned == order["disposed_quantity_scaled"] and released == total == order["released_cost_minor"] and total == good_total + scrap_total, "Complete quantity/WIP conservation differs")
    require(set(layers) == initial_layers | output_layers and set(effects) == set(expected_effects), "All and only original native effects/layers required")
    require(set(receipts) == expected_receipts and set(links) == expected_links, "All and only original posted/cancelled native receipt plans and links required")
    require(set(entries) == {value[0] for value in expected_effects.values()} | cancelled_entries, "All and only posted or cancelled source native entries required")
    positions: Counter[str] = Counter()
    turnover = 0
    lines = tables["finance_entry_lines"]
    native_line_population = _map(lines)
    require(all(line["entry_id"] in entries for line in native_line_population.values()), "Detached native journal line population")
    for identifier, (entry_id, expected_lines, expected_snapshot) in expected_effects.items():
        effect, entry = effects[identifier], entries[entry_id]
        snapshot = effect["snapshot_json"]
        require(set(snapshot) == {"schema_version", "entry", "lines"} and set(snapshot["entry"]) == HEADER_FIELDS
                and all(set(line) == LINE_FIELDS for line in snapshot["lines"]), "Exact original native snapshot shape required")
        require(effect["entry_id"] == entry_id and snapshot == expected_snapshot and sha(snapshot) == effect["validation_digest"] == entry["validation_digest"], "Native effect snapshot/entry seal differs")
        require(snapshot["schema_version"] == "finance-entry-review-v1" and entry["status"] == "Validated", "Original native posting contract/status differs")
        native_actors = (snapshot["entry"]["preparer_actor_id"], entry["validator_actor_id"], effect["posted_actor_id"])
        require(all(type(actor) is str and actor for actor in native_actors) and len(set(native_actors)) == 3, "Every actual native effect requires three distinct retained actors")
        require(all(snapshot["entry"][key] == entry.get(key) for key in snapshot["entry"] if key not in {"organization_id", "legal_entity_id"})
                and all(snapshot["entry"][key] == value for key, value in scope.items())
                and entry["organization_code"] == source["organization_code"] and entry["entity_code"] == source["entity_code"], "Native original header differs")
        policy = source["monetary_policy"]
        require(all(snapshot["entry"][key] == value for key, value in {"currency_code": source["currency_code"], "currency_precision": policy["precision"],
                     "currency_rounding_policy": policy["rounding_policy"], "currency_registry_version": policy["registry_version"],
                     "currency_registry_digest": policy["registry_digest"]}.items()), "Native original currency interpretation differs")
        native_lines = sorted((line for line in lines if line["entry_id"] == entry_id), key=lambda line: line["line_number"])
        require(len(native_lines) == len(snapshot["lines"]) and all({key: line.get(key) for key in saved if key != "dimensions"} == {key: saved[key] for key in saved if key != "dimensions"} and saved["dimensions"] == {} and line["currency_code"] == source["currency_code"] for line, saved in zip(native_lines, snapshot["lines"], strict=True)), "Native exact journal line population differs")
        require(Counter((line["account_id"], integer(line["debit_minor"]), integer(line["credit_minor"])) for line in native_lines) == Counter(expected_lines), "Independent exact financial equation differs")
        debit, credit = sum(line[1] for line in expected_lines), sum(line[2] for line in expected_lines)
        require(debit == credit > 0 and entry["total_debit_minor"] == debit == entry["total_credit_minor"], "Native double entry differs")
        turnover += debit
        for account, dr, cr in expected_lines:
            require(account in accounts, "Original account absent")
            positions[accounts[account]["account_code"]] += dr - cr
    require(positions[accounts[source["wip_account_id"]]["account_code"]] == 0, "Independent native WIP position differs")
    return {"financial_verification": "passed", "manufacturing_scope": "one-complete-actual-material-batch", "order_id": order["id"],
            "issued_material_minor": str(total), "finished_cost_minor": str(good_total), "abnormal_scrap_minor": str(scrap_total),
            "remaining_wip_minor": "0", "posting_effects": len(effects), "balanced_turnover_minor": str(turnover),
            "original_effect_ids": sorted(effects), "native_positions_minor": {key: str(value) for key, value in sorted(positions.items())},
            "performance_accepted": False, "external_attestation": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--proof", required=True, type=Path)
    parser.add_argument("--proof-sha256", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    require(re.fullmatch("[0-9a-f]{64}", args.proof_sha256) is not None, "Separately trusted raw proof SHA required")
    raw = args.proof.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == args.proof_sha256, "Original raw proof bytes differ")
    result = {**verify_proof(json.loads(raw, object_pairs_hook=unique_object)), "original_proof_sha256": args.proof_sha256}
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
