"""Close original unissued receipt removal with supplier debit and retained costs."""
import sqlalchemy as sa

from alembic import op
from reconforge.infrastructure.postgres_supplier_returns_schema import DOWNGRADE_SQL, UPGRADE_SQL

revision = "0130_pg_supplier_returns"
down_revision = "0129_pg_financial_read_plans"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text(UPGRADE_SQL))


def downgrade() -> None:
    op.execute(sa.text(DOWNGRADE_SQL))
