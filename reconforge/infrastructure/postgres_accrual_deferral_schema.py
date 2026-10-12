"""Independent SQL closure for AD1; shared ownership directory stays in Core.

Revision141 installs these owned tables before the root-owned additive AD1
financial source directory fragment. Downgrade refuses populated history.
"""

UPGRADE_SQL = r"""
CREATE TABLE reconforge.accrual_deferral_sources(
 tenant_id TEXT NOT NULL,id TEXT NOT NULL,workspace_id TEXT NOT NULL,organization_id TEXT NOT NULL,legal_entity_id TEXT NOT NULL,
 reference TEXT NOT NULL CHECK(reconforge.irp_text(reference,160)),payload JSONB NOT NULL CHECK(jsonb_typeof(payload)='object' AND octet_length(payload::text)<=1048576),
 PRIMARY KEY(tenant_id,id),UNIQUE(tenant_id,workspace_id,organization_id,legal_entity_id,reference),
 FOREIGN KEY(tenant_id,workspace_id) REFERENCES reconforge.domain_workspaces(tenant_id,id),
 FOREIGN KEY(tenant_id,organization_id) REFERENCES reconforge.organizations(tenant_id,id),
 FOREIGN KEY(tenant_id,legal_entity_id) REFERENCES reconforge.legal_entities(tenant_id,id)
);
CREATE TABLE reconforge.accrual_deferral_plans(
 tenant_id TEXT NOT NULL,id TEXT NOT NULL,source_id TEXT NOT NULL,kind TEXT NOT NULL CHECK(kind IN('source','release','accrue','reverse','cancel')),
 phase INTEGER NOT NULL CHECK(phase BETWEEN 0 AND 2),payload JSONB NOT NULL CHECK(jsonb_typeof(payload)='object' AND octet_length(payload::text)<=1048576),
 PRIMARY KEY(tenant_id,id),FOREIGN KEY(tenant_id,source_id) REFERENCES reconforge.accrual_deferral_sources(tenant_id,id)
);
ALTER TABLE reconforge.fiscal_periods ADD CONSTRAINT ad1_fiscal_identity
 UNIQUE(tenant_id,id,start_date,end_date,fiscal_year,period_number,application_workspace_id);
ALTER TABLE reconforge.finance_accounts ADD CONSTRAINT ad1_native_account_identity
 UNIQUE(tenant_id,id,workspace_id,chart_id,account_code,account_type);
CREATE TABLE reconforge.accrual_deferral_account_pins(
 tenant_id TEXT NOT NULL,source_id TEXT NOT NULL,role TEXT NOT NULL CHECK(role IN('prepaid','expense','accrued_liability','cash')),
 account_id TEXT NOT NULL,workspace_id TEXT NOT NULL,chart_id TEXT NOT NULL,account_code TEXT NOT NULL,account_type TEXT NOT NULL,
 PRIMARY KEY(tenant_id,source_id,role),UNIQUE(tenant_id,source_id,account_id),
 FOREIGN KEY(tenant_id,source_id) REFERENCES reconforge.accrual_deferral_sources(tenant_id,id),
 FOREIGN KEY(tenant_id,account_id,workspace_id,chart_id,account_code,account_type)
  REFERENCES reconforge.finance_accounts(tenant_id,id,workspace_id,chart_id,account_code,account_type)
);
CREATE TABLE reconforge.accrual_deferral_period_pins(
 tenant_id TEXT NOT NULL,source_id TEXT NOT NULL,period_id TEXT NOT NULL,start_date DATE NOT NULL,end_date DATE NOT NULL,
 fiscal_year INTEGER NOT NULL,period_number INTEGER NOT NULL,application_workspace_id TEXT NOT NULL,
 PRIMARY KEY(tenant_id,source_id,period_id),FOREIGN KEY(tenant_id,source_id) REFERENCES reconforge.accrual_deferral_sources(tenant_id,id),
 FOREIGN KEY(tenant_id,period_id,start_date,end_date,fiscal_year,period_number,application_workspace_id)
  REFERENCES reconforge.fiscal_periods(tenant_id,id,start_date,end_date,fiscal_year,period_number,application_workspace_id)
);
CREATE UNIQUE INDEX accrual_deferral_initial ON reconforge.accrual_deferral_plans(tenant_id,source_id) WHERE kind='source';
CREATE UNIQUE INDEX accrual_deferral_cancel ON reconforge.accrual_deferral_plans(tenant_id,source_id) WHERE kind='cancel';
CREATE UNIQUE INDEX accrual_deferral_pending ON reconforge.accrual_deferral_plans(tenant_id,source_id) WHERE phase<2 AND kind<>'cancel';
CREATE TABLE reconforge.accrual_deferral_phase_events(
 tenant_id TEXT NOT NULL,plan_id TEXT NOT NULL,operation TEXT NOT NULL CHECK(operation IN('prepare','review','post')),
 actor_id TEXT NOT NULL,reason TEXT NOT NULL CHECK(reconforge.irp_text(reason,500)),posting_effect_id TEXT,audit_event_id TEXT NOT NULL,outbox_event_id TEXT NOT NULL,
 PRIMARY KEY(tenant_id,plan_id,operation),UNIQUE(tenant_id,posting_effect_id),
 FOREIGN KEY(tenant_id,plan_id) REFERENCES reconforge.accrual_deferral_plans(tenant_id,id),
 FOREIGN KEY(tenant_id,actor_id) REFERENCES reconforge.identity_users(tenant_id,id),
 FOREIGN KEY(tenant_id,posting_effect_id) REFERENCES reconforge.finance_posting_effects(tenant_id,id),
 CHECK(operation='post' OR posting_effect_id IS NULL)
);
CREATE TABLE reconforge.accrual_deferral_claim_events(
 tenant_id TEXT NOT NULL,source_id TEXT NOT NULL,tranche_id TEXT NOT NULL,sequence INTEGER NOT NULL CHECK(sequence BETWEEN 1 AND 16),
 plan_id TEXT NOT NULL,operation TEXT NOT NULL CHECK(operation IN('Initialize','Claim','Consume','Reverse','Cancel')),
 state TEXT NOT NULL CHECK(state IN('Available','Reserved','Consumed')),
 PRIMARY KEY(tenant_id,source_id,tranche_id,sequence),UNIQUE(tenant_id,source_id,tranche_id,plan_id,operation),
 FOREIGN KEY(tenant_id,source_id) REFERENCES reconforge.accrual_deferral_sources(tenant_id,id),
 FOREIGN KEY(tenant_id,plan_id) REFERENCES reconforge.accrual_deferral_plans(tenant_id,id)
);
CREATE TABLE reconforge.accrual_deferral_claim_heads(
 tenant_id TEXT NOT NULL,source_id TEXT NOT NULL,tranche_id TEXT NOT NULL,sequence INTEGER NOT NULL CHECK(sequence BETWEEN 1 AND 16),
 plan_id TEXT NOT NULL,state TEXT NOT NULL CHECK(state IN('Available','Reserved','Consumed')),
 PRIMARY KEY(tenant_id,source_id,tranche_id),FOREIGN KEY(tenant_id,source_id) REFERENCES reconforge.accrual_deferral_sources(tenant_id,id),
 FOREIGN KEY(tenant_id,source_id,tranche_id,sequence) REFERENCES reconforge.accrual_deferral_claim_events(tenant_id,source_id,tranche_id,sequence)
 DEFERRABLE INITIALLY DEFERRED
);
CREATE TABLE reconforge.accrual_deferral_original_claims(
 tenant_id TEXT NOT NULL,id TEXT NOT NULL,source_id TEXT NOT NULL,workspace_id TEXT NOT NULL,organization_id TEXT NOT NULL,legal_entity_id TEXT NOT NULL,
 effect_id TEXT NOT NULL,state TEXT NOT NULL CHECK(state IN('Reserved','Consumed','Released')),
 PRIMARY KEY(tenant_id,id),UNIQUE(tenant_id,source_id),FOREIGN KEY(tenant_id,source_id) REFERENCES reconforge.accrual_deferral_sources(tenant_id,id),
 FOREIGN KEY(tenant_id,effect_id) REFERENCES reconforge.finance_posting_effects(tenant_id,id)
);
CREATE TABLE reconforge.accrual_deferral_original_releases(
 tenant_id TEXT NOT NULL,id TEXT NOT NULL,claim_id TEXT NOT NULL,source_id TEXT NOT NULL,workspace_id TEXT NOT NULL,organization_id TEXT NOT NULL,legal_entity_id TEXT NOT NULL,
 cancellation_plan_id TEXT NOT NULL,PRIMARY KEY(tenant_id,id),UNIQUE(tenant_id,claim_id),
 FOREIGN KEY(tenant_id,claim_id) REFERENCES reconforge.accrual_deferral_original_claims(tenant_id,id),
 FOREIGN KEY(tenant_id,source_id) REFERENCES reconforge.accrual_deferral_sources(tenant_id,id),
 FOREIGN KEY(tenant_id,cancellation_plan_id) REFERENCES reconforge.accrual_deferral_plans(tenant_id,id)
);
CREATE TABLE reconforge.accrual_deferral_commands(
 tenant_id TEXT NOT NULL,workspace_id TEXT NOT NULL,organization_id TEXT NOT NULL,legal_entity_id TEXT NOT NULL,plan_id TEXT NOT NULL,
 operation TEXT NOT NULL CHECK(operation IN('prepare','review','post')),command_id TEXT NOT NULL CHECK(reconforge.irp_text(command_id,140)),actor_id TEXT NOT NULL,
 request_digest TEXT NOT NULL CHECK(request_digest~'^[a-f0-9]{64}$'),request_json JSONB NOT NULL,response_json JSONB NOT NULL,
 PRIMARY KEY(tenant_id,workspace_id,command_id),UNIQUE(tenant_id,plan_id,operation),
 FOREIGN KEY(tenant_id,plan_id) REFERENCES reconforge.accrual_deferral_plans(tenant_id,id),FOREIGN KEY(tenant_id,actor_id) REFERENCES reconforge.identity_users(tenant_id,id)
);
CREATE FUNCTION reconforge.ad1_assert(ok BOOLEAN,message TEXT) RETURNS VOID LANGUAGE plpgsql SET search_path=pg_catalog AS $ad1$
BEGIN IF ok IS DISTINCT FROM TRUE THEN RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='accrual_deferral_owner',MESSAGE=message;END IF;END $ad1$;
CREATE FUNCTION reconforge.ad1_protect() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $ad1$
BEGIN
 IF TG_OP='UPDATE' THEN
  IF TG_TABLE_NAME='accrual_deferral_plans' THEN
   IF NEW.phase=OLD.phase+1 AND to_jsonb(NEW)-'phase'=to_jsonb(OLD)-'phase' THEN RETURN NEW;END IF;
  ELSIF TG_TABLE_NAME='accrual_deferral_claim_heads' THEN
   IF NEW.sequence=OLD.sequence+1 AND(NEW.tenant_id,NEW.source_id,NEW.tranche_id)=(OLD.tenant_id,OLD.source_id,OLD.tranche_id) THEN RETURN NEW;END IF;
  ELSIF TG_TABLE_NAME='accrual_deferral_original_claims' THEN
   IF OLD.state='Reserved' AND NEW.state IN('Consumed','Released') AND to_jsonb(NEW)-'state'=to_jsonb(OLD)-'state' THEN RETURN NEW;END IF;
  END IF;
 END IF;
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='accrual_deferral_owner',MESSAGE='Approved voucher source membership claims and phase history are immutable';
END $ad1$;
CREATE FUNCTION reconforge.ad1_line(account TEXT,debit NUMERIC,credit NUMERIC,dimensions JSONB) RETURNS JSONB
 LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog AS $ad1$
BEGIN
 PERFORM reconforge.ad1_assert(account~'^[A-Z0-9][A-Z0-9_.:/-]{0,63}$' AND debit IS NOT NULL AND credit IS NOT NULL
  AND debit=trunc(debit) AND credit=trunc(credit) AND debit BETWEEN 0 AND 9000000000000000000 AND credit BETWEEN 0 AND 9000000000000000000
  AND (debit>0)<>(credit>0) AND jsonb_typeof(dimensions)='object','Native AD1 lines require exact bounded money one side and retained dimensions');
 RETURN jsonb_build_object('account_code',account,'debit_minor',debit,'credit_minor',credit,'dimensions',dimensions);
END $ad1$;
CREATE FUNCTION reconforge.ad1_allocate(q JSONB) RETURNS JSONB LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog AS $ad1$
DECLARE item JSONB;amount NUMERIC;total NUMERIC;residual INTEGER;result JSONB:='[]';
BEGIN
 PERFORM reconforge.ad1_assert(reconforge.fx_minor(q->'amount_minor') AND(q->>'amount_minor')::numeric>0
  AND jsonb_typeof(q->'tranches')='array' AND jsonb_array_length(q->'tranches') BETWEEN 1 AND 36,'Schedule needs exact bounded source money and one to36 tranches');
 amount:=(q->>'amount_minor')::numeric;
 FOR item IN SELECT value FROM jsonb_array_elements(q->'tranches') LOOP
  PERFORM reconforge.ad1_assert(reconforge.fx_object(item,CASE WHEN q->>'mode'='expense_accrual'
   THEN ARRAY['id','period_id','posting_date','weight','amount_minor','reversal_period_id','reversal_date']
   ELSE ARRAY['id','period_id','posting_date','weight','amount_minor'] END)
   AND reconforge.irp_text(item->>'id',40) AND reconforge.irp_text(item->>'period_id',160)
   AND reconforge.fx_minor(item->'weight') AND(item->>'weight')::numeric>0 AND reconforge.fx_minor(item->'amount_minor')
   AND(item->>'posting_date')::date::text=item->>'posting_date' AND item->>'posting_date'>=q->>'posting_date',
   'Retained tranche identities dates and weights must be closed exact fields');
  IF q->>'mode'='expense_accrual' THEN
   PERFORM reconforge.ad1_assert(reconforge.irp_text(item->>'reversal_period_id',160) AND item->>'reversal_period_id'<>item->>'period_id'
    AND(item->>'reversal_date')::date::text=item->>'reversal_date' AND item->>'reversal_date'>item->>'posting_date',
    'Accrual retains its explicit next-period inverse date');
  END IF;
 END LOOP;
 PERFORM reconforge.ad1_assert((SELECT count(DISTINCT x->>'id') FROM jsonb_array_elements(q->'tranches')x)=jsonb_array_length(q->'tranches')
  AND(SELECT count(DISTINCT x->>'period_id') FROM jsonb_array_elements(q->'tranches')x)=jsonb_array_length(q->'tranches'),
  'Tranches and source fiscal periods must be distinct');
 SELECT sum((value->>'weight')::numeric) INTO total FROM jsonb_array_elements(q->'tranches');
 SELECT(amount-sum(div(amount*(value->>'weight')::numeric,total)))::integer INTO residual FROM jsonb_array_elements(q->'tranches');
 FOR item IN WITH weighted AS(SELECT value,div(amount*(value->>'weight')::numeric,total) AS allocated,
   mod(amount*(value->>'weight')::numeric,total) AS remainder FROM jsonb_array_elements(q->'tranches')),
  ranked AS(SELECT value,allocated,row_number() OVER(ORDER BY remainder DESC,value->>'id') AS rank FROM weighted)
  SELECT value||jsonb_build_object('amount_minor',allocated+CASE WHEN rank<=residual THEN 1 ELSE 0 END)
   FROM ranked ORDER BY value->>'posting_date',value->>'id' LOOP
  PERFORM reconforge.ad1_assert((item->>'amount_minor')::numeric>0,'Schedule rejects zero-value native tranches');
  result:=result||jsonb_build_array(item);
 END LOOP;
 RETURN result;
END $ad1$;
CREATE FUNCTION reconforge.ad1_source_close(t TEXT,i TEXT) RETURNS VOID LANGUAGE plpgsql SET search_path=pg_catalog AS $ad1$
DECLARE s RECORD;original RECORD;entry RECORD;review JSONB;claim RECORD;released RECORD;cfg JSONB;a JSONB;policy JSONB;item JSONB;roles JSONB;
 expected JSONB;membership JSONB:='{}';rows JSONB:='[]';dimensions JSONB:='{}';cash_dimensions JSONB;amount NUMERIC;role TEXT;kind TEXT;initial RECORD;
BEGIN
 SELECT* INTO s FROM reconforge.accrual_deferral_sources WHERE tenant_id=t AND id=$2;
 PERFORM reconforge.ad1_assert(s.id IS NOT NULL,'Every source plan must retain its original voucher source');
 a:=s.payload;cfg:=a->'request';policy:=a->'policy';amount:=(cfg->>'amount_minor')::numeric;kind:=cfg->>'mode';
 PERFORM reconforge.ad1_assert(reconforge.fx_object(a,ARRAY['schema_version','id','request','policy','equation','native_accounts','native_periods','preparer_actor_id','source_digest'])
  AND a->>'schema_version'='accrual-deferral-source-v1' AND a->>'id'=s.id AND s.id~'^AD1S-[a-f0-9]{32}$'
  AND a->>'source_digest'=reconforge.irp_digest(a-'source_digest')
  AND reconforge.fx_object(cfg,ARRAY['schema_version','mode','workspace_id','organization_id','legal_entity_id','reference','period_id','reason','organization_code',
   'entity_code','currency_code','journal_code','posting_date','amount_minor','accounts','tranches','allocation_policy','original_effect_id'])
  AND cfg->>'schema_version'='accrual-deferral-source-v1' AND kind IN('new_prepaid_voucher','attach_paid_expense','attach_prepaid_voucher','expense_accrual')
  AND(cfg->>'workspace_id',cfg->>'organization_id',cfg->>'legal_entity_id',cfg->>'reference')=(s.workspace_id,s.organization_id,s.legal_entity_id,s.reference)
  AND cfg->>'allocation_policy'='native-hamilton-stable-id-v1' AND reconforge.irp_text(cfg->>'reason',500)
  AND(cfg->>'posting_date')::date::text=cfg->>'posting_date' AND cfg->'tranches'=reconforge.ad1_allocate(cfg)
  AND reconforge.fx_policy(t,policy) AND policy->>'currency_code'=cfg->>'currency_code'
  AND EXISTS(SELECT 1 FROM reconforge.currency_registry_bindings b WHERE b.tenant_id=t AND b.workspace_id=s.workspace_id
   AND(b.registry_version,b.registry_digest)=(policy->>'currency_registry_version',policy->>'currency_registry_digest')),
  'Original source schema scope policy allocation and digest cannot diverge');
 PERFORM reconforge.ad1_assert(EXISTS(SELECT 1 FROM reconforge.legal_entities e JOIN reconforge.organizations o ON o.tenant_id=e.tenant_id AND o.id=e.organization_id
  WHERE e.tenant_id=t AND e.id=s.legal_entity_id AND e.organization_id=s.organization_id AND o.application_workspace_id=s.workspace_id
   AND(e.entity_code,e.currency_code,o.organization_code)=(cfg->>'entity_code',cfg->>'currency_code',cfg->>'organization_code')),
  'Source functional currency and native legal hierarchy must retain their original identities');
 PERFORM reconforge.ad1_assert(reconforge.fx_object(cfg->'accounts',ARRAY['prepaid','expense','accrued_liability','cash'])
  AND(SELECT count(DISTINCT value) FROM jsonb_each_text(cfg->'accounts'))=4
  AND reconforge.fx_object(a->'native_accounts',ARRAY['prepaid','expense','accrued_liability','cash']),
  'Four distinct explicit native account roles are required');
 FOR role,item IN SELECT key,value FROM jsonb_each(a->'native_accounts') LOOP
  PERFORM reconforge.ad1_assert(reconforge.fx_object(item,ARRAY['id','account_code','account_type','chart_id'])
   AND item->>'account_code'=cfg->'accounts'->>role AND item->>'account_type'=CASE role WHEN'expense' THEN'Expense' WHEN'accrued_liability' THEN'Liability' ELSE'Asset' END
   AND EXISTS(SELECT 1 FROM reconforge.finance_accounts ac JOIN reconforge.finance_journals j ON j.tenant_id=ac.tenant_id AND j.chart_id=ac.chart_id
    WHERE ac.tenant_id=t AND ac.id=item->>'id' AND ac.workspace_id=s.workspace_id AND ac.account_code=item->>'account_code'
     AND ac.account_type=item->>'account_type' AND ac.chart_id=item->>'chart_id' AND j.workspace_id=s.workspace_id
     AND(j.organization_code,j.journal_code,j.currency_code)=(cfg->>'organization_code',cfg->>'journal_code',cfg->>'currency_code')),
   'Frozen source-used native account identity chart role and journal cannot be forged');
 END LOOP;
 PERFORM reconforge.ad1_assert((SELECT count(*) FROM reconforge.accrual_deferral_account_pins pin WHERE pin.tenant_id=t AND pin.source_id=s.id)=4
  AND NOT EXISTS(SELECT 1 FROM reconforge.accrual_deferral_account_pins pin WHERE pin.tenant_id=t AND pin.source_id=s.id
   AND(a->'native_accounts'->pin.role) IS DISTINCT FROM jsonb_build_object('id',pin.account_id,'account_code',pin.account_code,
    'account_type',pin.account_type,'chart_id',pin.chart_id))
  AND NOT EXISTS(SELECT 1 FROM reconforge.accrual_deferral_account_pins pin WHERE pin.tenant_id=t AND pin.source_id=s.id AND pin.workspace_id<>s.workspace_id),
  'Four original native account roles retain exact structural identities across hidden entity sources');
 FOR item IN SELECT value FROM jsonb_array_elements(cfg->'tranches') LOOP
  PERFORM reconforge.ad1_assert(EXISTS(SELECT 1 FROM reconforge.fiscal_periods p WHERE p.tenant_id=t AND p.id=item->>'period_id'
   AND p.application_workspace_id=s.workspace_id AND(item->>'posting_date')::date BETWEEN p.start_date AND p.end_date),
   'Each retained tranche must belong to its exact native fiscal period');
  IF kind='expense_accrual' THEN PERFORM reconforge.ad1_assert(EXISTS(SELECT 1 FROM reconforge.fiscal_periods p WHERE p.tenant_id=t
   AND p.id=item->>'reversal_period_id' AND p.application_workspace_id=s.workspace_id AND(item->>'reversal_date')::date BETWEEN p.start_date AND p.end_date),
   'Each accrual inverse must belong to its explicit retained next fiscal period');END IF;
 END LOOP;
 PERFORM reconforge.ad1_assert((SELECT array_agg(key ORDER BY key) FROM jsonb_object_keys(a->'native_periods')key)
  =(SELECT array_agg(DISTINCT period ORDER BY period) FROM(SELECT cfg->>'period_id' AS period
    UNION ALL SELECT value->>'period_id' FROM jsonb_array_elements(cfg->'tranches')
    UNION ALL SELECT value->>'reversal_period_id' FROM jsonb_array_elements(cfg->'tranches') WHERE value ? 'reversal_period_id')x),
  'The frozen native calendar includes every original source tranche and next-period inverse');
 FOR role,item IN SELECT key,value FROM jsonb_each(a->'native_periods') LOOP
  PERFORM reconforge.ad1_assert(reconforge.fx_object(item,ARRAY['id','start_date','end_date','fiscal_year','period_number','application_workspace_id'])
   AND item->>'id'=role AND EXISTS(SELECT 1 FROM reconforge.fiscal_periods p WHERE p.tenant_id=t AND p.id=role
    AND jsonb_build_object('id',p.id,'start_date',p.start_date::text,'end_date',p.end_date::text,'fiscal_year',p.fiscal_year,
     'period_number',p.period_number,'application_workspace_id',p.application_workspace_id)=item),
   'Original fiscal calendar identity dates numbering and workspace cannot be replaced');
 END LOOP;
 PERFORM reconforge.ad1_assert((SELECT count(*) FROM reconforge.accrual_deferral_period_pins pin WHERE pin.tenant_id=t AND pin.source_id=s.id)
  =(SELECT count(DISTINCT id) FROM(SELECT key AS id FROM jsonb_object_keys(a->'native_periods')key
   UNION ALL SELECT p.payload->>'period_id' FROM reconforge.accrual_deferral_plans p WHERE p.tenant_id=t AND p.source_id=s.id)x)
  AND NOT EXISTS(SELECT 1 FROM reconforge.accrual_deferral_period_pins pin WHERE pin.tenant_id=t AND pin.source_id=s.id
   AND NOT(a->'native_periods' ? pin.period_id) AND NOT EXISTS(SELECT 1 FROM reconforge.accrual_deferral_plans p
    WHERE p.tenant_id=t AND p.source_id=s.id AND p.payload->>'period_id'=pin.period_id)),
  'The exact structural calendar pin set cannot omit or invent original plan periods');
 SELECT* INTO claim FROM reconforge.accrual_deferral_original_claims c WHERE c.tenant_id=t AND c.source_id=s.id;
 SELECT* INTO initial FROM reconforge.accrual_deferral_plans p WHERE p.tenant_id=t AND p.source_id=s.id AND p.kind='source';
 PERFORM reconforge.ad1_assert(initial.id IS NOT NULL AND(SELECT count(*) FROM reconforge.accrual_deferral_plans WHERE tenant_id=t AND source_id=s.id)<=160,
  'A bounded schedule retains exactly its original voucher approval plan');
 IF kind IN('attach_paid_expense','attach_prepaid_voucher') THEN
  SELECT* INTO original FROM reconforge.finance_posting_effects WHERE tenant_id=t AND id=cfg->>'original_effect_id';
  SELECT* INTO entry FROM reconforge.finance_entries WHERE tenant_id=t AND id=original.entry_id;
  SELECT* INTO released FROM reconforge.accrual_deferral_original_releases WHERE tenant_id=t AND claim_id=claim.id;
  PERFORM reconforge.ad1_assert(claim.id IS NOT NULL AND claim.effect_id=original.id AND claim.source_id=s.id
   AND(claim.workspace_id,claim.organization_id,claim.legal_entity_id)=(s.workspace_id,s.organization_id,s.legal_entity_id)
   AND original.source_kind='Manual' AND original.reverses_effect_id IS NULL AND entry.source_type='Manual' AND entry.reverses_posting_id IS NULL
   AND entry.status='Validated' AND entry.posting_date<=cfg->>'posting_date'
   AND upper(entry.entry_number)!~'^(IC1-|IC2[SRE]?-|FX1-|ME[12]C?-|HC1P?-|OPS1-|OB1-|FI1-|CA1-|LC1-|FA1-|CRF?1-|SR1-|AD1R?-)'
   AND upper(entry.id)!~'^(IC1-|IC2[SRE]?-|FX1-|ME[12]C?-|HC1P?-|OPS1-|OB1-|FI1-|CA1-|LC1-|FA1-|CRF?1-|SR1-|AD1R?-)'
   AND(original.workspace_id,original.organization_id,original.legal_entity_id)=(s.workspace_id,s.organization_id,s.legal_entity_id)
   AND entry.validation_digest=original.validation_digest AND original.validation_digest=reconforge.irp_digest(original.snapshot_json)
   AND entry.validation_contract_version='finance-entry-review-v1'
   AND(SELECT count(DISTINCT actor) FROM unnest(ARRAY[entry.preparer_actor_id,entry.validator_actor_id,original.posted_actor_id])actor)=3
   AND entry.preparer_actor_id IS NOT NULL AND entry.validator_actor_id IS NOT NULL
   AND NOT EXISTS(SELECT 1 FROM reconforge.finance_posting_effects r WHERE r.tenant_id=t AND r.reverses_effect_id=original.id AND claim.state<>'Released'),
   'Attachment preserves an exact eligible three-human ordinary paid original voucher and exclusive active ownership');
  PERFORM reconforge.ad1_assert((original.currency_code,original.currency_precision::text,original.currency_rounding_policy,original.currency_registry_version,original.currency_registry_digest)
   =(policy->>'currency_code',policy->>'currency_precision',policy->>'currency_rounding_policy',policy->>'currency_registry_version',policy->>'currency_registry_digest'),
   'Attached original effect retains its exact functional currency policy');
  roles:=a->'native_accounts';
  PERFORM reconforge.ad1_assert(jsonb_array_length(original.snapshot_json->'lines')=2
   AND(SELECT count(*) FROM jsonb_array_elements(original.snapshot_json->'lines')x WHERE x->>'account_id'=roles->CASE kind WHEN'attach_paid_expense' THEN'expense' ELSE'prepaid' END->>'id'
    AND(x->>'debit_minor')::numeric=amount AND(x->>'credit_minor')::numeric=0)=1
   AND(SELECT count(*) FROM jsonb_array_elements(original.snapshot_json->'lines')x WHERE x->>'account_id'=roles->'cash'->>'id'
    AND(x->>'credit_minor')::numeric=amount AND(x->>'debit_minor')::numeric=0)=1,
   'Attached original native amounts cannot be replaced with an unsupported complex or other-source voucher');
  SELECT x->'dimensions' INTO dimensions FROM jsonb_array_elements(original.snapshot_json->'lines')x
   WHERE x->>'account_id'=roles->CASE kind WHEN'attach_paid_expense' THEN'expense' ELSE'prepaid' END->>'id';
  SELECT x->'dimensions' INTO cash_dimensions FROM jsonb_array_elements(original.snapshot_json->'lines')x WHERE x->>'account_id'=roles->'cash'->>'id';
  review:=jsonb_build_object('id',entry.id,'status',entry.status,'preparer_actor_id',entry.preparer_actor_id,'validator_actor_id',entry.validator_actor_id,
   'validation_digest',entry.validation_digest,'validation_contract_version',entry.validation_contract_version);
  membership:=jsonb_build_object('original_effect_id',original.id,'original_entry_id',original.entry_id,'original_validation_digest',original.validation_digest,
   'original_snapshot',original.snapshot_json,'original_actor_ids',jsonb_build_array(entry.preparer_actor_id,entry.validator_actor_id,original.posted_actor_id),
   'original_review',review,'basis_dimensions',dimensions,'original_cash_dimensions',cash_dimensions);
  PERFORM reconforge.ad1_assert(EXISTS(SELECT 1 FROM reconforge.domain_audit_events d JOIN reconforge.outbox_events o ON o.tenant_id=d.tenant_id
   WHERE d.tenant_id=t AND d.id=original.audit_event_id AND o.event_id=original.outbox_event_id AND d.actor_user_id=original.posted_actor_id
    AND d.object_type='finance_posting' AND d.object_id=original.id AND d.action='finance_entry_posted'
    AND d.metadata_json=jsonb_build_object('entry_id',original.entry_id,'content_digest',original.validation_digest)
    AND o.event_type=d.action AND o.aggregate_type=d.object_type AND o.aggregate_id=d.object_id
    AND(o.workspace_id,o.organization_id,o.legal_entity_id)=(s.workspace_id,s.organization_id,s.legal_entity_id)
    AND o.payload=jsonb_build_object('entry_id',original.entry_id,'content_digest',original.validation_digest,'audit_event_id',original.audit_event_id)),
   'Attached original must retain its original native posting audit and outbox');
  PERFORM reconforge.ad1_assert(EXISTS(SELECT 1 FROM reconforge.financial_effect_ownership_guards g WHERE g.tenant_id=t AND g.id=claim.id
   AND g.owner_claim_id=claim.id AND g.owner_namespace='AD1' AND g.source_effect_id=original.id
   AND(g.workspace_id,g.organization_id,g.legal_entity_id)=(s.workspace_id,s.organization_id,s.legal_entity_id)),
   'Every whole-original AD1 claim retains its exact shared financial source guard');
  PERFORM reconforge.ad1_assert((claim.state='Reserved' AND released.id IS NULL AND NOT EXISTS(SELECT 1 FROM reconforge.accrual_deferral_phase_events z
     JOIN reconforge.accrual_deferral_plans p ON p.tenant_id=z.tenant_id AND p.id=z.plan_id WHERE p.tenant_id=t AND p.source_id=s.id AND z.posting_effect_id IS NOT NULL))
   OR(claim.state='Consumed' AND released.id IS NULL AND EXISTS(SELECT 1 FROM reconforge.accrual_deferral_phase_events z
     JOIN reconforge.accrual_deferral_plans p ON p.tenant_id=z.tenant_id AND p.id=z.plan_id WHERE p.tenant_id=t AND p.source_id=s.id AND z.posting_effect_id IS NOT NULL))
   OR(claim.state='Released' AND released.id IS NOT NULL AND released.source_id=s.id AND EXISTS(SELECT 1 FROM reconforge.accrual_deferral_plans c
     WHERE c.tenant_id=t AND c.id=released.cancellation_plan_id AND c.source_id=s.id AND c.kind='cancel' AND c.phase=2)
    AND EXISTS(SELECT 1 FROM reconforge.financial_effect_ownership_releases r WHERE r.tenant_id=t AND r.guard_id=claim.id AND r.release_id=released.id)
    AND NOT EXISTS(SELECT 1 FROM reconforge.accrual_deferral_phase_events z JOIN reconforge.accrual_deferral_plans p ON p.tenant_id=z.tenant_id AND p.id=z.plan_id
     WHERE p.tenant_id=t AND p.source_id=s.id AND z.posting_effect_id IS NOT NULL)),
   'Whole-original reservation consumption and cancellation release must close together');
 ELSE
  PERFORM reconforge.ad1_assert(cfg->'original_effect_id'='null'::jsonb AND claim.id IS NULL,'New cash voucher and accrual estimate cannot attach an implicit paid original');
 END IF;
 IF kind='new_prepaid_voucher' THEN rows:=jsonb_build_array(reconforge.ad1_line(cfg->'accounts'->>'prepaid',amount,0,'{}'),reconforge.ad1_line(cfg->'accounts'->>'cash',0,amount,'{}'));
 ELSIF kind='attach_paid_expense' THEN rows:=jsonb_build_array(reconforge.ad1_line(cfg->'accounts'->>'prepaid',amount,0,dimensions),reconforge.ad1_line(cfg->'accounts'->>'expense',0,amount,dimensions));END IF;
 expected:=jsonb_build_object('schema_version','accrual-deferral-source-v1','operation','source','mode',kind,'policy',policy,'lines',rows,
  'cash_changed_minor',CASE WHEN kind='new_prepaid_voucher' THEN -amount ELSE 0 END,'native_effect_required',rows<>'[]'::jsonb,
  'external_original_membership',membership,'allocated_minor',amount,'allocation_policy','native-hamilton-stable-id-v1','tranches',cfg->'tranches');
 PERFORM reconforge.ad1_assert(a->'equation'=expected,'Original voucher attachment cannot replace cash source membership dimensions or independent allocation');
END $ad1$;
CREATE FUNCTION reconforge.ad1_claim_close(t TEXT,source_id TEXT,tranche TEXT) RETURNS VOID LANGUAGE plpgsql SET search_path=pg_catalog AS $ad1$
DECLARE event RECORD;plan RECORD;head RECORD;state TEXT:='';previous TEXT;sequence INTEGER:=0;
BEGIN
 SELECT* INTO head FROM reconforge.accrual_deferral_claim_heads h WHERE h.tenant_id=t AND h.source_id=$2 AND h.tranche_id=$3;
 PERFORM reconforge.ad1_assert(head.source_id IS NOT NULL,'Each retained tranche has its exact original claim head');
 FOR event IN SELECT* FROM reconforge.accrual_deferral_claim_events e WHERE e.tenant_id=t AND e.source_id=$2 AND e.tranche_id=$3 ORDER BY e.sequence LOOP
  sequence:=sequence+1;
  SELECT* INTO plan FROM reconforge.accrual_deferral_plans WHERE tenant_id=t AND id=event.plan_id;
  PERFORM reconforge.ad1_assert(event.sequence=sequence AND plan.source_id=$2,'Tranche claim history must be contiguous and source bound');
  IF event.operation='Initialize' THEN PERFORM reconforge.ad1_assert(sequence=1 AND plan.kind='source' AND event.state='Available','Only original voucher preparation initializes a tranche');
  ELSIF event.operation='Claim' THEN PERFORM reconforge.ad1_assert(state='Available' AND plan.kind IN('release','accrue') AND plan.payload->>'tranche_id'=$3 AND event.state='Reserved','A tranche may have only one exact active financial plan');
  ELSIF event.operation='Consume' THEN PERFORM reconforge.ad1_assert(state='Reserved' AND event.plan_id=previous AND plan.phase=2 AND event.state='Consumed'
   AND EXISTS(SELECT 1 FROM reconforge.accrual_deferral_phase_events p WHERE p.tenant_id=t AND p.plan_id=plan.id AND p.operation='post' AND p.posting_effect_id IS NOT NULL),
   'Consumption requires the exact posted original tranche effect');
  ELSIF event.operation='Reverse' THEN PERFORM reconforge.ad1_assert(state='Consumed' AND plan.kind='reverse' AND plan.phase=2 AND plan.payload->>'original_plan_id'=previous
   AND plan.payload->>'tranche_id'=$3 AND event.state='Available','Only the exact original posted native inverse releases tranche eligibility');
  ELSE PERFORM reconforge.ad1_assert(plan.kind='cancel' AND plan.phase=2 AND state IN('Available','Reserved') AND event.state='Available'
   AND NOT EXISTS(SELECT 1 FROM reconforge.accrual_deferral_phase_events p JOIN reconforge.accrual_deferral_plans z ON z.tenant_id=p.tenant_id AND z.id=p.plan_id
    WHERE z.tenant_id=t AND z.source_id=$2 AND p.posting_effect_id IS NOT NULL),'A consumed financial source cannot be cancelled');END IF;
  state:=event.state;previous:=event.plan_id;
 END LOOP;
 PERFORM reconforge.ad1_assert(sequence BETWEEN 1 AND 16 AND(head.sequence,head.state,head.plan_id)=(sequence,state,previous),
  'Latest exact append-only claim event and current head must close together');
END $ad1$;
CREATE FUNCTION reconforge.ad1_close(t TEXT,i TEXT) RETURNS VOID LANGUAGE plpgsql SET search_path=pg_catalog AS $ad1$
DECLARE p RECORD;s RECORD;e RECORD;j RECORD;original RECORD;native RECORD;phase_event RECORD;command RECORD;initial RECORD;v JSONB;a JSONB;q JSONB;eq JSONB;req JSONB;
 expected JSONB;item JSONB;tranche JSONB;head JSONB;native_lines JSONB;expected_effect TEXT;dimensions JSONB;actor TEXT;reviewer TEXT;poster TEXT;
 amount NUMERIC;fields TEXT[]:=ARRAY['phase','status','reviewer_actor_id','posted_actor_id','posting_effect_id'];
BEGIN
 SELECT* INTO p FROM reconforge.accrual_deferral_plans WHERE tenant_id=t AND id=$2;
 IF p.id IS NULL THEN RETURN;END IF;
 SELECT* INTO s FROM reconforge.accrual_deferral_sources WHERE tenant_id=t AND id=p.source_id;
 PERFORM reconforge.ad1_source_close(t,p.source_id);
 a:=s.payload;q:=a->'request';v:=p.payload;eq:=v->'equation';req:=v->'command_request';
 SELECT* INTO native FROM reconforge.finance_posting_effects WHERE tenant_id=t AND entry_id=v->>'entry_id';
 PERFORM reconforge.ad1_assert(reconforge.fx_object(v,ARRAY['schema_version','id','source_id','workspace_id','organization_id','legal_entity_id','kind','tranche_id','original_plan_id',
  'period_id','posting_date','reason','native_period','entry_id','snapshot','validation_digest','source_digest','preparer_actor_id','equation','command_request','plan_digest'])
  AND v->>'schema_version'='accrual-deferral-plan-v1' AND(v->>'id',v->>'source_id',v->>'kind')=(p.id,s.id,p.kind)
  AND(v->>'workspace_id',v->>'organization_id',v->>'legal_entity_id')=(s.workspace_id,s.organization_id,s.legal_entity_id)
  AND v->>'source_digest'=a->>'source_digest' AND v->>'plan_digest'=reconforge.irp_digest(v-'plan_digest')
  AND p.id~CASE WHEN p.kind='reverse' THEN'^AD1R-[a-f0-9]{32}$' ELSE'^AD1-[a-f0-9]{32}$' END
  AND reconforge.irp_text(v->>'reason',500) AND(v->>'posting_date')::date::text=v->>'posting_date'
  AND req->>'kind'=p.kind AND req->>'period_id'=v->>'period_id' AND req->>'posting_date'=v->>'posting_date' AND req->>'reason'=v->>'reason',
  'Retained source plan identity scope request and sealed original content cannot diverge');
 PERFORM reconforge.ad1_assert(EXISTS(SELECT 1 FROM reconforge.fiscal_periods period WHERE period.tenant_id=t AND period.id=v->>'period_id'
  AND jsonb_build_object('id',period.id,'start_date',period.start_date::text,'end_date',period.end_date::text,'fiscal_year',period.fiscal_year,
   'period_number',period.period_number,'application_workspace_id',period.application_workspace_id)=v->'native_period'
  AND period.application_workspace_id=s.workspace_id AND(v->>'posting_date')::date BETWEEN period.start_date AND period.end_date),
  'Every native plan retains its exact current approved fiscal calendar interpretation');
 PERFORM reconforge.ad1_assert(EXISTS(SELECT 1 FROM reconforge.accrual_deferral_period_pins pin WHERE pin.tenant_id=t AND pin.source_id=s.id
  AND pin.period_id=v->>'period_id' AND jsonb_build_object('id',pin.period_id,'start_date',pin.start_date::text,'end_date',pin.end_date::text,
   'fiscal_year',pin.fiscal_year,'period_number',pin.period_number,'application_workspace_id',pin.application_workspace_id)=v->'native_period'),
  'Every native plan fiscal tuple retains a structural original calendar FK across RLS');
 SELECT* INTO initial FROM reconforge.accrual_deferral_plans WHERE tenant_id=t AND source_id=s.id AND kind='source';
 IF p.kind='source' THEN
  PERFORM reconforge.ad1_assert(reconforge.fx_object(req,ARRAY['kind','period_id','posting_date','reason','original_request']) AND req->'original_request'=q
   AND v->'tranche_id'='null'::jsonb AND v->'original_plan_id'='null'::jsonb AND v->>'preparer_actor_id'=a->>'preparer_actor_id'
   AND(v->>'period_id',v->>'posting_date',v->>'reason')=(q->>'period_id',q->>'posting_date',q->>'reason'),'Original approval retains its exact voucher request');
  expected:=a->'equation';
 ELSIF p.kind IN('release','accrue') THEN
  SELECT value INTO tranche FROM jsonb_array_elements(q->'tranches') WHERE value->>'id'=v->>'tranche_id';
  PERFORM reconforge.ad1_assert(initial.phase=2 AND tranche IS NOT NULL
   AND p.kind=CASE WHEN q->>'mode'='expense_accrual' THEN'accrue' ELSE'release' END
   AND reconforge.fx_object(req,ARRAY['kind','source_id','tranche_id','period_id','posting_date','reason']) AND req->>'source_id'=s.id
   AND req->>'tranche_id'=v->>'tranche_id' AND v->'original_plan_id'='null'::jsonb
   AND(v->>'period_id',v->>'posting_date',v->>'reason')=(tranche->>'period_id',tranche->>'posting_date',q->>'reason'),
   'A tranche must retain the exact allocated native fiscal period and approved original voucher');
  amount:=(tranche->>'amount_minor')::numeric;dimensions:=COALESCE(a->'equation'->'external_original_membership'->'basis_dimensions','{}'::jsonb);
  expected:=jsonb_build_object('schema_version','accrual-deferral-source-v1','operation',p.kind,'tranche_id',tranche->>'id','period_id',tranche->>'period_id',
   'posting_date',tranche->>'posting_date','amount_minor',amount,'lines',jsonb_build_array(reconforge.ad1_line(q->'accounts'->>'expense',amount,0,dimensions),
    reconforge.ad1_line(q->'accounts'->>CASE WHEN p.kind='accrue' THEN'accrued_liability' ELSE'prepaid' END,0,amount,dimensions)),
   'policy',a->'policy','cash_changed_minor',0,'native_effect_required',true);
  PERFORM reconforge.ad1_assert((SELECT count(*) FROM reconforge.accrual_deferral_claim_events c WHERE c.tenant_id=t AND c.plan_id=p.id AND c.operation='Claim')=1
   AND(SELECT count(*) FROM reconforge.accrual_deferral_claim_events c WHERE c.tenant_id=t AND c.plan_id=p.id AND c.operation='Consume')=CASE WHEN p.phase=2 THEN 1 ELSE 0 END,
   'Every posted allocated tranche consumes one exact original claim');
 ELSIF p.kind='reverse' THEN
  SELECT* INTO original FROM reconforge.accrual_deferral_plans WHERE tenant_id=t AND id=v->>'original_plan_id';
  SELECT* INTO native FROM reconforge.accrual_deferral_phase_events WHERE tenant_id=t AND plan_id=original.id AND operation='post';
  PERFORM reconforge.ad1_assert(original.source_id=s.id AND original.phase=2 AND original.kind IN('release','accrue')
   AND original.payload->>'tranche_id'=v->>'tranche_id' AND v->>'posting_date'>=original.payload->>'posting_date'
   AND reconforge.fx_object(req,ARRAY['kind','source_id','original_plan_id','period_id','posting_date','reason','tranche_id'])
   AND req->>'source_id'=s.id AND req->>'original_plan_id'=original.id AND req->>'tranche_id'=v->>'tranche_id',
   'An exact native inverse retains its original posted tranche membership');
  IF original.kind='accrue' THEN
   SELECT value INTO tranche FROM jsonb_array_elements(q->'tranches') WHERE value->>'id'=v->>'tranche_id';
   PERFORM reconforge.ad1_assert((v->>'period_id',v->>'posting_date')=(tranche->>'reversal_period_id',tranche->>'reversal_date'),
    'Accrual inverse cannot replace its retained next-period date');END IF;
  SELECT jsonb_agg(reconforge.ad1_line(x.value->>'account_code',(x.value->>'credit_minor')::numeric,(x.value->>'debit_minor')::numeric,x.value->'dimensions') ORDER BY x.ord)
   INTO native_lines FROM jsonb_array_elements(original.payload->'equation'->'lines') WITH ORDINALITY x(value,ord);
  expected:=jsonb_build_object('schema_version','accrual-deferral-source-v1','operation','reverse','original_plan_id',original.id,
   'original_plan_digest',original.payload->>'plan_digest','original_posting_effect_id',native.posting_effect_id,'original_kind',original.kind,
   'tranche_id',original.payload->>'tranche_id','amount_minor',original.payload->'equation'->'amount_minor','policy',a->'policy','lines',native_lines,
   'cash_changed_minor',0,'native_effect_required',true);
  expected_effect:=native.posting_effect_id;
  PERFORM reconforge.ad1_assert((SELECT count(*) FROM reconforge.accrual_deferral_claim_events c WHERE c.tenant_id=t AND c.plan_id=p.id AND c.operation='Reverse')
   =CASE WHEN p.phase=2 THEN 1 ELSE 0 END,'Only a fully posted exact inverse releases the original tranche claim');
 ELSE
  PERFORM reconforge.ad1_assert(reconforge.fx_object(req,ARRAY['kind','source_id','period_id','posting_date','reason']) AND req->>'source_id'=s.id
   AND(v->>'period_id',v->>'posting_date')=(q->>'period_id',q->>'posting_date')
   AND v->'tranche_id'='null'::jsonb AND v->'original_plan_id'='null'::jsonb
   AND NOT EXISTS(SELECT 1 FROM reconforge.accrual_deferral_phase_events z JOIN reconforge.accrual_deferral_plans b ON b.tenant_id=z.tenant_id AND b.id=z.plan_id
    WHERE b.tenant_id=t AND b.source_id=s.id AND z.posting_effect_id IS NOT NULL),'A financial original effect cannot be undone through non-financial cancellation');
  expected:=jsonb_build_object('schema_version','accrual-deferral-source-v1','operation','cancel','lines','[]'::jsonb,
   'policy',a->'policy','cash_changed_minor',0,'native_effect_required',false);
  PERFORM reconforge.ad1_assert((SELECT count(*) FROM reconforge.accrual_deferral_claim_events c WHERE c.tenant_id=t AND c.plan_id=p.id AND c.operation='Cancel')
   =CASE WHEN p.phase=2 THEN jsonb_array_length(q->'tranches') ELSE 0 END,'Cancellation releases every unconsumed retained tranche exactly once');
 END IF;
 PERFORM reconforge.ad1_assert(eq=expected,'Independent source cash membership allocation accrued liability dimensions and exact inverse cannot diverge');
 IF(expected->>'native_effect_required')::boolean THEN
  SELECT* INTO e FROM reconforge.finance_entries WHERE tenant_id=t AND id=v->>'entry_id';
  SELECT* INTO j FROM reconforge.finance_journals WHERE tenant_id=t AND id=e.journal_id;
  PERFORM reconforge.ad1_assert(e.id IS NOT NULL AND upper(e.entry_number)=upper(p.id) AND e.workspace_id=s.workspace_id
   AND(e.organization_code,e.entity_code,e.period_id,e.posting_date,e.description,e.preparer_actor_id)
    =(q->>'organization_code',q->>'entity_code',v->>'period_id',v->>'posting_date',v->>'reason',v->>'preparer_actor_id')
   AND(j.journal_code,j.workspace_id,j.organization_code)=(q->>'journal_code',s.workspace_id,q->>'organization_code')
   AND e.reverses_posting_id IS NOT DISTINCT FROM expected_effect AND e.source_type=CASE WHEN p.kind='reverse' THEN'Generated' ELSE'Manual' END
   AND e.external_reference=CASE WHEN p.kind='reverse' THEN expected_effect ELSE'AD1:'||s.id||':'||p.kind END
   AND(e.currency_code,e.currency_precision::text,e.currency_rounding_policy,e.currency_registry_version,e.currency_registry_digest)
    =(a->'policy'->>'currency_code',a->'policy'->>'currency_precision',a->'policy'->>'currency_rounding_policy',a->'policy'->>'currency_registry_version',a->'policy'->>'currency_registry_digest'),
   'Each exact native source voucher and inverse retains original journal scope policy and source ownership');
  SELECT jsonb_agg(reconforge.ad1_line(ac.account_code,l.debit_minor,l.credit_minor,COALESCE((SELECT jsonb_object_agg(d.dimension_id,d.dimension_value_id)
   FROM reconforge.finance_entry_line_dimensions d WHERE d.tenant_id=l.tenant_id AND d.entry_line_id=l.id),'{}'::jsonb)) ORDER BY l.line_number)
   INTO native_lines FROM reconforge.finance_entry_lines l JOIN reconforge.finance_accounts ac ON ac.tenant_id=l.tenant_id AND ac.id=l.account_id WHERE l.tenant_id=t AND l.entry_id=e.id;
  PERFORM reconforge.ad1_assert(native_lines=expected->'lines' AND e.total_debit_minor=e.total_credit_minor AND e.total_debit_minor BETWEEN 1 AND 9000000000000000000
   AND e.total_debit_minor=(SELECT sum((x->>'debit_minor')::numeric) FROM jsonb_array_elements(expected->'lines')x),'Native cash and tranche allocations must conserve exact functional money');
  SELECT jsonb_object_agg(key,value) INTO head FROM jsonb_each(to_jsonb(e)) WHERE key=ANY(ARRAY['id','workspace_id','journal_id','period_id','entry_number','posting_date','description','external_reference','source_type',
   'currency_code','currency_precision','currency_rounding_policy','currency_registry_version','currency_registry_digest','preparer_actor_id','reverses_posting_id']);
  head:=head||jsonb_build_object('organization_id',s.organization_id,'legal_entity_id',s.legal_entity_id);
  SELECT jsonb_agg(jsonb_build_object('line_number',l.line_number,'account_id',l.account_id,'description',l.description,'debit_minor',l.debit_minor,'credit_minor',l.credit_minor,
   'dimensions',COALESCE((SELECT jsonb_object_agg(d.dimension_id,d.dimension_value_id) FROM reconforge.finance_entry_line_dimensions d WHERE d.tenant_id=l.tenant_id AND d.entry_line_id=l.id),'{}'::jsonb)) ORDER BY l.line_number)
   INTO native_lines FROM reconforge.finance_entry_lines l WHERE l.tenant_id=t AND l.entry_id=e.id;
  PERFORM reconforge.ad1_assert(v->'snapshot'=jsonb_build_object('schema_version','finance-entry-review-v1','entry',head,'lines',native_lines)
   AND v->>'validation_digest'=reconforge.irp_digest(v->'snapshot'),'Complete source native snapshot and dimensions retain exact original membership');
 ELSE PERFORM reconforge.ad1_assert(v->'entry_id'='null'::jsonb AND v->'snapshot'='null'::jsonb AND v->'validation_digest'='null'::jsonb,
  'Original attachment membership and estimate approval must not invent a native GL effect');END IF;
 SELECT actor_id INTO reviewer FROM reconforge.accrual_deferral_phase_events WHERE tenant_id=t AND plan_id=p.id AND operation='review';
 SELECT actor_id INTO poster FROM reconforge.accrual_deferral_phase_events WHERE tenant_id=t AND plan_id=p.id AND operation='post';
 PERFORM reconforge.ad1_assert((p.phase=0 AND reviewer IS NULL AND poster IS NULL) OR(p.phase=1 AND reviewer IS NOT NULL AND reviewer<>v->>'preparer_actor_id' AND poster IS NULL)
  OR(p.phase=2 AND reviewer IS NOT NULL AND poster IS NOT NULL AND reviewer<>v->>'preparer_actor_id' AND poster NOT IN(reviewer,v->>'preparer_actor_id')),
  'Every voucher approval and native tranche requires three distinct actual human phase actors');
 IF(expected->>'native_effect_required')::boolean THEN
  SELECT* INTO native FROM reconforge.finance_posting_effects WHERE tenant_id=t AND entry_id=e.id;
  IF p.phase=0 THEN PERFORM reconforge.ad1_assert(e.status='Draft' AND e.validation_digest IS NULL AND native.id IS NULL,'Prepared vouchers cannot contain a detached native review or effect');
  ELSE PERFORM reconforge.ad1_assert(e.status='Validated' AND e.validator_actor_id=reviewer AND e.validation_digest=v->>'validation_digest','Independent review seals the exact native voucher');
   IF p.phase=1 THEN PERFORM reconforge.ad1_assert(native.id IS NULL,'Reviewed voucher cannot contain an early native effect');
   ELSE PERFORM reconforge.ad1_assert(native.id IS NOT NULL AND native.snapshot_json=v->'snapshot' AND native.validation_digest=v->>'validation_digest'
    AND native.posted_actor_id=poster AND native.reverses_effect_id IS NOT DISTINCT FROM expected_effect
    AND native.source_kind=CASE WHEN p.kind='reverse' THEN'Reversal' ELSE'Manual' END,
    'Source-owned publication requires its exact native original or full inverse effect');END IF;
  END IF;
 END IF;
 PERFORM reconforge.ad1_assert((SELECT count(*) FROM reconforge.accrual_deferral_phase_events WHERE tenant_id=t AND plan_id=p.id)=p.phase+1
  AND(SELECT count(*) FROM reconforge.accrual_deferral_commands WHERE tenant_id=t AND plan_id=p.id)=p.phase+1,'Every phase retains one exact original acknowledgement and audit/outbox');
 FOR phase_event IN SELECT* FROM reconforge.accrual_deferral_phase_events WHERE tenant_id=t AND plan_id=p.id LOOP
  actor:=CASE phase_event.operation WHEN'prepare' THEN v->>'preparer_actor_id' WHEN'review' THEN reviewer ELSE poster END;
  PERFORM reconforge.ad1_assert(phase_event.actor_id=actor AND phase_event.posting_effect_id IS NOT DISTINCT FROM
   CASE WHEN phase_event.operation='post' AND(expected->>'native_effect_required')::boolean THEN native.id ELSE NULL END
   AND EXISTS(SELECT 1 FROM reconforge.domain_audit_events d JOIN reconforge.outbox_events o ON o.tenant_id=d.tenant_id
    WHERE d.tenant_id=t AND d.id=phase_event.audit_event_id AND o.event_id=phase_event.outbox_event_id AND d.actor_user_id=actor
     AND d.object_type='operational_finance' AND d.object_id=p.id AND d.action='accrual_deferral_'||phase_event.operation
     AND d.metadata_json=jsonb_build_object('plan_digest',v->>'plan_digest') AND o.aggregate_type=d.object_type AND o.aggregate_id=d.object_id AND o.event_type=d.action
     AND(o.workspace_id,o.organization_id,o.legal_entity_id)=(s.workspace_id,s.organization_id,s.legal_entity_id)
     AND o.payload=d.metadata_json||jsonb_build_object('audit_event_id',d.id)),'Original human phase audit and outbox cannot be detached');
  SELECT* INTO command FROM reconforge.accrual_deferral_commands c WHERE c.tenant_id=t AND c.plan_id=p.id AND c.operation=phase_event.operation;
  PERFORM reconforge.ad1_assert(command.actor_id=actor AND command.request_digest=reconforge.irp_digest(command.request_json)
   AND reconforge.fx_object(command.request_json,ARRAY['operation','actor_id','request'])
   AND command.request_json->>'operation'=command.operation AND command.request_json->>'actor_id'=actor
   AND(command.workspace_id,command.organization_id,command.legal_entity_id)=(s.workspace_id,s.organization_id,s.legal_entity_id)
   AND command.response_json-fields=v AND command.response_json->>'status'=CASE command.operation WHEN'prepare' THEN'Prepared' WHEN'review' THEN'Reviewed' ELSE'Posted' END
   AND(command.response_json->>'phase')::integer=CASE command.operation WHEN'prepare' THEN 0 WHEN'review' THEN 1 ELSE 2 END,
   'Retained command response binds the exact actor scope source and phase');
  IF command.operation='prepare' THEN PERFORM reconforge.ad1_assert(command.request_json->'request'=req AND command.response_json->'reviewer_actor_id'='null'::jsonb
   AND command.response_json->'posted_actor_id'='null'::jsonb AND command.response_json->'posting_effect_id'='null'::jsonb,'Original preparation acknowledgement differs');
  ELSE PERFORM reconforge.ad1_assert(command.request_json->'request'->>'plan_id'=p.id AND command.request_json->'request'->>'expected_plan_digest'=v->>'plan_digest'
   AND command.request_json->'request'->>'reason'=phase_event.reason AND command.response_json->>'reviewer_actor_id'=reviewer,
   'Reviewed acknowledgement must retain the exact source digest and reason');
   IF command.operation='review' THEN PERFORM reconforge.ad1_assert(command.response_json->'posted_actor_id'='null'::jsonb AND command.response_json->'posting_effect_id'='null'::jsonb,'Review cannot claim early publication');
   ELSE PERFORM reconforge.ad1_assert(command.response_json->>'posted_actor_id'=poster AND command.response_json->>'posting_effect_id' IS NOT DISTINCT FROM phase_event.posting_effect_id,
    'Publication acknowledgement must retain its exact native effect or explicit external-only membership');END IF;
  END IF;
 END LOOP;
 FOR item IN SELECT value FROM jsonb_array_elements(q->'tranches') LOOP PERFORM reconforge.ad1_claim_close(t,s.id,item->>'id');END LOOP;
 PERFORM reconforge.ad1_assert((SELECT count(*) FROM reconforge.accrual_deferral_claim_heads WHERE tenant_id=t AND source_id=s.id)=jsonb_array_length(q->'tranches'),
  'All source tranches have one exact current claim head');
END $ad1$;
CREATE FUNCTION reconforge.ad1_command_actor() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $ad1$
DECLARE source RECORD;plan RECORD;permission TEXT;
BEGIN
 SELECT* INTO plan FROM reconforge.accrual_deferral_plans WHERE tenant_id=NEW.tenant_id AND id=NEW.plan_id;
 SELECT* INTO source FROM reconforge.accrual_deferral_sources WHERE tenant_id=NEW.tenant_id AND id=plan.source_id FOR UPDATE;
 PERFORM 1 FROM reconforge.identity_user_roles u JOIN reconforge.identity_role_permissions r ON r.tenant_id=u.tenant_id AND r.role_id=u.role_id
  WHERE u.tenant_id=NEW.tenant_id AND u.user_id=NEW.actor_id ORDER BY u.role_id,r.permission_name FOR SHARE OF u,r;
 permission:=CASE NEW.operation WHEN'review' THEN'finance_core.validate' WHEN'post' THEN'finance_core.post' ELSE'finance_core.manage' END;
 PERFORM reconforge.ad1_assert(reconforge.sales_revenue_actor(NEW.tenant_id,NEW.actor_id,permission)
  AND reconforge.sales_revenue_actor(NEW.tenant_id,NEW.actor_id,'accrual_deferral.'||NEW.operation),
  'Each new phase needs current persisted human owner and native finance permission');
 IF plan.kind='reverse' THEN PERFORM reconforge.ad1_assert(reconforge.sales_revenue_actor(NEW.tenant_id,NEW.actor_id,'finance_core.reverse'),
  'Every new inverse phase needs current persisted native reverse permission');END IF;
 PERFORM 1 FROM reconforge.principal_scope_grants WHERE tenant_id=NEW.tenant_id AND principal_type='user' AND principal_id=NEW.actor_id
  AND revoked_at IS NULL ORDER BY scope_type,scope_id FOR SHARE;
 PERFORM reconforge.ad1_assert((SELECT count(DISTINCT(scope_type,scope_id)) FROM reconforge.principal_scope_grants WHERE tenant_id=NEW.tenant_id
  AND principal_type='user' AND principal_id=NEW.actor_id AND revoked_at IS NULL
  AND((scope_type='workspace' AND scope_id=source.workspace_id) OR(scope_type='organization' AND scope_id=source.organization_id)
   OR(scope_type='legal_entity' AND scope_id=source.legal_entity_id)))=3
  AND NOT EXISTS(SELECT 1 FROM reconforge.accrual_deferral_plans c WHERE c.tenant_id=NEW.tenant_id AND c.source_id=source.id AND c.kind='cancel' AND c.id<>plan.id),
  'Every current phase retains exact native hierarchy grants and an uncancelled original source');
 PERFORM reconforge.ad1_assert(EXISTS(SELECT 1 FROM reconforge.fiscal_periods p WHERE p.tenant_id=NEW.tenant_id AND p.id=plan.payload->>'period_id'
  AND p.application_workspace_id=source.workspace_id AND p.status='Open' AND(plan.payload->>'posting_date')::date BETWEEN p.start_date AND p.end_date),
  'New owner phases cannot cross a closed or changed native fiscal period');
 RETURN NEW;
END $ad1$;
CREATE TRIGGER current_ad1_actor BEFORE INSERT ON reconforge.accrual_deferral_commands FOR EACH ROW EXECUTE FUNCTION reconforge.ad1_command_actor();
CREATE FUNCTION reconforge.ad1_deferred() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $ad1$
DECLARE source TEXT;plan TEXT;value JSONB:=to_jsonb(NEW);row RECORD;
BEGIN
 IF TG_TABLE_NAME='accrual_deferral_sources' THEN source:=value->>'id';
 ELSIF TG_TABLE_NAME='accrual_deferral_plans' THEN source:=value->>'source_id';
 ELSIF TG_TABLE_NAME IN('accrual_deferral_phase_events','accrual_deferral_commands') THEN plan:=value->>'plan_id';
 ELSE source:=value->>'source_id';END IF;
 IF plan IS NOT NULL THEN PERFORM reconforge.ad1_close(value->>'tenant_id',plan);
 ELSE
  PERFORM reconforge.ad1_assert(EXISTS(SELECT 1 FROM reconforge.accrual_deferral_plans WHERE tenant_id=value->>'tenant_id' AND source_id=source AND kind='source'),
   'Every original AD1 source retains its closed original voucher plan');
  FOR row IN SELECT id FROM reconforge.accrual_deferral_plans WHERE tenant_id=value->>'tenant_id' AND source_id=source LOOP
   PERFORM reconforge.ad1_close(value->>'tenant_id',row.id);END LOOP;
 END IF;RETURN NEW;
END $ad1$;
CREATE FUNCTION reconforge.ad1_native_close() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $ad1$
DECLARE changed JSONB;entry TEXT;original TEXT;number TEXT;native_id TEXT;owner RECORD;inverse RECORD;source_plan RECORD;
BEGIN
 FOR changed IN SELECT value FROM jsonb_array_elements(CASE TG_OP WHEN'INSERT' THEN jsonb_build_array(to_jsonb(NEW)) WHEN'DELETE' THEN jsonb_build_array(to_jsonb(OLD)) ELSE jsonb_build_array(to_jsonb(OLD),to_jsonb(NEW)) END) LOOP
  entry:=NULL;original:=NULL;number:=NULL;native_id:=NULL;
  IF TG_TABLE_NAME='finance_entries' THEN entry:=changed->>'id';original:=changed->>'reverses_posting_id';number:=changed->>'entry_number';
  ELSIF TG_TABLE_NAME IN('finance_entry_lines','finance_posting_effects') THEN entry:=changed->>'entry_id';original:=changed->>'reverses_effect_id';
  ELSE SELECT entry_id INTO entry FROM reconforge.finance_entry_lines WHERE tenant_id=changed->>'tenant_id' AND id=changed->>'entry_line_id';END IF;
  SELECT e.entry_number,e.id INTO number,native_id FROM reconforge.finance_entries e WHERE e.tenant_id=changed->>'tenant_id' AND e.id=entry;
  -- Ordinary native work does not read protected AD1 tables unless its actual
  -- old/current entry identity or original source reserves this namespace.
  IF COALESCE(upper(number),'') LIKE ANY(ARRAY['AD1-%','AD1R-%']) OR COALESCE(upper(native_id),'') LIKE ANY(ARRAY['AD1-%','AD1R-%'])
   OR COALESCE(upper(changed->>'entry_number'),'') LIKE ANY(ARRAY['AD1-%','AD1R-%']) OR COALESCE(upper(entry),'') LIKE ANY(ARRAY['AD1-%','AD1R-%']) THEN
   SELECT* INTO owner FROM reconforge.accrual_deferral_plans WHERE tenant_id=changed->>'tenant_id' AND payload->>'entry_id'=entry;
   PERFORM reconforge.ad1_assert(owner.id IS NOT NULL,'Reserved AD1 entries require their actual source owner');
   PERFORM reconforge.ad1_close(changed->>'tenant_id',owner.id);
  END IF;
  IF original IS NOT NULL THEN
   SELECT e.entry_number,e.id INTO number,native_id FROM reconforge.finance_posting_effects p JOIN reconforge.finance_entries e ON e.tenant_id=p.tenant_id AND e.id=p.entry_id
    WHERE p.tenant_id=changed->>'tenant_id' AND p.id=original;
   IF COALESCE(upper(number),'') LIKE ANY(ARRAY['AD1-%','AD1R-%']) OR COALESCE(upper(native_id),'') LIKE ANY(ARRAY['AD1-%','AD1R-%']) THEN
    SELECT* INTO source_plan FROM reconforge.accrual_deferral_plans WHERE tenant_id=changed->>'tenant_id' AND payload->>'entry_id'=native_id;
    SELECT* INTO inverse FROM reconforge.accrual_deferral_plans WHERE tenant_id=changed->>'tenant_id' AND payload->>'entry_id'=entry;
    PERFORM reconforge.ad1_assert(source_plan.id IS NOT NULL AND source_plan.phase=2 AND source_plan.kind IN('release','accrue')
     AND inverse.id IS NOT NULL AND inverse.kind='reverse' AND inverse.source_id=source_plan.source_id AND inverse.payload->>'original_plan_id'=source_plan.id,
     'Native AD1 inverse must retain its exact posted original tranche owner');
    PERFORM reconforge.ad1_close(changed->>'tenant_id',inverse.id);
   END IF;
  END IF;
 END LOOP;RETURN NULL;
END $ad1$;
DO $ad1$ DECLARE name TEXT;BEGIN
 FOREACH name IN ARRAY ARRAY['accrual_deferral_sources','accrual_deferral_plans','accrual_deferral_period_pins','accrual_deferral_account_pins','accrual_deferral_phase_events','accrual_deferral_claim_events','accrual_deferral_claim_heads',
  'accrual_deferral_original_claims','accrual_deferral_original_releases','accrual_deferral_commands'] LOOP
  EXECUTE format('ALTER TABLE reconforge.%I ENABLE ROW LEVEL SECURITY',name);EXECUTE format('ALTER TABLE reconforge.%I FORCE ROW LEVEL SECURITY',name);
  IF name IN('accrual_deferral_sources','accrual_deferral_original_claims','accrual_deferral_original_releases','accrual_deferral_commands') THEN
   EXECUTE format('CREATE POLICY source_scope ON reconforge.%I USING(tenant_id=current_setting(''app.tenant_id'',true) AND reconforge.irp_scope(tenant_id,workspace_id,organization_id,legal_entity_id)) WITH CHECK(tenant_id=current_setting(''app.tenant_id'',true) AND reconforge.irp_scope(tenant_id,workspace_id,organization_id,legal_entity_id))',name);
  ELSIF name IN('accrual_deferral_plans','accrual_deferral_period_pins','accrual_deferral_account_pins','accrual_deferral_claim_events','accrual_deferral_claim_heads') THEN
   EXECUTE format('CREATE POLICY source_scope ON reconforge.%I USING(tenant_id=current_setting(''app.tenant_id'',true) AND EXISTS(SELECT 1 FROM reconforge.accrual_deferral_sources s WHERE s.tenant_id=%I.tenant_id AND s.id=%I.source_id)) WITH CHECK(tenant_id=current_setting(''app.tenant_id'',true) AND EXISTS(SELECT 1 FROM reconforge.accrual_deferral_sources s WHERE s.tenant_id=%I.tenant_id AND s.id=%I.source_id))',name,name,name,name,name);
  ELSE EXECUTE format('CREATE POLICY source_scope ON reconforge.%I USING(tenant_id=current_setting(''app.tenant_id'',true) AND EXISTS(SELECT 1 FROM reconforge.accrual_deferral_plans p WHERE p.tenant_id=%I.tenant_id AND p.id=%I.plan_id)) WITH CHECK(tenant_id=current_setting(''app.tenant_id'',true) AND EXISTS(SELECT 1 FROM reconforge.accrual_deferral_plans p WHERE p.tenant_id=%I.tenant_id AND p.id=%I.plan_id))',name,name,name,name,name);END IF;
  EXECUTE format('CREATE TRIGGER original_ad1_owner BEFORE UPDATE OR DELETE ON reconforge.%I FOR EACH ROW EXECUTE FUNCTION reconforge.ad1_protect()',name);
  EXECUTE format('CREATE CONSTRAINT TRIGGER closed_ad1_owner AFTER INSERT OR UPDATE ON reconforge.%I DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION reconforge.ad1_deferred()',name);
 END LOOP;
 FOREACH name IN ARRAY ARRAY['finance_entries','finance_entry_lines','finance_entry_line_dimensions','finance_posting_effects'] LOOP
  EXECUTE format('CREATE CONSTRAINT TRIGGER native_ad1_owner AFTER INSERT OR UPDATE OR DELETE ON reconforge.%I DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION reconforge.ad1_native_close()',name);
 END LOOP;
END $ad1$;
"""

DOWNGRADE_SQL = r"""
DO $ad1$ BEGIN IF EXISTS(SELECT 1 FROM reconforge.accrual_deferral_sources) THEN
 RAISE EXCEPTION 'Populated accrual deferral history requires restore; destructive downgrade refused';END IF;END $ad1$;
DROP TRIGGER native_ad1_owner ON reconforge.finance_posting_effects;
DROP TRIGGER native_ad1_owner ON reconforge.finance_entry_line_dimensions;
DROP TRIGGER native_ad1_owner ON reconforge.finance_entry_lines;
DROP TRIGGER native_ad1_owner ON reconforge.finance_entries;
DROP TABLE reconforge.accrual_deferral_commands,reconforge.accrual_deferral_original_releases,reconforge.accrual_deferral_original_claims,reconforge.accrual_deferral_period_pins,reconforge.accrual_deferral_account_pins,
 reconforge.accrual_deferral_claim_heads,reconforge.accrual_deferral_claim_events,reconforge.accrual_deferral_phase_events,
 reconforge.accrual_deferral_plans,reconforge.accrual_deferral_sources;
ALTER TABLE reconforge.fiscal_periods DROP CONSTRAINT ad1_fiscal_identity;
ALTER TABLE reconforge.finance_accounts DROP CONSTRAINT ad1_native_account_identity;
DROP FUNCTION reconforge.ad1_native_close(),reconforge.ad1_deferred(),reconforge.ad1_command_actor(),
 reconforge.ad1_close(TEXT,TEXT),reconforge.ad1_claim_close(TEXT,TEXT,TEXT),reconforge.ad1_source_close(TEXT,TEXT),
 reconforge.ad1_allocate(JSONB),reconforge.ad1_line(TEXT,NUMERIC,NUMERIC,JSONB),reconforge.ad1_protect(),reconforge.ad1_assert(BOOLEAN,TEXT);
"""
