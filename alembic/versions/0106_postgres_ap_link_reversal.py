"""Add immutable Finance-evidenced reversals for supplier payment links."""

from alembic import op

revision = "0106_pg_ap_link_reversal"
down_revision = "0105_pg_payables_payment_link"
branch_labels = None
depends_on = None


# This revision owns the persistence contract that permits an AP allocation to
# be unwound.  It does not create a posting path: the only admissible evidence
# is a separately posted Finance ``Reversal`` effect of the original payment
# effect.  Database guards intentionally duplicate the narrow projection used
# by the repository so direct SQL cannot bypass the business boundary.
UPGRADE_SQL = r"""
DO $reversal$
BEGIN
 IF NOT EXISTS (
   SELECT 1 FROM pg_roles
   WHERE rolname=current_user AND (rolsuper OR rolbypassrls)
 ) THEN
  RAISE EXCEPTION 'payables payment-link reversal migration requires a role that bypasses forced row security';
 END IF;
END $reversal$;

CREATE TABLE reconforge.ap_payment_link_reversals (
 tenant_id TEXT NOT NULL,id TEXT NOT NULL,workspace_id TEXT NOT NULL,organization_id TEXT NOT NULL,
 legal_entity_id TEXT NOT NULL,supplier_invoice_id TEXT NOT NULL,payment_link_id TEXT NOT NULL,
 reversal_finance_effect_id TEXT NOT NULL,reversal_finance_entry_id TEXT NOT NULL,
 amount_minor BIGINT NOT NULL CHECK(amount_minor BETWEEN 1 AND 9000000000000000000),
 currency_code TEXT NOT NULL,reversal_date TEXT NOT NULL,
 finance_validation_digest TEXT NOT NULL CHECK(finance_validation_digest ~ '^[0-9a-f]{64}$'),
 finance_posted_actor_id TEXT NOT NULL,reversal_actor_id TEXT NOT NULL,
 invoice_version_before BIGINT NOT NULL CHECK(invoice_version_before>0),
 audit_event_id TEXT NOT NULL,outbox_event_id TEXT NOT NULL,created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(tenant_id,id),UNIQUE(tenant_id,payment_link_id),UNIQUE(tenant_id,reversal_finance_effect_id),
 UNIQUE(tenant_id,reversal_finance_entry_id),UNIQUE(tenant_id,supplier_invoice_id,invoice_version_before),
 FOREIGN KEY(tenant_id,workspace_id) REFERENCES reconforge.domain_workspaces(tenant_id,id),
 FOREIGN KEY(tenant_id,organization_id) REFERENCES reconforge.organizations(tenant_id,id),
 FOREIGN KEY(tenant_id,legal_entity_id) REFERENCES reconforge.legal_entities(tenant_id,id),
 FOREIGN KEY(tenant_id,supplier_invoice_id) REFERENCES reconforge.ap_supplier_invoices(tenant_id,id),
 FOREIGN KEY(tenant_id,payment_link_id) REFERENCES reconforge.ap_payment_links(tenant_id,id),
 FOREIGN KEY(tenant_id,reversal_finance_effect_id) REFERENCES reconforge.finance_posting_effects(tenant_id,id),
 FOREIGN KEY(tenant_id,reversal_finance_entry_id) REFERENCES reconforge.finance_entries(tenant_id,id),
 FOREIGN KEY(tenant_id,finance_posted_actor_id) REFERENCES reconforge.identity_users(tenant_id,id),
 FOREIGN KEY(tenant_id,reversal_actor_id) REFERENCES reconforge.identity_users(tenant_id,id),
 FOREIGN KEY(tenant_id,audit_event_id) REFERENCES reconforge.domain_audit_events(tenant_id,id),
 FOREIGN KEY(tenant_id,outbox_event_id) REFERENCES reconforge.outbox_events(tenant_id,event_id)
);
CREATE INDEX ap_payment_link_reversals_invoice_order ON reconforge.ap_payment_link_reversals
 (tenant_id,supplier_invoice_id,reversal_date,id);

CREATE TABLE reconforge.ap_payment_link_reversal_commands (
 tenant_id TEXT NOT NULL,workspace_id TEXT NOT NULL,organization_id TEXT NOT NULL,legal_entity_id TEXT NOT NULL,
 command_id TEXT NOT NULL CHECK(length(command_id) BETWEEN 1 AND 160),reversal_actor_id TEXT NOT NULL,
 request_digest TEXT NOT NULL CHECK(request_digest ~ '^[0-9a-f]{64}$'),
 result_json JSONB NOT NULL CHECK(octet_length(result_json::text)<=2097152 AND jsonb_typeof(result_json)='object'),
 created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(tenant_id,workspace_id,command_id),
 FOREIGN KEY(tenant_id,workspace_id) REFERENCES reconforge.domain_workspaces(tenant_id,id),
 FOREIGN KEY(tenant_id,organization_id) REFERENCES reconforge.organizations(tenant_id,id),
 FOREIGN KEY(tenant_id,legal_entity_id) REFERENCES reconforge.legal_entities(tenant_id,id),
 FOREIGN KEY(tenant_id,reversal_actor_id) REFERENCES reconforge.identity_users(tenant_id,id)
);
CREATE INDEX ap_payment_link_reversal_commands_scope ON reconforge.ap_payment_link_reversal_commands
 (tenant_id,workspace_id,organization_id,legal_entity_id,created_at,command_id);

CREATE OR REPLACE FUNCTION reconforge.payment_link_canonical_principal_id(
 input_tenant_id TEXT,input_actor TEXT
)
RETURNS TEXT LANGUAGE plpgsql SET search_path=reconforge,pg_catalog AS $reversal$
DECLARE candidate_ids TEXT[];
BEGIN
 IF input_actor IS NULL OR btrim(input_actor)='' THEN RETURN NULL; END IF;
 SELECT array_agg(candidate.id ORDER BY candidate.id) INTO candidate_ids
 FROM (
  SELECT id FROM reconforge.identity_users
   WHERE tenant_id=input_tenant_id AND (id=btrim(input_actor) OR username=btrim(input_actor))
   ORDER BY id FOR KEY SHARE
 ) candidate;
 IF COALESCE(array_length(candidate_ids,1),0)<>1 THEN RETURN NULL; END IF;
 RETURN candidate_ids[1];
END $reversal$;

CREATE OR REPLACE FUNCTION reconforge.guard_ap_payment_link()
RETURNS trigger LANGUAGE plpgsql SET search_path=reconforge,pg_catalog AS $reversal$
DECLARE invoice RECORD; finance_effect RECORD; debit_count BIGINT; credit_count BIGINT;
 invoice_found BOOLEAN; finance_effect_found BOOLEAN;
 creator_actor_id TEXT; approver_actor_id TEXT; settlement_actor_id TEXT;
 finance_preparer_actor_id TEXT; finance_validator_actor_id TEXT; finance_posted_actor_id TEXT;
BEGIN
 IF TG_OP<>'INSERT' THEN
  RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Supplier payment links are immutable.';
 END IF;
 SELECT * INTO invoice FROM reconforge.ap_supplier_invoices
  WHERE tenant_id=NEW.tenant_id AND id=NEW.supplier_invoice_id FOR NO KEY UPDATE;
 invoice_found:=FOUND;
 SELECT posting.*,ledger.validator_actor_id INTO finance_effect FROM reconforge.finance_posting_effects posting
  JOIN reconforge.finance_entries ledger ON ledger.tenant_id=posting.tenant_id AND ledger.id=posting.entry_id
  WHERE posting.tenant_id=NEW.tenant_id AND posting.id=NEW.finance_effect_id FOR KEY SHARE OF posting,ledger;
 finance_effect_found:=FOUND;
 IF invoice_found AND finance_effect_found THEN
  creator_actor_id:=reconforge.payment_link_canonical_principal_id(NEW.tenant_id,invoice.created_by);
  approver_actor_id:=reconforge.payment_link_canonical_principal_id(NEW.tenant_id,invoice.approved_by);
  settlement_actor_id:=reconforge.payment_link_canonical_principal_id(NEW.tenant_id,NEW.settlement_actor_id);
  finance_preparer_actor_id:=reconforge.payment_link_canonical_principal_id(
   NEW.tenant_id,finance_effect.snapshot_json->'entry'->>'preparer_actor_id');
  finance_validator_actor_id:=reconforge.payment_link_canonical_principal_id(
   NEW.tenant_id,finance_effect.validator_actor_id);
  finance_posted_actor_id:=reconforge.payment_link_canonical_principal_id(
   NEW.tenant_id,finance_effect.posted_actor_id);
 END IF;
 IF NOT invoice_found OR NOT finance_effect_found
  OR invoice.status<>'Approved' OR NEW.invoice_version_before<>invoice.row_version
  OR (invoice.workspace_id,invoice.organization_id,invoice.legal_entity_id)
       IS DISTINCT FROM (NEW.workspace_id,NEW.organization_id,NEW.legal_entity_id)
  OR (finance_effect.workspace_id,finance_effect.organization_id,finance_effect.legal_entity_id,finance_effect.entry_id,
       finance_effect.currency_code,finance_effect.validation_digest)
       IS DISTINCT FROM (NEW.workspace_id,NEW.organization_id,NEW.legal_entity_id,NEW.finance_entry_id,
       NEW.currency_code,NEW.finance_validation_digest)
  OR finance_effect.source_kind<>'Manual' OR finance_effect.source_id<>finance_effect.entry_id
  OR finance_effect.reverses_effect_id IS NOT NULL
  OR creator_actor_id IS NULL OR approver_actor_id IS NULL OR settlement_actor_id IS NULL
  OR finance_preparer_actor_id IS NULL OR finance_validator_actor_id IS NULL OR finance_posted_actor_id IS NULL
  OR NEW.settlement_actor_id IS DISTINCT FROM settlement_actor_id
  OR NEW.finance_posted_actor_id IS DISTINCT FROM finance_posted_actor_id
  OR settlement_actor_id IN (creator_actor_id,approver_actor_id)
  OR finance_posted_actor_id IN (creator_actor_id,approver_actor_id)
  OR finance_preparer_actor_id IN (finance_validator_actor_id,finance_posted_actor_id)
  OR finance_validator_actor_id=finance_posted_actor_id
  OR finance_effect.snapshot_json->'entry'->>'id' IS DISTINCT FROM finance_effect.entry_id
  OR finance_effect.snapshot_json->'entry'->>'external_reference' IS DISTINCT FROM 'AP-PAYMENT:'||invoice.id
  OR finance_effect.snapshot_json->'entry'->>'currency_code' IS DISTINCT FROM invoice.currency_code
  OR finance_effect.snapshot_json->'entry'->>'posting_date' IS DISTINCT FROM NEW.payment_date
  OR jsonb_typeof(finance_effect.snapshot_json->'lines')<>'array'
  OR jsonb_array_length(finance_effect.snapshot_json->'lines')<>2
  OR NEW.amount_minor+COALESCE((SELECT SUM(prior.amount_minor) FROM reconforge.ap_payment_links prior
       WHERE prior.tenant_id=NEW.tenant_id AND prior.supplier_invoice_id=invoice.id
         AND NOT EXISTS(SELECT 1 FROM reconforge.ap_payment_link_reversals reversed
                        WHERE reversed.tenant_id=prior.tenant_id AND reversed.payment_link_id=prior.id)),0)>invoice.total_minor
 THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Supplier payment link requires an exact approved AP/cash financial effect.'; END IF;
 SELECT count(*) INTO debit_count FROM jsonb_array_elements(finance_effect.snapshot_json->'lines') line(value)
  WHERE line.value->>'account_id'=NEW.ap_account_id
    AND (line.value->>'debit_minor')::bigint=NEW.amount_minor AND (line.value->>'credit_minor')::bigint=0;
 SELECT count(*) INTO credit_count FROM jsonb_array_elements(finance_effect.snapshot_json->'lines') line(value)
  WHERE line.value->>'account_id'=NEW.cash_account_id
    AND (line.value->>'debit_minor')::bigint=0 AND (line.value->>'credit_minor')::bigint=NEW.amount_minor;
 IF debit_count<>1 OR credit_count<>1
  OR NOT EXISTS(SELECT 1 FROM reconforge.domain_audit_events audit
    WHERE audit.tenant_id=NEW.tenant_id AND audit.id=NEW.audit_event_id
      AND audit.actor_user_id=NEW.settlement_actor_id AND audit.object_type='ap_payment_link'
      AND audit.object_id=NEW.id AND audit.action='ap_payment_linked'
      AND audit.metadata_json=jsonb_build_object('supplier_invoice_id',invoice.id,
          'finance_effect_id',finance_effect.id,'finance_entry_id',finance_effect.entry_id,'amount_minor',NEW.amount_minor,
          'currency_code',NEW.currency_code,'invoice_version_before',NEW.invoice_version_before))
  OR NOT EXISTS(SELECT 1 FROM reconforge.outbox_events event
    WHERE event.tenant_id=NEW.tenant_id AND event.event_id=NEW.outbox_event_id
      AND event.event_type='ap.payment_linked' AND event.aggregate_type='ap_payment_link' AND event.aggregate_id=NEW.id
      AND (event.workspace_id,event.organization_id,event.legal_entity_id)
          =(NEW.workspace_id,NEW.organization_id,NEW.legal_entity_id)
      AND event.payload=jsonb_build_object('audit_event_id',NEW.audit_event_id,'payment_link_id',NEW.id,
          'supplier_invoice_id',invoice.id,'finance_effect_id',finance_effect.id,'finance_entry_id',finance_effect.entry_id,
          'amount_minor',NEW.amount_minor,'currency_code',NEW.currency_code))
 THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Supplier payment link requires exact AP/cash lines and retained evidence.'; END IF;
 RETURN NEW;
END $reversal$;

CREATE OR REPLACE FUNCTION reconforge.guard_ap_payment_link_command()
RETURNS trigger LANGUAGE plpgsql SET search_path=reconforge,pg_catalog AS $reversal$
DECLARE link RECORD; invoice RECORD; allocated BIGINT; expected JSONB;
BEGIN
 IF TG_OP<>'INSERT' THEN
  RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Supplier payment command receipts are immutable.';
 END IF;
 SELECT * INTO link FROM reconforge.ap_payment_links WHERE tenant_id=NEW.tenant_id
  AND id=NEW.result_json->>'payment_link_id' FOR KEY SHARE;
 IF link IS NULL OR (link.workspace_id,link.organization_id,link.legal_entity_id,link.settlement_actor_id)
    IS DISTINCT FROM (NEW.workspace_id,NEW.organization_id,NEW.legal_entity_id,NEW.settlement_actor_id)
 THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Supplier payment command requires a retained payment link.'; END IF;
 SELECT * INTO invoice FROM reconforge.ap_supplier_invoices WHERE tenant_id=NEW.tenant_id
  AND id=link.supplier_invoice_id FOR KEY SHARE;
 SELECT COALESCE(SUM(history.amount_minor),0)::bigint INTO allocated FROM reconforge.ap_payment_links history
  WHERE history.tenant_id=NEW.tenant_id AND history.supplier_invoice_id=link.supplier_invoice_id
    AND history.invoice_version_before<=link.invoice_version_before
    AND NOT EXISTS(SELECT 1 FROM reconforge.ap_payment_link_reversals reversal
      WHERE reversal.tenant_id=history.tenant_id AND reversal.payment_link_id=history.id
        AND reversal.invoice_version_before<=link.invoice_version_before);
 expected:=jsonb_build_object('payment_link_id',link.id,'supplier_invoice_id',link.supplier_invoice_id,
   'finance_effect_id',link.finance_effect_id,'finance_entry_id',link.finance_entry_id,
   'ap_account_id',link.ap_account_id,'cash_account_id',link.cash_account_id,'amount_minor',link.amount_minor,
   'currency_code',link.currency_code,'payment_date',link.payment_date,
   'finance_validation_digest',link.finance_validation_digest,'finance_posted_actor_id',link.finance_posted_actor_id,
   'settlement_actor_id',link.settlement_actor_id,'invoice_version_before',link.invoice_version_before,
   'invoice_version_after',link.invoice_version_before+1,'allocated_minor',allocated,
   'outstanding_minor',invoice.total_minor-allocated,
   'invoice_status',CASE WHEN allocated=invoice.total_minor THEN 'Paid' ELSE 'Approved' END,
   'audit_event_id',link.audit_event_id,'outbox_event_id',link.outbox_event_id);
 IF invoice IS NULL OR NEW.result_json IS DISTINCT FROM expected
 THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Supplier payment command receipt does not match retained evidence.'; END IF;
 RETURN NEW;
END $reversal$;

CREATE OR REPLACE FUNCTION reconforge.guard_ap_payment_link_reversal()
RETURNS trigger LANGUAGE plpgsql SET search_path=reconforge,pg_catalog AS $reversal$
DECLARE invoice RECORD; link RECORD; finance_effect RECORD; original_finance_effect RECORD;
 invoice_found BOOLEAN; link_found BOOLEAN; finance_effect_found BOOLEAN;
 original_finance_effect_found BOOLEAN;
 debit_count BIGINT; credit_count BIGINT; creator_actor_id TEXT; approver_actor_id TEXT;
 settlement_actor_id TEXT; original_finance_preparer_actor_id TEXT;
 original_finance_validator_actor_id TEXT; original_finance_posted_actor_id TEXT;
 retained_finance_posted_actor_id TEXT; reversal_actor_id TEXT;
 finance_preparer_actor_id TEXT; finance_validator_actor_id TEXT; finance_posted_actor_id TEXT;
BEGIN
 IF TG_OP<>'INSERT' THEN
  RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Supplier payment-link reversals are immutable.';
 END IF;
 SELECT * INTO invoice FROM reconforge.ap_supplier_invoices
  WHERE tenant_id=NEW.tenant_id AND id=NEW.supplier_invoice_id FOR NO KEY UPDATE;
 invoice_found:=FOUND;
 SELECT * INTO link FROM reconforge.ap_payment_links
  WHERE tenant_id=NEW.tenant_id AND id=NEW.payment_link_id FOR KEY SHARE;
 link_found:=FOUND;
 SELECT posting.*,ledger.validator_actor_id INTO finance_effect FROM reconforge.finance_posting_effects posting
  JOIN reconforge.finance_entries ledger ON ledger.tenant_id=posting.tenant_id AND ledger.id=posting.entry_id
  WHERE posting.tenant_id=NEW.tenant_id AND posting.id=NEW.reversal_finance_effect_id FOR KEY SHARE OF posting,ledger;
 finance_effect_found:=FOUND;
 SELECT posting.*,ledger.validator_actor_id INTO original_finance_effect FROM reconforge.finance_posting_effects posting
  JOIN reconforge.finance_entries ledger ON ledger.tenant_id=posting.tenant_id AND ledger.id=posting.entry_id
  JOIN reconforge.ap_payment_links original_link
    ON original_link.tenant_id=posting.tenant_id AND original_link.finance_effect_id=posting.id
  WHERE original_link.tenant_id=NEW.tenant_id AND original_link.id=NEW.payment_link_id
  FOR KEY SHARE OF posting,ledger;
 original_finance_effect_found:=FOUND;
 IF invoice_found AND link_found AND finance_effect_found AND original_finance_effect_found THEN
  creator_actor_id:=reconforge.payment_link_canonical_principal_id(NEW.tenant_id,invoice.created_by);
  approver_actor_id:=reconforge.payment_link_canonical_principal_id(NEW.tenant_id,invoice.approved_by);
  settlement_actor_id:=reconforge.payment_link_canonical_principal_id(
   NEW.tenant_id,link.settlement_actor_id);
  retained_finance_posted_actor_id:=reconforge.payment_link_canonical_principal_id(
   NEW.tenant_id,link.finance_posted_actor_id);
  original_finance_preparer_actor_id:=reconforge.payment_link_canonical_principal_id(
   NEW.tenant_id,original_finance_effect.snapshot_json->'entry'->>'preparer_actor_id');
  original_finance_validator_actor_id:=reconforge.payment_link_canonical_principal_id(
   NEW.tenant_id,original_finance_effect.validator_actor_id);
  original_finance_posted_actor_id:=reconforge.payment_link_canonical_principal_id(
   NEW.tenant_id,original_finance_effect.posted_actor_id);
  reversal_actor_id:=reconforge.payment_link_canonical_principal_id(
   NEW.tenant_id,NEW.reversal_actor_id);
  finance_preparer_actor_id:=reconforge.payment_link_canonical_principal_id(
   NEW.tenant_id,finance_effect.snapshot_json->'entry'->>'preparer_actor_id');
  finance_validator_actor_id:=reconforge.payment_link_canonical_principal_id(
   NEW.tenant_id,finance_effect.validator_actor_id);
  finance_posted_actor_id:=reconforge.payment_link_canonical_principal_id(
   NEW.tenant_id,finance_effect.posted_actor_id);
 END IF;
 IF NOT invoice_found OR NOT link_found OR NOT finance_effect_found
  OR NOT original_finance_effect_found
  OR invoice.status NOT IN ('Approved','Paid') OR NEW.invoice_version_before<>invoice.row_version
  OR (invoice.workspace_id,invoice.organization_id,invoice.legal_entity_id)
       IS DISTINCT FROM (NEW.workspace_id,NEW.organization_id,NEW.legal_entity_id)
  OR (link.workspace_id,link.organization_id,link.legal_entity_id,link.supplier_invoice_id,link.amount_minor,link.currency_code)
       IS DISTINCT FROM (NEW.workspace_id,NEW.organization_id,NEW.legal_entity_id,invoice.id,NEW.amount_minor,NEW.currency_code)
  OR (finance_effect.workspace_id,finance_effect.organization_id,finance_effect.legal_entity_id,finance_effect.entry_id,
       finance_effect.currency_code,finance_effect.validation_digest)
       IS DISTINCT FROM (NEW.workspace_id,NEW.organization_id,NEW.legal_entity_id,NEW.reversal_finance_entry_id,
       NEW.currency_code,NEW.finance_validation_digest)
  OR finance_effect.source_kind<>'Reversal' OR finance_effect.source_id<>link.finance_effect_id
  OR finance_effect.reverses_effect_id<>link.finance_effect_id
  OR creator_actor_id IS NULL OR approver_actor_id IS NULL OR settlement_actor_id IS NULL
  OR retained_finance_posted_actor_id IS NULL OR original_finance_preparer_actor_id IS NULL
  OR original_finance_validator_actor_id IS NULL OR original_finance_posted_actor_id IS NULL
  OR reversal_actor_id IS NULL OR finance_preparer_actor_id IS NULL
  OR finance_validator_actor_id IS NULL OR finance_posted_actor_id IS NULL
  OR retained_finance_posted_actor_id<>original_finance_posted_actor_id
  OR settlement_actor_id IN (creator_actor_id,approver_actor_id)
  OR retained_finance_posted_actor_id IN (creator_actor_id,approver_actor_id)
  OR original_finance_preparer_actor_id IN (original_finance_validator_actor_id,original_finance_posted_actor_id)
  OR original_finance_validator_actor_id=original_finance_posted_actor_id
  OR NEW.reversal_actor_id IS DISTINCT FROM reversal_actor_id
  OR NEW.finance_posted_actor_id IS DISTINCT FROM finance_posted_actor_id
  OR reversal_actor_id IN (creator_actor_id,approver_actor_id,settlement_actor_id,finance_posted_actor_id)
  OR finance_preparer_actor_id IN (finance_validator_actor_id,finance_posted_actor_id,reversal_actor_id)
  OR finance_validator_actor_id IN (finance_posted_actor_id,reversal_actor_id)
  OR finance_posted_actor_id=reversal_actor_id
  OR finance_effect.snapshot_json->'entry'->>'id' IS DISTINCT FROM finance_effect.entry_id
  OR finance_effect.snapshot_json->'entry'->>'reverses_posting_id' IS DISTINCT FROM link.finance_effect_id
  OR finance_effect.snapshot_json->'entry'->>'external_reference' IS DISTINCT FROM link.finance_effect_id
  OR finance_effect.snapshot_json->'entry'->>'currency_code' IS DISTINCT FROM link.currency_code
  OR finance_effect.snapshot_json->'entry'->>'posting_date' IS DISTINCT FROM NEW.reversal_date
  OR jsonb_typeof(finance_effect.snapshot_json->'lines')<>'array'
  OR jsonb_array_length(finance_effect.snapshot_json->'lines')<>2
  OR EXISTS(SELECT 1 FROM reconforge.ap_payment_link_reversals prior
            WHERE prior.tenant_id=NEW.tenant_id
              AND (prior.payment_link_id=link.id OR prior.reversal_finance_effect_id=finance_effect.id))
 THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Supplier payment-link reversal requires an exact independently posted Finance inverse.'; END IF;
 SELECT count(*) INTO debit_count FROM jsonb_array_elements(finance_effect.snapshot_json->'lines') line(value)
  WHERE line.value->>'account_id'=link.cash_account_id
    AND (line.value->>'debit_minor')::bigint=link.amount_minor AND (line.value->>'credit_minor')::bigint=0;
 SELECT count(*) INTO credit_count FROM jsonb_array_elements(finance_effect.snapshot_json->'lines') line(value)
  WHERE line.value->>'account_id'=link.ap_account_id
    AND (line.value->>'debit_minor')::bigint=0 AND (line.value->>'credit_minor')::bigint=link.amount_minor;
 IF debit_count<>1 OR credit_count<>1
  OR NOT EXISTS(SELECT 1 FROM reconforge.domain_audit_events audit
    WHERE audit.tenant_id=NEW.tenant_id AND audit.id=NEW.audit_event_id
      AND audit.actor_user_id=NEW.reversal_actor_id AND audit.object_type='ap_payment_link_reversal'
      AND audit.object_id=NEW.id AND audit.action='ap_payment_link_reversed'
      AND audit.metadata_json=jsonb_build_object('payment_link_id',link.id,'supplier_invoice_id',invoice.id,
          'original_finance_effect_id',link.finance_effect_id,'reversal_finance_effect_id',finance_effect.id,
          'amount_minor',link.amount_minor,'currency_code',link.currency_code,
          'invoice_version_before',NEW.invoice_version_before))
  OR NOT EXISTS(SELECT 1 FROM reconforge.outbox_events event
    WHERE event.tenant_id=NEW.tenant_id AND event.event_id=NEW.outbox_event_id
      AND event.event_type='ap.payment_link_reversed' AND event.aggregate_type='ap_payment_link_reversal'
      AND event.aggregate_id=NEW.id
      AND (event.workspace_id,event.organization_id,event.legal_entity_id)
          =(NEW.workspace_id,NEW.organization_id,NEW.legal_entity_id)
      AND event.payload=jsonb_build_object('audit_event_id',NEW.audit_event_id,
          'payment_link_reversal_id',NEW.id,'payment_link_id',link.id,'supplier_invoice_id',invoice.id,
          'reversal_finance_effect_id',finance_effect.id,'reversal_finance_entry_id',finance_effect.entry_id,
          'amount_minor',link.amount_minor,'currency_code',link.currency_code))
 THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Supplier payment-link reversal requires exact AP/cash inverse lines and retained evidence.'; END IF;
 RETURN NEW;
END $reversal$;
CREATE TRIGGER ap_payment_link_reversal_guard BEFORE INSERT OR UPDATE OR DELETE ON reconforge.ap_payment_link_reversals
 FOR EACH ROW EXECUTE FUNCTION reconforge.guard_ap_payment_link_reversal();

CREATE OR REPLACE FUNCTION reconforge.guard_ap_supplier_invoice_payment_status()
RETURNS trigger LANGUAGE plpgsql SET search_path=reconforge,pg_catalog AS $reversal$
DECLARE allocated BIGINT; current_link BOOLEAN; current_reversal BOOLEAN;
BEGIN
 IF TG_OP='DELETE' THEN
  IF EXISTS(SELECT 1 FROM reconforge.ap_payment_links link WHERE link.tenant_id=OLD.tenant_id AND link.supplier_invoice_id=OLD.id) THEN
   RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Supplier invoices with payment evidence cannot be deleted.';
  END IF;
  RETURN OLD;
 END IF;
 IF OLD.status IN ('Approved','Paid') THEN
  SELECT COALESCE(SUM(link.amount_minor),0)::bigint INTO allocated FROM reconforge.ap_payment_links link
    WHERE link.tenant_id=OLD.tenant_id AND link.supplier_invoice_id=OLD.id
      AND NOT EXISTS(SELECT 1 FROM reconforge.ap_payment_link_reversals reversal
                     WHERE reversal.tenant_id=link.tenant_id AND reversal.payment_link_id=link.id);
  SELECT EXISTS(SELECT 1 FROM reconforge.ap_payment_links link
     WHERE link.tenant_id=OLD.tenant_id AND link.supplier_invoice_id=OLD.id
       AND link.invoice_version_before=OLD.row_version) INTO current_link;
  SELECT EXISTS(SELECT 1 FROM reconforge.ap_payment_link_reversals reversal
     WHERE reversal.tenant_id=OLD.tenant_id AND reversal.supplier_invoice_id=OLD.id
       AND reversal.invoice_version_before=OLD.row_version) INTO current_reversal;
  IF NOT (current_link OR current_reversal) OR NEW.row_version<>OLD.row_version+1
     OR NEW.status<>(CASE WHEN allocated=OLD.total_minor THEN 'Paid' ELSE 'Approved' END)
  THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Supplier invoice payment state requires immutable exact payment-link evidence.'; END IF;
 END IF;
 RETURN NEW;
END $reversal$;

CREATE OR REPLACE FUNCTION reconforge.advance_ap_supplier_invoice_payment_link()
RETURNS trigger LANGUAGE plpgsql SET search_path=reconforge,pg_catalog AS $reversal$
DECLARE allocated BIGINT;
BEGIN
 SELECT COALESCE(SUM(link.amount_minor),0)::bigint INTO allocated FROM reconforge.ap_payment_links link
  WHERE link.tenant_id=NEW.tenant_id AND link.supplier_invoice_id=NEW.supplier_invoice_id
    AND NOT EXISTS(SELECT 1 FROM reconforge.ap_payment_link_reversals reversal
                   WHERE reversal.tenant_id=link.tenant_id AND reversal.payment_link_id=link.id);
 UPDATE reconforge.ap_supplier_invoices
    SET status=CASE WHEN allocated=total_minor THEN 'Paid' ELSE 'Approved' END,
        updated_at=NEW.created_at,row_version=row_version+1
  WHERE tenant_id=NEW.tenant_id AND id=NEW.supplier_invoice_id
    AND status='Approved' AND row_version=NEW.invoice_version_before;
 IF NOT FOUND THEN RAISE EXCEPTION USING ERRCODE='23514',
   MESSAGE='Supplier payment link must atomically advance its invoice state.'; END IF;
 RETURN NEW;
END $reversal$;

CREATE OR REPLACE FUNCTION reconforge.advance_ap_supplier_invoice_payment_link_reversal()
RETURNS trigger LANGUAGE plpgsql SET search_path=reconforge,pg_catalog AS $reversal$
DECLARE allocated BIGINT;
BEGIN
 SELECT COALESCE(SUM(link.amount_minor),0)::bigint INTO allocated FROM reconforge.ap_payment_links link
  WHERE link.tenant_id=NEW.tenant_id AND link.supplier_invoice_id=NEW.supplier_invoice_id
    AND NOT EXISTS(SELECT 1 FROM reconforge.ap_payment_link_reversals reversal
                   WHERE reversal.tenant_id=link.tenant_id AND reversal.payment_link_id=link.id);
 UPDATE reconforge.ap_supplier_invoices
    SET status=CASE WHEN allocated=total_minor THEN 'Paid' ELSE 'Approved' END,
        updated_at=NEW.created_at,row_version=row_version+1
  WHERE tenant_id=NEW.tenant_id AND id=NEW.supplier_invoice_id
    AND status IN ('Approved','Paid') AND row_version=NEW.invoice_version_before;
 IF NOT FOUND THEN RAISE EXCEPTION USING ERRCODE='23514',
   MESSAGE='Supplier payment-link reversal must atomically advance its invoice state.'; END IF;
 RETURN NEW;
END $reversal$;
CREATE TRIGGER ap_payment_link_reversal_invoice_transition AFTER INSERT ON reconforge.ap_payment_link_reversals
 FOR EACH ROW EXECUTE FUNCTION reconforge.advance_ap_supplier_invoice_payment_link_reversal();

CREATE OR REPLACE FUNCTION reconforge.guard_ap_payment_link_reversal_command()
RETURNS trigger LANGUAGE plpgsql SET search_path=reconforge,pg_catalog AS $reversal$
DECLARE reversal RECORD; link RECORD; invoice RECORD; allocated BIGINT; expected JSONB;
BEGIN
 IF TG_OP<>'INSERT' THEN
  RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Supplier payment-link reversal command receipts are immutable.';
 END IF;
 SELECT * INTO reversal FROM reconforge.ap_payment_link_reversals
  WHERE tenant_id=NEW.tenant_id AND id=NEW.result_json->>'payment_link_reversal_id' FOR KEY SHARE;
 IF reversal IS NULL OR (reversal.workspace_id,reversal.organization_id,reversal.legal_entity_id,reversal.reversal_actor_id)
    IS DISTINCT FROM (NEW.workspace_id,NEW.organization_id,NEW.legal_entity_id,NEW.reversal_actor_id)
 THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Supplier payment-link reversal command requires retained reversal evidence.'; END IF;
 SELECT * INTO link FROM reconforge.ap_payment_links WHERE tenant_id=NEW.tenant_id AND id=reversal.payment_link_id FOR KEY SHARE;
 SELECT * INTO invoice FROM reconforge.ap_supplier_invoices WHERE tenant_id=NEW.tenant_id AND id=reversal.supplier_invoice_id FOR KEY SHARE;
 SELECT COALESCE(SUM(history.amount_minor),0)::bigint INTO allocated FROM reconforge.ap_payment_links history
  WHERE history.tenant_id=NEW.tenant_id AND history.supplier_invoice_id=reversal.supplier_invoice_id
    AND history.invoice_version_before<=reversal.invoice_version_before
    AND NOT EXISTS(SELECT 1 FROM reconforge.ap_payment_link_reversals historical_reversal
      WHERE historical_reversal.tenant_id=history.tenant_id AND historical_reversal.payment_link_id=history.id
        AND historical_reversal.invoice_version_before<=reversal.invoice_version_before);
 expected:=jsonb_build_object('payment_link_reversal_id',reversal.id,'payment_link_id',link.id,
   'supplier_invoice_id',reversal.supplier_invoice_id,'original_finance_effect_id',link.finance_effect_id,
   'original_finance_entry_id',link.finance_entry_id,'reversal_finance_effect_id',reversal.reversal_finance_effect_id,
   'reversal_finance_entry_id',reversal.reversal_finance_entry_id,'amount_minor',reversal.amount_minor,
   'currency_code',reversal.currency_code,'reversal_date',reversal.reversal_date,
   'finance_validation_digest',reversal.finance_validation_digest,'finance_posted_actor_id',reversal.finance_posted_actor_id,
   'reversal_actor_id',reversal.reversal_actor_id,'invoice_version_before',reversal.invoice_version_before,
   'invoice_version_after',reversal.invoice_version_before+1,'allocated_minor',allocated,
   'outstanding_minor',invoice.total_minor-allocated,'invoice_status',CASE WHEN allocated=invoice.total_minor THEN 'Paid' ELSE 'Approved' END,
   'audit_event_id',reversal.audit_event_id,'outbox_event_id',reversal.outbox_event_id);
 IF link IS NULL OR invoice IS NULL OR NEW.result_json IS DISTINCT FROM expected
 THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Supplier payment-link reversal command receipt does not match retained evidence.'; END IF;
 RETURN NEW;
END $reversal$;
CREATE TRIGGER ap_payment_link_reversal_command_guard BEFORE INSERT OR UPDATE OR DELETE ON reconforge.ap_payment_link_reversal_commands
 FOR EACH ROW EXECUTE FUNCTION reconforge.guard_ap_payment_link_reversal_command();

ALTER TABLE reconforge.ap_payment_link_reversals ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.ap_payment_link_reversals FORCE ROW LEVEL SECURITY;
CREATE POLICY ap_payment_link_reversal_scope ON reconforge.ap_payment_link_reversals
 USING (tenant_id=current_setting('app.tenant_id',true)
   AND (NULLIF(current_setting('app.workspace_id',true),'') IS NULL OR workspace_id=current_setting('app.workspace_id',true))
   AND (NULLIF(current_setting('app.organization_id',true),'') IS NULL OR organization_id=current_setting('app.organization_id',true))
   AND (NULLIF(current_setting('app.legal_entity_id',true),'') IS NULL OR legal_entity_id=current_setting('app.legal_entity_id',true)))
 WITH CHECK (tenant_id=current_setting('app.tenant_id',true)
   AND (NULLIF(current_setting('app.workspace_id',true),'') IS NULL OR workspace_id=current_setting('app.workspace_id',true))
   AND (NULLIF(current_setting('app.organization_id',true),'') IS NULL OR organization_id=current_setting('app.organization_id',true))
   AND (NULLIF(current_setting('app.legal_entity_id',true),'') IS NULL OR legal_entity_id=current_setting('app.legal_entity_id',true)));
ALTER TABLE reconforge.ap_payment_link_reversal_commands ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.ap_payment_link_reversal_commands FORCE ROW LEVEL SECURITY;
CREATE POLICY ap_payment_link_reversal_command_scope ON reconforge.ap_payment_link_reversal_commands
 USING (tenant_id=current_setting('app.tenant_id',true)
   AND (NULLIF(current_setting('app.workspace_id',true),'') IS NULL OR workspace_id=current_setting('app.workspace_id',true))
   AND (NULLIF(current_setting('app.organization_id',true),'') IS NULL OR organization_id=current_setting('app.organization_id',true))
   AND (NULLIF(current_setting('app.legal_entity_id',true),'') IS NULL OR legal_entity_id=current_setting('app.legal_entity_id',true)))
 WITH CHECK (tenant_id=current_setting('app.tenant_id',true)
   AND (NULLIF(current_setting('app.workspace_id',true),'') IS NULL OR workspace_id=current_setting('app.workspace_id',true))
   AND (NULLIF(current_setting('app.organization_id',true),'') IS NULL OR organization_id=current_setting('app.organization_id',true))
   AND (NULLIF(current_setting('app.legal_entity_id',true),'') IS NULL OR legal_entity_id=current_setting('app.legal_entity_id',true)));

INSERT INTO reconforge.identity_permissions(tenant_id,name,description)
 SELECT tenant.id,'payables.reverse','Reverse retained supplier payment evidence only with an independently posted exact Finance inverse.'
 FROM reconforge.tenants tenant ON CONFLICT(tenant_id,name) DO NOTHING;
INSERT INTO reconforge.identity_role_permissions(tenant_id,role_id,permission_name)
 SELECT roles.tenant_id,roles.id,'payables.reverse' FROM reconforge.identity_roles roles
 WHERE roles.name IN ('admin','controller') ON CONFLICT DO NOTHING;
CREATE OR REPLACE FUNCTION reconforge.seed_ap_payment_link_reversal_permissions()
RETURNS trigger LANGUAGE plpgsql SET search_path=reconforge,pg_catalog AS $reversal$
BEGIN
 IF TG_TABLE_NAME='tenants' THEN
  INSERT INTO reconforge.identity_permissions(tenant_id,name,description) VALUES
   (NEW.id,'payables.reverse','Reverse retained supplier payment evidence only with an independently posted exact Finance inverse.')
  ON CONFLICT(tenant_id,name) DO NOTHING;
 ELSIF TG_TABLE_NAME='identity_roles' AND NEW.name IN ('admin','controller') THEN
  INSERT INTO reconforge.identity_role_permissions(tenant_id,role_id,permission_name)
   VALUES(NEW.tenant_id,NEW.id,'payables.reverse') ON CONFLICT DO NOTHING;
 END IF;
 RETURN NEW;
END $reversal$;
CREATE TRIGGER ap_payment_link_reversal_permission_tenant_seed AFTER INSERT ON reconforge.tenants
 FOR EACH ROW EXECUTE FUNCTION reconforge.seed_ap_payment_link_reversal_permissions();
CREATE TRIGGER ap_payment_link_reversal_permission_role_seed AFTER INSERT ON reconforge.identity_roles
 FOR EACH ROW EXECUTE FUNCTION reconforge.seed_ap_payment_link_reversal_permissions();
"""


DOWNGRADE_SQL = r"""
DO $reversal$
BEGIN
 IF NOT EXISTS (
   SELECT 1 FROM pg_roles
   WHERE rolname=current_user AND (rolsuper OR rolbypassrls)
 ) THEN
  RAISE EXCEPTION 'payables payment-link reversal migration requires a role that bypasses forced row security';
 END IF;
END $reversal$;

DO $reversal$
BEGIN
 IF EXISTS(SELECT 1 FROM reconforge.ap_payment_link_reversals)
    OR EXISTS(SELECT 1 FROM reconforge.ap_payment_link_reversal_commands) THEN
  RAISE EXCEPTION USING ERRCODE='23514',
   MESSAGE='Supplier payment-link reversal evidence prevents downgrade; restore a verified pre-upgrade backup.';
 END IF;
END $reversal$;

DROP TRIGGER ap_payment_link_reversal_permission_role_seed ON reconforge.identity_roles;
DROP TRIGGER ap_payment_link_reversal_permission_tenant_seed ON reconforge.tenants;
DROP FUNCTION reconforge.seed_ap_payment_link_reversal_permissions();
DELETE FROM reconforge.identity_role_permissions WHERE permission_name='payables.reverse';
DELETE FROM reconforge.identity_permissions WHERE name='payables.reverse';
DROP TRIGGER ap_payment_link_reversal_command_guard ON reconforge.ap_payment_link_reversal_commands;
DROP FUNCTION reconforge.guard_ap_payment_link_reversal_command();
DROP TRIGGER ap_payment_link_reversal_invoice_transition ON reconforge.ap_payment_link_reversals;
DROP FUNCTION reconforge.advance_ap_supplier_invoice_payment_link_reversal();
DROP TRIGGER ap_payment_link_reversal_guard ON reconforge.ap_payment_link_reversals;
DROP FUNCTION reconforge.guard_ap_payment_link_reversal();
DROP TABLE reconforge.ap_payment_link_reversal_commands;
DROP TABLE reconforge.ap_payment_link_reversals;

-- Restore the three 0105 functions whose replacement above referenced the
-- now-removed reversal relation.  The 0105 guards remain attached to their
-- existing triggers and retain the original append-only contract.
CREATE OR REPLACE FUNCTION reconforge.guard_ap_supplier_invoice_payment_status()
RETURNS trigger LANGUAGE plpgsql SET search_path=reconforge,pg_catalog AS $reversal$
DECLARE allocated BIGINT; current_link BOOLEAN;
BEGIN
 IF TG_OP='DELETE' THEN
  IF EXISTS(SELECT 1 FROM reconforge.ap_payment_links link WHERE link.tenant_id=OLD.tenant_id AND link.supplier_invoice_id=OLD.id) THEN
   RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Supplier invoices with payment evidence cannot be deleted.';
  END IF;
  RETURN OLD;
 END IF;
 IF OLD.status='Paid' AND NEW IS DISTINCT FROM OLD THEN
  RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Paid supplier invoices are immutable.';
 END IF;
 IF OLD.status='Approved' THEN
  SELECT COALESCE(SUM(amount_minor),0)::bigint INTO allocated FROM reconforge.ap_payment_links
    WHERE tenant_id=OLD.tenant_id AND supplier_invoice_id=OLD.id;
  SELECT EXISTS(SELECT 1 FROM reconforge.ap_payment_links link
     WHERE link.tenant_id=OLD.tenant_id AND link.supplier_invoice_id=OLD.id
       AND link.invoice_version_before=OLD.row_version) INTO current_link;
  IF NOT current_link OR NEW.row_version<>OLD.row_version+1
     OR NEW.status<>(CASE WHEN allocated=OLD.total_minor THEN 'Paid' ELSE 'Approved' END)
  THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Approved supplier invoice payment state requires its exact immutable payment link.'; END IF;
 END IF;
 RETURN NEW;
END $reversal$;

CREATE OR REPLACE FUNCTION reconforge.advance_ap_supplier_invoice_payment_link()
RETURNS trigger LANGUAGE plpgsql SET search_path=reconforge,pg_catalog AS $reversal$
DECLARE allocated BIGINT;
BEGIN
 SELECT COALESCE(SUM(amount_minor),0)::bigint INTO allocated FROM reconforge.ap_payment_links
  WHERE tenant_id=NEW.tenant_id AND supplier_invoice_id=NEW.supplier_invoice_id;
 UPDATE reconforge.ap_supplier_invoices
    SET status=CASE WHEN allocated=total_minor THEN 'Paid' ELSE 'Approved' END,
        updated_at=NEW.created_at,row_version=row_version+1
  WHERE tenant_id=NEW.tenant_id AND id=NEW.supplier_invoice_id
    AND status='Approved' AND row_version=NEW.invoice_version_before;
 IF NOT FOUND THEN RAISE EXCEPTION USING ERRCODE='23514',
   MESSAGE='Supplier payment link must atomically advance its invoice state.'; END IF;
 RETURN NEW;
END $reversal$;

CREATE OR REPLACE FUNCTION reconforge.guard_ap_payment_link()
RETURNS trigger LANGUAGE plpgsql SET search_path=reconforge,pg_catalog AS $reversal$
DECLARE invoice RECORD; finance_effect RECORD; debit_count BIGINT; credit_count BIGINT;
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Supplier payment links are immutable.'; END IF;
 SELECT * INTO invoice FROM reconforge.ap_supplier_invoices WHERE tenant_id=NEW.tenant_id AND id=NEW.supplier_invoice_id FOR NO KEY UPDATE;
 SELECT posting.*,ledger.validator_actor_id INTO finance_effect FROM reconforge.finance_posting_effects posting
  JOIN reconforge.finance_entries ledger ON ledger.tenant_id=posting.tenant_id AND ledger.id=posting.entry_id
  WHERE posting.tenant_id=NEW.tenant_id AND posting.id=NEW.finance_effect_id FOR KEY SHARE OF posting,ledger;
 IF invoice IS NULL OR finance_effect IS NULL OR invoice.status<>'Approved' OR NEW.invoice_version_before<>invoice.row_version
  OR (invoice.workspace_id,invoice.organization_id,invoice.legal_entity_id) IS DISTINCT FROM (NEW.workspace_id,NEW.organization_id,NEW.legal_entity_id)
  OR (finance_effect.workspace_id,finance_effect.organization_id,finance_effect.legal_entity_id,finance_effect.entry_id,finance_effect.currency_code,finance_effect.validation_digest,finance_effect.posted_actor_id)
     IS DISTINCT FROM (NEW.workspace_id,NEW.organization_id,NEW.legal_entity_id,NEW.finance_entry_id,NEW.currency_code,NEW.finance_validation_digest,NEW.finance_posted_actor_id)
  OR finance_effect.source_kind<>'Manual' OR finance_effect.source_id<>finance_effect.entry_id OR finance_effect.reverses_effect_id IS NOT NULL
  OR invoice.created_by IS NULL OR btrim(invoice.created_by)='' OR invoice.approved_by IS NULL OR btrim(invoice.approved_by)=''
  OR NEW.settlement_actor_id IN (invoice.created_by,invoice.approved_by) OR NEW.finance_posted_actor_id IN (invoice.created_by,invoice.approved_by)
  OR finance_effect.validator_actor_id IS NULL OR (finance_effect.snapshot_json->'entry'->>'preparer_actor_id') IS NULL
  OR (finance_effect.snapshot_json->'entry'->>'preparer_actor_id') IN (finance_effect.validator_actor_id,finance_effect.posted_actor_id)
  OR finance_effect.validator_actor_id=finance_effect.posted_actor_id
  OR finance_effect.snapshot_json->'entry'->>'id' IS DISTINCT FROM finance_effect.entry_id
  OR finance_effect.snapshot_json->'entry'->>'external_reference' IS DISTINCT FROM 'AP-PAYMENT:'||invoice.id
  OR finance_effect.snapshot_json->'entry'->>'currency_code' IS DISTINCT FROM invoice.currency_code
  OR finance_effect.snapshot_json->'entry'->>'posting_date' IS DISTINCT FROM NEW.payment_date
  OR jsonb_typeof(finance_effect.snapshot_json->'lines')<>'array' OR jsonb_array_length(finance_effect.snapshot_json->'lines')<>2
  OR NEW.amount_minor+COALESCE((SELECT SUM(amount_minor) FROM reconforge.ap_payment_links prior WHERE prior.tenant_id=NEW.tenant_id AND prior.supplier_invoice_id=invoice.id),0)>invoice.total_minor
 THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Supplier payment link requires an exact approved AP/cash financial effect.'; END IF;
 SELECT count(*) INTO debit_count FROM jsonb_array_elements(finance_effect.snapshot_json->'lines') line(value)
  WHERE line.value->>'account_id'=NEW.ap_account_id AND (line.value->>'debit_minor')::bigint=NEW.amount_minor AND (line.value->>'credit_minor')::bigint=0;
 SELECT count(*) INTO credit_count FROM jsonb_array_elements(finance_effect.snapshot_json->'lines') line(value)
  WHERE line.value->>'account_id'=NEW.cash_account_id AND (line.value->>'debit_minor')::bigint=0 AND (line.value->>'credit_minor')::bigint=NEW.amount_minor;
 IF debit_count<>1 OR credit_count<>1 THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Supplier payment link requires exact AP/cash lines and retained evidence.'; END IF;
 RETURN NEW;
END $reversal$;
DROP FUNCTION reconforge.payment_link_canonical_principal_id(TEXT,TEXT);
"""


def upgrade() -> None:
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    op.execute(DOWNGRADE_SQL)
