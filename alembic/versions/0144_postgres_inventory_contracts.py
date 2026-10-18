"""Retain accepted Inventory Core hierarchy contracts in generic quantity gates."""

import sqlalchemy as sa

from alembic import op
from reconforge.infrastructure.postgres_inventory_quantity_contracts import DOWNGRADE_SQL, UPGRADE_SQL

revision = "0144_pg_inventory_contracts"
down_revision = "0143_pg_project_billing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text(UPGRADE_SQL))


def downgrade() -> None:
    op.execute(sa.text(DOWNGRADE_SQL))
