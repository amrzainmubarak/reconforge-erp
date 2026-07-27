from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

import reconforge.db.migrations as migration_module
from reconforge.api import create_api_app
from reconforge.audit import list_audit_events, verify_audit_events
from reconforge.auth import LocalAuthService
from reconforge.cli import app
from reconforge.db import connect, run_migrations
from reconforge.db.exporter import export_database
from reconforge.platform import PlatformError
from reconforge.platform.master_data import MasterDataService

runner = CliRunner()


def _database(tmp_path: Path, name: str = "master_data.db") -> Path:
    path = tmp_path / name
    run_migrations(path)
    return path


def _api_setup(tmp_path: Path) -> tuple[TestClient, Path]:
    path = _database(tmp_path, "master_data_api.db")
    connection = connect(path, require_exists=True)
    try:
        auth = LocalAuthService(connection)
        auth.init_admin(username="admin", password="Secret-123")
        auth.create_user(username="controller", password="Secret-123", role="controller")
        auth.create_user(username="reviewer", password="Secret-123", role="reviewer")
    finally:
        connection.close()
    return TestClient(create_api_app(path)), path


def _token(client: TestClient, username: str) -> str:
    response = client.post("/api/v1/auth/login", json={"username": username, "password": "Secret-123"})
    assert response.status_code == 200
    return str(response.json()["access_token"])


def test_master_data_service_enforces_relationships_periods_and_audit(tmp_path: Path) -> None:
    path = _database(tmp_path)
    connection = connect(path, require_exists=True)
    try:
        service = MasterDataService(connection)
        currency = service.upsert_currency(code="jpy", name="Japanese Yen", minor_units=0)
        organization = service.upsert_organization(organization_code="syn", name="Synthetic Group")
        entity = service.upsert_legal_entity(
            organization_code="SYN",
            entity_code="JP01",
            name="Synthetic Japan",
            currency_code="JPY",
        )
        branch = service.upsert_branch(
            organization_code="SYN",
            branch_code="TYO",
            name="Tokyo",
            entity_code="JP01",
        )
        period = service.upsert_period(
            name="2026-07",
            start_date="2026-07-01",
            end_date="2026-07-31",
        )
        renamed = service.upsert_organization(organization_code="SYN", name="Synthetic Group Updated")
        service.upsert_organization(organization_code="SYN2", name="Synthetic Group Two")
        soft_closed = service.set_period_status(str(period["id"]), status="Soft Closed")
        closed = service.set_period_status(str(period["id"]), status="Closed")
        reopened = service.set_period_status(str(period["id"]), status="Open", reason="Synthetic correction")
        summary = service.summary()
        snapshot = service.snapshot()

        assert currency["code"] == "JPY"
        assert currency["minor_units"] == 0
        assert organization["organization_code"] == "SYN"
        assert renamed["id"] == organization["id"]
        assert entity["currency"] == "JPY"
        assert branch["legal_entity_id"] == entity["id"]
        assert branch["entity_code"] == "JP01"
        assert soft_closed["status"] == "Soft Closed"
        assert closed["status"] == "Closed"
        assert reopened["status_reason"] == "Synthetic correction"
        assert summary.to_dict() == {
            "workspace": "default",
            "organizations": 2,
            "legal_entities": 1,
            "branches": 1,
            "periods": 1,
            "active_currencies": 7,
        }
        assert [row["organization_code"] for row in service.list_organizations(limit=1, offset=1)] == ["SYN2"]
        assert len(service.list_legal_entities()) == 1
        assert len(service.list_branches()) == 1
        assert len(service.list_periods()) == 1
        assert snapshot["schema_version"] == 1
        assert snapshot["source"] == {
            "kind": "local-sqlite-master-data",
            "local_first": True,
            "external_calls": False,
        }
        assert snapshot["branches"][0]["branch_code"] == "TYO"
        assert "source_path" not in json.dumps(snapshot)
        with pytest.raises(PlatformError, match="List limit"):
            service.list_organizations(limit=0)

        events = list_audit_events(connection)
        actions = {event.action for event in events}
        assert {
            "currency_upserted",
            "organization_upserted",
            "legal_entity_upserted",
            "branch_upserted",
            "fiscal_period_upserted",
            "fiscal_period_status_changed",
        } <= actions
        assert verify_audit_events(connection).ok is True
    finally:
        connection.close()


def test_master_data_rejects_invalid_currency_overlap_cross_scope_and_transitions(tmp_path: Path) -> None:
    path = _database(tmp_path)
    connection = connect(path, require_exists=True)
    try:
        service = MasterDataService(connection)
        service.upsert_organization(organization_code="ORG1", name="Organization One")
        service.upsert_organization(organization_code="ORG2", name="Organization Two")
        service.upsert_legal_entity(
            organization_code="ORG2",
            entity_code="E2",
            name="Entity Two",
            currency_code="USD",
        )
        service.upsert_currency(code="CAD", name="Canadian Dollar", active=False)
        first_period = service.upsert_period(name="P1", start_date="2026-01-01", end_date="2026-01-31")

        with pytest.raises(PlatformError, match="Currency reference was not found"):
            service.upsert_legal_entity(
                organization_code="ORG1",
                entity_code="E1",
                name="Entity One",
                currency_code="ZZZ",
            )
        with pytest.raises(PlatformError, match="active currency"):
            service.upsert_legal_entity(
                organization_code="ORG1",
                entity_code="E1",
                name="Entity One",
                currency_code="CAD",
            )
        with pytest.raises(PlatformError, match="selected organization"):
            service.upsert_branch(
                organization_code="ORG1",
                branch_code="B1",
                name="Branch One",
                entity_code="E2",
            )
        with pytest.raises(PlatformError, match="must not overlap"):
            service.upsert_period(name="P2", start_date="2026-01-15", end_date="2026-02-15")
        with pytest.raises(PlatformError, match="Invalid fiscal-period status transition"):
            service.set_period_status(str(first_period["id"]), status="Closed")
        service.set_period_status(str(first_period["id"]), status="Soft Closed")
        service.set_period_status(str(first_period["id"]), status="Closed")
        with pytest.raises(PlatformError, match="requires a reason"):
            service.set_period_status(str(first_period["id"]), status="Open")
        with pytest.raises(PlatformError, match="Organization code"):
            service.upsert_organization(organization_code="unsafe code", name="Unsafe")
    finally:
        connection.close()


def test_master_data_service_enforces_seeded_rbac(tmp_path: Path) -> None:
    path = _database(tmp_path)
    connection = connect(path, require_exists=True)
    try:
        auth = LocalAuthService(connection)
        auth.init_admin(username="admin", password="Secret-123")
        auth.create_user(username="controller", password="Secret-123", role="controller")
        auth.create_user(username="reviewer", password="Secret-123", role="reviewer")
        service = MasterDataService(connection)

        created = service.upsert_organization(
            organization_code="SYN",
            name="Synthetic Group",
            actor_label="controller",
        )
        visible = service.list_organizations(actor_label="reviewer")

        assert visible == [created]
        with pytest.raises(PlatformError, match="Permission denied"):
            service.upsert_organization(
                organization_code="DENIED",
                name="Denied Organization",
                actor_label="reviewer",
            )
    finally:
        connection.close()


def test_master_data_api_is_authenticated_rbac_protected_and_strict(tmp_path: Path) -> None:
    client, _ = _api_setup(tmp_path)
    controller_headers = {"Authorization": f"Bearer {_token(client, 'controller')}"}
    reviewer_headers = {"Authorization": f"Bearer {_token(client, 'reviewer')}"}

    created_org = client.post(
        "/api/v1/master-data/organizations",
        headers=controller_headers,
        json={"organization_code": "SYN", "name": "Synthetic Group"},
    )
    created_entity = client.post(
        "/api/v1/master-data/entities",
        headers=controller_headers,
        json={
            "organization_code": "SYN",
            "entity_code": "EG01",
            "name": "Synthetic Egypt",
            "currency_code": "EGP",
        },
    )
    created_period = client.post(
        "/api/v1/master-data/periods",
        headers=controller_headers,
        json={"name": "2026-07", "start_date": "2026-07-01", "end_date": "2026-07-31"},
    )
    listed = client.get("/api/v1/master-data/organizations", headers=reviewer_headers)
    paged = client.get("/api/v1/master-data/organizations?limit=1&offset=0", headers=reviewer_headers)
    invalid_page = client.get("/api/v1/master-data/organizations?limit=1001", headers=reviewer_headers)
    summary = client.get("/api/v1/master-data/summary", headers=reviewer_headers)
    snapshot = client.get("/api/v1/master-data/snapshot", headers=reviewer_headers)
    denied = client.post(
        "/api/v1/master-data/organizations",
        headers=reviewer_headers,
        json={"organization_code": "NO", "name": "Denied"},
    )
    unauthenticated = client.get("/api/v1/master-data/currencies")
    malformed = client.post(
        "/api/v1/master-data/currencies",
        headers=controller_headers,
        json={"code": "USD", "name": "Dollar", "unexpected": "rejected"},
    )
    overlap = client.post(
        "/api/v1/master-data/periods",
        headers=controller_headers,
        json={"name": "Overlap", "start_date": "2026-07-15", "end_date": "2026-08-15"},
    )
    period_id = str(created_period.json()["period"]["id"])
    soft_close = client.post(
        f"/api/v1/master-data/periods/{period_id}/status",
        headers=controller_headers,
        json={"status": "Soft Closed"},
    )

    assert created_org.status_code == 200
    assert created_entity.status_code == 200
    assert created_period.status_code == 200
    assert listed.status_code == 200
    assert listed.json()["organizations"][0]["organization_code"] == "SYN"
    assert listed.json()["pagination"] == {"limit": 500, "offset": 0, "returned": 1}
    assert paged.json()["pagination"] == {"limit": 1, "offset": 0, "returned": 1}
    assert invalid_page.status_code == 422
    assert summary.json()["summary"]["legal_entities"] == 1
    assert snapshot.status_code == 200
    assert snapshot.json()["schema_version"] == 1
    assert denied.status_code == 403
    assert unauthenticated.status_code == 401
    assert malformed.status_code == 422
    assert overlap.status_code == 400
    assert soft_close.json()["period"]["status"] == "Soft Closed"
    combined = denied.text + unauthenticated.text + malformed.text + overlap.text + invalid_page.text
    assert "Traceback" not in combined
    assert "sqlite" not in combined.lower()


def test_master_data_cli_workflow_and_safe_failure(tmp_path: Path) -> None:
    path = tmp_path / "master_data_cli.db"
    initialized = runner.invoke(app, ["db", "init", "--db", str(path)])
    organization = runner.invoke(
        app,
        ["master-data", "organization-upsert", "--code", "SYN", "--name", "Synthetic Group", "--db", str(path)],
    )
    entity = runner.invoke(
        app,
        [
            "master-data",
            "entity-upsert",
            "--organization",
            "SYN",
            "--code",
            "EG01",
            "--name",
            "Synthetic Egypt",
            "--currency",
            "EGP",
            "--db",
            str(path),
        ],
    )
    branch = runner.invoke(
        app,
        [
            "master-data",
            "branch-upsert",
            "--organization",
            "SYN",
            "--code",
            "CAI",
            "--name",
            "Cairo",
            "--entity",
            "EG01",
            "--db",
            str(path),
        ],
    )
    period = runner.invoke(
        app,
        [
            "master-data",
            "period-upsert",
            "--name",
            "2026-07",
            "--start",
            "2026-07-01",
            "--end",
            "2026-07-31",
            "--db",
            str(path),
        ],
    )
    summary = runner.invoke(app, ["master-data", "summary", "--db", str(path)])
    snapshot = runner.invoke(app, ["master-data", "snapshot", "--db", str(path)])
    paged = runner.invoke(app, ["master-data", "organizations", "--limit", "1", "--db", str(path)])
    rejected = runner.invoke(
        app,
        ["master-data", "organization-upsert", "--code", "bad code", "--name", "Bad", "--db", str(path)],
    )

    assert initialized.exit_code == 0
    assert organization.exit_code == entity.exit_code == branch.exit_code == period.exit_code == 0
    assert summary.exit_code == 0
    assert snapshot.exit_code == 0
    assert paged.exit_code == 0
    assert "Synthetic Group" in organization.output
    assert "EG01" in entity.output
    assert "CAI" in branch.output
    assert "2026-07" in period.output
    assert "organizations" in summary.output
    assert json.loads(snapshot.output)["summary"]["branches"] == 1
    assert rejected.exit_code == 1
    assert "Organization code" in rejected.output
    assert "Traceback" not in rejected.output


def test_migration_seven_upgrades_v6_data_and_export_includes_master_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "upgrade.db"
    full_migrations = migration_module.MIGRATIONS
    monkeypatch.setattr(migration_module, "MIGRATIONS", full_migrations[:6])
    first = migration_module.run_migrations(path)
    assert first.current_version == 6

    connection = connect(path, require_exists=True)
    try:
        connection.execute(
            "INSERT INTO workspaces (id, name, local_first_note, created_at) VALUES ('WS-old', 'old', 'local', '2026-01-01T00:00:00Z')"
        )
        connection.execute(
            "INSERT INTO organizations (id, workspace_id, name, created_at) VALUES ('ORG-old', 'WS-old', 'Old Organization', '2026-01-01T00:00:00Z')"
        )
        connection.execute(
            """
            INSERT INTO legal_entities (id, organization_id, entity_code, name, currency, created_at)
            VALUES ('LE-old', 'ORG-old', 'OLD', 'Old Entity', 'USD', '2026-01-01T00:00:00Z')
            """
        )
        connection.execute(
            """
            INSERT INTO periods (id, workspace_id, name, start_date, end_date, status, created_at)
            VALUES ('PER-old', 'WS-old', '2026-01', '2026-01-01', '2026-01-31', 'Open', '2026-01-01T00:00:00Z')
            """
        )
        connection.commit()
    finally:
        connection.close()

    monkeypatch.setattr(migration_module, "MIGRATIONS", full_migrations)
    upgraded = migration_module.run_migrations(path)

    assert upgraded.applied_versions == list(range(7, migration_module.MIGRATIONS[-1].version + 1))
    assert upgraded.current_version == migration_module.MIGRATIONS[-1].version
    connection = connect(path, require_exists=True)
    try:
        organization = connection.execute("SELECT * FROM organizations WHERE id = 'ORG-old'").fetchone()
        entity = connection.execute("SELECT * FROM legal_entities WHERE id = 'LE-old'").fetchone()
        period = connection.execute("SELECT * FROM periods WHERE id = 'PER-old'").fetchone()
        assert organization is not None and organization["organization_code"]
        assert entity is not None and entity["active"] == 1
        assert period is not None and period["fiscal_year"] == 2026 and period["period_number"] == 1
    finally:
        connection.close()

    exported = export_database(path, tmp_path / "export")
    assert exported.schema_version == migration_module.MIGRATIONS[-1].version
    domain = json.loads((tmp_path / "export" / "domain.json").read_text(encoding="utf-8"))
    assert "currencies" in domain
    assert "branches" in domain
    assert domain["legal_entities"][0]["entity_code"] == "OLD"
