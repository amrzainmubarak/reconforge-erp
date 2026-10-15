"""Literal synthetic four-stage controls, never native execution evidence."""
from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from tests import customer_partial_return_restituted_cycle_oracle as reader
from tests.test_customer_partial_return_posted_cycle_oracle import policy_event, seal_audit, set_audits
from tests.test_customer_partial_return_restituted_source_oracle import fixture as factual_fixture


def raw(rows: dict[str, list[dict[str, Any]]]) -> dict[str, list[str]]:
    return {name: sorted(json.dumps(row, sort_keys=True) for row in values) for name, values in rows.items()}


def add_gl(rows: dict[str, list[dict[str, Any]]], number: str, lines: tuple[tuple[str, int, int], ...]) -> dict[str, Any]:
    header = {"tenant_id": "tenant", "id": number, "entry_number": number, "workspace_id": "work", "journal_id": "journal", "period_id": "period",
              "currency_code": "USD", "currency_precision": 2, "currency_rounding_policy": "ROUND_HALF_UP", "currency_registry_version": "captured",
              "currency_registry_digest": "d" * 64, "preparer_actor_id": "maker", "source_type": "Manual", "external_reference": number,
              "reverses_posting_id": None, "status": "Validated", "total_debit_minor": sum(d for _, d, _c in lines), "total_credit_minor": sum(c for _, _d, c in lines)}
    sealed = {"entry": {key: value for key, value in header.items() if key not in {"tenant_id", "status", "total_debit_minor", "total_credit_minor"}},
              "schema_version": "finance-entry-review-v1", "lines": []}
    for index, (code, debit, credit) in enumerate(lines, 1):
        row = {"tenant_id": "tenant", "id": number + "-line-" + str(index), "entry_id": number, "line_number": index,
               "account_id": code, "debit_minor": debit, "credit_minor": credit}
        rows["finance_entry_lines"].append(row)
        sealed["lines"].append({key: value for key, value in row.items() if key not in {"tenant_id", "id", "entry_id"}} | {"dimensions": {}})
    digest = reader.base._digest(sealed)
    header["validation_digest"] = digest
    rows["finance_entries"].append(header)
    rows["finance_posting_effects"].append({"tenant_id": "tenant", "id": number + "-effect", "entry_id": number, "snapshot_json": sealed, "validation_digest": digest})
    return {"entry_id": number, "purpose": "RevenueCredit", "snapshot": sealed, "validation_digest": digest}


def seal_plan(plan: dict[str, Any]) -> None:
    payload = plan["payload"]
    payload.update({key: plan[key] for key in ("id", "source_id", "source_order_id", "quantity_scaled", "credit_minor", "cogs_restored_minor",
                                              "receivable_released_minor", "refund_entitlement_delta_minor", "amount_minor", "preparer_actor_id")})
    payload.pop("plan_digest", None)
    plan["plan_digest"] = payload["plan_digest"] = reader.base._digest(payload)


def fixture() -> dict[str, Any]:
    prior, issued, source = factual_fixture()
    prior = {name: copy.deepcopy(prior.get(name, [])) for name in reader.TABLES}
    scope = {"tenant_id": "tenant", "workspace_id": "work", "organization_id": "org", "legal_entity_id": "entity"}
    stock = {**scope, "id": "old-stock", "invoice_id": "old-invoice", "valuation_id": "old-valuation", "quantity_scaled": 3, "quantity_precision": 1,
             "cogs_entry_id": "old-cogs", "cogs_effect_id": "old-cogs-effect",
             "item_id": "item", "uom_id": "uom", "location_id": "location", "issue_plan": {"schema_version": "stock-sales-issue-v1",
             "allocations": [{"cost_layer_id": "layer", "quantity_scaled": 3, "value_minor": 1}]}}
    prior["stock_sales_orders"] = [stock]
    prior["ar_invoices"] = [{**scope, "id": "old-invoice", "total_minor": 1, "tax_minor": 0}]
    prior["inventory_valuation_lines"] = [{"tenant_id": "tenant", "id": "old-line", "valuation_document_id": "old-valuation"}]
    old_source = prior["customer_partial_return_sources"][0]
    old_source["original_cogs_effect_id"] = "old-cogs-effect"
    old_source.update(original_quantity_scaled=3, gross_minor=1, initial_collected_minor=0)
    fingerprint = {"contract": "customer-partial-return-domain-v1"}
    old_source.update(source_fingerprint=reader.base._digest(fingerprint), source_payload={"allocation_policy": "remaining-original-v1", "typed_source": {}, "fingerprint_payload": fingerprint})
    plan = prior["customer_partial_return_plans"][0]
    plan.update(source_order_id="old-stock", expected_history_version=0, preparer_actor_id="maker", receivable_released_minor=0,
                refund_entitlement_delta_minor=0, amount_minor=0)
    portion = {"original_consumption_id": "old-consumption", "cost_layer_id": "layer", "original_valuation_line_id": "old-line",
               "quantity_scaled": 1, "value_minor": 0, "offset_quantity_scaled": 0, "before_quantity_scaled": 3, "before_value_minor": 1}
    plan["payload"] = {"schema_version": "customer-partial-return-v2", "allocation_policy": "remaining-original-v1", "entries": [], "movement_id": "old-movement",
                       "domain_plan": {"source_fingerprint": old_source["source_fingerprint"], "expected_version": 0, "allocation_policy": "remaining-original-v1",
                                       "revenue_before_quantity_scaled": 3, "revenue_before_value_minor": 1, "portions": [portion]}}
    seal_plan(plan)
    movement = prior["inventory_movements"][0]
    movement.update(source_type="Generated", movement_type="Receipt", movement_number="OLD-PLAN")
    prior["inventory_movement_lines"][0].update(item_id="item", uom_id="uom", quantity_precision=1, from_location_id=None, to_location_id="location")
    prior["customer_partial_return_history"] = [{"tenant_id": "tenant", "source_id": "old-source", "plan_id": "old-plan", "sequence": 1, "kind": "Return"}]
    prior["customer_partial_return_events"] = [{"tenant_id": "tenant", "plan_id": "old-plan", "operation": action, "actor_id": actor}
                                               for action, actor in (("review", "reviewer"), ("post", "poster"))]
    prior["customer_partial_return_restorations"][0].update(offset_quantity_scaled=0, original_valuation_line_id="old-line",
                                                          original_restoration_plan_id=None, consumption_count_at_restore=1)
    event = policy_event(1, "0" * 64)
    event.update(object_type="inventory_movement", action="posted")
    seal_audit(event)
    set_audits(prior, [event])
    for name in ("domain_audit_events", "domain_audit_ledger_state"):
        prior[name] = [json.loads(value) for value in prior[name]]
    prior["finance_accounts"] = [{"tenant_id": "tenant", "id": code, "account_code": code} for code in reader.ACCOUNT_BALANCES]
    for number, lines in (("receipt", (("INVENTORY", 1, 0), ("CLEARING", 0, 1))),
                          ("old-cogs", (("COGS", 1, 0), ("INVENTORY", 0, 1))),
                          ("old-invoice-entry", (("AR", 1, 0), ("REVENUE", 0, 1)))):
        add_gl(prior, number, lines)
    initial = copy.deepcopy(prior)
    for name in ("customer_partial_return_sources", "customer_partial_return_plans", "customer_partial_return_restorations", "customer_partial_return_allocation_witnesses",
                 "customer_partial_return_events", "customer_partial_return_history", "inventory_movements", "inventory_movement_lines", "outbox_events"):
        initial[name] = []
    initial["inventory_cost_layers"][0]["remaining_quantity_scaled"] = 0
    set_audits(initial, [])
    for name in ("domain_audit_events", "domain_audit_ledger_state"):
        initial[name] = [json.loads(value) for value in initial[name]]
    # Rebind every captured factual component to the exact prior originals.
    sale = copy.deepcopy(issued["stock_sales_orders"][0])
    sale.update(item_id="item", uom_id="uom", location_id="location")
    pool = sale["issue_plan"]["restitution_cost_snapshot"]["sources"][0]
    pool["layer"] = copy.deepcopy(prior["inventory_cost_layers"][0])
    correction = pool["partial_return_corrections"][0]
    correction["source"] = {key: old_source[key] for key in ("id", "source_fingerprint", "workspace_id", "organization_id", "legal_entity_id", "item_id", "uom_id", "quantity_precision", "location_id", "original_cogs_effect_id")}
    correction["plan"] = {key: plan[key] for key in ("id", "source_id", "operation", "phase", "plan_digest", "cogs_restored_minor")}
    correction["restoration"] = copy.deepcopy(prior["customer_partial_return_restorations"][0])
    correction["physical"] = {"head": copy.deepcopy(movement), "lines": copy.deepcopy(prior["inventory_movement_lines"]), "audit": [event], "outbox": copy.deepcopy(prior["outbox_events"])}
    second = copy.deepcopy(prior)
    second["stock_sales_orders"].append(sale)
    for name in ("ar_invoices", "inventory_valuation_documents", "inventory_valuation_lines"):
        second[name].extend(copy.deepcopy(issued[name]))
    second["inventory_layer_consumptions"].append(copy.deepcopy(issued["inventory_layer_consumptions"][-1]))
    second["inventory_cost_layers"][0]["remaining_quantity_scaled"] = 0
    add_gl(second, "new-invoice-entry", (("AR", 100, 0), ("REVENUE", 0, 100)))
    source.update(id="new-source", original_quantity_scaled=1, gross_minor=100, initial_collected_minor=0)
    proof = source["source_payload"]["original_source"]["cost_admission"]
    proof["issue_plan"] = copy.deepcopy(sale["issue_plan"])
    digest = reader.base._digest(proof)
    source["source_payload"]["typed_source"]["original_cost_admission"] = {"evidence_digest": digest}
    source["source_payload"]["fingerprint_payload"]["original_cost_admission"] = ["stock-sales-restituted-cost-v1", digest]
    source["source_fingerprint"] = reader.base._digest(source["source_payload"]["fingerprint_payload"])
    final = copy.deepcopy(second)
    final["customer_partial_return_sources"].append(source)
    new_plan = copy.deepcopy(plan)
    new_plan.update(id="new-plan", source_id="new-source", source_order_id="resale", quantity_scaled=1, credit_minor=100, receivable_released_minor=100, amount_minor=100)
    new_plan["payload"].update(movement_id="new-movement", entries=[add_gl(final, "new-credit", (("REVENUE", 100, 0), ("AR", 0, 100)))])
    domain = new_plan["payload"]["domain_plan"]
    domain.update(source_fingerprint=source["source_fingerprint"], revenue_before_quantity_scaled=1, revenue_before_value_minor=100)
    domain["portions"][0].update(original_consumption_id="consumption", original_valuation_line_id="line", before_quantity_scaled=1, before_value_minor=0)
    seal_plan(new_plan)
    final["customer_partial_return_plans"].append(new_plan)
    final["customer_partial_return_history"].append({"tenant_id": "tenant", "source_id": "new-source", "plan_id": "new-plan", "sequence": 1, "kind": "Return"})
    final["customer_partial_return_events"].extend({"tenant_id": "tenant", "plan_id": "new-plan", "operation": action, "actor_id": actor} for action, actor in (("review", "reviewer"), ("post", "poster")))
    final["inventory_movements"].append({**scope, "id": "new-movement", "status": "Posted", "source_reference": "new-plan", "source_type": "Generated", "movement_type": "Receipt", "movement_number": "NEW-PLAN"})
    final["inventory_movement_lines"].append({**copy.deepcopy(prior["inventory_movement_lines"][0]), "movement_id": "new-movement"})
    final["customer_partial_return_restorations"].append({**copy.deepcopy(prior["customer_partial_return_restorations"][0]), "source_id": "new-source", "plan_id": "new-plan",
                                                        "original_consumption_id": "consumption", "original_valuation_line_id": "line", "original_cogs_effect_id": None,
                                                        "physical_movement_id": "new-movement", "consumption_count_at_restore": 2})
    final["customer_partial_return_allocation_witnesses"].append({"tenant_id": "tenant", "plan_id": "new-plan", "position": 1, "before_quantity_scaled": 1, "before_value_minor": 0})
    final["inventory_cost_layers"][0]["remaining_quantity_scaled"] = 1
    return {"schema_version": "customer-partial-return-restituted-cycle-input-v1", "tenant_id": "tenant", "original_source_order_id": "old-stock", "resale_source_order_id": "resale",
            "captures": [{"checkpoint": label, "tables": raw(rows)} for label, rows in zip(reader.CHECKPOINTS, (initial, prior, second, final), strict=True)]}


def test_four_literal_checkpoints_preserve_old_source_and_require_real_new_zero_cost_admission() -> None:
    proof = reader.qualify_raw_cycle(fixture())
    assert (proof["final_actual_posting_effects"], proof["final_actual_posted_lines"], proof["final_debits_minor"], proof["final_credits_minor"]) == (5, 10, 203, 203)
    assert proof["final_account_minor_balances"] == reader.ACCOUNT_BALANCES
    assert proof["old_return_later_immutable_consumption_dependency"] is True
    assert proof["dependency_refusal_http_proven"] is proof["current_authorization_proven"] is proof["populated_restore_proven"] is False


@pytest.mark.parametrize("attack", ["checkpoint", "source-swap", "missing-table", "old-consumption", "resale-value", "later-consumption-witness", "fake-zero-entry", "new-credit", "snapshot-line", "new-original-claim", "old-history", "physical", "witness", "old-audit-prefix"])
def test_resealed_or_structural_counterexamples_cannot_qualify_fourth_cycle(attack: str) -> None:
    value = fixture()
    if attack == "checkpoint":
        value["captures"][2]["checkpoint"] = "ZeroReturn"
    elif attack == "source-swap":
        value["resale_source_order_id"] = value["original_source_order_id"]
    elif attack == "missing-table":
        value["captures"][-1]["tables"].pop("customer_partial_return_allocation_witnesses")
    elif attack == "old-audit-prefix":
        # The successor alone is validly resealed, yet deletes a retained audit.
        set_audits(value["captures"][2]["tables"], [])
    else:
        tables = value["captures"][-1]["tables"]
        name = {"old-consumption": "inventory_layer_consumptions", "resale-value": "inventory_cost_layers", "later-consumption-witness": "customer_partial_return_restorations",
                "fake-zero-entry": "finance_entries", "new-credit": "finance_entry_lines", "snapshot-line": "finance_posting_effects", "new-original-claim": "customer_partial_return_sources",
                "old-history": "customer_partial_return_history", "physical": "inventory_movement_lines", "witness": "customer_partial_return_allocation_witnesses"}[attack]
        rows = [json.loads(row) for row in tables[name]]
        if attack == "old-consumption":
            next(row for row in rows if row["id"] == "old-consumption")["value_minor"] = 2
        elif attack == "resale-value":
            rows[0]["remaining_value_minor"] = 1
        elif attack == "later-consumption-witness":
            next(row for row in rows if row["plan_id"] == "old-plan")["consumption_count_at_restore"] = 2
        elif attack == "fake-zero-entry":
            rows.append({**rows[0], "id": "fake", "total_debit_minor": 0, "total_credit_minor": 0})
        elif attack == "new-credit":
            next(row for row in rows if row["entry_id"] == "new-credit" and row["debit_minor"])["debit_minor"] = 99
        elif attack == "snapshot-line":
            next(row for row in rows if row["entry_id"] == "new-credit")["snapshot_json"]["lines"][0]["debit_minor"] = 99
        elif attack == "new-original-claim":
            next(row for row in rows if row["id"] == "new-source")["source_payload"]["typed_source"]["original_cogs"] = {}
        elif attack == "old-history":
            rows.append({**rows[0], "sequence": 2})
        elif attack == "physical":
            next(row for row in rows if row["movement_id"] == "new-movement")["quantity_scaled"] = 2
        elif attack == "witness":
            next(row for row in rows if row["plan_id"] == "new-plan")["before_value_minor"] = 1
        tables[name] = sorted(json.dumps(row, sort_keys=True) for row in rows)
    with pytest.raises((ValueError, KeyError)):
        reader.qualify_raw_cycle(value)


def test_standalone_isolated_optimized_fourth_reader_is_byte_equal_and_exclusive(tmp_path: Path) -> None:
    source = tmp_path / "original.json"
    source.write_text(json.dumps(fixture()), encoding="utf-8")
    outputs = []
    for mode in (("-I",), ("-I", "-O")):
        output = tmp_path / ("proof" + str(len(outputs)) + ".json")
        result = subprocess.run([sys.executable, *mode, reader.__file__, "--input", str(source), "--output", str(output)], capture_output=True, check=False, timeout=30)
        assert result.returncode == 0 and result.stdout == result.stderr == b""
        outputs.append(output.read_bytes())
    assert outputs[0] == outputs[1]
    result = subprocess.run([sys.executable, "-I", reader.__file__, "--input", str(source), "--output", str(output)], capture_output=True, check=False, timeout=30)
    assert result.returncode == 1 and b"original.json" not in result.stderr


def observations_fixture() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    packet = fixture()
    tables = packet["captures"][-1]["tables"]
    events = sorted((json.loads(value) for value in tables["domain_audit_events"]), key=lambda row: row["sequence"])
    values = []
    for kind, plan, surface, permission in (
        ("RetainedReplay", "new-plan", "POST /api/v2/customer-partial-returns/plans/new-plan/post", "finance_core.post"),
        ("DependencyRefusal", "old-plan", "POST /api/v2/customer-partial-returns/plans/old-plan/reversals", "finance_core.reverse"),
        ("FinalRead", "new-plan", "GET /api/v2/customer-partial-returns/plans", "finance_core.read"),
    ):
        events.append(policy_event(len(events) + 1, events[-1]["event_hash"], surface=surface, permission=permission))
        observed = copy.deepcopy(tables)
        set_audits(observed, copy.deepcopy(events))
        digest = next(json.loads(raw)["plan_digest"] for raw in tables["customer_partial_return_plans"] if json.loads(raw)["id"] == plan)
        values.append({"schema_version": "customer-partial-return-restituted-browser-observation-v1", "tenant_id": "tenant", "original_source_order_id": "old-stock", "resale_source_order_id": "resale",
                       "kind": kind, "posted_plan_id": plan, "plan_digest": digest, "tables": observed,
                       "refusal": {"method": "POST", "route": "/api/v2/customer-partial-returns/plans/old-plan/reversals", "status": 409,
                                   "code": "customer_partial_return_reversal_dependency"} if kind == "DependencyRefusal" else None})
    observations = {"schema_version": "customer-partial-return-restituted-observations-input-v1", "tenant_id": "tenant", "original_source_order_id": "old-stock", "resale_source_order_id": "resale", "observations": values}
    restored = {"schema_version": "customer-partial-return-restituted-restored-input-v1", "tenant_id": "tenant", "original_source_order_id": "old-stock", "resale_source_order_id": "resale", "tables": copy.deepcopy(values[-1]["tables"])}
    return packet, observations, restored


def test_two_source_replay_actual_refusal_receipt_and_final_restore_bind_full_seventy_nine_tables() -> None:
    packet, observations, restored = observations_fixture()
    proof = reader.verify_raw_observations(packet, observations)
    assert proof["appended_audit_events"] == 3 and proof["dependency_refusal_http_proven"] is True
    assert reader.verify_restored_cycle(packet, restored, observations)["restored_tables"] == 79
    assert reader.verify_restored_cycle(packet, restored, observations)["populated_restore_proven"] is True


@pytest.mark.parametrize("attack", ["sequence", "kind", "source", "parent", "status", "code", "route", "refusal-on-replay", "financial-delta", "audit-mutation", "audit-gap", "forged-head", "unrelated-action", "unrelated-surface", "wrong-permission", "unknown-actor", "missing-request-affinity", "old-restore-target"])
def test_fourth_observation_receipts_do_not_replace_actual_business_or_audit_originals(attack: str) -> None:
    packet, observations, restored = observations_fixture()
    value = observations["observations"][1]
    if attack == "sequence":
        observations["observations"].reverse()
    elif attack == "kind":
        value["kind"] = "FinalRead"
    elif attack == "source":
        value["original_source_order_id"] = "foreign"
    elif attack == "parent":
        value["posted_plan_id"] = "new-plan"
    elif attack in {"status", "code", "route"}:
        value["refusal"][attack] = {"status": 403, "code": "operational_actor_denied", "route": "/api/v2/customer-partial-returns/plans/new-plan/reversals"}[attack]
    elif attack == "refusal-on-replay":
        observations["observations"][0]["refusal"] = copy.deepcopy(value["refusal"])
    elif attack == "financial-delta":
        value["tables"]["customer_partial_return_allocation_witnesses"] = []
    elif attack == "forged-head":
        head = json.loads(value["tables"]["domain_audit_ledger_state"][0])
        head["last_event_hash"] = "e" * 64
        value["tables"]["domain_audit_ledger_state"] = [json.dumps(head)]
    elif attack == "old-restore-target":
        restored["tables"] = copy.deepcopy(packet["captures"][-1]["tables"])
    else:
        events = sorted((json.loads(raw) for raw in value["tables"]["domain_audit_events"]), key=lambda row: row["sequence"])
        if attack == "audit-mutation":
            events[0]["actor_label"] = "mutated-original"
        elif attack == "audit-gap":
            events[-1]["sequence"] = 5
        elif attack == "unrelated-action":
            events[-1]["action"] = "approved"
        else:
            events[-1] = policy_event(3, events[-2]["event_hash"], surface="POST /api/v1/admin/access/roles" if attack == "unrelated-surface" else
                                     "GET /api/v2/customer-partial-returns/plans" if attack == "missing-request-affinity" else "POST /api/v2/customer-partial-returns/plans/old-plan/reversals",
                                     permission="users.manage" if attack == "wrong-permission" else "finance_core.reverse",
                                     actor="foreign" if attack == "unknown-actor" else "poster")
        seal_audit(events[-1])
        set_audits(value["tables"], events)
    with pytest.raises(ValueError):
        reader.verify_restored_cycle(packet, restored, observations)


def test_real_isolated_fourth_cli_checks_observations_and_populated_final_restore(tmp_path: Path) -> None:
    packet, observations, restored = observations_fixture()
    paths = []
    for name, value in (("input", packet), ("observations", observations), ("restore", restored)):
        path = tmp_path / (name + ".json")
        path.write_text(json.dumps(value), encoding="utf-8")
        paths.append(path)
    results = []
    for index, mode in enumerate((("-I",), ("-I", "-O"))):
        output = tmp_path / (str(index) + ".json")
        result = subprocess.run([sys.executable, *mode, reader.__file__, "--input", str(paths[0]), "--observations-input", str(paths[1]),
                                 "--restore-input", str(paths[2]), "--output", str(output)], capture_output=True, check=False, timeout=30)
        assert result.returncode == 0 and result.stdout == result.stderr == b""
        results.append(output.read_bytes())
    assert results[0] == results[1]
    proof = json.loads(results[0])
    assert proof["dependency_refusal_http_proven"] and proof["populated_restore_proven"]
    assert proof["current_authorization_proven"] is False and len(proof["reader_source_sha256"]) == 5
