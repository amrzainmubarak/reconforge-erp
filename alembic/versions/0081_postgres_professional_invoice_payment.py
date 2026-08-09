"""Persist replay-verifiable professional invoice-to-payment evidence under PostgreSQL RLS."""

from alembic import op
from reconforge.infrastructure.postgres_professional_invoice_payment import (
    POSTGRES_PROFESSIONAL_INVOICE_PAYMENT_SCHEMA_SQL,
)

revision = "0081_pg_prof_invoice"
down_revision = "0080_pg_retail_settlement"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(POSTGRES_PROFESSIONAL_INVOICE_PAYMENT_SCHEMA_SQL)


def downgrade() -> None:
    op.execute(
        """
        DO $reconforge$
        BEGIN
            IF EXISTS (SELECT 1 FROM reconforge.professional_invoice_payment_runs) THEN
                RAISE EXCEPTION 'refusing to discard professional invoice/payment evidence';
            END IF;
        END $reconforge$;
        DROP TRIGGER IF EXISTS professional_invoice_payment_runs_guard
            ON reconforge.professional_invoice_payment_runs;
        DROP FUNCTION IF EXISTS reconforge.guard_professional_invoice_payment_run();
        DROP INDEX IF EXISTS reconforge.professional_invoice_payment_runs_scope_idx;
        DROP TABLE IF EXISTS reconforge.professional_invoice_payment_runs;
        """
    )
