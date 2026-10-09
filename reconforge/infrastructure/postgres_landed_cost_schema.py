"""Immutable landed cost allocations and bidirectional native effect closure."""
from collections.abc import Mapping
from typing import Any

UPGRADE_SQL = r"""
DO $lc$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname=current_user AND (rolsuper OR rolbypassrls)) THEN
  RAISE EXCEPTION 'Landed cost migration requires forced-RLS migration authority'; END IF;
 IF EXISTS(SELECT 1 FROM reconforge.finance_entries WHERE upper(entry_number) LIKE 'LC1-%' OR upper(id) LIKE 'LC1-%') THEN
  RAISE EXCEPTION 'LC1 namespace already contains incompatible entries'; END IF;
END $lc$;
CREATE TABLE reconforge.landed_cost_plans (
 tenant_id TEXT NOT NULL,id TEXT NOT NULL,order_id TEXT NOT NULL,workspace_id TEXT NOT NULL,organization_id TEXT NOT NULL,legal_entity_id TEXT NOT NULL,
 entry_id TEXT NOT NULL,amount_minor BIGINT NOT NULL CHECK(amount_minor BETWEEN 1 AND 9000000000000000000),
 phase INTEGER NOT NULL CHECK(phase BETWEEN 0 AND 2),payload JSONB NOT NULL CHECK(octet_length(payload::text)<=131072),
 plan_digest TEXT NOT NULL CHECK(plan_digest~'^[0-9a-f]{64}$'),audit_event_id TEXT NOT NULL,outbox_event_id TEXT NOT NULL,
 PRIMARY KEY(tenant_id,id),UNIQUE(tenant_id,entry_id),UNIQUE(tenant_id,order_id,id),
 FOREIGN KEY(tenant_id,order_id) REFERENCES reconforge.procurement_partial_orders(tenant_id,id),
 FOREIGN KEY(tenant_id,entry_id) REFERENCES reconforge.finance_entries(tenant_id,id),
 FOREIGN KEY(tenant_id,audit_event_id) REFERENCES reconforge.domain_audit_events(tenant_id,id),
 FOREIGN KEY(tenant_id,outbox_event_id) REFERENCES reconforge.outbox_events(tenant_id,event_id)
);
CREATE UNIQUE INDEX landed_cost_order_number ON reconforge.landed_cost_plans(tenant_id,order_id,(payload#>>'{request,number}'));
CREATE TABLE reconforge.landed_cost_allocations (
 tenant_id TEXT NOT NULL,plan_id TEXT NOT NULL,order_id TEXT NOT NULL,sequence INTEGER NOT NULL CHECK(sequence BETWEEN 1 AND 128),
 order_line_id TEXT NOT NULL,quantity_text TEXT NOT NULL CHECK(length(quantity_text)<=64 AND quantity_text::numeric>0),
 base_minor BIGINT NOT NULL CHECK(base_minor BETWEEN 1 AND 9000000000000000000),
 freight_minor BIGINT NOT NULL CHECK(freight_minor BETWEEN 0 AND 9000000000000000000),
 duty_minor BIGINT NOT NULL CHECK(duty_minor BETWEEN 0 AND 9000000000000000000),receipt_id TEXT NOT NULL,
 CHECK(base_minor::numeric+freight_minor+duty_minor<=9000000000000000000),
 PRIMARY KEY(tenant_id,plan_id,sequence),UNIQUE(tenant_id,receipt_id),UNIQUE(tenant_id,plan_id,order_line_id),
 FOREIGN KEY(tenant_id,order_id,plan_id) REFERENCES reconforge.landed_cost_plans(tenant_id,order_id,id),
 FOREIGN KEY(tenant_id,order_id,order_line_id) REFERENCES reconforge.procurement_partial_order_lines(tenant_id,order_id,id),
 FOREIGN KEY(tenant_id,receipt_id) REFERENCES reconforge.procurement_partial_receipts(tenant_id,id) DEFERRABLE INITIALLY DEFERRED
);
CREATE TABLE reconforge.landed_cost_reviews (
 tenant_id TEXT NOT NULL,plan_id TEXT NOT NULL,reviewer_actor_id TEXT NOT NULL,reason TEXT NOT NULL CHECK(reconforge.irp_text(reason,500)),
 audit_event_id TEXT NOT NULL,outbox_event_id TEXT NOT NULL,PRIMARY KEY(tenant_id,plan_id),
 FOREIGN KEY(tenant_id,plan_id) REFERENCES reconforge.landed_cost_plans(tenant_id,id),
 FOREIGN KEY(tenant_id,reviewer_actor_id) REFERENCES reconforge.identity_users(tenant_id,id),
 FOREIGN KEY(tenant_id,audit_event_id) REFERENCES reconforge.domain_audit_events(tenant_id,id),
 FOREIGN KEY(tenant_id,outbox_event_id) REFERENCES reconforge.outbox_events(tenant_id,event_id)
);
CREATE TABLE reconforge.landed_cost_links (
 tenant_id TEXT NOT NULL,plan_id TEXT NOT NULL,posting_effect_id TEXT NOT NULL,posted_actor_id TEXT NOT NULL,
 reason TEXT NOT NULL CHECK(reconforge.irp_text(reason,500)),audit_event_id TEXT NOT NULL,outbox_event_id TEXT NOT NULL,
 PRIMARY KEY(tenant_id,plan_id),UNIQUE(tenant_id,posting_effect_id),
 FOREIGN KEY(tenant_id,plan_id) REFERENCES reconforge.landed_cost_plans(tenant_id,id),
 FOREIGN KEY(tenant_id,posting_effect_id) REFERENCES reconforge.finance_posting_effects(tenant_id,id),
 FOREIGN KEY(tenant_id,posted_actor_id) REFERENCES reconforge.identity_users(tenant_id,id),
 FOREIGN KEY(tenant_id,audit_event_id) REFERENCES reconforge.domain_audit_events(tenant_id,id),
 FOREIGN KEY(tenant_id,outbox_event_id) REFERENCES reconforge.outbox_events(tenant_id,event_id)
);
CREATE TABLE reconforge.landed_cost_commands (
 tenant_id TEXT NOT NULL,workspace_id TEXT NOT NULL,plan_id TEXT NOT NULL,operation TEXT NOT NULL CHECK(operation IN ('prepare','review','post')),
 command_id TEXT NOT NULL CHECK(reconforge.irp_text(command_id,140)),actor_id TEXT NOT NULL,request_digest TEXT NOT NULL CHECK(request_digest~'^[0-9a-f]{64}$'),
 request_json JSONB NOT NULL CHECK(octet_length(request_json::text)<=131072),response_json JSONB NOT NULL CHECK(octet_length(response_json::text)<=131072),
 PRIMARY KEY(tenant_id,workspace_id,command_id),UNIQUE(tenant_id,plan_id,operation),
 FOREIGN KEY(tenant_id,plan_id) REFERENCES reconforge.landed_cost_plans(tenant_id,id),
 FOREIGN KEY(tenant_id,actor_id) REFERENCES reconforge.identity_users(tenant_id,id)
);
CREATE FUNCTION reconforge.landed_cost_command_admit() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $lc$
DECLARE p RECORD;permission TEXT;required TEXT[];
BEGIN
 SELECT * INTO p FROM reconforge.landed_cost_plans WHERE tenant_id=NEW.tenant_id AND id=NEW.plan_id;
 required:=ARRAY['payables.read','inventory.read','finance_core.read','payables.settle']||CASE NEW.operation
 WHEN 'prepare' THEN ARRAY['payables.manage','inventory.manage','inventory.valuation.manage','finance_core.manage']
 WHEN 'review' THEN ARRAY['payables.approve','inventory.post','inventory.valuation.approve','finance_core.validate']
 WHEN 'post' THEN ARRAY['payables.manage','inventory.post','inventory.valuation.approve','finance_core.post'] ELSE ARRAY[]::TEXT[] END;
 IF p IS NULL OR NEW.operation NOT IN('prepare','review','post') OR NEW.workspace_id IS DISTINCT FROM p.workspace_id
 OR NOT reconforge.irp_scope(p.tenant_id,p.workspace_id,p.organization_id,p.legal_entity_id) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='landed_cost_owner_phase',MESSAGE='Landed cost command requires its current retained source scope'; END IF;
 FOREACH permission IN ARRAY required LOOP
 IF NOT reconforge.sales_revenue_actor(p.tenant_id,NEW.actor_id,permission) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='landed_cost_owner_phase',MESSAGE='Landed cost command requires current persisted scoped human authority'; END IF;
 END LOOP;
 RETURN NEW;
END $lc$;
CREATE TRIGGER landed_cost_command_admission BEFORE INSERT ON reconforge.landed_cost_commands
 FOR EACH ROW EXECUTE FUNCTION reconforge.landed_cost_command_admit();
CREATE FUNCTION reconforge.landed_cost_protect() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $lc$
BEGIN
 IF TG_TABLE_NAME='landed_cost_plans' AND TG_OP='INSERT' THEN
  IF NEW.phase<>0 THEN RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='landed_cost_owner_phase',MESSAGE='Landed costs are born Prepared'; END IF;
  RETURN NEW;
 END IF;
 IF TG_TABLE_NAME='landed_cost_plans' AND TG_OP='UPDATE' THEN
  IF NEW.phase=OLD.phase+1 AND (to_jsonb(NEW)-'phase')=(to_jsonb(OLD)-'phase') THEN RETURN NEW; END IF;
 END IF;
 IF TG_OP='INSERT' THEN RETURN NEW; END IF;
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='landed_cost_owner_phase',MESSAGE='Landed cost history is immutable';
END $lc$;
CREATE FUNCTION reconforge.landed_cost_event(t TEXT,i TEXT,a TEXT,b TEXT,actor TEXT,action TEXT,seal TEXT) RETURNS BOOLEAN
 LANGUAGE sql STABLE SET search_path=pg_catalog AS $lc$
 SELECT EXISTS(SELECT 1 FROM reconforge.domain_audit_events x JOIN reconforge.outbox_events y ON y.tenant_id=x.tenant_id
 JOIN reconforge.landed_cost_plans p ON p.tenant_id=x.tenant_id AND p.id=i WHERE x.tenant_id=t AND x.id=a AND y.event_id=b
 AND x.actor_user_id=actor AND x.object_type='landed_cost' AND x.object_id=i AND x.action=$6
 AND x.metadata_json=jsonb_build_object('plan_digest',seal) AND y.event_type=$6 AND y.aggregate_type='landed_cost' AND y.aggregate_id=i
 AND y.payload=jsonb_build_object('plan_digest',seal,'audit_event_id',a)
 AND (y.workspace_id,y.organization_id,y.legal_entity_id)=(p.workspace_id,p.organization_id,p.legal_entity_id))
$lc$;
CREATE FUNCTION reconforge.landed_cost_ack(t TEXT,i TEXT,ack_stage INTEGER) RETURNS JSONB
 LANGUAGE sql STABLE SET search_path=pg_catalog AS $lc$
 SELECT jsonb_build_object('id',p.id,'order_id',p.order_id,'number',p.payload#>>'{request,number}',
 'workspace_id',p.workspace_id,'organization_id',p.organization_id,'legal_entity_id',p.legal_entity_id,
 'phase',ack_stage,'status',CASE ack_stage WHEN 0 THEN 'Prepared' WHEN 1 THEN 'Reviewed' ELSE 'Posted' END,
 'plan_digest',p.plan_digest,'freight_minor',p.payload#>>'{request,freight_minor}','duty_minor',p.payload#>>'{request,duty_minor}',
 'amount_minor',p.amount_minor::text,'currency_code',p.payload#>>'{snapshot,entry,currency_code}','entry_id',p.entry_id,
 'preparer_actor_id',p.payload->>'preparer_actor_id','reviewer_actor_id',CASE WHEN ack_stage>=1 THEN r.reviewer_actor_id ELSE NULL END,
 'posted_actor_id',CASE WHEN ack_stage=2 THEN l.posted_actor_id ELSE NULL END,'posting_effect_id',CASE WHEN ack_stage=2 THEN l.posting_effect_id ELSE NULL END,
 'allocations',(SELECT jsonb_agg((to_jsonb(a)-ARRAY['tenant_id','plan_id','order_id'])||jsonb_build_object(
 'base_minor',a.base_minor::text,'freight_minor',a.freight_minor::text,'duty_minor',a.duty_minor::text,'receipt_plan_id',d.receipt_plan_id,'stage',ack_stage)
 ORDER BY a.sequence) FROM reconforge.landed_cost_allocations a JOIN reconforge.procurement_partial_receipts d
 ON d.tenant_id=a.tenant_id AND d.id=a.receipt_id WHERE a.tenant_id=t AND a.plan_id=i))
 FROM reconforge.landed_cost_plans p LEFT JOIN reconforge.landed_cost_reviews r ON r.tenant_id=p.tenant_id AND r.plan_id=p.id
 LEFT JOIN reconforge.landed_cost_links l ON l.tenant_id=p.tenant_id AND l.plan_id=p.id WHERE p.tenant_id=t AND p.id=i
$lc$;
CREATE FUNCTION reconforge.landed_cost_close(t TEXT,i TEXT) RETURNS VOID LANGUAGE plpgsql SET search_path=pg_catalog AS $lc$
DECLARE p RECORD;o RECORD;e RECORD;r RECORD;l RECORD;f RECORD;a RECORD;d RECORD;n RECORD;c RECORD;header JSONB;lines JSONB;allocations JSONB;
 cash TEXT;clearing TEXT;maker TEXT;total NUMERIC;expected_freight NUMERIC;expected_duty NUMERIC;expected_actor TEXT;expected_request JSONB;
BEGIN
 SELECT * INTO p FROM reconforge.landed_cost_plans WHERE tenant_id=t AND id=i;
 IF p IS NULL THEN RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='landed_cost_owner_phase',MESSAGE='LC1 source owner is required'; END IF;
 SELECT * INTO o FROM reconforge.procurement_partial_orders WHERE tenant_id=t AND id=p.order_id;
 SELECT * INTO e FROM reconforge.finance_entries WHERE tenant_id=t AND id=p.entry_id;
 SELECT * INTO r FROM reconforge.landed_cost_reviews WHERE tenant_id=t AND plan_id=i;
 SELECT * INTO l FROM reconforge.landed_cost_links WHERE tenant_id=t AND plan_id=i;
 maker:=p.payload->>'preparer_actor_id';
 IF o IS NULL OR NOT o.multiline OR o.stage<>2 OR e IS NULL OR NOT reconforge.irp_scope(t,p.workspace_id,p.organization_id,p.legal_entity_id)
 OR (p.workspace_id,p.organization_id,p.legal_entity_id) IS DISTINCT FROM (o.workspace_id,o.organization_id,o.legal_entity_id)
 OR p.payload->>'schema_version' IS DISTINCT FROM 'landed-cost-v1' OR p.payload->>'id' IS DISTINCT FROM i
 OR p.payload->>'entry_id' IS DISTINCT FROM p.entry_id OR p.payload#>>'{request,order_id}' IS DISTINCT FROM o.id
 OR reconforge.irp_digest(p.payload) IS DISTINCT FROM p.plan_digest
 OR p.amount_minor::numeric IS DISTINCT FROM (p.payload#>>'{request,freight_minor}')::numeric+(p.payload#>>'{request,duty_minor}')::numeric
 OR (p.payload#>>'{request,freight_minor}')::numeric<0 OR (p.payload#>>'{request,duty_minor}')::numeric<0
 OR (p.payload->>'workspace_id',p.payload->>'organization_id',p.payload->>'legal_entity_id') IS DISTINCT FROM (p.workspace_id,p.organization_id,p.legal_entity_id)
 OR e.entry_number<>upper(i) OR e.external_reference<>'LANDED-COST:'||i OR e.source_type<>'Manual'
 OR e.preparer_actor_id IS DISTINCT FROM maker OR e.total_debit_minor<>p.amount_minor OR e.total_credit_minor<>p.amount_minor
 OR e.currency_code<>o.request_json->>'currency_code' OR e.organization_code<>o.request_json->>'organization_code'
 OR e.entity_code<>o.request_json->>'entity_code' OR e.workspace_id<>o.workspace_id OR e.reverses_posting_id IS NOT NULL
 OR e.description<>p.payload#>>'{request,reason}' OR e.posting_date::text<>p.payload#>>'{request,posting_date}' OR e.period_id<>p.payload#>>'{request,period_id}'
 OR NOT EXISTS(SELECT 1 FROM reconforge.finance_journals j WHERE j.tenant_id=t AND j.id=e.journal_id AND j.journal_code=o.request_json->>'journal_code') THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='landed_cost_owner_phase',MESSAGE='Landed cost exact source, scope, amount or immutable digest differs'; END IF;
 SELECT jsonb_object_agg(key,value) INTO header FROM jsonb_each(to_jsonb(e)) WHERE key=ANY(ARRAY[
 'id','workspace_id','journal_id','period_id','entry_number','posting_date','description','external_reference','source_type','currency_code',
 'currency_precision','currency_rounding_policy','currency_registry_version','currency_registry_digest','preparer_actor_id','reverses_posting_id']);
 header:=header||jsonb_build_object('organization_id',p.organization_id,'legal_entity_id',p.legal_entity_id);
 SELECT jsonb_agg(jsonb_build_object('line_number',x.line_number,'account_id',x.account_id,'description',x.description,
 'debit_minor',x.debit_minor,'credit_minor',x.credit_minor,'dimensions',COALESCE((SELECT jsonb_object_agg(z.dimension_id,z.dimension_value_id)
 FROM reconforge.finance_entry_line_dimensions z WHERE z.tenant_id=t AND z.entry_line_id=x.id),'{}'::jsonb)) ORDER BY x.line_number)
 INTO lines FROM reconforge.finance_entry_lines x WHERE x.tenant_id=t AND x.entry_id=e.id;
 SELECT fa.id INTO cash FROM reconforge.finance_accounts fa JOIN reconforge.finance_journals j ON j.tenant_id=fa.tenant_id AND j.chart_id=fa.chart_id
 WHERE fa.tenant_id=t AND j.id=e.journal_id AND fa.account_code=o.request_json->>'cash_account_code' AND fa.account_type='Asset';
 IF p.payload->'snapshot' IS DISTINCT FROM jsonb_build_object('schema_version','finance-entry-review-v1','entry',header,'lines',lines)
 OR reconforge.irp_digest(p.payload->'snapshot') IS DISTINCT FROM p.payload->>'validation_digest'
 OR jsonb_array_length(lines)<>2 OR cash IS NULL OR lines->1->>'account_id' IS DISTINCT FROM cash
 OR (lines->0->>'debit_minor')::numeric<>p.amount_minor OR (lines->0->>'credit_minor')::numeric<>0
 OR (lines->1->>'credit_minor')::numeric<>p.amount_minor OR (lines->1->>'debit_minor')::numeric<>0 THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='landed_cost_owner_phase',MESSAGE='Paid charges require their exact retained native GL snapshot'; END IF;
 SELECT sum(base_minor) INTO total FROM reconforge.landed_cost_allocations WHERE tenant_id=t AND plan_id=i;
 SELECT jsonb_agg(to_jsonb(x)-ARRAY['tenant_id','plan_id','order_id'] ORDER BY sequence) INTO allocations
 FROM reconforge.landed_cost_allocations x WHERE tenant_id=t AND plan_id=i;
 IF allocations IS DISTINCT FROM p.payload->'allocations' OR jsonb_array_length(allocations) NOT BETWEEN 1 AND 128
 OR jsonb_array_length(p.payload#>'{request,lines}')<>jsonb_array_length(allocations)
 OR (SELECT sum(freight_minor) FROM reconforge.landed_cost_allocations WHERE tenant_id=t AND plan_id=i)<>(p.payload#>>'{request,freight_minor}')::numeric
 OR (SELECT sum(duty_minor) FROM reconforge.landed_cost_allocations WHERE tenant_id=t AND plan_id=i)<>(p.payload#>>'{request,duty_minor}')::numeric THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='landed_cost_owner_phase',MESSAGE='Allocations must conserve all paid charges and source members'; END IF;
 FOR a IN SELECT * FROM reconforge.landed_cost_allocations WHERE tenant_id=t AND plan_id=i ORDER BY sequence LOOP
 SELECT * INTO d FROM reconforge.procurement_partial_receipts WHERE tenant_id=t AND id=a.receipt_id;
 SELECT * INTO n FROM reconforge.procurement_partial_order_lines WHERE tenant_id=t AND order_id=o.id AND id=a.order_line_id;
 SELECT q.receipt_clearing_account_id INTO clearing FROM reconforge.inventory_receipt_plans q WHERE q.tenant_id=t AND q.id=d.receipt_plan_id;
 SELECT floor((p.payload#>>'{request,freight_minor}')::numeric*a.base_minor/total)+CASE WHEN rank<=residual THEN 1 ELSE 0 END INTO expected_freight
 FROM (SELECT order_line_id,row_number() OVER(ORDER BY mod((p.payload#>>'{request,freight_minor}')::numeric*base_minor,total) DESC,order_line_id COLLATE "C") rank,
 (p.payload#>>'{request,freight_minor}')::numeric-sum(floor((p.payload#>>'{request,freight_minor}')::numeric*base_minor/total)) OVER() residual
 FROM reconforge.landed_cost_allocations WHERE tenant_id=t AND plan_id=i) weights WHERE order_line_id=a.order_line_id;
 SELECT floor((p.payload#>>'{request,duty_minor}')::numeric*a.base_minor/total)+CASE WHEN rank<=residual THEN 1 ELSE 0 END INTO expected_duty
 FROM (SELECT order_line_id,row_number() OVER(ORDER BY mod((p.payload#>>'{request,duty_minor}')::numeric*base_minor,total) DESC,order_line_id COLLATE "C") rank,
 (p.payload#>>'{request,duty_minor}')::numeric-sum(floor((p.payload#>>'{request,duty_minor}')::numeric*base_minor/total)) OVER() residual
 FROM reconforge.landed_cost_allocations WHERE tenant_id=t AND plan_id=i) weights WHERE order_line_id=a.order_line_id;
 IF d IS NULL OR n IS NULL OR d.order_id<>o.id OR d.order_line_id<>n.id OR a.quantity_text::numeric<>d.quantity
 OR a.base_minor<>d.total_minor OR a.base_minor::numeric<>d.quantity*n.unit_price_minor
 OR a.freight_minor<>expected_freight OR a.duty_minor<>expected_duty OR clearing IS DISTINCT FROM lines->0->>'account_id'
 OR d.stage<>p.phase OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(p.payload#>'{request,lines}') z
 WHERE z->>'line_id'=n.id AND (z->>'quantity')::numeric=d.quantity)
 OR reconforge.pp_command(t,o.id,d.created_version,'prepare-receipt-line')<>maker
 OR (p.phase>=1 AND reconforge.pp_command(t,o.id,d.reviewed_version,'review-receipt',d.id)<>r.reviewer_actor_id)
 OR (p.phase=2 AND reconforge.pp_command(t,o.id,d.posted_version,'receive',d.id)<>l.posted_actor_id) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='landed_cost_owner_phase',MESSAGE='Charged receipts require the whole conserved bundle and its three human stages'; END IF;
 END LOOP;
 IF NOT reconforge.landed_cost_event(t,i,p.audit_event_id,p.outbox_event_id,maker,'landed_cost_prepared',p.plan_digest)
 OR (p.phase=0 AND (e.status<>'Draft' OR r IS NOT NULL OR l IS NOT NULL))
 OR (p.phase>=1 AND (r IS NULL OR r.reviewer_actor_id=maker OR e.validator_actor_id<>r.reviewer_actor_id
 OR e.validation_digest<>p.payload->>'validation_digest' OR NOT reconforge.landed_cost_event(t,i,r.audit_event_id,r.outbox_event_id,r.reviewer_actor_id,'landed_cost_reviewed',p.plan_digest)))
 OR (p.phase=1 AND (e.status<>'Validated' OR l IS NOT NULL)) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='landed_cost_owner_phase',MESSAGE='Landed cost requires retained independent review and evidence'; END IF;
 IF p.phase=2 THEN
 SELECT * INTO f FROM reconforge.finance_posting_effects WHERE tenant_id=t AND id=l.posting_effect_id;
 IF l IS NULL OR f IS NULL OR f.entry_id<>e.id OR f.source_kind<>'Manual' OR f.source_id<>e.id OR f.snapshot_json<>p.payload->'snapshot'
 OR e.status<>'Validated' OR f.validation_digest<>p.payload->>'validation_digest' OR f.posted_actor_id<>l.posted_actor_id
 OR l.posted_actor_id IN(maker,r.reviewer_actor_id) OR EXISTS(SELECT 1 FROM reconforge.finance_posting_effects z WHERE z.tenant_id=t AND z.reverses_effect_id=f.id)
 OR NOT reconforge.landed_cost_event(t,i,l.audit_event_id,l.outbox_event_id,l.posted_actor_id,'landed_cost_posted',p.plan_digest) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='landed_cost_owner_phase',MESSAGE='Receipt publication and exact cash posting must commit together'; END IF;
 ELSIF EXISTS(SELECT 1 FROM reconforge.finance_posting_effects z WHERE z.tenant_id=t AND z.entry_id=e.id) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='landed_cost_owner_phase',MESSAGE='Cash cannot publish without its received allocation bundle'; END IF;
 FOR c IN SELECT * FROM reconforge.landed_cost_commands WHERE tenant_id=t AND plan_id=i LOOP
 expected_actor:=CASE c.operation WHEN 'prepare' THEN maker WHEN 'review' THEN r.reviewer_actor_id ELSE l.posted_actor_id END;
 expected_request:=CASE c.operation WHEN 'prepare' THEN p.payload->'request' ELSE jsonb_build_object('plan_id',i,'expected_plan_digest',p.plan_digest,
 'reason',CASE c.operation WHEN 'review' THEN r.reason ELSE l.reason END) END;
 IF c.workspace_id<>p.workspace_id OR c.actor_id IS DISTINCT FROM expected_actor
 OR c.request_json IS DISTINCT FROM jsonb_build_object('operation',c.operation,'actor_id',c.actor_id,'request',expected_request)
 OR reconforge.irp_digest(c.request_json) IS DISTINCT FROM c.request_digest
 OR c.response_json->>'id' IS DISTINCT FROM i OR c.response_json->>'plan_digest' IS DISTINCT FROM p.plan_digest
 OR c.response_json IS DISTINCT FROM reconforge.landed_cost_ack(t,i,CASE c.operation WHEN 'prepare' THEN 0 WHEN 'review' THEN 1 ELSE 2 END)
 OR (c.response_json->>'phase')::integer<>(CASE c.operation WHEN 'prepare' THEN 0 WHEN 'review' THEN 1 ELSE 2 END)
 OR c.response_json->>'status'<>(CASE c.operation WHEN 'prepare' THEN 'Prepared' WHEN 'review' THEN 'Reviewed' ELSE 'Posted' END) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='landed_cost_owner_phase',MESSAGE='Retry acknowledgement requires its exact source, actor and phase'; END IF;
 END LOOP;
 IF (SELECT count(*) FROM reconforge.landed_cost_commands WHERE tenant_id=t AND plan_id=i)<>p.phase+1 THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='landed_cost_owner_phase',MESSAGE='Every paid landed cost stage requires an immutable command'; END IF;
END $lc$;
ALTER FUNCTION reconforge.pp_verify_multiline(TEXT,TEXT) RENAME TO pp_verify_multiline_pre_landed;
DO $lc$ DECLARE definition TEXT;needle TEXT:='OR r.total_value_minor<>d.total_minor';BEGIN
 definition:=pg_get_functiondef('reconforge.pp_verify_multiline_pre_landed(text,text)'::regprocedure);
 IF length(definition)-length(replace(definition,needle,''))<>length(needle) THEN RAISE EXCEPTION 'Unsupported prior receipt closure'; END IF;
 definition:=replace(definition,'reconforge.pp_verify_multiline_pre_landed','reconforge.pp_verify_multiline');
 definition:=replace(definition,needle,'OR r.total_value_minor::numeric<>d.total_minor::numeric+COALESCE((SELECT freight_minor::numeric+duty_minor FROM reconforge.landed_cost_allocations WHERE tenant_id=t AND receipt_id=d.id),0)');
 EXECUTE definition;
END $lc$;
CREATE FUNCTION reconforge.landed_cost_reverse_close() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $lc$
DECLARE j JSONB;changed JSONB[];p RECORD;native_entry TEXT;number TEXT;receipt TEXT;parent TEXT;
BEGIN
 changed:=CASE WHEN TG_OP='INSERT' THEN ARRAY[to_jsonb(NEW)] WHEN TG_OP='DELETE' THEN ARRAY[to_jsonb(OLD)] ELSE ARRAY[to_jsonb(OLD),to_jsonb(NEW)] END;
 FOREACH j IN ARRAY changed LOOP
 native_entry:=NULL;number:=NULL;receipt:=NULL;parent:=NULL;
 IF TG_TABLE_NAME='finance_entries' THEN native_entry:=j->>'id';number:=j->>'entry_number';
 ELSIF TG_TABLE_NAME IN('finance_entry_lines','finance_posting_effects') THEN native_entry:=j->>'entry_id';
 ELSIF TG_TABLE_NAME='finance_entry_line_dimensions' THEN SELECT entry_id INTO native_entry FROM reconforge.finance_entry_lines WHERE tenant_id=j->>'tenant_id' AND id=j->>'entry_line_id';
 ELSIF TG_TABLE_NAME='procurement_partial_receipts' THEN receipt:=j->>'id';
 ELSIF TG_TABLE_NAME='procurement_partial_orders' THEN parent:=j->>'id';
 END IF;
 IF TG_TABLE_NAME='finance_posting_effects' AND j->>'reverses_effect_id' IS NOT NULL THEN
 SELECT entry_id INTO native_entry FROM reconforge.finance_posting_effects WHERE tenant_id=j->>'tenant_id' AND id=j->>'reverses_effect_id'; END IF;
 IF native_entry IS NOT NULL AND number IS NULL THEN SELECT entry_number INTO number FROM reconforge.finance_entries WHERE tenant_id=j->>'tenant_id' AND id=native_entry; END IF;
 IF upper(COALESCE(number,'')) LIKE 'LC1-%' AND NOT EXISTS(SELECT 1 FROM reconforge.landed_cost_plans WHERE tenant_id=j->>'tenant_id' AND entry_id=native_entry) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='landed_cost_owner_phase',MESSAGE='Reserved landed cost GL entry requires its source owner'; END IF;
 FOR p IN SELECT * FROM reconforge.landed_cost_plans WHERE tenant_id=j->>'tenant_id' AND
 (id=j->>'plan_id' OR (TG_TABLE_NAME='landed_cost_plans' AND id=j->>'id') OR entry_id=native_entry OR order_id=parent
 OR EXISTS(SELECT 1 FROM reconforge.landed_cost_allocations a WHERE a.tenant_id=j->>'tenant_id' AND a.plan_id=landed_cost_plans.id AND a.receipt_id=receipt)
 OR (TG_TABLE_NAME='domain_audit_events' AND id=j->>'object_id') OR (TG_TABLE_NAME='outbox_events' AND id=j->>'aggregate_id')) LOOP
 PERFORM reconforge.landed_cost_close(p.tenant_id,p.id);
 END LOOP;
 END LOOP;
 RETURN NULL;
END $lc$;
DO $lc$ DECLARE n TEXT; BEGIN
 FOREACH n IN ARRAY ARRAY['landed_cost_plans','landed_cost_allocations','landed_cost_reviews','landed_cost_links','landed_cost_commands'] LOOP
 EXECUTE format('ALTER TABLE reconforge.%I ENABLE ROW LEVEL SECURITY',n);
 EXECUTE format('ALTER TABLE reconforge.%I FORCE ROW LEVEL SECURITY',n);
 IF n='landed_cost_plans' THEN
 EXECUTE format('CREATE POLICY scope ON reconforge.%I USING(reconforge.irp_scope(tenant_id,workspace_id,organization_id,legal_entity_id)) WITH CHECK(reconforge.irp_scope(tenant_id,workspace_id,organization_id,legal_entity_id))',n);
 ELSE
 EXECUTE format('CREATE POLICY scope ON reconforge.%I USING(EXISTS(SELECT 1 FROM reconforge.landed_cost_plans p WHERE p.tenant_id=%I.tenant_id AND p.id=%I.plan_id)) WITH CHECK(EXISTS(SELECT 1 FROM reconforge.landed_cost_plans p WHERE p.tenant_id=%I.tenant_id AND p.id=%I.plan_id))',n,n,n,n,n);
 END IF;
 EXECUTE format('CREATE TRIGGER retained BEFORE INSERT OR UPDATE OR DELETE ON reconforge.%I FOR EACH ROW EXECUTE FUNCTION reconforge.landed_cost_protect()',n);
 END LOOP;
 FOREACH n IN ARRAY ARRAY['landed_cost_plans','landed_cost_allocations','landed_cost_reviews','landed_cost_links','landed_cost_commands',
 'finance_entries','finance_entry_lines','finance_entry_line_dimensions','finance_posting_effects','procurement_partial_orders','procurement_partial_receipts','domain_audit_events','outbox_events'] LOOP
 EXECUTE format('CREATE CONSTRAINT TRIGGER landed_cost_closure AFTER INSERT OR UPDATE OR DELETE ON reconforge.%I DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION reconforge.landed_cost_reverse_close()',n);
 END LOOP;
END $lc$;
"""

DOWNGRADE_SQL = r"""
DO $lc$ BEGIN IF EXISTS(SELECT 1 FROM reconforge.landed_cost_plans) THEN
 RAISE EXCEPTION 'Retained landed costs prohibit downgrade; restore a verified pre-upgrade backup'; END IF; END $lc$;
DO $lc$ DECLARE n TEXT; BEGIN
 FOREACH n IN ARRAY ARRAY['landed_cost_plans','landed_cost_allocations','landed_cost_reviews','landed_cost_links','landed_cost_commands',
 'finance_entries','finance_entry_lines','finance_entry_line_dimensions','finance_posting_effects','procurement_partial_orders','procurement_partial_receipts','domain_audit_events','outbox_events'] LOOP
 EXECUTE format('DROP TRIGGER landed_cost_closure ON reconforge.%I',n); END LOOP;
END $lc$;
DROP FUNCTION reconforge.pp_verify_multiline(TEXT,TEXT);
ALTER FUNCTION reconforge.pp_verify_multiline_pre_landed(TEXT,TEXT) RENAME TO pp_verify_multiline;
DROP FUNCTION reconforge.landed_cost_reverse_close();
DROP FUNCTION reconforge.landed_cost_close(TEXT,TEXT);
DROP FUNCTION reconforge.landed_cost_ack(TEXT,TEXT,INTEGER);
DROP FUNCTION reconforge.landed_cost_event(TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT);
DROP TABLE reconforge.landed_cost_commands,reconforge.landed_cost_links,reconforge.landed_cost_reviews,reconforge.landed_cost_allocations,reconforge.landed_cost_plans;
DROP FUNCTION reconforge.landed_cost_protect();
DROP FUNCTION reconforge.landed_cost_command_admit();
"""


def install_postgres_landed_cost(connection: Any) -> None:
    row = connection.execute("SELECT to_regclass('reconforge.landed_cost_plans') AS installed").fetchone()
    if (row["installed"] if isinstance(row, Mapping) else row[0]) is not None:
        return
    with connection.transaction():
        connection.execute(UPGRADE_SQL)
