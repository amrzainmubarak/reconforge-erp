"""Retain source-owned native acquisition, depreciation and disposal."""
import sqlalchemy as sa

from alembic import op
from reconforge.infrastructure.postgres_fixed_assets_schema import DOWNGRADE_SQL, UPGRADE_SQL

revision = "0122_pg_fixed_assets"
down_revision = "0121_pg_landed_cost"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text(UPGRADE_SQL))


def downgrade() -> None:
    op.execute(sa.text(DOWNGRADE_SQL))
