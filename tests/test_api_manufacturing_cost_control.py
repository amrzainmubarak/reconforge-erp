from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from reconforge.api import create_api_app
from reconforge.application.manufacturing_cost_control import (
    run_manufacturing_cost_control_files,
    verify_manufacturing_report,
    write_manufacturing_report,
)
from reconforge.auth.service import LocalAuthService
from reconforge.db import connect, run_migrations
from reconforge.infrastructure.sqlite_manufacturing_cost_control import SQLiteManufacturingCostControlRepository

ORDERS = Path("examples/manufacturing_cost_control/orders.json")
ISSUES = Path("examples/manufacturing_cost_control/issues.json")
COMPLETIONS = Path("examples/manufacturing_cost_control/completions.json")
SCRAP = Path("examples/manufacturing_cost_control/scrap.json")


def _client(tmp_path: Path) -> TestClient:
    db_path = tmp_path / "manufacturing-api.db"
    run_migrations(db_path)
    connection = connect(db_path)
    try:
        LocalAuthService(connection).init_admin(username="admin", password="Secret-123")
    finally:
        connection.close()
    return TestClient(create_api_app(db_path))


def _report(tmp_path: Path) -> dict[str, object]:
    report_path = tmp_path / "report.json"
    run = run_manufacturing_cost_control_files(
        ORDERS,
        ISSUES,
        COMPLETIONS,
        SCRAP,
        currency="EUR",
        tolerance="0.01",
        max_scrap_quantity="2",
        unit="PCS",
    )
    write_manufacturing_report(run, report_path)
    return verify_manufacturing_report(report_path)


def test_manufacturing_local_api_persists_reads_and_isolates_workspace(tmp_path: Path) -> None:
    client = _client(tmp_path)
    report = _report(tmp_path)
    assert client.post("/api/v1/manufacturing/cost-controls", json={"report": report}).status_code == 401
    login = client.post("/api/v1/auth/login", json={"username": "admin", "password": "Secret-123"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    payload = {"report": report, "workspace": "plant-a"}
    first = client.post("/api/v1/manufacturing/cost-controls", json=payload, headers=headers)
    second = client.post("/api/v1/manufacturing/cost-controls", json=payload, headers=headers)
    assert first.status_code == second.status_code == 200, (first.text, second.text)
    assert first.json()["manufacturing_cost_control"] == second.json()["manufacturing_cost_control"]
    assert first.json()["network_dispatch"] == "disabled"
    digest = str(report["decision_digest"])
    fetched = client.get(
        f"/api/v1/manufacturing/cost-controls/{digest}", params={"workspace": "plant-a"}, headers=headers
    )
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["manufacturing_cost_control"] == first.json()["manufacturing_cost_control"]
    assert client.get(
        f"/api/v1/manufacturing/cost-controls/{digest}", params={"workspace": "plant-b"}, headers=headers
    ).status_code == 404
    listed = client.get("/api/v1/manufacturing/cost-controls", params={"workspace": "plant-a"}, headers=headers)
    assert listed.status_code == 200, listed.text
    assert listed.json()["manufacturing_cost_controls"] == [first.json()["manufacturing_cost_control"]]


def test_manufacturing_local_api_rejects_tampered_report_and_unknown_digest(tmp_path: Path) -> None:
    client = _client(tmp_path)
    login = client.post("/api/v1/auth/login", json={"username": "admin", "password": "Secret-123"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    tampered = json.loads(json.dumps(_report(tmp_path)))
    tampered["decisions"][0]["reason_codes"] = ["TAMPERED"]
    response = client.post(
        "/api/v1/manufacturing/cost-controls",
        json={"report": tampered, "workspace": "plant-a"},
        headers=headers,
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "manufacturing_cost_control_persistence_failed"
    missing = client.get(
        "/api/v1/manufacturing/cost-controls/" + ("f" * 64),
        params={"workspace": "plant-a"},
        headers=headers,
    )
    assert missing.status_code == 404


def test_manufacturing_api_drops_future_adapter_fields_recursively(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path)
    report = _report(tmp_path)
    login = client.post("/api/v1/auth/login", json={"username": "admin", "password": "Secret-123"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    baseline = client.post(
        "/api/v1/manufacturing/cost-controls",
        json={"report": report, "workspace": "plant-a"},
        headers=headers,
    )
    assert baseline.status_code == 200, baseline.text
    future = json.loads(json.dumps(baseline.json()["manufacturing_cost_control"]))
    future["unknown_adapter_field"] = "must-not-escape"
    future["report"]["unknown_report_field"] = "must-not-escape"
    future["report"]["amount_tolerance"]["unknown_money_field"] = "must-not-escape"
    future["report"]["max_scrap_quantity"]["unknown_quantity_field"] = "must-not-escape"
    future["report"]["decisions"][0]["unknown_decision_field"] = "must-not-escape"
    decision = future["report"]["decisions"][0]
    for field_name in (
        "actual_material_cost",
        "completion_cost",
        "completion_cost_variance",
        "expected_material_cost",
        "material_cost_variance",
    ):
        if decision[field_name] is not None:
            decision[field_name]["unknown_money_field"] = "must-not-escape"
    for field_name in ("completed_quantity", "issued_quantity", "planned_quantity", "scrap_quantity"):
        if decision[field_name] is not None:
            decision[field_name]["unknown_quantity_field"] = "must-not-escape"

    def fake_put(
        self: SQLiteManufacturingCostControlRepository, payload: dict[str, object], **kwargs: object
    ) -> dict[str, object]:
        return future

    def fake_list(self: SQLiteManufacturingCostControlRepository, **kwargs: object) -> tuple[dict[str, object], ...]:
        return (future,)

    def fake_get(self: SQLiteManufacturingCostControlRepository, **kwargs: object) -> dict[str, object]:
        return future

    monkeypatch.setattr(SQLiteManufacturingCostControlRepository, "put_payload", fake_put)
    monkeypatch.setattr(SQLiteManufacturingCostControlRepository, "list", fake_list)
    monkeypatch.setattr(SQLiteManufacturingCostControlRepository, "get", fake_get)

    created = client.post(
        "/api/v1/manufacturing/cost-controls",
        json={"report": report, "workspace": "plant-a"},
        headers=headers,
    )
    listed = client.get("/api/v1/manufacturing/cost-controls", params={"workspace": "plant-a"}, headers=headers)
    fetched = client.get(
        f"/api/v1/manufacturing/cost-controls/{report['decision_digest']}",
        params={"workspace": "plant-a"},
        headers=headers,
    )

    assert created.status_code == listed.status_code == fetched.status_code == 200
    assert all("unknown_" not in response.text for response in (created, listed, fetched))
    assert listed.json()["manufacturing_cost_controls"][0]["decision_digest"] == report["decision_digest"]


def test_manufacturing_api_boundary_is_packaged() -> None:
    manifest = Path("MANIFEST.in").read_text(encoding="utf-8")
    assert "include reconforge/api/routes/manufacturing_cost_control.py" in manifest
    assert "include reconforge/infrastructure/sqlite_manufacturing_cost_control.py" in manifest
    assert "include tests/test_api_manufacturing_cost_control.py" in manifest
