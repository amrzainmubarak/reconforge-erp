"""SQLite operational posting invariants and actual transaction ownership."""

from __future__ import annotations

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from threading import Barrier, Event

import pytest

import reconforge.db.exporter as exporter_module
from reconforge.audit import AuditLedgerError
from reconforge.auth import LocalAuthService
from reconforge.db import connect, run_migrations
from reconforge.db.backup import create_backup, restore_backup
from reconforge.db.exporter import DBBridgeError, checksum_file, export_database
from reconforge.domain.finance_posting import FinancePostingError, PostingActor, canonical_json, digest_payload
from reconforge.infrastructure.sqlite_finance_posting import (
    SQLiteFinancePostingRepository,
    SQLiteFinancePostingUnitOfWork,
)
from reconforge.io.finance_posting import decode_posting_receipt
from reconforge.io.persisted import PersistedJsonError
from reconforge.platform.common import PlatformError, ServerPrincipal, server_principal_context, trusted_local_mode
from tests.test_finance_core import _create_entry, _seed_finance_model


@contextmanager
def _actor(connection: sqlite3.Connection, username: str):
    auth = LocalAuthService(connection)
    user = auth.authenticate_user(username=username, password="Synthetic-posting-password-123")
    assert user is not None
    principal = ServerPrincipal(
        user=user, permissions=frozenset(auth.roles.user_permissions(username)), step_up_active=True
    )
    with trusted_local_mode(False), server_principal_context(principal):
        yield principal


def _seed_actors(connection: sqlite3.Connection) -> None:
    auth = LocalAuthService(connection)
    auth.init_admin(username="maker", password="Synthetic-posting-password-123")
    auth.create_user(username="checker", password="Synthetic-posting-password-123", role="admin")


def _posting_actor(principal: ServerPrincipal) -> PostingActor:
    return PostingActor(principal.user.id, principal.user.username, principal.permissions, step_up_active=True)


def _reviewed(connection: sqlite3.Connection):
    finance, period = _seed_finance_model(connection)
    _seed_actors(connection)
    with _actor(connection, "maker") as maker:
        draft = _create_entry(finance, period, actor="maker")
    with _actor(connection, "checker") as checker:
        finance.validate_entry(str(draft["id"]), reason="Independent synthetic review", actor_label="checker")
    repository = SQLiteFinancePostingRepository(connection)
    preview = repository.preview(draft["id"], actor=_posting_actor(checker))
    return finance, period, repository, preview, _posting_actor(maker), _posting_actor(checker)


def _post(repository, preview, checker, command="post-1"):
    return repository.post(
        preview["entry_id"],
        command_id=command,
        expected_validation_digest=preview["validation_digest"],
        reason="Explicit synthetic posting",
        actor=checker,
    )


def test_review_post_lost_ack_replay_and_full_reversal_preserve_turnover(tmp_path: Path) -> None:
    path = tmp_path / "posting.db"
    run_migrations(path)
    with connect(path, require_exists=True) as connection:
        finance, period, repository, preview, maker, checker = _reviewed(connection)
        assert preview["validation_digest"] == preview["current_content_digest"]
        assert preview["preparer_actor_id"] == maker.user_id
        trial_args = dict(period_id=period["id"], organization_code="SYN", entity_code="EG01", actor=checker)
        assert repository.posted_trial_balance(**trial_args)["effect_count"] == 0
        effect = _post(repository, preview, checker)
        evidence = tuple(
            connection.execute(
                "SELECT (SELECT COUNT(*) FROM audit_events),(SELECT COUNT(*) FROM outbox_events)"
            ).fetchone()
        )
        assert _post(repository, preview, checker) == effect
        assert (
            tuple(
                connection.execute(
                    "SELECT (SELECT COUNT(*) FROM audit_events),(SELECT COUNT(*) FROM outbox_events)"
                ).fetchone()
            )
            == evidence
        )
        with pytest.raises(FinancePostingError, match="different content"):
            repository.post(
                preview["entry_id"],
                command_id="post-1",
                expected_validation_digest=preview["validation_digest"],
                reason="Changed retry",
                actor=checker,
            )
        with pytest.raises(FinancePostingError, match="committed operational effect"):
            _post(repository, preview, checker, "different-source-key")
        with pytest.raises(PlatformError):
            finance.void_entry(preview["entry_id"], reason="Forbidden old void")
        reversal = repository.prepare_reversal(
            effect["id"],
            command_id="reverse-1",
            entry_number="REV-1",
            period_id=period["id"],
            posting_date="2026-07-06",
            reason="Full synthetic correction",
            actor=maker,
        )
        assert (
            repository.prepare_reversal(
                effect["id"],
                command_id="reverse-1",
                entry_number="REV-1",
                period_id=period["id"],
                posting_date="2026-07-06",
                reason="Full synthetic correction",
                actor=maker,
            )
            == reversal
        )
        with _actor(connection, "checker"):
            finance.validate_entry(reversal["entry_id"], reason="Independent reversal review", actor_label="checker")
        reverse_preview = repository.preview(reversal["entry_id"], actor=checker)
        inverse = _post(repository, reverse_preview, checker, "post-reversal")
        assert inverse["reverses_effect_id"] == effect["id"]
        with pytest.raises(FinancePostingError) as revoked:
            _post(
                repository,
                reverse_preview,
                replace(checker, permissions=checker.permissions - {"finance_core.reverse"}),
                "post-reversal",
            )
        assert revoked.value.code == "posting_permission_denied"
        assert repository.get_effect(effect["id"], actor=checker) == effect
        trial = repository.posted_trial_balance(**trial_args)
        assert trial["effect_count"] == 2
        assert trial["totals"] == {"debit_minor": 200000, "credit_minor": 200000, "balanced": True}
        assert trial["balance_totals"] == {"debit_minor": 0, "credit_minor": 0, "balanced": True}
        assert all(account["balance_minor"] == 0 and len(account["postings"]) == 2 for account in trial["accounts"])


def test_preparer_is_stable_across_replacement_and_hidden_from_legacy_projection(tmp_path: Path) -> None:
    path = tmp_path / "posting.db"
    run_migrations(path)
    with connect(path, require_exists=True) as connection:
        finance, period = _seed_finance_model(connection)
        _seed_actors(connection)
        with _actor(connection, "maker") as maker:
            draft = _create_entry(finance, period, actor="maker")
        with _actor(connection, "maker"):
            replacement = _create_entry(finance, period, actor="maker")
        with _actor(connection, "checker"):
            with pytest.raises(PlatformError, match="preparer"):
                _create_entry(finance, period, actor="checker")
            listed = finance.list_entries(actor_label="checker")
        assert (
            connection.execute("SELECT preparer_actor_id FROM ledger_entries WHERE id=?", (draft["id"],)).fetchone()[0]
            == maker.user.id
        )
        for record in (draft, replacement, listed[0]):
            assert not set(record) & {
                "preparer_actor_id",
                "validator_actor_id",
                "validation_digest",
                "validation_contract_version",
                "reverses_posting_id",
            }
        anonymous = _create_entry(finance, period, number="ANONYMOUS")
        with _actor(connection, "maker"):
            _create_entry(finance, period, number="ANONYMOUS", actor="maker")
        assert (
            connection.execute(
                "SELECT preparer_actor_id FROM ledger_entries WHERE id=?", (anonymous["id"],)
            ).fetchone()[0]
            is None
        )


def test_export_and_backup_refuse_corrupt_posting_evidence_before_publication(tmp_path: Path) -> None:
    path = tmp_path / "posting.db"
    run_migrations(path)
    with connect(path, require_exists=True) as connection:
        _, _, repository, preview, _, checker = _reviewed(connection)
        effect = _post(repository, preview, checker)
    exported = export_database(path, tmp_path / "valid-export")
    finance = json.loads((exported.output_dir / "finance_workflows.json").read_text(encoding="utf-8"))
    assert finance["finance_posting_effects"][0]["snapshot"] == effect["snapshot"]
    assert finance["finance_posting_commands"][0]["result"] == effect
    with connect(path, require_exists=True) as connection:
        trigger = connection.execute(
            "SELECT sql FROM sqlite_master WHERE name='finance_posting_effect_update_immutable'"
        ).fetchone()[0]
        connection.execute("DROP TRIGGER finance_posting_effect_update_immutable")
        connection.execute("UPDATE finance_posting_effects SET snapshot_json=?", ('{"duplicate":1,"duplicate":2}',))
        connection.execute(trigger)
        connection.commit()
    for operation, output in (
        (export_database, tmp_path / "corrupt-export"),
        (create_backup, tmp_path / "corrupt-backup"),
    ):
        with pytest.raises(DBBridgeError):
            operation(path, output)
        assert not output.exists()


def test_restore_rejects_rechecksummed_financial_snapshot_tampering(tmp_path: Path) -> None:
    path = tmp_path / "posting.db"
    run_migrations(path)
    with connect(path, require_exists=True) as connection:
        _, _, repository, preview, _, checker = _reviewed(connection)
        _post(repository, preview, checker)
    backup = create_backup(path, tmp_path / "backup")
    data = json.loads(backup.backup_path.read_text(encoding="utf-8"))
    snapshot = json.loads(data["tables"]["finance_posting_effects"][0]["snapshot_json"])
    snapshot["lines"][0]["debit_minor"] += 1
    data["tables"]["finance_posting_effects"][0]["snapshot_json"] = canonical_json(snapshot)
    backup.backup_path.write_text(json.dumps(data), encoding="utf-8")
    manifest = json.loads(backup.manifest_path.read_text(encoding="utf-8"))
    manifest["artifacts"]["backup.json"]["sha256"] = checksum_file(backup.backup_path)
    manifest["artifacts"]["backup.json"]["bytes"] = backup.backup_path.stat().st_size
    backup.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    destination = tmp_path / "rejected.db"
    with pytest.raises(DBBridgeError):
        restore_backup(destination, backup.backup_path)
    assert not destination.exists()
    assert not destination.with_name("rejected.restore_tmp.db").exists()


@pytest.mark.parametrize(
    "raw", ['{"x":1,"x":2}', '{"amount":1.25}', '{"x":NaN}', "[]", b"{}", '{"x":' + "[" * 15 + "0" + "]" * 15 + "}"]
)
def test_posting_json_is_bounded_and_exact(raw: object) -> None:
    with pytest.raises(PersistedJsonError):
        decode_posting_receipt(raw)


def test_raw_effect_snapshot_cannot_replace_nullable_field_or_change_amount(tmp_path: Path) -> None:
    path = tmp_path / "posting.db"
    run_migrations(path)
    with connect(path, require_exists=True) as connection:
        finance, period, repository, preview, _, checker = _reviewed(connection)
        original = _post(repository, preview, checker)
        with _actor(connection, "maker"):
            other = _create_entry(finance, period, number="OTHER", actor="maker")
        with _actor(connection, "checker"):
            finance.validate_entry(other["id"], reason="Independent review", actor_label="checker")
        other_preview = repository.preview(other["id"], actor=checker)
        row = dict(connection.execute("SELECT * FROM finance_posting_effects WHERE id=?", (original["id"],)).fetchone())
        row.update(
            id="PST-forged",
            entry_id=other["id"],
            source_id=other["id"],
            validation_digest=other_preview["validation_digest"],
        )
        for change in ("unknown_header", "amount"):
            snapshot = json.loads(canonical_json(other_preview["snapshot"]))
            if change == "unknown_header":
                snapshot["entry"]["unknown"] = snapshot["entry"].pop("reverses_posting_id")
            else:
                snapshot["lines"][0]["debit_minor"] += 1
            row["snapshot_json"] = canonical_json(snapshot)
            # Identifier list is obtained from this fixed table, never external input.
            query = (
                "INSERT INTO finance_posting_effects ("
                + ",".join(row)
                + ") VALUES ("
                + ",".join("?" for _ in row)
                + ")"
            )
            with pytest.raises(sqlite3.DatabaseError, match="snapshot"):
                connection.execute(query, tuple(row.values()))
            connection.rollback()


def test_legacy_unsealed_validation_cannot_be_posted(tmp_path: Path) -> None:
    path = tmp_path / "posting.db"
    run_migrations(path)
    with connect(path, require_exists=True) as connection:
        finance, period = _seed_finance_model(connection)
        _seed_actors(connection)
        draft = _create_entry(finance, period)
        with _actor(connection, "checker") as checker:
            finance.validate_entry(draft["id"], reason="Legacy control review", actor_label="checker")
        actor = _posting_actor(checker)
        repository = SQLiteFinancePostingRepository(connection)
        preview = repository.preview(draft["id"], actor=actor)
        assert preview["validation_digest"] is None
        with pytest.raises(FinancePostingError) as rejected:
            _post(repository, preview, actor)
        assert rejected.value.code == "posting_review_unverified"
        assert connection.execute("SELECT count(*) FROM finance_posting_effects").fetchone()[0] == 0


def test_export_snapshot_cannot_include_posting_without_its_audit_event(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "posting.db"
    run_migrations(path)
    with connect(path, require_exists=True) as connection:
        _, _, _, preview, _, checker = _reviewed(connection)
    original_finance_payload = exporter_module._finance_payload

    def commit_posting_after_audit_read(reader):
        with connect(path, require_exists=True) as writer:
            _post(SQLiteFinancePostingRepository(writer), preview, checker)
        return original_finance_payload(reader)

    monkeypatch.setattr(exporter_module, "_finance_payload", commit_posting_after_audit_read)
    with connect(path, require_exists=True) as reader:
        payloads = exporter_module.build_public_export_payloads(reader, schema_version=48)
        assert not reader.in_transaction
    effects = payloads["finance_workflows"]["finance_posting_effects"]
    audit_ids = {row["id"] for row in payloads["audit_events"]["audit_events"]}
    assert all(effect["audit_event_id"] in audit_ids for effect in effects)
    assert effects == []
    with connect(path, require_exists=True) as connection:
        assert connection.execute("SELECT count(*) FROM finance_posting_effects").fetchone()[0] == 1


def test_export_snapshot_preserves_caller_owned_pending_writes(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "posting.db"
    run_migrations(path)
    with connect(path, require_exists=True) as connection:
        _reviewed(connection)
        connection.execute("CREATE TABLE posting_probe(value TEXT)")
        connection.execute("INSERT INTO posting_probe VALUES('pending')")
        exporter_module.build_public_export_payloads(connection, schema_version=48)
        assert connection.in_transaction
        assert connection.execute("SELECT value FROM posting_probe").fetchone()[0] == "pending"
        with connect(path, require_exists=True) as independent:
            assert independent.execute("SELECT count(*) FROM posting_probe").fetchone()[0] == 0

        def fail_finance(_connection):
            raise DBBridgeError("injected export failure")

        monkeypatch.setattr(exporter_module, "_finance_payload", fail_finance)
        with pytest.raises(DBBridgeError, match="injected"):
            exporter_module.build_public_export_payloads(connection, schema_version=48)
        assert connection.in_transaction
        assert connection.execute("SELECT value FROM posting_probe").fetchone()[0] == "pending"
        connection.rollback()
        assert connection.execute("SELECT count(*) FROM posting_probe").fetchone()[0] == 0


def test_canonical_preparer_cannot_review_after_username_change(tmp_path: Path) -> None:
    path = tmp_path / "posting.db"
    run_migrations(path)
    with connect(path, require_exists=True) as connection:
        finance, period = _seed_finance_model(connection)
        _seed_actors(connection)
        with _actor(connection, "maker") as maker:
            draft = _create_entry(finance, period, actor="maker")
        renamed = replace(maker, user=maker.user.model_copy(update={"username": "renamed-maker"}))
        with (
            trusted_local_mode(False),
            server_principal_context(renamed),
            pytest.raises(PlatformError, match="Segregation"),
        ):
            finance.validate_entry(str(draft["id"]), reason="Synthetic self review", actor_label="renamed-maker")


def test_validated_dimension_links_reject_update_and_reparent(tmp_path: Path) -> None:
    path = tmp_path / "posting.db"
    run_migrations(path)
    connection = connect(path, require_exists=True)
    try:
        finance, period = _seed_finance_model(connection)
        finance.upsert_dimension_value(dimension_code="CC", value_code="ALT", name="Other synthetic cost center")
        original = _create_entry(finance, period)
        other = _create_entry(finance, period, number="JE-OTHER")
        finance.validate_entry(str(original["id"]), reason="Synthetic independent control review")
        dimension_id = connection.execute(
            "SELECT id FROM accounting_dimension_values WHERE value_code='ALT'"
        ).fetchone()[0]
        for query, values in (
            (
                "UPDATE ledger_line_dimensions SET dimension_value_id=? WHERE line_id=?",
                (dimension_id, original["lines"][0]["id"]),
            ),
            (
                "UPDATE ledger_line_dimensions SET line_id=? WHERE line_id=?",
                (other["lines"][0]["id"], original["lines"][0]["id"]),
            ),
            (
                "UPDATE ledger_line_dimensions SET line_id=?, dimension_value_id=? WHERE line_id=?",
                (original["lines"][0]["id"], dimension_id, other["lines"][0]["id"]),
            ),
        ):
            with pytest.raises(sqlite3.DatabaseError, match="immutable"):
                connection.execute(query, values)
            connection.rollback()
    finally:
        connection.close()


@pytest.mark.parametrize(
    "table", ["audit_events", "outbox_events", "finance_posting_effects", "finance_posting_commands"]
)
def test_post_failure_rolls_back_business_receipt_and_all_evidence(tmp_path: Path, table: str) -> None:
    path = tmp_path / "posting.db"
    run_migrations(path)
    with connect(path, require_exists=True) as connection:
        _, _, repository, preview, _, checker = _reviewed(connection)
        before = tuple(
            connection.execute(
                "SELECT (SELECT count(*) FROM audit_events),(SELECT count(*) FROM outbox_events),(SELECT updated_at FROM ledger_entries WHERE id=?)",
                (preview["entry_id"],),
            ).fetchone()
        )
        # The parameter is a closed test-owned list, never user input.
        connection.execute(
            f"CREATE TRIGGER posting_test_failure BEFORE INSERT ON {table} BEGIN SELECT RAISE(ABORT,'synthetic late posting failure'); END"
        )
        with pytest.raises((AuditLedgerError, PlatformError, FinancePostingError, sqlite3.DatabaseError)):
            _post(repository, preview, checker)
        assert not connection.in_transaction
        with connect(path, require_exists=True) as independent:
            assert (
                tuple(
                    independent.execute(
                        "SELECT (SELECT count(*) FROM audit_events),(SELECT count(*) FROM outbox_events),(SELECT updated_at FROM ledger_entries WHERE id=?)",
                        (preview["entry_id"],),
                    ).fetchone()
                )
                == before
            )
            assert independent.execute("SELECT count(*) FROM finance_posting_effects").fetchone()[0] == 0
            assert independent.execute("SELECT count(*) FROM finance_posting_commands").fetchone()[0] == 0
        connection.execute("DROP TRIGGER posting_test_failure")
        assert _post(repository, preview, checker)["entry_id"] == preview["entry_id"]


def test_explicit_owner_composition_and_rejected_nested_owner_preserve_pending_work(tmp_path: Path) -> None:
    path = tmp_path / "posting.db"
    run_migrations(path)
    with connect(path, require_exists=True) as connection:
        _, _, repository, preview, _, checker = _reviewed(connection)
        connection.execute("CREATE TABLE posting_probe(id TEXT PRIMARY KEY)")
        connection.execute("INSERT INTO posting_probe VALUES('caller')")
        with pytest.raises(FinancePostingError) as conflict:
            _post(repository, preview, checker)
        assert conflict.value.code == "posting_transaction_owned"
        assert connection.in_transaction
        assert connection.execute("SELECT id FROM posting_probe").fetchone()[0] == "caller"
        connection.rollback()
        with (
            pytest.raises(RuntimeError, match="late owner failure"),
            SQLiteFinancePostingUnitOfWork(connection) as owner,
        ):
            connection.execute("INSERT INTO posting_probe VALUES('owned')")
            result = _post(owner.repository(), preview, checker)
            with connect(path, require_exists=True) as independent:
                assert independent.execute("SELECT count(*) FROM finance_posting_effects").fetchone()[0] == 0
            assert result["entry_id"] == preview["entry_id"]
            assert connection.in_transaction
            raise RuntimeError("late owner failure")
        assert connection.execute("SELECT count(*) FROM finance_posting_effects").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM posting_probe").fetchone()[0] == 0
        with SQLiteFinancePostingUnitOfWork(connection) as owner:
            assert _post(owner.repository(), preview, checker)["entry_id"] == preview["entry_id"]
        assert connection.execute("SELECT count(*) FROM finance_posting_effects").fetchone()[0] == 1


def test_caught_bound_failure_marks_owner_for_rollback(tmp_path: Path) -> None:
    path = tmp_path / "posting.db"
    run_migrations(path)
    with connect(path, require_exists=True) as connection:
        _, _, _, preview, _, checker = _reviewed(connection)
        connection.execute("CREATE TABLE posting_probe(id TEXT PRIMARY KEY)")
        with pytest.raises(FinancePostingError) as failed_owner, SQLiteFinancePostingUnitOfWork(connection) as owner:
            connection.execute("INSERT INTO posting_probe VALUES('owned')")
            with pytest.raises(FinancePostingError):
                owner.repository().post(
                    preview["entry_id"],
                    command_id="post-1",
                    expected_validation_digest="0" * 64,
                    reason="Mismatch",
                    actor=checker,
                )
            assert connection.in_transaction
            assert connection.execute("SELECT count(*) FROM posting_probe").fetchone()[0] == 1
        assert failed_owner.value.code == "posting_transaction_failed"
        assert connection.execute("SELECT count(*) FROM posting_probe").fetchone()[0] == 0


def test_two_real_connections_retry_exactly_one_committed_command(tmp_path: Path) -> None:
    path = tmp_path / "posting.db"
    run_migrations(path)
    with connect(path, require_exists=True) as connection:
        _, _, _, preview, _, checker = _reviewed(connection)
    ready = Barrier(2)

    def worker():
        connection = connect(path, require_exists=True)
        try:
            repository = SQLiteFinancePostingRepository(connection)
            ready.wait(timeout=10)
            return _post(repository, preview, checker)
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = list(pool.map(lambda _: worker(), range(2)))
    assert first == second
    with connect(path, require_exists=True) as connection:
        assert connection.execute("SELECT count(*) FROM finance_posting_effects").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM finance_posting_commands").fetchone()[0] == 1
        assert (
            connection.execute("SELECT count(*) FROM audit_events WHERE action='finance_entry_posted'").fetchone()[0]
            == 1
        )
        assert (
            connection.execute("SELECT count(*) FROM outbox_events WHERE event_type='finance_entry_posted'").fetchone()[
                0
            ]
            == 1
        )


def test_backup_restore_preserves_posted_original_reversal_receipts_and_guards(tmp_path: Path) -> None:
    path = tmp_path / "posting.db"
    run_migrations(path)
    with connect(path, require_exists=True) as connection:
        finance, period, repository, preview, maker, checker = _reviewed(connection)
        effect = _post(repository, preview, checker)
        reversal = repository.prepare_reversal(
            effect["id"],
            command_id="reverse-1",
            entry_number="REV-1",
            period_id=period["id"],
            posting_date="2026-07-06",
            reason="Full synthetic correction",
            actor=maker,
        )
        with _actor(connection, "checker"):
            finance.validate_entry(reversal["entry_id"], reason="Independent reversal review", actor_label="checker")
        inverse = _post(repository, repository.preview(reversal["entry_id"], actor=checker), checker, "reverse-post")
        # Historical effects remain restorable after their accounting period closes.
        connection.execute("UPDATE periods SET status='Closed' WHERE id=?", (period["id"],))
        connection.commit()
    backup = create_backup(path, tmp_path / "backup")
    restored = tmp_path / "restored.db"
    restore_backup(restored, backup.backup_path)
    with connect(restored, require_exists=True) as connection:
        repository = SQLiteFinancePostingRepository(connection)
        assert repository.get_effect(effect["id"], actor=checker) == effect
        assert repository.get_effect(inverse["id"], actor=checker) == inverse
        assert _post(repository, preview, checker) == effect
        trial = repository.posted_trial_balance(
            period_id=period["id"], organization_code="SYN", entity_code="EG01", actor=checker
        )
        assert trial["balance_totals"]["debit_minor"] == 0
        assert trial["totals"]["debit_minor"] == 200000
        for query in (
            "UPDATE finance_posting_effects SET reason='changed'",
            "DELETE FROM finance_posting_commands",
            "UPDATE ledger_entries SET updated_at='changed' WHERE id=?",
        ):
            with pytest.raises(sqlite3.DatabaseError, match="immutable"):
                connection.execute(query, (effect["entry_id"],) if "?" in query else ())
            connection.rollback()


def test_command_receipt_cannot_claim_nonexistent_posting(tmp_path: Path) -> None:
    path = tmp_path / "posting.db"
    run_migrations(path)
    with connect(path, require_exists=True) as connection:
        _, _, _, preview, _, checker = _reviewed(connection)
        with pytest.raises(sqlite3.DatabaseError, match="receipt"):
            connection.execute(
                "INSERT INTO finance_posting_commands(workspace_id,command_id,operation,actor_id,request_digest,result_json,created_at) VALUES(?, 'forged', 'post', ?, ?, ?, '2026-07-05T00:00:00Z')",
                (preview["snapshot"]["entry"]["workspace_id"], checker.user_id, "a" * 64, '{"id":"PST-nonexistent"}'),
            )
        connection.rollback()


def test_reviewed_entry_retained_before_operational_posting(tmp_path: Path) -> None:
    path = tmp_path / "posting.db"
    run_migrations(path)
    with connect(path, require_exists=True) as connection:
        _, _, _, preview, _, _ = _reviewed(connection)
        with pytest.raises(sqlite3.DatabaseError, match="immutable"):
            connection.execute("DELETE FROM ledger_entries WHERE id=?", (preview["entry_id"],))
        connection.rollback()
        assert (
            connection.execute("SELECT status FROM ledger_entries WHERE id=?", (preview["entry_id"],)).fetchone()[0]
            == "Validated"
        )


def test_copied_real_receipt_cannot_report_success_for_another_entry(tmp_path: Path) -> None:
    path = tmp_path / "posting.db"
    run_migrations(path)
    with connect(path, require_exists=True) as connection:
        finance, period, repository, preview, _, checker = _reviewed(connection)
        original = _post(repository, preview, checker)
        with _actor(connection, "maker"):
            other = _create_entry(finance, period, number="OTHER", actor="maker")
        with _actor(connection, "checker"):
            finance.validate_entry(other["id"], reason="Other independent review", actor_label="checker")
        other_preview = repository.preview(other["id"], actor=checker)
        reason = "Explicit synthetic posting"
        forged_request = digest_payload(
            {
                "operation": "post",
                "actor_id": checker.user_id,
                "workspace_id": original["workspace_id"],
                "entry_id": other["id"],
                "expected_validation_digest": other_preview["validation_digest"],
                "reason": reason,
            }
        )
        connection.execute(
            "INSERT INTO finance_posting_commands(workspace_id,command_id,operation,actor_id,request_digest,result_json,created_at) VALUES(?, 'copied', 'post', ?, ?, ?, '2026-07-05T00:00:00Z')",
            (original["workspace_id"], checker.user_id, forged_request, canonical_json(original)),
        )
        connection.commit()
        with pytest.raises(FinancePostingError, match="receipt"):
            _post(repository, other_preview, checker, "copied")
        assert (
            connection.execute(
                "SELECT count(*) FROM finance_posting_effects WHERE entry_id=?", (other["id"],)
            ).fetchone()[0]
            == 0
        )


@pytest.mark.parametrize(
    "changed,code",
    [
        ({"principal_type": "service_account"}, "posting_human_required"),
        ({"step_up_active": False}, "posting_step_up_required"),
        ({"permissions": frozenset({"finance_core.read"})}, "posting_permission_denied"),
    ],
)
def test_actor_assurance_rejection_precedes_financial_mutation(tmp_path: Path, changed, code: str) -> None:
    path = tmp_path / "posting.db"
    run_migrations(path)
    with connect(path, require_exists=True) as connection:
        _, _, repository, preview, maker, checker = _reviewed(connection)
        with pytest.raises(FinancePostingError) as denied:
            _post(repository, preview, replace(checker, **changed))
        assert denied.value.code == code
        with pytest.raises(FinancePostingError) as self_post:
            _post(repository, preview, maker)
        assert self_post.value.code == "posting_sod_denied"
        assert connection.execute("SELECT count(*) FROM finance_posting_effects").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM finance_posting_commands").fetchone()[0] == 0


@pytest.mark.parametrize("close_first", [True, False])
def test_period_close_and_post_serialize_actual_writer_transactions(tmp_path: Path, close_first: bool) -> None:
    path = tmp_path / "posting.db"
    run_migrations(path)
    with connect(path, require_exists=True) as connection:
        _, period, _, preview, _, checker = _reviewed(connection)
        attempted = Event()

        def competitor():
            other = connect(path, require_exists=True)
            try:

                def observed(query):
                    if query.startswith("BEGIN IMMEDIATE") or query.startswith("UPDATE periods"):
                        attempted.set()

                other.set_trace_callback(observed)
                if close_first:
                    return _post(SQLiteFinancePostingRepository(other), preview, checker)
                other.execute("UPDATE periods SET status='Closed' WHERE id=?", (period["id"],))
                other.commit()
                return "closed"
            finally:
                other.close()

        with ThreadPoolExecutor(max_workers=1) as pool:
            with SQLiteFinancePostingUnitOfWork(connection) as owner:
                if close_first:
                    connection.execute("UPDATE periods SET status='Closed' WHERE id=?", (period["id"],))
                else:
                    _post(owner.repository(), preview, checker)
                pending = pool.submit(competitor)
                assert attempted.wait(timeout=10)
                with pytest.raises(FutureTimeout):
                    pending.result(timeout=0.2)
            if close_first:
                with pytest.raises(FinancePostingError) as denied:
                    pending.result(timeout=10)
                assert denied.value.code == "posting_period_closed"
            else:
                assert pending.result(timeout=10) == "closed"
        assert connection.execute("SELECT count(*) FROM finance_posting_effects").fetchone()[0] == (
            0 if close_first else 1
        )
        assert connection.execute("SELECT status FROM periods WHERE id=?", (period["id"],)).fetchone()[0] == "Closed"
