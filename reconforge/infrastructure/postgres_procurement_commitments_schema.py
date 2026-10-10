"""Native purchase/budget bidirectional closure; no new monetary ledger."""
from collections.abc import Mapping
from typing import Any

_TABLES = r"""
CREATE TABLE reconforge.procurement_commitment_plans(
 tenant_id TEXT NOT NULL,order_id TEXT NOT NULL,budget_id TEXT NOT NULL,commitment_id TEXT NOT NULL,reserve_event_id TEXT NOT NULL,
 payload JSONB NOT NULL CHECK(jsonb_typeof(payload)='object' AND octet_length(payload::text)<=131072),
 plan_digest TEXT NOT NULL CHECK(plan_digest~'^[0-9a-f]{64}$'),PRIMARY KEY(tenant_id,order_id),
 UNIQUE(tenant_id,reserve_event_id),UNIQUE(tenant_id,budget_id,commitment_id),
 FOREIGN KEY(tenant_id,order_id) REFERENCES reconforge.procurement_partial_orders(tenant_id,id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(tenant_id,budget_id) REFERENCES reconforge.budget_envelopes(tenant_id,id),
 FOREIGN KEY(tenant_id,reserve_event_id) REFERENCES reconforge.budget_commitment_events(tenant_id,id)
);
CREATE TABLE reconforge.procurement_commitment_commands(
 tenant_id TEXT NOT NULL,workspace_id TEXT NOT NULL,order_id TEXT NOT NULL,command_id TEXT NOT NULL CHECK(reconforge.irp_text(command_id,140)),
 operation TEXT NOT NULL CHECK(operation IN('create','consume','release')),actor_id TEXT NOT NULL,
 request_json JSONB NOT NULL CHECK(jsonb_typeof(request_json)='object' AND octet_length(request_json::text)<=131072),
 request_digest TEXT NOT NULL CHECK(request_digest~'^[0-9a-f]{64}$'),budget_event_id TEXT NOT NULL,invoice_id TEXT,
 order_version BIGINT NOT NULL CHECK(order_version>0),audit_event_id TEXT NOT NULL,outbox_event_id TEXT NOT NULL,
 response_json JSONB NOT NULL CHECK(jsonb_typeof(response_json)='object' AND octet_length(response_json::text)<=4096),
 PRIMARY KEY(tenant_id,workspace_id,command_id),UNIQUE(tenant_id,budget_event_id),
 FOREIGN KEY(tenant_id,order_id) REFERENCES reconforge.procurement_commitment_plans(tenant_id,order_id),
 FOREIGN KEY(tenant_id,actor_id) REFERENCES reconforge.identity_users(tenant_id,id),
 FOREIGN KEY(tenant_id,budget_event_id) REFERENCES reconforge.budget_commitment_events(tenant_id,id),
 FOREIGN KEY(tenant_id,invoice_id) REFERENCES reconforge.procurement_partial_invoices(tenant_id,id),
 FOREIGN KEY(tenant_id,audit_event_id) REFERENCES reconforge.domain_audit_events(tenant_id,id),
 FOREIGN KEY(tenant_id,outbox_event_id) REFERENCES reconforge.outbox_events(tenant_id,event_id),
 CHECK((operation='consume')=(invoice_id IS NOT NULL))
);
CREATE UNIQUE INDEX procurement_commitment_create ON reconforge.procurement_commitment_commands(tenant_id,order_id) WHERE operation='create';
CREATE UNIQUE INDEX procurement_commitment_release ON reconforge.procurement_commitment_commands(tenant_id,order_id) WHERE operation='release';
CREATE UNIQUE INDEX procurement_commitment_invoice ON reconforge.procurement_commitment_commands(tenant_id,invoice_id) WHERE operation='consume';
ALTER TABLE reconforge.procurement_commitment_plans ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.procurement_commitment_plans FORCE ROW LEVEL SECURITY;
CREATE POLICY scope ON reconforge.procurement_commitment_plans USING(
 tenant_id=current_setting('app.tenant_id',true) AND reconforge.irp_scope(tenant_id,payload#>>'{scope,workspace_id}',payload#>>'{scope,organization_id}',payload#>>'{scope,legal_entity_id}'))
 WITH CHECK(tenant_id=current_setting('app.tenant_id',true) AND reconforge.irp_scope(tenant_id,payload#>>'{scope,workspace_id}',payload#>>'{scope,organization_id}',payload#>>'{scope,legal_entity_id}'));
ALTER TABLE reconforge.procurement_commitment_commands ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.procurement_commitment_commands FORCE ROW LEVEL SECURITY;
CREATE POLICY scope ON reconforge.procurement_commitment_commands USING(EXISTS(SELECT 1 FROM reconforge.procurement_commitment_plans p
 WHERE p.tenant_id=procurement_commitment_commands.tenant_id AND p.order_id=procurement_commitment_commands.order_id))
 WITH CHECK(EXISTS(SELECT 1 FROM reconforge.procurement_commitment_plans p WHERE p.tenant_id=procurement_commitment_commands.tenant_id AND p.order_id=procurement_commitment_commands.order_id));
CREATE FUNCTION reconforge.pc_protect() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $pc$
BEGIN
 IF TG_TABLE_NAME='procurement_commitment_commands' AND TG_OP='UPDATE' AND OLD.response_json='{}'::jsonb
 AND NEW.response_json<>'{}'::jsonb AND (to_jsonb(OLD)-'response_json')=(to_jsonb(NEW)-'response_json') THEN RETURN NEW; END IF;
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='procurement_commitment_owner',MESSAGE='Procurement commitment evidence is immutable';
END $pc$;
CREATE TRIGGER retained BEFORE UPDATE OR DELETE ON reconforge.procurement_commitment_plans FOR EACH ROW EXECUTE FUNCTION reconforge.pc_protect();
CREATE TRIGGER retained BEFORE UPDATE OR DELETE ON reconforge.procurement_commitment_commands FOR EACH ROW EXECUTE FUNCTION reconforge.pc_protect();
"""

_VERIFY = r"""
CREATE FUNCTION reconforge.pc_currency_precision(t TEXT,i TEXT,code TEXT) RETURNS INTEGER LANGUAGE plpgsql STABLE SET search_path=pg_catalog AS $pc$
DECLARE retained INTEGER;current_precision INTEGER;
BEGIN
 SELECT (payload#>>'{budget_policy,currency_precision}')::integer INTO retained FROM reconforge.procurement_commitment_plans
 WHERE tenant_id=t AND order_id=i AND payload#>>'{order_request,currency_code}'=code;
 SELECT minor_units INTO current_precision FROM reconforge.currencies WHERE tenant_id=t AND currencies.code=pc_currency_precision.code AND active;
 IF retained IS NULL OR current_precision IS DISTINCT FROM retained THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='procurement_commitment_currency_policy',MESSAGE='Original appropriation currency precision must remain authoritative; forward correction is required'; END IF;
 RETURN retained;
END $pc$;
CREATE FUNCTION reconforge.pc_ack(t TEXT,event_id TEXT) RETURNS JSONB LANGUAGE sql STABLE SET search_path=pg_catalog AS $pc$
 SELECT jsonb_build_object('id',p.order_id,'order_id',p.order_id,'number',p.payload#>>'{order_request,number}',
 'workspace_id',p.payload#>>'{scope,workspace_id}','organization_id',p.payload#>>'{scope,organization_id}',
 'legal_entity_id',p.payload#>>'{scope,legal_entity_id}','preparer_actor_id',p.payload->>'preparer_actor_id',
 'budget_id',p.budget_id,'commitment_id',p.commitment_id,'currency_code',p.payload#>>'{order_request,currency_code}',
 'original_minor',(p.payload->>'amount_minor')::numeric::text,'reserved_minor',b.remaining_minor::text,
 'consumed_minor',(SELECT COALESCE(sum(e.amount_minor),0)::text FROM reconforge.budget_commitment_events e
 WHERE e.tenant_id=t AND e.budget_id=p.budget_id AND e.commitment_id=p.commitment_id AND e.operation='Consume' AND e.budget_version<=b.budget_version),
 'released_minor',(SELECT COALESCE(sum(e.amount_minor),0)::text FROM reconforge.budget_commitment_events e
 WHERE e.tenant_id=t AND e.budget_id=p.budget_id AND e.commitment_id=p.commitment_id AND e.operation='Release' AND e.budget_version<=b.budget_version),
 'remaining_minor',b.remaining_minor::text,'budget_version',b.budget_version,'status',
 CASE WHEN EXISTS(SELECT 1 FROM reconforge.budget_commitment_events e WHERE e.tenant_id=t AND e.budget_id=p.budget_id
 AND e.commitment_id=p.commitment_id AND e.operation='Release' AND e.budget_version<=b.budget_version) THEN 'Released'
 WHEN b.remaining_minor=0 THEN 'Consumed' ELSE 'Reserved' END,
 'evidence',jsonb_build_object('budget_event_id',b.id,'audit_event_id',c.audit_event_id,'outbox_event_id',c.outbox_event_id,'request_digest',c.request_digest))
 FROM reconforge.procurement_commitment_commands c JOIN reconforge.procurement_commitment_plans p ON p.tenant_id=c.tenant_id AND p.order_id=c.order_id
 JOIN reconforge.budget_commitment_events b ON b.tenant_id=c.tenant_id AND b.id=c.budget_event_id WHERE c.tenant_id=t AND c.budget_event_id=event_id
$pc$;
CREATE FUNCTION reconforge.pc_budget_event(t TEXT,event_id TEXT) RETURNS VOID LANGUAGE plpgsql SET search_path=pg_catalog AS $pc$
DECLARE e RECORD;b RECORD;c RECORD;scope JSONB;request JSONB;metadata JSONB;
BEGIN
 SELECT * INTO e FROM reconforge.budget_commitment_events WHERE tenant_id=t AND id=event_id;
 SELECT * INTO b FROM reconforge.budget_envelopes WHERE tenant_id=t AND id=e.budget_id;
 SELECT * INTO c FROM reconforge.budget_commands WHERE tenant_id=t AND budget_id=e.budget_id AND request_digest=e.request_digest;
 scope:=jsonb_build_object('workspace_id',b.workspace_id,'organization_id',b.organization_id,'legal_entity_id',b.legal_entity_id);
 request:=jsonb_build_object('budget_id',e.budget_id,'expected_version',e.budget_version-1,'commitment_id',
 CASE WHEN e.operation='Reserve' THEN '' ELSE e.commitment_id END,'operation',e.operation,'amount_minor',e.amount_minor,
 'operation_date',e.operation_date,'source_reference',e.source_reference,'reason',e.reason);
 metadata:=scope||jsonb_build_object('schema_version',1,'commitment_id',e.commitment_id,'event_id',e.id,
 'request_digest',e.request_digest,'row_version',e.budget_version);
 IF e IS NULL OR b IS NULL OR c IS NULL OR c.actor_id IS DISTINCT FROM e.actor_id OR c.workspace_id IS DISTINCT FROM b.workspace_id
 OR c.request_json::jsonb IS DISTINCT FROM request OR e.request_digest IS DISTINCT FROM reconforge.irp_digest(jsonb_build_object('scope',scope,'actor_id',e.actor_id,'request',request))
 OR c.result_digest IS DISTINCT FROM reconforge.irp_digest(c.result_json::jsonb)
 OR c.result_json::jsonb->>'commitment_id' IS DISTINCT FROM e.commitment_id
 OR c.result_json::jsonb->>'remaining_minor' IS DISTINCT FROM e.remaining_minor::text
 OR (c.result_json::jsonb->>'row_version')::bigint IS DISTINCT FROM e.budget_version
 OR NOT EXISTS(SELECT 1 FROM reconforge.domain_audit_events a JOIN reconforge.outbox_events o ON o.tenant_id=a.tenant_id
 WHERE a.tenant_id=t AND a.id=e.audit_event_id AND o.event_id=e.outbox_event_id AND a.actor_user_id=e.actor_id
 AND a.object_type='budget_control' AND a.object_id=b.id AND a.action='budget.'||lower(e.operation) AND a.metadata_json=metadata
 AND o.aggregate_type='budget_control' AND o.aggregate_id=b.id AND o.event_type=a.action
 AND o.payload=metadata||jsonb_build_object('audit_event_id',a.id) AND (o.workspace_id,o.organization_id,o.legal_entity_id)=(b.workspace_id,b.organization_id,b.legal_entity_id)) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='procurement_commitment_owner',MESSAGE='Budget event requires its exact native command, actor and evidence'; END IF;
END $pc$;
CREATE FUNCTION reconforge.pc_release_admit(t TEXT,i TEXT) RETURNS VOID LANGUAGE plpgsql SET search_path=pg_catalog AS $pc$
DECLARE l RECORD;received NUMERIC;invoiced NUMERIC;
BEGIN
 IF EXISTS(SELECT 1 FROM reconforge.procurement_commitment_commands WHERE tenant_id=t AND order_id=i AND operation='release')
 OR EXISTS(SELECT 1 FROM reconforge.procurement_partial_receipts WHERE tenant_id=t AND order_id=i AND stage<>2)
 OR EXISTS(SELECT 1 FROM reconforge.procurement_partial_invoices WHERE tenant_id=t AND order_id=i AND stage<>4) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='procurement_commitment_release',MESSAGE='Release requires no pending source drafts and no previous release'; END IF;
 FOR l IN SELECT id FROM reconforge.procurement_partial_order_lines WHERE tenant_id=t AND order_id=i LOOP
 SELECT COALESCE(sum(quantity),0) INTO received FROM reconforge.procurement_partial_receipts WHERE tenant_id=t AND order_id=i AND order_line_id=l.id AND stage=2;
 SELECT COALESCE(sum(il.quantity),0) INTO invoiced FROM reconforge.procurement_partial_invoice_lines il JOIN reconforge.procurement_partial_invoices n
 ON n.tenant_id=il.tenant_id AND n.id=il.invoice_id WHERE il.tenant_id=t AND il.order_id=i AND il.order_line_id=l.id AND n.stage=4;
 IF received IS DISTINCT FROM invoiced THEN RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='procurement_commitment_release',MESSAGE='All received source quantities must be accrued and consumed before release'; END IF;
 END LOOP;
END $pc$;
CREATE FUNCTION reconforge.pc_close(t TEXT,i TEXT) RETURNS VOID LANGUAGE plpgsql SET search_path=pg_catalog AS $pc$
DECLARE p RECORD;o RECORD;b RECORD;e RECORD;c RECORD;n RECORD;release RECORD;policy JSONB;expected JSONB;consumed NUMERIC;released NUMERIC;counted INTEGER;
BEGIN
 SELECT * INTO o FROM reconforge.procurement_partial_orders WHERE tenant_id=t AND id=i;
 IF o IS NULL OR left(o.number,5)<>'BPC1-' THEN RETURN; END IF;
 PERFORM reconforge.pc_currency_precision(t,i,o.request_json->>'currency_code');
 SELECT * INTO p FROM reconforge.procurement_commitment_plans WHERE tenant_id=t AND order_id=i;
 SELECT * INTO b FROM reconforge.budget_envelopes WHERE tenant_id=t AND id=p.budget_id;
 SELECT * INTO e FROM reconforge.budget_commitment_events WHERE tenant_id=t AND id=p.reserve_event_id;
 policy:=jsonb_build_object('currency_precision',b.currency_precision,'currency_rounding_policy',b.currency_rounding_policy,
 'currency_registry_version',b.currency_registry_version,'currency_registry_digest',b.currency_registry_digest);
 expected:=jsonb_build_object('order_request',o.request_json-ARRAY['item_code','quantity','unit_price_minor','location_code','policy_code'],
 'scope',jsonb_build_object('workspace_id',o.workspace_id,'organization_id',o.organization_id,'legal_entity_id',o.legal_entity_id),
 'budget_id',p.budget_id,'budget_policy',policy,'amount_minor',o.total_minor,'preparer_actor_id',o.creator_actor_id);
 IF p IS NULL OR b IS NULL OR e IS NULL OR NOT o.multiline OR p.payload IS DISTINCT FROM expected
 OR p.plan_digest IS DISTINCT FROM reconforge.irp_digest(expected) OR b.status<>'Approved'
 OR (b.workspace_id,b.organization_id,b.legal_entity_id,b.period_id,b.currency_code) IS DISTINCT FROM
 (o.workspace_id,o.organization_id,o.legal_entity_id,o.request_json->>'period_id',o.request_json->>'currency_code')
 OR e.budget_id<>b.id OR e.commitment_id<>p.commitment_id OR e.operation<>'Reserve' OR e.amount_minor<>o.total_minor
 OR e.remaining_minor<>o.total_minor OR e.source_reference<>'BPC1:'||i OR e.actor_id<>o.creator_actor_id OR e.operation_date<>o.request_json->>'posting_date'
 OR NOT reconforge.irp_scope(t,o.workspace_id,o.organization_id,o.legal_entity_id) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='procurement_commitment_owner',MESSAGE='Budget-backed purchase requires its exact approved native appropriation and original obligation'; END IF;
 SELECT COALESCE(sum(amount_minor) FILTER(WHERE operation='Consume'),0),COALESCE(sum(amount_minor) FILTER(WHERE operation='Release'),0),count(*)
 INTO consumed,released,counted FROM reconforge.budget_commitment_events WHERE tenant_id=t AND budget_id=p.budget_id AND commitment_id=p.commitment_id;
 IF consumed+released>o.total_minor OR counted<>(SELECT count(*) FROM reconforge.procurement_commitment_commands WHERE tenant_id=t AND order_id=i)
 OR consumed IS DISTINCT FROM (SELECT COALESCE(sum(total_minor),0) FROM reconforge.procurement_partial_invoices WHERE tenant_id=t AND order_id=i AND stage=4)
 OR EXISTS(SELECT 1 FROM reconforge.procurement_partial_receipts d JOIN reconforge.inventory_receipt_plans r
 ON r.tenant_id=d.tenant_id AND r.id=d.receipt_plan_id WHERE d.tenant_id=t AND d.order_id=i AND r.total_value_minor<>d.total_minor) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='procurement_commitment_owner',MESSAGE='Native AP accrual and appropriation consumption must close atomically; paid landed charges need their own appropriation'; END IF;
 FOR c IN SELECT * FROM reconforge.procurement_commitment_commands WHERE tenant_id=t AND order_id=i LOOP
 SELECT * INTO e FROM reconforge.budget_commitment_events WHERE tenant_id=t AND id=c.budget_event_id;
 PERFORM reconforge.pc_budget_event(t,e.id);
 IF e.budget_id<>p.budget_id OR e.commitment_id<>p.commitment_id OR e.source_reference<>'BPC1:'||i OR e.actor_id<>c.actor_id
 OR e.operation IS DISTINCT FROM (CASE c.operation WHEN 'create' THEN 'Reserve' WHEN 'consume' THEN 'Consume' ELSE 'Release' END)
 OR c.workspace_id<>o.workspace_id OR c.request_digest IS DISTINCT FROM reconforge.irp_digest(c.request_json)
 OR c.request_json->>'operation' IS DISTINCT FROM c.operation OR c.request_json->>'actor_id' IS DISTINCT FROM c.actor_id
 OR c.response_json IS DISTINCT FROM reconforge.pc_ack(t,e.id)
 OR NOT EXISTS(SELECT 1 FROM reconforge.domain_audit_events a JOIN reconforge.outbox_events x ON x.tenant_id=a.tenant_id
 WHERE a.tenant_id=t AND a.id=c.audit_event_id AND x.event_id=c.outbox_event_id AND a.actor_user_id=c.actor_id
 AND a.object_type='procurement_commitment' AND a.object_id=i AND a.action='procurement_commitment_'||c.operation
 AND a.metadata_json=jsonb_build_object('request_digest',c.request_digest,'budget_event_id',e.id)
 AND x.aggregate_type='procurement_commitment' AND x.aggregate_id=i AND x.event_type=a.action
 AND x.payload=a.metadata_json||jsonb_build_object('audit_event_id',a.id)
 AND (x.workspace_id,x.organization_id,x.legal_entity_id)=(o.workspace_id,o.organization_id,o.legal_entity_id)) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='procurement_commitment_owner',MESSAGE='Source command, budget event, immutable response and evidence must match'; END IF;
 IF c.operation='create' THEN
 IF e.id<>p.reserve_event_id OR c.actor_id<>o.creator_actor_id OR c.order_version<>1
 OR c.request_json->'request' IS DISTINCT FROM jsonb_build_object('budget_id',p.budget_id,'expected_budget_version',e.budget_version-1,
 'order',p.payload->'order_request','reason',e.reason) THEN RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='procurement_commitment_owner',MESSAGE='Purchase reservation differs from original creation'; END IF;
 ELSIF c.operation='consume' THEN
 SELECT * INTO n FROM reconforge.procurement_partial_invoices WHERE tenant_id=t AND id=c.invoice_id AND order_id=i;
 IF n IS NULL OR n.stage<>4 OR n.total_minor<>e.amount_minor OR n.posted_version<>c.order_version OR e.operation_date<>n.posting_date::text
 OR n.period_id IS DISTINCT FROM o.request_json->>'period_id'
 OR NOT EXISTS(SELECT 1 FROM reconforge.finance_posting_effects f WHERE f.tenant_id=t AND f.id=n.accrual_effect_id AND f.posted_actor_id=c.actor_id)
 OR c.request_json->'request' IS DISTINCT FROM jsonb_build_object('order_id',i,'invoice_id',n.id,'expected_order_version',c.order_version-1,
 'expected_budget_version',e.budget_version-1,'reason',e.reason) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='procurement_commitment_owner',MESSAGE='Every consumption requires the same exact native AP effect and third poster'; END IF;
 ELSE
 IF c.actor_id=o.creator_actor_id OR e.remaining_minor<>0 OR e.amount_minor<>o.total_minor-consumed OR c.order_version<>o.row_version
 OR e.operation_date<o.request_json->>'posting_date'
 OR c.request_json->'request' IS DISTINCT FROM jsonb_build_object('order_id',i,'expected_order_version',c.order_version,
 'expected_budget_version',e.budget_version-1,'posting_date',e.operation_date,'reason',e.reason)
 OR EXISTS(SELECT 1 FROM reconforge.procurement_partial_receipts WHERE tenant_id=t AND order_id=i AND stage<>2)
 OR EXISTS(SELECT 1 FROM reconforge.procurement_partial_invoices WHERE tenant_id=t AND order_id=i AND stage<>4) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='procurement_commitment_release',MESSAGE='Terminal release must retain exactly the unreceived obligation and original source version'; END IF;
 FOR n IN SELECT id FROM reconforge.procurement_partial_order_lines WHERE tenant_id=t AND order_id=i LOOP
 IF (SELECT COALESCE(sum(quantity),0) FROM reconforge.procurement_partial_receipts WHERE tenant_id=t AND order_id=i AND order_line_id=n.id AND stage=2)
 IS DISTINCT FROM (SELECT COALESCE(sum(il.quantity),0) FROM reconforge.procurement_partial_invoice_lines il JOIN reconforge.procurement_partial_invoices h
 ON h.tenant_id=il.tenant_id AND h.id=il.invoice_id WHERE il.tenant_id=t AND il.order_id=i AND il.order_line_id=n.id AND h.stage=4) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='procurement_commitment_release',MESSAGE='Release cannot hide unaccrued received source quantities'; END IF;
 END LOOP;
 END IF;
 END LOOP;
 IF NOT EXISTS(SELECT 1 FROM reconforge.procurement_commitment_commands WHERE tenant_id=t AND order_id=i AND operation='create')
 OR EXISTS(SELECT 1 FROM reconforge.procurement_partial_invoices invoice_source
 WHERE invoice_source.tenant_id=t AND invoice_source.order_id=i AND invoice_source.stage=4
 AND NOT EXISTS(SELECT 1 FROM reconforge.procurement_commitment_commands owner_command
 WHERE owner_command.tenant_id=t AND owner_command.order_id=i AND owner_command.invoice_id=invoice_source.id AND owner_command.operation='consume')) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='procurement_commitment_owner',MESSAGE='Native purchase and accrual require their complete appropriation owner'; END IF;
END $pc$;
"""

_ADMISSION = r"""
CREATE FUNCTION reconforge.pc_command_admit() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $pc$
DECLARE o RECORD;permission TEXT;
BEGIN
 SELECT * INTO o FROM reconforge.procurement_partial_orders WHERE tenant_id=NEW.tenant_id AND id=NEW.order_id;
 IF o IS NULL OR left(o.number,5)<>'BPC1-' OR NOT reconforge.irp_scope(o.tenant_id,o.workspace_id,o.organization_id,o.legal_entity_id)
 OR current_setting('transaction_isolation')<>'read committed' THEN RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='procurement_commitment_owner',MESSAGE='Current scoped native purchase is required'; END IF;
 PERFORM 1 FROM reconforge.identity_users WHERE tenant_id=NEW.tenant_id AND id=NEW.actor_id AND NOT disabled FOR SHARE;
 IF NOT FOUND THEN RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='procurement_commitment_owner',MESSAGE='Current persisted human is required'; END IF;
 PERFORM 1 FROM reconforge.principal_scope_grants WHERE tenant_id=NEW.tenant_id AND principal_type='user'
 AND principal_id=NEW.actor_id AND revoked_at IS NULL AND ((scope_type='workspace' AND scope_id=o.workspace_id)
 OR (scope_type='organization' AND scope_id=o.organization_id) OR (scope_type='legal_entity' AND scope_id=o.legal_entity_id)) FOR SHARE;
 IF (SELECT count(*) FROM reconforge.principal_scope_grants WHERE tenant_id=NEW.tenant_id AND principal_type='user'
 AND principal_id=NEW.actor_id AND revoked_at IS NULL AND ((scope_type='workspace' AND scope_id=o.workspace_id)
 OR (scope_type='organization' AND scope_id=o.organization_id) OR (scope_type='legal_entity' AND scope_id=o.legal_entity_id)))<>3 THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='procurement_commitment_owner',MESSAGE='Current canonical appropriation scope grants are required'; END IF;
 PERFORM 1 FROM reconforge.identity_user_roles u JOIN reconforge.identity_roles r ON r.tenant_id=u.tenant_id AND r.id=u.role_id
 JOIN reconforge.identity_role_permissions p ON p.tenant_id=r.tenant_id AND p.role_id=r.id
 WHERE u.tenant_id=NEW.tenant_id AND u.user_id=NEW.actor_id AND u.active AND r.active AND p.active FOR SHARE OF u,r,p;
 FOREACH permission IN ARRAY ARRAY['budget_control.read','budget_control.manage','payables.read','inventory.read','finance_core.read',
 (CASE NEW.operation WHEN 'create' THEN 'payables.manage' WHEN 'consume' THEN 'finance_core.post' ELSE 'payables.approve' END)] LOOP
 IF NOT reconforge.sales_revenue_actor(NEW.tenant_id,NEW.actor_id,permission) THEN RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='procurement_commitment_owner',MESSAGE='Current purchase and appropriation authority is required'; END IF;
 END LOOP;
 RETURN NEW;
END $pc$;
CREATE TRIGGER admission BEFORE INSERT ON reconforge.procurement_commitment_commands FOR EACH ROW EXECUTE FUNCTION reconforge.pc_command_admit();
CREATE FUNCTION reconforge.pc_progress(t TEXT,i TEXT) RETURNS VOID LANGUAGE plpgsql SET search_path=pg_catalog AS $pc$
BEGIN
 IF EXISTS(SELECT 1 FROM reconforge.procurement_commitment_commands WHERE tenant_id=t AND order_id=i AND operation='release') THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='procurement_commitment_release',MESSAGE='Released purchase retains its terminal source state'; END IF;
END $pc$;
ALTER FUNCTION reconforge.pp_verify_order(TEXT,TEXT) RENAME TO pp_verify_order_pre_commitment;
CREATE FUNCTION reconforge.pp_verify_order(t TEXT,i TEXT) RETURNS VOID LANGUAGE plpgsql SET search_path=pg_catalog AS $pc$
DECLARE number TEXT;
BEGIN
 PERFORM reconforge.pp_verify_order_pre_commitment(t,i);
 SELECT o.number INTO number FROM reconforge.procurement_partial_orders o WHERE tenant_id=t AND id=i;
 IF left(number,5)='BPC1-' THEN PERFORM reconforge.pc_close(t,i); END IF;
END $pc$;
CREATE FUNCTION reconforge.pc_reverse_close() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $pc$
DECLARE j JSONB;identifier TEXT;
BEGIN
 IF TG_OP='DELETE' THEN j:=to_jsonb(OLD); ELSE j:=to_jsonb(NEW); END IF;
 IF TG_TABLE_NAME='budget_commitment_events' THEN
 IF left(j->>'source_reference',5) IS DISTINCT FROM 'BPC1:' THEN RETURN NULL; END IF;
 identifier:=substr(j->>'source_reference',6);
 ELSIF TG_TABLE_NAME='budget_commands' THEN
 IF left(j->>'request_json',1)<>'{' THEN RETURN NULL; END IF;
 IF left((j->>'request_json')::jsonb->>'source_reference',5) IS DISTINCT FROM 'BPC1:' THEN RETURN NULL; END IF;
 identifier:=substr((j->>'request_json')::jsonb->>'source_reference',6);
 ELSIF TG_TABLE_NAME IN ('domain_audit_events','outbox_events') THEN identifier:=COALESCE(j->>'object_id',j->>'aggregate_id');
 ELSE identifier:=j->>'order_id'; END IF;
 IF NOT EXISTS(SELECT 1 FROM reconforge.procurement_partial_orders WHERE tenant_id=j->>'tenant_id' AND id=identifier AND left(number,5)='BPC1-') THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='procurement_commitment_owner',MESSAGE='Reserved appropriation source has no exact native purchase'; END IF;
 PERFORM reconforge.pp_verify_order(j->>'tenant_id',identifier);
 RETURN NULL;
END $pc$;
CREATE CONSTRAINT TRIGGER closure AFTER INSERT OR UPDATE OR DELETE ON reconforge.procurement_commitment_plans DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION reconforge.pc_reverse_close();
CREATE CONSTRAINT TRIGGER closure AFTER INSERT OR UPDATE OR DELETE ON reconforge.procurement_commitment_commands DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION reconforge.pc_reverse_close();
CREATE CONSTRAINT TRIGGER procurement_budget_closure AFTER INSERT OR UPDATE OR DELETE ON reconforge.budget_commitment_events DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION reconforge.pc_reverse_close();
CREATE CONSTRAINT TRIGGER procurement_budget_closure AFTER INSERT OR UPDATE OR DELETE ON reconforge.budget_commands DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION reconforge.pc_reverse_close();
CREATE CONSTRAINT TRIGGER procurement_budget_audit_closure AFTER UPDATE OR DELETE ON reconforge.domain_audit_events DEFERRABLE INITIALLY DEFERRED FOR EACH ROW WHEN(OLD.object_type='procurement_commitment') EXECUTE FUNCTION reconforge.pc_reverse_close();
CREATE CONSTRAINT TRIGGER procurement_budget_outbox_closure AFTER UPDATE OR DELETE ON reconforge.outbox_events DEFERRABLE INITIALLY DEFERRED FOR EACH ROW WHEN(OLD.aggregate_type='procurement_commitment') EXECUTE FUNCTION reconforge.pc_reverse_close();
"""

UPGRADE_SQL = _TABLES + _VERIFY + _ADMISSION

DOWNGRADE_SQL = r"""
DO $pc$ BEGIN IF EXISTS(SELECT 1 FROM reconforge.procurement_commitment_plans) OR EXISTS(SELECT 1 FROM reconforge.procurement_commitment_commands) THEN
 RAISE EXCEPTION 'Retained appropriation history requires forward correction or verified pre-upgrade restore'; END IF; END $pc$;
DROP TRIGGER procurement_budget_closure ON reconforge.budget_commitment_events;
DROP TRIGGER procurement_budget_closure ON reconforge.budget_commands;
DROP TRIGGER procurement_budget_audit_closure ON reconforge.domain_audit_events;
DROP TRIGGER procurement_budget_outbox_closure ON reconforge.outbox_events;
DROP FUNCTION reconforge.pp_verify_order(TEXT,TEXT);
ALTER FUNCTION reconforge.pp_verify_order_pre_commitment(TEXT,TEXT) RENAME TO pp_verify_order;
DROP TABLE reconforge.procurement_commitment_commands;
DROP TABLE reconforge.procurement_commitment_plans;
DROP FUNCTION reconforge.pc_reverse_close();
DROP FUNCTION reconforge.pc_command_admit();
DROP FUNCTION reconforge.pc_progress(TEXT,TEXT);
DROP FUNCTION reconforge.pc_close(TEXT,TEXT);
DROP FUNCTION reconforge.pc_currency_precision(TEXT,TEXT,TEXT);
DROP FUNCTION reconforge.pc_release_admit(TEXT,TEXT);
DROP FUNCTION reconforge.pc_budget_event(TEXT,TEXT);
DROP FUNCTION reconforge.pc_ack(TEXT,TEXT);
DROP FUNCTION reconforge.pc_protect();
"""


def install_postgres_procurement_commitments(connection: Any) -> None:
    row = connection.execute("SELECT to_regclass('reconforge.procurement_commitment_plans') AS installed").fetchone()
    if (row["installed"] if isinstance(row, Mapping) else row[0]) is None:
        with connection.transaction():
            connection.execute(UPGRADE_SQL)
