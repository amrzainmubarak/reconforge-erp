"""PostgreSQL governed inventory planning aggregate."""

from alembic import op
from reconforge.infrastructure.postgres_inventory_planning import POSTGRES_INVENTORY_PLANNING_SCHEMA_SQL

revision = "0027_postgres_inventory_planning"
down_revision = "0026_postgres_inventory_reverse"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(POSTGRES_INVENTORY_PLANNING_SCHEMA_SQL)


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS inventory_count_adjustment_lines_guard ON reconforge.inventory_movement_lines"
    )
    op.execute("DROP TRIGGER IF EXISTS inventory_count_adjustment_guard ON reconforge.inventory_movements")
    op.execute("DROP TABLE IF EXISTS reconforge.inventory_count_lines CASCADE")
    op.execute("DROP TABLE IF EXISTS reconforge.inventory_count_sessions CASCADE")
    op.execute("DROP TABLE IF EXISTS reconforge.inventory_reorder_rules CASCADE")
    op.execute("DROP FUNCTION IF EXISTS reconforge.inventory_count_dependency_guard()")
    op.execute("DROP FUNCTION IF EXISTS reconforge.inventory_count_guard()")
