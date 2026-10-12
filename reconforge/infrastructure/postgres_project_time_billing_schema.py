"""Additive whole approved time → native AR/Project revenue → cash closure.

Unposted cancellation preserves its Submitted AR and all immutable history.
Destructive downgrade is refused after any billing source has been recorded.
"""

UPGRADE_SQL = r"""
DO $pb$ BEGIN
 IF EXISTS(SELECT 1 FROM reconforge.finance_entries WHERE upper(entry_number) LIKE 'PB1-%' OR upper(entry_number) LIKE 'PB1C-%'
 OR upper(id) LIKE 'PB1-%' OR upper(id) LIKE 'PB1C-%') THEN RAISE EXCEPTION 'PB1 native namespace already exists without its owner';END IF;
END $pb$;
CREATE FUNCTION reconforge.pb_assert(ok BOOLEAN,message TEXT) RETURNS VOID LANGUAGE plpgsql SET search_path=pg_catalog AS $pb$
BEGIN IF ok IS DISTINCT FROM TRUE THEN RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='project_billing_owner',MESSAGE=message;END IF;END $pb$;
CREATE TABLE reconforge.pb_prices(
 tenant_id TEXT NOT NULL,id TEXT NOT NULL CHECK(id~'^PBP-[0-9a-f]{32}$'),workspace_id TEXT NOT NULL,organization_id TEXT NOT NULL,legal_entity_id TEXT NOT NULL,
 project_id TEXT NOT NULL,customer_code TEXT NOT NULL,valid_from DATE NOT NULL,valid_through DATE NOT NULL CHECK(valid_through>=valid_from),
 currency_code TEXT NOT NULL,hourly_price_minor BIGINT NOT NULL CHECK(hourly_price_minor BETWEEN 1 AND 4500000000000000000),
 source_json JSONB NOT NULL CHECK(jsonb_typeof(source_json)='object' AND octet_length(source_json::TEXT)<=65536),source_digest TEXT NOT NULL CHECK(source_digest~'^[0-9a-f]{64}$'),preparer_id TEXT NOT NULL,approver_id TEXT,
 audit_id TEXT NOT NULL,outbox_id TEXT NOT NULL,approve_audit_id TEXT,approve_outbox_id TEXT,
 PRIMARY KEY(tenant_id,id),FOREIGN KEY(tenant_id,project_id) REFERENCES reconforge.hc_projects(tenant_id,id));
CREATE TABLE reconforge.pb_plans(
 tenant_id TEXT NOT NULL,id TEXT NOT NULL,workspace_id TEXT NOT NULL,organization_id TEXT NOT NULL,legal_entity_id TEXT NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN('Invoice','Collection')),parent_id TEXT,ar_invoice_id TEXT NOT NULL,entry_id TEXT NOT NULL,
 amount_minor BIGINT NOT NULL CHECK(amount_minor BETWEEN 1 AND 4500000000000000000),phase INTEGER NOT NULL CHECK(phase BETWEEN 0 AND 3),payload JSONB NOT NULL CHECK(jsonb_typeof(payload)='object' AND octet_length(payload::TEXT)<=2097152),
 preparer_id TEXT NOT NULL,reviewer_id TEXT,poster_id TEXT,canceller_id TEXT,effect_id TEXT,receipt_id TEXT,
 audit_id TEXT NOT NULL,outbox_id TEXT NOT NULL,review_audit_id TEXT,review_outbox_id TEXT,post_audit_id TEXT,post_outbox_id TEXT,cancel_audit_id TEXT,cancel_outbox_id TEXT,
 PRIMARY KEY(tenant_id,id),UNIQUE(tenant_id,entry_id),UNIQUE(tenant_id,effect_id),UNIQUE(tenant_id,receipt_id),
 CHECK((kind='Invoice' AND id~'^PB1-[0-9a-f]{32}$' AND parent_id IS NULL AND receipt_id IS NULL)
 OR(kind='Collection' AND id~'^PB1C-[0-9a-f]{32}$' AND parent_id IS NOT NULL AND phase<>3)),
 FOREIGN KEY(tenant_id,parent_id) REFERENCES reconforge.pb_plans(tenant_id,id),
 FOREIGN KEY(tenant_id,ar_invoice_id) REFERENCES reconforge.ar_invoices(tenant_id,id),
 FOREIGN KEY(tenant_id,entry_id) REFERENCES reconforge.finance_entries(tenant_id,id),
 FOREIGN KEY(tenant_id,effect_id) REFERENCES reconforge.finance_posting_effects(tenant_id,id),
 FOREIGN KEY(tenant_id,receipt_id) REFERENCES reconforge.ar_receipts(tenant_id,id));
CREATE UNIQUE INDEX pb_original_invoice ON reconforge.pb_plans(tenant_id,ar_invoice_id) WHERE kind='Invoice';
CREATE UNIQUE INDEX pb_pending_collection ON reconforge.pb_plans(tenant_id,parent_id) WHERE kind='Collection' AND phase<2;
ALTER TABLE reconforge.finance_accounts ADD CONSTRAINT pb_native_account_identity UNIQUE(tenant_id,id,workspace_id,chart_id,account_code,account_type);
CREATE TABLE reconforge.pb_account_pins(
 tenant_id TEXT NOT NULL,invoice_id TEXT NOT NULL,role TEXT NOT NULL CHECK(role IN('receivable','revenue','cash')),
 account_id TEXT NOT NULL,workspace_id TEXT NOT NULL,chart_id TEXT NOT NULL,account_code TEXT NOT NULL,account_type TEXT NOT NULL,
 PRIMARY KEY(tenant_id,invoice_id,role),UNIQUE(tenant_id,invoice_id,account_id),
 FOREIGN KEY(tenant_id,invoice_id) REFERENCES reconforge.pb_plans(tenant_id,id),
 FOREIGN KEY(tenant_id,account_id,workspace_id,chart_id,account_code,account_type) REFERENCES reconforge.finance_accounts(tenant_id,id,workspace_id,chart_id,account_code,account_type));
ALTER TABLE reconforge.ar_invoices ADD COLUMN pb_owner_id TEXT;
ALTER TABLE reconforge.ar_invoices ADD CONSTRAINT pb_invoice_owner UNIQUE(tenant_id,pb_owner_id);
ALTER TABLE reconforge.ar_invoices ADD CONSTRAINT pb_invoice_source FOREIGN KEY(tenant_id,pb_owner_id)
 REFERENCES reconforge.pb_plans(tenant_id,id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE reconforge.ar_receipts ADD COLUMN pb_owner_id TEXT;
ALTER TABLE reconforge.ar_receipts ADD CONSTRAINT pb_receipt_owner UNIQUE(tenant_id,pb_owner_id);
ALTER TABLE reconforge.ar_receipts ADD CONSTRAINT pb_receipt_source FOREIGN KEY(tenant_id,pb_owner_id)
 REFERENCES reconforge.pb_plans(tenant_id,id) DEFERRABLE INITIALLY DEFERRED;
CREATE FUNCTION reconforge.pb_native_ar_owner() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $pb$
DECLARE selector TEXT;
BEGIN
 IF TG_OP='UPDATE' THEN
  PERFORM reconforge.pb_assert(NEW.pb_owner_id IS NOT DISTINCT FROM OLD.pb_owner_id,'Original native AR source link cannot detach or reassign');RETURN NEW;
 END IF;
 selector:=NULLIF(current_setting(CASE TG_TABLE_NAME WHEN 'ar_invoices' THEN 'app.pb_invoice_source' ELSE 'app.pb_collection_source' END,true),'');
 PERFORM reconforge.pb_assert(NEW.pb_owner_id IS NULL,'Native owner link is assigned by its composing transaction');
 IF selector IS NOT NULL THEN
  PERFORM reconforge.pb_assert(selector~CASE TG_TABLE_NAME WHEN 'ar_invoices' THEN '^PB1-[0-9a-f]{32}$' ELSE '^PB1C-[0-9a-f]{32}$' END,'Unknown native billing source selector');
  NEW.pb_owner_id:=selector;
 END IF;RETURN NEW;
END $pb$;
CREATE TRIGGER pb_original_ar_invoice BEFORE INSERT OR UPDATE ON reconforge.ar_invoices FOR EACH ROW EXECUTE FUNCTION reconforge.pb_native_ar_owner();
CREATE TRIGGER pb_original_ar_receipt BEFORE INSERT OR UPDATE ON reconforge.ar_receipts FOR EACH ROW EXECUTE FUNCTION reconforge.pb_native_ar_owner();
CREATE TABLE reconforge.pb_time_claims(
 tenant_id TEXT NOT NULL,time_id TEXT NOT NULL,invoice_id TEXT NOT NULL,source_digest TEXT NOT NULL,
 PRIMARY KEY(tenant_id,time_id,invoice_id),FOREIGN KEY(tenant_id,time_id) REFERENCES reconforge.hc_times(tenant_id,id),
 FOREIGN KEY(tenant_id,invoice_id) REFERENCES reconforge.pb_plans(tenant_id,id));
CREATE TABLE reconforge.pb_claim_events(
 tenant_id TEXT NOT NULL,id TEXT NOT NULL,time_id TEXT NOT NULL,invoice_id TEXT NOT NULL,sequence INTEGER NOT NULL CHECK(sequence>0),
 operation TEXT NOT NULL CHECK(operation IN('Claim','Consume','Release')),source_digest TEXT NOT NULL,actor_id TEXT NOT NULL,audit_id TEXT NOT NULL,outbox_id TEXT NOT NULL,
 PRIMARY KEY(tenant_id,id),UNIQUE(tenant_id,time_id,sequence),UNIQUE(tenant_id,time_id,invoice_id,operation),
 FOREIGN KEY(tenant_id,time_id,invoice_id) REFERENCES reconforge.pb_time_claims(tenant_id,time_id,invoice_id));
CREATE TABLE reconforge.pb_claim_heads(
 tenant_id TEXT NOT NULL,time_id TEXT NOT NULL,invoice_id TEXT NOT NULL,sequence INTEGER NOT NULL,state TEXT NOT NULL CHECK(state IN('Active','Consumed','Released')),
 PRIMARY KEY(tenant_id,time_id),FOREIGN KEY(tenant_id,time_id,invoice_id) REFERENCES reconforge.pb_time_claims(tenant_id,time_id,invoice_id),
 FOREIGN KEY(tenant_id,time_id,sequence) REFERENCES reconforge.pb_claim_events(tenant_id,time_id,sequence) DEFERRABLE INITIALLY DEFERRED);
CREATE TABLE reconforge.pb_commands(
 tenant_id TEXT NOT NULL,workspace_id TEXT NOT NULL,organization_id TEXT NOT NULL,legal_entity_id TEXT NOT NULL,command_id TEXT NOT NULL,
 operation TEXT NOT NULL CHECK(operation IN('manage','approve_price','prepare','collect','review','post','cancel')),actor_id TEXT NOT NULL,
 request_digest TEXT NOT NULL CHECK(request_digest~'^[0-9a-f]{64}$'),request_json JSONB NOT NULL CHECK(jsonb_typeof(request_json)='object' AND octet_length(request_json::TEXT)<=2097152),
 response_json JSONB NOT NULL CHECK(jsonb_typeof(response_json)='object' AND octet_length(response_json::TEXT)<=2097152),PRIMARY KEY(tenant_id,workspace_id,command_id),CHECK(length(command_id) BETWEEN 1 AND 140));

CREATE FUNCTION reconforge.pb_guard() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $pb$
DECLARE actor TEXT;permission TEXT;customer RECORD;exposure NUMERIC;
BEGIN
 IF TG_OP='DELETE' THEN PERFORM reconforge.pb_assert(FALSE,'Original billing history cannot be deleted');END IF;
 IF TG_TABLE_NAME='pb_prices' THEN
  PERFORM pg_advisory_xact_lock(hashtextextended(jsonb_build_array(NEW.tenant_id,NEW.workspace_id,NEW.organization_id,NEW.legal_entity_id,NEW.customer_code,NEW.project_id,'pb-price')::TEXT,0));
 END IF;
 IF TG_OP='UPDATE' THEN
  IF TG_TABLE_NAME='pb_prices' THEN
   PERFORM reconforge.pb_assert(OLD.approver_id IS NULL AND NEW.approver_id IS NOT NULL AND NEW.approver_id<>NEW.preparer_id
    AND (to_jsonb(NEW)-ARRAY['approver_id','approve_audit_id','approve_outbox_id'])=(to_jsonb(OLD)-ARRAY['approver_id','approve_audit_id','approve_outbox_id']),
    'Original price changes only by one independent approval');
   actor:=NEW.approver_id;permission:='approve_price';
  ELSIF TG_TABLE_NAME='pb_plans' THEN
   PERFORM reconforge.pb_assert((OLD.phase,NEW.phase) IN((0,1),(1,2),(0,3),(1,3))
    AND (to_jsonb(NEW)-ARRAY['phase','reviewer_id','poster_id','canceller_id','effect_id','receipt_id','review_audit_id','review_outbox_id','post_audit_id','post_outbox_id','cancel_audit_id','cancel_outbox_id'])
      =(to_jsonb(OLD)-ARRAY['phase','reviewer_id','poster_id','canceller_id','effect_id','receipt_id','review_audit_id','review_outbox_id','post_audit_id','post_outbox_id','cancel_audit_id','cancel_outbox_id']),
      'Immutable source changes only through exact original financial phases');
   IF OLD.reviewer_id IS NOT NULL THEN PERFORM reconforge.pb_assert(NEW.reviewer_id=OLD.reviewer_id AND NEW.review_audit_id=OLD.review_audit_id AND NEW.review_outbox_id=OLD.review_outbox_id,'Original review cannot change');END IF;
   actor:=CASE NEW.phase WHEN 1 THEN NEW.reviewer_id WHEN 2 THEN NEW.poster_id ELSE NEW.canceller_id END;
   permission:=CASE NEW.phase WHEN 1 THEN 'review' WHEN 2 THEN 'post' ELSE 'prepare' END;
  ELSIF TG_TABLE_NAME='pb_claim_heads' THEN
   PERFORM reconforge.pb_assert(NEW.tenant_id=OLD.tenant_id AND NEW.time_id=OLD.time_id AND NEW.sequence=OLD.sequence+1,'Claim head advances only to its next original event');RETURN NEW;
  ELSE PERFORM reconforge.pb_assert(FALSE,'Original price time command and event history are immutable');END IF;
 ELSE
  IF TG_TABLE_NAME='pb_prices' THEN actor:=NEW.preparer_id;permission:='manage';
   PERFORM reconforge.pb_assert(NEW.approver_id IS NULL AND NEW.approve_audit_id IS NULL AND NEW.approve_outbox_id IS NULL,'New price must await independent approval');
  ELSIF TG_TABLE_NAME='pb_plans' THEN actor:=NEW.preparer_id;permission:=CASE NEW.kind WHEN 'Invoice' THEN 'prepare' ELSE 'collect' END;
   PERFORM reconforge.pb_assert(NEW.phase=0 AND NEW.reviewer_id IS NULL AND NEW.poster_id IS NULL AND NEW.canceller_id IS NULL AND NEW.effect_id IS NULL AND NEW.receipt_id IS NULL,'New source must be unposted and independently reviewed');
  ELSIF TG_TABLE_NAME='pb_commands' THEN actor:=NEW.actor_id;permission:=CASE NEW.operation WHEN 'cancel' THEN 'prepare' ELSE NEW.operation END;
   PERFORM reconforge.pb_assert(NEW.request_digest=reconforge.irp_digest(jsonb_build_object('operation',NEW.operation,'request',NEW.request_json)),'Original command digest differs');
  ELSE RETURN NEW;END IF;
 END IF;
 PERFORM reconforge.hc_actor(NEW.tenant_id,NEW.workspace_id,NEW.organization_id,NEW.legal_entity_id,actor,'project_time_billing.'||permission);
 IF TG_TABLE_NAME='pb_prices' AND permission='manage' THEN
  PERFORM reconforge.hc_actor(NEW.tenant_id,NEW.workspace_id,NEW.organization_id,NEW.legal_entity_id,actor,'receivables.read');END IF;
 IF TG_TABLE_NAME='pb_plans' THEN
  PERFORM reconforge.hc_actor(NEW.tenant_id,NEW.workspace_id,NEW.organization_id,NEW.legal_entity_id,actor,
   'finance_core.'||CASE permission WHEN 'review' THEN 'validate' WHEN 'post' THEN 'post' ELSE 'manage' END);
  PERFORM reconforge.hc_actor(NEW.tenant_id,NEW.workspace_id,NEW.organization_id,NEW.legal_entity_id,actor,
   'receivables.'||CASE WHEN permission='collect' OR(permission='post' AND NEW.kind='Collection') THEN 'receive' WHEN permission='post' THEN 'approve' ELSE 'manage' END);
  IF permission='post' THEN
   PERFORM reconforge.hc_actor(NEW.tenant_id,NEW.workspace_id,NEW.organization_id,NEW.legal_entity_id,actor,'receivables.approve');
   PERFORM reconforge.hc_actor(NEW.tenant_id,NEW.workspace_id,NEW.organization_id,NEW.legal_entity_id,actor,'receivables.receive');
  ELSIF permission='prepare' AND TG_OP='INSERT' THEN
   PERFORM reconforge.hc_actor(NEW.tenant_id,NEW.workspace_id,NEW.organization_id,NEW.legal_entity_id,actor,'people_project_payroll.read');END IF;
  IF TG_OP='UPDATE' AND NEW.phase=2 THEN
   SELECT c.* INTO customer FROM reconforge.ar_customers c JOIN reconforge.ar_invoices i ON i.tenant_id=c.tenant_id AND i.customer_id=c.id
    WHERE i.tenant_id=NEW.tenant_id AND i.id=NEW.ar_invoice_id FOR UPDATE OF c;
   PERFORM reconforge.pb_assert(customer.id IS NOT NULL AND customer.status='Active'
    AND(customer.workspace_id,customer.organization_id,customer.legal_entity_id,customer.currency_code)
    =(NEW.workspace_id,NEW.organization_id,NEW.legal_entity_id,NEW.payload#>>'{monetary_policy,currency_code}'),'Current active customer and functional currency are required at publication');
   IF NEW.kind='Invoice' THEN
    SELECT COALESCE(sum(i.total_minor-COALESCE(a.amount,0)),0) INTO exposure FROM reconforge.ar_invoices i
    LEFT JOIN(SELECT tenant_id,invoice_id,sum(amount_minor) amount FROM reconforge.ar_receipt_allocations GROUP BY tenant_id,invoice_id) a ON a.tenant_id=i.tenant_id AND a.invoice_id=i.id
    WHERE i.tenant_id=NEW.tenant_id AND i.customer_id=customer.id AND i.status IN('Approved','PartiallyPaid');
    PERFORM reconforge.pb_assert(NOT customer.credit_hold AND exposure<=customer.credit_limit_minor,'Current native customer credit controls cannot be bypassed by SQL posting');
   END IF;
  END IF;
 END IF;RETURN NEW;
END $pb$;

CREATE FUNCTION reconforge.pb_claim(t TEXT,ti TEXT,pi TEXT,operation TEXT,actor TEXT) RETURNS VOID LANGUAGE plpgsql SET search_path=pg_catalog AS $pb$
DECLARE tm RECORD;p RECORD;h RECORD;prior RECORD;seq INTEGER;a TEXT;b TEXT;state TEXT;
BEGIN
 SELECT * INTO tm FROM reconforge.hc_times WHERE tenant_id=t AND id=ti FOR UPDATE;
 SELECT * INTO p FROM reconforge.pb_plans WHERE tenant_id=t AND id=pi;
 SELECT * INTO h FROM reconforge.pb_claim_heads WHERE tenant_id=t AND time_id=ti FOR UPDATE;
 PERFORM reconforge.pb_assert(tm.approver_id IS NOT NULL AND p.kind='Invoice' AND(tm.workspace_id,tm.organization_id,tm.legal_entity_id)=(p.workspace_id,p.organization_id,p.legal_entity_id),'Whole billing claim requires approved original scoped time');
 seq:=COALESCE(h.sequence,0)+1;
 IF operation='Claim' THEN
  PERFORM reconforge.pb_assert(p.phase=0 AND actor=p.preparer_id AND(h.time_id IS NULL OR h.state='Released'),'Whole time already belongs to an active or consumed bill');
  IF h.time_id IS NOT NULL THEN SELECT * INTO prior FROM reconforge.pb_plans WHERE tenant_id=t AND id=h.invoice_id;
   PERFORM reconforge.pb_assert(prior.phase=3 AND prior.effect_id IS NULL AND NOT EXISTS(SELECT 1 FROM reconforge.finance_posting_effects WHERE tenant_id=t AND entry_id=prior.entry_id),'Only an actually cancelled unposted bill releases its original time');END IF;
  INSERT INTO reconforge.pb_time_claims VALUES(t,ti,pi,tm.source_digest);a:=p.audit_id;b:=p.outbox_id;state:='Active';
 ELSIF operation='Consume' THEN
  PERFORM reconforge.pb_assert(h.invoice_id=pi AND h.state='Active' AND p.phase=2 AND p.effect_id IS NOT NULL AND actor=p.poster_id,'Consumption requires original posted invoice');a:=p.post_audit_id;b:=p.post_outbox_id;state:='Consumed';
 ELSIF operation='Release' THEN
  PERFORM reconforge.pb_assert(h.invoice_id=pi AND h.state='Active' AND p.phase=3 AND actor=p.canceller_id,'Consumed billed time cannot release');a:=p.cancel_audit_id;b:=p.cancel_outbox_id;state:='Released';
 ELSE PERFORM reconforge.pb_assert(FALSE,'Unknown billing claim operation');END IF;
 INSERT INTO reconforge.pb_claim_events VALUES(t,'PBC-'||encode(sha256(convert_to(t||':'||ti||':'||seq::text,'UTF8')),'hex'),ti,pi,seq,operation,tm.source_digest,actor,a,b);
 INSERT INTO reconforge.pb_claim_heads VALUES(t,ti,pi,seq,state)
 ON CONFLICT(tenant_id,time_id) DO UPDATE SET invoice_id=excluded.invoice_id,sequence=excluded.sequence,state=excluded.state;
END $pb$;

CREATE FUNCTION reconforge.pb_price_close(t TEXT,pi TEXT) RETURNS VOID LANGUAGE plpgsql SET search_path=pg_catalog AS $pb$
DECLARE p RECORD;project RECORD;c RECORD;cmd RECORD;
BEGIN
 SELECT * INTO p FROM reconforge.pb_prices WHERE tenant_id=t AND id=pi;
 PERFORM reconforge.pb_assert(p.id IS NOT NULL AND p.source_digest=reconforge.irp_digest(p.source_json)
 AND (p.id,p.tenant_id,p.workspace_id,p.organization_id,p.legal_entity_id,p.project_id,p.customer_code,p.valid_from::text,p.valid_through::text,p.currency_code,p.hourly_price_minor::text,p.preparer_id)
 =(p.source_json->>'id',p.source_json->>'tenant_id',p.source_json->>'workspace_id',p.source_json->>'organization_id',p.source_json->>'legal_entity_id',p.source_json->>'project_id',p.source_json->>'customer_code',p.source_json->>'valid_from',p.source_json->>'valid_through',p.source_json->>'currency_code',p.source_json->>'hourly_price_minor',p.source_json->>'preparer_id'),'Price projection must retain exact original sealed source');
 SELECT * INTO project FROM reconforge.hc_projects WHERE tenant_id=t AND id=p.project_id;
 PERFORM reconforge.pb_assert(project.id IS NOT NULL AND(project.workspace_id,project.organization_id,project.legal_entity_id)=(p.workspace_id,p.organization_id,p.legal_entity_id)
 AND(project.dimension_id,project.value_id)=(p.source_json->>'dimension_id',p.source_json->>'value_id'),'Price requires original scoped Project dimensions');
 PERFORM reconforge.hc_input_close(t,'hc_projects',project.id);
 SELECT * INTO c FROM reconforge.ar_customers WHERE tenant_id=t AND workspace_id=p.workspace_id AND customer_code=p.customer_code;
 PERFORM reconforge.pb_assert(c.id IS NOT NULL AND(c.organization_id,c.legal_entity_id,c.currency_code)=(p.organization_id,p.legal_entity_id,p.currency_code)
 AND(SELECT currency_code FROM reconforge.legal_entities WHERE tenant_id=t AND id=p.legal_entity_id)=p.currency_code
    AND p.source_json#>>'{monetary_policy,currency_code}'=p.currency_code AND reconforge.fx_policy(t,p.source_json->'monetary_policy')
    AND jsonb_typeof(p.source_json->'hourly_price_minor')='number'
    AND p.source_json->>'organization_code'=(SELECT organization_code FROM reconforge.organizations WHERE tenant_id=t AND id=p.organization_id AND application_workspace_id=p.workspace_id)
    AND p.source_json->>'entity_code'=(SELECT entity_code FROM reconforge.legal_entities WHERE tenant_id=t AND id=p.legal_entity_id AND organization_id=p.organization_id),
    'First billing price requires original customer functional currency policy and canonical hierarchy');
 IF p.approver_id IS NOT NULL THEN
  PERFORM reconforge.pb_assert(p.approver_id<>p.preparer_id AND NOT EXISTS(SELECT 1 FROM reconforge.pb_prices other WHERE other.tenant_id=t AND other.id<>pi
   AND other.workspace_id=p.workspace_id AND other.organization_id=p.organization_id AND other.legal_entity_id=p.legal_entity_id
   AND other.customer_code=p.customer_code AND other.project_id=p.project_id AND other.approver_id IS NOT NULL
   AND other.valid_from<=p.valid_through AND other.valid_through>=p.valid_from),'Approved effective project prices cannot overlap');
 END IF;
 SELECT * INTO cmd FROM reconforge.pb_commands WHERE tenant_id=t AND operation='manage' AND response_json->>'id'=pi;
 PERFORM reconforge.pb_assert(cmd.actor_id=p.preparer_id AND cmd.request_json=(p.source_json-ARRAY['id','tenant_id','preparer_id','dimension_id','value_id','monetary_policy'])
  AND(cmd.workspace_id,cmd.organization_id,cmd.legal_entity_id)=(p.workspace_id,p.organization_id,p.legal_entity_id)
  AND(cmd.response_json-ARRAY['source_digest','approver_id','status'])=p.source_json
  AND cmd.response_json->>'source_digest'=p.source_digest AND cmd.response_json->>'status'='Submitted'
  AND(SELECT count(*) FROM reconforge.pb_commands WHERE tenant_id=t AND operation='manage' AND response_json->>'id'=pi)=1,
  'Original price requires its complete immutable command acknowledgement');
 PERFORM reconforge.pb_audit(t,pi,p.preparer_id,'price_registered',p.source_digest,p.audit_id,p.outbox_id,p.workspace_id,p.organization_id,p.legal_entity_id);
 IF p.approver_id IS NOT NULL THEN
  SELECT * INTO cmd FROM reconforge.pb_commands WHERE tenant_id=t AND operation='approve_price' AND response_json->>'id'=pi;
  PERFORM reconforge.pb_assert(cmd.actor_id=p.approver_id AND cmd.request_json->>'price_id'=pi AND cmd.request_json->>'expected_digest'=p.source_digest
   AND(cmd.response_json-ARRAY['source_digest','approver_id','status'])=p.source_json AND cmd.response_json->>'source_digest'=p.source_digest
   AND cmd.response_json->>'approver_id'=p.approver_id AND cmd.response_json->>'status'='Approved'
   AND(SELECT count(*) FROM reconforge.pb_commands WHERE tenant_id=t AND operation='approve_price' AND response_json->>'id'=pi)=1,
   'Price approval requires original independent acknowledgement');
  PERFORM reconforge.pb_audit(t,pi,p.approver_id,'price_approved',p.source_digest,p.approve_audit_id,p.approve_outbox_id,p.workspace_id,p.organization_id,p.legal_entity_id);
 END IF;
END $pb$;

CREATE FUNCTION reconforge.pb_calculate(t TEXT,pi TEXT) RETURNS JSONB LANGUAGE plpgsql SET search_path=pg_catalog AS $pb$
DECLARE p RECORD;tm RECORD;price RECORD;line JSONB;project RECORD;totals JSONB:='{}';minutes JSONB:='{}';sources JSONB:='[]';used JSONB:='[]';result JSONB:='{}';amount NUMERIC;key TEXT;v JSONB;
BEGIN
 SELECT * INTO p FROM reconforge.pb_plans WHERE tenant_id=t AND id=pi;v:=p.payload->'calculation';
 PERFORM reconforge.pb_assert(v->'monetary_policy'=p.payload->'monetary_policy','Calculation retains the original native monetary policy');
 PERFORM reconforge.pb_assert(jsonb_array_length(v->'time_ids') BETWEEN 1 AND 1000 AND jsonb_array_length(v->'price_ids') BETWEEN 1 AND 999,'Bounded complete billing population required');
 FOR tm IN SELECT time.* FROM reconforge.hc_times time JOIN reconforge.pb_time_claims claim ON claim.tenant_id=time.tenant_id AND claim.time_id=time.id WHERE claim.tenant_id=t AND claim.invoice_id=pi ORDER BY time.id COLLATE "C" LOOP
  PERFORM reconforge.pb_assert(tm.approver_id IS NOT NULL AND(tm.workspace_id,tm.organization_id,tm.legal_entity_id)=(p.workspace_id,p.organization_id,p.legal_entity_id),'Billing retains exact original approved time scope');
  PERFORM reconforge.hc_input_close(t,'hc_times',tm.id);
  FOR line IN SELECT value FROM jsonb_array_elements(tm.lines) ORDER BY(value->>'start_minute')::INTEGER LOOP
   SELECT * INTO price FROM reconforge.pb_prices WHERE tenant_id=t AND id IN(SELECT jsonb_array_elements_text(v->'price_ids'))
    AND project_id=line->>'project_id' AND valid_from<=tm.business_date AND valid_through>=tm.business_date;
   PERFORM reconforge.pb_assert(price.id IS NOT NULL AND price.approver_id IS NOT NULL AND price.customer_code=p.payload->>'customer_code'
    AND(price.workspace_id,price.organization_id,price.legal_entity_id)=(p.workspace_id,p.organization_id,p.legal_entity_id)
    AND price.source_json->'monetary_policy'=v->'monetary_policy','Original time needs exactly one effective independently approved native price');
   PERFORM reconforge.pb_price_close(t,price.id);
   key:=line->>'project_id';amount:=((line->>'end_minute')::NUMERIC-(line->>'start_minute')::NUMERIC)*price.hourly_price_minor;
   totals:=jsonb_set(totals,ARRAY[key],to_jsonb(COALESCE((totals->>key)::NUMERIC,0)+amount));
   minutes:=jsonb_set(minutes,ARRAY[key],to_jsonb(COALESCE((minutes->>key)::INTEGER,0)+(line->>'end_minute')::INTEGER-(line->>'start_minute')::INTEGER));
   IF NOT used ? price.id THEN used:=used||jsonb_build_array(price.id);END IF;
   sources:=sources||jsonb_build_array(jsonb_build_object('time_id',tm.id,'time_digest',tm.source_digest,'project_id',key,
    'start_minute',(line->>'start_minute')::INTEGER,'end_minute',(line->>'end_minute')::INTEGER,'minutes',(line->>'end_minute')::INTEGER-(line->>'start_minute')::INTEGER,
    'price_id',price.id,'price_digest',price.source_digest,'hourly_price_minor',price.hourly_price_minor));
  END LOOP;
 END LOOP;
 FOR key,amount IN SELECT z.key,z.value::text::NUMERIC FROM jsonb_each(totals) z LOOP
  amount:=trunc(amount/60)+CASE WHEN mod(amount,60)*2>=60 THEN 1 ELSE 0 END;
  PERFORM reconforge.pb_assert(amount BETWEEN 1 AND 4500000000000000000,'Native project amount exceeds exact capacity');result:=jsonb_set(result,ARRAY[key],to_jsonb(amount));
 END LOOP;
 PERFORM reconforge.pb_assert(v->'project_minor'=result AND v->'sources'=sources AND v->'project_minutes'=minutes
 AND(v->>'amount_minor')::NUMERIC=(SELECT sum(value::TEXT::NUMERIC) FROM jsonb_each(result))
 AND(SELECT jsonb_agg(value ORDER BY value COLLATE "C") FROM jsonb_array_elements_text(used))=v->'price_ids'
 AND(SELECT jsonb_agg(time_id ORDER BY time_id COLLATE "C") FROM reconforge.pb_time_claims WHERE tenant_id=t AND invoice_id=pi)=v->'time_ids',
 'Original invoice must equal independently recomputed full minute/captured-price HALF_UP allocation');RETURN result;
END $pb$;

CREATE FUNCTION reconforge.pb_audit(t TEXT,pi TEXT,actor TEXT,operation TEXT,digest TEXT,aid TEXT,oid TEXT,w TEXT,o TEXT,e TEXT) RETURNS VOID LANGUAGE plpgsql SET search_path=pg_catalog AS $pb$
BEGIN
 PERFORM reconforge.pb_assert(EXISTS(SELECT 1 FROM reconforge.domain_audit_events WHERE tenant_id=t AND id=aid AND actor_user_id=actor
 AND object_type='operational_finance' AND object_id=pi AND action='project_billing_'||operation AND metadata_json::jsonb=jsonb_build_object('source_digest',digest)),'Billing audit must retain original actor and seal');
 PERFORM reconforge.pb_assert(EXISTS(SELECT 1 FROM reconforge.outbox_events WHERE tenant_id=t AND event_id=oid AND aggregate_type='operational_finance'
 AND aggregate_id=pi AND event_type='project_billing_'||operation AND(workspace_id,organization_id,legal_entity_id)=(w,o,e)
 AND payload=jsonb_build_object('source_digest',digest,'audit_event_id',aid)),'Billing outbox retains exact immutable original evidence');
END $pb$;

CREATE FUNCTION reconforge.pb_phases(t TEXT,p JSONB) RETURNS VOID LANGUAGE plpgsql SET search_path=pg_catalog AS $pb$
DECLARE op TEXT;act TEXT;actor TEXT;aid TEXT;oid TEXT;cmd RECORD;phase INTEGER:=(p->>'phase')::INTEGER;v JSONB:=p->'payload';
BEGIN
 FOR op,act,actor,aid,oid IN SELECT * FROM(VALUES
 (CASE p->>'kind' WHEN 'Invoice' THEN 'prepare' ELSE 'collect' END,'prepared',p->>'preparer_id',p->>'audit_id',p->>'outbox_id'),
 ('review','reviewed',p->>'reviewer_id',p->>'review_audit_id',p->>'review_outbox_id'),
 ('post','posted',p->>'poster_id',p->>'post_audit_id',p->>'post_outbox_id'),
 ('cancel','cancelled',p->>'canceller_id',p->>'cancel_audit_id',p->>'cancel_outbox_id')) z(op,act,actor,a,b) LOOP
  IF op IN('prepare','collect') OR(op='review' AND(phase IN(1,2) OR(phase=3 AND p->>'reviewer_id' IS NOT NULL))) OR(op='post' AND phase=2) OR(op='cancel' AND phase=3) THEN
   PERFORM reconforge.pb_assert(actor IS NOT NULL AND aid IS NOT NULL AND oid IS NOT NULL,'Completed billing phase needs original actor and evidence');
   PERFORM reconforge.pb_audit(t,p->>'id',actor,act,v->>'plan_digest',aid,oid,p->>'workspace_id',p->>'organization_id',p->>'legal_entity_id');
   SELECT * INTO cmd FROM reconforge.pb_commands c WHERE c.tenant_id=t AND c.workspace_id=p->>'workspace_id' AND c.operation=op AND c.response_json->>'id'=p->>'id';
   PERFORM reconforge.pb_assert(cmd.command_id IS NOT NULL AND cmd.actor_id=actor
    AND(cmd.organization_id,cmd.legal_entity_id)=(p->>'organization_id',p->>'legal_entity_id')
    AND(SELECT count(*) FROM reconforge.pb_commands c WHERE c.tenant_id=t AND c.operation=op AND c.response_json->>'id'=p->>'id')=1
    AND(cmd.response_json-ARRAY['phase','status','reviewer_id','posted_actor_id','posting_effect_id','receipt_id'])=v
    AND(cmd.response_json->>'phase')::INTEGER=CASE op WHEN 'prepare' THEN 0 WHEN 'collect' THEN 0 WHEN 'review' THEN 1 WHEN 'post' THEN 2 ELSE 3 END
    AND cmd.response_json->>'status'=CASE op WHEN 'prepare' THEN 'Prepared' WHEN 'collect' THEN 'Prepared' WHEN 'review' THEN 'Reviewed' WHEN 'post' THEN 'Posted' ELSE 'Cancelled' END
    AND (cmd.response_json->>'receipt_id') IS NOT DISTINCT FROM CASE WHEN op='post' THEN p->>'receipt_id' ELSE NULL END
    AND (cmd.response_json->>'posting_effect_id') IS NOT DISTINCT FROM CASE WHEN op='post' THEN p->>'effect_id' ELSE NULL END,
    'Billing phase needs one exact immutable original acknowledgement');
   IF op IN('prepare','collect') THEN PERFORM reconforge.pb_assert(cmd.request_json=v->'command_request','Original preparation request differs');
   ELSE PERFORM reconforge.pb_assert(cmd.request_json->>'plan_id'=p->>'id' AND cmd.request_json->>'expected_plan_digest'=v->>'plan_digest','Original financial phase request differs');END IF;
  ELSE PERFORM reconforge.pb_assert(actor IS NULL AND aid IS NULL AND oid IS NULL,'Unperformed billing phase has no fabricated evidence');END IF;
 END LOOP;
END $pb$;

CREATE FUNCTION reconforge.pb_close(t TEXT,pi TEXT) RETURNS VOID LANGUAGE plpgsql SET search_path=pg_catalog AS $pb$
DECLARE p RECORD;parent RECORD;e RECORD;ar RECORD;receipt RECORD;claim RECORD;v JSONB;project RECORD;amount NUMERIC;expected JSONB;actual JSONB;paid NUMERIC;
BEGIN
 SELECT * INTO p FROM reconforge.pb_plans WHERE tenant_id=t AND id=pi;
 PERFORM reconforge.pb_assert(p.id IS NOT NULL,'Native billing source cannot detach');v:=p.payload;
 PERFORM reconforge.pb_assert(v->>'plan_digest'=reconforge.irp_digest(v-'plan_digest')
 AND(p.id,p.workspace_id,p.organization_id,p.legal_entity_id,p.entry_id,p.amount_minor::text,p.preparer_id,p.ar_invoice_id)
 =(v->>'id',v->>'workspace_id',v->>'organization_id',v->>'legal_entity_id',v->>'entry_id',v->>'amount_minor',v->>'preparer_id',v->>'ar_invoice_id'),'Native billing owner and immutable payload differ');
 SELECT * INTO e FROM reconforge.finance_entries WHERE tenant_id=t AND id=p.entry_id;
 PERFORM reconforge.pb_assert(e.id IS NOT NULL AND e.entry_number=upper(p.id) AND e.preparer_actor_id=p.preparer_id AND e.workspace_id=p.workspace_id
 AND e.organization_code=v->>'organization_code' AND e.entity_code=v->>'entity_code' AND e.period_id=v->>'period_id' AND e.posting_date=v->>'posting_date'
 AND e.external_reference=p.id AND e.source_type='Manual' AND e.reverses_posting_id IS NULL
 AND(e.currency_code,e.currency_precision::text,e.currency_rounding_policy,e.currency_registry_version,e.currency_registry_digest)
 =(v#>>'{monetary_policy,currency_code}',v#>>'{monetary_policy,currency_precision}',v#>>'{monetary_policy,currency_rounding_policy}',v#>>'{monetary_policy,currency_registry_version}',v#>>'{monetary_policy,currency_registry_digest}'),
 'Original native entry header and captured currency policy differ');
 PERFORM reconforge.pb_phases(t,to_jsonb(p));
 PERFORM reconforge.pb_assert((SELECT count(*) FROM reconforge.finance_posting_effects WHERE tenant_id=t AND entry_id=p.entry_id)=CASE WHEN p.phase=2 THEN 1 ELSE 0 END,'Billing publication and GL effect must be atomic');
 IF p.phase=2 THEN
  PERFORM reconforge.pb_assert(p.poster_id<>p.preparer_id AND p.poster_id<>p.reviewer_id AND p.reviewer_id<>p.preparer_id
   AND EXISTS(SELECT 1 FROM reconforge.finance_posting_effects f WHERE f.tenant_id=t AND f.id=p.effect_id AND f.entry_id=p.entry_id AND f.posted_actor_id=p.poster_id
    AND f.reverses_effect_id IS NULL AND f.validation_digest=v->>'validation_digest' AND f.snapshot_json=v->'snapshot'),'Original native effect needs three distinct financial humans and exact reviewed contents');
 ELSE PERFORM reconforge.pb_assert(p.effect_id IS NULL AND p.poster_id IS NULL,'Unposted source cannot retain native financial effects');END IF;
 IF p.phase IN(1,2) OR(p.phase=3 AND p.reviewer_id IS NOT NULL) THEN PERFORM reconforge.pb_assert(e.status='Validated' AND e.validator_actor_id=p.reviewer_id AND e.validation_digest=v->>'validation_digest','Source must retain exact independent native review');
 ELSE PERFORM reconforge.pb_assert(e.status='Draft' AND p.reviewer_id IS NULL,'Prepared source must retain native Draft');END IF;
 IF p.phase IN(0,1) THEN PERFORM reconforge.pb_assert((SELECT status FROM reconforge.fiscal_periods WHERE tenant_id=t AND id=e.period_id)='Open','Pending source requires its current open accounting period');END IF;
 IF p.kind='Invoice' THEN
  SELECT * INTO ar FROM reconforge.ar_invoices WHERE tenant_id=t AND id=p.ar_invoice_id;
  PERFORM reconforge.pb_assert(ar.id IS NOT NULL AND(ar.workspace_id,ar.organization_id,ar.legal_entity_id,ar.customer_id,ar.invoice_number,ar.invoice_date::text,ar.due_date::text)
   =(p.workspace_id,p.organization_id,p.legal_entity_id,v->>'customer_id',v->>'invoice_number',v->>'posting_date',v->>'due_date')
   AND(ar.currency_code,ar.currency_precision,ar.currency_rounding_policy,ar.currency_registry_version,ar.currency_registry_digest)
   =(e.currency_code,e.currency_precision,e.currency_rounding_policy,e.currency_registry_version,e.currency_registry_digest)
   AND ar.pb_owner_id=p.id AND ar.tax_minor=0 AND ar.subtotal_minor=p.amount_minor AND ar.total_minor=p.amount_minor,'Original native AR header and amount differ');
  actual:=reconforge.pb_calculate(t,pi);
  PERFORM reconforge.pb_assert((SELECT count(*) FROM(VALUES(v->>'receivable_account_code','Asset'),(v->>'revenue_account_code','Income'),(v->>'cash_account_code','Asset')) roles(code,kind)
   JOIN reconforge.finance_accounts a ON a.tenant_id=t AND a.workspace_id=p.workspace_id AND a.account_code=roles.code AND a.account_type=roles.kind
   JOIN reconforge.finance_journals j ON j.tenant_id=a.tenant_id AND j.id=e.journal_id AND j.chart_id=a.chart_id)=3
   AND v->>'receivable_account_code'<>v->>'cash_account_code','Original billing needs distinct AR/cash assets and Income in the captured journal chart');
  PERFORM reconforge.pb_assert((SELECT count(*) FROM reconforge.pb_account_pins WHERE tenant_id=t AND invoice_id=pi)=3
   AND NOT EXISTS(SELECT 1 FROM reconforge.pb_account_pins pin WHERE pin.tenant_id=t AND pin.invoice_id=pi
    AND(pin.workspace_id<>p.workspace_id OR pin.account_code<>v->>(CASE pin.role WHEN 'receivable' THEN 'receivable_account_code' WHEN 'revenue' THEN 'revenue_account_code' ELSE 'cash_account_code' END)
     OR pin.account_type<>CASE pin.role WHEN 'revenue' THEN 'Income' ELSE 'Asset' END
     OR pin.chart_id<>(SELECT chart_id FROM reconforge.finance_journals WHERE tenant_id=t AND id=e.journal_id))),
    'Billing retains three exact structural native account identities');
  PERFORM reconforge.pb_assert((SELECT count(*) FROM reconforge.ar_invoice_lines WHERE tenant_id=t AND invoice_id=p.ar_invoice_id)=(SELECT count(*) FROM jsonb_object_keys(actual))
   AND NOT EXISTS(SELECT 1 FROM reconforge.ar_invoice_lines l WHERE l.tenant_id=t AND l.invoice_id=p.ar_invoice_id
    AND(l.quantity_text<>'1' OR l.quantity<>1 OR l.tax_minor<>0 OR l.unit_price_minor<>(actual->>l.description)::NUMERIC OR l.line_total_minor<>l.unit_price_minor OR NOT actual ? l.description)),
   'Original AR must contain exact quantity-one Project aggregates');
  expected:=jsonb_build_array(jsonb_build_object('account_code',v->>'receivable_account_code','debit_minor',p.amount_minor,'credit_minor',0,'dimensions','{}'::jsonb));
  FOR project IN SELECT key,value FROM jsonb_each(actual) ORDER BY key COLLATE "C" LOOP
   expected:=expected||jsonb_build_array(jsonb_build_object('account_code',v->>'revenue_account_code','debit_minor',0,'credit_minor',project.value,
    'dimensions',(SELECT jsonb_build_object(dimension_id,value_id) FROM reconforge.hc_projects WHERE tenant_id=t AND id=project.key)));
  END LOOP;
  SELECT COALESCE(sum(amount_minor),0) INTO paid FROM reconforge.pb_plans WHERE tenant_id=t AND parent_id=pi AND phase=2;
  PERFORM reconforge.pb_assert(paid<=p.amount_minor AND paid=(SELECT COALESCE(sum(amount_minor),0) FROM reconforge.ar_receipt_allocations WHERE tenant_id=t AND invoice_id=p.ar_invoice_id),'Native receipt allocations equal only original posted collection sources');
  PERFORM reconforge.pb_assert(ar.status=CASE WHEN p.phase<>2 THEN 'Submitted' WHEN paid=0 THEN 'Approved' WHEN paid=p.amount_minor THEN 'Paid' ELSE 'PartiallyPaid' END
   AND (p.phase<>2 OR ar.approved_by=(SELECT username FROM reconforge.identity_users WHERE tenant_id=t AND id=p.poster_id)),'AR approval and collections cannot publish independently of their source');
  PERFORM reconforge.pb_assert((SELECT count(*) FROM reconforge.pb_claim_heads WHERE tenant_id=t AND time_id IN(SELECT time_id FROM reconforge.pb_time_claims WHERE tenant_id=t AND invoice_id=pi))
   =jsonb_array_length(v#>'{calculation,time_ids}'),'Every whole billing-time claim requires its actual current head');
  FOR claim IN SELECT c.*,h.invoice_id current_owner,h.state FROM reconforge.pb_time_claims c JOIN reconforge.pb_claim_heads h ON h.tenant_id=c.tenant_id AND h.time_id=c.time_id WHERE c.tenant_id=t AND c.invoice_id=pi LOOP
   PERFORM reconforge.pb_assert(claim.source_digest=(SELECT source_digest FROM reconforge.hc_times WHERE tenant_id=t AND id=claim.time_id),'Billed time retains original approved digest');
   IF p.phase<>3 THEN PERFORM reconforge.pb_assert(claim.current_owner=pi AND claim.state=CASE p.phase WHEN 2 THEN 'Consumed' ELSE 'Active' END,'Whole time belongs to one active or consumed invoice');
   ELSE PERFORM reconforge.pb_assert(EXISTS(SELECT 1 FROM reconforge.pb_claim_events z WHERE z.tenant_id=t AND z.time_id=claim.time_id AND z.invoice_id=pi AND z.operation='Release'),'Cancelled bill retains actual immutable claim release');END IF;
  END LOOP;
  FOR claim IN SELECT h.*,z.invoice_id event_owner,z.operation FROM reconforge.pb_claim_heads h JOIN reconforge.pb_claim_events z ON z.tenant_id=h.tenant_id AND z.time_id=h.time_id AND z.sequence=h.sequence WHERE h.tenant_id=t AND h.time_id IN(SELECT time_id FROM reconforge.pb_time_claims WHERE tenant_id=t AND invoice_id=pi) LOOP
   PERFORM reconforge.pb_assert(claim.invoice_id=claim.event_owner AND claim.sequence=(SELECT count(*) FROM reconforge.pb_claim_events WHERE tenant_id=t AND time_id=claim.time_id)
   AND claim.sequence=(SELECT max(sequence) FROM reconforge.pb_claim_events WHERE tenant_id=t AND time_id=claim.time_id)
   AND claim.state=CASE claim.operation WHEN 'Claim' THEN 'Active' WHEN 'Consume' THEN 'Consumed' ELSE 'Released' END,'Claim head equals contiguous immutable last event');
  END LOOP;
  FOR claim IN SELECT * FROM reconforge.pb_claim_events WHERE tenant_id=t AND invoice_id=pi LOOP
   PERFORM reconforge.pb_assert(claim.source_digest=(SELECT source_digest FROM reconforge.hc_times WHERE tenant_id=t AND id=claim.time_id)
    AND(claim.actor_id,claim.audit_id,claim.outbox_id)=CASE claim.operation WHEN 'Claim' THEN(p.preparer_id,p.audit_id,p.outbox_id) WHEN 'Consume' THEN(p.poster_id,p.post_audit_id,p.post_outbox_id) ELSE(p.canceller_id,p.cancel_audit_id,p.cancel_outbox_id) END,'Claim history retains exact original financial phase');
  END LOOP;
  PERFORM reconforge.pb_assert(NOT EXISTS(SELECT 1 FROM reconforge.pb_time_claims c WHERE c.tenant_id=t AND c.invoice_id=pi AND(
   (SELECT count(*) FROM reconforge.pb_claim_events z WHERE z.tenant_id=t AND z.time_id=c.time_id AND z.invoice_id=pi AND z.operation='Claim')<>1
   OR(SELECT count(*) FROM reconforge.pb_claim_events z WHERE z.tenant_id=t AND z.time_id=c.time_id AND z.invoice_id=pi AND z.operation='Consume')<>CASE WHEN p.phase=2 THEN 1 ELSE 0 END
   OR(SELECT count(*) FROM reconforge.pb_claim_events z WHERE z.tenant_id=t AND z.time_id=c.time_id AND z.invoice_id=pi AND z.operation='Release')<>CASE WHEN p.phase=3 THEN 1 ELSE 0 END)),
   'Every original time claim has exactly its completed financial phase history');
 ELSE
  SELECT * INTO parent FROM reconforge.pb_plans WHERE tenant_id=t AND id=p.parent_id;
  PERFORM reconforge.pb_assert(parent.kind='Invoice' AND parent.phase=2 AND parent.ar_invoice_id=p.ar_invoice_id
   AND(parent.workspace_id,parent.organization_id,parent.legal_entity_id)=(p.workspace_id,p.organization_id,p.legal_entity_id)
   AND v->>'parent_digest'=parent.payload->>'plan_digest' AND v->'monetary_policy'=parent.payload->'monetary_policy'
   AND(v#>>'{calculation,amount_minor}')::NUMERIC=p.amount_minor,'Collection requires its original posted scoped invoice and exact monetary policy');
  expected:=jsonb_build_array(jsonb_build_object('account_code',parent.payload->>'cash_account_code','debit_minor',p.amount_minor,'credit_minor',0,'dimensions','{}'::jsonb),
   jsonb_build_object('account_code',parent.payload->>'receivable_account_code','debit_minor',0,'credit_minor',p.amount_minor,'dimensions','{}'::jsonb));
  IF p.phase=2 THEN
   SELECT * INTO receipt FROM reconforge.ar_receipts WHERE tenant_id=t AND id=p.receipt_id;
   PERFORM reconforge.pb_assert(receipt.id IS NOT NULL AND receipt.pb_owner_id=pi AND receipt.status='Posted' AND receipt.receipt_number=upper(pi) AND receipt.receipt_date::TEXT=v->>'posting_date'
    AND(receipt.workspace_id,receipt.organization_id,receipt.legal_entity_id,receipt.customer_id,receipt.currency_code,receipt.amount_minor)
    =(p.workspace_id,p.organization_id,p.legal_entity_id,parent.payload->>'customer_id',e.currency_code,p.amount_minor)
    AND receipt.posted_by=(SELECT username FROM reconforge.identity_users WHERE tenant_id=t AND id=p.poster_id)
    AND(SELECT count(*) FROM reconforge.ar_receipt_allocations WHERE tenant_id=t AND receipt_id=p.receipt_id)=1
    AND EXISTS(SELECT 1 FROM reconforge.ar_receipt_allocations WHERE tenant_id=t AND receipt_id=p.receipt_id AND invoice_id=p.ar_invoice_id AND amount_minor=p.amount_minor),
    'Collection requires one original native receipt and exact attached allocation');
  ELSE PERFORM reconforge.pb_assert(p.receipt_id IS NULL,'Unposted collection cannot publish a receipt');END IF;
 END IF;
 SELECT jsonb_agg(jsonb_build_object('account_code',a.account_code,'debit_minor',l.debit_minor,'credit_minor',l.credit_minor,
  'dimensions',COALESCE((SELECT jsonb_object_agg(d.dimension_id,d.dimension_value_id) FROM reconforge.finance_entry_line_dimensions d WHERE d.tenant_id=l.tenant_id AND d.entry_line_id=l.id),'{}'::jsonb)) ORDER BY l.line_number)
 INTO actual FROM reconforge.finance_entry_lines l JOIN reconforge.finance_accounts a ON a.tenant_id=l.tenant_id AND a.id=l.account_id WHERE l.tenant_id=t AND l.entry_id=p.entry_id;
 PERFORM reconforge.pb_assert(actual=expected,'Native billing or cash lines and original Project dimensions differ');
 IF p.kind='Invoice' THEN FOR project IN SELECT id FROM reconforge.pb_plans WHERE tenant_id=t AND parent_id=pi LOOP PERFORM reconforge.pb_close(t,project.id);END LOOP;END IF;
END $pb$;

CREATE FUNCTION reconforge.pb_reverse_close() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $pb$
DECLARE changes JSONB[];changed JSONB;source_id TEXT;native_id TEXT;number TEXT;original TEXT;p RECORD;
BEGIN
 IF TG_OP='UPDATE' AND TG_TABLE_NAME='outbox_events' THEN
  IF(NEW.tenant_id,NEW.event_id,NEW.event_type,NEW.aggregate_type,NEW.aggregate_id,NEW.workspace_id,NEW.organization_id,NEW.legal_entity_id,NEW.payload,NEW.created_at)
   IS NOT DISTINCT FROM(OLD.tenant_id,OLD.event_id,OLD.event_type,OLD.aggregate_type,OLD.aggregate_id,OLD.workspace_id,OLD.organization_id,OLD.legal_entity_id,OLD.payload,OLD.created_at) THEN RETURN NULL;END IF;
 END IF;
 IF TG_OP='INSERT' THEN changes:=ARRAY[to_jsonb(NEW)];ELSIF TG_OP='DELETE' THEN changes:=ARRAY[to_jsonb(OLD)];ELSIF TG_OP='UPDATE' THEN changes:=ARRAY[to_jsonb(OLD),to_jsonb(NEW)];ELSE PERFORM reconforge.pb_assert(FALSE,'Unsupported billing closure operation');END IF;
 FOREACH changed IN ARRAY changes LOOP
  source_id:=NULL;native_id:=NULL;
  IF TG_TABLE_NAME='pb_prices' THEN PERFORM reconforge.pb_price_close(changed->>'tenant_id',changed->>'id');
   FOR p IN SELECT id FROM reconforge.pb_plans WHERE tenant_id=changed->>'tenant_id' AND kind='Invoice' AND payload#>'{calculation,price_ids}' ? (changed->>'id') LOOP PERFORM reconforge.pb_close(changed->>'tenant_id',p.id);END LOOP;
  ELSIF TG_TABLE_NAME='pb_plans' THEN source_id:=COALESCE(changed->>'parent_id',changed->>'id');
  ELSIF TG_TABLE_NAME IN('pb_time_claims','pb_claim_events','pb_claim_heads','pb_account_pins') THEN source_id:=changed->>'invoice_id';
  ELSIF TG_TABLE_NAME='pb_commands' THEN
   source_id:=changed#>>'{response_json,id}';
   IF source_id LIKE 'PBP-%' THEN PERFORM reconforge.pb_price_close(changed->>'tenant_id',source_id);source_id:=NULL;END IF;
  ELSIF TG_TABLE_NAME IN('finance_entries','finance_entry_lines','finance_entry_line_dimensions','finance_posting_effects') THEN
   native_id:=CASE TG_TABLE_NAME WHEN 'finance_entries' THEN changed->>'id' ELSE changed->>'entry_id' END;
   IF TG_TABLE_NAME='finance_entry_line_dimensions' THEN SELECT l.entry_id INTO native_id FROM reconforge.finance_entry_lines l WHERE tenant_id=changed->>'tenant_id' AND id=changed->>'entry_line_id';END IF;
   original:=CASE TG_TABLE_NAME WHEN 'finance_entries' THEN changed->>'reverses_posting_id' ELSE changed->>'reverses_effect_id' END;
   IF original IS NOT NULL THEN
    SELECT e.entry_number INTO number FROM reconforge.finance_posting_effects f JOIN reconforge.finance_entries e ON e.tenant_id=f.tenant_id AND e.id=f.entry_id WHERE f.tenant_id=changed->>'tenant_id' AND f.id=original;
    PERFORM reconforge.pb_assert(upper(COALESCE(number,'')) NOT LIKE 'PB1-%' AND upper(COALESCE(number,'')) NOT LIKE 'PB1C-%','Billed source cannot reverse outside its future owned credit contract');END IF;
   SELECT entry_number INTO number FROM reconforge.finance_entries WHERE tenant_id=changed->>'tenant_id' AND id=native_id;
   IF TG_TABLE_NAME='finance_entries' THEN number:=changed->>'entry_number';END IF;
   IF upper(COALESCE(number,'')) LIKE 'PB1-%' OR upper(COALESCE(number,'')) LIKE 'PB1C-%' OR upper(COALESCE(native_id,'')) LIKE 'PB1-%' OR upper(COALESCE(native_id,'')) LIKE 'PB1C-%' THEN
    SELECT COALESCE(parent_id,id) INTO source_id FROM reconforge.pb_plans WHERE tenant_id=changed->>'tenant_id' AND pb_plans.entry_id=native_id;
    PERFORM reconforge.pb_assert(source_id IS NOT NULL,'Reserved PB1 native entry cannot detach');END IF;
  ELSIF TG_TABLE_NAME IN('ar_invoices','ar_invoice_lines','ar_receipt_allocations','ar_receipts') THEN
   IF TG_TABLE_NAME IN('ar_invoices','ar_receipts') THEN source_id:=changed->>'pb_owner_id';
   ELSE SELECT ar.pb_owner_id INTO source_id FROM reconforge.ar_invoices ar WHERE ar.tenant_id=changed->>'tenant_id' AND ar.id=changed->>'invoice_id';END IF;
   IF TG_TABLE_NAME='ar_receipts' AND source_id IS NOT NULL THEN
    SELECT parent_id INTO source_id FROM reconforge.pb_plans WHERE tenant_id=changed->>'tenant_id' AND id=source_id;
    PERFORM reconforge.pb_assert(source_id IS NOT NULL,'Native receipt owner must retain its original invoice');END IF;
  ELSIF TG_TABLE_NAME IN('domain_audit_events','outbox_events') THEN
   source_id:=CASE TG_TABLE_NAME WHEN 'domain_audit_events' THEN changed->>'object_id' ELSE changed->>'aggregate_id' END;
   IF source_id LIKE 'PBP-%' THEN PERFORM reconforge.pb_price_close(changed->>'tenant_id',source_id);source_id:=NULL;
   ELSIF source_id NOT LIKE 'PB1-%' AND source_id NOT LIKE 'PB1C-%' THEN source_id:=NULL;
   ELSE SELECT COALESCE(parent_id,id) INTO source_id FROM reconforge.pb_plans WHERE tenant_id=changed->>'tenant_id' AND id=source_id;END IF;
  END IF;
  IF source_id IS NOT NULL THEN PERFORM reconforge.pb_close(changed->>'tenant_id',source_id);END IF;
 END LOOP;RETURN NULL;
END $pb$;
DO $pb$ DECLARE n TEXT;BEGIN
 FOREACH n IN ARRAY ARRAY['pb_prices','pb_plans','pb_time_claims','pb_claim_events','pb_claim_heads','pb_commands','pb_account_pins'] LOOP
  EXECUTE format('ALTER TABLE reconforge.%I ENABLE ROW LEVEL SECURITY',n);EXECUTE format('ALTER TABLE reconforge.%I FORCE ROW LEVEL SECURITY',n);
  IF n IN('pb_time_claims','pb_claim_events','pb_claim_heads') THEN
   EXECUTE format('CREATE POLICY scope ON reconforge.%I USING(EXISTS(SELECT 1 FROM reconforge.hc_times t WHERE t.tenant_id=%I.tenant_id AND t.id=%I.time_id)) WITH CHECK(EXISTS(SELECT 1 FROM reconforge.hc_times t WHERE t.tenant_id=%I.tenant_id AND t.id=%I.time_id))',n,n,n,n,n);
  ELSIF n='pb_account_pins' THEN EXECUTE format('CREATE POLICY scope ON reconforge.%I USING(EXISTS(SELECT 1 FROM reconforge.pb_plans p WHERE p.tenant_id=%I.tenant_id AND p.id=%I.invoice_id)) WITH CHECK(EXISTS(SELECT 1 FROM reconforge.pb_plans p WHERE p.tenant_id=%I.tenant_id AND p.id=%I.invoice_id))',n,n,n,n,n);
  ELSE EXECUTE format('CREATE POLICY scope ON reconforge.%I USING(reconforge.irp_scope(tenant_id,workspace_id,organization_id,legal_entity_id)) WITH CHECK(reconforge.irp_scope(tenant_id,workspace_id,organization_id,legal_entity_id))',n);END IF;
  EXECUTE format('CREATE TRIGGER immutable BEFORE INSERT OR UPDATE OR DELETE ON reconforge.%I FOR EACH ROW EXECUTE FUNCTION reconforge.pb_guard()',n);
 END LOOP;
 FOREACH n IN ARRAY ARRAY['pb_prices','pb_plans','pb_time_claims','pb_claim_events','pb_claim_heads','pb_commands','pb_account_pins',
  'finance_entries','finance_entry_lines','finance_entry_line_dimensions','finance_posting_effects','ar_invoices','ar_invoice_lines','ar_receipts','ar_receipt_allocations','domain_audit_events','outbox_events'] LOOP
  EXECUTE format('CREATE CONSTRAINT TRIGGER pb_source_close AFTER INSERT OR UPDATE OR DELETE ON reconforge.%I DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION reconforge.pb_reverse_close()',n);
 END LOOP;
END $pb$;
"""

DOWNGRADE_SQL = r"""
DO $pb$ BEGIN IF EXISTS(SELECT 1 FROM reconforge.pb_plans) OR EXISTS(SELECT 1 FROM reconforge.pb_prices)
 THEN RAISE EXCEPTION 'Populated project billing history requires restore; destructive downgrade refused';END IF;END $pb$;
DO $pb$ DECLARE n TEXT;BEGIN FOREACH n IN ARRAY ARRAY['pb_prices','pb_plans','pb_time_claims','pb_claim_events','pb_claim_heads','pb_commands','pb_account_pins',
 'finance_entries','finance_entry_lines','finance_entry_line_dimensions','finance_posting_effects','ar_invoices','ar_invoice_lines','ar_receipts','ar_receipt_allocations','domain_audit_events','outbox_events'] LOOP
 EXECUTE format('DROP TRIGGER IF EXISTS pb_source_close ON reconforge.%I',n);END LOOP;END $pb$;
DROP TRIGGER pb_original_ar_invoice ON reconforge.ar_invoices;
DROP TRIGGER pb_original_ar_receipt ON reconforge.ar_receipts;
ALTER TABLE reconforge.ar_invoices DROP COLUMN pb_owner_id;
ALTER TABLE reconforge.ar_receipts DROP COLUMN pb_owner_id;
DROP TABLE reconforge.pb_commands,reconforge.pb_claim_heads,reconforge.pb_claim_events,reconforge.pb_time_claims,reconforge.pb_account_pins,reconforge.pb_plans,reconforge.pb_prices;
ALTER TABLE reconforge.finance_accounts DROP CONSTRAINT pb_native_account_identity;
DROP FUNCTION reconforge.pb_reverse_close(),reconforge.pb_close(TEXT,TEXT),reconforge.pb_phases(TEXT,JSONB),
 reconforge.pb_audit(TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT),reconforge.pb_calculate(TEXT,TEXT),reconforge.pb_price_close(TEXT,TEXT),
 reconforge.pb_claim(TEXT,TEXT,TEXT,TEXT,TEXT),reconforge.pb_guard(),reconforge.pb_native_ar_owner(),reconforge.pb_assert(BOOLEAN,TEXT);
"""


def upgrade_project_time_billing_schema(connection: object) -> None:
    connection.execute(UPGRADE_SQL)  # type: ignore[attr-defined]


def downgrade_project_time_billing_schema(connection: object) -> None:
    connection.execute(DOWNGRADE_SQL)  # type: ignore[attr-defined]
