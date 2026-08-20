from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from reconforge.domain.consolidation_ownership_changes import prepare_ownership_change_adjustment
from reconforge.infrastructure.postgres_consolidation_ownership_change import (
    POSTGRES_CONSOLIDATION_OWNERSHIP_CHANGE_SCHEMA_SQL,
    PostgresConsolidationOwnershipChangeError,
    PostgresConsolidationOwnershipChangeRepository,
)

ROOT = Path(__file__).resolve().parents[1]


def test_postgres_ownership_change_schema_is_non_posting_tenant_rls_and_append_only() -> None:
    sql = POSTGRES_CONSOLIDATION_OWNERSHIP_CHANGE_SCHEMA_SQL
    required = (
        "CREATE TABLE IF NOT EXISTS reconforge.consolidation_ownership_change_artifacts",
        "request_payload JSONB",
        "result_payload JSONB",
        "result_payload->>'posted' = 'false'",
        "UNIQUE (tenant_id, result_digest)",
        "ENABLE ROW LEVEL SECURITY",
        "FORCE ROW LEVEL SECURITY",
        "guard_consolidation_ownership_change_artifact",
        "consolidation ownership-change artifacts are immutable",
        "consolidation ownership-change artifacts cannot be deleted",
    )
    assert all(fragment in sql for fragment in required)


def test_postgres_ownership_change_migration_is_linear_and_refuses_data_loss() -> None:
    path = ROOT / "alembic/versions/0070_postgres_consolidation_ownership_change.py"
    spec = importlib.util.spec_from_file_location("migration_0070", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.revision == "0070_pg_ownership_change"
    assert module.down_revision == "0069_pg_close_ppa_links"
    assert "refusing to discard consolidation ownership-change evidence" in path.read_text(encoding="utf-8")


def test_postgres_ownership_change_link_migration_is_linear_and_refuses_data_loss() -> None:
    path = ROOT / "alembic/versions/0071_postgres_close_ownership_change_links.py"
    spec = importlib.util.spec_from_file_location("migration_0071_contract", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.revision == "0071_pg_close_ownchg_links"
    assert module.down_revision == "0070_pg_ownership_change"
    assert "refusing to discard close/ownership-change evidence links" in path.read_text(encoding="utf-8")


def test_postgres_ownership_change_repository_rechecks_deterministic_result() -> None:
    from tests.test_consolidation_ownership_changes import _request

    request = _request()
    result = prepare_ownership_change_adjustment(request)
    payload = PostgresConsolidationOwnershipChangeRepository._verify_result(request, result)
    assert payload["posted"] is False
    assert payload["result_digest"] == result.result_digest

    with pytest.raises(PostgresConsolidationOwnershipChangeError, match="deterministic"):
        PostgresConsolidationOwnershipChangeRepository._verify_result(
            request, result.__class__(**{**result.__dict__, "request_digest": "0" * 64})
        )
