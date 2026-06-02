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
