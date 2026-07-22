from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from reconforge.api import create_api_app
from reconforge.audit import list_audit_events, verify_audit_events
from reconforge.auth import LocalAuthService
from reconforge.cli import app
from reconforge.db import connect, run_migrations
from reconforge.db.backup import create_backup, restore_backup
from reconforge.db.exporter import export_database
from reconforge.platform import PlatformError
from reconforge.platform.common import ensure_workspace
from reconforge.platform.finance_core import FinanceCoreService
from reconforge.platform.inventory_core import InventoryCoreService
from reconforge.platform.master_data import MasterDataService

runner = CliRunner()


def _database(tmp_path: Path, name: str = "inventory.db") -> Path:
    path = tmp_path / name
    run_migrations(path)
    return path


def _seed_references(connection: sqlite3.Connection) -> dict[str, object]:
    master = MasterDataService(connection)
    master.upsert_organization(organization_code="SYN", name="Synthetic Group")
    master.upsert_legal_entity(
        organization_code="SYN",
        entity_code="EG01",
        name="Synthetic Egypt",
        currency_code="EGP",
    )
    return master.upsert_period(name="2026-07", start_date="2026-07-01", end_date="2026-07-31")


def _seed_inventory(connection: sqlite3.Connection) -> tuple[InventoryCoreService, dict[str, object]]:
    period = _seed_references(connection)
    finance = FinanceCoreService(connection)
    finance.upsert_account(
        account_code="1400",
        name="Inventory control",
        account_type="Asset",
        normal_balance="Debit",
    )
    inventory = InventoryCoreService(connection)
    inventory.upsert_uom(
        uom_code="KG",
        name="Kilogram",
        category="Weight",
        decimal_places=3,
    )
    inventory.upsert_item(
        item_code="MAT-01",
        name="Synthetic material",
        organization_code="SYN",
        uom_code="KG",
        inventory_account_code="1400",
    )
    inventory.upsert_item(
        item_code="SER-01",
        name="Synthetic serialized item",
        organization_code="SYN",
        tracking_mode="Serial",
        inventory_account_code="1400",
    )
    inventory.upsert_lot(
        item_code="SER-01",
        lot_serial_code="SN-001",
        organization_code="SYN",
    )
    inventory.upsert_warehouse(
        warehouse_code="MAIN",
        name="Main warehouse",
        organization_code="SYN",
        entity_code="EG01",
    )
    inventory.upsert_location(
        warehouse_code="MAIN",
        location_code="RECV",
        name="Receiving",
        organization_code="SYN",
    )
    inventory.upsert_location(
        warehouse_code="MAIN",
        location_code="STOCK",
        name="Stock",
        organization_code="SYN",
    )
    return inventory, period


def _receipt_lines() -> list[dict[str, object]]:
    return [
        {"item_code": "MAT-01", "quantity": "10.125", "to_location": "MAIN/RECV"},
        {
            "item_code": "SER-01",
            "quantity": "1",
            "to_location": "MAIN/RECV",
            "lot_serial_code": "SN-001",
        },
    ]


def _create_movement(
    inventory: InventoryCoreService,
    period: dict[str, object],
    *,
    number: str,
    movement_type: str,
    lines: list[dict[str, object]],
    actor: str = "local-cli",
) -> dict[str, object]:
    return inventory.create_movement(
        movement_number=number,
        movement_type=movement_type,
        organization_code="SYN",
        entity_code="EG01",
        period_id=str(period["id"]),
        movement_date="2026-07-05",
        description="Synthetic inventory movement",
        source_reference="SYN-SOURCE-001",
        lines=lines,
        actor_label=actor,
    )


def _token(client: TestClient, username: str) -> str:
    response = client.post("/api/v1/auth/login", json={"username": username, "password": "Secret-123"})
    assert response.status_code == 200
    return str(response.json()["access_token"])


def test_inventory_lifecycle_exact_on_hand_void_and_immutability(tmp_path: Path) -> None:
    path = _database(tmp_path)
    connection = connect(path, require_exists=True)
    try:
        inventory, period = _seed_inventory(connection)
        receipt = _create_movement(
            inventory,
            period,
            number="RCV/2026/001",
            movement_type="Receipt",
            lines=_receipt_lines(),
        )
        posted_receipt = inventory.post_movement(str(receipt["id"]), reason="Independent receipt review")
        transfer = _create_movement(
            inventory,
            period,
            number="TRF/2026/001",
            movement_type="Transfer",
            lines=[
                {
                    "item_code": "MAT-01",
                    "quantity": "4.125",
                    "from_location": "MAIN/RECV",
                    "to_location": "MAIN/STOCK",
                }
            ],
        )
        posted_transfer = inventory.post_movement(str(transfer["id"]), reason="Independent transfer review")
        balances = inventory.on_hand(organization_code="SYN", entity_code="EG01")
        by_key = {(row["item_code"], row["location_code"]): row["quantity"] for row in balances["balances"]}

        assert receipt["status"] == "Draft"
        assert posted_receipt["status"] == posted_transfer["status"] == "Posted"
        assert by_key == {
            ("MAT-01", "RECV"): "6.000",
            ("MAT-01", "STOCK"): "4.125",
            ("SER-01", "RECV"): "1",
        }
        assert balances["source"] == {
            "kind": "local-inventory-ledger",
            "local_first": True,
            "external_calls": False,
        }

        line_id = str(posted_transfer["lines"][0]["id"])
        with pytest.raises(sqlite3.DatabaseError, match="immutable"):
            connection.execute("UPDATE inventory_movement_lines SET quantity_scaled = 1 WHERE id = ?", (line_id,))
        connection.rollback()
        with pytest.raises(sqlite3.DatabaseError, match="headers are immutable"):
            connection.execute(
                "UPDATE inventory_movements SET description = 'Changed' WHERE id = ?",
                (posted_transfer["id"],),
            )
        connection.rollback()

        with pytest.raises(PlatformError, match="negative stock"):
            inventory.void_movement(str(receipt["id"]), reason="Would invalidate downstream transfer")
        assert inventory.void_movement(str(transfer["id"]), reason="Transfer cancelled")["status"] == "Voided"
        assert inventory.void_movement(str(receipt["id"]), reason="Receipt cancelled")["status"] == "Voided"
        assert inventory.on_hand(organization_code="SYN", entity_code="EG01")["balances"] == []

        summary = inventory.summary().to_dict()
        assert summary == {
            "workspace": "default",
            "units_of_measure": 2,
            "items": 2,
            "warehouses": 1,
            "locations": 2,
            "lots_and_serials": 1,
            "draft_movements": 0,
            "posted_movements": 0,
            "voided_movements": 2,
        }
        actions = {event.action for event in list_audit_events(connection)}
        assert {
            "unit_of_measure_upserted",
            "inventory_item_upserted",
            "inventory_lot_upserted",
            "warehouse_upserted",
            "inventory_location_upserted",
            "inventory_movement_draft_saved",
            "inventory_movement_posted",
            "inventory_movement_voided",
        } <= actions
        assert verify_audit_events(connection).ok is True
    finally:
        connection.close()


def test_inventory_rejects_precision_direction_negative_serial_and_cycles(tmp_path: Path) -> None:
    path = _database(tmp_path)
    connection = connect(path, require_exists=True)
    try:
        inventory, period = _seed_inventory(connection)
        with pytest.raises(PlatformError, match="3-decimal precision"):
            _create_movement(
                inventory,
                period,
                number="RCV/BAD/PRECISION",
                movement_type="Receipt",
                lines=[{"item_code": "MAT-01", "quantity": "1.0001", "to_location": "MAIN/RECV"}],
            )
        with pytest.raises(PlatformError, match="exact decimal string"):
            _create_movement(
                inventory,
                period,
                number="RCV/BAD/FLOAT",
                movement_type="Receipt",
                lines=[{"item_code": "MAT-01", "quantity": 1.5, "to_location": "MAIN/RECV"}],
            )
        with pytest.raises(PlatformError, match="valid positive decimal"):
            _create_movement(
                inventory,
                period,
                number="RCV/BAD/EXPONENT",
                movement_type="Receipt",
                lines=[{"item_code": "MAT-01", "quantity": "1e1000000", "to_location": "MAIN/RECV"}],
            )
        with pytest.raises(PlatformError, match="Receipt lines"):
            _create_movement(
                inventory,
                period,
                number="RCV/BAD/DIRECTION",
                movement_type="Receipt",
                lines=[{"item_code": "MAT-01", "quantity": "1", "from_location": "MAIN/RECV"}],
            )
        with pytest.raises(PlatformError, match="exactly one unit"):
            _create_movement(
                inventory,
                period,
                number="RCV/BAD/SERIAL",
                movement_type="Receipt",
                lines=[
                    {
                        "item_code": "SER-01",
                        "quantity": "2",
                        "to_location": "MAIN/RECV",
                        "lot_serial_code": "SN-001",
                    }
                ],
            )

        delivery = _create_movement(
            inventory,
            period,
            number="DLV/BAD/NEGATIVE",
            movement_type="Delivery",
            lines=[{"item_code": "MAT-01", "quantity": "1", "from_location": "MAIN/STOCK"}],
        )
        with pytest.raises(PlatformError, match="negative stock"):
            inventory.post_movement(str(delivery["id"]), reason="Must fail")

        receipt = _create_movement(
            inventory,
            period,
            number="RCV/SERIAL/001",
            movement_type="Receipt",
            lines=[_receipt_lines()[1]],
        )
        inventory.post_movement(str(receipt["id"]), reason="Initial serial receipt")
        duplicate = _create_movement(
            inventory,
            period,
            number="RCV/SERIAL/002",
            movement_type="Receipt",
            lines=[_receipt_lines()[1]],
        )
        with pytest.raises(PlatformError, match="zero or one"):
            inventory.post_movement(str(duplicate["id"]), reason="Duplicate serial")

        inventory.upsert_location(
            warehouse_code="MAIN",
            location_code="ZONE",
            name="Zone",
            organization_code="SYN",
        )
        inventory.upsert_location(
            warehouse_code="MAIN",
            location_code="BIN",
            name="Bin",
            organization_code="SYN",
            parent_location_code="ZONE",
        )
        with pytest.raises(PlatformError, match="acyclic"):
            inventory.upsert_location(
                warehouse_code="MAIN",
                location_code="ZONE",
                name="Zone",
                organization_code="SYN",
                parent_location_code="BIN",
            )

        direct = _create_movement(
            inventory,
            period,
            number="RCV/DIRECT/001",
            movement_type="Receipt",
            lines=[{"item_code": "MAT-01", "quantity": "1", "to_location": "MAIN/RECV"}],
        )
        with pytest.raises(sqlite3.DatabaseError, match="review metadata"):
            connection.execute("UPDATE inventory_movements SET status = 'Posted' WHERE id = ?", (direct["id"],))
        connection.rollback()
    finally:
        connection.close()


def test_inventory_control_exceptions_are_deterministic_and_explainable(tmp_path: Path) -> None:
    path = _database(tmp_path)
    connection = connect(path, require_exists=True)
    try:
        inventory, period = _seed_inventory(connection)
        inventory.upsert_item(
            item_code="LOT-01",
            name="Lot-tracked stock without account",
            organization_code="SYN",
            tracking_mode="Lot",
        )
        inventory.upsert_lot(
            item_code="LOT-01",
            lot_serial_code="LOT-OLD",
            organization_code="SYN",
            manufactured_on="2025-01-01",
            expires_on="2026-06-30",
        )
        inventory.upsert_location(
            warehouse_code="MAIN",
            location_code="ALLOWNEG",
            name="Controlled negative location",
            organization_code="SYN",
            allow_negative=True,
        )
        receipt = _create_movement(
            inventory,
            period,
            number="RCV/LOT/001",
            movement_type="Receipt",
            lines=[
                {
                    "item_code": "LOT-01",
                    "quantity": "3",
                    "to_location": "MAIN/RECV",
                    "lot_serial_code": "LOT-OLD",
                }
            ],
        )
        inventory.post_movement(str(receipt["id"]), reason="Receive expiring synthetic lot")
        delivery = _create_movement(
            inventory,
            period,
            number="DLV/NEG/001",
            movement_type="Delivery",
            lines=[{"item_code": "MAT-01", "quantity": "2", "from_location": "MAIN/ALLOWNEG"}],
        )
        inventory.post_movement(str(delivery["id"]), reason="Allowed negative control scenario")

        first = inventory.control_exceptions(organization_code="SYN", entity_code="EG01", as_of="2026-07-31")
        second = inventory.control_exceptions(organization_code="SYN", entity_code="EG01", as_of="2026-07-31")
        codes = {row["control_code"] for row in first["exceptions"]}

        assert first["summary"] == {"total": 3, "high": 2, "medium": 1}
        assert codes == {"INV-NEGATIVE-STOCK", "INV-EXPIRED-STOCK", "INV-MISSING-ACCOUNT"}
        assert [row["exception_id"] for row in first["exceptions"]] == [
            row["exception_id"] for row in second["exceptions"]
        ]
        assert "source_path" not in json.dumps(first)
    finally:
        connection.close()


def test_inventory_control_database_errors_are_safely_redacted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = _database(tmp_path)
    connection = connect(path, require_exists=True)
    try:
        inventory, _period = _seed_inventory(connection)

        class ExpiryReadFailure:
            def execute(self, statement: str, parameters: tuple[object, ...] = ()) -> sqlite3.Cursor:
                if "SELECT expires_on FROM inventory_lots" in statement:
                    raise sqlite3.OperationalError("sensitive inventory schema details")
                return connection.execute(statement, parameters)

        monkeypatch.setattr(
            inventory,
            "on_hand",
            lambda **_kwargs: {
                "balances": [
                    {
                        "quantity_scaled": 1,
                        "warehouse_code": "MAIN",
                        "location_code": "RECV",
                        "item_code": "SER-01",
                        "lot_serial_code": "SN-001",
                        "quantity": "1",
                        "inventory_lot_id": "LOT-sensitive",
                        "location_id": "LOC-sensitive",
                    }
                ]
            },
        )
        inventory.connection = ExpiryReadFailure()  # type: ignore[assignment]

        with pytest.raises(PlatformError) as caught:
            inventory.control_exceptions(
                organization_code="SYN",
                entity_code="EG01",
                as_of="2026-07-31",
            )

        assert str(caught.value) == "Unable to evaluate local inventory controls."
        assert "sensitive inventory schema details" not in str(caught.value)
    finally:
        connection.close()


def test_inventory_seeded_rbac_and_sod(tmp_path: Path) -> None:
    path = _database(tmp_path)
    connection = connect(path, require_exists=True)
    try:
        inventory, period = _seed_inventory(connection)
        auth = LocalAuthService(connection)
        auth.init_admin(username="admin", password="Secret-123")
        auth.create_user(username="controller", password="Secret-123", role="controller")
        auth.create_user(username="preparer", password="Secret-123", role="preparer")
        auth.create_user(username="reviewer", password="Secret-123", role="reviewer")
        auth.create_user(username="auditor", password="Secret-123", role="auditor-readonly")

        movement = _create_movement(
            inventory,
            period,
            number="RCV/SOD/001",
            movement_type="Receipt",
            lines=[{"item_code": "MAT-01", "quantity": "1", "to_location": "MAIN/RECV"}],
            actor="controller",
        )
        with pytest.raises(PlatformError, match="Segregation of duties"):
            inventory.post_movement(str(movement["id"]), reason="Self posting", actor_label="controller")
        posted = inventory.post_movement(str(movement["id"]), reason="Independent posting", actor_label="reviewer")
        assert posted["posted_by"] == "reviewer"
        assert inventory.list_movements(actor_label="auditor")[0]["status"] == "Posted"
        with pytest.raises(PlatformError, match="Permission denied"):
            inventory.upsert_item(
                item_code="DENIED",
                name="Denied",
                organization_code="SYN",
                actor_label="reviewer",
            )
        with pytest.raises(PlatformError, match="Permission denied"):
            inventory.post_movement(str(movement["id"]), reason="Denied", actor_label="preparer")
    finally:
        connection.close()


def test_inventory_api_is_strict_paginated_rbac_and_sod_protected(tmp_path: Path) -> None:
    path = _database(tmp_path, "inventory_api.db")
    connection = connect(path, require_exists=True)
    try:
        _seed_references(connection)
        master_period = connection.execute("SELECT id FROM periods WHERE name = '2026-07'").fetchone()
        assert master_period is not None
        period_id = str(master_period["id"])
        auth = LocalAuthService(connection)
        auth.init_admin(username="admin", password="Secret-123")
        auth.create_user(username="controller", password="Secret-123", role="controller")
        auth.create_user(username="reviewer", password="Secret-123", role="reviewer")
    finally:
        connection.close()
    client = TestClient(create_api_app(path))
    controller = {"Authorization": f"Bearer {_token(client, 'controller')}"}
    reviewer = {"Authorization": f"Bearer {_token(client, 'reviewer')}"}

    item = client.post(
        "/api/v1/inventory/items",
        headers=controller,
        json={"item_code": "MAT-01", "name": "Synthetic material", "organization_code": "SYN"},
    )
    warehouse = client.post(
        "/api/v1/inventory/warehouses",
        headers=controller,
        json={
            "warehouse_code": "MAIN",
            "name": "Main warehouse",
            "organization_code": "SYN",
            "entity_code": "EG01",
        },
    )
    location = client.post(
        "/api/v1/inventory/locations",
        headers=controller,
        json={
            "warehouse_code": "MAIN",
            "location_code": "STOCK",
            "name": "Stock",
            "organization_code": "SYN",
        },
    )
    created = client.post(
        "/api/v1/inventory/movements",
        headers=controller,
        json={
            "movement_number": "RCV/API/001",
            "movement_type": "Receipt",
            "organization_code": "SYN",
            "entity_code": "EG01",
            "period_id": period_id,
            "movement_date": "2026-07-05",
            "description": "Synthetic API receipt",
            "lines": [{"item_code": "MAT-01", "quantity": "2", "to_location": "MAIN/STOCK"}],
        },
    )
    assert item.status_code == warehouse.status_code == location.status_code == created.status_code == 200
    movement_id = str(created.json()["movement"]["id"])
    own_post = client.post(
        f"/api/v1/inventory/movements/{movement_id}/post",
        headers=controller,
        json={"reason": "Self post"},
    )
    posted = client.post(
        f"/api/v1/inventory/movements/{movement_id}/post",
        headers=reviewer,
        json={"reason": "Independent API post"},
    )
    balances = client.get(
        "/api/v1/inventory/on-hand",
        headers=reviewer,
        params={"organization": "SYN", "entity": "EG01", "limit": 1},
    )
    listed = client.get("/api/v1/inventory/items?limit=1", headers=reviewer)
    denied = client.post(
        "/api/v1/inventory/items",
        headers=reviewer,
        json={"item_code": "DENIED", "name": "Denied", "organization_code": "SYN"},
    )
    strict = client.post(
        "/api/v1/inventory/items",
        headers=controller,
        json={"item_code": "STRICT", "name": "Strict", "unexpected": True},
    )
    bad_page = client.get("/api/v1/inventory/items?limit=1001", headers=reviewer)
    unauthenticated = client.get("/api/v1/inventory/summary")

    assert own_post.status_code == 400
    assert posted.status_code == 200
    assert posted.json()["movement"]["status"] == "Posted"
    assert balances.status_code == 200
    assert balances.json()["balances"][0]["quantity"] == "2"
    assert listed.json()["pagination"] == {"limit": 1, "offset": 0, "returned": 1}
    assert denied.status_code == 403
    assert strict.status_code == 422
    assert bad_page.status_code == 422
    assert unauthenticated.status_code == 401
    combined = own_post.text + denied.text + strict.text + bad_page.text + unauthenticated.text
    assert "Traceback" not in combined
    assert "sqlite" not in combined.lower()


def test_inventory_cli_workflow_and_safe_json_failure(tmp_path: Path) -> None:
    path = tmp_path / "inventory_cli.db"
    lines_path = tmp_path / "inventory-lines.json"
    lines_path.write_text(
        json.dumps({"lines": [{"item_code": "MAT-01", "quantity": "2.500", "to_location": "MAIN/STOCK"}]}),
        encoding="utf-8",
    )
    invalid_path = tmp_path / "invalid-lines.json"
    invalid_path.write_text(
        json.dumps({"lines": [{"item_code": "MAT-01", "quantity": "1", "secret": "bad"}]}),
        encoding="utf-8",
    )
    commands = [
        ["db", "init", "--db", str(path)],
        ["master-data", "organization-upsert", "--code", "SYN", "--name", "Synthetic Group", "--db", str(path)],
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
        [
            "inventory",
            "unit-upsert",
            "--code",
            "KG",
            "--name",
            "Kilogram",
            "--category",
            "Weight",
            "--decimals",
            "3",
            "--db",
            str(path),
        ],
        [
            "inventory",
            "item-upsert",
            "--code",
            "MAT-01",
            "--name",
            "Synthetic material",
            "--organization",
            "SYN",
            "--unit",
            "KG",
            "--db",
            str(path),
        ],
        [
            "inventory",
            "warehouse-upsert",
            "--code",
            "MAIN",
            "--name",
            "Main warehouse",
            "--organization",
            "SYN",
            "--entity",
            "EG01",
            "--db",
            str(path),
        ],
        [
            "inventory",
            "location-upsert",
            "--warehouse",
            "MAIN",
            "--code",
            "STOCK",
            "--name",
            "Stock",
            "--organization",
            "SYN",
            "--db",
            str(path),
        ],
    ]
    for command in commands:
        result = runner.invoke(app, command)
        assert result.exit_code == 0, result.output
    connection = connect(path, require_exists=True)
    try:
        period_id = str(connection.execute("SELECT id FROM periods WHERE name = '2026-07'").fetchone()["id"])
    finally:
        connection.close()
    created = runner.invoke(
        app,
        [
            "inventory",
            "movement-create",
            "--number",
            "RCV/CLI/001",
            "--type",
            "Receipt",
            "--organization",
            "SYN",
            "--entity",
            "EG01",
            "--period-id",
            period_id,
            "--date",
            "2026-07-05",
            "--description",
            "Synthetic CLI receipt",
            "--lines",
            str(lines_path),
            "--db",
            str(path),
        ],
    )
    assert created.exit_code == 0, created.output
    connection = connect(path, require_exists=True)
    try:
        movement_id = str(connection.execute("SELECT id FROM inventory_movements").fetchone()["id"])
    finally:
        connection.close()
    posted = runner.invoke(
        app,
        [
            "inventory",
            "movement-post",
            "--movement-id",
            movement_id,
            "--reason",
            "CLI review",
            "--db",
            str(path),
        ],
    )
    on_hand = runner.invoke(
        app,
        ["inventory", "on-hand", "--organization", "SYN", "--entity", "EG01", "--db", str(path)],
    )
    invalid = runner.invoke(
        app,
        [
            "inventory",
            "movement-create",
            "--number",
            "RCV/CLI/BAD",
            "--type",
            "Receipt",
            "--organization",
            "SYN",
            "--entity",
            "EG01",
            "--period-id",
            period_id,
            "--date",
            "2026-07-05",
            "--description",
            "Invalid",
            "--lines",
            str(invalid_path),
            "--db",
            str(path),
        ],
    )
    assert posted.exit_code == 0, posted.output
    assert on_hand.exit_code == 0, on_hand.output
    assert '"quantity": "2.500"' in on_hand.output
    assert invalid.exit_code == 1
    assert "unsupported fields" in invalid.output
    assert "secret" not in invalid.output
    assert "Traceback" not in invalid.output


def test_inventory_v8_upgrade_seeds_default_unit_without_changing_existing_state(tmp_path: Path) -> None:
    path = tmp_path / "version-eight.db"
    run_migrations(path, target_version=8)
    connection = connect(path, require_exists=True)
    try:
        workspace_id = ensure_workspace(connection, "Legacy Inventory Workspace")
        connection.execute(
            """
            INSERT INTO accounts (id, workspace_id, account_code, account_name, created_at, chart_id, updated_at)
            VALUES ('ACC-legacy-inventory', ?, '1400', 'Legacy inventory',
                    '2026-01-01T00:00:00Z', ?, '2026-01-01T00:00:00Z')
            """,
            (workspace_id, f"COA-{workspace_id}"),
        )
        connection.commit()
    finally:
        connection.close()

    upgraded = run_migrations(path)
    assert upgraded.applied_versions == [9, 10, 11, 12]
    connection = connect(path, require_exists=True)
    try:
        unit = connection.execute(
            "SELECT uom_code, decimal_places FROM units_of_measure WHERE workspace_id = ?", (workspace_id,)
        ).fetchone()
        account = connection.execute("SELECT account_name FROM accounts WHERE id = 'ACC-legacy-inventory'").fetchone()
        assert unit is not None
        assert (unit["uom_code"], unit["decimal_places"]) == ("EA", 0)
        assert account is not None and account["account_name"] == "Legacy inventory"
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        connection.close()


def test_inventory_backup_restore_and_public_export_preserve_posted_movement(tmp_path: Path) -> None:
    path = _database(tmp_path, "inventory_source.db")
    connection = connect(path, require_exists=True)
    try:
        inventory, period = _seed_inventory(connection)
        movement = _create_movement(
            inventory,
            period,
            number="RCV/BACKUP/001",
            movement_type="Receipt",
            lines=_receipt_lines(),
        )
        inventory.post_movement(str(movement["id"]), reason="Backup fixture review")
    finally:
        connection.close()

    backup = create_backup(path, tmp_path / "inventory_backup")
    exported = export_database(path, tmp_path / "inventory_export")
    restored_path = tmp_path / "inventory_restored.db"
    restore_backup(restored_path, backup.backup_path)

    assert backup.schema_version == exported.schema_version == 12
    export_payload = json.loads((tmp_path / "inventory_export" / "inventory.json").read_text(encoding="utf-8"))
    assert len(export_payload["items"]) == 2
    assert export_payload["movements"][0]["status"] == "Posted"

    connection = connect(restored_path, require_exists=True)
    try:
        restored = InventoryCoreService(connection)
        restored_movement = restored.get_movement(str(movement["id"]))
        balances = restored.on_hand(organization_code="SYN", entity_code="EG01")
        assert restored_movement["status"] == "Posted"
        assert {row["quantity"] for row in balances["balances"]} == {"10.125", "1"}
        with pytest.raises(sqlite3.DatabaseError, match="immutable"):
            connection.execute(
                "UPDATE inventory_movement_lines SET quantity_scaled = 1 WHERE movement_id = ?",
                (movement["id"],),
            )
        connection.rollback()
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        connection.close()
