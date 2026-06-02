"""Rule condition operators."""

from __future__ import annotations

import re
from datetime import date

import pandas as pd

from reconforge.rules.models import Condition
from reconforge.utils.dates import days_between
from reconforge.utils.money import within_tolerance


def is_missing(value: object) -> bool:
    """Return true when a cell should be treated as missing."""

    if value is None:
        return True
    text = str(value).strip()
    return text == "" or text.lower() in {"nan", "nat", "none", "null"}


def _value(row: pd.Series, condition: Condition) -> object:
    if condition.field is None:
        return None
    return row.get(condition.field)


def _right_value(row: pd.Series, condition: Condition) -> object:
    if condition.other_field:
        return row.get(condition.other_field)
    return condition.value


def _as_float(value: object) -> float:
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return 0.0


def _as_date(value: object) -> date | None:
    if is_missing(value):
        return None
    parsed = pd.to_datetime(str(value), errors="coerce")
    if not isinstance(parsed, pd.Timestamp) or pd.isna(parsed):
        return None
    return parsed.date()


def evaluate_condition(
    row: pd.Series,
    condition: Condition,
    *,
    frame: pd.DataFrame | None = None,
    related_frames: dict[str, pd.DataFrame] | None = None,
) -> bool:
    """Evaluate a condition against a row."""

    operator = condition.operator.lower()
    left = _value(row, condition)
    right = _right_value(row, condition)

    if operator == "and":
        return all(evaluate_condition(row, child, frame=frame, related_frames=related_frames) for child in condition.conditions)
    if operator == "or":
        return any(evaluate_condition(row, child, frame=frame, related_frames=related_frames) for child in condition.conditions)
    if operator == "not":
        return not any(evaluate_condition(row, child, frame=frame, related_frames=related_frames) for child in condition.conditions)

    if operator == "exists":
        return not is_missing(left)
    if operator == "missing":
        return is_missing(left)
    if operator == "equals":
        return str(left).strip() == str(right).strip()
    if operator == "not_equals":
        return str(left).strip() != str(right).strip()
    if operator == "contains":
        return str(right).lower() in str(left).lower()
    if operator == "not_contains":
        return str(right).lower() not in str(left).lower()
    if operator == "starts_with":
        return str(left).startswith(str(right))
    if operator == "ends_with":
        return str(left).endswith(str(right))
    if operator == "greater_than":
        return _as_float(left) > _as_float(right)
    if operator == "less_than":
        return _as_float(left) < _as_float(right)
    if operator == "greater_or_equal":
        return _as_float(left) >= _as_float(right)
    if operator == "less_or_equal":
        return _as_float(left) <= _as_float(right)
    if operator == "in_list":
        values = condition.value if isinstance(condition.value, list) else []
        return str(left) in {str(value) for value in values}
    if operator == "not_in_list":
        values = condition.value if isinstance(condition.value, list) else []
        return str(left) not in {str(value) for value in values}
    if operator == "amount_within_tolerance":
        return within_tolerance(_as_float(left), _as_float(right), float(condition.tolerance or 0.0))
    if operator == "date_within_days":
        diff = days_between(_as_date(left), _as_date(right))
        return diff is not None and diff <= int(condition.days or 0)
    if operator == "regex_match":
        return re.search(str(right), str(left)) is not None
    if operator == "before_date":
        left_date = _as_date(left)
        right_date = _as_date(right)
        return left_date is not None and right_date is not None and left_date < right_date
    if operator == "after_date":
        left_date = _as_date(left)
        right_date = _as_date(right)
        return left_date is not None and right_date is not None and left_date > right_date
    if operator == "variance_above":
        variance = abs(_as_float(left) - _as_float(right))
        threshold = condition.threshold if condition.threshold is not None else condition.value
        return variance > _as_float(threshold)
    if operator == "aging_bucket":
        left_date = _as_date(left)
        if left_date is None:
            return False
        return days_between(left_date, date.today()) is not None and (days_between(left_date, date.today()) or 0) >= int(
            condition.bucket_days or condition.days or condition.value or 0,
        )
    if operator == "duplicate":
        if frame is None or condition.field is None or condition.field not in frame.columns:
            return False
        value = row.get(condition.field)
        if is_missing(value):
            return False
        return int(frame[condition.field].astype(str).eq(str(value)).sum()) > 1
    if operator == "unique":
        if frame is None or condition.field is None or condition.field not in frame.columns:
            return False
        value = row.get(condition.field)
        if is_missing(value):
            return False
        return int(frame[condition.field].astype(str).eq(str(value)).sum()) == 1
    if operator in {"cross_file_exists", "cross_file_missing"}:
        if related_frames is None or condition.target_file is None:
            return operator == "cross_file_missing"
        target = related_frames.get(condition.target_file)
        source_field = condition.source_key or condition.field
        target_field = condition.target_key or condition.target_field
        if target is None or source_field is None or target_field is None or target_field not in target.columns:
            return operator == "cross_file_missing"
        source_value = row.get(source_field)
        exists = not is_missing(source_value) and bool(target[target_field].astype(str).eq(str(source_value)).any())
        return exists if operator == "cross_file_exists" else not exists
    if operator == "sum_matches":
        if related_frames is None or condition.target_file is None:
            return False
        target = related_frames.get(condition.target_file)
        source_key = condition.source_key or "work_order"
        target_key = condition.target_key or source_key
        aggregate_field = condition.aggregate_field or condition.target_field
        if target is None or aggregate_field is None or target_key not in target.columns or aggregate_field not in target.columns:
            return False
        source_value = row.get(source_key)
        total = pd.to_numeric(target[target[target_key].astype(str).eq(str(source_value))][aggregate_field], errors="coerce").fillna(0).sum()
        expected = _as_float(left if condition.field else condition.value)
        return within_tolerance(float(total), expected, float(condition.tolerance or 0.0))
    raise ValueError(f"Unsupported rule operator: {condition.operator}")


SUPPORTED_OPERATORS = {
    "equals",
    "not_equals",
    "contains",
    "not_contains",
    "exists",
    "missing",
    "greater_than",
    "less_than",
    "greater_or_equal",
    "less_or_equal",
    "in_list",
    "not_in_list",
    "amount_within_tolerance",
    "date_within_days",
    "regex_match",
    "starts_with",
    "ends_with",
    "duplicate",
    "unique",
    "cross_file_exists",
    "cross_file_missing",
    "sum_matches",
    "variance_above",
    "aging_bucket",
    "before_date",
    "after_date",
    "and",
    "or",
    "not",
}
