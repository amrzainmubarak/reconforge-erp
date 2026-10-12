"""Seal reconciliation child writes without guessing or repairing old manifests."""
from alembic import op

revision = "0097_pg_reconciliation_seal"
down_revision = "0096_pg_master_authority"
branch_labels = None
depends_on = None

UPGRADE_SQL = r"""
CREATE OR REPLACE FUNCTION reconforge.guard_reconciliation_child_write() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $reconforge$
DECLARE
 target_tenant TEXT;
 target_run TEXT;
 run_status TEXT;
 run_execution_status TEXT;
 run_attempt INTEGER;
 run_cancelled BOOLEAN;
BEGIN
 IF TG_OP='UPDATE' THEN
  IF OLD.tenant_id IS DISTINCT FROM NEW.tenant_id OR OLD.run_id IS DISTINCT FROM NEW.run_id THEN
   RAISE EXCEPTION USING ERRCODE='55000',MESSAGE='Reconciliation child tenant/run identity is immutable.';
  END IF;
 END IF;
 IF current_setting('transaction_isolation') IS DISTINCT FROM 'read committed' THEN
  RAISE EXCEPTION USING ERRCODE='25000',MESSAGE='Reconciliation child writes require a READ COMMITTED transaction.';
 END IF;
 IF TG_OP='DELETE' THEN
  target_tenant := OLD.tenant_id;
  target_run := OLD.run_id;
 ELSE
  target_tenant := NEW.tenant_id;
  target_run := NEW.run_id;
 END IF;
 SELECT status,execution_status,execution_attempt,cancel_requested
 INTO run_status,run_execution_status,run_attempt,run_cancelled
 FROM reconforge.reconciliation_runs
 WHERE tenant_id=target_tenant AND id=target_run
 FOR UPDATE;
 IF NOT FOUND THEN
  RAISE EXCEPTION USING ERRCODE='55000',MESSAGE='Reconciliation child writes require a visible unsealed run.';
 END IF;
 IF run_status IS DISTINCT FROM 'Running' OR run_cancelled IS DISTINCT FROM FALSE THEN
  RAISE EXCEPTION USING ERRCODE='55000',MESSAGE='Reconciliation child writes are sealed for this run.';
 END IF;
 IF TG_TABLE_NAME='reconciliation_inputs' THEN
  IF run_execution_status IS DISTINCT FROM 'Queued' OR run_attempt IS DISTINCT FROM 0 THEN
   RAISE EXCEPTION USING ERRCODE='55000',MESSAGE='Reconciliation inputs are sealed after execution starts.';
  END IF;
 ELSE
  IF run_execution_status IS DISTINCT FROM 'Running'
     AND (run_execution_status IS DISTINCT FROM 'Queued' OR run_attempt IS DISTINCT FROM 0) THEN
   RAISE EXCEPTION USING ERRCODE='55000',MESSAGE='Reconciliation outputs are sealed outside active execution.';
  END IF;
 END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF;
 RETURN NEW;
END $reconforge$;

DROP TRIGGER IF EXISTS reconciliation_child_write_guard ON reconforge.reconciliation_inputs;
CREATE TRIGGER reconciliation_child_write_guard BEFORE INSERT OR UPDATE OR DELETE ON reconforge.reconciliation_inputs
 FOR EACH ROW EXECUTE FUNCTION reconforge.guard_reconciliation_child_write();
DROP TRIGGER IF EXISTS reconciliation_child_write_guard ON reconforge.reconciliation_results;
CREATE TRIGGER reconciliation_child_write_guard BEFORE INSERT OR UPDATE OR DELETE ON reconforge.reconciliation_results
 FOR EACH ROW EXECUTE FUNCTION reconforge.guard_reconciliation_child_write();
DROP TRIGGER IF EXISTS reconciliation_child_write_guard ON reconforge.reconciliation_exceptions;
CREATE TRIGGER reconciliation_child_write_guard BEFORE INSERT OR UPDATE OR DELETE ON reconforge.reconciliation_exceptions
 FOR EACH ROW EXECUTE FUNCTION reconforge.guard_reconciliation_child_write();
"""

DOWNGRADE_SQL = r"""
DROP TRIGGER IF EXISTS reconciliation_child_write_guard ON reconforge.reconciliation_inputs;
DROP TRIGGER IF EXISTS reconciliation_child_write_guard ON reconforge.reconciliation_results;
DROP TRIGGER IF EXISTS reconciliation_child_write_guard ON reconforge.reconciliation_exceptions;
DROP FUNCTION IF EXISTS reconforge.guard_reconciliation_child_write();
"""


def upgrade() -> None:
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    op.execute(DOWNGRADE_SQL)
