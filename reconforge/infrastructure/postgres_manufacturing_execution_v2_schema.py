"""ME2 additive source closure. ME1 remains the original material/FIFO owner."""
from collections.abc import Mapping
from typing import Any

from reconforge.infrastructure.postgres_financial_source_ownership import (
    DOWNGRADE_SQL as OWNERSHIP_DOWNGRADE_SQL,
)
from reconforge.infrastructure.postgres_financial_source_ownership import (
    UPGRADE_SQL as OWNERSHIP_UPGRADE_SQL,
)

_TABLES_SQL = r"""
ALTER TABLE reconforge.manufacturing_execution_orders ADD COLUMN execution_owner_id TEXT;
CREATE TABLE reconforge.manufacturing_execution_v2_definitions(
 tenant_id TEXT NOT NULL,id TEXT NOT NULL,kind TEXT NOT NULL CHECK(kind IN('Workcenter','Routing')),
 workspace_id TEXT NOT NULL,organization_id TEXT NOT NULL,legal_entity_id TEXT NOT NULL,number TEXT NOT NULL,
 version BIGINT NOT NULL CHECK(version>0),payload JSONB NOT NULL,source_digest TEXT NOT NULL CHECK(source_digest~'^[0-9a-f]{64}$'),
 phase INTEGER NOT NULL DEFAULT 0 CHECK(phase IN(0,1)),creator_id TEXT NOT NULL,reviewer_id TEXT,
 PRIMARY KEY(tenant_id,id),UNIQUE(tenant_id,workspace_id,legal_entity_id,kind,number,version),
 CHECK((kind='Workcenter' AND left(id,5)='ME2W-') OR(kind='Routing' AND left(id,5)='ME2R-')),
 FOREIGN KEY(tenant_id,creator_id) REFERENCES reconforge.identity_users(tenant_id,id),
 FOREIGN KEY(tenant_id,reviewer_id) REFERENCES reconforge.identity_users(tenant_id,id)
);
CREATE TABLE reconforge.manufacturing_execution_v2_orders(
 tenant_id TEXT NOT NULL,id TEXT NOT NULL,workspace_id TEXT NOT NULL,organization_id TEXT NOT NULL,legal_entity_id TEXT NOT NULL,
 material_order_id TEXT NOT NULL,routing_id TEXT NOT NULL,payload JSONB NOT NULL,source_digest TEXT NOT NULL CHECK(source_digest~'^[0-9a-f]{64}$'),
 phase INTEGER NOT NULL DEFAULT 0 CHECK(phase BETWEEN 0 AND 5),cost_entry JSONB,total_cost_minor BIGINT NOT NULL DEFAULT 0 CHECK(total_cost_minor>=0),
 reviewer_id TEXT,cost_effect_id TEXT,produced_quantity_scaled BIGINT NOT NULL DEFAULT 0 CHECK(produced_quantity_scaled>=0),
 produced_cost_minor BIGINT NOT NULL DEFAULT 0 CHECK(produced_cost_minor>=0),disposed_quantity_scaled BIGINT NOT NULL DEFAULT 0 CHECK(disposed_quantity_scaled>=0),
 released_cost_minor BIGINT NOT NULL DEFAULT 0 CHECK(released_cost_minor>=0),PRIMARY KEY(tenant_id,id),UNIQUE(tenant_id,material_order_id),CHECK(left(id,4)='ME2-'),
 FOREIGN KEY(tenant_id,material_order_id) REFERENCES reconforge.manufacturing_execution_orders(tenant_id,id),
 FOREIGN KEY(tenant_id,routing_id) REFERENCES reconforge.manufacturing_execution_v2_definitions(tenant_id,id),
 FOREIGN KEY(tenant_id,cost_effect_id) REFERENCES reconforge.finance_posting_effects(tenant_id,id) DEFERRABLE INITIALLY DEFERRED
);
ALTER TABLE reconforge.manufacturing_execution_orders ADD CONSTRAINT manufacturing_v2_owner_fk
 FOREIGN KEY(tenant_id,execution_owner_id) REFERENCES reconforge.manufacturing_execution_v2_orders(tenant_id,id) DEFERRABLE INITIALLY DEFERRED;
CREATE TABLE reconforge.manufacturing_execution_v2_cost_claims(
 tenant_id TEXT NOT NULL,id TEXT NOT NULL,order_id TEXT NOT NULL,workspace_id TEXT NOT NULL,organization_id TEXT NOT NULL,legal_entity_id TEXT NOT NULL,
 effect_id TEXT NOT NULL,line_id TEXT NOT NULL,amount_minor BIGINT NOT NULL CHECK(amount_minor>0),payload JSONB NOT NULL,
 state TEXT NOT NULL DEFAULT'Reserved' CHECK(state IN('Reserved','Consumed','Released')),PRIMARY KEY(tenant_id,id),UNIQUE(tenant_id,order_id,effect_id,line_id),
 FOREIGN KEY(tenant_id,order_id) REFERENCES reconforge.manufacturing_execution_v2_orders(tenant_id,id),
 FOREIGN KEY(tenant_id,effect_id) REFERENCES reconforge.finance_posting_effects(tenant_id,id),
 FOREIGN KEY(tenant_id,line_id) REFERENCES reconforge.finance_entry_lines(tenant_id,id)
);
CREATE INDEX manufacturing_v2_expense_capacity ON reconforge.manufacturing_execution_v2_cost_claims(tenant_id,effect_id,line_id) WHERE state<>'Released';
CREATE TABLE reconforge.manufacturing_execution_v2_cost_releases(
 tenant_id TEXT NOT NULL,id TEXT NOT NULL,order_id TEXT NOT NULL,claim_id TEXT NOT NULL,workspace_id TEXT NOT NULL,organization_id TEXT NOT NULL,legal_entity_id TEXT NOT NULL,
 actor_id TEXT NOT NULL,reason TEXT NOT NULL,PRIMARY KEY(tenant_id,id),UNIQUE(tenant_id,claim_id),
 FOREIGN KEY(tenant_id,claim_id) REFERENCES reconforge.manufacturing_execution_v2_cost_claims(tenant_id,id),
 FOREIGN KEY(tenant_id,order_id) REFERENCES reconforge.manufacturing_execution_v2_orders(tenant_id,id)
);
CREATE TABLE reconforge.manufacturing_execution_v2_productions(
 tenant_id TEXT NOT NULL,id TEXT NOT NULL,order_id TEXT NOT NULL,workspace_id TEXT NOT NULL,organization_id TEXT NOT NULL,legal_entity_id TEXT NOT NULL,
 payload JSONB NOT NULL,source_digest TEXT NOT NULL CHECK(source_digest~'^[0-9a-f]{64}$'),phase INTEGER NOT NULL DEFAULT 0 CHECK(phase BETWEEN 0 AND 4),reviewer_id TEXT,
 PRIMARY KEY(tenant_id,id),CHECK(left(id,5)='ME2P-'),FOREIGN KEY(tenant_id,order_id) REFERENCES reconforge.manufacturing_execution_v2_orders(tenant_id,id)
);
CREATE UNIQUE INDEX manufacturing_v2_pending_hold ON reconforge.manufacturing_execution_v2_productions(tenant_id,order_id) WHERE phase IN(0,1,2);
CREATE TABLE reconforge.manufacturing_execution_v2_inspections(
 tenant_id TEXT NOT NULL,id TEXT NOT NULL,order_id TEXT NOT NULL,production_id TEXT NOT NULL,workspace_id TEXT NOT NULL,organization_id TEXT NOT NULL,legal_entity_id TEXT NOT NULL,
 payload JSONB NOT NULL,source_digest TEXT NOT NULL CHECK(source_digest~'^[0-9a-f]{64}$'),phase INTEGER NOT NULL DEFAULT 0 CHECK(phase BETWEEN 0 AND 3),
 reviewer_id TEXT,receipt_effect JSONB,loss_effect_id TEXT,PRIMARY KEY(tenant_id,id),CHECK(left(id,5)='ME2C-'),
 FOREIGN KEY(tenant_id,order_id) REFERENCES reconforge.manufacturing_execution_v2_orders(tenant_id,id),
 FOREIGN KEY(tenant_id,production_id) REFERENCES reconforge.manufacturing_execution_v2_productions(tenant_id,id),
 FOREIGN KEY(tenant_id,loss_effect_id) REFERENCES reconforge.finance_posting_effects(tenant_id,id) DEFERRABLE INITIALLY DEFERRED
);
CREATE UNIQUE INDEX manufacturing_v2_once_inspected ON reconforge.manufacturing_execution_v2_inspections(tenant_id,production_id) WHERE phase IN(0,1,2);
CREATE TABLE reconforge.manufacturing_execution_v2_events(
 tenant_id TEXT NOT NULL,object_id TEXT NOT NULL,operation TEXT NOT NULL,actor_id TEXT NOT NULL,reason TEXT NOT NULL,
 audit_event_id TEXT NOT NULL,outbox_event_id TEXT NOT NULL,metadata JSONB NOT NULL,PRIMARY KEY(tenant_id,object_id,operation),
 FOREIGN KEY(tenant_id,audit_event_id) REFERENCES reconforge.domain_audit_events(tenant_id,id),
 FOREIGN KEY(tenant_id,outbox_event_id) REFERENCES reconforge.outbox_events(tenant_id,event_id)
);
CREATE TABLE reconforge.manufacturing_execution_v2_commands(
 tenant_id TEXT NOT NULL,workspace_id TEXT NOT NULL,object_id TEXT NOT NULL,operation TEXT NOT NULL,command_id TEXT NOT NULL,actor_id TEXT NOT NULL,
 request_json JSONB NOT NULL,request_digest TEXT NOT NULL CHECK(request_digest~'^[0-9a-f]{64}$'),response_json JSONB NOT NULL,
 PRIMARY KEY(tenant_id,workspace_id,command_id),UNIQUE(tenant_id,object_id,operation),
 FOREIGN KEY(tenant_id,object_id,operation) REFERENCES reconforge.manufacturing_execution_v2_events(tenant_id,object_id,operation) DEFERRABLE INITIALLY DEFERRED
);
"""

_AUTHORITY_SQL = r"""
CREATE FUNCTION reconforge.me2_assert(valid BOOLEAN,message TEXT) RETURNS VOID LANGUAGE plpgsql SET search_path=pg_catalog AS $me$
BEGIN IF valid IS DISTINCT FROM TRUE THEN RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='manufacturing_execution_v2_owner',MESSAGE=message;END IF;END $me$;
CREATE FUNCTION reconforge.me2_object(t TEXT,i TEXT) RETURNS JSONB LANGUAGE plpgsql STABLE SET search_path=pg_catalog AS $me$
DECLARE d RECORD;
BEGIN
 IF left(i,5) IN('ME2W-','ME2R-') THEN SELECT * INTO d FROM reconforge.manufacturing_execution_v2_definitions WHERE tenant_id=t AND id=i;
 ELSIF left(i,5)='ME2P-' THEN SELECT * INTO d FROM reconforge.manufacturing_execution_v2_productions WHERE tenant_id=t AND id=i;
 ELSIF left(i,5)='ME2C-' THEN SELECT * INTO d FROM reconforge.manufacturing_execution_v2_inspections WHERE tenant_id=t AND id=i;
 ELSE SELECT * INTO d FROM reconforge.manufacturing_execution_v2_orders WHERE tenant_id=t AND id=i;END IF;
 RETURN d.payload||(to_jsonb(d)-ARRAY['tenant_id','payload','created_at']);
END $me$;
CREATE FUNCTION reconforge.me2_visible(t TEXT,i TEXT) RETURNS BOOLEAN LANGUAGE plpgsql STABLE SET search_path=pg_catalog AS $me$
DECLARE d JSONB:=reconforge.me2_object(t,i);
BEGIN RETURN d IS NOT NULL AND reconforge.irp_scope(t,d->>'workspace_id',d->>'organization_id',d->>'legal_entity_id');END $me$;
CREATE FUNCTION reconforge.me2_permission(op TEXT) RETURNS TEXT LANGUAGE sql IMMUTABLE SET search_path=pg_catalog AS $me$
 SELECT 'manufacturing_execution_v2.'||CASE WHEN op IN('approve','review','cancel') THEN 'approve' WHEN op='post' THEN 'post' ELSE 'manage' END $me$;
CREATE FUNCTION reconforge.me2_integer(v JSONB) RETURNS BOOLEAN LANGUAGE sql IMMUTABLE SET search_path=pg_catalog AS $me$
 SELECT jsonb_typeof(v)='number' AND v::text~'^(0|[1-9][0-9]*)$'
 AND CASE WHEN v::text~'^(0|[1-9][0-9]*)$' THEN(v::text)::numeric<=9000000000000000000 ELSE FALSE END $me$;
CREATE FUNCTION reconforge.me2_policy(entry JSONB,source JSONB) RETURNS BOOLEAN LANGUAGE sql IMMUTABLE SET search_path=pg_catalog AS $me$
 SELECT entry->>'currency_code'=source->>'currency_code'
 AND entry->'currency_precision'=source->'monetary_policy'->'precision'
 AND entry->'currency_rounding_policy'=source->'monetary_policy'->'rounding_policy'
 AND entry->'currency_registry_version'=source->'monetary_policy'->'registry_version'
 AND entry->'currency_registry_digest'=source->'monetary_policy'->'registry_digest' $me$;
CREATE FUNCTION reconforge.me2_claim_value(minutes BIGINT,rate BIGINT) RETURNS NUMERIC LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog AS $me$
DECLARE value NUMERIC:=minutes::numeric*rate::numeric;whole NUMERIC;residual NUMERIC;
BEGIN
 whole:=floor(value/60);residual:=mod(value,60);
 RETURN whole+CASE WHEN residual*2>60 OR(residual*2=60 AND mod(whole,2)=1) THEN 1 ELSE 0 END;
END $me$;
CREATE FUNCTION reconforge.me2_protect() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $me$
DECLARE a TEXT:=current_setting('app.manufacturing_execution_v2_actor_id',true);d JSONB;op TEXT;p TEXT;allowed TEXT[];g RECORD;period TEXT;day TEXT;
BEGIN
 IF TG_OP='DELETE' THEN PERFORM reconforge.me2_assert(FALSE,'Manufacturing v2 source and evidence history is immutable');END IF;
 IF TG_TABLE_NAME IN('manufacturing_execution_v2_events','manufacturing_execution_v2_commands') THEN d:=reconforge.me2_object(NEW.tenant_id,NEW.object_id);op:=NEW.operation;
 ELSE d:=to_jsonb(NEW);
 IF TG_TABLE_NAME='manufacturing_execution_v2_cost_claims' THEN op:=CASE NEW.state WHEN'Reserved' THEN'create' WHEN'Consumed' THEN'post' ELSE'cancel' END;
 ELSIF TG_TABLE_NAME='manufacturing_execution_v2_cost_releases' THEN op:='cancel';
 ELSE op:=CASE WHEN NEW.phase=0 THEN'create' WHEN NEW.phase=1 THEN CASE WHEN TG_TABLE_NAME='manufacturing_execution_v2_definitions' THEN'approve' WHEN TG_TABLE_NAME='manufacturing_execution_v2_orders' THEN'prepare' ELSE'review' END
  WHEN TG_TABLE_NAME='manufacturing_execution_v2_orders' AND NEW.phase=2 THEN'review'
  WHEN NEW.phase IN(4,5) OR(TG_TABLE_NAME='manufacturing_execution_v2_inspections' AND NEW.phase=3) THEN'cancel' ELSE'post' END;END IF;END IF;
 p:=reconforge.me2_permission(op);
 PERFORM reconforge.me2_assert(reconforge.sales_revenue_actor(NEW.tenant_id,a,p),'ME2 needs current persisted human role permission');
 PERFORM 1 FROM reconforge.principal_scope_grants WHERE tenant_id=NEW.tenant_id AND principal_type='user' AND principal_id=a AND revoked_at IS NULL
  AND((scope_type='workspace' AND scope_id=d->>'workspace_id') OR(scope_type='organization' AND scope_id=d->>'organization_id') OR(scope_type='legal_entity' AND scope_id=d->>'legal_entity_id')) FOR SHARE;
 PERFORM reconforge.me2_assert((SELECT count(DISTINCT(scope_type,scope_id))=3 FROM reconforge.principal_scope_grants
  WHERE tenant_id=NEW.tenant_id AND principal_type='user' AND principal_id=a AND revoked_at IS NULL
  AND((scope_type='workspace' AND scope_id=d->>'workspace_id') OR(scope_type='organization' AND scope_id=d->>'organization_id') OR(scope_type='legal_entity' AND scope_id=d->>'legal_entity_id'))),'ME2 needs all current persisted parent scopes');
 IF TG_TABLE_NAME IN('manufacturing_execution_v2_cost_claims','manufacturing_execution_v2_cost_releases') THEN d:=reconforge.me2_object(NEW.tenant_id,NEW.order_id);END IF;
 period:=COALESCE(d->>'period_id',d->'payload'->>'period_id');day:=COALESCE(d->>'posting_date',d->'payload'->>'posting_date');
 IF period IS NOT NULL THEN
  PERFORM 1 FROM reconforge.fiscal_periods WHERE tenant_id=NEW.tenant_id AND id=period FOR SHARE;
  PERFORM reconforge.me2_assert(EXISTS(SELECT 1 FROM reconforge.fiscal_periods WHERE tenant_id=NEW.tenant_id AND id=period
   AND application_workspace_id=d->>'workspace_id' AND status='Open' AND day::date BETWEEN start_date AND end_date),
   'Every new manufacturing command requires its current scoped open period and valid business date');
 END IF;
 IF TG_OP='INSERT' THEN
  IF TG_TABLE_NAME IN('manufacturing_execution_v2_events','manufacturing_execution_v2_commands') THEN PERFORM reconforge.me2_assert(NEW.actor_id=a,'Evidence retains actual current human');
  ELSIF TG_TABLE_NAME='manufacturing_execution_v2_cost_releases' THEN PERFORM reconforge.me2_assert(NEW.actor_id=a,'Release retains current cancellation actor');
  ELSIF TG_TABLE_NAME<>'manufacturing_execution_v2_cost_claims' THEN PERFORM reconforge.me2_assert(NEW.phase=0,'ME2 sources are born unposted');END IF;RETURN NEW;
 END IF;
 IF TG_TABLE_NAME='manufacturing_execution_v2_definitions' THEN allowed:=ARRAY['phase','reviewer_id'];PERFORM reconforge.me2_assert(OLD.phase=0 AND NEW.phase=1 AND NEW.reviewer_id=a AND a<>OLD.creator_id,'Independent effective revision approval required');
 ELSIF TG_TABLE_NAME='manufacturing_execution_v2_orders' THEN allowed:=ARRAY['phase','cost_entry','total_cost_minor','reviewer_id','cost_effect_id','produced_quantity_scaled','produced_cost_minor','disposed_quantity_scaled','released_cost_minor'];
  PERFORM reconforge.me2_assert((OLD.phase=0 AND NEW.phase IN(1,5)) OR(OLD.phase=1 AND NEW.phase IN(2,5)) OR(OLD.phase=2 AND NEW.phase IN(3,5)) OR(OLD.phase=3 AND NEW.phase IN(3,4)),'ME2 complete order phases cannot regress');
  PERFORM reconforge.me2_assert(OLD.cost_entry IS NULL OR NEW.cost_entry IS NOT DISTINCT FROM OLD.cost_entry,'Frozen cost allocation is immutable');
  PERFORM reconforge.me2_assert(OLD.total_cost_minor=0 OR NEW.total_cost_minor=OLD.total_cost_minor,'Approved production cost pool is immutable');
 ELSIF TG_TABLE_NAME='manufacturing_execution_v2_productions' THEN allowed:=ARRAY['phase','reviewer_id'];
  PERFORM reconforge.me2_assert((OLD.phase=0 AND NEW.phase IN(1,4)) OR(OLD.phase=1 AND NEW.phase IN(2,4)) OR(OLD.phase=2 AND NEW.phase=3),'Production quality holds cannot regress or disappear');
 ELSIF TG_TABLE_NAME='manufacturing_execution_v2_inspections' THEN allowed:=ARRAY['phase','reviewer_id','receipt_effect','loss_effect_id'];
  PERFORM reconforge.me2_assert((OLD.phase=0 AND NEW.phase IN(1,3)) OR(OLD.phase=1 AND NEW.phase IN(2,3)),'Inspection disposition is terminal and cannot repeat');
 ELSIF TG_TABLE_NAME='manufacturing_execution_v2_cost_claims' THEN allowed:=ARRAY['state'];PERFORM reconforge.me2_assert(OLD.state='Reserved' AND NEW.state IN('Consumed','Released'),'Original expense claims cannot be reallocated after consumption');
 ELSE PERFORM reconforge.me2_assert(FALSE,'ME2 command and event history is immutable');END IF;
 PERFORM reconforge.me2_assert((to_jsonb(NEW)-allowed) IS NOT DISTINCT FROM(to_jsonb(OLD)-allowed),'ME2 immutable source or native custody changed');RETURN NEW;
END $me$;
CREATE FUNCTION reconforge.me2_ack(t TEXT,i TEXT,op TEXT) RETURNS JSONB LANGUAGE plpgsql STABLE SET search_path=pg_catalog AS $me$
DECLARE d JSONB:=reconforge.me2_object(t,i);phase INTEGER;
BEGIN
 IF left(i,5) IN('ME2W-','ME2R-') THEN phase:=CASE op WHEN'create' THEN 0 WHEN'approve' THEN 1 END;
 ELSIF left(i,5)='ME2P-' THEN phase:=CASE op WHEN'create' THEN 0 WHEN'review' THEN 1 WHEN'post' THEN 2 WHEN'cancel' THEN 4 END;
 ELSIF left(i,5)='ME2C-' THEN phase:=CASE op WHEN'create' THEN 0 WHEN'review' THEN 1 WHEN'post' THEN 2 WHEN'cancel' THEN 3 END;
 ELSE phase:=CASE op WHEN'create' THEN 0 WHEN'prepare' THEN 1 WHEN'review' THEN 2 WHEN'post' THEN 3 WHEN'cancel' THEN 5 END;
  d:=d||jsonb_build_object('produced_quantity_scaled',0,'produced_cost_minor',0,'disposed_quantity_scaled',0,'released_cost_minor',0);
  IF op='create' THEN d:=d||jsonb_build_object('cost_entry',NULL,'total_cost_minor',0);END IF;
  IF op<>'post' THEN d:=d||jsonb_build_object('cost_effect_id',NULL);END IF;
 END IF;
 PERFORM reconforge.me2_assert(phase IS NOT NULL AND d IS NOT NULL,'Historical ME2 ACK needs exact owner operation');
 IF op IN('create','prepare') THEN d:=d||jsonb_build_object('reviewer_id',NULL);END IF;
 IF left(i,5)='ME2C-' AND op<>'post' THEN d:=d||jsonb_build_object('receipt_effect',NULL,'loss_effect_id',NULL);END IF;
 RETURN d||jsonb_build_object('phase',phase);
END $me$;
CREATE FUNCTION reconforge.me2_evidence(t TEXT,i TEXT,op TEXT) RETURNS TEXT LANGUAGE plpgsql SET search_path=pg_catalog AS $me$
DECLARE d JSONB:=reconforge.me2_object(t,i);e RECORD;c RECORD;q JSONB;expected_phase INTEGER;
BEGIN
 SELECT * INTO e FROM reconforge.manufacturing_execution_v2_events WHERE tenant_id=t AND object_id=i AND operation=op;
 SELECT * INTO c FROM reconforge.manufacturing_execution_v2_commands WHERE tenant_id=t AND object_id=i AND operation=op;
 q:=CASE WHEN op='create' THEN d->'command_request' ELSE jsonb_build_object('id',i,'expected_digest',d->>'source_digest','reason',e.reason) END;
 expected_phase:=(reconforge.me2_ack(t,i,op)->>'phase')::integer;
 PERFORM reconforge.me2_assert(e.object_id IS NOT NULL AND c.object_id IS NOT NULL AND c.actor_id=e.actor_id AND c.workspace_id=d->>'workspace_id'
  AND c.request_json=jsonb_build_object('operation',op,'actor_id',e.actor_id,'request',q)
  AND reconforge.irp_digest(c.request_json)=c.request_digest AND c.response_json=reconforge.me2_ack(t,i,op)
  AND e.metadata=jsonb_build_object('source_digest',d->>'source_digest','phase',expected_phase,'reason',e.reason)
  AND EXISTS(SELECT 1 FROM reconforge.domain_audit_events a JOIN reconforge.outbox_events o ON o.tenant_id=a.tenant_id
   WHERE a.tenant_id=t AND a.id=e.audit_event_id AND a.actor_user_id=e.actor_id AND a.object_type='manufacturing_execution_v2'
   AND a.object_id=i AND a.action='manufacturing_execution_v2.'||op AND a.metadata_json=e.metadata AND o.event_id=e.outbox_event_id
   AND o.aggregate_type='manufacturing_execution_v2' AND o.aggregate_id=i AND o.event_type=a.action
   AND(o.workspace_id,o.organization_id,o.legal_entity_id)=(d->>'workspace_id',d->>'organization_id',d->>'legal_entity_id')
   AND o.payload=e.metadata||jsonb_build_object('audit_event_id',a.id)),'Every ME2 transition needs exact request, full historical ACK, audit and scoped outbox');RETURN e.actor_id;
END $me$;
CREATE FUNCTION reconforge.me2_history(t TEXT,i TEXT) RETURNS VOID LANGUAGE plpgsql SET search_path=pg_catalog AS $me$
DECLARE d JSONB:=reconforge.me2_object(t,i);expected TEXT[]:=ARRAY['create'];actual TEXT[];phase INTEGER:=(d->>'phase')::integer;op TEXT;
BEGIN
 IF left(i,5) IN('ME2W-','ME2R-') THEN IF phase=1 THEN expected:=expected||ARRAY['approve'];END IF;
 ELSIF left(i,5) IN('ME2P-','ME2C-') THEN
  IF d->>'reviewer_id' IS NOT NULL THEN expected:=expected||ARRAY['review'];END IF;
  IF(left(i,5)='ME2P-' AND phase IN(2,3)) OR(left(i,5)='ME2C-' AND phase=2) THEN expected:=expected||ARRAY['post'];END IF;
  IF(left(i,5)='ME2P-' AND phase=4) OR(left(i,5)='ME2C-' AND phase=3) THEN expected:=expected||ARRAY['cancel'];END IF;
 ELSE
  IF d->'cost_entry'<>'null'::jsonb THEN expected:=expected||ARRAY['prepare'];END IF;
  IF d->>'reviewer_id' IS NOT NULL THEN expected:=expected||ARRAY['review'];END IF;
  IF phase IN(3,4) THEN expected:=expected||ARRAY['post'];END IF;
  IF phase=5 THEN expected:=expected||ARRAY['cancel'];END IF;
 END IF;
 SELECT array_agg(v ORDER BY v) INTO expected FROM unnest(expected) v;
 SELECT array_agg(operation ORDER BY operation) INTO actual FROM(
  SELECT operation FROM reconforge.manufacturing_execution_v2_commands WHERE tenant_id=t AND object_id=i
  UNION SELECT operation FROM reconforge.manufacturing_execution_v2_events WHERE tenant_id=t AND object_id=i) q;
 PERFORM reconforge.me2_assert(actual IS NOT DISTINCT FROM expected,'Complete ME2 command/event population must match its actual owner phase');
 FOREACH op IN ARRAY expected LOOP PERFORM reconforge.me2_evidence(t,i,op);END LOOP;
END $me$;
"""

_CLOSURE_SQL = r"""
CREATE FUNCTION reconforge.me2_close(t TEXT,i TEXT) RETURNS VOID LANGUAGE plpgsql SET search_path=pg_catalog AS $me$
DECLARE d JSONB:=reconforge.me2_object(t,i);r JSONB;m RECORD;c RECORD;p RECORD;f RECORD;a RECORD;z JSONB;line JSONB;field TEXT;
 maker TEXT;reviewer TEXT;poster TEXT;op TEXT;total NUMERIC:=0;produced NUMERIC:=0;held NUMERIC:=0;disposed NUMERIC:=0;released NUMERIC:=0;
BEGIN
 PERFORM reconforge.me2_assert(d IS NOT NULL AND reconforge.irp_scope(t,d->>'workspace_id',d->>'organization_id',d->>'legal_entity_id'),'ME2 needs exact original hierarchy');
 IF left(i,5) IN('ME2P-','ME2C-') THEN PERFORM reconforge.me2_close(t,d->>'order_id');RETURN;END IF;
 PERFORM reconforge.me2_history(t,i);
 IF left(i,5) IN('ME2W-','ME2R-') THEN
  SELECT * INTO c FROM reconforge.manufacturing_execution_v2_definitions WHERE tenant_id=t AND id=i;
  PERFORM reconforge.me2_assert(reconforge.me2_integer(c.payload->'version'),'Engineering revision uses an exact integer version');
  PERFORM reconforge.me2_assert(reconforge.irp_digest(c.payload)=c.source_digest AND c.payload->>'id'=i
   AND(c.payload->>'version')::bigint=c.version AND c.payload->>'creator_id'=c.creator_id
   AND c.creator_id=reconforge.me2_evidence(t,i,'create') AND(c.payload->>'effective_from')::date<=(c.payload->>'effective_until')::date,'Effective workcenter/routing requires canonical native source');
  PERFORM reconforge.me2_assert(c.phase=0 OR(c.reviewer_id=reconforge.me2_evidence(t,i,'approve') AND c.reviewer_id<>c.creator_id),'Engineering revision approval requires independent human');
  PERFORM reconforge.me2_assert(NOT EXISTS(SELECT 1 FROM reconforge.manufacturing_execution_v2_events WHERE tenant_id=t AND object_id=i AND(operation NOT IN('create','approve') OR(operation='approve' AND c.phase=0))),'Definition history cannot exceed its approved phase');
  IF c.kind='Routing' THEN
   SELECT payload||jsonb_build_object('source_digest',source_digest,'phase',phase) INTO r FROM reconforge.manufacturing_execution_boms WHERE tenant_id=t AND id=c.payload->>'bom_version_id';
   PERFORM reconforge.me2_assert(r IS NOT NULL AND(r->>'phase')::integer=1 AND r->>'source_digest'=c.payload->>'bom_digest'
    AND(r->>'workspace_id',r->>'organization_id',r->>'legal_entity_id')=(c.workspace_id,c.organization_id,c.legal_entity_id)
    AND jsonb_array_length(c.payload->'operations') BETWEEN 1 AND 50,'Routing needs actual approved native BOM and bounded operations');
   FOR z IN SELECT value FROM jsonb_array_elements(c.payload->'operations') WITH ORDINALITY x(value,n) LOOP
    PERFORM reconforge.me2_assert(reconforge.me2_integer(z->'sequence') AND reconforge.me2_integer(z->'minutes_per_batch'),'Routing sequence and actual work time require exact integers');
    SELECT * INTO a FROM reconforge.manufacturing_execution_v2_definitions WHERE tenant_id=t AND id=z->>'workcenter_id';
    PERFORM reconforge.me2_assert(a.id IS NOT NULL AND a.kind='Workcenter' AND a.phase=1 AND a.source_digest=z->>'workcenter_digest'
     AND(a.workspace_id,a.organization_id,a.legal_entity_id)=(c.workspace_id,c.organization_id,c.legal_entity_id)
     AND(z->>'minutes_per_batch')::bigint>0 AND(a.payload->>'effective_from')::date<=(c.payload->>'effective_from')::date
     AND(a.payload->>'effective_until')::date>=(c.payload->>'effective_until')::date,'Every routing operation binds its effective approved workcenter');
   END LOOP;
   PERFORM reconforge.me2_assert(NOT EXISTS(SELECT 1 FROM jsonb_array_elements(c.payload->'operations') WITH ORDINALITY x(value,n) WHERE(value->>'sequence')::bigint<>n),'Routing operations require contiguous order');
  END IF;RETURN;
 END IF;
 SELECT * INTO c FROM reconforge.manufacturing_execution_v2_orders WHERE tenant_id=t AND id=i;
 SELECT * INTO m FROM reconforge.manufacturing_execution_orders WHERE tenant_id=t AND id=c.material_order_id;
 r:=reconforge.me2_object(t,c.routing_id);
 PERFORM reconforge.me1_close_before_me2(t,m.id);
 PERFORM reconforge.me2_assert(m.id IS NOT NULL AND m.execution_owner_id=i AND m.source_digest=c.payload->>'material_source_digest'
  AND(m.workspace_id,m.organization_id,m.legal_entity_id)=(c.workspace_id,c.organization_id,c.legal_entity_id)
  AND reconforge.irp_digest(c.payload)=c.source_digest AND c.payload->>'id'=i
  AND r->>'kind'='Routing' AND(r->>'phase')::integer=1 AND r->>'source_digest'=c.payload->>'routing_digest'
  AND r->>'bom_version_id'=m.bom_version_id AND r->'operations'=c.payload->'operations'
  AND c.payload->'monetary_policy'=m.payload->'monetary_policy' AND c.payload->>'currency_code'=m.payload->>'currency_code'
  AND m.phase=CASE c.phase WHEN 4 THEN 3 ELSE c.phase END
  AND NOT EXISTS(SELECT 1 FROM reconforge.manufacturing_execution_completions WHERE tenant_id=t AND order_id=m.id),'ME2 must delegate exactly one original strict native material order without ME1 dispositions');
 maker:=reconforge.me2_evidence(t,i,'create');PERFORM reconforge.me2_assert(maker=c.payload->>'creator_id','Order retains actual creator');
 PERFORM reconforge.me2_assert((SELECT count(*) FROM reconforge.manufacturing_execution_v2_cost_claims WHERE tenant_id=t AND order_id=i)=jsonb_array_length(c.payload->'claims')
  AND jsonb_array_length(c.payload->'claims') BETWEEN 1 AND 100,'Complete original expense claim population is mandatory');
 FOR z IN SELECT value FROM jsonb_array_elements(c.payload->'claims') LOOP
  FOREACH field IN ARRAY ARRAY['amount_minor','original_debit_minor','operation_sequence','minutes','rate_minor_per_hour'] LOOP
   PERFORM reconforge.me2_assert(reconforge.me2_integer(z->field),'Original expense rate/time and financial claim require exact integer tokens');END LOOP;
  FOREACH field IN ARRAY ARRAY['line_number','debit_minor','credit_minor'] LOOP
   PERFORM reconforge.me2_assert(reconforge.me2_integer(z->'original_line'->field),'Original native expense snapshot requires exact integer amounts and line identity');END LOOP;
  SELECT * INTO f FROM reconforge.finance_posting_effects WHERE tenant_id=t AND id=z->>'effect_id';
  SELECT * INTO a FROM reconforge.finance_entry_lines WHERE tenant_id=t AND id=z->>'line_id';
  PERFORM pg_advisory_xact_lock(hashtextextended(jsonb_build_array(t,'me2-expense-line',z->>'effect_id',z->>'line_id')::text,0));
  PERFORM reconforge.me2_assert(f.id IS NOT NULL AND a.id IS NOT NULL AND f.entry_id=a.entry_id AND f.source_kind='Manual' AND f.reverses_effect_id IS NULL
   AND(f.workspace_id,f.organization_id,f.legal_entity_id)=(c.workspace_id,c.organization_id,c.legal_entity_id)
   AND(f.currency_code,f.currency_precision,f.currency_rounding_policy,f.currency_registry_version,f.currency_registry_digest)
    =(c.payload->>'currency_code',(c.payload->'monetary_policy'->>'precision')::integer,c.payload->'monetary_policy'->>'rounding_policy',c.payload->'monetary_policy'->>'registry_version',c.payload->'monetary_policy'->>'registry_digest')
   AND f.validation_digest=z->>'effect_validation_digest' AND a.debit_minor=(z->>'original_debit_minor')::bigint AND a.credit_minor=0
   AND EXISTS(SELECT 1 FROM jsonb_array_elements(f.snapshot_json->'lines') x WHERE x=z->'original_line' AND(x->>'line_number')::integer=a.line_number)
   AND EXISTS(SELECT 1 FROM reconforge.finance_accounts ac WHERE ac.tenant_id=t AND ac.id=a.account_id AND ac.account_type='Expense')
   AND z->>'kind' IN('Labor','Overhead') AND(z->>'minutes')::bigint>0 AND(z->>'rate_minor_per_hour')::bigint>0
   AND(z->>'amount_minor')::bigint=reconforge.me2_claim_value((z->>'minutes')::bigint,(z->>'rate_minor_per_hour')::bigint)
   AND EXISTS(SELECT 1 FROM jsonb_array_elements(c.payload->'operations') x WHERE x->'sequence'=z->'operation_sequence')
   AND EXISTS(SELECT 1 FROM reconforge.manufacturing_execution_v2_cost_claims cl WHERE cl.tenant_id=t AND cl.order_id=i
    AND cl.effect_id=f.id AND cl.line_id=a.id AND cl.payload=z AND cl.amount_minor=(z->>'amount_minor')::bigint
    AND(cl.workspace_id,cl.organization_id,cl.legal_entity_id)=(c.workspace_id,c.organization_id,c.legal_entity_id)
    AND cl.state=CASE WHEN c.phase=5 THEN'Released' WHEN c.phase IN(3,4) THEN'Consumed' ELSE'Reserved' END)
   AND(SELECT COALESCE(sum(amount_minor),0) FROM reconforge.manufacturing_execution_v2_cost_claims WHERE tenant_id=t AND effect_id=f.id AND line_id=a.id AND state<>'Released')<=a.debit_minor
   AND(c.phase=5 OR NOT EXISTS(SELECT 1 FROM reconforge.finance_posting_effects inverse WHERE inverse.tenant_id=t AND inverse.reverses_effect_id=f.id)),
   'Cumulative labor/overhead cost must retain an unreversed original posted positive expense line and exact rate/time');
  total:=total+(z->>'amount_minor')::numeric;
 END LOOP;
 IF c.cost_entry IS NOT NULL THEN
  maker:=reconforge.me2_evidence(t,i,'prepare');reviewer:=CASE WHEN c.reviewer_id IS NOT NULL THEN reconforge.me2_evidence(t,i,'review') END;
  PERFORM reconforge.me1_entry(t,c.cost_entry,reviewer,c.phase IN(3,4),c.phase=5);
  PERFORM reconforge.me2_assert(c.total_cost_minor=total+(m.issue_plan->>'total_cost_minor')::numeric
   AND reconforge.me2_policy(c.cost_entry->'snapshot'->'entry',c.payload)
   AND reconforge.me2_policy(m.issue_plan->'entry'->'snapshot'->'entry',c.payload)
   AND maker=c.cost_entry->'snapshot'->'entry'->>'preparer_actor_id' AND(c.reviewer_id IS NULL OR(c.reviewer_id=reviewer AND maker<>reviewer))
   AND jsonb_array_length(c.cost_entry->'snapshot'->'lines')=2*jsonb_array_length(c.payload->'claims')
   AND NOT EXISTS(WITH actual AS(SELECT x->>'account_id' account,(x->>'debit_minor')::numeric debit,(x->>'credit_minor')::numeric credit,x->'dimensions' dimensions FROM jsonb_array_elements(c.cost_entry->'snapshot'->'lines') x),
    expected AS(SELECT m.payload->>'wip_account_id' account,(claim_value.value->>'amount_minor')::numeric debit,0::numeric credit,claim_value.value->'original_line'->'dimensions' dimensions FROM jsonb_array_elements(c.payload->'claims') claim_value(value)
     UNION ALL SELECT claim_value.value->>'account_id',0::numeric,(claim_value.value->>'amount_minor')::numeric,claim_value.value->'original_line'->'dimensions' FROM jsonb_array_elements(c.payload->'claims') claim_value(value))
    (SELECT * FROM actual EXCEPT ALL SELECT * FROM expected) UNION ALL(SELECT * FROM expected EXCEPT ALL SELECT * FROM actual)),
   'Additional native WIP and original expense credits must exactly reproduce every retained source cost and dimension');
  IF c.phase IN(3,4) THEN poster:=reconforge.me2_evidence(t,i,'post');PERFORM reconforge.me2_assert(poster NOT IN(maker,reviewer)
   AND EXISTS(SELECT 1 FROM reconforge.finance_posting_effects e WHERE e.tenant_id=t AND e.id=c.cost_effect_id AND e.entry_id=c.cost_entry->>'entry_id' AND e.posted_actor_id=poster),'Cost pool posting requires its original effect and third actual human');END IF;
 ELSE PERFORM reconforge.me2_assert(c.phase IN(0,5) AND c.total_cost_minor=0 AND c.cost_effect_id IS NULL,'Unprepared ME2 order cannot invent WIP');END IF;
 IF c.phase=5 THEN PERFORM reconforge.me2_evidence(t,i,'cancel');END IF;
 FOR p IN SELECT * FROM reconforge.manufacturing_execution_v2_productions WHERE tenant_id=t AND order_id=i ORDER BY(payload->>'produced_before_scaled')::bigint,id LOOP
  FOREACH field IN ARRAY ARRAY['quantity_scaled','held_cost_minor','produced_before_scaled','produced_cost_before_minor'] LOOP
   PERFORM reconforge.me2_assert(reconforge.me2_integer(p.payload->field),'Held production must retain exact integer quantity and cost');END LOOP;
  PERFORM reconforge.me2_assert((p.payload->>'quantity_scaled')::bigint>0 AND(p.payload->>'held_cost_minor')::bigint>0,'A real production tranche has positive held quantity and cost');
  FOR z IN SELECT value FROM jsonb_array_elements(p.payload->'operations') LOOP
   PERFORM reconforge.me2_assert(reconforge.me2_integer(z->'sequence') AND reconforge.me2_integer(z->'minutes'),'Actual ordered operation evidence requires exact integer execution metadata');END LOOP;
  PERFORM reconforge.me2_history(t,p.id);
  maker:=reconforge.me2_evidence(t,p.id,'create');reviewer:=CASE WHEN p.reviewer_id IS NOT NULL THEN reconforge.me2_evidence(t,p.id,'review') END;
  PERFORM reconforge.me2_assert(c.phase IN(3,4) AND reconforge.irp_digest(p.payload)=p.source_digest AND p.payload->>'order_digest'=c.source_digest
   AND p.payload->>'cost_effect_id'=c.cost_effect_id AND p.payload->>'preparer_id'=maker AND p.payload->>'routing_digest'=c.payload->>'routing_digest'
   AND(p.workspace_id,p.organization_id,p.legal_entity_id)=(c.workspace_id,c.organization_id,c.legal_entity_id)
   AND jsonb_array_length(p.payload->'operations')=jsonb_array_length(c.payload->'operations')
   AND NOT EXISTS(SELECT 1 FROM jsonb_array_elements(p.payload->'operations') WITH ORDINALITY x(value,n)
    WHERE(value->>'sequence')::integer<>n OR(value->>'minutes')::numeric<=0 OR length(value->>'evidence_reference') NOT BETWEEN 1 AND 500)
   AND(p.reviewer_id IS NULL OR(p.reviewer_id=reviewer AND maker<>reviewer)),'Every quality hold retains complete actual ordered routing execution and independent review');
  IF p.phase<>4 THEN
   PERFORM reconforge.me2_assert((p.payload->>'produced_before_scaled')::numeric=produced AND(p.payload->>'produced_cost_before_minor')::numeric=held
    AND(p.payload->>'held_cost_minor')::bigint=reconforge.stock_sales_fifo_value(c.total_cost_minor-held::bigint,(m.payload->>'output_quantity_scaled')::bigint-produced::bigint,(p.payload->>'quantity_scaled')::bigint),
    'Quality hold costs must allocate the exact remaining frozen production pool');
  END IF;
  IF p.phase IN(2,3) THEN
   poster:=reconforge.me2_evidence(t,p.id,'post');PERFORM reconforge.me2_assert(poster NOT IN(maker,reviewer),'Holding production requires a third current human');
   produced:=produced+(p.payload->>'quantity_scaled')::numeric;held:=held+(p.payload->>'held_cost_minor')::numeric;
  ELSIF p.phase=4 THEN PERFORM reconforge.me2_evidence(t,p.id,'cancel');END IF;
  FOR a IN SELECT * FROM reconforge.manufacturing_execution_v2_inspections WHERE tenant_id=t AND production_id=p.id LOOP
   FOREACH field IN ARRAY ARRAY['accepted_quantity_scaled','rejected_quantity_scaled','accepted_cost_minor','rejected_cost_minor','released_cost_minor'] LOOP
    PERFORM reconforge.me2_assert(reconforge.me2_integer(a.payload->field),'Quality disposition retains exact integer quantities and money');END LOOP;
   PERFORM reconforge.me2_history(t,a.id);
   maker:=reconforge.me2_evidence(t,a.id,'create');reviewer:=CASE WHEN a.reviewer_id IS NOT NULL THEN reconforge.me2_evidence(t,a.id,'review') END;
   PERFORM reconforge.me2_assert(p.phase IN(2,3) AND reconforge.irp_digest(a.payload)=a.source_digest AND a.payload->>'production_digest'=p.source_digest
    AND a.order_id=i AND a.payload->>'order_digest'=c.source_digest AND a.payload->>'preparer_id'=maker
    AND(a.workspace_id,a.organization_id,a.legal_entity_id)=(c.workspace_id,c.organization_id,c.legal_entity_id)
    AND(a.payload->>'accepted_quantity_scaled')::numeric+(a.payload->>'rejected_quantity_scaled')::numeric=(p.payload->>'quantity_scaled')::numeric
    AND(a.payload->>'released_cost_minor')::numeric=(p.payload->>'held_cost_minor')::numeric
    AND(a.payload->>'accepted_cost_minor')::numeric+(a.payload->>'rejected_cost_minor')::numeric=(p.payload->>'held_cost_minor')::numeric
    AND(a.payload->>'accepted_cost_minor')::bigint=reconforge.stock_sales_fifo_value((p.payload->>'held_cost_minor')::bigint,(p.payload->>'quantity_scaled')::bigint,(a.payload->>'accepted_quantity_scaled')::bigint)
    AND(a.reviewer_id IS NULL OR(a.reviewer_id=reviewer AND maker<>reviewer)),'Inspection must disposition its complete exact held quantity and cost once');
   PERFORM reconforge.me2_assert(((a.payload->>'accepted_quantity_scaled')::numeric>0)=(a.payload->'receipt_plan'<>'null'::jsonb)
    AND((a.payload->>'rejected_quantity_scaled')::numeric>0)=(a.payload->'loss_entry'<>'null'::jsonb),'Accepted and rejected units require their original native receipts and loss');
   IF a.payload->'loss_entry'<>'null'::jsonb THEN
    PERFORM reconforge.me1_entry(t,a.payload->'loss_entry',reviewer,a.phase=2,a.phase=3);
    PERFORM reconforge.me2_assert(jsonb_array_length(a.payload->'loss_entry'->'snapshot'->'lines')=2
     AND reconforge.me2_policy(a.payload->'loss_entry'->'snapshot'->'entry',c.payload)
     AND EXISTS(SELECT 1 FROM jsonb_array_elements(a.payload->'loss_entry'->'snapshot'->'lines') x WHERE x->>'account_id'=m.payload->>'scrap_account_id'
      AND(x->>'debit_minor')::numeric=(a.payload->>'rejected_cost_minor')::numeric AND(x->>'credit_minor')::numeric=0)
     AND EXISTS(SELECT 1 FROM jsonb_array_elements(a.payload->'loss_entry'->'snapshot'->'lines') x WHERE x->>'account_id'=m.payload->>'wip_account_id'
      AND(x->>'credit_minor')::numeric=(a.payload->>'rejected_cost_minor')::numeric AND(x->>'debit_minor')::numeric=0),'Rejected inspection quantities release their exact held WIP to abnormal loss');
   END IF;
   IF a.payload->'receipt_plan'<>'null'::jsonb THEN
    PERFORM reconforge.me2_assert(EXISTS(SELECT 1 FROM reconforge.inventory_receipt_plans irp WHERE irp.tenant_id=t AND irp.id=a.payload->'receipt_plan'->>'plan_id'
     AND irp.plan_json=a.payload->'receipt_plan' AND irp.source_number=a.id AND irp.operation='Receipt'
     AND irp.quantity_scaled=(a.payload->>'accepted_quantity_scaled')::bigint AND irp.total_value_minor=(a.payload->>'accepted_cost_minor')::bigint
     AND irp.item_id=m.payload->>'output_item_id' AND irp.receipt_clearing_account_id=m.payload->>'wip_account_id'
     AND(irp.workspace_id,irp.organization_id,irp.legal_entity_id)=(c.workspace_id,c.organization_id,c.legal_entity_id)
     AND reconforge.me2_policy(irp.plan_json->'currency_policy',c.payload)
     AND irp.preparer_actor_id=maker AND(a.phase=2)=EXISTS(SELECT 1 FROM reconforge.inventory_receipt_links l WHERE l.tenant_id=t AND l.plan_id=irp.id)),
     'Only accepted inspected units can create native saleable FIFO finished goods');
   END IF;
   IF a.phase=2 THEN
    poster:=reconforge.me2_evidence(t,a.id,'post');PERFORM reconforge.me2_assert(poster NOT IN(maker,reviewer) AND p.phase=3,'Inspection posting requires a third human and terminal held source');
    IF a.payload->'loss_entry'<>'null'::jsonb THEN PERFORM reconforge.me2_assert(EXISTS(SELECT 1 FROM reconforge.finance_posting_effects loss_effect WHERE loss_effect.tenant_id=t AND loss_effect.id=a.loss_effect_id AND loss_effect.entry_id=a.payload->'loss_entry'->>'entry_id' AND loss_effect.posted_actor_id=poster),'Actual native abnormal loss effect must match its inspected source');END IF;
    IF a.payload->'receipt_plan'<>'null'::jsonb THEN PERFORM reconforge.me2_assert(EXISTS(SELECT 1 FROM reconforge.inventory_receipt_commands co WHERE co.tenant_id=t AND co.plan_id=a.payload->'receipt_plan'->>'plan_id' AND co.operation='commit' AND co.actor_user_id=poster AND co.result_json=a.receipt_effect),'Actual native FG receipt ACK must match exact inspected source');END IF;
    disposed:=disposed+(p.payload->>'quantity_scaled')::numeric;released:=released+(p.payload->>'held_cost_minor')::numeric;
   ELSE PERFORM reconforge.me2_assert(a.loss_effect_id IS NULL AND COALESCE(a.receipt_effect,'null'::jsonb)='null'::jsonb,'Unposted inspection cannot release WIP or stock held units');IF a.phase=3 THEN PERFORM reconforge.me2_evidence(t,a.id,'cancel');END IF;END IF;
  END LOOP;
  PERFORM reconforge.me2_assert((p.phase=3)=EXISTS(SELECT 1 FROM reconforge.manufacturing_execution_v2_inspections WHERE tenant_id=t AND production_id=p.id AND phase=2),'Held production can close only through one complete posted inspection');
 END LOOP;
 PERFORM reconforge.me2_assert(c.produced_quantity_scaled=produced AND c.produced_cost_minor=held AND c.disposed_quantity_scaled=disposed AND c.released_cost_minor=released
  AND produced<=(m.payload->>'output_quantity_scaled')::numeric AND held<=c.total_cost_minor AND released<=held AND disposed<=produced
  AND(c.phase=4)=(disposed=(m.payload->>'output_quantity_scaled')::numeric AND released=c.total_cost_minor),'Material/labor/overhead pool, held WIP, inspected FG, abnormal loss and residual must conserve exactly');
END $me$;
"""

_DISPATCH_SQL = r"""
ALTER FUNCTION reconforge.me1_close(TEXT,TEXT) RENAME TO me1_close_before_me2;
CREATE FUNCTION reconforge.me1_close(t TEXT,i TEXT) RETURNS VOID LANGUAGE plpgsql SET search_path=pg_catalog AS $me$
DECLARE owner TEXT;
BEGIN
 PERFORM reconforge.me1_close_before_me2(t,i);
 IF left(i,4)<>'ME1-' THEN RETURN;END IF;
 SELECT execution_owner_id INTO owner FROM reconforge.manufacturing_execution_orders WHERE tenant_id=t AND id=i;
 IF owner IS NOT NULL THEN PERFORM reconforge.me2_close(t,owner);END IF;
END $me$;
CREATE FUNCTION reconforge.me2_material_guard() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $me$
DECLARE owner TEXT;
BEGIN
 SELECT execution_owner_id INTO owner FROM reconforge.manufacturing_execution_orders WHERE tenant_id=NEW.tenant_id AND id=NEW.order_id;
 IF owner IS NULL THEN RETURN NEW;END IF;
 PERFORM reconforge.me2_assert(FALSE,'Delegated ME2 material source cannot bypass cost pool and quality hold through a ME1 disposition');RETURN NEW;
END $me$;
CREATE TRIGGER manufacturing_v2_delegated_completion BEFORE INSERT ON reconforge.manufacturing_execution_completions FOR EACH ROW EXECUTE FUNCTION reconforge.me2_material_guard();
CREATE FUNCTION reconforge.me2_native_immutable() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $me$
DECLARE entry TEXT;number TEXT;
BEGIN
 IF TG_TABLE_NAME='finance_entries' THEN entry:=OLD.id;number:=OLD.entry_number;
 ELSIF TG_TABLE_NAME='finance_entry_lines' THEN entry:=OLD.entry_id;
 ELSE SELECT entry_id INTO entry FROM reconforge.finance_entry_lines WHERE tenant_id=OLD.tenant_id AND id=OLD.entry_line_id;END IF;
 IF number IS NULL THEN SELECT entry_number INTO number FROM reconforge.finance_entries WHERE tenant_id=OLD.tenant_id AND id=entry;END IF;
 IF left(COALESCE(number,''),4)='ME2-' OR left(COALESCE(number,''),5)='ME2C-' THEN
  PERFORM reconforge.me2_assert(FALSE,'Source-owned prepared manufacturing cost and loss lines remain immutable');END IF;RETURN OLD;
END $me$;
CREATE FUNCTION reconforge.me2_deferred() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $me$
DECLARE i TEXT;number TEXT;entry TEXT;d RECORD;reference TEXT;
BEGIN
 IF TG_TABLE_NAME IN('manufacturing_execution_v2_events','manufacturing_execution_v2_commands') THEN i:=NEW.object_id;
 ELSIF TG_TABLE_NAME IN('manufacturing_execution_v2_cost_claims','manufacturing_execution_v2_cost_releases') THEN i:=NEW.order_id;
 ELSIF left(TG_TABLE_NAME,27)='manufacturing_execution_v2_' THEN i:=NEW.id;
 ELSE
  IF TG_TABLE_NAME='finance_entries' THEN number:=NEW.entry_number;reference:=NEW.external_reference;
  ELSIF TG_TABLE_NAME IN('finance_entry_lines','finance_posting_effects') THEN SELECT entry_number INTO number FROM reconforge.finance_entries WHERE tenant_id=NEW.tenant_id AND id=NEW.entry_id;
  ELSIF TG_TABLE_NAME='finance_entry_line_dimensions' THEN SELECT e.entry_number INTO number FROM reconforge.finance_entries e
   JOIN reconforge.finance_entry_lines detail ON detail.tenant_id=e.tenant_id AND detail.entry_id=e.id WHERE detail.tenant_id=NEW.tenant_id AND detail.id=NEW.entry_line_id;
  ELSIF TG_TABLE_NAME='inventory_receipt_plans' THEN
   number:=NEW.source_number;
   PERFORM reconforge.me2_assert(upper(number)!~'^ME2(?:-|[WRPKX]-)' OR left(number,5)='ME2C-',
    'Only exact inspected ME2C sources can use native FG receiving');
  ELSIF TG_TABLE_NAME='inventory_movements' THEN
   reference:=NEW.source_reference;
   PERFORM reconforge.me2_assert(upper(COALESCE(reference,''))!~'^ME2(?:-|[WRPKXC]-)',
    'Native manufacturing movements require the ME1 material or exact IRP inspected receipt engine');RETURN NEW;
  ELSIF TG_TABLE_NAME='inventory_movement_lines' THEN
   SELECT source_reference INTO reference FROM reconforge.inventory_movements WHERE tenant_id=NEW.tenant_id AND id=NEW.movement_id;
   PERFORM reconforge.me2_assert(upper(COALESCE(reference,''))!~'^ME2(?:-|[WRPKXC]-)',
    'Held manufacturing source cannot create a detached native stock line');RETURN NEW;
  ELSE SELECT source_number INTO number FROM reconforge.inventory_receipt_plans WHERE tenant_id=NEW.tenant_id AND id=NEW.plan_id;END IF;
  IF upper(COALESCE(number,''))~'^ME2(?:-|[WRPKXC]-)' THEN
   PERFORM reconforge.me2_assert(number=upper(number),'Reserved manufacturing source identifiers retain exact canonical casing');END IF;
  PERFORM reconforge.me2_assert(upper(COALESCE(number,''))!~'^ME2[WRPKX]-','Nonfinancial engineering and held-source IDs cannot become native journals or FG receipts');
  IF upper(COALESCE(reference,''))~'^ME2(?:-|[WRPKXC]-)' THEN
   PERFORM reconforge.me2_assert(number=reference AND(left(number,4)='ME2-' OR left(number,5)='ME2C-'),
    'A financial entry cannot attach another journal number to a frozen ME2 source reference');END IF;
  IF left(COALESCE(number,''),4)<>'ME2-' AND left(COALESCE(number,''),5)<>'ME2C-' THEN RETURN NEW;END IF;i:=number;
 END IF;
 PERFORM reconforge.me2_close(NEW.tenant_id,i);RETURN NEW;
END $me$;
DO $me$ DECLARE n TEXT;BEGIN
 FOREACH n IN ARRAY ARRAY['manufacturing_execution_v2_definitions','manufacturing_execution_v2_orders','manufacturing_execution_v2_cost_claims','manufacturing_execution_v2_cost_releases','manufacturing_execution_v2_productions','manufacturing_execution_v2_inspections','manufacturing_execution_v2_events','manufacturing_execution_v2_commands'] LOOP
  EXECUTE format('ALTER TABLE reconforge.%I ENABLE ROW LEVEL SECURITY',n);EXECUTE format('ALTER TABLE reconforge.%I FORCE ROW LEVEL SECURITY',n);
  IF n IN('manufacturing_execution_v2_events','manufacturing_execution_v2_commands') THEN
   EXECUTE format('CREATE POLICY manufacturing_v2_scope ON reconforge.%I USING(reconforge.me2_visible(tenant_id,object_id)) WITH CHECK(reconforge.me2_visible(tenant_id,object_id))',n);
  ELSE EXECUTE format('CREATE POLICY manufacturing_v2_scope ON reconforge.%I USING(reconforge.irp_scope(tenant_id,workspace_id,organization_id,legal_entity_id)) WITH CHECK(reconforge.irp_scope(tenant_id,workspace_id,organization_id,legal_entity_id))',n);END IF;
  EXECUTE format('CREATE TRIGGER manufacturing_v2_protect BEFORE INSERT OR UPDATE OR DELETE ON reconforge.%I FOR EACH ROW EXECUTE FUNCTION reconforge.me2_protect()',n);
  EXECUTE format('CREATE CONSTRAINT TRIGGER manufacturing_v2_close AFTER INSERT OR UPDATE ON reconforge.%I DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION reconforge.me2_deferred()',n);
 END LOOP;
 FOREACH n IN ARRAY ARRAY['finance_entries','finance_entry_lines','finance_entry_line_dimensions','finance_posting_effects','inventory_receipt_plans','inventory_receipt_reviews','inventory_receipt_commands','inventory_receipt_links','inventory_movements','inventory_movement_lines'] LOOP
  EXECUTE format('CREATE CONSTRAINT TRIGGER manufacturing_v2_native_close AFTER INSERT OR UPDATE ON reconforge.%I DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION reconforge.me2_deferred()',n);
 END LOOP;
 CREATE TRIGGER manufacturing_v2_native_immutable BEFORE DELETE ON reconforge.finance_entries FOR EACH ROW EXECUTE FUNCTION reconforge.me2_native_immutable();
 FOREACH n IN ARRAY ARRAY['finance_entry_lines','finance_entry_line_dimensions'] LOOP
  EXECUTE format('CREATE TRIGGER manufacturing_v2_native_immutable BEFORE UPDATE OR DELETE ON reconforge.%I FOR EACH ROW EXECUTE FUNCTION reconforge.me2_native_immutable()',n);END LOOP;
END $me$;
"""

UPGRADE_SQL = _TABLES_SQL + OWNERSHIP_UPGRADE_SQL + _AUTHORITY_SQL + _CLOSURE_SQL + _DISPATCH_SQL

_DOWNGRADE_SQL = r"""
DO $me$ BEGIN IF EXISTS(SELECT 1 FROM reconforge.manufacturing_execution_v2_definitions)
 OR EXISTS(SELECT 1 FROM reconforge.manufacturing_execution_v2_orders) OR EXISTS(SELECT 1 FROM reconforge.manufacturing_execution_v2_events)
 THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Populated manufacturing v2 source and evidence must be retained';END IF;END $me$;
DO $me$ DECLARE n TEXT;BEGIN
 FOREACH n IN ARRAY ARRAY['finance_entries','finance_entry_lines','finance_entry_line_dimensions','finance_posting_effects','inventory_receipt_plans','inventory_receipt_reviews','inventory_receipt_commands','inventory_receipt_links','inventory_movements','inventory_movement_lines'] LOOP EXECUTE format('DROP TRIGGER manufacturing_v2_native_close ON reconforge.%I',n);END LOOP;
END $me$;
DROP TRIGGER manufacturing_v2_delegated_completion ON reconforge.manufacturing_execution_completions;
DROP TRIGGER manufacturing_v2_native_immutable ON reconforge.finance_entries;
DROP TRIGGER manufacturing_v2_native_immutable ON reconforge.finance_entry_lines;
DROP TRIGGER manufacturing_v2_native_immutable ON reconforge.finance_entry_line_dimensions;
ALTER TABLE reconforge.manufacturing_execution_orders DROP CONSTRAINT manufacturing_v2_owner_fk;
ALTER TABLE reconforge.manufacturing_execution_orders DROP COLUMN execution_owner_id;
DROP TABLE reconforge.manufacturing_execution_v2_commands;DROP TABLE reconforge.manufacturing_execution_v2_events;
DROP TABLE reconforge.manufacturing_execution_v2_inspections;DROP TABLE reconforge.manufacturing_execution_v2_productions;
DROP TABLE reconforge.manufacturing_execution_v2_cost_releases;
DROP TABLE reconforge.manufacturing_execution_v2_cost_claims;DROP TABLE reconforge.manufacturing_execution_v2_orders;DROP TABLE reconforge.manufacturing_execution_v2_definitions;
DROP FUNCTION reconforge.me1_close(TEXT,TEXT);ALTER FUNCTION reconforge.me1_close_before_me2(TEXT,TEXT) RENAME TO me1_close;
DROP FUNCTION reconforge.me2_deferred();DROP FUNCTION reconforge.me2_material_guard();DROP FUNCTION reconforge.me2_close(TEXT,TEXT);
DROP FUNCTION reconforge.me2_native_immutable();
DROP FUNCTION reconforge.me2_evidence(TEXT,TEXT,TEXT);DROP FUNCTION reconforge.me2_ack(TEXT,TEXT,TEXT);DROP FUNCTION reconforge.me2_protect();
DROP FUNCTION reconforge.me2_history(TEXT,TEXT);
DROP FUNCTION reconforge.me2_permission(TEXT);DROP FUNCTION reconforge.me2_visible(TEXT,TEXT);DROP FUNCTION reconforge.me2_object(TEXT,TEXT);DROP FUNCTION reconforge.me2_assert(BOOLEAN,TEXT);
DROP FUNCTION reconforge.me2_claim_value(BIGINT,BIGINT);
DROP FUNCTION reconforge.me2_integer(JSONB);
DROP FUNCTION reconforge.me2_policy(JSONB,JSONB);
"""

DOWNGRADE_SQL = OWNERSHIP_DOWNGRADE_SQL + _DOWNGRADE_SQL


def install_postgres_manufacturing_execution_v2_schema(connection: Any) -> None:
    row = connection.execute("SELECT to_regclass('reconforge.manufacturing_execution_v2_orders') installed").fetchone()
    installed = row["installed"] if isinstance(row, Mapping) else row[0]
    if installed is None:
        connection.execute(UPGRADE_SQL)
        return
    row = connection.execute("""SELECT
        (SELECT count(*) FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
         WHERE n.nspname='reconforge' AND c.relname=ANY(ARRAY[
          'manufacturing_execution_v2_definitions','manufacturing_execution_v2_orders','manufacturing_execution_v2_cost_claims',
          'manufacturing_execution_v2_cost_releases','manufacturing_execution_v2_productions','manufacturing_execution_v2_inspections',
          'manufacturing_execution_v2_events','manufacturing_execution_v2_commands','financial_effect_claim_gates',
          'financial_effect_ownership_guards','financial_effect_ownership_releases']) AND c.relrowsecurity AND c.relforcerowsecurity)=11
        AND to_regprocedure('reconforge.me2_close(text,text)') IS NOT NULL
        AND to_regprocedure('reconforge.me2_history(text,text)') IS NOT NULL
        AND to_regprocedure('reconforge.me1_close_before_me2(text,text)') IS NOT NULL
        AND to_regprocedure('reconforge.touch_financial_effect_claim_gate(text,text)') IS NOT NULL
        AND EXISTS(SELECT 1 FROM pg_catalog.pg_attribute WHERE attrelid='reconforge.manufacturing_execution_orders'::regclass
          AND attname='execution_owner_id' AND NOT attisdropped) complete""").fetchone()
    complete = row["complete"] if isinstance(row, Mapping) else row[0]
    if complete is not True:
        raise RuntimeError("Existing ME2 catalog is incomplete; apply the exact ordered manufacturing migration.")
