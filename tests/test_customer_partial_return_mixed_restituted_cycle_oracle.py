"""Literal finite mixed-source controls; no private native files are imported."""
from __future__ import annotations

import copy
import json
from fractions import Fraction
from typing import Any

import pytest

from tests import customer_partial_return_mixed_restituted_cycle_oracle as reader
from tests.test_customer_partial_return_restituted_cycle_oracle import add_gl
from tests.test_customer_partial_return_restituted_cycle_oracle import fixture as original_fixture


def fixture() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    original = original_fixture()
    rows = reader.base._rows(reader.base._originals(original["captures"][2]["tables"], "tenant"))
    source = next(json.loads(value) for value in original["captures"][3]["tables"]["customer_partial_return_sources"] if json.loads(value)["id"] == "new-source")
    stock = reader.base._one(rows["stock_sales_orders"], id="resale")
    old_source = reader.base._one(rows["customer_partial_return_sources"], id="old-source")
    stock.update(quantity_scaled=2, total_minor=200, cogs_entry_id="mixed-cogs", cogs_effect_id="mixed-cogs-effect")
    reader.base._one(rows["ar_invoices"], id=stock["invoice_id"])["total_minor"] = 200
    add_gl(rows, "mixed-cogs", (("COGS", 10, 0), ("INVENTORY", 0, 10)))
    effect = reader.base._one(rows["finance_posting_effects"], id="mixed-cogs-effect")
    effect.update(source_id=effect["entry_id"], source_kind="Manual", purpose="operational_posting")
    reader.base._one(rows["finance_entries"], id=effect["entry_id"])["external_reference"] = stock["id"]
    effect["snapshot_json"]["entry"]["external_reference"] = stock["id"]
    effect["validation_digest"] = reader.base._digest(effect["snapshot_json"])
    reader.base._one(rows["finance_entries"], id=effect["entry_id"])["validation_digest"] = effect["validation_digest"]
    valuation = reader.base._one(rows["inventory_valuation_documents"], id=stock["valuation_id"])
    valuation.update(total_value_minor=10, finance_entry_id="mixed-cogs")
    zero_line = reader.base._one(rows["inventory_valuation_lines"], valuation_document_id=valuation["id"])
    zero_line["line_number"] = 1
    zero_line.update(quantity_scaled=2, value_minor=10)
    zero = reader.base._one(rows["inventory_layer_consumptions"], valuation_line_id=zero_line["id"])
    positive = {**copy.deepcopy(zero), "id": "positive-consumption", "cost_layer_id": "positive-layer", "value_minor": 10}
    rows["inventory_layer_consumptions"].append(positive)
    positive_layer = {**copy.deepcopy(rows["inventory_cost_layers"][0]), "id": "positive-layer", "original_quantity_scaled": 1, "original_value_minor": 10,
                      "remaining_quantity_scaled": 0, "remaining_value_minor": 0}
    rows["inventory_cost_layers"].append(positive_layer)
    issue = stock["issue_plan"]
    issue.update(total_cost_minor=10, entry_id="mixed-cogs")
    issue["allocations"].append({"cost_layer_id": positive_layer["id"], "quantity_scaled": 1, "value_minor": 10})
    snapshot = issue["restitution_cost_snapshot"]
    snapshot.update(remaining_quantity_scaled=2, remaining_value_minor=10)
    rows["inventory_cost_layers"][0]["row_version"] = 2
    snapshot["sources"][0]["layer"]["row_version"] = 1
    positive_layer["row_version"] = 2
    snapshot["sources"].append({"layer": {**copy.deepcopy(positive_layer), "remaining_quantity_scaled": 1, "remaining_value_minor": 10, "row_version": 1},
                                "consumptions": [], "partial_return_corrections": []})
    proof = source["source_payload"]["original_source"]["cost_admission"]
    proof.update(issue_plan=issue, valuation_document=valuation, valuation_lines=[zero_line], consumptions=[zero, positive], posting_effect=effect)
    source.update(original_quantity_scaled=2, gross_minor=200, original_cogs_effect_id=effect["id"])
    source.update({key: stock[key] for key in ("item_id", "uom_id", "location_id")})
    payload = source["source_payload"]
    scope = {key: stock[key] for key in ("tenant_id", "workspace_id", "organization_id", "legal_entity_id", "item_id", "uom_id", "location_id")}
    payload["typed_source"]["scope"] = scope
    payload["typed_source"]["original_cogs"] = {"posting_effect_id": effect["id"], "validation_digest": effect["validation_digest"], "scope": scope,
                                                "snapshot_json": json.dumps(effect["snapshot_json"])}
    payload["fingerprint_payload"]["scope"] = scope
    payload["fingerprint_payload"].update(quantity_scaled=2, gross_minor=200, original_cogs=[effect["id"], effect["validation_digest"]],
        consumptions=[{"consumption_id": row["id"], "valuation_line_id": row["valuation_line_id"], "cost_layer_id": row["cost_layer_id"], "quantity_scaled": 1, "value_minor": value}
                      for row, value in zip((zero, positive), (0, 10), strict=True)])
    reseal(source)
    return rows, source, stock, old_source


def reseal(source: dict[str, Any]) -> None:
    payload = source["source_payload"]
    digest = reader.base._digest(payload["original_source"]["cost_admission"])
    payload["typed_source"]["original_cost_admission"] = {"evidence_digest": digest}
    payload["fingerprint_payload"]["original_cost_admission"] = ["stock-sales-restituted-cost-v1", digest]
    source["source_fingerprint"] = reader.base._digest(payload["fingerprint_payload"])


def test_positive_total_retains_one_real_cogs_owner_for_zero_and_positive_consumptions() -> None:
    rows, source, stock, old = fixture()
    consumed = reader._mixed_original(rows, source, stock, old)
    assert [row["value_minor"] for row in consumed] == [0, 10]
    assert reader._entry_vector(rows, stock["cogs_entry_id"]) == [("COGS", 10, 0), ("INVENTORY", 0, 10)]


@pytest.mark.parametrize("attack", ["null-effect", "bool-cost", "foreign-owner", "source-quantity", "before-witness", "missing-consumption", "scope", "cogs-vector", "extra-source", "outbox-payload", "missing-source-pin", "bool-history", "bool-witness"])
def test_coherently_resealed_mixed_admission_counterexamples_are_refused(attack: str) -> None:
    rows, source, stock, old = fixture()
    proof = source["source_payload"]["original_source"]["cost_admission"]
    if attack == "null-effect":
        proof["posting_effect"] = None
    elif attack == "bool-cost":
        stock["issue_plan"]["allocations"][0]["value_minor"] = False
    elif attack == "foreign-owner":
        proof["posting_effect"]["source_id"] = "foreign-stock"
    elif attack == "source-quantity":
        source["source_payload"]["fingerprint_payload"]["quantity_scaled"] = 3
    elif attack == "before-witness":
        stock["issue_plan"]["restitution_cost_snapshot"]["sources"][0]["partial_return_corrections"][0]["allocation_witness"]["before_value_minor"] = 0
    elif attack == "missing-consumption":
        rows["inventory_layer_consumptions"] = [row for row in rows["inventory_layer_consumptions"] if row["id"] != "positive-consumption"]
    elif attack == "scope":
        source["workspace_id"] = "foreign"
    elif attack == "cogs-vector":
        next(row for row in rows["finance_entry_lines"] if row["entry_id"] == "mixed-cogs" and row["debit_minor"])["account_id"] = "REVENUE"
    elif attack == "extra-source":
        snapshot = stock["issue_plan"]["restitution_cost_snapshot"]
        snapshot["sources"].append(copy.deepcopy(snapshot["sources"][0]))
    elif attack == "outbox-payload":
        native = stock["issue_plan"]["restitution_cost_snapshot"]["sources"][0]["partial_return_corrections"][0]["physical"]
        native["outbox"][0]["payload"] = {"forged": True}
    else:
        correction = stock["issue_plan"]["restitution_cost_snapshot"]["sources"][0]["partial_return_corrections"][0]
        if attack == "missing-source-pin":
            correction["source"] = {}
        elif attack == "bool-history":
            correction["history_sequence"] = True
        else:
            correction["allocation_witness"]["before_value_minor"] = True
    reseal(source)
    with pytest.raises((ValueError, KeyError)):
        reader._mixed_original(rows, source, stock, old)


@pytest.mark.parametrize("value", [True, False, 1.0, Fraction(1, 1), -1, None, "1"])
def test_financial_fields_require_exact_nonnegative_integers(value: Any) -> None:
    with pytest.raises(ValueError):
        reader.integer(value)


def test_existing_zero_total_packet_does_not_establish_the_new_mixed_case() -> None:
    with pytest.raises(ValueError):
        reader.qualify_raw_cycle(original_fixture())
