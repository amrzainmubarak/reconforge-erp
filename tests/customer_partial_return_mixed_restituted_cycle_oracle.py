"""Independent finite mixed zero/positive original-cost raw-row reader.

Only the declared synthetic two-layer scenario is admitted. This is neither a
general source engine nor independent proof of current native authorization.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import stat
import sys
from pathlib import Path
from typing import Any

PINS = {
    "customer_partial_return_restituted_cycle_oracle.py": "fe2ede4c586014f1d63fc4ae639ea28c19740bdf21139f33ee7a7d7402459c35",
    "customer_partial_return_restituted_source_oracle.py": "77689aeb529ebc886a658120e824f5842f07e1c6e9fb302f5836356962f7bd40",
    "customer_partial_return_remainder_posted_oracle.py": "833b37ff15666b53504aea41c244d55ada3169df97f7f72bf7783d224b6e9c8d",
    "customer_partial_return_remainder_oracle.py": "e47d3900bb50e77bc4186eb91a5556fa495fdbb4c07cb408f5e89ac20f545510",
    "customer_partial_return_posted_cycle_oracle.py": "be85ca58d3dec5873527ae9654f9208c87b6a61e171cd2215b9d2da97346544e",
}
for _name, _sha in PINS.items():
    if hashlib.sha256(Path(__file__).with_name(_name).read_bytes()).hexdigest() != _sha:
        raise ValueError("Independent mixed-reader source pin refused.")
_spec = importlib.util.spec_from_file_location("_mixed_original_core", Path(__file__).with_name("customer_partial_return_restituted_cycle_oracle.py"))
if _spec is None or _spec.loader is None:
    raise ValueError("Independent mixed-reader dependency refused.")
core = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(core)
base = core.base
TABLES = core.TABLES
CHECKPOINTS = ("Original", "MixedResaleInvoiced", "MixedZeroCostReturned", "MixedPositiveCostReturned")
FINAL_BALANCES = {"INVENTORY": 10, "CLEARING": -11, "COGS": 1, "AR": 1, "REVENUE": -1, "CASH": 0, "REFUND": 0}
require, integer = core.require, core.integer


def _entry_vector(rows: dict[str, list[dict[str, Any]]], entry_id: str) -> list[tuple[str, int, int]]:
    accounts = {row["id"]: row["account_code"] for row in rows["finance_accounts"]}
    return [(accounts[row["account_id"]], integer(row["debit_minor"]), integer(row["credit_minor"]))
            for row in sorted((row for row in rows["finance_entry_lines"] if row["entry_id"] == entry_id), key=lambda row: integer(row["line_number"]))]


def _typed_effect(value: dict[str, Any], effect: dict[str, Any], scope: dict[str, Any]) -> None:
    require(set(value) == {"posting_effect_id", "validation_digest", "scope", "snapshot_json"}
            and value["posting_effect_id"] == effect["id"] and value["validation_digest"] == effect["validation_digest"]
            and value["scope"] == scope and type(value["snapshot_json"]) is str
            and base._audit.decode_row(value["snapshot_json"]) == effect["snapshot_json"])


def _mixed_original(rows: dict[str, list[dict[str, Any]]], source: dict[str, Any], stock: dict[str, Any], old_source: dict[str, Any]) -> list[dict[str, Any]]:
    payload = source["source_payload"]
    proof = payload["original_source"]["cost_admission"]
    require(set(proof) == {"schema_version", "stock_order_id", "issue_plan", "valuation_document", "valuation_lines", "consumptions", "posting_effect"}
            and proof["schema_version"] == "stock-sales-restituted-cost-v1" and proof["stock_order_id"] == stock["id"]
            and proof["issue_plan"] == stock["issue_plan"] and payload["allocation_policy"] == "remaining-original-v1")
    issue = stock["issue_plan"]
    require(issue["schema_version"] == "stock-sales-issue-v2" and issue["cost_admission_policy"] == "partial-return-restituted-v1"
            and integer(issue["total_cost_minor"]) == 10 and integer(stock["quantity_scaled"]) == 2 and integer(stock["quantity_precision"]) == 1
            and stock["status"] == "Invoiced" and integer(stock["total_minor"]) == 200 and stock["source"]["net_unit_price_minor"] == 1000)
    invoice = base._one(rows["ar_invoices"], id=stock["invoice_id"])
    require(integer(invoice["total_minor"]) == 200 and integer(invoice["tax_minor"]) == 0 and source["invoice_id"] == invoice["id"])
    effect = base._one(rows["finance_posting_effects"], id=stock["cogs_effect_id"])
    require(effect == proof["posting_effect"] and effect["entry_id"] == stock["cogs_entry_id"] == issue["entry_id"]
            and effect["source_kind"] == "Manual" and effect["purpose"] == "operational_posting"
            and effect["source_id"] == effect["entry_id"] and source["original_cogs_effect_id"] == effect["id"])
    cogs_entry = base._one(rows["finance_entries"], id=effect["entry_id"])
    require(cogs_entry["source_type"] == "Manual" and cogs_entry["external_reference"] == stock["id"] and cogs_entry["reverses_posting_id"] is None
            and effect["snapshot_json"]["entry"]["external_reference"] == stock["id"])
    require(_entry_vector(rows, effect["entry_id"]) == [("COGS", 10, 0), ("INVENTORY", 0, 10)])
    valuation = base._one(rows["inventory_valuation_documents"], id=stock["valuation_id"])
    lines = sorted((row for row in rows["inventory_valuation_lines"] if row["valuation_document_id"] == valuation["id"]), key=lambda row: integer(row["line_number"]))
    require(valuation == proof["valuation_document"] and valuation["status"] == "Approved" and integer(valuation["total_value_minor"]) == 10
            and valuation["finance_entry_id"] == effect["entry_id"] and lines == proof["valuation_lines"] and len(lines) == 1)
    selected = [row for row in rows["inventory_layer_consumptions"] if row["valuation_line_id"] == lines[0]["id"]]
    require(len(issue["allocations"]) == len(selected) == 2)
    consumed = [base._one(selected, cost_layer_id=part["cost_layer_id"]) for part in issue["allocations"]]
    require(len({row["cost_layer_id"] for row in consumed}) == 2 and len(proof["consumptions"]) == 2
            and {row["id"]: row for row in consumed} == {row["id"]: row for row in proof["consumptions"]})
    require([(integer(line["quantity_scaled"]), integer(line["value_minor"]), line["flow_direction"]) for line in lines] == [(2, 10, "Outbound")])
    require([(integer(row["quantity_scaled"]), integer(row["value_minor"])) for row in consumed] == [(1, 0), (1, 10)])
    require([(part["cost_layer_id"], integer(part["quantity_scaled"]), integer(part["value_minor"])) for part in issue["allocations"]]
            == [(row["cost_layer_id"], 1, value) for row, value in zip(consumed, (0, 10), strict=True)])
    snapshot = issue["restitution_cost_snapshot"]
    policy = issue["currency_policy"]
    captured_policy = {"currency_code": policy["currency_code"], "currency_precision": policy["precision"], "currency_rounding_policy": policy["rounding_policy"],
                       "currency_registry_version": policy["registry_version"], "currency_registry_digest": policy["registry_digest"]}
    require(set(snapshot) == {"schema_version", "monetary_policy", "remaining_quantity_scaled", "remaining_value_minor", "sources"}
            and snapshot["schema_version"] == "inventory-transfer-cost-v3" and snapshot["monetary_policy"] == captured_policy
            and integer(snapshot["remaining_quantity_scaled"]) == 2 and integer(snapshot["remaining_value_minor"]) == 10 and len(snapshot["sources"]) == 2)
    for consumption, value in zip(consumed, (0, 10), strict=True):
        candidates = [part for part in snapshot["sources"] if part["layer"]["id"] == consumption["cost_layer_id"]]
        require(len(candidates) == 1)
        captured = candidates[0]
        layer = base._one(rows["inventory_cost_layers"], id=consumption["cost_layer_id"])
        require(integer(layer["row_version"]) == integer(captured["layer"]["row_version"]) + 1
                and captured["layer"] == {**layer, "remaining_quantity_scaled": 1, "remaining_value_minor": value, "row_version": layer["row_version"] - 1})
        originals = [row for row in rows["inventory_layer_consumptions"] if row["cost_layer_id"] == layer["id"] and row["id"] != consumption["id"]]
        require({row["id"]: row for row in captured["consumptions"]} == {row["id"]: row for row in originals})
        corrections = captured.get("partial_return_corrections", [])
        if value:
            require(corrections == [])
        else:
            require(len(corrections) == 1)
            correction = corrections[0]
            restoration = base._one(rows["customer_partial_return_restorations"], source_id=old_source["id"])
            old_plan = base._one(rows["customer_partial_return_plans"], id=restoration["plan_id"])
            require(set(correction) == {"restoration", "source", "plan", "entry", "effect", "lines", "dimensions", "physical", "history_sequence", "allocation_policy", "allocation_witness"}
                    and correction["restoration"] == restoration
                    and correction["source"] == {key: old_source[key] for key in ("id", "source_fingerprint", "workspace_id", "organization_id", "legal_entity_id", "item_id", "uom_id", "quantity_precision", "location_id", "original_cogs_effect_id")}
                    and correction["plan"] == {key: old_plan[key] for key in ("id", "source_id", "operation", "phase", "plan_digest", "cogs_restored_minor")}
                    and correction["entry"] is correction["effect"] is None and correction["lines"] == correction["dimensions"] == []
                    and correction["allocation_policy"] == "remaining-original-v1" and integer(correction["history_sequence"]) == 1
                    and set(correction["allocation_witness"]) == {"before_quantity_scaled", "before_value_minor"}
                    and tuple(integer(correction["allocation_witness"][key]) for key in ("before_quantity_scaled", "before_value_minor")) == (3, 1))
            native = correction["physical"]
            movement = base._one(rows["inventory_movements"], id=restoration["physical_movement_id"])
            require(set(native) == {"head", "lines", "audit", "outbox"} and native["head"] == movement
                    and native["lines"] == [row for row in rows["inventory_movement_lines"] if row["movement_id"] == movement["id"]]
                    and native["audit"] and all(row in rows["domain_audit_events"] for row in native["audit"]) and native["outbox"])
            for event in native["outbox"]:
                retained = base._one(rows["outbox_events"], event_id=event["event_id"])
                require(set(event) == core.factual.OUTBOX_FIELDS and event == {key: retained[key] for key in core.factual.OUTBOX_FIELDS})
    typed, fingerprint = payload["typed_source"], payload["fingerprint_payload"]
    scope = {key: stock[key] for key in ("tenant_id", "workspace_id", "organization_id", "legal_entity_id", "item_id", "uom_id", "location_id")}
    _typed_effect(typed["original_cogs"], effect, scope)
    require(typed["original_cost_admission"] == {"evidence_digest": base._digest(proof)}
            and typed["scope"] == fingerprint["scope"] == scope
            and fingerprint["contract"] == "customer-partial-return-original-v2"
            and fingerprint["original_cost_admission"] == ["stock-sales-restituted-cost-v1", base._digest(proof)]
            and fingerprint["original_cogs"] == [effect["id"], effect["validation_digest"]]
            and source["source_fingerprint"] == base._digest(fingerprint))
    require(tuple(integer(source[key]) for key in ("original_quantity_scaled", "gross_minor", "initial_collected_minor")) == (2, 200, 0)
            and (fingerprint["source_order_id"], fingerprint["invoice_id"], integer(fingerprint["quantity_scaled"]), integer(fingerprint["gross_minor"])) == (stock["id"], invoice["id"], 2, 200))
    require([(row["consumption_id"], row["valuation_line_id"], row["cost_layer_id"], integer(row["quantity_scaled"]), integer(row["value_minor"])) for row in fingerprint["consumptions"]]
            == [(row["id"], row["valuation_line_id"], row["cost_layer_id"], 1, value) for row, value in zip(consumed, (0, 10), strict=True)])
    for row in (stock, invoice, valuation, source):
        require(all(row[key] == old_source[key] for key in ("tenant_id", "workspace_id", "organization_id", "legal_entity_id")))
    require(all(source[key] == stock[key] == old_source[key] for key in ("item_id", "uom_id", "location_id")))
    require(all(captured_policy[key] == old_source[key] for key in captured_policy))
    return consumed


def qualify_raw_cycle(packet: dict[str, Any]) -> dict[str, Any]:
    require(type(packet) is dict and set(packet) == {"schema_version", "tenant_id", "original_source_order_id", "resale_source_order_id", "captures"}
            and packet["schema_version"] == "customer-partial-return-mixed-restituted-cycle-input-v1")
    tenant = base._audit.identity(packet["tenant_id"])
    old_id, resale_id = (base._audit.identity(packet[key]) for key in ("original_source_order_id", "resale_source_order_id"))
    require(old_id != resale_id and type(packet["captures"]) is list and len(packet["captures"]) == 4)
    raw = []
    for capture, label in zip(packet["captures"], CHECKPOINTS, strict=True):
        require(type(capture) is dict and set(capture) == {"checkpoint", "tables"} and capture["checkpoint"] == label)
        raw.append(base._originals(capture["tables"], tenant))
    stages = [base._rows(tables) for tables in raw]
    _birth, old_stock, old_consumed = base._source(stages[0], "zero", old_id)
    require(not stages[0]["customer_partial_return_sources"] and len(old_consumed) == 1)
    old_source = base._one(stages[1]["customer_partial_return_sources"], source_order_id=old_id)
    require(tuple(integer(old_source[key]) for key in ("original_quantity_scaled", "gross_minor", "initial_collected_minor")) == (3, 1, 0)
            and old_source["original_cogs_effect_id"] == old_stock["cogs_effect_id"]
            and old_source["source_fingerprint"] == base._digest(old_source["source_payload"]["fingerprint_payload"]))
    old_plan = core._plan(stages[1], old_source, old_stock, credit=0, consumption=old_consumed[0], before_q=3, before_v=1, before_revenue=1)
    resale = base._one(stages[1]["stock_sales_orders"], id=resale_id)
    source = base._one(stages[2]["customer_partial_return_sources"], source_order_id=resale_id)
    consumed = _mixed_original(stages[1], source, resale, old_source)
    revenue_plan = base._one(stages[1]["operational_finance_plans"], id=resale["invoice_plan_id"])
    revenue_link = base._one(stages[1]["operational_finance_links"], plan_id=revenue_plan["id"])
    revenue = base._one(stages[1]["finance_posting_effects"], id=revenue_link["posting_effect_id"])
    require(revenue_plan["source_kind"] == "ARInvoice" and revenue_plan["source_id"] == resale["invoice_id"] and integer(revenue_plan["amount_minor"]) == 200
            and revenue_plan["entry_id"] == revenue["entry_id"] and revenue_plan["validation_digest"] == revenue["validation_digest"]
            and revenue_link["plan_digest"] == revenue_plan["plan_digest"] and source["original_revenue_effect_id"] == revenue["id"]
            and source["source_payload"]["original_source"]["revenue"] == revenue
            and source["source_payload"]["fingerprint_payload"]["original_revenue"] == [revenue["id"], revenue["validation_digest"]])
    _typed_effect(source["source_payload"]["typed_source"]["original_revenue"], revenue, source["source_payload"]["typed_source"]["scope"])
    require(_entry_vector(stages[1], revenue["entry_id"]) == [("AR", 200, 0), ("REVENUE", 0, 200)])
    for version, value in enumerate((0, 10)):
        before, after = stages[version + 1:version + 3]
        history = sorted((row for row in after["customer_partial_return_history"] if row["source_id"] == source["id"]), key=lambda row: integer(row["sequence"]))
        require(len(history) == version + 1 and [row["sequence"] for row in history] == list(range(1, version + 2)))
        event = history[-1]
        plan = base._one(after["customer_partial_return_plans"], id=event["plan_id"])
        payload = plan["payload"]
        require(event["kind"] == plan["operation"] == "Return" and plan["phase"] == 2 and type(plan["phase"]) is int
                and integer(plan["expected_history_version"]) == version and payload["schema_version"] == "customer-partial-return-v2"
                and payload["allocation_policy"] == "remaining-original-v1" and plan["source_order_id"] == resale_id
                and plan["source_id"] == source["id"] and payload["plan_digest"] == plan["plan_digest"] == base._digest({key: item for key, item in payload.items() if key != "plan_digest"}))
        require(all(payload[key] == plan[key] for key in ("id", "source_id", "source_order_id", "quantity_scaled", "credit_minor", "cogs_restored_minor", "receivable_released_minor", "refund_entitlement_delta_minor", "amount_minor", "preparer_actor_id")))
        require(tuple(integer(plan[key]) for key in ("quantity_scaled", "credit_minor", "cogs_restored_minor", "receivable_released_minor", "refund_entitlement_delta_minor", "amount_minor")) == (1, 100, value, 100, 0, 100 + value))
        domain = payload["domain_plan"]
        require(domain["source_fingerprint"] == source["source_fingerprint"] and integer(domain["expected_version"]) == version and len(domain["portions"]) == 1)
        part = domain["portions"][0]
        original = consumed[version]
        require((part["original_consumption_id"], part["cost_layer_id"], part["original_valuation_line_id"]) == (original["id"], original["cost_layer_id"], original["valuation_line_id"])
                and tuple(integer(part[key]) for key in ("quantity_scaled", "value_minor", "offset_quantity_scaled", "before_quantity_scaled", "before_value_minor")) == (1, value, 0, 1, value))
        portion = base._model.Portion(original["id"], 0, 1, value, 1, value)
        witness = base._model.ReturnWitness(plan["id"], source["source_fingerprint"], "remaining-original-v1", version, 1, 100, value, 100, 0, 2 - version, 200 - 100 * version, (portion,))
        base._physical(after, resale, plan, witness, False)
        expected: tuple[tuple[str, tuple[tuple[str, int, int], ...]], ...] = (("RevenueCredit", (("REVENUE", 100, 0), ("AR", 0, 100))),)
        if value:
            expected += (("CostRestoration", (("INVENTORY", 10, 0), ("COGS", 0, 10))),)
        base._gl_delta(before, after, plan, expected)
        review = base._one(after["customer_partial_return_events"], plan_id=plan["id"], operation="review")
        post = base._one(after["customer_partial_return_events"], plan_id=plan["id"], operation="post")
        require(len({plan["preparer_actor_id"], review["actor_id"], post["actor_id"]}) == 3)
    balances = ({**core.ACCOUNT_BALANCES}, {**FINAL_BALANCES, "INVENTORY": 0, "COGS": 11, "AR": 201, "REVENUE": -201},
                {**FINAL_BALANCES, "INVENTORY": 0, "COGS": 11, "AR": 101, "REVENUE": -101}, FINAL_BALANCES)
    for index, rows in enumerate(stages):
        effects, count, turnover, observed = core._ledger(rows, old_source)
        require((effects, count, turnover) == ((3, 6, 3), (6, 12, 223), (7, 14, 323), (9, 18, 433))[index] and observed == balances[index])
        require(base._one(rows["stock_sales_orders"], id=old_id) == old_stock)
        audit = base._audit._audit_chain(raw[index], tenant)
        if index:
            previous = base._audit._audit_chain(raw[index - 1], tenant)
            require([text for row, text in audit[:len(previous)]] == [text for row, text in previous])
            core._unchanged_rows(raw[index - 1], raw[index], ("finance_posting_effects", "finance_entry_lines", "finance_entry_line_dimensions", "inventory_layer_consumptions"))
            for previous_effect in stages[index - 1]["finance_posting_effects"]:
                require(base._one(rows["finance_entries"], id=previous_effect["entry_id"]) == base._one(stages[index - 1]["finance_entries"], id=previous_effect["entry_id"]))
            require(base._one(rows["customer_partial_return_sources"], id=old_source["id"]) == old_source and base._one(rows["customer_partial_return_plans"], id=old_plan["id"]) == old_plan)
            require(base._one(rows["stock_sales_orders"], id=resale_id) == resale)
            for position, original in enumerate(consumed):
                layer = base._one(rows["inventory_cost_layers"], id=original["cost_layer_id"])
                restored = index >= position + 2
                require((integer(layer["remaining_quantity_scaled"]), integer(layer["remaining_value_minor"]))
                        == ((1, 10 * position) if restored else (0, 0)))
                original_layer = base._one(stages[1]["inventory_cost_layers"], id=layer["id"])
                require(all(layer[key] == original_layer[key] for key in ("original_quantity_scaled", "original_value_minor", "source_valuation_line_id")))
        if index >= 2:
            require(base._one(rows["customer_partial_return_sources"], id=source["id"]) == source)
    require(len(stages[-1]["customer_partial_return_sources"]) == 2 and len(stages[-1]["customer_partial_return_plans"]) == 3
            and len(stages[-1]["inventory_cost_layers"]) == 2 and sum(integer(row["remaining_quantity_scaled"]) for row in stages[-1]["inventory_cost_layers"]) == 2
            and sum(integer(row["remaining_value_minor"]) for row in stages[-1]["inventory_cost_layers"]) == 10)
    return {"schema_version": "independent-mixed-restituted-cycle-proof-v1", "status": "passed", "checkpoints": 4, "tables": 79, "sources": 2,
            "original_consumption_costs_minor": [0, 10], "original_real_cogs_minor": 10, "new_return_credit_minor": [100, 100], "new_return_cost_minor": [0, 10],
            "final_posting_effects": 9, "final_posted_lines": 18, "final_debits_minor": 433, "final_credits_minor": 433, "final_account_minor_balances": FINAL_BALANCES,
            "explicit_original_cost_admission": True, "no_fake_zero_financial_entries": True, "all_financial_scope_currency_pins": True,
            "current_authorization_proven": False, "browser_execution_proven": False, "populated_restore_proven": False, "benchmark": False}


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        require(args.input.is_absolute() and args.output.is_absolute() and ".." not in args.input.parts and ".." not in args.output.parts)
        for path in (args.input, args.output, *args.input.parents, *args.output.parents):
            require(not path.is_symlink() and not getattr(path, "is_junction", lambda: False)())
            if path.exists():
                require(not getattr(path.lstat(), "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)
        require(not args.output.exists() and args.input.resolve() != args.output.resolve())
        before = args.input.stat()
        def stable(info: Any) -> tuple[int, int, int, int]:
            return info.st_size, info.st_mtime_ns, info.st_dev, info.st_ino
        require(stat.S_ISREG(before.st_mode) and before.st_size <= 64 * 1024 * 1024)
        with args.input.open("rb") as stream:
            data = stream.read(64 * 1024 * 1024 + 1)
        require(len(data) <= 64 * 1024 * 1024 and stable(args.input.stat()) == stable(before))
        proof = qualify_raw_cycle(base._audit.decode_row(data.decode(), maximum_bytes=64 * 1024 * 1024))
        proof["input_sha256"] = hashlib.sha256(data).hexdigest()
        proof["reader_source_sha256"] = {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() for name in (Path(__file__).name, *PINS)}
        with args.input.open("rb") as stream:
            retained = stream.read(64 * 1024 * 1024 + 1)
        require(retained == data and stable(args.input.stat()) == stable(before))
        with args.output.open("x", encoding="utf8", newline="\n") as stream:
            json.dump(proof, stream, sort_keys=True, separators=(",", ":"))
            stream.write("\n")
        return 0
    except (ValueError, TypeError, KeyError, IndexError, StopIteration, OSError, OverflowError, RecursionError):
        print("Independent mixed-restituted financial verification refused.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
