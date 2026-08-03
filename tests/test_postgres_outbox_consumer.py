"""Idempotent PostgreSQL outbox-consumer receipt contracts."""

from __future__ import annotations

import hashlib
import os
import re
from typing import Any
from uuid import uuid4

import pytest

from reconforge.infrastructure.postgres import (
    PostgresConnectionFactory,
    PostgresSettings,
    PostgresTenantBoundary,
    install_postgres_rls_schema,
)
from reconforge.infrastructure.postgres_ledger import POSTGRES_LEDGER_SCHEMA_SQL
from reconforge.infrastructure.postgres_master_data import POSTGRES_MASTER_DATA_SCHEMA_SQL
from reconforge.infrastructure.postgres_outbox import (
    POSTGRES_OUTBOX_APPLICATION_SCHEMA_SQL,
    PostgresOutboxRepository,
)
from reconforge.infrastructure.postgres_outbox_consumer import (
    POSTGRES_OUTBOX_CONSUMER_SCHEMA_SQL,
    PostgresOutboxConsumer,
    PostgresOutboxConsumerIntegrityError,
    PostgresOutboxConsumerValidationError,
    canonical_effect_digest,
)
from reconforge.io.persisted import encode_postgres_outbox_payload


def test_postgres_outbox_consumer_schema_is_forced_rls_and_immutable() -> None:
    assert "outbox_consumer_receipts" in POSTGRES_OUTBOX_CONSUMER_SCHEMA_SQL
    assert "FORCE ROW LEVEL SECURITY" in POSTGRES_OUTBOX_CONSUMER_SCHEMA_SQL
    assert "event_digest TEXT NOT NULL CHECK" in POSTGRES_OUTBOX_CONSUMER_SCHEMA_SQL
    assert "outbox consumer receipts are immutable" in POSTGRES_OUTBOX_CONSUMER_SCHEMA_SQL
    assert "outbox consumer receipts cannot be deleted" in POSTGRES_OUTBOX_CONSUMER_SCHEMA_SQL


def test_postgres_outbox_consumer_digest_and_input_guards_are_bounded() -> None:
    digest = hashlib.sha256(b"event").hexdigest()
    assert canonical_effect_digest("effect") == hashlib.sha256(b"effect").hexdigest()
    assert canonical_effect_digest(None) == hashlib.sha256(b"").hexdigest()
    consumer = PostgresOutboxConsumer(connection_factory=None)
    with pytest.raises(PostgresOutboxConsumerValidationError):
        consumer.apply(
            tenant_id="tenant_a",
            consumer_id="consumer_a",
            event_id="event_a",
            event_digest="not-a-digest",
            effect=lambda _connection: None,
        )
    with pytest.raises(PostgresOutboxConsumerValidationError):
        consumer.apply(
            tenant_id="tenant_a",
            consumer_id="consumer with spaces",
            event_id="event_a",
            event_digest=digest,
            effect=lambda _connection: None,
        )
    assert re.fullmatch(r"[a-f0-9]{64}", digest)


@pytest.mark.skipif(
    not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"), reason="requires a live PostgreSQL service"
)
def test_live_postgres_consumer_receipt_prevents_duplicate_effect_after_ack_crash() -> None:
    """A committed consumer effect is not repeated when outbox ack is lost."""

    pytest.importorskip("psycopg")
    dsn = os.environ["RECONFORGE_TEST_POSTGRES_DSN"]
    admin_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN", dsn)
    app_user = os.environ.get("RECONFORGE_TEST_POSTGRES_APP_USER", "")
    if not app_user:
        pytest.skip("requires a non-privileged application role")
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", app_user):
        pytest.fail("RECONFORGE_TEST_POSTGRES_APP_USER contains unsafe characters")
    factory = PostgresConnectionFactory(PostgresSettings(dsn=dsn, require_tls=False))
    admin_factory = PostgresConnectionFactory(PostgresSettings(dsn=admin_dsn, require_tls=False))
    tenant_id = "consumer_live_" + uuid4().hex[:8]
    event_id = "event-live-" + uuid4().hex[:8]
    consumer_id = "ledger-consumer"
    payload = {"entry_id": "entry-live", "amount": "10.00"}
    payload_json = encode_postgres_outbox_payload(payload).text
    event_digest = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
    admin = admin_factory.connect()
    try:
        with admin.transaction():
            install_postgres_rls_schema(admin)
            admin.execute(POSTGRES_MASTER_DATA_SCHEMA_SQL)
            admin.execute(POSTGRES_LEDGER_SCHEMA_SQL)
            admin.execute(POSTGRES_OUTBOX_APPLICATION_SCHEMA_SQL)
            admin.execute(POSTGRES_OUTBOX_CONSUMER_SCHEMA_SQL)
            admin.execute(
                """
                CREATE TABLE IF NOT EXISTS reconforge.consumer_effect_probe (
                    tenant_id TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    effect_count INTEGER NOT NULL,
                    PRIMARY KEY (tenant_id, event_id)
                )
                """
            )
            admin.execute(f"GRANT USAGE ON SCHEMA reconforge TO {app_user}")
            admin.execute(f"GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA reconforge TO {app_user}")
            admin.execute("INSERT INTO reconforge.tenants(id,name) VALUES(%s,%s)", (tenant_id, tenant_id))
        with PostgresTenantBoundary(factory).transaction(tenant_id) as connection:
            connection.execute(
                """
                INSERT INTO reconforge.outbox_events(
                    tenant_id,event_id,event_type,aggregate_type,aggregate_id,payload
                ) VALUES(%s,%s,'ledger.entry_posted','ledger_entry',%s,%s::jsonb)
                """,
                (tenant_id, event_id, payload["entry_id"], payload_json),
            )
        consumer = PostgresOutboxConsumer(factory)

        def effect(connection: Any) -> str:
            connection.execute(
                """
                INSERT INTO reconforge.consumer_effect_probe(tenant_id,event_id,effect_count)
                VALUES(%s,%s,1)
                ON CONFLICT (tenant_id,event_id)
                DO UPDATE SET effect_count = reconforge.consumer_effect_probe.effect_count + 1
                """,
                (tenant_id, event_id),
            )
            return "ledger-effect-v1"

        with PostgresTenantBoundary(factory).transaction(tenant_id) as connection:
            claimed = PostgresOutboxRepository(connection).claim_pending(
                tenant_id=tenant_id, worker_id="publisher-a", limit=1, lease_seconds=1
            )
        assert len(claimed) == 1
        first = consumer.apply(
            tenant_id=tenant_id,
            consumer_id=consumer_id,
            event_id=event_id,
            event_digest=event_digest,
            effect=effect,
        )
        assert first.status == "applied"
        # Simulate a process crash after the consumer transaction committed but
        # before the publisher acknowledged the outbox row.
        with PostgresTenantBoundary(factory).transaction(tenant_id) as connection:
            connection.execute(
                """
                UPDATE reconforge.outbox_events
                SET claimed_at = now() - interval '1 second'
                WHERE tenant_id=%s AND event_id=%s
                """,
                (tenant_id, event_id),
            )
            retry = PostgresOutboxRepository(connection).claim_pending(
                tenant_id=tenant_id, worker_id="publisher-b", limit=1, lease_seconds=60
            )
        assert len(retry) == 1
        duplicate = consumer.apply(
            tenant_id=tenant_id,
            consumer_id=consumer_id,
            event_id=event_id,
            event_digest=event_digest,
            effect=effect,
        )
        assert duplicate.status == "duplicate"
        with PostgresTenantBoundary(factory).transaction(tenant_id) as connection:
            PostgresOutboxRepository(connection).mark_published(
                tenant_id=tenant_id, event_id=event_id, worker_id="publisher-b"
            )
            count = connection.execute(
                "SELECT effect_count FROM reconforge.consumer_effect_probe WHERE tenant_id=%s AND event_id=%s",
                (tenant_id, event_id),
            ).fetchone()[0]
            receipt_count = connection.execute(
                """
                SELECT COUNT(*) FROM reconforge.outbox_consumer_receipts
                WHERE tenant_id=%s AND consumer_id=%s AND event_id=%s
                """,
                (tenant_id, consumer_id, event_id),
            ).fetchone()[0]
            assert count == 1
            assert receipt_count == 1
        with pytest.raises(PostgresOutboxConsumerIntegrityError):
            consumer.apply(
                tenant_id=tenant_id,
                consumer_id=consumer_id,
                event_id=event_id,
                event_digest=hashlib.sha256(b"different-event").hexdigest(),
                effect=effect,
            )
    finally:
        try:
            with admin.transaction():
                admin.execute("DROP TABLE IF EXISTS reconforge.consumer_effect_probe")
                admin.execute("DELETE FROM reconforge.tenants WHERE id=%s", (tenant_id,))
        except Exception:
            pass
        admin.close()
