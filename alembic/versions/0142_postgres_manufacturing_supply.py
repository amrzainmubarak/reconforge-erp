"""Original net-supply custody, native purchasing and atomic production handoff."""

import sqlalchemy as sa

from alembic import op
from reconforge.infrastructure.postgres_manufacturing_supply_plan_schema import DOWNGRADE_SQL, UPGRADE_SQL
from reconforge.infrastructure.postgres_wave5_permission_schema import permission_downgrade_sql, permission_upgrade_sql

revision = "0142_pg_manufacturing_supply"
down_revision = "0141_pg_accrual_deferral"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Owned source tables precede the shared native quantity directory;
    # source closure and native purchase/handoff contracts follow it.
    op.execute(sa.text(UPGRADE_SQL))
    op.execute(sa.text(permission_upgrade_sql("manufacturing_supply_plan")))


def downgrade() -> None:
    op.execute(sa.text(DOWNGRADE_SQL))
    op.execute(sa.text(permission_downgrade_sql("manufacturing_supply_plan")))
