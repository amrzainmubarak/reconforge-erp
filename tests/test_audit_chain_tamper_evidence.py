"""Cryptographic SHA-256 Audit Chaining Tamper Evidence Verification Suite.

Validates Defense-in-Depth for Audit Ledgers:
1. Level 1 Database Defense (Append-Only Triggers):
   - Verifies that SQLite schema triggers (trg_audit_events_no_update, trg_audit_events_no_delete)
     actively reject UPDATE and DELETE attempts with sqlite3.IntegrityError ("audit events are append-only").
2. Level 2 Cryptographic Chain Defense (SHA-256 Tamper Evidence):
   - Simulates a compromised database or offline tamper where triggers are bypassed or dropped:
     - Direct row value mutation drills: Modifies actor_label, action, or metadata_json in SQLite ledger rows,
       proving verify_audit_events() fails and detects the exact corrupted sequence number.
     - Record deletion tamper drill: Deletes an intermediate event, proving detection of sequence discontinuity
       and previous-hash divergence.
     - Sequence order swap drill: Inverts adjacent event sequence numbers, proving detection.
     - Ledger head state tampering: Modifies audit_ledger_state last_sequence or last_event_hash,
       proving detection of head mismatch.
     - Malformed JSON metadata injection: Corrupts metadata string, proving payload validation failure.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from reconforge.audit.events import (
    append_audit_event,
    verify_audit_events,
)
from reconforge.db import connect, run_migrations


def _create_clean_ledger(tmp_path: Path, event_count: int = 50) -> sqlite3.Connection:
    """Create a temporary SQLite database, run migrations, and append N authentic events."""
    db_path = tmp_path / "tamper_drill.db"
    run_migrations(db_path)
    conn = connect(db_path, require_exists=True)

    for i in range(1, event_count + 1):
        append_audit_event(
            conn,
            actor_label=f"auditor_{i % 5}",
            actor_user_id=f"usr-{i % 5}",
            object_type="JournalEntry",
            object_id=f"JE-2026-{i:04d}",
            action="CREATE" if i % 2 == 1 else "POST",
            before_hash=None if i % 2 == 1 else f"hash-before-{i}",
            after_hash=f"hash-after-{i}",
            metadata={"step": i, "batch": f"B-{i // 10}"},
        )
    return conn


def _bypass_append_only_triggers(conn: sqlite3.Connection) -> None:
    """Drop append-only triggers to simulate offline database tampering or privileged attacker access."""
    # Find and drop triggers on audit_events
    triggers = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'trigger' AND tbl_name = 'audit_events'"
    ).fetchall()
    for row in triggers:
        conn.execute(f"DROP TRIGGER IF EXISTS {row['name']}")
    conn.commit()


# ==============================================================================
# 1. Level 1: Database Append-Only Trigger Enforcement
# ==============================================================================


def test_database_triggers_prevent_direct_update_and_delete(tmp_path: Path) -> None:
    """SQLite triggers actively abort any direct UPDATE or DELETE on audit_events."""
    conn = _create_clean_ledger(tmp_path, 10)
    try:
        # Attempt direct UPDATE
        with pytest.raises(sqlite3.IntegrityError, match="audit events are append-only"):
            conn.execute("UPDATE audit_events SET actor_label = 'attacker' WHERE sequence = 5")

        # Attempt direct DELETE
        with pytest.raises(sqlite3.IntegrityError, match="audit events are append-only"):
            conn.execute("DELETE FROM audit_events WHERE sequence = 5")
    finally:
        conn.close()


# ==============================================================================
# 2. Level 2: Cryptographic SHA-256 Tamper Detection
# ==============================================================================


def test_clean_audit_chain_verification_succeeds(tmp_path: Path) -> None:
    """A clean, unmodified audit ledger with 50 events validates with 0 issues."""
    conn = _create_clean_ledger(tmp_path, 50)
    try:
        result = verify_audit_events(conn)
        assert result.ok is True, f"Clean ledger failed verification: {result.issues}"
        assert len(result.issues) == 0
        assert result.checked_events == 50
        assert result.head_hash is not None
    finally:
        conn.close()


def test_tamper_row_actor_label_detected(tmp_path: Path) -> None:
    """Mutating actor_label on sequence 25 causes verify_audit_events to detect hash mismatch at seq 25."""
    conn = _create_clean_ledger(tmp_path, 50)
    try:
        _bypass_append_only_triggers(conn)

        # Adversarial tamper drill: Change actor
        conn.execute("UPDATE audit_events SET actor_label = 'malicious_intruder' WHERE sequence = 25")
        conn.commit()

        result = verify_audit_events(conn)
        assert result.ok is False
        assert len(result.issues) >= 1

        # Pinpoint exact tampered sequence
        seq_25_issues = [issue for issue in result.issues if issue.sequence == 25]
        assert len(seq_25_issues) >= 1
        assert "Audit event hash does not match row content." in seq_25_issues[0].message
    finally:
        conn.close()


def test_tamper_row_action_detected(tmp_path: Path) -> None:
    """Mutating action on sequence 10 causes verify_audit_events to detect hash mismatch at seq 10."""
    conn = _create_clean_ledger(tmp_path, 50)
    try:
        _bypass_append_only_triggers(conn)

        # Adversarial tamper drill: Mutate action
        conn.execute("UPDATE audit_events SET action = 'UNAUTHORIZED_DELETE' WHERE sequence = 10")
        conn.commit()

        result = verify_audit_events(conn)
        assert result.ok is False
        seq_10_issues = [issue for issue in result.issues if issue.sequence == 10]
        assert len(seq_10_issues) >= 1
        assert "Audit event hash does not match row content." in seq_10_issues[0].message
    finally:
        conn.close()


def test_tamper_row_metadata_json_detected(tmp_path: Path) -> None:
    """Mutating metadata_json on sequence 35 causes verify_audit_events to detect hash mismatch at seq 35."""
    conn = _create_clean_ledger(tmp_path, 50)
    try:
        _bypass_append_only_triggers(conn)

        conn.execute("UPDATE audit_events SET metadata_json = '{\"tampered\": true}' WHERE sequence = 35")
        conn.commit()

        result = verify_audit_events(conn)
        assert result.ok is False
        seq_35_issues = [issue for issue in result.issues if issue.sequence == 35]
        assert len(seq_35_issues) >= 1
        assert "Audit event hash does not match row content." in seq_35_issues[0].message
    finally:
        conn.close()


def test_tamper_row_deletion_detected(tmp_path: Path) -> None:
    """Deleting sequence 20 causes verify_audit_events to detect sequence discontinuity and previous_hash mismatch."""
    conn = _create_clean_ledger(tmp_path, 50)
    try:
        _bypass_append_only_triggers(conn)

        # Adversarial tamper drill: Delete an intermediate row
        conn.execute("DELETE FROM audit_events WHERE sequence = 20")
        conn.commit()

        result = verify_audit_events(conn)
        assert result.ok is False

        # Issue reported at sequence 21: sequence is not contiguous (expected 20, got 21)
        # and previous_hash does not match ledger head
        seq_21_issues = [issue for issue in result.issues if issue.sequence == 21]
        assert len(seq_21_issues) >= 1
        messages = [issue.message for issue in seq_21_issues]
        assert any("not contiguous" in msg for msg in messages)
        assert any("previous hash does not match" in msg for msg in messages)
    finally:
        conn.close()


def test_tamper_sequence_order_swap_detected(tmp_path: Path) -> None:
    """Swapping sequence numbers between rows 15 and 16 causes verification failure."""
    conn = _create_clean_ledger(tmp_path, 50)
    try:
        _bypass_append_only_triggers(conn)

        conn.execute("UPDATE audit_events SET sequence = 999 WHERE sequence = 15")
        conn.execute("UPDATE audit_events SET sequence = 15 WHERE sequence = 16")
        conn.execute("UPDATE audit_events SET sequence = 16 WHERE sequence = 999")
        conn.commit()

        result = verify_audit_events(conn)
        assert result.ok is False
        tampered_seqs = {issue.sequence for issue in result.issues}
        assert 15 in tampered_seqs or 16 in tampered_seqs
    finally:
        conn.close()


def test_tamper_ledger_state_head_hash_detected(tmp_path: Path) -> None:
    """Tampering with audit_ledger_state.last_event_hash triggers head hash mismatch."""
    conn = _create_clean_ledger(tmp_path, 50)
    try:
        conn.execute(
            "UPDATE audit_ledger_state SET last_event_hash = 'ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff' WHERE id = 1"
        )
        conn.commit()

        result = verify_audit_events(conn)
        assert result.ok is False
        head_issues = [
            issue for issue in result.issues
            if "Audit ledger state hash does not match final event hash." in issue.message
        ]
        assert len(head_issues) == 1
    finally:
        conn.close()


def test_tamper_ledger_state_last_sequence_detected(tmp_path: Path) -> None:
    """Tampering with audit_ledger_state.last_sequence triggers count mismatch."""
    conn = _create_clean_ledger(tmp_path, 50)
    try:
        conn.execute("UPDATE audit_ledger_state SET last_sequence = 100 WHERE id = 1")
        conn.commit()

        result = verify_audit_events(conn)
        assert result.ok is False
        seq_issues = [
            issue for issue in result.issues
            if "Audit ledger state sequence does not match event count." in issue.message
        ]
        assert len(seq_issues) == 1
    finally:
        conn.close()


def test_tamper_malformed_metadata_json_detected(tmp_path: Path) -> None:
    """Injecting invalid JSON syntax into metadata_json triggers metadata invalid issue."""
    conn = _create_clean_ledger(tmp_path, 50)
    try:
        _bypass_append_only_triggers(conn)

        conn.execute("UPDATE audit_events SET metadata_json = '{\"broken\": [unclosed' WHERE sequence = 12")
        conn.commit()

        result = verify_audit_events(conn)
        assert result.ok is False
        seq_12_issues = [issue for issue in result.issues if issue.sequence == 12]
        assert any("metadata is invalid" in issue.message for issue in seq_12_issues)
    finally:
        conn.close()
