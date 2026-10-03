"""SQLite-specific transactional outbox repository."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any

from reconforge.application.outbox import OutboxError, OutboxEvent
from reconforge.domain.models import utc_now_text


def _utc_after(seconds: int) -> str:
    return (datetime.now(UTC) + timedelta(seconds=seconds)).replace(microsecond=0).isoformat().replace("+00:00", "Z")


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

OUTBOX_RECOVERY_SELECT_SQL = """
SELECT id, attempts FROM outbox_events INDEXED BY idx_outbox_expired_lease
WHERE published_at IS NULL AND dead_lettered_at IS NULL
  AND locked_at IS NOT NULL AND locked_at <= ?
ORDER BY locked_at, created_at, id LIMIT ?
"""


class SQLiteOutboxRepository:
    """SQLite implementation of the transactional outbox persistence operations."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        self._ensure_delivery_schema()

    def _ensure_delivery_schema(self) -> None:
        try:
            columns = {
                str(row["name"]) for row in self.connection.execute("PRAGMA table_info(outbox_events)").fetchall()
            }
        except sqlite3.DatabaseError as exc:
            raise OutboxError("Unable to inspect outbox schema. Run 'reconforge db migrate' first.") from exc
        required = {
            "id", "available_at", "locked_at", "locked_by", "dead_lettered_at", "lease_generation",
            "lease_generation_floor",
        }
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

    @staticmethod
    def _event_from_row(row: sqlite3.Row | dict[str, Any]) -> OutboxEvent:
        return OutboxEvent(
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
            lease_generation=int(row["lease_generation"]),
            lease_generation_floor=int(row["lease_generation_floor"]),
        )

    @staticmethod
    def _bounded_integer(value: int, field: str, minimum: int, maximum: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
            raise OutboxError(f"{field} must be between {minimum} and {maximum}.")
        return value

    @classmethod
    def _generation(cls, value: int | None) -> int:
        # Compatibility is restricted to a fresh event's first active claim.
        return cls._bounded_integer(1 if value is None else value, "lease_generation", 1, 2**63 - 1)

    def _recover_expired(self, *, now: str, limit: int, max_attempts: int) -> int:
        rows = self.connection.execute(
            OUTBOX_RECOVERY_SELECT_SQL, (now, limit)
        ).fetchall()
        for row in rows:
            attempts = int(row["attempts"]) + 1
            cursor = self.connection.execute(
                """UPDATE outbox_events SET attempts=?, last_error='LEASE_EXPIRED',
                available_at=?, locked_at=NULL, locked_by=NULL, dead_lettered_at=?
                WHERE id=? AND published_at IS NULL AND dead_lettered_at IS NULL
                  AND locked_at IS NOT NULL AND locked_at <= ?""",
                (attempts, now, now if attempts >= max_attempts else None, row["id"], now),
            )
            if cursor.rowcount != 1:
                raise OutboxError("Outbox event lease changed during crash recovery.")
        return len(rows)

    def recover_expired(self, *, limit: int = 50, max_attempts: int = 5) -> int:
        """Recover at most limit crashed claims, charging each expired attempt once."""
        self._bounded_integer(limit, "limit", 1, 1000)
        self._bounded_integer(max_attempts, "max_attempts", 1, 100)
        self._require_idle_connection()
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            count = self._recover_expired(now=utc_now_text(), limit=limit, max_attempts=max_attempts)
            self.connection.commit()
            return count
        except OutboxError:
            self.connection.rollback()
            raise
        except sqlite3.DatabaseError as exc:
            self.connection.rollback()
            raise OutboxError("Unable to recover expired outbox claims.") from exc

    def claim_pending(
        self, *, worker_id: str, limit: int = 50, max_attempts: int = 5, lease_seconds: int = 300
    ) -> list[OutboxEvent]:
        worker = self._worker_id(worker_id)
        self._bounded_integer(limit, "Outbox claim limit", 1, 1000)
        self._bounded_integer(max_attempts, "max_attempts", 1, 100)
        self._bounded_integer(lease_seconds, "lease_seconds", 1, 86400)
        self._require_idle_connection()
        now = utc_now_text()
        lease_until = _utc_after(lease_seconds)
        claimed: list[OutboxEvent] = []
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            self._recover_expired(now=now, limit=limit, max_attempts=max_attempts)
            rows = self.connection.execute(
                """
                SELECT * FROM outbox_events
                WHERE published_at IS NULL
                  AND dead_lettered_at IS NULL
                  AND attempts < ?
                  AND (available_at IS NULL OR available_at <= ?)
                  AND locked_at IS NULL
                ORDER BY COALESCE(available_at, created_at), created_at, id
                LIMIT ?
                """,
                (max_attempts, now, limit),
            ).fetchall()
            for row in rows:
                cursor = self.connection.execute(
                    """
                    UPDATE outbox_events
                    SET locked_at = ?, locked_by = ?, lease_generation = lease_generation + 1
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
                    values["lease_generation"] = int(row["lease_generation"]) + 1
                    claimed.append(self._event_from_row(values))
            self.connection.commit()
        except OutboxError:
            self.connection.rollback()
            raise
        except sqlite3.DatabaseError as exc:
            self.connection.rollback()
            raise OutboxError("Unable to claim pending outbox events.") from exc
        return claimed

    def assert_claim(self, *, event_id: str, worker_id: str, lease_generation: int) -> None:
        worker = self._worker_id(worker_id)
        generation = self._generation(lease_generation)
        row = self.connection.execute(
            """SELECT 1 FROM outbox_events WHERE id=? AND locked_by=? AND lease_generation=?
            AND locked_at > ? AND published_at IS NULL AND dead_lettered_at IS NULL""",
            (event_id, worker, generation, utc_now_text()),
        ).fetchone()
        if row is None:
            raise OutboxError("Outbox event claim is expired or fenced by a newer lease.")

    def mark_published(self, *, event_id: str, worker_id: str, lease_generation: int | None = None) -> None:
        worker = self._worker_id(worker_id)
        generation = self._generation(lease_generation)
        self._require_idle_connection()
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            cursor = self.connection.execute(
                """
                UPDATE outbox_events
                SET published_at = ?, locked_at = NULL, locked_by = NULL, last_error = NULL
                WHERE id = ? AND published_at IS NULL AND locked_by = ?
                  AND dead_lettered_at IS NULL AND lease_generation = ? AND locked_at > ?
                """,
                (utc_now_text(), event_id, worker, generation, utc_now_text()),
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

    def mark_failed(
        self, *, event_id: str, worker_id: str, error: str, max_attempts: int = 5,
        retry_base_seconds: int = 5, lease_generation: int | None = None
    ) -> bool:
        worker = self._worker_id(worker_id)
        generation = self._generation(lease_generation)
        self._bounded_integer(max_attempts, "max_attempts", 1, 100)
        self._bounded_integer(retry_base_seconds, "retry_base_seconds", 0, 86400)
        safe_error = (str(error).strip() or "publisher failure")[:1_000]
        self._require_idle_connection()
        now = utc_now_text()
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            row = self.connection.execute(
                """SELECT attempts FROM outbox_events WHERE id = ? AND published_at IS NULL AND locked_by = ?
                AND dead_lettered_at IS NULL AND lease_generation = ? AND locked_at > ?""",
                (event_id, worker, generation, now),
            ).fetchone()
            if row is None:
                raise OutboxError("Outbox event is not leased by this worker.")
            next_attempt = int(row["attempts"]) + 1
            dead_lettered = next_attempt >= max_attempts
            available_at = None if dead_lettered else _utc_after(
                min(86400, retry_base_seconds * (2 ** max(next_attempt - 1, 0)))
            )
            cursor = self.connection.execute(
                """
                UPDATE outbox_events
                SET attempts = ?, last_error = ?, available_at = ?,
                    locked_at = NULL, locked_by = ?, dead_lettered_at = ?
                WHERE id = ? AND published_at IS NULL AND locked_by = ?
                  AND dead_lettered_at IS NULL AND lease_generation = ? AND locked_at > ?
                """,
                (
                    next_attempt,
                    safe_error,
                    available_at,
                    None,
                    now if dead_lettered else None,
                    event_id,
                    worker,
                    generation,
                    now,
                ),
            )
            if cursor.rowcount != 1:
                raise OutboxError("Outbox event lease changed before failure state was saved.")
            self.connection.commit()
        except OutboxError:
            self.connection.rollback()
            raise
        except sqlite3.DatabaseError as exc:
            self.connection.rollback()
            raise OutboxError("Unable to record outbox delivery failure.") from exc
        return dead_lettered

    def requeue_dead_letter(self, *, event_id: str) -> None:
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
        if limit < 1 or limit > 10_000:
            raise OutboxError("Outbox list limit must be between 1 and 10000.")
        query = OUTBOX_LIST_QUERIES.get(status)
        if query is None:
            raise OutboxError("Outbox status must be pending, published, dead_letter, or all.")
        try:
            rows = self.connection.execute(query, (limit,)).fetchall()
        except sqlite3.DatabaseError as exc:
            raise OutboxError("Unable to list outbox events.") from exc
        return [self._event_from_row(row) for row in rows]
