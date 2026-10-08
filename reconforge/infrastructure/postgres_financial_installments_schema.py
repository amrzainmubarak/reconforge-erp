"""Additive, forced-RLS installment source ownership over native AP and GL."""

UPGRADE_SQL = r"""
DO $fi$ BEGIN
 IF EXISTS(SELECT 1 FROM reconforge.finance_entries WHERE upper(entry_number) LIKE 'FI1-%') THEN
  RAISE EXCEPTION 'FI1 namespace already contains incompatible native entries';
 END IF;
END $fi$;
CREATE TABLE reconforge.financial_installment_plans (
 tenant_id TEXT NOT NULL,id TEXT NOT NULL,workspace_id TEXT NOT NULL,organization_id TEXT NOT NULL,legal_entity_id TEXT NOT NULL,
 source_id TEXT NOT NULL,entry_id TEXT NOT NULL,amount_minor BIGINT NOT NULL CHECK(amount_minor BETWEEN 1 AND 9000000000000000000),
 phase INTEGER NOT NULL CHECK(phase BETWEEN 0 AND 2),payload JSONB NOT NULL,audit_event_id TEXT NOT NULL,outbox_event_id TEXT NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(),PRIMARY KEY(tenant_id,id),UNIQUE(tenant_id,entry_id),
 FOREIGN KEY(tenant_id,source_id) REFERENCES reconforge.ap_supplier_invoices(tenant_id,id),
 FOREIGN KEY(tenant_id,entry_id) REFERENCES reconforge.finance_entries(tenant_id,id)
);
CREATE UNIQUE INDEX financial_installment_pending ON reconforge.financial_installment_plans(tenant_id,source_id) WHERE phase<2;
CREATE TABLE reconforge.financial_installment_reviews (
 tenant_id TEXT NOT NULL,plan_id TEXT NOT NULL,reviewer_actor_id TEXT NOT NULL,reason TEXT NOT NULL,audit_event_id TEXT NOT NULL,
 outbox_event_id TEXT NOT NULL,PRIMARY KEY(tenant_id,plan_id),FOREIGN KEY(tenant_id,plan_id) REFERENCES reconforge.financial_installment_plans(tenant_id,id)
);
CREATE TABLE reconforge.financial_installment_links (
 tenant_id TEXT NOT NULL,plan_id TEXT NOT NULL,posting_effect_id TEXT NOT NULL,payment_link_id TEXT NOT NULL,posted_actor_id TEXT NOT NULL,
 reason TEXT NOT NULL,audit_event_id TEXT NOT NULL,outbox_event_id TEXT NOT NULL,PRIMARY KEY(tenant_id,plan_id),
 UNIQUE(tenant_id,posting_effect_id),UNIQUE(tenant_id,payment_link_id),
 FOREIGN KEY(tenant_id,plan_id) REFERENCES reconforge.financial_installment_plans(tenant_id,id),
 FOREIGN KEY(tenant_id,posting_effect_id) REFERENCES reconforge.finance_posting_effects(tenant_id,id),
 FOREIGN KEY(tenant_id,payment_link_id) REFERENCES reconforge.ap_payment_links(tenant_id,id)
);
CREATE TABLE reconforge.financial_installment_commands (
 tenant_id TEXT NOT NULL,workspace_id TEXT NOT NULL,organization_id TEXT NOT NULL,legal_entity_id TEXT NOT NULL,
 plan_id TEXT NOT NULL,operation TEXT NOT NULL CHECK(operation IN ('prepare','review','post')),command_id TEXT NOT NULL,
 actor_id TEXT NOT NULL,request_digest TEXT NOT NULL,request_json JSONB NOT NULL,response_json JSONB NOT NULL,
 PRIMARY KEY(tenant_id,workspace_id,command_id),UNIQUE(tenant_id,plan_id,operation),
 FOREIGN KEY(tenant_id,plan_id) REFERENCES reconforge.financial_installment_plans(tenant_id,id)
);
CREATE FUNCTION reconforge.installment_protect() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $fi$
BEGIN
 IF TG_TABLE_NAME='financial_installment_plans' AND TG_OP='UPDATE' AND NEW.phase=OLD.phase+1
 AND (to_jsonb(NEW)-'phase')=(to_jsonb(OLD)-'phase') THEN RETURN NEW; END IF;
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='financial_installment_owner_phase',MESSAGE='Retained installment evidence is immutable';
END $fi$;
CREATE FUNCTION reconforge.installment_event(t TEXT,p TEXT,a TEXT,b TEXT,actor TEXT,action TEXT,metadata JSONB) RETURNS BOOLEAN
 LANGUAGE sql STABLE SET search_path=pg_catalog AS $fi$
 SELECT EXISTS(SELECT 1 FROM reconforge.domain_audit_events x JOIN reconforge.outbox_events y ON y.tenant_id=x.tenant_id
 JOIN reconforge.financial_installment_plans z ON z.tenant_id=x.tenant_id AND z.id=p
 WHERE x.tenant_id=t AND x.id=a AND y.event_id=b AND x.actor_user_id=actor AND x.object_type='operational_finance' AND x.object_id=p
 AND x.action=$6 AND x.metadata_json=$7 AND y.event_type=$6 AND y.aggregate_type='operational_finance' AND y.aggregate_id=p
 AND y.payload=$7||jsonb_build_object('audit_event_id',a) AND (y.workspace_id,y.organization_id,y.legal_entity_id)=(z.workspace_id,z.organization_id,z.legal_entity_id))
$fi$;
CREATE FUNCTION reconforge.installment_close(t TEXT,i TEXT) RETURNS VOID LANGUAGE plpgsql SET search_path=pg_catalog AS $fi$
DECLARE p RECORD;e RECORD;r RECORD;l RECORD;f RECORD;a RECORD;h RECORD;s JSONB;header JSONB;lines JSONB;maker TEXT;seal TEXT;
 allocated NUMERIC; c RECORD; request_expected JSONB; effect_kind TEXT; account_kind TEXT;
BEGIN
 SELECT * INTO p FROM reconforge.financial_installment_plans WHERE tenant_id=t AND id=i;
 IF p IS NULL THEN RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='financial_installment_owner_phase',MESSAGE='FI1 source owner is required'; END IF;
 SELECT * INTO e FROM reconforge.finance_entries WHERE tenant_id=t AND id=p.entry_id;
 SELECT * INTO h FROM reconforge.ap_supplier_invoices WHERE tenant_id=t AND id=p.source_id;
 SELECT * INTO r FROM reconforge.financial_installment_reviews WHERE tenant_id=t AND plan_id=i;
 SELECT * INTO l FROM reconforge.financial_installment_links WHERE tenant_id=t AND plan_id=i;
 maker:=p.payload->>'preparer_actor_id';seal:=p.payload->>'plan_digest';s:=reconforge.ops_source(t,'APPayment',p.source_id);
 IF e IS NULL OR h IS NULL OR s IS NULL OR h.status NOT IN ('Approved','Paid')
 OR NOT EXISTS(SELECT 1 FROM reconforge.procurement_partial_invoices v WHERE v.tenant_id=t AND v.native_invoice_id=p.source_id AND v.stage=4)
 OR p.payload->'source_snapshot' IS DISTINCT FROM s OR (s->>'tax_minor')::bigint<>0
 OR reconforge.irp_digest(p.payload-'plan_digest'-'validation_digest') IS DISTINCT FROM seal
 OR p.payload->>'id' IS DISTINCT FROM p.id OR p.payload->>'entry_id' IS DISTINCT FROM p.entry_id
 OR p.payload->>'source_id' IS DISTINCT FROM p.source_id OR p.payload->>'source_kind' IS DISTINCT FROM 'APPayment'
 OR (p.payload->>'amount_minor')::bigint IS DISTINCT FROM p.amount_minor
 OR (p.payload->>'workspace_id',p.payload->>'organization_id',p.payload->>'legal_entity_id') IS DISTINCT FROM
 (p.workspace_id,p.organization_id,p.legal_entity_id)
 OR (s->>'workspace_id',s->>'organization_id',s->>'legal_entity_id') IS DISTINCT FROM (p.workspace_id,p.organization_id,p.legal_entity_id)
 OR e.entry_number<>upper(p.id) OR e.source_type<>'Manual' OR e.external_reference<>'AP-PAYMENT:'||p.source_id
 OR e.preparer_actor_id<>maker OR e.total_debit_minor<>p.amount_minor OR e.total_credit_minor<>p.amount_minor
 OR e.currency_code<>s->>'currency_code' OR e.currency_code<>p.payload->>'currency_code'
 OR e.currency_precision<>(p.payload->>'currency_precision')::integer OR e.reverses_posting_id IS NOT NULL
 OR (p.payload->>'allocated_before_minor')::numeric<0
 OR (p.payload->>'allocated_before_minor')::numeric+p.amount_minor>h.total_minor
 OR (SELECT count(*) FROM reconforge.financial_installment_plans q WHERE q.tenant_id=t AND q.source_id=p.source_id)>200 THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='financial_installment_owner_phase',MESSAGE='Installment native source, exact amount and retained plan differ'; END IF;
 IF NOT EXISTS(SELECT 1 FROM reconforge.organizations o JOIN reconforge.legal_entities x ON x.tenant_id=o.tenant_id AND x.organization_id=o.id
 WHERE o.tenant_id=t AND o.id=p.organization_id AND x.id=p.legal_entity_id AND o.application_workspace_id=p.workspace_id
 AND e.organization_code=o.organization_code AND e.entity_code=x.entity_code AND x.currency_code=e.currency_code) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='financial_installment_owner_phase',MESSAGE='Installment GL hierarchy differs'; END IF;
 SELECT jsonb_object_agg(key,value) INTO header FROM jsonb_each(to_jsonb(e)) WHERE key=ANY(ARRAY[
 'id','workspace_id','journal_id','period_id','entry_number','posting_date','description','external_reference','source_type','currency_code',
 'currency_precision','currency_rounding_policy','currency_registry_version','currency_registry_digest','preparer_actor_id','reverses_posting_id']);
 header:=header||jsonb_build_object('organization_id',p.organization_id,'legal_entity_id',p.legal_entity_id);
 SELECT jsonb_agg(jsonb_build_object('line_number',x.line_number,'account_id',x.account_id,'description',x.description,
 'debit_minor',x.debit_minor,'credit_minor',x.credit_minor,'dimensions',COALESCE((SELECT jsonb_object_agg(d.dimension_id,d.dimension_value_id)
 FROM reconforge.finance_entry_line_dimensions d WHERE d.tenant_id=t AND d.entry_line_id=x.id),'{}'::jsonb)) ORDER BY x.line_number)
 INTO lines FROM reconforge.finance_entry_lines x WHERE x.tenant_id=t AND x.entry_id=e.id;
 IF p.payload->'snapshot' IS DISTINCT FROM jsonb_build_object('schema_version','finance-entry-review-v1','entry',header,'lines',lines)
 OR reconforge.irp_digest(p.payload->'snapshot') IS DISTINCT FROM p.payload->>'validation_digest'
 OR jsonb_array_length(lines)<>2 OR (lines->0->>'debit_minor')::bigint<>p.amount_minor OR (lines->0->>'credit_minor')::bigint<>0
 OR (lines->1->>'credit_minor')::bigint<>p.amount_minor OR (lines->1->>'debit_minor')::bigint<>0 THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='financial_installment_owner_phase',MESSAGE='Installment GL snapshot is incomplete'; END IF;
 SELECT account_type INTO account_kind FROM reconforge.finance_accounts WHERE tenant_id=t AND id=lines->0->>'account_id';
 IF account_kind<>'Liability' THEN RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='financial_installment_owner_phase',MESSAGE='AP debit requires a liability account'; END IF;
 SELECT account_type INTO account_kind FROM reconforge.finance_accounts WHERE tenant_id=t AND id=lines->1->>'account_id';
 IF account_kind<>'Asset' THEN RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='financial_installment_owner_phase',MESSAGE='Cash credit requires an asset account'; END IF;
 IF NOT reconforge.installment_event(t,i,p.audit_event_id,p.outbox_event_id,maker,'financial_installment_prepared',jsonb_build_object('plan_digest',seal)) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='financial_installment_owner_phase',MESSAGE='Installment preparation evidence is incomplete'; END IF;
 IF p.phase=0 AND (e.status<>'Draft' OR r IS NOT NULL OR l IS NOT NULL) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='financial_installment_owner_phase',MESSAGE='Prepared installment source phase differs'; END IF;
 IF p.phase>=1 AND (r IS NULL OR r.reviewer_actor_id=maker OR e.validator_actor_id<>r.reviewer_actor_id
 OR e.validation_digest<>p.payload->>'validation_digest'
 OR NOT reconforge.installment_event(t,i,r.audit_event_id,r.outbox_event_id,r.reviewer_actor_id,'financial_installment_reviewed',jsonb_build_object('plan_digest',seal))) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='financial_installment_owner_phase',MESSAGE='Independent installment review is required'; END IF;
 IF p.phase=1 AND (e.status<>'Validated' OR l IS NOT NULL) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='financial_installment_owner_phase',MESSAGE='Reviewed installment source phase differs'; END IF;
 IF p.phase<2 THEN
 SELECT COALESCE(sum(allocation.amount_minor),0) INTO allocated FROM reconforge.ap_payment_links allocation WHERE allocation.tenant_id=t AND allocation.supplier_invoice_id=p.source_id
 AND NOT EXISTS(SELECT 1 FROM reconforge.ap_payment_link_reversals z WHERE z.tenant_id=t AND z.payment_link_id=allocation.id);
 IF h.status<>'Approved' OR h.row_version<>(p.payload->>'invoice_version')::integer
 OR allocated<>(p.payload->>'allocated_before_minor')::numeric OR allocated+p.amount_minor>h.total_minor THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='financial_installment_owner_phase',MESSAGE='Pending installment must retain the exact current invoice residual'; END IF;
 ELSE
 SELECT * INTO f FROM reconforge.finance_posting_effects WHERE tenant_id=t AND id=l.posting_effect_id;
 SELECT * INTO a FROM reconforge.ap_payment_links WHERE tenant_id=t AND id=l.payment_link_id;
 IF l IS NULL OR f IS NULL OR a IS NULL OR e.status<>'Validated' OR f.entry_id<>p.entry_id OR f.snapshot_json<>p.payload->'snapshot'
 OR f.validation_digest<>p.payload->>'validation_digest' OR f.posted_actor_id<>l.posted_actor_id
 OR l.posted_actor_id IN (maker,r.reviewer_actor_id) OR a.finance_effect_id<>f.id OR a.supplier_invoice_id<>p.source_id
 OR a.amount_minor<>p.amount_minor OR a.currency_code<>e.currency_code OR a.invoice_version_before<>(p.payload->>'invoice_version')::integer
 OR h.row_version<a.invoice_version_before+1
 OR (SELECT COALESCE(sum(z.amount_minor),0) FROM reconforge.ap_payment_links z WHERE z.tenant_id=t AND z.supplier_invoice_id=p.source_id
 AND z.invoice_version_before<a.invoice_version_before
 AND NOT EXISTS(SELECT 1 FROM reconforge.ap_payment_link_reversals v WHERE v.tenant_id=t AND v.payment_link_id=z.id))<>(p.payload->>'allocated_before_minor')::numeric
 OR (a.ap_account_id,a.cash_account_id) IS DISTINCT FROM (lines->0->>'account_id',lines->1->>'account_id')
 OR EXISTS(SELECT 1 FROM reconforge.finance_posting_effects z WHERE z.tenant_id=t AND z.reverses_effect_id=f.id)
 OR NOT reconforge.installment_event(t,i,l.audit_event_id,l.outbox_event_id,l.posted_actor_id,'financial_installment_posted',
 jsonb_build_object('plan_digest',seal,'posting_effect_id',f.id,'payment_link_id',a.id)) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='financial_installment_owner_phase',MESSAGE='Posted installment requires its exact native AP allocation and financial effect'; END IF;
 END IF;
 FOR c IN SELECT * FROM reconforge.financial_installment_commands WHERE tenant_id=t AND plan_id=i LOOP
 IF (c.workspace_id,c.organization_id,c.legal_entity_id) IS DISTINCT FROM (p.workspace_id,p.organization_id,p.legal_entity_id)
 OR reconforge.irp_digest(c.request_json)<>c.request_digest OR c.request_json->>'operation'<>c.operation OR c.request_json->>'actor_id'<>c.actor_id
 OR (c.response_json-ARRAY['phase','status','reviewer_actor_id','posting_effect_id','payment_link_id']) IS DISTINCT FROM p.payload
 OR (c.response_json->>'phase')::integer<>(CASE c.operation WHEN 'prepare' THEN 0 WHEN 'review' THEN 1 ELSE 2 END)
 OR c.response_json->>'status' IS DISTINCT FROM (CASE c.operation WHEN 'prepare' THEN 'Prepared' WHEN 'review' THEN 'Reviewed' ELSE 'Posted' END)
 OR c.response_json->>'reviewer_actor_id' IS DISTINCT FROM (CASE WHEN c.operation='prepare' THEN NULL ELSE r.reviewer_actor_id END)
 OR c.response_json->>'posting_effect_id' IS DISTINCT FROM (CASE WHEN c.operation='post' THEN l.posting_effect_id ELSE NULL END)
 OR c.response_json->>'payment_link_id' IS DISTINCT FROM (CASE WHEN c.operation='post' THEN l.payment_link_id ELSE NULL END)
 OR c.actor_id IS DISTINCT FROM (CASE c.operation WHEN 'prepare' THEN maker WHEN 'review' THEN r.reviewer_actor_id ELSE l.posted_actor_id END) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='financial_installment_owner_phase',MESSAGE='Installment command does not close its actor and retained response'; END IF;
 IF c.operation<>'prepare' AND c.request_json->'request'<>jsonb_build_object('plan_id',i,'expected_plan_digest',seal,'reason',
 CASE c.operation WHEN 'review' THEN r.reason ELSE l.reason END) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='financial_installment_owner_phase',MESSAGE='Installment retry request differs'; END IF;
 IF c.operation='prepare' AND c.request_json->'request' IS DISTINCT FROM (p.payload-ARRAY[
 'schema_version','id','entry_id','invoice_version','allocated_before_minor','currency_code','currency_precision','source_snapshot',
 'snapshot','preparer_actor_id','plan_digest','validation_digest']) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='financial_installment_owner_phase',MESSAGE='Installment preparation request differs'; END IF;
 END LOOP;
 IF NOT EXISTS(SELECT 1 FROM reconforge.financial_installment_commands WHERE tenant_id=t AND plan_id=i AND operation='prepare')
 OR (p.phase>=1 AND NOT EXISTS(SELECT 1 FROM reconforge.financial_installment_commands WHERE tenant_id=t AND plan_id=i AND operation='review'))
 OR (p.phase=2 AND NOT EXISTS(SELECT 1 FROM reconforge.financial_installment_commands WHERE tenant_id=t AND plan_id=i AND operation='post')) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='financial_installment_owner_phase',MESSAGE='Installment phase requires an immutable command'; END IF;
END $fi$;
CREATE FUNCTION reconforge.installment_reverse_close() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $fi$
DECLARE changed JSONB;changes JSONB[];p RECORD;native_entry TEXT;native_number TEXT;owner_id TEXT;
BEGIN
 IF TG_OP='INSERT' THEN changes:=ARRAY[to_jsonb(NEW)]; ELSIF TG_OP='DELETE' THEN changes:=ARRAY[to_jsonb(OLD)];
 ELSE changes:=ARRAY[to_jsonb(OLD),to_jsonb(NEW)]; END IF;
 FOREACH changed IN ARRAY changes LOOP
  IF TG_TABLE_NAME='ap_payment_links' AND EXISTS(SELECT 1 FROM reconforge.procurement_partial_invoices v
   WHERE v.tenant_id=changed->>'tenant_id' AND v.native_invoice_id=changed->>'supplier_invoice_id') AND NOT EXISTS(
   SELECT 1 FROM reconforge.financial_installment_links l JOIN reconforge.financial_installment_plans p
   ON p.tenant_id=l.tenant_id AND p.id=l.plan_id WHERE p.tenant_id=changed->>'tenant_id' AND p.phase=2
   AND p.source_id=changed->>'supplier_invoice_id' AND l.payment_link_id=changed->>'id'
   AND l.posting_effect_id=changed->>'finance_effect_id') THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='financial_installment_owner_phase',MESSAGE='Partial source payment requires its reviewed FI1 owner';
  END IF;
  IF TG_TABLE_NAME IN ('domain_audit_events','outbox_events') THEN
   owner_id:=CASE WHEN TG_TABLE_NAME='domain_audit_events' THEN changed->>'object_id' ELSE changed->>'aggregate_id' END;
   IF upper(left(COALESCE(owner_id,''),4))<>'FI1-' THEN CONTINUE; END IF;
   PERFORM reconforge.installment_close(changed->>'tenant_id',owner_id);
   CONTINUE;
  END IF;
  native_entry:=CASE WHEN TG_TABLE_NAME='finance_entries' THEN changed->>'id' ELSE changed->>'entry_id' END;
  IF TG_TABLE_NAME='finance_entry_line_dimensions' THEN
   SELECT entry_id INTO native_entry FROM reconforge.finance_entry_lines WHERE tenant_id=changed->>'tenant_id' AND id=changed->>'entry_line_id';
  END IF;
  IF TG_TABLE_NAME IN ('finance_entries','finance_entry_lines','finance_entry_line_dimensions','finance_posting_effects') THEN
   IF TG_TABLE_NAME='finance_posting_effects' AND changed->>'reverses_effect_id' IS NOT NULL THEN
    SELECT entry_id INTO native_entry FROM reconforge.finance_posting_effects WHERE tenant_id=changed->>'tenant_id' AND id=changed->>'reverses_effect_id';
   END IF;
   native_number:=CASE WHEN TG_TABLE_NAME='finance_entries' THEN changed->>'entry_number' ELSE NULL END;
   IF native_number IS NULL THEN SELECT entry_number INTO native_number FROM reconforge.finance_entries
    WHERE tenant_id=changed->>'tenant_id' AND id=native_entry; END IF;
   IF upper(left(COALESCE(native_number,''),4))<>'FI1-' THEN CONTINUE; END IF;
  END IF;
  IF TG_TABLE_NAME='finance_entries' AND upper(changed->>'entry_number') LIKE 'FI1-%' THEN
   SELECT * INTO p FROM reconforge.financial_installment_plans WHERE tenant_id=changed->>'tenant_id' AND entry_id=native_entry;
   IF p IS NULL THEN RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='financial_installment_owner_phase',MESSAGE='Reserved FI1 entry requires its source'; END IF;
  END IF;
  FOR p IN SELECT * FROM reconforge.financial_installment_plans WHERE tenant_id=changed->>'tenant_id' AND
   (id=changed->>'id' OR id=changed->>'plan_id' OR entry_id=native_entry OR source_id=changed->>'id'
    OR source_id=changed->>'supplier_invoice_id'
    OR entry_id IN (SELECT z.entry_id FROM reconforge.finance_posting_effects z
     WHERE z.tenant_id=changed->>'tenant_id' AND z.id=changed->>'reverses_effect_id')) LOOP
   PERFORM reconforge.installment_close(p.tenant_id,p.id);
  END LOOP;
 END LOOP; RETURN NULL;
END $fi$;
DO $fi$ DECLARE n TEXT; BEGIN
 FOREACH n IN ARRAY ARRAY['financial_installment_plans','financial_installment_reviews','financial_installment_links','financial_installment_commands'] LOOP
  EXECUTE format('ALTER TABLE reconforge.%I ENABLE ROW LEVEL SECURITY',n);
  EXECUTE format('ALTER TABLE reconforge.%I FORCE ROW LEVEL SECURITY',n);
  IF n IN ('financial_installment_plans','financial_installment_commands') THEN
   EXECUTE format('CREATE POLICY scope ON reconforge.%I USING(reconforge.irp_scope(tenant_id,workspace_id,organization_id,legal_entity_id)) WITH CHECK(reconforge.irp_scope(tenant_id,workspace_id,organization_id,legal_entity_id))',n);
  ELSE
   EXECUTE format('CREATE POLICY scope ON reconforge.%I USING(EXISTS(SELECT 1 FROM reconforge.financial_installment_plans p WHERE p.tenant_id=%I.tenant_id AND p.id=%I.plan_id)) WITH CHECK(EXISTS(SELECT 1 FROM reconforge.financial_installment_plans p WHERE p.tenant_id=%I.tenant_id AND p.id=%I.plan_id))',n,n,n,n,n);
  END IF;
  EXECUTE format('CREATE TRIGGER immutable BEFORE UPDATE OR DELETE ON reconforge.%I FOR EACH ROW EXECUTE FUNCTION reconforge.installment_protect()',n);
 END LOOP;
 FOREACH n IN ARRAY ARRAY['financial_installment_plans','financial_installment_reviews','financial_installment_links','financial_installment_commands',
 'finance_entries','finance_entry_lines','finance_entry_line_dimensions','finance_posting_effects','ap_supplier_invoices','ap_payment_links',
 'domain_audit_events','outbox_events'] LOOP
  EXECUTE format('CREATE CONSTRAINT TRIGGER installment_owner_closure AFTER INSERT OR UPDATE OR DELETE ON reconforge.%I DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION reconforge.installment_reverse_close()',n);
 END LOOP;
END $fi$;
"""

DOWNGRADE_SQL = r"""
DO $fi$ BEGIN IF EXISTS(SELECT 1 FROM reconforge.financial_installment_plans) THEN
 RAISE EXCEPTION 'Installment downgrade refuses to discard retained financial evidence'; END IF; END $fi$;
DO $fi$ DECLARE n TEXT; BEGIN
 FOREACH n IN ARRAY ARRAY['financial_installment_plans','financial_installment_reviews','financial_installment_links','financial_installment_commands',
 'finance_entries','finance_entry_lines','finance_entry_line_dimensions','finance_posting_effects','ap_supplier_invoices','ap_payment_links',
 'domain_audit_events','outbox_events'] LOOP
 EXECUTE format('DROP TRIGGER installment_owner_closure ON reconforge.%I',n); END LOOP;
END $fi$;
DROP FUNCTION reconforge.installment_reverse_close();
DROP FUNCTION reconforge.installment_protect();
DROP FUNCTION reconforge.installment_close(TEXT,TEXT);
DROP FUNCTION reconforge.installment_event(TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,JSONB);
DROP TABLE reconforge.financial_installment_commands,reconforge.financial_installment_links,reconforge.financial_installment_reviews,reconforge.financial_installment_plans;
"""
