"""Additive reviewed classification and OB1 source closure; all guards are invoker scoped."""

from __future__ import annotations

from typing import Any

UPGRADE_SQL = r"""
DO $preflight$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname=current_user AND (rolsuper OR rolbypassrls)) THEN
 RAISE EXCEPTION 'Financial reporting installation requires an authorized migration administrator.'; END IF;
 IF to_regclass('reconforge.financial_opening_plans') IS NULL AND EXISTS(
 SELECT 1 FROM reconforge.finance_entries WHERE upper(left(entry_number,4))='OB1-' OR upper(left(id,4))='OB1-') THEN
 RAISE EXCEPTION 'OB1 namespace contains historical entries; explicit migration is required.'; END IF;
END $preflight$;
CREATE TABLE IF NOT EXISTS reconforge.financial_reporting_maps (
 tenant_id TEXT NOT NULL,id TEXT NOT NULL,workspace_id TEXT NOT NULL,organization_id TEXT NOT NULL,legal_entity_id TEXT NOT NULL,
 preparer_actor_id TEXT NOT NULL,map_digest TEXT NOT NULL CHECK(map_digest ~ '^[0-9a-f]{64}$'),
 payload JSONB NOT NULL CHECK(jsonb_typeof(payload)='object' AND octet_length(payload::text)<=524288),
 audit_event_id TEXT NOT NULL,outbox_event_id TEXT NOT NULL,created_at TEXT NOT NULL,
 PRIMARY KEY(tenant_id,id),UNIQUE(tenant_id,id,workspace_id,organization_id,legal_entity_id),
 FOREIGN KEY(tenant_id,workspace_id) REFERENCES reconforge.domain_workspaces(tenant_id,id),
 FOREIGN KEY(tenant_id,organization_id) REFERENCES reconforge.organizations(tenant_id,id),
 FOREIGN KEY(tenant_id,legal_entity_id) REFERENCES reconforge.legal_entities(tenant_id,id),
 FOREIGN KEY(tenant_id,preparer_actor_id) REFERENCES reconforge.identity_users(tenant_id,id),
 FOREIGN KEY(tenant_id,audit_event_id) REFERENCES reconforge.domain_audit_events(tenant_id,id),
 FOREIGN KEY(tenant_id,outbox_event_id) REFERENCES reconforge.outbox_events(tenant_id,event_id)
);
CREATE TABLE IF NOT EXISTS reconforge.financial_reporting_map_reviews (
 tenant_id TEXT NOT NULL,map_id TEXT NOT NULL,reviewer_actor_id TEXT NOT NULL,map_digest TEXT NOT NULL,
 review_digest TEXT NOT NULL CHECK(review_digest ~ '^[0-9a-f]{64}$'),reason TEXT NOT NULL CHECK(reconforge.irp_text(reason,500)),
 audit_event_id TEXT NOT NULL,outbox_event_id TEXT NOT NULL,created_at TEXT NOT NULL,
 PRIMARY KEY(tenant_id,map_id),FOREIGN KEY(tenant_id,map_id) REFERENCES reconforge.financial_reporting_maps(tenant_id,id),
 FOREIGN KEY(tenant_id,reviewer_actor_id) REFERENCES reconforge.identity_users(tenant_id,id),
 FOREIGN KEY(tenant_id,audit_event_id) REFERENCES reconforge.domain_audit_events(tenant_id,id),
 FOREIGN KEY(tenant_id,outbox_event_id) REFERENCES reconforge.outbox_events(tenant_id,event_id)
);
CREATE TABLE IF NOT EXISTS reconforge.financial_opening_plans (
 tenant_id TEXT NOT NULL,id TEXT NOT NULL CHECK(left(id,4)='OB1-'),workspace_id TEXT NOT NULL,organization_id TEXT NOT NULL,legal_entity_id TEXT NOT NULL,
 map_id TEXT NOT NULL,entry_id TEXT NOT NULL,preparer_actor_id TEXT NOT NULL,
 plan_digest TEXT NOT NULL CHECK(plan_digest ~ '^[0-9a-f]{64}$'),validation_digest TEXT NOT NULL CHECK(validation_digest ~ '^[0-9a-f]{64}$'),
 payload JSONB NOT NULL CHECK(jsonb_typeof(payload)='object' AND octet_length(payload::text)<=131072),
 audit_event_id TEXT NOT NULL,outbox_event_id TEXT NOT NULL,created_at TEXT NOT NULL,
 PRIMARY KEY(tenant_id,id),UNIQUE(tenant_id,workspace_id,organization_id,legal_entity_id),UNIQUE(tenant_id,entry_id),
 FOREIGN KEY(tenant_id,map_id,workspace_id,organization_id,legal_entity_id) REFERENCES reconforge.financial_reporting_maps(tenant_id,id,workspace_id,organization_id,legal_entity_id),
 FOREIGN KEY(tenant_id,entry_id) REFERENCES reconforge.finance_entries(tenant_id,id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(tenant_id,preparer_actor_id) REFERENCES reconforge.identity_users(tenant_id,id),
 FOREIGN KEY(tenant_id,audit_event_id) REFERENCES reconforge.domain_audit_events(tenant_id,id),
 FOREIGN KEY(tenant_id,outbox_event_id) REFERENCES reconforge.outbox_events(tenant_id,event_id)
);
CREATE TABLE IF NOT EXISTS reconforge.financial_opening_reviews (
 tenant_id TEXT NOT NULL,plan_id TEXT NOT NULL,reviewer_actor_id TEXT NOT NULL,plan_digest TEXT NOT NULL,
 review_digest TEXT NOT NULL CHECK(review_digest ~ '^[0-9a-f]{64}$'),reason TEXT NOT NULL CHECK(reconforge.irp_text(reason,500)),
 audit_event_id TEXT NOT NULL,outbox_event_id TEXT NOT NULL,created_at TEXT NOT NULL,
 PRIMARY KEY(tenant_id,plan_id),FOREIGN KEY(tenant_id,plan_id) REFERENCES reconforge.financial_opening_plans(tenant_id,id),
 FOREIGN KEY(tenant_id,reviewer_actor_id) REFERENCES reconforge.identity_users(tenant_id,id),
 FOREIGN KEY(tenant_id,audit_event_id) REFERENCES reconforge.domain_audit_events(tenant_id,id),
 FOREIGN KEY(tenant_id,outbox_event_id) REFERENCES reconforge.outbox_events(tenant_id,event_id)
);
CREATE TABLE IF NOT EXISTS reconforge.financial_opening_links (
 tenant_id TEXT NOT NULL,plan_id TEXT NOT NULL,posting_effect_id TEXT NOT NULL,posted_actor_id TEXT NOT NULL,
 plan_digest TEXT NOT NULL,review_digest TEXT NOT NULL,reason TEXT NOT NULL CHECK(reconforge.irp_text(reason,500)),
 audit_event_id TEXT NOT NULL,outbox_event_id TEXT NOT NULL,created_at TEXT NOT NULL,
 PRIMARY KEY(tenant_id,plan_id),UNIQUE(tenant_id,posting_effect_id),
 FOREIGN KEY(tenant_id,plan_id) REFERENCES reconforge.financial_opening_plans(tenant_id,id),
 FOREIGN KEY(tenant_id,posting_effect_id) REFERENCES reconforge.finance_posting_effects(tenant_id,id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(tenant_id,posted_actor_id) REFERENCES reconforge.identity_users(tenant_id,id),
 FOREIGN KEY(tenant_id,audit_event_id) REFERENCES reconforge.domain_audit_events(tenant_id,id),
 FOREIGN KEY(tenant_id,outbox_event_id) REFERENCES reconforge.outbox_events(tenant_id,event_id)
);
CREATE TABLE IF NOT EXISTS reconforge.financial_reporting_commands (
 tenant_id TEXT NOT NULL,workspace_id TEXT NOT NULL,command_id TEXT NOT NULL CHECK(reconforge.irp_text(command_id,140)),
 operation TEXT NOT NULL CHECK(operation IN ('prepare_map','review_map','prepare_opening','review_opening','post_opening')),
 actor_id TEXT NOT NULL,object_id TEXT NOT NULL,request_digest TEXT NOT NULL CHECK(request_digest ~ '^[0-9a-f]{64}$'),
 request_json JSONB NOT NULL CHECK(jsonb_typeof(request_json)='object' AND octet_length(request_json::text)<=524288),
 result_json JSONB NOT NULL CHECK(jsonb_typeof(result_json)='object' AND octet_length(result_json::text)<=524288),
 PRIMARY KEY(tenant_id,workspace_id,command_id),FOREIGN KEY(tenant_id,actor_id) REFERENCES reconforge.identity_users(tenant_id,id)
);
CREATE INDEX IF NOT EXISTS financial_reporting_maps_scope ON reconforge.financial_reporting_maps(tenant_id,workspace_id,organization_id,legal_entity_id,created_at,id);

CREATE OR REPLACE FUNCTION reconforge.fr_event(t TEXT,i TEXT,w TEXT,o TEXT,e TEXT,a TEXT,b TEXT,actor TEXT,action TEXT,metadata JSONB)
 RETURNS BOOLEAN LANGUAGE sql STABLE SET search_path=pg_catalog AS $fr$
 SELECT EXISTS(SELECT 1 FROM reconforge.domain_audit_events x JOIN reconforge.outbox_events y ON y.tenant_id=x.tenant_id
 WHERE x.tenant_id=t AND x.id=a AND y.event_id=b AND x.actor_user_id=actor AND x.object_type='financial_reporting' AND x.object_id=i
 AND x.action=$9 AND x.metadata_json=$10 AND y.event_type=$9 AND y.aggregate_type='financial_reporting' AND y.aggregate_id=i
 AND y.payload=$10||jsonb_build_object('audit_event_id',a) AND (y.workspace_id,y.organization_id,y.legal_entity_id)=(w,o,e))
$fr$;
CREATE OR REPLACE FUNCTION reconforge.fr_snapshot(t TEXT,i TEXT,o TEXT,l TEXT) RETURNS JSONB LANGUAGE sql STABLE SET search_path=pg_catalog AS $fr$
 SELECT jsonb_build_object('schema_version','finance-entry-review-v1','entry',
 jsonb_build_object('organization_id',o,'legal_entity_id',l)||(SELECT jsonb_object_agg(key,value) FROM jsonb_each(to_jsonb(e)) WHERE key=ANY(ARRAY['id','workspace_id','journal_id','period_id','entry_number','posting_date','description','external_reference','source_type','currency_code','currency_precision','currency_rounding_policy','currency_registry_version','currency_registry_digest','preparer_actor_id','reverses_posting_id'])),
 'lines',(SELECT jsonb_agg(jsonb_build_object('line_number',x.line_number,'account_id',x.account_id,'description',x.description,'debit_minor',x.debit_minor,'credit_minor',x.credit_minor,
 'dimensions',COALESCE((SELECT jsonb_object_agg(d.dimension_id,d.dimension_value_id) FROM reconforge.finance_entry_line_dimensions d WHERE d.tenant_id=t AND d.entry_line_id=x.id),'{}'::jsonb)) ORDER BY x.line_number)
 FROM reconforge.finance_entry_lines x WHERE x.tenant_id=t AND x.entry_id=e.id))
 FROM reconforge.finance_entries e WHERE e.tenant_id=t AND e.id=i
$fr$;
CREATE OR REPLACE FUNCTION reconforge.fr_result(t TEXT,i TEXT,phase TEXT) RETURNS JSONB LANGUAGE plpgsql STABLE SET search_path=pg_catalog AS $fr$
DECLARE m RECORD;p RECORD;r RECORD;l RECORD;
BEGIN
 SELECT * INTO m FROM reconforge.financial_reporting_maps WHERE tenant_id=t AND id=i;
 IF m IS NOT NULL THEN
 SELECT * INTO r FROM reconforge.financial_reporting_map_reviews WHERE tenant_id=t AND map_id=i;
 RETURN m.payload||jsonb_build_object('map_digest',m.map_digest,'status',phase,'reviewer_actor_id',CASE WHEN phase='Reviewed' THEN r.reviewer_actor_id ELSE NULL END,'review_digest',CASE WHEN phase='Reviewed' THEN r.review_digest ELSE NULL END);
 END IF;
 SELECT * INTO p FROM reconforge.financial_opening_plans WHERE tenant_id=t AND id=i;
 SELECT * INTO r FROM reconforge.financial_opening_reviews WHERE tenant_id=t AND plan_id=i;
 SELECT * INTO l FROM reconforge.financial_opening_links WHERE tenant_id=t AND plan_id=i;
 RETURN p.payload||jsonb_build_object('plan_digest',p.plan_digest,'validation_digest',p.validation_digest,'status',phase,
 'reviewer_actor_id',CASE WHEN phase IN ('Reviewed','Posted') THEN r.reviewer_actor_id ELSE NULL END,
 'review_digest',CASE WHEN phase IN ('Reviewed','Posted') THEN r.review_digest ELSE NULL END,
 'posting_effect_id',CASE WHEN phase='Posted' THEN l.posting_effect_id ELSE NULL END);
END $fr$;
CREATE OR REPLACE FUNCTION reconforge.fr_map_close(t TEXT,i TEXT) RETURNS VOID LANGUAGE plpgsql SET search_path=pg_catalog AS $fr$
DECLARE m RECORD;r RECORD;a JSONB;
BEGIN
 SELECT * INTO m FROM reconforge.financial_reporting_maps WHERE tenant_id=t AND id=i;
 IF m IS NULL THEN RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='financial_reporting_owner_phase',MESSAGE='Reporting map source is required.'; END IF;
 IF reconforge.irp_digest(m.payload) IS DISTINCT FROM m.map_digest OR m.payload->>'contract_version' IS DISTINCT FROM 'financial-reporting-map-v1'
 OR (m.payload->>'id',m.payload->>'workspace_id',m.payload->>'organization_id',m.payload->>'legal_entity_id',m.payload->>'preparer_actor_id') IS DISTINCT FROM (m.id,m.workspace_id,m.organization_id,m.legal_entity_id,m.preparer_actor_id)
 OR jsonb_typeof(m.payload->'accounts')<>'array' OR jsonb_array_length(m.payload->'accounts') NOT BETWEEN 1 AND 1000
 OR (SELECT count(*) FROM jsonb_object_keys(m.payload))<>8
 OR NOT reconforge.irp_text(m.payload->>'name',160) OR NOT EXISTS(SELECT 1 FROM reconforge.identity_users WHERE tenant_id=t AND id=m.preparer_actor_id)
 OR NOT reconforge.fr_event(t,m.id,m.workspace_id,m.organization_id,m.legal_entity_id,m.audit_event_id,m.outbox_event_id,m.preparer_actor_id,'financial_reporting_map_prepared',jsonb_build_object('map_digest',m.map_digest))
 OR (SELECT count(DISTINCT x->>'account_id') FROM jsonb_array_elements(m.payload->'accounts') x)<>jsonb_array_length(m.payload->'accounts') THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='financial_reporting_owner_phase',MESSAGE='Reporting classification requires exact scope, closed unique accounts and preparation evidence.'; END IF;
 FOR a IN SELECT value FROM jsonb_array_elements(m.payload->'accounts') LOOP
 IF (SELECT count(*) FROM jsonb_object_keys(a))<>7 OR NOT reconforge.irp_text(a->>'account_id') OR NOT reconforge.irp_text(a->>'account_code',64) OR NOT reconforge.irp_text(a->>'account_name',240)
 OR a->>'normal_balance' NOT IN ('Debit','Credit') OR jsonb_typeof(a->'is_cash')<>'boolean'
 OR (CASE a->>'section' WHEN 'CurrentAsset' THEN 'Asset' WHEN 'NonCurrentAsset' THEN 'Asset' WHEN 'CurrentLiability' THEN 'Liability' WHEN 'NonCurrentLiability' THEN 'Liability' WHEN 'Equity' THEN 'Equity' WHEN 'Income' THEN 'Income' WHEN 'Expense' THEN 'Expense' END) IS DISTINCT FROM a->>'account_type'
 OR ((a->>'is_cash')::boolean AND a->>'section'<>'CurrentAsset') THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='financial_reporting_owner_phase',MESSAGE='Reporting account classification is malformed or incompatible.'; END IF;
 END LOOP;
 SELECT * INTO r FROM reconforge.financial_reporting_map_reviews WHERE tenant_id=t AND map_id=i;
 IF r IS NOT NULL AND (r.reviewer_actor_id=m.preparer_actor_id OR r.map_digest<>m.map_digest
 OR r.review_digest IS DISTINCT FROM reconforge.irp_digest(jsonb_build_object('map_id',i,'map_digest',m.map_digest,'reviewer_actor_id',r.reviewer_actor_id,'reason',r.reason))
 OR NOT EXISTS(SELECT 1 FROM reconforge.identity_users WHERE tenant_id=t AND id=r.reviewer_actor_id)
 OR NOT reconforge.fr_event(t,m.id,m.workspace_id,m.organization_id,m.legal_entity_id,r.audit_event_id,r.outbox_event_id,r.reviewer_actor_id,'financial_reporting_map_reviewed',jsonb_build_object('map_digest',m.map_digest,'review_digest',r.review_digest))) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='financial_reporting_owner_phase',MESSAGE='Classification review requires independent exact human evidence.'; END IF;
 IF NOT EXISTS(SELECT 1 FROM reconforge.financial_reporting_commands WHERE tenant_id=t AND object_id=i AND operation='prepare_map' AND actor_id=m.preparer_actor_id)
 OR (r IS NOT NULL AND NOT EXISTS(SELECT 1 FROM reconforge.financial_reporting_commands WHERE tenant_id=t AND object_id=i AND operation='review_map' AND actor_id=r.reviewer_actor_id)) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='financial_reporting_owner_phase',MESSAGE='Classification phase requires its actual command.'; END IF;
END $fr$;
CREATE OR REPLACE FUNCTION reconforge.fr_opening_close(t TEXT,i TEXT) RETURNS VOID LANGUAGE plpgsql SET search_path=pg_catalog AS $fr$
DECLARE p RECORD;m RECORD;e RECORD;r RECORD;l RECORD;f RECORD;period RECORD;a JSONB;entry_line JSONB;captured JSONB;
BEGIN
 SELECT * INTO p FROM reconforge.financial_opening_plans WHERE tenant_id=t AND id=i;
 IF p IS NULL THEN RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='financial_reporting_owner_phase',MESSAGE='OB1 namespace requires an opening source owner.'; END IF;
 SELECT * INTO m FROM reconforge.financial_reporting_maps WHERE tenant_id=t AND id=p.map_id;
 SELECT * INTO e FROM reconforge.finance_entries WHERE tenant_id=t AND id=p.entry_id;
 SELECT * INTO period FROM reconforge.fiscal_periods WHERE tenant_id=t AND id=e.period_id AND application_workspace_id=p.workspace_id;
 captured:=reconforge.fr_snapshot(t,p.entry_id,p.organization_id,p.legal_entity_id);
 IF e IS NULL OR m IS NULL OR period IS NULL OR reconforge.irp_digest(p.payload) IS DISTINCT FROM p.plan_digest
 OR p.payload->>'contract_version' IS DISTINCT FROM 'financial-opening-v1' OR p.payload->'snapshot' IS DISTINCT FROM captured OR reconforge.irp_digest(captured) IS DISTINCT FROM p.validation_digest
 OR (p.payload->>'id',p.payload->>'entry_id',p.payload->>'workspace_id',p.payload->>'organization_id',p.payload->>'legal_entity_id',p.payload->>'map_id',p.payload->>'map_digest',p.payload->>'preparer_actor_id')
 IS DISTINCT FROM (p.id,p.entry_id,p.workspace_id,p.organization_id,p.legal_entity_id,p.map_id,m.map_digest,p.preparer_actor_id)
 OR (e.workspace_id,e.entry_number,e.external_reference,e.source_type,e.preparer_actor_id,e.reverses_posting_id)
 IS DISTINCT FROM (p.workspace_id,p.id,p.id,'Manual',p.preparer_actor_id,NULL::text)
 OR (p.payload->>'period_id',p.payload->>'posting_date',p.payload->>'reason',p.payload->>'currency_code',(p.payload->>'currency_precision')::integer,(p.payload->>'amount_minor')::bigint)
 IS DISTINCT FROM (e.period_id,e.posting_date,e.description,e.currency_code,e.currency_precision,e.total_debit_minor)
 OR p.id IS DISTINCT FROM 'OB1-'||upper(left(reconforge.irp_digest(jsonb_build_array(t,jsonb_build_object('workspace_id',p.workspace_id,'organization_id',p.organization_id,'legal_entity_id',p.legal_entity_id))),32))
 OR NOT EXISTS(SELECT 1 FROM reconforge.finance_journals j WHERE j.tenant_id=t AND j.id=e.journal_id AND j.journal_code=p.payload->>'journal_code')
 OR e.total_debit_minor<>e.total_credit_minor OR e.total_debit_minor NOT BETWEEN 1 AND 9000000000000000000 OR e.posting_date<>period.start_date::text
 OR (SELECT count(*) FROM jsonb_object_keys(p.payload))<>20
 OR jsonb_array_length(captured->'lines') NOT BETWEEN 2 AND 64 OR jsonb_array_length(p.payload->'lines')<>jsonb_array_length(captured->'lines')
 OR (SELECT count(DISTINCT value->>'account_code') FROM jsonb_array_elements(p.payload->'lines'))<>jsonb_array_length(p.payload->'lines')
 OR NOT EXISTS(SELECT 1 FROM reconforge.financial_reporting_map_reviews WHERE tenant_id=t AND map_id=m.id)
 OR NOT EXISTS(SELECT 1 FROM reconforge.organizations o JOIN reconforge.legal_entities x ON x.tenant_id=o.tenant_id AND x.organization_id=o.id
 WHERE o.tenant_id=t AND o.id=p.organization_id AND x.id=p.legal_entity_id AND o.application_workspace_id=p.workspace_id
 AND (e.organization_code,e.entity_code,e.currency_code)=(o.organization_code,x.entity_code,x.currency_code)
 AND (p.payload->>'organization_code',p.payload->>'entity_code')=(o.organization_code,x.entity_code))
 OR NOT reconforge.fr_event(t,p.id,p.workspace_id,p.organization_id,p.legal_entity_id,p.audit_event_id,p.outbox_event_id,p.preparer_actor_id,'financial_opening_prepared',jsonb_build_object('plan_digest',p.plan_digest,'validation_digest',p.validation_digest)) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='financial_reporting_owner_phase',MESSAGE='Opening source, exact native money, scope, policy or preparation evidence differ.'; END IF;
 FOR a IN SELECT value FROM jsonb_array_elements(p.payload->'lines') LOOP
 SELECT value INTO entry_line FROM jsonb_array_elements(captured->'lines') x(value)
 JOIN jsonb_array_elements(m.payload->'accounts') y(account) ON account->>'account_id'=value->>'account_id'
 WHERE account->>'account_code'=a->>'account_code' AND account->>'account_type' IN ('Asset','Liability','Equity');
 IF entry_line IS NULL OR (a->>'debit_minor',a->>'credit_minor') IS DISTINCT FROM (entry_line->>'debit_minor',entry_line->>'credit_minor') THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='financial_reporting_owner_phase',MESSAGE='Opening lines must bind mapped balance-sheet accounts and exact amounts.'; END IF;
 END LOOP;
 SELECT * INTO r FROM reconforge.financial_opening_reviews WHERE tenant_id=t AND plan_id=i;
 SELECT * INTO l FROM reconforge.financial_opening_links WHERE tenant_id=t AND plan_id=i;
 SELECT * INTO f FROM reconforge.finance_posting_effects WHERE tenant_id=t AND entry_id=p.entry_id;
 IF r IS NULL THEN
 IF e.status<>'Draft' OR f IS NOT NULL OR l IS NOT NULL OR e.validator_actor_id IS NOT NULL THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='financial_reporting_owner_phase',MESSAGE='Draft opening cannot acquire detached validation or posting.'; END IF;
 ELSE
 IF e.status<>'Validated' OR r.reviewer_actor_id=p.preparer_actor_id OR r.plan_digest<>p.plan_digest OR e.validator_actor_id<>r.reviewer_actor_id OR e.validation_digest<>p.validation_digest
 OR r.review_digest IS DISTINCT FROM reconforge.irp_digest(jsonb_build_object('opening_id',i,'plan_digest',p.plan_digest,'reviewer_actor_id',r.reviewer_actor_id,'reason',r.reason))
 OR NOT reconforge.fr_event(t,p.id,p.workspace_id,p.organization_id,p.legal_entity_id,r.audit_event_id,r.outbox_event_id,r.reviewer_actor_id,'financial_opening_reviewed',jsonb_build_object('plan_digest',p.plan_digest,'review_digest',r.review_digest)) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='financial_reporting_owner_phase',MESSAGE='Opening validation requires exact independent owner review.'; END IF;
 END IF;
 IF (f IS NULL)<>(l IS NULL) THEN RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='financial_reporting_owner_phase',MESSAGE='Opening requires its complete immutable source/GL link.'; END IF;
 IF l IS NOT NULL AND (r IS NULL OR l.posting_effect_id<>f.id OR l.posted_actor_id<>f.posted_actor_id OR l.posted_actor_id IN (p.preparer_actor_id,r.reviewer_actor_id)
 OR l.plan_digest<>p.plan_digest OR l.review_digest<>r.review_digest OR f.snapshot_json IS DISTINCT FROM captured OR f.reason<>l.reason
 OR f.source_kind<>'Manual' OR f.source_id<>p.entry_id OR f.reverses_effect_id IS NOT NULL
 OR NOT reconforge.fr_event(t,p.id,p.workspace_id,p.organization_id,p.legal_entity_id,l.audit_event_id,l.outbox_event_id,l.posted_actor_id,'financial_opening_posted',jsonb_build_object('plan_digest',p.plan_digest,'review_digest',r.review_digest,'posting_effect_id',f.id))) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='financial_reporting_owner_phase',MESSAGE='Opening posting requires a third human and complete exact financial evidence.'; END IF;
 IF EXISTS(SELECT 1 FROM reconforge.finance_posting_effects x JOIN reconforge.finance_entries y ON y.tenant_id=x.tenant_id AND y.id=x.entry_id
 WHERE x.tenant_id=t AND (x.workspace_id,x.organization_id,x.legal_entity_id)=(p.workspace_id,p.organization_id,p.legal_entity_id)
 AND x.entry_id<>p.entry_id AND (l IS NULL OR y.posting_date<e.posting_date)) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='financial_reporting_owner_phase',MESSAGE='Opening must precede all other retained entity posting history.'; END IF;
 IF EXISTS(SELECT 1 FROM reconforge.finance_posting_effects WHERE tenant_id=t AND reverses_effect_id=f.id) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='financial_reporting_owner_phase',MESSAGE='Opening correction requires a separately reviewed adjustment, preserving initial history.'; END IF;
 IF NOT EXISTS(SELECT 1 FROM reconforge.financial_reporting_commands WHERE tenant_id=t AND object_id=i AND operation='prepare_opening' AND actor_id=p.preparer_actor_id)
 OR (r IS NOT NULL AND NOT EXISTS(SELECT 1 FROM reconforge.financial_reporting_commands WHERE tenant_id=t AND object_id=i AND operation='review_opening' AND actor_id=r.reviewer_actor_id))
 OR (l IS NOT NULL AND NOT EXISTS(SELECT 1 FROM reconforge.financial_reporting_commands WHERE tenant_id=t AND object_id=i AND operation='post_opening' AND actor_id=l.posted_actor_id)) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='financial_reporting_owner_phase',MESSAGE='Opening phases require actual exact command acknowledgements.'; END IF;
END $fr$;
CREATE OR REPLACE FUNCTION reconforge.fr_immutable() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $fr$
 BEGIN RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='financial_reporting_owner_phase',MESSAGE='Reporting classifications, opening sources and phase evidence are immutable.'; END $fr$;
CREATE OR REPLACE FUNCTION reconforge.fr_admit() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $fr$
DECLARE payload JSONB;row_scope RECORD;a JSONB;identifier TEXT;
BEGIN
 IF TG_TABLE_NAME='financial_reporting_commands' THEN
 IF (NEW.operation='prepare_map' AND EXISTS(SELECT 1 FROM reconforge.financial_reporting_map_reviews WHERE tenant_id=NEW.tenant_id AND map_id=NEW.object_id))
 OR (NEW.operation='prepare_opening' AND EXISTS(SELECT 1 FROM reconforge.financial_opening_reviews WHERE tenant_id=NEW.tenant_id AND plan_id=NEW.object_id))
 OR (NEW.operation IN ('prepare_opening','review_opening') AND EXISTS(SELECT 1 FROM reconforge.financial_opening_links WHERE tenant_id=NEW.tenant_id AND plan_id=NEW.object_id)) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='financial_reporting_owner_phase',MESSAGE='A new acknowledgement must belong to the actual current owner phase.'; END IF;
 RETURN NEW;
 ELSIF TG_TABLE_NAME='financial_reporting_maps' THEN payload:=NEW.payload;row_scope:=NEW;
 ELSIF TG_TABLE_NAME='financial_reporting_map_reviews' THEN
 SELECT * INTO row_scope FROM reconforge.financial_reporting_maps WHERE tenant_id=NEW.tenant_id AND id=NEW.map_id;payload:=row_scope.payload;
 ELSIF TG_TABLE_NAME IN ('financial_opening_plans','financial_opening_reviews') THEN
 IF TG_TABLE_NAME='financial_opening_plans' THEN identifier:=NEW.map_id;
 ELSE SELECT map_id INTO identifier FROM reconforge.financial_opening_plans WHERE tenant_id=NEW.tenant_id AND id=NEW.plan_id; END IF;
 SELECT * INTO row_scope FROM reconforge.financial_reporting_maps WHERE tenant_id=NEW.tenant_id AND id=identifier;payload:=row_scope.payload;
 ELSE RETURN NEW; END IF;
 FOR a IN SELECT value FROM jsonb_array_elements(payload->'accounts') LOOP
 IF NOT EXISTS(SELECT 1 FROM reconforge.finance_accounts x WHERE x.tenant_id=NEW.tenant_id AND x.workspace_id=row_scope.workspace_id
 AND (x.id,x.account_code,x.name,x.account_type,x.normal_balance)=(a->>'account_id',a->>'account_code',a->>'account_name',a->>'account_type',a->>'normal_balance')) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='financial_reporting_owner_phase',MESSAGE='New classification and review must capture actual current native account semantics.'; END IF;
 END LOOP;
 RETURN NEW;
END $fr$;
CREATE OR REPLACE FUNCTION reconforge.fr_command_close(t TEXT,w TEXT,c TEXT) RETURNS VOID LANGUAGE plpgsql SET search_path=pg_catalog AS $fr$
DECLARE k RECORD;m RECORD;p RECORD;r RECORD;l RECORD;expected JSONB;request JSONB;phase TEXT;
BEGIN
 SELECT * INTO k FROM reconforge.financial_reporting_commands WHERE tenant_id=t AND workspace_id=w AND command_id=c;
 IF k IS NULL THEN RETURN; END IF;
 IF NOT EXISTS(SELECT 1 FROM reconforge.identity_users WHERE tenant_id=t AND id=k.actor_id AND NOT disabled)
 OR reconforge.irp_digest(k.request_json) IS DISTINCT FROM k.request_digest OR
 k.request_json IS DISTINCT FROM jsonb_build_object('operation',k.operation,'actor_id',k.actor_id,'request',k.request_json->'request') THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='financial_reporting_owner_phase',MESSAGE='Reporting command must retain its exact actor and request digest.'; END IF;
 IF k.operation IN ('prepare_map','review_map') THEN
 SELECT * INTO m FROM reconforge.financial_reporting_maps WHERE tenant_id=t AND id=k.object_id;
 SELECT * INTO r FROM reconforge.financial_reporting_map_reviews WHERE tenant_id=t AND map_id=k.object_id;
 IF m IS NULL OR m.workspace_id<>w THEN RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='financial_reporting_owner_phase',MESSAGE='Map command requires a scoped source.'; END IF;
 IF k.operation='prepare_map' THEN
 request:=jsonb_build_object('workspace_id',m.workspace_id,'organization_id',m.organization_id,'legal_entity_id',m.legal_entity_id,'name',m.payload->>'name','accounts',
 (SELECT jsonb_agg(jsonb_build_object('account_code',a->>'account_code','section',a->>'section','is_cash',a->'is_cash') ORDER BY a->>'account_code') FROM jsonb_array_elements(m.payload->'accounts') a));
 IF k.actor_id<>m.preparer_actor_id THEN RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='financial_reporting_owner_phase',MESSAGE='Map preparation actor differs.'; END IF;phase:='Draft';
 ELSE request:=jsonb_build_object('map_id',m.id,'expected_digest',m.map_digest,'reason',r.reason);
 IF r IS NULL OR k.actor_id<>r.reviewer_actor_id THEN RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='financial_reporting_owner_phase',MESSAGE='Map review actor differs.'; END IF;phase:='Reviewed'; END IF;
 ELSE
 SELECT * INTO p FROM reconforge.financial_opening_plans WHERE tenant_id=t AND id=k.object_id;
 SELECT * INTO r FROM reconforge.financial_opening_reviews WHERE tenant_id=t AND plan_id=k.object_id;
 SELECT * INTO l FROM reconforge.financial_opening_links WHERE tenant_id=t AND plan_id=k.object_id;
 IF p IS NULL OR p.workspace_id<>w THEN RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='financial_reporting_owner_phase',MESSAGE='Opening command requires a scoped source.'; END IF;
 IF k.operation='prepare_opening' THEN
 SELECT jsonb_object_agg(key,value) INTO request FROM jsonb_each(p.payload) WHERE key=ANY(ARRAY['workspace_id','organization_id','legal_entity_id','map_id','organization_code','entity_code','period_id','journal_code','posting_date','reason','lines']);
 IF k.actor_id<>p.preparer_actor_id THEN RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='financial_reporting_owner_phase',MESSAGE='Opening maker differs.'; END IF;phase:='Draft';
 ELSIF k.operation='review_opening' THEN request:=jsonb_build_object('opening_id',p.id,'expected_digest',p.plan_digest,'reason',r.reason);
 IF r IS NULL OR k.actor_id<>r.reviewer_actor_id THEN RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='financial_reporting_owner_phase',MESSAGE='Opening checker differs.'; END IF;phase:='Reviewed';
 ELSE request:=jsonb_build_object('opening_id',p.id,'expected_digest',p.plan_digest,'reason',l.reason);
 IF l IS NULL OR k.actor_id<>l.posted_actor_id THEN RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='financial_reporting_owner_phase',MESSAGE='Opening poster differs.'; END IF;phase:='Posted'; END IF;
 END IF;
 expected:=reconforge.fr_result(t,k.object_id,phase);
 IF k.request_json->'request' IS DISTINCT FROM request OR k.result_json IS DISTINCT FROM expected THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='financial_reporting_owner_phase',MESSAGE='Reporting command request or acknowledged phase differs from its actual source.'; END IF;
END $fr$;
CREATE OR REPLACE FUNCTION reconforge.fr_close_trigger() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $fr$
DECLARE d JSONB;old_data JSONB;candidate RECORD;identifier TEXT;
BEGIN
 d:=CASE WHEN TG_OP='DELETE' THEN to_jsonb(OLD) ELSE to_jsonb(NEW) END;old_data:=CASE WHEN TG_OP='INSERT' THEN '{}'::jsonb ELSE to_jsonb(OLD) END;
 IF TG_TABLE_NAME='financial_reporting_maps' THEN PERFORM reconforge.fr_map_close(d->>'tenant_id',d->>'id');
 ELSIF TG_TABLE_NAME='financial_reporting_map_reviews' THEN PERFORM reconforge.fr_map_close(d->>'tenant_id',d->>'map_id');
 ELSIF TG_TABLE_NAME='financial_reporting_commands' THEN
 PERFORM reconforge.fr_command_close(d->>'tenant_id',d->>'workspace_id',d->>'command_id');
 IF d->>'operation' IN ('prepare_map','review_map') THEN PERFORM reconforge.fr_map_close(d->>'tenant_id',d->>'object_id');
 ELSE PERFORM reconforge.fr_opening_close(d->>'tenant_id',d->>'object_id'); END IF;
 ELSIF TG_TABLE_NAME='financial_opening_plans' THEN PERFORM reconforge.fr_opening_close(d->>'tenant_id',d->>'id');
 ELSIF TG_TABLE_NAME IN ('financial_opening_reviews','financial_opening_links') THEN PERFORM reconforge.fr_opening_close(d->>'tenant_id',d->>'plan_id');
 ELSE
 IF TG_TABLE_NAME='finance_entries' AND (upper(left(d->>'entry_number',4))='OB1-' OR upper(left(d->>'id',4))='OB1-' OR upper(left(old_data->>'entry_number',4))='OB1-' OR upper(left(old_data->>'id',4))='OB1-')
 AND NOT EXISTS(SELECT 1 FROM reconforge.financial_opening_plans WHERE tenant_id=d->>'tenant_id' AND entry_id IN (d->>'id',old_data->>'id')) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='financial_reporting_owner_phase',MESSAGE='Reserved OB1 identifier has no retained opening owner.'; END IF;
 FOR candidate IN SELECT p.tenant_id,p.id FROM reconforge.financial_opening_plans p
 WHERE p.tenant_id=d->>'tenant_id' AND (
 (TG_TABLE_NAME='finance_entries' AND p.entry_id IN (d->>'id',old_data->>'id')) OR
 (TG_TABLE_NAME='finance_entry_lines' AND p.entry_id IN (d->>'entry_id',old_data->>'entry_id')) OR
 (TG_TABLE_NAME='finance_entry_line_dimensions' AND EXISTS(SELECT 1 FROM reconforge.finance_entry_lines x WHERE x.tenant_id=p.tenant_id AND x.entry_id=p.entry_id AND x.id IN (d->>'entry_line_id',old_data->>'entry_line_id'))) OR
 (TG_TABLE_NAME='finance_posting_effects' AND ((p.workspace_id,p.organization_id,p.legal_entity_id)=(d->>'workspace_id',d->>'organization_id',d->>'legal_entity_id') OR (p.workspace_id,p.organization_id,p.legal_entity_id)=(old_data->>'workspace_id',old_data->>'organization_id',old_data->>'legal_entity_id')))) LOOP
 PERFORM reconforge.fr_opening_close(candidate.tenant_id,candidate.id); END LOOP;
 END IF;
 RETURN NEW;
END $fr$;
CREATE OR REPLACE FUNCTION reconforge.fr_opening_lock() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $fr$
 BEGIN PERFORM pg_advisory_xact_lock(hashtextextended(reconforge.irp_canonical(jsonb_build_array(NEW.tenant_id,NEW.workspace_id,NEW.legal_entity_id,'financial_opening')),0)); RETURN NEW; END $fr$;
DO $install$ DECLARE n TEXT;
BEGIN
 FOREACH n IN ARRAY ARRAY['financial_reporting_maps','financial_reporting_map_reviews','financial_opening_plans','financial_opening_reviews','financial_opening_links','financial_reporting_commands'] LOOP
 EXECUTE format('ALTER TABLE reconforge.%I ENABLE ROW LEVEL SECURITY',n);EXECUTE format('ALTER TABLE reconforge.%I FORCE ROW LEVEL SECURITY',n);
 EXECUTE format('DROP POLICY IF EXISTS financial_reporting_scope ON reconforge.%I',n);
 IF n IN ('financial_reporting_maps','financial_opening_plans') THEN
 EXECUTE format('CREATE POLICY financial_reporting_scope ON reconforge.%I USING(reconforge.irp_scope(tenant_id,workspace_id,organization_id,legal_entity_id)) WITH CHECK(reconforge.irp_scope(tenant_id,workspace_id,organization_id,legal_entity_id))',n);
 ELSIF n='financial_reporting_map_reviews' THEN
 EXECUTE format('CREATE POLICY financial_reporting_scope ON reconforge.%I USING(EXISTS(SELECT 1 FROM reconforge.financial_reporting_maps m WHERE m.tenant_id=%I.tenant_id AND m.id=%I.map_id))',n,n,n);
 ELSIF n='financial_reporting_commands' THEN
 EXECUTE format('CREATE POLICY financial_reporting_scope ON reconforge.%I USING(EXISTS(SELECT 1 FROM reconforge.financial_reporting_maps m WHERE m.tenant_id=%I.tenant_id AND m.workspace_id=%I.workspace_id AND m.id=%I.object_id) OR EXISTS(SELECT 1 FROM reconforge.financial_opening_plans p WHERE p.tenant_id=%I.tenant_id AND p.workspace_id=%I.workspace_id AND p.id=%I.object_id))',n,n,n,n,n,n,n);
 ELSE EXECUTE format('CREATE POLICY financial_reporting_scope ON reconforge.%I USING(EXISTS(SELECT 1 FROM reconforge.financial_opening_plans p WHERE p.tenant_id=%I.tenant_id AND p.id=%I.plan_id))',n,n,n); END IF;
 EXECUTE format('DROP TRIGGER IF EXISTS financial_reporting_immutable ON reconforge.%I',n);
 EXECUTE format('CREATE TRIGGER financial_reporting_immutable BEFORE UPDATE OR DELETE ON reconforge.%I FOR EACH ROW EXECUTE FUNCTION reconforge.fr_immutable()',n);
 END LOOP;
 FOREACH n IN ARRAY ARRAY['financial_reporting_maps','financial_reporting_map_reviews','financial_opening_plans','financial_opening_reviews','financial_reporting_commands'] LOOP
 EXECUTE format('DROP TRIGGER IF EXISTS financial_reporting_admission ON reconforge.%I',n);
 EXECUTE format('CREATE TRIGGER financial_reporting_admission BEFORE INSERT ON reconforge.%I FOR EACH ROW EXECUTE FUNCTION reconforge.fr_admit()',n); END LOOP;
 FOREACH n IN ARRAY ARRAY['financial_opening_plans','finance_posting_effects'] LOOP
 EXECUTE format('DROP TRIGGER IF EXISTS financial_opening_namespace_lock ON reconforge.%I',n);
 EXECUTE format('CREATE TRIGGER financial_opening_namespace_lock BEFORE INSERT ON reconforge.%I FOR EACH ROW EXECUTE FUNCTION reconforge.fr_opening_lock()',n); END LOOP;
 FOREACH n IN ARRAY ARRAY['financial_reporting_maps','financial_reporting_map_reviews','financial_opening_plans','financial_opening_reviews','financial_opening_links','financial_reporting_commands','finance_entries','finance_entry_lines','finance_entry_line_dimensions','finance_posting_effects'] LOOP
 EXECUTE format('DROP TRIGGER IF EXISTS financial_reporting_closure ON reconforge.%I',n);
 EXECUTE format('CREATE CONSTRAINT TRIGGER financial_reporting_closure AFTER INSERT OR UPDATE OR DELETE ON reconforge.%I DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION reconforge.fr_close_trigger()',n); END LOOP;
END $install$;
"""

DOWNGRADE_SQL = r"""
DO $guard$ BEGIN
 IF EXISTS(SELECT 1 FROM reconforge.financial_reporting_maps) OR EXISTS(SELECT 1 FROM reconforge.financial_opening_plans) THEN
 RAISE EXCEPTION 'Reviewed reporting and financial opening history require forward recovery.'; END IF;
END $guard$;
DROP TRIGGER IF EXISTS financial_reporting_closure ON reconforge.finance_entries;
DROP TRIGGER IF EXISTS financial_reporting_closure ON reconforge.finance_entry_lines;
DROP TRIGGER IF EXISTS financial_reporting_closure ON reconforge.finance_entry_line_dimensions;
DROP TRIGGER IF EXISTS financial_reporting_closure ON reconforge.finance_posting_effects;
DROP TRIGGER IF EXISTS financial_opening_namespace_lock ON reconforge.finance_posting_effects;
DROP TABLE reconforge.financial_reporting_commands,reconforge.financial_opening_links,reconforge.financial_opening_reviews,reconforge.financial_opening_plans,reconforge.financial_reporting_map_reviews,reconforge.financial_reporting_maps;
DROP FUNCTION reconforge.fr_close_trigger(),reconforge.fr_command_close(TEXT,TEXT,TEXT),reconforge.fr_admit(),reconforge.fr_immutable(),reconforge.fr_opening_close(TEXT,TEXT),reconforge.fr_map_close(TEXT,TEXT),reconforge.fr_result(TEXT,TEXT,TEXT),reconforge.fr_snapshot(TEXT,TEXT,TEXT,TEXT),reconforge.fr_event(TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,JSONB),reconforge.fr_opening_lock();
"""


def install_postgres_financial_reporting_schema(connection: Any) -> None:
    with connection.transaction():
        connection.execute(UPGRADE_SQL)
