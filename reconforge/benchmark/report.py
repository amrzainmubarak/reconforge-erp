"""Benchmark report writers."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from reconforge.benchmark.metrics import BenchmarkMetrics
from reconforge.io.writers import ensure_output_dir, write_json


def write_benchmark_reports(metrics: BenchmarkMetrics, output_dir: Path | str) -> list[Path]:
    """Write benchmark JSON, Markdown, CSV, and HTML reports."""

    target = ensure_output_dir(output_dir)
    payload = metrics.to_dict()
    json_path = write_json(payload, target, "benchmark")
    csv_path = target / "benchmark.csv"
    pd.DataFrame([payload]).to_csv(csv_path, index=False)
    md_path = target / "benchmark.md"
    lines = [
        "# ReconForge Benchmark",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        *[f"| {key} | {value} |" for key, value in payload.items()],
    ]
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    html_path = target / "benchmark.html"
    rows = "".join(f"<tr><th>{key}</th><td>{value}</td></tr>" for key, value in payload.items())
    html_path.write_text(
        f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>ReconForge Benchmark</title>
  <style>
    body {{ font-family: Inter, Segoe UI, Arial, sans-serif; margin: 32px; color: #182230; }}
    h1 {{ color: #17324d; }}
    table {{ border-collapse: collapse; min-width: 520px; }}
    th, td {{ border-bottom: 1px solid #e4e7ec; padding: 10px 12px; text-align: left; }}
    th {{ background: #edf3f8; }}
  </style>
</head>
<body>
  <h1>ReconForge Benchmark</h1>
  <table>{rows}</table>
</body>
</html>
""",
        encoding="utf-8",
    )
    return [json_path, md_path, csv_path, html_path]
