"""Independent stdlib oracle over original IT1/IRP/native FIFO/GL populations.

Run with python -I [and -O] FILE ORIGINAL.json --expected-export-sha256 SHA. No application, accounting or
inventory engine is imported; all quantities and conservation use integers or
Fraction and every refusal uses an explicit exception rather than assert.
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

MAX = 9_000_000_000_000_000_000
MAX_BYTES = 16_777_216
OUTBOX_IMMUTABLE = ("tenant_id", "event_id", "event_type", "aggregate_type", "aggregate_id", "workspace_id", "organization_id", "legal_entity_id", "payload", "created_at")


def require(value: bool, message: str) -> None:
    if value is not True:
        raise ValueError(message)


def integer(value: Any, positive: bool = False) -> int:
    require(type(value) is int or isinstance(value, str) and re.fullmatch(r"0|[1-9][0-9]{0,18}", value) is not None,
        "Original values must be exact bounded integer tokens or canonical integer text")
    selected = int(value)
    require((1 if positive else 0) <= selected <= MAX, "Original value is outside exact supported bounds")
    return selected


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def indexed(rows: Any, key: str = "id") -> dict[str, dict[str, Any]]:
    require(isinstance(rows, list) and len(rows) <= 20000, "Original population must be finite")
    result = {}
    for row in rows:
        require(isinstance(row, dict) and isinstance(row.get(key), str) and row[key] not in result,
            "Original population has duplicate or missing identities")
        result[row[key]] = row
    return result


def unique_members(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        require(key not in result, "Duplicate original JSON member is forbidden")
        result[key] = value
    return result


def forbidden_number(_: str) -> Any:
    raise ValueError("Floating or nonfinite original financial input is forbidden")


def read_original(path: Path, expected_sha256: str) -> tuple[dict[str, Any], str]:
    require(re.fullmatch(r"[a-f0-9]{64}", expected_sha256) is not None, "Trusted exact original SHA-256 is required")
    with path.open("rb") as original:
        raw = original.read(MAX_BYTES + 1)
    require(len(raw) <= MAX_BYTES, "Original transfer proof exceeds the finite byte budget")
    digest = hashlib.sha256(raw).hexdigest()
    require(digest == expected_sha256, "Original bytes differ from the separately trusted export SHA-256")
    proof = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_members, parse_float=forbidden_number, parse_constant=forbidden_number)
    require(isinstance(proof, dict), "Original proof must be one object")
    return proof, digest


def immutable_outbox(row: dict[str, Any]) -> dict[str, Any]:
    return {key: row[key] for key in OUTBOX_IMMUTABLE}


def native_original(snapshot: dict[str, Any], tables: dict[str, Any], *, historical: bool = False, receipt: bool = False) -> None:
    movements = indexed(tables["inventory_movements"])
    audits = indexed(tables["domain_audit_events"])
    outbox = indexed(tables["outbox_events"], "event_id")
    head = snapshot["head"]
    current = movements[head["id"]]
    if historical:
        changing = {"status", "row_version", "posted_by", "posted_at", "updated_at", "post_reason"}
        require({key: part for key, part in head.items() if key not in changing} == {key: part for key, part in current.items() if key not in changing}
            and head["status"] == "Draft" and head["row_version"] == 1, "Retained native creation head differs")
    else:
        require(head == current, "Original native posted head differs")
    lines = sorted([row for row in tables["inventory_movement_lines"] if row["movement_id"] == head["id"]], key=lambda row: (row["line_number"], row["id"]))
    require(snapshot["lines"] == lines and len(lines) == 1, "Complete original native line membership differs")
    related_audits = sorted([row for row in tables["domain_audit_events"] if row["object_type"] == "inventory_movement" and row["object_id"] == head["id"]], key=lambda row: (row["sequence"], row["id"]))
    related_outbox = sorted([row for row in tables["outbox_events"] if row["aggregate_type"] == "inventory_movement" and row["aggregate_id"] == head["id"]], key=lambda row: row["event_id"])
    require(len(snapshot["audit"]) == len(snapshot["outbox"]) == (0 if receipt else 1 if historical else 2), "Complete native audit/outbox cardinality differs")
    require(all(row == audits[row["id"]] and row["object_type"] == "inventory_movement" and row["object_id"] == head["id"] for row in snapshot["audit"]), "Native audit original membership differs")
    require(all(immutable_outbox(row) == immutable_outbox(outbox[row["event_id"]]) and row["aggregate_type"] == "inventory_movement"
        and row["aggregate_id"] == head["id"] and all(row[key] == head[key] for key in ("tenant_id", "workspace_id", "organization_id", "legal_entity_id")) for row in snapshot["outbox"]), "Native scoped immutable outbox membership differs")
    require(snapshot["audit"] == (related_audits[:1] if historical else related_audits), "Native audit population was omitted or added")
    expected_outbox = [row for row in related_outbox if not historical or row["event_type"] == "inventory_movement_draft_saved"]
    require([immutable_outbox(row) for row in snapshot["outbox"]] == [immutable_outbox(row) for row in expected_outbox], "Native immutable outbox population was omitted or added")
    for audit in snapshot["audit"]:
        matches = [row for row in snapshot["outbox"] if row["event_type"] == audit["action"]]
        require(len(matches) == 1 and matches[0]["payload"] == audit["metadata_json"], "Native audit and immutable event payload differ")


def audit_chain(tables: dict[str, Any]) -> None:
    previous = "0" * 64
    rows = sorted(indexed(tables["domain_audit_events"]).values(), key=lambda row: row["sequence"])
    for sequence, row in enumerate(rows, 1):
        require(row["sequence"] == sequence and row["previous_hash"] == previous, "Original audit chain membership/order differs")
        payload = {key: row[key] for key in ("action", "actor_label", "actor_user_id", "after_hash", "before_hash", "created_at", "id", "object_id", "object_type", "previous_hash", "sequence")}
        payload["metadata_json"] = json.dumps(row["metadata_json"], ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        original_hash = hashlib.sha256(json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        require(original_hash == row["event_hash"], "Immutable original audit hash differs")
        previous = original_hash


def original_cost(cost: dict[str, Any], tables: dict[str, Any], scope: dict[str, str], item: str) -> tuple[int, int]:
    require(cost["schema_version"] == "inventory-transfer-cost-v1" and 1 <= len(cost["sources"]) <= 32, "Complete bounded cost originals required")
    layers = indexed(tables["inventory_cost_layers"])
    receipts = indexed(tables["inventory_receipt_plans"])
    links = indexed(tables["inventory_receipt_links"], "plan_id")
    valuations = indexed(tables["inventory_valuation_documents"])
    valuation_lines = indexed(tables["inventory_valuation_lines"])
    inputs = indexed(tables["inventory_valuation_input_costs"])
    entries = indexed(tables["finance_entries"])
    effects = indexed(tables["finance_posting_effects"])
    reviews = indexed(tables["inventory_receipt_reviews"])
    consumed = indexed(tables["inventory_layer_consumptions"])
    seen = set()
    quantity, value = 0, 0
    for source in cost["sources"]:
        layer = source["layer"]
        require(layer["id"] not in seen and layer["id"] in layers and layer["item_id"] == item, "Cited original layer identity differs")
        seen.add(layer["id"])
        current = layers[layer["id"]]
        changing = {"remaining_quantity_scaled", "remaining_value_minor", "row_version"}
        require({key: part for key, part in layer.items() if key not in changing} == {key: part for key, part in current.items() if key not in changing},
            "Original FIFO cost ownership was changed")
        receipt = source["receipt_plan"]
        plan = receipts[receipt["plan_id"]]
        require(plan["operation"] == receipt["operation"] == "Receipt" and receipt == plan["plan_json"]
            and all(receipt["scope"][key] == expected for key, expected in scope.items()), "Cited receipt source/scope differs")
        require(sha({key: part for key, part in receipt.items() if key not in {"plan_digest", "preparation_audit_event_id", "preparation_outbox_event_id"}}) == receipt["plan_digest"] == plan["plan_digest"], "Original receipt plan seal differs")
        review = source["receipt_review"]
        reviewed = reviews[review["review_id"]]
        require(review == reviewed["review_json"] and review["plan_id"] == receipt["plan_id"] and review["plan_digest"] == receipt["plan_digest"]
            and sha({key: part for key, part in review.items() if key not in {"review_digest", "audit_event_id", "outbox_event_id"}}) == review["review_digest"] == reviewed["review_digest"], "Original independent receipt review seal differs")
        actors = [receipt["preparer"]["user_id"], review["reviewer"]["user_id"], source["receipt_link"]["posted_actor_id"]]
        require(len(set(actors)) == 3 and source["receipt_link"]["review_digest"] == review["review_digest"], "Original receipt requires three exact independent actors")
        native_original(source["receipt_native"], tables, receipt=True)
        require(source["receipt_native"]["head"]["id"] == receipt["artifacts"]["movement_id"] == plan["movement_id"]
            and source["receipt_native"]["lines"][0]["id"] == plan["movement_line_id"]
            and source["receipt_native"]["lines"][0]["to_location_id"] == receipt["source"]["location_id"], "Original receipt physical source differs")
        audit_rows = indexed(tables["domain_audit_events"])
        event_rows = indexed(tables["outbox_events"], "event_id")
        ids = ((receipt["preparation_audit_event_id"], receipt["preparation_outbox_event_id"], "inventory_receipt_prepared", actors[0]),
            (review["audit_event_id"], review["outbox_event_id"], "inventory_receipt_reviewed", actors[1]),
            (source["receipt_link"]["audit_event_id"], source["receipt_link"]["outbox_event_id"], "inventory_receipt_committed", actors[2]))
        metadata = {"plan_digest": receipt["plan_digest"], "finance_validation_digest": receipt["finance_validation_digest"]}
        for audit_id, event_id, action, actor_id in ids:
            if action != "inventory_receipt_prepared":
                metadata = {**metadata, "review_digest": review["review_digest"]}
            if action == "inventory_receipt_committed":
                metadata = {**metadata, "effect_id": source["receipt_link"]["posting_effect_id"]}
            audit, event = audit_rows[audit_id], event_rows[event_id]
            require(audit["object_type"] == event["aggregate_type"] == "inventory_receipt_posting" and audit["object_id"] == event["aggregate_id"] == receipt["plan_id"]
                and audit["actor_user_id"] == actor_id and audit["action"] == event["event_type"] == action
                and audit["metadata_json"] == metadata and event["payload"] == {**metadata, "audit_event_id": audit_id}
                and all(event[key] == expected for key, expected in scope.items()), "Original receipt audit and scoped immutable event differ")
        require({audit_id for audit_id, _, _, _ in ids} == {audit["id"] for audit in audit_rows.values() if audit["object_type"] == "inventory_receipt_posting" and audit["object_id"] == receipt["plan_id"]}
            and {event_id for _, event_id, _, _ in ids} == {event["event_id"] for event in event_rows.values() if event["aggregate_type"] == "inventory_receipt_posting" and event["aggregate_id"] == receipt["plan_id"]}, "Original receipt owner evidence population differs")
        require(source["receipt_link"] == links[plan["id"]] and source["valuation_document"] == valuations[plan["valuation_document_id"]]
            and source["valuation_line"] == valuation_lines[plan["valuation_line_id"]] and source["valuation_input"] == inputs[plan["input_cost_id"]],
            "Approved cost/receipt/input source membership differs")
        require(source["valuation_document"]["status"] == "Approved" and source["valuation_line"]["flow_direction"] == "Inbound",
            "Approved original inbound valuation required")
        require(source["finance_entry"] == entries[plan["finance_entry_id"]] and source["posting_effect"] == effects[plan["posting_effect_id"]]
            and source["finance_entry"]["status"] == "Validated" and source["posting_effect"]["source_kind"] == "InventoryReceipt"
            and source["posting_effect"]["source_id"] == plan["id"], "Original posted GL membership differs")
        lines = [line for line in tables["finance_entry_lines"] if line["entry_id"] == plan["finance_entry_id"]]
        require(sorted(lines, key=lambda row: (row["line_number"], row["id"])) == source["finance_lines"] and len(lines) == 2,
            "Complete original GL lines differ")
        total = integer(layer["original_value_minor"], True)
        require(total == integer(plan["total_value_minor"], True) == integer(source["valuation_line"]["value_minor"], True)
            == integer(source["valuation_input"]["total_cost_minor"], True) == sum(integer(line["debit_minor"]) for line in lines)
            == sum(integer(line["credit_minor"]) for line in lines), "Original approved cost/GL conservation differs")
        amounts = [layer["original_value_minor"], layer["remaining_value_minor"], source["valuation_document"]["total_value_minor"], source["valuation_line"]["value_minor"],
            plan["total_value_minor"], source["finance_entry"]["total_debit_minor"], source["finance_entry"]["total_credit_minor"],
            *[line["debit_minor"] for line in lines], *[line["credit_minor"] for line in lines]]
        require(source["exposed_amounts_minor"] == amounts, "Complete exposed original financial values differ")
        require(receipt["currency_policy"] == cost["monetary_policy"] and integer(cost["monetary_policy"]["currency_precision"]) <= 8,
            "Exact original captured currency policy required")
        require(all(source["finance_entry"][key] == policy for key, policy in cost["monetary_policy"].items()), "Original GL captured currency policy differs")
        histories = source["consumptions"]
        require(len({row["id"] for row in histories}) == len(histories) <= 200 and all(row == consumed[row["id"]] and row["cost_layer_id"] == layer["id"] for row in histories),
            "Historical consumption bytes/membership differ")
        residual_q = integer(layer["original_quantity_scaled"], True) - sum(integer(row["quantity_scaled"], True) for row in histories)
        residual_v = total - sum(integer(row["value_minor"], True) for row in histories)
        require(residual_q == integer(layer["remaining_quantity_scaled"]) and residual_v == integer(layer["remaining_value_minor"]),
            "Independent original residual cost/quantity differs")
        quantity += residual_q
        value += residual_v
    require(quantity == integer(cost["remaining_quantity_scaled"], True) and value == integer(cost["remaining_value_minor"], True),
        "Complete original pool totals differ")
    return quantity, value


def verify(proof: dict[str, Any]) -> dict[str, Any]:
    require(proof["schema_version"] == "inventory-transfer-proof-v1" and proof["capture"]["role_superuser"] is False
        and proof["capture"]["role_bypassrls"] is False, "Original capture must use the ordinary tenant role")
    require(all(re.fullmatch(r"[a-f0-9]{64}", digest) for digest in proof["capture"]["source_files_sha256"].values()), "Source-qualified capture digests required")
    tables = proof["populations"]
    for rows in tables.values():
        require(isinstance(rows, list) and all(row["tenant_id"] == proof["tenant_id"] for row in rows), "Cross-tenant original population")
    audit_chain(tables)
    sources = indexed(tables["inventory_transfer_sources"])
    require(len(sources) == 2, "One forward source and one independent complete inverse required")
    forward = next((row for row in sources.values() if row["original_transfer_id"] is None), None)
    require(forward is not None, "Original forward source is missing")
    child = next((row for row in sources.values() if row["original_transfer_id"] == forward["id"]), None)
    require(child is not None and all(type(row["phase"]) is int and row["phase"] == 2 and type(row["row_version"]) is int and row["row_version"] == 3 for row in sources.values()), "Two original Posted source histories required")
    scope = {key: forward[key] for key in ("workspace_id", "organization_id", "legal_entity_id")}
    require(all(child[key] == expected for key, expected in scope.items()) and child["item_id"] == forward["item_id"]
        and child["quantity_scaled"] == forward["quantity_scaled"] and child["from_location_id"] == forward["to_location_id"]
        and child["to_location_id"] == forward["from_location_id"], "Inverse source must swap exact original custody")
    movements = indexed(tables["inventory_movements"])
    native_lines_all = indexed(tables["inventory_movement_lines"])
    require(len(native_lines_all) == len(movements) == 3 and all(line["movement_id"] in movements for line in native_lines_all.values()), "Detached or extra original native movement line")
    audits = indexed(tables["domain_audit_events"])
    outbox = indexed(tables["outbox_events"], "event_id")
    require(all(row["aggregate_id"] in movements for row in outbox.values() if row["aggregate_type"] == "inventory_movement"), "Detached native movement outbox")
    require(all(row["object_id"] in movements for row in audits.values() if row["object_type"] == "inventory_movement"), "Detached native movement audit")
    claims = indexed(tables["inventory_transfer_claims"])
    releases = indexed(tables["inventory_transfer_releases"], "claim_id")
    guards = indexed(tables["inventory_quantity_source_guards"])
    core_releases = indexed(tables["inventory_quantity_source_releases"], "guard_id")
    require(len(claims) == 2 and set(claims) == set(releases) == set(guards) == set(core_releases), "Original bijective quantity custody differs")
    require(len(tables["inventory_transfer_events"]) == len(tables["inventory_transfer_commands"]) == 6, "Complete six original human commands required")
    require(len({(row["tenant_id"], row["workspace_id"], row["command_id"]) for row in tables["inventory_transfer_commands"]}) == 6,
        "Original scoped command identity population contains duplicates")
    for row in (forward, child):
        payload = row["payload"]
        require(sha(payload) == row["source_digest"] and payload["id"] == row["id"] and payload["scope"] == scope, "Original source seal/scope differs")
        require(all(payload[key] == row[key] for key in ("item_id", "uom_id", "quantity_precision", "quantity_scaled", "from_location_id", "to_location_id", "native_movement_id", "creator_actor_id", "number", "period_id")), "Retained source scalar identity differs")
        scaled = Fraction(payload["quantity"]) * 10 ** integer(row["quantity_precision"])
        require(scaled.denominator == 1 and scaled == integer(row["quantity_scaled"], True), "Original exact native UOM scaling differs")
        original_cost(payload["cost_snapshot"], tables, scope, row["item_id"])
        _, value = original_cost(row["review_cost_json"], tables, scope, row["item_id"])
        require(sha(row["review_cost_json"]) == row["review_cost_digest"] and value == integer(payload["cost_snapshot"]["remaining_value_minor"]),
            "Original reviewed complete cost bytes differ")
        native = movements[row["native_movement_id"]]
        native_original(row["posted_native_json"], tables)
        native_original(row["native_creation_json"], tables, historical=True)
        require(native == row["posted_native_json"]["head"] and native["status"] == "Posted" and native["movement_type"] == "Transfer"
            and native["source_type"] == "Generated" and native["source_reference"] == row["id"]
            and native["created_by"] == row["creator_actor_id"] and native["posted_by"] == row["poster_actor_id"], "Original native transfer identity differs")
        require(all(native[key] == expected for key, expected in scope.items()) and native["period_id"] == row["period_id"]
            and native["movement_date"] == row["posting_date"] and native["row_version"] == 2, "Original native scope/date/period/version differs")
        native_lines = [line for line in tables["inventory_movement_lines"] if line["movement_id"] == native["id"]]
        require(len(native_lines) == 1 and native_lines == row["posted_native_json"]["lines"] == row["native_creation_json"]["lines"],
            "Original transfer native line was changed")
        line = native_lines[0]
        require(all(line[key] == row[key] for key in ("item_id", "uom_id", "quantity_precision", "quantity_scaled", "from_location_id", "to_location_id"))
            and line["inventory_lot_id"] is None, "Original transfer quantity/location differs")
        claim = next((claim for claim in claims.values() if claim["transfer_id"] == row["id"]), None)
        require(claim is not None and claim["state"] == "Posted" and claim["quantity_scaled"] == row["quantity_scaled"]
            and claim["location_id"] == row["from_location_id"] and all(claim[key] == expected for key, expected in scope.items()), "Posted original claim differs")
        guard, release, core = guards[claim["id"]], releases[claim["id"]], core_releases[claim["id"]]
        require(guard["owner_namespace"] == core["owner_namespace"] == "IT1" and guard["owner_claim_id"] == claim["id"]
            and all(guard[key] == claim[key] for key in ("workspace_id", "organization_id", "legal_entity_id", "item_id", "uom_id", "quantity_precision", "location_id", "quantity_scaled")), "Shared original guard differs")
        require(core["release_id"] == release["id"] and release["purpose"] == "Post" and release["target_movement_id"] == native["id"]
            and release["actor_id"] == row["poster_actor_id"] and release["created_version"] == 3 and release["transfer_id"] == row["id"]
            and claim["created_version"] == 2 and all(release[key] == expected for key, expected in scope.items()), "Original terminal native release differs")
        events = sorted([event for event in tables["inventory_transfer_events"] if event["transfer_id"] == row["id"]], key=lambda event: event["version"])
        commands = sorted([command for command in tables["inventory_transfer_commands"] if command["transfer_id"] == row["id"]], key=lambda command: command["version"])
        require(all(type(event["version"]) is int for event in events) and [event["version"] for event in events] == [1, 2, 3] and [event["operation"] for event in events] == ["inverse-create" if row is child else "create", "review", "post"]
            and [event["actor_id"] for event in events] == [row["creator_actor_id"], row["reviewer_actor_id"], row["poster_actor_id"]]
            and len({event["actor_id"] for event in events}) == 3, "Three independent original human commands differ")
        for event, command in zip(events, commands, strict=True):
            require(type(command["version"]) is int and command["version"] == event["version"] and command["operation"] == event["operation"] and command["actor_id"] == event["actor_id"]
                and command["request_json"] == event["request_json"] and sha(command["request_json"]) == event["request_digest"] == command["request_digest"],
                "Immutable original request/actor/command seal differs")
            metadata = {"source_digest": row["source_digest"], "version": event["version"], "operation": event["operation"], "reason": event["reason"]}
            audit, emitted = audits[event["audit_event_id"]], outbox[event["outbox_event_id"]]
            require(audit["object_type"] == emitted["aggregate_type"] == "inventory_transfer" and audit["object_id"] == emitted["aggregate_id"] == row["id"]
                and audit["actor_user_id"] == event["actor_id"] and audit["action"] == emitted["event_type"] == "inventory_transfer." + event["operation"]
                and audit["metadata_json"] == metadata and emitted["payload"] == {**metadata, "audit_event_id": audit["id"]}
                and all(emitted[key] == expected for key, expected in scope.items()), "Original transfer event/audit/scoped immutable outbox membership differs")
            ack = command["response_json"]
            require(type(ack["source"]["row_version"]) is int and type(ack["source"]["phase"]) is int and ack["source"]["id"] == row["id"] and ack["source"]["source_digest"] == row["source_digest"]
                and ack["source"]["row_version"] == event["version"] and ack["source"]["phase"] == event["version"] - 1
                and ack["native_response"] == ack["source"]["native_response"]
                and ack["native_response"] == (row["posted_native_json"] if event["version"] == 3 else row["native_creation_json"]),
                "Original historical ACK/native membership differs")
            public = ack["source"]
            require(all(public[key] == value for key, value in payload.items()) and public["creator_actor_id"] == row["creator_actor_id"]
                and public["reviewer_actor_id"] == (row["reviewer_actor_id"] if event["version"] >= 2 else None)
                and public["poster_actor_id"] == (row["poster_actor_id"] if event["version"] == 3 else None)
                and public["review_cost_snapshot"] == (row["review_cost_json"] if event["version"] >= 2 else None)
                and public["review_cost_digest"] == (row["review_cost_digest"] if event["version"] >= 2 else None), "Complete original historical ACK source differs")
            retained_claim = None if event["version"] == 1 else {**claim, "state": "Active" if event["version"] == 2 else "Posted"}
            require(public["claim"] == retained_claim and public["release"] == (release if event["version"] == 3 else None), "Original historical ACK claim/release state differs")
        require({event["audit_event_id"] for event in events} == {audit["id"] for audit in audits.values() if audit["object_type"] == "inventory_transfer" and audit["object_id"] == row["id"]}
            and {event["outbox_event_id"] for event in events} == {event["event_id"] for event in outbox.values() if event["aggregate_type"] == "inventory_transfer" and event["aggregate_id"] == row["id"]}, "Transfer original owner evidence population omitted or added")
    require(all(audit["object_id"] in sources for audit in audits.values() if audit["object_type"] == "inventory_transfer")
        and all(event["aggregate_id"] in sources for event in outbox.values() if event["aggregate_type"] == "inventory_transfer"), "Detached transfer owner evidence")
    require(not tables["inventory_layer_consumptions"] and not tables["inventory_valuation_reversals"] and not tables["inventory_valuation_reversal_effects"],
        "Bounded full transfer cycle cannot invent consumption or correction effects")
    receipts = tables["inventory_receipt_plans"]
    require(len(receipts) == len(tables["inventory_cost_layers"]) == len(tables["inventory_valuation_documents"]) == len(tables["finance_posting_effects"]) == 1,
        "Same-entity transfers must add zero valuation, layer or native GL effects")
    require(all(len(tables[name]) == 1 for name in ("inventory_receipt_reviews", "inventory_receipt_links", "inventory_valuation_lines", "inventory_valuation_input_costs", "finance_entries"))
        and len(tables["finance_entry_lines"]) == 2 and len(tables["inventory_receipt_commands"]) == 3, "Complete original cost/GL owner population differs")
    receipt = receipts[0]
    require(len(movements) == 3 and receipt["movement_id"] in movements, "One original opening receipt plus two native transfers required")
    opening = integer(receipt["quantity_scaled"], True)
    physical: Counter[str] = Counter()
    for movement in sorted(movements.values(), key=lambda movement: (movement["movement_date"], movement["movement_number"])):
        require(movement["status"] == "Posted", "Original physical population contains an incomplete effect")
        for line in tables["inventory_movement_lines"]:
            if line["movement_id"] == movement["id"]:
                amount = integer(line["quantity_scaled"], True)
                if line["from_location_id"] is not None:
                    physical[line["from_location_id"]] -= amount
                if line["to_location_id"] is not None:
                    physical[line["to_location_id"]] += amount
    require(physical[forward["from_location_id"]] == opening and physical[forward["to_location_id"]] == 0 and sum(physical.values()) == opening,
        "Independent original physical forward/inverse conservation differs")
    layer = tables["inventory_cost_layers"][0]
    require(integer(layer["original_quantity_scaled"]) == integer(layer["remaining_quantity_scaled"]) == opening
        and integer(layer["original_value_minor"]) == integer(layer["remaining_value_minor"]) == integer(receipt["total_value_minor"], True),
        "Original approved pooled FIFO quantity/value changed")
    return {"schema_version": "inventory-transfer-oracle-v1", "original_digest": sha(proof), "opening_quantity_scaled": str(opening),
        "forward_quantity_scaled": str(integer(forward["quantity_scaled"])), "restored_quantity_scaled": str(physical[forward["from_location_id"]]),
        "destination_quantity_scaled": "0", "pooled_value_minor": str(integer(layer["remaining_value_minor"])),
        "new_valuation_effects": 0, "new_gl_effects": 0, "original_gl_effects": 1, "posted_transfers": 2, "independent_human_commands": 6}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("original", type=Path)
    parser.add_argument("--expected-export-sha256", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    proof, raw_digest = read_original(args.original, args.expected_export_sha256)
    result = canonical({**verify(proof), "original_file_sha256": raw_digest, "verifier_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}) + "\n"
    if args.output:
        with args.output.open("x", encoding="utf-8", newline="\n") as target:
            target.write(result)
    else:
        print(result, end="")


if __name__ == "__main__":
    main()
