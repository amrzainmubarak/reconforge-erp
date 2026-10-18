"""ME1 source ownership, physical reservations and native accounting closure.

Revision 0133 imports these static statements. Earlier published migrations and
their native definitions remain unchanged; the capacity wrapper is reversible.
"""
from collections.abc import Mapping
from typing import Any

_TABLES_SQL = r"""
ALTER TABLE reconforge.inventory_movements ADD COLUMN manufacturing_claim_state TEXT
 CHECK(manufacturing_claim_state IN('Reserved','IssuePrepared','IssueReviewed','Issued','Cancelled'));
CREATE TABLE reconforge.manufacturing_execution_boms (
 tenant_id TEXT NOT NULL,id TEXT NOT NULL,workspace_id TEXT NOT NULL,organization_id TEXT NOT NULL,legal_entity_id TEXT NOT NULL,
 number TEXT NOT NULL,version BIGINT NOT NULL CHECK(version>0),payload JSONB NOT NULL,source_digest TEXT NOT NULL CHECK(source_digest~'^[a-f0-9]{64}$'),
 phase INTEGER NOT NULL DEFAULT 0 CHECK(phase IN(0,1)),creator_id TEXT NOT NULL,reviewer_id TEXT,
 PRIMARY KEY(tenant_id,id),UNIQUE(tenant_id,workspace_id,legal_entity_id,number,version),
 FOREIGN KEY(tenant_id,creator_id) REFERENCES reconforge.identity_users(tenant_id,id),
 FOREIGN KEY(tenant_id,reviewer_id) REFERENCES reconforge.identity_users(tenant_id,id),CHECK(left(id,5)='ME1B-')
);
CREATE TABLE reconforge.manufacturing_execution_orders (
 tenant_id TEXT NOT NULL,id TEXT NOT NULL,workspace_id TEXT NOT NULL,organization_id TEXT NOT NULL,legal_entity_id TEXT NOT NULL,
 number TEXT NOT NULL,bom_version_id TEXT NOT NULL,movement_id TEXT NOT NULL,payload JSONB NOT NULL,source_digest TEXT NOT NULL CHECK(source_digest~'^[a-f0-9]{64}$'),
 phase INTEGER NOT NULL DEFAULT 0 CHECK(phase BETWEEN 0 AND 5),issue_plan JSONB,issue_digest TEXT,issue_reviewer_id TEXT,
 issue_effect_id TEXT,valuation_id TEXT,disposed_quantity_scaled BIGINT NOT NULL DEFAULT 0 CHECK(disposed_quantity_scaled>=0),
 released_cost_minor BIGINT NOT NULL DEFAULT 0 CHECK(released_cost_minor>=0),
 PRIMARY KEY(tenant_id,id),UNIQUE(tenant_id,workspace_id,number),UNIQUE(tenant_id,movement_id),
 FOREIGN KEY(tenant_id,bom_version_id) REFERENCES reconforge.manufacturing_execution_boms(tenant_id,id),
 FOREIGN KEY(tenant_id,movement_id) REFERENCES reconforge.inventory_movements(tenant_id,id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(tenant_id,issue_reviewer_id) REFERENCES reconforge.identity_users(tenant_id,id),
 FOREIGN KEY(tenant_id,issue_effect_id) REFERENCES reconforge.finance_posting_effects(tenant_id,id) DEFERRABLE INITIALLY DEFERRED,
 CHECK(left(id,4)='ME1-')
);
CREATE TABLE reconforge.manufacturing_execution_requirements (
 tenant_id TEXT NOT NULL,id TEXT NOT NULL,order_id TEXT NOT NULL,bom_version_id TEXT NOT NULL,
 workspace_id TEXT NOT NULL,organization_id TEXT NOT NULL,legal_entity_id TEXT NOT NULL,item_id TEXT NOT NULL,uom_id TEXT NOT NULL,
 required_quantity_scaled BIGINT NOT NULL CHECK(required_quantity_scaled BETWEEN 1 AND 9000000000000000000),
 quantity_precision INTEGER NOT NULL CHECK(quantity_precision BETWEEN 0 AND 6),requirement_json JSONB NOT NULL,
 requirement_digest TEXT NOT NULL CHECK(requirement_digest~'^[a-f0-9]{64}$'),
 PRIMARY KEY(tenant_id,id),UNIQUE(tenant_id,order_id,item_id),
 FOREIGN KEY(tenant_id,order_id) REFERENCES reconforge.manufacturing_execution_orders(tenant_id,id),
 FOREIGN KEY(tenant_id,item_id) REFERENCES reconforge.inventory_items(tenant_id,id),
 FOREIGN KEY(tenant_id,uom_id) REFERENCES reconforge.inventory_units_of_measure(tenant_id,id),CHECK(left(id,5)='ME1R-')
);
CREATE TABLE reconforge.manufacturing_execution_reservations (
 tenant_id TEXT NOT NULL,requirement_id TEXT NOT NULL,order_id TEXT NOT NULL,workspace_id TEXT NOT NULL,organization_id TEXT NOT NULL,legal_entity_id TEXT NOT NULL,
 item_id TEXT NOT NULL,location_id TEXT NOT NULL,quantity_scaled BIGINT NOT NULL CHECK(quantity_scaled>0),
 state TEXT NOT NULL DEFAULT 'Active' CHECK(state IN('Active','Consumed','Released')),
 PRIMARY KEY(tenant_id,requirement_id),FOREIGN KEY(tenant_id,requirement_id) REFERENCES reconforge.manufacturing_execution_requirements(tenant_id,id)
);
CREATE INDEX manufacturing_reservation_capacity ON reconforge.manufacturing_execution_reservations(tenant_id,workspace_id,legal_entity_id,location_id,item_id) WHERE state='Active';
CREATE TABLE reconforge.manufacturing_execution_completions (
 tenant_id TEXT NOT NULL,id TEXT NOT NULL,order_id TEXT NOT NULL,workspace_id TEXT NOT NULL,organization_id TEXT NOT NULL,legal_entity_id TEXT NOT NULL,
 payload JSONB NOT NULL,source_digest TEXT NOT NULL CHECK(source_digest~'^[a-f0-9]{64}$'),phase INTEGER NOT NULL DEFAULT 0 CHECK(phase BETWEEN 0 AND 3),
 reviewer_id TEXT,receipt_effect JSONB,scrap_effect_id TEXT,
 PRIMARY KEY(tenant_id,id),FOREIGN KEY(tenant_id,order_id) REFERENCES reconforge.manufacturing_execution_orders(tenant_id,id),
 FOREIGN KEY(tenant_id,reviewer_id) REFERENCES reconforge.identity_users(tenant_id,id),
 FOREIGN KEY(tenant_id,scrap_effect_id) REFERENCES reconforge.finance_posting_effects(tenant_id,id) DEFERRABLE INITIALLY DEFERRED,
 CHECK(left(id,5)='ME1C-')
);
CREATE UNIQUE INDEX manufacturing_pending_completion ON reconforge.manufacturing_execution_completions(tenant_id,order_id) WHERE phase IN(0,1);
CREATE TABLE reconforge.manufacturing_execution_events (
 tenant_id TEXT NOT NULL,object_id TEXT NOT NULL,operation TEXT NOT NULL,actor_id TEXT NOT NULL,reason TEXT NOT NULL,
 audit_event_id TEXT NOT NULL,outbox_event_id TEXT NOT NULL,metadata JSONB NOT NULL,
 PRIMARY KEY(tenant_id,object_id,operation),FOREIGN KEY(tenant_id,actor_id) REFERENCES reconforge.identity_users(tenant_id,id),
 FOREIGN KEY(tenant_id,audit_event_id) REFERENCES reconforge.domain_audit_events(tenant_id,id),
 FOREIGN KEY(tenant_id,outbox_event_id) REFERENCES reconforge.outbox_events(tenant_id,event_id)
);
CREATE TABLE reconforge.manufacturing_execution_commands (
 tenant_id TEXT NOT NULL,workspace_id TEXT NOT NULL,object_id TEXT NOT NULL,operation TEXT NOT NULL,command_id TEXT NOT NULL CHECK(length(command_id) BETWEEN 1 AND 140),
 actor_id TEXT NOT NULL,request_json JSONB NOT NULL,request_digest TEXT NOT NULL CHECK(request_digest~'^[a-f0-9]{64}$'),response_json JSONB NOT NULL,
 PRIMARY KEY(tenant_id,workspace_id,command_id),UNIQUE(tenant_id,object_id,operation),
 FOREIGN KEY(tenant_id,object_id,operation) REFERENCES reconforge.manufacturing_execution_events(tenant_id,object_id,operation)
);
"""

_PROTECTION_SQL = r"""
CREATE FUNCTION reconforge.me1_permission(operation TEXT) RETURNS TEXT LANGUAGE sql IMMUTABLE SET search_path=pg_catalog AS $me$
 SELECT 'manufacturing_execution.'||CASE WHEN operation IN('approve-bom','review','cancel') THEN 'approve' WHEN operation='post' THEN 'post' ELSE 'manage' END $me$;
CREATE FUNCTION reconforge.me1_visible(t TEXT,i TEXT) RETURNS BOOLEAN LANGUAGE plpgsql STABLE SET search_path=pg_catalog AS $me$
DECLARE d RECORD;
BEGIN
 IF left(i,5)='ME1B-' THEN SELECT * INTO d FROM reconforge.manufacturing_execution_boms WHERE tenant_id=t AND id=i;
 ELSIF left(i,5)='ME1C-' THEN SELECT * INTO d FROM reconforge.manufacturing_execution_completions WHERE tenant_id=t AND id=i;
 ELSE SELECT * INTO d FROM reconforge.manufacturing_execution_orders WHERE tenant_id=t AND id=i; END IF;
 RETURN d.id IS NOT NULL AND reconforge.irp_scope(t,d.workspace_id,d.organization_id,d.legal_entity_id);
END $me$;
CREATE FUNCTION reconforge.me1_protect() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $me$
DECLARE a TEXT:=current_setting('app.manufacturing_execution_actor_id',true);p TEXT;d RECORD;w TEXT;o TEXT;e TEXT;
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='manufacturing_execution_owner',MESSAGE='Manufacturing source history is immutable'; END IF;
 IF TG_TABLE_NAME IN('manufacturing_execution_events','manufacturing_execution_commands') THEN p:=reconforge.me1_permission(NEW.operation);
 ELSIF TG_TABLE_NAME='manufacturing_execution_boms' THEN p:=CASE WHEN NEW.phase=1 THEN 'manufacturing_execution.approve' ELSE 'manufacturing_execution.manage' END;
 ELSIF TG_TABLE_NAME='manufacturing_execution_completions' THEN p:=CASE WHEN NEW.phase IN(1,3) THEN 'manufacturing_execution.approve' WHEN NEW.phase=2 THEN 'manufacturing_execution.post' ELSE 'manufacturing_execution.manage' END;
 ELSIF TG_TABLE_NAME='manufacturing_execution_orders' THEN p:=CASE WHEN NEW.phase IN(2,5) THEN 'manufacturing_execution.approve' WHEN NEW.phase IN(3,4) THEN 'manufacturing_execution.post' ELSE 'manufacturing_execution.manage' END;
 ELSE p:='manufacturing_execution.manage'; END IF;
 IF TG_TABLE_NAME='manufacturing_execution_reservations' AND TG_OP='UPDATE' THEN
  SELECT phase INTO d FROM reconforge.manufacturing_execution_orders WHERE tenant_id=NEW.tenant_id AND id=NEW.order_id;
  p:=CASE WHEN d.phase=5 THEN 'manufacturing_execution.approve' ELSE 'manufacturing_execution.post' END;
 END IF;
 IF NOT reconforge.sales_revenue_actor(NEW.tenant_id,a,p) THEN
  RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='manufacturing_execution_owner',MESSAGE='Manufacturing requires current persisted human authority'; END IF;
 IF TG_TABLE_NAME IN('manufacturing_execution_events','manufacturing_execution_commands') THEN
  IF left(NEW.object_id,5)='ME1B-' THEN SELECT workspace_id,organization_id,legal_entity_id INTO w,o,e FROM reconforge.manufacturing_execution_boms WHERE tenant_id=NEW.tenant_id AND id=NEW.object_id;
  ELSIF left(NEW.object_id,5)='ME1C-' THEN SELECT workspace_id,organization_id,legal_entity_id INTO w,o,e FROM reconforge.manufacturing_execution_completions WHERE tenant_id=NEW.tenant_id AND id=NEW.object_id;
  ELSE SELECT workspace_id,organization_id,legal_entity_id INTO w,o,e FROM reconforge.manufacturing_execution_orders WHERE tenant_id=NEW.tenant_id AND id=NEW.object_id;END IF;
 ELSE w:=NEW.workspace_id;o:=NEW.organization_id;e:=NEW.legal_entity_id;END IF;
 PERFORM 1 FROM reconforge.principal_scope_grants WHERE tenant_id=NEW.tenant_id AND principal_type='user' AND principal_id=a
  AND revoked_at IS NULL AND((scope_type='workspace' AND scope_id=w) OR(scope_type='organization' AND scope_id=o) OR(scope_type='legal_entity' AND scope_id=e)) ORDER BY scope_type,scope_id FOR SHARE;
 IF(SELECT count(DISTINCT(scope_type,scope_id)) FROM reconforge.principal_scope_grants WHERE tenant_id=NEW.tenant_id AND principal_type='user' AND principal_id=a
  AND revoked_at IS NULL AND((scope_type='workspace' AND scope_id=w) OR(scope_type='organization' AND scope_id=o) OR(scope_type='legal_entity' AND scope_id=e)))<>3 THEN
  RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='manufacturing_execution_owner',MESSAGE='Manufacturing requires all current persisted parent scopes';END IF;
 IF TG_OP='INSERT' THEN
  IF TG_TABLE_NAME IN('manufacturing_execution_boms','manufacturing_execution_orders','manufacturing_execution_completions') THEN
   IF NEW.phase<>0 THEN RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='manufacturing_execution_owner',MESSAGE='Manufacturing sources are born unposted'; END IF;
  END IF;
  IF TG_TABLE_NAME IN('manufacturing_execution_events','manufacturing_execution_commands') THEN
   IF NEW.actor_id IS DISTINCT FROM a THEN RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='manufacturing_execution_owner',MESSAGE='Evidence must identify the actual current human'; END IF;
  END IF;
  RETURN NEW;
 END IF;
 IF TG_TABLE_NAME='manufacturing_execution_boms' THEN
  IF OLD.phase<>0 OR NEW.phase<>1 OR NEW.reviewer_id IS DISTINCT FROM a OR a=OLD.creator_id
   OR(to_jsonb(NEW)-ARRAY['phase','reviewer_id']) IS DISTINCT FROM(to_jsonb(OLD)-ARRAY['phase','reviewer_id']) THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='manufacturing_execution_owner',MESSAGE='Approved BOM versions are immutable and independently reviewed'; END IF;
 ELSIF TG_TABLE_NAME='manufacturing_execution_orders' THEN
  IF(to_jsonb(NEW)-ARRAY['phase','issue_plan','issue_digest','issue_reviewer_id','issue_effect_id','valuation_id','disposed_quantity_scaled','released_cost_minor'])
   IS DISTINCT FROM(to_jsonb(OLD)-ARRAY['phase','issue_plan','issue_digest','issue_reviewer_id','issue_effect_id','valuation_id','disposed_quantity_scaled','released_cost_minor'])
   OR NOT((OLD.phase=0 AND NEW.phase=1) OR(OLD.phase=1 AND NEW.phase=2) OR(OLD.phase=2 AND NEW.phase=3)
   OR(OLD.phase=3 AND NEW.phase IN(3,4)) OR(OLD.phase IN(0,1,2) AND NEW.phase=5))
   OR(OLD.issue_plan IS NOT NULL AND(NEW.issue_plan,NEW.issue_digest) IS DISTINCT FROM(OLD.issue_plan,OLD.issue_digest))
   OR(OLD.issue_reviewer_id IS NOT NULL AND NEW.issue_reviewer_id IS DISTINCT FROM OLD.issue_reviewer_id)
   OR(OLD.issue_effect_id IS NOT NULL AND(NEW.issue_effect_id,NEW.valuation_id) IS DISTINCT FROM(OLD.issue_effect_id,OLD.valuation_id)) THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='manufacturing_execution_owner',MESSAGE='Manufacturing order transition or retained cost changed'; END IF;
 ELSIF TG_TABLE_NAME='manufacturing_execution_completions' THEN
  IF(to_jsonb(NEW)-ARRAY['phase','reviewer_id','receipt_effect','scrap_effect_id']) IS DISTINCT FROM(to_jsonb(OLD)-ARRAY['phase','reviewer_id','receipt_effect','scrap_effect_id'])
   OR NOT((OLD.phase=0 AND NEW.phase=1) OR(OLD.phase=1 AND NEW.phase=2) OR(OLD.phase IN(0,1) AND NEW.phase=3))
   OR(OLD.reviewer_id IS NOT NULL AND NEW.reviewer_id IS DISTINCT FROM OLD.reviewer_id) THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='manufacturing_execution_owner',MESSAGE='Completion cannot change retained quantities, cost or source'; END IF;
 ELSIF TG_TABLE_NAME='manufacturing_execution_reservations' THEN
  IF OLD.state<>'Active' OR NEW.state NOT IN('Consumed','Released') OR(to_jsonb(NEW)-'state') IS DISTINCT FROM(to_jsonb(OLD)-'state') THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='manufacturing_execution_owner',MESSAGE='Material reservations retain their exact original demand'; END IF;
 ELSE RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='manufacturing_execution_owner',MESSAGE='Manufacturing source and evidence are immutable'; END IF;
 RETURN NEW;
END $me$;
CREATE FUNCTION reconforge.me1_ack(t TEXT,i TEXT,op TEXT) RETURNS JSONB LANGUAGE plpgsql SET search_path=pg_catalog AS $me$
DECLARE d RECORD;phase INTEGER;response JSONB;
BEGIN
 IF left(i,5)='ME1B-' THEN
  SELECT * INTO d FROM reconforge.manufacturing_execution_boms WHERE tenant_id=t AND id=i;
  phase:=CASE op WHEN 'create' THEN 0 WHEN 'approve-bom' THEN 1 ELSE NULL END;
  IF op='approve-bom' AND d.phase<>1 THEN phase:=NULL;END IF;
  response:=d.payload||jsonb_build_object('source_digest',d.source_digest,'phase',phase,'reviewer_id',CASE WHEN phase=1 THEN d.reviewer_id ELSE NULL END);
 ELSIF left(i,5)='ME1C-' THEN
  SELECT * INTO d FROM reconforge.manufacturing_execution_completions WHERE tenant_id=t AND id=i;
  phase:=CASE op WHEN 'create' THEN 0 WHEN 'review' THEN 1 WHEN 'post' THEN 2 WHEN 'cancel' THEN 3 ELSE NULL END;
  IF(op='review' AND d.reviewer_id IS NULL) OR(op='post' AND d.phase<>2) OR(op='cancel' AND d.phase<>3) THEN phase:=NULL;END IF;
  response:=d.payload||jsonb_build_object('source_digest',d.source_digest,'phase',phase,
   'reviewer_id',CASE WHEN phase IN(1,2,3) THEN d.reviewer_id ELSE NULL END,
   'receipt_effect',CASE WHEN phase=2 THEN d.receipt_effect ELSE NULL END,
   'scrap_effect_id',CASE WHEN phase=2 THEN d.scrap_effect_id ELSE NULL END);
 ELSE
  SELECT * INTO d FROM reconforge.manufacturing_execution_orders WHERE tenant_id=t AND id=i;
  phase:=CASE op WHEN 'create' THEN 0 WHEN 'prepare' THEN 1 WHEN 'review' THEN 2 WHEN 'post' THEN 3 WHEN 'cancel' THEN 5 ELSE NULL END;
  IF(op='prepare' AND d.issue_plan IS NULL) OR(op='review' AND d.issue_reviewer_id IS NULL)
   OR(op='post' AND d.phase NOT IN(3,4)) OR(op='cancel' AND d.phase<>5) THEN phase:=NULL;END IF;
  response:=d.payload||jsonb_build_object('source_digest',d.source_digest,'phase',phase,
   'issue_plan',CASE WHEN phase<>0 THEN d.issue_plan ELSE NULL END,'issue_digest',CASE WHEN phase<>0 THEN d.issue_digest ELSE NULL END,
   'issue_reviewer_id',CASE WHEN phase IN(2,3,5) THEN d.issue_reviewer_id ELSE NULL END,
   'issue_effect_id',CASE WHEN phase=3 THEN d.issue_effect_id ELSE NULL END,'valuation_id',CASE WHEN phase=3 THEN d.valuation_id ELSE NULL END,
   'disposed_quantity_scaled',0,'released_cost_minor',0);
 END IF;
 IF d.id IS NULL OR phase IS NULL THEN RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='manufacturing_execution_owner',MESSAGE='Historical manufacturing acknowledgement needs an exact owner operation'; END IF;
 RETURN response;
END $me$;
CREATE FUNCTION reconforge.me1_evidence(t TEXT,i TEXT,op TEXT,digest TEXT) RETURNS TEXT LANGUAGE plpgsql SET search_path=pg_catalog AS $me$
DECLARE e RECORD;c RECORD;response JSONB;request JSONB;
BEGIN
 SELECT * INTO e FROM reconforge.manufacturing_execution_events WHERE tenant_id=t AND object_id=i AND operation=op;
 SELECT * INTO c FROM reconforge.manufacturing_execution_commands WHERE tenant_id=t AND object_id=i AND operation=op;
 response:=reconforge.me1_ack(t,i,op);
 request:=CASE WHEN op='create' THEN response->'command_request' ELSE jsonb_build_object('id',i,'expected_digest',digest,'reason',e.reason) END;
 IF e IS NULL OR c IS NULL OR c.actor_id IS DISTINCT FROM e.actor_id OR reconforge.irp_digest(c.request_json) IS DISTINCT FROM c.request_digest
 OR c.request_json->>'actor_id' IS DISTINCT FROM e.actor_id OR c.request_json->>'operation' IS DISTINCT FROM op
 OR c.request_json IS DISTINCT FROM jsonb_build_object('actor_id',e.actor_id,'operation',op,'request',request)
 OR request->>'reason' IS DISTINCT FROM e.reason OR c.response_json IS DISTINCT FROM response
 OR c.workspace_id IS DISTINCT FROM response->>'workspace_id'
 OR e.metadata IS DISTINCT FROM jsonb_build_object('source_digest',digest,'phase',response->'phase','reason',e.reason)
 OR NOT EXISTS(SELECT 1 FROM reconforge.domain_audit_events a JOIN reconforge.outbox_events o ON o.tenant_id=a.tenant_id
  WHERE a.tenant_id=t AND a.id=e.audit_event_id AND a.actor_user_id=e.actor_id AND a.object_type='manufacturing_execution'
  AND a.object_id=i AND a.action='manufacturing_execution.'||op AND a.metadata_json=e.metadata
  AND o.event_id=e.outbox_event_id AND o.aggregate_type='manufacturing_execution' AND o.aggregate_id=i
  AND o.event_type=a.action AND o.payload=e.metadata||jsonb_build_object('audit_event_id',a.id)
  AND(o.workspace_id,o.organization_id,o.legal_entity_id) IS NOT DISTINCT FROM(response->>'workspace_id',response->>'organization_id',response->>'legal_entity_id')) THEN
  RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='manufacturing_execution_owner',MESSAGE='Every manufacturing phase requires exact command, audit and outbox evidence'; END IF;
 RETURN e.actor_id;
END $me$;
CREATE FUNCTION reconforge.me1_history(t TEXT,i TEXT) RETURNS VOID LANGUAGE plpgsql SET search_path=pg_catalog AS $me$
DECLARE phase RECORD;seal TEXT;
BEGIN
 FOR phase IN SELECT operation FROM reconforge.manufacturing_execution_commands WHERE tenant_id=t AND object_id=i
  UNION SELECT operation FROM reconforge.manufacturing_execution_events WHERE tenant_id=t AND object_id=i LOOP
  seal:=reconforge.me1_ack(t,i,phase.operation)->>'source_digest';
  PERFORM reconforge.me1_evidence(t,i,phase.operation,seal);
 END LOOP;
END $me$;
"""

_CAPACITY_SQL = r"""
ALTER FUNCTION reconforge.stock_sales_capacity(TEXT,TEXT,TEXT,TEXT,TEXT) RENAME TO stock_sales_capacity_pre_me1;
CREATE FUNCTION reconforge.stock_sales_capacity(t TEXT,w TEXT,e TEXT,l TEXT,i TEXT) RETURNS VOID LANGUAGE plpgsql SET search_path=pg_catalog AS $me$
DECLARE available NUMERIC;reserved NUMERIC;
BEGIN
 PERFORM reconforge.stock_sales_capacity_pre_me1(t,w,e,l,i);
 -- Relevance is established using existing native tables before any new-table query is planned.
 IF NOT EXISTS(SELECT 1 FROM reconforge.inventory_movements m JOIN reconforge.inventory_movement_lines x ON x.tenant_id=m.tenant_id AND x.movement_id=m.id
  WHERE m.tenant_id=t AND m.workspace_id=w AND m.legal_entity_id=e AND m.manufacturing_claim_state IN('Reserved','IssuePrepared','IssueReviewed')
  AND x.item_id=i AND x.from_location_id=l AND x.inventory_lot_id IS NULL) THEN RETURN; END IF;
 SELECT COALESCE(sum(CASE WHEN x.to_location_id=l THEN x.quantity_scaled ELSE 0 END-CASE WHEN x.from_location_id=l THEN x.quantity_scaled ELSE 0 END),0)
 INTO available FROM reconforge.inventory_movement_lines x JOIN reconforge.inventory_movements m ON m.tenant_id=x.tenant_id AND m.id=x.movement_id
 WHERE x.tenant_id=t AND m.workspace_id=w AND m.legal_entity_id=e AND m.status='Posted' AND x.item_id=i AND x.inventory_lot_id IS NULL;
 SELECT COALESCE(sum(quantity_scaled),0) INTO reserved FROM reconforge.stock_sales_reservations WHERE tenant_id=t AND workspace_id=w AND legal_entity_id=e AND location_id=l AND item_id=i AND state='Active';
 SELECT reserved+COALESCE(sum(quantity_scaled),0) INTO reserved FROM reconforge.manufacturing_execution_reservations WHERE tenant_id=t AND workspace_id=w AND legal_entity_id=e AND location_id=l AND item_id=i AND state='Active';
 IF available<reserved THEN RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='manufacturing_execution_owner',MESSAGE='Physical stock must cover all native sales and manufacturing reservations'; END IF;
END $me$;
CREATE FUNCTION reconforge.me1_native_guard() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $me$
DECLARE d RECORD;v RECORD;layer RECORD;ref TEXT;a TEXT:=current_setting('app.manufacturing_execution_actor_id',true);
BEGIN
 IF TG_TABLE_NAME='inventory_movements' THEN
  IF TG_OP='INSERT' AND NEW.manufacturing_claim_state IS NULL AND left(NEW.source_reference,4)<>'ME1-' THEN RETURN NEW; END IF;
  IF TG_OP='UPDATE' AND OLD.manufacturing_claim_state IS NULL AND NEW.manufacturing_claim_state IS NULL AND left(NEW.source_reference,4)<>'ME1-' THEN RETURN NEW; END IF;
  ref:=NEW.source_reference;
  SELECT * INTO d FROM reconforge.manufacturing_execution_orders WHERE tenant_id=NEW.tenant_id AND id=ref;
  IF d IS NULL OR d.movement_id IS DISTINCT FROM NEW.id OR NEW.source_type<>'Generated' OR NEW.movement_type<>'Delivery'
   OR NOT reconforge.sales_revenue_actor(NEW.tenant_id,a,CASE WHEN NEW.manufacturing_claim_state IN('IssueReviewed','Cancelled') THEN 'manufacturing_execution.approve' WHEN NEW.manufacturing_claim_state='Issued' THEN 'manufacturing_execution.post' ELSE 'manufacturing_execution.manage' END)
   OR NOT(COALESCE(NEW.manufacturing_claim_state,'Reserved')=CASE d.phase WHEN 0 THEN 'Reserved' WHEN 1 THEN 'IssuePrepared' WHEN 2 THEN 'IssueReviewed' WHEN 5 THEN 'Cancelled' ELSE 'Issued' END)
   OR NOT(NEW.status=CASE WHEN d.phase=4 THEN 'Posted' ELSE 'Draft' END OR(d.phase=3 AND NEW.status IN('Draft','Posted'))) THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='manufacturing_execution_owner',MESSAGE='Manufacturing native movement requires its exact owner phase and current human'; END IF;
 ELSIF TG_TABLE_NAME='inventory_movement_lines' THEN
  SELECT * INTO v FROM reconforge.inventory_movements WHERE tenant_id=NEW.tenant_id AND id=NEW.movement_id;
  IF v.manufacturing_claim_state IS NULL THEN RETURN NEW; END IF;
  IF TG_OP<>'INSERT' OR NOT EXISTS(SELECT 1 FROM reconforge.manufacturing_execution_requirements r JOIN reconforge.manufacturing_execution_orders o ON o.tenant_id=r.tenant_id AND o.id=r.order_id
   WHERE r.tenant_id=NEW.tenant_id AND o.movement_id=NEW.movement_id AND(r.item_id,r.uom_id,r.required_quantity_scaled,r.quantity_precision)
   IS NOT DISTINCT FROM(NEW.item_id,NEW.uom_id,NEW.quantity_scaled,NEW.quantity_precision) AND NEW.inventory_lot_id IS NULL
   AND NEW.to_location_id IS NULL AND NEW.from_location_id=o.payload->>'component_location_id') THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='manufacturing_execution_owner',MESSAGE='Native material issue lines must equal the complete immutable BOM requirements'; END IF;
 ELSE
  IF TG_TABLE_NAME='inventory_cost_layers' THEN layer:=NEW;
  ELSE SELECT * INTO layer FROM reconforge.inventory_cost_layers WHERE tenant_id=NEW.tenant_id AND id=NEW.cost_layer_id; END IF;
  IF NOT EXISTS(SELECT 1 FROM reconforge.inventory_movements m JOIN reconforge.inventory_movement_lines x ON x.tenant_id=m.tenant_id AND x.movement_id=m.id
   WHERE m.tenant_id=NEW.tenant_id AND m.workspace_id=layer.workspace_id AND m.legal_entity_id=layer.legal_entity_id
   AND m.manufacturing_claim_state IN('IssuePrepared','IssueReviewed') AND x.item_id=layer.item_id AND x.inventory_lot_id IS NULL) THEN RETURN NEW; END IF;
  PERFORM pg_advisory_xact_lock(hashtextextended(layer.legal_entity_id||'|'||layer.item_id||'|',0));
  FOR d IN SELECT o.* FROM reconforge.manufacturing_execution_orders o WHERE o.tenant_id=NEW.tenant_id AND o.phase IN(1,2)
   AND EXISTS(SELECT 1 FROM jsonb_array_elements(o.issue_plan->'components') c,jsonb_array_elements(c->'allocations') allocation WHERE allocation->>'cost_layer_id'=layer.id) LOOP
   IF TG_TABLE_NAME='inventory_cost_layers' THEN
    IF NEW.remaining_quantity_scaled<>OLD.remaining_quantity_scaled OR NEW.remaining_value_minor<>OLD.remaining_value_minor THEN
     RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='manufacturing_execution_owner',MESSAGE='Reviewed material FIFO residual is reserved by its exact manufacturing owner'; END IF;
   ELSE
    SELECT document.* INTO v FROM reconforge.inventory_valuation_lines detail JOIN reconforge.inventory_valuation_documents document ON document.tenant_id=detail.tenant_id AND document.id=detail.valuation_document_id WHERE detail.tenant_id=NEW.tenant_id AND detail.id=NEW.valuation_line_id;
    IF v.movement_id IS DISTINCT FROM d.movement_id THEN RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='manufacturing_execution_owner',MESSAGE='A material claim cannot be consumed by another source'; END IF;
   END IF;
  END LOOP;
 END IF;
 RETURN NEW;
END $me$;
"""

_CLOSURE_SQL = r"""
CREATE FUNCTION reconforge.me1_entry(t TEXT,p JSONB,reviewer TEXT,posted BOOLEAN,cancelled BOOLEAN DEFAULT FALSE) RETURNS VOID LANGUAGE plpgsql SET search_path=pg_catalog AS $me$
DECLARE e RECORD;f RECORD;l JSONB;head JSONB;native_lines JSONB;
BEGIN
 SELECT * INTO e FROM reconforge.finance_entries WHERE tenant_id=t AND id=p->>'entry_id';
 SELECT * INTO f FROM reconforge.finance_posting_effects WHERE tenant_id=t AND entry_id=p->>'entry_id';
 IF e IS NULL OR e.external_reference IS DISTINCT FROM p->'snapshot'->'entry'->>'external_reference'
 OR e.entry_number IS DISTINCT FROM p->'snapshot'->'entry'->>'entry_number' OR e.source_type<>'Manual'
 OR e.preparer_actor_id IS DISTINCT FROM p->'snapshot'->'entry'->>'preparer_actor_id'
 OR e.currency_registry_digest IS DISTINCT FROM p->'snapshot'->'entry'->>'currency_registry_digest'
 OR e.currency_precision IS DISTINCT FROM(p->'snapshot'->'entry'->>'currency_precision')::integer
 OR(reviewer IS NOT NULL AND(e.validator_actor_id IS DISTINCT FROM reviewer OR reviewer=e.preparer_actor_id))
 OR e.status IS DISTINCT FROM(CASE WHEN cancelled THEN 'Voided' WHEN reviewer IS NULL THEN 'Draft' ELSE 'Validated' END)
 OR posted IS DISTINCT FROM(f.id IS NOT NULL) OR(f.id IS NOT NULL AND(f.snapshot_json IS DISTINCT FROM p->'snapshot'
 OR f.validation_digest IS DISTINCT FROM p->>'validation_digest' OR f.posted_actor_id IN(e.preparer_actor_id,reviewer)))
 OR(SELECT count(*) FROM reconforge.finance_entry_lines WHERE tenant_id=t AND entry_id=e.id)<>jsonb_array_length(p->'snapshot'->'lines') THEN
  RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='manufacturing_execution_owner',MESSAGE='Manufacturing native financial source must preserve exact prepared/reviewed/posted evidence'; END IF;
 SELECT jsonb_object_agg(key,value) INTO head FROM jsonb_each(to_jsonb(e))
  WHERE key=ANY(ARRAY['id','workspace_id','journal_id','period_id','entry_number','posting_date','description','external_reference','source_type','currency_code',
   'currency_precision','currency_rounding_policy','currency_registry_version','currency_registry_digest','preparer_actor_id','reverses_posting_id']);
 head:=head||jsonb_build_object('organization_id',p->'snapshot'->'entry'->'organization_id','legal_entity_id',p->'snapshot'->'entry'->'legal_entity_id');
 SELECT jsonb_agg(jsonb_build_object('line_number',nl.line_number,'account_id',nl.account_id,'description',nl.description,
  'debit_minor',nl.debit_minor,'credit_minor',nl.credit_minor,'dimensions',COALESCE((SELECT jsonb_object_agg(d.dimension_id,d.dimension_value_id)
   FROM reconforge.finance_entry_line_dimensions d WHERE d.tenant_id=nl.tenant_id AND d.entry_line_id=nl.id),'{}'::jsonb)) ORDER BY nl.line_number)
  INTO native_lines FROM reconforge.finance_entry_lines nl WHERE nl.tenant_id=t AND nl.entry_id=e.id;
 IF p->>'validation_digest' IS DISTINCT FROM reconforge.irp_digest(p->'snapshot')
  OR p->'snapshot' IS DISTINCT FROM jsonb_build_object('schema_version','finance-entry-review-v1','entry',head,'lines',native_lines)
  OR NOT EXISTS(SELECT 1 FROM reconforge.legal_entities z JOIN reconforge.organizations o ON o.tenant_id=z.tenant_id AND o.id=z.organization_id
   WHERE z.tenant_id=t AND z.id=head->>'legal_entity_id' AND o.id=head->>'organization_id' AND z.entity_code=e.entity_code
    AND o.organization_code=e.organization_code AND o.application_workspace_id=e.workspace_id AND z.currency_code=e.currency_code) THEN
  RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='manufacturing_execution_owner',MESSAGE='Complete original native manufacturing entry snapshot must remain byte-canonical'; END IF;
 FOR l IN SELECT value FROM jsonb_array_elements(p->'snapshot'->'lines') LOOP
  IF l->'dimensions'<>'{}'::jsonb OR NOT EXISTS(SELECT 1 FROM reconforge.finance_entry_lines x WHERE x.tenant_id=t AND x.entry_id=e.id
   AND x.line_number=(l->>'line_number')::integer AND x.account_id=l->>'account_id'
   AND x.debit_minor=(l->>'debit_minor')::bigint AND x.credit_minor=(l->>'credit_minor')::bigint)
   OR EXISTS(SELECT 1 FROM reconforge.finance_entry_line_dimensions x JOIN reconforge.finance_entry_lines y ON y.tenant_id=x.tenant_id AND y.id=x.entry_line_id WHERE y.tenant_id=t AND y.entry_id=e.id) THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='manufacturing_execution_owner',MESSAGE='Manufacturing entry accounts and exact quantities cannot be detached from source'; END IF;
 END LOOP;
END $me$;
CREATE FUNCTION reconforge.me1_close(t TEXT,i TEXT) RETURNS VOID LANGUAGE plpgsql SET search_path=pg_catalog AS $me$
DECLARE d RECORD;b RECORD;r RECORD;m RECORD;c RECORD;x JSONB;a JSONB;v RECORD;l RECORD;total NUMERIC:=0;qty NUMERIC;disposed NUMERIC;released NUMERIC;maker TEXT;reviewer TEXT;poster TEXT;digits TEXT;quantity_text TEXT;
BEGIN
 PERFORM reconforge.me1_history(t,i);
 IF left(i,5)='ME1B-' THEN
  SELECT * INTO b FROM reconforge.manufacturing_execution_boms WHERE tenant_id=t AND id=i;
  IF b IS NULL OR NOT reconforge.irp_scope(t,b.workspace_id,b.organization_id,b.legal_entity_id)
   OR reconforge.irp_digest(b.payload) IS DISTINCT FROM b.source_digest OR b.creator_id IS DISTINCT FROM b.payload->>'creator_id'
   OR b.creator_id IS DISTINCT FROM reconforge.me1_evidence(t,i,'create',b.source_digest)
   OR jsonb_array_length(b.payload->'components') NOT BETWEEN 1 AND 100 THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='manufacturing_execution_owner',MESSAGE='BOM requires canonical scoped complete source and actual creator'; END IF;
  IF b.phase=1 AND(b.reviewer_id IS DISTINCT FROM reconforge.me1_evidence(t,i,'approve-bom',b.source_digest) OR b.reviewer_id=b.creator_id) THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='manufacturing_execution_owner',MESSAGE='BOM approval requires a distinct actual human'; END IF;
  IF(b.payload->>'output_quantity_scaled')::numeric<=0
   OR EXISTS(SELECT 1 FROM jsonb_array_elements(b.payload->'components') z GROUP BY z->>'item_id' HAVING count(*)>1)
   OR NOT EXISTS(SELECT 1 FROM reconforge.inventory_items item JOIN reconforge.inventory_units_of_measure u ON u.tenant_id=item.tenant_id AND u.id=item.uom_id
    WHERE item.tenant_id=t AND item.id=b.payload->'output'->>'item_id' AND item.item_code=b.payload->>'output_item_code'
    AND item.workspace_id=b.workspace_id AND(item.organization_id IS NULL OR item.organization_id=b.organization_id)
    AND item.item_type IN('Stock','Consumable') AND item.tracking_mode='None' AND item.uom_id=b.payload->'output'->>'uom_id'
    AND u.decimal_places=(b.payload->'output'->>'quantity_precision')::integer
    AND(b.payload->>'output_quantity')::numeric*power(10::numeric,u.decimal_places)=(b.payload->>'output_quantity_scaled')::numeric) THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='manufacturing_execution_owner',MESSAGE='BOM output must reproduce its actual native base UOM'; END IF;
  FOR x IN SELECT value FROM jsonb_array_elements(b.payload->'components') LOOP
   IF x->>'item_id'=b.payload->'output'->>'item_id' OR(x->>'quantity_scaled')::numeric<=0
    OR NOT EXISTS(SELECT 1 FROM reconforge.inventory_items item JOIN reconforge.inventory_units_of_measure u ON u.tenant_id=item.tenant_id AND u.id=item.uom_id
     WHERE item.tenant_id=t AND item.id=x->>'item_id' AND item.item_code=x->>'item_code' AND item.workspace_id=b.workspace_id
     AND(item.organization_id IS NULL OR item.organization_id=b.organization_id) AND item.item_type IN('Stock','Consumable') AND item.tracking_mode='None'
     AND item.uom_id=x->>'uom_id' AND item.inventory_account_id=x->>'inventory_account_id' AND u.decimal_places=(x->>'quantity_precision')::integer
     AND(x->>'quantity')::numeric*power(10::numeric,u.decimal_places)=(x->>'quantity_scaled')::numeric) THEN
    RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='manufacturing_execution_owner',MESSAGE='BOM material must reproduce its native item and exact base UOM'; END IF;
  END LOOP;RETURN;
 END IF;
 IF left(i,5)='ME1C-' THEN
  SELECT * INTO c FROM reconforge.manufacturing_execution_completions WHERE tenant_id=t AND id=i;
  IF c IS NULL THEN RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='manufacturing_execution_owner',MESSAGE='Completion owner is missing'; END IF;
  PERFORM reconforge.me1_close(t,c.order_id);RETURN;
 END IF;
 SELECT * INTO d FROM reconforge.manufacturing_execution_orders WHERE tenant_id=t AND id=i;
 SELECT * INTO b FROM reconforge.manufacturing_execution_boms WHERE tenant_id=t AND id=d.bom_version_id;
 SELECT * INTO m FROM reconforge.inventory_movements WHERE tenant_id=t AND id=d.movement_id;
 IF d IS NULL OR b IS NULL OR b.phase<>1 OR NOT reconforge.irp_scope(t,d.workspace_id,d.organization_id,d.legal_entity_id)
 OR reconforge.irp_digest(d.payload) IS DISTINCT FROM d.source_digest OR d.payload->>'bom_digest' IS DISTINCT FROM b.source_digest
 OR d.payload->>'bom_version_id' IS DISTINCT FROM b.id OR d.payload->>'id' IS DISTINCT FROM d.id
 OR m IS NULL OR(m.workspace_id,m.organization_id,m.legal_entity_id,m.source_reference,m.source_type,m.movement_type)
  IS DISTINCT FROM(d.workspace_id,d.organization_id,d.legal_entity_id,d.id,'Generated','Delivery')
 OR m.manufacturing_claim_state IS DISTINCT FROM(CASE d.phase WHEN 0 THEN 'Reserved' WHEN 1 THEN 'IssuePrepared' WHEN 2 THEN 'IssueReviewed' WHEN 5 THEN 'Cancelled' ELSE 'Issued' END)
 OR m.status IS DISTINCT FROM(CASE WHEN d.phase IN(3,4) THEN 'Posted' ELSE 'Draft' END)
 OR(m.movement_number,m.period_id,m.movement_date::text,m.description) IS DISTINCT FROM(d.id,d.payload->>'period_id',d.payload->>'posting_date',d.payload->>'reason')
 OR(SELECT count(*) FROM reconforge.manufacturing_execution_requirements WHERE tenant_id=t AND order_id=i)<>jsonb_array_length(d.payload->'requirements')
 OR(SELECT count(*) FROM reconforge.manufacturing_execution_reservations WHERE tenant_id=t AND order_id=i)<>jsonb_array_length(d.payload->'requirements')
 OR(SELECT count(*) FROM reconforge.inventory_movement_lines WHERE tenant_id=t AND movement_id=m.id)<>jsonb_array_length(d.payload->'requirements') THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='manufacturing_execution_owner',MESSAGE='Manufacturing native source and phase must remain complete'; END IF;
 maker:=reconforge.me1_evidence(t,i,'create',d.source_digest);
 IF maker IS DISTINCT FROM d.payload->>'creator_id' THEN RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='manufacturing_execution_owner',MESSAGE='Order retains the actual creator'; END IF;
 IF NOT EXISTS(SELECT 1 FROM reconforge.finance_accounts w JOIN reconforge.finance_accounts s ON s.tenant_id=w.tenant_id AND s.chart_id=w.chart_id
  JOIN reconforge.finance_journals j ON j.tenant_id=w.tenant_id AND j.chart_id=w.chart_id WHERE w.tenant_id=t AND w.id=d.payload->>'wip_account_id'
  AND s.id=d.payload->>'scrap_account_id' AND w.account_type='Asset' AND s.account_type='Expense' AND w.id<>s.id
  AND j.id=d.payload->>'journal_id' AND j.workspace_id=d.workspace_id AND j.organization_code=d.payload->>'organization_code'
  AND j.currency_code=d.payload->>'currency_code')
 OR NOT EXISTS(SELECT 1 FROM reconforge.inventory_valuation_policies policy WHERE policy.tenant_id=t AND policy.id=d.payload->>'finished_policy_id'
  AND(policy.workspace_id,policy.organization_id,policy.legal_entity_id,policy.receipt_clearing_account_id,policy.finance_journal_id,policy.currency_code,policy.costing_method)
   IS NOT DISTINCT FROM(d.workspace_id,d.organization_id,d.legal_entity_id,d.payload->>'wip_account_id',d.payload->>'journal_id',d.payload->>'currency_code','FIFO')) THEN
  RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='manufacturing_execution_owner',MESSAGE='Production requires exact distinct native WIP, scrap and finished receipt policy'; END IF;
 FOR x IN SELECT value FROM jsonb_array_elements(d.payload->'requirements') LOOP
  SELECT * INTO r FROM reconforge.manufacturing_execution_requirements WHERE tenant_id=t AND id=x->>'requirement_id';
  digits:=lpad(r.required_quantity_scaled::text,greatest(length(r.required_quantity_scaled::text),r.quantity_precision+1),'0');
  quantity_text:=CASE WHEN r.quantity_precision=0 THEN digits ELSE left(digits,length(digits)-r.quantity_precision)||'.'||right(digits,r.quantity_precision) END;
  IF r IS NULL OR reconforge.irp_digest(r.requirement_json) IS DISTINCT FROM r.requirement_digest
  OR(r.order_id,r.bom_version_id,r.workspace_id,r.organization_id,r.legal_entity_id,r.item_id,r.uom_id,r.required_quantity_scaled,r.quantity_precision)
   IS DISTINCT FROM(d.id,b.id,d.workspace_id,d.organization_id,d.legal_entity_id,x->>'item_id',x->>'uom_id',(x->>'required_quantity_scaled')::bigint,(x->>'quantity_precision')::integer)
  OR x->>'required_quantity' IS DISTINCT FROM quantity_text
  OR r.requirement_json IS DISTINCT FROM jsonb_build_object('schema_version','manufacturing-requirement-v1','requirement_id',r.id,
   'order_id',d.id,'bom_version_id',b.id,'order_source_digest',d.source_digest,'bom_digest',b.source_digest,
   'scope',jsonb_build_object('workspace_id',d.workspace_id,'organization_id',d.organization_id,'legal_entity_id',d.legal_entity_id),
   'item_id',r.item_id,'item_code',x->>'item_code','uom_id',r.uom_id,'uom_code',x->>'uom_code','quantity_precision',r.quantity_precision,
   'required_quantity_scaled',r.required_quantity_scaled,'required_quantity',quantity_text)
  OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(b.payload->'components') z WHERE z->>'item_id'=r.item_id AND z->>'uom_id'=r.uom_id
   AND z=x-ARRAY['requirement_id','required_quantity_scaled','required_quantity']
   AND(z->>'quantity_scaled')::numeric*(d.payload->>'output_quantity_scaled')::numeric
    =r.required_quantity_scaled::numeric*(b.payload->>'output_quantity_scaled')::numeric)
  OR NOT EXISTS(SELECT 1 FROM reconforge.inventory_movement_lines ml WHERE ml.tenant_id=t AND ml.movement_id=m.id
   AND(ml.item_id,ml.uom_id,ml.quantity_scaled,ml.quantity_precision,ml.from_location_id)
    IS NOT DISTINCT FROM(r.item_id,r.uom_id,r.required_quantity_scaled,r.quantity_precision,d.payload->>'component_location_id') AND ml.to_location_id IS NULL AND ml.inventory_lot_id IS NULL)
  OR NOT EXISTS(SELECT 1 FROM reconforge.manufacturing_execution_reservations z WHERE z.tenant_id=t AND z.requirement_id=r.id
   AND(z.order_id,z.quantity_scaled,z.location_id,z.item_id,z.state) IS NOT DISTINCT FROM(d.id,r.required_quantity_scaled,d.payload->>'component_location_id',r.item_id,
    CASE WHEN d.phase=5 THEN 'Released' WHEN d.phase IN(3,4) THEN 'Consumed' ELSE 'Active' END)) THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='manufacturing_execution_owner',MESSAGE='Every component must reproduce immutable exact BOM demand, reservation and material movement'; END IF;
  PERFORM reconforge.stock_sales_capacity(t,d.workspace_id,d.legal_entity_id,d.payload->>'component_location_id',r.item_id);
 END LOOP;
 IF(d.phase IN(1,2,3,4)) AND d.issue_plan IS NULL OR(d.issue_plan IS NOT NULL AND reconforge.irp_digest(d.issue_plan) IS DISTINCT FROM d.issue_digest) THEN
  RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='manufacturing_execution_owner',MESSAGE='Material cost requires complete immutable preparation'; END IF;
 IF d.issue_plan IS NOT NULL THEN
  maker:=reconforge.me1_evidence(t,i,'prepare',d.source_digest);
  IF maker IS DISTINCT FROM d.issue_plan->>'preparer_actor_id' OR d.issue_plan->>'source_digest' IS DISTINCT FROM d.source_digest THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='manufacturing_execution_owner',MESSAGE='Issue retains the actual material cost preparer'; END IF;
  reviewer:=CASE WHEN d.issue_reviewer_id IS NOT NULL THEN reconforge.me1_evidence(t,i,'review',d.source_digest) ELSE NULL END;
  IF(d.phase IN(2,3,4) OR d.issue_reviewer_id IS NOT NULL) AND(reviewer IS DISTINCT FROM d.issue_reviewer_id OR reviewer=maker) THEN RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='manufacturing_execution_owner',MESSAGE='Issue requires independent review'; END IF;
  PERFORM reconforge.me1_entry(t,d.issue_plan->'entry',reviewer,d.phase IN(3,4),d.phase=5);
  IF jsonb_array_length(d.issue_plan->'components')<>jsonb_array_length(d.payload->'requirements')
   OR EXISTS(SELECT 1 FROM jsonb_array_elements(d.issue_plan->'components') z GROUP BY z->>'item_id' HAVING count(*)>1)
   OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(d.issue_plan->'entry'->'snapshot'->'lines') z WHERE z->>'account_id'=d.payload->>'wip_account_id'
    AND(z->>'debit_minor')::numeric=(d.issue_plan->>'total_cost_minor')::numeric AND(z->>'credit_minor')::numeric=0)
   OR EXISTS((SELECT z->>'account_id',(z->>'credit_minor')::numeric FROM jsonb_array_elements(d.issue_plan->'entry'->'snapshot'->'lines') z WHERE(z->>'credit_minor')::numeric>0
    EXCEPT ALL SELECT z->>'inventory_account_id',sum((z->>'value_minor')::numeric) FROM jsonb_array_elements(d.issue_plan->'components') z GROUP BY z->>'inventory_account_id')
    UNION ALL(SELECT z->>'inventory_account_id',sum((z->>'value_minor')::numeric) FROM jsonb_array_elements(d.issue_plan->'components') z GROUP BY z->>'inventory_account_id'
    EXCEPT ALL SELECT z->>'account_id',(z->>'credit_minor')::numeric FROM jsonb_array_elements(d.issue_plan->'entry'->'snapshot'->'lines') z WHERE(z->>'credit_minor')::numeric>0)) THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='manufacturing_execution_owner',MESSAGE='Native WIP debit and inventory credits must equal the complete original material cost'; END IF;
  FOR x IN SELECT value FROM jsonb_array_elements(d.issue_plan->'components') LOOP
   IF NOT EXISTS(SELECT 1 FROM jsonb_array_elements(d.payload->'requirements') z WHERE (z-ARRAY['allocations','value_minor'])=(x-ARRAY['allocations','value_minor']))
    OR EXISTS(SELECT 1 FROM jsonb_array_elements(x->'allocations') z GROUP BY z->>'cost_layer_id' HAVING count(*)>1) THEN
    RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='manufacturing_execution_owner',MESSAGE='Costing must retain every original component requirement exactly once'; END IF;
   qty:=0;
   FOR a IN SELECT value FROM jsonb_array_elements(x->'allocations') LOOP
    IF(a->>'value_minor')::bigint IS DISTINCT FROM reconforge.stock_sales_fifo_value((a->>'remaining_value_minor')::bigint,(a->>'remaining_quantity_scaled')::bigint,(a->>'quantity_scaled')::bigint) THEN
     RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='manufacturing_execution_owner',MESSAGE='Component cost must reproduce original HALF_EVEN FIFO'; END IF;
    qty:=qty+(a->>'quantity_scaled')::numeric;total:=total+(a->>'value_minor')::numeric;
    SELECT * INTO l FROM reconforge.inventory_cost_layers WHERE tenant_id=t AND id=a->>'cost_layer_id';
    IF l IS NULL OR(l.workspace_id,l.legal_entity_id,l.item_id,l.uom_id,l.quantity_precision) IS DISTINCT FROM(d.workspace_id,d.legal_entity_id,x->>'item_id',x->>'uom_id',(x->>'quantity_precision')::integer)
    OR(d.phase IN(1,2) AND(l.row_version,l.remaining_quantity_scaled,l.remaining_value_minor) IS DISTINCT FROM((a->>'row_version')::bigint,(a->>'remaining_quantity_scaled')::bigint,(a->>'remaining_value_minor')::bigint))
    OR(d.phase IN(3,4) AND NOT EXISTS(SELECT 1 FROM reconforge.inventory_layer_consumptions consumption JOIN reconforge.inventory_valuation_lines detail ON detail.tenant_id=consumption.tenant_id AND detail.id=consumption.valuation_line_id
      WHERE consumption.tenant_id=t AND detail.valuation_document_id=d.valuation_id AND detail.item_id=l.item_id AND consumption.cost_layer_id=l.id
      AND consumption.quantity_scaled=(a->>'quantity_scaled')::bigint AND consumption.value_minor=(a->>'value_minor')::bigint)) THEN
     RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='manufacturing_execution_owner',MESSAGE='Frozen component FIFO ownership or issued history differs'; END IF;
   END LOOP;
   IF qty IS DISTINCT FROM(x->>'required_quantity_scaled')::numeric THEN RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='manufacturing_execution_owner',MESSAGE='Material issue must consume the whole original component tranche'; END IF;
  END LOOP;
  IF total IS DISTINCT FROM(d.issue_plan->>'total_cost_minor')::numeric THEN RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='manufacturing_execution_owner',MESSAGE='WIP cost must equal every original FIFO consumption'; END IF;
 END IF;
 IF d.phase IN(3,4) THEN
  poster:=reconforge.me1_evidence(t,i,'post',d.source_digest);
  SELECT * INTO v FROM reconforge.inventory_valuation_documents WHERE tenant_id=t AND id=d.valuation_id;
  IF poster IN(maker,reviewer) OR v IS NULL OR v.status<>'Approved' OR v.movement_id<>m.id OR v.total_value_minor<>total
   OR v.finance_entry_id IS DISTINCT FROM d.issue_plan->'entry'->>'entry_id'
   OR NOT EXISTS(SELECT 1 FROM reconforge.finance_posting_effects f WHERE f.tenant_id=t AND f.id=d.issue_effect_id AND f.entry_id=v.finance_entry_id AND f.posted_actor_id=poster)
   OR(SELECT count(*) FROM reconforge.inventory_valuation_lines WHERE tenant_id=t AND valuation_document_id=v.id)<>jsonb_array_length(d.issue_plan->'components') THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='manufacturing_execution_owner',MESSAGE='Issued material requires a third human, actual valuation and original native WIP effect'; END IF;
 END IF;
 IF d.phase=5 THEN PERFORM reconforge.me1_evidence(t,i,'cancel',d.source_digest); END IF;
 disposed:=0;released:=0;
 FOR c IN SELECT * FROM reconforge.manufacturing_execution_completions WHERE tenant_id=t AND order_id=i ORDER BY (payload->>'disposed_before_scaled')::bigint,id LOOP
  PERFORM reconforge.me1_history(t,c.id);
  IF d.phase NOT IN(3,4) OR reconforge.irp_digest(c.payload) IS DISTINCT FROM c.source_digest OR c.payload->>'order_digest' IS DISTINCT FROM d.source_digest
   OR c.payload->>'issue_digest' IS DISTINCT FROM d.issue_digest THEN RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='manufacturing_execution_owner',MESSAGE='Completion must retain its original posted component cost'; END IF;
  maker:=reconforge.me1_evidence(t,c.id,'create',c.source_digest);
  reviewer:=CASE WHEN c.reviewer_id IS NOT NULL THEN reconforge.me1_evidence(t,c.id,'review',c.source_digest) ELSE NULL END;
  IF maker IS DISTINCT FROM c.payload->>'preparer_actor_id' OR((c.phase IN(1,2) OR c.reviewer_id IS NOT NULL) AND(reviewer IS DISTINCT FROM c.reviewer_id OR maker=reviewer)) THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='manufacturing_execution_owner',MESSAGE='Completion retains independent actual source preparation and review'; END IF;
  IF c.phase<>3 THEN
   IF(c.payload->>'disposed_before_scaled')::numeric<>disposed OR(c.payload->>'released_before_minor')::numeric<>released
    OR(c.payload->>'released_cost_minor')::bigint IS DISTINCT FROM reconforge.stock_sales_fifo_value((d.issue_plan->>'total_cost_minor')::bigint-released::bigint,(d.payload->>'output_quantity_scaled')::bigint-disposed::bigint,(c.payload->>'stage_quantity_scaled')::bigint)
    OR(c.payload->>'stage_quantity_scaled')::bigint<>(c.payload->>'good_quantity_scaled')::bigint+(c.payload->>'scrap_quantity_scaled')::bigint
    OR(c.payload->>'released_cost_minor')::bigint<>(c.payload->>'good_cost_minor')::bigint+(c.payload->>'scrap_cost_minor')::bigint
    OR((c.payload->>'good_quantity_scaled')::bigint>0 AND(c.payload->>'good_cost_minor')::bigint IS DISTINCT FROM reconforge.stock_sales_fifo_value((c.payload->>'released_cost_minor')::bigint,(c.payload->>'stage_quantity_scaled')::bigint,(c.payload->>'good_quantity_scaled')::bigint)) THEN
    RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='manufacturing_execution_owner',MESSAGE='Partial output and abnormal scrap must exactly conserve retained WIP'; END IF;
  END IF;
  IF((c.payload->>'scrap_quantity_scaled')::numeric>0) IS DISTINCT FROM(c.payload->'scrap_entry'<>'null'::jsonb)
   OR((c.payload->>'good_quantity_scaled')::numeric>0) IS DISTINCT FROM(c.payload->'receipt_plan'<>'null'::jsonb) THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='manufacturing_execution_owner',MESSAGE='Every positive good or scrap quantity needs its actual native financial source'; END IF;
  poster:=CASE WHEN c.phase=2 THEN reconforge.me1_evidence(t,c.id,'post',c.source_digest) ELSE NULL END;
  IF c.phase<>2 AND(COALESCE(c.receipt_effect,'null'::jsonb)<>'null'::jsonb OR c.scrap_effect_id IS NOT NULL)
   OR(c.payload->'receipt_plan'='null'::jsonb AND COALESCE(c.receipt_effect,'null'::jsonb)<>'null'::jsonb)
   OR(c.payload->'scrap_entry'='null'::jsonb AND c.scrap_effect_id IS NOT NULL) THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='manufacturing_execution_owner',MESSAGE='Unposted or absent dispositions cannot retain financial effects'; END IF;
  IF c.payload->'scrap_entry'<>'null'::jsonb THEN
   PERFORM reconforge.me1_entry(t,c.payload->'scrap_entry',reviewer,c.phase=2,c.phase=3);
   IF jsonb_array_length(c.payload->'scrap_entry'->'snapshot'->'lines')<>2 OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(c.payload->'scrap_entry'->'snapshot'->'lines') z
    WHERE z->>'account_id'=d.payload->>'scrap_account_id' AND(z->>'debit_minor')::numeric=(c.payload->>'scrap_cost_minor')::numeric AND(z->>'credit_minor')::numeric=0)
    OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(c.payload->'scrap_entry'->'snapshot'->'lines') z
    WHERE z->>'account_id'=d.payload->>'wip_account_id' AND(z->>'credit_minor')::numeric=(c.payload->>'scrap_cost_minor')::numeric AND(z->>'debit_minor')::numeric=0) THEN
    RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='manufacturing_execution_owner',MESSAGE='Abnormal material scrap must expense the exact released WIP'; END IF;
   IF c.phase=2 AND NOT EXISTS(SELECT 1 FROM reconforge.finance_posting_effects f WHERE f.tenant_id=t AND f.id=c.scrap_effect_id
    AND f.entry_id=c.payload->'scrap_entry'->>'entry_id' AND f.posted_actor_id=poster) THEN
    RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='manufacturing_execution_owner',MESSAGE='Scrap effect identity must name the exact third-human native expense'; END IF;
  END IF;
  IF c.payload->'receipt_plan'<>'null'::jsonb THEN
   IF NOT EXISTS(SELECT 1 FROM reconforge.inventory_receipt_plans p WHERE p.tenant_id=t AND p.id=c.payload->'receipt_plan'->>'plan_id'
    AND p.plan_json IS NOT DISTINCT FROM c.payload->'receipt_plan' AND p.operation='Receipt'
    AND p.quantity_scaled=(c.payload->>'good_quantity_scaled')::bigint AND p.total_value_minor=(c.payload->>'good_cost_minor')::bigint
    AND p.item_id=d.payload->>'output_item_id' AND p.receipt_clearing_account_id=d.payload->>'wip_account_id'
    AND p.source_number=c.id AND p.period_id=c.payload->>'period_id' AND p.posting_date::text=c.payload->>'posting_date'
    AND(p.workspace_id,p.organization_id,p.legal_entity_id)=(d.workspace_id,d.organization_id,d.legal_entity_id)
    AND p.preparer_actor_id=maker
    AND(c.reviewer_id IS NULL) IS NOT DISTINCT FROM NOT EXISTS(SELECT 1 FROM reconforge.inventory_receipt_reviews review WHERE review.tenant_id=t AND review.plan_id=p.id)
    AND(c.reviewer_id IS NULL OR EXISTS(SELECT 1 FROM reconforge.inventory_receipt_reviews review WHERE review.tenant_id=t AND review.plan_id=p.id AND review.reviewer_actor_id=c.reviewer_id))
    AND(c.phase<>2 OR EXISTS(SELECT 1 FROM reconforge.inventory_receipt_commands command WHERE command.tenant_id=t AND command.plan_id=p.id
      AND command.operation='commit' AND command.actor_user_id=poster AND command.result_json=c.receipt_effect))
    AND(c.phase=2) IS NOT DISTINCT FROM EXISTS(SELECT 1 FROM reconforge.inventory_receipt_links link WHERE link.tenant_id=t AND link.plan_id=p.id)) THEN
    RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='manufacturing_execution_owner',MESSAGE='Finished goods require the exact original native receipt engine, cost and WIP offset'; END IF;
  END IF;
  IF c.phase=2 THEN
   poster:=reconforge.me1_evidence(t,c.id,'post',c.source_digest);
   IF poster IN(maker,reviewer) THEN RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='manufacturing_execution_owner',MESSAGE='Completion posting requires a third actual human'; END IF;
   disposed:=disposed+(c.payload->>'stage_quantity_scaled')::numeric;released:=released+(c.payload->>'released_cost_minor')::numeric;
  ELSIF c.phase=3 THEN PERFORM reconforge.me1_evidence(t,c.id,'cancel',c.source_digest); END IF;
 END LOOP;
 IF d.disposed_quantity_scaled<>disposed OR d.released_cost_minor<>released OR disposed>(d.payload->>'output_quantity_scaled')::numeric
 OR released>total OR(d.phase=4) IS DISTINCT FROM(disposed=(d.payload->>'output_quantity_scaled')::numeric AND released=total) THEN
  RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='manufacturing_execution_owner',MESSAGE='Production quantities, finished inventory, scrap and remaining WIP must reconcile exactly'; END IF;
END $me$;
CREATE FUNCTION reconforge.me1_native_immutable() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $me$
DECLARE relevant BOOLEAN;entry TEXT;
BEGIN
 IF TG_TABLE_NAME='inventory_movements' THEN relevant:=OLD.manufacturing_claim_state IS NOT NULL OR left(OLD.source_reference,4)='ME1-';
 ELSIF TG_TABLE_NAME='inventory_movement_lines' THEN SELECT manufacturing_claim_state IS NOT NULL INTO relevant FROM reconforge.inventory_movements WHERE tenant_id=OLD.tenant_id AND id=OLD.movement_id;
 ELSE
  IF TG_TABLE_NAME='finance_entry_lines' THEN entry:=OLD.entry_id;
  ELSE SELECT entry_id INTO entry FROM reconforge.finance_entry_lines WHERE tenant_id=OLD.tenant_id AND id=OLD.entry_line_id; END IF;
  SELECT left(entry_number,4)='ME1-' OR left(entry_number,5)='ME1C-' INTO relevant FROM reconforge.finance_entries WHERE tenant_id=OLD.tenant_id AND id=entry;
 END IF;
 IF relevant THEN RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='manufacturing_execution_owner',MESSAGE='Original native manufacturing source history is immutable'; END IF;
 RETURN CASE WHEN TG_OP='DELETE' THEN OLD ELSE NEW END;
END $me$;
"""

_INSTALL_SQL = r"""
CREATE FUNCTION reconforge.me1_deferred() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $me$
DECLARE i TEXT;ref TEXT;original_entry RECORD;d RECORD;
BEGIN
 IF TG_TABLE_NAME LIKE 'manufacturing_execution_%' THEN
  IF TG_TABLE_NAME IN('manufacturing_execution_events','manufacturing_execution_commands') THEN i:=NEW.object_id;
  ELSIF TG_TABLE_NAME IN('manufacturing_execution_requirements','manufacturing_execution_reservations') THEN i:=NEW.order_id;
  ELSE i:=NEW.id;END IF;
  PERFORM reconforge.me1_close(NEW.tenant_id,i);RETURN NEW;
 END IF;
 IF TG_TABLE_NAME='inventory_movements' THEN
  IF NEW.manufacturing_claim_state IS NULL THEN RETURN NEW; END IF;i:=NEW.source_reference;
 ELSIF TG_TABLE_NAME='inventory_movement_lines' THEN SELECT source_reference INTO i FROM reconforge.inventory_movements WHERE tenant_id=NEW.tenant_id AND id=NEW.movement_id AND manufacturing_claim_state IS NOT NULL;
 ELSIF TG_TABLE_NAME='finance_entries' THEN
  IF left(NEW.entry_number,4)<>'ME1-' AND left(NEW.entry_number,5)<>'ME1C-' AND NEW.reverses_posting_id IS NULL THEN RETURN NEW; END IF;
  IF NEW.reverses_posting_id IS NOT NULL THEN
   SELECT entry.* INTO original_entry FROM reconforge.finance_posting_effects effect JOIN reconforge.finance_entries entry ON entry.tenant_id=effect.tenant_id AND entry.id=effect.entry_id WHERE effect.tenant_id=NEW.tenant_id AND effect.id=NEW.reverses_posting_id;
   IF left(original_entry.entry_number,4)='ME1-' OR left(original_entry.entry_number,5)='ME1C-' THEN RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='manufacturing_execution_owner',MESSAGE='Source-owned material WIP and scrap cannot be independently reversed'; END IF;
  END IF;i:=NEW.external_reference;
 ELSIF TG_TABLE_NAME='finance_entry_lines' THEN SELECT external_reference INTO i FROM reconforge.finance_entries WHERE tenant_id=NEW.tenant_id AND id=NEW.entry_id AND(left(entry_number,4)='ME1-' OR left(entry_number,5)='ME1C-');
 ELSIF TG_TABLE_NAME='finance_posting_effects' THEN SELECT external_reference INTO i FROM reconforge.finance_entries WHERE tenant_id=NEW.tenant_id AND id=NEW.entry_id AND(left(entry_number,4)='ME1-' OR left(entry_number,5)='ME1C-');
 ELSIF TG_TABLE_NAME IN('inventory_receipt_plans','inventory_receipt_reviews','inventory_receipt_commands','inventory_receipt_links') THEN
  IF TG_TABLE_NAME='inventory_receipt_plans' THEN ref:=NEW.id;ELSE ref:=NEW.plan_id;END IF;
  IF NOT EXISTS(SELECT 1 FROM reconforge.inventory_receipt_plans p WHERE p.tenant_id=NEW.tenant_id AND p.id=ref AND left(p.source_number,5)='ME1C-') THEN RETURN NEW; END IF;
  SELECT id INTO i FROM reconforge.manufacturing_execution_completions WHERE tenant_id=NEW.tenant_id AND payload->'receipt_plan'->>'plan_id'=ref;
  IF i IS NULL THEN RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='manufacturing_execution_owner',MESSAGE='Reserved finished receipt requires its exact manufacturing completion'; END IF;
 ELSE RETURN NEW;
 END IF;
 IF i IS NOT NULL AND(left(i,4)='ME1-' OR left(i,5)='ME1C-') THEN PERFORM reconforge.me1_close(NEW.tenant_id,i); END IF;
 RETURN NEW;
END $me$;
DO $me$ DECLARE n TEXT; BEGIN
 FOREACH n IN ARRAY ARRAY['manufacturing_execution_boms','manufacturing_execution_orders','manufacturing_execution_requirements','manufacturing_execution_reservations','manufacturing_execution_completions','manufacturing_execution_events','manufacturing_execution_commands'] LOOP
  EXECUTE format('ALTER TABLE reconforge.%I ENABLE ROW LEVEL SECURITY',n);EXECUTE format('ALTER TABLE reconforge.%I FORCE ROW LEVEL SECURITY',n);
  IF n IN('manufacturing_execution_events','manufacturing_execution_commands') THEN
   EXECUTE format('CREATE POLICY manufacturing_scope ON reconforge.%I USING(reconforge.me1_visible(tenant_id,object_id)) WITH CHECK(reconforge.me1_visible(tenant_id,object_id))',n);
  ELSE EXECUTE format('CREATE POLICY manufacturing_scope ON reconforge.%I USING(reconforge.irp_scope(tenant_id,workspace_id,organization_id,legal_entity_id)) WITH CHECK(reconforge.irp_scope(tenant_id,workspace_id,organization_id,legal_entity_id))',n); END IF;
  EXECUTE format('CREATE TRIGGER manufacturing_protect BEFORE INSERT OR UPDATE OR DELETE ON reconforge.%I FOR EACH ROW EXECUTE FUNCTION reconforge.me1_protect()',n);
  EXECUTE format('CREATE CONSTRAINT TRIGGER manufacturing_close AFTER INSERT OR UPDATE ON reconforge.%I DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION reconforge.me1_deferred()',n);
 END LOOP;
 FOREACH n IN ARRAY ARRAY['inventory_movements','inventory_movement_lines','inventory_cost_layers','inventory_layer_consumptions'] LOOP
  EXECUTE format('CREATE TRIGGER aa_manufacturing_native_guard BEFORE INSERT OR UPDATE ON reconforge.%I FOR EACH ROW EXECUTE FUNCTION reconforge.me1_native_guard()',n);
 END LOOP;
 FOREACH n IN ARRAY ARRAY['inventory_movements','inventory_movement_lines'] LOOP EXECUTE format('CREATE TRIGGER manufacturing_native_immutable BEFORE DELETE ON reconforge.%I FOR EACH ROW EXECUTE FUNCTION reconforge.me1_native_immutable()',n);END LOOP;
 FOREACH n IN ARRAY ARRAY['finance_entry_lines','finance_entry_line_dimensions'] LOOP EXECUTE format('CREATE TRIGGER manufacturing_native_immutable BEFORE UPDATE OR DELETE ON reconforge.%I FOR EACH ROW EXECUTE FUNCTION reconforge.me1_native_immutable()',n);END LOOP;
 FOREACH n IN ARRAY ARRAY['inventory_movements','inventory_movement_lines','finance_entries','finance_entry_lines','finance_posting_effects','inventory_receipt_plans','inventory_receipt_reviews','inventory_receipt_commands','inventory_receipt_links'] LOOP
  EXECUTE format('CREATE CONSTRAINT TRIGGER manufacturing_native_close AFTER INSERT OR UPDATE ON reconforge.%I DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION reconforge.me1_deferred()',n);
 END LOOP;
END $me$;
"""

UPGRADE_SQL = _TABLES_SQL + _PROTECTION_SQL + _CAPACITY_SQL + _CLOSURE_SQL + _INSTALL_SQL

DOWNGRADE_SQL = r"""
DO $me$ BEGIN
 IF EXISTS(SELECT 1 FROM reconforge.manufacturing_execution_boms) OR EXISTS(SELECT 1 FROM reconforge.manufacturing_execution_orders)
 OR EXISTS(SELECT 1 FROM reconforge.manufacturing_execution_commands) THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Populated manufacturing evidence must be retained; rollback is refused'; END IF;
END $me$;
DO $me$ DECLARE n TEXT; BEGIN
 FOREACH n IN ARRAY ARRAY['inventory_movements','inventory_movement_lines','finance_entry_lines','finance_entry_line_dimensions'] LOOP EXECUTE format('DROP TRIGGER manufacturing_native_immutable ON reconforge.%I',n);END LOOP;
 FOREACH n IN ARRAY ARRAY['inventory_movements','inventory_movement_lines','inventory_cost_layers','inventory_layer_consumptions'] LOOP EXECUTE format('DROP TRIGGER aa_manufacturing_native_guard ON reconforge.%I',n);END LOOP;
 FOREACH n IN ARRAY ARRAY['inventory_movements','inventory_movement_lines','finance_entries','finance_entry_lines','finance_posting_effects','inventory_receipt_plans','inventory_receipt_reviews','inventory_receipt_commands','inventory_receipt_links'] LOOP EXECUTE format('DROP TRIGGER manufacturing_native_close ON reconforge.%I',n);END LOOP;
END $me$;
DROP TABLE reconforge.manufacturing_execution_commands;
DROP TABLE reconforge.manufacturing_execution_events;
DROP TABLE reconforge.manufacturing_execution_completions;
DROP TABLE reconforge.manufacturing_execution_reservations;
DROP TABLE reconforge.manufacturing_execution_requirements;
DROP TABLE reconforge.manufacturing_execution_orders;
DROP TABLE reconforge.manufacturing_execution_boms;
DROP FUNCTION reconforge.me1_deferred();DROP FUNCTION reconforge.me1_close(TEXT,TEXT);DROP FUNCTION reconforge.me1_entry(TEXT,JSONB,TEXT,BOOLEAN,BOOLEAN);
DROP FUNCTION reconforge.me1_native_guard();DROP FUNCTION reconforge.me1_native_immutable();DROP FUNCTION reconforge.me1_history(TEXT,TEXT);DROP FUNCTION reconforge.me1_evidence(TEXT,TEXT,TEXT,TEXT);DROP FUNCTION reconforge.me1_ack(TEXT,TEXT,TEXT);DROP FUNCTION reconforge.me1_protect();DROP FUNCTION reconforge.me1_permission(TEXT);DROP FUNCTION reconforge.me1_visible(TEXT,TEXT);
DROP FUNCTION reconforge.stock_sales_capacity(TEXT,TEXT,TEXT,TEXT,TEXT);
ALTER FUNCTION reconforge.stock_sales_capacity_pre_me1(TEXT,TEXT,TEXT,TEXT,TEXT) RENAME TO stock_sales_capacity;
ALTER TABLE reconforge.inventory_movements DROP COLUMN manufacturing_claim_state;
"""


def install_postgres_manufacturing_execution_schema(connection: Any) -> None:
    row = connection.execute("SELECT to_regclass('reconforge.manufacturing_execution_orders') installed").fetchone()
    installed = row["installed"] if isinstance(row, Mapping) else row[0]
    if installed is not None:
        # A fixture also runs after the real migration chain. Never reinstall its
        # wrapper or silently accept an interrupted/older partial owner catalog.
        row = connection.execute("""SELECT
            to_regclass('reconforge.manufacturing_execution_boms') IS NOT NULL
            AND to_regclass('reconforge.manufacturing_execution_requirements') IS NOT NULL
            AND to_regclass('reconforge.manufacturing_execution_reservations') IS NOT NULL
            AND to_regclass('reconforge.manufacturing_execution_completions') IS NOT NULL
            AND to_regclass('reconforge.manufacturing_execution_events') IS NOT NULL
            AND to_regclass('reconforge.manufacturing_execution_commands') IS NOT NULL
            AND to_regprocedure('reconforge.me1_history(text,text)') IS NOT NULL
            AND to_regprocedure('reconforge.me1_entry(text,jsonb,text,boolean,boolean)') IS NOT NULL
            AND to_regprocedure('reconforge.stock_sales_capacity_pre_me1(text,text,text,text,text)') IS NOT NULL
            AND EXISTS(SELECT 1 FROM pg_catalog.pg_attribute WHERE attrelid='reconforge.inventory_movements'::regclass
                AND attname='manufacturing_claim_state' AND NOT attisdropped) complete""").fetchone()
        complete = row["complete"] if isinstance(row, Mapping) else row[0]
        if complete is not True:
            raise RuntimeError("Existing manufacturing schema is incomplete; apply its exact ordered migration.")
        return
    connection.execute(UPGRADE_SQL)
