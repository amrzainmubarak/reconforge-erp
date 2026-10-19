"""Tests for enterprise batch operations, multi-GUC setup, and scoped cache invalidation."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from reconforge.api import create_api_app
from reconforge.auth.policy import PolicyDecision
from reconforge.auth.policy_cache import PolicyDecisionCache
from reconforge.db import run_migrations
from reconforge.infrastructure.postgres import (
    PostgresExecutionScope,
    set_local_tenant_scope,
)
from reconforge.infrastructure.postgres_finance_posting import (
    FinancePostingError,
    PostgresFinancePostingRepository,
    PostingActor,
)
from reconforge.infrastructure.postgres_reconciliation import (
    PostgresReconciliationIntegrityError,
    PostgresReconciliationRepository,
    PostgresReconciliationValidationError,
)


class _MockConnection:
    """Mock connection to test the combined multi-GUC statement and execution counts."""

    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple[Any, ...] | None]] = []
        self.closed = False

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> Any:
        self.executed.append((sql, params))
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_cursor.fetchone.return_value = (True,)
        return mock_cursor


def test_set_local_tenant_scope_executes_single_combined_multiguc_statement() -> None:
    """Verify set_local_tenant_scope executes a single 5-setting SELECT statement."""
    connection = _MockConnection()
    scope = set_local_tenant_scope(
        connection,
        "tenant-corp",
        organization_id="org-main",
        workspace_id="ws-prod",
        legal_entity_id="le-hq",
    )

    assert scope == PostgresExecutionScope("tenant-corp", "org-main", "ws-prod", "le-hq")
    # Must be exactly 1 SQL execution instead of 5 separate round-trips
    assert len(connection.executed) == 1
    query, params = connection.executed[0]
    assert "set_config('app.tenant_id'" in query
    assert "set_config('app.organization_id'" in query
    assert "set_config('app.workspace_id'" in query
    assert "set_config('app.legal_entity_id'" in query
    assert "set_config('app.entity_id'" in query
    assert params == ("tenant-corp", "org-main", "ws-prod", "le-hq", "le-hq")


def test_reconciliation_append_results_batch_set_validation_and_chunking() -> None:
    """Test append_results_batch enforces set-based input existence and executes chunked inserts."""
    conn = _MockConnection()
    repo = PostgresReconciliationRepository(conn)

    # Bypass frozen dataclass to mock _run_row
    object.__setattr__(repo, "_run_row", MagicMock())

    # Test 1: Empty batch returns empty list with zero queries
    assert repo.append_results_batch(tenant_id="tenant-a", run_id="run-1", items=[]) == []

    # Test 2: Missing left/right input record raises validation error
    invalid_item = {"match_type": "Exact", "confidence": "1.0", "status": "Matched"}
    try:
        repo.append_results_batch(tenant_id="tenant-a", run_id="run-1", items=[invalid_item])
        raise AssertionError("Expected PostgresReconciliationValidationError")
    except PostgresReconciliationValidationError:
        pass

    # Test 3: Set-based input verification rejects missing input
    valid_item = {
        "left_id": "left-001",
        "right_id": "right-001",
        "match_type": "Exact",
        "explanation": "Exact amount and reference match",
        "confidence": "1.0",
        "status": "Matched",
    }
    # Mock connection.execute to return empty set for input existence query
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = []
    conn.execute = MagicMock(return_value=mock_cursor)  # type: ignore[method-assign]

    try:
        repo.append_results_batch(tenant_id="tenant-a", run_id="run-1", items=[valid_item])
        raise AssertionError("Expected PostgresReconciliationIntegrityError")
    except PostgresReconciliationIntegrityError:
        pass

    # Test 4: When inputs exist, execute produces chunked multi-row INSERT
    def mock_execute(sql: str, params: tuple[Any, ...] | None = None) -> Any:
        cursor = MagicMock()
        if "reconciliation_inputs" in sql:
            # Return both inputs as existing
            if "side = 'Left'" in sql:
                cursor.fetchall.return_value = [("left-001",)]
            else:
                cursor.fetchall.return_value = [("right-001",)]
            return cursor
        if "INSERT INTO reconforge.reconciliation_results" in sql:
            # Return inserted row
            assert params is not None
            returned_row = (
                params[0], params[1], params[2], params[3], params[4],
                params[5], params[6], params[7], params[8], params[9],
                params[10], params[11], params[12], "2026-10-19T20:00:00Z"
            )
            cursor.fetchall.return_value = [returned_row]
            return cursor
        return cursor

    conn.execute = MagicMock(side_effect=mock_execute)  # type: ignore[method-assign]
    results = repo.append_results_batch(tenant_id="tenant-a", run_id="run-1", items=[valid_item])
    assert len(results) == 1
    assert results[0]["left_id"] == "left-001"
    assert results[0]["right_id"] == "right-001"


def test_reconciliation_append_exceptions_batch_execution() -> None:
    """Test append_exceptions_batch executes chunked multi-row inserts."""
    conn = _MockConnection()
    repo = PostgresReconciliationRepository(conn)
    object.__setattr__(repo, "_run_row", MagicMock())

    exception_item = {
        "exception_type": "AmountMismatch",
        "source_side": "Left",
        "source_id": "left-002",
        "title": "Discrepancy",
        "explanation": "Amount difference detected",
        "severity": "High",
        "risk_score": "0.85",
        "reason_code": "AMT_DIFF",
    }

    def mock_execute(sql: str, params: tuple[Any, ...] | None = None) -> Any:
        cursor = MagicMock()
        if "INSERT INTO reconforge.reconciliation_exceptions" in sql:
            assert params is not None
            returned_row = (
                params[0], params[1], params[2], params[3], params[4],
                params[5], params[6], params[7], params[8], params[9],
                "Open", params[10], params[11], params[12],
                "2026-10-19T20:00:00Z", "2026-10-19T20:00:00Z"
            )
            cursor.fetchall.return_value = [returned_row]
        return cursor

    conn.execute = MagicMock(side_effect=mock_execute)  # type: ignore[method-assign]
    exceptions = repo.append_exceptions_batch(tenant_id="tenant-a", run_id="run-1", items=[exception_item])
    assert len(exceptions) == 1
    assert exceptions[0]["exception_type"] == "AmountMismatch"
    assert exceptions[0]["severity"] == "High"


def test_multi_tenant_scoped_cache_invalidation() -> None:
    """Verify policy cache invalidation is scoped to tenant without evicting other tenants."""
    cache = PolicyDecisionCache()

    # Pre-populate cache for Tenant A and Tenant B
    cache._entries["eval-1"] = (PolicyDecision(True, "req-1"), "tenant-a", "org-a", "ws-a", 100.0)
    cache._entries["eval-2"] = (PolicyDecision(True, "req-2"), "tenant-a", "org-a", "ws-a", 100.0)
    cache._entries["eval-3"] = (PolicyDecision(True, "req-3"), "tenant-b", "org-b", "ws-b", 100.0)

    assert len(cache) == 3

    # Invalidate Tenant A only
    evicted = cache.invalidate(tenant_id="tenant-a")
    assert evicted == 2
    assert len(cache) == 1

    # Tenant B's cached decisions must remain intact
    assert "eval-3" in cache._entries
    assert cache._entries["eval-3"][1] == "tenant-b"


def test_api_middleware_scopes_cache_invalidation_to_request_tenant(tmp_path: Path) -> None:
    """Verify API mutation middleware extracts tenant context and scopes cache invalidation."""
    db_path = tmp_path / "scoped-cache.db"
    run_migrations(db_path)
    api = create_api_app(db_path, policy_cache_enabled=True)
    cache = api.state.policy_decision_cache
    assert isinstance(cache, PolicyDecisionCache)

    # Pre-populate decisions for tenant-alpha and tenant-beta
    cache._entries["decision-alpha"] = (PolicyDecision(True, "perm1"), "tenant-alpha", None, None, 100.0)
    cache._entries["decision-beta"] = (PolicyDecision(True, "perm2"), "tenant-beta", None, None, 100.0)
    assert len(cache) == 2

    client = TestClient(api)

    # Perform mutation for tenant-alpha
    client.post(
        "/api/v1/auth/login",
        json={"username": "test", "password": "wrong-password"},
        headers={"x-tenant-id": "tenant-alpha"},
    )

    # Tenant alpha decisions evicted, but tenant beta decisions must be preserved
    assert "decision-alpha" not in cache._entries
    assert "decision-beta" in cache._entries


def test_finance_post_batch_requires_permission_and_executes_atomically() -> None:
    """Verify post_batch requires finance_core.post permission and executes in a single transaction."""
    conn = _MockConnection()
    repo = PostgresFinancePostingRepository(conn, "tenant-a")

    # Unauthorized actor should be rejected
    unauthorized = PostingActor(user_id="viewer", username="viewer", permissions=frozenset({"finance_core.read"}))
    try:
        repo.post_batch([], actor=unauthorized)
        raise AssertionError("Expected FinancePostingError for unauthorized actor")
    except FinancePostingError:
        pass

    # Authorized actor with empty list returns []
    authorized = PostingActor(
        user_id="controller",
        username="controller",
        permissions=frozenset({"finance_core.post"}),
        step_up_active=True,
    )
    assert repo.post_batch([], actor=authorized) == []

    # With items, verifies that post is called per item inside a transaction
    items = [
        {
            "entry_id": "ENT-001",
            "command_id": "CMD-001",
            "expected_validation_digest": "digest1",
            "reason": "Batch post 1",
        },
        {
            "entry_id": "ENT-002",
            "command_id": "CMD-002",
            "expected_validation_digest": "digest2",
            "reason": "Batch post 2",
        },
    ]

    mock_post_results = [{"id": "PST-001"}, {"id": "PST-002"}]
    repo.post = MagicMock(side_effect=mock_post_results)  # type: ignore[method-assign]
    repo._transaction = MagicMock()  # type: ignore[method-assign]
    repo._transaction.return_value.__enter__ = MagicMock()
    repo._transaction.return_value.__exit__ = MagicMock()

    results = repo.post_batch(items, actor=authorized)
    assert len(results) == 2
    assert results == mock_post_results
    assert repo.post.call_count == 2
