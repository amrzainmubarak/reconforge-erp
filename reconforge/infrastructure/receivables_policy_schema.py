"""Forward-only AR monetary-policy capture; legacy rows remain unverified."""

AR_POLICY_TABLES = ("ar_customers", "ar_invoices", "ar_receipts")


def _sqlite_policy_sql() -> str:
    # SQL identifiers are drawn only from closed module constants below.
    parts = []
    for table in AR_POLICY_TABLES:
        parts.append(f"""
ALTER TABLE {table} ADD COLUMN currency_precision INTEGER CHECK(currency_precision BETWEEN 0 AND 8);
ALTER TABLE {table} ADD COLUMN currency_rounding_policy TEXT CHECK(currency_rounding_policy='ROUND_HALF_UP');
ALTER TABLE {table} ADD COLUMN currency_registry_version TEXT CHECK(length(currency_registry_version) BETWEEN 1 AND 128);
ALTER TABLE {table} ADD COLUMN currency_registry_digest TEXT REFERENCES currency_registry_snapshots(registry_digest)
 CHECK(length(currency_registry_digest)=64 AND currency_registry_digest NOT GLOB '*[^0-9a-f]*');
CREATE TRIGGER {table}_currency_policy_required BEFORE INSERT ON {table}
WHEN NEW.currency_precision IS NULL OR NEW.currency_rounding_policy IS NULL
 OR NEW.currency_registry_version IS NULL OR NEW.currency_registry_digest IS NULL
BEGIN SELECT RAISE(ABORT,'A verified monetary policy is required for new AR records.'); END;
CREATE TRIGGER {table}_currency_policy_immutable BEFORE UPDATE ON {table}
WHEN (NEW.currency_code IS NOT OLD.currency_code OR NEW.currency_precision IS NOT OLD.currency_precision
 OR NEW.currency_rounding_policy IS NOT OLD.currency_rounding_policy
 OR NEW.currency_registry_version IS NOT OLD.currency_registry_version
 OR NEW.currency_registry_digest IS NOT OLD.currency_registry_digest)
""")
        if table == "ar_customers":
            parts.append("""AND NOT (OLD.currency_precision IS NOT NULL AND NEW.currency_code IS NOT OLD.currency_code
 AND NEW.currency_precision IS NOT NULL AND NEW.currency_rounding_policy IS NOT NULL
 AND NEW.currency_registry_version IS NOT NULL AND NEW.currency_registry_digest IS NOT NULL
 AND NOT EXISTS(SELECT 1 FROM ar_invoices WHERE customer_id=OLD.id)
 AND NOT EXISTS(SELECT 1 FROM ar_receipts WHERE customer_id=OLD.id))
""")
        parts.append("BEGIN SELECT RAISE(ABORT,'AR monetary policy is immutable.'); END;\n")
        if table != "ar_customers":
            parts.append(f"""
CREATE TRIGGER {table}_customer_policy_affinity BEFORE INSERT ON {table}
WHEN NOT EXISTS(SELECT 1 FROM ar_customers c WHERE c.id=NEW.customer_id
 AND c.workspace_id=NEW.workspace_id AND c.currency_code=NEW.currency_code
 AND c.currency_precision=NEW.currency_precision AND c.currency_rounding_policy=NEW.currency_rounding_policy
 AND c.currency_registry_version=NEW.currency_registry_version AND c.currency_registry_digest=NEW.currency_registry_digest)
BEGIN SELECT RAISE(ABORT,'AR customer and document monetary policy must match.'); END;
CREATE TRIGGER {table}_customer_policy_update_affinity BEFORE UPDATE ON {table}
WHEN NOT EXISTS(SELECT 1 FROM ar_customers c WHERE c.id=NEW.customer_id
 AND c.workspace_id=NEW.workspace_id AND c.currency_code=NEW.currency_code
 AND c.currency_precision IS NEW.currency_precision AND c.currency_rounding_policy IS NEW.currency_rounding_policy
 AND c.currency_registry_version IS NEW.currency_registry_version AND c.currency_registry_digest IS NEW.currency_registry_digest)
BEGIN SELECT RAISE(ABORT,'AR customer and document monetary policy must match.'); END;
""")  # nosec B608
    parts.append("""
CREATE TRIGGER ar_customer_policy_history_guard BEFORE UPDATE ON ar_customers
WHEN (NEW.id IS NOT OLD.id OR NEW.workspace_id IS NOT OLD.workspace_id OR NEW.currency_code IS NOT OLD.currency_code)
 AND (EXISTS(SELECT 1 FROM ar_invoices WHERE customer_id=OLD.id)
 OR EXISTS(SELECT 1 FROM ar_receipts WHERE customer_id=OLD.id))
BEGIN SELECT RAISE(ABORT,'AR customer historical monetary affinity is immutable.'); END;
CREATE TRIGGER ar_customer_policy_snapshot_insert BEFORE INSERT ON ar_customers
WHEN NEW.currency_precision IS NOT NULL AND NOT EXISTS(
 SELECT 1 FROM currency_registry_snapshots s,json_each(s.snapshot_json,'$.currencies') c
 WHERE s.registry_digest=NEW.currency_registry_digest AND s.registry_version=NEW.currency_registry_version
 AND json_extract(s.snapshot_json,'$.registry_version')=NEW.currency_registry_version
 AND json_extract(c.value,'$.code')=NEW.currency_code
 AND json_extract(c.value,'$.minor_units')=NEW.currency_precision
 AND json_extract(c.value,'$.rounding_policy')=NEW.currency_rounding_policy)
BEGIN SELECT RAISE(ABORT,'AR monetary policy does not match retained snapshot.'); END;
CREATE TRIGGER ar_customer_policy_snapshot_update BEFORE UPDATE ON ar_customers
WHEN NEW.currency_precision IS NOT NULL AND NOT EXISTS(
 SELECT 1 FROM currency_registry_snapshots s,json_each(s.snapshot_json,'$.currencies') c
 WHERE s.registry_digest=NEW.currency_registry_digest AND s.registry_version=NEW.currency_registry_version
 AND json_extract(s.snapshot_json,'$.registry_version')=NEW.currency_registry_version
 AND json_extract(c.value,'$.code')=NEW.currency_code
 AND json_extract(c.value,'$.minor_units')=NEW.currency_precision
 AND json_extract(c.value,'$.rounding_policy')=NEW.currency_rounding_policy)
BEGIN SELECT RAISE(ABORT,'AR monetary policy does not match retained snapshot.'); END;
CREATE TRIGGER ar_customer_legacy_credit_guard BEFORE UPDATE OF credit_limit_minor ON ar_customers
WHEN NEW.credit_limit_minor IS NOT OLD.credit_limit_minor AND OLD.currency_precision IS NULL
BEGIN SELECT RAISE(ABORT,'Legacy AR monetary policy is unverified.'); END;
CREATE TRIGGER ar_invoice_legacy_financial_guard BEFORE UPDATE OF status ON ar_invoices
WHEN OLD.currency_precision IS NULL AND NEW.status IS NOT OLD.status
 AND (NEW.status IN ('Approved','PartiallyPaid','Paid','Cancelled') OR OLD.status IN ('Approved','PartiallyPaid','Paid','Cancelled'))
BEGIN SELECT RAISE(ABORT,'Legacy AR monetary policy is unverified.'); END;
CREATE TRIGGER ar_invoice_legacy_amount_guard BEFORE UPDATE ON ar_invoices
WHEN OLD.currency_precision IS NULL AND (NEW.subtotal_minor IS NOT OLD.subtotal_minor
 OR NEW.tax_minor IS NOT OLD.tax_minor OR NEW.total_minor IS NOT OLD.total_minor
 OR NEW.customer_id IS NOT OLD.customer_id OR NEW.workspace_id IS NOT OLD.workspace_id
 OR NEW.invoice_date IS NOT OLD.invoice_date OR NEW.due_date IS NOT OLD.due_date)
BEGIN SELECT RAISE(ABORT,'Legacy AR monetary policy is unverified.'); END;
CREATE TRIGGER ar_receipt_legacy_financial_guard BEFORE UPDATE ON ar_receipts
WHEN OLD.currency_precision IS NULL AND (NEW.amount_minor IS NOT OLD.amount_minor
 OR NEW.status IS NOT OLD.status OR NEW.customer_id IS NOT OLD.customer_id
 OR NEW.workspace_id IS NOT OLD.workspace_id OR NEW.receipt_date IS NOT OLD.receipt_date)
BEGIN SELECT RAISE(ABORT,'Legacy AR monetary policy is unverified.'); END;
CREATE TRIGGER ar_allocation_policy_affinity BEFORE INSERT ON ar_receipt_allocations
WHEN NOT EXISTS(SELECT 1 FROM ar_receipts r JOIN ar_invoices i ON i.id=NEW.invoice_id
 WHERE r.id=NEW.receipt_id AND r.customer_id=i.customer_id
 AND r.workspace_id=NEW.workspace_id AND i.workspace_id=NEW.workspace_id
 AND r.currency_code=i.currency_code AND r.currency_precision=i.currency_precision
 AND r.currency_rounding_policy=i.currency_rounding_policy
 AND r.currency_registry_version=i.currency_registry_version AND r.currency_registry_digest=i.currency_registry_digest)
BEGIN SELECT RAISE(ABORT,'AR allocation requires compatible verified monetary policies.'); END;
CREATE TRIGGER ar_allocation_update_policy_affinity BEFORE UPDATE ON ar_receipt_allocations
WHEN NOT EXISTS(SELECT 1 FROM ar_receipts r JOIN ar_invoices i ON i.id=NEW.invoice_id
 WHERE r.id=NEW.receipt_id AND r.customer_id=i.customer_id
 AND r.workspace_id=NEW.workspace_id AND i.workspace_id=NEW.workspace_id
 AND r.currency_code=i.currency_code AND r.currency_precision=i.currency_precision
 AND r.currency_rounding_policy=i.currency_rounding_policy
 AND r.currency_registry_version=i.currency_registry_version AND r.currency_registry_digest=i.currency_registry_digest)
BEGIN SELECT RAISE(ABORT,'AR allocation requires compatible verified monetary policies.'); END;
""")
    for operation in ("INSERT", "UPDATE", "DELETE"):
        identities = ["NEW"] if operation == "INSERT" else ["OLD"] if operation == "DELETE" else ["OLD", "NEW"]
        for identity in identities:
            parts.append(f"""
CREATE TRIGGER ar_line_policy_{operation.lower()}_{identity.lower()} BEFORE {operation} ON ar_invoice_lines
WHEN NOT EXISTS(SELECT 1 FROM ar_invoices i WHERE i.id={identity}.invoice_id AND i.currency_precision IS NOT NULL)
BEGIN SELECT RAISE(ABORT,'Legacy AR monetary policy is unverified.'); END;
""")  # nosec B608
    parts.append("""
CREATE TRIGGER ar_allocation_legacy_delete_guard BEFORE DELETE ON ar_receipt_allocations
WHEN EXISTS(SELECT 1 FROM ar_receipts r WHERE r.id=OLD.receipt_id AND r.currency_precision IS NULL)
 OR EXISTS(SELECT 1 FROM ar_invoices i WHERE i.id=OLD.invoice_id AND i.currency_precision IS NULL)
BEGIN SELECT RAISE(ABORT,'Legacy AR monetary policy is unverified.'); END;
""")
    return "".join(parts)


SQLITE_RECEIVABLES_POLICY_MIGRATION_SQL = _sqlite_policy_sql()


def _postgres_policy_sql() -> str:
    # SQL identifiers are drawn only from closed module constants below.
    parts = []
    for table in AR_POLICY_TABLES:
        parts.append(f"""
ALTER TABLE reconforge.{table}
 ADD COLUMN IF NOT EXISTS currency_precision INTEGER CHECK(currency_precision BETWEEN 0 AND 8),
 ADD COLUMN IF NOT EXISTS currency_rounding_policy TEXT CHECK(currency_rounding_policy='ROUND_HALF_UP'),
 ADD COLUMN IF NOT EXISTS currency_registry_version TEXT CHECK(length(currency_registry_version) BETWEEN 1 AND 128),
 ADD COLUMN IF NOT EXISTS currency_registry_digest TEXT CHECK(currency_registry_digest ~ '^[0-9a-f]{{64}}$');
DO $arpolicy$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM pg_constraint WHERE conname='{table}_currency_snapshot_fk'
 AND conrelid='reconforge.{table}'::regclass) THEN
 ALTER TABLE reconforge.{table} ADD CONSTRAINT {table}_currency_snapshot_fk
 FOREIGN KEY(tenant_id,currency_registry_digest) REFERENCES reconforge.currency_registry_snapshots(tenant_id,registry_digest);
 END IF;
END $arpolicy$;
""")  # nosec B608
    parts.append("""
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
""")
    for table in AR_POLICY_TABLES:
        parts.append(f"""
DROP TRIGGER IF EXISTS {table}_currency_policy_guard ON reconforge.{table};
CREATE TRIGGER {table}_currency_policy_guard BEFORE INSERT OR UPDATE ON reconforge.{table}
 FOR EACH ROW EXECUTE FUNCTION reconforge.guard_ar_monetary_policy();
""")
    return "".join(parts)


POSTGRES_RECEIVABLES_POLICY_SCHEMA_SQL = _postgres_policy_sql()
