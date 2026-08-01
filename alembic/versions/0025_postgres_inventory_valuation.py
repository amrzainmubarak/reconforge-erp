"""PostgreSQL governed FIFO inventory valuation aggregate."""

from alembic import op
from reconforge.infrastructure.postgres_inventory_valuation import POSTGRES_INVENTORY_VALUATION_SCHEMA_SQL

revision = "0025_postgres_inventory_value"
down_revision = "0024_postgres_inventory_core"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(POSTGRES_INVENTORY_VALUATION_SCHEMA_SQL)


def downgrade() -> None:
    for table in (
        "inventory_layer_consumptions",
        "inventory_cost_layers",
        "inventory_valuation_lines",
        "inventory_valuation_input_costs",
        "inventory_valuation_documents",
        "inventory_valuation_policies",
    ):
        op.execute(f"DROP TABLE IF EXISTS reconforge.{table} CASCADE")
    op.execute("DROP FUNCTION IF EXISTS reconforge.inventory_cost_layer_guard()")
    op.execute("DROP FUNCTION IF EXISTS reconforge.inventory_layer_consumption_guard()")
    op.execute("DROP FUNCTION IF EXISTS reconforge.inventory_valuation_guard()")
