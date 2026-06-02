"""FastAPI dashboard for generated ReconForge output."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, Response

from reconforge.utils.safe_paths import safe_resolve_child

DOWNLOAD_SUFFIXES = {".html", ".xlsx", ".csv", ".json", ".md", ".txt", ".yml", ".yaml"}
TEXT_DOWNLOAD_SUFFIXES = DOWNLOAD_SUFFIXES - {".xlsx"}


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _report_links(output_dir: Path) -> list[str]:
    return sorted(file.name for file in output_dir.iterdir() if file.is_file() and file.suffix.lower() in DOWNLOAD_SUFFIXES)


def _download_response(path: Path, media_type: str) -> Response:
    if path.suffix.lower() in TEXT_DOWNLOAD_SUFFIXES:
        return Response(
            content=path.read_text(encoding="utf-8"),
            media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="{path.name}"'},
        )
    return FileResponse(path, media_type=media_type, filename=path.name)


def create_app(output_dir: Path | str) -> FastAPI:
    """Create a local FastAPI app serving generated reports."""

    base_path = Path(output_dir)
    app = FastAPI(title="ReconForge ERP Dashboard", version="0.3.0")

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        dashboard_path = base_path / "dashboard.html"
        if dashboard_path.exists():
            html = dashboard_path.read_text(encoding="utf-8")
            links = "".join(f'<li><a href="/reports/{name}">{name}</a></li>' for name in _report_links(base_path))
            return html.replace("</main>", f'<section class="report"><h2>Downloadable Reports</h2><ul>{links}</ul></section></main>')

        payload = _load_json(base_path / "management_pack.json")
        executive = payload.get("executive_summary", [])
        cards = "".join(
            f"<section class='card'><span>{item.get('metric')}</span><strong>{item.get('value')}</strong></section>"
            for item in executive
        )
        links = "".join(f'<li><a href="/reports/{name}">{name}</a></li>' for name in _report_links(base_path))
        return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ReconForge ERP Dashboard</title>
  <style>
    body {{ font-family: Segoe UI, Arial, sans-serif; margin: 0; background: #f6f8fb; color: #182230; }}
    header {{ background: #17324d; color: #fff; padding: 28px 40px; }}
    main {{ padding: 28px; max-width: 1100px; margin: 0 auto; }}
    .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 14px; }}
    .card {{ background: #fff; border: 1px solid #dce3ea; border-radius: 8px; padding: 16px; }}
    .card span {{ display: block; color: #667085; font-size: 13px; }}
    .card strong {{ display: block; font-size: 24px; margin-top: 8px; }}
  </style>
</head>
<body>
  <header><h1>ReconForge ERP Dashboard</h1></header>
  <main><div class="cards">{cards}</div><h2>Downloadable Reports</h2><ul>{links}</ul></main>
</body>
</html>"""

    @app.get("/api/summary")
    def summary() -> dict[str, Any]:
        return _load_json(base_path / "management_pack.json")

    @app.get("/reports/{filename}")
    def report(filename: str) -> Response:
        try:
            path = safe_resolve_child(base_path, filename, allowed_suffixes=DOWNLOAD_SUFFIXES)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid filename") from None
        if not path.exists() or not path.is_file():
            raise HTTPException(status_code=404, detail="Report not found")
        media_types = {
            ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ".csv": "text/csv",
            ".json": "application/json",
            ".md": "text/markdown",
            ".html": "text/html",
            ".txt": "text/plain",
            ".yml": "application/x-yaml",
            ".yaml": "application/x-yaml",
        }
        return _download_response(path, media_types.get(path.suffix.lower(), "application/octet-stream"))

    return app
