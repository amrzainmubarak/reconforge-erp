from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from reconforge.application.notifications import (
    NotificationApplicationService,
    NotificationChannel,
    NotificationDeliveryError,
    NotificationEgressPolicy,
    NotificationOutboxPublisher,
    NotificationRequest,
    NotificationRouteRecord,
    NotificationRouteRegistration,
    OutboxPublisherRouter,
)
from reconforge.application.scheduler import ScheduleJobTemplate, SchedulerApplicationService, ScheduleRegistration
from reconforge.domain.scheduling import MisfirePolicy, ScheduleDefinition, ScheduleFrequency
from reconforge.infrastructure.postgres import (
    PostgresConnectionFactory,
    PostgresSettings,
    PostgresTenantBoundary,
)
from reconforge.infrastructure.postgres_notifications import (
    POSTGRES_NOTIFICATION_SCHEMA_SQL,
    PostgresNotificationRepository,
    PostgresNotificationResolver,
    install_postgres_notification_schema,
)
from reconforge.infrastructure.postgres_outbox import PostgresOutboxRepository
from reconforge.infrastructure.postgres_scheduler import PostgresScheduleRepository
from reconforge.workers.outbox import OutboxWorkerSettings
from reconforge.workers.postgres_outbox import PostgresOutboxWorker
from reconforge.workers.postgres_scheduler import PostgresSchedulerWorker, PostgresSchedulerWorkerSettings


def _schedule(tenant_id: str, workspace_id: str, entity_id: str) -> ScheduleRegistration:
    return ScheduleRegistration(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        entity_id=entity_id,
        definition=ScheduleDefinition(
            schedule_id="notification-close",
            version=1,
            timezone="Africa/Cairo",
            local_hour=9,
            local_minute=30,
            frequency=ScheduleFrequency.DAILY,
            start_at=datetime(2026, 1, 1, tzinfo=UTC),
            misfire_policy=MisfirePolicy.CATCH_UP,
            max_catch_up=2,
        ),
        job=ScheduleJobTemplate(
            job_type="notification-reconciliation",
            input_digest="1" * 64,
            config_digest="2" * 64,
            worker_version="worker-v1",
            total_units=10,
            retry_ceiling=3,
        ),
        cursor_at=datetime(2026, 6, 1, tzinfo=UTC),
    )


def _policy() -> NotificationEgressPolicy:
    return NotificationEgressPolicy(
        enabled=True,
        webhook_urls=frozenset({"https://hooks.example.com/reconforge"}),
    )


def _route(tenant_id: str, workspace_id: str, entity_id: str) -> NotificationRouteRegistration:
    return NotificationRouteRegistration(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        entity_id=entity_id,
        route_id="scheduler-webhook",
        version=1,
        channel=NotificationChannel.WEBHOOK,
        destination="https://hooks.example.com/reconforge",
        secret_ref="vault/scheduler-webhook",
    )


def test_postgres_notification_schema_is_forced_rls_append_only_and_outbox_audited() -> None:
    assert POSTGRES_NOTIFICATION_SCHEMA_SQL.count("FORCE ROW LEVEL SECURITY") == 3
    assert "notification routes cannot be deleted" in POSTGRES_NOTIFICATION_SCHEMA_SQL
    assert "notification subscriptions and delivery evidence are append-only" in POSTGRES_NOTIFICATION_SCHEMA_SQL
    assert "notification_outbox_delivery_transition" in POSTGRES_NOTIFICATION_SCHEMA_SQL
    assert "notification.scheduler_dispatch.v1" in POSTGRES_NOTIFICATION_SCHEMA_SQL
    assert "destination_digest" in POSTGRES_NOTIFICATION_SCHEMA_SQL
    assert "secret" not in "notification_delivery_events"


@dataclass
class _FailingTransport:
    attempts: int = 0

    def deliver(self, route: NotificationRouteRecord, request: NotificationRequest) -> None:
        self.attempts += 1
        assert route.registration.destination_digest == request.destination_digest
        raise NotificationDeliveryError("Synthetic transport unavailable.")


@dataclass
class _SuccessfulTransport:
    delivered: list[str]

    def deliver(self, route: NotificationRouteRecord, request: NotificationRequest) -> None:
        assert route.registration.destination_digest == request.destination_digest
        self.delivered.append(request.notification_id)


@pytest.mark.skipif(not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"), reason="requires live PostgreSQL")
def test_live_postgres_scheduler_notifications_are_atomic_scoped_retryable_and_audited() -> None:
    pytest.importorskip("psycopg")
    dsn = os.environ["RECONFORGE_TEST_POSTGRES_DSN"]
    admin_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN", dsn)
    app_user = os.environ.get("RECONFORGE_TEST_POSTGRES_APP_USER", "")
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", app_user):
        pytest.skip("requires a safe non-privileged application role")
    factory = PostgresConnectionFactory(PostgresSettings(dsn=dsn, require_tls=False))
    admin_factory = PostgresConnectionFactory(PostgresSettings(dsn=admin_dsn, require_tls=False))
    tenant = "notifications_live_" + uuid4().hex[:8]
    workspace = "notifications-workspace"
    sibling_workspace = "notifications-sibling"
    entity = "notifications-entity"
    admin = admin_factory.connect()
    try:
        with admin.transaction():
            install_postgres_notification_schema(admin)
            admin.execute(f"GRANT USAGE ON SCHEMA reconforge TO {app_user}")
            admin.execute(
                f"GRANT SELECT,INSERT,UPDATE ON reconforge.notification_routes,"
                f"reconforge.schedule_notification_subscriptions,reconforge.notification_delivery_events,"
                f"reconforge.schedules,reconforge.schedule_dispatches,reconforge.schedule_events,"
                f"reconforge.durable_jobs,reconforge.durable_job_transitions,reconforge.outbox_events "
                f"TO {app_user}"
            )
            admin.execute(
                f"GRANT DELETE ON reconforge.notification_delivery_events TO {app_user}"
            )
            admin.execute("INSERT INTO reconforge.tenants(id,name) VALUES(%s,%s)", (tenant, tenant))
            for workspace_id in (workspace, sibling_workspace):
                admin.execute(
                    "INSERT INTO reconforge.domain_workspaces(tenant_id,id,name) VALUES(%s,%s,%s)",
                    (tenant, workspace_id, workspace_id),
                )

        connection = factory.connect()
        try:
            scheduler = SchedulerApplicationService(PostgresScheduleRepository(connection))
            scheduler.register(_schedule(tenant, workspace, entity), actor_id="scheduler-admin")
            notifications = NotificationApplicationService(
                PostgresNotificationRepository(connection), policy=_policy()
            )
            record, created = notifications.register_route(
                _route(tenant, workspace, entity), actor_id="notification-admin"
            )
            replay, replay_created = notifications.register_route(
                _route(tenant, workspace, entity), actor_id="notification-admin"
            )
            assert created is True and replay_created is False and replay == record
            assert notifications.subscribe_schedule(
                tenant_id=tenant,
                schedule_id="notification-close",
                schedule_version=1,
                route_id="scheduler-webhook",
                route_version=1,
                actor_id="notification-admin",
            ) is True
            assert notifications.subscribe_schedule(
                tenant_id=tenant,
                schedule_id="notification-close",
                schedule_version=1,
                route_id="scheduler-webhook",
                route_version=1,
                actor_id="notification-admin",
            ) is False

            scheduler_worker = PostgresSchedulerWorker(
                factory,
                tenant_supplier=lambda: (tenant,),
                settings=PostgresSchedulerWorkerSettings(
                    worker_id="scheduler-worker", poll_interval_seconds=0
                ),
                clock=lambda: datetime(2026, 6, 2, 12, tzinfo=UTC),
            )
            scheduler_summary = scheduler_worker.run(max_cycles=1)
            assert (
                scheduler_summary.cycles,
                scheduler_summary.tenants_processed,
                scheduler_summary.dispatched,
            ) == (1, 1, 2)
            replay_summary = scheduler_worker.run(max_cycles=1)
            assert (replay_summary.dispatched, replay_summary.replayed) == (0, 0)
            with PostgresTenantBoundary(factory).transaction(
                tenant, workspace_id=workspace
            ) as scoped:
                scoped.execute("SELECT set_config('app.entity_id', %s, true)", (entity,))
                events = scoped.execute(
                    """
                    SELECT event_id,payload FROM reconforge.outbox_events
                    WHERE tenant_id=%s AND event_type='notification.scheduler_dispatch.v1'
                    ORDER BY event_id
                    """,
                    (tenant,),
                ).fetchall()
                assert len(events) == 2
                for event_id, payload in events:
                    assert payload["notification_id"] == event_id
                    serialized = str(payload)
                    assert "https://" not in serialized and "vault/" not in serialized
                    assert "amount" not in serialized and "financial" not in serialized
                statuses = scoped.execute(
                    "SELECT delivery_status,attempt_count FROM reconforge.notification_delivery_events ORDER BY outbox_event_id,transition_sequence"
                ).fetchall()
                assert [(str(row[0]), int(row[1])) for row in statuses] == [
                    ("Pending", 0),
                    ("Pending", 0),
                ]

            failing = _FailingTransport()
            notification_publisher = NotificationOutboxPublisher(
                resolver=PostgresNotificationResolver(factory), transport=failing, policy=_policy()
            )
            default_events: list[str] = []
            failed_worker = PostgresOutboxWorker(
                factory,
                tenant_supplier=lambda: (tenant,),
                publisher=OutboxPublisherRouter(
                    notification_publisher=notification_publisher,
                    default_publisher=lambda event: default_events.append(event.id),
                ),
                settings=OutboxWorkerSettings(
                    worker_id="notification-worker",
                    poll_interval_seconds=0,
                    batch_size=10,
                    max_attempts=2,
                    retry_base_seconds=0,
                ),
            )
            first = failed_worker.process_once()
            second = failed_worker.process_once()
            assert (first.failed, first.dead_lettered, second.failed, second.dead_lettered) == (2, 0, 2, 2)
            assert failing.attempts == 4 and default_events == []

            with PostgresTenantBoundary(factory).transaction(tenant) as tenant_connection:
                outbox = PostgresOutboxRepository(tenant_connection)
                dead = outbox.list_events(tenant_id=tenant, status="dead")
                assert len(dead) == 2
                assert all(event.last_error == "Synthetic transport unavailable." for event in dead)
                replay_event_id = dead[0].id
                outbox.replay_dead(tenant_id=tenant, event_id=replay_event_id)

            delivered: list[str] = []
            successful_worker = PostgresOutboxWorker(
                factory,
                tenant_supplier=lambda: (tenant,),
                publisher=OutboxPublisherRouter(
                    notification_publisher=NotificationOutboxPublisher(
                        resolver=PostgresNotificationResolver(factory),
                        transport=_SuccessfulTransport(delivered),
                        policy=_policy(),
                    ),
                    default_publisher=lambda event: default_events.append(event.id),
                ),
                settings=OutboxWorkerSettings(
                    worker_id="notification-worker-success",
                    poll_interval_seconds=0,
                    batch_size=10,
                    max_attempts=2,
                    retry_base_seconds=0,
                ),
            )
            success = successful_worker.process_once()
            assert (success.published, success.failed) == (1, 0)
            assert delivered == [replay_event_id]

            with PostgresTenantBoundary(factory).transaction(
                tenant, workspace_id=workspace
            ) as scoped:
                scoped.execute("SELECT set_config('app.entity_id', %s, true)", (entity,))
                transitions = scoped.execute(
                    """
                    SELECT delivery_status,attempt_count
                    FROM reconforge.notification_delivery_events
                    WHERE tenant_id=%s AND outbox_event_id=%s
                    ORDER BY transition_sequence
                    """,
                    (tenant, replay_event_id),
                ).fetchall()
                assert [(str(row[0]), int(row[1])) for row in transitions] == [
                    ("Pending", 0),
                    ("Claimed", 1),
                    ("Pending", 1),
                    ("Claimed", 2),
                    ("Dead", 2),
                    ("Pending", 0),
                    ("Claimed", 1),
                    ("Published", 1),
                ]
                with pytest.raises(Exception, match="append-only"):
                    scoped.execute(
                        "DELETE FROM reconforge.notification_delivery_events WHERE tenant_id=%s",
                        (tenant,),
                    )

            with PostgresTenantBoundary(factory).transaction(
                tenant, workspace_id=sibling_workspace
            ) as sibling:
                sibling.execute("SELECT set_config('app.entity_id', %s, true)", ("sibling-entity",))
                assert sibling.execute(
                    "SELECT COUNT(*) FROM reconforge.notification_routes WHERE tenant_id=%s", (tenant,)
                ).fetchone()[0] == 0
                assert sibling.execute(
                    "SELECT COUNT(*) FROM reconforge.notification_delivery_events WHERE tenant_id=%s",
                    (tenant,),
                ).fetchone()[0] == 0
            with pytest.raises(Exception, match="immutable"), PostgresTenantBoundary(factory).transaction(
                tenant, workspace_id=workspace
            ) as scoped:
                scoped.execute("SELECT set_config('app.entity_id', %s, true)", (entity,))
                scoped.execute(
                    "UPDATE reconforge.notification_routes SET destination='https://hooks.example.com/changed' "
                    "WHERE tenant_id=%s AND route_id='scheduler-webhook'",
                    (tenant,),
                )
        finally:
            connection.close()
    finally:
        admin.close()
