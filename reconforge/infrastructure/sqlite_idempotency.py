"""SQLite implementation of the generic idempotency contract."""

from __future__ import annotations

import base64
import sqlite3
from dataclasses import dataclass

from reconforge.application.idempotency import (
    IdempotencyBeginResult,
    IdempotencyConflictError,
    IdempotencyInProgressError,
    IdempotencyOwnershipError,
    IdempotencyReservation,
    digest_bytes,
)


def _decode(row: sqlite3.Row) -> IdempotencyReservation:
    encoded = str(row["response_body"])
    if len(encoded) > 22 * 1024 * 1024:
        raise RuntimeError("Stored idempotency response exceeds its safety limit.")
    try:
        response = base64.b64decode(encoded, validate=True)
    except ValueError as exc:
        raise RuntimeError("Stored idempotency response encoding is invalid.") from exc
    return IdempotencyReservation(
        schema_version=int(row["schema_version"]),
        tenant_id=str(row["tenant_id"]),
        scope=str(row["scope"]),
        key=str(row["idempotency_key"]),
        request_digest=str(row["request_digest"]),
        owner_token=str(row["owner_token_digest"]),
        status=str(row["status"]),
        response=response,
        response_digest=str(row["response_digest"]),
        content_type=str(row["content_type"]),
        created_at=str(row["created_at"]),
        expires_at=str(row["expires_at"]),
        completed_at=str(row["completed_at"]),
    )


@dataclass
class SQLiteIdempotencyRepository:
    connection: sqlite3.Connection

    def _begin_transaction(self) -> None:
        if self.connection.in_transaction:
            raise RuntimeError("Idempotency repository requires an unambiguous transaction boundary.")
        self.connection.execute("BEGIN IMMEDIATE")

    def begin(self, reservation: IdempotencyReservation, *, observed_at: str) -> IdempotencyBeginResult:
        self._begin_transaction()
        try:
            row = self.connection.execute(
                "SELECT * FROM idempotency_records WHERE tenant_id=? AND scope=? AND idempotency_key=?",
                (reservation.tenant_id, reservation.scope, reservation.key),
            ).fetchone()
            if row is not None and str(row["expires_at"]) <= observed_at:
                self.connection.execute(
                    "DELETE FROM idempotency_records WHERE tenant_id=? AND scope=? AND idempotency_key=?",
                    (reservation.tenant_id, reservation.scope, reservation.key),
                )
                row = None
            if row is None:
                self.connection.execute(
                    """INSERT INTO idempotency_records
                    (schema_version,tenant_id,scope,idempotency_key,request_digest,owner_token_digest,status,
                     response_body,response_digest,content_type,created_at,expires_at,completed_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        reservation.schema_version,
                        reservation.tenant_id,
                        reservation.scope,
                        reservation.key,
                        reservation.request_digest,
                        digest_bytes(reservation.owner_token.encode()),
                        reservation.status,
                        "",
                        "",
                        "",
                        reservation.created_at,
                        reservation.expires_at,
                        "",
                    ),
                )
                self.connection.commit()
                return IdempotencyBeginResult(reservation, True, False)
            existing = _decode(row)
            if existing.request_digest != reservation.request_digest:
                raise IdempotencyConflictError("Idempotency key is bound to a different request.")
            if existing.status == "pending":
                raise IdempotencyInProgressError("Equivalent idempotent request is still in progress.")
            self.connection.commit()
            return IdempotencyBeginResult(existing, False, True)
        except Exception:
            self.connection.rollback()
            raise

    def complete(
        self,
        reservation: IdempotencyReservation,
        *,
        response: bytes,
        response_digest: str,
        content_type: str,
        completed_at: str,
    ) -> IdempotencyReservation:
        self._begin_transaction()
        try:
            cursor = self.connection.execute(
                """UPDATE idempotency_records SET status='completed',response_body=?,response_digest=?,
                   content_type=?,completed_at=? WHERE tenant_id=? AND scope=? AND idempotency_key=?
                   AND request_digest=? AND owner_token_digest=? AND status='pending' AND expires_at>?""",
                (
                    base64.b64encode(response).decode("ascii"),
                    response_digest,
                    content_type,
                    completed_at,
                    reservation.tenant_id,
                    reservation.scope,
                    reservation.key,
                    reservation.request_digest,
                    digest_bytes(reservation.owner_token.encode()),
                    completed_at,
                ),
            )
            if cursor.rowcount != 1:
                raise IdempotencyOwnershipError("Idempotency reservation ownership is stale or invalid.")
            row = self.connection.execute(
                "SELECT * FROM idempotency_records WHERE tenant_id=? AND scope=? AND idempotency_key=?",
                (reservation.tenant_id, reservation.scope, reservation.key),
            ).fetchone()
            if row is None:
                raise IdempotencyOwnershipError("Completed idempotency reservation could not be reloaded.")
            completed = _decode(row)
            self.connection.commit()
            return completed
        except Exception:
            self.connection.rollback()
            raise
