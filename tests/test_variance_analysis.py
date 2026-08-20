from __future__ import annotations

import json
from decimal import ROUND_DOWN, Decimal, localcontext
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from typer.testing import CliRunner

from reconforge.cli import app
from reconforge.io.writers import exact_json_dumps
from reconforge.utils.money import (
    LEGACY_FINANCIAL_INPUT_POLICY,
    STRICT_FINANCIAL_INPUT_POLICY,
    InvalidAmountError,
    LegacyFinancialInputWarning,
)
from reconforge.variance import (
    VarianceThresholdPolicy,
    analyze_variance,
    load_summary_metrics,
    read_variance_thresholds,
    variance_frame,
)

runner = CliRunner()


def test_direct_variance_threshold_policy_rejects_unsupported_financial_policy() -> None:
    with pytest.raises(InvalidAmountError, match="unsupported financial input policy"):
        VarianceThresholdPolicy(
            amount_threshold=Decimal("0"),
            percent_threshold=Decimal("0"),
            artifact_schema_version=3,
            threshold_policy_schema_version=2,
            financial_input_policy="unknown-v9",  # type: ignore[arg-type]
        )


def _write_management_summary(path: Path, exception_count: int, unmatched_stock: int | str | float | Decimal) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "management_pack.json").write_text(
        json.dumps(
            {
                "executive_summary": [
                    {"metric": "exception_count", "value": exception_count},
                    {"metric": "unmatched_stock_amount", "value": unmatched_stock},
                ],
                "control_value_summary": [{"metric": "review_completion_rate_pct", "value": 50}],
            },
        ),
        encoding="utf-8",
    )


def test_variance_analysis_compares_summary_metrics(tmp_path: Path) -> None:
    previous = tmp_path / "jan"
    current = tmp_path / "feb"
    _write_management_summary(previous, exception_count=10, unmatched_stock=100)
    _write_management_summary(current, exception_count=15, unmatched_stock=80)

    artifacts = analyze_variance(current, previous, tmp_path / "variance", percent_threshold=20)
    assert artifacts.workbook_path.exists()
    assert artifacts.csv_path.exists()
    assert artifacts.json_path.exists()
    assert artifacts.html_path.exists()
    assert artifacts.markdown_path.exists()

    payload = json.loads(artifacts.json_path.read_text(encoding="utf-8"))
    rows = {row["metric"]: row for row in payload["variances"]}
    assert Decimal(str(rows["executive_summary.exception_count"]["amount_variance"])) == Decimal("5")
    assert Decimal(str(rows["executive_summary.exception_count"]["percentage_variance"])) == Decimal("50")
    assert rows["executive_summary.exception_count"]["threshold_flag"] is True

    thresholds = read_variance_thresholds(payload)
    assert thresholds.artifact_schema_version == 3
    assert thresholds.threshold_policy_schema_version == 2
    assert thresholds.financial_input_policy == STRICT_FINANCIAL_INPUT_POLICY
    assert thresholds.amount_threshold == Decimal("0")
    assert thresholds.percent_threshold == Decimal("20")


def test_cli_variance_analysis_outputs(tmp_path: Path) -> None:
    previous = tmp_path / "jan"
    current = tmp_path / "feb"
    output = tmp_path / "variance"
    _write_management_summary(previous, exception_count=10, unmatched_stock=100)
    _write_management_summary(current, exception_count=12, unmatched_stock=105)
    result = runner.invoke(
        app,
        [
            "analyze",
            "variance",
            "--current",
            str(current),
            "--previous",
            str(previous),
            "--output",
            str(output),
        ],
    )
    assert result.exit_code == 0
    assert (output / "variance_analysis.json").exists()
    assert (output / "variance_analysis.html").exists()


def test_cli_variance_thresholds_preserve_exact_text_and_decision(tmp_path: Path) -> None:
    previous = tmp_path / "jan"
    current = tmp_path / "feb"
    output = tmp_path / "variance"
    _write_management_summary(previous, exception_count=4, unmatched_stock="0")
    _write_management_summary(current, exception_count=4, unmatched_stock="0.100000000000000003")

    result = runner.invoke(
        app,
        [
            "analyze",
            "variance",
            "--current",
            str(current),
            "--previous",
            str(previous),
            "--output",
            str(output),
            "--amount-threshold",
            "0.100000000000000005",
            "--percent-threshold",
            "999999",
        ],
    )

    assert result.exit_code == 0, result.output
    text = (output / "variance_analysis.json").read_text(encoding="utf-8")
    payload = json.loads(text)
    exact_payload = json.loads(text, parse_float=Decimal)
    rows = {row["metric"]: row for row in payload["variances"]}
    assert rows["executive_summary.unmatched_stock_amount"]["threshold_flag"] is False
    assert exact_payload["thresholds"]["amount_threshold"] == Decimal("0.100000000000000005")
    assert payload["schema_version"] == 3
    assert payload["threshold_policy"]["schema_version"] == 2
    assert payload["threshold_policy"]["financial_input_policy"] == STRICT_FINANCIAL_INPUT_POLICY
    assert payload["threshold_policy"]["amount_threshold"] == "0.100000000000000005"
    assert len(payload["threshold_policy"]["policy_digest"]) == 64
    assert read_variance_thresholds(payload).amount_threshold == Decimal("0.100000000000000005")


def test_percent_threshold_decision_is_exact_and_context_independent() -> None:
    with localcontext() as context:
        context.prec = 3
        context.rounding = ROUND_DOWN
        frame = variance_frame(
            {"metric": Decimal("1.001000000000000003")},
            {"metric": Decimal("1")},
            amount_threshold="0",
            percent_threshold="0.1000000000000005",
        )

    row = frame.iloc[0]
    assert bool(row["threshold_flag"]) is False
    assert row["amount_variance"] == Decimal("0.00")
    assert row["percentage_variance"] == Decimal("0.10")


def test_exact_json_decimal_encoding_is_context_independent_and_collision_safe() -> None:
    value = Decimal("123456789012345678901234567890.10000000000000000500")
    with localcontext() as context:
        context.prec = 3
        context.rounding = ROUND_DOWN
        text = exact_json_dumps(
            {
                "value": value,
                "negative_zero": Decimal("-0.00"),
                "source_text": "\x00reconforge:exact-decimal:0",
            },
        )

    payload = json.loads(text, parse_float=Decimal)
    assert payload["value"] == Decimal("123456789012345678901234567890.100000000000000005")
    assert payload["negative_zero"] == 0
    assert payload["source_text"] == "\x00reconforge:exact-decimal:0"
    with pytest.raises(ValueError, match="must be finite"):
        exact_json_dumps({"value": Decimal("NaN")})


@pytest.mark.parametrize(
    ("option", "value", "message"),
    [
        ("--amount-threshold", "-0.01", "amount_threshold cannot be negative"),
        ("--percent-threshold", "1e-3", "scientific notation is not allowed"),
        ("--percent-threshold", "NaN", "must be a finite"),
    ],
)
def test_cli_variance_rejects_invalid_threshold_without_artifacts(
    tmp_path: Path,
    option: str,
    value: str,
    message: str,
) -> None:
    previous = tmp_path / "jan"
    current = tmp_path / "feb"
    output = tmp_path / "variance"
    _write_management_summary(previous, exception_count=4, unmatched_stock="1")
    _write_management_summary(current, exception_count=4, unmatched_stock="2")

    result = runner.invoke(
        app,
        [
            "analyze",
            "variance",
            "--current",
            str(current),
            "--previous",
            str(previous),
            "--output",
            str(output),
            option,
            value,
        ],
    )

    assert result.exit_code == 1
    assert message in result.output
    assert "Traceback" not in result.output
    assert not output.exists()


def test_variance_missing_input_handled_cleanly(tmp_path: Path) -> None:
    previous = tmp_path / "jan"
    _write_management_summary(previous, exception_count=10, unmatched_stock=100)
    result = runner.invoke(
        app,
        ["analyze", "variance", "--current", str(tmp_path / "missing"), "--previous", str(previous), "--output", str(tmp_path / "out")],
    )
    assert result.exit_code == 1
    assert "Summary folder not found" in result.output
    assert "Traceback" not in result.output


def test_variance_malformed_summary_has_safe_error(tmp_path: Path) -> None:
    current = tmp_path / "current"
    previous = tmp_path / "previous"
    current.mkdir()
    previous.mkdir()
    (current / "management_pack.json").write_text("{bad json", encoding="utf-8")
    (previous / "management_pack.json").write_text("{bad json", encoding="utf-8")
    result = runner.invoke(
        app,
        ["analyze", "variance", "--current", str(current), "--previous", str(previous), "--output", str(tmp_path / "out")],
    )
    assert result.exit_code == 1
    assert "No summary metrics found" in result.output


def test_variance_loads_summary_csv(tmp_path: Path) -> None:
    period = tmp_path / "period"
    period.mkdir()
    (period / "stock_gl_summary.csv").write_text("metric,count\nexceptions,3\n", encoding="utf-8")
    metrics = load_summary_metrics(period)
    assert metrics["stock_gl_summary.exceptions"] == 3


def test_variance_loaders_preserve_json_and_csv_numeric_lexemes(tmp_path: Path) -> None:
    json_period = tmp_path / "json-period"
    json_period.mkdir()
    (json_period / "management_pack.json").write_text(
        """{
  "executive_summary": [
    {"metric": "exact", "value": 0.100000000000000003},
    {"metric": "scientific_rejected", "value": 1e-3}
  ]
}
""",
        encoding="utf-8",
    )
    json_metrics = load_summary_metrics(json_period)
    assert json_metrics["executive_summary.exact"] == Decimal("0.100000000000000003")
    assert "executive_summary.scientific_rejected" not in json_metrics

    csv_period = tmp_path / "csv-period"
    csv_period.mkdir()
    (csv_period / "custom_summary.csv").write_text(
        "metric,value\nexact,0.100000000000000003\n",
        encoding="utf-8",
    )
    csv_metrics = load_summary_metrics(csv_period)
    assert csv_metrics["custom_summary.exact"] == Decimal("0.100000000000000003")


def test_variance_analysis_preserves_decimal_precision(tmp_path: Path) -> None:
    previous = tmp_path / "previous"
    current = tmp_path / "current"
    _write_management_summary(previous, exception_count=4, unmatched_stock="0.10")
    _write_management_summary(current, exception_count=4, unmatched_stock="0.20")

    artifacts = analyze_variance(current, previous, tmp_path / "variance-decimal")
    payload = json.loads(artifacts.json_path.read_text(encoding="utf-8"))
    rows = {row["metric"]: row for row in payload["variances"]}
    assert Decimal(str(rows["executive_summary.unmatched_stock_amount"]["amount_variance"])) == Decimal("0.10")
    assert Decimal(str(rows["executive_summary.unmatched_stock_amount"]["percentage_variance"])) == Decimal("100")


def test_variance_service_retains_finite_float_compatibility_reader(tmp_path: Path) -> None:
    previous = tmp_path / "previous"
    current = tmp_path / "current"
    _write_management_summary(previous, exception_count=4, unmatched_stock="1")
    _write_management_summary(current, exception_count=4, unmatched_stock="2")

    with pytest.warns(LegacyFinancialInputWarning, match="deprecated"):
        artifacts = analyze_variance(
            current,
            previous,
            tmp_path / "legacy-float",
            amount_threshold=0.1,
            percent_threshold=20.0,
            financial_input_policy=LEGACY_FINANCIAL_INPUT_POLICY,
        )
    policy = json.loads(artifacts.json_path.read_text(encoding="utf-8"))["threshold_policy"]
    assert policy["amount_threshold"] == "0.1"
    assert policy["percent_threshold"] == "20"
    assert policy["financial_input_policy"] == LEGACY_FINANCIAL_INPUT_POLICY

    invalid_output = tmp_path / "invalid-float"
    with pytest.raises(ValueError, match="must be a finite"):
        analyze_variance(current, previous, invalid_output, amount_threshold=float("inf"))
    assert not invalid_output.exists()


def test_variance_service_strict_policy_rejects_float_before_artifacts(tmp_path: Path) -> None:
    previous = tmp_path / "previous"
    current = tmp_path / "current"
    output = tmp_path / "strict-float"
    _write_management_summary(previous, exception_count=4, unmatched_stock="1")
    _write_management_summary(current, exception_count=4, unmatched_stock="2")

    with pytest.raises(ValueError, match="strict-financial-input-v2"):
        analyze_variance(
            current,
            previous,
            output,
            amount_threshold=0.1,
            financial_input_policy=STRICT_FINANCIAL_INPUT_POLICY,
        )

    assert not output.exists()


@pytest.mark.parametrize(
    ("payload", "expected_amount", "expected_percent"),
    [
        (
            {"thresholds": {"amount_threshold": 0.1, "percent_threshold": 10.0}},
            Decimal("0.1"),
            Decimal("10.0"),
        ),
        (
            {"schema_version": 1, "thresholds": {"amount_threshold": "0.100", "percent_threshold": "20"}},
            Decimal("0.100"),
            Decimal("20"),
        ),
    ],
)
def test_variance_threshold_reader_accepts_legacy_v1_artifacts(
    payload: dict[str, object],
    expected_amount: Decimal,
    expected_percent: Decimal,
) -> None:
    thresholds = read_variance_thresholds(payload)
    assert thresholds.artifact_schema_version == 1
    assert thresholds.threshold_policy_schema_version == 1
    assert thresholds.financial_input_policy == LEGACY_FINANCIAL_INPUT_POLICY
    assert thresholds.amount_threshold == expected_amount
    assert thresholds.percent_threshold == expected_percent


def test_variance_threshold_reader_accepts_historical_v2_policy() -> None:
    payload = {
        "schema_version": 2,
        "threshold_policy": {
            "schema_version": 1,
            "value_encoding": "canonical-decimal-string",
            "amount_threshold": "0.25",
            "percent_threshold": "10",
            "amount_comparison": "disabled-at-zero-otherwise-absolute-unrounded-gte",
            "percent_comparison": "absolute-unrounded-gte",
            "display_rounding": "ROUND_HALF_EVEN_2DP",
            "digest_algorithm": "sha256",
            "policy_digest": "3159ee6e25f5aa1f6d33f2f9d9576d641bfbb8a8e28aee86b214aa6348442851",
        },
    }

    thresholds = read_variance_thresholds(payload)

    assert thresholds.artifact_schema_version == 2
    assert thresholds.threshold_policy_schema_version == 1
    assert thresholds.financial_input_policy == LEGACY_FINANCIAL_INPUT_POLICY
    assert thresholds.amount_threshold == Decimal("0.25")
    assert thresholds.percent_threshold == Decimal("10")


def test_variance_threshold_reader_rejects_unknown_or_tampered_policy(tmp_path: Path) -> None:
    previous = tmp_path / "previous"
    current = tmp_path / "current"
    _write_management_summary(previous, exception_count=4, unmatched_stock="1")
    _write_management_summary(current, exception_count=4, unmatched_stock="2")
    artifacts = analyze_variance(current, previous, tmp_path / "variance", amount_threshold="0.25")
    payload = json.loads(artifacts.json_path.read_text(encoding="utf-8"))

    payload["threshold_policy"]["amount_threshold"] = "0.26"
    with pytest.raises(ValueError, match="digest"):
        read_variance_thresholds(payload)

    policy_tamper = json.loads(artifacts.json_path.read_text(encoding="utf-8"))
    policy_tamper["threshold_policy"]["financial_input_policy"] = LEGACY_FINANCIAL_INPUT_POLICY
    with pytest.raises(ValueError, match="digest"):
        read_variance_thresholds(policy_tamper)

    unsupported_policy = json.loads(artifacts.json_path.read_text(encoding="utf-8"))
    unsupported_policy["threshold_policy"]["financial_input_policy"] = "unknown-v9"
    with pytest.raises(ValueError, match="financial_input_policy is unsupported"):
        read_variance_thresholds(unsupported_policy)
    with pytest.raises(ValueError, match="unsupported variance report schema_version"):
        read_variance_thresholds({"schema_version": 99, "thresholds": {}})
    with pytest.raises(ValueError, match="unsupported variance report schema_version"):
        read_variance_thresholds({"schema_version": True, "thresholds": {}})

    canonical_payload = json.loads(artifacts.json_path.read_text(encoding="utf-8"))
    canonical_payload["threshold_policy"]["amount_threshold"] = "0.250"
    with pytest.raises(ValueError, match="not canonical"):
        read_variance_thresholds(canonical_payload)


def test_variance_v3_and_historical_artifacts_validate_against_documented_schema(tmp_path: Path) -> None:
    previous = tmp_path / "previous"
    current = tmp_path / "current"
    _write_management_summary(previous, exception_count=4, unmatched_stock="1")
    _write_management_summary(current, exception_count=4, unmatched_stock="2")
    artifacts = analyze_variance(current, previous, tmp_path / "variance", amount_threshold="0.100000000000000005")
    payload = json.loads(artifacts.json_path.read_text(encoding="utf-8"))
    schema = json.loads(Path("docs/schemas/variance_report.schema.json").read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)

    Draft202012Validator.check_schema(schema)
    validator.validate(payload)
    validator.validate(
        {
            "schema_version": 2,
            "current": "current",
            "previous": "previous",
            "summary": [],
            "variances": [],
            "thresholds": {"amount_threshold": 0.25, "percent_threshold": 10},
            "threshold_policy": {
                "schema_version": 1,
                "value_encoding": "canonical-decimal-string",
                "amount_threshold": "0.25",
                "percent_threshold": "10",
                "amount_comparison": "disabled-at-zero-otherwise-absolute-unrounded-gte",
                "percent_comparison": "absolute-unrounded-gte",
                "display_rounding": "ROUND_HALF_EVEN_2DP",
                "digest_algorithm": "sha256",
                "policy_digest": "3159ee6e25f5aa1f6d33f2f9d9576d641bfbb8a8e28aee86b214aa6348442851",
            },
            "analysis_boundary": "Historical v2 artifact",
        },
    )
    validator.validate(
        {
            "current": "current",
            "previous": "previous",
            "summary": [],
            "variances": [],
            "thresholds": {"amount_threshold": 0.0, "percent_threshold": 10.0},
            "analysis_boundary": "Legacy v1 artifact",
        },
    )

    missing_policy = json.loads(artifacts.json_path.read_text(encoding="utf-8"))
    del missing_policy["threshold_policy"]["financial_input_policy"]
    assert list(validator.iter_errors(missing_policy))

    historical_with_future_field = {
        **json.loads(artifacts.json_path.read_text(encoding="utf-8")),
        "schema_version": 2,
    }
    assert list(validator.iter_errors(historical_with_future_field))
