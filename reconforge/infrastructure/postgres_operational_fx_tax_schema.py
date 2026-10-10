"""FX1 native AR/functional GL closure, checked independently with SQL NUMERIC."""

UPGRADE_SQL = r"""
DO $fx$ BEGIN
 IF EXISTS(SELECT 1 FROM reconforge.finance_entries WHERE upper(entry_number) LIKE 'FX1-%')
 OR EXISTS(SELECT 1 FROM reconforge.ar_invoices WHERE upper(invoice_number) LIKE 'FX1-%')
 OR EXISTS(SELECT 1 FROM reconforge.ar_receipts WHERE upper(receipt_number) LIKE 'FX1-%') THEN
  RAISE EXCEPTION 'FX1 namespace already contains incompatible native sources'; END IF;
END $fx$;
CREATE TABLE reconforge.operational_fx_sources (
 tenant_id TEXT NOT NULL,id TEXT NOT NULL,workspace_id TEXT NOT NULL,organization_id TEXT NOT NULL,legal_entity_id TEXT NOT NULL,
 invoice_id TEXT NOT NULL,payload JSONB NOT NULL CHECK(jsonb_typeof(payload)='object' AND octet_length(payload::text)<=131072),
 PRIMARY KEY(tenant_id,id),UNIQUE(tenant_id,invoice_id),
 FOREIGN KEY(tenant_id,invoice_id) REFERENCES reconforge.ar_invoices(tenant_id,id)
);
CREATE TABLE reconforge.operational_fx_plans (
 tenant_id TEXT NOT NULL,id TEXT NOT NULL,workspace_id TEXT NOT NULL,organization_id TEXT NOT NULL,legal_entity_id TEXT NOT NULL,
 source_id TEXT NOT NULL,entry_id TEXT NOT NULL,sequence INTEGER NOT NULL CHECK(sequence BETWEEN 0 AND 200),
 kind TEXT NOT NULL CHECK(kind IN ('recognize','settle')),phase INTEGER NOT NULL CHECK(phase BETWEEN 0 AND 2),
 payload JSONB NOT NULL CHECK(jsonb_typeof(payload)='object' AND octet_length(payload::text)<=131072),
 audit_event_id TEXT NOT NULL,outbox_event_id TEXT NOT NULL,PRIMARY KEY(tenant_id,id),UNIQUE(tenant_id,entry_id),UNIQUE(tenant_id,source_id,sequence),
 FOREIGN KEY(tenant_id,source_id) REFERENCES reconforge.operational_fx_sources(tenant_id,id),
 FOREIGN KEY(tenant_id,entry_id) REFERENCES reconforge.finance_entries(tenant_id,id)
);
CREATE UNIQUE INDEX operational_fx_pending ON reconforge.operational_fx_plans(tenant_id,source_id) WHERE phase<2;
CREATE TABLE reconforge.operational_fx_reviews (
 tenant_id TEXT NOT NULL,plan_id TEXT NOT NULL,reviewer_actor_id TEXT NOT NULL,reason TEXT NOT NULL CHECK(reconforge.irp_text(reason,500)),
 audit_event_id TEXT NOT NULL,outbox_event_id TEXT NOT NULL,PRIMARY KEY(tenant_id,plan_id),
 FOREIGN KEY(tenant_id,plan_id) REFERENCES reconforge.operational_fx_plans(tenant_id,id),
 FOREIGN KEY(tenant_id,reviewer_actor_id) REFERENCES reconforge.identity_users(tenant_id,id)
);
CREATE TABLE reconforge.operational_fx_links (
 tenant_id TEXT NOT NULL,plan_id TEXT NOT NULL,posting_effect_id TEXT NOT NULL,receipt_id TEXT,posted_actor_id TEXT NOT NULL,
 reason TEXT NOT NULL CHECK(reconforge.irp_text(reason,500)),audit_event_id TEXT NOT NULL,outbox_event_id TEXT NOT NULL,
 PRIMARY KEY(tenant_id,plan_id),UNIQUE(tenant_id,posting_effect_id),UNIQUE(tenant_id,receipt_id),
 FOREIGN KEY(tenant_id,plan_id) REFERENCES reconforge.operational_fx_plans(tenant_id,id),
 FOREIGN KEY(tenant_id,posting_effect_id) REFERENCES reconforge.finance_posting_effects(tenant_id,id),
 FOREIGN KEY(tenant_id,receipt_id) REFERENCES reconforge.ar_receipts(tenant_id,id),
 FOREIGN KEY(tenant_id,posted_actor_id) REFERENCES reconforge.identity_users(tenant_id,id)
);
CREATE TABLE reconforge.operational_fx_commands (
 tenant_id TEXT NOT NULL,workspace_id TEXT NOT NULL,organization_id TEXT NOT NULL,legal_entity_id TEXT NOT NULL,plan_id TEXT NOT NULL,
 operation TEXT NOT NULL CHECK(operation IN ('prepare','review','post')),command_id TEXT NOT NULL CHECK(reconforge.irp_text(command_id,140)),
 actor_id TEXT NOT NULL,request_digest TEXT NOT NULL,request_json JSONB NOT NULL,response_json JSONB NOT NULL,
 PRIMARY KEY(tenant_id,workspace_id,command_id),UNIQUE(tenant_id,plan_id,operation),
 FOREIGN KEY(tenant_id,plan_id) REFERENCES reconforge.operational_fx_plans(tenant_id,id),
 FOREIGN KEY(tenant_id,actor_id) REFERENCES reconforge.identity_users(tenant_id,id),
 CHECK(octet_length(request_json::text)<=131072 AND octet_length(response_json::text)<=131072)
);
CREATE FUNCTION reconforge.fx_assert(ok BOOLEAN,message TEXT) RETURNS VOID LANGUAGE plpgsql SET search_path=pg_catalog AS $fx$
BEGIN IF ok IS DISTINCT FROM TRUE THEN RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='operational_fx_owner',MESSAGE=message; END IF; END $fx$;
CREATE FUNCTION reconforge.fx_object(v JSONB,keys TEXT[]) RETURNS BOOLEAN LANGUAGE sql IMMUTABLE SET search_path=pg_catalog AS $fx$
 SELECT jsonb_typeof(v)='object' AND v ?& keys AND v-keys='{}'::jsonb
$fx$;
CREATE FUNCTION reconforge.fx_minor(v JSONB) RETURNS BOOLEAN LANGUAGE sql IMMUTABLE SET search_path=pg_catalog AS $fx$
 SELECT jsonb_typeof(v)='number' AND v::text~'^(0|[1-9][0-9]*)$' AND (v::text)::numeric BETWEEN 0 AND 9000000000000000000
$fx$;
CREATE FUNCTION reconforge.fx_convert(amount NUMERIC,rate NUMERIC,fp INTEGER,lp INTEGER) RETURNS NUMERIC
 LANGUAGE sql IMMUTABLE SET search_path=pg_catalog AS $fx$
 SELECT round(amount*rate*power(10::numeric,lp-fp),0)
$fx$;
CREATE FUNCTION reconforge.fx_rate(v JSONB,day TEXT) RETURNS NUMERIC LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog AS $fx$
BEGIN
 PERFORM reconforge.fx_assert(reconforge.fx_object(v,ARRAY['rate','source','effective_at'])
 AND jsonb_typeof(v->'rate')='string' AND v->>'rate'~'^(0|[1-9][0-9]{0,11})(\.[0-9]{1,12})?$'
 AND (v->>'rate')::numeric>0 AND reconforge.irp_text(v->>'source',200)
 AND v->>'effective_at'~'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$'
 AND reconforge.irp_timestamp(v->>'effective_at') AND left(v->>'effective_at',10)=day,'FX rate requires exact bounded decimal and original UTC spot provenance');
 RETURN (v->>'rate')::numeric;
END $fx$;
CREATE FUNCTION reconforge.fx_policy(t TEXT,v JSONB) RETURNS BOOLEAN LANGUAGE sql STABLE SET search_path=pg_catalog AS $fx$
 SELECT reconforge.fx_object(v,ARRAY['currency_code','currency_precision','currency_rounding_policy','currency_registry_version','currency_registry_digest'])
 AND jsonb_typeof(v->'currency_precision')='number' AND (v->>'currency_precision')::integer BETWEEN 0 AND 8
 AND v->>'currency_code'~'^[A-Z]{3}$' AND v->>'currency_rounding_policy'='ROUND_HALF_UP'
 AND EXISTS(SELECT 1 FROM reconforge.currency_registry_snapshots s,
 jsonb_array_elements(s.snapshot_json::jsonb->'currencies') spec WHERE s.tenant_id=t
 AND s.registry_digest=v->>'currency_registry_digest' AND s.registry_version=v->>'currency_registry_version'
 AND spec->>'code'=v->>'currency_code' AND spec->>'minor_units'=v->>'currency_precision'
 AND spec->>'rounding_policy'=v->>'currency_rounding_policy')
$fx$;
CREATE FUNCTION reconforge.fx_event(t TEXT,p TEXT,a TEXT,b TEXT,actor TEXT,action TEXT,metadata JSONB) RETURNS BOOLEAN
 LANGUAGE sql STABLE SET search_path=pg_catalog AS $fx$
 SELECT EXISTS(SELECT 1 FROM reconforge.domain_audit_events x JOIN reconforge.outbox_events y ON y.tenant_id=x.tenant_id
 JOIN reconforge.operational_fx_plans z ON z.tenant_id=x.tenant_id AND z.id=p WHERE x.tenant_id=t AND x.id=a AND y.event_id=b
 AND x.actor_user_id=actor AND x.object_type='operational_finance' AND x.object_id=p AND x.action=$6 AND x.metadata_json=$7
 AND y.event_type=$6 AND y.aggregate_type='operational_finance' AND y.aggregate_id=p
 AND y.payload=$7||jsonb_build_object('audit_event_id',a)
 AND (y.workspace_id,y.organization_id,y.legal_entity_id)=(z.workspace_id,z.organization_id,z.legal_entity_id))
$fx$;
CREATE FUNCTION reconforge.fx_protect() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $fx$
BEGIN
 IF TG_TABLE_NAME='operational_fx_plans' AND TG_OP='UPDATE' AND NEW.phase=OLD.phase+1 AND (to_jsonb(NEW)-'phase')=(to_jsonb(OLD)-'phase') THEN RETURN NEW; END IF;
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='operational_fx_owner',MESSAGE='Historical FX source, policy, review and acknowledgement are immutable';
END $fx$;
CREATE FUNCTION reconforge.fx_command_actor() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $fx$
DECLARE permission TEXT; ar_permission TEXT;
BEGIN
 permission:=CASE NEW.operation WHEN 'prepare' THEN 'finance_core.manage' WHEN 'review' THEN 'finance_core.validate' ELSE 'finance_core.post' END;
 ar_permission:=CASE NEW.operation WHEN 'review' THEN 'receivables.approve' ELSE 'receivables.manage' END;
 PERFORM reconforge.fx_assert(reconforge.sales_revenue_actor(NEW.tenant_id,NEW.actor_id,permission)
 AND reconforge.sales_revenue_actor(NEW.tenant_id,NEW.actor_id,ar_permission),'FX command requires current persisted human finance and AR permissions');
 RETURN NEW;
END $fx$;
CREATE TRIGGER operational_fx_current_actor BEFORE INSERT ON reconforge.operational_fx_commands FOR EACH ROW EXECUTE FUNCTION reconforge.fx_command_actor();
CREATE FUNCTION reconforge.fx_close(t TEXT,i TEXT) RETURNS VOID LANGUAGE plpgsql SET search_path=pg_catalog AS $fx$
DECLARE p RECORD;s RECORD;e RECORD;r RECORD;l RECORD;f RECORD;c RECORD;inv RECORD;customer RECORD;receipt RECORD;prior RECORD;jn RECORD;
 a JSONB;v JSONB;q JSONB;tax JSONB;components JSONB:='[]'::jsonb;expected JSONB;equation JSONB;header JSONB;lines JSONB;item JSONB;req JSONB;
 fp INTEGER;lp INTEGER;idx INTEGER:=0;sequence INTEGER:=0;foreign_paid NUMERIC:=0;historical_paid NUMERIC:=0;all_paid NUMERIC;
 net NUMERIC;fg NUMERIC;fn NUMERIC;lg NUMERIC;ft NUMERIC;lt NUMERIC;rate NUMERIC;amount NUMERIC;cash NUMERIC;release NUMERIC;difference NUMERIC;turnover NUMERIC;
 last_day TEXT;field TEXT;account_id TEXT;account_kind TEXT;
BEGIN
 SELECT * INTO p FROM reconforge.operational_fx_plans WHERE tenant_id=t AND id=i;
 PERFORM reconforge.fx_assert(p.id IS NOT NULL,'FX1 native entry requires its complete retained owner');
 SELECT * INTO s FROM reconforge.operational_fx_sources WHERE tenant_id=t AND id=p.source_id;
 SELECT * INTO e FROM reconforge.finance_entries WHERE tenant_id=t AND id=p.entry_id;
 SELECT * INTO r FROM reconforge.operational_fx_reviews WHERE tenant_id=t AND plan_id=i;
 SELECT * INTO l FROM reconforge.operational_fx_links WHERE tenant_id=t AND plan_id=i;
 SELECT * INTO inv FROM reconforge.ar_invoices WHERE tenant_id=t AND id=s.invoice_id;
 SELECT * INTO customer FROM reconforge.ar_customers WHERE tenant_id=t AND id=inv.customer_id;
 a:=s.payload;v:=p.payload;q:=a->'request';
 PERFORM reconforge.fx_assert(s.id IS NOT NULL AND e.id IS NOT NULL AND inv.id IS NOT NULL AND customer.id IS NOT NULL
 AND reconforge.fx_object(a,ARRAY['schema_version','id','workspace_id','organization_id','legal_entity_id','request','foreign_policy','functional_policy',
 'foreign_net_minor','foreign_tax_minor','foreign_gross_minor','functional_net_minor','functional_gross_minor','tax_components','functional_allocation_policy','lines','preparer_actor_id','invoice_id','source_digest'])
 AND reconforge.fx_object(v,ARRAY['schema_version','id','source_id','workspace_id','organization_id','legal_entity_id','kind','sequence','period_id','posting_date','reason',
 'currency_code','currency_precision','source_digest','entry_id','equation','amount_minor','snapshot','preparer_actor_id','command_request','plan_digest','validation_digest'])
 AND reconforge.fx_object(q,ARRAY['workspace_id','organization_id','legal_entity_id','organization_code','entity_code','customer_code','invoice_number','posting_date','due_date','period_id','journal_code',
 'foreign_currency_code','net_minor','original_rate','country_code','transaction_class','taxes','receivable_account_code','revenue_account_code','cash_account_code','gain_account_code','loss_account_code','reason']),
 'FX source and plan require exact bounded versioned schemas');
 FOREACH field IN ARRAY ARRAY['foreign_net_minor','foreign_tax_minor','foreign_gross_minor','functional_net_minor','functional_gross_minor'] LOOP
  PERFORM reconforge.fx_assert(reconforge.fx_minor(a->field),'FX source money requires exact numeric minor units');
 END LOOP;
 FOREACH field IN ARRAY ARRAY['sequence','amount_minor','currency_precision'] LOOP
  PERFORM reconforge.fx_assert(reconforge.fx_minor(v->field),'FX plan money and scale require exact numeric minor units');
 END LOOP;
 PERFORM reconforge.fx_assert(a->>'schema_version'='operational-fx-source-v1' AND v->>'schema_version'='operational-fx-plan-v1'
 AND a->>'source_digest'=reconforge.irp_digest(a-'source_digest') AND v->>'plan_digest'=reconforge.irp_digest(v-ARRAY['plan_digest','validation_digest'])
 AND v->>'validation_digest'=reconforge.irp_digest(v->'snapshot') AND v->>'source_digest'=a->>'source_digest'
 AND (a->>'id',a->>'invoice_id',a->>'workspace_id',a->>'organization_id',a->>'legal_entity_id')=(s.id,s.invoice_id,s.workspace_id,s.organization_id,s.legal_entity_id)
 AND (v->>'id',v->>'source_id',v->>'entry_id',v->>'kind',v->>'workspace_id',v->>'organization_id',v->>'legal_entity_id')=(p.id,p.source_id,p.entry_id,p.kind,p.workspace_id,p.organization_id,p.legal_entity_id)
 AND (p.workspace_id,p.organization_id,p.legal_entity_id)=(s.workspace_id,s.organization_id,s.legal_entity_id)
 AND (q->>'workspace_id',q->>'organization_id',q->>'legal_entity_id')=(s.workspace_id,s.organization_id,s.legal_entity_id)
 AND (v->>'sequence')::integer=p.sequence AND p.id~'^FX1-[0-9a-f]{32}$' AND s.id~'^FX-[0-9a-f]{32}$'
 AND (v->>'posting_date')::date::text=v->>'posting_date' AND reconforge.irp_text(v->>'reason',500), 'FX retained source identity or financial seal differs');
 FOREACH field IN ARRAY ARRAY['organization_code','entity_code','customer_code','invoice_number','journal_code','period_id','transaction_class',
 'receivable_account_code','revenue_account_code','cash_account_code','gain_account_code','loss_account_code'] LOOP
  PERFORM reconforge.fx_assert(jsonb_typeof(q->field)='string' AND reconforge.irp_text(q->>field,160),'FX source metadata requires canonical text');
 END LOOP;
 PERFORM reconforge.fx_assert(reconforge.irp_text(q->>'reason',500) AND q->>'country_code'~'^[A-Z]{2}$'
 AND (q->>'posting_date')::date::text=q->>'posting_date' AND (q->>'due_date')::date::text=q->>'due_date'
 AND q->>'due_date'>=q->>'posting_date' AND reconforge.fx_minor(q->'net_minor') AND (q->>'net_minor')::numeric>0
 AND reconforge.fx_policy(t,a->'foreign_policy') AND reconforge.fx_policy(t,a->'functional_policy')
 AND a->'foreign_policy'->>'currency_code'=q->>'foreign_currency_code'
 AND a->'foreign_policy'->>'currency_code'<>a->'functional_policy'->>'currency_code'
 AND a->'foreign_policy'->>'currency_registry_digest'=a->'functional_policy'->>'currency_registry_digest'
 AND a->>'functional_allocation_policy'='converted-cumulative-prefix-v1','FX original currencies, dates and retained registry policies differ');
 fp:=(a->'foreign_policy'->>'currency_precision')::integer;lp:=(a->'functional_policy'->>'currency_precision')::integer;
 rate:=reconforge.fx_rate(q->'original_rate',q->>'posting_date');net:=(q->>'net_minor')::numeric;fg:=net;
 fn:=reconforge.fx_convert(net,rate,fp,lp);lg:=fn;
 PERFORM reconforge.fx_assert(jsonb_typeof(q->'taxes')='array' AND jsonb_array_length(q->'taxes')<=8
 AND (SELECT count(DISTINCT value->>'policy_id') FROM jsonb_array_elements(q->'taxes'))=jsonb_array_length(q->'taxes'), 'FX taxes require at most eight distinct ordered policy identities');
 expected:=jsonb_build_array(jsonb_build_object('account_code',q->>'receivable_account_code','debit_minor',0,'credit_minor',0),
 jsonb_build_object('account_code',q->>'revenue_account_code','debit_minor',0,'credit_minor',fn));
 FOR tax IN SELECT value FROM jsonb_array_elements(q->'taxes') LOOP
  PERFORM reconforge.fx_assert(reconforge.fx_object(tax,ARRAY['policy_id','version','country_code','transaction_class','effective_from','effective_to','rate','account_code','source','policy_digest'])
  AND tax->>'country_code'=q->>'country_code' AND tax->>'transaction_class'=q->>'transaction_class'
  AND reconforge.irp_text(tax->>'policy_id',200) AND reconforge.irp_text(tax->>'version',200) AND reconforge.irp_text(tax->>'source',200)
  AND reconforge.irp_text(tax->>'account_code',160) AND tax->>'rate'~'^(0|[1-9][0-9]{0,11})(\.[0-9]{1,12})?$'
  AND (tax->>'rate')::numeric BETWEEN 0 AND 1 AND (tax->>'effective_from')::date::text=tax->>'effective_from'
  AND (tax->>'effective_to')::date::text=tax->>'effective_to' AND q->>'posting_date' BETWEEN tax->>'effective_from' AND tax->>'effective_to'
  AND tax->>'policy_digest'=reconforge.irp_digest(tax-'policy_digest'), 'FX tax policy version, provenance, effective country/class or content seal differs');
  ft:=round(net*(tax->>'rate')::numeric,0);fg:=fg+ft;lt:=reconforge.fx_convert(fg,rate,fp,lp)-lg;lg:=lg+lt;
  components:=components||jsonb_build_array(tax||jsonb_build_object('foreign_tax_minor',ft,'functional_tax_minor',lt));
  IF lt>0 THEN expected:=expected||jsonb_build_array(jsonb_build_object('account_code',tax->>'account_code','debit_minor',0,'credit_minor',lt)); END IF;
 END LOOP;
 expected:=jsonb_set(expected,'{0,debit_minor}',to_jsonb(lg));
 PERFORM reconforge.fx_assert(fn BETWEEN 1 AND 9000000000000000000 AND fg BETWEEN 1 AND 9000000000000000000 AND lg BETWEEN 1 AND 9000000000000000000
 AND a->'lines'=expected AND a->'tax_components'=components AND (a->>'foreign_net_minor')::numeric=net
 AND (a->>'foreign_tax_minor')::numeric=fg-net AND (a->>'foreign_gross_minor')::numeric=fg
 AND (a->>'functional_net_minor')::numeric=fn AND (a->>'functional_gross_minor')::numeric=lg, 'FX independently recomputed original tax and conversion differ');
 PERFORM reconforge.fx_assert(inv.invoice_number='FX1-'||(q->>'invoice_number') AND inv.invoice_date::text=q->>'posting_date' AND inv.due_date::text=q->>'due_date'
 AND inv.currency_code=q->>'foreign_currency_code' AND inv.subtotal_minor=net AND inv.tax_minor=fg-net AND inv.total_minor=fg
 AND (inv.workspace_id,inv.organization_id,inv.legal_entity_id)=(s.workspace_id,s.organization_id,s.legal_entity_id)
 AND customer.customer_code=q->>'customer_code' AND customer.currency_code=inv.currency_code
 AND (customer.workspace_id,customer.organization_id,customer.legal_entity_id)=(s.workspace_id,s.organization_id,s.legal_entity_id)
 AND inv.currency_precision=fp AND to_jsonb(inv)->>'currency_registry_digest'=a->'foreign_policy'->>'currency_registry_digest'
 AND to_jsonb(inv)->>'currency_registry_version'=a->'foreign_policy'->>'currency_registry_version'
 AND to_jsonb(inv)->>'currency_rounding_policy'=a->'foreign_policy'->>'currency_rounding_policy'
 AND (SELECT count(*) FROM reconforge.ar_invoice_lines WHERE tenant_id=t AND invoice_id=inv.id)=1
 AND EXISTS(SELECT 1 FROM reconforge.ar_invoice_lines x WHERE x.tenant_id=t AND x.invoice_id=inv.id AND x.line_number=1
 AND x.quantity=1 AND x.quantity_text='1' AND x.unit_price_minor=net AND x.line_total_minor=net AND x.tax_minor=fg-net AND x.description=q->>'reason'), 'FX original native AR invoice and retained source differ');
 last_day:=q->>'posting_date';
 FOR prior IN SELECT z.* FROM reconforge.operational_fx_plans z WHERE z.tenant_id=t AND z.source_id=s.id AND z.sequence<p.sequence ORDER BY z.sequence LOOP
  PERFORM reconforge.fx_assert(prior.sequence=sequence AND prior.phase=2 AND (sequence=0)=(prior.kind='recognize'),'FX history requires contiguous posted recognition and settlements');
  sequence:=sequence+1;last_day:=prior.payload->>'posting_date';
  IF prior.kind='settle' THEN foreign_paid:=foreign_paid+(prior.payload->'equation'->>'foreign_minor')::numeric;
   historical_paid:=historical_paid+(prior.payload->'equation'->>'historical_release_minor')::numeric;END IF;
 END LOOP;
 PERFORM reconforge.fx_assert(sequence=p.sequence AND (p.sequence=0)=(p.kind='recognize') AND v->>'posting_date'>=last_day
 AND NOT EXISTS(SELECT 1 FROM reconforge.operational_fx_plans z WHERE z.tenant_id=t AND z.source_id=s.id AND z.sequence>p.sequence AND p.phase<2), 'FX proposal requires the exact preceding native settlement basis');
 IF p.kind='recognize' THEN
  equation:=jsonb_build_object('lines',expected);req:=q||jsonb_build_object('kind','recognize');
  PERFORM reconforge.fx_assert(v->>'posting_date'=q->>'posting_date' AND v->>'period_id'=q->>'period_id' AND v->>'reason'=q->>'reason'
  AND v->>'preparer_actor_id'=a->>'preparer_actor_id','FX recognition requires its original source preparer and accounting date');
 ELSE
  req:=v->'command_request';
  PERFORM reconforge.fx_assert(reconforge.fx_object(req,ARRAY['kind','source_id','foreign_minor','settlement_rate','period_id','posting_date','reason'])
  AND req->>'kind'='settle' AND req->>'source_id'=s.id AND req->>'period_id'=v->>'period_id' AND req->>'posting_date'=v->>'posting_date'
  AND req->>'reason'=v->>'reason' AND reconforge.fx_minor(req->'foreign_minor') AND (req->>'foreign_minor')::numeric>0, 'FX settlement request requires exact original source and foreign amount');
  amount:=(req->>'foreign_minor')::numeric;
  PERFORM reconforge.fx_assert(foreign_paid+amount<=fg AND historical_paid=reconforge.fx_convert(foreign_paid,rate,fp,lp), 'FX settlement exceeds the native foreign residual or differs from historical cumulative release');
  release:=reconforge.fx_convert(foreign_paid+amount,rate,fp,lp)-historical_paid;
  cash:=reconforge.fx_convert(amount,reconforge.fx_rate(req->'settlement_rate',v->>'posting_date'),fp,lp);difference:=cash-release;
  PERFORM reconforge.fx_assert(cash BETWEEN 1 AND 9000000000000000000,'FX settlement requires positive bounded functional cash');
  expected:=jsonb_build_array(jsonb_build_object('account_code',q->>'cash_account_code','debit_minor',cash,'credit_minor',0));
  IF release>0 THEN expected:=expected||jsonb_build_array(jsonb_build_object('account_code',q->>'receivable_account_code','debit_minor',0,'credit_minor',release)); END IF;
  IF difference<>0 THEN expected:=expected||jsonb_build_array(jsonb_build_object('account_code',q->>(CASE WHEN difference>0 THEN 'gain_account_code' ELSE 'loss_account_code' END),
   'debit_minor',greatest(-difference,0),'credit_minor',greatest(difference,0))); END IF;
  equation:=jsonb_build_object('foreign_minor',amount,'foreign_before_minor',foreign_paid,'foreign_after_minor',foreign_paid+amount,
   'historical_before_minor',historical_paid,'historical_release_minor',release,'historical_after_minor',historical_paid+release,
   'functional_cash_minor',cash,'realized_fx_minor',difference,'settlement_rate',req->'settlement_rate','amount_minor',cash+greatest(-difference,0),'lines',expected);
 END IF;
 SELECT sum((value->>'debit_minor')::numeric) INTO turnover FROM jsonb_array_elements(expected);
 PERFORM reconforge.fx_assert(v->'equation'=equation AND v->'command_request'=req AND (v->>'amount_minor')::numeric=turnover
 AND turnover BETWEEN 1 AND 9000000000000000000 AND v->>'currency_code'=a->'functional_policy'->>'currency_code'
 AND (v->>'currency_precision')::integer=lp,'FX proposal differs from the independent settlement equation or exact debit turnover');
 SELECT * INTO jn FROM reconforge.finance_journals WHERE tenant_id=t AND id=e.journal_id;
 PERFORM reconforge.fx_assert(jn.id IS NOT NULL AND jn.journal_code=q->>'journal_code' AND e.entry_number=upper(p.id)
 AND e.source_type='Manual' AND e.external_reference='FX:'||s.id||':'||p.kind AND e.period_id=v->>'period_id'
 AND e.posting_date::text=v->>'posting_date' AND e.description=v->>'reason' AND e.preparer_actor_id=v->>'preparer_actor_id'
 AND e.reverses_posting_id IS NULL AND e.currency_code=a->'functional_policy'->>'currency_code' AND e.currency_precision=lp
 AND to_jsonb(e)->>'currency_registry_digest'=a->'functional_policy'->>'currency_registry_digest'
 AND to_jsonb(e)->>'currency_registry_version'=a->'functional_policy'->>'currency_registry_version'
 AND to_jsonb(e)->>'currency_rounding_policy'=a->'functional_policy'->>'currency_rounding_policy'
 AND EXISTS(SELECT 1 FROM reconforge.organizations o JOIN reconforge.legal_entities ent ON ent.tenant_id=o.tenant_id AND ent.organization_id=o.id
 WHERE o.tenant_id=t AND o.id=s.organization_id AND ent.id=s.legal_entity_id AND o.application_workspace_id=s.workspace_id
 AND e.organization_code=o.organization_code AND e.entity_code=ent.entity_code AND ent.currency_code=e.currency_code),'FX functional native GL hierarchy and retained original policy differ');
 SELECT jsonb_object_agg(key,value) INTO header FROM jsonb_each(to_jsonb(e)) WHERE key=ANY(ARRAY['id','workspace_id','journal_id','period_id','entry_number','posting_date','description',
 'external_reference','source_type','currency_code','currency_precision','currency_rounding_policy','currency_registry_version','currency_registry_digest','preparer_actor_id','reverses_posting_id']);
 header:=header||jsonb_build_object('organization_id',s.organization_id,'legal_entity_id',s.legal_entity_id);
 SELECT jsonb_agg(jsonb_build_object('line_number',x.line_number,'account_id',x.account_id,'description',x.description,'debit_minor',x.debit_minor,'credit_minor',x.credit_minor,
 'dimensions',COALESCE((SELECT jsonb_object_agg(d.dimension_id,d.dimension_value_id) FROM reconforge.finance_entry_line_dimensions d WHERE d.tenant_id=t AND d.entry_line_id=x.id),'{}'::jsonb)) ORDER BY x.line_number)
 INTO lines FROM reconforge.finance_entry_lines x WHERE x.tenant_id=t AND x.entry_id=e.id;
 PERFORM reconforge.fx_assert(v->'snapshot'=jsonb_build_object('schema_version','finance-entry-review-v1','entry',header,'lines',lines)
 AND jsonb_array_length(lines)=jsonb_array_length(expected),'FX complete native snapshot differs from retained exact accounting');
 FOR item IN SELECT value FROM jsonb_array_elements(expected) LOOP
  SELECT id INTO account_id FROM reconforge.finance_accounts WHERE tenant_id=t AND workspace_id=s.workspace_id AND chart_id=jn.chart_id AND account_code=item->>'account_code';
  PERFORM reconforge.fx_assert(account_id IS NOT NULL AND lines->idx->>'account_id'=account_id
  AND (lines->idx->>'debit_minor')::numeric=(item->>'debit_minor')::numeric AND (lines->idx->>'credit_minor')::numeric=(item->>'credit_minor')::numeric
  AND lines->idx->>'description'=v->>'reason' AND lines->idx->'dimensions'='{}'::jsonb,'FX native GL line differs from independently recomputed source equation');idx:=idx+1;
 END LOOP;
 PERFORM reconforge.fx_assert((SELECT count(DISTINCT q->>x) FROM unnest(ARRAY['receivable_account_code','revenue_account_code','cash_account_code','gain_account_code','loss_account_code']) x)=5,'FX accounting roles must be distinct');
 FOREACH field IN ARRAY ARRAY['receivable','revenue','cash','gain','loss'] LOOP
  SELECT account_type INTO account_kind FROM reconforge.finance_accounts WHERE tenant_id=t AND workspace_id=s.workspace_id AND chart_id=jn.chart_id AND account_code=q->>(field||'_account_code');
  PERFORM reconforge.fx_assert(account_kind=CASE WHEN field IN ('receivable','cash') THEN 'Asset' WHEN field IN ('revenue','gain') THEN 'Income' ELSE 'Expense' END,'FX original account classifications differ');
 END LOOP;
 FOR tax IN SELECT value FROM jsonb_array_elements(q->'taxes') LOOP
  SELECT account_type INTO account_kind FROM reconforge.finance_accounts WHERE tenant_id=t AND workspace_id=s.workspace_id AND chart_id=jn.chart_id AND account_code=tax->>'account_code';
  PERFORM reconforge.fx_assert(account_kind='Liability' AND NOT EXISTS(SELECT 1 FROM unnest(ARRAY['receivable_account_code','revenue_account_code','cash_account_code','gain_account_code','loss_account_code']) x WHERE q->>x=tax->>'account_code'),'FX tax components require distinct liability account roles');
 END LOOP;
 PERFORM reconforge.fx_assert(reconforge.fx_event(t,i,p.audit_event_id,p.outbox_event_id,e.preparer_actor_id,'operational_fx_prepared',jsonb_build_object('plan_digest',v->>'plan_digest')),'FX preparation requires complete native audit and outbox evidence');
 IF p.phase<2 THEN PERFORM reconforge.fx_assert(EXISTS(SELECT 1 FROM reconforge.fiscal_periods z WHERE z.tenant_id=t AND z.id=e.period_id AND z.status='Open' AND e.posting_date::date BETWEEN z.start_date AND z.end_date),'Pending FX plan requires its original open period'); END IF;
 IF p.phase=0 THEN PERFORM reconforge.fx_assert(e.status='Draft' AND r IS NULL AND l IS NULL,'Prepared FX phase differs from native GL'); END IF;
 IF p.phase>=1 THEN PERFORM reconforge.fx_assert(r.plan_id IS NOT NULL AND r.reviewer_actor_id<>e.preparer_actor_id AND e.validator_actor_id=r.reviewer_actor_id
 AND e.validation_digest=v->>'validation_digest' AND e.status='Validated'
 AND reconforge.fx_event(t,i,r.audit_event_id,r.outbox_event_id,r.reviewer_actor_id,'operational_fx_reviewed',jsonb_build_object('plan_digest',v->>'plan_digest')),'FX independent native review differs from retained owner'); END IF;
 IF p.phase<2 THEN PERFORM reconforge.fx_assert(l IS NULL AND NOT EXISTS(SELECT 1 FROM reconforge.finance_posting_effects z WHERE z.tenant_id=t AND z.entry_id=p.entry_id),'FX native effect requires atomic owner publication'); END IF;
 IF p.phase=2 THEN
  SELECT * INTO f FROM reconforge.finance_posting_effects WHERE tenant_id=t AND id=l.posting_effect_id;
  PERFORM reconforge.fx_assert(l.plan_id IS NOT NULL AND f.id IS NOT NULL AND f.entry_id=p.entry_id AND f.snapshot_json=v->'snapshot' AND f.validation_digest=v->>'validation_digest'
  AND f.posted_actor_id=l.posted_actor_id AND l.posted_actor_id NOT IN (e.preparer_actor_id,r.reviewer_actor_id)
  AND NOT EXISTS(SELECT 1 FROM reconforge.finance_posting_effects z WHERE z.tenant_id=t AND z.reverses_effect_id=f.id)
  AND reconforge.fx_event(t,i,l.audit_event_id,l.outbox_event_id,l.posted_actor_id,'operational_fx_posted',jsonb_build_object('plan_digest',v->>'plan_digest','posting_effect_id',f.id)), 'FX publication requires three distinct humans and exact unreversed native effect');
  IF p.kind='settle' THEN
   SELECT * INTO receipt FROM reconforge.ar_receipts WHERE tenant_id=t AND id=l.receipt_id;
   PERFORM reconforge.fx_assert(receipt.id IS NOT NULL AND receipt.receipt_number=upper(p.id) AND receipt.receipt_date::text=v->>'posting_date'
   AND receipt.currency_code=inv.currency_code AND receipt.amount_minor=(equation->>'foreign_minor')::numeric AND receipt.status='Posted'
   AND (receipt.workspace_id,receipt.organization_id,receipt.legal_entity_id,receipt.customer_id)=(inv.workspace_id,inv.organization_id,inv.legal_entity_id,inv.customer_id)
   AND receipt.currency_precision=fp AND to_jsonb(receipt)->>'currency_registry_digest'=a->'foreign_policy'->>'currency_registry_digest'
   AND receipt.posted_by=(SELECT username FROM reconforge.identity_users WHERE tenant_id=t AND id=l.posted_actor_id)
   AND (SELECT count(*) FROM reconforge.ar_receipt_allocations WHERE tenant_id=t AND receipt_id=receipt.id)=1
   AND EXISTS(SELECT 1 FROM reconforge.ar_receipt_allocations z WHERE z.tenant_id=t AND z.receipt_id=receipt.id AND z.invoice_id=inv.id AND z.amount_minor=receipt.amount_minor), 'FX settlement requires exact foreign native receipt and single source allocation');
  ELSE PERFORM reconforge.fx_assert(l.receipt_id IS NULL,'FX recognition cannot create a cash receipt'); END IF;
 END IF;
 SELECT COALESCE(sum((payload->'equation'->>'foreign_minor')::numeric),0) INTO all_paid FROM reconforge.operational_fx_plans WHERE tenant_id=t AND source_id=s.id AND phase=2 AND kind='settle';
 PERFORM reconforge.fx_assert(all_paid=(SELECT COALESCE(sum(amount_minor),0) FROM reconforge.ar_receipt_allocations WHERE tenant_id=t AND invoice_id=inv.id)
 AND inv.status=CASE WHEN all_paid=fg THEN 'Paid' WHEN all_paid>0 THEN 'PartiallyPaid'
 WHEN EXISTS(SELECT 1 FROM reconforge.operational_fx_plans z WHERE z.tenant_id=t AND z.source_id=s.id AND z.sequence=0 AND z.phase>=1) THEN 'Approved' ELSE 'Submitted' END,
 'FX native AR balance and status require exact posted owner settlements');
 FOR c IN SELECT * FROM reconforge.operational_fx_commands WHERE tenant_id=t AND plan_id=i LOOP
  PERFORM reconforge.fx_assert((c.workspace_id,c.organization_id,c.legal_entity_id)=(p.workspace_id,p.organization_id,p.legal_entity_id)
  AND reconforge.irp_digest(c.request_json)=c.request_digest AND c.request_json=jsonb_build_object('operation',c.operation,'actor_id',c.actor_id,'request',
  CASE WHEN c.operation='prepare' THEN req ELSE jsonb_build_object('plan_id',i,'expected_plan_digest',v->>'plan_digest','reason',CASE WHEN c.operation='review' THEN r.reason ELSE l.reason END) END)
  AND c.actor_id=CASE WHEN c.operation='prepare' THEN e.preparer_actor_id WHEN c.operation='review' THEN r.reviewer_actor_id ELSE l.posted_actor_id END
  AND c.response_json=v||jsonb_build_object('phase',CASE WHEN c.operation='prepare' THEN 0 WHEN c.operation='review' THEN 1 ELSE 2 END,
  'status',CASE WHEN c.operation='prepare' THEN 'Prepared' WHEN c.operation='review' THEN 'Reviewed' ELSE 'Posted' END,
  'reviewer_actor_id',CASE WHEN c.operation='prepare' THEN NULL ELSE r.reviewer_actor_id END,
  'posting_effect_id',CASE WHEN c.operation='post' THEN l.posting_effect_id ELSE NULL END,
  'receipt_id',CASE WHEN c.operation='post' THEN l.receipt_id ELSE NULL END),'FX command requires exact retained actor, immutable request and historical acknowledgement');
 END LOOP;
 PERFORM reconforge.fx_assert((SELECT count(*) FROM reconforge.operational_fx_commands WHERE tenant_id=t AND plan_id=i)=p.phase+1,'Every FX phase requires its immutable command acknowledgement');
END $fx$;
CREATE FUNCTION reconforge.fx_reverse_close() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $fx$
DECLARE changed JSONB;row_json JSONB;selected_source TEXT;entry TEXT;invoice TEXT;receipt TEXT;number TEXT;plan RECORD;
BEGIN
 FOREACH row_json IN ARRAY ARRAY[CASE WHEN TG_OP<>'INSERT' THEN to_jsonb(OLD) END,CASE WHEN TG_OP<>'DELETE' THEN to_jsonb(NEW) END] LOOP
  IF row_json IS NULL THEN CONTINUE; END IF;changed:=row_json;selected_source:=NULL;entry:=NULL;invoice:=NULL;receipt:=NULL;number:=NULL;
  IF TG_TABLE_NAME='operational_fx_sources' THEN
   selected_source:=changed->>'id';
   PERFORM reconforge.fx_assert(EXISTS(SELECT 1 FROM reconforge.operational_fx_plans z WHERE z.tenant_id=changed->>'tenant_id' AND z.source_id=selected_source AND z.sequence=0 AND z.kind='recognize'),'FX source requires its atomic recognition proposal');
  ELSIF TG_TABLE_NAME='operational_fx_plans' THEN selected_source:=changed->>'source_id';
  ELSIF TG_TABLE_NAME IN ('finance_entries','finance_entry_lines','finance_entry_line_dimensions','finance_posting_effects') THEN
   entry:=CASE WHEN TG_TABLE_NAME='finance_entries' THEN changed->>'id' ELSE changed->>'entry_id' END;
   IF TG_TABLE_NAME='finance_entry_line_dimensions' THEN SELECT entry_id INTO entry FROM reconforge.finance_entry_lines WHERE tenant_id=changed->>'tenant_id' AND id=changed->>'entry_line_id'; END IF;
   IF TG_TABLE_NAME='finance_posting_effects' AND changed->>'reverses_effect_id' IS NOT NULL THEN SELECT entry_id INTO entry FROM reconforge.finance_posting_effects WHERE tenant_id=changed->>'tenant_id' AND id=changed->>'reverses_effect_id'; END IF;
   IF TG_TABLE_NAME='finance_entries' THEN number:=changed->>'entry_number';
   ELSE SELECT entry_number INTO number FROM reconforge.finance_entries WHERE tenant_id=changed->>'tenant_id' AND id=entry;END IF;
   IF upper(left(COALESCE(number,''),4))<>'FX1-' THEN CONTINUE; END IF;
   PERFORM reconforge.fx_assert(EXISTS(SELECT 1 FROM reconforge.operational_fx_plans z WHERE z.tenant_id=changed->>'tenant_id' AND z.entry_id=entry),'Reserved FX1 native GL entry requires its source');
  ELSIF TG_TABLE_NAME IN ('ar_invoices','ar_invoice_lines','ar_receipt_allocations') THEN
   invoice:=CASE WHEN TG_TABLE_NAME='ar_invoices' THEN changed->>'id' ELSE changed->>'invoice_id' END;
   IF TG_TABLE_NAME='ar_invoices' THEN number:=changed->>'invoice_number';
   ELSE SELECT invoice_number INTO number FROM reconforge.ar_invoices WHERE tenant_id=changed->>'tenant_id' AND id=invoice;END IF;
   IF upper(left(COALESCE(number,changed->>'invoice_number',''),4))<>'FX1-' THEN CONTINUE; END IF;
   SELECT id INTO selected_source FROM reconforge.operational_fx_sources WHERE tenant_id=changed->>'tenant_id' AND invoice_id=invoice;
   PERFORM reconforge.fx_assert(selected_source IS NOT NULL,'Reserved FX1 native AR invoice requires its historical source');
  ELSIF TG_TABLE_NAME='ar_receipts' THEN
   receipt:=changed->>'id';IF upper(left(COALESCE(changed->>'receipt_number',''),4))<>'FX1-' THEN CONTINUE; END IF;
   PERFORM reconforge.fx_assert(EXISTS(SELECT 1 FROM reconforge.operational_fx_links z WHERE z.tenant_id=changed->>'tenant_id' AND z.receipt_id=receipt),'Reserved FX1 native receipt requires its complete posted source');
  ELSIF TG_TABLE_NAME IN ('finance_accounts','finance_journals','fiscal_periods','legal_entities','ar_customers') THEN
   FOR plan IN SELECT z.id,z.tenant_id FROM reconforge.operational_fx_plans z
   JOIN reconforge.operational_fx_sources source ON source.tenant_id=z.tenant_id AND source.id=z.source_id
   JOIN reconforge.finance_entries native ON native.tenant_id=z.tenant_id AND native.id=z.entry_id
   JOIN reconforge.ar_invoices ar ON ar.tenant_id=source.tenant_id AND ar.id=source.invoice_id
   WHERE z.tenant_id=changed->>'tenant_id' AND
   ((TG_TABLE_NAME='finance_accounts' AND native.workspace_id=changed->>'workspace_id')
   OR (TG_TABLE_NAME='finance_journals' AND native.journal_id=changed->>'id')
   OR (TG_TABLE_NAME='fiscal_periods' AND z.phase<2 AND native.period_id=changed->>'id')
   OR (TG_TABLE_NAME='legal_entities' AND source.legal_entity_id=changed->>'id')
   OR (TG_TABLE_NAME='ar_customers' AND ar.customer_id=changed->>'id')) LOOP
    PERFORM reconforge.fx_close(plan.tenant_id,plan.id);
   END LOOP;CONTINUE;
  END IF;
  FOR plan IN SELECT z.* FROM reconforge.operational_fx_plans z LEFT JOIN reconforge.operational_fx_links link ON link.tenant_id=z.tenant_id AND link.plan_id=z.id
   WHERE z.tenant_id=changed->>'tenant_id' AND (z.source_id=selected_source OR z.entry_id=entry OR z.id=changed->>'plan_id'
   OR z.id=changed->>'id' OR z.id=changed->>'object_id' OR z.id=changed->>'aggregate_id' OR link.receipt_id=receipt)
   LOOP PERFORM reconforge.fx_close(plan.tenant_id,plan.id);END LOOP;
 END LOOP;RETURN NULL;
END $fx$;
DO $fx$ DECLARE n TEXT; BEGIN
 FOREACH n IN ARRAY ARRAY['operational_fx_sources','operational_fx_plans','operational_fx_reviews','operational_fx_links','operational_fx_commands'] LOOP
  EXECUTE format('ALTER TABLE reconforge.%I ENABLE ROW LEVEL SECURITY',n);EXECUTE format('ALTER TABLE reconforge.%I FORCE ROW LEVEL SECURITY',n);
  IF n IN ('operational_fx_sources','operational_fx_plans','operational_fx_commands') THEN
   EXECUTE format('CREATE POLICY scope ON reconforge.%I USING(reconforge.irp_scope(tenant_id,workspace_id,organization_id,legal_entity_id)) WITH CHECK(reconforge.irp_scope(tenant_id,workspace_id,organization_id,legal_entity_id))',n);
  ELSE EXECUTE format('CREATE POLICY scope ON reconforge.%I USING(EXISTS(SELECT 1 FROM reconforge.operational_fx_plans p WHERE p.tenant_id=%I.tenant_id AND p.id=%I.plan_id)) WITH CHECK(EXISTS(SELECT 1 FROM reconforge.operational_fx_plans p WHERE p.tenant_id=%I.tenant_id AND p.id=%I.plan_id))',n,n,n,n,n); END IF;
  EXECUTE format('CREATE TRIGGER immutable BEFORE UPDATE OR DELETE ON reconforge.%I FOR EACH ROW EXECUTE FUNCTION reconforge.fx_protect()',n);
 END LOOP;
 FOREACH n IN ARRAY ARRAY['operational_fx_sources','operational_fx_plans','operational_fx_reviews','operational_fx_links','operational_fx_commands',
 'finance_entries','finance_entry_lines','finance_entry_line_dimensions','finance_posting_effects','ar_invoices','ar_invoice_lines','ar_receipts','ar_receipt_allocations',
 'domain_audit_events','outbox_events','finance_accounts','finance_journals','fiscal_periods','legal_entities','ar_customers'] LOOP
  EXECUTE format('CREATE CONSTRAINT TRIGGER operational_fx_owner_closure AFTER INSERT OR UPDATE OR DELETE ON reconforge.%I DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION reconforge.fx_reverse_close()',n);
 END LOOP;
END $fx$;
"""

DOWNGRADE_SQL = r"""
DO $fx$ BEGIN IF EXISTS(SELECT 1 FROM reconforge.operational_fx_sources) THEN RAISE EXCEPTION 'FX downgrade refuses to discard retained AR and financial evidence'; END IF;END $fx$;
DO $fx$ DECLARE n TEXT; BEGIN
 FOREACH n IN ARRAY ARRAY['operational_fx_sources','operational_fx_plans','operational_fx_reviews','operational_fx_links','operational_fx_commands',
 'finance_entries','finance_entry_lines','finance_entry_line_dimensions','finance_posting_effects','ar_invoices','ar_invoice_lines','ar_receipts','ar_receipt_allocations',
 'domain_audit_events','outbox_events','finance_accounts','finance_journals','fiscal_periods','legal_entities','ar_customers'] LOOP EXECUTE format('DROP TRIGGER operational_fx_owner_closure ON reconforge.%I',n);END LOOP;
END $fx$;
DROP TABLE reconforge.operational_fx_commands,reconforge.operational_fx_links,reconforge.operational_fx_reviews,reconforge.operational_fx_plans,reconforge.operational_fx_sources;
DROP FUNCTION reconforge.fx_reverse_close(),reconforge.fx_protect(),reconforge.fx_command_actor();
DROP FUNCTION reconforge.fx_close(TEXT,TEXT),reconforge.fx_event(TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,JSONB);
DROP FUNCTION reconforge.fx_policy(TEXT,JSONB),reconforge.fx_rate(JSONB,TEXT),reconforge.fx_convert(NUMERIC,NUMERIC,INTEGER,INTEGER),reconforge.fx_minor(JSONB),reconforge.fx_object(JSONB,TEXT[]),reconforge.fx_assert(BOOLEAN,TEXT);
"""
