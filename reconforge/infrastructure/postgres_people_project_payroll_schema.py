"""Additive nonstatutory workforce source/claim/budget/native GL closure."""

UPGRADE_SQL = r"""
DO $hc$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM pg_catalog.pg_roles WHERE rolname='reconforge_personnel_runtime') THEN
  CREATE ROLE reconforge_personnel_runtime NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEROLE NOCREATEDB NOINHERIT NOREPLICATION;
 END IF;
 IF EXISTS(SELECT 1 FROM pg_catalog.pg_roles WHERE rolname='reconforge_personnel_runtime'
  AND (rolcanlogin OR rolsuper OR rolbypassrls OR rolcreaterole OR rolcreatedb OR rolinherit OR rolreplication)) THEN
  RAISE EXCEPTION 'Existing personnel role violates the reviewed private-backend contract';
 END IF;
 IF EXISTS(SELECT 1 FROM reconforge.finance_entries WHERE upper(entry_number) LIKE 'HC1-%' OR upper(entry_number) LIKE 'HC1P-%'
   OR upper(id) LIKE 'HC1-%' OR upper(id) LIKE 'HC1P-%') THEN RAISE EXCEPTION 'HC1 native namespace already exists without its owner'; END IF;
END $hc$;
CREATE FUNCTION reconforge.hc_assert(ok BOOLEAN,message TEXT) RETURNS VOID LANGUAGE plpgsql SET search_path=pg_catalog AS $hc$
BEGIN IF ok IS DISTINCT FROM TRUE THEN RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='people_payroll_owner',MESSAGE=message; END IF; END $hc$;
CREATE FUNCTION reconforge.hc_private() RETURNS BOOLEAN LANGUAGE sql STABLE SET search_path=pg_catalog AS $hc$
 SELECT pg_has_role(session_user,'reconforge_personnel_runtime','MEMBER') AND EXISTS(
 SELECT 1 FROM reconforge.identity_users u JOIN reconforge.identity_user_roles a ON a.tenant_id=u.tenant_id AND a.user_id=u.id
 JOIN reconforge.identity_role_permissions p ON p.tenant_id=a.tenant_id AND p.role_id=a.role_id JOIN reconforge.identity_roles r ON r.tenant_id=a.tenant_id AND r.id=a.role_id
 WHERE u.tenant_id=current_setting('app.tenant_id',true) AND u.id=current_setting('app.personnel_actor_id',true)
 AND NOT u.disabled AND a.active AND p.active AND r.active AND p.permission_name='people_project_payroll.read_sensitive')
$hc$;
CREATE FUNCTION reconforge.hc_actor(t TEXT,w TEXT,o TEXT,e TEXT,actor TEXT,permission TEXT) RETURNS BOOLEAN
 LANGUAGE plpgsql SET search_path=pg_catalog AS $hc$
DECLARE valid BOOLEAN;
BEGIN
 PERFORM 1 FROM reconforge.identity_users WHERE tenant_id=t AND id=actor AND NOT disabled FOR SHARE;
 PERFORM reconforge.hc_assert(FOUND,'Workforce command requires a current persisted human');
 PERFORM 1 FROM reconforge.identity_user_roles a JOIN reconforge.identity_role_permissions p ON p.tenant_id=a.tenant_id AND p.role_id=a.role_id
 JOIN reconforge.identity_roles r ON r.tenant_id=a.tenant_id AND r.id=a.role_id
 WHERE a.tenant_id=t AND a.user_id=actor AND a.active AND p.active AND r.active AND p.permission_name=permission FOR SHARE OF a,p,r;
 PERFORM reconforge.hc_assert(FOUND,'Workforce command requires current phase permission');
 PERFORM 1 FROM reconforge.principal_scope_grants g WHERE g.tenant_id=t AND g.principal_type='user' AND g.principal_id=actor AND g.revoked_at IS NULL
 AND ((g.scope_type='workspace' AND g.scope_id=w) OR(g.scope_type='organization' AND g.scope_id=o) OR(g.scope_type='legal_entity' AND g.scope_id=e))
 ORDER BY g.scope_type,g.scope_id FOR SHARE;
 SELECT count(DISTINCT scope_type)=3 INTO valid FROM reconforge.principal_scope_grants g WHERE g.tenant_id=t AND g.principal_type='user'
 AND g.principal_id=actor AND g.revoked_at IS NULL AND ((g.scope_type='workspace' AND g.scope_id=w)
 OR(g.scope_type='organization' AND g.scope_id=o) OR(g.scope_type='legal_entity' AND g.scope_id=e));
 PERFORM reconforge.hc_assert(valid AND reconforge.irp_scope(t,w,o,e),'Workforce source requires current explicit hierarchy grants');
 RETURN TRUE;
END $hc$;
CREATE FUNCTION reconforge.hc_even(n NUMERIC,d NUMERIC) RETURNS NUMERIC LANGUAGE sql IMMUTABLE STRICT SET search_path=pg_catalog AS $hc$
 SELECT trunc(n/d)+CASE WHEN mod(n,d)*2>d OR(mod(n,d)*2=d AND mod(trunc(n/d),2)=1) THEN 1 ELSE 0 END
$hc$;
CREATE TABLE reconforge.hc_employees(
 tenant_id TEXT NOT NULL,id TEXT NOT NULL CHECK(id~'^HCE-[0-9a-f]{32}$'),workspace_id TEXT NOT NULL,organization_id TEXT NOT NULL,legal_entity_id TEXT NOT NULL,
 employee_code TEXT NOT NULL CHECK(employee_code~'^[A-Z0-9][A-Z0-9._/-]{0,63}$'),linked_user_id TEXT,preparer_id TEXT NOT NULL,audit_id TEXT NOT NULL,outbox_id TEXT NOT NULL,
 PRIMARY KEY(tenant_id,id),UNIQUE(tenant_id,workspace_id,organization_id,legal_entity_id,employee_code),
 FOREIGN KEY(tenant_id,linked_user_id) REFERENCES reconforge.identity_users(tenant_id,id));
CREATE TABLE reconforge.hc_employee_private(
 tenant_id TEXT NOT NULL,employee_id TEXT NOT NULL,workspace_id TEXT NOT NULL,organization_id TEXT NOT NULL,legal_entity_id TEXT NOT NULL,
 display_name TEXT NOT NULL CHECK(length(display_name) BETWEEN 1 AND 160),PRIMARY KEY(tenant_id,employee_id),
 FOREIGN KEY(tenant_id,employee_id) REFERENCES reconforge.hc_employees(tenant_id,id));
CREATE TABLE reconforge.hc_employments(
 tenant_id TEXT NOT NULL,id TEXT NOT NULL CHECK(id~'^HCA-[0-9a-f]{32}$'),employee_id TEXT NOT NULL,workspace_id TEXT NOT NULL,organization_id TEXT NOT NULL,legal_entity_id TEXT NOT NULL,
 valid_from DATE NOT NULL,valid_through DATE NOT NULL CHECK(valid_through>=valid_from),currency_code TEXT NOT NULL,currency_precision INTEGER NOT NULL CHECK(currency_precision BETWEEN 0 AND 8),
 currency_rounding_policy TEXT NOT NULL,currency_registry_version TEXT NOT NULL,currency_registry_digest TEXT NOT NULL CHECK(currency_registry_digest~'^[0-9a-f]{64}$'),preparer_id TEXT NOT NULL,
 request_digest TEXT NOT NULL,audit_id TEXT NOT NULL,outbox_id TEXT NOT NULL,
 PRIMARY KEY(tenant_id,id),FOREIGN KEY(tenant_id,employee_id) REFERENCES reconforge.hc_employees(tenant_id,id));
CREATE TABLE reconforge.hc_rates(
 tenant_id TEXT NOT NULL,employment_id TEXT NOT NULL,workspace_id TEXT NOT NULL,organization_id TEXT NOT NULL,legal_entity_id TEXT NOT NULL,
 hourly_rate_minor BIGINT NOT NULL CHECK(hourly_rate_minor BETWEEN 1 AND 9000000000000000000),PRIMARY KEY(tenant_id,employment_id),
 FOREIGN KEY(tenant_id,employment_id) REFERENCES reconforge.hc_employments(tenant_id,id));
CREATE TABLE reconforge.hc_projects(
 tenant_id TEXT NOT NULL,id TEXT NOT NULL CHECK(id~'^HCP-[0-9a-f]{32}$'),workspace_id TEXT NOT NULL,organization_id TEXT NOT NULL,legal_entity_id TEXT NOT NULL,
 project_code TEXT NOT NULL,dimension_id TEXT NOT NULL,value_id TEXT NOT NULL,dimension_code TEXT NOT NULL,value_code TEXT NOT NULL,preparer_id TEXT NOT NULL,
 request_digest TEXT NOT NULL,audit_id TEXT NOT NULL,outbox_id TEXT NOT NULL,
 PRIMARY KEY(tenant_id,id),UNIQUE(tenant_id,workspace_id,organization_id,legal_entity_id,project_code),
 FOREIGN KEY(tenant_id,dimension_id) REFERENCES reconforge.finance_dimensions(tenant_id,id),FOREIGN KEY(tenant_id,value_id) REFERENCES reconforge.finance_dimension_values(tenant_id,id));
CREATE TABLE reconforge.hc_times(
 tenant_id TEXT NOT NULL,id TEXT NOT NULL CHECK(id~'^HCT-[0-9a-f]{32}$'),workspace_id TEXT NOT NULL,organization_id TEXT NOT NULL,legal_entity_id TEXT NOT NULL,
 employee_id TEXT NOT NULL,employment_id TEXT NOT NULL,business_date DATE NOT NULL,lines JSONB NOT NULL CHECK(jsonb_typeof(lines)='array' AND jsonb_array_length(lines) BETWEEN 1 AND 128),
 request_json JSONB NOT NULL,source_digest TEXT NOT NULL CHECK(source_digest~'^[0-9a-f]{64}$'),submitter_id TEXT NOT NULL,approver_id TEXT,audit_id TEXT,outbox_id TEXT,
 submit_audit_id TEXT NOT NULL,submit_outbox_id TEXT NOT NULL,
 PRIMARY KEY(tenant_id,id),UNIQUE(tenant_id,workspace_id,organization_id,legal_entity_id,employee_id,business_date),
 FOREIGN KEY(tenant_id,employee_id) REFERENCES reconforge.hc_employees(tenant_id,id),FOREIGN KEY(tenant_id,employment_id) REFERENCES reconforge.hc_employments(tenant_id,id));
CREATE TABLE reconforge.hc_payruns(
 tenant_id TEXT NOT NULL,id TEXT NOT NULL CHECK(id~'^HC1-[0-9a-f]{32}$'),workspace_id TEXT NOT NULL,organization_id TEXT NOT NULL,legal_entity_id TEXT NOT NULL,
 entry_id TEXT NOT NULL,budget_id TEXT NOT NULL,commitment_id TEXT NOT NULL,amount_minor BIGINT NOT NULL CHECK(amount_minor BETWEEN 1 AND 9000000000000000000),
 phase INTEGER NOT NULL CHECK(phase BETWEEN 0 AND 3),payload JSONB NOT NULL,preparer_id TEXT NOT NULL,reviewer_id TEXT,poster_id TEXT,canceller_id TEXT,effect_id TEXT,
 audit_id TEXT NOT NULL,outbox_id TEXT NOT NULL,review_audit_id TEXT,review_outbox_id TEXT,post_audit_id TEXT,post_outbox_id TEXT,cancel_audit_id TEXT,cancel_outbox_id TEXT,
 PRIMARY KEY(tenant_id,id),UNIQUE(tenant_id,entry_id),FOREIGN KEY(tenant_id,entry_id) REFERENCES reconforge.finance_entries(tenant_id,id),
 FOREIGN KEY(tenant_id,budget_id) REFERENCES reconforge.budget_envelopes(tenant_id,id),FOREIGN KEY(tenant_id,effect_id) REFERENCES reconforge.finance_posting_effects(tenant_id,id));
CREATE TABLE reconforge.hc_payrun_private(
 tenant_id TEXT NOT NULL,plan_id TEXT NOT NULL,workspace_id TEXT NOT NULL,organization_id TEXT NOT NULL,legal_entity_id TEXT NOT NULL,payload JSONB NOT NULL,
 PRIMARY KEY(tenant_id,plan_id),FOREIGN KEY(tenant_id,plan_id) REFERENCES reconforge.hc_payruns(tenant_id,id));
CREATE TABLE reconforge.hc_payments(
 tenant_id TEXT NOT NULL,id TEXT NOT NULL CHECK(id~'^HC1P-[0-9a-f]{32}$'),workspace_id TEXT NOT NULL,organization_id TEXT NOT NULL,legal_entity_id TEXT NOT NULL,
 payrun_id TEXT NOT NULL,entry_id TEXT NOT NULL,amount_minor BIGINT NOT NULL CHECK(amount_minor BETWEEN 1 AND 9000000000000000000),phase INTEGER NOT NULL CHECK(phase BETWEEN 0 AND 2),
 payload JSONB NOT NULL,preparer_id TEXT NOT NULL,reviewer_id TEXT,poster_id TEXT,effect_id TEXT,audit_id TEXT NOT NULL,outbox_id TEXT NOT NULL,
 review_audit_id TEXT,review_outbox_id TEXT,post_audit_id TEXT,post_outbox_id TEXT,
 PRIMARY KEY(tenant_id,id),UNIQUE(tenant_id,entry_id),FOREIGN KEY(tenant_id,payrun_id) REFERENCES reconforge.hc_payruns(tenant_id,id),
 FOREIGN KEY(tenant_id,entry_id) REFERENCES reconforge.finance_entries(tenant_id,id),FOREIGN KEY(tenant_id,effect_id) REFERENCES reconforge.finance_posting_effects(tenant_id,id));
CREATE UNIQUE INDEX hc_pending_payment ON reconforge.hc_payments(tenant_id,payrun_id) WHERE phase<2;
CREATE TABLE reconforge.hc_payment_private(
 tenant_id TEXT NOT NULL,plan_id TEXT NOT NULL,workspace_id TEXT NOT NULL,organization_id TEXT NOT NULL,legal_entity_id TEXT NOT NULL,payload JSONB NOT NULL,
 PRIMARY KEY(tenant_id,plan_id),FOREIGN KEY(tenant_id,plan_id) REFERENCES reconforge.hc_payments(tenant_id,id));
CREATE TABLE reconforge.hc_time_claims(
 tenant_id TEXT NOT NULL,time_id TEXT NOT NULL,payrun_id TEXT NOT NULL,source_digest TEXT NOT NULL,
 PRIMARY KEY(tenant_id,time_id,payrun_id),FOREIGN KEY(tenant_id,time_id) REFERENCES reconforge.hc_times(tenant_id,id),
 FOREIGN KEY(tenant_id,payrun_id) REFERENCES reconforge.hc_payruns(tenant_id,id));
CREATE TABLE reconforge.hc_claim_events(
 tenant_id TEXT NOT NULL,id TEXT NOT NULL,time_id TEXT NOT NULL,payrun_id TEXT NOT NULL,sequence INTEGER NOT NULL CHECK(sequence>=1),
 operation TEXT NOT NULL CHECK(operation IN('Claim','Release','Consume')),source_digest TEXT NOT NULL,actor_id TEXT NOT NULL,audit_id TEXT NOT NULL,outbox_id TEXT NOT NULL,
 PRIMARY KEY(tenant_id,id),UNIQUE(tenant_id,time_id,sequence),UNIQUE(tenant_id,time_id,payrun_id,operation),
 FOREIGN KEY(tenant_id,time_id,payrun_id) REFERENCES reconforge.hc_time_claims(tenant_id,time_id,payrun_id));
CREATE TABLE reconforge.hc_claim_heads(
 tenant_id TEXT NOT NULL,time_id TEXT NOT NULL,payrun_id TEXT NOT NULL,sequence INTEGER NOT NULL CHECK(sequence>=1),state TEXT NOT NULL CHECK(state IN('Active','Released','Consumed')),
 PRIMARY KEY(tenant_id,time_id),FOREIGN KEY(tenant_id,time_id,payrun_id) REFERENCES reconforge.hc_time_claims(tenant_id,time_id,payrun_id),
 CONSTRAINT hc_claim_head_original_event FOREIGN KEY(tenant_id,time_id,sequence) REFERENCES reconforge.hc_claim_events(tenant_id,time_id,sequence)
 DEFERRABLE INITIALLY DEFERRED);
CREATE TABLE reconforge.hc_commands(
 tenant_id TEXT NOT NULL,workspace_id TEXT NOT NULL,organization_id TEXT NOT NULL,legal_entity_id TEXT NOT NULL,command_id TEXT NOT NULL CHECK(length(command_id) BETWEEN 1 AND 140),
 operation TEXT NOT NULL CHECK(operation IN('personnel','manage','approve_time','prepare','review','post','pay','cancel')),
 actor_id TEXT NOT NULL,request_digest TEXT NOT NULL CHECK(request_digest~'^[0-9a-f]{64}$'),request_json JSONB NOT NULL,response_json JSONB NOT NULL,
 PRIMARY KEY(tenant_id,workspace_id,command_id),FOREIGN KEY(tenant_id,actor_id) REFERENCES reconforge.identity_users(tenant_id,id));

CREATE FUNCTION reconforge.hc_guard_immutable() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $hc$
DECLARE before_row JSONB:=to_jsonb(OLD);after_row JSONB:=to_jsonb(NEW);
BEGIN
 IF TG_OP='UPDATE' AND TG_TABLE_NAME='hc_times' AND before_row->>'approver_id' IS NULL AND after_row->>'approver_id' IS NOT NULL
  AND (to_jsonb(NEW)-ARRAY['approver_id','audit_id','outbox_id'])=(to_jsonb(OLD)-ARRAY['approver_id','audit_id','outbox_id']) THEN RETURN NEW; END IF;
 IF TG_OP='UPDATE' AND TG_TABLE_NAME IN('hc_payruns','hc_payments')
  AND (((before_row->>'phase')::INTEGER=0 AND (after_row->>'phase')::INTEGER=1) OR((before_row->>'phase')::INTEGER=1 AND (after_row->>'phase')::INTEGER=2)
   OR(TG_TABLE_NAME='hc_payruns' AND (before_row->>'phase')::INTEGER IN(0,1) AND (after_row->>'phase')::INTEGER=3))
  AND (to_jsonb(NEW)-ARRAY['phase','reviewer_id','poster_id','canceller_id','effect_id','review_audit_id','review_outbox_id','post_audit_id','post_outbox_id','cancel_audit_id','cancel_outbox_id'])
   =(to_jsonb(OLD)-ARRAY['phase','reviewer_id','poster_id','canceller_id','effect_id','review_audit_id','review_outbox_id','post_audit_id','post_outbox_id','cancel_audit_id','cancel_outbox_id']) THEN
   IF before_row->>'phase'='1' THEN
    PERFORM reconforge.hc_assert(after_row->>'reviewer_id'=before_row->>'reviewer_id' AND after_row->>'review_audit_id'=before_row->>'review_audit_id' AND after_row->>'review_outbox_id'=before_row->>'review_outbox_id','Original review is immutable');
   END IF;
   RETURN NEW;
 END IF;
 IF TG_OP='UPDATE' AND TG_TABLE_NAME='hc_claim_heads' AND (after_row->>'sequence')::INTEGER=(before_row->>'sequence')::INTEGER+1
  AND after_row->>'tenant_id'=before_row->>'tenant_id' AND after_row->>'time_id'=before_row->>'time_id'
  AND before_row->>'state'<>'Consumed' THEN RETURN NEW; END IF;
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='people_payroll_owner',MESSAGE='Workforce source and original claim history are immutable';
END $hc$;
CREATE FUNCTION reconforge.hc_source_guard() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $hc$
DECLARE a RECORD;e RECORD;line JSONB;p RECORD;previous_end INTEGER:=-1;start_m INTEGER;end_m INTEGER;bound RECORD;permission TEXT;row_value JSONB:=to_jsonb(NEW);current_actor TEXT;
BEGIN
 IF TG_TABLE_NAME='hc_employees' THEN
  PERFORM reconforge.hc_assert(reconforge.hc_private(),'Private backend is required for personnel admission');
  PERFORM reconforge.hc_actor(NEW.tenant_id,NEW.workspace_id,NEW.organization_id,NEW.legal_entity_id,NEW.preparer_id,'people_project_payroll.personnel');
 ELSIF TG_TABLE_NAME IN('hc_payruns','hc_payments') THEN
  PERFORM reconforge.hc_assert(reconforge.hc_private(),'Private backend is required for financial workforce commands');
  permission:=CASE WHEN TG_OP='INSERT' THEN CASE TG_TABLE_NAME WHEN 'hc_payruns' THEN 'prepare' ELSE 'pay' END
   WHEN NEW.phase=1 THEN 'review' WHEN NEW.phase=2 THEN 'post' ELSE 'prepare' END;
  current_actor:=CASE WHEN TG_OP='INSERT' THEN row_value->>'preparer_id' WHEN NEW.phase=1 THEN row_value->>'reviewer_id'
   WHEN NEW.phase=2 THEN row_value->>'poster_id' ELSE row_value->>'canceller_id' END;
  PERFORM reconforge.hc_actor(NEW.tenant_id,NEW.workspace_id,NEW.organization_id,NEW.legal_entity_id,
   current_actor,'people_project_payroll.'||permission);
  PERFORM reconforge.hc_actor(NEW.tenant_id,NEW.workspace_id,NEW.organization_id,NEW.legal_entity_id,
   current_actor,
   CASE permission WHEN 'review' THEN 'finance_core.validate' WHEN 'post' THEN 'finance_core.post' ELSE 'finance_core.manage' END);
  PERFORM reconforge.hc_actor(NEW.tenant_id,NEW.workspace_id,NEW.organization_id,NEW.legal_entity_id,current_actor,'budget_control.read');
  IF TG_TABLE_NAME='hc_payruns' AND permission<>'review' THEN
   PERFORM reconforge.hc_actor(NEW.tenant_id,NEW.workspace_id,NEW.organization_id,NEW.legal_entity_id,current_actor,'budget_control.manage');
  END IF;
 ELSIF TG_TABLE_NAME='hc_employments' THEN
  SELECT * INTO a FROM reconforge.hc_employees WHERE tenant_id=NEW.tenant_id AND id=NEW.employee_id FOR UPDATE;
  PERFORM reconforge.hc_assert(a.id IS NOT NULL AND (a.workspace_id,a.organization_id,a.legal_entity_id)=(NEW.workspace_id,NEW.organization_id,NEW.legal_entity_id),'Employment scope differs from person');
  PERFORM reconforge.hc_assert(NOT EXISTS(SELECT 1 FROM reconforge.hc_employments z WHERE z.tenant_id=NEW.tenant_id AND z.employee_id=NEW.employee_id
    AND z.valid_from<=NEW.valid_through AND z.valid_through>=NEW.valid_from),'Effective employment versions must not overlap');
  PERFORM reconforge.hc_actor(NEW.tenant_id,NEW.workspace_id,NEW.organization_id,NEW.legal_entity_id,NEW.preparer_id,'people_project_payroll.personnel');
 ELSIF TG_TABLE_NAME='hc_projects' THEN
  SELECT * INTO p FROM reconforge.finance_dimensions WHERE tenant_id=NEW.tenant_id AND id=NEW.dimension_id;
  SELECT * INTO bound FROM reconforge.finance_dimension_values WHERE tenant_id=NEW.tenant_id AND id=NEW.value_id;
  PERFORM reconforge.hc_assert(p.active AND bound.active AND p.dimension_type='Project' AND p.workspace_id=NEW.workspace_id AND bound.dimension_id=p.id
    AND p.dimension_code=NEW.dimension_code AND bound.value_code=NEW.value_code,'Project must bind its original active native dimension');
  PERFORM reconforge.hc_actor(NEW.tenant_id,NEW.workspace_id,NEW.organization_id,NEW.legal_entity_id,NEW.preparer_id,'people_project_payroll.manage');
 ELSIF TG_TABLE_NAME='hc_times' THEN
  SELECT * INTO a FROM reconforge.hc_employees WHERE tenant_id=NEW.tenant_id AND id=NEW.employee_id FOR UPDATE;
  SELECT * INTO e FROM reconforge.hc_employments WHERE tenant_id=NEW.tenant_id AND id=NEW.employment_id FOR SHARE;
  PERFORM reconforge.hc_assert(a.id IS NOT NULL AND e.employee_id=a.id AND NEW.business_date BETWEEN e.valid_from AND e.valid_through
    AND (a.workspace_id,a.organization_id,a.legal_entity_id)=(NEW.workspace_id,NEW.organization_id,NEW.legal_entity_id),'Time requires effective original employment and canonical scope');
  PERFORM reconforge.hc_assert(NEW.source_digest=reconforge.irp_digest(NEW.request_json||jsonb_build_object('employment_id',NEW.employment_id))
    AND NEW.request_json->'lines'=NEW.lines AND NEW.request_json->>'business_date'=NEW.business_date::text
    AND NEW.request_json->>'employee_id'=NEW.employee_id,'Time digest must bind its original version and intervals');
  FOR line IN SELECT value FROM jsonb_array_elements(NEW.lines) ORDER BY (value->>'start_minute')::INTEGER LOOP
   PERFORM reconforge.hc_assert(jsonb_typeof(line)='object' AND (SELECT count(*) FROM jsonb_object_keys(line))=3
    AND line ?& ARRAY['project_id','start_minute','end_minute'] AND line->>'start_minute'~'^(0|[1-9][0-9]{0,3})$'
    AND line->>'end_minute'~'^[1-9][0-9]{0,3}$' AND jsonb_typeof(line->'start_minute')='number' AND jsonb_typeof(line->'end_minute')='number',
    'Time interval requires closed exact integer fields');
   start_m:=(line->>'start_minute')::INTEGER;end_m:=(line->>'end_minute')::INTEGER;
   PERFORM reconforge.hc_assert(start_m>=0 AND end_m>start_m AND end_m<=1440 AND start_m>=previous_end,'Employee intervals must not overlap');previous_end:=end_m;
   SELECT * INTO p FROM reconforge.hc_projects WHERE tenant_id=NEW.tenant_id AND id=line->>'project_id';
   PERFORM reconforge.hc_assert(p.id IS NOT NULL AND (p.workspace_id,p.organization_id,p.legal_entity_id)=(NEW.workspace_id,NEW.organization_id,NEW.legal_entity_id),'Time project must share its original employee scope');
  END LOOP;
  IF TG_OP='UPDATE' THEN
   PERFORM reconforge.hc_assert(NEW.approver_id NOT IN(NEW.submitter_id,COALESCE(a.linked_user_id,'')),'Employee or submitter cannot approve their time');
   PERFORM reconforge.hc_actor(NEW.tenant_id,NEW.workspace_id,NEW.organization_id,NEW.legal_entity_id,NEW.approver_id,'people_project_payroll.approve_time');
  ELSE PERFORM reconforge.hc_actor(NEW.tenant_id,NEW.workspace_id,NEW.organization_id,NEW.legal_entity_id,NEW.submitter_id,'people_project_payroll.manage');END IF;
 ELSIF TG_TABLE_NAME='hc_commands' THEN
  permission:=CASE NEW.operation WHEN 'cancel' THEN 'prepare' ELSE NEW.operation END;
  PERFORM reconforge.hc_actor(NEW.tenant_id,NEW.workspace_id,NEW.organization_id,NEW.legal_entity_id,NEW.actor_id,'people_project_payroll.'||permission);
  PERFORM reconforge.hc_assert(NEW.request_digest=reconforge.irp_digest(jsonb_build_object('operation',NEW.operation,'request',NEW.request_json)),'Workforce command must retain exact original request');
 END IF;RETURN NEW;
END $hc$;
CREATE TRIGGER hc_employment_admission BEFORE INSERT ON reconforge.hc_employments FOR EACH ROW EXECUTE FUNCTION reconforge.hc_source_guard();
CREATE TRIGGER hc_employee_admission BEFORE INSERT ON reconforge.hc_employees FOR EACH ROW EXECUTE FUNCTION reconforge.hc_source_guard();
CREATE TRIGGER hc_payrun_admission BEFORE INSERT OR UPDATE ON reconforge.hc_payruns FOR EACH ROW EXECUTE FUNCTION reconforge.hc_source_guard();
CREATE TRIGGER hc_payment_admission BEFORE INSERT OR UPDATE ON reconforge.hc_payments FOR EACH ROW EXECUTE FUNCTION reconforge.hc_source_guard();
CREATE TRIGGER hc_project_admission BEFORE INSERT ON reconforge.hc_projects FOR EACH ROW EXECUTE FUNCTION reconforge.hc_source_guard();
CREATE TRIGGER hc_time_admission BEFORE INSERT OR UPDATE ON reconforge.hc_times FOR EACH ROW EXECUTE FUNCTION reconforge.hc_source_guard();
CREATE TRIGGER hc_command_admission BEFORE INSERT ON reconforge.hc_commands FOR EACH ROW EXECUTE FUNCTION reconforge.hc_source_guard();

CREATE FUNCTION reconforge.hc_claim(t TEXT,ti TEXT,pi TEXT,operation TEXT,actor TEXT) RETURNS VOID LANGUAGE plpgsql SET search_path=pg_catalog AS $hc$
DECLARE tm RECORD;p RECORD;h RECORD;old_owner RECORD;next_seq INTEGER;a TEXT;b TEXT;new_state TEXT;
BEGIN
 SELECT * INTO tm FROM reconforge.hc_times WHERE tenant_id=t AND id=ti FOR UPDATE;
 SELECT * INTO p FROM reconforge.hc_payruns WHERE tenant_id=t AND id=pi;
 SELECT * INTO h FROM reconforge.hc_claim_heads WHERE tenant_id=t AND time_id=ti FOR UPDATE;
 PERFORM reconforge.hc_assert(tm.approver_id IS NOT NULL AND p.id IS NOT NULL AND (tm.workspace_id,tm.organization_id,tm.legal_entity_id)=(p.workspace_id,p.organization_id,p.legal_entity_id),'Whole time claim requires approved original scoped source');
 next_seq:=COALESCE(h.sequence,0)+1;
 IF operation='Claim' THEN
  PERFORM reconforge.hc_assert(p.phase=0 AND actor=p.preparer_id AND (h.time_id IS NULL OR h.state='Released'),'Only released or unclaimed whole time can enter a prepared payrun');
  IF h.time_id IS NOT NULL THEN
   SELECT * INTO old_owner FROM reconforge.hc_payruns WHERE tenant_id=t AND id=h.payrun_id;
   PERFORM reconforge.hc_assert(old_owner.phase=3 AND NOT EXISTS(SELECT 1 FROM reconforge.finance_posting_effects WHERE tenant_id=t AND entry_id=old_owner.entry_id)
    AND EXISTS(SELECT 1 FROM reconforge.budget_commitment_events WHERE tenant_id=t AND commitment_id=old_owner.commitment_id
      AND budget_commitment_events.operation='Release' AND amount_minor=old_owner.amount_minor AND remaining_minor=0),'Cancelled claim requires actual complete budget release before re-claim');
  END IF;
  INSERT INTO reconforge.hc_time_claims(tenant_id,time_id,payrun_id,source_digest) VALUES(t,ti,pi,tm.source_digest);
  a:=p.audit_id;b:=p.outbox_id;new_state:='Active';
 ELSIF operation='Consume' THEN
  PERFORM reconforge.hc_assert(h.payrun_id=pi AND h.state='Active' AND p.phase=2 AND p.effect_id IS NOT NULL AND actor=p.poster_id,'Consumption requires original posted accrual');
  a:=p.post_audit_id;b:=p.post_outbox_id;new_state:='Consumed';
 ELSIF operation='Release' THEN
  PERFORM reconforge.hc_assert(h.payrun_id=pi AND h.state='Active' AND p.phase=3 AND actor=p.canceller_id,'Consumed time cannot release or change owner');
  a:=p.cancel_audit_id;b:=p.cancel_outbox_id;new_state:='Released';
 ELSE PERFORM reconforge.hc_assert(FALSE,'Unknown whole-time claim operation');END IF;
 INSERT INTO reconforge.hc_claim_events(tenant_id,id,time_id,payrun_id,sequence,operation,source_digest,actor_id,audit_id,outbox_id)
 VALUES(t,'HCC-'||encode(sha256(convert_to(t||':'||ti||':'||next_seq::text,'UTF8')),'hex'),ti,pi,next_seq,operation,tm.source_digest,actor,a,b);
 INSERT INTO reconforge.hc_claim_heads(tenant_id,time_id,payrun_id,sequence,state) VALUES(t,ti,pi,next_seq,new_state)
 ON CONFLICT(tenant_id,time_id) DO UPDATE SET payrun_id=excluded.payrun_id,sequence=excluded.sequence,state=excluded.state;
END $hc$;

CREATE FUNCTION reconforge.hc_calculate(t TEXT,pi TEXT) RETURNS JSONB LANGUAGE plpgsql SET search_path=pg_catalog AS $hc$
DECLARE result JSONB;employees JSONB;projects JSONB;ids JSONB;earned_total NUMERIC;
BEGIN
 WITH source AS(SELECT tm.id,tm.employee_id,tm.lines,r.hourly_rate_minor FROM reconforge.hc_time_claims claim
 JOIN reconforge.hc_times tm ON tm.tenant_id=claim.tenant_id AND tm.id=claim.time_id
 JOIN reconforge.hc_rates r ON r.tenant_id=tm.tenant_id AND r.employment_id=tm.employment_id WHERE claim.tenant_id=t AND claim.payrun_id=pi),
 numerators AS(SELECT s.employee_id,line->>'project_id' AS project,sum(((line->>'end_minute')::NUMERIC-(line->>'start_minute')::NUMERIC)*s.hourly_rate_minor) AS n
 FROM source s CROSS JOIN LATERAL jsonb_array_elements(s.lines) line GROUP BY s.employee_id,line->>'project_id'),
 cumulative AS(SELECT *,reconforge.hc_even(sum(n) OVER(PARTITION BY employee_id ORDER BY project COLLATE "C"),60) AS total FROM numerators),
 allocated AS(SELECT *,total-COALESCE(lag(total) OVER(PARTITION BY employee_id ORDER BY project COLLATE "C"),0) AS amount FROM cumulative),
 per_employee AS(SELECT employee_id,max(total) AS gross,jsonb_object_agg(project,amount ORDER BY project COLLATE "C") AS allocation FROM allocated GROUP BY employee_id),
 employee_json AS(SELECT jsonb_agg(jsonb_build_object('employee_id',employee_id,'time_entry_ids',(SELECT jsonb_agg(id ORDER BY id COLLATE "C") FROM source s WHERE s.employee_id=e.employee_id),
 'gross_minor',gross,'project_minor',allocation) ORDER BY employee_id COLLATE "C") AS employee_payload,sum(gross) AS total FROM per_employee e),
 per_project AS(SELECT project,sum(amount) AS total FROM allocated GROUP BY project)
 SELECT e.employee_payload,e.total,(SELECT jsonb_object_agg(project,total ORDER BY project COLLATE "C") FROM per_project),
 (SELECT jsonb_agg(id ORDER BY id COLLATE "C") FROM source) INTO employees,earned_total,projects,ids FROM employee_json e;
 PERFORM reconforge.hc_assert(earned_total BETWEEN 1 AND 9000000000000000000 AND jsonb_array_length(employees) BETWEEN 1 AND 100 AND jsonb_array_length(ids) BETWEEN 1 AND 1000,'Payrun exact earned population is absent or out of bounds');
 result:=jsonb_build_object('contract_version','people-project-payroll-v1','earnings_rounding','HALF_EVEN','allocation','canonical-project-cumulative-v1',
 'time_entry_ids',ids,'employees',employees,'project_minor',projects,'gross_minor',earned_total);RETURN result;
END $hc$;

CREATE FUNCTION reconforge.hc_close(t TEXT,pi TEXT) RETURNS VOID LANGUAGE plpgsql SET search_path=pg_catalog AS $hc$
DECLARE p RECORD;v JSONB;priv JSONB;calc JSONB;e RECORD;b RECORD;rate RECORD;line RECORD;project RECORD;expected JSONB;actual JSONB;paid NUMERIC;amount NUMERIC;
BEGIN
 SELECT * INTO p FROM reconforge.hc_payruns WHERE tenant_id=t AND id=pi;
 PERFORM reconforge.hc_assert(p.id IS NOT NULL,'HC1 native entry requires its complete source owner');v:=p.payload;
 SELECT payload INTO priv FROM reconforge.hc_payrun_private WHERE tenant_id=t AND plan_id=pi;
 calc:=reconforge.hc_calculate(t,pi);
 PERFORM reconforge.hc_assert(priv=calc AND v->'time_entry_ids'=calc->'time_entry_ids' AND v->'project_minor'=calc->'project_minor'
 AND p.amount_minor=(calc->>'gross_minor')::NUMERIC AND v->>'earnings_rounding'='HALF_EVEN'
 AND v->>'plan_digest'=reconforge.irp_digest((v-'plan_digest')||jsonb_build_object('private',calc)),'Payrun must exactly retain independent approved time, earned wages and project conservation');
 SELECT * INTO e FROM reconforge.finance_entries WHERE tenant_id=t AND id=p.entry_id;
 PERFORM reconforge.hc_assert(e.id IS NOT NULL AND e.entry_number=upper(p.id) AND e.preparer_actor_id=p.preparer_id
 AND e.workspace_id=p.workspace_id AND e.organization_code=v->>'organization_code' AND e.entity_code=v->>'entity_code'
 AND e.external_reference=p.id AND e.source_type='Manual' AND e.reverses_posting_id IS NULL
 AND e.period_id=v->>'period_id' AND e.posting_date=v->>'posting_date'
 AND (e.currency_code,e.currency_precision::text,e.currency_rounding_policy,e.currency_registry_version,e.currency_registry_digest)
  =(v#>>'{monetary_policy,currency_code}',v#>>'{monetary_policy,currency_precision}',v#>>'{monetary_policy,currency_rounding_policy}',v#>>'{monetary_policy,currency_registry_version}',v#>>'{monetary_policy,currency_registry_digest}'),'Payrun native header and captured policy must match original source');
 PERFORM reconforge.hc_assert(NOT EXISTS(SELECT 1 FROM reconforge.hc_time_claims c JOIN reconforge.hc_times tm ON tm.tenant_id=c.tenant_id AND tm.id=c.time_id
 JOIN reconforge.hc_employments ag ON ag.tenant_id=tm.tenant_id AND ag.id=tm.employment_id WHERE c.tenant_id=t AND c.payrun_id=pi
 AND (tm.approver_id IS NULL OR c.source_digest<>tm.source_digest OR (tm.workspace_id,tm.organization_id,tm.legal_entity_id)<>(p.workspace_id,p.organization_id,p.legal_entity_id)
 OR (ag.currency_code,ag.currency_precision::text,ag.currency_rounding_policy,ag.currency_registry_version,ag.currency_registry_digest)
  <>(e.currency_code,e.currency_precision::text,e.currency_rounding_policy,e.currency_registry_version,e.currency_registry_digest))),'Accrual cannot reinterpret original rate policy or detach whole-time source claims');
 SELECT * INTO b FROM reconforge.budget_envelopes WHERE tenant_id=t AND id=p.budget_id;
 PERFORM reconforge.hc_assert(b.id IS NOT NULL AND (b.workspace_id,b.organization_id,b.legal_entity_id)=(p.workspace_id,p.organization_id,p.legal_entity_id)
 AND b.period_id=e.period_id AND (b.currency_code,b.currency_precision,b.currency_rounding_policy,b.currency_registry_version,b.currency_registry_digest)
 =(e.currency_code,e.currency_precision,e.currency_rounding_policy,e.currency_registry_version,e.currency_registry_digest),
 'Payroll budget must retain canonical source scope/currency/period and captured monetary policy');
 PERFORM reconforge.hc_assert((SELECT count(*) FROM reconforge.budget_commitment_events WHERE tenant_id=t AND commitment_id=p.commitment_id AND operation='Reserve'
 AND source_reference=p.id AND amount_minor=p.amount_minor)=1,'Payrun needs exactly one native reserve event');
 PERFORM reconforge.hc_assert((SELECT count(*) FROM reconforge.budget_commitment_events WHERE tenant_id=t AND commitment_id=p.commitment_id AND operation='Consume')
 =CASE WHEN p.phase=2 THEN 1 ELSE 0 END AND (SELECT count(*) FROM reconforge.budget_commitment_events WHERE tenant_id=t AND commitment_id=p.commitment_id AND operation='Release')
 =CASE WHEN p.phase=3 THEN 1 ELSE 0 END,'Only posted accrual consumes, only unposted cancellation releases the original budget');
 PERFORM reconforge.hc_assert(NOT EXISTS(SELECT 1 FROM reconforge.budget_commitment_events WHERE tenant_id=t AND commitment_id=p.commitment_id
 AND (budget_id<>p.budget_id OR source_reference<>p.id OR amount_minor<>p.amount_minor OR operation_date<>e.posting_date
 OR actor_id<>CASE operation WHEN 'Reserve' THEN p.preparer_id WHEN 'Consume' THEN p.poster_id ELSE p.canceller_id END
 OR (operation='Reserve' AND remaining_minor<>p.amount_minor) OR (operation IN('Consume','Release') AND remaining_minor<>0))),
 'Payroll budget event amount original envelope actor date and source cannot diverge');
 expected:='[]'::jsonb;
 FOR project IN SELECT key,value FROM jsonb_each(v->'project_minor') ORDER BY key COLLATE "C" LOOP
  amount:=project.value::TEXT::NUMERIC;
  IF amount>0 THEN
   SELECT * INTO rate FROM reconforge.hc_projects WHERE tenant_id=t AND id=project.key;
   expected:=expected||jsonb_build_array(jsonb_build_object('account_code',v->>'expense_account_code','debit_minor',amount,'credit_minor',0,
    'dimensions',jsonb_build_object(rate.dimension_id,rate.value_id)));
  END IF;
 END LOOP;
 expected:=expected||jsonb_build_array(jsonb_build_object('account_code',v->>'liability_account_code','debit_minor',0,'credit_minor',p.amount_minor,'dimensions','{}'::jsonb));
 SELECT jsonb_agg(jsonb_build_object('account_code',a.account_code,'debit_minor',l.debit_minor,'credit_minor',l.credit_minor,
 'dimensions',COALESCE((SELECT jsonb_object_agg(d.dimension_id,d.dimension_value_id) FROM reconforge.finance_entry_line_dimensions d WHERE d.tenant_id=l.tenant_id AND d.entry_line_id=l.id),'{}'::jsonb)) ORDER BY l.line_number)
 INTO actual FROM reconforge.finance_entry_lines l JOIN reconforge.finance_accounts a ON a.tenant_id=l.tenant_id AND a.id=l.account_id WHERE l.tenant_id=t AND l.entry_id=p.entry_id;
 PERFORM reconforge.hc_assert(actual=expected,'Native wage lines and original Project dimensions must equal captured cumulative allocation');
 PERFORM reconforge.hc_phases(t,to_jsonb(p),FALSE);
 PERFORM reconforge.hc_assert((SELECT count(*) FROM reconforge.hc_time_claims WHERE tenant_id=t AND payrun_id=pi)=jsonb_array_length(v->'time_entry_ids')
 AND (SELECT count(*) FROM reconforge.hc_claim_heads WHERE tenant_id=t AND time_id IN(SELECT time_id FROM reconforge.hc_time_claims WHERE tenant_id=t AND payrun_id=pi))=jsonb_array_length(v->'time_entry_ids'),
 'Every whole-time source requires an original immutable claim and current head');
 IF p.phase IN(0,1) THEN
  PERFORM reconforge.hc_assert((SELECT status FROM reconforge.fiscal_periods WHERE tenant_id=t AND id=e.period_id)='Open','Pending payroll requires its open original period');
 END IF;
 PERFORM reconforge.hc_assert((SELECT count(*) FROM reconforge.finance_posting_effects WHERE tenant_id=t AND entry_id=p.entry_id)=CASE WHEN p.phase=2 THEN 1 ELSE 0 END,'Payroll phase and native GL effect must close atomically');
 IF p.phase=2 THEN PERFORM reconforge.hc_assert(p.poster_id<>p.preparer_id AND p.poster_id<>p.reviewer_id AND p.reviewer_id<>p.preparer_id
  AND EXISTS(SELECT 1 FROM reconforge.finance_posting_effects f WHERE f.tenant_id=t AND f.id=p.effect_id AND f.entry_id=p.entry_id
   AND f.posted_actor_id=p.poster_id AND f.validation_digest=v->>'validation_digest'),'Payroll needs its original native effect and three distinct financial humans');END IF;
 IF p.phase IN(1,2) THEN PERFORM reconforge.hc_assert(e.status='Validated' AND e.validator_actor_id=p.reviewer_id AND e.validation_digest=v->>'validation_digest','Payroll source review cannot detach from native reviewed digest');END IF;
 IF p.phase=0 THEN PERFORM reconforge.hc_assert(e.status='Draft' AND p.reviewer_id IS NULL AND p.poster_id IS NULL,'Prepared payroll requires its original draft');END IF;
 FOR rate IN SELECT c.*,h.payrun_id AS current_payrun,h.state FROM reconforge.hc_time_claims c JOIN reconforge.hc_claim_heads h ON h.tenant_id=c.tenant_id AND h.time_id=c.time_id
 WHERE c.tenant_id=t AND c.payrun_id=pi LOOP
  IF p.phase<>3 THEN PERFORM reconforge.hc_assert(rate.current_payrun=pi AND rate.state=CASE WHEN p.phase=2 THEN 'Consumed' ELSE 'Active' END,'Active or consumed whole-time claim must have exactly one source');
  ELSE PERFORM reconforge.hc_assert(EXISTS(SELECT 1 FROM reconforge.hc_claim_events z WHERE z.tenant_id=t AND z.time_id=rate.time_id AND z.payrun_id=pi AND z.operation='Release'),'Cancelled original claim history requires its retained release');END IF;
 END LOOP;
 FOR rate IN SELECT h.*,z.operation,z.payrun_id AS event_payrun,z.source_digest FROM reconforge.hc_claim_heads h
 JOIN reconforge.hc_claim_events z ON z.tenant_id=h.tenant_id AND z.time_id=h.time_id AND z.sequence=h.sequence
 WHERE h.tenant_id=t AND h.time_id IN(SELECT time_id FROM reconforge.hc_time_claims WHERE tenant_id=t AND payrun_id=pi) LOOP
  PERFORM reconforge.hc_assert(rate.event_payrun=rate.payrun_id AND rate.state=CASE rate.operation WHEN 'Claim' THEN 'Active' WHEN 'Release' THEN 'Released' ELSE 'Consumed' END
   AND rate.sequence=(SELECT max(sequence) FROM reconforge.hc_claim_events WHERE tenant_id=t AND time_id=rate.time_id),'Current claim head must equal latest append-only original event');
  PERFORM reconforge.hc_assert(rate.sequence=(SELECT count(*) FROM reconforge.hc_claim_events WHERE tenant_id=t AND time_id=rate.time_id)
   AND NOT EXISTS(SELECT 1 FROM reconforge.hc_claim_events z JOIN reconforge.hc_times tm ON tm.tenant_id=z.tenant_id AND tm.id=z.time_id
     WHERE z.tenant_id=t AND z.time_id=rate.time_id AND z.source_digest<>tm.source_digest),'Claim history must be contiguous and retain exact approved time');
 END LOOP;
 PERFORM reconforge.hc_assert(NOT EXISTS(SELECT 1 FROM reconforge.hc_time_claims c WHERE c.tenant_id=t AND c.payrun_id=pi AND
  (SELECT count(*) FROM reconforge.hc_claim_events z WHERE z.tenant_id=t AND z.time_id=c.time_id AND z.payrun_id=pi AND z.operation='Claim')<>1), 'Each original time/payrun claim has one append-only Claim');
 PERFORM reconforge.hc_assert(NOT EXISTS(SELECT 1 FROM reconforge.hc_claim_events z WHERE z.tenant_id=t AND z.payrun_id=pi AND
  (z.source_digest<>(SELECT source_digest FROM reconforge.hc_times WHERE tenant_id=t AND id=z.time_id)
   OR z.actor_id<>CASE z.operation WHEN 'Claim' THEN p.preparer_id WHEN 'Consume' THEN p.poster_id ELSE p.canceller_id END
   OR z.audit_id<>CASE z.operation WHEN 'Claim' THEN p.audit_id WHEN 'Consume' THEN p.post_audit_id ELSE p.cancel_audit_id END
   OR z.outbox_id<>CASE z.operation WHEN 'Claim' THEN p.outbox_id WHEN 'Consume' THEN p.post_outbox_id ELSE p.cancel_outbox_id END)),
  'Claim events retain exact financial phase actor and evidence');
 FOR rate IN SELECT * FROM reconforge.hc_payments WHERE tenant_id=t AND payrun_id=pi LOOP PERFORM reconforge.hc_payment_close(t,rate.id);END LOOP;
END $hc$;

CREATE FUNCTION reconforge.hc_payment_close(t TEXT,pi TEXT) RETURNS VOID LANGUAGE plpgsql SET search_path=pg_catalog AS $hc$
DECLARE p RECORD;source RECORD;e RECORD;priv JSONB;earned JSONB;item RECORD;due NUMERIC;paid NUMERIC;total NUMERIC;actual JSONB;v JSONB;
BEGIN
 SELECT * INTO p FROM reconforge.hc_payments WHERE tenant_id=t AND id=pi;PERFORM reconforge.hc_assert(p.id IS NOT NULL,'HC1P requires its retained original settlement owner');v:=p.payload;
 SELECT * INTO source FROM reconforge.hc_payruns WHERE tenant_id=t AND id=p.payrun_id;
 SELECT payload INTO priv FROM reconforge.hc_payment_private WHERE tenant_id=t AND plan_id=pi;
 SELECT payload INTO earned FROM reconforge.hc_payrun_private WHERE tenant_id=t AND plan_id=p.payrun_id;
 PERFORM reconforge.hc_assert(source.phase=2 AND jsonb_typeof(priv->'employees_minor')='object' AND (SELECT count(*) FROM jsonb_object_keys(priv->'employees_minor')) BETWEEN 1 AND 100
 AND v->>'plan_digest'=reconforge.irp_digest((v-'plan_digest')||jsonb_build_object('private',priv)),'Settlement must bind original posted liability and exact private allocations');
 total:=0;
 FOR item IN SELECT key,value FROM jsonb_each(priv->'employees_minor') LOOP
  PERFORM reconforge.hc_assert(item.value::text~'^[1-9][0-9]{0,18}$','Employee settlement requires positive exact minor units');
  SELECT (value->>'gross_minor')::NUMERIC INTO due FROM jsonb_array_elements(earned->'employees') WHERE value->>'employee_id'=item.key;
  SELECT COALESCE(sum((d.payload#>>ARRAY['employees_minor',item.key])::NUMERIC),0) INTO paid FROM reconforge.hc_payments other
   JOIN reconforge.hc_payment_private d ON d.tenant_id=other.tenant_id AND d.plan_id=other.id WHERE other.tenant_id=t AND other.payrun_id=p.payrun_id AND other.phase=2;
  PERFORM reconforge.hc_assert(due IS NOT NULL AND CASE WHEN p.phase=2 THEN paid<=due ELSE paid+item.value::text::NUMERIC<=due END,'Native settlement cannot overpay original employee liability');
  total:=total+item.value::text::NUMERIC;
 END LOOP;
 PERFORM reconforge.hc_assert(total=p.amount_minor AND total=(priv->>'amount_minor')::NUMERIC,'Settlement allocation must conserve native total');
 SELECT * INTO e FROM reconforge.finance_entries WHERE tenant_id=t AND id=p.entry_id;
 PERFORM reconforge.hc_assert(e.id IS NOT NULL AND e.entry_number=upper(p.id) AND e.preparer_actor_id=p.preparer_id AND e.workspace_id=p.workspace_id
 AND e.period_id=v->>'period_id' AND e.posting_date=v->>'posting_date','Settlement native header must retain exact original ownership');
 PERFORM reconforge.hc_assert((e.organization_code,e.entity_code)=(source.payload->>'organization_code',source.payload->>'entity_code') AND e.external_reference=p.id
 AND e.source_type='Manual' AND e.reverses_posting_id IS NULL AND e.journal_id=(SELECT journal_id FROM reconforge.finance_entries WHERE tenant_id=t AND id=source.entry_id)
 AND (e.currency_code,e.currency_precision::text,e.currency_rounding_policy,e.currency_registry_version,e.currency_registry_digest)
 =(source.payload#>>'{monetary_policy,currency_code}',source.payload#>>'{monetary_policy,currency_precision}',source.payload#>>'{monetary_policy,currency_rounding_policy}',
 source.payload#>>'{monetary_policy,currency_registry_version}',source.payload#>>'{monetary_policy,currency_registry_digest}'),'Settlement retains original currency and native source scope');
 SELECT jsonb_agg(jsonb_build_object('account_code',a.account_code,'debit_minor',l.debit_minor,'credit_minor',l.credit_minor) ORDER BY l.line_number)
 INTO actual FROM reconforge.finance_entry_lines l JOIN reconforge.finance_accounts a ON a.tenant_id=l.tenant_id AND a.id=l.account_id WHERE l.tenant_id=t AND l.entry_id=p.entry_id;
 PERFORM reconforge.hc_assert(actual=jsonb_build_array(jsonb_build_object('account_code',source.payload->>'liability_account_code','debit_minor',p.amount_minor,'credit_minor',0),
 jsonb_build_object('account_code',source.payload->>'cash_account_code','debit_minor',0,'credit_minor',p.amount_minor)),'Settlement must reduce original payroll liability and record native cash only');
 PERFORM reconforge.hc_assert(NOT EXISTS(SELECT 1 FROM reconforge.finance_entry_line_dimensions d JOIN reconforge.finance_entry_lines l
 ON l.tenant_id=d.tenant_id AND l.id=d.entry_line_id WHERE l.tenant_id=t AND l.entry_id=p.entry_id),'Cash settlement cannot create new project allocations');
 PERFORM reconforge.hc_phases(t,to_jsonb(p),TRUE);
 PERFORM reconforge.hc_assert((SELECT count(*) FROM reconforge.finance_posting_effects WHERE tenant_id=t AND entry_id=p.entry_id)=CASE WHEN p.phase=2 THEN 1 ELSE 0 END,'Settlement phase cannot detach from native effect');
 IF p.phase=2 THEN PERFORM reconforge.hc_assert(p.poster_id<>p.preparer_id AND p.poster_id<>p.reviewer_id AND p.preparer_id<>p.reviewer_id
 AND EXISTS(SELECT 1 FROM reconforge.finance_posting_effects WHERE tenant_id=t AND id=p.effect_id AND entry_id=p.entry_id AND posted_actor_id=p.poster_id
 AND validation_digest=v->>'validation_digest'),'Settlement requires its own original effect and financial SoD');END IF;
 IF p.phase=0 THEN PERFORM reconforge.hc_assert(e.status='Draft','Prepared settlement requires native draft');
 ELSE PERFORM reconforge.hc_assert(e.status='Validated' AND e.validator_actor_id=p.reviewer_id AND e.validation_digest=v->>'validation_digest','Settlement needs original reviewed content');END IF;
END $hc$;

CREATE FUNCTION reconforge.hc_audit(t TEXT,pi TEXT,actor TEXT,event_action TEXT,digest TEXT,aid TEXT,oid TEXT,w TEXT,o TEXT,e TEXT)
 RETURNS VOID LANGUAGE plpgsql SET search_path=pg_catalog AS $hc$
BEGIN
 PERFORM reconforge.hc_assert(EXISTS(SELECT 1 FROM reconforge.domain_audit_events WHERE tenant_id=t AND id=aid
 AND actor_user_id=actor AND object_type='operational_finance' AND object_id=pi AND domain_audit_events.action='people_'||event_action
 AND metadata_json::jsonb=jsonb_build_object('source_digest',digest)), 'Workforce audit must retain exact source digest and actor without private fields');
 PERFORM reconforge.hc_assert(EXISTS(SELECT 1 FROM reconforge.outbox_events WHERE tenant_id=t AND event_id=oid AND aggregate_type='operational_finance'
 AND aggregate_id=pi AND event_type='people_'||event_action AND (workspace_id,organization_id,legal_entity_id)=(w,o,e)
 AND payload=jsonb_build_object('source_digest',digest,'audit_event_id',aid)), 'Workforce outbox must retain original scoped audit relation');
END $hc$;
CREATE FUNCTION reconforge.hc_phases(t TEXT,p JSONB,payment BOOLEAN) RETURNS VOID LANGUAGE plpgsql SET search_path=pg_catalog AS $hc$
DECLARE phase INTEGER:=(p->>'phase')::INTEGER;v JSONB:=p->'payload';action TEXT;actor TEXT;aid TEXT;oid TEXT;op TEXT;cmd RECORD;
BEGIN
 PERFORM reconforge.hc_assert((p->>'id',p->>'workspace_id',p->>'organization_id',p->>'legal_entity_id',p->>'entry_id',p->>'amount_minor',p->>'preparer_id')
 =(v->>'id',v->>'workspace_id',v->>'organization_id',v->>'legal_entity_id',v->>'entry_id',v->>'amount_minor',v->>'preparer_id'), 'Public workforce source cannot detach from canonical native ownership');
 FOR op,action,actor,aid,oid IN SELECT * FROM (VALUES
 (CASE WHEN payment THEN 'pay' ELSE 'prepare' END,CASE WHEN payment THEN 'payment_prepared' ELSE 'payrun_prepared' END,p->>'preparer_id',p->>'audit_id',p->>'outbox_id'),
 ('review','plan_reviewed',p->>'reviewer_id',p->>'review_audit_id',p->>'review_outbox_id'),
 ('post','plan_posted',p->>'poster_id',p->>'post_audit_id',p->>'post_outbox_id'),
 ('cancel','payrun_cancelled',p->>'canceller_id',p->>'cancel_audit_id',p->>'cancel_outbox_id')) AS phases(op,act,person,a,b) LOOP
  IF op IN('prepare','pay') OR(op='review' AND (phase IN(1,2) OR (phase=3 AND p->>'reviewer_id' IS NOT NULL)))
   OR(op='post' AND phase=2) OR(op='cancel' AND phase=3) THEN
   PERFORM reconforge.hc_assert(actor IS NOT NULL AND aid IS NOT NULL AND oid IS NOT NULL,'Completed workforce phase requires immutable original actor and evidence');
   PERFORM reconforge.hc_audit(t,p->>'id',actor,action,v->>'plan_digest',aid,oid,p->>'workspace_id',p->>'organization_id',p->>'legal_entity_id');
   PERFORM reconforge.hc_assert((SELECT count(*) FROM reconforge.hc_commands c WHERE c.tenant_id=t AND c.workspace_id=p->>'workspace_id'
    AND c.operation=op AND c.actor_id=actor AND c.response_json->>'id'=p->>'id'
    AND c.response_json->>'plan_digest'=v->>'plan_digest'
    AND (op IN('prepare','pay') OR c.request_json->>'expected_plan_digest'=v->>'plan_digest'))=1,
    'Completed workforce phase requires one exact immutable command acknowledgement');
   FOR cmd IN SELECT * FROM reconforge.hc_commands c WHERE c.tenant_id=t AND c.workspace_id=p->>'workspace_id'
    AND c.operation=op AND c.response_json->>'id'=p->>'id' LOOP
    PERFORM reconforge.hc_assert((cmd.response_json-ARRAY['phase','status','reviewer_id','posted_actor_id','posting_effect_id'])=v
     AND (cmd.organization_id,cmd.legal_entity_id)=(p->>'organization_id',p->>'legal_entity_id')
     AND cmd.response_json->>'phase'=CASE op WHEN 'prepare' THEN '0' WHEN 'pay' THEN '0' WHEN 'review' THEN '1' WHEN 'post' THEN '2' ELSE '3' END
     AND cmd.response_json->>'status'=CASE op WHEN 'prepare' THEN 'Prepared' WHEN 'pay' THEN 'Prepared' WHEN 'review' THEN 'Reviewed' WHEN 'post' THEN 'Posted' ELSE 'Cancelled' END,
     'Immutable financial acknowledgement must retain complete original payload scope and phase');
    IF op='prepare' THEN PERFORM reconforge.hc_assert(cmd.request_json=v->'command_request','Accrual request cannot detach from original source');
    ELSIF op IN('review','post','cancel') THEN PERFORM reconforge.hc_assert(COALESCE(cmd.request_json->>'plan_id',cmd.request_json->>'payrun_id')=p->>'id','Phase command retains its original source');END IF;
   END LOOP;
  ELSE PERFORM reconforge.hc_assert(actor IS NULL AND aid IS NULL AND oid IS NULL,'Unperformed phase cannot retain fabricated actor or evidence');END IF;
 END LOOP;
 IF phase IN(0,1,3) THEN PERFORM reconforge.hc_assert(p->>'effect_id' IS NULL,'Unposted workforce cannot retain a native effect');END IF;
 IF phase=2 THEN PERFORM reconforge.hc_assert(p->>'preparer_id'<>p->>'reviewer_id' AND p->>'reviewer_id'<>p->>'poster_id'
 AND p->>'preparer_id'<>p->>'poster_id','Three distinct financial humans are required');END IF;
END $hc$;

CREATE FUNCTION reconforge.hc_input_close(t TEXT,table_name TEXT,identifier TEXT) RETURNS VOID LANGUAGE plpgsql SET search_path=pg_catalog AS $hc$
DECLARE p RECORD;priv RECORD;cmd RECORD;request JSONB;op TEXT;action TEXT;digest TEXT;actor TEXT;
BEGIN
 IF table_name='hc_employees' THEN
  SELECT * INTO p FROM reconforge.hc_employees WHERE tenant_id=t AND id=identifier;
  SELECT * INTO priv FROM reconforge.hc_employee_private WHERE tenant_id=t AND employee_id=identifier;
  op:='personnel';action:='employee_registered';actor:=p.preparer_id;
  PERFORM reconforge.hc_assert(priv.employee_id IS NOT NULL AND (priv.workspace_id,priv.organization_id,priv.legal_entity_id)=(p.workspace_id,p.organization_id,p.legal_entity_id),'Employee requires original private name in canonical scope');
 ELSIF table_name='hc_employments' THEN
  SELECT * INTO p FROM reconforge.hc_employments WHERE tenant_id=t AND id=identifier;
  SELECT * INTO priv FROM reconforge.hc_rates WHERE tenant_id=t AND employment_id=identifier;
  op:='personnel';action:='employment_registered';actor:=p.preparer_id;
  PERFORM reconforge.hc_assert(priv.employment_id IS NOT NULL AND (priv.workspace_id,priv.organization_id,priv.legal_entity_id)=(p.workspace_id,p.organization_id,p.legal_entity_id),'Effective employment requires its original private exact rate');
 ELSIF table_name='hc_projects' THEN
  SELECT * INTO p FROM reconforge.hc_projects WHERE tenant_id=t AND id=identifier;
  op:='manage';action:='project_registered';actor:=p.preparer_id;
  PERFORM reconforge.hc_assert(EXISTS(SELECT 1 FROM reconforge.finance_dimensions d JOIN reconforge.finance_dimension_values val
   ON val.tenant_id=d.tenant_id AND val.dimension_id=d.id WHERE d.tenant_id=t AND d.id=p.dimension_id AND val.id=p.value_id
   AND d.workspace_id=p.workspace_id AND d.active AND val.active AND d.dimension_type='Project' AND d.dimension_code=p.dimension_code AND val.value_code=p.value_code),
   'Registered workforce Project retains its active native dimension and value');
 ELSIF table_name='hc_times' THEN
  SELECT * INTO p FROM reconforge.hc_times WHERE tenant_id=t AND id=identifier;
  op:='manage';action:='time_submitted';actor:=p.submitter_id;
 ELSE PERFORM reconforge.hc_assert(FALSE,'Unknown workforce input source');END IF;
 PERFORM reconforge.hc_assert(p.id IS NOT NULL,'Workforce input cannot detach from original parent');
 SELECT * INTO cmd FROM reconforge.hc_commands c WHERE c.tenant_id=t AND c.workspace_id=p.workspace_id AND c.operation=op AND c.response_json->>'id'=identifier;
 PERFORM reconforge.hc_assert(cmd.command_id IS NOT NULL AND cmd.actor_id=actor
 AND (cmd.organization_id,cmd.legal_entity_id)=(p.organization_id,p.legal_entity_id)
 AND (SELECT count(*) FROM reconforge.hc_commands c WHERE c.tenant_id=t AND c.workspace_id=p.workspace_id AND c.operation=op AND c.response_json->>'id'=identifier)=1,
 'Workforce input requires one original scoped command acknowledgement');
 request:=cmd.request_json;digest:=cmd.request_digest;
 IF table_name='hc_employees' THEN
  PERFORM reconforge.hc_assert(request->>'employee_code'=p.employee_code AND request->>'display_name'=priv.display_name
   AND (request->>'linked_user_id') IS NOT DISTINCT FROM p.linked_user_id,'Employee name and linked identity cannot detach from request');
 ELSIF table_name='hc_employments' THEN
  PERFORM reconforge.hc_assert(request->>'employee_id'=p.employee_id AND request->>'valid_from'=p.valid_from::text AND request->>'valid_through'=p.valid_through::text
   AND request->>'hourly_rate_minor'=priv.hourly_rate_minor::text AND request->>'currency_code'=p.currency_code AND digest=p.request_digest,'Original effective rate must match retained private agreement');
 ELSIF table_name='hc_projects' THEN
  PERFORM reconforge.hc_assert(request->>'project_code'=p.project_code AND request->>'dimension_code'=p.dimension_code AND request->>'value_code'=p.value_code
   AND digest=p.request_digest,'Project command retains exact original dimension');
 ELSE
  PERFORM reconforge.hc_assert(request=p.request_json,'Time source must equal retained original interval request');
  PERFORM reconforge.hc_audit(t,identifier,actor,action,digest,p.submit_audit_id,p.submit_outbox_id,p.workspace_id,p.organization_id,p.legal_entity_id);
  IF p.approver_id IS NOT NULL THEN
   SELECT * INTO cmd FROM reconforge.hc_commands c WHERE c.tenant_id=t AND c.operation='approve_time' AND c.response_json->>'id'=identifier;
   PERFORM reconforge.hc_assert(cmd.actor_id=p.approver_id AND cmd.request_json->>'expected_digest'=p.source_digest
    AND (SELECT count(*) FROM reconforge.hc_commands c WHERE c.tenant_id=t AND c.operation='approve_time' AND c.response_json->>'id'=identifier)=1,'Approved time requires one original independent acknowledgement');
   PERFORM reconforge.hc_audit(t,identifier,p.approver_id,'time_approved',cmd.request_digest,p.audit_id,p.outbox_id,p.workspace_id,p.organization_id,p.legal_entity_id);
  ELSE PERFORM reconforge.hc_assert(p.audit_id IS NULL AND p.outbox_id IS NULL,'Unapproved time has no approval evidence');END IF;
  RETURN;
 END IF;
 PERFORM reconforge.hc_audit(t,identifier,actor,action,digest,p.audit_id,p.outbox_id,p.workspace_id,p.organization_id,p.legal_entity_id);
END $hc$;

CREATE FUNCTION reconforge.hc_reverse_close() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $hc$
DECLARE changes JSONB[];changed JSONB;native_id TEXT;native_number TEXT;owner_id TEXT;source_id TEXT;p RECORD;
BEGIN
 -- Delivery leasing/acknowledgement changes do not reinterpret the immutable
 -- source event. An ordinary worker must not acquire personnel credentials.
 IF TG_OP='UPDATE' AND TG_TABLE_NAME='outbox_events' THEN
  IF (to_jsonb(NEW)->'tenant_id',to_jsonb(NEW)->'event_id',to_jsonb(NEW)->'event_type',to_jsonb(NEW)->'aggregate_type',
   to_jsonb(NEW)->'aggregate_id',to_jsonb(NEW)->'workspace_id',to_jsonb(NEW)->'organization_id',to_jsonb(NEW)->'legal_entity_id',to_jsonb(NEW)->'payload',to_jsonb(NEW)->'created_at')
   IS NOT DISTINCT FROM (to_jsonb(OLD)->'tenant_id',to_jsonb(OLD)->'event_id',to_jsonb(OLD)->'event_type',to_jsonb(OLD)->'aggregate_type',
   to_jsonb(OLD)->'aggregate_id',to_jsonb(OLD)->'workspace_id',to_jsonb(OLD)->'organization_id',to_jsonb(OLD)->'legal_entity_id',to_jsonb(OLD)->'payload',to_jsonb(OLD)->'created_at')
   THEN RETURN NULL;END IF;
 END IF;
 IF TG_OP='INSERT' THEN changes:=ARRAY[to_jsonb(NEW)];ELSIF TG_OP='DELETE' THEN changes:=ARRAY[to_jsonb(OLD)];
 ELSIF TG_OP='UPDATE' THEN changes:=ARRAY[to_jsonb(OLD),to_jsonb(NEW)];ELSE PERFORM reconforge.hc_assert(FALSE,'Unsupported workforce closure operation');END IF;
 FOREACH changed IN ARRAY changes LOOP
  native_id:=NULL;native_number:=NULL;source_id:=NULL;
  IF TG_TABLE_NAME IN('finance_dimensions','finance_dimension_values') THEN
   FOR p IN SELECT id FROM reconforge.hc_projects WHERE tenant_id=changed->>'tenant_id'
    AND CASE TG_TABLE_NAME WHEN 'finance_dimensions' THEN dimension_id=changed->>'id' ELSE value_id=changed->>'id' END
    LOOP PERFORM reconforge.hc_input_close(changed->>'tenant_id','hc_projects',p.id);END LOOP;
  END IF;
  IF TG_TABLE_NAME IN('hc_employees','hc_employee_private','hc_employments','hc_rates','hc_projects','hc_times') THEN
   PERFORM reconforge.hc_input_close(changed->>'tenant_id',CASE TG_TABLE_NAME WHEN 'hc_employee_private' THEN 'hc_employees' WHEN 'hc_rates' THEN 'hc_employments' ELSE TG_TABLE_NAME END,
    CASE TG_TABLE_NAME WHEN 'hc_employee_private' THEN changed->>'employee_id' WHEN 'hc_rates' THEN changed->>'employment_id' ELSE changed->>'id' END);
   IF TG_TABLE_NAME IN('hc_times','hc_rates','hc_employments') THEN
    FOR p IN SELECT DISTINCT c.payrun_id FROM reconforge.hc_time_claims c JOIN reconforge.hc_times tm ON tm.tenant_id=c.tenant_id AND tm.id=c.time_id
     WHERE c.tenant_id=changed->>'tenant_id' AND CASE TG_TABLE_NAME WHEN 'hc_times' THEN tm.id=changed->>'id' ELSE tm.employment_id=COALESCE(changed->>'employment_id',changed->>'id') END
     LOOP PERFORM reconforge.hc_close(changed->>'tenant_id',p.payrun_id);END LOOP;
   END IF;
  ELSIF TG_TABLE_NAME='hc_commands' THEN
   owner_id:=changed#>>'{response_json,id}';
   IF owner_id LIKE 'HC1-%' THEN source_id:=owner_id;
   ELSIF owner_id LIKE 'HC1P-%' THEN SELECT payrun_id INTO source_id FROM reconforge.hc_payments WHERE tenant_id=changed->>'tenant_id' AND id=owner_id;
   ELSE PERFORM reconforge.hc_input_close(changed->>'tenant_id',CASE WHEN owner_id LIKE 'HCE-%' THEN 'hc_employees'
    WHEN owner_id LIKE 'HCA-%' THEN 'hc_employments' WHEN owner_id LIKE 'HCP-%' THEN 'hc_projects' ELSE 'hc_times' END,owner_id);END IF;
  END IF;
  IF TG_TABLE_NAME IN('finance_entries','finance_entry_lines','finance_entry_line_dimensions','finance_posting_effects') THEN
   native_id:=CASE WHEN TG_TABLE_NAME='finance_entries' THEN changed->>'id' ELSE changed->>'entry_id' END;
   IF TG_TABLE_NAME='finance_entry_line_dimensions' THEN SELECT entry_id INTO native_id FROM reconforge.finance_entry_lines WHERE tenant_id=changed->>'tenant_id' AND id=changed->>'entry_line_id';END IF;
   IF (TG_TABLE_NAME='finance_posting_effects' AND changed->>'reverses_effect_id' IS NOT NULL) OR(TG_TABLE_NAME='finance_entries' AND changed->>'reverses_posting_id' IS NOT NULL) THEN
    SELECT e.entry_number INTO native_number FROM reconforge.finance_posting_effects f JOIN reconforge.finance_entries e ON e.tenant_id=f.tenant_id AND e.id=f.entry_id
     WHERE f.tenant_id=changed->>'tenant_id' AND f.id=COALESCE(changed->>'reverses_effect_id',changed->>'reverses_posting_id');
    PERFORM reconforge.hc_assert(COALESCE(native_number,'') NOT LIKE 'HC1-%' AND COALESCE(native_number,'') NOT LIKE 'HC1P-%','Consumed workforce effects cannot reverse outside a future source-owned correction contract');
   END IF;
   SELECT entry_number INTO native_number FROM reconforge.finance_entries WHERE tenant_id=changed->>'tenant_id' AND id=native_id;
   IF TG_TABLE_NAME='finance_entries' THEN native_number:=changed->>'entry_number';END IF;
   IF upper(COALESCE(native_number,'')) LIKE 'HC1-%' OR upper(COALESCE(native_id,'')) LIKE 'HC1-%' THEN
    SELECT id INTO source_id FROM reconforge.hc_payruns WHERE tenant_id=changed->>'tenant_id' AND entry_id=native_id;
    PERFORM reconforge.hc_assert(source_id IS NOT NULL,'Reserved HC1 native entry cannot detach from its source');
   ELSIF upper(COALESCE(native_number,'')) LIKE 'HC1P-%' OR upper(COALESCE(native_id,'')) LIKE 'HC1P-%' THEN
    SELECT payrun_id INTO source_id FROM reconforge.hc_payments WHERE tenant_id=changed->>'tenant_id' AND entry_id=native_id;
    PERFORM reconforge.hc_assert(source_id IS NOT NULL,'Reserved HC1P settlement cannot detach from its original accrual');
   END IF;
  ELSIF TG_TABLE_NAME IN('hc_payruns','hc_payrun_private') THEN source_id:=COALESCE(changed->>'plan_id',changed->>'id');
  ELSIF TG_TABLE_NAME IN('hc_payments','hc_payment_private') THEN
   SELECT payrun_id INTO source_id FROM reconforge.hc_payments WHERE tenant_id=changed->>'tenant_id' AND id=COALESCE(changed->>'plan_id',changed->>'id');
  ELSIF TG_TABLE_NAME IN('hc_time_claims','hc_claim_events','hc_claim_heads') THEN source_id:=changed->>'payrun_id';
  ELSIF TG_TABLE_NAME='budget_commitment_events' THEN
   owner_id:=changed->>'source_reference';IF upper(COALESCE(owner_id,'')) LIKE 'HC1-%' THEN source_id:=owner_id;END IF;
  ELSIF TG_TABLE_NAME IN('domain_audit_events','outbox_events') THEN
   owner_id:=CASE WHEN TG_TABLE_NAME='domain_audit_events' THEN changed->>'object_id' ELSE changed->>'aggregate_id' END;
   IF upper(COALESCE(owner_id,'')) LIKE 'HC1-%' THEN source_id:=owner_id;
   ELSIF upper(COALESCE(owner_id,'')) LIKE 'HC1P-%' THEN SELECT payrun_id INTO source_id FROM reconforge.hc_payments WHERE tenant_id=changed->>'tenant_id' AND id=owner_id;END IF;
  END IF;
  IF source_id IS NOT NULL THEN PERFORM reconforge.hc_close(changed->>'tenant_id',source_id);END IF;
 END LOOP;RETURN NULL;
END $hc$;
DO $hc$ DECLARE n TEXT; BEGIN
 FOREACH n IN ARRAY ARRAY['hc_employees','hc_employee_private','hc_employments','hc_rates','hc_projects','hc_times','hc_payruns','hc_payrun_private',
 'hc_payments','hc_payment_private','hc_time_claims','hc_claim_events','hc_claim_heads','hc_commands'] LOOP
  EXECUTE format('ALTER TABLE reconforge.%I ENABLE ROW LEVEL SECURITY',n);EXECUTE format('ALTER TABLE reconforge.%I FORCE ROW LEVEL SECURITY',n);
  IF n IN('hc_time_claims','hc_claim_events','hc_claim_heads') THEN
   EXECUTE format('CREATE POLICY scope ON reconforge.%I USING(EXISTS(SELECT 1 FROM reconforge.hc_times t WHERE t.tenant_id=%I.tenant_id AND t.id=%I.time_id)) WITH CHECK(EXISTS(SELECT 1 FROM reconforge.hc_times t WHERE t.tenant_id=%I.tenant_id AND t.id=%I.time_id))',n,n,n,n,n);
  ELSE EXECUTE format('CREATE POLICY scope ON reconforge.%I USING(reconforge.irp_scope(tenant_id,workspace_id,organization_id,legal_entity_id)) WITH CHECK(reconforge.irp_scope(tenant_id,workspace_id,organization_id,legal_entity_id))',n);END IF;
  IF n IN('hc_employee_private','hc_rates','hc_payrun_private','hc_payment_private') THEN
   EXECUTE format('CREATE POLICY private_role ON reconforge.%I AS RESTRICTIVE USING(reconforge.hc_private()) WITH CHECK(reconforge.hc_private())',n);
  ELSIF n='hc_commands' THEN
   EXECUTE format('CREATE POLICY private_role ON reconforge.%I AS RESTRICTIVE USING(operation IN(''manage'',''approve_time'') OR reconforge.hc_private()) WITH CHECK(operation IN(''manage'',''approve_time'') OR reconforge.hc_private())',n);
  END IF;
  EXECUTE format('CREATE TRIGGER immutable BEFORE UPDATE OR DELETE ON reconforge.%I FOR EACH ROW EXECUTE FUNCTION reconforge.hc_guard_immutable()',n);
 END LOOP;
 FOREACH n IN ARRAY ARRAY['hc_employees','hc_employee_private','hc_employments','hc_rates','hc_projects','hc_times','hc_commands',
 'hc_payruns','hc_payrun_private','hc_payments','hc_payment_private','hc_time_claims','hc_claim_events','hc_claim_heads',
 'finance_dimensions','finance_dimension_values','finance_entries','finance_entry_lines','finance_entry_line_dimensions','finance_posting_effects','budget_commitment_events','domain_audit_events','outbox_events'] LOOP
  EXECUTE format('CREATE CONSTRAINT TRIGGER hc_source_close AFTER INSERT OR UPDATE OR DELETE ON reconforge.%I DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION reconforge.hc_reverse_close()',n);
 END LOOP;
END $hc$;
"""

DOWNGRADE_SQL = r"""
DO $hc$ BEGIN
 IF EXISTS(SELECT 1 FROM reconforge.hc_employees) OR EXISTS(SELECT 1 FROM reconforge.hc_payruns) OR EXISTS(SELECT 1 FROM reconforge.hc_projects)
 THEN RAISE EXCEPTION 'Populated workforce/payroll history requires restore; destructive downgrade refused';END IF;
END $hc$;
DROP TRIGGER IF EXISTS hc_source_close ON reconforge.finance_entries;
DROP TRIGGER IF EXISTS hc_source_close ON reconforge.finance_dimensions;
DROP TRIGGER IF EXISTS hc_source_close ON reconforge.finance_dimension_values;
DROP TRIGGER IF EXISTS hc_source_close ON reconforge.finance_entry_lines;
DROP TRIGGER IF EXISTS hc_source_close ON reconforge.finance_entry_line_dimensions;
DROP TRIGGER IF EXISTS hc_source_close ON reconforge.finance_posting_effects;
DROP TRIGGER IF EXISTS hc_source_close ON reconforge.budget_commitment_events;
DROP TRIGGER IF EXISTS hc_source_close ON reconforge.domain_audit_events;
DROP TRIGGER IF EXISTS hc_source_close ON reconforge.outbox_events;
DROP TABLE reconforge.hc_commands,reconforge.hc_claim_heads,reconforge.hc_claim_events,reconforge.hc_time_claims,
 reconforge.hc_payment_private,reconforge.hc_payments,reconforge.hc_payrun_private,reconforge.hc_payruns,reconforge.hc_times,
 reconforge.hc_projects,reconforge.hc_rates,reconforge.hc_employments,reconforge.hc_employee_private,reconforge.hc_employees;
DROP FUNCTION reconforge.hc_reverse_close(),reconforge.hc_payment_close(TEXT,TEXT),reconforge.hc_close(TEXT,TEXT),reconforge.hc_calculate(TEXT,TEXT),
 reconforge.hc_input_close(TEXT,TEXT,TEXT),reconforge.hc_phases(TEXT,JSONB,BOOLEAN),reconforge.hc_audit(TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT),
 reconforge.hc_claim(TEXT,TEXT,TEXT,TEXT,TEXT),reconforge.hc_source_guard(),reconforge.hc_guard_immutable(),reconforge.hc_even(NUMERIC,NUMERIC),
 reconforge.hc_actor(TEXT,TEXT,TEXT,TEXT,TEXT,TEXT),reconforge.hc_private(),reconforge.hc_assert(BOOLEAN,TEXT);
-- The fixed NOLOGIN role may be operator-owned; preserve it and explicit memberships.
"""


def upgrade_people_project_payroll_schema(connection: object) -> None:
    connection.execute(UPGRADE_SQL)  # type: ignore[attr-defined]


def downgrade_people_project_payroll_schema(connection: object) -> None:
    connection.execute(DOWNGRADE_SQL)  # type: ignore[attr-defined]
