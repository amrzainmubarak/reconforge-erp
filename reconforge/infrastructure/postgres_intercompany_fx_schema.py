"""Revision0139 paired foreign trade owner; canonical FX functions are reused."""

from typing import Any

UPGRADE_SQL = r"""
CREATE TABLE reconforge.intercompany_fx_sources(
 tenant_id TEXT NOT NULL,id TEXT NOT NULL,workspace_id TEXT NOT NULL,organization_id TEXT NOT NULL,
 seller_entity_id TEXT NOT NULL,buyer_entity_id TEXT NOT NULL,adjustment_entity_id TEXT NOT NULL,reference TEXT NOT NULL,
 payload JSONB NOT NULL CHECK(jsonb_typeof(payload)='object' AND octet_length(payload::text)<=65536),
 PRIMARY KEY(tenant_id,id),UNIQUE(tenant_id,workspace_id,reference),
 CHECK(seller_entity_id<>buyer_entity_id AND seller_entity_id<>adjustment_entity_id AND buyer_entity_id<>adjustment_entity_id),
 FOREIGN KEY(tenant_id,seller_entity_id) REFERENCES reconforge.legal_entities(tenant_id,id),
 FOREIGN KEY(tenant_id,buyer_entity_id) REFERENCES reconforge.legal_entities(tenant_id,id),
 FOREIGN KEY(tenant_id,adjustment_entity_id) REFERENCES reconforge.legal_entities(tenant_id,id));
CREATE TABLE reconforge.intercompany_fx_plans(
 tenant_id TEXT NOT NULL,id TEXT NOT NULL,workspace_id TEXT NOT NULL,organization_id TEXT NOT NULL,
 seller_entity_id TEXT NOT NULL,buyer_entity_id TEXT NOT NULL,adjustment_entity_id TEXT NOT NULL,source_id TEXT NOT NULL,
 sequence INTEGER NOT NULL CHECK(sequence BETWEEN 0 AND 63),kind TEXT NOT NULL CHECK(kind IN('recognize','settle','revalue','reverse_revaluation','eliminate')),
 phase INTEGER NOT NULL CHECK(phase BETWEEN 0 AND 2),payload JSONB NOT NULL CHECK(jsonb_typeof(payload)='object' AND octet_length(payload::text)<=1048576),
 audit_event_id TEXT NOT NULL,outbox_event_id TEXT NOT NULL,PRIMARY KEY(tenant_id,id),UNIQUE(tenant_id,source_id,sequence),
 FOREIGN KEY(tenant_id,source_id) REFERENCES reconforge.intercompany_fx_sources(tenant_id,id));
CREATE UNIQUE INDEX intercompany_fx_pending ON reconforge.intercompany_fx_plans(tenant_id,source_id) WHERE phase<2;
CREATE UNIQUE INDEX intercompany_fx_elimination ON reconforge.intercompany_fx_plans(tenant_id,source_id) WHERE kind='eliminate';
CREATE TABLE reconforge.intercompany_fx_reviews(
 tenant_id TEXT NOT NULL,plan_id TEXT NOT NULL,reviewer_actor_id TEXT NOT NULL,reason TEXT NOT NULL CHECK(reconforge.irp_text(reason,500)),
 audit_event_id TEXT NOT NULL,outbox_event_id TEXT NOT NULL,PRIMARY KEY(tenant_id,plan_id),
 FOREIGN KEY(tenant_id,plan_id) REFERENCES reconforge.intercompany_fx_plans(tenant_id,id),
 FOREIGN KEY(tenant_id,reviewer_actor_id) REFERENCES reconforge.identity_users(tenant_id,id));
CREATE TABLE reconforge.intercompany_fx_links(
 tenant_id TEXT NOT NULL,plan_id TEXT NOT NULL,book TEXT NOT NULL CHECK(book IN('seller','buyer','adjustment')),
 entry_id TEXT NOT NULL,posting_effect_id TEXT NOT NULL,posted_actor_id TEXT NOT NULL,reason TEXT NOT NULL CHECK(reconforge.irp_text(reason,500)),
 PRIMARY KEY(tenant_id,plan_id,book),UNIQUE(tenant_id,entry_id),UNIQUE(tenant_id,posting_effect_id),
 FOREIGN KEY(tenant_id,plan_id) REFERENCES reconforge.intercompany_fx_plans(tenant_id,id),
 FOREIGN KEY(tenant_id,entry_id) REFERENCES reconforge.finance_entries(tenant_id,id),
 FOREIGN KEY(tenant_id,posting_effect_id) REFERENCES reconforge.finance_posting_effects(tenant_id,id),
 FOREIGN KEY(tenant_id,posted_actor_id) REFERENCES reconforge.identity_users(tenant_id,id));
CREATE TABLE reconforge.intercompany_fx_post_evidence(
 tenant_id TEXT NOT NULL,plan_id TEXT NOT NULL,audit_event_id TEXT NOT NULL,outbox_event_id TEXT NOT NULL,
 PRIMARY KEY(tenant_id,plan_id),FOREIGN KEY(tenant_id,plan_id) REFERENCES reconforge.intercompany_fx_plans(tenant_id,id));
CREATE TABLE reconforge.intercompany_fx_commands(
 tenant_id TEXT NOT NULL,workspace_id TEXT NOT NULL,organization_id TEXT NOT NULL,seller_entity_id TEXT NOT NULL,
 buyer_entity_id TEXT NOT NULL,adjustment_entity_id TEXT NOT NULL,plan_id TEXT NOT NULL,
 operation TEXT NOT NULL CHECK(operation IN('prepare','review','post')),command_id TEXT NOT NULL CHECK(reconforge.irp_text(command_id,140)),
 actor_id TEXT NOT NULL,request_digest TEXT NOT NULL,request_json JSONB NOT NULL,response_json JSONB NOT NULL,
 PRIMARY KEY(tenant_id,workspace_id,command_id),UNIQUE(tenant_id,plan_id,operation),
 FOREIGN KEY(tenant_id,plan_id) REFERENCES reconforge.intercompany_fx_plans(tenant_id,id),
 FOREIGN KEY(tenant_id,actor_id) REFERENCES reconforge.identity_users(tenant_id,id),
 CHECK(octet_length(request_json::text)<=262144 AND octet_length(response_json::text)<=1048576));
CREATE FUNCTION reconforge.icfx_assert(ok BOOLEAN,message TEXT) RETURNS VOID LANGUAGE plpgsql SET search_path=pg_catalog AS $icfx$
BEGIN IF ok IS DISTINCT FROM TRUE THEN RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='intercompany_fx_owner',MESSAGE=message;END IF;END $icfx$;
CREATE FUNCTION reconforge.icfx_scope(t TEXT,w TEXT,o TEXT,a TEXT,b TEXT,g TEXT) RETURNS BOOLEAN
 LANGUAGE sql STABLE SECURITY INVOKER SET search_path=pg_catalog AS $icfx$
 SELECT a<>b AND a<>g AND b<>g AND reconforge.irp_scope(t,w,o,a) AND reconforge.irp_scope(t,w,o,b) AND reconforge.irp_scope(t,w,o,g)
$icfx$;
CREATE FUNCTION reconforge.icfx_line(account TEXT,debit NUMERIC,credit NUMERIC) RETURNS JSONB LANGUAGE sql IMMUTABLE SET search_path=pg_catalog AS $icfx$
 SELECT jsonb_build_object('account_code',account,'debit_minor',debit,'credit_minor',credit)
$icfx$;
CREATE FUNCTION reconforge.icfx_event(t TEXT,p TEXT,a TEXT,b TEXT,actor TEXT,action TEXT,metadata JSONB) RETURNS BOOLEAN
 LANGUAGE sql STABLE SECURITY INVOKER SET search_path=pg_catalog AS $icfx$
 SELECT EXISTS(SELECT 1 FROM reconforge.domain_audit_events x JOIN reconforge.outbox_events y ON y.tenant_id=x.tenant_id
 JOIN reconforge.intercompany_fx_plans z ON z.tenant_id=x.tenant_id AND z.id=p WHERE x.tenant_id=t AND x.id=a AND y.event_id=b
 AND x.actor_user_id=actor AND x.object_type='operational_finance' AND x.object_id=p AND x.action=$6 AND x.metadata_json=$7
 AND y.event_type=$6 AND y.aggregate_type='operational_finance' AND y.aggregate_id=p
 AND y.payload=$7||jsonb_build_object('audit_event_id',a)
 AND(y.workspace_id,y.organization_id,y.legal_entity_id)=(z.workspace_id,z.organization_id,z.adjustment_entity_id))
$icfx$;
CREATE FUNCTION reconforge.icfx_protect() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $icfx$
BEGIN
 IF TG_TABLE_NAME='intercompany_fx_plans' AND TG_OP='UPDATE' THEN
  IF NEW.phase=OLD.phase+1 AND(to_jsonb(NEW)-'phase')=(to_jsonb(OLD)-'phase') THEN RETURN NEW;END IF;
 END IF;
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='intercompany_fx_owner',MESSAGE='Original foreign pair, retained rates, native memberships and phase evidence are immutable';
END $icfx$;
CREATE FUNCTION reconforge.icfx_command_actor() RETURNS trigger LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog AS $icfx$
DECLARE p RECORD;permission TEXT;entity TEXT;period TEXT;
BEGIN
 SELECT* INTO p FROM reconforge.intercompany_fx_plans WHERE tenant_id=NEW.tenant_id AND id=NEW.plan_id;
 permission:=CASE NEW.operation WHEN'prepare' THEN'finance_core.manage' WHEN'review' THEN'finance_core.validate' ELSE'finance_core.post' END;
 PERFORM reconforge.icfx_assert(reconforge.sales_revenue_actor(NEW.tenant_id,NEW.actor_id,permission)
 AND reconforge.sales_revenue_actor(NEW.tenant_id,NEW.actor_id,'intercompany_fx.'||NEW.operation), 'Current independent human owner permission is required');
 IF p.kind='reverse_revaluation' THEN
  PERFORM 1 FROM reconforge.identity_role_permissions rp JOIN reconforge.identity_user_roles ur
   ON ur.tenant_id=rp.tenant_id AND ur.role_id=rp.role_id WHERE rp.tenant_id=NEW.tenant_id AND ur.user_id=NEW.actor_id
   AND ur.active AND rp.active AND rp.permission_name='finance_core.reverse' FOR SHARE OF rp,ur;
  PERFORM reconforge.icfx_assert(reconforge.sales_revenue_actor(NEW.tenant_id,NEW.actor_id,'finance_core.reverse'),
   'Every new inverse phase requires current persisted native reverse permission');
 END IF;
 PERFORM 1 FROM reconforge.principal_scope_grants WHERE tenant_id=NEW.tenant_id AND principal_type='user' AND principal_id=NEW.actor_id
 AND revoked_at IS NULL ORDER BY scope_type,scope_id FOR SHARE;
 PERFORM reconforge.icfx_assert((SELECT count(DISTINCT(scope_type,scope_id)) FROM reconforge.principal_scope_grants
 WHERE tenant_id=NEW.tenant_id AND principal_type='user' AND principal_id=NEW.actor_id AND revoked_at IS NULL
 AND((scope_type='workspace' AND scope_id=NEW.workspace_id) OR(scope_type='organization' AND scope_id=NEW.organization_id)
 OR(scope_type='legal_entity' AND scope_id IN(NEW.seller_entity_id,NEW.buyer_entity_id,NEW.adjustment_entity_id))))=5,
 'Paired FX command requires all three current persisted entity grants and parent scopes');
 FOR period IN SELECT DISTINCT value FROM jsonb_each_text(p.payload->'period_ids') LOOP
  PERFORM 1 FROM reconforge.fiscal_periods WHERE tenant_id=NEW.tenant_id AND id=period FOR SHARE;
  PERFORM reconforge.icfx_assert(EXISTS(SELECT 1 FROM reconforge.fiscal_periods WHERE tenant_id=NEW.tenant_id AND id=period
   AND application_workspace_id=NEW.workspace_id AND status='Open'),'New native owner phase cannot cross a closed period');
 END LOOP;
 RETURN NEW;
END $icfx$;
CREATE TRIGGER current_actor BEFORE INSERT ON reconforge.intercompany_fx_commands FOR EACH ROW EXECUTE FUNCTION reconforge.icfx_command_actor();
CREATE FUNCTION reconforge.icfx_translation(t TEXT,s JSONB,book TEXT,pseq INTEGER,req JSONB) RETURNS JSONB
 LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog AS $icfx$
#variable_conflict use_variable
DECLARE q JSONB:=s->'request';cfg JSONB;roles JSONB;group_map JSONB;by_role JSONB:='{}';row JSONB;role TEXT;group_role TEXT;
 contribution JSONB;native RECORD;field TEXT;amount NUMERIC;translated NUMERIC;balance NUMERIC;total NUMERIC:=0;count_lines INTEGER:=0;
 closing_rate NUMERIC;fp INTEGER;lp INTEGER;policy JSONB;rate NUMERIC;effect_ids JSONB;accounts JSONB;result JSONB;
BEGIN
 cfg:=q->book;roles:=cfg->'accounts';group_map:=q->'adjustment'->'accounts';policy:=s->'policies'->book;
 fp:=(s->'policies'->'adjustment'->>'currency_precision')::integer;lp:=(policy->>'currency_precision')::integer;
 closing_rate:=reconforge.fx_rate(req->'closing_rates'->book,req->>'posting_date');
 FOR native IN SELECT l.posting_effect_id AS effect_id,l.entry_id,p.payload->>'posting_date' AS posting_date,
  n.line_number,n.account_id,a.account_code,n.debit_minor,n.credit_minor
  FROM reconforge.intercompany_fx_links l JOIN reconforge.intercompany_fx_plans p ON p.tenant_id=l.tenant_id AND p.id=l.plan_id
  JOIN reconforge.finance_posting_effects f ON f.tenant_id=l.tenant_id AND f.id=l.posting_effect_id
  CROSS JOIN LATERAL jsonb_to_recordset(f.snapshot_json->'lines') AS n(line_number INTEGER,account_id TEXT,debit_minor BIGINT,credit_minor BIGINT)
  JOIN reconforge.finance_accounts a ON a.tenant_id=f.tenant_id AND a.id=n.account_id
  WHERE p.tenant_id=t AND p.source_id=s->>'id' AND p.phase=2 AND p.sequence<pseq AND l.book=book ORDER BY p.sequence,n.line_number LOOP
  count_lines:=count_lines+1;PERFORM reconforge.icfx_assert(count_lines<=512,'Bounded exact translation membership exceeded');
  SELECT key INTO role FROM jsonb_each_text(roles) WHERE value=native.account_code;
  PERFORM reconforge.icfx_assert(role IS NOT NULL AND req->'income_rates'->book ? native.posting_date,
   'Every actual native contribution requires its retained account role and captured event-date reporting rate');
  rate:=reconforge.fx_rate(req->'income_rates'->book->native.posting_date,native.posting_date);
  group_role:=CASE role WHEN'party' THEN CASE book WHEN'seller' THEN'receivable' ELSE'payable' END
   WHEN'trade' THEN CASE book WHEN'seller' THEN'revenue' ELSE'expense' END ELSE role END;
  contribution:=jsonb_build_object('effect_id',native.effect_id,'entry_id',native.entry_id,'line_number',native.line_number,
   'account_id',native.account_id,'account_code',native.account_code,'posting_date',native.posting_date,
   'debit_minor',native.debit_minor,'credit_minor',native.credit_minor,'legal_entity_id',cfg->>'legal_entity_id',
   'income_rate',req->'income_rates'->book->native.posting_date);
  row:=COALESCE(by_role->role,jsonb_build_object('role',group_role,'native_account_code',native.account_code,'account_code',group_map->>group_role,
   'native_balance_minor',0,'balance_minor',0,'contributions','[]'::jsonb));
  amount:=native.debit_minor-native.credit_minor;
  row:=row||jsonb_build_object('native_balance_minor',(row->>'native_balance_minor')::numeric+amount,
   'contributions',(row->'contributions')||jsonb_build_array(contribution));
  IF role NOT IN('party','cash') THEN
   translated:=reconforge.fx_convert_inverse(abs(amount),rate,lp,fp)*CASE WHEN amount<0 THEN-1 ELSE 1 END;
   row:=row||jsonb_build_object('balance_minor',(row->>'balance_minor')::numeric+translated,'translation_method','captured-event-historical-inverse-v2');
  END IF;
  by_role:=jsonb_set(by_role,ARRAY[role],row,TRUE);
 END LOOP;
 PERFORM reconforge.icfx_assert(count_lines>0,'Translation requires the exact populated native party book');
 PERFORM reconforge.icfx_assert((SELECT count(*) FROM jsonb_each(req->'income_rates'->book))=
  (SELECT count(DISTINCT p.payload->>'posting_date') FROM reconforge.intercompany_fx_plans p JOIN reconforge.intercompany_fx_links l
   ON l.tenant_id=p.tenant_id AND l.plan_id=p.id WHERE p.tenant_id=t AND p.source_id=s->>'id' AND p.phase=2 AND p.sequence<pseq AND l.book=book),
  'Historical reporting date/rate map cannot include invented or omitted membership');
 FOR role,row IN SELECT key,value FROM jsonb_each(by_role) LOOP
  amount:=(row->>'native_balance_minor')::numeric;
  IF role IN('party','cash') THEN
   translated:=reconforge.fx_convert_inverse(abs(amount),closing_rate,lp,fp)*CASE WHEN amount<0 THEN-1 ELSE 1 END;
   row:=row||jsonb_build_object('balance_minor',translated,'translation_method','captured-monetary-closing-inverse-v2','closing_rate',req->'closing_rates'->book);
   by_role:=jsonb_set(by_role,ARRAY[role],row,TRUE);
  END IF;
  total:=total+(row->>'balance_minor')::numeric;
 END LOOP;
 SELECT jsonb_agg(effect_id ORDER BY effect_id) INTO effect_ids FROM(SELECT DISTINCT l.posting_effect_id AS effect_id
  FROM reconforge.intercompany_fx_links l JOIN reconforge.intercompany_fx_plans p ON p.tenant_id=l.tenant_id AND p.id=l.plan_id
  WHERE p.tenant_id=t AND p.source_id=s->>'id' AND p.phase=2 AND p.sequence<pseq AND l.book=book) effects;
 by_role:=by_role||jsonb_build_object('cta',jsonb_build_object('role','cta','account_code',group_map->>'cta','native_account_code',NULL,
  'native_balance_minor',NULL,'balance_minor',-total,'contributions','[]'::jsonb,'translation_method','explained-translation-balance-v2',
  'derived_from_effect_ids',effect_ids));
 SELECT jsonb_agg(value ORDER BY key) INTO accounts FROM jsonb_each(by_role);
 result:=jsonb_build_object('legal_entity_id',cfg->>'legal_entity_id','functional_policy',policy,'reporting_policy',s->'policies'->'adjustment',
  'closing_rate',req->'closing_rates'->book,'cta_minor',total,'accounts',accounts,'effect_ids',effect_ids);
 RETURN result||jsonb_build_object('translation_digest',reconforge.irp_digest(result));
END $icfx$;
CREATE FUNCTION reconforge.icfx_close(t TEXT,i TEXT) RETURNS VOID LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog AS $icfx$
#variable_conflict use_variable
DECLARE p RECORD;s RECORD;r RECORD;l RECORD;f RECORD;e RECORD;j RECORD;post_event RECORD;previous RECORD;command RECORD;original RECORD;
 a JSONB;q JSONB;v JSONB;req JSONB;eq JSONB;books JSONB:='{}';positions JSONB:='{}';rows JSONB;cfg JSONB;pol JSONB;item JSONB;
 book TEXT;role TEXT;expected_type TEXT;field TEXT;policy_fields TEXT[]:=ARRAY['currency_code','currency_precision','currency_rounding_policy','currency_registry_version','currency_registry_digest'];
 gross NUMERIC;paid NUMERIC:=0;amount NUMERIC:=0;original_amount NUMERIC;historical NUMERIC;release NUMERIC;cash NUMERIC;gain NUMERIC;delta NUMERIC;
 carrying NUMERIC;valued NUMERIC;rate NUMERIC;closing NUMERIC;lp INTEGER;fp INTEGER;seq INTEGER:=0;settlements INTEGER:=0;active TEXT;closed BOOLEAN:=FALSE;last_day TEXT;
 expected_eq JSONB;expected_translations JSONB:='{}';translation JSONB;trade_a NUMERIC;trade_b NUMERIC;residual_a NUMERIC;residual_b NUMERIC;
 head JSONB;native_lines JSONB;count_entries INTEGER:=0;count_links INTEGER;expected_number TEXT;expected_effect TEXT;
BEGIN
 SELECT* INTO p FROM reconforge.intercompany_fx_plans WHERE tenant_id=t AND id=i;
 IF p.id IS NULL THEN RETURN;END IF;
 SELECT* INTO s FROM reconforge.intercompany_fx_sources WHERE tenant_id=t AND id=p.source_id;
 SELECT* INTO r FROM reconforge.intercompany_fx_reviews WHERE tenant_id=t AND plan_id=i;
 SELECT* INTO post_event FROM reconforge.intercompany_fx_post_evidence WHERE tenant_id=t AND plan_id=i;
 a:=s.payload;q:=a->'request';v:=p.payload;eq:=v->'equation';req:=v->'command_request';
 PERFORM reconforge.icfx_assert(reconforge.fx_object(a,ARRAY['schema_version','id','request','policies','original_positions','native_accounts','preparer_actor_id','source_digest'])
 AND reconforge.fx_object(q,ARRAY['workspace_id','organization_id','organization_code','reference','transaction_currency_code','transaction_minor','posting_date','reason','seller','buyer','adjustment','seller_original_rate','buyer_original_rate'])
 AND reconforge.fx_object(a->'policies',ARRAY['transaction','seller','buyer','adjustment'])
 AND reconforge.fx_object(a->'original_positions',ARRAY['seller','buyer'])
 AND reconforge.fx_object(a->'native_accounts',ARRAY['seller','buyer','adjustment'])
 AND reconforge.fx_object(v,ARRAY['schema_version','id','source_id','workspace_id','organization_id','seller_entity_id','buyer_entity_id','adjustment_entity_id',
 'kind','sequence','period_ids','posting_date','reason','source_digest','equation','entries','preparer_actor_id','command_request','plan_digest']),
 'Paired FX source and native plan require closed versioned schemas');
 PERFORM reconforge.icfx_assert(a->>'schema_version'='intercompany-fx-source-v2' AND v->>'schema_version'='intercompany-fx-plan-v2'
 AND a->>'id'=s.id AND s.id~'^IC2S-[a-f0-9]{32}$' AND p.id~'^IC2[SRE]?-[a-f0-9]{32}$'
 AND a->>'source_digest'=reconforge.irp_digest(a-'source_digest') AND v->>'plan_digest'=reconforge.irp_digest(v-'plan_digest')
 AND v->>'source_digest'=a->>'source_digest'
 AND(q->>'workspace_id',q->>'organization_id',q->'seller'->>'legal_entity_id',q->'buyer'->>'legal_entity_id',q->'adjustment'->>'legal_entity_id',q->>'reference')
 =(s.workspace_id,s.organization_id,s.seller_entity_id,s.buyer_entity_id,s.adjustment_entity_id,s.reference)
 AND(v->>'id',v->>'source_id',v->>'workspace_id',v->>'organization_id',v->>'seller_entity_id',v->>'buyer_entity_id',v->>'adjustment_entity_id',v->>'kind')
 =(p.id,p.source_id,p.workspace_id,p.organization_id,p.seller_entity_id,p.buyer_entity_id,p.adjustment_entity_id,p.kind)
 AND(p.workspace_id,p.organization_id,p.seller_entity_id,p.buyer_entity_id,p.adjustment_entity_id)
 =(s.workspace_id,s.organization_id,s.seller_entity_id,s.buyer_entity_id,s.adjustment_entity_id)
 AND(v->>'sequence')::integer=p.sequence AND reconforge.fx_minor(q->'transaction_minor') AND(q->>'transaction_minor')::numeric<=4500000000000000000
 AND q->'seller'->>'currency_code'<>q->'buyer'->>'currency_code'
 AND reconforge.fx_object(v->'period_ids',ARRAY['seller','buyer','adjustment']) AND req->'period_ids'=v->'period_ids'
 AND req->>'kind'=p.kind AND req->>'posting_date'=v->>'posting_date' AND req->>'reason'=v->>'reason',
 'Original identities, currencies, periods and captured command cannot diverge');
 PERFORM reconforge.icfx_assert(p.id LIKE CASE p.kind WHEN'recognize' THEN'IC2-%' WHEN'settle' THEN'IC2S-%'
 WHEN'eliminate' THEN'IC2E-%' ELSE'IC2R-%' END AND reconforge.fx_object(req,CASE p.kind
 WHEN'recognize' THEN ARRAY['kind','posting_date','reason','period_ids','original_request']
 WHEN'settle' THEN ARRAY['kind','transaction_minor','rates','period_ids','posting_date','reason','source_id']
 WHEN'revalue' THEN ARRAY['kind','rates','period_ids','posting_date','reason','source_id']
 WHEN'reverse_revaluation' THEN ARRAY['kind','original_revaluation_id','period_ids','posting_date','reason','source_id']
 ELSE ARRAY['kind','closing_rates','income_rates','period_ids','posting_date','reason','source_id'] END)
 AND(p.kind='recognize' OR req->>'source_id'=s.id),'Operation prefix and exact captured request must retain its owner');
 IF p.kind IN('settle','revalue') THEN
  PERFORM reconforge.icfx_assert(reconforge.fx_object(req->'rates',ARRAY['seller','buyer']),'Both party rates must be explicitly retained');
 ELSIF p.kind='eliminate' THEN
  PERFORM reconforge.icfx_assert(reconforge.fx_object(req->'closing_rates',ARRAY['seller','buyer'])
   AND reconforge.fx_object(req->'income_rates',ARRAY['seller','buyer']),'Closing and income rates must retain both books');
 END IF;
 FOREACH book IN ARRAY ARRAY['transaction','seller','buyer','adjustment'] LOOP
  PERFORM reconforge.icfx_assert(reconforge.fx_policy(t,a->'policies'->book)
   AND a->'policies'->book->>'currency_registry_digest'=a->'policies'->'transaction'->>'currency_registry_digest',
   'Each exact currency retains the same workspace registry snapshot, not the same currency');
 END LOOP;
 PERFORM reconforge.icfx_assert(a->'policies'->'transaction'->>'currency_code'=q->>'transaction_currency_code'
 AND (q->>'posting_date')::date::text=q->>'posting_date' AND(v->>'posting_date')::date::text=v->>'posting_date'
 AND reconforge.irp_text(q->>'reason',500) AND reconforge.irp_text(v->>'reason',500),'Explicit dates and retained provenance are required');
 FOREACH book IN ARRAY ARRAY['seller','buyer','adjustment'] LOOP
  cfg:=q->book;pol:=a->'policies'->book;
  PERFORM reconforge.icfx_assert(reconforge.fx_object(cfg,ARRAY['legal_entity_id','entity_code','currency_code','journal_code','period_id','accounts'])
   AND cfg->>'currency_code'=pol->>'currency_code'
   AND EXISTS(SELECT 1 FROM reconforge.legal_entities le JOIN reconforge.organizations o ON o.tenant_id=le.tenant_id AND o.id=le.organization_id
    WHERE le.tenant_id=t AND le.id=cfg->>'legal_entity_id' AND le.entity_code=cfg->>'entity_code' AND le.currency_code=cfg->>'currency_code'
    AND le.organization_id=s.organization_id AND o.organization_code=q->>'organization_code' AND o.application_workspace_id=s.workspace_id),
   'Each original party and reporting entity retains its own native currency and organization');
  PERFORM reconforge.icfx_assert(reconforge.fx_object(cfg->'accounts',CASE WHEN book='adjustment' THEN ARRAY['receivable','payable','revenue','expense','cash','realized_gain','realized_loss','unrealized_gain','unrealized_loss','cta']
   ELSE ARRAY['party','trade','cash','realized_gain','realized_loss','unrealized_gain','unrealized_loss'] END)
   AND(SELECT count(DISTINCT value) FROM jsonb_each_text(cfg->'accounts'))=(CASE WHEN book='adjustment' THEN 10 ELSE 7 END),
   'Every retained party and group account role is distinct and explicit');
  PERFORM reconforge.icfx_assert(reconforge.fx_object(a->'native_accounts'->book,CASE WHEN book='adjustment' THEN
   ARRAY['receivable','payable','revenue','expense','cash','realized_gain','realized_loss','unrealized_gain','unrealized_loss','cta']
   ELSE ARRAY['party','trade','cash','realized_gain','realized_loss','unrealized_gain','unrealized_loss'] END),
   'The frozen native account map must include every explicit role');
  FOR role,item IN SELECT key,value FROM jsonb_each(a->'native_accounts'->book) LOOP
   expected_type:=CASE WHEN role IN('cash','receivable') OR(role='party' AND book='seller') THEN'Asset'
    WHEN role='payable' OR(role='party' AND book='buyer') THEN'Liability'
    WHEN role IN('revenue','realized_gain','unrealized_gain') OR(role='trade' AND book='seller') THEN'Income'
    WHEN role='cta' THEN'Equity' ELSE'Expense' END;
   PERFORM reconforge.icfx_assert(reconforge.fx_object(item,ARRAY['id','account_code','account_type','chart_id'])
    AND item->>'account_code'=cfg->'accounts'->>role AND item->>'account_type'=expected_type
    AND EXISTS(SELECT 1 FROM reconforge.finance_accounts ac JOIN reconforge.finance_journals mapped_journal ON mapped_journal.tenant_id=ac.tenant_id AND mapped_journal.chart_id=ac.chart_id
     WHERE ac.tenant_id=t AND ac.id=item->>'id' AND ac.account_code=item->>'account_code' AND ac.account_type=expected_type AND ac.chart_id=item->>'chart_id'
     AND ac.workspace_id=s.workspace_id AND mapped_journal.workspace_id=s.workspace_id AND mapped_journal.organization_code=q->>'organization_code'
     AND mapped_journal.journal_code=cfg->>'journal_code' AND mapped_journal.currency_code=cfg->>'currency_code'), 'Frozen native account maps cannot be forged or relabelled');
  END LOOP;
 END LOOP;
 gross:=(q->>'transaction_minor')::numeric;last_day:=q->>'posting_date';fp:=(a->'policies'->'transaction'->>'currency_precision')::integer;
 FOR previous IN SELECT* FROM reconforge.intercompany_fx_plans WHERE tenant_id=t AND source_id=s.id AND sequence<p.sequence ORDER BY sequence LOOP
  PERFORM reconforge.icfx_assert(previous.sequence=seq AND previous.phase=2 AND NOT closed AND previous.payload->>'posting_date'>=last_day,
   'Every earlier operation must be contiguous, completely posted and date-ordered');
  IF previous.kind='settle' THEN paid:=paid+(previous.payload->'equation'->>'transaction_minor')::numeric;settlements:=settlements+1;END IF;
  IF previous.kind='revalue' THEN active:=previous.id;END IF;
  IF previous.kind='reverse_revaluation' THEN active:=NULL;END IF;
  IF previous.kind='eliminate' THEN closed:=TRUE;END IF;
  seq:=seq+1;last_day:=previous.payload->>'posting_date';
 END LOOP;
 PERFORM reconforge.icfx_assert(seq=p.sequence AND NOT closed AND v->>'posting_date'>=last_day
  AND(p.sequence=0)=(p.kind='recognize') AND paid BETWEEN 0 AND gross
  AND(active IS NULL OR p.kind IN('reverse_revaluation','eliminate')),
  'Exact original residual and active closing observation cannot be bypassed');
 IF p.kind IN('recognize','settle','revalue') THEN
  FOREACH book IN ARRAY ARRAY['seller','buyer'] LOOP
   cfg:=q->book;pol:=a->'policies'->book;lp:=(pol->>'currency_precision')::integer;
   rate:=reconforge.fx_rate(q->(book||'_original_rate'),q->>'posting_date');original_amount:=reconforge.fx_convert(gross,rate,fp,lp);
   PERFORM reconforge.icfx_assert(a->'original_positions'->book=jsonb_build_object('original_functional_minor',original_amount,'amount_minor',original_amount)
    AND original_amount BETWEEN 1 AND 4500000000000000000,'Original functional carrying amount requires the canonical captured historical rate');
   IF p.kind='recognize' THEN
    PERFORM reconforge.icfx_assert(req->'original_request'=q,'Original preparation request must equal the source');
    rows:=CASE book WHEN'seller' THEN jsonb_build_array(reconforge.icfx_line(cfg->'accounts'->>'party',original_amount,0),reconforge.icfx_line(cfg->'accounts'->>'trade',0,original_amount))
     ELSE jsonb_build_array(reconforge.icfx_line(cfg->'accounts'->>'trade',original_amount,0),reconforge.icfx_line(cfg->'accounts'->>'party',0,original_amount)) END;
    positions:=positions||jsonb_build_object(book,jsonb_build_object('original_functional_minor',original_amount,'amount_minor',original_amount));
   ELSIF p.kind='settle' THEN
    amount:=(req->>'transaction_minor')::numeric;
    PERFORM reconforge.icfx_assert(reconforge.fx_minor(req->'transaction_minor') AND amount>0 AND paid+amount<=gross AND settlements<32,'Foreign settlement exceeds its exact original residual or declared bound');
    historical:=reconforge.fx_convert(paid,rate,fp,lp);release:=reconforge.fx_convert(paid+amount,rate,fp,lp)-historical;
    cash:=reconforge.fx_convert(amount,reconforge.fx_rate(req->'rates'->book,v->>'posting_date'),fp,lp);
    gain:=CASE book WHEN'seller' THEN cash-release ELSE release-cash END;
    rows:=jsonb_build_array(CASE book WHEN'seller' THEN reconforge.icfx_line(cfg->'accounts'->>'cash',cash,0) ELSE reconforge.icfx_line(cfg->'accounts'->>'cash',0,cash) END);
    IF release>0 THEN rows:=rows||jsonb_build_array(CASE book WHEN'seller' THEN reconforge.icfx_line(cfg->'accounts'->>'party',0,release) ELSE reconforge.icfx_line(cfg->'accounts'->>'party',release,0) END);END IF;
    IF gain<>0 THEN rows:=rows||jsonb_build_array(reconforge.icfx_line(cfg->'accounts'->>CASE WHEN gain>0 THEN'realized_gain' ELSE'realized_loss' END,greatest(-gain,0),greatest(gain,0)));END IF;
    positions:=positions||jsonb_build_object(book,jsonb_build_object('historical_before_minor',historical,'historical_release_minor',release,'historical_after_minor',historical+release,
     'functional_cash_minor',cash,'realized_fx_minor',gain,'rate',req->'rates'->book,'amount_minor',(SELECT sum((x->>'debit_minor')::numeric) FROM jsonb_array_elements(rows)x)));
   ELSE
    PERFORM reconforge.icfx_assert(gross>paid,'Closing valuation requires an outstanding foreign monetary item');
    carrying:=original_amount-reconforge.fx_convert(paid,rate,fp,lp);
    valued:=reconforge.fx_convert(gross-paid,reconforge.fx_rate(req->'rates'->book,v->>'posting_date'),fp,lp);delta:=valued-carrying;
    gain:=CASE book WHEN'seller' THEN delta ELSE-delta END;rows:='[]';
    IF delta<>0 THEN rows:=jsonb_build_array(CASE book WHEN'seller' THEN reconforge.icfx_line(cfg->'accounts'->>'party',greatest(delta,0),greatest(-delta,0))
     ELSE reconforge.icfx_line(cfg->'accounts'->>'party',greatest(-delta,0),greatest(delta,0)) END,
     reconforge.icfx_line(cfg->'accounts'->>CASE WHEN gain>0 THEN'unrealized_gain' ELSE'unrealized_loss' END,greatest(-gain,0),greatest(gain,0)));END IF;
    positions:=positions||jsonb_build_object(book,jsonb_build_object('historical_outstanding_minor',carrying,'valued_outstanding_minor',valued,'unrealized_fx_minor',gain,
     'rate',req->'rates'->book,'amount_minor',abs(delta)));
   END IF;
   IF jsonb_array_length(rows)>0 THEN books:=books||jsonb_build_object(book,rows);END IF;
  END LOOP;
  expected_eq:=CASE p.kind WHEN'recognize' THEN jsonb_build_object('kind',p.kind,'transaction_minor',gross,'policies',a->'policies','books',books,'positions',positions)
   WHEN'settle' THEN jsonb_build_object('kind',p.kind,'transaction_before_minor',paid,'transaction_minor',amount,'transaction_after_minor',paid+amount,'books',books,'positions',positions)
   ELSE jsonb_build_object('kind',p.kind,'transaction_before_minor',paid,'transaction_outstanding_minor',gross-paid,'books',books,'positions',positions) END;
 ELSIF p.kind='reverse_revaluation' THEN
  SELECT* INTO original FROM reconforge.intercompany_fx_plans WHERE tenant_id=t AND id=active AND source_id=s.id AND kind='revalue' AND phase=2;
  PERFORM reconforge.icfx_assert(original.id IS NOT NULL AND req->>'original_revaluation_id'=original.id,'A valuation inverse requires its exact active posted original');
  FOR book,rows IN SELECT key,value FROM jsonb_each(original.payload->'equation'->'books') LOOP
   SELECT jsonb_agg(reconforge.icfx_line(x->>'account_code',(x->>'credit_minor')::numeric,(x->>'debit_minor')::numeric) ORDER BY ordinal)
    INTO rows FROM jsonb_array_elements(rows) WITH ORDINALITY elements(x,ordinal);
   books:=books||jsonb_build_object(book,rows);positions:=positions||jsonb_build_object(book,jsonb_build_object('amount_minor',(SELECT sum((x->>'debit_minor')::numeric) FROM jsonb_array_elements(rows)x)));
  END LOOP;
  expected_eq:=jsonb_build_object('kind',p.kind,'original_revaluation_id',original.id,'original_plan_digest',original.payload->>'plan_digest',
   'original_posting_effect_ids',(SELECT jsonb_object_agg(links.book,links.posting_effect_id) FROM reconforge.intercompany_fx_links links WHERE links.tenant_id=t AND links.plan_id=original.id),
   'books',books,'positions',positions);
 ELSE
  FOREACH book IN ARRAY ARRAY['seller','buyer'] LOOP
   translation:=reconforge.icfx_translation(t,a,book,p.sequence,req);expected_translations:=expected_translations||jsonb_build_object(book,translation);
  END LOOP;
  SELECT -(x->>'balance_minor')::numeric INTO trade_a FROM jsonb_array_elements(expected_translations->'seller'->'accounts')x WHERE x->>'role'='revenue';
  SELECT(x->>'balance_minor')::numeric INTO trade_b FROM jsonb_array_elements(expected_translations->'buyer'->'accounts')x WHERE x->>'role'='expense';
  SELECT(x->>'balance_minor')::numeric INTO residual_a FROM jsonb_array_elements(expected_translations->'seller'->'accounts')x WHERE x->>'role'='receivable';
  SELECT-(x->>'balance_minor')::numeric INTO residual_b FROM jsonb_array_elements(expected_translations->'buyer'->'accounts')x WHERE x->>'role'='payable';
  PERFORM reconforge.icfx_assert(trade_a=trade_b AND residual_a=residual_b AND trade_a>0 AND residual_a>=0,
   'Native elimination cannot invent unequal translated original or residual balances');
  cfg:=q->'adjustment';rows:=jsonb_build_array(reconforge.icfx_line(cfg->'accounts'->>'revenue',trade_a,0),reconforge.icfx_line(cfg->'accounts'->>'expense',0,trade_b));
  IF residual_a>0 THEN rows:=rows||jsonb_build_array(reconforge.icfx_line(cfg->'accounts'->>'payable',residual_b,0),reconforge.icfx_line(cfg->'accounts'->>'receivable',0,residual_a));END IF;
  books:=jsonb_build_object('adjustment',rows);positions:=jsonb_build_object('adjustment',jsonb_build_object('amount_minor',trade_a+residual_a));
  expected_eq:=jsonb_build_object('kind',p.kind,'translated_trade_minor',trade_a,'translated_residual_minor',residual_a,
   'translation_digests',jsonb_build_object('seller',expected_translations->'seller'->>'translation_digest','buyer',expected_translations->'buyer'->>'translation_digest'),
   'native_membership',jsonb_build_object('seller',expected_translations->'seller'->'effect_ids','buyer',expected_translations->'buyer'->'effect_ids'),
   'books',books,'positions',positions,'translations',expected_translations);
 END IF;
 PERFORM reconforge.icfx_assert(eq=expected_eq AND books<>'{}'::jsonb,'Independent canonical FX, residual, translation, CTA and native elimination equations differ');
 FOR item IN SELECT value FROM jsonb_array_elements(v->'entries') LOOP
  book:=item->>'book';cfg:=q->book;pol:=a->'policies'->book;count_entries:=count_entries+1;
  PERFORM reconforge.icfx_assert(books ? book AND reconforge.fx_object(item,ARRAY['book','entry_id','snapshot','validation_digest','reverses_effect_id'])
   AND item->>'validation_digest'=reconforge.irp_digest(item->'snapshot'),'Each exact source-owned native book requires its original complete snapshot');
  SELECT* INTO e FROM reconforge.finance_entries WHERE tenant_id=t AND id=item->>'entry_id';
  SELECT* INTO j FROM reconforge.finance_journals WHERE tenant_id=t AND id=e.journal_id;
  expected_number:=upper(p.id)||'-'||CASE book WHEN'seller' THEN'A' WHEN'buyer' THEN'B' ELSE'G' END;
  expected_effect:=CASE WHEN p.kind='reverse_revaluation' THEN expected_eq->'original_posting_effect_ids'->>book ELSE NULL END;
  PERFORM reconforge.icfx_assert(e.id IS NOT NULL AND e.entry_number=expected_number AND e.workspace_id=s.workspace_id
   AND e.organization_code=q->>'organization_code' AND e.entity_code=cfg->>'entity_code' AND e.period_id=v->'period_ids'->>book
   AND e.posting_date=v->>'posting_date' AND e.description=v->>'reason' AND e.preparer_actor_id=v->>'preparer_actor_id'
   AND j.journal_code=cfg->>'journal_code' AND e.reverses_posting_id IS NOT DISTINCT FROM expected_effect
   AND item->>'reverses_effect_id' IS NOT DISTINCT FROM expected_effect
   AND e.source_type=CASE WHEN p.kind='reverse_revaluation' THEN'Generated' ELSE'Manual' END
   AND e.external_reference=CASE WHEN p.kind='reverse_revaluation' THEN expected_effect ELSE'IC2:'||s.id||':'||p.kind END
   AND (e.currency_code,e.currency_precision::text,e.currency_rounding_policy,e.currency_registry_version,e.currency_registry_digest)
   =(pol->>'currency_code',pol->>'currency_precision',pol->>'currency_rounding_policy',pol->>'currency_registry_version',pol->>'currency_registry_digest'),
   'Native party identity, period, policy and exact source inverse cannot diverge');
  SELECT jsonb_agg(jsonb_build_object('account_code',ac.account_code,'debit_minor',n.debit_minor,'credit_minor',n.credit_minor) ORDER BY n.line_number)
   INTO native_lines FROM reconforge.finance_entry_lines n JOIN reconforge.finance_accounts ac ON ac.tenant_id=n.tenant_id AND ac.id=n.account_id WHERE n.tenant_id=t AND n.entry_id=e.id;
  PERFORM reconforge.icfx_assert(native_lines=books->book AND e.total_debit_minor=e.total_credit_minor
   AND e.total_debit_minor=(SELECT sum((x->>'debit_minor')::numeric) FROM jsonb_array_elements(books->book)x)
   AND e.total_debit_minor BETWEEN 1 AND 9000000000000000000,'Every native original, settlement and inverse conserves its own functional currency');
  SELECT jsonb_object_agg(key,value) INTO head FROM jsonb_each(to_jsonb(e)) WHERE key=ANY(ARRAY['id','workspace_id','journal_id','period_id','entry_number','posting_date','description','external_reference','source_type',
   'currency_code','currency_precision','currency_rounding_policy','currency_registry_version','currency_registry_digest','preparer_actor_id','reverses_posting_id']);
  head:=head||jsonb_build_object('organization_id',s.organization_id,'legal_entity_id',cfg->>'legal_entity_id');
  SELECT jsonb_agg(jsonb_build_object('line_number',n.line_number,'account_id',n.account_id,'description',n.description,'debit_minor',n.debit_minor,'credit_minor',n.credit_minor,
   'dimensions',COALESCE((SELECT jsonb_object_agg(d.dimension_id,d.dimension_value_id) FROM reconforge.finance_entry_line_dimensions d WHERE d.tenant_id=n.tenant_id AND d.entry_line_id=n.id),'{}'::jsonb)) ORDER BY n.line_number)
   INTO native_lines FROM reconforge.finance_entry_lines n WHERE n.tenant_id=t AND n.entry_id=e.id;
  PERFORM reconforge.icfx_assert(item->'snapshot'=jsonb_build_object('schema_version','finance-entry-review-v1','entry',head,'lines',native_lines),'Complete original dimensions and native line snapshots must retain their exact source');
  SELECT links.* INTO l FROM reconforge.intercompany_fx_links links WHERE links.tenant_id=t AND links.plan_id=i AND links.book=item->>'book';
  SELECT* INTO f FROM reconforge.finance_posting_effects WHERE tenant_id=t AND entry_id=e.id;
  IF p.phase=0 THEN
   PERFORM reconforge.icfx_assert(e.status='Draft' AND e.validation_digest IS NULL AND r.plan_id IS NULL AND l.plan_id IS NULL AND f.id IS NULL,'Prepared operation cannot contain detached review or partial native effects');
  ELSE
   PERFORM reconforge.icfx_assert(r.plan_id IS NOT NULL AND r.reviewer_actor_id<>v->>'preparer_actor_id' AND e.status='Validated'
    AND e.validator_actor_id=r.reviewer_actor_id AND e.validation_digest=item->>'validation_digest','Independent review must seal every exact native party book');
   IF p.phase=1 THEN PERFORM reconforge.icfx_assert(l.plan_id IS NULL AND f.id IS NULL,'Reviewed operation cannot retain half of a native effect pair');
   ELSE PERFORM reconforge.icfx_assert(l.plan_id IS NOT NULL AND f.id=l.posting_effect_id AND l.entry_id=e.id
    AND l.posted_actor_id=f.posted_actor_id AND l.posted_actor_id NOT IN(v->>'preparer_actor_id',r.reviewer_actor_id)
    AND f.snapshot_json=item->'snapshot' AND f.validation_digest=item->>'validation_digest'
    AND f.source_kind=CASE WHEN expected_effect IS NULL THEN'Manual' ELSE'Reversal' END
    AND f.reverses_effect_id IS NOT DISTINCT FROM expected_effect,'Every paired publication must include its exact native effect and third human');END IF;
  END IF;
 END LOOP;
 PERFORM reconforge.icfx_assert(count_entries=(SELECT count(*) FROM jsonb_each(books))
  AND(SELECT count(DISTINCT x->>'book') FROM jsonb_array_elements(v->'entries')x)=count_entries,
  'Exact native effect membership cannot omit or duplicate a party');
 SELECT count(*) INTO count_links FROM reconforge.intercompany_fx_links WHERE tenant_id=t AND plan_id=i;
 PERFORM reconforge.icfx_assert(count_links=CASE WHEN p.phase=2 THEN count_entries ELSE 0 END
  AND reconforge.icfx_event(t,i,p.audit_event_id,p.outbox_event_id,v->>'preparer_actor_id','intercompany_fx_prepared',jsonb_build_object('plan_digest',v->>'plan_digest')),
  'Native membership, audit and outbox preparation evidence must close atomically');
 IF p.phase>0 THEN PERFORM reconforge.icfx_assert(reconforge.icfx_event(t,i,r.audit_event_id,r.outbox_event_id,r.reviewer_actor_id,'intercompany_fx_reviewed',jsonb_build_object('plan_digest',v->>'plan_digest')),
  'Independent review audit and outbox differ');END IF;
 IF p.phase=2 THEN PERFORM reconforge.icfx_assert(post_event.plan_id IS NOT NULL
  AND(SELECT count(DISTINCT posted_actor_id) FROM reconforge.intercompany_fx_links WHERE tenant_id=t AND plan_id=i)=1
  AND reconforge.icfx_event(t,i,post_event.audit_event_id,post_event.outbox_event_id,l.posted_actor_id,'intercompany_fx_posted',jsonb_build_object('plan_digest',v->>'plan_digest')),
  'Whole publication requires the exact third-human audit and outbox');
 ELSE PERFORM reconforge.icfx_assert(post_event.plan_id IS NULL,'Unposted plans cannot claim final evidence');END IF;
 PERFORM reconforge.icfx_assert((SELECT count(*) FROM reconforge.intercompany_fx_commands WHERE tenant_id=t AND plan_id=i)=p.phase+1,'Every phase retains its exact original command acknowledgement');
 FOR command IN SELECT* FROM reconforge.intercompany_fx_commands WHERE tenant_id=t AND plan_id=i LOOP
  PERFORM reconforge.icfx_assert(command.request_digest=reconforge.irp_digest(command.request_json)
   AND reconforge.fx_object(command.request_json,ARRAY['operation','actor_id','request'])
   AND command.request_json->>'operation'=command.operation AND command.request_json->>'actor_id'=command.actor_id
   AND command.response_json-'phase'-'status'-'reviewer_actor_id'-'posted_actor_id'-'posting_effect_ids'=v
   AND(command.response_json->>'phase')::integer=CASE command.operation WHEN'prepare' THEN 0 WHEN'review' THEN 1 ELSE 2 END
   AND command.response_json->>'status'=CASE command.operation WHEN'prepare' THEN'Prepared' WHEN'review' THEN'Reviewed' ELSE'Posted' END
   AND(command.workspace_id,command.organization_id,command.seller_entity_id,command.buyer_entity_id,command.adjustment_entity_id)
   =(s.workspace_id,s.organization_id,s.seller_entity_id,s.buyer_entity_id,s.adjustment_entity_id),'Original acknowledgement cannot diverge from immutable actor, source or phase');
  IF command.operation='prepare' THEN PERFORM reconforge.icfx_assert(command.actor_id=v->>'preparer_actor_id' AND command.request_json->'request'=req
   AND command.response_json->'reviewer_actor_id'='null'::jsonb AND command.response_json->'posted_actor_id'='null'::jsonb
   AND command.response_json->'posting_effect_ids'='{}'::jsonb,'Preparation acknowledgement differs');
  ELSE PERFORM reconforge.icfx_assert(command.request_json->'request'->>'plan_id'=i AND command.request_json->'request'->>'expected_plan_digest'=v->>'plan_digest'
   AND command.response_json->>'reviewer_actor_id'=r.reviewer_actor_id,'Retained reviewed digest must match');
   IF command.operation='review' THEN PERFORM reconforge.icfx_assert(command.actor_id=r.reviewer_actor_id AND command.request_json->'request'->>'reason'=r.reason
    AND command.response_json->'posted_actor_id'='null'::jsonb AND command.response_json->'posting_effect_ids'='{}'::jsonb,'Review acknowledgement differs');
   ELSE PERFORM reconforge.icfx_assert(command.actor_id=l.posted_actor_id AND command.request_json->'request'->>'reason'=l.reason
    AND command.response_json->>'posted_actor_id'=l.posted_actor_id AND command.response_json->'posting_effect_ids'=(SELECT jsonb_object_agg(links.book,links.posting_effect_id) FROM reconforge.intercompany_fx_links links WHERE links.tenant_id=t AND links.plan_id=i),
    'Publication acknowledgement requires the exact complete original effect population');END IF;
  END IF;
 END LOOP;
END $icfx$;
CREATE FUNCTION reconforge.icfx_reverse_close() RETURNS trigger LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog AS $icfx$
DECLARE changed JSONB;entry TEXT;original TEXT;number TEXT;plan RECORD;selected TEXT;inverse RECORD;original_number TEXT;original_entry TEXT;
BEGIN
 FOR changed IN SELECT value FROM jsonb_array_elements(CASE TG_OP WHEN'INSERT' THEN jsonb_build_array(to_jsonb(NEW)) WHEN'DELETE' THEN jsonb_build_array(to_jsonb(OLD)) ELSE jsonb_build_array(to_jsonb(OLD),to_jsonb(NEW)) END) LOOP
  selected:=changed->>'tenant_id';entry:=NULL;original:=NULL;
  IF TG_TABLE_NAME='finance_entries' THEN entry:=changed->>'id';original:=changed->>'reverses_posting_id';
  ELSIF TG_TABLE_NAME IN('finance_entry_lines','finance_posting_effects') THEN entry:=changed->>'entry_id';original:=changed->>'reverses_effect_id';
  ELSIF TG_TABLE_NAME='finance_entry_line_dimensions' THEN SELECT entry_id INTO entry FROM reconforge.finance_entry_lines WHERE tenant_id=selected AND id=changed->>'entry_line_id';END IF;
  original_number:=NULL;original_entry:=NULL;
  IF original IS NOT NULL THEN SELECT e.entry_number,e.id INTO original_number,original_entry FROM reconforge.finance_posting_effects f
   JOIN reconforge.finance_entries e ON e.tenant_id=f.tenant_id AND e.id=f.entry_id WHERE f.tenant_id=selected AND f.id=original;END IF;
  IF original IS NOT NULL AND(upper(coalesce(original_number,''))~'^IC2[SRE]?-' OR upper(coalesce(original_entry,''))~'^IC2[SRE]?-') THEN
   PERFORM reconforge.icfx_assert(EXISTS(SELECT 1 FROM reconforge.intercompany_fx_links WHERE tenant_id=selected AND posting_effect_id=original),
    'A reserved native original effect requires its exact paired owner');
   SELECT* INTO inverse FROM reconforge.intercompany_fx_plans p WHERE p.tenant_id=selected AND p.kind='reverse_revaluation'
    AND EXISTS(SELECT 1 FROM jsonb_array_elements(p.payload->'entries')x WHERE x->>'entry_id'=entry AND x->>'reverses_effect_id'=original);
   PERFORM reconforge.icfx_assert(inverse.id IS NOT NULL,'A detached native inverse cannot bypass the exact reviewed paired closing owner');
   PERFORM reconforge.icfx_close(selected,inverse.id);
  END IF;
  IF TG_TABLE_NAME IN('finance_entries','finance_entry_lines','finance_entry_line_dimensions','finance_posting_effects') THEN
   IF entry IS NULL THEN CONTINUE;END IF;SELECT entry_number INTO number FROM reconforge.finance_entries WHERE tenant_id=selected AND id=entry;
   IF upper(coalesce(number,''))!~'^IC2[SRE]?-' AND upper(coalesce(entry,''))!~'^IC2[SRE]?-' AND NOT(TG_TABLE_NAME='finance_entries' AND upper(coalesce(changed->>'entry_number',''))~'^IC2[SRE]?-') THEN CONTINUE;END IF;
   SELECT* INTO plan FROM reconforge.intercompany_fx_plans p WHERE p.tenant_id=selected AND EXISTS(SELECT 1 FROM jsonb_array_elements(p.payload->'entries')x WHERE x->>'entry_id'=entry);
   PERFORM reconforge.icfx_assert(plan.id IS NOT NULL,'The IC2 namespace requires its complete source owner');PERFORM reconforge.icfx_close(selected,plan.id);CONTINUE;
  END IF;
  IF TG_TABLE_NAME='intercompany_fx_sources' THEN PERFORM reconforge.icfx_assert(EXISTS(SELECT 1 FROM reconforge.intercompany_fx_plans WHERE tenant_id=selected AND source_id=changed->>'id' AND sequence=0 AND kind='recognize'),
   'Original paired trade must retain its complete recognition');END IF;
  IF TG_TABLE_NAME IN('finance_accounts','finance_journals','fiscal_periods','legal_entities') THEN
   IF NOT EXISTS(SELECT 1 FROM reconforge.finance_entries e WHERE e.tenant_id=selected AND e.entry_number~'^IC2[SRE]?-' AND
    ((TG_TABLE_NAME='finance_journals' AND e.journal_id=changed->>'id') OR(TG_TABLE_NAME='fiscal_periods' AND e.period_id=changed->>'id')
    OR(TG_TABLE_NAME='finance_accounts' AND EXISTS(SELECT 1 FROM reconforge.finance_entry_lines n WHERE n.tenant_id=e.tenant_id AND n.entry_id=e.id AND n.account_id=changed->>'id'))
    OR(TG_TABLE_NAME='legal_entities' AND e.entity_code=changed->>'entity_code'))) THEN CONTINUE;END IF;
   FOR plan IN SELECT* FROM reconforge.intercompany_fx_plans WHERE tenant_id=selected LOOP PERFORM reconforge.icfx_close(selected,plan.id);END LOOP;CONTINUE;
  END IF;
  IF TG_TABLE_NAME IN('domain_audit_events','outbox_events') AND coalesce(changed->>'object_id',changed->>'aggregate_id','')!~'^IC2[SRE]?-' THEN CONTINUE;END IF;
  FOR plan IN SELECT* FROM reconforge.intercompany_fx_plans p WHERE p.tenant_id=selected AND(p.id=changed->>'plan_id' OR p.id=changed->>'id' OR p.source_id=changed->>'id' OR p.id=changed->>'object_id' OR p.id=changed->>'aggregate_id') LOOP
   PERFORM reconforge.icfx_close(selected,plan.id);
  END LOOP;
 END LOOP;RETURN NULL;
END $icfx$;
DO $icfx$ DECLARE n TEXT;BEGIN
 FOREACH n IN ARRAY ARRAY['intercompany_fx_sources','intercompany_fx_plans','intercompany_fx_reviews','intercompany_fx_links','intercompany_fx_post_evidence','intercompany_fx_commands'] LOOP
  EXECUTE format('ALTER TABLE reconforge.%I ENABLE ROW LEVEL SECURITY',n);EXECUTE format('ALTER TABLE reconforge.%I FORCE ROW LEVEL SECURITY',n);
  IF n IN('intercompany_fx_sources','intercompany_fx_plans','intercompany_fx_commands') THEN
   EXECUTE format('CREATE POLICY scope ON reconforge.%I USING(reconforge.icfx_scope(tenant_id,workspace_id,organization_id,seller_entity_id,buyer_entity_id,adjustment_entity_id)) WITH CHECK(reconforge.icfx_scope(tenant_id,workspace_id,organization_id,seller_entity_id,buyer_entity_id,adjustment_entity_id))',n);
  ELSE EXECUTE format('CREATE POLICY scope ON reconforge.%I USING(EXISTS(SELECT 1 FROM reconforge.intercompany_fx_plans p WHERE p.tenant_id=%I.tenant_id AND p.id=%I.plan_id)) WITH CHECK(EXISTS(SELECT 1 FROM reconforge.intercompany_fx_plans p WHERE p.tenant_id=%I.tenant_id AND p.id=%I.plan_id))',n,n,n,n,n);END IF;
  EXECUTE format('CREATE TRIGGER immutable BEFORE UPDATE OR DELETE ON reconforge.%I FOR EACH ROW EXECUTE FUNCTION reconforge.icfx_protect()',n);
 END LOOP;
 FOREACH n IN ARRAY ARRAY['intercompany_fx_sources','intercompany_fx_plans','intercompany_fx_reviews','intercompany_fx_links','intercompany_fx_post_evidence','intercompany_fx_commands',
 'finance_entries','finance_entry_lines','finance_entry_line_dimensions','finance_posting_effects','domain_audit_events','outbox_events','finance_accounts','finance_journals','fiscal_periods','legal_entities'] LOOP
  EXECUTE format('CREATE CONSTRAINT TRIGGER intercompany_fx_owner_closure AFTER INSERT OR UPDATE OR DELETE ON reconforge.%I DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION reconforge.icfx_reverse_close()',n);
 END LOOP;
END $icfx$;
"""

DOWNGRADE_SQL = r"""
DO $icfx$ BEGIN IF EXISTS(SELECT 1 FROM reconforge.intercompany_fx_sources) THEN RAISE EXCEPTION 'ICFX2 downgrade refuses to discard retained original financial history';END IF;END $icfx$;
DO $icfx$ DECLARE n TEXT;BEGIN
 FOREACH n IN ARRAY ARRAY['intercompany_fx_sources','intercompany_fx_plans','intercompany_fx_reviews','intercompany_fx_links','intercompany_fx_post_evidence','intercompany_fx_commands',
 'finance_entries','finance_entry_lines','finance_entry_line_dimensions','finance_posting_effects','domain_audit_events','outbox_events','finance_accounts','finance_journals','fiscal_periods','legal_entities'] LOOP
  EXECUTE format('DROP TRIGGER intercompany_fx_owner_closure ON reconforge.%I',n);
 END LOOP;END $icfx$;
DROP TABLE reconforge.intercompany_fx_commands,reconforge.intercompany_fx_post_evidence,reconforge.intercompany_fx_links,reconforge.intercompany_fx_reviews,reconforge.intercompany_fx_plans,reconforge.intercompany_fx_sources;
DROP FUNCTION reconforge.icfx_reverse_close(),reconforge.icfx_command_actor(),reconforge.icfx_protect(),reconforge.icfx_close(TEXT,TEXT),reconforge.icfx_translation(TEXT,JSONB,TEXT,INTEGER,JSONB);
DROP FUNCTION reconforge.icfx_event(TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,JSONB),reconforge.icfx_scope(TEXT,TEXT,TEXT,TEXT,TEXT,TEXT),reconforge.icfx_line(TEXT,NUMERIC,NUMERIC),reconforge.icfx_assert(BOOLEAN,TEXT);
"""


def upgrade(connection: Any) -> None:
    connection.execute(UPGRADE_SQL)


def downgrade(connection: Any) -> None:
    connection.execute(DOWNGRADE_SQL)
