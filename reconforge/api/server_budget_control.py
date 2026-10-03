"""Request-scoped PostgreSQL budget execution, with no local fallback."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from fastapi import Request

from reconforge.api.errors import APIError
from reconforge.api.server_identity import request_execution_scope
from reconforge.domain.budget_control import BudgetControlError, BudgetScope
from reconforge.infrastructure.postgres import PostgresConnectionFactory, PostgresTenantBoundary
from reconforge.infrastructure.postgres_budget_control import PostgresBudgetControlRepository
from reconforge.platform.common import ServerPrincipal, server_principal_context

T = TypeVar("T")


def server_budget_control_enabled(request: Request) -> bool:
    return isinstance(getattr(request.app.state, "postgres_budget_control_factory", None), PostgresConnectionFactory)


def execute_postgres_budget_control(request: Request, scope: BudgetScope, operation: Callable[[PostgresBudgetControlRepository], T]) -> T:
    factory = getattr(request.app.state, "postgres_budget_control_factory", None)
    if not isinstance(factory, PostgresConnectionFactory):
        raise APIError(status_code=503, code="budget_control_unavailable", message="Budget backend is unavailable.")
    selected = request_execution_scope(request)
    if (selected.workspace_id, selected.organization_id, selected.legal_entity_id) != (scope.workspace_id, scope.organization_id, scope.legal_entity_id):
        raise APIError(status_code=403, code="budget_scope_denied", message="Exact selected budget scope is not authorized.")
    principal = getattr(request.state, "server_principal", None)
    if not isinstance(principal, ServerPrincipal):
        raise APIError(status_code=401, code="auth_required", message="Authentication required.")
    try:
        with (
            PostgresTenantBoundary(factory).transaction(
                selected.tenant_id,
                workspace_id=scope.workspace_id,
                organization_id=scope.organization_id,
                legal_entity_id=scope.legal_entity_id,
            ) as connection,
            # Bind the same request identity while the repository locks and
            # rechecks its current stronger-authentication session on writes.
            server_principal_context(principal),
        ):
            return operation(
                PostgresBudgetControlRepository(
                    connection,
                    selected.tenant_id,
                    require_live_session_assurance=True,
                )
            )
    except (APIError, BudgetControlError):
        raise
    except Exception as exc:
        raise APIError(status_code=503, code="budget_control_unavailable", message="Budget backend is temporarily unavailable.") from exc
