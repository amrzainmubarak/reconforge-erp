"""Request-scoped PostgreSQL bank-statement evidence operations."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from fastapi import Request

from reconforge.api.errors import APIError
from reconforge.api.server_identity import request_execution_scope
from reconforge.infrastructure.postgres import (
    PostgresConfigurationError,
    PostgresConnectionFactory,
    PostgresTenantBoundary,
    PostgresUnavailableError,
)
from reconforge.infrastructure.postgres_bank_statement import (
    PostgresBankStatementPersistenceError,
    PostgresBankStatementRepository,
)

T = TypeVar("T")
BankStatementOperation = Callable[[PostgresBankStatementRepository, str, str], T]


def get_postgres_bank_statement_factory(request: Request) -> PostgresConnectionFactory | None:
    value = getattr(request.app.state, "postgres_bank_statement_factory", None)
    return value if isinstance(value, PostgresConnectionFactory) else None


def server_bank_statement_enabled(request: Request) -> bool:
    return get_postgres_bank_statement_factory(request) is not None


def execute_postgres_bank_statement(request: Request, operation: BankStatementOperation[T]) -> T:
    factory = get_postgres_bank_statement_factory(request)
    if factory is None:
        raise APIError(
            status_code=503,
            code="bank_statement_backend_not_configured",
            message="Server bank-statement persistence is not configured.",
        )
    scope = request_execution_scope(request)
    try:
        with PostgresTenantBoundary(factory).transaction(
            scope.tenant_id,
            organization_id=scope.organization_id,
            workspace_id=scope.workspace_id,
            legal_entity_id=scope.legal_entity_id,
        ) as connection:
            return operation(PostgresBankStatementRepository(connection), scope.tenant_id, scope.workspace_id)
    except APIError:
        raise
    except PostgresBankStatementPersistenceError as exc:
        status = 409 if "conflicts" in str(exc) else 400
        raise APIError(status_code=status, code="bank_statement_persistence_failed", message=str(exc)) from exc
    except (PostgresConfigurationError, PostgresUnavailableError) as exc:
        raise APIError(
            status_code=503,
            code="bank_statement_unavailable",
            message="Server bank-statement persistence is temporarily unavailable.",
        ) from exc
    except Exception as exc:
        raise APIError(
            status_code=503,
            code="bank_statement_unavailable",
            message="Server bank-statement persistence is temporarily unavailable.",
        ) from exc


__all__ = [
    "execute_postgres_bank_statement",
    "get_postgres_bank_statement_factory",
    "server_bank_statement_enabled",
]
