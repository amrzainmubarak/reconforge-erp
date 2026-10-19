"""Enterprise ERP v1.0 tables: Shop Floor, Project WBS, MPS, Consolidation, and Intercompany Elimination."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op
from reconforge.infrastructure.postgres_enterprise_erp_v1_schema import (
    DOWNGRADE_SQL,
    UPGRADE_SQL,
)

revision = "0151_pg_enterprise_erp_v1_tables"
down_revision = "0150_pg_native_query_plans"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text(UPGRADE_SQL))


def downgrade() -> None:
    op.execute(sa.text(DOWNGRADE_SQL))
