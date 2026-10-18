"""Synthetic original-row counterexamples for the standalone source oracle."""

from __future__ import annotations

import ast
import copy
import hashlib
import json
import subprocess
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from tests import customer_partial_return_source_oracle as oracle


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def fixture() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Hand-authored five original entries; no application fixture or engine."""
    tables: dict[str, list[dict[str, Any]]] = {name: [] for name in oracle.TABLES}
    scope = dict(zip(sorted(oracle.SCOPE_KEYS), ("item", "entity", "location", "org", "tenant", "uom", "workspace"), strict=True))
    shared = {name: scope[name] for name in ("tenant_id", "workspace_id", "organization_id", "legal_entity_id")}
    registry = {"schema_version": 1, "currencies": [{"code": "USD", "minor_units": 2, "rounding_policy": "ROUND_HALF_UP"}], "published_at": "2026-01-01", "registry_version": "synthetic-v1", "source": "synthetic", "source_url": "synthetic"}
    registry["digest"] = digest(registry)
    policy = {"currency_code": "USD", "currency_precision": 2, "currency_rounding_policy": "ROUND_HALF_UP", "currency_registry_version": "synthetic-v1", "currency_registry_digest": registry["digest"]}
    for code, kind in (("INVENTORY", "Asset"), ("CLEARING", "Liability"), ("COGS", "Expense"), ("AR", "Asset"), ("REVENUE", "Income"), ("CASH", "Asset"), ("REFUND", "Liability")):
        tables["finance_accounts"].append({"id": code, "account_code": code, "account_type": kind, "workspace_id": scope["workspace_id"]})
    snapshots, effects = {}, {}
    for name, debit, credit, amount, kind, reference in (
        ("receipt1", "INVENTORY", "CLEARING", 12000, "InventoryReceipt", "receipt-plan1"),
        ("receipt2", "INVENTORY", "CLEARING", 20000, "InventoryReceipt", "receipt-plan2"),
        ("cogs", "COGS", "INVENTORY", 22000, "Manual", "stock"),
        ("revenue", "AR", "REVENUE", 67500, "Manual", "revenue-plan"),
        ("cash", "CASH", "AR", 10000, "Manual", "collection-plan"),
    ):
        header = {**shared, **policy, "id": name, "external_reference": reference, "source_type": "Generated" if kind == "InventoryReceipt" else "Manual", "reverses_posting_id": None, "preparer_actor_id": "maker", "journal_id": "journal", "period_id": "period", "posting_date": "2026-10-09"}
        frozen_lines = [{"line_number": n, "account_id": account, "description": "synthetic", "debit_minor": amount if n == 1 else 0, "credit_minor": amount if n == 2 else 0, "dimensions": {}} for n, account in enumerate((debit, credit), 1)]
        snapshot = {"schema_version": "finance-entry-review-v1", "entry": header, "lines": frozen_lines}
        effect = {**shared, **policy, "id": "effect-" + name, "entry_id": name, "source_kind": kind, "source_id": reference if kind == "InventoryReceipt" else name, "purpose": "operational_posting", "reverses_effect_id": None, "posted_actor_id": "poster", "validation_contract_version": snapshot["schema_version"], "validation_digest": digest(snapshot), "snapshot_json": snapshot}
        tables["finance_posting_effects"].append(effect)
        tables["finance_entries"].append({**header, "status": "Validated", "validator_actor_id": "checker", "validation_contract_version": snapshot["schema_version"], "validation_digest": effect["validation_digest"], "total_debit_minor": amount, "total_credit_minor": amount})
        tables["finance_entry_lines"].extend({**{k: v for k, v in line.items() if k != "dimensions"}, "id": name + str(line["line_number"]), "entry_id": name, "tenant_id": scope["tenant_id"], "currency_code": "USD"} for line in frozen_lines)
        snapshots[name], effects[name] = snapshot, effect
    source = {"net_unit_price_minor": 4500}
    allocations = [{"cost_layer_id": "layer1", "quantity_scaled": 10, "value_minor": 12000}, {"cost_layer_id": "layer2", "quantity_scaled": 5, "value_minor": 10000}]
    issue = {"source_digest": digest(source), "allocations": allocations, "total_cost_minor": 22000}
    stock = {**scope, "id": "stock", "invoice_id": "invoice", "valuation_id": "valuation-out", "movement_id": "movement-out", "invoice_plan_id": "revenue-plan", "status": "Invoiced", "customer_id": "customer", "currency_code": "USD", "quantity_scaled": 15, "quantity_precision": 0, "total_minor": 67500, "cogs_effect_id": "effect-cogs", "cogs_entry_id": "cogs", "source": source, "source_digest": digest(source), "issue_plan": issue}
    invoice = {**shared, **policy, "id": "invoice", "customer_id": "customer", "status": "PartiallyPaid", "row_version": 4, "total_minor": 67500, "tax_minor": 0, "cancel_reason": None, "cancelled_at": None, "cancelled_by": None, "customer_return_owner_id": None, "updated_at": "synthetic"}
    invoice_line = {"id": "invoice-line", "invoice_id": "invoice", "quantity": 15, "quantity_text": "15.0", "unit_price_minor": 4500, "line_total_minor": 67500, "tax_minor": 0}
    tables["stock_sales_orders"], tables["ar_invoices"], tables["ar_invoice_lines"] = [stock], [invoice], [invoice_line]
    tables["stock_sales_issue_claims"] = [{**scope, "order_id": "stock", "state": "Consumed", "entry_id": "cogs", "plan_digest": digest(issue), "payload": issue}]
    tables["operational_finance_plans"] = [{"id": "revenue-plan", "source_kind": "ARInvoice", "source_id": "invoice", "entry_id": "revenue", "amount_minor": 67500, "validation_digest": effects["revenue"]["validation_digest"], "payload": {"snapshot": snapshots["revenue"]}}]
    tables["operational_finance_links"] = [{"plan_id": "revenue-plan", "source_effect_id": "invoice", "posting_effect_id": "effect-revenue", "posted_actor_id": "poster"}]
    detail_fields = {"item_id": scope["item_id"], "uom_id": scope["uom_id"], "inventory_lot_id": None, "quantity_precision": 0}
    tables["inventory_valuation_documents"] = [{**shared, **policy, "id": "valuation-out", "movement_id": "movement-out", "finance_entry_id": "cogs", "total_value_minor": 22000, "status": "Approved"}]
    tables["inventory_valuation_lines"] = [{**detail_fields, "id": "valuation-line-out", "valuation_document_id": "valuation-out", "movement_line_id": "movement-line-out", "flow_direction": "Outbound", "quantity_scaled": 15, "value_minor": 22000, "inventory_account_id": "INVENTORY", "offset_account_id": "COGS"}]
    tables["inventory_movements"] = [{**shared, "id": "movement-out", "status": "Posted", "movement_type": "Delivery", "source_reference": "stock"}]
    tables["inventory_movement_lines"] = [{**detail_fields, "id": "movement-line-out", "movement_id": "movement-out", "from_location_id": scope["location_id"], "to_location_id": None, "quantity_scaled": 15}]
    typed_consumed, portions = [], []
    for n, used, value, remaining, remaining_value, returned, returned_value in ((1, 10, 12000, 0, 0, 10, 12000), (2, 5, 10000, 5, 10000, 2, 4000)):
        layer, consumption, valuation = f"layer{n}", f"consumption{n}", f"valuation{n}"
        tables["inventory_cost_layers"].append({**{k: scope[k] for k in ("tenant_id", "workspace_id", "legal_entity_id", "item_id", "uom_id")}, "id": layer, "currency_code": "USD", "quantity_precision": 0, "original_quantity_scaled": 10, "original_value_minor": value + remaining_value, "remaining_quantity_scaled": remaining, "remaining_value_minor": remaining_value, "inventory_lot_id": None, "source_valuation_line_id": f"valuation-line{n}"})
        native = {"id": consumption, "cost_layer_id": layer, "workspace_id": scope["workspace_id"], "valuation_line_id": "valuation-line-out", "quantity_scaled": used, "value_minor": value}
        tables["inventory_layer_consumptions"].append(native)
        typed_consumed.append({"position": n, "consumption_id": consumption, "valuation_line_id": "valuation-line-out", "cost_layer_id": layer, "scope": scope, "quantity_precision": 0, "quantity_scaled": used, "value_minor": value, "currency_code": "USD"})
        portions.append({"position": n, "original_consumption_id": consumption, "original_valuation_line_id": "valuation-line-out", "cost_layer_id": layer, "offset_quantity_scaled": 0, "quantity_scaled": returned, "value_minor": returned_value})
        tables["inventory_valuation_documents"].append({**shared, **policy, "id": valuation, "movement_id": f"movement{n}", "finance_entry_id": f"receipt{n}", "status": "Approved", "total_value_minor": value + remaining_value, "valuation_date": f"2026-10-0{n}"})
        tables["inventory_valuation_lines"].append({**detail_fields, "id": f"valuation-line{n}", "valuation_document_id": valuation, "movement_line_id": f"movement-line{n}", "flow_direction": "Inbound", "quantity_scaled": 10, "value_minor": value + remaining_value, "inventory_account_id": "INVENTORY", "offset_account_id": "CLEARING"})
        tables["inventory_movements"].append({**shared, "id": f"movement{n}", "status": "Posted", "movement_type": "Receipt", "source_reference": f"receipt-plan{n}"})
        tables["inventory_movement_lines"].append({**detail_fields, "id": f"movement-line{n}", "movement_id": f"movement{n}", "from_location_id": None, "to_location_id": scope["location_id"], "quantity_scaled": 10})
        tables["inventory_receipt_plans"].append({**shared, **policy, "id": f"receipt-plan{n}", "cost_layer_id": layer, "posting_effect_id": f"effect-receipt{n}", "movement_id": f"movement{n}", "movement_line_id": f"movement-line{n}", "valuation_document_id": valuation, "valuation_line_id": f"valuation-line{n}", "finance_entry_id": f"receipt{n}", "total_value_minor": value + remaining_value, "finance_validation_digest": effects[f"receipt{n}"]["validation_digest"], "plan_json": {"finance_snapshot": snapshots[f"receipt{n}"]}})
        tables["inventory_receipt_links"].append({**shared, "plan_id": f"receipt-plan{n}", "movement_id": f"movement{n}", "movement_line_id": f"movement-line{n}", "posting_effect_id": f"effect-receipt{n}", "cost_layer_id": layer, "posted_actor_id": "poster"})
    receipt = {**shared, **policy, "id": "receipt", "status": "Posted", "customer_id": "customer", "amount_minor": 10000}
    allocation = {"id": "allocation", "invoice_id": "invoice", "receipt_id": "receipt", "amount_minor": 10000}
    collection = {**shared, "id": "collection-plan", "source_id": "invoice", "phase": 2, "amount_minor": 10000, "entry_id": "cash", "payload": {"snapshot": snapshots["cash"], "validation_digest": effects["cash"]["validation_digest"]}}
    tables["ar_receipts"], tables["ar_receipt_allocations"], tables["commercial_collection_plans"] = [receipt], [allocation], [collection]
    tables["commercial_collection_links"] = [{"plan_id": "collection-plan", "receipt_id": "receipt", "posting_effect_id": "effect-cash", "posted_actor_id": "poster"}]
    for rows in tables.values():
        for row in rows:
            row.setdefault("tenant_id", scope["tenant_id"])
    native_policy = {"currency_code": "USD", "precision": 2, "rounding_policy": "ROUND_HALF_UP", "registry_version": "synthetic-v1", "registry_digest": registry["digest"]}
    typed = {"scope": scope, "source_order_id": "stock", "invoice_id": "invoice", "valuation_document_id": "valuation-out", "original_revenue_plan_id": "revenue-plan", "quantity_precision": 0, "quantity_scaled": 15, "gross_minor": 67500, "net_unit_price_minor": 4500, "collected_minor": 10000, "currency_policy": native_policy, "consumptions": typed_consumed, "functional_currency": "USD", "base_uom_id": scope["uom_id"], "tax_minor": 0, "inventory_lot_id": None, "serial_tracked": False, "original_cogs_snapshot_json": canonical(snapshots["cogs"]), "original_revenue_snapshot_json": canonical(snapshots["revenue"])}
    source_payload = {"contract": "customer-partial-return-domain-v1", **{k: typed[k] for k in ("scope", "source_order_id", "invoice_id", "valuation_document_id", "quantity_precision", "original_revenue_plan_id", "quantity_scaled", "gross_minor", "net_unit_price_minor", "collected_minor", "functional_currency", "base_uom_id", "tax_minor", "inventory_lot_id", "serial_tracked", "consumptions")}, "currency": "USD", "policy": {k: v for k, v in policy.items() if k != "currency_code"}, "original_cogs": ["effect-cogs", effects["cogs"]["validation_digest"]], "original_revenue": ["effect-revenue", effects["revenue"]["validation_digest"]]}
    typed["source_fingerprint"] = digest(source_payload)
    immutable = {k: v for k, v in invoice.items() if k not in {"cancel_reason", "cancelled_at", "cancelled_by", "customer_return_owner_id", "row_version", "status", "updated_at"}}
    observed = {"schema_version": "native-partial-return-source-original-v1", "case": oracle.TWO_LAYER, "typed_source": typed, "captured_registry_snapshot": registry, "original_source_json": canonical({"stock": stock, "invoice": immutable, "invoice_status": "PartiallyPaid", "invoice_version": 4, "allocated_minor": 10000, "cogs": effects["cogs"], "revenue": effects["revenue"], "consumptions": tables["inventory_layer_consumptions"]}), "collection_evidence_json": canonical([{"allocation": allocation, "receipt": receipt, "owner_kind": "Commercial", "owner_id": "collection-plan", "posting_effect": effects["cash"]}])}
    raw = {"schema_version": "native-partial-source-financial-rows-v1", "case": oracle.TWO_LAYER, "retained_state_digest": "a" * 64, "tables": {name: sorted(canonical(row) for row in rows) for name, rows in tables.items()}, "invoice_quantity_text_witness": [{"id": "invoice-line", "invoice_id": "invoice", "quantity_numeric_text": "15.000", "quantity_text": "15.0"}]}
    plan = {"schema_version": "customer-partial-return-domain-v1", "source_fingerprint": typed["source_fingerprint"], "history_fingerprint": digest({"contract": "customer-partial-return-domain-v1", "source": typed["source_fingerprint"]}), "expected_version": 0, "quantity_before_scaled": 0, "quantity_scaled": 12, "returned_quantity_scaled": 12, "credit_minor": 54000, "cogs_restored_minor": 16000, "receivable_released_minor": 54000, "refund_entitlement_delta_minor": 0, "outstanding_after_minor": 3500, "portions": portions}
    intent = {"posting_date": "2026-10-11", "period_id": "new-period", "reason": "Synthetic unapproved intent"}
    roles = {"scope": scope, "source_fingerprint": typed["source_fingerprint"], "currency_policy": policy, "accounts": dict(zip(("receivable_account_id", "revenue_account_id", "inventory_account_id", "cogs_account_id", "refund_liability_account_id"), ("AR", "REVENUE", "INVENTORY", "COGS", "REFUND"), strict=True)), "refund_liability_account_type": "Liability"}
    common = {"schema_version": "customer-partial-return-correction-template-v1", "source_fingerprint": typed["source_fingerprint"], "history_fingerprint": plan["history_fingerprint"], "plan_fingerprint": digest(plan), "account_roles_fingerprint": digest(roles), "scope": scope, "currency_policy": policy, "posting_intent": intent, "portions": portions, "reverses_posting_id": None, "requires_native_participant": True, "requires_current_authorization": True, "requires_three_person_approval": True, "postable": False}
    templates = []
    for purpose, name, debit, credit, amount in (("RevenueCredit", "revenue", "REVENUE", "AR", 54000), ("CostRestoration", "cogs", "INVENTORY", "COGS", 16000)):
        templates.append({**common, "purpose": purpose, "original_posting_effect_id": effects[name]["id"], "original_entry_id": name, "original_validation_digest": effects[name]["validation_digest"], "journal_id": "journal", "lines": [{"line_number": n, "account_id": code, "description": intent["reason"], "debit_minor": amount if n == 1 else 0, "credit_minor": amount if n == 2 else 0, "dimensions": {}} for n, code in enumerate((debit, credit), 1)]})
    proposal = {"schema_version": "native-unposted-partial-return-proposal-original-v1", "case": oracle.TWO_LAYER, "plan_payload": plan, "account_roles_payload": roles, "posting_intent_payload": intent, "posting_contract_payload": {"schema_version": "customer-partial-return-posting-contract-v1", "postable": False, "templates": templates}}
    return raw, observed, proposal


def write_fixture(root: Path, *, with_proposal: bool = False, full: bool = False) -> None:
    raw, mapped, proposal = fixture()
    cases = oracle.CASES if full else (oracle.TWO_LAYER,)
    for n, case in enumerate(cases):
        current = copy.deepcopy(raw)
        current["case"] = case
        for number in (2 * n + 1, 2 * n + 2):
            (root / f"native-financial-rows-original-{number}.json").write_text(canonical(current), encoding="utf8")
    for n, case in enumerate(oracle.MAPPED_FULL_CASES if full else (oracle.TWO_LAYER,)):
        current = copy.deepcopy(mapped)
        current["case"] = case
        (root / f"native-source-original-{n + 1}.json").write_text(canonical(current), encoding="utf8")
    if with_proposal:
        (root / oracle.PROPOSAL_NAME).write_text(canonical(proposal), encoding="utf8")


def mutate_row(raw: dict[str, Any], table: str, field: str, value: Any) -> None:
    row = json.loads(raw["tables"][table][0])
    row[field] = value
    raw["tables"][table][0] = canonical(row)
    raw["tables"][table].sort()


@pytest.mark.parametrize("full", [False, True])
def test_original_row_custody_and_declared_financial_scope(tmp_path: Path, full: bool) -> None:
    write_fixture(tmp_path, full=full)
    report = oracle.verify_directory(tmp_path)
    assert report["case_count_with_exact_row_custody"] == (6 if full else 1)
    assert report["case_count_with_independent_financial_oracle"] == 1
    assert report["result"]["original_gl_debit_minor"] == report["result"]["original_gl_credit_minor"] == 131500
    assert (report["result"]["credit_minor"], report["result"]["cogs_restored_minor"], report["result"]["refund_entitlement_delta_minor"]) == (54000, 16000, 0)
    assert report["result"]["actual_proposal_serialization_retained"] is False


def test_retained_unapproved_proposal_matches_independent_accounts_history_portions_and_amounts(tmp_path: Path) -> None:
    write_fixture(tmp_path, with_proposal=True)
    report = oracle.verify_directory(tmp_path)
    assert report["result"]["actual_proposal_serialization_retained"] is True
    assert report["result"]["native_authorization_or_approval_proven"] is False
    assert report["result"]["proposal_posted"] is False


@pytest.mark.parametrize("token", ['{"x":1,"x":2}', 'NaN', 'Infinity', '1e999', '1e-99', '9' * 21, '"' + 'x' * 131073 + '"', '[' * 34 + '0' + ']' * 34], ids=["duplicate", "nan", "infinity", "positive-exponent", "negative-exponent", "integer-bound", "scalar-bound", "depth-bound"])
def test_bounded_strict_json_refuses_duplicate_nonfinite_or_excessive_inputs(token: str) -> None:
    with pytest.raises(oracle.OracleRefusal):
        oracle.decode(token)


@pytest.mark.parametrize("value", [Decimal("1e65"), Decimal("NaN"), Decimal("Infinity"), 1 << 257, True])
def test_direct_exact_quantity_conversion_is_bounded_before_fraction_construction(value: Any) -> None:
    with pytest.raises(oracle.OracleRefusal):
        oracle.fraction(value)


@pytest.mark.parametrize("table,field,value", [
    ("ar_invoices", "total_minor", True), ("ar_invoices", "total_minor", 67500.0),
    ("inventory_layer_consumptions", "value_minor", "12000"),
    ("ar_invoice_lines", "quantity", True), ("ar_invoice_lines", "quantity_text", "15.001"),
    ("finance_posting_effects", "source_kind", "Counterfeit"),
    ("finance_posting_effects", "source_id", "wrong-owned-plan"),
    ("finance_posting_effects", "reverses_effect_id", "effect-cogs"),
    ("commercial_collection_links", "posted_actor_id", "maker"),
    ("operational_finance_links", "source_effect_id", "wrong-invoice"),
    ("ar_invoice_lines", "tenant_id", "other"),
    ("inventory_layer_consumptions", "tenant_id", "other"),
    ("finance_accounts", "tenant_id", "other"),
    ("stock_sales_orders", "quantity_precision", False),
    ("inventory_valuation_lines", "quantity_precision", False),
    ("inventory_movement_lines", "quantity_precision", False),
])
def test_actual_columns_and_source_ownership_refuse_balanced_corruption(table: str, field: str, value: Any) -> None:
    raw, observed, _ = fixture()
    mutate_row(raw, table, field, value)
    with pytest.raises(oracle.OracleRefusal):
        oracle.verify_two_layer(raw, observed)


@pytest.mark.parametrize("kind", ["missing", "duplicate", "swapped", "policy", "scope", "collected", "typed-precision", "typed-consumption-precision"])
def test_raw_or_typed_membership_and_historical_policy_cannot_drift(kind: str) -> None:
    raw, observed, _ = fixture()
    if kind == "missing":
        raw["tables"]["finance_entry_lines"].pop()
    elif kind == "duplicate":
        raw["tables"]["inventory_layer_consumptions"].append(raw["tables"]["inventory_layer_consumptions"][0])
    elif kind == "swapped":
        observed["typed_source"]["consumptions"].reverse()
    elif kind == "policy":
        observed["captured_registry_snapshot"]["currencies"][0]["minor_units"] = 3
    elif kind == "scope":
        observed["typed_source"]["scope"]["tenant_id"] = "other"
    elif kind == "typed-precision":
        observed["typed_source"]["quantity_precision"] = False
    elif kind == "typed-consumption-precision":
        observed["typed_source"]["consumptions"][0]["quantity_precision"] = False
    else:
        observed["typed_source"]["collected_minor"] = 10001
    with pytest.raises(oracle.OracleRefusal):
        oracle.verify_two_layer(raw, observed)


@pytest.mark.parametrize("numbers", [(0, 2), (1, 3)])
def test_coherently_resealed_cash_lines_still_require_original_one_two_sequence(numbers: tuple[int, int]) -> None:
    raw, observed, _ = fixture()
    tables = {name: [json.loads(row) for row in rows] for name, rows in raw["tables"].items()}
    effect = next(row for row in tables["finance_posting_effects"] if row["id"] == "effect-cash")
    actual = sorted((row for row in tables["finance_entry_lines"] if row["entry_id"] == "cash"), key=lambda row: row["line_number"])
    for row, frozen, number in zip(actual, effect["snapshot_json"]["lines"], numbers, strict=True):
        row["line_number"] = frozen["line_number"] = number
    effect["validation_digest"] = digest(effect["snapshot_json"])
    next(row for row in tables["finance_entries"] if row["id"] == "cash")["validation_digest"] = effect["validation_digest"]
    collection = tables["commercial_collection_plans"][0]
    collection["payload"]["snapshot"] = effect["snapshot_json"]
    collection["payload"]["validation_digest"] = effect["validation_digest"]
    evidence = json.loads(observed["collection_evidence_json"])
    evidence[0]["posting_effect"] = effect
    observed["collection_evidence_json"] = canonical(evidence)
    raw["tables"] = {name: sorted(canonical(row) for row in rows) for name, rows in tables.items()}
    with pytest.raises(oracle.OracleRefusal):
        oracle.verify_two_layer(raw, observed)


@pytest.mark.parametrize("kind,value", [("changed", 1), ("boolean", False), ("null", None), ("fractional-token", 0.0), ("missing", None)])
def test_coherent_before_after_layer_precision_drift_is_not_an_original_zero_scale(tmp_path: Path, kind: str, value: Any) -> None:
    write_fixture(tmp_path)
    raw = json.loads((tmp_path / "native-financial-rows-original-1.json").read_text(encoding="utf8"))
    layer = json.loads(raw["tables"]["inventory_cost_layers"][0])
    if kind == "missing":
        layer.pop("quantity_precision")
    else:
        layer["quantity_precision"] = value
    raw["tables"]["inventory_cost_layers"][0] = canonical(layer)
    raw["tables"]["inventory_cost_layers"].sort()
    # Both original envelopes agree; rejection must come from the independent
    # finite financial scope, rather than a before/after byte drift alone.
    for number in (1, 2):
        (tmp_path / f"native-financial-rows-original-{number}.json").write_text(canonical(raw), encoding="utf8")
    with pytest.raises(oracle.OracleRefusal):
        oracle.verify_directory(tmp_path)


@pytest.mark.parametrize("kind", ["source", "history", "plan", "roles", "amount", "account", "dimensions", "effect", "postable", "inverse", "approval", "zero-line"])
def test_balanced_unposted_proposal_drift_is_refused(kind: str) -> None:
    raw, observed, proposal = fixture()
    template = proposal["posting_contract_payload"]["templates"][0]
    if kind in {"source", "history"}:
        proposal["plan_payload"][kind + "_fingerprint"] = "0" * 64
    elif kind == "plan":
        proposal["plan_payload"]["credit_minor"] = 54001
    elif kind == "roles":
        proposal["account_roles_payload"]["accounts"]["receivable_account_id"] = "CASH"
    elif kind == "amount":
        template["lines"][0]["debit_minor"] = template["lines"][1]["credit_minor"] = 54001
    elif kind == "account":
        template["lines"][0]["account_id"] = "COGS"
    elif kind == "dimensions":
        template["lines"][0]["dimensions"] = {"cost-center": "other"}
    elif kind == "effect":
        template["original_posting_effect_id"] = "effect-cogs"
    elif kind == "postable":
        proposal["posting_contract_payload"]["postable"] = True
    elif kind == "inverse":
        template["reverses_posting_id"] = "effect-revenue"
    elif kind == "approval":
        template["requires_three_person_approval"] = 1
    else:
        template["lines"].append({**template["lines"][0], "line_number": 3, "debit_minor": 0})
    with pytest.raises(oracle.OracleRefusal):
        oracle.verify_two_layer(raw, observed, proposal)


@pytest.mark.parametrize("kind", ["after-change", "duplicate-file", "missing-table", "wrong-case", "ancestor-link"])
def test_directory_membership_row_bytes_and_ancestry_are_bound(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str) -> None:
    write_fixture(tmp_path)
    path = tmp_path / "native-financial-rows-original-2.json"
    if kind in {"after-change", "missing-table", "wrong-case"}:
        raw = json.loads(path.read_text(encoding="utf8"))
        if kind == "after-change":
            raw["retained_state_digest"] = "b" * 64
        elif kind == "missing-table":
            raw["tables"].pop("inventory_items")
        else:
            raw["case"] = oracle.CASES[1]
        path.write_text(canonical(raw), encoding="utf8")
    elif kind == "duplicate-file":
        (tmp_path / "native-financial-rows-original-02.json").write_bytes(path.read_bytes())
    else:
        original = Path.is_symlink
        monkeypatch.setattr(Path, "is_symlink", lambda p: p == tmp_path.parent or original(p))
    with pytest.raises(oracle.OracleRefusal):
        oracle.verify_directory(tmp_path)


def test_isolated_and_optimized_cli_proofs_equal_and_unsafe_input_refuses_without_output(tmp_path: Path) -> None:
    source = Path(oracle.__file__).resolve()
    originals = tmp_path / "originals"
    originals.mkdir()
    write_fixture(originals, with_proposal=True)
    outputs: list[bytes] = []
    for flags in (["-I"], ["-I", "-O"]):
        output = tmp_path / (str(len(outputs)) + ".json")
        result = subprocess.run([sys.executable, *flags, str(source), str(originals), "--output", str(output)], capture_output=True, timeout=30, check=False)
        assert result.returncode == 0 and result.stderr == b""
        outputs.append(output.read_bytes())
    assert outputs[0] == outputs[1]
    proposal_path = originals / oracle.PROPOSAL_NAME
    proposal = json.loads(proposal_path.read_text(encoding="utf8"))
    proposal["posting_contract_payload"]["postable"] = True
    proposal_path.write_text(canonical(proposal), encoding="utf8")
    output = tmp_path / "refused.json"
    result = subprocess.run([sys.executable, "-I", "-O", str(source), str(originals), "--output", str(output)], capture_output=True, timeout=30, check=False)
    assert result.returncode == 1 and not output.exists()
    assert result.stdout == b"" and b"Independent native source oracle refused." in result.stderr


def test_late_oversized_drift_is_rechecked_with_bounded_single_reads(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_fixture(tmp_path)
    original = oracle.verify_two_layer

    def grow(envelope: dict[str, Any], observed: dict[str, Any], proposal: dict[str, Any] | None = None) -> dict[str, Any]:
        result = original(envelope, observed, proposal)
        (tmp_path / "native-financial-rows-original-2.json").write_bytes(b"x" * (oracle.MAX_BYTES + 1))
        return result

    monkeypatch.setattr(oracle, "verify_two_layer", grow)
    with pytest.raises(oracle.OracleRefusal):
        oracle.verify_directory(tmp_path)


def test_standalone_oracle_has_no_application_import_or_assertion() -> None:
    tree = ast.parse(Path(oracle.__file__).read_text(encoding="utf8"))
    for node in ast.walk(tree):
        assert not isinstance(node, ast.Assert)
        if isinstance(node, ast.Import):
            assert all(not alias.name.startswith(("reconforge", "tests", "psycopg", "pytest", "playwright")) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert not (node.module or "").startswith(("reconforge", "tests", "psycopg", "pytest", "playwright"))
