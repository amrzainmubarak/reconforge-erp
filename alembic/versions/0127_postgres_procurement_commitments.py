"""Bind native purchase obligations and AP accruals to approved appropriations."""
import sqlalchemy as sa

from alembic import op
from reconforge.infrastructure.postgres_procurement_commitments_schema import DOWNGRADE_SQL, UPGRADE_SQL

revision = "0127_pg_procurement_commitments"
down_revision = "0125_pg_landed_cost_cancellation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text(UPGRADE_SQL))


def downgrade() -> None:
    op.execute(sa.text(DOWNGRADE_SQL))
