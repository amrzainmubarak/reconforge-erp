"""Retain native scope, review bytes and canonical values with reusable plans."""
import sqlalchemy as sa

from alembic import op
from reconforge.infrastructure.postgres_native_query_plans import DOWNGRADE_SQL, UPGRADE_SQL

revision = "0150_pg_native_query_plans"
down_revision = "0149_pg_monetary_partial_returns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text(UPGRADE_SQL))


def downgrade() -> None:
    op.execute(sa.text(DOWNGRADE_SQL))
