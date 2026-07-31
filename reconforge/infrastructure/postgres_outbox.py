"""Tenant-scoped PostgreSQL transactional-outbox delivery primitives."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from reconforge.application.outbox import OutboxError, OutboxEvent, OutboxRepositoryProtocol
from reconforge.infrastructure.postgres import PostgresConfigurationError, normalize_scope_id, validate_tenant_id
from reconforge.io.persisted import (
    PersistedJsonError,
    decode_postgres_outbox_payload,
    encode_postgres_outbox_payload,
)

_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_STATUSES = ("Pending", "Claimed", "Published", "Dead")
_LIST_STATUSES = {"pending", "claimed", "published", "dead", "all"}
_LIST_OUTBOX_EVENT_QUERIES: dict[str, str] = {
    "all": (
        "SELECT tenant_id, event_id, event_type, aggregate_type, aggregate_id, payload, "
        "status, attempt_count, available_at, claimed_at, claimed_by, published_at, last_error, "
        "dead_lettered_at, created_at "
        "FROM reconforge.outbox_events "
        "WHERE tenant_id = %s "
        "ORDER BY created_at, event_id "
        "LIMIT %s"
    ),
    "pending": (
        "SELECT tenant_id, event_id, event_type, aggregate_type, aggregate_id, payload, "
        "status, attempt_count, available_at, claimed_at, claimed_by, published_at, last_error, "
        "dead_lettered_at, created_at "
        "FROM reconforge.outbox_events "
        "WHERE tenant_id = %s AND status IN ('Pending', 'Claimed') "
        "ORDER BY created_at, event_id "
        "LIMIT %s"
    ),
    "claimed": (
        "SELECT tenant_id, event_id, event_type, aggregate_type, aggregate_id, payload, "
        "status, attempt_count, available_at, claimed_at, claimed_by, published_at, last_error, "
        "dead_lettered_at, created_at "
        "FROM reconforge.outbox_events "
        "WHERE tenant_id = %s AND status = 'Claimed' "
        "ORDER BY created_at, event_id "
        "LIMIT %s"
    ),
    "published": (
        "SELECT tenant_id, event_id, event_type, aggregate_type, aggregate_id, payload, "
        "status, attempt_count, available_at, claimed_at, claimed_by, published_at, last_error, "
        "dead_lettered_at, created_at "
        "FROM reconforge.outbox_events "
        "WHERE tenant_id = %s AND status = 'Published' "
        "ORDER BY created_at, event_id "
        "LIMIT %s"
    ),
    "dead": (
        "SELECT tenant_id, event_id, event_type, aggregate_type, aggregate_id, payload, "
        "status, attempt_count, available_at, claimed_at, claimed_by, published_at, last_error, "
        "dead_lettered_at, created_at "
        "FROM reconforge.outbox_events "
        "WHERE tenant_id = %s AND status = 'Dead' "
        "ORDER BY created_at, event_id "
        "LIMIT %s"
    ),
}

POSTGRES_OUTBOX_APPLICATION_SCHEMA_SQL = r"""
ALTER TABLE reconforge.outbox_events ADD COLUMN IF NOT EXISTS dead_lettered_at TIMESTAMPTZ;

CREATE OR REPLACE FUNCTION reconforge.outbox_application_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='UPDATE' AND (NEW.event_type,NEW.aggregate_type,NEW.aggregate_id,NEW.payload,NEW.created_at)
  IS DISTINCT FROM (OLD.event_type,OLD.aggregate_type,OLD.aggregate_id,OLD.payload,OLD.created_at)
 THEN RAISE EXCEPTION 'outbox event identity and payload are immutable'; END IF;
 IF NEW.status='Pending' AND (NEW.claimed_at IS NOT NULL OR NEW.claimed_by IS NOT NULL
  OR NEW.published_at IS NOT NULL OR NEW.dead_lettered_at IS NOT NULL)
 THEN RAISE EXCEPTION 'pending outbox state has inconsistent delivery metadata'; END IF;
 IF NEW.status='Claimed' AND (NEW.claimed_at IS NULL OR NEW.claimed_by IS NULL
  OR NEW.published_at IS NOT NULL OR NEW.dead_lettered_at IS NOT NULL)
 THEN RAISE EXCEPTION 'claimed outbox state requires an exclusive lease'; END IF;
 IF NEW.status='Published' AND (NEW.published_at IS NULL OR NEW.claimed_at IS NOT NULL
  OR NEW.claimed_by IS NOT NULL OR NEW.dead_lettered_at IS NOT NULL)
 THEN RAISE EXCEPTION 'published outbox state has inconsistent delivery metadata'; END IF;
 IF NEW.status='Dead' AND (NEW.dead_lettered_at IS NULL OR NEW.claimed_at IS NOT NULL
  OR NEW.claimed_by IS NOT NULL OR NEW.published_at IS NOT NULL)
 THEN RAISE EXCEPTION 'dead outbox state requires exclusive transition evidence'; END IF;
 RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS outbox_application_state_guard ON reconforge.outbox_events;
CREATE TRIGGER outbox_application_state_guard BEFORE INSERT OR UPDATE ON reconforge.outbox_events
 FOR EACH ROW EXECUTE FUNCTION reconforge.outbox_application_guard();
"""


class PostgresOutboxValidationError(ValueError):
    """Raised when outbox delivery input is invalid."""


class PostgresOutboxIntegrityError(RuntimeError):
    """Raised when a delivery state transition is not owned by the caller."""


def _tenant_id(value: object) -> str:
    try:
        return validate_tenant_id(str(value))
    except PostgresConfigurationError as exc:
        raise PostgresOutboxValidationError(str(exc)) from exc


def _identifier(value: object, field_name: str) -> str:
    try:
        normalized = normalize_scope_id(str(value), field_name=field_name)
    except PostgresConfigurationError as exc:
        raise PostgresOutboxValidationError(str(exc)) from exc
    if not _ID_PATTERN.fullmatch(normalized):
        raise PostgresOutboxValidationError(f"{field_name} has an invalid identifier.")
    return normalized


def _text(value: object, field_name: str, *, maximum: int = 160) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise PostgresOutboxValidationError(f"{field_name} must not be blank.")
    if len(normalized) > maximum:
        raise PostgresOutboxValidationError(f"{field_name} must be at most {maximum} characters.")
    if any(ord(character) < 32 or ord(character) == 127 for character in normalized):
        raise PostgresOutboxValidationError(f"{field_name} must contain printable characters only.")
    return " ".join(normalized.split())


def _row_value(row: Any, key: str, index: int) -> Any:
    if isinstance(row, Mapping):
        return row.get(key)
    return row[index]


def _metadata(value: object) -> tuple[dict[str, Any], str]:
    try:
        decoded = decode_postgres_outbox_payload(value)
        canonical = encode_postgres_outbox_payload(decoded.payload)
    except PersistedJsonError as exc:
        raise PostgresOutboxIntegrityError("Stored outbox payload is invalid.") from exc
    return canonical.payload, canonical.text


@dataclass(frozen=True)
class PostgresOutboxEvent:
    """Immutable event snapshot handed to an external publisher."""

    tenant_id: str
    id: str
    event_type: str
    aggregate_type: str
    aggregate_id: str
    payload: dict[str, Any]
    payload_json: str
    status: str
    attempt_count: int
    available_at: str | None
    claimed_at: str | None
    claimed_by: str | None
    published_at: str | None
    last_error: str | None
    dead_lettered_at: str | None
    created_at: str


@dataclass(frozen=True)
class PostgresOutboxRepository:
    """Claim and transition PostgreSQL outbox events without committing."""

    connection: Any

    def _event(self, row: Any) -> PostgresOutboxEvent:
        payload, payload_json = _metadata(_row_value(row, "payload", 5))
        return PostgresOutboxEvent(
            tenant_id=str(_row_value(row, "tenant_id", 0)),
            id=str(_row_value(row, "event_id", 1)),
            event_type=str(_row_value(row, "event_type", 2)),
            aggregate_type=str(_row_value(row, "aggregate_type", 3)),
            aggregate_id=str(_row_value(row, "aggregate_id", 4)),
            payload=payload,
            payload_json=payload_json,
            status=str(_row_value(row, "status", 6)),
            attempt_count=int(_row_value(row, "attempt_count", 7)),
            available_at=self._optional_timestamp(_row_value(row, "available_at", 8)),
            claimed_at=self._optional_timestamp(_row_value(row, "claimed_at", 9)),
            claimed_by=str(_row_value(row, "claimed_by", 10)) if _row_value(row, "claimed_by", 10) else None,
            published_at=self._optional_timestamp(_row_value(row, "published_at", 11)),
            last_error=str(_row_value(row, "last_error", 12)) if _row_value(row, "last_error", 12) else None,
            dead_lettered_at=self._optional_timestamp(_row_value(row, "dead_lettered_at", 13)),
            created_at=str(_row_value(row, "created_at", 14)),
        )

    @staticmethod
    def _optional_timestamp(value: object) -> str | None:
        return str(value) if value is not None else None

    @staticmethod
    def _validate_limit(limit: int, *, maximum: int = 1_000) -> int:
        if not 1 <= int(limit) <= maximum:
            raise PostgresOutboxValidationError(f"limit must be between 1 and {maximum}.")
        return int(limit)

    @staticmethod
    def _validate_attempts(max_attempts: int) -> int:
        if not 1 <= int(max_attempts) <= 100:
            raise PostgresOutboxValidationError("max_attempts must be between 1 and 100.")
        return int(max_attempts)

    @staticmethod
    def _validate_seconds(value: int, field_name: str, *, allow_zero: bool = False) -> int:
        minimum = 0 if allow_zero else 1
        if not minimum <= int(value) <= 86_400:
            raise PostgresOutboxValidationError(f"{field_name} is outside its supported range.")
        return int(value)

    def claim_pending(
        self,
        *,
        tenant_id: str,
        worker_id: str,
        limit: int = 50,
        max_attempts: int = 5,
        lease_seconds: int = 300,
    ) -> list[PostgresOutboxEvent]:
        """Atomically claim ready or expired events using PostgreSQL row locks."""

        tenant = _tenant_id(tenant_id)
        worker = _text(worker_id, "worker_id")
        selected_limit = self._validate_limit(limit)
        attempts = self._validate_attempts(max_attempts)
        lease = self._validate_seconds(lease_seconds, "lease_seconds")
        cursor = self.connection.execute(
            """
            WITH candidates AS (
                SELECT tenant_id, event_id
                FROM reconforge.outbox_events
                WHERE tenant_id = %s
                  AND attempt_count < %s
                  AND available_at <= now()
                  AND (status = 'Pending' OR (status = 'Claimed' AND claimed_at <= now()))
                ORDER BY available_at, created_at, event_id
                FOR UPDATE SKIP LOCKED
                LIMIT %s
            ), claimed AS (
                UPDATE reconforge.outbox_events AS events
                SET status = 'Claimed',
                    claimed_at = now() + (%s * INTERVAL '1 second'),
                    claimed_by = %s,
                    attempt_count = events.attempt_count + 1
                FROM candidates
                WHERE events.tenant_id = candidates.tenant_id
                  AND events.event_id = candidates.event_id
                RETURNING events.tenant_id, events.event_id, events.event_type,
                          events.aggregate_type, events.aggregate_id, events.payload,
                          events.status, events.attempt_count, events.available_at,
                          events.claimed_at, events.claimed_by, events.published_at,
                          events.last_error, events.dead_lettered_at, events.created_at
            )
            SELECT tenant_id, event_id, event_type, aggregate_type, aggregate_id,
                   payload, status, attempt_count, available_at, claimed_at, claimed_by,
                   published_at, last_error, dead_lettered_at, created_at
            FROM claimed
            ORDER BY available_at, created_at, event_id
            """,
            (tenant, attempts, selected_limit, lease, worker),
        )
        return [self._event(row) for row in cursor.fetchall()]

    def mark_published(self, *, tenant_id: str, event_id: str, worker_id: str) -> None:
        """Acknowledge one event only for the worker holding its lease."""

        tenant = _tenant_id(tenant_id)
        identifier = _identifier(event_id, "event_id")
        worker = _text(worker_id, "worker_id")
        cursor = self.connection.execute(
            """
            UPDATE reconforge.outbox_events
            SET status = 'Published', published_at = now(), claimed_at = NULL,
                claimed_by = NULL, last_error = NULL
            WHERE tenant_id = %s AND event_id = %s AND status = 'Claimed' AND claimed_by = %s
            """,
            (tenant, identifier, worker),
        )
        if cursor.rowcount != 1:
            raise PostgresOutboxIntegrityError("Outbox event is not leased by this worker or is already published.")

    def mark_failed(
        self,
        *,
        tenant_id: str,
        event_id: str,
        worker_id: str,
        error: str,
        max_attempts: int = 5,
        retry_base_seconds: int = 5,
    ) -> bool:
        """Release one lease for retry and return whether it became dead-lettered."""

        tenant = _tenant_id(tenant_id)
        identifier = _identifier(event_id, "event_id")
        worker = _text(worker_id, "worker_id")
        attempts = self._validate_attempts(max_attempts)
        retry_base = self._validate_seconds(retry_base_seconds, "retry_base_seconds", allow_zero=True)
        safe_error = (str(error).strip() or "publisher failure")[:1_000]
        row = self.connection.execute(
            """
            SELECT attempt_count
            FROM reconforge.outbox_events
            WHERE tenant_id = %s AND event_id = %s AND status = 'Claimed' AND claimed_by = %s
            FOR UPDATE
            """,
            (tenant, identifier, worker),
        ).fetchone()
        if row is None:
            raise PostgresOutboxIntegrityError("Outbox event is not leased by this worker.")
        attempt_count = int(_row_value(row, "attempt_count", 0))
        dead_lettered = attempt_count >= attempts
        if dead_lettered:
            cursor = self.connection.execute(
                """
                UPDATE reconforge.outbox_events
                SET status = 'Dead', last_error = %s, claimed_at = NULL, claimed_by = NULL,
                    dead_lettered_at = now()
                WHERE tenant_id = %s AND event_id = %s AND status = 'Claimed' AND claimed_by = %s
                """,
                (safe_error, tenant, identifier, worker),
            )
        else:
            backoff = retry_base * (2 ** max(attempt_count - 1, 0))
            cursor = self.connection.execute(
                """
                UPDATE reconforge.outbox_events
                SET status = 'Pending', last_error = %s,
                    available_at = now() + (%s * INTERVAL '1 second'),
                    claimed_at = NULL, claimed_by = NULL, dead_lettered_at = NULL
                WHERE tenant_id = %s AND event_id = %s AND status = 'Claimed' AND claimed_by = %s
                """,
                (safe_error, backoff, tenant, identifier, worker),
            )
        if cursor.rowcount != 1:
            raise PostgresOutboxIntegrityError("Outbox event lease changed before failure state was saved.")
        return dead_lettered

    def replay_dead(self, *, tenant_id: str, event_id: str) -> None:
        """Reset one dead-lettered event for explicit operator replay."""

        tenant = _tenant_id(tenant_id)
        identifier = _identifier(event_id, "event_id")
        cursor = self.connection.execute(
            """
            UPDATE reconforge.outbox_events
            SET status = 'Pending', attempt_count = 0, available_at = now(),
                claimed_at = NULL, claimed_by = NULL, published_at = NULL, last_error = NULL,
                dead_lettered_at = NULL
            WHERE tenant_id = %s AND event_id = %s AND status = 'Dead'
            """,
            (tenant, identifier),
        )
        if cursor.rowcount != 1:
            raise PostgresOutboxIntegrityError("Outbox event is not dead-lettered or is already published.")

    def list_events(self, *, tenant_id: str, status: str = "pending", limit: int = 100) -> list[PostgresOutboxEvent]:
        """List tenant events in deterministic delivery order."""

        tenant = _tenant_id(tenant_id)
        selected_status = str(status or "").strip().casefold()
        if selected_status not in _LIST_STATUSES:
            raise PostgresOutboxValidationError("status must be pending, claimed, published, dead, or all.")
        selected_limit = self._validate_limit(limit, maximum=10_000)
        query = _LIST_OUTBOX_EVENT_QUERIES[selected_status]
        cursor = self.connection.execute(query, (tenant, selected_limit))
        return [self._event(row) for row in cursor.fetchall()]

    def summary(self, *, tenant_id: str) -> dict[str, int | str]:
        """Return tenant-scoped delivery counts."""

        tenant = _tenant_id(tenant_id)
        cursor = self.connection.execute(
            """
            SELECT
                COUNT(*) FILTER (WHERE status = 'Pending') AS pending,
                COUNT(*) FILTER (WHERE status = 'Claimed') AS claimed,
                COUNT(*) FILTER (WHERE status = 'Published') AS published,
                COUNT(*) FILTER (WHERE status = 'Dead') AS dead
            FROM reconforge.outbox_events
            WHERE tenant_id = %s
            """,
            (tenant,),
        )
        row = cursor.fetchone()
        if row is None:
            raise PostgresOutboxIntegrityError("PostgreSQL outbox summary returned no record.")
        return {
            "tenant_id": tenant,
            "pending": int(_row_value(row, "pending", 0) or 0),
            "claimed": int(_row_value(row, "claimed", 1) or 0),
            "published": int(_row_value(row, "published", 2) or 0),
            "dead": int(_row_value(row, "dead", 3) or 0),
        }


@dataclass(frozen=True)
class TenantBoundPostgresOutboxRepository:
    """Bind the generic outbox contract to exactly one validated tenant.

    PostgreSQL keeps tenant scope explicit at the persistence boundary.  This
    adapter captures that scope once so the backend-neutral application service
    cannot accidentally mix tenants or omit the tenant predicate.
    """

    repository: PostgresOutboxRepository
    tenant_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "tenant_id", _tenant_id(self.tenant_id))

    @staticmethod
    def _event(event: PostgresOutboxEvent) -> OutboxEvent:
        return OutboxEvent(
            id=event.id,
            event_type=event.event_type,
            aggregate_type=event.aggregate_type,
            aggregate_id=event.aggregate_id,
            payload_json=event.payload_json,
            created_at=event.created_at,
            published_at=event.published_at,
            attempts=event.attempt_count,
            last_error=event.last_error,
            available_at=event.available_at,
            locked_at=event.claimed_at,
            locked_by=event.claimed_by,
            dead_lettered_at=event.dead_lettered_at,
        )

    @staticmethod
    def _translate(operation: Any) -> Any:
        try:
            return operation()
        except (PostgresOutboxValidationError, PostgresOutboxIntegrityError) as exc:
            raise OutboxError(str(exc)) from exc

    def claim_pending(
        self,
        *,
        worker_id: str,
        limit: int = 50,
        max_attempts: int = 5,
        lease_seconds: int = 300,
    ) -> list[OutboxEvent]:
        events = self._translate(
            lambda: self.repository.claim_pending(
                tenant_id=self.tenant_id,
                worker_id=worker_id,
                limit=limit,
                max_attempts=max_attempts,
                lease_seconds=lease_seconds,
            )
        )
        return [self._event(event) for event in events]

    def mark_published(self, *, event_id: str, worker_id: str) -> None:
        self._translate(
            lambda: self.repository.mark_published(tenant_id=self.tenant_id, event_id=event_id, worker_id=worker_id)
        )

    def mark_failed(
        self,
        *,
        event_id: str,
        worker_id: str,
        error: str,
        max_attempts: int = 5,
        retry_base_seconds: int = 5,
    ) -> bool:
        return bool(
            self._translate(
                lambda: self.repository.mark_failed(
                    tenant_id=self.tenant_id,
                    event_id=event_id,
                    worker_id=worker_id,
                    error=error,
                    max_attempts=max_attempts,
                    retry_base_seconds=retry_base_seconds,
                )
            )
        )

    def requeue_dead_letter(self, *, event_id: str) -> None:
        self._translate(lambda: self.repository.replay_dead(tenant_id=self.tenant_id, event_id=event_id))

    def list_events(self, *, status: str = "pending", limit: int = 100) -> list[OutboxEvent]:
        postgres_status = "dead" if status == "dead_letter" else status
        events = self._translate(
            lambda: self.repository.list_events(tenant_id=self.tenant_id, status=postgres_status, limit=limit)
        )
        return [self._event(event) for event in events]


def tenant_bound_postgres_outbox_repository(connection: Any, *, tenant_id: str) -> OutboxRepositoryProtocol:
    """Construct the PostgreSQL adapter through the public repository contract."""

    return TenantBoundPostgresOutboxRepository(repository=PostgresOutboxRepository(connection), tenant_id=tenant_id)
