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
from reconforge.utils.safe_paths import build_download_registry, get_registered_download, is_safe_download_key


def _endpoint(app: Any, route_path: str) -> Callable[..., Any]:
    for route in app.routes:
        if isinstance(route, APIRoute) and route.path == route_path:
            return cast(Callable[..., Any], route.endpoint)
    raise AssertionError(f"Route not found: {route_path}")


def test_download_registry_accepts_normal_filename(tmp_path: Path) -> None:
    report_path = tmp_path / "report.csv"
    report_path.write_text("a,b\n1,2\n", encoding="utf-8")
    registry = build_download_registry(tmp_path, allowed_suffixes={".csv"})

    assert get_registered_download(registry, "report.csv") == report_path.resolve()


def test_download_registry_accepts_recursive_evidence_key(tmp_path: Path) -> None:
    summary_path = tmp_path / "EXC-0001" / "summary.md"
    summary_path.parent.mkdir()
    summary_path.write_text("# Evidence\n", encoding="utf-8")
    registry = build_download_registry(tmp_path, allowed_suffixes={".md"}, recursive=True)

    assert get_registered_download(registry, "EXC-0001/summary.md") == summary_path.resolve()


def test_download_registry_rejects_parent_traversal(tmp_path: Path) -> None:
    registry = build_download_registry(tmp_path, allowed_suffixes={".txt"})

    with pytest.raises(ValueError, match="Unsafe"):
        get_registered_download(registry, "../secret.txt")


def test_download_registry_rejects_absolute_windows_path(tmp_path: Path) -> None:
    registry = build_download_registry(tmp_path, allowed_suffixes={".txt"})

    with pytest.raises(ValueError, match="Unsafe"):
        get_registered_download(registry, "C:/Users/amrza/secret.txt")


def test_download_registry_rejects_absolute_posix_path(tmp_path: Path) -> None:
    registry = build_download_registry(tmp_path, allowed_suffixes={".txt"})

    with pytest.raises(ValueError, match="Unsafe"):
        get_registered_download(registry, "/tmp/secret.txt")


def test_download_registry_rejects_backslash_path(tmp_path: Path) -> None:
    registry = build_download_registry(tmp_path, allowed_suffixes={".txt"})

    with pytest.raises(ValueError, match="Unsafe"):
        get_registered_download(registry, r"reports\secret.txt")


def test_download_registry_excludes_unsupported_suffix(tmp_path: Path) -> None:
    (tmp_path / "report.exe").write_text("nope\n", encoding="utf-8")
    registry = build_download_registry(tmp_path, allowed_suffixes={".csv"})

    assert "report.exe" not in registry
    with pytest.raises(FileNotFoundError):
        get_registered_download(registry, "report.exe")


def test_is_safe_download_key_rejects_double_slashes_and_control_characters() -> None:
    assert not is_safe_download_key("EXC-0001//summary.md")
    assert not is_safe_download_key("summary.md\x00")


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
    assert response.text.replace("\r\n", "\n") == "a,b\n1,2\n"


def test_dashboard_download_route_rejects_backslash(tmp_path: Path) -> None:
    app = create_app(tmp_path)
    report = _endpoint(app, "/reports/{filename}")

    with pytest.raises(HTTPException) as exc_info:
        report(r"reports\secret.txt")

    assert exc_info.value.status_code == 400


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


def test_studio_report_download_route_still_serves_file(tmp_path: Path) -> None:
    (tmp_path / "summary.md").write_text("# Summary\n", encoding="utf-8")
    client = TestClient(create_studio_app("examples/sample_data", tmp_path))

    response = client.get("/download/summary.md")

    assert response.status_code == 200
    assert "# Summary" in response.text


def test_studio_evidence_download_route_still_serves_file(tmp_path: Path) -> None:
    evidence_dir = tmp_path / "evidence" / "EXC-001"
    evidence_dir.mkdir(parents=True)
    (evidence_dir / "summary.md").write_text("# Evidence\n", encoding="utf-8")
    client = TestClient(create_studio_app("examples/sample_data", tmp_path))

    response = client.get("/download/evidence/EXC-001/summary.md")

    assert response.status_code == 200
    assert "# Evidence" in response.text


def test_studio_doc_download_route_still_serves_file(tmp_path: Path) -> None:
    client = TestClient(create_studio_app("examples/sample_data", tmp_path))

    assert client.get("/download-doc/security-model.md").status_code == 200
