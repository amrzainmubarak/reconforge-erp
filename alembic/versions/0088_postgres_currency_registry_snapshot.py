"""Persist immutable tenant-scoped currency-registry snapshots."""

from __future__ import annotations

from alembic import op
from reconforge_migration_sql import load_postgres_schema_sql

POSTGRES_CURRENCY_REGISTRY_SNAPSHOT_SCHEMA_SQL = load_postgres_schema_sql(
    "reconforge.infrastructure.postgres_master_data_application",
    "POSTGRES_CURRENCY_REGISTRY_SNAPSHOT_SCHEMA_SQL",
)

revision = "0088_pg_currency_snapshot"
down_revision = "0087_pg_currency_binding"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(POSTGRES_CURRENCY_REGISTRY_SNAPSHOT_SCHEMA_SQL)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS reconforge.currency_registry_snapshots")
