"""Historical foreign monetary closing valuation and exact reviewed inverse."""

import sqlalchemy as sa

from alembic import op
from reconforge.infrastructure.postgres_operational_fx_revaluation_schema import DOWNGRADE_SQL, UPGRADE_SQL

revision = "0131_pg_fx_revaluation"
down_revision = "0130_pg_supplier_returns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text(UPGRADE_SQL))


def downgrade() -> None:
    op.execute(sa.text(DOWNGRADE_SQL))
