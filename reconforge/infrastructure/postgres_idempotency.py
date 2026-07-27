"""PostgreSQL implementation of the generic idempotency contract."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any

from reconforge.application.idempotency import (
    IdempotencyBeginResult,
    IdempotencyConflictError,
    IdempotencyInProgressError,
    IdempotencyOwnershipError,
    IdempotencyReservation,
    digest_bytes,
)
from reconforge.infrastructure.postgres import ConnectionFactory, validate_tenant_id


def _decode(row: Any) -> IdempotencyReservation:
    encoded = str(row[7])
    if len(encoded) > 22 * 1024 * 1024:
        raise RuntimeError("Stored idempotency response exceeds its safety limit.")
    try:
        response = base64.b64decode(encoded, validate=True)
    except ValueError as exc:
        raise RuntimeError("Stored idempotency response encoding is invalid.") from exc
    return IdempotencyReservation(
        int(row[0]), str(row[1]), str(row[2]), str(row[3]), str(row[4]), str(row[5]),
        str(row[6]), response, str(row[8]), str(row[9]), str(row[10]), str(row[11]), str(row[12]),
    )


@dataclass(frozen=True)
class PostgresIdempotencyRepository:
    connection_factory: ConnectionFactory
    tenant_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "tenant_id", validate_tenant_id(self.tenant_id))

    @staticmethod
    def _select(connection: Any, tenant_id: str, scope: str, key: str) -> Any:
        return connection.execute(
            """SELECT schema_version,tenant_id,scope,idempotency_key,request_digest,owner_token_digest,
               status,response_body,response_digest,content_type,created_at,expires_at,completed_at
               FROM reconforge.idempotency_records
               WHERE tenant_id=%s AND scope=%s AND idempotency_key=%s FOR UPDATE""",
            (tenant_id, scope, key),
        ).fetchone()

    def begin(self, reservation: IdempotencyReservation, *, observed_at: str) -> IdempotencyBeginResult:
        if reservation.tenant_id != self.tenant_id:
            raise IdempotencyConflictError("Idempotency tenant scope does not match the repository.")
        connection = self.connection_factory.connect()
        try:
            with connection.transaction():
                connection.execute("SELECT set_config('app.tenant_id', %s, true)", (self.tenant_id,))
                row = self._select(connection, self.tenant_id, reservation.scope, reservation.key)
                if row is not None and str(row[11]) <= observed_at:
                    connection.execute(
                        "DELETE FROM reconforge.idempotency_records WHERE tenant_id=%s AND scope=%s AND idempotency_key=%s",
                        (self.tenant_id, reservation.scope, reservation.key),
                    )
                    row = None
                if row is None:
                    inserted = connection.execute(
                        """INSERT INTO reconforge.idempotency_records
                        (schema_version,tenant_id,scope,idempotency_key,request_digest,owner_token_digest,status,
                         response_body,response_digest,content_type,created_at,expires_at,completed_at)
                        VALUES (%s,%s,%s,%s,%s,%s,'pending',%s,'','',%s,%s,'')
                        ON CONFLICT (tenant_id,scope,idempotency_key) DO NOTHING RETURNING 1""",
                        (reservation.schema_version, self.tenant_id, reservation.scope, reservation.key,
                         reservation.request_digest, digest_bytes(reservation.owner_token.encode()), "", reservation.created_at,
                         reservation.expires_at),
                    ).fetchone()
                    if inserted is not None:
                        return IdempotencyBeginResult(reservation, True, False)
                    row = self._select(connection, self.tenant_id, reservation.scope, reservation.key)
                if row is None:
                    raise IdempotencyConflictError("Idempotency reservation could not be resolved.")
                existing = _decode(row)
                if existing.request_digest != reservation.request_digest:
                    raise IdempotencyConflictError("Idempotency key is bound to a different request.")
                if existing.status == "pending":
                    raise IdempotencyInProgressError("Equivalent idempotent request is still in progress.")
                return IdempotencyBeginResult(existing, False, True)
        finally:
            connection.close()

    def complete(
        self, reservation: IdempotencyReservation, *, response: bytes,
        response_digest: str, content_type: str, completed_at: str,
    ) -> IdempotencyReservation:
        connection = self.connection_factory.connect()
        try:
            with connection.transaction():
                connection.execute("SELECT set_config('app.tenant_id', %s, true)", (self.tenant_id,))
                row = connection.execute(
                    """UPDATE reconforge.idempotency_records SET status='completed',response_body=%s,
                       response_digest=%s,content_type=%s,completed_at=%s
                       WHERE tenant_id=%s AND scope=%s AND idempotency_key=%s AND request_digest=%s
                       AND owner_token_digest=%s AND status='pending' AND expires_at>%s
                       RETURNING schema_version,tenant_id,scope,idempotency_key,request_digest,owner_token_digest,
                       status,response_body,response_digest,content_type,created_at,expires_at,completed_at""",
                    (base64.b64encode(response).decode("ascii"), response_digest, content_type, completed_at, self.tenant_id, reservation.scope,
                     reservation.key, reservation.request_digest, digest_bytes(reservation.owner_token.encode()),
                     completed_at),
                ).fetchone()
                if row is None:
                    raise IdempotencyOwnershipError("Idempotency reservation ownership is stale or invalid.")
                return _decode(row)
        finally:
            connection.close()


POSTGRES_IDEMPOTENCY_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS reconforge.idempotency_records (
  schema_version INTEGER NOT NULL CHECK (schema_version=1), tenant_id TEXT NOT NULL,
  scope TEXT NOT NULL CHECK (length(scope) BETWEEN 1 AND 160),
  idempotency_key TEXT NOT NULL CHECK (length(idempotency_key) BETWEEN 1 AND 200),
  request_digest TEXT NOT NULL CHECK (length(request_digest)=64),
  owner_token_digest TEXT NOT NULL CHECK (length(owner_token_digest)=64),
  status TEXT NOT NULL CHECK (status IN ('pending','completed')),
  response_body TEXT NOT NULL DEFAULT '', response_digest TEXT NOT NULL DEFAULT '',
  content_type TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, expires_at TEXT NOT NULL,
  completed_at TEXT NOT NULL DEFAULT '', PRIMARY KEY (tenant_id,scope,idempotency_key),
  CHECK (expires_at > created_at),
  CHECK ((status='pending' AND length(response_body)=0 AND response_digest='' AND completed_at='')
      OR (status='completed' AND length(response_digest)=64 AND completed_at<>''))
);
CREATE INDEX IF NOT EXISTS idx_idempotency_expiry ON reconforge.idempotency_records(expires_at,tenant_id);
ALTER TABLE reconforge.idempotency_records ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.idempotency_records FORCE ROW LEVEL SECURITY;
DO $reconforge$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE schemaname='reconforge' AND tablename='idempotency_records' AND policyname='tenant_scope') THEN
  CREATE POLICY tenant_scope ON reconforge.idempotency_records
   USING (tenant_id=current_setting('app.tenant_id',true))
   WITH CHECK (tenant_id=current_setting('app.tenant_id',true));
 END IF;
END $reconforge$;
"""


def install_postgres_idempotency_schema(connection: Any) -> None:
    connection.execute(POSTGRES_IDEMPOTENCY_SCHEMA_SQL)
