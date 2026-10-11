"""Immutable sourcing evidence with deferred closure to the existing native PO."""
from collections.abc import Mapping
from typing import Any

_TABLES = r"""
CREATE TABLE reconforge.procurement_sourcing_requisitions(
 tenant_id TEXT NOT NULL,id TEXT NOT NULL,workspace_id TEXT NOT NULL,organization_id TEXT NOT NULL,legal_entity_id TEXT NOT NULL,
 number TEXT NOT NULL CHECK(number~'^SRC5-[A-Z0-9._/-]{1,25}$'),budget_id TEXT NOT NULL,order_id TEXT NOT NULL,
 ceiling_minor BIGINT NOT NULL CHECK(ceiling_minor BETWEEN 1 AND 9000000000000000000),
 payload JSONB NOT NULL CHECK(jsonb_typeof(payload)='object' AND octet_length(payload::text)<=262144),
 source_digest TEXT NOT NULL CHECK(source_digest~'^[0-9a-f]{64}$'),creator_actor_id TEXT NOT NULL,
 phase INTEGER NOT NULL DEFAULT 0 CHECK(phase BETWEEN 0 AND 4),row_version BIGINT NOT NULL DEFAULT 1 CHECK(row_version BETWEEN 1 AND 38),
 selected_quote_id TEXT,created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 PRIMARY KEY(tenant_id,id),UNIQUE(tenant_id,workspace_id,number),UNIQUE(tenant_id,order_id),
 FOREIGN KEY(tenant_id,budget_id) REFERENCES reconforge.budget_envelopes(tenant_id,id),
 FOREIGN KEY(tenant_id,creator_actor_id) REFERENCES reconforge.identity_users(tenant_id,id),
 FOREIGN KEY(tenant_id,workspace_id) REFERENCES reconforge.domain_workspaces(tenant_id,id),
 FOREIGN KEY(tenant_id,organization_id) REFERENCES reconforge.organizations(tenant_id,id),
 FOREIGN KEY(tenant_id,legal_entity_id) REFERENCES reconforge.legal_entities(tenant_id,id)
);
CREATE TABLE reconforge.procurement_sourcing_quotes(
 tenant_id TEXT NOT NULL,id TEXT NOT NULL,requisition_id TEXT NOT NULL,supplier_id TEXT NOT NULL,supplier_code TEXT NOT NULL,
 total_minor BIGINT NOT NULL CHECK(total_minor BETWEEN 1 AND 9000000000000000000),
 payload JSONB NOT NULL CHECK(jsonb_typeof(payload)='object' AND octet_length(payload::text)<=262144),
 quote_digest TEXT NOT NULL CHECK(quote_digest~'^[0-9a-f]{64}$'),registrar_actor_id TEXT NOT NULL,
 created_version BIGINT NOT NULL CHECK(created_version BETWEEN 3 AND 34),
 PRIMARY KEY(tenant_id,id),UNIQUE(tenant_id,requisition_id,supplier_code),UNIQUE(tenant_id,requisition_id,created_version),
 FOREIGN KEY(tenant_id,requisition_id) REFERENCES reconforge.procurement_sourcing_requisitions(tenant_id,id),
 FOREIGN KEY(tenant_id,supplier_id) REFERENCES reconforge.ap_suppliers(tenant_id,id),
 FOREIGN KEY(tenant_id,registrar_actor_id) REFERENCES reconforge.identity_users(tenant_id,id)
);
ALTER TABLE reconforge.procurement_sourcing_requisitions ADD CONSTRAINT sourcing_selected_quote
 FOREIGN KEY(tenant_id,selected_quote_id) REFERENCES reconforge.procurement_sourcing_quotes(tenant_id,id) DEFERRABLE INITIALLY DEFERRED;
CREATE TABLE reconforge.procurement_sourcing_events(
 tenant_id TEXT NOT NULL,requisition_id TEXT NOT NULL,version BIGINT NOT NULL,
 operation TEXT NOT NULL CHECK(operation IN('create','open-rfq','quote','review-selection','award','cancel')),
 actor_id TEXT NOT NULL,command_id TEXT NOT NULL CHECK(reconforge.irp_text(command_id,140)),
 request_json JSONB NOT NULL CHECK(jsonb_typeof(request_json)='object' AND octet_length(request_json::text)<=262144),
 request_digest TEXT NOT NULL CHECK(request_digest~'^[0-9a-f]{64}$'),reason TEXT NOT NULL CHECK(reconforge.irp_text(reason,500)),
 audit_event_id TEXT NOT NULL,outbox_event_id TEXT NOT NULL,
 PRIMARY KEY(tenant_id,requisition_id,version),UNIQUE(tenant_id,audit_event_id),UNIQUE(tenant_id,outbox_event_id),
 FOREIGN KEY(tenant_id,requisition_id) REFERENCES reconforge.procurement_sourcing_requisitions(tenant_id,id),
 FOREIGN KEY(tenant_id,actor_id) REFERENCES reconforge.identity_users(tenant_id,id),
 FOREIGN KEY(tenant_id,audit_event_id) REFERENCES reconforge.domain_audit_events(tenant_id,id),
 FOREIGN KEY(tenant_id,outbox_event_id) REFERENCES reconforge.outbox_events(tenant_id,event_id)
);
CREATE UNIQUE INDEX sourcing_once ON reconforge.procurement_sourcing_events(tenant_id,requisition_id,operation) WHERE operation<>'quote';
CREATE TABLE reconforge.procurement_sourcing_commands(
 tenant_id TEXT NOT NULL,workspace_id TEXT NOT NULL,requisition_id TEXT NOT NULL,command_id TEXT NOT NULL CHECK(reconforge.irp_text(command_id,140)),
 actor_id TEXT NOT NULL,request_digest TEXT NOT NULL CHECK(request_digest~'^[0-9a-f]{64}$'),
 request_json JSONB NOT NULL CHECK(jsonb_typeof(request_json)='object' AND octet_length(request_json::text)<=262144),
 version BIGINT NOT NULL,response_json JSONB NOT NULL CHECK(jsonb_typeof(response_json)='object' AND octet_length(response_json::text)<=4096),
 PRIMARY KEY(tenant_id,workspace_id,command_id),UNIQUE(tenant_id,requisition_id,version),
 FOREIGN KEY(tenant_id,requisition_id,version) REFERENCES reconforge.procurement_sourcing_events(tenant_id,requisition_id,version),
 FOREIGN KEY(tenant_id,actor_id) REFERENCES reconforge.identity_users(tenant_id,id)
);
CREATE FUNCTION reconforge.ps_assert(ok BOOLEAN,message TEXT) RETURNS VOID LANGUAGE plpgsql SET search_path=pg_catalog AS $ps$
BEGIN IF ok IS DISTINCT FROM TRUE THEN RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='procurement_sourcing_owner',MESSAGE=message; END IF; END $ps$;
CREATE FUNCTION reconforge.ps_authority(t TEXT,a TEXT,operation TEXT,w TEXT,o TEXT,e TEXT) RETURNS BOOLEAN LANGUAGE plpgsql SET search_path=pg_catalog AS $ps$
DECLARE permission TEXT;extra TEXT;
BEGIN
 extra:=CASE operation WHEN'create' THEN'procurement_sourcing.manage' WHEN'quote' THEN'procurement_sourcing.manage'
 WHEN'award' THEN'procurement_sourcing.award' ELSE'procurement_sourcing.approve' END;
 PERFORM 1 FROM reconforge.identity_users WHERE tenant_id=t AND id=a AND NOT disabled FOR SHARE;
 IF NOT FOUND THEN RETURN FALSE; END IF;
 PERFORM 1 FROM reconforge.principal_scope_grants WHERE tenant_id=t AND principal_type='user' AND principal_id=a AND revoked_at IS NULL
 AND((scope_type='workspace' AND scope_id=w) OR(scope_type='organization' AND scope_id=o) OR(scope_type='legal_entity' AND scope_id=e)) FOR SHARE;
 IF(SELECT count(*) FROM reconforge.principal_scope_grants WHERE tenant_id=t AND principal_type='user' AND principal_id=a AND revoked_at IS NULL
 AND((scope_type='workspace' AND scope_id=w) OR(scope_type='organization' AND scope_id=o) OR(scope_type='legal_entity' AND scope_id=e)))<>3 THEN RETURN FALSE; END IF;
 PERFORM 1 FROM reconforge.identity_user_roles u JOIN reconforge.identity_roles r ON r.tenant_id=u.tenant_id AND r.id=u.role_id
 JOIN reconforge.identity_role_permissions p ON p.tenant_id=r.tenant_id AND p.role_id=r.id
 WHERE u.tenant_id=t AND u.user_id=a AND u.active AND r.active AND p.active FOR SHARE OF u,r,p;
 FOREACH permission IN ARRAY ARRAY['procurement_sourcing.read','budget_control.read','payables.read','inventory.read','finance_core.read',extra] LOOP
 IF NOT reconforge.sales_revenue_actor(t,a,permission) THEN RETURN FALSE; END IF; END LOOP;
 IF operation='award' AND(NOT reconforge.sales_revenue_actor(t,a,'budget_control.manage') OR NOT reconforge.sales_revenue_actor(t,a,'payables.manage')) THEN RETURN FALSE; END IF;
 RETURN TRUE;
END $ps$;
CREATE FUNCTION reconforge.ps_protect() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $ps$
DECLARE p RECORD;a TEXT:=current_setting('app.procurement_sourcing_actor_id',true);operation TEXT;j JSONB;policy JSONB;period TEXT;w TEXT;t TEXT;
BEGIN
 PERFORM reconforge.ps_assert(TG_OP<>'DELETE' AND(TG_OP<>'UPDATE' OR TG_TABLE_NAME='procurement_sourcing_requisitions'),'Sourcing history and supplier offers are immutable');
 j:=to_jsonb(NEW);
 IF TG_TABLE_NAME='procurement_sourcing_requisitions' THEN
  IF TG_OP='INSERT' THEN operation:='create';
   PERFORM reconforge.ps_assert(NEW.phase=0 AND NEW.row_version=1 AND NEW.selected_quote_id IS NULL AND NEW.creator_actor_id=a,'Sourcing starts with exact Prepared human ownership');
  ELSE
   PERFORM reconforge.ps_assert((j-ARRAY['phase','row_version','selected_quote_id'])=(to_jsonb(OLD)-ARRAY['phase','row_version','selected_quote_id'])
    AND NEW.row_version=OLD.row_version+1
    AND((OLD.phase=0 AND NEW.phase IN(1,4)) OR(OLD.phase=1 AND NEW.phase IN(1,2,4)) OR(OLD.phase=2 AND NEW.phase IN(3,4)))
    AND(NEW.selected_quote_id IS NOT DISTINCT FROM OLD.selected_quote_id OR OLD.phase=1 AND NEW.phase=2),'Sourcing cannot rewrite retained demand or skip approval history');
   operation:=CASE WHEN NEW.phase=1 AND OLD.phase=0 THEN'open-rfq' WHEN NEW.phase=1 THEN'quote' WHEN NEW.phase=2 THEN'review-selection' WHEN NEW.phase=3 THEN'award' ELSE'cancel' END;
  END IF;
  PERFORM reconforge.ps_assert(reconforge.ps_authority(NEW.tenant_id,a,operation,NEW.workspace_id,NEW.organization_id,NEW.legal_entity_id),'Sourcing mutation requires current persisted scoped human authority');
  policy:=NEW.payload;w:=NEW.workspace_id;t:=NEW.tenant_id;
 ELSE
  SELECT * INTO p FROM reconforge.procurement_sourcing_requisitions WHERE tenant_id=NEW.tenant_id AND id=NEW.requisition_id;
  operation:=CASE WHEN TG_TABLE_NAME='procurement_sourcing_quotes' THEN'quote' ELSE j->'request_json'->>'operation' END;
  PERFORM reconforge.ps_assert(p.id IS NOT NULL AND reconforge.ps_authority(NEW.tenant_id,a,operation,p.workspace_id,p.organization_id,p.legal_entity_id)
   AND a=CASE WHEN TG_TABLE_NAME='procurement_sourcing_quotes' THEN j->>'registrar_actor_id' ELSE j->>'actor_id' END,'Sourcing offer, event and acknowledgment require the same current scoped human');
  policy:=p.payload;w:=p.workspace_id;t:=p.tenant_id;
 END IF;
 IF EXISTS(SELECT 1 FROM jsonb_array_elements(policy#>'{request,requirements}') z WHERE z<>'null'::jsonb) THEN
  PERFORM reconforge.ps_assert(reconforge.ps_authority(t,a,operation,w,policy#>>'{scope,organization_id}',policy#>>'{scope,legal_entity_id}')
   AND reconforge.sales_revenue_actor(t,a,'manufacturing_execution.read'),'Linked sourcing mutations require current manufacturing source read authority');
 END IF;
 period:=policy#>>'{request,order,period_id}';
 PERFORM 1 FROM reconforge.fiscal_periods WHERE tenant_id=t AND id=period AND application_workspace_id=w AND status='Open'
  AND(policy#>>'{request,order,posting_date}')::date BETWEEN start_date AND end_date FOR SHARE;
 PERFORM reconforge.ps_assert(FOUND AND current_setting('transaction_isolation')='read committed','Sourcing mutation requires its Open scoped original business period and READ COMMITTED');
 RETURN NEW;
END $ps$;
DO $ps$ DECLARE n TEXT;BEGIN
 FOREACH n IN ARRAY ARRAY['procurement_sourcing_requisitions','procurement_sourcing_quotes','procurement_sourcing_events','procurement_sourcing_commands'] LOOP
 EXECUTE format('ALTER TABLE reconforge.%I ENABLE ROW LEVEL SECURITY',n); EXECUTE format('ALTER TABLE reconforge.%I FORCE ROW LEVEL SECURITY',n);
 IF n='procurement_sourcing_requisitions' THEN
 EXECUTE format('CREATE POLICY scope ON reconforge.%I USING(reconforge.irp_scope(tenant_id,workspace_id,organization_id,legal_entity_id)) WITH CHECK(reconforge.irp_scope(tenant_id,workspace_id,organization_id,legal_entity_id))',n);
 ELSE
 EXECUTE format('CREATE POLICY scope ON reconforge.%I USING(EXISTS(SELECT 1 FROM reconforge.procurement_sourcing_requisitions p WHERE p.tenant_id=%I.tenant_id AND p.id=%I.requisition_id)) WITH CHECK(EXISTS(SELECT 1 FROM reconforge.procurement_sourcing_requisitions p WHERE p.tenant_id=%I.tenant_id AND p.id=%I.requisition_id))',n,n,n,n,n);
 END IF;
 EXECUTE format('CREATE TRIGGER immutable BEFORE INSERT OR UPDATE OR DELETE ON reconforge.%I FOR EACH ROW EXECUTE FUNCTION reconforge.ps_protect()',n);
 END LOOP;
END $ps$;
"""

_VERIFY = r"""
CREATE FUNCTION reconforge.ps_public(t TEXT,i TEXT,v BIGINT) RETURNS JSONB LANGUAGE plpgsql STABLE SET search_path=pg_catalog AS $ps$
DECLARE p RECORD;e RECORD;r RECORD;a RECORD;c RECORD;selected TEXT;stage TEXT;
BEGIN
 SELECT * INTO p FROM reconforge.procurement_sourcing_requisitions WHERE tenant_id=t AND id=i;
 SELECT * INTO e FROM reconforge.procurement_sourcing_events WHERE tenant_id=t AND requisition_id=i AND version=v;
 SELECT * INTO r FROM reconforge.procurement_sourcing_events WHERE tenant_id=t AND requisition_id=i AND operation='review-selection' AND version<=v;
 SELECT * INTO a FROM reconforge.procurement_sourcing_events WHERE tenant_id=t AND requisition_id=i AND operation='award' AND version<=v;
 SELECT * INTO c FROM reconforge.procurement_sourcing_events WHERE tenant_id=t AND requisition_id=i AND operation='open-rfq' AND version<=v;
 IF p.id IS NULL OR e.version IS NULL THEN RETURN NULL; END IF;
 stage:=CASE WHEN e.operation='cancel' THEN'Cancelled' WHEN a.version IS NOT NULL THEN'Awarded' WHEN r.version IS NOT NULL THEN'SelectionReviewed' WHEN c.version IS NOT NULL THEN'OpenRFQ' ELSE'Draft' END;
 IF r.version IS NOT NULL THEN SELECT id INTO selected FROM reconforge.procurement_sourcing_quotes
 WHERE tenant_id=t AND requisition_id=i AND created_version<r.version ORDER BY total_minor,supplier_code COLLATE "C" LIMIT 1; END IF;
 RETURN jsonb_build_object('schema_version','procurement-sourcing-v1','id',p.id,'number',p.number,'row_version',v,'status',stage,
 'workspace_id',p.workspace_id,'organization_id',p.organization_id,'legal_entity_id',p.legal_entity_id,
 'currency_code',p.payload#>>'{request,order,currency_code}','ceiling_minor',p.ceiling_minor::text,'budget_id',p.budget_id,
 'source_digest',p.source_digest,'creator_actor_id',p.creator_actor_id,'rfq_approver_actor_id',c.actor_id,'selection_reviewer_actor_id',r.actor_id,
 'award_actor_id',a.actor_id,'selected_quote_id',selected,'order_id',CASE WHEN a.version IS NOT NULL THEN p.order_id ELSE NULL END,
 'evidence',jsonb_build_object('audit_event_id',e.audit_event_id,'outbox_event_id',e.outbox_event_id,'request_digest',e.request_digest));
END $ps$;
CREATE FUNCTION reconforge.ps_close(t TEXT,i TEXT) RETURNS VOID LANGUAGE plpgsql SET search_path=pg_catalog AS $ps$
DECLARE p RECORD;b RECORD;q RECORD;x RECORD;c RECORD;r RECORD;a RECORD;o RECORD;source JSONB;request JSONB;line JSONB;part JSONB;price NUMERIC;
 total NUMERIC;amount NUMERIC;metadata JSONB;winner TEXT;position INTEGER;prior INTEGER:=0;next_stage INTEGER;seen INTEGER:=0;original_scope JSONB;
BEGIN
 SELECT * INTO p FROM reconforge.procurement_sourcing_requisitions WHERE tenant_id=t AND id=i;
 PERFORM reconforge.ps_assert(p.id IS NOT NULL AND reconforge.irp_scope(t,p.workspace_id,p.organization_id,p.legal_entity_id),'Sourcing must retain its current visible canonical owner');
 source:=p.payload;request:=source#>'{request,order}';
 SELECT * INTO b FROM reconforge.budget_envelopes WHERE tenant_id=t AND id=p.budget_id;
 original_scope:=jsonb_build_object('workspace_id',p.workspace_id,'organization_id',p.organization_id,'legal_entity_id',p.legal_entity_id);
 PERFORM reconforge.ps_assert(reconforge.irp_digest(source)=p.source_digest AND source->>'schema_version'='procurement-sourcing-v1'
 AND source->'scope'=original_scope AND source->>'creator_actor_id'=p.creator_actor_id AND source->'request'->>'budget_id'=p.budget_id
 AND request->>'number'=p.number AND(source->>'ceiling_minor')::bigint=p.ceiling_minor AND jsonb_typeof(request->'lines')='array'
 AND jsonb_array_length(request->'lines') BETWEEN 1 AND 128 AND jsonb_array_length(source->'request'->'requirements')=jsonb_array_length(request->'lines')
 AND jsonb_array_length(source->'demand_masters')=jsonb_array_length(request->'lines')
 AND jsonb_array_length(source->'manufacturing_requirements')=jsonb_array_length(request->'lines')
 AND b.id IS NOT NULL AND(b.workspace_id,b.organization_id,b.legal_entity_id)=(p.workspace_id,p.organization_id,p.legal_entity_id)
 AND(b.currency_code,b.period_id)=(request->>'currency_code',request->>'period_id')
 AND b.currency_precision=(source->>'currency_precision')::integer
 AND EXISTS(SELECT 1 FROM reconforge.currencies WHERE tenant_id=t AND code=b.currency_code AND minor_units=b.currency_precision AND active)
 AND request->>'workspace'=p.workspace_id
 AND EXISTS(SELECT 1 FROM reconforge.organizations z JOIN reconforge.legal_entities y ON y.tenant_id=z.tenant_id AND y.organization_id=z.id
 WHERE z.tenant_id=t AND z.id=p.organization_id AND y.id=p.legal_entity_id AND z.organization_code=request->>'organization_code' AND y.entity_code=request->>'entity_code'),
 'Original demand, currency, appropriation and canonical source digest must agree');
 total:=0;position:=0;
 FOR line IN SELECT * FROM jsonb_array_elements(request->'lines') LOOP
  PERFORM reconforge.ps_assert(jsonb_typeof(line->'unit_price_minor')='number' AND(line->>'unit_price_minor')::numeric BETWEEN 1 AND 9000000000000000000
   AND(line->>'unit_price_minor')::numeric=trunc((line->>'unit_price_minor')::numeric) AND jsonb_typeof(line->'quantity')='string'
   AND line->>'quantity'~'^[0-9]+(\.[0-9]{1,6})?$' AND(line->>'quantity')::numeric>0,'Demand quantities and estimate prices require exact bounded values');
  amount:=(line->>'quantity')::numeric*(line->>'unit_price_minor')::numeric;
  PERFORM reconforge.ps_assert(amount=trunc(amount) AND amount BETWEEN 1 AND 9000000000000000000,'Demand estimate cannot silently round fractional minor units');
  total:=total+amount;
  part:=source->'demand_masters'->position;
  PERFORM reconforge.ps_assert(EXISTS(SELECT 1 FROM reconforge.inventory_items stock JOIN reconforge.inventory_units_of_measure u
   ON u.tenant_id=stock.tenant_id AND u.id=stock.uom_id WHERE stock.tenant_id=t AND stock.id=part->>'item_id'
   AND stock.workspace_id=p.workspace_id AND stock.item_code=line->>'item_code' AND stock.uom_id=part->>'uom_id'
   AND u.decimal_places=(part->>'quantity_precision')::integer
   AND(line->>'quantity')::numeric*power(10::numeric,u.decimal_places)=trunc((line->>'quantity')::numeric*power(10::numeric,u.decimal_places)))
   AND EXISTS(SELECT 1 FROM reconforge.inventory_locations loc JOIN reconforge.inventory_warehouses z ON z.tenant_id=loc.tenant_id AND z.id=loc.warehouse_id
    WHERE loc.tenant_id=t AND loc.id=part->>'location_id' AND z.warehouse_code||'/'||loc.location_code=line->>'location_code'
    AND z.workspace_id=p.workspace_id AND z.organization_id=p.organization_id AND(z.legal_entity_id IS NULL OR z.legal_entity_id=p.legal_entity_id)
    AND loc.location_type='Internal' AND NOT loc.allow_negative)
   AND EXISTS(SELECT 1 FROM reconforge.inventory_valuation_policies z WHERE z.tenant_id=t AND z.id=part->>'policy_id'
    AND z.workspace_id=p.workspace_id AND z.organization_id=p.organization_id AND z.legal_entity_id=p.legal_entity_id
    AND z.policy_code=line->>'policy_code' AND z.currency_code=request->>'currency_code' AND z.costing_method='FIFO'),
   'Every original demand line requires its actual scoped stock, precise base unit, warehouse and FIFO policy');
  part:=source->'request'->'requirements'->position;
  IF part IS DISTINCT FROM 'null'::jsonb THEN
   PERFORM reconforge.ps_assert(part IS NOT NULL AND part->>'requirement_digest'=source->'manufacturing_requirements'->position->>'requirement_digest',
    'A manufacturing-linked demand requires its exact immutable requirement evidence');
   -- Dynamic guarded SQL preserves ordinary-source roles and independent installations.
   EXECUTE 'SELECT requirement_json,requirement_digest,required_quantity_scaled,quantity_precision,item_id,uom_id,workspace_id,organization_id,legal_entity_id FROM reconforge.manufacturing_execution_requirements WHERE tenant_id=$1 AND id=$2'
    INTO x USING t,part->>'requirement_id';
   PERFORM reconforge.ps_assert(x.requirement_digest=part->>'requirement_digest' AND reconforge.irp_digest(x.requirement_json)=x.requirement_digest
    AND (source->'manufacturing_requirements'->position)-'requirement_digest'=x.requirement_json
    AND x.requirement_json->>'item_code'=line->>'item_code'
    AND(x.item_id,x.uom_id,x.quantity_precision)=(source->'demand_masters'->position->>'item_id',source->'demand_masters'->position->>'uom_id',
      (source->'demand_masters'->position->>'quantity_precision')::integer)
    AND(x.workspace_id,x.organization_id,x.legal_entity_id)=(p.workspace_id,p.organization_id,p.legal_entity_id)
    AND(x.requirement_json->>'item_id',x.requirement_json->>'uom_id',x.requirement_json->>'quantity_precision',x.requirement_json->>'required_quantity_scaled')
      =(x.item_id,x.uom_id,x.quantity_precision::text,x.required_quantity_scaled::text)
    AND(x.requirement_json#>>'{scope,workspace_id}',x.requirement_json#>>'{scope,organization_id}',x.requirement_json#>>'{scope,legal_entity_id}')=(p.workspace_id,p.organization_id,p.legal_entity_id)
    AND(line->>'quantity')::numeric*power(10::numeric,x.quantity_precision)=trunc((line->>'quantity')::numeric*power(10::numeric,x.quantity_precision))
    AND(line->>'quantity')::numeric*power(10::numeric,x.quantity_precision)<=x.required_quantity_scaled,
    'Manufacturing-linked procurement demand must match its original scoped item and exact required quantity');
  END IF;
  position:=position+1;
 END LOOP;
 PERFORM reconforge.ps_assert(total=p.ceiling_minor,'Original demand sum differs from its retained appropriation ceiling');
 PERFORM reconforge.ps_assert((SELECT count(*) FROM reconforge.procurement_sourcing_quotes WHERE tenant_id=t AND requisition_id=i)<=32,'The original offer set is explicitly bounded');
 FOR q IN SELECT * FROM reconforge.procurement_sourcing_quotes WHERE tenant_id=t AND requisition_id=i ORDER BY created_version LOOP
  PERFORM reconforge.ps_assert(q.quote_digest=reconforge.irp_digest(q.payload) AND q.payload->>'schema_version'='supplier-quotation-v1'
   AND q.payload->>'requisition_id'=i AND q.payload->>'source_digest'=p.source_digest AND q.payload->>'supplier_id'=q.supplier_id
   AND q.payload->>'registrar_actor_id'=q.registrar_actor_id AND(q.payload->>'total_minor')::numeric=q.total_minor
   AND q.payload#>>'{quotation,supplier_code}'=q.supplier_code AND q.payload#>>'{order,supplier_code}'=q.supplier_code
   AND (q.payload->'order')-ARRAY['number','supplier_code','lines']=request-ARRAY['number','supplier_code','lines']
   AND q.payload#>>'{order,number}'='BPC1-'||p.number
   AND jsonb_array_length(q.payload#>'{quotation,unit_prices_minor}')=jsonb_array_length(request->'lines')
   AND jsonb_array_length(q.payload#>'{order,lines}')=jsonb_array_length(request->'lines')
   AND q.payload#>>'{quotation,valid_until}'>=request->>'posting_date'
   AND EXISTS(SELECT 1 FROM reconforge.ap_suppliers s WHERE s.tenant_id=t AND s.id=q.supplier_id AND s.supplier_code=q.supplier_code
    AND s.workspace_id=p.workspace_id AND(s.organization_id IS NULL OR s.organization_id=p.organization_id)
    AND(s.legal_entity_id IS NULL OR s.legal_entity_id=p.legal_entity_id) AND s.currency_code=request->>'currency_code'),
   'Every quote must preserve all original demanded quantities, warehouse ownership and monetary policy');
  total:=0;position:=0;
  FOR line IN SELECT * FROM jsonb_array_elements(request->'lines') LOOP
   part:=q.payload#>'{order,lines}'->position;
   price:=(q.payload#>'{quotation,unit_prices_minor}'->>position)::numeric;
   PERFORM reconforge.ps_assert(jsonb_typeof(q.payload#>'{quotation,unit_prices_minor}'->position)='number' AND price=trunc(price)
    AND price BETWEEN 1 AND 9000000000000000000 AND(part->>'unit_price_minor')::numeric=price
    AND part-'unit_price_minor'=line-'unit_price_minor','Quotation prices may change; original per-line quantities and masters cannot');
   amount:=(line->>'quantity')::numeric*price;
   PERFORM reconforge.ps_assert(amount=trunc(amount) AND amount BETWEEN 1 AND 9000000000000000000,'Quotation products must be exact minor units');
   total:=total+amount;position:=position+1;
  END LOOP;
  PERFORM reconforge.ps_assert(total=q.total_minor,'Retained supplier quotation total does not equal its exact original line products');
 END LOOP;
 SELECT * INTO r FROM reconforge.procurement_sourcing_events WHERE tenant_id=t AND requisition_id=i AND operation='review-selection';
 SELECT * INTO a FROM reconforge.procurement_sourcing_events WHERE tenant_id=t AND requisition_id=i AND operation='award';
 SELECT id INTO winner FROM reconforge.procurement_sourcing_quotes WHERE tenant_id=t AND requisition_id=i ORDER BY total_minor,supplier_code COLLATE "C" LIMIT 1;
 PERFORM reconforge.ps_assert((r.version IS NULL)=(p.selected_quote_id IS NULL) AND(r.version IS NULL OR p.selected_quote_id=winner)
 AND(r.version IS NULL OR NOT EXISTS(SELECT 1 FROM reconforge.procurement_sourcing_quotes WHERE tenant_id=t AND requisition_id=i AND(created_version>=r.version OR registrar_actor_id=r.actor_id OR total_minor<1)))
 AND(r.version IS NULL OR(SELECT total_minor FROM reconforge.procurement_sourcing_quotes WHERE tenant_id=t AND id=winner)<=p.ceiling_minor),
 'The reviewed frozen offer set must choose the deterministic exact winner under the original ceiling');
 FOR x IN SELECT * FROM reconforge.procurement_sourcing_events WHERE tenant_id=t AND requisition_id=i ORDER BY version LOOP
  seen:=seen+1;
  next_stage:=CASE x.operation WHEN'create' THEN 0 WHEN'open-rfq' THEN 1 WHEN'quote' THEN 1 WHEN'review-selection' THEN 2 WHEN'award' THEN 3 ELSE 4 END;
  PERFORM reconforge.ps_assert(x.version=seen AND((x.operation='create' AND seen=1 AND x.actor_id=p.creator_actor_id)
    OR(x.operation='open-rfq' AND prior=0 AND seen=2 AND x.actor_id<>p.creator_actor_id)
    OR(x.operation='quote' AND prior=1 AND EXISTS(SELECT 1 FROM reconforge.procurement_sourcing_quotes z WHERE z.tenant_id=t AND z.requisition_id=i AND z.created_version=x.version AND z.registrar_actor_id=x.actor_id))
    OR(x.operation='review-selection' AND prior=1 AND x.actor_id<>p.creator_actor_id)
    OR(x.operation='award' AND prior=2 AND x.actor_id<>p.creator_actor_id AND x.actor_id<>r.actor_id
     AND NOT EXISTS(SELECT 1 FROM reconforge.procurement_sourcing_events z WHERE z.tenant_id=t AND z.requisition_id=i AND z.operation='open-rfq' AND z.actor_id=x.actor_id)
     AND NOT EXISTS(SELECT 1 FROM reconforge.procurement_sourcing_quotes z WHERE z.tenant_id=t AND z.id=p.selected_quote_id AND z.registrar_actor_id=x.actor_id))
    OR(x.operation='cancel' AND prior IN(0,1,2) AND x.actor_id<>p.creator_actor_id))
   AND x.request_digest=reconforge.irp_digest(x.request_json) AND x.request_json->>'actor_id'=x.actor_id AND x.request_json->>'operation'=x.operation,
   'Sourcing lifecycle must retain every consecutive command and independent human approval');
  IF x.operation='create' THEN PERFORM reconforge.ps_assert(x.request_json->'request'=source->'request','Original sourcing preparation acknowledgment differs');
  ELSIF x.operation='quote' THEN
   SELECT * INTO q FROM reconforge.procurement_sourcing_quotes WHERE tenant_id=t AND requisition_id=i AND created_version=x.version;
   PERFORM reconforge.ps_assert(x.request_json->'request'=jsonb_build_object('requisition_id',i,'expected_version',x.version-1,'quotation',q.payload->'quotation')
    AND q.payload#>>'{quotation,reason}'=x.reason,'Quote command must retain its entire immutable original offer');
  ELSE
   PERFORM reconforge.ps_assert((x.request_json->'request')-'expected_budget_version'=jsonb_build_object('requisition_id',i,'expected_version',x.version-1,'reason',x.reason)
    AND(x.operation='award')=((x.request_json->'request')?'expected_budget_version'),'Approval command must bind the exact preceding source version and reason');
  END IF;
  metadata:=jsonb_build_object('source_digest',p.source_digest,'command_id',x.command_id,'request_digest',x.request_digest,'version',x.version,'operation',x.operation,'reason',x.reason);
  PERFORM reconforge.ps_assert(EXISTS(SELECT 1 FROM reconforge.domain_audit_events d JOIN reconforge.outbox_events z ON z.tenant_id=d.tenant_id
   WHERE d.tenant_id=t AND d.id=x.audit_event_id AND z.event_id=x.outbox_event_id AND d.actor_user_id=x.actor_id
   AND d.object_type='procurement_sourcing' AND d.object_id=i AND d.action='procurement_sourcing_'||x.operation AND d.metadata_json=metadata
   AND z.aggregate_type='procurement_sourcing' AND z.aggregate_id=i AND z.event_type=d.action AND z.payload=metadata||jsonb_build_object('audit_event_id',d.id)
   AND(z.workspace_id,z.organization_id,z.legal_entity_id)=(p.workspace_id,p.organization_id,p.legal_entity_id)),'Source approval evidence requires its exact native audit and outbox');
  SELECT * INTO c FROM reconforge.procurement_sourcing_commands WHERE tenant_id=t AND requisition_id=i AND version=x.version;
  PERFORM reconforge.ps_assert(c.command_id=x.command_id AND c.actor_id=x.actor_id AND c.request_json=x.request_json AND c.request_digest=x.request_digest
   AND c.workspace_id=p.workspace_id AND c.response_json=reconforge.ps_public(t,i,x.version),'Every source effect requires its exact immutable replay acknowledgment');
  prior:=next_stage;
 END LOOP;
 PERFORM reconforge.ps_assert(seen=p.row_version AND prior=p.phase AND seen=(SELECT count(*) FROM reconforge.procurement_sourcing_commands WHERE tenant_id=t AND requisition_id=i)
 AND(SELECT count(*) FROM reconforge.procurement_sourcing_quotes WHERE tenant_id=t AND requisition_id=i)
 =(SELECT count(*) FROM reconforge.procurement_sourcing_events WHERE tenant_id=t AND requisition_id=i AND operation='quote'),'Current source stage and immutable command history must close exactly');
 SELECT * INTO o FROM reconforge.procurement_partial_orders WHERE tenant_id=t AND id=p.order_id;
 PERFORM reconforge.ps_assert((o.id IS NOT NULL)=(p.phase=3) AND(a.version IS NOT NULL)=(p.phase=3),'Only the approved third-human source award may create its native budget-backed purchase');
 IF p.phase=3 THEN
  SELECT * INTO q FROM reconforge.procurement_sourcing_quotes WHERE tenant_id=t AND id=p.selected_quote_id;
  PERFORM reconforge.ps_assert(o.number='BPC1-'||p.number AND o.creator_actor_id=a.actor_id
   AND(o.workspace_id,o.organization_id,o.legal_entity_id)=(p.workspace_id,p.organization_id,p.legal_entity_id)
   AND o.request_json-ARRAY['item_code','quantity','unit_price_minor','location_code','policy_code']=q.payload->'order'
   AND o.total_minor=q.total_minor AND o.multiline
   AND EXISTS(SELECT 1 FROM reconforge.procurement_commitment_plans z JOIN reconforge.procurement_commitment_commands y ON y.tenant_id=z.tenant_id AND y.order_id=z.order_id
    WHERE z.tenant_id=t AND z.order_id=p.order_id AND z.budget_id=p.budget_id AND y.operation='create' AND y.actor_id=a.actor_id
    AND(y.request_json#>>'{request,expected_budget_version}')::bigint=(a.request_json#>>'{request,expected_budget_version}')::bigint
    AND y.request_json#>>'{request,reason}'=a.reason),'Native purchase and original appropriation must exactly match the reviewed supplier award');
  PERFORM reconforge.pc_close(t,p.order_id);
 END IF;
END $ps$;
"""

_CLOSURE = r"""
CREATE FUNCTION reconforge.ps_reverse_close() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $ps$
DECLARE j JSONB;identifier TEXT;number TEXT;
BEGIN
 j:=CASE WHEN TG_OP='DELETE' THEN to_jsonb(OLD) ELSE to_jsonb(NEW) END;
 IF TG_TABLE_NAME='procurement_partial_orders' THEN
  number:=j->>'number';
  IF left(number,10) IS DISTINCT FROM 'BPC1-SRC5-' THEN RETURN NULL; END IF;
  SELECT id INTO identifier FROM reconforge.procurement_sourcing_requisitions WHERE tenant_id=j->>'tenant_id' AND order_id=j->>'id';
 ELSIF TG_TABLE_NAME IN('domain_audit_events','outbox_events') THEN identifier:=COALESCE(j->>'object_id',j->>'aggregate_id');
 ELSE identifier:=COALESCE(j->>'requisition_id',j->>'id'); END IF;
 PERFORM reconforge.ps_assert(identifier IS NOT NULL,'Reserved sourcing purchase namespace requires its exact original award owner');
 PERFORM reconforge.ps_close(j->>'tenant_id',identifier); RETURN NULL;
END $ps$;
DO $ps$ DECLARE n TEXT;BEGIN
 FOREACH n IN ARRAY ARRAY['procurement_sourcing_requisitions','procurement_sourcing_quotes','procurement_sourcing_events','procurement_sourcing_commands','procurement_partial_orders'] LOOP
 EXECUTE format('CREATE CONSTRAINT TRIGGER sourcing_closure AFTER INSERT OR UPDATE OR DELETE ON reconforge.%I DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION reconforge.ps_reverse_close()',n);
 END LOOP;
END $ps$;
CREATE CONSTRAINT TRIGGER sourcing_audit_closure AFTER UPDATE OR DELETE ON reconforge.domain_audit_events DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
 WHEN(OLD.object_type='procurement_sourcing') EXECUTE FUNCTION reconforge.ps_reverse_close();
CREATE CONSTRAINT TRIGGER sourcing_outbox_closure AFTER UPDATE OR DELETE ON reconforge.outbox_events DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
 WHEN(OLD.aggregate_type='procurement_sourcing') EXECUTE FUNCTION reconforge.ps_reverse_close();
"""

UPGRADE_SQL = _TABLES + _VERIFY + _CLOSURE
DOWNGRADE_SQL = r"""
DO $ps$ BEGIN IF EXISTS(SELECT 1 FROM reconforge.procurement_sourcing_requisitions) THEN
 RAISE EXCEPTION 'Retained sourcing history requires forward correction or verified pre-upgrade restore'; END IF; END $ps$;
DROP TRIGGER sourcing_audit_closure ON reconforge.domain_audit_events;
DROP TRIGGER sourcing_outbox_closure ON reconforge.outbox_events;
DROP TRIGGER sourcing_closure ON reconforge.procurement_partial_orders;
ALTER TABLE reconforge.procurement_sourcing_requisitions DROP CONSTRAINT sourcing_selected_quote;
DROP TABLE reconforge.procurement_sourcing_commands;
DROP TABLE reconforge.procurement_sourcing_events;
DROP TABLE reconforge.procurement_sourcing_quotes;
DROP TABLE reconforge.procurement_sourcing_requisitions;
DROP FUNCTION reconforge.ps_reverse_close();
DROP FUNCTION reconforge.ps_close(TEXT,TEXT);
DROP FUNCTION reconforge.ps_public(TEXT,TEXT,BIGINT);
DROP FUNCTION reconforge.ps_protect();
DROP FUNCTION reconforge.ps_authority(TEXT,TEXT,TEXT,TEXT,TEXT,TEXT);
DROP FUNCTION reconforge.ps_assert(BOOLEAN,TEXT);
"""


def install_postgres_procurement_sourcing(connection: Any) -> None:
    row = connection.execute("SELECT to_regclass('reconforge.procurement_sourcing_requisitions') AS installed").fetchone()
    if (row["installed"] if isinstance(row, Mapping) else row[0]) is None:
        with connection.transaction():
            connection.execute(UPGRADE_SQL)
