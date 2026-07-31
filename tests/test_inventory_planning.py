from __future__ import annotations

import json
import sqlite3
from importlib import import_module
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from typer.testing import CliRunner

import reconforge.db.migrations as migration_module
from reconforge.api import create_api_app
from reconforge.audit import list_audit_events, verify_audit_events
from reconforge.auth import LocalAuthService
from reconforge.cli import app
from reconforge.db import connect, run_migrations
from reconforge.db.backup import create_backup, restore_backup
from reconforge.db.exporter import export_database
from reconforge.platform import PlatformError
from reconforge.platform.finance_core import FinanceCoreService
from reconforge.platform.inventory_core import InventoryCoreService
from reconforge.platform.inventory_planning import InventoryPlanningService
from reconforge.platform.inventory_planning_repository import SQLiteInventoryPlanningRepository
from reconforge.platform.master_data import MasterDataService

planning_module = import_module("reconforge.infrastructure.sqlite_inventory_planning")

runner = CliRunner()
SCHEMA_DIR = Path(__file__).resolve().parents[1] / "docs" / "schemas"


def _assert_contract(filename: str, payload: object) -> None:
    schema = json.loads((SCHEMA_DIR / filename).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(payload)


def _database(tmp_path: Path, name: str = "planning.db") -> Path:
    path = tmp_path / name
    run_migrations(path)
    return path


def _seed(connection: sqlite3.Connection) -> tuple[InventoryCoreService, InventoryPlanningService, str]:
    master = MasterDataService(connection)
    master.upsert_organization(organization_code="SYN", name="Synthetic Group")
    master.upsert_legal_entity(
        organization_code="SYN",
        entity_code="EG01",
        name="Synthetic Egypt",
        currency_code="EGP",
    )
    period = master.upsert_period(name="2026-07", start_date="2026-07-01", end_date="2026-07-31")
    FinanceCoreService(connection).upsert_account(
        account_code="1400",
        name="Inventory control",
        account_type="Asset",
        normal_balance="Debit",
    )
    inventory = InventoryCoreService(connection)
    inventory.upsert_uom(uom_code="KG", name="Kilogram", category="Weight", decimal_places=3)
    inventory.upsert_item(
        item_code="MAT-01",
        name="Synthetic material",
        organization_code="SYN",
        uom_code="KG",
        inventory_account_code="1400",
    )
    inventory.upsert_warehouse(
        warehouse_code="MAIN",
        name="Main warehouse",
        organization_code="SYN",
        entity_code="EG01",
    )
    inventory.upsert_location(
        warehouse_code="MAIN",
        location_code="STOCK",
        name="Stock",
        organization_code="SYN",
    )
    receipt = inventory.create_movement(
        movement_number="RCV/2026/001",
        movement_type="Receipt",
        organization_code="SYN",
        entity_code="EG01",
        period_id=str(period["id"]),
        movement_date="2026-07-05",
        description="Synthetic opening stock",
        lines=[{"item_code": "MAT-01", "quantity": "10.125", "to_location": "MAIN/STOCK"}],
    )
    inventory.post_movement(str(receipt["id"]), reason="Reviewed synthetic receipt")
    return inventory, InventoryPlanningService(connection), str(period["id"])


def _create_count(
    planning: InventoryPlanningService,
    period_id: str,
    *,
    number: str = "COUNT/2026/001",
    actor: str = "local-cli",
) -> dict[str, object]:
    return planning.create_count_session(
        count_number=number,
        organization_code="SYN",
        entity_code="EG01",
        period_id=period_id,
        warehouse_code="MAIN",
        location_code="STOCK",
        count_date="2026-07-20",
        description="Synthetic cycle count",
        actor_label=actor,
    )


def _complete_count(
    planning: InventoryPlanningService,
    period_id: str,
    *,
    quantity: str = "9.875",
    number: str = "COUNT/2026/001",
    preparer: str = "local-cli",
    reviewer: str = "independent-reviewer",
) -> dict[str, object]:
    created = _create_count(planning, period_id, number=number, actor=preparer)
    started = planning.start_count_session(str(created["id"]), actor_label=preparer)
    line_id = str(started["lines"][0]["id"])
    planning.record_counted_quantity(
        str(created["id"]),
        line_id,
        counted_quantity=quantity,
        note="Synthetic physical observation",
        actor_label=preparer,
    )
    planning.submit_count_session(
        str(created["id"]),
        reason="Count completed and evidence retained locally",
        actor_label=preparer,
    )
    return planning.approve_count_session(
        str(created["id"]),
        reason="Independent variance review",
        actor_label=reviewer,
    )


def _token(client: TestClient, username: str) -> str:
    response = client.post("/api/v1/auth/login", json={"username": username, "password": "Secret-123"})
    assert response.status_code == 200
    return str(response.json()["access_token"])


def test_count_lifecycle_is_exact_audited_and_prepares_only_a_draft_adjustment(tmp_path: Path) -> None:
    path = _database(tmp_path)
    connection = connect(path, require_exists=True)
    try:
        inventory, planning, period_id = _seed(connection)
        approved = _complete_count(planning, period_id)
        adjustment = inventory.get_movement(str(approved["adjustment_movement_id"]))

        assert approved["status"] == "Approved"
        assert approved["summary"] == {"lines": 1, "counted_lines": 1, "variance_lines": 1}
        assert approved["lines"][0]["expected_quantity"] == "10.125"
        assert approved["lines"][0]["counted_quantity"] == "9.875"
        assert approved["lines"][0]["variance_quantity"] == "-0.250"
        assert adjustment["movement_type"] == "Adjustment"
        assert adjustment["status"] == "Draft"
        assert adjustment["source_type"] == "Generated"
        assert adjustment["lines"][0]["quantity"] == "0.250"
        assert adjustment["lines"][0]["from_location"] == "MAIN/STOCK"
        assert planning.summary().to_dict() == {
            "workspace": "default",
            "count_sessions": 1,
            "counting_sessions": 0,
            "submitted_sessions": 0,
            "approved_sessions": 1,
            "reorder_rules": 0,
            "active_reorder_rules": 0,
        }
        _assert_contract("inventory_count_session.schema.json", approved)
        _assert_contract("inventory_planning_snapshot.schema.json", planning.snapshot())
        with pytest.raises(sqlite3.DatabaseError, match="immutable"):
            connection.execute(
                "UPDATE inventory_count_lines SET expected_quantity_scaled = 0 WHERE id = ?",
                (approved["lines"][0]["id"],),
            )
        connection.rollback()
        with pytest.raises(sqlite3.DatabaseError, match="invalid inventory count status transition"):
            connection.execute(
                "UPDATE inventory_count_sessions SET status = 'Draft' WHERE id = ?",
                (approved["id"],),
            )
        connection.rollback()
        with pytest.raises(sqlite3.DatabaseError, match="created as Draft"):
            connection.execute(
                """
                INSERT INTO inventory_count_sessions (
                    id, workspace_id, organization_id, legal_entity_id, period_id,
                    location_id, count_number, count_date, description, status,
                    created_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'Approved', ?, ?, ?)
                """,
                (
                    "ICNT-direct-invalid",
                    approved["workspace_id"],
                    approved["organization_id"],
                    approved["legal_entity_id"],
                    approved["period_id"],
                    approved["location_id"],
                    "COUNT/DIRECT/INVALID",
                    approved["count_date"],
                    "Invalid direct final state",
                    "direct-sql",
                    approved["created_at"],
                    approved["updated_at"],
                ),
            )
        connection.rollback()

        actions = {event.action for event in list_audit_events(connection)}
        assert {
            "inventory_count_created",
            "inventory_count_started",
            "inventory_count_quantity_recorded",
            "inventory_count_submitted",
            "inventory_count_approved",
            "inventory_count_adjustment_draft_created",
        } <= actions
        assert verify_audit_events(connection).ok is True
    finally:
        connection.close()


def test_planning_audit_and_outbox_failures_roll_back_business_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _database(tmp_path, "planning_atomic.db")
    connection = connect(path, require_exists=True)
    try:
        _inventory, planning, period_id = _seed(connection)
        audit_count = connection.execute("SELECT COUNT(*) AS count FROM audit_events").fetchone()["count"]
        outbox_count = connection.execute("SELECT COUNT(*) AS count FROM outbox_events").fetchone()["count"]

        def fail_audit(*_args: object, **_kwargs: object) -> None:
            raise PlatformError("forced audit failure")

        monkeypatch.setattr(planning_module, "commit_audited", fail_audit)
        with pytest.raises(PlatformError, match="forced audit failure"):
            _create_count(planning, period_id, number="COUNT/ATOMIC-AUDIT")
        assert (
            connection.execute(
                "SELECT COUNT(*) AS count FROM inventory_count_sessions WHERE count_number = 'COUNT/ATOMIC-AUDIT'",
            ).fetchone()["count"]
            == 0
        )
        assert connection.execute("SELECT COUNT(*) AS count FROM audit_events").fetchone()["count"] == audit_count
        assert connection.execute("SELECT COUNT(*) AS count FROM outbox_events").fetchone()["count"] == outbox_count

        def fail_outbox(*_args: object, **_kwargs: object) -> None:
            raise PlatformError("forced outbox failure")

        monkeypatch.setattr(planning_module, "commit_audited", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(planning_module, "append_outbox_event", fail_outbox)
        with pytest.raises(PlatformError, match="forced outbox failure"):
            _create_count(planning, period_id, number="COUNT/ATOMIC-OUTBOX")
        assert (
            connection.execute(
                "SELECT COUNT(*) AS count FROM inventory_count_sessions WHERE count_number = 'COUNT/ATOMIC-OUTBOX'",
            ).fetchone()["count"]
            == 0
        )
    finally:
        connection.close()


def test_count_rejects_incomplete_results_precision_and_balance_drift(tmp_path: Path) -> None:
    path = _database(tmp_path)
    connection = connect(path, require_exists=True)
    try:
        inventory, planning, period_id = _seed(connection)
        created = _create_count(planning, period_id)
        started = planning.start_count_session(str(created["id"]))
        line_id = str(started["lines"][0]["id"])
        with pytest.raises(PlatformError, match="Every inventory count line"):
            planning.submit_count_session(str(created["id"]), reason="Incomplete count")
        with pytest.raises(PlatformError, match="3-decimal precision"):
            planning.record_counted_quantity(str(created["id"]), line_id, counted_quantity="10.0001")
        with pytest.raises(PlatformError, match="exact decimal string"):
            planning.record_counted_quantity(str(created["id"]), line_id, counted_quantity=10.0)
        planning.record_counted_quantity(str(created["id"]), line_id, counted_quantity="10.000")
        planning.submit_count_session(str(created["id"]), reason="Completed count")

        receipt = inventory.create_movement(
            movement_number="RCV/2026/DRIFT",
            movement_type="Receipt",
            organization_code="SYN",
            entity_code="EG01",
            period_id=period_id,
            movement_date="2026-07-21",
            description="Synthetic movement after snapshot",
            lines=[{"item_code": "MAT-01", "quantity": "0.125", "to_location": "MAIN/STOCK"}],
        )
        inventory.post_movement(str(receipt["id"]), reason="Reviewed movement after count snapshot")
        with pytest.raises(PlatformError, match="changed after this count started"):
            planning.approve_count_session(
                str(created["id"]),
                reason="Must use a current snapshot",
                actor_label="independent-reviewer",
            )
        assert planning.get_count_session(str(created["id"]))["status"] == "Submitted"
        assert (
            connection.execute(
                "SELECT COUNT(*) AS count FROM inventory_movements WHERE source_reference = ?",
                (created["id"],),
            ).fetchone()["count"]
            == 0
        )
    finally:
        connection.close()


def test_count_rbac_and_segregation_of_duties_are_enforced(tmp_path: Path) -> None:
    path = _database(tmp_path)
    connection = connect(path, require_exists=True)
    try:
        _inventory, planning, period_id = _seed(connection)
        auth = LocalAuthService(connection)
        auth.init_admin(username="admin", password="Secret-123")
        auth.create_user(username="controller", password="Secret-123", role="controller")
        auth.create_user(username="preparer", password="Secret-123", role="preparer")
        auth.create_user(username="reviewer", password="Secret-123", role="reviewer")
        auth.create_user(username="auditor", password="Secret-123", role="auditor-readonly")

        approved = _complete_count(
            planning,
            period_id,
            preparer="preparer",
            reviewer="reviewer",
        )
        assert approved["approved_by"] == "reviewer"
        own = _create_count(planning, period_id, number="COUNT/2026/002", actor="controller")
        own_started = planning.start_count_session(str(own["id"]), actor_label="controller")
        planning.record_counted_quantity(
            str(own["id"]),
            str(own_started["lines"][0]["id"]),
            counted_quantity="10.125",
            actor_label="controller",
        )
        planning.submit_count_session(str(own["id"]), reason="Controller submission", actor_label="controller")
        with pytest.raises(PlatformError, match="Segregation of duties"):
            planning.approve_count_session(
                str(own["id"]), reason="Self approval is forbidden", actor_label="controller"
            )
        with pytest.raises(PlatformError, match="Permission denied"):
            _create_count(planning, period_id, number="COUNT/2026/003", actor="auditor")
        with pytest.raises(PlatformError, match="Permission denied"):
            planning.start_count_session(str(own["id"]), actor_label="reviewer")
    finally:
        connection.close()


def test_reorder_signals_are_exact_deterministic_advice_only_and_paginated(tmp_path: Path) -> None:
    path = _database(tmp_path)
    connection = connect(path, require_exists=True)
    try:
        _inventory, planning, _period_id = _seed(connection)
        with pytest.raises(PlatformError, match="exact decimal string"):
            planning.upsert_reorder_rule(
                organization_code="SYN",
                entity_code="EG01",
                item_code="MAT-01",
                warehouse_code="MAIN",
                location_code="STOCK",
                minimum_quantity=10.0,
                target_quantity="20.000",
            )
        with pytest.raises(PlatformError, match="greater than minimum"):
            planning.upsert_reorder_rule(
                organization_code="SYN",
                entity_code="EG01",
                item_code="MAT-01",
                warehouse_code="MAIN",
                location_code="STOCK",
                minimum_quantity="10.125",
                target_quantity="10.125",
            )
        rule = planning.upsert_reorder_rule(
            organization_code="SYN",
            entity_code="EG01",
            item_code="MAT-01",
            warehouse_code="MAIN",
            location_code="STOCK",
            minimum_quantity="10.125",
            target_quantity="20.000",
            lead_time_days=7,
        )
        first = planning.reorder_signals(organization_code="SYN", entity_code="EG01", limit=1, offset=0)
        second = planning.reorder_signals(organization_code="SYN", entity_code="EG01", limit=1, offset=0)

        assert rule["minimum_quantity"] == "10.125"
        assert rule["on_hand_quantity"] == "10.125"
        assert first["source"] == {
            "kind": "local-inventory-reorder-controls",
            "local_first": True,
            "external_calls": False,
        }
        assert first["summary"] == {"total": 1, "high": 0, "medium": 1}
        assert first["pagination"] == {"limit": 1, "offset": 0, "returned": 1}
        assert first["signals"][0]["suggested_quantity"] == "9.875"
        assert first["signals"][0]["signal_id"] == second["signals"][0]["signal_id"]
        _assert_contract("inventory_reorder_signals.schema.json", first)
        assert connection.execute("SELECT COUNT(*) AS count FROM inventory_movements").fetchone()["count"] == 1

        empty = planning.reorder_signals(
            workspace="missing",
            organization_code="SYN",
            entity_code="EG01",
            limit=7,
            offset=3,
        )
        assert empty["pagination"] == {"limit": 7, "offset": 3, "returned": 0}
    finally:
        connection.close()


def test_inventory_planning_api_is_strict_authenticated_and_rbac_protected(tmp_path: Path) -> None:
    path = _database(tmp_path)
    connection = connect(path, require_exists=True)
    try:
        _inventory, _planning, period_id = _seed(connection)
        auth = LocalAuthService(connection)
        auth.init_admin(username="admin", password="Secret-123")
        auth.create_user(username="controller", password="Secret-123", role="controller")
        auth.create_user(username="reviewer", password="Secret-123", role="reviewer")
        auth.create_user(username="auditor", password="Secret-123", role="auditor-readonly")
    finally:
        connection.close()
    client = TestClient(create_api_app(path))
    controller = {"Authorization": f"Bearer {_token(client, 'controller')}"}
    reviewer = {"Authorization": f"Bearer {_token(client, 'reviewer')}"}
    auditor = {"Authorization": f"Bearer {_token(client, 'auditor')}"}
    payload = {
        "count_number": "COUNT/API/001",
        "organization_code": "SYN",
        "entity_code": "EG01",
        "period_id": period_id,
        "warehouse_code": "MAIN",
        "location_code": "STOCK",
        "count_date": "2026-07-20",
    }

    created = client.post("/api/v1/inventory-planning/counts", json=payload, headers=controller)
    assert created.status_code == 200
    session_id = created.json()["count_session"]["id"]
    started = client.post(f"/api/v1/inventory-planning/counts/{session_id}/start", headers=controller)
    assert started.status_code == 200
    line_id = started.json()["count_session"]["lines"][0]["id"]
    recorded = client.post(
        f"/api/v1/inventory-planning/counts/{session_id}/lines/{line_id}",
        json={"counted_quantity": "10.125"},
        headers=controller,
    )
    submitted = client.post(
        f"/api/v1/inventory-planning/counts/{session_id}/submit",
        json={"reason": "API count complete"},
        headers=controller,
    )
    approved = client.post(
        f"/api/v1/inventory-planning/counts/{session_id}/approve",
        json={"reason": "Independent API review"},
        headers=reviewer,
    )
    strict = client.post(
        "/api/v1/inventory-planning/reorder-rules",
        json={
            "organization_code": "SYN",
            "entity_code": "EG01",
            "item_code": "MAT-01",
            "warehouse_code": "MAIN",
            "location_code": "STOCK",
            "minimum_quantity": "10.125",
            "target_quantity": "20.000",
            "unexpected": "rejected",
        },
        headers=controller,
    )
    denied = client.post("/api/v1/inventory-planning/counts", json=payload, headers=auditor)
    listed = client.get("/api/v1/inventory-planning/counts?limit=1&offset=0", headers=auditor)
    bad_page = client.get("/api/v1/inventory-planning/counts?limit=1001", headers=auditor)
    unauthenticated = client.get("/api/v1/inventory-planning/summary")

    assert recorded.status_code == submitted.status_code == approved.status_code == 200
    assert approved.json()["count_session"]["status"] == "Approved"
    assert strict.status_code == 422
    assert denied.status_code == 403
    assert listed.status_code == 200
    assert listed.json()["pagination"] == {"limit": 1, "offset": 0, "returned": 1}
    assert bad_page.status_code == 422
    assert unauthenticated.status_code == 401
    combined = strict.text + denied.text + bad_page.text + unauthenticated.text
    assert "Traceback" not in combined
    assert str(path) not in combined


def test_inventory_planning_cli_migration_backup_restore_and_export(tmp_path: Path) -> None:
    legacy_path = tmp_path / "legacy-v9.db"
    assert run_migrations(legacy_path, target_version=9).current_version == 9
    upgraded = run_migrations(legacy_path)
    assert upgraded.applied_versions == list(range(10, migration_module.MIGRATIONS[-1].version + 1))

    path = _database(tmp_path, "source.db")
    connection = connect(path, require_exists=True)
    try:
        _inventory, planning, period_id = _seed(connection)
        approved = _complete_count(planning, period_id)
        planning.upsert_reorder_rule(
            organization_code="SYN",
            entity_code="EG01",
            item_code="MAT-01",
            warehouse_code="MAIN",
            location_code="STOCK",
            minimum_quantity="10.125",
            target_quantity="20.000",
        )
    finally:
        connection.close()

    summary = runner.invoke(
        app,
        ["inventory", "planning", "summary", "--db", str(path)],
    )
    shown = runner.invoke(
        app,
        [
            "inventory",
            "planning",
            "count-show",
            "--session-id",
            str(approved["id"]),
            "--db",
            str(path),
        ],
    )
    bad = runner.invoke(
        app,
        ["inventory", "planning", "count-show", "--session-id", "missing", "--db", str(path)],
    )
    assert summary.exit_code == shown.exit_code == 0
    assert json.loads(summary.output)["summary"]["approved_sessions"] == 1
    assert json.loads(shown.output)["count_session"]["status"] == "Approved"
    assert bad.exit_code == 1
    assert "Traceback" not in bad.output

    backup = create_backup(path, tmp_path / "backup")
    restored_path = tmp_path / "restored.db"
    restore_backup(restored_path, backup.backup_path)
    restored_connection = connect(restored_path, require_exists=True)
    try:
        restored = InventoryPlanningService(restored_connection)
        restored_count = restored.get_count_session(str(approved["id"]))
        assert restored_count["status"] == "Approved"
        assert restored_count["adjustment_movement_id"] == approved["adjustment_movement_id"]
        assert restored.list_reorder_rules()[0]["minimum_quantity"] == "10.125"
        assert restored_connection.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        restored_connection.close()

    exported = export_database(path, tmp_path / "export")
    inventory_payload = json.loads((exported.output_dir / "inventory.json").read_text(encoding="utf-8"))
    assert inventory_payload["count_sessions"][0]["status"] == "Approved"
    assert inventory_payload["count_lines"][0]["counted_quantity_scaled"] == 9875
    assert inventory_payload["reorder_rules"][0]["target_quantity_scaled"] == 20000


def test_inventory_planning_repository_errors_are_safely_redacted(tmp_path: Path) -> None:
    path = _database(tmp_path)
    connection = connect(path, require_exists=True)
    try:
        _inventory, _planning, _period_id = _seed(connection)

        class FailingRepository(SQLiteInventoryPlanningRepository):
            def summary_counts(self, workspace_id: str) -> dict[str, int]:
                raise sqlite3.OperationalError("secret schema and local path")

        service = InventoryPlanningService(connection, repository=FailingRepository(connection))
        with pytest.raises(PlatformError) as failure:
            service.summary()
        assert str(failure.value) == "Unable to summarize local inventory planning records."
        assert "secret" not in str(failure.value)
    finally:
        connection.close()
