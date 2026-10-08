"""Preserve receipt admission and serialize the first workspace currency binding."""
from alembic import op

revision = "0108_pg_receipt_admission"
down_revision = "0107_pg_job_operations"
branch_labels = None
depends_on = None

def upgrade() -> None:
    from reconforge.infrastructure.postgres_receipt_admission import POSTGRES_RECEIPT_ADMISSION_SQL
    op.get_bind().exec_driver_sql(POSTGRES_RECEIPT_ADMISSION_SQL)

def downgrade() -> None:
    from reconforge.infrastructure.postgres_receipt_admission import PREVIOUS_RECEIPT_ADMISSION_SQL
    connection = op.get_bind()
    connection.exec_driver_sql("""DO $guard$ BEGIN
    IF EXISTS(SELECT 1 FROM reconforge.inventory_receipt_plans) THEN
      RAISE EXCEPTION 'Retained receipt plans prohibit admission downgrade; restore a verified pre-upgrade backup.';
    END IF;
    END $guard$;""")
    connection.exec_driver_sql("DROP TRIGGER IF EXISTS currency_registry_admission_lock ON reconforge.currency_registry_bindings")
    connection.exec_driver_sql("DROP FUNCTION IF EXISTS reconforge.guard_currency_registry_admission_lock()")
    connection.exec_driver_sql(PREVIOUS_RECEIPT_ADMISSION_SQL)
