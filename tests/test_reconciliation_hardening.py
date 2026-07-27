from __future__ import annotations

from decimal import Decimal

import pandas as pd
import pytest

from reconforge.config import ReconForgeConfig
from reconforge.engines.signature import build_reconciliation_signature
from reconforge.reconciliation.matching import RECORD_IDENTITY_POLICY, is_exact_match, normalize_reference
from reconforge.reconciliation.stock_gl import reconcile_stock_gl
from reconforge.rules.models import Condition
from reconforge.rules.operators import evaluate_condition
from reconforge.utils.money import (
    STRICT_FINANCIAL_INPUT_POLICY,
    InvalidAmountError,
    parse_amount,
    parse_amount_for_currency_precision,
)


def _duplicate_exact_frames() -> tuple[pd.DataFrame, pd.DataFrame]:
    stock_record = {
        "move_id": "MOVE-DUP",
        "date": "2026-07-25",
        "source_document": "INV-DUP",
        "work_order": "WO-DUP",
        "total_cost": Decimal("10.00"),
        "currency": "USD",
    }
    gl_record = {
        "entry_id": "GL-DUP",
        "date": "2026-07-25",
        "reference": "INV-DUP",
        "work_order": "WO-DUP",
        "amount": Decimal("10.00"),
        "currency": "USD",
    }
    return pd.DataFrame([stock_record, stock_record]), pd.DataFrame([gl_record, gl_record])


def test_duplicate_identical_rows_receive_stable_occurrence_identity() -> None:
    stock, gl = _duplicate_exact_frames()
    config = ReconForgeConfig()

    first = reconcile_stock_gl(
        stock,
        gl,
        config,
        input_policy=STRICT_FINANCIAL_INPUT_POLICY,
    )
    shuffled = reconcile_stock_gl(
        stock.iloc[::-1].reset_index(drop=True),
        gl.iloc[::-1].reset_index(drop=True),
        config,
        input_policy=STRICT_FINANCIAL_INPUT_POLICY,
    )

    assert len(first.matched_transactions) == 2
    assert first.record_identity_policy == RECORD_IDENTITY_POLICY
    assert first.matched_transactions["match_id"].nunique() == 2
    assert first.matched_transactions["stock_record_instance_id"].nunique() == 2
    assert first.matched_transactions["gl_record_instance_id"].nunique() == 2
    assert set(first.matched_transactions["stock_duplicate_ordinal"]) == {1, 2}
    assert set(first.matched_transactions["gl_duplicate_ordinal"]) == {1, 2}
    assert set(first.matched_transactions["stock_duplicate_count"]) == {2}
    assert set(first.matched_transactions["gl_duplicate_count"]) == {2}
    assert build_reconciliation_signature(
        matched_transactions=first.matched_transactions,
        all_exceptions=first.all_exceptions,
    ) == build_reconciliation_signature(
        matched_transactions=shuffled.matched_transactions,
        all_exceptions=shuffled.all_exceptions,
    )


def test_data_quality_identity_is_stable_while_source_row_tracks_location() -> None:
    invalid = {
        "move_id": "MOVE-BAD",
        "date": "2026-07-25",
        "source_document": "INV-BAD",
        "work_order": "WO-1",
        "total_cost": "not-an-amount",
        "currency": "USD",
        "_reconforge_source_position": 999,
    }
    valid = {
        "move_id": "MOVE-GOOD",
        "date": "2026-07-25",
        "source_document": "INV-GOOD",
        "work_order": "WO-1",
        "total_cost": Decimal("1.00"),
        "currency": "USD",
    }
    gl = pd.DataFrame(
        columns=["entry_id", "date", "reference", "work_order", "amount", "currency"]
    )

    first = reconcile_stock_gl(
        pd.DataFrame([invalid, valid]),
        gl,
        ReconForgeConfig(),
        input_policy=STRICT_FINANCIAL_INPUT_POLICY,
    ).data_quality_exceptions.iloc[0]
    relocated = reconcile_stock_gl(
        pd.DataFrame([valid, invalid]),
        gl,
        ReconForgeConfig(),
        input_policy=STRICT_FINANCIAL_INPUT_POLICY,
    ).data_quality_exceptions.iloc[0]

    assert first["exception_id"] == relocated["exception_id"]
    assert first["record_instance_id"] == relocated["record_instance_id"]
    assert first["source_position"] == 1
    assert relocated["source_position"] == 2
    assert first["source_row"] == 2
    assert relocated["source_row"] == 3
    assert first["source_row_basis"] == "tabular-header-offset-v1"
    assert first["record_identity_policy"] == RECORD_IDENTITY_POLICY


def test_duplicate_data_quality_rows_do_not_collapse_exception_identity() -> None:
    invalid = {
        "move_id": "MOVE-BAD-DUP",
        "date": "2026-07-25",
        "source_document": "INV-BAD-DUP",
        "work_order": "WO-1",
        "total_cost": "not-an-amount",
        "currency": "USD",
    }
    gl = pd.DataFrame(
        columns=["entry_id", "date", "reference", "work_order", "amount", "currency"]
    )

    result = reconcile_stock_gl(
        pd.DataFrame([invalid, invalid]),
        gl,
        ReconForgeConfig(),
        input_policy=STRICT_FINANCIAL_INPUT_POLICY,
    )

    quality = result.data_quality_exceptions
    assert len(quality) == 2
    assert quality["exception_id"].nunique() == 2
    assert quality["record_instance_id"].nunique() == 2
    assert set(quality["duplicate_ordinal"]) == {1, 2}
    assert set(quality["duplicate_count"]) == {2}


def _global_assignment_frames() -> tuple[pd.DataFrame, pd.DataFrame]:
    stock = pd.DataFrame(
        [
            {
                "move_id": "MOVE-A",
                "date": "2026-01-10",
                "source_document": "SOURCE-A",
                "work_order": "WO-1",
                "total_cost": "100.0",
            },
            {
                "move_id": "MOVE-B",
                "date": "2026-01-10",
                "source_document": "SOURCE-B",
                "work_order": "WO-1",
                "total_cost": "102.0",
            },
        ],
    )
    gl = pd.DataFrame(
        [
            {
                "entry_id": "GL-ONLY-B",
                "date": "2026-01-10",
                "reference": "SOURCE-B",
                "work_order": "WO-1",
                "amount": "102.0",
            },
            {
                "entry_id": "GL-FOR-A",
                "date": "2026-01-10",
                "reference": "OTHER",
                "work_order": "WO-1",
                "amount": "98.0",
            },
        ],
    )
    return stock, gl


def _pairs(frame: pd.DataFrame) -> set[tuple[str, str, str]]:
    return {
        (str(row["move_id"]), str(row["entry_id"]), str(row["match_id"]))
        for _, row in frame.iterrows()
    }


def test_global_assignment_avoids_greedy_dead_end_and_is_order_independent() -> None:
    stock, gl = _global_assignment_frames()
    config = ReconForgeConfig(amount_tolerance="2.0", date_tolerance_days=3)

    original = reconcile_stock_gl(stock, gl, config)
    shuffled = reconcile_stock_gl(
        stock.sample(frac=1, random_state=11).reset_index(drop=True),
        gl.sample(frac=1, random_state=13).reset_index(drop=True),
        config,
    )

    assert len(original.matched_transactions) == 2
    assert _pairs(original.matched_transactions) == _pairs(shuffled.matched_transactions)
    assert {(move, entry) for move, entry, _ in _pairs(original.matched_transactions)} == {
        ("MOVE-A", "GL-FOR-A"),
        ("MOVE-B", "GL-ONLY-B"),
    }
    assert original.matched_transactions["entry_id"].is_unique


def test_perfect_reconciliation_returns_typed_empty_exception_frame() -> None:
    stock = pd.DataFrame(
        [{"move_id": "MOVE-1", "date": "2026-01-01", "source_document": "INV-001", "work_order": "WO-1", "total_cost": 10}],
    )
    gl = pd.DataFrame(
        [{"entry_id": "GL-1", "date": "2026-01-01", "reference": "INV-001", "work_order": "WO-1", "amount": 10}],
    )

    result = reconcile_stock_gl(stock, gl, ReconForgeConfig())

    assert len(result.matched_transactions) == 1
    assert result.all_exceptions.empty
    assert {"exception_id", "exception_type", "exception_reason", "risk_score"} <= set(result.all_exceptions.columns)


def test_reference_normalization_ignores_case_spacing_symbols_and_leading_zeros() -> None:
    equivalent = ["INV-001", "inv-001 ", "INV/001", "INV 1"]

    assert {normalize_reference(value) for value in equivalent} == {"INV1"}


def test_normalized_equivalent_reference_is_not_reported_as_mismatch() -> None:
    stock = pd.DataFrame(
        [{"move_id": "MOVE-1", "date": "2026-01-01", "source_document": "INV-001 ", "work_order": "WO-1", "total_cost": 10}],
    )
    gl = pd.DataFrame(
        [{"entry_id": "GL-1", "date": "2026-01-01", "reference": "inv/1", "work_order": "WO-1", "amount": 10}],
    )

    result = reconcile_stock_gl(stock, gl, ReconForgeConfig())

    assert result.reference_mismatches.empty
    row = result.matched_transactions.iloc[0]
    assert row["source_document"] == "INV-001 "
    assert row["gl_reference"] == "inv/1"
    assert row["source_document_normalized"] == row["gl_reference_normalized"] == "INV1"


def test_invalid_financial_value_is_visible_and_never_matches_as_zero() -> None:
    stock = pd.DataFrame(
        [{"move_id": "MOVE-BAD", "date": "2026-01-01", "source_document": "INV-1", "work_order": "WO-1", "total_cost": "N/A?"}],
    )
    gl = pd.DataFrame(
        [{"entry_id": "GL-ZERO", "date": "2026-01-01", "reference": "INV-1", "work_order": "WO-1", "amount": 0}],
    )

    result = reconcile_stock_gl(stock, gl, ReconForgeConfig())

    assert result.matched_transactions.empty
    assert result.stock_without_gl.empty
    assert len(result.data_quality_exceptions) == 1
    quality = result.data_quality_exceptions.iloc[0]
    assert quality["invalid_value"] == "N/A?"
    assert quality["exception_type"] == "data_quality"
    assert quality["risk_score"] >= 60
    assert set(result.all_exceptions["exception_type"]) == {"data_quality", "gl_without_stock"}


def test_currency_precision_mismatch_is_flagged_as_data_quality() -> None:
    stock = pd.DataFrame(
        [{"move_id": "MOVE-OVER", "date": "2026-01-01", "source_document": "INV-1", "work_order": "WO-1", "total_cost": "100.75", "currency": "JPY"}],
    )
    gl = pd.DataFrame(
        [{"entry_id": "GL-OVER", "date": "2026-01-01", "reference": "INV-1", "work_order": "WO-1", "amount": "100.75", "currency": "JPY"}],
    )

    result = reconcile_stock_gl(stock, gl, ReconForgeConfig())

    assert result.matched_transactions.empty
    assert len(result.data_quality_exceptions) == 2
    assert set(result.data_quality_exceptions["parse_error"]) == {"invalid_amount"}
    assert result.all_exceptions["exception_type"].isin(["data_quality"]).any()


def test_unknown_currency_is_a_visible_data_quality_exception_and_never_matches() -> None:
    stock = pd.DataFrame(
        [
            {
                "move_id": "MOVE-UNKNOWN-CURRENCY",
                "date": "2026-01-01",
                "source_document": "INV-UNKNOWN-CURRENCY",
                "work_order": "WO-1",
                "total_cost": "100.00",
                "currency": "ZZZ",
            }
        ],
    )
    gl = pd.DataFrame(
        [
            {
                "entry_id": "GL-UNKNOWN-CURRENCY",
                "date": "2026-01-01",
                "reference": "INV-UNKNOWN-CURRENCY",
                "work_order": "WO-1",
                "amount": "100.00",
                "currency": "ZZZ",
            }
        ],
    )

    result = reconcile_stock_gl(stock, gl, ReconForgeConfig())

    assert result.matched_transactions.empty
    assert result.stock_without_gl.empty
    assert result.gl_without_stock.empty
    assert len(result.data_quality_exceptions) == 2
    assert set(result.data_quality_exceptions["field"]) == {"currency"}
    assert set(result.data_quality_exceptions["invalid_value"]) == {"ZZZ"}
    assert set(result.data_quality_exceptions["parse_error"]) == {"unknown_currency"}
    assert result.invariants["record_accounting_ok"] is True


def test_amount_parser_accepts_accounting_formats_and_rejects_bad_values() -> None:
    assert parse_amount("1,250.00") == Decimal("1250.00")
    assert isinstance(parse_amount("1,250.00"), Decimal)
    assert parse_amount("(1,250.00)") == Decimal("-1250.00")
    for invalid in (None, "", "N/A?", "NaN", float("inf"), True):
        try:
            parse_amount(invalid)
        except InvalidAmountError:
            pass
        else:
            raise AssertionError(f"expected InvalidAmountError for {invalid!r}")


def test_currency_precision_mismatch_is_rejected_by_matching_engine() -> None:
    stock_row = pd.Series(
        {
            "total_cost": "100.75",
            "currency": "JPY",
            "source_document": "INV-1",
            "work_order": "WO-1",
        },
    )
    gl_row = pd.Series(
        {
            "amount": "100.75",
            "currency": "JPY",
            "reference": "INV-1",
            "work_order": "WO-1",
        },
    )

    assert is_exact_match(stock_row, gl_row) is False


def test_amount_parser_rejects_scientific_notation() -> None:
    for invalid in ("1e2", "1E2", "1.23e-2", "-1e3"):
        try:
            parse_amount(invalid)
        except InvalidAmountError:
            pass
        else:
            raise AssertionError(f"expected InvalidAmountError for {invalid!r}")


def test_amount_parser_supports_locale_decimal_and_thousands_separators() -> None:
    assert parse_amount("1,250.00", decimal_separator=".", thousands_separator=",") == Decimal("1250.00")
    assert parse_amount("1.250,00", decimal_separator=",", thousands_separator=".") == Decimal("1250.00")
    assert parse_amount("-1.250,00", decimal_separator=",", thousands_separator=".") == Decimal("-1250.00")


def test_amount_parser_respects_currency_precision_rules() -> None:
    assert parse_amount_for_currency_precision("1250", precision=2) == Decimal("1250")
    assert parse_amount_for_currency_precision("1250.00", precision=2) == Decimal("1250.00")
    assert parse_amount_for_currency_precision("1250.00", precision=3) == Decimal("1250.00")
    assert isinstance(parse_amount_for_currency_precision("1250.00", precision=2), Decimal)
    try:
        parse_amount_for_currency_precision("10.50", precision=0)
    except InvalidAmountError:
        pass
    else:
        raise AssertionError("expected InvalidAmountError for precision mismatch")
    try:
        parse_amount_for_currency_precision("1e2", precision=2)
    except InvalidAmountError:
        pass
    else:
        raise AssertionError("expected InvalidAmountError for scientific notation input")


def test_amount_parser_defaults_reject_binary_float_inputs() -> None:
    with pytest.raises(InvalidAmountError, match="strict-financial-input-v2"):
        parse_amount(1250.0)
    with pytest.raises(InvalidAmountError, match="strict-financial-input-v2"):
        parse_amount_for_currency_precision(1250.0, precision=2)


def test_invalid_rule_numeric_operand_does_not_become_zero() -> None:
    row = pd.Series({"amount": "broken"})
    condition = Condition(field="amount", operator="greater_than", value=-1)

    assert evaluate_condition(row, condition) is False


def test_rule_amount_comparisons_preserve_decimal_tolerance_boundaries() -> None:
    row = pd.Series({"left_amount": "100.000000001", "right_amount": "100.000000000"})
    condition = Condition(
        field="left_amount",
        other_field="right_amount",
        operator="amount_within_tolerance",
        tolerance=Decimal("0.000000001"),
    )

    assert evaluate_condition(row, condition) is True


def test_every_reconciliation_exception_has_reason_evidence_and_independent_risk() -> None:
    stock, gl = _global_assignment_frames()
    result = reconcile_stock_gl(stock, gl, ReconForgeConfig(amount_tolerance="2.0"))

    assert not result.all_exceptions.empty
    assert result.all_exceptions["exception_id"].astype(str).str.startswith("EXC-").all()
    assert result.all_exceptions["exception_reason"].astype(str).str.len().gt(0).all()
    assert result.all_exceptions["evidence_reference"].astype(str).str.len().gt(0).all()
    assert result.all_exceptions["risk_score"].notna().all()


def test_exception_rows_include_classification_metadata() -> None:
    stock, gl = _global_assignment_frames()
    result = reconcile_stock_gl(stock, gl, ReconForgeConfig(amount_tolerance="2.0"))

    required = {
        "exception_title",
        "exception_explanation",
        "suggested_action",
        "severity",
        "ownership",
        "workflow_status",
        "exception_type",
        "exception_reason",
        "evidence_reference",
    }
    assert required.issubset(result.all_exceptions.columns)


def test_reconciled_exception_ids_are_reorder_invariant() -> None:
    stock = pd.DataFrame(
        [
            {
                "move_id": "MOVE-B",
                "date": "2026-02-01",
                "source_document": "INV-200",
                "work_order": "WO-1",
                "total_cost": 90,
            },
            {
                "move_id": "MOVE-A",
                "date": "2026-01-01",
                "source_document": "INV-100",
                "work_order": "WO-1",
                "total_cost": 50,
            },
        ],
    )
    gl = pd.DataFrame(
        [
            {
                "entry_id": "GL-200",
                "date": "2026-01-31",
                "reference": "INV-200",
                "work_order": "WO-1",
                "amount": 90,
            },
            {
                "entry_id": "GL-EXTRA",
                "date": "2026-02-10",
                "reference": "INV-MISSING",
                "work_order": "WO-1",
                "amount": 15,
            },
        ],
    )
    config = ReconForgeConfig(amount_tolerance="0.5")

    original = reconcile_stock_gl(stock, gl, config)
    shuffled = reconcile_stock_gl(
        stock.sample(frac=1, random_state=11).reset_index(drop=True),
        gl.sample(frac=1, random_state=17).reset_index(drop=True),
        config,
    )

    baseline_signature = sorted(
        (row["exception_type"], row["evidence_reference"], row["exception_id"])
        for _, row in original.all_exceptions.iterrows()
    )
    shuffled_signature = sorted(
        (row["exception_type"], row["evidence_reference"], row["exception_id"])
        for _, row in shuffled.all_exceptions.iterrows()
    )
    assert baseline_signature == shuffled_signature
    assert len(original.all_exceptions) == len(shuffled.all_exceptions)


def test_reordered_rows_do_not_change_data_quality_exception_id() -> None:
    stock = pd.DataFrame(
        [
            {
                "move_id": "MOVE-BAD",
                "date": "2026-01-01",
                "source_document": "INV-BAD",
                "work_order": "WO-1",
                "total_cost": "N/A?",
            },
            {
                "move_id": "MOVE-200",
                "date": "2026-01-01",
                "source_document": "INV-200",
                "work_order": "WO-1",
                "total_cost": "200",
            },
        ],
    )
    gl = pd.DataFrame(
        [
            {
                "entry_id": "GL-200",
                "date": "2026-01-01",
                "reference": "INV-200",
                "work_order": "WO-1",
                "amount": "200",
            },
        ],
    )
    config = ReconForgeConfig()

    baseline = reconcile_stock_gl(stock, gl, config)
    reordered = reconcile_stock_gl(
        stock.sample(frac=1, random_state=77).reset_index(drop=True),
        gl,
        config,
    )

    baseline_quality = baseline.all_exceptions[baseline.all_exceptions["exception_type"] == "data_quality"]
    reordered_quality = reordered.all_exceptions[reordered.all_exceptions["exception_type"] == "data_quality"]
    assert not baseline_quality.empty
    assert not reordered_quality.empty
    assert sorted(baseline_quality["exception_id"]) == sorted(reordered_quality["exception_id"])
