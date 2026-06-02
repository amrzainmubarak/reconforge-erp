"""Static HTML dashboard report generation."""

from __future__ import annotations

from datetime import datetime
from html import escape
from pathlib import Path

import pandas as pd

from reconforge.config import ReconForgeConfig


def _card(title: str, value: str) -> str:
    return f'<section class="card"><span>{escape(title)}</span><strong>{escape(value)}</strong></section>'


def _table(frame: pd.DataFrame, columns: list[str], limit: int = 10) -> str:
    if frame.empty:
        return "<p>No records found.</p>"
    visible = frame[[column for column in columns if column in frame.columns]].head(limit)
    header = "".join(f"<th>{escape(str(column))}</th>" for column in visible.columns)
    rows = []
    for _, row in visible.iterrows():
        rows.append("".join(f"<td>{escape(str(value))}</td>" for value in row.tolist()))
    body = "".join(f"<tr>{row}</tr>" for row in rows)
    return f"<table><thead><tr>{header}</tr></thead><tbody>{body}</tbody></table>"


def write_html_dashboard(
    output_path: Path | str,
    config: ReconForgeConfig,
    summary: dict[str, float | int | str],
    exceptions: pd.DataFrame,
    wip_aging: pd.DataFrame,
) -> Path:
    """Write a self-contained HTML dashboard report."""

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    cards = "".join(_card(str(key).replace("_", " ").title(), str(value)) for key, value in summary.items())
    exception_table = _table(
        exceptions,
        ["exception_type", "work_order", "source_document", "reference", "amount", "total_cost", "risk_score", "risk_level"],
    )
    wip_table = _table(
        wip_aging,
        ["work_order", "customer_name", "equipment_serial", "workshop", "aging_days", "aging_bucket", "actual_cost", "risk_level"],
    )
    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(config.report_title)}</title>
  <style>
    :root {{ color-scheme: light; font-family: Inter, Segoe UI, Arial, sans-serif; }}
    body {{ margin: 0; background: #f6f8fb; color: #182230; }}
    header {{ background: #17324d; color: #fff; padding: 28px 40px; }}
    header h1 {{ margin: 0; font-size: 28px; letter-spacing: 0; }}
    header p {{ margin: 8px 0 0; color: #dbe8f3; }}
    main {{ max-width: 1180px; margin: 0 auto; padding: 28px; }}
    .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 14px; }}
    .card {{ background: #fff; border: 1px solid #dce3ea; border-radius: 8px; padding: 16px; box-shadow: 0 1px 2px rgba(24,34,48,.06); }}
    .card span {{ display: block; color: #667085; font-size: 13px; }}
    .card strong {{ display: block; margin-top: 8px; font-size: 24px; }}
    section.report {{ margin-top: 28px; }}
    h2 {{ font-size: 20px; margin: 0 0 12px; }}
    table {{ border-collapse: collapse; width: 100%; background: #fff; border: 1px solid #dce3ea; }}
    th, td {{ padding: 10px 12px; border-bottom: 1px solid #edf1f5; text-align: left; font-size: 13px; }}
    th {{ background: #e8eef5; color: #17324d; }}
    footer {{ padding: 24px 40px; color: #667085; font-size: 13px; }}
  </style>
</head>
<body>
  <header>
    <h1>{escape(config.report_title)}</h1>
    <p>{escape(config.company_name)} · Generated {datetime.utcnow().replace(microsecond=0).isoformat()}Z · Local processing only</p>
  </header>
  <main>
    <div class="cards">{cards}</div>
    <section class="report">
      <h2>Top Exceptions</h2>
      {exception_table}
    </section>
    <section class="report">
      <h2>WIP Aging</h2>
      {wip_table}
    </section>
  </main>
  <footer>ReconForge ERP · Open-source reconciliation intelligence</footer>
</body>
</html>
"""
    path.write_text(html, encoding="utf-8")
    return path
