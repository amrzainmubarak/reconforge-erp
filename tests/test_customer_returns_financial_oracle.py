"""Adversarial pure tests for the independent original-row oracle, not a GL engine."""

from __future__ import annotations

import copy
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from tests import customer_returns_financial_oracle as oracle


def rows() -> dict[str, list[dict[str, Any]]]:
    tables: dict[str, list[dict[str, Any]]] = {table: [] for table in oracle.TABLES}
    codes = ("INVENTORY", "CLEARING", "COGS", "AR", "REVENUE", "CASH", "REFUND")
    tables["finance_accounts"] = [{"tenant_id": "synthetic-tenant", "id": code, "account_code": code} for code in codes]
    # Written out independently of the oracle's vector construction.
    entries = (
        ("INVENTORY", "CLEARING", 12000),
        ("COGS", "INVENTORY", 12000),
        ("AR", "REVENUE", 45000),
        ("CASH", "AR", 10000),
        ("REVENUE", "AR", 45000),
        ("INVENTORY", "COGS", 12000),
        ("AR", "REFUND", 10000),
        ("REFUND", "CASH", 3000),
        ("REFUND", "CASH", 7000),
    )
    for index, (debit, credit, amount) in enumerate(entries):
        identifier = f"entry-{index}"
        tables["finance_entries"].append(
            {
                "id": identifier,
                "status": "Validated",
                "currency_code": "USD",
                "total_debit_minor": amount,
                "total_credit_minor": amount,
            }
        )
        tables["finance_posting_effects"].append(
            {"id": f"effect-{index}", "entry_id": identifier, "currency_code": "USD", "currency_precision": 2}
        )
        for number, code in enumerate((debit, credit), 1):
            tables["finance_entry_lines"].append(
                {
                    "id": f"line-{index}-{number}",
                    "entry_id": identifier,
                    "line_number": number,
                    "account_id": code,
                    "description": "",
                    "debit_minor": amount if number == 1 else 0,
                    "credit_minor": amount if number == 2 else 0,
                    "currency_code": "USD",
                }
            )
    for index, header in enumerate(tables["finance_entries"]):
        original = f"effect-{2 if index == 4 else 1}" if index in {4, 5} else None
        reference = (
            "receipt-plan"
            if index == 0
            else "return"
            if index in {4, 5, 6}
            else f"refund-{3000 if index == 7 else 7000}"
            if index in {7, 8}
            else "fixture-source"
        )
        header.update(
            currency_precision=2,
            source_type="Generated" if index in {0, 4, 5} else "Manual",
            external_reference=reference,
            reverses_posting_id=original,
        )
        snapshot = {
            "schema_version": "finance-entry-review-v1",
            "entry": {
                key: header[key]
                for key in (
                    "id",
                    "currency_code",
                    "currency_precision",
                    "source_type",
                    "external_reference",
                    "reverses_posting_id",
                )
            },
            "lines": [
                {
                    **{
                        key: line[key]
                        for key in ("line_number", "account_id", "description", "debit_minor", "credit_minor")
                    },
                    "dimensions": {},
                }
                for line in tables["finance_entry_lines"]
                if line["entry_id"] == header["id"]
            ],
        }
        digest = hashlib.sha256(
            json.dumps(snapshot, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
        ).hexdigest()
        header["validation_digest"] = digest
        effect = tables["finance_posting_effects"][index]
        effect.update(
            source_kind="InventoryReceipt" if index == 0 else "Reversal" if original else "Manual",
            source_id=reference if index == 0 else original or header["id"],
            reverses_effect_id=original,
            purpose="operational_posting",
            validation_contract_version="finance-entry-review-v1",
            snapshot_json=snapshot,
            validation_digest=digest,
        )
    tables["stock_sales_orders"] = [
        {
            "id": "stock",
            "invoice_id": "invoice",
            "quantity_scaled": 10,
            "quantity_precision": 0,
            "total_minor": 45000,
            "status": "Invoiced",
            "currency_code": "USD",
            "cogs_effect_id": "effect-1",
        }
    ]
    tables["ar_invoices"] = [
        {
            "id": "invoice",
            "status": "Cancelled",
            "total_minor": 45000,
            "tax_minor": 0,
            "customer_return_owner_id": "return",
            "currency_code": "USD",
        }
    ]
    tables["ar_invoice_lines"] = [
        {
            "id": "invoice-line",
            "invoice_id": "invoice",
            "quantity": 10,
            "quantity_text": "10.000",
            "unit_price_minor": 4500,
            "line_total_minor": 45000,
            "tax_minor": 0,
        }
    ]
    tables["ar_receipts"] = [{"id": "receipt", "status": "Posted", "amount_minor": 10000, "currency_code": "USD"}]
    tables["ar_receipt_allocations"] = [
        {"id": "allocation", "invoice_id": "invoice", "receipt_id": "receipt", "amount_minor": 10000}
    ]
    parent = {
        "id": "return",
        "source_order_id": "stock",
        "invoice_id": "invoice",
        "operation": "Return",
        "phase": 2,
        "amount_minor": 67000,
        "payload": {
            "credit_minor": 45000,
            "cogs_restored_minor": 12000,
            "refund_entitlement_minor": 10000,
            "receivable_released_minor": 35000,
        },
    }
    cancelled = {**parent, "id": "cancelled", "phase": 3}
    tables["customer_return_plans"] = [
        parent,
        cancelled,
        *(
            {
                "id": f"refund-{amount}",
                "source_order_id": "stock",
                "invoice_id": "invoice",
                "operation": "Refund",
                "phase": 2,
                "return_id": "return",
                "amount_minor": amount,
            }
            for amount in (3000, 7000)
        ),
    ]
    tables["inventory_cost_layers"] = [
        {
            "id": "layer",
            "original_quantity_scaled": 10,
            "remaining_quantity_scaled": 10,
            "original_value_minor": 12000,
            "remaining_value_minor": 12000,
            "currency_code": "USD",
        }
    ]
    tables["inventory_layer_consumptions"] = [
        {
            "id": "consumption",
            "cost_layer_id": "layer",
            "valuation_line_id": "issue-line",
            "quantity_scaled": 10,
            "value_minor": 12000,
        }
    ]
    tables["inventory_valuation_reversal_effects"] = [
        {
            "id": "restore",
            "cost_layer_id": "layer",
            "original_consumption_id": "consumption",
            "original_valuation_line_id": "issue-line",
            "effect_type": "Restore",
            "quantity_scaled": 10,
            "value_minor": 12000,
        }
    ]
    for plan in tables["customer_return_plans"]:
        if plan["phase"] == 3:
            plan["payload"] = {"entries": [{"entry_id": f"unposted-{number}"} for number in range(3)]}
            continue
        effect_indices = (5, 4, 6) if plan["operation"] == "Return" else (7 if plan["amount_minor"] == 3000 else 8,)
        plan["payload"] = copy.deepcopy(plan.get("payload", {}))
        plan["payload"]["entries"] = [
            {
                "entry_id": tables["finance_posting_effects"][number]["entry_id"],
                "original_effect_id": tables["finance_posting_effects"][number]["reverses_effect_id"],
                "snapshot": copy.deepcopy(tables["finance_posting_effects"][number]["snapshot_json"]),
                "validation_digest": tables["finance_posting_effects"][number]["validation_digest"],
            }
            for number in effect_indices
        ]
    for values in tables.values():
        for row in values:
            row["tenant_id"] = "synthetic-tenant"
    return tables


def write_capture(root: Path, tables: dict[str, list[dict[str, Any]]], capture: int = 1) -> None:
    root.mkdir(exist_ok=True)
    for index, table in enumerate(oracle.TABLES, 1):
        packet = {
            "schema_version": "native-customer-return-row-original-v1",
            "capture": capture,
            "table": table,
            "rows": sorted(json.dumps(row, sort_keys=True, separators=(",", ":")) for row in tables[table]),
        }
        (root / f"native-financial-snapshot-oracle-{(capture - 1) * len(oracle.TABLES) + index}.json").write_text(
            json.dumps(packet), encoding="utf8"
        )


def test_independent_oracle_computes_every_actual_journal_vector_and_source_residual() -> None:
    result = oracle.verify_capture(rows())
    assert result["posted_effects"] == 9 and result["entry_lines"] == 18
    assert result["gl_debit_minor"] == result["gl_credit_minor"] == 156000
    assert result["account_balances_minor"] == {
        "AR": 0,
        "CASH": 0,
        "REVENUE": 0,
        "COGS": 0,
        "REFUND": 0,
        "INVENTORY": 12000,
        "CLEARING": -12000,
    }
    assert (
        result["source_credit_minor"]
        == result["receivable_released_minor"] + result["original_collected_minor"]
        == 45000
    )
    assert result["partial_refunds_minor"] == [3000, 7000] and result["refund_due_minor"] == 0


@pytest.mark.parametrize(
    "attack",
    [
        "missing",
        "duplicate",
        "extra",
        "unbalanced",
        "wrong_account",
        "balanced_swizzle",
        "orphan",
        "boolean_money",
        "string_money",
        "float_money",
        "wrong_currency",
        "wrong_status",
        "wrong_tenant",
        "wrong_cost",
        "wrong_refund",
        "wrong_source",
    ],
)
def test_independent_oracle_refuses_corrupt_actual_rows(attack: str) -> None:
    data = rows()
    if attack == "missing":
        data["finance_entry_lines"].pop()
    elif attack == "duplicate":
        data["finance_entry_lines"][1]["id"] = data["finance_entry_lines"][0]["id"]
    elif attack == "extra":
        data["finance_posting_effects"].append(copy.deepcopy(data["finance_posting_effects"][0]))
    elif attack == "unbalanced":
        data["finance_entry_lines"][0]["debit_minor"] -= 1
    elif attack == "wrong_account":
        data["finance_entry_lines"][0]["account_id"] = "missing-account"
    elif attack == "balanced_swizzle":
        data["finance_entry_lines"][0]["account_id"], data["finance_entry_lines"][2]["account_id"] = "COGS", "INVENTORY"
    elif attack == "orphan":
        data["finance_posting_effects"][0]["entry_id"] = "missing-entry"
    elif attack == "boolean_money":
        data["finance_entry_lines"][0]["debit_minor"] = True
    elif attack == "string_money":
        data["finance_entry_lines"][0]["debit_minor"] = "12000"
    elif attack == "float_money":
        data["finance_entry_lines"][0]["debit_minor"] = 12000.0
    elif attack == "wrong_currency":
        data["ar_invoices"][0]["currency_code"] = "EUR"
    elif attack == "wrong_status":
        data["finance_entries"][0]["status"] = "Posted"
    elif attack == "wrong_tenant":
        data["finance_entries"][0]["tenant_id"] = "other-tenant"
    elif attack == "wrong_cost":
        data["inventory_cost_layers"][0]["remaining_value_minor"] += 1
    elif attack == "wrong_refund":
        data["customer_return_plans"][-1]["amount_minor"] += 1
    else:
        data["inventory_valuation_reversal_effects"][0]["original_consumption_id"] = "other-source"
    with pytest.raises(oracle.OracleRefusal, match="Independent CR1"):
        oracle.verify_capture(data)


@pytest.mark.parametrize(
    "attack",
    [
        "source_kind",
        "source_id",
        "purpose",
        "fake_amount",
        "inverse_id",
        "snapshot_money",
        "refund_owner",
        "inverse_owner",
        "turnover_amount",
        "numeric_text_disagreement",
    ],
)
def test_balanced_gl_does_not_hide_corrupt_source_ownership(attack: str) -> None:
    data = rows()
    effect = data["finance_posting_effects"][1]
    if attack == "source_kind":
        effect["source_kind"] = "Unowned"
    elif attack == "source_id":
        effect["source_id"] = "other-source"
    elif attack == "purpose":
        effect["purpose"] = "other-purpose"
    elif attack == "fake_amount":
        effect["amount_minor"] = 12000
    elif attack == "inverse_id":
        data["finance_posting_effects"][4]["reverses_effect_id"] = "effect-1"
    elif attack == "snapshot_money":
        effect["snapshot_json"]["lines"][0]["debit_minor"] = True
    elif attack == "refund_owner":
        (
            data["customer_return_plans"][2]["payload"]["entries"],
            data["customer_return_plans"][3]["payload"]["entries"],
        ) = (
            data["customer_return_plans"][3]["payload"]["entries"],
            data["customer_return_plans"][2]["payload"]["entries"],
        )
    elif attack == "inverse_owner":
        data["customer_return_plans"][0]["payload"]["entries"][0]["original_effect_id"] = "effect-2"
    elif attack == "turnover_amount":
        data["customer_return_plans"][0]["amount_minor"] = 45000
    else:
        data["ar_invoice_lines"][0]["quantity_text"] = "11"
    with pytest.raises(oracle.OracleRefusal):
        oracle.verify_capture(data)


def test_original_postgres_numeric_quantity_token_uses_bounded_exact_fraction_and_retained_text(tmp_path: Path) -> None:
    root = tmp_path / "originals"
    write_capture(root, rows())
    path = root / "native-financial-snapshot-oracle-8.json"
    packet = json.loads(path.read_text())
    packet["rows"] = [row.replace('"quantity":10,', '"quantity":10.000000,') for row in packet["rows"]]
    assert "10.000000" in packet["rows"][0]
    path.write_text(json.dumps(packet))
    assert oracle.verify_directory(root)["result"]["restored_quantity_scaled"] == 10
    assert type(oracle.decode("10.000000")) is oracle.Fraction
    with pytest.raises(oracle.OracleRefusal):
        oracle.decode("1e99999999")


def test_whole_private_original_captures_and_restore_repeats_are_verified_without_mutation(tmp_path: Path) -> None:
    root = tmp_path / "originals"
    write_capture(root, rows())
    write_capture(root, rows(), 2)
    before = {path.name: path.read_bytes() for path in root.iterdir()}
    result = oracle.verify_directory(root)
    assert result["captures"] == 2 and len(result["input_identities"]) == 26
    assert result["complete_actual_rows_unchanged_across_captures"] is True
    assert before == {path.name: path.read_bytes() for path in root.iterdir()}


@pytest.mark.parametrize(
    "attack",
    ["gap", "duplicate_json_key", "nonfinite", "float", "unknown_envelope", "wrong_table", "wrong_capture", "drift"],
)
def test_private_original_parser_refuses_invalid_packets_and_custody(attack: str, tmp_path: Path) -> None:
    root = tmp_path / "originals"
    write_capture(root, rows())
    path = root / "native-financial-snapshot-oracle-1.json"
    if attack == "gap":
        path.unlink()
    elif attack == "duplicate_json_key":
        path.write_text('{"table":1,"table":2}')
    elif attack == "nonfinite":
        path.write_text('{"money":NaN}')
    elif attack == "float":
        path.write_text('{"money":1.2}')
    elif attack == "drift":
        changed = rows()
        changed["finance_entries"][0]["irrelevant_retained_field"] = "original-changed"
        write_capture(root, changed, 2)
    else:
        packet = json.loads(path.read_text())
        if attack == "unknown_envelope":
            packet["raw_error"] = "private-value"
        elif attack == "wrong_table":
            packet["table"] = "identity_sessions"
        else:
            packet["capture"] = True
        path.write_text(json.dumps(packet))
    with pytest.raises(oracle.OracleRefusal):
        oracle.verify_directory(root)


@pytest.mark.parametrize("optimized", [False, True])
def test_standalone_isolated_oracle_works_and_refuses_corruption_even_with_optimized_python(
    optimized: bool, tmp_path: Path
) -> None:
    root = tmp_path / "originals"
    write_capture(root, rows())
    command = [
        sys.executable,
        "-I",
        *(["-O"] if optimized else []),
        oracle.__file__,
        str(root),
        "--output",
        str(tmp_path / "scalar-proof.json"),
    ]
    accepted = subprocess.run(command, capture_output=True, text=True, check=False)
    assert accepted.returncode == 0 and json.loads(accepted.stdout)["verified"] is True
    damaged = json.loads((root / "native-financial-snapshot-oracle-2.json").read_text())
    damaged["rows"].pop()
    (root / "native-financial-snapshot-oracle-2.json").write_text(json.dumps(damaged))
    command[-1] = str(tmp_path / "refused-proof.json")
    refused = subprocess.run(command, capture_output=True, text=True, check=False)
    assert refused.returncode == 1 and not Path(command[-1]).exists()
    assert "synthetic-tenant" not in refused.stdout + refused.stderr


def test_observer_captures_sorted_original_row_text_once_per_table_and_preserves_restore_repeats(
    tmp_path: Path,
) -> None:
    from tests.customer_returns_browser import _capture_financial_originals

    class Cursor:
        def __init__(self, original: list[dict[str, Any]]) -> None:
            self.original = original

        def fetchall(self) -> list[dict[str, str]]:
            return [{"original": json.dumps(row, sort_keys=True)} for row in reversed(self.original)]

    class Connection:
        def __init__(self) -> None:
            self.queries: list[str] = []

        def execute(self, query: str, arguments: tuple[str, ...]) -> Cursor:
            assert query.startswith("SELECT to_jsonb(r)::text original FROM reconforge.")
            assert arguments == ("synthetic-tenant",)
            matched = re.search(r"FROM reconforge\.([a-z_]+) r WHERE", query)
            assert matched is not None
            self.queries.append(query)
            return Cursor(rows()[matched[1]])

    connection = Connection()
    root = tmp_path / "originals"
    first = _capture_financial_originals(connection, "synthetic-tenant", root)
    original_bytes = {path.name: path.read_bytes() for path in root.iterdir()}
    second = _capture_financial_originals(connection, "synthetic-tenant", root)
    assert first == second  # Full original/restored verify_cycles proof must remain comparable.
    assert first["table_count"] == second["table_count"] == 13
    assert first["published"] is second["published"] is False
    assert all({"table", "row_count", "row_text_bytes", "row_text_sha256"} == set(row) for row in first["tables"])
    assert all((root / name).read_bytes() == raw for name, raw in original_bytes.items())
    assert oracle.verify_directory(root)["captures"] == 2
    assert len(connection.queries) == 26
    assert sum("EXISTS" in query for query in connection.queries) == 6


@pytest.mark.parametrize("attack", ["unknown_entry", "incomplete_capture", "budget"])
def test_observer_refuses_unowned_or_incomplete_storage_before_sql_reads(tmp_path: Path, attack: str) -> None:
    from tests.customer_returns_browser import _capture_financial_originals

    root = tmp_path / "originals"
    root.mkdir()
    if attack == "unknown_entry":
        (root / "not-a-financial-original.json").write_text("{}")
    elif attack == "incomplete_capture":
        (root / "native-financial-snapshot-oracle-1.json").write_text("{}")
    else:
        for number in range(1, oracle.MAX_FILES + 1):
            (root / f"native-financial-snapshot-oracle-{number}.json").write_text("{}")

    class NoSql:
        def execute(self, *_: Any) -> None:
            raise AssertionError("Refusal must precede SQL.")

    with pytest.raises(AssertionError, match="Private financial"):
        _capture_financial_originals(NoSql(), "synthetic-tenant", root)
