"""Append-only audit event creation and hash-chain verification."""

from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
import uuid
from dataclasses import dataclass
from typing import Any

from reconforge.domain.models import AuditEventReference, utc_now_text
from reconforge.io.persisted import (
    PersistedJsonError,
    decode_audit_metadata,
    encode_audit_metadata,
)

GENESIS_AUDIT_HASH = "0000000000000000000000000000000000000000000000000000000000000000"


class AuditLedgerError(ValueError):
    """Raised for safe, user-facing audit ledger errors."""


@dataclass(frozen=True)
class AuditVerificationIssue:
    """One audit ledger verification issue."""

    sequence: int | None
    message: str


@dataclass(frozen=True)
class AuditVerificationResult:
    """Audit ledger verification result."""

    ok: bool
    checked_events: int
    issues: list[AuditVerificationIssue]
    head_hash: str


def _require_text(value: str, label: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise AuditLedgerError(f"Audit event {label} is required.")
    return cleaned


def _metadata_to_json(metadata: dict[str, Any] | None) -> str:
    try:
        return encode_audit_metadata(metadata).text
    except PersistedJsonError as exc:
        raise AuditLedgerError("Audit event metadata must be JSON-serializable.") from exc


def _metadata_from_json(value: str) -> dict[str, Any]:
    try:
        return decode_audit_metadata(value).payload
    except PersistedJsonError as exc:
        raise AuditLedgerError("Stored audit event metadata is invalid.") from exc


def _event_hash_payload(
    *,
    event_id: str,
    sequence: int,
    previous_hash: str,
    actor_user_id: str | None,
    actor_label: str,
    object_type: str,
    object_id: str,
    action: str,
    before_hash: str | None,
    after_hash: str | None,
    metadata_json: str,
    created_at: str,
) -> dict[str, Any]:
    return {
        "action": action,
        "actor_label": actor_label,
        "actor_user_id": actor_user_id,
        "after_hash": after_hash,
        "before_hash": before_hash,
        "created_at": created_at,
        "id": event_id,
        "metadata_json": metadata_json,
        "object_id": object_id,
        "object_type": object_type,
        "previous_hash": previous_hash,
        "sequence": sequence,
    }


def _calculate_event_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _row_hash(row: sqlite3.Row) -> str:
    payload = _event_hash_payload(
        event_id=str(row["id"]),
        sequence=int(row["sequence"]),
        previous_hash=str(row["previous_hash"]),
        actor_user_id=str(row["actor_user_id"]) if row["actor_user_id"] is not None else None,
        actor_label=str(row["actor_label"]),
        object_type=str(row["object_type"]),
        object_id=str(row["object_id"]),
        action=str(row["action"]),
        before_hash=str(row["before_hash"]) if row["before_hash"] is not None else None,
        after_hash=str(row["after_hash"]) if row["after_hash"] is not None else None,
        metadata_json=str(row["metadata_json"]),
        created_at=str(row["created_at"]),
    )
    return _calculate_event_hash(payload)


def _row_to_event(row: sqlite3.Row) -> AuditEventReference:
    return AuditEventReference(
        id=str(row["id"]),
        sequence=int(row["sequence"]),
        previous_hash=str(row["previous_hash"]),
        event_hash=str(row["event_hash"]),
        actor_user_id=str(row["actor_user_id"]) if row["actor_user_id"] is not None else None,
        actor_label=str(row["actor_label"]),
        object_type=str(row["object_type"]),
        object_id=str(row["object_id"]),
        action=str(row["action"]),
        before_hash=str(row["before_hash"]) if row["before_hash"] is not None else None,
        after_hash=str(row["after_hash"]) if row["after_hash"] is not None else None,
        metadata=_metadata_from_json(str(row["metadata_json"])),
        created_at=str(row["created_at"]),
    )


def append_audit_event(
    connection: sqlite3.Connection,
    *,
    actor_label: str,
    object_type: str,
    object_id: str,
    action: str,
    actor_user_id: str | None = None,
    before_hash: str | None = None,
    after_hash: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> AuditEventReference:
    """Append one audit event and update the local ledger head."""

    actor = _require_text(actor_label, "actor_label")
    target_type = _require_text(object_type, "object_type")
    target_id = _require_text(object_id, "object_id")
    event_action = _require_text(action, "action")
    metadata_json = _metadata_to_json(metadata)
    event_id = f"AE-{uuid.uuid4().hex}"
    created_at = utc_now_text()

    owns_transaction = not connection.in_transaction
    try:
        if owns_transaction:
            connection.execute("BEGIN IMMEDIATE")
        state = connection.execute(
            "SELECT last_sequence, last_event_hash FROM audit_ledger_state WHERE id = 1",
        ).fetchone()
        if state is None:
            raise AuditLedgerError("Audit ledger is not initialized. Run 'reconforge db init' first.")
        sequence = int(state["last_sequence"]) + 1
        previous_hash = str(state["last_event_hash"])
        payload = _event_hash_payload(
            event_id=event_id,
            sequence=sequence,
            previous_hash=previous_hash,
            actor_user_id=actor_user_id,
            actor_label=actor,
            object_type=target_type,
            object_id=target_id,
            action=event_action,
            before_hash=before_hash,
            after_hash=after_hash,
            metadata_json=metadata_json,
            created_at=created_at,
        )
        event_hash = _calculate_event_hash(payload)
        connection.execute(
            """
            INSERT INTO audit_events (
                id, sequence, previous_hash, event_hash, actor_user_id, actor_label,
                object_type, object_id, action, before_hash, after_hash, metadata_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                sequence,
                previous_hash,
                event_hash,
                actor_user_id,
                actor,
                target_type,
                target_id,
                event_action,
                before_hash,
                after_hash,
                metadata_json,
                created_at,
            ),
        )
        connection.execute(
            "UPDATE audit_ledger_state SET last_sequence = ?, last_event_hash = ?, updated_at = ? WHERE id = 1",
            (sequence, event_hash, created_at),
        )
        if owns_transaction:
            connection.commit()
    except AuditLedgerError:
        if owns_transaction:
            connection.rollback()
        raise
    except sqlite3.DatabaseError as exc:
        if owns_transaction:
            connection.rollback()
        raise AuditLedgerError("Unable to append audit event. Run 'reconforge db init' and retry.") from exc

    return AuditEventReference(
        id=event_id,
        sequence=sequence,
        previous_hash=previous_hash,
        event_hash=event_hash,
        actor_user_id=actor_user_id,
        actor_label=actor,
        object_type=target_type,
        object_id=target_id,
        action=event_action,
        before_hash=before_hash,
        after_hash=after_hash,
        metadata=_metadata_from_json(metadata_json),
        created_at=created_at,
    )


def list_audit_events(connection: sqlite3.Connection, *, limit: int | None = None) -> list[AuditEventReference]:
    """List audit events in ledger sequence order."""

    try:
        if limit is None:
            rows = connection.execute("SELECT * FROM audit_events ORDER BY sequence").fetchall()
        else:
            if limit < 1:
                raise AuditLedgerError("Audit event limit must be greater than zero.")
            rows = connection.execute("SELECT * FROM audit_events ORDER BY sequence LIMIT ?", (limit,)).fetchall()
    except sqlite3.DatabaseError as exc:
        raise AuditLedgerError("Unable to read audit events. Run 'reconforge db init' and retry.") from exc
    return [_row_to_event(row) for row in rows]


def verify_audit_events(connection: sqlite3.Connection) -> AuditVerificationResult:
    """Verify audit event sequence, previous-hash links, event hashes, and local head."""

    issues: list[AuditVerificationIssue] = []
    try:
        rows = connection.execute("SELECT * FROM audit_events ORDER BY sequence").fetchall()
        state = connection.execute(
            "SELECT last_sequence, last_event_hash FROM audit_ledger_state WHERE id = 1",
        ).fetchone()
    except sqlite3.DatabaseError as exc:
        raise AuditLedgerError("Unable to verify audit events. Run 'reconforge db init' and retry.") from exc

    expected_sequence = 1
    expected_previous_hash = GENESIS_AUDIT_HASH
    for row in rows:
        sequence = int(row["sequence"])
        try:
            decode_audit_metadata(str(row["metadata_json"]))
        except PersistedJsonError:
            issues.append(AuditVerificationIssue(sequence=sequence, message="Audit event metadata is invalid."))
        if sequence != expected_sequence:
            issues.append(AuditVerificationIssue(sequence=sequence, message="Audit event sequence is not contiguous."))
        previous_hash = str(row["previous_hash"])
        if previous_hash != expected_previous_hash:
            issues.append(AuditVerificationIssue(sequence=sequence, message="Audit event previous hash does not match ledger head."))
        expected_hash = _row_hash(row)
        actual_hash = str(row["event_hash"])
        if not hmac.compare_digest(actual_hash, expected_hash):
            issues.append(AuditVerificationIssue(sequence=sequence, message="Audit event hash does not match row content."))
        expected_previous_hash = actual_hash
        expected_sequence += 1

    if state is None:
        issues.append(AuditVerificationIssue(sequence=None, message="Audit ledger state row is missing."))
    else:
        last_sequence = int(state["last_sequence"])
        last_event_hash = str(state["last_event_hash"])
        if last_sequence != len(rows):
            issues.append(AuditVerificationIssue(sequence=None, message="Audit ledger state sequence does not match event count."))
        if last_event_hash != expected_previous_hash:
            issues.append(AuditVerificationIssue(sequence=None, message="Audit ledger state hash does not match final event hash."))

    return AuditVerificationResult(
        ok=not issues,
        checked_events=len(rows),
        issues=issues,
        head_hash=expected_previous_hash,
    )
