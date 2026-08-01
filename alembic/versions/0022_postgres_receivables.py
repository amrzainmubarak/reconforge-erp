"""Add tenant-scoped governed Receivables storage."""

from alembic import op
from reconforge_migration_sql import load_postgres_schema_sql

POSTGRES_RECEIVABLES_SCHEMA_SQL = load_postgres_schema_sql(
    "reconforge.infrastructure.postgres_receivables", "POSTGRES_RECEIVABLES_SCHEMA_SQL"
)
revision = "0022_postgres_receivables"
down_revision = "0021_postgres_payables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(POSTGRES_RECEIVABLES_SCHEMA_SQL)


def downgrade() -> None:
    for table in (
        "ar_idempotency_keys",
        "ar_receipt_allocations",
        "ar_receipts",
        "ar_invoice_lines",
        "ar_invoices",
        "ar_customers",
    ):
        op.execute(f"DROP TABLE IF EXISTS reconforge.{table}")
    op.execute("DROP FUNCTION IF EXISTS reconforge.ar_protect_final_invoice_line()")
    op.execute("DROP FUNCTION IF EXISTS reconforge.ar_protect_final_invoice()")
