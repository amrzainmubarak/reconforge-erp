"""Actual storage admission, writer ordering and coherent reviewed-source backup."""

from __future__ import annotations

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import replace
from pathlib import Path
from threading import Event

import pytest

import reconforge.db.backup as backup_module
import reconforge.infrastructure.sqlite_inventory_receipt_finance as participant_module
import reconforge.infrastructure.sqlite_inventory_receipt_posting as receipt_module
from reconforge.db import connect
from reconforge.db.backup import create_backup, restore_backup
from reconforge.db.exporter import DBBridgeError
from reconforge.domain.inventory_receipt_posting import ReceiptReversalPreparation
from reconforge.infrastructure.sqlite_finance_posting import verify_posting_storage
from reconforge.infrastructure.sqlite_inventory_receipt_posting import (
    SQLiteInventoryReceiptPostingRepository,
    verify_receipt_storage,
)
from reconforge.platform.common import server_principal_context, trusted_local_mode
from reconforge.platform.finance_core import FinanceCoreService
from reconforge.platform.inventory_core import InventoryCoreService
from reconforge.platform.inventory_valuation import InventoryValuationService
from reconforge.platform.master_data import MasterDataService
from reconforge.utils.money import CurrencyRegistryContext
from tests.test_sqlite_finance_posting import _actor, _posting_actor
from tests.test_sqlite_inventory_receipt_posting import _fixture, _reviewed


def _commit(repository, plan, review, principal, command="commit"):
    return repository.commit(
        plan["plan_id"],
        command_id=command,
        expected_review_digest=review["review_digest"],
        reason="Independent reviewed posting",
        actor=_posting_actor(principal),
    )


@pytest.mark.parametrize("family", ["bundle", "finance"])
@pytest.mark.parametrize("field", ["audit", "outbox"])
@pytest.mark.parametrize("corruption", ["missing", "unrelated"])
def test_effect_insert_itself_requires_exact_bundle_and_finance_evidence(
    tmp_path: Path, monkeypatch, family, field, corruption
) -> None:
    _path, connection, repository, request = _fixture(tmp_path)
    try:
        plan, review = _reviewed(connection, repository, request)
        wrong = "missing-evidence" if corruption == "missing" else plan[f"preparation_{field}_event_id"]
        attempted = []
        insert = participant_module._insert

        def inspect_insert(conn, table, values):
            if table == "finance_posting_effects":
                attempted.append(table)
                if family == "finance":
                    values = {**values, f"{field}_event_id": wrong}
            return insert(conn, table, values)

        monkeypatch.setattr(participant_module, "_insert", inspect_insert)
        if family == "bundle":
            event = repository._event

            def wrong_bundle(*args, **kwargs):
                audit, outbox = event(*args, **kwargs)
                return (wrong, outbox) if field == "audit" else (audit, wrong)

            monkeypatch.setattr(repository, "_event", wrong_bundle)
            # Deliberately bypass only the Python precheck, so this probe reaches
            # the real SQL INSERT guard with malformed retained bundle evidence.
            monkeypatch.setattr(participant_module, "verify_inventory_backing", lambda *args: None)
        with _actor(connection, "checker") as principal:
            before = tuple(connection.iterdump())
            with pytest.raises(sqlite3.IntegrityError, match="receipt"):
                _commit(repository, plan, review, principal)
            assert attempted == ["finance_posting_effects"]
            assert tuple(connection.iterdump()) == before
            assert not connection.in_transaction
    finally:
        connection.close()


def test_reserved_draft_parent_refuses_ordinary_child_before_sealing(tmp_path: Path, monkeypatch) -> None:
    _path, connection, repository, request = _fixture(tmp_path)
    try:
        plan, review = _reviewed(connection, repository, request)
        original = participant_module._insert
        observed = []

        def insert(conn, table, values):
            original(conn, table, values)
            if table == "ledger_entries":
                assert (
                    conn.execute("SELECT status FROM ledger_entries WHERE id=?", (values["id"],)).fetchone()[0]
                    == "Draft"
                )
                with pytest.raises(sqlite3.IntegrityError, match="receipt"):
                    conn.execute(
                        "INSERT INTO ledger_lines(id,entry_id,line_number,account_id,debit_minor,credit_minor,created_at) VALUES('ordinary-child',?,3,?,1,0,?)",
                        (values["id"], plan["mapping"]["inventory_account_id"], values["created_at"]),
                    )
                observed.append("Draft child denied")

        monkeypatch.setattr(participant_module, "_insert", insert)
        with _actor(connection, "checker") as principal:
            _commit(repository, plan, review, principal)
        assert observed == ["Draft child denied"]
        verify_receipt_storage(connection)
    finally:
        connection.close()


@pytest.mark.parametrize("prefix", ["IRP1-", "irp1-", "IrP1-"])
def test_namespace_is_reserved_before_any_plan_exists(tmp_path: Path, prefix: str) -> None:
    _path, connection, _repository, request = _fixture(tmp_path)
    try:
        core = InventoryCoreService(connection)
        existing = core.create_movement(
            movement_number="ORDINARY-DRAFT",
            movement_type="Receipt",
            organization_code="SYN",
            entity_code="EG01",
            period_id=request.period_id,
            movement_date=request.posting_date,
            description="Existing ordinary draft",
            lines=[{"item_code": "MAT-01", "quantity": "10", "to_location": "MAIN/STOCK"}],
        )
        row = dict(connection.execute("SELECT * FROM inventory_movements WHERE id=?", (existing["id"],)).fetchone())
        before = tuple(connection.iterdump())
        with pytest.raises(sqlite3.IntegrityError, match="receipt"):
            receipt_module._insert(
                connection,
                "inventory_movements",
                {**row, "id": "unowned-candidate", "movement_number": prefix + "MOV-" + "a" * 32},
            )
        connection.rollback()
        assert tuple(connection.iterdump()) == before
        assert connection.execute("SELECT COUNT(*) FROM inventory_receipt_plans").fetchone()[0] == 0
    finally:
        connection.close()


@pytest.mark.parametrize("reverse_order", [False, True])
def test_same_date_fifo_respects_retained_movement_number_order(tmp_path: Path, reverse_order: bool) -> None:
    _path, connection, repository, request = _fixture(tmp_path)
    try:
        prepared = []
        for number in ("RECEIPT-A", "RECEIPT-B"):
            with _actor(connection, "maker") as principal:
                plan = repository.prepare_receipt(
                    replace(request, receipt_number=number),
                    command_id=f"prepare-{number}",
                    actor=_posting_actor(principal),
                )
            with _actor(connection, "checker") as principal:
                review = repository.review(
                    plan["plan_id"],
                    command_id=f"review-{number}",
                    expected_plan_digest=plan["plan_digest"],
                    reason="Independent chronology review",
                    actor=_posting_actor(principal),
                )
            prepared.append((plan, review))
        prepared.sort(key=lambda pair: pair[0]["artifacts"]["movement_number"], reverse=reverse_order)
        with _actor(connection, "checker") as principal:
            _commit(repository, *prepared[0], principal, "first")
            before = tuple(connection.iterdump())
            if reverse_order:
                with pytest.raises(ValueError, match="chronology"):
                    _commit(repository, *prepared[1], principal, "second")
                assert tuple(connection.iterdump()) == before
            else:
                _commit(repository, *prepared[1], principal, "second")
        assert connection.execute("SELECT COUNT(*) FROM finance_posting_effects").fetchone()[0] == (
            1 if reverse_order else 2
        )
        verify_receipt_storage(connection)
    finally:
        connection.close()


def _inverse_fixture(connection, repository, request):
    plan, review = _reviewed(connection, repository, request)
    with _actor(connection, "checker") as principal:
        _commit(repository, plan, review, principal, "original")
    with _actor(connection, "maker") as principal:
        inverse = repository.prepare_reversal(
            ReceiptReversalPreparation(
                original_plan_id=plan["plan_id"],
                reversal_number="RETURN-ALL",
                posting_date="2026-07-06",
                period_id=request.period_id,
                reason="Return unused original",
            ),
            command_id="prepare-inverse",
            actor=_posting_actor(principal),
        )
    with _actor(connection, "checker") as principal:
        reviewed = repository.review(
            inverse["plan_id"],
            command_id="review-inverse",
            expected_plan_digest=inverse["plan_digest"],
            reason="Full unused layer review",
            actor=_posting_actor(principal),
        )
    delivery = InventoryCoreService(connection).create_movement(
        movement_number="LATER-OUTBOUND",
        movement_type="Delivery",
        organization_code="SYN",
        entity_code="EG01",
        period_id=request.period_id,
        movement_date="2026-07-07",
        description="Actual competing physical consumer",
        lines=[{"item_code": "MAT-01", "quantity": "1", "from_location": "MAIN/STOCK"}],
    )
    return inverse, reviewed, str(delivery["id"]), principal


@pytest.mark.parametrize("inverse_first", [False, True])
def test_actual_writer_race_consumer_against_full_inverse(tmp_path: Path, monkeypatch, inverse_first: bool) -> None:
    path, connection, repository, request = _fixture(tmp_path)
    try:
        inverse, review, delivery_id, principal = _inverse_fixture(connection, repository, request)
        writer_holds, release, contender_started = Event(), Event(), Event()
        original = SQLiteInventoryReceiptPostingRepository._materialize_inventory

        def hold_inverse(self, *args):
            if inverse_first:
                writer_holds.set()
                assert release.wait(10)
            return original(self, *args)

        monkeypatch.setattr(SQLiteInventoryReceiptPostingRepository, "_materialize_inventory", hold_inverse)

        def run_inverse():
            with (
                connect(path, require_exists=True, busy_timeout_ms=15000) as conn,
                trusted_local_mode(False),
                server_principal_context(principal),
            ):
                if not inverse_first:
                    contender_started.set()
                return _commit(
                    SQLiteInventoryReceiptPostingRepository(conn), inverse, review, principal, "race-inverse"
                )

        def run_consumer():
            with connect(path, require_exists=True, busy_timeout_ms=15000) as conn:
                if inverse_first:
                    contender_started.set()
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    "UPDATE inventory_movements SET status='Posted',posted_by='checker',posted_at='2026-07-07T00:00:00Z',post_reason='Independent physical dispatch' WHERE id=?",
                    (delivery_id,),
                )
                if not inverse_first:
                    writer_holds.set()
                    assert release.wait(10)
                conn.commit()
                return "consumer posted"

        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(run_inverse if inverse_first else run_consumer)
            try:
                assert writer_holds.wait(10)
                second = pool.submit(run_consumer if inverse_first else run_inverse)
                assert contender_started.wait(10)
                with pytest.raises(FutureTimeout):
                    second.result(timeout=0.15)
            finally:
                release.set()
            first.result(timeout=15)
            with pytest.raises(
                sqlite3.IntegrityError if inverse_first else ValueError, match="receipt" if inverse_first else "unused"
            ):
                second.result(timeout=15)
        assert connection.execute("SELECT status FROM inventory_movements WHERE id=?", (delivery_id,)).fetchone()[
            0
        ] == ("Draft" if inverse_first else "Posted")
        assert connection.execute("SELECT COUNT(*) FROM finance_posting_effects").fetchone()[0] == (
            2 if inverse_first else 1
        )
        verify_receipt_storage(connection)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        connection.close()


def test_wal_backup_is_one_snapshot_during_second_actual_receipt(tmp_path: Path, monkeypatch) -> None:
    path, connection, repository, request = _fixture(tmp_path)
    try:
        plan, review = _reviewed(connection, repository, request)
        with _actor(connection, "checker") as principal:
            _commit(repository, plan, review, principal, "original")
        with _actor(connection, "maker") as principal:
            next_plan = repository.prepare_receipt(
                replace(request, receipt_number="SECOND", posting_date="2026-07-06"),
                command_id="prepare-second",
                actor=_posting_actor(principal),
            )
        with _actor(connection, "checker") as principal:
            next_review = repository.review(
                next_plan["plan_id"],
                command_id="review-second",
                expected_plan_digest=next_plan["plan_digest"],
                reason="Second independent receipt",
                actor=_posting_actor(principal),
            )
        original = backup_module._table_rows
        observed = []

        def table_rows(snapshot, table):
            rows = original(snapshot, table)
            if not observed:
                observed.append(table)
                assert snapshot.in_transaction
                with trusted_local_mode(False), server_principal_context(principal):
                    _commit(repository, next_plan, next_review, principal, "second")
            return rows

        monkeypatch.setattr(backup_module, "_table_rows", table_rows)
        backup = create_backup(path, tmp_path / "wal-backup")
        payload = json.loads(backup.backup_path.read_text(encoding="utf-8"))
        assert len(payload["tables"]["inventory_receipt_plans"]) == 2
        assert len(payload["tables"]["inventory_receipt_links"]) == 1
        assert len(payload["tables"]["finance_posting_effects"]) == 1
        assert connection.execute("SELECT COUNT(*) FROM finance_posting_effects").fetchone()[0] == 2
        target = tmp_path / "wal-restored.db"
        restore_backup(target, backup.backup_path)
        with connect(target, require_exists=True) as restored:
            verify_receipt_storage(restored)
            verify_posting_storage(restored)
            assert restored.execute("SELECT COUNT(*) FROM finance_posting_effects").fetchone()[0] == 1
    finally:
        connection.close()


def test_raw_draft_line_cannot_enter_posted_outbound_after_full_inverse(tmp_path: Path) -> None:
    _path, connection, repository, request = _fixture(tmp_path)
    try:
        inverse, review, delivery_id, principal = _inverse_fixture(connection, repository, request)
        with trusted_local_mode(False), server_principal_context(principal):
            _commit(repository, inverse, review, principal, "complete-inverse")
        # The inherited schema allows an empty Posted header to be inserted.
        # Its lack of lines has no stock effect, until a Draft line is moved in.
        header = dict(connection.execute("SELECT * FROM inventory_movements WHERE id=?", (delivery_id,)).fetchone())
        receipt_module._insert(
            connection,
            "inventory_movements",
            {
                **header,
                "id": "ordinary-empty-posted",
                "movement_number": "EMPTY-POSTED",
                "status": "Posted",
                "posted_by": "checker",
                "posted_at": "2026-07-07T00:00:00Z",
                "post_reason": "Raw header probe",
            },
        )
        connection.commit()
        before = tuple(connection.iterdump())
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE inventory_movement_lines SET movement_id='ordinary-empty-posted' WHERE movement_id=?",
                (delivery_id,),
            )
        connection.rollback()
        assert tuple(connection.iterdump()) == before
    finally:
        connection.close()


@pytest.mark.parametrize(("currency", "precision"), [("JPY", 0), ("KWD", 3)])
def test_actual_receipt_captures_zero_and_three_decimal_policy(tmp_path: Path, currency: str, precision: int) -> None:
    _path, connection, repository, request = _fixture(tmp_path)
    try:
        master = MasterDataService(connection)
        master.upsert_currency(code=currency, name="Synthetic functional currency", minor_units=precision)
        master.upsert_legal_entity(
            organization_code="SYN", entity_code=currency, name="Synthetic entity", currency_code=currency
        )
        FinanceCoreService(connection).upsert_journal(
            journal_code="INV" + currency,
            name="Inventory valuation",
            organization_code="SYN",
            currency_code=currency,
            journal_type="Adjustment",
        )
        InventoryValuationService(connection).upsert_policy(
            policy_code="FIFO" + currency,
            organization_code="SYN",
            entity_code=currency,
            journal_code="INV" + currency,
            receipt_clearing_account_code="2100",
            cogs_account_code="5100",
            adjustment_account_code="5190",
        )
        inventory = InventoryCoreService(connection)
        inventory.upsert_warehouse(
            warehouse_code=currency, name="Currency-scoped warehouse", organization_code="SYN", entity_code=currency
        )
        inventory.upsert_location(
            warehouse_code=currency, location_code="STOCK", name="Currency-scoped stock", organization_code="SYN"
        )
        request = replace(
            request, entity_code=currency, policy_code="FIFO" + currency, location_code=currency + "/STOCK"
        )
        plan, review = _reviewed(connection, repository, request)
        with _actor(connection, "checker") as principal:
            effect = _commit(repository, plan, review, principal)
        assert plan["currency_policy"]["currency_precision"] == precision
        assert effect["finance_effect"]["currency_code"] == currency
        assert effect["finance_effect"]["currency_precision"] == precision
        assert [
            (line["debit_minor"], line["credit_minor"]) for line in effect["finance_effect"]["snapshot"]["lines"]
        ] == [(12000, 0), (0, 12000)]
        verify_receipt_storage(connection)
    finally:
        connection.close()


def test_current_admission_and_retained_read_replay_are_separate(tmp_path: Path) -> None:
    _path, connection, repository, request = _fixture(tmp_path)
    try:
        plan, review = _reviewed(connection, repository, request)
        with _actor(connection, "checker") as principal:
            effect = _commit(repository, plan, review, principal)
        # Trusted fixture administration changes current admission only; retained
        # evidence remains interpreted through its captured policy and mapping.
        connection.execute("UPDATE periods SET status='Closed' WHERE id=?", (request.period_id,))
        connection.execute("UPDATE inventory_locations SET active=0")
        connection.commit()
        with _actor(connection, "checker") as principal:
            before = tuple(connection.iterdump())
            assert _commit(repository, plan, review, principal) == effect
            assert repository.get_effect(plan["plan_id"], actor=_posting_actor(principal)) == effect
            assert tuple(connection.iterdump()) == before
        with _actor(connection, "maker") as principal:
            assert repository.prepare_receipt(request, command_id="prepare-10", actor=_posting_actor(principal)) == plan
            before = tuple(connection.iterdump())
            with pytest.raises(ValueError):
                repository.prepare_receipt(
                    replace(request, receipt_number="NEW-INACTIVE"),
                    command_id="new-inactive",
                    actor=_posting_actor(principal),
                )
            assert tuple(connection.iterdump()) == before
        verify_receipt_storage(connection)
    finally:
        connection.close()


def test_corrupted_command_digest_refuses_backup_before_publication(tmp_path: Path) -> None:
    path, connection, repository, request = _fixture(tmp_path)
    try:
        plan, review = _reviewed(connection, repository, request)
        with _actor(connection, "checker") as principal:
            _commit(repository, plan, review, principal)
        # Simulate damaged storage only in this disposable fixture. Normal raw
        # command UPDATE is first proved immutable before its guard is removed.
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE inventory_receipt_commands SET request_digest=? WHERE operation='commit'", ("0" * 64,)
            )
        connection.rollback()
        triggers = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='inventory_receipt_commands' AND sql LIKE '%BEFORE UPDATE%'"
        ).fetchall()
        assert triggers
        for row in triggers:
            connection.execute('DROP TRIGGER "' + row[0] + '"')
        connection.execute(
            "UPDATE inventory_receipt_commands SET request_digest=? WHERE operation='commit'", ("0" * 64,)
        )
        connection.commit()
        destination = tmp_path / "corrupt-backup"
        with pytest.raises(DBBridgeError):
            create_backup(path, destination)
        assert not (destination / "backup.json").exists()
        assert not (destination / "manifest.json").exists()
    finally:
        connection.close()


def test_allow_negative_location_refused_before_preparation(tmp_path: Path) -> None:
    _path, connection, repository, request = _fixture(tmp_path)
    try:
        connection.execute("UPDATE inventory_locations SET allow_negative=1")
        connection.commit()
        with _actor(connection, "maker") as principal:
            before = tuple(connection.iterdump())
            with pytest.raises(ValueError, match="Internal location"):
                repository.prepare_receipt(request, command_id="negative-location", actor=_posting_actor(principal))
            assert tuple(connection.iterdump()) == before
    finally:
        connection.close()


def test_registry_rebind_refuses_stale_review_but_preserves_posted_read_and_replay(tmp_path: Path) -> None:
    _path, connection, repository, request = _fixture(tmp_path)
    try:
        plan, review = _reviewed(connection, repository, request)
        with _actor(connection, "checker") as principal:
            effect = _commit(repository, plan, review, principal)
        with _actor(connection, "maker") as principal:
            future = repository.prepare_receipt(
                replace(request, receipt_number="FUTURE", posting_date="2026-07-06"),
                command_id="future-prepare",
                actor=_posting_actor(principal),
            )
        with _actor(connection, "checker") as principal:
            future_review = repository.review(
                future["plan_id"],
                command_id="future-review",
                expected_plan_digest=future["plan_digest"],
                reason="Independent future review",
                actor=_posting_actor(principal),
            )
        snapshot = json.loads(
            connection.execute(
                "SELECT snapshot_json FROM currency_registry_snapshots WHERE registry_digest=?",
                (plan["currency_policy"]["currency_registry_digest"],),
            ).fetchone()[0]
        )
        snapshot["source"] = "Synthetic changed policy provenance"
        snapshot.pop("digest", None)
        context = CurrencyRegistryContext.from_snapshot(snapshot)
        digest = context.registry_manifest.digest
        version = context.registry_manifest.registry_version
        connection.execute(
            "INSERT INTO currency_registry_snapshots(registry_digest,registry_version,snapshot_json,captured_at,captured_by) VALUES(?,?,?,'2026-10-03','synthetic')",
            (digest, version, json.dumps(context.snapshot(), sort_keys=True, separators=(",", ":"))),
        )
        connection.execute(
            "INSERT INTO currency_registry_bindings(workspace_id,registry_version,registry_digest,bound_at,bound_by) "
            "VALUES(?,?,?,'2026-10-03','synthetic') ON CONFLICT(workspace_id) DO UPDATE SET "
            "registry_digest=excluded.registry_digest,registry_version=excluded.registry_version",
            (plan["scope"]["workspace_id"], version, digest),
        )
        connection.commit()
        with _actor(connection, "checker") as principal:
            before = tuple(connection.iterdump())
            assert _commit(repository, plan, review, principal) == effect
            assert repository.get_effect(plan["plan_id"], actor=_posting_actor(principal)) == effect
            with pytest.raises(ValueError, match="policy changed"):
                _commit(repository, future, future_review, principal, "future-commit")
            assert tuple(connection.iterdump()) == before
        verify_receipt_storage(connection)
    finally:
        connection.close()
