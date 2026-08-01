from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

import reconforge.platform.common as common_module
import reconforge.platform.finance_core as finance_core_module
import reconforge.platform.inventory_core as inventory_core_module
from reconforge.audit import AuditLedgerError
from reconforge.db import connect, run_migrations
from reconforge.platform.approvals import ApprovalService
from reconforge.platform.close import CloseManagementService
from reconforge.platform.common import PlatformError
from reconforge.platform.controls import ControlTestingService
from reconforge.platform.evidence import EvidenceRegistryService
from reconforge.platform.exceptions import ExceptionQueueService
from reconforge.platform.intercompany import IntercompanyService
from reconforge.platform.journals import JournalControlService
from reconforge.platform.master_data import MasterDataService
from reconforge.platform.metrics import MetricsService


def _seed_finance_for_entry_tests(connection: sqlite3.Connection) -> tuple[finance_core_module.FinanceCoreService, dict[str, object]]:
    masters = MasterDataService(connection)
    masters.upsert_organization(organization_code="SYN", name="Synthetic Group")
    masters.upsert_legal_entity(
        organization_code="SYN", entity_code="EG01", name="Synthetic Egypt", currency_code="EGP"
    )
    period = masters.upsert_period(name="2026-07", start_date="2026-07-01", end_date="2026-07-31")
    finance = finance_core_module.FinanceCoreService(connection)
    finance.upsert_account(
        account_code="1000",
        name="Cash",
        account_type="Asset",
        normal_balance="Debit",
    )
    finance.upsert_account(
        account_code="3000",
        name="Equity",
        account_type="Equity",
        normal_balance="Credit",
    )
    finance.upsert_dimension(dimension_code="CC", name="Cost Center", required_on_entries=True)
    finance.upsert_dimension_value(dimension_code="CC", value_code="HQ", name="Head Office")
    finance.upsert_journal(
        journal_code="GJ",
        name="General Journal",
        organization_code="SYN",
        currency_code="EGP",
    )
    return finance, period


def _seed_inventory_for_movement_tests(
    connection: sqlite3.Connection,
) -> tuple[inventory_core_module.InventoryCoreService, dict[str, object]]:
    masters = MasterDataService(connection)
    masters.upsert_organization(organization_code="SYN", name="Synthetic Group")
    masters.upsert_legal_entity(
        organization_code="SYN", entity_code="EG01", name="Synthetic Egypt", currency_code="EGP"
    )
    period = masters.upsert_period(name="2026-07", start_date="2026-07-01", end_date="2026-07-31")
    finance = finance_core_module.FinanceCoreService(connection)
    finance.upsert_account(account_code="1400", name="Inventory", account_type="Asset", normal_balance="Debit")
    inventory = inventory_core_module.InventoryCoreService(connection)
    inventory.upsert_uom(uom_code="KG", name="Kilogram", category="Weight", decimal_places=3)
    inventory.upsert_item(
        item_code="MAT-01",
        name="Synthetic material",
        organization_code="SYN",
        uom_code="KG",
        inventory_account_code="1400",
    )
    inventory.upsert_warehouse(warehouse_code="MAIN", name="Main", organization_code="SYN", entity_code="EG01")
    inventory.upsert_location(warehouse_code="MAIN", location_code="RECV", name="Receiving", organization_code="SYN")
    inventory.upsert_location(warehouse_code="MAIN", location_code="STOCK", name="Stock", organization_code="SYN")
    return inventory, period


def _fail_audit(*_args: object, **_kwargs: object) -> None:
    raise AuditLedgerError("forced audit failure")


def test_exception_queue_rolls_back_when_audit_append_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "exception-atomic.db"
    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    monkeypatch.setattr(common_module, "audit", _fail_audit)
    try:
        with pytest.raises(PlatformError, match="audit evidence"):
            ExceptionQueueService(connection).upsert_exception(
                source_type="test",
                source_id="EX-1",
                description="Synthetic exception",
            )
        assert connection.execute("SELECT COUNT(*) AS count FROM exceptions_queue").fetchone()["count"] == 0
    finally:
        connection.close()


def test_metrics_roll_back_when_audit_append_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "metrics-atomic.db"
    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    monkeypatch.setattr(common_module, "audit", _fail_audit)
    try:
        with pytest.raises(PlatformError, match="audit evidence"):
            MetricsService(connection).compute()
        assert connection.execute("SELECT COUNT(*) AS count FROM metric_snapshots").fetchone()["count"] == 0
    finally:
        connection.close()


def test_control_library_import_rolls_back_when_audit_append_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "controls-atomic.db"
    controls = tmp_path / "controls.csv"
    controls.write_text("control_code,name\nCTRL-1,Synthetic control\n", encoding="utf-8")
    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    monkeypatch.setattr(common_module, "audit", _fail_audit)
    try:
        with pytest.raises(PlatformError, match="audit evidence"):
            ControlTestingService(connection).import_library(controls)
        assert connection.execute("SELECT COUNT(*) AS count FROM control_library").fetchone()["count"] == 0
    finally:
        connection.close()


def test_control_result_and_exception_roll_back_when_audit_append_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "control-result-atomic.db"
    controls = tmp_path / "controls.csv"
    controls.write_text("control_code,name,risk_rating\nCTRL-1,Synthetic control,high\n", encoding="utf-8")
    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    try:
        service = ControlTestingService(connection)
        service.import_library(controls)
        service.plan_tests(period_name="2026-07")
        plan_id = str(service.list_plans(period_name="2026-07")[0]["id"])
        monkeypatch.setattr(common_module, "audit", _fail_audit)
        with pytest.raises(PlatformError, match="audit evidence"):
            service.record_result(
                plan_id=plan_id, result_status="Completed", effectiveness_status="Ineffective"
            )
        assert connection.execute("SELECT COUNT(*) AS count FROM control_test_results").fetchone()["count"] == 0
        assert connection.execute("SELECT status FROM control_test_plans WHERE id = ?", (plan_id,)).fetchone()["status"] == "Planned"
        assert connection.execute("SELECT COUNT(*) AS count FROM exceptions_queue").fetchone()["count"] == 0
    finally:
        connection.close()


def test_intercompany_import_rolls_back_when_audit_append_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "intercompany-atomic.db"
    transactions = tmp_path / "intercompany.csv"
    transactions.write_text(
        "transaction_id,period_name,entity_code,counterparty_code,posting_date,amount,currency,reference\n"
        "IC-1,2026-05,US01,UK01,2026-05-10,100,USD,REF-1\n",
        encoding="utf-8",
    )
    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    monkeypatch.setattr(common_module, "audit", _fail_audit)
    try:
        with pytest.raises(PlatformError, match="audit evidence"):
            IntercompanyService(connection).import_transactions(transactions)
        assert connection.execute("SELECT COUNT(*) AS count FROM intercompany_transactions").fetchone()["count"] == 0
    finally:
        connection.close()


def test_intercompany_match_rolls_back_case_exception_and_outbox_when_audit_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "intercompany-match-atomic.db"
    transactions = tmp_path / "intercompany.csv"
    transactions.write_text(
        "transaction_id,period_name,entity_code,counterparty_code,amount,currency,reference\n"
        "IC-1,2026-08,A,B,10.00,USD,REF-1\n",
        encoding="utf-8",
    )
    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    try:
        service = IntercompanyService(connection)
        service.import_transactions(transactions)
        connection.execute("DELETE FROM outbox_events")
        connection.commit()
        monkeypatch.setattr(common_module, "audit", _fail_audit)
        with pytest.raises(PlatformError, match="audit evidence"):
            service.match(period_name="2026-08", tolerance="0.01")
        assert connection.execute("SELECT COUNT(*) AS count FROM intercompany_cases").fetchone()["count"] == 0
        assert connection.execute("SELECT COUNT(*) AS count FROM exceptions_queue").fetchone()["count"] == 0
        assert connection.execute("SELECT COUNT(*) AS count FROM outbox_events").fetchone()["count"] == 0
    finally:
        connection.close()


def test_intercompany_missing_settlement_has_no_audit_or_outbox_effect(tmp_path: Path) -> None:
    db_path = tmp_path / "intercompany-missing-settlement.db"
    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    try:
        with pytest.raises(PlatformError, match="case not found"):
            IntercompanyService(connection).settle("ICC-missing")
        assert connection.execute("SELECT COUNT(*) AS count FROM audit_events").fetchone()["count"] == 0
        assert connection.execute("SELECT COUNT(*) AS count FROM outbox_events").fetchone()["count"] == 0
    finally:
        connection.close()


def test_journal_import_rolls_back_when_audit_append_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "journal-atomic.db"
    journals = tmp_path / "journals.csv"
    journals.write_text(
        "journal_id,period_name,entity_code,posting_date,account_code,amount,currency\n"
        "J-1,2026-07,EG01,2026-07-10,1000,10.00,EGP\n",
        encoding="utf-8",
    )
    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    monkeypatch.setattr(common_module, "audit", _fail_audit)
    try:
        with pytest.raises(PlatformError, match="audit evidence"):
            JournalControlService(connection).import_journals(journals)
        assert connection.execute("SELECT COUNT(*) AS count FROM journal_entries").fetchone()["count"] == 0
        assert connection.execute("SELECT COUNT(*) AS count FROM outbox_events").fetchone()["count"] == 0
    finally:
        connection.close()


def test_master_data_and_approval_mutations_roll_back_when_audit_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "approval-master-data-atomic.db"
    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    monkeypatch.setattr(common_module, "audit", _fail_audit)
    try:
        with pytest.raises(PlatformError, match="audit evidence"):
            MasterDataService(connection).upsert_currency(code="ZZZ", name="Synthetic currency")
        with pytest.raises(PlatformError, match="audit evidence"):
            ApprovalService(connection).submit(
                object_type="test",
                object_id="OBJ-1",
                title="Synthetic approval",
                assigned_to="reviewer",
            )
        assert connection.execute("SELECT COUNT(*) AS count FROM currencies WHERE code = 'ZZZ'").fetchone()["count"] == 0
        assert connection.execute("SELECT COUNT(*) AS count FROM approval_requests").fetchone()["count"] == 0
    finally:
        connection.close()


def test_evidence_registration_rolls_back_when_audit_append_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "evidence-atomic.db"
    evidence_file = tmp_path / "evidence.txt"
    evidence_file.write_text("synthetic evidence\n", encoding="utf-8")
    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    monkeypatch.setattr(common_module, "audit", _fail_audit)
    try:
        with pytest.raises(PlatformError, match="audit evidence"):
            EvidenceRegistryService(connection).register(evidence_file, evidence_code="EV-1")
        assert connection.execute("SELECT COUNT(*) AS count FROM evidence_registry").fetchone()["count"] == 0
    finally:
        connection.close()


def test_linked_evidence_registration_rolls_back_all_effects_when_final_audit_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "linked-evidence-atomic.db"
    evidence_file = tmp_path / "linked-evidence.txt"
    evidence_file.write_text("synthetic linked evidence\n", encoding="utf-8")
    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    original_audit = common_module.audit
    calls = 0

    def fail_second_audit(*args: object, **kwargs: object) -> object:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise AuditLedgerError("synthetic final audit failure")
        return original_audit(*args, **kwargs)

    monkeypatch.setattr(common_module, "audit", fail_second_audit)
    try:
        with pytest.raises(PlatformError, match="audit evidence"):
            EvidenceRegistryService(connection).register(
                evidence_file, evidence_code="EV-LINK", object_type="control", object_id="CTRL-1"
            )
        assert connection.execute("SELECT COUNT(*) AS count FROM evidence_registry").fetchone()["count"] == 0
        assert connection.execute("SELECT COUNT(*) AS count FROM evidence_links").fetchone()["count"] == 0
        assert connection.execute("SELECT COUNT(*) AS count FROM audit_events").fetchone()["count"] == 0
        assert connection.execute("SELECT COUNT(*) AS count FROM outbox_events").fetchone()["count"] == 0
    finally:
        connection.close()


def test_close_period_initialization_rolls_back_when_audit_append_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "close-atomic.db"
    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    monkeypatch.setattr(common_module, "audit", _fail_audit)
    try:
        with pytest.raises(PlatformError, match="audit evidence"):
            CloseManagementService(connection).period_init(
                period_name="2026-05",
                start_date="2026-05-01",
                end_date="2026-05-31",
            )
        assert connection.execute("SELECT COUNT(*) AS count FROM close_periods").fetchone()["count"] == 0
        assert connection.execute("SELECT COUNT(*) AS count FROM close_tasks_db").fetchone()["count"] == 0
    finally:
        connection.close()


def test_finance_core_upsert_account_rolls_back_when_audit_append_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "finance-core-atomic-upsert.db"
    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    finance = finance_core_module.FinanceCoreService(connection)
    finance.upsert_account(account_code="1000", name="Seed account", account_type="Asset", normal_balance="Debit")
    monkeypatch.setattr(common_module, "audit", _fail_audit)
    try:
        with pytest.raises(PlatformError, match="audit evidence"):
            finance.upsert_account(account_code="2000", name="Synthetic account", account_type="Asset", normal_balance="Debit")
        assert connection.execute("SELECT COUNT(*) AS count FROM accounts WHERE account_code = '2000'").fetchone()[
            "count"
        ] == 0
    finally:
        connection.close()


def test_finance_core_create_entry_rolls_back_when_audit_append_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "finance-core-entry-atomic.db"
    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    try:
        finance, period = _seed_finance_for_entry_tests(connection)
        monkeypatch.setattr(common_module, "audit", _fail_audit)
        with pytest.raises(PlatformError, match="audit evidence"):
            finance.create_entry(
                entry_number="JE/ATOMIC",
                organization_code="SYN",
                entity_code="EG01",
                period_id=str(period["id"]),
                journal_code="GJ",
                posting_date="2026-07-05",
                description="Synthetic atomic failure",
                lines=[
                    {"account_code": "1000", "debit": "10.00", "dimensions": {"CC": "HQ"}},
                    {"account_code": "3000", "credit": "10.00", "dimensions": {"CC": "HQ"}},
                ],
            )
        assert connection.execute("SELECT COUNT(*) AS count FROM ledger_entries WHERE entry_number = 'JE/ATOMIC'").fetchone()[
            "count"
        ] == 0
    finally:
        connection.close()


def test_inventory_core_upsert_uom_rolls_back_when_audit_append_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "inventory-core-uom-atomic.db"
    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    inventory = inventory_core_module.InventoryCoreService(connection)
    inventory.upsert_uom(uom_code="KG", name="Kilogram", category="Weight")
    monkeypatch.setattr(common_module, "audit", _fail_audit)
    try:
        with pytest.raises(PlatformError, match="audit evidence"):
            inventory.upsert_uom(uom_code="LB", name="Pound", category="Weight")
        assert connection.execute("SELECT COUNT(*) AS count FROM units_of_measure WHERE uom_code = 'LB'").fetchone()[
            "count"
        ] == 0
    finally:
        connection.close()


def test_inventory_core_create_movement_rolls_back_when_audit_append_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "inventory-core-movement-atomic.db"
    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    try:
        inventory, period = _seed_inventory_for_movement_tests(connection)
        monkeypatch.setattr(common_module, "audit", _fail_audit)
        with pytest.raises(PlatformError, match="audit evidence"):
            inventory.create_movement(
                movement_number="RCV/ATOMIC",
                movement_type="Receipt",
                organization_code="SYN",
                entity_code="EG01",
                period_id=str(period["id"]),
                movement_date="2026-07-06",
                description="Synthetic failing movement",
                lines=[{"item_code": "MAT-01", "quantity": "1.000", "to_location": "MAIN/RECV"}],
            )
        assert (
            connection.execute("SELECT COUNT(*) AS count FROM inventory_movements WHERE movement_number = 'RCV/ATOMIC'").fetchone()[
                "count"
            ]
            == 0
        )
    finally:
        connection.close()
