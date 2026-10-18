"""Standalone PRIVATE SQL-row oracle for one declared, unposted CR2 source.

Run directly with Python -I / -I -O. All six native cases may supply exact
before/after custody; only the declared two-layer case has a financial oracle.
No application, database, browser or installed currency registry is imported.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from pathlib import Path
from typing import Any, cast

TABLES = tuple(["ar_customers", "ar_idempotency_keys", "ar_invoice_lines", "ar_invoices", "ar_receipt_allocations", "ar_receipts", "commercial_collection_cancellations", "commercial_collection_commands", "commercial_collection_links", "commercial_collection_plans", "commercial_collection_reviews", "customer_return_commands", "customer_return_events", "customer_return_plans", "domain_audit_events", "domain_audit_ledger_state", "finance_accounts", "finance_charts", "finance_dimension_values", "finance_dimensions", "finance_entries", "finance_entry_line_dimensions", "finance_entry_lines", "finance_journals", "finance_posting_commands", "finance_posting_effects", "inventory_cost_layers", "inventory_count_lines", "inventory_count_sessions", "inventory_items", "inventory_layer_consumptions", "inventory_locations", "inventory_lots", "inventory_movement_lines", "inventory_movements", "inventory_quantity_claim_gates", "inventory_quantity_source_guards", "inventory_quantity_source_releases", "inventory_receipt_commands", "inventory_receipt_links", "inventory_receipt_plans", "inventory_receipt_reviews", "inventory_reorder_rules", "inventory_transfer_claims", "inventory_transfer_commands", "inventory_transfer_events", "inventory_transfer_releases", "inventory_transfer_sources", "inventory_units_of_measure", "inventory_valuation_documents", "inventory_valuation_input_costs", "inventory_valuation_lines", "inventory_valuation_policies", "inventory_valuation_reversal_effects", "inventory_valuation_reversals", "inventory_warehouses", "operational_finance_commands", "operational_finance_links", "operational_finance_plans", "operational_finance_reviews", "outbox_consumer_receipts", "outbox_delivery_evidence", "outbox_events", "stock_commerce_commands", "stock_commerce_lines", "stock_commerce_orders", "stock_commerce_tranches", "stock_sales_commands", "stock_sales_events", "stock_sales_issue_claims", "stock_sales_orders", "stock_sales_reservations"])
CASE_PREFIX = "tests/test_postgres_customer_partial_return_source.py::"
TWO_LAYER = CASE_PREFIX + "test_real_two_layer_issue_order_becomes_typed_source_and_exact_unposted_corrections_without_any_row_change"
CASES = (TWO_LAYER, CASE_PREFIX + "test_caller_membership_source_swaps_and_boolean_money_are_not_native_evidence",
         CASE_PREFIX + "test_retained_registry_context_is_used_without_installing_or_recapturing_current_policy",
         CASE_PREFIX + "test_fully_paid_real_source_preserves_original_cash_owner_membership[full-commercial]",
         CASE_PREFIX + "test_fully_paid_real_source_preserves_original_cash_owner_membership[full-stock]",
         CASE_PREFIX + "test_real_differing_owned_cash_accounts_are_a_finite_refund_scope_refusal")
MAPPED_FULL_CASES = (TWO_LAYER, CASES[2], CASES[2], CASES[3], CASES[4])
RAW_NAME = re.compile(r"native-financial-rows-original-([1-9][0-9]?)\.json")
MAP_NAME = re.compile(r"native-source-original-([1-9][0-9]?)\.json")
PROPOSAL_NAME = "native-unposted-partial-return-proposal-original-1.json"
MAX_BYTES = 4 * 1024 * 1024
DOMAIN_VERSION = "customer-partial-return-domain-v1"
SCOPE_KEYS = {"tenant_id", "workspace_id", "organization_id", "legal_entity_id", "item_id", "location_id", "uom_id"}
POLICY_KEYS = ("currency_code", "currency_precision", "currency_rounding_policy", "currency_registry_version", "currency_registry_digest")


class OracleRefusal(ValueError):
    """A constant refusal does not echo financial rows, paths or credentials."""


def require(value: bool) -> None:
    if not value:
        raise OracleRefusal("Independent native source contract refused.")


def integer(value: Any, *, positive: bool = False) -> int:
    require(type(value) is int and 0 <= value <= 9_000_000_000_000_000_000)
    require(not positive or value > 0)
    return int(value)


def text(value: Any) -> str:
    require(type(value) is str and 0 < len(value) <= 200)
    return str(value)


def decimal(token: str) -> Decimal:
    require(type(token) is str and len(token) <= 80 and
            re.fullmatch(r"-?[0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]{1,2})?", token) is not None)
    result = Decimal(token)
    require(result.is_finite())
    exponent = result.as_tuple().exponent
    require(type(exponent) is int and abs(cast(int, exponent)) <= 64 and len(result.as_tuple().digits) <= 64)
    return result


def fraction(value: Any) -> Fraction:
    require(type(value) in {int, Decimal, str})
    if type(value) is Decimal:
        require(value.is_finite())
        parts = value.as_tuple()
        require(type(parts.exponent) is int and abs(cast(int, parts.exponent)) <= 64 and len(parts.digits) <= 64)
    elif type(value) is int:
        require(value.bit_length() <= 256)
    result = Fraction(decimal(value) if type(value) is str else value)
    require(result.numerator.bit_length() <= 256 and result.denominator.bit_length() <= 256)
    return result


def _pairs(values: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in values:
        require(key not in result)
        result[key] = value
    return result


def _bad_constant(_: str) -> Any:
    raise OracleRefusal("Independent native source contract refused.")


def _parse_int(token: str) -> int:
    require(len(token) <= 20)
    return int(token)


def _walk(value: Any, depth: int = 0, budget: list[int] | None = None) -> None:
    budget = [100_000] if budget is None else budget
    budget[0] -= 1
    require(budget[0] >= 0 and depth <= 32)
    if type(value) is dict:
        require(len(value) <= 1000)
        for key, child in value.items():
            require(type(key) is str and len(key) <= 200)
            _walk(child, depth + 1, budget)
    elif type(value) is list:
        require(len(value) <= 4000)
        for child in value:
            _walk(child, depth + 1, budget)
    elif type(value) is str:
        require(len(value) <= 131_072)
    elif type(value) is Decimal:
        fraction(value)
    else:
        require(type(value) in {int, bool, type(None)})


def decode(raw: bytes | str) -> Any:
    try:
        require(type(raw) in {str, bytes} and len(raw if isinstance(raw, bytes) else raw.encode("utf8")) <= MAX_BYTES)
        value = json.loads(raw, object_pairs_hook=_pairs, parse_int=_parse_int, parse_float=decimal, parse_constant=_bad_constant)
        _walk(value)
        return value
    except (ValueError, TypeError, UnicodeError, RecursionError, InvalidOperation) as exc:
        raise OracleRefusal("Independent native source contract refused.") from exc


def canonical(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf8")
    except (ValueError, TypeError, UnicodeError) as exc:
        raise OracleRefusal("Independent native source contract refused.") from exc


def same(left: Any, right: Any) -> bool:
    return canonical(left) == canonical(right)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def index(rows: list[dict[str, Any]], count: int | None = None, key: str = "id") -> dict[str, dict[str, Any]]:
    require(type(rows) is list and (count is None or len(rows) == count))
    result = {text(row[key]): row for row in rows}
    require(len(result) == len(rows))
    return result


def raw_tables(envelope: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    require(type(envelope) is dict and set(envelope) == {"schema_version", "case", "retained_state_digest", "tables", "invoice_quantity_text_witness"})
    require(envelope["schema_version"] == "native-partial-source-financial-rows-v1" and envelope["case"] in CASES)
    require(type(envelope["tables"]) is dict and set(envelope["tables"]) == set(TABLES))
    require(re.fullmatch(r"[a-f0-9]{64}", text(envelope["retained_state_digest"])) is not None)
    result = {}
    for table, originals in envelope["tables"].items():
        require(type(originals) is list and all(type(row) is str for row in originals))
        require(originals == sorted(originals) and len(set(originals)) == len(originals))
        rows = [decode(row) for row in originals]
        require(all(type(row) is dict for row in rows))
        # Native scalar columns are authoritative integers. Opaque nested ACK
        # DTOs can legitimately serialize money as strings; they are custody
        # evidence only and never feed this financial calculation.
        for row in rows:
            for key, value in row.items():
                if key.endswith(("_minor", "_scaled", "_precision")) and value is not None:
                    integer(value)
        if rows and all("id" in row for row in rows):
            index(rows)
        result[table] = rows
    witnesses = envelope["invoice_quantity_text_witness"]
    require(type(witnesses) is list and len(witnesses) == len(result["ar_invoice_lines"]))
    witness_index = index(witnesses)
    for row in result["ar_invoice_lines"]:
        witness = witness_index[row["id"]]
        require(set(witness) == {"id", "invoice_id", "quantity_numeric_text", "quantity_text"})
        require(witness["invoice_id"] == row["invoice_id"] and witness["quantity_text"] == row["quantity_text"])
        require(fraction(row["quantity"]) == fraction(witness["quantity_numeric_text"]) == fraction(row["quantity_text"]))
    return result


def _policy(row: dict[str, Any], policy: dict[str, Any]) -> None:
    require(all(key in row and same(row[key], policy[key]) for key in POLICY_KEYS))


def _scope(row: dict[str, Any], scope: dict[str, Any]) -> None:
    require(all(row[key] == scope[key] for key in ("tenant_id", "workspace_id", "organization_id", "legal_entity_id")))


def _verify_two_layer(envelope: dict[str, Any], observed: dict[str, Any], proposal: dict[str, Any] | None = None) -> dict[str, Any]:
    """Hand-derived finite facts, independently bound to actual retained SQL rows."""
    tables = raw_tables(envelope)
    require(observed["schema_version"] == "native-partial-return-source-original-v1" and observed["case"] == envelope["case"] == TWO_LAYER)
    require(set(observed) == {"schema_version", "case", "typed_source", "original_source_json", "collection_evidence_json", "captured_registry_snapshot"})
    typed = observed["typed_source"]
    require(type(typed) is dict and set(typed) == {"scope", "source_order_id", "invoice_id", "valuation_document_id", "original_revenue_plan_id", "quantity_precision", "quantity_scaled", "gross_minor", "net_unit_price_minor", "collected_minor", "currency_policy", "consumptions", "functional_currency", "base_uom_id", "tax_minor", "inventory_lot_id", "serial_tracked", "source_fingerprint", "original_cogs_snapshot_json", "original_revenue_snapshot_json"})
    scope, captured = typed["scope"], observed["captured_registry_snapshot"]
    require(type(scope) is dict and set(scope) == SCOPE_KEYS and all(type(value) is str and text(value) for value in scope.values()))
    native_policy = typed["currency_policy"]
    require(set(native_policy) == {"currency_code", "precision", "rounding_policy", "registry_version", "registry_digest"})
    require(native_policy["currency_code"] == typed["functional_currency"] == "USD" and integer(native_policy["precision"]) == 2)
    require(native_policy["rounding_policy"] == "ROUND_HALF_UP" and set(captured) == {"currencies", "digest", "published_at", "registry_version", "schema_version", "source", "source_url"})
    require(type(captured["schema_version"]) is int and captured["schema_version"] == 1)
    require(captured["digest"] == native_policy["registry_digest"] == digest({key: value for key, value in captured.items() if key != "digest"}))
    registry = index(captured["currencies"], key="code")
    require(registry["USD"]["minor_units"] == 2 and type(registry["USD"]["minor_units"]) is int and registry["USD"]["rounding_policy"] == "ROUND_HALF_UP")
    require(captured["registry_version"] == native_policy["registry_version"])
    policy = dict(zip(POLICY_KEYS, ("USD", 2, "ROUND_HALF_UP", native_policy["registry_version"], native_policy["registry_digest"]), strict=True))
    stock = next(iter(index(tables["stock_sales_orders"], 1).values()))
    invoice = next(iter(index(tables["ar_invoices"], 1).values()))
    invoice_line = next(iter(index(tables["ar_invoice_lines"], 1).values()))
    _scope(stock, scope)
    _scope(invoice, scope)
    _policy(invoice, policy)
    require(stock["id"] == typed["source_order_id"] and stock["invoice_id"] == invoice["id"] == typed["invoice_id"])
    require(all(stock[key] == scope[key] for key in ("item_id", "location_id", "uom_id")))
    require(all(row["tenant_id"] == scope["tenant_id"] for rows in tables.values() for row in rows))
    require(stock["valuation_id"] == typed["valuation_document_id"] and stock["invoice_plan_id"] == typed["original_revenue_plan_id"])
    require(stock["status"] == "Invoiced" and invoice["status"] == "PartiallyPaid" and invoice["customer_return_owner_id"] is None)
    require(stock["customer_id"] == invoice["customer_id"] and stock["currency_code"] == "USD")
    require(integer(stock["quantity_scaled"]) == integer(typed["quantity_scaled"]) == 15 and integer(stock["quantity_precision"]) == integer(typed["quantity_precision"]) == 0)
    require(integer(stock["total_minor"]) == integer(invoice["total_minor"]) == integer(typed["gross_minor"]) == 67500)
    require(invoice_line["invoice_id"] == invoice["id"] and fraction(invoice_line["quantity"]) == fraction(invoice_line["quantity_text"]) == 15)
    require(integer(invoice_line["unit_price_minor"]) == integer(typed["net_unit_price_minor"]) == 4500 and integer(invoice_line["line_total_minor"]) == 67500)
    require(integer(invoice["tax_minor"]) == integer(invoice_line["tax_minor"]) == integer(typed["tax_minor"]) == 0)
    require(typed["inventory_lot_id"] is None and typed["serial_tracked"] is False and typed["base_uom_id"] == scope["uom_id"])
    effects, entries = index(tables["finance_posting_effects"], 5), index(tables["finance_entries"], 5)
    lines, accounts = index(tables["finance_entry_lines"], 10), index(tables["finance_accounts"])
    codes = index(tables["finance_accounts"], key="account_code")
    for code, classification in (("INVENTORY", "Asset"), ("CLEARING", "Liability"), ("COGS", "Expense"), ("AR", "Asset"), ("REVENUE", "Income"), ("CASH", "Asset"), ("REFUND", "Liability")):
        require(codes[code]["account_type"] == classification and codes[code]["workspace_id"] == scope["workspace_id"])
    require(not tables["finance_entry_line_dimensions"] and not tables["customer_return_plans"] and not tables["inventory_valuation_reversal_effects"])
    vectors: dict[str, tuple[str, str, int]] = {}
    snapshots: dict[str, dict[str, Any]] = {}
    balances: Counter[str] = Counter()
    for effect in effects.values():
        _scope(effect, scope)
        _policy(effect, policy)
        header = entries[effect["entry_id"]]
        _policy(header, policy)
        require(header["tenant_id"] == scope["tenant_id"] and header["workspace_id"] == scope["workspace_id"])
        require(header["status"] == "Validated" and effect["purpose"] == "operational_posting" and effect["reverses_effect_id"] is None and header["reverses_posting_id"] is None)
        require(len({text(header["preparer_actor_id"]), text(header["validator_actor_id"]), text(effect["posted_actor_id"])}) == 3)
        snapshot = effect["snapshot_json"]
        require(type(snapshot) is dict)
        require(set(snapshot) == {"entry", "lines", "schema_version"} and snapshot["schema_version"] == "finance-entry-review-v1")
        require(effect["validation_contract_version"] == header["validation_contract_version"] == snapshot["schema_version"])
        require(effect["validation_digest"] == header["validation_digest"] == digest(snapshot))
        for key, value in snapshot["entry"].items():
            require(same(value, (effect if key in {"organization_id", "legal_entity_id"} else header)[key]))
        actual = sorted((row for row in lines.values() if row["entry_id"] == header["id"]), key=lambda row: integer(row["line_number"]))
        require(len(actual) == len(snapshot["lines"]) == 2)
        require([integer(row["line_number"]) for row in actual] == [1, 2])
        for frozen, line in zip(snapshot["lines"], actual, strict=True):
            require(frozen["dimensions"] == {} and line["tenant_id"] == scope["tenant_id"] and line["currency_code"] == "USD")
            require(all(same(frozen[key], line[key]) for key in ("account_id", "line_number", "description", "debit_minor", "credit_minor")))
        debit, credit = actual
        amount = integer(debit["debit_minor"], positive=True)
        require(integer(credit["credit_minor"]) == amount and integer(debit["credit_minor"]) == integer(credit["debit_minor"]) == 0)
        require(integer(header["total_debit_minor"]) == integer(header["total_credit_minor"]) == amount)
        debit_code, credit_code = accounts[debit["account_id"]]["account_code"], accounts[credit["account_id"]]["account_code"]
        balances[debit_code] += amount
        balances[credit_code] -= amount
        vectors[effect["id"]] = debit_code, credit_code, amount
        snapshots[effect["id"]] = snapshot
    require(len({effect["entry_id"] for effect in effects.values()}) == len(entries))
    require(Counter(vectors.values()) == Counter([("INVENTORY", "CLEARING", 12000), ("INVENTORY", "CLEARING", 20000), ("COGS", "INVENTORY", 22000), ("AR", "REVENUE", 67500), ("CASH", "AR", 10000)]))
    require({key: value for key, value in balances.items() if value} == {"INVENTORY": 10000, "CLEARING": -32000, "COGS": 22000, "AR": 57500, "CASH": 10000, "REVENUE": -67500})
    cogs_effect = effects[stock["cogs_effect_id"]]
    revenue_plan = index(tables["operational_finance_plans"], 1)[stock["invoice_plan_id"]]
    revenue_link = index(tables["operational_finance_links"], 1, "plan_id")[revenue_plan["id"]]
    revenue_effect = effects[revenue_link["posting_effect_id"]]
    require(revenue_plan["source_kind"] == "ARInvoice" and revenue_plan["source_id"] == revenue_link["source_effect_id"] == invoice["id"])
    require(revenue_plan["entry_id"] == revenue_effect["entry_id"] and integer(revenue_plan["amount_minor"]) == 67500)
    require(revenue_plan["validation_digest"] == revenue_effect["validation_digest"] and same(revenue_plan["payload"]["snapshot"], snapshots[revenue_effect["id"]]))
    require(revenue_link["posted_actor_id"] == revenue_effect["posted_actor_id"])
    for effect, reference, amount in ((cogs_effect, stock["id"], 22000), (revenue_effect, revenue_plan["id"], 67500)):
        require(effect["source_kind"] == "Manual" and effect["source_id"] == effect["entry_id"] and snapshots[effect["id"]]["entry"]["source_type"] == "Manual")
        require(snapshots[effect["id"]]["entry"]["external_reference"] == reference and vectors[effect["id"]][2] == amount)
    require(cogs_effect["entry_id"] == stock["cogs_entry_id"] and same(decode(typed["original_cogs_snapshot_json"]), snapshots[cogs_effect["id"]]))
    require(same(decode(typed["original_revenue_snapshot_json"]), snapshots[revenue_effect["id"]]))
    source_original = decode(observed["original_source_json"])
    require(set(source_original) == {"stock", "invoice", "invoice_status", "invoice_version", "allocated_minor", "cogs", "revenue", "consumptions"})
    immutable_invoice = {key: value for key, value in invoice.items() if key not in
                         {"cancel_reason", "cancelled_at", "cancelled_by", "customer_return_owner_id", "row_version", "status", "updated_at"}}
    require(same(source_original["stock"], stock) and same(source_original["invoice"], immutable_invoice) and same(source_original["cogs"], cogs_effect) and same(source_original["revenue"], revenue_effect))
    require(source_original["invoice_status"] == invoice["status"] and same(source_original["invoice_version"], invoice["row_version"]))
    require(digest(stock["source"]) == stock["source_digest"] == stock["issue_plan"]["source_digest"])
    claim = next(iter(index(tables["stock_sales_issue_claims"], 1, "order_id").values()))
    require(claim["order_id"] == stock["id"] and claim["state"] == "Consumed" and claim["entry_id"] == stock["cogs_entry_id"])
    require(claim["plan_digest"] == digest(stock["issue_plan"]) and same(claim["payload"], stock["issue_plan"]))
    require(all(claim[key] == scope[key] for key in ("workspace_id", "legal_entity_id", "item_id")))
    valuations = index(tables["inventory_valuation_documents"], 3)
    valuation_lines = index(tables["inventory_valuation_lines"], 3)
    movements = index(tables["inventory_movements"], 3)
    movement_lines = index(tables["inventory_movement_lines"], 3)
    outbound = valuations[stock["valuation_id"]]
    _scope(outbound, scope)
    _policy(outbound, policy)
    require(outbound["finance_entry_id"] == stock["cogs_entry_id"] and integer(outbound["total_value_minor"]) == 22000 and outbound["status"] == "Approved")
    detail = next(row for row in valuation_lines.values() if row["valuation_document_id"] == outbound["id"])
    require(detail["flow_direction"] == "Outbound" and integer(detail["quantity_scaled"]) == 15 and integer(detail["value_minor"]) == 22000)
    move = movements[stock["movement_id"]]
    _scope(move, scope)
    require(outbound["movement_id"] == move["id"] and move["status"] == "Posted" and move["movement_type"] == "Delivery" and move["source_reference"] == stock["id"])
    movement_detail = movement_lines[detail["movement_line_id"]]
    require(movement_detail["movement_id"] == move["id"] and movement_detail["from_location_id"] == scope["location_id"] and movement_detail["to_location_id"] is None)
    require(detail["inventory_account_id"] == codes["INVENTORY"]["id"] and detail["offset_account_id"] == codes["COGS"]["id"])
    for row in (detail, movement_detail):
        require(row["item_id"] == scope["item_id"] and row["uom_id"] == scope["uom_id"] and row["inventory_lot_id"] is None and integer(row["quantity_precision"]) == 0 and integer(row["quantity_scaled"]) == 15)
    layers, consumed = index(tables["inventory_cost_layers"], 2), index(tables["inventory_layer_consumptions"], 2)
    require({row["id"] for row in source_original["consumptions"]} == set(consumed) and all(same(row, consumed[row["id"]]) for row in source_original["consumptions"]))
    by_layer = index(tables["inventory_layer_consumptions"], 2, "cost_layer_id")
    allocations, typed_consumed = stock["issue_plan"]["allocations"], typed["consumptions"]
    require(len(allocations) == len(typed_consumed) == 2 and integer(stock["issue_plan"]["total_cost_minor"]) == 22000)
    receipt_plans = index(tables["inventory_receipt_plans"], 2, "cost_layer_id")
    receipt_links = index(tables["inventory_receipt_links"], 2, "plan_id")
    origins, portions = [], []
    for number, (allocation, original, expected) in enumerate(zip(allocations, typed_consumed, ((10, 12000, 0, 0, 10, 12000), (5, 10000, 5, 10000, 2, 4000)), strict=True), 1):
        layer = layers[allocation["cost_layer_id"]]
        native = by_layer[layer["id"]]
        used_qty, used_value, remaining_qty, remaining_value, return_qty, return_value = expected
        require(integer(native["quantity_scaled"]) == integer(allocation["quantity_scaled"]) == used_qty and integer(native["value_minor"]) == integer(allocation["value_minor"]) == used_value)
        require(native["valuation_line_id"] == detail["id"] and native["workspace_id"] == scope["workspace_id"])
        require(integer(layer["original_quantity_scaled"]) == 10 and integer(layer["remaining_quantity_scaled"]) == remaining_qty and integer(layer["remaining_value_minor"]) == remaining_value)
        require(integer(layer["original_value_minor"]) == used_value + remaining_value and layer["inventory_lot_id"] is None)
        require(integer(layer["quantity_precision"]) == integer(typed["quantity_precision"]) == 0)
        require(all(layer[key] == scope[key] for key in ("tenant_id", "workspace_id", "legal_entity_id", "item_id", "uom_id")) and layer["currency_code"] == "USD")
        expected_consumption = {"position": number, "consumption_id": native["id"], "valuation_line_id": detail["id"], "cost_layer_id": layer["id"], "scope": scope, "quantity_precision": 0, "quantity_scaled": used_qty, "value_minor": used_value, "currency_code": "USD"}
        require(same(original, expected_consumption))
        inbound = valuation_lines[layer["source_valuation_line_id"]]
        document = valuations[inbound["valuation_document_id"]]
        _scope(document, scope)
        _policy(document, policy)
        require(document["status"] == "Approved" and inbound["flow_direction"] == "Inbound" and integer(inbound["quantity_scaled"]) == 10)
        require(inbound["item_id"] == scope["item_id"] and inbound["uom_id"] == scope["uom_id"] and inbound["inventory_lot_id"] is None and integer(inbound["quantity_precision"]) == 0)
        require(inbound["inventory_account_id"] == codes["INVENTORY"]["id"] and inbound["offset_account_id"] == codes["CLEARING"]["id"])
        plan = receipt_plans[layer["id"]]
        link = receipt_links[plan["id"]]
        effect = effects[plan["posting_effect_id"]]
        _scope(plan, scope)
        _scope(link, scope)
        _policy(plan, policy)
        require(plan["valuation_document_id"] == document["id"] and plan["valuation_line_id"] == inbound["id"] and plan["finance_entry_id"] == document["finance_entry_id"] == effect["entry_id"])
        require(link["posting_effect_id"] == effect["id"] and link["cost_layer_id"] == layer["id"] and link["posted_actor_id"] == effect["posted_actor_id"])
        require(effect["source_kind"] == "InventoryReceipt" and effect["source_id"] == plan["id"] and snapshots[effect["id"]]["entry"]["external_reference"] == plan["id"] and snapshots[effect["id"]]["entry"]["source_type"] == "Generated")
        require(integer(plan["total_value_minor"]) == integer(document["total_value_minor"]) == integer(inbound["value_minor"]) == integer(layer["original_value_minor"]))
        require(plan["finance_validation_digest"] == effect["validation_digest"] and same(plan["plan_json"]["finance_snapshot"], snapshots[effect["id"]]))
        inbound_move = movements[document["movement_id"]]
        _scope(inbound_move, scope)
        require(plan["movement_id"] == link["movement_id"] == inbound_move["id"] and inbound_move["status"] == "Posted" and inbound_move["movement_type"] == "Receipt" and inbound_move["source_reference"] == plan["id"])
        inbound_movement_line = movement_lines[inbound["movement_line_id"]]
        require(plan["movement_line_id"] == link["movement_line_id"] == inbound_movement_line["id"] and inbound_movement_line["movement_id"] == inbound_move["id"])
        require(inbound_movement_line["from_location_id"] is None and inbound_movement_line["to_location_id"] == scope["location_id"] and inbound_movement_line["item_id"] == scope["item_id"] and inbound_movement_line["uom_id"] == scope["uom_id"] and inbound_movement_line["inventory_lot_id"] is None and integer(inbound_movement_line["quantity_scaled"]) == 10 and integer(inbound_movement_line["quantity_precision"]) == 0)
        origins.append(document["valuation_date"])
        require(Fraction(used_value, used_qty) * return_qty == return_value)
        portions.append({"position": number, "original_consumption_id": native["id"], "original_valuation_line_id": detail["id"], "cost_layer_id": layer["id"], "offset_quantity_scaled": 0, "quantity_scaled": return_qty, "value_minor": return_value})
    require(origins[0] < origins[1])
    receipt = next(iter(index(tables["ar_receipts"], 1).values()))
    allocation = next(iter(index(tables["ar_receipt_allocations"], 1).values()))
    collection = next(iter(index(tables["commercial_collection_plans"], 1).values()))
    collection_link = index(tables["commercial_collection_links"], 1, "plan_id")[collection["id"]]
    cash_effect = effects[collection_link["posting_effect_id"]]
    _scope(receipt, scope)
    _scope(collection, scope)
    _policy(receipt, policy)
    require(receipt["status"] == "Posted" and receipt["customer_id"] == invoice["customer_id"] and receipt["id"] == allocation["receipt_id"] == collection_link["receipt_id"])
    require(allocation["invoice_id"] == collection["source_id"] == invoice["id"] and collection["phase"] == 2)
    require(integer(receipt["amount_minor"]) == integer(allocation["amount_minor"]) == integer(collection["amount_minor"]) == integer(typed["collected_minor"]) == integer(source_original["allocated_minor"]) == 10000)
    require(collection["entry_id"] == cash_effect["entry_id"] and collection_link["posted_actor_id"] == cash_effect["posted_actor_id"])
    require(cash_effect["source_kind"] == "Manual" and cash_effect["source_id"] == cash_effect["entry_id"] and snapshots[cash_effect["id"]]["entry"]["external_reference"] == collection["id"])
    require(collection["payload"]["validation_digest"] == cash_effect["validation_digest"] and same(collection["payload"]["snapshot"], snapshots[cash_effect["id"]]))
    require(same(decode(observed["collection_evidence_json"]), [{"allocation": allocation, "receipt": receipt, "owner_kind": "Commercial", "owner_id": collection["id"], "posting_effect": cash_effect}]))
    source_payload = {"contract": DOMAIN_VERSION, "scope": scope, "source_order_id": stock["id"], "invoice_id": invoice["id"], "valuation_document_id": stock["valuation_id"], "quantity_precision": 0, "original_revenue_plan_id": revenue_plan["id"], "quantity_scaled": 15, "gross_minor": 67500, "net_unit_price_minor": 4500, "collected_minor": 10000, "currency": "USD", "policy": {key: policy[key] for key in POLICY_KEYS if key != "currency_code"}, "functional_currency": "USD", "base_uom_id": scope["uom_id"], "tax_minor": 0, "inventory_lot_id": None, "serial_tracked": False, "consumptions": typed_consumed, "original_cogs": [cogs_effect["id"], cogs_effect["validation_digest"]], "original_revenue": [revenue_effect["id"], revenue_effect["validation_digest"]]}
    require(typed["source_fingerprint"] == digest(source_payload))
    requested_credit = Fraction(67500, 15) * 12
    cost = sum(Fraction(row["value_minor"]) for row in portions)
    require(requested_credit.denominator == cost.denominator == 1 and requested_credit == 54000 and cost == 16000)
    plan_payload = {"schema_version": DOMAIN_VERSION, "source_fingerprint": typed["source_fingerprint"], "history_fingerprint": digest({"contract": DOMAIN_VERSION, "source": typed["source_fingerprint"]}), "expected_version": 0, "quantity_before_scaled": 0, "quantity_scaled": 12, "returned_quantity_scaled": 12, "credit_minor": 54000, "cogs_restored_minor": 16000, "receivable_released_minor": 54000, "refund_entitlement_delta_minor": 0, "outstanding_after_minor": 3500, "portions": portions}
    if proposal is not None:
        verify_proposal(proposal, plan_payload, scope, policy, codes, snapshots, cogs_effect, revenue_effect)
    return {"original_effects": 5, "original_entry_lines": 10, "original_gl_debit_minor": sum(vector[2] for vector in vectors.values()), "original_gl_credit_minor": sum(vector[2] for vector in vectors.values()), "original_quantity_scaled": 15, "original_cost_minor": 22000, "original_gross_minor": 67500, "original_collected_minor": 10000, "original_inventory_remaining_quantity_scaled": 5, "original_inventory_remaining_value_minor": 10000, "requested_return_quantity_scaled": 12, "credit_minor": 54000, "cogs_restored_minor": 16000, "receivable_released_minor": 54000, "refund_entitlement_delta_minor": 0, "outstanding_after_minor": 3500, "source_content_fingerprint": digest(source_payload), "requested_plan_content_fingerprint": digest(plan_payload), "actual_proposal_serialization_retained": proposal is not None, "proposal_posted": False, "native_authorization_or_approval_proven": False}


def verify_two_layer(envelope: dict[str, Any], observed: dict[str, Any], proposal: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        return _verify_two_layer(envelope, observed, proposal)
    except (KeyError, StopIteration, ValueError, TypeError, AttributeError, IndexError) as exc:
        raise OracleRefusal("Independent native source contract refused.") from exc


def verify_proposal(proposal: dict[str, Any], plan: dict[str, Any], scope: dict[str, Any], policy: dict[str, Any], codes: dict[str, dict[str, Any]], snapshots: dict[str, dict[str, Any]], cogs: dict[str, Any], revenue: dict[str, Any]) -> None:
    require(set(proposal) == {"schema_version", "case", "plan_payload", "account_roles_payload", "posting_intent_payload", "posting_contract_payload"})
    require(proposal["schema_version"] == "native-unposted-partial-return-proposal-original-v1" and proposal["case"] == TWO_LAYER and same(proposal["plan_payload"], plan))
    roles, intent, contract = proposal["account_roles_payload"], proposal["posting_intent_payload"], proposal["posting_contract_payload"]
    require(set(intent) == {"posting_date", "period_id", "reason"} and all(type(value) is str and 0 < len(value) <= 1000 for value in intent.values()))
    require(re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", intent["posting_date"]) is not None)
    role_accounts = dict(zip(("receivable_account_id", "revenue_account_id", "inventory_account_id", "cogs_account_id", "refund_liability_account_id"), (codes[code]["id"] for code in ("AR", "REVENUE", "INVENTORY", "COGS", "REFUND")), strict=True))
    require(codes["REFUND"]["account_type"] == "Liability")
    require(same(roles, {"scope": scope, "source_fingerprint": plan["source_fingerprint"], "currency_policy": policy, "accounts": role_accounts, "refund_liability_account_type": "Liability"}))
    require(set(contract) == {"schema_version", "postable", "templates"} and contract["schema_version"] == "customer-partial-return-posting-contract-v1" and contract["postable"] is False)
    common = {"schema_version": "customer-partial-return-correction-template-v1", "source_fingerprint": plan["source_fingerprint"], "history_fingerprint": plan["history_fingerprint"], "plan_fingerprint": digest(plan), "account_roles_fingerprint": digest(roles), "scope": scope, "currency_policy": policy, "posting_intent": intent, "portions": plan["portions"], "reverses_posting_id": None, "requires_native_participant": True, "requires_current_authorization": True, "requires_three_person_approval": True, "postable": False}
    expected = []
    for purpose, effect, debit_code, credit_code, amount in (("RevenueCredit", revenue, "REVENUE", "AR", 54000), ("CostRestoration", cogs, "INVENTORY", "COGS", 16000)):
        snapshot = snapshots[effect["id"]]
        line_by_account = {line["account_id"]: line for line in snapshot["lines"]}
        correction_lines = [{"line_number": number, "account_id": codes[code]["id"], "description": intent["reason"], "debit_minor": amount if number == 1 else 0, "credit_minor": amount if number == 2 else 0, "dimensions": line_by_account[codes[code]["id"]]["dimensions"]} for number, code in enumerate((debit_code, credit_code), 1)]
        expected.append({**common, "purpose": purpose, "original_posting_effect_id": effect["id"], "original_entry_id": effect["entry_id"], "original_validation_digest": effect["validation_digest"], "journal_id": snapshot["entry"]["journal_id"], "lines": correction_lines})
    require(same(contract["templates"], expected))


def _owned(path: Path) -> None:
    require(all(not ancestor.is_symlink() for ancestor in (path, *path.parents)))


def _read(path: Path) -> bytes:
    _owned(path)
    require(path.is_file())
    with path.open("rb") as stream:
        raw = stream.read(MAX_BYTES + 1)
    require(len(raw) <= MAX_BYTES)
    _owned(path)
    return raw


def verify_directory(root: Path) -> dict[str, Any]:
    try:
        _owned(root)
        require(root.is_dir())
        paths = sorted(root.iterdir(), key=lambda path: path.name)
        require(len(paths) <= 60)
        originals: list[Path] = []
        maps: list[Path] = []
        for pattern, prefix, target in ((RAW_NAME, "native-financial-rows-original-", originals), (MAP_NAME, "native-source-original-", maps)):
            selected = [path for path in paths if path.name.startswith(prefix)]
            require(all(pattern.fullmatch(path.name) is not None for path in selected))
            ordered = sorted(selected, key=lambda path: int(cast(re.Match[str], pattern.fullmatch(path.name)).group(1)))
            require([int(cast(re.Match[str], pattern.fullmatch(path.name)).group(1)) for path in ordered] == list(range(1, len(ordered) + 1)))
            target.extend(ordered)
        require(len(originals) in {2, 12} and len(maps) == (1 if len(originals) == 2 else 5))
        proposals = [path for path in paths if path.name.startswith("native-unposted-partial-return-proposal-original-")]
        require(not proposals or len(proposals) == 1 and proposals[0].name == PROPOSAL_NAME)
        inputs = originals + maps + proposals
        before = []
        data = {}
        total_bytes = 0
        for path in inputs:
            raw = _read(path)
            total_bytes += len(raw)
            require(total_bytes <= 32 * 1024 * 1024)
            before.append({"name": path.name, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})
            data[path.name] = decode(raw)
        expected_cases = CASES if len(originals) == 12 else (TWO_LAYER,)
        first = None
        for offset, case in enumerate(expected_cases):
            left, right = (data[path.name] for path in originals[2 * offset:2 * offset + 2])
            raw_tables(left)
            raw_tables(right)
            require(left["case"] == right["case"] == case and left == right)
            # Equality of retained exact row strings is stronger than decoded numeric equality.
            require(left["tables"] == right["tables"])
            if case == TWO_LAYER:
                first = left
        mapped = [data[path.name] for path in maps]
        require([row["case"] for row in mapped] == list(MAPPED_FULL_CASES if len(originals) == 12 else (TWO_LAYER,)) and first is not None)
        if len(originals) == 12:
            require(same(mapped[1], mapped[2]))
        result = verify_two_layer(cast(dict[str, Any], first), mapped[0], data[PROPOSAL_NAME] if proposals else None)
        require(sorted(path.name for path in root.iterdir()) == [path.name for path in paths])
        after = []
        final_total_bytes = 0
        for path in inputs:
            raw = _read(path)
            final_total_bytes += len(raw)
            require(final_total_bytes <= 32 * 1024 * 1024)
            after.append({"name": path.name, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})
        require(before == after)
        return {"schema_version": "independent-native-partial-source-row-proof-v1", "status": "passed", "application_imports": False, "database_browser_or_api_calls": False, "raw_financial_originals_published": False, "case_count_with_exact_row_custody": len(expected_cases), "case_count_with_independent_financial_oracle": 1, "tables_per_capture": len(TABLES), "original_sql_row_text_before_after_unchanged": True, "input_identities": before, "input_bytes_unchanged": True, "input_fingerprint": digest(before), "result": result}
    except (OSError, KeyError, StopIteration, ValueError, TypeError, AttributeError, RecursionError) as exc:
        raise OracleRefusal("Independent native source contract refused.") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify private native source originals without application imports.")
    parser.add_argument("root", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        _owned(args.output)
        require(not args.output.resolve().is_relative_to(args.root.resolve()))
        report = verify_directory(args.root)
        report["oracle_source_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        with args.output.open("xb") as stream:
            stream.write(canonical(report) + b"\n")
        print("Independent native source originals verified.")
        return 0
    except (OracleRefusal, OSError, ValueError):
        print("Independent native source oracle refused.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
