"""PostgreSQL schema upgrades for durable reconciliation execution state."""

POSTGRES_RECONCILIATION_EXECUTION_SCHEMA_SQL = """
ALTER TABLE reconforge.reconciliation_runs
    ADD COLUMN IF NOT EXISTS execution_status TEXT NOT NULL DEFAULT 'Queued',
    ADD COLUMN IF NOT EXISTS execution_worker_id TEXT,
    ADD COLUMN IF NOT EXISTS execution_claimed_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS execution_lease_until TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS execution_progress INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS execution_attempt INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS execution_started_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS execution_finished_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS execution_error TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS cancel_requested BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE reconforge.reconciliation_inputs
    ADD COLUMN IF NOT EXISTS attributes_json JSONB NOT NULL DEFAULT '{}'::jsonb;

DO $reconforge$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'reconciliation_runs_execution_status_check'
          AND conrelid = 'reconforge.reconciliation_runs'::regclass
    ) THEN
        ALTER TABLE reconforge.reconciliation_runs
            ADD CONSTRAINT reconciliation_runs_execution_status_check
            CHECK (execution_status IN ('Queued', 'Running', 'Complete', 'Failed', 'Cancelled'));
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'reconciliation_runs_execution_progress_check'
          AND conrelid = 'reconforge.reconciliation_runs'::regclass
    ) THEN
        ALTER TABLE reconforge.reconciliation_runs
            ADD CONSTRAINT reconciliation_runs_execution_progress_check
            CHECK (execution_progress BETWEEN 0 AND 100);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'reconciliation_runs_execution_attempt_check'
          AND conrelid = 'reconforge.reconciliation_runs'::regclass
    ) THEN
        ALTER TABLE reconforge.reconciliation_runs
            ADD CONSTRAINT reconciliation_runs_execution_attempt_check
            CHECK (execution_attempt >= 0);
    END IF;
END
$reconforge$;

CREATE INDEX IF NOT EXISTS idx_reconciliation_runs_execution_queue
    ON reconforge.reconciliation_runs (tenant_id, execution_status, execution_lease_until, created_at, id);

CREATE OR REPLACE FUNCTION reconforge.reject_completed_reconciliation_child_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $reconforge$
DECLARE
    target_tenant TEXT;
    target_run TEXT;
    run_status TEXT;
    run_execution_status TEXT;
BEGIN
    target_tenant := CASE WHEN TG_OP = 'DELETE' THEN OLD.tenant_id ELSE NEW.tenant_id END;
    target_run := CASE WHEN TG_OP = 'DELETE' THEN OLD.run_id ELSE NEW.run_id END;
    SELECT status, execution_status INTO run_status, run_execution_status
      FROM reconforge.reconciliation_runs
     WHERE tenant_id = target_tenant AND id = target_run;
    IF run_status <> 'Running' OR run_execution_status NOT IN ('Queued', 'Running') THEN
        RAISE EXCEPTION 'Completed reconciliation children are immutable' USING ERRCODE = '55000';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END
$reconforge$;
"""
