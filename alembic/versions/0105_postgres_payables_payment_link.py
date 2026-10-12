"""Add immutable evidence-bound supplier payment links."""

from alembic import op

revision = "0105_pg_payables_payment_link"
down_revision = "0104_pg_exception_review_api"
branch_labels = None
depends_on = None


# This revision deliberately owns its SQL literal.  The relation between an AP
# invoice and a Finance posting is financial evidence and must not drift when a
# later runtime adapter evolves.
UPGRADE_SQL = r"""
DO $payment$
BEGIN
 IF NOT EXISTS (
   SELECT 1 FROM pg_roles
   WHERE rolname=current_user AND (rolsuper OR rolbypassrls)
 ) THEN
  RAISE EXCEPTION 'payables payment-link migration requires a role that bypasses forced row security';
 END IF;
END $payment$;

CREATE TABLE reconforge.ap_payment_links (
 tenant_id TEXT NOT NULL,id TEXT NOT NULL,workspace_id TEXT NOT NULL,organization_id TEXT NOT NULL,
 legal_entity_id TEXT NOT NULL,supplier_invoice_id TEXT NOT NULL,finance_effect_id TEXT NOT NULL,
 finance_entry_id TEXT NOT NULL,ap_account_id TEXT NOT NULL,cash_account_id TEXT NOT NULL,
 amount_minor BIGINT NOT NULL CHECK(amount_minor BETWEEN 1 AND 9000000000000000000),
 currency_code TEXT NOT NULL,payment_date TEXT NOT NULL,
 finance_validation_digest TEXT NOT NULL CHECK(finance_validation_digest ~ '^[0-9a-f]{64}$'),
 finance_posted_actor_id TEXT NOT NULL,settlement_actor_id TEXT NOT NULL,
 invoice_version_before BIGINT NOT NULL CHECK(invoice_version_before>0),
 audit_event_id TEXT NOT NULL,outbox_event_id TEXT NOT NULL,created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(tenant_id,id),UNIQUE(tenant_id,finance_effect_id),UNIQUE(tenant_id,finance_entry_id),
 UNIQUE(tenant_id,supplier_invoice_id,finance_effect_id),
 UNIQUE(tenant_id,supplier_invoice_id,invoice_version_before),CHECK(ap_account_id<>cash_account_id),
 FOREIGN KEY(tenant_id,workspace_id) REFERENCES reconforge.domain_workspaces(tenant_id,id),
 FOREIGN KEY(tenant_id,organization_id) REFERENCES reconforge.organizations(tenant_id,id),
 FOREIGN KEY(tenant_id,legal_entity_id) REFERENCES reconforge.legal_entities(tenant_id,id),
 FOREIGN KEY(tenant_id,supplier_invoice_id) REFERENCES reconforge.ap_supplier_invoices(tenant_id,id),
 FOREIGN KEY(tenant_id,finance_effect_id) REFERENCES reconforge.finance_posting_effects(tenant_id,id),
 FOREIGN KEY(tenant_id,finance_entry_id) REFERENCES reconforge.finance_entries(tenant_id,id),
 FOREIGN KEY(tenant_id,ap_account_id) REFERENCES reconforge.finance_accounts(tenant_id,id),
 FOREIGN KEY(tenant_id,cash_account_id) REFERENCES reconforge.finance_accounts(tenant_id,id),
 FOREIGN KEY(tenant_id,finance_posted_actor_id) REFERENCES reconforge.identity_users(tenant_id,id),
 FOREIGN KEY(tenant_id,settlement_actor_id) REFERENCES reconforge.identity_users(tenant_id,id),
 FOREIGN KEY(tenant_id,audit_event_id) REFERENCES reconforge.domain_audit_events(tenant_id,id),
 FOREIGN KEY(tenant_id,outbox_event_id) REFERENCES reconforge.outbox_events(tenant_id,event_id)
);
CREATE INDEX ap_payment_links_invoice_order ON reconforge.ap_payment_links
 (tenant_id,supplier_invoice_id,payment_date,id);
CREATE TABLE reconforge.ap_payment_link_commands (
 tenant_id TEXT NOT NULL,workspace_id TEXT NOT NULL,organization_id TEXT NOT NULL,legal_entity_id TEXT NOT NULL,
 command_id TEXT NOT NULL CHECK(length(command_id) BETWEEN 1 AND 160),settlement_actor_id TEXT NOT NULL,
 request_digest TEXT NOT NULL CHECK(request_digest ~ '^[0-9a-f]{64}$'),
 result_json JSONB NOT NULL CHECK(octet_length(result_json::text)<=2097152 AND jsonb_typeof(result_json)='object'),
 created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(tenant_id,workspace_id,command_id),
 FOREIGN KEY(tenant_id,workspace_id) REFERENCES reconforge.domain_workspaces(tenant_id,id),
 FOREIGN KEY(tenant_id,organization_id) REFERENCES reconforge.organizations(tenant_id,id),
 FOREIGN KEY(tenant_id,legal_entity_id) REFERENCES reconforge.legal_entities(tenant_id,id),
 FOREIGN KEY(tenant_id,settlement_actor_id) REFERENCES reconforge.identity_users(tenant_id,id)
);
CREATE INDEX ap_payment_link_commands_scope ON reconforge.ap_payment_link_commands
 (tenant_id,workspace_id,organization_id,legal_entity_id,created_at,command_id);

CREATE OR REPLACE FUNCTION reconforge.guard_ap_payment_link()
RETURNS trigger LANGUAGE plpgsql SET search_path=reconforge,pg_catalog AS $payment$
DECLARE invoice RECORD; finance_effect RECORD; debit_count BIGINT; credit_count BIGINT;
BEGIN
 IF TG_OP<>'INSERT' THEN
  RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Supplier payment links are immutable.';
 END IF;
 SELECT * INTO invoice FROM reconforge.ap_supplier_invoices
  WHERE tenant_id=NEW.tenant_id AND id=NEW.supplier_invoice_id FOR NO KEY UPDATE;
 SELECT posting.*,ledger.validator_actor_id INTO finance_effect FROM reconforge.finance_posting_effects posting
  JOIN reconforge.finance_entries ledger ON ledger.tenant_id=posting.tenant_id AND ledger.id=posting.entry_id
  WHERE posting.tenant_id=NEW.tenant_id AND posting.id=NEW.finance_effect_id FOR KEY SHARE OF posting,ledger;
 IF invoice IS NULL OR finance_effect IS NULL
  OR invoice.status<>'Approved'
  OR NEW.invoice_version_before<>invoice.row_version
  OR (invoice.workspace_id,invoice.organization_id,invoice.legal_entity_id)
     IS DISTINCT FROM (NEW.workspace_id,NEW.organization_id,NEW.legal_entity_id)
  OR (finance_effect.workspace_id,finance_effect.organization_id,finance_effect.legal_entity_id,finance_effect.entry_id,finance_effect.currency_code,
      finance_effect.validation_digest,finance_effect.posted_actor_id)
     IS DISTINCT FROM (NEW.workspace_id,NEW.organization_id,NEW.legal_entity_id,NEW.finance_entry_id,
      NEW.currency_code,NEW.finance_validation_digest,NEW.finance_posted_actor_id)
  OR finance_effect.source_kind<>'Manual' OR finance_effect.source_id<>finance_effect.entry_id OR finance_effect.reverses_effect_id IS NOT NULL
  OR invoice.created_by IS NULL OR btrim(invoice.created_by)=''
  OR invoice.approved_by IS NULL OR btrim(invoice.approved_by)=''
  OR NEW.settlement_actor_id IN (invoice.created_by,invoice.approved_by)
  OR NEW.finance_posted_actor_id IN (invoice.created_by,invoice.approved_by)
  OR finance_effect.validator_actor_id IS NULL
  OR (finance_effect.snapshot_json->'entry'->>'preparer_actor_id') IS NULL
  OR (finance_effect.snapshot_json->'entry'->>'preparer_actor_id') IN (finance_effect.validator_actor_id,finance_effect.posted_actor_id)
  OR finance_effect.validator_actor_id=finance_effect.posted_actor_id
  OR finance_effect.snapshot_json->'entry'->>'id' IS DISTINCT FROM finance_effect.entry_id
  OR finance_effect.snapshot_json->'entry'->>'external_reference' IS DISTINCT FROM 'AP-PAYMENT:'||invoice.id
  OR finance_effect.snapshot_json->'entry'->>'currency_code' IS DISTINCT FROM invoice.currency_code
  OR finance_effect.snapshot_json->'entry'->>'posting_date' IS DISTINCT FROM NEW.payment_date
  OR jsonb_typeof(finance_effect.snapshot_json->'lines')<>'array'
  OR jsonb_array_length(finance_effect.snapshot_json->'lines')<>2
  OR NEW.amount_minor + COALESCE((SELECT SUM(amount_minor) FROM reconforge.ap_payment_links prior
       WHERE prior.tenant_id=NEW.tenant_id AND prior.supplier_invoice_id=invoice.id),0)>invoice.total_minor
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
      AND event.event_type='ap.payment_linked' AND event.aggregate_type='ap_payment_link'
      AND event.aggregate_id=NEW.id
      AND (event.workspace_id,event.organization_id,event.legal_entity_id)
          =(NEW.workspace_id,NEW.organization_id,NEW.legal_entity_id)
      AND event.payload=jsonb_build_object('audit_event_id',NEW.audit_event_id,'payment_link_id',NEW.id,
          'supplier_invoice_id',invoice.id,'finance_effect_id',finance_effect.id,'finance_entry_id',finance_effect.entry_id,
          'amount_minor',NEW.amount_minor,'currency_code',NEW.currency_code))
 THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Supplier payment link requires exact AP/cash lines and retained evidence.'; END IF;
 RETURN NEW;
END $payment$;
CREATE TRIGGER ap_payment_link_guard BEFORE INSERT OR UPDATE OR DELETE ON reconforge.ap_payment_links
 FOR EACH ROW EXECUTE FUNCTION reconforge.guard_ap_payment_link();

CREATE OR REPLACE FUNCTION reconforge.guard_ap_supplier_invoice_payment_status()
RETURNS trigger LANGUAGE plpgsql SET search_path=reconforge,pg_catalog AS $payment$
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
  SELECT COALESCE(SUM(amount_minor),0) INTO allocated FROM reconforge.ap_payment_links
    WHERE tenant_id=OLD.tenant_id AND supplier_invoice_id=OLD.id;
  SELECT EXISTS(SELECT 1 FROM reconforge.ap_payment_links link
     WHERE link.tenant_id=OLD.tenant_id AND link.supplier_invoice_id=OLD.id
       AND link.invoice_version_before=OLD.row_version) INTO current_link;
  IF NOT current_link OR NEW.row_version<>OLD.row_version+1
     OR NEW.status<>(CASE WHEN allocated=OLD.total_minor THEN 'Paid' ELSE 'Approved' END)
  THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Approved supplier invoice payment state requires its exact immutable payment link.'; END IF;
 END IF;
 RETURN NEW;
END $payment$;
CREATE TRIGGER ap_supplier_invoice_payment_status_guard BEFORE UPDATE OR DELETE ON reconforge.ap_supplier_invoices
 FOR EACH ROW EXECUTE FUNCTION reconforge.guard_ap_supplier_invoice_payment_status();

CREATE OR REPLACE FUNCTION reconforge.advance_ap_supplier_invoice_payment_link()
RETURNS trigger LANGUAGE plpgsql SET search_path=reconforge,pg_catalog AS $payment$
DECLARE allocated BIGINT;
BEGIN
 SELECT COALESCE(SUM(amount_minor),0) INTO allocated FROM reconforge.ap_payment_links
  WHERE tenant_id=NEW.tenant_id AND supplier_invoice_id=NEW.supplier_invoice_id;
 UPDATE reconforge.ap_supplier_invoices
    SET status=CASE WHEN allocated=total_minor THEN 'Paid' ELSE 'Approved' END,
        updated_at=NEW.created_at,row_version=row_version+1
  WHERE tenant_id=NEW.tenant_id AND id=NEW.supplier_invoice_id
    AND status='Approved' AND row_version=NEW.invoice_version_before;
 IF NOT FOUND THEN
  RAISE EXCEPTION USING ERRCODE='23514',
   MESSAGE='Supplier payment link must atomically advance its invoice state.';
 END IF;
 RETURN NEW;
END $payment$;
CREATE TRIGGER ap_payment_link_invoice_transition AFTER INSERT ON reconforge.ap_payment_links
 FOR EACH ROW EXECUTE FUNCTION reconforge.advance_ap_supplier_invoice_payment_link();

CREATE OR REPLACE FUNCTION reconforge.guard_ap_payment_link_command()
RETURNS trigger LANGUAGE plpgsql SET search_path=reconforge,pg_catalog AS $payment$
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
 SELECT COALESCE(SUM(amount_minor),0) INTO allocated FROM reconforge.ap_payment_links
  WHERE tenant_id=NEW.tenant_id AND supplier_invoice_id=link.supplier_invoice_id
    AND invoice_version_before<=link.invoice_version_before;
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
END $payment$;
CREATE TRIGGER ap_payment_link_command_guard BEFORE INSERT OR UPDATE OR DELETE ON reconforge.ap_payment_link_commands
 FOR EACH ROW EXECUTE FUNCTION reconforge.guard_ap_payment_link_command();

ALTER TABLE reconforge.ap_payment_links ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.ap_payment_links FORCE ROW LEVEL SECURITY;
CREATE POLICY ap_payment_link_scope ON reconforge.ap_payment_links
 USING (tenant_id=current_setting('app.tenant_id',true)
   AND (NULLIF(current_setting('app.workspace_id',true),'') IS NULL OR workspace_id=current_setting('app.workspace_id',true))
   AND (NULLIF(current_setting('app.organization_id',true),'') IS NULL OR organization_id=current_setting('app.organization_id',true))
   AND (NULLIF(current_setting('app.legal_entity_id',true),'') IS NULL OR legal_entity_id=current_setting('app.legal_entity_id',true)))
 WITH CHECK (tenant_id=current_setting('app.tenant_id',true)
   AND (NULLIF(current_setting('app.workspace_id',true),'') IS NULL OR workspace_id=current_setting('app.workspace_id',true))
   AND (NULLIF(current_setting('app.organization_id',true),'') IS NULL OR organization_id=current_setting('app.organization_id',true))
   AND (NULLIF(current_setting('app.legal_entity_id',true),'') IS NULL OR legal_entity_id=current_setting('app.legal_entity_id',true)));
ALTER TABLE reconforge.ap_payment_link_commands ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.ap_payment_link_commands FORCE ROW LEVEL SECURITY;
CREATE POLICY ap_payment_link_command_scope ON reconforge.ap_payment_link_commands
 USING (tenant_id=current_setting('app.tenant_id',true)
   AND (NULLIF(current_setting('app.workspace_id',true),'') IS NULL OR workspace_id=current_setting('app.workspace_id',true))
   AND (NULLIF(current_setting('app.organization_id',true),'') IS NULL OR organization_id=current_setting('app.organization_id',true))
   AND (NULLIF(current_setting('app.legal_entity_id',true),'') IS NULL OR legal_entity_id=current_setting('app.legal_entity_id',true)))
 WITH CHECK (tenant_id=current_setting('app.tenant_id',true)
   AND (NULLIF(current_setting('app.workspace_id',true),'') IS NULL OR workspace_id=current_setting('app.workspace_id',true))
   AND (NULLIF(current_setting('app.organization_id',true),'') IS NULL OR organization_id=current_setting('app.organization_id',true))
   AND (NULLIF(current_setting('app.legal_entity_id',true),'') IS NULL OR legal_entity_id=current_setting('app.legal_entity_id',true)));

INSERT INTO reconforge.identity_permissions(tenant_id,name,description)
 SELECT tenant.id,'payables.settle','Link approved supplier invoices to exact independently posted AP/cash effects.'
 FROM reconforge.tenants tenant ON CONFLICT(tenant_id,name) DO NOTHING;
INSERT INTO reconforge.identity_role_permissions(tenant_id,role_id,permission_name)
 SELECT roles.tenant_id,roles.id,'payables.settle' FROM reconforge.identity_roles roles
 WHERE roles.name IN ('admin','controller') ON CONFLICT DO NOTHING;
CREATE OR REPLACE FUNCTION reconforge.seed_ap_payment_link_permissions()
RETURNS trigger LANGUAGE plpgsql SET search_path=reconforge,pg_catalog AS $payment$
BEGIN
 IF TG_TABLE_NAME='tenants' THEN
  INSERT INTO reconforge.identity_permissions(tenant_id,name,description) VALUES
   (NEW.id,'payables.settle','Link approved supplier invoices to exact independently posted AP/cash effects.')
  ON CONFLICT(tenant_id,name) DO NOTHING;
 ELSIF TG_TABLE_NAME='identity_roles' AND NEW.name IN ('admin','controller') THEN
  INSERT INTO reconforge.identity_role_permissions(tenant_id,role_id,permission_name)
   VALUES(NEW.tenant_id,NEW.id,'payables.settle') ON CONFLICT DO NOTHING;
 END IF;
 RETURN NEW;
END $payment$;
CREATE TRIGGER ap_payment_link_permission_tenant_seed AFTER INSERT ON reconforge.tenants
 FOR EACH ROW EXECUTE FUNCTION reconforge.seed_ap_payment_link_permissions();
CREATE TRIGGER ap_payment_link_permission_role_seed AFTER INSERT ON reconforge.identity_roles
 FOR EACH ROW EXECUTE FUNCTION reconforge.seed_ap_payment_link_permissions();
"""


DOWNGRADE_SQL = r"""
DO $payment$
BEGIN
 IF NOT EXISTS (
   SELECT 1 FROM pg_roles
   WHERE rolname=current_user AND (rolsuper OR rolbypassrls)
 ) THEN
  RAISE EXCEPTION 'payables payment-link migration requires a role that bypasses forced row security';
 END IF;
END $payment$;

DO $payment$
BEGIN
 IF EXISTS(SELECT 1 FROM reconforge.ap_payment_links)
    OR EXISTS(SELECT 1 FROM reconforge.ap_payment_link_commands) THEN
  RAISE EXCEPTION USING ERRCODE='23514',
   MESSAGE='Supplier payment evidence prevents downgrade; restore a verified pre-upgrade backup.';
 END IF;
END $payment$;
DROP TRIGGER ap_payment_link_permission_role_seed ON reconforge.identity_roles;
DROP TRIGGER ap_payment_link_permission_tenant_seed ON reconforge.tenants;
DROP FUNCTION reconforge.seed_ap_payment_link_permissions();
DROP TRIGGER ap_payment_link_command_guard ON reconforge.ap_payment_link_commands;
DROP FUNCTION reconforge.guard_ap_payment_link_command();
DROP TRIGGER ap_payment_link_invoice_transition ON reconforge.ap_payment_links;
DROP FUNCTION reconforge.advance_ap_supplier_invoice_payment_link();
DROP TRIGGER ap_supplier_invoice_payment_status_guard ON reconforge.ap_supplier_invoices;
DROP FUNCTION reconforge.guard_ap_supplier_invoice_payment_status();
DROP TRIGGER ap_payment_link_guard ON reconforge.ap_payment_links;
DROP FUNCTION reconforge.guard_ap_payment_link();
DROP TABLE reconforge.ap_payment_link_commands;
DROP TABLE reconforge.ap_payment_links;
"""


def upgrade() -> None:
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    op.execute(DOWNGRADE_SQL)
