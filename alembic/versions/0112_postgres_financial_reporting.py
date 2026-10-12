"""Reviewed account classification, initial balances and source-bound financial statements."""

import sqlalchemy as sa

from alembic import op
from reconforge.infrastructure.postgres_financial_reporting_schema import DOWNGRADE_SQL, UPGRADE_SQL

revision = "0112_pg_financial_reporting"
down_revision = "0111_pg_procurement_operations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text(UPGRADE_SQL))


def downgrade() -> None:
    op.execute(sa.text(DOWNGRADE_SQL))
