"""Retain new AR monetary policy without inferring historical precision.

All legacy policy fields remain NULL. Captured evidence makes downgrade refuse;
restore the pre-upgrade database instead of deleting monetary interpretation.
"""

from alembic import op

revision = "0099_pg_receivables_policy"
down_revision = "0098_pg_finance_posting"
branch_labels = None
depends_on = None

UPGRADE_SQL = """
ALTER TABLE reconforge.ar_customers
 ADD COLUMN IF NOT EXISTS currency_precision INTEGER CHECK(currency_precision BETWEEN 0 AND 8),
 ADD COLUMN IF NOT EXISTS currency_rounding_policy TEXT CHECK(currency_rounding_policy='ROUND_HALF_UP'),
 ADD COLUMN IF NOT EXISTS currency_registry_version TEXT CHECK(length(currency_registry_version) BETWEEN 1 AND 128),
 ADD COLUMN IF NOT EXISTS currency_registry_digest TEXT CHECK(currency_registry_digest ~ '^[0-9a-f]{64}$');
DO $arpolicy$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM pg_constraint WHERE conname='ar_customers_currency_snapshot_fk'
 AND conrelid='reconforge.ar_customers'::regclass) THEN
 ALTER TABLE reconforge.ar_customers ADD CONSTRAINT ar_customers_currency_snapshot_fk
 FOREIGN KEY(tenant_id,currency_registry_digest) REFERENCES reconforge.currency_registry_snapshots(tenant_id,registry_digest);
 END IF;
END $arpolicy$;

ALTER TABLE reconforge.ar_invoices
 ADD COLUMN IF NOT EXISTS currency_precision INTEGER CHECK(currency_precision BETWEEN 0 AND 8),
 ADD COLUMN IF NOT EXISTS currency_rounding_policy TEXT CHECK(currency_rounding_policy='ROUND_HALF_UP'),
 ADD COLUMN IF NOT EXISTS currency_registry_version TEXT CHECK(length(currency_registry_version) BETWEEN 1 AND 128),
 ADD COLUMN IF NOT EXISTS currency_registry_digest TEXT CHECK(currency_registry_digest ~ '^[0-9a-f]{64}$');
DO $arpolicy$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM pg_constraint WHERE conname='ar_invoices_currency_snapshot_fk'
 AND conrelid='reconforge.ar_invoices'::regclass) THEN
 ALTER TABLE reconforge.ar_invoices ADD CONSTRAINT ar_invoices_currency_snapshot_fk
 FOREIGN KEY(tenant_id,currency_registry_digest) REFERENCES reconforge.currency_registry_snapshots(tenant_id,registry_digest);
 END IF;
END $arpolicy$;

ALTER TABLE reconforge.ar_receipts
 ADD COLUMN IF NOT EXISTS currency_precision INTEGER CHECK(currency_precision BETWEEN 0 AND 8),
 ADD COLUMN IF NOT EXISTS currency_rounding_policy TEXT CHECK(currency_rounding_policy='ROUND_HALF_UP'),
 ADD COLUMN IF NOT EXISTS currency_registry_version TEXT CHECK(length(currency_registry_version) BETWEEN 1 AND 128),
 ADD COLUMN IF NOT EXISTS currency_registry_digest TEXT CHECK(currency_registry_digest ~ '^[0-9a-f]{64}$');
DO $arpolicy$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM pg_constraint WHERE conname='ar_receipts_currency_snapshot_fk'
 AND conrelid='reconforge.ar_receipts'::regclass) THEN
 ALTER TABLE reconforge.ar_receipts ADD CONSTRAINT ar_receipts_currency_snapshot_fk
 FOREIGN KEY(tenant_id,currency_registry_digest) REFERENCES reconforge.currency_registry_snapshots(tenant_id,registry_digest);
 END IF;
END $arpolicy$;

CREATE UNIQUE INDEX IF NOT EXISTS ar_customer_policy_identity_idx ON reconforge.ar_customers
 (tenant_id,id,workspace_id,currency_code,currency_precision,currency_rounding_policy,currency_registry_version,currency_registry_digest);
DO $arpolicy$
DECLARE table_name TEXT;
BEGIN
 FOREACH table_name IN ARRAY ARRAY['ar_invoices','ar_receipts'] LOOP
  IF NOT EXISTS(SELECT 1 FROM pg_constraint WHERE conname=table_name||'_customer_policy_fk'
   AND conrelid=('reconforge.'||table_name)::regclass) THEN
   EXECUTE format('ALTER TABLE reconforge.%I ADD CONSTRAINT %I FOREIGN KEY
    (tenant_id,customer_id,workspace_id,currency_code,currency_precision,currency_rounding_policy,currency_registry_version,currency_registry_digest)
    REFERENCES reconforge.ar_customers
    (tenant_id,id,workspace_id,currency_code,currency_precision,currency_rounding_policy,currency_registry_version,currency_registry_digest)',
    table_name,table_name||'_customer_policy_fk');
  END IF;
 END LOOP;
END $arpolicy$;
CREATE OR REPLACE FUNCTION reconforge.guard_ar_monetary_policy() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $arpolicy$
DECLARE customer_row reconforge.ar_customers%ROWTYPE;
BEGIN
 IF NEW.currency_precision IS NOT NULL AND TG_TABLE_NAME='ar_customers' THEN
  IF NOT EXISTS(SELECT 1 FROM reconforge.currency_registry_snapshots s,
   jsonb_array_elements(s.snapshot_json::jsonb->'currencies') c
   WHERE s.tenant_id=NEW.tenant_id AND s.registry_digest=NEW.currency_registry_digest
   AND s.registry_version=NEW.currency_registry_version
   AND s.snapshot_json::jsonb->>'registry_version'=NEW.currency_registry_version
   AND c->>'code'=NEW.currency_code AND c->'minor_units'=to_jsonb(NEW.currency_precision)
   AND c->>'rounding_policy'=NEW.currency_rounding_policy) THEN
   RAISE EXCEPTION 'AR monetary policy does not match retained snapshot.';
  END IF;
 END IF;
 IF TG_OP='INSERT' THEN
  IF NEW.currency_precision IS NULL OR NEW.currency_rounding_policy IS NULL
   OR NEW.currency_registry_version IS NULL OR NEW.currency_registry_digest IS NULL THEN
   RAISE EXCEPTION 'A verified monetary policy is required for new AR records.';
  END IF;
 END IF;
 IF TG_TABLE_NAME<>'ar_customers' THEN
   SELECT * INTO customer_row FROM reconforge.ar_customers
   WHERE tenant_id=NEW.tenant_id AND id=NEW.customer_id FOR NO KEY UPDATE;
   IF NOT FOUND OR (customer_row.workspace_id,customer_row.currency_code,customer_row.currency_precision,
    customer_row.currency_rounding_policy,customer_row.currency_registry_version,customer_row.currency_registry_digest)
    IS DISTINCT FROM (NEW.workspace_id,NEW.currency_code,NEW.currency_precision,
    NEW.currency_rounding_policy,NEW.currency_registry_version,NEW.currency_registry_digest) THEN
    RAISE EXCEPTION 'AR customer and document monetary policy must match.';
   END IF;
 END IF;
 IF TG_OP='UPDATE' THEN
  IF (NEW.tenant_id,NEW.currency_code,NEW.currency_precision,NEW.currency_rounding_policy,
   NEW.currency_registry_version,NEW.currency_registry_digest) IS DISTINCT FROM
   (OLD.tenant_id,OLD.currency_code,OLD.currency_precision,OLD.currency_rounding_policy,
   OLD.currency_registry_version,OLD.currency_registry_digest) THEN
   IF TG_TABLE_NAME='ar_customers' AND NEW.tenant_id=OLD.tenant_id
    AND OLD.currency_precision IS NOT NULL AND NEW.currency_code<>OLD.currency_code
    AND NEW.currency_precision IS NOT NULL AND NEW.currency_rounding_policy IS NOT NULL
    AND NEW.currency_registry_version IS NOT NULL AND NEW.currency_registry_digest IS NOT NULL
    AND NOT EXISTS(SELECT 1 FROM reconforge.ar_invoices WHERE tenant_id=OLD.tenant_id AND customer_id=OLD.id)
    AND NOT EXISTS(SELECT 1 FROM reconforge.ar_receipts WHERE tenant_id=OLD.tenant_id AND customer_id=OLD.id) THEN
    RETURN NEW;
   END IF;
   RAISE EXCEPTION 'AR monetary policy is immutable.';
  END IF;
  IF TG_TABLE_NAME='ar_customers' THEN
   IF NEW.credit_limit_minor IS DISTINCT FROM OLD.credit_limit_minor AND OLD.currency_precision IS NULL THEN
    RAISE EXCEPTION 'Legacy AR monetary policy is unverified.';
   END IF;
  END IF;
  IF TG_TABLE_NAME='ar_invoices' THEN
   IF OLD.currency_precision IS NULL AND NEW.status IS DISTINCT FROM OLD.status
    AND (NEW.status IN ('Approved','PartiallyPaid','Paid','Cancelled') OR OLD.status IN ('Approved','PartiallyPaid','Paid','Cancelled')) THEN
    RAISE EXCEPTION 'Legacy AR monetary policy is unverified.';
   END IF;
   IF OLD.currency_precision IS NULL AND
    (NEW.subtotal_minor,NEW.tax_minor,NEW.total_minor,NEW.customer_id,NEW.workspace_id,NEW.invoice_date,NEW.due_date)
    IS DISTINCT FROM (OLD.subtotal_minor,OLD.tax_minor,OLD.total_minor,OLD.customer_id,OLD.workspace_id,OLD.invoice_date,OLD.due_date) THEN
    RAISE EXCEPTION 'Legacy AR monetary policy is unverified.';
   END IF;
  END IF;
  IF TG_TABLE_NAME='ar_receipts' THEN
   IF OLD.currency_precision IS NULL AND
    (NEW.amount_minor,NEW.status,NEW.customer_id,NEW.workspace_id,NEW.receipt_date)
    IS DISTINCT FROM (OLD.amount_minor,OLD.status,OLD.customer_id,OLD.workspace_id,OLD.receipt_date) THEN
    RAISE EXCEPTION 'Legacy AR monetary policy is unverified.';
   END IF;
  END IF;
 END IF;
 RETURN NEW;
END $arpolicy$;
CREATE OR REPLACE FUNCTION reconforge.guard_ar_allocation_policy() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $arpolicy$
BEGIN
 IF TG_OP='DELETE' THEN
  IF EXISTS(SELECT 1 FROM reconforge.ar_receipts WHERE tenant_id=OLD.tenant_id AND id=OLD.receipt_id AND currency_precision IS NULL)
   OR EXISTS(SELECT 1 FROM reconforge.ar_invoices WHERE tenant_id=OLD.tenant_id AND id=OLD.invoice_id AND currency_precision IS NULL) THEN
   RAISE EXCEPTION 'Legacy AR monetary policy is unverified.';
  END IF;
  RETURN OLD;
 END IF;
 IF NOT EXISTS(SELECT 1 FROM reconforge.ar_receipts r JOIN reconforge.ar_invoices i
 ON i.tenant_id=r.tenant_id AND i.id=NEW.invoice_id WHERE r.tenant_id=NEW.tenant_id AND r.id=NEW.receipt_id
 AND r.customer_id=i.customer_id AND r.workspace_id=NEW.workspace_id AND i.workspace_id=NEW.workspace_id
 AND r.currency_code=i.currency_code AND r.currency_precision=i.currency_precision
 AND r.currency_rounding_policy=i.currency_rounding_policy AND r.currency_registry_version=i.currency_registry_version
 AND r.currency_registry_digest=i.currency_registry_digest) THEN
 RAISE EXCEPTION 'AR allocation requires compatible verified monetary policies.';
 END IF;
 RETURN NEW;
END $arpolicy$;
DROP TRIGGER IF EXISTS ar_allocation_policy_affinity ON reconforge.ar_receipt_allocations;
CREATE TRIGGER ar_allocation_policy_affinity BEFORE INSERT OR UPDATE OR DELETE ON reconforge.ar_receipt_allocations
 FOR EACH ROW EXECUTE FUNCTION reconforge.guard_ar_allocation_policy();
CREATE OR REPLACE FUNCTION reconforge.guard_ar_line_policy() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $arpolicy$
BEGIN
 IF TG_OP<>'INSERT' THEN
  IF NOT EXISTS(SELECT 1 FROM reconforge.ar_invoices WHERE tenant_id=OLD.tenant_id AND id=OLD.invoice_id AND currency_precision IS NOT NULL) THEN
   RAISE EXCEPTION 'Legacy AR monetary policy is unverified.';
  END IF;
 END IF;
 IF TG_OP<>'DELETE' THEN
  IF NOT EXISTS(SELECT 1 FROM reconforge.ar_invoices WHERE tenant_id=NEW.tenant_id AND id=NEW.invoice_id AND currency_precision IS NOT NULL) THEN
   RAISE EXCEPTION 'Legacy AR monetary policy is unverified.';
  END IF;
  RETURN NEW;
 END IF;
 RETURN OLD;
END $arpolicy$;
DROP TRIGGER IF EXISTS ar_line_policy_guard ON reconforge.ar_invoice_lines;
CREATE TRIGGER ar_line_policy_guard BEFORE INSERT OR UPDATE OR DELETE ON reconforge.ar_invoice_lines
 FOR EACH ROW EXECUTE FUNCTION reconforge.guard_ar_line_policy();

DROP TRIGGER IF EXISTS ar_customers_currency_policy_guard ON reconforge.ar_customers;
CREATE TRIGGER ar_customers_currency_policy_guard BEFORE INSERT OR UPDATE ON reconforge.ar_customers
 FOR EACH ROW EXECUTE FUNCTION reconforge.guard_ar_monetary_policy();

DROP TRIGGER IF EXISTS ar_invoices_currency_policy_guard ON reconforge.ar_invoices;
CREATE TRIGGER ar_invoices_currency_policy_guard BEFORE INSERT OR UPDATE ON reconforge.ar_invoices
 FOR EACH ROW EXECUTE FUNCTION reconforge.guard_ar_monetary_policy();

DROP TRIGGER IF EXISTS ar_receipts_currency_policy_guard ON reconforge.ar_receipts;
CREATE TRIGGER ar_receipts_currency_policy_guard BEFORE INSERT OR UPDATE ON reconforge.ar_receipts
 FOR EACH ROW EXECUTE FUNCTION reconforge.guard_ar_monetary_policy();
"""


def upgrade() -> None:
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    op.execute("""
        SET LOCAL row_security = off;
        LOCK TABLE reconforge.ar_customers,reconforge.ar_invoices,reconforge.ar_invoice_lines,
            reconforge.ar_receipts,reconforge.ar_receipt_allocations IN ACCESS EXCLUSIVE MODE;
        DO $arpolicy$ BEGIN
            IF EXISTS(SELECT 1 FROM reconforge.ar_customers WHERE currency_precision IS NOT NULL OR currency_rounding_policy IS NOT NULL OR currency_registry_version IS NOT NULL OR currency_registry_digest IS NOT NULL)
            OR EXISTS(SELECT 1 FROM reconforge.ar_invoices WHERE currency_precision IS NOT NULL OR currency_rounding_policy IS NOT NULL OR currency_registry_version IS NOT NULL OR currency_registry_digest IS NOT NULL)
            OR EXISTS(SELECT 1 FROM reconforge.ar_receipts WHERE currency_precision IS NOT NULL OR currency_rounding_policy IS NOT NULL OR currency_registry_version IS NOT NULL OR currency_registry_digest IS NOT NULL) THEN
                RAISE EXCEPTION 'AR policy downgrade refused: retained policies require a pre-upgrade restore';
            END IF;
        END $arpolicy$;
        DROP TRIGGER ar_line_policy_guard ON reconforge.ar_invoice_lines;
        DROP TRIGGER ar_allocation_policy_affinity ON reconforge.ar_receipt_allocations;
        DROP TRIGGER ar_customers_currency_policy_guard ON reconforge.ar_customers;
        DROP TRIGGER ar_invoices_currency_policy_guard ON reconforge.ar_invoices;
        DROP TRIGGER ar_receipts_currency_policy_guard ON reconforge.ar_receipts;
        DROP FUNCTION reconforge.guard_ar_line_policy();
        DROP FUNCTION reconforge.guard_ar_allocation_policy();
        DROP FUNCTION reconforge.guard_ar_monetary_policy();
        ALTER TABLE reconforge.ar_invoices DROP CONSTRAINT ar_invoices_customer_policy_fk;
        ALTER TABLE reconforge.ar_receipts DROP CONSTRAINT ar_receipts_customer_policy_fk;
        DROP INDEX reconforge.ar_customer_policy_identity_idx;
        ALTER TABLE reconforge.ar_invoices DROP CONSTRAINT ar_invoices_currency_snapshot_fk,
            DROP COLUMN currency_precision,DROP COLUMN currency_rounding_policy,
            DROP COLUMN currency_registry_version,DROP COLUMN currency_registry_digest;
        ALTER TABLE reconforge.ar_receipts DROP CONSTRAINT ar_receipts_currency_snapshot_fk,
            DROP COLUMN currency_precision,DROP COLUMN currency_rounding_policy,
            DROP COLUMN currency_registry_version,DROP COLUMN currency_registry_digest;
        ALTER TABLE reconforge.ar_customers DROP CONSTRAINT ar_customers_currency_snapshot_fk,
            DROP COLUMN currency_precision,DROP COLUMN currency_rounding_policy,
            DROP COLUMN currency_registry_version,DROP COLUMN currency_registry_digest;
    """)
