from __future__ import annotations

import ast
import warnings
from decimal import Decimal, localcontext
from pathlib import Path

import pandas as pd
import pytest

from reconforge.io.readers import coerce_dataset_types
from reconforge.schemas import DatasetName
from reconforge.utils.money import (
    CURRENT_FINANCIAL_INPUT_POLICY,
    LEGACY_FINANCIAL_INPUT_POLICY,
    STRICT_FINANCIAL_INPUT_POLICY,
    InvalidAmountError,
    LegacyFinancialInputWarning,
    Money,
    exact_money_difference,
    money_difference,
    parse_amount,
    parse_amount_for_currency_precision,
    parse_exact_amount,
    parse_exact_amount_for_currency_precision,
    round_exact_money,
    round_money,
    within_exact_tolerance,
    within_tolerance,
)

ROOT = Path(__file__).resolve().parents[1]


def test_current_financial_input_policy_is_strict_v2() -> None:
    assert CURRENT_FINANCIAL_INPUT_POLICY == "strict-financial-input-v2"
    assert LEGACY_FINANCIAL_INPUT_POLICY == "legacy-financial-input-v1"
    assert STRICT_FINANCIAL_INPUT_POLICY == CURRENT_FINANCIAL_INPUT_POLICY


def test_legacy_v1_warns_and_preserves_documented_finite_float_compatibility() -> None:
    with pytest.warns(LegacyFinancialInputWarning, match="deprecated"):
        parsed = parse_amount(0.1, input_policy=LEGACY_FINANCIAL_INPUT_POLICY)

    assert parsed == Decimal("0.1")


def test_legacy_warning_is_emitted_once_per_call_site_even_with_always_filter() -> None:
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always", LegacyFinancialInputWarning)
        for _ in range(5):
            parse_amount(1.25, input_policy=LEGACY_FINANCIAL_INPUT_POLICY)

    assert len(captured) == 1


@pytest.mark.parametrize(
    "value",
    [0.1, float("nan"), float("inf"), pd.Series([0.1], dtype="float32").iloc[0]],
)
def test_strict_v2_rejects_binary_floating_point_before_conversion(value: object) -> None:
    with pytest.raises(InvalidAmountError, match="strict-financial-input-v2") as captured:
        parse_exact_amount(value)

    assert str(captured.value) == (
        "binary floating-point financial input is not allowed under strict-financial-input-v2"
    )


def test_strict_v2_accepts_exact_types_under_hostile_decimal_context() -> None:
    with localcontext() as context:
        context.prec = 3
        context.rounding = "ROUND_DOWN"
        assert parse_exact_amount("123456789.000100") == Decimal("123456789.000100")
        assert parse_exact_amount(123456789) == Decimal("123456789")
        assert parse_exact_amount(Decimal("0.000000000000000001")) == Decimal(
            "0.000000000000000001"
        )


def test_currency_precision_parser_forwards_the_selected_input_policy() -> None:
    with pytest.warns(LegacyFinancialInputWarning):
        assert parse_amount_for_currency_precision(
            10.5,
            precision=2,
            input_policy=LEGACY_FINANCIAL_INPUT_POLICY,
        ) == Decimal("10.5")
    with pytest.raises(InvalidAmountError, match="strict-financial-input-v2"):
        parse_exact_amount_for_currency_precision(10.5, precision=2)
    assert parse_exact_amount_for_currency_precision("10.50", precision=2) == Decimal("10.50")


def test_unknown_financial_input_policy_fails_closed_without_echoing_value() -> None:
    with pytest.raises(InvalidAmountError, match="unsupported financial input policy") as captured:
        parse_amount("987654321.01", input_policy="unknown-v9")  # type: ignore[arg-type]

    assert "987654321.01" not in str(captured.value)


def test_exact_scalar_helpers_reject_binary_floats_and_accept_exact_values() -> None:
    assert round_exact_money("100.005") == Decimal("100.01")
    assert exact_money_difference(Decimal("10.005"), "8") == Decimal("2.01")
    assert within_exact_tolerance("10.00", Decimal("10.01"), 1) is True

    operations = (
        lambda: round_exact_money(0.1),
        lambda: exact_money_difference("1", 0.1),
        lambda: within_exact_tolerance("1", "1", 0.1),
    )
    for operation in operations:
        with pytest.raises(InvalidAmountError, match="strict-financial-input-v2"):
            operation()


def test_legacy_scalar_helpers_remain_compatible_during_deprecation_window() -> None:
    with pytest.warns(LegacyFinancialInputWarning, match="deprecated"):
        assert round_money(0.1) == Decimal("0.10")
        assert money_difference(1.1, 0.1) == Decimal("1.00")
        assert within_tolerance(1.1, 0.1, 1.0) is True


def test_public_financial_policy_defaults_are_strict_and_legacy_is_explicit() -> None:
    with pytest.raises(InvalidAmountError, match="strict-financial-input-v2"):
        parse_amount(0.1)
    with pytest.raises(InvalidAmountError, match="strict-financial-input-v2"):
        Money(0.1, "USD")

    implicit_legacy_defaults: list[str] = []
    for path in sorted((ROOT / "reconforge").rglob("*.py")):
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if "FinancialInputPolicy = LEGACY_FINANCIAL_INPUT_POLICY" in line:
                implicit_legacy_defaults.append(f"{path.relative_to(ROOT)}:{line_number}")

    assert implicit_legacy_defaults == []


def test_exact_money_construction_and_scalar_operations_reject_binary_floats() -> None:
    money = Money.from_exact("100.50", "USD", strict_precision=True)

    assert money.multiply_exact("2") == Money.from_exact("201.00", "USD")
    assert money.divide_exact(2) == Money.from_exact("50.25", "USD")
    with pytest.raises(InvalidAmountError, match="strict-financial-input-v2"):
        Money.from_exact(0.1, "USD")
    with pytest.raises(InvalidAmountError, match="strict-financial-input-v2"):
        money.multiply_exact(0.1)
    with pytest.raises(InvalidAmountError, match="strict-financial-input-v2"):
        money.divide_exact(0.1)

    with pytest.raises(InvalidAmountError, match="strict-financial-input-v2"):
        money * 0.5


def test_production_code_cannot_call_legacy_scalar_helpers_or_implicit_money_reader() -> None:
    """Keep compatibility helper/default use outside production code."""

    legacy_names = {"money_difference", "round_money", "within_tolerance"}
    violations: list[str] = []
    for path in sorted((ROOT / "reconforge").rglob("*.py")):
        if path == ROOT / "reconforge" / "utils" / "money.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            called_name = ""
            if isinstance(node.func, ast.Name):
                called_name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                called_name = node.func.attr
            if called_name in legacy_names:
                violations.append(f"{path.relative_to(ROOT)}:{node.lineno}:{called_name}")
            if called_name == "Money" and not any(
                keyword.arg == "input_policy" for keyword in node.keywords
            ):
                violations.append(
                    f"{path.relative_to(ROOT)}:{node.lineno}:implicit-Money-input-policy"
                )
            if called_name == "_filter_exceptions" and not any(
                keyword.arg == "financial_input_policy" for keyword in node.keywords
            ):
                violations.append(
                    f"{path.relative_to(ROOT)}:{node.lineno}:implicit-Studio-filter-policy"
                )
            if called_name == "anonymize_directory" and not any(
                keyword.arg == "financial_input_policy" for keyword in node.keywords
            ):
                violations.append(
                    f"{path.relative_to(ROOT)}:{node.lineno}:implicit-anonymizer-policy"
                )
            if called_name == "analyze_variance" and not any(
                keyword.arg == "financial_input_policy" for keyword in node.keywords
            ):
                violations.append(
                    f"{path.relative_to(ROOT)}:{node.lineno}:implicit-variance-policy"
                )
            if called_name == "generate_synthetic_dataset" and not any(
                keyword.arg == "financial_input_policy" for keyword in node.keywords
            ):
                violations.append(
                    f"{path.relative_to(ROOT)}:{node.lineno}:implicit-generator-policy"
                )
            if called_name == "load_config" and not any(
                keyword.arg == "financial_input_policy" for keyword in node.keywords
            ):
                violations.append(
                    f"{path.relative_to(ROOT)}:{node.lineno}:implicit-config-policy"
                )
            if called_name in {
                "control_matrix_frame",
                "collect_exception_frame",
                "compare_period_outputs",
                "evaluate_condition",
                "evaluate_rule",
                "execute_rule_pack",
                "explain_rule",
                "export_review_register",
                "export_control_matrix",
                "collect_evidence_cases",
                "generate_client_pack",
                "generate_evidence_binder",
                "load_rule_pack",
                "review_register_frame",
                "run_rule_pack",
                "_bucket_amount",
            } and not any(
                keyword.arg == "financial_input_policy" for keyword in node.keywords
            ):
                violations.append(
                    f"{path.relative_to(ROOT)}:{node.lineno}:"
                    f"implicit-rule-policy:{called_name}"
                )

    assert violations == []


def test_official_dataset_coercion_rejects_binary_floating_point_as_data_quality() -> None:
    frame = pd.DataFrame(
        [
            {
                "move_id": "SM-1",
                "date": "2026-07-25",
                "total_cost": 10.5,
                "source_document": "INV-1",
                "work_order": "WO-1",
            },
            {
                "move_id": "SM-2",
                "date": "2026-07-25",
                "total_cost": "10.50",
                "source_document": "INV-2",
                "work_order": "WO-2",
            },
        ]
    )

    coerced = coerce_dataset_types(frame, DatasetName.STOCK_MOVES)

    assert coerced.loc[0, "total_cost"] is None
    assert coerced.loc[0, "_reconforge_raw_total_cost"] == "10.5"
    assert coerced.loc[1, "total_cost"] == Decimal("10.50")
    assert pd.isna(coerced.loc[1, "_reconforge_raw_total_cost"])
