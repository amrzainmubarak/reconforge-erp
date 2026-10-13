"""Retain complete native closures while removing proven duplicate delegates."""
import sqlalchemy as sa

from alembic import op
from reconforge.infrastructure.postgres_manufacturing_supply_closure import DOWNGRADE_SQL, UPGRADE_SQL

revision = "0145_pg_supply_closure"
down_revision = "0144_pg_inventory_contracts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text(UPGRADE_SQL))


def downgrade() -> None:
    op.execute(sa.text(DOWNGRADE_SQL))
