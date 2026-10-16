"""Bind fixed monetary Stock originals and partial corrections to existing owners."""

import sqlalchemy as sa

from alembic import op
from reconforge.infrastructure.postgres_monetary_customer_returns_schema import DOWNGRADE_SQL, UPGRADE_SQL
from reconforge.infrastructure.postgres_monetary_installation import installation_preflight_sql
from reconforge.infrastructure.postgres_monetary_inventory_shared_hooks import (
    DOWNGRADE_SQL as PHYSICAL_DOWNGRADE_SQL,
)
from reconforge.infrastructure.postgres_monetary_inventory_shared_hooks import (
    UPGRADE_SQL as PHYSICAL_UPGRADE_SQL,
)
from reconforge.infrastructure.postgres_monetary_inventory_shared_hooks import preflight as physical_preflight
from reconforge.infrastructure.postgres_monetary_stock_schema import (
    DOWNGRADE_PREFLIGHT_SQL,
    DROP_STORAGE_SQL,
    STORAGE_SQL,
)
from reconforge.infrastructure.postgres_monetary_stock_shared_hooks import DOWNGRADE_SQL as STOCK_DOWNGRADE_SQL
from reconforge.infrastructure.postgres_monetary_stock_shared_hooks import UPGRADE_SQL as STOCK_UPGRADE_SQL
from reconforge.infrastructure.postgres_monetary_stock_shared_hooks import preflight as stock_preflight

revision = "0149_pg_monetary_partial_returns"
down_revision = "0148_pg_partial_return_rounding"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Reject unknown accepted148 bodies/attributes before changing any relation.
    # Alembic executes the complete revision in its existing ACID transaction.
    for statement in (stock_preflight(upgraded=False), physical_preflight(upgraded=False),
                      STORAGE_SQL, UPGRADE_SQL, STOCK_UPGRADE_SQL, PHYSICAL_UPGRADE_SQL,
                      installation_preflight_sql()):
        op.execute(sa.text(statement))


def downgrade() -> None:
    # Retained Drafts, originals or evidence require a verified compatible backup;
    # refuse before changing the accepted dispatches or removing native owners.
    for statement in (DOWNGRADE_PREFLIGHT_SQL, installation_preflight_sql(),
                      PHYSICAL_DOWNGRADE_SQL, STOCK_DOWNGRADE_SQL, DOWNGRADE_SQL, DROP_STORAGE_SQL):
        op.execute(sa.text(statement))
