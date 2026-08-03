"""Tenant-RLS PostgreSQL snapshot loader for policy conflict analysis."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from reconforge.auth.policy_analysis import (
    PolicyAnalysisError,
    PolicyAnalysisRequest,
    PolicyGrant,
    PolicyScope,
)
from reconforge.infrastructure.postgres import PostgresConfigurationError, normalize_scope_id


class PostgresPolicyAnalysisError(PolicyAnalysisError):
    """Disclosure-safe policy snapshot failure."""


def _value(row: Any, key: str, index: int) -> Any:
    return row.get(key) if isinstance(row, Mapping) else row[index]


def _scope(value: str, field_name: str) -> str:
    try:
        return normalize_scope_id(value, field_name=field_name)
    except PostgresConfigurationError as exc:
        raise PostgresPolicyAnalysisError(f"{field_name} is invalid.") from exc


def _timestamp(value: datetime, field_name: str) -> str:
    if value.tzinfo is None or value.utcoffset() is None or value.microsecond:
        raise PostgresPolicyAnalysisError(f"{field_name} must be timezone-aware and whole-second.")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class PostgresPolicyAnalysisRepository:
    """Read active effective grants under the caller's transaction-local tenant RLS."""

    connection: Any
    tenant_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "tenant_id", _scope(self.tenant_id, "tenant_id"))

    def _require_active_user(self, user_id: str, field_name: str) -> str:
        actor = _scope(user_id, field_name)
        row = self.connection.execute(
            """SELECT 1 FROM reconforge.identity_users
                WHERE tenant_id=%s AND id=%s AND NOT disabled""",
            (self.tenant_id, actor),
        ).fetchone()
        if row is None:
            raise PostgresPolicyAnalysisError(f"{field_name} is unavailable.")
        return actor

    def load_request(
        self,
        *,
        policy_id: str,
        policy_version: str,
        require_scoped_privileged: bool,
        prepared_by: str,
        prepared_at: datetime,
        approved_by: str,
        approved_at: str,
    ) -> PolicyAnalysisRequest:
        prepared = self._require_active_user(prepared_by, "prepared_by")
        approved = self._require_active_user(approved_by, "approved_by")
        user_rows = self.connection.execute(
            """SELECT ur.user_id AS principal_id, ur.role_id, r.name AS role_name,
                      rp.permission_name
                 FROM reconforge.identity_user_roles ur
                 JOIN reconforge.identity_users u
                   ON u.tenant_id=ur.tenant_id AND u.id=ur.user_id AND NOT u.disabled
                 JOIN reconforge.identity_roles r
                   ON r.tenant_id=ur.tenant_id AND r.id=ur.role_id AND r.active
                 JOIN reconforge.identity_role_permissions rp
                   ON rp.tenant_id=r.tenant_id AND rp.role_id=r.id AND rp.active
                WHERE ur.tenant_id=%s AND ur.active
                ORDER BY ur.user_id, ur.role_id, rp.permission_name""",
            (self.tenant_id,),
        ).fetchall()
        service_rows = self.connection.execute(
            """SELECT sa.id AS principal_id, sap.permission_name
                 FROM reconforge.service_accounts sa
                 JOIN reconforge.service_account_permissions sap
                   ON sap.tenant_id=sa.tenant_id AND sap.service_account_id=sa.id
                WHERE sa.tenant_id=%s AND sa.enabled
                ORDER BY sa.id, sap.permission_name""",
            (self.tenant_id,),
        ).fetchall()

        user_permissions: dict[tuple[str, str, str], set[str]] = defaultdict(set)
        for row in user_rows:
            principal = _scope(str(_value(row, "principal_id", 0)), "principal_id")
            role_id = _scope(str(_value(row, "role_id", 1)), "role_id")
            role_name = _scope(str(_value(row, "role_name", 2)), "role_name")
            permission = str(_value(row, "permission_name", 3)).strip()
            user_permissions[(principal, role_id, role_name)].add(permission)

        grants: list[PolicyGrant] = []
        for (principal, role_id, _role_name), permissions in sorted(user_permissions.items()):
            grants.append(
                PolicyGrant(
                    grant_id=f"role-grant:{principal}:{role_id}",
                    principal_id=principal,
                    principal_type="user",
                    role_id=role_id,
                    scope=PolicyScope(tenant_id=self.tenant_id),
                    permissions=frozenset(permissions),
                )
            )

        service_permissions: dict[str, set[str]] = defaultdict(set)
        for row in service_rows:
            principal = _scope(str(_value(row, "principal_id", 0)), "service_account_id")
            service_permissions[principal].add(str(_value(row, "permission_name", 1)).strip())
        for principal, permissions in sorted(service_permissions.items()):
            grants.append(
                PolicyGrant(
                    grant_id=f"service-grant:{principal}",
                    principal_id=principal,
                    principal_type="service_account",
                    role_id=f"service-role:{principal}",
                    scope=PolicyScope(tenant_id=self.tenant_id),
                    permissions=frozenset(permissions),
                )
            )

        try:
            return PolicyAnalysisRequest(
                policy_id=policy_id,
                policy_version=policy_version,
                grants=tuple(grants),
                require_scoped_privileged=require_scoped_privileged,
                prepared_by=prepared,
                prepared_at=_timestamp(prepared_at, "prepared_at"),
                approved_by=approved,
                approved_at=approved_at,
            )
        except (TypeError, ValueError) as exc:
            raise PostgresPolicyAnalysisError("Policy snapshot is invalid.") from exc


__all__ = ["PostgresPolicyAnalysisError", "PostgresPolicyAnalysisRepository"]
