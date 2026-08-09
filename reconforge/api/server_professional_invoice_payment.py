"""Request-scoped PostgreSQL professional invoice/payment evidence operations."""

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
from reconforge.infrastructure.postgres_professional_invoice_payment import (
    PostgresProfessionalInvoicePaymentPersistenceError,
    PostgresProfessionalInvoicePaymentRepository,
)

T = TypeVar("T")
ProfessionalInvoicePaymentOperation = Callable[[PostgresProfessionalInvoicePaymentRepository, str, str], T]


def get_postgres_professional_invoice_payment_factory(request: Request) -> PostgresConnectionFactory | None:
    """Return the explicitly configured PostgreSQL professional invoice/payment factory."""

    value = getattr(request.app.state, "postgres_professional_invoice_payment_factory", None)
    return value if isinstance(value, PostgresConnectionFactory) else None


def server_professional_invoice_payment_enabled(request: Request) -> bool:
    """Return whether professional invoice/payment persistence must use PostgreSQL server mode."""

    return get_postgres_professional_invoice_payment_factory(request) is not None


def execute_postgres_professional_invoice_payment(
    request: Request,
    operation: ProfessionalInvoicePaymentOperation[T],
) -> T:
    """Execute one tenant/workspace-scoped professional invoice/payment operation."""

    factory = get_postgres_professional_invoice_payment_factory(request)
    if factory is None:
        raise APIError(
            status_code=503,
            code="professional_invoice_payment_backend_not_configured",
            message="Server professional invoice/payment persistence is not configured.",
        )
    scope = request_execution_scope(request)
    try:
        with PostgresTenantBoundary(factory).transaction(
            scope.tenant_id,
            organization_id=scope.organization_id,
            workspace_id=scope.workspace_id,
            legal_entity_id=scope.legal_entity_id,
        ) as connection:
            return operation(
                PostgresProfessionalInvoicePaymentRepository(connection),
                scope.tenant_id,
                scope.workspace_id,
            )
    except APIError:
        raise
    except PostgresProfessionalInvoicePaymentPersistenceError as exc:
        status = 409 if "conflicts" in str(exc) else 400
        raise APIError(
            status_code=status,
            code="professional_invoice_payment_persistence_failed",
            message=str(exc),
        ) from exc
    except (PostgresConfigurationError, PostgresUnavailableError) as exc:
        raise APIError(
            status_code=503,
            code="professional_invoice_payment_unavailable",
            message="Server professional invoice/payment persistence is temporarily unavailable.",
        ) from exc
    except Exception as exc:
        raise APIError(
            status_code=503,
            code="professional_invoice_payment_unavailable",
            message="Server professional invoice/payment persistence is temporarily unavailable.",
        ) from exc


__all__ = [
    "execute_postgres_professional_invoice_payment",
    "get_postgres_professional_invoice_payment_factory",
    "server_professional_invoice_payment_enabled",
]
