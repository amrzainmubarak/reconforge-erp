"""Join a financial repository to caller authority without widening its scope."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from reconforge.infrastructure.postgres import (
    PostgresConfigurationError,
    normalize_scope_id,
    set_local_tenant_scope,
    validate_tenant_id,
)

_SCOPE_FIELDS = ("tenant_id", "organization_id", "workspace_id", "legal_entity_id", "entity_id")
_READ_SCOPE_SQL = """SELECT
    current_setting('app.tenant_id',true) AS tenant_id,
    current_setting('app.organization_id',true) AS organization_id,
    current_setting('app.workspace_id',true) AS workspace_id,
    current_setting('app.legal_entity_id',true) AS legal_entity_id,
    current_setting('app.entity_id',true) AS entity_id"""


class PostgresRepositoryScopeError(PostgresConfigurationError):
    """The repository cannot join the active transaction's authority."""


def ensure_repository_tenant_scope(connection: Any, tenant_id: str) -> None:
    """Initialize an unbound transaction or preserve all existing scope fields.

    Call inside the repository's transaction/savepoint. A matching tenant never
    authorizes clearing or changing its child scope. Read afresh on every call:
    successful nested savepoints must not leave a broader authority behind, and
    rollback/retry or pool reuse must not rely on cached connection attributes.

    The explicit administrative setter remains separate. This guards trusted
    application composition, not arbitrary SQL issued using application credentials.
    """

    selected_tenant = validate_tenant_id(tenant_id)
    row = connection.execute(_READ_SCOPE_SQL).fetchone()
    if row is None:
        raise PostgresRepositoryScopeError("PostgreSQL repository scope could not be established.")
    values = tuple(row[name] for name in _SCOPE_FIELDS) if isinstance(row, Mapping) or hasattr(row, "keys") else tuple(row)
    if len(values) != len(_SCOPE_FIELDS):
        raise PostgresRepositoryScopeError("PostgreSQL repository scope could not be established.")
    current = tuple(None if value in (None, "") else value for value in values)
    try:
        for name, value in zip(_SCOPE_FIELDS, current, strict=True):
            if value is not None and (not isinstance(value, str) or normalize_scope_id(value, field_name=name) != value):
                raise PostgresConfigurationError("invalid scope identifier")
    except PostgresConfigurationError:
        raise PostgresRepositoryScopeError("PostgreSQL repository scope is inconsistent.") from None
    tenant, organization, _workspace, legal_entity, entity_alias = current
    if tenant is None:
        if any(value is not None for value in current[1:]):
            raise PostgresRepositoryScopeError("PostgreSQL repository scope is inconsistent.")
        set_local_tenant_scope(connection, selected_tenant)
        return
    if tenant != selected_tenant:
        raise PostgresRepositoryScopeError("PostgreSQL repository scope does not match the active transaction.")
    if legal_entity != entity_alias or (legal_entity is not None and organization is None):
        raise PostgresRepositoryScopeError("PostgreSQL repository scope is inconsistent.")
