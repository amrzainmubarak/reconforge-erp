"""Add allowlisted notification routes and append-only delivery evidence."""

from __future__ import annotations

from alembic import op
from reconforge_migration_sql import load_postgres_schema_sql

POSTGRES_NOTIFICATION_SCHEMA_SQL = load_postgres_schema_sql(
    "reconforge.infrastructure.postgres_notifications", "POSTGRES_NOTIFICATION_SCHEMA_SQL"
)

revision = "0048_postgres_notifications"
down_revision = "0047_postgres_scheduler"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(POSTGRES_NOTIFICATION_SCHEMA_SQL)


def downgrade() -> None:
    op.execute(
        """
        DO $reconforge$
        BEGIN
          IF EXISTS (SELECT 1 FROM reconforge.notification_routes LIMIT 1)
             OR EXISTS (SELECT 1 FROM reconforge.schedule_notification_subscriptions LIMIT 1)
             OR EXISTS (SELECT 1 FROM reconforge.notification_delivery_events LIMIT 1)
             OR EXISTS (
               SELECT 1 FROM reconforge.outbox_events
               WHERE event_type='notification.scheduler_dispatch.v1' LIMIT 1
             )
          THEN
            RAISE EXCEPTION '0048 downgrade refuses non-empty notification evidence; back up and use an approved data migration';
          END IF;
        END $reconforge$;
        """
    )
    op.execute(
        """
        DROP TRIGGER IF EXISTS notification_outbox_delivery_transition ON reconforge.outbox_events;
        DROP FUNCTION IF EXISTS reconforge.record_notification_delivery_transition();
        DROP TRIGGER IF EXISTS notification_delivery_events_immutable ON reconforge.notification_delivery_events;
        DROP TRIGGER IF EXISTS notification_subscriptions_immutable ON reconforge.schedule_notification_subscriptions;
        DROP TRIGGER IF EXISTS notification_routes_guard ON reconforge.notification_routes;
        DROP TABLE IF EXISTS reconforge.notification_delivery_events;
        DROP TABLE IF EXISTS reconforge.schedule_notification_subscriptions;
        DROP TABLE IF EXISTS reconforge.notification_routes;
        DROP FUNCTION IF EXISTS reconforge.reject_notification_evidence_mutation();
        DROP FUNCTION IF EXISTS reconforge.notification_route_guard();
        """
    )
