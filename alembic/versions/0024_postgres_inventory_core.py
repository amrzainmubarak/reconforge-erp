"""Add tenant-scoped governed Inventory Core storage."""

from alembic import op
from reconforge_migration_sql import load_postgres_schema_sql

POSTGRES_INVENTORY_CORE_SCHEMA_SQL = load_postgres_schema_sql(
    "reconforge.infrastructure.postgres_inventory_core", "POSTGRES_INVENTORY_CORE_SCHEMA_SQL"
)
revision = "0024_postgres_inventory_core"
down_revision = "0023_postgres_matching_app"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(POSTGRES_INVENTORY_CORE_SCHEMA_SQL)


def downgrade() -> None:
    for table in (
        "inventory_movement_lines", "inventory_movements", "inventory_lots",
        "inventory_locations", "inventory_warehouses", "inventory_items",
        "inventory_units_of_measure",
    ):
        op.execute(f"DROP TABLE IF EXISTS reconforge.{table}")
    op.execute("DROP FUNCTION IF EXISTS reconforge.inventory_guard_movement_header()")
    op.execute("DROP FUNCTION IF EXISTS reconforge.inventory_guard_movement_line()")
