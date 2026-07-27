"""Studio dataset loading and utility helpers."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd

from reconforge.config import load_config
from reconforge.db import DatabaseError, connect, database_status, resolve_db_path
from reconforge.io.generated import (
    GeneratedArtifactError,
    read_generated_csv_document,
    read_generated_json_document,
)
from reconforge.io.readers import read_required_datasets
from reconforge.reconciliation.stock_gl import reconcile_stock_gl
from reconforge.reconciliation.workorders import reconcile_workorders
from reconforge.reports.wip_aging import generate_wip_aging
from reconforge.review.state import ALLOWED_STATUSES
from reconforge.schemas import DatasetName
from reconforge.utils.money import (
    STRICT_FINANCIAL_INPUT_POLICY,
    FinancialInputPolicy,
    InvalidAmountError,
    parse_amount,
)
from reconforge.utils.safe_paths import is_safe_download_key

DOWNLOAD_SUFFIXES = {".html", ".xlsx", ".csv", ".json", ".md", ".txt", ".yml", ".yaml"}
DOC_SUFFIXES = {".md"}
AmountFilterInput = Decimal | str | int
LegacyAmountFilterInput = AmountFilterInput | float
_MAX_AMOUNT_FILTER_CHARS = 100

INVALID_REVIEW_STATUS_MESSAGE = f"Invalid review status. Expected one of: {', '.join(ALLOWED_STATUSES)}."


def _single_segment_download_key(value: str) -> str:
    if "/" in value or not is_safe_download_key(value):
        raise ValueError("Unsafe download key segment")
    return value


def _evidence_download_key(case_id: str, filename: str) -> str:
    return f"{_single_segment_download_key(case_id)}/{_single_segment_download_key(filename)}"


def _load_reconciliation(input_dir: Path) -> dict[str, Any]:
    config = load_config(
        Path("config/reconforge.yml"),
        financial_input_policy=STRICT_FINANCIAL_INPUT_POLICY,
    )
    datasets = read_required_datasets(
        input_dir,
        [
            DatasetName.STOCK_MOVES,
            DatasetName.GL_ENTRIES,
            DatasetName.WORK_ORDERS,
            DatasetName.PURCHASE_ORDERS,
            DatasetName.OLD_PARTS_RETURNS,
            DatasetName.INVOICES,
        ],
    )
    stock = reconcile_stock_gl(
        datasets[DatasetName.STOCK_MOVES],
        datasets[DatasetName.GL_ENTRIES],
        config,
        input_policy=STRICT_FINANCIAL_INPUT_POLICY,
    )
    workorders = reconcile_workorders(
        datasets[DatasetName.STOCK_MOVES],
        datasets[DatasetName.WORK_ORDERS],
        datasets[DatasetName.PURCHASE_ORDERS],
        datasets[DatasetName.OLD_PARTS_RETURNS],
        datasets[DatasetName.INVOICES],
        config,
    )
    wip = generate_wip_aging(datasets[DatasetName.WORK_ORDERS], config)
    exceptions = pd.concat([stock.all_exceptions, workorders.all_exceptions], ignore_index=True, sort=False)
    return {"stock": stock, "workorders": workorders, "wip": wip, "exceptions": exceptions}


def _read_generated_csv(
    path: Path,
    *,
    companion_path: Path | None = None,
    collection_key: str | None = None,
) -> pd.DataFrame:
    """Read one bounded Studio CSV, checking companion shape when available."""

    if not path.exists() or not path.is_file():
        return pd.DataFrame()
    try:
        document = read_generated_csv_document(path)
        if companion_path is not None and companion_path.exists():
            if collection_key is None:
                return pd.DataFrame()
            companion = read_generated_json_document(companion_path).payload
            records = companion.get(collection_key)
            if (
                not isinstance(records, list)
                or not all(isinstance(record, dict) for record in records)
                or len(records) != len(document.frame)
            ):
                return pd.DataFrame()
            expected_columns = {str(key) for record in records for key in record}
            if not expected_columns.issubset({str(column) for column in document.frame.columns}):
                return pd.DataFrame()
        return document.frame
    except GeneratedArtifactError:
        return pd.DataFrame()


def _json_payload(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {}
    try:
        return read_generated_json_document(path).payload
    except GeneratedArtifactError:
        return {}


def _evidence_coverage_cards(exceptions: pd.DataFrame, output_path: Path) -> str:
    if exceptions.empty:
        high_critical = 0
    else:
        risk_score = pd.Series(
            [_parse_amount_decimal(value) for value in exceptions.get("risk_score", pd.Series([None] * len(exceptions), index=exceptions.index))],
            index=exceptions.index,
        )
        risk_level = exceptions.get("risk_level", pd.Series([""] * len(exceptions))).astype(str).str.lower()
        high_risk_score = pd.Series([value is not None and value >= Decimal("61") for value in risk_score], index=exceptions.index)
        high_critical = int((high_risk_score | risk_level.isin({"high", "critical"})).sum())
    payload = _json_payload(output_path / "evidence" / "evidence_index.json")
    case_count_value = payload.get("case_count")
    evidence_cases = int(case_count_value) if isinstance(case_count_value, int) else len(payload.get("cases", [])) if isinstance(payload.get("cases"), list) else 0
    coverage = round((evidence_cases / high_critical) * 100, 2) if high_critical else 100.0
    return "".join(
        [
            f'<section class="card"><span>High/Critical Exceptions</span><strong>{high_critical}</strong></section>',
            f'<section class="card"><span>Evidence Cases</span><strong>{evidence_cases}</strong></section>',
            f'<section class="card"><span>Evidence Coverage</span><strong>{coverage}%</strong></section>',
        ],
    )


def _amount_series(frame: pd.DataFrame) -> pd.Series:
    if "amount_impact" in frame.columns:
        return pd.Series([_parse_amount_decimal(value) for value in frame["amount_impact"]], index=frame.index)
    return pd.Series([pd.NA] * len(frame), index=frame.index, dtype=object)


def _search_text(row: pd.Series) -> str:
    return " ".join(str(value) for value in row.to_list()).lower()


def _filter_exceptions(
    frame: pd.DataFrame,
    *,
    severity: str = "",
    exception_type: str = "",
    status: str = "",
    source_file: str = "",
    search: str = "",
    min_amount: LegacyAmountFilterInput = "0",
    financial_input_policy: FinancialInputPolicy = STRICT_FINANCIAL_INPUT_POLICY,
    sort: str = "risk_score",
) -> pd.DataFrame:
    threshold = _parse_minimum_amount(
        min_amount,
        input_policy=financial_input_policy,
    )
    filtered = frame.copy()
    if severity:
        severity_values = pd.Series([""] * len(filtered), index=filtered.index)
        if "severity" in filtered.columns:
            severity_values = severity_values.mask(filtered["severity"].astype(str).str.strip().ne(""), filtered["severity"].astype(str))
        if "risk_level" in filtered.columns:
            severity_values = severity_values.mask(severity_values.str.strip().eq(""), filtered["risk_level"].astype(str))
        filtered = filtered[severity_values.str.lower().eq(severity.lower())]
    if exception_type and "exception_type" in filtered.columns:
        filtered = filtered[filtered["exception_type"].astype(str).str.lower().eq(exception_type.lower())]
    if status and "status" in filtered.columns:
        filtered = filtered[filtered["status"].astype(str).str.lower().eq(status.lower())]
    if source_file and "source_file" in filtered.columns:
        filtered = filtered[filtered["source_file"].astype(str).str.lower().eq(source_file.lower())]
    if search:
        haystack = filtered.apply(_search_text, axis=1)
        filtered = filtered[haystack.str.contains(search.lower(), regex=False)]
    if threshold > 0:
        amount_series = _amount_series(filtered)
        filtered = filtered[amount_series.notna() & amount_series.ge(threshold)]
    if sort == "amount_impact":
        amount_series = _amount_series(filtered)
        tie_breaker = filtered.get("exception_id", pd.Series([""] * len(filtered))).astype(str)
        filtered = filtered.assign(
            _sort_amount=amount_series,
            _sort_amount_valid=amount_series.notna(),
            _sort_tie=tie_breaker,
        ).sort_values(
            ["_sort_amount_valid", "_sort_amount", "_sort_tie"],
            ascending=[False, False, True],
        ).drop(columns=["_sort_amount", "_sort_amount_valid", "_sort_tie"])
    elif sort == "updated_at" and "updated_at" in filtered.columns:
        filtered = filtered.sort_values("updated_at", ascending=False)
    elif "risk_score" in filtered.columns:
        risk_scores = pd.Series([_parse_amount_decimal(value) for value in filtered["risk_score"]], index=filtered.index)
        tie_breaker = filtered.get("exception_id", pd.Series([""] * len(filtered))).astype(str)
        filtered = filtered.assign(
            _sort_risk=risk_scores,
            _sort_risk_valid=risk_scores.notna(),
            _sort_tie=tie_breaker,
        ).sort_values(
            ["_sort_risk_valid", "_sort_risk", "_sort_tie"],
            ascending=[False, False, True],
        ).drop(columns=["_sort_risk", "_sort_risk_valid", "_sort_tie"])
    return filtered


def _parse_minimum_amount(
    value: LegacyAmountFilterInput,
    *,
    input_policy: FinancialInputPolicy = STRICT_FINANCIAL_INPUT_POLICY,
) -> Decimal:
    """Parse one bounded, exact, non-negative Studio amount threshold."""

    if isinstance(value, str) and len(value) > _MAX_AMOUNT_FILTER_CHARS:
        raise InvalidAmountError("minimum amount filter is too long")
    try:
        parsed = parse_amount(value, input_policy=input_policy)
    except (InvalidAmountError, TypeError, ValueError) as exc:
        raise InvalidAmountError("minimum amount filter must be a finite non-negative decimal") from exc
    if parsed < 0:
        raise InvalidAmountError("minimum amount filter must be a finite non-negative decimal")
    return parsed


def _parse_amount_decimal(value: object) -> Decimal | None:
    """Parse an amount value to Decimal, returning None on invalid financial text."""

    try:
        return parse_amount(value)
    except (InvalidAmountError, TypeError, ValueError):
        return None


def _filter_form(frame: pd.DataFrame) -> str:
    from reconforge.studio.components import _options

    severity_values = sorted(
        {
            value
            for column in ("severity", "risk_level")
            if column in frame.columns
            for value in frame[column].astype(str).str.strip()
            if value and str(value).lower() != "nan"
        },
        key=lambda item: str(item),
    )
    exception_values = sorted(set(frame.get("exception_type", pd.Series(dtype=str)).astype(str).str.strip()) - {""})
    source_values = sorted(set(frame.get("source_file", pd.Series(dtype=str)).astype(str).str.strip()) - {""})
    return f"""
<form class="filters" method="get" action="/exceptions">
  <label>Severity / risk level<select name="severity">{_options(severity_values)}</select></label>
  <label>Exception type<select name="exception_type">{_options(exception_values)}</select></label>
  <label>Review status<select name="status">{_options(list(ALLOWED_STATUSES))}</select></label>
  <label>Source file<select name="source_file">{_options(source_values)}</select></label>
  <label>Search<input name="search"></label>
  <label>Minimum amount<input name="min_amount" type="text" inputmode="decimal" value="0" maxlength="100"></label>
  <label>Sort<select name="sort">{_options(["risk_score", "amount_impact", "updated_at"])}</select></label>
  <button type="submit">Apply</button>
</form>
"""


def _validate_auth_database(db_path: Path | str | None) -> Path:
    if db_path is None:
        raise DatabaseError("Studio auth-required mode needs --db pointing to a migrated ReconForge database.")
    resolved = resolve_db_path(db_path)
    status = database_status(resolved)
    if status.pending_versions:
        raise DatabaseError("ReconForge database has pending migrations. Run 'reconforge db migrate' first.")
    connection = connect(resolved, require_exists=True)
    try:
        from reconforge.api.security import ensure_session_schema
        from reconforge.auth.repositories import ensure_auth_schema

        ensure_auth_schema(connection)
        ensure_session_schema(connection)
    finally:
        connection.close()
    return resolved


def _optional_studio_database(db_path: Path | str | None) -> Path | None:
    if db_path is None:
        return None
    try:
        resolved = resolve_db_path(db_path)
    except DatabaseError:
        return None
    if not resolved.exists():
        return None
    status = database_status(resolved)
    if status.pending_versions:
        return None
    return resolved
