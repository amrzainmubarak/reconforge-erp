"""Atomic paired intercompany books and native group elimination journals."""

import sqlalchemy as sa

from alembic import op
from reconforge.infrastructure.postgres_intercompany_operations_schema import DOWNGRADE_SQL, UPGRADE_SQL
from reconforge.infrastructure.postgres_wave5_permission_schema import permission_downgrade_sql, permission_upgrade_sql

revision = "0134_pg_intercompany_operations"
down_revision = "0133_pg_manufacturing_execution"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text(UPGRADE_SQL))
    op.execute(sa.text(permission_upgrade_sql("intercompany_operations")))


def downgrade() -> None:
    op.execute(sa.text(DOWNGRADE_SQL))
    op.execute(sa.text(permission_downgrade_sql("intercompany_operations")))
