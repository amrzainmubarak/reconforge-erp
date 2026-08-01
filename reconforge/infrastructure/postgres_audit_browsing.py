"""PostgreSQL adapter for the bounded, redacted audit-administration view."""

from __future__ import annotations

import hashlib
from typing import Any, cast

from reconforge.application.audit_browsing import (
    AuditBrowsingError,
    AuditChainVerification,
    AuditSource,
    AuditVerificationSummary,
    RedactedAuditEvent,
)
from reconforge.audit import AuditLedgerError
from reconforge.infrastructure.postgres_domain import PostgresAuditEventRepository
from reconforge.infrastructure.postgres_ledger import PostgresLedgerIntegrityError, PostgresLedgerRepository
from reconforge.io.persisted import PersistedJsonError, decode_audit_metadata, encode_audit_metadata


def _value(row: Any, name: str, index: int) -> object:
    if isinstance(row, dict):
        return row[name]
    try:
        return row[name]
    except (IndexError, KeyError, TypeError):
        return row[index]


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_metadata_digest(metadata_text: str) -> str:
    try:
        canonical = encode_audit_metadata(decode_audit_metadata(metadata_text).payload).text
    except PersistedJsonError as exc:
        raise AuditBrowsingError("Stored audit metadata is invalid.") from exc
    return _digest(canonical)


def _issue_code(message: str) -> str:
    normalized = message.casefold()
    if "sequence" in normalized and "contiguous" in normalized:
        return "sequence_not_contiguous"
    if "previous" in normalized and "hash" in normalized:
        return "previous_hash_mismatch"
    if "state" in normalized and "sequence" in normalized:
        return "ledger_state_sequence_mismatch"
    if "state" in normalized and "hash" in normalized:
        return "ledger_state_hash_mismatch"
    if "metadata" in normalized:
        return "metadata_invalid"
    if "event hash" in normalized or "hash does not match" in normalized:
        return "event_hash_mismatch"
    if "state row" in normalized and "missing" in normalized:
        return "ledger_state_missing"
    return "verification_issue"


class PostgresAuditBrowsingRepository:
    """Read two RLS-filtered chains without disclosing their sensitive fields."""

    def __init__(self, connection: Any, tenant_id: str) -> None:
        self.connection = connection
        self.tenant_id = tenant_id

    def list_redacted_events(
        self,
        *,
        limit: int,
        after_occurred_at: str | None = None,
        after_source: AuditSource | None = None,
        after_event_id: str | None = None,
    ) -> tuple[RedactedAuditEvent, ...]:
        if not 1 <= limit <= 201:
            raise AuditBrowsingError("Audit query limit is invalid.")
        if after_source is not None and after_source not in {"domain", "ledger_control"}:
            raise AuditBrowsingError("Audit cursor source is invalid.")
        if any(value is not None for value in (after_occurred_at, after_source, after_event_id)) and not all(
            value is not None for value in (after_occurred_at, after_source, after_event_id)
        ):
            raise AuditBrowsingError("Audit cursor continuation is incomplete.")
        rows = self.connection.execute(
            """
            WITH combined_events AS (
              SELECT
                'domain'::text AS source,
                id AS event_id,
                sequence,
                to_char(created_at::timestamptz AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS occurred_at,
                action,
                object_type,
                actor_user_id,
                actor_label,
                object_id,
                metadata_json::text AS metadata_text,
                previous_hash AS previous_event_hash,
                event_hash,
                before_hash AS before_state_hash,
                after_hash AS after_state_hash
              FROM reconforge.domain_audit_events
              WHERE tenant_id=%s
              UNION ALL
              SELECT
                'ledger_control'::text AS source,
                event_id,
                event_sequence AS sequence,
                to_char(occurred_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS occurred_at,
                action,
                resource_type AS object_type,
                actor_id AS actor_user_id,
                ''::text AS actor_label,
                resource_id AS object_id,
                metadata::text AS metadata_text,
                previous_event_hash,
                event_hash,
                before_state_hash,
                after_state_hash
              FROM reconforge.audit_events
              WHERE tenant_id=%s
            )
            SELECT source,event_id,sequence,occurred_at,action,object_type,actor_user_id,actor_label,
                   object_id,metadata_text,previous_event_hash,event_hash,before_state_hash,after_state_hash
            FROM combined_events
            WHERE (%s::text IS NULL OR (occurred_at,source,event_id)>(%s::text,%s::text,%s::text))
            ORDER BY occurred_at ASC,source ASC,event_id ASC
            LIMIT %s
            """,
            (
                self.tenant_id,
                self.tenant_id,
                after_occurred_at,
                after_occurred_at,
                after_source,
                after_event_id,
                limit,
            ),
        ).fetchall()
        records: list[RedactedAuditEvent] = []
        for row in rows:
            source = str(_value(row, "source", 0))
            if source not in {"domain", "ledger_control"}:
                raise AuditBrowsingError("Stored audit source is invalid.")
            actor_user_id = _value(row, "actor_user_id", 6)
            actor_label = str(_value(row, "actor_label", 7) or "")
            actor_material = f"user:{actor_user_id}" if actor_user_id is not None else f"label:{actor_label}"
            records.append(
                RedactedAuditEvent(
                    source=cast(AuditSource, source),
                    event_id=str(_value(row, "event_id", 1)),
                    sequence=int(cast(Any, _value(row, "sequence", 2))),
                    occurred_at=str(_value(row, "occurred_at", 3)),
                    action=str(_value(row, "action", 4)),
                    object_type=str(_value(row, "object_type", 5)),
                    actor_digest=_digest(actor_material),
                    object_digest=_digest(str(_value(row, "object_id", 8))),
                    metadata_digest=_canonical_metadata_digest(str(_value(row, "metadata_text", 9))),
                    previous_event_hash=str(_value(row, "previous_event_hash", 10)),
                    event_hash=str(_value(row, "event_hash", 11)),
                    before_state_hash=(
                        None
                        if _value(row, "before_state_hash", 12) is None
                        else str(_value(row, "before_state_hash", 12))
                    ),
                    after_state_hash=(
                        None
                        if _value(row, "after_state_hash", 13) is None
                        else str(_value(row, "after_state_hash", 13))
                    ),
                )
            )
        return tuple(records)

    def verify_chains(self) -> AuditVerificationSummary:
        try:
            domain = PostgresAuditEventRepository(self.connection, self.tenant_id).verify()
            ledger = PostgresLedgerRepository(self.connection).verify_audit_events(tenant_id=self.tenant_id)
        except (AuditLedgerError, PostgresLedgerIntegrityError) as exc:
            raise AuditBrowsingError("Audit chain verification could not complete.") from exc
        domain_chain = AuditChainVerification(
            source="domain",
            ok=domain.ok,
            checked_events=domain.checked_events,
            head_hash=domain.head_hash,
            issue_codes=tuple(sorted({_issue_code(issue.message) for issue in domain.issues})),
        )
        ledger_chain = AuditChainVerification(
            source="ledger_control",
            ok=bool(ledger["ok"]),
            checked_events=int(ledger["checked_events"]),
            head_hash=str(ledger["head_hash"]),
            issue_codes=tuple(
                sorted({_issue_code(str(issue.get("message", ""))) for issue in ledger["issues"]})
            ),
        )
        return AuditVerificationSummary(
            ok=domain_chain.ok and ledger_chain.ok,
            chains=(domain_chain, ledger_chain),
        )
