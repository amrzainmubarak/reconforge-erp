"""PostgreSQL governed FIFO inventory valuation reversal aggregate."""

from alembic import op
from reconforge.infrastructure.postgres_inventory_valuation import POSTGRES_INVENTORY_VALUATION_SCHEMA_SQL
from reconforge.infrastructure.postgres_inventory_valuation_reversal import (
    POSTGRES_INVENTORY_VALUATION_REVERSAL_SCHEMA_SQL,
)

revision = "0026_postgres_inventory_reverse"
down_revision = "0025_postgres_inventory_value"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(POSTGRES_INVENTORY_VALUATION_REVERSAL_SCHEMA_SQL)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS inventory_reversal_movements_guard ON reconforge.inventory_movements")
    op.execute(
        "DROP TRIGGER IF EXISTS inventory_reversal_finance_dimensions_guard ON reconforge.finance_entry_line_dimensions"
    )
    op.execute("DROP TRIGGER IF EXISTS inventory_reversal_finance_lines_guard ON reconforge.finance_entry_lines")
    op.execute("DROP TRIGGER IF EXISTS inventory_reversal_finance_entries_guard ON reconforge.finance_entries")
    op.execute("DROP TABLE IF EXISTS reconforge.inventory_valuation_reversal_effects CASCADE")
    op.execute("DROP TABLE IF EXISTS reconforge.inventory_valuation_reversals CASCADE")
    op.execute("DROP FUNCTION IF EXISTS reconforge.inventory_reversal_dependency_guard()")
    op.execute("DROP FUNCTION IF EXISTS reconforge.inventory_valuation_reversal_guard()")
    op.execute(POSTGRES_INVENTORY_VALUATION_SCHEMA_SQL)
