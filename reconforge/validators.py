"""Dataset validation for ReconForge ERP."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from reconforge.io.readers import find_dataset_file, read_available_datasets, read_table
from reconforge.schemas import DATE_COLUMNS, NUMERIC_COLUMNS, REQUIRED_COLUMNS, DatasetName, ValidationIssue

OPTIONAL_DATE_COLUMNS: dict[DatasetName, set[str]] = {
    DatasetName.WORK_ORDERS: {"closed_date"},
}


def _issue(
    dataset: DatasetName,
    severity: str,
    check: str,
    message: str,
    row: int | None = None,
    column: str | None = None,
    reference: str | None = None,
) -> ValidationIssue:
    return ValidationIssue(
        dataset=dataset.value,
        severity=severity,
        check=check,
        message=message,
        row=row,
        column=column,
        reference=reference,
    )


def _row_number(index: object) -> int:
    return int(str(index)) + 2


def validate_required_files(input_dir: Path) -> list[ValidationIssue]:
    """Validate that all expected input files exist."""

    issues: list[ValidationIssue] = []
    for dataset in DatasetName:
        if find_dataset_file(input_dir, dataset) is None:
            issues.append(
                _issue(
                    dataset,
                    "error",
                    "required_file",
                    f"Missing required file for dataset '{dataset.value}'",
                ),
            )
    return issues


def validate_columns(input_dir: Path) -> list[ValidationIssue]:
    """Validate dataset columns before type coercion."""

    issues: list[ValidationIssue] = []
    for dataset in DatasetName:
        file_path = find_dataset_file(input_dir, dataset)
        if file_path is None:
            continue
        raw = read_table(file_path)
        raw.columns = [str(column).strip().lower().replace(" ", "_") for column in raw.columns]
        missing = [column for column in REQUIRED_COLUMNS[dataset] if column not in raw.columns]
        for column in missing:
            issues.append(
                _issue(
                    dataset,
                    "error",
                    "required_column",
                    f"Missing required column '{column}'",
                    column=column,
                ),
            )
    return issues


def validate_types(datasets: dict[DatasetName, pd.DataFrame]) -> list[ValidationIssue]:
    """Validate dates and numeric values after coercion."""

    issues: list[ValidationIssue] = []
    for dataset, frame in datasets.items():
        for column in DATE_COLUMNS[dataset]:
            if column in frame.columns:
                if column in OPTIONAL_DATE_COLUMNS.get(dataset, set()):
                    continue
                invalid_rows = frame.index[frame[column].isna()].tolist()
                for index in invalid_rows:
                    issues.append(
                        _issue(
                            dataset,
                            "error",
                            "invalid_date",
                            f"Invalid or missing date in column '{column}'",
                            row=_row_number(index),
                            column=column,
                        ),
                    )
        for column in NUMERIC_COLUMNS[dataset]:
            if column in frame.columns:
                invalid_rows = frame.index[frame[column].isna()].tolist()
                for index in invalid_rows:
                    issues.append(
                        _issue(
                            dataset,
                            "error",
                            "invalid_number",
                            f"Invalid or missing numeric value in column '{column}'",
                            row=_row_number(index),
                            column=column,
                        ),
                    )
    return issues


def validate_duplicates(datasets: dict[DatasetName, pd.DataFrame]) -> list[ValidationIssue]:
    """Validate duplicate identifiers and transaction references."""

    issues: list[ValidationIssue] = []
    identifier_columns = {
        DatasetName.STOCK_MOVES: ["move_id", "source_document"],
        DatasetName.GL_ENTRIES: ["entry_id", "reference"],
        DatasetName.WORK_ORDERS: ["work_order"],
        DatasetName.PURCHASE_ORDERS: ["po_number"],
        DatasetName.PRODUCTS: ["product_code"],
        DatasetName.CUSTOMERS: ["customer_code"],
        DatasetName.OLD_PARTS_RETURNS: ["return_id"],
        DatasetName.INVOICES: ["invoice_number"],
    }
    for dataset, columns in identifier_columns.items():
        frame = datasets.get(dataset)
        if frame is None:
            continue
        for column in columns:
            if column not in frame.columns:
                continue
            duplicate_mask = frame[column].astype(str).str.strip().ne("") & frame[column].duplicated(keep=False)
            for index, row in frame[duplicate_mask].iterrows():
                severity = "error" if column in {"move_id", "entry_id", "work_order", "po_number"} else "warning"
                issues.append(
                    _issue(
                        dataset,
                        severity,
                        "duplicate_reference",
                        f"Duplicate value '{row[column]}' in column '{column}'",
                        row=_row_number(index),
                        column=column,
                        reference=str(row[column]),
                    ),
                )
    return issues


def validate_amount_consistency(datasets: dict[DatasetName, pd.DataFrame]) -> list[ValidationIssue]:
    """Validate accounting amount consistency for transactional datasets."""

    issues: list[ValidationIssue] = []
    stock = datasets.get(DatasetName.STOCK_MOVES)
    if stock is not None and {"quantity", "unit_cost", "total_cost"}.issubset(stock.columns):
        expected = (stock["quantity"] * stock["unit_cost"]).round(2)
        diff = (stock["total_cost"] - expected).abs().round(2)
        for index, row in stock[diff > 0.01].iterrows():
            issues.append(
                _issue(
                    DatasetName.STOCK_MOVES,
                    "warning",
                    "invalid_amount",
                    "Stock total_cost does not equal quantity multiplied by unit_cost",
                    row=_row_number(index),
                    column="total_cost",
                    reference=str(row.get("move_id", "")),
                ),
            )

    gl = datasets.get(DatasetName.GL_ENTRIES)
    if gl is not None and {"debit", "credit", "amount"}.issubset(gl.columns):
        expected_amount = (gl["debit"] - gl["credit"]).abs().round(2)
        diff = (gl["amount"].abs().round(2) - expected_amount).abs()
        for index, row in gl[diff > 0.01].iterrows():
            issues.append(
                _issue(
                    DatasetName.GL_ENTRIES,
                    "warning",
                    "invalid_amount",
                    "GL amount does not equal absolute debit minus credit",
                    row=_row_number(index),
                    column="amount",
                    reference=str(row.get("entry_id", "")),
                ),
            )
    return issues


def validate_references(datasets: dict[DatasetName, pd.DataFrame]) -> list[ValidationIssue]:
    """Validate cross-dataset references."""

    issues: list[ValidationIssue] = []
    stock = datasets.get(DatasetName.STOCK_MOVES)
    gl = datasets.get(DatasetName.GL_ENTRIES)
    work_orders = datasets.get(DatasetName.WORK_ORDERS)
    products = datasets.get(DatasetName.PRODUCTS)
    customers = datasets.get(DatasetName.CUSTOMERS)

    valid_work_orders = set(work_orders["work_order"].astype(str)) if work_orders is not None and "work_order" in work_orders else set()
    valid_products = set(products["product_code"].astype(str)) if products is not None and "product_code" in products else set()
    valid_customers = set(customers["customer_code"].astype(str)) if customers is not None and "customer_code" in customers else set()

    if stock is not None:
        for index, row in stock.iterrows():
            work_order = str(row.get("work_order", "")).strip()
            product_code = str(row.get("product_code", "")).strip()
            customer_code = str(row.get("customer_code", "")).strip()
            if not work_order or work_order not in valid_work_orders:
                issues.append(
                    _issue(
                        DatasetName.STOCK_MOVES,
                        "warning",
                        "missing_work_order",
                        "Stock movement references a missing or invalid work order",
                        row=_row_number(index),
                        column="work_order",
                        reference=work_order,
                    ),
                )
            if not product_code or product_code not in valid_products:
                issues.append(
                    _issue(
                        DatasetName.STOCK_MOVES,
                        "warning",
                        "missing_item_code",
                        "Stock movement references a missing or invalid product code",
                        row=_row_number(index),
                        column="product_code",
                        reference=product_code,
                    ),
                )
            if not customer_code or customer_code not in valid_customers:
                issues.append(
                    _issue(
                        DatasetName.STOCK_MOVES,
                        "warning",
                        "missing_customer_reference",
                        "Stock movement references a missing or invalid customer",
                        row=_row_number(index),
                        column="customer_code",
                        reference=customer_code,
                    ),
                )

    if gl is not None:
        for index, row in gl.iterrows():
            work_order = str(row.get("work_order", "")).strip()
            if work_order and work_order not in valid_work_orders:
                issues.append(
                    _issue(
                        DatasetName.GL_ENTRIES,
                        "warning",
                        "missing_work_order",
                        "GL entry references a missing or invalid work order",
                        row=_row_number(index),
                        column="work_order",
                        reference=work_order,
                    ),
                )
    return issues


def validate_input_directory(input_dir: Path | str) -> list[ValidationIssue]:
    """Run all validation checks for an input directory."""

    base_path = Path(input_dir)
    issues = validate_required_files(base_path)
    issues.extend(validate_columns(base_path))
    structural_errors = [issue for issue in issues if issue.severity == "error"]
    if structural_errors:
        return issues

    datasets = read_available_datasets(base_path)
    issues.extend(validate_types(datasets))
    type_errors = [issue for issue in issues if issue.severity == "error"]
    if type_errors:
        return issues

    issues.extend(validate_duplicates(datasets))
    issues.extend(validate_amount_consistency(datasets))
    issues.extend(validate_references(datasets))
    return issues


def issues_to_frame(issues: list[ValidationIssue]) -> pd.DataFrame:
    """Convert validation issues to a DataFrame."""

    if not issues:
        return pd.DataFrame(columns=["dataset", "severity", "check", "message", "row", "column", "reference"])
    return pd.DataFrame([issue.model_dump() for issue in issues])
