"""Bind governed same-entity transfers to original quantity and native custody."""

import sqlalchemy as sa

from alembic import op
from reconforge.infrastructure.postgres_inventory_transfer_integration import DOWNGRADE_SQL as CORE_DOWNGRADE_SQL
from reconforge.infrastructure.postgres_inventory_transfer_integration import SOURCE_DOWNGRADE_PREFLIGHT_SQL
from reconforge.infrastructure.postgres_inventory_transfer_integration import UPGRADE_SQL as CORE_UPGRADE_SQL
from reconforge.infrastructure.postgres_inventory_transfer_schema import DOWNGRADE_SQL, OWNER_SQL, TABLES_SQL
from reconforge.infrastructure.postgres_wave5_permission_schema import permission_downgrade_sql, permission_upgrade_sql

revision = "0146_pg_inventory_transfer"
down_revision = "0145_pg_supply_closure"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text(TABLES_SQL))
    op.execute(sa.text(CORE_UPGRADE_SQL))
    op.execute(sa.text(OWNER_SQL))
    op.execute(sa.text(permission_upgrade_sql("inventory_transfer")))


def downgrade() -> None:
    op.execute(sa.text(SOURCE_DOWNGRADE_PREFLIGHT_SQL))
    op.execute(sa.text(permission_downgrade_sql("inventory_transfer")))
    op.execute(sa.text(CORE_DOWNGRADE_SQL))
    op.execute(sa.text(DOWNGRADE_SQL))
