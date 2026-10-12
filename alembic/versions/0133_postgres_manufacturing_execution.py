"""Source-owned component issue, WIP and finished-goods completion."""

import sqlalchemy as sa

from alembic import op
from reconforge.infrastructure.postgres_manufacturing_execution_schema import DOWNGRADE_SQL, UPGRADE_SQL
from reconforge.infrastructure.postgres_wave5_permission_schema import permission_downgrade_sql, permission_upgrade_sql

revision = "0133_pg_manufacturing_execution"
down_revision = "0132_pg_stock_inverse_dispatch"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text(UPGRADE_SQL))
    op.execute(sa.text(permission_upgrade_sql("manufacturing_execution")))


def downgrade() -> None:
    op.execute(sa.text(DOWNGRADE_SQL))
    op.execute(sa.text(permission_downgrade_sql("manufacturing_execution")))
