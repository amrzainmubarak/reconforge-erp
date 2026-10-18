"""Versioned cost claims, held production and inspected native receipt ownership."""

import sqlalchemy as sa

from alembic import op
from reconforge.infrastructure.postgres_manufacturing_execution_v2_schema import DOWNGRADE_SQL, UPGRADE_SQL
from reconforge.infrastructure.postgres_wave5_permission_schema import permission_downgrade_sql, permission_upgrade_sql

revision = "0138_pg_manufacturing_v2"
down_revision = "0136_pg_inventory_scope"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The owned schema installs core ownership gates after its claim tables.
    op.execute(sa.text(UPGRADE_SQL))
    op.execute(sa.text(permission_upgrade_sql("manufacturing_execution_v2")))


def downgrade() -> None:
    op.execute(sa.text(DOWNGRADE_SQL))
    op.execute(sa.text(permission_downgrade_sql("manufacturing_execution_v2")))
