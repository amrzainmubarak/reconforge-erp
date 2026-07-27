from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

import reconforge.platform.accounts as accounts_module
import reconforge.platform.common as common_module
from reconforge.audit import AuditLedgerError, list_audit_events
from reconforge.auth import LocalAuthService
from reconforge.cli import app
from reconforge.db import connect, run_migrations
from reconforge.db.backup import create_backup, restore_backup
from reconforge.platform.accounts import AccountReconciliationService
from reconforge.platform.common import PlatformError

runner = CliRunner()


def _db_with_users(tmp_path: Path) -> Path:
    db_path = tmp_path / "accounts.db"
    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    try:
        auth = LocalAuthService(connection)
        auth.init_admin(username="admin", password="Secret-123")
        auth.create_user(username="prep", password="Secret-123", role="preparer")
        auth.create_user(username="review", password="Secret-123", role="reviewer")
    finally:
        connection.close()
    return db_path


def test_account_reconciliation_lifecycle_and_sod(tmp_path: Path) -> None:
    db_path = _db_with_users(tmp_path)
    trial_balance = tmp_path / "trial_balance.csv"
    trial_balance.write_text(
        "period,entity_code,account_code,account_name,balance,currency\n"
        "2026-05,US01,1000,Cash,125000,USD\n",
        encoding="utf-8",
    )

    connection = connect(db_path, require_exists=True)
    try:
        service = AccountReconciliationService(connection)
        service.create_template(
            account_code="1000",
            risk_rating="high",
            materiality_threshold=10000,
            owner="prep",
            reviewer="review",
            actor_label="prep",
        )
        result = service.import_trial_balance(trial_balance, actor_label="prep")
        records = service.list_reconciliations(period_name="2026-05")
        reconciliation_id = records[0]["id"]
        detail = service.get_reconciliation(str(reconciliation_id))
        prepared = service.prepare(reconciliation_id=str(reconciliation_id), actor_label="prep")
        submitted = service.submit(str(reconciliation_id), actor_label="prep")
        reviewed = service.review(str(reconciliation_id), actor_label="review")
        completed = service.complete(str(reconciliation_id), actor_label="review")
        audit_actions = [event.action for event in list_audit_events(connection)]
    finally:
        connection.close()

    assert result.imported_rows == 1
    assert records[0]["risk_rating"] == "high"
    assert detail["items"][0]["evidence_required"] == 1
    assert prepared["status"] == "Prepared"
    assert submitted["status"] == "In Review"
    assert reviewed["status"] == "Reviewed"
    assert completed["status"] == "Complete"
    assert "trial_balance_imported" in audit_actions
    assert "account_reconciliation_transitioned" in audit_actions


def test_account_reconciliation_rejects_same_preparer_reviewer(tmp_path: Path) -> None:
    db_path = _db_with_users(tmp_path)
    connection = connect(db_path, require_exists=True)
    try:
        service = AccountReconciliationService(connection)
        record = service.create_reconciliation(
            period_name="2026-05",
            entity_code="US01",
            account_code="2000",
            actor_label="admin",
        )
        service.prepare(reconciliation_id=str(record["id"]), actor_label="admin")
        service.submit(str(record["id"]), actor_label="admin")
        with pytest.raises(PlatformError, match="Separation of duties"):
            service.review(str(record["id"]), actor_label="admin")
    finally:
        connection.close()


def _fail_audit(*_args: object, **_kwargs: object) -> None:
    raise AuditLedgerError("forced audit failure")


def _fail_outbox(*_args: object, **_kwargs: object) -> None:
    raise PlatformError("forced outbox failure")


def test_account_reconciliation_uses_strict_decimal_storage_and_rejects_invalid_amounts(tmp_path: Path) -> None:
    db_path = _db_with_users(tmp_path)
    trial_balance = tmp_path / "strict_trial_balance.csv"
    trial_balance.write_text(
        "period,entity_code,account_code,account_name,balance,currency\n"
        "2026-05,US01,1000,Cash,125000.25,USD\n",
        encoding="utf-8",
    )
    invalid_trial_balance = tmp_path / "invalid_trial_balance.csv"
    invalid_trial_balance.write_text(
        "period,entity_code,account_code,account_name,balance,currency\n"
        "2026-05,US01,1001,Invalid,not-a-number,USD\n",
        encoding="utf-8",
    )

    connection = connect(db_path, require_exists=True)
    try:
        service = AccountReconciliationService(connection)
        service.create_template(
            account_code="1000",
            materiality_threshold="100.10",
            actor_label="prep",
        )
        service.import_trial_balance(trial_balance, actor_label="prep")
        record = service.list_reconciliations(period_name="2026-05")[0]
        trial_row = connection.execute(
            "SELECT balance_decimal, currency FROM trial_balance_rows WHERE account_code = '1000'",
        ).fetchone()
        assert record["balance_decimal"] == "125000.25"
        assert record["currency_code"] == "USD"
        assert record["materiality_threshold_decimal"] == "100.1"
        assert trial_row["balance_decimal"] == "125000.25"
        with pytest.raises(PlatformError, match="financial amount"):
            service.import_trial_balance(invalid_trial_balance, actor_label="prep")
        assert connection.execute(
            "SELECT COUNT(*) AS count FROM trial_balance_rows WHERE account_code = '1001'",
        ).fetchone()["count"] == 0
    finally:
        connection.close()


def test_accounts_cli_preserves_exact_materiality_text_before_decimal_parsing(tmp_path: Path) -> None:
    db_path = _db_with_users(tmp_path)
    exact_threshold = "0.10000000000000001"

    result = runner.invoke(
        app,
        [
            "accounts",
            "create-template",
            "--account-code",
            "1000",
            "--materiality",
            exact_threshold,
            "--actor",
            "prep",
            "--db",
            str(db_path),
        ],
    )

    assert result.exit_code == 0, result.output
    connection = connect(db_path, require_exists=True)
    try:
        stored = connection.execute(
            "SELECT materiality_threshold_decimal FROM account_reconciliation_templates WHERE account_code = '1000'",
        ).fetchone()
    finally:
        connection.close()
    assert stored is not None
    assert stored["materiality_threshold_decimal"] == exact_threshold


def test_accounts_cli_rejects_scientific_notation_materiality_without_mutation(tmp_path: Path) -> None:
    db_path = _db_with_users(tmp_path)

    result = runner.invoke(
        app,
        [
            "accounts",
            "create-template",
            "--account-code",
            "1000",
            "--materiality",
            "1e-3",
            "--actor",
            "prep",
            "--db",
            str(db_path),
        ],
    )

    assert result.exit_code != 0
    connection = connect(db_path, require_exists=True)
    try:
        count = connection.execute(
            "SELECT COUNT(*) AS count FROM account_reconciliation_templates WHERE account_code = '1000'",
        ).fetchone()["count"]
    finally:
        connection.close()
    assert count == 0


def test_account_reconciliation_rolls_back_business_workflow_audit_and_outbox_on_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = _db_with_users(tmp_path)
    connection = connect(db_path, require_exists=True)
    try:
        service = AccountReconciliationService(connection)
        audit_count = connection.execute("SELECT COUNT(*) AS count FROM audit_events").fetchone()["count"]
        outbox_count = connection.execute("SELECT COUNT(*) AS count FROM outbox_events").fetchone()["count"]
        monkeypatch.setattr(common_module, "audit", _fail_audit)
        with pytest.raises(PlatformError, match="audit evidence"):
            service.create_reconciliation(
                period_name="2026-05",
                entity_code="US01",
                account_code="1000",
                balance="10.00",
                actor_label="prep",
            )
        assert connection.execute("SELECT COUNT(*) AS count FROM account_reconciliation_records").fetchone()["count"] == 0
        assert connection.execute("SELECT COUNT(*) AS count FROM workflow_objects").fetchone()["count"] == 0
        assert connection.execute("SELECT COUNT(*) AS count FROM audit_events").fetchone()["count"] == audit_count
        assert connection.execute("SELECT COUNT(*) AS count FROM outbox_events").fetchone()["count"] == outbox_count
        monkeypatch.setattr(accounts_module, "append_outbox_event", _fail_outbox)
        with pytest.raises(PlatformError, match="outbox"):
            AccountReconciliationService(connection).create_reconciliation(
                period_name="2026-05",
                entity_code="US01",
                account_code="1001",
                balance="10.00",
                actor_label="prep",
            )
        assert connection.execute("SELECT COUNT(*) AS count FROM account_reconciliation_records").fetchone()["count"] == 0
        assert connection.execute("SELECT COUNT(*) AS count FROM workflow_objects").fetchone()["count"] == 0
    finally:
        connection.close()


def test_account_reconciliation_backup_restore_preserves_decimal_columns(tmp_path: Path) -> None:
    db_path = _db_with_users(tmp_path)
    connection = connect(db_path, require_exists=True)
    try:
        record = AccountReconciliationService(connection).create_reconciliation(
            period_name="2026-05",
            entity_code="US01",
            account_code="1000",
            balance="10.25",
            materiality_threshold="1.25",
            actor_label="prep",
        )
    finally:
        connection.close()

    backup = create_backup(db_path, tmp_path / "accounts-backup")
    restored_db = tmp_path / "accounts-restored.db"
    restore_backup(restored_db, backup.backup_path)
    connection = connect(restored_db, require_exists=True)
    try:
        restored = connection.execute(
            """
            SELECT balance_decimal, materiality_threshold_decimal, currency_code
            FROM account_reconciliation_records WHERE id = ?
            """,
            (record["id"],),
        ).fetchone()
        item = connection.execute(
            "SELECT amount_decimal FROM account_reconciliation_items WHERE reconciliation_id = ?",
            (record["id"],),
        ).fetchone()
        assert restored is not None
        assert (restored["balance_decimal"], restored["materiality_threshold_decimal"], restored["currency_code"]) == (
            "10.25",
            "1.25",
            "LOCAL",
        )
        assert item["amount_decimal"] == "10.25"
    finally:
        connection.close()
