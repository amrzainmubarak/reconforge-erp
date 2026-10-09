"""Authoritative commercial line and native tranche closure, with forced scope RLS."""
UPGRADE_SQL = r"""
CREATE TABLE reconforge.stock_commerce_orders (
 tenant_id TEXT NOT NULL,id TEXT NOT NULL,workspace_id TEXT NOT NULL,organization_id TEXT NOT NULL,legal_entity_id TEXT NOT NULL,
 customer_id TEXT NOT NULL,number TEXT NOT NULL,currency_code TEXT NOT NULL,total_minor BIGINT NOT NULL CHECK(total_minor BETWEEN 1 AND 9000000000000000000),
 line_count INTEGER NOT NULL CHECK(line_count BETWEEN 1 AND 1000),source JSONB NOT NULL,source_digest TEXT NOT NULL CHECK(source_digest~'^[a-f0-9]{64}$'),
 status TEXT NOT NULL DEFAULT'Draft' CHECK(status IN('Draft','Submitted','Approved')),row_version INTEGER NOT NULL DEFAULT 1 CHECK(row_version>0),
 created_by TEXT NOT NULL,approved_by TEXT,created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 PRIMARY KEY(tenant_id,id),UNIQUE(tenant_id,workspace_id,number),
 FOREIGN KEY(tenant_id,workspace_id) REFERENCES reconforge.domain_workspaces(tenant_id,id),
 FOREIGN KEY(tenant_id,organization_id) REFERENCES reconforge.organizations(tenant_id,id),
 FOREIGN KEY(tenant_id,legal_entity_id) REFERENCES reconforge.legal_entities(tenant_id,id),
 FOREIGN KEY(tenant_id,customer_id) REFERENCES reconforge.ar_customers(tenant_id,id),
 FOREIGN KEY(tenant_id,created_by) REFERENCES reconforge.identity_users(tenant_id,id),
 FOREIGN KEY(tenant_id,approved_by) REFERENCES reconforge.identity_users(tenant_id,id)
);
CREATE TABLE reconforge.stock_commerce_lines (
 tenant_id TEXT NOT NULL,order_id TEXT NOT NULL,line_number INTEGER NOT NULL CHECK(line_number BETWEEN 1 AND 1000),
 item_id TEXT NOT NULL,uom_id TEXT NOT NULL,location_id TEXT NOT NULL,quantity_precision INTEGER NOT NULL CHECK(quantity_precision BETWEEN 0 AND 6),
 quantity_scaled BIGINT NOT NULL CHECK(quantity_scaled>0),total_minor BIGINT NOT NULL CHECK(total_minor>0),source JSONB NOT NULL,
 PRIMARY KEY(tenant_id,order_id,line_number),FOREIGN KEY(tenant_id,order_id) REFERENCES reconforge.stock_commerce_orders(tenant_id,id),
 FOREIGN KEY(tenant_id,item_id) REFERENCES reconforge.inventory_items(tenant_id,id),
 FOREIGN KEY(tenant_id,uom_id) REFERENCES reconforge.inventory_units_of_measure(tenant_id,id),
 FOREIGN KEY(tenant_id,location_id) REFERENCES reconforge.inventory_locations(tenant_id,id)
);
CREATE TABLE reconforge.stock_commerce_tranches (
 tenant_id TEXT NOT NULL,id TEXT NOT NULL,order_id TEXT NOT NULL,line_number INTEGER NOT NULL,
 stock_order_id TEXT NOT NULL,created_version INTEGER NOT NULL CHECK(created_version>3),
 PRIMARY KEY(tenant_id,id),UNIQUE(tenant_id,stock_order_id),UNIQUE(tenant_id,order_id,created_version),
 FOREIGN KEY(tenant_id,order_id,line_number) REFERENCES reconforge.stock_commerce_lines(tenant_id,order_id,line_number),
 FOREIGN KEY(tenant_id,stock_order_id) REFERENCES reconforge.stock_sales_orders(tenant_id,id)
);
CREATE TABLE reconforge.stock_commerce_commands (
 tenant_id TEXT NOT NULL,workspace_id TEXT NOT NULL,command_id TEXT NOT NULL,order_id TEXT NOT NULL,version INTEGER NOT NULL,
 actor_id TEXT NOT NULL,operation TEXT NOT NULL,reason TEXT NOT NULL,request_digest TEXT NOT NULL,request JSONB NOT NULL,
 result JSONB NOT NULL,result_digest TEXT NOT NULL,audit_event_id TEXT NOT NULL,
 PRIMARY KEY(tenant_id,workspace_id,command_id),UNIQUE(tenant_id,order_id,version),
 FOREIGN KEY(tenant_id,order_id) REFERENCES reconforge.stock_commerce_orders(tenant_id,id),
 FOREIGN KEY(tenant_id,actor_id) REFERENCES reconforge.identity_users(tenant_id,id),
 FOREIGN KEY(tenant_id,audit_event_id) REFERENCES reconforge.domain_audit_events(tenant_id,id)
);
CREATE INDEX stock_commerce_scope ON reconforge.stock_commerce_orders(tenant_id,workspace_id,organization_id,legal_entity_id,id COLLATE"C");
CREATE INDEX stock_commerce_line_tranches ON reconforge.stock_commerce_tranches(tenant_id,order_id,line_number);
CREATE FUNCTION reconforge.stock_commerce_public(d reconforge.stock_commerce_orders) RETURNS JSONB LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
 SELECT jsonb_build_object('id',d.id,'number',d.number,'workspace_id',d.workspace_id,'organization_id',d.organization_id,
 'legal_entity_id',d.legal_entity_id,'customer_code',d.source->>'customer_code','customer_reference',d.source->>'customer_reference',
 'currency_code',d.currency_code,'order_date',d.source->>'order_date','total_minor',d.total_minor::text,'line_count',d.line_count,
 'row_version',d.row_version,'status',d.status,'created_by',d.created_by,'approved_by',d.approved_by,'source_digest',d.source_digest,
 'lines',COALESCE((SELECT jsonb_agg(jsonb_build_object('line_number',l.line_number,'source',
 (l.source-ARRAY['unit_price_minor','net_unit_price_minor','total_minor','quantity_scaled'])||jsonb_build_object(
 'unit_price_minor',l.source->>'unit_price_minor','net_unit_price_minor',l.source->>'net_unit_price_minor',
 'total_minor',l.source->>'total_minor','quantity_scaled',l.source->>'quantity_scaled'),
 'quantity_scaled',l.quantity_scaled::text,'quantity_precision',l.quantity_precision,'total_minor',l.total_minor::text,
 'committed_quantity_scaled',COALESCE(a.committed_quantity,0)::text,'delivered_quantity_scaled',COALESCE(a.delivered_quantity,0)::text,
 'invoiced_minor',COALESCE(a.invoiced,0)::text,'collected_minor',COALESCE(a.collected,0)::text,
 'tranches',COALESCE(a.tranches,'[]'::jsonb)) ORDER BY l.line_number)
 FROM reconforge.stock_commerce_lines l LEFT JOIN LATERAL (
 SELECT sum(CASE WHEN s.status<>'Cancelled' THEN s.quantity_scaled ELSE 0 END) committed_quantity,
 sum(CASE WHEN reconforge.stock_sales_stage(s.status)>=6 THEN s.quantity_scaled ELSE 0 END) delivered_quantity,
 sum(CASE WHEN reconforge.stock_sales_stage(s.status)>=9 THEN s.total_minor ELSE 0 END) invoiced,
 sum(CASE WHEN s.status='Paid' THEN s.total_minor ELSE 0 END) collected,
 jsonb_agg(jsonb_build_object('id',t.id,'stock_order_id',s.id,'quantity_scaled',s.quantity_scaled::text,'total_minor',s.total_minor::text,
 'status',s.status,'row_version',s.row_version,'invoice_id',s.invoice_id,'receipt_id',s.receipt_id,
 'movement_id',s.movement_id,'cogs_effect_id',s.cogs_effect_id,'created_by',s.created_by,
 'issue_preparer_id',s.issue_plan->>'preparer_actor_id','issue_reviewer_id',s.issue_reviewer_id,
 'invoice_preparer_id',(SELECT preparer_actor_id FROM reconforge.operational_finance_plans WHERE tenant_id=s.tenant_id AND id=s.invoice_plan_id),
 'invoice_reviewer_id',(SELECT reviewer_actor_id FROM reconforge.operational_finance_reviews WHERE tenant_id=s.tenant_id AND plan_id=s.invoice_plan_id),
 'collection_preparer_id',(SELECT preparer_actor_id FROM reconforge.operational_finance_plans WHERE tenant_id=s.tenant_id AND id=s.collection_plan_id),
 'collection_reviewer_id',(SELECT reviewer_actor_id FROM reconforge.operational_finance_reviews WHERE tenant_id=s.tenant_id AND plan_id=s.collection_plan_id)) ORDER BY t.created_version) tranches
 FROM reconforge.stock_commerce_tranches t JOIN reconforge.stock_sales_orders s ON s.tenant_id=t.tenant_id AND s.id=t.stock_order_id
 WHERE t.tenant_id=l.tenant_id AND t.order_id=l.order_id AND t.line_number=l.line_number) a ON TRUE
 WHERE l.tenant_id=d.tenant_id AND l.order_id=d.id),'[]'::jsonb)) $$;
CREATE FUNCTION reconforge.stock_commerce_progress(d reconforge.stock_commerce_orders) RETURNS JSONB LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
 -- Source lines and membership are immutable after their admitted command.
 -- Native Stock Sales changes require a strictly advancing guarded row version.
 -- Bind those authoritative changing rows without repeatedly copying 1000
 -- immutable source lines into the command acknowledgement hash.
 SELECT jsonb_build_array('stock-commerce-progress-v1',d.source_digest,COALESCE((
  SELECT jsonb_agg(jsonb_build_array(t.line_number,t.created_version,t.id,t.stock_order_id,s.row_version,s.status,
    s.source_digest,s.quantity_scaled,s.total_minor) ORDER BY t.created_version)
  FROM reconforge.stock_commerce_tranches t JOIN reconforge.stock_sales_orders s ON s.tenant_id=t.tenant_id AND s.id=t.stock_order_id
  WHERE t.tenant_id=d.tenant_id AND t.order_id=d.id),'[]'::jsonb)) $$;
CREATE FUNCTION reconforge.stock_commerce_ack(d reconforge.stock_commerce_orders) RETURNS JSONB LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
 SELECT jsonb_build_object('id',d.id,'number',d.number,'workspace_id',d.workspace_id,'organization_id',d.organization_id,
 'legal_entity_id',d.legal_entity_id,'currency_code',d.currency_code,'total_minor',d.total_minor::text,'line_count',d.line_count,
 'row_version',d.row_version,'status',d.status,'created_by',d.created_by,'approved_by',d.approved_by,'source_digest',d.source_digest,
 'progress_digest',reconforge.irp_digest(reconforge.stock_commerce_progress(d))) $$;
CREATE FUNCTION reconforge.stock_commerce_admit() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE d reconforge.stock_commerce_orders%ROWTYPE; a TEXT:=current_setting('app.stock_commerce_actor_id',true); p TEXT; q JSONB;
 seal JSONB;inputs JSONB;birth_count BIGINT;birth_total NUMERIC;birth_last INTEGER;
BEGIN
 IF TG_OP='DELETE' OR(TG_OP='UPDATE' AND TG_TABLE_NAME<>'stock_commerce_orders') THEN
  RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='stock_commerce_owner_phase',MESSAGE='Commercial source and evidence are immutable.';
 END IF;
 IF TG_TABLE_NAME='stock_commerce_orders' THEN d:=NEW;
 ELSE SELECT * INTO d FROM reconforge.stock_commerce_orders WHERE tenant_id=NEW.tenant_id AND id=NEW.order_id; END IF;
 p:=CASE WHEN current_setting('app.stock_commerce_operation',true) IN('approve','approve-tranche','review-issue','review-invoice','review-collection')
 THEN'sales.approve' ELSE'sales.manage' END;
 IF d IS NULL OR NOT reconforge.irp_scope(d.tenant_id,d.workspace_id,d.organization_id,d.legal_entity_id)
 OR NOT reconforge.sales_revenue_actor(d.tenant_id,a,p) THEN
  RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='stock_commerce_owner_phase',MESSAGE='Commercial command requires current scoped persisted human authority.';
 END IF;
 IF TG_TABLE_NAME='stock_commerce_orders' THEN
  IF(TG_OP='INSERT' AND(NEW.status<>'Draft' OR NEW.row_version<>1 OR NEW.created_by IS DISTINCT FROM a OR NEW.approved_by IS NOT NULL))
  OR(TG_OP='UPDATE' AND((to_jsonb(NEW)-ARRAY['status','row_version','approved_by']) IS DISTINCT FROM(to_jsonb(OLD)-ARRAY['status','row_version','approved_by'])
   OR NEW.row_version<>OLD.row_version+1
   OR NOT((OLD.status='Draft' AND NEW.status='Submitted') OR(OLD.status='Submitted' AND NEW.status='Approved') OR(OLD.status='Approved' AND NEW.status='Approved'))
   OR(OLD.approved_by IS NOT NULL AND NEW.approved_by IS DISTINCT FROM OLD.approved_by)
   OR(OLD.status='Submitted' AND(NEW.approved_by IS DISTINCT FROM a OR a=NEW.created_by)))) THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='stock_commerce_owner_phase',MESSAGE='Commercial terms or independent approval changed.';
  END IF;
  q:=NEW.source; PERFORM reconforge.irp_bounded(q);
  IF q->>'schema_version' IS DISTINCT FROM'stock-commerce-v1' OR q->>'number' IS DISTINCT FROM NEW.number
  OR q->>'currency_code' IS DISTINCT FROM NEW.currency_code OR(q->>'total_minor')::bigint IS DISTINCT FROM NEW.total_minor
  OR(q->>'line_count')::integer IS DISTINCT FROM NEW.line_count
  OR NOT EXISTS(SELECT 1 FROM reconforge.ar_customers c JOIN reconforge.legal_entities e ON e.tenant_id=c.tenant_id AND e.id=c.legal_entity_id
   WHERE c.tenant_id=NEW.tenant_id AND c.id=NEW.customer_id AND c.customer_code=q->>'customer_code'
   AND(c.workspace_id,c.organization_id,c.legal_entity_id,c.currency_code)=(NEW.workspace_id,NEW.organization_id,NEW.legal_entity_id,NEW.currency_code)
   AND e.currency_code=NEW.currency_code AND(TG_OP<>'INSERT' OR(c.status='Active' AND e.active))) THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='stock_commerce_owner_phase',MESSAGE='Commercial header differs from native customer and currency.';
  END IF;
 ELSIF TG_TABLE_NAME='stock_commerce_lines' THEN
  q:=NEW.source; PERFORM reconforge.irp_bounded(q);
  IF d.row_version<>1 OR EXISTS(SELECT 1 FROM reconforge.stock_commerce_commands WHERE tenant_id=d.tenant_id AND order_id=d.id AND version=1)
  OR q->>'schema_version' IS DISTINCT FROM'stock-sales-order-v1'
  OR q->>'number' IS DISTINCT FROM d.number OR q->>'customer_code' IS DISTINCT FROM d.source->>'customer_code'
  OR q->>'customer_reference' IS DISTINCT FROM d.source->>'customer_reference' OR q->>'order_date' IS DISTINCT FROM d.source->>'order_date'
  OR q->>'currency_code' IS DISTINCT FROM d.currency_code OR q->>'tax_minor' IS DISTINCT FROM'0'
  OR(q->>'quantity_scaled')::bigint IS DISTINCT FROM NEW.quantity_scaled
  OR(q->>'quantity')::numeric*power(10::numeric,NEW.quantity_precision) IS DISTINCT FROM NEW.quantity_scaled::numeric
  OR(q->>'total_minor')::bigint IS DISTINCT FROM NEW.total_minor
  OR(q->>'discount_basis_points')::integer NOT BETWEEN 0 AND 9999
  OR floor(((q->>'unit_price_minor')::numeric*(10000-(q->>'discount_basis_points')::integer)+5000)/10000)
    IS DISTINCT FROM(q->>'net_unit_price_minor')::numeric
  OR NEW.quantity_scaled::numeric*(q->>'net_unit_price_minor')::numeric/power(10::numeric,NEW.quantity_precision)
    IS DISTINCT FROM NEW.total_minor::numeric
  OR NOT EXISTS(SELECT 1 FROM reconforge.inventory_items i JOIN reconforge.inventory_units_of_measure u ON u.tenant_id=i.tenant_id AND u.id=i.uom_id
   JOIN reconforge.inventory_locations l ON l.tenant_id=i.tenant_id AND l.id=NEW.location_id
   JOIN reconforge.inventory_warehouses w ON w.tenant_id=l.tenant_id AND w.id=l.warehouse_id
   WHERE i.tenant_id=NEW.tenant_id AND i.id=NEW.item_id AND i.uom_id=NEW.uom_id AND u.decimal_places=NEW.quantity_precision
   AND i.item_code=q->>'item_code' AND w.warehouse_code=q->>'warehouse_code' AND l.location_code=q->>'location_code'
   AND i.workspace_id=d.workspace_id AND w.workspace_id=d.workspace_id AND w.organization_id=d.organization_id AND w.legal_entity_id=d.legal_entity_id
   AND(i.organization_id IS NULL OR i.organization_id=d.organization_id) AND i.active AND u.active AND l.active AND w.active
   AND NOT l.allow_negative AND i.tracking_mode='None' AND i.item_type<>'Service' AND i.inventory_account_id IS NOT NULL)
  OR NOT EXISTS(SELECT 1 FROM reconforge.ar_customers c WHERE c.tenant_id=d.tenant_id AND c.id=d.customer_id
   AND reconforge.sales_revenue_policy_matches(d.tenant_id,q->'monetary_policy',c.currency_code,c.currency_precision,c.currency_rounding_policy,
    c.currency_registry_version,c.currency_registry_digest)) THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='stock_commerce_owner_phase',MESSAGE='Commercial line requires exact reproducible native masters and minor units.';
  END IF;
 ELSIF TG_TABLE_NAME='stock_commerce_tranches' THEN
  IF d.status<>'Approved' OR NEW.created_version<>d.row_version
  OR EXISTS(SELECT 1 FROM reconforge.stock_commerce_commands WHERE tenant_id=d.tenant_id AND order_id=d.id AND version=d.row_version) THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='stock_commerce_owner_phase',MESSAGE='Delivery tranche requires approved current commercial owner.';
  END IF;
 ELSE
  IF NEW.actor_id IS DISTINCT FROM a OR NEW.workspace_id IS DISTINCT FROM d.workspace_id OR NEW.version<>d.row_version
  OR octet_length(NEW.request::text)>2097152 OR octet_length(NEW.result::text)>4194304
  OR reconforge.irp_digest(NEW.request) IS DISTINCT FROM NEW.request_digest
  OR reconforge.irp_digest(NEW.result) IS DISTINCT FROM NEW.result_digest
  OR NEW.result IS DISTINCT FROM reconforge.stock_commerce_ack(d) THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='stock_commerce_owner_phase',MESSAGE='Commercial evidence exceeds its exact actor, version or resource contract.';
  END IF;
  IF NEW.version=1 THEN
   -- The immutable first command is the birth seal. Every source line must
   -- exist and be admitted before it; no line can be appended afterwards,
   -- even within the same transaction or with immediate deferred constraints.
   SELECT jsonb_build_object('header',d.source,'lines',jsonb_agg(source ORDER BY line_number)),
    jsonb_agg(source-ARRAY['quantity_scaled','monetary_policy'] ORDER BY line_number),count(*),sum(total_minor),max(line_number)
   INTO seal,inputs,birth_count,birth_total,birth_last FROM reconforge.stock_commerce_lines WHERE tenant_id=d.tenant_id AND order_id=d.id;
   IF NEW.operation IS DISTINCT FROM'create' OR NEW.actor_id IS DISTINCT FROM d.created_by OR d.status<>'Draft'
   OR reconforge.irp_digest(seal) IS DISTINCT FROM d.source_digest
   OR birth_count<>d.line_count OR birth_last IS DISTINCT FROM d.line_count OR birth_total IS DISTINCT FROM d.total_minor::numeric
   OR NEW.request->'payload' IS DISTINCT FROM jsonb_build_object('header',d.source,'lines',inputs) THEN
    RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='stock_commerce_owner_phase',MESSAGE='Commercial birth requires complete independently admitted immutable lines and exact source seal.';
   END IF;
  END IF;
 END IF;
 RETURN NEW;
END $$;
DO $$ DECLARE n TEXT; BEGIN
 FOREACH n IN ARRAY ARRAY['stock_commerce_orders','stock_commerce_lines','stock_commerce_tranches','stock_commerce_commands'] LOOP
  EXECUTE format('CREATE TRIGGER stock_commerce_admission BEFORE INSERT OR UPDATE OR DELETE ON reconforge.%I FOR EACH ROW EXECUTE FUNCTION reconforge.stock_commerce_admit()',n);
  EXECUTE format('ALTER TABLE reconforge.%I ENABLE ROW LEVEL SECURITY',n); EXECUTE format('ALTER TABLE reconforge.%I FORCE ROW LEVEL SECURITY',n);
  IF n='stock_commerce_orders' THEN
   EXECUTE format('CREATE POLICY stock_commerce_scope ON reconforge.%I USING(reconforge.irp_scope(tenant_id,workspace_id,organization_id,legal_entity_id)) WITH CHECK(reconforge.irp_scope(tenant_id,workspace_id,organization_id,legal_entity_id))',n);
  ELSE
   EXECUTE format('CREATE POLICY stock_commerce_scope ON reconforge.%I USING(EXISTS(SELECT 1 FROM reconforge.stock_commerce_orders d WHERE d.tenant_id=%I.tenant_id AND d.id=%I.order_id AND reconforge.irp_scope(d.tenant_id,d.workspace_id,d.organization_id,d.legal_entity_id))) WITH CHECK(EXISTS(SELECT 1 FROM reconforge.stock_commerce_orders d WHERE d.tenant_id=%I.tenant_id AND d.id=%I.order_id AND reconforge.irp_scope(d.tenant_id,d.workspace_id,d.organization_id,d.legal_entity_id)))',n,n,n,n,n);
  END IF;
 END LOOP;
END $$;
CREATE FUNCTION reconforge.stock_commerce_close(t TEXT,target TEXT) RETURNS VOID LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE d reconforge.stock_commerce_orders%ROWTYPE; c RECORD; s RECORD; l RECORD; actual JSONB; child_id TEXT; child_operation TEXT;
BEGIN
 SELECT * INTO d FROM reconforge.stock_commerce_orders WHERE tenant_id=t AND id=target;
 IF d IS NULL OR NOT reconforge.irp_scope(d.tenant_id,d.workspace_id,d.organization_id,d.legal_entity_id) THEN
  RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='stock_commerce_owner_phase',MESSAGE='Commercial source is absent from current scope.';
 END IF;
 -- Immutable command admission validates each exact digest once, including
 -- the complete birth seal. Continuous closure still validates all phases,
 -- counts, conserved quantities and native participants at transaction end.
 IF(d.row_version>=3) IS DISTINCT FROM(d.approved_by IS NOT NULL)
 OR(SELECT count(*) FROM reconforge.stock_commerce_lines WHERE tenant_id=t AND order_id=target)<>d.line_count
 OR(SELECT sum(total_minor) FROM reconforge.stock_commerce_lines WHERE tenant_id=t AND order_id=target) IS DISTINCT FROM d.total_minor::numeric
 OR EXISTS(SELECT 1 FROM reconforge.stock_commerce_lines WHERE tenant_id=t AND order_id=target AND line_number>d.line_count)
 OR(SELECT count(*) FROM reconforge.stock_commerce_commands WHERE tenant_id=t AND order_id=target)<>d.row_version THEN
  RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='stock_commerce_owner_phase',MESSAGE='Commercial lines and commands require complete authoritative seal.';
 END IF;
 FOR c IN SELECT * FROM reconforge.stock_commerce_commands WHERE tenant_id=t AND order_id=target ORDER BY version LOOP
  IF c.request->>'id' IS DISTINCT FROM d.id OR c.request->>'actor_id' IS DISTINCT FROM c.actor_id OR c.request->>'operation' IS DISTINCT FROM c.operation
  OR c.request->'scope'->>'workspace_id' IS DISTINCT FROM d.workspace_id OR c.request->'scope'->>'organization_id' IS DISTINCT FROM d.organization_id
  OR c.request->'scope'->>'legal_entity_id' IS DISTINCT FROM d.legal_entity_id OR(c.result->>'row_version')::integer IS DISTINCT FROM c.version
  OR c.result->>'source_digest' IS DISTINCT FROM d.source_digest
  OR(c.version=1 AND(c.operation<>'create' OR c.actor_id<>d.created_by OR c.result->>'status'<>'Draft'
    OR c.request->'payload'->'header' IS DISTINCT FROM d.source))
  OR(c.version>1 AND(c.request->'payload'->>'expected_version')::integer IS DISTINCT FROM c.version-1)
  OR(c.version=2 AND(c.operation<>'submit' OR c.result->>'status'<>'Submitted'))
  OR(c.version=3 AND(c.operation<>'approve' OR c.actor_id=d.created_by OR c.actor_id IS DISTINCT FROM d.approved_by OR c.result->>'status'<>'Approved'))
  OR(c.version>3 AND(c.operation NOT IN('open-tranche','approve-tranche','prepare-issue','review-issue','deliver','prepare-invoice','review-invoice','invoice','prepare-collection','review-collection','collect','cancel') OR c.result->>'status'<>'Approved'))
  OR NOT EXISTS(SELECT 1 FROM reconforge.domain_audit_events a WHERE a.tenant_id=t AND a.id=c.audit_event_id AND a.actor_user_id=c.actor_id
    AND a.object_type='stock_commerce' AND a.object_id=d.id AND a.action='stock_commerce.'||c.operation
    AND(a.metadata_json->>'version')::integer=c.version AND a.metadata_json->>'source_digest'=d.source_digest) THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='stock_commerce_owner_phase',MESSAGE='Commercial command, actor, review and audit differ.';
  END IF;
  IF c.version>3 THEN
   child_id:=NULL;
   IF c.operation='open-tranche' THEN
    SELECT stock_order_id INTO child_id FROM reconforge.stock_commerce_tranches WHERE tenant_id=t AND order_id=target AND created_version=c.version;
    child_operation:='create';
   ELSE
    SELECT stock_order_id INTO child_id FROM reconforge.stock_commerce_tranches
      WHERE tenant_id=t AND order_id=target AND id=c.request->'payload'->>'tranche_id';
    child_operation:=CASE WHEN c.operation='approve-tranche' THEN'approve' ELSE c.operation END;
   END IF;
   IF child_id IS NULL OR NOT EXISTS(SELECT 1 FROM reconforge.stock_sales_commands nc WHERE nc.tenant_id=t
     AND nc.workspace_id=d.workspace_id AND nc.order_id=child_id AND nc.actor_id=c.actor_id AND nc.operation=child_operation
     AND nc.command_id='commerce-native:'||reconforge.irp_digest(jsonb_build_array(c.command_id,child_operation)))
   OR(c.operation IN('open-tranche','approve-tranche') AND NOT EXISTS(SELECT 1 FROM reconforge.stock_sales_commands nc WHERE nc.tenant_id=t
     AND nc.workspace_id=d.workspace_id AND nc.order_id=child_id AND nc.actor_id=c.actor_id
     AND nc.operation=CASE WHEN c.operation='open-tranche' THEN'submit' ELSE'reserve' END
     AND nc.command_id='commerce-native:'||reconforge.irp_digest(jsonb_build_array(c.command_id,
       CASE WHEN c.operation='open-tranche' THEN'submit' ELSE'reserve' END)))) THEN
    RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='stock_commerce_owner_phase',MESSAGE='Commercial operation must bind its exact atomic native stock command.';
   END IF;
  END IF;
 END LOOP;
 IF EXISTS(SELECT l.line_number FROM reconforge.stock_commerce_lines l
   LEFT JOIN reconforge.stock_commerce_tranches x ON x.tenant_id=l.tenant_id AND x.order_id=l.order_id AND x.line_number=l.line_number
   LEFT JOIN reconforge.stock_sales_orders n ON n.tenant_id=x.tenant_id AND n.id=x.stock_order_id AND n.status<>'Cancelled'
   WHERE l.tenant_id=t AND l.order_id=target GROUP BY l.line_number,l.quantity_scaled,l.total_minor
   HAVING coalesce(sum(n.quantity_scaled),0)>l.quantity_scaled OR coalesce(sum(n.total_minor),0)>l.total_minor) THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='stock_commerce_owner_phase',MESSAGE='Commercial line quantity and value cannot be overcommitted.';
 END IF;
 FOR s IN SELECT n.*,x.line_number,x.created_version FROM reconforge.stock_commerce_tranches x
   JOIN reconforge.stock_sales_orders n ON n.tenant_id=x.tenant_id AND n.id=x.stock_order_id WHERE x.tenant_id=t AND x.order_id=target LOOP
  SELECT * INTO l FROM reconforge.stock_commerce_lines WHERE tenant_id=t AND order_id=target AND line_number=s.line_number;
  IF(s.workspace_id,s.organization_id,s.legal_entity_id,s.customer_id,s.item_id,s.uom_id,s.location_id,s.currency_code,s.quantity_precision)
   IS DISTINCT FROM(d.workspace_id,d.organization_id,d.legal_entity_id,d.customer_id,l.item_id,l.uom_id,l.location_id,d.currency_code,l.quantity_precision)
  OR(s.source-ARRAY['number','quantity','quantity_scaled','total_minor']) IS DISTINCT FROM(l.source-ARRAY['number','quantity','quantity_scaled','total_minor'])
  OR s.number!~'^EC1\.[A-F0-9]{48}$' OR s.quantity_scaled::numeric*(s.source->>'net_unit_price_minor')::numeric/power(10::numeric,s.quantity_precision)
    IS DISTINCT FROM s.total_minor::numeric
  OR NOT EXISTS(SELECT 1 FROM reconforge.stock_commerce_commands x WHERE x.tenant_id=t AND x.order_id=target AND x.version=s.created_version
    AND x.operation='open-tranche' AND x.actor_id=s.created_by AND(x.request->'payload'->>'line_number')::integer=s.line_number
    AND(x.request->'payload'->>'quantity')::numeric*power(10::numeric,s.quantity_precision)=s.quantity_scaled) THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='stock_commerce_owner_phase',MESSAGE='Native stock tranche must retain its exact commercial line, amount and creation command.';
  END IF;
 END LOOP;
 SELECT * INTO c FROM reconforge.stock_commerce_commands WHERE tenant_id=t AND order_id=target AND version=d.row_version;
 actual:=reconforge.stock_commerce_ack(d);
 IF c.result IS DISTINCT FROM actual THEN
  RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='stock_commerce_owner_phase',MESSAGE='Native tranche changed outside its atomic commercial command.';
 END IF;
END $$;
CREATE FUNCTION reconforge.stock_commerce_close_trigger() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE target TEXT;
BEGIN
 IF TG_TABLE_NAME='stock_sales_orders' THEN
  SELECT order_id INTO target FROM reconforge.stock_commerce_tranches WHERE tenant_id=NEW.tenant_id AND stock_order_id=NEW.id;
  IF target IS NULL AND NEW.number LIKE'EC1.%' THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='stock_commerce_owner_phase',MESSAGE='Commercial tranche namespace requires its complete authoritative parent.';
  END IF;
 ELSIF TG_TABLE_NAME='stock_commerce_orders' THEN target:=NEW.id;
 ELSE target:=NEW.order_id; END IF;
 IF target IS NOT NULL THEN PERFORM reconforge.stock_commerce_close(NEW.tenant_id,target); END IF;
 RETURN NEW;
END $$;
DO $$ DECLARE n TEXT; BEGIN
 FOREACH n IN ARRAY ARRAY['stock_commerce_orders','stock_sales_orders'] LOOP
  EXECUTE format('CREATE CONSTRAINT TRIGGER stock_commerce_source_closure AFTER INSERT OR UPDATE ON reconforge.%I DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION reconforge.stock_commerce_close_trigger()',n);
 END LOOP;
END $$;
"""

DOWNGRADE_SQL = r"""
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM reconforge.stock_commerce_orders) THEN
  RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Commercial history exists; restore the retained backup instead of removing financial source evidence.';
 END IF;
END $$;
DROP TRIGGER stock_commerce_source_closure ON reconforge.stock_sales_orders;
DROP TRIGGER stock_commerce_source_closure ON reconforge.stock_commerce_orders;
DROP TRIGGER stock_commerce_admission ON reconforge.stock_commerce_orders;
DROP TABLE reconforge.stock_commerce_commands,reconforge.stock_commerce_tranches,reconforge.stock_commerce_lines;
DROP FUNCTION reconforge.stock_commerce_close_trigger(),reconforge.stock_commerce_close(TEXT,TEXT),reconforge.stock_commerce_admit();
DROP FUNCTION reconforge.stock_commerce_ack(reconforge.stock_commerce_orders),reconforge.stock_commerce_progress(reconforge.stock_commerce_orders),reconforge.stock_commerce_public(reconforge.stock_commerce_orders);
DROP TABLE reconforge.stock_commerce_orders;
"""
