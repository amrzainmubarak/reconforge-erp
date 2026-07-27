"""Deterministic reconciliation signatures for engine parity checks."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from decimal import Decimal
from numbers import Integral
from typing import Any, Literal

import pandas as pd
from pandas.api.types import is_float

from reconforge.reconciliation.matching import RECORD_IDENTITY_POLICY
from reconforge.utils.money import InvalidAmountError, parse_exact_amount

RECONCILIATION_SIGNATURE_V1: Literal["reconciliation-signature-v1"] = (
    "reconciliation-signature-v1"
)
RECONCILIATION_SIGNATURE_V2: Literal["reconciliation-signature-v2"] = (
    "reconciliation-signature-v2"
)
RECONCILIATION_SIGNATURE_V3: Literal["reconciliation-signature-v3"] = (
    "reconciliation-signature-v3"
)
ReconciliationSignatureVersion = Literal[
    "reconciliation-signature-v1",
    "reconciliation-signature-v2",
    "reconciliation-signature-v3",
]
CURRENT_RECONCILIATION_SIGNATURE_VERSION: ReconciliationSignatureVersion = (
    RECONCILIATION_SIGNATURE_V3
)

_FINANCIAL_MATCH_COLUMNS = frozenset({"stock_amount", "gl_amount", "value_difference"})


class InvalidReconciliationSignatureValueError(ValueError):
    """Raised when a strict signature receives a non-canonical financial value."""


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
    if isinstance(value, Decimal):
        if not value.is_finite():
            return str(value)
        normalized = Decimal("0") if value == 0 else value.normalize()
        return format(normalized, "f")
    if isinstance(value, (int, float, bool, str)):
        return value
    return str(value)


def _canonical_financial_value(value: Any, *, column: str) -> str | None:
    """Canonicalize exact financial values while rejecting binary floating-point ingress."""

    if is_float(value):
        raise InvalidReconciliationSignatureValueError(
            f"financial signature column '{column}' cannot contain a binary floating-point value"
        )
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, bool):
        raise InvalidReconciliationSignatureValueError(
            f"financial signature column '{column}' cannot contain a boolean value"
        )
    if isinstance(value, Decimal):
        parsed = value
    elif isinstance(value, Integral):
        parsed = Decimal(int(value))
    elif isinstance(value, str):
        try:
            parsed = parse_exact_amount(value)
        except InvalidAmountError as exc:
            raise InvalidReconciliationSignatureValueError(
                f"financial signature column '{column}' must contain a finite exact amount"
            ) from exc
    else:
        raise InvalidReconciliationSignatureValueError(
            f"financial signature column '{column}' must contain Decimal, integer, or exact text"
        )
    if not parsed.is_finite():
        raise InvalidReconciliationSignatureValueError(
            f"financial signature column '{column}' must contain a finite exact amount"
        )
    normalized = Decimal("0") if parsed == 0 else parsed.normalize()
    return format(normalized, "f")


def _frame_signature(
    frame: pd.DataFrame,
    columns: list[str],
    *,
    strict_financial_columns: frozenset[str] = frozenset(),
) -> list[list[Any]]:
    if frame.empty:
        return []
    selected = [column for column in columns if column in frame.columns]
    if not selected:
        selected = sorted(frame.columns)
    normalized = frame[selected].copy()
    rows: list[list[Any]] = []
    for row in normalized.itertuples(index=False, name=None):
        rows.append(
            [
                _canonical_financial_value(value, column=column)
                if column in strict_financial_columns
                else _canonical_value(value)
                for column, value in zip(selected, row, strict=True)
            ]
        )
    rows.sort(key=lambda item: ["" if value is None else str(value) for value in item])
    return rows


def build_reconciliation_signature(
    *,
    matched_transactions: pd.DataFrame,
    all_exceptions: pd.DataFrame,
    signature_version: ReconciliationSignatureVersion = CURRENT_RECONCILIATION_SIGNATURE_VERSION,
) -> str:
    """Build a versioned stable reconciliation fingerprint for parity validation.

    Version 1 reproduces the historical generic serializer. Version 2 rejects
    binary floating-point values in financial result columns and canonicalizes
    exact financial values before hashing. Version 3 retains that financial
    contract, includes canonical record-instance identity, and excludes mutable
    source location.
    """

    if signature_version not in {
        RECONCILIATION_SIGNATURE_V1,
        RECONCILIATION_SIGNATURE_V2,
        RECONCILIATION_SIGNATURE_V3,
    }:
        raise ValueError(f"unsupported reconciliation signature version: {signature_version}")
    strict_financial_columns = (
        _FINANCIAL_MATCH_COLUMNS
        if signature_version in {RECONCILIATION_SIGNATURE_V2, RECONCILIATION_SIGNATURE_V3}
        else frozenset()
    )

    match_columns = [
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
    ]
    exception_columns = [
        "exception_id",
        "exception_type",
        "source_dataset",
        "source_row",
        "field",
        "evidence_reference",
        "risk_score",
        "risk_level",
        "match_id",
    ]
    if signature_version == RECONCILIATION_SIGNATURE_V3:
        match_columns.extend(
            [
                "stock_record_instance_id",
                "gl_record_instance_id",
                "stock_duplicate_ordinal",
                "gl_duplicate_ordinal",
                "stock_duplicate_count",
                "gl_duplicate_count",
                "record_identity_policy",
            ]
        )
        exception_columns = [
            "exception_id",
            "exception_type",
            "source_dataset",
            "record_instance_id",
            "stock_record_instance_id",
            "gl_record_instance_id",
            "duplicate_ordinal",
            "duplicate_count",
            "record_identity_policy",
            "field",
            "evidence_reference",
            "risk_score",
            "risk_level",
            "match_id",
        ]

    match_signature = _frame_signature(
        matched_transactions,
        match_columns,
        strict_financial_columns=strict_financial_columns,
    )
    exception_signature = _frame_signature(
        all_exceptions,
        exception_columns,
    )
    payload: dict[str, object] = {
        "matched": match_signature,
        "exceptions": exception_signature,
    }
    if signature_version in {RECONCILIATION_SIGNATURE_V2, RECONCILIATION_SIGNATURE_V3}:
        payload["signature_version"] = signature_version
    if signature_version == RECONCILIATION_SIGNATURE_V3:
        payload["record_identity_policy"] = RECORD_IDENTITY_POLICY
    digest = hashlib.sha256(json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return digest
