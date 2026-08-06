from __future__ import annotations

from pathlib import Path

from reconforge.infrastructure.postgres_consolidation_impairment import (
    POSTGRES_CONSOLIDATION_IMPAIRMENT_SCHEMA_SQL,
)

ROOT = Path(__file__).resolve().parents[1]


def test_postgres_impairment_schema_is_non_posting_tenant_rls_and_append_only() -> None:
    sql = POSTGRES_CONSOLIDATION_IMPAIRMENT_SCHEMA_SQL
    required = (
        "CREATE TABLE IF NOT EXISTS reconforge.consolidation_impairment_artifacts",
        "request_payload JSONB",
        "result_payload JSONB",
        "result_payload->>'posted' = 'false'",
        "UNIQUE (tenant_id, result_digest)",
        "ENABLE ROW LEVEL SECURITY",
        "FORCE ROW LEVEL SECURITY",
        "guard_consolidation_impairment_artifact",
        "consolidation impairment artifacts are immutable",
        "consolidation impairment artifacts cannot be deleted",
    )
    assert all(fragment in sql for fragment in required)


def test_postgres_impairment_migration_is_linear_and_refuses_data_loss() -> None:
    migration = (
        ROOT / "alembic" / "versions" / "0066_postgres_consolidation_impairment.py"
    ).read_text(encoding="utf-8")
    assert 'revision = "0066_pg_impairment"' in migration
    assert 'down_revision = "0065_pg_deferred_tax"' in migration
    assert "refusing to discard consolidation impairment evidence" in migration
