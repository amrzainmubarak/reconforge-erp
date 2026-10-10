"""Native foreign receivables, retained tax policies and realized FX closure."""

import sqlalchemy as sa

from alembic import op
from reconforge.infrastructure.postgres_operational_fx_tax_schema import DOWNGRADE_SQL, UPGRADE_SQL

revision = "0128_pg_operational_fx_tax"
down_revision = "0127_pg_procurement_commitments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text(UPGRADE_SQL))


def downgrade() -> None:
    op.execute(sa.text(DOWNGRADE_SQL))
