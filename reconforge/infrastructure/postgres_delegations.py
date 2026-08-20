"""Tenant-scoped PostgreSQL persistence for temporary policy delegations.

The repository owns validation and row-shape conversion, while transaction
ownership remains with the caller.  Database triggers make approved grants
append-only: the only permitted transition is an independent actor revoking
an active grant.  This keeps delegation state replayable and prevents a
policy administrator from silently changing historical authority.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from reconforge.auth.delegations import DelegationGrant, DelegationValidationError
from reconforge.infrastructure.postgres import (
    PostgresConfigurationError,
    normalize_scope_id,
    validate_tenant_id,
    validate_workspace_id,
)


class PostgresDelegationError(ValueError):
    """Disclosure-safe PostgreSQL delegation failure."""


def _scope(value: str, field_name: str) -> str:
    try:
        return normalize_scope_id(value, field_name=field_name)
    except PostgresConfigurationError as exc:
        raise PostgresDelegationError(f"{field_name} is invalid.") from exc


def _tenant(value: str) -> str:
    try:
        return validate_tenant_id(value)
    except PostgresConfigurationError as exc:
        raise PostgresDelegationError("tenant_id is invalid.") from exc


def _workspace(value: str) -> str:
    try:
        normalized = validate_workspace_id(value)
    except PostgresConfigurationError as exc:
        raise PostgresDelegationError("workspace_id is invalid.") from exc
    if normalized is None:
        raise PostgresDelegationError("workspace_id is required.")
    return normalized


def _timestamp(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise PostgresDelegationError(f"{field_name} must be timezone-aware.")
    return value.astimezone(UTC)


def _value(row: Any, key: str, index: int) -> Any:
    if isinstance(row, Mapping):
        return row.get(key)
    return row[index]


def _row_to_grant(row: Any) -> DelegationGrant:
    try:
        permissions = _value(row, "permissions", 5)
        if isinstance(permissions, str):
            permissions = json.loads(permissions)
        return DelegationGrant(
            id=str(_value(row, "id", 0)),
            tenant_id=str(_value(row, "tenant_id", 1)),
            workspace_id=str(_value(row, "workspace_id", 2)),
            delegator_id=str(_value(row, "delegator_id", 3)),
            delegatee_id=str(_value(row, "delegatee_id", 4)),
            permissions=frozenset(str(item) for item in permissions),
            starts_at=_parse_timestamp(_value(row, "starts_at", 6), "starts_at"),
            expires_at=_parse_timestamp(_value(row, "expires_at", 7), "expires_at"),
            created_by=str(_value(row, "created_by", 8)),
            approved_by=str(_value(row, "approved_by", 9)),
            status=str(_value(row, "status", 10)),
            revoked_at=(
                _parse_timestamp(_value(row, "revoked_at", 11), "revoked_at")
                if _value(row, "revoked_at", 11) is not None
                else None
            ),
            revoked_by=str(_value(row, "revoked_by", 12)) if _value(row, "revoked_by", 12) else None,
        )
    except (DelegationValidationError, TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
        raise PostgresDelegationError("Stored delegation is invalid.") from exc


def _parse_timestamp(value: Any, field_name: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError as exc:
            raise PostgresDelegationError(f"Stored {field_name} is invalid.") from exc
    return _timestamp(parsed, field_name)


class PostgresDelegationRepository:
    """Persist and query immutable tenant/workspace-scoped delegations."""

    def __init__(self, connection: Any) -> None:
        self.connection = connection

    def create(self, grant: DelegationGrant) -> DelegationGrant:
        try:
            # Re-run domain validation and normalize the scope before SQL.
            validated = DelegationGrant(
                id=_scope(grant.id, "delegation_id"),
                tenant_id=_tenant(grant.tenant_id),
                workspace_id=_workspace(grant.workspace_id),
                delegator_id=_scope(grant.delegator_id, "delegator_id"),
                delegatee_id=_scope(grant.delegatee_id, "delegatee_id"),
                permissions=grant.permissions,
                starts_at=_timestamp(grant.starts_at, "starts_at"),
                expires_at=_timestamp(grant.expires_at, "expires_at"),
                created_by=_scope(grant.created_by, "created_by"),
                approved_by=_scope(grant.approved_by, "approved_by"),
                status=grant.status,
                revoked_at=grant.revoked_at,
                revoked_by=_scope(grant.revoked_by, "revoked_by") if grant.revoked_by else None,
            )
            self.connection.execute(
                """INSERT INTO reconforge.policy_delegations
                   (tenant_id,id,workspace_id,delegator_id,delegatee_id,permissions,
                    starts_at,expires_at,created_by,approved_by,status,revoked_at,revoked_by)
                   VALUES (%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    validated.tenant_id,
                    validated.id,
                    validated.workspace_id,
                    validated.delegator_id,
                    validated.delegatee_id,
                    validated.permissions_json(),
                    validated.starts_at,
                    validated.expires_at,
                    validated.created_by,
                    validated.approved_by,
                    validated.status,
                    validated.revoked_at,
                    validated.revoked_by,
                ),
            )
            return validated
        except PostgresDelegationError:
            raise
        except (DelegationValidationError, TypeError, ValueError) as exc:
            raise PostgresDelegationError("Delegation validation failed.") from exc
        except Exception as exc:  # driver-specific integrity errors stay disclosure-safe
            raise PostgresDelegationError("Delegation already exists or violates tenant policy.") from exc

    def get_effective(
        self,
        *,
        delegation_id: str,
        tenant_id: str,
        workspace_id: str,
        evaluation_time: datetime,
    ) -> DelegationGrant | None:
        tenant = _tenant(tenant_id)
        workspace = _workspace(workspace_id)
        identifier = _scope(delegation_id, "delegation_id")
        instant = _timestamp(evaluation_time, "evaluation_time")
        row = self.connection.execute(
            """SELECT id,tenant_id,workspace_id,delegator_id,delegatee_id,permissions,
                      starts_at,expires_at,created_by,approved_by,status,revoked_at,revoked_by
                 FROM reconforge.policy_delegations
                WHERE tenant_id=%s AND id=%s AND workspace_id=%s AND status='active'
                  AND starts_at <= %s AND expires_at > %s""",
            (tenant, identifier, workspace, instant, instant),
        ).fetchone()
        return None if row is None else _row_to_grant(row)

    def revoke(
        self,
        *,
        delegation_id: str,
        tenant_id: str,
        workspace_id: str,
        actor_id: str,
        revoked_at: datetime,
    ) -> DelegationGrant:
        tenant = _tenant(tenant_id)
        workspace = _workspace(workspace_id)
        identifier = _scope(delegation_id, "delegation_id")
        actor = _scope(actor_id, "actor_id")
        instant = _timestamp(revoked_at, "revoked_at")
        row = self.connection.execute(
            """UPDATE reconforge.policy_delegations
                  SET status='revoked', revoked_at=%s, revoked_by=%s
                WHERE tenant_id=%s AND id=%s AND workspace_id=%s AND status='active'
                  AND delegator_id <> %s
            RETURNING id,tenant_id,workspace_id,delegator_id,delegatee_id,permissions,
                      starts_at,expires_at,created_by,approved_by,status,revoked_at,revoked_by""",
            (instant, actor, tenant, identifier, workspace, actor),
        ).fetchone()
        if row is None:
            raise PostgresDelegationError("Delegation not found or revocation is not permitted.")
        return _row_to_grant(row)


POSTGRES_DELEGATION_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS reconforge.policy_delegations (
    tenant_id TEXT NOT NULL,
    id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    delegator_id TEXT NOT NULL,
    delegatee_id TEXT NOT NULL,
    permissions JSONB NOT NULL,
    starts_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    created_by TEXT NOT NULL,
    approved_by TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    revoked_at TIMESTAMPTZ,
    revoked_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    CONSTRAINT policy_delegations_distinct_users CHECK (delegator_id <> delegatee_id),
    CONSTRAINT policy_delegations_independent_approval CHECK (approved_by <> delegator_id),
    CONSTRAINT policy_delegations_time_order CHECK (starts_at < expires_at),
    CONSTRAINT policy_delegations_permissions_array CHECK (
        jsonb_typeof(permissions) = 'array' AND jsonb_array_length(permissions) > 0
    ),
    CONSTRAINT policy_delegations_status_consistent CHECK (
        (status = 'active' AND revoked_at IS NULL AND revoked_by IS NULL)
        OR (status = 'revoked' AND revoked_at IS NOT NULL AND revoked_by IS NOT NULL)
    )
);
CREATE INDEX IF NOT EXISTS policy_delegations_effective_idx
    ON reconforge.policy_delegations (tenant_id, workspace_id, id, status, starts_at, expires_at);
ALTER TABLE reconforge.policy_delegations ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.policy_delegations FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.policy_delegations;
CREATE POLICY tenant_scope ON reconforge.policy_delegations
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
CREATE OR REPLACE FUNCTION reconforge.guard_policy_delegation_update() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'policy delegations are append-only; revoke the grant instead';
    END IF;
    IF OLD.tenant_id <> NEW.tenant_id OR OLD.id <> NEW.id OR OLD.workspace_id <> NEW.workspace_id
       OR OLD.delegator_id <> NEW.delegator_id OR OLD.delegatee_id <> NEW.delegatee_id
       OR OLD.permissions <> NEW.permissions OR OLD.starts_at <> NEW.starts_at
       OR OLD.expires_at <> NEW.expires_at OR OLD.created_by <> NEW.created_by
       OR OLD.approved_by <> NEW.approved_by OR OLD.created_at <> NEW.created_at
       OR OLD.status <> 'active' OR NEW.status <> 'revoked'
       OR NEW.revoked_at IS NULL OR NEW.revoked_by IS NULL
       OR NEW.revoked_by = OLD.delegator_id THEN
        RAISE EXCEPTION 'policy delegation mutation is not an independent revocation';
    END IF;
    RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS policy_delegation_guard ON reconforge.policy_delegations;
CREATE TRIGGER policy_delegation_guard
    BEFORE UPDATE OR DELETE ON reconforge.policy_delegations
    FOR EACH ROW EXECUTE FUNCTION reconforge.guard_policy_delegation_update();
"""
