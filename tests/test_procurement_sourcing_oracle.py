"""Adversarial checks of the independent stdlib evidence verifier."""
from __future__ import annotations

import ast
import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / ".github/scripts/verify_procurement_sourcing_oracle.py"
spec = importlib.util.spec_from_file_location("independent_sourcing_oracle", SCRIPT)
assert spec and spec.loader
oracle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(oracle)


def packet() -> dict[str, Any]:
    scope = {"workspace_id": "work", "organization_id": "org", "legal_entity_id": "entity"}
    def row(**fields: Any) -> dict[str, Any]:
        return {"tenant_id": "synthetic", **scope, **fields}
    lines = [{"item_code": "ITEM", "quantity": "2", "unit_price_minor": 1000, "location_code": "STORE"},
             {"item_code": "WEIGHT", "quantity": "1.00", "unit_price_minor": 2000, "location_code": "WAREHOUSE"}]
    original = {"number": "SRC5-ORACLE", "supplier_code": "SUP", "currency_code": "USD", "period_id": "period", "ap_account_code": "AP", "cash_account_code": "CASH", "lines": lines}
    payload = {"scope": scope, "request": {"order": original}, "ceiling_minor": 4000, "currency_precision": 2}
    source = row(id="source", payload=payload, source_digest=oracle.seal(payload), phase=3, row_version=6, ceiling_minor=4000, selected_quote_id="SUP", order_id="order", budget_id="budget")
    quotes = []
    for version, supplier, prices in ((3, "ALT", [600, 2000]), (4, "SUP", [500, 2000])):
        order = {**original, "number": "BPC1-SRC5-ORACLE", "supplier_code": supplier,
                 "lines": [{**line, "unit_price_minor": price} for line, price in zip(lines, prices, strict=True)]}
        quotation = {"supplier_code": supplier, "unit_prices_minor": prices, "valid_until": "2026-10-31", "reason": "Original offer"}
        value = {"order": order, "quotation": quotation, "total_minor": oracle.exact_total(order["lines"]), "source_digest": source["source_digest"],
                 "requisition_id": "source", "registrar_actor_id": "maker", "supplier_id": supplier}
        quotes.append(row(id=supplier, supplier_id=supplier, supplier_code=supplier, payload=value, quote_digest=oracle.seal(value),
                          total_minor=value["total_minor"], requisition_id="source", registrar_actor_id="maker", created_version=version))
    history, commands, audits, outbox = [], [], [], []
    for version, (operation, actor) in enumerate((('create', 'maker'), ('open-rfq', 'checker'), ('quote', 'maker'), ('quote', 'maker'), ('review-selection', 'checker'), ('award', 'poster')), 1):
        request = {"quotation": quotes[version - 3]["payload"]["quotation"]} if operation == "quote" else {"reason": "Independent approval"}
        envelope = {"operation": operation, "actor_id": actor, "request": request}
        event = row(requisition_id="source", version=version, operation=operation, actor_id=actor, command_id="cmd" + str(version),
                    request_json=envelope, request_digest=oracle.seal(envelope), reason="Original evidence", audit_event_id="audit" + str(version), outbox_event_id="outbox" + str(version))
        metadata = {"source_digest": source["source_digest"], **{key: event[key] for key in ("command_id", "request_digest", "version", "operation", "reason")}}
        audit = row(id=event["audit_event_id"], object_type="procurement_sourcing", object_id="source", actor_user_id=actor,
                    action="procurement_sourcing_" + operation, metadata_json=metadata)
        published = row(event_id=event["outbox_event_id"], aggregate_type="procurement_sourcing", aggregate_id="source", event_type=audit["action"], payload={**metadata, "audit_event_id": audit["id"]})
        ack = {"id": "source", "row_version": version, "source_digest": source["source_digest"], **scope,
               "evidence": {"audit_event_id": audit["id"], "outbox_event_id": published["event_id"], "request_digest": event["request_digest"]}}
        history.append(event)
        audits.append(audit)
        outbox.append(published)
        commands.append(row(**{key: event[key] for key in ("requisition_id", "version", "actor_id", "command_id", "request_json", "request_digest")}, response_json=ack))
    winning = quotes[1]["payload"]["order"]
    owner_payload = {"order_request": winning, "scope": scope, "amount_minor": 3000}
    owner = row(order_id="order", budget_id="budget", commitment_id="commitment", reserve_event_id="reserve", payload=owner_payload, plan_digest=oracle.seal(owner_payload))
    native_lines = [row(id="line" + str(index), sequence=index + 1, order_id="order", item_id="item" + str(index), quantity_text=line["quantity"], total_minor=oracle.exact_total([line]), **{k: line[k] for k in ("item_code", "unit_price_minor", "location_code")}, location_id="location" + str(index)) for index, line in enumerate(winning["lines"])]
    receipts, plans, links, layers, parts = [], [], [], [], []
    for index, (qty, scaled, precision, value) in enumerate((('1', 1, 0, 500), ('0.50', 50, 2, 1000))):
        line = native_lines[index]
        receipts.append(row(id="receipt" + str(index), order_line_id=line["id"], quantity_text=qty, total_minor=value, stage=2, receipt_plan_id="plan" + str(index)))
        plans.append(row(id="plan" + str(index), operation="Receipt", total_value_minor=value, quantity_scaled=scaled, quantity_precision=precision, item_id=line["item_id"], location_id=line["location_id"],
                         currency_code="USD", currency_precision=2, inventory_account_id="INV", receipt_clearing_account_id="CLEAR", posting_effect_id="receipt-effect" + str(index), cost_layer_id="layer" + str(index)))
        links.append(row(plan_id=plans[-1]["id"], posting_effect_id=plans[-1]["posting_effect_id"], cost_layer_id=plans[-1]["cost_layer_id"]))
        layers.append(row(id=plans[-1]["cost_layer_id"], original_value_minor=value, remaining_value_minor=value, original_quantity_scaled=scaled, remaining_quantity_scaled=scaled))
        parts.append(row(id="part" + str(index), invoice_id="invoice", order_line_id=line["id"], quantity_text=qty, total_minor=value))
    def effect(identifier: str, debit: str, credit: str, value: int) -> dict[str, Any]:
        snapshot = {"entry": {**scope, "currency_code": "USD"}, "lines": [{"account_id": debit, "debit_minor": value, "credit_minor": 0}, {"account_id": credit, "debit_minor": 0, "credit_minor": value}]}
        return row(id=identifier, snapshot_json=snapshot, validation_digest=oracle.seal(snapshot), currency_code="USD", currency_precision=2)
    budget_events = [row(id=identity, budget_id="budget", commitment_id="commitment", operation=operation, amount_minor=amount, remaining_minor=remaining, budget_version=version)
                     for version, (identity, operation, amount, remaining) in enumerate((('reserve', 'Reserve', 3000, 3000), ('consume', 'Consume', 1500, 1500), ('release', 'Release', 1500, 0)), 4)]
    owners = []
    for event in budget_events:
        request = {"operation": {'Reserve': 'create', 'Consume': 'consume', 'Release': 'release'}[event["operation"]], "actor_id": "poster", "request": {"reason": "Original native source"}}
        owners.append(row(budget_event_id=event["id"], operation=request["operation"], order_id="order", invoice_id="invoice" if event["operation"] == "Consume" else None, request_json=request, request_digest=oracle.seal(request)))
    return {"schema_version": "sourcing-oracle-v1", "source": source, "quotes": quotes, "source_events": history,
        "source_commands": commands, "source_audits": audits, "source_outbox": outbox, "commitment": owner, "commitment_commands": owners,
        "budget": row(id="budget", currency_code="USD", currency_precision=2, period_id="period", limit_minor=5000, reserved_minor=0, consumed_minor=1500), "budget_events": budget_events,
        "native": {"order": row(id="order", request_json=winning, total_minor=3000, creator_actor_id="poster"), "lines": native_lines, "receipts": receipts,
            "receipt_plans": plans, "receipt_links": links, "layers": layers, "layer_consumptions": [], "invoices": [row(id="invoice", native_invoice_id="native-invoice", stage=4, total_minor=1500, accrual_effect_id="ap-effect")],
            "invoice_lines": parts, "native_invoices": [row(id="native-invoice", total_minor=1500, tax_minor=0, currency_code="USD", status="Paid")],
            "payments": [row(id="payment1", supplier_invoice_id="native-invoice", amount_minor=600, posting_effect_id="pay1"), row(id="payment2", supplier_invoice_id="native-invoice", amount_minor=900, posting_effect_id="pay2")],
            "accounts": [row(id=account, account_code=account) for account in ('INV', 'CLEAR', 'AP', 'CASH')],
            "effects": [effect('receipt-effect0', 'INV', 'CLEAR', 500), effect('receipt-effect1', 'INV', 'CLEAR', 1000), effect('ap-effect', 'CLEAR', 'AP', 1500), effect('pay1', 'AP', 'CASH', 600), effect('pay2', 'AP', 'CASH', 900)]}}


def test_independent_oracle_exact_hand_calculated_mixed_units_and_partial_settlements() -> None:
    result = oracle.verify(packet())
    assert {key: result[key] for key in ("awarded_minor", "received_minor", "consumed_minor", "paid_minor", "released_minor", "source_reserved_minor", "budget_available_minor", "effect_count")} == {
        "awarded_minor": "3000", "received_minor": "1500", "consumed_minor": "1500", "paid_minor": "1500", "released_minor": "1500", "source_reserved_minor": "0", "budget_available_minor": "3500", "effect_count": 5}


def test_native_first_line_compatibility_header_must_exactly_match_retained_multiline_order() -> None:
    value = packet()
    value["native"]["order"]["request_json"] = {**value["native"]["order"]["request_json"], **value["native"]["order"]["request_json"]["lines"][0]}
    assert oracle.verify(value)["verified"] is True
    value["native"]["order"]["request_json"]["quantity"] = "3"
    with pytest.raises(oracle.OracleError, match="compatibility"):
        oracle.verify(value)


@pytest.mark.parametrize("tamper", ('tenant', 'scope', 'quote', 'selection', 'history', 'evidence', 'ack', 'fifo', 'consume', 'oversettle', 'gl'))
def test_independent_oracle_refuses_detached_or_balanced_resealed_false_financial_evidence(tamper: str) -> None:
    value = copy.deepcopy(packet())
    if tamper == 'tenant':
        value['native']['payments'][0]['tenant_id'] = 'foreign'
    elif tamper == 'scope':
        value['budget']['legal_entity_id'] = 'foreign'
    elif tamper == 'quote':
        quote = value['quotes'][0]
        quote['payload']['order']['lines'][0]['quantity'] = '3'
        quote['quote_digest'] = oracle.seal(quote['payload'])
    elif tamper == 'selection':
        value['source']['selected_quote_id'] = 'ALT'
    elif tamper == 'history':
        value['source_events'].append(value['source_events'][0])
    elif tamper == 'evidence':
        value['source_outbox'][0]['payload']['version'] = 99
    elif tamper == 'ack':
        value['source_commands'][0]['response_json']['row_version'] = 99
    elif tamper == 'fifo':
        value['native']['layers'][0]['remaining_value_minor'] = 499
    elif tamper == 'consume':
        value['budget_events'][1]['amount_minor'] = 1499
    elif tamper == 'oversettle':
        value['native']['payments'][0]['amount_minor'] = 601
    else:
        effect = value['native']['effects'][0]
        effect['snapshot_json']['lines'][0]['debit_minor'] = 499
        effect['snapshot_json']['lines'][1]['credit_minor'] = 499
        effect['validation_digest'] = oracle.seal(effect['snapshot_json'])
    with pytest.raises(oracle.OracleError):
        oracle.verify(value)


@pytest.mark.parametrize('bad', (1.5, float('nan'), float('inf'), True, '1e3', '-1', '01'))
def test_independent_oracle_rejects_unsafe_financial_numbers(bad: Any) -> None:
    with pytest.raises(oracle.OracleError):
        oracle.integer(bad)


def test_oracle_uses_only_stdlib_and_runs_in_isolated_python(tmp_path: Path) -> None:
    allowed = {'__future__', 'argparse', 'hashlib', 'json', 're', 'fractions', 'pathlib', 'typing'}
    tree = ast.parse(SCRIPT.read_text(encoding='utf-8'))
    assert all(node.module in allowed for node in ast.walk(tree) if isinstance(node, ast.ImportFrom))
    assert all(alias.name in allowed for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names)
    evidence = tmp_path / 'raw.json'
    evidence.write_text(oracle.canonical(packet()), encoding='utf-8')
    result = subprocess.run([sys.executable, '-I', str(SCRIPT), '--input', str(evidence)], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)['verified'] is True
