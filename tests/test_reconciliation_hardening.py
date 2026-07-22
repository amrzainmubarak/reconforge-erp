from __future__ import annotations

import pandas as pd

from reconforge.config import ReconForgeConfig
from reconforge.reconciliation.matching import normalize_reference
from reconforge.reconciliation.stock_gl import reconcile_stock_gl
from reconforge.rules.models import Condition
from reconforge.rules.operators import evaluate_condition
from reconforge.utils.money import InvalidAmountError, parse_amount


def _global_assignment_frames() -> tuple[pd.DataFrame, pd.DataFrame]:
    stock = pd.DataFrame(
        [
            {
                "move_id": "MOVE-A",
                "date": "2026-01-10",
                "source_document": "SOURCE-A",
                "work_order": "WO-1",
                "total_cost": 100.0,
            },
            {
                "move_id": "MOVE-B",
                "date": "2026-01-10",
                "source_document": "SOURCE-B",
                "work_order": "WO-1",
                "total_cost": 102.0,
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
                "amount": 102.0,
            },
            {
                "entry_id": "GL-FOR-A",
                "date": "2026-01-10",
                "reference": "OTHER",
                "work_order": "WO-1",
                "amount": 98.0,
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
    config = ReconForgeConfig(amount_tolerance=2.0, date_tolerance_days=3)

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


def test_amount_parser_accepts_accounting_formats_and_rejects_bad_values() -> None:
    assert parse_amount("1,250.00") == 1250.0
    assert parse_amount("(1,250.00)") == -1250.0
    for invalid in (None, "", "N/A?", "NaN", float("inf"), True):
        try:
            parse_amount(invalid)
        except InvalidAmountError:
            pass
        else:
            raise AssertionError(f"expected InvalidAmountError for {invalid!r}")


def test_invalid_rule_numeric_operand_does_not_become_zero() -> None:
    row = pd.Series({"amount": "broken"})
    condition = Condition(field="amount", operator="greater_than", value=-1)

    assert evaluate_condition(row, condition) is False


def test_every_reconciliation_exception_has_reason_evidence_and_independent_risk() -> None:
    stock, gl = _global_assignment_frames()
    result = reconcile_stock_gl(stock, gl, ReconForgeConfig(amount_tolerance=2.0))

    assert not result.all_exceptions.empty
    assert result.all_exceptions["exception_id"].astype(str).str.startswith("EXC-").all()
    assert result.all_exceptions["exception_reason"].astype(str).str.len().gt(0).all()
    assert result.all_exceptions["evidence_reference"].astype(str).str.len().gt(0).all()
    assert result.all_exceptions["risk_score"].notna().all()


def test_exception_rows_include_classification_metadata() -> None:
    stock, gl = _global_assignment_frames()
    result = reconcile_stock_gl(stock, gl, ReconForgeConfig(amount_tolerance=2.0))

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
