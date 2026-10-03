"""PostgreSQL owner with real row locks, tenant RLS and current authority."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from uuid import uuid4

from reconforge.domain.budget_control import BudgetControlError, BudgetScope
from reconforge.infrastructure.budget_control_repository import BudgetControlRepositoryBase, BudgetCurrentAuthority
from reconforge.infrastructure.postgres import validate_tenant_id
from reconforge.infrastructure.postgres_domain import PostgresAuditEventRepository
from reconforge.infrastructure.postgres_repository_scope import ensure_repository_tenant_scope


class PostgresBudgetControlRepository(BudgetControlRepositoryBase):
    tenant_id: str

    def __init__(self, connection: Any, tenant_id: str) -> None:
        self.connection = connection
        self.tenant_id = validate_tenant_id(tenant_id)

    @contextmanager
    def _transaction(self, *, write: bool) -> Iterator[None]:
        try:
            with self.connection.transaction():
                ensure_repository_tenant_scope(self.connection, self.tenant_id)
                if write and self.connection.execute("SHOW transaction_isolation").fetchone()["transaction_isolation"] != "read committed":
                    raise BudgetControlError("Budget mutations require READ COMMITTED isolation.")
                yield
        except Exception as exc:
            if getattr(exc, "sqlstate", None) in {"23503", "23505", "23514", "40001", "40P01"}:
                raise BudgetControlError("Budget command conflicts with current retained state; reload before retrying.") from exc
            raise

    def _execute(self, query: str, parameters: tuple[Any, ...] = ()) -> Any:
        statement = re.sub(r"\b(budget_envelopes|budget_commitment_events|budget_commands)\b", r"reconforge.\1", query)
        return self.connection.execute(statement.replace("?", "%s"), parameters)

    def _identity(self, user_id: str, username: str) -> bool:
        return self.connection.execute("SELECT 1 FROM reconforge.identity_users WHERE tenant_id=%s AND id=%s AND username=%s AND NOT disabled FOR SHARE", (self.tenant_id, user_id, username)).fetchone() is not None

    def _authority(self, scope: BudgetScope, user_id: str, username: str) -> BudgetCurrentAuthority | None:
        permission_rows = self.connection.execute(
            "SELECT p.permission_name FROM reconforge.identity_user_roles a "
            "JOIN reconforge.identity_role_permissions p ON p.tenant_id=a.tenant_id AND p.role_id=a.role_id "
            "JOIN reconforge.identity_roles r ON r.tenant_id=a.tenant_id AND r.id=a.role_id "
            "WHERE a.tenant_id=%s AND a.user_id=%s AND a.active AND p.active AND r.active "
            "ORDER BY p.permission_name FOR SHARE OF a,p,r",
            (self.tenant_id, user_id),
        ).fetchall()
        rows = self.connection.execute("SELECT scope_type,scope_id FROM reconforge.principal_scope_grants WHERE tenant_id=%s AND principal_type='user' AND principal_id=%s AND revoked_at IS NULL FOR SHARE", (self.tenant_id, user_id)).fetchall()
        grouped: dict[str, set[str]] = {"workspace": set(), "organization": set(), "legal_entity": set()}
        for row in rows:
            grouped[str(row["scope_type"])].add(str(row["scope_id"]))
        return BudgetCurrentAuthority(
            permissions=frozenset(str(row["permission_name"]) for row in permission_rows),
            workspace_ids=frozenset(grouped["workspace"]),
            organization_ids=frozenset(grouped["organization"]),
            legal_entity_ids=frozenset(grouped["legal_entity"]),
        )

    def _canonical(self, scope: BudgetScope, *, period_id: str | None = None, currency_code: str | None = None) -> dict[str, Any]:
        row = self.connection.execute("SELECT 1 FROM reconforge.organizations o JOIN reconforge.legal_entities e "
            "ON e.tenant_id=o.tenant_id AND e.organization_id=o.id WHERE o.tenant_id=%s AND o.id=%s "
            "AND o.application_workspace_id=%s AND e.id=%s AND o.active AND e.active FOR SHARE OF o,e",
            (self.tenant_id, scope.organization_id, scope.workspace_id, scope.legal_entity_id)).fetchone()
        if row is None:
            raise BudgetControlError("Budget canonical organization/entity/workspace is absent or inactive.")
        result: dict[str, Any] = {}
        if period_id is not None:
            row = self.connection.execute("SELECT start_date,end_date FROM reconforge.fiscal_periods WHERE tenant_id=%s "
                "AND id=%s AND application_workspace_id=%s AND status='Open' FOR SHARE", (self.tenant_id, period_id, scope.workspace_id)).fetchone()
            if row is None:
                raise BudgetControlError("Budget fiscal period must be open in the selected workspace.")
            result.update(dict(row))
        if currency_code is not None:
            row = self.connection.execute("SELECT minor_units FROM reconforge.currencies WHERE tenant_id=%s AND code=%s AND active FOR SHARE", (self.tenant_id, currency_code)).fetchone()
            if row is None:
                raise BudgetControlError("Budget requires an active canonical currency.")
            result.update(dict(row))
        return result

    def _event(self, scope: BudgetScope, budget_id: str, action: str, actor: Any, metadata: dict[str, Any]) -> tuple[str, str]:
        metadata = {**vars(scope), **metadata, "schema_version": 1}
        audit = PostgresAuditEventRepository(self.connection, self.tenant_id).append(actor_user_id=actor.id,
            actor_label=actor.username, object_type="budget_control", object_id=budget_id, action=action, metadata=metadata)
        event_id = "OBX-" + uuid4().hex
        self.connection.execute("INSERT INTO reconforge.outbox_events (tenant_id,event_id,event_type,aggregate_type,aggregate_id,workspace_id,organization_id,legal_entity_id,payload) VALUES (%s,%s,%s,'budget_control',%s,%s,%s,%s,%s::jsonb)",
            (self.tenant_id, event_id, action, budget_id, scope.workspace_id, scope.organization_id, scope.legal_entity_id, json.dumps({**metadata, "audit_event_id": audit.id})))
        return audit.id, event_id
