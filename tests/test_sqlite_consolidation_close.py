from __future__ import annotations

import json
import sqlite3
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

import pytest

import reconforge.infrastructure.sqlite_consolidation_close as consolidation_module
from reconforge.db import connect, run_migrations
from reconforge.db.backup import create_backup, restore_backup
from reconforge.db.exporter import DBBridgeError, checksum_file, write_json_file
from reconforge.db.migrations import MIGRATIONS
from reconforge.domain.consolidation import (
    ConsolidationBalance,
    ConsolidationPolicy,
    ConsolidationRequest,
    translate_consolidation,
)
from reconforge.domain.consolidation_lifecycle import (
    ConsolidationElimination,
    ConsolidationEliminationLine,
    ConsolidationLifecyclePolicy,
    ConsolidationOwnershipInterest,
    ConsolidationWorksheetRequest,
    prepare_consolidation_worksheet,
)
from reconforge.domain.models import utc_now_text
from reconforge.infrastructure.sqlite_consolidation_close import (
    SQLiteConsolidationCloseRepository,
    verify_consolidation_close_integrity,
)
from reconforge.io.persisted import (
    PersistedJsonError,
    decode_consolidation_worksheet,
    encode_consolidation_worksheet,
)
from reconforge.platform.common import PlatformError
from reconforge.utils.money import Money


def _digest(label: str) -> str:
    return sha256(label.encode("utf-8")).hexdigest()


def _balance(
    line_id: str,
    entity: str,
    account: str,
    group_account: str,
    account_type: str,
    amount: str,
    rate_type: str,
) -> ConsolidationBalance:
    return ConsolidationBalance(
        source_line_id=line_id,
        source_trial_balance_digest=_digest(f"trial-balance:{entity}"),
        entity_code=entity,
        source_account_code=account,
        group_account_code=group_account,
        account_type=account_type,  # type: ignore[arg-type]
        period_id="2026-08",
        amount=Decimal(amount),
        currency="USD",
        rate_type=rate_type,  # type: ignore[arg-type]
        rate_bucket=f"identity:{entity}:{rate_type}",
    )


def _worksheet(*, elimination_amount: str = "12.00"):
    now = utc_now_text()
    translation = translate_consolidation(
        ConsolidationRequest(
            group_code="GLOBAL-GROUP",
            period_id="2026-08",
            reporting_currency="USD",
            actor_id="translation-controller",
            calculated_at=now,
            policy=ConsolidationPolicy(
                policy_id="translation-policy",
                version="1.0.0",
                translation_adjustment_account_code="CTA-999",
                translation_adjustment_account_type="Equity",
            ),
            balances=(
                _balance("P-A", "PARENT", "1100", "1000", "Asset", "50.00", "closing"),
                _balance("P-E", "PARENT", "3100", "3000", "Equity", "-50.00", "historical"),
                _balance("S-A", "SUB", "1200", "1000", "Asset", "100.00", "closing"),
                _balance("S-E", "SUB", "3200", "3000", "Equity", "-100.00", "historical"),
            ),
            rates=(),
        )
    )
    amount = Money.from_exact(elimination_amount, "USD", strict_precision=True)
    opposite = Money.from_exact(-amount.amount, "USD", strict_precision=True)
    elimination = ConsolidationElimination(
        elimination_id="ELIM-IC-1",
        elimination_type="intercompany_balance",
        version="1.0.0",
        lines=(
            ConsolidationEliminationLine(
                line_id="ELIM-IC-1-DR",
                entity_code="SUB",
                group_account_code="1000",
                account_type="Asset",
                amount=amount,
                source_reference="intercompany-case:IC-1:sub",
                source_digest=_digest("intercompany-case:IC-1:sub"),
            ),
            ConsolidationEliminationLine(
                line_id="ELIM-IC-1-CR",
                entity_code="PARENT",
                group_account_code="3000",
                account_type="Equity",
                amount=opposite,
                source_reference="intercompany-case:IC-1:parent",
                source_digest=_digest("intercompany-case:IC-1:parent"),
            ),
        ),
        prepared_by="consolidation-preparer",
        prepared_at=now,
        rationale="Eliminate one synthetic reciprocal group balance.",
    )
    ownership = ConsolidationOwnershipInterest(
        interest_id="OWN-PARENT-SUB",
        parent_entity_code="PARENT",
        subsidiary_entity_code="SUB",
        direct_ownership_percentage=Decimal("0.80"),
        effective_from="2026-01-01",
        effective_to="",
        version="1.0.0",
        source_digest=_digest("ownership:PARENT:SUB"),
        prepared_by="ownership-preparer",
        approved_by="ownership-reviewer",
        approved_at=now,
    )
    return prepare_consolidation_worksheet(
        ConsolidationWorksheetRequest(
            translation_result=translation,
            policy=ConsolidationLifecyclePolicy(
                policy_id="group-close-policy",
                version="1.0.0",
                parent_entity_code="PARENT",
                nci_net_assets_presentation_account_code="NCI-NET-ASSETS",
                nci_profit_presentation_account_code="NCI-PROFIT",
            ),
            period_start_date="2026-08-01",
            period_end_date="2026-08-31",
            reporting_date="2026-08-01",
            ownership_interests=(ownership,),
            eliminations=(elimination,),
            prepared_by="consolidation-preparer",
            prepared_at=now,
        )
    )


def _database(tmp_path: Path, *, version: int | None = None) -> tuple[Path, sqlite3.Connection]:
    path = tmp_path / "consolidation.db"
    run_migrations(path, target_version=version)
    return path, connect(path, require_exists=True)


def _prepare(
    connection: sqlite3.Connection,
    *,
    run_number: str = "RUN-001",
    worksheet=None,
) -> tuple[SQLiteConsolidationCloseRepository, dict[str, object], dict[str, object]]:
    repository = SQLiteConsolidationCloseRepository(connection)
    period = repository.create_period(
        group_code="GLOBAL-GROUP",
        period_id="2026-08",
        reporting_currency="USD",
        period_start_date="2026-08-01",
        period_end_date="2026-08-31",
        reporting_date="2026-08-01",
        actor_label="consolidation-preparer",
    )
    run = repository.prepare_run(
        run_number=run_number,
        worksheet=worksheet or _worksheet(),
        actor_label="consolidation-preparer",
    )
    return repository, period, run


def _post(repository: SQLiteConsolidationCloseRepository, run: dict[str, object]) -> dict[str, object]:
    repository.approve_run(
        str(run["id"]),
        expected_version=1,
        reason="Independent worksheet approval.",
        actor_label="group-reviewer",
    )
    return repository.post_run(
        str(run["id"]),
        expected_version=2,
        reason="Post to the isolated consolidation control ledger.",
        actor_label="group-poster",
    )


def _reverse(repository: SQLiteConsolidationCloseRepository, run: dict[str, object]) -> dict[str, object]:
    repository.request_reversal(
        str(run["id"]),
        expected_version=3,
        reason="Synthetic correction requires an exact reversal.",
        actor_label="reversal-requester",
    )
    return repository.approve_reversal(
        str(run["id"]),
        expected_version=4,
        reason="Independent approval of exact compensating effect.",
        actor_label="reversal-reviewer",
    )


def test_replay_verified_run_exposes_explicit_translation_lineage_evidence(tmp_path: Path) -> None:
    connection = _database(tmp_path)[1]
    repository, _, run = _prepare(connection)

    detail = repository.get_run(str(run["id"]))
    evidence = detail["translation_evidence"]

    assert evidence["result_digest"] == str(run["translation_result_digest"])
    assert evidence["line_count"] == len(detail["worksheet"]["request"]["translation_result"]["lines"])
    assert evidence["source_currencies"] == ["USD"]
    assert evidence["rate_ids"] == ["IDENTITY-USD"]
    assert len(str(evidence["lineage_digest"])) == 64
    assert evidence["post_adjustment_balance"]["amount"] == "0.00"
    statement = detail["management_statement"]
    assert statement["total_balance"]["amount"] == "0.00"
    assert statement["worksheet_result_digest"] == run["worksheet_result_digest"]
    assert statement["sections"]
    bundle = detail["close_bundle"]
    assert bundle["worksheet_result_digest"] == run["worksheet_result_digest"]
    assert bundle["translation_result_digest"] == run["translation_result_digest"]
    assert bundle["management_statement_digest"] == statement["artifact_digest"]


def test_migration_25_is_additive_and_adapter_rejects_a_pre_migration_database(tmp_path: Path) -> None:
    assert next(migration for migration in MIGRATIONS if migration.version == 25).name == "consolidation_close_lifecycle"
    assert MIGRATIONS[-1].version >= 38
    old_path, old_connection = _database(tmp_path, version=24)
    try:
        with pytest.raises(PlatformError, match="schema is unavailable"):
            SQLiteConsolidationCloseRepository(old_connection)
    finally:
        old_connection.close()

    applied = run_migrations(old_path)
    assert applied.applied_versions == list(range(25, MIGRATIONS[-1].version + 1))
    upgraded = connect(old_path, require_exists=True)
    try:
        SQLiteConsolidationCloseRepository(upgraded)
    finally:
        upgraded.close()


def test_full_lifecycle_is_exact_attributable_immutable_and_replay_verified(tmp_path: Path) -> None:
    _path, connection = _database(tmp_path)
    try:
        worksheet = _worksheet()
        repository, period, run = _prepare(connection, worksheet=worksheet)

        assert repository.create_period(
            group_code="GLOBAL-GROUP",
            period_id="2026-08",
            reporting_currency="USD",
            period_start_date="2026-08-01",
            period_end_date="2026-08-31",
            reporting_date="2026-08-01",
            actor_label="consolidation-preparer",
        ) == period
        assert repository.prepare_run(
            run_number="RUN-001",
            worksheet=worksheet,
            actor_label="consolidation-preparer",
        ) == run
        with pytest.raises(PlatformError, match="conflicts"):
            repository.create_period(
                group_code="GLOBAL-GROUP",
                period_id="2026-08",
                reporting_currency="USD",
                period_start_date="2026-08-01",
                period_end_date="2026-08-31",
                reporting_date="2026-08-02",
                actor_label="consolidation-preparer",
            )
        with pytest.raises(PlatformError, match="Segregation of duties"):
            repository.approve_run(
                str(run["id"]),
                expected_version=1,
                reason="Self approval must fail.",
                actor_label="CONSOLIDATION-PREPARER",
            )
        with pytest.raises(PlatformError, match="expected Prepared version 2"):
            repository.approve_run(
                str(run["id"]),
                expected_version=2,
                reason="Stale version must fail.",
                actor_label="group-reviewer",
            )

        approved = repository.approve_run(
            str(run["id"]),
            expected_version=1,
            reason="Independent worksheet approval.",
            actor_label="group-reviewer",
        )
        with pytest.raises(PlatformError, match="independent"):
            repository.post_run(
                str(run["id"]),
                expected_version=2,
                reason="Reviewer cannot post.",
                actor_label="GROUP-REVIEWER",
            )
        posted = repository.post_run(
            str(run["id"]),
            expected_version=2,
            reason="Post to isolated control ledger.",
            actor_label="group-poster",
        )
        assert approved["status"] == "Approved"
        assert posted["status"] == "Posted"
        posting = posted["effects"][0]  # type: ignore[index]
        assert posting["effect_type"] == "Posting"
        assert sum(line["amount_minor"] for line in posting["lines"]) == 0
        assert [line["amount_minor"] for line in posting["lines"]] == [
            line["amount_minor"] for line in posted["journal_lines"]
        ]

        requested = repository.request_reversal(
            str(run["id"]),
            expected_version=3,
            reason="Prepare exact correction.",
            actor_label="reversal-requester",
        )
        for actor in ("reversal-requester", "group-poster"):
            with pytest.raises(PlatformError, match="independent"):
                repository.approve_reversal(
                    str(run["id"]),
                    expected_version=4,
                    reason="Conflicted reversal approval.",
                    actor_label=actor,
                )
        reversed_run = repository.approve_reversal(
            str(run["id"]),
            expected_version=4,
            reason="Independent exact reversal approval.",
            actor_label="reversal-reviewer",
        )
        effects = {effect["effect_type"]: effect for effect in reversed_run["effects"]}  # type: ignore[index]
        assert requested["status"] == "ReversalPrepared"
        assert reversed_run["status"] == "Reversed"
        assert reversed_run["row_version"] == 5
        assert [line["amount_minor"] for line in effects["Reversal"]["lines"]] == [
            -line["amount_minor"] for line in effects["Posting"]["lines"]
        ]

        locked = repository.lock_period(
            str(period["id"]),
            expected_version=1,
            reason="All governed runs are final.",
            actor_label="period-locker",
        )
        with pytest.raises(PlatformError, match="independent"):
            repository.reopen_period(
                str(period["id"]),
                expected_version=2,
                reason="Self reopen must fail.",
                actor_label="PERIOD-LOCKER",
            )
        reopened = repository.reopen_period(
            str(period["id"]),
            expected_version=2,
            reason="Approved adjustment window.",
            actor_label="period-reopener",
        )
        relocked = repository.lock_period(
            str(period["id"]),
            expected_version=3,
            reason="Adjustment window closed.",
            actor_label="second-period-locker",
        )
        events = connection.execute(
            "SELECT event_sequence,from_status,to_status FROM consolidation_period_events ORDER BY event_sequence"
        ).fetchall()
        assert locked["status"] == "Locked"
        assert reopened["status"] == "Reopened"
        assert relocked["status"] == "Locked"
        assert [tuple(event) for event in events] == [
            (2, "Open", "Locked"),
            (3, "Locked", "Reopened"),
            (4, "Reopened", "Locked"),
        ]
        verify_consolidation_close_integrity(connection)
        assert repository.summary(actor_label="reader").to_dict() == {
            "workspace": "default",
            "periods": 1,
            "locked_periods": 1,
            "prepared_runs": 0,
            "approved_runs": 0,
            "posted_runs": 0,
            "reversal_prepared_runs": 0,
            "reversed_runs": 1,
        }
        assert repository.list_runs(status="Reversed", actor_label="reader")[0]["id"] == run["id"]
        assert connection.execute("SELECT COUNT(*) FROM ledger_entries").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM finance_journals").fetchone()[0] == 0
    finally:
        connection.close()


def test_posted_run_certification_is_replayable_and_maker_checker_bound(tmp_path: Path) -> None:
    _path, connection = _database(tmp_path)
    try:
        repository, _period, run = _prepare(connection)
        posted = _post(repository, run)
        prepared = repository.prepare_certification(
            str(posted["id"]),
            note="Synthetic close evidence is ready for independent review.",
            actor_label="certification-preparer",
        )
        assert prepared["status"] == "Prepared"
        assert prepared["prepared_by"] == "certification-preparer"
        assert prepared["evidence_digest"] == posted["close_bundle"]["bundle_digest"]
        with pytest.raises(PlatformError, match="preparer and reviewer"):
            repository.review_certification(
                str(posted["id"]),
                note="Self-review must fail closed.",
                actor_label="certification-preparer",
            )
        reviewed = repository.review_certification(
            str(posted["id"]),
            note="Independent review completed against the posted control journal.",
            actor_label="certification-reviewer",
        )
        assert reviewed["status"] == "Reviewed"
        assert reviewed["reviewed_by"] == "certification-reviewer"
        assert reviewed["evidence_digest"] == posted["close_bundle"]["bundle_digest"]
        assert repository.get_certification(str(posted["id"])) == reviewed
        connection.execute(
            "UPDATE certification_records SET evidence_digest=? WHERE object_type=? AND object_id=?",
            ("0" * 64, "consolidation_close_run", str(posted["id"])),
        )
        with pytest.raises(PlatformError, match="evidence digest"):
            repository.get_certification(str(posted["id"]))
    finally:
        connection.close()


def test_locked_period_blocks_new_or_changed_runs_until_independent_reopen(tmp_path: Path) -> None:
    _path, connection = _database(tmp_path)
    try:
        repository, period, prepared = _prepare(connection)
        posted = _post(repository, prepared)
        locked = repository.lock_period(
            str(period["id"]),
            expected_version=1,
            reason="Posted run closes the period.",
            actor_label="period-locker",
        )
        assert locked["status"] == "Locked"
        with pytest.raises(PlatformError, match="locked"):
            repository.request_reversal(
                str(posted["id"]),
                expected_version=3,
                reason="Blocked while locked.",
                actor_label="reversal-requester",
            )
        with pytest.raises(PlatformError, match="locked"):
            repository.prepare_run(
                run_number="RUN-002",
                worksheet=_worksheet(elimination_amount="13.00"),
                actor_label="consolidation-preparer",
            )
        repository.reopen_period(
            str(period["id"]),
            expected_version=2,
            reason="Open an approved correction window.",
            actor_label="period-reopener",
        )
        requested = repository.request_reversal(
            str(posted["id"]),
            expected_version=3,
            reason="Prepare correction after reopen.",
            actor_label="reversal-requester",
        )
        assert requested["status"] == "ReversalPrepared"
        with pytest.raises(PlatformError, match="Unable to lock"):
            repository.lock_period(
                str(period["id"]),
                expected_version=3,
                reason="Unfinished reversal must block relock.",
                actor_label="second-period-locker",
            )
        assert connection.execute("SELECT COUNT(*) FROM consolidation_period_events").fetchone()[0] == 2
    finally:
        connection.close()


def test_database_guards_reject_bypass_and_audit_failure_rolls_back_effect(tmp_path: Path, monkeypatch) -> None:
    _path, connection = _database(tmp_path)
    try:
        repository, period, prepared = _prepare(connection)
        with pytest.raises(sqlite3.IntegrityError, match="immutable event"):
            connection.execute(
                """
                UPDATE consolidation_close_periods
                SET status='Locked',row_version=2,locked_by='x',locked_at=?,lock_reason='x'
                WHERE id=?
                """,
                (utc_now_text(), period["id"]),
            )
        connection.rollback()
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute(
                "UPDATE consolidation_run_lines SET amount_minor=amount_minor+1 WHERE run_id=?",
                (prepared["id"],),
            )
        connection.rollback()
        with pytest.raises(sqlite3.IntegrityError, match="independent"):
            connection.execute(
                """
                UPDATE consolidation_runs
                SET status='Approved',row_version=2,approved_by=prepared_by,
                    approved_at=prepared_at,approval_reason='bypass'
                WHERE id=?
                """,
                (prepared["id"],),
            )
        connection.rollback()

        approved = repository.approve_run(
            str(prepared["id"]),
            expected_version=1,
            reason="Independent approval.",
            actor_label="group-reviewer",
        )

        def fail_audit(*_args, **_kwargs) -> None:
            raise PlatformError("synthetic audit failure")

        monkeypatch.setattr(consolidation_module, "commit_audited", fail_audit)
        with pytest.raises(PlatformError, match="audit failure"):
            repository.post_run(
                str(approved["id"]),
                expected_version=2,
                reason="Must roll back with audit.",
                actor_label="group-poster",
            )
        persisted = repository.get_run(str(prepared["id"]), actor_label="reader")
        assert persisted["status"] == "Approved"
        assert persisted["effects"] == []
        assert connection.execute("SELECT COUNT(*) FROM consolidation_effects").fetchone()[0] == 0
    finally:
        connection.close()


def test_bounded_replay_detects_at_rest_payload_and_effect_tampering(tmp_path: Path) -> None:
    _path, connection = _database(tmp_path)
    try:
        repository, _period, prepared = _prepare(connection)
        posted = _post(repository, prepared)
        connection.execute("DROP TRIGGER consolidation_runs_guard_update")
        connection.execute(
            "UPDATE consolidation_runs SET worksheet_payload=worksheet_payload || ' ' WHERE id=?",
            (posted["id"],),
        )
        connection.commit()
        with pytest.raises(PlatformError, match="checksum mismatch"):
            repository.get_run(str(posted["id"]), actor_label="reader")
    finally:
        connection.close()

    _path, connection = _database(tmp_path / "effect")
    try:
        repository, _period, prepared = _prepare(connection)
        posted = _post(repository, prepared)
        connection.execute("DROP TRIGGER consolidation_effect_lines_immutable_update")
        connection.execute(
            "UPDATE consolidation_effect_lines SET amount_decimal='999.00' WHERE effect_id=?",
            (posted["effects"][0]["id"],),  # type: ignore[index]
        )
        connection.commit()
        with pytest.raises(PlatformError, match="does not reproduce"):
            repository.get_run(str(posted["id"]), actor_label="reader")
    finally:
        connection.close()


def test_backup_restore_replays_every_state_and_rejects_rehashed_tampering(tmp_path: Path) -> None:
    source_path, connection = _database(tmp_path / "source")
    try:
        repository, period, prepared = _prepare(connection)
        reversed_run = _reverse(repository, _post(repository, prepared))
        repository.lock_period(
            str(period["id"]),
            expected_version=1,
            reason="First close.",
            actor_label="period-locker",
        )
        repository.reopen_period(
            str(period["id"]),
            expected_version=2,
            reason="Correction window.",
            actor_label="period-reopener",
        )
        final_period = repository.lock_period(
            str(period["id"]),
            expected_version=3,
            reason="Final close.",
            actor_label="second-period-locker",
        )
    finally:
        connection.close()

    backup = create_backup(source_path, tmp_path / "backup")
    restored_path = tmp_path / "restored.db"
    restore_backup(restored_path, backup.backup_path)
    restored_connection = connect(restored_path, require_exists=True)
    try:
        restored = SQLiteConsolidationCloseRepository(restored_connection)
        assert restored.get_run(str(reversed_run["id"]), actor_label="reader") == reversed_run
        assert restored.get_period(str(final_period["id"]), actor_label="reader") == final_period
        verify_consolidation_close_integrity(restored_connection)
    finally:
        restored_connection.close()

    document = json.loads(backup.backup_path.read_text(encoding="utf-8"))
    run_row = document["tables"]["consolidation_runs"][0]
    payload = json.loads(run_row["worksheet_payload"])
    payload["prepared_by"] = "tampered-preparer"
    run_row["worksheet_payload"] = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    write_json_file(backup.backup_path, document)
    manifest = json.loads(backup.manifest_path.read_text(encoding="utf-8"))
    manifest["artifacts"]["backup.json"]["sha256"] = checksum_file(backup.backup_path)
    manifest["artifacts"]["backup.json"]["bytes"] = backup.backup_path.stat().st_size
    write_json_file(backup.manifest_path, manifest)

    tampered_target = tmp_path / "tampered-restored.db"
    with pytest.raises(DBBridgeError, match="integrity verification"):
        restore_backup(tampered_target, backup.backup_path)
    assert not tampered_target.exists()


def test_consolidation_worksheet_json_profile_rejects_fractional_and_unbounded_values() -> None:
    with pytest.raises(PersistedJsonError, match="fractional_number_forbidden"):
        decode_consolidation_worksheet('{"fractional":1.25}')
    with pytest.raises(PersistedJsonError):
        encode_consolidation_worksheet({"float": 1.25})
    with pytest.raises(PersistedJsonError):
        decode_consolidation_worksheet('{"oversized":"' + ("x" * (1024 * 1024 + 1)) + '"}')


def test_schema_runtime_docs_and_tests_are_in_distribution_manifest() -> None:
    manifest = Path("MANIFEST.in").read_text(encoding="utf-8")
    expected = {
        "include docs/adr/0212-consolidation-close-lifecycle-is-local-and-replayable.md",
        "include docs/consolidation-close-lifecycle.md",
        "include reconforge/application/consolidation_close.py",
        "include reconforge/infrastructure/sqlite_consolidation_close.py",
        "include tests/test_sqlite_consolidation_close.py",
    }
    assert expected <= set(manifest.splitlines())
