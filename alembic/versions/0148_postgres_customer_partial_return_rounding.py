"""Version remaining-value customer return allocations without rewriting v1 history."""

import sqlalchemy as sa

from alembic import op
from reconforge.infrastructure.postgres_customer_partial_return_rounding_schema import (
    DOWNGRADE_SQL,
    UPGRADE_SQL,
)

revision = "0148_pg_partial_return_rounding"
down_revision = "0147_pg_customer_partial_returns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text(UPGRADE_SQL))


def downgrade() -> None:
    # The SQL contract performs retained-v2 preflight before any mutation.
    op.execute(sa.text(DOWNGRADE_SQL))
