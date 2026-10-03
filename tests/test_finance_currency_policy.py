from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from reconforge.db import connect, run_migrations
from reconforge.db.backup import create_backup, restore_backup
from reconforge.platform.common import PlatformError
from reconforge.platform.master_data import MasterDataService
from reconforge.utils.money import CurrencyRegistry, CurrencySpec
from tests.test_finance_core import _create_entry, _seed_finance_model


@pytest.fixture(autouse=True)
def restore_registry():
    CurrencyRegistry.reset_to_bundled()
    yield
    CurrencyRegistry.reset_to_bundled()


def test_new_entry_retains_policy_and_master_edits_cannot_relabel_money(tmp_path: Path) -> None:
    path = tmp_path / "policy.db"
    run_migrations(path)
    with connect(path, require_exists=True) as connection:
        finance, period = _seed_finance_model(connection)
        masters = MasterDataService(connection)
        masters.bind_currency_registry()
        draft = _create_entry(finance, period)
        assert draft["currency_precision"] == 2
        assert draft["currency_rounding_policy"] == "ROUND_HALF_UP"
        digest = draft["currency_registry_digest"]
        finance.validate_entry(str(draft["id"]), reason="Independent review")
        with pytest.raises(PlatformError, match="immutable"):
            masters.upsert_currency(code="EGP", name="Changed precision", minor_units=3)
        with pytest.raises(PlatformError, match="immutable"):
            masters.upsert_legal_entity(
                organization_code="SYN", entity_code="EG01", name="Relabeled entity", currency_code="USD"
            )
        masters.upsert_currency(code="EGP", name="Renamed Egyptian pound", minor_units=2)
        detail = finance.get_entry(str(draft["id"]))
        assert detail["total_debit_minor"] == 100_000
        assert detail["total_debit"] == "1000.00"
        assert detail["currency_registry_digest"] == digest
        trial = finance.trial_balance(period_id=str(period["id"]), organization_code="SYN", entity_code="EG01")
        assert trial["totals"]["debit"] == "1000.00"
        for statement in (
            "UPDATE currencies SET minor_units=3 WHERE code='EGP'",
            "UPDATE legal_entities SET currency='USD' WHERE entity_code='EG01'",
            "UPDATE currency_registry_snapshots SET snapshot_json='{}'",
        ):
            with pytest.raises(sqlite3.DatabaseError, match="immutable"):
                connection.execute(statement)
            connection.rollback()


def test_workspace_binding_and_draft_policy_survive_installed_registry_change(tmp_path: Path) -> None:
    path = tmp_path / "binding.db"
    run_migrations(path)
    with connect(path, require_exists=True) as connection:
        finance, period = _seed_finance_model(connection)
        masters = MasterDataService(connection)
        masters.bind_currency_registry()
        first = _create_entry(finance, period)
        CurrencyRegistry.register(
            CurrencySpec(code="EGP", name="Synthetic changed EGP", minor_units=3),
            registry_version="synthetic-policy-v2", source="Synthetic policy test",
        )
        second = _create_entry(finance, period, number="JE/SECOND")
        assert second["total_debit_minor"] == 100_000
        assert second["currency_registry_digest"] == first["currency_registry_digest"]
        masters.bind_currency_registry()
        replaced = _create_entry(finance, period)
        assert replaced["total_debit_minor"] == 100_000
        assert replaced["currency_registry_digest"] == first["currency_registry_digest"]
        with pytest.raises(PlatformError, match="policy_mismatch"):
            _create_entry(finance, period, number="JE/MISMATCH")
        assert finance.get_entry(str(first["id"]))["total_debit"] == "1000.00"


@pytest.mark.parametrize("currency,precision,amount,minor", [
    ("JPY", 0, "100", 100), ("EGP", 2, "100.01", 10001),
    ("KWD", 3, "100.001", 100001), ("CLF", 4, "100.0001", 1000001),
])
def test_currency_precision_is_captured_exactly(
    tmp_path: Path, currency: str, precision: int, amount: str, minor: int,
) -> None:
    path = tmp_path / "precision.db"
    run_migrations(path)
    with connect(path, require_exists=True) as connection:
        finance, period = _seed_finance_model(connection)
        masters = MasterDataService(connection)
        masters.upsert_currency(code=currency, name=currency, minor_units=precision)
        masters.upsert_legal_entity(organization_code="SYN", entity_code="EXACT", name="Exact", currency_code=currency)
        finance.upsert_journal(journal_code="EXACT", name="Exact", organization_code="SYN", currency_code=currency)
        entry = finance.create_entry(
            entry_number="EXACT/1", organization_code="SYN", entity_code="EXACT", period_id=str(period["id"]),
            journal_code="EXACT", posting_date="2026-07-05", description="Exact currency policy",
            lines=[{"account_code": "1010", "debit": amount, "dimensions": {"CC": "HQ"}},
                   {"account_code": "3000", "credit": amount, "dimensions": {"CC": "HQ"}}],
        )
        assert entry["currency_precision"] == precision
        assert entry["total_debit_minor"] == minor
        assert entry["total_debit"] == amount


def test_legacy_upgrade_and_both_backup_versions_retain_unverified_minor_units(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "legacy.db"
    run_migrations(path, target_version=46)
    with connect(path, require_exists=True) as connection:
        _finance, period = _seed_finance_model(connection)
        journal = connection.execute("SELECT * FROM finance_journals WHERE journal_code='GJ'").fetchone()
        entity = connection.execute("SELECT id FROM legal_entities WHERE entity_code='EG01'").fetchone()
        connection.execute(
            """INSERT INTO ledger_entries(id,workspace_id,organization_id,chart_id,legal_entity_id,period_id,
               finance_journal_id,entry_number,posting_date,currency_code,description,created_by,created_at,updated_at)
               VALUES ('legacy',?,?,?,?,?,?,'LEGACY','2026-07-05','EGP','Legacy integers','maker','2026-07-05','2026-07-05')""",
            (journal["workspace_id"], journal["organization_id"], journal["chart_id"], entity["id"], period["id"], journal["id"]),
        )
        for number, account, debit, credit in ((1, "1010", 10000, 0), (2, "3000", 0, 10000)):
            account_id = connection.execute("SELECT id FROM accounts WHERE account_code=?", (account,)).fetchone()[0]
            connection.execute(
                "INSERT INTO ledger_lines(id,entry_id,line_number,account_id,debit_minor,credit_minor,created_at) "
                "VALUES (?,'legacy',?,?,?,?,'2026-07-05')", (f"legacy-{number}", number, account_id, debit, credit),
            )
        connection.execute("UPDATE ledger_entries SET status='Validated',validated_by='checker',validated_at='2026-07-05',validation_reason='Retained history' WHERE id='legacy'")
        connection.commit()
    import reconforge.db.backup as backup_module
    import reconforge.db.migrations as migration_module

    with monkeypatch.context() as old_writer:
        historical_migrations = [item for item in migration_module.MIGRATIONS if item.version <= 46]
        old_writer.setattr(migration_module, "MIGRATIONS", historical_migrations)
        old_writer.setattr(backup_module, "MIGRATIONS", historical_migrations)
        old_backup = create_backup(path, tmp_path / "old-backup")
    run_migrations(path)
    new_backup = create_backup(path, tmp_path / "new-backup")
    for label, backup in (("old", old_backup), ("new", new_backup)):
        restored = tmp_path / f"restored-{label}.db"
        restore_backup(restored, backup.backup_path)
        with connect(restored, require_exists=True) as connection:
            from reconforge.platform.finance_core import FinanceCoreService

            finance = FinanceCoreService(connection)
            raw = finance.list_entries()[0]
            assert raw["currency_policy_status"] == "unverified"
            assert raw["currency_registry_digest"] is None
            assert raw["total_debit_minor"] == 10000
            for operation in (
                lambda service=finance: service.get_entry("legacy"),
                lambda service=finance: service.void_entry("legacy", reason="Cannot guess policy"),
                lambda service=finance: service.trial_balance(period_id=str(period["id"]), organization_code="SYN", entity_code="EG01"),
            ):
                with pytest.raises(PlatformError, match="policy_unverified"):
                    operation()
            with pytest.raises(sqlite3.DatabaseError, match="verified currency policy is required"):
                connection.execute(
                    "INSERT INTO ledger_entries(id,workspace_id,organization_id,chart_id,legal_entity_id,period_id,"
                    "finance_journal_id,entry_number,posting_date,currency_code,description,external_reference,source_type,"
                    "status,created_by,validated_by,validated_at,validation_reason,voided_by,voided_at,void_reason,"
                    "created_at,updated_at,currency_precision,currency_rounding_policy,currency_registry_version,"
                    "currency_registry_digest) SELECT 'new-legacy',workspace_id,organization_id,chart_id,legal_entity_id,"
                    "period_id,finance_journal_id,'NEW-LEGACY',posting_date,currency_code,description,external_reference,"
                    "source_type,'Draft',created_by,validated_by,validated_at,validation_reason,voided_by,voided_at,"
                    "void_reason,created_at,updated_at,NULL,NULL,NULL,NULL FROM ledger_entries WHERE id='legacy'"
                )


def test_valuation_approval_and_reversal_keep_source_policy_after_rebinding(tmp_path: Path) -> None:
    from reconforge.platform.finance_core import FinanceCoreService
    from reconforge.platform.inventory_valuation_reversal import InventoryValuationReversalService
    from tests.test_inventory_valuation import _movement, _seed, _valuation_document

    path = tmp_path / "valuation-policy.db"
    run_migrations(path)
    with connect(path, require_exists=True) as connection:
        inventory, valuation, period = _seed(connection)
        receipt = _movement(inventory, period, number="RECEIPT", movement_type="Receipt", movement_date="2026-07-01", quantity="2.000")
        document = _valuation_document(valuation, receipt, number="VALUATION", total_cost="40.03")
        digest = connection.execute("SELECT currency_registry_digest FROM inventory_valuation_documents WHERE id=?", (document["id"],)).fetchone()[0]
        CurrencyRegistry.register(CurrencySpec(code="EGP", name="Changed registry", minor_units=3), registry_version="rebind-v2", source="Synthetic test")
        MasterDataService(connection).bind_currency_registry()
        approved = valuation.approve_document(str(document["id"]), reason="Independent review")
        finance = FinanceCoreService(connection)
        original = finance.get_entry(str(approved["finance_entry_id"]))
        assert original["currency_registry_digest"] == digest
        assert original["total_debit_minor"] == 4003
        assert original["total_debit"] == "40.03"
        mirror = _movement(inventory, period, number="MIRROR", movement_type="Delivery", movement_date="2026-07-02", quantity="2.000")
        reversals = InventoryValuationReversalService(connection)
        reversal = reversals.create_reversal(
            reversal_number="REVERSAL", original_valuation_document_id=str(document["id"]),
            reversal_movement_id=str(mirror["id"]), actor_label="reversal-maker",
        )
        result = reversals.approve_reversal(str(reversal["id"]), reason="Independent reversal review")
        entry = finance.get_entry(str(result["finance_entry_id"]))
        assert entry["currency_registry_digest"] == digest
        assert entry["currency_precision"] == 2
        assert entry["total_debit_minor"] == 4003
        assert entry["total_debit"] == "40.03"


def test_fifo_cannot_merge_different_retained_currency_manifests(tmp_path: Path) -> None:
    from tests.test_inventory_valuation import _movement, _seed, _valuation_document

    path = tmp_path / "fifo-policy.db"
    run_migrations(path)
    with connect(path, require_exists=True) as connection:
        inventory, valuation, period = _seed(connection)
        receipt = _movement(inventory, period, number="RECEIPT", movement_type="Receipt", movement_date="2026-07-01", quantity="2.000")
        source = _valuation_document(valuation, receipt, number="SOURCE", total_cost="40.03")
        valuation.approve_document(str(source["id"]), reason="Independent review")
        CurrencyRegistry.register(CurrencySpec(code="EGP", name="Changed provenance", minor_units=2), registry_version="new-provenance", source="Synthetic")
        MasterDataService(connection).bind_currency_registry()
        delivery = _movement(inventory, period, number="DELIVERY", movement_type="Delivery", movement_date="2026-07-02", quantity="2.000")
        target = _valuation_document(valuation, delivery, number="TARGET")
        with pytest.raises(PlatformError, match="finance_currency_policy_mismatch"):
            valuation.approve_document(str(target["id"]), reason="Do not silently merge policy provenance")
        assert connection.execute("SELECT COUNT(*) FROM ledger_entries").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM inventory_layer_consumptions").fetchone()[0] == 0
        assert connection.execute("SELECT remaining_value_minor FROM inventory_cost_layers").fetchone()[0] == 4003
