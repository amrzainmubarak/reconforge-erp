"""Database-owned native evidence captures and scalable exact report snapshots."""

import sqlalchemy as sa

from alembic import op
from reconforge.infrastructure.postgres_financial_reporting_snapshot_schema import DOWNGRADE_SQL, UPGRADE_SQL

revision = "0118_pg_financial_report_capture"
down_revision = "0117_pg_procurement_multiline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text(UPGRADE_SQL))


def downgrade() -> None:
    op.execute(sa.text(DOWNGRADE_SQL))
