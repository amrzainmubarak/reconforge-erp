"""Tenant-RLS PostgreSQL persistence for governed write-back intents.

The adapter stores only the digest-bound intent and its immutable lifecycle
versions. It never stores provider payloads or secrets and never performs
network I/O.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from reconforge.connectors.writeback import (
    WritebackError,
    WritebackIntent,
    WritebackStatus,
    validate_writeback_transition,
)
from reconforge.infrastructure.postgres import set_local_tenant_scope, validate_tenant_id, validate_workspace_id


class PostgresWritebackPersistenceError(RuntimeError):
    """Safe persistence failure without payload or secret disclosure."""


_POSTGRES_WRITEBACK_TABLE_SQL = r"""
CREATE TABLE IF NOT EXISTS reconforge.connector_writeback_intents (
    tenant_id TEXT NOT NULL,
    intent_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    version INTEGER NOT NULL CHECK (version > 0),
    status TEXT NOT NULL CHECK (status IN (
        'proposed', 'approved', 'dispatched', 'acknowledged',
        'compensation_requested', 'compensated', 'rejected', 'failed'
    )),
    intent_digest TEXT NOT NULL CHECK (intent_digest ~ '^[a-f0-9]{64}$'),
    intent_json JSONB NOT NULL CHECK (jsonb_typeof(intent_json) = 'object'),
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, intent_id, version),
    UNIQUE (tenant_id, workspace_id, intent_id, intent_digest),
    FOREIGN KEY (tenant_id) REFERENCES reconforge.tenants(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS connector_writeback_intents_scope_idx
    ON reconforge.connector_writeback_intents(tenant_id, workspace_id, intent_id, version DESC);
ALTER TABLE reconforge.connector_writeback_intents ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.connector_writeback_intents FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_workspace_scope ON reconforge.connector_writeback_intents;
CREATE POLICY tenant_workspace_scope ON reconforge.connector_writeback_intents
    USING (
        tenant_id = current_setting('app.tenant_id', true)
        AND (
            NULLIF(current_setting('app.workspace_id', true), '') IS NULL
            OR workspace_id = current_setting('app.workspace_id', true)
        )
    )
    WITH CHECK (
        tenant_id = current_setting('app.tenant_id', true)
        AND workspace_id = current_setting('app.workspace_id', true)
    );
"""

POSTGRES_WRITEBACK_PROPOSAL_IDENTITY_AUDIT_SQL = r"""
DO $reconforge$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM reconforge.connector_writeback_intents AS current
        LEFT JOIN reconforge.connector_writeback_intents AS previous
          ON previous.tenant_id = current.tenant_id
         AND previous.workspace_id = current.workspace_id
         AND previous.intent_id = current.intent_id
         AND previous.version = current.version - 1
        WHERE NOT (current.intent_json ?& ARRAY[
                  'schema_version', 'intent_id', 'tenant_id', 'workspace_id',
                  'connector_id', 'operation', 'payload_digest', 'idempotency_key',
                  'requested_by', 'requested_at', 'feature_enabled', 'status'
              ])
           OR jsonb_typeof(current.intent_json->'schema_version') IS DISTINCT FROM 'string'
           OR jsonb_typeof(current.intent_json->'intent_id') IS DISTINCT FROM 'string'
           OR jsonb_typeof(current.intent_json->'tenant_id') IS DISTINCT FROM 'string'
           OR jsonb_typeof(current.intent_json->'workspace_id') IS DISTINCT FROM 'string'
           OR jsonb_typeof(current.intent_json->'connector_id') IS DISTINCT FROM 'string'
           OR jsonb_typeof(current.intent_json->'operation') IS DISTINCT FROM 'string'
           OR jsonb_typeof(current.intent_json->'payload_digest') IS DISTINCT FROM 'string'
           OR jsonb_typeof(current.intent_json->'idempotency_key') IS DISTINCT FROM 'string'
           OR jsonb_typeof(current.intent_json->'requested_by') IS DISTINCT FROM 'string'
           OR jsonb_typeof(current.intent_json->'requested_at') IS DISTINCT FROM 'string'
           OR jsonb_typeof(current.intent_json->'feature_enabled') IS DISTINCT FROM 'boolean'
           OR jsonb_typeof(current.intent_json->'status') IS DISTINCT FROM 'string'
           OR (current.intent_json->>'intent_id') IS DISTINCT FROM current.intent_id
           OR (current.intent_json->>'tenant_id') IS DISTINCT FROM current.tenant_id
           OR (current.intent_json->>'workspace_id') IS DISTINCT FROM current.workspace_id
           OR (current.intent_json->>'status') IS DISTINCT FROM current.status
           OR (current.version = 1 AND current.status <> 'proposed')
           OR (current.version > 1 AND previous.version IS NULL)
           OR (
              current.version > 1
              AND (
                  (previous.intent_json->'schema_version') IS DISTINCT FROM (current.intent_json->'schema_version')
                  OR (previous.intent_json->'connector_id') IS DISTINCT FROM (current.intent_json->'connector_id')
                  OR (previous.intent_json->'operation') IS DISTINCT FROM (current.intent_json->'operation')
                  OR (previous.intent_json->'payload_digest') IS DISTINCT FROM (current.intent_json->'payload_digest')
                  OR (previous.intent_json->'idempotency_key') IS DISTINCT FROM (current.intent_json->'idempotency_key')
                  OR (previous.intent_json->'requested_by') IS DISTINCT FROM (current.intent_json->'requested_by')
                  OR (previous.intent_json->'requested_at') IS DISTINCT FROM (current.intent_json->'requested_at')
                  OR (previous.intent_json->'feature_enabled') IS DISTINCT FROM (current.intent_json->'feature_enabled')
              )
           )
           OR (
              current.version > 1
              AND NOT (
                  (previous.status = 'proposed' AND current.status IN ('approved', 'rejected'))
                  OR (previous.status = 'approved' AND current.status IN ('dispatched', 'rejected'))
                  OR (previous.status = 'dispatched' AND current.status IN ('acknowledged', 'compensation_requested', 'failed'))
                  OR (previous.status = 'acknowledged' AND current.status = 'compensation_requested')
                  OR (previous.status = 'compensation_requested' AND current.status IN ('compensated', 'failed'))
              )
           )
    ) THEN
        RAISE EXCEPTION 'existing connector write-back history violates immutable proposal identity or lifecycle';
    END IF;
END
$reconforge$;
"""

POSTGRES_WRITEBACK_PROPOSAL_IDENTITY_SQL = r"""
CREATE OR REPLACE FUNCTION reconforge.guard_connector_writeback_intent()
RETURNS TRIGGER LANGUAGE plpgsql AS $reconforge$
DECLARE
    previous_row RECORD;
    immutable_key TEXT;
BEGIN
    IF TG_OP = 'UPDATE' THEN
        RAISE EXCEPTION 'connector write-back intents are immutable' USING ERRCODE='check_violation';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'connector write-back intents cannot be deleted' USING ERRCODE='check_violation';
    END IF;
    IF NOT (NEW.intent_json ?& ARRAY[
              'schema_version', 'intent_id', 'tenant_id', 'workspace_id',
              'connector_id', 'operation', 'payload_digest', 'idempotency_key',
              'requested_by', 'requested_at', 'feature_enabled', 'status'
           ])
       OR jsonb_typeof(NEW.intent_json->'schema_version') IS DISTINCT FROM 'string'
       OR jsonb_typeof(NEW.intent_json->'intent_id') IS DISTINCT FROM 'string'
       OR jsonb_typeof(NEW.intent_json->'tenant_id') IS DISTINCT FROM 'string'
       OR jsonb_typeof(NEW.intent_json->'workspace_id') IS DISTINCT FROM 'string'
       OR jsonb_typeof(NEW.intent_json->'connector_id') IS DISTINCT FROM 'string'
       OR jsonb_typeof(NEW.intent_json->'operation') IS DISTINCT FROM 'string'
       OR jsonb_typeof(NEW.intent_json->'payload_digest') IS DISTINCT FROM 'string'
       OR jsonb_typeof(NEW.intent_json->'idempotency_key') IS DISTINCT FROM 'string'
       OR jsonb_typeof(NEW.intent_json->'requested_by') IS DISTINCT FROM 'string'
       OR jsonb_typeof(NEW.intent_json->'requested_at') IS DISTINCT FROM 'string'
       OR jsonb_typeof(NEW.intent_json->'feature_enabled') IS DISTINCT FROM 'boolean'
       OR jsonb_typeof(NEW.intent_json->'status') IS DISTINCT FROM 'string' THEN
        RAISE EXCEPTION 'connector write-back proposal identity fields are missing or invalid' USING ERRCODE='check_violation';
    END IF;
    IF (NEW.intent_json->>'intent_id') IS DISTINCT FROM NEW.intent_id
       OR (NEW.intent_json->>'tenant_id') IS DISTINCT FROM NEW.tenant_id
       OR (NEW.intent_json->>'workspace_id') IS DISTINCT FROM NEW.workspace_id
       OR (NEW.intent_json->>'status') IS DISTINCT FROM NEW.status THEN
        RAISE EXCEPTION 'connector write-back columns do not match JSON identity' USING ERRCODE='check_violation';
    END IF;
    IF NEW.version = 1 THEN
        IF NEW.status <> 'proposed' THEN
            RAISE EXCEPTION 'connector write-back intent must start as proposed' USING ERRCODE='check_violation';
        END IF;
        RETURN NEW;
    END IF;
    SELECT previous.status, previous.intent_json
      INTO previous_row
      FROM reconforge.connector_writeback_intents AS previous
     WHERE previous.tenant_id = NEW.tenant_id
       AND previous.workspace_id = NEW.workspace_id
       AND previous.intent_id = NEW.intent_id
       AND previous.version = NEW.version - 1;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'connector write-back predecessor is missing' USING ERRCODE='check_violation';
    END IF;
    FOREACH immutable_key IN ARRAY ARRAY[
        'schema_version', 'connector_id', 'operation', 'payload_digest',
        'idempotency_key', 'requested_by', 'requested_at', 'feature_enabled'
    ] LOOP
        IF (previous_row.intent_json->immutable_key) IS DISTINCT FROM (NEW.intent_json->immutable_key) THEN
            RAISE EXCEPTION 'connector write-back proposal identity is immutable' USING ERRCODE='check_violation';
        END IF;
    END LOOP;
    IF NOT (
        (previous_row.status = 'proposed' AND NEW.status IN ('approved', 'rejected'))
        OR (previous_row.status = 'approved' AND NEW.status IN ('dispatched', 'rejected'))
        OR (previous_row.status = 'dispatched' AND NEW.status IN ('acknowledged', 'compensation_requested', 'failed'))
        OR (previous_row.status = 'acknowledged' AND NEW.status = 'compensation_requested')
        OR (previous_row.status = 'compensation_requested' AND NEW.status IN ('compensated', 'failed'))
    ) THEN
        RAISE EXCEPTION 'connector write-back intent transition is invalid' USING ERRCODE='check_violation';
    END IF;
    RETURN NEW;
END
$reconforge$;
DROP TRIGGER IF EXISTS connector_writeback_intent_guard
    ON reconforge.connector_writeback_intents;
CREATE TRIGGER connector_writeback_intent_guard
BEFORE INSERT OR UPDATE OR DELETE ON reconforge.connector_writeback_intents
FOR EACH ROW EXECUTE FUNCTION reconforge.guard_connector_writeback_intent();
"""

_POSTGRES_WRITEBACK_LEGACY_IMMUTABILITY_SQL = r"""
CREATE OR REPLACE FUNCTION reconforge.guard_connector_writeback_intent()
RETURNS TRIGGER LANGUAGE plpgsql AS $reconforge$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        RAISE EXCEPTION 'connector write-back intents are immutable' USING ERRCODE='check_violation';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'connector write-back intents cannot be deleted' USING ERRCODE='check_violation';
    END IF;
    RETURN NEW;
END
$reconforge$;
DROP TRIGGER IF EXISTS connector_writeback_intent_guard
    ON reconforge.connector_writeback_intents;
CREATE TRIGGER connector_writeback_intent_guard
BEFORE UPDATE OR DELETE ON reconforge.connector_writeback_intents
FOR EACH ROW EXECUTE FUNCTION reconforge.guard_connector_writeback_intent();
"""

# Keep the SQL consumed by historical migration 0061 stable. Migration 0089
# audits existing history and replaces this legacy append-only guard with the
# proposal-identity/lifecycle guard above.
POSTGRES_WRITEBACK_SCHEMA_SQL = _POSTGRES_WRITEBACK_TABLE_SQL + _POSTGRES_WRITEBACK_LEGACY_IMMUTABILITY_SQL


def _row_value(row: Any, key: str, index: int) -> Any:
    return row.get(key) if isinstance(row, Mapping) else row[index]


def _decode_intent(row: Any) -> tuple[int, WritebackIntent]:
    try:
        raw = _row_value(row, "intent_json", 3)
        document = json.loads(raw) if isinstance(raw, str) else raw
        intent = WritebackIntent.model_validate(document)
        if intent.digest != str(_row_value(row, "intent_digest", 2)) and intent.legacy_digest != str(
            _row_value(row, "intent_digest", 2)
        ):
            raise ValueError("digest mismatch")
        return int(_row_value(row, "version", 0)), intent
    except Exception as exc:
        raise PostgresWritebackPersistenceError("persisted write-back intent is invalid.") from exc


class PostgresWritebackIntentRepository:
    """Append-only write-back intent history with explicit tenant/workspace scope."""

    def __init__(self, connection: Any) -> None:
        self.connection = connection

    def _scope(self, tenant_id: str, workspace_id: str) -> tuple[str, str]:
        tenant = validate_tenant_id(tenant_id)
        workspace = validate_workspace_id(workspace_id)
        if workspace is None:
            raise PostgresWritebackPersistenceError("write-back workspace scope is required.")
        set_local_tenant_scope(self.connection, tenant, workspace_id=workspace)
        return tenant, workspace

    def _get_locked(self, *, tenant_id: str, workspace_id: str, intent_id: str, lock: bool) -> dict[str, Any] | None:
        parameters = (tenant_id, workspace_id, intent_id)
        if lock:
            # SELECT ... FOR UPDATE would require UPDATE privilege even though
            # this append-only role must never receive it. A transaction-scoped
            # advisory lock serializes same-intent writers while preserving
            # SELECT/INSERT-only table grants.
            lock_key = json.dumps((tenant_id, workspace_id, intent_id), ensure_ascii=True, separators=(",", ":"))
            self.connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (lock_key,),
            )
        row = self.connection.execute(
            """
            SELECT version, status, intent_digest, intent_json
            FROM reconforge.connector_writeback_intents
            WHERE tenant_id=%s AND workspace_id=%s AND intent_id=%s
            ORDER BY version DESC
            LIMIT 1
            """,
            parameters,
        ).fetchone()
        if row is None:
            return None
        version, intent = _decode_intent(row)
        return {"version": version, "status": intent.status.value, "intent": intent}

    def put(self, intent: WritebackIntent, *, expected_version: int | None = None) -> WritebackIntent:
        if not isinstance(intent, WritebackIntent):
            raise PostgresWritebackPersistenceError("write-back intent is invalid.")
        try:
            with self.connection.transaction():
                tenant, workspace = self._scope(intent.tenant_id, intent.workspace_id)
                current = self._get_locked(
                    tenant_id=tenant,
                    workspace_id=workspace,
                    intent_id=intent.intent_id,
                    lock=True,
                )
                if current is not None:
                    current_intent = current["intent"]
                    if current_intent.digest == intent.digest:
                        return current_intent
                    if expected_version is None or current["version"] != expected_version:
                        raise PostgresWritebackPersistenceError("write-back intent version conflict.")
                    try:
                        validate_writeback_transition(current_intent, intent)
                    except WritebackError as exc:
                        raise PostgresWritebackPersistenceError(str(exc)) from exc
                    version = int(current["version"]) + 1
                else:
                    if expected_version not in {None, 0} or intent.status is not WritebackStatus.PROPOSED:
                        raise PostgresWritebackPersistenceError("write-back intent must start as proposed.")
                    version = 1
                self.connection.execute(
                    """
                    INSERT INTO reconforge.connector_writeback_intents(
                        tenant_id, intent_id, workspace_id, version, status,
                        intent_digest, intent_json, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s)
                    """,
                    (
                        tenant,
                        intent.intent_id,
                        workspace,
                        version,
                        intent.status.value,
                        intent.digest,
                        json.dumps(intent.model_dump(mode="json", exclude_none=False), sort_keys=True, separators=(",", ":")),
                        intent.requested_at,
                    ),
                )
                return intent
        except PostgresWritebackPersistenceError:
            raise
        except Exception as exc:
            raise PostgresWritebackPersistenceError("write-back intent persistence failed.") from exc

    def get(self, *, intent_id: str, tenant_id: str, workspace_id: str) -> dict[str, Any] | None:
        try:
            with self.connection.transaction():
                tenant, workspace = self._scope(tenant_id, workspace_id)
                return self._get_locked(
                    tenant_id=tenant,
                    workspace_id=workspace,
                    intent_id=intent_id,
                    lock=False,
                )
        except PostgresWritebackPersistenceError:
            raise
        except Exception as exc:
            raise PostgresWritebackPersistenceError("write-back intent read failed.") from exc

    def list_latest(self, *, tenant_id: str, workspace_id: str) -> tuple[WritebackIntent, ...]:
        try:
            with self.connection.transaction():
                tenant, workspace = self._scope(tenant_id, workspace_id)
                rows = self.connection.execute(
                    """
                    SELECT DISTINCT ON (intent_id) version, status, intent_digest, intent_json
                    FROM reconforge.connector_writeback_intents
                    WHERE tenant_id=%s AND workspace_id=%s
                    ORDER BY intent_id, version DESC
                    """,
                    (tenant, workspace),
                ).fetchall()
                return tuple(_decode_intent(row)[1] for row in rows)
        except PostgresWritebackPersistenceError:
            raise
        except Exception as exc:
            raise PostgresWritebackPersistenceError("write-back intent listing failed.") from exc
