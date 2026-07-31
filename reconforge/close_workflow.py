"""Local close checklist workflow support."""

from __future__ import annotations

import json
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Any, Literal, TypeAlias, cast

import pandas as pd

from reconforge.io.excel import write_excel_workbook
from reconforge.io.structured import StructuredDocumentError, read_json_document, read_yaml_document
from reconforge.io.writers import ensure_output_dir, frame_to_records, json_default
from reconforge.utils.time import utc_now_text

CloseStatus = Literal["Not Started", "In Progress", "Blocked", "Complete", "Not Applicable"]
ALLOWED_CLOSE_STATUSES: tuple[CloseStatus, ...] = (
    "Not Started",
    "In Progress",
    "Blocked",
    "Complete",
    "Not Applicable",
)

CloseTask: TypeAlias = dict[str, str]
CloseChecklist: TypeAlias = dict[str, Any]

CHECKLIST_FILENAME = "close_checklist.json"

DEFAULT_CLOSE_TASKS: list[CloseTask] = [
    {
        "task_id": "CLOSE-001",
        "task_name": "Validate local ERP exports",
        "category": "Data readiness",
        "owner": "Finance Controller",
        "due_date": "",
        "status": "Not Started",
        "note": "",
        "updated_at": "",
    },
    {
        "task_id": "CLOSE-002",
        "task_name": "Run stock-to-GL reconciliation",
        "category": "Reconciliation",
        "owner": "Finance",
        "due_date": "",
        "status": "Not Started",
        "note": "",
        "updated_at": "",
    },
    {
        "task_id": "CLOSE-003",
        "task_name": "Review high and critical exceptions",
        "category": "Review",
        "owner": "Finance Controller",
        "due_date": "",
        "status": "Not Started",
        "note": "",
        "updated_at": "",
    },
    {
        "task_id": "CLOSE-004",
        "task_name": "Generate evidence binder",
        "category": "Evidence",
        "owner": "Internal Audit",
        "due_date": "",
        "status": "Not Started",
        "note": "",
        "updated_at": "",
    },
    {
        "task_id": "CLOSE-005",
        "task_name": "Export review register",
        "category": "Review",
        "owner": "Finance Controller",
        "due_date": "",
        "status": "Not Started",
        "note": "",
        "updated_at": "",
    },
    {
        "task_id": "CLOSE-006",
        "task_name": "Prepare management pack",
        "category": "Reporting",
        "owner": "Finance",
        "due_date": "",
        "status": "Not Started",
        "note": "",
        "updated_at": "",
    },
    {
        "task_id": "CLOSE-007",
        "task_name": "Review close readiness",
        "category": "Readiness",
        "owner": "Finance Controller",
        "due_date": "",
        "status": "Not Started",
        "note": "",
        "updated_at": "",
    },
]


@dataclass(frozen=True)
class CloseReportArtifacts:
    """Generated close checklist report artifacts."""

    html_path: Path
    workbook_path: Path
    csv_path: Path
    markdown_path: Path
    json_path: Path


def _now() -> str:
    return utc_now_text()


def _clean_text(value: object) -> str:
    text = str(value).strip()
    return "" if text.lower() in {"nan", "nat", "none", "null", "<na>"} else text


def _md_escape(value: object) -> str:
    return _clean_text(value).replace("<", "&lt;").replace(">", "&gt;")


def _coerce_status(value: object) -> CloseStatus:
    text = _clean_text(value)
    normalized = text.lower().replace("_", " ").replace("-", " ")
    normalized = " ".join(normalized.split())
    for status in ALLOWED_CLOSE_STATUSES:
        if normalized == status.lower():
            return status
    raise ValueError(f"Invalid close status. Expected one of: {', '.join(ALLOWED_CLOSE_STATUSES)}")


def _checklist_path(base: Path | str) -> Path:
    path = Path(base)
    if path.is_file():
        return path
    return path / CHECKLIST_FILENAME


def _normalize_task(raw: object, index: int) -> CloseTask:
    if not isinstance(raw, dict):
        raise ValueError("Each close checklist task must be an object.")
    task_id = _clean_text(raw.get("task_id", "")) or f"CLOSE-{index:03d}"
    task_name = _clean_text(raw.get("task_name", raw.get("title", ""))) or f"Close task {index}"
    status = _coerce_status(raw.get("status", "Not Started"))
    return {
        "task_id": task_id,
        "task_name": task_name,
        "category": _clean_text(raw.get("category", "")),
        "owner": _clean_text(raw.get("owner", "")),
        "due_date": _clean_text(raw.get("due_date", "")),
        "status": status,
        "note": _clean_text(raw.get("note", "")),
        "updated_at": _clean_text(raw.get("updated_at", "")),
    }


def _normalize_tasks(raw_tasks: object) -> list[CloseTask]:
    if not isinstance(raw_tasks, list):
        raise ValueError("Close checklist must contain a tasks list.")
    tasks = [_normalize_task(raw, index) for index, raw in enumerate(raw_tasks, start=1)]
    task_ids = [task["task_id"] for task in tasks]
    if len(task_ids) != len(set(task_ids)):
        raise ValueError("Close checklist task IDs must be unique.")
    return tasks


def _read_template(path: Path | str) -> list[CloseTask]:
    template_path = Path(path)
    if not template_path.exists() or not template_path.is_file():
        raise FileNotFoundError(f"Close checklist template not found: {template_path}")
    try:
        if template_path.suffix.lower() in {".yml", ".yaml"}:
            payload = read_yaml_document(template_path) or {}
        else:
            payload = read_json_document(template_path)
    except StructuredDocumentError as exc:
        raise ValueError("Close checklist template could not be parsed.") from exc
    raw_tasks = payload.get("tasks", payload) if isinstance(payload, dict) else payload
    return _normalize_tasks(raw_tasks)


def default_close_checklist(tasks: list[CloseTask] | None = None) -> CloseChecklist:
    """Return a default local close checklist payload."""

    return {
        "version": 1,
        "generated_at": _now(),
        "local_first_note": "Close checklist state is stored locally. No cloud upload, SaaS workflow, or authentication is required.",
        "workflow_boundary": "Prepared/reviewed fields and task statuses are workflow metadata only; they are not an audit opinion, legal sign-off, or digital signature.",
        "tasks": [dict(task) for task in (tasks or DEFAULT_CLOSE_TASKS)],
    }


def write_close_checklist(
    output_path: Path | str,
    *,
    template_path: Path | str | None = None,
    force: bool = False,
) -> Path:
    """Write a default or template-based close checklist JSON file."""

    output_dir = ensure_output_dir(output_path)
    path = output_dir / CHECKLIST_FILENAME
    if path.exists() and not force:
        return path
    tasks = _read_template(template_path) if template_path is not None else [dict(task) for task in DEFAULT_CLOSE_TASKS]
    payload = default_close_checklist(tasks)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, default=json_default)
    return path


def load_close_checklist(input_path: Path | str) -> CloseChecklist:
    """Load and validate a local close checklist JSON file."""

    path = _checklist_path(input_path)
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"Close checklist not found: {path}")
    try:
        payload = read_json_document(path)
    except StructuredDocumentError as exc:
        raise ValueError("Close checklist JSON could not be parsed.") from exc
    if not isinstance(payload, dict):
        raise ValueError("Close checklist JSON must contain an object.")
    payload = dict(payload)
    payload["tasks"] = _normalize_tasks(payload.get("tasks", []))
    payload.setdefault("version", 1)
    return payload


def save_close_checklist(input_path: Path | str, checklist: CloseChecklist) -> Path:
    """Persist a local close checklist atomically."""

    path = _checklist_path(input_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(checklist)
    payload["tasks"] = _normalize_tasks(payload.get("tasks", []))
    temp_path = path.with_suffix(path.suffix + ".tmp")
    with temp_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, default=json_default)
    temp_path.replace(path)
    return path


def close_tasks_frame(checklist: CloseChecklist) -> pd.DataFrame:
    """Convert checklist tasks to a deterministic DataFrame."""

    tasks = cast(list[CloseTask], checklist.get("tasks", []))
    columns = ["task_id", "task_name", "category", "status", "owner", "due_date", "note", "updated_at"]
    frame = pd.DataFrame(tasks)
    for column in columns:
        if column not in frame.columns:
            frame[column] = ""
    return frame[columns].sort_values("task_id").reset_index(drop=True)


def close_summary_frame(checklist: CloseChecklist) -> pd.DataFrame:
    """Summarize close checklist completion."""

    frame = close_tasks_frame(checklist)
    total = len(frame)
    complete = int(frame["status"].eq("Complete").sum()) if total else 0
    not_applicable = int(frame["status"].eq("Not Applicable").sum()) if total else 0
    blocked = int(frame["status"].eq("Blocked").sum()) if total else 0
    actionable = max(total - not_applicable, 0)
    completion = round((complete / actionable) * 100, 2) if actionable else 0.0
    rows: list[dict[str, object]] = [
        {"metric": "total_tasks", "value": total, "meaning": "All checklist tasks in the local close file."},
        {"metric": "complete_tasks", "value": complete, "meaning": "Tasks marked Complete."},
        {"metric": "blocked_tasks", "value": blocked, "meaning": "Tasks marked Blocked."},
        {
            "metric": "not_applicable_tasks",
            "value": not_applicable,
            "meaning": "Tasks excluded from completion denominator.",
        },
        {
            "metric": "completion_rate_pct",
            "value": completion,
            "meaning": "Complete tasks divided by actionable tasks.",
        },
    ]
    for status in ALLOWED_CLOSE_STATUSES:
        rows.append(
            {
                "metric": f"status_{status.lower().replace(' ', '_')}",
                "value": int(frame["status"].eq(status).sum()) if total else 0,
                "meaning": f"Tasks currently marked {status}.",
            },
        )
    return pd.DataFrame(rows)


def update_close_task_status(
    input_path: Path | str,
    *,
    task_id: str,
    status: str,
    owner: str = "",
    note: str = "",
    due_date: str = "",
) -> CloseTask:
    """Update a task status in the local close checklist and return the task."""

    clean_task_id = _clean_text(task_id)
    if not clean_task_id:
        raise ValueError("task_id is required.")
    checklist = load_close_checklist(input_path)
    tasks = cast(list[CloseTask], checklist["tasks"])
    next_status = _coerce_status(status)
    for task in tasks:
        if task["task_id"] != clean_task_id:
            continue
        task["status"] = next_status
        clean_owner = _clean_text(owner)
        clean_note = _clean_text(note)
        clean_due_date = _clean_text(due_date)
        if clean_owner:
            task["owner"] = clean_owner
        if clean_note:
            task["note"] = clean_note
        if clean_due_date:
            task["due_date"] = clean_due_date
        task["updated_at"] = _now()
        save_close_checklist(input_path, checklist)
        return task
    raise ValueError(f"Close checklist task not found: {clean_task_id}")


def _html_table(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "<p>No tasks found.</p>"
    columns = ["task_id", "task_name", "category", "status", "owner", "due_date", "note", "updated_at"]
    visible = frame[[column for column in columns if column in frame.columns]]
    header = "".join(f"<th>{escape(column.replace('_', ' ').title())}</th>" for column in visible.columns)
    rows = []
    for _, row in visible.iterrows():
        rows.append("<tr>" + "".join(f"<td>{escape(_clean_text(value))}</td>" for value in row.tolist()) + "</tr>")
    return f"<table><thead><tr>{header}</tr></thead><tbody>{''.join(rows)}</tbody></table>"


def _write_html(path: Path, summary: pd.DataFrame, tasks: pd.DataFrame) -> None:
    cards = "".join(
        f"<section class='card'><span>{escape(str(row['metric']).replace('_', ' ').title())}</span><strong>{escape(str(row['value']))}</strong></section>"
        for _, row in summary.iterrows()
        if str(row["metric"]) in {"total_tasks", "complete_tasks", "blocked_tasks", "completion_rate_pct"}
    )
    path.write_text(
        f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ReconForge Close Checklist Report</title>
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
    <h1>ReconForge Close Checklist Report</h1>
    <p>Local checklist workflow metadata only. No audit opinion, legal sign-off, digital signature, SaaS workflow, or cloud upload.</p>
  </header>
  <main>
    <div class="cards">{cards}</div>
    <section>
      <h2>Task Register</h2>
      {_html_table(tasks)}
    </section>
  </main>
</body>
</html>
""",
        encoding="utf-8",
    )


def _write_markdown(path: Path, summary: pd.DataFrame, tasks: pd.DataFrame) -> None:
    lines = [
        "# ReconForge Close Checklist Summary",
        "",
        "Local checklist workflow metadata only. This report is not an audit opinion, legal sign-off, compliance certification, or digital signature.",
        "",
        "## Summary",
        "",
        *[f"- {_md_escape(row['metric'])}: {_md_escape(row['value'])}" for _, row in summary.iterrows()],
        "",
        "## Tasks",
        "",
    ]
    if tasks.empty:
        lines.append("No tasks found.")
    else:
        for _, row in tasks.iterrows():
            lines.append(
                f"- `{_md_escape(row['task_id'])}` {_md_escape(row['task_name'])}: {_md_escape(row['status'])}"
                f" | category: {_md_escape(row.get('category', ''))}"
                f" | owner: {_md_escape(row.get('owner', ''))}"
                f" | due: {_md_escape(row.get('due_date', ''))}"
                f" | note: {_md_escape(row.get('note', ''))}",
            )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def export_close_report(input_path: Path | str, output_path: Path | str) -> CloseReportArtifacts:
    """Export close checklist HTML, Excel, CSV, Markdown, and JSON reports."""

    checklist = load_close_checklist(input_path)
    output_dir = ensure_output_dir(output_path)
    tasks = close_tasks_frame(checklist)
    summary = close_summary_frame(checklist)
    workbook_path = write_excel_workbook(
        {"Close Summary": summary, "Close Tasks": tasks}, output_dir / "close_report.xlsx"
    )
    csv_path = output_dir / "close_report.csv"
    tasks.to_csv(csv_path, index=False)
    json_path = output_dir / "close_report.json"
    with json_path.open("w", encoding="utf-8") as handle:
        json.dump(
            {
                "summary": frame_to_records(summary),
                "tasks": frame_to_records(tasks),
                "local_first_note": "Generated from a local close checklist file.",
                "workflow_boundary": "No audit opinion, legal sign-off, compliance certification, or digital signature is implied.",
            },
            handle,
            indent=2,
            default=json_default,
        )
    html_path = output_dir / "close_report.html"
    markdown_path = output_dir / "close_summary.md"
    _write_html(html_path, summary, tasks)
    _write_markdown(markdown_path, summary, tasks)
    return CloseReportArtifacts(
        html_path=html_path,
        workbook_path=workbook_path,
        csv_path=csv_path,
        markdown_path=markdown_path,
        json_path=json_path,
    )
