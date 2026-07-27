from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest

from reconforge.application.idempotency import (
    IdempotencyApplicationService,
    IdempotencyConflictError,
    IdempotencyInProgressError,
    IdempotencyOwnershipError,
)
from reconforge.infrastructure.postgres import PostgresConnectionFactory, PostgresSettings, install_postgres_rls_schema
from reconforge.infrastructure.postgres_idempotency import (
    POSTGRES_IDEMPOTENCY_SCHEMA_SQL,
    PostgresIdempotencyRepository,
    install_postgres_idempotency_schema,
)


def test_postgres_idempotency_schema_forces_tenant_rls() -> None:
    assert "FORCE ROW LEVEL SECURITY" in POSTGRES_IDEMPOTENCY_SCHEMA_SQL
    assert "PRIMARY KEY (tenant_id,scope,idempotency_key)" in POSTGRES_IDEMPOTENCY_SCHEMA_SQL


@pytest.mark.skipif(not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"), reason="requires live PostgreSQL")
def test_live_postgres_idempotency_concurrency_replay_expiry_and_isolation() -> None:
    pytest.importorskip("psycopg")
    dsn = os.environ["RECONFORGE_TEST_POSTGRES_DSN"]
    admin_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN", dsn)
    app_user = os.environ.get("RECONFORGE_TEST_POSTGRES_APP_USER", "")
    if not app_user:
        pytest.skip("requires a non-privileged application role")
    factory = PostgresConnectionFactory(PostgresSettings(dsn=dsn, require_tls=False))
    admin_factory = PostgresConnectionFactory(PostgresSettings(dsn=admin_dsn, require_tls=False))
    tenant_a, tenant_b = "idem_a_" + uuid4().hex[:8], "idem_b_" + uuid4().hex[:8]
    admin = admin_factory.connect()
    try:
        with admin.transaction():
            install_postgres_rls_schema(admin)
            admin.execute("DROP TABLE IF EXISTS reconforge.idempotency_records")
            install_postgres_idempotency_schema(admin)
            admin.execute(f"GRANT USAGE ON SCHEMA reconforge TO {app_user}")
            admin.execute(f"GRANT SELECT,INSERT,UPDATE,DELETE ON reconforge.idempotency_records TO {app_user}")
            for tenant in (tenant_a, tenant_b):
                admin.execute("INSERT INTO reconforge.tenants(id,name) VALUES (%s,%s)", (tenant, tenant))

        def reserve(index: int) -> str:
            service = IdempotencyApplicationService(PostgresIdempotencyRepository(factory, tenant_a))
            try:
                result = service.begin(
                    tenant_id=tenant_a, scope="payments", key="same", request=b"request",
                    owner_token=f"worker-{index}", created_at="2026-07-27T10:00:00Z",
                    expires_at="2026-07-27T11:00:00Z", observed_at="2026-07-27T10:00:00Z",
                )
                return "created" if result.created else "replayed"
            except IdempotencyInProgressError:
                return "in-progress"

        with ThreadPoolExecutor(max_workers=6) as executor:
            outcomes = list(executor.map(reserve, range(6)))
        assert outcomes.count("created") == 1 and outcomes.count("in-progress") == 5
        service = IdempotencyApplicationService(PostgresIdempotencyRepository(factory, tenant_a))
        first = service.begin(
            tenant_id=tenant_a, scope="reports", key="sequential", request=b"request-v1",
            owner_token="owner-1", created_at="2026-07-27T10:00:00Z",
            expires_at="2026-07-27T11:00:00Z", observed_at="2026-07-27T10:00:00Z",
        )
        with pytest.raises(IdempotencyConflictError):
            service.begin(
                tenant_id=tenant_a, scope="reports", key="sequential", request=b"different",
                owner_token="owner-2", created_at="2026-07-27T10:00:00Z",
                expires_at="2026-07-27T11:00:00Z", observed_at="2026-07-27T10:00:00Z",
            )
        completed = service.complete(
            first.reservation, response=b"response-v1", content_type="application/octet-stream",
            completed_at="2026-07-27T10:01:00Z",
        )
        replay = service.begin(
            tenant_id=tenant_a, scope="reports", key="sequential", request=b"request-v1",
            owner_token="owner-3", created_at="2026-07-27T10:00:00Z",
            expires_at="2026-07-27T11:00:00Z", observed_at="2026-07-27T10:02:00Z",
        )
        assert replay.replayed is True and replay.reservation == completed
        replacement = service.begin(
            tenant_id=tenant_a, scope="reports", key="sequential", request=b"request-v2",
            owner_token="owner-4", created_at="2026-07-27T11:00:01Z",
            expires_at="2026-07-27T12:00:00Z", observed_at="2026-07-27T11:00:01Z",
        )
        assert replacement.created is True
        with pytest.raises(IdempotencyOwnershipError):
            service.complete(
                first.reservation, response=b"stale", content_type="text/plain",
                completed_at="2026-07-27T11:01:00Z",
            )
        isolated = factory.connect()
        try:
            with isolated.transaction():
                isolated.execute("SELECT set_config('app.tenant_id', %s, true)", (tenant_b,))
                assert isolated.execute("SELECT count(*) FROM reconforge.idempotency_records").fetchone()[0] == 0
        finally:
            isolated.close()
    finally:
        admin.close()
