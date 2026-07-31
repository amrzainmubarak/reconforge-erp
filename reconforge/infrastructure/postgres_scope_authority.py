"""Durable principal grants for trusted PostgreSQL execution scope."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

from reconforge.infrastructure.postgres import normalize_scope_id, validate_tenant_id

ScopeType = Literal["workspace", "organization", "legal_entity"]
PrincipalType = Literal["user", "service_account"]
_PRINCIPAL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,127}$")

POSTGRES_SCOPE_AUTHORITY_SCHEMA_SQL = r"""
CREATE TABLE IF NOT EXISTS reconforge.principal_scope_grants (
  tenant_id TEXT NOT NULL,
  id TEXT NOT NULL,
  principal_type TEXT NOT NULL CHECK (principal_type IN ('user','service_account')),
  principal_id TEXT NOT NULL,
  scope_type TEXT NOT NULL CHECK (scope_type IN ('workspace','organization','legal_entity')),
  scope_id TEXT NOT NULL,
  granted_by TEXT NOT NULL,
  granted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  revoked_by TEXT NOT NULL DEFAULT '',
  revoked_at TIMESTAMPTZ,
  revocation_reason TEXT NOT NULL DEFAULT '',
  PRIMARY KEY (tenant_id,id),
  FOREIGN KEY (tenant_id) REFERENCES reconforge.tenants(id) ON DELETE CASCADE,
  CHECK ((revoked_at IS NULL AND revoked_by='' AND revocation_reason='') OR
         (revoked_at IS NOT NULL AND revoked_by<>'' AND revocation_reason<>''))
);
CREATE UNIQUE INDEX IF NOT EXISTS principal_scope_grants_active_unique
 ON reconforge.principal_scope_grants(tenant_id,principal_type,principal_id,scope_type,scope_id)
 WHERE revoked_at IS NULL;
CREATE INDEX IF NOT EXISTS principal_scope_grants_lookup
 ON reconforge.principal_scope_grants(tenant_id,principal_type,principal_id,revoked_at,scope_type,scope_id);

CREATE OR REPLACE FUNCTION reconforge.principal_scope_grant_guard() RETURNS trigger
LANGUAGE plpgsql AS $reconforge$
BEGIN
  IF TG_OP='DELETE' THEN RAISE EXCEPTION 'scope grants are immutable; revoke instead'; END IF;
  IF TG_OP='UPDATE' THEN
    IF (NEW.tenant_id,NEW.id,NEW.principal_type,NEW.principal_id,NEW.scope_type,NEW.scope_id,
        NEW.granted_by,NEW.granted_at)
       IS DISTINCT FROM
       (OLD.tenant_id,OLD.id,OLD.principal_type,OLD.principal_id,OLD.scope_type,OLD.scope_id,
        OLD.granted_by,OLD.granted_at)
    THEN RAISE EXCEPTION 'scope grant authority is immutable'; END IF;
    IF OLD.revoked_at IS NOT NULL THEN RAISE EXCEPTION 'revoked scope grants are immutable'; END IF;
    RETURN NEW;
  END IF;
  IF NEW.principal_type='user' AND NOT EXISTS (
    SELECT 1 FROM reconforge.identity_users u WHERE u.tenant_id=NEW.tenant_id AND u.id=NEW.principal_id
  ) THEN RAISE EXCEPTION 'scope grant user is not registered'; END IF;
  IF NEW.principal_type='service_account' AND NOT EXISTS (
    SELECT 1 FROM reconforge.service_accounts s WHERE s.tenant_id=NEW.tenant_id AND s.id=NEW.principal_id
  ) THEN RAISE EXCEPTION 'scope grant service account is not registered'; END IF;
  IF NEW.scope_type='workspace' AND NOT EXISTS (
    SELECT 1 FROM reconforge.domain_workspaces w WHERE w.tenant_id=NEW.tenant_id AND w.id=NEW.scope_id
  ) THEN RAISE EXCEPTION 'scope grant workspace is not registered'; END IF;
  IF NEW.scope_type='organization' AND NOT EXISTS (
    SELECT 1 FROM reconforge.organizations o WHERE o.tenant_id=NEW.tenant_id AND o.id=NEW.scope_id
  ) THEN RAISE EXCEPTION 'scope grant organization is not registered'; END IF;
  IF NEW.scope_type='legal_entity' AND NOT EXISTS (
    SELECT 1 FROM reconforge.legal_entities e WHERE e.tenant_id=NEW.tenant_id AND e.id=NEW.scope_id
  ) THEN RAISE EXCEPTION 'scope grant legal entity is not registered'; END IF;
  RETURN NEW;
END $reconforge$;
DROP TRIGGER IF EXISTS principal_scope_grants_guard ON reconforge.principal_scope_grants;
CREATE TRIGGER principal_scope_grants_guard BEFORE INSERT OR UPDATE OR DELETE
 ON reconforge.principal_scope_grants FOR EACH ROW EXECUTE FUNCTION reconforge.principal_scope_grant_guard();
ALTER TABLE reconforge.principal_scope_grants ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.principal_scope_grants FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.principal_scope_grants;
CREATE POLICY tenant_scope ON reconforge.principal_scope_grants
 USING (tenant_id=current_setting('app.tenant_id',true))
 WITH CHECK (tenant_id=current_setting('app.tenant_id',true));
"""


@dataclass(frozen=True)
class PrincipalScopeSnapshot:
    workspace_ids: frozenset[str] = frozenset()
    organization_ids: frozenset[str] = frozenset()
    legal_entity_ids: frozenset[str] = frozenset()


@dataclass(frozen=True)
class PostgresScopeAuthorityRepository:
    connection: Any

    def active_for_principal(
        self, *, tenant_id: str, principal_type: PrincipalType, principal_id: str
    ) -> PrincipalScopeSnapshot:
        tenant = validate_tenant_id(tenant_id)
        if principal_type not in {"user", "service_account"} or not _PRINCIPAL_ID.fullmatch(principal_id):
            return PrincipalScopeSnapshot()
        rows = self.connection.execute(
            "SELECT scope_type,scope_id FROM reconforge.principal_scope_grants "
            "WHERE tenant_id=%s AND principal_type=%s AND principal_id=%s AND revoked_at IS NULL "
            "ORDER BY scope_type,scope_id",
            (tenant, principal_type, principal_id),
        ).fetchall()
        grouped: dict[str, set[str]] = {"workspace": set(), "organization": set(), "legal_entity": set()}
        for row in rows:
            grouped[str(row[0])].add(str(row[1]))
        return PrincipalScopeSnapshot(
            workspace_ids=frozenset(grouped["workspace"]),
            organization_ids=frozenset(grouped["organization"]),
            legal_entity_ids=frozenset(grouped["legal_entity"]),
        )

    def list_active(
        self, *, tenant_id: str, principal_type: PrincipalType, principal_id: str
    ) -> list[dict[str, str]]:
        tenant = validate_tenant_id(tenant_id)
        if principal_type not in {"user", "service_account"} or not _PRINCIPAL_ID.fullmatch(principal_id):
            raise ValueError("principal identity is invalid")
        rows = self.connection.execute(
            "SELECT id,principal_type,principal_id,scope_type,scope_id,granted_by,granted_at "
            "FROM reconforge.principal_scope_grants WHERE tenant_id=%s AND principal_type=%s "
            "AND principal_id=%s AND revoked_at IS NULL ORDER BY scope_type,scope_id,id",
            (tenant, principal_type, principal_id),
        ).fetchall()
        return [
            {
                "id": str(row[0]),
                "principal_type": str(row[1]),
                "principal_id": str(row[2]),
                "scope_type": str(row[3]),
                "scope_id": str(row[4]),
                "granted_by": str(row[5]),
                "granted_at": str(row[6]),
            }
            for row in rows
        ]

    def grant(
        self,
        *,
        tenant_id: str,
        grant_id: str,
        principal_type: PrincipalType,
        principal_id: str,
        scope_type: ScopeType,
        scope_id: str,
        actor_id: str,
    ) -> None:
        tenant = validate_tenant_id(tenant_id)
        normalized_grant = normalize_scope_id(grant_id, field_name="grant_id")
        normalized_scope = normalize_scope_id(scope_id, field_name="scope_id")
        if principal_type not in {"user", "service_account"} or not _PRINCIPAL_ID.fullmatch(principal_id):
            raise ValueError("principal identity is invalid")
        if scope_type not in {"workspace", "organization", "legal_entity"}:
            raise ValueError("scope_type is invalid")
        if not _PRINCIPAL_ID.fullmatch(actor_id):
            raise ValueError("actor_id is invalid")
        self.connection.execute(
            "INSERT INTO reconforge.principal_scope_grants"
            "(tenant_id,id,principal_type,principal_id,scope_type,scope_id,granted_by) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s)",
            (tenant, normalized_grant, principal_type, principal_id, scope_type, normalized_scope, actor_id),
        )

    def revoke(self, *, tenant_id: str, grant_id: str, actor_id: str, reason: str) -> None:
        if not reason.strip() or not _PRINCIPAL_ID.fullmatch(actor_id):
            raise ValueError("revocation actor and reason are required")
        cursor = self.connection.execute(
            "UPDATE reconforge.principal_scope_grants SET revoked_by=%s,revoked_at=now(),revocation_reason=%s "
            "WHERE tenant_id=%s AND id=%s AND revoked_at IS NULL",
            (actor_id, reason.strip(), validate_tenant_id(tenant_id), normalize_scope_id(grant_id, field_name="grant_id")),
        )
        if cursor.rowcount != 1:
            raise ValueError("active scope grant was not found")


def install_postgres_scope_authority_schema(connection: Any) -> None:
    connection.execute(POSTGRES_SCOPE_AUTHORITY_SCHEMA_SQL)
