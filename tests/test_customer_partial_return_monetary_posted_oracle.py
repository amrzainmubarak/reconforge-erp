"""Raw-contract controls only; synthetic empty tables are not posting proof."""
from __future__ import annotations

import ast
import hashlib
import json
from copy import deepcopy
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest

from tests import customer_partial_return_monetary_posted_oracle as reader


def packet() -> dict[str, Any]:
    capture = {"capture": 0, "tables": {name: [] for name in reader.TABLES}}
    second = deepcopy(capture)
    second["capture"] = 1
    return {"schema_version": reader.SCHEMA, "tenant_id": "tenant", "source_order_id": "STSALE-original",
            "captures": [capture, second]}


def encoded(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def row(identifier: str = "row", *, tenant: str = "tenant") -> str:
    return json.dumps({"tenant_id": tenant, "id": identifier}, sort_keys=True)


def storage_row(table: str) -> dict[str, Any]:
    value: dict[str, Any] = dict.fromkeys(reader.MONETARY_COLUMNS[table], "reference")
    value["tenant_id"] = "tenant"
    for field in value:
        if field.endswith("_digest"):
            value[field] = "a" * 64
        elif field in {"payload", "snapshot", "ar_balance", "request_json", "response_json"}:
            value[field] = {}
    for field in {"original_id", "original_effect_id", "posting_effect_id", "stock_fx_plan_id", "partial_plan_id",
                  "original_sequence", "correction_effect_id", "original_restoration_plan_id"} & value.keys():
        value[field] = None
    if table.endswith("_plans"):
        value.update(id="CR3-" + "1" * 32, operation="Return", phase=0, expected_history_version=0)
    elif table.endswith("_entries"):
        value["purpose"] = "CostRestoration"
    elif table.endswith("_events") or table.endswith("_commands"):
        value["operation"] = "prepare"
    elif table.endswith("_history"):
        value.update(sequence=1, kind="Return", partial_plan_id="CR3-" + "1" * 32)
    elif table.endswith("_restorations"):
        value.update(position=1, before_quantity_scaled=2, before_value_minor=1, quantity_scaled=1,
                     value_minor=0, direction=1, consumption_count_at_restore=1)
    return value


def with_storage(table: str, record: dict[str, Any]) -> bytes:
    value = packet()
    value["captures"][1]["tables"][table] = [json.dumps(record, sort_keys=True)]
    return encoded(value)


def original_tables(*, foreign: bool = True) -> dict[str, list[str]]:
    """Literal synthetic row joins; no production finance or native calls."""
    tables: dict[str, list[dict[str, Any]]] = {name: [] for name in reader.TABLES}
    scope = {"tenant_id": "tenant", "workspace_id": "work", "organization_id": "org", "legal_entity_id": "entity"}
    compact = {"currency_code": "USD", "precision": 2, "rounding_policy": "ROUND_HALF_UP", "registry_version": "synthetic", "registry_digest": "a" * 64}
    quoted = {**compact, "currency_code": "EUR" if foreign else "USD"}
    full = {"currency_code": "USD", "currency_precision": 2, "currency_rounding_policy": "ROUND_HALF_UP", "currency_registry_version": "synthetic", "currency_registry_digest": "a" * 64}
    role_kinds = {"receivable": "Asset", "revenue": "Income", "cash": "Asset", "gain": "Income", "loss": "Expense", "refund_liability": "Liability", "inventory": "Asset", "cogs": "Expense", "tax": "Liability"}
    for code, kind in role_kinds.items():
        tables["finance_accounts"].append({"tenant_id": "tenant", "id": code, "workspace_id": "work", "account_code": code.upper(), "account_type": kind})
    roles = {key + "_account_id": key for key in role_kinds if key != "tax"}
    declared = {"schema_version": "stock-sales-monetary-order-v2", "monetary_policy": quoted, "functional_policy": compact,
                "quantity": "10", "quantity_scaled": 10, "unit_price_minor": 1000, "discount_basis_points": 0,
                "net_unit_price_minor": 1000, "total_minor": 10000, "description": "Synthetic original merchandise", "discount_policy": "net-exclusive-v1"}
    stock = {**scope, "id": "stock", "status": "Invoiced", "invoice_id": "invoice", "invoice_plan_id": "recognition", "customer_id": "customer",
             "quantity_scaled": 10, "quantity_precision": 0, "currency_code": quoted["currency_code"], "total_minor": 10000,
             "source": declared, "source_digest": reader._digest(declared), "movement_id": "movement", "valuation_id": "valuation", "item_id": "item", "uom_id": "EA",
             "issue_plan": {"total_cost_minor": 12000, "allocations": [{"cost_layer_id": "layer", "quantity_scaled": 10, "value_minor": 12000}]},
             "cogs_entry_id": "cogs-entry", "cogs_effect_id": "cogs-effect"}
    invoice = {**scope, "id": "invoice", "customer_id": "customer", "currency_code": quoted["currency_code"], "invoice_number": "FX1-SYNTHETIC", "invoice_date": "2026-10-15", "due_date": "2026-10-31",
               "subtotal_minor": 10000, "tax_minor": 1400, "total_minor": 11400, "customer_partial_return_source_id": None}
    line = {"tenant_id": "tenant", "id": "ar-line", "invoice_id": "invoice", "line_number": 1, "quantity": 10, "quantity_text": "10", "unit_price_minor": 1000,
            "line_total_minor": 10000, "tax_minor": 1400, "description": declared["description"]}
    tax = {"policy_id": "synthetic-tax", "country_code": "ZZ", "transaction_class": "synthetic-merchandise", "effective_from": "2026-01-01", "effective_to": "2026-12-31", "rate": "0.14", "account_code": "TAX", "source": "Synthetic illustrative fraction", "version": "1"}
    tax["policy_digest"] = reader._digest(tax)
    request: dict[str, Any] = {key: value for key, value in scope.items() if key != "tenant_id"}
    request.update(net_minor=10000, foreign_currency_code=quoted["currency_code"], posting_date="2026-10-15", due_date="2026-10-31", country_code="ZZ", transaction_class="synthetic-merchandise", taxes=[tax],
                   original_rate={"rate": "1.25", "source": "Synthetic reviewed quote", "effective_at": "2026-10-15T12:00:00Z"} if foreign else None)
    request.update({key + "_account_code": key.upper() for key in ("receivable", "revenue", "cash", "gain", "loss")})
    local_net, local_tax, gross = (12500, 1750, 14250) if foreign else (10000, 1400, 11400)
    equation = {"request": request, "foreign_policy": {**full, "currency_code": quoted["currency_code"]}, "functional_policy": full,
                "foreign_net_minor": 10000, "foreign_tax_minor": 1400, "foreign_gross_minor": 11400, "functional_net_minor": local_net, "functional_gross_minor": gross,
                "tax_components": [{**tax, "foreign_tax_minor": 1400, "functional_tax_minor": local_tax}],
                "functional_allocation_policy": "converted-cumulative-prefix-v1", "lines": []}
    fx = {**equation, **{key: value for key, value in scope.items() if key != "tenant_id"}, "schema_version": "operational-fx-stock-source-v2", "id": "fx-source", "invoice_id": "invoice", "preparer_actor_id": "maker",
          "stock_order_id": "stock", "stock_source_digest": stock["source_digest"]}
    fx["source_digest"] = reader._digest(fx)

    def effect(identifier: str, entry_id: str, vectors: list[tuple[str, int, int]], reference: str) -> dict[str, Any]:
        header = {"id": entry_id, "workspace_id": "work", "organization_id": "org", "legal_entity_id": "entity", "journal_id": "journal", "period_id": "period", "entry_number": entry_id.upper(),
                  "posting_date": "2026-10-15", "description": "Synthetic governed posting", "external_reference": reference, "source_type": "Manual", **full,
                  "preparer_actor_id": "maker", "reverses_posting_id": None}
        sealed = [{"line_number": index, "account_id": account, "description": "", "debit_minor": dr, "credit_minor": cr, "dimensions": {}}
                  for index, (account, dr, cr) in enumerate(vectors, 1)]
        snapshot = {"schema_version": "finance-entry-review-v1", "entry": header, "lines": sealed}
        digest = reader._digest(snapshot)
        raw_entry = {key: value for key, value in header.items() if key not in {"organization_id", "legal_entity_id"}}
        tables["finance_entries"].append({**raw_entry, "tenant_id": "tenant", "status": "Validated", "validator_actor_id": "checker", "validation_digest": digest,
                                         "validation_contract_version": "finance-entry-review-v1", "total_debit_minor": sum(dr for _, dr, _ in vectors), "total_credit_minor": sum(cr for _, _, cr in vectors)})
        for index, item in enumerate(sealed, 1):
            tables["finance_entry_lines"].append({key: value for key, value in {**item, "tenant_id": "tenant", "id": entry_id + "-" + str(index), "entry_id": entry_id, "currency_code": "USD"}.items() if key != "dimensions"})
        value = {**scope, "id": identifier, "entry_id": entry_id, **full, "purpose": "operational_posting", "source_kind": "Manual", "source_id": entry_id,
                 "reverses_effect_id": None, "snapshot_json": snapshot, "validation_digest": digest, "validation_contract_version": "finance-entry-review-v1", "posted_actor_id": "poster", "audit_event_id": identifier + "-audit", "outbox_event_id": identifier + "-outbox"}
        tables["finance_posting_effects"].append(value)
        tables["domain_audit_events"].append({"tenant_id": "tenant", "id": value["audit_event_id"]})
        tables["outbox_events"].append({"tenant_id": "tenant", "event_id": value["outbox_event_id"]})
        return value

    cogs = effect("cogs-effect", "cogs-entry", [("cogs", 12000, 0), ("inventory", 0, 12000)], "stock")
    revenue = effect("revenue-effect", "revenue-entry", [("receivable", gross, 0), ("revenue", 0, local_net), ("tax", 0, local_tax)], "FX:fx-source:recognize")
    consumed = {"tenant_id": "tenant", "id": "consumed", "workspace_id": "work", "valuation_line_id": "valuation-line", "cost_layer_id": "layer", "quantity_scaled": 10, "value_minor": 12000}
    typed_consumed = {"position": 1, "original_consumption_id": "consumed", "original_valuation_line_id": "valuation-line", "cost_layer_id": "layer", "quantity_scaled": 10, "value_minor": 12000}
    dimensions = {account: {} for account in (*roles.values(), "tax")}
    evidence = {"stock_order_id": "stock", "stock_source": declared, "stock_source_digest": stock["source_digest"],
                **{key: stock[key] for key in ("issue_plan", "movement_id", "valuation_id", "cogs_entry_id", "cogs_effect_id", "invoice_id")},
                "cogs_snapshot": cogs["snapshot_json"], "fx_source": fx, "recognition_plan_id": "recognition", "recognition_snapshot": revenue["snapshot_json"],
                "invoice_original": {key: invoice[key] for key in ("customer_id", "currency_code", "invoice_number", "invoice_date", "due_date", "subtotal_minor", "tax_minor", "total_minor")},
                "invoice_line": {**{key: value for key, value in line.items() if key not in {"tenant_id", "quantity"}}, "quantity_native_text": "10"},
                "consumptions": [typed_consumed], "roles": roles, "dimensions": dimensions}
    source = {"source_id": "origin", "source_order_id": "stock", "invoice_id": "invoice", "posting_date": "2026-10-15", "native_origin_digest": reader._digest(evidence),
              "quantity_scaled": 10, "quantity_precision": 0, "transaction_policy": quoted, "functional_policy": compact, "registry_snapshot": {"digest": "a" * 64},
              "components": [{"position": 0, "kind": "Net", "account_id": "revenue", "transaction_minor": 10000, "functional_minor": local_net, "policy_digest": reader._digest({"stock_source_digest": stock["source_digest"], "discount_policy": declared["discount_policy"]})},
                             {"position": 1, "kind": "Tax", "account_id": "tax", "transaction_minor": 1400, "functional_minor": local_tax, "policy_digest": tax["policy_digest"]}],
              "consumptions": [typed_consumed], "original_cost_admission_digest": None, "allocation_policy": "remaining-dual-currency-v1", "alignment_policy": "historical-carrying-component-alignment-v1"}
    body = {"source": source, "evidence": evidence, "equation": equation, "roles": roles, "dimensions": dimensions, "journal_id": "journal", "functional_policy": full, "refund_liability_account_code": "REFUND_LIABILITY"}
    tables["stock_sales_monetary_origins"] = [{**scope, "id": "origin", "stock_order_id": "stock", "invoice_id": "invoice", "fx_source_id": "fx-source", "recognition_plan_id": "recognition", "payload": body, "source_digest": reader._digest(body), "ar_balance": {}}]
    tables["stock_sales_orders"] = [stock]
    tables["ar_invoices"], tables["ar_invoice_lines"] = [invoice], [line]
    tables["operational_fx_sources"] = [{**scope, "id": "fx-source", "invoice_id": "invoice", "payload": fx}]
    tables["operational_fx_plans"] = [{**scope, "id": "recognition", "source_id": "fx-source", "kind": "recognize", "sequence": 0, "phase": 2, "entry_id": "revenue-entry"}]
    tables["operational_fx_links"] = [{"tenant_id": "tenant", "plan_id": "recognition", "posting_effect_id": "revenue-effect"}]
    tables["inventory_layer_consumptions"] = [consumed]
    tables["inventory_valuation_documents"] = [{**scope, "id": "valuation", "status": "Approved", "movement_id": "movement", "finance_entry_id": "cogs-entry", "currency_code": "USD"}]
    tables["inventory_valuation_lines"] = [{"tenant_id": "tenant", "id": "valuation-line", "valuation_document_id": "valuation", "item_id": "item", "uom_id": "EA", "flow_direction": "Outbound"}]
    tables["inventory_cost_layers"] = [{"tenant_id": "tenant", "id": "layer", "workspace_id": "work", "legal_entity_id": "entity", "item_id": "item", "uom_id": "EA", "currency_code": "USD"}]
    return {name: sorted(json.dumps(row, sort_keys=True) for row in rows) for name, rows in tables.items()}


def original_capture(tables: dict[str, list[str]]) -> reader.Capture:
    return reader.decode_capture({"capture": 0, "tables": tables}, index=0, tenant_id="tenant")


@pytest.mark.parametrize("foreign", [False, True])
def test_original_rows_rederive_actual_net_tax_fx_ar_fifo_and_reviewed_effects(foreign: bool) -> None:
    source = reader.verify_original_rows(original_capture(original_tables(foreign=foreign)), source_order_id="stock")
    assert source.components == ((10000, 12500), (1400, 1750)) if foreign else source.components == ((10000, 10000), (1400, 1400))
    assert source.fifo == ((10, 12000),) and source.origin_id == "origin"
    assert not hasattr(source, "native_acceptance") and not hasattr(source, "posted_cycle_verified")


@pytest.mark.parametrize("table,field,value", [
    ("ar_invoice_lines", "quantity", True), ("ar_invoice_lines", "line_total_minor", 9999),
    ("ar_invoices", "currency_code", "USD"), ("inventory_layer_consumptions", "value_minor", 11999),
    ("inventory_cost_layers", "legal_entity_id", "foreign-entity"),
    ("finance_posting_effects", "source_id", "stock"), ("finance_posting_effects", "posted_actor_id", "checker"),
    ("finance_entry_lines", "currency_code", "EUR"), ("inventory_valuation_documents", "finance_entry_id", "foreign-entry"),
])
def test_original_financial_membership_changes_refuse(table: str, field: str, value: Any) -> None:
    tables = original_tables()
    rows = [json.loads(text) for text in tables[table]]
    rows[0][field] = value
    tables[table] = sorted(json.dumps(row, sort_keys=True) for row in rows)
    with pytest.raises(reader.MonetaryRawRefusal):
        reader.verify_original_rows(original_capture(tables), source_order_id="stock")


def literal_foreign_events(source: reader.OriginalFinancial) -> list[dict[str, Any]]:
    """Hand-vector history; no reader/SUT allocation functions construct it."""
    def position(q: int, nf: int, nl: int, tf: int, tl: int, cost: int, ar_f: int, ar_l: int, due_f: int, due_l: int,
                 collected: int, credited: int, refunded: int, released: int) -> dict[str, Any]:
        return dict(zip(("remaining_quantity_scaled", "component_transaction_minor", "component_functional_minor", "consumption_quantity_scaled", "consumption_value_minor",
                         "transaction_outstanding_minor", "functional_outstanding_minor", "transaction_refund_due_minor", "functional_refund_due_minor", "transaction_collected_minor",
                         "transaction_credited_minor", "transaction_refunded_minor", "functional_refund_released_minor"),
                        (q, [nf, tf], [nl, tl], [q], [cost], ar_f, ar_l, due_f, due_l, collected, credited, refunded, released), strict=True))
    states = [position(10, 10000, 12500, 1400, 1750, 12000, 11400, 14250, 0, 0, 0, 0, 0, 0),
              position(10, 10000, 12500, 1400, 1750, 12000, 7400, 9250, 0, 0, 4000, 0, 0, 0),
              position(4, 4000, 5000, 560, 700, 4800, 560, 700, 0, 0, 4000, 6840, 0, 0),
              position(0, 0, 0, 0, 0, 0, 0, 0, 4000, 5000, 4000, 11400, 0, 0),
              position(0, 0, 0, 0, 0, 0, 0, 0, 2500, 3125, 4000, 11400, 1500, 1875),
              position(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 4000, 11400, 4000, 5000)]
    states.extend((deepcopy(states[4]), deepcopy(states[5])))
    seeds = [("Collection", 0, 4000, "1.3", None), ("Return", 6, 0, None, None), ("Return", 4, 0, None, None),
             ("Refund", 0, 1500, "1.2", None), ("Refund", 0, 2500, "1.3", None), ("ReverseRefund", 0, 2500, None, 5), ("Refund", 0, 2500, "1.3", None)]
    movements = [dict(transaction_receivable_released_minor=4000, functional_receivable_released_minor=5000, functional_cash_minor=5200, functional_fx_gain_minor=200, functional_turnover_minor=5200),
                 dict(transaction_net_minor=6000, transaction_tax_minor=840, transaction_credit_minor=6840, functional_net_minor=7500, functional_tax_minor=1050, functional_credit_minor=8550,
                      functional_cost_minor=7200, transaction_receivable_released_minor=6840, functional_receivable_released_minor=8550, functional_turnover_minor=15750),
                 dict(transaction_net_minor=4000, transaction_tax_minor=560, transaction_credit_minor=4560, functional_net_minor=5000, functional_tax_minor=700, functional_credit_minor=5700,
                      functional_cost_minor=4800, transaction_receivable_released_minor=560, functional_receivable_released_minor=700, transaction_refund_delta_minor=4000, functional_refund_delta_minor=5000, functional_turnover_minor=10500),
                 dict(transaction_refund_minor=1500, functional_refund_released_minor=1875, functional_cash_minor=1800, functional_fx_gain_minor=75, functional_turnover_minor=1875),
                 dict(transaction_refund_minor=2500, functional_refund_released_minor=3125, functional_cash_minor=3250, functional_fx_loss_minor=125, functional_turnover_minor=3250)]
    movements.extend((dict(movements[4]), dict(movements[4])))
    events: list[dict[str, Any]] = []
    chain = reader._digest({"contract": "customer-partial-return-monetary-original-v3", "source_fingerprint": source.fingerprint,
                            "allocation_policy": "remaining-dual-currency-v1", "alignment_policy": "historical-carrying-component-alignment-v1"})
    for index, (kind, quantity, amount, rate, inverse) in enumerate(seeds):
        components, portions = [], []
        if kind == "Return":
            first = index == 1
            components = [dict(position=0, before_quantity_scaled=10 if first else 4, before_transaction_minor=10000 if first else 4000, before_functional_minor=12500 if first else 5000,
                               transaction_minor=6000 if first else 4000, functional_minor=7500 if first else 5000),
                          dict(position=1, before_quantity_scaled=10 if first else 4, before_transaction_minor=1400 if first else 560, before_functional_minor=1750 if first else 700,
                               transaction_minor=840 if first else 560, functional_minor=1050 if first else 700)]
            portions = [dict(position=1, original_consumption_id="consumed", original_valuation_line_id="valuation-line", cost_layer_id="layer", before_quantity_scaled=10 if first else 4,
                             before_value_minor=12000 if first else 4800, quantity_scaled=quantity, value_minor=7200 if first else 4800)]
        event = {"kind": kind, "sequence": index + 1, "source_fingerprint": source.fingerprint, "previous_history_fingerprint": chain,
                 "posting_date": "2026-10-15", "quantity_scaled": quantity, "amount_minor": amount,
                 "settlement_rate": None if rate is None else {"rate": rate, "source": "Synthetic observed spot", "effective_at": "2026-10-15T12:00:00Z"},
                 "original_sequence": inverse, "before": states[index], "after": states[index + 1], "monetary": {**dict.fromkeys(reader._MOVEMENT_FIELDS, 0), **movements[index]},
                 "components": components, "portions": portions}
        events.append(event)
        chain = reader._digest(event)
    return events


def test_independent_history_replays_literal_foreign_returns_cash_and_exact_inverse() -> None:
    original = reader.verify_original_rows(original_capture(original_tables()), source_order_id="stock")
    previous: list[dict[str, Any]] = []
    for expected in literal_foreign_events(original):
        actual = reader._next_event(original, previous, expected)
        assert actual == expected and reader._digest(actual) == reader._digest(expected)
        previous.append(actual)
    assert previous[-1]["after"]["transaction_refund_due_minor"] == previous[-1]["after"]["functional_refund_due_minor"] == 0


@pytest.mark.parametrize("inverse", [None, True, 0, 4, 6])
def test_history_inverse_cannot_reprice_or_select_a_nonlatest_active_member(inverse: Any) -> None:
    source = reader.verify_original_rows(original_capture(original_tables()), source_order_id="stock")
    events = literal_foreign_events(source)
    forged = {**events[5], "original_sequence": inverse}
    with pytest.raises(reader.MonetaryRawRefusal):
        reader._next_event(source, events[:5], forged)


def history_tables() -> tuple[dict[str, list[str]], list[dict[str, Any]]]:
    tables = original_tables()
    source = reader.verify_original_rows(original_capture(tables), source_order_id="stock")
    events = literal_foreign_events(source)
    history, plans = [], []
    for event in events:
        record = storage_row("customer_partial_return_monetary_history")
        record.update(workspace_id="work", organization_id="org", legal_entity_id="entity", origin_id="origin", sequence=event["sequence"], kind=event["kind"],
                      payload=event, original_sequence=event["original_sequence"], previous_digest=event["previous_history_fingerprint"], event_digest=reader._digest(event))
        if event["kind"] == "Collection":
            record.update(stock_fx_plan_id="collection", partial_plan_id=None)
            fx_plan = {"tenant_id": "tenant", "workspace_id": "work", "organization_id": "org", "legal_entity_id": "entity", "id": "collection", "source_id": "fx-source", "kind": "settle", "phase": 2, "sequence": 1,
                       "payload": {"equation": {"monetary_event": event}}}
            tables["operational_fx_plans"].append(json.dumps(fx_plan, sort_keys=True))
            tables["operational_fx_plans"].sort()
        else:
            prefixes = {"Return": "CR3", "Refund": "CRF3", "ReverseRefund": "CRF3R"}
            identifier = prefixes[event["kind"]] + "-" + str(event["sequence"]) * 32
            record.update(stock_fx_plan_id=None, partial_plan_id=identifier)
            plan = storage_row("customer_partial_return_monetary_plans")
            payload = {"monetary_event": event}
            payload["plan_digest"] = reader._digest(payload)
            plan.update(workspace_id="work", organization_id="org", legal_entity_id="entity", origin_id="origin", operation=event["kind"], id=identifier, phase=2,
                        expected_history_version=event["sequence"] - 1, original_id=None if event["kind"] == "Return" else "CR3-" + "2" * 32,
                        payload=payload, plan_digest=payload["plan_digest"])
            plans.append(json.dumps(plan, sort_keys=True))
        history.append(json.dumps(record, sort_keys=True))
    tables["customer_partial_return_monetary_history"] = sorted(history)
    tables["customer_partial_return_monetary_plans"] = sorted(plans)
    return tables, events


def test_actual_native_history_rows_join_their_distinct_fx_and_partial_owners() -> None:
    tables, expected = history_tables()
    capture = original_capture(tables)
    source = reader.verify_original_rows(capture, source_order_id="stock")
    assert reader.verify_history_rows(capture, source) == tuple(expected)


@pytest.mark.parametrize("field", ["carrying", "cash", "component", "fifo", "bool", "foreign-owner", "sequence"])
def test_coherently_resealed_history_cannot_replace_independent_original_math(field: str) -> None:
    tables, _events = history_tables()
    history = sorted((json.loads(text) for text in tables["customer_partial_return_monetary_history"]), key=lambda row: row["sequence"])
    record = history[1]
    event = record["payload"]
    if field == "carrying":
        event["after"]["functional_outstanding_minor"] += 1
    elif field == "cash":
        event["monetary"]["functional_turnover_minor"] -= 1
    elif field == "component":
        event["components"][0]["functional_minor"] -= 1
    elif field == "fifo":
        event["portions"][0]["original_consumption_id"] = "foreign-consumption"
    elif field == "bool":
        event["components"][1]["position"] = True
    elif field == "foreign-owner":
        record["origin_id"] = "foreign-origin"
    else:
        event["sequence"] = 3
    # Re-seal both the event and owner, so digest checks alone are insufficient.
    record["event_digest"] = reader._digest(event)
    plans = [json.loads(text) for text in tables["customer_partial_return_monetary_plans"]]
    for plan in plans:
        if plan["id"] == record["partial_plan_id"]:
            plan["payload"]["monetary_event"] = event
            plan["plan_digest"] = reader._digest({key: value for key, value in plan["payload"].items() if key != "plan_digest"})
            plan["payload"]["plan_digest"] = plan["plan_digest"]
    tables["customer_partial_return_monetary_history"] = sorted(json.dumps(row, sort_keys=True) for row in history)
    tables["customer_partial_return_monetary_plans"] = sorted(json.dumps(row, sort_keys=True) for row in plans)
    capture = original_capture(tables)
    source = reader.verify_original_rows(capture, source_order_id="stock")
    with pytest.raises(reader.MonetaryRawRefusal):
        reader.verify_history_rows(capture, source)


LITERAL_JOURNALS = [
    [("Collection", [("cash", 5200, 0), ("receivable", 0, 5000), ("gain", 0, 200)])],
    [("MerchandiseCredit", [("revenue", 7500, 0), ("tax", 1050, 0), ("receivable", 0, 8550)]), ("CostRestoration", [("inventory", 7200, 0), ("cogs", 0, 7200)])],
    [("MerchandiseCredit", [("revenue", 5000, 0), ("tax", 700, 0), ("receivable", 0, 700), ("refund_liability", 0, 5000)]), ("CostRestoration", [("inventory", 4800, 0), ("cogs", 0, 4800)])],
    [("Refund", [("refund_liability", 1875, 0), ("cash", 0, 1800), ("gain", 0, 75)])],
    [("Refund", [("refund_liability", 3125, 0), ("loss", 125, 0), ("cash", 0, 3250)])],
    [("ReverseRefund", [("refund_liability", 0, 3125), ("loss", 0, 125), ("cash", 3250, 0)])],
    [("Refund", [("refund_liability", 3125, 0), ("loss", 125, 0), ("cash", 0, 3250)])],
]


def test_journal_templates_equal_literal_tax_cost_cash_and_full_inverse_lines() -> None:
    source = reader.verify_original_rows(original_capture(original_tables()), source_order_id="stock")
    for event, expected in zip(literal_foreign_events(source), LITERAL_JOURNALS, strict=True):
        assert reader._journals(source, event) == expected
    assert sum(len(lines) for entries in LITERAL_JOURNALS for _, lines in entries) == 26
    assert sum(dr for entries in LITERAL_JOURNALS for _, lines in entries for _, dr, _ in lines) == 43075


def posted_tables() -> dict[str, list[str]]:
    raw, events = history_tables()
    tables = {name: [json.loads(text) for text in values] for name, values in raw.items()}
    template = tables["finance_posting_effects"][0]
    header_template = template["snapshot_json"]["entry"]
    history = sorted(tables["customer_partial_return_monetary_history"], key=lambda row: row["sequence"])
    for event, retained, entries in zip(events, history, LITERAL_JOURNALS, strict=True):
        plan_id = retained["stock_fx_plan_id"] or retained["partial_plan_id"]
        plan_table = "operational_fx_plans" if event["kind"] == "Collection" else "customer_partial_return_monetary_plans"
        plan = next(row for row in tables[plan_table] if row["id"] == plan_id)
        if event["kind"] != "Collection":
            plan["payload"]["preparer_actor_id"] = "maker"
            plan["payload"]["entries"] = []
            plan["payload"].update(movement_id=None, quantity_scaled=event["quantity_scaled"], period_id="period", posting_date="2026-10-15")
            if event["kind"] == "ReverseRefund":
                plan["original_id"] = "CRF3-" + "5" * 32
            for op, actor in (("prepare", "maker"), ("review", "checker"), ("post", "poster")):
                native = storage_row("customer_partial_return_monetary_events")
                native.update(workspace_id="work", organization_id="org", legal_entity_id="entity", plan_id=plan_id, operation=op, actor_id=actor)
                tables["customer_partial_return_monetary_events"].append(native)
        for purpose, vectors in entries:
            inverse = purpose.startswith("Reverse")
            original_effect = "effect-5-Refund" if inverse else None
            suffix = "C" if purpose.endswith("CostRestoration") else "F" if purpose.endswith("Refund") else "R"
            number = plan_id.upper() + "-" + suffix
            entry_id = "collection-entry" if event["kind"] == "Collection" else "GLE-" + hashlib.sha256(("work|" + number).encode()).hexdigest()[:16]
            effect_id = "effect-" + str(event["sequence"]) + "-" + purpose
            reference = "FX:fx-source:settle" if event["kind"] == "Collection" else original_effect if inverse else plan_id
            header = {**header_template, "id": entry_id, "entry_number": number, "external_reference": reference,
                      "source_type": "Generated" if inverse else "Manual", "reverses_posting_id": original_effect}
            lines = [{"line_number": n, "account_id": a, "description": "", "debit_minor": dr, "credit_minor": cr, "dimensions": {}}
                     for n, (a, dr, cr) in enumerate(vectors, 1)]
            snapshot = {"schema_version": "finance-entry-review-v1", "entry": header, "lines": lines}
            digest = reader._digest(snapshot)
            effect = {**template, "id": effect_id, "entry_id": entry_id, "source_id": original_effect if inverse else entry_id, "source_kind": "Reversal" if inverse else "Manual", "reverses_effect_id": original_effect,
                      "snapshot_json": snapshot, "validation_digest": digest, "audit_event_id": effect_id + "-audit", "outbox_event_id": effect_id + "-outbox"}
            tables["finance_posting_effects"].append(effect)
            tables["domain_audit_events"].append({"tenant_id": "tenant", "id": effect["audit_event_id"]})
            tables["outbox_events"].append({"tenant_id": "tenant", "event_id": effect["outbox_event_id"]})
            entry = {key: value for key, value in header.items() if key not in {"organization_id", "legal_entity_id"}}
            tables["finance_entries"].append({**entry, "tenant_id": "tenant", "status": "Validated", "validator_actor_id": "checker", "validation_digest": digest, "validation_contract_version": "finance-entry-review-v1",
                                             "total_debit_minor": sum(dr for _, dr, _ in vectors), "total_credit_minor": sum(cr for _, _, cr in vectors)})
            for n, item in enumerate(lines, 1):
                tables["finance_entry_lines"].append({key: value for key, value in {**item, "tenant_id": "tenant", "id": entry_id + "-" + str(n), "entry_id": entry_id, "currency_code": "USD"}.items() if key != "dimensions"})
            if event["kind"] == "Collection":
                plan["entry_id"] = entry_id
                tables["operational_fx_links"].append({"tenant_id": "tenant", "plan_id": plan_id, "receipt_id": "receipt", "posting_effect_id": effect_id, "posted_actor_id": "poster"})
                tables["ar_receipts"].append({"tenant_id": "tenant", "workspace_id": "work", "organization_id": "org", "legal_entity_id": "entity", "id": "receipt", "currency_code": "EUR", "status": "Posted", "amount_minor": 4000})
                tables["ar_receipt_allocations"].append({"tenant_id": "tenant", "id": "allocation", "receipt_id": "receipt", "invoice_id": "invoice", "amount_minor": 4000})
            else:
                member = storage_row("customer_partial_return_monetary_entries")
                member.update(workspace_id="work", organization_id="org", legal_entity_id="entity", plan_id=plan_id, purpose=purpose, entry_id=entry_id,
                              original_effect_id=original_effect, posting_effect_id=effect_id, snapshot=snapshot, validation_digest=digest)
                tables["customer_partial_return_monetary_entries"].append(member)
                plan["payload"]["entries"].append({key: member[key] for key in ("purpose", "entry_id", "snapshot", "validation_digest", "original_effect_id")})
        if event["kind"] != "Collection":
            plan["plan_digest"] = reader._digest({key: value for key, value in plan["payload"].items() if key != "plan_digest"})
            plan["payload"]["plan_digest"] = plan["plan_digest"]
    return {name: sorted(json.dumps(row, sort_keys=True) for row in rows) for name, rows in tables.items()}


def test_posted_native_journal_membership_requires_real_ar_cash_and_exact_inverse_owner() -> None:
    capture = original_capture(posted_tables())
    original = reader.verify_original_rows(capture, source_order_id="stock")
    events = reader.verify_history_rows(capture, original)
    effects = reader.verify_posted_journal_rows(capture, original, events)
    assert len(effects) == len(set(effects)) == 9


@pytest.mark.parametrize("table,field,bad", [
    ("ar_receipts", "amount_minor", 4001), ("ar_receipt_allocations", "invoice_id", "foreign-invoice"),
    ("customer_partial_return_monetary_events", "actor_id", "same-human"),
    ("customer_partial_return_monetary_entries", "posting_effect_id", "revenue-effect"),
    ("customer_partial_return_monetary_entries", "entry_id", "revenue-entry"),
])
def test_native_posted_membership_does_not_accept_sealed_but_unowned_finance(table: str, field: str, bad: str | int) -> None:
    tables = posted_tables()
    records = [json.loads(text) for text in tables[table]]
    records[0][field] = bad
    tables[table] = sorted(json.dumps(row, sort_keys=True) for row in records)
    capture = original_capture(tables)
    original = reader.verify_original_rows(capture, source_order_id="stock")
    events = reader.verify_history_rows(capture, original)
    with pytest.raises(reader.MonetaryRawRefusal):
        reader.verify_posted_journal_rows(capture, original, events)


def physical_tables() -> dict[str, list[str]]:
    tables = {name: [json.loads(text) for text in values] for name, values in posted_tables().items()}
    tables["inventory_cost_layers"][0].update(original_quantity_scaled=10, original_value_minor=12000, remaining_quantity_scaled=10, remaining_value_minor=12000)
    for plan in tables["customer_partial_return_monetary_plans"]:
        if plan["operation"] != "Return":
            continue
        payload = plan["payload"]
        event = payload["monetary_event"]
        movement_id = "MOV-" + hashlib.sha256(("work|" + plan["id"].upper()).encode()).hexdigest()[:16]
        payload["movement_id"] = movement_id
        scope = {key: plan[key] for key in ("tenant_id", "workspace_id", "organization_id", "legal_entity_id")}
        tables["inventory_movements"].append({**scope, "id": movement_id, "movement_number": plan["id"].upper(), "movement_type": "Receipt", "movement_date": "2026-10-15",
                                               "source_reference": plan["id"], "source_type": "Generated", "status": "Posted", "period_id": "period"})
        tables["inventory_movement_lines"].append({"tenant_id": "tenant", "id": movement_id + "-line", "movement_id": movement_id, "item_id": "item", "uom_id": "EA", "quantity_scaled": event["quantity_scaled"],
                                                   "quantity_precision": 0, "from_location_id": None, "to_location_id": "location", "inventory_lot_id": None})
        cost = next(row for row in tables["customer_partial_return_monetary_entries"] if row["plan_id"] == plan["id"] and row["purpose"] == "CostRestoration")
        for part in event["portions"]:
            record = {**scope, "origin_id": "origin", "plan_id": plan["id"], **part, "direction": 1, "physical_movement_id": movement_id, "correction_effect_id": cost["posting_effect_id"],
                      "original_restoration_plan_id": None, "consumption_count_at_restore": 1}
            tables["customer_partial_return_monetary_restorations"].append(record)
        plan["plan_digest"] = reader._digest({key: value for key, value in payload.items() if key != "plan_digest"})
        payload["plan_digest"] = plan["plan_digest"]
    tables["stock_sales_orders"][0]["location_id"] = "location"
    return {name: sorted(json.dumps(row, sort_keys=True) for row in rows) for name, rows in tables.items()}


def test_physical_original_layer_and_signed_restoration_equation_are_independent() -> None:
    capture = original_capture(physical_tables())
    source = reader.verify_original_rows(capture, source_order_id="stock")
    events = reader.verify_history_rows(capture, source)
    assert len(reader.verify_posted_journal_rows(capture, source, events)) == 9
    assert len(reader.verify_physical_rows(capture, source, events)) == 2


@pytest.mark.parametrize("table,field,bad", [
    ("inventory_cost_layers", "remaining_quantity_scaled", 9), ("inventory_cost_layers", "remaining_value_minor", 11999),
    ("inventory_movements", "source_reference", "foreign-plan"), ("inventory_movement_lines", "to_location_id", "foreign-location"),
    ("customer_partial_return_monetary_restorations", "origin_id", "foreign-origin"),
    ("customer_partial_return_monetary_restorations", "correction_effect_id", "revenue-effect"),
    ("customer_partial_return_monetary_restorations", "consumption_count_at_restore", 2),
])
def test_balanced_finance_cannot_hide_a_wrong_physical_or_original_fifo_owner(table: str, field: str, bad: Any) -> None:
    tables = physical_tables()
    records = [json.loads(text) for text in tables[table]]
    records[0][field] = bad
    tables[table] = sorted(json.dumps(row, sort_keys=True) for row in records)
    capture = original_capture(tables)
    original = reader.verify_original_rows(capture, source_order_id="stock")
    events = reader.verify_history_rows(capture, original)
    assert len(reader.verify_posted_journal_rows(capture, original, events)) == 9
    with pytest.raises(reader.MonetaryRawRefusal):
        reader.verify_physical_rows(capture, original, events)


def valuation_tables() -> dict[str, list[str]]:
    raw = physical_tables()
    tables = {name: [json.loads(text) for text in values] for name, values in raw.items()}
    source = reader.verify_original_rows(original_capture(raw), source_order_id="stock")
    events = literal_foreign_events(source)
    for identifier, kind in (("unreal-gain", "Income"), ("unreal-loss", "Expense")):
        tables["finance_accounts"].append({"tenant_id": "tenant", "workspace_id": "work", "id": identifier, "account_code": identifier.upper().replace("-", "_"), "account_type": kind})
    equation: dict[str, Any] = {"foreign_before_minor": 10840, "historical_before_minor": 13550, "foreign_outstanding_minor": 560, "historical_outstanding_minor": 700,
                               "valued_outstanding_minor": 840, "unrealized_fx_minor": 140, "amount_minor": 140,
                               "closing_rate": {"rate": "1.50", "source": "Synthetic closing observation", "effective_at": "2026-10-15T12:00:00Z"},
                               "unrealized_gain_account_code": "UNREAL_GAIN", "unrealized_loss_account_code": "UNREAL_LOSS",
                               "monetary_history_basis": {"source_fingerprint": source.fingerprint, "history_version": 2, "history_fingerprint": reader._digest(events[1])},
                               "lines": [{"account_code": "RECEIVABLE", "debit_minor": 140, "credit_minor": 0}, {"account_code": "UNREAL_GAIN", "debit_minor": 0, "credit_minor": 140}]}
    template = tables["finance_posting_effects"][0]
    original_plan: dict[str, Any] = {}
    parent_effect: str | None = None
    for sequence, inverse in ((2, False), (3, True)):
        plan_id = "FX1-" + ("b" if inverse else "a") * 32
        effect_id = "valuation-inverse-effect" if inverse else "valuation-effect"
        number = plan_id.upper()
        entry_id = "GLE-" + hashlib.sha256(("work|" + number).encode()).hexdigest()[:16]
        observed = equation
        if inverse:
            observed = {"original_revaluation_id": original_plan["id"], "original_plan_digest": original_plan["payload"]["plan_digest"],
                        "original_posting_effect_id": parent_effect, "original_equation_digest": reader._digest(equation), "unrealized_fx_minor": -140, "amount_minor": 140,
                        "lines": [{"account_code": "RECEIVABLE", "debit_minor": 0, "credit_minor": 140}, {"account_code": "UNREAL_GAIN", "debit_minor": 140, "credit_minor": 0}]}
        vectors = [("receivable", 0, 140), ("unreal-gain", 140, 0)] if inverse else [("receivable", 140, 0), ("unreal-gain", 0, 140)]
        header = {**template["snapshot_json"]["entry"], "id": entry_id, "entry_number": number, "external_reference": parent_effect if inverse else "FX:fx-source:revalue",
                  "source_type": "Generated" if inverse else "Manual", "reverses_posting_id": parent_effect if inverse else None}
        lines = [{"line_number": n, "account_id": account, "description": "", "debit_minor": dr, "credit_minor": cr, "dimensions": {}} for n, (account, dr, cr) in enumerate(vectors, 1)]
        snapshot = {"schema_version": "finance-entry-review-v1", "entry": header, "lines": lines}
        digest = reader._digest(snapshot)
        effect = {**template, "id": effect_id, "entry_id": entry_id, "source_kind": "Reversal" if inverse else "Manual", "source_id": parent_effect if inverse else entry_id,
                  "reverses_effect_id": parent_effect if inverse else None, "snapshot_json": snapshot, "validation_digest": digest, "audit_event_id": effect_id + "-audit", "outbox_event_id": effect_id + "-outbox"}
        tables["finance_posting_effects"].append(effect)
        tables["finance_entries"].append({**{key: value for key, value in header.items() if key not in {"organization_id", "legal_entity_id"}}, "tenant_id": "tenant", "status": "Validated", "validator_actor_id": "checker",
                                         "validation_digest": digest, "validation_contract_version": "finance-entry-review-v1", "total_debit_minor": 140, "total_credit_minor": 140})
        for n, line in enumerate(lines, 1):
            tables["finance_entry_lines"].append({key: value for key, value in {**line, "tenant_id": "tenant", "id": entry_id + "-" + str(n), "entry_id": entry_id, "currency_code": "USD"}.items() if key != "dimensions"})
        tables["domain_audit_events"].append({"tenant_id": "tenant", "id": effect["audit_event_id"]})
        tables["outbox_events"].append({"tenant_id": "tenant", "event_id": effect["outbox_event_id"]})
        body = {"id": plan_id, "source_id": "fx-source", "schema_version": "operational-fx-plan-v2", "kind": "reverse_revaluation" if inverse else "revalue", "sequence": sequence,
                "entry_id": entry_id, "equation": observed, "amount_minor": 140, "snapshot": snapshot, "preparer_actor_id": "maker", "posting_date": "2026-10-15"}
        body["plan_digest"] = reader._digest(body)
        body["validation_digest"] = digest
        native = {"tenant_id": "tenant", "workspace_id": "work", "organization_id": "org", "legal_entity_id": "entity", "id": plan_id, "source_id": "fx-source", "kind": body["kind"], "sequence": sequence, "phase": 2, "entry_id": entry_id, "payload": body}
        tables["operational_fx_plans"].append(native)
        tables["operational_fx_links"].append({"tenant_id": "tenant", "plan_id": plan_id, "posting_effect_id": effect_id, "receipt_id": None, "posted_actor_id": "poster"})
        tables["operational_fx_reviews"].append({"tenant_id": "tenant", "plan_id": plan_id, "reviewer_actor_id": "checker"})
        if not inverse:
            original_plan, parent_effect = native, effect_id
    return {name: sorted(json.dumps(row, sort_keys=True) for row in rows) for name, rows in tables.items()}


def test_closing_valuation_uses_credit_adjusted_560_700_and_exact140_inverse() -> None:
    capture = original_capture(valuation_tables())
    original = reader.verify_original_rows(capture, source_order_id="stock")
    events = reader.verify_history_rows(capture, original)
    assert reader.verify_valuation_rows(capture, original, events) == (("valuation-effect", "valuation-inverse-effect"), None)
    assert len(events) == 7  # Closing valuation does not invent monetary history.


@pytest.mark.parametrize("field,bad", [("foreign_outstanding_minor", 7400), ("historical_outstanding_minor", 9250), ("valued_outstanding_minor", 841), ("unrealized_fx_minor", 141)])
def test_resealed_valuation_must_use_actual_component_credit_adjusted_carrying(field: str, bad: int) -> None:
    tables = valuation_tables()
    plans = [json.loads(text) for text in tables["operational_fx_plans"]]
    native = next(row for row in plans if row["kind"] == "revalue")
    native["payload"]["equation"][field] = bad
    native["payload"]["plan_digest"] = reader._digest({key: value for key, value in native["payload"].items() if key not in {"plan_digest", "validation_digest"}})
    tables["operational_fx_plans"] = sorted(json.dumps(row, sort_keys=True) for row in plans)
    capture = original_capture(tables)
    original = reader.verify_original_rows(capture, source_order_id="stock")
    events = reader.verify_history_rows(capture, original)
    with pytest.raises(reader.MonetaryRawRefusal):
        reader.verify_valuation_rows(capture, original, events)


def audit_tables(*, append: bool, allowed: bool = True, surface: str = "GET /api/v3/customer-partial-returns/plans") -> dict[str, list[str]]:
    tables = original_tables()
    native: list[dict[str, Any]] = []
    previous = "0" * 64
    identifiers = ["cogs-effect-audit", "revenue-effect-audit"] + (["policy-event"] if append else [])
    for sequence, identifier in enumerate(identifiers, 1):
        metadata: dict[str, Any] = {}
        policy: dict[str, Any] = {}
        if identifier == "policy-event":
            policy = {"schema_version": 1, "policy_version": "central-policy-v3", "allowed": allowed, "reason_code": "allowed" if allowed else "entity_scope_denied", "evaluator": "central-policy",
                      "principal_type": "user", "actor_digest": reader._text_digest("principal.actor", "poster"),
                      "required_permission_digest": reader._audit_digest({"namespace": "permission.contract", "values": ["finance_core.read"]}),
                      "granted_permission_digest": reader._text_digest("permission.granted", "finance_core.read") if allowed else None,
                      "context_binding": "bound", "context_digest": "a" * 64, "scope_digest": "b" * 64,
                      "surface_digest": reader._text_digest("audit.surface", surface), "request_id_digest": "c" * 64}
            policy["decision_digest"] = reader._audit_digest(policy)
            metadata = {"policy_decision_evidence": policy, "request_id_digest": policy["request_id_digest"]}
        event = {"tenant_id": "tenant", "id": identifier, "sequence": sequence, "previous_hash": previous,
                 "actor_user_id": "poster", "actor_label": "policy-engine" if policy else "Synthetic poster",
                 "object_type": "authorization.policy_decision" if policy else "finance_posting", "object_id": policy["decision_digest"] if policy else "posting",
                 "action": "evaluated" if policy else "finance_entry_posted", "before_hash": None,
                 "after_hash": policy["decision_digest"] if policy else None, "metadata_json": metadata, "created_at": "2026-10-15T12:00:0" + str(sequence) + "Z"}
        unsigned = {key: value for key, value in event.items() if key != "tenant_id"}
        unsigned["metadata_json"] = reader._audit_json(metadata)
        previous = reader._audit_digest(unsigned)
        event["event_hash"] = previous
        native.append(event)
    tables["domain_audit_events"] = sorted(json.dumps(row, sort_keys=True) for row in native)
    tables["domain_audit_ledger_state"] = [json.dumps({"tenant_id": "tenant", "last_sequence": len(native), "last_event_hash": previous, "updated_at": native[-1]["created_at"]}, sort_keys=True)]
    return tables


def test_new_monetary_audit_only_transition_retains_all89_business_tables() -> None:
    result = reader.verify_audit_only_transition(audit_tables(append=False), audit_tables(append=True), tenant_id="tenant")
    assert result == {"business_tables": 89, "business_original_rows_equal": True, "audit_original_prefix_equal": True,
                      "audit_chain_valid": True, "audit_actions_bound": True, "appended_audit_events": 1}


def complete_final_tables() -> dict[str, list[str]]:
    """Finite synthetic native rows, never a claimed actual database capture."""
    tables = {name: [json.loads(text) for text in values] for name, values in valuation_tables().items()}
    scope = {key: "tenant" if key == "tenant_id" else "work" if key == "workspace_id" else "org" if key == "organization_id" else "entity"
             for key in ("tenant_id", "workspace_id", "organization_id", "legal_entity_id")}
    template = tables["finance_posting_effects"][0]
    full = {key: value for key, value in template.items() if key.startswith("currency_")}
    header = {**template["snapshot_json"]["entry"], "id": "receipt-entry", "entry_number": "IRP-SYNTHETIC", "external_reference": "receipt-plan", "source_type": "Generated"}
    lines = [{"line_number": n, "account_id": account, "description": "", "debit_minor": dr, "credit_minor": cr, "dimensions": {}}
             for n, (account, dr, cr) in enumerate((("inventory", 12000, 0), ("clearing", 0, 12000)), 1)]
    snapshot = {"schema_version": "finance-entry-review-v1", "entry": header, "lines": lines}
    digest = reader._digest(snapshot)
    tables["finance_accounts"].append({"tenant_id": "tenant", "workspace_id": "work", "id": "clearing", "account_code": "CLEARING", "account_type": "Liability"})
    tables["finance_posting_effects"].append({**template, "id": "receipt-effect", "entry_id": "receipt-entry", "source_kind": "InventoryReceipt", "source_id": "receipt-plan",
                                             "snapshot_json": snapshot, "validation_digest": digest, "audit_event_id": "receipt-audit", "outbox_event_id": "receipt-outbox"})
    tables["finance_entries"].append({**{key: value for key, value in header.items() if key not in {"organization_id", "legal_entity_id"}}, "tenant_id": "tenant", "status": "Validated",
                                    "validator_actor_id": "checker", "validation_digest": digest, "validation_contract_version": "finance-entry-review-v1", "total_debit_minor": 12000, "total_credit_minor": 12000})
    tables["finance_entry_lines"].extend({key: value for key, value in {**line, "tenant_id": "tenant", "entry_id": "receipt-entry", "id": "receipt-line-" + str(line["line_number"]), "currency_code": "USD"}.items() if key != "dimensions"} for line in lines)
    tables["inventory_receipt_plans"] = [{**scope, **full, "id": "receipt-plan", "operation": "Receipt", "total_value_minor": 12000, "finance_entry_id": "receipt-entry", "posting_effect_id": "receipt-effect",
                                         "inventory_account_id": "inventory", "receipt_clearing_account_id": "clearing", "preparer_actor_id": "maker", "plan_digest": "a" * 64}]
    tables["inventory_receipt_links"] = [{**scope, "plan_id": "receipt-plan", "posting_effect_id": "receipt-effect", "posted_actor_id": "poster", "plan_digest": "a" * 64}]
    tables["inventory_receipt_reviews"] = [{"tenant_id": "tenant", "plan_id": "receipt-plan", "reviewer_actor_id": "checker", "plan_digest": "a" * 64}]
    for plan in tables["customer_partial_return_monetary_plans"]:
        body = plan["payload"]
        body.update(id=plan["id"], source_id="origin", source_order_id="stock", operation=plan["operation"], original_id=plan["original_id"])
        body["plan_digest"] = reader._digest({key: value for key, value in body.items() if key != "plan_digest"})
        plan["plan_digest"] = body["plan_digest"]
        for event in [row for row in tables["customer_partial_return_monetary_events"] if row["plan_id"] == plan["id"]]:
            event["audit_event_id"] = plan["id"] + "-audit-" + event["operation"]
            event["outbox_event_id"] = plan["id"] + "-outbox-" + event["operation"]
            command = storage_row("customer_partial_return_monetary_commands")
            request = {"protocol_version": 3, "actor_id": event["actor_id"], "operation": event["operation"], "request": {"plan_id": plan["id"]}}
            command.update(**scope, plan_id=plan["id"], command_id=plan["id"] + "-" + event["operation"], actor_id=event["actor_id"], operation=event["operation"],
                           request_json=request, request_digest=reader._digest(request), response_json={"id": plan["id"], "plan_digest": plan["plan_digest"]})
            tables["customer_partial_return_monetary_commands"].append(command)
    metadata: dict[str, tuple[str, str, str, dict[str, Any]]] = {}
    for effect in tables["finance_posting_effects"]:
        metadata[effect["audit_event_id"]] = ("poster", "finance_posting", effect["id"], {})
        if not any(row.get("event_id") == effect["outbox_event_id"] for row in tables["outbox_events"]):
            tables["outbox_events"].append({"tenant_id": "tenant", "event_id": effect["outbox_event_id"]})
    for event in tables["customer_partial_return_monetary_events"]:
        plan = next(row for row in tables["customer_partial_return_monetary_plans"] if row["id"] == event["plan_id"])
        payload = {"plan_digest": plan["plan_digest"], "reason": event["reason"]}
        metadata[event["audit_event_id"]] = (event["actor_id"], "operational_finance", plan["id"], payload)
        tables["outbox_events"].append({**scope, "event_id": event["outbox_event_id"], "event_type": "customer_partial_return_monetary_" + event["operation"],
                                         "aggregate_type": "operational_finance", "aggregate_id": plan["id"], "payload": {**payload, "audit_event_id": event["audit_event_id"]}})
    audits: list[dict[str, Any]] = []
    previous = "0" * 64
    for sequence, (identifier, (actor, object_type, object_id, payload)) in enumerate(metadata.items(), 1):
        native_event = next((row for row in tables["customer_partial_return_monetary_events"] if row["audit_event_id"] == identifier), None)
        action = "customer_partial_return_monetary_" + native_event["operation"] if native_event else "finance_entry_posted"
        event = {"tenant_id": "tenant", "id": identifier, "sequence": sequence, "previous_hash": previous, "actor_user_id": actor, "actor_label": actor,
                 "object_type": object_type, "object_id": object_id, "action": action, "before_hash": None, "after_hash": None, "metadata_json": payload, "created_at": "2026-10-15T12:00:00Z"}
        signed = {key: value for key, value in event.items() if key != "tenant_id"}
        signed["metadata_json"] = reader._audit_json(payload)
        previous = reader._audit_digest(signed)
        event["event_hash"] = previous
        audits.append(event)
    tables["domain_audit_events"] = audits
    tables["domain_audit_ledger_state"] = [{"tenant_id": "tenant", "last_sequence": len(audits), "last_event_hash": previous, "updated_at": audits[-1]["created_at"]}]
    history = sorted(tables["customer_partial_return_monetary_history"], key=lambda row: row["sequence"])
    tables["stock_sales_monetary_origins"][0]["ar_balance"] = {"schema_version": "stock-monetary-balance-v1", "history_version": 7, "history_fingerprint": reader._digest(history[-1]["payload"]),
        "transaction_original_gross_minor": "11400", "functional_original_gross_minor": "14250", "transaction_collected_minor": "4000", "transaction_credited_minor": "11400",
        "transaction_outstanding_minor": "0", "functional_outstanding_minor": "0", "transaction_refund_entitlement_minor": "4000", "functional_refund_entitlement_minor": "5000",
        "transaction_refunded_minor": "4000", "functional_refund_released_minor": "5000", "transaction_refund_due_minor": "0", "functional_refund_due_minor": "0", "active_plan_id": None, "active_revaluation_plan_id": None}
    tables["ar_invoices"][0]["status"] = "Paid"
    return {name: sorted(json.dumps(row, sort_keys=True) for row in rows) for name, rows in tables.items()}


def test_complete_financial_trace_rederives_every_effect_and_retains_no_native_claim() -> None:
    tables = complete_final_tables()
    value = {"schema_version": reader.SCHEMA, "tenant_id": "tenant", "source_order_id": "stock", "captures": [{"capture": index, "tables": tables} for index in range(2)]}
    proof = reader.qualify_raw_cycle(reader.decode_packet(encoded(value)))
    assert (proof["final_posting_effects"], proof["final_posted_lines"], proof["final_debits_minor"]) == (14, 37, "81605")
    assert proof["current_authorization_proven"] is False and proof["observations"] == 0 and proof["populated_restore_original_rows_equal"] is False


def test_scope_refusal_permits_only_the_known_denied_current_read_surface() -> None:
    before = audit_tables(append=False)
    after = audit_tables(append=True, allowed=False, surface="server.scoped:finance_core.read")
    assert reader.verify_audit_only_transition(before, after, tenant_id="tenant", scope_refusal=True)["appended_audit_events"] == 1
    with pytest.raises(reader.MonetaryRawRefusal):
        reader.verify_audit_only_transition(before, after, tenant_id="tenant")


@pytest.mark.parametrize("mutation", ["business", "hash", "gap", "head", "audit-mutation", "unrelated-action", "unknown-actor", "unknown-field"])
def test_audit_chain_and_action_affinity_do_not_hide_financial_or_earlier_original_changes(mutation: str) -> None:
    before, after = audit_tables(append=False), audit_tables(append=True)
    if mutation == "business":
        rows = [json.loads(text) for text in after["finance_entry_lines"]]
        rows[0]["debit_minor"] += 1
        after["finance_entry_lines"] = sorted(json.dumps(row, sort_keys=True) for row in rows)
    elif mutation == "head":
        head = json.loads(after["domain_audit_ledger_state"][0])
        head["last_event_hash"] = "f" * 64
        after["domain_audit_ledger_state"] = [json.dumps(head, sort_keys=True)]
    else:
        events = sorted((json.loads(text) for text in after["domain_audit_events"]), key=lambda row: row["sequence"])
        if mutation == "hash":
            events[-1]["event_hash"] = "f" * 64
        elif mutation == "gap":
            events[-1]["sequence"] = 4
        elif mutation == "audit-mutation":
            events[0]["actor_label"] = "Rewritten old actor"
        elif mutation == "unrelated-action":
            after = audit_tables(append=True, surface="POST /api/v1/admin/access/roles")
            events = [json.loads(text) for text in after["domain_audit_events"]]
        elif mutation == "unknown-actor":
            events[-1]["actor_user_id"] = "foreign-human"
        else:
            events[-1]["unknown"] = "future"
        after["domain_audit_events"] = sorted(json.dumps(row, sort_keys=True) for row in events)
    with pytest.raises(reader.MonetaryRawRefusal):
        reader.verify_audit_only_transition(before, after, tenant_id="tenant", scope_refusal=True)


def test_inventory_is_exact_old79_plus_five_fx_and_seven_monetary_tables() -> None:
    tree = ast.parse(Path(__file__).with_name("customer_partial_return_posted_cycle_oracle.py").read_text(encoding="utf-8"))
    original = next(ast.literal_eval(item.value) for item in tree.body if isinstance(item, ast.Assign)
                    and any(isinstance(target, ast.Name) and target.id == "TABLES" for target in item.targets))
    expected = set(original) | {"customer_partial_return_allocation_witnesses", "stock_sales_monetary_origins"}
    expected |= {"operational_fx_" + name for name in ("sources", "plans", "reviews", "links", "commands")}
    expected |= {"customer_partial_return_monetary_" + name for name in
                 ("plans", "entries", "events", "history", "restorations", "commands")}
    assert len(original) == 78 and len(expected) == 91
    assert tuple(sorted(expected)) == reader.TABLES


def test_exact_opaque_row_bytes_and_parent_packet_digest_are_retained() -> None:
    value = packet()
    raw = '{"tenant_id": "tenant", "id": "native", "quantity": 0.1, "value_minor": 1001}'
    value["captures"][1]["tables"]["inventory_layer_consumptions"] = [raw]
    original = encoded(value)
    result = reader.decode_packet(original)
    assert result.sha256 == hashlib.sha256(original).hexdigest() and result.byte_size == len(original)
    assert result.tenant_id == "tenant" and result.source_order_id == "STSALE-original"
    assert dict(result.captures[1].raw_tables)["inventory_layer_consumptions"] == (raw,)
    assert result.captures[1].rows("inventory_layer_consumptions")[0]["quantity"] == Fraction(1, 10)
    assert type(result.captures[1].rows("inventory_layer_consumptions")[0]["value_minor"]) is int
    assert not hasattr(result, "financially_verified") and not hasattr(result, "native_acceptance")


@pytest.mark.parametrize("table", reader.MONETARY_COLUMNS)
def test_seven_storage_shapes_are_closed_without_claiming_deferred_closure(table: str) -> None:
    value = storage_row(table)
    result = reader.decode_packet(with_storage(table, value))
    assert result.captures[1].rows(table) == (value,)
    for field in value:
        incomplete = dict(value)
        incomplete.pop(field)
        with pytest.raises(reader.MonetaryRawRefusal):
            reader.decode_packet(with_storage(table, incomplete))
    with pytest.raises(reader.MonetaryRawRefusal):
        reader.decode_packet(with_storage(table, {**value, "unknown_future_column": None}))


@pytest.mark.parametrize("table,field,invalid", [
    ("customer_partial_return_monetary_plans", "phase", True),
    ("customer_partial_return_monetary_plans", "phase", 4),
    ("customer_partial_return_monetary_plans", "expected_history_version", 256),
    ("customer_partial_return_monetary_plans", "id", "CR2-" + "1" * 32),
    ("customer_partial_return_monetary_entries", "entry_id", None),
    ("customer_partial_return_monetary_entries", "original_effect_id", "foreign-inverse"),
    ("customer_partial_return_monetary_events", "operation", "repost"),
    ("customer_partial_return_monetary_history", "sequence", True),
    ("customer_partial_return_monetary_history", "sequence", 257),
    ("customer_partial_return_monetary_history", "stock_fx_plan_id", "FX1-extra"),
    ("customer_partial_return_monetary_restorations", "before_value_minor", -1),
    ("customer_partial_return_monetary_restorations", "quantity_scaled", 3),
    ("customer_partial_return_monetary_restorations", "consumption_count_at_restore", 0),
    ("customer_partial_return_monetary_commands", "request_digest", "A" * 64),
])
def test_new_native_shape_type_and_nullable_effect_invariants(table: str, field: str, invalid: Any) -> None:
    value = storage_row(table)
    value[field] = invalid
    with pytest.raises(reader.MonetaryRawRefusal):
        reader.decode_packet(with_storage(table, value))


@pytest.mark.parametrize("original", [None, False, 0, 2])
def test_reversal_history_cannot_use_sql_check_null_or_nonpreceding_original(original: Any) -> None:
    table = "customer_partial_return_monetary_history"
    value = storage_row(table)
    value.update(kind="ReverseReturn", sequence=2, original_sequence=original)
    with pytest.raises(reader.MonetaryRawRefusal):
        reader.decode_packet(with_storage(table, value))


def test_zero_portion_can_share_positive_plan_effect_but_positive_portion_requires_one() -> None:
    table = "customer_partial_return_monetary_restorations"
    value = storage_row(table)
    assert reader.decode_packet(with_storage(table, value))
    value["correction_effect_id"] = "real-plan-total-effect"
    assert reader.decode_packet(with_storage(table, value))
    value.update(value_minor=1, correction_effect_id=None)
    with pytest.raises(reader.MonetaryRawRefusal):
        reader.decode_packet(with_storage(table, value))


def test_different_raw_texts_cannot_forge_duplicate_new_primary_keys() -> None:
    table = "customer_partial_return_monetary_events"
    first = storage_row(table)
    second = {**first, "reason": "Different reason for the same primary key"}
    value = packet()
    value["captures"][1]["tables"][table] = sorted([json.dumps(first), json.dumps(second)])
    with pytest.raises(reader.MonetaryRawRefusal):
        reader.decode_packet(encoded(value))


@pytest.mark.parametrize("name", reader.TABLES)
def test_every_missing_table_refuses_including_empty_financial_owners(name: str) -> None:
    value = packet()
    value["captures"][1]["tables"].pop(name)
    with pytest.raises(reader.MonetaryRawRefusal):
        reader.decode_packet(encoded(value))


@pytest.mark.parametrize("mutation", ["schema", "extra", "missing", "unknown-table", "bool-index", "gap", "duplicate-index",
                                     "one-capture", "too-many", "tenant", "order", "capture-extra"])
def test_closed_envelopes_and_ordered_capture_membership(mutation: str) -> None:
    value = packet()
    if mutation == "schema":
        value["schema_version"] = "customer-partial-return-remainder-posted-cycle-input-v1"
    elif mutation == "extra":
        value["trusted"] = True
    elif mutation == "missing":
        value.pop("tenant_id")
    elif mutation == "unknown-table":
        value["captures"][0]["tables"]["unknown_future_owner"] = []
    elif mutation == "bool-index":
        value["captures"][1]["capture"] = True
    elif mutation == "gap":
        value["captures"][1]["capture"] = 2
    elif mutation == "duplicate-index":
        value["captures"][1]["capture"] = 0
    elif mutation == "one-capture":
        value["captures"].pop()
    elif mutation == "too-many":
        value["captures"] *= 129
    elif mutation == "tenant":
        value["tenant_id"] = " tenant "
    elif mutation == "order":
        value["source_order_id"] = "../outside"
    else:
        value["captures"][0]["case"] = "synthetic"
    with pytest.raises(reader.MonetaryRawRefusal):
        reader.decode_packet(encoded(value))


@pytest.mark.parametrize("rows", [[row(tenant="other")], [row("same"), row("same")], [row("z"), row("a")],
                                  [1], [False], [None], [{}], ["[]"], ["null"], ["{}"]])
def test_foreign_duplicate_unsorted_or_non_pg_record_rows_refuse(rows: Any) -> None:
    value = packet()
    value["captures"][1]["tables"]["operational_fx_commands"] = rows
    with pytest.raises(reader.MonetaryRawRefusal):
        reader.decode_packet(encoded(value))


@pytest.mark.parametrize("bad", ["1e100000000", "NaN", "Infinity", "-Infinity", "9000000000000000001", "1" * 97])
def test_numeric_lexemes_are_bounded_before_integer_or_fraction_expansion(bad: str) -> None:
    value = packet()
    value["captures"][0]["tables"]["operational_fx_sources"] = ['{"tenant_id":"tenant","amount":' + bad + '}']
    with pytest.raises(reader.MonetaryRawRefusal):
        reader.decode_packet(encoded(value))


@pytest.mark.parametrize("where", ["outer", "row"])
def test_duplicate_json_keys_never_last_win(where: str) -> None:
    value = packet()
    if where == "row":
        value["captures"][0]["tables"]["stock_sales_monetary_origins"] = ['{"tenant_id":"other","tenant_id":"tenant"}']
        original = encoded(value)
    else:
        original = encoded(value).replace(b'"tenant_id":"tenant"', b'"tenant_id":"other","tenant_id":"tenant"', 1)
    with pytest.raises(reader.MonetaryRawRefusal):
        reader.decode_packet(original)


def test_invalid_utf8_and_escaped_unpaired_surrogate_rows_refuse() -> None:
    with pytest.raises(reader.MonetaryRawRefusal):
        reader.decode_packet(b"\xff")
    value = packet()
    value["captures"][0]["tables"]["operational_fx_commands"] = ['{"tenant_id":"tenant","id":"\ud800"}']
    original = json.dumps(value, ensure_ascii=True).encode()
    with pytest.raises(reader.MonetaryRawRefusal):
        reader.decode_packet(original)


def test_packet_capture_row_and_rowcount_budgets_are_enforced(monkeypatch: pytest.MonkeyPatch) -> None:
    original = encoded(packet())
    monkeypatch.setattr(reader, "MAX_PACKET_BYTES", len(original) - 1)
    with pytest.raises(reader.MonetaryRawRefusal):
        reader.decode_packet(original)
    monkeypatch.setattr(reader, "MAX_PACKET_BYTES", len(original) + 10000)
    value = packet()
    value["captures"][0]["tables"]["stock_sales_monetary_origins"] = [row()]
    monkeypatch.setattr(reader, "MAX_ROW_BYTES", 1)
    with pytest.raises(reader.MonetaryRawRefusal):
        reader.decode_packet(encoded(value))
    monkeypatch.setattr(reader, "MAX_ROW_BYTES", 1000)
    monkeypatch.setattr(reader, "MAX_CAPTURE_ROWS", 0)
    with pytest.raises(reader.MonetaryRawRefusal):
        reader.decode_packet(encoded(value))
    monkeypatch.setattr(reader, "MAX_CAPTURE_ROWS", 20_000)
    monkeypatch.setattr(reader, "MAX_CAPTURE_BYTES", 1)
    with pytest.raises(reader.MonetaryRawRefusal):
        reader.decode_packet(encoded(value))


def test_bounded_original_file_and_second_byte_comparison(tmp_path: Path) -> None:
    path = tmp_path / "original.json"
    original = encoded(packet())
    path.write_bytes(original)
    assert reader.read_original(path) == original
    reader.require_original_unchanged(path, original)
    path.write_bytes(original.replace(b"STSALE-original", b"STSALE-modified"))
    with pytest.raises(reader.MonetaryRawRefusal):
        reader.require_original_unchanged(path, original)
    with pytest.raises(reader.MonetaryRawRefusal):
        reader.read_original(tmp_path)
    with pytest.raises(reader.MonetaryRawRefusal):
        reader.read_original(Path("relative.json"))
    with pytest.raises(reader.MonetaryRawRefusal):
        reader.read_original(tmp_path / ".." / tmp_path.name / "original.json")


def test_reparse_ancestor_refuses_using_real_lstat_fields(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    path = tmp_path / "original.json"
    path.write_bytes(encoded(packet()))
    real = Path.lstat

    def fake(selected: Path) -> Any:
        result = real(selected)
        if selected != tmp_path:
            return result
        fields = {name: getattr(result, name) for name in dir(result) if name.startswith("st_")}
        fields["st_file_attributes"] = getattr(result, "st_file_attributes", 0) | 0x400
        return SimpleNamespace(**fields)

    monkeypatch.setattr(Path, "lstat", fake)
    with pytest.raises(reader.MonetaryRawRefusal):
        reader.read_original(path)
