"""Immutable sourcing decisions awarded into native budget-bound orders."""

import sqlalchemy as sa

from alembic import op
from reconforge.infrastructure.postgres_procurement_sourcing_schema import DOWNGRADE_SQL, UPGRADE_SQL
from reconforge.infrastructure.postgres_wave5_permission_schema import permission_downgrade_sql, permission_upgrade_sql

revision = "0135_pg_procurement_sourcing"
down_revision = "0134_pg_intercompany_operations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text(UPGRADE_SQL))
    op.execute(sa.text(permission_upgrade_sql("procurement_sourcing")))


def downgrade() -> None:
    op.execute(sa.text(DOWNGRADE_SQL))
    op.execute(sa.text(permission_downgrade_sql("procurement_sourcing")))
