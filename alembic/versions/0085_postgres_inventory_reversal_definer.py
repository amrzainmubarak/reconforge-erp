"""Run inventory reversal guards with their schema owner privileges."""

from alembic import op
from reconforge.infrastructure.postgres_inventory_valuation_reversal import (
    POSTGRES_INVENTORY_VALUATION_REVERSAL_SCHEMA_SQL,
)

revision = "0085_pg_reversal_definer"
down_revision = "0084_pg_bank_statement"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Re-running the idempotent schema definition updates the three trigger
    # functions for installations that already applied revision 0026.
    op.execute(POSTGRES_INVENTORY_VALUATION_REVERSAL_SCHEMA_SQL)


def downgrade() -> None:
    # Keep the guarded aggregate intact; downgrade only removes the privilege
    # hardening from the existing function bodies.
    op.execute(
        """
        ALTER FUNCTION reconforge.inventory_valuation_reversal_guard() SECURITY INVOKER;
        ALTER FUNCTION reconforge.inventory_valuation_reversal_guard() RESET search_path;
        ALTER FUNCTION reconforge.inventory_cost_layer_guard() SECURITY INVOKER;
        ALTER FUNCTION reconforge.inventory_cost_layer_guard() RESET search_path;
        ALTER FUNCTION reconforge.inventory_reversal_dependency_guard() SECURITY INVOKER;
        ALTER FUNCTION reconforge.inventory_reversal_dependency_guard() RESET search_path;
        """
    )
