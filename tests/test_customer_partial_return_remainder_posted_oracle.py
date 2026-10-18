"""Synthetic raw-adapter controls; these never qualify a native/browser run."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from tests import customer_partial_return_remainder_posted_oracle as reader
from tests.test_customer_partial_return_posted_cycle_oracle import audit_capture, policy_event, seal_audit, set_audits


def raw(rows: dict[str, list[dict[str, Any]]]) -> dict[str, list[str]]:
    return {name: sorted(json.dumps(row, sort_keys=True) for row in values) for name, values in rows.items()}


def fixture(case: str) -> dict[str, Any]:
    q, gross, cost, paid, precision = {
        "ordinary": (3, 3000, 1001, 0, 0),
        "zero": (3, 1, 1, 0, 1),
        "refund": (10, 45000, 12000, 10000, 0),
    }[case]
    tables: dict[str, list[dict[str, Any]]] = {name: [] for name in reader.TABLES}

    def add(name: str, **fields: Any) -> dict[str, Any]:
        row = {"tenant_id": "tenant", **fields}
        tables[name].append(row)
        return row

    stock = add(
        "stock_sales_orders",
        id="stock",
        invoice_id="invoice",
        valuation_id="valuation",
        quantity_scaled=q,
        quantity_precision=precision,
        item_id="item",
        uom_id="uom",
        location_id="location",
        issue_plan={
            "schema_version": "stock-sales-issue-v1",
            "allocations": [{"cost_layer_id": "layer", "quantity_scaled": q, "value_minor": cost}],
        },
    )
    add("ar_invoices", id="invoice", total_minor=gross, tax_minor=0)
    if paid:
        add("ar_receipt_allocations", invoice_id="invoice", amount_minor=paid)
    add("inventory_valuation_lines", id="valuation-line", valuation_document_id="valuation")
    add(
        "inventory_layer_consumptions",
        id="consumption",
        cost_layer_id="layer",
        valuation_line_id="valuation-line",
        quantity_scaled=q,
        value_minor=cost,
    )
    layer = add("inventory_cost_layers", id="layer", remaining_quantity_scaled=0, remaining_value_minor=0)
    for code in ("AR", "REVENUE", "INVENTORY", "COGS", "REFUND", "CASH"):
        add("finance_accounts", id=code, account_code=code)
    captures = [
        {
            "schema_version": "customer-partial-return-remainder-browser-capture-v1",
            "tenant_id": "tenant",
            "source_order_id": "stock",
            "history_version": 0,
            "posted_plan_id": None,
            "plan_digest": None,
            "tables": raw(tables),
        }
    ]
    fingerprint = {"contract": "synthetic-original-positive-v1"}
    source = {
        "id": "source",
        "source_order_id": "stock",
        "original_quantity_scaled": q,
        "gross_minor": gross,
        "initial_collected_minor": paid,
        "source_fingerprint": reader._digest(fingerprint),
        "source_payload": {
            "allocation_policy": "remaining-original-v1",
            "typed_source": {},
            "fingerprint_payload": fingerprint,
        },
    }
    add("customer_partial_return_sources", **source)
    # Literal independently calculated cuts: before revenueQ/V, before costQ/V,
    # selectedQ, credit, cost, releasedAR, liability delta, parent sequence.
    vectors = {
        "ordinary": [
            (3, 3000, 3, 1001, 1, 1000, 334, 1000, 0, None),
            (2, 2000, 2, 667, 1, 1000, 334, 1000, 0, None),
            (1, 1000, 1, 333, 1, 1000, 333, 1000, 0, None),
        ],
        "zero": [
            (3, 1, 3, 1, 1, 0, 0, 0, 0, None),
            (3, 1, 3, 1, 1, 0, 0, 0, 0, 1),
            (3, 1, 3, 1, 1, 0, 0, 0, 0, None),
            (2, 1, 2, 1, 1, 1, 0, 1, 0, None),
            (1, 0, 1, 1, 1, 0, 1, 0, 0, None),
            (1, 0, 1, 1, 1, 0, 1, 0, 0, 5),
            (1, 0, 1, 1, 1, 0, 1, 0, 0, None),
        ],
        "refund": [
            (10, 45000, 10, 12000, 8, 36000, 9600, 35000, 1000, None),
            (2, 9000, 2, 2400, 2, 9000, 2400, 0, 9000, None),
            (0, 0, 0, 0, 0, 0, 0, 0, 0, 2),
            (0, 0, 0, 0, 0, 0, 0, 0, 0, 2),
            (0, 0, 0, 0, 0, 0, 0, 0, 0, 4),
            (0, 0, 0, 0, 0, 0, 0, 0, 0, 2),
        ],
    }[case]
    returned_q = returned_v = 0
    for index, (operation, vector) in enumerate(zip(reader.CASE_EVENTS[case], vectors, strict=True), 1):
        revenue_q, revenue_v, cost_q, cost_v, take, credit, value, release, liability, parent = vector
        identifier = "plan-" + str(index)
        payload: dict[str, Any] = {
            "schema_version": "customer-partial-return-v2",
            "allocation_policy": "remaining-original-v1",
            "entries": [],
            "original_id": "plan-" + str(parent) if parent else None,
        }
        plan = add(
            "customer_partial_return_plans",
            id=identifier,
            source_order_id="stock",
            source_id="source",
            phase=2,
            operation=operation,
            expected_history_version=index - 1,
            plan_digest="d" * 64,
            payload=payload,
            preparer_actor_id="maker",
            workspace_id="work",
            quantity_scaled=take,
            credit_minor=credit,
            cogs_restored_minor=value,
            receivable_released_minor=release,
            refund_entitlement_delta_minor=liability,
            amount_minor=credit + value if take else 3000 if index == 3 else 7000,
        )
        add("customer_partial_return_history", source_id="source", sequence=index, plan_id=identifier, kind=operation)
        add("customer_partial_return_events", plan_id=identifier, operation="review", actor_id="reviewer")
        add("customer_partial_return_events", plan_id=identifier, operation="post", actor_id="poster")
        entries: list[tuple[str, list[tuple[str, int, int]]]] = []
        direction = -1 if operation.startswith("Reverse") else 1
        if take:
            domain_part = {
                "position": 1,
                "original_consumption_id": "consumption",
                "before_quantity_scaled": cost_q,
                "before_value_minor": cost_v,
            }
            payload["domain_plan"] = {
                "allocation_policy": "remaining-original-v1",
                "revenue_before_quantity_scaled": revenue_q,
                "revenue_before_value_minor": revenue_v,
                "portions": [domain_part],
            }
            payload["movement_id"] = "movement-" + str(index)
            add(
                "inventory_movements",
                id=payload["movement_id"],
                source_reference=identifier,
                movement_number=identifier.upper(),
                status="Posted",
                source_type="Generated",
                movement_type="Receipt" if direction == 1 else "Delivery",
            )
            add(
                "inventory_movement_lines",
                movement_id=payload["movement_id"],
                item_id=stock["item_id"],
                uom_id=stock["uom_id"],
                quantity_scaled=take,
                quantity_precision=precision,
                from_location_id="location" if direction == -1 else None,
                to_location_id="location" if direction == 1 else None,
            )
            if credit:
                entries.append(
                    (
                        "RevenueCredit",
                        [
                            ("REVENUE", credit, 0),
                            *([("AR", 0, release)] if release else []),
                            *([("REFUND", 0, liability)] if liability else []),
                        ],
                    )
                )
            if value:
                entries.append(("CostRestoration", [("INVENTORY", value, 0), ("COGS", 0, value)]))
            if direction == -1:
                entries = [
                    ("Reverse" + purpose, [(code, right, left) for code, left, right in lines])
                    for purpose, lines in entries
                ]
            returned_q += direction * take
            returned_v += direction * value
            layer["remaining_quantity_scaled"], layer["remaining_value_minor"] = returned_q, returned_v
            add(
                "customer_partial_return_allocation_witnesses",
                plan_id=identifier,
                position=1,
                before_quantity_scaled=cost_q,
                before_value_minor=cost_v,
            )
        else:
            amount = plan["amount_minor"]
            entries = [(operation, [("REFUND", amount, 0), ("CASH", 0, amount)])]
            if direction == -1:
                entries = [(operation, [(code, right, left) for code, left, right in entries[0][1]])]
        for ordinal, (purpose, lines) in enumerate(entries):
            entry_id, effect_id = f"entry-{index}-{ordinal}", f"effect-{index}-{ordinal}"
            snapshot = {
                "schema_version": "finance-entry-review-v1",
                "entry": {"id": entry_id},
                "lines": [
                    {"account_id": code, "debit_minor": left, "credit_minor": right} for code, left, right in lines
                ],
            }
            digest = reader._digest(snapshot)
            payload["entries"].append(
                {"entry_id": entry_id, "purpose": purpose, "validation_digest": digest, "snapshot": snapshot}
            )
            add(
                "finance_posting_effects",
                id=effect_id,
                entry_id=entry_id,
                validation_digest=digest,
                snapshot_json=snapshot,
            )
            add(
                "finance_entries",
                id=entry_id,
                workspace_id="work",
                status="Validated",
                validation_digest=digest,
                total_debit_minor=sum(left for _code, left, _right in lines),
                total_credit_minor=sum(right for _code, _left, right in lines),
            )
            for number, (code, left, right) in enumerate(lines, 1):
                add(
                    "finance_entry_lines",
                    id=f"line-{index}-{ordinal}-{number}",
                    entry_id=entry_id,
                    line_number=number,
                    account_id=code,
                    debit_minor=left,
                    credit_minor=right,
                )
        if take:
            cost_effect = next(
                (
                    row["id"]
                    for row in tables["finance_posting_effects"]
                    if row["entry_id"]
                    in {part["entry_id"] for part in payload["entries"] if "CostRestoration" in part["purpose"]}
                ),
                None,
            )
            add(
                "customer_partial_return_restorations",
                source_id="source",
                plan_id=identifier,
                position=1,
                original_consumption_id="consumption",
                original_valuation_line_id="valuation-line",
                cost_layer_id="layer",
                offset_quantity_scaled=q - cost_q,
                quantity_scaled=take,
                value_minor=value,
                direction=direction,
                correction_effect_id=cost_effect,
                original_restoration_plan_id=payload["original_id"],
                physical_movement_id=payload["movement_id"],
            )
        captures.append(
            {
                "schema_version": "customer-partial-return-remainder-browser-capture-v1",
                "tenant_id": "tenant",
                "source_order_id": "stock",
                "history_version": index,
                "posted_plan_id": identifier,
                "plan_digest": "d" * 64,
                "tables": raw(tables),
            }
        )
    return {
        "schema_version": "customer-partial-return-remainder-posted-cycle-input-v1",
        "case": case,
        "tenant_id": "tenant",
        "source_order_id": "stock",
        "captures": captures,
    }


@pytest.mark.parametrize(
    ("case", "effects", "lines", "debits"), [("ordinary", 6, 12, 4001), ("zero", 4, 8, 4), ("refund", 8, 17, 81000)]
)
def test_closed_synthetic_adapter_controls_match_literal_rounded_zero_and_refund_vectors(
    case: str, effects: int, lines: int, debits: int
) -> None:
    proof = reader.qualify_raw_cycle(fixture(case))
    assert (proof["new_actual_posting_effects"], proof["new_actual_posted_lines"], proof["new_debits_minor"]) == (
        effects,
        lines,
        debits,
    )
    assert proof["original_zero_cost_admission"] is False


@pytest.mark.parametrize(
    "attack",
    [
        "missing-table",
        "foreign-tenant",
        "bool-version",
        "zero-before",
        "null-cost-effect",
        "duplicate-effect",
        "layer",
        "money",
        "entry-purpose",
        "sod",
        "source-policy",
        "fake-zero-original",
    ],
)
def test_resealed_or_well_typed_raw_counterexamples_do_not_qualify_as_actual_posted_money(attack: str) -> None:
    packet = fixture("zero")
    capture = packet["captures"][1]
    tables = capture["tables"]
    if attack == "missing-table":
        tables.pop("customer_partial_return_allocation_witnesses")
    elif attack == "bool-version":
        capture["history_version"] = True
    else:
        name = {
            "foreign-tenant": "inventory_cost_layers",
            "zero-before": "customer_partial_return_allocation_witnesses",
            "null-cost-effect": "customer_partial_return_restorations",
            "duplicate-effect": "finance_posting_effects",
            "layer": "inventory_cost_layers",
            "money": "customer_partial_return_plans",
            "entry-purpose": "customer_partial_return_plans",
            "sod": "customer_partial_return_events",
            "source-policy": "customer_partial_return_sources",
            "fake-zero-original": "inventory_layer_consumptions",
        }[attack]
        if attack in {"null-cost-effect", "duplicate-effect", "entry-purpose"}:
            tables = packet["captures"][5]["tables"]
        position = next(
            (
                index
                for index, raw_row in enumerate(tables[name])
                if json.loads(raw_row).get("plan_id", json.loads(raw_row).get("id")) == "plan-5"
            ),
            len(tables[name]) - 1,
        )
        row = json.loads(tables[name][position])
        if attack == "foreign-tenant":
            row["tenant_id"] = "other"
        if attack == "zero-before":
            row["before_value_minor"] = 0
        if attack == "null-cost-effect":
            row["correction_effect_id"] = None
        if attack == "duplicate-effect":
            tables[name].append(tables[name][-1])
        if attack == "layer":
            row["remaining_quantity_scaled"] += 1
        if attack == "money":
            row["amount_minor"] = 1
        if attack == "entry-purpose":
            row["payload"]["entries"][0]["purpose"] = "RevenueCredit"
        if attack == "sod":
            row["actor_id"] = "maker"
        if attack == "source-policy":
            row["source_payload"]["allocation_policy"] = None
        if attack == "fake-zero-original":
            row["value_minor"] = 0
        tables[name][position] = json.dumps(row, sort_keys=True)
    with pytest.raises(ValueError):
        reader.qualify_raw_cycle(packet)


def observation_tables() -> dict[str, list[str]]:
    tables = audit_capture()
    tables["customer_partial_return_allocation_witnesses"] = [
        json.dumps(
            {
                "tenant_id": "tenant",
                "plan_id": "plan-1",
                "position": 1,
                "before_quantity_scaled": 3,
                "before_value_minor": 1,
            },
            sort_keys=True,
        )
    ]
    return tables


@pytest.mark.parametrize(
    "surface",
    [
        "GET /api/v2/customer-partial-returns/plans",
        "GET /api/v2/customer-partial-returns/plans/plan-1",
        "GET /api/v2/customer-partial-returns/sources/stock/balance",
        "POST /api/v2/customer-partial-returns/plans/plan-1/post",
    ],
)
def test_explicit_v2_read_or_retained_post_policy_append_is_allowed_with_exact_permission(surface: str) -> None:
    before = observation_tables()
    after = copy.deepcopy(before)
    event = policy_event(
        1,
        "0" * 64,
        surface=surface,
        permission="finance_core.post" if surface.startswith("POST") else "finance_core.read",
    )
    set_audits(after, [event])
    proof = reader.verify_audit_only_transition(before, after, tenant_id="tenant")
    assert proof["business_tables"] == 77 and proof["appended_audit_events"] == 1


@pytest.mark.parametrize(
    "attack", ["witness", "audit-mutation", "gap", "head", "unrelated-action", "wrong-permission", "denied"]
)
def test_audit_append_cannot_cover_new_witness_mutation_or_invalid_or_unrelated_policy(attack: str) -> None:
    before, after = observation_tables(), observation_tables()
    event = policy_event(1, "0" * 64, surface="GET /api/v2/customer-partial-returns/plans")
    if attack == "gap":
        event["sequence"] = 2
    if attack == "unrelated-action":
        event["action"] = "changed"
    if attack == "wrong-permission":
        event = policy_event(
            1, "0" * 64, surface="POST /api/v2/customer-partial-returns/plans/plan-1/post", permission="users.manage"
        )
    if attack == "denied":
        event["metadata_json"]["policy_decision_evidence"]["allowed"] = False
    if attack == "audit-mutation":
        set_audits(before, [event])
        event = copy.deepcopy(event)
        event["created_at"] = "2026-10-15T00:00:59+00:00"
    event = seal_audit(event)
    set_audits(after, [event])
    if attack == "head":
        head = json.loads(after["domain_audit_ledger_state"][0])
        head["last_event_hash"] = "e" * 64
        after["domain_audit_ledger_state"][0] = json.dumps(head)
    if attack == "witness":
        row = json.loads(after["customer_partial_return_allocation_witnesses"][0])
        row["before_value_minor"] = 0
        after["customer_partial_return_allocation_witnesses"][0] = json.dumps(row)
    with pytest.raises(ValueError):
        reader.verify_audit_only_transition(before, after, tenant_id="tenant")


def observations_fixture(case: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    packet = fixture(case)
    replay = reader.REPLAY_VERSIONS[case]
    event = policy_event(
        1,
        "0" * 64,
        surface=f"POST /api/v2/customer-partial-returns/plans/plan-{replay}/post",
        permission="finance_core.post",
    )
    sidecars = []
    for kind, version in (("RetainedReplay", replay), ("FinalRead", len(reader.CASE_EVENTS[case]))):
        baseline = packet["captures"][version]
        sidecar = {
            **copy.deepcopy(baseline),
            "schema_version": "customer-partial-return-remainder-browser-observation-v1",
            "kind": kind,
        }
        if kind == "RetainedReplay":
            set_audits(sidecar["tables"], [event])
            for following in packet["captures"][version + 1 :]:
                set_audits(following["tables"], [event])
        else:
            final = policy_event(2, event["event_hash"], surface="GET /api/v2/customer-partial-returns/plans")
            set_audits(sidecar["tables"], [event, final])
        sidecars.append(sidecar)
    observations = {
        "schema_version": "customer-partial-return-remainder-posted-observations-input-v1",
        "case": case,
        "tenant_id": "tenant",
        "source_order_id": "stock",
        "observations": sidecars,
    }
    restored = {
        "schema_version": "customer-partial-return-remainder-posted-restored-input-v1",
        "case": case,
        "tenant_id": "tenant",
        "source_order_id": "stock",
        "tables": copy.deepcopy(sidecars[-1]["tables"]),
    }
    return packet, observations, restored


@pytest.mark.parametrize("case", ["ordinary", "zero", "refund"])
def test_two_case_bound_observations_and_final_populated_restore_keep_all_seventy_nine_tables(case: str) -> None:
    packet, observations, restored = observations_fixture(case)
    reader.qualify_raw_cycle(packet)
    proof = reader.verify_raw_observations(packet, observations)
    assert proof["observations"] == 2 and proof["observation_business_tables"] == 77
    assert proof["appended_audit_events"] == 2
    assert reader.verify_restored_cycle(packet, restored, observations)["restored_tables"] == 79


@pytest.mark.parametrize(
    "attack",
    [
        "extra-case",
        "bool-version",
        "foreign-plan",
        "foreign-digest",
        "chronology",
        "missing-final-audit",
        "restore-witness",
    ],
)
def test_observation_and_restore_identity_original_membership_and_chronology_are_mandatory(attack: str) -> None:
    packet, observations, restored = observations_fixture("zero")
    if attack == "extra-case":
        observations["case"] = "refund"
    elif attack == "bool-version":
        observations["observations"][0]["history_version"] = True
    elif attack == "foreign-plan":
        observations["observations"][0]["posted_plan_id"] = "another-plan"
    elif attack == "foreign-digest":
        observations["observations"][0]["plan_digest"] = "e" * 64
    elif attack == "chronology":
        set_audits(packet["captures"][2]["tables"], [])
    elif attack == "missing-final-audit":
        restored["tables"] = copy.deepcopy(packet["captures"][-1]["tables"])
    else:
        row = json.loads(restored["tables"]["customer_partial_return_allocation_witnesses"][0])
        row["before_value_minor"] += 1
        restored["tables"]["customer_partial_return_allocation_witnesses"][0] = json.dumps(row)
    with pytest.raises(ValueError):
        reader.verify_restored_cycle(packet, restored, observations)


def test_native_refund_input_contract_is_separate_from_browser_and_restore_claims() -> None:
    packet = fixture("refund")
    native = {
        "schema_version": "customer-partial-return-remainder-native-refunds-v1",
        "tenant_id": "tenant",
        "source_order_id": "stock",
        "captures": [capture["tables"] for capture in packet["captures"]],
    }
    proof = reader.qualify_native_refunds(native)
    assert (proof["new_actual_posting_effects"], proof["new_actual_posted_lines"], proof["new_debits_minor"]) == (
        8,
        17,
        81000,
    )
    assert proof["browser_execution_proven"] is proof["populated_restore_proven"] is False


def test_standalone_isolated_and_optimized_cli_outputs_match_without_production_imports(tmp_path: Path) -> None:
    packet, observations, restored = observations_fixture("zero")
    inputs = []
    for label, value in (("input", packet), ("observations-input", observations), ("restore-input", restored)):
        path = tmp_path / (label + ".json")
        path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
        inputs.extend(("--" + label, str(path)))
    outputs = []
    for mode, flags in (("I", ["-I"]), ("IO", ["-I", "-O"])):
        output = tmp_path / (mode + ".json")
        result = subprocess.run(
            [sys.executable, *flags, reader.__file__, *inputs, "--output", str(output)],
            capture_output=True,
            timeout=20,
            check=False,
        )
        assert result.returncode == 0 and result.stdout == result.stderr == b""
        outputs.append(output.read_bytes())
    assert outputs[0] == outputs[1]
