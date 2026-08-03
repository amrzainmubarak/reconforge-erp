"""Tenant-scoped idempotent PostgreSQL outbox-consumer effects.

The consumer boundary is deliberately transaction-bound: the business effect
callback receives the same PostgreSQL connection used to insert the receipt.
This gives a concrete exactly-once *business effect* boundary for effects that
are persisted in that database.  It does not claim exactly-once delivery over
an external broker or provider; those systems still need their own idempotency
key and acknowledgement contract.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from reconforge.infrastructure.postgres import (
    PostgresConfigurationError,
    PostgresTenantBoundary,
    normalize_scope_id,
    validate_tenant_id,
)
from reconforge.io.persisted import PersistedJsonError, decode_postgres_outbox_payload

_DIGEST_PATTERN = re.compile(r"^[a-f0-9]{64}$")
_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


class PostgresOutboxConsumerValidationError(ValueError):
    """Raised when an idempotent consumer request is malformed."""


class PostgresOutboxConsumerIntegrityError(RuntimeError):
    """Raised when an event is replayed with a different payload digest."""


class PostgresOutboxConsumerEffectError(RuntimeError):
    """Raised when the effect fails and its receipt transaction is rolled back."""


POSTGRES_OUTBOX_CONSUMER_SCHEMA_SQL = r"""
CREATE TABLE IF NOT EXISTS reconforge.outbox_consumer_receipts (
    tenant_id TEXT NOT NULL,
    consumer_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    event_digest TEXT NOT NULL CHECK (event_digest ~ '^[a-f0-9]{64}$'),
    effect_digest TEXT NOT NULL CHECK (effect_digest ~ '^[a-f0-9]{64}$'),
    status TEXT NOT NULL DEFAULT 'applied' CHECK (status = 'applied'),
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, consumer_id, event_id),
    FOREIGN KEY (tenant_id) REFERENCES reconforge.tenants(id) ON DELETE CASCADE,
    FOREIGN KEY (tenant_id, event_id)
        REFERENCES reconforge.outbox_events(tenant_id, event_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS outbox_consumer_receipts_event_idx
    ON reconforge.outbox_consumer_receipts(tenant_id, event_id, consumer_id);
ALTER TABLE reconforge.outbox_consumer_receipts ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.outbox_consumer_receipts FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.outbox_consumer_receipts;
CREATE POLICY tenant_scope ON reconforge.outbox_consumer_receipts
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
CREATE OR REPLACE FUNCTION reconforge.guard_outbox_consumer_receipt()
RETURNS TRIGGER LANGUAGE plpgsql AS $reconforge$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        RAISE EXCEPTION 'outbox consumer receipts are immutable' USING ERRCODE='check_violation';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'outbox consumer receipts cannot be deleted' USING ERRCODE='check_violation';
    END IF;
    RETURN NEW;
END
$reconforge$;
DROP TRIGGER IF EXISTS outbox_consumer_receipt_guard
    ON reconforge.outbox_consumer_receipts;
CREATE TRIGGER outbox_consumer_receipt_guard
BEFORE UPDATE OR DELETE ON reconforge.outbox_consumer_receipts
FOR EACH ROW EXECUTE FUNCTION reconforge.guard_outbox_consumer_receipt();
"""


def _scope_id(value: object, field_name: str) -> str:
    try:
        normalized = normalize_scope_id(str(value), field_name=field_name)
    except PostgresConfigurationError as exc:
        raise PostgresOutboxConsumerValidationError(str(exc)) from exc
    if not _ID_PATTERN.fullmatch(normalized):
        raise PostgresOutboxConsumerValidationError(f"{field_name} has an invalid identifier.")
    return normalized


def _tenant(value: object) -> str:
    try:
        return validate_tenant_id(str(value))
    except PostgresConfigurationError as exc:
        raise PostgresOutboxConsumerValidationError(str(exc)) from exc


def _digest(value: object, field_name: str) -> str:
    normalized = str(value or "").strip().lower()
    if not _DIGEST_PATTERN.fullmatch(normalized):
        raise PostgresOutboxConsumerValidationError(f"{field_name} must be a lowercase SHA-256 digest.")
    return normalized


def canonical_effect_digest(value: object) -> str:
    """Return a non-reversible digest for a consumer effect result."""

    if value is None:
        data = b""
    elif isinstance(value, bytes):
        data = value
    else:
        data = str(value).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class PostgresOutboxConsumerReceipt:
    """Receipt returned after an effect is applied or recognized as a replay."""

    tenant_id: str
    consumer_id: str
    event_id: str
    event_digest: str
    effect_digest: str
    status: str


@dataclass(frozen=True)
class PostgresOutboxConsumer:
    """Apply a tenant-scoped outbox event exactly once inside PostgreSQL."""

    connection_factory: Any

    def apply(
        self,
        *,
        tenant_id: str,
        consumer_id: str,
        event_id: str,
        event_digest: str,
        effect: Callable[[Any], object],
    ) -> PostgresOutboxConsumerReceipt:
        """Run ``effect`` once and atomically persist its receipt.

        The callback must only perform work on the supplied connection.  If it
        raises, both the business writes and the receipt roll back.  A later
        delivery with the same event digest returns ``duplicate`` without
        invoking the callback.  A changed digest fails closed.
        """

        tenant = _tenant(tenant_id)
        consumer = _scope_id(consumer_id, "consumer_id")
        event = _scope_id(event_id, "event_id")
        payload_digest = _digest(event_digest, "event_digest")
        if not callable(effect):
            raise PostgresOutboxConsumerValidationError("effect must be callable.")
        lock_key = f"outbox-consumer:{tenant}:{consumer}:{event}"
        try:
            with PostgresTenantBoundary(self.connection_factory).transaction(tenant) as connection:
                # Serialize the same event/consumer pair without requiring
                # UPDATE privilege on the append-only receipt table.
                connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (lock_key,))
                source_event = connection.execute(
                    """
                    SELECT payload
                    FROM reconforge.outbox_events
                    WHERE tenant_id=%s AND event_id=%s
                    """,
                    (tenant, event),
                ).fetchone()
                if source_event is None:
                    raise PostgresOutboxConsumerIntegrityError("outbox event is not available for consumption.")
                try:
                    source_digest = decode_postgres_outbox_payload(source_event[0]).checksum_sha256
                except PersistedJsonError as exc:
                    raise PostgresOutboxConsumerIntegrityError("outbox event payload failed integrity validation.") from exc
                if source_digest != payload_digest:
                    raise PostgresOutboxConsumerIntegrityError("event digest does not match the persisted outbox payload.")
                existing = connection.execute(
                    """
                    SELECT event_digest, effect_digest
                    FROM reconforge.outbox_consumer_receipts
                    WHERE tenant_id=%s AND consumer_id=%s AND event_id=%s
                    """,
                    (tenant, consumer, event),
                ).fetchone()
                if existing is not None:
                    stored_digest = str(existing[0])
                    if stored_digest != payload_digest:
                        raise PostgresOutboxConsumerIntegrityError(
                            "event replay digest differs from the recorded consumer receipt."
                        )
                    return PostgresOutboxConsumerReceipt(
                        tenant_id=tenant,
                        consumer_id=consumer,
                        event_id=event,
                        event_digest=stored_digest,
                        effect_digest=str(existing[1]),
                        status="duplicate",
                    )
                try:
                    result = effect(connection)
                except Exception as exc:  # noqa: BLE001 - rollback boundary is intentional.
                    raise PostgresOutboxConsumerEffectError(
                        "consumer effect failed; receipt and database writes were rolled back."
                    ) from exc
                result_digest = canonical_effect_digest(result)
                connection.execute(
                    """
                    INSERT INTO reconforge.outbox_consumer_receipts(
                        tenant_id, consumer_id, event_id, event_digest,
                        effect_digest, status, applied_at
                    ) VALUES (%s, %s, %s, %s, %s, 'applied', now())
                    """,
                    (tenant, consumer, event, payload_digest, result_digest),
                )
                return PostgresOutboxConsumerReceipt(
                    tenant_id=tenant,
                    consumer_id=consumer,
                    event_id=event,
                    event_digest=payload_digest,
                    effect_digest=result_digest,
                    status="applied",
                )
        except (
            PostgresOutboxConsumerValidationError,
            PostgresOutboxConsumerIntegrityError,
            PostgresOutboxConsumerEffectError,
        ):
            raise
        except Exception as exc:
            raise PostgresOutboxConsumerIntegrityError("idempotent consumer transaction failed safely.") from exc


def install_postgres_outbox_consumer_schema(connection: Any) -> None:
    """Install the receipt schema for an explicitly managed connection."""

    connection.execute(POSTGRES_OUTBOX_CONSUMER_SCHEMA_SQL)
