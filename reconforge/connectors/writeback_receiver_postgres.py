"""PostgreSQL reference backend for receiver-side write-back conformance.

The adapter is additive and loads psycopg only when a PostgreSQL operation is
requested, preserving the local Community import path.  It stores the same
digest-only receipt/effect contract as the SQLite reference receiver.
"""

from __future__ import annotations

import hashlib
import importlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import ModuleType
from typing import Any

from reconforge.connectors.writeback_receiver import (
    WritebackReceiverCounts,
    WritebackReceiverDisposition,
    WritebackReceiverError,
    WritebackReceiverRequest,
    WritebackReceiverResult,
    build_writeback_receiver_response,
    replay_writeback_receiver_result,
)

SCHEMA_NAME = "reconforge_receiver_conformance"
RECEIPTS_TABLE = f"{SCHEMA_NAME}.writeback_receiver_receipts"
EFFECTS_TABLE = f"{SCHEMA_NAME}.writeback_receiver_effects"

_SCHEMA = f"""
CREATE SCHEMA IF NOT EXISTS {SCHEMA_NAME};
CREATE TABLE IF NOT EXISTS {RECEIPTS_TABLE} (
    receiver_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    operation TEXT NOT NULL,
    payload_digest TEXT NOT NULL,
    request_digest TEXT NOT NULL,
    provider_reference TEXT NOT NULL,
    response_digest TEXT NOT NULL,
    committed_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (receiver_id, idempotency_key),
    CHECK (payload_digest ~ '^[0-9a-f]{{64}}$'),
    CHECK (request_digest ~ '^[0-9a-f]{{64}}$'),
    CHECK (response_digest ~ '^[0-9a-f]{{64}}$')
);
CREATE TABLE IF NOT EXISTS {EFFECTS_TABLE} (
    receiver_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    request_digest TEXT NOT NULL,
    provider_reference TEXT NOT NULL,
    PRIMARY KEY (receiver_id, idempotency_key),
    FOREIGN KEY (receiver_id, idempotency_key)
        REFERENCES {RECEIPTS_TABLE} (receiver_id, idempotency_key)
);
CREATE OR REPLACE FUNCTION {SCHEMA_NAME}.reject_receipt_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
BEGIN
    RAISE EXCEPTION 'writeback_receiver_receipt_immutable' USING ERRCODE = '55000';
END;
$function$;
CREATE OR REPLACE FUNCTION {SCHEMA_NAME}.reject_effect_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
BEGIN
    RAISE EXCEPTION 'writeback_receiver_effect_immutable' USING ERRCODE = '55000';
END;
$function$;
DROP TRIGGER IF EXISTS writeback_receiver_receipts_no_mutation ON {RECEIPTS_TABLE};
CREATE TRIGGER writeback_receiver_receipts_no_mutation
BEFORE UPDATE OR DELETE ON {RECEIPTS_TABLE}
FOR EACH ROW EXECUTE FUNCTION {SCHEMA_NAME}.reject_receipt_mutation();
DROP TRIGGER IF EXISTS writeback_receiver_effects_no_mutation ON {EFFECTS_TABLE};
CREATE TRIGGER writeback_receiver_effects_no_mutation
BEFORE UPDATE OR DELETE ON {EFFECTS_TABLE}
FOR EACH ROW EXECUTE FUNCTION {SCHEMA_NAME}.reject_effect_mutation();
"""


def _load_psycopg() -> ModuleType:
    try:
        return importlib.import_module("psycopg")
    except ImportError as exc:
        raise WritebackReceiverError("writeback_receiver_postgres_dependency_missing") from exc


def _receiver_key_digest(request: WritebackReceiverRequest) -> str:
    encoded = json.dumps(
        {"idempotency_key": request.idempotency_key, "receiver_id": request.receiver_id},
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class PostgresWritebackReceiverStore:
    """Server-backed reference receiver with transaction-scoped key locking."""

    dsn: str = field(repr=False)
    connect_timeout_seconds: int = 10
    statement_timeout_ms: int = 30_000

    def __post_init__(self) -> None:
        if not isinstance(self.dsn, str) or not self.dsn:
            raise WritebackReceiverError("writeback_receiver_postgres_dsn_invalid")
        if not 1 <= self.connect_timeout_seconds <= 60:
            raise WritebackReceiverError("writeback_receiver_postgres_connect_timeout_invalid")
        if not 1 <= self.statement_timeout_ms <= 120_000:
            raise WritebackReceiverError("writeback_receiver_postgres_statement_timeout_invalid")

    def initialize(self) -> None:
        psycopg = _load_psycopg()
        try:
            with self._connect() as connection:
                connection.execute(_SCHEMA, prepare=False)
        except psycopg.Error as exc:
            raise WritebackReceiverError("writeback_receiver_postgres_initialization_failed") from exc

    def receive(self, request: WritebackReceiverRequest) -> WritebackReceiverResult:
        psycopg = _load_psycopg()
        try:
            with self._connect() as connection:
                connection.execute(
                    "SELECT set_config('statement_timeout', %s, true)",
                    (str(self.statement_timeout_ms),),
                )
                connection.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    (_receiver_key_digest(request),),
                )
                row = connection.execute(
                    f"""
                    SELECT operation, payload_digest, request_digest,
                           provider_reference, response_digest
                    FROM {RECEIPTS_TABLE}
                    WHERE receiver_id = %s AND idempotency_key = %s
                    """,  # nosec B608 - table is an immutable module constant
                    (request.receiver_id, request.idempotency_key),
                ).fetchone()
                if row is not None:
                    return replay_writeback_receiver_result(
                        request,
                        operation=str(row[0]),
                        payload_digest=str(row[1]),
                        request_digest=str(row[2]),
                        provider_reference=str(row[3]),
                        response_digest=str(row[4]),
                    )

                provider_reference = "rf-receiver-" + request.request_digest[:24]
                response = build_writeback_receiver_response(
                    request.idempotency_key, provider_reference
                )
                connection.execute(
                    f"""
                    INSERT INTO {RECEIPTS_TABLE} (
                        receiver_id, idempotency_key, operation, payload_digest,
                        request_digest, provider_reference, response_digest, committed_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,  # nosec B608 - table is an immutable module constant
                    (
                        request.receiver_id,
                        request.idempotency_key,
                        request.operation,
                        request.payload_digest,
                        request.request_digest,
                        provider_reference,
                        response.response_digest,
                        datetime.now(UTC),
                    ),
                )
                connection.execute(
                    f"""
                    INSERT INTO {EFFECTS_TABLE} (
                        receiver_id, idempotency_key, request_digest, provider_reference
                    ) VALUES (%s, %s, %s, %s)
                    """,  # nosec B608 - table is an immutable module constant
                    (
                        request.receiver_id,
                        request.idempotency_key,
                        request.request_digest,
                        provider_reference,
                    ),
                )
                return WritebackReceiverResult(
                    disposition=WritebackReceiverDisposition.APPLIED,
                    request_digest=request.request_digest,
                    response=response,
                )
        except WritebackReceiverError:
            raise
        except psycopg.Error as exc:
            raise WritebackReceiverError("writeback_receiver_postgres_store_failed") from exc

    def counts(self) -> WritebackReceiverCounts:
        psycopg = _load_psycopg()
        try:
            with self._connect() as connection:
                receipts_row = connection.execute(
                    f"SELECT COUNT(*) FROM {RECEIPTS_TABLE}"  # nosec B608 - fixed table
                ).fetchone()
                effects_row = connection.execute(
                    f"SELECT COUNT(*) FROM {EFFECTS_TABLE}"  # nosec B608 - fixed table
                ).fetchone()
        except psycopg.Error as exc:
            raise WritebackReceiverError("writeback_receiver_postgres_store_failed") from exc
        if receipts_row is None or effects_row is None:
            raise WritebackReceiverError("writeback_receiver_postgres_history_invalid")
        return WritebackReceiverCounts(receipts=int(receipts_row[0]), effects=int(effects_row[0]))

    def canonical_history_digest(self) -> str:
        psycopg = _load_psycopg()
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    f"""
                    SELECT receiver_id, idempotency_key, operation, payload_digest,
                           request_digest, provider_reference, response_digest
                    FROM {RECEIPTS_TABLE}
                    ORDER BY receiver_id, idempotency_key
                    """  # nosec B608 - table is an immutable module constant
                ).fetchall()
        except psycopg.Error as exc:
            raise WritebackReceiverError("writeback_receiver_postgres_store_failed") from exc
        encoded = json.dumps(rows, ensure_ascii=True, separators=(",", ":")).encode("ascii")
        return hashlib.sha256(encoded).hexdigest()

    def _connect(self) -> Any:
        psycopg = _load_psycopg()
        return psycopg.connect(
            self.dsn,
            connect_timeout=self.connect_timeout_seconds,
            application_name="reconforge-receiver-conformance",
        )
