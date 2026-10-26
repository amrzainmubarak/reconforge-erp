"""Bind reviewed enterprise sources to the existing canonical posting owner."""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op
from reconforge.infrastructure.postgres_enterprise_finance_bridge_schema import DOWNGRADE_SQL, UPGRADE_SQL

revision = "0154_pg_enterprise_finance"
down_revision = "0153_pg_enterprise_modules"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.execute(sa.text(UPGRADE_SQL))

def downgrade() -> None:
    op.execute(sa.text(DOWNGRADE_SQL))
