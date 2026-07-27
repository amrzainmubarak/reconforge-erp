from __future__ import annotations

from decimal import Decimal

import pandas as pd
import pytest

from reconforge.engines.signature import (
    CURRENT_RECONCILIATION_SIGNATURE_VERSION,
    RECONCILIATION_SIGNATURE_V1,
    RECONCILIATION_SIGNATURE_V2,
    RECONCILIATION_SIGNATURE_V3,
    InvalidReconciliationSignatureValueError,
    build_reconciliation_signature,
)


def _matched_row(**overrides: object) -> pd.DataFrame:
    row: dict[str, object] = {
        "match_id": "M-1",
        "move_id": "S-1",
        "entry_id": "G-1",
        "match_level": "exact",
        "confidence_score": 0.875,
        "stock_amount": Decimal("1.250"),
        "gl_amount": Decimal("1.25"),
        "value_difference": Decimal("0.00"),
        "date_difference_days": 0,
        "reference_similarity": 0.5,
        "source_document": "INV-1",
        "gl_reference": "INV-1",
    }
    row.update(overrides)
    return pd.DataFrame([row])


def _exception_row() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "exception_id": "E-1",
                "exception_type": "data_quality",
                "source_dataset": "stock_moves",
                "source_row": 2,
                "field": "total_cost",
                "evidence_reference": "source.csv:2",
                "risk_score": 50,
                "risk_level": "medium",
                "match_id": None,
            }
        ]
    )


def _signature(frame: pd.DataFrame, *, version: str = CURRENT_RECONCILIATION_SIGNATURE_VERSION) -> str:
    return build_reconciliation_signature(
        matched_transactions=frame,
        all_exceptions=_exception_row(),
        signature_version=version,  # type: ignore[arg-type]
    )


def test_signature_v1_preserves_historical_digest_and_float_compatibility() -> None:
    frame = _matched_row(stock_amount=1.25, value_difference="0.00")

    assert _signature(frame, version=RECONCILIATION_SIGNATURE_V1) == (
        "c323485405c9cb5ebc0627bbfd50f24dcacf6e3735d771859be571e2c686e745"
    )


@pytest.mark.parametrize(
    "value",
    [1.25, float("nan"), pd.Series([1.25], dtype="float32").iloc[0]],
)
def test_signature_v2_rejects_binary_float_financial_values(value: float) -> None:
    with pytest.raises(
        InvalidReconciliationSignatureValueError,
        match="stock_amount.*binary floating-point",
    ):
        _signature(_matched_row(stock_amount=value), version=RECONCILIATION_SIGNATURE_V2)


def test_signature_v2_rejects_other_noncanonical_financial_values() -> None:
    for value in (True, "NaN", "1e2", Decimal("Infinity"), object()):
        with pytest.raises(
            InvalidReconciliationSignatureValueError,
            match="financial signature column 'stock_amount'",
        ):
            _signature(_matched_row(stock_amount=value), version=RECONCILIATION_SIGNATURE_V2)


def test_signature_v2_allows_nonfinancial_float_scores() -> None:
    signature = _signature(
        _matched_row(confidence_score=0.875, reference_similarity=0.5),
        version=RECONCILIATION_SIGNATURE_V2,
    )

    assert len(signature) == 64


def test_signature_v2_canonicalizes_exact_financial_representations_and_row_order() -> None:
    first = _matched_row(
        stock_amount=Decimal("1.2500"),
        gl_amount="1.250",
        value_difference=0,
    )
    second = _matched_row(
        match_id="M-2",
        move_id="S-2",
        entry_id="G-2",
        stock_amount=Decimal("2.00"),
        gl_amount="2",
        value_difference=Decimal("0.0"),
    )
    alternate_first = _matched_row(
        stock_amount="1.25",
        gl_amount=Decimal("1.25"),
        value_difference=Decimal("0.000"),
    )

    left = pd.concat([first, second], ignore_index=True)
    right = pd.concat([second, alternate_first], ignore_index=True)

    assert _signature(left, version=RECONCILIATION_SIGNATURE_V2) == _signature(
        right,
        version=RECONCILIATION_SIGNATURE_V2,
    )


def test_signature_v3_excludes_source_location_and_includes_record_instance_identity() -> None:
    first_exception = _exception_row().assign(
        record_instance_id="stock:S-1:fingerprint#occurrence:1",
        duplicate_ordinal=1,
        duplicate_count=2,
        record_identity_policy="canonical-multiset-occurrence-v1",
    )
    relocated_exception = first_exception.assign(source_row=999)
    matched = _matched_row(
        stock_record_instance_id="stock:S-1:fingerprint#occurrence:1",
        gl_record_instance_id="gl:G-1:fingerprint#occurrence:1",
        stock_duplicate_ordinal=1,
        gl_duplicate_ordinal=1,
        stock_duplicate_count=2,
        gl_duplicate_count=2,
        record_identity_policy="canonical-multiset-occurrence-v1",
    )

    first = build_reconciliation_signature(
        matched_transactions=matched,
        all_exceptions=first_exception,
        signature_version=RECONCILIATION_SIGNATURE_V3,
    )
    relocated = build_reconciliation_signature(
        matched_transactions=matched,
        all_exceptions=relocated_exception,
        signature_version=RECONCILIATION_SIGNATURE_V3,
    )
    changed_identity = build_reconciliation_signature(
        matched_transactions=matched.assign(
            stock_record_instance_id="stock:S-1:fingerprint#occurrence:2"
        ),
        all_exceptions=first_exception,
        signature_version=RECONCILIATION_SIGNATURE_V3,
    )

    assert first == relocated
    assert first != changed_identity


def test_signature_rejects_unknown_version() -> None:
    with pytest.raises(ValueError, match="unsupported reconciliation signature version"):
        _signature(_matched_row(), version="reconciliation-signature-v4")
