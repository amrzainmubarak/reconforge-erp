from __future__ import annotations

import json
import sqlite3
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
from reconforge.platform.inventory_valuation import InventoryValuationService
from reconforge.platform.inventory_valuation_reversal import InventoryValuationReversalService
from reconforge.platform.inventory_valuation_reversal_repository import (
    SQLiteInventoryValuationReversalRepository,
)
from reconforge.platform.master_data import MasterDataService

runner = CliRunner()
SCHEMA_DIR = Path(__file__).resolve().parents[1] / "docs" / "schemas"


def _assert_contract(filename: str, payload: object) -> None:
    schema = json.loads((SCHEMA_DIR / filename).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(payload)


def _database(tmp_path: Path, name: str = "reversal.db") -> Path:
    path = tmp_path / name
    run_migrations(path)
    return path


def _seed(
    connection: sqlite3.Connection,
    *,
    with_users: bool = False,
    allow_negative: bool = False,
    quantity_precision: int = 3,
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
    period = master.upsert_period(name="2026-07", start_date="2026-07-01", end_date="2026-07-31")
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
        uom_code="KG",
        name="Kilogram",
        category="Weight",
        decimal_places=quantity_precision,
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
        allow_negative=allow_negative,
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
    actor: str = "local-cli",
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
        actor_label=actor,
    )
    return inventory.post_movement(str(movement["id"]), reason="Independent stock review", actor_label=actor)


def _approve_valuation(
    valuation: InventoryValuationService,
    movement: dict[str, object],
    *,
    number: str,
    total_cost: str | None = None,
) -> dict[str, object]:
    document = valuation.create_document(
        valuation_number=number,
        movement_id=str(movement["id"]),
        policy_code="FIFO",
        input_costs=([] if total_cost is None else [{"line_number": 1, "total_cost": total_cost}]),
        actor_label="valuation-preparer",
    )
    return valuation.approve_document(str(document["id"]), reason="Synthetic valuation independently reviewed")


def _token(client: TestClient, username: str) -> str:
    response = client.post("/api/v1/auth/login", json={"username": username, "password": "Secret-123"})
    assert response.status_code == 200
    return str(response.json()["access_token"])


def test_receipt_reversal_removes_layer_and_creates_mirror_finance_draft(
    tmp_path: Path,
) -> None:
    path = _database(tmp_path)
    connection = connect(path, require_exists=True)
    try:
        inventory, valuation, period = _seed(connection)
        receipt = _movement(
            inventory,
            period,
            number="RCV-001",
            movement_type="Receipt",
            movement_date="2026-07-01",
            quantity="10.000",
        )
        original = _approve_valuation(valuation, receipt, number="VAL-001", total_cost="100.01")
        mirror = _movement(
            inventory,
            period,
            number="REV-RCV-001",
            movement_type="Delivery",
            movement_date="2026-07-02",
            quantity="10.000",
        )
        service = InventoryValuationReversalService(connection)
        draft = service.create_reversal(
            reversal_number="IVR-001",
            original_valuation_document_id=str(original["id"]),
            reversal_movement_id=str(mirror["id"]),
            actor_label="reversal-preparer",
        )
        approved = service.approve_reversal(str(draft["id"]), reason="Exact receipt correction independently reviewed")

        assert approved["status"] == "Approved"
        assert approved["total_value"] == "100.01"
        assert approved["finance_entry_status"] == "Draft"
        assert approved["effects"][0]["effect_type"] == "Remove"
        assert approved["effects"][0]["quantity"] == "10.000"
        assert approved["effects"][0]["value"] == "100.01"
        _assert_contract("inventory_valuation_reversal.schema.json", approved)
        _assert_contract("inventory_valuation_reversal_snapshot.schema.json", service.snapshot())
        layer = valuation.list_cost_layers(open_only=False)[0]
        assert layer["remaining_quantity"] == "0.000"
        assert layer["remaining_value"] == "0.00"

        reversal_entry = connection.execute(
            "SELECT * FROM ledger_entries WHERE id = ?", (approved["finance_entry_id"],)
        ).fetchone()
        reversal_lines = connection.execute(
            "SELECT * FROM ledger_lines WHERE entry_id = ? ORDER BY line_number",
            (approved["finance_entry_id"],),
        ).fetchall()
        original_lines = connection.execute(
            "SELECT * FROM ledger_lines WHERE entry_id = ? ORDER BY line_number",
            (original["finance_entry_id"],),
        ).fetchall()
        assert reversal_entry["status"] == "Draft"
        assert [row["debit_minor"] for row in reversal_lines] == [row["credit_minor"] for row in original_lines]
        assert [row["credit_minor"] for row in reversal_lines] == [row["debit_minor"] for row in original_lines]
        with pytest.raises(PlatformError, match="preserves this mirror movement"):
            inventory.void_movement(str(mirror["id"]), reason="Blocked evidence deletion")

        new_receipt = _movement(
            inventory,
            period,
            number="RCV-002",
            movement_type="Receipt",
            movement_date="2026-07-03",
            quantity="1.000",
        )
        _approve_valuation(valuation, new_receipt, number="VAL-002", total_cost="5.00")
        assert valuation.summary().unvalued_posted_movements == 0
        assert service.summary().to_dict() == {
            "workspace": "default",
            "draft_reversals": 0,
            "approved_reversals": 1,
            "cancelled_reversals": 0,
            "approved_effects": 1,
            "finance_drafts": 1,
        }
        _assert_contract("inventory_valuation_reversal.schema.json", approved)
        _assert_contract("inventory_valuation_reversal_snapshot.schema.json", service.snapshot())
        actions = {event.action for event in list_audit_events(connection)}
        assert {
            "inventory_valuation_reversal_draft_created",
            "inventory_valuation_reversal_approved",
        } <= actions
        assert verify_audit_events(connection).ok is True
    finally:
        connection.close()


def test_delivery_reversal_restores_exact_consumed_layer(tmp_path: Path) -> None:
    path = _database(tmp_path)
    connection = connect(path, require_exists=True)
    try:
        inventory, valuation, period = _seed(connection)
        receipt = _movement(
            inventory,
            period,
            number="RCV-001",
            movement_type="Receipt",
            movement_date="2026-07-01",
            quantity="10.000",
        )
        _approve_valuation(valuation, receipt, number="VAL-R", total_cost="100.01")
        delivery = _movement(
            inventory,
            period,
            number="DLV-001",
            movement_type="Delivery",
            movement_date="2026-07-02",
            quantity="3.000",
        )
        original = _approve_valuation(valuation, delivery, number="VAL-D")
        mirror = _movement(
            inventory,
            period,
            number="REV-DLV-001",
            movement_type="Receipt",
            movement_date="2026-07-03",
            quantity="3.000",
        )
        service = InventoryValuationReversalService(connection)
        draft = service.create_reversal(
            reversal_number="IVR-D",
            original_valuation_document_id=str(original["id"]),
            reversal_movement_id=str(mirror["id"]),
            actor_label="reversal-preparer",
        )
        approved = service.approve_reversal(str(draft["id"]), reason="Exact delivery correction reviewed")

        assert approved["total_value"] == "30.00"
        assert approved["effects"][0]["effect_type"] == "Restore"
        assert approved["effects"][0]["quantity"] == "3.000"
        assert approved["effects"][0]["value"] == "30.00"
        layer = valuation.list_cost_layers(open_only=True)[0]
        assert layer["remaining_quantity"] == "10.000"
        assert layer["remaining_value"] == "100.01"
        with pytest.raises(sqlite3.DatabaseError, match="immutable"):
            connection.execute(
                "UPDATE inventory_valuation_reversal_effects SET value_minor = 1 WHERE id = ?",
                (approved["effects"][0]["id"],),
            )
        connection.rollback()
        reversal_line = connection.execute(
            "SELECT id FROM ledger_lines WHERE entry_id = ? ORDER BY line_number LIMIT 1",
            (approved["finance_entry_id"],),
        ).fetchone()
        with pytest.raises(sqlite3.DatabaseError, match="finance lines are immutable"):
            connection.execute(
                "UPDATE ledger_lines SET debit_minor = debit_minor + 1 WHERE id = ?",
                (reversal_line["id"],),
            )
        connection.rollback()
        finance = FinanceCoreService(connection)
        finance.validate_entry(
            str(approved["finance_entry_id"]),
            reason="Independent Finance Core validation",
        )
        with pytest.raises(PlatformError, match="preserves this Finance Core entry"):
            finance.void_entry(
                str(approved["finance_entry_id"]),
                reason="Protected reversal evidence cannot be voided",
            )
    finally:
        connection.close()


def test_cancelled_reversal_releases_document_and_movement_for_a_new_draft(
    tmp_path: Path,
) -> None:
    path = _database(tmp_path)
    connection = connect(path, require_exists=True)
    try:
        inventory, valuation, period = _seed(connection)
        receipt = _movement(
            inventory,
            period,
            number="RCV-CANCEL",
            movement_type="Receipt",
            movement_date="2026-07-01",
            quantity="1.000",
        )
        original = _approve_valuation(valuation, receipt, number="VAL-CANCEL", total_cost="25.00")
        mirror = _movement(
            inventory,
            period,
            number="REV-CANCEL",
            movement_type="Delivery",
            movement_date="2026-07-02",
            quantity="1.000",
        )
        service = InventoryValuationReversalService(connection)
        draft = service.create_reversal(
            reversal_number="IVR-CANCEL-1",
            original_valuation_document_id=str(original["id"]),
            reversal_movement_id=str(mirror["id"]),
        )
        cancelled = service.cancel_reversal(str(draft["id"]), reason="Replacement evidence will use a new workflow")

        assert cancelled["status"] == "Cancelled"
        assert cancelled["finance_entry_id"] is None
        assert cancelled["effects"] == []
        assert inventory.get_movement(str(mirror["id"]))["status"] == "Posted"
        with pytest.raises(PlatformError, match="Only Draft"):
            service.approve_reversal(str(cancelled["id"]), reason="Cancelled records stay terminal")

        replacement = service.create_reversal(
            reversal_number="IVR-CANCEL-2",
            original_valuation_document_id=str(original["id"]),
            reversal_movement_id=str(mirror["id"]),
        )
        assert replacement["status"] == "Draft"
        assert replacement["id"] != cancelled["id"]
        assert service.summary().cancelled_reversals == 1
        assert service.summary().draft_reversals == 1
    finally:
        connection.close()


def test_six_decimal_delivery_reversal_restores_multiple_fifo_layers_exactly(
    tmp_path: Path,
) -> None:
    path = _database(tmp_path)
    connection = connect(path, require_exists=True)
    try:
        inventory, valuation, period = _seed(connection, quantity_precision=6)
        first_receipt = _movement(
            inventory,
            period,
            number="RCV-PREC-1",
            movement_type="Receipt",
            movement_date="2026-07-01",
            quantity="1.000001",
        )
        _approve_valuation(valuation, first_receipt, number="VAL-PREC-1", total_cost="100.01")
        second_receipt = _movement(
            inventory,
            period,
            number="RCV-PREC-2",
            movement_type="Receipt",
            movement_date="2026-07-02",
            quantity="1.000001",
        )
        _approve_valuation(valuation, second_receipt, number="VAL-PREC-2", total_cost="200.02")
        delivery = _movement(
            inventory,
            period,
            number="DLV-PREC",
            movement_type="Delivery",
            movement_date="2026-07-03",
            quantity="1.500001",
        )
        original = _approve_valuation(valuation, delivery, number="VAL-PREC-D")
        mirror = _movement(
            inventory,
            period,
            number="REV-PREC",
            movement_type="Receipt",
            movement_date="2026-07-04",
            quantity="1.500001",
        )
        service = InventoryValuationReversalService(connection)
        draft = service.create_reversal(
            reversal_number="IVR-PREC",
            original_valuation_document_id=str(original["id"]),
            reversal_movement_id=str(mirror["id"]),
            actor_label="reversal-preparer",
        )
        approved = service.approve_reversal(str(draft["id"]), reason="Six-decimal multi-layer restoration reviewed")

        assert [effect["quantity"] for effect in approved["effects"]] == [
            "1.000001",
            "0.500000",
        ]
        assert sum(
            int(row["value_minor"])
            for row in connection.execute(
                "SELECT value_minor FROM inventory_valuation_reversal_effects WHERE reversal_id = ?",
                (approved["id"],),
            ).fetchall()
        ) == int(original["total_value"].replace(".", ""))
        layers = {str(layer["valuation_number"]): layer for layer in valuation.list_cost_layers(open_only=False)}
        assert layers["VAL-PREC-1"]["remaining_quantity"] == "1.000001"
        assert layers["VAL-PREC-1"]["remaining_value"] == "100.01"
        assert layers["VAL-PREC-2"]["remaining_quantity"] == "1.000001"
        assert layers["VAL-PREC-2"]["remaining_value"] == "200.02"
    finally:
        connection.close()


def test_reversal_rejects_mismatch_consumed_receipt_and_known_user_self_approval(
    tmp_path: Path,
) -> None:
    path = _database(tmp_path)
    connection = connect(path, require_exists=True)
    try:
        inventory, valuation, period = _seed(connection, with_users=True, allow_negative=True)
        receipt = _movement(
            inventory,
            period,
            number="RCV-RISK",
            movement_type="Receipt",
            movement_date="2026-07-01",
            quantity="10.000",
        )
        original = _approve_valuation(valuation, receipt, number="VAL-RISK", total_cost="100.00")
        delivery = _movement(
            inventory,
            period,
            number="DLV-RISK",
            movement_type="Delivery",
            movement_date="2026-07-02",
            quantity="2.000",
        )
        dependent = _approve_valuation(valuation, delivery, number="VAL-RISK-D")
        wrong = _movement(
            inventory,
            period,
            number="REV-WRONG",
            movement_type="Delivery",
            movement_date="2026-07-03",
            quantity="9.000",
        )
        service = InventoryValuationReversalService(connection)
        with pytest.raises(PlatformError, match="quantity"):
            service.create_reversal(
                reversal_number="IVR-WRONG",
                original_valuation_document_id=str(original["id"]),
                reversal_movement_id=str(wrong["id"]),
            )
        mirror = _movement(
            inventory,
            period,
            number="REV-RISK",
            movement_type="Delivery",
            movement_date="2026-07-04",
            quantity="10.000",
        )
        draft = service.create_reversal(
            reversal_number="IVR-RISK",
            original_valuation_document_id=str(original["id"]),
            reversal_movement_id=str(mirror["id"]),
            actor_label="controller",
        )
        with pytest.raises(PlatformError, match="Segregation of duties"):
            service.approve_reversal(str(draft["id"]), reason="Self approval blocked", actor_label="controller")
        with pytest.raises(PlatformError, match="still consumed"):
            service.approve_reversal(str(draft["id"]), reason="Independent review", actor_label="reviewer")
        assert service.get_reversal(str(draft["id"]))["status"] == "Draft"

        dependent_mirror = _movement(
            inventory,
            period,
            number="REV-DLV-RISK",
            movement_type="Receipt",
            movement_date="2026-07-05",
            quantity="2.000",
        )
        dependent_draft = service.create_reversal(
            reversal_number="IVR-RISK-D",
            original_valuation_document_id=str(dependent["id"]),
            reversal_movement_id=str(dependent_mirror["id"]),
            actor_label="preparer",
        )
        dependent_approved = service.approve_reversal(
            str(dependent_draft["id"]),
            reason="Dependent outbound valuation reversed first",
            actor_label="reviewer",
        )
        assert dependent_approved["effects"][0]["effect_type"] == "Restore"
        approved = service.approve_reversal(
            str(draft["id"]),
            reason="Inbound layer is untouched after dependency reversal",
            actor_label="reviewer",
        )
        assert approved["effects"][0]["effect_type"] == "Remove"
        closed_layer = valuation.list_cost_layers(open_only=False)[0]
        assert closed_layer["remaining_quantity"] == "0.000"
        assert closed_layer["remaining_value"] == "0.00"
    finally:
        connection.close()


def test_reversal_api_cli_rbac_and_migration_12(tmp_path: Path) -> None:
    path = _database(tmp_path)
    connection = connect(path, require_exists=True)
    try:
        inventory, valuation, period = _seed(connection, with_users=True)
        receipt = _movement(
            inventory,
            period,
            number="RCV-API",
            movement_type="Receipt",
            movement_date="2026-07-01",
            quantity="1.000",
        )
        original = _approve_valuation(valuation, receipt, number="VAL-API", total_cost="25.00")
        mirror = _movement(
            inventory,
            period,
            number="REV-API",
            movement_type="Delivery",
            movement_date="2026-07-02",
            quantity="1.000",
        )
    finally:
        connection.close()

    client = TestClient(create_api_app(path))
    preparer = _token(client, "preparer")
    reviewer = _token(client, "reviewer")
    auditor = _token(client, "auditor")
    denied = client.post(
        "/api/v1/inventory-valuation/reversals",
        headers={"Authorization": f"Bearer {auditor}"},
        json={
            "reversal_number": "IVR-DENIED",
            "original_valuation_document_id": original["id"],
            "reversal_movement_id": mirror["id"],
        },
    )
    assert denied.status_code == 403
    created = client.post(
        "/api/v1/inventory-valuation/reversals",
        headers={"Authorization": f"Bearer {preparer}"},
        json={
            "reversal_number": "IVR-API",
            "original_valuation_document_id": original["id"],
            "reversal_movement_id": mirror["id"],
        },
    )
    assert created.status_code == 200, created.text
    reversal_id = created.json()["reversal"]["id"]
    approved = client.post(
        f"/api/v1/inventory-valuation/reversals/{reversal_id}/approve",
        headers={"Authorization": f"Bearer {reviewer}"},
        json={"reason": "Independent API review"},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["reversal"]["status"] == "Approved"
    read = client.get(
        "/api/v1/inventory-valuation/reversals/snapshot",
        headers={"Authorization": f"Bearer {auditor}"},
    )
    assert read.status_code == 200
    assert read.json()["source"]["external_calls"] is False
    _assert_contract("inventory_valuation_reversal_snapshot.schema.json", read.json())

    cli = runner.invoke(app, ["inventory", "valuation", "reversal", "summary", "--db", str(path)])
    assert cli.exit_code == 0, cli.output
    assert json.loads(cli.stdout)["summary"]["approved_reversals"] == 1

    old = tmp_path / "version-eleven.db"
    run_migrations(old, target_version=11)
    result = run_migrations(old)
    assert result.applied_versions == list(range(12, migration_module.MIGRATIONS[-1].version + 1))
    old_connection = connect(old, require_exists=True)
    try:
        assert SQLiteInventoryValuationReversalRepository(old_connection).summary_counts("missing") == {
            "draft_reversals": 0,
            "approved_reversals": 0,
            "cancelled_reversals": 0,
            "approved_effects": 0,
            "finance_drafts": 0,
        }
    finally:
        old_connection.close()


def test_reversal_backup_restore_and_public_export(tmp_path: Path) -> None:
    source = _database(tmp_path, "reversal-source.db")
    connection = connect(source, require_exists=True)
    try:
        inventory, valuation, period = _seed(connection)
        receipt = _movement(
            inventory,
            period,
            number="RCV-BACKUP",
            movement_type="Receipt",
            movement_date="2026-07-01",
            quantity="2.000",
        )
        original = _approve_valuation(valuation, receipt, number="VAL-BACKUP", total_cost="40.03")
        mirror = _movement(
            inventory,
            period,
            number="REV-BACKUP",
            movement_type="Delivery",
            movement_date="2026-07-02",
            quantity="2.000",
        )
        service = InventoryValuationReversalService(connection)
        draft = service.create_reversal(
            reversal_number="IVR-BACKUP",
            original_valuation_document_id=str(original["id"]),
            reversal_movement_id=str(mirror["id"]),
            actor_label="reversal-preparer",
        )
        expected = service.approve_reversal(str(draft["id"]), reason="Backup reversal review")
    finally:
        connection.close()

    backup = create_backup(source, tmp_path / "backup")
    restored = tmp_path / "restored.db"
    restore_backup(restored, backup.output_dir)
    restored_connection = connect(restored, require_exists=True)
    try:
        restored_reversal = InventoryValuationReversalService(restored_connection).get_reversal(str(expected["id"]))
        assert restored_reversal == expected
        layer = InventoryValuationService(restored_connection).list_cost_layers(open_only=False)[0]
        assert layer["remaining_quantity"] == "0.000"
        assert restored_connection.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        restored_connection.close()

    exported = export_database(restored, tmp_path / "export")
    payload = json.loads((exported.output_dir / "inventory.json").read_text(encoding="utf-8"))
    assert payload["valuation_reversals"][0]["reversal_number"] == "IVR-BACKUP"
    assert payload["valuation_reversal_effects"][0]["effect_type"] == "Remove"


def test_migration_12_preserves_and_locks_legacy_finance_line_dimensions(
    tmp_path: Path,
) -> None:
    path = tmp_path / "version-eleven-dimensions.db"
    run_migrations(path, target_version=11)
    connection = connect(path, require_exists=True)
    try:
        inventory, valuation, period = _seed(connection)
        finance = FinanceCoreService(connection)
        finance.upsert_dimension(
            dimension_code="CC",
            name="Cost center",
            dimension_type="Cost Center",
            required_on_entries=False,
        )
        value = finance.upsert_dimension_value(dimension_code="CC", value_code="OPS", name="Operations")
        receipt = _movement(
            inventory,
            period,
            number="RCV-DIM",
            movement_type="Receipt",
            movement_date="2026-07-01",
            quantity="2.000",
        )
        original = _approve_valuation(valuation, receipt, number="VAL-DIM", total_cost="40.03")
        original_line_ids = [
            str(row["id"])
            for row in connection.execute(
                "SELECT id FROM ledger_lines WHERE entry_id = ? ORDER BY line_number",
                (original["finance_entry_id"],),
            ).fetchall()
        ]
        for line_id in original_line_ids:
            connection.execute(
                "INSERT INTO ledger_line_dimensions (line_id, dimension_value_id) VALUES (?, ?)",
                (line_id, value["id"]),
            )
        connection.commit()
        mirror = _movement(
            inventory,
            period,
            number="REV-DIM",
            movement_type="Delivery",
            movement_date="2026-07-02",
            quantity="2.000",
        )
    finally:
        connection.close()

    result = run_migrations(path)
    assert result.applied_versions == list(range(12, migration_module.MIGRATIONS[-1].version + 1))
    connection = connect(path, require_exists=True)
    try:
        service = InventoryValuationReversalService(connection)
        draft = service.create_reversal(
            reversal_number="IVR-DIM",
            original_valuation_document_id=str(original["id"]),
            reversal_movement_id=str(mirror["id"]),
            actor_label="reversal-preparer",
        )
        approved = service.approve_reversal(str(draft["id"]), reason="Legacy dimensions independently reviewed")
        dimension_rows = connection.execute(
            """
            SELECT entries.id AS entry_id, lines.line_number, dimensions.dimension_value_id
            FROM ledger_entries entries
            JOIN ledger_lines lines ON lines.entry_id = entries.id
            JOIN ledger_line_dimensions dimensions ON dimensions.line_id = lines.id
            WHERE entries.id IN (?, ?)
            ORDER BY entries.id, lines.line_number, dimensions.dimension_value_id
            """,
            (original["finance_entry_id"], approved["finance_entry_id"]),
        ).fetchall()
        by_entry: dict[str, list[tuple[int, str]]] = {}
        for row in dimension_rows:
            by_entry.setdefault(str(row["entry_id"]), []).append(
                (int(row["line_number"]), str(row["dimension_value_id"]))
            )
        assert by_entry[str(original["finance_entry_id"])] == by_entry[str(approved["finance_entry_id"])]

        reversal_dimension = connection.execute(
            """
            SELECT dimensions.line_id, dimensions.dimension_value_id
            FROM ledger_line_dimensions dimensions
            JOIN ledger_lines lines ON lines.id = dimensions.line_id
            WHERE lines.entry_id = ? LIMIT 1
            """,
            (approved["finance_entry_id"],),
        ).fetchone()
        with pytest.raises(sqlite3.DatabaseError, match="dimensions are immutable"):
            connection.execute(
                "DELETE FROM ledger_line_dimensions WHERE line_id = ? AND dimension_value_id = ?",
                (reversal_dimension["line_id"], reversal_dimension["dimension_value_id"]),
            )
        connection.rollback()
        with pytest.raises(sqlite3.DatabaseError, match="dimensions are immutable"):
            connection.execute(
                "DELETE FROM ledger_line_dimensions WHERE line_id = ? AND dimension_value_id = ?",
                (original_line_ids[0], value["id"]),
            )
        connection.rollback()
    finally:
        connection.close()
