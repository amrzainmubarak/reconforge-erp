"""Contract tests for PostgreSQL outbox delivery and worker leases."""

from __future__ import annotations

import os
import re
from contextlib import contextmanager
from typing import Any
from uuid import uuid4

import pytest

from reconforge.application.outbox import OutboxApplicationService, OutboxError, OutboxRepositoryProtocol
from reconforge.auth.policy import PolicyEvaluationContext
from reconforge.benchmark.postgres_outbox_scale import (
    default_profile as postgres_outbox_scale_profile,
)
from reconforge.benchmark.postgres_outbox_scale import (
    run_postgres_outbox_scale_profile,
    verify_postgres_outbox_scale_result,
)
from reconforge.infrastructure.postgres import (
    PostgresConnectionFactory,
    PostgresSettings,
    PostgresTenantBoundary,
    install_postgres_rls_schema,
)
from reconforge.infrastructure.postgres_ledger import POSTGRES_LEDGER_SCHEMA_SQL
from reconforge.infrastructure.postgres_master_data import POSTGRES_MASTER_DATA_SCHEMA_SQL
from reconforge.infrastructure.postgres_outbox import (
    _LIST_OUTBOX_EVENT_QUERIES,
    POSTGRES_OUTBOX_APPLICATION_SCHEMA_SQL,
    PostgresOutboxIntegrityError,
    PostgresOutboxRepository,
    PostgresOutboxValidationError,
    TenantBoundPostgresOutboxRepository,
    tenant_bound_postgres_outbox_repository,
)
from reconforge.workers.outbox import OutboxWorkerSettings
from reconforge.workers.postgres_outbox import PostgresOutboxWorker, PostgresOutboxWorkerError


class _Cursor:
    def __init__(
        self,
        row: tuple[Any, ...] | None = None,
        rows: list[tuple[Any, ...]] | None = None,
        *,
        rowcount: int = 0,
    ) -> None:
        self.row = row
        self.rows = rows or []
        self.rowcount = rowcount

    def fetchone(self) -> tuple[Any, ...] | None:
        return self.row

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self.rows


class _FakeConnection:
    def __init__(
        self, *, attempt_count: int = 1, publishable: bool = True,
        list_status: str = "Pending", dead_lettered_at: str | None = None,
    ) -> None:
        self.attempt_count = attempt_count
        self.publishable = publishable
        self.list_status = list_status
        self.dead_lettered_at = dead_lettered_at
        self.claimed = False
        self.commits = 0
        self.executed: list[tuple[str, tuple[Any, ...] | None]] = []

    @contextmanager
    def transaction(self) -> Any:
        yield self
        self.commits += 1

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> _Cursor:
        self.executed.append((sql, params))
        normalized = " ".join(sql.split()).lower()
        if normalized.startswith("select set_config"):
            return _Cursor()
        if normalized.startswith("with candidates"):
            if self.claimed:
                return _Cursor(rows=[])
            self.claimed = True
            return _Cursor(
                rows=[
                    (
                        "tenant_a",
                        "evt-1",
                        "ledger.entry_posted",
                        "ledger_entry",
                        "entry-a",
                        {"entry_id": "entry-a"},
                        "Claimed",
                        self.attempt_count,
                        "2026-07-23T00:00:00Z",
                        "2026-07-23T00:05:00Z",
                        "worker-a",
                        None,
                        None,
                        None,
                        "2026-07-23T00:00:00Z",
                        "workspace-a",
                        "org-a",
                        "entity-a",
                    )
                ]
            )
        if normalized.startswith("select attempt_count"):
            return _Cursor(row=(self.attempt_count,))
        if normalized.startswith("update reconforge.outbox_events"):
            return _Cursor(rowcount=0 if params and "other-worker" in params else 1)
        if normalized.startswith("select tenant_id, event_id"):
            return _Cursor(
                rows=[
                    (
                        "tenant_a",
                        "evt-1",
                        "ledger.entry_posted",
                        "ledger_entry",
                        "entry-a",
                        {"entry_id": "entry-a"},
                        self.list_status,
                        self.attempt_count,
                        "2026-07-23T00:00:00Z",
                        None,
                        None,
                        None,
                        None,
                        self.dead_lettered_at,
                        "2026-07-23T00:00:00Z",
                        "workspace-a",
                        "org-a",
                        "entity-a",
                    )
                ]
            )
        if normalized.startswith("select count(*) filter"):
            return _Cursor(row=(1, 0, 0, 0))
        return _Cursor()

    def close(self) -> None:
        return None


class _FakeFactory:
    def __init__(self, connection: _FakeConnection) -> None:
        self.connection = connection

    def connect(self) -> _FakeConnection:
        return self.connection


def test_postgres_outbox_claim_and_transitions_are_tenant_scoped() -> None:
    assert "claimed_by TEXT" in POSTGRES_LEDGER_SCHEMA_SQL
    assert "workspace_id TEXT DEFAULT NULLIF(current_setting('app.workspace_id'" in POSTGRES_LEDGER_SCHEMA_SQL
    assert "organization_id TEXT DEFAULT NULLIF(current_setting('app.organization_id'" in POSTGRES_LEDGER_SCHEMA_SQL
    assert "legal_entity_id TEXT DEFAULT NULLIF(current_setting('app.legal_entity_id'" in POSTGRES_LEDGER_SCHEMA_SQL
    assert "idx_outbox_events_scope_pending" in POSTGRES_LEDGER_SCHEMA_SQL
    connection = _FakeConnection()
    repository = PostgresOutboxRepository(connection)

    events = repository.claim_pending(
        tenant_id="TENANT_A",
        worker_id="worker-a",
        limit=10,
        max_attempts=5,
        lease_seconds=60,
    )
    repository.mark_published(tenant_id="tenant_a", event_id="evt-1", worker_id="worker-a")

    assert events[0].id == "evt-1"
    assert events[0].payload == {"entry_id": "entry-a"}
    assert events[0].payload_json == '{"entry_id":"entry-a"}'
    assert connection.commits == 0
    assert any("FOR UPDATE SKIP LOCKED" in sql for sql, _ in connection.executed)
    assert any(params is not None and "tenant_a" in params for _, params in connection.executed)


def test_postgres_outbox_failure_dead_letters_at_max_attempts() -> None:
    connection = _FakeConnection(attempt_count=1)
    repository = PostgresOutboxRepository(connection)

    dead = repository.mark_failed(
        tenant_id="tenant_a",
        event_id="evt-1",
        worker_id="worker-a",
        error="publisher unavailable",
        max_attempts=1,
    )

    assert dead is True
    assert connection.commits == 0
    assert any("dead_lettered_at = now()" in sql for sql, _ in connection.executed)


def test_postgres_outbox_rejects_wrong_worker_and_invalid_status() -> None:
    repository = PostgresOutboxRepository(_FakeConnection())
    with pytest.raises(PostgresOutboxIntegrityError):
        repository.mark_published(tenant_id="tenant_a", event_id="evt-1", worker_id="other-worker")
    with pytest.raises(PostgresOutboxValidationError):
        repository.list_events(tenant_id="tenant_a", status="unknown")


def test_postgres_outbox_worker_publishes_with_idempotent_event_id() -> None:
    connection = _FakeConnection()
    published: list[str] = []
    worker = PostgresOutboxWorker(
        _FakeFactory(connection),
        tenant_supplier=lambda: ["tenant_a"],
        publisher=lambda event: published.append(event.id),
        settings=OutboxWorkerSettings(worker_id="worker-a", poll_interval_seconds=0),
    )

    result = worker.process_once()

    assert result.claimed == 1
    assert result.published == 1
    assert result.failed == 0
    assert published == ["evt-1"]
    assert connection.commits == 2


def test_postgres_outbox_worker_records_publisher_failure() -> None:
    connection = _FakeConnection(attempt_count=1)

    def publish(_: object) -> None:
        raise RuntimeError("transport unavailable")

    worker = PostgresOutboxWorker(
        _FakeFactory(connection),
        tenant_supplier=lambda: ["tenant_a"],
        publisher=publish,
        settings=OutboxWorkerSettings(worker_id="worker-a", max_attempts=1, poll_interval_seconds=0),
    )

    result = worker.process_once()

    assert result.claimed == 1
    assert result.published == 0
    assert result.failed == 1
    assert result.dead_lettered == 1


def test_postgres_outbox_worker_policy_denies_before_connection_access() -> None:
    class _NeverConnect:
        def connect(self) -> Any:
            raise AssertionError("policy denial must precede connection access")

    worker = PostgresOutboxWorker(
        _NeverConnect(),
        tenant_supplier=lambda: ["tenant_a"],
        publisher=lambda _event: None,
        settings=OutboxWorkerSettings(
            worker_id="outbox-policy-worker",
            policy_context_supplier=lambda tenant: PolicyEvaluationContext(
                user_id="outbox-policy-worker",
                username="outbox-policy-worker",
                user_permissions=set(),
                principal_type="service_account",
                tenant_id=tenant,
                authorized_tenant_ids=frozenset({tenant}),
            ),
        ),
    )
    with pytest.raises(PostgresOutboxWorkerError, match="permission_missing"):
        worker.process_once()


def test_postgres_outbox_worker_policy_allows_scoped_service_identity() -> None:
    connection = _FakeConnection()
    worker = PostgresOutboxWorker(
        _FakeFactory(connection),
        tenant_supplier=lambda: ["tenant_a"],
        publisher=lambda _event: None,
        settings=OutboxWorkerSettings(
            worker_id="outbox-policy-worker",
            policy_context_supplier=lambda tenant: PolicyEvaluationContext(
                user_id="outbox-policy-worker",
                username="outbox-policy-worker",
                user_permissions={"outbox.publish"},
                principal_type="service_account",
                tenant_id=tenant,
                authorized_tenant_ids=frozenset({tenant}),
            ),
        ),
    )
    result = worker.process_once()
    assert result.published == 1


def test_postgres_outbox_worker_rechecks_policy_before_publisher_side_effect() -> None:
    connection = _FakeConnection()
    policy_calls = 0
    published: list[str] = []

    def policy_context(tenant: str) -> PolicyEvaluationContext:
        nonlocal policy_calls
        policy_calls += 1
        permissions = {"outbox.publish"} if policy_calls == 1 else set()
        return PolicyEvaluationContext(
            user_id="outbox-revocation-worker",
            username="outbox-revocation-worker",
            user_permissions=permissions,
            principal_type="service_account",
            tenant_id=tenant,
            authorized_tenant_ids=frozenset({tenant}),
        )

    worker = PostgresOutboxWorker(
        _FakeFactory(connection),
        tenant_supplier=lambda: ["tenant_a"],
        publisher=lambda event: published.append(event.id),
        settings=OutboxWorkerSettings(
            worker_id="outbox-revocation-worker",
            policy_context_supplier=policy_context,
            poll_interval_seconds=0,
        ),
    )

    with pytest.raises(PostgresOutboxWorkerError, match="permission_missing"):
        worker.process_once()

    assert policy_calls == 2
    assert published == []
    assert connection.commits == 1  # claim committed; no publish acknowledgment was written
    assert not any("SET status = 'Published'" in sql for sql, _ in connection.executed)


def test_postgres_outbox_worker_processes_exact_hierarchy_lane() -> None:
    connection = _FakeConnection()

    def policy_context(
        tenant: str,
        workspace: str | None,
        organization: str | None,
        entity: str | None,
    ) -> PolicyEvaluationContext:
        return PolicyEvaluationContext(
            user_id="outbox-scoped-worker",
            username="outbox-scoped-worker",
            user_permissions={"outbox.publish"},
            principal_type="service_account",
            tenant_id=tenant,
            organization_id=organization,
            workspace_id=workspace,
            entity_id=entity,
            authorized_tenant_ids=frozenset({tenant}),
            authorized_organization_ids=frozenset({organization}) if organization else frozenset(),
            authorized_workspace_ids=frozenset({workspace}) if workspace else frozenset(),
            authorized_entity_ids=frozenset({entity}) if entity else frozenset(),
        )

    worker = PostgresOutboxWorker(
        _FakeFactory(connection),
        tenant_supplier=lambda: ["tenant-without-scope-must-not-be-used"],
        publisher=lambda _event: None,
        settings=OutboxWorkerSettings(
            worker_id="outbox-scoped-worker",
            poll_interval_seconds=0,
            policy_context_hierarchy_supplier=policy_context,
            scope_supplier=lambda: (("tenant_a", "workspace-a", "org-a", "entity-a"),),
        ),
    )

    result = worker.process_once()

    assert result.published == 1
    assert any(
        "set_config('app.organization_id'" in sql and params == ("org-a",)
        for sql, params in connection.executed
    )
    assert any(
        "set_config('app.legal_entity_id'" in sql and params == ("entity-a",)
        for sql, params in connection.executed
    )
    claim_params = next(params for sql, params in connection.executed if "FOR UPDATE SKIP LOCKED" in sql)
    assert claim_params[:4] == ("tenant_a", "workspace-a", "org-a", "entity-a")


def test_postgres_outbox_worker_requires_hierarchy_policy_for_organization_lane() -> None:
    worker = PostgresOutboxWorker(
        _FakeFactory(_FakeConnection()),
        tenant_supplier=lambda: [],
        publisher=lambda _event: None,
        settings=OutboxWorkerSettings(
            worker_id="outbox-organization-policy",
            policy_context_scope_supplier=lambda tenant, workspace, entity: PolicyEvaluationContext(
                user_id="outbox-organization-policy",
                username="outbox-organization-policy",
                user_permissions={"outbox.publish"},
                principal_type="service_account",
                tenant_id=tenant,
                workspace_id=workspace,
                entity_id=entity,
                authorized_tenant_ids=frozenset({tenant}),
                authorized_workspace_ids=frozenset({workspace}) if workspace else frozenset(),
                authorized_entity_ids=frozenset({entity}) if entity else frozenset(),
            ),
            scope_supplier=lambda: (("tenant_a", None, "org-a", None),),
        ),
    )
    with pytest.raises(PostgresOutboxWorkerError, match="hierarchy-aware"):
        worker.process_once()


def test_postgres_outbox_worker_rejects_entity_lane_without_organization_before_connection() -> None:
    class _NeverConnect:
        def connect(self) -> Any:
            raise AssertionError("invalid hierarchy must be rejected before connection access")

    worker = PostgresOutboxWorker(
        _NeverConnect(),
        tenant_supplier=lambda: [],
        publisher=lambda _event: None,
        settings=OutboxWorkerSettings(
            worker_id="outbox-invalid-scope",
            scope_supplier=lambda: (("tenant_a", "workspace-a", None, "entity-a"),),
        ),
    )
    with pytest.raises(PostgresOutboxWorkerError, match="requires organization"):
        worker.process_once()


def test_tenant_bound_postgres_adapter_satisfies_application_contract() -> None:
    connection = _FakeConnection()
    repository: OutboxRepositoryProtocol = tenant_bound_postgres_outbox_repository(
        connection, tenant_id="TENANT_A"
    )

    published: list[str] = []
    result = OutboxApplicationService(repository).process_once(
        publisher=lambda event: published.append(event.payload_json),
        worker_id="worker-a",
    )

    assert result.published == 1
    assert published == ['{"entry_id":"entry-a"}']
    assert all(params is None or "tenant_a" in params for sql, params in connection.executed if "outbox_events" in sql)


def test_tenant_bound_postgres_adapter_maps_status_and_safe_errors() -> None:
    connection = _FakeConnection()
    repository = TenantBoundPostgresOutboxRepository(
        PostgresOutboxRepository(connection), tenant_id="tenant_a"
    )

    events = repository.list_events(status="dead_letter")
    assert events[0].attempts == 1
    assert events[0].dead_lettered_at is None
    assert connection.executed[-1][1] == ("tenant_a", 100)

    with pytest.raises(OutboxError, match="status must be"):
        repository.list_events(status="unknown")


def test_postgres_application_pending_includes_leases_and_dead_timestamp_is_real() -> None:
    assert "status IN ('Pending', 'Claimed')" in _LIST_OUTBOX_EVENT_QUERIES["pending"]
    connection = _FakeConnection(list_status="Dead", dead_lettered_at="2026-07-23T00:10:00Z")
    repository = TenantBoundPostgresOutboxRepository(
        PostgresOutboxRepository(connection), tenant_id="tenant_a"
    )
    event = repository.list_events(status="dead_letter")[0]
    assert event.dead_lettered_at == "2026-07-23T00:10:00Z"
    assert "dead_lettered_at TIMESTAMPTZ" in POSTGRES_OUTBOX_APPLICATION_SCHEMA_SQL
    assert "dead outbox state requires exclusive transition evidence" in POSTGRES_OUTBOX_APPLICATION_SCHEMA_SQL


def test_tenant_bound_postgres_adapter_rejects_invalid_tenant_before_query() -> None:
    connection = _FakeConnection()
    with pytest.raises(PostgresOutboxValidationError):
        TenantBoundPostgresOutboxRepository(
            PostgresOutboxRepository(connection), tenant_id="tenant with spaces"
        )
    assert connection.executed == []


@pytest.mark.skipif(
    not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"), reason="requires a live PostgreSQL service"
)
def test_live_postgres_outbox_application_claim_retry_dead_replay_publish_and_rls() -> None:
    psycopg = pytest.importorskip("psycopg")
    dsn = os.environ["RECONFORGE_TEST_POSTGRES_DSN"]
    admin_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN", dsn)
    app_user = os.environ.get("RECONFORGE_TEST_POSTGRES_APP_USER", "")
    if not app_user:
        pytest.skip("requires a non-privileged application role")
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", app_user):
        pytest.fail("RECONFORGE_TEST_POSTGRES_APP_USER contains unsafe characters")
    factory = PostgresConnectionFactory(PostgresSettings(dsn=dsn, require_tls=False))
    admin_factory = PostgresConnectionFactory(PostgresSettings(dsn=admin_dsn, require_tls=False))
    tenant_a = "outbox_a_" + uuid4().hex[:8]
    tenant_b = "outbox_b_" + uuid4().hex[:8]
    admin = admin_factory.connect()
    try:
        with admin.transaction():
            install_postgres_rls_schema(admin)
            admin.execute(POSTGRES_MASTER_DATA_SCHEMA_SQL)
            admin.execute(POSTGRES_LEDGER_SCHEMA_SQL)
            admin.execute(POSTGRES_OUTBOX_APPLICATION_SCHEMA_SQL)
            admin.execute(f"GRANT USAGE ON SCHEMA reconforge TO {app_user}")
            admin.execute(f"GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA reconforge TO {app_user}")
            admin.execute(
                "INSERT INTO reconforge.tenants(id,name) VALUES(%s,%s),(%s,%s)",
                (tenant_a, tenant_a, tenant_b, tenant_b),
            )
        with factory.connect() as probe:
            role = probe.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone()
        if role is None or bool(role[0]) or bool(role[1]):
            pytest.skip("requires a non-superuser, non-BYPASSRLS application role")
        with PostgresTenantBoundary(factory).transaction(tenant_a) as connection:
            for event_id in ("evt-live-1", "evt-live-2"):
                connection.execute(
                    """INSERT INTO reconforge.outbox_events(
                    tenant_id,event_id,event_type,aggregate_type,aggregate_id,payload)
                    VALUES(%s,%s,'test.created','test',%s,'{}'::jsonb)""",
                    (tenant_a, event_id, event_id),
                )
        with PostgresTenantBoundary(factory).transaction(tenant_a) as connection:
            first = TenantBoundPostgresOutboxRepository(
                PostgresOutboxRepository(connection), tenant_id=tenant_a
            )
            claimed_a = first.claim_pending(worker_id="worker-a", limit=1, max_attempts=1, lease_seconds=60)
            assert len(claimed_a) == 1
        with PostgresTenantBoundary(factory).transaction(tenant_a) as connection:
            second = TenantBoundPostgresOutboxRepository(
                PostgresOutboxRepository(connection), tenant_id=tenant_a
            )
            claimed_b = second.claim_pending(worker_id="worker-b", limit=1, max_attempts=2, lease_seconds=60)
            assert len(claimed_b) == 1 and claimed_b[0].id != claimed_a[0].id
            assert len(second.list_events(status="pending")) == 2
            assert second.mark_failed(
                event_id=claimed_b[0].id, worker_id="worker-b", error="synthetic failure", max_attempts=1
            )
            dead = second.list_events(status="dead_letter")
            assert len(dead) == 1 and dead[0].dead_lettered_at is not None
            second.requeue_dead_letter(event_id=dead[0].id)
        with PostgresTenantBoundary(factory).transaction(tenant_a) as connection:
            replay = TenantBoundPostgresOutboxRepository(
                PostgresOutboxRepository(connection), tenant_id=tenant_a
            )
            replayed = replay.claim_pending(worker_id="worker-c", limit=1)
            assert len(replayed) == 1
            replay.mark_published(event_id=replayed[0].id, worker_id="worker-c")
            assert len(replay.list_events(status="published")) == 1
        with PostgresTenantBoundary(factory).transaction(tenant_b) as connection:
            isolated = TenantBoundPostgresOutboxRepository(
                PostgresOutboxRepository(connection), tenant_id=tenant_b
            )
            assert isolated.list_events(status="all") == []
    finally:
        try:
            with admin.transaction():
                admin.execute("DELETE FROM reconforge.tenants WHERE id IN (%s,%s)", (tenant_a, tenant_b))
        except psycopg.Error:
            pass
        admin.close()


@pytest.mark.skipif(
    not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"), reason="requires a live PostgreSQL service"
)
def test_live_postgres_outbox_bounded_multi_worker_delivery_profile() -> None:
    """Drain one synthetic 64-event queue with independent PostgreSQL workers."""

    pytest.importorskip("psycopg")
    dsn = os.environ["RECONFORGE_TEST_POSTGRES_DSN"]
    admin_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN", dsn)
    app_user = os.environ.get("RECONFORGE_TEST_POSTGRES_APP_USER", "")
    if not app_user:
        pytest.skip("requires a non-privileged application role")
    factory = PostgresConnectionFactory(PostgresSettings(dsn=dsn, require_tls=False))
    admin_factory = PostgresConnectionFactory(PostgresSettings(dsn=admin_dsn, require_tls=False))
    tenant_id = "outbox_scale_" + uuid4().hex[:8]
    admin = admin_factory.connect()
    try:
        with admin.transaction():
            install_postgres_rls_schema(admin)
            admin.execute(POSTGRES_MASTER_DATA_SCHEMA_SQL)
            admin.execute(POSTGRES_LEDGER_SCHEMA_SQL)
            admin.execute(POSTGRES_OUTBOX_APPLICATION_SCHEMA_SQL)
            admin.execute(f"GRANT USAGE ON SCHEMA reconforge TO {app_user}")
            admin.execute(f"GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA reconforge TO {app_user}")
            admin.execute("INSERT INTO reconforge.tenants(id,name) VALUES(%s,%s)", (tenant_id, tenant_id))
        result = run_postgres_outbox_scale_profile(
            factory,
            tenant_id,
            id_prefix="PGOUTBOX-" + uuid4().hex[:8],
        )
        verify_postgres_outbox_scale_result(result)
        assert result.published_events == postgres_outbox_scale_profile().events
        assert result.duplicate_publish_attempts == 0
        assert result.pending_events == result.claimed_events == result.dead_events == 0
    finally:
        try:
            with admin.transaction():
                admin.execute("DELETE FROM reconforge.tenants WHERE id=%s", (tenant_id,))
        except Exception:
            pass
        admin.close()
