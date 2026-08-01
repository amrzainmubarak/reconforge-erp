"""PostgreSQL integration and evidence-retention administration."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from reconforge.application.security_governance import (
    DataClassification,
    EvidenceRetentionChange,
    IntegrationDisableChange,
    IntegrationKind,
    IntegrationPage,
    IntegrationStatus,
    IntegrationSummary,
    RetentionPolicyChange,
    RetentionPolicyPage,
    RetentionPolicySummary,
    SecurityGovernanceError,
)
from reconforge.infrastructure.postgres import PostgresConfigurationError, normalize_scope_id
from reconforge.infrastructure.postgres_domain import PostgresAuditEventRepository

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,319}$")
_INTEGRATION_KINDS = frozenset({"federation_link", "notification_route", "scim_credential", "service_account"})


def _value(row: Any, key: str, index: int) -> Any:
    return row[key] if isinstance(row, Mapping) else row[index]


def _identifier(value: str, field_name: str) -> str:
    normalized = str(value).strip()
    if not _IDENTIFIER.fullmatch(normalized):
        raise SecurityGovernanceError("security_governance_identifier_invalid", f"{field_name} is invalid.")
    return normalized


def _tenant(value: str) -> str:
    try:
        return normalize_scope_id(value, field_name="tenant_id")
    except PostgresConfigurationError as exc:
        raise SecurityGovernanceError("security_governance_tenant_invalid", "tenant_id is invalid.") from exc


def _utc_text(value: object | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
        except ValueError as exc:
            raise SecurityGovernanceError(
                "security_governance_persisted_time_invalid", "Stored administration time is invalid."
            ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SecurityGovernanceError(
            "security_governance_persisted_time_invalid", "Stored administration time needs a timezone."
        )
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _digest(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(dict(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def _secret_digest(value: object | None) -> str | None:
    return None if value is None else hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def _clock(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None or value.microsecond:
        raise SecurityGovernanceError(
            "security_governance_time_invalid", "Administration time must be timezone-aware and whole-second."
        )
    return value.astimezone(UTC)


_INTEGRATION_LIST_SQL = """
WITH integrations AS (
  SELECT 'federation_link'::text AS kind,
         l.provider_id || ':' || l.user_id AS integration_id,
         CASE WHEN l.disabled_at IS NULL THEN 'active' ELSE 'disabled' END AS status,
         (1 + CASE WHEN l.disabled_at IS NULL THEN 0 ELSE 1 END)::bigint AS lifecycle_version,
         0::bigint AS credential_count, 0::bigint AS active_credential_count,
         l.linked_at AS created_at, NULL::timestamptz AS expires_at,
         NULL::timestamptz AS last_used_at, l.provider_id AS scope_material,
         l.disabled_by AS disabled_actor, l.disabled_at
    FROM reconforge.federation_identity_links l
   WHERE l.tenant_id=%s
  UNION ALL
  SELECT 'notification_route', r.route_id || ':' || r.route_version::text,
         CASE WHEN r.enabled THEN 'active' ELSE 'disabled' END,
         r.route_version::bigint, 0::bigint, 0::bigint, r.created_at,
         NULL::timestamptz, NULL::timestamptz,
         r.workspace_id || ':' || r.entity_id || ':' || r.channel,
         NULL::text, CASE WHEN r.enabled THEN NULL::timestamptz ELSE r.created_at END
    FROM reconforge.notification_routes r
   WHERE r.tenant_id=%s
  UNION ALL
  SELECT 'scim_credential', c.id,
         CASE WHEN c.revoked_at IS NOT NULL THEN 'disabled'
              WHEN c.expires_at<=%s THEN 'expired' ELSE 'active' END,
         (1 + CASE WHEN c.revoked_at IS NULL THEN 0 ELSE 1 END)::bigint,
         1::bigint,
         CASE WHEN c.revoked_at IS NULL AND c.expires_at>%s THEN 1 ELSE 0 END::bigint,
         c.created_at,c.expires_at,c.last_used_at,
         c.provisioning_domain || ':' || c.client_id,c.revoked_by,c.revoked_at
    FROM reconforge.scim_credentials c
   WHERE c.tenant_id=%s
  UNION ALL
  SELECT 'service_account', a.id,
         CASE WHEN a.enabled THEN 'active' ELSE 'disabled' END,
         a.version::bigint,
         (SELECT count(*) FROM reconforge.service_account_credentials c
           WHERE c.tenant_id=a.tenant_id AND c.service_account_id=a.id),
         (SELECT count(*) FROM reconforge.service_account_credentials c
           WHERE c.tenant_id=a.tenant_id AND c.service_account_id=a.id
             AND c.revoked_at IS NULL AND c.expires_at>%s),
         a.created_at,NULL::timestamptz,
         (SELECT max(c.last_used_at) FROM reconforge.service_account_credentials c
           WHERE c.tenant_id=a.tenant_id AND c.service_account_id=a.id),
         a.name,NULL::text,CASE WHEN a.enabled THEN NULL::timestamptz ELSE a.updated_at END
    FROM reconforge.service_accounts a
   WHERE a.tenant_id=%s
)
SELECT kind,integration_id,status,lifecycle_version,credential_count,active_credential_count,
       created_at,expires_at,last_used_at,scope_material,disabled_actor,disabled_at
  FROM integrations
 WHERE (%s OR status='active')
   AND (%s::text IS NULL OR kind>%s::text OR (kind=%s::text AND integration_id>%s::text))
 ORDER BY kind,integration_id
 LIMIT %s
"""


POSTGRES_SECURITY_GOVERNANCE_SCHEMA_SQL = r"""
ALTER TABLE reconforge.evidence_registry
  ADD COLUMN IF NOT EXISTS retention_version BIGINT NOT NULL DEFAULT 1;
ALTER TABLE reconforge.evidence_registry
  DROP CONSTRAINT IF EXISTS evidence_registry_retention_version_positive;
ALTER TABLE reconforge.evidence_registry
  ADD CONSTRAINT evidence_registry_retention_version_positive CHECK (retention_version >= 1);

CREATE TABLE IF NOT EXISTS reconforge.retention_policies (
  tenant_id TEXT NOT NULL REFERENCES reconforge.tenants(id) ON DELETE CASCADE,
  id TEXT NOT NULL CHECK (id ~ '^rtp-[0-9a-f]{32}$'),
  name TEXT NOT NULL CHECK (name ~ '^[a-z0-9][a-z0-9._-]{0,63}$'),
  description TEXT NOT NULL DEFAULT '' CHECK (length(description) <= 500),
  data_classification TEXT NOT NULL
    CHECK (data_classification IN ('public','internal','confidential','restricted')),
  duration_days INTEGER NOT NULL CHECK (duration_days BETWEEN 1 AND 36500),
  active BOOLEAN NOT NULL DEFAULT TRUE,
  lifecycle_version BIGINT NOT NULL DEFAULT 1 CHECK (lifecycle_version >= 1),
  created_by TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT date_trunc('second',now()),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT date_trunc('second',now()),
  retired_at TIMESTAMPTZ,
  retired_by TEXT,
  retirement_reason_code TEXT,
  PRIMARY KEY (tenant_id,id),
  UNIQUE (tenant_id,name),
  CONSTRAINT retention_policies_retirement_reason_closed CHECK (
    retirement_reason_code IS NULL OR retirement_reason_code IN
      ('administrative_cleanup','policy_change','security_response','user_request')
  ),
  CONSTRAINT retention_policies_state_consistent CHECK (
    (active AND retired_at IS NULL AND retired_by IS NULL AND retirement_reason_code IS NULL)
    OR (NOT active AND retired_at IS NOT NULL AND retired_by IS NOT NULL
        AND retirement_reason_code IS NOT NULL)
  )
);

CREATE TABLE IF NOT EXISTS reconforge.evidence_retention_assignments (
  tenant_id TEXT NOT NULL,
  id TEXT NOT NULL CHECK (id ~ '^rta-[0-9a-f]{32}$'),
  evidence_id TEXT NOT NULL,
  policy_id TEXT NOT NULL,
  policy_lifecycle_version BIGINT NOT NULL CHECK (policy_lifecycle_version >= 1),
  evidence_retention_version BIGINT NOT NULL CHECK (evidence_retention_version >= 1),
  previous_retention_until TIMESTAMPTZ,
  policy_retention_until TIMESTAMPTZ NOT NULL,
  effective_retention_until TIMESTAMPTZ NOT NULL,
  assigned_by TEXT NOT NULL,
  assigned_at TIMESTAMPTZ NOT NULL,
  reason_code TEXT NOT NULL CHECK (
    reason_code IN ('policy_application','regulatory_request','security_response','contractual_requirement')
  ),
  PRIMARY KEY (tenant_id,id),
  UNIQUE (tenant_id,evidence_id,policy_id,policy_lifecycle_version),
  FOREIGN KEY (tenant_id,evidence_id)
    REFERENCES reconforge.evidence_registry(tenant_id,id) ON DELETE RESTRICT,
  FOREIGN KEY (tenant_id,policy_id)
    REFERENCES reconforge.retention_policies(tenant_id,id) ON DELETE RESTRICT,
  CHECK (policy_retention_until >= assigned_at),
  CHECK (effective_retention_until >= policy_retention_until),
  CHECK (previous_retention_until IS NULL OR effective_retention_until >= previous_retention_until)
);

CREATE INDEX IF NOT EXISTS idx_retention_policies_admin_page
  ON reconforge.retention_policies (tenant_id,active,name,id);
CREATE INDEX IF NOT EXISTS idx_evidence_retention_assignments_evidence
  ON reconforge.evidence_retention_assignments (tenant_id,evidence_id,assigned_at,id);

CREATE OR REPLACE FUNCTION reconforge.guard_evidence_retention_floor()
RETURNS trigger LANGUAGE plpgsql AS $reconforge$
BEGIN
  IF NEW.retention_until IS DISTINCT FROM OLD.retention_until THEN
    IF OLD.retention_until IS NOT NULL
       AND (NEW.retention_until IS NULL OR NEW.retention_until < OLD.retention_until) THEN
      RAISE EXCEPTION 'evidence retention cannot be shortened' USING ERRCODE='check_violation';
    END IF;
    IF NEW.retention_version <> OLD.retention_version + 1 THEN
      RAISE EXCEPTION 'evidence retention version transition is invalid' USING ERRCODE='check_violation';
    END IF;
  ELSIF NEW.retention_version <> OLD.retention_version THEN
    RAISE EXCEPTION 'evidence retention version changed without a retention change' USING ERRCODE='check_violation';
  END IF;
  RETURN NEW;
END $reconforge$;
DROP TRIGGER IF EXISTS evidence_retention_floor_guard ON reconforge.evidence_registry;
CREATE TRIGGER evidence_retention_floor_guard
BEFORE UPDATE OF retention_until,retention_version ON reconforge.evidence_registry
FOR EACH ROW EXECUTE FUNCTION reconforge.guard_evidence_retention_floor();

CREATE OR REPLACE FUNCTION reconforge.guard_retention_policy_update()
RETURNS trigger LANGUAGE plpgsql AS $reconforge$
BEGIN
  IF NEW.tenant_id<>OLD.tenant_id OR NEW.id<>OLD.id OR NEW.name<>OLD.name
     OR NEW.created_by<>OLD.created_by OR NEW.created_at<>OLD.created_at
     OR NEW.lifecycle_version<>OLD.lifecycle_version+1 THEN
    RAISE EXCEPTION 'retention policy identity or version transition is invalid' USING ERRCODE='check_violation';
  END IF;
  RETURN NEW;
END $reconforge$;
DROP TRIGGER IF EXISTS retention_policy_update_guard ON reconforge.retention_policies;
CREATE TRIGGER retention_policy_update_guard BEFORE UPDATE ON reconforge.retention_policies
FOR EACH ROW EXECUTE FUNCTION reconforge.guard_retention_policy_update();

CREATE OR REPLACE FUNCTION reconforge.reject_retention_assignment_mutation()
RETURNS trigger LANGUAGE plpgsql AS $reconforge$
BEGIN
  RAISE EXCEPTION 'evidence retention assignments are append-only' USING ERRCODE='check_violation';
END $reconforge$;
DROP TRIGGER IF EXISTS evidence_retention_assignments_append_only
  ON reconforge.evidence_retention_assignments;
CREATE TRIGGER evidence_retention_assignments_append_only
BEFORE UPDATE OR DELETE ON reconforge.evidence_retention_assignments
FOR EACH ROW EXECUTE FUNCTION reconforge.reject_retention_assignment_mutation();

ALTER TABLE reconforge.retention_policies ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.retention_policies FORCE ROW LEVEL SECURITY;
ALTER TABLE reconforge.evidence_retention_assignments ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.evidence_retention_assignments FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.retention_policies;
CREATE POLICY tenant_scope ON reconforge.retention_policies
USING (tenant_id=current_setting('app.tenant_id',true))
WITH CHECK (tenant_id=current_setting('app.tenant_id',true));
DROP POLICY IF EXISTS tenant_scope ON reconforge.evidence_retention_assignments;
CREATE POLICY tenant_scope ON reconforge.evidence_retention_assignments
USING (tenant_id=current_setting('app.tenant_id',true))
WITH CHECK (tenant_id=current_setting('app.tenant_id',true));
"""


@dataclass(frozen=True)
class PostgresSecurityGovernanceRepository:
    """Govern real integration rows and evidence-retention policy in one caller transaction."""

    connection: Any
    tenant_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "tenant_id", _tenant(self.tenant_id))

    def _lock(self) -> None:
        self.connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
            (f"security-governance:{self.tenant_id}",),
        )

    def _actor(self, actor_user_id: str) -> str:
        actor = _identifier(actor_user_id, "actor_user_id")
        row = self.connection.execute(
            "SELECT 1 FROM reconforge.identity_users WHERE tenant_id=%s AND id=%s AND NOT disabled",
            (self.tenant_id, actor),
        ).fetchone()
        if row is None:
            raise SecurityGovernanceError("security_governance_actor_inactive", "Administrator is not active.")
        return actor

    @staticmethod
    def _integration(row: Any) -> IntegrationSummary:
        kind = str(_value(row, "kind", 0))
        status = str(_value(row, "status", 2))
        if kind not in _INTEGRATION_KINDS or status not in {"active", "disabled", "expired"}:
            raise SecurityGovernanceError(
                "integration_persisted_state_invalid", "Stored integration state is invalid."
            )
        created_at = _utc_text(_value(row, "created_at", 6))
        expires_at = _utc_text(_value(row, "expires_at", 7))
        last_used_at = _utc_text(_value(row, "last_used_at", 8))
        disabled_at = _utc_text(_value(row, "disabled_at", 11))
        scope_digest = hashlib.sha256(str(_value(row, "scope_material", 9)).encode("utf-8")).hexdigest()
        credential_count = int(_value(row, "credential_count", 4))
        active_credential_count = int(_value(row, "active_credential_count", 5))
        lifecycle_version = int(_value(row, "lifecycle_version", 3))
        state = {
            "active_credential_count": active_credential_count,
            "created_at": created_at,
            "credential_count": credential_count,
            "disabled_actor_digest": _secret_digest(_value(row, "disabled_actor", 10)),
            "disabled_at": disabled_at,
            "expires_at": expires_at,
            "id": str(_value(row, "integration_id", 1)),
            "kind": kind,
            "last_used_at": last_used_at,
            "lifecycle_version": lifecycle_version,
            "scope_digest": scope_digest,
            "status": status,
        }
        if credential_count < 0 or active_credential_count < 0 or lifecycle_version < 1:
            raise SecurityGovernanceError(
                "integration_persisted_state_invalid", "Stored integration counts are invalid."
            )
        return IntegrationSummary(
            kind=cast(IntegrationKind, kind),
            id=str(state["id"]),
            status=cast(IntegrationStatus, status),
            lifecycle_version=lifecycle_version,
            credential_count=credential_count,
            active_credential_count=active_credential_count,
            created_at=str(created_at),
            expires_at=expires_at,
            last_used_at=last_used_at,
            scope_digest=scope_digest,
            state_digest=_digest(state),
        )

    @staticmethod
    def _policy(row: Any) -> RetentionPolicySummary:
        created_at = _utc_text(_value(row, "created_at", 7))
        updated_at = _utc_text(_value(row, "updated_at", 8))
        retired_at = _utc_text(_value(row, "retired_at", 9))
        classification = str(_value(row, "data_classification", 3))
        if classification not in {"public", "internal", "confidential", "restricted"}:
            raise SecurityGovernanceError(
                "retention_policy_persisted_state_invalid", "Stored retention policy is invalid."
            )
        duration_days = int(_value(row, "duration_days", 4))
        lifecycle_version = int(_value(row, "lifecycle_version", 6))
        state = {
            "active": bool(_value(row, "active", 5)),
            "created_at": created_at,
            "created_by_digest": _secret_digest(_value(row, "created_by", 11)),
            "data_classification": classification,
            "description": str(_value(row, "description", 2)),
            "duration_days": duration_days,
            "id": str(_value(row, "id", 0)),
            "lifecycle_version": lifecycle_version,
            "name": str(_value(row, "name", 1)),
            "retired_at": retired_at,
            "retired_by_digest": _secret_digest(_value(row, "retired_by", 10)),
            "updated_at": updated_at,
        }
        return RetentionPolicySummary(
            id=str(state["id"]),
            name=str(state["name"]),
            description=str(state["description"]),
            data_classification=cast(DataClassification, classification),
            duration_days=duration_days,
            active=bool(state["active"]),
            lifecycle_version=lifecycle_version,
            created_at=str(created_at),
            updated_at=str(updated_at),
            retired_at=retired_at,
            state_digest=_digest(state),
        )

    def list_integrations(
        self,
        *,
        as_of: datetime,
        include_inactive: bool,
        limit: int,
        after_kind: IntegrationKind | None,
        after_integration_id: str | None,
    ) -> IntegrationPage:
        instant = _clock(as_of)
        rows = self.connection.execute(
            _INTEGRATION_LIST_SQL,
            (
                self.tenant_id,
                self.tenant_id,
                instant,
                instant,
                self.tenant_id,
                instant,
                self.tenant_id,
                include_inactive,
                after_kind,
                after_kind,
                after_kind,
                after_integration_id,
                limit + 1,
            ),
        ).fetchall()
        items = tuple(self._integration(row) for row in rows[:limit])
        if len(rows) <= limit or not items:
            return IntegrationPage(items)
        return IntegrationPage(items, items[-1].kind, items[-1].id)

    def _integration_row(self, kind: IntegrationKind, integration_id: str, as_of: datetime) -> Any | None:
        if kind == "federation_link":
            provider, separator, user_id = integration_id.partition(":")
            if not separator or not provider or not user_id:
                raise SecurityGovernanceError("integration_identifier_invalid", "Federation link id is invalid.")
            return self.connection.execute(
                """SELECT 'federation_link' AS kind,provider_id || ':' || user_id AS integration_id,
                          CASE WHEN disabled_at IS NULL THEN 'active' ELSE 'disabled' END AS status,
                          (1+CASE WHEN disabled_at IS NULL THEN 0 ELSE 1 END)::bigint AS lifecycle_version,
                          0::bigint AS credential_count,0::bigint AS active_credential_count,
                          linked_at AS created_at,NULL::timestamptz AS expires_at,NULL::timestamptz AS last_used_at,
                          provider_id AS scope_material,disabled_by AS disabled_actor,disabled_at
                     FROM reconforge.federation_identity_links
                    WHERE tenant_id=%s AND provider_id=%s AND user_id=%s
                    FOR UPDATE""",
                (self.tenant_id, provider, user_id),
            ).fetchone()
        if kind == "notification_route":
            route_id, separator, version_text = integration_id.rpartition(":")
            if not separator or not version_text.isdecimal() or int(version_text) < 1:
                raise SecurityGovernanceError("integration_identifier_invalid", "Notification route id is invalid.")
            return self.connection.execute(
                """SELECT 'notification_route' AS kind,route_id || ':' || route_version::text AS integration_id,
                          CASE WHEN enabled THEN 'active' ELSE 'disabled' END AS status,
                          route_version::bigint AS lifecycle_version,0::bigint AS credential_count,
                          0::bigint AS active_credential_count,created_at,NULL::timestamptz AS expires_at,
                          NULL::timestamptz AS last_used_at,
                          workspace_id || ':' || entity_id || ':' || channel AS scope_material,
                          NULL::text AS disabled_actor,
                          CASE WHEN enabled THEN NULL::timestamptz ELSE created_at END AS disabled_at
                     FROM reconforge.notification_routes
                    WHERE tenant_id=%s AND route_id=%s AND route_version=%s
                    FOR UPDATE""",
                (self.tenant_id, route_id, int(version_text)),
            ).fetchone()
        if kind == "scim_credential":
            return self.connection.execute(
                """SELECT 'scim_credential' AS kind,id AS integration_id,
                          CASE WHEN revoked_at IS NOT NULL THEN 'disabled'
                               WHEN expires_at<=%s THEN 'expired' ELSE 'active' END AS status,
                          (1+CASE WHEN revoked_at IS NULL THEN 0 ELSE 1 END)::bigint AS lifecycle_version,
                          1::bigint AS credential_count,
                          CASE WHEN revoked_at IS NULL AND expires_at>%s THEN 1 ELSE 0 END::bigint
                            AS active_credential_count,
                          created_at,expires_at,last_used_at,
                          provisioning_domain || ':' || client_id AS scope_material,
                          revoked_by AS disabled_actor,revoked_at AS disabled_at
                     FROM reconforge.scim_credentials WHERE tenant_id=%s AND id=%s
                     FOR UPDATE""",
                (as_of, as_of, self.tenant_id, integration_id),
            ).fetchone()
        return self.connection.execute(
            """SELECT 'service_account' AS kind,a.id AS integration_id,
                      CASE WHEN a.enabled THEN 'active' ELSE 'disabled' END AS status,
                      a.version::bigint AS lifecycle_version,
                      (SELECT count(*) FROM reconforge.service_account_credentials c
                        WHERE c.tenant_id=a.tenant_id AND c.service_account_id=a.id) AS credential_count,
                      (SELECT count(*) FROM reconforge.service_account_credentials c
                        WHERE c.tenant_id=a.tenant_id AND c.service_account_id=a.id
                          AND c.revoked_at IS NULL AND c.expires_at>%s) AS active_credential_count,
                      a.created_at,NULL::timestamptz AS expires_at,
                      (SELECT max(c.last_used_at) FROM reconforge.service_account_credentials c
                        WHERE c.tenant_id=a.tenant_id AND c.service_account_id=a.id) AS last_used_at,
                      a.name AS scope_material,NULL::text AS disabled_actor,
                      CASE WHEN a.enabled THEN NULL::timestamptz ELSE a.updated_at END AS disabled_at
                 FROM reconforge.service_accounts a WHERE a.tenant_id=%s AND a.id=%s
                 FOR UPDATE OF a""",
            (as_of, self.tenant_id, integration_id),
        ).fetchone()

    def disable_integration(
        self,
        *,
        actor_user_id: str,
        kind: IntegrationKind,
        integration_id: str,
        expected_state_digest: str,
        reason_code: str,
        as_of: datetime,
    ) -> IntegrationDisableChange:
        instant = _clock(as_of)
        target = _identifier(integration_id, "integration_id")
        self._lock()
        actor = self._actor(actor_user_id)
        row = self._integration_row(kind, target, instant)
        if row is None:
            raise SecurityGovernanceError("integration_not_found", "Integration was not found.")
        before = self._integration(row)
        if before.state_digest != expected_state_digest:
            raise SecurityGovernanceError("integration_state_conflict", "Integration state digest does not match.")
        if before.status == "disabled":
            return IntegrationDisableChange(before, False, 0, None)

        revoked_credentials = 0
        if kind == "federation_link":
            provider, _, user_id = target.partition(":")
            self.connection.execute(
                """UPDATE reconforge.federation_identity_links
                      SET disabled_at=%s,disabled_by=%s
                    WHERE tenant_id=%s AND provider_id=%s AND user_id=%s AND disabled_at IS NULL""",
                (instant, actor, self.tenant_id, provider, user_id),
            )
            self.connection.execute(
                """INSERT INTO reconforge.federation_identity_events
                       (tenant_id,id,provider_id,user_id,action,outcome,actor_id,occurred_at)
                   VALUES (%s,%s,%s,%s,'DISABLED','ALLOWED',%s,%s)""",
                (self.tenant_id, f"fie-{uuid.uuid4().hex}", provider, user_id, actor, instant),
            )
        elif kind == "notification_route":
            route_id, _, version_text = target.rpartition(":")
            self.connection.execute(
                """UPDATE reconforge.notification_routes SET enabled=FALSE
                    WHERE tenant_id=%s AND route_id=%s AND route_version=%s AND enabled""",
                (self.tenant_id, route_id, int(version_text)),
            )
        elif kind == "scim_credential":
            changed = self.connection.execute(
                """UPDATE reconforge.scim_credentials SET revoked_at=%s,revoked_by=%s
                    WHERE tenant_id=%s AND id=%s AND revoked_at IS NULL RETURNING id""",
                (instant, actor, self.tenant_id, target),
            ).fetchone()
            revoked_credentials = 1 if changed is not None else 0
        else:
            self.connection.execute(
                """UPDATE reconforge.service_accounts
                      SET enabled=FALSE,version=version+1,updated_at=%s
                    WHERE tenant_id=%s AND id=%s AND enabled""",
                (instant, self.tenant_id, target),
            )
            revoked = self.connection.execute(
                """UPDATE reconforge.service_account_credentials
                      SET revoked_at=%s,revoked_by=%s
                    WHERE tenant_id=%s AND service_account_id=%s AND revoked_at IS NULL
                    RETURNING id""",
                (instant, actor, self.tenant_id, target),
            ).fetchall()
            revoked_credentials = len(revoked)
            self.connection.execute(
                """INSERT INTO reconforge.service_account_events
                       (tenant_id,id,service_account_id,actor_id,action,outcome,occurred_at)
                   VALUES (%s,%s,%s,%s,'DISABLE','ALLOWED',%s)""",
                (self.tenant_id, f"sae-{uuid.uuid4().hex}", target, actor, instant),
            )

        after_row = self._integration_row(kind, target, instant)
        if after_row is None:
            raise SecurityGovernanceError("integration_not_found", "Integration disappeared during mutation.")
        after = self._integration(after_row)
        if after.status != "disabled":
            raise SecurityGovernanceError("integration_disable_failed", "Integration did not become disabled.")
        audit = PostgresAuditEventRepository(self.connection, self.tenant_id).append(
            actor_label=actor,
            actor_user_id=actor,
            object_type=f"integration.{kind}",
            object_id=target,
            action="security.integration.disabled",
            before_hash=before.state_digest,
            after_hash=after.state_digest,
            metadata={
                "integration_kind": kind,
                "reason_code": reason_code,
                "revoked_credentials": revoked_credentials,
                "schema_version": 1,
            },
        )
        return IntegrationDisableChange(after, True, revoked_credentials, audit.id)

    def _policy_row(self, policy_id: str) -> Any | None:
        return self.connection.execute(
            """SELECT id,name,description,data_classification,duration_days,active,lifecycle_version,
                      created_at,updated_at,retired_at,retired_by,created_by
                 FROM reconforge.retention_policies WHERE tenant_id=%s AND id=%s
                 FOR UPDATE""",
            (self.tenant_id, policy_id),
        ).fetchone()

    def list_retention_policies(
        self,
        *,
        include_retired: bool,
        limit: int,
        after_name: str | None,
        after_policy_id: str | None,
    ) -> RetentionPolicyPage:
        rows = self.connection.execute(
            """SELECT id,name,description,data_classification,duration_days,active,lifecycle_version,
                      created_at,updated_at,retired_at,retired_by,created_by
                 FROM reconforge.retention_policies
                WHERE tenant_id=%s AND (%s OR active)
                  AND (%s::text IS NULL OR (name,id)>(%s::text,%s::text))
                ORDER BY name,id LIMIT %s""",
            (
                self.tenant_id,
                include_retired,
                after_name,
                after_name,
                after_policy_id,
                limit + 1,
            ),
        ).fetchall()
        items = tuple(self._policy(row) for row in rows[:limit])
        if len(rows) <= limit or not items:
            return RetentionPolicyPage(items)
        return RetentionPolicyPage(items, items[-1].name, items[-1].id)

    def create_retention_policy(
        self,
        *,
        actor_user_id: str,
        name: str,
        description: str,
        data_classification: DataClassification,
        duration_days: int,
        as_of: datetime,
    ) -> RetentionPolicyChange:
        instant = _clock(as_of)
        self._lock()
        actor = self._actor(actor_user_id)
        if self.connection.execute(
            "SELECT 1 FROM reconforge.retention_policies WHERE tenant_id=%s AND name=%s",
            (self.tenant_id, name),
        ).fetchone() is not None:
            raise SecurityGovernanceError("retention_policy_exists", "Retention policy name already exists.")
        policy_id = f"rtp-{uuid.uuid4().hex}"
        self.connection.execute(
            """INSERT INTO reconforge.retention_policies
                   (tenant_id,id,name,description,data_classification,duration_days,created_by,created_at,updated_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                self.tenant_id,
                policy_id,
                name,
                description,
                data_classification,
                duration_days,
                actor,
                instant,
                instant,
            ),
        )
        row = self._policy_row(policy_id)
        if row is None:
            raise SecurityGovernanceError("retention_policy_not_found", "Retention policy was not returned.")
        policy = self._policy(row)
        audit = PostgresAuditEventRepository(self.connection, self.tenant_id).append(
            actor_label=actor,
            actor_user_id=actor,
            object_type="retention_policy",
            object_id=policy.id,
            action="security.retention_policy.created",
            before_hash=None,
            after_hash=policy.state_digest,
            metadata={"data_classification": data_classification, "duration_days": duration_days, "schema_version": 1},
        )
        return RetentionPolicyChange(policy, True, audit.id)

    def update_retention_policy(
        self,
        *,
        actor_user_id: str,
        policy_id: str,
        description: str | None,
        data_classification: DataClassification | None,
        duration_days: int | None,
        active: bool | None,
        expected_lifecycle_version: int,
        reason_code: str,
        as_of: datetime,
    ) -> RetentionPolicyChange:
        instant = _clock(as_of)
        target = _identifier(policy_id, "policy_id")
        self._lock()
        actor = self._actor(actor_user_id)
        row = self._policy_row(target)
        if row is None:
            raise SecurityGovernanceError("retention_policy_not_found", "Retention policy was not found.")
        before = self._policy(row)
        if before.lifecycle_version != expected_lifecycle_version:
            raise SecurityGovernanceError(
                "retention_policy_version_conflict", "Retention policy lifecycle version does not match."
            )
        next_description = before.description if description is None else description
        next_classification = before.data_classification if data_classification is None else data_classification
        next_duration = before.duration_days if duration_days is None else duration_days
        next_active = before.active if active is None else active
        if (
            next_description,
            next_classification,
            next_duration,
            next_active,
        ) == (before.description, before.data_classification, before.duration_days, before.active):
            return RetentionPolicyChange(before, False, None)
        updated = self.connection.execute(
            """UPDATE reconforge.retention_policies
                  SET description=%s,data_classification=%s,duration_days=%s,active=%s,
                      lifecycle_version=lifecycle_version+1,updated_at=%s,
                      retired_at=CASE WHEN %s THEN NULL ELSE %s END,
                      retired_by=CASE WHEN %s THEN NULL ELSE %s END,
                      retirement_reason_code=CASE WHEN %s THEN NULL ELSE %s END
                WHERE tenant_id=%s AND id=%s AND lifecycle_version=%s RETURNING id""",
            (
                next_description,
                next_classification,
                next_duration,
                next_active,
                instant,
                next_active,
                instant,
                next_active,
                actor,
                next_active,
                reason_code,
                self.tenant_id,
                target,
                expected_lifecycle_version,
            ),
        ).fetchone()
        if updated is None:
            raise SecurityGovernanceError(
                "retention_policy_version_conflict", "Retention policy lifecycle version does not match."
            )
        after_row = self._policy_row(target)
        if after_row is None:
            raise SecurityGovernanceError("retention_policy_not_found", "Retention policy disappeared.")
        after = self._policy(after_row)
        audit = PostgresAuditEventRepository(self.connection, self.tenant_id).append(
            actor_label=actor,
            actor_user_id=actor,
            object_type="retention_policy",
            object_id=target,
            action="security.retention_policy.updated",
            before_hash=before.state_digest,
            after_hash=after.state_digest,
            metadata={"active": after.active, "reason_code": reason_code, "schema_version": 1},
        )
        return RetentionPolicyChange(after, True, audit.id)

    def apply_retention_policy(
        self,
        *,
        actor_user_id: str,
        policy_id: str,
        evidence_id: str,
        expected_retention_version: int,
        reason_code: str,
        as_of: datetime,
    ) -> EvidenceRetentionChange:
        instant = _clock(as_of)
        policy_target = _identifier(policy_id, "policy_id")
        evidence_target = _identifier(evidence_id, "evidence_id")
        self._lock()
        actor = self._actor(actor_user_id)
        policy_row = self._policy_row(policy_target)
        if policy_row is None:
            raise SecurityGovernanceError("retention_policy_not_found", "Retention policy was not found.")
        policy = self._policy(policy_row)
        if not policy.active:
            raise SecurityGovernanceError("retention_policy_retired", "A retired retention policy cannot be applied.")
        existing = self.connection.execute(
            """SELECT evidence_retention_version,previous_retention_until,policy_retention_until,
                      effective_retention_until,id
                 FROM reconforge.evidence_retention_assignments
                WHERE tenant_id=%s AND evidence_id=%s AND policy_id=%s AND policy_lifecycle_version=%s""",
            (self.tenant_id, evidence_target, policy_target, policy.lifecycle_version),
        ).fetchone()
        if existing is not None:
            previous = _utc_text(_value(existing, "previous_retention_until", 1))
            policy_until = _utc_text(_value(existing, "policy_retention_until", 2))
            effective = _utc_text(_value(existing, "effective_retention_until", 3))
            version = int(_value(existing, "evidence_retention_version", 0))
            state = {
                "effective_retention_until": effective,
                "evidence_id": evidence_target,
                "policy_id": policy_target,
                "policy_lifecycle_version": policy.lifecycle_version,
                "policy_retention_until": policy_until,
                "retention_version": version,
            }
            return EvidenceRetentionChange(
                evidence_target,
                policy_target,
                policy.lifecycle_version,
                version,
                previous,
                str(policy_until),
                str(effective),
                False,
                False,
                None,
                _digest(state),
            )
        evidence = self.connection.execute(
            """SELECT retention_until,retention_version FROM reconforge.evidence_registry
                WHERE tenant_id=%s AND id=%s FOR UPDATE""",
            (self.tenant_id, evidence_target),
        ).fetchone()
        if evidence is None:
            raise SecurityGovernanceError("retention_evidence_not_found", "Evidence record was not found.")
        previous_value = _value(evidence, "retention_until", 0)
        previous_text = _utc_text(previous_value)
        current_version = int(_value(evidence, "retention_version", 1))
        if current_version != expected_retention_version:
            raise SecurityGovernanceError(
                "retention_version_conflict", "Evidence retention version does not match."
            )
        policy_until_value = instant + timedelta(days=policy.duration_days)
        previous_datetime = (
            None
            if previous_text is None
            else datetime.fromisoformat(previous_text.replace("Z", "+00:00")).astimezone(UTC)
        )
        effective_value = max(policy_until_value, previous_datetime) if previous_datetime else policy_until_value
        retention_extended = previous_datetime is None or policy_until_value > previous_datetime
        next_version = current_version + 1 if retention_extended else current_version
        if retention_extended:
            updated = self.connection.execute(
                """UPDATE reconforge.evidence_registry
                      SET retention_until=%s,retention_version=retention_version+1,updated_at=%s
                    WHERE tenant_id=%s AND id=%s AND retention_version=%s RETURNING retention_version""",
                (effective_value, instant, self.tenant_id, evidence_target, expected_retention_version),
            ).fetchone()
            if updated is None or int(_value(updated, "retention_version", 0)) != next_version:
                raise SecurityGovernanceError("retention_version_conflict", "Evidence retention update conflicted.")
        assignment_id = f"rta-{uuid.uuid4().hex}"
        self.connection.execute(
            """INSERT INTO reconforge.evidence_retention_assignments
                   (tenant_id,id,evidence_id,policy_id,policy_lifecycle_version,evidence_retention_version,
                    previous_retention_until,policy_retention_until,effective_retention_until,
                    assigned_by,assigned_at,reason_code)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                self.tenant_id,
                assignment_id,
                evidence_target,
                policy_target,
                policy.lifecycle_version,
                next_version,
                previous_datetime,
                policy_until_value,
                effective_value,
                actor,
                instant,
                reason_code,
            ),
        )
        policy_until_text = str(_utc_text(policy_until_value))
        effective_text = str(_utc_text(effective_value))
        state = {
            "effective_retention_until": effective_text,
            "evidence_id": evidence_target,
            "policy_id": policy_target,
            "policy_lifecycle_version": policy.lifecycle_version,
            "policy_retention_until": policy_until_text,
            "retention_version": next_version,
        }
        state_digest = _digest(state)
        audit = PostgresAuditEventRepository(self.connection, self.tenant_id).append(
            actor_label=actor,
            actor_user_id=actor,
            object_type="evidence_retention",
            object_id=evidence_target,
            action="security.retention_policy.applied",
            before_hash=None
            if previous_text is None
            else _digest({"evidence_id": evidence_target, "retention_until": previous_text}),
            after_hash=state_digest,
            metadata={
                "policy_id": policy_target,
                "policy_lifecycle_version": policy.lifecycle_version,
                "reason_code": reason_code,
                "retention_extended": retention_extended,
                "schema_version": 1,
            },
        )
        return EvidenceRetentionChange(
            evidence_target,
            policy_target,
            policy.lifecycle_version,
            next_version,
            previous_text,
            policy_until_text,
            effective_text,
            retention_extended,
            True,
            audit.id,
            state_digest,
        )
