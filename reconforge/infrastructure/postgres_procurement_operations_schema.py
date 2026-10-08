"""Forced-RLS purchase cycle ownership and exact existing-engine closure."""
from typing import Any

_AUTHORITY_SQL = r"""
DO $$ BEGIN IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname=current_user AND (rolsuper OR rolbypassrls)) THEN
 RAISE EXCEPTION 'Procurement schema migration requires bypass of forced row security.'; END IF; END $$;
"""

UPGRADE_SQL = r"""
CREATE TABLE reconforge.procurement_cycles (
 tenant_id TEXT NOT NULL,id TEXT NOT NULL,workspace_id TEXT NOT NULL,organization_id TEXT NOT NULL,legal_entity_id TEXT NOT NULL,
 number TEXT NOT NULL,request_json JSONB NOT NULL CHECK(octet_length(request_json::text)<=16384),
 total_minor BIGINT NOT NULL CHECK(total_minor BETWEEN 1 AND 9000000000000000000),
 stage INTEGER NOT NULL DEFAULT 0 CHECK(stage BETWEEN 0 AND 13),row_version BIGINT NOT NULL DEFAULT 1 CHECK(row_version>0),
 purchase_order_id TEXT NOT NULL,receipt_plan_id TEXT,goods_receipt_id TEXT,invoice_id TEXT,
 accrual_plan_id TEXT,payment_plan_id TEXT,accrual_effect_id TEXT,payment_effect_id TEXT,payment_link_id TEXT,
 creator_actor_id TEXT NOT NULL,created_at TIMESTAMPTZ NOT NULL DEFAULT now(),updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 PRIMARY KEY(tenant_id,id),UNIQUE(tenant_id,workspace_id,number),UNIQUE(tenant_id,purchase_order_id),
 UNIQUE(tenant_id,receipt_plan_id),UNIQUE(tenant_id,goods_receipt_id),UNIQUE(tenant_id,invoice_id),
 UNIQUE(tenant_id,accrual_effect_id),UNIQUE(tenant_id,payment_effect_id),UNIQUE(tenant_id,payment_link_id),
 FOREIGN KEY(tenant_id,workspace_id) REFERENCES reconforge.domain_workspaces(tenant_id,id),
 FOREIGN KEY(tenant_id,organization_id) REFERENCES reconforge.organizations(tenant_id,id),
 FOREIGN KEY(tenant_id,legal_entity_id) REFERENCES reconforge.legal_entities(tenant_id,id),
 FOREIGN KEY(tenant_id,purchase_order_id) REFERENCES reconforge.ap_purchase_orders(tenant_id,id),
 FOREIGN KEY(tenant_id,receipt_plan_id) REFERENCES reconforge.inventory_receipt_plans(tenant_id,id),
 FOREIGN KEY(tenant_id,accrual_plan_id,workspace_id,organization_id,legal_entity_id) REFERENCES reconforge.operational_finance_plans(tenant_id,id,workspace_id,organization_id,legal_entity_id),
 FOREIGN KEY(tenant_id,payment_plan_id,workspace_id,organization_id,legal_entity_id) REFERENCES reconforge.operational_finance_plans(tenant_id,id,workspace_id,organization_id,legal_entity_id),
 FOREIGN KEY(tenant_id,goods_receipt_id) REFERENCES reconforge.ap_goods_receipts(tenant_id,id),
 FOREIGN KEY(tenant_id,invoice_id) REFERENCES reconforge.ap_supplier_invoices(tenant_id,id),
 FOREIGN KEY(tenant_id,accrual_effect_id) REFERENCES reconforge.finance_posting_effects(tenant_id,id),
 FOREIGN KEY(tenant_id,payment_effect_id) REFERENCES reconforge.finance_posting_effects(tenant_id,id),
 FOREIGN KEY(tenant_id,payment_link_id) REFERENCES reconforge.ap_payment_links(tenant_id,id),
 FOREIGN KEY(tenant_id,creator_actor_id) REFERENCES reconforge.identity_users(tenant_id,id)
);
CREATE TABLE reconforge.procurement_commands (
 tenant_id TEXT NOT NULL,workspace_id TEXT NOT NULL,command_id TEXT NOT NULL CHECK(length(command_id) BETWEEN 1 AND 160),
 cycle_id TEXT NOT NULL,actor_id TEXT NOT NULL,operation TEXT NOT NULL,request_json JSONB NOT NULL,request_digest TEXT NOT NULL CHECK(request_digest~'^[0-9a-f]{64}$'),
 cycle_version BIGINT NOT NULL CHECK(cycle_version>0),
 response_json JSONB NOT NULL CHECK(octet_length(response_json::text)<=131072),audit_event_id TEXT NOT NULL,outbox_event_id TEXT NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(),PRIMARY KEY(tenant_id,workspace_id,command_id),UNIQUE(tenant_id,cycle_id,cycle_version),
 FOREIGN KEY(tenant_id,cycle_id) REFERENCES reconforge.procurement_cycles(tenant_id,id),
 FOREIGN KEY(tenant_id,actor_id) REFERENCES reconforge.identity_users(tenant_id,id),
 FOREIGN KEY(tenant_id,audit_event_id) REFERENCES reconforge.domain_audit_events(tenant_id,id),
 FOREIGN KEY(tenant_id,outbox_event_id) REFERENCES reconforge.outbox_events(tenant_id,event_id)
);
CREATE INDEX procurement_cycle_scope_idx ON reconforge.procurement_cycles(tenant_id,workspace_id,organization_id,legal_entity_id,created_at DESC,id);
ALTER TABLE reconforge.procurement_cycles ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.procurement_cycles FORCE ROW LEVEL SECURITY;
CREATE POLICY procurement_cycles_scope ON reconforge.procurement_cycles USING (
 tenant_id=current_setting('app.tenant_id',true) AND
 (NULLIF(current_setting('app.workspace_id',true),'') IS NULL OR workspace_id=current_setting('app.workspace_id',true)) AND
 (NULLIF(current_setting('app.organization_id',true),'') IS NULL OR organization_id=current_setting('app.organization_id',true)) AND
 (NULLIF(current_setting('app.legal_entity_id',true),'') IS NULL OR legal_entity_id=current_setting('app.legal_entity_id',true)))
 WITH CHECK(tenant_id=current_setting('app.tenant_id',true) AND
 (NULLIF(current_setting('app.workspace_id',true),'') IS NULL OR workspace_id=current_setting('app.workspace_id',true)) AND
 (NULLIF(current_setting('app.organization_id',true),'') IS NULL OR organization_id=current_setting('app.organization_id',true)) AND
 (NULLIF(current_setting('app.legal_entity_id',true),'') IS NULL OR legal_entity_id=current_setting('app.legal_entity_id',true)));
ALTER TABLE reconforge.procurement_commands ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.procurement_commands FORCE ROW LEVEL SECURITY;
CREATE POLICY procurement_commands_scope ON reconforge.procurement_commands USING (
 tenant_id=current_setting('app.tenant_id',true) AND EXISTS(SELECT 1 FROM reconforge.procurement_cycles c WHERE c.tenant_id=procurement_commands.tenant_id AND c.id=cycle_id))
 WITH CHECK(tenant_id=current_setting('app.tenant_id',true) AND EXISTS(SELECT 1 FROM reconforge.procurement_cycles c WHERE c.tenant_id=procurement_commands.tenant_id AND c.id=cycle_id));
CREATE FUNCTION reconforge.procurement_immutable_command() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Procurement command evidence is append-only.'; END $$;
CREATE TRIGGER procurement_commands_immutable BEFORE UPDATE OR DELETE ON reconforge.procurement_commands FOR EACH ROW EXECUTE FUNCTION reconforge.procurement_immutable_command();
CREATE FUNCTION reconforge.procurement_actor_id(t TEXT,label TEXT) RETURNS TEXT LANGUAGE plpgsql STABLE SET search_path=pg_catalog AS $$
DECLARE identifier TEXT;matches INTEGER;
BEGIN
 SELECT count(*),min(id) INTO matches,identifier FROM reconforge.identity_users
 WHERE tenant_id=t AND (id=label OR lower(username)=lower(label));
 IF matches<>1 THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Procurement historical actor identity is absent or ambiguous.'; END IF;
 RETURN identifier;
END $$;
CREATE FUNCTION reconforge.procurement_verify_approval_commands(c reconforge.procurement_cycles) RETURNS VOID
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE p reconforge.ap_purchase_orders%ROWTYPE;i reconforge.ap_supplier_invoices%ROWTYPE;creator TEXT;approver TEXT;
BEGIN
 SELECT * INTO p FROM reconforge.ap_purchase_orders WHERE tenant_id=c.tenant_id AND id=c.purchase_order_id;
 creator:=reconforge.procurement_actor_id(c.tenant_id,p.created_by);
 IF creator IS DISTINCT FROM c.creator_actor_id THEN
 RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Procurement purchase creator differs from the retained command actor.'; END IF;
 IF c.stage>=2 THEN
 approver:=reconforge.procurement_actor_id(c.tenant_id,p.approved_by);
 IF approver=creator OR NOT EXISTS(SELECT 1 FROM reconforge.procurement_commands m WHERE m.tenant_id=c.tenant_id AND m.cycle_id=c.id
 AND m.cycle_version=3 AND m.operation='approve-order' AND m.actor_id=approver) THEN
 RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Procurement order approval needs its independent retained command actor.'; END IF;
 END IF;
 IF c.stage>=6 THEN
 SELECT * INTO i FROM reconforge.ap_supplier_invoices WHERE tenant_id=c.tenant_id AND id=c.invoice_id;
 creator:=reconforge.procurement_actor_id(c.tenant_id,i.created_by);
 IF NOT EXISTS(SELECT 1 FROM reconforge.procurement_commands m WHERE m.tenant_id=c.tenant_id AND m.cycle_id=c.id
 AND m.cycle_version=7 AND m.operation='match-invoice' AND m.actor_id=creator) THEN
 RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Procurement invoice creator differs from the retained match command actor.'; END IF;
 IF c.stage>=7 THEN
 approver:=reconforge.procurement_actor_id(c.tenant_id,i.approved_by);
 IF approver=creator OR NOT EXISTS(SELECT 1 FROM reconforge.procurement_commands m WHERE m.tenant_id=c.tenant_id AND m.cycle_id=c.id
 AND m.cycle_version=8 AND m.operation='approve-invoice' AND m.actor_id=approver) THEN
 RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Procurement invoice approval needs its independent retained command actor.'; END IF;
 END IF;
 END IF;
END $$;
CREATE FUNCTION reconforge.procurement_verify_cycle(c reconforge.procurement_cycles) RETURNS VOID
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE p reconforge.ap_purchase_orders%ROWTYPE;l reconforge.ap_purchase_order_lines%ROWTYPE;
 r reconforge.inventory_receipt_plans%ROWTYPE;g reconforge.ap_goods_receipts%ROWTYPE;i reconforge.ap_supplier_invoices%ROWTYPE;
 qty NUMERIC;a reconforge.operational_finance_plans%ROWTYPE;q reconforge.operational_finance_plans%ROWTYPE;ap_account TEXT;cash_account TEXT;
BEGIN
 IF (c.stage<3 AND c.receipt_plan_id IS NOT NULL) OR (c.stage<5 AND c.goods_receipt_id IS NOT NULL)
 OR (c.stage<6 AND c.invoice_id IS NOT NULL) OR (c.stage<8 AND c.accrual_plan_id IS NOT NULL)
 OR (c.stage<10 AND c.accrual_effect_id IS NOT NULL) OR (c.stage<11 AND c.payment_plan_id IS NOT NULL)
 OR (c.stage<13 AND (c.payment_effect_id IS NOT NULL OR c.payment_link_id IS NOT NULL)) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='procurement_owner_phase',MESSAGE='Procurement retained engine references must match their exact cycle phase.'; END IF;
 SELECT * INTO p FROM reconforge.ap_purchase_orders WHERE tenant_id=c.tenant_id AND id=c.purchase_order_id;
 SELECT * INTO l FROM reconforge.ap_purchase_order_lines WHERE tenant_id=c.tenant_id AND purchase_order_id=p.id;
 qty:=(c.request_json->>'quantity')::numeric;
 IF p IS NULL OR l IS NULL OR (SELECT count(*) FROM reconforge.ap_purchase_order_lines WHERE tenant_id=c.tenant_id AND purchase_order_id=p.id)<>1
 OR (p.workspace_id,p.organization_id,p.legal_entity_id) IS DISTINCT FROM (c.workspace_id,c.organization_id,c.legal_entity_id)
 OR p.currency_code<>c.request_json->>'currency_code' OR l.item_code<>c.request_json->>'item_code'
 OR l.ordered_quantity<>qty OR l.unit_price_minor<>(c.request_json->>'unit_price_minor')::bigint OR l.tax_minor<>0
 OR qty*l.unit_price_minor<>c.total_minor THEN
 RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Procurement source differs from its exact purchase order.'; END IF;
 IF reconforge.procurement_actor_id(c.tenant_id,p.created_by) IS DISTINCT FROM c.creator_actor_id
 OR c.stage=0 AND p.status<>'Draft' OR c.stage=1 AND p.status<>'Submitted' OR c.stage>=2 AND p.status<>'Approved' THEN
 RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Procurement requires its current approved purchase order.'; END IF;
 IF c.stage>=2 AND reconforge.procurement_actor_id(c.tenant_id,p.approved_by)=c.creator_actor_id THEN
 RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Procurement order approval requires an independent canonical identity.'; END IF;
 IF c.stage>=3 THEN
 SELECT * INTO r FROM reconforge.inventory_receipt_plans WHERE tenant_id=c.tenant_id AND id=c.receipt_plan_id;
 IF r IS NULL OR r.operation<>'Receipt' OR (r.workspace_id,r.organization_id,r.legal_entity_id) IS DISTINCT FROM (c.workspace_id,c.organization_id,c.legal_entity_id)
 OR r.currency_code<>p.currency_code OR r.total_value_minor<>c.total_minor OR r.quantity_scaled<>qty*power(10::numeric,r.quantity_precision)
 OR r.posting_date<>(c.request_json->>'posting_date')::date OR r.period_id<>c.request_json->>'period_id'
 OR NOT EXISTS(SELECT 1 FROM reconforge.inventory_items WHERE tenant_id=c.tenant_id AND id=r.item_id AND item_code=l.item_code) THEN
 RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Procurement receipt capture differs from ordered stock and cost.'; END IF;
 END IF;
 IF c.stage=3 AND EXISTS(SELECT 1 FROM reconforge.inventory_receipt_reviews WHERE tenant_id=c.tenant_id AND plan_id=r.id)
 OR c.stage IN (3,4) AND EXISTS(SELECT 1 FROM reconforge.inventory_receipt_links WHERE tenant_id=c.tenant_id AND plan_id=r.id) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='procurement_owner_phase',MESSAGE='Procurement receipt review and posting must advance its exact owner phase.'; END IF;
 IF c.stage>=4 AND NOT EXISTS(SELECT 1 FROM reconforge.inventory_receipt_reviews WHERE tenant_id=c.tenant_id AND plan_id=r.id) THEN
 RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Procurement receipt needs independent review.'; END IF;
 IF c.stage>=5 THEN
 SELECT * INTO g FROM reconforge.ap_goods_receipts WHERE tenant_id=c.tenant_id AND id=c.goods_receipt_id;
 IF g IS NULL OR g.purchase_order_id<>p.id OR g.workspace_id<>c.workspace_id OR g.status<>'Posted'
 OR NOT EXISTS(SELECT 1 FROM reconforge.ap_goods_receipt_lines WHERE tenant_id=c.tenant_id AND receipt_id=g.id AND purchase_order_line_id=l.id AND received_quantity=qty)
 OR NOT EXISTS(SELECT 1 FROM reconforge.inventory_receipt_links WHERE tenant_id=c.tenant_id AND plan_id=r.id) THEN
 RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Procurement receiving requires stock/FIFO/GL and AP receipt atomically.'; END IF;
 END IF;
 IF c.stage>=6 THEN
 SELECT * INTO i FROM reconforge.ap_supplier_invoices WHERE tenant_id=c.tenant_id AND id=c.invoice_id;
 IF i IS NULL OR i.purchase_order_id<>p.id OR i.supplier_id<>p.supplier_id OR i.total_minor<>c.total_minor OR i.tax_minor<>0 OR i.currency_code<>p.currency_code
 OR (i.workspace_id,i.organization_id,i.legal_entity_id) IS DISTINCT FROM (c.workspace_id,c.organization_id,c.legal_entity_id)
 OR (c.stage=6 AND i.status<>'Matched') OR (c.stage BETWEEN 7 AND 12 AND i.status<>'Approved') OR (c.stage=13 AND i.status<>'Paid')
 OR NOT EXISTS(SELECT 1 FROM reconforge.ap_three_way_matches WHERE tenant_id=c.tenant_id AND supplier_invoice_id=i.id AND status='Passed') THEN
 RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Procurement invoice needs exact passed three-way matching.'; END IF;
 IF c.stage>=7 AND reconforge.procurement_actor_id(c.tenant_id,i.created_by)=reconforge.procurement_actor_id(c.tenant_id,i.approved_by) THEN
 RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Procurement invoice approval requires an independent canonical identity.'; END IF;
 END IF;
 IF c.stage>=8 THEN
 SELECT * INTO a FROM reconforge.operational_finance_plans WHERE tenant_id=c.tenant_id AND id=c.accrual_plan_id;
 SELECT x.id INTO ap_account FROM reconforge.finance_accounts x JOIN reconforge.finance_journals j ON j.tenant_id=x.tenant_id AND j.chart_id=x.chart_id
 WHERE x.tenant_id=c.tenant_id AND x.workspace_id=c.workspace_id AND x.account_code=c.request_json->>'ap_account_code'
 AND j.workspace_id=c.workspace_id AND j.journal_code=c.request_json->>'journal_code';
 IF a IS NULL OR a.source_kind<>'APInvoice' OR a.source_id<>i.id OR a.amount_minor<>c.total_minor OR a.currency_code<>p.currency_code
 OR (a.workspace_id,a.organization_id,a.legal_entity_id) IS DISTINCT FROM (c.workspace_id,c.organization_id,c.legal_entity_id)
 OR a.payload->'snapshot'->'entry'->>'period_id'<>c.request_json->>'period_id'
 OR a.payload->'snapshot'->'entry'->>'posting_date'<>c.request_json->>'posting_date'
 OR a.payload->'snapshot'->'lines'->0->>'account_id'<>r.receipt_clearing_account_id
 OR ap_account IS NULL OR a.payload->'snapshot'->'lines'->1->>'account_id'<>ap_account THEN
 RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Procurement accrual requires this invoice, receipt clearing and exact AP mapping.'; END IF;
 PERFORM reconforge.ops_close_plan(c.tenant_id,a.id);
 END IF;
 IF c.stage=8 AND EXISTS(SELECT 1 FROM reconforge.operational_finance_reviews WHERE tenant_id=c.tenant_id AND plan_id=a.id)
 OR c.stage IN (8,9) AND EXISTS(SELECT 1 FROM reconforge.operational_finance_links WHERE tenant_id=c.tenant_id AND plan_id=a.id) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='procurement_owner_phase',MESSAGE='Procurement accrual review and posting must advance its exact owner phase.'; END IF;
 IF c.stage>=9 AND NOT EXISTS(SELECT 1 FROM reconforge.operational_finance_reviews WHERE tenant_id=c.tenant_id AND plan_id=a.id AND plan_digest=a.plan_digest) THEN
 RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Procurement accrual needs retained independent review.'; END IF;
 IF c.stage>=10 AND NOT EXISTS(SELECT 1 FROM reconforge.operational_finance_links WHERE tenant_id=c.tenant_id AND plan_id=a.id AND posting_effect_id=c.accrual_effect_id) THEN
 RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Procurement accrual effect must belong to this retained reviewed invoice plan.'; END IF;
 IF c.stage>=11 THEN
 SELECT * INTO q FROM reconforge.operational_finance_plans WHERE tenant_id=c.tenant_id AND id=c.payment_plan_id;
 SELECT x.id INTO cash_account FROM reconforge.finance_accounts x JOIN reconforge.finance_journals j ON j.tenant_id=x.tenant_id AND j.chart_id=x.chart_id
 WHERE x.tenant_id=c.tenant_id AND x.workspace_id=c.workspace_id AND x.account_code=c.request_json->>'cash_account_code'
 AND j.workspace_id=c.workspace_id AND j.journal_code=c.request_json->>'journal_code';
 IF q IS NULL OR q.source_kind<>'APPayment' OR q.source_id<>i.id OR q.amount_minor<>c.total_minor OR q.currency_code<>p.currency_code
 OR (q.workspace_id,q.organization_id,q.legal_entity_id) IS DISTINCT FROM (c.workspace_id,c.organization_id,c.legal_entity_id)
 OR q.payload->'snapshot'->'entry'->>'period_id'<>c.request_json->>'period_id'
 OR q.payload->'snapshot'->'entry'->>'posting_date'<>c.request_json->>'posting_date'
 OR q.payload->'snapshot'->'lines'->0->>'account_id'<>ap_account
 OR cash_account IS NULL OR q.payload->'snapshot'->'lines'->1->>'account_id'<>cash_account THEN
 RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Procurement payment requires this invoice and exact AP/cash mapping.'; END IF;
 PERFORM reconforge.ops_close_plan(c.tenant_id,q.id);
 END IF;
 IF c.stage=11 AND EXISTS(SELECT 1 FROM reconforge.operational_finance_reviews WHERE tenant_id=c.tenant_id AND plan_id=q.id)
 OR c.stage IN (11,12) AND EXISTS(SELECT 1 FROM reconforge.operational_finance_links WHERE tenant_id=c.tenant_id AND plan_id=q.id) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='procurement_owner_phase',MESSAGE='Procurement payment review and posting must advance its exact owner phase.'; END IF;
 IF c.stage>=12 AND NOT EXISTS(SELECT 1 FROM reconforge.operational_finance_reviews WHERE tenant_id=c.tenant_id AND plan_id=q.id AND plan_digest=q.plan_digest) THEN
 RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Procurement payment needs retained independent review.'; END IF;
 IF c.stage=13 AND NOT EXISTS(SELECT 1 FROM reconforge.operational_finance_links WHERE tenant_id=c.tenant_id AND plan_id=q.id AND posting_effect_id=c.payment_effect_id) THEN
 RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Procurement payment effect must belong to this retained reviewed payment plan.'; END IF;
 IF c.stage>=7 AND i.status NOT IN ('Approved','Paid') OR c.stage>=10 AND c.accrual_effect_id IS NULL THEN
 RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Procurement needs independently approved invoice and retained accrual.'; END IF;
 IF c.stage=13 AND (i.status<>'Paid' OR c.payment_effect_id IS NULL OR NOT EXISTS(SELECT 1 FROM reconforge.ap_payment_links
 WHERE tenant_id=c.tenant_id AND id=c.payment_link_id AND supplier_invoice_id=i.id AND finance_effect_id=c.payment_effect_id AND amount_minor=c.total_minor
 AND (workspace_id,organization_id,legal_entity_id,currency_code,ap_account_id,cash_account_id)=(c.workspace_id,c.organization_id,c.legal_entity_id,p.currency_code,ap_account,cash_account))) THEN
 RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Procurement paid state requires exact governed payment evidence.'; END IF;
 RETURN;
END $$;
CREATE FUNCTION reconforge.procurement_guard() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Procurement source history is retained.'; END IF;
 IF TG_OP='UPDATE' AND (NEW.tenant_id,NEW.id,NEW.workspace_id,NEW.organization_id,NEW.legal_entity_id,NEW.number,NEW.request_json,NEW.total_minor,NEW.purchase_order_id,NEW.creator_actor_id,NEW.created_at)
 IS DISTINCT FROM (OLD.tenant_id,OLD.id,OLD.workspace_id,OLD.organization_id,OLD.legal_entity_id,OLD.number,OLD.request_json,OLD.total_minor,OLD.purchase_order_id,OLD.creator_actor_id,OLD.created_at) THEN
 RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Procurement immutable source differs.'; END IF;
 IF TG_OP='UPDATE' AND (NEW.stage<>OLD.stage+1 OR NEW.row_version<>OLD.row_version+1) THEN
 RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Procurement stage requires exactly the next reviewed version.'; END IF;
 IF TG_OP='UPDATE' AND ((OLD.receipt_plan_id IS NOT NULL AND NEW.receipt_plan_id IS DISTINCT FROM OLD.receipt_plan_id) OR
 (OLD.goods_receipt_id IS NOT NULL AND NEW.goods_receipt_id IS DISTINCT FROM OLD.goods_receipt_id) OR
 (OLD.invoice_id IS NOT NULL AND NEW.invoice_id IS DISTINCT FROM OLD.invoice_id) OR
 (OLD.accrual_plan_id IS NOT NULL AND NEW.accrual_plan_id IS DISTINCT FROM OLD.accrual_plan_id) OR
 (OLD.payment_plan_id IS NOT NULL AND NEW.payment_plan_id IS DISTINCT FROM OLD.payment_plan_id) OR
 (OLD.accrual_effect_id IS NOT NULL AND NEW.accrual_effect_id IS DISTINCT FROM OLD.accrual_effect_id) OR
 (OLD.payment_effect_id IS NOT NULL AND NEW.payment_effect_id IS DISTINCT FROM OLD.payment_effect_id) OR
 (OLD.payment_link_id IS NOT NULL AND NEW.payment_link_id IS DISTINCT FROM OLD.payment_link_id)) THEN
 RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Procurement retained engine link is immutable.'; END IF;
 PERFORM reconforge.procurement_verify_cycle(NEW);
 RETURN NEW;
END $$;
CREATE TRIGGER procurement_cycles_guard BEFORE INSERT OR UPDATE OR DELETE ON reconforge.procurement_cycles FOR EACH ROW EXECUTE FUNCTION reconforge.procurement_guard();
"""

# Reverse reference closure validates the statically declared complete source routine.
UPGRADE_SQL += r"""
CREATE FUNCTION reconforge.procurement_source_closure() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE j JSONB;references_json JSONB[];parent TEXT;owned_plan_id TEXT;source_kind TEXT;source_id TEXT;
 receipt reconforge.inventory_receipt_plans%ROWTYPE;c reconforge.procurement_cycles;
BEGIN
 IF TG_OP='INSERT' THEN references_json:=ARRAY[to_jsonb(NEW)];
 ELSIF TG_OP='DELETE' THEN references_json:=ARRAY[to_jsonb(OLD)];
 ELSE references_json:=ARRAY[to_jsonb(OLD),to_jsonb(NEW)]; END IF;
 FOREACH j IN ARRAY references_json LOOP
 owned_plan_id:=NULL;source_kind:=NULL;source_id:=NULL;receipt:=NULL;
 parent:=CASE TG_TABLE_NAME
 WHEN 'procurement_cycles' THEN j->>'id'
 WHEN 'ap_purchase_orders' THEN j->>'id'
 WHEN 'ap_purchase_order_lines' THEN j->>'purchase_order_id'
 WHEN 'ap_goods_receipts' THEN j->>'id'
 WHEN 'ap_goods_receipt_lines' THEN j->>'receipt_id'
 WHEN 'ap_supplier_invoices' THEN j->>'id'
 WHEN 'ap_supplier_invoice_lines' THEN j->>'supplier_invoice_id'
 WHEN 'ap_three_way_matches' THEN j->>'supplier_invoice_id'
 WHEN 'ap_payment_links' THEN j->>'supplier_invoice_id' END;
 IF TG_TABLE_NAME IN ('operational_finance_plans','operational_finance_reviews','operational_finance_links','operational_finance_commands') THEN
 owned_plan_id:=CASE WHEN TG_TABLE_NAME='operational_finance_plans' THEN j->>'id' ELSE j->>'plan_id' END;
 SELECT p.source_kind,p.source_id INTO source_kind,source_id FROM reconforge.operational_finance_plans p
 WHERE p.tenant_id=j->>'tenant_id' AND p.id=owned_plan_id;
 IF source_kind IN ('APInvoice','APPayment') THEN parent:=source_id; END IF;
 ELSIF TG_TABLE_NAME IN ('inventory_receipt_plans','inventory_receipt_reviews','inventory_receipt_links','inventory_receipt_commands') THEN
 owned_plan_id:=CASE WHEN TG_TABLE_NAME='inventory_receipt_plans' THEN j->>'id' ELSE j->>'plan_id' END;
 SELECT * INTO receipt FROM reconforge.inventory_receipt_plans p WHERE p.tenant_id=j->>'tenant_id' AND p.id=owned_plan_id;
 END IF;
 FOR c IN SELECT * FROM reconforge.procurement_cycles WHERE tenant_id=j->>'tenant_id'
 AND (id=parent OR purchase_order_id=parent OR goods_receipt_id=parent OR invoice_id=parent
 OR receipt_plan_id=owned_plan_id OR accrual_plan_id=owned_plan_id OR payment_plan_id=owned_plan_id
 OR receipt_plan_id=receipt.original_plan_id
 OR (receipt.operation='Receipt' AND receipt.source_number='GR-'||number
 AND (receipt.workspace_id,receipt.organization_id,receipt.legal_entity_id)=(workspace_id,organization_id,legal_entity_id))) LOOP
 IF (source_kind='APInvoice' AND (c.stage<8 OR c.accrual_plan_id IS DISTINCT FROM owned_plan_id))
 OR (source_kind='APPayment' AND (c.stage<11 OR c.payment_plan_id IS DISTINCT FROM owned_plan_id)) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='procurement_owner_phase',MESSAGE='Procurement operational source must be captured by its exact owner phase.'; END IF;
 IF receipt.operation='FullReceiptReversal' AND receipt.original_plan_id=c.receipt_plan_id THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='procurement_owner_phase',MESSAGE='Procurement receipt reversal requires an integrated supplier return owner.'; END IF;
 IF receipt.operation='Receipt' AND (c.stage<3 OR c.receipt_plan_id IS DISTINCT FROM owned_plan_id) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='procurement_owner_phase',MESSAGE='Procurement receipt source must be captured by its exact owner phase.'; END IF;
 PERFORM reconforge.procurement_verify_cycle(c);
 PERFORM reconforge.procurement_verify_approval_commands(c);
 END LOOP;
 END LOOP;
 RETURN NULL;
END $$;
DO $$ DECLARE t TEXT; BEGIN
 FOREACH t IN ARRAY ARRAY['procurement_cycles','ap_purchase_orders','ap_purchase_order_lines','ap_goods_receipts','ap_goods_receipt_lines',
  'ap_supplier_invoices','ap_supplier_invoice_lines','ap_three_way_matches','ap_payment_links',
  'operational_finance_plans','operational_finance_reviews','operational_finance_links','operational_finance_commands',
  'inventory_receipt_plans','inventory_receipt_reviews','inventory_receipt_links','inventory_receipt_commands'] LOOP
 EXECUTE format('CREATE CONSTRAINT TRIGGER %I AFTER INSERT OR UPDATE OR DELETE ON reconforge.%I DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION reconforge.procurement_source_closure()',t||'_procurement_closure',t);
 END LOOP;
END $$;
"""

UPGRADE_SQL += r"""
DROP POLICY procurement_cycles_scope ON reconforge.procurement_cycles;
CREATE POLICY procurement_cycles_scope ON reconforge.procurement_cycles
USING(reconforge.irp_scope(tenant_id,workspace_id,organization_id,legal_entity_id))
WITH CHECK(reconforge.irp_scope(tenant_id,workspace_id,organization_id,legal_entity_id));
CREATE FUNCTION reconforge.procurement_close_commands() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE j JSONB;c reconforge.procurement_cycles;m RECORD;actions TEXT[]:=ARRAY['create','submit-order','approve-order','prepare-receipt','review-receipt','receive',
 'match-invoice','approve-invoice','prepare-accrual','review-accrual','post-accrual','prepare-payment','review-payment','pay'];
BEGIN
 j:=CASE WHEN TG_OP='DELETE' THEN to_jsonb(OLD) ELSE to_jsonb(NEW) END;
 SELECT * INTO c FROM reconforge.procurement_cycles WHERE tenant_id=j->>'tenant_id' AND id=CASE WHEN TG_TABLE_NAME='procurement_cycles' THEN j->>'id'
 WHEN TG_TABLE_NAME='outbox_events' THEN j->>'aggregate_id' WHEN TG_TABLE_NAME='domain_audit_events' THEN j->>'object_id' ELSE j->>'cycle_id' END;
 IF c IS NULL OR NOT reconforge.irp_scope(c.tenant_id,c.workspace_id,c.organization_id,c.legal_entity_id) THEN
 RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Procurement command needs canonical cycle scope.'; END IF;
 IF (SELECT count(*) FROM reconforge.procurement_commands WHERE tenant_id=c.tenant_id AND cycle_id=c.id)<>c.row_version THEN
 RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Each procurement version needs exactly one retained command and audit event.'; END IF;
 FOR m IN SELECT * FROM reconforge.procurement_commands WHERE tenant_id=c.tenant_id AND cycle_id=c.id ORDER BY cycle_version LOOP
 IF m.cycle_version>c.row_version OR m.workspace_id<>c.workspace_id OR m.operation IS DISTINCT FROM actions[m.cycle_version]
 OR reconforge.irp_digest(jsonb_build_object('cycle_id',c.id,'operation',m.operation,'payload',m.request_json,'actor_id',m.actor_id)) IS DISTINCT FROM m.request_digest
 OR m.response_json->'cycle'->>'id' IS DISTINCT FROM c.id OR (m.response_json->'cycle'->>'row_version')::bigint IS DISTINCT FROM m.cycle_version
 OR m.response_json->'cycle'->>'total_minor' IS DISTINCT FROM c.total_minor::text
 OR (m.response_json->'cycle'->>'workspace_id',m.response_json->'cycle'->>'organization_id',m.response_json->'cycle'->>'legal_entity_id') IS DISTINCT FROM (c.workspace_id,c.organization_id,c.legal_entity_id)
 OR (m.cycle_version=1 AND (m.request_json IS DISTINCT FROM c.request_json OR m.actor_id<>c.creator_actor_id))
 OR (m.cycle_version>1 AND (m.request_json->>'expected_version')::bigint<>m.cycle_version-1)
 OR NOT EXISTS(SELECT 1 FROM reconforge.domain_audit_events a JOIN reconforge.outbox_events o ON o.tenant_id=a.tenant_id
 WHERE a.tenant_id=c.tenant_id AND a.id=m.audit_event_id AND a.object_type='procurement_cycle' AND a.object_id=c.id
 AND a.actor_user_id=m.actor_id AND a.action='procurement_'||replace(m.operation,'-','_') AND
 a.metadata_json=jsonb_build_object('stage',m.response_json->'cycle'->>'stage','row_version',m.cycle_version,'request_digest',m.request_digest)
 AND o.event_id=m.outbox_event_id AND o.event_type='procurement.cycle_changed' AND o.aggregate_type='procurement_cycle' AND o.aggregate_id=c.id
 AND (o.workspace_id,o.organization_id,o.legal_entity_id)=(c.workspace_id,c.organization_id,c.legal_entity_id)
 AND o.payload=jsonb_build_object('cycle_id',c.id,'stage',m.response_json->'cycle'->>'stage','row_version',m.cycle_version,'audit_event_id',m.audit_event_id)) THEN
 RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Procurement command, actor, exact request, audit or outbox evidence differs.'; END IF;
 END LOOP;
 PERFORM reconforge.procurement_verify_approval_commands(c);
 RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER procurement_cycle_commands AFTER INSERT OR UPDATE ON reconforge.procurement_cycles DEFERRABLE INITIALLY DEFERRED
 FOR EACH ROW EXECUTE FUNCTION reconforge.procurement_close_commands();
CREATE CONSTRAINT TRIGGER procurement_command_closure AFTER INSERT ON reconforge.procurement_commands DEFERRABLE INITIALLY DEFERRED
 FOR EACH ROW EXECUTE FUNCTION reconforge.procurement_close_commands();
CREATE CONSTRAINT TRIGGER procurement_outbox_closure AFTER UPDATE OR DELETE ON reconforge.outbox_events DEFERRABLE INITIALLY DEFERRED
 FOR EACH ROW WHEN(OLD.aggregate_type='procurement_cycle') EXECUTE FUNCTION reconforge.procurement_close_commands();
CREATE CONSTRAINT TRIGGER procurement_audit_closure AFTER UPDATE OR DELETE ON reconforge.domain_audit_events DEFERRABLE INITIALLY DEFERRED
 FOR EACH ROW WHEN(OLD.object_type='procurement_cycle') EXECUTE FUNCTION reconforge.procurement_close_commands();
"""

DOWNGRADE_SQL = r"""
DO $$ BEGIN IF EXISTS(SELECT 1 FROM reconforge.procurement_cycles) OR EXISTS(SELECT 1 FROM reconforge.procurement_commands) THEN
 RAISE EXCEPTION 'Retained procurement cycles prohibit downgrade; restore a verified pre-upgrade backup.'; END IF; END $$;
DO $$ DECLARE t TEXT; BEGIN
 FOREACH t IN ARRAY ARRAY['ap_purchase_orders','ap_purchase_order_lines','ap_goods_receipts','ap_goods_receipt_lines',
  'ap_supplier_invoices','ap_supplier_invoice_lines','ap_three_way_matches','ap_payment_links',
  'operational_finance_plans','operational_finance_reviews','operational_finance_links','operational_finance_commands',
  'inventory_receipt_plans','inventory_receipt_reviews','inventory_receipt_links','inventory_receipt_commands'] LOOP
 EXECUTE format('DROP TRIGGER IF EXISTS %I ON reconforge.%I',t||'_procurement_closure',t);
 END LOOP;
END $$;
DROP TABLE reconforge.procurement_commands;
DROP TRIGGER procurement_outbox_closure ON reconforge.outbox_events;
DROP TRIGGER procurement_audit_closure ON reconforge.domain_audit_events;
DROP TRIGGER procurement_cycles_procurement_closure ON reconforge.procurement_cycles;
DROP TRIGGER procurement_cycle_commands ON reconforge.procurement_cycles;
DROP FUNCTION reconforge.procurement_close_commands();
DROP FUNCTION reconforge.procurement_source_closure();
DROP FUNCTION reconforge.procurement_verify_cycle(reconforge.procurement_cycles);
DROP FUNCTION reconforge.procurement_verify_approval_commands(reconforge.procurement_cycles);
DROP TABLE reconforge.procurement_cycles;
DROP FUNCTION reconforge.procurement_guard();
DROP FUNCTION reconforge.procurement_immutable_command();
DROP FUNCTION reconforge.procurement_actor_id(TEXT,TEXT);
"""


def install_postgres_procurement_operations(connection: Any) -> None:
    connection.execute(UPGRADE_SQL)


UPGRADE_SQL = _AUTHORITY_SQL + UPGRADE_SQL
DOWNGRADE_SQL = _AUTHORITY_SQL + DOWNGRADE_SQL
