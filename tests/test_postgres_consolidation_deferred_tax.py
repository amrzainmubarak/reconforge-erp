from __future__ import annotations

from pathlib import Path

from reconforge.infrastructure.postgres_consolidation_deferred_tax import (
    POSTGRES_CONSOLIDATION_DEFERRED_TAX_SCHEMA_SQL,
)

ROOT = Path(__file__).resolve().parents[1]


def test_postgres_deferred_tax_schema_is_non_posting_tenant_rls_and_append_only() -> None:
    sql = POSTGRES_CONSOLIDATION_DEFERRED_TAX_SCHEMA_SQL
    required = (
        "CREATE TABLE IF NOT EXISTS reconforge.consolidation_deferred_tax_artifacts",
        "request_payload JSONB",
        "result_payload JSONB",
        "result_payload->>'posted' = 'false'",
        "UNIQUE (tenant_id, result_digest)",
        "ENABLE ROW LEVEL SECURITY",
        "FORCE ROW LEVEL SECURITY",
        "guard_consolidation_deferred_tax_artifact",
        "consolidation deferred-tax artifacts are immutable",
        "consolidation deferred-tax artifacts cannot be deleted",
    )
    assert all(fragment in sql for fragment in required)


def test_postgres_deferred_tax_migration_is_linear_and_refuses_data_loss() -> None:
    migration = (
        ROOT / "alembic" / "versions" / "0065_postgres_consolidation_deferred_tax.py"
    ).read_text(encoding="utf-8")
    assert 'revision = "0065_pg_deferred_tax"' in migration
    assert 'down_revision = "0064_pg_close_ic_links"' in migration
    assert "refusing to discard consolidation deferred-tax evidence" in migration
