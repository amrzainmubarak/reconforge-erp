"""Tenant-isolated service-sales sources and immutable acknowledgements."""

POSTGRES_SALES_REVENUE_SCHEMA_SQL = r"""
CREATE TABLE reconforge.sales_revenue_documents (
 tenant_id TEXT NOT NULL REFERENCES reconforge.tenants(id), id TEXT NOT NULL,
 workspace_id TEXT NOT NULL, organization_id TEXT NOT NULL, legal_entity_id TEXT NOT NULL,
 customer_id TEXT NOT NULL, number TEXT NOT NULL, quotation JSONB NOT NULL,
 quotation_digest TEXT NOT NULL CHECK(quotation_digest ~ '^[0-9a-f]{64}$'),
 currency_code TEXT NOT NULL, total_minor BIGINT NOT NULL CHECK(total_minor BETWEEN 1 AND 9000000000000000000),
 status TEXT NOT NULL DEFAULT 'Draft' CHECK(status IN ('Draft','Submitted','Approved','Ordered','Fulfilled',
 'InvoicePrepared','InvoiceReviewed','Invoiced','CollectionPrepared','CollectionReviewed','Paid','Cancelled')),
 created_by TEXT NOT NULL, approved_by TEXT, approved_reason TEXT,
 order_reference TEXT, fulfillment_reference TEXT, fulfillment_date DATE,
 invoice_id TEXT, invoice_plan_id TEXT, collection_plan_id TEXT, receipt_id TEXT,
 invoice_parameters JSONB, collection_parameters JSONB,
 row_version INTEGER NOT NULL DEFAULT 1 CHECK(row_version>0),
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 PRIMARY KEY(tenant_id,id), UNIQUE(tenant_id,workspace_id,number),
 FOREIGN KEY(tenant_id,workspace_id) REFERENCES reconforge.domain_workspaces(tenant_id,id),
 FOREIGN KEY(tenant_id,organization_id) REFERENCES reconforge.organizations(tenant_id,id),
 FOREIGN KEY(tenant_id,legal_entity_id) REFERENCES reconforge.legal_entities(tenant_id,id),
 FOREIGN KEY(tenant_id,customer_id) REFERENCES reconforge.ar_customers(tenant_id,id),
 FOREIGN KEY(tenant_id,currency_code) REFERENCES reconforge.currencies(tenant_id,code),
 FOREIGN KEY(tenant_id,created_by) REFERENCES reconforge.identity_users(tenant_id,id),
 FOREIGN KEY(tenant_id,approved_by) REFERENCES reconforge.identity_users(tenant_id,id),
 FOREIGN KEY(tenant_id,invoice_id) REFERENCES reconforge.ar_invoices(tenant_id,id),
 FOREIGN KEY(tenant_id,receipt_id) REFERENCES reconforge.ar_receipts(tenant_id,id),
 CHECK(approved_by IS NULL OR approved_by<>created_by),
 CHECK(status NOT IN ('Approved','Ordered','Fulfilled','InvoicePrepared','InvoiceReviewed','Invoiced',
 'CollectionPrepared','CollectionReviewed','Paid') OR (approved_by IS NOT NULL AND length(approved_reason)>0)),
 CHECK(status NOT IN ('Fulfilled','InvoicePrepared','InvoiceReviewed','Invoiced','CollectionPrepared',
 'CollectionReviewed','Paid') OR (fulfillment_reference IS NOT NULL AND fulfillment_date IS NOT NULL)),
 CHECK(status NOT IN ('InvoicePrepared','InvoiceReviewed','Invoiced','CollectionPrepared','CollectionReviewed','Paid')
 OR (invoice_id IS NOT NULL AND invoice_plan_id IS NOT NULL)),
 CHECK(status<>'Paid' OR receipt_id IS NOT NULL)
);
CREATE INDEX sales_revenue_lane ON reconforge.sales_revenue_documents
 (tenant_id,workspace_id,organization_id,legal_entity_id,id COLLATE "C");
CREATE TABLE reconforge.sales_revenue_commands (
 tenant_id TEXT NOT NULL, workspace_id TEXT NOT NULL, command_id TEXT NOT NULL,
 document_id TEXT NOT NULL, document_version INTEGER NOT NULL, operation TEXT NOT NULL, actor_id TEXT NOT NULL,
 request_digest TEXT NOT NULL CHECK(request_digest ~ '^[0-9a-f]{64}$'), request JSONB NOT NULL, result JSONB NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY(tenant_id,workspace_id,command_id), UNIQUE(tenant_id,document_id,document_version),
 FOREIGN KEY(tenant_id,document_id) REFERENCES reconforge.sales_revenue_documents(tenant_id,id),
 FOREIGN KEY(tenant_id,actor_id) REFERENCES reconforge.identity_users(tenant_id,id)
);
CREATE TABLE reconforge.sales_revenue_events (
 tenant_id TEXT NOT NULL, document_id TEXT NOT NULL, version INTEGER NOT NULL,
 actor_id TEXT NOT NULL, operation TEXT NOT NULL, reason TEXT NOT NULL, status TEXT NOT NULL,
 audit_event_id TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 PRIMARY KEY(tenant_id,document_id,version),
 FOREIGN KEY(tenant_id,document_id) REFERENCES reconforge.sales_revenue_documents(tenant_id,id),
 FOREIGN KEY(tenant_id,actor_id) REFERENCES reconforge.identity_users(tenant_id,id),
 FOREIGN KEY(tenant_id,audit_event_id) REFERENCES reconforge.domain_audit_events(tenant_id,id)
);
CREATE FUNCTION reconforge.sales_revenue_protect() RETURNS trigger
 LANGUAGE plpgsql SET search_path=pg_catalog AS $sales$
BEGIN
 IF TG_OP='DELETE' OR TG_TABLE_NAME<>'sales_revenue_documents' THEN
  RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Retained sales history is immutable.';
 END IF;
 IF NEW.tenant_id<>OLD.tenant_id OR NEW.id<>OLD.id OR NEW.created_by<>OLD.created_by OR NEW.created_at<>OLD.created_at
 OR NEW.row_version<>OLD.row_version+1
 OR (NEW.workspace_id,NEW.organization_id,NEW.legal_entity_id,NEW.customer_id,NEW.number,NEW.quotation,
     NEW.quotation_digest,NEW.currency_code,NEW.total_minor)
 IS DISTINCT FROM
 (OLD.workspace_id,OLD.organization_id,OLD.legal_entity_id,OLD.customer_id,OLD.number,OLD.quotation,
     OLD.quotation_digest,OLD.currency_code,OLD.total_minor)
 OR (OLD.approved_by IS NOT NULL AND (NEW.approved_by,NEW.approved_reason) IS DISTINCT FROM (OLD.approved_by,OLD.approved_reason))
 OR (OLD.invoice_id IS NOT NULL AND (NEW.invoice_id,NEW.invoice_plan_id,NEW.invoice_parameters)
 IS DISTINCT FROM (OLD.invoice_id,OLD.invoice_plan_id,OLD.invoice_parameters))
 OR (OLD.collection_plan_id IS NOT NULL AND (NEW.collection_plan_id,NEW.collection_parameters)
 IS DISTINCT FROM (OLD.collection_plan_id,OLD.collection_parameters))
 OR (OLD.fulfillment_reference IS NOT NULL AND (NEW.fulfillment_reference,NEW.fulfillment_date)
 IS DISTINCT FROM (OLD.fulfillment_reference,OLD.fulfillment_date))
 OR NOT ((OLD.status='Draft' AND NEW.status IN ('Submitted','Cancelled'))
 OR (OLD.status='Submitted' AND NEW.status IN ('Approved','Cancelled'))
 OR (OLD.status='Approved' AND NEW.status IN ('Ordered','Cancelled'))
 OR (OLD.status='Ordered' AND NEW.status IN ('Fulfilled','Cancelled'))
 OR (OLD.status='Fulfilled' AND NEW.status='InvoicePrepared')
 OR (OLD.status='InvoicePrepared' AND NEW.status='InvoiceReviewed')
 OR (OLD.status='InvoiceReviewed' AND NEW.status='Invoiced')
 OR (OLD.status='Invoiced' AND NEW.status='CollectionPrepared')
 OR (OLD.status='CollectionPrepared' AND NEW.status='CollectionReviewed')
 OR (OLD.status='CollectionReviewed' AND NEW.status='Paid')) THEN
  RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Sales transition or immutable source differs.';
 END IF;
 RETURN NEW;
END $sales$;
CREATE TRIGGER sales_revenue_immutable BEFORE UPDATE OR DELETE ON reconforge.sales_revenue_documents
 FOR EACH ROW EXECUTE FUNCTION reconforge.sales_revenue_protect();
CREATE TRIGGER sales_revenue_commands_immutable BEFORE UPDATE OR DELETE ON reconforge.sales_revenue_commands
 FOR EACH ROW EXECUTE FUNCTION reconforge.sales_revenue_protect();
CREATE TRIGGER sales_revenue_events_immutable BEFORE UPDATE OR DELETE ON reconforge.sales_revenue_events
 FOR EACH ROW EXECUTE FUNCTION reconforge.sales_revenue_protect();
CREATE FUNCTION reconforge.sales_revenue_actor(t TEXT,a TEXT,p TEXT) RETURNS BOOLEAN
 LANGUAGE sql STABLE SET search_path=pg_catalog AS $sales$
 SELECT EXISTS(SELECT 1 FROM reconforge.identity_users u
 JOIN reconforge.identity_user_roles ur ON ur.tenant_id=u.tenant_id AND ur.user_id=u.id AND ur.active
 JOIN reconforge.identity_roles r ON r.tenant_id=ur.tenant_id AND r.id=ur.role_id AND r.active
 JOIN reconforge.identity_role_permissions rp ON rp.tenant_id=r.tenant_id AND rp.role_id=r.id AND rp.active
 WHERE u.tenant_id=t AND u.id=a AND NOT u.disabled AND rp.permission_name=p)
$sales$;
CREATE FUNCTION reconforge.sales_revenue_admit() RETURNS trigger
 LANGUAGE plpgsql SET search_path=pg_catalog AS $sales$
DECLARE q JSONB; l JSONB; aggregate NUMERIC:=0; unit NUMERIC; value NUMERIC; customer RECORD; a TEXT:=current_setting('app.sales_actor_id',true); p TEXT;
BEGIN
 IF TG_TABLE_NAME='sales_revenue_documents' THEN
  p:=CASE WHEN NEW.status IN ('Approved','InvoiceReviewed','CollectionReviewed') THEN 'sales.approve' ELSE 'sales.manage' END;
  IF NOT reconforge.sales_revenue_actor(NEW.tenant_id,a,p) OR (TG_OP='INSERT' AND (NEW.status<>'Draft' OR NEW.created_by<>a)) THEN
   RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Sales source requires current active human authority.';
  END IF;
  IF NEW.status='Approved' AND (NEW.approved_by IS DISTINCT FROM a OR a=NEW.created_by) THEN
   RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Sales quotation requires its distinct actual checker.';
  END IF;
  q:=NEW.quotation;
  PERFORM reconforge.irp_bounded(q);
  IF q->>'schema_version' IS DISTINCT FROM 'sales-service-revenue-v1'
  OR q->>'fulfillment_kind' IS DISTINCT FROM 'Service' OR q->>'discount_policy' IS DISTINCT FROM 'per-unit-minor-half-up-v1'
  OR q->>'number' IS DISTINCT FROM NEW.number OR q->>'currency_code' IS DISTINCT FROM NEW.currency_code
  OR q->>'digest' IS DISTINCT FROM NEW.quotation_digest OR reconforge.irp_digest(q-'digest') IS DISTINCT FROM NEW.quotation_digest
  OR (q->>'total_minor')::bigint IS DISTINCT FROM NEW.total_minor OR q->>'tax_minor' IS DISTINCT FROM '0'
  OR jsonb_typeof(q->'lines') IS DISTINCT FROM 'array' OR jsonb_array_length(q->'lines') NOT BETWEEN 1 AND 16 THEN
   RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Sales quotation is not its exact bounded source.';
  END IF;
  FOR l IN SELECT * FROM jsonb_array_elements(q->'lines') LOOP
   IF NOT reconforge.irp_text(l->>'description',500) OR length(l->>'quantity')>64 OR l->>'quantity' !~ '^[0-9]+(\.[0-9]+)?$'
   OR l->>'gross_unit_price_minor' !~ '^[1-9][0-9]{0,18}$' OR l->>'discount_basis_points' !~ '^(0|[1-9][0-9]{0,3})$'
   OR (l->>'discount_basis_points')::integer NOT BETWEEN 0 AND 9999 OR l->>'tax_minor' IS DISTINCT FROM '0' THEN
    RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Sales service pricing requires exact units and bounded discount.';
   END IF;
   unit:=floor(((l->>'gross_unit_price_minor')::numeric*(10000-(l->>'discount_basis_points')::integer)+5000)/10000);
   value:=round((l->>'quantity')::numeric*unit,0);
   IF unit<=0 OR value<=0 OR value>9000000000000000000 OR unit IS DISTINCT FROM (l->>'unit_price_minor')::numeric
   OR value IS DISTINCT FROM (l->>'line_total_minor')::numeric THEN
    RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Sales line does not reproduce exact discounted service value.';
   END IF;
   aggregate:=aggregate+value;
  END LOOP;
  IF aggregate IS DISTINCT FROM NEW.total_minor::numeric THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Sales total does not equal service lines.'; END IF;
  SELECT c.* INTO customer FROM reconforge.ar_customers c JOIN reconforge.organizations o ON o.tenant_id=c.tenant_id AND o.id=c.organization_id
  JOIN reconforge.legal_entities e ON e.tenant_id=c.tenant_id AND e.id=c.legal_entity_id AND e.organization_id=o.id
  WHERE c.tenant_id=NEW.tenant_id AND c.id=NEW.customer_id AND c.workspace_id=NEW.workspace_id
  AND c.organization_id=NEW.organization_id AND c.legal_entity_id=NEW.legal_entity_id
  AND c.currency_code=NEW.currency_code AND o.application_workspace_id=NEW.workspace_id;
  IF customer IS NULL OR q->>'customer_code' IS DISTINCT FROM customer.customer_code THEN
   RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Sales customer and hierarchy differ from their canonical source.';
  END IF;
  IF TG_OP='INSERT' AND (customer.status<>'Active' OR q->'monetary_policy'->>'status' IS DISTINCT FROM 'captured'
  OR (q->'monetary_policy'->>'precision')::integer IS DISTINCT FROM customer.currency_precision
  OR q->'monetary_policy'->>'registry_digest' IS DISTINCT FROM customer.currency_registry_digest) THEN
   RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Sales quotation requires its retained customer monetary policy.';
  END IF;
 ELSE
  p:=CASE WHEN NEW.operation IN ('approve','review_invoice','review_collection') THEN 'sales.approve' ELSE 'sales.manage' END;
  IF NEW.actor_id IS DISTINCT FROM a OR NOT reconforge.sales_revenue_actor(NEW.tenant_id,a,p) THEN
   RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Sales evidence requires its exact current human authority.';
  END IF;
  IF TG_TABLE_NAME='sales_revenue_commands' THEN
   PERFORM reconforge.irp_bounded(NEW.request); PERFORM reconforge.irp_bounded(NEW.result);
   IF reconforge.irp_digest(NEW.request) IS DISTINCT FROM NEW.request_digest OR NEW.request->>'actor_id' IS DISTINCT FROM NEW.actor_id
   OR NEW.request->>'operation' IS DISTINCT FROM NEW.operation THEN
    RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Sales acknowledgement request does not reproduce its digest.';
   END IF;
  END IF;
 END IF;
 RETURN NEW;
END $sales$;
CREATE TRIGGER sales_revenue_admission BEFORE INSERT OR UPDATE ON reconforge.sales_revenue_documents
 FOR EACH ROW EXECUTE FUNCTION reconforge.sales_revenue_admit();
CREATE TRIGGER sales_revenue_command_admission BEFORE INSERT ON reconforge.sales_revenue_commands
 FOR EACH ROW EXECUTE FUNCTION reconforge.sales_revenue_admit();
CREATE TRIGGER sales_revenue_event_admission BEFORE INSERT ON reconforge.sales_revenue_events
 FOR EACH ROW EXECUTE FUNCTION reconforge.sales_revenue_admit();
CREATE FUNCTION reconforge.sales_revenue_close() RETURNS trigger
 LANGUAGE plpgsql SET search_path=pg_catalog AS $sales$
DECLARE d RECORD; ev RECORD; cmd RECORD; invoice RECORD; plan RECORD; receipt RECORD; target TEXT;
BEGIN
 IF TG_TABLE_NAME='sales_revenue_documents' THEN target:=NEW.id; ELSE target:=NEW.document_id; END IF;
 SELECT * INTO d FROM reconforge.sales_revenue_documents WHERE tenant_id=NEW.tenant_id AND id=target;
 IF d IS NULL OR NOT reconforge.irp_scope(d.tenant_id,d.workspace_id,d.organization_id,d.legal_entity_id)
 OR (SELECT count(*) FROM reconforge.sales_revenue_events WHERE tenant_id=d.tenant_id AND document_id=d.id)<>d.row_version
 OR (SELECT count(*) FROM reconforge.sales_revenue_commands WHERE tenant_id=d.tenant_id AND document_id=d.id)<>d.row_version THEN
  RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Sales source requires one complete command and audit event per version.';
 END IF;
 FOR ev IN SELECT * FROM reconforge.sales_revenue_events WHERE tenant_id=d.tenant_id AND document_id=d.id ORDER BY version LOOP
  SELECT * INTO cmd FROM reconforge.sales_revenue_commands WHERE tenant_id=d.tenant_id AND document_id=d.id AND document_version=ev.version;
  IF cmd IS NULL OR cmd.workspace_id<>d.workspace_id OR cmd.operation<>ev.operation OR cmd.actor_id<>ev.actor_id
  OR cmd.result->>'id' IS DISTINCT FROM d.id OR (cmd.result->>'row_version')::integer IS DISTINCT FROM ev.version
  OR cmd.result->>'status' IS DISTINCT FROM ev.status OR cmd.result->>'quotation_digest' IS DISTINCT FROM d.quotation_digest
  OR cmd.result->>'total_minor' IS DISTINCT FROM d.total_minor::text
  OR cmd.result->>'workspace_id' IS DISTINCT FROM d.workspace_id OR cmd.result->>'organization_id' IS DISTINCT FROM d.organization_id
  OR cmd.result->>'legal_entity_id' IS DISTINCT FROM d.legal_entity_id
  OR cmd.request->'scope'->>'workspace_id' IS DISTINCT FROM d.workspace_id
  OR cmd.request->'scope'->>'organization_id' IS DISTINCT FROM d.organization_id
  OR cmd.request->'scope'->>'legal_entity_id' IS DISTINCT FROM d.legal_entity_id
  OR (ev.version=1 AND (ev.operation<>'create' OR ev.status<>'Draft' OR ev.actor_id<>d.created_by))
  OR (ev.version>1 AND ((cmd.request->'payload'->>'expected_version')::integer IS DISTINCT FROM ev.version-1
  OR cmd.request->'payload'->>'id' IS DISTINCT FROM d.id OR cmd.request->'payload'->>'reason' IS DISTINCT FROM ev.reason))
  OR (ev.version=d.row_version AND ev.status<>d.status)
  OR NOT EXISTS(SELECT 1 FROM reconforge.domain_audit_events a WHERE a.tenant_id=d.tenant_id AND a.id=ev.audit_event_id
   AND a.object_type='sales_revenue' AND a.object_id=d.id AND a.action='sales.'||ev.operation AND a.actor_user_id=ev.actor_id
   AND a.metadata_json->>'source_digest'=d.quotation_digest AND (a.metadata_json->>'version')::integer=ev.version
   AND a.metadata_json->>'status'=ev.status) THEN
   RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Sales acknowledgement or audit event differs from its real source transition.';
  END IF;
  IF jsonb_typeof(cmd.result->'events') IS DISTINCT FROM 'array' OR jsonb_array_length(cmd.result->'events')<>ev.version
  OR EXISTS(SELECT 1 FROM jsonb_array_elements(cmd.result->'events') j WHERE NOT EXISTS(
   SELECT 1 FROM reconforge.sales_revenue_events retained WHERE retained.tenant_id=d.tenant_id AND retained.document_id=d.id
   AND retained.version=(j->>'version')::integer AND retained.operation=j->>'operation' AND retained.actor_id=j->>'actor_id'
   AND retained.reason=j->>'reason' AND retained.audit_event_id=j->>'audit_event_id')) THEN
   RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Sales acknowledgement has fabricated event lineage.';
  END IF;
 END LOOP;
 IF d.invoice_id IS NOT NULL THEN
  SELECT * INTO invoice FROM reconforge.ar_invoices WHERE tenant_id=d.tenant_id AND id=d.invoice_id;
  SELECT * INTO plan FROM reconforge.operational_finance_plans WHERE tenant_id=d.tenant_id AND id=d.invoice_plan_id;
  IF invoice IS NULL OR plan IS NULL OR (invoice.workspace_id,invoice.organization_id,invoice.legal_entity_id,invoice.customer_id,invoice.currency_code,invoice.total_minor)
  IS DISTINCT FROM (d.workspace_id,d.organization_id,d.legal_entity_id,d.customer_id,d.currency_code,d.total_minor)
  OR (plan.workspace_id,plan.organization_id,plan.legal_entity_id,plan.source_kind,plan.source_id,plan.currency_code,plan.amount_minor)
  IS DISTINCT FROM (d.workspace_id,d.organization_id,d.legal_entity_id,'ARInvoice'::text,d.invoice_id,d.currency_code,d.total_minor) THEN
   RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Sales invoice does not have its exact native AR and financial source.';
  END IF;
  IF d.status='InvoicePrepared' AND (invoice.status<>'Submitted' OR EXISTS(SELECT 1 FROM reconforge.operational_finance_reviews WHERE tenant_id=d.tenant_id AND plan_id=plan.id))
  OR d.status='InvoiceReviewed' AND (invoice.status<>'Approved' OR NOT EXISTS(SELECT 1 FROM reconforge.operational_finance_reviews WHERE tenant_id=d.tenant_id AND plan_id=plan.id))
  OR d.status IN ('Invoiced','CollectionPrepared','CollectionReviewed','Paid') AND (invoice.status NOT IN ('Approved','Paid')
   OR NOT EXISTS(SELECT 1 FROM reconforge.operational_finance_links WHERE tenant_id=d.tenant_id AND plan_id=plan.id)) THEN
   RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Sales invoice stage lacks its reviewed or posted financial effect.';
  END IF;
 END IF;
 IF d.collection_plan_id IS NOT NULL THEN
  SELECT * INTO plan FROM reconforge.operational_finance_plans WHERE tenant_id=d.tenant_id AND id=d.collection_plan_id;
  IF plan IS NULL OR (plan.workspace_id,plan.organization_id,plan.legal_entity_id,plan.source_kind,plan.source_id,plan.currency_code,plan.amount_minor)
  IS DISTINCT FROM (d.workspace_id,d.organization_id,d.legal_entity_id,'ARReceipt'::text,d.invoice_id,d.currency_code,d.total_minor)
  OR (d.status IN ('CollectionReviewed','Paid') AND NOT EXISTS(SELECT 1 FROM reconforge.operational_finance_reviews WHERE tenant_id=d.tenant_id AND plan_id=plan.id)) THEN
   RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Sales collection stage lacks its exact reviewed source.';
  END IF;
 END IF;
 IF d.status='Paid' THEN
  SELECT * INTO receipt FROM reconforge.ar_receipts WHERE tenant_id=d.tenant_id AND id=d.receipt_id;
  IF receipt IS NULL OR receipt.status<>'Posted' OR invoice.status<>'Paid'
  OR (receipt.workspace_id,receipt.organization_id,receipt.legal_entity_id,receipt.customer_id,receipt.currency_code,receipt.amount_minor)
  IS DISTINCT FROM (d.workspace_id,d.organization_id,d.legal_entity_id,d.customer_id,d.currency_code,d.total_minor)
  OR NOT EXISTS(SELECT 1 FROM reconforge.ar_receipt_allocations a WHERE a.tenant_id=d.tenant_id AND a.receipt_id=receipt.id
  AND a.invoice_id=invoice.id AND a.amount_minor=d.total_minor)
  OR (SELECT count(*) FROM reconforge.ar_receipt_allocations WHERE tenant_id=d.tenant_id AND receipt_id=receipt.id)<>1
  OR NOT EXISTS(SELECT 1 FROM reconforge.operational_finance_links WHERE tenant_id=d.tenant_id AND plan_id=d.collection_plan_id AND source_effect_id=d.receipt_id) THEN
   RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Collected sale requires one complete AR allocation and its real cash GL effect.';
  END IF;
 END IF;
 RETURN NULL;
END $sales$;
CREATE CONSTRAINT TRIGGER sales_revenue_source_closure AFTER INSERT OR UPDATE ON reconforge.sales_revenue_documents
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION reconforge.sales_revenue_close();
CREATE CONSTRAINT TRIGGER sales_revenue_event_closure AFTER INSERT ON reconforge.sales_revenue_events
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION reconforge.sales_revenue_close();
CREATE CONSTRAINT TRIGGER sales_revenue_command_closure AFTER INSERT ON reconforge.sales_revenue_commands
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION reconforge.sales_revenue_close();
DO $sales$ DECLARE n TEXT; BEGIN
 FOREACH n IN ARRAY ARRAY['sales_revenue_documents','sales_revenue_commands','sales_revenue_events'] LOOP
  EXECUTE format('ALTER TABLE reconforge.%I ENABLE ROW LEVEL SECURITY',n);
  EXECUTE format('ALTER TABLE reconforge.%I FORCE ROW LEVEL SECURITY',n);
  IF n='sales_revenue_documents' THEN
   EXECUTE format('CREATE POLICY tenant_scope ON reconforge.%I USING (reconforge.irp_scope(tenant_id,workspace_id,organization_id,legal_entity_id)) WITH CHECK (reconforge.irp_scope(tenant_id,workspace_id,organization_id,legal_entity_id))',n);
  ELSE
   EXECUTE format('CREATE POLICY tenant_scope ON reconforge.%I USING (EXISTS(SELECT 1 FROM reconforge.sales_revenue_documents d WHERE d.tenant_id=%I.tenant_id AND d.id=%I.document_id)) WITH CHECK (EXISTS(SELECT 1 FROM reconforge.sales_revenue_documents d WHERE d.tenant_id=%I.tenant_id AND d.id=%I.document_id))',n,n,n,n,n);
  END IF;
 END LOOP;
END $sales$;
INSERT INTO reconforge.identity_permissions(tenant_id,name,description)
 SELECT id,p,'Governed service quotation, fulfillment, invoice and collection.' FROM reconforge.tenants
 CROSS JOIN (VALUES('sales.read'),('sales.manage'),('sales.approve')) q(p) ON CONFLICT DO NOTHING;
INSERT INTO reconforge.identity_role_permissions(tenant_id,role_id,permission_name)
 SELECT tenant_id,id,p FROM reconforge.identity_roles CROSS JOIN (VALUES('sales.read'),('sales.manage'),('sales.approve')) q(p)
 WHERE name='admin' ON CONFLICT DO NOTHING;
CREATE FUNCTION reconforge.sales_revenue_seed_permissions() RETURNS trigger
 LANGUAGE plpgsql SET search_path=reconforge,pg_catalog AS $sales$ BEGIN
 IF TG_TABLE_NAME='tenants' THEN
  INSERT INTO reconforge.identity_permissions(tenant_id,name,description)
  SELECT NEW.id,p,'Governed service quotation, fulfillment, invoice and collection.'
  FROM (VALUES('sales.read'),('sales.manage'),('sales.approve')) q(p) ON CONFLICT DO NOTHING;
 ELSIF TG_TABLE_NAME='identity_roles' AND NEW.name='admin' THEN
  INSERT INTO reconforge.identity_role_permissions(tenant_id,role_id,permission_name)
  SELECT NEW.tenant_id,NEW.id,p FROM (VALUES('sales.read'),('sales.manage'),('sales.approve')) q(p) ON CONFLICT DO NOTHING;
 END IF; RETURN NEW; END $sales$;
CREATE TRIGGER sales_revenue_permission_tenant AFTER INSERT ON reconforge.tenants
 FOR EACH ROW EXECUTE FUNCTION reconforge.sales_revenue_seed_permissions();
CREATE TRIGGER sales_revenue_permission_role AFTER INSERT ON reconforge.identity_roles
 FOR EACH ROW EXECUTE FUNCTION reconforge.sales_revenue_seed_permissions();
"""

POSTGRES_SALES_REVENUE_DOWNGRADE_SQL = r"""
DO $sales$ BEGIN
 IF EXISTS(SELECT 1 FROM reconforge.sales_revenue_documents)
 OR EXISTS(SELECT 1 FROM reconforge.identity_role_permissions p JOIN reconforge.identity_roles r
 ON r.tenant_id=p.tenant_id AND r.id=p.role_id WHERE p.permission_name IN ('sales.read','sales.manage','sales.approve') AND r.name<>'admin')
 THEN RAISE EXCEPTION 'Sales downgrade refuses to discard retained sources or custom authority.'; END IF;
END $sales$;
DROP TRIGGER sales_revenue_permission_tenant ON reconforge.tenants;
DROP TRIGGER sales_revenue_permission_role ON reconforge.identity_roles;
DROP FUNCTION reconforge.sales_revenue_seed_permissions();
DELETE FROM reconforge.identity_role_permissions WHERE permission_name IN ('sales.read','sales.manage','sales.approve');
DELETE FROM reconforge.identity_permissions WHERE name IN ('sales.read','sales.manage','sales.approve');
DROP TABLE reconforge.sales_revenue_events,reconforge.sales_revenue_commands,reconforge.sales_revenue_documents;
DROP FUNCTION reconforge.sales_revenue_protect();
DROP FUNCTION reconforge.sales_revenue_admit();
DROP FUNCTION reconforge.sales_revenue_actor(TEXT,TEXT,TEXT);
DROP FUNCTION reconforge.sales_revenue_close();
"""
