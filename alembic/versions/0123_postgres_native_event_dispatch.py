"""Refresh invoker owner dispatch without modifying retained financial history."""

import sqlalchemy as sa

from alembic import op
from reconforge.infrastructure.postgres_fixed_assets_schema import REVERSE_CLOSE_SQL as ASSET_SQL
from reconforge.infrastructure.postgres_landed_cost_schema import REVERSE_CLOSE_SQL as LANDED_COST_SQL

revision = "0123_pg_native_event_dispatch"
down_revision = "0122_pg_fixed_assets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text(LANDED_COST_SQL))
    op.execute(sa.text(ASSET_SQL))


def downgrade() -> None:
    # Same signatures and no storage changes: code/storage rollback remains
    # compatible with 0122. Preserve corrected invoker dispatch instead of
    # reinstalling a known incompatible function body on retained history.
    upgrade()
