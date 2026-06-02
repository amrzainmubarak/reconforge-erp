"""Markdown summary report generation."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd

from reconforge.config import ReconForgeConfig


def _metric(frame: pd.DataFrame, metric: str) -> int:
    if frame.empty or "metric" not in frame.columns:
        return 0
    rows = frame[frame["metric"].astype(str).eq(metric)]
    if rows.empty:
        return 0
    return int(rows.iloc[0]["count"])


def write_markdown_summary(
    output_path: Path | str,
    config: ReconForgeConfig,
    stock_summary: pd.DataFrame,
    workorder_summary: pd.DataFrame,
    wip_aging: pd.DataFrame,
    critical_count: int,
) -> Path:
    """Write an audit-ready Markdown summary report."""

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# {config.report_title}",
        "",
        f"Company: **{config.company_name}**",
        f"Generated at: **{datetime.utcnow().replace(microsecond=0).isoformat()}Z**",
        f"Currency: **{config.output_currency}**",
        "",
        "## Executive Summary",
        "",
        "| Control Area | Result |",
        "| --- | ---: |",
        f"| Matched stock/GL transactions | {_metric(stock_summary, 'matched_transactions')} |",
        f"| Stock movements without GL | {_metric(stock_summary, 'stock_without_gl')} |",
        f"| GL entries without stock | {_metric(stock_summary, 'gl_without_stock')} |",
        f"| Value differences | {_metric(stock_summary, 'value_differences')} |",
        f"| Work-order exceptions | {int(workorder_summary['count'].sum()) if not workorder_summary.empty else 0} |",
        f"| Open WIP orders | {len(wip_aging)} |",
        f"| Critical risks | {critical_count} |",
        "",
        "## Recommended Actions",
        "",
        "- Investigate unmatched stock movements before period close.",
        "- Confirm GL manual journals are linked to source documents and work orders.",
        "- Review direct purchase-and-fit cases for stores receipt evidence and approval trail.",
        "- Follow up old-part return requirements for controlled categories.",
        "- Escalate WIP older than 90 days to workshop and finance owners.",
        "",
        "## Audit Trail",
        "",
        "This report was generated locally from supplied ERP exports. No data was uploaded to any external service.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
