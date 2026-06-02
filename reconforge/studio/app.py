"""FastAPI-powered local ReconForge Studio."""

from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

from reconforge.config import load_config
from reconforge.io.readers import read_required_datasets
from reconforge.reconciliation.stock_gl import reconcile_stock_gl
from reconforge.reconciliation.workorders import reconcile_workorders
from reconforge.reports.wip_aging import generate_wip_aging
from reconforge.review.state import ALLOWED_STATUSES, load_review_state, merge_review_state_with_exceptions
from reconforge.schemas import DatasetName
from reconforge.utils.safe_paths import build_download_registry, get_registered_download, is_safe_download_key
from reconforge.validators import issues_to_frame, validate_input_directory

DOWNLOAD_SUFFIXES = {".html", ".xlsx", ".csv", ".json", ".md", ".txt", ".yml", ".yaml"}
DOC_SUFFIXES = {".md"}


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
    .filters {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 10px; align-items: end; margin: 0 0 14px; }}
    .filters label {{ display: grid; gap: 4px; font-size: 12px; color: #475467; }}
    .filters input, .filters select {{ min-height: 34px; border: 1px solid #ccd6e0; border-radius: 6px; padding: 6px 8px; background: #fff; }}
    .filters button {{ min-height: 34px; border: 0; border-radius: 6px; padding: 6px 10px; background: #16324f; color: #fff; }}
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
    header = "".join(f"<th>{escape(str(column))}</th>" for column in visible.columns)
    rows = []
    for _, row in visible.iterrows():
        rows.append("<tr>" + "".join(f"<td>{_html_cell(row[column])}</td>" for column in visible.columns) + "</tr>")
    return f"<table><thead><tr>{header}</tr></thead><tbody>{''.join(rows)}</tbody></table>"


def _html_cell(value: object) -> str:
    if value is None:
        return ""
    text = str(value)
    if text.strip().lower() in {"nan", "nat", "none", "<na>"}:
        return ""
    return escape(text)


def _search_text(row: pd.Series) -> str:
    return " ".join(_html_cell(value) for value in row.to_list()).lower()


def _options(values: list[str], selected: str = "") -> str:
    items = ["<option value=''></option>"]
    for value in values:
        is_selected = " selected" if value == selected else ""
        items.append(f"<option value='{escape(value)}'{is_selected}>{escape(value)}</option>")
    return "".join(items)


def _amount_series(frame: pd.DataFrame) -> pd.Series:
    if "amount_impact" in frame.columns:
        return pd.to_numeric(frame["amount_impact"], errors="coerce").fillna(0)
    return pd.Series([0.0] * len(frame), index=frame.index)


def _filter_exceptions(
    frame: pd.DataFrame,
    *,
    severity: str = "",
    exception_type: str = "",
    status: str = "",
    source_file: str = "",
    search: str = "",
    min_amount: float = 0.0,
    sort: str = "risk_score",
) -> pd.DataFrame:
    filtered = frame.copy()
    if severity:
        severity_values = pd.Series([""] * len(filtered), index=filtered.index)
        if "severity" in filtered.columns:
            severity_values = severity_values.mask(filtered["severity"].astype(str).str.strip().ne(""), filtered["severity"].astype(str))
        if "risk_level" in filtered.columns:
            severity_values = severity_values.mask(severity_values.str.strip().eq(""), filtered["risk_level"].astype(str))
        filtered = filtered[severity_values.str.lower().eq(severity.lower())]
    if exception_type and "exception_type" in filtered.columns:
        filtered = filtered[filtered["exception_type"].astype(str).str.lower().eq(exception_type.lower())]
    if status and "status" in filtered.columns:
        filtered = filtered[filtered["status"].astype(str).str.lower().eq(status.lower())]
    if source_file and "source_file" in filtered.columns:
        filtered = filtered[filtered["source_file"].astype(str).str.lower().eq(source_file.lower())]
    if search:
        haystack = filtered.apply(_search_text, axis=1)
        filtered = filtered[haystack.str.contains(search.lower(), regex=False)]
    if min_amount > 0:
        filtered = filtered[_amount_series(filtered) >= min_amount]
    if sort == "amount_impact":
        filtered = filtered.assign(_sort_amount=_amount_series(filtered)).sort_values("_sort_amount", ascending=False).drop(columns=["_sort_amount"])
    elif sort == "updated_at" and "updated_at" in filtered.columns:
        filtered = filtered.sort_values("updated_at", ascending=False)
    elif "risk_score" in filtered.columns:
        filtered = filtered.assign(_sort_risk=pd.to_numeric(filtered["risk_score"], errors="coerce").fillna(0)).sort_values(
            "_sort_risk",
            ascending=False,
        ).drop(columns=["_sort_risk"])
    return filtered


def _filter_form(
    frame: pd.DataFrame,
    *,
    severity: str,
    exception_type: str,
    status: str,
    source_file: str,
    search: str,
    min_amount: float,
    sort: str,
) -> str:
    severity_values = sorted(
        {
            value
            for column in ("severity", "risk_level")
            if column in frame.columns
            for value in frame[column].astype(str).str.strip()
            if value
        },
    )
    exception_values = sorted(set(frame.get("exception_type", pd.Series(dtype=str)).astype(str).str.strip()) - {""})
    source_values = sorted(set(frame.get("source_file", pd.Series(dtype=str)).astype(str).str.strip()) - {""})
    return f"""
<form class="filters" method="get" action="/exceptions">
  <label>Severity / risk level<select name="severity">{_options(severity_values, severity)}</select></label>
  <label>Exception type<select name="exception_type">{_options(exception_values, exception_type)}</select></label>
  <label>Review status<select name="status">{_options(list(ALLOWED_STATUSES), status)}</select></label>
  <label>Source file<select name="source_file">{_options(source_values, source_file)}</select></label>
  <label>Search<input name="search" value="{escape(search)}"></label>
  <label>Minimum amount<input name="min_amount" type="number" step="0.01" value="{min_amount:g}"></label>
  <label>Sort<select name="sort">{_options(["risk_score", "amount_impact", "updated_at"], sort)}</select></label>
  <button type="submit">Apply</button>
</form>
"""


def _single_segment_download_key(value: str) -> str:
    if "/" in value or not is_safe_download_key(value):
        raise ValueError("Unsafe download key segment")
    return value


def _evidence_download_key(case_id: str, filename: str) -> str:
    return f"{_single_segment_download_key(case_id)}/{_single_segment_download_key(filename)}"


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
    output_registry = build_download_registry(output_path, allowed_suffixes=DOWNLOAD_SUFFIXES)
    evidence_registry = build_download_registry(output_path / "evidence", allowed_suffixes=DOWNLOAD_SUFFIXES, recursive=True)
    docs_registry = build_download_registry(Path("docs"), allowed_suffixes=DOC_SUFFIXES)
    app = FastAPI(title="ReconForge Studio", version="0.5.0")

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
    def exceptions(
        severity: str = "",
        exception_type: str = "",
        status: str = "",
        source_file: str = "",
        search: str = "",
        min_amount: float = 0.0,
        sort: str = "risk_score",
    ) -> str:
        rec = _load_reconciliation(input_path)
        exceptions_frame = merge_review_state_with_exceptions(
            rec["exceptions"],
            load_review_state(output_path / "review_state.json"),
        )
        filtered = _filter_exceptions(
            exceptions_frame,
            severity=severity,
            exception_type=exception_type,
            status=status,
            source_file=source_file,
            search=search,
            min_amount=min_amount,
            sort=sort,
        )
        form = _filter_form(
            exceptions_frame,
            severity=severity,
            exception_type=exception_type,
            status=status,
            source_file=source_file,
            search=search,
            min_amount=min_amount,
            sort=sort,
        )
        message = "<p>No exceptions match the current filters.</p>" if filtered.empty else ""
        return _layout("Exceptions", "<h2>Exception Review</h2>" + form + message + _table(filtered, limit=100))

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
        rows = [
            {"case": key.split("/", 1)[0], "summary": f"/download/evidence/{key}"}
            for key in sorted(evidence_registry)
            if key.endswith("/summary.md") and len(key.split("/")) == 2
        ]
        return _layout("Evidence", "<h2>Evidence Binder</h2>" + _table(pd.DataFrame(rows)))

    @app.get("/downloads", response_class=HTMLResponse)
    def downloads() -> str:
        links = "".join(f'<li><a href="/download/{key}">{key}</a></li>' for key in sorted(output_registry))
        return _layout("Downloads", f"<h2>Downloads</h2><ul>{links}</ul>")

    @app.get("/docs", response_class=HTMLResponse)
    def docs() -> str:
        links = "".join(f'<li><a href="/download-doc/{key}">{key}</a></li>' for key in sorted(docs_registry))
        return _layout("Docs", f"<h2>Documentation</h2><ul>{links}</ul>")

    @app.get("/download/{filename}")
    def download(filename: str) -> FileResponse:
        try:
            path = get_registered_download(output_registry, filename)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid filename") from None
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="File not found") from None
        return FileResponse(path, media_type="application/octet-stream", filename=path.name)

    @app.get("/download/evidence/{case_id}/{filename}")
    def download_evidence(case_id: str, filename: str) -> FileResponse:
        try:
            path = get_registered_download(evidence_registry, _evidence_download_key(case_id, filename))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid filename") from None
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="Evidence file not found") from None
        return FileResponse(path, media_type="text/plain", filename=path.name)

    @app.get("/download-doc/{filename}")
    def download_doc(filename: str) -> FileResponse:
        try:
            path = get_registered_download(docs_registry, filename)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid filename") from None
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="Doc not found") from None
        return FileResponse(path, media_type="text/markdown", filename=path.name)

    return app
