"""Partial stock receiving and exact payable tranches share a governed owner."""
import sqlalchemy as sa

from alembic import op
from reconforge.infrastructure.postgres_procurement_partial_schema import DOWNGRADE_SQL, UPGRADE_SQL

revision = "0114_pg_procurement_partial"
down_revision = "0113_pg_stock_sales"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text(UPGRADE_SQL))


def downgrade() -> None:
    op.execute(sa.text(DOWNGRADE_SQL))
