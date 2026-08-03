from __future__ import annotations

from datetime import UTC, datetime

import pytest

from reconforge.application.policy_analysis import PolicyAnalysisApplicationService
from reconforge.infrastructure.postgres_policy_analysis import (
    PostgresPolicyAnalysisError,
    PostgresPolicyAnalysisRepository,
)


class _Cursor:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows

    def fetchone(self) -> dict[str, object] | None:
        return self.rows[0] if self.rows else None

    def fetchall(self) -> list[dict[str, object]]:
        return list(self.rows)


class _Connection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def execute(self, sql: str, parameters: tuple[object, ...]) -> _Cursor:
        self.calls.append((sql, parameters))
        if "identity_user_roles" in sql:
            return _Cursor(
                [
                    {
                        "principal_id": "user-1",
                        "role_id": "role-approve",
                        "role_name": "approver",
                        "permission_name": "close.approve",
                        "scope_id": "rps-1",
                        "workspace_id": "workspace-a",
                        "entity_id": "entity-a",
                        "period_id": "period-2026",
                        "region_id": None,
                        "data_classification": "financial",
                    },
                    {"principal_id": "user-1", "role_id": "role-prepare", "role_name": "preparer", "permission_name": "close.prepare"},
                ]
            )
        if "service_accounts" in sql:
            return _Cursor([{"principal_id": "svc-1", "permission_name": "close.manage"}])
        return _Cursor([{"active": True}])


def test_postgres_snapshot_loader_is_tenant_bound_and_replayable() -> None:
    connection = _Connection()
    service = PolicyAnalysisApplicationService(PostgresPolicyAnalysisRepository(connection, "tenant-a"))
    result = service.analyze(
        policy_id="postgres-access-policy",
        policy_version="1.0.0",
        require_scoped_privileged=True,
        prepared_by="user-1",
        prepared_at=datetime(2026, 8, 3, 12, tzinfo=UTC),
        approved_by="user-2",
        approved_at="2026-08-03T11:00:00Z",
    )

    codes = {finding.code for finding in result.findings}
    assert {"sod_permission_overlap", "service_account_human_permission", "unscoped_privileged_grant"} <= codes
    assert result.request_digest
    assert result.result_digest
    assert any(finding.scope_digests for finding in result.findings)
    assert all(parameters == ("tenant-a", "user-1") or parameters == ("tenant-a", "user-2") or parameters == ("tenant-a",) for _, parameters in connection.calls)
    assert any("identity_user_roles" in sql for sql, _ in connection.calls)
    assert any("identity_role_permission_scopes" in sql for sql, _ in connection.calls)
    assert any("service_accounts" in sql for sql, _ in connection.calls)


def test_postgres_snapshot_loader_refuses_unknown_or_inactive_actors() -> None:
    class Connection:
        def execute(self, _sql: str, _parameters: tuple[object, ...]) -> _Cursor:
            return _Cursor([])

    repository = PostgresPolicyAnalysisRepository(Connection(), "tenant-a")
    with pytest.raises(PostgresPolicyAnalysisError, match="prepared_by is unavailable"):
        repository.load_request(
            policy_id="postgres-access-policy",
            policy_version="1.0.0",
            require_scoped_privileged=True,
            prepared_by="missing-user",
            prepared_at=datetime(2026, 8, 3, 12, tzinfo=UTC),
            approved_by="reviewer",
            approved_at="2026-08-03T11:00:00Z",
        )


def test_postgres_snapshot_loader_rejects_invalid_tenant_before_sql() -> None:
    class Connection:
        def execute(self, *_args: object) -> object:
            raise AssertionError("invalid tenant must fail before SQL")

    with pytest.raises(PostgresPolicyAnalysisError, match="tenant_id"):
        PostgresPolicyAnalysisRepository(Connection(), "Tenant Unsafe")
