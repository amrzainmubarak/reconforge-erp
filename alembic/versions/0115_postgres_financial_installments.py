"""Compose reviewed partial AP payments with immutable native allocations."""
import sqlalchemy as sa

from alembic import op
from reconforge.infrastructure.postgres_financial_installments_schema import DOWNGRADE_SQL, UPGRADE_SQL

revision = "0115_pg_financial_installments"
down_revision = "0114_pg_procurement_partial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text(UPGRADE_SQL))


def downgrade() -> None:
    op.execute(sa.text(DOWNGRADE_SQL))
