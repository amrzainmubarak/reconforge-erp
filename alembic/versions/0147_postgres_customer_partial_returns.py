"""Bind repeated partial stock credits to existing FIFO, AR and GL owners."""

import sqlalchemy as sa

from alembic import op
from reconforge.infrastructure.postgres_customer_partial_return_shared_hooks import (
    DOWNGRADE_PREFLIGHT_SQL,
)
from reconforge.infrastructure.postgres_customer_partial_return_shared_hooks import (
    DOWNGRADE_SQL as SHARED_DOWNGRADE_SQL,
)
from reconforge.infrastructure.postgres_customer_partial_return_shared_hooks import (
    UPGRADE_SQL as SHARED_UPGRADE_SQL,
)
from reconforge.infrastructure.postgres_customer_partial_return_transfer_hooks import (
    DOWNGRADE_SQL as TRANSFER_DOWNGRADE_SQL,
)
from reconforge.infrastructure.postgres_customer_partial_return_transfer_hooks import (
    UPGRADE_SQL as TRANSFER_UPGRADE_SQL,
)
from reconforge.infrastructure.postgres_customer_partial_returns_schema import DOWNGRADE_SQL, UPGRADE_SQL

revision = "0147_pg_customer_partial_returns"
down_revision = "0146_pg_inventory_transfer"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text(UPGRADE_SQL))
    op.execute(sa.text(SHARED_UPGRADE_SQL))
    op.execute(sa.text(TRANSFER_UPGRADE_SQL))


def downgrade() -> None:
    op.execute(sa.text(DOWNGRADE_PREFLIGHT_SQL))
    op.execute(sa.text(TRANSFER_DOWNGRADE_SQL))
    op.execute(sa.text(SHARED_DOWNGRADE_SQL))
    op.execute(sa.text(DOWNGRADE_SQL))
