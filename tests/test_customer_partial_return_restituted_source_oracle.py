"""Finite factual-admission controls; synthetic dictionaries are not native proof."""

from __future__ import annotations

import copy
from typing import Any

import pytest

from tests.customer_partial_return_restituted_source_oracle import OUTBOX_FIELDS, digest, verify_restituted_original


def fixture() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    scope = {"tenant_id": "tenant", "workspace_id": "work", "organization_id": "org", "legal_entity_id": "entity"}
    names = (
        "stock_sales_orders",
        "ar_invoices",
        "inventory_valuation_documents",
        "inventory_valuation_lines",
        "inventory_layer_consumptions",
        "finance_entries",
        "finance_posting_effects",
        "inventory_cost_layers",
        "customer_partial_return_sources",
        "customer_partial_return_plans",
        "customer_partial_return_restorations",
        "customer_partial_return_allocation_witnesses",
        "inventory_movements",
        "inventory_movement_lines",
        "domain_audit_events",
        "outbox_events",
    )
    prior: dict[str, Any] = {name: [] for name in names}
    old_source = {
        **scope,
        "id": "old-source",
        "source_order_id": "old-stock",
        "source_fingerprint": "a" * 64,
        "item_id": "item",
        "uom_id": "uom",
        "location_id": "location",
        "quantity_precision": 1,
        "original_cogs_effect_id": "old-cogs",
    }
    old_plan = {
        **scope,
        "id": "old-plan",
        "source_id": "old-source",
        "operation": "Return",
        "phase": 2,
        "plan_digest": "b" * 64,
        "quantity_scaled": 1,
        "credit_minor": 0,
        "cogs_restored_minor": 0,
    }
    layer = {**scope, "id": "layer", "remaining_quantity_scaled": 1, "remaining_value_minor": 0}
    old_consumption = {
        "tenant_id": "tenant",
        "id": "old-consumption",
        "cost_layer_id": "layer",
        "valuation_line_id": "old-line",
        "quantity_scaled": 3,
        "value_minor": 1,
    }
    restoration = {
        "tenant_id": "tenant",
        "source_id": "old-source",
        "plan_id": "old-plan",
        "position": 1,
        "cost_layer_id": "layer",
        "original_consumption_id": "old-consumption",
        "quantity_scaled": 1,
        "value_minor": 0,
        "direction": 1,
        "correction_effect_id": None,
        "physical_movement_id": "old-movement",
    }
    witness = {
        "tenant_id": "tenant",
        "plan_id": "old-plan",
        "position": 1,
        "before_quantity_scaled": 3,
        "before_value_minor": 1,
    }
    physical = {
        "head": {**scope, "id": "old-movement", "status": "Posted", "source_reference": "old-plan"},
        "lines": [{"tenant_id": "tenant", "movement_id": "old-movement", "quantity_scaled": 1}],
        "audit": [{"tenant_id": "tenant", "id": "audit"}],
        "outbox": [{**scope, "event_id": "outbox", "event_type": "inventory.posted", "aggregate_type": "movement", "aggregate_id": "old-movement",
                    "payload": {"movement_id": "old-movement"}, "created_at": "2026-10-14T00:00:00Z"}],
    }
    prior.update(
        customer_partial_return_sources=[old_source],
        customer_partial_return_plans=[old_plan],
        inventory_cost_layers=[layer],
        inventory_layer_consumptions=[old_consumption],
        customer_partial_return_restorations=[restoration],
        customer_partial_return_allocation_witnesses=[witness],
        inventory_movements=[physical["head"]],
        inventory_movement_lines=physical["lines"],
        domain_audit_events=physical["audit"],
        outbox_events=physical["outbox"],
    )
    correction = {
        "restoration": restoration,
        "source": {key: value for key, value in old_source.items() if key not in {"tenant_id", "source_order_id"}},
        "plan": {
            key: old_plan[key]
            for key in ("id", "source_id", "operation", "phase", "plan_digest", "cogs_restored_minor")
        },
        "entry": None,
        "effect": None,
        "lines": [],
        "dimensions": [],
        "physical": physical,
        "history_sequence": 1,
        "allocation_policy": "remaining-original-v1",
        "allocation_witness": {"before_quantity_scaled": 3, "before_value_minor": 1},
    }
    monetary = {
        "currency_code": "USD",
        "currency_precision": 2,
        "currency_rounding_policy": "ROUND_HALF_UP",
        "currency_registry_version": "captured",
        "currency_registry_digest": "d" * 64,
    }
    issue = {
        "schema_version": "stock-sales-issue-v2",
        "cost_admission_policy": "partial-return-restituted-v1",
        "total_cost_minor": 0,
        "entry_id": None,
        "currency_policy": {
            "currency_code": "USD",
            "precision": 2,
            "rounding_policy": "ROUND_HALF_UP",
            "registry_version": "captured",
            "registry_digest": "d" * 64,
        },
        "allocations": [{"cost_layer_id": "layer", "quantity_scaled": 1, "value_minor": 0}],
        "restitution_cost_snapshot": {
            "schema_version": "inventory-transfer-cost-v3",
            "monetary_policy": monetary,
            "remaining_quantity_scaled": 1,
            "remaining_value_minor": 0,
            "sources": [
                {"layer": layer, "consumptions": [old_consumption], "partial_return_corrections": [correction]}
            ],
        },
    }
    stock = {
        **scope,
        "id": "resale",
        "invoice_id": "invoice",
        "valuation_id": "valuation",
        "quantity_scaled": 1,
        "quantity_precision": 1,
        "status": "Invoiced",
        "total_minor": 100,
        "source": {"net_unit_price_minor": 1000},
        "issue_plan": issue,
        "cogs_entry_id": None,
        "cogs_effect_id": None,
    }
    valuation = {**scope, "id": "valuation", "status": "Approved", "finance_entry_id": None, "total_value_minor": 0}
    line = {
        "tenant_id": "tenant",
        "id": "line",
        "valuation_document_id": "valuation",
        "flow_direction": "Outbound",
        "quantity_scaled": 1,
        "value_minor": 0,
    }
    consumption = {
        "tenant_id": "tenant",
        "id": "consumption",
        "valuation_line_id": "line",
        "cost_layer_id": "layer",
        "quantity_scaled": 1,
        "value_minor": 0,
    }
    issued = copy.deepcopy(prior)
    issued.update(
        stock_sales_orders=[stock],
        ar_invoices=[{**scope, "id": "invoice", "total_minor": 100, "tax_minor": 0}],
        inventory_valuation_documents=[valuation],
        inventory_valuation_lines=[line],
        inventory_layer_consumptions=[old_consumption, consumption],
    )
    proof = {
        "schema_version": "stock-sales-restituted-cost-v1",
        "stock_order_id": "resale",
        "issue_plan": issue,
        "valuation_document": valuation,
        "valuation_lines": [line],
        "consumptions": [consumption],
        "posting_effect": None,
    }
    fingerprint = {
        "contract": "customer-partial-return-original-v2",
        "source_order_id": "resale",
        "invoice_id": "invoice",
        "quantity_scaled": 1,
        "gross_minor": 100,
        "original_cogs": None,
        "original_cost_admission": ["stock-sales-restituted-cost-v1", digest(proof)],
        "currency": "USD",
        "policy": {key: value for key, value in monetary.items() if key != "currency_code"},
        "consumptions": [
            {
                "consumption_id": "consumption",
                "valuation_line_id": "line",
                "cost_layer_id": "layer",
                "quantity_scaled": 1,
                "value_minor": 0,
            }
        ],
    }
    source = {
        **scope,
        "source_order_id": "resale",
        "invoice_id": "invoice",
        "original_cogs_effect_id": None,
        "source_fingerprint": digest(fingerprint),
        "source_payload": {
            "allocation_policy": "remaining-original-v1",
            "original_source": {"cost_admission": proof},
            "typed_source": {"original_cogs": None, "original_cost_admission": {"evidence_digest": digest(proof)}},
            "fingerprint_payload": fingerprint,
        },
    }
    return copy.deepcopy(prior), copy.deepcopy(issued), copy.deepcopy(source)


def verify(prior: dict[str, Any], issued: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    return verify_restituted_original(
        prior, issued, source, tenant_id="tenant", original_source_order_id="old-stock", resale_source_order_id="resale"
    )


def test_explicit_zero_original_requires_its_actual_prior_restitution_and_absent_cost_effect() -> None:
    proof = verify(*fixture())
    assert proof["explicit_original_cost_admission"] is True and proof["original_cogs_effect_absent"] is True
    assert (proof["original_quantity_scaled"], proof["original_gross_minor"], proof["original_cost_minor"]) == (
        1,
        100,
        0,
    )
    assert proof["current_authorization_proven"] is proof["native_execution_proven"] is False


def test_resealed_boolean_before_value_is_not_an_integer_witness() -> None:
    prior, issued, source = fixture()
    issue = issued["stock_sales_orders"][0]["issue_plan"]
    issue["restitution_cost_snapshot"]["sources"][0]["partial_return_corrections"][0]["allocation_witness"]["before_value_minor"] = True
    proof = source["source_payload"]["original_source"]["cost_admission"]
    proof["issue_plan"] = copy.deepcopy(issue)
    admission_digest = digest(proof)
    source["source_payload"]["typed_source"]["original_cost_admission"] = {"evidence_digest": admission_digest}
    source["source_payload"]["fingerprint_payload"]["original_cost_admission"] = ["stock-sales-restituted-cost-v1", admission_digest]
    source["source_fingerprint"] = digest(source["source_payload"]["fingerprint_payload"])
    with pytest.raises(ValueError):
        verify(prior, issued, source)


@pytest.mark.parametrize(
    "attack",
    [
        "policy",
        "schema",
        "effect",
        "fake-zero-entry",
        "tenant",
        "scope",
        "layer-value",
        "old-consumption",
        "witness",
        "correction-cost",
        "physical",
        "missing-audit",
        "legacy-fingerprint",
        "proof-digest",
        "foreign-source",
        "outbox-payload",
        "outbox-extra-field",
    ],
)
def test_even_coherently_resealed_factual_admission_cannot_replace_actual_native_rows(attack: str) -> None:
    prior, issued, source = fixture()
    payload = source["source_payload"]
    proof = payload["original_source"]["cost_admission"]
    if attack == "policy":
        proof["issue_plan"]["cost_admission_policy"] = "guessed-policy"
    elif attack == "schema":
        proof["schema_version"] = "stock-sales-issue-v1"
    elif attack == "effect":
        proof["posting_effect"] = {"id": "fake-zero-effect"}
    elif attack == "fake-zero-entry":
        issued["finance_entries"].append(
            {"tenant_id": "tenant", "external_reference": "resale", "total_debit_minor": 0}
        )
    elif attack == "tenant":
        issued["inventory_layer_consumptions"][-1]["tenant_id"] = "hidden"
    elif attack == "scope":
        issued["stock_sales_orders"][0]["workspace_id"] = "hidden"
    elif attack == "layer-value":
        prior["inventory_cost_layers"][0]["remaining_value_minor"] = 1
    elif attack == "old-consumption":
        prior["inventory_layer_consumptions"][0]["value_minor"] = 0
    elif attack == "witness":
        proof["issue_plan"]["restitution_cost_snapshot"]["sources"][0]["partial_return_corrections"][0][
            "allocation_witness"
        ]["before_value_minor"] = 0
    elif attack == "correction-cost":
        proof["issue_plan"]["restitution_cost_snapshot"]["sources"][0]["partial_return_corrections"][0]["restoration"][
            "value_minor"
        ] = 1
    elif attack == "physical":
        prior["inventory_movements"][0]["status"] = "Draft"
    elif attack == "missing-audit":
        prior["domain_audit_events"] = []
    elif attack == "legacy-fingerprint":
        payload["fingerprint_payload"]["contract"] = "customer-partial-return-domain-v1"
    elif attack == "foreign-source":
        proof["stock_order_id"] = "foreign-stock"
    elif attack in {"outbox-payload", "outbox-extra-field"}:
        native = proof["issue_plan"]["restitution_cost_snapshot"]["sources"][0]["partial_return_corrections"][0]["physical"]
        native["outbox"] = [{**native["outbox"][0], **({"payload": {"forged": True}} if attack == "outbox-payload" else {"status": "Pending"})}]
        issued["stock_sales_orders"][0]["issue_plan"] = copy.deepcopy(proof["issue_plan"])
    if attack == "proof-digest":
        payload["typed_source"]["original_cost_admission"]["evidence_digest"] = "e" * 64
    else:
        payload["typed_source"]["original_cost_admission"]["evidence_digest"] = digest(proof)
        payload["fingerprint_payload"]["original_cost_admission"][1] = digest(proof)
    source["source_fingerprint"] = digest(payload["fingerprint_payload"])
    with pytest.raises(ValueError):
        verify(prior, issued, source)


def test_factual_outbox_projection_binds_all_ten_immutable_fields_to_full_original_row() -> None:
    prior, issued, source = fixture()
    captured = source["source_payload"]["original_source"]["cost_admission"]["issue_plan"]["restitution_cost_snapshot"]["sources"][0]["partial_return_corrections"][0]["physical"]
    event = {**prior["outbox_events"][0],
             "status": "Pending", "attempt_count": 0, "available_at": "2026-10-14T00:00:00Z", "claimed_at": None, "claimed_by": None,
             "published_at": None, "last_error": None, "dead_lettered_at": None, "lease_generation": 0, "lease_generation_floor": 0}
    prior["outbox_events"] = [event]
    captured["outbox"] = [{key: event[key] for key in OUTBOX_FIELDS}]
    proof = source["source_payload"]["original_source"]["cost_admission"]
    issued["stock_sales_orders"][0]["issue_plan"] = copy.deepcopy(proof["issue_plan"])
    source["source_payload"]["typed_source"]["original_cost_admission"] = {"evidence_digest": digest(proof)}
    source["source_payload"]["fingerprint_payload"]["original_cost_admission"][1] = digest(proof)
    source["source_fingerprint"] = digest(source["source_payload"]["fingerprint_payload"])
    assert verify(prior, issued, source)["explicit_original_cost_admission"] is True
