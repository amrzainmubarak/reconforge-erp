"""Retained multiline purchase and supplier invoice ownership."""
import sqlalchemy as sa

from alembic import op
from reconforge.infrastructure.postgres_procurement_partial_multiline_schema import DOWNGRADE_SQL, UPGRADE_SQL

revision = "0117_pg_procurement_multiline"
down_revision = "0116_pg_stock_commerce"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text(UPGRADE_SQL))


def downgrade() -> None:
    op.execute(sa.text(DOWNGRADE_SQL))
