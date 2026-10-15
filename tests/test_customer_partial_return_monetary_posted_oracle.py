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
    revenue = effect("revenue-effect", "revenue-entry", [("receivable", gross, 0), ("revenue", 0, local_net), ("tax", 0, local_tax)], "recognition")
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
            fx_plan = {"tenant_id": "tenant", "workspace_id": "work", "organization_id": "org", "legal_entity_id": "entity", "id": "collection", "source_id": "fx-source", "kind": "settle", "phase": 2,
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
