"""Register module storage and enforce tenant/workspace isolation without data loss."""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op
from reconforge.infrastructure.postgres_enterprise_modules_schema import DOWNGRADE_SQL, UPGRADE_SQL

revision = "0153_pg_enterprise_modules"
down_revision = "0152_pg_performance_indexes"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.execute(sa.text(UPGRADE_SQL))

def downgrade() -> None:
    op.execute(sa.text(DOWNGRADE_SQL))
