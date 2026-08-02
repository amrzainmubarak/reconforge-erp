from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from reconforge.auth.delegations import DelegationGrant
from reconforge.infrastructure.postgres_delegations import (
    POSTGRES_DELEGATION_SCHEMA_SQL,
    PostgresDelegationError,
    PostgresDelegationRepository,
)


def _grant(*, status: str = "active", revoked_at: datetime | None = None, revoked_by: str | None = None) -> DelegationGrant:
    return DelegationGrant(
        id="delegation-1",
        tenant_id="tenant-a",
        workspace_id="workspace-a",
        delegator_id="manager-1",
        delegatee_id="reviewer-1",
        permissions=frozenset({"reports.read", "close.review"}),
        starts_at=datetime(2026, 8, 3, 8, tzinfo=UTC),
        expires_at=datetime(2026, 8, 3, 18, tzinfo=UTC),
        created_by="operator-1",
        approved_by="approver-1",
        status=status,
        revoked_at=revoked_at,
        revoked_by=revoked_by,
    )


def test_schema_is_rls_immutable_and_has_fail_closed_constraints() -> None:
    schema = POSTGRES_DELEGATION_SCHEMA_SQL
    assert "FORCE ROW LEVEL SECURITY" in schema
    assert "current_setting('app.tenant_id', true)" in schema
    assert "policy delegations are append-only" in schema
    assert "approved_by <> delegator_id" in schema
    assert "jsonb_array_length(permissions) > 0" in schema
    assert "OLD.permissions <> NEW.permissions" in schema


def test_migration_is_linear_and_downgrade_refuses_data_loss() -> None:
    migration = Path("alembic/versions/0056_postgres_policy_delegations.py").read_text(encoding="utf-8")
    assert 'revision = "0056_pg_policy_delegations"' in migration
    assert 'down_revision = "0055_pg_consol_close"' in migration
    assert "refusing to discard policy delegation evidence" in migration


def test_create_rejects_invalid_scope_before_touching_connection() -> None:
    class Connection:
        def execute(self, *_args: object) -> object:
            raise AssertionError("invalid input must fail before SQL")

    grant = _grant()
    object.__setattr__(grant, "tenant_id", "Tenant Unsafe")
    with pytest.raises(PostgresDelegationError, match="tenant_id"):
        PostgresDelegationRepository(Connection()).create(grant)


def test_get_effective_binds_tenant_workspace_and_explicit_instant() -> None:
    class Connection:
        def __init__(self) -> None:
            self.parameters: tuple[object, ...] | None = None

        def execute(self, _sql: str, parameters: tuple[object, ...]) -> object:
            self.parameters = parameters

            class Cursor:
                def fetchone(self) -> None:
                    return None

            return Cursor()

    connection = Connection()
    result = PostgresDelegationRepository(connection).get_effective(
        delegation_id="delegation-1",
        tenant_id="tenant-a",
        workspace_id="workspace-a",
        evaluation_time=datetime(2026, 8, 3, 12, tzinfo=UTC),
    )
    assert result is None
    assert connection.parameters is not None
    assert connection.parameters[:3] == ("tenant-a", "delegation-1", "workspace-a")
    assert connection.parameters[3] == connection.parameters[4]


def test_revoke_requires_independent_actor_and_uses_active_guard() -> None:
    class Connection:
        def execute(self, _sql: str, _parameters: tuple[object, ...]) -> object:
            class Cursor:
                def fetchone(self) -> None:
                    return None

            return Cursor()

    with pytest.raises(PostgresDelegationError, match="not permitted"):
        PostgresDelegationRepository(Connection()).revoke(
            delegation_id="delegation-1",
            tenant_id="tenant-a",
            workspace_id="workspace-a",
            actor_id="manager-1",
            revoked_at=datetime.now(UTC),
        )
