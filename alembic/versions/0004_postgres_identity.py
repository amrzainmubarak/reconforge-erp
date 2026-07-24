"""Add tenant-scoped PostgreSQL identity and session storage."""

from __future__ import annotations

from alembic import op
from reconforge_migration_sql import load_postgres_schema_sql

POSTGRES_IDENTITY_SCHEMA_SQL = load_postgres_schema_sql(
    "reconforge.infrastructure.postgres_identity",
    "POSTGRES_IDENTITY_SCHEMA_SQL",
)

revision = "0004_postgres_identity"
down_revision = "0003_postgres_ledger"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Install tenant-scoped users, RBAC assignments, and hashed sessions."""

    op.execute(POSTGRES_IDENTITY_SCHEMA_SQL)


def downgrade() -> None:
    """Drop the identity boundary after explicit operator approval."""

    op.execute("DROP TABLE IF EXISTS reconforge.identity_sessions")
    op.execute("DROP TABLE IF EXISTS reconforge.identity_user_roles")
    op.execute("DROP TABLE IF EXISTS reconforge.identity_role_permissions")
    op.execute("DROP TABLE IF EXISTS reconforge.identity_users")
    op.execute("DROP TABLE IF EXISTS reconforge.identity_permissions")
    op.execute("DROP TABLE IF EXISTS reconforge.identity_roles")
