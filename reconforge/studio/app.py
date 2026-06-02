"""FastAPI-powered local ReconForge Studio."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, Response

from reconforge.config import load_config
from reconforge.io.readers import read_required_datasets
from reconforge.reconciliation.stock_gl import reconcile_stock_gl
from reconforge.reconciliation.workorders import reconcile_workorders
from reconforge.reports.wip_aging import generate_wip_aging
from reconforge.schemas import DatasetName
from reconforge.utils.safe_paths import safe_resolve_child
from reconforge.validators import issues_to_frame, validate_input_directory

DOWNLOAD_SUFFIXES = {".html", ".xlsx", ".csv", ".json", ".md", ".txt", ".yml", ".yaml"}
DOC_SUFFIXES = {".md"}
TEXT_DOWNLOAD_SUFFIXES = DOWNLOAD_SUFFIXES - {".xlsx"}


def _layout(title: str, body: str) -> str:
    nav = """
    <nav>
      <a href="/">Overview</a>
      <a href="/health">Dataset Health</a>
      <a href="/validation">Validation</a>
      <a href="/reconciliation">Reconciliation</a>
      <a href="/rule-results">Rule Results</a>
      <a href="/exceptions">Exceptions</a>
      <a href="/risk-matrix">Risk Matrix</a>
      <a href="/wip">WIP Aging</a>
      <a href="/control-packs">Control Packs</a>
      <a href="/evidence">Evidence</a>
      <a href="/downloads">Downloads</a>
      <a href="/docs">Docs</a>
    </nav>
    """
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    body {{ margin: 0; font-family: Inter, Segoe UI, Arial, sans-serif; background: #f5f7fa; color: #182230; }}
    header {{ background: #16324f; color: #fff; padding: 22px 32px; }}
    header h1 {{ margin: 0; font-size: 24px; }}
    nav {{ display: flex; flex-wrap: wrap; gap: 8px; padding: 12px 32px; background: #e7edf4; border-bottom: 1px solid #d5dde8; }}
    nav a {{ color: #16324f; text-decoration: none; padding: 6px 8px; border-radius: 6px; }}
    nav a:hover {{ background: #d5dde8; }}
    main {{ max-width: 1180px; margin: 0 auto; padding: 24px; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 12px; }}
    .card {{ background: #fff; border: 1px solid #dce3ea; border-radius: 8px; padding: 14px; }}
    .card span {{ display: block; color: #667085; font-size: 13px; }}
    .card strong {{ display: block; margin-top: 6px; font-size: 23px; }}
    .badge {{ border-radius: 999px; padding: 3px 8px; font-size: 12px; background: #e8eef5; }}
    .high, .critical {{ background: #fee4e2; color: #912018; }}
    .medium {{ background: #fff4cc; color: #7a4d00; }}
    table {{ width: 100%; border-collapse: collapse; background: #fff; border: 1px solid #dce3ea; }}
    th, td {{ padding: 9px 10px; border-bottom: 1px solid #edf1f5; text-align: left; font-size: 13px; }}
    th {{ background: #e8eef5; }}
    h2 {{ margin-top: 0; }}
  </style>
</head>
<body>
  <header><h1>ReconForge Studio</h1></header>
  {nav}
  <main>{body}</main>
</body>
</html>"""


def _table(frame: pd.DataFrame, limit: int = 50) -> str:
    if frame.empty:
        return "<p>No records found.</p>"
    visible = frame.head(limit)
    header = "".join(f"<th>{column}</th>" for column in visible.columns)
    rows = []
    for _, row in visible.iterrows():
        rows.append("<tr>" + "".join(f"<td>{row[column]}</td>" for column in visible.columns) + "</tr>")
    return f"<table><thead><tr>{header}</tr></thead><tbody>{''.join(rows)}</tbody></table>"


def _download_response(path: Path, media_type: str) -> Response:
    if path.suffix.lower() in TEXT_DOWNLOAD_SUFFIXES:
        return Response(
            content=path.read_text(encoding="utf-8"),
            media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="{path.name}"'},
        )
    return FileResponse(path, media_type=media_type, filename=path.name)


def _load_reconciliation(input_dir: Path) -> dict[str, Any]:
    config = load_config(Path("config/reconforge.yml"))
    datasets = read_required_datasets(
        input_dir,
        [
            DatasetName.STOCK_MOVES,
            DatasetName.GL_ENTRIES,
            DatasetName.WORK_ORDERS,
            DatasetName.PURCHASE_ORDERS,
            DatasetName.OLD_PARTS_RETURNS,
            DatasetName.INVOICES,
        ],
    )
    stock = reconcile_stock_gl(datasets[DatasetName.STOCK_MOVES], datasets[DatasetName.GL_ENTRIES], config)
    workorders = reconcile_workorders(
        datasets[DatasetName.STOCK_MOVES],
        datasets[DatasetName.WORK_ORDERS],
        datasets[DatasetName.PURCHASE_ORDERS],
        datasets[DatasetName.OLD_PARTS_RETURNS],
        datasets[DatasetName.INVOICES],
        config,
    )
    wip = generate_wip_aging(datasets[DatasetName.WORK_ORDERS], config)
    exceptions = pd.concat([stock.all_exceptions, workorders.all_exceptions], ignore_index=True, sort=False)
    return {"stock": stock, "workorders": workorders, "wip": wip, "exceptions": exceptions}


def create_studio_app(input_dir: Path | str, output_dir: Path | str) -> FastAPI:
    """Create a local ReconForge Studio app."""

    input_path = Path(input_dir)
    output_path = Path(output_dir)
    app = FastAPI(title="ReconForge Studio", version="0.2.0")

    @app.get("/", response_class=HTMLResponse)
    def overview() -> str:
        rec = _load_reconciliation(input_path)
        exceptions = rec["exceptions"]
        cards = "".join(
            [
                f'<section class="card"><span>Input Folder</span><strong>{input_path}</strong></section>',
                f'<section class="card"><span>Total Exceptions</span><strong>{len(exceptions)}</strong></section>',
                f'<section class="card"><span>Critical Risks</span><strong>{exceptions.get("risk_level", pd.Series(dtype=str)).astype(str).eq("Critical").sum()}</strong></section>',
                f'<section class="card"><span>Open WIP</span><strong>{len(rec["wip"])}</strong></section>',
            ],
        )
        return _layout("ReconForge Studio", f"<h2>Overview</h2><div class='grid'>{cards}</div>")

    @app.get("/health", response_class=HTMLResponse)
    def health() -> str:
        files = sorted(input_path.glob("*.csv"))
        rows = [{"file": path.name, "rows": len(pd.read_csv(path, keep_default_na=False))} for path in files]
        return _layout("Dataset Health", "<h2>Dataset Health</h2>" + _table(pd.DataFrame(rows)))

    @app.get("/validation", response_class=HTMLResponse)
    def validation() -> str:
        return _layout("Validation", "<h2>Validation Results</h2>" + _table(issues_to_frame(validate_input_directory(input_path))))

    @app.get("/reconciliation", response_class=HTMLResponse)
    def reconciliation() -> str:
        rec = _load_reconciliation(input_path)
        return _layout(
            "Reconciliation",
            "<h2>Stock vs GL</h2>"
            + _table(rec["stock"].summary)
            + "<h2>Work Orders</h2>"
            + _table(rec["workorders"].summary),
        )

    @app.get("/exceptions", response_class=HTMLResponse)
    def exceptions() -> str:
        rec = _load_reconciliation(input_path)
        exceptions_frame = rec["exceptions"]
        if "risk_score" in exceptions_frame.columns:
            exceptions_frame = exceptions_frame.sort_values("risk_score", ascending=False)
        return _layout("Exceptions", "<h2>Exception Review</h2>" + _table(exceptions_frame, limit=100))

    @app.get("/rule-results", response_class=HTMLResponse)
    def rule_results() -> str:
        rules_path = output_path / "rules" / "rule_results.csv"
        if not rules_path.exists():
            return _layout("Rule Results", "<h2>Rule Results</h2><p>No rule results have been generated yet.</p>")
        return _layout("Rule Results", "<h2>Rule Results</h2>" + _table(pd.read_csv(rules_path, keep_default_na=False), limit=100))

    @app.get("/risk-matrix", response_class=HTMLResponse)
    def risk_matrix() -> str:
        rec = _load_reconciliation(input_path)
        exceptions_frame = rec["exceptions"]
        if exceptions_frame.empty or "risk_level" not in exceptions_frame.columns:
            return _layout("Risk Matrix", "<h2>Risk Matrix</h2><p>No risk data found.</p>")
        group_cols = [column for column in ["risk_level", "exception_type"] if column in exceptions_frame.columns]
        matrix = exceptions_frame.groupby(group_cols, as_index=False).size().rename(columns={"size": "exception_count"})
        return _layout("Risk Matrix", "<h2>Risk Matrix</h2>" + _table(matrix, limit=100))

    @app.get("/wip", response_class=HTMLResponse)
    def wip() -> str:
        return _layout("WIP Aging", "<h2>WIP Aging</h2>" + _table(_load_reconciliation(input_path)["wip"]))

    @app.get("/control-packs", response_class=HTMLResponse)
    def control_packs() -> str:
        pack_rows = []
        for pack in sorted(Path("control-packs").glob("*/pack.yml")):
            pack_rows.append({"pack": pack.parent.name, "path": str(pack.parent)})
        rules_path = output_path / "rules" / "rule_results.csv"
        body = "<h2>Control Packs</h2>" + _table(pd.DataFrame(pack_rows))
        if rules_path.exists():
            body += "<h2>Latest Rule Results</h2>" + _table(pd.read_csv(rules_path, keep_default_na=False))
        return _layout("Control Packs", body)

    @app.get("/evidence", response_class=HTMLResponse)
    def evidence() -> str:
        evidence_dir = output_path / "evidence"
        rows = [{"case": path.name, "summary": f"/download/evidence/{path.name}/summary.md"} for path in sorted(evidence_dir.glob("EXC-*"))]
        return _layout("Evidence", "<h2>Evidence Binder</h2>" + _table(pd.DataFrame(rows)))

    @app.get("/downloads", response_class=HTMLResponse)
    def downloads() -> str:
        files = sorted(path for path in output_path.glob("*") if path.is_file() and path.suffix.lower() in DOWNLOAD_SUFFIXES)
        links = "".join(f'<li><a href="/download/{path.name}">{path.name}</a></li>' for path in files)
        return _layout("Downloads", f"<h2>Downloads</h2><ul>{links}</ul>")

    @app.get("/docs", response_class=HTMLResponse)
    def docs() -> str:
        links = "".join(f'<li><a href="/download-doc/{path.name}">{path.name}</a></li>' for path in sorted(Path("docs").glob("*.md")))
        return _layout("Docs", f"<h2>Documentation</h2><ul>{links}</ul>")

    @app.get("/download/{filename}")
    def download(filename: str) -> Response:
        try:
            path = safe_resolve_child(output_path, filename, allowed_suffixes=DOWNLOAD_SUFFIXES)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid filename") from None
        if not path.exists() or not path.is_file():
            raise HTTPException(status_code=404, detail="File not found")
        return _download_response(path, "application/octet-stream")

    @app.get("/download/evidence/{case_id}/{filename}")
    def download_evidence(case_id: str, filename: str) -> Response:
        try:
            case_dir = safe_resolve_child(output_path / "evidence", case_id)
            path = safe_resolve_child(case_dir, filename, allowed_suffixes=DOWNLOAD_SUFFIXES)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid filename") from None
        if not path.exists() or not path.is_file():
            raise HTTPException(status_code=404, detail="Evidence file not found")
        return _download_response(path, "text/plain")

    @app.get("/download-doc/{filename}")
    def download_doc(filename: str) -> Response:
        try:
            path = safe_resolve_child(Path("docs"), filename, allowed_suffixes=DOC_SUFFIXES)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid filename") from None
        if not path.exists() or not path.is_file():
            raise HTTPException(status_code=404, detail="Doc not found")
        return _download_response(path, "text/markdown")

    return app
