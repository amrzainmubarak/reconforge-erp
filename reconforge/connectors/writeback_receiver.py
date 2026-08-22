"""Durable receiver-side idempotency reference for write-back conformance.

This module models the *receiving* side of a mutation.  It is deliberately a
synthetic, local reference adapter: it proves the contract that a real provider
must implement, but it does not claim interoperability with any vendor or
provide a production HTTP service.

The SQLite implementation stores request and response digests, never payload
bytes or credentials.  The idempotency receipt and the synthetic business
effect commit in one ``BEGIN IMMEDIATE`` transaction so concurrent processes
observe one business effect for one receiver/key identity.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from reconforge.connectors.writeback_network import WritebackProviderResponse

_ID_PATTERN = r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$"
_OPERATION_PATTERN = r"^[a-z][a-z0-9._-]{0,127}$"
_IDEMPOTENCY_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$"
_PROVIDER_REFERENCE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")


class WritebackReceiverError(RuntimeError):
    """Safe receiver conformance failure without payload disclosure."""


class WritebackReceiverRequest(BaseModel):
    """Digest-only mutation identity presented to a receiver."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["writeback-receiver-request-v1"]
    receiver_id: str = Field(pattern=_ID_PATTERN)
    operation: str = Field(pattern=_OPERATION_PATTERN)
    idempotency_key: str = Field(pattern=_IDEMPOTENCY_PATTERN)
    payload_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @property
    def request_digest(self) -> str:
        encoded = json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
        return hashlib.sha256(encoded).hexdigest()


class WritebackReceiverDisposition(StrEnum):
    APPLIED = "applied"
    REPLAYED = "replayed"


@dataclass(frozen=True)
class WritebackReceiverResult:
    """Stable provider response plus whether this call created the effect."""

    disposition: WritebackReceiverDisposition
    request_digest: str
    response: WritebackProviderResponse

    @property
    def response_body(self) -> bytes:
        return json.dumps(
            self.response.model_dump(mode="json"),
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")


@dataclass(frozen=True)
class WritebackReceiverCounts:
    receipts: int
    effects: int


_SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS writeback_receiver_receipts (
    receiver_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    operation TEXT NOT NULL,
    payload_digest TEXT NOT NULL,
    request_digest TEXT NOT NULL,
    provider_reference TEXT NOT NULL,
    response_digest TEXT NOT NULL,
    committed_at TEXT NOT NULL,
    PRIMARY KEY (receiver_id, idempotency_key),
    CHECK (length(payload_digest) = 64),
    CHECK (length(request_digest) = 64),
    CHECK (length(response_digest) = 64)
);
CREATE TABLE IF NOT EXISTS writeback_receiver_effects (
    receiver_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    request_digest TEXT NOT NULL,
    provider_reference TEXT NOT NULL,
    PRIMARY KEY (receiver_id, idempotency_key),
    FOREIGN KEY (receiver_id, idempotency_key)
        REFERENCES writeback_receiver_receipts (receiver_id, idempotency_key)
);
CREATE TRIGGER IF NOT EXISTS writeback_receiver_receipts_no_update
BEFORE UPDATE ON writeback_receiver_receipts
BEGIN
    SELECT RAISE(ABORT, 'writeback_receiver_receipt_immutable');
END;
CREATE TRIGGER IF NOT EXISTS writeback_receiver_receipts_no_delete
BEFORE DELETE ON writeback_receiver_receipts
BEGIN
    SELECT RAISE(ABORT, 'writeback_receiver_receipt_immutable');
END;
CREATE TRIGGER IF NOT EXISTS writeback_receiver_effects_no_update
BEFORE UPDATE ON writeback_receiver_effects
BEGIN
    SELECT RAISE(ABORT, 'writeback_receiver_effect_immutable');
END;
CREATE TRIGGER IF NOT EXISTS writeback_receiver_effects_no_delete
BEFORE DELETE ON writeback_receiver_effects
BEGIN
    SELECT RAISE(ABORT, 'writeback_receiver_effect_immutable');
END;
"""


@dataclass(frozen=True)
class SQLiteWritebackReceiverStore:
    """SQLite reference receiver with atomic effect-and-receipt persistence."""

    path: Path
    busy_timeout_ms: int = 30_000

    def initialize(self) -> None:
        if self.busy_timeout_ms < 1 or self.busy_timeout_ms > 120_000:
            raise WritebackReceiverError("writeback_receiver_busy_timeout_invalid")
        resolved = self.path.resolve(strict=False)
        if resolved.exists() and not resolved.is_file():
            raise WritebackReceiverError("writeback_receiver_store_path_invalid")
        resolved.parent.mkdir(parents=True, exist_ok=True)
        connection: sqlite3.Connection | None = None
        try:
            connection = self._connect()
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = FULL")
            connection.executescript(_SCHEMA)
        except sqlite3.Error as exc:
            raise WritebackReceiverError("writeback_receiver_store_initialization_failed") from exc
        finally:
            if connection is not None:
                connection.close()

    def receive(self, request: WritebackReceiverRequest) -> WritebackReceiverResult:
        """Apply once or replay the exact prior response for this receiver/key."""

        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT operation, payload_digest, request_digest,
                       provider_reference, response_digest
                FROM writeback_receiver_receipts
                WHERE receiver_id = ? AND idempotency_key = ?
                """,
                (request.receiver_id, request.idempotency_key),
            ).fetchone()
            if row is not None:
                result = self._replay(request, row)
                connection.commit()
                return result

            provider_reference = "rf-receiver-" + request.request_digest[:24]
            response = _provider_response(request.idempotency_key, provider_reference)
            committed_at = datetime.now(UTC).replace(microsecond=0).isoformat()
            connection.execute(
                """
                INSERT INTO writeback_receiver_receipts (
                    receiver_id, idempotency_key, operation, payload_digest,
                    request_digest, provider_reference, response_digest, committed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    request.receiver_id,
                    request.idempotency_key,
                    request.operation,
                    request.payload_digest,
                    request.request_digest,
                    provider_reference,
                    response.response_digest,
                    committed_at,
                ),
            )
            connection.execute(
                """
                INSERT INTO writeback_receiver_effects (
                    receiver_id, idempotency_key, request_digest, provider_reference
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    request.receiver_id,
                    request.idempotency_key,
                    request.request_digest,
                    provider_reference,
                ),
            )
            connection.commit()
            return WritebackReceiverResult(
                disposition=WritebackReceiverDisposition.APPLIED,
                request_digest=request.request_digest,
                response=response,
            )
        except WritebackReceiverError:
            connection.rollback()
            raise
        except sqlite3.Error as exc:
            connection.rollback()
            raise WritebackReceiverError("writeback_receiver_store_failed") from exc
        finally:
            connection.close()

    def counts(self) -> WritebackReceiverCounts:
        connection: sqlite3.Connection | None = None
        try:
            connection = self._connect()
            receipts = int(connection.execute("SELECT COUNT(*) FROM writeback_receiver_receipts").fetchone()[0])
            effects = int(connection.execute("SELECT COUNT(*) FROM writeback_receiver_effects").fetchone()[0])
        except sqlite3.Error as exc:
            raise WritebackReceiverError("writeback_receiver_store_failed") from exc
        finally:
            if connection is not None:
                connection.close()
        return WritebackReceiverCounts(receipts=receipts, effects=effects)

    def canonical_history_digest(self) -> str:
        """Digest immutable identities while excluding non-deterministic time."""

        connection: sqlite3.Connection | None = None
        try:
            connection = self._connect()
            rows = connection.execute(
                """
                SELECT receiver_id, idempotency_key, operation, payload_digest,
                       request_digest, provider_reference, response_digest
                FROM writeback_receiver_receipts
                ORDER BY receiver_id, idempotency_key
                """
            ).fetchall()
        except sqlite3.Error as exc:
            raise WritebackReceiverError("writeback_receiver_store_failed") from exc
        finally:
            if connection is not None:
                connection.close()
        encoded = json.dumps(rows, ensure_ascii=True, separators=(",", ":")).encode("ascii")
        return hashlib.sha256(encoded).hexdigest()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.path.resolve(strict=False),
            timeout=self.busy_timeout_ms / 1_000,
            isolation_level=None,
        )
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(f"PRAGMA busy_timeout = {self.busy_timeout_ms}")  # nosec B608 - validated integer
        return connection

    @staticmethod
    def _replay(request: WritebackReceiverRequest, row: sqlite3.Row | tuple[object, ...]) -> WritebackReceiverResult:
        operation, payload_digest, request_digest, provider_reference, response_digest = (str(value) for value in row)
        if (
            operation != request.operation
            or payload_digest != request.payload_digest
            or request_digest != request.request_digest
        ):
            raise WritebackReceiverError("writeback_receiver_idempotency_conflict")
        if _PROVIDER_REFERENCE_PATTERN.fullmatch(provider_reference) is None:
            raise WritebackReceiverError("writeback_receiver_history_invalid")
        response = _provider_response(request.idempotency_key, provider_reference)
        if response.response_digest != response_digest:
            raise WritebackReceiverError("writeback_receiver_history_invalid")
        return WritebackReceiverResult(
            disposition=WritebackReceiverDisposition.REPLAYED,
            request_digest=request.request_digest,
            response=response,
        )


def _provider_response(idempotency_key: str, provider_reference: str) -> WritebackProviderResponse:
    fields = {
        "accepted": True,
        "idempotency_key": idempotency_key,
        "provider_reference": provider_reference,
    }
    encoded = json.dumps(fields, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("ascii")
    return WritebackProviderResponse.model_validate(
        {**fields, "response_digest": hashlib.sha256(encoded).hexdigest()}
    )
