"""Rule operator registry for documentation, validation, and Studio display."""

from __future__ import annotations

from dataclasses import dataclass

from reconforge.rules.operators import SUPPORTED_OPERATORS


@dataclass(frozen=True)
class OperatorInfo:
    """Human-readable operator metadata."""

    name: str
    description: str


_DESCRIPTIONS: dict[str, str] = {
    "equals": "Field equals a literal value or another field.",
    "not_equals": "Field does not equal a literal value or another field.",
    "contains": "Field text contains a value.",
    "not_contains": "Field text does not contain a value.",
    "exists": "Field is populated.",
    "missing": "Field is blank or null-like.",
    "greater_than": "Numeric field is greater than a value.",
    "less_than": "Numeric field is less than a value.",
    "greater_or_equal": "Numeric field is greater than or equal to a value.",
    "less_or_equal": "Numeric field is less than or equal to a value.",
    "in_list": "Field is in an allowed list.",
    "not_in_list": "Field is not in a blocked list.",
    "amount_within_tolerance": "Numeric field and value are within tolerance.",
    "date_within_days": "Date field and value are within a day tolerance.",
    "regex_match": "Field matches a regular expression.",
    "starts_with": "Field starts with a value.",
    "ends_with": "Field ends with a value.",
    "duplicate": "Field value appears more than once in the source file.",
    "unique": "Field value appears exactly once in the source file.",
    "cross_file_exists": "A referenced value exists in another input file.",
    "cross_file_missing": "A referenced value is missing in another input file.",
    "sum_matches": "Related file totals match a source value within tolerance.",
    "variance_above": "Absolute variance between field and value exceeds threshold.",
    "aging_bucket": "Date age is greater than or equal to a bucket threshold.",
    "before_date": "Date field is before another date or field.",
    "after_date": "Date field is after another date or field.",
    "and": "All nested conditions must pass.",
    "or": "Any nested condition may pass.",
    "not": "Nested condition must not pass.",
}


def list_operators() -> list[OperatorInfo]:
    """Return supported operators with descriptions."""

    return [OperatorInfo(name=name, description=_DESCRIPTIONS.get(name, "Supported rule operator.")) for name in sorted(SUPPORTED_OPERATORS)]


def operator_names() -> set[str]:
    """Return supported operator names."""

    return set(SUPPORTED_OPERATORS)
