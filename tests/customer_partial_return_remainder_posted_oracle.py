"""Standalone, private raw-row verification of finite actual v2 posted cycles.

The rational money model and retained audit-chain utility are separately pinned
stdlib-only dependencies. No production financial code, database, browser, or
implementation-generated expected values are imported. Zero *original* cost
needs its separate factual source contract; this reader never silently admits it.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import Any


def _dependency(name: str, filename: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    if spec is None or spec.loader is None:
        raise ValueError("Independent reader dependency refused.")
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


_audit = _dependency("_remainder_retained_audit", "customer_partial_return_posted_cycle_oracle.py")
_model = _dependency("_remainder_independent_model", "customer_partial_return_remainder_oracle.py")
TABLES = (*_audit.TABLES, "customer_partial_return_allocation_witnesses")
CASE_EVENTS = {
    "ordinary": ("Return", "Return", "Return"),
    "zero": ("Return", "ReverseReturn", "Return", "Return", "Return", "ReverseReturn", "Return"),
    "refund": ("Return", "Return", "Refund", "Refund", "ReverseRefund", "Refund"),
}
REPLAY_VERSIONS = {"ordinary": 1, "zero": 1, "refund": 4}


def require(value: bool) -> None:
    if not value:
        raise ValueError("Independent remaining-original posted cycle refused.")


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    ).hexdigest()


def _one(rows: list[dict[str, Any]], **keys: Any) -> dict[str, Any]:
    selected = [row for row in rows if all(row.get(key) == value for key, value in keys.items())]
    require(len(selected) == 1)
    return selected[0]


def _originals(value: Any, tenant: str) -> dict[str, tuple[str, ...]]:
    require(type(value) is dict and set(value) == set(TABLES))
    old = _audit._capture_originals({name: value[name] for name in _audit.TABLES}, tenant)
    name = "customer_partial_return_allocation_witnesses"
    rows = value[name]
    require(type(rows) in (list, tuple) and len(rows) <= 4096 and all(type(row) is str for row in rows))
    require(len(rows) == len(set(rows)) and all(_audit.decode_row(row)["tenant_id"] == tenant for row in rows))
    return {**old, name: tuple(sorted(rows))}


def _rows(tables: dict[str, tuple[str, ...]]) -> dict[str, list[dict[str, Any]]]:
    return {name: [_audit.decode_row(raw) for raw in values] for name, values in tables.items()}


def _capture(value: Any, tenant: str, source: str, version: int) -> dict[str, tuple[str, ...]]:
    require(
        type(value) is dict
        and set(value)
        == {
            "schema_version",
            "tenant_id",
            "source_order_id",
            "history_version",
            "posted_plan_id",
            "plan_digest",
            "tables",
        }
        and value["schema_version"] == "customer-partial-return-remainder-browser-capture-v1"
        and value["tenant_id"] == tenant
        and value["source_order_id"] == source
        and type(value["history_version"]) is int
        and value["history_version"] == version
    )
    if version == 0:
        require(value["posted_plan_id"] is None and value["plan_digest"] is None)
    else:
        require(
            type(value["posted_plan_id"]) is str
            and type(value["plan_digest"]) is str
            and re.fullmatch(r"[a-f0-9]{64}", value["plan_digest"]) is not None
        )
    return _originals(value["tables"], tenant)


def _source(
    baseline: dict[str, list[dict[str, Any]]], case: str, source: str
) -> tuple[Any, dict[str, Any], list[dict[str, Any]]]:
    stock = _one(baseline["stock_sales_orders"], id=source)
    invoice = _one(baseline["ar_invoices"], id=stock["invoice_id"])
    allocations = stock["issue_plan"]["allocations"]
    require(
        type(allocations) is list
        and 0 < len(allocations) <= 32
        and stock["issue_plan"]["schema_version"] == "stock-sales-issue-v1"
    )
    valuation = _one(baseline["inventory_valuation_lines"], valuation_document_id=stock["valuation_id"])
    consumptions = [
        _one(
            baseline["inventory_layer_consumptions"],
            cost_layer_id=part["cost_layer_id"],
            valuation_line_id=valuation["id"],
        )
        for part in allocations
    ]
    require(
        all(
            (part["quantity_scaled"], part["value_minor"]) == (row["quantity_scaled"], row["value_minor"])
            for part, row in zip(allocations, consumptions, strict=True)
        )
    )
    require(sum(row["quantity_scaled"] for row in consumptions) == stock["quantity_scaled"])
    paid = sum(row["amount_minor"] for row in baseline["ar_receipt_allocations"] if row["invoice_id"] == invoice["id"])
    expected = {"ordinary": (3, 3000, 1001, 0, 0), "zero": (3, 1, 1, 0, 1), "refund": (10, 45000, 12000, 10000, 0)}[
        case
    ]
    require(
        (
            stock["quantity_scaled"],
            invoice["total_minor"],
            sum(row["value_minor"] for row in consumptions),
            paid,
            stock["quantity_precision"],
        )
        == expected
        and invoice["tax_minor"] == 0
    )
    originals = tuple(_model.Consumption(row["id"], row["quantity_scaled"], row["value_minor"]) for row in consumptions)
    return (stock, invoice, paid, originals), stock, consumptions


def _gl_delta(
    before: dict[str, list[dict[str, Any]]], after: dict[str, list[dict[str, Any]]], plan: dict[str, Any], expected: Any
) -> tuple[int, int, int]:
    old = {row["id"] for row in before["finance_posting_effects"]}
    effects = [row for row in after["finance_posting_effects"] if row["id"] not in old]
    parts = plan["payload"]["entries"]
    require(
        type(parts) is list
        and len(parts) == len(expected) == len(effects)
        and [part["purpose"] for part in parts] == [purpose for purpose, _lines in expected]
    )
    require({effect["entry_id"] for effect in effects} == {part["entry_id"] for part in parts})
    accounts = {row["account_code"]: row["id"] for row in after["finance_accounts"]}
    line_count = debit = 0
    for part, (_purpose, expected_lines) in zip(parts, expected, strict=True):
        entry = _one(after["finance_entries"], id=part["entry_id"])
        effect = _one(effects, entry_id=entry["id"])
        lines = sorted(
            (row for row in after["finance_entry_lines"] if row["entry_id"] == entry["id"]),
            key=lambda row: row["line_number"],
        )
        require(
            entry["status"] == "Validated"
            and entry["validation_digest"] == effect["validation_digest"]
            and effect["validation_digest"] == part["validation_digest"] == _digest(effect["snapshot_json"])
            and effect["snapshot_json"] == part["snapshot"]
        )
        require(all(entry[key] == plan[key] for key in ("tenant_id", "workspace_id")))
        require(
            [(row["account_id"], row["debit_minor"], row["credit_minor"]) for row in lines]
            == [(accounts[code], left, right) for code, left, right in expected_lines]
        )
        require(
            all(
                type(row["debit_minor"]) is int
                and type(row["credit_minor"]) is int
                and min(row["debit_minor"], row["credit_minor"]) == 0 < max(row["debit_minor"], row["credit_minor"])
                for row in lines
            )
        )
        left, right = sum(row["debit_minor"] for row in lines), sum(row["credit_minor"] for row in lines)
        require(left == right == entry["total_debit_minor"] == entry["total_credit_minor"] > 0)
        line_count += len(lines)
        debit += left
    for name in ("finance_posting_effects", "inventory_layer_consumptions"):
        require(all(row in after[name] for row in before[name]))
    return len(effects), line_count, debit


def _physical(
    after: dict[str, list[dict[str, Any]]], stock: dict[str, Any], plan: dict[str, Any], witness: Any, reverse: bool
) -> None:
    payload = plan["payload"]
    require(payload["domain_plan"]["allocation_policy"] == _model.POLICY)
    domain = payload["domain_plan"]
    require(
        (domain["revenue_before_quantity_scaled"], domain["revenue_before_value_minor"])
        == (witness.revenue_before_quantity_scaled, witness.revenue_before_value_minor)
    )
    movement = _one(after["inventory_movements"], id=payload["movement_id"])
    line = _one(after["inventory_movement_lines"], movement_id=movement["id"])
    require(
        movement["source_reference"] == plan["id"]
        and movement["movement_number"] == plan["id"].upper()
        and movement["status"] == "Posted"
        and movement["source_type"] == "Generated"
        and movement["movement_type"] == ("Delivery" if reverse else "Receipt")
        and line["quantity_scaled"] == witness.quantity_scaled
        and line["quantity_precision"] == stock["quantity_precision"]
        and line["item_id"] == stock["item_id"]
        and line["uom_id"] == stock["uom_id"]
        and line["from_location_id"] == (stock["location_id"] if reverse else None)
        and line["to_location_id"] == (None if reverse else stock["location_id"])
    )
    originals = {row["id"]: row for row in after["inventory_layer_consumptions"]}
    restorations = [row for row in after["customer_partial_return_restorations"] if row["plan_id"] == plan["id"]]
    before_values = [
        row for row in after["customer_partial_return_allocation_witnesses"] if row["plan_id"] == plan["id"]
    ]
    require(len(restorations) == len(before_values) == len(witness.portions) == len(domain["portions"]))
    cost_parts = [
        part for part in payload["entries"] if part["purpose"] in ("CostRestoration", "ReverseCostRestoration")
    ]
    require(len(cost_parts) == (1 if witness.cost_minor else 0))
    cost_effect = (
        _one(after["finance_posting_effects"], entry_id=cost_parts[0]["entry_id"])["id"] if witness.cost_minor else None
    )
    for portion in witness.portions:
        original = originals[portion.consumption_id]
        restoration = _one(restorations, original_consumption_id=original["id"])
        native_witness = _one(before_values, position=restoration["position"])
        domain_part = _one(domain["portions"], original_consumption_id=original["id"])
        require(
            (
                restoration["quantity_scaled"],
                restoration["value_minor"],
                restoration["offset_quantity_scaled"],
                restoration["direction"],
                restoration["correction_effect_id"],
                restoration["original_restoration_plan_id"],
            )
            == (
                portion.quantity_scaled,
                portion.value_minor,
                portion.offset_quantity_scaled,
                -1 if reverse else 1,
                cost_effect,
                payload["original_id"] if reverse else None,
            )
        )
        require(
            restoration["cost_layer_id"] == original["cost_layer_id"]
            and restoration["original_valuation_line_id"] == original["valuation_line_id"]
            and restoration["physical_movement_id"] == movement["id"]
        )
        for observed in (native_witness, domain_part):
            require(
                (observed["before_quantity_scaled"], observed["before_value_minor"])
                == (portion.before_quantity_scaled, portion.before_value_minor)
            )


def qualify_raw_cycle(packet: dict[str, Any]) -> dict[str, Any]:
    require(
        type(packet) is dict
        and set(packet) == {"schema_version", "case", "tenant_id", "source_order_id", "captures"}
        and packet["schema_version"] == "customer-partial-return-remainder-posted-cycle-input-v1"
        and packet["case"] in CASE_EVENTS
    )
    case, tenant, source = (
        packet["case"],
        _audit.identity(packet["tenant_id"]),
        _audit.identity(packet["source_order_id"]),
    )
    events, captures = CASE_EVENTS[case], packet["captures"]
    require(type(captures) is list and len(captures) == len(events) + 1 <= 257)
    raw = [_capture(value, tenant, source, index) for index, value in enumerate(captures)]
    decoded = [_rows(tables) for tables in raw]
    facts, stock, originals = _source(decoded[0], case, source)
    source_row = _one(decoded[1]["customer_partial_return_sources"], source_order_id=source)
    require(
        source_row["source_payload"]["allocation_policy"] == _model.POLICY
        and "original_cost_admission" not in source_row["source_payload"]["typed_source"]
    )
    _, invoice, paid, consumed = facts
    require(
        (source_row["original_quantity_scaled"], source_row["gross_minor"], source_row["initial_collected_minor"])
        == (stock["quantity_scaled"], invoice["total_minor"], paid)
        and _digest(source_row["source_payload"]["fingerprint_payload"]) == source_row["source_fingerprint"]
    )
    birth = _model.Birth(
        stock["quantity_scaled"],
        invoice["total_minor"],
        paid,
        consumed,
        source_row["source_fingerprint"],
        _model.POLICY,
        "HALF_UP",
        "HALF_EVEN",
    )
    model = _model.History(birth)
    seen: dict[str, Any] = {}
    totals = [0, 0, 0]
    for index, operation in enumerate(events, 1):
        before, after = decoded[index - 1], decoded[index]
        histories = sorted(after["customer_partial_return_history"], key=lambda row: row["sequence"])
        require(len(histories) == index and [row["sequence"] for row in histories] == list(range(1, index + 1)))
        event = histories[-1]
        plan = _one(after["customer_partial_return_plans"], id=event["plan_id"])
        payload = plan["payload"]
        require(
            plan["phase"] == 2
            and plan["operation"] == operation == event["kind"]
            and plan["expected_history_version"] == index - 1
            and plan["id"] == captures[index]["posted_plan_id"]
            and plan["plan_digest"] == captures[index]["plan_digest"]
            and payload["schema_version"] == "customer-partial-return-v2"
            and payload["allocation_policy"] == _model.POLICY
        )
        require(_one(after["customer_partial_return_sources"], id=source_row["id"]) == source_row)
        if operation == "Return":
            quantity = (8 if index == 1 else 2) if case == "refund" else 1
            witness = model.propose_return(plan["id"], quantity, model.version)
            model.post_return(witness)
            seen[plan["id"]] = witness
            expected = _model.return_entries(witness)
        elif operation == "ReverseReturn":
            parent = payload["original_id"]
            witness = model.reverse_latest(plan["id"], parent, model.version).witness
            require(witness is not None and witness == seen[parent])
            expected = _model.return_entries(witness, reverse=True)
        elif operation == "Refund":
            amount = 3000 if index == 3 else 7000
            model.refund(plan["id"], payload["original_id"], amount, model.version)
            expected = (("Refund", (("REFUND", amount, 0), ("CASH", 0, amount))),)
        else:
            parent = model.reverse_latest(plan["id"], payload["original_id"], model.version)
            require(parent.kind == "Refund" and parent.amount_minor == 7000)
            expected = (("ReverseRefund", (("REFUND", 0, 7000), ("CASH", 7000, 0))),)
        if operation in ("Return", "ReverseReturn"):
            require(
                (
                    plan["quantity_scaled"],
                    plan["credit_minor"],
                    plan["cogs_restored_minor"],
                    plan["receivable_released_minor"],
                    plan["refund_entitlement_delta_minor"],
                    plan["amount_minor"],
                )
                == (
                    witness.quantity_scaled,
                    witness.credit_minor,
                    witness.cost_minor,
                    witness.receivable_released_minor,
                    witness.refund_delta_minor,
                    witness.credit_minor + witness.cost_minor,
                )
            )
            _physical(after, stock, plan, witness, operation == "ReverseReturn")
        else:
            require(
                plan["quantity_scaled"] == plan["credit_minor"] == plan["cogs_restored_minor"] == 0
                and plan["amount_minor"] == (3000 if index == 3 else 7000)
            )
        totals = [left + right for left, right in zip(totals, _gl_delta(before, after, plan, expected), strict=True)]
        require(after["inventory_layer_consumptions"] == decoded[0]["inventory_layer_consumptions"])
        for original, (remaining_q, remaining_v) in zip(originals, model.remaining, strict=True):
            old_layer = _one(decoded[0]["inventory_cost_layers"], id=original["cost_layer_id"])
            layer = _one(after["inventory_cost_layers"], id=original["cost_layer_id"])
            require(
                (layer["remaining_quantity_scaled"], layer["remaining_value_minor"])
                == (
                    old_layer["remaining_quantity_scaled"] + original["quantity_scaled"] - remaining_q,
                    old_layer["remaining_value_minor"] + original["value_minor"] - remaining_v,
                )
            )
        review = _one(after["customer_partial_return_events"], plan_id=plan["id"], operation="review")
        post = _one(after["customer_partial_return_events"], plan_id=plan["id"], operation="post")
        require(len({plan["preparer_actor_id"], review["actor_id"], post["actor_id"]}) == 3)
    expected_totals = {"ordinary": [6, 12, 4001], "zero": [4, 8, 4], "refund": [8, 17, 81000]}[case]
    require(
        totals == expected_totals
        and model.returned == birth.quantity_scaled
        and model.credited == birth.revenue_minor
        and model.restored_cost == sum(row.value_minor for row in birth.consumptions)
        and model.outstanding == model.refund_due == 0
    )
    return {
        "status": "passed",
        "case": case,
        "events": len(events),
        "captures": len(captures),
        "tables": 79,
        "positive_original_consumptions": len(originals),
        "history_capacity": 256,
        "allocation_policy": _model.POLICY,
        "new_actual_posting_effects": totals[0],
        "new_actual_posted_lines": totals[1],
        "new_debits_minor": totals[2],
        "new_credits_minor": totals[2],
        "zero_financial_entries_omitted": True,
        "immutable_original_consumptions": True,
        "independent_active_prefix_witnesses": True,
        "three_distinct_humans": True,
        "original_zero_cost_admission": False,
        "benchmark": False,
    }


def _policy_append(row: dict[str, Any], tables: dict[str, tuple[str, ...]]) -> None:
    require(
        row["actor_label"] == "policy-engine"
        and row["object_type"] == "authorization.policy_decision"
        and row["action"] == "evaluated"
        and row["before_hash"] is None
    )
    metadata = row["metadata_json"]
    require(type(metadata) is dict and set(metadata) == {"policy_decision_evidence", "request_id_digest"})
    policy = metadata["policy_decision_evidence"]
    require(
        type(policy) is dict
        and set(policy) == _audit.POLICY_FIELDS
        and type(policy["schema_version"]) is int
        and policy["schema_version"] == 1
        and policy["policy_version"] == "central-policy-v3"
        and policy["allowed"] is True
        and policy["principal_type"] == "user"
        and policy["context_binding"] == "bound"
    )
    for name in (
        "actor_digest",
        "context_digest",
        "decision_digest",
        "required_permission_digest",
        "scope_digest",
        "surface_digest",
        "request_id_digest",
        "granted_permission_digest",
    ):
        _audit._hex(policy[name])
    for name in ("reason_code", "evaluator"):
        _audit.identity(policy[name])
    unsigned = {key: value for key, value in policy.items() if key != "decision_digest"}
    require(
        _audit.audit_digest(unsigned) == policy["decision_digest"] == row["object_id"] == row["after_hash"]
        and metadata["request_id_digest"] == policy["request_id_digest"]
    )
    surfaces, actors = _audit._surface_contracts(tables)
    plans = [_audit.decode_row(raw) for raw in tables["customer_partial_return_plans"]]
    for plan in plans:
        endpoints = {
            "GET /api/v2/customer-partial-returns/plans": _audit.READ_PERMISSIONS,
            "GET /api/v2/customer-partial-returns/plans/" + plan["id"]: _audit.READ_PERMISSIONS,
            "GET /api/v2/customer-partial-returns/sources/"
            + plan["source_order_id"]
            + "/balance": _audit.READ_PERMISSIONS,
        }
        if plan["phase"] == 2:
            endpoints["POST /api/v2/customer-partial-returns/plans/" + plan["id"] + "/post"] = _audit.POST_PERMISSIONS
        surfaces.update(
            {_audit._text_digest("audit.surface", path): permissions for path, permissions in endpoints.items()}
        )
    actor = _audit.identity(row["actor_user_id"])
    require(
        actor in actors and policy["actor_digest"] == _audit._text_digest("principal.actor", actor.strip().casefold())
    )
    permissions = surfaces.get(policy["surface_digest"])
    require(permissions is not None)
    require(
        any(
            policy["required_permission_digest"]
            == _audit.audit_digest({"namespace": "permission.contract", "values": [permission]})
            and policy["granted_permission_digest"] == _audit._text_digest("permission.granted", permission)
            for permission in permissions
        )
    )


def verify_audit_only_transition(
    before_tables: dict[str, Any], after_tables: dict[str, Any], *, tenant_id: str
) -> dict[str, Any]:
    """All 77 business tables exact; retained audit bytes, chain and finite actions valid."""
    before, after = _originals(before_tables, tenant_id), _originals(after_tables, tenant_id)
    require(all(before[name] == after[name] for name in set(TABLES) - _audit.AUDIT_TABLES))
    old, new = _audit._audit_chain(before, tenant_id), _audit._audit_chain(after, tenant_id)
    require(len(new) >= len(old) and [raw for _row, raw in new[: len(old)]] == [raw for _row, raw in old])
    if len(new) == len(old):
        require(before["domain_audit_ledger_state"] == after["domain_audit_ledger_state"])
    for row, _raw in new[len(old) :]:
        _policy_append(row, after)
    return {
        "business_tables": 77,
        "business_original_rows_equal": True,
        "audit_original_prefix_equal": True,
        "audit_chain_valid": True,
        "audit_actions_bound": True,
        "appended_audit_events": len(new) - len(old),
    }


def verify_raw_observations(packet: dict[str, Any], observations: dict[str, Any]) -> dict[str, Any]:
    case, tenant, source = packet["case"], packet["tenant_id"], packet["source_order_id"]
    require(
        type(observations) is dict
        and set(observations) == {"schema_version", "case", "tenant_id", "source_order_id", "observations"}
        and observations["schema_version"] == "customer-partial-return-remainder-posted-observations-input-v1"
        and all(observations[key] == packet[key] for key in ("case", "tenant_id", "source_order_id"))
    )
    rows = observations["observations"]
    require(type(rows) is list and len(rows) == 2)
    appended = 0
    for observation, kind, version in zip(
        rows, ("RetainedReplay", "FinalRead"), (REPLAY_VERSIONS[case], len(CASE_EVENTS[case])), strict=True
    ):
        require(
            type(observation) is dict
            and set(observation)
            == {
                "schema_version",
                "kind",
                "tenant_id",
                "source_order_id",
                "history_version",
                "posted_plan_id",
                "plan_digest",
                "tables",
            }
            and observation["schema_version"] == "customer-partial-return-remainder-browser-observation-v1"
            and observation["kind"] == kind
            and type(observation["history_version"]) is int
            and observation["history_version"] == version
        )
        baseline = packet["captures"][version]
        require(
            all(
                observation[key] == baseline[key]
                for key in ("tenant_id", "source_order_id", "posted_plan_id", "plan_digest")
            )
        )
        result = verify_audit_only_transition(baseline["tables"], observation["tables"], tenant_id=tenant)
        appended += result["appended_audit_events"]
        if kind == "RetainedReplay":
            current = _audit._audit_chain(_originals(observation["tables"], tenant), tenant)
            following = _audit._audit_chain(_originals(packet["captures"][version + 1]["tables"], tenant), tenant)
            require([raw for _row, raw in following[: len(current)]] == [raw for _row, raw in current])
    require(rows[-1]["source_order_id"] == source)
    return {
        "observation_schema": "customer-partial-return-remainder-posted-observations-input-v1",
        "observations": 2,
        "observation_tables": 79,
        "observation_business_tables": 77,
        "observation_chronology_bound": True,
        "appended_audit_events": appended,
        "audit_original_prefix_equal": True,
        "audit_chain_valid": True,
        "audit_actions_bound": True,
        "business_original_rows_equal": True,
    }


def verify_restored_cycle(
    packet: dict[str, Any], restored: dict[str, Any], observations: dict[str, Any] | None = None
) -> dict[str, Any]:
    require(
        type(restored) is dict
        and set(restored) == {"schema_version", "case", "tenant_id", "source_order_id", "tables"}
        and restored["schema_version"] == "customer-partial-return-remainder-posted-restored-input-v1"
        and all(restored[key] == packet[key] for key in ("case", "tenant_id", "source_order_id"))
    )
    if observations is not None:
        verify_raw_observations(packet, observations)
    expected = (
        observations["observations"][-1]["tables"] if observations is not None else packet["captures"][-1]["tables"]
    )
    require(_originals(restored["tables"], packet["tenant_id"]) == _originals(expected, packet["tenant_id"]))
    return {
        "restored_tables": 79,
        "restored_rows": sum(len(rows) for rows in restored["tables"].values()),
        "restored_original_rows_equal": True,
        "restore_target_final_observation": observations is not None,
    }


def qualify_native_refunds(packet: dict[str, Any]) -> dict[str, Any]:
    """The native test's seven original snapshots are a separate input contract."""
    require(
        type(packet) is dict
        and set(packet) == {"schema_version", "tenant_id", "source_order_id", "captures"}
        and packet["schema_version"] == "customer-partial-return-remainder-native-refunds-v1"
        and type(packet["captures"]) is list
        and len(packet["captures"]) == 7
    )
    captures = []
    for version, tables in enumerate(packet["captures"]):
        decoded = _rows(_originals(tables, packet["tenant_id"]))
        if version:
            event = _one(decoded["customer_partial_return_history"], sequence=version)
            plan = _one(decoded["customer_partial_return_plans"], id=event["plan_id"])
        captures.append(
            {
                "schema_version": "customer-partial-return-remainder-browser-capture-v1",
                "tenant_id": packet["tenant_id"],
                "source_order_id": packet["source_order_id"],
                "history_version": version,
                "posted_plan_id": plan["id"] if version else None,
                "plan_digest": plan["plan_digest"] if version else None,
                "tables": tables,
            }
        )
    proof = qualify_raw_cycle(
        {
            "schema_version": "customer-partial-return-remainder-posted-cycle-input-v1",
            "case": "refund",
            "tenant_id": packet["tenant_id"],
            "source_order_id": packet["source_order_id"],
            "captures": captures,
        }
    )
    return {
        **proof,
        "input_schema": "customer-partial-return-remainder-native-refunds-v1",
        "browser_execution_proven": False,
        "populated_restore_proven": False,
    }


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Verify private v2 remaining-original financial captures.")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--observations-input", type=Path)
    parser.add_argument("--restore-input", type=Path)
    args = parser.parse_args()
    try:
        require(not args.output.exists())
        inputs: dict[str, bytes] = {}
        values: dict[str, dict[str, Any]] = {}
        for name in ("input", "observations_input", "restore_input"):
            path = getattr(args, name)
            if path is not None:
                require(path.resolve() != args.output.resolve() and path.stat().st_size <= 64 * 1024 * 1024)
                inputs[name] = path.read_bytes()
                values[name] = _audit.decode_row(inputs[name].decode("utf-8"), maximum_bytes=64 * 1024 * 1024)
        native = values["input"].get("schema_version") == "customer-partial-return-remainder-native-refunds-v1"
        if native:
            require(set(values) == {"input"})
        proof = qualify_native_refunds(values["input"]) if native else qualify_raw_cycle(values["input"])
        if "observations_input" in values:
            proof.update(verify_raw_observations(values["input"], values["observations_input"]))
        if "restore_input" in values:
            proof.update(
                verify_restored_cycle(values["input"], values["restore_input"], values.get("observations_input"))
            )
        proof["input_sha256"] = {name: hashlib.sha256(data).hexdigest() for name, data in inputs.items()}
        proof["reader_source_sha256"] = {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (
                Path(__file__),
                Path(__file__).with_name("customer_partial_return_posted_cycle_oracle.py"),
                Path(__file__).with_name("customer_partial_return_remainder_oracle.py"),
            )
        }
        with args.output.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(proof, stream, sort_keys=True, separators=(",", ":"))
            stream.write("\n")
        return 0
    except (ValueError, TypeError, KeyError, IndexError, OverflowError, OSError, RecursionError):
        print("Independent remaining-original financial verification refused.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
