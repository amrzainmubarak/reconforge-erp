"""Deterministic reconciliation signatures for engine parity checks."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Any

import pandas as pd


def _canonical_value(value: Any) -> str | int | float | bool | None:
    if value is None:
        return None
    if isinstance(value, (pd.Timestamp, date)):
        return str(value)
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, (int, float, bool, str)):
        return value
    return str(value)


def _frame_signature(frame: pd.DataFrame, columns: list[str]) -> list[list[Any]]:
    if frame.empty:
        return []
    selected = [column for column in columns if column in frame.columns]
    if not selected:
        selected = sorted(frame.columns)
    normalized = frame[selected].copy()
    normalized = normalized.fillna(value=None)
    rows: list[list[Any]] = []
    for row in normalized.itertuples(index=False, name=None):
        rows.append([_canonical_value(value) for value in row])
    rows.sort(key=lambda item: ["" if value is None else str(value) for value in item])
    return rows


def build_reconciliation_signature(*, matched_transactions: pd.DataFrame, all_exceptions: pd.DataFrame) -> str:
    """Build a stable reconciliation fingerprint for parity validation."""

    match_signature = _frame_signature(
        matched_transactions,
        [
            "match_id",
            "move_id",
            "entry_id",
            "match_level",
            "confidence_score",
            "stock_amount",
            "gl_amount",
            "value_difference",
            "date_difference_days",
            "reference_similarity",
            "source_document",
            "gl_reference",
        ],
    )
    exception_signature = _frame_signature(
        all_exceptions,
        [
            "exception_id",
            "exception_type",
            "source_dataset",
            "source_row",
            "field",
            "evidence_reference",
            "risk_score",
            "risk_level",
            "match_id",
        ],
    )
    payload = {
        "matched": match_signature,
        "exceptions": exception_signature,
    }
    digest = hashlib.sha256(json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return digest
