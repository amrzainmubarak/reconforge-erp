"""Compose reviewed stock purchase-to-pay with retained source and command evidence."""
import sqlalchemy as sa

from alembic import op
from reconforge.infrastructure.postgres_procurement_operations_schema import DOWNGRADE_SQL, UPGRADE_SQL

revision = "0111_pg_procurement_operations"
down_revision = "0110_pg_sales_revenue"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text(UPGRADE_SQL))


def downgrade() -> None:
    op.execute(sa.text(DOWNGRADE_SQL))
