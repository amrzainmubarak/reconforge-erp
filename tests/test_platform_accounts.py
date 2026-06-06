from __future__ import annotations

from pathlib import Path

import pytest

from reconforge.audit import list_audit_events
from reconforge.auth import LocalAuthService
from reconforge.db import connect, run_migrations
from reconforge.platform.accounts import AccountReconciliationService
from reconforge.platform.common import PlatformError


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
