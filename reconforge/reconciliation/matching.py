"""Stock-to-GL matching logic."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from difflib import SequenceMatcher
from re import sub
from typing import Any, Literal, cast

import pandas as pd

from reconforge.config import ReconForgeConfig
from reconforge.utils.dates import days_between
from reconforge.utils.money import money_difference, within_tolerance

MatchLevel = Literal[
    "Level 1 Exact",
    "Level 2 Normalized Reference",
    "Level 2 Fuzzy Reference",
    "Level 3 Amount/Date Proximity",
    "Value Difference",
]
MatchingStrategy = Literal["standard", "strict", "aggressive", "audit-safe"]


@dataclass(frozen=True)
class MatchCandidate:
    """A matched stock and GL pair."""

    stock_index: int
    gl_index: int
    match_level: MatchLevel
    confidence: float
    reason: str
    match_id: str = ""
    stock_move_id: str = ""
    gl_entry_id: str = ""
    amount_difference: float = 0.0
    date_difference: int = 0
    reference_similarity: float = 0.0
    review_required: bool = False


def _string(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"nan", "nat", "none"} else text


def _amount(value: object) -> float:
    if value is None:
        return 0.0
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return 0.0


def _date(value: object) -> date | None:
    if value is None:
        return None
    text = str(value).strip()
    if text == "" or text.lower() in {"nan", "nat", "none"}:
        return None
    if isinstance(value, pd.Timestamp):
        return value.date()
    if isinstance(value, date):
        return value
    parsed = pd.to_datetime(text, errors="coerce")
    if not isinstance(parsed, pd.Timestamp):
        return None
    if pd.isna(parsed):
        return None
    return parsed.date()


def normalize_reference(value: object) -> str:
    """Normalize an ERP reference for matching."""

    return sub(r"[^A-Z0-9]", "", _string(value).upper())


def reference_similarity(left: object, right: object) -> float:
    """Return normalized text similarity from 0 to 1."""

    left_norm = normalize_reference(left)
    right_norm = normalize_reference(right)
    if not left_norm or not right_norm:
        return 0.0
    if left_norm in right_norm or right_norm in left_norm:
        return 0.94
    return round(SequenceMatcher(None, left_norm, right_norm).ratio(), 4)


def is_exact_match(stock_row: pd.Series, gl_row: pd.Series) -> bool:
    """Return true when a pair meets Level 1 exact matching criteria."""

    return (
        _string(stock_row.get("source_document")) == _string(gl_row.get("reference"))
        and _string(stock_row.get("work_order")) == _string(gl_row.get("work_order"))
        and money_difference(_amount(stock_row.get("total_cost")), _amount(gl_row.get("amount"))) <= 0.01
    )


def is_fuzzy_reference_match(stock_row: pd.Series, gl_row: pd.Series, config: ReconForgeConfig) -> bool:
    """Return true when a pair meets Level 2 fuzzy reference criteria."""

    source_document = _string(stock_row.get("source_document"))
    reference = _string(gl_row.get("reference"))
    if not source_document or not reference:
        return False
    reference_match = source_document in reference or reference in source_document
    return (
        reference_match
        and _string(stock_row.get("work_order")) == _string(gl_row.get("work_order"))
        and within_tolerance(_amount(stock_row.get("total_cost")), _amount(gl_row.get("amount")), config.amount_tolerance)
    )


def is_normalized_reference_match(stock_row: pd.Series, gl_row: pd.Series, config: ReconForgeConfig) -> bool:
    """Return true when normalized references and work order/amount agree."""

    return (
        normalize_reference(stock_row.get("source_document")) == normalize_reference(gl_row.get("reference"))
        and _string(stock_row.get("work_order")) == _string(gl_row.get("work_order"))
        and within_tolerance(_amount(stock_row.get("total_cost")), _amount(gl_row.get("amount")), config.amount_tolerance)
    )


def is_proximity_match(stock_row: pd.Series, gl_row: pd.Series, config: ReconForgeConfig) -> bool:
    """Return true when a pair meets Level 3 amount/date proximity criteria."""

    stock_date = _date(stock_row.get("date"))
    gl_date = _date(gl_row.get("date"))
    day_difference = days_between(stock_date, gl_date)
    return (
        _string(stock_row.get("work_order")) == _string(gl_row.get("work_order"))
        and within_tolerance(_amount(stock_row.get("total_cost")), _amount(gl_row.get("amount")), config.amount_tolerance)
        and day_difference is not None
        and day_difference <= config.date_tolerance_days
    )


def is_value_difference(stock_row: pd.Series, gl_row: pd.Series, config: ReconForgeConfig) -> bool:
    """Return true when a pair has the same source/work order but a material amount difference."""

    return (
        _string(stock_row.get("source_document")) == _string(gl_row.get("reference"))
        and _string(stock_row.get("work_order")) == _string(gl_row.get("work_order"))
        and money_difference(_amount(stock_row.get("total_cost")), _amount(gl_row.get("amount"))) > config.amount_tolerance
    )


def _best_candidate(
    stock_index: int,
    stock_row: pd.Series,
    gl_frame: pd.DataFrame,
    available_gl: set[int],
    config: ReconForgeConfig,
    strategy: MatchingStrategy,
) -> MatchCandidate | None:
    minimum_similarity = {"strict": 0.98, "standard": 0.88, "aggressive": 0.76, "audit-safe": 0.93}[strategy]
    allow_proximity = strategy != "strict"
    allow_value_difference = strategy in {"standard", "aggressive", "audit-safe"}

    for gl_index in sorted(available_gl):
        gl_row = cast("pd.Series[Any]", gl_frame.loc[gl_index])
        if is_exact_match(stock_row, gl_row):
            return _candidate(stock_index, stock_row, gl_index, gl_row, "Level 1 Exact", 1.0, "source_document, work_order, and amount match", False)

    for gl_index in sorted(available_gl):
        gl_row = cast("pd.Series[Any]", gl_frame.loc[gl_index])
        if is_normalized_reference_match(stock_row, gl_row, config):
            return _candidate(
                stock_index,
                stock_row,
                gl_index,
                gl_row,
                "Level 2 Normalized Reference",
                0.92,
                "normalized references match with same work_order and amount tolerance",
                strategy == "audit-safe",
            )

    for gl_index in sorted(available_gl):
        gl_row = cast("pd.Series[Any]", gl_frame.loc[gl_index])
        similarity = reference_similarity(stock_row.get("source_document"), gl_row.get("reference"))
        if is_fuzzy_reference_match(stock_row, gl_row, config) and similarity >= minimum_similarity:
            return _candidate(
                stock_index,
                stock_row,
                gl_index,
                gl_row,
                "Level 2 Fuzzy Reference",
                0.86 if strategy != "aggressive" else 0.78,
                "reference contains or resembles source_document with same work_order and amount tolerance",
                strategy in {"audit-safe", "aggressive"},
            )

    if allow_proximity:
        for gl_index in sorted(available_gl):
            gl_row = cast("pd.Series[Any]", gl_frame.loc[gl_index])
            if is_proximity_match(stock_row, gl_row, config):
                confidence = 0.72 if strategy != "audit-safe" else 0.67
                return _candidate(
                    stock_index,
                    stock_row,
                    gl_index,
                    gl_row,
                    "Level 3 Amount/Date Proximity",
                    confidence,
                    "same work_order with amount and date proximity",
                    True,
                )

    if allow_value_difference:
        for gl_index in sorted(available_gl):
            gl_row = cast("pd.Series[Any]", gl_frame.loc[gl_index])
            if is_value_difference(stock_row, gl_row, config):
                return _candidate(
                    stock_index,
                    stock_row,
                    gl_index,
                    gl_row,
                    "Value Difference",
                    0.66,
                    "same source_document and work_order with amount outside tolerance",
                    True,
                )

    return None


def _candidate(
    stock_index: int,
    stock_row: pd.Series,
    gl_index: int,
    gl_row: pd.Series,
    level: MatchLevel,
    confidence: float,
    reason: str,
    review_required: bool,
) -> MatchCandidate:
    stock_amount = _amount(stock_row.get("total_cost"))
    gl_amount = _amount(gl_row.get("amount"))
    date_difference = days_between(_date(stock_row.get("date")), _date(gl_row.get("date"))) or 0
    stock_move_id = _string(stock_row.get("move_id"))
    gl_entry_id = _string(gl_row.get("entry_id"))
    return MatchCandidate(
        match_id=f"MATCH-{stock_index + 1:06d}-{gl_index + 1:06d}",
        stock_index=stock_index,
        gl_index=gl_index,
        stock_move_id=stock_move_id,
        gl_entry_id=gl_entry_id,
        match_level=level,
        confidence=confidence,
        amount_difference=round(stock_amount - gl_amount, 2),
        date_difference=date_difference,
        reference_similarity=reference_similarity(stock_row.get("source_document"), gl_row.get("reference")),
        reason=reason,
        review_required=review_required,
    )


def match_stock_to_gl(
    stock_moves: pd.DataFrame,
    gl_entries: pd.DataFrame,
    config: ReconForgeConfig,
    strategy: MatchingStrategy = "standard",
) -> list[MatchCandidate]:
    """Run matching levels against stock movements and GL entries."""

    if strategy not in {"standard", "strict", "aggressive", "audit-safe"}:
        raise ValueError("matching strategy must be one of: standard, strict, aggressive, audit-safe")
    matches: list[MatchCandidate] = []
    available_gl = {int(cast(int, index)) for index in gl_entries.index}
    for raw_stock_index, stock_row in stock_moves.iterrows():
        if not available_gl:
            break
        stock_index = int(cast(int, raw_stock_index))
        candidate = _best_candidate(stock_index, cast("pd.Series[Any]", stock_row), gl_entries, available_gl, config, strategy)
        if candidate is None:
            continue
        matches.append(candidate)
        available_gl.remove(candidate.gl_index)
    return matches
