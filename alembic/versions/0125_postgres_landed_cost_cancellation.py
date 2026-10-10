"""Retain unreceived charge cancellation and release its exact reservations."""

import sqlalchemy as sa

from alembic import op
from reconforge.infrastructure.postgres_landed_cost_cancellation_schema import DOWNGRADE_SQL, UPGRADE_SQL

revision = "0125_pg_landed_cost_cancellation"
down_revision = "0124_pg_collection_cancellation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text(UPGRADE_SQL))


def downgrade() -> None:
    op.execute(sa.text(DOWNGRADE_SQL))
