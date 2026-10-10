"""Original-source whole stock credits and governed partial customer refunds."""

import sqlalchemy as sa

from alembic import op
from reconforge.infrastructure.postgres_customer_returns_schema import DOWNGRADE_SQL, UPGRADE_SQL

revision = "0126_pg_customer_returns"
down_revision = "0125_pg_landed_cost_cancellation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text(UPGRADE_SQL))


def downgrade() -> None:
    op.execute(sa.text(DOWNGRADE_SQL))
