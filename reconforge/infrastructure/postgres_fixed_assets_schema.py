"""Additive source and native GL closure for retained fixed asset history."""

UPGRADE_SQL = r"""
DO $fa$ BEGIN
 IF EXISTS(SELECT 1 FROM reconforge.finance_entries WHERE upper(entry_number) LIKE 'FA1-%' OR upper(id) LIKE 'FA1-%') THEN
  RAISE EXCEPTION 'FA1 namespace already contains incompatible native entries';
 END IF;
END $fa$;
CREATE TABLE reconforge.fixed_assets (
 tenant_id TEXT NOT NULL,id TEXT NOT NULL,workspace_id TEXT NOT NULL,organization_id TEXT NOT NULL,legal_entity_id TEXT NOT NULL,
 asset_number TEXT NOT NULL,payload JSONB NOT NULL,PRIMARY KEY(tenant_id,id),
 UNIQUE(tenant_id,workspace_id,organization_id,legal_entity_id,asset_number)
);
CREATE TABLE reconforge.fixed_asset_plans (
 tenant_id TEXT NOT NULL,id TEXT NOT NULL,workspace_id TEXT NOT NULL,organization_id TEXT NOT NULL,legal_entity_id TEXT NOT NULL,
 asset_id TEXT NOT NULL,entry_id TEXT NOT NULL,sequence INTEGER NOT NULL CHECK(sequence BETWEEN 0 AND 1201),
 kind TEXT NOT NULL CHECK(kind IN ('acquire','depreciate','dispose')),phase INTEGER NOT NULL CHECK(phase BETWEEN 0 AND 2),
 payload JSONB NOT NULL,audit_event_id TEXT NOT NULL,outbox_event_id TEXT NOT NULL,
 PRIMARY KEY(tenant_id,id),UNIQUE(tenant_id,entry_id),UNIQUE(tenant_id,asset_id,sequence),
 FOREIGN KEY(tenant_id,asset_id) REFERENCES reconforge.fixed_assets(tenant_id,id),
 FOREIGN KEY(tenant_id,entry_id) REFERENCES reconforge.finance_entries(tenant_id,id)
);
CREATE UNIQUE INDEX fixed_asset_pending ON reconforge.fixed_asset_plans(tenant_id,asset_id) WHERE phase<2;
CREATE TABLE reconforge.fixed_asset_reviews (
 tenant_id TEXT NOT NULL,plan_id TEXT NOT NULL,reviewer_actor_id TEXT NOT NULL,reason TEXT NOT NULL,
 audit_event_id TEXT NOT NULL,outbox_event_id TEXT NOT NULL,PRIMARY KEY(tenant_id,plan_id),
 FOREIGN KEY(tenant_id,plan_id) REFERENCES reconforge.fixed_asset_plans(tenant_id,id),
 FOREIGN KEY(tenant_id,reviewer_actor_id) REFERENCES reconforge.identity_users(tenant_id,id)
);
CREATE TABLE reconforge.fixed_asset_links (
 tenant_id TEXT NOT NULL,plan_id TEXT NOT NULL,posting_effect_id TEXT NOT NULL,posted_actor_id TEXT NOT NULL,
 reason TEXT NOT NULL,audit_event_id TEXT NOT NULL,outbox_event_id TEXT NOT NULL,PRIMARY KEY(tenant_id,plan_id),
 UNIQUE(tenant_id,posting_effect_id),FOREIGN KEY(tenant_id,plan_id) REFERENCES reconforge.fixed_asset_plans(tenant_id,id),
 FOREIGN KEY(tenant_id,posting_effect_id) REFERENCES reconforge.finance_posting_effects(tenant_id,id),
 FOREIGN KEY(tenant_id,posted_actor_id) REFERENCES reconforge.identity_users(tenant_id,id)
);
CREATE TABLE reconforge.fixed_asset_commands (
 tenant_id TEXT NOT NULL,workspace_id TEXT NOT NULL,organization_id TEXT NOT NULL,legal_entity_id TEXT NOT NULL,
 plan_id TEXT NOT NULL,operation TEXT NOT NULL CHECK(operation IN ('prepare','review','post')),command_id TEXT NOT NULL,
 actor_id TEXT NOT NULL,request_digest TEXT NOT NULL,request_json JSONB NOT NULL,response_json JSONB NOT NULL,
 PRIMARY KEY(tenant_id,workspace_id,command_id),UNIQUE(tenant_id,plan_id,operation),
 FOREIGN KEY(tenant_id,plan_id) REFERENCES reconforge.fixed_asset_plans(tenant_id,id),
 FOREIGN KEY(tenant_id,actor_id) REFERENCES reconforge.identity_users(tenant_id,id)
);
CREATE FUNCTION reconforge.asset_protect() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $fa$
BEGIN
 IF TG_TABLE_NAME='fixed_asset_plans' AND TG_OP='UPDATE' THEN
  IF NEW.phase=OLD.phase+1 AND (to_jsonb(NEW)-'phase')=(to_jsonb(OLD)-'phase') THEN RETURN NEW; END IF;
 END IF;
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='fixed_asset_owner',MESSAGE='Retained asset evidence is immutable';
END $fa$;
CREATE FUNCTION reconforge.asset_event(t TEXT,p TEXT,a TEXT,b TEXT,actor TEXT,action TEXT,metadata JSONB) RETURNS BOOLEAN
 LANGUAGE sql STABLE SET search_path=pg_catalog AS $fa$
 SELECT EXISTS(SELECT 1 FROM reconforge.domain_audit_events x JOIN reconforge.outbox_events y ON y.tenant_id=x.tenant_id
 JOIN reconforge.fixed_asset_plans z ON z.tenant_id=x.tenant_id AND z.id=p
 WHERE x.tenant_id=t AND x.id=a AND y.event_id=b AND x.actor_user_id=actor AND x.object_type='operational_finance' AND x.object_id=p
 AND x.action=$6 AND x.metadata_json=$7 AND y.event_type=$6 AND y.aggregate_type='operational_finance' AND y.aggregate_id=p
 AND y.payload=$7||jsonb_build_object('audit_event_id',a)
 AND (y.workspace_id,y.organization_id,y.legal_entity_id)=(z.workspace_id,z.organization_id,z.legal_entity_id))
$fa$;
CREATE FUNCTION reconforge.asset_command_actor() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $fa$
DECLARE permission TEXT;
BEGIN
 permission:=CASE NEW.operation WHEN 'prepare' THEN 'finance_core.manage' WHEN 'review' THEN 'finance_core.validate' ELSE 'finance_core.post' END;
 IF NOT EXISTS(SELECT 1 FROM reconforge.identity_users u WHERE u.tenant_id=NEW.tenant_id AND u.id=NEW.actor_id AND NOT u.disabled)
 OR NOT EXISTS(SELECT 1 FROM reconforge.identity_user_roles assignments
 JOIN reconforge.identity_role_permissions grants ON grants.tenant_id=assignments.tenant_id AND grants.role_id=assignments.role_id
 JOIN reconforge.identity_roles roles ON roles.tenant_id=assignments.tenant_id AND roles.id=assignments.role_id
 WHERE assignments.tenant_id=NEW.tenant_id AND assignments.user_id=NEW.actor_id AND assignments.active AND grants.active
 AND roles.active AND grants.permission_name=permission) THEN
  RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='fixed_asset_owner',MESSAGE='Asset command requires current persisted human permission'; END IF;
 RETURN NEW;
END $fa$;
CREATE TRIGGER fixed_asset_current_actor BEFORE INSERT ON reconforge.fixed_asset_commands FOR EACH ROW EXECUTE FUNCTION reconforge.asset_command_actor();
CREATE FUNCTION reconforge.asset_close(t TEXT,i TEXT) RETURNS VOID LANGUAGE plpgsql SET search_path=pg_catalog AS $fa$
DECLARE p RECORD;a RECORD;e RECORD;r RECORD;l RECORD;f RECORD;c RECORD;prior RECORD;native_journal RECORD;
 field_name TEXT;account_kind TEXT;account_code TEXT;account_id TEXT;expected_kind TEXT;idx INTEGER;
 asset JSONB;v JSONB;header JSONB;lines JSONB;expected JSONB:='[]'::jsonb;item JSONB;request JSONB;
 cost NUMERIC;salvage NUMERIC;life INTEGER;accumulated NUMERIC:=0;months INTEGER:=0;after_months INTEGER;amount NUMERIC;
 proceeds NUMERIC;carrying NUMERIC;last_date DATE;through_date DATE;expected_id TEXT;expected_debit NUMERIC;expected_credit NUMERIC;
BEGIN
 SELECT * INTO p FROM reconforge.fixed_asset_plans WHERE tenant_id=t AND id=i;
 IF p IS NULL THEN RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='fixed_asset_owner',MESSAGE='FA1 entry requires its retained asset owner'; END IF;
 SELECT * INTO a FROM reconforge.fixed_assets WHERE tenant_id=t AND id=p.asset_id;
 SELECT * INTO e FROM reconforge.finance_entries WHERE tenant_id=t AND id=p.entry_id;
 SELECT * INTO r FROM reconforge.fixed_asset_reviews WHERE tenant_id=t AND plan_id=i;
 SELECT * INTO l FROM reconforge.fixed_asset_links WHERE tenant_id=t AND plan_id=i;
 asset:=a.payload;v:=p.payload;
 IF a IS NULL OR e IS NULL OR jsonb_typeof(asset) IS DISTINCT FROM 'object' OR jsonb_typeof(v) IS DISTINCT FROM 'object'
 OR asset->>'schema_version' IS DISTINCT FROM 'fixed-asset-v1' OR v->>'schema_version' IS DISTINCT FROM 'fixed-asset-plan-v1'
 OR NOT asset ?& ARRAY['schema_version','id','workspace_id','organization_id','legal_entity_id','organization_code','entity_code',
 'asset_number','name','journal_code','period_id','posting_date','in_service_date','cost_minor','salvage_minor','useful_life_months',
 'asset_account_code','accumulated_account_code','expense_account_code','cash_account_code','gain_account_code','loss_account_code',
 'reason','currency_code','currency_precision','preparer_actor_id','asset_digest']
 OR asset-ARRAY['schema_version','id','workspace_id','organization_id','legal_entity_id','organization_code','entity_code',
 'asset_number','name','journal_code','period_id','posting_date','in_service_date','cost_minor','salvage_minor','useful_life_months',
 'asset_account_code','accumulated_account_code','expense_account_code','cash_account_code','gain_account_code','loss_account_code',
 'reason','currency_code','currency_precision','preparer_actor_id','asset_digest']<>'{}'::jsonb
 OR NOT v ?& ARRAY['schema_version','id','asset_id','workspace_id','organization_id','legal_entity_id','organization_code','entity_code',
 'currency_code','currency_precision','kind','period_id','posting_date','through_month','proceeds_minor','reason','sequence','asset_digest',
 'entry_id','amount_minor','accumulated_before_minor','months_before','months_after','snapshot','preparer_actor_id','command_request',
 'plan_digest','validation_digest']
 OR v-ARRAY['schema_version','id','asset_id','workspace_id','organization_id','legal_entity_id','organization_code','entity_code',
 'currency_code','currency_precision','kind','period_id','posting_date','through_month','proceeds_minor','reason','sequence','asset_digest',
 'entry_id','amount_minor','accumulated_before_minor','months_before','months_after','snapshot','preparer_actor_id','command_request',
 'plan_digest','validation_digest']<>'{}'::jsonb THEN
  RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='fixed_asset_owner',MESSAGE='Asset and plan require their exact versioned schemas';
 END IF;
 FOREACH field_name IN ARRAY ARRAY['id','workspace_id','organization_id','legal_entity_id','organization_code','entity_code','asset_number','name',
 'journal_code','period_id','posting_date','in_service_date','asset_account_code','accumulated_account_code','expense_account_code',
 'cash_account_code','gain_account_code','loss_account_code','reason','currency_code','preparer_actor_id','asset_digest'] LOOP
  IF jsonb_typeof(asset->field_name) IS DISTINCT FROM 'string' OR NOT reconforge.irp_text(asset->>field_name,CASE WHEN field_name='reason' THEN 500 ELSE 160 END) THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='fixed_asset_owner',MESSAGE='Asset metadata requires bounded printable text'; END IF;
 END LOOP;
 FOREACH field_name IN ARRAY ARRAY['cost_minor','salvage_minor','useful_life_months','currency_precision'] LOOP
  IF jsonb_typeof(asset->field_name) IS DISTINCT FROM 'number' OR (asset->>field_name)!~'^(0|[1-9][0-9]*)$' THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='fixed_asset_owner',MESSAGE='Asset amounts require exact integer minor units'; END IF;
 END LOOP;
 FOREACH field_name IN ARRAY ARRAY['proceeds_minor','sequence','amount_minor','accumulated_before_minor','months_before','months_after','currency_precision'] LOOP
  IF jsonb_typeof(v->field_name) IS DISTINCT FROM 'number' OR (v->>field_name)!~'^(0|[1-9][0-9]*)$' THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='fixed_asset_owner',MESSAGE='Plan amounts require exact integer minor units'; END IF;
 END LOOP;
 cost:=(asset->>'cost_minor')::numeric;salvage:=(asset->>'salvage_minor')::numeric;life:=(asset->>'useful_life_months')::integer;
 proceeds:=(v->>'proceeds_minor')::numeric;
 IF cost NOT BETWEEN 1 AND 9000000000000000000 OR salvage<0 OR salvage>=cost OR life NOT BETWEEN 1 AND 1200
 OR proceeds NOT BETWEEN 0 AND 9000000000000000000 OR (asset->>'currency_precision')::integer NOT BETWEEN 0 AND 8
 OR asset->>'asset_digest' IS DISTINCT FROM reconforge.irp_digest(asset-'asset_digest')
 OR v->>'plan_digest' IS DISTINCT FROM reconforge.irp_digest(v-ARRAY['plan_digest','validation_digest'])
 OR v->>'asset_digest' IS DISTINCT FROM asset->>'asset_digest' OR v->>'validation_digest' IS DISTINCT FROM reconforge.irp_digest(v->'snapshot')
 OR (asset->>'id',asset->>'asset_number',asset->>'workspace_id',asset->>'organization_id',asset->>'legal_entity_id') IS DISTINCT FROM
 (a.id,a.asset_number,a.workspace_id,a.organization_id,a.legal_entity_id)
 OR (v->>'id',v->>'asset_id',v->>'entry_id',v->>'kind',v->>'workspace_id',v->>'organization_id',v->>'legal_entity_id') IS DISTINCT FROM
 (p.id,p.asset_id,p.entry_id,p.kind,p.workspace_id,p.organization_id,p.legal_entity_id)
 OR (p.workspace_id,p.organization_id,p.legal_entity_id) IS DISTINCT FROM (a.workspace_id,a.organization_id,a.legal_entity_id)
 OR (v->>'organization_code',v->>'entity_code',v->>'currency_code',v->>'currency_precision') IS DISTINCT FROM
 (asset->>'organization_code',asset->>'entity_code',asset->>'currency_code',asset->>'currency_precision')
 OR (v->>'sequence')::integer<>p.sequence OR p.id!~'^FA1-[0-9a-f]{32}$'
 OR (asset->>'in_service_date')::date<(asset->>'posting_date')::date THEN
  RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='fixed_asset_owner',MESSAGE='Retained asset definition, exact amounts and plan seal differ'; END IF;
 last_date:=(asset->>'posting_date')::date;
 idx:=0;
 FOR prior IN SELECT * FROM reconforge.fixed_asset_plans WHERE tenant_id=t AND asset_id=p.asset_id AND sequence<p.sequence ORDER BY sequence LOOP
  IF prior.sequence<>idx OR prior.phase<>2 OR (idx=0 AND prior.kind<>'acquire') OR prior.kind='dispose' THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='fixed_asset_owner',MESSAGE='Asset history requires ordered posted acquisition and no disposal'; END IF;
  idx:=idx+1;
  IF prior.kind='depreciate' THEN accumulated:=accumulated+(prior.payload->>'amount_minor')::numeric; END IF;
  months:=(prior.payload->>'months_after')::integer;last_date:=(prior.payload->>'posting_date')::date;
 END LOOP;
 IF idx<>p.sequence OR (v->>'accumulated_before_minor')::numeric<>accumulated OR (v->>'months_before')::integer<>months
 OR (v->>'posting_date')::date<last_date OR (p.sequence=0) IS DISTINCT FROM (p.kind='acquire') THEN
  RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='fixed_asset_owner',MESSAGE='Asset operation requires its exact preceding basis and chronology'; END IF;
 after_months:=months;
 IF p.kind='acquire' THEN
  IF proceeds<>0 OR v->>'through_month'<>'' OR v->>'posting_date'<>asset->>'posting_date' OR v->>'period_id'<>asset->>'period_id'
   OR v->>'preparer_actor_id'<>asset->>'preparer_actor_id' OR v->>'reason'<>asset->>'reason' THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='fixed_asset_owner',MESSAGE='Acquisition must retain its original definition'; END IF;
  amount:=cost;
  expected:=jsonb_build_array(jsonb_build_object('code',asset->>'asset_account_code','debit',cost,'credit',0),
                              jsonb_build_object('code',asset->>'cash_account_code','debit',0,'credit',cost));
  request:=(asset-ARRAY['schema_version','id','currency_code','currency_precision','preparer_actor_id','asset_digest'])||jsonb_build_object('kind','acquire');
 ELSIF p.kind='depreciate' THEN
  IF proceeds<>0 OR v->>'through_month'!~'^[0-9]{4}-(0[1-9]|1[0-2])$' THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='fixed_asset_owner',MESSAGE='Depreciation requires a completed calendar month'; END IF;
  through_date:=(v->>'through_month'||'-01')::date;
  IF (v->>'posting_date')::date<(through_date+INTERVAL '1 month')::date THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='fixed_asset_owner',MESSAGE='Depreciation cannot recognize an uncompleted month'; END IF;
  after_months:=LEAST(life,(EXTRACT(YEAR FROM through_date)::integer-EXTRACT(YEAR FROM (asset->>'in_service_date')::date)::integer)*12
    +EXTRACT(MONTH FROM through_date)::integer-EXTRACT(MONTH FROM (asset->>'in_service_date')::date)::integer+1);
  amount:=floor(((cost-salvage)*after_months*2+life)/(2*life))-accumulated;
  IF after_months<=months OR amount<=0 THEN RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='fixed_asset_owner',MESSAGE='No new positive cumulative depreciation is due'; END IF;
  expected:=jsonb_build_array(jsonb_build_object('code',asset->>'expense_account_code','debit',amount,'credit',0),
                              jsonb_build_object('code',asset->>'accumulated_account_code','debit',0,'credit',amount));
 ELSE
  IF v->>'through_month'<>'' THEN RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='fixed_asset_owner',MESSAGE='Disposal does not include a depreciation month'; END IF;
  amount:=cost-accumulated;carrying:=amount;
  IF proceeds>0 THEN expected:=expected||jsonb_build_array(jsonb_build_object('code',asset->>'cash_account_code','debit',proceeds,'credit',0)); END IF;
  IF accumulated>0 THEN expected:=expected||jsonb_build_array(jsonb_build_object('code',asset->>'accumulated_account_code','debit',accumulated,'credit',0)); END IF;
  IF carrying>proceeds THEN expected:=expected||jsonb_build_array(jsonb_build_object('code',asset->>'loss_account_code','debit',carrying-proceeds,'credit',0)); END IF;
  expected:=expected||jsonb_build_array(jsonb_build_object('code',asset->>'asset_account_code','debit',0,'credit',cost));
  IF proceeds>carrying THEN expected:=expected||jsonb_build_array(jsonb_build_object('code',asset->>'gain_account_code','debit',0,'credit',proceeds-carrying)); END IF;
 END IF;
 IF p.kind<>'acquire' THEN
  request:=jsonb_build_object('asset_id',p.asset_id,'kind',p.kind,'period_id',v->>'period_id','posting_date',v->>'posting_date',
    'reason',v->>'reason','through_month',v->>'through_month','proceeds_minor',proceeds);
 END IF;
 IF v->'command_request' IS DISTINCT FROM request OR (v->>'amount_minor')::numeric<>amount OR (v->>'months_after')::integer<>after_months
 OR accumulated>cost-salvage OR (p.phase<2 AND EXISTS(SELECT 1 FROM reconforge.fixed_asset_plans q WHERE q.tenant_id=t AND q.asset_id=p.asset_id AND q.sequence>p.sequence)) THEN
  RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='fixed_asset_owner',MESSAGE='Asset command and cumulative entitlement differ'; END IF;
 SELECT * INTO native_journal FROM reconforge.finance_journals WHERE tenant_id=t AND id=e.journal_id;
 IF native_journal IS NULL OR native_journal.journal_code<>asset->>'journal_code' OR e.entry_number<>upper(p.id)
 OR e.source_type<>'Manual' OR e.external_reference<>'FA:'||p.asset_id||':'||p.kind OR e.period_id<>v->>'period_id'
 OR e.posting_date::text<>v->>'posting_date' OR e.description<>v->>'reason' OR e.preparer_actor_id<>v->>'preparer_actor_id'
 OR e.currency_code<>asset->>'currency_code' OR e.currency_precision<>(asset->>'currency_precision')::integer OR e.reverses_posting_id IS NOT NULL
 OR NOT EXISTS(SELECT 1 FROM reconforge.organizations o JOIN reconforge.legal_entities x ON x.tenant_id=o.tenant_id AND x.organization_id=o.id
 WHERE o.tenant_id=t AND o.id=a.organization_id AND x.id=a.legal_entity_id AND o.application_workspace_id=a.workspace_id
 AND e.organization_code=o.organization_code AND e.entity_code=x.entity_code AND x.currency_code=e.currency_code)
 OR NOT EXISTS(SELECT 1 FROM reconforge.identity_users u WHERE u.tenant_id=t AND u.id=e.preparer_actor_id) THEN
  RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='fixed_asset_owner',MESSAGE='Asset native journal, hierarchy and original entry differ'; END IF;
 SELECT jsonb_object_agg(key,value) INTO header FROM jsonb_each(to_jsonb(e)) WHERE key=ANY(ARRAY[
 'id','workspace_id','journal_id','period_id','entry_number','posting_date','description','external_reference','source_type','currency_code',
 'currency_precision','currency_rounding_policy','currency_registry_version','currency_registry_digest','preparer_actor_id','reverses_posting_id']);
 header:=header||jsonb_build_object('organization_id',a.organization_id,'legal_entity_id',a.legal_entity_id);
 SELECT jsonb_agg(jsonb_build_object('line_number',x.line_number,'account_id',x.account_id,'description',x.description,
 'debit_minor',x.debit_minor,'credit_minor',x.credit_minor,'dimensions',COALESCE((SELECT jsonb_object_agg(d.dimension_id,d.dimension_value_id)
 FROM reconforge.finance_entry_line_dimensions d WHERE d.tenant_id=t AND d.entry_line_id=x.id),'{}'::jsonb)) ORDER BY x.line_number)
 INTO lines FROM reconforge.finance_entry_lines x WHERE x.tenant_id=t AND x.entry_id=e.id;
 IF v->'snapshot' IS DISTINCT FROM jsonb_build_object('schema_version','finance-entry-review-v1','entry',header,'lines',lines)
 OR jsonb_array_length(lines)<>jsonb_array_length(expected) THEN
  RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='fixed_asset_owner',MESSAGE='Asset GL requires its complete retained snapshot'; END IF;
 idx:=0;
 FOR item IN SELECT value FROM jsonb_array_elements(expected) LOOP
  SELECT id INTO expected_id FROM reconforge.finance_accounts WHERE tenant_id=t AND chart_id=native_journal.chart_id
   AND workspace_id=a.workspace_id AND account_code=item->>'code';
  IF expected_id IS NULL OR lines->idx->>'account_id' IS DISTINCT FROM expected_id
   OR (lines->idx->>'debit_minor')::numeric IS DISTINCT FROM (item->>'debit')::numeric
   OR (lines->idx->>'credit_minor')::numeric IS DISTINCT FROM (item->>'credit')::numeric
   OR lines->idx->>'description' IS DISTINCT FROM v->>'reason' OR lines->idx->'dimensions'<>'{}'::jsonb THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='fixed_asset_owner',MESSAGE='Asset GL lines differ from the independent accounting equation'; END IF;
  idx:=idx+1;
 END LOOP;
 FOREACH field_name IN ARRAY ARRAY['asset','accumulated','expense','cash','gain','loss'] LOOP
  account_code:=asset->>(field_name||'_account_code');
  expected_kind:=CASE WHEN field_name IN ('expense','loss') THEN 'Expense' WHEN field_name='gain' THEN 'Income' ELSE 'Asset' END;
  SELECT fa.account_type,fa.id INTO account_kind,account_id FROM reconforge.finance_accounts fa
   WHERE fa.tenant_id=t AND fa.chart_id=native_journal.chart_id AND fa.workspace_id=a.workspace_id AND fa.account_code=account_code;
  IF account_kind IS DISTINCT FROM expected_kind OR account_id IS NULL THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='fixed_asset_owner',MESSAGE='Asset accounts require their retained financial classifications'; END IF;
 END LOOP;
 IF (SELECT count(DISTINCT asset->>x) FROM unnest(ARRAY['asset_account_code','accumulated_account_code','expense_account_code','cash_account_code','gain_account_code','loss_account_code']) x)<>6
 OR NOT reconforge.asset_event(t,i,p.audit_event_id,p.outbox_event_id,e.preparer_actor_id,'fixed_asset_prepared',jsonb_build_object('plan_digest',v->>'plan_digest')) THEN
  RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='fixed_asset_owner',MESSAGE='Asset preparation and policy evidence are incomplete'; END IF;
 IF p.phase=0 AND (e.status<>'Draft' OR r IS NOT NULL OR l IS NOT NULL) THEN
  RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='fixed_asset_owner',MESSAGE='Prepared asset phase differs from its native entry'; END IF;
 IF p.phase<2 AND NOT EXISTS(SELECT 1 FROM reconforge.fiscal_periods period WHERE period.tenant_id=t AND period.id=e.period_id
  AND period.status='Open' AND e.posting_date BETWEEN period.start_date AND period.end_date) THEN
  RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='fixed_asset_owner',MESSAGE='Pending asset accounting requires its open original period'; END IF;
 IF p.phase>=1 AND (r IS NULL OR r.reviewer_actor_id=e.preparer_actor_id OR e.validator_actor_id<>r.reviewer_actor_id
 OR e.validation_digest<>v->>'validation_digest' OR e.status<>'Validated'
 OR NOT reconforge.asset_event(t,i,r.audit_event_id,r.outbox_event_id,r.reviewer_actor_id,'fixed_asset_reviewed',jsonb_build_object('plan_digest',v->>'plan_digest'))) THEN
  RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='fixed_asset_owner',MESSAGE='Asset native entry requires its independent retained review'; END IF;
 IF p.phase=1 AND l IS NOT NULL THEN RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='fixed_asset_owner',MESSAGE='Reviewed asset has an unattached effect'; END IF;
 IF p.phase<2 AND EXISTS(SELECT 1 FROM reconforge.finance_posting_effects z WHERE z.tenant_id=t AND z.entry_id=p.entry_id) THEN
  RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='fixed_asset_owner',MESSAGE='An asset effect requires the complete source transition'; END IF;
 IF p.phase=2 THEN
  SELECT * INTO f FROM reconforge.finance_posting_effects WHERE tenant_id=t AND id=l.posting_effect_id;
  IF l IS NULL OR f IS NULL OR f.entry_id<>p.entry_id OR f.snapshot_json<>v->'snapshot' OR f.validation_digest<>v->>'validation_digest'
  OR f.posted_actor_id<>l.posted_actor_id OR l.posted_actor_id IN (e.preparer_actor_id,r.reviewer_actor_id)
  OR EXISTS(SELECT 1 FROM reconforge.finance_posting_effects z WHERE z.tenant_id=t AND z.reverses_effect_id=f.id)
  OR NOT reconforge.asset_event(t,i,l.audit_event_id,l.outbox_event_id,l.posted_actor_id,'fixed_asset_posted',
    jsonb_build_object('plan_digest',v->>'plan_digest','posting_effect_id',f.id)) THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='fixed_asset_owner',MESSAGE='Posted asset requires its exact native effect and three independent humans'; END IF;
 END IF;
 FOR c IN SELECT * FROM reconforge.fixed_asset_commands WHERE tenant_id=t AND plan_id=i LOOP
  IF (c.workspace_id,c.organization_id,c.legal_entity_id) IS DISTINCT FROM (p.workspace_id,p.organization_id,p.legal_entity_id)
  OR reconforge.irp_digest(c.request_json) IS DISTINCT FROM c.request_digest
  OR c.request_json IS DISTINCT FROM jsonb_build_object('operation',c.operation,'actor_id',c.actor_id,'request',
   CASE WHEN c.operation='prepare' THEN request ELSE jsonb_build_object('plan_id',i,'expected_plan_digest',v->>'plan_digest',
   'reason',CASE c.operation WHEN 'review' THEN r.reason ELSE l.reason END) END)
  OR c.actor_id IS DISTINCT FROM (CASE c.operation WHEN 'prepare' THEN e.preparer_actor_id WHEN 'review' THEN r.reviewer_actor_id ELSE l.posted_actor_id END)
  OR c.response_json IS DISTINCT FROM v||jsonb_build_object('phase',CASE c.operation WHEN 'prepare' THEN 0 WHEN 'review' THEN 1 ELSE 2 END,
   'status',CASE c.operation WHEN 'prepare' THEN 'Prepared' WHEN 'review' THEN 'Reviewed' ELSE 'Posted' END,
   'reviewer_actor_id',CASE WHEN c.operation='prepare' THEN NULL ELSE r.reviewer_actor_id END,
   'posting_effect_id',CASE WHEN c.operation='post' THEN l.posting_effect_id ELSE NULL END) THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='fixed_asset_owner',MESSAGE='Asset command requires its exact actor, request and acknowledgement'; END IF;
 END LOOP;
 IF (SELECT count(*) FROM reconforge.fixed_asset_commands WHERE tenant_id=t AND plan_id=i)<>p.phase+1 THEN
  RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='fixed_asset_owner',MESSAGE='Every retained asset phase requires its immutable command'; END IF;
END $fa$;
CREATE FUNCTION reconforge.asset_reverse_close() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $fa$
DECLARE changed JSONB;changes JSONB[];p RECORD;native_entry TEXT;native_number TEXT;owner_id TEXT;asset_id TEXT;
BEGIN
 IF TG_OP='INSERT' THEN changes:=ARRAY[to_jsonb(NEW)]; ELSIF TG_OP='DELETE' THEN changes:=ARRAY[to_jsonb(OLD)];
 ELSE changes:=ARRAY[to_jsonb(OLD),to_jsonb(NEW)]; END IF;
 FOREACH changed IN ARRAY changes LOOP
  native_entry:=NULL;native_number:=NULL;asset_id:=NULL;
  IF TG_TABLE_NAME IN ('domain_audit_events','outbox_events') THEN
   owner_id:=CASE WHEN TG_TABLE_NAME='domain_audit_events' THEN changed->>'object_id' ELSE changed->>'aggregate_id' END;
   IF upper(left(COALESCE(owner_id,''),4))<>'FA1-' THEN CONTINUE; END IF;
   PERFORM reconforge.asset_close(changed->>'tenant_id',owner_id);CONTINUE;
  END IF;
  IF TG_TABLE_NAME IN ('finance_accounts','finance_journals','fiscal_periods','legal_entities') THEN
   FOR p IN SELECT q.* FROM reconforge.fixed_asset_plans q JOIN reconforge.fixed_assets definition
    ON definition.tenant_id=q.tenant_id AND definition.id=q.asset_id JOIN reconforge.finance_entries entry
    ON entry.tenant_id=q.tenant_id AND entry.id=q.entry_id WHERE q.tenant_id=changed->>'tenant_id' AND
    ((TG_TABLE_NAME='finance_journals' AND entry.journal_id=changed->>'id')
     OR (TG_TABLE_NAME='fiscal_periods' AND entry.period_id=changed->>'id' AND q.phase<2)
     OR (TG_TABLE_NAME='legal_entities' AND q.legal_entity_id=changed->>'id')
     OR (TG_TABLE_NAME='finance_accounts' AND definition.workspace_id=changed->>'workspace_id'
      AND changed->>'account_code'=ANY(ARRAY[definition.payload->>'asset_account_code',definition.payload->>'accumulated_account_code',
       definition.payload->>'expense_account_code',definition.payload->>'cash_account_code',definition.payload->>'gain_account_code',definition.payload->>'loss_account_code']))) LOOP
    PERFORM reconforge.asset_close(p.tenant_id,p.id);
   END LOOP;
   CONTINUE;
  END IF;
  IF TG_TABLE_NAME='fixed_assets' THEN
   asset_id:=changed->>'id';
   IF NOT EXISTS(SELECT 1 FROM reconforge.fixed_asset_plans q WHERE q.tenant_id=changed->>'tenant_id' AND q.asset_id=asset_id AND q.sequence=0 AND q.kind='acquire') THEN
    RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='fixed_asset_owner',MESSAGE='Asset registration requires its atomic native acquisition plan'; END IF;
  ELSIF TG_TABLE_NAME='fixed_asset_plans' THEN asset_id:=changed->>'asset_id';
  END IF;
  IF TG_TABLE_NAME IN ('finance_entries','finance_entry_lines','finance_entry_line_dimensions','finance_posting_effects') THEN
   native_entry:=CASE WHEN TG_TABLE_NAME='finance_entries' THEN changed->>'id' ELSE changed->>'entry_id' END;
   IF TG_TABLE_NAME='finance_entry_line_dimensions' THEN SELECT entry_id INTO native_entry FROM reconforge.finance_entry_lines
    WHERE tenant_id=changed->>'tenant_id' AND id=changed->>'entry_line_id'; END IF;
   IF TG_TABLE_NAME='finance_posting_effects' AND changed->>'reverses_effect_id' IS NOT NULL THEN SELECT entry_id INTO native_entry
    FROM reconforge.finance_posting_effects WHERE tenant_id=changed->>'tenant_id' AND id=changed->>'reverses_effect_id'; END IF;
   native_number:=CASE WHEN TG_TABLE_NAME='finance_entries' THEN changed->>'entry_number' ELSE NULL END;
   IF native_number IS NULL THEN SELECT entry_number INTO native_number FROM reconforge.finance_entries
    WHERE tenant_id=changed->>'tenant_id' AND id=native_entry; END IF;
   IF upper(left(COALESCE(native_number,''),4))<>'FA1-' AND upper(left(COALESCE(native_entry,''),4))<>'FA1-' THEN CONTINUE; END IF;
   IF NOT EXISTS(SELECT 1 FROM reconforge.fixed_asset_plans q WHERE q.tenant_id=changed->>'tenant_id' AND q.entry_id=native_entry) THEN
    RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='fixed_asset_owner',MESSAGE='Reserved FA1 native entry requires its source'; END IF;
  END IF;
  FOR p IN SELECT q.* FROM reconforge.fixed_asset_plans q WHERE q.tenant_id=changed->>'tenant_id' AND
   (q.id=changed->>'plan_id' OR q.id=changed->>'id' OR q.entry_id=native_entry OR q.asset_id=asset_id) LOOP
   PERFORM reconforge.asset_close(p.tenant_id,p.id);
  END LOOP;
 END LOOP;RETURN NULL;
END $fa$;
DO $fa$ DECLARE n TEXT; BEGIN
 FOREACH n IN ARRAY ARRAY['fixed_assets','fixed_asset_plans','fixed_asset_reviews','fixed_asset_links','fixed_asset_commands'] LOOP
  EXECUTE format('ALTER TABLE reconforge.%I ENABLE ROW LEVEL SECURITY',n);
  EXECUTE format('ALTER TABLE reconforge.%I FORCE ROW LEVEL SECURITY',n);
  IF n IN ('fixed_assets','fixed_asset_plans','fixed_asset_commands') THEN
   EXECUTE format('CREATE POLICY scope ON reconforge.%I USING(reconforge.irp_scope(tenant_id,workspace_id,organization_id,legal_entity_id)) WITH CHECK(reconforge.irp_scope(tenant_id,workspace_id,organization_id,legal_entity_id))',n);
  ELSE
   EXECUTE format('CREATE POLICY scope ON reconforge.%I USING(EXISTS(SELECT 1 FROM reconforge.fixed_asset_plans p WHERE p.tenant_id=%I.tenant_id AND p.id=%I.plan_id)) WITH CHECK(EXISTS(SELECT 1 FROM reconforge.fixed_asset_plans p WHERE p.tenant_id=%I.tenant_id AND p.id=%I.plan_id))',n,n,n,n,n);
  END IF;
  EXECUTE format('CREATE TRIGGER immutable BEFORE UPDATE OR DELETE ON reconforge.%I FOR EACH ROW EXECUTE FUNCTION reconforge.asset_protect()',n);
 END LOOP;
 FOREACH n IN ARRAY ARRAY['fixed_assets','fixed_asset_plans','fixed_asset_reviews','fixed_asset_links','fixed_asset_commands',
 'finance_entries','finance_entry_lines','finance_entry_line_dimensions','finance_posting_effects','domain_audit_events','outbox_events',
 'finance_accounts','finance_journals','fiscal_periods','legal_entities'] LOOP
  EXECUTE format('CREATE CONSTRAINT TRIGGER fixed_asset_owner_closure AFTER INSERT OR UPDATE OR DELETE ON reconforge.%I DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION reconforge.asset_reverse_close()',n);
 END LOOP;
END $fa$;
"""

DOWNGRADE_SQL = r"""
DO $fa$ BEGIN IF EXISTS(SELECT 1 FROM reconforge.fixed_assets) THEN
 RAISE EXCEPTION 'Fixed asset downgrade refuses to discard retained financial evidence'; END IF; END $fa$;
DO $fa$ DECLARE n TEXT; BEGIN
 FOREACH n IN ARRAY ARRAY['fixed_assets','fixed_asset_plans','fixed_asset_reviews','fixed_asset_links','fixed_asset_commands',
 'finance_entries','finance_entry_lines','finance_entry_line_dimensions','finance_posting_effects','domain_audit_events','outbox_events',
 'finance_accounts','finance_journals','fiscal_periods','legal_entities'] LOOP
  EXECUTE format('DROP TRIGGER fixed_asset_owner_closure ON reconforge.%I',n);
 END LOOP;
END $fa$;
DROP TABLE reconforge.fixed_asset_commands,reconforge.fixed_asset_links,reconforge.fixed_asset_reviews,reconforge.fixed_asset_plans,reconforge.fixed_assets;
DROP FUNCTION reconforge.asset_reverse_close();DROP FUNCTION reconforge.asset_protect();
DROP FUNCTION reconforge.asset_close(TEXT,TEXT);DROP FUNCTION reconforge.asset_event(TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,JSONB);
DROP FUNCTION reconforge.asset_command_actor();
"""
