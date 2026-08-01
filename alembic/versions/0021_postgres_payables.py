"""Add tenant-scoped governed Payables application storage."""

from alembic import op
from reconforge_migration_sql import load_postgres_schema_sql

POSTGRES_PAYABLES_SCHEMA_SQL = load_postgres_schema_sql(
    "reconforge.infrastructure.postgres_payables", "POSTGRES_PAYABLES_SCHEMA_SQL"
)
revision = "0021_postgres_payables"
down_revision = "0020_postgres_master_data_app"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(POSTGRES_PAYABLES_SCHEMA_SQL)


def downgrade() -> None:
    for table in (
        "ap_idempotency_keys",
        "ap_three_way_matches",
        "ap_supplier_invoice_lines",
        "ap_supplier_invoices",
        "ap_goods_receipt_lines",
        "ap_goods_receipts",
        "ap_purchase_order_lines",
        "ap_purchase_orders",
        "ap_suppliers",
    ):
        op.execute(f"DROP TABLE IF EXISTS reconforge.{table}")
