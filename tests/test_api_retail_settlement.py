from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from reconforge.api import create_api_app
from reconforge.application.retail_settlement import (
    run_retail_settlement_files,
    verify_retail_settlement_report,
    write_retail_settlement_report,
)
from reconforge.auth.service import LocalAuthService
from reconforge.db import connect, run_migrations


def _client(tmp_path: Path) -> TestClient:
    db_path = tmp_path / "retail-api.db"
    run_migrations(db_path)
    connection = connect(db_path)
    try:
        LocalAuthService(connection).init_admin(username="admin", password="Secret-123")
    finally:
        connection.close()
    return TestClient(create_api_app(db_path))


def _report(tmp_path: Path) -> dict[str, object]:
    report_path = tmp_path / "report.json"
    run = run_retail_settlement_files(
        Path("examples/retail_settlement/pos_batches.json"),
        Path("examples/retail_settlement/settlements.json"),
        currency="USD",
        tolerance="0.01",
    )
    write_retail_settlement_report(run, report_path)
    return verify_retail_settlement_report(report_path)


def test_retail_api_boundary_is_packaged() -> None:
    manifest = Path("MANIFEST.in").read_text(encoding="utf-8")
    assert "include docs/adr/0449-retail-settlement-local-api-boundary.md" in manifest
    assert "include reconforge/api/routes/retail_settlement.py" in manifest
    assert "include tests/test_api_retail_settlement.py" in manifest


def test_local_retail_api_persists_reads_and_isolates_workspace(tmp_path: Path) -> None:
    client = _client(tmp_path)
    report = _report(tmp_path)
    assert client.post("/api/v1/retail/settlements", json={"report": report}).status_code == 401
    login = client.post("/api/v1/auth/login", json={"username": "admin", "password": "Secret-123"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    payload = {"report": report, "workspace": "shop-a"}
    first = client.post("/api/v1/retail/settlements", json=payload, headers=headers)
    second = client.post("/api/v1/retail/settlements", json=payload, headers=headers)
    assert first.status_code == second.status_code == 200, (first.text, second.text)
    assert first.json()["settlement"] == second.json()["settlement"]
    digest = str(report["decision_digest"])

    fetched = client.get(
        f"/api/v1/retail/settlements/{digest}", params={"workspace": "shop-a"}, headers=headers
    )
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["settlement"] == first.json()["settlement"]
    assert client.get(
        f"/api/v1/retail/settlements/{digest}", params={"workspace": "shop-b"}, headers=headers
    ).status_code == 404
    listed = client.get("/api/v1/retail/settlements", params={"workspace": "shop-a"}, headers=headers)
    assert listed.status_code == 200, listed.text
    assert listed.json()["settlements"] == [first.json()["settlement"]]


def test_local_retail_api_rejects_tampered_report_and_unknown_digest(tmp_path: Path) -> None:
    client = _client(tmp_path)
    login = client.post("/api/v1/auth/login", json={"username": "admin", "password": "Secret-123"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    tampered = json.loads(json.dumps(_report(tmp_path)))
    tampered["decisions"][0]["status"] = "exception"
    response = client.post(
        "/api/v1/retail/settlements",
        json={"report": tampered, "workspace": "shop-a"},
        headers=headers,
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "retail_settlement_persistence_failed"
    missing = client.get(
        "/api/v1/retail/settlements/" + ("f" * 64),
        params={"workspace": "shop-a"},
        headers=headers,
    )
    assert missing.status_code == 404
