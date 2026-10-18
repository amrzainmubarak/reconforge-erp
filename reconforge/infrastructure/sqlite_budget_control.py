"""SQLite owner for serialized budget effects and atomically linked evidence."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from uuid import uuid4

from reconforge.audit import append_audit_event
from reconforge.auth import LocalAuthService
from reconforge.domain.budget_control import BudgetControlError, BudgetScope
from reconforge.infrastructure.budget_control_repository import BudgetControlRepositoryBase, BudgetCurrentAuthority
from reconforge.platform.common import append_outbox_event


class SQLiteBudgetControlRepository(BudgetControlRepositoryBase):
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        self.tenant_id = None

    @contextmanager
    def _transaction(self, *, write: bool) -> Iterator[None]:
        if self.connection.in_transaction:
            raise BudgetControlError("Budget commands require an idle connection and one transaction owner.")
        try:
            self.connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield
            self.connection.commit()
        except BaseException as exc:
            self.connection.rollback()
            if isinstance(exc, sqlite3.DatabaseError):
                raise BudgetControlError("Budget command conflicts with current retained state; reload before retrying.") from exc
            raise

    def _execute(self, query: str, parameters: tuple[Any, ...] = ()) -> Any:
        return self.connection.execute(query, parameters)

    def _identity(self, user_id: str, username: str) -> bool:
        return self.connection.execute("SELECT 1 FROM users WHERE id=? AND username=? AND disabled=0", (user_id, username)).fetchone() is not None

    def _authority(self, scope: BudgetScope, user_id: str, username: str) -> BudgetCurrentAuthority | None:
        """Read current local RBAC under the command's BEGIN IMMEDIATE owner.

        Community SQLite has no separate per-scope grant relation: a user with
        the current local role may access canonical scopes in that local file.
        The explicit values still make the central policy engine validate the
        requested hierarchy instead of treating an empty grant set as ambient
        authority.  Server deployments use the durable PostgreSQL grant table.
        """

        permissions = frozenset(LocalAuthService(self.connection).roles.user_permissions(username))
        return BudgetCurrentAuthority(
            permissions=permissions,
            workspace_ids=frozenset({scope.workspace_id}),
            organization_ids=frozenset({scope.organization_id}),
            legal_entity_ids=frozenset({scope.legal_entity_id}),
        )

    def _canonical(self, scope: BudgetScope, *, period_id: str | None = None, currency_code: str | None = None) -> dict[str, Any]:
        row = self.connection.execute("SELECT 1 FROM organizations o JOIN legal_entities e ON e.organization_id=o.id "
            "WHERE o.id=? AND o.workspace_id=? AND e.id=? AND o.active=1 AND e.active=1",
            (scope.organization_id, scope.workspace_id, scope.legal_entity_id)).fetchone()
        if row is None:
            raise BudgetControlError("Budget canonical organization/entity/workspace is absent or inactive.")
        result: dict[str, Any] = {}
        if period_id is not None:
            row = self.connection.execute("SELECT start_date,end_date FROM periods WHERE id=? AND workspace_id=? AND status='Open'", (period_id, scope.workspace_id)).fetchone()
            if row is None:
                raise BudgetControlError("Budget fiscal period must be open in the selected workspace.")
            result.update(dict(row))
        if currency_code is not None:
            row = self.connection.execute("SELECT minor_units FROM currencies WHERE code=? AND active=1", (currency_code,)).fetchone()
            if row is None:
                raise BudgetControlError("Budget requires an active canonical currency.")
            result.update(dict(row))
        return result

    def _event(self, scope: BudgetScope, budget_id: str, action: str, actor: Any, metadata: dict[str, Any]) -> tuple[str, str]:
        metadata = {**vars(scope), **metadata, "schema_version": 1}
        audit = append_audit_event(self.connection, actor_user_id=actor.id, actor_label=actor.username,
            object_type="budget_control", object_id=budget_id, action=action, metadata=metadata)
        event_id = "OBX-" + uuid4().hex
        append_outbox_event(self.connection, event_id=event_id, event_type=action, aggregate_type="budget_control",
            aggregate_id=budget_id, payload={**metadata, "audit_event_id": audit.id})
        return audit.id, event_id
