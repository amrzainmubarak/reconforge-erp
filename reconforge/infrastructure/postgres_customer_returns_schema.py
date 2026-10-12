"""CR1 invoker-scoped source ownership and deferred native effect closure."""

_STORAGE_SQL = r"""
ALTER TABLE reconforge.ar_invoices ADD COLUMN customer_return_owner_id TEXT;
CREATE TABLE reconforge.customer_return_plans (
 tenant_id TEXT NOT NULL,id TEXT NOT NULL CHECK(id~'^(CR1|CRF1)-[a-f0-9]{32}$'),workspace_id TEXT NOT NULL,
 organization_id TEXT NOT NULL,legal_entity_id TEXT NOT NULL,source_order_id TEXT NOT NULL,invoice_id TEXT NOT NULL,
 return_id TEXT,operation TEXT NOT NULL CHECK(operation IN('Return','Refund')),phase INTEGER NOT NULL DEFAULT 0 CHECK(phase BETWEEN 0 AND 3),
 amount_minor BIGINT NOT NULL CHECK(amount_minor BETWEEN 1 AND 9000000000000000000),payload JSONB NOT NULL,
 audit_event_id TEXT NOT NULL,outbox_event_id TEXT NOT NULL,created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 PRIMARY KEY(tenant_id,id),FOREIGN KEY(tenant_id,source_order_id) REFERENCES reconforge.stock_sales_orders(tenant_id,id),
 FOREIGN KEY(tenant_id,invoice_id) REFERENCES reconforge.ar_invoices(tenant_id,id),
 FOREIGN KEY(tenant_id,return_id) REFERENCES reconforge.customer_return_plans(tenant_id,id),
 FOREIGN KEY(tenant_id,audit_event_id) REFERENCES reconforge.domain_audit_events(tenant_id,id),
 FOREIGN KEY(tenant_id,outbox_event_id) REFERENCES reconforge.outbox_events(tenant_id,event_id),
 CHECK((operation='Return' AND return_id IS NULL AND left(id,4)='CR1-') OR(operation='Refund' AND return_id IS NOT NULL AND left(id,5)='CRF1-'))
);
CREATE UNIQUE INDEX customer_return_active_source ON reconforge.customer_return_plans(tenant_id,source_order_id)
 WHERE operation='Return' AND phase<>3;
CREATE UNIQUE INDEX customer_return_pending_refund ON reconforge.customer_return_plans(tenant_id,return_id)
 WHERE operation='Refund' AND phase IN(0,1);
CREATE INDEX customer_return_scope ON reconforge.customer_return_plans(tenant_id,workspace_id,organization_id,legal_entity_id,id COLLATE "C");
CREATE TABLE reconforge.customer_return_events (
 tenant_id TEXT NOT NULL,plan_id TEXT NOT NULL,operation TEXT NOT NULL CHECK(operation IN('review','post','cancel')),
 actor_id TEXT NOT NULL,reason TEXT NOT NULL CHECK(length(reason) BETWEEN 1 AND 500),effects JSONB NOT NULL CHECK(jsonb_typeof(effects)='array'),
 audit_event_id TEXT NOT NULL,outbox_event_id TEXT NOT NULL,created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 PRIMARY KEY(tenant_id,plan_id,operation),FOREIGN KEY(tenant_id,plan_id) REFERENCES reconforge.customer_return_plans(tenant_id,id),
 FOREIGN KEY(tenant_id,actor_id) REFERENCES reconforge.identity_users(tenant_id,id),
 FOREIGN KEY(tenant_id,audit_event_id) REFERENCES reconforge.domain_audit_events(tenant_id,id),
 FOREIGN KEY(tenant_id,outbox_event_id) REFERENCES reconforge.outbox_events(tenant_id,event_id)
);
CREATE TABLE reconforge.customer_return_commands (
 tenant_id TEXT NOT NULL,workspace_id TEXT NOT NULL,plan_id TEXT NOT NULL,operation TEXT NOT NULL CHECK(operation IN('prepare','prepare_refund','review','post','cancel')),
 command_id TEXT NOT NULL CHECK(length(command_id) BETWEEN 1 AND 140),actor_id TEXT NOT NULL,request_digest TEXT NOT NULL CHECK(request_digest~'^[a-f0-9]{64}$'),
 request_json JSONB NOT NULL,response_json JSONB NOT NULL,created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 PRIMARY KEY(tenant_id,workspace_id,command_id),UNIQUE(tenant_id,plan_id,operation),
 FOREIGN KEY(tenant_id,plan_id) REFERENCES reconforge.customer_return_plans(tenant_id,id),
 FOREIGN KEY(tenant_id,actor_id) REFERENCES reconforge.identity_users(tenant_id,id)
);
CREATE FUNCTION reconforge.customer_return_source(t TEXT,i TEXT) RETURNS JSONB LANGUAGE sql STABLE SET search_path=pg_catalog AS $cr$
 SELECT jsonb_build_object('stock',to_jsonb(s),'invoice',to_jsonb(h)-ARRAY['customer_return_owner_id','status','row_version','updated_at','cancelled_by','cancelled_at','cancel_reason'],
 'invoice_status',h.status,'invoice_version',h.row_version,'allocated_minor',COALESCE((SELECT sum(amount_minor) FROM reconforge.ar_receipt_allocations WHERE tenant_id=t AND invoice_id=h.id),0),
 'cogs',(SELECT to_jsonb(f) FROM reconforge.finance_posting_effects f WHERE f.tenant_id=t AND f.id=s.cogs_effect_id),
 'revenue',(SELECT to_jsonb(f) FROM reconforge.operational_finance_links l JOIN reconforge.finance_posting_effects f
  ON f.tenant_id=l.tenant_id AND f.id=l.posting_effect_id WHERE l.tenant_id=t AND l.plan_id=s.invoice_plan_id),
 'consumptions',COALESCE((SELECT jsonb_agg(to_jsonb(c) ORDER BY c.cost_layer_id,c.id) FROM reconforge.inventory_layer_consumptions c
 JOIN reconforge.inventory_valuation_lines v ON v.tenant_id=c.tenant_id AND v.id=c.valuation_line_id WHERE c.tenant_id=t AND v.valuation_document_id=s.valuation_id),'[]'::jsonb))
 FROM reconforge.stock_sales_orders s JOIN reconforge.ar_invoices h ON h.tenant_id=s.tenant_id AND h.id=s.invoice_id WHERE s.tenant_id=t AND s.id=i
$cr$;
CREATE FUNCTION reconforge.customer_return_source_available(t TEXT,i TEXT) RETURNS VOID LANGUAGE plpgsql SET search_path=pg_catalog AS $cr$
DECLARE s RECORD;h RECORD;
BEGIN
 SELECT * INTO s FROM reconforge.stock_sales_orders WHERE tenant_id=t AND id=i;
 SELECT * INTO h FROM reconforge.ar_invoices WHERE tenant_id=t AND id=s.invoice_id;
 IF s IS NULL OR h IS NULL OR s.status NOT IN('Invoiced','Paid') OR h.status NOT IN('Approved','PartiallyPaid','Paid')
 OR h.tax_minor<>0 OR h.customer_return_owner_id IS NOT NULL OR(s.collection_plan_id IS NOT NULL AND s.status<>'Paid')
 OR EXISTS(SELECT 1 FROM reconforge.commercial_collection_plans WHERE tenant_id=t AND source_id=h.id AND phase IN(0,1))
 OR EXISTS(SELECT 1 FROM reconforge.customer_return_plans WHERE tenant_id=t AND source_order_id=i AND operation='Return' AND phase<>3)
 OR EXISTS(SELECT 1 FROM reconforge.inventory_valuation_reversals WHERE tenant_id=t AND original_valuation_document_id=s.valuation_id AND status<>'Cancelled') THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='customer_return_owner',MESSAGE='Return requires one complete uncredited original zero-tax functional-currency delivery and no pending collection'; END IF;
END $cr$;
CREATE FUNCTION reconforge.customer_return_accounts(t TEXT,i TEXT,j TEXT,l TEXT,c TEXT,live BOOLEAN DEFAULT TRUE) RETURNS VOID LANGUAGE plpgsql SET search_path=pg_catalog AS $cr$
DECLARE s RECORD;journal RECORD;liability RECORD;cash RECORD;source_cash TEXT;
BEGIN
 SELECT * INTO s FROM reconforge.stock_sales_orders WHERE tenant_id=t AND id=i;
 SELECT * INTO journal FROM reconforge.finance_journals WHERE tenant_id=t AND workspace_id=s.workspace_id AND organization_code=s.source->>'organization_code' AND journal_code=j;
 IF journal IS NULL THEN SELECT fj.* INTO journal FROM reconforge.finance_journals fj JOIN reconforge.organizations o
  ON o.tenant_id=fj.tenant_id AND o.organization_code=fj.organization_code AND o.application_workspace_id=fj.workspace_id
  WHERE fj.tenant_id=t AND fj.workspace_id=s.workspace_id AND o.id=s.organization_id AND fj.journal_code=j; END IF;
 SELECT * INTO liability FROM reconforge.finance_accounts WHERE tenant_id=t AND chart_id=journal.chart_id AND account_code=l;
 SELECT * INTO cash FROM reconforge.finance_accounts WHERE tenant_id=t AND chart_id=journal.chart_id AND account_code=c;
 IF journal IS NULL OR(live AND NOT journal.active) OR journal.currency_code<>s.currency_code OR liability IS NULL OR cash IS NULL
 OR liability.account_type<>'Liability' OR liability.normal_balance<>'Credit' OR cash.account_type<>'Asset' OR cash.normal_balance<>'Debit'
 OR(live AND(NOT liability.active OR NOT cash.active OR NOT liability.allow_posting OR NOT cash.allow_posting))
 OR liability.id=cash.id OR c=s.invoice_parameters->>'receivable_account_code' THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='customer_return_owner',MESSAGE='Refund requires distinct active native liability and cash accounts in the functional journal'; END IF;
 FOR source_cash IN SELECT DISTINCT p.payload->>'debit_account_code' FROM reconforge.commercial_collection_plans p WHERE p.tenant_id=t AND p.source_id=s.invoice_id AND p.phase=2 LOOP
  IF source_cash IS DISTINCT FROM c THEN RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='customer_return_owner',MESSAGE='Refund must use the original collected cash account'; END IF;
 END LOOP;
 IF s.status='Paid' AND s.collection_parameters->>'cash_account_code' IS DISTINCT FROM c THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='customer_return_owner',MESSAGE='Refund must use the original full collection cash account'; END IF;
END $cr$;
CREATE FUNCTION reconforge.customer_return_refund_due(t TEXT,i TEXT) RETURNS BIGINT LANGUAGE sql STABLE SET search_path=pg_catalog AS $cr$
 SELECT (p.payload->>'refund_entitlement_minor')::bigint-COALESCE((SELECT sum(amount_minor) FROM reconforge.customer_return_plans
 WHERE tenant_id=t AND return_id=i AND operation='Refund' AND phase=2),0)::bigint FROM reconforge.customer_return_plans p WHERE p.tenant_id=t AND p.id=i AND p.operation='Return'
$cr$;
CREATE FUNCTION reconforge.customer_return_refund_available(t TEXT,i TEXT) RETURNS VOID LANGUAGE plpgsql SET search_path=pg_catalog AS $cr$
BEGIN
 IF EXISTS(SELECT 1 FROM reconforge.customer_return_plans WHERE tenant_id=t AND return_id=i AND phase IN(0,1))
 OR(SELECT count(*) FROM reconforge.customer_return_plans WHERE tenant_id=t AND return_id=i)>=200 THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='customer_return_owner',MESSAGE='Complete or cancel the current bounded refund installment first'; END IF;
END $cr$;
CREATE FUNCTION reconforge.customer_return_public(t TEXT,i TEXT,selected_phase INTEGER DEFAULT NULL) RETURNS JSONB LANGUAGE plpgsql STABLE SET search_path=pg_catalog AS $cr$
DECLARE p RECORD;r RECORD;l RECORD;c RECORD;stage INTEGER;
BEGIN
 SELECT * INTO p FROM reconforge.customer_return_plans WHERE tenant_id=t AND id=i;
 SELECT * INTO r FROM reconforge.customer_return_events WHERE tenant_id=t AND plan_id=i AND operation='review';
 SELECT * INTO l FROM reconforge.customer_return_events WHERE tenant_id=t AND plan_id=i AND operation='post';
 SELECT * INTO c FROM reconforge.customer_return_events WHERE tenant_id=t AND plan_id=i AND operation='cancel';
 stage:=COALESCE(selected_phase,p.phase);
 RETURN p.payload||jsonb_build_object('phase',stage,'status',(ARRAY['Prepared','Reviewed','Posted','Cancelled'])[stage+1],
 'reviewer_actor_id',CASE WHEN stage<>0 THEN r.actor_id ELSE NULL END,
 'posted_actor_id',CASE WHEN stage=2 THEN l.actor_id ELSE NULL END,'posting_effect_ids',CASE WHEN stage=2 THEN l.effects ELSE '[]'::jsonb END,
 'cancelled_actor_id',CASE WHEN stage=3 THEN c.actor_id ELSE NULL END,'cancellation_reason',CASE WHEN stage=3 THEN c.reason ELSE NULL END,
 'canonical_plan_json',reconforge.irp_canonical(p.payload-'plan_digest'),
 'evidence',jsonb_build_object('prepared_audit_event_id',p.audit_event_id,'prepared_outbox_event_id',p.outbox_event_id,
 'review_audit_event_id',CASE WHEN stage<>0 THEN r.audit_event_id ELSE NULL END,'review_outbox_event_id',CASE WHEN stage<>0 THEN r.outbox_event_id ELSE NULL END,
 'post_audit_event_id',CASE WHEN stage=2 THEN l.audit_event_id ELSE NULL END,'post_outbox_event_id',CASE WHEN stage=2 THEN l.outbox_event_id ELSE NULL END,
 'cancel_audit_event_id',CASE WHEN stage=3 THEN c.audit_event_id ELSE NULL END,'cancel_outbox_event_id',CASE WHEN stage=3 THEN c.outbox_event_id ELSE NULL END));
END $cr$;
CREATE FUNCTION reconforge.customer_return_event(t TEXT,i TEXT,a TEXT,b TEXT,actor TEXT,action TEXT,metadata JSONB) RETURNS BOOLEAN
 LANGUAGE sql STABLE SET search_path=pg_catalog AS $cr$
 SELECT EXISTS(SELECT 1 FROM reconforge.domain_audit_events x JOIN reconforge.outbox_events y ON y.tenant_id=x.tenant_id
 JOIN reconforge.customer_return_plans p ON p.tenant_id=x.tenant_id AND p.id=i
 WHERE x.tenant_id=t AND x.id=a AND y.event_id=b AND x.actor_user_id=actor AND x.object_type='operational_finance' AND x.object_id=i
 AND x.action=action AND x.metadata_json=metadata AND y.event_type=action AND y.aggregate_type='operational_finance' AND y.aggregate_id=i
 AND y.payload=metadata||jsonb_build_object('audit_event_id',a) AND(y.workspace_id,y.organization_id,y.legal_entity_id)=(p.workspace_id,p.organization_id,p.legal_entity_id))
$cr$;
CREATE FUNCTION reconforge.customer_return_authority(t TEXT,a TEXT,operation TEXT) RETURNS BOOLEAN LANGUAGE plpgsql SET search_path=pg_catalog AS $cr$
DECLARE permission TEXT;permissions TEXT[];
BEGIN
 permissions:=ARRAY['sales.read','receivables.read','inventory.read','finance_core.read'];
 IF operation IN('prepare','prepare_refund') THEN permissions:=permissions||ARRAY['sales.manage','receivables.manage','inventory.valuation.manage','finance_core.manage','finance_core.reverse'];
 ELSIF operation='review' THEN permissions:=permissions||ARRAY['sales.approve','inventory.valuation.approve','finance_core.validate','finance_core.reverse'];
 ELSIF operation='post' THEN permissions:=permissions||ARRAY['sales.manage','receivables.manage','inventory.post','inventory.valuation.approve','finance_core.post','finance_core.reverse'];
 ELSIF operation='cancel' THEN permissions:=permissions||ARRAY['sales.approve','finance_core.validate']; ELSE RETURN FALSE; END IF;
 FOREACH permission IN ARRAY permissions LOOP IF NOT reconforge.sales_revenue_actor(t,a,permission) THEN RETURN FALSE; END IF; END LOOP;
 RETURN TRUE;
END $cr$;
CREATE FUNCTION reconforge.customer_return_protect() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $cr$
DECLARE p RECORD;a TEXT:=current_setting('app.customer_return_actor_id',true);
BEGIN
 IF TG_OP='DELETE' OR(TG_OP='UPDATE' AND TG_TABLE_NAME<>'customer_return_plans') THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='customer_return_owner',MESSAGE='Original-source customer credit evidence is immutable'; END IF;
 IF TG_TABLE_NAME='customer_return_plans' THEN
  IF TG_OP='INSERT' AND(NEW.phase<>0 OR NOT reconforge.customer_return_authority(NEW.tenant_id,a,CASE NEW.operation WHEN'Return' THEN'prepare' ELSE'prepare_refund' END)
   OR NEW.payload->>'preparer_actor_id' IS DISTINCT FROM a) THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='customer_return_owner',MESSAGE='Credit must be born Prepared under current scoped human authority'; END IF;
  IF TG_OP='UPDATE' AND((to_jsonb(NEW)-'phase') IS DISTINCT FROM(to_jsonb(OLD)-'phase')
   OR NOT((OLD.phase=0 AND NEW.phase=1) OR(OLD.phase=1 AND NEW.phase=2) OR(OLD.phase IN(0,1) AND NEW.phase=3))) THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='customer_return_owner',MESSAGE='Credit transition cannot change original source evidence'; END IF;
 ELSE
  SELECT * INTO p FROM reconforge.customer_return_plans WHERE tenant_id=NEW.tenant_id AND id=NEW.plan_id;
  IF p IS NULL OR NEW.actor_id IS DISTINCT FROM a OR NOT reconforge.customer_return_authority(NEW.tenant_id,a,NEW.operation) THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='customer_return_owner',MESSAGE='Credit event or command requires current persisted human authority'; END IF;
 END IF;
 RETURN NEW;
END $cr$;
DO $cr$ DECLARE n TEXT;BEGIN
 FOREACH n IN ARRAY ARRAY['customer_return_plans','customer_return_events','customer_return_commands'] LOOP
  EXECUTE format('ALTER TABLE reconforge.%I ENABLE ROW LEVEL SECURITY',n);
  EXECUTE format('ALTER TABLE reconforge.%I FORCE ROW LEVEL SECURITY',n);
  IF n='customer_return_plans' THEN EXECUTE format('CREATE POLICY scope ON reconforge.%I USING(reconforge.irp_scope(tenant_id,workspace_id,organization_id,legal_entity_id)) WITH CHECK(reconforge.irp_scope(tenant_id,workspace_id,organization_id,legal_entity_id))',n);
  ELSE EXECUTE format('CREATE POLICY scope ON reconforge.%I USING(EXISTS(SELECT 1 FROM reconforge.customer_return_plans p WHERE p.tenant_id=%I.tenant_id AND p.id=%I.plan_id)) WITH CHECK(EXISTS(SELECT 1 FROM reconforge.customer_return_plans p WHERE p.tenant_id=%I.tenant_id AND p.id=%I.plan_id))',n,n,n,n,n); END IF;
  EXECUTE format('CREATE TRIGGER immutable BEFORE INSERT OR UPDATE OR DELETE ON reconforge.%I FOR EACH ROW EXECUTE FUNCTION reconforge.customer_return_protect()',n);
 END LOOP;
END $cr$;
"""

_CLOSURE_SQL = r"""
CREATE FUNCTION reconforge.customer_return_close(t TEXT,i TEXT) RETURNS VOID LANGUAGE plpgsql SET search_path=pg_catalog AS $cr$
DECLARE p RECORD;r RECORD;l RECORD;c RECORD;h RECORD;f RECORD;e RECORD;v RECORD;command RECORD;part JSONB;source JSONB;original JSONB;
 maker TEXT;seal TEXT;expected_phase INTEGER;amount NUMERIC;ordinal INTEGER:=0;reviewed BOOLEAN;
BEGIN
 SELECT * INTO p FROM reconforge.customer_return_plans WHERE tenant_id=t AND id=i;
 IF p IS NULL THEN RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='customer_return_owner',MESSAGE='Native credit effect requires its retained source owner'; END IF;
 SELECT * INTO r FROM reconforge.customer_return_events WHERE tenant_id=t AND plan_id=i AND operation='review';
 SELECT * INTO l FROM reconforge.customer_return_events WHERE tenant_id=t AND plan_id=i AND operation='post';
 SELECT * INTO c FROM reconforge.customer_return_events WHERE tenant_id=t AND plan_id=i AND operation='cancel';
 maker:=p.payload->>'preparer_actor_id';seal:=p.payload->>'plan_digest';source:=reconforge.customer_return_source(t,p.source_order_id);
 SELECT * INTO h FROM reconforge.ar_invoices WHERE tenant_id=t AND id=p.invoice_id;
 IF source IS NULL OR h IS NULL OR NOT reconforge.irp_scope(t,p.workspace_id,p.organization_id,p.legal_entity_id)
 OR reconforge.irp_digest(p.payload-'plan_digest') IS DISTINCT FROM seal OR p.payload->>'schema_version' IS DISTINCT FROM'customer-return-v1'
 OR(p.payload->>'id',p.payload->>'operation',p.payload->>'source_order_id',p.payload->>'invoice_id') IS DISTINCT FROM(p.id,p.operation,p.source_order_id,p.invoice_id)
 OR(p.payload->>'workspace_id',p.payload->>'organization_id',p.payload->>'legal_entity_id') IS DISTINCT FROM(p.workspace_id,p.organization_id,p.legal_entity_id)
 OR(p.payload->>'amount_minor')::numeric IS DISTINCT FROM p.amount_minor::numeric
 OR p.payload->>'currency_code' IS DISTINCT FROM h.currency_code OR(p.payload->>'currency_precision')::integer IS DISTINCT FROM h.currency_precision
 OR h.tax_minor<>0 OR jsonb_typeof(p.payload->'entries') IS DISTINCT FROM'array'
 OR(p.phase=2) IS DISTINCT FROM(l IS NOT NULL) OR(p.phase=3) IS DISTINCT FROM(c IS NOT NULL)
 OR(p.phase IN(1,2) AND r IS NULL) OR(p.phase=0 AND r IS NOT NULL)
 OR NOT reconforge.customer_return_event(t,i,p.audit_event_id,p.outbox_event_id,maker,'customer_return_prepared',jsonb_build_object('plan_digest',seal)) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='customer_return_owner',MESSAGE='Credit plan phase, exact source and preparation evidence differ'; END IF;
 IF p.operation='Return' THEN
  original:=p.payload->'source_snapshot';
  IF(source-ARRAY['invoice_status','invoice_version','allocated_minor']) IS DISTINCT FROM(original-ARRAY['invoice_status','invoice_version','allocated_minor'])
  OR original->'stock'->>'status' NOT IN('Invoiced','Paid') OR original->>'invoice_status' NOT IN('Approved','PartiallyPaid','Paid')
  OR jsonb_array_length(original->'consumptions')<1 OR jsonb_array_length(original->'consumptions')>1000
  OR(p.payload->>'credit_minor')::numeric IS DISTINCT FROM h.total_minor::numeric
  OR(p.phase<>3 AND(source->>'allocated_minor')::numeric IS DISTINCT FROM(original->>'allocated_minor')::numeric)
  OR(p.payload->>'refund_entitlement_minor')::numeric IS DISTINCT FROM(original->>'allocated_minor')::numeric
  OR(p.payload->>'receivable_released_minor')::numeric IS DISTINCT FROM h.total_minor::numeric-(original->>'allocated_minor')::numeric
  OR(p.payload->>'cogs_restored_minor')::numeric IS DISTINCT FROM(original->'cogs'->'snapshot_json'->'lines'->0->>'debit_minor')::numeric
  OR p.amount_minor::numeric IS DISTINCT FROM h.total_minor::numeric+(original->>'allocated_minor')::numeric+(p.payload->>'cogs_restored_minor')::numeric
  OR jsonb_array_length(p.payload->'entries') IS DISTINCT FROM(CASE WHEN(original->>'allocated_minor')::numeric=0 THEN 2 ELSE 3 END)
  OR(p.phase<>3 AND EXISTS(SELECT 1 FROM reconforge.commercial_collection_plans WHERE tenant_id=t AND source_id=h.id AND phase IN(0,1)))
  OR(p.phase IN(0,1) AND(h.customer_return_owner_id IS DISTINCT FROM i OR h.status IS DISTINCT FROM original->>'invoice_status' OR h.row_version IS DISTINCT FROM(original->>'invoice_version')::integer))
  OR(p.phase=2 AND(h.customer_return_owner_id IS DISTINCT FROM i OR h.status<>'Cancelled' OR h.cancel_reason IS DISTINCT FROM i OR h.cancelled_at IS NULL OR h.row_version<>(original->>'invoice_version')::integer+1))
  OR(p.phase=3 AND h.customer_return_owner_id=i) THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='customer_return_owner',MESSAGE='Whole source credit must conserve original invoice, collections and FIFO cost'; END IF;
  IF p.phase<>3 THEN PERFORM reconforge.customer_return_accounts(t,p.source_order_id,p.payload->>'journal_code',p.payload->>'refund_liability_account_code',p.payload->>'cash_account_code',p.phase IN(0,1)); END IF;
  IF p.phase=2 THEN
   SELECT * INTO v FROM reconforge.inventory_valuation_reversals WHERE tenant_id=t AND id=p.payload->>'valuation_reversal_id';
   IF v IS NULL OR v.status<>'Approved' OR v.original_valuation_document_id IS DISTINCT FROM source->'stock'->>'valuation_id'
   OR v.reversal_movement_id IS DISTINCT FROM p.payload->>'movement_id' OR v.finance_entry_id IS DISTINCT FROM p.payload->'entries'->0->>'entry_id'
   OR v.total_value_minor IS DISTINCT FROM(p.payload->>'cogs_restored_minor')::bigint OR v.approved_by IS DISTINCT FROM h.cancelled_by
   OR(v.workspace_id,v.organization_id,v.legal_entity_id,v.period_id,v.currency_code,v.reversal_date::text) IS DISTINCT FROM
    (p.workspace_id,p.organization_id,p.legal_entity_id,p.payload->>'period_id',h.currency_code,p.payload->>'posting_date')
   OR NOT EXISTS(SELECT 1 FROM reconforge.inventory_movements m JOIN reconforge.inventory_movement_lines ml ON ml.tenant_id=m.tenant_id AND ml.movement_id=m.id
    WHERE m.tenant_id=t AND m.id=v.reversal_movement_id AND m.status='Posted' AND m.source_reference=i AND m.movement_type='Receipt'
    AND(m.workspace_id,m.organization_id,m.legal_entity_id,m.period_id,m.movement_date::text)=(p.workspace_id,p.organization_id,p.legal_entity_id,p.payload->>'period_id',p.payload->>'posting_date')
    AND ml.to_location_id=source->'stock'->>'location_id' AND ml.from_location_id IS NULL AND ml.item_id=source->'stock'->>'item_id'
    AND ml.uom_id=source->'stock'->>'uom_id' AND ml.inventory_lot_id IS NULL AND ml.quantity_scaled=(source->'stock'->>'quantity_scaled')::bigint
    AND ml.quantity_precision=(source->'stock'->>'quantity_precision')::integer)
   OR(SELECT count(*) FROM reconforge.inventory_movement_lines WHERE tenant_id=t AND movement_id=v.reversal_movement_id)<>1
   OR(SELECT count(*) FROM reconforge.inventory_valuation_reversal_effects WHERE tenant_id=t AND reversal_id=v.id)<>jsonb_array_length(original->'consumptions')
   OR EXISTS(SELECT 1 FROM jsonb_array_elements(original->'consumptions') x WHERE NOT EXISTS(SELECT 1 FROM reconforge.inventory_valuation_reversal_effects z
    WHERE z.tenant_id=t AND z.reversal_id=v.id AND z.original_consumption_id=x->>'id' AND z.original_valuation_line_id=x->>'valuation_line_id'
    AND z.cost_layer_id=x->>'cost_layer_id' AND z.effect_type='Restore' AND z.quantity_scaled=(x->>'quantity_scaled')::bigint AND z.value_minor=(x->>'value_minor')::bigint)) THEN
    RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='customer_return_owner',MESSAGE='Source credit requires its exact complete opposite stock movement and original FIFO restitution'; END IF;
  ELSIF EXISTS(SELECT 1 FROM reconforge.inventory_movements WHERE tenant_id=t AND id=p.payload->>'movement_id')
   OR EXISTS(SELECT 1 FROM reconforge.inventory_valuation_reversals WHERE tenant_id=t AND id=p.payload->>'valuation_reversal_id') THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='customer_return_owner',MESSAGE='Unposted credit cannot have native stock effects'; END IF;
 ELSE
  PERFORM reconforge.customer_return_close(t,p.return_id);
  SELECT * INTO v FROM reconforge.customer_return_plans WHERE tenant_id=t AND id=p.return_id AND operation='Return' AND phase=2;
  IF v IS NULL OR p.payload->>'return_id' IS DISTINCT FROM v.id OR p.payload->>'parent_digest' IS DISTINCT FROM v.payload->>'plan_digest'
  OR(p.source_order_id,p.invoice_id,p.workspace_id,p.organization_id,p.legal_entity_id) IS DISTINCT FROM(v.source_order_id,v.invoice_id,v.workspace_id,v.organization_id,v.legal_entity_id)
  OR p.payload->>'refund_liability_account_code' IS DISTINCT FROM v.payload->>'refund_liability_account_code'
  OR p.payload->>'cash_account_code' IS DISTINCT FROM v.payload->>'cash_account_code' OR p.payload->>'journal_code' IS DISTINCT FROM v.payload->>'journal_code'
  OR jsonb_array_length(p.payload->'entries')<>1 OR p.payload->>'posting_date'<v.payload->>'posting_date'
  OR(p.payload->>'refunded_before_minor')::numeric<0
  OR(p.payload->>'refunded_before_minor')::numeric+p.amount_minor>(v.payload->>'refund_entitlement_minor')::numeric
  OR reconforge.customer_return_refund_due(t,v.id)<0
  OR(p.phase IN(0,1) AND(v.payload->>'refund_entitlement_minor')::numeric-reconforge.customer_return_refund_due(t,v.id)<>(p.payload->>'refunded_before_minor')::numeric)
  OR(p.phase=2 AND(SELECT COALESCE(sum(q.amount_minor),0) FROM reconforge.customer_return_plans q WHERE q.tenant_id=t AND q.return_id=v.id AND q.phase=2
   AND(q.payload->>'refunded_before_minor')::numeric<(p.payload->>'refunded_before_minor')::numeric)<>(p.payload->>'refunded_before_minor')::numeric) THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='customer_return_owner',MESSAGE='Refund must conserve one original source liability and retained installment sequence'; END IF;
 END IF;
 FOR part IN SELECT * FROM jsonb_array_elements(p.payload->'entries') LOOP
  SELECT * INTO e FROM reconforge.finance_entries WHERE tenant_id=t AND id=part->>'entry_id';
  SELECT * INTO f FROM reconforge.finance_posting_effects WHERE tenant_id=t AND entry_id=e.id;
  reviewed:=r IS NOT NULL;
  IF e IS NULL OR part->'snapshot' IS DISTINCT FROM reconforge.fr_snapshot(t,e.id,p.organization_id,p.legal_entity_id)
  OR part->>'validation_digest' IS DISTINCT FROM reconforge.irp_digest(part->'snapshot') OR e.preparer_actor_id IS DISTINCT FROM maker
  OR e.external_reference IS DISTINCT FROM i OR e.posting_date IS DISTINCT FROM p.payload->>'posting_date' OR e.period_id IS DISTINCT FROM p.payload->>'period_id'
  OR(e.currency_code,e.currency_precision,e.currency_rounding_policy,e.currency_registry_version,e.currency_registry_digest) IS DISTINCT FROM
   (h.currency_code,h.currency_precision,h.currency_rounding_policy,h.currency_registry_version,h.currency_registry_digest)
  OR e.status IS DISTINCT FROM(CASE WHEN reviewed THEN'Validated' ELSE'Draft' END)
  OR(reviewed AND(e.validator_actor_id IS DISTINCT FROM r.actor_id OR e.validation_digest IS DISTINCT FROM part->>'validation_digest'))
  OR(p.phase=2) IS DISTINCT FROM(f.id IS NOT NULL)
  OR(f.id IS NOT NULL AND(f.id IS DISTINCT FROM l.effects->>ordinal OR f.posted_actor_id IS DISTINCT FROM l.actor_id OR f.snapshot_json IS DISTINCT FROM part->'snapshot')) THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='customer_return_owner',MESSAGE='Credit native GL entries, review and posted effects must match retained exact snapshots'; END IF;
  IF p.operation='Return' AND ordinal<2 THEN
   original:=CASE WHEN ordinal=0 THEN source->'cogs' ELSE source->'revenue' END;
   IF part->>'original_effect_id' IS DISTINCT FROM original->>'id' OR e.reverses_posting_id IS DISTINCT FROM original->>'id'
   OR e.source_type<>'Generated' OR e.journal_id IS DISTINCT FROM original->'snapshot_json'->'entry'->>'journal_id'
   OR EXISTS((SELECT x->>'account_id',x->'credit_minor',x->'debit_minor',x->'dimensions' FROM jsonb_array_elements(original->'snapshot_json'->'lines') x
    EXCEPT ALL SELECT x->>'account_id',x->'debit_minor',x->'credit_minor',x->'dimensions' FROM jsonb_array_elements(part->'snapshot'->'lines') x)
    UNION ALL(SELECT x->>'account_id',x->'credit_minor',x->'debit_minor',x->'dimensions' FROM jsonb_array_elements(part->'snapshot'->'lines') x
    EXCEPT ALL SELECT x->>'account_id',x->'debit_minor',x->'credit_minor',x->'dimensions' FROM jsonb_array_elements(original->'snapshot_json'->'lines') x)) THEN
    RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='customer_return_owner',MESSAGE='Credit must exactly reverse the original GL amounts accounts currency policy and dimensions'; END IF;
  ELSE
   amount:=CASE p.operation WHEN'Return' THEN(p.payload->>'refund_entitlement_minor')::numeric ELSE p.amount_minor END;
   IF e.reverses_posting_id IS NOT NULL OR e.source_type<>'Manual' OR jsonb_array_length(part->'snapshot'->'lines')<>2
   OR NOT EXISTS(SELECT 1 FROM reconforge.finance_entry_lines a JOIN reconforge.finance_accounts b ON b.tenant_id=a.tenant_id AND b.id=a.account_id
    WHERE a.tenant_id=t AND a.entry_id=e.id AND a.line_number=1 AND a.debit_minor=amount AND a.credit_minor=0
    AND b.account_code=CASE p.operation WHEN'Return' THEN source->'stock'->'invoice_parameters'->>'receivable_account_code' ELSE p.payload->>'refund_liability_account_code' END)
   OR NOT EXISTS(SELECT 1 FROM reconforge.finance_entry_lines a JOIN reconforge.finance_accounts b ON b.tenant_id=a.tenant_id AND b.id=a.account_id
    WHERE a.tenant_id=t AND a.entry_id=e.id AND a.line_number=2 AND a.credit_minor=amount AND a.debit_minor=0
    AND b.account_code=CASE p.operation WHEN'Return' THEN p.payload->>'refund_liability_account_code' ELSE p.payload->>'cash_account_code' END) THEN
    RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='customer_return_owner',MESSAGE='Collected credit and refund require exact native AR liability and cash entries'; END IF;
  END IF;
  ordinal:=ordinal+1;
 END LOOP;
 FOR v IN SELECT * FROM reconforge.customer_return_events WHERE tenant_id=t AND plan_id=i LOOP
  IF v.actor_id=maker OR(v.operation IN('post','cancel') AND r IS NOT NULL AND v.actor_id=r.actor_id)
  OR(v.operation<>'post' AND v.effects<>'[]'::jsonb) OR(v.operation='post' AND jsonb_array_length(v.effects)<>ordinal)
  OR NOT reconforge.customer_return_event(t,i,v.audit_event_id,v.outbox_event_id,v.actor_id,'customer_return_'||v.operation,
   jsonb_build_object('plan_digest',seal,'reason',v.reason,'effects',v.effects)) THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='customer_return_owner',MESSAGE='Credit lifecycle requires independently governed exact audit and outbox evidence'; END IF;
 END LOOP;
 FOR command IN SELECT * FROM reconforge.customer_return_commands WHERE tenant_id=t AND plan_id=i LOOP
  expected_phase:=CASE command.operation WHEN'prepare' THEN 0 WHEN'prepare_refund' THEN 0 WHEN'review' THEN 1 WHEN'post' THEN 2 ELSE 3 END;
  IF command.request_digest IS DISTINCT FROM reconforge.irp_digest(command.request_json)
  OR command.request_json->>'operation' IS DISTINCT FROM command.operation OR command.request_json->>'actor_id' IS DISTINCT FROM command.actor_id
  OR command.workspace_id IS DISTINCT FROM p.workspace_id OR command.response_json IS DISTINCT FROM reconforge.customer_return_public(t,i,expected_phase)
  OR(expected_phase=0 AND command.request_json->'request' IS DISTINCT FROM p.payload->'request')
  OR command.actor_id IS DISTINCT FROM(CASE expected_phase WHEN 0 THEN maker WHEN 1 THEN r.actor_id WHEN 2 THEN l.actor_id ELSE c.actor_id END)
  OR(expected_phase<>0 AND command.request_json->'request' IS DISTINCT FROM jsonb_build_object('plan_id',i,'expected_plan_digest',seal,'reason',
   CASE expected_phase WHEN 1 THEN r.reason WHEN 2 THEN l.reason ELSE c.reason END)) THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='customer_return_owner',MESSAGE='Credit retry requires its exact original request actor and acknowledgement'; END IF;
 END LOOP;
 IF NOT EXISTS(SELECT 1 FROM reconforge.customer_return_commands WHERE tenant_id=t AND plan_id=i AND operation=CASE p.operation WHEN'Return' THEN'prepare' ELSE'prepare_refund' END)
 OR(r IS NOT NULL AND NOT EXISTS(SELECT 1 FROM reconforge.customer_return_commands WHERE tenant_id=t AND plan_id=i AND operation='review'))
 OR(l IS NOT NULL AND NOT EXISTS(SELECT 1 FROM reconforge.customer_return_commands WHERE tenant_id=t AND plan_id=i AND operation='post'))
 OR(c IS NOT NULL AND NOT EXISTS(SELECT 1 FROM reconforge.customer_return_commands WHERE tenant_id=t AND plan_id=i AND operation='cancel')) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='customer_return_owner',MESSAGE='Every credit phase requires its retained immutable command'; END IF;
END $cr$;
"""

_NATIVE_SQL = r"""
CREATE FUNCTION reconforge.customer_return_native_admit() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $cr$
DECLARE marker TEXT;candidate TEXT;h RECORD;p RECORD;changed JSONB;
BEGIN
 changed:=CASE WHEN TG_OP='DELETE' THEN to_jsonb(OLD) ELSE to_jsonb(NEW) END;
 IF TG_TABLE_NAME='ar_invoices' THEN
  IF TG_OP='INSERT' AND NEW.customer_return_owner_id IS NULL THEN RETURN NEW; END IF;
  IF TG_OP<>'INSERT' AND OLD.customer_return_owner_id IS NULL AND NEW.customer_return_owner_id IS NULL THEN RETURN NEW; END IF;
  marker:=COALESCE(NEW.customer_return_owner_id,OLD.customer_return_owner_id);
  SELECT * INTO p FROM reconforge.customer_return_plans WHERE tenant_id=changed->>'tenant_id' AND id=marker AND operation='Return';
  IF p IS NULL OR p.invoice_id IS DISTINCT FROM NEW.id OR(p.phase=2 AND NEW.customer_return_owner_id IS DISTINCT FROM marker)
  OR(NEW.customer_return_owner_id IS NULL AND p.phase<>3) THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='customer_return_owner',MESSAGE='Original invoice credit reservation requires its complete immutable owner'; END IF;
 ELSIF TG_TABLE_NAME IN('ar_receipt_allocations','commercial_collection_plans') THEN
  candidate:=CASE TG_TABLE_NAME WHEN'ar_receipt_allocations' THEN changed->>'invoice_id' ELSE changed->>'source_id' END;
  SELECT * INTO h FROM reconforge.ar_invoices WHERE tenant_id=changed->>'tenant_id' AND id=candidate;
  IF h.customer_return_owner_id IS NULL THEN RETURN COALESCE(NEW,OLD); END IF;
  RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='customer_return_owner',MESSAGE='A retained whole credit claims its original invoice residual and prohibits extra collections';
 ELSIF TG_TABLE_NAME='inventory_valuation_reversals' THEN
  IF left(NEW.original_valuation_document_id,6)<>'STVAL-' AND left(NEW.reversal_number,4)<>'CR1-' THEN RETURN NEW; END IF;
  IF NOT EXISTS(SELECT 1 FROM reconforge.customer_return_plans q WHERE q.tenant_id=NEW.tenant_id AND q.operation='Return'
   AND q.payload->>'valuation_reversal_id'=NEW.id AND q.payload->'source_snapshot'->'stock'->>'valuation_id'=NEW.original_valuation_document_id) THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='customer_return_owner',MESSAGE='Original stock consumption restitution requires its native credit owner'; END IF;
 END IF;
 RETURN COALESCE(NEW,OLD);
END $cr$;
CREATE TRIGGER customer_return_invoice_admission BEFORE INSERT OR UPDATE ON reconforge.ar_invoices FOR EACH ROW EXECUTE FUNCTION reconforge.customer_return_native_admit();
CREATE TRIGGER customer_return_allocation_admission BEFORE INSERT OR UPDATE OR DELETE ON reconforge.ar_receipt_allocations FOR EACH ROW EXECUTE FUNCTION reconforge.customer_return_native_admit();
CREATE TRIGGER customer_return_collection_admission BEFORE INSERT ON reconforge.commercial_collection_plans FOR EACH ROW EXECUTE FUNCTION reconforge.customer_return_native_admit();
CREATE TRIGGER customer_return_restitution_admission BEFORE INSERT OR UPDATE ON reconforge.inventory_valuation_reversals FOR EACH ROW EXECUTE FUNCTION reconforge.customer_return_native_admit();
CREATE FUNCTION reconforge.customer_return_reverse_close() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $cr$
DECLARE changes JSONB[];changed JSONB;candidate TEXT;marker TEXT;p RECORD;
BEGIN
 changes:=CASE TG_OP WHEN'INSERT' THEN ARRAY[to_jsonb(NEW)] WHEN'DELETE' THEN ARRAY[to_jsonb(OLD)] ELSE ARRAY[to_jsonb(OLD),to_jsonb(NEW)] END;
 FOREACH changed IN ARRAY changes LOOP
  candidate:=NULL;marker:=NULL;
  IF TG_TABLE_NAME='customer_return_plans' THEN candidate:=changed->>'id';
  ELSIF TG_TABLE_NAME IN('customer_return_events','customer_return_commands') THEN candidate:=changed->>'plan_id';
  ELSIF TG_TABLE_NAME='ar_invoices' THEN candidate:=changed->>'customer_return_owner_id';
  ELSIF TG_TABLE_NAME='finance_entries' THEN candidate:=changed->>'external_reference';marker:=changed->>'entry_number';
  ELSIF TG_TABLE_NAME IN('finance_entry_lines','finance_posting_effects') THEN SELECT external_reference,entry_number INTO candidate,marker FROM reconforge.finance_entries WHERE tenant_id=changed->>'tenant_id' AND id=changed->>'entry_id';
  ELSIF TG_TABLE_NAME='finance_entry_line_dimensions' THEN SELECT e.external_reference,e.entry_number INTO candidate,marker FROM reconforge.finance_entries e
   JOIN reconforge.finance_entry_lines l ON l.tenant_id=e.tenant_id AND l.entry_id=e.id WHERE l.tenant_id=changed->>'tenant_id' AND l.id=changed->>'entry_line_id';
  ELSIF TG_TABLE_NAME='inventory_movements' THEN candidate:=changed->>'source_reference';marker:=changed->>'movement_number';
  ELSIF TG_TABLE_NAME='inventory_movement_lines' THEN SELECT source_reference,movement_number INTO candidate,marker FROM reconforge.inventory_movements WHERE tenant_id=changed->>'tenant_id' AND id=changed->>'movement_id';
  ELSIF TG_TABLE_NAME='inventory_valuation_reversals' THEN marker:=changed->>'reversal_number';candidate:=lower(marker);candidate:=replace(candidate,'cr1-','CR1-');
  ELSIF TG_TABLE_NAME='inventory_valuation_reversal_effects' THEN SELECT reversal_number INTO marker FROM reconforge.inventory_valuation_reversals WHERE tenant_id=changed->>'tenant_id' AND id=changed->>'reversal_id';candidate:=replace(lower(marker),'cr1-','CR1-');
  ELSIF TG_TABLE_NAME IN('domain_audit_events','outbox_events') THEN candidate:=CASE TG_TABLE_NAME WHEN'domain_audit_events' THEN changed->>'object_id' ELSE changed->>'aggregate_id' END;
  END IF;
  IF candidate IS NULL OR(candidate!~'^(CR1|CRF1)-' AND COALESCE(marker,'')!~'^(CR1|CRF1)-') THEN CONTINUE; END IF;
  PERFORM reconforge.customer_return_close(changed->>'tenant_id',candidate);
 END LOOP;
 RETURN NULL;
END $cr$;
DO $cr$ DECLARE n TEXT;BEGIN
 FOREACH n IN ARRAY ARRAY['customer_return_plans','customer_return_events','customer_return_commands','ar_invoices','finance_entries',
 'finance_entry_lines','finance_entry_line_dimensions','finance_posting_effects','inventory_movements','inventory_movement_lines',
 'inventory_valuation_reversals','inventory_valuation_reversal_effects','domain_audit_events','outbox_events'] LOOP
  EXECUTE format('CREATE CONSTRAINT TRIGGER customer_return_source_closure AFTER INSERT OR UPDATE OR DELETE ON reconforge.%I DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION reconforge.customer_return_reverse_close()',n);
 END LOOP;
END $cr$;
"""

_FORWARD_SQL = r"""
CREATE FUNCTION reconforge.customer_return_projection(t TEXT,i TEXT) RETURNS JSONB LANGUAGE plpgsql STABLE SET search_path=pg_catalog AS $cr$
DECLARE marker TEXT;p RECORD;
BEGIN
 SELECT customer_return_owner_id INTO marker FROM reconforge.ar_invoices WHERE tenant_id=t AND id=i;
 IF marker IS NULL THEN RETURN '{}'::jsonb; END IF;
 PERFORM reconforge.customer_return_close(t,marker);
 SELECT * INTO p FROM reconforge.customer_return_plans WHERE tenant_id=t AND id=marker AND invoice_id=i AND operation='Return';
 IF p.id IS NULL THEN RAISE EXCEPTION 'Native credited invoice requires retained CR1 source evidence'; END IF;
 IF p.phase=2 THEN RETURN jsonb_build_object('credit_memo_id',p.id,'credited_minor',p.payload->>'credit_minor',
 'outstanding_minor','0','refund_due_minor',reconforge.customer_return_refund_due(t,p.id)::text,'pending_return_id',NULL); END IF;
 RETURN jsonb_build_object('pending_return_id',p.id,'credit_memo_id',NULL,'credited_minor','0');
END $cr$;
CREATE FUNCTION reconforge.customer_return_credited(t TEXT,i TEXT) RETURNS BOOLEAN LANGUAGE plpgsql STABLE SET search_path=pg_catalog AS $cr$
DECLARE marker TEXT;state TEXT;reason TEXT;p RECORD;
BEGIN
 SELECT customer_return_owner_id,status,cancel_reason INTO marker,state,reason FROM reconforge.ar_invoices WHERE tenant_id=t AND id=i;
 IF marker IS NULL THEN RETURN FALSE; END IF;
 SELECT * INTO p FROM reconforge.customer_return_plans WHERE tenant_id=t AND id=marker AND invoice_id=i AND operation='Return';
 IF p.id IS NULL THEN RAISE EXCEPTION 'Native credited invoice requires retained CR1 source evidence'; END IF;
 RETURN p.phase=2 AND state='Cancelled' AND reason=p.id;
END $cr$;
CREATE FUNCTION reconforge.customer_return_inverse_entry(t TEXT,s TEXT,e TEXT) RETURNS BOOLEAN LANGUAGE plpgsql STABLE SET search_path=pg_catalog AS $cr$
DECLARE number TEXT;reference TEXT;
BEGIN
 SELECT entry_number,external_reference INTO number,reference FROM reconforge.finance_entries WHERE tenant_id=t AND id=e;
 IF number IS NULL OR left(upper(number),4)<>'CR1-' OR left(upper(coalesce(reference,'')),4)<>'CR1-' THEN RETURN FALSE; END IF;
 RETURN EXISTS(SELECT 1 FROM reconforge.customer_return_plans p CROSS JOIN LATERAL jsonb_array_elements(p.payload->'entries') x
 WHERE p.tenant_id=t AND p.source_order_id=s AND p.operation='Return' AND x->>'entry_id'=e AND x->>'original_effect_id' IS NOT NULL);
END $cr$;
DO $cr$ DECLARE definition TEXT;anchor TEXT;
BEGIN
 definition:=pg_get_functiondef('reconforge.stock_commerce_public(reconforge.stock_commerce_orders)'::regprocedure);
 anchor:='id=s.collection_plan_id)) ORDER BY t.created_version) tranches';
 IF position(anchor IN definition)=0 THEN RAISE EXCEPTION 'Retained commercial tranche projection differs'; END IF;
 definition:=replace(definition,anchor,'id=s.collection_plan_id))||reconforge.customer_return_projection(s.tenant_id,s.invoice_id) ORDER BY t.created_version) tranches');
 EXECUTE definition;
 definition:=pg_get_functiondef('reconforge.stock_sales_close(text,text)'::regprocedure);
 anchor:='OR EXISTS(SELECT 1 FROM reconforge.finance_entries WHERE tenant_id=t AND reverses_posting_id=d.cogs_effect_id)';
 IF position(anchor IN definition)=0 THEN RAISE EXCEPTION 'Retained StockSales inverse guard differs'; END IF;
 definition:=replace(definition,anchor,'OR EXISTS(SELECT 1 FROM reconforge.finance_entries WHERE tenant_id=t AND reverses_posting_id=d.cogs_effect_id AND NOT reconforge.customer_return_inverse_entry(t,d.id,id))');
 anchor:='OR EXISTS(SELECT 1 FROM reconforge.finance_posting_effects WHERE tenant_id=t AND reverses_effect_id=d.cogs_effect_id)';
 definition:=replace(definition,anchor,'OR EXISTS(SELECT 1 FROM reconforge.finance_posting_effects WHERE tenant_id=t AND reverses_effect_id=d.cogs_effect_id AND NOT reconforge.customer_return_inverse_entry(t,d.id,entry_id))');
 definition:=replace(definition,'invoice.status IS DISTINCT FROM(CASE WHEN s=7 THEN''Submitted'' WHEN s=12 THEN''Paid'' ELSE''Approved'' END)',
  '(NOT reconforge.customer_return_credited(t,d.invoice_id) AND invoice.status IS DISTINCT FROM(CASE WHEN s=7 THEN''Submitted'' WHEN s=12 THEN''Paid'' ELSE''Approved'' END))');
 definition:=replace(definition,'invoice.status IN(''Approved'',''PartiallyPaid'',''Paid'')','(invoice.status IN(''Approved'',''PartiallyPaid'',''Paid'') OR reconforge.customer_return_credited(t,d.invoice_id))');
 anchor:='posted:=EXISTS(SELECT 1 FROM reconforge.operational_finance_links WHERE tenant_id=t AND plan_id=p.id);';
 IF position(anchor IN definition)=0 THEN RAISE EXCEPTION 'Retained StockSales invoice posting guard differs'; END IF;
 definition:=replace(definition,anchor,anchor||$inverse$
  IF EXISTS(SELECT 1 FROM reconforge.finance_entries inverse_entry JOIN reconforge.operational_finance_links original_link
   ON original_link.tenant_id=inverse_entry.tenant_id AND original_link.posting_effect_id=inverse_entry.reverses_posting_id WHERE original_link.tenant_id=t AND original_link.plan_id=d.invoice_plan_id
   AND NOT reconforge.customer_return_inverse_entry(t,d.id,inverse_entry.id))
  OR EXISTS(SELECT 1 FROM reconforge.finance_posting_effects inverse_effect JOIN reconforge.operational_finance_links original_link
   ON original_link.tenant_id=inverse_effect.tenant_id AND original_link.posting_effect_id=inverse_effect.reverses_effect_id WHERE original_link.tenant_id=t AND original_link.plan_id=d.invoice_plan_id
   AND NOT reconforge.customer_return_inverse_entry(t,d.id,inverse_effect.entry_id)) THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='stock_sales_owner_phase',MESSAGE='Original StockSales revenue inverse requires complete original-source credit';
  END IF;
$inverse$);
 EXECUTE definition;
 definition:=pg_get_functiondef('reconforge.stock_sales_native_close()'::regprocedure);
 anchor:='OR d.cogs_effect_id=reverse_effect';
 IF position(anchor IN definition)=0 THEN RAISE EXCEPTION 'Retained StockSales reverse dispatch differs'; END IF;
 definition:=replace(definition,anchor,anchor||' OR EXISTS(SELECT 1 FROM reconforge.operational_finance_links l WHERE l.tenant_id=d.tenant_id AND l.plan_id=d.invoice_plan_id AND l.posting_effect_id=reverse_effect)');
 EXECUTE definition;
 definition:=pg_get_functiondef('reconforge.collection_invoice_close(text,text)'::regprocedure);
 definition:=replace(definition,'OR h.status IS DISTINCT FROM (CASE','OR (NOT reconforge.customer_return_credited(t,i) AND h.status IS DISTINCT FROM (CASE');
 definition:=replace(definition,'ELSE''PartiallyPaid'' END)','ELSE''PartiallyPaid'' END))');
 EXECUTE definition;
 definition:=pg_get_functiondef('reconforge.collection_close(text,text)'::regprocedure);
 definition:=replace(definition,'OR h.status NOT IN (''Approved'',''PartiallyPaid'',''Paid'')','OR (h.status NOT IN (''Approved'',''PartiallyPaid'',''Paid'') AND NOT reconforge.customer_return_credited(t,p.source_id))');
 EXECUTE definition;
 definition:=pg_get_functiondef('reconforge.ops_close_plan(text,text)'::regprocedure);
 definition:=replace(definition,'status NOT IN (''Submitted'',''Approved'',''PartiallyPaid'',''Paid'')','(status NOT IN (''Submitted'',''Approved'',''PartiallyPaid'',''Paid'') AND NOT reconforge.customer_return_credited(t,p.source_id))');
 definition:=replace(definition,'status NOT IN (''Approved'',''PartiallyPaid'',''Paid'')','(status NOT IN (''Approved'',''PartiallyPaid'',''Paid'') AND NOT reconforge.customer_return_credited(t,p.source_id))');
 EXECUTE definition;
 definition:=pg_get_functiondef('reconforge.inventory_valuation_reversal_guard()'::regprocedure);
 anchor:='e.status=''Draft'' AND e.workspace_id=OLD.workspace_id';
 IF position(anchor IN definition)=0 THEN RAISE EXCEPTION 'Retained FIFO reversal finance phase differs'; END IF;
 definition:=replace(definition,anchor,'(e.status=''Draft'' OR(e.status=''Validated'' AND EXISTS(SELECT 1 FROM reconforge.customer_return_plans p WHERE p.tenant_id=e.tenant_id AND p.operation=''Return'' AND p.phase=1 AND p.payload->>''valuation_reversal_id''=OLD.id AND p.payload->''entries''->0->>''entry_id''=e.id))) AND e.workspace_id=OLD.workspace_id');
 EXECUTE definition;
END $cr$;
"""

UPGRADE_SQL = _STORAGE_SQL + _CLOSURE_SQL + _NATIVE_SQL + _FORWARD_SQL

# Downgrade refuses any retained owner history. Exact function bodies restored by
# inverse substitutions, preserving other independently installed source owners.
DOWNGRADE_SQL = r"""
DO $cr$ BEGIN IF EXISTS(SELECT 1 FROM reconforge.customer_return_plans) THEN
 RAISE EXCEPTION 'Customer credit downgrade refuses to discard immutable native financial history; restore the verified backup'; END IF; END $cr$;
DO $cr$ DECLARE n TEXT;definition TEXT;BEGIN
 definition:=pg_get_functiondef('reconforge.stock_commerce_public(reconforge.stock_commerce_orders)'::regprocedure);
 definition:=replace(definition,')||reconforge.customer_return_projection(s.tenant_id,s.invoice_id) ORDER BY t.created_version)',') ORDER BY t.created_version)');
 EXECUTE definition;
 definition:=pg_get_functiondef('reconforge.stock_sales_native_close()'::regprocedure);
 definition:=replace(definition,' OR EXISTS(SELECT 1 FROM reconforge.operational_finance_links l WHERE l.tenant_id=d.tenant_id AND l.plan_id=d.invoice_plan_id AND l.posting_effect_id=reverse_effect)','');
 EXECUTE definition;
 FOREACH n IN ARRAY ARRAY['customer_return_plans','customer_return_events','customer_return_commands','ar_invoices','finance_entries',
 'finance_entry_lines','finance_entry_line_dimensions','finance_posting_effects','inventory_movements','inventory_movement_lines',
 'inventory_valuation_reversals','inventory_valuation_reversal_effects','domain_audit_events','outbox_events'] LOOP
  EXECUTE format('DROP TRIGGER customer_return_source_closure ON reconforge.%I',n);
 END LOOP;
 FOREACH n IN ARRAY ARRAY['stock_sales_close(text,text)','collection_invoice_close(text,text)','collection_close(text,text)','ops_close_plan(text,text)','inventory_valuation_reversal_guard()'] LOOP
  definition:=pg_get_functiondef(('reconforge.'||n)::regprocedure);
  definition:=replace(definition,' AND NOT reconforge.customer_return_inverse_entry(t,d.id,id)','');
  definition:=replace(definition,' AND NOT reconforge.customer_return_inverse_entry(t,d.id,entry_id)','');
  definition:=replace(definition,$inverse$
  IF EXISTS(SELECT 1 FROM reconforge.finance_entries inverse_entry JOIN reconforge.operational_finance_links original_link
   ON original_link.tenant_id=inverse_entry.tenant_id AND original_link.posting_effect_id=inverse_entry.reverses_posting_id WHERE original_link.tenant_id=t AND original_link.plan_id=d.invoice_plan_id
   AND NOT reconforge.customer_return_inverse_entry(t,d.id,inverse_entry.id))
  OR EXISTS(SELECT 1 FROM reconforge.finance_posting_effects inverse_effect JOIN reconforge.operational_finance_links original_link
   ON original_link.tenant_id=inverse_effect.tenant_id AND original_link.posting_effect_id=inverse_effect.reverses_effect_id WHERE original_link.tenant_id=t AND original_link.plan_id=d.invoice_plan_id
   AND NOT reconforge.customer_return_inverse_entry(t,d.id,inverse_effect.entry_id)) THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='stock_sales_owner_phase',MESSAGE='Original StockSales revenue inverse requires complete original-source credit';
  END IF;
$inverse$,'');
  definition:=replace(definition,'(NOT reconforge.customer_return_credited(t,d.invoice_id) AND invoice.status IS DISTINCT FROM(CASE WHEN s=7 THEN''Submitted'' WHEN s=12 THEN''Paid'' ELSE''Approved'' END))','invoice.status IS DISTINCT FROM(CASE WHEN s=7 THEN''Submitted'' WHEN s=12 THEN''Paid'' ELSE''Approved'' END)');
  definition:=replace(definition,'(invoice.status IN(''Approved'',''PartiallyPaid'',''Paid'') OR reconforge.customer_return_credited(t,d.invoice_id))','invoice.status IN(''Approved'',''PartiallyPaid'',''Paid'')');
  definition:=replace(definition,'(NOT reconforge.customer_return_credited(t,i) AND h.status IS DISTINCT FROM (CASE WHEN paid=0 THEN''Approved'' WHEN paid=h.total_minor THEN''Paid'' ELSE''PartiallyPaid'' END))','h.status IS DISTINCT FROM (CASE WHEN paid=0 THEN''Approved'' WHEN paid=h.total_minor THEN''Paid'' ELSE''PartiallyPaid'' END)');
  definition:=replace(definition,'(h.status NOT IN (''Approved'',''PartiallyPaid'',''Paid'') AND NOT reconforge.customer_return_credited(t,p.source_id))','h.status NOT IN (''Approved'',''PartiallyPaid'',''Paid'')');
  definition:=replace(definition,'(status NOT IN (''Submitted'',''Approved'',''PartiallyPaid'',''Paid'') AND NOT reconforge.customer_return_credited(t,p.source_id))','status NOT IN (''Submitted'',''Approved'',''PartiallyPaid'',''Paid'')');
  definition:=replace(definition,'(status NOT IN (''Approved'',''PartiallyPaid'',''Paid'') AND NOT reconforge.customer_return_credited(t,p.source_id))','status NOT IN (''Approved'',''PartiallyPaid'',''Paid'')');
  definition:=replace(definition,'(e.status=''Draft'' OR(e.status=''Validated'' AND EXISTS(SELECT 1 FROM reconforge.customer_return_plans p WHERE p.tenant_id=e.tenant_id AND p.operation=''Return'' AND p.phase=1 AND p.payload->>''valuation_reversal_id''=OLD.id AND p.payload->''entries''->0->>''entry_id''=e.id)))','e.status=''Draft''');
  EXECUTE definition;
 END LOOP;
END $cr$;
DROP TRIGGER customer_return_invoice_admission ON reconforge.ar_invoices;
DROP TRIGGER customer_return_allocation_admission ON reconforge.ar_receipt_allocations;
DROP TRIGGER customer_return_collection_admission ON reconforge.commercial_collection_plans;
DROP TRIGGER customer_return_restitution_admission ON reconforge.inventory_valuation_reversals;
DROP TRIGGER immutable ON reconforge.customer_return_plans;
DROP TRIGGER immutable ON reconforge.customer_return_events;
DROP TRIGGER immutable ON reconforge.customer_return_commands;
DROP FUNCTION reconforge.customer_return_reverse_close();DROP FUNCTION reconforge.customer_return_native_admit();
DROP FUNCTION reconforge.customer_return_close(TEXT,TEXT);DROP FUNCTION reconforge.customer_return_public(TEXT,TEXT,INTEGER);
DROP FUNCTION reconforge.customer_return_event(TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,JSONB);
DROP FUNCTION reconforge.customer_return_protect();DROP FUNCTION reconforge.customer_return_authority(TEXT,TEXT,TEXT);
DROP FUNCTION reconforge.customer_return_credited(TEXT,TEXT);DROP FUNCTION reconforge.customer_return_inverse_entry(TEXT,TEXT,TEXT);
DROP FUNCTION reconforge.customer_return_projection(TEXT,TEXT);
DROP FUNCTION reconforge.customer_return_refund_due(TEXT,TEXT);DROP FUNCTION reconforge.customer_return_refund_available(TEXT,TEXT);
DROP FUNCTION reconforge.customer_return_source_available(TEXT,TEXT);DROP FUNCTION reconforge.customer_return_accounts(TEXT,TEXT,TEXT,TEXT,TEXT,BOOLEAN);
DROP FUNCTION reconforge.customer_return_source(TEXT,TEXT);
DROP TABLE reconforge.customer_return_commands,reconforge.customer_return_events,reconforge.customer_return_plans;
ALTER TABLE reconforge.ar_invoices DROP COLUMN customer_return_owner_id;
"""
