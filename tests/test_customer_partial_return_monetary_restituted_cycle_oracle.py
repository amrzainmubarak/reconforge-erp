"""Finite zero-original controls; no production arithmetic or PostgreSQL calls."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from tests import customer_partial_return_monetary_restituted_cycle_oracle as reader
from tests.test_customer_partial_return_monetary_posted_oracle import original_tables


def encoded(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def envelope() -> dict[str, Any]:
    return {"schema_version": reader.SCHEMA, "tenant_id": "tenant", "original_source_order_id": "old-stock", "resale_source_order_id": "new-stock",
            "captures": [{"checkpoint": label, "tables": {name: [] for name in reader.TABLES}} for label in reader.CHECKPOINTS]}


def zero_original() -> dict[str, list[str]]:
    """Literal native-shaped USD0.1/net100/tax14/zero COGS source facts."""
    tables = {name: [json.loads(raw) for raw in rows] for name, rows in original_tables(foreign=False).items()}
    stock = tables["stock_sales_orders"][0]
    declared = stock["source"]
    declared.update(quantity="0.1", quantity_scaled=1, unit_price_minor=1000, net_unit_price_minor=1000, total_minor=100)
    stock.update(quantity_scaled=1, quantity_precision=1, total_minor=100, cogs_entry_id=None, cogs_effect_id=None, source_digest=reader._digest(declared))
    issue = {"schema_version": "stock-sales-issue-v2", "total_cost_minor": 0, "cost_admission_policy": "partial-return-restituted-v1", "entry_id": None,
             "allocations": [{"cost_layer_id": "layer", "quantity_scaled": 1, "value_minor": 0}], "restitution_cost_snapshot": {"private": "prior original rows"}}
    stock["issue_plan"] = issue
    invoice = tables["ar_invoices"][0]
    invoice.update(subtotal_minor=100, tax_minor=14, total_minor=114)
    line = tables["ar_invoice_lines"][0]
    line.update(quantity=0, quantity_text="0.1", unit_price_minor=1000, line_total_minor=100, tax_minor=14)
    # JSON exact decimals use native numeric lexemes, handled below without float.
    fx = tables["operational_fx_sources"][0]["payload"]
    fx["stock_source_digest"] = stock["source_digest"]
    fx["request"]["net_minor"] = 100
    fx.update(foreign_net_minor=100, foreign_tax_minor=14, foreign_gross_minor=114, functional_net_minor=100, functional_gross_minor=114)
    fx["tax_components"][0].update(foreign_tax_minor=14, functional_tax_minor=14)
    fx["source_digest"] = reader._digest({key: value for key, value in fx.items() if key != "source_digest"})
    tables["finance_posting_effects"] = [row for row in tables["finance_posting_effects"] if row["id"] == "revenue-effect"]
    tables["finance_entries"] = [row for row in tables["finance_entries"] if row["id"] == "revenue-entry"]
    tables["finance_entry_lines"] = [row for row in tables["finance_entry_lines"] if row["entry_id"] == "revenue-entry"]
    effect, entry = tables["finance_posting_effects"][0], tables["finance_entries"][0]
    vectors = [("receivable", 114, 0), ("revenue", 0, 100), ("tax", 0, 14)]
    for raw, sealed, (account, debit, credit) in zip(tables["finance_entry_lines"], effect["snapshot_json"]["lines"], vectors, strict=True):
        assert account == raw["account_id"] == sealed["account_id"]
        raw.update(debit_minor=debit, credit_minor=credit)
        sealed.update(debit_minor=debit, credit_minor=credit)
    effect["validation_digest"] = entry["validation_digest"] = reader._digest(effect["snapshot_json"])
    entry.update(total_debit_minor=114, total_credit_minor=114)
    tables["inventory_layer_consumptions"][0].update(quantity_scaled=1, value_minor=0)
    tables["inventory_valuation_documents"][0]["finance_entry_id"] = None
    origin = tables["stock_sales_monetary_origins"][0]
    body, source, evidence = origin["payload"], origin["payload"]["source"], origin["payload"]["evidence"]
    source.update(quantity_scaled=1, quantity_precision=1, original_cost_admission_digest=reader._digest(issue))
    source["consumptions"][0].update(quantity_scaled=1, value_minor=0)
    for component, amounts in zip(source["components"], ((100, 100), (14, 14)), strict=True):
        component.update(transaction_minor=amounts[0], functional_minor=amounts[1])
    source["components"][0]["policy_digest"] = reader._digest({"stock_source_digest": stock["source_digest"], "discount_policy": declared["discount_policy"]})
    body["equation"] = {key: value for key, value in fx.items() if key not in {"schema_version", "id", "workspace_id", "organization_id", "legal_entity_id", "preparer_actor_id", "invoice_id", "source_digest", "stock_order_id", "stock_source_digest"}}
    evidence.update(stock_source=declared, stock_source_digest=stock["source_digest"], issue_plan=issue, cogs_entry_id=None, cogs_effect_id=None, cogs_snapshot=None,
                    recognition_snapshot=effect["snapshot_json"], fx_source=fx,
                    invoice_original={key: invoice[key] for key in ("customer_id", "currency_code", "invoice_number", "invoice_date", "due_date", "subtotal_minor", "tax_minor", "total_minor")})
    evidence["consumptions"] = source["consumptions"]
    evidence["invoice_line"] = {**{key: value for key, value in line.items() if key not in {"tenant_id", "quantity"}}, "quantity_native_text": "0.1"}
    source["native_origin_digest"] = reader._digest(evidence)
    origin["source_digest"] = reader._digest(body)
    raw = {name: sorted(json.dumps(row, sort_keys=True) for row in rows) for name, rows in tables.items()}
    raw["ar_invoice_lines"] = [raw["ar_invoice_lines"][0].replace('"quantity": 0', '"quantity": 0.1')]
    return raw


def capture(tables: dict[str, list[str]]) -> Any:
    return reader.base.decode_capture({"capture": 2, "tables": tables}, index=2, tenant_id="tenant")


def test_explicit_zero_original_joins_actual_recognition_tax_and_null_cost_without_relaxing_old_reader() -> None:
    facts = reader.verify_zero_original_rows(capture(zero_original()), source_order_id="stock")
    assert facts.components == ((100, 100), (14, 14)) and facts.fifo == ((1, 0),)
    with pytest.raises(reader.base.MonetaryRawRefusal):
        reader.base.verify_original_rows(capture(zero_original()), source_order_id="stock")


@pytest.mark.parametrize("table,field,bad", [
    ("inventory_layer_consumptions", "value_minor", 1), ("stock_sales_orders", "cogs_effect_id", "cogs-effect"),
    ("inventory_valuation_documents", "finance_entry_id", "cogs-entry"), ("ar_invoice_lines", "quantity", True),
])
def test_zero_original_requires_native_absence_and_exact_quantity(table: str, field: str, bad: Any) -> None:
    tables = zero_original()
    value = json.loads(tables[table][0])
    value[field] = bad
    tables[table] = [json.dumps(value, sort_keys=True)]
    with pytest.raises(reader.base.MonetaryRawRefusal):
        reader.verify_zero_original_rows(capture(tables), source_order_id="stock")


def test_declared_zero_original_policy_is_not_a_substitute_for_immutable_cost_admission_digest() -> None:
    tables = zero_original()
    origin = json.loads(tables["stock_sales_monetary_origins"][0])
    origin["payload"]["source"]["original_cost_admission_digest"] = "f" * 64
    origin["source_digest"] = reader._digest(origin["payload"])
    tables["stock_sales_monetary_origins"] = [json.dumps(origin, sort_keys=True)]
    with pytest.raises(reader.base.MonetaryRawRefusal):
        reader.verify_zero_original_rows(capture(tables), source_order_id="stock")


def test_exact_six_stage_contract_preserves_every_raw_row_and_parent_hash() -> None:
    value = envelope()
    value["captures"][0]["tables"]["finance_accounts"] = ['{"tenant_id": "tenant", "id": "raw-original"}']
    original = encoded(value)
    packet = reader.decode_packet(original)
    assert len(packet.captures) == 6 and packet.sha256 == hashlib.sha256(original).hexdigest()
    assert dict(packet.captures[0].raw_tables)["finance_accounts"] == ('{"tenant_id": "tenant", "id": "raw-original"}',)
    with pytest.raises(reader.base.MonetaryRawRefusal):
        reader.qualify_raw_cycle(packet)


@pytest.mark.parametrize("table", reader.TABLES)
def test_no_raw_table_can_be_dropped_even_when_empty(table: str) -> None:
    value = envelope()
    del value["captures"][3]["tables"][table]
    with pytest.raises(reader.base.MonetaryRawRefusal):
        reader.decode_packet(encoded(value))


@pytest.mark.parametrize("mutation", ["extra-main", "extra-capture", "same-source", "missing-stage", "stage-order", "duplicate", "foreign", "bool-stage"])
def test_closed_sources_stages_and_original_rows(mutation: str) -> None:
    value = envelope()
    if mutation == "extra-main":
        value["expected_total"] = 233
    elif mutation == "extra-capture":
        value["captures"][0]["derived"] = True
    elif mutation == "same-source":
        value["resale_source_order_id"] = value["original_source_order_id"]
    elif mutation == "missing-stage":
        value["captures"].pop()
    elif mutation == "stage-order":
        value["captures"].reverse()
    elif mutation == "bool-stage":
        value["captures"][0]["checkpoint"] = True
    else:
        value["captures"][0]["tables"]["finance_accounts"] = ['{"tenant_id":"other"}'] if mutation == "foreign" else ['{"tenant_id":"tenant"}'] * 2
    with pytest.raises(reader.base.MonetaryRawRefusal):
        reader.decode_packet(encoded(value))


def test_zero_partial_components_cannot_create_a_fake_gl_leg() -> None:
    source = reader.verify_zero_original_rows(capture(zero_original()), source_order_id="stock")
    event = reader.base._next_event(source, [], {"kind": "Return", "quantity_scaled": 1, "amount_minor": 0, "posting_date": "2026-10-15", "settlement_rate": None, "original_sequence": None})
    assert event["monetary"]["transaction_credit_minor"] == event["monetary"]["functional_credit_minor"] == 114
    assert event["monetary"]["functional_cost_minor"] == 0
    assert reader.base._journals(source, event) == [("MerchandiseCredit", [("revenue", 100, 0), ("tax", 14, 0), ("receivable", 0, 114)])]


@pytest.mark.parametrize("optimized", [False, True])
def test_isolated_cli_refuses_empty_raw_tables_without_a_success_proof(tmp_path: Path, optimized: bool) -> None:
    source = tmp_path / "original.json"
    source.write_bytes(encoded(envelope()))
    output = tmp_path / "proof.json"
    command = [sys.executable, "-I", *(["-O"] if optimized else []), str(Path(reader.__file__).absolute()), "--input", str(source), "--output", str(output)]
    completed = subprocess.run(command, capture_output=True, timeout=20, check=False)
    assert completed.returncode == 2 and not output.exists() and b"Independent monetary restituted raw input refused." in completed.stderr


def test_frozen_positive_reader_bytes_are_unmodified() -> None:
    assert hashlib.sha256(reader.BASE_PATH.read_bytes()).hexdigest() == reader.BASE_SHA256


def test_new_reader_uses_only_stdlib_and_frozen_independent_raw_validation() -> None:
    text = Path(reader.__file__).read_text(encoding="utf-8")
    assert "from reconforge" not in text and "import reconforge" not in text
    assert "later_dependency_refusal_proven\": False" in text
    assert "current_authorization_proven\": False" in text


def receipt_event_fixture() -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    """Minimal literal event-affinity facts; full financial joins are checked separately."""
    tables: dict[str, list[dict[str, Any]]] = {name: [] for name in reader.TABLES}
    scope = {"tenant_id": "tenant", "workspace_id": "work", "organization_id": "org", "legal_entity_id": "entity"}
    snapshot = {"entry": {"id": "receipt-entry"}, "lines": []}
    finance_digest = reader._digest(snapshot)
    body = {"contract_version": "inventory-receipt-plan-v1", "plan_id": "receipt", "plan_version": 1,
            "operation": "Receipt", "original": None, "scope": {**{k: scope[k] for k in scope if k != "tenant_id"},
                "organization_code": "ORG", "entity_code": "ENTITY"},
            "preparer": {"user_id": "maker", "username": "maker"}, "finance_snapshot": snapshot,
            "finance_validation_digest": finance_digest, "artifacts": {"movement_id": "receipt-movement",
                "finance_entry_id": "receipt-entry", "posting_effect_id": "receipt-effect"},
            "preparation_audit_event_id": "prepared-audit", "preparation_outbox_event_id": "prepared-outbox"}
    body["plan_digest"] = reader._digest({k: v for k, v in body.items() if k not in {"preparation_audit_event_id", "preparation_outbox_event_id"}})
    plan = {**scope, "id": "receipt", "plan_json": body, "plan_version": 1, "operation": "Receipt",
            "movement_id": "receipt-movement", "finance_entry_id": "receipt-entry", "plan_digest": body["plan_digest"],
            "finance_validation_digest": finance_digest, "preparer_actor_id": "maker", "preparer_username": "maker",
            "preparation_audit_event_id": "prepared-audit", "preparation_outbox_event_id": "prepared-outbox"}
    reviewed = {"contract_version": "inventory-receipt-review-v1", "review_id": "review", "plan_id": "receipt", "plan_version": 1,
                "plan_digest": body["plan_digest"], "finance_validation_digest": finance_digest,
                "reviewer": {"user_id": "checker", "username": "checker"}, "audit_event_id": "reviewed-audit", "outbox_event_id": "reviewed-outbox"}
    reviewed["review_digest"] = reader._digest({k: v for k, v in reviewed.items() if k not in {"audit_event_id", "outbox_event_id"}})
    review = {**scope, **{k: reviewed[k] for k in ("plan_id", "plan_version", "plan_digest", "finance_validation_digest", "review_digest", "audit_event_id", "outbox_event_id")},
              "id": "review", "review_json": reviewed, "reviewer_actor_id": "checker", "reviewer_username": "checker"}
    link = {**scope, **body["artifacts"], "plan_id": "receipt", "review_id": "review", "posted_actor_id": "poster",
            "plan_digest": body["plan_digest"], "review_digest": reviewed["review_digest"], "audit_event_id": "committed-audit", "outbox_event_id": "committed-outbox"}
    tables["inventory_receipt_plans"] = [plan]
    tables["inventory_receipt_reviews"] = [review]
    tables["inventory_receipt_links"] = [link]
    tables["finance_entries"] = [{"tenant_id": "tenant", "id": "receipt-entry", "organization_code": "ORG", "entity_code": "ENTITY"}]
    tables["finance_posting_effects"] = [{**scope, "id": "receipt-effect", "snapshot_json": snapshot,
                                           "validation_digest": finance_digest, "posted_actor_id": "poster"}]
    head = {**scope, "id": "receipt-movement"}
    lines = [{"tenant_id": "tenant", "id": "receipt-line", "movement_id": "receipt-movement", "line_number": 1}]
    tables["inventory_movements"], tables["inventory_movement_lines"] = [head], lines
    common = {"plan_digest": body["plan_digest"], "finance_validation_digest": finance_digest}
    for sequence, (stage, actor, metadata) in enumerate((
        ("prepared", "maker", common), ("reviewed", "checker", {**common, "review_digest": reviewed["review_digest"]}),
        ("committed", "poster", {**common, "review_digest": reviewed["review_digest"], "effect_id": "receipt-effect"}),
    ), 1):
        action = "inventory_receipt_" + stage
        tables["domain_audit_events"].append({"tenant_id": "tenant", "id": stage + "-audit", "sequence": sequence,
            "actor_user_id": actor, "object_type": "inventory_receipt_posting", "object_id": "receipt", "action": action, "metadata_json": dict(metadata)})
        tables["outbox_events"].append({**scope, "event_id": stage + "-outbox", "aggregate_type": "inventory_receipt_posting",
            "aggregate_id": "receipt", "event_type": action, "payload": {**metadata, "audit_event_id": stage + "-audit"}, "created_at": "2026-10-15T00:00:00Z"})
    return tables, {"head": head, "lines": lines, "audit": [], "outbox": []}


def receipt_capture(tables: dict[str, list[dict[str, Any]]]) -> Any:
    return capture({name: sorted(json.dumps(row, sort_keys=True) for row in rows) for name, rows in tables.items()})


def test_real_irp_event_contract_accepts_empty_generic_snapshot_only_for_receipt() -> None:
    tables, supplied = receipt_event_fixture()
    facts = receipt_capture(tables)
    reader._receipt_native(facts, facts.rows("inventory_receipt_plans")[0], supplied)
    with pytest.raises(reader.base.MonetaryRawRefusal):
        reader._native(facts, "receipt-movement", supplied)


@pytest.mark.parametrize("stage", ["prepared", "reviewed", "committed"])
@pytest.mark.parametrize("mutation", ["missing-audit", "missing-outbox", "action", "actor", "scope", "digest", "event-link"])
def test_irp_receipt_requires_each_exact_source_owned_event_pair(stage: str, mutation: str) -> None:
    tables, supplied = receipt_event_fixture()
    audit = next(row for row in tables["domain_audit_events"] if row["id"] == stage + "-audit")
    outbox = next(row for row in tables["outbox_events"] if row["event_id"] == stage + "-outbox")
    if mutation == "missing-audit":
        tables["domain_audit_events"].remove(audit)
    elif mutation == "missing-outbox":
        tables["outbox_events"].remove(outbox)
    elif mutation == "action":
        audit["action"] = "inventory_receipt_prepared" if stage != "prepared" else "inventory_receipt_committed"
    elif mutation == "actor":
        audit["actor_user_id"] = "different-human"
    elif mutation == "scope":
        outbox["organization_id"] = "different-organization"
    elif mutation == "digest":
        audit["metadata_json"]["plan_digest"] = "f" * 64
    else:
        outbox["payload"]["audit_event_id"] = "unrelated-audit"
    facts = receipt_capture(tables)
    with pytest.raises(reader.base.MonetaryRawRefusal):
        reader._receipt_native(facts, facts.rows("inventory_receipt_plans")[0], supplied)


@pytest.mark.parametrize("event", ["audit", "outbox", "both"])
def test_irp_receipt_refuses_propagated_generic_movement_events(event: str) -> None:
    tables, supplied = receipt_event_fixture()
    if event in {"audit", "both"}:
        row = {"tenant_id": "tenant", "id": "generic-audit", "sequence": 4, "object_type": "inventory_movement", "object_id": "receipt-movement"}
        tables["domain_audit_events"].append(row)
        supplied["audit"] = [row]
    if event in {"outbox", "both"}:
        row = {**{key: "tenant" if key == "tenant_id" else "work" if key == "workspace_id" else "org" if key == "organization_id" else "entity" for key in ("tenant_id", "workspace_id", "organization_id", "legal_entity_id")},
               "event_id": "generic-outbox", "event_type": "posted", "aggregate_type": "inventory_movement", "aggregate_id": "receipt-movement", "payload": {}, "created_at": "2026-10-15T00:00:00Z"}
        tables["outbox_events"].append(row)
        supplied["outbox"] = [row]
    facts = receipt_capture(tables)
    with pytest.raises(reader.base.MonetaryRawRefusal):
        reader._receipt_native(facts, facts.rows("inventory_receipt_plans")[0], supplied)
