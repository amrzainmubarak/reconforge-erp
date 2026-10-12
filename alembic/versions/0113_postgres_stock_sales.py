"""Governed stock reservations, FIFO issue, COGS and customer settlement."""

import sqlalchemy as sa

from alembic import op
from reconforge.infrastructure.postgres_stock_sales_schema import (
    DOWNGRADE_STOCK_SALES_SQL,
    POSTGRES_STOCK_SALES_SCHEMA_SQL,
)

revision = "0113_pg_stock_sales"
down_revision = "0112_pg_financial_reporting"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text(POSTGRES_STOCK_SALES_SCHEMA_SQL))


def downgrade() -> None:
    op.execute(sa.text(DOWNGRADE_STOCK_SALES_SQL))
