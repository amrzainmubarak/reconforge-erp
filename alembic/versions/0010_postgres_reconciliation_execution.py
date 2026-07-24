"""Add durable reconciliation execution claims and cancellation state."""

from alembic import op
from reconforge.infrastructure.postgres_reconciliation_execution import (
    POSTGRES_RECONCILIATION_EXECUTION_SCHEMA_SQL,
)

revision = "0010_postgres_reconciliation_execution"
down_revision = "0009_postgres_reconciliation_results"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Install tenant-scoped execution lease and progress state."""

    op.execute(POSTGRES_RECONCILIATION_EXECUTION_SCHEMA_SQL)


def downgrade() -> None:
    """Remove execution state while preserving reconciliation results."""

    op.execute(
        """
        CREATE OR REPLACE FUNCTION reconforge.reject_completed_reconciliation_child_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $reconforge$
        DECLARE
            target_tenant TEXT;
            target_run TEXT;
            run_status TEXT;
        BEGIN
            target_tenant := CASE WHEN TG_OP = 'DELETE' THEN OLD.tenant_id ELSE NEW.tenant_id END;
            target_run := CASE WHEN TG_OP = 'DELETE' THEN OLD.run_id ELSE NEW.run_id END;
            SELECT status INTO run_status
              FROM reconforge.reconciliation_runs
             WHERE tenant_id = target_tenant AND id = target_run;
            IF run_status <> 'Running' THEN
                RAISE EXCEPTION 'Completed reconciliation children are immutable' USING ERRCODE = '55000';
            END IF;
            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END
        $reconforge$;
        """
    )
    op.execute("DROP INDEX IF EXISTS reconforge.idx_reconciliation_runs_execution_queue")
    op.execute("ALTER TABLE reconforge.reconciliation_runs DROP CONSTRAINT IF EXISTS reconciliation_runs_execution_attempt_check")
    op.execute("ALTER TABLE reconforge.reconciliation_runs DROP CONSTRAINT IF EXISTS reconciliation_runs_execution_progress_check")
    op.execute("ALTER TABLE reconforge.reconciliation_runs DROP CONSTRAINT IF EXISTS reconciliation_runs_execution_status_check")
    op.execute(
        """
        ALTER TABLE reconforge.reconciliation_runs
            DROP COLUMN IF EXISTS cancel_requested,
            DROP COLUMN IF EXISTS execution_error,
            DROP COLUMN IF EXISTS execution_finished_at,
            DROP COLUMN IF EXISTS execution_started_at,
            DROP COLUMN IF EXISTS execution_attempt,
            DROP COLUMN IF EXISTS execution_progress,
            DROP COLUMN IF EXISTS execution_lease_until,
            DROP COLUMN IF EXISTS execution_claimed_at,
            DROP COLUMN IF EXISTS execution_worker_id,
            DROP COLUMN IF EXISTS execution_status
        """
    )
