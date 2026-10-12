"""Dedicated personnel DB role, composed with existing server identity and GL.

The credential is a trusted backend credential, not per-human database login.
Private field RLS requires authenticated session_user role membership as well
as tenant/hierarchy scope; a freely set actor GUC alone proves no identity.
"""

from __future__ import annotations

from typing import TypeVar

from fastapi import Request

from reconforge.api.errors import APIError
from reconforge.api.server_finance_core import FinanceCoreExecutionScope, FinanceCoreScopedOperation, _scope_codes
from reconforge.api.server_identity import request_execution_scope
from reconforge.infrastructure.postgres import PostgresConnectionFactory, PostgresTenantBoundary
from reconforge.infrastructure.postgres_finance_core import PostgresFinanceCoreRepository
from reconforge.infrastructure.postgres_identity import PostgresIdentityRepository
from reconforge.platform.common import current_server_principal

T = TypeVar("T")
PERSONNEL_ROLE = "reconforge_personnel_runtime"
PERSONNEL_PERMISSION = "people_project_payroll.read_sensitive"


def validate_personnel_database_pair(main_dsn: str, personnel_dsn: str) -> None:
    """Require explicit matching endpoints/database and different DB logins.

    No secret or connection text is included in errors. Libpq service files and
    environment-derived endpoints are not accepted for this dual-role boundary.
    """
    try:
        from psycopg.conninfo import conninfo_to_dict

        main = conninfo_to_dict(main_dsn)
        personnel = conninfo_to_dict(personnel_dsn)
        if any("service" in value or not value.get("dbname") or not value.get("user")
               or not (value.get("host") or value.get("hostaddr")) for value in (main, personnel)):
            raise ValueError
        endpoint_fields = ("host", "hostaddr", "dbname")
        if any(main.get(key, "") != personnel.get(key, "") for key in endpoint_fields):
            raise ValueError
        if main.get("port", "5432") != personnel.get("port", "5432") or main["user"] == personnel["user"]:
            raise ValueError
    except Exception:
        raise ValueError("Personnel PostgreSQL requires the same explicit database endpoint and a separate login.") from None


def get_postgres_personnel_factory(request: Request) -> PostgresConnectionFactory | None:
    factory = getattr(request.app.state, "postgres_personnel_factory", None)
    return factory if isinstance(factory, PostgresConnectionFactory) else None


def execute_postgres_personnel_scoped(
    request: Request,
    operation: FinanceCoreScopedOperation[T],
    *,
    organization_code: str = "",
    entity_code: str = "",
) -> T:
    """One private-role transaction with current human authority and native GL."""
    principal = current_server_principal()
    if principal is None or principal.principal_type != "user" or principal.user.disabled:
        raise APIError(status_code=403, code="personnel_human_required", message="A current human identity is required.")
    if PERSONNEL_PERMISSION not in principal.permissions or not principal.step_up_active:
        raise APIError(status_code=403, code="personnel_access_denied", message="Current personnel access and stronger authentication are required.")
    factory = get_postgres_personnel_factory(request)
    if factory is None:
        raise APIError(status_code=503, code="personnel_backend_unavailable", message="The dedicated personnel database boundary is not configured.")
    scope = request_execution_scope(request)
    try:
        with PostgresTenantBoundary(factory).transaction(
            scope.tenant_id, workspace_id=scope.workspace_id,
            organization_id=scope.organization_id, legal_entity_id=scope.legal_entity_id,
        ) as connection:
            role = connection.execute(
                "SELECT COALESCE(pg_catalog.pg_has_role(session_user,pg_catalog.to_regrole(%s),'MEMBER'),false)",
                (PERSONNEL_ROLE,),
            ).fetchone()
            if role is None or role[0] is not True:
                raise APIError(status_code=503, code="personnel_backend_unavailable", message="The personnel database role is not configured.")
            active = connection.execute(
                "SELECT 1 FROM reconforge.identity_users WHERE tenant_id=%s AND id=%s AND NOT disabled FOR SHARE",
                (scope.tenant_id, principal.user.id),
            ).fetchone()
            permissions = PostgresIdentityRepository(connection).user_permissions(
                tenant_id=scope.tenant_id, user_id=principal.user.id,
            )
            if active is None or PERSONNEL_PERMISSION not in permissions:
                raise APIError(status_code=403, code="personnel_access_denied", message="Current personnel access is required.")
            # This is a current-authority selector inside a role-authenticated
            # backend transaction. It is deliberately not an authentication claim.
            connection.execute("SELECT set_config('app.personnel_actor_id',%s,true)", (principal.user.id,))
            bound_organization, bound_entity = _scope_codes(
                connection, scope, organization_code=organization_code, entity_code=entity_code,
            )
            return operation(
                PostgresFinanceCoreRepository(connection, scope.tenant_id),
                FinanceCoreExecutionScope(scope, bound_organization, bound_entity),
            )
    except APIError:
        raise
    except Exception as exc:
        if getattr(exc, "sqlstate", None) in {"23503", "23505", "23514", "40001", "40P01"}:
            raise APIError(status_code=409, code="personnel_source_conflict", message="The retained personnel source conflicts with this command; reload before retrying.") from None
        raise APIError(status_code=503, code="personnel_backend_unavailable", message="The personnel service is temporarily unavailable.") from None
