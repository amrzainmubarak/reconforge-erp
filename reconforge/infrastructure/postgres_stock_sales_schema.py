"""Exact source closure and shared-lock-affine reservations for product sales."""
from __future__ import annotations

from reconforge.infrastructure.postgres_sales_revenue_schema import POSTGRES_SALES_REVENUE_SCHEMA_SQL

POSTGRES_STOCK_SALES_SCHEMA_SQL = r"""
CREATE TABLE reconforge.stock_sales_orders (
 tenant_id TEXT NOT NULL,id TEXT NOT NULL,workspace_id TEXT NOT NULL,organization_id TEXT NOT NULL,legal_entity_id TEXT NOT NULL,
 customer_id TEXT NOT NULL,item_id TEXT NOT NULL,uom_id TEXT NOT NULL,location_id TEXT NOT NULL,number TEXT NOT NULL,
 currency_code TEXT NOT NULL,quantity_scaled BIGINT NOT NULL CHECK(quantity_scaled>0),quantity_precision INTEGER NOT NULL CHECK(quantity_precision BETWEEN 0 AND 6),
 total_minor BIGINT NOT NULL CHECK(total_minor BETWEEN 1 AND 9000000000000000000),source JSONB NOT NULL,source_digest TEXT NOT NULL CHECK(source_digest~'^[0-9a-f]{64}$'),
 status TEXT NOT NULL DEFAULT'Draft' CHECK(status IN('Draft','Submitted','Approved','Reserved','IssuePrepared','IssueReviewed','Delivered',
 'InvoicePrepared','InvoiceReviewed','Invoiced','CollectionPrepared','CollectionReviewed','Paid','Cancelled')),
 created_by TEXT NOT NULL,approved_by TEXT,issue_plan JSONB,cogs_entry_id TEXT,issue_reviewer_id TEXT,movement_id TEXT,valuation_id TEXT,cogs_effect_id TEXT,
 invoice_id TEXT,invoice_plan_id TEXT,invoice_parameters JSONB,collection_plan_id TEXT,collection_parameters JSONB,receipt_id TEXT,
 row_version INTEGER NOT NULL DEFAULT 1 CHECK(row_version>0),created_at TIMESTAMPTZ NOT NULL DEFAULT now(),updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 PRIMARY KEY(tenant_id,id),UNIQUE(tenant_id,workspace_id,number),UNIQUE(tenant_id,cogs_entry_id),UNIQUE(tenant_id,invoice_id),
 FOREIGN KEY(tenant_id,workspace_id) REFERENCES reconforge.domain_workspaces(tenant_id,id),
 FOREIGN KEY(tenant_id,organization_id) REFERENCES reconforge.organizations(tenant_id,id),
 FOREIGN KEY(tenant_id,legal_entity_id) REFERENCES reconforge.legal_entities(tenant_id,id),
 FOREIGN KEY(tenant_id,customer_id) REFERENCES reconforge.ar_customers(tenant_id,id),
 FOREIGN KEY(tenant_id,item_id) REFERENCES reconforge.inventory_items(tenant_id,id),
 FOREIGN KEY(tenant_id,uom_id) REFERENCES reconforge.inventory_units_of_measure(tenant_id,id),
 FOREIGN KEY(tenant_id,location_id) REFERENCES reconforge.inventory_locations(tenant_id,id),
 FOREIGN KEY(tenant_id,created_by) REFERENCES reconforge.identity_users(tenant_id,id),
 FOREIGN KEY(tenant_id,approved_by) REFERENCES reconforge.identity_users(tenant_id,id),
 FOREIGN KEY(tenant_id,issue_reviewer_id) REFERENCES reconforge.identity_users(tenant_id,id),
 FOREIGN KEY(tenant_id,cogs_entry_id) REFERENCES reconforge.finance_entries(tenant_id,id),
 FOREIGN KEY(tenant_id,invoice_id) REFERENCES reconforge.ar_invoices(tenant_id,id),
 FOREIGN KEY(tenant_id,receipt_id) REFERENCES reconforge.ar_receipts(tenant_id,id)
);
CREATE TABLE reconforge.stock_sales_reservations (
 tenant_id TEXT NOT NULL,order_id TEXT NOT NULL,workspace_id TEXT NOT NULL,organization_id TEXT NOT NULL,legal_entity_id TEXT NOT NULL,
 location_id TEXT NOT NULL,item_id TEXT NOT NULL,quantity_scaled BIGINT NOT NULL CHECK(quantity_scaled>0),
 state TEXT NOT NULL DEFAULT'Active' CHECK(state IN('Active','Consumed','Released')),created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 PRIMARY KEY(tenant_id,order_id),FOREIGN KEY(tenant_id,order_id) REFERENCES reconforge.stock_sales_orders(tenant_id,id)
);
CREATE INDEX stock_sales_active_stock ON reconforge.stock_sales_reservations(tenant_id,workspace_id,legal_entity_id,location_id,item_id) WHERE state='Active';
CREATE TABLE reconforge.stock_sales_issue_claims (
 tenant_id TEXT NOT NULL,order_id TEXT NOT NULL,workspace_id TEXT NOT NULL,legal_entity_id TEXT NOT NULL,item_id TEXT NOT NULL,
 entry_id TEXT NOT NULL,payload JSONB NOT NULL,plan_digest TEXT NOT NULL CHECK(plan_digest~'^[0-9a-f]{64}$'),
 state TEXT NOT NULL DEFAULT'Active' CHECK(state IN('Active','Consumed','Released')),created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 PRIMARY KEY(tenant_id,order_id),UNIQUE(tenant_id,entry_id),FOREIGN KEY(tenant_id,order_id) REFERENCES reconforge.stock_sales_orders(tenant_id,id),
 FOREIGN KEY(tenant_id,entry_id) REFERENCES reconforge.finance_entries(tenant_id,id) DEFERRABLE INITIALLY DEFERRED
);
CREATE UNIQUE INDEX stock_sales_active_fifo ON reconforge.stock_sales_issue_claims(tenant_id,workspace_id,legal_entity_id,item_id) WHERE state='Active';
CREATE TABLE reconforge.stock_sales_events (
 tenant_id TEXT NOT NULL,order_id TEXT NOT NULL,version INTEGER NOT NULL,actor_id TEXT NOT NULL,operation TEXT NOT NULL,
 reason TEXT NOT NULL,status TEXT NOT NULL,audit_event_id TEXT NOT NULL,created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 PRIMARY KEY(tenant_id,order_id,version),FOREIGN KEY(tenant_id,order_id) REFERENCES reconforge.stock_sales_orders(tenant_id,id),
 FOREIGN KEY(tenant_id,actor_id) REFERENCES reconforge.identity_users(tenant_id,id),
 FOREIGN KEY(tenant_id,audit_event_id) REFERENCES reconforge.domain_audit_events(tenant_id,id)
);
CREATE TABLE reconforge.stock_sales_commands (
 tenant_id TEXT NOT NULL,workspace_id TEXT NOT NULL,command_id TEXT NOT NULL,order_id TEXT NOT NULL,version INTEGER NOT NULL,
 actor_id TEXT NOT NULL,operation TEXT NOT NULL,request_digest TEXT NOT NULL CHECK(request_digest~'^[0-9a-f]{64}$'),request JSONB NOT NULL,result JSONB NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(),PRIMARY KEY(tenant_id,workspace_id,command_id),UNIQUE(tenant_id,order_id,version),
 FOREIGN KEY(tenant_id,order_id) REFERENCES reconforge.stock_sales_orders(tenant_id,id),FOREIGN KEY(tenant_id,actor_id) REFERENCES reconforge.identity_users(tenant_id,id)
);
CREATE INDEX stock_sales_scope ON reconforge.stock_sales_orders(tenant_id,workspace_id,organization_id,legal_entity_id,id COLLATE"C");
CREATE FUNCTION reconforge.stock_sales_stage(s TEXT) RETURNS INTEGER LANGUAGE sql IMMUTABLE SET search_path=pg_catalog AS $$
 SELECT array_position(ARRAY['Draft','Submitted','Approved','Reserved','IssuePrepared','IssueReviewed','Delivered','InvoicePrepared',
 'InvoiceReviewed','Invoiced','CollectionPrepared','CollectionReviewed','Paid'],s)-1 $$;
CREATE FUNCTION reconforge.stock_sales_fifo_value(v BIGINT,q BIGINT,t BIGINT) RETURNS BIGINT LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog AS $$
DECLARE base NUMERIC; residual NUMERIC;
BEGIN
 IF v<=0 OR q<=0 OR t<=0 OR t>q THEN RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='stock_sales_owner_phase',MESSAGE='Invalid exact FIFO ratio.'; END IF;
 IF t=q THEN RETURN v; END IF;
 base:=floor(v::numeric*t/q); residual:=v::numeric*t-base*q;
 IF residual*2>q OR(residual*2=q AND mod(base,2)=1) THEN base:=base+1; END IF;
 IF base<=0 OR base>=v THEN RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='stock_sales_owner_phase',MESSAGE='Unrepresentable partial FIFO cost.'; END IF;
 RETURN base::bigint;
END $$;
CREATE FUNCTION reconforge.stock_sales_public(d reconforge.stock_sales_orders) RETURNS JSONB LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
 SELECT jsonb_build_object('id',d.id,'workspace_id',d.workspace_id,'organization_id',d.organization_id,'legal_entity_id',d.legal_entity_id,
 'number',d.number,'status',d.status,'row_version',d.row_version,'source_digest',d.source_digest,'currency_code',d.currency_code,
 'quantity_scaled',d.quantity_scaled::text,'quantity_precision',d.quantity_precision,'total_minor',d.total_minor::text,
 'customer_code',d.source->>'customer_code','customer_reference',d.source->>'customer_reference','item_code',d.source->>'item_code',
 'warehouse_code',d.source->>'warehouse_code','location_code',d.source->>'location_code','quantity',d.source->>'quantity','description',d.source->>'description',
 'created_by',d.created_by,'approved_by',d.approved_by,'issue_reviewer_id',d.issue_reviewer_id,
 'unit_price_minor',d.source->>'unit_price_minor','discount_basis_points',d.source->'discount_basis_points',
 'net_unit_price_minor',d.source->>'net_unit_price_minor','order_date',d.source->>'order_date','monetary_policy',d.source->'monetary_policy',
 'issue_digest',CASE WHEN d.issue_plan IS NULL THEN NULL ELSE reconforge.irp_digest(d.issue_plan) END,
 'cogs_minor',d.issue_plan->>'total_cost_minor','cogs_entry_id',d.cogs_entry_id,'movement_id',d.movement_id,'valuation_id',d.valuation_id,
 'cogs_effect_id',d.cogs_effect_id,'invoice_id',d.invoice_id,'invoice_plan_id',d.invoice_plan_id,'receipt_id',d.receipt_id,'collection_plan_id',d.collection_plan_id,
 'invoice_parameters',d.invoice_parameters,'collection_parameters',d.collection_parameters,
 'events',COALESCE((SELECT jsonb_agg(jsonb_build_object('version',e.version,'actor_id',e.actor_id,'operation',e.operation,
 'reason',e.reason,'status',e.status,'audit_event_id',e.audit_event_id) ORDER BY e.version)
 FROM reconforge.stock_sales_events e WHERE e.tenant_id=d.tenant_id AND e.order_id=d.id),'[]'::jsonb)) $$;
CREATE FUNCTION reconforge.stock_sales_protect() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF TG_OP='DELETE' OR TG_TABLE_NAME IN('stock_sales_events','stock_sales_commands') THEN
  RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='stock_sales_owner_phase',MESSAGE='Retained stock-sale history is immutable.';
 END IF;
 IF TG_TABLE_NAME='stock_sales_orders' THEN
  IF (to_jsonb(NEW)-ARRAY['status','approved_by','issue_plan','cogs_entry_id','issue_reviewer_id','movement_id','valuation_id','cogs_effect_id',
   'invoice_id','invoice_plan_id','invoice_parameters','collection_plan_id','collection_parameters','receipt_id','row_version','updated_at'])
   IS DISTINCT FROM(to_jsonb(OLD)-ARRAY['status','approved_by','issue_plan','cogs_entry_id','issue_reviewer_id','movement_id','valuation_id','cogs_effect_id',
   'invoice_id','invoice_plan_id','invoice_parameters','collection_plan_id','collection_parameters','receipt_id','row_version','updated_at'])
   OR NEW.row_version<>OLD.row_version+1 OR NOT COALESCE((reconforge.stock_sales_stage(NEW.status)=reconforge.stock_sales_stage(OLD.status)+1
    OR(NEW.status='Cancelled' AND reconforge.stock_sales_stage(OLD.status)<6)),FALSE)
   OR(OLD.issue_plan IS NOT NULL AND(NEW.issue_plan,NEW.cogs_entry_id) IS DISTINCT FROM(OLD.issue_plan,OLD.cogs_entry_id))
   OR(OLD.approved_by IS NOT NULL AND NEW.approved_by IS DISTINCT FROM OLD.approved_by)
   OR(OLD.invoice_id IS NOT NULL AND(NEW.invoice_id,NEW.invoice_plan_id,NEW.invoice_parameters) IS DISTINCT FROM(OLD.invoice_id,OLD.invoice_plan_id,OLD.invoice_parameters))
   OR(OLD.collection_plan_id IS NOT NULL AND(NEW.collection_plan_id,NEW.collection_parameters) IS DISTINCT FROM(OLD.collection_plan_id,OLD.collection_parameters))
   OR(OLD.movement_id IS NOT NULL AND(NEW.movement_id,NEW.valuation_id,NEW.cogs_effect_id) IS DISTINCT FROM(OLD.movement_id,OLD.valuation_id,OLD.cogs_effect_id)) THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='stock_sales_owner_phase',MESSAGE='Stock-sale transition or immutable source differs.';
  END IF;
 ELSE
  IF OLD.state<>'Active' OR NEW.state NOT IN('Consumed','Released') OR(to_jsonb(NEW)-'state') IS DISTINCT FROM(to_jsonb(OLD)-'state') THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='stock_sales_owner_phase',MESSAGE='Stock reservation or frozen claim is immutable.';
  END IF;
 END IF;
 RETURN NEW;
END $$;
DO $$ DECLARE n TEXT; BEGIN
 FOREACH n IN ARRAY ARRAY['stock_sales_orders','stock_sales_reservations','stock_sales_issue_claims','stock_sales_events','stock_sales_commands'] LOOP
  EXECUTE format('CREATE TRIGGER stock_sales_immutable BEFORE UPDATE OR DELETE ON reconforge.%I FOR EACH ROW EXECUTE FUNCTION reconforge.stock_sales_protect()',n);
  EXECUTE format('ALTER TABLE reconforge.%I ENABLE ROW LEVEL SECURITY',n); EXECUTE format('ALTER TABLE reconforge.%I FORCE ROW LEVEL SECURITY',n);
  IF n IN('stock_sales_orders','stock_sales_reservations') THEN
   EXECUTE format('CREATE POLICY stock_sales_scope ON reconforge.%I USING(reconforge.irp_scope(tenant_id,workspace_id,organization_id,legal_entity_id)) WITH CHECK(reconforge.irp_scope(tenant_id,workspace_id,organization_id,legal_entity_id))',n);
  ELSE
   EXECUTE format('CREATE POLICY stock_sales_scope ON reconforge.%I USING(EXISTS(SELECT 1 FROM reconforge.stock_sales_orders d WHERE d.tenant_id=%I.tenant_id AND d.id=%I.order_id AND reconforge.irp_scope(d.tenant_id,d.workspace_id,d.organization_id,d.legal_entity_id))) WITH CHECK(EXISTS(SELECT 1 FROM reconforge.stock_sales_orders d WHERE d.tenant_id=%I.tenant_id AND d.id=%I.order_id AND reconforge.irp_scope(d.tenant_id,d.workspace_id,d.organization_id,d.legal_entity_id)))',n,n,n,n,n);
  END IF;
 END LOOP;
END $$;
CREATE FUNCTION reconforge.stock_sales_capacity(t TEXT,w TEXT,e TEXT,l TEXT,i TEXT) RETURNS VOID LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE available NUMERIC; reserved NUMERIC;
BEGIN
 PERFORM pg_advisory_xact_lock(hashtextextended(w||'|'||e||'|'||l||'|'||i||'|',0));
 SELECT COALESCE(sum(CASE WHEN x.to_location_id=l THEN x.quantity_scaled ELSE 0 END-CASE WHEN x.from_location_id=l THEN x.quantity_scaled ELSE 0 END),0)
 INTO available FROM reconforge.inventory_movement_lines x JOIN reconforge.inventory_movements m ON m.tenant_id=x.tenant_id AND m.id=x.movement_id
 WHERE x.tenant_id=t AND m.workspace_id=w AND m.legal_entity_id=e AND m.status='Posted' AND x.item_id=i AND x.inventory_lot_id IS NULL;
 SELECT COALESCE(sum(quantity_scaled),0) INTO reserved FROM reconforge.stock_sales_reservations WHERE tenant_id=t AND workspace_id=w AND legal_entity_id=e
 AND location_id=l AND item_id=i AND state='Active';
 IF available<reserved THEN RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='stock_sales_owner_phase',MESSAGE='Reserved stock cannot be overcommitted or withdrawn by another owner.'; END IF;
END $$;
CREATE FUNCTION reconforge.stock_sales_admit() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE d RECORD; a TEXT:=current_setting('app.stock_sales_actor_id',true); permission TEXT; q JSONB; unit NUMERIC; amount NUMERIC;
BEGIN
 IF TG_TABLE_NAME='stock_sales_orders' THEN d:=NEW;
 ELSE SELECT * INTO d FROM reconforge.stock_sales_orders WHERE tenant_id=NEW.tenant_id AND id=NEW.order_id; END IF;
 IF TG_TABLE_NAME='stock_sales_orders' THEN
  permission:=CASE WHEN NEW.status IN('Approved','IssueReviewed','InvoiceReviewed','CollectionReviewed') THEN 'sales.approve' ELSE 'sales.manage' END;
 ELSIF TG_TABLE_NAME IN('stock_sales_events','stock_sales_commands') THEN
  permission:=CASE WHEN NEW.operation IN('approve','review-issue','review-invoice','review-collection') THEN 'sales.approve' ELSE 'sales.manage' END;
 ELSE permission:='sales.manage'; END IF;
 IF d IS NULL OR NOT reconforge.sales_revenue_actor(NEW.tenant_id,a,permission) THEN
  RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='stock_sales_owner_phase',MESSAGE='Stock-sale source requires current persisted human authority.';
 END IF;
 IF TG_TABLE_NAME='stock_sales_orders' THEN
  IF(TG_OP='INSERT' AND(NEW.status<>'Draft' OR NEW.created_by IS DISTINCT FROM a))
  OR(NEW.status='Approved' AND(NEW.approved_by IS DISTINCT FROM a OR a=NEW.created_by))
  OR(NEW.status='IssueReviewed' AND NEW.issue_reviewer_id IS DISTINCT FROM a) THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='stock_sales_owner_phase',MESSAGE='Actual creator and independent review must be retained.';
  END IF;
  q:=NEW.source; PERFORM reconforge.irp_bounded(q);
  IF reconforge.irp_digest(q) IS DISTINCT FROM NEW.source_digest OR q->>'schema_version' IS DISTINCT FROM'stock-sales-order-v1'
  OR q->>'number' IS DISTINCT FROM NEW.number OR q->>'currency_code' IS DISTINCT FROM NEW.currency_code OR q->>'tax_minor' IS DISTINCT FROM'0'
  OR q->>'discount_policy' IS DISTINCT FROM'per-unit-minor-half-up-v1' OR q->>'quantity' !~'^[0-9]+(\.[0-9]+)?$'
  OR q->>'unit_price_minor' !~'^[1-9][0-9]{0,18}$' OR(q->>'discount_basis_points')::integer NOT BETWEEN 0 AND 9999
  OR(q->>'quantity')::numeric*power(10::numeric,NEW.quantity_precision) IS DISTINCT FROM NEW.quantity_scaled::numeric THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='stock_sales_owner_phase',MESSAGE='Product order requires canonical exact source values.';
  END IF;
  unit:=floor(((q->>'unit_price_minor')::numeric*(10000-(q->>'discount_basis_points')::integer)+5000)/10000);
  amount:=round((q->>'quantity')::numeric*unit,0);
  IF unit<=0 OR unit IS DISTINCT FROM(q->>'net_unit_price_minor')::numeric OR amount IS DISTINCT FROM NEW.total_minor::numeric
  OR amount IS DISTINCT FROM(q->>'total_minor')::numeric THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='stock_sales_owner_phase',MESSAGE='Discounted product value does not reproduce its exact minor units.';
  END IF;
  IF NOT EXISTS(SELECT 1 FROM reconforge.ar_customers c JOIN reconforge.legal_entities e ON e.tenant_id=c.tenant_id AND e.id=c.legal_entity_id
   JOIN reconforge.organizations o ON o.tenant_id=e.tenant_id AND o.id=e.organization_id
   WHERE c.tenant_id=NEW.tenant_id AND c.id=NEW.customer_id AND c.workspace_id=NEW.workspace_id
   AND c.organization_id=NEW.organization_id AND c.legal_entity_id=NEW.legal_entity_id AND c.customer_code=q->>'customer_code'
   AND c.currency_code=NEW.currency_code AND o.application_workspace_id=NEW.workspace_id
   AND(TG_OP<>'INSERT' OR(c.status='Active' AND e.active AND o.active AND reconforge.sales_revenue_policy_matches(NEW.tenant_id,
    q->'monetary_policy',c.currency_code,c.currency_precision,c.currency_rounding_policy,c.currency_registry_version,c.currency_registry_digest))))
  OR NOT EXISTS(SELECT 1 FROM reconforge.inventory_items i JOIN reconforge.inventory_units_of_measure u ON u.tenant_id=i.tenant_id AND u.id=i.uom_id
   JOIN reconforge.inventory_locations l ON l.tenant_id=i.tenant_id AND l.id=NEW.location_id
   JOIN reconforge.inventory_warehouses w ON w.tenant_id=l.tenant_id AND w.id=l.warehouse_id
   WHERE i.tenant_id=NEW.tenant_id AND i.id=NEW.item_id AND i.workspace_id=NEW.workspace_id AND i.uom_id=NEW.uom_id
   AND u.decimal_places=NEW.quantity_precision AND i.item_code=q->>'item_code' AND w.warehouse_code=q->>'warehouse_code'
   AND l.location_code=q->>'location_code' AND w.workspace_id=NEW.workspace_id AND w.organization_id=NEW.organization_id
   AND w.legal_entity_id=NEW.legal_entity_id AND(TG_OP<>'INSERT' OR(i.active AND u.active AND w.active AND l.active
   AND NOT l.allow_negative AND i.tracking_mode='None' AND i.item_type<>'Service')))
  OR(q->>'quantity_scaled')::bigint IS DISTINCT FROM NEW.quantity_scaled THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='stock_sales_owner_phase',MESSAGE='Stock-sale canonical masters or monetary interpretation differs.';
  END IF;
 ELSIF TG_TABLE_NAME IN('stock_sales_commands','stock_sales_events') THEN
  IF NEW.actor_id IS DISTINCT FROM a THEN RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='stock_sales_owner_phase',MESSAGE='Evidence actor differs from actual command human.'; END IF;
 ELSE
  IF(NEW.workspace_id,NEW.legal_entity_id,NEW.item_id) IS DISTINCT FROM(d.workspace_id,d.legal_entity_id,d.item_id)
  THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='stock_sales_owner_phase',MESSAGE='Reservation differs from its exact product source.';
  END IF;
  IF TG_TABLE_NAME='stock_sales_reservations' THEN
   IF(NEW.organization_id,NEW.location_id,NEW.quantity_scaled) IS DISTINCT FROM(d.organization_id,d.location_id,d.quantity_scaled) THEN
    RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='stock_sales_owner_phase',MESSAGE='Reservation quantity/location differs from its exact product source.';
   END IF;
   PERFORM pg_advisory_xact_lock(hashtextextended(d.workspace_id||'|'||d.legal_entity_id||'|'||d.location_id||'|'||d.item_id||'|',0));
  END IF;
 END IF;
 RETURN NEW;
END $$;
DO $$ DECLARE n TEXT; BEGIN FOREACH n IN ARRAY ARRAY['stock_sales_orders','stock_sales_reservations','stock_sales_issue_claims','stock_sales_events','stock_sales_commands'] LOOP
 EXECUTE format('CREATE TRIGGER stock_sales_admission BEFORE INSERT OR UPDATE ON reconforge.%I FOR EACH ROW EXECUTE FUNCTION reconforge.stock_sales_admit()',n);
END LOOP; END $$;
CREATE FUNCTION reconforge.stock_sales_close(t TEXT,target TEXT) RETURNS VOID LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE d RECORD; s INTEGER; e RECORD; c RECORD; r RECORD; claim RECORD; entry RECORD; x JSONB; total NUMERIC:=0; quantity NUMERIC:=0;
 invoice RECORD; p RECORD; reviewed BOOLEAN; posted BOOLEAN; native_receipt RECORD; layer RECORD; remaining BIGINT; ordinal INTEGER:=0;
BEGIN
 SELECT * INTO d FROM reconforge.stock_sales_orders WHERE tenant_id=t AND id=target;
 IF d IS NULL OR NOT reconforge.irp_scope(d.tenant_id,d.workspace_id,d.organization_id,d.legal_entity_id) THEN
  RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='stock_sales_owner_phase',MESSAGE='Stock-sale source scope is incomplete.';
 END IF;
 s:=reconforge.stock_sales_stage(d.status);
 IF(SELECT count(*) FROM reconforge.stock_sales_events WHERE tenant_id=t AND order_id=target)<>d.row_version
 OR NOT EXISTS(SELECT 1 FROM reconforge.stock_sales_events WHERE tenant_id=t AND order_id=target AND version=1)
 OR EXISTS(SELECT 1 FROM reconforge.stock_sales_events WHERE tenant_id=t AND order_id=target AND version NOT BETWEEN 1 AND d.row_version)
 OR(SELECT count(*) FROM reconforge.stock_sales_commands WHERE tenant_id=t AND order_id=target)<>d.row_version THEN
  RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='stock_sales_owner_phase',MESSAGE='Each stock-sale version requires its command and audit event.';
 END IF;
 FOR e IN SELECT * FROM reconforge.stock_sales_events WHERE tenant_id=t AND order_id=target ORDER BY version LOOP
  SELECT * INTO c FROM reconforge.stock_sales_commands WHERE tenant_id=t AND order_id=target AND version=e.version;
  IF c IS NULL OR(c.actor_id,c.operation,c.workspace_id) IS DISTINCT FROM(e.actor_id,e.operation,d.workspace_id)
  OR reconforge.irp_digest(c.request) IS DISTINCT FROM c.request_digest OR c.request->>'actor_id' IS DISTINCT FROM c.actor_id
  OR c.request->>'operation' IS DISTINCT FROM c.operation OR c.request->>'id' IS DISTINCT FROM d.id
  OR c.request->'scope'->>'workspace_id' IS DISTINCT FROM d.workspace_id OR c.request->'scope'->>'organization_id' IS DISTINCT FROM d.organization_id
  OR c.request->'scope'->>'legal_entity_id' IS DISTINCT FROM d.legal_entity_id OR c.result->>'source_digest' IS DISTINCT FROM d.source_digest
  OR(c.result->>'row_version')::integer IS DISTINCT FROM e.version OR c.result->>'status' IS DISTINCT FROM e.status
  OR c.result->>'id' IS DISTINCT FROM d.id OR c.result->>'total_minor' IS DISTINCT FROM d.total_minor::text
  OR(e.version=1 AND(e.status<>'Draft' OR e.operation<>'create' OR e.actor_id<>d.created_by))
  OR(e.version=1 AND c.request->'payload' IS DISTINCT FROM d.source-ARRAY['monetary_policy','quantity_scaled'])
  OR(e.version>1 AND(c.request->'payload'->>'expected_version')::integer IS DISTINCT FROM e.version-1)
  OR(e.version>1 AND c.request->'payload'->>'reason' IS DISTINCT FROM e.reason)
  OR(e.version>1 AND e.status IS DISTINCT FROM CASE e.operation WHEN'submit' THEN'Submitted' WHEN'approve' THEN'Approved'
    WHEN'reserve' THEN'Reserved' WHEN'prepare-issue' THEN'IssuePrepared' WHEN'review-issue' THEN'IssueReviewed' WHEN'deliver' THEN'Delivered'
    WHEN'prepare-invoice' THEN'InvoicePrepared' WHEN'review-invoice' THEN'InvoiceReviewed' WHEN'invoice' THEN'Invoiced'
    WHEN'prepare-collection' THEN'CollectionPrepared' WHEN'review-collection' THEN'CollectionReviewed' WHEN'collect' THEN'Paid' WHEN'cancel' THEN'Cancelled' END)
  OR NOT EXISTS(SELECT 1 FROM reconforge.domain_audit_events a WHERE a.tenant_id=t AND a.id=e.audit_event_id
   AND a.object_type='stock_sales' AND a.object_id=target AND a.action='stock_sales.'||e.operation AND a.actor_user_id=e.actor_id
   AND a.metadata_json=jsonb_build_object('source_digest',d.source_digest,'version',e.version,'status',e.status))
  OR jsonb_array_length(c.result->'events')<>e.version
  OR EXISTS(SELECT 1 FROM jsonb_array_elements(c.result->'events') value WHERE NOT EXISTS(SELECT 1 FROM reconforge.stock_sales_events ev
    WHERE ev.tenant_id=t AND ev.order_id=target AND value=jsonb_build_object('version',ev.version,'actor_id',ev.actor_id,'operation',ev.operation,
     'reason',ev.reason,'status',ev.status,'audit_event_id',ev.audit_event_id))) THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='stock_sales_owner_phase',MESSAGE='Stock-sale acknowledgement or lineage was forged.';
  END IF;
  IF e.version=d.row_version AND(c.result IS DISTINCT FROM reconforge.stock_sales_public(d) OR e.status IS DISTINCT FROM d.status) THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='stock_sales_owner_phase',MESSAGE='Current acknowledgement differs from complete source.';
  END IF;
 END LOOP;
 SELECT * INTO r FROM reconforge.stock_sales_reservations WHERE tenant_id=t AND order_id=target;
 IF(s>=3 AND r IS NULL) OR(r IS NOT NULL AND r.state IS DISTINCT FROM CASE WHEN d.status='Cancelled' THEN'Released' WHEN s>=6 THEN'Consumed' ELSE'Active' END) THEN
  RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='stock_sales_owner_phase',MESSAGE='Reservation phase differs from source owner.';
 END IF;
 IF r IS NOT NULL THEN PERFORM reconforge.stock_sales_capacity(t,d.workspace_id,d.legal_entity_id,d.location_id,d.item_id); END IF;
 SELECT * INTO claim FROM reconforge.stock_sales_issue_claims WHERE tenant_id=t AND order_id=target;
 IF(s>=4 AND claim IS NULL) OR(claim IS NOT NULL AND(claim.payload IS DISTINCT FROM d.issue_plan OR reconforge.irp_digest(claim.payload) IS DISTINCT FROM claim.plan_digest
 OR claim.state IS DISTINCT FROM CASE WHEN d.status='Cancelled' THEN'Released' WHEN s>=6 THEN'Consumed' ELSE'Active' END)) THEN
  RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='stock_sales_owner_phase',MESSAGE='Frozen FIFO claim differs from source owner.';
 END IF;
 IF claim IS NOT NULL THEN
  SELECT * INTO entry FROM reconforge.finance_entries WHERE tenant_id=t AND id=d.cogs_entry_id;
  IF entry IS NULL OR entry.id IS DISTINCT FROM claim.entry_id OR entry.id IS DISTINCT FROM d.issue_plan->>'entry_id'
  OR entry.entry_number IS DISTINCT FROM d.issue_plan->>'entry_number' OR entry.source_type<>'Manual'
  OR entry.external_reference IS DISTINCT FROM d.id OR entry.journal_id IS DISTINCT FROM d.issue_plan->>'journal_id'
  OR entry.period_id IS DISTINCT FROM d.issue_plan->'request'->>'period_id'
  OR entry.posting_date::text IS DISTINCT FROM d.issue_plan->'request'->>'posting_date'
  OR d.issue_plan->>'source_digest' IS DISTINCT FROM d.source_digest
  OR(entry.workspace_id,entry.organization_id,entry.legal_entity_id,entry.currency_code) IS DISTINCT FROM(d.workspace_id,d.organization_id,d.legal_entity_id,d.currency_code)
  OR entry.preparer_actor_id IS DISTINCT FROM d.issue_plan->>'preparer_actor_id' OR entry.preparer_actor_id=d.issue_reviewer_id
  OR entry.status IS DISTINCT FROM CASE WHEN d.status='Cancelled' THEN'Voided' WHEN s=4 THEN'Draft' ELSE'Validated' END
  OR entry.total_debit_minor IS DISTINCT FROM(d.issue_plan->>'total_cost_minor')::bigint OR entry.total_credit_minor<>entry.total_debit_minor
  OR NOT reconforge.sales_revenue_policy_matches(t,d.source->'monetary_policy',entry.currency_code,entry.currency_precision,
      entry.currency_rounding_policy,entry.currency_registry_version,entry.currency_registry_digest)
  OR(s>=5 AND entry.validator_actor_id IS DISTINCT FROM d.issue_reviewer_id) THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='stock_sales_owner_phase',MESSAGE='COGS finance draft/review differs from frozen FIFO source.';
  END IF;
  IF(SELECT count(*) FROM reconforge.finance_entry_lines WHERE tenant_id=t AND entry_id=entry.id)<>2
  OR NOT EXISTS(SELECT 1 FROM reconforge.finance_entry_lines l WHERE l.tenant_id=t AND l.entry_id=entry.id
    AND l.account_id=d.issue_plan->>'cogs_account_id' AND l.debit_minor=entry.total_debit_minor AND l.credit_minor=0)
  OR NOT EXISTS(SELECT 1 FROM reconforge.finance_entry_lines l WHERE l.tenant_id=t AND l.entry_id=entry.id
    AND l.account_id=d.issue_plan->>'inventory_account_id' AND l.credit_minor=entry.total_credit_minor AND l.debit_minor=0) THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='stock_sales_owner_phase',MESSAGE='COGS does not debit expense and credit the exact inventory account.';
  END IF;
  FOR x IN SELECT * FROM jsonb_array_elements(d.issue_plan->'allocations') LOOP
   IF(x->>'value_minor')::bigint IS DISTINCT FROM reconforge.stock_sales_fifo_value((x->>'remaining_value_minor')::bigint,
      (x->>'remaining_quantity_scaled')::bigint,(x->>'quantity_scaled')::bigint) THEN
    RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='stock_sales_owner_phase',MESSAGE='Frozen FIFO partial cost does not reproduce HALF_EVEN.';
   END IF;
   total:=total+(x->>'value_minor')::bigint; quantity:=quantity+(x->>'quantity_scaled')::bigint;
   IF s IN(4,5) AND NOT EXISTS(SELECT 1 FROM reconforge.inventory_cost_layers l WHERE l.tenant_id=t AND l.id=x->>'cost_layer_id'
    AND l.workspace_id=d.workspace_id AND l.legal_entity_id=d.legal_entity_id AND l.item_id=d.item_id AND l.uom_id=d.uom_id
    AND l.inventory_lot_id IS NULL AND l.quantity_precision=d.quantity_precision AND l.row_version=(x->>'row_version')::bigint
    AND l.remaining_quantity_scaled=(x->>'remaining_quantity_scaled')::bigint AND l.remaining_value_minor=(x->>'remaining_value_minor')::bigint) THEN
    RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='stock_sales_owner_phase',MESSAGE='Prepared FIFO residuals changed outside their owner.';
   END IF;
   IF s>=6 AND NOT EXISTS(SELECT 1 FROM reconforge.inventory_layer_consumptions n JOIN reconforge.inventory_valuation_lines v
    ON v.tenant_id=n.tenant_id AND v.id=n.valuation_line_id WHERE n.tenant_id=t AND v.valuation_document_id=d.valuation_id
    AND n.cost_layer_id=x->>'cost_layer_id' AND n.quantity_scaled=(x->>'quantity_scaled')::bigint AND n.value_minor=(x->>'value_minor')::bigint) THEN
    RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='stock_sales_owner_phase',MESSAGE='Actual FIFO consumption differs from independently reviewed slices.';
   END IF;
  END LOOP;
  IF total IS DISTINCT FROM entry.total_debit_minor::numeric OR quantity IS DISTINCT FROM d.quantity_scaled::numeric
  OR(s<6 AND EXISTS(SELECT 1 FROM reconforge.finance_posting_effects WHERE tenant_id=t AND entry_id=entry.id)) THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='stock_sales_owner_phase',MESSAGE='COGS effect exists outside complete stock delivery.';
  END IF;
  IF s IN(4,5) THEN
   remaining:=d.quantity_scaled;
   FOR layer IN SELECT l.* FROM reconforge.inventory_cost_layers l
    JOIN reconforge.inventory_valuation_lines vl ON vl.tenant_id=l.tenant_id AND vl.id=l.source_valuation_line_id
    JOIN reconforge.inventory_valuation_documents vd ON vd.tenant_id=vl.tenant_id AND vd.id=vl.valuation_document_id
    WHERE l.tenant_id=t AND l.workspace_id=d.workspace_id AND l.legal_entity_id=d.legal_entity_id AND l.item_id=d.item_id
     AND l.inventory_lot_id IS NULL AND l.remaining_quantity_scaled>0 AND vd.status='Approved' ORDER BY l.created_at,l.id LOOP
    EXIT WHEN remaining=0;
    x:=d.issue_plan->'allocations'->ordinal;
    IF x IS NULL OR x->>'cost_layer_id' IS DISTINCT FROM layer.id
     OR(x->>'quantity_scaled')::bigint IS DISTINCT FROM least(remaining,layer.remaining_quantity_scaled) THEN
     RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='stock_sales_owner_phase',MESSAGE='Selected slices are not the complete earliest native FIFO layers.';
    END IF;
    remaining:=remaining-(x->>'quantity_scaled')::bigint; ordinal:=ordinal+1;
   END LOOP;
   IF remaining<>0 OR ordinal<>jsonb_array_length(d.issue_plan->'allocations') THEN
    RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='stock_sales_owner_phase',MESSAGE='FIFO allocation cardinality differs from native stock.';
   END IF;
  END IF;
 END IF;
 IF s>=6 THEN
  IF NOT EXISTS(SELECT 1 FROM reconforge.inventory_movements m JOIN reconforge.inventory_movement_lines l ON l.tenant_id=m.tenant_id AND l.movement_id=m.id
   WHERE m.tenant_id=t AND m.id=d.movement_id AND(m.workspace_id,m.organization_id,m.legal_entity_id)=(d.workspace_id,d.organization_id,d.legal_entity_id)
   AND m.status='Posted' AND m.movement_type='Delivery' AND m.source_reference=d.id AND l.item_id=d.item_id AND l.uom_id=d.uom_id
   AND l.from_location_id=d.location_id AND l.to_location_id IS NULL AND l.inventory_lot_id IS NULL AND l.quantity_scaled=d.quantity_scaled)
  OR NOT EXISTS(SELECT 1 FROM reconforge.inventory_valuation_documents v WHERE v.tenant_id=t AND v.id=d.valuation_id AND v.movement_id=d.movement_id
   AND v.status='Approved' AND v.finance_entry_id=d.cogs_entry_id AND v.total_value_minor=entry.total_debit_minor
   AND(v.workspace_id,v.organization_id,v.legal_entity_id,v.currency_code)=(d.workspace_id,d.organization_id,d.legal_entity_id,d.currency_code)
   AND v.policy_id=d.issue_plan->>'policy_id' AND v.period_id=entry.period_id AND v.valuation_date=entry.posting_date
   AND reconforge.sales_revenue_policy_matches(t,d.source->'monetary_policy',v.currency_code,v.currency_precision,
    v.currency_rounding_policy,v.currency_registry_version,v.currency_registry_digest))
  OR NOT EXISTS(SELECT 1 FROM reconforge.finance_posting_effects f WHERE f.tenant_id=t AND f.id=d.cogs_effect_id AND f.entry_id=d.cogs_entry_id
   AND f.posted_actor_id<>entry.preparer_actor_id AND f.validation_digest=entry.validation_digest)
  OR(SELECT count(*) FROM reconforge.inventory_movement_lines WHERE tenant_id=t AND movement_id=d.movement_id)<>1
  OR(SELECT count(*) FROM reconforge.inventory_valuation_lines WHERE tenant_id=t AND valuation_document_id=d.valuation_id)<>1 THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='stock_sales_owner_phase',MESSAGE='Delivery requires complete native stock, FIFO and posted COGS.';
  END IF;
  IF(SELECT count(*) FROM reconforge.inventory_layer_consumptions n JOIN reconforge.inventory_valuation_lines v
   ON v.tenant_id=n.tenant_id AND v.id=n.valuation_line_id WHERE n.tenant_id=t AND v.valuation_document_id=d.valuation_id)
   <>jsonb_array_length(d.issue_plan->'allocations')
   OR EXISTS(SELECT 1 FROM reconforge.finance_entries WHERE tenant_id=t AND reverses_posting_id=d.cogs_effect_id)
   OR EXISTS(SELECT 1 FROM reconforge.finance_posting_effects WHERE tenant_id=t AND reverses_effect_id=d.cogs_effect_id) THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='stock_sales_owner_phase',MESSAGE='Complete StockSales inverse is required for owned financial history.';
  END IF;
 END IF;
 IF d.invoice_id IS NOT NULL THEN
  SELECT * INTO invoice FROM reconforge.ar_invoices WHERE tenant_id=t AND id=d.invoice_id;
  SELECT * INTO p FROM reconforge.operational_finance_plans WHERE tenant_id=t AND id=d.invoice_plan_id;
  reviewed:=EXISTS(SELECT 1 FROM reconforge.operational_finance_reviews WHERE tenant_id=t AND plan_id=p.id);
  posted:=EXISTS(SELECT 1 FROM reconforge.operational_finance_links WHERE tenant_id=t AND plan_id=p.id);
  IF invoice IS NULL OR p IS NULL OR(invoice.workspace_id,invoice.organization_id,invoice.legal_entity_id,invoice.customer_id,invoice.currency_code,invoice.total_minor)
   IS DISTINCT FROM(d.workspace_id,d.organization_id,d.legal_entity_id,d.customer_id,d.currency_code,d.total_minor)
  OR(p.source_kind,p.source_id,p.amount_minor,p.currency_code) IS DISTINCT FROM('ARInvoice'::text,d.invoice_id,d.total_minor,d.currency_code)
  OR invoice.status IS DISTINCT FROM CASE WHEN s=7 THEN'Submitted' WHEN s=12 THEN'Paid' ELSE'Approved' END
  OR reviewed IS DISTINCT FROM(s>=8) OR posted IS DISTINCT FROM(s>=9)
  OR NOT reconforge.sales_revenue_policy_matches(t,d.source->'monetary_policy',invoice.currency_code,invoice.currency_precision,
    invoice.currency_rounding_policy,invoice.currency_registry_version,invoice.currency_registry_digest)
  OR EXISTS(SELECT 1 FROM reconforge.ar_receipt_allocations WHERE tenant_id=t AND invoice_id=d.invoice_id AND s<>12)
  OR(SELECT count(*) FROM reconforge.ar_invoice_lines WHERE tenant_id=t AND invoice_id=d.invoice_id)<>1
  OR NOT EXISTS(SELECT 1 FROM reconforge.ar_invoice_lines l WHERE l.tenant_id=t AND l.invoice_id=d.invoice_id
    AND l.quantity_text=d.source->>'quantity' AND l.unit_price_minor=(d.source->>'net_unit_price_minor')::bigint
    AND l.line_total_minor=d.total_minor AND l.tax_minor=0 AND l.description=d.source->>'description')
  OR EXISTS(SELECT 1 FROM reconforge.operational_finance_plans z WHERE z.tenant_id=t AND z.source_id=d.invoice_id
    AND((z.source_kind='ARInvoice' AND z.id IS DISTINCT FROM d.invoice_plan_id) OR(z.source_kind='ARReceipt' AND z.id IS DISTINCT FROM d.collection_plan_id))) THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='stock_sales_owner_phase',MESSAGE='Native AR and revenue phase require their coordinated stock-sale owner.';
  END IF;
 END IF;
 IF d.collection_plan_id IS NOT NULL THEN
  SELECT * INTO p FROM reconforge.operational_finance_plans WHERE tenant_id=t AND id=d.collection_plan_id;
  reviewed:=EXISTS(SELECT 1 FROM reconforge.operational_finance_reviews WHERE tenant_id=t AND plan_id=p.id);
  posted:=EXISTS(SELECT 1 FROM reconforge.operational_finance_links WHERE tenant_id=t AND plan_id=p.id);
  IF p IS NULL OR(p.source_kind,p.source_id,p.amount_minor,p.currency_code) IS DISTINCT FROM('ARReceipt'::text,d.invoice_id,d.total_minor,d.currency_code)
  OR reviewed IS DISTINCT FROM(s>=11) OR posted IS DISTINCT FROM(s=12)
  OR d.collection_parameters->>'receipt_number' !~'^[A-Z0-9][A-Z0-9._-]{0,63}$' THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='stock_sales_owner_phase',MESSAGE='Cash preparation/review differs from native owner phase.';
  END IF;
 END IF;
 IF s=12 THEN
  SELECT * INTO native_receipt FROM reconforge.ar_receipts WHERE tenant_id=t AND id=d.receipt_id;
  IF native_receipt IS NULL OR native_receipt.status<>'Posted' OR native_receipt.amount_minor<>d.total_minor
  OR(native_receipt.workspace_id,native_receipt.organization_id,native_receipt.legal_entity_id,native_receipt.customer_id,native_receipt.currency_code)
   IS DISTINCT FROM(d.workspace_id,d.organization_id,d.legal_entity_id,d.customer_id,d.currency_code)
  OR native_receipt.receipt_number IS DISTINCT FROM d.collection_parameters->>'receipt_number'
  OR NOT reconforge.sales_revenue_policy_matches(t,d.source->'monetary_policy',native_receipt.currency_code,native_receipt.currency_precision,
    native_receipt.currency_rounding_policy,native_receipt.currency_registry_version,native_receipt.currency_registry_digest)
  OR(SELECT count(*) FROM reconforge.ar_receipt_allocations WHERE tenant_id=t AND invoice_id=d.invoice_id)<>1
  OR NOT EXISTS(SELECT 1 FROM reconforge.ar_receipt_allocations WHERE tenant_id=t AND invoice_id=d.invoice_id AND receipt_id=d.receipt_id AND amount_minor=d.total_minor)
  OR NOT EXISTS(SELECT 1 FROM reconforge.operational_finance_links WHERE tenant_id=t AND plan_id=d.collection_plan_id AND source_effect_id=d.receipt_id) THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='stock_sales_owner_phase',MESSAGE='Paid source requires one complete owned AR/cash settlement.';
  END IF;
 END IF;
END $$;
CREATE FUNCTION reconforge.stock_sales_close_trigger() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF TG_TABLE_NAME='stock_sales_orders' THEN PERFORM reconforge.stock_sales_close(NEW.tenant_id,NEW.id);
 ELSE PERFORM reconforge.stock_sales_close(NEW.tenant_id,NEW.order_id); END IF;
 RETURN NULL;
END $$;
DO $$ DECLARE n TEXT; BEGIN FOREACH n IN ARRAY ARRAY['stock_sales_orders','stock_sales_reservations','stock_sales_issue_claims','stock_sales_events','stock_sales_commands'] LOOP
 EXECUTE format('CREATE CONSTRAINT TRIGGER stock_sales_source_closure AFTER INSERT OR UPDATE ON reconforge.%I DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION reconforge.stock_sales_close_trigger()',n);
END LOOP; END $$;
CREATE FUNCTION reconforge.stock_sales_native_lock() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE l RECORD; owner RECORD; changed JSONB:=to_jsonb(NEW); reference TEXT;
BEGIN
 IF TG_TABLE_NAME='inventory_movements' THEN
  IF NEW.movement_number LIKE'SS1-%' AND NOT EXISTS(SELECT 1 FROM reconforge.stock_sales_orders d
   JOIN reconforge.stock_sales_issue_claims c ON c.tenant_id=d.tenant_id AND c.order_id=d.id
   WHERE d.tenant_id=NEW.tenant_id AND d.id=NEW.source_reference AND d.workspace_id=NEW.workspace_id
   AND d.organization_id=NEW.organization_id AND d.legal_entity_id=NEW.legal_entity_id AND d.status IN('IssueReviewed','Delivered','InvoicePrepared','InvoiceReviewed','Invoiced','CollectionPrepared','CollectionReviewed','Paid')
   AND c.payload->>'entry_number'=NEW.movement_number AND NEW.movement_type='Delivery') THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='stock_sales_owner_phase',MESSAGE='SS1 movement namespace requires its complete StockSales owner.';
  END IF;
  IF NEW.status='Posted' AND(TG_OP='INSERT' OR OLD.status<>'Posted') THEN
   FOR l IN SELECT x.* FROM reconforge.inventory_movement_lines x WHERE x.tenant_id=NEW.tenant_id AND x.movement_id=NEW.id ORDER BY x.item_id,x.from_location_id LOOP
    IF l.from_location_id IS NOT NULL AND l.inventory_lot_id IS NULL THEN
     PERFORM pg_advisory_xact_lock(hashtextextended(NEW.workspace_id||'|'||NEW.legal_entity_id||'|'||l.from_location_id||'|'||l.item_id||'|',0));
     FOR owner IN SELECT c.order_id FROM reconforge.stock_sales_issue_claims c WHERE c.tenant_id=NEW.tenant_id
      AND c.workspace_id=NEW.workspace_id AND c.legal_entity_id=NEW.legal_entity_id AND c.item_id=l.item_id AND c.state='Active' LOOP
      IF NEW.source_reference IS DISTINCT FROM owner.order_id THEN
       RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='stock_sales_owner_phase',MESSAGE='Prepared FIFO item requires its complete reviewed delivery owner.';
      END IF;
     END LOOP;
    END IF;
   END LOOP;
  END IF;
 ELSIF TG_TABLE_NAME='inventory_layer_consumptions' THEN
  FOR owner IN SELECT c.order_id FROM reconforge.stock_sales_issue_claims c
   WHERE c.tenant_id=NEW.tenant_id AND c.state='Active' AND EXISTS(SELECT 1 FROM jsonb_array_elements(c.payload->'allocations') a WHERE a->>'cost_layer_id'=NEW.cost_layer_id) LOOP
   SELECT m.source_reference INTO reference FROM reconforge.inventory_valuation_lines v
    JOIN reconforge.inventory_valuation_documents d ON d.tenant_id=v.tenant_id AND d.id=v.valuation_document_id
    JOIN reconforge.inventory_movements m ON m.tenant_id=d.tenant_id AND m.id=d.movement_id
    WHERE v.tenant_id=NEW.tenant_id AND v.id=NEW.valuation_line_id;
   IF reference IS DISTINCT FROM owner.order_id THEN
    RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='stock_sales_owner_phase',MESSAGE='Frozen FIFO slice cannot be consumed outside its owner.';
   END IF;
  END LOOP;
 ELSIF TG_TABLE_NAME='finance_entries' THEN
  IF NEW.entry_number LIKE'SS1-%' AND NOT EXISTS(SELECT 1 FROM reconforge.stock_sales_issue_claims c WHERE c.tenant_id=NEW.tenant_id AND c.entry_id=NEW.id
   AND c.payload->>'entry_number'=NEW.entry_number) THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='stock_sales_owner_phase',MESSAGE='SS1 finance namespace requires its actual frozen stock issue.';
  END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER stock_sales_movement_lock BEFORE INSERT OR UPDATE ON reconforge.inventory_movements FOR EACH ROW EXECUTE FUNCTION reconforge.stock_sales_native_lock();
CREATE TRIGGER stock_sales_consumption_lock BEFORE INSERT ON reconforge.inventory_layer_consumptions FOR EACH ROW EXECUTE FUNCTION reconforge.stock_sales_native_lock();
CREATE TRIGGER stock_sales_finance_namespace BEFORE INSERT OR UPDATE ON reconforge.finance_entries FOR EACH ROW EXECUTE FUNCTION reconforge.stock_sales_native_lock();
CREATE FUNCTION reconforge.stock_sales_native_close() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE previous JSONB; current_row JSONB; changed JSONB; owner RECORD; movement TEXT; invoice TEXT; receipt TEXT; entry TEXT; plan TEXT; layer TEXT; reference TEXT; reverse_effect TEXT;
BEGIN
 IF TG_OP<>'INSERT' THEN previous:=to_jsonb(OLD); END IF;
 IF TG_OP<>'DELETE' THEN current_row:=to_jsonb(NEW); END IF;
 FOR changed IN SELECT previous WHERE previous IS NOT NULL UNION SELECT current_row WHERE current_row IS NOT NULL LOOP
  movement:=NULL; invoice:=NULL; receipt:=NULL; entry:=NULL; plan:=NULL; layer:=NULL; reference:=NULL; reverse_effect:=NULL;
  IF TG_TABLE_NAME='inventory_movements' THEN movement:=changed->>'id'; reference:=changed->>'source_reference';
  ELSIF TG_TABLE_NAME='inventory_movement_lines' THEN movement:=changed->>'movement_id';
  ELSIF TG_TABLE_NAME='inventory_valuation_documents' THEN movement:=changed->>'movement_id';
  ELSIF TG_TABLE_NAME='inventory_valuation_lines' THEN SELECT movement_id INTO movement FROM reconforge.inventory_valuation_documents WHERE tenant_id=changed->>'tenant_id' AND id=changed->>'valuation_document_id';
  ELSIF TG_TABLE_NAME='inventory_layer_consumptions' THEN layer:=changed->>'cost_layer_id';
  ELSIF TG_TABLE_NAME='inventory_cost_layers' THEN layer:=changed->>'id';
  ELSIF TG_TABLE_NAME='finance_entries' THEN entry:=changed->>'id'; reference:=changed->>'external_reference'; reverse_effect:=changed->>'reverses_posting_id';
  ELSIF TG_TABLE_NAME IN('finance_entry_lines','finance_posting_effects') THEN entry:=changed->>'entry_id'; reverse_effect:=changed->>'reverses_effect_id';
  ELSIF TG_TABLE_NAME='ar_invoices' THEN invoice:=changed->>'id';
  ELSIF TG_TABLE_NAME='ar_invoice_lines' THEN invoice:=changed->>'invoice_id';
  ELSIF TG_TABLE_NAME='ar_receipts' THEN receipt:=changed->>'id';
  ELSIF TG_TABLE_NAME='ar_receipt_allocations' THEN invoice:=changed->>'invoice_id'; receipt:=changed->>'receipt_id';
  ELSIF TG_TABLE_NAME='operational_finance_plans' THEN plan:=changed->>'id'; invoice:=changed->>'source_id';
  ELSIF TG_TABLE_NAME IN('operational_finance_reviews','operational_finance_links','operational_finance_commands') THEN
   plan:=changed->>'plan_id'; SELECT source_id INTO invoice FROM reconforge.operational_finance_plans WHERE tenant_id=changed->>'tenant_id' AND id=plan;
  END IF;
  FOR owner IN SELECT d.id FROM reconforge.stock_sales_orders d WHERE d.tenant_id=changed->>'tenant_id'
   AND(d.id=reference OR d.cogs_effect_id=reverse_effect OR d.movement_id=movement OR d.invoice_id=invoice OR d.receipt_id=receipt OR d.cogs_entry_id=entry
    OR d.invoice_plan_id=plan OR d.collection_plan_id=plan
    OR EXISTS(SELECT 1 FROM reconforge.stock_sales_issue_claims c WHERE c.tenant_id=d.tenant_id AND c.order_id=d.id
     AND(EXISTS(SELECT 1 FROM jsonb_array_elements(c.payload->'allocations') a WHERE a->>'cost_layer_id'=layer)
      OR(TG_TABLE_NAME='inventory_cost_layers' AND c.state='Active' AND c.workspace_id=changed->>'workspace_id'
       AND c.legal_entity_id=changed->>'legal_entity_id' AND c.item_id=changed->>'item_id')))) LOOP
   PERFORM reconforge.stock_sales_close(changed->>'tenant_id',owner.id);
  END LOOP;
  IF movement IS NOT NULL THEN
   FOR owner IN SELECT DISTINCT m.workspace_id,m.legal_entity_id,x.from_location_id location_id,x.item_id FROM reconforge.inventory_movements m
    JOIN reconforge.inventory_movement_lines x ON x.tenant_id=m.tenant_id AND x.movement_id=m.id
    WHERE m.tenant_id=changed->>'tenant_id' AND m.id=movement AND x.from_location_id IS NOT NULL AND x.inventory_lot_id IS NULL LOOP
    PERFORM reconforge.stock_sales_capacity(changed->>'tenant_id',owner.workspace_id,owner.legal_entity_id,owner.location_id,owner.item_id);
   END LOOP;
  END IF;
 END LOOP;
 RETURN NULL;
END $$;
DO $$ DECLARE n TEXT; BEGIN FOREACH n IN ARRAY ARRAY['inventory_movements','inventory_movement_lines','inventory_valuation_documents','inventory_valuation_lines',
 'inventory_cost_layers','inventory_layer_consumptions','finance_entries','finance_entry_lines','finance_posting_effects',
 'ar_invoices','ar_invoice_lines','ar_receipts','ar_receipt_allocations','operational_finance_plans','operational_finance_reviews','operational_finance_links','operational_finance_commands'] LOOP
 EXECUTE format('CREATE CONSTRAINT TRIGGER stock_sales_native_closure AFTER INSERT OR UPDATE OR DELETE ON reconforge.%I DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION reconforge.stock_sales_native_close()',n);
END LOOP; END $$;
"""


def _original_namespace_function(name: str) -> str:
    """Restore two exact existing function bodies on an empty additive rollback."""
    marker = f"CREATE FUNCTION reconforge.{name}("
    original = marker + POSTGRES_SALES_REVENUE_SCHEMA_SQL.split(marker, 1)[1].split("END $sales$;", 1)[0] + "END $sales$;"
    return original.replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1)


_original_admit = _original_namespace_function("sales_receipt_name_admit")
_original_close = _original_namespace_function("sales_receipt_name_close")
_stock_admit = _original_admit.replace(
    "IF retained->>'owner_kind'='Sales' THEN",
    """IF retained->>'owner_kind'='StockSales' THEN
  SELECT * INTO d FROM reconforge.stock_sales_orders WHERE tenant_id=NEW.tenant_id AND id=retained->>'owner_id';
  IF d IS NULL OR d.status NOT IN ('CollectionReviewed','Paid')
  OR d.collection_parameters->>'receipt_number' IS DISTINCT FROM NEW.receipt_number
  OR(d.workspace_id,d.organization_id,d.legal_entity_id,d.customer_id,d.currency_code,d.total_minor)
   IS DISTINCT FROM(NEW.workspace_id,NEW.organization_id,NEW.legal_entity_id,NEW.customer_id,NEW.currency_code,NEW.amount_minor)
  OR(d.status='Paid' AND d.receipt_id IS DISTINCT FROM NEW.id) THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='stock_sales_owner_phase',MESSAGE='Reserved receipt requires its complete StockSales collection.';
  END IF;
 ELSIF retained->>'owner_kind'='Sales' THEN""", 1,
)
_stock_close = _original_close.replace(
    "IF retained->>'owner_kind'='Sales' THEN",
    """IF retained->>'owner_kind'='StockSales' THEN
  SELECT * INTO d FROM reconforge.stock_sales_orders WHERE tenant_id=t AND id=retained->>'owner_id';
  IF d IS NULL OR d.workspace_id IS DISTINCT FROM w OR d.collection_parameters->>'receipt_number' IS DISTINCT FROM n
  OR d.status NOT IN('CollectionPrepared','CollectionReviewed','Paid')
  OR retained IS DISTINCT FROM jsonb_build_object('schema_version',1,'owner_kind','StockSales','owner_id',d.id)
  OR EXISTS(SELECT 1 FROM reconforge.ar_receipts r WHERE r.tenant_id=t AND r.workspace_id=w AND r.receipt_number=n
    AND(d.status<>'Paid' OR r.id IS DISTINCT FROM d.receipt_id)) THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='stock_sales_owner_phase',MESSAGE='Receipt namespace lacks its exact complete StockSales owner.';
  END IF;
  PERFORM reconforge.stock_sales_close(t,d.id);
 ELSIF retained->>'owner_kind'='Sales' THEN""", 1,
)
POSTGRES_STOCK_SALES_SCHEMA_SQL += _stock_admit + "\n" + _stock_close

DOWNGRADE_STOCK_SALES_SQL = r"""
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM reconforge.stock_sales_orders)
 OR EXISTS(SELECT 1 FROM reconforge.ar_idempotency_keys WHERE payload->>'owner_kind'='StockSales') THEN
  RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='StockSales history exists; restore the preserved backup instead of removing immutable financial history.';
 END IF;
END $$;
""" + _original_admit + "\n" + _original_close + r"""
DO $$ DECLARE n TEXT; BEGIN FOREACH n IN ARRAY ARRAY['inventory_movements','inventory_movement_lines','inventory_valuation_documents','inventory_valuation_lines',
 'inventory_cost_layers','inventory_layer_consumptions','finance_entries','finance_entry_lines','finance_posting_effects',
 'ar_invoices','ar_invoice_lines','ar_receipts','ar_receipt_allocations','operational_finance_plans','operational_finance_reviews','operational_finance_links','operational_finance_commands'] LOOP
 EXECUTE format('DROP TRIGGER stock_sales_native_closure ON reconforge.%I',n);
END LOOP; END $$;
DROP TRIGGER stock_sales_movement_lock ON reconforge.inventory_movements;
DROP TRIGGER stock_sales_consumption_lock ON reconforge.inventory_layer_consumptions;
DROP TRIGGER stock_sales_finance_namespace ON reconforge.finance_entries;
DROP TABLE reconforge.stock_sales_commands,reconforge.stock_sales_events,reconforge.stock_sales_issue_claims,reconforge.stock_sales_reservations;
DROP FUNCTION reconforge.stock_sales_public(reconforge.stock_sales_orders);
DROP TABLE reconforge.stock_sales_orders;
DROP FUNCTION reconforge.stock_sales_native_close(),reconforge.stock_sales_native_lock(),reconforge.stock_sales_close_trigger(),
 reconforge.stock_sales_close(TEXT,TEXT),reconforge.stock_sales_admit(),reconforge.stock_sales_capacity(TEXT,TEXT,TEXT,TEXT,TEXT),
 reconforge.stock_sales_protect(),reconforge.stock_sales_fifo_value(BIGINT,BIGINT,BIGINT),reconforge.stock_sales_stage(TEXT);
"""
