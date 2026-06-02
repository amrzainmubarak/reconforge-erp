"""Stock movement to GL reconciliation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

import pandas as pd

from reconforge.config import ReconForgeConfig
from reconforge.reconciliation.matching import MatchCandidate, MatchingStrategy, match_stock_to_gl
from reconforge.reconciliation.risk import assess_risk
from reconforge.utils.dates import days_between


@dataclass(frozen=True)
class StockGLReconciliationResult:
    """Output frames from stock-vs-GL reconciliation."""

    matched_transactions: pd.DataFrame
    stock_without_gl: pd.DataFrame
    gl_without_stock: pd.DataFrame
    value_differences: pd.DataFrame
    date_differences: pd.DataFrame
    reference_mismatches: pd.DataFrame
    all_exceptions: pd.DataFrame
    summary: pd.DataFrame


def _risk_columns(frame: pd.DataFrame, exception_type: str, config: ReconForgeConfig, amount_column: str) -> pd.DataFrame:
    enriched = frame.copy()
    scores: list[int] = []
    levels: list[str] = []
    for _, row in enriched.iterrows():
        assessment = assess_risk(exception_type, config, amount=float(row.get(amount_column, 0.0) or 0.0))
        scores.append(assessment.score)
        levels.append(assessment.level)
    enriched["exception_type"] = exception_type
    enriched["risk_score"] = scores
    enriched["risk_level"] = levels
    return enriched


def _build_match_rows(stock_moves: pd.DataFrame, gl_entries: pd.DataFrame, matches: list[MatchCandidate], config: ReconForgeConfig) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for match in matches:
        stock = cast("pd.Series[Any]", stock_moves.loc[match.stock_index])
        gl = cast("pd.Series[Any]", gl_entries.loc[match.gl_index])
        stock_amount = float(stock.get("total_cost", 0.0) or 0.0)
        gl_amount = float(gl.get("amount", 0.0) or 0.0)
        value_difference = round(stock_amount - gl_amount, 2)
        stock_date = stock.get("date")
        gl_date = gl.get("date")
        date_difference = days_between(cast(Any, stock_date), cast(Any, gl_date)) or 0
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
    matches = match_stock_to_gl(stock, gl, config, strategy=matching_strategy)
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

    value_differences = matched[matched["match_level"].eq("Value Difference")].copy()
    date_differences = matched[matched["date_difference_days"].fillna(0).astype(int).gt(0)].copy()
    reference_mismatches = matched[matched["source_document"].astype(str).ne(matched["gl_reference"].astype(str))].copy()

    stock_without = stock[~stock.index.isin(matched_indices)].copy()
    gl_without = gl[~gl.index.isin(matched_gl_indices)].copy()
    stock_without = _risk_columns(stock_without, "stock_without_gl", config, "total_cost")
    gl_without = _risk_columns(gl_without, "gl_without_stock", config, "amount")

    exception_frames = [
        stock_without,
        gl_without,
        value_differences.assign(exception_type="value_difference"),
        reference_mismatches.assign(exception_type="reference_mismatch"),
    ]
    all_exceptions = pd.concat([frame for frame in exception_frames if not frame.empty], ignore_index=True, sort=False)

    result_frames = {
        "matched_transactions": matched,
        "stock_without_gl": stock_without,
        "gl_without_stock": gl_without,
        "value_differences": value_differences,
        "date_differences": date_differences,
        "reference_mismatches": reference_mismatches,
    }
    summary = _summary_frame(result_frames)
    return StockGLReconciliationResult(
        matched_transactions=matched,
        stock_without_gl=stock_without,
        gl_without_stock=gl_without,
        value_differences=value_differences,
        date_differences=date_differences,
        reference_mismatches=reference_mismatches,
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
        "all_exceptions": result.all_exceptions,
    }
