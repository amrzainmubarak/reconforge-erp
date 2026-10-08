"""Bind reviewed native AR/AP sources to atomic immutable manual postings."""

import sqlalchemy as sa

from alembic import op

revision = "0109_pg_operational_finance"
down_revision = "0108_pg_receipt_admission"
branch_labels = None
depends_on = None
UPGRADE_SQL = r"""

DO $preflight$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname=current_user AND (rolsuper OR rolbypassrls)) THEN
 RAISE EXCEPTION 'Operational financial schema installation requires bypass of forced row security.'; END IF;
 IF to_regclass('reconforge.operational_finance_plans') IS NULL AND EXISTS(
 SELECT 1 FROM reconforge.finance_entries WHERE upper(left(entry_number,5))='OPS1-' OR upper(left(id,5))='OPS1-') THEN
 RAISE EXCEPTION 'Operational source namespace already contains historical entries; explicit migration is required.'; END IF;
END $preflight$;
CREATE TABLE IF NOT EXISTS reconforge.operational_finance_plans (
 tenant_id TEXT NOT NULL,id TEXT NOT NULL,workspace_id TEXT NOT NULL,organization_id TEXT NOT NULL,legal_entity_id TEXT NOT NULL,
 source_kind TEXT NOT NULL CHECK(source_kind IN ('ARInvoice','ARReceipt','APInvoice','APPayment')),source_id TEXT NOT NULL,
 entry_id TEXT NOT NULL,entry_number TEXT NOT NULL CHECK(left(entry_number,5)='OPS1-'),
 preparer_actor_id TEXT NOT NULL,amount_minor BIGINT NOT NULL CHECK(amount_minor BETWEEN 1 AND 9000000000000000000),
 currency_code TEXT NOT NULL,currency_precision INTEGER NOT NULL CHECK(currency_precision BETWEEN 0 AND 8),
 plan_digest TEXT NOT NULL CHECK(plan_digest ~ '^[0-9a-f]{64}$'),validation_digest TEXT NOT NULL CHECK(validation_digest ~ '^[0-9a-f]{64}$'),
 payload JSONB NOT NULL CHECK(jsonb_typeof(payload)='object' AND octet_length(payload::text)<=131072),
 audit_event_id TEXT NOT NULL,outbox_event_id TEXT NOT NULL,created_at TEXT NOT NULL,
 PRIMARY KEY(tenant_id,id),UNIQUE(tenant_id,source_kind,source_id),UNIQUE(tenant_id,entry_id),
 UNIQUE(tenant_id,id,workspace_id,organization_id,legal_entity_id),
 FOREIGN KEY(tenant_id,entry_id) REFERENCES reconforge.finance_entries(tenant_id,id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(tenant_id,workspace_id) REFERENCES reconforge.domain_workspaces(tenant_id,id),
 FOREIGN KEY(tenant_id,organization_id) REFERENCES reconforge.organizations(tenant_id,id),
 FOREIGN KEY(tenant_id,legal_entity_id) REFERENCES reconforge.legal_entities(tenant_id,id),
 FOREIGN KEY(tenant_id,preparer_actor_id) REFERENCES reconforge.identity_users(tenant_id,id),
 FOREIGN KEY(tenant_id,audit_event_id) REFERENCES reconforge.domain_audit_events(tenant_id,id),
 FOREIGN KEY(tenant_id,outbox_event_id) REFERENCES reconforge.outbox_events(tenant_id,event_id)
);
CREATE TABLE IF NOT EXISTS reconforge.operational_finance_reviews (
 tenant_id TEXT NOT NULL,plan_id TEXT NOT NULL,reviewer_actor_id TEXT NOT NULL,plan_digest TEXT NOT NULL,
 reason TEXT NOT NULL CHECK(reconforge.irp_text(reason,500)),review_digest TEXT NOT NULL CHECK(review_digest ~ '^[0-9a-f]{64}$'),
 audit_event_id TEXT NOT NULL,outbox_event_id TEXT NOT NULL,created_at TEXT NOT NULL,
 PRIMARY KEY(tenant_id,plan_id),
 FOREIGN KEY(tenant_id,plan_id) REFERENCES reconforge.operational_finance_plans(tenant_id,id),
 FOREIGN KEY(tenant_id,reviewer_actor_id) REFERENCES reconforge.identity_users(tenant_id,id),
 FOREIGN KEY(tenant_id,audit_event_id) REFERENCES reconforge.domain_audit_events(tenant_id,id),
 FOREIGN KEY(tenant_id,outbox_event_id) REFERENCES reconforge.outbox_events(tenant_id,event_id)
);
CREATE TABLE IF NOT EXISTS reconforge.operational_finance_links (
 tenant_id TEXT NOT NULL,plan_id TEXT NOT NULL,posting_effect_id TEXT NOT NULL,source_effect_id TEXT NOT NULL,
 posted_actor_id TEXT NOT NULL,plan_digest TEXT NOT NULL,review_digest TEXT NOT NULL,
 audit_event_id TEXT NOT NULL,outbox_event_id TEXT NOT NULL,created_at TEXT NOT NULL,
 PRIMARY KEY(tenant_id,plan_id),UNIQUE(tenant_id,posting_effect_id),
 FOREIGN KEY(tenant_id,plan_id) REFERENCES reconforge.operational_finance_plans(tenant_id,id),
 FOREIGN KEY(tenant_id,posting_effect_id) REFERENCES reconforge.finance_posting_effects(tenant_id,id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(tenant_id,posted_actor_id) REFERENCES reconforge.identity_users(tenant_id,id),
 FOREIGN KEY(tenant_id,audit_event_id) REFERENCES reconforge.domain_audit_events(tenant_id,id),
 FOREIGN KEY(tenant_id,outbox_event_id) REFERENCES reconforge.outbox_events(tenant_id,event_id)
);
CREATE TABLE IF NOT EXISTS reconforge.operational_finance_commands (
 tenant_id TEXT NOT NULL,workspace_id TEXT NOT NULL,command_id TEXT NOT NULL CHECK(reconforge.irp_text(command_id,140)),operation TEXT NOT NULL CHECK(operation IN ('prepare','review','post')),
 actor_id TEXT NOT NULL,request_digest TEXT NOT NULL CHECK(request_digest ~ '^[0-9a-f]{64}$'),request_json JSONB NOT NULL CHECK(jsonb_typeof(request_json)='object' AND octet_length(request_json::text)<=131072),plan_id TEXT NOT NULL,
 result_json JSONB NOT NULL CHECK(jsonb_typeof(result_json)='object' AND octet_length(result_json::text)<=131072),
 PRIMARY KEY(tenant_id,workspace_id,command_id),
 FOREIGN KEY(tenant_id,plan_id) REFERENCES reconforge.operational_finance_plans(tenant_id,id),
 FOREIGN KEY(tenant_id,actor_id) REFERENCES reconforge.identity_users(tenant_id,id)
);
CREATE INDEX IF NOT EXISTS operational_finance_scope_idx ON reconforge.operational_finance_plans(tenant_id,workspace_id,organization_id,legal_entity_id,created_at,id);

CREATE OR REPLACE FUNCTION reconforge.ops_source(t TEXT,k TEXT,i TEXT) RETURNS JSONB LANGUAGE plpgsql STABLE SET search_path=pg_catalog AS $ops$
DECLARE source JSONB;
BEGIN
 IF k IN ('ARInvoice','ARReceipt') THEN
 SELECT jsonb_build_object('id',h.id,'workspace_id',h.workspace_id,'organization_id',h.organization_id,'legal_entity_id',h.legal_entity_id,
 'party_id',h.customer_id,'number',h.invoice_number,'date',h.invoice_date::text,'currency_code',h.currency_code,'amount_minor',h.total_minor,
 'tax_minor',h.tax_minor,'currency_precision',h.currency_precision,'currency_rounding_policy',h.currency_rounding_policy,
 'currency_registry_version',h.currency_registry_version,'currency_registry_digest',h.currency_registry_digest,
 'created_by',h.created_by,'lines',(SELECT jsonb_agg(jsonb_build_object('id',l.id,'line_number',l.line_number,'description',l.description,
 'quantity',l.quantity_text,'unit_price_minor',l.unit_price_minor,'tax_minor',l.tax_minor,'line_total_minor',l.line_total_minor) ORDER BY l.line_number)
 FROM reconforge.ar_invoice_lines l WHERE l.tenant_id=t AND l.invoice_id=h.id)) INTO source
 FROM reconforge.ar_invoices h WHERE h.tenant_id=t AND h.id=i;
 ELSIF k IN ('APInvoice','APPayment') THEN
 SELECT jsonb_build_object('id',h.id,'workspace_id',h.workspace_id,'organization_id',h.organization_id,'legal_entity_id',h.legal_entity_id,
 'party_id',h.supplier_id,'number',h.invoice_number,'date',h.invoice_date::text,'currency_code',h.currency_code,'amount_minor',h.total_minor,
 'tax_minor',h.tax_minor,'purchase_order_id',h.purchase_order_id,'created_by',h.created_by,
 'lines',(SELECT jsonb_agg(jsonb_build_object('id',l.id,'line_number',l.line_number,'description',l.description,'quantity',l.invoiced_quantity_text,
 'unit_price_minor',l.unit_price_minor,'tax_minor',l.tax_minor,'line_total_minor',l.line_total_minor,'purchase_order_line_id',l.purchase_order_line_id) ORDER BY l.line_number)
 FROM reconforge.ap_supplier_invoice_lines l WHERE l.tenant_id=t AND l.supplier_invoice_id=h.id)) INTO source
 FROM reconforge.ap_supplier_invoices h WHERE h.tenant_id=t AND h.id=i;
 ELSE RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Unsupported operational financial source.'; END IF;
 RETURN source;
END $ops$;
CREATE OR REPLACE FUNCTION reconforge.ops_event(t TEXT,p TEXT,a TEXT,b TEXT,actor TEXT,action TEXT,metadata JSONB) RETURNS BOOLEAN
 LANGUAGE sql STABLE SET search_path=pg_catalog AS $ops$
 SELECT EXISTS(SELECT 1 FROM reconforge.domain_audit_events x JOIN reconforge.outbox_events y ON y.tenant_id=x.tenant_id
 JOIN reconforge.operational_finance_plans z ON z.tenant_id=x.tenant_id AND z.id=p
 WHERE x.tenant_id=t AND x.id=a AND y.event_id=b AND x.actor_user_id=actor AND x.object_type='operational_finance' AND x.object_id=p
 AND x.action=$6 AND x.metadata_json=$7 AND y.event_type=$6 AND y.aggregate_type='operational_finance' AND y.aggregate_id=p
 AND y.payload=$7||jsonb_build_object('audit_event_id',a) AND (y.workspace_id,y.organization_id,y.legal_entity_id)=(z.workspace_id,z.organization_id,z.legal_entity_id))
$ops$;
CREATE OR REPLACE FUNCTION reconforge.ops_close_plan(t TEXT,i TEXT) RETURNS VOID LANGUAGE plpgsql SET search_path=pg_catalog AS $ops$
DECLARE p RECORD;e RECORD;r RECORD;f RECORD;l RECORD;s JSONB;lines JSONB;header JSONB;reference TEXT;status TEXT;debit_kind TEXT;credit_kind TEXT;
BEGIN
 SELECT * INTO p FROM reconforge.operational_finance_plans WHERE tenant_id=t AND id=i;
 IF p IS NULL THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='OPS1 requires a retained source plan.'; END IF;
 SELECT * INTO e FROM reconforge.finance_entries WHERE tenant_id=t AND id=p.entry_id;
 s:=reconforge.ops_source(t,p.source_kind,p.source_id);
 IF e IS NULL OR s IS NULL OR p.payload->'source_snapshot' IS DISTINCT FROM s OR reconforge.irp_digest(p.payload) IS DISTINCT FROM p.plan_digest
 OR p.payload->>'id' IS DISTINCT FROM p.id OR p.payload->>'entry_id' IS DISTINCT FROM p.entry_id
 OR p.payload->>'source_kind' IS DISTINCT FROM p.source_kind OR p.payload->>'source_id' IS DISTINCT FROM p.source_id
 OR p.payload->>'preparer_actor_id' IS DISTINCT FROM p.preparer_actor_id OR (s->>'amount_minor')::bigint IS DISTINCT FROM p.amount_minor
 OR p.id IS DISTINCT FROM 'OPS1-'||left(reconforge.irp_digest(jsonb_build_array(p.workspace_id,p.source_kind,p.source_id)),32)
 OR p.entry_number IS DISTINCT FROM upper(p.id)
 OR (s->>'tax_minor')::bigint<>0 OR (s->>'workspace_id',s->>'organization_id',s->>'legal_entity_id') IS DISTINCT FROM (p.workspace_id,p.organization_id,p.legal_entity_id)
 OR (e.workspace_id,e.entry_number,e.preparer_actor_id,e.total_debit_minor,e.total_credit_minor,e.currency_code,e.currency_precision)
 IS DISTINCT FROM (p.workspace_id,p.entry_number,p.preparer_actor_id,p.amount_minor,p.amount_minor,p.currency_code,p.currency_precision)
 OR e.source_type<>'Manual' OR e.reverses_posting_id IS NOT NULL THEN
 RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Operational source must retain exact native money, scope, provenance and plan.'; END IF;
 IF NOT EXISTS(SELECT 1 FROM reconforge.organizations o JOIN reconforge.legal_entities x ON x.tenant_id=o.tenant_id AND x.organization_id=o.id
 WHERE o.tenant_id=t AND o.id=p.organization_id AND x.id=p.legal_entity_id AND o.application_workspace_id=p.workspace_id
 AND e.organization_code=o.organization_code AND e.entity_code=x.entity_code AND x.currency_code=p.currency_code) THEN
 RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Operational GL and native source canonical entity differ.'; END IF;
 IF p.source_kind IN ('ARInvoice','ARReceipt') THEN SELECT h.status INTO status FROM reconforge.ar_invoices h WHERE h.tenant_id=t AND h.id=p.source_id;
 ELSE SELECT h.status INTO status FROM reconforge.ap_supplier_invoices h WHERE h.tenant_id=t AND h.id=p.source_id; END IF;
 IF (p.source_kind IN ('ARInvoice','ARReceipt') AND status NOT IN ('Submitted','Approved','PartiallyPaid','Paid'))
 OR (p.source_kind IN ('APInvoice','APPayment') AND status NOT IN ('Approved','Paid')) THEN
 RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Operational source cannot discard approved native history.'; END IF;
 reference:=CASE WHEN p.source_kind='APPayment' THEN 'AP-PAYMENT:'||p.source_id ELSE p.id END;
 IF e.external_reference<>reference THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Operational reference must identify its exact source.'; END IF;
 SELECT jsonb_object_agg(key,value) INTO header FROM jsonb_each(to_jsonb(e)) WHERE key=ANY(ARRAY['id','workspace_id','journal_id','period_id','entry_number','posting_date','description','external_reference','source_type','currency_code',
 'currency_precision','currency_rounding_policy','currency_registry_version','currency_registry_digest','preparer_actor_id','reverses_posting_id']);
 header:=header||jsonb_build_object('organization_id',p.organization_id,'legal_entity_id',p.legal_entity_id);
 SELECT jsonb_agg(jsonb_build_object('line_number',x.line_number,'account_id',x.account_id,'description',x.description,'debit_minor',x.debit_minor,'credit_minor',x.credit_minor,
 'dimensions',COALESCE((SELECT jsonb_object_agg(d.dimension_id,d.dimension_value_id) FROM reconforge.finance_entry_line_dimensions d WHERE d.tenant_id=t AND d.entry_line_id=x.id),'{}'::jsonb)) ORDER BY x.line_number)
 INTO lines FROM reconforge.finance_entry_lines x WHERE x.tenant_id=t AND x.entry_id=e.id;
 IF p.payload->'snapshot' IS DISTINCT FROM jsonb_build_object('schema_version','finance-entry-review-v1','entry',header,'lines',lines)
 OR reconforge.irp_digest(p.payload->'snapshot') IS DISTINCT FROM p.validation_digest OR jsonb_array_length(lines)<>2
 OR NOT reconforge.ops_event(t,p.id,p.audit_event_id,p.outbox_event_id,p.preparer_actor_id,'operational_finance_prepared',jsonb_build_object('plan_digest',p.plan_digest,'validation_digest',p.validation_digest)) THEN
 RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Operational plan snapshot and preparation evidence differ.'; END IF;
 IF NOT EXISTS(SELECT 1 FROM reconforge.operational_finance_commands c WHERE c.tenant_id=t AND c.plan_id=p.id AND c.operation='prepare' AND c.actor_id=p.preparer_actor_id) THEN
 RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Operational preparation requires its actual command acknowledgement.'; END IF;
 SELECT a.account_type INTO debit_kind FROM reconforge.finance_accounts a WHERE a.tenant_id=t AND a.id=lines->0->>'account_id';
 SELECT a.account_type INTO credit_kind FROM reconforge.finance_accounts a WHERE a.tenant_id=t AND a.id=lines->1->>'account_id';
 IF (lines->0->>'debit_minor')::bigint<>p.amount_minor OR (lines->0->>'credit_minor')::bigint<>0
 OR (lines->1->>'credit_minor')::bigint<>p.amount_minor OR (lines->1->>'debit_minor')::bigint<>0
 OR (p.source_kind='ARInvoice' AND (debit_kind,credit_kind) IS DISTINCT FROM ('Asset','Income'))
 OR (p.source_kind='ARReceipt' AND (debit_kind,credit_kind) IS DISTINCT FROM ('Asset','Asset'))
 OR (p.source_kind='APInvoice' AND (debit_kind,credit_kind) IS DISTINCT FROM ('Liability','Liability'))
 OR (p.source_kind='APPayment' AND (debit_kind,credit_kind) IS DISTINCT FROM ('Liability','Asset')) THEN
 RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Operational source requires its closed debit and credit account roles.'; END IF;
 SELECT * INTO r FROM reconforge.operational_finance_reviews WHERE tenant_id=t AND plan_id=p.id;
 IF r IS NOT NULL THEN
 IF r.reviewer_actor_id=p.preparer_actor_id OR r.plan_digest<>p.plan_digest OR e.validator_actor_id IS DISTINCT FROM r.reviewer_actor_id OR e.validation_digest IS DISTINCT FROM p.validation_digest
 OR r.review_digest<>reconforge.irp_digest(jsonb_build_object('plan_id',p.id,'plan_digest',p.plan_digest,'reviewer_actor_id',r.reviewer_actor_id,'reason',r.reason))
 OR NOT reconforge.ops_event(t,p.id,r.audit_event_id,r.outbox_event_id,r.reviewer_actor_id,'operational_finance_reviewed',jsonb_build_object('plan_digest',p.plan_digest,'review_digest',r.review_digest)) THEN
 RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Operational source requires exact independent review.'; END IF;
 IF NOT EXISTS(SELECT 1 FROM reconforge.operational_finance_commands c WHERE c.tenant_id=t AND c.plan_id=p.id AND c.operation='review' AND c.actor_id=r.reviewer_actor_id) THEN
 RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Operational review requires its actual command acknowledgement.'; END IF;
 ELSIF e.status<>'Draft' THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Operational validation requires its retained source review.'; END IF;
 SELECT * INTO f FROM reconforge.finance_posting_effects WHERE tenant_id=t AND entry_id=e.id;
 SELECT * INTO l FROM reconforge.operational_finance_links WHERE tenant_id=t AND plan_id=p.id;
 IF (f IS NULL)<>(l IS NULL) THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Operational financial effect and native source must commit together.'; END IF;
 IF l IS NULL AND ((p.source_kind='ARReceipt' AND EXISTS(SELECT 1 FROM reconforge.ar_receipt_allocations a JOIN reconforge.ar_receipts h ON h.tenant_id=a.tenant_id AND h.id=a.receipt_id
 WHERE a.tenant_id=t AND a.invoice_id=p.source_id AND h.status='Posted'))
 OR (p.source_kind='APPayment' AND EXISTS(SELECT 1 FROM reconforge.ap_payment_links a WHERE a.tenant_id=t AND a.supplier_invoice_id=p.source_id))) THEN
 RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Native settlement cannot commit without its reviewed operational GL.'; END IF;
 IF l IS NOT NULL THEN
 IF r IS NULL OR l.posting_effect_id<>f.id OR l.plan_digest<>p.plan_digest OR l.review_digest<>r.review_digest
 OR f.posted_actor_id<>l.posted_actor_id OR l.posted_actor_id=p.preparer_actor_id OR f.source_kind<>'Manual' OR f.source_id<>e.id
 OR f.snapshot_json<>p.payload->'snapshot' OR f.validation_digest<>p.validation_digest OR f.reverses_effect_id IS NOT NULL
 OR NOT reconforge.ops_event(t,p.id,l.audit_event_id,l.outbox_event_id,l.posted_actor_id,'operational_finance_posted',jsonb_build_object('plan_digest',p.plan_digest,'review_digest',r.review_digest,'posting_effect_id',f.id,'source_effect_id',l.source_effect_id)) THEN
 RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Operational posting must close its immutable source and finance evidence.'; END IF;
 IF NOT EXISTS(SELECT 1 FROM reconforge.operational_finance_commands c WHERE c.tenant_id=t AND c.plan_id=p.id AND c.operation='post' AND c.actor_id=l.posted_actor_id) THEN
 RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Operational posting requires its actual command acknowledgement.'; END IF;
 IF p.source_kind IN ('ARInvoice','ARReceipt') THEN SELECT h.status INTO status FROM reconforge.ar_invoices h WHERE h.tenant_id=t AND h.id=p.source_id;
 ELSE SELECT h.status INTO status FROM reconforge.ap_supplier_invoices h WHERE h.tenant_id=t AND h.id=p.source_id; END IF;
 IF p.source_kind='ARInvoice' AND (status NOT IN ('Approved','PartiallyPaid','Paid') OR l.source_effect_id<>p.source_id) THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Revenue requires a real approved receivable.'; END IF;
 IF p.source_kind='APInvoice' AND (status NOT IN ('Approved','Paid') OR l.source_effect_id<>p.source_id) THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Accrual requires a real approved payable.'; END IF;
 IF p.source_kind='ARReceipt' AND NOT EXISTS(SELECT 1 FROM reconforge.ar_receipts h JOIN reconforge.ar_receipt_allocations a ON a.tenant_id=h.tenant_id AND a.receipt_id=h.id
 WHERE h.tenant_id=t AND h.id=l.source_effect_id AND h.status='Posted' AND a.invoice_id=p.source_id AND a.amount_minor=p.amount_minor
 AND h.amount_minor=p.amount_minor AND h.currency_code=p.currency_code AND h.customer_id=s->>'party_id'
 AND (h.workspace_id,h.organization_id,h.legal_entity_id)=(p.workspace_id,p.organization_id,p.legal_entity_id)
 AND (SELECT count(*) FROM reconforge.ar_receipt_allocations z WHERE z.tenant_id=t AND z.receipt_id=h.id)=1) THEN
 RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Collection requires its exact posted receipt and one invoice allocation.'; END IF;
 IF p.source_kind='ARReceipt' AND (SELECT COALESCE(sum(a.amount_minor),0) FROM reconforge.ar_receipt_allocations a JOIN reconforge.ar_receipts h ON h.tenant_id=a.tenant_id AND h.id=a.receipt_id
 WHERE a.tenant_id=t AND a.invoice_id=p.source_id AND h.status='Posted')<>p.amount_minor THEN
 RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Full collection cannot retain duplicate or excess native allocations.'; END IF;
 IF p.source_kind='APPayment' AND NOT EXISTS(SELECT 1 FROM reconforge.ap_payment_links a WHERE a.tenant_id=t AND a.supplier_invoice_id=p.source_id
 AND a.finance_effect_id=f.id AND a.amount_minor=p.amount_minor AND a.currency_code=p.currency_code AND l.source_effect_id=f.id
 AND (a.workspace_id,a.organization_id,a.legal_entity_id)=(p.workspace_id,p.organization_id,p.legal_entity_id)) THEN
 RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Payment requires its exact native AP settlement link.'; END IF;
 END IF;
END $ops$;
CREATE OR REPLACE FUNCTION reconforge.ops_close_trigger() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $ops$
DECLARE identifier TEXT;row_data JSONB:=CASE WHEN TG_OP='DELETE' THEN to_jsonb(OLD) ELSE to_jsonb(NEW) END;prior JSONB:=CASE WHEN TG_OP='INSERT' THEN '{}'::jsonb ELSE to_jsonb(OLD) END;candidate RECORD;
BEGIN
 IF TG_TABLE_NAME='operational_finance_plans' THEN identifier:=row_data->>'id';
 ELSIF TG_TABLE_NAME IN ('operational_finance_reviews','operational_finance_links','operational_finance_commands') THEN identifier:=row_data->>'plan_id';
 ELSIF TG_TABLE_NAME='finance_entries' THEN
 FOR candidate IN SELECT id FROM reconforge.operational_finance_plans WHERE tenant_id=row_data->>'tenant_id' AND entry_id IN (row_data->>'id',prior->>'id') LOOP
 PERFORM reconforge.ops_close_plan(row_data->>'tenant_id',candidate.id); identifier:=candidate.id;
 END LOOP;
 IF identifier IS NOT NULL THEN RETURN NEW; END IF;
 IF upper(left(row_data->>'entry_number',5))<>'OPS1-' AND upper(left(row_data->>'id',5))<>'OPS1-' AND COALESCE(upper(left(prior->>'entry_number',5)),'')<>'OPS1-' AND COALESCE(upper(left(prior->>'id',5)),'')<>'OPS1-' THEN RETURN NEW; END IF;
 ELSIF TG_TABLE_NAME='finance_posting_effects' THEN SELECT id INTO identifier FROM reconforge.operational_finance_plans WHERE tenant_id=row_data->>'tenant_id' AND entry_id=row_data->>'entry_id';
 IF identifier IS NULL AND NOT EXISTS(SELECT 1 FROM reconforge.finance_entries WHERE tenant_id=row_data->>'tenant_id' AND id=row_data->>'entry_id' AND (upper(left(entry_number,5))='OPS1-' OR upper(left(id,5))='OPS1-')) THEN RETURN NEW; END IF;
 ELSIF TG_TABLE_NAME IN ('finance_entry_lines','finance_entry_line_dimensions') THEN
 IF TG_TABLE_NAME='finance_entry_lines' THEN
 FOR candidate IN SELECT id FROM reconforge.operational_finance_plans WHERE tenant_id=row_data->>'tenant_id' AND entry_id IN (row_data->>'entry_id',prior->>'entry_id') LOOP
 PERFORM reconforge.ops_close_plan(row_data->>'tenant_id',candidate.id);
 END LOOP;
 ELSE
 FOR candidate IN SELECT p.id FROM reconforge.operational_finance_plans p JOIN reconforge.finance_entry_lines x ON x.tenant_id=p.tenant_id AND x.entry_id=p.entry_id WHERE x.tenant_id=row_data->>'tenant_id' AND x.id IN (row_data->>'entry_line_id',prior->>'entry_line_id') LOOP
 PERFORM reconforge.ops_close_plan(row_data->>'tenant_id',candidate.id);
 END LOOP;
 END IF;
 RETURN NEW;
 END IF;
 IF identifier IS NULL THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='OPS1 namespace has no source owner.'; END IF;
 PERFORM reconforge.ops_close_plan(row_data->>'tenant_id',identifier); RETURN NEW;
END $ops$;
CREATE OR REPLACE FUNCTION reconforge.ops_guard_command() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $ops$
DECLARE p RECORD;r RECORD;l RECORD;expected JSONB;
BEGIN
 SELECT * INTO p FROM reconforge.operational_finance_plans WHERE tenant_id=NEW.tenant_id AND id=NEW.plan_id;
 SELECT * INTO r FROM reconforge.operational_finance_reviews WHERE tenant_id=NEW.tenant_id AND plan_id=NEW.plan_id;
 SELECT * INTO l FROM reconforge.operational_finance_links WHERE tenant_id=NEW.tenant_id AND plan_id=NEW.plan_id;
 IF p IS NULL OR NEW.workspace_id<>p.workspace_id OR NEW.request_digest<>reconforge.irp_digest(NEW.request_json)
 OR NEW.request_json->>'operation' IS DISTINCT FROM NEW.operation OR NEW.request_json->>'actor_id' IS DISTINCT FROM NEW.actor_id
 OR NOT EXISTS(SELECT 1 FROM reconforge.identity_users WHERE tenant_id=NEW.tenant_id AND id=NEW.actor_id AND NOT disabled)
 OR NOT reconforge.irp_scope(NEW.tenant_id,p.workspace_id,p.organization_id,p.legal_entity_id) THEN
 RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Operational command requires exact current actor, scope and digest.'; END IF;
 expected:=p.payload||jsonb_build_object('plan_digest',p.plan_digest,'validation_digest',p.validation_digest,
 'status',CASE WHEN l IS NOT NULL THEN 'Posted' WHEN r IS NOT NULL THEN 'Reviewed' ELSE 'Draft' END,
 'reviewer_actor_id',r.reviewer_actor_id,'review_digest',r.review_digest,'posting_effect_id',l.posting_effect_id,'source_effect_id',l.source_effect_id);
 IF NEW.result_json IS DISTINCT FROM expected OR
 (NEW.operation='prepare' AND (NEW.actor_id<>p.preparer_actor_id OR r IS NOT NULL OR l IS NOT NULL OR NOT (p.payload @> (NEW.request_json->'request')))) OR
 (NEW.operation='review' AND (r IS NULL OR NEW.actor_id<>r.reviewer_actor_id OR l IS NOT NULL OR NEW.request_json->'request'->>'reason' IS DISTINCT FROM r.reason)) OR
 (NEW.operation='post' AND (l IS NULL OR NEW.actor_id<>l.posted_actor_id)) OR
 (NEW.operation IN ('review','post') AND (NEW.request_json->'request'->>'plan_id' IS DISTINCT FROM p.id OR NEW.request_json->'request'->>'expected_plan_digest' IS DISTINCT FROM p.plan_digest)) THEN
 RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Operational command acknowledgement must match its actual source phase.'; END IF;
 IF (NEW.operation='review' AND (SELECT array_agg(key ORDER BY key) FROM jsonb_object_keys(NEW.request_json->'request') x(key)) IS DISTINCT FROM ARRAY['expected_plan_digest','plan_id','reason'])
 OR (NEW.operation='post' AND (SELECT array_agg(key ORDER BY key) FROM jsonb_object_keys(NEW.request_json->'request') x(key)) IS DISTINCT FROM ARRAY['expected_plan_digest','plan_id','reason','source_effect_id'])
 OR (NEW.operation='post' AND NOT EXISTS(SELECT 1 FROM reconforge.finance_posting_effects f WHERE f.tenant_id=NEW.tenant_id AND f.id=l.posting_effect_id
 AND f.reason=NEW.request_json->'request'->>'reason' AND f.posted_actor_id=NEW.actor_id))
 OR (NEW.operation='post' AND ((p.source_kind='ARReceipt' AND NEW.request_json->'request'->>'source_effect_id' IS DISTINCT FROM l.source_effect_id)
 OR (p.source_kind<>'ARReceipt' AND NEW.request_json->'request'->>'source_effect_id' IS NOT NULL))) THEN
 RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Operational command reason and native effect must match its posting.'; END IF;
 RETURN NEW;
END $ops$;
DROP TRIGGER IF EXISTS operational_command_guard ON reconforge.operational_finance_commands;
CREATE TRIGGER operational_command_guard BEFORE INSERT ON reconforge.operational_finance_commands FOR EACH ROW EXECUTE FUNCTION reconforge.ops_guard_command();
CREATE OR REPLACE FUNCTION reconforge.ops_close_native() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $ops$
DECLARE data JSONB;prior JSONB;identifier TEXT;old_identifier TEXT;p RECORD;
BEGIN
 data:=CASE WHEN TG_OP='DELETE' THEN to_jsonb(OLD) ELSE to_jsonb(NEW) END;
 prior:=CASE WHEN TG_OP='INSERT' THEN '{}'::jsonb ELSE to_jsonb(OLD) END;
 identifier:=CASE WHEN TG_TABLE_NAME='ar_invoice_lines' THEN data->>'invoice_id' WHEN TG_TABLE_NAME='ap_supplier_invoice_lines' THEN data->>'supplier_invoice_id'
 WHEN TG_TABLE_NAME='ar_receipt_allocations' THEN data->>'invoice_id' WHEN TG_TABLE_NAME='ap_payment_links' THEN data->>'supplier_invoice_id' ELSE data->>'id' END;
 old_identifier:=CASE WHEN TG_TABLE_NAME='ar_invoice_lines' THEN prior->>'invoice_id' WHEN TG_TABLE_NAME='ap_supplier_invoice_lines' THEN prior->>'supplier_invoice_id'
 WHEN TG_TABLE_NAME='ar_receipt_allocations' THEN prior->>'invoice_id' WHEN TG_TABLE_NAME='ap_payment_links' THEN prior->>'supplier_invoice_id' ELSE prior->>'id' END;
 FOR p IN SELECT id FROM reconforge.operational_finance_plans WHERE tenant_id=data->>'tenant_id' AND
 ((source_id IN (identifier,old_identifier) AND ((TG_TABLE_NAME LIKE 'ar_%' AND source_kind IN ('ARInvoice','ARReceipt')) OR (TG_TABLE_NAME LIKE 'ap_%' AND source_kind IN ('APInvoice','APPayment'))))
 OR (TG_TABLE_NAME='ar_receipts' AND EXISTS(SELECT 1 FROM reconforge.operational_finance_links l WHERE l.tenant_id=data->>'tenant_id' AND l.plan_id=operational_finance_plans.id AND l.source_effect_id IN (identifier,old_identifier)))) LOOP
 PERFORM reconforge.ops_close_plan(data->>'tenant_id',p.id);
 END LOOP;
 RETURN NULL;
END $ops$;
CREATE OR REPLACE FUNCTION reconforge.ops_no_mutation() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $ops$
BEGIN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Operational financial evidence is immutable.'; END $ops$;
DO $install$ DECLARE name TEXT;
BEGIN
 FOREACH name IN ARRAY ARRAY['operational_finance_plans','operational_finance_reviews','operational_finance_links','operational_finance_commands'] LOOP
 EXECUTE format('ALTER TABLE reconforge.%I ENABLE ROW LEVEL SECURITY',name); EXECUTE format('ALTER TABLE reconforge.%I FORCE ROW LEVEL SECURITY',name);
 EXECUTE format('DROP POLICY IF EXISTS operational_scope ON reconforge.%I',name);
 IF name='operational_finance_plans' THEN
 EXECUTE format('CREATE POLICY operational_scope ON reconforge.%I USING (reconforge.irp_scope(tenant_id,workspace_id,organization_id,legal_entity_id)) WITH CHECK (reconforge.irp_scope(tenant_id,workspace_id,organization_id,legal_entity_id))',name);
 ELSE EXECUTE format('CREATE POLICY operational_scope ON reconforge.%I USING (EXISTS(SELECT 1 FROM reconforge.operational_finance_plans p WHERE p.tenant_id=%I.tenant_id AND p.id=%I.plan_id))',name,name,name); END IF;
 EXECUTE format('DROP TRIGGER IF EXISTS operational_immutable ON reconforge.%I',name);
 EXECUTE format('CREATE TRIGGER operational_immutable BEFORE UPDATE OR DELETE ON reconforge.%I FOR EACH ROW EXECUTE FUNCTION reconforge.ops_no_mutation()',name);
 END LOOP;
 FOREACH name IN ARRAY ARRAY['operational_finance_plans','operational_finance_reviews','operational_finance_links','operational_finance_commands','finance_entries','finance_entry_lines','finance_entry_line_dimensions','finance_posting_effects'] LOOP
 EXECUTE format('DROP TRIGGER IF EXISTS operational_closure ON reconforge.%I',name);
 EXECUTE format('CREATE CONSTRAINT TRIGGER operational_closure AFTER INSERT OR UPDATE OR DELETE ON reconforge.%I DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION reconforge.ops_close_trigger()',name);
 END LOOP;
 FOREACH name IN ARRAY ARRAY['ar_invoices','ar_invoice_lines','ar_receipts','ar_receipt_allocations','ap_supplier_invoices','ap_supplier_invoice_lines','ap_payment_links'] LOOP
 EXECUTE format('DROP TRIGGER IF EXISTS operational_native_closure ON reconforge.%I',name);
 EXECUTE format('CREATE CONSTRAINT TRIGGER operational_native_closure AFTER INSERT OR UPDATE OR DELETE ON reconforge.%I DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION reconforge.ops_close_native()',name);
 END LOOP;
END $install$;

"""


def upgrade() -> None:
    op.get_bind().execute(sa.text(UPGRADE_SQL))


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text("""DO $guard$ BEGIN
     IF EXISTS(SELECT 1 FROM reconforge.operational_finance_plans) THEN
      RAISE EXCEPTION 'Operational source history cannot be discarded; use forward recovery.';
     END IF;
     END $guard$;""")
    )
    for table in ("finance_entries", "finance_entry_lines", "finance_entry_line_dimensions", "finance_posting_effects"):
        connection.execute(sa.text(f"DROP TRIGGER IF EXISTS operational_closure ON reconforge.{table}"))
    for table in (
        "ar_invoices",
        "ar_invoice_lines",
        "ar_receipts",
        "ar_receipt_allocations",
        "ap_supplier_invoices",
        "ap_supplier_invoice_lines",
        "ap_payment_links",
    ):
        connection.execute(sa.text(f"DROP TRIGGER IF EXISTS operational_native_closure ON reconforge.{table}"))
    for table in (
        "operational_finance_commands",
        "operational_finance_links",
        "operational_finance_reviews",
        "operational_finance_plans",
    ):
        connection.execute(sa.text(f"DROP TABLE reconforge.{table}"))
    connection.execute(
        sa.text(
            "DROP FUNCTION reconforge.ops_close_trigger(), reconforge.ops_no_mutation(), reconforge.ops_close_plan(TEXT,TEXT), reconforge.ops_event(TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,JSONB), reconforge.ops_source(TEXT,TEXT,TEXT), reconforge.ops_guard_command(), reconforge.ops_close_native()"
        )
    )
