"""Additive partial purchase ownership, exact capacity and bidirectional closure."""
from __future__ import annotations

from typing import Any

_AUTHORITY_SQL = r"""
DO $$ BEGIN IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname=current_user AND (rolsuper OR rolbypassrls)) THEN
 RAISE EXCEPTION 'Partial procurement migration requires bypass of forced row security.'; END IF; END $$;
"""

_UPGRADE_BODY_SQL = r"""
CREATE TABLE reconforge.procurement_partial_orders (
 tenant_id TEXT NOT NULL,id TEXT NOT NULL,workspace_id TEXT NOT NULL,organization_id TEXT NOT NULL,legal_entity_id TEXT NOT NULL,
 number TEXT NOT NULL CHECK(length(number) BETWEEN 1 AND 40),request_json JSONB NOT NULL CHECK(octet_length(request_json::text)<=16384),
 total_minor BIGINT NOT NULL CHECK(total_minor BETWEEN 1 AND 9000000000000000000),purchase_order_id TEXT NOT NULL,
 stage INTEGER NOT NULL DEFAULT 0 CHECK(stage BETWEEN 0 AND 2),row_version BIGINT NOT NULL DEFAULT 1 CHECK(row_version>0),
 creator_actor_id TEXT NOT NULL,submitted_version BIGINT,approved_version BIGINT,created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 PRIMARY KEY(tenant_id,id),UNIQUE(tenant_id,workspace_id,number),UNIQUE(tenant_id,purchase_order_id),
 FOREIGN KEY(tenant_id,workspace_id) REFERENCES reconforge.domain_workspaces(tenant_id,id),
 FOREIGN KEY(tenant_id,organization_id) REFERENCES reconforge.organizations(tenant_id,id),
 FOREIGN KEY(tenant_id,legal_entity_id) REFERENCES reconforge.legal_entities(tenant_id,id),
 FOREIGN KEY(tenant_id,purchase_order_id) REFERENCES reconforge.ap_purchase_orders(tenant_id,id),
 FOREIGN KEY(tenant_id,creator_actor_id) REFERENCES reconforge.identity_users(tenant_id,id)
);
CREATE TABLE reconforge.procurement_partial_receipts (
 tenant_id TEXT NOT NULL,id TEXT NOT NULL,order_id TEXT NOT NULL,sequence INTEGER NOT NULL CHECK(sequence BETWEEN 1 AND 32),
 number TEXT NOT NULL,quantity NUMERIC NOT NULL CHECK(quantity>0),quantity_text TEXT NOT NULL CHECK(quantity_text::numeric=quantity),
 total_minor BIGINT NOT NULL CHECK(total_minor BETWEEN 1 AND 9000000000000000000),posting_date DATE NOT NULL,period_id TEXT NOT NULL,
 receipt_plan_id TEXT NOT NULL,goods_receipt_id TEXT,stage INTEGER NOT NULL DEFAULT 0 CHECK(stage BETWEEN 0 AND 2),
 created_version BIGINT NOT NULL,reviewed_version BIGINT,posted_version BIGINT,
 PRIMARY KEY(tenant_id,id),UNIQUE(tenant_id,order_id,sequence),UNIQUE(tenant_id,receipt_plan_id),UNIQUE(tenant_id,goods_receipt_id),
 FOREIGN KEY(tenant_id,order_id) REFERENCES reconforge.procurement_partial_orders(tenant_id,id),
 FOREIGN KEY(tenant_id,period_id) REFERENCES reconforge.fiscal_periods(tenant_id,id),
 FOREIGN KEY(tenant_id,receipt_plan_id) REFERENCES reconforge.inventory_receipt_plans(tenant_id,id),
 FOREIGN KEY(tenant_id,goods_receipt_id) REFERENCES reconforge.ap_goods_receipts(tenant_id,id)
);
CREATE TABLE reconforge.procurement_partial_invoices (
 tenant_id TEXT NOT NULL,id TEXT NOT NULL,order_id TEXT NOT NULL,sequence INTEGER NOT NULL CHECK(sequence BETWEEN 1 AND 32),
 number TEXT NOT NULL,quantity NUMERIC NOT NULL CHECK(quantity>0),quantity_text TEXT NOT NULL CHECK(quantity_text::numeric=quantity),
 total_minor BIGINT NOT NULL CHECK(total_minor BETWEEN 1 AND 9000000000000000000),posting_date DATE NOT NULL,period_id TEXT NOT NULL,
 native_invoice_id TEXT NOT NULL,accrual_plan_id TEXT,accrual_effect_id TEXT,stage INTEGER NOT NULL DEFAULT 0 CHECK(stage BETWEEN 0 AND 4),
 created_version BIGINT NOT NULL,approved_version BIGINT,prepared_version BIGINT,reviewed_version BIGINT,posted_version BIGINT,
 PRIMARY KEY(tenant_id,id),UNIQUE(tenant_id,order_id,sequence),UNIQUE(tenant_id,native_invoice_id),
 UNIQUE(tenant_id,accrual_plan_id),UNIQUE(tenant_id,accrual_effect_id),
 FOREIGN KEY(tenant_id,order_id) REFERENCES reconforge.procurement_partial_orders(tenant_id,id),
 FOREIGN KEY(tenant_id,period_id) REFERENCES reconforge.fiscal_periods(tenant_id,id),
 FOREIGN KEY(tenant_id,native_invoice_id) REFERENCES reconforge.ap_supplier_invoices(tenant_id,id),
 FOREIGN KEY(tenant_id,accrual_plan_id) REFERENCES reconforge.operational_finance_plans(tenant_id,id),
 FOREIGN KEY(tenant_id,accrual_effect_id) REFERENCES reconforge.finance_posting_effects(tenant_id,id)
);
CREATE TABLE reconforge.procurement_partial_commands (
 tenant_id TEXT NOT NULL,workspace_id TEXT NOT NULL,command_id TEXT NOT NULL CHECK(reconforge.irp_text(command_id,160)),
 order_id TEXT NOT NULL,order_version BIGINT NOT NULL CHECK(order_version>0),actor_id TEXT NOT NULL,operation TEXT NOT NULL,
 request_json JSONB NOT NULL CHECK(octet_length(request_json::text)<=16384),request_digest TEXT NOT NULL CHECK(request_digest~'^[0-9a-f]{64}$'),
 response_json JSONB NOT NULL CHECK(octet_length(response_json::text)<=262144),audit_event_id TEXT NOT NULL,outbox_event_id TEXT NOT NULL,
 PRIMARY KEY(tenant_id,workspace_id,command_id),UNIQUE(tenant_id,order_id,order_version),
 FOREIGN KEY(tenant_id,order_id) REFERENCES reconforge.procurement_partial_orders(tenant_id,id),
 FOREIGN KEY(tenant_id,actor_id) REFERENCES reconforge.identity_users(tenant_id,id),
 FOREIGN KEY(tenant_id,audit_event_id) REFERENCES reconforge.domain_audit_events(tenant_id,id),
 FOREIGN KEY(tenant_id,outbox_event_id) REFERENCES reconforge.outbox_events(tenant_id,event_id)
);
CREATE INDEX procurement_partial_scope_idx ON reconforge.procurement_partial_orders(tenant_id,workspace_id,organization_id,legal_entity_id,created_at DESC,id);
DO $$ DECLARE t TEXT; BEGIN
 FOREACH t IN ARRAY ARRAY['procurement_partial_orders','procurement_partial_receipts','procurement_partial_invoices','procurement_partial_commands'] LOOP
 EXECUTE format('ALTER TABLE reconforge.%I ENABLE ROW LEVEL SECURITY',t);
 EXECUTE format('ALTER TABLE reconforge.%I FORCE ROW LEVEL SECURITY',t);
 END LOOP;
END $$;
CREATE POLICY procurement_partial_orders_scope ON reconforge.procurement_partial_orders
 USING(reconforge.irp_scope(tenant_id,workspace_id,organization_id,legal_entity_id))
 WITH CHECK(reconforge.irp_scope(tenant_id,workspace_id,organization_id,legal_entity_id));
DO $$ DECLARE t TEXT; BEGIN
 FOREACH t IN ARRAY ARRAY['procurement_partial_receipts','procurement_partial_invoices','procurement_partial_commands'] LOOP
 EXECUTE format('CREATE POLICY %I ON reconforge.%I USING(tenant_id=current_setting(''app.tenant_id'',true) AND EXISTS(SELECT 1 FROM reconforge.procurement_partial_orders p WHERE p.tenant_id=%I.tenant_id AND p.id=order_id)) WITH CHECK(tenant_id=current_setting(''app.tenant_id'',true) AND EXISTS(SELECT 1 FROM reconforge.procurement_partial_orders p WHERE p.tenant_id=%I.tenant_id AND p.id=order_id))',t||'_scope',t,t,t);
 END LOOP;
END $$;
CREATE FUNCTION reconforge.pp_guard() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF TG_OP='DELETE' OR (TG_TABLE_NAME='procurement_partial_commands' AND TG_OP='UPDATE') THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='procurement_partial_owner_phase',MESSAGE='Partial procurement history is retained.'; END IF;
 IF TG_OP='UPDATE' AND TG_TABLE_NAME='procurement_partial_orders' THEN
 IF (to_jsonb(NEW)-ARRAY['stage','row_version','submitted_version','approved_version']) IS DISTINCT FROM
 (to_jsonb(OLD)-ARRAY['stage','row_version','submitted_version','approved_version'])
 OR NEW.stage NOT BETWEEN OLD.stage AND OLD.stage+1 OR NEW.row_version NOT BETWEEN OLD.row_version AND OLD.row_version+1
 OR (OLD.submitted_version IS NOT NULL AND NEW.submitted_version IS DISTINCT FROM OLD.submitted_version)
 OR (OLD.approved_version IS NOT NULL AND NEW.approved_version IS DISTINCT FROM OLD.approved_version) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='procurement_partial_owner_phase',MESSAGE='Partial order source, retained phase or version is immutable.'; END IF;
 ELSIF TG_OP='UPDATE' AND TG_TABLE_NAME='procurement_partial_receipts' THEN
 IF (to_jsonb(NEW)-ARRAY['stage','goods_receipt_id','reviewed_version','posted_version']) IS DISTINCT FROM
 (to_jsonb(OLD)-ARRAY['stage','goods_receipt_id','reviewed_version','posted_version']) OR NEW.stage<>OLD.stage+1
 OR (OLD.goods_receipt_id IS NOT NULL AND NEW.goods_receipt_id IS DISTINCT FROM OLD.goods_receipt_id)
 OR (OLD.reviewed_version IS NOT NULL AND NEW.reviewed_version IS DISTINCT FROM OLD.reviewed_version)
 OR (OLD.posted_version IS NOT NULL AND NEW.posted_version IS DISTINCT FROM OLD.posted_version) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='procurement_partial_owner_phase',MESSAGE='Partial receipt source or retained phase is immutable.'; END IF;
 ELSIF TG_OP='UPDATE' AND TG_TABLE_NAME='procurement_partial_invoices' THEN
 IF (to_jsonb(NEW)-ARRAY['stage','accrual_plan_id','accrual_effect_id','approved_version','prepared_version','reviewed_version','posted_version']) IS DISTINCT FROM
 (to_jsonb(OLD)-ARRAY['stage','accrual_plan_id','accrual_effect_id','approved_version','prepared_version','reviewed_version','posted_version']) OR NEW.stage<>OLD.stage+1
 OR (OLD.accrual_plan_id IS NOT NULL AND NEW.accrual_plan_id IS DISTINCT FROM OLD.accrual_plan_id)
 OR (OLD.accrual_effect_id IS NOT NULL AND NEW.accrual_effect_id IS DISTINCT FROM OLD.accrual_effect_id)
 OR (OLD.approved_version IS NOT NULL AND NEW.approved_version IS DISTINCT FROM OLD.approved_version)
 OR (OLD.prepared_version IS NOT NULL AND NEW.prepared_version IS DISTINCT FROM OLD.prepared_version)
 OR (OLD.reviewed_version IS NOT NULL AND NEW.reviewed_version IS DISTINCT FROM OLD.reviewed_version)
 OR (OLD.posted_version IS NOT NULL AND NEW.posted_version IS DISTINCT FROM OLD.posted_version) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='procurement_partial_owner_phase',MESSAGE='Partial invoice source or retained phase is immutable.'; END IF;
 END IF;
 RETURN NEW;
END $$;
DO $$ DECLARE t TEXT; BEGIN
 FOREACH t IN ARRAY ARRAY['procurement_partial_orders','procurement_partial_receipts','procurement_partial_invoices','procurement_partial_commands'] LOOP
 EXECUTE format('CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON reconforge.%I FOR EACH ROW EXECUTE FUNCTION reconforge.pp_guard()',t||'_guard',t);
 END LOOP;
END $$;
CREATE FUNCTION reconforge.pp_command(t TEXT,p TEXT,v BIGINT,k TEXT,d TEXT DEFAULT NULL) RETURNS TEXT
 LANGUAGE plpgsql STABLE SET search_path=pg_catalog AS $$
DECLARE m reconforge.procurement_partial_commands%ROWTYPE;
BEGIN
 SELECT * INTO m FROM reconforge.procurement_partial_commands WHERE tenant_id=t AND order_id=p AND order_version=v;
 IF m IS NULL OR m.operation<>k OR (d IS NOT NULL AND m.request_json->>'document_id' IS DISTINCT FROM d) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='procurement_partial_owner_phase',MESSAGE='Partial procurement phase requires its exact retained owner command.'; END IF;
 RETURN m.actor_id;
END $$;
CREATE FUNCTION reconforge.pp_verify_order(t TEXT,identifier TEXT) RETURNS VOID
 LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE c reconforge.procurement_partial_orders%ROWTYPE;p reconforge.ap_purchase_orders%ROWTYPE;l reconforge.ap_purchase_order_lines%ROWTYPE;
 d reconforge.procurement_partial_receipts%ROWTYPE;i reconforge.procurement_partial_invoices%ROWTYPE;
 r reconforge.inventory_receipt_plans%ROWTYPE;g reconforge.ap_goods_receipts%ROWTYPE;h reconforge.ap_supplier_invoices%ROWTYPE;
 a reconforge.operational_finance_plans%ROWTYPE;m reconforge.procurement_partial_commands%ROWTYPE;
 ordered NUMERIC;received NUMERIC;invoiced NUMERIC;clearing TEXT;ap_account TEXT;cash_account TEXT;paid BIGINT;precision INTEGER;
BEGIN
 SELECT * INTO c FROM reconforge.procurement_partial_orders WHERE tenant_id=t AND id=identifier;
 IF c IS NULL THEN RETURN; END IF;
 IF NOT reconforge.irp_scope(t,c.workspace_id,c.organization_id,c.legal_entity_id) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='procurement_partial_owner_phase',MESSAGE='Partial procurement requires canonical current scope.'; END IF;
 IF NOT (c.request_json ?& ARRAY['number','supplier_code','item_code','quantity','unit_price_minor','currency_code','posting_date','period_id','location_code','policy_code','journal_code','ap_account_code','cash_account_code','organization_code','entity_code','workspace'])
 OR c.request_json->>'number' IS DISTINCT FROM c.number
 OR NOT EXISTS(SELECT 1 FROM reconforge.organizations x WHERE x.tenant_id=t AND x.id=c.organization_id AND x.organization_code=c.request_json->>'organization_code')
 OR NOT EXISTS(SELECT 1 FROM reconforge.legal_entities x WHERE x.tenant_id=t AND x.id=c.legal_entity_id AND x.entity_code=c.request_json->>'entity_code') THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='procurement_partial_owner_phase',MESSAGE='Partial procurement requires complete canonical business fields.'; END IF;
 SELECT * INTO p FROM reconforge.ap_purchase_orders WHERE tenant_id=t AND id=c.purchase_order_id;
 SELECT * INTO l FROM reconforge.ap_purchase_order_lines WHERE tenant_id=t AND purchase_order_id=p.id;
 ordered:=(c.request_json->>'quantity')::numeric;
 IF p IS NULL OR l IS NULL OR (SELECT count(*) FROM reconforge.ap_purchase_order_lines WHERE tenant_id=t AND purchase_order_id=p.id)<>1
 OR p.po_number<>c.number OR (p.workspace_id,p.organization_id,p.legal_entity_id) IS DISTINCT FROM (c.workspace_id,c.organization_id,c.legal_entity_id)
 OR p.currency_code<>c.request_json->>'currency_code' OR p.order_date<>(c.request_json->>'posting_date')::date
 OR NOT EXISTS(SELECT 1 FROM reconforge.ap_suppliers s WHERE s.tenant_id=t AND s.id=p.supplier_id AND s.supplier_code=c.request_json->>'supplier_code')
 OR l.item_code<>c.request_json->>'item_code' OR l.ordered_quantity<>ordered OR l.ordered_quantity_text::numeric<>ordered
 OR l.unit_price_minor<>(c.request_json->>'unit_price_minor')::bigint OR l.tax_minor<>0 OR ordered*l.unit_price_minor<>c.total_minor
 OR NOT EXISTS(SELECT 1 FROM reconforge.inventory_items stock JOIN reconforge.inventory_units_of_measure u
 ON u.tenant_id=stock.tenant_id AND u.id=stock.uom_id WHERE stock.tenant_id=t AND stock.workspace_id=c.workspace_id AND stock.item_code=l.item_code
 AND ordered*power(10::numeric,COALESCE((SELECT q.quantity_precision FROM reconforge.procurement_partial_receipts v
 JOIN reconforge.inventory_receipt_plans q ON q.tenant_id=v.tenant_id AND q.id=v.receipt_plan_id
 WHERE v.tenant_id=t AND v.order_id=c.id ORDER BY v.sequence LIMIT 1),u.decimal_places))=
 trunc(ordered*power(10::numeric,COALESCE((SELECT q.quantity_precision FROM reconforge.procurement_partial_receipts v
 JOIN reconforge.inventory_receipt_plans q ON q.tenant_id=v.tenant_id AND q.id=v.receipt_plan_id
 WHERE v.tenant_id=t AND v.order_id=c.id ORDER BY v.sequence LIMIT 1),u.decimal_places))))
 OR reconforge.procurement_actor_id(t,p.created_by)<>c.creator_actor_id
 OR (c.stage=0 AND p.status<>'Draft') OR (c.stage=1 AND p.status<>'Submitted') OR (c.stage=2 AND p.status<>'Approved')
 OR (c.stage<1 AND c.submitted_version IS NOT NULL) OR (c.stage<2 AND c.approved_version IS NOT NULL) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='procurement_partial_owner_phase',MESSAGE='Partial purchase source or exact approved owner stage differs.'; END IF;
 IF reconforge.pp_command(t,c.id,1,'create')<>c.creator_actor_id THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='procurement_partial_owner_phase',MESSAGE='Partial purchase creator command differs.'; END IF;
 IF c.stage>=1 THEN PERFORM reconforge.pp_command(t,c.id,c.submitted_version,'submit-order'); END IF;
 IF c.stage=2 AND (reconforge.pp_command(t,c.id,c.approved_version,'approve-order') IS DISTINCT FROM reconforge.procurement_actor_id(t,p.approved_by)
 OR reconforge.procurement_actor_id(t,p.approved_by)=c.creator_actor_id) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='procurement_partial_owner_phase',MESSAGE='Partial purchase approval needs its independent canonical actor.'; END IF;
 IF (SELECT COALESCE(sum(quantity),0) FROM reconforge.procurement_partial_receipts WHERE tenant_id=t AND order_id=c.id)>ordered
 OR (c.stage<2 AND (EXISTS(SELECT 1 FROM reconforge.procurement_partial_receipts WHERE tenant_id=t AND order_id=c.id)
 OR EXISTS(SELECT 1 FROM reconforge.procurement_partial_invoices WHERE tenant_id=t AND order_id=c.id))) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='procurement_partial_owner_phase',MESSAGE='Partial receipt reservations exceed exact approved order capacity.'; END IF;
 IF EXISTS(SELECT 1 FROM reconforge.inventory_receipt_plans x WHERE x.tenant_id=t AND x.operation='Receipt'
 AND (x.workspace_id,x.organization_id,x.legal_entity_id)=(c.workspace_id,c.organization_id,c.legal_entity_id)
 AND x.source_number IN (SELECT 'PPR-'||c.number||'-'||n FROM generate_series(1,32)n)
 AND NOT EXISTS(SELECT 1 FROM reconforge.procurement_partial_receipts y WHERE y.tenant_id=t AND y.order_id=c.id AND y.receipt_plan_id=x.id))
 OR EXISTS(SELECT 1 FROM reconforge.ap_goods_receipts x WHERE x.tenant_id=t AND x.purchase_order_id=p.id
 AND NOT EXISTS(SELECT 1 FROM reconforge.procurement_partial_receipts y WHERE y.tenant_id=t AND y.order_id=c.id AND y.stage=2 AND y.goods_receipt_id=x.id))
 OR EXISTS(SELECT 1 FROM reconforge.ap_supplier_invoices x WHERE x.tenant_id=t AND (x.purchase_order_id=p.id OR
 (x.workspace_id=c.workspace_id AND x.supplier_id=p.supplier_id AND x.invoice_number IN(SELECT 'PPI-'||c.number||'-'||n FROM generate_series(1,32)n)))
 AND NOT EXISTS(SELECT 1 FROM reconforge.procurement_partial_invoices y WHERE y.tenant_id=t AND y.order_id=c.id AND y.native_invoice_id=x.id)) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='procurement_partial_owner_phase',MESSAGE='Reserved partial receipt and invoice sources require atomic owner capture.'; END IF;
 FOR d IN SELECT * FROM reconforge.procurement_partial_receipts WHERE tenant_id=t AND order_id=c.id ORDER BY sequence LOOP
 SELECT * INTO r FROM reconforge.inventory_receipt_plans WHERE tenant_id=t AND id=d.receipt_plan_id;
 IF r IS NULL OR r.operation<>'Receipt' OR r.source_number<>d.number OR d.number<>'PPR-'||c.number||'-'||d.sequence
 OR d.quantity*l.unit_price_minor<>d.total_minor OR r.total_value_minor<>d.total_minor OR r.quantity_scaled<>d.quantity*power(10::numeric,r.quantity_precision)
 OR r.currency_code<>p.currency_code OR r.posting_date<>d.posting_date OR r.period_id<>d.period_id OR d.posting_date<p.order_date
 OR (r.workspace_id,r.organization_id,r.legal_entity_id) IS DISTINCT FROM (c.workspace_id,c.organization_id,c.legal_entity_id)
 OR NOT EXISTS(SELECT 1 FROM reconforge.inventory_items x WHERE x.tenant_id=t AND x.id=r.item_id AND x.item_code=l.item_code)
 OR NOT EXISTS(SELECT 1 FROM reconforge.inventory_locations x JOIN reconforge.inventory_warehouses w ON w.tenant_id=x.tenant_id AND w.id=x.warehouse_id
 WHERE x.tenant_id=t AND x.id=r.location_id AND w.warehouse_code||'/'||x.location_code=c.request_json->>'location_code')
 OR NOT EXISTS(SELECT 1 FROM reconforge.inventory_valuation_policies x WHERE x.tenant_id=t AND x.id=r.policy_id AND x.policy_code=c.request_json->>'policy_code')
 OR reconforge.pp_command(t,c.id,d.created_version,'prepare-receipt')<>r.preparer_actor_id
 OR NOT EXISTS(SELECT 1 FROM reconforge.procurement_partial_commands x WHERE x.tenant_id=t AND x.order_id=c.id AND x.order_version=d.created_version
 AND (x.request_json->>'quantity')::numeric=d.quantity AND x.request_json->>'posting_date'=d.posting_date::text AND x.request_json->>'period_id'=d.period_id)
 OR (d.stage=0 AND d.reviewed_version IS NOT NULL) OR (d.stage<2 AND (d.posted_version IS NOT NULL OR d.goods_receipt_id IS NOT NULL))
 OR (d.stage=0 AND EXISTS(SELECT 1 FROM reconforge.inventory_receipt_reviews WHERE tenant_id=t AND plan_id=r.id))
 OR (d.stage<2 AND EXISTS(SELECT 1 FROM reconforge.inventory_receipt_links WHERE tenant_id=t AND plan_id=r.id))
 OR EXISTS(SELECT 1 FROM reconforge.inventory_receipt_plans x WHERE x.tenant_id=t AND x.original_plan_id=r.id) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='procurement_partial_owner_phase',MESSAGE='Partial receipt source, exact owner phase or unsupported supplier return differs.'; END IF;
 IF clearing IS NULL THEN clearing:=r.receipt_clearing_account_id;
 ELSIF clearing<>r.receipt_clearing_account_id THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='procurement_partial_owner_phase',MESSAGE='Partial receipts must retain one exact clearing mapping.'; END IF;
 IF d.stage>=1 AND NOT EXISTS(SELECT 1 FROM reconforge.inventory_receipt_reviews x WHERE x.tenant_id=t AND x.plan_id=r.id
 AND x.reviewer_actor_id=reconforge.pp_command(t,c.id,d.reviewed_version,'review-receipt',d.id)
 AND x.reviewer_actor_id<>r.preparer_actor_id) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='procurement_partial_owner_phase',MESSAGE='Partial receipt needs its owner independent review.'; END IF;
 IF d.stage=2 THEN
 SELECT * INTO g FROM reconforge.ap_goods_receipts WHERE tenant_id=t AND id=d.goods_receipt_id;
 IF g IS NULL OR g.purchase_order_id<>p.id OR g.receipt_number<>d.number OR g.status<>'Posted' OR g.receipt_date<>d.posting_date
 OR g.workspace_id<>c.workspace_id OR (SELECT count(*) FROM reconforge.ap_goods_receipt_lines WHERE tenant_id=t AND receipt_id=g.id)<>1
 OR NOT EXISTS(SELECT 1 FROM reconforge.ap_goods_receipt_lines WHERE tenant_id=t AND receipt_id=g.id AND purchase_order_line_id=l.id AND received_quantity=d.quantity)
 OR NOT EXISTS(SELECT 1 FROM reconforge.inventory_receipt_links x WHERE x.tenant_id=t AND x.plan_id=r.id
 AND x.posted_actor_id=reconforge.pp_command(t,c.id,d.posted_version,'receive',d.id)
 AND x.posted_actor_id NOT IN (r.preparer_actor_id,reconforge.pp_command(t,c.id,d.reviewed_version,'review-receipt',d.id))) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='procurement_partial_owner_phase',MESSAGE='Partial receiving requires three distinct human identities and exact FIFO, stock GL and native AP receipt together.'; END IF;
 PERFORM reconforge.irp_assert_complete(t,r.id);
 END IF;
 END LOOP;
 SELECT COALESCE(sum(quantity),0) INTO received FROM reconforge.procurement_partial_receipts WHERE tenant_id=t AND order_id=c.id AND stage=2;
 SELECT q.quantity_precision INTO precision FROM reconforge.procurement_partial_receipts v
 JOIN reconforge.inventory_receipt_plans q ON q.tenant_id=v.tenant_id AND q.id=v.receipt_plan_id
 WHERE v.tenant_id=t AND v.order_id=c.id AND v.stage=2 ORDER BY v.sequence LIMIT 1;
 SELECT COALESCE(sum(quantity),0) INTO invoiced FROM reconforge.procurement_partial_invoices WHERE tenant_id=t AND order_id=c.id;
 IF invoiced>received THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='procurement_partial_owner_phase',MESSAGE='Partial invoice reservations exceed posted received quantity.'; END IF;
 SELECT fa.id INTO ap_account FROM reconforge.finance_accounts fa JOIN reconforge.finance_journals j ON j.tenant_id=fa.tenant_id AND j.chart_id=fa.chart_id
 WHERE fa.tenant_id=t AND fa.workspace_id=c.workspace_id AND fa.account_code=c.request_json->>'ap_account_code' AND j.workspace_id=c.workspace_id AND j.journal_code=c.request_json->>'journal_code';
 SELECT fa.id INTO cash_account FROM reconforge.finance_accounts fa JOIN reconforge.finance_journals j ON j.tenant_id=fa.tenant_id AND j.chart_id=fa.chart_id
 WHERE fa.tenant_id=t AND fa.workspace_id=c.workspace_id AND fa.account_code=c.request_json->>'cash_account_code' AND j.workspace_id=c.workspace_id AND j.journal_code=c.request_json->>'journal_code';
 FOR i IN SELECT * FROM reconforge.procurement_partial_invoices WHERE tenant_id=t AND order_id=c.id ORDER BY sequence LOOP
 SELECT * INTO h FROM reconforge.ap_supplier_invoices WHERE tenant_id=t AND id=i.native_invoice_id;
 IF h IS NULL OR h.purchase_order_id<>p.id OR h.supplier_id<>p.supplier_id OR h.total_minor<>i.total_minor OR h.tax_minor<>0 OR h.currency_code<>p.currency_code
 OR h.invoice_number<>i.number OR i.number<>'PPI-'||c.number||'-'||i.sequence OR h.invoice_date<>i.posting_date OR i.posting_date<p.order_date OR i.quantity*l.unit_price_minor<>i.total_minor
 OR precision IS NULL OR i.quantity*power(10::numeric,precision)<>trunc(i.quantity*power(10::numeric,precision))
 OR NOT EXISTS(SELECT 1 FROM reconforge.fiscal_periods f JOIN reconforge.master_data_workspace_periods w ON w.tenant_id=f.tenant_id AND w.period_id=f.id
 WHERE f.tenant_id=t AND f.id=i.period_id AND w.workspace_id=c.workspace_id AND i.posting_date BETWEEN f.start_date AND f.end_date)
 OR (h.workspace_id,h.organization_id,h.legal_entity_id) IS DISTINCT FROM (c.workspace_id,c.organization_id,c.legal_entity_id)
 OR (i.stage=0 AND h.status<>'Matched') OR (i.stage>0 AND h.status NOT IN ('Approved','Paid'))
 OR reconforge.procurement_actor_id(t,h.created_by)<>reconforge.pp_command(t,c.id,i.created_version,'match-invoice')
 OR (SELECT count(*) FROM reconforge.ap_supplier_invoice_lines WHERE tenant_id=t AND supplier_invoice_id=h.id)<>1
 OR NOT EXISTS(SELECT 1 FROM reconforge.ap_supplier_invoice_lines x WHERE x.tenant_id=t AND x.supplier_invoice_id=h.id AND x.purchase_order_line_id=l.id
 AND x.invoiced_quantity=i.quantity AND x.unit_price_minor=l.unit_price_minor AND x.line_total_minor=i.total_minor AND x.tax_minor=0)
 OR NOT EXISTS(SELECT 1 FROM reconforge.ap_three_way_matches x WHERE x.tenant_id=t AND x.supplier_invoice_id=h.id AND x.purchase_order_id=p.id AND x.status='Passed' AND x.price_variance_minor=0 AND x.total_variance_minor=0)
 OR NOT EXISTS(SELECT 1 FROM reconforge.procurement_partial_commands x WHERE x.tenant_id=t AND x.order_id=c.id AND x.order_version=i.created_version
 AND (x.request_json->>'quantity')::numeric=i.quantity AND x.request_json->>'posting_date'=i.posting_date::text AND x.request_json->>'period_id'=i.period_id)
 OR (i.stage<1 AND i.approved_version IS NOT NULL) OR (i.stage<2 AND (i.prepared_version IS NOT NULL OR i.accrual_plan_id IS NOT NULL))
 OR (i.stage<3 AND i.reviewed_version IS NOT NULL) OR (i.stage<4 AND (i.posted_version IS NOT NULL OR i.accrual_effect_id IS NOT NULL)) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='procurement_partial_owner_phase',MESSAGE='Partial invoice native source, match or owner stage differs.'; END IF;
 IF i.stage>=1 AND (reconforge.procurement_actor_id(t,h.approved_by) IS DISTINCT FROM reconforge.pp_command(t,c.id,i.approved_version,'approve-invoice',i.id)
 OR reconforge.procurement_actor_id(t,h.approved_by)=reconforge.procurement_actor_id(t,h.created_by)) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='procurement_partial_owner_phase',MESSAGE='Partial invoice approval needs its independent canonical owner.'; END IF;
 IF EXISTS(SELECT 1 FROM reconforge.operational_finance_plans x WHERE x.tenant_id=t AND x.source_kind IN ('APInvoice','APPayment') AND x.source_id=h.id
 AND (x.source_kind='APPayment' OR i.stage<2 OR x.id IS DISTINCT FROM i.accrual_plan_id)) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='procurement_partial_owner_phase',MESSAGE='Partial invoice accrual requires its atomic owner; payments use the installment contract.'; END IF;
 IF i.stage>=2 THEN
 SELECT * INTO a FROM reconforge.operational_finance_plans WHERE tenant_id=t AND id=i.accrual_plan_id;
 IF a IS NULL OR a.source_kind<>'APInvoice' OR a.source_id<>h.id OR a.amount_minor<>i.total_minor OR a.currency_code<>h.currency_code
 OR (a.workspace_id,a.organization_id,a.legal_entity_id) IS DISTINCT FROM (c.workspace_id,c.organization_id,c.legal_entity_id)
 OR a.payload->'snapshot'->'entry'->>'period_id'<>i.period_id OR a.payload->'snapshot'->'entry'->>'posting_date'<>i.posting_date::text
 OR a.payload->'snapshot'->'lines'->0->>'account_id' IS DISTINCT FROM clearing
 OR a.payload->'snapshot'->'lines'->1->>'account_id' IS DISTINCT FROM ap_account
 OR a.preparer_actor_id<>reconforge.pp_command(t,c.id,i.prepared_version,'prepare-accrual',i.id)
 OR (i.stage=2 AND EXISTS(SELECT 1 FROM reconforge.operational_finance_reviews WHERE tenant_id=t AND plan_id=a.id))
 OR (i.stage<4 AND EXISTS(SELECT 1 FROM reconforge.operational_finance_links WHERE tenant_id=t AND plan_id=a.id)) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='procurement_partial_owner_phase',MESSAGE='Partial accrual exact money, mapping or owner phase differs.'; END IF;
 PERFORM reconforge.ops_close_plan(t,a.id);
 IF i.stage>=3 AND NOT EXISTS(SELECT 1 FROM reconforge.operational_finance_reviews x WHERE x.tenant_id=t AND x.plan_id=a.id
 AND x.reviewer_actor_id=reconforge.pp_command(t,c.id,i.reviewed_version,'review-accrual',i.id)
 AND x.reviewer_actor_id<>a.preparer_actor_id) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='procurement_partial_owner_phase',MESSAGE='Partial accrual needs its independent owner review.'; END IF;
 IF i.stage=4 AND NOT EXISTS(SELECT 1 FROM reconforge.operational_finance_links x WHERE x.tenant_id=t AND x.plan_id=a.id
 AND x.posting_effect_id=i.accrual_effect_id AND x.posted_actor_id=reconforge.pp_command(t,c.id,i.posted_version,'post-accrual',i.id)
 AND x.posted_actor_id NOT IN (a.preparer_actor_id,reconforge.pp_command(t,c.id,i.reviewed_version,'review-accrual',i.id))) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='procurement_partial_owner_phase',MESSAGE='Partial accrual requires three distinct human identities and GL and native payable must close together.'; END IF;
 END IF;
 SELECT COALESCE(sum(x.amount_minor),0) INTO paid FROM reconforge.ap_payment_links x WHERE x.tenant_id=t AND x.supplier_invoice_id=h.id;
 IF (paid>0 AND i.stage<>4) OR paid>i.total_minor OR (h.status='Paid') IS DISTINCT FROM (paid=i.total_minor)
 OR EXISTS(SELECT 1 FROM reconforge.ap_payment_links x WHERE x.tenant_id=t AND x.supplier_invoice_id=h.id
 AND (x.workspace_id,x.organization_id,x.legal_entity_id,x.currency_code,x.ap_account_id,x.cash_account_id)
 IS DISTINCT FROM (c.workspace_id,c.organization_id,c.legal_entity_id,h.currency_code,ap_account,cash_account))
 OR EXISTS(SELECT 1 FROM reconforge.ap_payment_link_reversals x JOIN reconforge.ap_payment_links y ON y.tenant_id=x.tenant_id AND y.id=x.payment_link_id
 WHERE y.tenant_id=t AND y.supplier_invoice_id=h.id) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='procurement_partial_owner_phase',MESSAGE='Partial payable payments require accrued source, exact mapping and immutable allocations.'; END IF;
 END LOOP;
 IF EXISTS(SELECT event_version FROM (
 SELECT unnest(ARRAY[1::bigint,c.submitted_version,c.approved_version]) AS event_version
 UNION ALL SELECT unnest(ARRAY[v.created_version,v.reviewed_version,v.posted_version])
 FROM reconforge.procurement_partial_receipts v WHERE v.tenant_id=t AND v.order_id=c.id
 UNION ALL SELECT unnest(ARRAY[v.created_version,v.approved_version,v.prepared_version,v.reviewed_version,v.posted_version])
 FROM reconforge.procurement_partial_invoices v WHERE v.tenant_id=t AND v.order_id=c.id) events
 WHERE event_version IS NOT NULL GROUP BY event_version HAVING count(*)<>1) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='procurement_partial_owner_phase',MESSAGE='Partial source phases require unique retained owner command versions.'; END IF;
 IF (SELECT count(*) FROM reconforge.procurement_partial_commands WHERE tenant_id=t AND order_id=c.id)<>c.row_version THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='procurement_partial_owner_phase',MESSAGE='Each partial order version needs one retained command and audit.'; END IF;
 FOR m IN SELECT * FROM reconforge.procurement_partial_commands WHERE tenant_id=t AND order_id=c.id LOOP
 IF m.workspace_id<>c.workspace_id OR m.order_version>c.row_version
 OR NOT COALESCE((
 (m.operation='create' AND m.order_version=1)
 OR (m.operation='submit-order' AND m.order_version=c.submitted_version)
 OR (m.operation='approve-order' AND m.order_version=c.approved_version)
 OR EXISTS(SELECT 1 FROM reconforge.procurement_partial_receipts x WHERE x.tenant_id=t AND x.order_id=c.id AND
 ((m.operation='prepare-receipt' AND m.order_version=x.created_version) OR (m.operation='review-receipt' AND m.order_version=x.reviewed_version)
 OR (m.operation='receive' AND m.order_version=x.posted_version)))
 OR EXISTS(SELECT 1 FROM reconforge.procurement_partial_invoices x WHERE x.tenant_id=t AND x.order_id=c.id AND
 ((m.operation='match-invoice' AND m.order_version=x.created_version) OR (m.operation='approve-invoice' AND m.order_version=x.approved_version)
 OR (m.operation='prepare-accrual' AND m.order_version=x.prepared_version) OR (m.operation='review-accrual' AND m.order_version=x.reviewed_version)
 OR (m.operation='post-accrual' AND m.order_version=x.posted_version)))),false)
 OR reconforge.irp_digest(jsonb_build_object('order_id',c.id,'operation',m.operation,'payload',m.request_json,'actor_id',m.actor_id)) IS DISTINCT FROM m.request_digest
 OR m.response_json->'order'->>'id' IS DISTINCT FROM c.id OR (m.response_json->'order'->>'row_version')::bigint IS DISTINCT FROM m.order_version
 OR (m.response_json->'order'->>'workspace_id',m.response_json->'order'->>'organization_id',m.response_json->'order'->>'legal_entity_id') IS DISTINCT FROM (c.workspace_id,c.organization_id,c.legal_entity_id)
 OR (m.order_version=1 AND (m.operation<>'create' OR m.request_json IS DISTINCT FROM c.request_json OR m.actor_id<>c.creator_actor_id))
 OR (m.order_version>1 AND (m.request_json->>'expected_version')::bigint IS DISTINCT FROM m.order_version-1)
 OR NOT EXISTS(SELECT 1 FROM reconforge.domain_audit_events evt JOIN reconforge.outbox_events o ON o.tenant_id=evt.tenant_id WHERE evt.tenant_id=t
 AND evt.id=m.audit_event_id AND evt.object_type='procurement_partial_order' AND evt.object_id=c.id AND evt.actor_user_id=m.actor_id
 AND evt.action='procurement_partial_'||replace(m.operation,'-','_') AND evt.metadata_json=jsonb_build_object('row_version',m.order_version,'request_digest',m.request_digest)
 AND o.event_id=m.outbox_event_id AND o.aggregate_type='procurement_partial_order' AND o.aggregate_id=c.id AND o.event_type='procurement.partial_changed'
 AND (o.workspace_id,o.organization_id,o.legal_entity_id)=(c.workspace_id,c.organization_id,c.legal_entity_id)
 AND o.payload=jsonb_build_object('order_id',c.id,'row_version',m.order_version,'audit_event_id',m.audit_event_id)) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='procurement_partial_owner_phase',MESSAGE='Partial order command, frozen acknowledgement, audit or outbox differs.'; END IF;
 END LOOP;
END $$;
CREATE FUNCTION reconforge.pp_source_closure() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE refs JSONB[];j JSONB;parent TEXT;native_order TEXT;native_invoice TEXT;plan TEXT;r reconforge.inventory_receipt_plans%ROWTYPE;c RECORD;
BEGIN
 refs:=CASE WHEN TG_OP='INSERT' THEN ARRAY[to_jsonb(NEW)] WHEN TG_OP='DELETE' THEN ARRAY[to_jsonb(OLD)] ELSE ARRAY[to_jsonb(OLD),to_jsonb(NEW)] END;
 FOREACH j IN ARRAY refs LOOP
 parent:=NULL;native_order:=NULL;native_invoice:=NULL;plan:=NULL;r:=NULL;
 IF TG_TABLE_NAME='procurement_partial_orders' THEN parent:=j->>'id';
 ELSIF TG_TABLE_NAME IN ('procurement_partial_receipts','procurement_partial_invoices','procurement_partial_commands') THEN parent:=j->>'order_id';
 ELSIF TG_TABLE_NAME='ap_purchase_orders' THEN native_order:=j->>'id';
 ELSIF TG_TABLE_NAME IN ('ap_purchase_order_lines','ap_goods_receipts','ap_supplier_invoices','ap_three_way_matches') THEN native_order:=j->>'purchase_order_id';
 ELSIF TG_TABLE_NAME='ap_goods_receipt_lines' THEN SELECT purchase_order_id INTO native_order FROM reconforge.ap_goods_receipts WHERE tenant_id=j->>'tenant_id' AND id=j->>'receipt_id';
 ELSIF TG_TABLE_NAME IN ('ap_supplier_invoice_lines','ap_payment_links') THEN native_invoice:=j->>'supplier_invoice_id';
 ELSIF TG_TABLE_NAME='ap_payment_link_reversals' THEN SELECT supplier_invoice_id INTO native_invoice FROM reconforge.ap_payment_links WHERE tenant_id=j->>'tenant_id' AND id=j->>'payment_link_id';
 ELSIF TG_TABLE_NAME LIKE 'operational_finance_%' THEN
 plan:=CASE WHEN TG_TABLE_NAME='operational_finance_plans' THEN j->>'id' ELSE j->>'plan_id' END;
 SELECT source_id INTO native_invoice FROM reconforge.operational_finance_plans WHERE tenant_id=j->>'tenant_id' AND id=plan AND source_kind IN ('APInvoice','APPayment');
 ELSIF TG_TABLE_NAME LIKE 'inventory_receipt_%' THEN
 plan:=CASE WHEN TG_TABLE_NAME='inventory_receipt_plans' THEN j->>'id' ELSE j->>'plan_id' END;
 SELECT * INTO r FROM reconforge.inventory_receipt_plans WHERE tenant_id=j->>'tenant_id' AND id=plan;
 ELSIF TG_TABLE_NAME='domain_audit_events' THEN parent:=j->>'object_id';
 ELSIF TG_TABLE_NAME='outbox_events' THEN parent:=j->>'aggregate_id'; END IF;
 IF TG_TABLE_NAME='ap_supplier_invoices' THEN native_invoice:=j->>'id'; END IF;
 FOR c IN SELECT x.id FROM reconforge.procurement_partial_orders x WHERE x.tenant_id=j->>'tenant_id'
 AND (x.id=parent OR x.purchase_order_id=native_order
 OR EXISTS(SELECT 1 FROM reconforge.procurement_partial_invoices y WHERE y.tenant_id=x.tenant_id AND y.order_id=x.id AND (y.native_invoice_id=native_invoice OR y.accrual_plan_id=plan))
 OR EXISTS(SELECT 1 FROM reconforge.procurement_partial_receipts y WHERE y.tenant_id=x.tenant_id AND y.order_id=x.id AND y.receipt_plan_id IN(plan,r.original_plan_id))
 OR (r.operation='Receipt' AND (r.workspace_id,r.organization_id,r.legal_entity_id)=(x.workspace_id,x.organization_id,x.legal_entity_id)
 AND r.source_number IN(SELECT 'PPR-'||x.number||'-'||n FROM generate_series(1,32)n))
 OR (TG_TABLE_NAME='ap_supplier_invoices' AND j->>'workspace_id'=x.workspace_id
 AND j->>'supplier_id'=(SELECT supplier_id FROM reconforge.ap_purchase_orders WHERE tenant_id=x.tenant_id AND id=x.purchase_order_id)
 AND j->>'invoice_number' IN(SELECT 'PPI-'||x.number||'-'||n FROM generate_series(1,32)n))) LOOP
 PERFORM reconforge.pp_verify_order(j->>'tenant_id',c.id);
 END LOOP;
 END LOOP;
 RETURN NULL;
END $$;
DO $$ DECLARE t TEXT; BEGIN
 FOREACH t IN ARRAY ARRAY['procurement_partial_orders','procurement_partial_receipts','procurement_partial_invoices','procurement_partial_commands',
 'ap_purchase_orders','ap_purchase_order_lines','ap_goods_receipts','ap_goods_receipt_lines','ap_supplier_invoices','ap_supplier_invoice_lines','ap_three_way_matches',
 'ap_payment_links','ap_payment_link_reversals','operational_finance_plans','operational_finance_reviews','operational_finance_links','operational_finance_commands',
 'inventory_receipt_plans','inventory_receipt_reviews','inventory_receipt_links','inventory_receipt_commands'] LOOP
 EXECUTE format('CREATE CONSTRAINT TRIGGER %I AFTER INSERT OR UPDATE OR DELETE ON reconforge.%I DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION reconforge.pp_source_closure()',t||'_pp_closure',t);
 END LOOP;
END $$;
CREATE CONSTRAINT TRIGGER partial_order_audit_closure AFTER UPDATE OR DELETE ON reconforge.domain_audit_events DEFERRABLE INITIALLY DEFERRED
 FOR EACH ROW WHEN(OLD.object_type='procurement_partial_order') EXECUTE FUNCTION reconforge.pp_source_closure();
CREATE CONSTRAINT TRIGGER partial_order_outbox_closure AFTER UPDATE OR DELETE ON reconforge.outbox_events DEFERRABLE INITIALLY DEFERRED
 FOR EACH ROW WHEN(OLD.aggregate_type='procurement_partial_order') EXECUTE FUNCTION reconforge.pp_source_closure();
"""

UPGRADE_SQL = "".join((_AUTHORITY_SQL, _UPGRADE_BODY_SQL))

_DOWNGRADE_BODY_SQL = r"""
DO $$ BEGIN IF EXISTS(SELECT 1 FROM reconforge.procurement_partial_orders) THEN
 RAISE EXCEPTION 'Retained partial procurements prohibit downgrade; restore a verified pre-upgrade backup.'; END IF; END $$;
DO $$ DECLARE t TEXT; BEGIN
 FOREACH t IN ARRAY ARRAY['procurement_partial_orders','procurement_partial_receipts','procurement_partial_invoices','procurement_partial_commands',
 'ap_purchase_orders','ap_purchase_order_lines','ap_goods_receipts','ap_goods_receipt_lines','ap_supplier_invoices','ap_supplier_invoice_lines','ap_three_way_matches',
 'ap_payment_links','ap_payment_link_reversals','operational_finance_plans','operational_finance_reviews','operational_finance_links','operational_finance_commands',
 'inventory_receipt_plans','inventory_receipt_reviews','inventory_receipt_links','inventory_receipt_commands'] LOOP
 EXECUTE format('DROP TRIGGER %I ON reconforge.%I',t||'_pp_closure',t);
 END LOOP;
END $$;
DROP TRIGGER partial_order_audit_closure ON reconforge.domain_audit_events;
DROP TRIGGER partial_order_outbox_closure ON reconforge.outbox_events;
DROP FUNCTION reconforge.pp_source_closure();
DROP FUNCTION reconforge.pp_verify_order(TEXT,TEXT);
DROP FUNCTION reconforge.pp_command(TEXT,TEXT,BIGINT,TEXT,TEXT);
DROP TABLE reconforge.procurement_partial_commands;
DROP TABLE reconforge.procurement_partial_invoices;
DROP TABLE reconforge.procurement_partial_receipts;
DROP TABLE reconforge.procurement_partial_orders;
DROP FUNCTION reconforge.pp_guard();
"""

DOWNGRADE_SQL = "".join((_AUTHORITY_SQL, _DOWNGRADE_BODY_SQL))


def install_postgres_procurement_partial(connection: Any) -> None:
    connection.execute(UPGRADE_SQL)
