"""Tenant-scoped PostgreSQL projection for the administration security overview."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from reconforge.application.security_center import SecurityCenterCounts
from reconforge.infrastructure.postgres import PostgresConfigurationError, normalize_scope_id


class PostgresSecurityCenterError(ValueError):
    """Raised when the security overview projection cannot be read safely."""


_COUNTS_SQL = """
WITH parameters AS (
  SELECT %s::text AS tenant_id, %s::timestamptz AS as_of
)
SELECT
  (SELECT count(*) FROM reconforge.identity_users u, parameters p WHERE u.tenant_id=p.tenant_id),
  (SELECT count(*) FROM reconforge.identity_users u, parameters p WHERE u.tenant_id=p.tenant_id AND NOT u.disabled),
  (SELECT count(*) FROM reconforge.identity_users u, parameters p WHERE u.tenant_id=p.tenant_id AND u.disabled),
  (SELECT count(*) FROM reconforge.identity_users u, parameters p
    WHERE u.tenant_id=p.tenant_id AND NOT u.disabled AND u.locked_until>p.as_of),
  (SELECT count(*) FROM reconforge.identity_users u, parameters p
    WHERE u.tenant_id=p.tenant_id AND NOT u.disabled AND NOT EXISTS (
      SELECT 1 FROM reconforge.identity_user_roles ur
      JOIN reconforge.identity_roles r ON r.tenant_id=ur.tenant_id AND r.id=ur.role_id
      WHERE ur.tenant_id=u.tenant_id AND ur.user_id=u.id AND ur.active AND r.active)),
  (SELECT count(*) FROM reconforge.identity_roles r, parameters p
    WHERE r.tenant_id=p.tenant_id AND r.active),
  (SELECT count(*) FROM reconforge.identity_permissions x, parameters p WHERE x.tenant_id=p.tenant_id),
  (SELECT count(*) FROM reconforge.identity_role_permissions rp
    JOIN reconforge.identity_roles r ON r.tenant_id=rp.tenant_id AND r.id=rp.role_id, parameters p
    WHERE rp.tenant_id=p.tenant_id AND rp.active AND r.active),
  (SELECT count(*) FROM reconforge.identity_sessions s, parameters p
    WHERE s.tenant_id=p.tenant_id AND s.revoked_at IS NULL AND s.expires_at>p.as_of),
  (SELECT count(*) FROM reconforge.identity_sessions s, parameters p
    WHERE s.tenant_id=p.tenant_id AND s.revoked_at IS NOT NULL),
  (SELECT count(*) FROM reconforge.identity_sessions s, parameters p
    WHERE s.tenant_id=p.tenant_id AND s.revoked_at IS NULL AND s.expires_at<=p.as_of),
  (SELECT count(*) FROM reconforge.identity_step_up_assertions a
    JOIN reconforge.identity_sessions s ON s.tenant_id=a.tenant_id AND s.id=a.session_id, parameters p
    WHERE a.tenant_id=p.tenant_id AND a.expires_at>p.as_of
      AND s.revoked_at IS NULL AND s.expires_at>p.as_of),
  (SELECT count(*) FROM reconforge.identity_webauthn_credentials c
    JOIN reconforge.identity_users u ON u.tenant_id=c.tenant_id AND u.id=c.user_id, parameters p
    WHERE c.tenant_id=p.tenant_id AND c.disabled_at IS NULL AND NOT u.disabled),
  (SELECT count(DISTINCT c.user_id) FROM reconforge.identity_webauthn_credentials c
    JOIN reconforge.identity_users u ON u.tenant_id=c.tenant_id AND u.id=c.user_id, parameters p
    WHERE c.tenant_id=p.tenant_id AND c.disabled_at IS NULL AND NOT u.disabled),
  (SELECT count(DISTINCT l.provider_id) FROM reconforge.federation_identity_links l, parameters p
    WHERE l.tenant_id=p.tenant_id AND l.disabled_at IS NULL),
  (SELECT count(*) FROM reconforge.federation_identity_links l, parameters p
    WHERE l.tenant_id=p.tenant_id AND l.disabled_at IS NULL),
  (SELECT count(*) FROM reconforge.federation_identity_links l, parameters p
    WHERE l.tenant_id=p.tenant_id AND l.disabled_at IS NOT NULL),
  (SELECT count(*) FROM (
      SELECT u.provisioning_domain FROM reconforge.scim_users u, parameters p WHERE u.tenant_id=p.tenant_id
      UNION
      SELECT c.provisioning_domain FROM reconforge.scim_credentials c, parameters p WHERE c.tenant_id=p.tenant_id
    ) domains),
  (SELECT count(*) FROM reconforge.scim_users u, parameters p
    WHERE u.tenant_id=p.tenant_id AND u.active),
  (SELECT count(*) FROM reconforge.scim_credentials c, parameters p
    WHERE c.tenant_id=p.tenant_id AND c.revoked_at IS NULL AND c.expires_at>p.as_of),
  (SELECT count(*) FROM reconforge.service_accounts a, parameters p
    WHERE a.tenant_id=p.tenant_id AND a.enabled),
  (SELECT count(*) FROM reconforge.service_account_credentials c
    JOIN reconforge.service_accounts a ON a.tenant_id=c.tenant_id AND a.id=c.service_account_id, parameters p
    WHERE c.tenant_id=p.tenant_id AND a.enabled AND c.revoked_at IS NULL AND c.expires_at>p.as_of),
  (SELECT count(*) FROM reconforge.notification_routes r, parameters p
    WHERE r.tenant_id=p.tenant_id AND r.enabled),
  (SELECT count(*) FROM reconforge.principal_scope_grants g, parameters p
    WHERE g.tenant_id=p.tenant_id AND g.revoked_at IS NULL),
  (SELECT count(*) FROM reconforge.emergency_access_requests e, parameters p
    WHERE e.tenant_id=p.tenant_id AND e.status='Pending'),
  (SELECT count(*) FROM reconforge.emergency_access_requests e, parameters p
    WHERE e.tenant_id=p.tenant_id AND e.status='Active' AND e.expires_at>p.as_of),
  (SELECT count(*) FROM reconforge.emergency_access_requests e, parameters p
    WHERE e.tenant_id=p.tenant_id AND e.status='ReviewPending' AND e.review_due_at<p.as_of),
  (SELECT count(*) FROM reconforge.evidence_registry e, parameters p WHERE e.tenant_id=p.tenant_id),
  (SELECT count(*) FROM reconforge.evidence_registry e, parameters p
    WHERE e.tenant_id=p.tenant_id AND e.retention_until IS NOT NULL),
  (SELECT count(*) FROM reconforge.evidence_registry e, parameters p
    WHERE e.tenant_id=p.tenant_id AND e.retention_until IS NOT NULL AND e.retention_until<=p.as_of),
  (SELECT count(*) FROM reconforge.evidence_registry e, parameters p
    WHERE e.tenant_id=p.tenant_id AND e.verification_status='Unverified'),
  (SELECT count(*) FROM reconforge.evidence_registry e, parameters p
    WHERE e.tenant_id=p.tenant_id AND e.verification_status='Failed'),
  (SELECT count(*) FROM reconforge.audit_events a, parameters p WHERE a.tenant_id=p.tenant_id)
"""


def _integer(row: Any, index: int) -> int:
    value = row[index]
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise PostgresSecurityCenterError("Security overview returned an invalid aggregate.")
    return value


class PostgresSecurityCenterRepository:
    """Read one static, count-only projection beneath transaction-local tenant RLS."""

    def __init__(self, connection: Any) -> None:
        self.connection = connection

    def read_counts(self, *, tenant_id: str, as_of: datetime) -> SecurityCenterCounts:
        try:
            tenant = normalize_scope_id(tenant_id, field_name="tenant_id")
        except PostgresConfigurationError as exc:
            raise PostgresSecurityCenterError("tenant_id is invalid.") from exc
        if as_of.tzinfo is None or as_of.utcoffset() is None or as_of.microsecond:
            raise PostgresSecurityCenterError("as_of must be a timezone-aware whole-second timestamp.")
        row = self.connection.execute(_COUNTS_SQL, (tenant, as_of.astimezone(UTC))).fetchone()
        if row is None or len(row) != 33:
            raise PostgresSecurityCenterError("Security overview aggregate is unavailable.")
        values = [_integer(row, index) for index in range(33)]
        return SecurityCenterCounts(*values)
