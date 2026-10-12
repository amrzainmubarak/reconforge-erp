"""Authenticated local HTTP acceptance for governed budget envelopes."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from reconforge.api import create_api_app
from reconforge.auth import LocalAuthService
from reconforge.db import connect, run_migrations
from reconforge.platform.master_data import MasterDataService

PASSWORD = "Synthetic-Amr-Budget-API-2026!"
PERMISSIONS = frozenset({"budget_control.read", "budget_control.manage", "budget_control.approve"})


@pytest.fixture
def budget_api(tmp_path: Path) -> Iterator[tuple[TestClient, dict[str, str], dict[str, dict[str, str]]]]:
    database = tmp_path / "budget-api.db"
    run_migrations(database)
    connection = connect(database)
    try:
        master_data = MasterDataService(connection)
        organization = master_data.upsert_organization(
            organization_code="SYN",
            name="Synthetic budget API organization",
        )
        entity = master_data.upsert_legal_entity(
            organization_code="SYN",
            entity_code="EG",
            name="Synthetic budget API entity",
            currency_code="EGP",
        )
        period = master_data.upsert_period(
            name="2026-10",
            start_date="2026-10-01",
            end_date="2026-10-31",
        )
        auth = LocalAuthService(connection)
        for username in ("maker", "checker"):
            auth.create_user(
                username=username,
                password=PASSWORD,
                display_name=f"Synthetic {username}",
                role="controller",
            )
        role_id = connection.execute("SELECT id FROM roles WHERE name='controller'").fetchone()[0]
        assigned = {
            str(row[0])
            for row in connection.execute("SELECT permission_name FROM role_permissions WHERE role_id=?", (role_id,))
        }
        assert assigned >= PERMISSIONS
        scope = {
            "workspace_id": str(organization["workspace_id"]),
            "organization_id": str(organization["id"]),
            "legal_entity_id": str(entity["id"]),
            "period_id": str(period["id"]),
        }
    finally:
        connection.close()

    app = create_api_app(database)
    with TestClient(app) as client:
        headers: dict[str, dict[str, str]] = {}
        for username in ("maker", "checker"):
            response = client.post("/api/v1/auth/login", json={"username": username, "password": PASSWORD})
            assert response.status_code == 200, response.text
            headers[username] = {"Authorization": "Bearer " + response.json()["access_token"]}
        yield client, scope, headers


def _draft(scope: dict[str, str], *, command_id: str = "budget-create") -> dict[str, Any]:
    return {
        **{key: scope[key] for key in ("workspace_id", "organization_id", "legal_entity_id")},
        "budget_code": "OPS-API",
        "name": "Synthetic API appropriation",
        "period_id": scope["period_id"],
        "currency_code": "EGP",
        "limit_minor": "10000",
        "command_id": command_id,
    }


def _review(scope: dict[str, str], *, version: int, command_id: str, reason: str) -> dict[str, Any]:
    return {
        **{key: scope[key] for key in ("workspace_id", "organization_id", "legal_entity_id")},
        "expected_version": version,
        "command_id": command_id,
        "reason": reason,
    }


def test_authenticated_local_api_enforces_maker_checker_exact_replay_and_current_reads(budget_api: Any) -> None:
    client, scope, headers = budget_api
    assert client.post("/api/v1/budget-control/envelopes", json=_draft(scope)).status_code == 401
    created = client.post("/api/v1/budget-control/envelopes", headers=headers["maker"], json=_draft(scope))
    assert created.status_code == 200, created.text
    envelope = created.json()
    assert envelope["status"] == "Draft"
    assert envelope["limit_minor"] == "10000"
    assert envelope["monetary_policy"]["precision"] == 2
    assert client.post("/api/v1/budget-control/envelopes", headers=headers["maker"], json=_draft(scope)).json() == envelope
    changed = client.post(
        "/api/v1/budget-control/envelopes",
        headers=headers["maker"],
        json={**_draft(scope), "name": "Changed request"},
    )
    assert changed.status_code == 409 and changed.json()["error"]["code"] == "budget_control_conflict"
    submitted = client.post(
        f"/api/v1/budget-control/envelopes/{envelope['id']}/submit",
        headers=headers["maker"],
        json=_review(scope, version=1, command_id="budget-submit", reason="Synthetic submission"),
    )
    assert submitted.status_code == 200, submitted.text
    self_approval = client.post(
        f"/api/v1/budget-control/envelopes/{envelope['id']}/approve",
        headers=headers["maker"],
        json=_review(scope, version=2, command_id="budget-self", reason="Synthetic self review"),
    )
    assert self_approval.status_code == 403
    approved = client.post(
        f"/api/v1/budget-control/envelopes/{envelope['id']}/approve",
        headers=headers["checker"],
        json=_review(scope, version=2, command_id="budget-approve", reason="Synthetic independent review"),
    )
    assert approved.status_code == 200, approved.text
    reserve = client.post(
        f"/api/v1/budget-control/envelopes/{envelope['id']}/commitments",
        headers=headers["maker"],
        json={
            **_review(scope, version=3, command_id="budget-reserve", reason="Synthetic purchase commitment"),
            "operation": "Reserve",
            "amount_minor": "4000",
            "operation_date": "2026-10-03",
            "source_reference": "PO/SYN/API/1",
        },
    )
    assert reserve.status_code == 200, reserve.text
    assert reserve.json()["available_minor"] == "6000"
    fetched = client.get(
        f"/api/v1/budget-control/envelopes/{envelope['id']}",
        headers=headers["checker"],
        params={key: scope[key] for key in ("workspace_id", "organization_id", "legal_entity_id")},
    )
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["events"][0]["amount_minor"] == "4000"
    listed = client.get(
        "/api/v1/budget-control/envelopes",
        headers=headers["checker"],
        params={key: scope[key] for key in ("workspace_id", "organization_id", "legal_entity_id")},
    )
    assert listed.status_code == 200, listed.text
    assert [item["id"] for item in listed.json()["envelopes"]] == [envelope["id"]]
