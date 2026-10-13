"""Retained pre-stock BOM demand and exclusive native supply ownership."""
from collections.abc import Mapping
from typing import Any

from reconforge.infrastructure.postgres_inventory_quantity_source_ownership import (
    DOWNGRADE_SQL as CORE_DOWNGRADE_SQL,
)
from reconforge.infrastructure.postgres_inventory_quantity_source_ownership import (
    UPGRADE_SQL as CORE_UPGRADE_SQL,
)

_TABLES_SQL = r"""
CREATE TABLE reconforge.manufacturing_supply_plans (
 tenant_id TEXT NOT NULL,id TEXT NOT NULL CHECK(id~'^MSP1-[A-F0-9]{32}$'),
 workspace_id TEXT NOT NULL,organization_id TEXT NOT NULL,legal_entity_id TEXT NOT NULL,
 number TEXT NOT NULL,bom_version_id TEXT NOT NULL,routing_id TEXT NOT NULL,budget_id TEXT NOT NULL,
 payload JSONB NOT NULL CHECK(octet_length(payload::text)<=1048576),source_digest TEXT NOT NULL CHECK(source_digest~'^[a-f0-9]{64}$'),
 phase SMALLINT NOT NULL DEFAULT 0 CHECK(phase BETWEEN 0 AND 3),row_version INTEGER NOT NULL DEFAULT 1 CHECK(row_version BETWEEN 1 AND 2001),
 creator_actor_id TEXT NOT NULL,reviewer_actor_id TEXT,material_order_id TEXT,manufacturing_order_id TEXT,
 PRIMARY KEY(tenant_id,id),UNIQUE(tenant_id,workspace_id,number),UNIQUE(tenant_id,id,workspace_id,organization_id,legal_entity_id),
 UNIQUE(tenant_id,material_order_id),UNIQUE(tenant_id,manufacturing_order_id),
 FOREIGN KEY(tenant_id,bom_version_id) REFERENCES reconforge.manufacturing_execution_boms(tenant_id,id),
 FOREIGN KEY(tenant_id,routing_id) REFERENCES reconforge.manufacturing_execution_v2_definitions(tenant_id,id),
 FOREIGN KEY(tenant_id,budget_id) REFERENCES reconforge.budget_envelopes(tenant_id,id),
 FOREIGN KEY(tenant_id,creator_actor_id) REFERENCES reconforge.identity_users(tenant_id,id),
 FOREIGN KEY(tenant_id,reviewer_actor_id) REFERENCES reconforge.identity_users(tenant_id,id),
 FOREIGN KEY(tenant_id,material_order_id) REFERENCES reconforge.manufacturing_execution_orders(tenant_id,id),
 FOREIGN KEY(tenant_id,manufacturing_order_id) REFERENCES reconforge.manufacturing_execution_v2_orders(tenant_id,id)
);
CREATE TABLE reconforge.manufacturing_supply_requirements (
 tenant_id TEXT NOT NULL,id TEXT NOT NULL CHECK(id~'^MSP1D-[A-F0-9]{32}$'),plan_id TEXT NOT NULL,sequence INTEGER NOT NULL CHECK(sequence BETWEEN 1 AND 100),
 workspace_id TEXT NOT NULL,organization_id TEXT NOT NULL,legal_entity_id TEXT NOT NULL,
 item_id TEXT NOT NULL,uom_id TEXT NOT NULL,quantity_precision INTEGER NOT NULL CHECK(quantity_precision BETWEEN 0 AND 6),location_id TEXT NOT NULL,
 gross_quantity_scaled BIGINT NOT NULL CHECK(gross_quantity_scaled BETWEEN 1 AND 9000000000000000000),
 onhand_reserved_scaled BIGINT CHECK(onhand_reserved_scaled BETWEEN 0 AND gross_quantity_scaled),
 shortage_quantity_scaled BIGINT CHECK(shortage_quantity_scaled BETWEEN 0 AND gross_quantity_scaled),
 payload JSONB NOT NULL CHECK(octet_length(payload::text)<=65536),source_digest TEXT NOT NULL CHECK(source_digest~'^[a-f0-9]{64}$'),
 coverage_json JSONB CHECK(octet_length(coverage_json::text)<=65536),coverage_digest TEXT CHECK(coverage_digest~'^[a-f0-9]{64}$'),
 PRIMARY KEY(tenant_id,id),UNIQUE(tenant_id,plan_id,sequence),UNIQUE(tenant_id,plan_id,item_id),
 UNIQUE(tenant_id,id,plan_id,workspace_id,organization_id,legal_entity_id),
 CHECK((onhand_reserved_scaled IS NULL)=(shortage_quantity_scaled IS NULL) AND(onhand_reserved_scaled IS NULL)=(coverage_json IS NULL)
  AND(coverage_json IS NULL)=(coverage_digest IS NULL)
  AND(onhand_reserved_scaled IS NULL OR onhand_reserved_scaled+shortage_quantity_scaled=gross_quantity_scaled)),
 FOREIGN KEY(tenant_id,plan_id,workspace_id,organization_id,legal_entity_id)
 REFERENCES reconforge.manufacturing_supply_plans(tenant_id,id,workspace_id,organization_id,legal_entity_id),
 FOREIGN KEY(tenant_id,item_id) REFERENCES reconforge.inventory_items(tenant_id,id),
 FOREIGN KEY(tenant_id,uom_id) REFERENCES reconforge.inventory_units_of_measure(tenant_id,id),
 FOREIGN KEY(tenant_id,location_id) REFERENCES reconforge.inventory_locations(tenant_id,id)
);
CREATE TABLE reconforge.manufacturing_supply_stock_claims (
 tenant_id TEXT NOT NULL,id TEXT NOT NULL CHECK(id~'^MSP1K-[A-F0-9]{32}$'),plan_id TEXT NOT NULL,requirement_id TEXT NOT NULL,
 workspace_id TEXT NOT NULL,organization_id TEXT NOT NULL,legal_entity_id TEXT NOT NULL,
 item_id TEXT NOT NULL,uom_id TEXT NOT NULL,quantity_precision INTEGER NOT NULL CHECK(quantity_precision BETWEEN 0 AND 6),location_id TEXT NOT NULL,
 quantity_scaled BIGINT NOT NULL CHECK(quantity_scaled BETWEEN 1 AND 9000000000000000000),
 origin TEXT NOT NULL CHECK(origin IN('OnHand','Receipt')),native_receipt_plan_id TEXT,
 state TEXT NOT NULL DEFAULT 'Active' CHECK(state IN('Active','Released','HandedOff')),created_version INTEGER NOT NULL,
 PRIMARY KEY(tenant_id,id),UNIQUE(tenant_id,native_receipt_plan_id),
 UNIQUE(tenant_id,id,plan_id,workspace_id,organization_id,legal_entity_id),
 CHECK((origin='Receipt')=(native_receipt_plan_id IS NOT NULL)),
 FOREIGN KEY(tenant_id,requirement_id,plan_id,workspace_id,organization_id,legal_entity_id)
 REFERENCES reconforge.manufacturing_supply_requirements(tenant_id,id,plan_id,workspace_id,organization_id,legal_entity_id),
 FOREIGN KEY(tenant_id,native_receipt_plan_id) REFERENCES reconforge.inventory_receipt_plans(tenant_id,id)
);
CREATE UNIQUE INDEX manufacturing_supply_onhand_once ON reconforge.manufacturing_supply_stock_claims(tenant_id,requirement_id) WHERE origin='OnHand';
CREATE TABLE reconforge.manufacturing_supply_stock_releases (
 tenant_id TEXT NOT NULL,id TEXT NOT NULL,plan_id TEXT NOT NULL,claim_id TEXT NOT NULL,
 workspace_id TEXT NOT NULL,organization_id TEXT NOT NULL,legal_entity_id TEXT NOT NULL,
 purpose TEXT NOT NULL CHECK(purpose IN('Cancel','Handoff')),target_material_order_id TEXT,
 actor_id TEXT NOT NULL,reason TEXT NOT NULL CHECK(length(reason) BETWEEN 1 AND 500),created_version INTEGER NOT NULL,
 PRIMARY KEY(tenant_id,id),UNIQUE(tenant_id,claim_id),CHECK((purpose='Handoff')=(target_material_order_id IS NOT NULL)),
 FOREIGN KEY(tenant_id,claim_id,plan_id,workspace_id,organization_id,legal_entity_id)
 REFERENCES reconforge.manufacturing_supply_stock_claims(tenant_id,id,plan_id,workspace_id,organization_id,legal_entity_id),
 FOREIGN KEY(tenant_id,target_material_order_id) REFERENCES reconforge.manufacturing_execution_orders(tenant_id,id),
 FOREIGN KEY(tenant_id,actor_id) REFERENCES reconforge.identity_users(tenant_id,id)
);
CREATE TABLE reconforge.manufacturing_supply_procurement_claims (
 tenant_id TEXT NOT NULL,id TEXT NOT NULL CHECK(id~'^MSP1Q-[A-F0-9]{32}$'),plan_id TEXT NOT NULL,requirement_id TEXT NOT NULL,
 workspace_id TEXT NOT NULL,organization_id TEXT NOT NULL,legal_entity_id TEXT NOT NULL,
 quantity_scaled BIGINT NOT NULL CHECK(quantity_scaled BETWEEN 1 AND 9000000000000000000),
 requisition_id TEXT NOT NULL,source_line INTEGER NOT NULL CHECK(source_line BETWEEN 1 AND 100),
 payload JSONB NOT NULL CHECK(octet_length(payload::text)<=65536),source_digest TEXT NOT NULL CHECK(source_digest~'^[a-f0-9]{64}$'),
 state TEXT NOT NULL DEFAULT 'Active' CHECK(state IN('Active','Released','HandedOff')),created_version INTEGER NOT NULL,
 PRIMARY KEY(tenant_id,id),UNIQUE(tenant_id,requisition_id,source_line),UNIQUE(tenant_id,requisition_id,requirement_id),
 FOREIGN KEY(tenant_id,requirement_id,plan_id,workspace_id,organization_id,legal_entity_id)
 REFERENCES reconforge.manufacturing_supply_requirements(tenant_id,id,plan_id,workspace_id,organization_id,legal_entity_id),
 FOREIGN KEY(tenant_id,requisition_id) REFERENCES reconforge.procurement_sourcing_requisitions(tenant_id,id) DEFERRABLE INITIALLY DEFERRED
);
CREATE TABLE reconforge.manufacturing_supply_events (
 tenant_id TEXT NOT NULL,plan_id TEXT NOT NULL,version INTEGER NOT NULL,operation TEXT NOT NULL,actor_id TEXT NOT NULL,
 request_json JSONB NOT NULL,request_digest TEXT NOT NULL,reason TEXT NOT NULL,
 audit_event_id TEXT NOT NULL,outbox_event_id TEXT NOT NULL,
 PRIMARY KEY(tenant_id,plan_id,version),UNIQUE(tenant_id,audit_event_id),UNIQUE(tenant_id,outbox_event_id),
 FOREIGN KEY(tenant_id,plan_id) REFERENCES reconforge.manufacturing_supply_plans(tenant_id,id),
 FOREIGN KEY(tenant_id,audit_event_id) REFERENCES reconforge.domain_audit_events(tenant_id,id),
 FOREIGN KEY(tenant_id,outbox_event_id) REFERENCES reconforge.outbox_events(tenant_id,event_id)
);
CREATE TABLE reconforge.manufacturing_supply_commands (
 tenant_id TEXT NOT NULL,workspace_id TEXT NOT NULL,command_id TEXT NOT NULL,plan_id TEXT NOT NULL,version INTEGER NOT NULL,
 operation TEXT NOT NULL,actor_id TEXT NOT NULL,request_json JSONB NOT NULL,request_digest TEXT NOT NULL,
 native_kind TEXT,native_owner_id TEXT,native_command_id TEXT,response_json JSONB NOT NULL CHECK(octet_length(response_json::text)<=4194304),
 PRIMARY KEY(tenant_id,workspace_id,command_id),UNIQUE(tenant_id,plan_id,version),UNIQUE(tenant_id,native_kind,native_owner_id,native_command_id),
 CHECK((native_kind IS NULL)=(native_owner_id IS NULL) AND(native_kind IS NULL)=(native_command_id IS NULL)),
 FOREIGN KEY(tenant_id,plan_id,version) REFERENCES reconforge.manufacturing_supply_events(tenant_id,plan_id,version)
);
"""


def installed_manufacturing_supply_plan(connection: Any) -> bool:
    row = connection.execute("SELECT to_regclass('reconforge.manufacturing_supply_plans') installed").fetchone()
    return (row["installed"] if isinstance(row, Mapping) else row[0]) is not None


_OWNER_SQL = r"""
CREATE FUNCTION reconforge.msp_assert(valid BOOLEAN,message TEXT) RETURNS VOID LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog AS $msp$
BEGIN IF valid IS DISTINCT FROM TRUE THEN RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='manufacturing_supply_owner',MESSAGE=message;END IF;END $msp$;
CREATE FUNCTION reconforge.msp_visible(t TEXT,i TEXT) RETURNS BOOLEAN LANGUAGE sql STABLE SET search_path=pg_catalog AS $msp$
 SELECT EXISTS(SELECT 1 FROM reconforge.manufacturing_supply_plans p WHERE p.tenant_id=t AND p.id=i
 AND reconforge.irp_scope(p.tenant_id,p.workspace_id,p.organization_id,p.legal_entity_id)) $msp$;
CREATE FUNCTION reconforge.msp_public(t TEXT,i TEXT,v INTEGER) RETURNS JSONB LANGUAGE plpgsql STABLE SET search_path=pg_catalog AS $msp$
DECLARE p RECORD;phase INTEGER:=0;reviewer TEXT;material TEXT;production TEXT;requirements JSONB;claims JSONB;procurement JSONB;
BEGIN
 SELECT * INTO p FROM reconforge.manufacturing_supply_plans WHERE tenant_id=t AND id=i;
 IF p.id IS NULL OR v NOT BETWEEN 1 AND p.row_version THEN RETURN NULL;END IF;
 SELECT actor_id INTO reviewer FROM reconforge.manufacturing_supply_events WHERE tenant_id=t AND plan_id=i AND operation='approve' AND version<=v;
 IF reviewer IS NOT NULL THEN phase:=1;END IF;
 IF EXISTS(SELECT 1 FROM reconforge.manufacturing_supply_events WHERE tenant_id=t AND plan_id=i AND operation='cancel' AND version<=v) THEN phase:=3;END IF;
 IF EXISTS(SELECT 1 FROM reconforge.manufacturing_supply_events WHERE tenant_id=t AND plan_id=i AND operation='handoff' AND version<=v) THEN
 phase:=2;material:=p.material_order_id;production:=p.manufacturing_order_id;END IF;
 SELECT COALESCE(jsonb_agg(r.payload||jsonb_build_object('source_digest',r.source_digest,
  'coverage',CASE WHEN reviewer IS NOT NULL THEN r.coverage_json ELSE NULL END,
  'coverage_digest',CASE WHEN reviewer IS NOT NULL THEN r.coverage_digest ELSE NULL END) ORDER BY r.sequence),'[]'::jsonb)
 INTO requirements FROM reconforge.manufacturing_supply_requirements r WHERE r.tenant_id=t AND r.plan_id=i;
 SELECT COALESCE(jsonb_agg(jsonb_build_object('id',c.id,'requirement_id',c.requirement_id,'quantity_scaled',c.quantity_scaled,
  'origin',c.origin,'native_receipt_plan_id',c.native_receipt_plan_id,'state',CASE WHEN r.id IS NULL THEN'Active'
  WHEN r.purpose='Handoff' THEN'HandedOff' ELSE'Released' END) ORDER BY c.id),'[]'::jsonb)
 INTO claims FROM reconforge.manufacturing_supply_stock_claims c LEFT JOIN reconforge.manufacturing_supply_stock_releases r
 ON r.tenant_id=c.tenant_id AND r.claim_id=c.id AND r.created_version<=v WHERE c.tenant_id=t AND c.plan_id=i AND c.created_version<=v;
 SELECT COALESCE(jsonb_agg(c.payload||jsonb_build_object('source_digest',c.source_digest,'state',CASE
 WHEN EXISTS(SELECT 1 FROM reconforge.manufacturing_supply_events event JOIN reconforge.manufacturing_supply_commands command
 ON command.tenant_id=event.tenant_id AND command.plan_id=event.plan_id AND command.version=event.version
 WHERE event.tenant_id=t AND event.plan_id=i AND event.operation='source-cancel' AND command.native_owner_id=c.requisition_id AND event.version<=v)
 THEN'Released' WHEN phase=2 THEN'HandedOff' ELSE'Active' END) ORDER BY c.id),'[]'::jsonb)
 INTO procurement FROM reconforge.manufacturing_supply_procurement_claims c WHERE c.tenant_id=t AND c.plan_id=i AND c.created_version<=v;
 RETURN p.payload||jsonb_build_object('source_digest',p.source_digest,'phase',phase,'row_version',v,'reviewer_actor_id',reviewer,
 'material_order_id',material,'manufacturing_order_id',production,'planned_requirements',requirements,'stock_claims',claims,'procurement_claims',procurement);
END $msp$;
CREATE FUNCTION reconforge.msp_evidence(t TEXT,i TEXT,v INTEGER) RETURNS TEXT LANGUAGE plpgsql SET search_path=pg_catalog AS $msp$
DECLARE p RECORD;e RECORD;c RECORD;metadata JSONB;source JSONB;native JSONB;native_request JSONB;
BEGIN
 SELECT * INTO p FROM reconforge.manufacturing_supply_plans WHERE tenant_id=t AND id=i;
 SELECT * INTO e FROM reconforge.manufacturing_supply_events WHERE tenant_id=t AND plan_id=i AND version=v;
 SELECT * INTO c FROM reconforge.manufacturing_supply_commands WHERE tenant_id=t AND plan_id=i AND version=v;
 source:=reconforge.msp_public(t,i,v);
 metadata:=jsonb_build_object('source_digest',p.source_digest,'version',v,'operation',e.operation,'reason',e.reason);
 PERFORM reconforge.msp_assert(e.plan_id IS NOT NULL AND c.plan_id IS NOT NULL AND source IS NOT NULL
 AND(c.workspace_id,c.operation,c.actor_id,c.request_json,c.request_digest)=(p.workspace_id,e.operation,e.actor_id,e.request_json,e.request_digest)
 AND c.request_json->>'operation'=e.operation AND c.request_json->>'actor_id'=e.actor_id
 AND reconforge.irp_digest(c.request_json)=c.request_digest AND jsonb_typeof(c.request_json->'request')='object'
 AND c.response_json->'source'=source,'Each command needs a complete exact original request and historical source ACK');
 IF e.operation='create' THEN
 PERFORM reconforge.msp_assert(v=1 AND c.request_json->'request'=p.payload->'command_request' AND e.actor_id=p.creator_actor_id,'Creation retains original source request and current maker');
 ELSIF e.operation IN('approve','cancel') THEN
 PERFORM reconforge.msp_assert(c.request_json->'request'=jsonb_build_object('id',i,'expected_digest',p.source_digest,'reason',e.reason),
 'Approval/cancellation request binds the complete original source and reason');
 END IF;
 IF c.native_kind IS NULL THEN PERFORM reconforge.msp_assert(c.native_owner_id IS NULL AND c.native_command_id IS NULL
 AND c.response_json=jsonb_build_object('source',source),'A non-native command cannot invent a native acknowledgment');
 ELSIF c.native_kind='SRC' THEN
 SELECT response_json,request_json INTO native,native_request FROM reconforge.procurement_sourcing_commands command WHERE command.tenant_id=t
 AND command.workspace_id=p.workspace_id AND command.requisition_id=c.native_owner_id AND command.command_id=c.native_command_id
 AND command.actor_id=c.actor_id;
 PERFORM reconforge.msp_assert(native IS NOT NULL AND e.operation='source-'||(native_request->>'operation')
 AND c.request_json->'request'->'native_request'=native_request->'request'
 AND c.response_json=jsonb_build_object('source',source,'native_response',native)
 AND EXISTS(SELECT 1 FROM reconforge.manufacturing_supply_procurement_claims claim WHERE claim.tenant_id=t AND claim.plan_id=i
 AND claim.requisition_id=c.native_owner_id AND claim.created_version<=v),'Native sourcing ACK must be its original owned command and full companion');
 ELSIF c.native_kind='PP' THEN
 SELECT response_json,request_json INTO native,native_request FROM reconforge.procurement_partial_commands command WHERE command.tenant_id=t
 AND command.workspace_id=p.workspace_id AND command.order_id=c.native_owner_id AND command.command_id=c.native_command_id AND command.actor_id=c.actor_id;
 PERFORM reconforge.msp_assert(native IS NOT NULL AND c.request_json->'request'->>'order_id'=c.native_owner_id
 AND c.request_json->'request'->'native_request'=native_request
 AND EXISTS(SELECT 1 FROM reconforge.procurement_partial_commands command WHERE command.tenant_id=t AND command.order_id=c.native_owner_id
 AND command.command_id=c.native_command_id AND command.operation=c.request_json->'request'->>'native_operation'
 AND command.request_digest=reconforge.irp_digest(jsonb_build_object('order_id',c.native_owner_id,'operation',command.operation,
 'payload',native_request,'actor_id',c.actor_id)))
 AND c.response_json=jsonb_build_object('source',source,'native_response',native)
 AND e.operation=CASE c.request_json->'request'->>'native_operation' WHEN'submit-order' THEN'purchase-submit' WHEN'approve-order' THEN'purchase-approve'
 WHEN'prepare-receipt-line' THEN'receive-prepare'
 WHEN'review-receipt' THEN'receive-review' WHEN'receive' THEN'receive-commit' WHEN'match-invoice-lines' THEN'invoice-match'
 WHEN'approve-invoice' THEN'invoice-approve' WHEN'prepare-accrual' THEN'invoice-prepare' WHEN'review-accrual' THEN'invoice-review' END,
 'Receiving/AP ACK binds one complete actual native command, actor, request, operation and original response');
 ELSIF c.native_kind='BPC' THEN
 SELECT response_json,request_json INTO native,native_request FROM reconforge.procurement_commitment_commands command WHERE command.tenant_id=t
 AND command.workspace_id=p.workspace_id AND command.order_id=c.native_owner_id AND command.command_id=c.native_command_id AND command.actor_id=c.actor_id;
 PERFORM reconforge.msp_assert(native IS NOT NULL AND native_request->>'operation'='consume' AND e.operation='invoice-post'
 AND c.request_json->'request'->>'order_id'=c.native_owner_id AND c.request_json->'request'->'native_request'=native_request->'request'
 AND c.response_json=jsonb_build_object('source',source,'native_response',native),'Budget consumption ACK is its actual original AP and appropriation command');
 ELSIF c.native_kind='ME2' THEN
 SELECT response_json,request_json INTO native,native_request FROM reconforge.manufacturing_execution_v2_commands command WHERE command.tenant_id=t
 AND command.workspace_id=p.workspace_id AND command.object_id=c.native_owner_id AND command.command_id=c.native_command_id AND command.actor_id=c.actor_id;
 PERFORM reconforge.msp_assert(native IS NOT NULL AND e.operation='handoff' AND native_request->>'operation'='create'
 AND c.native_owner_id=p.manufacturing_order_id AND c.request_json->'request'->'native_request'=native_request->'request'
 AND c.request_json->'request'->>'id'=p.id AND c.request_json->'request'->>'expected_digest'=p.source_digest
 AND c.request_json->'request'->>'reason'=e.reason AND c.response_json=jsonb_build_object('source',source,'native_response',native),
 'Production handoff ACK must be its exact original native ME2 source creation');
 ELSE PERFORM reconforge.msp_assert(FALSE,'Unknown native supply command family');END IF;
 PERFORM reconforge.msp_assert(EXISTS(SELECT 1 FROM reconforge.domain_audit_events audit JOIN reconforge.outbox_events outbox
 ON outbox.tenant_id=audit.tenant_id WHERE audit.tenant_id=t AND audit.id=e.audit_event_id AND audit.actor_user_id=e.actor_id
 AND audit.object_type='manufacturing_supply_plan' AND audit.object_id=i AND audit.action='manufacturing_supply_plan.'||e.operation
 AND audit.metadata_json=metadata AND outbox.event_id=e.outbox_event_id AND outbox.aggregate_type='manufacturing_supply_plan'
 AND outbox.aggregate_id=i AND outbox.event_type=audit.action AND(outbox.workspace_id,outbox.organization_id,outbox.legal_entity_id)
 =(p.workspace_id,p.organization_id,p.legal_entity_id) AND outbox.payload=metadata||jsonb_build_object('audit_event_id',audit.id)),
 'Every supply command requires exact immutable audit and scoped outbox');RETURN e.actor_id;
END $msp$;
CREATE FUNCTION reconforge.msp_protect() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $msp$
DECLARE a TEXT:=current_setting('app.manufacturing_supply_actor_id',true);op TEXT:=current_setting('app.manufacturing_supply_operation',true);
 d JSONB;permission TEXT;allowed TEXT[];p RECORD;
BEGIN
 PERFORM reconforge.msp_assert(TG_OP<>'DELETE','Planning source, claims and event history cannot be deleted');
 d:=to_jsonb(NEW);
 IF TG_TABLE_NAME='manufacturing_supply_plans' THEN p:=NEW;ELSE
 SELECT * INTO p FROM reconforge.manufacturing_supply_plans WHERE tenant_id=NEW.tenant_id AND id=NEW.plan_id;END IF;
 permission:='manufacturing_supply_plan.'||CASE WHEN op IN('approve','cancel','source-open-rfq','source-review-selection','source-cancel',
 'purchase-approve','receive-review','invoice-approve','invoice-review') THEN'approve'
 WHEN op IN('source-award','receive-commit','invoice-post') THEN'post' ELSE'manage' END;
 PERFORM reconforge.msp_assert(op IN('create','approve','cancel','handoff','source-create','source-open-rfq','source-quote','source-review-selection',
 'source-award','source-cancel','purchase-submit','purchase-approve','receive-prepare','receive-review','receive-commit','invoice-match','invoice-approve','invoice-prepare','invoice-review','invoice-post')
 AND reconforge.sales_revenue_actor(NEW.tenant_id,a,permission),'Planning writes require the exact current persisted human operation');
 PERFORM 1 FROM reconforge.principal_scope_grants WHERE tenant_id=NEW.tenant_id AND principal_type='user' AND principal_id=a AND revoked_at IS NULL
 AND((scope_type='workspace' AND scope_id=p.workspace_id) OR(scope_type='organization' AND scope_id=p.organization_id)
 OR(scope_type='legal_entity' AND scope_id=p.legal_entity_id)) FOR SHARE;
 PERFORM reconforge.msp_assert((SELECT count(DISTINCT(scope_type,scope_id))=3 FROM reconforge.principal_scope_grants
 WHERE tenant_id=NEW.tenant_id AND principal_type='user' AND principal_id=a AND revoked_at IS NULL
 AND((scope_type='workspace' AND scope_id=p.workspace_id) OR(scope_type='organization' AND scope_id=p.organization_id)
 OR(scope_type='legal_entity' AND scope_id=p.legal_entity_id))),'Planning writes require all current persisted original parent grants');
 PERFORM 1 FROM reconforge.fiscal_periods WHERE tenant_id=NEW.tenant_id AND id=p.payload->>'period_id' FOR SHARE;
 PERFORM reconforge.msp_assert(EXISTS(SELECT 1 FROM reconforge.fiscal_periods WHERE tenant_id=NEW.tenant_id AND id=p.payload->>'period_id'
 AND application_workspace_id=p.workspace_id AND status='Open' AND(p.payload->>'posting_date')::date BETWEEN start_date AND end_date),
 'Every new planning command requires its current scoped open period');
 IF TG_OP='INSERT' THEN
 IF TG_TABLE_NAME='manufacturing_supply_plans' THEN
 PERFORM reconforge.msp_assert(op='create' AND NEW.phase=0 AND NEW.row_version=1 AND NEW.creator_actor_id=a
 AND NEW.reviewer_actor_id IS NULL AND NEW.material_order_id IS NULL AND NEW.manufacturing_order_id IS NULL,'Planner starts with actual unapproved source only');
 ELSIF TG_TABLE_NAME IN('manufacturing_supply_commands','manufacturing_supply_events') THEN
 PERFORM reconforge.msp_assert(NEW.actor_id=a AND NEW.operation=op AND NEW.version=p.row_version,'Evidence must identify the same current actor, command and source version');
 ELSIF TG_TABLE_NAME='manufacturing_supply_stock_releases' THEN
 PERFORM reconforge.msp_assert(NEW.actor_id=a AND op=CASE NEW.purpose WHEN'Handoff' THEN'handoff' ELSE'cancel' END,'Release needs actual authorized source disposition');
 END IF;RETURN NEW;END IF;
 IF TG_TABLE_NAME='manufacturing_supply_plans' THEN allowed:=ARRAY['phase','row_version','reviewer_actor_id','material_order_id','manufacturing_order_id'];
 PERFORM reconforge.msp_assert(NEW.row_version=OLD.row_version+1 AND((op='approve' AND OLD.phase=0 AND NEW.phase=1 AND NEW.reviewer_actor_id=a AND a<>OLD.creator_actor_id)
 OR(op='cancel' AND OLD.phase IN(0,1) AND NEW.phase=3) OR(op='handoff' AND OLD.phase=1 AND NEW.phase=2)
 OR(op LIKE'source-%' OR op LIKE'purchase-%' OR op LIKE'receive-%' OR op LIKE'invoice-%') AND OLD.phase=1 AND NEW.phase=1),
 'Planning phase and exact version cannot skip source governance or regress');
 PERFORM reconforge.msp_assert(OLD.reviewer_actor_id IS NULL OR NEW.reviewer_actor_id=OLD.reviewer_actor_id,'Independent original approval remains immutable');
 ELSIF TG_TABLE_NAME='manufacturing_supply_requirements' THEN allowed:=ARRAY['onhand_reserved_scaled','shortage_quantity_scaled','coverage_json','coverage_digest'];
 PERFORM reconforge.msp_assert(op='approve' AND OLD.coverage_json IS NULL AND NEW.coverage_json IS NOT NULL,'Original net coverage freezes exactly once at approval');
 ELSIF TG_TABLE_NAME IN('manufacturing_supply_stock_claims','manufacturing_supply_procurement_claims') THEN allowed:=ARRAY['state'];
 PERFORM reconforge.msp_assert(OLD.state='Active' AND NEW.state IN('Released','HandedOff'),'Source custody disposition is terminal');
 ELSE PERFORM reconforge.msp_assert(FALSE,'Planning evidence and release history is immutable');END IF;
 PERFORM reconforge.msp_assert((to_jsonb(NEW)-allowed) IS NOT DISTINCT FROM(to_jsonb(OLD)-allowed),'Original engineering/supply source and quantity custody cannot be rewritten');RETURN NEW;
END $msp$;
CREATE FUNCTION reconforge.msp_procurement_close(t TEXT,i TEXT) RETURNS VOID LANGUAGE plpgsql SET search_path=pg_catalog AS $msp$
DECLARE source RECORD;p RECORD;r RECORD;c RECORD;line JSONB;master JSONB;expected JSONB;
BEGIN
 SELECT * INTO source FROM reconforge.procurement_sourcing_requisitions WHERE tenant_id=t AND id=i;
 PERFORM reconforge.msp_assert(source.id IS NOT NULL AND source.number~'^SRC5-MSP-[A-F0-9]{16}$'
 AND(SELECT count(DISTINCT plan_id) FROM reconforge.manufacturing_supply_procurement_claims WHERE tenant_id=t AND requisition_id=i)=1,
 'Every planned source requires one actual owning pre-stock plan');
 SELECT plan.* INTO p FROM reconforge.manufacturing_supply_plans plan JOIN reconforge.manufacturing_supply_procurement_claims claim
 ON claim.tenant_id=plan.tenant_id AND claim.plan_id=plan.id WHERE claim.tenant_id=t AND claim.requisition_id=i LIMIT 1;
 PERFORM reconforge.msp_assert(p.reviewer_actor_id IS NOT NULL AND p.phase IN(1,2,3)
 AND(source.workspace_id,source.organization_id,source.legal_entity_id,source.budget_id)=(p.workspace_id,p.organization_id,p.legal_entity_id,p.budget_id)
 AND(SELECT count(*) FROM reconforge.manufacturing_supply_procurement_claims WHERE tenant_id=t AND requisition_id=i)
 =jsonb_array_length(source.payload->'request'->'order'->'lines')
 AND NOT EXISTS(SELECT 1 FROM jsonb_array_elements(source.payload->'request'->'requirements') reference WHERE reference<>'null'::jsonb),
 'Versioned planned companion preserves ordinary SRC1 source format and exact complete line population');
 PERFORM reconforge.ps_close(t,i);
 FOR c IN SELECT * FROM reconforge.manufacturing_supply_procurement_claims WHERE tenant_id=t AND requisition_id=i ORDER BY source_line LOOP
 SELECT * INTO r FROM reconforge.manufacturing_supply_requirements WHERE tenant_id=t AND id=c.requirement_id;
 line:=source.payload->'request'->'order'->'lines'->(c.source_line-1);master:=source.payload->'demand_masters'->(c.source_line-1);
 expected:=jsonb_build_object('schema_version','manufacturing-planned-origin-v2','id',c.id,'plan_id',p.id,'plan_digest',p.source_digest,
 'requirement_id',r.id,'requirement_digest',r.source_digest,'coverage_digest',r.coverage_digest,'requisition_id',source.id,
 'source_line',c.source_line,'quantity_scaled',c.quantity_scaled,'scope',jsonb_build_object('workspace_id',p.workspace_id,
 'organization_id',p.organization_id,'legal_entity_id',p.legal_entity_id),'item_id',r.item_id,'uom_id',r.uom_id,
 'quantity_precision',r.quantity_precision,'location_id',r.location_id);
 PERFORM reconforge.msp_assert(c.payload=expected AND reconforge.irp_digest(c.payload)=c.source_digest AND c.plan_id=p.id
 AND r.plan_id=p.id AND c.quantity_scaled<=r.shortage_quantity_scaled
 AND(line->>'quantity')::numeric*power(10::numeric,r.quantity_precision)=c.quantity_scaled
 AND line->>'item_code'=r.payload->>'item_code' AND(master->>'item_id',master->>'uom_id',master->>'location_id')=(r.item_id,r.uom_id,r.location_id)
 AND(master->>'quantity_precision')::integer=r.quantity_precision
 AND(line->>'unit_price_minor')::numeric=(p.payload->'unit_price_ceilings_minor'->>(r.payload->>'item_code'))::numeric
 AND EXISTS(SELECT 1 FROM reconforge.manufacturing_supply_commands command WHERE command.tenant_id=t AND command.plan_id=p.id
 AND command.version=c.created_version AND command.operation='source-create' AND command.native_kind='SRC' AND command.native_owner_id=i)
 AND c.state=CASE WHEN source.phase=4 THEN'Released' WHEN p.phase=2 THEN'HandedOff' ELSE'Active' END,
 'Source companion requires exact approved net-demand quantity, scope, item/UOM and immutable price ceiling');
 END LOOP;
 IF source.phase=3 THEN PERFORM reconforge.msp_purchase_close(t,source.order_id);END IF;
 PERFORM reconforge.msp_assert(NOT EXISTS(SELECT 1 FROM reconforge.procurement_sourcing_commands native
 WHERE native.tenant_id=t AND native.requisition_id=i AND NOT EXISTS(SELECT 1 FROM reconforge.manufacturing_supply_commands owner
 WHERE owner.tenant_id=t AND owner.plan_id=p.id AND owner.native_kind='SRC' AND owner.native_owner_id=i AND owner.native_command_id=native.command_id
 AND owner.actor_id=native.actor_id)),'All planned native sourcing history requires exact finite owner command custody');
END $msp$;
CREATE FUNCTION reconforge.msp_purchase_close(t TEXT,i TEXT) RETURNS VOID LANGUAGE plpgsql SET search_path=pg_catalog AS $msp$
DECLARE native RECORD;p RECORD;r RECORD;c RECORD;
BEGIN
 SELECT * INTO native FROM reconforge.procurement_partial_orders WHERE tenant_id=t AND id=i;
 SELECT plan.* INTO p FROM reconforge.manufacturing_supply_plans plan JOIN reconforge.manufacturing_supply_procurement_claims claim
 ON claim.tenant_id=plan.tenant_id AND claim.plan_id=plan.id JOIN reconforge.procurement_sourcing_requisitions source
 ON source.tenant_id=claim.tenant_id AND source.id=claim.requisition_id WHERE source.tenant_id=t AND source.order_id=i AND source.phase=3 LIMIT 1;
 PERFORM reconforge.msp_assert(native.id IS NOT NULL AND p.id IS NOT NULL AND native.number~'^BPC1-SRC5-MSP-[A-F0-9]{16}$'
 AND(native.workspace_id,native.organization_id,native.legal_entity_id)=(p.workspace_id,p.organization_id,p.legal_entity_id),
 'Planned purchase progression requires its exact awarded original shortage source');
 PERFORM reconforge.pp_verify_order(t,i);PERFORM reconforge.pc_close(t,i);
 FOR r IN SELECT receipt.*,claim.requirement_id,requirement.quantity_precision FROM reconforge.procurement_partial_receipts receipt
 JOIN reconforge.procurement_partial_order_lines line ON line.tenant_id=receipt.tenant_id AND line.id=receipt.order_line_id
 JOIN reconforge.procurement_sourcing_requisitions source ON source.tenant_id=line.tenant_id AND source.order_id=line.order_id
 JOIN reconforge.manufacturing_supply_procurement_claims claim ON claim.tenant_id=source.tenant_id AND claim.requisition_id=source.id AND claim.source_line=line.sequence
 JOIN reconforge.manufacturing_supply_requirements requirement ON requirement.tenant_id=claim.tenant_id AND requirement.id=claim.requirement_id
 WHERE receipt.tenant_id=t AND receipt.order_id=i LOOP
 PERFORM reconforge.msp_assert((SELECT count(*) FROM reconforge.manufacturing_supply_stock_claims stock WHERE stock.tenant_id=t
 AND stock.native_receipt_plan_id=r.receipt_plan_id)=CASE WHEN r.stage=2 THEN 1 ELSE 0 END,
 'Only actually committed original purchase receipts create exactly one source-owned stock claim');
 IF r.stage=2 THEN
 SELECT * INTO c FROM reconforge.manufacturing_supply_stock_claims WHERE tenant_id=t AND native_receipt_plan_id=r.receipt_plan_id;
 PERFORM reconforge.msp_assert(c.plan_id=p.id AND c.requirement_id=r.requirement_id AND c.origin='Receipt'
 AND c.quantity_scaled=r.quantity*power(10::numeric,r.quantity_precision)
 AND EXISTS(SELECT 1 FROM reconforge.manufacturing_supply_commands owner JOIN reconforge.procurement_partial_commands command
 ON command.tenant_id=owner.tenant_id AND command.order_id=owner.native_owner_id AND command.command_id=owner.native_command_id
 WHERE owner.tenant_id=t AND owner.plan_id=p.id AND owner.version=c.created_version AND owner.operation='receive-commit'
 AND owner.native_kind='PP' AND command.order_id=i AND command.request_json->>'document_id'=r.id),
 'Each received claim retains its exact original native receipt, quantity and owner command');END IF;
 END LOOP;
 PERFORM reconforge.msp_assert(NOT EXISTS(SELECT 1 FROM reconforge.procurement_partial_commands command WHERE command.tenant_id=t AND command.order_id=i
 AND command.operation<>'create' AND NOT EXISTS(SELECT 1 FROM reconforge.manufacturing_supply_commands owner WHERE owner.tenant_id=t AND owner.plan_id=p.id
 AND owner.native_owner_id=i AND((owner.native_kind='PP' AND owner.native_command_id=command.command_id) OR(owner.native_kind='BPC'
 AND EXISTS(SELECT 1 FROM reconforge.procurement_commitment_commands budget WHERE budget.tenant_id=t AND budget.order_id=i
 AND budget.command_id=owner.native_command_id AND budget.order_version=command.order_version AND budget.operation='consume'))))),
 'Every actual planned receipt/AP progression has one complete retained owner command');
END $msp$;
CREATE FUNCTION reconforge.msp_handoff_ready(t TEXT,i TEXT) RETURNS VOID LANGUAGE plpgsql SET search_path=pg_catalog AS $msp$
BEGIN
 PERFORM reconforge.msp_assert(NOT EXISTS(SELECT 1 FROM reconforge.manufacturing_supply_procurement_claims claim
 JOIN reconforge.procurement_sourcing_requisitions source ON source.tenant_id=claim.tenant_id AND source.id=claim.requisition_id
 JOIN reconforge.procurement_partial_order_lines line ON line.tenant_id=source.tenant_id AND line.order_id=source.order_id AND line.sequence=claim.source_line
 WHERE claim.tenant_id=t AND claim.plan_id=i AND claim.state<>'Released' AND(source.phase<>3
 OR claim.quantity_scaled<>(SELECT COALESCE(sum(stock.quantity_scaled),0) FROM reconforge.manufacturing_supply_stock_claims stock
 JOIN reconforge.procurement_partial_receipts receipt ON receipt.tenant_id=stock.tenant_id AND receipt.receipt_plan_id=stock.native_receipt_plan_id
 WHERE stock.tenant_id=t AND stock.plan_id=i AND stock.requirement_id=claim.requirement_id AND receipt.order_line_id=line.id)
 OR line.quantity<>(SELECT COALESCE(sum(allocation.quantity),0) FROM reconforge.procurement_partial_invoice_lines allocation
 JOIN reconforge.procurement_partial_invoices invoice ON invoice.tenant_id=allocation.tenant_id AND invoice.id=allocation.invoice_id
 WHERE allocation.tenant_id=t AND allocation.order_line_id=line.id AND invoice.stage=4))),
 'Handoff requires full actual receipt and independently accrued AP/budget consumption of every awarded shortage');
END $msp$;
CREATE FUNCTION reconforge.msp_material_handoff() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $msp$
DECLARE owner_id TEXT:=current_setting('app.manufacturing_supply_handoff_plan_id',true);p RECORD;c RECORD;
 a TEXT:=current_setting('app.manufacturing_supply_actor_id',true);reason TEXT:=current_setting('app.manufacturing_supply_handoff_reason',true);release_id TEXT;
BEGIN
 IF owner_id IS NULL OR owner_id='' THEN RETURN NEW;END IF;
 SELECT * INTO p FROM reconforge.manufacturing_supply_plans WHERE tenant_id=NEW.tenant_id AND id=owner_id FOR UPDATE;
 PERFORM reconforge.msp_assert(p.id IS NOT NULL AND p.phase=1 AND current_setting('app.manufacturing_supply_operation',true)='handoff'
 AND reconforge.sales_revenue_actor(NEW.tenant_id,a,'manufacturing_supply_plan.manage') AND NEW.execution_owner_id IS NOT NULL
 AND (NEW.payload->'command_request')-'posting_date'=(p.payload->'command_request'->'material')-'posting_date'
 AND(NEW.workspace_id,NEW.organization_id,NEW.legal_entity_id)=(p.workspace_id,p.organization_id,p.legal_entity_id)
 AND(NEW.payload->>'posting_date')::date>=(p.payload->>'posting_date')::date
 AND NOT EXISTS(SELECT 1 FROM reconforge.procurement_partial_receipts receipt JOIN reconforge.manufacturing_supply_stock_claims stock
 ON stock.tenant_id=receipt.tenant_id AND stock.native_receipt_plan_id=receipt.receipt_plan_id WHERE stock.tenant_id=NEW.tenant_id
 AND stock.plan_id=p.id AND receipt.posting_date>(NEW.payload->>'posting_date')::date),
 'Native material transfer requires the exact approved source, live human and forward actual production date');
 PERFORM reconforge.msp_handoff_ready(NEW.tenant_id,p.id);
 FOR c IN SELECT * FROM reconforge.manufacturing_supply_stock_claims WHERE tenant_id=NEW.tenant_id AND plan_id=p.id AND state='Active' ORDER BY id LOOP
 release_id:='MSP1X-'||upper(substr(reconforge.irp_digest(jsonb_build_array(p.id,c.id,NEW.id)),1,32));
 INSERT INTO reconforge.manufacturing_supply_stock_releases(tenant_id,id,plan_id,claim_id,workspace_id,organization_id,legal_entity_id,
 purpose,target_material_order_id,actor_id,reason,created_version) VALUES(NEW.tenant_id,release_id,p.id,c.id,p.workspace_id,p.organization_id,p.legal_entity_id,
 'Handoff',NEW.id,a,reason,p.row_version+1);
 INSERT INTO reconforge.inventory_quantity_source_releases(tenant_id,guard_id,release_id) VALUES(NEW.tenant_id,c.id,release_id);
 UPDATE reconforge.manufacturing_supply_stock_claims SET state='HandedOff' WHERE tenant_id=NEW.tenant_id AND id=c.id;
 END LOOP;
 RETURN NEW;
END $msp$;
CREATE TRIGGER manufacturing_supply_material_handoff AFTER INSERT ON reconforge.manufacturing_execution_orders
 FOR EACH ROW EXECUTE FUNCTION reconforge.msp_material_handoff();
CREATE FUNCTION reconforge.msp_close(t TEXT,i TEXT) RETURNS VOID LANGUAGE plpgsql SET search_path=pg_catalog AS $msp$
DECLARE p RECORD;b RECORD;route RECORD;r RECORD;c RECORD;e RECORD;x JSONB;expected JSONB;coverage JSONB;current JSONB;
 v INTEGER;onhand NUMERIC;received NUMERIC;claimed NUMERIC;sequence INTEGER:=0;original_request JSONB;field TEXT;ceiling NUMERIC:=0;product NUMERIC;
BEGIN
 SELECT * INTO p FROM reconforge.manufacturing_supply_plans WHERE tenant_id=t AND id=i;
 PERFORM reconforge.msp_assert(p.id IS NOT NULL AND reconforge.irp_scope(t,p.workspace_id,p.organization_id,p.legal_entity_id)
 AND reconforge.irp_digest(p.payload)=p.source_digest AND p.payload->>'schema_version'='manufacturing-supply-plan-v1'
 AND(p.payload->>'id',p.payload->>'workspace_id',p.payload->>'organization_id',p.payload->>'legal_entity_id',p.payload->>'bom_version_id',
 p.payload->>'routing_id',p.payload->>'budget_id',p.payload->>'number',p.payload->>'creator_id')
 =(p.id,p.workspace_id,p.organization_id,p.legal_entity_id,p.bom_version_id,p.routing_id,p.budget_id,p.number,p.creator_actor_id),
 'Planning must retain its canonical original hierarchy and engineering request');
 original_request:=p.payload->'command_request';
 PERFORM reconforge.msp_assert(original_request->>'schema_version'='manufacturing-supply-plan-v1'
 AND original_request->>'routing_id'=p.routing_id AND original_request->>'budget_id'=p.budget_id
 AND original_request->'unit_price_ceilings_minor'=p.payload->'unit_price_ceilings_minor'
 AND original_request->'material'->>'schema_version'='manufacturing-order-v1'
 AND reconforge.me2_integer(p.payload->'ceiling_minor') AND(p.payload->>'ceiling_minor')::numeric>0
 AND reconforge.me2_integer(p.payload->'monetary_policy'->'precision'),'Original typed request must reproduce retained source and monetary burden');
 FOREACH field IN ARRAY ARRAY['number','bom_version_id','output_quantity','component_location_code','finished_location_code',
 'component_policy_code','finished_policy_code','journal_code','wip_account_code','scrap_account_code','period_id','posting_date',
 'workspace_id','organization_id','legal_entity_id','organization_code','entity_code','reason'] LOOP
 PERFORM reconforge.msp_assert(original_request->'material'->field=p.payload->field,'Original planning field differs from its maker command');END LOOP;
 PERFORM reconforge.msp_assert(EXISTS(SELECT 1 FROM reconforge.budget_envelopes budget WHERE budget.tenant_id=t AND budget.id=p.budget_id
 AND(budget.workspace_id,budget.organization_id,budget.legal_entity_id,budget.period_id,budget.currency_code,budget.status)
 =(p.workspace_id,p.organization_id,p.legal_entity_id,p.payload->>'period_id',p.payload->>'currency_code','Approved')
 AND to_jsonb(budget)->'currency_precision'=p.payload->'monetary_policy'->'precision'
 AND to_jsonb(budget)->'currency_rounding_policy'=p.payload->'monetary_policy'->'rounding_policy'
 AND to_jsonb(budget)->'currency_registry_version'=p.payload->'monetary_policy'->'registry_version'
 AND to_jsonb(budget)->'currency_registry_digest'=p.payload->'monetary_policy'->'registry_digest'),
 'Original pre-stock demand binds its actual approved native budget hierarchy and complete monetary policy');
 SELECT * INTO b FROM reconforge.manufacturing_execution_boms WHERE tenant_id=t AND id=p.bom_version_id;
 SELECT * INTO route FROM reconforge.manufacturing_execution_v2_definitions WHERE tenant_id=t AND id=p.routing_id;
 PERFORM reconforge.msp_assert(b.id IS NOT NULL AND b.phase=1 AND b.source_digest=p.payload->>'bom_digest' AND route.id IS NOT NULL
 AND route.kind='Routing' AND route.phase=1 AND route.source_digest=p.payload->>'routing_digest' AND route.payload->>'bom_version_id'=b.id
 AND(route.workspace_id,route.organization_id,route.legal_entity_id)=(p.workspace_id,p.organization_id,p.legal_entity_id)
 AND(route.payload->>'effective_from')::date<=(p.payload->>'posting_date')::date
 AND(route.payload->>'effective_until')::date>=(p.payload->>'posting_date')::date,'Pre-stock demand requires actual effective approved BOM and routing');
 PERFORM reconforge.me1_close(t,b.id);PERFORM reconforge.me2_close(t,route.id);
 PERFORM reconforge.msp_assert((SELECT count(*) FROM reconforge.manufacturing_supply_commands WHERE tenant_id=t AND plan_id=i)=p.row_version
 AND(SELECT count(*) FROM reconforge.manufacturing_supply_events WHERE tenant_id=t AND plan_id=i)=p.row_version,
 'All planning events and original ACKs form a complete versioned bijection');
 FOR v IN 1..p.row_version LOOP PERFORM reconforge.msp_evidence(t,i,v);END LOOP;
 PERFORM reconforge.msp_assert(reconforge.msp_evidence(t,i,1)=p.creator_actor_id
 AND EXISTS(SELECT 1 FROM reconforge.manufacturing_supply_events WHERE tenant_id=t AND plan_id=i AND version=1 AND operation='create'),
 'Planning starts with one original maker command');
 current:=reconforge.msp_public(t,i,p.row_version);
 PERFORM reconforge.msp_assert((current->>'phase')::integer=p.phase AND current->>'reviewer_actor_id' IS NOT DISTINCT FROM p.reviewer_actor_id
 AND(p.reviewer_actor_id IS NULL OR p.reviewer_actor_id<>p.creator_actor_id),'Current owner phase exactly follows immutable approval/disposition history');
 PERFORM reconforge.msp_assert((SELECT count(*) FROM reconforge.manufacturing_supply_requirements WHERE tenant_id=t AND plan_id=i)
 =jsonb_array_length(p.payload->'requirements') AND jsonb_array_length(p.payload->'requirements')=jsonb_array_length(b.payload->'components'),
 'Every original BOM line has exactly one complete planned requirement');
 FOR x IN SELECT value FROM jsonb_array_elements(p.payload->'requirements') WITH ORDINALITY q(value,n) ORDER BY n LOOP
 sequence:=sequence+1;
 SELECT * INTO r FROM reconforge.manufacturing_supply_requirements WHERE tenant_id=t AND id=x->>'requirement_id';
 expected:=jsonb_build_object('schema_version','manufacturing-planned-requirement-v1','id',r.id,'plan_id',p.id,'plan_digest',p.source_digest,
 'bom_version_id',b.id,'bom_digest',b.source_digest,'routing_id',route.id,'routing_digest',route.source_digest,
 'scope',jsonb_build_object('workspace_id',p.workspace_id,'organization_id',p.organization_id,'legal_entity_id',p.legal_entity_id),
 'sequence',r.sequence,'location_id',p.payload->>'component_location_id','item_id',x->>'item_id','item_code',x->>'item_code',
 'uom_id',x->>'uom_id','uom_code',x->>'uom_code','quantity_precision',x->'quantity_precision','inventory_account_id',x->>'inventory_account_id',
 'gross_quantity_scaled',x->'required_quantity_scaled','gross_quantity',x->>'required_quantity');
 PERFORM reconforge.msp_assert(r.id IS NOT NULL AND r.sequence=sequence AND reconforge.me2_integer(x->'required_quantity_scaled')
 AND reconforge.me2_integer(x->'quantity_precision') AND reconforge.me2_integer(p.payload->'output_quantity_scaled')
 AND reconforge.me2_integer(p.payload->'unit_price_ceilings_minor'->(x->>'item_code'))
 AND(p.payload->'unit_price_ceilings_minor'->>(x->>'item_code'))::numeric>0
 AND(r.plan_id,r.workspace_id,r.organization_id,r.legal_entity_id,r.item_id,r.uom_id,r.location_id,
 r.quantity_precision,r.gross_quantity_scaled)=(p.id,p.workspace_id,p.organization_id,p.legal_entity_id,x->>'item_id',x->>'uom_id',p.payload->>'component_location_id',
 (x->>'quantity_precision')::integer,(x->>'required_quantity_scaled')::bigint) AND r.payload=expected AND reconforge.irp_digest(r.payload)=r.source_digest
 AND EXISTS(SELECT 1 FROM jsonb_array_elements(b.payload->'components') component WHERE component=x-ARRAY['requirement_id','required_quantity','required_quantity_scaled']
 AND(component->>'quantity_scaled')::numeric*(p.payload->>'output_quantity_scaled')::numeric=r.gross_quantity_scaled::numeric*(b.payload->>'output_quantity_scaled')::numeric),
 'Planned requirement must exactly reconstruct original typed BOM/UOM/quantity and source identity');
 product:=r.gross_quantity_scaled::numeric*(p.payload->'unit_price_ceilings_minor'->>(x->>'item_code'))::numeric;
 PERFORM reconforge.msp_assert(mod(product,power(10::numeric,r.quantity_precision))=0,'Original native unit price and gross quantity require exact minor money');
 ceiling:=ceiling+product/power(10::numeric,r.quantity_precision);
 PERFORM reconforge.msp_assert(EXISTS(SELECT 1 FROM reconforge.inventory_items item JOIN reconforge.inventory_units_of_measure unit
 ON unit.tenant_id=item.tenant_id AND unit.id=item.uom_id WHERE item.tenant_id=t AND item.id=r.item_id AND item.item_code=x->>'item_code'
 AND item.workspace_id=p.workspace_id AND(item.organization_id IS NULL OR item.organization_id=p.organization_id)
 AND item.item_type IN('Stock','Consumable') AND item.tracking_mode='None' AND item.uom_id=r.uom_id AND unit.decimal_places=r.quantity_precision
 AND unit.uom_code=x->>'uom_code' AND item.inventory_account_id=x->>'inventory_account_id'),
 'Even pre-stock demand must preserve actual native item/UOM/precision/account interpretation');
 IF p.reviewer_actor_id IS NULL THEN PERFORM reconforge.msp_assert(r.coverage_json IS NULL AND NOT EXISTS(
 SELECT 1 FROM reconforge.manufacturing_supply_stock_claims WHERE tenant_id=t AND requirement_id=r.id),
 'Unapproved planning cannot claim physical or FIFO quantities');
 ELSE
 coverage:=r.coverage_json;
 PERFORM reconforge.msp_assert(coverage IS NOT NULL AND reconforge.irp_digest(coverage)=r.coverage_digest
 AND coverage-ARRAY['observed_available_scaled','observed_reserved_scaled','observed_fifo_free_scaled','onhand_reserved_scaled','shortage_quantity_scaled']
 =jsonb_build_object('schema_version','manufacturing-supply-coverage-v1','requirement_id',r.id,'requirement_digest',r.source_digest,'gross_quantity_scaled',r.gross_quantity_scaled)
 AND reconforge.me2_integer(coverage->'observed_available_scaled') AND reconforge.me2_integer(coverage->'observed_reserved_scaled')
 AND reconforge.me2_integer(coverage->'observed_fifo_free_scaled') AND reconforge.me2_integer(coverage->'onhand_reserved_scaled')
 AND reconforge.me2_integer(coverage->'shortage_quantity_scaled') AND(coverage->>'onhand_reserved_scaled')::numeric=r.onhand_reserved_scaled
 AND(coverage->>'shortage_quantity_scaled')::numeric=r.shortage_quantity_scaled
 AND(coverage->>'observed_reserved_scaled')::numeric<=(coverage->>'observed_available_scaled')::numeric
 AND r.onhand_reserved_scaled=least(r.gross_quantity_scaled::numeric,(coverage->>'observed_available_scaled')::numeric-(coverage->>'observed_reserved_scaled')::numeric,
 (coverage->>'observed_fifo_free_scaled')::numeric),'Approval retains exact independent physical and valued FIFO coverage observations');
 SELECT COALESCE(sum(quantity_scaled),0) INTO onhand FROM reconforge.manufacturing_supply_stock_claims WHERE tenant_id=t AND requirement_id=r.id AND origin='OnHand';
 PERFORM reconforge.msp_assert(onhand=r.onhand_reserved_scaled,'Original exclusive on-hand claim must equal frozen approved coverage');END IF;
 SELECT COALESCE(sum(quantity_scaled),0) INTO claimed FROM reconforge.manufacturing_supply_procurement_claims
 WHERE tenant_id=t AND requirement_id=r.id AND state<>'Released';
 PERFORM reconforge.msp_assert(claimed<=COALESCE(r.shortage_quantity_scaled,0),'Cumulative requisitions cannot duplicate the original net shortage');
 FOR c IN SELECT DISTINCT requisition_id FROM reconforge.manufacturing_supply_procurement_claims WHERE tenant_id=t AND requirement_id=r.id LOOP
 PERFORM reconforge.msp_procurement_close(t,c.requisition_id);END LOOP;
 FOR c IN SELECT * FROM reconforge.manufacturing_supply_stock_claims WHERE tenant_id=t AND requirement_id=r.id LOOP
 PERFORM reconforge.msp_assert((c.item_id,c.uom_id,c.quantity_precision,c.location_id,c.workspace_id,c.organization_id,c.legal_entity_id)
 =(r.item_id,r.uom_id,r.quantity_precision,r.location_id,p.workspace_id,p.organization_id,p.legal_entity_id)
 AND EXISTS(SELECT 1 FROM reconforge.inventory_quantity_source_guards guard WHERE guard.tenant_id=t AND guard.id=c.id
 AND guard.owner_namespace='MSP1' AND guard.owner_claim_id=c.id AND(guard.workspace_id,guard.organization_id,guard.legal_entity_id,guard.item_id,guard.uom_id,
 guard.quantity_precision,guard.location_id,guard.quantity_scaled,guard.source_receipt_plan_id)
 IS NOT DISTINCT FROM(c.workspace_id,c.organization_id,c.legal_entity_id,c.item_id,c.uom_id,c.quantity_precision,c.location_id,c.quantity_scaled,c.native_receipt_plan_id)),
 'All actual stock custody has a complete bijective scoped Core guard');
 PERFORM reconforge.msp_assert(c.created_version<=p.row_version AND c.state=CASE p.phase WHEN 2 THEN'HandedOff' WHEN 3 THEN'Released' ELSE'Active' END,
 'Actual stock disposition must equal the complete retained planning phase, never a detached native insert');
 PERFORM reconforge.msp_assert(NOT EXISTS(SELECT 1 FROM reconforge.manufacturing_supply_stock_releases release
 WHERE release.tenant_id=t AND release.claim_id=c.id AND NOT EXISTS(SELECT 1 FROM reconforge.manufacturing_supply_events event
 WHERE event.tenant_id=t AND event.plan_id=i AND event.version=release.created_version AND event.actor_id=release.actor_id
 AND event.reason=release.reason AND event.operation=CASE release.purpose WHEN'Handoff' THEN'handoff' ELSE'cancel' END)),
 'Every immutable stock release requires its exact actual terminal owner command');
 IF c.origin='OnHand' THEN PERFORM reconforge.msp_assert(c.created_version=2 AND c.quantity_scaled=r.onhand_reserved_scaled,'Approval alone creates exact on-hand custody');END IF;
 IF c.origin='Receipt' THEN
 PERFORM reconforge.msp_assert(EXISTS(SELECT 1 FROM reconforge.procurement_partial_receipts receipt
 JOIN reconforge.procurement_partial_order_lines line ON line.tenant_id=receipt.tenant_id AND line.id=receipt.order_line_id
 JOIN reconforge.procurement_sourcing_requisitions source ON source.tenant_id=line.tenant_id AND source.order_id=line.order_id
 JOIN reconforge.manufacturing_supply_procurement_claims claim ON claim.tenant_id=source.tenant_id AND claim.requisition_id=source.id
 AND claim.source_line=line.sequence WHERE receipt.tenant_id=t AND receipt.receipt_plan_id=c.native_receipt_plan_id
 AND receipt.stage=2 AND claim.plan_id=i AND claim.requirement_id=r.id AND c.quantity_scaled=receipt.quantity*power(10::numeric,r.quantity_precision)),
 'Received custody cannot be invented from unrelated posted stock or another requirement');END IF;
 PERFORM reconforge.msp_assert((c.state='Active')=NOT EXISTS(SELECT 1 FROM reconforge.manufacturing_supply_stock_releases release
 WHERE release.tenant_id=t AND release.claim_id=c.id),'Active custody cannot be released or invented without immutable disposition');
 END LOOP;
 IF p.phase=2 THEN
 SELECT COALESCE(sum(quantity_scaled),0) INTO received FROM reconforge.manufacturing_supply_stock_claims WHERE tenant_id=t AND requirement_id=r.id AND origin='Receipt';
 PERFORM reconforge.msp_assert(onhand+received=r.gross_quantity_scaled,'Handoff requires complete actual original demand coverage');END IF;
 PERFORM reconforge.inventory_quantity_check_capacity(t,p.workspace_id,p.legal_entity_id,r.item_id,r.location_id);
 PERFORM reconforge.inventory_quantity_free_fifo(t,p.workspace_id,p.legal_entity_id,r.item_id);
 END LOOP;
 PERFORM reconforge.msp_assert(p.phase<>3 OR NOT EXISTS(SELECT 1 FROM reconforge.manufacturing_supply_stock_claims WHERE tenant_id=t AND plan_id=i AND state='Active'),
 'Cancelled source retains its history and releases all original stock custody');
 PERFORM reconforge.msp_assert(p.phase<>3 OR NOT EXISTS(SELECT 1 FROM reconforge.manufacturing_supply_procurement_claims WHERE tenant_id=t AND plan_id=i AND state<>'Released'),
 'Cancel cannot discard an awarded or still active source procurement commitment');
 PERFORM reconforge.msp_assert((SELECT count(*) FROM jsonb_object_keys(p.payload->'unit_price_ceilings_minor'))
 =jsonb_array_length(p.payload->'requirements') AND ceiling=(p.payload->>'ceiling_minor')::numeric,
 'Price ceilings must cover exactly the complete native component population and monetary admission burden');
 IF p.phase=2 THEN
 PERFORM reconforge.msp_handoff_ready(t,i);
 PERFORM reconforge.msp_assert(EXISTS(SELECT 1 FROM reconforge.manufacturing_execution_orders material
 JOIN reconforge.manufacturing_execution_v2_orders production ON production.tenant_id=material.tenant_id AND production.material_order_id=material.id
 WHERE material.tenant_id=t AND material.id=p.material_order_id AND production.id=p.manufacturing_order_id
 AND (material.payload->'command_request')-'posting_date'=(p.payload->'command_request'->'material')-'posting_date'
 AND production.routing_id=p.routing_id AND production.payload->'command_request'->'material'=material.payload->'command_request'
 AND(material.payload->>'posting_date')::date>=(p.payload->>'posting_date')::date
 AND(material.workspace_id,material.organization_id,material.legal_entity_id)=(p.workspace_id,p.organization_id,p.legal_entity_id)
 AND production.payload->>'routing_digest'=p.payload->>'routing_digest'
 AND material.execution_owner_id=production.id), 'Handoff retains exactly the same native approved BOM, routing, request and hierarchy');
 PERFORM reconforge.msp_assert(NOT EXISTS(SELECT 1 FROM reconforge.manufacturing_supply_stock_claims stock
 LEFT JOIN reconforge.manufacturing_supply_stock_releases release ON release.tenant_id=stock.tenant_id AND release.claim_id=stock.id
 WHERE stock.tenant_id=t AND stock.plan_id=i AND(stock.state<>'HandedOff' OR release.purpose IS DISTINCT FROM'Handoff'
 OR release.target_material_order_id IS DISTINCT FROM p.material_order_id)),
 'All original stock claims hand off atomically into one exact native material order');
 PERFORM reconforge.me2_close(t,p.manufacturing_order_id);
 ELSE PERFORM reconforge.msp_assert(p.material_order_id IS NULL AND p.manufacturing_order_id IS NULL,
 'Unhanded planning cannot silently create a native manufacturing source');END IF;
END $msp$;
CREATE FUNCTION reconforge.msp_deferred_close() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $msp$
DECLARE parent_id TEXT;
BEGIN
 IF TG_TABLE_NAME='manufacturing_supply_plans' THEN parent_id:=NEW.id;ELSE parent_id:=NEW.plan_id;END IF;
 PERFORM reconforge.msp_close(NEW.tenant_id,parent_id);RETURN NEW;
END $msp$;
CREATE FUNCTION reconforge.msp_native_sourcing_close() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $msp$
DECLARE changed JSONB;identifier TEXT;number TEXT;owner_id TEXT;
BEGIN
 changed:=CASE WHEN TG_OP='DELETE' THEN to_jsonb(OLD) ELSE to_jsonb(NEW) END;
 IF TG_TABLE_NAME='procurement_sourcing_requisitions' THEN identifier:=changed->>'id';number:=changed->>'number';
 ELSE identifier:=changed->>'requisition_id';
 SELECT source.number INTO number FROM reconforge.procurement_sourcing_requisitions source WHERE source.tenant_id=changed->>'tenant_id' AND source.id=identifier;
 END IF;
 -- Existing native source metadata establishes relevance before ANY protected planner query.
 IF number IS NULL OR upper(number) NOT LIKE'SRC5-MSP-%' THEN
 IF TG_OP='DELETE' THEN RETURN OLD;END IF;RETURN NEW;END IF;
 PERFORM reconforge.msp_procurement_close(changed->>'tenant_id',identifier);
 SELECT claim.plan_id INTO owner_id FROM reconforge.manufacturing_supply_procurement_claims claim
 WHERE claim.tenant_id=changed->>'tenant_id' AND claim.requisition_id=identifier LIMIT 1;
 PERFORM reconforge.msp_close(changed->>'tenant_id',owner_id);
 IF TG_OP='DELETE' THEN RETURN OLD;END IF;RETURN NEW;
END $msp$;
CREATE FUNCTION reconforge.msp_native_purchase_close() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $msp$
DECLARE changed JSONB;identifier TEXT;number TEXT;owner_id TEXT;
BEGIN
 changed:=CASE WHEN TG_OP='DELETE' THEN to_jsonb(OLD) ELSE to_jsonb(NEW) END;
 identifier:=CASE WHEN TG_TABLE_NAME='procurement_partial_orders' THEN changed->>'id' ELSE changed->>'order_id' END;
 SELECT purchase.number INTO number FROM reconforge.procurement_partial_orders purchase WHERE purchase.tenant_id=changed->>'tenant_id' AND purchase.id=identifier;
 IF number IS NULL OR upper(number) NOT LIKE'BPC1-SRC5-MSP-%' THEN IF TG_OP='DELETE' THEN RETURN OLD;END IF;RETURN NEW;END IF;
 PERFORM reconforge.msp_purchase_close(changed->>'tenant_id',identifier);
 SELECT claim.plan_id INTO owner_id FROM reconforge.manufacturing_supply_procurement_claims claim
 JOIN reconforge.procurement_sourcing_requisitions source ON source.tenant_id=claim.tenant_id AND source.id=claim.requisition_id
 WHERE source.tenant_id=changed->>'tenant_id' AND source.order_id=identifier LIMIT 1;
 PERFORM reconforge.msp_close(changed->>'tenant_id',owner_id);
 IF TG_OP='DELETE' THEN RETURN OLD;END IF;RETURN NEW;
END $msp$;
DO $msp$ DECLARE n TEXT;BEGIN
 FOREACH n IN ARRAY ARRAY['manufacturing_supply_plans','manufacturing_supply_requirements','manufacturing_supply_stock_claims',
 'manufacturing_supply_stock_releases','manufacturing_supply_procurement_claims','manufacturing_supply_events','manufacturing_supply_commands'] LOOP
 EXECUTE format('ALTER TABLE reconforge.%I ENABLE ROW LEVEL SECURITY',n);EXECUTE format('ALTER TABLE reconforge.%I FORCE ROW LEVEL SECURITY',n);
 IF n IN('manufacturing_supply_events','manufacturing_supply_commands') THEN
 EXECUTE format('CREATE POLICY manufacturing_supply_scope ON reconforge.%I USING(reconforge.msp_visible(tenant_id,plan_id)) WITH CHECK(reconforge.msp_visible(tenant_id,plan_id))',n);
 ELSE EXECUTE format('CREATE POLICY manufacturing_supply_scope ON reconforge.%I USING(reconforge.irp_scope(tenant_id,workspace_id,organization_id,legal_entity_id)) WITH CHECK(reconforge.irp_scope(tenant_id,workspace_id,organization_id,legal_entity_id))',n);END IF;
 EXECUTE format('CREATE TRIGGER manufacturing_supply_protect BEFORE INSERT OR UPDATE OR DELETE ON reconforge.%I FOR EACH ROW EXECUTE FUNCTION reconforge.msp_protect()',n);
 EXECUTE format('CREATE CONSTRAINT TRIGGER manufacturing_supply_close AFTER INSERT OR UPDATE ON reconforge.%I DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION reconforge.msp_deferred_close()',n);
 END LOOP;
 FOREACH n IN ARRAY ARRAY['procurement_sourcing_requisitions','procurement_sourcing_quotes','procurement_sourcing_events','procurement_sourcing_commands'] LOOP
 EXECUTE format('CREATE CONSTRAINT TRIGGER manufacturing_supply_native_source AFTER INSERT OR UPDATE OR DELETE ON reconforge.%I DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION reconforge.msp_native_sourcing_close()',n);
 END LOOP;
 FOREACH n IN ARRAY ARRAY['procurement_partial_orders','procurement_partial_receipts','procurement_partial_invoices','procurement_partial_commands',
 'procurement_partial_order_lines','procurement_partial_invoice_lines','procurement_commitment_commands'] LOOP
 EXECUTE format('CREATE CONSTRAINT TRIGGER manufacturing_supply_native_purchase AFTER INSERT OR UPDATE OR DELETE ON reconforge.%I DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION reconforge.msp_native_purchase_close()',n);
 END LOOP;
END $msp$;
"""


def install_postgres_manufacturing_supply_plan_schema(connection: Any) -> None:
    """Install owned source before root-owned Core custody and deferred closure."""
    if not installed_manufacturing_supply_plan(connection):
        connection.execute(UPGRADE_SQL)


_DOWNGRADE_SQL = r"""
DO $msp$ BEGIN IF EXISTS(SELECT 1 FROM reconforge.manufacturing_supply_plans) THEN
 RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Retained manufacturing supply history requires a compatible populated rollback';END IF;END $msp$;
DO $msp$ DECLARE n TEXT;BEGIN FOREACH n IN ARRAY ARRAY['procurement_sourcing_requisitions','procurement_sourcing_quotes','procurement_sourcing_events','procurement_sourcing_commands'] LOOP
 EXECUTE format('DROP TRIGGER manufacturing_supply_native_source ON reconforge.%I',n);END LOOP;END $msp$;
DO $msp$ DECLARE n TEXT;BEGIN FOREACH n IN ARRAY ARRAY['procurement_partial_orders','procurement_partial_receipts','procurement_partial_invoices','procurement_partial_commands',
 'procurement_partial_order_lines','procurement_partial_invoice_lines','procurement_commitment_commands'] LOOP
 EXECUTE format('DROP TRIGGER manufacturing_supply_native_purchase ON reconforge.%I',n);END LOOP;END $msp$;
DROP TRIGGER manufacturing_supply_material_handoff ON reconforge.manufacturing_execution_orders;
DROP FUNCTION reconforge.msp_material_handoff();
DROP TABLE reconforge.manufacturing_supply_commands;
DROP TABLE reconforge.manufacturing_supply_events;
DROP TABLE reconforge.manufacturing_supply_stock_releases;
DROP TABLE reconforge.manufacturing_supply_stock_claims;
DROP TABLE reconforge.manufacturing_supply_procurement_claims;
DROP TABLE reconforge.manufacturing_supply_requirements;
DROP TABLE reconforge.manufacturing_supply_plans;
DROP FUNCTION reconforge.msp_deferred_close();
DROP FUNCTION reconforge.msp_native_sourcing_close();
DROP FUNCTION reconforge.msp_native_purchase_close();
DROP FUNCTION reconforge.msp_close(TEXT,TEXT);
DROP FUNCTION reconforge.msp_handoff_ready(TEXT,TEXT);
DROP FUNCTION reconforge.msp_purchase_close(TEXT,TEXT);
DROP FUNCTION reconforge.msp_procurement_close(TEXT,TEXT);
DROP FUNCTION reconforge.msp_protect();
DROP FUNCTION reconforge.msp_evidence(TEXT,TEXT,INTEGER);
DROP FUNCTION reconforge.msp_public(TEXT,TEXT,INTEGER);
DROP FUNCTION reconforge.msp_visible(TEXT,TEXT);
DROP FUNCTION reconforge.msp_assert(BOOLEAN,TEXT);
"""

TABLES_SQL = _TABLES_SQL
OWNER_SQL = _OWNER_SQL
UPGRADE_SQL = TABLES_SQL + CORE_UPGRADE_SQL + OWNER_SQL
DOWNGRADE_SQL = CORE_DOWNGRADE_SQL + _DOWNGRADE_SQL
