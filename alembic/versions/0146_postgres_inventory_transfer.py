"""Bind governed same-entity transfers to original quantity and native custody."""

import sqlalchemy as sa

from alembic import op
from reconforge.infrastructure.postgres_inventory_transfer_integration import DOWNGRADE_SQL as CORE_DOWNGRADE_SQL
from reconforge.infrastructure.postgres_inventory_transfer_integration import UPGRADE_SQL as CORE_UPGRADE_SQL
from reconforge.infrastructure.postgres_inventory_transfer_schema import DOWNGRADE_SQL, OWNER_SQL, TABLES_SQL

revision = "0146_pg_inventory_transfer"
down_revision = "0145_pg_supply_closure"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text(TABLES_SQL))
    op.execute(sa.text(CORE_UPGRADE_SQL))
    op.execute(sa.text(OWNER_SQL))


def downgrade() -> None:
    op.execute(sa.text(CORE_DOWNGRADE_SQL))
    op.execute(sa.text(DOWNGRADE_SQL))
