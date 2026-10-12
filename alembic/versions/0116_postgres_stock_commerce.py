"""Conserved multi-line commercial orders over governed native stock tranches."""
import sqlalchemy as sa

from alembic import op
from reconforge.infrastructure.postgres_stock_commerce_schema import DOWNGRADE_SQL, UPGRADE_SQL

revision = "0116_pg_stock_commerce"
down_revision = "0115_pg_financial_installments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text(UPGRADE_SQL))


def downgrade() -> None:
    op.execute(sa.text(DOWNGRADE_SQL))
