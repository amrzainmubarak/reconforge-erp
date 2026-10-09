"""Additive immutable purchase lines with per-line capacity and native closure."""
from __future__ import annotations

from typing import Any

_AUTHORITY = r"""
DO $$ BEGIN IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname=current_user AND (rolsuper OR rolbypassrls)) THEN
 RAISE EXCEPTION 'Multiline procurement migration requires bypass of forced row security.'; END IF; END $$;
"""

_TABLES = r"""
ALTER TABLE reconforge.procurement_partial_orders ADD COLUMN multiline BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE reconforge.procurement_partial_orders ADD COLUMN line_count INTEGER NOT NULL DEFAULT 1 CHECK(line_count BETWEEN 1 AND 128);
ALTER TABLE reconforge.procurement_partial_orders DROP CONSTRAINT procurement_partial_orders_request_json_check;
ALTER TABLE reconforge.procurement_partial_orders ADD CONSTRAINT procurement_partial_orders_request_json_check CHECK(octet_length(request_json::text)<=131072);
ALTER TABLE reconforge.procurement_partial_commands DROP CONSTRAINT procurement_partial_commands_request_json_check;
ALTER TABLE reconforge.procurement_partial_commands ADD CONSTRAINT procurement_partial_commands_request_json_check CHECK(octet_length(request_json::text)<=131072);
ALTER TABLE reconforge.procurement_partial_commands DROP CONSTRAINT procurement_partial_commands_response_json_check;
ALTER TABLE reconforge.procurement_partial_commands ADD CONSTRAINT procurement_partial_commands_response_json_check CHECK(octet_length(response_json::text)<=1048576);
ALTER TABLE reconforge.procurement_partial_receipts DROP CONSTRAINT procurement_partial_receipts_sequence_check;
ALTER TABLE reconforge.procurement_partial_receipts ADD CONSTRAINT procurement_partial_receipts_sequence_check CHECK(sequence BETWEEN 1 AND 1024);
ALTER TABLE reconforge.procurement_partial_invoices DROP CONSTRAINT procurement_partial_invoices_sequence_check;
ALTER TABLE reconforge.procurement_partial_invoices ADD CONSTRAINT procurement_partial_invoices_sequence_check CHECK(sequence BETWEEN 1 AND 1024);
ALTER TABLE reconforge.procurement_partial_invoices ALTER COLUMN quantity DROP NOT NULL;
ALTER TABLE reconforge.procurement_partial_invoices ALTER COLUMN quantity_text DROP NOT NULL;
ALTER TABLE reconforge.procurement_partial_invoices ADD CONSTRAINT procurement_partial_invoice_quantity_pair CHECK((quantity IS NULL)=(quantity_text IS NULL));
ALTER TABLE reconforge.procurement_partial_invoices ADD CONSTRAINT procurement_partial_invoice_parent_key UNIQUE(tenant_id,order_id,id);
CREATE TABLE reconforge.procurement_partial_order_lines (
 tenant_id TEXT NOT NULL,id TEXT NOT NULL,order_id TEXT NOT NULL,sequence INTEGER NOT NULL CHECK(sequence BETWEEN 1 AND 128),
 purchase_order_line_id TEXT NOT NULL,item_id TEXT NOT NULL,item_code TEXT NOT NULL,uom_id TEXT NOT NULL,
 quantity_precision INTEGER NOT NULL CHECK(quantity_precision BETWEEN 0 AND 6),
 location_id TEXT NOT NULL,location_code TEXT NOT NULL,policy_id TEXT NOT NULL,policy_code TEXT NOT NULL,
 quantity NUMERIC NOT NULL CHECK(quantity>0),quantity_text TEXT NOT NULL CHECK(quantity_text::numeric=quantity),
 unit_price_minor BIGINT NOT NULL CHECK(unit_price_minor BETWEEN 1 AND 9000000000000000000),
 total_minor BIGINT NOT NULL CHECK(total_minor BETWEEN 1 AND 9000000000000000000 AND quantity*unit_price_minor=total_minor),
 PRIMARY KEY(tenant_id,id),UNIQUE(tenant_id,order_id,sequence),UNIQUE(tenant_id,purchase_order_line_id),UNIQUE(tenant_id,order_id,id),
 FOREIGN KEY(tenant_id,order_id) REFERENCES reconforge.procurement_partial_orders(tenant_id,id),
 FOREIGN KEY(tenant_id,purchase_order_line_id) REFERENCES reconforge.ap_purchase_order_lines(tenant_id,id),
 FOREIGN KEY(tenant_id,item_id) REFERENCES reconforge.inventory_items(tenant_id,id),
 FOREIGN KEY(tenant_id,uom_id) REFERENCES reconforge.inventory_units_of_measure(tenant_id,id),
 FOREIGN KEY(tenant_id,location_id) REFERENCES reconforge.inventory_locations(tenant_id,id),
 FOREIGN KEY(tenant_id,policy_id) REFERENCES reconforge.inventory_valuation_policies(tenant_id,id)
);
ALTER TABLE reconforge.procurement_partial_receipts ADD COLUMN order_line_id TEXT;
ALTER TABLE reconforge.procurement_partial_receipts ADD CONSTRAINT procurement_partial_receipt_line_scope
 FOREIGN KEY(tenant_id,order_id,order_line_id) REFERENCES reconforge.procurement_partial_order_lines(tenant_id,order_id,id);
CREATE TABLE reconforge.procurement_partial_invoice_lines (
 tenant_id TEXT NOT NULL,id TEXT NOT NULL,order_id TEXT NOT NULL,invoice_id TEXT NOT NULL,order_line_id TEXT NOT NULL,
 native_invoice_line_id TEXT NOT NULL,sequence INTEGER NOT NULL CHECK(sequence BETWEEN 1 AND 128),
 quantity NUMERIC NOT NULL CHECK(quantity>0),quantity_text TEXT NOT NULL CHECK(quantity_text::numeric=quantity),
 total_minor BIGINT NOT NULL CHECK(total_minor BETWEEN 1 AND 9000000000000000000),
 PRIMARY KEY(tenant_id,id),UNIQUE(tenant_id,invoice_id,sequence),UNIQUE(tenant_id,invoice_id,order_line_id),UNIQUE(tenant_id,native_invoice_line_id),
 FOREIGN KEY(tenant_id,order_id,invoice_id) REFERENCES reconforge.procurement_partial_invoices(tenant_id,order_id,id),
 FOREIGN KEY(tenant_id,order_id,order_line_id) REFERENCES reconforge.procurement_partial_order_lines(tenant_id,order_id,id),
 FOREIGN KEY(tenant_id,native_invoice_line_id) REFERENCES reconforge.ap_supplier_invoice_lines(tenant_id,id)
);
CREATE INDEX procurement_partial_receipt_line_capacity ON reconforge.procurement_partial_receipts(tenant_id,order_id,order_line_id,stage);
CREATE INDEX procurement_partial_invoice_line_capacity ON reconforge.procurement_partial_invoice_lines(tenant_id,order_id,order_line_id);
CREATE INDEX procurement_partial_order_keyset ON reconforge.procurement_partial_orders(tenant_id,workspace_id,organization_id,legal_entity_id,id);
ALTER TABLE reconforge.procurement_partial_order_lines ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.procurement_partial_order_lines FORCE ROW LEVEL SECURITY;
ALTER TABLE reconforge.procurement_partial_invoice_lines ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.procurement_partial_invoice_lines FORCE ROW LEVEL SECURITY;
DO $$ DECLARE t TEXT; BEGIN
 FOREACH t IN ARRAY ARRAY['procurement_partial_order_lines','procurement_partial_invoice_lines'] LOOP
 EXECUTE format('CREATE POLICY %I ON reconforge.%I USING(tenant_id=current_setting(''app.tenant_id'',true) AND EXISTS(SELECT 1 FROM reconforge.procurement_partial_orders p WHERE p.tenant_id=%I.tenant_id AND p.id=order_id)) WITH CHECK(tenant_id=current_setting(''app.tenant_id'',true) AND EXISTS(SELECT 1 FROM reconforge.procurement_partial_orders p WHERE p.tenant_id=%I.tenant_id AND p.id=order_id))',t||'_scope',t,t,t);
 END LOOP;
END $$;
CREATE FUNCTION reconforge.pp_line_immutable() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='procurement_partial_owner_phase',MESSAGE='Purchase and supplier invoice lines are immutable retained sources.'; END $$;
CREATE TRIGGER partial_order_line_immutable BEFORE UPDATE OR DELETE ON reconforge.procurement_partial_order_lines FOR EACH ROW EXECUTE FUNCTION reconforge.pp_line_immutable();
CREATE TRIGGER partial_invoice_line_immutable BEFORE UPDATE OR DELETE ON reconforge.procurement_partial_invoice_lines FOR EACH ROW EXECUTE FUNCTION reconforge.pp_line_immutable();
ALTER FUNCTION reconforge.pp_verify_order(TEXT,TEXT) RENAME TO pp_verify_order_legacy;
"""

_MULTILINE_CLOSURE = r"""
CREATE FUNCTION reconforge.pp_verify_multiline(t TEXT,identifier TEXT) RETURNS VOID
 LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE c reconforge.procurement_partial_orders%ROWTYPE;p reconforge.ap_purchase_orders%ROWTYPE;l reconforge.ap_purchase_order_lines%ROWTYPE;
 d reconforge.procurement_partial_receipts%ROWTYPE;i reconforge.procurement_partial_invoices%ROWTYPE;
 r reconforge.inventory_receipt_plans%ROWTYPE;g reconforge.ap_goods_receipts%ROWTYPE;h reconforge.ap_supplier_invoices%ROWTYPE;
 a reconforge.operational_finance_plans%ROWTYPE;m reconforge.procurement_partial_commands%ROWTYPE;
 ol reconforge.procurement_partial_order_lines%ROWTYPE;il reconforge.procurement_partial_invoice_lines%ROWTYPE;
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
 IF p IS NULL OR c.line_count<>(SELECT count(*) FROM reconforge.procurement_partial_order_lines WHERE tenant_id=t AND order_id=c.id)
 OR c.line_count<>jsonb_array_length(c.request_json->'lines')
 OR c.total_minor<>(SELECT sum(total_minor) FROM reconforge.procurement_partial_order_lines WHERE tenant_id=t AND order_id=c.id)
 OR c.line_count<>(SELECT count(*) FROM reconforge.ap_purchase_order_lines WHERE tenant_id=t AND purchase_order_id=p.id)
 OR p.po_number<>c.number OR (p.workspace_id,p.organization_id,p.legal_entity_id) IS DISTINCT FROM (c.workspace_id,c.organization_id,c.legal_entity_id)
 OR p.currency_code<>c.request_json->>'currency_code' OR p.order_date<>(c.request_json->>'posting_date')::date
 OR NOT EXISTS(SELECT 1 FROM reconforge.ap_suppliers s WHERE s.tenant_id=t AND s.id=p.supplier_id AND s.supplier_code=c.request_json->>'supplier_code')
 OR reconforge.procurement_actor_id(t,p.created_by)<>c.creator_actor_id
 OR (c.stage=0 AND p.status<>'Draft') OR (c.stage=1 AND p.status<>'Submitted') OR (c.stage=2 AND p.status<>'Approved')
 OR (c.stage<1 AND c.submitted_version IS NOT NULL) OR (c.stage<2 AND c.approved_version IS NOT NULL) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='procurement_partial_owner_phase',MESSAGE='Multiline purchase header, total, native lines or owner stage differs.'; END IF;
 FOR ol IN SELECT * FROM reconforge.procurement_partial_order_lines WHERE tenant_id=t AND order_id=c.id ORDER BY sequence LOOP
 SELECT * INTO l FROM reconforge.ap_purchase_order_lines WHERE tenant_id=t AND id=ol.purchase_order_line_id;
 IF l IS NULL OR l.purchase_order_id<>p.id OR l.line_number<>ol.sequence OR l.item_code<>ol.item_code
 OR l.ordered_quantity<>ol.quantity OR l.ordered_quantity_text::numeric<>ol.quantity
 OR l.unit_price_minor<>ol.unit_price_minor OR l.tax_minor<>0 OR ol.quantity*ol.unit_price_minor<>ol.total_minor
 OR c.request_json->'lines'->(ol.sequence-1) IS DISTINCT FROM jsonb_build_object('item_code',ol.item_code,'quantity',ol.quantity_text,
 'unit_price_minor',ol.unit_price_minor,'location_code',ol.location_code,'policy_code',ol.policy_code)
 OR NOT EXISTS(SELECT 1 FROM reconforge.inventory_items stock JOIN reconforge.inventory_units_of_measure u
 ON u.tenant_id=stock.tenant_id AND u.id=stock.uom_id WHERE stock.tenant_id=t AND stock.id=ol.item_id
 AND stock.workspace_id=c.workspace_id AND stock.item_code=ol.item_code AND stock.uom_id=ol.uom_id
 AND u.decimal_places=ol.quantity_precision AND ol.quantity*power(10::numeric,ol.quantity_precision)=trunc(ol.quantity*power(10::numeric,ol.quantity_precision)))
 OR NOT EXISTS(SELECT 1 FROM reconforge.inventory_locations loc JOIN reconforge.inventory_warehouses w ON w.tenant_id=loc.tenant_id AND w.id=loc.warehouse_id
 WHERE loc.tenant_id=t AND loc.id=ol.location_id AND w.warehouse_code||'/'||loc.location_code=ol.location_code
 AND w.workspace_id=c.workspace_id AND w.organization_id=c.organization_id AND (w.legal_entity_id IS NULL OR w.legal_entity_id=c.legal_entity_id)
 AND loc.location_type='Internal' AND NOT loc.allow_negative)
 OR NOT EXISTS(SELECT 1 FROM reconforge.inventory_valuation_policies policy WHERE policy.tenant_id=t AND policy.id=ol.policy_id
 AND policy.policy_code=ol.policy_code AND (policy.workspace_id,policy.organization_id,policy.legal_entity_id)=(c.workspace_id,c.organization_id,c.legal_entity_id)
 AND policy.currency_code=p.currency_code AND policy.costing_method='FIFO')
 OR ol.sequence>c.line_count THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='procurement_partial_owner_phase',MESSAGE='Multiline purchase line and retained item, unit, price or native source differs.'; END IF;
 SELECT COALESCE(sum(quantity),0) INTO received FROM reconforge.procurement_partial_receipts WHERE tenant_id=t AND order_id=c.id AND order_line_id=ol.id;
 IF received>ol.quantity THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='procurement_partial_owner_phase',MESSAGE='Per-line receipt reservations exceed ordered capacity.'; END IF;
 SELECT COALESCE(sum(quantity),0) INTO received FROM reconforge.procurement_partial_receipts WHERE tenant_id=t AND order_id=c.id AND order_line_id=ol.id AND stage=2;
 SELECT COALESCE(sum(quantity),0) INTO invoiced FROM reconforge.procurement_partial_invoice_lines WHERE tenant_id=t AND order_id=c.id AND order_line_id=ol.id;
 IF invoiced>received THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='procurement_partial_owner_phase',MESSAGE='Per-line invoice reservations exceed posted received capacity.'; END IF;
 END LOOP;
 IF c.stage<2 AND (EXISTS(SELECT 1 FROM reconforge.procurement_partial_receipts WHERE tenant_id=t AND order_id=c.id)
 OR EXISTS(SELECT 1 FROM reconforge.procurement_partial_invoices WHERE tenant_id=t AND order_id=c.id)) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='procurement_partial_owner_phase',MESSAGE='Partial documents require approved parent purchase.'; END IF;
 IF reconforge.pp_command(t,c.id,1,'create')<>c.creator_actor_id THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='procurement_partial_owner_phase',MESSAGE='Partial purchase creator command differs.'; END IF;
 IF c.stage>=1 THEN PERFORM reconforge.pp_command(t,c.id,c.submitted_version,'submit-order'); END IF;
 IF c.stage=2 AND (reconforge.pp_command(t,c.id,c.approved_version,'approve-order') IS DISTINCT FROM reconforge.procurement_actor_id(t,p.approved_by)
 OR reconforge.procurement_actor_id(t,p.approved_by)=c.creator_actor_id) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='procurement_partial_owner_phase',MESSAGE='Partial purchase approval needs its independent canonical actor.'; END IF;
 IF EXISTS(SELECT 1 FROM reconforge.inventory_receipt_plans x WHERE x.tenant_id=t AND x.operation='Receipt'
 AND (x.workspace_id,x.organization_id,x.legal_entity_id)=(c.workspace_id,c.organization_id,c.legal_entity_id)
 AND x.source_number IN (SELECT 'PPR-'||c.number||'-'||n FROM generate_series(1,1024)n)
 AND NOT EXISTS(SELECT 1 FROM reconforge.procurement_partial_receipts y WHERE y.tenant_id=t AND y.order_id=c.id AND y.receipt_plan_id=x.id))
 OR EXISTS(SELECT 1 FROM reconforge.ap_goods_receipts x WHERE x.tenant_id=t AND x.purchase_order_id=p.id
 AND NOT EXISTS(SELECT 1 FROM reconforge.procurement_partial_receipts y WHERE y.tenant_id=t AND y.order_id=c.id AND y.stage=2 AND y.goods_receipt_id=x.id))
 OR EXISTS(SELECT 1 FROM reconforge.ap_supplier_invoices x WHERE x.tenant_id=t AND (x.purchase_order_id=p.id OR
 (x.workspace_id=c.workspace_id AND x.supplier_id=p.supplier_id AND x.invoice_number IN(SELECT 'PPI-'||c.number||'-'||n FROM generate_series(1,1024)n)))
 AND NOT EXISTS(SELECT 1 FROM reconforge.procurement_partial_invoices y WHERE y.tenant_id=t AND y.order_id=c.id AND y.native_invoice_id=x.id)) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='procurement_partial_owner_phase',MESSAGE='Reserved partial receipt and invoice sources require atomic owner capture.'; END IF;
 FOR d IN SELECT * FROM reconforge.procurement_partial_receipts WHERE tenant_id=t AND order_id=c.id ORDER BY sequence LOOP
 SELECT * INTO ol FROM reconforge.procurement_partial_order_lines WHERE tenant_id=t AND order_id=c.id AND id=d.order_line_id;
 SELECT * INTO l FROM reconforge.ap_purchase_order_lines WHERE tenant_id=t AND id=ol.purchase_order_line_id;
 IF ol IS NULL OR l IS NULL THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='procurement_partial_owner_phase',MESSAGE='Each multiline receipt requires its actual purchase line.'; END IF;
 SELECT * INTO r FROM reconforge.inventory_receipt_plans WHERE tenant_id=t AND id=d.receipt_plan_id;
 IF r IS NULL OR r.operation<>'Receipt' OR r.source_number<>d.number OR d.number<>'PPR-'||c.number||'-'||d.sequence
 OR d.quantity*l.unit_price_minor<>d.total_minor OR r.total_value_minor<>d.total_minor OR r.quantity_scaled<>d.quantity*power(10::numeric,r.quantity_precision)
 OR r.currency_code<>p.currency_code OR r.posting_date<>d.posting_date OR r.period_id<>d.period_id OR d.posting_date<p.order_date
 OR (r.item_id,r.uom_id,r.location_id,r.policy_id,r.quantity_precision) IS DISTINCT FROM (ol.item_id,ol.uom_id,ol.location_id,ol.policy_id,ol.quantity_precision)
 OR (r.workspace_id,r.organization_id,r.legal_entity_id) IS DISTINCT FROM (c.workspace_id,c.organization_id,c.legal_entity_id)
 OR NOT EXISTS(SELECT 1 FROM reconforge.inventory_items x WHERE x.tenant_id=t AND x.id=r.item_id AND x.item_code=l.item_code)
 OR NOT EXISTS(SELECT 1 FROM reconforge.inventory_locations x JOIN reconforge.inventory_warehouses w ON w.tenant_id=x.tenant_id AND w.id=x.warehouse_id
 WHERE x.tenant_id=t AND x.id=r.location_id AND w.warehouse_code||'/'||x.location_code=ol.location_code)
 OR NOT EXISTS(SELECT 1 FROM reconforge.inventory_valuation_policies x WHERE x.tenant_id=t AND x.id=r.policy_id AND x.policy_code=ol.policy_code)
 OR reconforge.pp_command(t,c.id,d.created_version,'prepare-receipt-line')<>r.preparer_actor_id
 OR NOT EXISTS(SELECT 1 FROM reconforge.procurement_partial_commands x WHERE x.tenant_id=t AND x.order_id=c.id AND x.order_version=d.created_version
 AND x.request_json->>'line_id'=ol.id AND (x.request_json->>'quantity')::numeric=d.quantity AND x.request_json->>'posting_date'=d.posting_date::text AND x.request_json->>'period_id'=d.period_id)
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
 SELECT fa.id INTO ap_account FROM reconforge.finance_accounts fa JOIN reconforge.finance_journals j ON j.tenant_id=fa.tenant_id AND j.chart_id=fa.chart_id
 WHERE fa.tenant_id=t AND fa.workspace_id=c.workspace_id AND fa.account_code=c.request_json->>'ap_account_code' AND j.workspace_id=c.workspace_id AND j.journal_code=c.request_json->>'journal_code';
 SELECT fa.id INTO cash_account FROM reconforge.finance_accounts fa JOIN reconforge.finance_journals j ON j.tenant_id=fa.tenant_id AND j.chart_id=fa.chart_id
 WHERE fa.tenant_id=t AND fa.workspace_id=c.workspace_id AND fa.account_code=c.request_json->>'cash_account_code' AND j.workspace_id=c.workspace_id AND j.journal_code=c.request_json->>'journal_code';
 FOR i IN SELECT * FROM reconforge.procurement_partial_invoices WHERE tenant_id=t AND order_id=c.id ORDER BY sequence LOOP
 SELECT * INTO h FROM reconforge.ap_supplier_invoices WHERE tenant_id=t AND id=i.native_invoice_id;
 IF h IS NULL OR h.purchase_order_id<>p.id OR h.supplier_id<>p.supplier_id OR h.total_minor<>i.total_minor OR h.tax_minor<>0 OR h.currency_code<>p.currency_code
 OR h.invoice_number<>i.number OR i.number<>'PPI-'||c.number||'-'||i.sequence OR h.invoice_date<>i.posting_date OR i.posting_date<p.order_date
 OR i.quantity IS NOT NULL OR i.quantity_text IS NOT NULL
 OR NOT EXISTS(SELECT 1 FROM reconforge.fiscal_periods f JOIN reconforge.master_data_workspace_periods w ON w.tenant_id=f.tenant_id AND w.period_id=f.id
 WHERE f.tenant_id=t AND f.id=i.period_id AND w.workspace_id=c.workspace_id AND i.posting_date BETWEEN f.start_date AND f.end_date)
 OR (h.workspace_id,h.organization_id,h.legal_entity_id) IS DISTINCT FROM (c.workspace_id,c.organization_id,c.legal_entity_id)
 OR (i.stage=0 AND h.status<>'Matched') OR (i.stage>0 AND h.status NOT IN ('Approved','Paid'))
 OR reconforge.procurement_actor_id(t,h.created_by)<>reconforge.pp_command(t,c.id,i.created_version,'match-invoice-lines')
 OR (SELECT count(*) FROM reconforge.ap_supplier_invoice_lines WHERE tenant_id=t AND supplier_invoice_id=h.id)<>
 (SELECT count(*) FROM reconforge.procurement_partial_invoice_lines WHERE tenant_id=t AND invoice_id=i.id)
 OR (SELECT count(*) FROM reconforge.procurement_partial_invoice_lines WHERE tenant_id=t AND invoice_id=i.id) NOT BETWEEN 1 AND 128
 OR NOT EXISTS(SELECT 1 FROM reconforge.ap_three_way_matches x WHERE x.tenant_id=t AND x.supplier_invoice_id=h.id AND x.purchase_order_id=p.id AND x.status='Passed' AND x.price_variance_minor=0 AND x.total_variance_minor=0)
 OR NOT EXISTS(SELECT 1 FROM reconforge.procurement_partial_commands x WHERE x.tenant_id=t AND x.order_id=c.id AND x.order_version=i.created_version
 AND x.request_json->>'posting_date'=i.posting_date::text AND x.request_json->>'period_id'=i.period_id
 AND x.request_json->'lines'=(SELECT jsonb_agg(jsonb_build_object('line_id',order_line_id,'quantity',quantity_text) ORDER BY sequence)
 FROM reconforge.procurement_partial_invoice_lines WHERE tenant_id=t AND invoice_id=i.id))
 OR i.total_minor::numeric IS DISTINCT FROM (SELECT sum(total_minor) FROM reconforge.procurement_partial_invoice_lines WHERE tenant_id=t AND invoice_id=i.id)
 OR (i.stage<1 AND i.approved_version IS NOT NULL) OR (i.stage<2 AND (i.prepared_version IS NOT NULL OR i.accrual_plan_id IS NOT NULL))
 OR (i.stage<3 AND i.reviewed_version IS NOT NULL) OR (i.stage<4 AND (i.posted_version IS NOT NULL OR i.accrual_effect_id IS NOT NULL)) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='procurement_partial_owner_phase',MESSAGE='Partial invoice native source, match or owner stage differs.'; END IF;
 FOR il IN SELECT * FROM reconforge.procurement_partial_invoice_lines WHERE tenant_id=t AND invoice_id=i.id ORDER BY sequence LOOP
 SELECT * INTO ol FROM reconforge.procurement_partial_order_lines WHERE tenant_id=t AND order_id=c.id AND id=il.order_line_id;
 IF ol IS NULL OR il.order_id<>c.id OR il.quantity*ol.unit_price_minor<>il.total_minor
 OR il.quantity*power(10::numeric,ol.quantity_precision)<>trunc(il.quantity*power(10::numeric,ol.quantity_precision))
 OR NOT EXISTS(SELECT 1 FROM reconforge.ap_supplier_invoice_lines x WHERE x.tenant_id=t AND x.id=il.native_invoice_line_id
 AND x.supplier_invoice_id=h.id AND x.purchase_order_line_id=ol.purchase_order_line_id AND x.invoiced_quantity=il.quantity
 AND x.unit_price_minor=ol.unit_price_minor AND x.line_total_minor=il.total_minor AND x.tax_minor=0) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='procurement_partial_owner_phase',MESSAGE='Multiline invoice allocations, units, exact amounts or native lines differ.'; END IF;
 END LOOP;
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
 ((m.operation='prepare-receipt-line' AND m.order_version=x.created_version) OR (m.operation='review-receipt' AND m.order_version=x.reviewed_version)
 OR (m.operation='receive' AND m.order_version=x.posted_version)))
 OR EXISTS(SELECT 1 FROM reconforge.procurement_partial_invoices x WHERE x.tenant_id=t AND x.order_id=c.id AND
 ((m.operation='match-invoice-lines' AND m.order_version=x.created_version) OR (m.operation='approve-invoice' AND m.order_version=x.approved_version)
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
"""

_DISPATCH = r"""
CREATE FUNCTION reconforge.pp_verify_order(t TEXT,identifier TEXT) RETURNS VOID LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE c reconforge.procurement_partial_orders%ROWTYPE;
BEGIN
 SELECT * INTO c FROM reconforge.procurement_partial_orders WHERE tenant_id=t AND id=identifier;
 IF c IS NULL THEN RETURN; END IF;
 IF c.multiline THEN
 IF NOT c.request_json ? 'lines' OR jsonb_typeof(c.request_json->'lines') IS DISTINCT FROM 'array'
 OR EXISTS(SELECT 1 FROM reconforge.procurement_partial_receipts WHERE tenant_id=t AND order_id=c.id AND order_line_id IS NULL)
 OR NOT EXISTS(SELECT 1 FROM reconforge.procurement_partial_order_lines WHERE tenant_id=t AND order_id=c.id)
 OR (c.request_json->>'item_code',c.request_json->>'quantity',c.request_json->>'unit_price_minor',c.request_json->>'location_code',c.request_json->>'policy_code') IS DISTINCT FROM
 (c.request_json->'lines'->0->>'item_code',c.request_json->'lines'->0->>'quantity',c.request_json->'lines'->0->>'unit_price_minor',c.request_json->'lines'->0->>'location_code',c.request_json->'lines'->0->>'policy_code') THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='procurement_partial_owner_phase',MESSAGE='Multiline purchase requires complete authoritative line ownership.'; END IF;
 PERFORM reconforge.pp_verify_multiline(t,identifier);
 ELSE
 IF c.line_count<>1 OR c.request_json ? 'lines'
 OR EXISTS(SELECT 1 FROM reconforge.procurement_partial_order_lines WHERE tenant_id=t AND order_id=c.id)
 OR EXISTS(SELECT 1 FROM reconforge.procurement_partial_receipts WHERE tenant_id=t AND order_id=c.id AND (order_line_id IS NOT NULL OR sequence>32))
 OR EXISTS(SELECT 1 FROM reconforge.procurement_partial_invoices WHERE tenant_id=t AND order_id=c.id AND (quantity IS NULL OR quantity_text IS NULL OR sequence>32)) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='procurement_partial_owner_phase',MESSAGE='Legacy single-line procurement history retains its exact original contract.'; END IF;
 PERFORM reconforge.pp_verify_order_legacy(t,identifier);
 END IF;
END $$;
CREATE FUNCTION reconforge.pp_line_closure() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE refs JSONB[];j JSONB;
BEGIN
 refs:=CASE WHEN TG_OP='INSERT' THEN ARRAY[to_jsonb(NEW)] WHEN TG_OP='DELETE' THEN ARRAY[to_jsonb(OLD)] ELSE ARRAY[to_jsonb(OLD),to_jsonb(NEW)] END;
 FOREACH j IN ARRAY refs LOOP PERFORM reconforge.pp_verify_order(j->>'tenant_id',j->>'order_id'); END LOOP;
 RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER partial_order_line_closure AFTER INSERT OR UPDATE OR DELETE ON reconforge.procurement_partial_order_lines
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION reconforge.pp_line_closure();
CREATE CONSTRAINT TRIGGER partial_invoice_line_closure AFTER INSERT OR UPDATE OR DELETE ON reconforge.procurement_partial_invoice_lines
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION reconforge.pp_line_closure();
CREATE FUNCTION reconforge.pp_extended_number_closure() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE refs JSONB[];j JSONB;c RECORD;source_number TEXT;prefix TEXT;
BEGIN
 refs:=CASE WHEN TG_OP='INSERT' THEN ARRAY[to_jsonb(NEW)] WHEN TG_OP='DELETE' THEN ARRAY[to_jsonb(OLD)] ELSE ARRAY[to_jsonb(OLD),to_jsonb(NEW)] END;
 FOREACH j IN ARRAY refs LOOP
 source_number:=CASE WHEN TG_TABLE_NAME='inventory_receipt_plans' THEN j->>'source_number' ELSE j->>'invoice_number' END;
 prefix:=CASE WHEN TG_TABLE_NAME='inventory_receipt_plans' THEN 'PPR-' ELSE 'PPI-' END;
 FOR c IN SELECT p.id FROM reconforge.procurement_partial_orders p WHERE p.tenant_id=j->>'tenant_id' AND p.multiline
 AND p.workspace_id=j->>'workspace_id' AND source_number LIKE prefix||p.number||'-%'
 AND substring(source_number FROM length(prefix||p.number||'-')+1)~'^[1-9][0-9]{0,3}$'
 AND substring(source_number FROM length(prefix||p.number||'-')+1)::integer BETWEEN 1 AND 1024 LOOP
 PERFORM reconforge.pp_verify_order(j->>'tenant_id',c.id);
 END LOOP;
 END LOOP;
 RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER multiline_reserved_receipt_closure AFTER INSERT OR UPDATE OR DELETE ON reconforge.inventory_receipt_plans
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION reconforge.pp_extended_number_closure();
CREATE CONSTRAINT TRIGGER multiline_reserved_invoice_closure AFTER INSERT OR UPDATE OR DELETE ON reconforge.ap_supplier_invoices
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION reconforge.pp_extended_number_closure();
"""

UPGRADE_SQL = _AUTHORITY + _TABLES + _MULTILINE_CLOSURE + _DISPATCH
DOWNGRADE_SQL = _AUTHORITY + r"""
DO $$ BEGIN IF EXISTS(SELECT 1 FROM reconforge.procurement_partial_orders WHERE multiline) THEN
 RAISE EXCEPTION 'Retained multiline procurements prohibit downgrade; restore a verified pre-upgrade backup.'; END IF; END $$;
DROP TRIGGER multiline_reserved_receipt_closure ON reconforge.inventory_receipt_plans;
DROP TRIGGER multiline_reserved_invoice_closure ON reconforge.ap_supplier_invoices;
DROP FUNCTION reconforge.pp_extended_number_closure();
DROP FUNCTION reconforge.pp_verify_order(TEXT,TEXT);
DROP FUNCTION reconforge.pp_verify_multiline(TEXT,TEXT);
ALTER FUNCTION reconforge.pp_verify_order_legacy(TEXT,TEXT) RENAME TO pp_verify_order;
DROP TABLE reconforge.procurement_partial_invoice_lines;
ALTER TABLE reconforge.procurement_partial_receipts DROP CONSTRAINT procurement_partial_receipt_line_scope;
ALTER TABLE reconforge.procurement_partial_receipts DROP COLUMN order_line_id;
DROP TABLE reconforge.procurement_partial_order_lines;
DROP FUNCTION reconforge.pp_line_immutable();
DROP FUNCTION reconforge.pp_line_closure();
ALTER TABLE reconforge.procurement_partial_invoices DROP CONSTRAINT procurement_partial_invoice_parent_key;
ALTER TABLE reconforge.procurement_partial_invoices DROP CONSTRAINT procurement_partial_invoice_quantity_pair;
ALTER TABLE reconforge.procurement_partial_invoices ALTER COLUMN quantity SET NOT NULL;
ALTER TABLE reconforge.procurement_partial_invoices ALTER COLUMN quantity_text SET NOT NULL;
ALTER TABLE reconforge.procurement_partial_orders DROP COLUMN multiline;
ALTER TABLE reconforge.procurement_partial_orders DROP COLUMN line_count;
ALTER TABLE reconforge.procurement_partial_orders DROP CONSTRAINT procurement_partial_orders_request_json_check;
ALTER TABLE reconforge.procurement_partial_orders ADD CONSTRAINT procurement_partial_orders_request_json_check CHECK(octet_length(request_json::text)<=16384);
ALTER TABLE reconforge.procurement_partial_commands DROP CONSTRAINT procurement_partial_commands_request_json_check;
ALTER TABLE reconforge.procurement_partial_commands ADD CONSTRAINT procurement_partial_commands_request_json_check CHECK(octet_length(request_json::text)<=16384);
ALTER TABLE reconforge.procurement_partial_commands DROP CONSTRAINT procurement_partial_commands_response_json_check;
ALTER TABLE reconforge.procurement_partial_commands ADD CONSTRAINT procurement_partial_commands_response_json_check CHECK(octet_length(response_json::text)<=262144);
ALTER TABLE reconforge.procurement_partial_receipts DROP CONSTRAINT procurement_partial_receipts_sequence_check;
ALTER TABLE reconforge.procurement_partial_receipts ADD CONSTRAINT procurement_partial_receipts_sequence_check CHECK(sequence BETWEEN 1 AND 32);
ALTER TABLE reconforge.procurement_partial_invoices DROP CONSTRAINT procurement_partial_invoices_sequence_check;
ALTER TABLE reconforge.procurement_partial_invoices ADD CONSTRAINT procurement_partial_invoices_sequence_check CHECK(sequence BETWEEN 1 AND 32);
DROP INDEX reconforge.procurement_partial_receipt_line_capacity;
DROP INDEX reconforge.procurement_partial_order_keyset;
"""


def install_postgres_procurement_partial_multiline(connection: Any) -> None:
    if connection.execute("SELECT to_regclass('reconforge.procurement_partial_order_lines')").fetchone()[0] is not None:
        return
    with connection.transaction():
        connection.execute(UPGRADE_SQL)
