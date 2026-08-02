from __future__ import annotations

import importlib.util
import inspect
from pathlib import Path

from reconforge.application.consolidation_close import ConsolidationCloseRepositoryProtocol
from reconforge.infrastructure.postgres_consolidation_close import (
    POSTGRES_CONSOLIDATION_CLOSE_SCHEMA_SQL,
    PostgresConsolidationCloseRepository,
)

ROOT = Path(__file__).resolve().parents[1]


def test_postgres_consolidation_close_schema_is_tenant_scoped_and_exact() -> None:
    schema = POSTGRES_CONSOLIDATION_CLOSE_SCHEMA_SQL
    assert "JSONB NOT NULL" in schema
    assert "FORCE ROW LEVEL SECURITY" in schema
    assert "current_setting(''app.tenant_id'',true)" in schema
    assert "DOUBLE PRECISION" not in schema


def test_postgres_consolidation_close_migration_is_linear_and_reversible() -> None:
    path = ROOT / "alembic/versions/0055_postgres_consolidation_close.py"
    spec = importlib.util.spec_from_file_location("migration_0055", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.revision == "0055_pg_consol_close"
    assert module.down_revision == "0054_pg_consol_ownership"
    assert "DROP TABLE IF EXISTS reconforge.consolidation_close_runs" in path.read_text(encoding="utf-8")


def test_postgres_adapter_exposes_the_backend_neutral_close_port() -> None:
    required = {
        name
        for name, value in vars(ConsolidationCloseRepositoryProtocol).items()
        if callable(value) and not name.startswith("__")
    }
    assert required <= set(vars(PostgresConsolidationCloseRepository))
    for name in required:
        assert callable(getattr(PostgresConsolidationCloseRepository, name))
        assert (
            inspect.signature(getattr(PostgresConsolidationCloseRepository, name)).return_annotation
            is not inspect.Signature.empty
        )
