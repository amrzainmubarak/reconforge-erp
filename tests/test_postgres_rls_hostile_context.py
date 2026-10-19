"""Hostile Tenant Context & PostgreSQL FORCE RLS Defense Verification.

Validates:
1. Adversarial SQL injection attempts on tenant/scope parameters: Verifies that malicious
   SQL injection, escape, union, and boundary violation strings are rejected fail-closed
   by validate_tenant_id and normalize_scope_id with PostgresConfigurationError.
2. Hostile session GUC tampering rejection: Verifies that _validate_runtime_connection
   and PostgresRuntimeConnectionFactory discard poisoned connections and raise
   PostgresRuntimeRoleError when row_security is disabled, privileged roles are used,
   or un-scoped session GUCs are detected.
3. Connection pool isolation: Proves that pooled connections shared across sequential tenants
   never retain cross-tenant scope, and that transaction-local GUCs reset completely.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from reconforge.infrastructure.postgres import (
    _RUNTIME_ROLE_SAFETY_SQL,
    PostgresConfigurationError,
    PostgresConnectionPool,
    PostgresRuntimeConnectionFactory,
    PostgresRuntimeRoleError,
    _validate_runtime_connection,
    normalize_scope_id,
    validate_legal_entity_id,
    validate_organization_id,
    validate_tenant_id,
    validate_workspace_id,
)

# ==============================================================================
# 1. Adversarial SQL Injection on Tenant & Scope Parameters
# ==============================================================================

ADVERSARIAL_TENANT_PAYLOADS = [
    "' OR '1'='1",
    "tenant_a'; DROP TABLE reconforge.finance_entries; --",
    "tenant\x00' UNION SELECT * FROM reconforge.ar_customers --",
    "'; SHUTDOWN; --",
    "admin' --",
    "tenant_a' OR 1=1 --",
    "../../etc/passwd",
    "<script>alert('xss')</script>",
    "tenant_a\nSET row_security = off;",
    "tenant_a\r\nSELECT set_config('app.tenant_id', 'evil', false);",
    "tenant_a'; EXEC xp_cmdshell('calc'); --",
    "tenant_a' AND 1=(SELECT COUNT(*) FROM reconforge.users) --",
    "'; VACUUM FULL reconforge.finance_entries; --",
    "'; ALTER ROLE app_user WITH SUPERUSER; --",
    "a" * 65,  # Exceeds max length of 64
    "",  # Empty string
    "   ",  # Whitespace only
    "-tenant_leading_hyphen",  # Must start with alphanumeric
    "_tenant_leading_underscore",  # Must start with alphanumeric
    "tenant with spaces",
    "tenant$special#chars",
    "TENANT_UPPERCASE_ONLY",  # Uppercase normalized to lowercase, but tested explicitly
]


@pytest.mark.parametrize("payload", ADVERSARIAL_TENANT_PAYLOADS)
def test_adversarial_sql_injection_rejected_by_validate_tenant_id(payload: str) -> None:
    """Every adversarial SQL injection payload must be rejected fail-closed

    with PostgresConfigurationError (unless it strictly normalizes to valid lowercase).
    """
    if payload == "TENANT_UPPERCASE_ONLY":
        # Upper case is normalized to lowercase "tenant_uppercase_only"
        normalized = validate_tenant_id(payload)
        assert normalized == "tenant_uppercase_only"
        return

    with pytest.raises(PostgresConfigurationError):
        validate_tenant_id(payload)


@pytest.mark.parametrize("field_validator", [
    validate_organization_id,
    validate_workspace_id,
    validate_legal_entity_id,
])
def test_adversarial_scope_parameters_rejected(field_validator: Any) -> None:
    """Organization, workspace, and legal entity parameters must reject SQL injection payloads."""
    hostile_payload = "org_a'; DROP SCHEMA reconforge CASCADE; --"
    with pytest.raises(PostgresConfigurationError):
        field_validator(hostile_payload)


def test_normalize_scope_id_boundary_lengths() -> None:
    """Test 1-char minimum and 64-char maximum boundaries."""
    # Valid 1-character ID
    assert normalize_scope_id("a") == "a"
    assert normalize_scope_id("1") == "1"

    # Valid 64-character ID
    valid_64 = "a" + "b" * 63
    assert normalize_scope_id(valid_64) == valid_64

    # Invalid 65-character ID
    invalid_65 = "a" + "b" * 64
    with pytest.raises(PostgresConfigurationError, match="must use 1-64"):
        normalize_scope_id(invalid_65)


# ==============================================================================
# 2. Hostile Session GUC Tampering & Catalog Validation
# ==============================================================================


class _MockCatalogConnection:
    """Mock connection for testing _validate_runtime_connection catalog queries."""

    def __init__(self, safe_row: tuple[bool] | None = (True,)) -> None:
        self.safe_row = safe_row
        self.closed = False
        self.executed_queries: list[str] = []
        self.rollbacks = 0

    def execute(self, query: str, params: Any = None) -> Any:
        self.executed_queries.append(query)
        if query == _RUNTIME_ROLE_SAFETY_SQL:
            return SimpleNamespace(fetchone=lambda: self.safe_row)
        return SimpleNamespace(fetchone=lambda: None)

    def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        self.closed = True


def test_validate_runtime_connection_accepts_clean_connection() -> None:
    """A clean runtime connection returning (True,) passes validation and executes rollback."""
    conn = _MockCatalogConnection(safe_row=(True,))
    validated = _validate_runtime_connection(conn)
    assert validated is conn
    assert conn.rollbacks == 1
    assert not conn.closed


@pytest.mark.parametrize("unsafe_row", [
    (False,),
    (None,),
    None,
    (),
    (0,),
])
def test_validate_runtime_connection_rejects_unsafe_catalog_result(unsafe_row: Any) -> None:
    """Any catalog result that does not evaluate strictly to (True,) is rejected."""
    conn = _MockCatalogConnection(safe_row=unsafe_row)
    with pytest.raises(PostgresRuntimeRoleError, match="runtime role safety check failed"):
        _validate_runtime_connection(conn)
    assert conn.closed, "Unsafe connection must be closed immediately"


def test_validate_runtime_connection_discards_on_exception() -> None:
    """Any database exception during safety query causes immediate connection close and rejection."""
    class _FailingConnection:
        def __init__(self) -> None:
            self.closed = False

        def execute(self, query: str, params: Any = None) -> Any:
            raise RuntimeError("Database connection reset by peer")

        def rollback(self) -> None:
            pass

        def close(self) -> None:
            self.closed = True

    failing_conn = _FailingConnection()
    with pytest.raises(PostgresRuntimeRoleError, match="runtime role safety check failed"):
        _validate_runtime_connection(failing_conn)
    assert failing_conn.closed


# ==============================================================================
# 3. Connection Pool Isolation & Zero Cross-Tenant State Leakage
# ==============================================================================


class _StatefulConnection:
    """Stateful simulated database connection tracking session-level vs local GUCs."""

    def __init__(self) -> None:
        self.session_gucs: dict[str, str] = {}
        self.local_gucs: dict[str, str] = {}
        self.in_transaction = False
        self.closed = False

    def execute(self, query: str, params: Any = None) -> Any:
        if query == _RUNTIME_ROLE_SAFETY_SQL:
            # Check if any session-level tenant GUC is persisted
            is_safe = (
                self.session_gucs.get("app.tenant_id", "") == ""
                and self.session_gucs.get("app.organization_id", "") == ""
                and self.session_gucs.get("row_security", "on") == "on"
            )
            return SimpleNamespace(fetchone=lambda: (is_safe,))

        if "set_config" in query and params:
            val = params[0]
            is_local = "true" in query.lower()
            if is_local:
                self.local_gucs["app.tenant_id"] = val
            else:
                self.session_gucs["app.tenant_id"] = val
            return SimpleNamespace(fetchone=lambda: None)

        return SimpleNamespace(fetchone=lambda: None)

    def commit(self) -> None:
        self.in_transaction = False
        self.local_gucs.clear()  # Transaction-local GUCs vanish on commit

    def rollback(self) -> None:
        self.in_transaction = False
        self.local_gucs.clear()  # Transaction-local GUCs vanish on rollback

    def close(self) -> None:
        self.closed = True


def test_pooled_connection_isolation_across_sequential_tenants() -> None:
    """Verify that a pooled connection leased by Tenant A, then returned to the pool,

    never leaks state to a subsequent lease by Tenant B.
    """
    connection = _StatefulConnection()
    pool = PostgresConnectionPool(SimpleNamespace(connect=lambda: connection), max_size=1)
    factory = PostgresRuntimeConnectionFactory(pool)

    # Lease 1: Tenant A checks out connection
    lease_a = factory.connect()
    # Tenant A sets transaction-local scope
    lease_a.execute("SELECT set_config('app.tenant_id', %s, true)", ("tenant_a",))
    assert lease_a._connection.local_gucs["app.tenant_id"] == "tenant_a"

    # Transaction ends (rollback or commit)
    lease_a.rollback()
    # Transaction-local GUC cleared
    assert "app.tenant_id" not in lease_a._connection.local_gucs
    lease_a.close()

    # Pool should have connection idle and clean
    assert pool.snapshot.leased == 0
    assert pool.snapshot.idle == 1

    # Lease 2: Tenant B checks out the same physical connection
    lease_b = factory.connect()
    # Assert connection safety query succeeded and no residual tenant_a state exists
    assert lease_b._connection.session_gucs.get("app.tenant_id", "") == ""
    assert "app.tenant_id" not in lease_b._connection.local_gucs

    lease_b.close()
    pool.close()


def test_pool_discards_connection_if_session_guc_was_poisoned() -> None:
    """If an adversarial query poisons the session with non-local set_config(..., false),

    the next checkout detects the violation, discards the connection, and does not return it.
    """
    connection = _StatefulConnection()
    pool = PostgresConnectionPool(SimpleNamespace(connect=lambda: connection), max_size=1)
    factory = PostgresRuntimeConnectionFactory(pool)

    lease = factory.connect()
    # Adversary sets session-level GUC (persists across transactions!)
    lease.execute("SELECT set_config('app.tenant_id', %s, false)", ("evil_tenant",))
    lease.rollback()
    lease.close()

    # Next attempt to checkout must fail and discard the poisoned connection
    with pytest.raises(PostgresRuntimeRoleError, match="runtime role safety check failed"):
        factory.connect()

    assert connection.closed, "Poisoned connection must be discarded and closed"
    assert pool.snapshot.total == 0
    pool.close()
