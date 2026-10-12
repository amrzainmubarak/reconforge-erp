"""Independent stdlib ME2 original material/expense/WIP/quality/FG/loss oracle over a trusted raw proof.

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


def exact_native_numbers(value: Any, key: str = "") -> None:
    """Raw PostgreSQL BIGINT/policy JSON must retain exact JSON integer types."""
    if key.endswith(("_minor", "_scaled")) or key in {"phase", "version", "line_number", "precision", "quantity_precision", "currency_precision", "minutes", "minutes_per_batch", "rate_minor_per_hour", "sequence", "operation_sequence"}:
        integer(value)
        if key in {"precision", "quantity_precision", "currency_precision"}:
            require(value <= 8, "Original exact retained policy precision required")
    elif type(value) is dict:
        for name, part in value.items():
            exact_native_numbers(part, name)
    elif type(value) is list:
        for part in value:
            exact_native_numbers(part)


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
    exact_native_numbers(proof)
    require(proof.get("schema_version") == "manufacturing-execution-proof-v2", "Unsupported manufacturing proof")
    tables, tenant = proof["populations"], proof["tenant_id"]
    require(type(tables) is dict and type(tenant) is str and bool(tenant), "Original tenant/populations required")
    for rows in tables.values():
        require(type(rows) is list and all(type(row) is dict and row.get("tenant_id") == tenant for row in rows), "Cross-tenant native source population")
    orders, boms = _map(tables["manufacturing_execution_orders"]), _map(tables["manufacturing_execution_boms"])
    require(len(orders) == len(boms) == 1, "This bounded oracle requires one complete original batch and BOM")
    order, bom = next(iter(orders.values())), next(iter(boms.values()))
    source, recipe, issue = order["payload"], bom["payload"], order["issue_plan"]
    require(integer(order["phase"]) == 3 and integer(bom["phase"]) == 1 and source["bom_version_id"] == bom["id"]
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
                and layer["legal_entity_id"] == scope["legal_entity_id"]
                and (layer["item_id"], layer["uom_id"], layer["quantity_precision"], layer["currency_code"], layer["inventory_lot_id"])
                == (row["item_id"], row["uom_id"], row["quantity_precision"], source["currency_code"], None), "Native original layer/receipt hierarchy or item/UOM/policy differs")
        value = valuation_lines[row["valuation_line_id"]]
        document, movement, line = valuations[row["valuation_document_id"]], movements[row["movement_id"]], movement_lines[row["movement_line_id"]]
        require(layer["source_valuation_line_id"] == value["id"] and value["valuation_document_id"] == document["id"]
                and document["movement_id"] == movement["id"] and line["movement_id"] == movement["id"]
                and all(document[key] == movement[key] == selected for key, selected in scope.items())
                and document["finance_entry_id"] == row["finance_entry_id"] and document["total_value_minor"] == row["total_value_minor"]
                and document["currency_code"] == source["currency_code"]
                and document["status"] == "Approved" and movement["status"] == "Posted" and movement["movement_type"] == "Receipt",
                "Native original layer valuation/movement lineage differs")
        require((value["item_id"], value["uom_id"], value["quantity_scaled"], value["quantity_precision"], value["value_minor"], value["flow_direction"], value["inventory_account_id"], value["offset_account_id"])
                == (row["item_id"], row["uom_id"], row["quantity_scaled"], row["quantity_precision"], row["total_value_minor"], "Inbound", row["inventory_account_id"], row["receipt_clearing_account_id"])
                and (line["item_id"], line["uom_id"], line["quantity_scaled"], line["from_location_id"], line["to_location_id"])
                == (row["item_id"], row["uom_id"], row["quantity_scaled"], None, row["location_id"]), "Native original receipt item/UOM/quantity/cost/location differs")

    def retain(effect_id: str, entry_id: str, lines: list[tuple[str, int, int]], snapshot: dict[str, Any]) -> None:
        require(effect_id not in expected_effects, "Native effect population reused")
        expected_effects[effect_id] = (entry_id, lines, snapshot)

    original_inputs = [row for row in receipts.values() if not row["source_number"].startswith("ME2C-")]
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
    issue_document, issue_movement = valuations[order["valuation_id"]], movements[source["movement_id"]]
    require(all(issue_document[key] == issue_movement[key] == value for key, value in scope.items())
            and issue_document["status"] == "Approved" and issue_document["movement_id"] == source["movement_id"]
            and issue_document["finance_entry_id"] == issue["entry"]["entry_id"] and issue_document["total_value_minor"] == issue["total_cost_minor"]
            and (issue_movement["status"], issue_movement["movement_type"], issue_movement["manufacturing_claim_state"], issue_movement["source_reference"])
            == ("Posted", "Delivery", "Issued", order["id"]), "Native issued movement/valuation custody differs")
    issue_values = {row["item_id"]: row for row in valuation_lines.values() if row["valuation_document_id"] == issue_document["id"]}
    issue_physical = {row["item_id"]: row for row in movement_lines.values() if row["movement_id"] == issue_movement["id"]}
    require(set(issue_values) == set(issue_physical) == set(components)
            and len(issue_values) == sum(row["valuation_document_id"] == issue_document["id"] for row in valuation_lines.values())
            and len(issue_physical) == sum(row["movement_id"] == issue_movement["id"] for row in movement_lines.values()), "Complete unique native issued component population differs")
    planned = integer(source["output_quantity_scaled"], positive=True)
    consumed_expected: Counter[tuple[str, str, int, int]] = Counter()
    layer_totals: dict[str, list[int]] = {}
    inventory_credits: dict[str, int] = {}
    total = 0
    for item, component in components.items():
        demand = Fraction(integer(component["quantity_scaled"], positive=True) * planned, integer(recipe["output_quantity_scaled"], positive=True))
        require(demand.denominator == 1, "Original base UOM expansion is fractional")
        requirement, material = requirements[item], issued[item]
        native_value, native_physical = issue_values[item], issue_physical[item]
        require((native_value["item_id"], native_value["uom_id"], native_value["quantity_scaled"], native_value["value_minor"], native_value["flow_direction"], native_value["inventory_account_id"], native_value["offset_account_id"], native_value["movement_line_id"])
                == (item, material["uom_id"], demand.numerator, material["value_minor"], "Outbound", material["inventory_account_id"], source["wip_account_id"], native_physical["id"])
                and (native_physical["item_id"], native_physical["uom_id"], native_physical["quantity_scaled"], native_physical["from_location_id"], native_physical["to_location_id"])
                == (item, material["uom_id"], demand.numerator, source["component_location_id"], None), "Native original issued item/UOM/quantity/cost/location differs")
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
            consumed_expected[(native_value["id"], identifier, taken, cost)] += 1
            layer_totals[identifier] = [taken, cost]
            quantity += taken
            value += cost
        require(quantity == demand.numerator and material["value_minor"] == value, "Whole material quantity/cost differs")
        inventory_credits[material["inventory_account_id"]] = inventory_credits.get(material["inventory_account_id"], 0) + value
        total += value
    require(integer(issue["total_cost_minor"], positive=True) == total, "Independent original WIP differs")
    consumptions = _map(tables["inventory_layer_consumptions"])
    require(all(row["workspace_id"] == scope["workspace_id"] for row in consumptions.values()), "Native material consumption workspace differs")
    observed_consumptions = Counter((row["valuation_line_id"], row["cost_layer_id"], row["quantity_scaled"], row["value_minor"]) for row in consumptions.values())
    require(observed_consumptions == consumed_expected, "Native material consumption population differs")
    for identifier in initial_layers:
        layer = layers[identifier]
        taken, value = layer_totals.get(identifier, [0, 0])
        require((layer["remaining_quantity_scaled"], layer["remaining_value_minor"]) == (layer["original_quantity_scaled"] - taken, layer["original_value_minor"] - value), "Native original residual layer differs")
    retain(order["issue_effect_id"], issue["entry"]["entry_id"], [(source["wip_account_id"], total, 0), *((account, 0, amount) for account, amount in inventory_credits.items())], issue["entry"]["snapshot"])

    require(tables["manufacturing_execution_completions"] == [], "Delegated material cannot bypass quality disposition")
    children: dict[str, dict[str, Any]] = {}
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
    v2orders = _map(tables["manufacturing_execution_v2_orders"])
    definitions = _map(tables["manufacturing_execution_v2_definitions"])
    productions = _map(tables["manufacturing_execution_v2_productions"])
    inspections = _map(tables["manufacturing_execution_v2_inspections"])
    claims = _map(tables["manufacturing_execution_v2_cost_claims"])
    guards = _map(tables["financial_effect_ownership_guards"])
    gates = _map(tables["financial_effect_claim_gates"], "source_effect_id")
    require(len(v2orders) == 1 and len(definitions) >= 2 and 1 <= len(productions) <= 200,
            "Bounded actual engineering/cost/quality source population required")
    parent = next(iter(v2orders.values()))
    body = parent["payload"]
    require(parent["phase"] in {3, 4} and parent["material_order_id"] == order["id"]
            and order["execution_owner_id"] == parent["id"] and sha(body) == parent["source_digest"]
            and body["material_source_digest"] == order["source_digest"] and body["material_order_id"] == order["id"]
            and body["id"] == parent["id"] and body["monetary_policy"] == source["monetary_policy"]
            and all(body[key] == parent[key] == selected for key, selected in scope.items()),
            "ME2 must retain the strict exact original native material and monetary source")
    route = definitions[parent["routing_id"]]
    require(route["kind"] == "Routing" and route["phase"] == 1 and route["source_digest"] == body["routing_digest"]
            and route["payload"]["bom_version_id"] == bom["id"] and route["payload"]["bom_digest"] == bom["source_digest"]
            and route["payload"]["operations"] == body["operations"]
            and route["payload"]["effective_from"] <= body["posting_date"] <= route["payload"]["effective_until"],
            "Actual effective approved engineering routing differs")
    used_definitions = {route["id"]}
    require(1 <= len(body["operations"]) <= 50, "Bounded actual routing required")
    for index, operation in enumerate(body["operations"], 1):
        center = definitions[operation["workcenter_id"]]
        used_definitions.add(center["id"])
        require(operation["sequence"] == index and integer(operation["minutes_per_batch"], positive=True) > 0
                and center["kind"] == "Workcenter" and center["phase"] == 1
                and center["source_digest"] == operation["workcenter_digest"]
                and center["payload"]["effective_from"] <= route["payload"]["effective_from"]
                and center["payload"]["effective_until"] >= route["payload"]["effective_until"], "Original ordered effective workcenter differs")
    require(set(definitions) == used_definitions, "Unexpected engineering definition population")
    for row in definitions.values():
        require(sha(row["payload"]) == row["source_digest"] and row["payload"]["id"] == row["id"]
                and all(row[key] == row["payload"][key] == selected for key, selected in scope.items())
                and row["reviewer_id"] != row["creator_id"] and row["version"] == row["payload"]["version"],
                "Approved definition seal/identity/scope differs")
    require(tables["manufacturing_execution_v2_cost_releases"] == tables["financial_effect_ownership_releases"] == [],
            "This bounded posted-batch oracle requires no detached released claims")
    require(1 <= len(claims) == len(body["claims"]) <= 100 and set(guards) == set(claims), "Complete original cost claim/directory population differs")
    extra, expected_cost_lines = 0, []
    original_expenses: set[str] = set()
    claim_keys: set[tuple[str, str]] = set()
    for claim in claims.values():
        value, guard = claim["payload"], guards[claim["id"]]
        require(claim["order_id"] == parent["id"] and claim["state"] == "Consumed" and value in body["claims"]
                and claim["effect_id"] == value["effect_id"] and claim["line_id"] == value["line_id"]
                and guard["owner_namespace"] == "ME2" and guard["owner_claim_id"] == claim["id"]
                and guard["source_effect_id"] == value["effect_id"] and all(claim[key] == guard[key] == selected for key, selected in scope.items()),
                "Original expense ownership claim/directory identity or scope differs")
        key = (value["effect_id"], value["line_id"])
        require(key not in claim_keys, "Duplicate original expense claim")
        claim_keys.add(key)
        require(value["kind"] in {"Labor", "Overhead"} and integer(value["operation_sequence"], positive=True) <= len(body["operations"]),
                "Claim must refer to an actual ordered engineering operation")
        amount = even(Fraction(integer(value["minutes"], positive=True) * integer(value["rate_minor_per_hour"], positive=True), 60))
        original_effect, native_line = effects[value["effect_id"]], next(line for line in tables["finance_entry_lines"] if line["id"] == value["line_id"])
        original_header = entries[original_effect["entry_id"]]
        original_line = next(line for line in original_effect["snapshot_json"]["lines"] if line["line_number"] == native_line["line_number"])
        require(original_line == value["original_line"] and original_header["source_type"] == original_effect["source_kind"] == "Manual"
                and original_effect["reverses_effect_id"] is None and original_header["reverses_posting_id"] is None
                and original_header["posting_date"] <= body["posting_date"]
                and original_effect["entry_id"] == value["effect_entry_id"] == native_line["entry_id"]
                and original_effect["validation_digest"] == value["effect_validation_digest"]
                and accounts[original_line["account_id"]]["account_type"] == "Expense"
                and original_line["account_id"] == value["account_id"] == native_line["account_id"]
                and original_line["debit_minor"] == value["original_debit_minor"] and original_line["credit_minor"] == 0
                and original_line["dimensions"] == value["dimensions"] == {}
                and integer(amount, positive=True) == claim["amount_minor"] == value["amount_minor"] <= original_line["debit_minor"],
                "Independent exact rate/time capacity or original posted expense source differs")
        extra += amount
        expected_cost_lines.extend([(source["wip_account_id"], amount, 0), (value["account_id"], 0, amount)])
        if original_effect["id"] not in original_expenses:
            retain(original_effect["id"], original_effect["entry_id"], [(line["account_id"], line["debit_minor"], line["credit_minor"])
                for line in original_effect["snapshot_json"]["lines"]], original_effect["snapshot_json"])
            original_expenses.add(original_effect["id"])
        require(value["effect_id"] in gates and integer(gates[value["effect_id"]]["version"], positive=True) > 0
                and all(gates[value["effect_id"]][key] == selected for key, selected in scope.items()), "Original source coordination custody differs")
    require(set(gates) == original_expenses, "Unexpected source coordination population")
    total_cost = integer(total + extra, positive=True)
    require(parent["total_cost_minor"] == total_cost, "Original material plus claimed expense cost pool differs")
    retain(parent["cost_effect_id"], parent["cost_entry"]["entry_id"], expected_cost_lines, parent["cost_entry"]["snapshot"])
    require(all(row["order_id"] == row["payload"]["order_id"] == parent["id"] and row["production_id"] == row["payload"]["production_id"]
                and row["production_id"] in productions and row["phase"] in {0, 1, 2, 3} for row in inspections.values()), "Detached or invalid quality inspection source")
    v2_rows = {**definitions, **v2orders, **productions, **inspections}
    require(len(v2_rows) == len(definitions) + len(v2orders) + len(productions) + len(inspections), "Cross-table owner identity shadowing")
    commands = {(row["object_id"], row["operation"]): row for row in tables["manufacturing_execution_v2_commands"]}
    events = {(row["object_id"], row["operation"]): row for row in tables["manufacturing_execution_v2_events"]}
    require(len(commands) == len(tables["manufacturing_execution_v2_commands"]) == len(events) == len(tables["manufacturing_execution_v2_events"]),
            "Exact ME2 command/event bijection required")
    audits, outbox = _map(tables["domain_audit_events"]), _map(tables["outbox_events"], "event_id")
    expected_keys: set[tuple[str, str]] = set()
    def projection(row: dict[str, Any], operation: str) -> dict[str, Any]:
        identifier = row["id"]
        result = {**row["payload"], **{key: value for key, value in row.items() if key not in {"tenant_id", "payload", "created_at"}}}
        definition = identifier in definitions
        production = identifier in productions
        phases = {"create": 0, "approve": 1} if definition else {"create": 0, "review": 1, "post": 2, "cancel": 4 if production else 3} if identifier != parent["id"] else {"create": 0, "prepare": 1, "review": 2, "post": 3}
        result["phase"] = phases[operation]
        if identifier == parent["id"]:
            result.update(produced_quantity_scaled=0, produced_cost_minor=0, disposed_quantity_scaled=0, released_cost_minor=0)
            if operation == "create":
                result.update(cost_entry=None, total_cost_minor=0)
            if operation != "post":
                result["cost_effect_id"] = None
        if operation in {"create", "prepare"}:
            result["reviewer_id"] = None
        if identifier in inspections and operation != "post":
            result.update(receipt_effect=None, loss_effect_id=None)
        return result
    for identifier, row in v2_rows.items():
        require(row["payload"]["id"] == identifier and sha(row["payload"]) == row["source_digest"] and all(row[key] == selected for key, selected in scope.items()),
                "Original owner source seal or hierarchy differs")
        operations = {"create", "approve"} if identifier in definitions else {"create", "prepare", "review", "post"} if identifier == parent["id"] else {"create"}
        if identifier not in definitions and identifier != parent["id"]:
            if row["reviewer_id"] is not None:
                operations.add("review")
            if identifier in productions and row["phase"] in {2, 3} or identifier in inspections and row["phase"] == 2:
                operations.add("post")
            if identifier in productions and row["phase"] == 4 or identifier in inspections and row["phase"] == 3:
                operations.add("cancel")
        expected_keys.update((identifier, operation) for operation in operations)
        for operation in operations:
            command, event = commands[(identifier, operation)], events[(identifier, operation)]
            request = row["payload"]["command_request"] if operation == "create" else {"id": identifier, "expected_digest": row["source_digest"], "reason": event["reason"]}
            ack = projection(row, operation)
            metadata = {"source_digest": row["source_digest"], "phase": ack["phase"], "reason": event["reason"]}
            audit, message = audits[event["audit_event_id"]], outbox[event["outbox_event_id"]]
            request_reason = request["material"]["reason"] if operation == "create" and identifier == parent["id"] else request["reason"]
            require(command["request_json"] == {"operation": operation, "actor_id": command["actor_id"], "request": request}
                    and sha(command["request_json"]) == command["request_digest"] and command["response_json"] == ack
                    and event["actor_id"] == command["actor_id"] == audit["actor_user_id"] and request_reason == event["reason"]
                    and command["workspace_id"] == scope["workspace_id"] and event["metadata"] == audit["metadata_json"] == metadata
                    and audit["object_type"] == message["aggregate_type"] == "manufacturing_execution_v2"
                    and audit["object_id"] == message["aggregate_id"] == identifier
                    and audit["action"] == message["event_type"] == "manufacturing_execution_v2." + operation
                    and message["payload"] == {**metadata, "audit_event_id": audit["id"]}
                    and all(message[key] == selected for key, selected in scope.items()), "Exact historical request/ACK/audit/outbox differs")
    require(set(commands) == set(events) == expected_keys, "Orphan or missing source lifecycle evidence")
    for identifier in {parent["id"], *productions, *inspections}:
        if (identifier, "post") in commands:
            first = "prepare" if identifier == parent["id"] else "create"
            require(len({commands[(identifier, operation)]["actor_id"] for operation in (first, "review", "post")}) == 3,
                    "Actual costing, held production and quality disposition require three different humans")
    produced = produced_cost = disposed = released = good_total = scrap_total = good_quantity = scrap_quantity = 0
    output_layers: set[str] = set()
    expected_receipts = set(row["id"] for row in original_inputs)
    expected_links = set(expected_receipts)
    cancelled_entries: set[str] = set()
    for held in sorted(productions.values(), key=lambda row: (row["payload"]["produced_before_scaled"], row["id"])):
        part = held["payload"]
        require(held["order_id"] == part["order_id"] == parent["id"] and part["order_digest"] == parent["source_digest"]
                and part["routing_digest"] == body["routing_digest"] and part["cost_effect_id"] == parent["cost_effect_id"]
                and [row["sequence"] for row in part["operations"]] == list(range(1, len(body["operations"]) + 1))
                and all(integer(row["minutes"], positive=True) and type(row["evidence_reference"]) is str and row["evidence_reference"] for row in part["operations"]),
                "Production needs exact original ordered engineering execution")
        if held["phase"] == 4:
            require(not any(row["production_id"] == held["id"] for row in inspections.values()), "Cancelled hold cannot be inspected")
            continue
        require(held["phase"] in {2, 3}, "This proof requires posted held/inspected production")
        q = integer(part["quantity_scaled"], positive=True)
        amount = total_cost - produced_cost if q == planned - produced else even(Fraction((total_cost - produced_cost) * q, planned - produced))
        require(q <= planned - produced and (part["produced_before_scaled"], part["produced_cost_before_minor"], part["held_cost_minor"])
                == (produced, produced_cost, amount), "Independent cumulative held quantity/cost differs")
        produced += q
        produced_cost += amount
        posted_inspections = [row for row in inspections.values() if row["production_id"] == held["id"] and row["phase"] == 2]
        require(len(posted_inspections) == int(held["phase"] == 3), "No stock or double disposition before one complete inspection")
        for decision in [row for row in inspections.values() if row["production_id"] == held["id"]]:
            choice = decision["payload"]
            require(decision["order_id"] == parent["id"] and choice["production_digest"] == held["source_digest"]
                    and choice["order_digest"] == parent["source_digest"] and choice["accepted_quantity_scaled"] + choice["rejected_quantity_scaled"] == q,
                    "Inspection must exactly dispose its complete original quality hold")
            accepted = even(Fraction(amount * choice["accepted_quantity_scaled"], q))
            rejected = amount - accepted
            require((choice["accepted_cost_minor"], choice["rejected_cost_minor"], choice["released_cost_minor"])
                    == (accepted, rejected, amount), "Independent exact acceptance/rejection cost differs")
            if choice["receipt_plan"]:
                expected_receipts.add(choice["receipt_plan"]["plan_id"])
            if decision["phase"] != 2:
                require(decision["receipt_effect"] is None and decision["loss_effect_id"] is None, "Unposted inspection leaked effect")
                if choice["receipt_plan"]:
                    native_plan = choice["receipt_plan"]
                    require(native_plan["plan_id"] not in links and native_plan["artifacts"]["posting_effect_id"] not in effects
                            and native_plan["artifacts"]["finance_entry_id"] not in entries,
                            "Unposted FG retains its plan/review without materializing a native GL header or saleable stock")
                if choice["loss_entry"]:
                    cancelled_entries.add(choice["loss_entry"]["entry_id"])
                    require(entries[choice["loss_entry"]["entry_id"]]["status"] == ("Voided" if decision["phase"] == 3 else "Draft" if decision["phase"] == 0 else "Validated"), "Unposted loss draft status differs")
                continue
            disposed += q
            released += amount
            good_total += accepted
            scrap_total += rejected
            good_quantity += choice["accepted_quantity_scaled"]
            scrap_quantity += choice["rejected_quantity_scaled"]
            actual_poster = commands[(decision["id"], "post")]["actor_id"]
            if accepted:
                native_plan, output = choice["receipt_plan"], decision["receipt_effect"]
                native = receipts[native_plan["plan_id"]]
                layer = layers[native["cost_layer_id"]]
                verify_receipt_layer(native, layer)
                require(native["source_number"] == decision["id"] and native["plan_json"] == native_plan
                        and native["item_id"] == source["output_item_id"] and native["location_id"] == source["finished_location_id"]
                        and (native["quantity_scaled"], native["total_value_minor"], layer["original_quantity_scaled"], layer["remaining_quantity_scaled"], layer["original_value_minor"], layer["remaining_value_minor"])
                        == (choice["accepted_quantity_scaled"], accepted, choice["accepted_quantity_scaled"], choice["accepted_quantity_scaled"], accepted, accepted)
                        and native["receipt_clearing_account_id"] == source["wip_account_id"]
                        and links[native["id"]]["posting_effect_id"] == output["effect_id"] == native["posting_effect_id"]
                        and output["posted_actor_id"] == actual_poster and sha({key: value for key, value in output.items() if key != "effect_digest"}) == output["effect_digest"],
                        "Only inspected accepted units may own exact original native saleable FG custody")
                output_layers.add(layer["id"])
                expected_links.add(native["id"])
                retain(output["effect_id"], native["finance_entry_id"], [(native["inventory_account_id"], accepted, 0), (source["wip_account_id"], 0, accepted)], native_plan["finance_snapshot"])
            else:
                require(choice["receipt_plan"] is None and decision["receipt_effect"] is None, "Zero accepted units cannot create native receipt")
            if rejected:
                retain(decision["loss_effect_id"], choice["loss_entry"]["entry_id"], [(source["scrap_account_id"], rejected, 0), (source["wip_account_id"], 0, rejected)], choice["loss_entry"]["snapshot"])
                require(effects[decision["loss_effect_id"]]["posted_actor_id"] == actual_poster, "Abnormal loss requires actual third human")
            else:
                require(choice["loss_entry"] is None and decision["loss_effect_id"] is None, "Zero rejected units cannot invent loss")
    require(set(receipts) == expected_receipts and set(links) == expected_links and set(layers) == initial_layers | output_layers,
            "Unexpected detached native stock/receipt population")
    require((parent["produced_quantity_scaled"], parent["produced_cost_minor"], parent["disposed_quantity_scaled"], parent["released_cost_minor"])
            == (produced, produced_cost, disposed, released) and produced <= planned and disposed <= produced
            and total_cost == good_total + scrap_total + total_cost - released
            and (parent["phase"] == 4) == (disposed == planned), "Complete source quality/WIP counters differ")
    require(set(effects) == set(expected_effects), "Native effect population is incomplete or has detached extra effects")
    expected_entries = {value[0] for value in expected_effects.values()} | cancelled_entries
    require(set(entries) == expected_entries, "Native entry population is incomplete or detached")
    lines = tables["finance_entry_lines"]
    native_line_population = _map(lines)
    positions: Counter[str] = Counter()
    turnover = 0
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

    require(positions[accounts[source["wip_account_id"]]["account_code"]] == total_cost - released, "Independent native remaining WIP differs")
    return {"financial_verification": "passed", "manufacturing_scope": "one-original-expense-backed-material-batch-with-posted-quality-holds",
            "order_id": parent["id"], "issued_material_minor": str(total), "claimed_expense_minor": str(extra), "total_cost_minor": str(total_cost),
            "finished_quantity_scaled": str(good_quantity), "finished_cost_minor": str(good_total), "abnormal_loss_quantity_scaled": str(scrap_quantity),
            "abnormal_loss_minor": str(scrap_total), "remaining_wip_minor": str(total_cost - released),
            "held_quantity_scaled": str(produced - disposed), "held_cost_minor": str(produced_cost - released),
            "posting_effects": len(effects), "balanced_turnover_minor": str(turnover), "original_effect_ids": sorted(effects),
            "native_positions_minor": {key: str(value) for key, value in sorted(positions.items())},
            "performance_accepted": False, "external_attestation": False}

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--proof", required=True, type=Path)
    parser.add_argument("--proof-sha256", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    require(re.fullmatch("[0-9a-f]{64}", args.proof_sha256) is not None, "Separately trusted raw proof SHA required")
    require(args.proof.is_file() and args.proof.stat().st_size <= 32 * 1024 * 1024, "Bounded original proof file required")
    require(not args.output.exists() and args.output.resolve() != args.proof.resolve(), "Oracle output must preserve every original existing artifact")
    raw = args.proof.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == args.proof_sha256, "Original raw proof bytes differ")
    result = {**verify_proof(json.loads(raw, object_pairs_hook=unique_object)), "original_proof_sha256": args.proof_sha256}
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
