"""PostgreSQL account-reconciliation aggregate."""

from alembic import op
from reconforge.infrastructure.postgres_accounts import POSTGRES_ACCOUNTS_SCHEMA_SQL

revision = "0028_postgres_accounts"
down_revision = "0027_postgres_inventory_planning"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(POSTGRES_ACCOUNTS_SCHEMA_SQL)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS reconforge.account_reconciliation_transitions CASCADE")
    op.execute("DROP TABLE IF EXISTS reconforge.account_reconciliation_items CASCADE")
    op.execute("DROP TABLE IF EXISTS reconforge.account_reconciliation_records CASCADE")
    op.execute("DROP TABLE IF EXISTS reconforge.trial_balance_rows CASCADE")
    op.execute("DROP TABLE IF EXISTS reconforge.account_reconciliation_templates CASCADE")
    op.execute("DROP FUNCTION IF EXISTS reconforge.account_reconciliation_transition_guard()")
    op.execute("DROP FUNCTION IF EXISTS reconforge.account_reconciliation_guard()")
