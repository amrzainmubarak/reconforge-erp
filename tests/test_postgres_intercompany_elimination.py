from __future__ import annotations

from pathlib import Path

from reconforge.infrastructure.postgres_intercompany_elimination import (
    POSTGRES_INTERCOMPANY_ELIMINATION_SCHEMA_SQL,
)

ROOT = Path(__file__).resolve().parents[1]


def test_postgres_intercompany_schema_is_workspace_rls_and_append_only() -> None:
    sql = POSTGRES_INTERCOMPANY_ELIMINATION_SCHEMA_SQL
    required = (
        "CREATE TABLE IF NOT EXISTS reconforge.intercompany_elimination_artifacts",
        "workspace_id TEXT NOT NULL",
        "request_payload JSONB",
        "result_payload JSONB",
        "UNIQUE (tenant_id, workspace_id, result_digest)",
        "FOREIGN KEY (tenant_id, workspace_id)",
        "ENABLE ROW LEVEL SECURITY",
        "FORCE ROW LEVEL SECURITY",
        "guard_intercompany_elimination_artifact",
        "intercompany elimination artifacts are immutable",
        "intercompany elimination artifacts cannot be deleted",
    )
    assert all(fragment in sql for fragment in required)


def test_postgres_intercompany_migration_is_linear_and_refuses_data_loss() -> None:
    migration = (ROOT / "alembic" / "versions" / "0063_postgres_intercompany_eliminations.py").read_text(
        encoding="utf-8"
    )
    assert 'revision = "0063_pg_ic_elimination"' in migration
    assert 'down_revision = "0062_pg_outbox_consumer"' in migration
    assert "refusing to discard intercompany elimination evidence" in migration
