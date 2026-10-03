"""Actual reviewed cross-period effects and preserved balances after restore."""

from pathlib import Path

import pytest

from reconforge.db import connect, run_migrations
from reconforge.db.backup import create_backup, restore_backup
from reconforge.domain.finance_balances import verify_posted_balances
from reconforge.domain.finance_posting import FinancePostingError
from reconforge.infrastructure.sqlite_finance_posting import SQLiteFinancePostingRepository
from reconforge.platform.master_data import MasterDataService
from tests.test_sqlite_finance_posting import _actor, _post, _reviewed


def test_actual_opening_reversal_cutoff_draft_exclusion_and_restore(tmp_path: Path):
    path = tmp_path / "balances.db"
    run_migrations(path)
    with connect(path, require_exists=True) as connection:
        finance, july, repository, preview, maker, checker = _reviewed(connection)
        # Leave the first reviewed entry unposted: validation alone is not a balance.
        with _actor(connection, "maker"):
            opening = finance.create_entry(entry_number="JUL-OPENING", description="Common cross-backend opening", organization_code="SYN", entity_code="EG01", period_id=july["id"], journal_code="GJ", posting_date="2026-07-28", actor_label="maker", lines=[{"account_code": "1010", "debit": "100.00", "dimensions": {"CC": "HQ"}}, {"account_code": "3000", "credit": "100.00", "dimensions": {"CC": "HQ"}}])
        with _actor(connection, "checker"):
            finance.validate_entry(opening["id"], reason="Independent common opening review", actor_label="checker")
        preview = repository.preview(opening["id"], actor=checker)
        original = _post(repository, preview, checker)
        august = MasterDataService(connection).upsert_period(name="2026-08", start_date="2026-08-01", end_date="2026-08-31")
        reversal = repository.prepare_reversal(original["id"], command_id="reverse-aug", entry_number="REV-AUG", period_id=august["id"], posting_date="2026-08-10", reason="Later-period correction", actor=maker)
        with _actor(connection, "checker"):
            finance.validate_entry(reversal["entry_id"], reason="Independent inverse review", actor_label="checker")
        _post(repository, repository.preview(reversal["entry_id"], actor=checker), checker, "post-aug-inverse")
        with _actor(connection, "maker"):
            draft = finance.create_entry(entry_number="AUG-NEW", description="Synthetic later funding", organization_code="SYN", entity_code="EG01", period_id=august["id"], journal_code="GJ", posting_date="2026-08-20", actor_label="maker", lines=[{"account_code": "1010", "debit": "25.00", "dimensions": {"CC": "HQ"}}, {"account_code": "3000", "credit": "25.00", "dimensions": {"CC": "HQ"}}])
            finance.create_entry(entry_number="UNPOSTED", description="Synthetic unposted exclusion", organization_code="SYN", entity_code="EG01", period_id=august["id"], journal_code="GJ", posting_date="2026-08-01", actor_label="maker", lines=[{"account_code": "1010", "debit": "1.00", "dimensions": {"CC": "HQ"}}, {"account_code": "3000", "credit": "1.00", "dimensions": {"CC": "HQ"}}])
        with _actor(connection, "checker"):
            finance.validate_entry(draft["id"], reason="Independent new funding review", actor_label="checker")
        _post(repository, repository.preview(draft["id"], actor=checker), checker, "post-aug-new")
        # Historical reading must remain possible after the opening period closes.
        connection.execute("UPDATE periods SET status='Closed' WHERE id=?", (july["id"],))
        connection.commit()
        args = dict(period_id=august["id"], organization_code="SYN", entity_code="EG01", actor=checker)
        early = repository.posted_balances_as_of(as_of_date="2026-08-05", **args)
        middle = repository.posted_balances_as_of(as_of_date="2026-08-15", **args)
        final = repository.posted_balances_as_of(as_of_date="2026-08-31", **args)
        assert early["totals"]["closing"]["balance_totals"]["debit_minor"] == 10000
        assert middle["totals"]["closing"]["balance_totals"]["debit_minor"] == 0
        assert final["totals"]["closing"]["balance_totals"]["debit_minor"] == 2500
        assert [value["totals"]["closing"]["effect_count"] for value in (early, middle, final)] == [1, 2, 3]
        cash = next(row for row in final["accounts"] if row["account_id"] == original["snapshot"]["lines"][0]["account_id"])
        assert (cash["opening"]["balance_minor"], cash["activity"]["balance_minor"], cash["closing"]["balance_minor"]) == (10000, -7500, 2500)
        verify_posted_balances(final)
        # A read joins a caller's pending transaction without committing it.
        connection.execute("INSERT INTO workspaces(id,name,local_first_note,created_at) VALUES('pending-balance-read','Pending','Synthetic','2026-10-03T00:00:00Z')")
        assert repository.posted_balances_as_of(as_of_date="2026-08-31", **args) == final
        assert connection.in_transaction
        connection.rollback()
        assert connection.execute("SELECT 1 FROM workspaces WHERE id='pending-balance-read'").fetchone() is None
    backup_dir = tmp_path / "balances.backup"
    restored = tmp_path / "restored.db"
    backup = create_backup(path, backup_dir)
    restore_backup(restored, backup.backup_path)
    with connect(restored, require_exists=True) as connection:
        assert SQLiteFinancePostingRepository(connection).posted_balances_as_of(as_of_date="2026-08-31", **args) == final


@pytest.mark.parametrize("value", ["20260805", "2026-08-05T00:00:00", "2026-02-30", "2026-06-30", "2026-08-01", True])
def test_invalid_or_outside_dates_cannot_produce_a_balance(tmp_path: Path, value):
    path = tmp_path / "dates.db"
    run_migrations(path)
    with connect(path, require_exists=True) as connection:
        _, period, repository, _, _, checker = _reviewed(connection)
        with pytest.raises(FinancePostingError) as denied:
            repository.posted_balances_as_of(period_id=period["id"], as_of_date=value, organization_code="SYN", entity_code="EG01", actor=checker)
        assert denied.value.code == "posting_date_invalid"
