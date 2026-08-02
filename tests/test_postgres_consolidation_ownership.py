from __future__ import annotations

import importlib.util
import inspect
from decimal import Decimal
from pathlib import Path

import pytest

from reconforge.application.consolidation_ownership import ConsolidationOwnershipRepositoryProtocol
from reconforge.domain.consolidation_lifecycle import ConsolidationOwnershipInterest
from reconforge.infrastructure.postgres_consolidation_ownership import (
    POSTGRES_CONSOLIDATION_OWNERSHIP_SCHEMA_SQL,
    PostgresConsolidationOwnershipRepository,
)
from reconforge.platform.common import PlatformError

ROOT = Path(__file__).resolve().parents[1]


def _interest() -> ConsolidationOwnershipInterest:
    return ConsolidationOwnershipInterest(
        interest_id="OWN-PG-1",
        parent_entity_code="PARENT",
        subsidiary_entity_code="SUB",
        direct_ownership_percentage=Decimal("0.80"),
        effective_from="2026-01-01",
        effective_to="",
        version="1.0.0",
        source_digest="a" * 64,
        prepared_by="ownership-preparer",
        approved_by="ownership-reviewer",
        approved_at="2026-08-01T00:00:00Z",
    )


def test_postgres_schema_is_tenant_scoped_immutable_and_exact() -> None:
    schema = POSTGRES_CONSOLIDATION_OWNERSHIP_SCHEMA_SQL
    assert "NUMERIC NOT NULL" in schema
    assert "DOUBLE PRECISION" not in schema
    assert "FORCE ROW LEVEL SECURITY" in schema
    assert "current_setting('app.tenant_id',true)" in schema
    assert "consolidation ownership interests are immutable" in schema
    assert "prepared_by<>approved_by" in schema


def test_postgres_migration_is_linear_and_reversible() -> None:
    path = ROOT / "alembic/versions/0054_postgres_consolidation_ownership.py"
    spec = importlib.util.spec_from_file_location("migration_0054", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.revision == "0054_pg_consol_ownership"
    assert module.down_revision == "0053_audit_administration_acl"
    source = path.read_text(encoding="utf-8")
    assert "DROP TABLE IF EXISTS reconforge.consolidation_ownership_interests CASCADE" in source


def test_postgres_adapter_exposes_the_backend_neutral_ownership_port() -> None:
    methods = [
        name
        for name, value in vars(ConsolidationOwnershipRepositoryProtocol).items()
        if callable(value) and not name.startswith("__")
    ]
    assert {"save_interest", "resolve_effective"} <= set(methods)
    for name in methods:
        assert inspect.signature(getattr(PostgresConsolidationOwnershipRepository, name)) == inspect.signature(
            getattr(ConsolidationOwnershipRepositoryProtocol, name)
        )


def test_postgres_adapter_refuses_actor_mismatch_before_connection_use() -> None:
    class _UnusedConnection:
        def transaction(self):
            raise AssertionError("connection must not be used")

    with pytest.raises(PlatformError, match="preparer"):
        PostgresConsolidationOwnershipRepository(_UnusedConnection(), "tenant_a").save_interest(
            _interest(), group_code="GLOBAL-GROUP", actor_label="different-actor"
        )
