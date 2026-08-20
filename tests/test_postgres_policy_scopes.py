from __future__ import annotations

from pathlib import Path

from reconforge.infrastructure.postgres_policy_scopes import (
    POSTGRES_POLICY_SCOPE_AMOUNT_BOUNDS_MIGRATION_SQL,
    POSTGRES_POLICY_SCOPE_SCHEMA_SQL,
)

ROOT = Path(__file__).resolve().parents[1]


def test_postgres_policy_scopes_are_dimension_bound_rls_and_append_only() -> None:
    sql = POSTGRES_POLICY_SCOPE_SCHEMA_SQL
    required = (
        "CREATE TABLE IF NOT EXISTS reconforge.identity_role_permission_scopes",
        "workspace_id TEXT",
        "entity_id TEXT",
        "period_id TEXT",
        "region_id TEXT",
        "data_classification TEXT",
        "identity_role_permission_scopes_dimension_required",
        "identity_role_permission_scopes_state_consistent",
        "FOREIGN KEY (tenant_id, role_id, permission_name)",
        "ENABLE ROW LEVEL SECURITY",
        "FORCE ROW LEVEL SECURITY",
        "guard_identity_role_permission_scope",
        "policy permission scopes are append-only",
        "only one active-to-revoked transition",
    )
    assert all(fragment in sql for fragment in required)


def test_postgres_policy_scope_amount_migration_is_exact_and_immutable() -> None:
    migration = (ROOT / "alembic" / "versions" / "0059_postgres_policy_scope_amount_bounds.py").read_text(
        encoding="utf-8"
    )
    assert 'revision = "0059_pg_policy_amt_bounds"' in migration
    assert 'down_revision = "0058_pg_policy_permission_scopes"' in migration
    sql = POSTGRES_POLICY_SCOPE_AMOUNT_BOUNDS_MIGRATION_SQL
    assert "minimum_amount NUMERIC" in sql
    assert "maximum_amount NUMERIC" in sql
    assert "refusing to discard policy permission amount-bound evidence" in migration
    assert "minimum_amount IS DISTINCT FROM OLD.minimum_amount" in sql
    assert "maximum_amount IS DISTINCT FROM OLD.maximum_amount" in sql


def test_policy_scope_migration_is_linear_and_refuses_data_loss_on_downgrade() -> None:
    migration = (ROOT / "alembic" / "versions" / "0058_postgres_policy_permission_scopes.py").read_text(
        encoding="utf-8"
    )
    assert 'revision = "0058_pg_policy_permission_scopes"' in migration
    assert 'down_revision = "0057_pg_consol_journal_lines"' in migration
    assert "refusing to discard policy permission scope evidence" in migration
