"""Independent finite four-checkpoint zero-cost resale and new-return reader.

The old positive original remains governed by its stricter source contract.
The new zero-cost original requires a separate factual admission bound to the
actual native issue, prior restitution, consumption, valuation and absent COGS.
No production financial modules, DB, browser or generated expectations are used.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

if __package__:
    from tests import customer_partial_return_remainder_posted_oracle as base
else:
    import importlib.util

    _spec = importlib.util.spec_from_file_location("_restituted_base", Path(__file__).with_name("customer_partial_return_remainder_posted_oracle.py"))
    if _spec is None or _spec.loader is None:
        raise ValueError("Independent restituted reader dependency refused.")
    base = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(base)

factual = base._dependency("_restituted_factual", "customer_partial_return_restituted_source_oracle.py")
TABLES = base.TABLES
CHECKPOINTS = ("Original", "ZeroReturn", "ResaleInvoiced", "ResaleReturned")
ACCOUNT_BALANCES = {"AR": 1, "CASH": 0, "CLEARING": -1, "COGS": 1, "INVENTORY": 0, "REFUND": 0, "REVENUE": -1}


def require(value: bool) -> None:
    if not value:
        raise ValueError("Independent restituted cycle refused.")


def integer(value: Any) -> int:
    require(type(value) is int and 0 <= value <= 9_000_000_000_000_000_000)
    return value


def _unchanged_rows(before: dict[str, tuple[str, ...]], after: dict[str, tuple[str, ...]], names: tuple[str, ...]) -> None:
    for name in names:
        require(set(before[name]).issubset(after[name]))


def _ledger(rows: dict[str, list[dict[str, Any]]]) -> tuple[int, int, int, dict[str, int]]:
    accounts = {row["id"]: row["account_code"] for row in rows["finance_accounts"]}
    require(len(accounts) == len(rows["finance_accounts"]))
    balances = dict.fromkeys(ACCOUNT_BALANCES, 0)
    effects = rows["finance_posting_effects"]
    require(len({row["id"] for row in effects}) == len({row["entry_id"] for row in effects}) == len(effects))
    require(len(rows["finance_entries"]) == len(effects))
    count = debit = 0
    for effect in effects:
        entry = base._one(rows["finance_entries"], id=effect["entry_id"])
        lines = sorted((row for row in rows["finance_entry_lines"] if row["entry_id"] == entry["id"]), key=lambda row: integer(row["line_number"]))
        snapshot = effect["snapshot_json"]
        require(type(snapshot) is dict and set(snapshot) == {"schema_version", "entry", "lines"}
                and snapshot["schema_version"] == "finance-entry-review-v1" and entry["status"] == "Validated"
                and effect["validation_digest"] == entry["validation_digest"] == base._digest(snapshot)
                and type(snapshot["lines"]) is list and len(snapshot["lines"]) == len(lines) > 0
                and [row["line_number"] for row in lines] == list(range(1, len(lines) + 1)))
        require(snapshot["entry"]["id"] == entry["id"])
        for key in ("entry_number", "workspace_id", "journal_id", "period_id", "currency_code", "currency_precision", "currency_rounding_policy",
                    "currency_registry_version", "currency_registry_digest", "preparer_actor_id", "source_type", "external_reference", "reverses_posting_id"):
            require(snapshot["entry"][key] == entry[key])
        left = right = 0
        for observed, sealed in zip(lines, snapshot["lines"], strict=True):
            require(all(sealed[key] == observed[key] for key in ("line_number", "account_id", "debit_minor", "credit_minor")))
            require(type(sealed["dimensions"]) is dict and sealed["dimensions"] == {} and not any(row["entry_line_id"] == observed["id"] for row in rows["finance_entry_line_dimensions"]))
            d, c = integer(observed["debit_minor"]), integer(observed["credit_minor"])
            require(min(d, c) == 0 < max(d, c) and accounts[observed["account_id"]] in balances)
            balances[accounts[observed["account_id"]]] += d - c
            left += d
            right += c
        require(left == right == integer(entry["total_debit_minor"]) == integer(entry["total_credit_minor"]) > 0)
        count += len(lines)
        debit += left
    require(count == len(rows["finance_entry_lines"]))
    return len(effects), count, debit, balances


def _plan(rows: dict[str, list[dict[str, Any]]], source: dict[str, Any], stock: dict[str, Any], *, credit: int,
          consumption: dict[str, Any], before_q: int, before_v: int, before_revenue: int) -> dict[str, Any]:
    histories = [row for row in rows["customer_partial_return_history"] if row["source_id"] == source["id"]]
    require(len(histories) == 1 and histories[0]["sequence"] == 1 and histories[0]["kind"] == "Return")
    plan = base._one(rows["customer_partial_return_plans"], id=histories[0]["plan_id"])
    payload = plan["payload"]
    require(payload["plan_digest"] == plan["plan_digest"] == base._digest({key: value for key, value in payload.items() if key != "plan_digest"}))
    require(all(payload[key] == plan[key] for key in ("id", "source_id", "source_order_id", "quantity_scaled", "credit_minor", "cogs_restored_minor",
                                                     "receivable_released_minor", "refund_entitlement_delta_minor", "amount_minor", "preparer_actor_id")))
    require(plan["source_id"] == source["id"] and plan["source_order_id"] == stock["id"] and plan["operation"] == "Return"
            and type(plan["phase"]) is int and plan["phase"] == 2 and type(plan["expected_history_version"]) is int and plan["expected_history_version"] == 0
            and payload["schema_version"] == "customer-partial-return-v2" and payload["allocation_policy"] == "remaining-original-v1")
    observed = tuple(integer(plan[key]) for key in ("quantity_scaled", "credit_minor", "cogs_restored_minor", "receivable_released_minor", "refund_entitlement_delta_minor", "amount_minor"))
    require(observed == (1, credit, 0, credit, 0, credit))
    domain = payload["domain_plan"]
    require(domain["source_fingerprint"] == source["source_fingerprint"] and domain["expected_version"] == 0
            and domain["allocation_policy"] == "remaining-original-v1")
    require(len(domain["portions"]) == 1)
    part = domain["portions"][0]
    require(tuple(integer(part[key]) for key in ("quantity_scaled", "value_minor", "offset_quantity_scaled", "before_quantity_scaled", "before_value_minor"))
            == (1, 0, 0, before_q, before_v) and part["original_consumption_id"] == consumption["id"]
            and part["cost_layer_id"] == consumption["cost_layer_id"] and part["original_valuation_line_id"] == consumption["valuation_line_id"])
    portion = base._model.Portion(consumption["id"], 0, 1, 0, before_q, before_v)
    witness = base._model.ReturnWitness(plan["id"], source["source_fingerprint"], "remaining-original-v1", 0, 1, credit, 0, credit, 0, before_q, before_revenue, (portion,))
    base._physical(rows, stock, plan, witness, False)
    review = base._one(rows["customer_partial_return_events"], plan_id=plan["id"], operation="review")
    post = base._one(rows["customer_partial_return_events"], plan_id=plan["id"], operation="post")
    require(len({plan["preparer_actor_id"], review["actor_id"], post["actor_id"]}) == 3)
    return plan


def qualify_raw_cycle(packet: dict[str, Any]) -> dict[str, Any]:
    require(type(packet) is dict and set(packet) == {"schema_version", "tenant_id", "original_source_order_id", "resale_source_order_id", "captures"}
            and packet["schema_version"] == "customer-partial-return-restituted-cycle-input-v1")
    tenant = base._audit.identity(packet["tenant_id"])
    old_id, new_id = (base._audit.identity(packet[key]) for key in ("original_source_order_id", "resale_source_order_id"))
    require(old_id != new_id and type(packet["captures"]) is list and len(packet["captures"]) == 4)
    raw = []
    for capture, checkpoint in zip(packet["captures"], CHECKPOINTS, strict=True):
        require(type(capture) is dict and set(capture) == {"checkpoint", "tables"} and capture["checkpoint"] == checkpoint)
        raw.append(base._originals(capture["tables"], tenant))
    stages = [base._rows(tables) for tables in raw]
    original = stages[0]
    facts, old_stock, old_consumptions = base._source(original, "zero", old_id)
    require(len(old_consumptions) == 1 and not original["customer_partial_return_sources"] and not original["customer_partial_return_plans"])
    cogs = base._one(original["finance_posting_effects"], id=old_stock["cogs_effect_id"])
    require(cogs["entry_id"] == old_stock["cogs_entry_id"])
    accounts = {row["account_code"]: row["id"] for row in original["finance_accounts"]}
    cogs_lines = sorted((row for row in original["finance_entry_lines"] if row["entry_id"] == cogs["entry_id"]), key=lambda row: integer(row["line_number"]))
    require([(row["account_id"], integer(row["debit_minor"]), integer(row["credit_minor"])) for row in cogs_lines] == [(accounts["COGS"], 1, 0), (accounts["INVENTORY"], 0, 1)])
    old_source = base._one(stages[1]["customer_partial_return_sources"], source_order_id=old_id)
    require(old_source["source_payload"]["allocation_policy"] == "remaining-original-v1"
            and "original_cost_admission" not in old_source["source_payload"]["typed_source"]
            and old_source["source_fingerprint"] == base._digest(old_source["source_payload"]["fingerprint_payload"])
            and old_source["original_cogs_effect_id"] == old_stock["cogs_effect_id"])
    require(tuple(integer(old_source[key]) for key in ("original_quantity_scaled", "gross_minor", "initial_collected_minor")) == (3, 1, 0))
    old_plan = _plan(stages[1], old_source, old_stock, credit=0, consumption=old_consumptions[0], before_q=3, before_v=1, before_revenue=1)
    base._gl_delta(stages[0], stages[1], old_plan, ())
    require(len(stages[1]["customer_partial_return_plans"]) == 1)
    new_stock = base._one(stages[2]["stock_sales_orders"], id=new_id)
    new_source = base._one(stages[3]["customer_partial_return_sources"], source_order_id=new_id)
    admission = factual.verify_restituted_original(stages[1], stages[2], new_source, tenant_id=tenant,
                                                  original_source_order_id=old_id, resale_source_order_id=new_id)
    invoice_plan = base._one(stages[2]["operational_finance_plans"], id=new_stock["invoice_plan_id"])
    invoice_link = base._one(stages[2]["operational_finance_links"], plan_id=invoice_plan["id"])
    invoice_effect = base._one(stages[2]["finance_posting_effects"], id=invoice_link["posting_effect_id"])
    require(invoice_plan["source_kind"] == "ARInvoice" and invoice_plan["source_id"] == new_stock["invoice_id"]
            and integer(invoice_plan["amount_minor"]) == 100 and invoice_plan["entry_id"] == invoice_effect["entry_id"]
            and invoice_plan["validation_digest"] == invoice_effect["validation_digest"]
            and invoice_link["plan_digest"] == invoice_plan["plan_digest"]
            and invoice_effect["id"] not in {row["id"] for row in stages[1]["finance_posting_effects"]}
            and all(invoice_plan[key] == new_stock[key] for key in ("workspace_id", "organization_id", "legal_entity_id"))
            and new_source["original_revenue_effect_id"] == invoice_effect["id"]
            and new_source["source_payload"]["original_source"]["revenue"] == invoice_effect
            and new_source["source_payload"]["typed_source"]["original_revenue"]["posting_effect_id"] == invoice_effect["id"]
            and new_source["source_payload"]["typed_source"]["original_revenue"]["validation_digest"] == invoice_effect["validation_digest"]
            and new_source["source_payload"]["fingerprint_payload"]["original_revenue"] == [invoice_effect["id"], invoice_effect["validation_digest"]])
    require(tuple(integer(new_source[key]) for key in ("original_quantity_scaled", "gross_minor", "initial_collected_minor")) == (1, 100, 0))
    zero_consumption = base._one(stages[2]["inventory_layer_consumptions"], valuation_line_id=admission_line(stages[2], new_stock))
    new_plan = _plan(stages[3], new_source, new_stock, credit=100, consumption=zero_consumption, before_q=1, before_v=0, before_revenue=100)
    base._gl_delta(stages[2], stages[3], new_plan, (("RevenueCredit", (("REVENUE", 100, 0), ("AR", 0, 100))),))
    require(len(stages[3]["customer_partial_return_sources"]) == len(stages[3]["customer_partial_return_plans"]) == 2)
    expected_balances = [
        {**ACCOUNT_BALANCES}, {**ACCOUNT_BALANCES},
        {**ACCOUNT_BALANCES, "AR": 101, "REVENUE": -101}, {**ACCOUNT_BALANCES},
    ]
    for index, rows in enumerate(stages):
        effects, lines, debit, balances = _ledger(rows)
        require((effects, lines, debit) == ((3, 6, 3), (3, 6, 3), (4, 8, 103), (5, 10, 203))[index]
                and balances == expected_balances[index])
        layer = base._one(rows["inventory_cost_layers"], id=old_consumptions[0]["cost_layer_id"])
        require((integer(layer["remaining_quantity_scaled"]), integer(layer["remaining_value_minor"])) == ((0, 0), (1, 0), (0, 0), (1, 0))[index])
        require(len(rows["inventory_cost_layers"]) == 1)
        require(len(rows["customer_partial_return_history"]) == (0, 1, 1, 2)[index])
        require(len(rows["inventory_layer_consumptions"]) == (1, 1, 2, 2)[index])
        base._audit._audit_chain(raw[index], tenant)
        if index:
            previous_audit = base._audit._audit_chain(raw[index - 1], tenant)
            current_audit = base._audit._audit_chain(raw[index], tenant)
            require([text for _row, text in current_audit[:len(previous_audit)]] == [text for _row, text in previous_audit])
            _unchanged_rows(raw[index - 1], raw[index], ("finance_posting_effects", "finance_entry_lines", "finance_entry_line_dimensions", "inventory_layer_consumptions"))
            for previous in stages[index - 1]["finance_posting_effects"]:
                entry = base._one(stages[index - 1]["finance_entries"], id=previous["entry_id"])
                require(base._one(rows["finance_entries"], id=entry["id"]) == entry)
        if index >= 1:
            require(base._one(rows["customer_partial_return_sources"], id=old_source["id"]) == old_source)
            require(base._one(rows["customer_partial_return_plans"], id=old_plan["id"]) == old_plan)
        require(base._one(rows["stock_sales_orders"], id=old_id) == old_stock)
    restoration = base._one(stages[3]["customer_partial_return_restorations"], plan_id=old_plan["id"])
    require(integer(restoration["consumption_count_at_restore"]) == 1
            and sum(row["cost_layer_id"] == restoration["cost_layer_id"] for row in stages[3]["inventory_layer_consumptions"]) == 2)
    return {"schema_version": "independent-restituted-cycle-proof-v1", "status": "passed", "checkpoints": 4, "tables": 79,
            "sources": 2, "governed_returns": 2, "original_cost_admission": admission,
            "final_actual_posting_effects": 5, "final_actual_posted_lines": 10, "final_debits_minor": 203, "final_credits_minor": 203,
            "final_account_minor_balances": dict(ACCOUNT_BALANCES), "old_return_credit_minor": 0, "resale_revenue_minor": 100,
            "resale_original_cogs_absent": True, "new_return_credit_minor": 100, "new_return_cost_minor": 0,
            "no_fake_zero_financial_entries": True, "final_layer_quantity_scaled": 1, "final_layer_value_minor": 0,
            "old_return_later_immutable_consumption_dependency": True, "three_distinct_humans": True,
            "dependency_refusal_http_proven": False, "populated_restore_proven": False, "current_authorization_proven": False, "benchmark": False}


def admission_line(rows: dict[str, list[dict[str, Any]]], stock: dict[str, Any]) -> str:
    return str(base._one(rows["inventory_valuation_lines"], valuation_document_id=stock["valuation_id"])["id"])


def _surfaces(tables: dict[str, tuple[str, ...]]) -> tuple[dict[str, frozenset[str]], set[str]]:
    rows = base._rows(tables)
    plans = rows["customer_partial_return_plans"]
    require(len(plans) == 2 and len({row["source_order_id"] for row in plans}) == 2 and all(row["phase"] == 2 for row in plans))
    actors = {base._audit.identity(row["preparer_actor_id"]) for row in plans}
    actors.update(base._audit.identity(row["actor_id"]) for row in rows["customer_partial_return_events"])
    read = base._audit.READ_PERMISSIONS
    prepare = read | {"sales.manage", "receivables.manage", "inventory.valuation.manage", "finance_core.manage", "finance_core.reverse"}
    surfaces: dict[str, frozenset[str]] = {"GET /api/v1/customer-returns/plans": read, "server.scoped:finance_core.read": frozenset({"finance_core.read"}),
                                            "server.scoped:finance_core.reverse": frozenset({"finance_core.reverse"})}
    for version in (1, 2):
        prefix = f"/api/v{version}/customer-partial-returns"
        surfaces["GET " + prefix + "/plans"] = read
        for plan in plans:
            surfaces["GET " + prefix + "/plans/" + plan["id"]] = read
            surfaces["GET " + prefix + "/sources/" + plan["source_order_id"] + "/balance"] = read
    for plan in plans:
        surfaces["POST /api/v2/customer-partial-returns/plans/" + plan["id"] + "/post"] = base._audit.POST_PERMISSIONS
        # Financial dependency refusal occurs after successful policy admission.
        # The separate observation receipt fixes which parent's inverse refused.
        surfaces["POST /api/v2/customer-partial-returns/plans/" + plan["id"] + "/reversals"] = frozenset(prepare)
    for suffix, permission in (("audit/events", "audit.read"), ("audit/verify", "audit.verify"), ("security/overview", "security.center.read"),
            ("identity/users", "users.manage"), ("identity/sessions", "users.manage"), ("access/permissions", "roles.manage"), ("access/roles", "roles.manage"),
            ("security/integrations", "security.policy.manage"), ("security/retention-policies", "security.policy.manage")):
        surfaces["GET /api/v1/admin/" + suffix] = frozenset({permission})
        surfaces["server.scoped:" + permission] = frozenset({permission})
    return {base._audit._text_digest("audit.surface", surface): permissions for surface, permissions in surfaces.items()}, actors


def _policy_append(row: dict[str, Any], tables: dict[str, tuple[str, ...]]) -> None:
    require(row["actor_label"] == "policy-engine" and row["object_type"] == "authorization.policy_decision" and row["action"] == "evaluated" and row["before_hash"] is None)
    metadata = row["metadata_json"]
    require(type(metadata) is dict and set(metadata) == {"policy_decision_evidence", "request_id_digest"})
    policy = metadata["policy_decision_evidence"]
    require(type(policy) is dict and set(policy) == base._audit.POLICY_FIELDS and type(policy["schema_version"]) is int and policy["schema_version"] == 1
            and policy["policy_version"] == "central-policy-v3" and policy["allowed"] is True and policy["principal_type"] == "user" and policy["context_binding"] == "bound")
    for key in ("actor_digest", "context_digest", "decision_digest", "required_permission_digest", "scope_digest", "surface_digest", "request_id_digest", "granted_permission_digest"):
        base._audit._hex(policy[key])
    for key in ("reason_code", "evaluator"):
        base._audit.identity(policy[key])
    require(base._audit.audit_digest({key: value for key, value in policy.items() if key != "decision_digest"}) == policy["decision_digest"] == row["object_id"] == row["after_hash"]
            and metadata["request_id_digest"] == policy["request_id_digest"])
    surfaces, actors = _surfaces(tables)
    actor = base._audit.identity(row["actor_user_id"])
    require(actor in actors and policy["actor_digest"] == base._audit._text_digest("principal.actor", actor.strip().casefold()))
    permissions = surfaces.get(policy["surface_digest"])
    require(permissions is not None)
    require(any(policy["required_permission_digest"] == base._audit.audit_digest({"namespace": "permission.contract", "values": [permission]})
                and policy["granted_permission_digest"] == base._audit._text_digest("permission.granted", permission) for permission in permissions or ()))


def verify_audit_only_transition(before_tables: dict[str, Any], after_tables: dict[str, Any], *, tenant_id: str) -> dict[str, Any]:
    """Two-source policy affinity, all77 business tables exact, full canonical audit."""
    before, after = base._originals(before_tables, tenant_id), base._originals(after_tables, tenant_id)
    require(all(before[name] == after[name] for name in set(TABLES) - base._audit.AUDIT_TABLES))
    old, new = base._audit._audit_chain(before, tenant_id), base._audit._audit_chain(after, tenant_id)
    require(len(new) >= len(old) and [raw for _row, raw in new[:len(old)]] == [raw for _row, raw in old])
    if len(old) == len(new):
        require(before["domain_audit_ledger_state"] == after["domain_audit_ledger_state"])
    for row, _raw in new[len(old):]:
        _policy_append(row, after)
    return {"business_tables": 77, "business_original_rows_equal": True, "audit_original_prefix_equal": True,
            "audit_chain_valid": True, "audit_actions_bound": True, "appended_audit_events": len(new) - len(old)}


def verify_raw_observations(packet: dict[str, Any], observations: dict[str, Any]) -> dict[str, Any]:
    identity = ("tenant_id", "original_source_order_id", "resale_source_order_id")
    require(type(observations) is dict and set(observations) == {"schema_version", *identity, "observations"}
            and observations["schema_version"] == "customer-partial-return-restituted-observations-input-v1"
            and all(observations[key] == packet[key] for key in identity) and type(observations["observations"]) is list and len(observations["observations"]) == 3)
    final = packet["captures"][-1]["tables"]
    rows = base._rows(base._originals(final, packet["tenant_id"]))
    old = base._one(rows["customer_partial_return_plans"], source_order_id=packet["original_source_order_id"])
    new = base._one(rows["customer_partial_return_plans"], source_order_id=packet["resale_source_order_id"])
    previous = final
    appended = 0
    for value, kind, plan in zip(observations["observations"], ("RetainedReplay", "DependencyRefusal", "FinalRead"), (new, old, new), strict=True):
        require(type(value) is dict and set(value) == {"schema_version", *identity, "kind", "posted_plan_id", "plan_digest", "tables", "refusal"}
                and value["schema_version"] == "customer-partial-return-restituted-browser-observation-v1" and value["kind"] == kind
                and all(value[key] == packet[key] for key in identity) and value["posted_plan_id"] == plan["id"] and value["plan_digest"] == plan["plan_digest"])
        if kind == "DependencyRefusal":
            refusal = value["refusal"]
            require(type(refusal) is dict and set(refusal) == {"method", "route", "status", "code"}
                    and refusal["method"] == "POST" and type(refusal["status"]) is int and refusal["status"] == 409
                    and refusal["code"] == "customer_partial_return_reversal_dependency"
                    and refusal["route"] == "/api/v2/customer-partial-returns/plans/" + old["id"] + "/reversals")
        else:
            require(value["refusal"] is None)
        result = verify_audit_only_transition(previous, value["tables"], tenant_id=packet["tenant_id"])
        if kind != "FinalRead":
            old_chain = base._audit._audit_chain(base._originals(previous, packet["tenant_id"]), packet["tenant_id"])
            new_chain = base._audit._audit_chain(base._originals(value["tables"], packet["tenant_id"]), packet["tenant_id"])
            surface = "POST /api/v2/customer-partial-returns/plans/" + plan["id"] + ("/post" if kind == "RetainedReplay" else "/reversals")
            expected_digest = base._audit._text_digest("audit.surface", surface)
            require(any(row["metadata_json"]["policy_decision_evidence"]["surface_digest"] == expected_digest for row, _raw in new_chain[len(old_chain):]))
        appended += result["appended_audit_events"]
        previous = value["tables"]
    return {"observations": 3, "observation_tables": 79, "observation_business_tables": 77, "observation_chronology_bound": True,
            "audit_actions_bound": True, "audit_chain_valid": True, "audit_original_prefix_equal": True, "business_original_rows_equal": True,
            "appended_audit_events": appended, "dependency_refusal_http_proven": True}


def verify_restored_cycle(packet: dict[str, Any], restored: dict[str, Any], observations: dict[str, Any]) -> dict[str, Any]:
    verify_raw_observations(packet, observations)
    identity = ("tenant_id", "original_source_order_id", "resale_source_order_id")
    require(type(restored) is dict and set(restored) == {"schema_version", *identity, "tables"}
            and restored["schema_version"] == "customer-partial-return-restituted-restored-input-v1"
            and all(restored[key] == packet[key] for key in identity))
    target = base._originals(observations["observations"][-1]["tables"], packet["tenant_id"])
    actual = base._originals(restored["tables"], packet["tenant_id"])
    require(target == actual)
    return {"populated_restore_proven": True, "restored_tables": 79, "restored_rows": sum(len(rows) for rows in actual.values()), "restore_target_final_observation": True}


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Verify private four-checkpoint restituted native originals.")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--observations-input", type=Path)
    parser.add_argument("--restore-input", type=Path)
    args = parser.parse_args()
    try:
        require(not args.output.exists() and args.input.resolve() != args.output.resolve() and args.input.stat().st_size <= 64 * 1024 * 1024)
        original = args.input.read_bytes()
        packet = base._audit.decode_row(original.decode("utf-8"), maximum_bytes=64 * 1024 * 1024)
        proof = qualify_raw_cycle(packet)
        inputs = {"input": hashlib.sha256(original).hexdigest()}
        optional = {}
        for name in ("observations_input", "restore_input"):
            path = getattr(args, name)
            if path is not None:
                require(path.resolve() != args.output.resolve() and path.stat().st_size <= 64 * 1024 * 1024)
                value = path.read_bytes()
                optional[name] = base._audit.decode_row(value.decode("utf-8"), maximum_bytes=64 * 1024 * 1024)
                inputs[name] = hashlib.sha256(value).hexdigest()
        if "observations_input" in optional:
            proof.update(verify_raw_observations(packet, optional["observations_input"]))
        if "restore_input" in optional:
            require("observations_input" in optional)
            proof.update(verify_restored_cycle(packet, optional["restore_input"], optional["observations_input"]))
        proof["input_sha256"] = inputs
        proof["reader_source_sha256"] = {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() for name in (
            Path(__file__).name, "customer_partial_return_restituted_source_oracle.py", "customer_partial_return_remainder_posted_oracle.py",
            "customer_partial_return_remainder_oracle.py", "customer_partial_return_posted_cycle_oracle.py")}
        with args.output.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(proof, stream, sort_keys=True, separators=(",", ":"))
            stream.write("\n")
        return 0
    except (ValueError, TypeError, KeyError, IndexError, OverflowError, OSError, RecursionError):
        print("Independent restituted financial verification refused.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
