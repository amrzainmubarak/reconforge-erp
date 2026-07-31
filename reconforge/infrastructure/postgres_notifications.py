"""PostgreSQL notification routes, subscriptions, and delivery evidence."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from reconforge.application.notifications import (
    NotificationChannel,
    NotificationError,
    NotificationRequest,
    NotificationRouteRecord,
    NotificationRouteRegistration,
)
from reconforge.infrastructure.postgres import PostgresTenantBoundary, set_local_tenant_scope, validate_tenant_id


class PostgresNotificationError(RuntimeError):
    """Safe persistence error without route or credential disclosure."""


class PostgresNotificationConflictError(PostgresNotificationError):
    """Raised when immutable route or subscription identity conflicts."""


_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
_ROUTE_COLUMNS = (
    "tenant_id",
    "route_id",
    "route_version",
    "workspace_id",
    "entity_id",
    "channel",
    "destination",
    "destination_digest",
    "secret_ref",
    "registration_digest",
    "enabled",
    "created_by",
    "created_at",
)


def _value(row: Any, name: str, index: int) -> Any:
    return row[name] if isinstance(row, Mapping) else row[index]


def _identifier(value: object, field_name: str) -> str:
    normalized = str(value or "").strip()
    if not _IDENTIFIER.fullmatch(normalized):
        raise NotificationError(f"{field_name} is invalid or exceeds 160 characters.")
    return normalized


def _registration_payload(registration: NotificationRouteRegistration) -> dict[str, object]:
    return {
        "tenant_id": registration.tenant_id,
        "workspace_id": registration.workspace_id,
        "entity_id": registration.entity_id,
        "route_id": registration.route_id,
        "route_version": registration.version,
        "channel": registration.channel.value,
        "destination": registration.destination,
        "destination_digest": registration.destination_digest,
        "secret_ref": registration.secret_ref,
    }


def _digest(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


def _registration_digest(registration: NotificationRouteRegistration) -> str:
    return _digest(_registration_payload(registration))


def _record(row: Any) -> NotificationRouteRecord:
    try:
        values = {name: _value(row, name, index) for index, name in enumerate(_ROUTE_COLUMNS)}
        registration = NotificationRouteRegistration(
            tenant_id=str(values["tenant_id"]),
            workspace_id=str(values["workspace_id"]),
            entity_id=str(values["entity_id"]),
            route_id=str(values["route_id"]),
            version=int(values["route_version"]),
            channel=NotificationChannel(str(values["channel"])),
            destination=str(values["destination"]),
            secret_ref=str(values["secret_ref"]),
        )
        if str(values["destination_digest"]) != registration.destination_digest:
            raise PostgresNotificationError("Stored notification destination binding is invalid.")
        if str(values["registration_digest"]) != _registration_digest(registration):
            raise PostgresNotificationError("Stored notification route digest is invalid.")
        return NotificationRouteRecord(
            registration=registration,
            enabled=bool(values["enabled"]),
            created_by=str(values["created_by"]),
            created_at=values["created_at"],
        )
    except (KeyError, TypeError, ValueError, NotificationError) as exc:
        raise PostgresNotificationError("Stored notification route is invalid.") from exc


@dataclass
class PostgresNotificationRepository:
    """Own versioned routes and immutable schedule subscriptions."""

    connection: Any

    @contextmanager
    def _transaction(
        self,
        tenant_id: str,
        *,
        workspace_id: str = "",
        entity_id: str = "",
    ) -> Iterator[None]:
        tenant = validate_tenant_id(tenant_id)
        try:
            with self.connection.transaction():
                set_local_tenant_scope(self.connection, tenant, workspace_id=workspace_id or None)
                self.connection.execute("SELECT set_config('app.entity_id', %s, true)", (entity_id,))
                yield
        except (PostgresNotificationError, NotificationError):
            raise
        except Exception as exc:
            raise PostgresNotificationError("PostgreSQL notification operation failed.") from exc

    def register(
        self,
        registration: NotificationRouteRegistration,
        *,
        actor_id: str,
    ) -> tuple[NotificationRouteRecord, bool]:
        actor = _identifier(actor_id, "actor_id")
        columns = ",".join(_ROUTE_COLUMNS)
        digest = _registration_digest(registration)
        with self._transaction(
            registration.tenant_id,
            workspace_id=registration.workspace_id,
            entity_id=registration.entity_id,
        ):
            rows = self.connection.execute(
                "SELECT " + columns + " FROM reconforge.notification_routes "  # nosec B608
                "WHERE tenant_id=%s AND route_id=%s ORDER BY route_version FOR UPDATE",
                (registration.tenant_id, registration.route_id),
            ).fetchall()
            for row in rows:
                version = int(_value(row, "route_version", 2))
                if version == registration.version:
                    if str(_value(row, "registration_digest", 9)) != digest:
                        raise PostgresNotificationConflictError(
                            "Notification route version is bound to different configuration."
                        )
                    return _record(row), False
            if rows and registration.version <= max(int(_value(row, "route_version", 2)) for row in rows):
                raise PostgresNotificationConflictError("Notification route versions must increase monotonically.")
            self.connection.execute(
                "UPDATE reconforge.notification_routes SET enabled=FALSE "
                "WHERE tenant_id=%s AND route_id=%s AND enabled=TRUE",
                (registration.tenant_id, registration.route_id),
            )
            inserted = self.connection.execute(
                """
                INSERT INTO reconforge.notification_routes
                  (tenant_id,route_id,route_version,workspace_id,entity_id,channel,destination,
                   destination_digest,secret_ref,registration_digest,created_by)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                RETURNING tenant_id,route_id,route_version,workspace_id,entity_id,channel,destination,
                          destination_digest,secret_ref,registration_digest,enabled,created_by,created_at
                """,
                (
                    registration.tenant_id,
                    registration.route_id,
                    registration.version,
                    registration.workspace_id,
                    registration.entity_id,
                    registration.channel.value,
                    registration.destination,
                    registration.destination_digest,
                    registration.secret_ref,
                    digest,
                    actor,
                ),
            ).fetchone()
            if inserted is None:
                raise PostgresNotificationConflictError("Notification route registration did not persist.")
            return _record(inserted), True

    def subscribe_schedule(
        self,
        *,
        tenant_id: str,
        schedule_id: str,
        schedule_version: int,
        route_id: str,
        route_version: int,
        actor_id: str,
    ) -> bool:
        tenant = validate_tenant_id(tenant_id)
        schedule = _identifier(schedule_id, "schedule_id")
        route = _identifier(route_id, "route_id")
        actor = _identifier(actor_id, "actor_id")
        with self._transaction(tenant):
            route_scope = self.connection.execute(
                """
                SELECT workspace_id,entity_id
                FROM reconforge.notification_routes
                WHERE tenant_id=%s AND route_id=%s AND route_version=%s AND enabled=TRUE
                """,
                (tenant, route, int(route_version)),
            ).fetchone()
            if route_scope is None:
                raise PostgresNotificationConflictError("Active notification route was not found.")
            workspace_id, entity_id = str(route_scope[0]), str(route_scope[1])
            set_local_tenant_scope(self.connection, tenant, workspace_id=workspace_id)
            self.connection.execute("SELECT set_config('app.entity_id', %s, true)", (entity_id,))
            schedule_scope = self.connection.execute(
                """
                SELECT workspace_id,entity_id
                FROM reconforge.schedules
                WHERE tenant_id=%s AND schedule_id=%s AND schedule_version=%s
                """,
                (tenant, schedule, int(schedule_version)),
            ).fetchone()
            if schedule_scope is None or (str(schedule_scope[0]), str(schedule_scope[1])) != (
                workspace_id,
                entity_id,
            ):
                raise PostgresNotificationConflictError(
                    "Schedule and notification route do not share the same execution scope."
                )
            inserted = self.connection.execute(
                """
                INSERT INTO reconforge.schedule_notification_subscriptions
                  (tenant_id,schedule_id,schedule_version,route_id,route_version,created_by)
                VALUES (%s,%s,%s,%s,%s,%s)
                ON CONFLICT (tenant_id,schedule_id,schedule_version,route_id,route_version) DO NOTHING
                RETURNING route_id
                """,
                (tenant, schedule, int(schedule_version), route, int(route_version), actor),
            ).fetchone()
            return inserted is not None

    def resolve(self, request: NotificationRequest) -> NotificationRouteRecord:
        columns = ",".join(_ROUTE_COLUMNS)
        with self._transaction(
            request.tenant_id,
            workspace_id=request.workspace_id,
            entity_id=request.entity_id,
        ):
            row = self.connection.execute(
                "SELECT " + columns + " FROM reconforge.notification_routes "  # nosec B608
                "WHERE tenant_id=%s AND route_id=%s AND route_version=%s AND enabled=TRUE",
                (request.tenant_id, request.route_id, request.route_version),
            ).fetchone()
            if row is None:
                raise PostgresNotificationError("Active notification route was not found in the requested scope.")
            record = _record(row)
            registration = record.registration
            if (
                registration.workspace_id != request.workspace_id
                or registration.entity_id != request.entity_id
                or registration.destination_digest != request.destination_digest
            ):
                raise PostgresNotificationError("Notification route scope or destination binding is invalid.")
            return record


@dataclass(frozen=True)
class PostgresNotificationResolver:
    """Resolve each delivery through one fresh workspace-scoped connection."""

    connection_factory: Any

    def resolve(self, request: NotificationRequest) -> NotificationRouteRecord:
        with PostgresTenantBoundary(self.connection_factory).transaction(
            request.tenant_id,
            workspace_id=request.workspace_id,
        ) as connection:
            connection.execute("SELECT set_config('app.entity_id', %s, true)", (request.entity_id,))
            columns = ",".join(_ROUTE_COLUMNS)
            row = connection.execute(
                "SELECT " + columns + " FROM reconforge.notification_routes "  # nosec B608
                "WHERE tenant_id=%s AND route_id=%s AND route_version=%s AND enabled=TRUE",
                (request.tenant_id, request.route_id, request.route_version),
            ).fetchone()
            if row is None:
                raise PostgresNotificationError("Active notification route was not found in the requested scope.")
            record = _record(row)
            registration = record.registration
            if (
                registration.workspace_id != request.workspace_id
                or registration.entity_id != request.entity_id
                or registration.destination_digest != request.destination_digest
            ):
                raise PostgresNotificationError("Notification route scope or destination binding is invalid.")
            return record


POSTGRES_NOTIFICATION_SCHEMA_SQL = r"""
CREATE TABLE IF NOT EXISTS reconforge.notification_routes (
  tenant_id TEXT NOT NULL REFERENCES reconforge.tenants(id) ON DELETE CASCADE,
  route_id TEXT NOT NULL CHECK (route_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$'),
  route_version INTEGER NOT NULL CHECK (route_version > 0),
  workspace_id TEXT NOT NULL,
  entity_id TEXT NOT NULL DEFAULT '',
  channel TEXT NOT NULL CHECK (channel IN ('webhook','email')),
  destination TEXT NOT NULL CHECK (destination <> '' AND length(destination) <= 2048),
  destination_digest TEXT NOT NULL CHECK (destination_digest ~ '^[0-9a-f]{64}$'),
  secret_ref TEXT NOT NULL DEFAULT ''
    CHECK (length(secret_ref) <= 256 AND secret_ref ~ '^[A-Za-z0-9._:/-]*$'),
  registration_digest TEXT NOT NULL CHECK (registration_digest ~ '^[0-9a-f]{64}$'),
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  created_by TEXT NOT NULL CHECK (created_by ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$'),
  created_at TIMESTAMPTZ NOT NULL DEFAULT date_trunc('second',now()),
  PRIMARY KEY (tenant_id,route_id,route_version),
  FOREIGN KEY (tenant_id,workspace_id)
    REFERENCES reconforge.domain_workspaces(tenant_id,id) ON DELETE RESTRICT,
  CHECK (channel <> 'webhook' OR secret_ref <> '')
);
CREATE UNIQUE INDEX IF NOT EXISTS notification_routes_one_active_version
 ON reconforge.notification_routes(tenant_id,route_id) WHERE enabled;

CREATE TABLE IF NOT EXISTS reconforge.schedule_notification_subscriptions (
  tenant_id TEXT NOT NULL,
  schedule_id TEXT NOT NULL,
  schedule_version INTEGER NOT NULL,
  route_id TEXT NOT NULL,
  route_version INTEGER NOT NULL,
  created_by TEXT NOT NULL CHECK (created_by ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$'),
  created_at TIMESTAMPTZ NOT NULL DEFAULT date_trunc('second',now()),
  PRIMARY KEY (tenant_id,schedule_id,schedule_version,route_id,route_version),
  FOREIGN KEY (tenant_id,schedule_id,schedule_version)
    REFERENCES reconforge.schedules(tenant_id,schedule_id,schedule_version) ON DELETE RESTRICT,
  FOREIGN KEY (tenant_id,route_id,route_version)
    REFERENCES reconforge.notification_routes(tenant_id,route_id,route_version) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS reconforge.notification_delivery_events (
  tenant_id TEXT NOT NULL,
  outbox_event_id TEXT NOT NULL,
  transition_sequence INTEGER NOT NULL CHECK (transition_sequence > 0),
  route_id TEXT NOT NULL,
  route_version INTEGER NOT NULL,
  destination_digest TEXT NOT NULL CHECK (destination_digest ~ '^[0-9a-f]{64}$'),
  delivery_status TEXT NOT NULL CHECK (delivery_status IN ('Pending','Claimed','Published','Dead')),
  attempt_count INTEGER NOT NULL CHECK (attempt_count >= 0),
  occurred_at TIMESTAMPTZ NOT NULL DEFAULT date_trunc('second',clock_timestamp()),
  PRIMARY KEY (tenant_id,outbox_event_id,transition_sequence),
  FOREIGN KEY (tenant_id,outbox_event_id)
    REFERENCES reconforge.outbox_events(tenant_id,event_id) ON DELETE RESTRICT,
  FOREIGN KEY (tenant_id,route_id,route_version)
    REFERENCES reconforge.notification_routes(tenant_id,route_id,route_version) ON DELETE RESTRICT
);

CREATE OR REPLACE FUNCTION reconforge.notification_route_guard() RETURNS trigger LANGUAGE plpgsql AS $reconforge$
BEGIN
  IF TG_OP='DELETE' THEN RAISE EXCEPTION 'notification routes cannot be deleted'; END IF;
  IF (NEW.tenant_id,NEW.route_id,NEW.route_version,NEW.workspace_id,NEW.entity_id,NEW.channel,
      NEW.destination,NEW.destination_digest,NEW.secret_ref,NEW.registration_digest,NEW.created_by,NEW.created_at)
     IS DISTINCT FROM
     (OLD.tenant_id,OLD.route_id,OLD.route_version,OLD.workspace_id,OLD.entity_id,OLD.channel,
      OLD.destination,OLD.destination_digest,OLD.secret_ref,OLD.registration_digest,OLD.created_by,OLD.created_at)
  THEN RAISE EXCEPTION 'notification route versions are immutable'; END IF;
  IF OLD.enabled=FALSE OR NEW.enabled=TRUE THEN
    RAISE EXCEPTION 'notification routes may only transition from enabled to disabled';
  END IF;
  RETURN NEW;
END $reconforge$;
DROP TRIGGER IF EXISTS notification_routes_guard ON reconforge.notification_routes;
CREATE TRIGGER notification_routes_guard BEFORE UPDATE OR DELETE ON reconforge.notification_routes
 FOR EACH ROW EXECUTE FUNCTION reconforge.notification_route_guard();

CREATE OR REPLACE FUNCTION reconforge.reject_notification_evidence_mutation() RETURNS trigger LANGUAGE plpgsql AS $reconforge$
BEGIN RAISE EXCEPTION 'notification subscriptions and delivery evidence are append-only'; END $reconforge$;
DROP TRIGGER IF EXISTS notification_subscriptions_immutable ON reconforge.schedule_notification_subscriptions;
CREATE TRIGGER notification_subscriptions_immutable
 BEFORE UPDATE OR DELETE ON reconforge.schedule_notification_subscriptions
 FOR EACH ROW EXECUTE FUNCTION reconforge.reject_notification_evidence_mutation();
DROP TRIGGER IF EXISTS notification_delivery_events_immutable ON reconforge.notification_delivery_events;
CREATE TRIGGER notification_delivery_events_immutable
 BEFORE UPDATE OR DELETE ON reconforge.notification_delivery_events
 FOR EACH ROW EXECUTE FUNCTION reconforge.reject_notification_evidence_mutation();

CREATE OR REPLACE FUNCTION reconforge.record_notification_delivery_transition() RETURNS trigger LANGUAGE plpgsql AS $reconforge$
DECLARE next_sequence INTEGER;
BEGIN
  IF NEW.event_type <> 'notification.scheduler_dispatch.v1' THEN RETURN NEW; END IF;
  IF TG_OP='UPDATE' AND NEW.status IS NOT DISTINCT FROM OLD.status
    AND NEW.attempt_count IS NOT DISTINCT FROM OLD.attempt_count THEN RETURN NEW; END IF;
  SELECT COALESCE(MAX(transition_sequence),0)+1 INTO next_sequence
  FROM reconforge.notification_delivery_events
  WHERE tenant_id=NEW.tenant_id AND outbox_event_id=NEW.event_id;
  INSERT INTO reconforge.notification_delivery_events
    (tenant_id,outbox_event_id,transition_sequence,route_id,route_version,destination_digest,
     delivery_status,attempt_count)
  VALUES (
    NEW.tenant_id,NEW.event_id,next_sequence,
    NEW.payload->>'route_id',(NEW.payload->>'route_version')::INTEGER,
    NEW.payload->>'destination_digest',NEW.status,NEW.attempt_count
  );
  RETURN NEW;
END $reconforge$;
DROP TRIGGER IF EXISTS notification_outbox_delivery_transition ON reconforge.outbox_events;
CREATE TRIGGER notification_outbox_delivery_transition
 AFTER INSERT OR UPDATE ON reconforge.outbox_events
 FOR EACH ROW EXECUTE FUNCTION reconforge.record_notification_delivery_transition();

ALTER TABLE reconforge.notification_routes ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.notification_routes FORCE ROW LEVEL SECURITY;
ALTER TABLE reconforge.schedule_notification_subscriptions ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.schedule_notification_subscriptions FORCE ROW LEVEL SECURITY;
ALTER TABLE reconforge.notification_delivery_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.notification_delivery_events FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_scope ON reconforge.notification_routes;
CREATE POLICY tenant_scope ON reconforge.notification_routes
 USING (tenant_id=current_setting('app.tenant_id',true)
   AND (NULLIF(current_setting('app.workspace_id',true),'') IS NULL
        OR workspace_id=current_setting('app.workspace_id',true))
   AND (NULLIF(current_setting('app.entity_id',true),'') IS NULL
        OR entity_id=current_setting('app.entity_id',true)))
 WITH CHECK (tenant_id=current_setting('app.tenant_id',true)
   AND (NULLIF(current_setting('app.workspace_id',true),'') IS NULL
        OR workspace_id=current_setting('app.workspace_id',true))
   AND (NULLIF(current_setting('app.entity_id',true),'') IS NULL
        OR entity_id=current_setting('app.entity_id',true)));

DO $reconforge$
DECLARE table_name TEXT;
BEGIN
  FOREACH table_name IN ARRAY ARRAY['schedule_notification_subscriptions','notification_delivery_events'] LOOP
    EXECUTE format('DROP POLICY IF EXISTS tenant_scope ON reconforge.%I',table_name);
    EXECUTE format(
      'CREATE POLICY tenant_scope ON reconforge.%1$I '
      'USING (tenant_id=current_setting(''app.tenant_id'',true) AND EXISTS ('
      'SELECT 1 FROM reconforge.notification_routes parent WHERE parent.tenant_id=%1$I.tenant_id '
      'AND parent.route_id=%1$I.route_id AND parent.route_version=%1$I.route_version)) '
      'WITH CHECK (tenant_id=current_setting(''app.tenant_id'',true) AND EXISTS ('
      'SELECT 1 FROM reconforge.notification_routes parent WHERE parent.tenant_id=%1$I.tenant_id '
      'AND parent.route_id=%1$I.route_id AND parent.route_version=%1$I.route_version))',
      table_name
    );
  END LOOP;
END $reconforge$;
"""


def install_postgres_notification_schema(connection: Any) -> None:
    connection.execute(POSTGRES_NOTIFICATION_SCHEMA_SQL)


__all__ = [
    "POSTGRES_NOTIFICATION_SCHEMA_SQL",
    "PostgresNotificationConflictError",
    "PostgresNotificationError",
    "PostgresNotificationRepository",
    "PostgresNotificationResolver",
    "install_postgres_notification_schema",
]
