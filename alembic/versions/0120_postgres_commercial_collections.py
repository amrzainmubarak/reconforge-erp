"""Reviewed partial native AR collections with conserved stock-sale evidence."""
import sqlalchemy as sa

from alembic import op
from reconforge.infrastructure.postgres_commercial_collections_schema import DOWNGRADE_SQL, UPGRADE_SQL

revision = "0120_pg_commercial_collections"
down_revision = "0119_pg_receipt_fifo_chronology"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text(UPGRADE_SQL))


def downgrade() -> None:
    op.execute(sa.text(DOWNGRADE_SQL))
