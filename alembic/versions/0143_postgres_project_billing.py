"""Source-owned approved Project time, native AR and partial cash settlement."""

import sqlalchemy as sa

from alembic import op
from reconforge.infrastructure.postgres_project_time_billing_schema import DOWNGRADE_SQL, UPGRADE_SQL
from reconforge.infrastructure.postgres_wave5_permission_schema import permission_downgrade_sql, permission_upgrade_sql

revision = "0143_pg_project_billing"
down_revision = "0142_pg_manufacturing_supply"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text(UPGRADE_SQL))
    op.execute(sa.text(permission_upgrade_sql("project_time_billing")))


def downgrade() -> None:
    op.execute(sa.text(DOWNGRADE_SQL))
    op.execute(sa.text(permission_downgrade_sql("project_time_billing")))
