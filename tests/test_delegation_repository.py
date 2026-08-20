from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from reconforge.auth.delegations import DelegationGrant, DelegationValidationError
from reconforge.auth.repositories import AuthRepositoryError, DelegationRepository
from reconforge.db import connect, run_migrations


def _grant(*, status: str = "active", revoked_at: datetime | None = None, revoked_by: str | None = None) -> DelegationGrant:
    start = datetime(2026, 8, 2, 10, tzinfo=UTC)
    return DelegationGrant(
        id="DEL-LOCAL-1", tenant_id="tenant-a", workspace_id="workspace-a",
        delegator_id="manager", delegatee_id="reviewer", permissions=frozenset({"close.manage"}),
        starts_at=start, expires_at=start + timedelta(hours=2), created_by="manager",
        approved_by="controller", status=status, revoked_at=revoked_at, revoked_by=revoked_by,
    )


def _repo(tmp_path: Path) -> DelegationRepository:
    path = tmp_path / "delegations.db"
    run_migrations(path)
    return DelegationRepository(connect(path, require_exists=True))


def test_delegation_is_effective_only_in_explicit_window_and_tenant_scope(tmp_path: Path) -> None:
    repository = _repo(tmp_path)
    grant = repository.create(_grant())
    assert repository.get_effective(
        delegation_id=grant.id, tenant_id="tenant-a", workspace_id="workspace-a",
        evaluation_time=datetime(2026, 8, 2, 11, tzinfo=UTC),
    ) == grant
    assert repository.get_effective(
        delegation_id=grant.id, tenant_id="tenant-b", workspace_id="workspace-a",
        evaluation_time=datetime(2026, 8, 2, 11, tzinfo=UTC),
    ) is None
    assert repository.get_effective(
        delegation_id=grant.id, tenant_id="tenant-a", workspace_id="workspace-a",
        evaluation_time=datetime(2026, 8, 2, 12, tzinfo=UTC),
    ) is None


def test_delegation_revoke_is_independent_and_append_only(tmp_path: Path) -> None:
    repository = _repo(tmp_path)
    repository.create(_grant())
    with pytest.raises(AuthRepositoryError, match="independent"):
        repository.revoke(delegation_id="DEL-LOCAL-1", tenant_id="tenant-a", workspace_id="workspace-a", actor_id="manager", revoked_at=datetime(2026, 8, 2, 11, 30, tzinfo=UTC))
    revoked = repository.revoke(delegation_id="DEL-LOCAL-1", tenant_id="tenant-a", workspace_id="workspace-a", actor_id="security", revoked_at=datetime(2026, 8, 2, 11, 30, tzinfo=UTC))
    assert revoked.status == "revoked"
    assert repository.get_effective(delegation_id="DEL-LOCAL-1", tenant_id="tenant-a", workspace_id="workspace-a", evaluation_time=datetime(2026, 8, 2, 11, 45, tzinfo=UTC)) is None
    with pytest.raises(Exception, match="immutable"):
        repository.connection.execute("UPDATE policy_delegations SET expires_at=? WHERE id=?", ("2027-01-01T00:00:00+00:00", "DEL-LOCAL-1"))


def test_delegation_domain_rejects_self_approval_and_naive_time() -> None:
    with pytest.raises(DelegationValidationError, match="independent"):
        DelegationGrant(**{**_grant().__dict__, "approved_by": "manager"})
    with pytest.raises(DelegationValidationError, match="timezone"):
        DelegationGrant(**{**_grant().__dict__, "starts_at": datetime(2026, 8, 2, 10)})
