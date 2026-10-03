"""Actual human-reviewed physical/valuation/operational receipt boundaries."""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from reconforge.db import connect, run_migrations
from reconforge.db.backup import create_backup, restore_backup
from reconforge.domain.inventory_receipt_posting import ReceiptPreparation, ReceiptReversalPreparation
from reconforge.infrastructure.sqlite_finance_posting import SQLiteFinancePostingRepository, verify_posting_storage
from reconforge.infrastructure.sqlite_inventory_receipt_posting import (
    SQLiteInventoryReceiptPostingRepository,
    verify_receipt_storage,
)
from reconforge.infrastructure.sqlite_inventory_unit_of_work import SQLiteInventoryUnitOfWork
from reconforge.platform.common import PlatformError, server_principal_context
from tests.test_inventory_valuation import _seed
from tests.test_sqlite_finance_posting import _actor, _posting_actor, _seed_actors


def _fixture(tmp_path: Path):
    path = tmp_path / "reviewed_receipt.db"
    run_migrations(path)
    connection = connect(path, require_exists=True)
    _inventory, _valuation, period = _seed(connection)
    _seed_actors(connection)
    repository = SQLiteInventoryReceiptPostingRepository(connection)
    request = ReceiptPreparation(
        receipt_number="REC-10",
        posting_date="2026-07-05",
        period_id=str(period["id"]),
        item_code="MAT-01",
        location_code="MAIN/STOCK",
        quantity="10",
        total_value_minor=12000,
        policy_code="FIFO",
        organization_code="SYN",
        entity_code="EG01",
        reason="Synthetic received stock",
    )
    return path, connection, repository, request


def _reviewed(connection, repository, request):
    with _actor(connection, "maker") as principal:
        plan = repository.prepare_receipt(request, command_id="prepare-10", actor=_posting_actor(principal))
    with _actor(connection, "checker") as principal:
        review = repository.review(
            plan["plan_id"],
            command_id="review-10",
            expected_plan_digest=plan["plan_digest"],
            reason="Count and cost independently checked",
            actor=_posting_actor(principal),
        )
    return plan, review


def test_actual_receipt_ten_value_12000_and_full_unused_inverse(tmp_path: Path) -> None:
    _path, connection, repository, request = _fixture(tmp_path)
    try:
        plan, review = _reviewed(connection, repository, request)
        with _actor(connection, "checker") as principal:
            checker = _posting_actor(principal)
            effect = repository.commit(
                plan["plan_id"],
                command_id="commit-10",
                expected_review_digest=review["review_digest"],
                reason="Explicit reviewed receipt posting",
                actor=checker,
            )
            before = tuple(
                connection.execute(
                    "SELECT (SELECT COUNT(*) FROM audit_events),(SELECT COUNT(*) FROM outbox_events)"
                ).fetchone()
            )
            assert (
                repository.commit(
                    plan["plan_id"],
                    command_id="commit-10",
                    expected_review_digest=review["review_digest"],
                    reason="Explicit reviewed receipt posting",
                    actor=checker,
                )
                == effect
            )
            assert (
                tuple(
                    connection.execute(
                        "SELECT (SELECT COUNT(*) FROM audit_events),(SELECT COUNT(*) FROM outbox_events)"
                    ).fetchone()
                )
                == before
            )
            assert repository.get_effect(plan["plan_id"], actor=checker) == effect
        layer = connection.execute(
            "SELECT * FROM inventory_cost_layers WHERE id=?", (plan["artifacts"]["cost_layer_id"],)
        ).fetchone()
        assert (layer["original_quantity_scaled"], layer["remaining_quantity_scaled"], layer["quantity_precision"]) == (
            10000,
            10000,
            3,
        )
        assert (layer["original_value_minor"], layer["remaining_value_minor"]) == (12000, 12000)
        assert (
            connection.execute(
                "SELECT status FROM inventory_movements WHERE id=?", (effect["movement_id"],)
            ).fetchone()[0]
            == "Posted"
        )
        assert (
            connection.execute(
                "SELECT status FROM inventory_valuation_documents WHERE id=?", (effect["valuation_document_id"],)
            ).fetchone()[0]
            == "Approved"
        )
        assert (
            connection.execute("SELECT status FROM ledger_entries WHERE id=?", (effect["entry_id"],)).fetchone()[0]
            == "Validated"
        )
        assert effect["finance_effect"]["source_kind"] == "InventoryReceipt"
        assert [
            (line["debit_minor"], line["credit_minor"]) for line in effect["finance_effect"]["snapshot"]["lines"]
        ] == [(12000, 0), (0, 12000)]
        inverse_request = ReceiptReversalPreparation(
            original_plan_id=plan["plan_id"],
            reversal_number="RETURN-10",
            posting_date="2026-07-06",
            period_id=request.period_id,
            reason="Return all unused stock",
        )
        with _actor(connection, "maker") as principal:
            inverse_plan = repository.prepare_reversal(
                inverse_request, command_id="prepare-inverse", actor=_posting_actor(principal)
            )
        with _actor(connection, "checker") as principal:
            checker = _posting_actor(principal)
            inverse_review = repository.review(
                inverse_plan["plan_id"],
                command_id="review-inverse",
                expected_plan_digest=inverse_plan["plan_digest"],
                reason="Original remains unused",
                actor=checker,
            )
            inverse = repository.commit(
                inverse_plan["plan_id"],
                command_id="commit-inverse",
                expected_review_digest=inverse_review["review_digest"],
                reason="Post complete original inverse",
                actor=checker,
            )
            assert inverse["reverses_effect_id"] == effect["effect_id"]
            assert repository.get_effect(plan["plan_id"], actor=checker) == effect
        assert tuple(
            connection.execute(
                "SELECT remaining_quantity_scaled,remaining_value_minor FROM inventory_cost_layers WHERE id=?",
                (layer["id"],),
            ).fetchone()
        ) == (0, 0)
        assert tuple(connection.execute("SELECT SUM(debit_minor),SUM(credit_minor) FROM ledger_lines").fetchone()) == (
            24000,
            24000,
        )
        assert all(
            row[0] == 0
            for row in connection.execute(
                "SELECT SUM(debit_minor)-SUM(credit_minor) FROM ledger_lines GROUP BY account_id"
            )
        )
        verify_posting_storage(connection)
        verify_receipt_storage(connection)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        backup = create_backup(_path, tmp_path / "receipt-backup")
        restored_path = tmp_path / "restored-receipt.db"
        restore_backup(restored_path, backup.backup_path)
        with connect(restored_path, require_exists=True) as restored:
            restored_repository = SQLiteInventoryReceiptPostingRepository(restored)
            with _actor(restored, "checker") as principal:
                restored_checker = _posting_actor(principal)
                assert restored_repository.get_effect(plan["plan_id"], actor=restored_checker) == effect
                assert restored_repository.get_effect(inverse_plan["plan_id"], actor=restored_checker) == inverse
            for table in (
                "inventory_receipt_plans",
                "inventory_receipt_reviews",
                "inventory_receipt_links",
                "inventory_receipt_commands",
                "finance_posting_effects",
            ):
                assert [tuple(row) for row in restored.execute(f"SELECT * FROM {table} ORDER BY 1")] == [
                    tuple(row) for row in connection.execute(f"SELECT * FROM {table} ORDER BY 1")
                ]
            assert restored.execute("PRAGMA foreign_keys").fetchone()[0] == 1
            assert restored.execute("PRAGMA foreign_key_check").fetchall() == []
            with pytest.raises(sqlite3.IntegrityError):
                restored.execute("UPDATE inventory_movements SET status='Voided' WHERE id=?", (effect["movement_id"],))
            restored.rollback()
    finally:
        connection.close()


def test_raw_complete_link_without_outputs_cannot_commit(tmp_path: Path) -> None:
    from reconforge.infrastructure.sqlite_inventory_receipt_posting import _insert

    _path, connection, repository, request = _fixture(tmp_path)
    try:
        plan, review = _reviewed(connection, repository, request)
        with _actor(connection, "checker") as principal:
            actor = _posting_actor(principal)
            before = tuple(connection.iterdump())
            connection.execute("BEGIN IMMEDIATE")
            audit, outbox = repository._event(
                plan["plan_id"],
                "inventory_receipt_committed",
                actor,
                {
                    "plan_digest": plan["plan_digest"],
                    "review_digest": review["review_digest"],
                    "finance_validation_digest": plan["finance_validation_digest"],
                    "effect_id": plan["artifacts"]["posting_effect_id"],
                },
            )
            link = {
                "id": plan["plan_id"],
                "plan_id": plan["plan_id"],
                "review_id": review["review_id"],
                **{key: plan["scope"][key] for key in ("workspace_id", "organization_id", "legal_entity_id")},
                "plan_digest": plan["plan_digest"],
                "review_digest": review["review_digest"],
                **{key: value for key, value in plan["artifacts"].items() if not key.endswith("_number")},
                "original_plan_id": None,
                "original_posting_effect_id": None,
                "posted_actor_id": actor.user_id,
                "posted_at": "2026-10-03T00:00:00Z",
                "reason": "Incomplete raw source probe",
                "audit_event_id": audit,
                "outbox_event_id": outbox,
            }
            _insert(connection, "inventory_receipt_links", link)
            with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
                connection.commit()
            connection.rollback()
            assert tuple(connection.iterdump()) == before
    finally:
        connection.close()


def test_raw_mutation_after_effect_and_unowned_child_are_denied(tmp_path: Path, monkeypatch) -> None:
    _path, connection, repository, request = _fixture(tmp_path)
    try:
        plan, review = _reviewed(connection, repository, request)
        original_command = repository._command
        observed = []

        def attempt_bypass(*args, **kwargs):
            for sql, parameters in (
                ("UPDATE inventory_movements SET status='Voided' WHERE id=?", (plan["artifacts"]["movement_id"],)),
                (
                    "UPDATE inventory_valuation_documents SET total_value_minor=1 WHERE id=?",
                    (plan["artifacts"]["valuation_document_id"],),
                ),
                (
                    "UPDATE ledger_entries SET description='changed after sealed effect' WHERE id=?",
                    (plan["artifacts"]["finance_entry_id"],),
                ),
                ("UPDATE inventory_receipt_links SET posted_actor_id='other' WHERE id=?", (plan["plan_id"],)),
                (
                    "INSERT INTO ledger_lines(id,entry_id,line_number,account_id,debit_minor,credit_minor,created_at) VALUES('ordinary-child',?,3,?,1,0,'2026-10-03T00:00:00Z')",
                    (plan["artifacts"]["finance_entry_id"], plan["mapping"]["inventory_account_id"]),
                ),
            ):
                with pytest.raises(sqlite3.IntegrityError):
                    connection.execute(sql, parameters)
                observed.append(sql)
            return original_command(*args, **kwargs)

        monkeypatch.setattr(repository, "_command", attempt_bypass)
        with _actor(connection, "checker") as principal:
            repository.commit(
                plan["plan_id"],
                command_id="raw-after-effect",
                expected_review_digest=review["review_digest"],
                reason="Guarded commit",
                actor=_posting_actor(principal),
            )
        assert len(observed) == 5
        verify_receipt_storage(connection)
        verify_posting_storage(connection)
    finally:
        connection.close()


@pytest.mark.parametrize("phase", ["finance_draft", "effect_insert", "command_insert"])
def test_python_failure_rolls_back_every_owned_record(tmp_path: Path, monkeypatch, phase: str) -> None:
    import reconforge.infrastructure.sqlite_inventory_receipt_finance as participant_module
    import reconforge.infrastructure.sqlite_inventory_receipt_posting as receipt_module

    _path, connection, repository, request = _fixture(tmp_path)
    try:
        plan, review = _reviewed(connection, repository, request)
        with _actor(connection, "checker") as principal:
            before = tuple(connection.iterdump())
            module = receipt_module if phase == "command_insert" else participant_module
            original = module._insert
            observed = []

            def fail_late(conn, table, values):
                original(conn, table, values)
                wanted = {
                    "finance_draft": "ledger_lines",
                    "effect_insert": "finance_posting_effects",
                    "command_insert": "inventory_receipt_commands",
                }[phase]
                if table == wanted:
                    observed.append(table)
                    raise RuntimeError("synthetic Python child failure after persisted write")

            monkeypatch.setattr(module, "_insert", fail_late)
            with pytest.raises(PlatformError, match="entire inventory"), SQLiteInventoryUnitOfWork(connection) as owner:
                bound = SQLiteInventoryReceiptPostingRepository(connection, unit_of_work=owner)
                with pytest.raises(RuntimeError, match="Python child"):
                    bound.commit(
                        plan["plan_id"],
                        command_id="fault",
                        expected_review_digest=review["review_digest"],
                        reason="Failure atomicity probe",
                        actor=_posting_actor(principal),
                    )
                assert owner.rollback_only is True
                assert connection.in_transaction is True
            assert observed
            assert tuple(connection.iterdump()) == before
            assert not connection.in_transaction
    finally:
        connection.close()


def test_verified_identity_sod_and_cached_current_authority(tmp_path: Path) -> None:
    _path, connection, repository, request = _fixture(tmp_path)
    try:
        plan, review = _reviewed(connection, repository, request)
        with _actor(connection, "maker") as principal, pytest.raises(ValueError, match="stable preparer"):
            repository.commit(
                plan["plan_id"],
                command_id="own-post",
                expected_review_digest=review["review_digest"],
                reason="Forbidden maker post",
                actor=_posting_actor(principal),
            )
        with _actor(connection, "checker") as principal:
            actor = _posting_actor(principal)
            effect = repository.commit(
                plan["plan_id"],
                command_id="valid",
                expected_review_digest=review["review_digest"],
                reason="Approved",
                actor=actor,
            )
            with (
                server_principal_context(replace(principal, permissions=principal.permissions - {"finance_core.post"})),
                pytest.raises(ValueError, match="permission"),
            ):
                repository.commit(
                    plan["plan_id"],
                    command_id="valid",
                    expected_review_digest=review["review_digest"],
                    reason="Approved",
                    actor=actor,
                )
            with (
                server_principal_context(replace(principal, principal_type="service_account")),
                pytest.raises(ValueError, match="human"),
            ):
                repository.commit(
                    plan["plan_id"],
                    command_id="valid",
                    expected_review_digest=review["review_digest"],
                    reason="Approved",
                    actor=actor,
                )
            with (
                server_principal_context(replace(principal, authorized_legal_entity_ids=frozenset({"SIBLING-ONLY"}))),
                pytest.raises(ValueError, match="scope"),
            ):
                repository.get_effect(plan["plan_id"], actor=actor)
            with pytest.raises(ValueError, match="complete"):
                SQLiteFinancePostingRepository(connection).post(
                    effect["entry_id"],
                    command_id="generic",
                    expected_validation_digest=plan["finance_validation_digest"],
                    reason="Bypass",
                    actor=actor,
                )
            with pytest.raises(ValueError, match="complete unused"):
                SQLiteFinancePostingRepository(connection).prepare_reversal(
                    effect["effect_id"],
                    command_id="generic-inverse",
                    entry_number="OTHER",
                    period_id=request.period_id,
                    posting_date=request.posting_date,
                    reason="Bypass",
                    actor=actor,
                )
        with pytest.raises(ValueError, match="bound human"):
            repository.get_effect(plan["plan_id"], actor=actor)
        verify_posting_storage(connection)
    finally:
        connection.close()


def test_foreign_keys_off_and_pending_work_refused_without_changing_caller(tmp_path: Path) -> None:
    _path, connection, repository, request = _fixture(tmp_path)
    try:
        with _actor(connection, "maker") as principal:
            actor = _posting_actor(principal)
            connection.execute("PRAGMA foreign_keys=OFF")
            before = tuple(connection.iterdump())
            with pytest.raises(ValueError, match="foreign_keys=ON"):
                repository.prepare_receipt(request, command_id="fk-off", actor=actor)
            assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 0
            assert tuple(connection.iterdump()) == before
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("UPDATE users SET display_name='pending caller change' WHERE id=?", (actor.user_id,))
            pending = tuple(connection.iterdump())
            with pytest.raises(PlatformError, match="pending caller"):
                repository.prepare_receipt(request, command_id="dirty", actor=actor)
            assert connection.in_transaction
            assert tuple(connection.iterdump()) == pending
            connection.rollback()
    finally:
        connection.close()
