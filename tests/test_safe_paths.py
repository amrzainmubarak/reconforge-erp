from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from reconforge.dashboard.app import create_app
from reconforge.studio.app import create_studio_app
from reconforge.utils.safe_paths import safe_resolve_child


def _endpoint(app: Any, route_path: str) -> Callable[..., Any]:
    for route in app.routes:
        if isinstance(route, APIRoute) and route.path == route_path:
            return cast(Callable[..., Any], route.endpoint)
    raise AssertionError(f"Route not found: {route_path}")


def test_safe_resolve_child_accepts_normal_filename(tmp_path: Path) -> None:
    assert safe_resolve_child(tmp_path, "report.csv") == (tmp_path / "report.csv").resolve()


def test_safe_resolve_child_rejects_parent_traversal(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="traversal"):
        safe_resolve_child(tmp_path, "../secret.txt")


def test_safe_resolve_child_rejects_absolute_paths(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Absolute"):
        safe_resolve_child(tmp_path, str((tmp_path / "secret.txt").resolve()))


def test_safe_resolve_child_rejects_nested_traversal(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="traversal"):
        safe_resolve_child(tmp_path, "reports/../../secret.txt")


def test_safe_resolve_child_rejects_unsupported_suffix(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="File type"):
        safe_resolve_child(tmp_path, "report.exe", allowed_suffixes={".csv"})


def test_dashboard_download_route_rejects_traversal(tmp_path: Path) -> None:
    app = create_app(tmp_path)
    report = _endpoint(app, "/reports/{filename}")

    with pytest.raises(HTTPException) as exc_info:
        report("../secret.txt")

    assert exc_info.value.status_code == 400


def test_dashboard_download_route_still_serves_report(tmp_path: Path) -> None:
    (tmp_path / "report.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    client = TestClient(create_app(tmp_path))

    response = client.get("/reports/report.csv")

    assert response.status_code == 200
    assert response.text == "a,b\n1,2\n"


def test_studio_download_route_rejects_traversal(tmp_path: Path) -> None:
    app = create_studio_app("examples/sample_data", tmp_path)
    download = _endpoint(app, "/download/{filename}")

    with pytest.raises(HTTPException) as exc_info:
        download("../secret.txt")

    assert exc_info.value.status_code == 400


def test_studio_evidence_route_rejects_case_traversal(tmp_path: Path) -> None:
    app = create_studio_app("examples/sample_data", tmp_path)
    download_evidence = _endpoint(app, "/download/evidence/{case_id}/{filename}")

    with pytest.raises(HTTPException) as exc_info:
        download_evidence("../outside", "summary.md")

    assert exc_info.value.status_code == 400


def test_studio_evidence_route_rejects_file_traversal(tmp_path: Path) -> None:
    app = create_studio_app("examples/sample_data", tmp_path)
    download_evidence = _endpoint(app, "/download/evidence/{case_id}/{filename}")

    with pytest.raises(HTTPException) as exc_info:
        download_evidence("EXC-001", "../secret.txt")

    assert exc_info.value.status_code == 400


def test_studio_doc_route_rejects_traversal(tmp_path: Path) -> None:
    app = create_studio_app("examples/sample_data", tmp_path)
    download_doc = _endpoint(app, "/download-doc/{filename}")

    with pytest.raises(HTTPException) as exc_info:
        download_doc("../README.md")

    assert exc_info.value.status_code == 400


def test_studio_download_routes_still_serve_files(tmp_path: Path) -> None:
    (tmp_path / "summary.md").write_text("# Summary\n", encoding="utf-8")
    evidence_dir = tmp_path / "evidence" / "EXC-001"
    evidence_dir.mkdir(parents=True)
    (evidence_dir / "summary.md").write_text("# Evidence\n", encoding="utf-8")
    client = TestClient(create_studio_app("examples/sample_data", tmp_path))

    assert client.get("/download/summary.md").status_code == 200
    assert client.get("/download/evidence/EXC-001/summary.md").status_code == 200
    assert client.get("/download-doc/security-model.md").status_code == 200
