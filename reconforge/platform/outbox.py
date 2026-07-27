"""Transactional outbox claiming, publishing, retry, and dead-letter state."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from reconforge.domain.models import utc_now_text


class OutboxError(ValueError):
    """Raised for safe outbox delivery errors."""


class OutboxPublisher(Protocol):
    """Injected event sink; transport concerns stay outside the local outbox."""

    def publish(self, event: OutboxEvent) -> None:
        """Publish one event or raise an exception that can be retried."""


@dataclass(frozen=True)
class OutboxEvent:
    """Immutable event snapshot handed to a publisher."""

    id: str
    event_type: str
    aggregate_type: str
    aggregate_id: str
    payload_json: str
    created_at: str
    published_at: str | None
    attempts: int
    last_error: str | None
    available_at: str | None
    locked_at: str | None
    locked_by: str | None
    dead_lettered_at: str | None

    @classmethod
    def from_row(cls, row: sqlite3.Row | dict[str, Any]) -> OutboxEvent:
        return cls(
            id=str(row["id"]),
            event_type=str(row["event_type"]),
            aggregate_type=str(row["aggregate_type"]),
            aggregate_id=str(row["aggregate_id"]),
            payload_json=str(row["payload_json"]),
            created_at=str(row["created_at"]),
            published_at=str(row["published_at"]) if row["published_at"] is not None else None,
            attempts=int(row["attempts"]),
            last_error=str(row["last_error"]) if row["last_error"] is not None else None,
            available_at=str(row["available_at"]) if row["available_at"] is not None else None,
            locked_at=str(row["locked_at"]) if row["locked_at"] is not None else None,
            locked_by=str(row["locked_by"]) if row["locked_by"] is not None else None,
            dead_lettered_at=str(row["dead_lettered_at"]) if row["dead_lettered_at"] is not None else None,
        )


@dataclass(frozen=True)
class OutboxProcessResult:
    """Counts from one bounded publisher pass."""

    claimed: int
    published: int
    failed: int
    dead_lettered: int


OUTBOX_LIST_QUERIES = {
    "pending": """
        SELECT * FROM outbox_events
        WHERE published_at IS NULL AND dead_lettered_at IS NULL
        ORDER BY created_at, id
        LIMIT ?
    """,
    "published": """
        SELECT * FROM outbox_events
        WHERE published_at IS NOT NULL
        ORDER BY created_at, id
        LIMIT ?
    """,
    "dead_letter": """
        SELECT * FROM outbox_events
        WHERE dead_lettered_at IS NOT NULL AND published_at IS NULL
        ORDER BY created_at, id
        LIMIT ?
    """,
    "all": """
        SELECT * FROM outbox_events
        ORDER BY created_at, id
        LIMIT ?
    """,
}


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _utc_after(seconds: int) -> str:
    return (datetime.now(UTC) + timedelta(seconds=seconds)).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class OutboxService:
    """SQLite outbox service with leases and deterministic retry state."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        *,
        max_attempts: int = 5,
        lease_seconds: int = 300,
        retry_base_seconds: int = 5,
    ) -> None:
        if max_attempts < 1:
            raise OutboxError("max_attempts must be at least 1.")
        if lease_seconds < 1:
            raise OutboxError("lease_seconds must be at least 1.")
        if retry_base_seconds < 0:
            raise OutboxError("retry_base_seconds cannot be negative.")
        self.connection = connection
        self.max_attempts = max_attempts
        self.lease_seconds = lease_seconds
        self.retry_base_seconds = retry_base_seconds
        self._ensure_delivery_schema()

    def claim_pending(self, *, worker_id: str, limit: int = 50) -> list[OutboxEvent]:
        """Claim ready events with an expiring lease, ordered deterministically."""

        worker = self._worker_id(worker_id)
        if limit < 1 or limit > 1_000:
            raise OutboxError("Outbox claim limit must be between 1 and 1000.")
        self._require_idle_connection()
        now = utc_now_text()
        lease_until = _utc_after(self.lease_seconds)
        claimed: list[OutboxEvent] = []
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            rows = self.connection.execute(
                """
                SELECT * FROM outbox_events
                WHERE published_at IS NULL
                  AND dead_lettered_at IS NULL
                  AND attempts < ?
                  AND (available_at IS NULL OR available_at <= ?)
                  AND (locked_at IS NULL OR locked_at <= ?)
                ORDER BY COALESCE(available_at, created_at), created_at, id
                LIMIT ?
                """,
                (self.max_attempts, now, now, limit),
            ).fetchall()
            for row in rows:
                cursor = self.connection.execute(
                    """
                    UPDATE outbox_events
                    SET locked_at = ?, locked_by = ?
                    WHERE id = ?
                      AND published_at IS NULL
                      AND dead_lettered_at IS NULL
                      AND (locked_at IS NULL OR locked_at <= ?)
                    """,
                    (lease_until, worker, str(row["id"]), now),
                )
                if cursor.rowcount:
                    values = dict(row)
                    values["locked_at"] = lease_until
                    values["locked_by"] = worker
                    claimed.append(OutboxEvent.from_row(values))
            self.connection.commit()
        except sqlite3.DatabaseError as exc:
            self.connection.rollback()
            raise OutboxError("Unable to claim pending outbox events.") from exc
        return claimed

    def process_once(
        self, *, publisher: OutboxPublisher | Callable[[OutboxEvent], None], worker_id: str, limit: int = 50
    ) -> OutboxProcessResult:
        """Claim and attempt a bounded batch without hiding publisher failures."""

        events = self.claim_pending(worker_id=worker_id, limit=limit)
        published = 0
        failed = 0
        dead_lettered = 0
        for event in events:
            try:
                if callable(publisher):
                    publisher(event)
                else:
                    publisher.publish(event)
                self.mark_published(event_id=event.id, worker_id=worker_id)
                published += 1
            except Exception as exc:  # noqa: BLE001 - publisher failures become retry state.
                failed += 1
                if self.mark_failed(event_id=event.id, worker_id=worker_id, error=str(exc)):
                    dead_lettered += 1
        return OutboxProcessResult(
            claimed=len(events),
            published=published,
            failed=failed,
            dead_lettered=dead_lettered,
        )

    def mark_published(self, *, event_id: str, worker_id: str) -> None:
        """Mark a leased event published only for the worker holding its lease."""

        worker = self._worker_id(worker_id)
        self._require_idle_connection()
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            cursor = self.connection.execute(
                """
                UPDATE outbox_events
                SET published_at = ?, locked_at = NULL, locked_by = NULL, last_error = NULL
                WHERE id = ? AND published_at IS NULL AND locked_by = ?
                """,
                (utc_now_text(), event_id, worker),
            )
            if cursor.rowcount != 1:
                raise OutboxError("Outbox event is not leased by this worker or is already published.")
            self.connection.commit()
        except OutboxError:
            self.connection.rollback()
            raise
        except sqlite3.DatabaseError as exc:
            self.connection.rollback()
            raise OutboxError("Unable to mark outbox event published.") from exc

    def mark_failed(self, *, event_id: str, worker_id: str, error: str) -> bool:
        """Record a bounded failure and return whether the event entered dead-letter state."""

        worker = self._worker_id(worker_id)
        safe_error = (str(error).strip() or "publisher failure")[:1_000]
        self._require_idle_connection()
        now = utc_now_text()
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            row = self.connection.execute(
                "SELECT attempts FROM outbox_events WHERE id = ? AND published_at IS NULL AND locked_by = ?",
                (event_id, worker),
            ).fetchone()
            if row is None:
                raise OutboxError("Outbox event is not leased by this worker.")
            next_attempt = int(row["attempts"]) + 1
            dead_lettered = next_attempt >= self.max_attempts
            available_at = (
                None if dead_lettered else _utc_after(self.retry_base_seconds * (2 ** max(next_attempt - 1, 0)))
            )
            self.connection.execute(
                """
                UPDATE outbox_events
                SET attempts = ?, last_error = ?, available_at = ?,
                    locked_at = NULL, locked_by = ?, dead_lettered_at = ?
                WHERE id = ? AND published_at IS NULL AND locked_by = ?
                """,
                (
                    next_attempt,
                    safe_error,
                    available_at,
                    None,
                    now if dead_lettered else None,
                    event_id,
                    worker,
                ),
            )
            self.connection.commit()
        except OutboxError:
            self.connection.rollback()
            raise
        except sqlite3.DatabaseError as exc:
            self.connection.rollback()
            raise OutboxError("Unable to record outbox delivery failure.") from exc
        return dead_lettered

    def requeue_dead_letter(self, *, event_id: str) -> None:
        """Reset one dead-lettered event for an explicit operator replay."""

        self._require_idle_connection()
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            cursor = self.connection.execute(
                """
                UPDATE outbox_events
                SET attempts = 0, last_error = NULL, available_at = ?,
                    locked_at = NULL, locked_by = NULL, dead_lettered_at = NULL
                WHERE id = ? AND published_at IS NULL AND dead_lettered_at IS NOT NULL
                """,
                (utc_now_text(), event_id),
            )
            if cursor.rowcount != 1:
                raise OutboxError("Outbox event is not dead-lettered or is already published.")
            self.connection.commit()
        except OutboxError:
            self.connection.rollback()
            raise
        except sqlite3.DatabaseError as exc:
            self.connection.rollback()
            raise OutboxError("Unable to requeue dead-lettered outbox event.") from exc

    def list_events(self, *, status: str = "pending", limit: int = 100) -> list[OutboxEvent]:
        """List events by delivery status in stable order."""

        if limit < 1 or limit > 10_000:
            raise OutboxError("Outbox list limit must be between 1 and 10000.")
        query = OUTBOX_LIST_QUERIES.get(status)
        if query is None:
            raise OutboxError("Outbox status must be pending, published, dead_letter, or all.")
        try:
            rows = self.connection.execute(query, (limit,)).fetchall()
        except sqlite3.DatabaseError as exc:
            raise OutboxError("Unable to list outbox events.") from exc
        return [OutboxEvent.from_row(row) for row in rows]

    def _ensure_delivery_schema(self) -> None:
        try:
            columns = {
                str(row["name"]) for row in self.connection.execute("PRAGMA table_info(outbox_events)").fetchall()
            }
        except sqlite3.DatabaseError as exc:
            raise OutboxError("Unable to inspect outbox schema. Run 'reconforge db migrate' first.") from exc
        required = {"id", "available_at", "locked_at", "locked_by", "dead_lettered_at"}
        if not required <= columns:
            raise OutboxError("Outbox delivery schema is not initialized. Run 'reconforge db migrate' first.")

    @staticmethod
    def _worker_id(value: str) -> str:
        worker = str(value or "").strip()
        if not worker or len(worker) > 160:
            raise OutboxError("worker_id must be a non-empty value of at most 160 characters.")
        return worker

    def _require_idle_connection(self) -> None:
        if self.connection.in_transaction:
            raise OutboxError("Outbox delivery operations require an idle database connection.")
