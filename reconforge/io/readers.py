"""Readers for CSV and Excel ERP extracts."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pandas as pd

from reconforge.io.ingress import (
    DEFAULT_TABULAR_INGRESS_POLICY,
    FileIngressError,
    TabularIngressPolicy,
    validate_tabular_input,
)
from reconforge.schemas import DATE_COLUMNS, NUMERIC_COLUMNS, REQUIRED_COLUMNS, DatasetName
from reconforge.utils.dates import parse_date_series
from reconforge.utils.money import InvalidAmountError, parse_exact_amount


def dataset_filename(dataset: DatasetName, extension: str) -> str:
    """Return the expected filename for a dataset and extension."""

    return f"{dataset.value}.{extension}"


def find_dataset_file(input_dir: Path, dataset: DatasetName) -> Path | None:
    """Find a CSV or XLSX file for a dataset."""

    for extension in ("csv", "xlsx", "xls"):
        candidate = input_dir / dataset_filename(dataset, extension)
        if candidate.exists():
            return candidate
    return None


def read_table(
    path: Path,
    *,
    nrows: int | None = None,
    ingress_policy: TabularIngressPolicy = DEFAULT_TABULAR_INGRESS_POLICY,
) -> pd.DataFrame:
    """Inspect and read a bounded CSV or Excel table into a DataFrame."""

    if nrows is not None and (isinstance(nrows, bool) or not 0 <= nrows <= ingress_policy.max_rows):
        raise ValueError("nrows must be between zero and the ingress row limit")
    validate_tabular_input(path, policy=ingress_policy)
    parser_rows = ingress_policy.max_rows + 1 if nrows is None else nrows
    try:
        if path.suffix.lower() == ".csv":
            frame = pd.read_csv(path, dtype=str, keep_default_na=False, nrows=parser_rows)
        elif path.suffix.lower() in {".xlsx", ".xls"}:
            frame = pd.read_excel(path, dtype=str, keep_default_na=False, nrows=parser_rows)
        else:
            raise FileIngressError("file_type_unsupported")
    except FileIngressError:
        raise
    except Exception as exc:
        raise FileIngressError("table_parse_failed") from exc
    if len(frame) > ingress_policy.max_rows:
        raise FileIngressError("table_row_limit")
    if len(frame.columns) > ingress_policy.max_columns:
        raise FileIngressError("table_column_limit")
    if len(frame) * max(1, len(frame.columns)) > ingress_policy.max_cells:
        raise FileIngressError("table_cell_limit")
    return frame


def normalize_columns(frame: pd.DataFrame) -> pd.DataFrame:
    """Normalize column names to lowercase snake_case-like labels."""

    normalized = frame.copy()
    normalized.columns = [str(column).strip().lower().replace(" ", "_") for column in normalized.columns]
    return normalized


def coerce_dataset_types(frame: pd.DataFrame, dataset: DatasetName) -> pd.DataFrame:
    """Coerce date and numeric columns for a loaded dataset."""

    coerced = normalize_columns(frame)
    for column in DATE_COLUMNS[dataset]:
        if column in coerced.columns:
            coerced[column] = parse_date_series(coerced[column])
    for column in NUMERIC_COLUMNS[dataset]:
        if column in coerced.columns:
            raw_values = coerced[column].copy()
            parsed_values: list[Decimal | None] = []
            invalid_values: list[str | None] = []
            for value in raw_values:
                try:
                    parsed_values.append(parse_exact_amount(value))
                    invalid_values.append(None)
                except InvalidAmountError:
                    parsed_values.append(None)
                    invalid_values.append(str(value))
            coerced[column] = parsed_values
            if any(value is not None for value in invalid_values):
                coerced[f"_reconforge_raw_{column}"] = invalid_values
    for column in REQUIRED_COLUMNS[dataset]:
        if column in coerced.columns and column not in DATE_COLUMNS[dataset] and column not in NUMERIC_COLUMNS[dataset]:
            coerced[column] = coerced[column].fillna("").astype(str).str.strip()
    return coerced


def read_dataset(input_dir: Path | str, dataset: DatasetName) -> pd.DataFrame:
    """Read a required dataset from an input directory."""

    base_path = Path(input_dir)
    file_path = find_dataset_file(base_path, dataset)
    if file_path is None:
        raise FileNotFoundError(f"Missing input file for dataset '{dataset.value}' in {base_path}")
    return coerce_dataset_types(read_table(file_path), dataset)


def read_available_datasets(input_dir: Path | str) -> dict[DatasetName, pd.DataFrame]:
    """Read all datasets that exist in an input directory."""

    base_path = Path(input_dir)
    datasets: dict[DatasetName, pd.DataFrame] = {}
    for dataset in DatasetName:
        file_path = find_dataset_file(base_path, dataset)
        if file_path is not None:
            datasets[dataset] = coerce_dataset_types(read_table(file_path), dataset)
    return datasets


def read_required_datasets(input_dir: Path | str, datasets: list[DatasetName]) -> dict[DatasetName, pd.DataFrame]:
    """Read a requested set of required datasets."""

    return {dataset: read_dataset(input_dir, dataset) for dataset in datasets}
