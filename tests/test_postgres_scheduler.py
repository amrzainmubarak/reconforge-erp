from __future__ import annotations

import os
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from reconforge.application.scheduler import (
    ScheduleJobTemplate,
    SchedulerApplicationService,
    ScheduleRegistration,
    SchedulerError,
)
from reconforge.domain.jobs import DurableJob
from reconforge.domain.scheduling import MisfirePolicy, ScheduleDefinition, ScheduleFrequency
from reconforge.infrastructure.postgres import PostgresConnectionFactory, PostgresSettings, set_local_tenant_scope
from reconforge.infrastructure.postgres_jobs import PostgresDurableJobRepository
from reconforge.infrastructure.postgres_scheduler import (
    POSTGRES_SCHEDULER_SCHEMA_SQL,
    PostgresSchedulerConflictError,
    PostgresScheduleRepository,
    install_postgres_scheduler_schema,
)


def _registration(
    tenant_id: str = "tenant-a",
    workspace_id: str = "workspace-a",
    *,
    version: int = 1,
    entity_id: str = "entity-a",
    cursor_at: datetime = datetime(2026, 6, 1, tzinfo=UTC),
) -> ScheduleRegistration:
    return ScheduleRegistration(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        entity_id=entity_id,
        definition=ScheduleDefinition(
            schedule_id="daily-close",
            version=version,
            timezone="Africa/Cairo",
            local_hour=9,
            local_minute=30,
            frequency=ScheduleFrequency.DAILY,
            start_at=datetime(2026, 1, 1, tzinfo=UTC),
            misfire_policy=MisfirePolicy.CATCH_UP,
            max_catch_up=2,
        ),
        job=ScheduleJobTemplate(
            job_type="daily-reconciliation",
            input_digest="1" * 64,
            config_digest="2" * 64,
            worker_version="worker-v1",
            total_units=10,
            retry_ceiling=3,
        ),
        cursor_at=cursor_at,
    )


def test_scheduler_application_contract_validates_bounds_and_preserves_inclusive_start() -> None:
    at_start = _registration(cursor_at=datetime(2025, 12, 31, 23, 59, 59, tzinfo=UTC))
    assert at_start.cursor_at == datetime(2025, 12, 31, 23, 59, 59, tzinfo=UTC)
    with pytest.raises(SchedulerError, match="review boundary"):
        _registration(cursor_at=datetime(2020, 1, 1, tzinfo=UTC))
    with pytest.raises(SchedulerError, match="total_units"):
        replace(at_start.job, total_units=0)


def test_postgres_scheduler_schema_has_versioning_rls_append_only_and_job_fk() -> None:
    assert POSTGRES_SCHEDULER_SCHEMA_SQL.count("FORCE ROW LEVEL SECURITY") == 3
    assert "schedules_one_active_version" in POSTGRES_SCHEDULER_SCHEMA_SQL
    assert "schedule cursor cannot move backward" in POSTGRES_SCHEDULER_SCHEMA_SQL
    assert "schedule dispatch and audit evidence are append-only" in POSTGRES_SCHEDULER_SCHEMA_SQL
    assert "REFERENCES reconforge.durable_jobs(tenant_id,id)" in POSTGRES_SCHEDULER_SCHEMA_SQL
    assert any(
        isinstance(value, str) and "FOR UPDATE SKIP LOCKED" in value
        for value in PostgresScheduleRepository.process_due.__code__.co_consts
    )


@pytest.mark.skipif(not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"), reason="requires live PostgreSQL")
def test_live_postgres_scheduler_is_atomic_idempotent_coordinated_and_scoped() -> None:
    pytest.importorskip("psycopg")
    dsn = os.environ["RECONFORGE_TEST_POSTGRES_DSN"]
    admin_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN", dsn)
    app_user = os.environ.get("RECONFORGE_TEST_POSTGRES_APP_USER", "")
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", app_user):
        pytest.skip("requires a safe non-privileged application role")
    factory = PostgresConnectionFactory(PostgresSettings(dsn=dsn, require_tls=False))
    admin_factory = PostgresConnectionFactory(PostgresSettings(dsn=admin_dsn, require_tls=False))
    tenant_a = "scheduler_live_a_" + uuid4().hex[:8]
    tenant_b = "scheduler_live_b_" + uuid4().hex[:8]
    workspace_a = "schedule-workspace-a"
    workspace_a_sibling = "schedule-workspace-sibling"
    workspace_b = "schedule-workspace-b"
    admin = admin_factory.connect()
    try:
        with admin.transaction():
            install_postgres_scheduler_schema(admin)
            admin.execute(f"GRANT USAGE ON SCHEMA reconforge TO {app_user}")
            admin.execute(
                f"GRANT SELECT,INSERT,UPDATE,DELETE ON reconforge.schedules,reconforge.schedule_dispatches,"
                f"reconforge.schedule_events,reconforge.durable_jobs,reconforge.durable_job_transitions TO {app_user}"
            )
            for tenant, workspace in ((tenant_a, workspace_a), (tenant_b, workspace_b)):
                admin.execute("INSERT INTO reconforge.tenants(id,name) VALUES(%s,%s)", (tenant, tenant))
                admin.execute(
                    "INSERT INTO reconforge.domain_workspaces(tenant_id,id,name) VALUES(%s,%s,%s)",
                    (tenant, workspace, workspace),
                )
            admin.execute(
                "INSERT INTO reconforge.domain_workspaces(tenant_id,id,name) VALUES(%s,%s,%s)",
                (tenant_a, workspace_a_sibling, workspace_a_sibling),
            )

        connection = factory.connect()
        try:
            service = SchedulerApplicationService(PostgresScheduleRepository(connection))
            registration = _registration(tenant_a, workspace_a)
            created, is_new = service.register(registration, actor_id="scheduler-admin")
            replayed, replay_is_new = service.register(registration, actor_id="scheduler-admin")
            assert is_new is True and replay_is_new is False and replayed == created
            with pytest.raises(PostgresSchedulerConflictError):
                service.register(
                    replace(registration, job=replace(registration.job, total_units=11)),
                    actor_id="scheduler-admin",
                )
            assert service.get(tenant_id=tenant_b, schedule_id="daily-close") is None

            def process(worker_id: str) -> tuple[int, int]:
                concurrent = factory.connect()
                try:
                    result = SchedulerApplicationService(PostgresScheduleRepository(concurrent)).process_due(
                        tenant_id=tenant_a,
                        worker_id=worker_id,
                        now=datetime(2026, 6, 2, 12, tzinfo=UTC),
                    )
                    return result.schedules_claimed, result.dispatched
                finally:
                    concurrent.close()

            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(process, ("scheduler-worker-a", "scheduler-worker-b")))
            assert sum(claimed for claimed, _ in results) == 1
            assert sum(count for _, count in results) == 2
            dispatches = service.list_dispatches(tenant_id=tenant_a, schedule_id="daily-close")
            assert len(dispatches) == 2
            assert len({item.dispatch_key for item in dispatches}) == 2
            after_dispatch, after_dispatch_is_new = service.register(registration, actor_id="scheduler-admin")
            assert after_dispatch_is_new is False
            assert after_dispatch.registration.cursor_at == datetime(2026, 6, 2, 12, tzinfo=UTC)
            with connection.transaction():
                set_local_tenant_scope(
                    connection,
                    tenant_a,
                    workspace_id=workspace_a,
                )
                connection.execute("SELECT set_config('app.entity_id', %s, true)", ("entity-a",))
                assert connection.execute(
                    "SELECT COUNT(*) FROM reconforge.durable_jobs WHERE tenant_id=%s", (tenant_a,)
                ).fetchone()[0] == 2
                assert connection.execute(
                    "SELECT COUNT(*) FROM reconforge.schedule_events WHERE tenant_id=%s", (tenant_a,)
                ).fetchone()[0] == 2
            with pytest.raises(Exception, match="append-only"), connection.transaction():
                set_local_tenant_scope(
                    connection,
                    tenant_a,
                    workspace_id=workspace_a,
                )
                connection.execute("SELECT set_config('app.entity_id', %s, true)", ("entity-a",))
                connection.execute(
                    "DELETE FROM reconforge.schedule_dispatches WHERE tenant_id=%s", (tenant_a,)
                )

            version_two = replace(
                registration,
                definition=replace(registration.definition, version=2),
                cursor_at=datetime(2026, 6, 2, 12, tzinfo=UTC),
            )
            current, current_is_new = service.register(version_two, actor_id="scheduler-admin")
            assert current_is_new is True and current.registration.definition.version == 2
            with connection.transaction():
                set_local_tenant_scope(
                    connection,
                    tenant_a,
                    workspace_id=workspace_a,
                )
                connection.execute("SELECT set_config('app.entity_id', %s, true)", ("entity-a",))
                enabled_rows = connection.execute(
                    "SELECT enabled FROM reconforge.schedules WHERE tenant_id=%s ORDER BY schedule_version",
                    (tenant_a,),
                ).fetchall()
                assert [bool(row[0]) for row in enabled_rows] == [False, True]
            sibling = replace(
                _registration(tenant_a, workspace_a_sibling, entity_id="entity-b"),
                definition=replace(registration.definition, schedule_id="sibling-close"),
            )
            service.register(sibling, actor_id="scheduler-admin")
            with connection.transaction():
                set_local_tenant_scope(
                    connection,
                    tenant_a,
                    workspace_id=workspace_a,
                )
                connection.execute("SELECT set_config('app.entity_id', %s, true)", ("entity-a",))
                visible_schedules = connection.execute(
                    "SELECT DISTINCT schedule_id FROM reconforge.schedules WHERE tenant_id=%s ORDER BY schedule_id",
                    (tenant_a,),
                ).fetchall()
                assert [str(row[0]) for row in visible_schedules] == ["daily-close"]
                assert connection.execute(
                    "SELECT COUNT(*) FROM reconforge.schedule_dispatches WHERE tenant_id=%s", (tenant_a,)
                ).fetchone()[0] == 2
        finally:
            connection.close()

        rollback_connection = factory.connect()
        try:
            rollback_service = SchedulerApplicationService(PostgresScheduleRepository(rollback_connection))
            rollback_registration = replace(
                _registration(tenant_a, workspace_a, version=3),
                definition=replace(_registration().definition, schedule_id="rollback-proof", version=3),
            )
            rollback_service.register(rollback_registration, actor_id="scheduler-admin")
            occurrence_key = rollback_registration.definition
            from reconforge.domain.scheduling import evaluate_schedule

            expected = evaluate_schedule(
                occurrence_key,
                last_evaluated_at=rollback_registration.cursor_at,
                now=datetime(2026, 6, 2, 12, tzinfo=UTC),
            ).dispatch[0]
            conflict = DurableJob.queued(
                job_id="scheduled-job-" + expected.dispatch_key[:48],
                idempotency_scope=rollback_registration.job.job_type,
                idempotency_key=expected.dispatch_key,
                tenant_id=tenant_a,
                workspace_id=workspace_a,
                entity_id="entity-a",
                input_digest="9" * 64,
                config_digest="8" * 64,
                worker_version="worker-v1",
                total_units=99,
                retry_ceiling=3,
                created_at="2026-06-02T12:00:00Z",
            )
            PostgresDurableJobRepository(rollback_connection).create_or_get(conflict, actor_id="preexisting")
            before = rollback_service.get(tenant_id=tenant_a, schedule_id="rollback-proof")
            with pytest.raises(PostgresSchedulerConflictError):
                rollback_service.process_due(
                    tenant_id=tenant_a,
                    worker_id="scheduler-worker",
                    now=datetime(2026, 6, 2, 12, tzinfo=UTC),
                )
            after = rollback_service.get(tenant_id=tenant_a, schedule_id="rollback-proof")
            assert before is not None and after is not None
            assert after.registration.cursor_at == before.registration.cursor_at
            assert rollback_service.list_dispatches(tenant_id=tenant_a, schedule_id="rollback-proof") == []
        finally:
            rollback_connection.close()
    finally:
        admin.close()
