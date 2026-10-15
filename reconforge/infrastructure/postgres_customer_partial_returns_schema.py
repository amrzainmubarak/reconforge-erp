"""Native CR2 ownership, immutable economics and deferred effect closure.

Shared inventory/AR hooks are installed separately by migration 0147. Every
function here is invoker scoped; none grants a new SQL identity or bypasses RLS.
"""

STORAGE_SQL = r"""
CREATE TABLE reconforge.customer_partial_return_sources (
 tenant_id TEXT NOT NULL,id TEXT NOT NULL CHECK(id~'^CRS2-[a-f0-9]{32}$'),
 workspace_id TEXT NOT NULL,organization_id TEXT NOT NULL,legal_entity_id TEXT NOT NULL,
 source_order_id TEXT NOT NULL,invoice_id TEXT NOT NULL,customer_id TEXT NOT NULL,
 item_id TEXT NOT NULL,location_id TEXT NOT NULL,uom_id TEXT NOT NULL,
 source_fingerprint TEXT NOT NULL CHECK(source_fingerprint~'^[a-f0-9]{64}$'),source_payload JSONB NOT NULL,
 initial_collected_minor BIGINT NOT NULL CHECK(initial_collected_minor>=0),gross_minor BIGINT NOT NULL CHECK(gross_minor>0),
 original_quantity_scaled BIGINT NOT NULL CHECK(original_quantity_scaled>0),quantity_precision INTEGER NOT NULL CHECK(quantity_precision BETWEEN 0 AND 6),
 original_cogs_effect_id TEXT NOT NULL,original_revenue_effect_id TEXT NOT NULL,original_valuation_document_id TEXT NOT NULL,
 refund_liability_account_id TEXT NOT NULL,cash_account_id TEXT NOT NULL,created_actor_id TEXT NOT NULL,
 currency_code TEXT NOT NULL,currency_precision INTEGER NOT NULL,currency_rounding_policy TEXT NOT NULL,
 currency_registry_version TEXT NOT NULL,currency_registry_digest TEXT NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(),PRIMARY KEY(tenant_id,id),
 UNIQUE(tenant_id,source_order_id),UNIQUE(tenant_id,invoice_id),
 FOREIGN KEY(tenant_id,source_order_id) REFERENCES reconforge.stock_sales_orders(tenant_id,id),
 FOREIGN KEY(tenant_id,invoice_id) REFERENCES reconforge.ar_invoices(tenant_id,id),
 FOREIGN KEY(tenant_id,customer_id) REFERENCES reconforge.ar_customers(tenant_id,id),
 FOREIGN KEY(tenant_id,original_cogs_effect_id) REFERENCES reconforge.finance_posting_effects(tenant_id,id),
 FOREIGN KEY(tenant_id,original_revenue_effect_id) REFERENCES reconforge.finance_posting_effects(tenant_id,id),
 FOREIGN KEY(tenant_id,original_valuation_document_id) REFERENCES reconforge.inventory_valuation_documents(tenant_id,id),
 FOREIGN KEY(tenant_id,refund_liability_account_id) REFERENCES reconforge.finance_accounts(tenant_id,id),
 FOREIGN KEY(tenant_id,cash_account_id) REFERENCES reconforge.finance_accounts(tenant_id,id),
 FOREIGN KEY(tenant_id,created_actor_id) REFERENCES reconforge.identity_users(tenant_id,id),
 CHECK(initial_collected_minor<=gross_minor),CHECK(refund_liability_account_id<>cash_account_id)
);
CREATE TABLE reconforge.customer_partial_return_plans (
 tenant_id TEXT NOT NULL,id TEXT NOT NULL CHECK(id~'^(CR2|CRF2|CR2R|CRF2R)-[a-f0-9]{32}$'),source_id TEXT NOT NULL,
 workspace_id TEXT NOT NULL,organization_id TEXT NOT NULL,legal_entity_id TEXT NOT NULL,
 source_order_id TEXT NOT NULL,invoice_id TEXT NOT NULL,original_id TEXT,
 operation TEXT NOT NULL CHECK(operation IN('Return','Refund','ReverseReturn','ReverseRefund')),
 phase INTEGER NOT NULL DEFAULT 0 CHECK(phase BETWEEN 0 AND 3),
 amount_minor BIGINT NOT NULL CHECK(amount_minor BETWEEN 1 AND 9000000000000000000),
 quantity_scaled BIGINT NOT NULL CHECK(quantity_scaled>=0),credit_minor BIGINT NOT NULL CHECK(credit_minor>=0),
 cogs_restored_minor BIGINT NOT NULL CHECK(cogs_restored_minor>=0),receivable_released_minor BIGINT NOT NULL CHECK(receivable_released_minor>=0),
 refund_entitlement_delta_minor BIGINT NOT NULL CHECK(refund_entitlement_delta_minor>=0),
 expected_history_version INTEGER NOT NULL CHECK(expected_history_version BETWEEN 0 AND 255),
 plan_digest TEXT NOT NULL CHECK(plan_digest~'^[a-f0-9]{64}$'),payload JSONB NOT NULL,preparer_actor_id TEXT NOT NULL,
 audit_event_id TEXT NOT NULL,outbox_event_id TEXT NOT NULL,created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 PRIMARY KEY(tenant_id,id),FOREIGN KEY(tenant_id,source_id) REFERENCES reconforge.customer_partial_return_sources(tenant_id,id),
 FOREIGN KEY(tenant_id,original_id) REFERENCES reconforge.customer_partial_return_plans(tenant_id,id),
 FOREIGN KEY(tenant_id,preparer_actor_id) REFERENCES reconforge.identity_users(tenant_id,id),
 FOREIGN KEY(tenant_id,audit_event_id) REFERENCES reconforge.domain_audit_events(tenant_id,id),
 FOREIGN KEY(tenant_id,outbox_event_id) REFERENCES reconforge.outbox_events(tenant_id,event_id),
 CHECK((operation='Return' AND original_id IS NULL) OR(operation<>'Return' AND original_id IS NOT NULL)),
 CHECK((operation='Return' AND id~'^CR2-') OR(operation='Refund' AND id~'^CRF2-')
  OR(operation='ReverseReturn' AND id~'^CR2R-') OR(operation='ReverseRefund' AND id~'^CRF2R-')),
 CHECK((operation IN('Return','ReverseReturn') AND quantity_scaled>0 AND credit_minor>0 AND cogs_restored_minor>0
  AND credit_minor=receivable_released_minor+refund_entitlement_delta_minor AND amount_minor=credit_minor+cogs_restored_minor)
  OR(operation IN('Refund','ReverseRefund') AND quantity_scaled=0 AND credit_minor=0 AND cogs_restored_minor=0
   AND receivable_released_minor=0 AND refund_entitlement_delta_minor=0))
);
CREATE UNIQUE INDEX customer_partial_return_pending_source ON reconforge.customer_partial_return_plans(tenant_id,source_id) WHERE phase IN(0,1);
CREATE UNIQUE INDEX customer_partial_return_single_inverse ON reconforge.customer_partial_return_plans(tenant_id,original_id)
 WHERE operation IN('ReverseReturn','ReverseRefund') AND phase<>3;
CREATE INDEX customer_partial_return_scope ON reconforge.customer_partial_return_plans(tenant_id,workspace_id,organization_id,legal_entity_id,id COLLATE "C");
CREATE TABLE reconforge.customer_partial_return_events (
 tenant_id TEXT NOT NULL,plan_id TEXT NOT NULL,operation TEXT NOT NULL CHECK(operation IN('review','post','cancel')),
 actor_id TEXT NOT NULL,reason TEXT NOT NULL CHECK(length(reason) BETWEEN 1 AND 500),effects JSONB NOT NULL CHECK(jsonb_typeof(effects)='array'),
 audit_event_id TEXT NOT NULL,outbox_event_id TEXT NOT NULL,created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 PRIMARY KEY(tenant_id,plan_id,operation),FOREIGN KEY(tenant_id,plan_id) REFERENCES reconforge.customer_partial_return_plans(tenant_id,id),
 FOREIGN KEY(tenant_id,actor_id) REFERENCES reconforge.identity_users(tenant_id,id),
 FOREIGN KEY(tenant_id,audit_event_id) REFERENCES reconforge.domain_audit_events(tenant_id,id),
 FOREIGN KEY(tenant_id,outbox_event_id) REFERENCES reconforge.outbox_events(tenant_id,event_id)
);
CREATE TABLE reconforge.customer_partial_return_history (
 tenant_id TEXT NOT NULL,source_id TEXT NOT NULL,sequence INTEGER NOT NULL CHECK(sequence BETWEEN 1 AND 256),
 kind TEXT NOT NULL CHECK(kind IN('Return','Collection','Refund','ReverseReturn','ReverseRefund')),plan_id TEXT,receipt_id TEXT,allocation_id TEXT,
 amount_minor BIGINT NOT NULL CHECK(amount_minor>=0),quantity_scaled BIGINT NOT NULL CHECK(quantity_scaled>=0),
 credit_minor BIGINT NOT NULL CHECK(credit_minor>=0),cogs_minor BIGINT NOT NULL CHECK(cogs_minor>=0),
 payload JSONB NOT NULL,previous_digest TEXT NOT NULL CHECK(previous_digest~'^[a-f0-9]{64}$'),event_digest TEXT NOT NULL CHECK(event_digest~'^[a-f0-9]{64}$'),
 PRIMARY KEY(tenant_id,source_id,sequence),FOREIGN KEY(tenant_id,source_id) REFERENCES reconforge.customer_partial_return_sources(tenant_id,id),
 FOREIGN KEY(tenant_id,plan_id) REFERENCES reconforge.customer_partial_return_plans(tenant_id,id),
 FOREIGN KEY(tenant_id,receipt_id) REFERENCES reconforge.ar_receipts(tenant_id,id),
 CHECK((kind='Collection' AND plan_id IS NULL AND receipt_id IS NOT NULL AND allocation_id IS NOT NULL AND amount_minor>0)
  OR(kind<>'Collection' AND plan_id IS NOT NULL AND receipt_id IS NULL AND allocation_id IS NULL))
);
CREATE UNIQUE INDEX customer_partial_return_history_plan ON reconforge.customer_partial_return_history(tenant_id,plan_id) WHERE plan_id IS NOT NULL;
CREATE TABLE reconforge.customer_partial_return_restorations (
 tenant_id TEXT NOT NULL,source_id TEXT NOT NULL,plan_id TEXT NOT NULL,position INTEGER NOT NULL CHECK(position BETWEEN 1 AND 32),
 original_consumption_id TEXT NOT NULL,original_valuation_line_id TEXT NOT NULL,cost_layer_id TEXT NOT NULL,
 offset_quantity_scaled BIGINT NOT NULL CHECK(offset_quantity_scaled>=0),quantity_scaled BIGINT NOT NULL CHECK(quantity_scaled>0),
 value_minor BIGINT NOT NULL CHECK(value_minor>0),direction INTEGER NOT NULL CHECK(direction IN(-1,1)),
 physical_movement_id TEXT NOT NULL,original_cogs_effect_id TEXT NOT NULL,correction_effect_id TEXT NOT NULL,original_restoration_plan_id TEXT,
 consumption_count_at_restore BIGINT NOT NULL CHECK(consumption_count_at_restore>0),
 PRIMARY KEY(tenant_id,plan_id,position),FOREIGN KEY(tenant_id,source_id) REFERENCES reconforge.customer_partial_return_sources(tenant_id,id),
 FOREIGN KEY(tenant_id,plan_id) REFERENCES reconforge.customer_partial_return_plans(tenant_id,id),
 FOREIGN KEY(tenant_id,original_consumption_id) REFERENCES reconforge.inventory_layer_consumptions(tenant_id,id),
 FOREIGN KEY(tenant_id,original_valuation_line_id) REFERENCES reconforge.inventory_valuation_lines(tenant_id,id),
 FOREIGN KEY(tenant_id,cost_layer_id) REFERENCES reconforge.inventory_cost_layers(tenant_id,id),
 FOREIGN KEY(tenant_id,physical_movement_id) REFERENCES reconforge.inventory_movements(tenant_id,id),
 FOREIGN KEY(tenant_id,original_cogs_effect_id) REFERENCES reconforge.finance_posting_effects(tenant_id,id),
 FOREIGN KEY(tenant_id,correction_effect_id) REFERENCES reconforge.finance_posting_effects(tenant_id,id),
 FOREIGN KEY(tenant_id,original_restoration_plan_id) REFERENCES reconforge.customer_partial_return_plans(tenant_id,id),
 FOREIGN KEY(tenant_id,original_restoration_plan_id,position) REFERENCES reconforge.customer_partial_return_restorations(tenant_id,plan_id,position),
 CHECK((direction=1 AND original_restoration_plan_id IS NULL) OR(direction=-1 AND original_restoration_plan_id IS NOT NULL))
);
CREATE INDEX customer_partial_return_layer_history ON reconforge.customer_partial_return_restorations(tenant_id,cost_layer_id);
CREATE TABLE reconforge.customer_partial_return_commands (
 tenant_id TEXT NOT NULL,workspace_id TEXT NOT NULL,plan_id TEXT NOT NULL,
 operation TEXT NOT NULL CHECK(operation IN('prepare','prepare_refund','prepare_reversal','review','post','cancel')),
 command_id TEXT NOT NULL CHECK(length(command_id) BETWEEN 1 AND 140),actor_id TEXT NOT NULL,
 request_digest TEXT NOT NULL CHECK(request_digest~'^[a-f0-9]{64}$'),request_json JSONB NOT NULL,response_json JSONB NOT NULL,
 PRIMARY KEY(tenant_id,workspace_id,command_id),UNIQUE(tenant_id,plan_id,operation),
 FOREIGN KEY(tenant_id,plan_id) REFERENCES reconforge.customer_partial_return_plans(tenant_id,id),
 FOREIGN KEY(tenant_id,actor_id) REFERENCES reconforge.identity_users(tenant_id,id)
);
CREATE FUNCTION reconforge.customer_partial_return_protect() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $cr2$
DECLARE a TEXT:=current_setting('app.customer_partial_return_actor_id',true);p RECORD;s RECORD;op TEXT;
BEGIN
 IF TG_OP='DELETE' OR(TG_OP='UPDATE' AND TG_TABLE_NAME<>'customer_partial_return_plans') THEN
  RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='customer_partial_return_owner',MESSAGE='Partial credit history is immutable'; END IF;
 IF TG_TABLE_NAME='customer_partial_return_sources' THEN
  IF NEW.created_actor_id IS DISTINCT FROM a OR NOT reconforge.customer_return_authority(NEW.tenant_id,a,'prepare')
  OR NEW.source_payload->'original_source' IS DISTINCT FROM reconforge.customer_partial_return_native_source(NEW.tenant_id,NEW.source_order_id) THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='customer_partial_return_owner',MESSAGE='Partial source requires current scoped human preparation'; END IF;
 ELSIF TG_TABLE_NAME='customer_partial_return_plans' THEN
  SELECT * INTO s FROM reconforge.customer_partial_return_sources WHERE tenant_id=NEW.tenant_id AND id=NEW.source_id;
  IF s IS NULL OR(NEW.workspace_id,NEW.organization_id,NEW.legal_entity_id,NEW.source_order_id,NEW.invoice_id)
    IS DISTINCT FROM(s.workspace_id,s.organization_id,s.legal_entity_id,s.source_order_id,s.invoice_id) THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='customer_partial_return_owner',MESSAGE='Partial plan must preserve native source hierarchy'; END IF;
  IF TG_OP='INSERT' AND(NEW.phase<>0 OR NEW.preparer_actor_id IS DISTINCT FROM a OR NOT reconforge.customer_return_authority(NEW.tenant_id,a,'prepare')) THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='customer_partial_return_owner',MESSAGE='Partial credit must be born Prepared'; END IF;
  IF TG_OP='UPDATE' AND((to_jsonb(NEW)-'phase') IS DISTINCT FROM(to_jsonb(OLD)-'phase')
   OR NOT((OLD.phase=0 AND NEW.phase=1) OR(OLD.phase=1 AND NEW.phase=2) OR(OLD.phase IN(0,1) AND NEW.phase=3))) THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='customer_partial_return_owner',MESSAGE='Partial plan transition cannot rewrite original intent'; END IF;
 ELSIF TG_TABLE_NAME IN('customer_partial_return_events','customer_partial_return_commands') THEN
  SELECT * INTO p FROM reconforge.customer_partial_return_plans WHERE tenant_id=NEW.tenant_id AND id=NEW.plan_id;
  op:=CASE WHEN NEW.operation IN('prepare_refund','prepare_reversal') THEN'prepare' ELSE NEW.operation END;
  IF p IS NULL OR NEW.actor_id IS DISTINCT FROM a OR NOT reconforge.customer_return_authority(NEW.tenant_id,a,op) THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='customer_partial_return_owner',MESSAGE='Partial lifecycle requires current human authority'; END IF;
 ELSIF TG_TABLE_NAME='customer_partial_return_history' THEN
  IF NEW.kind='Collection' THEN
   IF NOT reconforge.customer_partial_return_collection_admitted(NEW.tenant_id,NEW.source_id,NEW.receipt_id,NEW.allocation_id) THEN
    RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='customer_partial_return_owner',MESSAGE='Collection history requires the current native cash poster'; END IF;
  ELSIF NOT reconforge.customer_return_authority(NEW.tenant_id,a,'post') THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='customer_partial_return_owner',MESSAGE='Partial history requires current post authority';
  END IF;
 ELSE
  SELECT * INTO s FROM reconforge.customer_partial_return_sources WHERE tenant_id=NEW.tenant_id AND id=NEW.source_id;
  IF s IS NULL OR NOT reconforge.customer_return_authority(NEW.tenant_id,a,'post') THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='customer_partial_return_owner',MESSAGE='Native correction requires current post authority'; END IF;
  IF NEW.consumption_count_at_restore IS DISTINCT FROM(SELECT count(*) FROM reconforge.inventory_layer_consumptions
    WHERE tenant_id=NEW.tenant_id AND cost_layer_id=NEW.cost_layer_id)
   OR(NEW.direction=-1 AND NOT EXISTS(SELECT 1 FROM reconforge.customer_partial_return_restorations original
    WHERE original.tenant_id=NEW.tenant_id AND original.plan_id=NEW.original_restoration_plan_id AND original.position=NEW.position
    AND original.direction=1 AND original.cost_layer_id=NEW.cost_layer_id
    AND original.consumption_count_at_restore=NEW.consumption_count_at_restore)) THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='customer_partial_return_owner',MESSAGE='Restore witness must retain exact native consumption membership'; END IF;
 END IF;
 RETURN NEW;
END $cr2$;
DO $cr2$ DECLARE n TEXT;BEGIN
 FOREACH n IN ARRAY ARRAY['customer_partial_return_sources','customer_partial_return_plans','customer_partial_return_events',
 'customer_partial_return_history','customer_partial_return_restorations','customer_partial_return_commands'] LOOP
  EXECUTE format('ALTER TABLE reconforge.%I ENABLE ROW LEVEL SECURITY',n);
  EXECUTE format('ALTER TABLE reconforge.%I FORCE ROW LEVEL SECURITY',n);
  IF n IN('customer_partial_return_sources','customer_partial_return_plans') THEN
   EXECUTE format('CREATE POLICY scope ON reconforge.%I USING(reconforge.irp_scope(tenant_id,workspace_id,organization_id,legal_entity_id)) WITH CHECK(reconforge.irp_scope(tenant_id,workspace_id,organization_id,legal_entity_id))',n);
  ELSIF n IN('customer_partial_return_history','customer_partial_return_restorations') THEN
   EXECUTE format('CREATE POLICY scope ON reconforge.%I USING(EXISTS(SELECT 1 FROM reconforge.customer_partial_return_sources s WHERE s.tenant_id=%I.tenant_id AND s.id=%I.source_id)) WITH CHECK(EXISTS(SELECT 1 FROM reconforge.customer_partial_return_sources s WHERE s.tenant_id=%I.tenant_id AND s.id=%I.source_id))',n,n,n,n,n);
  ELSE
   EXECUTE format('CREATE POLICY scope ON reconforge.%I USING(EXISTS(SELECT 1 FROM reconforge.customer_partial_return_plans p WHERE p.tenant_id=%I.tenant_id AND p.id=%I.plan_id)) WITH CHECK(EXISTS(SELECT 1 FROM reconforge.customer_partial_return_plans p WHERE p.tenant_id=%I.tenant_id AND p.id=%I.plan_id))',n,n,n,n,n);
  END IF;
  EXECUTE format('CREATE TRIGGER immutable BEFORE INSERT OR UPDATE OR DELETE ON reconforge.%I FOR EACH ROW EXECUTE FUNCTION reconforge.customer_partial_return_protect()',n);
 END LOOP;
END $cr2$;
"""

CLOSURE_SQL = r"""
CREATE FUNCTION reconforge.customer_partial_return_balance(t TEXT,i TEXT) RETURNS JSONB LANGUAGE plpgsql VOLATILE SET search_path=pg_catalog AS $cr2$
DECLARE s RECORD;h RECORD;c NUMERIC;p NUMERIC;f NUMERIC;q NUMERIC;v INTEGER;chain TEXT;
BEGIN
 SELECT * INTO s FROM reconforge.customer_partial_return_sources WHERE tenant_id=t AND id=i;
 IF s IS NULL THEN RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='customer_partial_return_owner',MESSAGE='Partial source directory is absent or hidden'; END IF;
 SELECT COALESCE(sum(CASE kind WHEN'Collection' THEN amount_minor ELSE 0 END),0)::bigint collections,
 COALESCE(sum(CASE kind WHEN'Return' THEN credit_minor WHEN'ReverseReturn' THEN-credit_minor ELSE 0 END),0)::bigint credits,
 COALESCE(sum(CASE kind WHEN'Refund' THEN amount_minor WHEN'ReverseRefund' THEN-amount_minor ELSE 0 END),0)::bigint refunds,
 COALESCE(sum(CASE kind WHEN'Return' THEN quantity_scaled WHEN'ReverseReturn' THEN-quantity_scaled ELSE 0 END),0)::bigint quantities,
 count(*)::integer version INTO h FROM reconforge.customer_partial_return_history WHERE tenant_id=t AND source_id=i;
 c:=s.initial_collected_minor+h.collections;p:=h.credits;f:=h.refunds;q:=h.quantities;v:=h.version;
 SELECT event_digest INTO chain FROM reconforge.customer_partial_return_history WHERE tenant_id=t AND source_id=i ORDER BY sequence DESC LIMIT 1;
 RETURN jsonb_build_object('source_id',i,'source_order_id',s.source_order_id,'workspace_id',s.workspace_id,'organization_id',s.organization_id,
 'legal_entity_id',s.legal_entity_id,'source_fingerprint',s.source_fingerprint,'gross_minor',s.gross_minor,'collected_minor',c,
 'credited_minor',p,'returned_quantity_scaled',q,'remaining_quantity_scaled',s.original_quantity_scaled-q,'quantity_precision',s.quantity_precision,
 'refund_entitlement_minor',greatest(p+c-s.gross_minor,0),'refunded_minor',f,'refund_due_minor',greatest(p+c-s.gross_minor,0)-f,
 'outstanding_minor',greatest(s.gross_minor-p-c,0),'history_version',v,'history_fingerprint',COALESCE(chain,
 reconforge.irp_digest(jsonb_build_object('contract','customer-partial-return-domain-v1','source',s.source_fingerprint))),
 'currency_code',s.currency_code,'currency_precision',s.currency_precision,'currency_rounding_policy',s.currency_rounding_policy,
 'currency_registry_version',s.currency_registry_version,'currency_registry_digest',s.currency_registry_digest,
 'active_plan_id',(SELECT id FROM reconforge.customer_partial_return_plans WHERE tenant_id=t AND source_id=i AND phase IN(0,1)));
END $cr2$;
CREATE FUNCTION reconforge.customer_partial_return_public(t TEXT,i TEXT,selected_phase INTEGER DEFAULT NULL) RETURNS JSONB LANGUAGE plpgsql STABLE SET search_path=pg_catalog AS $cr2$
DECLARE p RECORD;r RECORD;l RECORD;stage INTEGER;result JSONB;
BEGIN
 SELECT * INTO p FROM reconforge.customer_partial_return_plans WHERE tenant_id=t AND id=i;
 IF p IS NULL THEN RETURN NULL; END IF;
 SELECT * INTO r FROM reconforge.customer_partial_return_events WHERE tenant_id=t AND plan_id=i AND operation='review';
 SELECT * INTO l FROM reconforge.customer_partial_return_events WHERE tenant_id=t AND plan_id=i AND operation='post';
 stage:=COALESCE(selected_phase,p.phase);
 SELECT jsonb_object_agg(key,value) INTO result FROM jsonb_each(p.payload) WHERE key=ANY(ARRAY[
 'schema_version','id','operation','plan_digest','source_id','source_order_id','invoice_id','workspace_id','organization_id','legal_entity_id',
 'quantity_precision','quantity_scaled','credit_minor','cogs_restored_minor','receivable_released_minor','refund_entitlement_delta_minor',
 'amount_minor','currency_code','currency_precision','currency_rounding_policy','currency_registry_version','currency_registry_digest',
 'expected_history_version','posting_date','period_id','preparer_actor_id','original_id']);
 result:=result||jsonb_build_object('phase',stage,'status',(ARRAY['Prepared','Reviewed','Posted','Cancelled'])[stage+1],
 'reviewer_actor_id',CASE WHEN stage<>0 THEN r.actor_id ELSE NULL END,'poster_actor_id',CASE WHEN stage=2 THEN l.actor_id ELSE NULL END,
 'audit_event_id',p.audit_event_id,'outbox_event_id',p.outbox_event_id,
 'entries',COALESCE((SELECT jsonb_agg(jsonb_build_object('entry_id',x->>'entry_id','purpose',x->>'purpose',
 'validation_digest',x->>'validation_digest','posting_effect_id',CASE WHEN stage=2 THEN l.effects->>(n-1)::integer ELSE NULL END) ORDER BY n)
 FROM jsonb_array_elements(p.payload->'entries') WITH ORDINALITY AS a(x,n)),'[]'::jsonb));
 RETURN result;
END $cr2$;
CREATE FUNCTION reconforge.customer_partial_return_source_close(t TEXT,i TEXT) RETURNS VOID LANGUAGE plpgsql SET search_path=pg_catalog AS $cr2$
DECLARE s RECORD;h RECORD;p RECORD;a RECORD;e RECORD;c RECORD;row JSONB;original JSONB;current_source JSONB;chain TEXT;
 stack INTEGER[]:='{}';q NUMERIC:=0;credit NUMERIC:=0;cash NUMERIC;refund NUMERIC:=0;cost NUMERIC:=0;liability NUMERIC:=0;
 ordinal INTEGER:=0;take NUMERIC;skip NUMERIC;pending NUMERIC;amount NUMERIC;portion JSONB;cons JSONB;position INTEGER;allocation JSONB;native RECORD;fp JSONB;
BEGIN
 SELECT * INTO s FROM reconforge.customer_partial_return_sources WHERE tenant_id=t AND id=i;
 IF s IS NULL THEN RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='customer_partial_return_owner',MESSAGE='Partial source owner is absent or hidden'; END IF;
 original:=s.source_payload->'original_source';current_source:=reconforge.customer_partial_return_native_source(t,s.source_order_id);
 IF current_source IS NULL OR NOT reconforge.irp_scope(t,s.workspace_id,s.organization_id,s.legal_entity_id)
 OR(current_source-ARRAY['invoice_status','invoice_version','allocated_minor']) IS DISTINCT FROM(original-ARRAY['invoice_status','invoice_version','allocated_minor'])
 OR s.source_fingerprint IS DISTINCT FROM reconforge.irp_digest(s.source_payload->'fingerprint_payload')
 OR(s.workspace_id,s.organization_id,s.legal_entity_id,s.invoice_id,s.customer_id,s.item_id,s.location_id,s.uom_id, s.original_valuation_document_id,
 s.original_cogs_effect_id,s.original_revenue_effect_id) IS DISTINCT FROM(original->'stock'->>'workspace_id',original->'stock'->>'organization_id',
 original->'stock'->>'legal_entity_id',original->'invoice'->>'id',original->'stock'->>'customer_id',original->'stock'->>'item_id',
 original->'stock'->>'location_id',original->'stock'->>'uom_id',original->'stock'->>'valuation_id',original->'cogs'->>'id',original->'revenue'->>'id')
 OR(s.gross_minor,s.initial_collected_minor,s.original_quantity_scaled,s.quantity_precision) IS DISTINCT FROM
 ((original->'invoice'->>'total_minor')::bigint,(original->>'allocated_minor')::bigint,(original->'stock'->>'quantity_scaled')::bigint,
 (original->'stock'->>'quantity_precision')::integer)
 OR(s.currency_code,s.currency_precision,s.currency_rounding_policy,s.currency_registry_version,s.currency_registry_digest) IS DISTINCT FROM
 (original->'invoice'->>'currency_code',(original->'invoice'->>'currency_precision')::integer,original->'invoice'->>'currency_rounding_policy',
 original->'invoice'->>'currency_registry_version',original->'invoice'->>'currency_registry_digest')
 OR(original->'invoice'->>'tax_minor')::bigint<>0 OR original->'stock'->>'status' NOT IN('Invoiced','Paid')
 OR original->>'invoice_status' NOT IN('Approved','PartiallyPaid','Paid')
 OR EXISTS(SELECT 1 FROM reconforge.customer_return_plans WHERE tenant_id=t AND source_order_id=s.source_order_id AND operation='Return' AND phase<>3)
 OR NOT EXISTS(SELECT 1 FROM reconforge.customer_partial_return_plans WHERE tenant_id=t AND source_id=i)
 OR NOT EXISTS(SELECT 1 FROM reconforge.ar_invoices WHERE tenant_id=t AND id=s.invoice_id AND customer_partial_return_source_id=i) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='customer_partial_return_owner',MESSAGE='Partial source must conserve original native document and monetary evidence'; END IF;
 fp:=s.source_payload->'fingerprint_payload';
 FOREACH chain IN ARRAY ARRAY['quantity_precision','quantity_scaled','gross_minor','collected_minor','net_unit_price_minor','tax_minor'] LOOP
  IF jsonb_typeof(fp->chain) IS DISTINCT FROM'number' OR(fp->>chain)!~'^(0|[1-9][0-9]*)$'
  OR fp->chain IS DISTINCT FROM s.source_payload->'typed_source'->chain THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='customer_partial_return_owner',MESSAGE='Original financial and quantity facts require exact integer metadata'; END IF;
 END LOOP;
 IF s.source_payload->'typed_source'->'scope' IS DISTINCT FROM fp->'scope'
 OR(s.source_payload->'typed_source'->>'source_order_id',s.source_payload->'typed_source'->>'invoice_id',s.source_payload->'typed_source'->>'valuation_document_id',
 s.source_payload->'typed_source'->>'original_revenue_plan_id',s.source_payload->'typed_source'->>'functional_currency',s.source_payload->'typed_source'->>'base_uom_id')
 IS DISTINCT FROM(s.source_order_id,s.invoice_id,s.original_valuation_document_id,original->'stock'->>'invoice_plan_id',s.currency_code,s.uom_id)
 OR s.source_payload->'typed_source'->'currency_policy' IS DISTINCT FROM jsonb_build_object('currency_code',s.currency_code,'precision',s.currency_precision,
 'rounding_policy',s.currency_rounding_policy,'registry_version',s.currency_registry_version,'registry_digest',s.currency_registry_digest)
 OR s.source_payload->'typed_source'->'inventory_lot_id' IS DISTINCT FROM'null'::jsonb
 OR s.source_payload->'typed_source'->'serial_tracked' IS DISTINCT FROM'false'::jsonb
 OR NOT EXISTS(SELECT 1 FROM reconforge.currency_registry_snapshots WHERE tenant_id=t AND registry_digest=s.currency_registry_digest
  AND registry_version=s.currency_registry_version AND snapshot_json::jsonb=s.source_payload->'registry_snapshot') THEN
  RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='customer_partial_return_owner',MESSAGE='Typed original source requires its exact retained native registry and hierarchy'; END IF;
 FOREACH chain IN ARRAY ARRAY['cogs','revenue'] LOOP
  IF s.source_payload->'typed_source'->('original_'||chain) IS DISTINCT FROM jsonb_build_object(
   'posting_effect_id',original->chain->>'id','scope',fp->'scope','snapshot_json',reconforge.irp_canonical(original->chain->'snapshot_json'),
   'validation_digest',original->chain->>'validation_digest') THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='customer_partial_return_owner',MESSAGE='Original typed finance evidence must match its native immutable effect'; END IF;
 END LOOP;
 IF NOT EXISTS(SELECT 1 FROM reconforge.legal_entities entity_record JOIN reconforge.organizations organization_record
  ON(organization_record.tenant_id,organization_record.id)=(entity_record.tenant_id,entity_record.organization_id)
  WHERE entity_record.tenant_id=t AND entity_record.id=s.legal_entity_id AND entity_record.organization_id=s.organization_id
  AND organization_record.application_workspace_id=s.workspace_id AND entity_record.currency_code=s.currency_code)
 OR NOT EXISTS(SELECT 1 FROM reconforge.inventory_items WHERE tenant_id=t AND id=s.item_id AND workspace_id=s.workspace_id
  AND(organization_id IS NULL OR organization_id=s.organization_id) AND item_type IN('Stock','Consumable') AND tracking_mode='None' AND uom_id=s.uom_id) THEN
  RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='customer_partial_return_owner',MESSAGE='First partial scope requires functional currency untracked original base UOM'; END IF;
 IF fp->>'contract' IS DISTINCT FROM'customer-partial-return-domain-v1'
 OR fp->'scope' IS DISTINCT FROM jsonb_build_object('tenant_id',t,'workspace_id',s.workspace_id,'organization_id',s.organization_id,
 'legal_entity_id',s.legal_entity_id,'item_id',s.item_id,'location_id',s.location_id,'uom_id',s.uom_id)
 OR(fp->>'source_order_id',fp->>'invoice_id',fp->>'valuation_document_id',fp->>'original_revenue_plan_id',fp->>'currency',fp->>'functional_currency',fp->>'base_uom_id')
 IS DISTINCT FROM(s.source_order_id,s.invoice_id,s.original_valuation_document_id,original->'stock'->>'invoice_plan_id',s.currency_code,s.currency_code,s.uom_id)
 OR(fp->'quantity_precision',fp->'quantity_scaled',fp->'gross_minor',fp->'collected_minor',fp->'net_unit_price_minor') IS DISTINCT FROM
 (to_jsonb(s.quantity_precision),to_jsonb(s.original_quantity_scaled),to_jsonb(s.gross_minor),to_jsonb(s.initial_collected_minor),original->'stock'->'source'->'net_unit_price_minor')
 OR fp->'tax_minor' IS DISTINCT FROM'0'::jsonb OR fp->'inventory_lot_id' IS DISTINCT FROM'null'::jsonb OR fp->'serial_tracked' IS DISTINCT FROM'false'::jsonb
 OR fp->'original_cogs' IS DISTINCT FROM jsonb_build_array(s.original_cogs_effect_id,original->'cogs'->>'validation_digest')
 OR fp->'original_revenue' IS DISTINCT FROM jsonb_build_array(s.original_revenue_effect_id,original->'revenue'->>'validation_digest')
 OR fp->'policy' IS DISTINCT FROM jsonb_build_object('currency_precision',s.currency_precision,'currency_rounding_policy',s.currency_rounding_policy,
 'currency_registry_version',s.currency_registry_version,'currency_registry_digest',s.currency_registry_digest)
 OR fp->'consumptions' IS DISTINCT FROM s.source_payload->'typed_source'->'consumptions'
 OR jsonb_typeof(fp->'consumptions') IS DISTINCT FROM'array' OR jsonb_array_length(fp->'consumptions') NOT BETWEEN 1 AND 32
 OR jsonb_array_length(fp->'consumptions')<>jsonb_array_length(original->'stock'->'issue_plan'->'allocations')
 OR jsonb_array_length(fp->'consumptions')<>jsonb_array_length(original->'consumptions') THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='customer_partial_return_owner',MESSAGE='Typed original source must bind exact native monetary and FIFO identities'; END IF;
 position:=0;
 FOR cons IN SELECT * FROM jsonb_array_elements(fp->'consumptions') LOOP
  allocation:=original->'stock'->'issue_plan'->'allocations'->position;position:=position+1;
  SELECT consumed_original.*,valuation_detail.valuation_document_id,cost_layer.item_id,cost_layer.uom_id,cost_layer.legal_entity_id,
   cost_layer.inventory_lot_id,cost_layer.quantity_precision INTO native
  FROM reconforge.inventory_layer_consumptions consumed_original JOIN reconforge.inventory_valuation_lines valuation_detail
  ON(valuation_detail.tenant_id,valuation_detail.id)=(consumed_original.tenant_id,consumed_original.valuation_line_id)
  JOIN reconforge.inventory_cost_layers cost_layer ON(cost_layer.tenant_id,cost_layer.id)=(consumed_original.tenant_id,consumed_original.cost_layer_id)
  WHERE consumed_original.tenant_id=t AND consumed_original.id=cons->>'consumption_id';
  IF native IS NULL OR cons->'scope' IS DISTINCT FROM fp->'scope' OR cons->'position' IS DISTINCT FROM to_jsonb(position)
  OR cons->>'currency_code' IS DISTINCT FROM s.currency_code OR cons->'quantity_precision' IS DISTINCT FROM to_jsonb(s.quantity_precision)
  OR(native.workspace_id,native.legal_entity_id,native.item_id,native.uom_id,native.valuation_document_id)
   IS DISTINCT FROM(s.workspace_id,s.legal_entity_id,s.item_id,s.uom_id,s.original_valuation_document_id)
  OR native.inventory_lot_id IS NOT NULL OR native.quantity_precision<>s.quantity_precision
  OR cons->>'valuation_line_id' IS DISTINCT FROM native.valuation_line_id OR cons->>'cost_layer_id' IS DISTINCT FROM native.cost_layer_id
  OR cons->'quantity_scaled' IS DISTINCT FROM to_jsonb(native.quantity_scaled) OR cons->'value_minor' IS DISTINCT FROM to_jsonb(native.value_minor)
  OR allocation->>'cost_layer_id' IS DISTINCT FROM native.cost_layer_id OR allocation->'quantity_scaled' IS DISTINCT FROM to_jsonb(native.quantity_scaled)
  OR allocation->'value_minor' IS DISTINCT FROM to_jsonb(native.value_minor) THEN
  RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='customer_partial_return_owner',MESSAGE='Original consumption order must match reviewed issue and native source membership'; END IF;
  FOREACH chain IN ARRAY ARRAY['position','quantity_precision','quantity_scaled','value_minor'] LOOP
   IF jsonb_typeof(cons->chain) IS DISTINCT FROM'number' OR(cons->>chain)!~'^(0|[1-9][0-9]*)$' THEN
    RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='customer_partial_return_owner',MESSAGE='Original FIFO facts require integer metadata'; END IF;
  END LOOP;
 END LOOP;
 FOR a IN SELECT x.*,to_jsonb(r) receipt FROM reconforge.ar_receipt_allocations x JOIN reconforge.ar_receipts r
 ON(r.tenant_id,r.id)=(x.tenant_id,x.receipt_id) WHERE x.tenant_id=t AND x.invoice_id=s.invoice_id LOOP
  SELECT count(*) INTO position FROM(
   SELECT cash_plan.entry_id,cash_link.posting_effect_id,cash_link.posted_actor_id,cash_plan.payload->'snapshot' snapshot,cash_plan.payload->>'validation_digest' seal
   FROM reconforge.commercial_collection_plans cash_plan JOIN reconforge.commercial_collection_links cash_link
   ON(cash_link.tenant_id,cash_link.plan_id)=(cash_plan.tenant_id,cash_plan.id)
   WHERE cash_plan.tenant_id=t AND cash_plan.source_id=s.invoice_id AND cash_plan.phase=2 AND cash_link.receipt_id=a.receipt_id
   UNION ALL SELECT legacy_plan.entry_id,legacy_link.posting_effect_id,legacy_link.posted_actor_id,legacy_plan.payload->'snapshot',legacy_plan.validation_digest
   FROM reconforge.operational_finance_plans legacy_plan JOIN reconforge.operational_finance_links legacy_link
   ON(legacy_link.tenant_id,legacy_link.plan_id)=(legacy_plan.tenant_id,legacy_plan.id)
   WHERE legacy_plan.tenant_id=t AND legacy_plan.id=original->'stock'->>'collection_plan_id' AND legacy_plan.source_kind='ARReceipt' AND legacy_plan.source_id=s.invoice_id
   AND legacy_link.source_effect_id=a.receipt_id) owner JOIN reconforge.finance_posting_effects cash_effect
   ON(cash_effect.tenant_id,cash_effect.id,cash_effect.entry_id)=(t,owner.posting_effect_id,owner.entry_id)
   WHERE cash_effect.snapshot_json=owner.snapshot AND cash_effect.validation_digest=owner.seal AND cash_effect.posted_actor_id=owner.posted_actor_id
   AND cash_effect.snapshot_json->'lines'->0->>'account_id'=s.cash_account_id
   AND cash_effect.snapshot_json->'lines'->0->'dimensions'=s.source_payload->'cash_dimensions'
   AND cash_effect.snapshot_json->'lines'->1->>'account_id'=original->'revenue'->'snapshot_json'->'lines'->0->>'account_id'
   AND cash_effect.snapshot_json->'lines'->1->'dimensions'=original->'revenue'->'snapshot_json'->'lines'->0->'dimensions'
   AND(cash_effect.snapshot_json->'lines'->0->>'debit_minor')::bigint=(a.receipt->>'amount_minor')::bigint
   AND(cash_effect.snapshot_json->'lines'->1->>'credit_minor')::bigint=(a.receipt->>'amount_minor')::bigint
   AND jsonb_array_length(cash_effect.snapshot_json->'lines')=2;
  IF position<>1 OR a.receipt->>'status'<>'Posted' OR a.receipt->>'customer_id' IS DISTINCT FROM s.customer_id
  OR(a.receipt->>'workspace_id',a.receipt->>'organization_id',a.receipt->>'legal_entity_id',a.receipt->>'currency_code',
  (a.receipt->>'currency_precision')::integer,a.receipt->>'currency_rounding_policy',a.receipt->>'currency_registry_version',a.receipt->>'currency_registry_digest')
  IS DISTINCT FROM(s.workspace_id,s.organization_id,s.legal_entity_id,s.currency_code,s.currency_precision,s.currency_rounding_policy,s.currency_registry_version,s.currency_registry_digest) THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='customer_partial_return_owner',MESSAGE='Every collected amount requires exact native receipt cash effect and retained source account membership'; END IF;
 END LOOP;
 chain:=reconforge.irp_digest(jsonb_build_object('contract','customer-partial-return-domain-v1','source',s.source_fingerprint));cash:=s.initial_collected_minor;
 FOR h IN SELECT * FROM reconforge.customer_partial_return_history WHERE tenant_id=t AND source_id=i ORDER BY sequence LOOP
  ordinal:=ordinal+1;row:=h.payload;
  IF h.sequence<>ordinal OR row->>'kind' IS DISTINCT FROM h.kind OR(row->>'sequence')::integer<>ordinal
  OR row->>'source_fingerprint' IS DISTINCT FROM s.source_fingerprint OR row->>'previous_history_fingerprint' IS DISTINCT FROM chain
  OR h.previous_digest IS DISTINCT FROM chain OR h.event_digest IS DISTINCT FROM reconforge.irp_digest(jsonb_build_object('previous',chain,'event',row))
  OR(row->>'amount_minor')::bigint IS DISTINCT FROM h.amount_minor THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='customer_partial_return_owner',MESSAGE='Partial economics require contiguous immutable source-owned history'; END IF;
  IF h.kind='Collection' THEN
   IF h.amount_minor>greatest(s.gross_minor-credit-cash,0) OR row->'return_values'<>'null'::jsonb OR row->'original_sequence'<>'null'::jsonb
   OR NOT EXISTS(SELECT 1 FROM reconforge.ar_receipt_allocations x JOIN reconforge.ar_receipts r ON(r.tenant_id,r.id)=(x.tenant_id,x.receipt_id)
    WHERE x.tenant_id=t AND x.id=h.allocation_id AND x.invoice_id=s.invoice_id AND x.receipt_id=h.receipt_id AND x.amount_minor>=h.amount_minor
    AND r.status='Posted' AND r.customer_id=s.customer_id AND r.currency_code=s.currency_code) THEN
    RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='customer_partial_return_owner',MESSAGE='Collection history requires its actual current native receipt allocation and prefix cap'; END IF;
   cash:=cash+h.amount_minor;stack:=array_append(stack,h.sequence);
  ELSE
   SELECT * INTO p FROM reconforge.customer_partial_return_plans WHERE tenant_id=t AND id=h.plan_id;
   IF p IS NULL OR p.source_id<>i OR p.phase<>2 OR p.operation<>h.kind OR p.expected_history_version<>ordinal-1 THEN
    RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='customer_partial_return_owner',MESSAGE='Economic history requires its exact posted source plan'; END IF;
   IF h.kind='Return' THEN
    IF p.quantity_scaled>s.original_quantity_scaled-q OR p.credit_minor::numeric*s.original_quantity_scaled<>s.gross_minor::numeric*p.quantity_scaled
    OR p.receivable_released_minor<>least(p.credit_minor,greatest(s.gross_minor-credit-cash,0))
    OR p.refund_entitlement_delta_minor<>p.credit_minor-p.receivable_released_minor
    OR(h.quantity_scaled,h.credit_minor,h.cogs_minor) IS DISTINCT FROM(p.quantity_scaled,p.credit_minor,p.cogs_restored_minor)
    OR row->'return_values' IS DISTINCT FROM((p.payload->'domain_plan')-ARRAY['schema_version','source_fingerprint','history_fingerprint','expected_version']) THEN
     RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='customer_partial_return_owner',MESSAGE='Posted partial credit must conserve original quantity and prefix AR economics'; END IF;
    skip:=q;pending:=p.quantity_scaled;amount:=0;position:=0;
    FOR cons IN SELECT * FROM jsonb_array_elements(s.source_payload->'typed_source'->'consumptions') LOOP
     position:=position+1;take:=least(pending,(cons->>'quantity_scaled')::numeric-least(skip,(cons->>'quantity_scaled')::numeric));
     IF take>0 THEN
      SELECT value INTO portion FROM jsonb_array_elements(p.payload->'domain_plan'->'portions') value WHERE(value->>'position')::integer=position;
      IF portion IS NULL OR portion->>'original_consumption_id' IS DISTINCT FROM cons->>'consumption_id'
      OR portion->>'cost_layer_id' IS DISTINCT FROM cons->>'cost_layer_id' OR portion->>'original_valuation_line_id' IS DISTINCT FROM cons->>'valuation_line_id'
      OR(portion->>'quantity_scaled')::numeric<>take OR(portion->>'offset_quantity_scaled')::numeric<>least(skip,(cons->>'quantity_scaled')::numeric)
      OR(portion->>'value_minor')::numeric*(cons->>'quantity_scaled')::numeric<>(cons->>'value_minor')::numeric*take THEN
       RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='customer_partial_return_owner',MESSAGE='Partial cost must follow the exact original reviewed FIFO prefix'; END IF;
      amount:=amount+(portion->>'value_minor')::numeric;pending:=pending-take;
     END IF;
     skip:=greatest(skip-(cons->>'quantity_scaled')::numeric,0);
    END LOOP;
    IF pending<>0 OR amount<>p.cogs_restored_minor THEN RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='customer_partial_return_owner',MESSAGE='Partial FIFO restitution must conserve original cost'; END IF;
    q:=q+p.quantity_scaled;credit:=credit+p.credit_minor;cost:=cost+p.cogs_restored_minor;liability:=liability+p.refund_entitlement_delta_minor;
    stack:=array_append(stack,h.sequence);
   ELSIF h.kind='Refund' THEN
    IF h.amount_minor<>p.amount_minor OR h.amount_minor>liability-refund OR row->'return_values'<>'null'::jsonb THEN
     RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='customer_partial_return_owner',MESSAGE='Refund exceeds the retained source liability'; END IF;
    refund:=refund+h.amount_minor;stack:=array_append(stack,h.sequence);
   ELSE
    SELECT * INTO e FROM reconforge.customer_partial_return_history WHERE tenant_id=t AND source_id=i AND sequence=(row->>'original_sequence')::integer;
    IF e IS NULL OR cardinality(stack)=0 OR stack[cardinality(stack)]<>e.sequence OR e.plan_id<>p.original_id OR h.kind<>'Reverse'||e.kind
    OR(row-'kind'-'sequence'-'source_fingerprint'-'previous_history_fingerprint'-'original_sequence') IS DISTINCT FROM
     (e.payload-'kind'-'sequence'-'source_fingerprint'-'previous_history_fingerprint'-'original_sequence') THEN
     RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='customer_partial_return_owner',MESSAGE='Reversal requires the exact latest unreversed economic operation'; END IF;
    stack:=stack[1:cardinality(stack)-1];
    IF h.kind='ReverseRefund' THEN refund:=refund-h.amount_minor;
    ELSE q:=q-p.quantity_scaled;credit:=credit-p.credit_minor;cost:=cost-p.cogs_restored_minor;liability:=liability-p.refund_entitlement_delta_minor;
     IF liability<refund THEN RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='customer_partial_return_owner',MESSAGE='Reverse the refund before its credited liability'; END IF;
    END IF;
   END IF;
  END IF;
  chain:=h.event_digest;
 END LOOP;
 IF cash<>(SELECT COALESCE(sum(amount_minor),0) FROM reconforge.ar_receipt_allocations WHERE tenant_id=t AND invoice_id=s.invoice_id)
 OR q<0 OR q>s.original_quantity_scaled OR credit<0 OR credit>s.gross_minor OR refund<0 OR refund>liability THEN
  RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='customer_partial_return_owner',MESSAGE='Partial history and actual allocation membership must agree'; END IF;
 IF NOT EXISTS(SELECT 1 FROM reconforge.ar_invoices WHERE tenant_id=t AND id=s.invoice_id
 AND status=CASE WHEN cash+credit>=s.gross_minor THEN'Paid' WHEN cash+credit>0 THEN'PartiallyPaid' ELSE'Approved' END) THEN
  RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='customer_partial_return_owner',MESSAGE='Actual invoice status must agree with net credits and native collections'; END IF;
END $cr2$;
"""

PLAN_SQL = r"""
CREATE FUNCTION reconforge.customer_partial_return_close(t TEXT,i TEXT) RETURNS VOID LANGUAGE plpgsql SET search_path=pg_catalog AS $cr2$
DECLARE p RECORD;s RECORD;r RECORD;l RECORD;c RECORD;e RECORD;f RECORD;v RECORD;o RECORD;command RECORD;
 part JSONB;oldpart JSONB;original JSONB;line JSONB;expected JSONB;metadata JSONB;maker TEXT;ordinal INTEGER:=0;stage INTEGER;
 ar JSONB;revenue JSONB;inventory JSONB;cogs JSONB;debit NUMERIC;credit NUMERIC;restoration_count INTEGER;entry_number TEXT;entry_identity TEXT;
BEGIN
 SELECT * INTO p FROM reconforge.customer_partial_return_plans WHERE tenant_id=t AND id=i;
 IF p IS NULL THEN RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='customer_partial_return_owner',MESSAGE='Partial plan owner is absent or hidden'; END IF;
 SELECT * INTO s FROM reconforge.customer_partial_return_sources WHERE tenant_id=t AND id=p.source_id;
 SELECT * INTO r FROM reconforge.customer_partial_return_events WHERE tenant_id=t AND plan_id=i AND operation='review';
 SELECT * INTO l FROM reconforge.customer_partial_return_events WHERE tenant_id=t AND plan_id=i AND operation='post';
 SELECT * INTO c FROM reconforge.customer_partial_return_events WHERE tenant_id=t AND plan_id=i AND operation='cancel';
 maker:=p.preparer_actor_id;
 IF s IS NULL OR reconforge.irp_digest(p.payload-'plan_digest') IS DISTINCT FROM p.plan_digest OR p.payload->>'plan_digest' IS DISTINCT FROM p.plan_digest
 OR p.payload->>'schema_version' IS DISTINCT FROM'customer-partial-return-v1'
 OR(p.payload->>'id',p.payload->>'operation',p.payload->>'source_id',p.payload->>'source_order_id',p.payload->>'invoice_id',p.payload->>'preparer_actor_id')
  IS DISTINCT FROM(p.id,p.operation,p.source_id,p.source_order_id,p.invoice_id,maker)
 OR(p.payload->>'amount_minor')::bigint IS DISTINCT FROM p.amount_minor OR(p.payload->>'quantity_scaled')::bigint IS DISTINCT FROM p.quantity_scaled
 OR(p.payload->>'credit_minor')::bigint IS DISTINCT FROM p.credit_minor OR(p.payload->>'cogs_restored_minor')::bigint IS DISTINCT FROM p.cogs_restored_minor
 OR(p.payload->>'receivable_released_minor')::bigint IS DISTINCT FROM p.receivable_released_minor
 OR(p.payload->>'refund_entitlement_delta_minor')::bigint IS DISTINCT FROM p.refund_entitlement_delta_minor
 OR(p.payload->>'expected_history_version')::integer IS DISTINCT FROM p.expected_history_version
 OR(p.payload->>'workspace_id',p.payload->>'organization_id',p.payload->>'legal_entity_id') IS DISTINCT FROM(s.workspace_id,s.organization_id,s.legal_entity_id)
 OR(p.phase=2) IS DISTINCT FROM(l IS NOT NULL) OR(p.phase=3) IS DISTINCT FROM(c IS NOT NULL)
 OR(p.phase IN(1,2) AND r IS NULL) OR(p.phase=0 AND r IS NOT NULL)
 OR NOT EXISTS(SELECT 1 FROM reconforge.domain_audit_events a JOIN reconforge.outbox_events b ON b.tenant_id=a.tenant_id
 WHERE a.tenant_id=t AND a.id=p.audit_event_id AND b.event_id=p.outbox_event_id AND a.actor_user_id=maker
 AND a.object_type='operational_finance' AND a.object_id=i AND a.action='customer_partial_return_prepared'
 AND a.metadata_json=jsonb_build_object('plan_digest',p.plan_digest) AND b.aggregate_type='operational_finance' AND b.aggregate_id=i
 AND b.event_type=a.action AND b.payload=a.metadata_json||jsonb_build_object('audit_event_id',a.id)
 AND(b.workspace_id,b.organization_id,b.legal_entity_id)=(s.workspace_id,s.organization_id,s.legal_entity_id)) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='customer_partial_return_owner',MESSAGE='Partial plan requires immutable scope intent audit and outbox'; END IF;
 IF p.original_id IS NOT NULL THEN
  SELECT * INTO o FROM reconforge.customer_partial_return_plans WHERE tenant_id=t AND id=p.original_id;
  IF o IS NULL OR o.source_id<>s.id OR o.phase<>2 OR o.operation IS DISTINCT FROM
   (CASE p.operation WHEN'Refund' THEN'Return' WHEN'ReverseReturn' THEN'Return' WHEN'ReverseRefund' THEN'Refund' ELSE NULL END) THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='customer_partial_return_owner',MESSAGE='Refund and reversal references require their exact posted original in the same native source'; END IF;
 END IF;
 ar:=s.source_payload->'original_source'->'revenue'->'snapshot_json'->'lines'->0;
 revenue:=s.source_payload->'original_source'->'revenue'->'snapshot_json'->'lines'->1;
 cogs:=s.source_payload->'original_source'->'cogs'->'snapshot_json'->'lines'->0;
 inventory:=s.source_payload->'original_source'->'cogs'->'snapshot_json'->'lines'->1;
 IF NOT EXISTS(SELECT 1 FROM reconforge.finance_accounts WHERE tenant_id=t AND id=s.refund_liability_account_id AND account_type='Liability' AND normal_balance='Credit')
 OR NOT EXISTS(SELECT 1 FROM reconforge.finance_accounts WHERE tenant_id=t AND id=s.cash_account_id AND account_type='Asset' AND normal_balance='Debit')
 OR jsonb_typeof(p.payload->'entries') IS DISTINCT FROM'array' OR jsonb_array_length(p.payload->'entries')<>(CASE WHEN p.operation IN('Return','ReverseReturn') THEN 2 ELSE 1 END) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='customer_partial_return_owner',MESSAGE='Partial correction requires exact native directional account roles'; END IF;
 FOR part IN SELECT * FROM jsonb_array_elements(p.payload->'entries') LOOP
  entry_number:=upper(p.id)||CASE WHEN p.operation='Refund' THEN'' WHEN ordinal=0 THEN'-R' ELSE'-C' END;
  entry_identity:='GLE-'||substr(encode(sha256(convert_to(btrim(s.workspace_id)||'|'||entry_number,'UTF8')),'hex'),1,16);
  SELECT * INTO e FROM reconforge.finance_entries WHERE tenant_id=t AND id=part->>'entry_id';
  SELECT * INTO f FROM reconforge.finance_posting_effects WHERE tenant_id=t AND entry_id=e.id;
  IF e IS NULL OR e.id IS DISTINCT FROM entry_identity OR e.entry_number IS DISTINCT FROM entry_number
  OR part->>'purpose' IS DISTINCT FROM(CASE p.operation WHEN'Return' THEN CASE ordinal WHEN 0 THEN'RevenueCredit' ELSE'CostRestoration' END
   WHEN'Refund' THEN'Refund' WHEN'ReverseReturn' THEN CASE ordinal WHEN 0 THEN'ReverseRevenueCredit' ELSE'ReverseCostRestoration' END ELSE'ReverseRefund' END)
  OR part->'snapshot' IS DISTINCT FROM reconforge.fr_snapshot(t,e.id,s.organization_id,s.legal_entity_id)
  OR part->>'validation_digest' IS DISTINCT FROM reconforge.irp_digest(part->'snapshot') OR e.preparer_actor_id IS DISTINCT FROM maker
  OR e.period_id IS DISTINCT FROM p.payload->>'period_id' OR e.posting_date IS DISTINCT FROM p.payload->>'posting_date'
  OR(e.currency_code,e.currency_precision,e.currency_rounding_policy,e.currency_registry_version,e.currency_registry_digest) IS DISTINCT FROM
   (s.currency_code,s.currency_precision,s.currency_rounding_policy,s.currency_registry_version,s.currency_registry_digest)
  OR e.status IS DISTINCT FROM(CASE WHEN p.phase=3 THEN'Voided' WHEN r IS NOT NULL THEN'Validated' ELSE'Draft' END)
  OR(r IS NOT NULL AND(e.validator_actor_id IS DISTINCT FROM r.actor_id OR e.validation_digest IS DISTINCT FROM part->>'validation_digest'))
  OR(p.phase=3 AND r IS NULL AND(e.validator_actor_id IS DISTINCT FROM c.actor_id OR e.validation_digest IS DISTINCT FROM part->>'validation_digest'))
  OR(p.phase=2) IS DISTINCT FROM(f.id IS NOT NULL)
  OR(f.id IS NOT NULL AND(f.id IS DISTINCT FROM l.effects->>ordinal OR f.posted_actor_id IS DISTINCT FROM l.actor_id OR f.snapshot_json IS DISTINCT FROM part->'snapshot')) THEN
  RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='customer_partial_return_owner',MESSAGE='Partial effect must preserve its exact reviewed entry and posting actor'; END IF;
  IF f.id IS NOT NULL AND EXISTS(SELECT 1 FROM reconforge.finance_entries inverse WHERE inverse.tenant_id=t AND inverse.reverses_posting_id=f.id
   AND NOT EXISTS(SELECT 1 FROM reconforge.customer_partial_return_plans owned WHERE owned.tenant_id=t AND owned.source_id=s.id
    AND owned.original_id=p.id AND owned.operation='Reverse'||p.operation
    AND EXISTS(SELECT 1 FROM jsonb_array_elements(owned.payload->'entries') pin WHERE pin->>'entry_id'=inverse.id
     AND pin->>'original_effect_id'=f.id AND pin->'snapshot'=reconforge.fr_snapshot(t,inverse.id,s.organization_id,s.legal_entity_id)))) THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='customer_partial_return_owner',MESSAGE='A partial effect inverse requires its exact new native correction owner'; END IF;
  IF p.operation LIKE'Reverse%' THEN
   SELECT * INTO o FROM reconforge.customer_partial_return_plans WHERE tenant_id=t AND id=p.original_id;
   oldpart:=o.payload->'entries'->ordinal;
   SELECT * INTO v FROM reconforge.finance_posting_effects WHERE tenant_id=t AND entry_id=oldpart->>'entry_id';
   IF o IS NULL OR o.phase<>2 OR o.source_id<>s.id OR p.operation<>'Reverse'||o.operation OR v IS NULL
   OR e.reverses_posting_id IS DISTINCT FROM v.id OR e.source_type<>'Generated'
   OR e.journal_id IS DISTINCT FROM oldpart->'snapshot'->'entry'->>'journal_id'
   OR part->>'original_effect_id' IS DISTINCT FROM v.id OR e.external_reference IS DISTINCT FROM v.id
   OR EXISTS((SELECT x->>'account_id',x->'credit_minor',x->'debit_minor',x->'dimensions' FROM jsonb_array_elements(oldpart->'snapshot'->'lines') x
    EXCEPT ALL SELECT x->>'account_id',x->'debit_minor',x->'credit_minor',x->'dimensions' FROM jsonb_array_elements(part->'snapshot'->'lines') x)
    UNION ALL(SELECT x->>'account_id',x->'debit_minor',x->'credit_minor',x->'dimensions' FROM jsonb_array_elements(part->'snapshot'->'lines') x
    EXCEPT ALL SELECT x->>'account_id',x->'credit_minor',x->'debit_minor',x->'dimensions' FROM jsonb_array_elements(oldpart->'snapshot'->'lines') x)) THEN
    RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='customer_partial_return_owner',MESSAGE='Reverse only the owned new partial effect with an exact full correction'; END IF;
  ELSE
   IF e.reverses_posting_id IS NOT NULL OR e.source_type<>'Manual' OR e.external_reference IS DISTINCT FROM i THEN
    RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='customer_partial_return_owner',MESSAGE='Partial credit must use additive Manual corrections'; END IF;
   IF p.operation='Return' AND ordinal=0 THEN
    expected:=jsonb_build_array(jsonb_build_object('account',revenue->>'account_id','debit',p.credit_minor,'credit',0,'dimensions',revenue->'dimensions'));
    IF p.receivable_released_minor>0 THEN expected:=expected||jsonb_build_array(jsonb_build_object('account',ar->>'account_id','debit',0,'credit',p.receivable_released_minor,'dimensions',ar->'dimensions')); END IF;
    IF p.refund_entitlement_delta_minor>0 THEN expected:=expected||jsonb_build_array(jsonb_build_object('account',s.refund_liability_account_id,'debit',0,'credit',p.refund_entitlement_delta_minor,'dimensions',ar->'dimensions')); END IF;
    IF e.journal_id IS DISTINCT FROM s.source_payload->'original_source'->'revenue'->'snapshot_json'->'entry'->>'journal_id' THEN
     RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='customer_partial_return_owner',MESSAGE='Original revenue journal must be preserved'; END IF;
   ELSIF p.operation='Return' THEN
    expected:=jsonb_build_array(jsonb_build_object('account',inventory->>'account_id','debit',p.cogs_restored_minor,'credit',0,'dimensions',inventory->'dimensions'),
     jsonb_build_object('account',cogs->>'account_id','debit',0,'credit',p.cogs_restored_minor,'dimensions',cogs->'dimensions'));
    IF e.journal_id IS DISTINCT FROM s.source_payload->'original_source'->'cogs'->'snapshot_json'->'entry'->>'journal_id' THEN
     RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='customer_partial_return_owner',MESSAGE='Original inventory journal must be preserved'; END IF;
   ELSE
    expected:=jsonb_build_array(jsonb_build_object('account',s.refund_liability_account_id,'debit',p.amount_minor,'credit',0,'dimensions',ar->'dimensions'),
     jsonb_build_object('account',s.cash_account_id,'debit',0,'credit',p.amount_minor,'dimensions',p.payload->'cash_dimensions'));
   END IF;
   IF expected IS DISTINCT FROM(SELECT jsonb_agg(jsonb_build_object('account',x->>'account_id','debit',x->'debit_minor','credit',x->'credit_minor','dimensions',x->'dimensions') ORDER BY n)
    FROM jsonb_array_elements(part->'snapshot'->'lines') WITH ORDINALITY a(x,n)) THEN
    RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='customer_partial_return_owner',MESSAGE='Partial correction amounts accounts and dimensions must match original source'; END IF;
  END IF;
  ordinal:=ordinal+1;
 END LOOP;
 IF EXISTS(SELECT 1 FROM reconforge.finance_entries extra WHERE extra.tenant_id=t
  AND(extra.external_reference=i OR upper(extra.entry_number) LIKE upper(i)||'%')
  AND NOT EXISTS(SELECT 1 FROM jsonb_array_elements(p.payload->'entries') pin WHERE pin->>'entry_id'=extra.id)) THEN
  RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='customer_partial_return_owner',MESSAGE='A native partial namespace permits only its exact reserved entries'; END IF;
 FOR v IN SELECT * FROM reconforge.customer_partial_return_events WHERE tenant_id=t AND plan_id=i LOOP
  metadata:=jsonb_build_object('plan_digest',p.plan_digest,'reason',v.reason,'effects',v.effects);
  IF v.actor_id=maker OR(v.operation IN('post','cancel') AND r IS NOT NULL AND v.actor_id=r.actor_id)
  OR(v.operation<>'post' AND v.effects<>'[]'::jsonb) OR(v.operation='post' AND jsonb_array_length(v.effects)<>ordinal)
  OR NOT EXISTS(SELECT 1 FROM reconforge.domain_audit_events a JOIN reconforge.outbox_events b ON b.tenant_id=a.tenant_id
  WHERE a.tenant_id=t AND a.id=v.audit_event_id AND b.event_id=v.outbox_event_id AND a.actor_user_id=v.actor_id AND a.object_id=i
  AND a.object_type='operational_finance' AND a.action='customer_partial_return_'||v.operation AND a.metadata_json=metadata
  AND b.aggregate_type='operational_finance' AND b.aggregate_id=i AND b.event_type=a.action AND b.payload=metadata||jsonb_build_object('audit_event_id',a.id)) THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='customer_partial_return_owner',MESSAGE='Partial lifecycle requires three independent humans and exact evidence'; END IF;
 END LOOP;
 FOR command IN SELECT * FROM reconforge.customer_partial_return_commands WHERE tenant_id=t AND plan_id=i LOOP
  stage:=CASE command.operation WHEN'review' THEN 1 WHEN'post' THEN 2 WHEN'cancel' THEN 3 ELSE 0 END;
  IF command.request_digest IS DISTINCT FROM reconforge.irp_digest(command.request_json)
  OR command.request_json->>'operation' IS DISTINCT FROM command.operation OR command.request_json->>'actor_id' IS DISTINCT FROM command.actor_id
  OR command.workspace_id IS DISTINCT FROM p.workspace_id OR command.response_json IS DISTINCT FROM reconforge.customer_partial_return_public(t,i,stage)
  OR(stage=0 AND command.request_json->'request' IS DISTINCT FROM p.payload->'request')
  OR command.actor_id IS DISTINCT FROM(CASE stage WHEN 0 THEN maker WHEN 1 THEN r.actor_id WHEN 2 THEN l.actor_id ELSE c.actor_id END) THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='customer_partial_return_owner',MESSAGE='Retry requires exact original actor request and acknowledgement'; END IF;
 END LOOP;
 IF NOT EXISTS(SELECT 1 FROM reconforge.customer_partial_return_commands WHERE tenant_id=t AND plan_id=i AND operation=
  CASE p.operation WHEN'Return' THEN'prepare' WHEN'Refund' THEN'prepare_refund' ELSE'prepare_reversal' END)
 OR(r IS NOT NULL AND NOT EXISTS(SELECT 1 FROM reconforge.customer_partial_return_commands WHERE tenant_id=t AND plan_id=i AND operation='review'))
 OR(l IS NOT NULL AND NOT EXISTS(SELECT 1 FROM reconforge.customer_partial_return_commands WHERE tenant_id=t AND plan_id=i AND operation='post'))
 OR(c IS NOT NULL AND NOT EXISTS(SELECT 1 FROM reconforge.customer_partial_return_commands WHERE tenant_id=t AND plan_id=i AND operation='cancel')) THEN
  RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='customer_partial_return_owner',MESSAGE='Every partial phase needs a retained native command'; END IF;
 IF(p.phase=2) IS DISTINCT FROM EXISTS(SELECT 1 FROM reconforge.customer_partial_return_history WHERE tenant_id=t AND source_id=s.id AND plan_id=i) THEN
  RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='customer_partial_return_owner',MESSAGE='Posted partial effects and economic history are atomic'; END IF;
 IF p.operation IN('Return','ReverseReturn') AND p.phase=2 THEN
  SELECT count(*) INTO restoration_count FROM reconforge.customer_partial_return_restorations WHERE tenant_id=t AND plan_id=i;
  IF restoration_count<>jsonb_array_length(p.payload->'domain_plan'->'portions')
  OR EXISTS(SELECT 1 FROM jsonb_array_elements(p.payload->'domain_plan'->'portions') x WHERE NOT EXISTS(
   SELECT 1 FROM reconforge.customer_partial_return_restorations z JOIN reconforge.finance_posting_effects owned_effect
   ON(owned_effect.tenant_id,owned_effect.id)=(z.tenant_id,z.correction_effect_id)
   WHERE z.tenant_id=t AND z.plan_id=i AND z.source_id=s.id AND z.position=(x->>'position')::integer
   AND z.original_consumption_id=x->>'original_consumption_id' AND z.original_valuation_line_id=x->>'original_valuation_line_id'
   AND z.cost_layer_id=x->>'cost_layer_id' AND z.quantity_scaled=(x->>'quantity_scaled')::bigint AND z.value_minor=(x->>'value_minor')::bigint
   AND z.offset_quantity_scaled=(x->>'offset_quantity_scaled')::bigint AND z.original_cogs_effect_id=s.original_cogs_effect_id
   AND z.direction=CASE p.operation WHEN'Return' THEN 1 ELSE-1 END AND z.physical_movement_id=p.payload->>'movement_id'
   AND z.original_restoration_plan_id IS NOT DISTINCT FROM CASE p.operation WHEN'Return' THEN NULL ELSE p.original_id END
   AND(z.direction=1 OR EXISTS(SELECT 1 FROM reconforge.customer_partial_return_restorations old
    WHERE old.tenant_id=z.tenant_id AND old.plan_id=p.original_id AND old.position=z.position
    AND old.direction=1 AND old.consumption_count_at_restore=z.consumption_count_at_restore))
   AND owned_effect.entry_id=p.payload->'entries'->1->>'entry_id'))
  OR NOT EXISTS(SELECT 1 FROM reconforge.inventory_movements m JOIN reconforge.inventory_movement_lines ml ON(ml.tenant_id,ml.movement_id)=(m.tenant_id,m.id)
   WHERE m.tenant_id=t AND m.id=p.payload->>'movement_id' AND m.status='Posted' AND m.source_reference=i
   AND m.movement_type=CASE p.operation WHEN'Return' THEN'Receipt' ELSE'Delivery' END
   AND(m.workspace_id,m.organization_id,m.legal_entity_id,m.period_id,m.movement_date::text)=(s.workspace_id,s.organization_id,s.legal_entity_id,p.payload->>'period_id',p.payload->>'posting_date')
   AND ml.item_id=s.item_id AND ml.uom_id=s.uom_id AND ml.inventory_lot_id IS NULL AND ml.quantity_scaled=p.quantity_scaled AND ml.quantity_precision=s.quantity_precision
   AND CASE p.operation WHEN'Return' THEN ml.to_location_id=s.location_id AND ml.from_location_id IS NULL ELSE ml.from_location_id=s.location_id AND ml.to_location_id IS NULL END)
  OR(SELECT count(*) FROM reconforge.inventory_movement_lines WHERE tenant_id=t AND movement_id=p.payload->>'movement_id')<>1 THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='customer_partial_return_owner',MESSAGE='Partial restoration requires original FIFO portions owned physical stock and actual correction effects'; END IF;
 ELSIF EXISTS(SELECT 1 FROM reconforge.customer_partial_return_restorations WHERE tenant_id=t AND plan_id=i) THEN
  RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='customer_partial_return_owner',MESSAGE='Unposted and cash-only plans cannot change original cost layers'; END IF;
 PERFORM reconforge.customer_partial_return_source_close(t,s.id);
END $cr2$;
CREATE FUNCTION reconforge.customer_partial_return_deferred_close() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $cr2$
DECLARE x JSONB:=to_jsonb(NEW);s RECORD;p RECORD;
BEGIN
 IF TG_TABLE_NAME='customer_partial_return_sources' THEN
  PERFORM reconforge.customer_partial_return_source_close(NEW.tenant_id,NEW.id);
  FOR p IN SELECT id FROM reconforge.customer_partial_return_plans WHERE tenant_id=NEW.tenant_id AND source_id=NEW.id LOOP
   PERFORM reconforge.customer_partial_return_close(NEW.tenant_id,p.id); END LOOP;
 ELSIF TG_TABLE_NAME='customer_partial_return_plans' THEN PERFORM reconforge.customer_partial_return_close(NEW.tenant_id,NEW.id);
 ELSIF TG_TABLE_NAME='customer_partial_return_history' THEN
  PERFORM reconforge.customer_partial_return_source_close(NEW.tenant_id,NEW.source_id);
  IF NEW.plan_id IS NOT NULL THEN PERFORM reconforge.customer_partial_return_close(NEW.tenant_id,NEW.plan_id); END IF;
 ELSE PERFORM reconforge.customer_partial_return_close(x->>'tenant_id',x->>'plan_id'); END IF;
 RETURN NULL;
END $cr2$;
DO $cr2$ DECLARE n TEXT;BEGIN
 FOREACH n IN ARRAY ARRAY['customer_partial_return_sources','customer_partial_return_plans','customer_partial_return_events',
 'customer_partial_return_history','customer_partial_return_restorations','customer_partial_return_commands'] LOOP
  EXECUTE format('CREATE CONSTRAINT TRIGGER native_close AFTER INSERT OR UPDATE ON reconforge.%I DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION reconforge.customer_partial_return_deferred_close()',n);
 END LOOP;
END $cr2$;
"""

COLLECTION_SQL = r"""
CREATE FUNCTION reconforge.customer_partial_return_collection_admitted(t TEXT,i TEXT,r TEXT,a TEXT) RETURNS BOOLEAN
 LANGUAGE plpgsql VOLATILE SET search_path=pg_catalog AS $cr2$
DECLARE actor TEXT;s RECORD;x RECORD;
BEGIN
 SELECT * INTO s FROM reconforge.customer_partial_return_sources WHERE tenant_id=t AND id=i;
 SELECT q.* INTO x FROM reconforge.ar_receipt_allocations q WHERE q.tenant_id=t AND q.id=a AND q.invoice_id=s.invoice_id AND q.receipt_id=r;
 IF s IS NULL OR x IS NULL THEN RETURN FALSE; END IF;
 SELECT f.posted_actor_id INTO actor FROM reconforge.commercial_collection_plans p
 JOIN reconforge.finance_posting_effects f ON(f.tenant_id,f.entry_id)=(p.tenant_id,p.entry_id)
 JOIN reconforge.ar_receipts h ON h.tenant_id=p.tenant_id AND h.id=r AND h.receipt_number=p.payload->>'receipt_number'
 WHERE p.tenant_id=t AND p.source_id=s.invoice_id AND p.phase IN(1,2) AND p.amount_minor=h.amount_minor
 AND(h.workspace_id,h.organization_id,h.legal_entity_id,h.customer_id,h.currency_code)=(s.workspace_id,s.organization_id,s.legal_entity_id,s.customer_id,s.currency_code)
 AND f.snapshot_json=p.payload->'snapshot' AND f.validation_digest=p.payload->>'validation_digest';
 RETURN actor IS NOT NULL AND reconforge.sales_revenue_actor(t,actor,'sales.manage')
 AND reconforge.sales_revenue_actor(t,actor,'receivables.manage') AND reconforge.sales_revenue_actor(t,actor,'finance_core.post');
END $cr2$;
CREATE FUNCTION reconforge.customer_partial_return_history_append_collection(t TEXT,i TEXT,r TEXT,a TEXT,delta BIGINT) RETURNS VOID
 LANGUAGE plpgsql VOLATILE SET search_path=pg_catalog AS $cr2$
DECLARE s RECORD;balance JSONB;event JSONB;previous TEXT;initial_amount BIGINT;retained BIGINT;actual BIGINT;version INTEGER;
BEGIN
 SELECT * INTO s FROM reconforge.customer_partial_return_sources WHERE tenant_id=t AND id=i;
 IF s IS NULL OR delta IS NULL OR delta<=0 OR NOT reconforge.customer_partial_return_collection_admitted(t,i,r,a) THEN
  RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='customer_partial_return_owner',MESSAGE='Collection append requires exact actual native ownership'; END IF;
 SELECT amount_minor INTO actual FROM reconforge.ar_receipt_allocations WHERE tenant_id=t AND id=a AND invoice_id=s.invoice_id AND receipt_id=r;
 SELECT COALESCE(sum((x->'allocation'->>'amount_minor')::bigint),0)::bigint INTO initial_amount
 FROM jsonb_array_elements(s.source_payload->'original_collections') x WHERE x->'allocation'->>'id'=a;
 SELECT COALESCE(sum(amount_minor),0)::bigint INTO retained FROM reconforge.customer_partial_return_history
 WHERE tenant_id=t AND source_id=i AND kind='Collection' AND allocation_id=a;
 balance:=reconforge.customer_partial_return_balance(t,i);version:=(balance->>'history_version')::integer;
 IF actual IS NULL OR actual-initial_amount-retained<>delta OR delta>(balance->>'outstanding_minor')::bigint OR version>=256 THEN
  RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='customer_partial_return_owner',MESSAGE='Collection append must match its exact new allocation delta and prefix residual'; END IF;
 previous:=balance->>'history_fingerprint';
 event:=jsonb_build_object('kind','Collection','sequence',version+1,'source_fingerprint',s.source_fingerprint,
 'previous_history_fingerprint',previous,'amount_minor',delta,'return_values',NULL,'original_sequence',NULL);
 INSERT INTO reconforge.customer_partial_return_history
 (tenant_id,source_id,sequence,kind,receipt_id,allocation_id,amount_minor,quantity_scaled,credit_minor,cogs_minor,payload,previous_digest,event_digest)
 VALUES(t,i,version+1,'Collection',r,a,delta,0,0,0,event,previous,reconforge.irp_digest(jsonb_build_object('previous',previous,'event',event)));
END $cr2$;
"""

UPGRADE_SQL = STORAGE_SQL + CLOSURE_SQL + PLAN_SQL + COLLECTION_SQL

DOWNGRADE_SQL = r"""
DO $cr2$ BEGIN IF EXISTS(SELECT 1 FROM reconforge.customer_partial_return_sources) THEN
 RAISE EXCEPTION 'Partial return downgrade refuses retained immutable evidence; restore the verified backup'; END IF; END $cr2$;
DROP TABLE reconforge.customer_partial_return_commands,reconforge.customer_partial_return_restorations,
 reconforge.customer_partial_return_history,reconforge.customer_partial_return_events,reconforge.customer_partial_return_plans,
 reconforge.customer_partial_return_sources;
DROP FUNCTION reconforge.customer_partial_return_protect();
DROP FUNCTION reconforge.customer_partial_return_deferred_close();
DROP FUNCTION reconforge.customer_partial_return_close(TEXT,TEXT);
DROP FUNCTION reconforge.customer_partial_return_source_close(TEXT,TEXT);
DROP FUNCTION reconforge.customer_partial_return_public(TEXT,TEXT,INTEGER);
DROP FUNCTION reconforge.customer_partial_return_balance(TEXT,TEXT);
DROP FUNCTION reconforge.customer_partial_return_history_append_collection(TEXT,TEXT,TEXT,TEXT,BIGINT);
DROP FUNCTION reconforge.customer_partial_return_collection_admitted(TEXT,TEXT,TEXT,TEXT);
"""
