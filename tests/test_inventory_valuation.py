from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from typer.testing import CliRunner

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
from reconforge.platform.inventory_valuation import InventoryValuationService
from reconforge.platform.inventory_valuation_repository import SQLiteInventoryValuationRepository
from reconforge.platform.master_data import MasterDataService

runner = CliRunner()
SCHEMA_DIR = Path(__file__).resolve().parents[1] / "docs" / "schemas"


def _assert_contract(filename: str, payload: object) -> None:
    schema = json.loads((SCHEMA_DIR / filename).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(payload)


def test_valuation_amount_contract_supports_zero_to_six_minor_units() -> None:
    schema = json.loads(
        (SCHEMA_DIR / "inventory_valuation_document.schema.json").read_text(encoding="utf-8")
    )
    validator = Draft202012Validator(schema["$defs"]["amount"])

    assert all(validator.is_valid(value) for value in ("1", "1.2", "1.234", "1.234567"))
    assert not validator.is_valid("1.2345678")
    assert not validator.is_valid("-1.00")


def _database(tmp_path: Path, name: str = "valuation.db") -> Path:
    path = tmp_path / name
    run_migrations(path)
    return path


def _seed(
    connection: sqlite3.Connection,
    *,
    with_users: bool = False,
) -> tuple[InventoryCoreService, InventoryValuationService, dict[str, object]]:
    if with_users:
        auth = LocalAuthService(connection)
        auth.init_admin(username="admin", password="Secret-123")
        auth.create_user(username="controller", password="Secret-123", role="controller")
        auth.create_user(username="preparer", password="Secret-123", role="preparer")
        auth.create_user(username="reviewer", password="Secret-123", role="reviewer")
        auth.create_user(username="auditor", password="Secret-123", role="auditor-readonly")
    master = MasterDataService(connection)
    master.upsert_organization(organization_code="SYN", name="Synthetic Group")
    master.upsert_legal_entity(
        organization_code="SYN",
        entity_code="EG01",
        name="Synthetic Egypt",
        currency_code="EGP",
    )
    period = master.upsert_period(
        name="2026-07", start_date="2026-07-01", end_date="2026-07-31"
    )
    finance = FinanceCoreService(connection)
    for account_code, name, account_type, normal_balance in (
        ("1400", "Inventory control", "Asset", "Debit"),
        ("2100", "Receipt clearing", "Liability", "Credit"),
        ("5100", "Cost of goods sold", "Expense", "Debit"),
        ("5190", "Inventory adjustments", "Expense", "Debit"),
    ):
        finance.upsert_account(
            account_code=account_code,
            name=name,
            account_type=account_type,
            normal_balance=normal_balance,
        )
    finance.upsert_journal(
        journal_code="INV",
        name="Inventory valuation",
        organization_code="SYN",
        currency_code="EGP",
        journal_type="Adjustment",
    )
    inventory = InventoryCoreService(connection)
    inventory.upsert_uom(
        uom_code="KG", name="Kilogram", category="Weight", decimal_places=3
    )
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
    valuation = InventoryValuationService(connection)
    valuation.upsert_policy(
        policy_code="FIFO",
        organization_code="SYN",
        entity_code="EG01",
        journal_code="INV",
        receipt_clearing_account_code="2100",
        cogs_account_code="5100",
        adjustment_account_code="5190",
    )
    return inventory, valuation, period


def _movement(
    inventory: InventoryCoreService,
    period: dict[str, object],
    *,
    number: str,
    movement_type: str,
    movement_date: str,
    quantity: str,
) -> dict[str, object]:
    location_key = "to_location" if movement_type == "Receipt" else "from_location"
    movement = inventory.create_movement(
        movement_number=number,
        movement_type=movement_type,
        organization_code="SYN",
        entity_code="EG01",
        period_id=str(period["id"]),
        movement_date=movement_date,
        description=f"Synthetic {movement_type.lower()}",
        lines=[
            {
                "item_code": "MAT-01",
                "quantity": quantity,
                location_key: "MAIN/STOCK",
            }
        ],
    )
    return inventory.post_movement(str(movement["id"]), reason="Independent stock review")


def _valuation_document(
    valuation: InventoryValuationService,
    movement: dict[str, object],
    *,
    number: str,
    total_cost: object | None = None,
    actor: str = "local-cli",
) -> dict[str, object]:
    costs = [] if total_cost is None else [{"line_number": 1, "total_cost": total_cost}]
    return valuation.create_document(
        valuation_number=number,
        movement_id=str(movement["id"]),
        policy_code="FIFO",
        input_costs=costs,
        actor_label=actor,
    )


def _token(client: TestClient, username: str) -> str:
    response = client.post(
        "/api/v1/auth/login", json={"username": username, "password": "Secret-123"}
    )
    assert response.status_code == 200
    return str(response.json()["access_token"])


def test_fifo_lifecycle_finance_draft_contracts_and_immutability(tmp_path: Path) -> None:
    path = _database(tmp_path)
    connection = connect(path, require_exists=True)
    try:
        inventory, valuation, period = _seed(connection)
        receipt = _movement(
            inventory,
            period,
            number="RCV/2026/001",
            movement_type="Receipt",
            movement_date="2026-07-01",
            quantity="10.000",
        )
        receipt_document = _valuation_document(
            valuation, receipt, number="VAL/2026/001", total_cost="100.01"
        )
        approved_receipt = valuation.approve_document(
            str(receipt_document["id"]), reason="Receipt cost evidence reviewed"
        )
        delivery = _movement(
            inventory,
            period,
            number="DLV/2026/001",
            movement_type="Delivery",
            movement_date="2026-07-02",
            quantity="3.000",
        )
        delivery_document = _valuation_document(
            valuation, delivery, number="VAL/2026/002"
        )
        approved_delivery = valuation.approve_document(
            str(delivery_document["id"]), reason="FIFO issue reviewed"
        )

        assert approved_receipt["total_value"] == "100.01"
        assert approved_delivery["total_value"] == "30.00"
        assert approved_delivery["finance_entry_status"] == "Draft"
        assert approved_delivery["layer_consumptions"][0]["quantity"] == "3.000"
        assert approved_delivery["layer_consumptions"][0]["value"] == "30.00"
        layers = valuation.list_cost_layers(open_only=False)
        assert layers[0]["original_quantity"] == "10.000"
        assert layers[0]["remaining_quantity"] == "7.000"
        assert layers[0]["original_value"] == "100.01"
        assert layers[0]["remaining_value"] == "70.01"

        entries = connection.execute(
            """
            SELECT entries.id, entries.status,
                   SUM(lines.debit_minor) AS debit_minor,
                   SUM(lines.credit_minor) AS credit_minor
            FROM ledger_entries entries
            JOIN ledger_lines lines ON lines.entry_id = entries.id
            GROUP BY entries.id, entries.status ORDER BY entries.entry_number
            """
        ).fetchall()
        assert sorted(
            (row["status"], row["debit_minor"], row["credit_minor"]) for row in entries
        ) == [("Draft", 3000, 3000), ("Draft", 10001, 10001)]
        with pytest.raises(PlatformError, match="must be reversed"):
            inventory.void_movement(str(receipt["id"]), reason="Blocked after valuation")
        finance_entry_id = str(approved_delivery["finance_entry_id"])
        finance_line_id = str(
            connection.execute(
                "SELECT id FROM ledger_lines WHERE entry_id = ? ORDER BY line_number LIMIT 1",
                (finance_entry_id,),
            ).fetchone()["id"]
        )
        with pytest.raises(sqlite3.DatabaseError, match="finance lines are immutable"):
            connection.execute(
                "UPDATE ledger_lines SET description = 'Changed' WHERE id = ?", (finance_line_id,)
            )
        connection.rollback()
        finance = FinanceCoreService(connection)
        finance.validate_entry(finance_entry_id, reason="Independent Finance Core review")
        with pytest.raises(PlatformError, match="must be reversed"):
            finance.void_entry(finance_entry_id, reason="Blocked without valuation reversal")
        consumption_id = str(approved_delivery["layer_consumptions"][0]["id"])
        with pytest.raises(sqlite3.DatabaseError, match="immutable"):
            connection.execute(
                "UPDATE inventory_layer_consumptions SET value_minor = 1 WHERE id = ?",
                (consumption_id,),
            )
        connection.rollback()

        assert valuation.summary().to_dict() == {
            "workspace": "default",
            "policies": 1,
            "draft_documents": 0,
            "approved_documents": 2,
            "open_layers": 1,
            "unvalued_posted_movements": 0,
        }
        _assert_contract(
            "inventory_valuation_document.schema.json",
            valuation.get_document(str(delivery_document["id"])),
        )
        _assert_contract("inventory_valuation_snapshot.schema.json", valuation.snapshot())
        actions = {event.action for event in list_audit_events(connection)}
        assert {
            "inventory_valuation_policy_upserted",
            "inventory_valuation_draft_created",
            "inventory_valuation_approved",
        } <= actions
        assert verify_audit_events(connection).ok is True
    finally:
        connection.close()


def test_fifo_sequence_insufficient_layers_and_exact_cost_boundaries(tmp_path: Path) -> None:
    path = _database(tmp_path)
    connection = connect(path, require_exists=True)
    try:
        inventory, valuation, period = _seed(connection)
        first = _movement(
            inventory,
            period,
            number="RCV-A",
            movement_type="Receipt",
            movement_date="2026-07-01",
            quantity="2.000",
        )
        second = _movement(
            inventory,
            period,
            number="RCV-B",
            movement_type="Receipt",
            movement_date="2026-07-02",
            quantity="1.000",
        )
        second_document = _valuation_document(
            valuation, second, number="VAL-B", total_cost="5.00"
        )
        with pytest.raises(PlatformError, match="RCV-A"):
            valuation.approve_document(str(second_document["id"]), reason="Out of sequence")
        with pytest.raises(PlatformError, match="exact decimal string"):
            _valuation_document(valuation, first, number="VAL-FLOAT", total_cost=10.0)
        first_document = _valuation_document(
            valuation, first, number="VAL-A", total_cost="0.01"
        )
        valuation.approve_document(str(first_document["id"]), reason="Opening layer reviewed")
        valuation.approve_document(str(second_document["id"]), reason="Second layer reviewed")
        delivery = _movement(
            inventory,
            period,
            number="DLV-C",
            movement_type="Delivery",
            movement_date="2026-07-03",
            quantity="1.000",
        )
        delivery_document = _valuation_document(valuation, delivery, number="VAL-C")
        with pytest.raises(PlatformError, match="cannot be represented"):
            valuation.approve_document(str(delivery_document["id"]), reason="Tiny partial layer")
        assert valuation.get_document(str(delivery_document["id"]))["status"] == "Draft"
        assert valuation.list_cost_layers(open_only=True)[0]["remaining_value"] == "0.01"
    finally:
        connection.close()


def test_fifo_consumes_oldest_layers_with_deterministic_half_even_allocation(tmp_path: Path) -> None:
    path = _database(tmp_path)
    connection = connect(path, require_exists=True)
    try:
        inventory, valuation, period = _seed(connection)
        first = _movement(
            inventory,
            period,
            number="RCV-OLD",
            movement_type="Receipt",
            movement_date="2026-07-01",
            quantity="2.000",
        )
        first_document = _valuation_document(
            valuation, first, number="VAL-OLD", total_cost="20.01"
        )
        valuation.approve_document(str(first_document["id"]), reason="Old layer reviewed")
        second = _movement(
            inventory,
            period,
            number="RCV-NEW",
            movement_type="Receipt",
            movement_date="2026-07-02",
            quantity="2.000",
        )
        second_document = _valuation_document(
            valuation, second, number="VAL-NEW", total_cost="30.01"
        )
        valuation.approve_document(str(second_document["id"]), reason="New layer reviewed")
        delivery = _movement(
            inventory,
            period,
            number="DLV-FIFO",
            movement_type="Delivery",
            movement_date="2026-07-03",
            quantity="3.000",
        )
        delivery_document = _valuation_document(valuation, delivery, number="VAL-FIFO")
        approved = valuation.approve_document(
            str(delivery_document["id"]), reason="FIFO sequence reviewed"
        )

        assert approved["total_value"] == "35.01"
        assert [record["quantity"] for record in approved["layer_consumptions"]] == [
            "2.000",
            "1.000",
        ]
        assert [record["value"] for record in approved["layer_consumptions"]] == [
            "20.01",
            "15.00",
        ]
        layers = valuation.list_cost_layers(open_only=False)
        by_valuation = {record["valuation_number"]: record for record in layers}
        assert by_valuation["VAL-OLD"]["layer_status"] == "Closed"
        assert by_valuation["VAL-NEW"]["remaining_value"] == "15.01"
    finally:
        connection.close()


def test_known_user_sod_rbac_api_and_cli(tmp_path: Path) -> None:
    path = _database(tmp_path)
    connection = connect(path, require_exists=True)
    try:
        inventory, valuation, period = _seed(connection, with_users=True)
        receipt = _movement(
            inventory,
            period,
            number="RCV-RBAC",
            movement_type="Receipt",
            movement_date="2026-07-01",
            quantity="1.000",
        )
        document = _valuation_document(
            valuation,
            receipt,
            number="VAL-RBAC",
            total_cost="25.00",
            actor="controller",
        )
        with pytest.raises(PlatformError, match="Segregation of duties"):
            valuation.approve_document(
                str(document["id"]), reason="Self approval", actor_label="controller"
            )
        approved = valuation.approve_document(
            str(document["id"]), reason="Independent approval", actor_label="reviewer"
        )
        assert approved["approved_by"] == "reviewer"
        with pytest.raises(PlatformError, match="Permission denied"):
            valuation.upsert_policy(
                policy_code="DENIED",
                organization_code="SYN",
                entity_code="EG01",
                journal_code="INV",
                receipt_clearing_account_code="2100",
                cogs_account_code="5100",
                adjustment_account_code="5190",
                actor_label="auditor",
            )
    finally:
        connection.close()

    client = TestClient(create_api_app(path))
    auditor_token = _token(client, "auditor")
    reviewer_token = _token(client, "reviewer")
    assert client.get(
        "/api/v1/inventory-valuation/snapshot",
        headers={"Authorization": f"Bearer {auditor_token}"},
    ).status_code == 200
    denied = client.post(
        "/api/v1/inventory-valuation/policies",
        headers={"Authorization": f"Bearer {auditor_token}"},
        json={
            "policy_code": "DENIED",
            "organization_code": "SYN",
            "entity_code": "EG01",
            "journal_code": "INV",
            "receipt_clearing_account_code": "2100",
            "cogs_account_code": "5100",
            "adjustment_account_code": "5190",
        },
    )
    assert denied.status_code == 403
    assert client.get(
        "/api/v1/inventory-valuation/documents?status=Approved",
        headers={"Authorization": f"Bearer {reviewer_token}"},
    ).json()["pagination"]["returned"] == 1

    result = runner.invoke(app, ["inventory", "valuation", "summary", "--db", str(path)])
    assert result.exit_code == 0
    assert json.loads(result.stdout)["summary"]["approved_documents"] == 1


def test_valuation_backup_restore_and_public_export(tmp_path: Path) -> None:
    source = _database(tmp_path, "source.db")
    connection = connect(source, require_exists=True)
    try:
        inventory, valuation, period = _seed(connection)
        receipt = _movement(
            inventory,
            period,
            number="RCV-BACKUP",
            movement_type="Receipt",
            movement_date="2026-07-01",
            quantity="4.000",
        )
        receipt_document = _valuation_document(
            valuation, receipt, number="VAL-BACKUP-R", total_cost="40.03"
        )
        valuation.approve_document(str(receipt_document["id"]), reason="Receipt reviewed")
        delivery = _movement(
            inventory,
            period,
            number="DLV-BACKUP",
            movement_type="Delivery",
            movement_date="2026-07-02",
            quantity="1.000",
        )
        delivery_document = _valuation_document(
            valuation, delivery, number="VAL-BACKUP-D"
        )
        valuation.approve_document(str(delivery_document["id"]), reason="Delivery reviewed")
        expected_layers = valuation.list_cost_layers(open_only=False)
        expected_summary = valuation.summary().to_dict()
    finally:
        connection.close()

    backup = create_backup(source, tmp_path / "backup")
    restored = tmp_path / "restored.db"
    restore_backup(restored, backup.output_dir)
    restored_connection = connect(restored, require_exists=True)
    try:
        restored_service = InventoryValuationService(restored_connection)
        assert restored_service.list_cost_layers(open_only=False) == expected_layers
        assert restored_service.summary().to_dict() == expected_summary
        assert restored_connection.execute(
            "SELECT COUNT(*) AS total FROM inventory_layer_consumptions"
        ).fetchone()["total"] == 1
    finally:
        restored_connection.close()

    exported = export_database(restored, tmp_path / "export")
    inventory_payload = json.loads(
        (exported.output_dir / "inventory.json").read_text(encoding="utf-8")
    )
    assert len(inventory_payload["valuation_documents"]) == 2
    assert len(inventory_payload["cost_layers"]) == 1
    assert len(inventory_payload["layer_consumptions"]) == 1


def test_migration_11_preserves_version_10_records(tmp_path: Path) -> None:
    path = tmp_path / "upgrade.db"
    run_migrations(path, target_version=10)
    connection = connect(path, require_exists=True)
    try:
        connection.execute(
            "INSERT INTO workspaces (id, name, local_first_note, created_at) VALUES ('WS-UP', 'upgrade', 'local', '2026-07-01T00:00:00Z')"
        )
        connection.commit()
    finally:
        connection.close()
    result = run_migrations(path)
    assert result.applied_versions == [11, 12]
    connection = connect(path, require_exists=True)
    try:
        assert connection.execute(
            "SELECT name FROM workspaces WHERE id = 'WS-UP'"
        ).fetchone()["name"] == "upgrade"
        assert SQLiteInventoryValuationRepository(connection).summary_counts("WS-UP") == {
            "policies": 0,
            "draft_documents": 0,
            "approved_documents": 0,
            "open_layers": 0,
            "unvalued_posted_movements": 0,
        }
    finally:
        connection.close()
