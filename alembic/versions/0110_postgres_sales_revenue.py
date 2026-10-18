"""Governed service sales through native AR and operational GL."""

from alembic import op
from reconforge.infrastructure.postgres_sales_revenue_schema import (
    POSTGRES_SALES_REVENUE_DOWNGRADE_SQL,
    POSTGRES_SALES_REVENUE_SCHEMA_SQL,
)

revision = "0110_pg_sales_revenue"
down_revision = "0109_pg_operational_finance"
branch_labels = None
depends_on = None


def _authority() -> None:
    op.execute("""DO $sales$ BEGIN
    IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname=current_user AND (rolsuper OR rolbypassrls))
    THEN RAISE EXCEPTION 'Sales migration requires forced-RLS administrator authority.'; END IF;
    END $sales$;""")


def upgrade() -> None:
    _authority()
    op.execute(POSTGRES_SALES_REVENUE_SCHEMA_SQL)


def downgrade() -> None:
    _authority()
    op.execute(POSTGRES_SALES_REVENUE_DOWNGRADE_SQL)
