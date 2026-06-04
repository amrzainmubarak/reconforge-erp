"""Local export-based variance analysis."""

from __future__ import annotations

import json
from dataclasses import dataclass
from html import escape
from pathlib import Path

import pandas as pd

from reconforge.io.excel import write_excel_workbook
from reconforge.io.writers import ensure_output_dir, frame_to_records, json_default


@dataclass(frozen=True)
class VarianceAnalysisArtifacts:
    """Generated variance analysis artifacts."""

    workbook_path: Path
    csv_path: Path
    json_path: Path
    html_path: Path
    markdown_path: Path


def _clean(value: object) -> str:
    text = str(value).strip()
    return "" if text.lower() in {"nan", "nat", "none", "null", "<na>"} else text


def _md_escape(value: object) -> str:
    return _clean(value).replace("<", "&lt;").replace(">", "&gt;")


def _numeric(value: object) -> float | None:
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _add_metric(metrics: dict[str, float], key: str, value: object) -> None:
    clean_key = _clean(key)
    numeric_value = _numeric(value)
    if clean_key and numeric_value is not None:
        metrics[clean_key] = numeric_value


def _extract_metric_records(records: object, prefix: str, metrics: dict[str, float]) -> None:
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


def _extract_json_metrics(path: Path, metrics: dict[str, float]) -> None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(payload, dict):
        return
    stem = path.stem
    for key, value in payload.items():
        if key == "trend" and isinstance(value, dict):
            _extract_metric_records(value.get("periods"), "trend", metrics)
            continue
        if isinstance(value, list):
            _extract_metric_records(value, key, metrics)
        elif isinstance(value, (int, float, str)):
            _add_metric(metrics, f"{stem}.{key}", value)


def _extract_csv_metrics(path: Path, metrics: dict[str, float]) -> None:
    try:
        frame = pd.read_csv(path, keep_default_na=False)
    except (OSError, pd.errors.ParserError, UnicodeDecodeError):
        return
    if frame.empty or "metric" not in frame.columns:
        return
    value_column = "value" if "value" in frame.columns else "count" if "count" in frame.columns else ""
    if not value_column:
        return
    for _, row in frame.iterrows():
        _add_metric(metrics, f"{path.stem}.{row['metric']}", row[value_column])


def load_summary_metrics(input_path: Path | str) -> dict[str, float]:
    """Load numeric summary metrics from a local ReconForge output folder."""

    base = Path(input_path)
    if not base.exists() or not base.is_dir():
        raise FileNotFoundError(f"Summary folder not found: {base}")
    metrics: dict[str, float] = {}
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
    current_metrics: dict[str, float],
    previous_metrics: dict[str, float],
    *,
    amount_threshold: float = 0.0,
    percent_threshold: float = 10.0,
) -> pd.DataFrame:
    """Build a deterministic variance table from two metric dictionaries."""

    rows: list[dict[str, object]] = []
    for metric in sorted(set(current_metrics) | set(previous_metrics)):
        current_value = current_metrics.get(metric)
        previous_value = previous_metrics.get(metric)
        amount_variance = (current_value or 0.0) - (previous_value or 0.0)
        percent_variance: float | None
        if previous_value is None or previous_value == 0:
            percent_variance = None if current_value else 0.0
        else:
            percent_variance = (amount_variance / abs(previous_value)) * 100
        threshold_flag = abs(amount_variance) >= amount_threshold if amount_threshold > 0 else False
        if percent_variance is not None:
            threshold_flag = threshold_flag or abs(percent_variance) >= percent_threshold
        rows.append(
            {
                "metric": metric,
                "previous_value": previous_value,
                "current_value": current_value,
                "amount_variance": round(amount_variance, 2),
                "percentage_variance": round(percent_variance, 2) if percent_variance is not None else "",
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
            {"metric": "threshold_flags", "value": flagged, "meaning": "Metrics exceeding configured amount or percentage thresholds."},
            {"metric": "analysis_boundary", "value": "workflow_support", "meaning": "No savings, audit opinion, or financial statement conclusion is inferred."},
        ],
    )


def _html_table(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "<p>No variance metrics found.</p>"
    columns = ["metric", "previous_value", "current_value", "amount_variance", "percentage_variance", "threshold_flag", "explanation"]
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
    amount_threshold: float = 0.0,
    percent_threshold: float = 10.0,
) -> VarianceAnalysisArtifacts:
    """Compare two local ReconForge output folders and write variance artifacts."""

    current_metrics = load_summary_metrics(current_path)
    previous_metrics = load_summary_metrics(previous_path)
    variances = variance_frame(
        current_metrics,
        previous_metrics,
        amount_threshold=amount_threshold,
        percent_threshold=percent_threshold,
    )
    summary = _summary_frame(variances)
    output_dir = ensure_output_dir(output_path)
    workbook_path = write_excel_workbook({"Variance Summary": summary, "Variance Register": variances}, output_dir / "variance_analysis.xlsx")
    csv_path = output_dir / "variance_analysis.csv"
    variances.to_csv(csv_path, index=False)
    json_path = output_dir / "variance_analysis.json"
    with json_path.open("w", encoding="utf-8") as handle:
        json.dump(
            {
                "current": str(current_path),
                "previous": str(previous_path),
                "summary": frame_to_records(summary),
                "variances": frame_to_records(variances),
                "thresholds": {"amount_threshold": amount_threshold, "percent_threshold": percent_threshold},
                "analysis_boundary": "No savings, audit opinion, or financial statement conclusion is inferred.",
            },
            handle,
            indent=2,
            default=json_default,
        )
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
