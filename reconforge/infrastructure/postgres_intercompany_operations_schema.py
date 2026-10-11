"""Native intercompany pair closure; published through root-owned revision134."""

UPGRADE_SQL = r"""
DO $ic$ BEGIN
 IF EXISTS(SELECT 1 FROM reconforge.finance_entries WHERE upper(entry_number) LIKE 'IC1-%') THEN
  RAISE EXCEPTION 'IC1 namespace already contains incompatible native entries'; END IF;
END $ic$;
CREATE TABLE reconforge.intercompany_operation_sources(
 tenant_id TEXT NOT NULL,id TEXT NOT NULL,workspace_id TEXT NOT NULL,organization_id TEXT NOT NULL,
 seller_entity_id TEXT NOT NULL,buyer_entity_id TEXT NOT NULL,adjustment_entity_id TEXT NOT NULL,reference TEXT NOT NULL,
 payload JSONB NOT NULL CHECK(jsonb_typeof(payload)='object' AND octet_length(payload::text)<=65536),
 PRIMARY KEY(tenant_id,id),UNIQUE(tenant_id,workspace_id,reference),
 CHECK(seller_entity_id<>buyer_entity_id AND seller_entity_id<>adjustment_entity_id AND buyer_entity_id<>adjustment_entity_id),
 FOREIGN KEY(tenant_id,seller_entity_id) REFERENCES reconforge.legal_entities(tenant_id,id),
 FOREIGN KEY(tenant_id,buyer_entity_id) REFERENCES reconforge.legal_entities(tenant_id,id),
 FOREIGN KEY(tenant_id,adjustment_entity_id) REFERENCES reconforge.legal_entities(tenant_id,id));
CREATE TABLE reconforge.intercompany_operation_plans(
 tenant_id TEXT NOT NULL,id TEXT NOT NULL,workspace_id TEXT NOT NULL,organization_id TEXT NOT NULL,
 seller_entity_id TEXT NOT NULL,buyer_entity_id TEXT NOT NULL,adjustment_entity_id TEXT NOT NULL,source_id TEXT NOT NULL,
 sequence INTEGER NOT NULL CHECK(sequence BETWEEN 0 AND 33),kind TEXT NOT NULL CHECK(kind IN('recognize','settle','eliminate')),
 phase INTEGER NOT NULL CHECK(phase BETWEEN 0 AND 2),payload JSONB NOT NULL CHECK(jsonb_typeof(payload)='object' AND octet_length(payload::text)<=131072),
 audit_event_id TEXT NOT NULL,outbox_event_id TEXT NOT NULL,PRIMARY KEY(tenant_id,id),UNIQUE(tenant_id,source_id,sequence),
 FOREIGN KEY(tenant_id,source_id) REFERENCES reconforge.intercompany_operation_sources(tenant_id,id));
CREATE UNIQUE INDEX intercompany_operation_pending ON reconforge.intercompany_operation_plans(tenant_id,source_id) WHERE phase<2;
CREATE UNIQUE INDEX intercompany_operation_elimination ON reconforge.intercompany_operation_plans(tenant_id,source_id) WHERE kind='eliminate';
CREATE TABLE reconforge.intercompany_operation_reviews(
 tenant_id TEXT NOT NULL,plan_id TEXT NOT NULL,reviewer_actor_id TEXT NOT NULL,reason TEXT NOT NULL CHECK(reconforge.irp_text(reason,500)),
 audit_event_id TEXT NOT NULL,outbox_event_id TEXT NOT NULL,PRIMARY KEY(tenant_id,plan_id),
 FOREIGN KEY(tenant_id,plan_id) REFERENCES reconforge.intercompany_operation_plans(tenant_id,id),
 FOREIGN KEY(tenant_id,reviewer_actor_id) REFERENCES reconforge.identity_users(tenant_id,id));
CREATE TABLE reconforge.intercompany_operation_links(
 tenant_id TEXT NOT NULL,plan_id TEXT NOT NULL,book TEXT NOT NULL CHECK(book IN('seller','buyer','adjustment')),
 entry_id TEXT NOT NULL,posting_effect_id TEXT NOT NULL,posted_actor_id TEXT NOT NULL,reason TEXT NOT NULL CHECK(reconforge.irp_text(reason,500)),
 PRIMARY KEY(tenant_id,plan_id,book),UNIQUE(tenant_id,entry_id),UNIQUE(tenant_id,posting_effect_id),
 FOREIGN KEY(tenant_id,plan_id) REFERENCES reconforge.intercompany_operation_plans(tenant_id,id),
 FOREIGN KEY(tenant_id,entry_id) REFERENCES reconforge.finance_entries(tenant_id,id),
 FOREIGN KEY(tenant_id,posting_effect_id) REFERENCES reconforge.finance_posting_effects(tenant_id,id),
 FOREIGN KEY(tenant_id,posted_actor_id) REFERENCES reconforge.identity_users(tenant_id,id));
CREATE TABLE reconforge.intercompany_operation_post_evidence(
 tenant_id TEXT NOT NULL,plan_id TEXT NOT NULL,audit_event_id TEXT NOT NULL,outbox_event_id TEXT NOT NULL,
 PRIMARY KEY(tenant_id,plan_id),FOREIGN KEY(tenant_id,plan_id) REFERENCES reconforge.intercompany_operation_plans(tenant_id,id));
CREATE TABLE reconforge.intercompany_operation_commands(
 tenant_id TEXT NOT NULL,workspace_id TEXT NOT NULL,organization_id TEXT NOT NULL,seller_entity_id TEXT NOT NULL,
 buyer_entity_id TEXT NOT NULL,adjustment_entity_id TEXT NOT NULL,plan_id TEXT NOT NULL,
 operation TEXT NOT NULL CHECK(operation IN('prepare','review','post')),command_id TEXT NOT NULL CHECK(reconforge.irp_text(command_id,140)),
 actor_id TEXT NOT NULL,request_digest TEXT NOT NULL,request_json JSONB NOT NULL,response_json JSONB NOT NULL,
 PRIMARY KEY(tenant_id,workspace_id,command_id),UNIQUE(tenant_id,plan_id,operation),
 FOREIGN KEY(tenant_id,plan_id) REFERENCES reconforge.intercompany_operation_plans(tenant_id,id),
 FOREIGN KEY(tenant_id,actor_id) REFERENCES reconforge.identity_users(tenant_id,id),
 CHECK(octet_length(request_json::text)<=131072 AND octet_length(response_json::text)<=131072));
CREATE FUNCTION reconforge.ic_operation_assert(ok BOOLEAN,message TEXT) RETURNS VOID LANGUAGE plpgsql SET search_path=pg_catalog AS $ic$
BEGIN IF ok IS DISTINCT FROM TRUE THEN RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='intercompany_operation_owner',MESSAGE=message;END IF;END $ic$;
CREATE FUNCTION reconforge.ic_operation_scope(t TEXT,w TEXT,o TEXT,a TEXT,b TEXT,g TEXT) RETURNS BOOLEAN
 LANGUAGE sql STABLE SECURITY INVOKER SET search_path=pg_catalog AS $ic$
 SELECT a<>b AND a<>g AND b<>g AND reconforge.irp_scope(t,w,o,a) AND reconforge.irp_scope(t,w,o,b) AND reconforge.irp_scope(t,w,o,g)
$ic$;
CREATE FUNCTION reconforge.ic_operation_event(t TEXT,p TEXT,a TEXT,b TEXT,actor TEXT,action TEXT,metadata JSONB) RETURNS BOOLEAN
 LANGUAGE sql STABLE SECURITY INVOKER SET search_path=pg_catalog AS $ic$
 SELECT EXISTS(SELECT 1 FROM reconforge.domain_audit_events x JOIN reconforge.outbox_events y ON y.tenant_id=x.tenant_id
 JOIN reconforge.intercompany_operation_plans z ON z.tenant_id=x.tenant_id AND z.id=p WHERE x.tenant_id=t AND x.id=a AND y.event_id=b
 AND x.actor_user_id=actor AND x.object_type='operational_finance' AND x.object_id=p AND x.action=$6 AND x.metadata_json=$7
 AND y.event_type=$6 AND y.aggregate_type='operational_finance' AND y.aggregate_id=p
 AND y.payload=$7||jsonb_build_object('audit_event_id',a)
 AND (y.workspace_id,y.organization_id,y.legal_entity_id)=(z.workspace_id,z.organization_id,z.adjustment_entity_id))
$ic$;
CREATE FUNCTION reconforge.ic_operation_protect() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $ic$
BEGIN
 IF TG_TABLE_NAME='intercompany_operation_plans' AND TG_OP='UPDATE' THEN
  IF NEW.phase=OLD.phase+1 AND (to_jsonb(NEW)-'phase')=(to_jsonb(OLD)-'phase') THEN RETURN NEW;END IF;
 END IF;
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='intercompany_operation_owner',MESSAGE='Original paired source, review, effects and acknowledgements are immutable';
END $ic$;
CREATE FUNCTION reconforge.ic_operation_command_actor() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $ic$
DECLARE p RECORD;period RECORD;permission TEXT;e RECORD;
BEGIN
 permission:=CASE NEW.operation WHEN 'prepare' THEN 'finance_core.manage' WHEN 'review' THEN 'finance_core.validate' ELSE 'finance_core.post' END;
 PERFORM reconforge.ic_operation_assert(reconforge.sales_revenue_actor(NEW.tenant_id,NEW.actor_id,permission)
 AND reconforge.sales_revenue_actor(NEW.tenant_id,NEW.actor_id,'intercompany_operations.'||NEW.operation),
 'Intercompany commands require current persisted human finance and operation permissions');
 PERFORM 1 FROM reconforge.principal_scope_grants WHERE tenant_id=NEW.tenant_id AND principal_type='user' AND principal_id=NEW.actor_id
 AND revoked_at IS NULL AND((scope_type='workspace' AND scope_id=NEW.workspace_id) OR(scope_type='organization' AND scope_id=NEW.organization_id)
 OR(scope_type='legal_entity' AND scope_id IN(NEW.seller_entity_id,NEW.buyer_entity_id,NEW.adjustment_entity_id))) ORDER BY scope_type,scope_id FOR SHARE;
 PERFORM reconforge.ic_operation_assert((SELECT count(DISTINCT(scope_type,scope_id)) FROM reconforge.principal_scope_grants
 WHERE tenant_id=NEW.tenant_id AND principal_type='user' AND principal_id=NEW.actor_id AND revoked_at IS NULL
 AND((scope_type='workspace' AND scope_id=NEW.workspace_id) OR(scope_type='organization' AND scope_id=NEW.organization_id)
 OR(scope_type='legal_entity' AND scope_id IN(NEW.seller_entity_id,NEW.buyer_entity_id,NEW.adjustment_entity_id))))=5,
 'Intercompany command requires all three current persisted entity grants and parent scopes');
 SELECT * INTO p FROM reconforge.intercompany_operation_plans WHERE tenant_id=NEW.tenant_id AND id=NEW.plan_id;
 SELECT * INTO period FROM reconforge.fiscal_periods WHERE tenant_id=NEW.tenant_id AND id=p.payload->>'period_id' FOR SHARE;
 PERFORM reconforge.ic_operation_assert(period.id IS NOT NULL AND period.status='Open' AND period.application_workspace_id=NEW.workspace_id
 AND (p.payload->>'posting_date')::date BETWEEN period.start_date AND period.end_date
 AND reconforge.ic_operation_scope(NEW.tenant_id,NEW.workspace_id,NEW.organization_id,NEW.seller_entity_id,NEW.buyer_entity_id,NEW.adjustment_entity_id),
 'A current open period and all three authorized hierarchy scopes are required');
 FOR e IN SELECT id,active FROM reconforge.legal_entities WHERE tenant_id=NEW.tenant_id
 AND id IN(NEW.seller_entity_id,NEW.buyer_entity_id,NEW.adjustment_entity_id) ORDER BY id FOR SHARE LOOP
  PERFORM reconforge.ic_operation_assert(e.active,'Current intercompany entity references must be active');
 END LOOP;
 RETURN NEW;
END $ic$;
CREATE TRIGGER current_actor BEFORE INSERT ON reconforge.intercompany_operation_commands FOR EACH ROW EXECUTE FUNCTION reconforge.ic_operation_command_actor();
CREATE FUNCTION reconforge.ic_operation_close(t TEXT,i TEXT) RETURNS VOID LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog AS $ic$
DECLARE p RECORD;s RECORD;r RECORD;l RECORD;f RECORD;e RECORD;j RECORD;post_event RECORD;command RECORD;prior RECORD;
 a JSONB;v JSONB;q JSONB;eq JSONB;books JSONB;lines JSONB;expected JSONB;item JSONB;head JSONB;native_lines JSONB;
 book_name TEXT;field TEXT;entity TEXT;account TEXT;expected_account_type TEXT;cash TEXT;ar TEXT;ap TEXT;income TEXT;expense TEXT;
 gross NUMERIC;paid NUMERIC:=0;installment NUMERIC;outstanding NUMERIC;burden NUMERIC;turnover NUMERIC;
 count_entries INTEGER;count_links INTEGER;sequence INTEGER:=0;last_day TEXT;closed BOOLEAN:=FALSE;
BEGIN
 SELECT * INTO p FROM reconforge.intercompany_operation_plans WHERE tenant_id=t AND id=i;
 PERFORM reconforge.ic_operation_assert(p.id IS NOT NULL,'IC1 native entry requires its complete retained owner');
 SELECT * INTO s FROM reconforge.intercompany_operation_sources WHERE tenant_id=t AND id=p.source_id;
 SELECT * INTO r FROM reconforge.intercompany_operation_reviews WHERE tenant_id=t AND plan_id=i;
 SELECT * INTO post_event FROM reconforge.intercompany_operation_post_evidence WHERE tenant_id=t AND plan_id=i;
 a:=s.payload;v:=p.payload;q:=a->'request';eq:=v->'equation';
 PERFORM reconforge.ic_operation_assert(s.id IS NOT NULL AND reconforge.fx_object(a,ARRAY['schema_version','id','request','monetary_policy','preparer_actor_id','source_digest'])
 AND reconforge.fx_object(q,ARRAY['workspace_id','organization_id','organization_code','seller_entity_id','seller_entity_code','buyer_entity_id','buyer_entity_code',
 'adjustment_entity_id','adjustment_entity_code','reference','amount_minor','period_id','posting_date','journal_code',
 'receivable_account_code','payable_account_code','revenue_account_code','expense_account_code','cash_account_code','reason'])
 AND reconforge.fx_object(v,ARRAY['schema_version','id','source_id','workspace_id','organization_id','seller_entity_id','buyer_entity_id','adjustment_entity_id',
 'kind','sequence','period_id','posting_date','reason','currency_code','currency_precision','source_digest','amount_minor','equation','entries','preparer_actor_id','command_request','plan_digest'])
 AND reconforge.fx_object(eq,ARRAY['kind','original_minor','settled_before_minor','settlement_minor','outstanding_before_minor','books','amount_minor']),
 'Paired source, native plan and integer equation require closed exact schemas');
 PERFORM reconforge.ic_operation_assert(a->>'schema_version'='intercompany-native-source-v1' AND v->>'schema_version'='intercompany-native-plan-v1'
 AND a->>'id'=s.id AND a->>'source_digest'=reconforge.irp_digest(a-'source_digest')
 AND v->>'plan_digest'=reconforge.irp_digest(v-'plan_digest') AND v->>'source_digest'=a->>'source_digest'
 AND s.id~'^IC-[a-f0-9]{32}$' AND p.id~'^IC1-[a-f0-9]{32}$'
 AND (q->>'workspace_id',q->>'organization_id',q->>'seller_entity_id',q->>'buyer_entity_id',q->>'adjustment_entity_id',q->>'reference')
 =(s.workspace_id,s.organization_id,s.seller_entity_id,s.buyer_entity_id,s.adjustment_entity_id,s.reference)
 AND (v->>'id',v->>'source_id',v->>'workspace_id',v->>'organization_id',v->>'seller_entity_id',v->>'buyer_entity_id',v->>'adjustment_entity_id',v->>'kind')
 =(p.id,p.source_id,p.workspace_id,p.organization_id,p.seller_entity_id,p.buyer_entity_id,p.adjustment_entity_id,p.kind)
 AND (p.workspace_id,p.organization_id,p.seller_entity_id,p.buyer_entity_id,p.adjustment_entity_id)
 =(s.workspace_id,s.organization_id,s.seller_entity_id,s.buyer_entity_id,s.adjustment_entity_id)
 AND (v->>'sequence')::integer=p.sequence AND reconforge.fx_minor(q->'amount_minor')
 AND (q->>'amount_minor')::numeric BETWEEN 1 AND 4500000000000000000
 AND reconforge.fx_policy(t,a->'monetary_policy') AND a->'monetary_policy'->>'currency_code'=v->>'currency_code'
 AND a->'monetary_policy'->>'currency_precision'=v->>'currency_precision', 'Original pair identity, money or retained currency policy differs');
 FOREACH field IN ARRAY ARRAY['organization_code','seller_entity_code','buyer_entity_code','adjustment_entity_code','reference','period_id','journal_code',
 'receivable_account_code','payable_account_code','revenue_account_code','expense_account_code','cash_account_code'] LOOP
  PERFORM reconforge.ic_operation_assert(jsonb_typeof(q->field)='string' AND reconforge.irp_text(q->>field,160),'Pair metadata requires bounded canonical text');
 END LOOP;
 PERFORM reconforge.ic_operation_assert((q->>'posting_date')::date::text=q->>'posting_date' AND (v->>'posting_date')::date::text=v->>'posting_date'
 AND reconforge.irp_text(q->>'reason',500) AND reconforge.irp_text(v->>'reason',500)
 AND (SELECT count(DISTINCT value) FROM jsonb_each_text(q) WHERE key IN('receivable_account_code','payable_account_code','revenue_account_code','expense_account_code','cash_account_code'))=5,
 'Source dates, reasons and distinct native account mapping are required');
 gross:=(q->>'amount_minor')::numeric;last_day:=q->>'posting_date';
 FOR prior IN SELECT pp.* FROM reconforge.intercompany_operation_plans pp WHERE pp.tenant_id=t AND pp.source_id=s.id AND pp.sequence<p.sequence ORDER BY pp.sequence LOOP
  PERFORM reconforge.ic_operation_assert(prior.sequence=sequence AND prior.phase=2 AND NOT closed
  AND prior.payload->>'posting_date'>=last_day, 'Every earlier source operation must be contiguous, complete and date-ordered');
  IF prior.kind='settle' THEN paid:=paid+(prior.payload->'equation'->>'settlement_minor')::numeric;END IF;
  IF prior.kind='eliminate' THEN closed:=TRUE;END IF;
  sequence:=sequence+1;last_day:=prior.payload->>'posting_date';
 END LOOP;
 PERFORM reconforge.ic_operation_assert(sequence=p.sequence AND NOT closed AND v->>'posting_date'>=last_day
 AND (p.sequence=0)=(p.kind='recognize') AND paid BETWEEN 0 AND gross,
 'Recognition, residual settlement and closing order cannot diverge');
 installment:=(eq->>'settlement_minor')::numeric;outstanding:=gross-paid;
 cash:=q->>'cash_account_code';ar:=q->>'receivable_account_code';ap:=q->>'payable_account_code';income:=q->>'revenue_account_code';expense:=q->>'expense_account_code';
 IF p.kind='recognize' THEN
  PERFORM reconforge.ic_operation_assert(installment=0 AND paid=0,'Recognition cannot release prior cash');
  books:=jsonb_build_object('seller',jsonb_build_array(jsonb_build_object('account_code',ar,'debit_minor',gross,'credit_minor',0),jsonb_build_object('account_code',income,'debit_minor',0,'credit_minor',gross)),
  'buyer',jsonb_build_array(jsonb_build_object('account_code',expense,'debit_minor',gross,'credit_minor',0),jsonb_build_object('account_code',ap,'debit_minor',0,'credit_minor',gross)));
 ELSIF p.kind='settle' THEN
  PERFORM reconforge.ic_operation_assert(p.sequence<=32 AND reconforge.fx_minor(eq->'settlement_minor') AND installment BETWEEN 1 AND outstanding,'Cash installment must exactly release the paired remaining balance');
  books:=jsonb_build_object('seller',jsonb_build_array(jsonb_build_object('account_code',cash,'debit_minor',installment,'credit_minor',0),jsonb_build_object('account_code',ar,'debit_minor',0,'credit_minor',installment)),
  'buyer',jsonb_build_array(jsonb_build_object('account_code',ap,'debit_minor',installment,'credit_minor',0),jsonb_build_object('account_code',cash,'debit_minor',0,'credit_minor',installment)));
 ELSE
  PERFORM reconforge.ic_operation_assert(installment=0,'Group elimination cannot transfer cash');
  lines:=jsonb_build_array(jsonb_build_object('account_code',income,'debit_minor',gross,'credit_minor',0),jsonb_build_object('account_code',expense,'debit_minor',0,'credit_minor',gross));
  IF outstanding>0 THEN lines:=lines||jsonb_build_array(jsonb_build_object('account_code',ap,'debit_minor',outstanding,'credit_minor',0),jsonb_build_object('account_code',ar,'debit_minor',0,'credit_minor',outstanding));END IF;
  books:=jsonb_build_object('adjustment',lines);
 END IF;
 SELECT max(debits) INTO burden FROM(SELECT sum((row->>'debit_minor')::numeric) AS debits FROM jsonb_each(books) b CROSS JOIN LATERAL jsonb_array_elements(b.value) row GROUP BY b.key) totals;
 expected:=jsonb_build_object('kind',p.kind,'original_minor',gross,'settled_before_minor',paid,'settlement_minor',installment,'outstanding_before_minor',outstanding,'books',books,'amount_minor',burden);
 PERFORM reconforge.ic_operation_assert(eq=expected AND reconforge.fx_minor(v->'amount_minor') AND (v->>'amount_minor')::numeric=burden,
 'Independent SQL original, cash, residual and group adjustment equations differ');
 IF p.kind='recognize' THEN
  PERFORM reconforge.ic_operation_assert(v->>'preparer_actor_id'=a->>'preparer_actor_id'
   AND v->'command_request'=q||jsonb_build_object('kind','recognize'), 'Recognition request must retain its exact original source and preparer');
 ELSE
  PERFORM reconforge.ic_operation_assert(v->'command_request'=jsonb_build_object('kind',p.kind,'source_id',s.id,
   'amount_minor',installment,'period_id',v->>'period_id','posting_date',v->>'posting_date','reason',v->>'reason'),
   'Progression request must retain its exact original source, money and business date');
 END IF;
 SELECT count(*) INTO count_entries FROM jsonb_object_keys(books);
 PERFORM reconforge.ic_operation_assert(jsonb_typeof(v->'entries')='array' AND jsonb_array_length(v->'entries')=count_entries
 AND (SELECT count(DISTINCT value->>'book') FROM jsonb_array_elements(v->'entries'))=count_entries
 AND (SELECT count(DISTINCT value->>'entry_id') FROM jsonb_array_elements(v->'entries'))=count_entries,
 'Native source requires every unique paired or group entry');
 FOR item IN SELECT value FROM jsonb_array_elements(v->'entries') LOOP
  book_name:=item->>'book';entity:=q->>(book_name||'_entity_id');
  PERFORM reconforge.ic_operation_assert(books ? book_name AND reconforge.fx_object(item,ARRAY['book','entry_id','snapshot','validation_digest'])
  AND item->>'validation_digest'=reconforge.irp_digest(item->'snapshot'), 'Native entry seal or paired book differs');
  SELECT * INTO e FROM reconforge.finance_entries WHERE tenant_id=t AND id=item->>'entry_id';
  SELECT * INTO j FROM reconforge.finance_journals WHERE tenant_id=t AND id=e.journal_id;
  PERFORM reconforge.ic_operation_assert(e.id IS NOT NULL AND e.entry_number=upper(p.id)||'-'||CASE book_name WHEN 'seller' THEN 'A' WHEN 'buyer' THEN 'B' ELSE 'G' END
  AND e.workspace_id=s.workspace_id AND e.organization_code=q->>'organization_code' AND e.entity_code=q->>(book_name||'_entity_code')
  AND e.period_id=v->>'period_id' AND e.posting_date=v->>'posting_date' AND e.description=v->>'reason'
  AND e.external_reference='IC:'||s.id||':'||p.kind AND e.source_type='Manual' AND e.reverses_posting_id IS NULL
  AND e.preparer_actor_id=v->>'preparer_actor_id' AND j.journal_code=q->>'journal_code'
  AND (e.currency_code,e.currency_precision::text,e.currency_rounding_policy,e.currency_registry_version,e.currency_registry_digest)
  =(a->'monetary_policy'->>'currency_code',a->'monetary_policy'->>'currency_precision',a->'monetary_policy'->>'currency_rounding_policy',a->'monetary_policy'->>'currency_registry_version',a->'monetary_policy'->>'currency_registry_digest')
  AND EXISTS(SELECT 1 FROM reconforge.legal_entities z WHERE z.tenant_id=t AND z.id=entity AND z.organization_id=s.organization_id AND z.entity_code=e.entity_code AND z.currency_code=e.currency_code),
  'Paired native entry identity, source, entity or original currency policy differs');
  SELECT jsonb_agg(jsonb_build_object('account_code',ac.account_code,'debit_minor',nl.debit_minor,'credit_minor',nl.credit_minor) ORDER BY nl.line_number)
  INTO native_lines FROM reconforge.finance_entry_lines nl JOIN reconforge.finance_accounts ac ON ac.tenant_id=nl.tenant_id AND ac.id=nl.account_id WHERE nl.tenant_id=t AND nl.entry_id=e.id;
  PERFORM reconforge.ic_operation_assert(native_lines=books->book_name AND e.total_debit_minor=(SELECT sum((row->>'debit_minor')::numeric) FROM jsonb_array_elements(books->book_name) row)
  AND e.total_debit_minor=e.total_credit_minor, 'Both original native journals must conserve their exact reviewed equations');
  FOR lines IN SELECT value FROM jsonb_array_elements(books->book_name) LOOP
   account:=lines->>'account_code';expected_account_type:=CASE WHEN account IN(ar,cash) THEN 'Asset' WHEN account=ap THEN 'Liability' WHEN account=income THEN 'Income' ELSE 'Expense' END;
   PERFORM reconforge.ic_operation_assert(EXISTS(SELECT 1 FROM reconforge.finance_accounts ac JOIN reconforge.finance_entry_lines nl ON nl.tenant_id=ac.tenant_id AND nl.account_id=ac.id
    WHERE ac.tenant_id=t AND nl.entry_id=e.id AND ac.account_code=account AND ac.account_type=expected_account_type AND ac.chart_id=j.chart_id), 'Retained native account semantics differ from reviewed service charge mapping');
  END LOOP;
  head:=item->'snapshot'->'entry';
  PERFORM reconforge.ic_operation_assert(head->>'id'=e.id AND head->>'workspace_id'=s.workspace_id AND head->>'organization_id'=s.organization_id AND head->>'legal_entity_id'=entity
  AND head->>'entry_number'=e.entry_number AND head->>'period_id'=e.period_id AND head->>'posting_date'=e.posting_date
  AND head->>'preparer_actor_id'=v->>'preparer_actor_id', 'Native snapshot must bind its exact party, period and original preparer');
  SELECT jsonb_object_agg(key,value) INTO head FROM jsonb_each(to_jsonb(e))
   WHERE key=ANY(ARRAY['id','workspace_id','journal_id','period_id','entry_number','posting_date','description','external_reference','source_type','currency_code',
   'currency_precision','currency_rounding_policy','currency_registry_version','currency_registry_digest','preparer_actor_id','reverses_posting_id']);
  head:=head||jsonb_build_object('organization_id',s.organization_id,'legal_entity_id',entity);
  SELECT jsonb_agg(jsonb_build_object('line_number',nl.line_number,'account_id',nl.account_id,'description',nl.description,
   'debit_minor',nl.debit_minor,'credit_minor',nl.credit_minor,'dimensions',COALESCE((SELECT jsonb_object_agg(d.dimension_id,d.dimension_value_id)
   FROM reconforge.finance_entry_line_dimensions d WHERE d.tenant_id=nl.tenant_id AND d.entry_line_id=nl.id),'{}'::jsonb)) ORDER BY nl.line_number)
   INTO native_lines FROM reconforge.finance_entry_lines nl WHERE nl.tenant_id=t AND nl.entry_id=e.id;
  PERFORM reconforge.ic_operation_assert(item->'snapshot'=jsonb_build_object('schema_version','finance-entry-review-v1','entry',head,'lines',native_lines),
   'Complete native snapshot, dimensions and descriptions must match their retained original seal');
  SELECT links.* INTO l FROM reconforge.intercompany_operation_links links WHERE links.tenant_id=t AND links.plan_id=i AND links.book=book_name;
  SELECT * INTO f FROM reconforge.finance_posting_effects WHERE tenant_id=t AND entry_id=e.id;
  IF p.phase=0 THEN
   PERFORM reconforge.ic_operation_assert(e.status='Draft' AND e.validation_digest IS NULL AND r.plan_id IS NULL AND l.plan_id IS NULL AND f.id IS NULL,
   'Prepared pair cannot contain independently reviewed or partially posted effects');
  ELSE
   PERFORM reconforge.ic_operation_assert(r.plan_id IS NOT NULL AND r.reviewer_actor_id<>v->>'preparer_actor_id' AND e.status='Validated'
   AND e.validator_actor_id=r.reviewer_actor_id AND e.validation_digest=item->>'validation_digest', 'Review must seal every party through an independent human');
   IF p.phase=1 THEN
    PERFORM reconforge.ic_operation_assert(l.plan_id IS NULL AND f.id IS NULL,'Reviewed pair cannot retain half a native posting');
   ELSE
    PERFORM reconforge.ic_operation_assert(l.plan_id IS NOT NULL AND f.id=l.posting_effect_id AND l.entry_id=e.id
    AND l.posted_actor_id=f.posted_actor_id AND l.posted_actor_id NOT IN(v->>'preparer_actor_id',r.reviewer_actor_id)
    AND f.snapshot_json=item->'snapshot' AND f.validation_digest=item->>'validation_digest' AND f.source_kind='Manual'
    AND f.source_id=e.id AND f.reverses_effect_id IS NULL,
    'Posting must include every exact native effect and a third distinct human');
   END IF;
  END IF;
 END LOOP;
 SELECT count(*) INTO count_links FROM reconforge.intercompany_operation_links WHERE tenant_id=t AND plan_id=i;
 PERFORM reconforge.ic_operation_assert(count_links=CASE WHEN p.phase=2 THEN count_entries ELSE 0 END
 AND reconforge.ic_operation_event(t,i,p.audit_event_id,p.outbox_event_id,v->>'preparer_actor_id','intercompany_operation_prepared',jsonb_build_object('plan_digest',v->>'plan_digest')),
 'Paired native effects and original preparation evidence must close together');
 IF p.phase>0 THEN
  PERFORM reconforge.ic_operation_assert(reconforge.ic_operation_event(t,i,r.audit_event_id,r.outbox_event_id,r.reviewer_actor_id,'intercompany_operation_reviewed',jsonb_build_object('plan_digest',v->>'plan_digest')),
  'Independent review audit and outbox seal differ');
 END IF;
 IF p.phase=2 THEN
  PERFORM reconforge.ic_operation_assert(post_event.plan_id IS NOT NULL
  AND (SELECT count(DISTINCT posted_actor_id) FROM reconforge.intercompany_operation_links WHERE tenant_id=t AND plan_id=i)=1
  AND reconforge.ic_operation_event(t,i,post_event.audit_event_id,post_event.outbox_event_id,l.posted_actor_id,'intercompany_operation_posted',jsonb_build_object('plan_digest',v->>'plan_digest')),
  'Complete paired publication requires one exact third-human audit and outbox');
 ELSE PERFORM reconforge.ic_operation_assert(post_event.plan_id IS NULL,'Unposted source cannot claim final publication evidence');END IF;
 PERFORM reconforge.ic_operation_assert((SELECT count(*) FROM reconforge.intercompany_operation_commands WHERE tenant_id=t AND plan_id=i)=p.phase+1,
 'Every retained phase requires its exact original acknowledgement');
 FOR command IN SELECT * FROM reconforge.intercompany_operation_commands WHERE tenant_id=t AND plan_id=i LOOP
  PERFORM reconforge.ic_operation_assert(command.request_digest=reconforge.irp_digest(command.request_json)
  AND reconforge.fx_object(command.request_json,ARRAY['operation','actor_id','request'])
  AND command.request_json->>'operation'=command.operation AND command.request_json->>'actor_id'=command.actor_id
  AND command.response_json-'phase'-'status'-'reviewer_actor_id'-'posted_actor_id'-'posting_effect_ids'=v
  AND (command.response_json->>'phase')::integer=CASE command.operation WHEN 'prepare' THEN 0 WHEN 'review' THEN 1 ELSE 2 END
  AND command.response_json->>'status'=CASE command.operation WHEN 'prepare' THEN 'Prepared' WHEN 'review' THEN 'Reviewed' ELSE 'Posted' END
  AND (command.workspace_id,command.organization_id,command.seller_entity_id,command.buyer_entity_id,command.adjustment_entity_id)
  =(s.workspace_id,s.organization_id,s.seller_entity_id,s.buyer_entity_id,s.adjustment_entity_id), 'Original phase acknowledgement must bind its immutable source, actor and complete response');
  IF command.operation='prepare' THEN
   PERFORM reconforge.ic_operation_assert(command.actor_id=v->>'preparer_actor_id' AND command.request_json->'request'=v->'command_request'
   AND command.response_json->'reviewer_actor_id'='null'::jsonb AND command.response_json->'posted_actor_id'='null'::jsonb
   AND command.response_json->'posting_effect_ids'='{}'::jsonb, 'Original preparation acknowledgement differs');
  ELSE
   PERFORM reconforge.ic_operation_assert(command.request_json->'request'->>'plan_id'=i AND command.request_json->'request'->>'expected_plan_digest'=v->>'plan_digest'
   AND command.response_json->>'reviewer_actor_id'=r.reviewer_actor_id, 'Original retained review or posting request differs');
   IF command.operation='review' THEN
    PERFORM reconforge.ic_operation_assert(command.actor_id=r.reviewer_actor_id AND command.request_json->'request'->>'reason'=r.reason
    AND command.response_json->'posted_actor_id'='null'::jsonb AND command.response_json->'posting_effect_ids'='{}'::jsonb,'Retained review acknowledgement differs');
   ELSE
    PERFORM reconforge.ic_operation_assert(command.actor_id=l.posted_actor_id AND command.request_json->'request'->>'reason'=l.reason
    AND command.response_json->>'posted_actor_id'=l.posted_actor_id
    AND command.response_json->'posting_effect_ids'=(SELECT jsonb_object_agg(book,posting_effect_id) FROM reconforge.intercompany_operation_links WHERE tenant_id=t AND plan_id=i),
    'Retained posting acknowledgement must name the exact complete native effect population');
   END IF;
  END IF;
 END LOOP;
END $ic$;
CREATE FUNCTION reconforge.ic_operation_reverse_close() RETURNS trigger LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog AS $ic$
DECLARE changed JSONB;entry TEXT;original TEXT;number TEXT;plan RECORD;selected TEXT;
BEGIN
 FOR changed IN SELECT value FROM jsonb_array_elements(CASE TG_OP WHEN 'INSERT' THEN jsonb_build_array(to_jsonb(NEW)) WHEN 'DELETE' THEN jsonb_build_array(to_jsonb(OLD)) ELSE jsonb_build_array(to_jsonb(OLD),to_jsonb(NEW)) END) LOOP
  selected:=changed->>'tenant_id';entry:=NULL;original:=NULL;
  IF TG_TABLE_NAME='finance_entries' THEN entry:=changed->>'id';original:=changed->>'reverses_posting_id';
  ELSIF TG_TABLE_NAME IN('finance_entry_lines','finance_posting_effects') THEN entry:=changed->>'entry_id';original:=changed->>'reverses_effect_id';
  ELSIF TG_TABLE_NAME='finance_entry_line_dimensions' THEN SELECT entry_id INTO entry FROM reconforge.finance_entry_lines WHERE tenant_id=selected AND id=changed->>'entry_line_id';
  END IF;
  IF original IS NOT NULL THEN
   PERFORM reconforge.ic_operation_assert(NOT EXISTS(SELECT 1 FROM reconforge.finance_posting_effects f JOIN reconforge.finance_entries e ON e.tenant_id=f.tenant_id AND e.id=f.entry_id
    WHERE f.tenant_id=selected AND f.id=original AND upper(left(e.entry_number,4))='IC1-'), 'Intercompany sources cannot be inverted through a detached native journal');
  END IF;
  IF entry IS NOT NULL THEN
   SELECT entry_number INTO number FROM reconforge.finance_entries WHERE tenant_id=selected AND id=entry;
   IF upper(left(number,4)) IS DISTINCT FROM 'IC1-' THEN CONTINUE;END IF;
   SELECT p.* INTO plan FROM reconforge.intercompany_operation_plans p WHERE p.tenant_id=selected AND EXISTS(SELECT 1 FROM jsonb_array_elements(p.payload->'entries') x WHERE x->>'entry_id'=entry);
   PERFORM reconforge.ic_operation_assert(plan.id IS NOT NULL,'IC1 namespace native entry requires its complete source owner');
   PERFORM reconforge.ic_operation_close(selected,plan.id);CONTINUE;
  END IF;
  IF TG_TABLE_NAME='intercompany_operation_sources' THEN
   PERFORM reconforge.ic_operation_assert(EXISTS(SELECT 1 FROM reconforge.intercompany_operation_plans p WHERE p.tenant_id=selected AND p.source_id=changed->>'id' AND p.sequence=0 AND p.kind='recognize'),
   'Original paired source must retain its complete recognition owner');
  END IF;
  IF TG_TABLE_NAME IN('finance_accounts','finance_journals','fiscal_periods','legal_entities') THEN
   -- Ordinary native roles must return before planning protected owner tables.
   IF NOT EXISTS(SELECT 1 FROM reconforge.finance_entries e WHERE e.tenant_id=selected AND upper(left(e.entry_number,4))='IC1-'
    AND ((TG_TABLE_NAME='finance_journals' AND e.journal_id=changed->>'id') OR(TG_TABLE_NAME='fiscal_periods' AND e.period_id=changed->>'id')
    OR(TG_TABLE_NAME='finance_accounts' AND EXISTS(SELECT 1 FROM reconforge.finance_entry_lines x WHERE x.tenant_id=e.tenant_id AND x.entry_id=e.id AND x.account_id=changed->>'id'))
    OR(TG_TABLE_NAME='legal_entities' AND e.entity_code=changed->>'entity_code'))) THEN CONTINUE;END IF;
   FOR plan IN SELECT * FROM reconforge.intercompany_operation_plans WHERE tenant_id=selected LOOP PERFORM reconforge.ic_operation_close(selected,plan.id);END LOOP;
   CONTINUE;
  END IF;
  IF TG_TABLE_NAME IN('domain_audit_events','outbox_events') AND
   upper(left(coalesce(changed->>'object_id',changed->>'aggregate_id',''),4))<>'IC1-' THEN CONTINUE;END IF;
  FOR plan IN SELECT * FROM reconforge.intercompany_operation_plans p WHERE p.tenant_id=selected AND
   (p.id=changed->>'plan_id' OR p.id=changed->>'id' OR p.source_id=changed->>'id' OR p.id=changed->>'object_id' OR p.id=changed->>'aggregate_id') LOOP
   PERFORM reconforge.ic_operation_close(selected,plan.id);
  END LOOP;
 END LOOP;RETURN NULL;
END $ic$;
DO $ic$ DECLARE n TEXT;BEGIN
 FOREACH n IN ARRAY ARRAY['intercompany_operation_sources','intercompany_operation_plans','intercompany_operation_reviews','intercompany_operation_links','intercompany_operation_post_evidence','intercompany_operation_commands'] LOOP
  EXECUTE format('ALTER TABLE reconforge.%I ENABLE ROW LEVEL SECURITY',n);EXECUTE format('ALTER TABLE reconforge.%I FORCE ROW LEVEL SECURITY',n);
  IF n IN('intercompany_operation_sources','intercompany_operation_plans','intercompany_operation_commands') THEN
   EXECUTE format('CREATE POLICY scope ON reconforge.%I USING(reconforge.ic_operation_scope(tenant_id,workspace_id,organization_id,seller_entity_id,buyer_entity_id,adjustment_entity_id)) WITH CHECK(reconforge.ic_operation_scope(tenant_id,workspace_id,organization_id,seller_entity_id,buyer_entity_id,adjustment_entity_id))',n);
  ELSE EXECUTE format('CREATE POLICY scope ON reconforge.%I USING(EXISTS(SELECT 1 FROM reconforge.intercompany_operation_plans p WHERE p.tenant_id=%I.tenant_id AND p.id=%I.plan_id)) WITH CHECK(EXISTS(SELECT 1 FROM reconforge.intercompany_operation_plans p WHERE p.tenant_id=%I.tenant_id AND p.id=%I.plan_id))',n,n,n,n,n);END IF;
  EXECUTE format('CREATE TRIGGER immutable BEFORE UPDATE OR DELETE ON reconforge.%I FOR EACH ROW EXECUTE FUNCTION reconforge.ic_operation_protect()',n);
 END LOOP;
 FOREACH n IN ARRAY ARRAY['intercompany_operation_sources','intercompany_operation_plans','intercompany_operation_reviews','intercompany_operation_links','intercompany_operation_post_evidence','intercompany_operation_commands',
 'finance_entries','finance_entry_lines','finance_entry_line_dimensions','finance_posting_effects','domain_audit_events','outbox_events','finance_accounts','finance_journals','fiscal_periods','legal_entities'] LOOP
  EXECUTE format('CREATE CONSTRAINT TRIGGER intercompany_operation_owner_closure AFTER INSERT OR UPDATE OR DELETE ON reconforge.%I DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION reconforge.ic_operation_reverse_close()',n);
 END LOOP;
END $ic$;
"""

DOWNGRADE_SQL = r"""
DO $ic$ BEGIN IF EXISTS(SELECT 1 FROM reconforge.intercompany_operation_sources) THEN RAISE EXCEPTION 'Intercompany downgrade refuses to discard retained paired financial history';END IF;END $ic$;
DO $ic$ DECLARE n TEXT;BEGIN
 FOREACH n IN ARRAY ARRAY['intercompany_operation_sources','intercompany_operation_plans','intercompany_operation_reviews','intercompany_operation_links','intercompany_operation_post_evidence','intercompany_operation_commands',
 'finance_entries','finance_entry_lines','finance_entry_line_dimensions','finance_posting_effects','domain_audit_events','outbox_events','finance_accounts','finance_journals','fiscal_periods','legal_entities'] LOOP
  EXECUTE format('DROP TRIGGER intercompany_operation_owner_closure ON reconforge.%I',n);
 END LOOP;END $ic$;
DROP TABLE reconforge.intercompany_operation_commands,reconforge.intercompany_operation_post_evidence,reconforge.intercompany_operation_links,reconforge.intercompany_operation_reviews,reconforge.intercompany_operation_plans,reconforge.intercompany_operation_sources;
DROP FUNCTION reconforge.ic_operation_reverse_close(),reconforge.ic_operation_command_actor(),reconforge.ic_operation_protect(),reconforge.ic_operation_close(TEXT,TEXT);
DROP FUNCTION reconforge.ic_operation_event(TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,JSONB),reconforge.ic_operation_scope(TEXT,TEXT,TEXT,TEXT,TEXT,TEXT),reconforge.ic_operation_assert(BOOLEAN,TEXT);
"""
