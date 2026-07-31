"""Local export-based variance analysis."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from html import escape
from pathlib import Path

import pandas as pd

from reconforge.io.excel import write_excel_workbook
from reconforge.io.generated import (
    GeneratedArtifactError,
    read_generated_csv_document,
    read_generated_json_document,
)
from reconforge.io.writers import canonical_decimal_text, ensure_output_dir, exact_json_dumps, frame_to_records
from reconforge.utils.money import (
    LEGACY_FINANCIAL_INPUT_POLICY,
    STRICT_FINANCIAL_INPUT_POLICY,
    FinancialInputPolicy,
    InvalidAmountError,
    parse_amount,
    validate_financial_input_policy,
)

VARIANCE_REPORT_SCHEMA_VERSION = 3
VARIANCE_THRESHOLD_POLICY_SCHEMA_VERSION = 2
_AMOUNT_COMPARISON_POLICY = "disabled-at-zero-otherwise-absolute-unrounded-gte"
_PERCENT_COMPARISON_POLICY = "absolute-unrounded-gte"
_DISPLAY_ROUNDING_POLICY = "ROUND_HALF_EVEN_2DP"
_REPORT_QUANTUM = Decimal("0.01")
_ONE_HUNDRED = Decimal("100")
ThresholdInput = Decimal | str | int
LegacyThresholdInput = ThresholdInput | float


@dataclass(frozen=True)
class VarianceAnalysisArtifacts:
    """Generated variance analysis artifacts."""

    workbook_path: Path
    csv_path: Path
    json_path: Path
    html_path: Path
    markdown_path: Path


@dataclass(frozen=True)
class VarianceThresholdPolicy:
    """Exact decision thresholds recovered from a variance report contract."""

    amount_threshold: Decimal
    percent_threshold: Decimal
    artifact_schema_version: int
    threshold_policy_schema_version: int
    financial_input_policy: FinancialInputPolicy

    def _digest_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.threshold_policy_schema_version,
            "value_encoding": "canonical-decimal-string",
            "amount_threshold": canonical_decimal_text(self.amount_threshold),
            "percent_threshold": canonical_decimal_text(self.percent_threshold),
            "amount_comparison": _AMOUNT_COMPARISON_POLICY,
            "percent_comparison": _PERCENT_COMPARISON_POLICY,
            "display_rounding": _DISPLAY_ROUNDING_POLICY,
        }
        if self.threshold_policy_schema_version >= 2:
            payload["financial_input_policy"] = self.financial_input_policy
        return payload

    @property
    def policy_digest(self) -> str:
        encoded = json.dumps(
            self._digest_payload(),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def to_canonical_dict(self) -> dict[str, object]:
        return {
            **self._digest_payload(),
            "digest_algorithm": "sha256",
            "policy_digest": self.policy_digest,
        }


def _threshold(
    value: LegacyThresholdInput,
    *,
    field: str,
    financial_input_policy: FinancialInputPolicy,
) -> Decimal:
    try:
        parsed = parse_amount(value, input_policy=financial_input_policy)
    except (InvalidAmountError, TypeError) as exc:
        raise ValueError(f"{field} must be a finite plain-decimal value: {exc}") from exc
    if parsed < 0:
        raise ValueError(f"{field} cannot be negative")
    return parsed


def _resolve_thresholds(
    amount_threshold: LegacyThresholdInput,
    percent_threshold: LegacyThresholdInput,
    *,
    artifact_schema_version: int,
    threshold_policy_schema_version: int,
    financial_input_policy: FinancialInputPolicy,
) -> VarianceThresholdPolicy:
    financial_input_policy = validate_financial_input_policy(financial_input_policy)
    return VarianceThresholdPolicy(
        amount_threshold=_threshold(
            amount_threshold,
            field="amount_threshold",
            financial_input_policy=financial_input_policy,
        ),
        percent_threshold=_threshold(
            percent_threshold,
            field="percent_threshold",
            financial_input_policy=financial_input_policy,
        ),
        artifact_schema_version=artifact_schema_version,
        threshold_policy_schema_version=threshold_policy_schema_version,
        financial_input_policy=financial_input_policy,
    )


def read_variance_thresholds(payload: Mapping[str, object]) -> VarianceThresholdPolicy:
    """Read thresholds from current v3 or historical unversioned/v1/v2 artifacts."""

    raw_version = payload.get("schema_version")
    if raw_version is None or (isinstance(raw_version, int) and not isinstance(raw_version, bool) and raw_version == 1):
        raw_thresholds = payload.get("thresholds")
        if not isinstance(raw_thresholds, Mapping):
            raise ValueError("legacy variance report thresholds must be an object")
        if "amount_threshold" not in raw_thresholds or "percent_threshold" not in raw_thresholds:
            raise ValueError("legacy variance report thresholds are incomplete")
        return _resolve_thresholds(
            raw_thresholds["amount_threshold"],
            raw_thresholds["percent_threshold"],
            artifact_schema_version=1,
            threshold_policy_schema_version=1,
            financial_input_policy=LEGACY_FINANCIAL_INPUT_POLICY,
        )
    if (
        not isinstance(raw_version, int)
        or isinstance(raw_version, bool)
        or raw_version not in {2, VARIANCE_REPORT_SCHEMA_VERSION}
    ):
        raise ValueError(f"unsupported variance report schema_version: {raw_version}")

    raw_policy = payload.get("threshold_policy")
    if not isinstance(raw_policy, Mapping):
        raise ValueError("variance report threshold_policy must be an object")
    raw_policy_version = raw_policy.get("schema_version")
    if (
        not isinstance(raw_policy_version, int)
        or isinstance(raw_policy_version, bool)
        or raw_policy_version != (1 if raw_version == 2 else VARIANCE_THRESHOLD_POLICY_SCHEMA_VERSION)
    ):
        raise ValueError(f"unsupported variance threshold policy schema_version: {raw_policy_version}")
    expected_metadata = {
        "value_encoding": "canonical-decimal-string",
        "amount_comparison": _AMOUNT_COMPARISON_POLICY,
        "percent_comparison": _PERCENT_COMPARISON_POLICY,
        "display_rounding": _DISPLAY_ROUNDING_POLICY,
        "digest_algorithm": "sha256",
    }
    for field, expected in expected_metadata.items():
        if raw_policy.get(field) != expected:
            raise ValueError(f"variance threshold policy {field} is unsupported")
    financial_input_policy: FinancialInputPolicy
    if raw_version == 2:
        if "financial_input_policy" in raw_policy:
            raise ValueError("variance threshold policy financial_input_policy is unsupported for schema v2")
        financial_input_policy = LEGACY_FINANCIAL_INPUT_POLICY
    else:
        try:
            financial_input_policy = validate_financial_input_policy(raw_policy.get("financial_input_policy"))
        except InvalidAmountError as exc:
            raise ValueError("variance threshold policy financial_input_policy is unsupported") from exc
    raw_amount = raw_policy.get("amount_threshold")
    raw_percent = raw_policy.get("percent_threshold")
    if not isinstance(raw_amount, str) or not isinstance(raw_percent, str):
        raise ValueError("variance threshold policy values must be canonical decimal strings")
    thresholds = _resolve_thresholds(
        raw_amount,
        raw_percent,
        artifact_schema_version=raw_version,
        threshold_policy_schema_version=raw_policy_version,
        financial_input_policy=financial_input_policy,
    )
    if raw_amount != canonical_decimal_text(thresholds.amount_threshold) or raw_percent != canonical_decimal_text(
        thresholds.percent_threshold
    ):
        raise ValueError("variance threshold policy values are not canonical decimal strings")
    if raw_policy.get("policy_digest") != thresholds.policy_digest:
        raise ValueError("variance threshold policy digest does not match its canonical values")
    return thresholds


def _exact_subtract(left: Decimal, right: Decimal) -> Decimal:
    values = (left, right)
    max_adjusted = max((value.adjusted() for value in values if value), default=0)
    min_exponent = min((int(value.as_tuple().exponent) for value in values), default=0)
    with localcontext() as context:
        context.prec = max(28, max_adjusted - min_exponent + 3)
        return left - right


def _exact_multiply(left: Decimal, right: Decimal) -> Decimal:
    with localcontext() as context:
        context.prec = max(28, len(left.as_tuple().digits) + len(right.as_tuple().digits) + 2)
        return left * right


def _quantize_for_report(value: Decimal) -> Decimal:
    integer_digits = max(1, value.adjusted() + 1) if value else 1
    with localcontext() as context:
        context.prec = max(28, len(value.as_tuple().digits) + 2, integer_digits + 4)
        context.rounding = ROUND_HALF_EVEN
        return value.quantize(_REPORT_QUANTUM, rounding=ROUND_HALF_EVEN)


def _percentage_for_report(amount_variance: Decimal, previous_value: Decimal) -> Decimal:
    numerator = _exact_multiply(amount_variance, _ONE_HUNDRED)
    denominator = abs(previous_value)
    integer_digits = max(1, numerator.adjusted() - denominator.adjusted() + 2) if numerator else 1
    with localcontext() as context:
        context.prec = max(
            34,
            integer_digits + 8,
            len(numerator.as_tuple().digits) + len(denominator.as_tuple().digits) + 8,
        )
        context.rounding = ROUND_HALF_EVEN
        percentage = numerator / denominator
    return _quantize_for_report(percentage)


def _percent_threshold_met(amount_variance: Decimal, previous_value: Decimal, percent_limit: Decimal) -> bool:
    left = _exact_multiply(abs(amount_variance), _ONE_HUNDRED)
    right = _exact_multiply(percent_limit, abs(previous_value))
    return left >= right


def _clean(value: object) -> str:
    text = str(value).strip()
    return "" if text.lower() in {"nan", "nat", "none", "null", "<na>"} else text


def _md_escape(value: object) -> str:
    return _clean(value).replace("<", "&lt;").replace(">", "&gt;")


def _numeric(value: object) -> Decimal | None:
    try:
        return parse_amount(str(value).replace(",", ""))
    except (InvalidAmountError, TypeError):
        return None


def _add_metric(metrics: dict[str, Decimal], key: str, value: object) -> None:
    clean_key = _clean(key)
    numeric_value = _numeric(value)
    if clean_key and numeric_value is not None:
        metrics[clean_key] = numeric_value


def _extract_metric_records(records: object, prefix: str, metrics: dict[str, Decimal]) -> None:
    if not isinstance(records, list):
        return
    for record in records:
        if not isinstance(record, dict):
            continue
        metric = record.get("metric")
        if metric is None:
            continue
        value = record.get("value", record.get("count"))
        key = f"{prefix}.{metric}" if prefix else str(metric)
        _add_metric(metrics, key, value)


def _extract_json_metrics(path: Path, metrics: dict[str, Decimal]) -> None:
    try:
        payload = read_generated_json_document(path).payload
    except GeneratedArtifactError:
        return
    stem = path.stem
    for key, value in payload.items():
        if key == "trend" and isinstance(value, dict):
            _extract_metric_records(value.get("periods"), "trend", metrics)
            continue
        if isinstance(value, list):
            _extract_metric_records(value, key, metrics)
        elif isinstance(value, (int, str)):
            _add_metric(metrics, f"{stem}.{key}", value)


def _extract_csv_metrics(path: Path, metrics: dict[str, Decimal]) -> None:
    try:
        frame = read_generated_csv_document(path, mode="exact-text").frame
    except GeneratedArtifactError:
        return
    if frame.empty or "metric" not in frame.columns:
        return
    value_column = "value" if "value" in frame.columns else "count" if "count" in frame.columns else ""
    if not value_column:
        return
    for _, row in frame.iterrows():
        _add_metric(metrics, f"{path.stem}.{row['metric']}", row[value_column])


def load_summary_metrics(input_path: Path | str) -> dict[str, Decimal]:
    """Load numeric summary metrics from a local ReconForge output folder."""

    base = Path(input_path)
    if not base.exists() or not base.is_dir():
        raise FileNotFoundError(f"Summary folder not found: {base}")
    metrics: dict[str, Decimal] = {}
    for filename in ["management_pack.json", "period_comparison.json", "close_report.json"]:
        path = base / filename
        if path.exists() and path.is_file():
            _extract_json_metrics(path, metrics)
    for path in sorted(base.glob("*summary.csv")) + sorted(base.glob("*control_value_summary.csv")):
        if path.is_file():
            _extract_csv_metrics(path, metrics)
    if not metrics:
        raise ValueError(f"No summary metrics found in: {base}")
    return metrics


def variance_frame(
    current_metrics: dict[str, Decimal],
    previous_metrics: dict[str, Decimal],
    *,
    amount_threshold: LegacyThresholdInput = Decimal("0"),
    percent_threshold: LegacyThresholdInput = Decimal("10"),
    financial_input_policy: FinancialInputPolicy = STRICT_FINANCIAL_INPUT_POLICY,
) -> pd.DataFrame:
    """Build a deterministic variance table from two metric dictionaries."""

    thresholds = _resolve_thresholds(
        amount_threshold,
        percent_threshold,
        artifact_schema_version=VARIANCE_REPORT_SCHEMA_VERSION,
        threshold_policy_schema_version=VARIANCE_THRESHOLD_POLICY_SCHEMA_VERSION,
        financial_input_policy=financial_input_policy,
    )
    return _variance_frame_with_thresholds(current_metrics, previous_metrics, thresholds=thresholds)


def _variance_frame_with_thresholds(
    current_metrics: dict[str, Decimal],
    previous_metrics: dict[str, Decimal],
    *,
    thresholds: VarianceThresholdPolicy,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for metric in sorted(set(current_metrics) | set(previous_metrics)):
        current_value = current_metrics.get(metric)
        previous_value = previous_metrics.get(metric)
        current_amount = current_value if current_value is not None else Decimal("0")
        previous_amount = previous_value if previous_value is not None else Decimal("0")
        amount_variance = _exact_subtract(current_amount, previous_amount)
        percent_variance: Decimal | None
        percent_threshold_met = False
        if previous_value is None or previous_value == Decimal("0"):
            percent_variance = None if current_value is None else Decimal("0")
            if percent_variance is not None:
                percent_threshold_met = abs(percent_variance) >= thresholds.percent_threshold
        else:
            percent_variance = _percentage_for_report(amount_variance, previous_value)
            percent_threshold_met = _percent_threshold_met(
                amount_variance,
                previous_value,
                thresholds.percent_threshold,
            )
        threshold_flag = (
            abs(amount_variance) >= thresholds.amount_threshold if thresholds.amount_threshold > 0 else False
        )
        threshold_flag = threshold_flag or percent_threshold_met
        rows.append(
            {
                "metric": metric,
                "previous_value": previous_value,
                "current_value": current_value,
                "amount_variance": _quantize_for_report(amount_variance),
                "percentage_variance": percent_variance if percent_variance is not None else "",
                "threshold_flag": threshold_flag,
                "explanation": "",
            },
        )
    return pd.DataFrame(rows)


def _summary_frame(frame: pd.DataFrame) -> pd.DataFrame:
    flagged = int(frame["threshold_flag"].astype(bool).sum()) if not frame.empty else 0
    return pd.DataFrame(
        [
            {"metric": "metrics_compared", "value": len(frame), "meaning": "Numeric local summary metrics compared."},
            {
                "metric": "threshold_flags",
                "value": flagged,
                "meaning": "Metrics exceeding configured amount or percentage thresholds.",
            },
            {
                "metric": "analysis_boundary",
                "value": "workflow_support",
                "meaning": "No savings, audit opinion, or financial statement conclusion is inferred.",
            },
        ],
    )


def _html_table(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "<p>No variance metrics found.</p>"
    columns = [
        "metric",
        "previous_value",
        "current_value",
        "amount_variance",
        "percentage_variance",
        "threshold_flag",
        "explanation",
    ]
    visible = frame[[column for column in columns if column in frame.columns]]
    header = "".join(f"<th>{escape(column.replace('_', ' ').title())}</th>" for column in visible.columns)
    rows = []
    for _, row in visible.iterrows():
        rows.append("<tr>" + "".join(f"<td>{escape(_clean(value))}</td>" for value in row.tolist()) + "</tr>")
    return f"<table><thead><tr>{header}</tr></thead><tbody>{''.join(rows)}</tbody></table>"


def _write_html(path: Path, summary: pd.DataFrame, variances: pd.DataFrame) -> None:
    cards = "".join(
        f"<section class='card'><span>{escape(str(row['metric']).replace('_', ' ').title())}</span><strong>{escape(str(row['value']))}</strong></section>"
        for _, row in summary.iterrows()
        if row["metric"] != "analysis_boundary"
    )
    path.write_text(
        f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ReconForge Variance Analysis</title>
  <style>
    body {{ margin: 0; font-family: Inter, Segoe UI, Arial, sans-serif; background: #f6f8fb; color: #182230; }}
    header {{ background: #17324d; color: #fff; padding: 24px 36px; }}
    header p {{ color: #dbe8f3; margin: 8px 0 0; }}
    main {{ max-width: 1180px; margin: 0 auto; padding: 28px; }}
    .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; }}
    .card {{ background: #fff; border: 1px solid #dce3ea; border-radius: 8px; padding: 14px; }}
    .card span {{ display: block; color: #667085; font-size: 13px; }}
    .card strong {{ display: block; margin-top: 6px; font-size: 24px; }}
    section {{ margin-top: 26px; }}
    table {{ border-collapse: collapse; width: 100%; background: #fff; border: 1px solid #dce3ea; }}
    th, td {{ padding: 9px 10px; border-bottom: 1px solid #edf1f5; text-align: left; font-size: 13px; vertical-align: top; }}
    th {{ background: #e8eef5; color: #17324d; }}
  </style>
</head>
<body>
  <header>
    <h1>ReconForge Variance Analysis</h1>
    <p>Local comparison of generated summary outputs. No savings, audit opinion, or financial statement conclusion is inferred.</p>
  </header>
  <main>
    <div class="cards">{cards}</div>
    <section>
      <h2>Variance Register</h2>
      {_html_table(variances)}
    </section>
  </main>
</body>
</html>
""",
        encoding="utf-8",
    )


def _write_markdown(path: Path, summary: pd.DataFrame, variances: pd.DataFrame) -> None:
    lines = [
        "# ReconForge Variance Analysis",
        "",
        "Local comparison of generated summary outputs. This report does not infer savings, provide an audit opinion, or conclude on financial statements.",
        "",
        "## Summary",
        "",
        *[f"- {_md_escape(row['metric'])}: {_md_escape(row['value'])}" for _, row in summary.iterrows()],
        "",
        "## Variances",
        "",
    ]
    if variances.empty:
        lines.append("No variance metrics found.")
    else:
        for _, row in variances.iterrows():
            lines.append(
                f"- `{_md_escape(row['metric'])}` previous={_md_escape(row['previous_value'])}, "
                f"current={_md_escape(row['current_value'])}, variance={_md_escape(row['amount_variance'])}, "
                f"pct={_md_escape(row['percentage_variance'])}, flag={_md_escape(row['threshold_flag'])}",
            )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def analyze_variance(
    current_path: Path | str,
    previous_path: Path | str,
    output_path: Path | str,
    *,
    amount_threshold: LegacyThresholdInput = Decimal("0"),
    percent_threshold: LegacyThresholdInput = Decimal("10"),
    financial_input_policy: FinancialInputPolicy = STRICT_FINANCIAL_INPUT_POLICY,
) -> VarianceAnalysisArtifacts:
    """Compare two local ReconForge output folders and write variance artifacts."""

    thresholds = _resolve_thresholds(
        amount_threshold,
        percent_threshold,
        artifact_schema_version=VARIANCE_REPORT_SCHEMA_VERSION,
        threshold_policy_schema_version=VARIANCE_THRESHOLD_POLICY_SCHEMA_VERSION,
        financial_input_policy=financial_input_policy,
    )
    current_metrics = load_summary_metrics(current_path)
    previous_metrics = load_summary_metrics(previous_path)
    variances = _variance_frame_with_thresholds(
        current_metrics,
        previous_metrics,
        thresholds=thresholds,
    )
    summary = _summary_frame(variances)
    output_dir = ensure_output_dir(output_path)
    workbook_path = write_excel_workbook(
        {"Variance Summary": summary, "Variance Register": variances}, output_dir / "variance_analysis.xlsx"
    )
    csv_path = output_dir / "variance_analysis.csv"
    variances.to_csv(csv_path, index=False)
    json_path = output_dir / "variance_analysis.json"
    payload = {
        "schema_version": VARIANCE_REPORT_SCHEMA_VERSION,
        "current": str(current_path),
        "previous": str(previous_path),
        "summary": frame_to_records(summary),
        "variances": frame_to_records(variances),
        # Preserve the legacy numeric keys while encoding Decimal directly as
        # JSON numbers. New readers should prefer the canonical policy below.
        "thresholds": {
            "amount_threshold": thresholds.amount_threshold,
            "percent_threshold": thresholds.percent_threshold,
        },
        "threshold_policy": thresholds.to_canonical_dict(),
        "analysis_boundary": "No savings, audit opinion, or financial statement conclusion is inferred.",
    }
    json_path.write_text(exact_json_dumps(payload), encoding="utf-8")
    html_path = output_dir / "variance_analysis.html"
    markdown_path = output_dir / "variance_summary.md"
    _write_html(html_path, summary, variances)
    _write_markdown(markdown_path, summary, variances)
    return VarianceAnalysisArtifacts(
        workbook_path=workbook_path,
        csv_path=csv_path,
        json_path=json_path,
        html_path=html_path,
        markdown_path=markdown_path,
    )
