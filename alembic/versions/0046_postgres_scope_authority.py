"""Add durable principal authority over execution scopes."""

from __future__ import annotations

from alembic import op
from reconforge_migration_sql import load_postgres_schema_sql

POSTGRES_SCOPE_AUTHORITY_SCHEMA_SQL = load_postgres_schema_sql(
    "reconforge.infrastructure.postgres_scope_authority", "POSTGRES_SCOPE_AUTHORITY_SCHEMA_SQL"
)

revision = "0046_postgres_scope_authority"
down_revision = "0045_postgres_workspace_scope"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(POSTGRES_SCOPE_AUTHORITY_SCHEMA_SQL)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS reconforge.principal_scope_grants")
    op.execute("DROP FUNCTION IF EXISTS reconforge.principal_scope_grant_guard()")
