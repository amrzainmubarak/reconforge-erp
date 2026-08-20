"""Request-scoped PostgreSQL identity operations for the server API profile.

The current server profile keeps legacy domain routes on the existing
database-per-tenant SQLite router while identity and session authority live in
PostgreSQL. This module deliberately opens one short tenant-scoped transaction
per identity operation; it never falls back to a shared SQLite identity store
when the server profile is enabled.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar

from fastapi import Request

from reconforge.api.errors import APIError
from reconforge.auth.models import LocalUser
from reconforge.infrastructure.postgres import (
    PostgresConfigurationError,
    PostgresConnectionFactory,
    PostgresTenantBoundary,
    PostgresUnavailableError,
    normalize_scope_id,
    validate_tenant_id,
)
from reconforge.infrastructure.postgres_access_administration import (
    PostgresAccessAdministrationRepository,
)
from reconforge.infrastructure.postgres_emergency_access import (
    EmergencyAccessError,
    PostgresEmergencyAccessRepository,
)
from reconforge.infrastructure.postgres_federation import (
    PostgresFederationAuditSink,
    PostgresFederationError,
    PostgresFederationReplayStore,
    PostgresFederationRepository,
)
from reconforge.infrastructure.postgres_identity import (
    PostgresIdentityError,
    PostgresIdentityRepository,
    PostgresIdentityValidationError,
)
from reconforge.infrastructure.postgres_identity_administration import (
    PostgresIdentityAdministrationRepository,
)
from reconforge.infrastructure.postgres_privileged_sessions import PostgresPrivilegedSessionRepository
from reconforge.infrastructure.postgres_scope_authority import (
    PostgresScopeAuthorityRepository,
    PrincipalScopeSnapshot,
)
from reconforge.infrastructure.postgres_security_center import (
    PostgresSecurityCenterError,
    PostgresSecurityCenterRepository,
)
from reconforge.infrastructure.postgres_security_governance import (
    PostgresSecurityGovernanceRepository,
)
from reconforge.infrastructure.postgres_service_accounts import (
    PostgresServiceAccountRepository,
    ServiceAccountError,
)
from reconforge.infrastructure.postgres_webauthn import PostgresWebAuthnRepository, WebAuthnRepositoryError
from reconforge.platform.common import ServerPrincipal

T = TypeVar("T")
IdentityOperation = Callable[[PostgresIdentityRepository, str], T]
IdentityAdministrationOperation = Callable[[PostgresIdentityAdministrationRepository, str], T]
AccessAdministrationOperation = Callable[[PostgresAccessAdministrationRepository, str], T]
EmergencyAccessOperation = Callable[[PostgresEmergencyAccessRepository, str], T]
ServiceAccountOperation = Callable[[PostgresServiceAccountRepository, str], T]
WebAuthnOperation = Callable[[PostgresWebAuthnRepository, str], T]
SecurityCenterOperation = Callable[[PostgresSecurityCenterRepository, str], T]
SecurityGovernanceOperation = Callable[[PostgresSecurityGovernanceRepository, str], T]
FederationOperation = Callable[
    [PostgresFederationReplayStore, PostgresFederationRepository, PostgresFederationAuditSink, str], T
]


@dataclass(frozen=True)
class AuthenticatedServerRequest:
    user: LocalUser
    permissions: frozenset[str]
    principal_type: str
    credential_id: str | None = None
    session_id: str | None = None
    step_up_active: bool = False
    step_up_expires_at: str | None = None
    step_up_method: str | None = None
    base_permissions: frozenset[str] | None = None
    emergency_permissions: frozenset[str] = frozenset()
    emergency_access_id_by_permission: tuple[tuple[str, str], ...] = ()
    scope_authority: PrincipalScopeSnapshot = PrincipalScopeSnapshot()


@dataclass(frozen=True)
class RequestExecutionScope:
    """Authorized hierarchy selected for one server business request."""

    tenant_id: str
    workspace_id: str
    organization_id: str | None = None
    legal_entity_id: str | None = None


def server_principal_from_authentication(
    authenticated: AuthenticatedServerRequest | tuple[LocalUser, frozenset[str]],
) -> ServerPrincipal:
    """Build a typed request principal while preserving old injected test seams."""

    if isinstance(authenticated, AuthenticatedServerRequest):
        return ServerPrincipal(
            user=authenticated.user,
            permissions=authenticated.permissions,
            principal_type="service_account" if authenticated.principal_type == "service_account" else "user",
            credential_id=authenticated.credential_id,
            session_id=authenticated.session_id,
            step_up_active=authenticated.step_up_active,
            step_up_expires_at=authenticated.step_up_expires_at,
            step_up_method=authenticated.step_up_method,
            base_permissions=(
                authenticated.permissions
                if authenticated.base_permissions is None
                else authenticated.base_permissions
            ),
            emergency_permissions=authenticated.emergency_permissions,
            emergency_access_id_by_permission=authenticated.emergency_access_id_by_permission,
            authorized_workspace_ids=authenticated.scope_authority.workspace_ids,
            authorized_organization_ids=authenticated.scope_authority.organization_ids,
            authorized_legal_entity_ids=authenticated.scope_authority.legal_entity_ids,
        )
    user, permissions = authenticated
    return ServerPrincipal(user=user, permissions=permissions)


def get_postgres_identity_factory(request: Request) -> PostgresConnectionFactory | None:
    """Return the configured server identity factory, if server mode is enabled."""

    value = getattr(request.app.state, "postgres_identity_factory", None)
    return value if isinstance(value, PostgresConnectionFactory) else None


def server_identity_enabled(request: Request) -> bool:
    """Return whether this request is served by the PostgreSQL identity profile."""

    return get_postgres_identity_factory(request) is not None


def request_tenant_id(request: Request) -> str:
    """Validate and return the required tenant header for server identity."""

    raw_tenant = request.headers.get("x-reconforge-tenant", "")
    if not raw_tenant:
        raise APIError(
            status_code=400,
            code="tenant_required",
            message="X-ReconForge-Tenant is required for server authentication.",
        )
    try:
        return validate_tenant_id(raw_tenant)
    except PostgresConfigurationError as exc:
        raise APIError(status_code=400, code="invalid_tenant", message=str(exc)) from exc


def request_optional_hierarchy(request: Request) -> tuple[str | None, str | None]:
    """Return optional organization/entity headers for tenant-scoped routes.

    Tenant-scoped compatibility routes do not require a workspace header, but
    they must still carry a coherent organization/legal-entity pair when one is
    supplied. Central policy evaluation remains responsible for authorization
    against the principal's granted hierarchy.
    """

    raw_organization = request.headers.get("x-reconforge-organization", "").strip()
    raw_entity = request.headers.get("x-reconforge-legal-entity", "").strip()
    try:
        organization_id = (
            normalize_scope_id(raw_organization, field_name="organization_id") if raw_organization else None
        )
        legal_entity_id = normalize_scope_id(raw_entity, field_name="legal_entity_id") if raw_entity else None
    except PostgresConfigurationError as exc:
        raise APIError(status_code=400, code="invalid_execution_scope", message=str(exc)) from exc
    if legal_entity_id is not None and organization_id is None:
        raise APIError(
            status_code=400,
            code="organization_scope_required",
            message="Legal-entity scope requires an organization scope.",
        )
    return organization_id, legal_entity_id


def request_execution_scope(request: Request) -> RequestExecutionScope:
    """Resolve caller-selected hierarchy only from an authenticated grant snapshot."""

    tenant_id = request_tenant_id(request)
    principal = getattr(request.state, "server_principal", None)
    if not isinstance(principal, ServerPrincipal):
        raise APIError(status_code=401, code="auth_required", message="Authentication required.")
    raw_workspace = request.headers.get("x-reconforge-workspace", "").strip()
    if not raw_workspace:
        raise APIError(
            status_code=400,
            code="workspace_scope_required",
            message="X-ReconForge-Workspace is required for server business operations.",
        )
    try:
        workspace_id = normalize_scope_id(raw_workspace, field_name="workspace_id")
        organization_id, legal_entity_id = request_optional_hierarchy(request)
    except PostgresConfigurationError as exc:
        raise APIError(status_code=400, code="invalid_execution_scope", message=str(exc)) from exc
    if workspace_id not in principal.authorized_workspace_ids:
        raise APIError(status_code=403, code="workspace_scope_denied", message="Workspace scope is not authorized.")
    if organization_id is not None and organization_id not in principal.authorized_organization_ids:
        raise APIError(status_code=403, code="organization_scope_denied", message="Organization scope is not authorized.")
    if legal_entity_id is not None:
        if organization_id is None:
            raise APIError(
                status_code=400,
                code="organization_scope_required",
                message="Legal-entity scope requires an organization scope.",
            )
        if legal_entity_id not in principal.authorized_legal_entity_ids:
            raise APIError(status_code=403, code="entity_scope_denied", message="Legal-entity scope is not authorized.")
    return RequestExecutionScope(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        organization_id=organization_id,
        legal_entity_id=legal_entity_id,
    )


def execute_postgres_identity(request: Request, operation: IdentityOperation[T]) -> T:
    """Execute one identity operation inside a transaction-local RLS scope."""

    factory = get_postgres_identity_factory(request)
    if factory is None:
        raise APIError(
            status_code=500,
            code="identity_backend_not_configured",
            message="Server identity backend is not configured.",
        )
    tenant_id = request_tenant_id(request)
    try:
        with PostgresTenantBoundary(factory).transaction(tenant_id) as connection:
            return operation(PostgresIdentityRepository(connection), tenant_id)
    except APIError:
        raise
    except (PostgresConfigurationError, PostgresUnavailableError) as exc:
        raise APIError(
            status_code=503,
            code="identity_unavailable",
            message="Server identity is temporarily unavailable.",
        ) from exc
    except PostgresIdentityValidationError as exc:
        raise APIError(status_code=400, code="identity_request_invalid", message=str(exc)) from exc
    except PostgresIdentityError as exc:
        raise APIError(
            status_code=503,
            code="identity_unavailable",
            message="Server identity is temporarily unavailable.",
        ) from exc
    except Exception as exc:
        # psycopg is optional and intentionally not imported here. Any driver
        # or network failure is sanitized into the same fail-closed response.
        raise APIError(
            status_code=503,
            code="identity_unavailable",
            message="Server identity is temporarily unavailable.",
        ) from exc


def execute_postgres_identity_administration(
    request: Request,
    operation: IdentityAdministrationOperation[T],
) -> T:
    """Execute governed identity administration under transaction-local RLS."""

    factory = get_postgres_identity_factory(request)
    if factory is None:
        raise APIError(
            status_code=503,
            code="identity_administration_unavailable",
            message="Identity administration is unavailable.",
        )
    tenant_id = request_tenant_id(request)
    try:
        with PostgresTenantBoundary(factory).transaction(tenant_id) as connection:
            return operation(PostgresIdentityAdministrationRepository(connection, tenant_id), tenant_id)
    except APIError:
        raise
    except (PostgresConfigurationError, PostgresUnavailableError) as exc:
        raise APIError(
            status_code=503,
            code="identity_administration_unavailable",
            message="Identity administration is temporarily unavailable.",
        ) from exc
    except Exception as exc:
        raise APIError(
            status_code=503,
            code="identity_administration_unavailable",
            message="Identity administration is temporarily unavailable.",
        ) from exc


def execute_postgres_access_administration(
    request: Request,
    operation: AccessAdministrationOperation[T],
) -> T:
    """Execute governed RBAC lifecycle work under transaction-local RLS."""

    factory = get_postgres_identity_factory(request)
    if factory is None:
        raise APIError(
            status_code=503,
            code="access_administration_unavailable",
            message="Access administration is unavailable.",
        )
    tenant_id = request_tenant_id(request)
    try:
        with PostgresTenantBoundary(factory).transaction(tenant_id) as connection:
            return operation(PostgresAccessAdministrationRepository(connection, tenant_id), tenant_id)
    except APIError:
        raise
    except (PostgresConfigurationError, PostgresUnavailableError) as exc:
        raise APIError(
            status_code=503,
            code="access_administration_unavailable",
            message="Access administration is temporarily unavailable.",
        ) from exc
    except Exception as exc:
        raise APIError(
            status_code=503,
            code="access_administration_unavailable",
            message="Access administration is temporarily unavailable.",
        ) from exc


def execute_postgres_emergency(request: Request, operation: EmergencyAccessOperation[T]) -> T:
    """Execute emergency-access lifecycle work inside request tenant RLS."""

    factory = get_postgres_identity_factory(request)
    if factory is None:
        raise APIError(status_code=404, code="emergency_access_unavailable", message="Emergency access is unavailable.")
    tenant_id = request_tenant_id(request)
    try:
        with PostgresTenantBoundary(factory).transaction(tenant_id) as connection:
            return operation(PostgresEmergencyAccessRepository(connection), tenant_id)
    except APIError:
        raise
    except EmergencyAccessError as exc:
        raise APIError(status_code=409, code="emergency_access_conflict", message=str(exc)) from exc
    except (PostgresConfigurationError, PostgresUnavailableError) as exc:
        raise APIError(
            status_code=503,
            code="emergency_access_unavailable",
            message="Emergency access is temporarily unavailable.",
        ) from exc
    except Exception as exc:
        raise APIError(
            status_code=503,
            code="emergency_access_unavailable",
            message="Emergency access is temporarily unavailable.",
        ) from exc


def execute_postgres_webauthn(request: Request, operation: WebAuthnOperation[T]) -> T:
    """Execute one WebAuthn persistence operation under request tenant RLS."""

    factory = get_postgres_identity_factory(request)
    if factory is None:
        raise APIError(status_code=404, code="webauthn_unavailable", message="WebAuthn is unavailable.")
    tenant_id = request_tenant_id(request)
    try:
        with PostgresTenantBoundary(factory).transaction(tenant_id) as connection:
            return operation(PostgresWebAuthnRepository(connection), tenant_id)
    except APIError:
        raise
    except WebAuthnRepositoryError as exc:
        raise APIError(status_code=409, code="webauthn_conflict", message=str(exc)) from exc
    except (PostgresConfigurationError, PostgresUnavailableError) as exc:
        raise APIError(
            status_code=503,
            code="webauthn_unavailable",
            message="WebAuthn is temporarily unavailable.",
        ) from exc
    except Exception as exc:
        raise APIError(
            status_code=503,
            code="webauthn_unavailable",
            message="WebAuthn is temporarily unavailable.",
        ) from exc


def execute_postgres_federation(request: Request, operation: FederationOperation[T]) -> T:
    """Execute one federation operation and its audit inside tenant-local RLS."""

    factory = get_postgres_identity_factory(request)
    if factory is None:
        raise APIError(
            status_code=503,
            code="federation_not_configured",
            message="Federated authentication is not configured.",
        )
    tenant_id = request_tenant_id(request)
    try:
        with PostgresTenantBoundary(factory).transaction(tenant_id) as connection:
            return operation(
                PostgresFederationReplayStore(connection, tenant_id),
                PostgresFederationRepository(connection),
                PostgresFederationAuditSink(connection, tenant_id),
                tenant_id,
            )
    except APIError:
        raise
    except (PostgresConfigurationError, PostgresUnavailableError, PostgresFederationError) as exc:
        raise APIError(
            status_code=503,
            code="federation_unavailable",
            message="Federated authentication is temporarily unavailable.",
        ) from exc
    except Exception as exc:
        raise APIError(
            status_code=503,
            code="federation_unavailable",
            message="Federated authentication is temporarily unavailable.",
        ) from exc


def execute_postgres_service_account(request: Request, operation: ServiceAccountOperation[T]) -> T:
    """Execute one service-account operation inside request tenant RLS."""

    factory = get_postgres_identity_factory(request)
    if factory is None:
        raise APIError(status_code=503, code="service_identity_unavailable", message="Service identity is unavailable.")
    tenant_id = request_tenant_id(request)
    try:
        with PostgresTenantBoundary(factory).transaction(tenant_id) as connection:
            return operation(PostgresServiceAccountRepository(connection), tenant_id)
    except APIError:
        raise
    except (PostgresConfigurationError, PostgresUnavailableError, ServiceAccountError) as exc:
        raise APIError(
            status_code=503, code="service_identity_unavailable", message="Service identity is unavailable."
        ) from exc
    except Exception as exc:
        raise APIError(
            status_code=503, code="service_identity_unavailable", message="Service identity is unavailable."
        ) from exc


def execute_postgres_security_center(request: Request, operation: SecurityCenterOperation[T]) -> T:
    """Read the count-only security projection inside request tenant RLS."""

    factory = get_postgres_identity_factory(request)
    if factory is None:
        raise APIError(status_code=404, code="security_center_unavailable", message="Security center is unavailable.")
    tenant_id = request_tenant_id(request)
    try:
        with PostgresTenantBoundary(factory).transaction(tenant_id) as connection:
            return operation(PostgresSecurityCenterRepository(connection), tenant_id)
    except APIError:
        raise
    except PostgresSecurityCenterError as exc:
        raise APIError(
            status_code=503,
            code="security_center_unavailable",
            message="Security center is temporarily unavailable.",
        ) from exc
    except (PostgresConfigurationError, PostgresUnavailableError) as exc:
        raise APIError(
            status_code=503,
            code="security_center_unavailable",
            message="Security center is temporarily unavailable.",
        ) from exc
    except Exception as exc:
        raise APIError(
            status_code=503,
            code="security_center_unavailable",
            message="Security center is temporarily unavailable.",
        ) from exc


def execute_postgres_security_governance(request: Request, operation: SecurityGovernanceOperation[T]) -> T:
    """Execute one integration/retention governance operation inside tenant RLS."""

    factory = get_postgres_identity_factory(request)
    if factory is None:
        raise APIError(
            status_code=404,
            code="security_governance_unavailable",
            message="Security governance is unavailable.",
        )
    tenant_id = request_tenant_id(request)
    try:
        with PostgresTenantBoundary(factory).transaction(tenant_id) as connection:
            return operation(PostgresSecurityGovernanceRepository(connection, tenant_id), tenant_id)
    except APIError:
        raise
    except (PostgresConfigurationError, PostgresUnavailableError) as exc:
        raise APIError(
            status_code=503,
            code="security_governance_unavailable",
            message="Security governance is temporarily unavailable.",
        ) from exc
    except Exception as exc:
        raise APIError(
            status_code=503,
            code="security_governance_unavailable",
            message="Security governance is temporarily unavailable.",
        ) from exc


def authenticate_server_request(
    request: Request,
    token: str,
) -> AuthenticatedServerRequest | None:
    """Authenticate one bearer token and snapshot permissions for middleware."""

    if token.startswith("rfa_"):
        principal, scope_authority = execute_postgres_service_account(
            request,
            lambda repository, tenant: _authenticate_service_account_with_scope(repository, tenant, token),
        )
        if principal is None:
            return None
        return AuthenticatedServerRequest(
            user=LocalUser(
                id=principal.service_account_id,
                username=principal.name,
                display_name=principal.display_name,
                created_at=principal.created_at.isoformat().replace("+00:00", "Z"),
            ),
            permissions=principal.permissions,
            principal_type="service_account",
            credential_id=principal.credential_id,
            scope_authority=scope_authority,
        )
    authenticated = execute_postgres_identity(request, _authenticate_and_snapshot(token))
    if authenticated is None:
        return None
    user, permissions, assurance, emergency, scope_authority = authenticated
    effective_permissions = permissions.union(emergency.permissions)
    return AuthenticatedServerRequest(
        user=user,
        permissions=effective_permissions,
        principal_type="user",
        session_id=assurance.session_id,
        step_up_active=assurance.step_up_active,
        step_up_expires_at=assurance.step_up_expires_at,
        step_up_method=assurance.step_up_method,
        base_permissions=permissions,
        emergency_permissions=emergency.permissions,
        emergency_access_id_by_permission=emergency.access_id_by_permission,
        scope_authority=scope_authority,
    )


def _authenticate_service_account_with_scope(repository: Any, tenant_id: str, token: str) -> tuple[Any, PrincipalScopeSnapshot]:
    principal = repository.authenticate(tenant_id=tenant_id, token=token)
    if principal is None:
        return None, PrincipalScopeSnapshot()
    scope = PostgresScopeAuthorityRepository(repository.connection).active_for_principal(
        tenant_id=tenant_id, principal_type="service_account", principal_id=principal.service_account_id
    )
    return principal, scope


def _authenticate_and_snapshot(
    token: str,
) -> IdentityOperation[tuple[LocalUser, frozenset[str], Any, Any, PrincipalScopeSnapshot] | None]:
    def operation(
        repository: PostgresIdentityRepository, tenant_id: str
    ) -> tuple[LocalUser, frozenset[str], Any, Any, PrincipalScopeSnapshot] | None:
        user = repository.authenticate_token(tenant_id=tenant_id, token=token)
        if user is None:
            return None
        assurance = PostgresPrivilegedSessionRepository(repository.connection).assurance_for_token(
            tenant_id=tenant_id, token=token, user_id=user.id
        )
        if assurance is None:
            return None
        emergency = PostgresEmergencyAccessRepository(repository.connection).active_for_session(
            tenant_id=tenant_id,
            token=token,
            user_id=user.id,
            session_id=assurance.session_id,
        )
        scope = PostgresScopeAuthorityRepository(repository.connection).active_for_principal(
            tenant_id=tenant_id, principal_type="user", principal_id=user.id
        )
        return user, repository.user_permissions(tenant_id=tenant_id, user_id=user.id), assurance, emergency, scope

    return operation


def record_emergency_authority_use(
    request: Request,
    principal: ServerPrincipal,
    *,
    permission: str,
    surface: str,
    request_id: str,
) -> None:
    """Fail closed unless an emergency-derived authorization use is appended."""

    if permission in principal.base_permissions or permission not in principal.emergency_permissions:
        return
    access_by_permission = dict(principal.emergency_access_id_by_permission)
    access_id = access_by_permission.get(permission)
    if access_id is None or principal.session_id is None:
        raise APIError(status_code=403, code="permission_denied", message="Permission denied.")
    try:
        execute_postgres_emergency(
            request,
            lambda repository, tenant_id: repository.record_use(
                tenant_id=tenant_id,
                access_id=access_id,
                user_id=principal.user.id,
                session_id=principal.session_id or "",
                permission=permission,
                surface=surface,
                request_id=request_id,
            ),
        )
    except EmergencyAccessError as exc:
        raise APIError(
            status_code=403,
            code="emergency_access_expired",
            message="Emergency authority is no longer active.",
        ) from exc


def server_identity_state(request: Request) -> dict[str, Any]:
    """Return non-secret diagnostics for the configured identity profile."""

    return {
        "backend": "postgresql" if server_identity_enabled(request) else "sqlite",
        "tenant_header_required": server_identity_enabled(request),
    }
