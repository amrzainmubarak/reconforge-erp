"""Paid landed costs and atomic multi-line capitalized receiving."""
import sqlalchemy as sa

from alembic import op
from reconforge.infrastructure.postgres_landed_cost_schema import DOWNGRADE_SQL, UPGRADE_SQL

revision = "0121_pg_landed_cost"
down_revision = "0120_pg_commercial_collections"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text(UPGRADE_SQL))


def downgrade() -> None:
    op.execute(sa.text(DOWNGRADE_SQL))
