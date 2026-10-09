"""Scope receipt chronology to its actual immutable FIFO item pool."""
import sqlalchemy as sa

from alembic import op
from reconforge.infrastructure.postgres_receipt_fifo_chronology import DOWNGRADE_SQL, UPGRADE_SQL

revision = "0119_pg_receipt_fifo_chronology"
down_revision = "0118_pg_financial_reporting_snapshots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text(UPGRADE_SQL))


def downgrade() -> None:
    op.execute(sa.text(DOWNGRADE_SQL))
