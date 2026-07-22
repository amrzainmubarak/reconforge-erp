"""Stock movement to GL reconciliation."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, cast

import pandas as pd

from reconforge.config import ReconForgeConfig
from reconforge.reconciliation.matching import MatchCandidate, MatchingStrategy, match_stock_to_gl, normalize_reference
from reconforge.reconciliation.risk import assess_risk
from reconforge.utils.money import InvalidAmountError, parse_amount


@dataclass(frozen=True)
class StockGLReconciliationResult:
    """Output frames from stock-vs-GL reconciliation."""

    matched_transactions: pd.DataFrame
    stock_without_gl: pd.DataFrame
    gl_without_stock: pd.DataFrame
    value_differences: pd.DataFrame
    date_differences: pd.DataFrame
    reference_mismatches: pd.DataFrame
    data_quality_exceptions: pd.DataFrame
    all_exceptions: pd.DataFrame
    summary: pd.DataFrame


_EXCEPTION_REASONS = {
    "stock_without_gl": "No eligible GL entry was assigned to the stock movement.",
    "gl_without_stock": "No eligible stock movement was assigned to the GL entry.",
    "value_difference": "Matched source and GL amounts differ beyond the configured tolerance.",
    "date_difference": "Matched source and GL postings have different dates.",
    "reference_mismatch": "Normalized source and GL references do not agree.",
    "data_quality": "A required financial amount is missing, malformed, or non-finite.",
}


def _safe_amount(value: object) -> float:
    try:
        return parse_amount(value)
    except InvalidAmountError:
        return 0.0


def _exception_id(exception_type: str, row: pd.Series) -> str:
    identity = "|".join(
        str(row.get(field, "") or "")
        for field in ("match_id", "move_id", "entry_id", "source_dataset", "source_row", "field")
    )
    digest = hashlib.sha256(f"{exception_type}|{identity}".encode()).hexdigest()[:20].upper()
    return f"EXC-{digest}"


def _risk_columns(
    frame: pd.DataFrame,
    exception_type: str,
    config: ReconForgeConfig,
    amount_column: str,
    difference_column: str | None = None,
) -> pd.DataFrame:
    enriched = frame.copy()
    scores: list[int] = []
    levels: list[str] = []
    for _, row in enriched.iterrows():
        assessment = assess_risk(
            exception_type,
            config,
            amount=_safe_amount(row.get(amount_column, 0.0)),
            amount_difference=abs(_safe_amount(row.get(difference_column, 0.0))) if difference_column else 0.0,
        )
        scores.append(assessment.score)
        levels.append(assessment.level)
    enriched["exception_type"] = exception_type
    enriched["exception_reason"] = _EXCEPTION_REASONS[exception_type]
    enriched["risk_score"] = scores
    enriched["risk_level"] = levels
    enriched["exception_id"] = [
        _exception_id(exception_type, cast("pd.Series[Any]", row)) for _, row in enriched.iterrows()
    ]
    enriched["evidence_reference"] = enriched.apply(
        lambda row: str(
            row.get("match_id")
            or row.get("move_id")
            or row.get("entry_id")
            or f"{row.get('source_dataset', '')}:{row.get('source_row', '')}",
        ),
        axis=1,
    )
    return enriched


def _data_quality_exceptions(
    stock: pd.DataFrame,
    gl: pd.DataFrame,
    config: ReconForgeConfig,
) -> tuple[pd.DataFrame, set[int], set[int]]:
    rows: list[dict[str, object]] = []
    invalid_stock: set[int] = set()
    invalid_gl: set[int] = set()
    for dataset, frame, field, identifier, invalid_indices in (
        ("stock_moves", stock, "total_cost", "move_id", invalid_stock),
        ("gl_entries", gl, "amount", "entry_id", invalid_gl),
    ):
        raw_column = f"_reconforge_raw_{field}"
        for raw_index, row in frame.iterrows():
            index = int(cast(int, raw_index))
            try:
                parse_amount(row.get(field))
            except InvalidAmountError:
                invalid_indices.add(index)
                raw_value = row.get(raw_column, row.get(field))
                rows.append(
                    {
                        "source_dataset": dataset,
                        "source_row": index + 2,
                        "field": field,
                        "invalid_value": "" if pd.isna(raw_value) else str(raw_value),
                        identifier: row.get(identifier),
                        "amount_impact": 0.0,
                    },
                )
    quality = pd.DataFrame(rows)
    if quality.empty:
        quality = pd.DataFrame(
            columns=["source_dataset", "source_row", "field", "invalid_value", "move_id", "entry_id", "amount_impact"],
        )
    return _risk_columns(quality, "data_quality", config, "amount_impact"), invalid_stock, invalid_gl


def _build_match_rows(
    stock_moves: pd.DataFrame, gl_entries: pd.DataFrame, matches: list[MatchCandidate], config: ReconForgeConfig
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for match in matches:
        stock = cast("pd.Series[Any]", stock_moves.loc[match.stock_index])
        gl = cast("pd.Series[Any]", gl_entries.loc[match.gl_index])
        stock_amount = parse_amount(stock.get("total_cost"))
        gl_amount = parse_amount(gl.get("amount"))
        value_difference = round(stock_amount - gl_amount, 2)
        stock_date = stock.get("date")
        gl_date = gl.get("date")
        date_difference = match.date_difference
        assessment = assess_risk(
            "value_difference" if match.match_level == "Value Difference" else "matched",
            config,
            amount=stock_amount,
            amount_difference=abs(value_difference),
        )
        rows.append(
            {
                "move_id": stock.get("move_id"),
                "entry_id": gl.get("entry_id"),
                "match_id": match.match_id,
                "stock_date": stock.get("date"),
                "gl_date": gl.get("date"),
                "source_document": stock.get("source_document"),
                "gl_reference": gl.get("reference"),
                "source_document_normalized": normalize_reference(stock.get("source_document")),
                "gl_reference_normalized": normalize_reference(gl.get("reference")),
                "work_order": stock.get("work_order"),
                "product_code": stock.get("product_code"),
                "product_name": stock.get("product_name"),
                "stock_amount": stock_amount,
                "gl_amount": gl_amount,
                "value_difference": value_difference,
                "date_difference_days": date_difference,
                "match_level": match.match_level,
                "confidence_score": match.confidence,
                "reference_similarity": match.reference_similarity,
                "match_reason": match.reason,
                "review_required": match.review_required,
                "risk_score": assessment.score if match.match_level == "Value Difference" else 0,
                "risk_level": assessment.level if match.match_level == "Value Difference" else "Low",
            },
        )
    return pd.DataFrame(rows)


def _summary_frame(result_frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = [
        {"metric": "matched_transactions", "count": len(result_frames["matched_transactions"])},
        {"metric": "stock_without_gl", "count": len(result_frames["stock_without_gl"])},
        {"metric": "gl_without_stock", "count": len(result_frames["gl_without_stock"])},
        {"metric": "value_differences", "count": len(result_frames["value_differences"])},
        {"metric": "date_differences", "count": len(result_frames["date_differences"])},
        {"metric": "reference_mismatches", "count": len(result_frames["reference_mismatches"])},
    ]
    return pd.DataFrame(rows)


def reconcile_stock_gl(
    stock_moves: pd.DataFrame,
    gl_entries: pd.DataFrame,
    config: ReconForgeConfig,
    matching_strategy: MatchingStrategy = "standard",
) -> StockGLReconciliationResult:
    """Reconcile stock movements against GL postings."""

    stock = stock_moves.reset_index(drop=True).copy()
    gl = gl_entries.reset_index(drop=True).copy()
    data_quality, invalid_stock_indices, invalid_gl_indices = _data_quality_exceptions(stock, gl, config)
    matchable_stock = stock[~stock.index.isin(invalid_stock_indices)]
    matchable_gl = gl[~gl.index.isin(invalid_gl_indices)]
    matches = match_stock_to_gl(matchable_stock, matchable_gl, config, strategy=matching_strategy)
    matched_indices = {match.stock_index for match in matches}
    matched_gl_indices = {match.gl_index for match in matches}

    matched = _build_match_rows(stock, gl, matches, config)
    if matched.empty:
        matched = pd.DataFrame(
            columns=[
                "move_id",
                "entry_id",
                "match_id",
                "stock_date",
                "gl_date",
                "source_document",
                "gl_reference",
                "source_document_normalized",
                "gl_reference_normalized",
                "work_order",
                "product_code",
                "product_name",
                "stock_amount",
                "gl_amount",
                "value_difference",
                "date_difference_days",
                "match_level",
                "confidence_score",
                "reference_similarity",
                "match_reason",
                "review_required",
                "risk_score",
                "risk_level",
            ],
        )

    value_differences = _risk_columns(
        matched[matched["match_level"].eq("Value Difference")].copy(),
        "value_difference",
        config,
        "stock_amount",
        "value_difference",
    )
    date_differences = _risk_columns(
        matched[matched["date_difference_days"].fillna(0).astype(int).gt(0)].copy(),
        "date_difference",
        config,
        "stock_amount",
    )
    reference_mismatches = _risk_columns(
        matched[
            matched["source_document_normalized"].astype(str).ne(matched["gl_reference_normalized"].astype(str))
        ].copy(),
        "reference_mismatch",
        config,
        "stock_amount",
        "value_difference",
    )

    stock_without = stock[~stock.index.isin(matched_indices | invalid_stock_indices)].copy()
    gl_without = gl[~gl.index.isin(matched_gl_indices | invalid_gl_indices)].copy()
    stock_without = _risk_columns(stock_without, "stock_without_gl", config, "total_cost")
    gl_without = _risk_columns(gl_without, "gl_without_stock", config, "amount")

    exception_frames = [
        stock_without,
        gl_without,
        value_differences,
        date_differences,
        reference_mismatches,
        data_quality,
    ]
    non_empty_exceptions = [frame for frame in exception_frames if not frame.empty]
    all_exceptions = (
        pd.concat(non_empty_exceptions, ignore_index=True, sort=False)
        if non_empty_exceptions
        else pd.DataFrame(
            columns=[
                "exception_id",
                "exception_type",
                "exception_reason",
                "evidence_reference",
                "risk_score",
                "risk_level",
            ],
        )
    )

    result_frames = {
        "matched_transactions": matched,
        "stock_without_gl": stock_without,
        "gl_without_stock": gl_without,
        "value_differences": value_differences,
        "date_differences": date_differences,
        "reference_mismatches": reference_mismatches,
        "data_quality_exceptions": data_quality,
    }
    summary = _summary_frame(result_frames)
    return StockGLReconciliationResult(
        matched_transactions=matched,
        stock_without_gl=stock_without,
        gl_without_stock=gl_without,
        value_differences=value_differences,
        date_differences=date_differences,
        reference_mismatches=reference_mismatches,
        data_quality_exceptions=data_quality,
        all_exceptions=all_exceptions,
        summary=summary,
    )


def result_frames(result: StockGLReconciliationResult) -> dict[str, pd.DataFrame]:
    """Return stock-GL result frames for writing."""

    return {
        "summary": result.summary,
        "matched_transactions": result.matched_transactions,
        "stock_without_gl": result.stock_without_gl,
        "gl_without_stock": result.gl_without_stock,
        "value_differences": result.value_differences,
        "date_differences": result.date_differences,
        "reference_mismatches": result.reference_mismatches,
        "data_quality_exceptions": result.data_quality_exceptions,
        "all_exceptions": result.all_exceptions,
    }
