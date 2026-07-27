from __future__ import annotations

from pathlib import Path

import pandas as pd

from reconforge.schemas import DatasetName
from reconforge.validators import issues_to_frame, validate_input_directory


def _copy_sample(tmp_path: Path, sample_dir: Path) -> Path:
    target = tmp_path / "input"
    target.mkdir()
    for source in sample_dir.glob("*.csv"):
        (target / source.name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    return target


def test_sample_validation_has_no_structural_errors(sample_dir: Path) -> None:
    issues = validate_input_directory(sample_dir)
    frame = issues_to_frame(issues)
    assert not frame.empty
    assert frame["severity"].eq("error").sum() == 0
    assert frame["severity"].eq("warning").sum() >= 1


def test_missing_required_column_is_error(tmp_path: Path, sample_dir: Path) -> None:
    target = _copy_sample(tmp_path, sample_dir)
    stock = pd.read_csv(target / "stock_moves.csv")
    stock = stock.drop(columns=["move_id"])
    stock.to_csv(target / "stock_moves.csv", index=False)
    issues = validate_input_directory(target)
    assert any(issue.check == "required_column" and issue.column == "move_id" for issue in issues)


def test_invalid_amount_warning_detected(sample_dir: Path) -> None:
    issues = validate_input_directory(sample_dir)
    assert any(issue.check == "invalid_amount" and issue.dataset == DatasetName.STOCK_MOVES.value for issue in issues)


def test_over_precise_currency_amount_is_flagged_during_validation(tmp_path: Path) -> None:
    target = tmp_path / "input"
    target.mkdir()
    (target / "stock_moves.csv").write_text(
        "move_id,date,source_document,work_order,product_code,product_name,category,quantity,unit_cost,total_cost,warehouse,movement_type,customer_code,equipment_serial,created_by,currency\n"
        "MOVE-JPY,2026-01-01,INV-1,WO-1,SKU-1,Widget,Stock,1,100.75,100.75,WH1,issue,CUST-1,SERIAL-1,USER-1,JPY\n",
        encoding="utf-8",
    )
    (target / "gl_entries.csv").write_text(
        "entry_id,date,journal,account_code,account_name,reference,source_document,debit,credit,amount,cost_center,work_order,created_by,currency\n"
        "GL-JPY,2026-01-01,JNL,1000,Main,INV-1,INV-1,0,0,0,CC1,WO-1,USER-1,JPY\n",
        encoding="utf-8",
    )
    (target / "work_orders.csv").write_text(
        "work_order,customer_code,customer_name,equipment_serial,status,opened_date,closed_date,service_type,responsible_engineer,workshop,estimated_cost,actual_cost\n"
        "WO-1,CUST-1,Customer,SERIAL-1,open,2026-01-01,,Service,ENG,WS1,0,0\n",
        encoding="utf-8",
    )
    (target / "purchase_orders.csv").write_text(
        "po_number,supplier_code,supplier_name,po_date,product_code,quantity,unit_price,total_price,status,linked_work_order\n"
        "PO-1,SUP-1,Supplier,2026-01-01,SKU-1,1,100,100,open,\n",
        encoding="utf-8",
    )
    (target / "products.csv").write_text(
        "product_code,product_name,category,standard_cost,stock_account,expense_account\n"
        "SKU-1,Widget,Stock,100,1000,5000\n",
        encoding="utf-8",
    )
    (target / "customers.csv").write_text(
        "customer_code,customer_name,segment,region\n"
        "CUST-1,Customer,SME,North\n",
        encoding="utf-8",
    )
    (target / "old_parts_returns.csv").write_text(
        "return_id,work_order,product_code,returned_quantity,return_date,received_by,condition\n"
        "RET-1,WO-1,SKU-1,0,2026-01-01,USER-1,good\n",
        encoding="utf-8",
    )
    (target / "invoices.csv").write_text(
        "invoice_number,work_order,customer_code,invoice_date,invoice_amount,status\n"
        "INV-1,WO-1,CUST-1,2026-01-01,100,open\n",
        encoding="utf-8",
    )

    issues = validate_input_directory(target)
    assert any(issue.check == "invalid_amount" and issue.dataset == DatasetName.STOCK_MOVES.value for issue in issues)


def test_unknown_currency_is_reported_without_assuming_two_decimals(tmp_path: Path, sample_dir: Path) -> None:
    target = _copy_sample(tmp_path, sample_dir)
    for filename in ("stock_moves.csv", "gl_entries.csv"):
        frame = pd.read_csv(target / filename)
        frame["currency"] = "ZZZ"
        frame.to_csv(target / filename, index=False)

    issues = validate_input_directory(target)
    currency_issues = [issue for issue in issues if issue.check == "unknown_currency"]

    assert currency_issues
    assert {issue.dataset for issue in currency_issues} == {
        DatasetName.STOCK_MOVES.value,
        DatasetName.GL_ENTRIES.value,
    }
    assert {issue.column for issue in currency_issues} == {"currency"}
    assert {issue.reference for issue in currency_issues} == {"ZZZ"}


def test_duplicate_reference_warning_detected(sample_dir: Path) -> None:
    issues = validate_input_directory(sample_dir)
    assert any(issue.check == "duplicate_reference" and issue.reference == "STK-ISS-1001" for issue in issues)


def test_invalid_product_code_warning_detected(sample_dir: Path) -> None:
    issues = validate_input_directory(sample_dir)
    assert any(issue.check == "missing_item_code" and issue.reference == "INVALID-999" for issue in issues)


def test_missing_work_order_warning_detected(sample_dir: Path) -> None:
    issues = validate_input_directory(sample_dir)
    assert any(issue.check == "missing_work_order" and issue.dataset == DatasetName.STOCK_MOVES.value for issue in issues)


def test_missing_customer_reference_warning_detected(sample_dir: Path) -> None:
    issues = validate_input_directory(sample_dir)
    assert any(issue.check == "missing_customer_reference" and issue.reference == "CUST-999" for issue in issues)
