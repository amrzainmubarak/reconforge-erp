from __future__ import annotations

from pathlib import Path

from reconforge.infrastructure.postgres_consolidation_ppa import POSTGRES_CONSOLIDATION_PPA_SCHEMA_SQL
from reconforge.infrastructure.postgres_consolidation_ppa_scope import (
    POSTGRES_CONSOLIDATION_PPA_SCOPE_SCHEMA_SQL,
)

ROOT = Path(__file__).resolve().parents[1]


def test_postgres_ppa_schema_is_non_posting_tenant_rls_and_append_only() -> None:
    sql = POSTGRES_CONSOLIDATION_PPA_SCHEMA_SQL
    required = (
        "CREATE TABLE IF NOT EXISTS reconforge.consolidation_ppa_artifacts",
        "request_payload JSONB",
        "result_payload JSONB",
        "result_payload->>'posted' = 'false'",
        "UNIQUE (tenant_id, result_digest)",
        "ENABLE ROW LEVEL SECURITY",
        "FORCE ROW LEVEL SECURITY",
        "guard_consolidation_ppa_artifact",
        "consolidation PPA artifacts are immutable",
        "consolidation PPA artifacts cannot be deleted",
    )
    assert all(fragment in sql for fragment in required)


def test_postgres_ppa_migration_is_linear_and_refuses_data_loss() -> None:
    migration = (ROOT / "alembic" / "versions" / "0060_postgres_consolidation_ppa.py").read_text(
        encoding="utf-8"
    )
    assert 'revision = "0060_pg_consolidation_ppa"' in migration
    assert 'down_revision = "0059_pg_policy_amt_bounds"' in migration
    assert "refusing to discard consolidation PPA evidence" in migration


def test_postgres_ppa_scope_migration_is_hierarchy_bound_and_reversible() -> None:
    migration = (ROOT / "alembic/versions/0076_postgres_consolidation_ppa_scope.py").read_text(encoding="utf-8")
    sql = POSTGRES_CONSOLIDATION_PPA_SCOPE_SCHEMA_SQL
    assert 'revision = "0076_pg_consolidation_ppa_scope"' in migration
    assert 'down_revision = "0075_pg_job_organization_scope"' in migration
    assert "organization_id" in sql
    assert "legal_entity_id" in sql
    assert "consolidation_ppa_scope_result_digest_key" in sql
    assert "current_setting('app.organization_id'" in sql
    assert "current_setting('app.legal_entity_id'" in sql
    assert "DROP COLUMN IF EXISTS organization_id" in migration
    assert "DROP COLUMN IF EXISTS legal_entity_id" in migration
