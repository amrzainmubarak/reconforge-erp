from __future__ import annotations

from pathlib import Path

from reconforge.infrastructure.postgres_consolidation_impairment import (
    POSTGRES_CONSOLIDATION_IMPAIRMENT_SCHEMA_SQL,
)
from reconforge.infrastructure.postgres_consolidation_impairment_deferred_tax_scope import (
    POSTGRES_CONSOLIDATION_IMPAIRMENT_DEFERRED_TAX_SCOPE_SCHEMA_SQL,
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


def test_impairment_deferred_tax_scope_migration_is_hierarchy_bound() -> None:
    migration = (
        ROOT / "alembic" / "versions" / "0077_postgres_consolidation_impairment_deferred_tax_scope.py"
    ).read_text(encoding="utf-8")
    sql = POSTGRES_CONSOLIDATION_IMPAIRMENT_DEFERRED_TAX_SCOPE_SCHEMA_SQL
    assert 'revision = "0077_pg_imp_tax_scope"' in migration
    assert 'down_revision = "0076_pg_consolidation_ppa_scope"' in migration
    assert sql.count("ADD COLUMN IF NOT EXISTS organization_id") == 2
    assert sql.count("ADD COLUMN IF NOT EXISTS legal_entity_id") == 2
    assert "consolidation_impairment_scope_result_digest_key" in sql
    assert "consolidation_deferred_tax_scope_result_digest_key" in sql
    assert "current_setting('app.organization_id'" in sql
    assert "current_setting('app.legal_entity_id'" in sql
    assert "DROP COLUMN IF EXISTS organization_id" in migration
    assert "DROP COLUMN IF EXISTS legal_entity_id" in migration
    assert "refusing to discard consolidation impairment hierarchy attribution" in migration
    assert "refusing to discard consolidation deferred-tax hierarchy attribution" in migration
