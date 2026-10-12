"""Restrict native inventory history to its original workspace and entity."""

import sqlalchemy as sa

from alembic import op
from reconforge.infrastructure.postgres_inventory_scope import DOWNGRADE_SQL, UPGRADE_SQL

revision = "0136_pg_inventory_scope"
down_revision = "0135_pg_procurement_sourcing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text(UPGRADE_SQL))


def downgrade() -> None:
    op.execute(sa.text(DOWNGRADE_SQL))
