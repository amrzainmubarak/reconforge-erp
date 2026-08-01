"""Multi-period exception comparison reporting."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Any, Literal

import pandas as pd

from reconforge.io.excel import write_excel_workbook
from reconforge.io.generated import GeneratedArtifactError, read_generated_json_document
from reconforge.io.writers import ensure_output_dir, frame_to_records, json_default
from reconforge.review.state import (
    EXCEPTION_FILE_CANDIDATES,
    collect_exception_frame,
    load_review_state,
    merge_review_state_with_exceptions,
)
from reconforge.utils.money import (
    LEGACY_FINANCIAL_INPUT_POLICY,
    STRICT_FINANCIAL_INPUT_POLICY,
    FinancialInputPolicy,
    InvalidAmountError,
    parse_amount,
    round_exact_money,
    validate_financial_input_policy,
)

SYNTHETIC_EXCEPTION_ID_PATTERN = re.compile(r"^EXC-\d+$", re.IGNORECASE)
PERIOD_COMPARISON_SCHEMA_VERSION = 2
PERIOD_COMPARISON_ALGORITHM_VERSION = "period-exception-fingerprint-v2"
_PERIOD_COMPARISON_ARTIFACT_TYPE = "reconforge-period-comparison"
_PERIOD_COMPARISON_INTEGRITY_BOUNDARY = (
    "Local content digests only; this artifact is not a signature, audit opinion, "
    "compliance certification, or proof of source-system authenticity."
)
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
RULE_FIELDS = ["rule_id", "control_id", "control", "check", "rule_name"]
DOCUMENT_FIELDS = [
    "reference",
    "source_document",
    "document_id",
    "work_order",
    "move_id",
    "entry_id",
    "po_number",
    "invoice_number",
    "return_id",
]
ITEM_FIELDS = [
    "product_code",
    "product_name",
    "customer_code",
    "customer_name",
    "equipment_serial",
    "category",
    "warehouse",
    "account_code",
    "cost_center",
]
DATE_FIELDS = ["date", "posting_date", "opened_date", "closed_date", "po_date", "invoice_date", "return_date"]


@dataclass(frozen=True)
class PeriodComparisonArtifacts:
    """Generated multi-period comparison artifacts."""

    workbook_path: Path
    html_path: Path
    json_path: Path
    markdown_path: Path


@dataclass(frozen=True)
class PeriodComparisonDocument:
    """A historical v1 or verified current period-comparison document."""

    schema_version: Literal[1, 2]
    verification_status: Literal["legacy-unverified", "verified"]
    payload: dict[str, Any]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_digest(payload: object) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
        default=json_default,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _period_input_manifest(periods: list[Path]) -> list[dict[str, Any]]:
    manifests: list[dict[str, Any]] = []
    filenames = sorted([*EXCEPTION_FILE_CANDIDATES, "review_state.json"])
    for index, period in enumerate(periods, start=1):
        files: list[dict[str, str | int]] = []
        for filename in filenames:
            path = period / filename
            if path.exists() and path.is_file():
                files.append(
                    {
                        "name": filename,
                        "bytes": path.stat().st_size,
                        "sha256": _sha256_file(path),
                    }
                )
        manifests.append({"period": f"period_{index}", "files": files})
    return manifests


def _clean(value: object) -> str:
    text = str(value).strip()
    return "" if text.lower() in {"nan", "nat", "none", "null", "<na>"} else text


def _amount_value(
    row: pd.Series,
    *,
    financial_input_policy: FinancialInputPolicy = STRICT_FINANCIAL_INPUT_POLICY,
) -> str:
    input_policy = validate_financial_input_policy(financial_input_policy)
    saw_invalid = False
    saw_zero = False
    for name in [
        "amount_impact",
        "amount",
        "total_cost",
        "actual_cost",
        "estimated_cost",
        "invoice_amount",
        "total_price",
    ]:
        if name not in row.index or not _clean(row.get(name)):
            continue
        value = row.get(name)
        try:
            amount = abs(
                round_exact_money(
                    parse_amount(
                        value,
                        input_policy=input_policy,
                    )
                )
            )
        except InvalidAmountError:
            saw_invalid = True
            continue
        if amount:
            return format(amount, "f")
        saw_zero = True
    if saw_zero or input_policy == LEGACY_FINANCIAL_INPUT_POLICY:
        return "0.00"
    if saw_invalid:
        return "invalid"
    if input_policy == STRICT_FINANCIAL_INPUT_POLICY:
        return "missing"
    return "0.00"


def _is_synthetic_exception_id(exception_id: str) -> bool:
    return bool(SYNTHETIC_EXCEPTION_ID_PATTERN.fullmatch(exception_id))


def _fingerprint_part(row: pd.Series, names: list[str]) -> str:
    values = []
    for name in names:
        if name in row.index:
            value = _clean(row.get(name, ""))
            if value:
                values.append(f"{name}={value.lower()}")
    return ";".join(values)


def _exception_key(
    row: pd.Series,
    *,
    financial_input_policy: FinancialInputPolicy,
) -> str:
    exception_id = _clean(row.get("exception_id", ""))
    if exception_id and not _is_synthetic_exception_id(exception_id):
        return f"id:{exception_id}"
    parts = [
        _fingerprint_part(row, ["source_file"]),
        _fingerprint_part(row, ["exception_type"]),
        _fingerprint_part(row, RULE_FIELDS),
        _fingerprint_part(row, DOCUMENT_FIELDS),
        _fingerprint_part(row, ITEM_FIELDS),
        f"amount={_amount_value(row, financial_input_policy=financial_input_policy)}",
        _fingerprint_part(row, DATE_FIELDS),
    ]
    return "fingerprint:" + "|".join(part for part in parts if part)


def _load_period(
    period_path: Path,
    period_index: int,
    *,
    financial_input_policy: FinancialInputPolicy,
) -> pd.DataFrame:
    exceptions = collect_exception_frame(
        period_path,
        financial_input_policy=financial_input_policy,
    )
    merged = merge_review_state_with_exceptions(exceptions, load_review_state(period_path / "review_state.json"))
    if merged.empty:
        return merged.assign(
            period=f"period_{period_index}", period_path=str(period_path), comparison_key=pd.Series(dtype=str)
        )
    output = merged.copy()
    output["period"] = f"period_{period_index}"
    output["period_path"] = str(period_path)
    output["comparison_key"] = [
        _exception_key(
            row,
            financial_input_policy=financial_input_policy,
        )
        for _, row in output.iterrows()
    ]
    return output


def _representative_rows(frame: pd.DataFrame, keys: set[str], category: str, period: str) -> pd.DataFrame:
    if frame.empty or not keys:
        return pd.DataFrame(columns=["comparison_category", "comparison_period", "comparison_key"])
    subset = frame[frame["comparison_key"].isin(keys)].copy()
    subset = subset.drop_duplicates("comparison_key", keep="first")
    subset.insert(0, "comparison_category", category)
    subset.insert(1, "comparison_period", period)
    return subset


def _summary_frame(
    *,
    periods: list[Path],
    frames: list[pd.DataFrame],
    new_keys: set[str],
    recurring_keys: set[str],
    resolved_keys: set[str],
    escalated_keys: set[str],
    accepted_risk_keys: set[str],
    trend: pd.DataFrame,
) -> pd.DataFrame:
    current_trend = trend.iloc[-1].to_dict() if not trend.empty else {}
    return pd.DataFrame(
        [
            {
                "metric": "periods_compared",
                "value": len(periods),
                "meaning": "Number of local output folders compared.",
            },
            {
                "metric": "current_period_exceptions",
                "value": len(frames[-1]) if frames else 0,
                "meaning": "Exceptions found in the final input period.",
            },
            {
                "metric": "new_exceptions",
                "value": len(new_keys),
                "meaning": "Current-period exceptions not seen in earlier periods.",
            },
            {
                "metric": "recurring_exceptions",
                "value": len(recurring_keys),
                "meaning": "Current-period exceptions also seen in at least one earlier period.",
            },
            {
                "metric": "resolved_exceptions",
                "value": len(resolved_keys),
                "meaning": "Earlier-period exceptions not present in the current period.",
            },
            {
                "metric": "escalated_exceptions",
                "value": len(escalated_keys),
                "meaning": "Current-period exceptions marked Escalated in review state.",
            },
            {
                "metric": "accepted_risk_items",
                "value": len(accepted_risk_keys),
                "meaning": "Current-period exceptions marked Accepted Risk in review state.",
            },
            {
                "metric": "current_high_or_critical",
                "value": current_trend.get("high_or_critical_count", 0),
                "meaning": "High or Critical exceptions in the final input period.",
            },
            {
                "metric": "current_review_completion_percent",
                "value": current_trend.get("review_completion_percent", 0),
                "meaning": "Share of final-period exceptions with a status beyond New.",
            },
        ],
    )


def _period_counts(frames: list[pd.DataFrame]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for frame in frames:
        if frame.empty:
            period = (
                _clean(frame.get("period", pd.Series([""])).iloc[0]) if "period" in frame.columns and len(frame) else ""
            )
            rows.append({"period": period, "exception_count": 0, "high_or_critical_count": 0})
            continue
        severity = frame.get("risk_level", frame.get("severity", pd.Series([""] * len(frame)))).astype(str).str.lower()
        rows.append(
            {
                "period": _clean(frame["period"].iloc[0]),
                "period_path": _clean(frame["period_path"].iloc[0]),
                "exception_count": len(frame),
                "unique_exception_count": int(frame["comparison_key"].nunique()),
                "high_or_critical_count": int(severity.isin({"high", "critical"}).sum()),
            },
        )
    return pd.DataFrame(rows)


def _reviewed_count(frame: pd.DataFrame) -> int:
    if frame.empty or "status" not in frame.columns:
        return 0
    statuses = frame["status"].astype(str).str.strip().str.lower()
    return int((statuses.ne("") & statuses.ne("new")).sum())


def _trend_frame(frames: list[pd.DataFrame]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    previous_keys: set[str] = set()
    for frame in frames:
        if frame.empty:
            period = ""
            period_path = ""
            current_keys: set[str] = set()
            severity = pd.Series(dtype=str)
            statuses = pd.Series(dtype=str)
        else:
            period = _clean(frame["period"].iloc[0])
            period_path = _clean(frame["period_path"].iloc[0])
            current_keys = set(frame["comparison_key"].astype(str))
            severity = (
                frame.get("risk_level", frame.get("severity", pd.Series([""] * len(frame)))).astype(str).str.lower()
            )
            statuses = frame.get("status", pd.Series([""] * len(frame))).astype(str).str.lower()
        reviewed = _reviewed_count(frame)
        exception_count = len(frame)
        rows.append(
            {
                "period": period,
                "period_path": period_path,
                "exception_count": exception_count,
                "unique_exception_count": len(current_keys),
                "new_count": len(current_keys - previous_keys),
                "recurring_count": len(current_keys & previous_keys),
                "resolved_since_previous_count": len(previous_keys - current_keys),
                "high_or_critical_count": int(severity.isin({"high", "critical"}).sum()),
                "reviewed_count": reviewed,
                "review_completion_percent": round((reviewed / exception_count) * 100, 2) if exception_count else 0,
                "accepted_risk_count": int(statuses.eq("accepted risk").sum()),
                "escalated_count": int(statuses.eq("escalated").sum()),
            },
        )
        previous_keys = current_keys
    return pd.DataFrame(rows)


def _top_recurring_themes(frame: pd.DataFrame, recurring_keys: set[str]) -> pd.DataFrame:
    if frame.empty or not recurring_keys:
        return pd.DataFrame(columns=["theme", "count"])
    subset = frame[frame["comparison_key"].isin(recurring_keys)].copy()
    if subset.empty:
        return pd.DataFrame(columns=["theme", "count"])
    for column in ["exception_type", "rule_name", "source_file"]:
        if column in subset.columns:
            values = subset[column].astype(str).map(_clean)
            values = values[values.ne("")]
            if not values.empty:
                counts = values.value_counts().head(10)
                return pd.DataFrame({"theme": counts.index.tolist(), "count": counts.tolist()})
    return pd.DataFrame(columns=["theme", "count"])


def _require_mapping(value: object, field_name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"Period comparison {field_name} must be an object")
    return value


def _require_records(value: object, field_name: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError(f"Period comparison {field_name} must be an array of objects")
    return value


def _without_period_path(records: object) -> list[dict[str, Any]]:
    validated = _require_records(records, "records")
    return [{key: value for key, value in record.items() if key != "period_path"} for record in validated]


def _comparison_keys(records: object) -> list[str]:
    validated = _require_records(records, "exception records")
    return sorted(str(record.get("comparison_key", "")) for record in validated)


def _decision_payload(payload: dict[str, Any]) -> dict[str, Any]:
    trend = _require_mapping(payload.get("trend"), "trend")
    return {
        "schema_version": PERIOD_COMPARISON_SCHEMA_VERSION,
        "financial_input_policy": payload.get("financial_input_policy"),
        "comparison_policy": payload.get("comparison_policy"),
        "input_periods": payload.get("input_periods"),
        "summary": payload.get("summary"),
        "period_counts": _without_period_path(payload.get("period_counts", [])),
        "trend": {
            "periods": _without_period_path(trend.get("periods", [])),
            "chart_data": trend.get("chart_data"),
            "top_recurring_themes": trend.get("top_recurring_themes"),
        },
        "new_exception_keys": _comparison_keys(payload.get("new_exceptions", [])),
        "recurring_exception_keys": _comparison_keys(payload.get("recurring_exceptions", [])),
        "resolved_exception_keys": _comparison_keys(payload.get("resolved_exceptions", [])),
        "escalated_exception_keys": _comparison_keys(payload.get("escalated_exceptions", [])),
        "accepted_risk_keys": _comparison_keys(payload.get("accepted_risk_items", [])),
    }


def _finalize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    payload["decision_digest"] = _canonical_digest(_decision_payload(payload))
    payload["artifact_digest"] = _canonical_digest(payload)
    return payload


def _trend_chart_html(trend: pd.DataFrame) -> str:
    if trend.empty:
        return "<p>No trend data found.</p>"
    max_count = int(trend[["new_count", "recurring_count", "resolved_since_previous_count"]].max().max()) or 1
    rows = []
    for _, row in trend.iterrows():
        bars = []
        for key, label, color in [
            ("new_count", "New", "#2563eb"),
            ("recurring_count", "Recurring", "#b45309"),
            ("resolved_since_previous_count", "Resolved", "#047857"),
        ]:
            value = int(row.get(key, 0))
            width = max(4, int((value / max_count) * 100)) if value else 0
            bars.append(
                f"<div class='bar-row'><span>{escape(label)}</span><div class='bar-track'><div class='bar' style='width:{width}%;background:{color}'></div></div><strong>{value}</strong></div>",
            )
        rows.append(
            f"<article class='trend-card'><h3>{escape(_clean(row.get('period', '')))}</h3>{''.join(bars)}</article>"
        )
    return "<div class='trend-grid'>" + "".join(rows) + "</div>"


def _html_table(frame: pd.DataFrame, limit: int = 25) -> str:
    if frame.empty:
        return "<p>No records found.</p>"
    visible = frame.head(limit)
    columns = [
        column
        for column in [
            "comparison_key",
            "exception_id",
            "status",
            "risk_level",
            "severity",
            "exception_type",
            "source_file",
            "work_order",
            "reference",
            "source_document",
            "amount_impact",
        ]
        if column in visible.columns
    ]
    if not columns:
        columns = list(visible.columns[:8])
    header = "".join(f"<th>{escape(str(column))}</th>" for column in columns)
    rows = []
    for _, row in visible[columns].iterrows():
        rows.append("<tr>" + "".join(f"<td>{escape(_clean(value))}</td>" for value in row.tolist()) + "</tr>")
    return f"<table><thead><tr>{header}</tr></thead><tbody>{''.join(rows)}</tbody></table>"


def _write_html(
    path: Path,
    summary: pd.DataFrame,
    trend: pd.DataFrame,
    top_themes: pd.DataFrame,
    sections: dict[str, pd.DataFrame],
    *,
    financial_input_policy: FinancialInputPolicy,
) -> None:
    cards = "".join(
        f"<section class='card'><span>{escape(str(row['metric']).replace('_', ' ').title())}</span><strong>{escape(str(row['value']))}</strong></section>"
        for _, row in summary.iterrows()
    )
    trend_html = f"<section><h2>Trend Summary</h2>{_trend_chart_html(trend)}{_html_table(trend)}</section>"
    themes_html = f"<section><h2>Top Recurring Themes</h2>{_html_table(top_themes)}</section>"
    section_html = "".join(
        f"<section><h2>{escape(title)}</h2>{_html_table(frame)}</section>" for title, frame in sections.items()
    )
    path.write_text(
        f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ReconForge Period Comparison</title>
  <style>
    body {{ margin: 0; font-family: Inter, Segoe UI, Arial, sans-serif; background: #f6f8fb; color: #182230; }}
    header {{ background: #17324d; color: #fff; padding: 24px 36px; }}
    main {{ max-width: 1180px; margin: 0 auto; padding: 28px; }}
    .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 12px; }}
    .card {{ background: #fff; border: 1px solid #dce3ea; border-radius: 8px; padding: 14px; }}
    .card span {{ display: block; color: #667085; font-size: 13px; }}
    .card strong {{ display: block; margin-top: 6px; font-size: 24px; }}
    section {{ margin-top: 26px; }}
    table {{ border-collapse: collapse; width: 100%; background: #fff; border: 1px solid #dce3ea; }}
    th, td {{ padding: 9px 10px; border-bottom: 1px solid #edf1f5; text-align: left; font-size: 13px; }}
    th {{ background: #e8eef5; color: #17324d; }}
    .trend-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; margin-bottom: 18px; }}
    .trend-card {{ background: #fff; border: 1px solid #dce3ea; border-radius: 8px; padding: 14px; }}
    .trend-card h3 {{ margin: 0 0 10px; }}
    .bar-row {{ display: grid; grid-template-columns: 76px 1fr 36px; gap: 8px; align-items: center; margin: 8px 0; font-size: 12px; }}
    .bar-track {{ height: 10px; background: #edf1f5; border-radius: 999px; overflow: hidden; }}
    .bar {{ height: 10px; border-radius: 999px; }}
  </style>
</head>
<body>
  <header><h1>ReconForge Period Comparison</h1><p>Local comparison of generated exception outputs under {escape(financial_input_policy)}. No savings are inferred.</p></header>
  <main><div class="cards">{cards}</div>{trend_html}{themes_html}{section_html}</main>
</body>
</html>
""",
        encoding="utf-8",
    )


def _write_markdown(
    path: Path,
    summary: pd.DataFrame,
    trend: pd.DataFrame,
    top_themes: pd.DataFrame,
    sections: dict[str, pd.DataFrame],
    periods: list[Path],
    *,
    financial_input_policy: FinancialInputPolicy,
) -> None:
    lines = [
        "# ReconForge Period Comparison",
        "",
        f"Financial input policy: `{financial_input_policy}`",
        "",
        "Compared local output folders:",
        *[f"- `{period}`" for period in periods],
        "",
        "## Summary",
        "",
        *[f"- {row['metric']}: {row['value']} ({row['meaning']})" for _, row in summary.iterrows()],
        "",
        "## Trend Summary",
        "",
    ]
    for _, row in trend.iterrows():
        lines.append(
            f"- `{row.get('period', '')}`: new {row.get('new_count', 0)}, recurring {row.get('recurring_count', 0)}, resolved since previous {row.get('resolved_since_previous_count', 0)}, high/critical {row.get('high_or_critical_count', 0)}, reviewed {row.get('review_completion_percent', 0)}%",
        )
    lines.extend(["", "## Top Recurring Themes", ""])
    if top_themes.empty:
        lines.append("No recurring themes found.")
    else:
        for _, row in top_themes.iterrows():
            lines.append(f"- {row['theme']}: {row['count']}")
    for title, frame in sections.items():
        lines.extend(["", f"## {title}", ""])
        if frame.empty:
            lines.append("No records found.")
            continue
        for _, row in frame.head(20).iterrows():
            label = _clean(row.get("exception_id", "")) or _clean(row.get("comparison_key", ""))
            detail = _clean(row.get("exception_type", row.get("rule_name", "")))
            status = _clean(row.get("status", ""))
            lines.append(f"- `{label}` {detail} {f'[{status}]' if status else ''}".strip())
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def compare_period_outputs(
    period_paths: Sequence[Path | str],
    output_path: Path | str,
    *,
    financial_input_policy: FinancialInputPolicy = STRICT_FINANCIAL_INPUT_POLICY,
) -> PeriodComparisonArtifacts:
    """Compare exception outputs across two or more generated output folders."""

    input_policy = validate_financial_input_policy(financial_input_policy)
    periods = [Path(path) for path in period_paths]
    if len(periods) < 2:
        raise ValueError("At least two period folders are required.")
    missing = [str(path) for path in periods if not path.exists() or not path.is_dir()]
    if missing:
        raise FileNotFoundError("Missing period folder(s): " + ", ".join(missing))

    input_periods = _period_input_manifest(periods)
    frames = [
        _load_period(
            path,
            index,
            financial_input_policy=input_policy,
        )
        for index, path in enumerate(periods, start=1)
    ]
    if _period_input_manifest(periods) != input_periods:
        raise ValueError("Period input files changed during comparison")
    current = frames[-1]
    current_keys = set(current.get("comparison_key", pd.Series(dtype=str)).astype(str))
    prior = pd.concat(frames[:-1], ignore_index=True, sort=False) if len(frames) > 1 else pd.DataFrame()
    prior_keys = set(prior.get("comparison_key", pd.Series(dtype=str)).astype(str))
    new_keys = current_keys - prior_keys
    recurring_keys = current_keys & prior_keys
    resolved_keys = prior_keys - current_keys
    escalated_keys = (
        set(
            current[current.get("status", pd.Series(dtype=str)).astype(str).str.lower().eq("escalated")][
                "comparison_key"
            ]
        )
        if not current.empty
        else set()
    )
    accepted_risk_keys = (
        set(
            current[current.get("status", pd.Series(dtype=str)).astype(str).str.lower().eq("accepted risk")][
                "comparison_key"
            ]
        )
        if not current.empty
        else set()
    )

    new_frame = _representative_rows(current, new_keys, "new", "current")
    recurring_frame = _representative_rows(current, recurring_keys, "recurring", "current")
    resolved_frame = _representative_rows(prior, resolved_keys, "resolved", "prior")
    escalated_frame = _representative_rows(current, escalated_keys, "escalated", "current")
    accepted_risk_frame = _representative_rows(current, accepted_risk_keys, "accepted_risk", "current")
    trend = _trend_frame(frames)
    top_themes = _top_recurring_themes(current, recurring_keys)
    summary = _summary_frame(
        periods=periods,
        frames=frames,
        new_keys=new_keys,
        recurring_keys=recurring_keys,
        resolved_keys=resolved_keys,
        escalated_keys=escalated_keys,
        accepted_risk_keys=accepted_risk_keys,
        trend=trend,
    )
    counts = _period_counts(frames)
    sheets = {
        "Summary": summary,
        "Period Counts": counts,
        "Trend Summary": trend,
        "Top Recurring Themes": top_themes,
        "New Exceptions": new_frame,
        "Recurring Exceptions": recurring_frame,
        "Resolved Exceptions": resolved_frame,
        "Escalated Exceptions": escalated_frame,
        "Accepted Risk Items": accepted_risk_frame,
    }
    payload = {
        "schema_version": PERIOD_COMPARISON_SCHEMA_VERSION,
        "artifact_type": _PERIOD_COMPARISON_ARTIFACT_TYPE,
        "financial_input_policy": input_policy,
        "comparison_policy": {
            "algorithm_version": PERIOD_COMPARISON_ALGORITHM_VERSION,
            "amount_rounding_policy": "ROUND_HALF_UP",
            "amount_fractional_digits": 2,
            "invalid_amount_policy": (
                "legacy-zero-v1" if input_policy == LEGACY_FINANCIAL_INPUT_POLICY else "explicit-invalid-or-missing-v2"
            ),
        },
        "input_periods": input_periods,
        "integrity_boundary": _PERIOD_COMPARISON_INTEGRITY_BOUNDARY,
        "periods": [str(path) for path in periods],
        "summary": frame_to_records(summary),
        "period_counts": frame_to_records(counts),
        "trend": {
            "periods": frame_to_records(trend),
            "chart_data": {
                "labels": trend["period"].tolist() if "period" in trend.columns else [],
                "new": trend["new_count"].tolist() if "new_count" in trend.columns else [],
                "recurring": trend["recurring_count"].tolist() if "recurring_count" in trend.columns else [],
                "resolved": trend["resolved_since_previous_count"].tolist()
                if "resolved_since_previous_count" in trend.columns
                else [],
                "high_or_critical": trend["high_or_critical_count"].tolist()
                if "high_or_critical_count" in trend.columns
                else [],
                "review_completion_percent": trend["review_completion_percent"].tolist()
                if "review_completion_percent" in trend.columns
                else [],
                "accepted_risk": trend["accepted_risk_count"].tolist()
                if "accepted_risk_count" in trend.columns
                else [],
                "escalated": trend["escalated_count"].tolist() if "escalated_count" in trend.columns else [],
            },
            "top_recurring_themes": frame_to_records(top_themes),
        },
        "new_exceptions": frame_to_records(new_frame),
        "recurring_exceptions": frame_to_records(recurring_frame),
        "resolved_exceptions": frame_to_records(resolved_frame),
        "escalated_exceptions": frame_to_records(escalated_frame),
        "accepted_risk_items": frame_to_records(accepted_risk_frame),
    }
    _finalize_payload(payload)
    output_dir = ensure_output_dir(output_path)
    workbook_path = write_excel_workbook(
        sheets,
        output_dir / "period_comparison.xlsx",
        metadata={
            "financial_input_policy": input_policy,
            "comparison_algorithm_version": PERIOD_COMPARISON_ALGORITHM_VERSION,
            "decision_digest": payload["decision_digest"],
        },
    )
    json_path = output_dir / "period_comparison.json"
    with json_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, default=json_default)
    html_path = output_dir / "period_comparison.html"
    markdown_path = output_dir / "period_comparison.md"
    _write_html(
        html_path,
        summary,
        trend,
        top_themes,
        {
            "New Exceptions": new_frame,
            "Recurring Exceptions": recurring_frame,
            "Resolved Exceptions": resolved_frame,
            "Escalated Exceptions": escalated_frame,
            "Accepted Risk Items": accepted_risk_frame,
        },
        financial_input_policy=input_policy,
    )
    _write_markdown(
        markdown_path,
        summary,
        trend,
        top_themes,
        {
            "New Exceptions": new_frame,
            "Recurring Exceptions": recurring_frame,
            "Resolved Exceptions": resolved_frame,
            "Escalated Exceptions": escalated_frame,
            "Accepted Risk Items": accepted_risk_frame,
        },
        periods,
        financial_input_policy=input_policy,
    )
    return PeriodComparisonArtifacts(
        workbook_path=workbook_path,
        html_path=html_path,
        json_path=json_path,
        markdown_path=markdown_path,
    )


def _validate_input_periods(value: object) -> list[dict[str, Any]]:
    periods = _require_records(value, "input_periods")
    allowed_names = {*EXCEPTION_FILE_CANDIDATES, "review_state.json"}
    for index, period in enumerate(periods, start=1):
        if period.get("period") != f"period_{index}":
            raise ValueError("Period comparison input labels must be sequential")
        files = _require_records(period.get("files"), "input files")
        names: list[str] = []
        for item in files:
            name = item.get("name")
            byte_count = item.get("bytes")
            digest = item.get("sha256")
            if (
                not isinstance(name, str)
                or name not in allowed_names
                or isinstance(byte_count, bool)
                or not isinstance(byte_count, int)
                or byte_count < 0
                or not isinstance(digest, str)
                or _SHA256_PATTERN.fullmatch(digest) is None
            ):
                raise ValueError("Period comparison contains an invalid input fingerprint")
            names.append(name)
        if names != sorted(set(names)):
            raise ValueError("Period comparison input fingerprints must be unique and sorted")
    return periods


def verify_period_comparison_payload(
    payload: dict[str, Any],
    *,
    period_paths: Sequence[Path | str] | None = None,
) -> None:
    """Verify v2 digests and optionally recheck local period input bytes."""

    if payload.get("schema_version") != PERIOD_COMPARISON_SCHEMA_VERSION:
        raise ValueError("Only current v2 period comparisons have verifiable digests")
    if payload.get("artifact_type") != _PERIOD_COMPARISON_ARTIFACT_TYPE:
        raise ValueError("Period comparison artifact type is invalid")
    input_policy = validate_financial_input_policy(payload.get("financial_input_policy"))
    comparison_policy = _require_mapping(
        payload.get("comparison_policy"),
        "comparison_policy",
    )
    expected_invalid_policy = (
        "legacy-zero-v1" if input_policy == LEGACY_FINANCIAL_INPUT_POLICY else "explicit-invalid-or-missing-v2"
    )
    if comparison_policy != {
        "algorithm_version": PERIOD_COMPARISON_ALGORITHM_VERSION,
        "amount_rounding_policy": "ROUND_HALF_UP",
        "amount_fractional_digits": 2,
        "invalid_amount_policy": expected_invalid_policy,
    }:
        raise ValueError("Period comparison policy is invalid")
    input_periods = _validate_input_periods(payload.get("input_periods"))
    if payload.get("integrity_boundary") != _PERIOD_COMPARISON_INTEGRITY_BOUNDARY:
        raise ValueError("Period comparison integrity boundary is invalid")
    expected_decision_digest = _canonical_digest(_decision_payload(payload))
    decision_digest = payload.get("decision_digest")
    if not isinstance(decision_digest, str) or not hmac.compare_digest(
        decision_digest,
        expected_decision_digest,
    ):
        raise ValueError("Period comparison decision digest verification failed")
    artifact_without_digest = {key: value for key, value in payload.items() if key != "artifact_digest"}
    artifact_digest = payload.get("artifact_digest")
    if not isinstance(artifact_digest, str) or not hmac.compare_digest(
        artifact_digest,
        _canonical_digest(artifact_without_digest),
    ):
        raise ValueError("Period comparison artifact digest verification failed")
    if period_paths is not None:
        paths = [Path(path) for path in period_paths]
        if input_periods != _period_input_manifest(paths):
            raise ValueError("Period comparison input fingerprint verification failed")


def read_period_comparison(path: Path | str) -> PeriodComparisonDocument:
    """Read historical unversioned v1 or verify current v2 JSON."""

    try:
        payload = read_generated_json_document(Path(path), mode="display").payload
    except GeneratedArtifactError as exc:
        raise ValueError("Period comparison JSON is invalid") from exc
    document = _require_mapping(payload, "document")
    _require_records(document.get("summary"), "summary")
    if "schema_version" not in document:
        return PeriodComparisonDocument(
            schema_version=1,
            verification_status="legacy-unverified",
            payload=document,
        )
    verify_period_comparison_payload(document)
    return PeriodComparisonDocument(
        schema_version=2,
        verification_status="verified",
        payload=document,
    )
