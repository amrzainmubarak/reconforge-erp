"""Add tenant-scoped PostgreSQL consolidation ownership masters."""

from __future__ import annotations

from alembic import op
from reconforge.infrastructure.postgres_consolidation_ownership import POSTGRES_CONSOLIDATION_OWNERSHIP_SCHEMA_SQL

revision = "0054_pg_consol_ownership"
down_revision = "0053_audit_administration_acl"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(POSTGRES_CONSOLIDATION_OWNERSHIP_SCHEMA_SQL)


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS reconforge.consolidation_ownership_interests CASCADE;
        DROP FUNCTION IF EXISTS reconforge.consolidation_ownership_immutable_guard();
        """
    )
