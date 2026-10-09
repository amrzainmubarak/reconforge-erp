"""Forward extension of existing stock owners, preserving all delivery invariants."""

UPGRADE_SQL = r"""
CREATE FUNCTION reconforge.collection_invoice_close(t TEXT,i TEXT) RETURNS VOID LANGUAGE plpgsql SET search_path=pg_catalog AS $ca$
DECLARE h RECORD; retained_plan RECORD; allocated NUMERIC; paid NUMERIC;
BEGIN
 IF NOT EXISTS(SELECT 1 FROM reconforge.commercial_collection_plans WHERE tenant_id=t AND source_id=i) THEN RETURN; END IF;
 SELECT * INTO h FROM reconforge.ar_invoices WHERE tenant_id=t AND id=i;
 SELECT coalesce(sum(amount_minor),0) INTO allocated FROM reconforge.ar_receipt_allocations WHERE tenant_id=t AND invoice_id=i;
 SELECT coalesce(sum(amount_minor),0) INTO paid FROM reconforge.commercial_collection_plans WHERE tenant_id=t AND source_id=i AND phase=2;
 IF h IS NULL OR paid IS DISTINCT FROM allocated OR paid>h.total_minor
 OR h.status IS DISTINCT FROM (CASE WHEN paid=0 THEN'Approved' WHEN paid=h.total_minor THEN'Paid' ELSE'PartiallyPaid' END)
 OR EXISTS(SELECT 1 FROM reconforge.ar_receipt_allocations a WHERE a.tenant_id=t AND a.invoice_id=i AND NOT EXISTS(
  SELECT 1 FROM reconforge.commercial_collection_links l JOIN reconforge.commercial_collection_plans p ON p.tenant_id=l.tenant_id AND p.id=l.plan_id
  WHERE p.tenant_id=t AND p.source_id=i AND p.phase=2 AND l.receipt_id=a.receipt_id AND p.amount_minor=a.amount_minor)) THEN
  RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='commercial_collection_owner_phase',MESSAGE='Invoice status, native allocations and reviewed cash effects must agree';
 END IF;
 FOR retained_plan IN SELECT id FROM reconforge.commercial_collection_plans WHERE tenant_id=t AND source_id=i LOOP
  PERFORM reconforge.collection_close(t,retained_plan.id);
 END LOOP;
END $ca$;
CREATE FUNCTION reconforge.collection_command_admit() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $ca$
DECLARE p RECORD;permission TEXT;
BEGIN
 SELECT * INTO p FROM reconforge.commercial_collection_plans WHERE tenant_id=NEW.tenant_id AND id=NEW.plan_id;
 permission:=CASE WHEN NEW.operation='review' THEN'sales.approve' ELSE'sales.manage' END;
 IF p IS NULL OR NOT reconforge.irp_scope(p.tenant_id,p.workspace_id,p.organization_id,p.legal_entity_id)
 OR NOT reconforge.sales_revenue_actor(p.tenant_id,NEW.actor_id,permission)
 OR NOT reconforge.sales_revenue_actor(p.tenant_id,NEW.actor_id,CASE NEW.operation WHEN'prepare' THEN'finance_core.manage' WHEN'review' THEN'finance_core.validate' ELSE'finance_core.post' END)
 OR NOT reconforge.sales_revenue_actor(p.tenant_id,NEW.actor_id,'receivables.manage') THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='commercial_collection_owner_phase',MESSAGE='Collection command requires current persisted scoped human authority'; END IF;
 RETURN NEW;
END $ca$;
CREATE TRIGGER commercial_collection_command_admission BEFORE INSERT ON reconforge.commercial_collection_commands
 FOR EACH ROW EXECUTE FUNCTION reconforge.collection_command_admit();
DO $ca$ DECLARE definition TEXT; original TEXT; BEGIN
 definition:=pg_get_functiondef('reconforge.stock_sales_close(text,text)'::regprocedure);original:=definition;
 definition:=replace(definition,
  'OR invoice.status IS DISTINCT FROM(CASE WHEN s=7 THEN''Submitted'' WHEN s=12 THEN''Paid'' ELSE''Approved'' END)',
  'OR (NOT EXISTS(SELECT 1 FROM reconforge.commercial_collection_plans cp WHERE cp.tenant_id=t AND cp.source_id=d.invoice_id) AND invoice.status IS DISTINCT FROM(CASE WHEN s=7 THEN''Submitted'' WHEN s=12 THEN''Paid'' ELSE''Approved'' END)) OR(EXISTS(SELECT 1 FROM reconforge.commercial_collection_plans cp WHERE cp.tenant_id=t AND cp.source_id=d.invoice_id) AND NOT(s=9 AND d.collection_plan_id IS NULL AND invoice.status IN(''Approved'',''PartiallyPaid'',''Paid'')))');
 definition:=replace(definition,
  'OR EXISTS(SELECT 1 FROM reconforge.ar_receipt_allocations WHERE tenant_id=t AND invoice_id=d.invoice_id AND s<>12)',
  'OR EXISTS(SELECT 1 FROM reconforge.ar_receipt_allocations WHERE tenant_id=t AND invoice_id=d.invoice_id AND s<>12 AND NOT EXISTS(SELECT 1 FROM reconforge.commercial_collection_plans cp WHERE cp.tenant_id=t AND cp.source_id=d.invoice_id))');
 definition:=replace(definition,'IF d.invoice_id IS NOT NULL THEN',
  'IF d.invoice_id IS NOT NULL THEN PERFORM reconforge.collection_invoice_close(t,d.invoice_id);');
 IF definition=original OR position('commercial_collection_plans' IN definition)=0 THEN RAISE EXCEPTION 'Stock Sales closure version differs from retained extension contract'; END IF;
 EXECUTE definition;
 definition:=pg_get_functiondef('reconforge.stock_commerce_public(reconforge.stock_commerce_orders)'::regprocedure);
 definition:=replace(definition,'sum(CASE WHEN s.status=''Paid'' THEN s.total_minor ELSE 0 END) collected',
  'sum(coalesce((SELECT sum(amount_minor) FROM reconforge.ar_receipt_allocations WHERE tenant_id=s.tenant_id AND invoice_id=s.invoice_id),0)) collected');
 definition:=replace(definition,'''status'',s.status,''row_version'',s.row_version,''invoice_id'',s.invoice_id,''receipt_id'',s.receipt_id,',
  '''status'',s.status,''row_version'',s.row_version,''invoice_id'',s.invoice_id,''receipt_id'',s.receipt_id,
   ''receivable_account_code'',s.invoice_parameters->>''receivable_account_code'',
   ''invoice_status'',(SELECT status FROM reconforge.ar_invoices WHERE tenant_id=s.tenant_id AND id=s.invoice_id),
   ''collected_minor'',coalesce((SELECT sum(amount_minor) FROM reconforge.ar_receipt_allocations WHERE tenant_id=s.tenant_id AND invoice_id=s.invoice_id),0)::text,
   ''outstanding_minor'',(s.total_minor-coalesce((SELECT sum(amount_minor) FROM reconforge.ar_receipt_allocations WHERE tenant_id=s.tenant_id AND invoice_id=s.invoice_id),0))::text,
   ''pending_collection'',(SELECT jsonb_build_object(''id'',p.id,''plan_digest'',p.payload->>''plan_digest'',''phase'',p.phase,''amount_minor'',p.amount_minor::text,
    ''preparer_actor_id'',p.payload->>''preparer_actor_id'',''reviewer_actor_id'',(SELECT reviewer_actor_id FROM reconforge.commercial_collection_reviews WHERE tenant_id=p.tenant_id AND plan_id=p.id))
    FROM reconforge.commercial_collection_plans p WHERE p.tenant_id=s.tenant_id AND p.source_id=s.invoice_id AND p.phase<2),');
 EXECUTE definition;
END $ca$;
"""
