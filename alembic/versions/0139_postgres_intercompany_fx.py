"""Original-rate paired foreign trade, settlement, revaluation and group translation."""

import sqlalchemy as sa

from alembic import op
from reconforge.infrastructure.postgres_fx_conversion_sql import DOWNGRADE_SQL as FX_DOWNGRADE_SQL
from reconforge.infrastructure.postgres_fx_conversion_sql import UPGRADE_SQL as FX_UPGRADE_SQL
from reconforge.infrastructure.postgres_intercompany_fx_schema import DOWNGRADE_SQL, UPGRADE_SQL
from reconforge.infrastructure.postgres_wave5_permission_schema import permission_downgrade_sql, permission_upgrade_sql

revision = "0139_pg_intercompany_fx"
down_revision = "0138_pg_manufacturing_v2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text(FX_UPGRADE_SQL))
    op.execute(sa.text(UPGRADE_SQL))
    op.execute(sa.text(permission_upgrade_sql("intercompany_fx")))


def downgrade() -> None:
    op.execute(sa.text(DOWNGRADE_SQL))
    op.execute(sa.text(permission_downgrade_sql("intercompany_fx")))
    op.execute(sa.text(FX_DOWNGRADE_SQL))
