"""Schema for tenant-scoped, idempotent reconciliation partition checkpoints."""


POSTGRES_RECONCILIATION_CHECKPOINT_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS reconforge.reconciliation_execution_checkpoints (
    tenant_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    partition_key TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'Complete',
    input_count BIGINT NOT NULL CHECK (input_count >= 0),
    result_count BIGINT NOT NULL CHECK (result_count >= 0),
    exception_count BIGINT NOT NULL CHECK (exception_count >= 0),
    output_hash TEXT NOT NULL,
    worker_id TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, run_id, partition_key),
    FOREIGN KEY (tenant_id, run_id)
        REFERENCES reconforge.reconciliation_runs(tenant_id, id) ON DELETE CASCADE,
    CHECK (partition_key <> ''),
    CHECK (status = 'Complete')
);

CREATE INDEX IF NOT EXISTS idx_reconciliation_checkpoints_run_status
    ON reconforge.reconciliation_execution_checkpoints
        (tenant_id, run_id, status, partition_key);

DO $reconforge$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger
        WHERE tgname = 'reconciliation_checkpoints_immutable'
    ) THEN
        CREATE TRIGGER reconciliation_checkpoints_immutable
        BEFORE UPDATE OR DELETE
        ON reconforge.reconciliation_execution_checkpoints
        FOR EACH ROW
        EXECUTE FUNCTION reconforge.reject_completed_reconciliation_child_mutation();
    END IF;
END
$reconforge$;

ALTER TABLE reconforge.reconciliation_execution_checkpoints ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.reconciliation_execution_checkpoints FORCE ROW LEVEL SECURITY;

DO $reconforge$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'reconforge'
          AND tablename = 'reconciliation_execution_checkpoints'
          AND policyname = 'tenant_scope'
    ) THEN
        CREATE POLICY tenant_scope
        ON reconforge.reconciliation_execution_checkpoints
        USING (tenant_id = current_setting('app.tenant_id', true))
        WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
    END IF;
END
$reconforge$;
"""
