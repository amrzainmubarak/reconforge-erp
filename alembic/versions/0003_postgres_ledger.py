"""Add the tenant-scoped PostgreSQL ledger-control boundary."""

from __future__ import annotations

from alembic import op
from reconforge.infrastructure.postgres_ledger import POSTGRES_LEDGER_SCHEMA_SQL

revision = "0003_postgres_ledger"
down_revision = "0002_postgres_master_data"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Install exact, balanced ledger-control tables and evidence tables."""

    op.execute(POSTGRES_LEDGER_SCHEMA_SQL)


def downgrade() -> None:
    """Drop the ledger boundary after explicit operator approval."""

    op.execute("DROP TABLE IF EXISTS reconforge.ledger_lines")
    op.execute("DROP TABLE IF EXISTS reconforge.ledger_entries")
    op.execute("DROP TABLE IF EXISTS reconforge.ledger_accounts")
    op.execute("DROP TABLE IF EXISTS reconforge.outbox_events")
    op.execute("DROP TABLE IF EXISTS reconforge.audit_events")
    op.execute("DROP FUNCTION IF EXISTS reconforge.assert_ledger_entry_balanced()")
    op.execute("DROP FUNCTION IF EXISTS reconforge.reject_posted_ledger_entry_mutation()")
    op.execute("DROP FUNCTION IF EXISTS reconforge.reject_posted_ledger_line_mutation()")
    op.execute("DROP FUNCTION IF EXISTS reconforge.reject_audit_mutation()")
