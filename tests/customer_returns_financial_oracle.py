"""Standalone integer oracle for PRIVATE original CR1 rows; no application imports.

Run this file directly with Python -I or -I -O. Assertions are deliberately not
used for verification. This proves the declared synthetic zero-tax, one-currency
fixture, not country compliance or general partial-merchandise return support.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from fractions import Fraction
from pathlib import Path
from typing import Any, cast

TABLES = (
    "finance_posting_effects",
    "finance_entries",
    "finance_entry_lines",
    "finance_accounts",
    "stock_sales_orders",
    "customer_return_plans",
    "ar_invoices",
    "ar_invoice_lines",
    "ar_receipts",
    "ar_receipt_allocations",
    "inventory_cost_layers",
    "inventory_layer_consumptions",
    "inventory_valuation_reversal_effects",
)
MAX_CAPTURES = 13
MAX_FILES = MAX_CAPTURES * len(TABLES)
MAX_ORIGINAL_BYTES = 4 * 1024 * 1024
NAME = re.compile(r"native-financial-snapshot-oracle-([1-9][0-9]{0,2})\.json")


class OracleRefusal(ValueError):
    """A constant refusal never echoes a private original value or path."""


def require(value: bool) -> None:
    if not value:
        raise OracleRefusal("Independent CR1 original-row contract refused.")


def _invalid(_: str) -> Any:
    raise OracleRefusal("Independent CR1 original-row numeric contract refused.")


def _exact_fraction(token: str) -> Fraction:
    require(len(token) <= 80 and re.fullmatch(r"-?[0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]{1,2})?", token) is not None)
    value = Fraction(token)
    require(value.numerator.bit_length() <= 256 and value.denominator.bit_length() <= 256)
    return value


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        require(key not in result)
        result[key] = value
    return result


def decode(raw: bytes | str) -> Any:
    return json.loads(raw, object_pairs_hook=_pairs, parse_float=_exact_fraction, parse_constant=_invalid)


def integer(value: Any, *, positive: bool = False) -> int:
    require(type(value) is int and 0 <= value <= 9_000_000_000_000_000_000)
    require(not positive or value > 0)
    return int(value)


def text(value: Any) -> str:
    require(type(value) is str and 0 < len(value) <= 200)
    return str(value)


def _walk(value: Any, *, depth: int = 0, budget: list[int] | None = None) -> None:
    budget = [100_000] if budget is None else budget
    budget[0] -= 1
    require(budget[0] >= 0 and depth <= 40)
    if type(value) is dict:
        require(len(value) <= 1000)
        for key, child in value.items():
            require(type(key) is str and len(key) <= 256)
            _walk(child, depth=depth + 1, budget=budget)
    elif type(value) is list:
        require(len(value) <= 1000)
        for child in value:
            _walk(child, depth=depth + 1, budget=budget)
    else:
        require(value is None or type(value) in {str, int, bool, Fraction})
        require(type(value) is not str or len(value) <= MAX_ORIGINAL_BYTES)


def _same(a: Any, b: Any) -> bool:
    if type(a) is not type(b):
        return False
    if type(a) is dict:
        return set(a) == set(b) and all(_same(a[key], b[key]) for key in a)
    if type(a) is list:
        return len(a) == len(b) and all(_same(left, right) for left, right in zip(a, b, strict=True))
    return bool(a == b)


def _object(value: Any) -> dict[str, Any]:
    require(type(value) is dict)
    return cast(dict[str, Any], value)


def _index(rows: list[dict[str, Any]], count: int) -> dict[str, dict[str, Any]]:
    require(len(rows) == count)
    result = {text(row.get("id")): row for row in rows}
    require(len(result) == count)
    return result


def verify_capture(tables: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """Derive every journal vector from actual rows, independently of the ERP."""
    require(set(tables) == set(TABLES))
    for rows in tables.values():
        require(type(rows) is list and len(rows) <= 64)
        for row in rows:
            require(type(row) is dict)
            _walk(row)
    tenants = {text(row.get("tenant_id")) for rows in tables.values() for row in rows}
    require(len(tenants) == 1)
    effects = _index(tables["finance_posting_effects"], 9)
    entries = _index(tables["finance_entries"], 9)
    lines = _index(tables["finance_entry_lines"], 18)
    accounts = _index(tables["finance_accounts"], 7)
    codes = {identifier: text(row.get("account_code")) for identifier, row in accounts.items()}
    require(set(codes.values()) == {"AR", "CASH", "REVENUE", "COGS", "REFUND", "INVENTORY", "CLEARING"})
    require({text(row.get("entry_id")) for row in effects.values()} == set(entries))
    require({text(row.get("entry_id")) for row in lines.values()} == set(entries))
    require({text(row.get("account_id")) for row in lines.values()} == set(accounts))
    currencies = {
        text(row.get("currency_code"))
        for rows in (list(effects.values()), list(entries.values()), list(lines.values()))
        for row in rows
    }
    require(len(currencies) == 1)
    quantities, cost, gross, collected, refunds = 10, 12000, 45000, 10000, (3000, 7000)
    require(Fraction(cost, quantities) * quantities == cost and sum(refunds) == collected)
    expected = Counter(
        (debit, credit, amount)
        for debit, credit, amount in (
            ("INVENTORY", "CLEARING", cost),
            ("COGS", "INVENTORY", cost),
            ("AR", "REVENUE", gross),
            ("CASH", "AR", collected),
            ("REVENUE", "AR", gross),
            ("INVENTORY", "COGS", cost),
            ("AR", "REFUND", collected),
            *(("REFUND", "CASH", amount) for amount in refunds),
        )
    )
    observed: Counter[tuple[str, str, int]] = Counter()
    vectors: dict[str, tuple[str, str, int]] = {}
    balances = dict.fromkeys(codes.values(), 0)
    total_debit = total_credit = 0
    for identifier, header in entries.items():
        require(header.get("status") == "Validated")
        children = [row for row in lines.values() if row["entry_id"] == identifier]
        require(len(children) == 2 and {integer(row.get("line_number"), positive=True) for row in children} == {1, 2})
        debit_rows: list[tuple[str, int]] = []
        credit_rows: list[tuple[str, int]] = []
        for row in children:
            debit, credit = integer(row.get("debit_minor")), integer(row.get("credit_minor"))
            require((debit == 0) != (credit == 0))
            account = codes[text(row.get("account_id"))]
            balances[account] += debit - credit
            total_debit += debit
            total_credit += credit
            (debit_rows if debit else credit_rows).append((account, debit or credit))
        require(len(debit_rows) == len(credit_rows) == 1 and debit_rows[0][1] == credit_rows[0][1])
        amount = debit_rows[0][1]
        require(integer(header.get("total_debit_minor")) == integer(header.get("total_credit_minor")) == amount)
        observed[(debit_rows[0][0], credit_rows[0][0], amount)] += 1
        vectors[identifier] = (debit_rows[0][0], credit_rows[0][0], amount)
    require(
        observed == expected and total_debit == total_credit == sum(key[2] * count for key, count in expected.items())
    )
    by_entry = {row["entry_id"]: row for row in effects.values()}
    require(
        Counter(row.get("source_kind") for row in effects.values())
        == {"Manual": 6, "Reversal": 2, "InventoryReceipt": 1}
    )
    for effect in effects.values():
        header = entries[text(effect.get("entry_id"))]
        require(effect.get("purpose") == "operational_posting" and "amount_minor" not in effect)
        kind, source, original = (
            effect.get("source_kind"),
            text(effect.get("source_id")),
            effect.get("reverses_effect_id"),
        )
        if kind == "Manual":
            require(
                source == header["id"]
                and original is None
                and header.get("reverses_posting_id") is None
                and header.get("source_type") == "Manual"
            )
        elif kind == "InventoryReceipt":
            require(
                source == header.get("external_reference")
                and original is None
                and header.get("source_type") == "Generated"
            )
        else:
            require(source == original == header.get("reverses_posting_id") and source in effects)
            other = effects[source]
            require(other.get("reverses_effect_id") is None and header.get("source_type") == "Generated")
            original_debit_account, original_credit_account, original_amount = vectors[other["entry_id"]]
            require(vectors[header["id"]] == (original_credit_account, original_debit_account, original_amount))
        require(effect.get("validation_contract_version") == "finance-entry-review-v1")
        snapshot = _object(effect.get("snapshot_json"))
        require(
            set(snapshot) == {"schema_version", "entry", "lines"}
            and snapshot["schema_version"] == "finance-entry-review-v1"
        )
        frozen_header = _object(snapshot["entry"])
        require(
            {"id", "source_type", "external_reference", "currency_code", "currency_precision", "reverses_posting_id"}
            <= set(frozen_header)
        )
        for key, value in frozen_header.items():
            reference = effect if key in {"organization_id", "legal_entity_id"} else header
            require(key in reference and _same(value, reference[key]))
        frozen_lines = snapshot["lines"]
        require(type(frozen_lines) is list and len(frozen_lines) == 2)
        actual_lines = sorted(
            (row for row in lines.values() if row["entry_id"] == header["id"]), key=lambda row: row["line_number"]
        )
        for frozen, actual in zip(frozen_lines, actual_lines, strict=True):
            require(type(frozen) is dict and frozen.get("dimensions") == {})
            for key in ("line_number", "account_id", "description", "debit_minor", "credit_minor"):
                require(key in frozen and key in actual and _same(frozen[key], actual[key]))
        digest = hashlib.sha256(
            json.dumps(snapshot, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode(
                "utf8"
            )
        ).hexdigest()
        require(effect.get("validation_digest") == header.get("validation_digest") == digest)
    require(
        balances == {"AR": 0, "CASH": 0, "REVENUE": 0, "COGS": 0, "REFUND": 0, "INVENTORY": cost, "CLEARING": -cost}
    )
    stock = next(iter(_index(tables["stock_sales_orders"], 1).values()))
    invoice = next(iter(_index(tables["ar_invoices"], 1).values()))
    invoice_line = next(iter(_index(tables["ar_invoice_lines"], 1).values()))
    receipt = next(iter(_index(tables["ar_receipts"], 1).values()))
    allocation = next(iter(_index(tables["ar_receipt_allocations"], 1).values()))
    plans = _index(tables["customer_return_plans"], 4)
    require(
        text(stock.get("invoice_id")) == invoice["id"]
        and integer(stock.get("quantity_scaled"), positive=True) == quantities
    )
    require(stock.get("status") in {"Invoiced", "Paid"})
    require(integer(stock.get("total_minor"), positive=True) == gross and integer(stock.get("quantity_precision")) == 0)
    require(
        invoice.get("status") == "Cancelled"
        and integer(invoice.get("total_minor")) == gross
        and integer(invoice.get("tax_minor")) == 0
    )
    quantity_text = text(invoice_line.get("quantity_text"))
    require(re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", quantity_text) is not None)
    numeric_quantity = invoice_line.get("quantity")
    require(type(numeric_quantity) in {int, Fraction} and invoice_line.get("invoice_id") == invoice["id"])
    require(numeric_quantity == Fraction(quantity_text) == quantities)
    require(
        integer(invoice_line.get("unit_price_minor")) * quantities
        == integer(invoice_line.get("line_total_minor"))
        == gross
    )
    require(integer(invoice_line.get("tax_minor")) == 0)
    require(receipt.get("status") == "Posted" and integer(receipt.get("amount_minor")) == collected)
    require(allocation.get("invoice_id") == invoice["id"] and allocation.get("receipt_id") == receipt["id"])
    require(integer(allocation.get("amount_minor")) == collected)
    posted = [row for row in plans.values() if row.get("operation") == "Return" and integer(row.get("phase")) == 2]
    cancelled = [row for row in plans.values() if row.get("operation") == "Return" and integer(row.get("phase")) == 3]
    cash_refunds = [
        row for row in plans.values() if row.get("operation") == "Refund" and integer(row.get("phase")) == 2
    ]
    require(len(posted) == len(cancelled) == 1 and len(cash_refunds) == 2)
    parent = posted[0]
    require(invoice.get("customer_return_owner_id") == parent["id"])
    require(
        all(
            row.get("source_order_id") == stock["id"] and row.get("invoice_id") == invoice["id"]
            for row in plans.values()
        )
    )
    require(
        integer(parent.get("amount_minor")) == integer(cancelled[0].get("amount_minor")) == gross + cost + collected
    )
    payload = parent.get("payload")
    require(type(payload) is dict)
    payload = cast(dict[str, Any], payload)
    require(
        tuple(
            integer(payload.get(key))
            for key in ("credit_minor", "cogs_restored_minor", "refund_entitlement_minor", "receivable_released_minor")
        )
        == (gross, cost, collected, gross - collected)
    )
    require(sorted(integer(row.get("amount_minor")) for row in cash_refunds) == list(refunds))
    require(all(row.get("return_id") == parent["id"] for row in cash_refunds))
    original_cogs = effects.get(text(stock.get("cogs_effect_id")))
    require(original_cogs is not None)
    original_cogs = cast(dict[str, Any], original_cogs)
    require(vectors[original_cogs["entry_id"]] == ("COGS", "INVENTORY", cost))
    original_revenue = [
        effect for effect in effects.values() if vectors[effect["entry_id"]] == ("AR", "REVENUE", gross)
    ]
    require(len(original_revenue) == 1)
    owned_entries: set[str] = set()
    for plan in plans.values():
        parts = _object(plan.get("payload")).get("entries")
        require(type(parts) is list and len(parts) == (3 if plan["operation"] == "Return" else 1))
        parts = cast(list[Any], parts)
        for index, part in enumerate(parts):
            part = _object(part)
            identifier = text(part.get("entry_id"))
            if plan["phase"] == 3:
                require(identifier not in by_entry)
                continue
            require(identifier in by_entry and identifier not in owned_entries)
            owned_entries.add(identifier)
            header, effect = entries[identifier], by_entry[identifier]
            require(header.get("external_reference") == plan["id"])
            require(
                _same(part.get("snapshot"), effect["snapshot_json"])
                and part.get("validation_digest") == effect["validation_digest"]
            )
            if plan["operation"] == "Return" and index < 2:
                original_id = original_cogs["id"] if index == 0 else original_revenue[0]["id"]
                require(part.get("original_effect_id") == effect.get("reverses_effect_id") == original_id)
            else:
                require(part.get("original_effect_id") is None and effect["source_kind"] == "Manual")
                expected_vector = (
                    ("AR", "REFUND", collected)
                    if plan["operation"] == "Return"
                    else ("REFUND", "CASH", integer(plan["amount_minor"]))
                )
                require(vectors[identifier] == expected_vector)
    require(len(owned_entries) == 5)
    layer = next(iter(_index(tables["inventory_cost_layers"], 1).values()))
    consumption = next(iter(_index(tables["inventory_layer_consumptions"], 1).values()))
    restoration = next(iter(_index(tables["inventory_valuation_reversal_effects"], 1).values()))
    require(
        tuple(
            integer(layer.get(key))
            for key in (
                "original_quantity_scaled",
                "remaining_quantity_scaled",
                "original_value_minor",
                "remaining_value_minor",
            )
        )
        == (quantities, quantities, cost, cost)
    )
    require(consumption.get("cost_layer_id") == restoration.get("cost_layer_id") == layer["id"])
    require(
        restoration.get("original_consumption_id") == consumption["id"] and restoration.get("effect_type") == "Restore"
    )
    require(restoration.get("original_valuation_line_id") == consumption.get("valuation_line_id"))
    require(
        all(
            integer(row.get("quantity_scaled")) == quantities and integer(row.get("value_minor")) == cost
            for row in (consumption, restoration)
        )
    )
    require({text(row.get("currency_code")) for row in (stock, invoice, receipt, layer)} == currencies)
    require(len({integer(row.get("currency_precision")) for row in effects.values()}) == 1)
    return {
        "posted_effects": len(effects),
        "entry_lines": len(lines),
        "gl_debit_minor": total_debit,
        "gl_credit_minor": total_credit,
        "account_balances_minor": balances,
        "source_credit_minor": gross,
        "receivable_released_minor": gross - collected,
        "original_collected_minor": collected,
        "partial_refunds_minor": list(refunds),
        "refund_due_minor": collected - sum(refunds),
        "restored_quantity_scaled": quantities,
        "restored_value_minor": cost,
    }


def verify_directory(root: Path) -> dict[str, Any]:
    require(root.is_dir() and not root.is_symlink() and all(not parent.is_symlink() for parent in root.parents))
    files = list(root.iterdir())
    require(0 < len(files) <= MAX_FILES)
    ordered: dict[int, Path] = {}
    for path in files:
        match = NAME.fullmatch(path.name)
        require(match is not None and path.is_file() and not path.is_symlink())
        number = int(match[1]) if match is not None else 0
        require(number not in ordered and number <= MAX_FILES)
        ordered[number] = path
    require(set(ordered) == set(range(1, len(files) + 1)))
    captures: dict[int, dict[str, list[dict[str, Any]]]] = {}
    raw_tables: dict[int, dict[str, list[str]]] = {}
    identities = []
    for number, path in sorted(ordered.items()):
        with path.open("rb") as stream:
            raw = stream.read(MAX_ORIGINAL_BYTES + 1)
        require(len(raw) <= MAX_ORIGINAL_BYTES)
        envelope = decode(raw)
        require(type(envelope) is dict and set(envelope) == {"schema_version", "capture", "table", "rows"})
        require(envelope["schema_version"] == "native-customer-return-row-original-v1")
        capture = integer(envelope["capture"], positive=True)
        require(capture <= MAX_CAPTURES and capture == (number - 1) // len(TABLES) + 1)
        table = envelope["table"]
        require(type(table) is str and table == TABLES[(number - 1) % len(TABLES)])
        rows = envelope["rows"]
        require(type(rows) is list and len(rows) <= 64 and all(type(row) is str for row in rows))
        require(rows == sorted(rows) and len(rows) == len(set(rows)))
        parsed = [decode(row) for row in rows]
        require(all(type(row) is dict for row in parsed))
        captures.setdefault(capture, {})[table] = parsed
        raw_tables.setdefault(capture, {})[table] = rows
        digest = hashlib.sha256(raw).hexdigest()
        with path.open("rb") as stream:
            require(stream.read(MAX_ORIGINAL_BYTES + 1) == raw)
        identities.append({"number": number, "bytes": len(raw), "sha256": digest})
    require(set(captures) == set(range(1, len(captures) + 1)))
    results = [verify_capture(tables) for _, tables in sorted(captures.items())]
    require(all(tables == raw_tables[1] for tables in raw_tables.values()))
    return {
        "schema_version": "independent-native-customer-return-row-oracle-v1",
        "captures": len(captures),
        "tables_per_capture": len(TABLES),
        "input_identities": identities,
        "result": results[0],
        "complete_actual_rows_unchanged_across_captures": True,
        "private_financial_originals_published": False,
        "application_imports": False,
        "financial_arithmetic": "stdlib-integer-and-Fraction",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("originals", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = verify_directory(args.originals)
        require(not args.output.exists() and not args.output.is_symlink())
        with args.output.open("x", encoding="utf8") as stream:
            json.dump(result, stream, sort_keys=True, separators=(",", ":"))
        print(
            json.dumps(
                {"verified": True, "captures": result["captures"], "posted_effects": result["result"]["posted_effects"]}
            )
        )
        return 0
    except Exception:
        print("Independent CR1 original-row verification refused.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
