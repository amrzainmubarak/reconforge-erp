"""Bound financial RLS read planning with invoker visibility predicates."""
from alembic import op
from reconforge.infrastructure.postgres_financial_read_plans import (
    POSTGRES_FINANCIAL_READ_PLANS_ROLLBACK_SQL,
    POSTGRES_FINANCIAL_READ_PLANS_SQL,
)

revision = "0129_pg_financial_read_plans"
down_revision = "0128_pg_operational_fx_tax"
branch_labels = None
depends_on = None
UPGRADE_SQL = POSTGRES_FINANCIAL_READ_PLANS_SQL
DOWNGRADE_SQL = POSTGRES_FINANCIAL_READ_PLANS_ROLLBACK_SQL


def upgrade() -> None:
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    op.execute(DOWNGRADE_SQL)
