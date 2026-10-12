"""Scope native original stock-sale revenue inverse owner discovery."""

import sqlalchemy as sa

from alembic import op
from reconforge.infrastructure.postgres_stock_sales_reversal_dispatch_schema import DOWNGRADE_SQL, UPGRADE_SQL

revision = "0132_pg_stock_inverse_dispatch"
down_revision = "0131_pg_fx_revaluation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text(UPGRADE_SQL))


def downgrade() -> None:
    op.execute(sa.text(DOWNGRADE_SQL))
