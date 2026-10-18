"""Immutable scoped report capture with SQL-verified native evidence membership."""

from typing import Any

UPGRADE_SQL = r'''
CREATE TABLE IF NOT EXISTS reconforge.financial_report_captures (
 tenant_id TEXT NOT NULL,id TEXT NOT NULL,workspace_id TEXT NOT NULL,organization_id TEXT NOT NULL,legal_entity_id TEXT NOT NULL,
 map_id TEXT NOT NULL,period_id TEXT NOT NULL,as_of_date DATE NOT NULL,actor_id TEXT NOT NULL,command_id TEXT NOT NULL,
 request_digest TEXT NOT NULL CHECK(request_digest ~ '^[0-9a-f]{64}$'),request_json JSONB NOT NULL,
 source_snapshot TEXT NOT NULL,created_at TEXT NOT NULL,membership_sealed BOOLEAN NOT NULL DEFAULT false,
 PRIMARY KEY(tenant_id,id),UNIQUE(tenant_id,workspace_id,command_id),
 FOREIGN KEY(tenant_id,map_id,workspace_id,organization_id,legal_entity_id) REFERENCES reconforge.financial_reporting_maps(tenant_id,id,workspace_id,organization_id,legal_entity_id),
 FOREIGN KEY(tenant_id,actor_id) REFERENCES reconforge.identity_users(tenant_id,id),
 FOREIGN KEY(tenant_id,period_id) REFERENCES reconforge.fiscal_periods(tenant_id,id)
);
CREATE TABLE IF NOT EXISTS reconforge.financial_report_members (
 tenant_id TEXT NOT NULL,capture_id TEXT NOT NULL,ordinal BIGINT NOT NULL CHECK(ordinal>0),effect_id TEXT NOT NULL,
 validation_digest TEXT NOT NULL CHECK(validation_digest ~ '^[0-9a-f]{64}$'),
 previous_digest TEXT NOT NULL CHECK(previous_digest ~ '^[0-9a-f]{64}$'),chain_digest TEXT NOT NULL CHECK(chain_digest ~ '^[0-9a-f]{64}$'),
 PRIMARY KEY(tenant_id,capture_id,ordinal),UNIQUE(tenant_id,capture_id,effect_id),
 FOREIGN KEY(tenant_id,capture_id) REFERENCES reconforge.financial_report_captures(tenant_id,id),
 FOREIGN KEY(tenant_id,effect_id) REFERENCES reconforge.finance_posting_effects(tenant_id,id)
);
CREATE TABLE IF NOT EXISTS reconforge.financial_report_snapshots (
 tenant_id TEXT NOT NULL,capture_id TEXT NOT NULL,payload JSONB NOT NULL CHECK(octet_length(payload::text)<=2097152),
 report_digest TEXT NOT NULL CHECK(report_digest ~ '^[0-9a-f]{64}$'),audit_event_id TEXT NOT NULL,outbox_event_id TEXT NOT NULL,
 PRIMARY KEY(tenant_id,capture_id),FOREIGN KEY(tenant_id,capture_id) REFERENCES reconforge.financial_report_captures(tenant_id,id),
 FOREIGN KEY(tenant_id,audit_event_id) REFERENCES reconforge.domain_audit_events(tenant_id,id),
 FOREIGN KEY(tenant_id,outbox_event_id) REFERENCES reconforge.outbox_events(tenant_id,event_id)
);
-- Existing complete captures from a pre-seal installation are already immutable.
ALTER TABLE reconforge.financial_report_captures ADD COLUMN IF NOT EXISTS membership_sealed BOOLEAN NOT NULL DEFAULT true;
ALTER TABLE reconforge.financial_report_captures ALTER COLUMN membership_sealed SET DEFAULT false;
CREATE INDEX IF NOT EXISTS financial_report_captures_list ON reconforge.financial_report_captures(tenant_id,workspace_id,organization_id,legal_entity_id,created_at DESC,id);
CREATE OR REPLACE FUNCTION reconforge.frs_amounts(d NUMERIC,c NUMERIC) RETURNS JSONB LANGUAGE sql IMMUTABLE SET search_path=pg_catalog AS $frs$
 SELECT jsonb_build_object('debit_minor',d,'credit_minor',c,'balance_minor',d-c,'debit_balance_minor',greatest(d-c,0),'credit_balance_minor',greatest(c-d,0))
$frs$;
CREATE OR REPLACE FUNCTION reconforge.frs_admit() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $frs$
DECLARE p RECORD;e RECORD;prev RECORD;
BEGIN
 IF TG_TABLE_NAME='financial_report_captures' THEN
 IF NOT reconforge.irp_scope(NEW.tenant_id,NEW.workspace_id,NEW.organization_id,NEW.legal_entity_id)
 OR NOT EXISTS(SELECT 1 FROM reconforge.financial_reporting_map_reviews WHERE tenant_id=NEW.tenant_id AND map_id=NEW.map_id)
 OR NOT EXISTS(SELECT 1 FROM reconforge.identity_users WHERE tenant_id=NEW.tenant_id AND id=NEW.actor_id AND NOT disabled)
 OR NEW.request_digest IS DISTINCT FROM reconforge.irp_digest(NEW.request_json)
 OR NEW.request_json IS DISTINCT FROM jsonb_build_object('actor_id',NEW.actor_id,'map_id',NEW.map_id,'period_id',NEW.period_id,'as_of_date',NEW.as_of_date::text)
 OR NOT EXISTS(SELECT 1 FROM reconforge.fiscal_periods WHERE tenant_id=NEW.tenant_id AND id=NEW.period_id AND application_workspace_id=NEW.workspace_id AND NEW.as_of_date BETWEEN start_date AND end_date) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='financial_report_snapshot_closure',MESSAGE='Report capture requires a current human, reviewed map and exact scoped request.'; END IF;
 NEW.source_snapshot:=pg_current_snapshot()::text;
 NEW.membership_sealed:=false;
 RETURN NEW;
 END IF;
 SELECT * INTO p FROM reconforge.financial_report_captures WHERE tenant_id=NEW.tenant_id AND id=NEW.capture_id;
 IF pg_trigger_depth()<>2 OR p IS NULL OR p.membership_sealed OR EXISTS(SELECT 1 FROM reconforge.financial_report_snapshots WHERE tenant_id=NEW.tenant_id AND capture_id=NEW.capture_id) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='financial_report_snapshot_closure',MESSAGE='Sealed report membership cannot be extended or detached.'; END IF;
 SELECT * INTO e FROM reconforge.finance_posting_effects WHERE tenant_id=NEW.tenant_id AND id=NEW.effect_id;
 IF e IS NULL OR (e.workspace_id,e.organization_id,e.legal_entity_id) IS DISTINCT FROM (p.workspace_id,p.organization_id,p.legal_entity_id)
 OR e.validation_digest IS DISTINCT FROM NEW.validation_digest OR reconforge.irp_digest(e.snapshot_json) IS DISTINCT FROM e.validation_digest
 OR (e.snapshot_json->'entry'->>'posting_date')::date>p.as_of_date
 THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='financial_report_snapshot_closure',MESSAGE='Report member requires its exact captured visible native effect.'; END IF;
 IF NEW.ordinal=1 THEN
 IF NEW.previous_digest IS DISTINCT FROM reconforge.irp_digest(jsonb_build_array('financial-reporting-snapshot-v1','ordered-native-evidence')) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='financial_report_snapshot_closure',MESSAGE='Report evidence chain seed differs.'; END IF;
 ELSE
 SELECT * INTO prev FROM reconforge.financial_report_members WHERE tenant_id=NEW.tenant_id AND capture_id=NEW.capture_id AND ordinal=NEW.ordinal-1;
 IF prev IS NULL OR prev.chain_digest IS DISTINCT FROM NEW.previous_digest OR prev.effect_id COLLATE "C">=NEW.effect_id COLLATE "C" THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='financial_report_snapshot_closure',MESSAGE='Report evidence chain order or predecessor differs.'; END IF;
 END IF;
 IF NEW.chain_digest IS DISTINCT FROM reconforge.irp_digest(jsonb_build_array(NEW.previous_digest,NEW.ordinal,NEW.effect_id,NEW.validation_digest)) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='financial_report_snapshot_closure',MESSAGE='Report evidence chain digest differs.'; END IF;
 RETURN NEW;
END $frs$;
CREATE OR REPLACE FUNCTION reconforge.frs_capture_members() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $frs$
DECLARE e RECORD;ordinal BIGINT:=0;previous TEXT:=reconforge.irp_digest(jsonb_build_array('financial-reporting-snapshot-v1','ordered-native-evidence'));chain TEXT;
BEGIN
 -- This cursor has one statement snapshot. Later commits and backdated effects
 -- cannot change the retained membership, including after vacuum or restoration.
 FOR e IN SELECT p.id,p.validation_digest FROM reconforge.finance_posting_effects p
 WHERE p.tenant_id=NEW.tenant_id AND (p.workspace_id,p.organization_id,p.legal_entity_id)=(NEW.workspace_id,NEW.organization_id,NEW.legal_entity_id)
 AND (p.snapshot_json->'entry'->>'posting_date')::date<=NEW.as_of_date ORDER BY p.id COLLATE "C" LOOP
 ordinal:=ordinal+1;chain:=reconforge.irp_digest(jsonb_build_array(previous,ordinal,e.id,e.validation_digest));
 INSERT INTO reconforge.financial_report_members(tenant_id,capture_id,ordinal,effect_id,validation_digest,previous_digest,chain_digest)
 VALUES(NEW.tenant_id,NEW.id,ordinal,e.id,e.validation_digest,previous,chain);previous:=chain;
 END LOOP;
 UPDATE reconforge.financial_report_captures SET membership_sealed=true WHERE tenant_id=NEW.tenant_id AND id=NEW.id;
 RETURN NEW;
END $frs$;
CREATE OR REPLACE FUNCTION reconforge.frs_capture_immutable() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $frs$
BEGIN
 -- The false state exists only while the parent's synchronous AFTER INSERT
 -- trigger is still running. Once INSERT returns, even a nested unrelated
 -- trigger cannot reopen membership or substitute captured provenance.
 IF TG_OP='UPDATE' THEN
 IF pg_trigger_depth()=2 AND NOT OLD.membership_sealed AND NEW.membership_sealed
 AND to_jsonb(OLD)-'membership_sealed'=to_jsonb(NEW)-'membership_sealed' THEN RETURN NEW; END IF;
 END IF;
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='financial_report_snapshot_closure',MESSAGE='Report capture provenance and completed membership seal are immutable.';
END $frs$;
CREATE OR REPLACE FUNCTION reconforge.frs_close() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $frs$
DECLARE p RECORD;s RECORD;m RECORD;section_value JSONB;phase TEXT;section TEXT;expected JSONB;accounts JSONB;sections JSONB:='{}'::jsonb;
 count_effect BIGINT;count_line BIGINT;opening_count BIGINT;activity_count BIGINT;chain TEXT;currency JSONB;cash JSONB;
 d NUMERIC;c NUMERIC;nd NUMERIC;nc NUMERIC;cash_o NUMERIC;cash_a NUMERIC;inflow NUMERIC;outflow NUMERIC;cash_count BIGINT;
 assets NUMERIC;liabilities NUMERIC;equity NUMERIC;result NUMERIC;period RECORD;
BEGIN
 SELECT * INTO p FROM reconforge.financial_report_captures WHERE tenant_id=NEW.tenant_id AND id=(to_jsonb(NEW)->>CASE WHEN TG_TABLE_NAME='financial_report_captures' THEN 'id' ELSE 'capture_id' END);
 SELECT * INTO s FROM reconforge.financial_report_snapshots WHERE tenant_id=p.tenant_id AND capture_id=p.id;
 SELECT * INTO m FROM reconforge.financial_reporting_maps WHERE tenant_id=p.tenant_id AND id=p.map_id;
 SELECT * INTO period FROM reconforge.fiscal_periods WHERE tenant_id=p.tenant_id AND id=p.period_id;
 IF NOT p.membership_sealed OR s IS NULL OR reconforge.irp_digest(s.payload-'report_digest') IS DISTINCT FROM s.report_digest OR s.payload->>'report_digest' IS DISTINCT FROM s.report_digest
 OR NOT reconforge.fr_event(p.tenant_id,p.id,p.workspace_id,p.organization_id,p.legal_entity_id,s.audit_event_id,s.outbox_event_id,p.actor_id,'financial_report_snapshot_created',jsonb_build_object('report_digest',s.report_digest,'evidence_digest',s.payload->>'evidence_digest')) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='financial_report_snapshot_closure',MESSAGE='Report capture requires complete immutable summary and audit closure.'; END IF;
 SELECT count(*),coalesce(sum(jsonb_array_length(e.snapshot_json->'lines')),0),count(*) FILTER(WHERE (e.snapshot_json->'entry'->>'posting_date')::date<period.start_date)
 INTO count_effect,count_line,opening_count FROM reconforge.financial_report_members x JOIN reconforge.finance_posting_effects e ON e.tenant_id=x.tenant_id AND e.id=x.effect_id WHERE x.tenant_id=p.tenant_id AND x.capture_id=p.id;
 activity_count:=count_effect-opening_count;
 SELECT chain_digest INTO chain FROM reconforge.financial_report_members WHERE tenant_id=p.tenant_id AND capture_id=p.id ORDER BY ordinal DESC LIMIT 1;
 chain:=coalesce(chain,reconforge.irp_digest(jsonb_build_array('financial-reporting-snapshot-v1','ordered-native-evidence')));
 SELECT jsonb_build_object('currency_code',e.currency_code,'currency_precision',e.currency_precision,'currency_rounding_policy',e.currency_rounding_policy,'currency_registry_version',e.currency_registry_version,'currency_registry_digest',e.currency_registry_digest)
 INTO currency FROM reconforge.financial_report_members x JOIN reconforge.finance_posting_effects e ON e.tenant_id=x.tenant_id AND e.id=x.effect_id WHERE x.tenant_id=p.tenant_id AND x.capture_id=p.id LIMIT 1;
 IF EXISTS(SELECT 1 FROM reconforge.financial_report_members x JOIN reconforge.finance_posting_effects e ON e.tenant_id=x.tenant_id AND e.id=x.effect_id WHERE x.tenant_id=p.tenant_id AND x.capture_id=p.id AND (
 jsonb_build_object('currency_code',e.currency_code,'currency_precision',e.currency_precision,'currency_rounding_policy',e.currency_rounding_policy,'currency_registry_version',e.currency_registry_version,'currency_registry_digest',e.currency_registry_digest) IS DISTINCT FROM currency
 OR ((e.snapshot_json->'entry'->>'posting_date')::date>=period.start_date AND e.snapshot_json->'entry'->>'period_id'<>p.period_id))) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='financial_report_snapshot_closure',MESSAGE='Report native currency or overlapping period differs.'; END IF;
 WITH native AS (SELECT l->>'account_id' account_id,(e.snapshot_json->'entry'->>'posting_date')::date<period.start_date opening,(l->>'debit_minor')::numeric d,(l->>'credit_minor')::numeric c
 FROM reconforge.financial_report_members x JOIN reconforge.finance_posting_effects e ON e.tenant_id=x.tenant_id AND e.id=x.effect_id CROSS JOIN LATERAL jsonb_array_elements(e.snapshot_json->'lines') l WHERE x.tenant_id=p.tenant_id AND x.capture_id=p.id),
 sums AS (SELECT account_id,coalesce(sum(native.d) FILTER(WHERE opening),0) od,coalesce(sum(native.c) FILTER(WHERE opening),0) oc,coalesce(sum(native.d) FILTER(WHERE NOT opening),0) ad,coalesce(sum(native.c) FILTER(WHERE NOT opening),0) ac,count(*) lines FROM native GROUP BY account_id),
 rows AS (SELECT a||jsonb_build_object('opening',reconforge.frs_amounts(od,oc),'activity',reconforge.frs_amounts(ad,ac),'closing',reconforge.frs_amounts(od+ad,oc+ac),'line_count',lines) account FROM sums JOIN LATERAL jsonb_array_elements(m.payload->'accounts') a ON a->>'account_id'=sums.account_id)
 SELECT coalesce(jsonb_agg(account ORDER BY account->>'account_id' COLLATE "C"),'[]'::jsonb) INTO accounts FROM rows;
 IF accounts IS DISTINCT FROM s.payload->'trial_balance'->'accounts' OR count_line<>(SELECT coalesce(sum((a->>'line_count')::bigint),0) FROM jsonb_array_elements(accounts) a) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='financial_report_snapshot_closure',MESSAGE='Report exact account sums or retained classification differs from native lines.'; END IF;
 expected:='{}'::jsonb;
 FOREACH phase IN ARRAY ARRAY['opening','activity','closing'] LOOP
 SELECT coalesce(sum((a->phase->>'debit_minor')::numeric),0),coalesce(sum((a->phase->>'credit_minor')::numeric),0),coalesce(sum((a->phase->>'debit_balance_minor')::numeric),0),coalesce(sum((a->phase->>'credit_balance_minor')::numeric),0) INTO d,c,nd,nc FROM jsonb_array_elements(accounts) a;
 IF d<>c OR nd<>nc THEN RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='financial_report_snapshot_closure',MESSAGE='Report totals do not balance.'; END IF;
 expected:=expected||jsonb_build_object(phase,jsonb_build_object('effect_count',CASE phase WHEN 'opening' THEN opening_count WHEN 'activity' THEN activity_count ELSE count_effect END,'turnover_totals',jsonb_build_object('debit_minor',d,'credit_minor',c,'balanced',true),'balance_totals',jsonb_build_object('debit_minor',nd,'credit_minor',nc,'balanced',true)));
 END LOOP;
 IF expected IS DISTINCT FROM s.payload->'trial_balance'->'totals' THEN RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='financial_report_snapshot_closure',MESSAGE='Report totals differ from native sums.'; END IF;
 FOREACH section IN ARRAY ARRAY['CurrentAsset','NonCurrentAsset','CurrentLiability','NonCurrentLiability','Equity','Income','Expense'] LOOP
 section_value:='{}'::jsonb;
 FOREACH phase IN ARRAY ARRAY['opening','activity','closing'] LOOP
 SELECT coalesce(sum((v->phase->>'balance_minor')::numeric*CASE WHEN v->>'account_type' IN ('Asset','Expense') THEN 1 ELSE -1 END),0) INTO d FROM jsonb_array_elements(accounts) v WHERE v->>'section'=section;
 section_value:=section_value||jsonb_build_object(phase||'_minor',d); END LOOP;
 sections:=sections||jsonb_build_object(section,section_value); END LOOP;
 SELECT coalesce(sum((a->'opening'->>'balance_minor')::numeric),0),coalesce(sum((a->'activity'->>'balance_minor')::numeric),0) INTO cash_o,cash_a FROM jsonb_array_elements(accounts) a WHERE (a->>'is_cash')::boolean;
 WITH movements AS (SELECT e.id,sum((l->>'debit_minor')::numeric-(l->>'credit_minor')::numeric) delta FROM reconforge.financial_report_members x JOIN reconforge.finance_posting_effects e ON e.tenant_id=x.tenant_id AND e.id=x.effect_id CROSS JOIN LATERAL jsonb_array_elements(e.snapshot_json->'lines') l
 JOIN LATERAL jsonb_array_elements(m.payload->'accounts') a ON a->>'account_id'=l->>'account_id' AND (a->>'is_cash')::boolean WHERE x.tenant_id=p.tenant_id AND x.capture_id=p.id AND (e.snapshot_json->'entry'->>'posting_date')::date>=period.start_date GROUP BY e.id)
 SELECT count(*),coalesce(sum(greatest(delta,0)),0),coalesce(sum(greatest(-delta,0)),0) INTO cash_count,inflow,outflow FROM movements;
 cash:=jsonb_build_object('opening_minor',cash_o,'activity_minor',cash_a,'closing_minor',cash_o+cash_a,'inflow_minor',inflow,'outflow_minor',outflow,'movement_count',cash_count);
 assets:=(sections->'CurrentAsset'->>'closing_minor')::numeric+(sections->'NonCurrentAsset'->>'closing_minor')::numeric;
 liabilities:=(sections->'CurrentLiability'->>'closing_minor')::numeric+(sections->'NonCurrentLiability'->>'closing_minor')::numeric;equity:=(sections->'Equity'->>'closing_minor')::numeric;result:=(sections->'Income'->>'closing_minor')::numeric-(sections->'Expense'->>'closing_minor')::numeric;
 expected:=jsonb_build_object('contract_version','financial-reporting-snapshot-v1','balance_scope','immutable-captured-native-postings','id',p.id,'workspace_id',p.workspace_id,'organization_id',p.organization_id,'legal_entity_id',p.legal_entity_id,
 'organization_code',(SELECT organization_code FROM reconforge.organizations WHERE tenant_id=p.tenant_id AND id=p.organization_id),'entity_code',(SELECT entity_code FROM reconforge.legal_entities WHERE tenant_id=p.tenant_id AND id=p.legal_entity_id),
 'period_id',p.period_id,'period_start',period.start_date::text,'period_end',period.end_date::text,'as_of_date',p.as_of_date::text,'source_snapshot',p.source_snapshot,'captured_at',p.created_at,
 'map_id',p.map_id,'map_digest',m.map_digest,'currency_policy',currency,'effect_count',count_effect,'line_count',count_line,'evidence_digest',chain,'trial_balance',s.payload->'trial_balance','sections',sections,
 'balance_sheet',jsonb_build_object('assets_minor',assets,'liabilities_minor',liabilities,'equity_minor',equity,'accumulated_unclosed_result_minor',result,'balanced',true),
 'income_statement',jsonb_build_object('income_minor',(sections->'Income'->>'activity_minor')::numeric,'expense_minor',(sections->'Expense'->>'activity_minor')::numeric,'result_minor',(sections->'Income'->>'activity_minor')::numeric-(sections->'Expense'->>'activity_minor')::numeric),'cash_movements',cash);
 IF assets<>liabilities+equity+result OR cash_a<>inflow-outflow OR expected IS DISTINCT FROM s.payload-'report_digest' THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='financial_report_snapshot_closure',MESSAGE='Report statements differ from native sums or exact scoped capture.'; END IF;
 RETURN NEW;
END $frs$;
DROP TRIGGER IF EXISTS report_snapshot_capture_members ON reconforge.financial_report_captures;
CREATE TRIGGER report_snapshot_capture_members AFTER INSERT ON reconforge.financial_report_captures FOR EACH ROW EXECUTE FUNCTION reconforge.frs_capture_members();
DO $install$ DECLARE n TEXT; BEGIN
 FOREACH n IN ARRAY ARRAY['financial_report_captures','financial_report_members','financial_report_snapshots'] LOOP
 EXECUTE format('ALTER TABLE reconforge.%I ENABLE ROW LEVEL SECURITY',n);EXECUTE format('ALTER TABLE reconforge.%I FORCE ROW LEVEL SECURITY',n);
 EXECUTE format('DROP POLICY IF EXISTS report_snapshot_scope ON reconforge.%I',n);
 IF n='financial_report_captures' THEN
 EXECUTE format('CREATE POLICY report_snapshot_scope ON reconforge.%I USING(reconforge.irp_scope(tenant_id,workspace_id,organization_id,legal_entity_id)) WITH CHECK(reconforge.irp_scope(tenant_id,workspace_id,organization_id,legal_entity_id))',n);
 ELSE EXECUTE format('CREATE POLICY report_snapshot_scope ON reconforge.%I USING(EXISTS(SELECT 1 FROM reconforge.financial_report_captures p WHERE p.tenant_id=%I.tenant_id AND p.id=%I.capture_id))',n,n,n); END IF;
 EXECUTE format('DROP TRIGGER IF EXISTS report_snapshot_immutable ON reconforge.%I',n);
 IF n='financial_report_captures' THEN
 EXECUTE format('CREATE TRIGGER report_snapshot_immutable BEFORE UPDATE OR DELETE ON reconforge.%I FOR EACH ROW EXECUTE FUNCTION reconforge.frs_capture_immutable()',n);
 ELSE EXECUTE format('CREATE TRIGGER report_snapshot_immutable BEFORE UPDATE OR DELETE ON reconforge.%I FOR EACH ROW EXECUTE FUNCTION reconforge.fr_immutable()',n); END IF;
 IF n<>'financial_report_snapshots' THEN
 EXECUTE format('DROP TRIGGER IF EXISTS report_snapshot_admission ON reconforge.%I',n);
 EXECUTE format('CREATE TRIGGER report_snapshot_admission BEFORE INSERT ON reconforge.%I FOR EACH ROW EXECUTE FUNCTION reconforge.frs_admit()',n); END IF;
 IF n<>'financial_report_members' THEN
 EXECUTE format('DROP TRIGGER IF EXISTS report_snapshot_closure ON reconforge.%I',n);
 EXECUTE format('CREATE CONSTRAINT TRIGGER report_snapshot_closure AFTER INSERT ON reconforge.%I DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION reconforge.frs_close()',n); END IF;
 END LOOP;
END $install$;
'''

DOWNGRADE_SQL = r'''
DO $guard$ BEGIN IF EXISTS(SELECT 1 FROM reconforge.financial_report_captures) THEN RAISE EXCEPTION 'Immutable financial report snapshots require forward recovery.'; END IF; END $guard$;
DROP TABLE reconforge.financial_report_snapshots,reconforge.financial_report_members,reconforge.financial_report_captures;
DROP FUNCTION reconforge.frs_close(),reconforge.frs_capture_members(),reconforge.frs_admit(),reconforge.frs_capture_immutable(),reconforge.frs_amounts(NUMERIC,NUMERIC);
'''


def install_postgres_financial_reporting_snapshot_schema(connection: Any) -> None:
    with connection.transaction():
        connection.execute(UPGRADE_SQL)
