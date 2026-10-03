"""Database ownership and evidence closure for reviewed Inventory receipts.

Only the new receipt namespace is reserved. Existing manual Finance and ordinary
Inventory records keep their existing guards. All routines run as the invoker.
"""

from __future__ import annotations

from typing import Any

_TABLE_SQL = r"""
CREATE TABLE IF NOT EXISTS reconforge.inventory_receipt_plans (
 tenant_id TEXT NOT NULL,id TEXT NOT NULL,workspace_id TEXT NOT NULL,organization_id TEXT NOT NULL,legal_entity_id TEXT NOT NULL,
 source_number TEXT NOT NULL CHECK(source_number ~ '^[A-Z0-9][A-Z0-9._/-]{0,63}$'),
 operation TEXT NOT NULL CHECK(operation IN ('Receipt','FullReceiptReversal')),plan_version INTEGER NOT NULL CHECK(plan_version=1),
 period_id TEXT NOT NULL,posting_date DATE NOT NULL,item_id TEXT NOT NULL,uom_id TEXT NOT NULL,location_id TEXT NOT NULL,
 quantity_scaled BIGINT NOT NULL CHECK(quantity_scaled BETWEEN 1 AND 9000000000000000000),
 quantity_precision INTEGER NOT NULL CHECK(quantity_precision BETWEEN 0 AND 6),
 total_value_minor BIGINT NOT NULL CHECK(total_value_minor BETWEEN 1 AND 9000000000000000000),
 preparer_actor_id TEXT NOT NULL,preparer_username TEXT NOT NULL,prepared_at TEXT NOT NULL,reason TEXT NOT NULL CHECK(length(reason) BETWEEN 1 AND 500 AND reason=btrim(reason) AND reason !~ '[[:cntrl:]]'),
 currency_code TEXT NOT NULL CHECK(currency_code ~ '^[A-Z]{3}$'),currency_precision INTEGER NOT NULL CHECK(currency_precision BETWEEN 0 AND 8),
 currency_rounding_policy TEXT NOT NULL CHECK(currency_rounding_policy='ROUND_HALF_UP'),currency_registry_version TEXT NOT NULL,currency_registry_digest TEXT NOT NULL,
 policy_id TEXT NOT NULL,journal_id TEXT NOT NULL,inventory_account_id TEXT NOT NULL,receipt_clearing_account_id TEXT NOT NULL,
 mapping_digest TEXT NOT NULL CHECK(mapping_digest ~ '^[0-9a-f]{64}$'),original_plan_id TEXT,original_posting_effect_id TEXT,
 movement_id TEXT NOT NULL,movement_number TEXT NOT NULL,movement_line_id TEXT NOT NULL,
 valuation_document_id TEXT,valuation_number TEXT NOT NULL,input_cost_id TEXT,valuation_line_id TEXT,cost_layer_id TEXT NOT NULL,
 valuation_reversal_id TEXT,reversal_effect_id TEXT,finance_entry_id TEXT NOT NULL,finance_entry_number TEXT NOT NULL,
 finance_line_1_id TEXT NOT NULL,finance_line_2_id TEXT NOT NULL,posting_effect_id TEXT NOT NULL,
 finance_validation_digest TEXT NOT NULL CHECK(finance_validation_digest ~ '^[0-9a-f]{64}$'),
 plan_digest TEXT NOT NULL CHECK(plan_digest ~ '^[0-9a-f]{64}$'),plan_json JSONB NOT NULL CHECK(octet_length(plan_json::text)<=65536),
 preparation_audit_event_id TEXT NOT NULL,preparation_outbox_event_id TEXT NOT NULL,
 PRIMARY KEY(tenant_id,id),UNIQUE(tenant_id,id,workspace_id,organization_id,legal_entity_id),
 UNIQUE(tenant_id,workspace_id,organization_id,legal_entity_id,source_number),
 UNIQUE(tenant_id,movement_id),UNIQUE(tenant_id,workspace_id,movement_number),UNIQUE(tenant_id,movement_line_id),
 UNIQUE(tenant_id,valuation_document_id),UNIQUE(tenant_id,workspace_id,valuation_number),UNIQUE(tenant_id,input_cost_id),UNIQUE(tenant_id,valuation_line_id),
 UNIQUE(tenant_id,valuation_reversal_id),UNIQUE(tenant_id,reversal_effect_id),UNIQUE(tenant_id,finance_entry_id),
 UNIQUE(tenant_id,workspace_id,finance_entry_number),UNIQUE(tenant_id,finance_line_1_id),UNIQUE(tenant_id,finance_line_2_id),UNIQUE(tenant_id,posting_effect_id),
 FOREIGN KEY(tenant_id,workspace_id) REFERENCES reconforge.domain_workspaces(tenant_id,id),
 FOREIGN KEY(tenant_id,organization_id) REFERENCES reconforge.organizations(tenant_id,id),
 FOREIGN KEY(tenant_id,legal_entity_id) REFERENCES reconforge.legal_entities(tenant_id,id),
 FOREIGN KEY(tenant_id,preparer_actor_id) REFERENCES reconforge.identity_users(tenant_id,id),
 FOREIGN KEY(tenant_id,period_id) REFERENCES reconforge.fiscal_periods(tenant_id,id),
 FOREIGN KEY(tenant_id,item_id) REFERENCES reconforge.inventory_items(tenant_id,id),
 FOREIGN KEY(tenant_id,uom_id) REFERENCES reconforge.inventory_units_of_measure(tenant_id,id),
 FOREIGN KEY(tenant_id,location_id) REFERENCES reconforge.inventory_locations(tenant_id,id),
 FOREIGN KEY(tenant_id,policy_id) REFERENCES reconforge.inventory_valuation_policies(tenant_id,id),
 FOREIGN KEY(tenant_id,journal_id) REFERENCES reconforge.finance_journals(tenant_id,id),
 FOREIGN KEY(tenant_id,inventory_account_id) REFERENCES reconforge.finance_accounts(tenant_id,id),
 FOREIGN KEY(tenant_id,receipt_clearing_account_id) REFERENCES reconforge.finance_accounts(tenant_id,id),
 FOREIGN KEY(tenant_id,currency_registry_digest) REFERENCES reconforge.currency_registry_snapshots(tenant_id,registry_digest),
 FOREIGN KEY(tenant_id,original_plan_id) REFERENCES reconforge.inventory_receipt_plans(tenant_id,id),
 FOREIGN KEY(tenant_id,original_posting_effect_id) REFERENCES reconforge.finance_posting_effects(tenant_id,id),
 FOREIGN KEY(tenant_id,preparation_audit_event_id) REFERENCES reconforge.domain_audit_events(tenant_id,id),
 FOREIGN KEY(tenant_id,preparation_outbox_event_id) REFERENCES reconforge.outbox_events(tenant_id,event_id),
 CHECK((operation='Receipt' AND original_plan_id IS NULL AND original_posting_effect_id IS NULL AND valuation_document_id IS NOT NULL
  AND input_cost_id IS NOT NULL AND valuation_line_id IS NOT NULL AND valuation_reversal_id IS NULL AND reversal_effect_id IS NULL)
 OR (operation='FullReceiptReversal' AND original_plan_id IS NOT NULL AND original_posting_effect_id IS NOT NULL AND valuation_document_id IS NULL
  AND input_cost_id IS NULL AND valuation_line_id IS NULL AND valuation_reversal_id IS NOT NULL AND reversal_effect_id IS NOT NULL))
);
CREATE UNIQUE INDEX IF NOT EXISTS inventory_receipt_original_layer_idx ON reconforge.inventory_receipt_plans(tenant_id,cost_layer_id) WHERE operation='Receipt';
CREATE TABLE IF NOT EXISTS reconforge.inventory_receipt_reviews (
 tenant_id TEXT NOT NULL,id TEXT NOT NULL,workspace_id TEXT NOT NULL,organization_id TEXT NOT NULL,legal_entity_id TEXT NOT NULL,
 plan_id TEXT NOT NULL,plan_version INTEGER NOT NULL CHECK(plan_version=1),plan_digest TEXT NOT NULL,finance_validation_digest TEXT NOT NULL,
 reviewer_actor_id TEXT NOT NULL,reviewer_username TEXT NOT NULL,reviewed_at TEXT NOT NULL,reason TEXT NOT NULL CHECK(length(reason) BETWEEN 1 AND 500 AND reason=btrim(reason) AND reason !~ '[[:cntrl:]]'),
 review_digest TEXT NOT NULL CHECK(review_digest ~ '^[0-9a-f]{64}$'),review_json JSONB NOT NULL CHECK(octet_length(review_json::text)<=65536),
 audit_event_id TEXT NOT NULL,outbox_event_id TEXT NOT NULL,
 PRIMARY KEY(tenant_id,id),UNIQUE(tenant_id,plan_id),
 FOREIGN KEY(tenant_id,plan_id,workspace_id,organization_id,legal_entity_id)
 REFERENCES reconforge.inventory_receipt_plans(tenant_id,id,workspace_id,organization_id,legal_entity_id),
 FOREIGN KEY(tenant_id,reviewer_actor_id) REFERENCES reconforge.identity_users(tenant_id,id),
 FOREIGN KEY(tenant_id,audit_event_id) REFERENCES reconforge.domain_audit_events(tenant_id,id),
 FOREIGN KEY(tenant_id,outbox_event_id) REFERENCES reconforge.outbox_events(tenant_id,event_id)
);
CREATE TABLE IF NOT EXISTS reconforge.inventory_receipt_links (
 tenant_id TEXT NOT NULL,id TEXT NOT NULL,workspace_id TEXT NOT NULL,organization_id TEXT NOT NULL,legal_entity_id TEXT NOT NULL,
 plan_id TEXT NOT NULL,review_id TEXT NOT NULL,plan_digest TEXT NOT NULL,review_digest TEXT NOT NULL,
 movement_id TEXT NOT NULL,movement_line_id TEXT NOT NULL,valuation_document_id TEXT,input_cost_id TEXT,valuation_line_id TEXT,
 cost_layer_id TEXT NOT NULL,valuation_reversal_id TEXT,reversal_effect_id TEXT,finance_entry_id TEXT NOT NULL,
 finance_line_1_id TEXT NOT NULL,finance_line_2_id TEXT NOT NULL,posting_effect_id TEXT NOT NULL,
 original_plan_id TEXT,original_posting_effect_id TEXT,posted_actor_id TEXT NOT NULL,posted_at TEXT NOT NULL,
 reason TEXT NOT NULL CHECK(length(reason) BETWEEN 1 AND 500 AND reason=btrim(reason) AND reason !~ '[[:cntrl:]]'),audit_event_id TEXT NOT NULL,outbox_event_id TEXT NOT NULL,
 PRIMARY KEY(tenant_id,id),UNIQUE(tenant_id,plan_id),UNIQUE(tenant_id,review_id),UNIQUE(tenant_id,original_plan_id),
 UNIQUE(tenant_id,movement_id),UNIQUE(tenant_id,movement_line_id),UNIQUE(tenant_id,valuation_document_id),UNIQUE(tenant_id,input_cost_id),
 UNIQUE(tenant_id,valuation_line_id),UNIQUE(tenant_id,valuation_reversal_id),UNIQUE(tenant_id,reversal_effect_id),
 UNIQUE(tenant_id,finance_entry_id),UNIQUE(tenant_id,finance_line_1_id),UNIQUE(tenant_id,finance_line_2_id),UNIQUE(tenant_id,posting_effect_id),
 CHECK(id=plan_id),
 FOREIGN KEY(tenant_id,plan_id,workspace_id,organization_id,legal_entity_id)
 REFERENCES reconforge.inventory_receipt_plans(tenant_id,id,workspace_id,organization_id,legal_entity_id),
 FOREIGN KEY(tenant_id,review_id) REFERENCES reconforge.inventory_receipt_reviews(tenant_id,id),
 FOREIGN KEY(tenant_id,posted_actor_id) REFERENCES reconforge.identity_users(tenant_id,id),
 FOREIGN KEY(tenant_id,original_plan_id) REFERENCES reconforge.inventory_receipt_plans(tenant_id,id),
 FOREIGN KEY(tenant_id,original_posting_effect_id) REFERENCES reconforge.finance_posting_effects(tenant_id,id),
 FOREIGN KEY(tenant_id,movement_id) REFERENCES reconforge.inventory_movements(tenant_id,id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(tenant_id,movement_line_id) REFERENCES reconforge.inventory_movement_lines(tenant_id,id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(tenant_id,valuation_document_id) REFERENCES reconforge.inventory_valuation_documents(tenant_id,id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(tenant_id,input_cost_id) REFERENCES reconforge.inventory_valuation_input_costs(tenant_id,id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(tenant_id,valuation_line_id) REFERENCES reconforge.inventory_valuation_lines(tenant_id,id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(tenant_id,cost_layer_id) REFERENCES reconforge.inventory_cost_layers(tenant_id,id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(tenant_id,valuation_reversal_id) REFERENCES reconforge.inventory_valuation_reversals(tenant_id,id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(tenant_id,reversal_effect_id) REFERENCES reconforge.inventory_valuation_reversal_effects(tenant_id,id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(tenant_id,finance_entry_id) REFERENCES reconforge.finance_entries(tenant_id,id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(tenant_id,finance_line_1_id) REFERENCES reconforge.finance_entry_lines(tenant_id,id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(tenant_id,finance_line_2_id) REFERENCES reconforge.finance_entry_lines(tenant_id,id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(tenant_id,posting_effect_id) REFERENCES reconforge.finance_posting_effects(tenant_id,id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(tenant_id,audit_event_id) REFERENCES reconforge.domain_audit_events(tenant_id,id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(tenant_id,outbox_event_id) REFERENCES reconforge.outbox_events(tenant_id,event_id) DEFERRABLE INITIALLY DEFERRED
);
CREATE TABLE IF NOT EXISTS reconforge.inventory_receipt_commands (
 tenant_id TEXT NOT NULL,workspace_id TEXT NOT NULL,organization_id TEXT NOT NULL,legal_entity_id TEXT NOT NULL,
 command_id TEXT NOT NULL CHECK(length(command_id) BETWEEN 1 AND 160),
 operation TEXT NOT NULL CHECK(operation IN ('prepare_receipt','prepare_reversal','review','commit')),
 request_digest TEXT NOT NULL CHECK(request_digest ~ '^[0-9a-f]{64}$'),plan_id TEXT NOT NULL,actor_user_id TEXT NOT NULL,
 created_at TEXT NOT NULL,result_json JSONB NOT NULL CHECK(octet_length(result_json::text)<=65536),
 PRIMARY KEY(tenant_id,workspace_id,operation,command_id),
 FOREIGN KEY(tenant_id,plan_id,workspace_id,organization_id,legal_entity_id)
 REFERENCES reconforge.inventory_receipt_plans(tenant_id,id,workspace_id,organization_id,legal_entity_id),
 FOREIGN KEY(tenant_id,actor_user_id) REFERENCES reconforge.identity_users(tenant_id,id)
);
"""

_HELPER_SQL = r"""
CREATE OR REPLACE FUNCTION reconforge.irp_reserved(value TEXT) RETURNS BOOLEAN
LANGUAGE sql IMMUTABLE PARALLEL SAFE SET search_path=pg_catalog
AS $irp$ SELECT translate(left(value,5),'irp','IRP')='IRP1-' $irp$;
CREATE OR REPLACE FUNCTION reconforge.irp_canonical(value JSONB) RETURNS TEXT
LANGUAGE sql IMMUTABLE STRICT SET search_path=pg_catalog
AS $irp$ SELECT CASE jsonb_typeof(value)
 WHEN 'object' THEN (SELECT '{'||COALESCE(string_agg(to_jsonb(k)::text||':'||reconforge.irp_canonical(v),',' ORDER BY k COLLATE "C"),'')||'}' FROM jsonb_each(value) e(k,v))
 WHEN 'array' THEN (SELECT '['||COALESCE(string_agg(reconforge.irp_canonical(v),',' ORDER BY n),'')||']' FROM jsonb_array_elements(value) WITH ORDINALITY e(v,n))
 ELSE value::text END $irp$;
CREATE OR REPLACE FUNCTION reconforge.irp_digest(value JSONB) RETURNS TEXT
LANGUAGE sql IMMUTABLE STRICT SET search_path=pg_catalog
AS $irp$ SELECT encode(sha256(convert_to(reconforge.irp_canonical(value),'UTF8')),'hex') $irp$;
CREATE OR REPLACE FUNCTION reconforge.irp_bounded(value JSONB,depth INTEGER DEFAULT 0) RETURNS INTEGER
LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog AS $irp$
DECLARE child JSONB; nodes INTEGER:=1; kind TEXT:=jsonb_typeof(value);
BEGIN
 IF depth>12 OR value IS NULL OR octet_length(value::text)>65536 THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Receipt JSON exceeds its closed budget.'; END IF;
 IF kind='object' THEN
  IF (SELECT count(*) FROM jsonb_object_keys(value))>64 THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Receipt JSON exceeds its collection budget.'; END IF;
  FOR child IN SELECT v FROM jsonb_each(value) e(k,v) LOOP nodes:=nodes+reconforge.irp_bounded(child,depth+1); END LOOP;
 ELSIF kind='array' THEN
  IF jsonb_array_length(value)>64 THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Receipt JSON exceeds its collection budget.'; END IF;
  FOR child IN SELECT v FROM jsonb_array_elements(value) e(v) LOOP nodes:=nodes+reconforge.irp_bounded(child,depth+1); END LOOP;
 ELSIF kind='string' AND length(value#>>'{}')>2048 THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Receipt JSON exceeds its scalar budget.';
 ELSIF kind='number' AND value::text !~ '^-?(0|[1-9][0-9]*)$' THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Receipt JSON requires exact integer numbers.';
 END IF;
 IF nodes>2048 THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Receipt JSON exceeds its node budget.'; END IF;
 RETURN nodes;
END $irp$;
CREATE OR REPLACE FUNCTION reconforge.irp_text(value TEXT,maximum INTEGER DEFAULT 160) RETURNS BOOLEAN
LANGUAGE sql IMMUTABLE SET search_path=pg_catalog AS $irp$
 SELECT value IS NOT NULL AND length(value) BETWEEN 1 AND maximum AND value=btrim(value,E' \t\n\r\f'||chr(11)||chr(133)||chr(160)||chr(5760)||chr(8192)||chr(8193)||chr(8194)||chr(8195)||chr(8196)||chr(8197)||chr(8198)||chr(8199)||chr(8200)||chr(8201)||chr(8202)||chr(8232)||chr(8233)||chr(8239)||chr(8287)||chr(12288)) AND value !~ '[[:cntrl:]]'
$irp$;
CREATE OR REPLACE FUNCTION reconforge.irp_timestamp(value TEXT) RETURNS BOOLEAN
LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog AS $irp$
BEGIN
 IF NOT reconforge.irp_text(value,40) OR value !~ '^\d{4}-\d{2}-\d{2}T([01]\d|2[0-3]):[0-5]\d:[0-5]\d(\.\d{1,6})?(Z|\+00:00)$' THEN RETURN FALSE; END IF;
 PERFORM value::timestamptz;
 RETURN TRUE;
EXCEPTION WHEN datetime_field_overflow OR invalid_datetime_format THEN RETURN FALSE;
END $irp$;
CREATE OR REPLACE FUNCTION reconforge.irp_scope(t TEXT,w TEXT,o TEXT,e TEXT) RETURNS BOOLEAN
LANGUAGE sql STABLE SET search_path=pg_catalog AS $irp$
 SELECT t=current_setting('app.tenant_id',true)
 AND (NULLIF(current_setting('app.workspace_id',true),'') IS NULL OR w=current_setting('app.workspace_id',true))
 AND (NULLIF(current_setting('app.organization_id',true),'') IS NULL OR o=current_setting('app.organization_id',true))
 AND (NULLIF(current_setting('app.legal_entity_id',true),'') IS NULL OR e=current_setting('app.legal_entity_id',true))
 AND (NULLIF(current_setting('app.entity_id',true),'') IS NULL OR e=current_setting('app.entity_id',true))
 AND EXISTS(SELECT 1 FROM reconforge.organizations org JOIN reconforge.legal_entities ent ON ent.tenant_id=org.tenant_id AND ent.organization_id=org.id
 WHERE org.tenant_id=t AND org.id=o AND ent.id=e AND org.application_workspace_id=w)
$irp$;
CREATE OR REPLACE FUNCTION reconforge.irp_event(t TEXT,p TEXT,w TEXT,o TEXT,e TEXT,a TEXT,b TEXT,actor TEXT,action TEXT,metadata JSONB)
RETURNS BOOLEAN LANGUAGE sql STABLE SET search_path=pg_catalog AS $irp$
 SELECT EXISTS(SELECT 1 FROM reconforge.domain_audit_events audit JOIN reconforge.outbox_events event ON event.tenant_id=audit.tenant_id
 WHERE audit.tenant_id=t AND audit.id=a AND event.event_id=b AND audit.actor_user_id=actor
 AND audit.object_type='inventory_receipt_posting' AND audit.object_id=p AND audit.action=$9 AND audit.metadata_json=$10
 AND event.aggregate_type='inventory_receipt_posting' AND event.aggregate_id=p AND event.event_type=$9
 AND event.payload=$10||jsonb_build_object('audit_event_id',a)
 AND (event.workspace_id,event.organization_id,event.legal_entity_id)=(w,o,e))
$irp$;
"""


_PLAN_SQL = r"""
CREATE OR REPLACE FUNCTION reconforge.irp_admit(j JSONB) RETURNS VOID
LANGUAGE plpgsql SET search_path=pg_catalog AS $irp$
DECLARE s JSONB:=j->'scope'; v JSONB:=j->'source'; m JSONB:=j->'mapping'; c JSONB:=j->'currency_policy'; t TEXT:=current_setting('app.tenant_id',true); period RECORD; reference RECORD; chart TEXT;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Receipt mutations require READ COMMITTED.'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(jsonb_build_array(t,'finance_dimensions',s->>'workspace_id')::text,0));
 SELECT * INTO period FROM reconforge.fiscal_periods WHERE tenant_id=t AND id=v->>'period_id' FOR SHARE;
 IF period IS NULL OR period.status<>'Open' OR period.application_workspace_id IS DISTINCT FROM s->>'workspace_id'
 OR (v->>'posting_date')::date NOT BETWEEN period.start_date AND period.end_date THEN
 RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Receipt needs its current open scoped period.'; END IF;
 PERFORM 1 FROM reconforge.organizations o JOIN reconforge.legal_entities e ON e.tenant_id=o.tenant_id AND e.organization_id=o.id
 WHERE o.tenant_id=t AND o.id=s->>'organization_id' AND e.id=s->>'legal_entity_id'
 AND o.application_workspace_id=s->>'workspace_id' AND o.organization_code=s->>'organization_code' AND e.entity_code=s->>'entity_code'
 AND o.active AND e.active AND e.currency_code=c->>'currency_code' FOR SHARE OF o,e;
 IF NOT FOUND THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Receipt canonical authority or functional currency differs.'; END IF;
 PERFORM 1 FROM reconforge.inventory_items i JOIN reconforge.inventory_units_of_measure u ON u.tenant_id=i.tenant_id AND u.id=i.uom_id
 WHERE i.tenant_id=t AND i.id=v->>'item_id' AND i.uom_id=v->>'uom_id' AND i.workspace_id=s->>'workspace_id'
 AND (i.organization_id IS NULL OR i.organization_id=s->>'organization_id') AND i.active AND u.active
 AND i.item_type='Stock' AND i.tracking_mode='None' AND u.decimal_places=(v->>'quantity_precision')::integer
 AND i.inventory_account_id=m->>'inventory_account_id' FOR SHARE OF i,u;
 IF NOT FOUND THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Receipt stock master differs from its source.'; END IF;
 PERFORM 1 FROM reconforge.inventory_locations l JOIN reconforge.inventory_warehouses w ON w.tenant_id=l.tenant_id AND w.id=l.warehouse_id
 WHERE l.tenant_id=t AND l.id=v->>'location_id' AND l.active AND w.active AND l.location_type='Internal' AND NOT l.allow_negative
 AND w.workspace_id=s->>'workspace_id' AND w.organization_id=s->>'organization_id'
 AND (w.legal_entity_id IS NULL OR w.legal_entity_id=s->>'legal_entity_id') FOR SHARE OF l,w;
 IF NOT FOUND THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Receipt location differs from its source scope.'; END IF;
 PERFORM 1 FROM reconforge.inventory_valuation_policies p WHERE p.tenant_id=t AND p.id=m->>'policy_id' AND p.active
 AND p.workspace_id=s->>'workspace_id' AND p.organization_id=s->>'organization_id' AND p.legal_entity_id=s->>'legal_entity_id'
 AND p.costing_method='FIFO' AND p.currency_code=c->>'currency_code' AND p.finance_journal_id=m->>'journal_id'
 AND p.receipt_clearing_account_id=m->>'receipt_clearing_account_id' AND p.cogs_account_id=m->>'cogs_account_id'
 AND p.adjustment_account_id=m->>'adjustment_account_id' FOR SHARE;
 IF NOT FOUND THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Receipt current mapping differs from its retained mapping.'; END IF;
 SELECT chart_id INTO chart FROM reconforge.finance_journals WHERE tenant_id=t AND id=m->>'journal_id';
 FOR reference IN SELECT * FROM (VALUES ('finance_charts',chart),('finance_journals',m->>'journal_id'),
  ('finance_accounts',m->>'inventory_account_id'),('finance_accounts',m->>'receipt_clearing_account_id'),
  ('finance_accounts',m->>'cogs_account_id'),('finance_accounts',m->>'adjustment_account_id')) x(table_name,id)
  ORDER BY table_name COLLATE "C",id COLLATE "C" LOOP
  PERFORM pg_advisory_xact_lock(hashtextextended(jsonb_build_array(t,reference.table_name,reference.id)::text,0));
 END LOOP;
 PERFORM 1 FROM reconforge.finance_journals jn JOIN reconforge.finance_charts ch ON ch.tenant_id=jn.tenant_id AND ch.id=jn.chart_id
 JOIN reconforge.finance_accounts a ON a.tenant_id=jn.tenant_id AND a.chart_id=jn.chart_id
 JOIN reconforge.finance_accounts b ON b.tenant_id=jn.tenant_id AND b.chart_id=jn.chart_id
 JOIN reconforge.finance_accounts acogs ON acogs.tenant_id=jn.tenant_id AND acogs.chart_id=jn.chart_id
 JOIN reconforge.finance_accounts aadjust ON aadjust.tenant_id=jn.tenant_id AND aadjust.chart_id=jn.chart_id
 WHERE jn.tenant_id=t AND jn.id=m->>'journal_id' AND jn.active AND ch.active AND a.active AND b.active AND a.allow_posting AND b.allow_posting
 AND a.id=m->>'inventory_account_id' AND b.id=m->>'receipt_clearing_account_id' AND a.id<>b.id
 AND acogs.id=m->>'cogs_account_id' AND aadjust.id=m->>'adjustment_account_id' AND acogs.active AND aadjust.active AND acogs.allow_posting AND aadjust.allow_posting
 AND jn.workspace_id=s->>'workspace_id' AND jn.organization_code=s->>'organization_code' AND jn.currency_code=c->>'currency_code'
;
 IF NOT FOUND OR EXISTS(SELECT 1 FROM reconforge.finance_dimensions WHERE tenant_id=t AND workspace_id=s->>'workspace_id'
 AND active AND required_on_entries AND organization_code IN ('',s->>'organization_code')) THEN
 RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Receipt requires its active journal/accounts and no required dimensions.'; END IF;
 PERFORM 1 FROM reconforge.currencies WHERE tenant_id=t AND code=c->>'currency_code' AND active AND minor_units=(c->>'currency_precision')::integer FOR SHARE;
 IF NOT FOUND THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Receipt current currency differs from retained precision.'; END IF;
END $irp$;
CREATE OR REPLACE FUNCTION reconforge.guard_inventory_receipt_plan() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $irp$
DECLARE expected JSONB; scope JSONB; source JSONB; mapping JSONB; policy JSONB; artifacts JSONB; original JSONB:='null'; snapshot JSONB;
 origin reconforge.inventory_receipt_plans%ROWTYPE; digits TEXT; quantity_text TEXT; suffix TEXT; tag TEXT; key TEXT; output_id TEXT;
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Receipt plans are immutable.'; END IF;
 PERFORM reconforge.irp_bounded(NEW.plan_json);
 IF NEW.posting_date::text !~ '^\d{4}-\d{2}-\d{2}$' OR NOT reconforge.irp_text(NEW.reason,500) THEN
  RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Receipt source requires canonical date and reason.'; END IF;
 FOREACH key IN ARRAY ARRAY['workspace_id','organization_id','legal_entity_id','period_id','item_id','uom_id','location_id','preparer_actor_id','preparer_username',
 'currency_registry_version','preparation_audit_event_id','preparation_outbox_event_id'] LOOP
  IF NOT reconforge.irp_text(to_jsonb(NEW)->>key) THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Receipt source requires canonical bounded identifiers.'; END IF;
 END LOOP;
 FOR key,output_id IN SELECT * FROM jsonb_each_text(NEW.plan_json->'mapping') UNION ALL SELECT * FROM jsonb_each_text(NEW.plan_json->'scope') LOOP
  IF NOT reconforge.irp_text(output_id) THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Receipt mapping requires canonical bounded identifiers.'; END IF;
 END LOOP;
 IF NOT reconforge.irp_scope(NEW.tenant_id,NEW.workspace_id,NEW.organization_id,NEW.legal_entity_id) THEN
 RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Receipt plan is outside current canonical scope.'; END IF;
 SELECT jsonb_build_object('workspace_id',NEW.workspace_id,'organization_id',o.id,'legal_entity_id',e.id,
 'organization_code',o.organization_code,'entity_code',e.entity_code) INTO scope
 FROM reconforge.organizations o JOIN reconforge.legal_entities e ON e.tenant_id=o.tenant_id AND e.organization_id=o.id
 WHERE o.tenant_id=NEW.tenant_id AND o.id=NEW.organization_id AND e.id=NEW.legal_entity_id;
 digits:=lpad(NEW.quantity_scaled::text,greatest(length(NEW.quantity_scaled::text),NEW.quantity_precision+1),'0');
 quantity_text:=CASE WHEN NEW.quantity_precision=0 THEN digits ELSE left(digits,length(digits)-NEW.quantity_precision)||'.'||right(digits,NEW.quantity_precision) END;
 source:=jsonb_build_object('number',NEW.source_number,'posting_date',NEW.posting_date::text,'period_id',NEW.period_id,'item_id',NEW.item_id,'uom_id',NEW.uom_id,
 'location_id',NEW.location_id,'quantity_scaled',NEW.quantity_scaled,'quantity_precision',NEW.quantity_precision,'quantity_text',quantity_text,'total_value_minor',NEW.total_value_minor);
 mapping:=jsonb_build_object('policy_id',NEW.policy_id,'costing_method','FIFO','currency_code',NEW.currency_code,'journal_id',NEW.journal_id,
 'inventory_account_id',NEW.inventory_account_id,'receipt_clearing_account_id',NEW.receipt_clearing_account_id,
 'cogs_account_id',NEW.plan_json#>>'{mapping,cogs_account_id}','adjustment_account_id',NEW.plan_json#>>'{mapping,adjustment_account_id}');
 policy:=jsonb_build_object('currency_code',NEW.currency_code,'currency_precision',NEW.currency_precision,'currency_rounding_policy',NEW.currency_rounding_policy,
 'currency_registry_version',NEW.currency_registry_version,'currency_registry_digest',NEW.currency_registry_digest);
 IF NEW.id IS DISTINCT FROM 'IRP1-PLAN-'||left(reconforge.irp_digest(jsonb_build_array('inventory-receipt-plan-v1',NEW.workspace_id,NEW.organization_id,NEW.legal_entity_id,NEW.source_number)),32)
 OR NEW.mapping_digest IS DISTINCT FROM reconforge.irp_digest(mapping) THEN
 RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Receipt identity or mapping digest is not canonical.'; END IF;
 suffix:=left(encode(sha256(convert_to(NEW.id,'UTF8')),'hex'),32);
 artifacts:='{}';
 FOR key,tag IN SELECT * FROM (VALUES ('movement_id','MOV'),('movement_line_id','MOVL'),('valuation_document_id','VAL'),('input_cost_id','COST'),
 ('valuation_line_id','VALL'),('cost_layer_id','LAY'),('valuation_reversal_id','REV'),('reversal_effect_id','REVE'),('finance_entry_id','GLE'),
 ('finance_line_1_id','GLL1'),('finance_line_2_id','GLL2'),('posting_effect_id','PST')) v(k,t) LOOP
  output_id:='IRP1-'||tag||'-'||suffix;
  IF (NEW.operation='Receipt' AND key IN ('valuation_reversal_id','reversal_effect_id')) OR
   (NEW.operation='FullReceiptReversal' AND key IN ('valuation_document_id','input_cost_id','valuation_line_id')) THEN output_id:=NULL; END IF;
  IF NEW.operation='FullReceiptReversal' AND key='cost_layer_id' THEN output_id:=NEW.cost_layer_id; END IF;
  IF to_jsonb(NEW)->key IS DISTINCT FROM COALESCE(to_jsonb(output_id),'null'::jsonb) THEN
   RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Receipt output identity is not canonical.'; END IF;
  artifacts:=artifacts||jsonb_build_object(key,output_id);
 END LOOP;
 artifacts:=artifacts||jsonb_build_object('movement_number',upper(NEW.movement_id),
 'valuation_number',upper(COALESCE(NEW.valuation_document_id,NEW.valuation_reversal_id)),'finance_entry_number',upper(NEW.finance_entry_id));
 IF NEW.movement_number IS DISTINCT FROM artifacts->>'movement_number' OR NEW.valuation_number IS DISTINCT FROM artifacts->>'valuation_number'
 OR NEW.finance_entry_number IS DISTINCT FROM artifacts->>'finance_entry_number' THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Receipt output number is not canonical.'; END IF;
 IF NEW.operation='FullReceiptReversal' THEN
  SELECT * INTO origin FROM reconforge.inventory_receipt_plans WHERE tenant_id=NEW.tenant_id AND id=NEW.original_plan_id FOR SHARE;
  IF origin IS NULL OR origin.operation<>'Receipt' OR NOT EXISTS(SELECT 1 FROM reconforge.inventory_receipt_links WHERE tenant_id=NEW.tenant_id AND plan_id=origin.id)
  OR (origin.workspace_id,origin.organization_id,origin.legal_entity_id,origin.item_id,origin.uom_id,origin.location_id,origin.quantity_scaled,origin.quantity_precision,
   origin.total_value_minor,origin.mapping_digest,origin.currency_code,origin.currency_precision,origin.currency_rounding_policy,origin.currency_registry_version,origin.currency_registry_digest)
  IS DISTINCT FROM (NEW.workspace_id,NEW.organization_id,NEW.legal_entity_id,NEW.item_id,NEW.uom_id,NEW.location_id,NEW.quantity_scaled,NEW.quantity_precision,
   NEW.total_value_minor,NEW.mapping_digest,NEW.currency_code,NEW.currency_precision,NEW.currency_rounding_policy,NEW.currency_registry_version,NEW.currency_registry_digest)
  OR NEW.original_posting_effect_id IS DISTINCT FROM origin.posting_effect_id OR NEW.cost_layer_id IS DISTINCT FROM origin.cost_layer_id THEN
   RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Receipt inverse must bind its complete original effect.'; END IF;
  original:=jsonb_build_object('plan_id',origin.id,'posting_effect_id',origin.posting_effect_id,'valuation_document_id',origin.valuation_document_id,
   'valuation_line_id',origin.valuation_line_id,'cost_layer_id',origin.cost_layer_id);
 END IF;
 snapshot:=jsonb_build_object('schema_version','finance-entry-review-v1','entry',jsonb_build_object(
 'id',NEW.finance_entry_id,'workspace_id',NEW.workspace_id,'organization_id',NEW.organization_id,'legal_entity_id',NEW.legal_entity_id,
 'journal_id',NEW.journal_id,'period_id',NEW.period_id,'entry_number',NEW.finance_entry_number,'posting_date',NEW.posting_date::text,'description',NEW.reason,
 'external_reference',NEW.id,'source_type','Generated','preparer_actor_id',NEW.preparer_actor_id,'reverses_posting_id',NEW.original_posting_effect_id)||policy,
 'lines',jsonb_build_array(jsonb_build_object('line_number',1,'account_id',NEW.inventory_account_id,'description',NEW.reason,'dimensions','{}'::jsonb,
 'debit_minor',CASE WHEN NEW.operation='Receipt' THEN NEW.total_value_minor ELSE 0 END,'credit_minor',CASE WHEN NEW.operation='Receipt' THEN 0 ELSE NEW.total_value_minor END),
 jsonb_build_object('line_number',2,'account_id',NEW.receipt_clearing_account_id,'description',NEW.reason,'dimensions','{}'::jsonb,
 'debit_minor',CASE WHEN NEW.operation='Receipt' THEN 0 ELSE NEW.total_value_minor END,'credit_minor',CASE WHEN NEW.operation='Receipt' THEN NEW.total_value_minor ELSE 0 END)));
 expected:=jsonb_build_object('contract_version','inventory-receipt-plan-v1','plan_id',NEW.id,'plan_version',1,'operation',NEW.operation,
 'prepared_at',NEW.prepared_at,'reason',NEW.reason,'preparer',jsonb_build_object('user_id',NEW.preparer_actor_id,'username',NEW.preparer_username),
 'scope',scope,'source',source,'mapping',mapping,'mapping_digest',NEW.mapping_digest,'currency_policy',policy,'artifacts',artifacts,'original',original,
 'finance_snapshot',snapshot,'finance_validation_digest',NEW.finance_validation_digest,'plan_digest',NEW.plan_digest,
 'preparation_audit_event_id',NEW.preparation_audit_event_id,'preparation_outbox_event_id',NEW.preparation_outbox_event_id);
 IF NEW.plan_json IS DISTINCT FROM expected OR NEW.finance_validation_digest IS DISTINCT FROM reconforge.irp_digest(snapshot)
 OR NEW.plan_digest IS DISTINCT FROM reconforge.irp_digest(expected-ARRAY['plan_digest','preparation_audit_event_id','preparation_outbox_event_id'])
 OR NOT EXISTS(SELECT 1 FROM reconforge.identity_users WHERE tenant_id=NEW.tenant_id AND id=NEW.preparer_actor_id AND username=NEW.preparer_username AND NOT disabled)
 OR NOT reconforge.irp_timestamp(NEW.prepared_at) THEN
 RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Receipt plan must match exact retained content and identity.'; END IF;
 IF NOT EXISTS(SELECT 1 FROM reconforge.currency_registry_snapshots s CROSS JOIN LATERAL jsonb_array_elements(s.snapshot_json::jsonb->'currencies') c
 WHERE s.tenant_id=NEW.tenant_id AND s.registry_digest=NEW.currency_registry_digest AND s.registry_version=NEW.currency_registry_version
 AND s.snapshot_json::jsonb->>'registry_version'=NEW.currency_registry_version
 AND c->>'code'=NEW.currency_code AND c->'minor_units'=to_jsonb(NEW.currency_precision) AND c->>'rounding_policy'=NEW.currency_rounding_policy) THEN
 RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Receipt policy must match its retained currency snapshot.'; END IF;
 IF NOT reconforge.irp_event(NEW.tenant_id,NEW.id,NEW.workspace_id,NEW.organization_id,NEW.legal_entity_id,NEW.preparation_audit_event_id,NEW.preparation_outbox_event_id,
 NEW.preparer_actor_id,'inventory_receipt_prepared',jsonb_build_object('plan_digest',NEW.plan_digest,'finance_validation_digest',NEW.finance_validation_digest)) THEN
 RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Receipt preparation evidence must bind its exact content.'; END IF;
 PERFORM reconforge.irp_admit(expected);
 RETURN NEW;
END $irp$;
CREATE OR REPLACE FUNCTION reconforge.guard_inventory_receipt_review() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $irp$
DECLARE p reconforge.inventory_receipt_plans%ROWTYPE; expected JSONB;
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Receipt reviews are immutable.'; END IF;
 PERFORM reconforge.irp_bounded(NEW.review_json);
 SELECT * INTO p FROM reconforge.inventory_receipt_plans WHERE tenant_id=NEW.tenant_id AND id=NEW.plan_id FOR UPDATE;
 expected:=jsonb_build_object('contract_version','inventory-receipt-review-v1','review_id',NEW.id,'plan_id',NEW.plan_id,'plan_version',NEW.plan_version,
 'plan_digest',NEW.plan_digest,'finance_validation_digest',NEW.finance_validation_digest,'reviewer',jsonb_build_object('user_id',NEW.reviewer_actor_id,'username',NEW.reviewer_username),
 'reviewed_at',NEW.reviewed_at,'reason',NEW.reason,'review_digest',NEW.review_digest,'audit_event_id',NEW.audit_event_id,'outbox_event_id',NEW.outbox_event_id);
 IF p IS NULL OR (NEW.workspace_id,NEW.organization_id,NEW.legal_entity_id,NEW.plan_version,NEW.plan_digest,NEW.finance_validation_digest)
 IS DISTINCT FROM (p.workspace_id,p.organization_id,p.legal_entity_id,p.plan_version,p.plan_digest,p.finance_validation_digest)
 OR NOT reconforge.irp_text(NEW.reason,500) OR NOT reconforge.irp_text(NEW.reviewer_actor_id) OR NOT reconforge.irp_text(NEW.reviewer_username)
 OR NOT reconforge.irp_text(NEW.audit_event_id) OR NOT reconforge.irp_text(NEW.outbox_event_id)
 OR NEW.reviewer_actor_id=p.preparer_actor_id OR NEW.id IS DISTINCT FROM 'IRP1-REVIEW-'||left(encode(sha256(convert_to(p.id,'UTF8')),'hex'),32)
 OR NEW.review_json IS DISTINCT FROM expected OR NEW.review_digest IS DISTINCT FROM reconforge.irp_digest(expected-ARRAY['review_digest','audit_event_id','outbox_event_id'])
 OR NOT reconforge.irp_timestamp(NEW.reviewed_at)
 OR NOT EXISTS(SELECT 1 FROM reconforge.identity_users WHERE tenant_id=NEW.tenant_id AND id=NEW.reviewer_actor_id AND username=NEW.reviewer_username AND NOT disabled) THEN
 RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Receipt review requires independent exact retained provenance.'; END IF;
 IF NOT reconforge.irp_event(NEW.tenant_id,p.id,p.workspace_id,p.organization_id,p.legal_entity_id,NEW.audit_event_id,NEW.outbox_event_id,
 NEW.reviewer_actor_id,'inventory_receipt_reviewed',jsonb_build_object('plan_digest',p.plan_digest,'finance_validation_digest',p.finance_validation_digest,'review_digest',NEW.review_digest)) THEN
 RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Receipt review evidence must bind its exact content.'; END IF;
 PERFORM reconforge.irp_admit(p.plan_json);
 RETURN NEW;
END $irp$;
"""


_LINK_SQL = r"""
CREATE OR REPLACE FUNCTION reconforge.guard_inventory_receipt_link() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $irp$
DECLARE p reconforge.inventory_receipt_plans%ROWTYPE; r reconforge.inventory_receipt_reviews%ROWTYPE; k TEXT; layer RECORD;
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Receipt complete-source links are immutable.'; END IF;
 IF current_setting('transaction_isolation')<>'read committed' THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Receipt mutations require READ COMMITTED.'; END IF;
 SELECT * INTO p FROM reconforge.inventory_receipt_plans WHERE tenant_id=NEW.tenant_id AND id=NEW.plan_id FOR UPDATE;
 SELECT * INTO r FROM reconforge.inventory_receipt_reviews WHERE tenant_id=NEW.tenant_id AND id=NEW.review_id FOR SHARE;
 IF p IS NULL OR r IS NULL OR r.plan_id IS DISTINCT FROM p.id OR NEW.id IS DISTINCT FROM p.id
 OR NEW.plan_digest IS DISTINCT FROM p.plan_digest OR NEW.review_digest IS DISTINCT FROM r.review_digest
 OR NOT reconforge.irp_text(NEW.reason,500) OR NOT reconforge.irp_text(NEW.posted_actor_id)
 OR NOT reconforge.irp_text(NEW.audit_event_id) OR NOT reconforge.irp_text(NEW.outbox_event_id)
 OR NEW.posted_actor_id=p.preparer_actor_id OR NOT EXISTS(SELECT 1 FROM reconforge.identity_users WHERE tenant_id=NEW.tenant_id AND id=NEW.posted_actor_id AND NOT disabled)
 OR NOT reconforge.irp_timestamp(NEW.posted_at) THEN
 RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Receipt link requires its independently reviewed source.'; END IF;
 FOREACH k IN ARRAY ARRAY['workspace_id','organization_id','legal_entity_id','movement_id','movement_line_id','valuation_document_id','input_cost_id',
 'valuation_line_id','cost_layer_id','valuation_reversal_id','reversal_effect_id','finance_entry_id','finance_line_1_id','finance_line_2_id','posting_effect_id',
 'original_plan_id','original_posting_effect_id'] LOOP
  IF to_jsonb(NEW)->k IS DISTINCT FROM to_jsonb(p)->k THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Receipt link cannot substitute a source artifact.'; END IF;
 END LOOP;
 PERFORM reconforge.irp_admit(p.plan_json);
 PERFORM pg_advisory_xact_lock(hashtextextended(p.workspace_id||'|'||p.legal_entity_id||'|'||p.location_id||'|'||p.item_id||'|',0));
 PERFORM pg_advisory_xact_lock(hashtextextended(p.legal_entity_id||'|'||p.item_id||'|',0));
 IF EXISTS(SELECT 1 FROM reconforge.inventory_movements m WHERE m.tenant_id=p.tenant_id
  AND m.workspace_id=p.workspace_id AND m.organization_id=p.organization_id AND m.legal_entity_id=p.legal_entity_id
  AND m.status='Posted' AND m.movement_type<>'Transfer' AND (m.movement_date,m.movement_number)<(p.posting_date,p.movement_number)
  AND NOT EXISTS(SELECT 1 FROM reconforge.inventory_valuation_documents v WHERE v.tenant_id=m.tenant_id AND v.movement_id=m.id AND v.status='Approved')
  AND NOT EXISTS(SELECT 1 FROM reconforge.inventory_valuation_reversals prior_reverse WHERE prior_reverse.tenant_id=m.tenant_id AND prior_reverse.reversal_movement_id=m.id AND prior_reverse.status='Approved'))
 OR EXISTS(SELECT 1 FROM reconforge.inventory_movements m JOIN reconforge.inventory_valuation_documents v ON v.tenant_id=m.tenant_id AND v.movement_id=m.id
  WHERE m.tenant_id=p.tenant_id AND m.workspace_id=p.workspace_id AND m.organization_id=p.organization_id AND m.legal_entity_id=p.legal_entity_id
  AND v.status='Approved' AND (m.movement_date,m.movement_number)>(p.posting_date,p.movement_number)) THEN
  RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Receipt commit requires consistent FIFO posting chronology.';
 END IF;
 IF p.operation='FullReceiptReversal' THEN
  PERFORM pg_advisory_xact_lock(hashtextextended(p.cost_layer_id,0));
  SELECT * INTO layer FROM reconforge.inventory_cost_layers WHERE tenant_id=p.tenant_id AND id=p.cost_layer_id FOR UPDATE;
  IF layer IS NULL OR layer.remaining_quantity_scaled<>p.quantity_scaled OR layer.remaining_value_minor<>p.total_value_minor
  OR EXISTS(SELECT 1 FROM reconforge.inventory_layer_consumptions WHERE tenant_id=p.tenant_id AND cost_layer_id=p.cost_layer_id)
  OR EXISTS(SELECT 1 FROM reconforge.inventory_valuation_reversal_effects WHERE tenant_id=p.tenant_id AND cost_layer_id=p.cost_layer_id)
  OR EXISTS(SELECT 1 FROM reconforge.inventory_movements m JOIN reconforge.inventory_movement_lines l ON l.tenant_id=m.tenant_id AND l.movement_id=m.id
   WHERE m.tenant_id=p.tenant_id AND m.workspace_id=p.workspace_id AND m.organization_id=p.organization_id AND m.legal_entity_id=p.legal_entity_id
   AND l.item_id=p.item_id AND m.status IN ('Posted','Voided') AND m.id<>p.movement_id AND l.from_location_id IS NOT NULL) THEN
   RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Receipt inverse requires an unused original without outbound history.'; END IF;
 END IF;
 RETURN NEW;
END $irp$;
CREATE OR REPLACE FUNCTION reconforge.irp_artifact_expected(p reconforge.inventory_receipt_plans,table_name TEXT) RETURNS JSONB
LANGUAGE plpgsql STABLE SET search_path=pg_catalog AS $irp$
DECLARE common JSONB:=jsonb_build_object('tenant_id',p.tenant_id,'workspace_id',p.workspace_id,'organization_id',p.organization_id,'legal_entity_id',p.legal_entity_id);
 item JSONB:=jsonb_build_object('item_id',p.item_id,'uom_id',p.uom_id,'inventory_lot_id',NULL,'quantity_scaled',p.quantity_scaled,'quantity_precision',p.quantity_precision);
 inverse BOOLEAN:=p.operation='FullReceiptReversal'; original reconforge.inventory_receipt_plans%ROWTYPE;
BEGIN
 IF inverse THEN SELECT * INTO original FROM reconforge.inventory_receipt_plans WHERE tenant_id=p.tenant_id AND id=p.original_plan_id; END IF;
 CASE table_name
 WHEN 'inventory_movements' THEN RETURN common||jsonb_build_object('id',p.movement_id,'period_id',p.period_id,'movement_number',p.movement_number,
  'movement_type',CASE WHEN inverse THEN 'Delivery' ELSE 'Receipt' END,'movement_date',p.posting_date::text,'source_reference',p.id,'description',p.reason,'source_type','Generated','created_by',p.preparer_username);
 WHEN 'inventory_movement_lines' THEN RETURN item||jsonb_build_object('tenant_id',p.tenant_id,'id',p.movement_line_id,'movement_id',p.movement_id,'line_number',1,
  'from_location_id',CASE WHEN inverse THEN p.location_id ELSE NULL END,'to_location_id',CASE WHEN inverse THEN NULL ELSE p.location_id END,'description',p.reason);
 WHEN 'inventory_valuation_documents' THEN
  IF inverse THEN RETURN NULL; END IF;
  RETURN common||jsonb_build_object('id',p.valuation_document_id,'period_id',p.period_id,'movement_id',p.movement_id,'policy_id',p.policy_id,
  'valuation_number',p.valuation_number,'valuation_date',p.posting_date::text,'created_by',p.preparer_username)||(p.plan_json->'currency_policy');
 WHEN 'inventory_valuation_input_costs' THEN
  IF inverse THEN RETURN NULL; END IF;
  RETURN jsonb_build_object('tenant_id',p.tenant_id,'id',p.input_cost_id,'valuation_document_id',p.valuation_document_id,'movement_line_id',p.movement_line_id,'total_cost_minor',p.total_value_minor);
 WHEN 'inventory_valuation_lines' THEN
  IF inverse THEN RETURN NULL; END IF;
  RETURN item||jsonb_build_object('tenant_id',p.tenant_id,'id',p.valuation_line_id,'valuation_document_id',p.valuation_document_id,'movement_line_id',p.movement_line_id,
  'line_number',1,'flow_direction','Inbound','value_minor',p.total_value_minor,'inventory_account_id',p.inventory_account_id,'offset_account_id',p.receipt_clearing_account_id);
 WHEN 'inventory_cost_layers' THEN
  IF inverse THEN RETURN NULL; END IF;
  RETURN (item-'quantity_scaled')||jsonb_build_object('tenant_id',p.tenant_id,'id',p.cost_layer_id,'workspace_id',p.workspace_id,'source_valuation_line_id',p.valuation_line_id,
  'legal_entity_id',p.legal_entity_id,'original_quantity_scaled',p.quantity_scaled,'original_value_minor',p.total_value_minor,'currency_code',p.currency_code);
 WHEN 'inventory_valuation_reversals' THEN
  IF NOT inverse THEN RETURN NULL; END IF;
  RETURN common||jsonb_build_object('id',p.valuation_reversal_id,'period_id',p.period_id,'original_valuation_document_id',original.valuation_document_id,
  'reversal_movement_id',p.movement_id,'reversal_number',p.valuation_number,'reversal_date',p.posting_date::text,'currency_code',p.currency_code,'created_by',p.preparer_username);
 WHEN 'inventory_valuation_reversal_effects' THEN
  IF NOT inverse THEN RETURN NULL; END IF;
  RETURN jsonb_build_object('tenant_id',p.tenant_id,'id',p.reversal_effect_id,'reversal_id',p.valuation_reversal_id,'original_valuation_line_id',original.valuation_line_id,
  'original_consumption_id',NULL,'cost_layer_id',original.cost_layer_id,'effect_type','Remove','quantity_scaled',p.quantity_scaled,'value_minor',p.total_value_minor);
 WHEN 'finance_entries' THEN RETURN ((p.plan_json#>'{finance_snapshot,entry}')-ARRAY['organization_id','legal_entity_id'])||jsonb_build_object(
  'tenant_id',p.tenant_id,'organization_code',p.plan_json#>>'{scope,organization_code}','entity_code',p.plan_json#>>'{scope,entity_code}',
  'total_debit_minor',p.total_value_minor,'total_credit_minor',p.total_value_minor,'created_by',p.preparer_username);
 ELSE RETURN NULL;
 END CASE;
END $irp$;
CREATE OR REPLACE FUNCTION reconforge.guard_inventory_receipt_artifact() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $irp$
DECLARE old_data JSONB:='{}'; data JSONB; affected BOOLEAN:=FALSE; k TEXT; v JSONB; expected JSONB;
 p reconforge.inventory_receipt_plans%ROWTYPE; l reconforge.inventory_receipt_links%ROWTYPE; r reconforge.inventory_receipt_reviews%ROWTYPE;
 table_name TEXT:=TG_TABLE_NAME; username TEXT; mutable TEXT[];
BEGIN
 IF TG_OP<>'INSERT' THEN old_data:=to_jsonb(OLD); END IF;
 IF TG_OP='DELETE' THEN data:=old_data; ELSE data:=to_jsonb(NEW); END IF;
 FOREACH k IN ARRAY ARRAY['id','movement_number','valuation_number','reversal_number','entry_number','movement_id','movement_line_id','valuation_document_id',
 'source_valuation_line_id','original_valuation_document_id','reversal_movement_id','reversal_id','original_valuation_line_id','cost_layer_id','entry_id','entry_line_id','reverses_posting_id'] LOOP
  affected:=affected OR COALESCE(reconforge.irp_reserved(data->>k),FALSE) OR COALESCE(reconforge.irp_reserved(old_data->>k),FALSE);
 END LOOP;
 IF NOT affected THEN IF TG_OP='DELETE' THEN RETURN OLD; END IF; RETURN NEW; END IF;
 IF table_name='inventory_valuation_reversal_effects' AND TG_OP='INSERT' THEN
  IF NEW.effect_type='Restore' AND NOT reconforge.irp_reserved(NEW.id) AND NOT reconforge.irp_reserved(NEW.reversal_id)
  AND NOT reconforge.irp_reserved(NEW.original_valuation_line_id)
  AND EXISTS(SELECT 1 FROM reconforge.inventory_layer_consumptions c WHERE c.tenant_id=NEW.tenant_id
   AND c.id=NEW.original_consumption_id AND c.valuation_line_id=NEW.original_valuation_line_id AND c.cost_layer_id=NEW.cost_layer_id) THEN
   RETURN NEW;
  END IF;
 END IF;
 IF TG_OP='DELETE' THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Reserved receipt sources retain immutable history.'; END IF;
 IF current_setting('transaction_isolation')<>'read committed' THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Receipt source writes require READ COMMITTED.'; END IF;
 IF TG_OP='UPDATE' AND (old_data->'tenant_id',old_data->'id') IS DISTINCT FROM (data->'tenant_id',data->'id') THEN
 RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Receipt source identity cannot be relabeled.'; END IF;
 CASE table_name
 WHEN 'inventory_movements' THEN SELECT * INTO p FROM reconforge.inventory_receipt_plans WHERE tenant_id=NEW.tenant_id AND (movement_id=NEW.id OR movement_number=NEW.movement_number);
 WHEN 'inventory_movement_lines' THEN SELECT * INTO p FROM reconforge.inventory_receipt_plans WHERE tenant_id=NEW.tenant_id AND movement_id=NEW.movement_id;
 WHEN 'inventory_valuation_documents' THEN SELECT * INTO p FROM reconforge.inventory_receipt_plans WHERE tenant_id=NEW.tenant_id AND (valuation_document_id=NEW.id OR movement_id=NEW.movement_id);
 WHEN 'inventory_valuation_input_costs' THEN SELECT * INTO p FROM reconforge.inventory_receipt_plans WHERE tenant_id=NEW.tenant_id AND valuation_document_id=NEW.valuation_document_id;
 WHEN 'inventory_valuation_lines' THEN SELECT * INTO p FROM reconforge.inventory_receipt_plans WHERE tenant_id=NEW.tenant_id AND valuation_document_id=NEW.valuation_document_id;
 WHEN 'inventory_cost_layers' THEN SELECT * INTO p FROM reconforge.inventory_receipt_plans WHERE tenant_id=NEW.tenant_id AND operation='Receipt' AND cost_layer_id=NEW.id;
 WHEN 'inventory_valuation_reversals' THEN SELECT * INTO p FROM reconforge.inventory_receipt_plans WHERE tenant_id=NEW.tenant_id AND valuation_reversal_id=NEW.id;
 WHEN 'inventory_valuation_reversal_effects' THEN SELECT * INTO p FROM reconforge.inventory_receipt_plans WHERE tenant_id=NEW.tenant_id AND valuation_reversal_id=NEW.reversal_id;
 WHEN 'finance_entries' THEN SELECT * INTO p FROM reconforge.inventory_receipt_plans WHERE tenant_id=NEW.tenant_id AND finance_entry_id=NEW.id;
 WHEN 'finance_entry_lines' THEN SELECT * INTO p FROM reconforge.inventory_receipt_plans WHERE tenant_id=NEW.tenant_id AND finance_entry_id=NEW.entry_id;
 ELSE RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Receipt sources do not permit additional dimensions.';
 END CASE;
 IF p IS NULL THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='IRP1 namespace requires an exact reviewed source; absence is not a legacy exemption.'; END IF;
 SELECT * INTO l FROM reconforge.inventory_receipt_links WHERE tenant_id=p.tenant_id AND plan_id=p.id;
 SELECT * INTO r FROM reconforge.inventory_receipt_reviews WHERE tenant_id=p.tenant_id AND plan_id=p.id;
 IF l IS NULL OR r IS NULL OR NOT reconforge.irp_scope(p.tenant_id,p.workspace_id,p.organization_id,p.legal_entity_id) THEN
 RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Receipt artifact requires its authorized complete-source reservation.'; END IF;
 SELECT u.username INTO username FROM reconforge.identity_users u WHERE u.tenant_id=p.tenant_id AND u.id=l.posted_actor_id;
 expected:=reconforge.irp_artifact_expected(p,table_name);
 IF table_name='finance_entry_lines' THEN
  IF NEW.line_number NOT IN (1,2) THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Receipt has exactly two reviewed financial lines.'; END IF;
  expected:=(((p.plan_json#>'{finance_snapshot,lines}')->(NEW.line_number-1))-'dimensions')||jsonb_build_object('tenant_id',p.tenant_id,'entry_id',p.finance_entry_id,
   'id',CASE WHEN NEW.line_number=1 THEN p.finance_line_1_id ELSE p.finance_line_2_id END,'currency_code',p.currency_code);
 END IF;
 IF expected IS NULL THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Receipt artifact kind differs from its source operation.'; END IF;
 FOR k,v IN SELECT * FROM jsonb_each(expected) LOOP
  IF data->k IS DISTINCT FROM v THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Receipt artifact differs from exact reviewed content.'; END IF;
 END LOOP;
 IF table_name='inventory_cost_layers' THEN
  IF TG_OP='INSERT' AND (NEW.remaining_quantity_scaled,NEW.remaining_value_minor) IS DISTINCT FROM (p.quantity_scaled,p.total_value_minor) THEN
   RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Receipt layer must start with the full reviewed cost.'; END IF;
  IF TG_OP='UPDATE' AND (old_data-ARRAY['remaining_quantity_scaled','remaining_value_minor','row_version']) IS DISTINCT FROM (data-ARRAY['remaining_quantity_scaled','remaining_value_minor','row_version']) THEN
   RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Receipt FIFO origin is immutable.'; END IF;
  RETURN NEW;
 END IF;
 IF table_name IN ('inventory_movements','inventory_valuation_documents','inventory_valuation_reversals','finance_entries') THEN
  IF TG_OP='INSERT' THEN
   IF data->>'status'<>'Draft' THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Receipt sources start as reviewed-content Draft records.'; END IF;
   IF table_name IN ('inventory_valuation_documents','inventory_valuation_reversals') AND
    (data->'total_value_minor'<>'0'::jsonb OR data->'finance_entry_id'<>'null'::jsonb) THEN
    RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Receipt valuation starts without its generated Finance draft.'; END IF;
  ELSE
   IF OLD.status<>'Draft' OR data->>'status' IS DISTINCT FROM (CASE table_name WHEN 'inventory_movements' THEN 'Posted' WHEN 'finance_entries' THEN 'Validated' ELSE 'Approved' END) THEN
    RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Receipt final source state is immutable.'; END IF;
   IF table_name='inventory_movements' THEN
    mutable:=ARRAY['status','posted_by','posted_at','post_reason','updated_at','row_version'];
    IF NEW.posted_by IS DISTINCT FROM username OR NEW.posted_at IS DISTINCT FROM l.posted_at::timestamptz OR NEW.post_reason IS DISTINCT FROM l.reason THEN
     RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Receipt physical posting must bind its source command.'; END IF;
   ELSIF table_name='finance_entries' THEN
    mutable:=ARRAY['status','validated_by','validated_at','validation_reason','updated_at','validator_actor_id','validation_digest','validation_contract_version'];
    IF (NEW.validator_actor_id,NEW.validated_by,NEW.validated_at,NEW.validation_reason,NEW.validation_digest,NEW.validation_contract_version)
    IS DISTINCT FROM (r.reviewer_actor_id,r.reviewer_username,r.reviewed_at,r.reason,p.finance_validation_digest,'finance-entry-review-v1') THEN
     RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Receipt seal must retain its independent source review.'; END IF;
   ELSE
    mutable:=ARRAY['status','approved_by','approved_at','approval_reason','total_value_minor','finance_entry_id','updated_at','row_version'];
    IF (NEW.total_value_minor,NEW.finance_entry_id,NEW.approved_by,NEW.approval_reason) IS DISTINCT FROM (p.total_value_minor,p.finance_entry_id,username,l.reason)
    OR NEW.approved_at IS DISTINCT FROM l.posted_at::timestamptz THEN
     RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Receipt valuation approval must bind the reviewed total and Finance draft.'; END IF;
   END IF;
   IF old_data-mutable IS DISTINCT FROM data-mutable THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Receipt lifecycle cannot replace reviewed source content.'; END IF;
  END IF;
 ELSIF TG_OP<>'INSERT' THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Receipt source lines are immutable.';
 END IF;
 RETURN NEW;
END $irp$;
"""


_EFFECT_SQL = r"""
CREATE OR REPLACE FUNCTION reconforge.irp_assert_complete(t TEXT,plan TEXT,require_effect BOOLEAN DEFAULT TRUE) RETURNS VOID
LANGUAGE plpgsql SET search_path=pg_catalog AS $irp$
DECLARE p reconforge.inventory_receipt_plans%ROWTYPE; l reconforge.inventory_receipt_links%ROWTYPE; r reconforge.inventory_receipt_reviews%ROWTYPE;
 table_name TEXT; identifier TEXT; actual JSONB; expected JSONB; k TEXT; v JSONB; effect RECORD;
BEGIN
 SELECT * INTO p FROM reconforge.inventory_receipt_plans WHERE tenant_id=t AND id=plan;
 SELECT * INTO l FROM reconforge.inventory_receipt_links WHERE tenant_id=t AND plan_id=plan;
 SELECT * INTO r FROM reconforge.inventory_receipt_reviews WHERE tenant_id=t AND plan_id=plan;
 IF p IS NULL OR l IS NULL OR r IS NULL OR NOT reconforge.irp_scope(t,p.workspace_id,p.organization_id,p.legal_entity_id) THEN
 RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Receipt effect needs an authorized reviewed complete-source link.'; END IF;
 FOR table_name,identifier IN SELECT * FROM (VALUES ('inventory_movements',p.movement_id),('inventory_movement_lines',p.movement_line_id),
 ('inventory_valuation_documents',p.valuation_document_id),('inventory_valuation_input_costs',p.input_cost_id),('inventory_valuation_lines',p.valuation_line_id),
 ('inventory_cost_layers',CASE WHEN p.operation='Receipt' THEN p.cost_layer_id ELSE NULL END),
 ('inventory_valuation_reversals',p.valuation_reversal_id),('inventory_valuation_reversal_effects',p.reversal_effect_id),('finance_entries',p.finance_entry_id)) a(n,i) LOOP
  IF identifier IS NULL THEN CONTINUE; END IF;
  EXECUTE format('SELECT to_jsonb(x) FROM reconforge.%I x WHERE tenant_id=$1 AND id=$2',table_name) INTO actual USING t,identifier;
  expected:=reconforge.irp_artifact_expected(p,table_name);
  IF actual IS NULL OR expected IS NULL THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Receipt effect is missing an exact source artifact.'; END IF;
  FOR k,v IN SELECT * FROM jsonb_each(expected) LOOP
   IF actual->k IS DISTINCT FROM v THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Receipt effect source content differs from its reviewed plan.'; END IF;
  END LOOP;
  IF table_name='inventory_movements' AND actual->>'status'<>'Posted' THEN
   RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Receipt effect requires Posted physical movement.';
  ELSIF table_name IN ('inventory_valuation_documents','inventory_valuation_reversals') AND
   (actual->>'status'<>'Approved' OR actual->'total_value_minor' IS DISTINCT FROM to_jsonb(p.total_value_minor) OR actual->>'finance_entry_id' IS DISTINCT FROM p.finance_entry_id) THEN
   RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Receipt effect requires its Approved valuation and generated Finance entry.';
  ELSIF table_name='finance_entries' AND (actual->>'status'<>'Validated' OR actual->>'validator_actor_id' IS DISTINCT FROM r.reviewer_actor_id
   OR actual->>'validation_digest' IS DISTINCT FROM p.finance_validation_digest OR actual->>'validated_at' IS DISTINCT FROM r.reviewed_at
   OR actual->>'validated_by' IS DISTINCT FROM r.reviewer_username OR actual->>'validation_reason' IS DISTINCT FROM r.reason) THEN
   RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Receipt effect requires its retained independent Finance review.';
  END IF;
 END LOOP;
 IF (SELECT count(*) FROM reconforge.inventory_movement_lines WHERE tenant_id=t AND movement_id=p.movement_id)<>1
 OR (SELECT count(*) FROM reconforge.finance_entry_lines WHERE tenant_id=t AND entry_id=p.finance_entry_id)<>2
 OR NOT EXISTS(SELECT 1 FROM reconforge.finance_entry_lines WHERE tenant_id=t AND id=p.finance_line_1_id AND entry_id=p.finance_entry_id AND line_number=1)
 OR NOT EXISTS(SELECT 1 FROM reconforge.finance_entry_lines WHERE tenant_id=t AND id=p.finance_line_2_id AND entry_id=p.finance_entry_id AND line_number=2)
 OR EXISTS(SELECT 1 FROM reconforge.finance_entry_line_dimensions d JOIN reconforge.finance_entry_lines f ON f.tenant_id=d.tenant_id AND f.id=d.entry_line_id WHERE f.tenant_id=t AND f.entry_id=p.finance_entry_id)
 OR (p.operation='Receipt' AND ((SELECT count(*) FROM reconforge.inventory_valuation_lines WHERE tenant_id=t AND valuation_document_id=p.valuation_document_id)<>1
  OR (SELECT count(*) FROM reconforge.inventory_valuation_input_costs WHERE tenant_id=t AND valuation_document_id=p.valuation_document_id)<>1))
 OR (p.operation='FullReceiptReversal' AND ((SELECT count(*) FROM reconforge.inventory_valuation_reversal_effects WHERE tenant_id=t AND reversal_id=p.valuation_reversal_id)<>1
  OR NOT EXISTS(SELECT 1 FROM reconforge.inventory_cost_layers WHERE tenant_id=t AND id=p.cost_layer_id AND remaining_quantity_scaled=0 AND remaining_value_minor=0))) THEN
  RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Receipt complete-source closure has missing or extra financial/physical effects.';
 END IF;
 IF NOT reconforge.irp_event(t,p.id,p.workspace_id,p.organization_id,p.legal_entity_id,l.audit_event_id,l.outbox_event_id,l.posted_actor_id,
 'inventory_receipt_committed',jsonb_build_object('plan_digest',p.plan_digest,'finance_validation_digest',p.finance_validation_digest,'review_digest',r.review_digest,'effect_id',p.posting_effect_id)) THEN
  RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Receipt complete-source effect needs its exact audit and outbox evidence.';
 END IF;
 IF require_effect THEN
  SELECT * INTO effect FROM reconforge.finance_posting_effects WHERE tenant_id=t AND id=p.posting_effect_id;
  IF effect IS NULL OR effect.entry_id IS DISTINCT FROM p.finance_entry_id OR effect.source_id IS DISTINCT FROM p.id
  OR effect.source_kind IS DISTINCT FROM (CASE p.operation WHEN 'Receipt' THEN 'InventoryReceipt' ELSE 'InventoryReceiptReversal' END)
  OR effect.snapshot_json IS DISTINCT FROM p.plan_json->'finance_snapshot' OR effect.validation_digest IS DISTINCT FROM p.finance_validation_digest
  OR (effect.posted_actor_id,effect.posted_at,effect.reason) IS DISTINCT FROM (l.posted_actor_id,l.posted_at,l.reason) THEN
   RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Receipt complete-source transaction must contain its exact immutable posting effect.';
  END IF;
 END IF;
END $irp$;
CREATE OR REPLACE FUNCTION reconforge.guard_inventory_receipt_complete() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $irp$
BEGIN PERFORM reconforge.irp_assert_complete(NEW.tenant_id,NEW.plan_id); RETURN NEW; END $irp$;
CREATE OR REPLACE FUNCTION reconforge.guard_inventory_receipt_finance_effect() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $irp$
DECLARE p reconforge.inventory_receipt_plans%ROWTYPE; l reconforge.inventory_receipt_links%ROWTYPE;
BEGIN
 IF NEW.source_kind NOT IN ('InventoryReceipt','InventoryReceiptReversal') THEN
  IF COALESCE(reconforge.irp_reserved(NEW.id),FALSE) OR COALESCE(reconforge.irp_reserved(NEW.entry_id),FALSE)
  OR COALESCE(reconforge.irp_reserved(NEW.source_id),FALSE) OR COALESCE(reconforge.irp_reserved(NEW.reverses_effect_id),FALSE)
  OR EXISTS(SELECT 1 FROM reconforge.finance_posting_effects WHERE tenant_id=NEW.tenant_id AND id=NEW.reverses_effect_id AND source_kind IN ('InventoryReceipt','InventoryReceiptReversal')) THEN
   RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Receipt-owned Finance effects require their complete source operation.';
  END IF;
  RETURN NEW;
 END IF;
 SELECT * INTO p FROM reconforge.inventory_receipt_plans WHERE tenant_id=NEW.tenant_id AND id=NEW.source_id;
 SELECT * INTO l FROM reconforge.inventory_receipt_links WHERE tenant_id=NEW.tenant_id AND plan_id=NEW.source_id;
 IF p IS NULL OR l IS NULL OR NEW.source_kind IS DISTINCT FROM (CASE p.operation WHEN 'Receipt' THEN 'InventoryReceipt' ELSE 'InventoryReceiptReversal' END)
 OR (NEW.id,NEW.entry_id,NEW.workspace_id,NEW.organization_id,NEW.legal_entity_id,NEW.reverses_effect_id,NEW.validation_digest,
  NEW.currency_code,NEW.currency_precision,NEW.currency_rounding_policy,NEW.currency_registry_version,NEW.currency_registry_digest,NEW.posted_actor_id,NEW.posted_at,NEW.reason)
 IS DISTINCT FROM (p.posting_effect_id,p.finance_entry_id,p.workspace_id,p.organization_id,p.legal_entity_id,p.original_posting_effect_id,p.finance_validation_digest,
  p.currency_code,p.currency_precision,p.currency_rounding_policy,p.currency_registry_version,p.currency_registry_digest,l.posted_actor_id,l.posted_at,l.reason)
 OR NEW.snapshot_json IS DISTINCT FROM p.plan_json->'finance_snapshot' THEN
  RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Receipt Finance effect must bind its exact reviewed complete-source reservation.';
 END IF;
 PERFORM reconforge.irp_assert_complete(NEW.tenant_id,p.id,FALSE);
 RETURN NEW;
END $irp$;
CREATE OR REPLACE FUNCTION reconforge.guard_inventory_receipt_command() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $irp$
DECLARE p reconforge.inventory_receipt_plans%ROWTYPE; r reconforge.inventory_receipt_reviews%ROWTYPE; l reconforge.inventory_receipt_links%ROWTYPE;
 effect RECORD; result JSONB; finance JSONB;
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Receipt command acknowledgements are immutable.'; END IF;
 PERFORM reconforge.irp_bounded(NEW.result_json);
 SELECT * INTO p FROM reconforge.inventory_receipt_plans WHERE tenant_id=NEW.tenant_id AND id=NEW.plan_id;
 IF p IS NULL OR NOT reconforge.irp_scope(NEW.tenant_id,NEW.workspace_id,NEW.organization_id,NEW.legal_entity_id)
 OR (NEW.workspace_id,NEW.organization_id,NEW.legal_entity_id) IS DISTINCT FROM (p.workspace_id,p.organization_id,p.legal_entity_id) THEN
  RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Receipt command requires its authoritative scoped source.';
 END IF;
 IF NEW.operation IN ('prepare_receipt','prepare_reversal') THEN
  IF NEW.operation IS DISTINCT FROM (CASE p.operation WHEN 'Receipt' THEN 'prepare_receipt' ELSE 'prepare_reversal' END) THEN
   RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Receipt command operation differs from its source.'; END IF;
  IF NEW.actor_user_id IS DISTINCT FROM p.preparer_actor_id THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Receipt command actor must bind its retained preparation.'; END IF;
  result:=p.plan_json;
 ELSIF NEW.operation='review' THEN
  SELECT * INTO r FROM reconforge.inventory_receipt_reviews WHERE tenant_id=NEW.tenant_id AND plan_id=p.id;
  IF NEW.actor_user_id IS DISTINCT FROM r.reviewer_actor_id THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Receipt command actor must bind its retained review.'; END IF;
  result:=r.review_json;
 ELSE
  SELECT * INTO r FROM reconforge.inventory_receipt_reviews WHERE tenant_id=NEW.tenant_id AND plan_id=p.id;
  SELECT * INTO l FROM reconforge.inventory_receipt_links WHERE tenant_id=NEW.tenant_id AND plan_id=p.id;
  SELECT * INTO effect FROM reconforge.finance_posting_effects WHERE tenant_id=NEW.tenant_id AND id=p.posting_effect_id;
  IF effect IS NULL OR r IS NULL OR l IS NULL THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Receipt acknowledgement requires its committed backing effect.'; END IF;
  IF NEW.actor_user_id IS DISTINCT FROM l.posted_actor_id THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Receipt command actor must bind its retained posting.'; END IF;
  PERFORM reconforge.irp_assert_complete(NEW.tenant_id,p.id);
  finance:=(to_jsonb(effect)-ARRAY['tenant_id','snapshot_json'])||jsonb_build_object('snapshot',effect.snapshot_json);
  result:=jsonb_build_object('contract_version','inventory-receipt-effect-v1','plan_id',p.id,'operation',p.operation,'plan_digest',p.plan_digest,
   'review_id',r.id,'review_digest',r.review_digest,'source_kind',effect.source_kind,'purpose','operational_posting','source_id',p.id,
   'movement_id',p.movement_id,'valuation_document_id',p.valuation_document_id,'valuation_reversal_id',p.valuation_reversal_id,'cost_layer_id',p.cost_layer_id,
   'entry_id',p.finance_entry_id,'effect_id',p.posting_effect_id,'reverses_effect_id',p.original_posting_effect_id,
   'posted_actor_id',effect.posted_actor_id,'posted_at',effect.posted_at,'audit_event_id',l.audit_event_id,'outbox_event_id',l.outbox_event_id,'finance_effect',finance);
  result:=result||jsonb_build_object('effect_digest',reconforge.irp_digest(result));
 END IF;
 IF result IS NULL OR NEW.result_json IS DISTINCT FROM result THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Receipt acknowledgement must retain its complete authoritative source result.'; END IF;
 IF NEW.operation IN ('review','commit') AND NEW.actor_user_id=p.preparer_actor_id THEN
  RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Receipt preparer cannot borrow independent command acknowledgement.';
 END IF;
 RETURN NEW;
END $irp$;
"""



_RESOURCE_SQL = r"""
CREATE OR REPLACE FUNCTION reconforge.guard_inventory_receipt_dimensions() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $irp$
DECLARE t TEXT; workspaces TEXT[]; workspace TEXT;
BEGIN
 IF TG_OP='INSERT' THEN t:=NEW.tenant_id; workspaces:=ARRAY[NEW.workspace_id];
 ELSIF TG_OP='DELETE' THEN t:=OLD.tenant_id; workspaces:=ARRAY[OLD.workspace_id];
 ELSE
  IF NEW.tenant_id IS DISTINCT FROM OLD.tenant_id THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Dimension tenant identity is immutable.'; END IF;
  t:=NEW.tenant_id; workspaces:=ARRAY[OLD.workspace_id,NEW.workspace_id];
 END IF;
 FOR workspace IN SELECT DISTINCT value COLLATE "C" FROM unnest(workspaces) value ORDER BY 1 LOOP
  PERFORM pg_advisory_xact_lock(hashtextextended(jsonb_build_array(t,'finance_dimensions',workspace)::text,0));
 END LOOP;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF;
 RETURN NEW;
END $irp$;
CREATE OR REPLACE FUNCTION reconforge.guard_inventory_receipt_reference() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $irp$
BEGIN
 PERFORM pg_advisory_xact_lock(hashtextextended(jsonb_build_array(OLD.tenant_id,TG_TABLE_NAME,OLD.id)::text,0));
 IF TG_OP='DELETE' THEN RETURN OLD; END IF;
 RETURN NEW;
END $irp$;
CREATE OR REPLACE FUNCTION reconforge.guard_inventory_receipt_stock_line() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $irp$
DECLARE p RECORD; t TEXT; identifiers TEXT[];
BEGIN
 IF TG_OP='INSERT' THEN t:=NEW.tenant_id; identifiers:=ARRAY[NEW.movement_id];
 ELSIF TG_OP='DELETE' THEN t:=OLD.tenant_id; identifiers:=ARRAY[OLD.movement_id];
 ELSE
  IF NEW.tenant_id IS DISTINCT FROM OLD.tenant_id THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Stock line cannot change tenant.'; END IF;
  t:=NEW.tenant_id; identifiers:=ARRAY[OLD.movement_id,NEW.movement_id];
 END IF;
 FOR p IN SELECT id,status FROM reconforge.inventory_movements WHERE tenant_id=t AND id=ANY(identifiers) ORDER BY id COLLATE "C" FOR UPDATE LOOP
  IF p.status<>'Draft' THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Stock lines require a locked Draft parent.'; END IF;
 END LOOP;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF;
 RETURN NEW;
END $irp$;
CREATE OR REPLACE FUNCTION reconforge.guard_inventory_receipt_stock_transition() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $irp$
DECLARE resource RECORD; fifo RECORD; balance NUMERIC; delta NUMERIC; sign INTEGER;
BEGIN
 IF NEW.status=OLD.status THEN RETURN NEW; END IF;
 IF current_setting('transaction_isolation')<>'read committed' THEN
  RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Physical posting and voiding require READ COMMITTED.';
 END IF;
 -- Acquire locks even before any receipt association exists: after a wait, each
 -- subsequent command obtains a fresh READ COMMITTED snapshot of committed links.
 FOR resource IN SELECT DISTINCT l.item_id COLLATE "C" item_id,locations.location_id COLLATE "C" location_id,COALESCE(l.inventory_lot_id,'') COLLATE "C" lot
  FROM reconforge.inventory_movement_lines l CROSS JOIN LATERAL (VALUES(l.from_location_id),(l.to_location_id)) locations(location_id)
  WHERE l.tenant_id=NEW.tenant_id AND l.movement_id=NEW.id AND locations.location_id IS NOT NULL
  ORDER BY 1,2,3 LOOP
  PERFORM pg_advisory_xact_lock(hashtextextended(NEW.workspace_id||'|'||NEW.legal_entity_id||'|'||resource.location_id||'|'||resource.item_id||'|'||resource.lot,0));
 END LOOP;
 FOR fifo IN SELECT DISTINCT item_id COLLATE "C" item_id,COALESCE(inventory_lot_id,'') COLLATE "C" lot FROM reconforge.inventory_movement_lines
  WHERE tenant_id=NEW.tenant_id AND movement_id=NEW.id ORDER BY 1,2 LOOP
  PERFORM pg_advisory_xact_lock(hashtextextended(NEW.legal_entity_id||'|'||fifo.item_id||'|'||fifo.lot,0));
 END LOOP;
 sign:=CASE WHEN OLD.status='Draft' AND NEW.status='Posted' THEN 1 WHEN OLD.status='Posted' AND NEW.status='Voided' THEN -1 ELSE 0 END;
 FOR resource IN SELECT DISTINCT p.item_id,p.location_id FROM reconforge.inventory_receipt_plans p
  JOIN reconforge.inventory_receipt_links link ON link.tenant_id=p.tenant_id AND link.plan_id=p.id
  JOIN reconforge.inventory_movement_lines changed ON changed.tenant_id=p.tenant_id AND changed.movement_id=NEW.id AND changed.item_id=p.item_id
  AND p.location_id IN (changed.from_location_id,changed.to_location_id)
  WHERE p.tenant_id=NEW.tenant_id AND p.workspace_id=NEW.workspace_id AND p.organization_id=NEW.organization_id
  AND p.legal_entity_id=NEW.legal_entity_id AND p.operation='Receipt' LOOP
  SELECT COALESCE(sum((CASE WHEN l.to_location_id=resource.location_id THEN 1 ELSE 0 END-CASE WHEN l.from_location_id=resource.location_id THEN 1 ELSE 0 END)
   *l.quantity_scaled::numeric*power(10::numeric,6-l.quantity_precision)),0) INTO balance
   FROM reconforge.inventory_movements m JOIN reconforge.inventory_movement_lines l ON l.tenant_id=m.tenant_id AND l.movement_id=m.id
   WHERE m.tenant_id=NEW.tenant_id AND m.workspace_id=NEW.workspace_id AND m.organization_id=NEW.organization_id AND m.legal_entity_id=NEW.legal_entity_id
   AND m.status='Posted' AND l.item_id=resource.item_id AND l.inventory_lot_id IS NULL;
  SELECT COALESCE(sum((CASE WHEN l.to_location_id=resource.location_id THEN 1 ELSE 0 END-CASE WHEN l.from_location_id=resource.location_id THEN 1 ELSE 0 END)
   *l.quantity_scaled::numeric*power(10::numeric,6-l.quantity_precision)),0) INTO delta FROM reconforge.inventory_movement_lines l
   WHERE l.tenant_id=NEW.tenant_id AND l.movement_id=NEW.id AND l.item_id=resource.item_id AND l.inventory_lot_id IS NULL;
  IF balance+sign*delta<0 THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Receipt-associated physical stock cannot become negative.'; END IF;
 END LOOP;
 RETURN NEW;
END $irp$;
"""


_HISTORY_SQL = r"""
CREATE OR REPLACE FUNCTION reconforge.guard_inventory_receipt_layer_history() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $irp$
DECLARE source reconforge.inventory_receipt_plans%ROWTYPE; layer reconforge.inventory_cost_layers%ROWTYPE;
BEGIN
 IF NOT reconforge.irp_reserved(NEW.cost_layer_id) THEN RETURN NEW; END IF;
 IF current_setting('transaction_isolation')<>'read committed' THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Receipt layer history requires READ COMMITTED.'; END IF;
 SELECT * INTO source FROM reconforge.inventory_receipt_plans WHERE tenant_id=NEW.tenant_id AND cost_layer_id=NEW.cost_layer_id AND operation='Receipt';
 IF source IS NULL OR NOT reconforge.irp_scope(source.tenant_id,source.workspace_id,source.organization_id,source.legal_entity_id)
 OR NOT EXISTS(SELECT 1 FROM reconforge.inventory_receipt_links WHERE tenant_id=source.tenant_id AND plan_id=source.id) THEN
  RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Reserved layer history requires its visible complete source.';
 END IF;
 -- Same FIFO and layer lock literals as both public valuation and full inverse.
 PERFORM pg_advisory_xact_lock(hashtextextended(source.legal_entity_id||'|'||source.item_id||'|',0));
 PERFORM pg_advisory_xact_lock(hashtextextended(source.cost_layer_id,0));
 SELECT * INTO layer FROM reconforge.inventory_cost_layers WHERE tenant_id=source.tenant_id AND id=source.cost_layer_id FOR UPDATE;
 IF layer IS NULL THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Reserved layer history requires an existing source layer.'; END IF;
 IF TG_TABLE_NAME='inventory_layer_consumptions' THEN
  IF NEW.workspace_id IS DISTINCT FROM source.workspace_id OR NOT EXISTS(
   SELECT 1 FROM reconforge.inventory_valuation_lines detail JOIN reconforge.inventory_valuation_documents document
    ON document.tenant_id=detail.tenant_id AND document.id=detail.valuation_document_id
   WHERE detail.tenant_id=NEW.tenant_id AND detail.id=NEW.valuation_line_id AND detail.flow_direction='Outbound' AND document.status='Draft'
    AND (document.workspace_id,document.organization_id,document.legal_entity_id,document.currency_code,document.currency_precision,document.currency_rounding_policy)
     IS NOT DISTINCT FROM (source.workspace_id,source.organization_id,source.legal_entity_id,source.currency_code,source.currency_precision,source.currency_rounding_policy)
    AND (detail.item_id,detail.uom_id,detail.quantity_precision) IS NOT DISTINCT FROM (source.item_id,source.uom_id,source.quantity_precision)
    AND detail.inventory_lot_id IS NULL) THEN
   RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Reserved layer consumption must bind its exact scoped item and monetary units.';
  END IF;
  IF NEW.quantity_scaled>layer.remaining_quantity_scaled OR NEW.value_minor>layer.remaining_value_minor THEN
   RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Reserved layer consumption exceeds remaining source capacity.';
  END IF;
 ELSE
  IF NOT EXISTS(SELECT 1 FROM reconforge.inventory_valuation_reversals reverse_document WHERE reverse_document.tenant_id=NEW.tenant_id
   AND reverse_document.id=NEW.reversal_id AND reverse_document.status='Draft'
   AND (reverse_document.workspace_id,reverse_document.organization_id,reverse_document.legal_entity_id,reverse_document.currency_code)
    IS NOT DISTINCT FROM (source.workspace_id,source.organization_id,source.legal_entity_id,source.currency_code)) THEN
   RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Reserved layer correction must bind its scoped Draft parent.';
  END IF;
  IF (NEW.effect_type='Remove' AND (NEW.quantity_scaled>layer.remaining_quantity_scaled OR NEW.value_minor>layer.remaining_value_minor))
  OR (NEW.effect_type='Restore' AND (NEW.quantity_scaled::numeric+layer.remaining_quantity_scaled>layer.original_quantity_scaled
   OR NEW.value_minor::numeric+layer.remaining_value_minor>layer.original_value_minor)) THEN
   RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Reserved layer correction exceeds original source capacity.';
  END IF;
 END IF;
 RETURN NEW;
END $irp$;
CREATE OR REPLACE FUNCTION reconforge.guard_inventory_receipt_layer_history_complete() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $irp$
DECLARE source reconforge.inventory_receipt_plans%ROWTYPE; layer reconforge.inventory_cost_layers%ROWTYPE; expected_quantity NUMERIC; expected_value NUMERIC;
BEGIN
 IF NOT reconforge.irp_reserved(NEW.cost_layer_id) THEN RETURN NEW; END IF;
 SELECT * INTO source FROM reconforge.inventory_receipt_plans WHERE tenant_id=NEW.tenant_id AND cost_layer_id=NEW.cost_layer_id AND operation='Receipt';
 IF source IS NULL OR NOT reconforge.irp_scope(source.tenant_id,source.workspace_id,source.organization_id,source.legal_entity_id) THEN
  RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Reserved layer closure requires its authorized source.';
 END IF;
 SELECT * INTO layer FROM reconforge.inventory_cost_layers WHERE tenant_id=NEW.tenant_id AND id=NEW.cost_layer_id;
 IF TG_TABLE_NAME='inventory_layer_consumptions' THEN
  IF NOT EXISTS(SELECT 1 FROM reconforge.inventory_valuation_lines detail JOIN reconforge.inventory_valuation_documents document
   ON document.tenant_id=detail.tenant_id AND document.id=detail.valuation_document_id
   WHERE detail.tenant_id=NEW.tenant_id AND detail.id=NEW.valuation_line_id AND document.status='Approved') THEN
   RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Reserved layer consumption requires its final Approved valuation.';
  END IF;
 ELSE
  IF NOT EXISTS(SELECT 1 FROM reconforge.inventory_valuation_reversals reverse_document WHERE reverse_document.tenant_id=NEW.tenant_id
   AND reverse_document.id=NEW.reversal_id AND reverse_document.status='Approved') THEN
   RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Reserved layer correction requires its final Approved reversal.';
  END IF;
 END IF;
 SELECT layer.original_quantity_scaled-COALESCE(sum(quantity_scaled),0),layer.original_value_minor-COALESCE(sum(value_minor),0)
  INTO expected_quantity,expected_value FROM reconforge.inventory_layer_consumptions WHERE tenant_id=NEW.tenant_id AND cost_layer_id=NEW.cost_layer_id;
 SELECT expected_quantity+COALESCE(sum(CASE effect_type WHEN 'Restore' THEN quantity_scaled ELSE -quantity_scaled END),0),
  expected_value+COALESCE(sum(CASE effect_type WHEN 'Restore' THEN value_minor ELSE -value_minor END),0)
  INTO expected_quantity,expected_value FROM reconforge.inventory_valuation_reversal_effects WHERE tenant_id=NEW.tenant_id AND cost_layer_id=NEW.cost_layer_id;
 IF layer IS NULL OR (layer.remaining_quantity_scaled::numeric,layer.remaining_value_minor::numeric) IS DISTINCT FROM (expected_quantity,expected_value) THEN
  RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Reserved layer final balance must equal complete immutable history.';
 END IF;
 RETURN NEW;
END $irp$;
"""

_INSTALL_SQL = r"""
LOCK TABLE reconforge.inventory_movements,reconforge.inventory_movement_lines,reconforge.inventory_valuation_documents,
 reconforge.inventory_valuation_input_costs,reconforge.inventory_valuation_lines,reconforge.inventory_cost_layers,
 reconforge.inventory_valuation_reversals,reconforge.inventory_valuation_reversal_effects,reconforge.finance_entries,
 reconforge.finance_entry_lines,reconforge.finance_entry_line_dimensions,reconforge.finance_posting_effects IN ACCESS EXCLUSIVE MODE;
DO $irp$
DECLARE definition TEXT; expected TEXT; selected TEXT; item RECORD; bad BOOLEAN;
BEGIN
 CREATE TEMP TABLE irp_expected_posting_checks (LIKE reconforge.finance_posting_effects) ON COMMIT DROP;
 ALTER TABLE irp_expected_posting_checks ADD CONSTRAINT irp_old_kind CHECK(source_kind IN ('Manual','Reversal'));
 ALTER TABLE irp_expected_posting_checks ADD CONSTRAINT irp_old_inverse CHECK((source_kind='Manual' AND reverses_effect_id IS NULL) OR (source_kind='Reversal' AND reverses_effect_id IS NOT NULL));
 ALTER TABLE irp_expected_posting_checks ADD CONSTRAINT irp_new_kind CHECK(source_kind IN ('Manual','Reversal','InventoryReceipt','InventoryReceiptReversal'));
 ALTER TABLE irp_expected_posting_checks ADD CONSTRAINT irp_new_inverse CHECK((source_kind IN ('Manual','InventoryReceipt') AND reverses_effect_id IS NULL) OR (source_kind IN ('Reversal','InventoryReceiptReversal') AND reverses_effect_id IS NOT NULL));
 FOR item IN SELECT * FROM (VALUES ('finance_posting_effects_source_kind_check','irp_old_kind','irp_new_kind'),
 ('finance_posting_effects_check','irp_old_inverse','irp_new_inverse')) c(name,old_name,new_name) LOOP
  selected:=CASE WHEN EXISTS(SELECT 1 FROM pg_constraint WHERE conrelid='reconforge.finance_posting_effects'::regclass AND conname=item.new_name)
   THEN item.new_name ELSE item.name END;
  SELECT pg_get_constraintdef(oid) INTO definition FROM pg_constraint WHERE conrelid='reconforge.finance_posting_effects'::regclass AND conname=selected AND contype='c';
  SELECT pg_get_constraintdef(oid) INTO expected FROM pg_constraint WHERE conrelid='pg_temp.irp_expected_posting_checks'::regclass
   AND conname=CASE WHEN selected=item.name THEN item.old_name ELSE item.new_name END;
  IF definition IS NULL OR definition IS DISTINCT FROM expected THEN
   RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Receipt extension refuses unknown Finance posting constraint definitions.'; END IF;
  IF selected=item.name THEN EXECUTE format('ALTER TABLE reconforge.finance_posting_effects DROP CONSTRAINT %I',selected); END IF;
 END LOOP;
 IF NOT EXISTS(SELECT 1 FROM pg_constraint WHERE conrelid='reconforge.finance_posting_effects'::regclass AND conname='irp_new_kind') THEN
  ALTER TABLE reconforge.finance_posting_effects ADD CONSTRAINT irp_new_kind CHECK(source_kind IN ('Manual','Reversal','InventoryReceipt','InventoryReceiptReversal'));
  ALTER TABLE reconforge.finance_posting_effects ADD CONSTRAINT irp_new_inverse CHECK((source_kind IN ('Manual','InventoryReceipt') AND reverses_effect_id IS NULL) OR (source_kind IN ('Reversal','InventoryReceiptReversal') AND reverses_effect_id IS NOT NULL));
 END IF;
 DROP TABLE pg_temp.irp_expected_posting_checks;
 FOR item IN SELECT * FROM (VALUES
 ('inventory_movements','id','movement_id'),('inventory_movements','movement_number','movement_number'),
 ('inventory_movement_lines','id','movement_line_id'),('inventory_valuation_documents','id','valuation_document_id'),
 ('inventory_valuation_documents','valuation_number','valuation_number'),('inventory_valuation_input_costs','id','input_cost_id'),
 ('inventory_valuation_lines','id','valuation_line_id'),('inventory_cost_layers','id','cost_layer_id'),
 ('inventory_valuation_reversals','id','valuation_reversal_id'),('inventory_valuation_reversals','reversal_number','valuation_number'),
 ('inventory_valuation_reversal_effects','id','reversal_effect_id'),('finance_entries','id','finance_entry_id'),
 ('finance_entries','entry_number','finance_entry_number'),('finance_entry_lines','id','finance_line_1_id'),
 ('finance_posting_effects','id','posting_effect_id')) x(table_name,column_name,plan_column) LOOP
  EXECUTE format('SELECT EXISTS(SELECT 1 FROM reconforge.%I a WHERE reconforge.irp_reserved(a.%I) AND NOT EXISTS('
   'SELECT 1 FROM reconforge.inventory_receipt_plans p WHERE p.tenant_id=a.tenant_id AND (p.%I=a.%I %s)))',
   item.table_name,item.column_name,item.plan_column,item.column_name,
   CASE WHEN item.table_name='finance_entry_lines' THEN 'OR p.finance_line_2_id=a.id' ELSE '' END) INTO bad;
  IF bad THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='IRP1 namespace is occupied by unrelated historical data; upgrade refuses adoption.'; END IF;
 END LOOP;
END $irp$;
DO $irp$ DECLARE table_name TEXT; BEGIN
 FOREACH table_name IN ARRAY ARRAY['inventory_receipt_plans','inventory_receipt_reviews','inventory_receipt_links','inventory_receipt_commands'] LOOP
  EXECUTE format('ALTER TABLE reconforge.%I ENABLE ROW LEVEL SECURITY',table_name);
  EXECUTE format('ALTER TABLE reconforge.%I FORCE ROW LEVEL SECURITY',table_name);
  EXECUTE format('DROP POLICY IF EXISTS inventory_receipt_scope ON reconforge.%I',table_name);
  EXECUTE format('CREATE POLICY inventory_receipt_scope ON reconforge.%I USING (reconforge.irp_scope(tenant_id,workspace_id,organization_id,legal_entity_id)) WITH CHECK (reconforge.irp_scope(tenant_id,workspace_id,organization_id,legal_entity_id))',table_name);
 END LOOP;
 FOREACH table_name IN ARRAY ARRAY['finance_charts','finance_journals','finance_accounts'] LOOP
  EXECUTE format('DROP TRIGGER IF EXISTS inventory_receipt_reference_lock ON reconforge.%I',table_name);
  EXECUTE format('CREATE TRIGGER inventory_receipt_reference_lock BEFORE UPDATE OR DELETE ON reconforge.%I FOR EACH ROW EXECUTE FUNCTION reconforge.guard_inventory_receipt_reference()',table_name);
 END LOOP;
 FOREACH table_name IN ARRAY ARRAY['inventory_movements','inventory_movement_lines','inventory_valuation_documents','inventory_valuation_input_costs',
 'inventory_valuation_lines','inventory_cost_layers','inventory_valuation_reversals','inventory_valuation_reversal_effects','finance_entries','finance_entry_lines','finance_entry_line_dimensions'] LOOP
  EXECUTE format('DROP TRIGGER IF EXISTS aaa_inventory_receipt_namespace ON reconforge.%I',table_name);
  EXECUTE format('CREATE TRIGGER aaa_inventory_receipt_namespace BEFORE INSERT OR UPDATE OR DELETE ON reconforge.%I FOR EACH ROW EXECUTE FUNCTION reconforge.guard_inventory_receipt_artifact()',table_name);
 END LOOP;
END $irp$;
DO $irp$ DECLARE target TEXT; BEGIN
 FOREACH target IN ARRAY ARRAY['inventory_layer_consumptions','inventory_valuation_reversal_effects'] LOOP
  EXECUTE format('DROP TRIGGER IF EXISTS aaa_inventory_receipt_layer_history ON reconforge.%I',target);
  EXECUTE format('CREATE TRIGGER aaa_inventory_receipt_layer_history BEFORE INSERT ON reconforge.%I FOR EACH ROW EXECUTE FUNCTION reconforge.guard_inventory_receipt_layer_history()',target);
  EXECUTE format('DROP TRIGGER IF EXISTS inventory_receipt_layer_history_complete ON reconforge.%I',target);
  EXECUTE format('CREATE CONSTRAINT TRIGGER inventory_receipt_layer_history_complete AFTER INSERT ON reconforge.%I DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION reconforge.guard_inventory_receipt_layer_history_complete()',target);
 END LOOP;
END $irp$;
DROP TRIGGER IF EXISTS inventory_receipt_dimension_lock ON reconforge.finance_dimensions;
CREATE TRIGGER inventory_receipt_dimension_lock BEFORE INSERT OR UPDATE OR DELETE ON reconforge.finance_dimensions FOR EACH ROW EXECUTE FUNCTION reconforge.guard_inventory_receipt_dimensions();
DROP TRIGGER IF EXISTS inventory_receipt_stock_line ON reconforge.inventory_movement_lines;
CREATE TRIGGER inventory_receipt_stock_line BEFORE INSERT OR UPDATE OR DELETE ON reconforge.inventory_movement_lines FOR EACH ROW EXECUTE FUNCTION reconforge.guard_inventory_receipt_stock_line();
DROP TRIGGER IF EXISTS inventory_receipt_stock_transition ON reconforge.inventory_movements;
CREATE TRIGGER inventory_receipt_stock_transition BEFORE UPDATE ON reconforge.inventory_movements FOR EACH ROW EXECUTE FUNCTION reconforge.guard_inventory_receipt_stock_transition();
DROP TRIGGER IF EXISTS inventory_receipt_plan ON reconforge.inventory_receipt_plans;
CREATE TRIGGER inventory_receipt_plan BEFORE INSERT OR UPDATE OR DELETE ON reconforge.inventory_receipt_plans FOR EACH ROW EXECUTE FUNCTION reconforge.guard_inventory_receipt_plan();
DROP TRIGGER IF EXISTS inventory_receipt_review ON reconforge.inventory_receipt_reviews;
CREATE TRIGGER inventory_receipt_review BEFORE INSERT OR UPDATE OR DELETE ON reconforge.inventory_receipt_reviews FOR EACH ROW EXECUTE FUNCTION reconforge.guard_inventory_receipt_review();
DROP TRIGGER IF EXISTS inventory_receipt_link ON reconforge.inventory_receipt_links;
CREATE TRIGGER inventory_receipt_link BEFORE INSERT OR UPDATE OR DELETE ON reconforge.inventory_receipt_links FOR EACH ROW EXECUTE FUNCTION reconforge.guard_inventory_receipt_link();
DROP TRIGGER IF EXISTS inventory_receipt_command ON reconforge.inventory_receipt_commands;
CREATE TRIGGER inventory_receipt_command BEFORE INSERT OR UPDATE OR DELETE ON reconforge.inventory_receipt_commands FOR EACH ROW EXECUTE FUNCTION reconforge.guard_inventory_receipt_command();
DROP TRIGGER IF EXISTS inventory_receipt_complete ON reconforge.inventory_receipt_links;
CREATE CONSTRAINT TRIGGER inventory_receipt_complete AFTER INSERT ON reconforge.inventory_receipt_links DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION reconforge.guard_inventory_receipt_complete();
DROP TRIGGER IF EXISTS aaa_inventory_receipt_effect ON reconforge.finance_posting_effects;
CREATE TRIGGER aaa_inventory_receipt_effect BEFORE INSERT ON reconforge.finance_posting_effects FOR EACH ROW EXECUTE FUNCTION reconforge.guard_inventory_receipt_finance_effect();
"""

POSTGRES_INVENTORY_RECEIPT_POSTING_SCHEMA_SQL = _TABLE_SQL + _HELPER_SQL + _PLAN_SQL + _LINK_SQL + _EFFECT_SQL + _RESOURCE_SQL + _HISTORY_SQL + _INSTALL_SQL


def install_postgres_inventory_receipt_posting_schema(connection: Any) -> None:
    """Install the additive current schema inside the caller's transaction."""
    connection.execute(POSTGRES_INVENTORY_RECEIPT_POSTING_SCHEMA_SQL)
