"""Request-scoped SCIM client authentication and protocol errors."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, cast

from fastapi import Depends, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials

from reconforge.api.dependencies import bearer_scheme
from reconforge.infrastructure.postgres import (
    PostgresConfigurationError,
    PostgresConnectionFactory,
    PostgresTenantBoundary,
    PostgresUnavailableError,
    validate_tenant_id,
)
from reconforge.infrastructure.postgres_scim import PostgresSCIMAuditSink, PostgresSCIMRepository
from reconforge.infrastructure.postgres_scim_auth import PostgresSCIMCredentialRepository, SCIMClientPrincipal

SCIM_ERROR_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:Error"


class SCIMHTTPError(ValueError):
    def __init__(self, status_code: int, detail: str, *, scim_type: str | None = None) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        self.scim_type = scim_type


@dataclass(frozen=True)
class SCIMRequestContext:
    principal: SCIMClientPrincipal
    repository: PostgresSCIMRepository
    audit: PostgresSCIMAuditSink


async def scim_error_handler(request: Request, exc: SCIMHTTPError) -> JSONResponse:
    del request
    content: dict[str, Any] = {
        "schemas": [SCIM_ERROR_SCHEMA],
        "status": str(exc.status_code),
        "detail": exc.detail,
    }
    if exc.scim_type is not None:
        content["scimType"] = exc.scim_type
    headers = {"WWW-Authenticate": 'Bearer realm="ReconForge SCIM"'} if exc.status_code == 401 else None
    return JSONResponse(
        status_code=exc.status_code, content=content, headers=headers, media_type="application/scim+json"
    )


def get_scim_context(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> Iterator[SCIMRequestContext]:
    """Authenticate a SCIM token and retain its tenant transaction for the request."""

    factory = getattr(request.app.state, "postgres_identity_factory", None)
    if not isinstance(factory, PostgresConnectionFactory):
        raise SCIMHTTPError(503, "SCIM provisioning is not configured.")
    raw_tenant = request.headers.get("x-reconforge-tenant", "")
    try:
        tenant = validate_tenant_id(raw_tenant)
    except PostgresConfigurationError as exc:
        raise SCIMHTTPError(401, "SCIM authentication failed.") from exc
    if credentials is None or credentials.scheme.casefold() != "bearer" or not credentials.credentials:
        raise SCIMHTTPError(401, "SCIM authentication failed.")
    try:
        with PostgresTenantBoundary(factory).transaction(tenant) as connection:
            principal = PostgresSCIMCredentialRepository(connection).authenticate(
                tenant_id=tenant, token=credentials.credentials
            )
            if principal is None:
                raise SCIMHTTPError(401, "SCIM authentication failed.")
            yield SCIMRequestContext(
                principal=principal,
                repository=PostgresSCIMRepository(connection),
                audit=PostgresSCIMAuditSink(connection),
            )
    except SCIMHTTPError:
        raise
    except (PostgresConfigurationError, PostgresUnavailableError) as exc:
        raise SCIMHTTPError(503, "SCIM provisioning is temporarily unavailable.") from exc
    except Exception as exc:
        raise SCIMHTTPError(503, "SCIM provisioning is temporarily unavailable.") from exc


scim_context_dependency = cast(Any, get_scim_context)
scim_context_dependency.__reconforge_permissions__ = frozenset()
scim_context_dependency.__reconforge_permission_mode__ = "scim"
