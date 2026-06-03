"""Multi-period exception comparison reporting."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Any

import pandas as pd

from reconforge.io.excel import write_excel_workbook
from reconforge.io.writers import ensure_output_dir, frame_to_records, json_default
from reconforge.review.state import collect_exception_frame, load_review_state, merge_review_state_with_exceptions

SYNTHETIC_EXCEPTION_ID_PATTERN = re.compile(r"^EXC-\d+$", re.IGNORECASE)
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


def _clean(value: object) -> str:
    text = str(value).strip()
    return "" if text.lower() in {"nan", "nat", "none", "null", "<na>"} else text


def _amount_value(row: pd.Series) -> str:
    for name in ["amount_impact", "amount", "total_cost", "actual_cost", "estimated_cost", "invoice_amount", "total_price"]:
        value = row.get(name)
        try:
            amount = abs(float(str(value)))
        except (TypeError, ValueError):
            continue
        if amount:
            return f"{amount:.2f}"
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


def _exception_key(row: pd.Series) -> str:
    exception_id = _clean(row.get("exception_id", ""))
    if exception_id and not _is_synthetic_exception_id(exception_id):
        return f"id:{exception_id}"
    parts = [
        _fingerprint_part(row, ["source_file"]),
        _fingerprint_part(row, ["exception_type"]),
        _fingerprint_part(row, RULE_FIELDS),
        _fingerprint_part(row, DOCUMENT_FIELDS),
        _fingerprint_part(row, ITEM_FIELDS),
        f"amount={_amount_value(row)}",
        _fingerprint_part(row, DATE_FIELDS),
    ]
    return "fingerprint:" + "|".join(part for part in parts if part)


def _load_period(period_path: Path, period_index: int) -> pd.DataFrame:
    exceptions = collect_exception_frame(period_path)
    merged = merge_review_state_with_exceptions(exceptions, load_review_state(period_path / "review_state.json"))
    if merged.empty:
        return merged.assign(period=f"period_{period_index}", period_path=str(period_path), comparison_key=pd.Series(dtype=str))
    output = merged.copy()
    output["period"] = f"period_{period_index}"
    output["period_path"] = str(period_path)
    output["comparison_key"] = [_exception_key(row) for _, row in output.iterrows()]
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
            {"metric": "periods_compared", "value": len(periods), "meaning": "Number of local output folders compared."},
            {"metric": "current_period_exceptions", "value": len(frames[-1]) if frames else 0, "meaning": "Exceptions found in the final input period."},
            {"metric": "new_exceptions", "value": len(new_keys), "meaning": "Current-period exceptions not seen in earlier periods."},
            {"metric": "recurring_exceptions", "value": len(recurring_keys), "meaning": "Current-period exceptions also seen in at least one earlier period."},
            {"metric": "resolved_exceptions", "value": len(resolved_keys), "meaning": "Earlier-period exceptions not present in the current period."},
            {"metric": "escalated_exceptions", "value": len(escalated_keys), "meaning": "Current-period exceptions marked Escalated in review state."},
            {"metric": "accepted_risk_items", "value": len(accepted_risk_keys), "meaning": "Current-period exceptions marked Accepted Risk in review state."},
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
            period = _clean(frame.get("period", pd.Series([""])).iloc[0]) if "period" in frame.columns and len(frame) else ""
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
            severity = frame.get("risk_level", frame.get("severity", pd.Series([""] * len(frame)))).astype(str).str.lower()
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
        rows.append(f"<article class='trend-card'><h3>{escape(_clean(row.get('period', '')))}</h3>{''.join(bars)}</article>")
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


def _write_html(path: Path, summary: pd.DataFrame, trend: pd.DataFrame, top_themes: pd.DataFrame, sections: dict[str, pd.DataFrame]) -> None:
    cards = "".join(
        f"<section class='card'><span>{escape(str(row['metric']).replace('_', ' ').title())}</span><strong>{escape(str(row['value']))}</strong></section>"
        for _, row in summary.iterrows()
    )
    trend_html = f"<section><h2>Trend Summary</h2>{_trend_chart_html(trend)}{_html_table(trend)}</section>"
    themes_html = f"<section><h2>Top Recurring Themes</h2>{_html_table(top_themes)}</section>"
    section_html = "".join(f"<section><h2>{escape(title)}</h2>{_html_table(frame)}</section>" for title, frame in sections.items())
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
  <header><h1>ReconForge Period Comparison</h1><p>Local comparison of generated exception outputs. No savings are inferred.</p></header>
  <main><div class="cards">{cards}</div>{trend_html}{themes_html}{section_html}</main>
</body>
</html>
""",
        encoding="utf-8",
    )


def _write_markdown(path: Path, summary: pd.DataFrame, trend: pd.DataFrame, top_themes: pd.DataFrame, sections: dict[str, pd.DataFrame], periods: list[Path]) -> None:
    lines = [
        "# ReconForge Period Comparison",
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


def compare_period_outputs(period_paths: Sequence[Path | str], output_path: Path | str) -> PeriodComparisonArtifacts:
    """Compare exception outputs across two or more generated output folders."""

    periods = [Path(path) for path in period_paths]
    if len(periods) < 2:
        raise ValueError("At least two period folders are required.")
    missing = [str(path) for path in periods if not path.exists() or not path.is_dir()]
    if missing:
        raise FileNotFoundError("Missing period folder(s): " + ", ".join(missing))

    output_dir = ensure_output_dir(output_path)
    frames = [_load_period(path, index) for index, path in enumerate(periods, start=1)]
    current = frames[-1]
    current_keys = set(current.get("comparison_key", pd.Series(dtype=str)).astype(str))
    prior = pd.concat(frames[:-1], ignore_index=True, sort=False) if len(frames) > 1 else pd.DataFrame()
    prior_keys = set(prior.get("comparison_key", pd.Series(dtype=str)).astype(str))
    new_keys = current_keys - prior_keys
    recurring_keys = current_keys & prior_keys
    resolved_keys = prior_keys - current_keys
    escalated_keys = set(current[current.get("status", pd.Series(dtype=str)).astype(str).str.lower().eq("escalated")]["comparison_key"]) if not current.empty else set()
    accepted_risk_keys = set(current[current.get("status", pd.Series(dtype=str)).astype(str).str.lower().eq("accepted risk")]["comparison_key"]) if not current.empty else set()

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
    workbook_path = write_excel_workbook(sheets, output_dir / "period_comparison.xlsx")
    json_path = output_dir / "period_comparison.json"
    payload = {
        "periods": [str(path) for path in periods],
        "summary": frame_to_records(summary),
        "period_counts": frame_to_records(counts),
        "trend": {
            "periods": frame_to_records(trend),
            "chart_data": {
                "labels": trend["period"].tolist() if "period" in trend.columns else [],
                "new": trend["new_count"].tolist() if "new_count" in trend.columns else [],
                "recurring": trend["recurring_count"].tolist() if "recurring_count" in trend.columns else [],
                "resolved": trend["resolved_since_previous_count"].tolist() if "resolved_since_previous_count" in trend.columns else [],
                "high_or_critical": trend["high_or_critical_count"].tolist() if "high_or_critical_count" in trend.columns else [],
                "review_completion_percent": trend["review_completion_percent"].tolist() if "review_completion_percent" in trend.columns else [],
                "accepted_risk": trend["accepted_risk_count"].tolist() if "accepted_risk_count" in trend.columns else [],
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
    )
    return PeriodComparisonArtifacts(
        workbook_path=workbook_path,
        html_path=html_path,
        json_path=json_path,
        markdown_path=markdown_path,
    )
