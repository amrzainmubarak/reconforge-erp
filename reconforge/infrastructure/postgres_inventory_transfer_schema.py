"""IT1 ownership over native Transfer movements; no additional inventory ledger.

Install TABLES_SQL, the Root-owned finite quantity/native dispatcher extension,
then OWNER_SQL. All routines execute as the caller. Historical cost snapshots
retain complete approved IRP, FIFO and GL originals; posting consumes no layer.
"""

TABLES_SQL = r"""
CREATE TABLE reconforge.inventory_transfer_sources (
 tenant_id TEXT NOT NULL,id TEXT NOT NULL CHECK(id~'^IT1-S-[A-F0-9]{32}$'),
 workspace_id TEXT NOT NULL,organization_id TEXT NOT NULL,legal_entity_id TEXT NOT NULL,
 number TEXT NOT NULL,original_transfer_id TEXT,item_id TEXT NOT NULL,uom_id TEXT NOT NULL,
 quantity_precision INTEGER NOT NULL CHECK(quantity_precision BETWEEN 0 AND 6),
 quantity_scaled BIGINT NOT NULL CHECK(quantity_scaled BETWEEN 1 AND 9000000000000000000),
 from_location_id TEXT NOT NULL,to_location_id TEXT NOT NULL,period_id TEXT NOT NULL,posting_date DATE NOT NULL,
 payload JSONB NOT NULL CHECK(octet_length(payload::text)<=4194304),source_digest TEXT NOT NULL CHECK(source_digest~'^[a-f0-9]{64}$'),
 phase SMALLINT NOT NULL DEFAULT 0 CHECK(phase BETWEEN 0 AND 3),row_version INTEGER NOT NULL DEFAULT 1 CHECK(row_version BETWEEN 1 AND 3),
 creator_actor_id TEXT NOT NULL,reviewer_actor_id TEXT,poster_actor_id TEXT,
 review_cost_json JSONB,review_cost_digest TEXT,native_movement_id TEXT NOT NULL,native_creation_json JSONB NOT NULL,posted_native_json JSONB,
 PRIMARY KEY(tenant_id,id),UNIQUE(tenant_id,workspace_id,number),UNIQUE(tenant_id,native_movement_id),
 UNIQUE(tenant_id,id,workspace_id,organization_id,legal_entity_id),CHECK(from_location_id<>to_location_id),
 CHECK((review_cost_json IS NULL)=(review_cost_digest IS NULL)),
 FOREIGN KEY(tenant_id,workspace_id) REFERENCES reconforge.domain_workspaces(tenant_id,id),
 FOREIGN KEY(tenant_id,organization_id) REFERENCES reconforge.organizations(tenant_id,id),
 FOREIGN KEY(tenant_id,legal_entity_id) REFERENCES reconforge.legal_entities(tenant_id,id),
 FOREIGN KEY(tenant_id,original_transfer_id) REFERENCES reconforge.inventory_transfer_sources(tenant_id,id),
 FOREIGN KEY(tenant_id,item_id) REFERENCES reconforge.inventory_items(tenant_id,id),
 FOREIGN KEY(tenant_id,uom_id) REFERENCES reconforge.inventory_units_of_measure(tenant_id,id),
 FOREIGN KEY(tenant_id,from_location_id) REFERENCES reconforge.inventory_locations(tenant_id,id),
 FOREIGN KEY(tenant_id,to_location_id) REFERENCES reconforge.inventory_locations(tenant_id,id),
 FOREIGN KEY(tenant_id,period_id) REFERENCES reconforge.fiscal_periods(tenant_id,id),
 FOREIGN KEY(tenant_id,creator_actor_id) REFERENCES reconforge.identity_users(tenant_id,id),
 FOREIGN KEY(tenant_id,reviewer_actor_id) REFERENCES reconforge.identity_users(tenant_id,id),
 FOREIGN KEY(tenant_id,poster_actor_id) REFERENCES reconforge.identity_users(tenant_id,id),
 FOREIGN KEY(tenant_id,native_movement_id) REFERENCES reconforge.inventory_movements(tenant_id,id) DEFERRABLE INITIALLY DEFERRED
);
CREATE UNIQUE INDEX inventory_transfer_one_inverse ON reconforge.inventory_transfer_sources(tenant_id,original_transfer_id)
 WHERE original_transfer_id IS NOT NULL AND phase<>3;
CREATE TABLE reconforge.inventory_transfer_claims (
 tenant_id TEXT NOT NULL,id TEXT NOT NULL CHECK(id~'^IT1-K-[A-F0-9]{32}$'),transfer_id TEXT NOT NULL,
 workspace_id TEXT NOT NULL,organization_id TEXT NOT NULL,legal_entity_id TEXT NOT NULL,
 item_id TEXT NOT NULL,uom_id TEXT NOT NULL,quantity_precision INTEGER NOT NULL CHECK(quantity_precision BETWEEN 0 AND 6),
 location_id TEXT NOT NULL,quantity_scaled BIGINT NOT NULL CHECK(quantity_scaled BETWEEN 1 AND 9000000000000000000),
 state TEXT NOT NULL DEFAULT 'Active' CHECK(state IN('Active','Posted','Released')),created_version INTEGER NOT NULL CHECK(created_version=2),
 PRIMARY KEY(tenant_id,id),UNIQUE(tenant_id,transfer_id),UNIQUE(tenant_id,id,transfer_id,workspace_id,organization_id,legal_entity_id),
 FOREIGN KEY(tenant_id,transfer_id,workspace_id,organization_id,legal_entity_id)
 REFERENCES reconforge.inventory_transfer_sources(tenant_id,id,workspace_id,organization_id,legal_entity_id)
);
CREATE TABLE reconforge.inventory_transfer_releases (
 tenant_id TEXT NOT NULL,id TEXT NOT NULL CHECK(id~'^IT1-R-[A-F0-9]{32}$'),transfer_id TEXT NOT NULL,claim_id TEXT NOT NULL,
 workspace_id TEXT NOT NULL,organization_id TEXT NOT NULL,legal_entity_id TEXT NOT NULL,
 purpose TEXT NOT NULL CHECK(purpose IN('Post','Cancel')),target_movement_id TEXT,actor_id TEXT NOT NULL,reason TEXT NOT NULL,
 created_version INTEGER NOT NULL CHECK(created_version=3),PRIMARY KEY(tenant_id,id),UNIQUE(tenant_id,claim_id),
 CHECK((purpose='Post')=(target_movement_id IS NOT NULL)),
 FOREIGN KEY(tenant_id,claim_id,transfer_id,workspace_id,organization_id,legal_entity_id)
 REFERENCES reconforge.inventory_transfer_claims(tenant_id,id,transfer_id,workspace_id,organization_id,legal_entity_id),
 FOREIGN KEY(tenant_id,target_movement_id) REFERENCES reconforge.inventory_movements(tenant_id,id),
 FOREIGN KEY(tenant_id,actor_id) REFERENCES reconforge.identity_users(tenant_id,id)
);
CREATE TABLE reconforge.inventory_transfer_events (
 tenant_id TEXT NOT NULL,transfer_id TEXT NOT NULL,version INTEGER NOT NULL CHECK(version BETWEEN 1 AND 3),
 operation TEXT NOT NULL CHECK(operation IN('create','inverse-create','review','post','cancel')),actor_id TEXT NOT NULL,
 request_json JSONB NOT NULL,request_digest TEXT NOT NULL,reason TEXT NOT NULL,audit_event_id TEXT NOT NULL,outbox_event_id TEXT NOT NULL,
 PRIMARY KEY(tenant_id,transfer_id,version),UNIQUE(tenant_id,audit_event_id),UNIQUE(tenant_id,outbox_event_id),
 FOREIGN KEY(tenant_id,transfer_id) REFERENCES reconforge.inventory_transfer_sources(tenant_id,id),
 FOREIGN KEY(tenant_id,actor_id) REFERENCES reconforge.identity_users(tenant_id,id),
 FOREIGN KEY(tenant_id,audit_event_id) REFERENCES reconforge.domain_audit_events(tenant_id,id),
 FOREIGN KEY(tenant_id,outbox_event_id) REFERENCES reconforge.outbox_events(tenant_id,event_id)
);
CREATE TABLE reconforge.inventory_transfer_commands (
 tenant_id TEXT NOT NULL,workspace_id TEXT NOT NULL,command_id TEXT NOT NULL CHECK(length(command_id) BETWEEN 1 AND 140),
 transfer_id TEXT NOT NULL,version INTEGER NOT NULL,operation TEXT NOT NULL,actor_id TEXT NOT NULL,
 request_json JSONB NOT NULL,request_digest TEXT NOT NULL,response_json JSONB NOT NULL CHECK(octet_length(response_json::text)<=8388608),
 PRIMARY KEY(tenant_id,workspace_id,command_id),UNIQUE(tenant_id,transfer_id,version),
 FOREIGN KEY(tenant_id,transfer_id,version) REFERENCES reconforge.inventory_transfer_events(tenant_id,transfer_id,version)
);
"""

OWNER_SQL = r"""
CREATE FUNCTION reconforge.it1_assert(valid BOOLEAN,message TEXT) RETURNS VOID
 LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog AS $it1$
BEGIN IF valid IS DISTINCT FROM TRUE THEN RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='inventory_transfer_owner',MESSAGE=message;END IF;END $it1$;
CREATE FUNCTION reconforge.it1_visible(t TEXT,i TEXT) RETURNS BOOLEAN LANGUAGE sql STABLE SET search_path=pg_catalog AS $it1$
 SELECT EXISTS(SELECT 1 FROM reconforge.inventory_transfer_sources s WHERE s.tenant_id=t AND s.id=i
 AND reconforge.irp_scope(s.tenant_id,s.workspace_id,s.organization_id,s.legal_entity_id)) $it1$;
CREATE FUNCTION reconforge.it1_cost_snapshot(t TEXT,w TEXT,o TEXT,e TEXT,i TEXT) RETURNS JSONB
 LANGUAGE plpgsql STABLE SET search_path=pg_catalog AS $it1$
DECLARE layer RECORD;p RECORD;document RECORD;entry RECORD;line RECORD;policy JSONB;sources JSONB:='[]'::jsonb;
 quantities NUMERIC:=0;values_minor NUMERIC:=0;amounts JSONB;original JSONB;lines JSONB;consumptions JSONB;
 consumed_quantity NUMERIC;consumed_value NUMERIC;history_count INTEGER:=0;
BEGIN
 PERFORM reconforge.it1_assert(reconforge.irp_scope(t,w,o,e),'Transfer cost requires the original scoped hierarchy');
 FOR layer IN SELECT * FROM reconforge.inventory_cost_layers WHERE tenant_id=t AND workspace_id=w AND legal_entity_id=e AND item_id=i
 ORDER BY created_at,id LOOP
  PERFORM reconforge.it1_assert(jsonb_array_length(sources)<32 AND layer.inventory_lot_id IS NULL,'Transfer requires at most 32 complete untracked approved cost sources');
  SELECT * INTO p FROM reconforge.inventory_receipt_plans WHERE tenant_id=t AND cost_layer_id=layer.id AND operation='Receipt';
  PERFORM reconforge.it1_assert(p.id IS NOT NULL AND(p.workspace_id,p.organization_id,p.legal_entity_id,p.item_id,p.uom_id,p.quantity_precision)
   =(w,o,e,i,layer.uom_id,layer.quantity_precision),'Every transfer layer requires its exact original posted IRP cost owner');
  PERFORM reconforge.irp_assert_complete(t,p.id,TRUE);
  PERFORM reconforge.it1_assert(NOT EXISTS(SELECT 1 FROM reconforge.inventory_receipt_plans inverse
   WHERE inverse.tenant_id=t AND inverse.original_plan_id=p.id AND inverse.operation='FullReceiptReversal')
   AND NOT EXISTS(SELECT 1 FROM reconforge.finance_posting_effects inverse WHERE inverse.tenant_id=t AND inverse.reverses_effect_id=p.posting_effect_id),
   'A transfer cannot adopt a cost source with a retained pending or committed complete receipt inverse');
  PERFORM reconforge.it1_assert(NOT EXISTS(SELECT 1 FROM reconforge.inventory_valuation_reversal_effects correction
   WHERE correction.tenant_id=t AND correction.cost_layer_id=layer.id),
   'First IT1 cost scope refuses retained valuation correction owners until their complete original contract is supported');
  SELECT * INTO document FROM reconforge.inventory_valuation_documents WHERE tenant_id=t AND id=p.valuation_document_id;
  SELECT * INTO entry FROM reconforge.finance_entries WHERE tenant_id=t AND id=p.finance_entry_id;
  SELECT * INTO line FROM reconforge.inventory_valuation_lines WHERE tenant_id=t AND id=p.valuation_line_id;
  PERFORM reconforge.it1_assert(document.status='Approved' AND line.flow_direction='Inbound'
   AND(layer.source_valuation_line_id,layer.original_quantity_scaled,layer.original_value_minor,layer.currency_code)
   =(line.id,line.quantity_scaled,line.value_minor,p.currency_code),'Transfer cost must retain approved inbound FIFO ownership');
  PERFORM reconforge.it1_assert(EXISTS(SELECT 1 FROM reconforge.inventory_items item JOIN reconforge.inventory_units_of_measure u
   ON u.tenant_id=item.tenant_id AND u.id=item.uom_id WHERE item.tenant_id=t AND item.id=i AND item.workspace_id=w
   AND(item.organization_id IS NULL OR item.organization_id=o) AND item.active AND u.active AND item.item_type IN('Stock','Consumable')
   AND item.tracking_mode='None' AND(item.uom_id,u.decimal_places,item.inventory_account_id)
   =(layer.uom_id,layer.quantity_precision,line.inventory_account_id)),
   'Current transfer cost must retain its active original scoped base unit and inventory account');
  IF policy IS NULL THEN policy:=p.plan_json->'currency_policy';END IF;
  PERFORM reconforge.it1_assert(policy=p.plan_json->'currency_policy','Transfer originals require one exact captured currency policy');
  SELECT COALESCE(jsonb_agg(to_jsonb(l) ORDER BY l.line_number,l.id),'[]'::jsonb) INTO lines
   FROM reconforge.finance_entry_lines l WHERE l.tenant_id=t AND l.entry_id=entry.id;
  SELECT COALESCE(jsonb_agg(to_jsonb(c) ORDER BY c.id),'[]'::jsonb) INTO consumptions
   FROM reconforge.inventory_layer_consumptions c WHERE c.tenant_id=t AND c.cost_layer_id=layer.id;
  history_count:=history_count+jsonb_array_length(consumptions);
  SELECT COALESCE(sum(c.quantity_scaled),0),COALESCE(sum(c.value_minor),0) INTO consumed_quantity,consumed_value
   FROM reconforge.inventory_layer_consumptions c WHERE c.tenant_id=t AND c.cost_layer_id=layer.id;
  PERFORM reconforge.it1_assert(history_count<=200 AND layer.remaining_quantity_scaled=layer.original_quantity_scaled-consumed_quantity
   AND layer.remaining_value_minor=layer.original_value_minor-consumed_value
   AND NOT EXISTS(SELECT 1 FROM reconforge.inventory_layer_consumptions c LEFT JOIN reconforge.inventory_valuation_lines detail
    ON detail.tenant_id=c.tenant_id AND detail.id=c.valuation_line_id LEFT JOIN reconforge.inventory_valuation_documents consumed_document
    ON consumed_document.tenant_id=detail.tenant_id AND consumed_document.id=detail.valuation_document_id WHERE c.tenant_id=t AND c.cost_layer_id=layer.id
    AND(consumed_document.status IS DISTINCT FROM 'Approved' OR detail.flow_direction IS DISTINCT FROM 'Outbound'
     OR(detail.item_id,detail.uom_id,detail.quantity_precision,detail.inventory_lot_id)
      IS DISTINCT FROM(layer.item_id,layer.uom_id,layer.quantity_precision,layer.inventory_lot_id))),
   'Transfer captures all bounded immutable approved consumption facts and exact residual quantity/value conservation');
  amounts:=jsonb_build_array(layer.original_value_minor,layer.remaining_value_minor,document.total_value_minor,
   line.value_minor,p.total_value_minor,entry.total_debit_minor,entry.total_credit_minor);
  SELECT amounts||COALESCE(jsonb_agg(l.debit_minor ORDER BY l.line_number),'[]'::jsonb)
   ||COALESCE(jsonb_agg(l.credit_minor ORDER BY l.line_number),'[]'::jsonb) INTO amounts
   FROM reconforge.finance_entry_lines l WHERE l.tenant_id=t AND l.entry_id=entry.id;
  SELECT jsonb_build_object('layer',to_jsonb(layer),'valuation_document',to_jsonb(document),'valuation_line',to_jsonb(line),
   'receipt_plan',p.plan_json,'receipt_link',to_jsonb(link),'receipt_review',review.review_json,
   'finance_entry',to_jsonb(entry),'finance_lines',lines,'posting_effect',to_jsonb(effect),
   'receipt_native',reconforge.it1_native_snapshot(t,p.movement_id),'valuation_input',to_jsonb(input),
   'consumptions',consumptions,'exposed_amounts_minor',amounts) INTO original
   FROM reconforge.inventory_receipt_links link JOIN reconforge.inventory_receipt_reviews review
   ON review.tenant_id=link.tenant_id AND review.id=link.review_id JOIN reconforge.finance_posting_effects effect
   ON effect.tenant_id=link.tenant_id AND effect.id=link.posting_effect_id JOIN reconforge.inventory_valuation_input_costs input
   ON input.tenant_id=p.tenant_id AND input.id=p.input_cost_id WHERE link.tenant_id=t AND link.plan_id=p.id;
  PERFORM reconforge.it1_assert(original IS NOT NULL,'Transfer cost needs actual posted receipt, review and GL effect originals');
  sources:=sources||jsonb_build_array(original);quantities:=quantities+layer.remaining_quantity_scaled;values_minor:=values_minor+layer.remaining_value_minor;
 END LOOP;
 PERFORM reconforge.it1_assert(jsonb_array_length(sources) BETWEEN 1 AND 32 AND quantities BETWEEN 1 AND 9000000000000000000
  AND values_minor BETWEEN 1 AND 9000000000000000000,'Transfer needs a bounded complete positive approved entity FIFO pool');
 RETURN jsonb_build_object('schema_version','inventory-transfer-cost-v1','monetary_policy',policy,
  'remaining_quantity_scaled',quantities,'remaining_value_minor',values_minor,'sources',sources);
END $it1$;
CREATE FUNCTION reconforge.it1_native_snapshot(t TEXT,i TEXT) RETURNS JSONB LANGUAGE sql STABLE SET search_path=pg_catalog AS $it1$
 SELECT jsonb_build_object('head',to_jsonb(m),'lines',COALESCE((SELECT jsonb_agg(to_jsonb(l) ORDER BY l.line_number,l.id)
  FROM reconforge.inventory_movement_lines l WHERE l.tenant_id=t AND l.movement_id=i),'[]'::jsonb),
  'audit',COALESCE((SELECT jsonb_agg(to_jsonb(a) ORDER BY a.sequence,a.id) FROM reconforge.domain_audit_events a
   WHERE a.tenant_id=t AND a.object_type='inventory_movement' AND a.object_id=i),'[]'::jsonb),
  'outbox',COALESCE((SELECT jsonb_agg(to_jsonb(b) ORDER BY b.event_id) FROM reconforge.outbox_events b
   WHERE b.tenant_id=t AND b.aggregate_type='inventory_movement' AND b.aggregate_id=i),'[]'::jsonb))
 FROM reconforge.inventory_movements m WHERE m.tenant_id=t AND m.id=i $it1$;
CREATE FUNCTION reconforge.it1_public(t TEXT,i TEXT,v INTEGER) RETURNS JSONB LANGUAGE plpgsql STABLE SET search_path=pg_catalog AS $it1$
DECLARE s RECORD;phase INTEGER:=0;reviewer TEXT;poster TEXT;claim JSONB;release JSONB;
BEGIN
 SELECT * INTO s FROM reconforge.inventory_transfer_sources WHERE tenant_id=t AND id=i;
 IF s.id IS NULL OR v NOT BETWEEN 1 AND s.row_version THEN RETURN NULL;END IF;
 SELECT actor_id INTO reviewer FROM reconforge.inventory_transfer_events WHERE tenant_id=t AND transfer_id=i AND operation='review' AND version<=v;
 IF reviewer IS NOT NULL THEN phase:=1;END IF;
 SELECT actor_id INTO poster FROM reconforge.inventory_transfer_events WHERE tenant_id=t AND transfer_id=i AND operation='post' AND version<=v;
 IF poster IS NOT NULL THEN phase:=2;END IF;
 IF EXISTS(SELECT 1 FROM reconforge.inventory_transfer_events WHERE tenant_id=t AND transfer_id=i AND operation='cancel' AND version<=v) THEN phase:=3;END IF;
 SELECT to_jsonb(c)||jsonb_build_object('state',CASE WHEN r.id IS NULL THEN'Active' WHEN r.purpose='Post' THEN'Posted' ELSE'Released' END)
 INTO claim FROM reconforge.inventory_transfer_claims c LEFT JOIN reconforge.inventory_transfer_releases r
 ON r.tenant_id=c.tenant_id AND r.claim_id=c.id AND r.created_version<=v WHERE c.tenant_id=t AND c.transfer_id=i AND c.created_version<=v;
 SELECT to_jsonb(r) INTO release FROM reconforge.inventory_transfer_releases r WHERE r.tenant_id=t AND r.transfer_id=i AND r.created_version<=v;
 RETURN s.payload||jsonb_build_object('source_digest',s.source_digest,'phase',phase,'row_version',v,
  'reviewer_actor_id',reviewer,'poster_actor_id',poster,'review_cost_snapshot',CASE WHEN reviewer IS NOT NULL THEN s.review_cost_json ELSE NULL END,
  'review_cost_digest',CASE WHEN reviewer IS NOT NULL THEN s.review_cost_digest ELSE NULL END,'claim',claim,'release',release,
  'native_response',CASE WHEN phase=2 THEN s.posted_native_json ELSE s.native_creation_json END);
END $it1$;
CREATE FUNCTION reconforge.it1_evidence(t TEXT,i TEXT,v INTEGER) RETURNS TEXT LANGUAGE plpgsql STABLE SET search_path=pg_catalog AS $it1$
DECLARE s RECORD;e RECORD;c RECORD;metadata JSONB;source JSONB;request JSONB;expected JSONB;
BEGIN
 SELECT * INTO s FROM reconforge.inventory_transfer_sources WHERE tenant_id=t AND id=i;
 SELECT * INTO e FROM reconforge.inventory_transfer_events WHERE tenant_id=t AND transfer_id=i AND version=v;
 SELECT * INTO c FROM reconforge.inventory_transfer_commands WHERE tenant_id=t AND transfer_id=i AND version=v;
 source:=reconforge.it1_public(t,i,v);request:=c.request_json->'request';
 PERFORM reconforge.it1_assert(e.transfer_id IS NOT NULL AND c.transfer_id IS NOT NULL AND source IS NOT NULL
  AND(c.workspace_id,c.operation,c.actor_id,c.request_json,c.request_digest)=(s.workspace_id,e.operation,e.actor_id,e.request_json,e.request_digest)
  AND c.request_digest=reconforge.irp_digest(c.request_json)
  AND c.request_json=jsonb_build_object('operation',e.operation,'actor_id',e.actor_id,'request',request)
  AND c.response_json=jsonb_build_object('source',source,'native_response',source->'native_response'),
  'Transfer ACK needs its complete immutable original actor, request, historical phase and native response');
 IF e.operation IN('create','inverse-create') THEN
  expected:=s.payload->'command_request';PERFORM reconforge.it1_assert(v=1 AND e.actor_id=s.creator_actor_id AND request=expected,
   'Transfer creation receipt must bind the retained submitted body and creator');
 ELSE
  expected:=jsonb_build_object('id',i,'expected_digest',s.source_digest,'expected_version',v-1,'reason',e.reason);
  PERFORM reconforge.it1_assert(request=expected AND((e.operation='review' AND v=2 AND e.actor_id=s.reviewer_actor_id)
   OR(e.operation='post' AND v=3 AND e.actor_id=s.poster_actor_id) OR(e.operation='cancel' AND v IN(2,3))),
   'Transfer phase receipt must bind the original subject, digest and requested version');
 END IF;
 metadata:=jsonb_build_object('source_digest',s.source_digest,'version',v,'operation',e.operation,'reason',e.reason);
 PERFORM reconforge.it1_assert(EXISTS(SELECT 1 FROM reconforge.domain_audit_events audit JOIN reconforge.outbox_events event
  ON event.tenant_id=audit.tenant_id WHERE audit.tenant_id=t AND audit.id=e.audit_event_id AND event.event_id=e.outbox_event_id
  AND audit.actor_user_id=e.actor_id AND audit.object_type='inventory_transfer' AND audit.object_id=i
  AND audit.action='inventory_transfer.'||e.operation AND audit.metadata_json=metadata
  AND event.aggregate_type='inventory_transfer' AND event.aggregate_id=i AND event.event_type=audit.action
  AND(event.workspace_id,event.organization_id,event.legal_entity_id)=(s.workspace_id,s.organization_id,s.legal_entity_id)
  AND event.payload=metadata||jsonb_build_object('audit_event_id',audit.id)),
  'Transfer command must retain exact source audit and scoped outbox membership');RETURN e.actor_id;
END $it1$;
CREATE FUNCTION reconforge.it1_cost_originals(t TEXT,cost JSONB) RETURNS VOID LANGUAGE plpgsql STABLE SET search_path=pg_catalog AS $it1$
DECLARE original JSONB;p RECORD;layer RECORD;actual JSONB;consumption JSONB;consumed_quantity NUMERIC;consumed_value NUMERIC;history_count INTEGER:=0;
 quantity_total NUMERIC:=0;value_total NUMERIC:=0;
BEGIN
 PERFORM reconforge.it1_assert(cost->>'schema_version'='inventory-transfer-cost-v1'
  AND jsonb_array_length(cost->'sources') BETWEEN 1 AND 32
  AND(SELECT count(DISTINCT value#>>'{layer,id}') FROM jsonb_array_elements(cost->'sources'))=jsonb_array_length(cost->'sources'),
  'Transfer retains a bounded complete unique approved cost-source population');
 FOR original IN SELECT value FROM jsonb_array_elements(cost->'sources') LOOP
  SELECT * INTO p FROM reconforge.inventory_receipt_plans WHERE tenant_id=t AND id=original#>>'{receipt_plan,plan_id}';
  PERFORM reconforge.it1_assert(p.id IS NOT NULL AND p.operation='Receipt' AND p.plan_json=original->'receipt_plan'
   AND p.plan_json->'currency_policy'=cost->'monetary_policy','Transfer original receipt and captured monetary policy must remain exact');
  PERFORM reconforge.irp_assert_complete(t,p.id,TRUE);
  SELECT * INTO layer FROM reconforge.inventory_cost_layers WHERE tenant_id=t AND id=p.cost_layer_id;
  PERFORM reconforge.it1_assert((to_jsonb(layer)-ARRAY['remaining_quantity_scaled','remaining_value_minor','row_version'])
   =((original->'layer')-ARRAY['remaining_quantity_scaled','remaining_value_minor','row_version']),
   'Transfer original FIFO identity and approved cost must remain unchanged');
  PERFORM reconforge.it1_assert(jsonb_typeof(original->'consumptions')='array','Transfer retains an exact immutable consumption history population');
  PERFORM reconforge.it1_assert((SELECT count(DISTINCT value->>'id') FROM jsonb_array_elements(original->'consumptions'))
   =jsonb_array_length(original->'consumptions'),'Transfer historical consumption membership cannot duplicate an original native fact');
  history_count:=history_count+jsonb_array_length(original->'consumptions');consumed_quantity:=0;consumed_value:=0;
  FOR consumption IN SELECT value FROM jsonb_array_elements(original->'consumptions') LOOP
   PERFORM reconforge.it1_assert(consumption->>'cost_layer_id'=layer.id AND EXISTS(SELECT 1 FROM reconforge.inventory_layer_consumptions c
    WHERE c.tenant_id=t AND c.id=consumption->>'id' AND to_jsonb(c)=consumption),
    'Every captured historical consumption must retain its exact original native byte and layer membership');
   consumed_quantity:=consumed_quantity+(consumption->>'quantity_scaled')::numeric;
   consumed_value:=consumed_value+(consumption->>'value_minor')::numeric;
  END LOOP;
  PERFORM reconforge.it1_assert(history_count<=200 AND(original#>>'{layer,remaining_quantity_scaled}')::numeric
   =(original#>>'{layer,original_quantity_scaled}')::numeric-consumed_quantity
   AND(original#>>'{layer,remaining_value_minor}')::numeric=(original#>>'{layer,original_value_minor}')::numeric-consumed_value,
   'Captured transfer residuals must derive independently from all retained original consumption facts');
  quantity_total:=quantity_total+(original#>>'{layer,remaining_quantity_scaled}')::numeric;
  value_total:=value_total+(original#>>'{layer,remaining_value_minor}')::numeric;
  SELECT jsonb_build_object('valuation_document',to_jsonb(d),'valuation_line',to_jsonb(l),'receipt_link',to_jsonb(link),
   'receipt_review',review.review_json,'finance_entry',to_jsonb(entry),'posting_effect',to_jsonb(effect),
   'receipt_native',reconforge.it1_native_snapshot(t,p.movement_id),'valuation_input',to_jsonb(input),
   'finance_lines',(SELECT jsonb_agg(to_jsonb(fl) ORDER BY fl.line_number,fl.id) FROM reconforge.finance_entry_lines fl
   WHERE fl.tenant_id=t AND fl.entry_id=p.finance_entry_id)) INTO actual
   FROM reconforge.inventory_valuation_documents d JOIN reconforge.inventory_valuation_lines l ON l.tenant_id=d.tenant_id AND l.id=p.valuation_line_id
   JOIN reconforge.inventory_receipt_links link ON link.tenant_id=d.tenant_id AND link.plan_id=p.id
   JOIN reconforge.inventory_receipt_reviews review ON review.tenant_id=link.tenant_id AND review.id=link.review_id
   JOIN reconforge.finance_entries entry ON entry.tenant_id=d.tenant_id AND entry.id=p.finance_entry_id
   JOIN reconforge.finance_posting_effects effect ON effect.tenant_id=entry.tenant_id AND effect.id=p.posting_effect_id
   JOIN reconforge.inventory_valuation_input_costs input ON input.tenant_id=p.tenant_id AND input.id=p.input_cost_id WHERE d.tenant_id=t AND d.id=p.valuation_document_id;
  PERFORM reconforge.it1_assert(actual=original-ARRAY['layer','receipt_plan','consumptions','exposed_amounts_minor'],
   'Transfer approved valuation, posted GL and immutable native effects must retain original bytes');
 END LOOP;
 PERFORM reconforge.it1_assert(quantity_total=(cost->>'remaining_quantity_scaled')::numeric AND value_total=(cost->>'remaining_value_minor')::numeric,
  'Transfer captured pool totals must equal its complete unique original layer residual population');
END $it1$;
CREATE FUNCTION reconforge.it1_close(t TEXT,i TEXT) RETURNS VOID LANGUAGE plpgsql SET search_path=pg_catalog AS $it1$
DECLARE s RECORD;original RECORD;c RECORD;r RECORD;native JSONB;created JSONB;line JSONB;v INTEGER;event RECORD;phase INTEGER:=0;
 expected_actor TEXT;policy JSONB;
BEGIN
 SELECT * INTO s FROM reconforge.inventory_transfer_sources WHERE tenant_id=t AND id=i;
 PERFORM reconforge.it1_assert(s.id IS NOT NULL AND reconforge.irp_scope(t,s.workspace_id,s.organization_id,s.legal_entity_id)
  AND s.source_digest=reconforge.irp_digest(s.payload) AND s.payload->>'id'=s.id
  AND s.payload->>'schema_version'='inventory-transfer-v1'
  AND s.payload->'scope'=jsonb_build_object('workspace_id',s.workspace_id,'organization_id',s.organization_id,'legal_entity_id',s.legal_entity_id)
  AND s.payload->>'creator_actor_id'=s.creator_actor_id
  AND(s.payload->>'item_id',s.payload->>'uom_id',(s.payload->>'quantity_precision')::integer,(s.payload->>'quantity_scaled')::bigint,
   s.payload->>'from_location_id',s.payload->>'to_location_id',s.payload->>'period_id',(s.payload->>'posting_date')::date,
   s.payload->>'number',s.payload->>'native_movement_id')
  =(s.item_id,s.uom_id,s.quantity_precision,s.quantity_scaled,s.from_location_id,s.to_location_id,s.period_id,s.posting_date,s.number,s.native_movement_id),
  'Transfer source must bind its exact immutable hierarchy, master quantities, date and native identity');
 PERFORM reconforge.it1_cost_originals(t,s.payload->'cost_snapshot');
 PERFORM reconforge.it1_assert(NOT EXISTS(SELECT 1 FROM jsonb_array_elements(s.payload#>'{cost_snapshot,sources}') original_source
  WHERE(original_source#>>'{layer,workspace_id}',original_source#>>'{layer,legal_entity_id}',original_source#>>'{layer,item_id}',
   original_source#>>'{layer,uom_id}',(original_source#>>'{layer,quantity_precision}')::integer,
   original_source#>>'{receipt_plan,scope,organization_id}') IS DISTINCT FROM(s.workspace_id,s.legal_entity_id,s.item_id,s.uom_id,s.quantity_precision,s.organization_id)),
  'Every transfer original cost layer must belong to the exact source item, base unit and parent hierarchy');
 IF s.review_cost_json IS NOT NULL THEN
  PERFORM reconforge.it1_assert(s.review_cost_digest=reconforge.irp_digest(s.review_cost_json)
   AND s.review_cost_json->'monetary_policy'=s.payload#>'{cost_snapshot,monetary_policy}',
   'Review freezes one exact complete current pool under the original captured monetary policy');
  PERFORM reconforge.it1_cost_originals(t,s.review_cost_json);
 END IF;
 IF s.original_transfer_id IS NOT NULL THEN
  SELECT * INTO original FROM reconforge.inventory_transfer_sources WHERE tenant_id=t AND id=s.original_transfer_id;
  PERFORM reconforge.it1_assert(original.id IS NOT NULL AND original.phase=2 AND original.original_transfer_id IS NULL
   AND(original.workspace_id,original.organization_id,original.legal_entity_id,original.item_id,original.uom_id,
    original.quantity_precision,original.quantity_scaled,original.to_location_id,original.from_location_id)
   =(s.workspace_id,s.organization_id,s.legal_entity_id,s.item_id,s.uom_id,s.quantity_precision,s.quantity_scaled,s.from_location_id,s.to_location_id)
   AND s.payload->'original'=jsonb_build_object('id',original.id,'source_digest',original.source_digest,
    'version',original.row_version,'native_response',original.posted_native_json,'review_cost_snapshot',original.review_cost_json),
   'Inverse is an independently governed exact child of one original Posted forward transfer');
 ELSE PERFORM reconforge.it1_assert(s.payload->'original'='null'::jsonb,'Forward transfer cannot invent an original source');END IF;
 created:=s.native_creation_json;native:=reconforge.it1_native_snapshot(t,s.native_movement_id);line:=created#>'{lines,0}';
 PERFORM reconforge.it1_assert(created IS NOT NULL AND jsonb_array_length(created->'lines')=1
  AND(created#>>'{head,id}',created#>>'{head,workspace_id}',created#>>'{head,organization_id}',created#>>'{head,legal_entity_id}',
   created#>>'{head,period_id}',(created#>>'{head,movement_date}')::date,created#>>'{head,source_reference}',created#>>'{head,created_by}')
  =(s.native_movement_id,s.workspace_id,s.organization_id,s.legal_entity_id,s.period_id,s.posting_date,s.id,s.creator_actor_id)
  AND created#>>'{head,movement_number}'='IT1-'||right(s.id,32) AND created#>>'{head,movement_type}'='Transfer'
  AND created#>>'{head,source_type}'='Generated' AND created#>>'{head,status}'='Draft' AND created#>>'{head,row_version}'='1'
  AND(line->>'item_id',line->>'uom_id',(line->>'quantity_precision')::integer,(line->>'quantity_scaled')::bigint,
   line->>'from_location_id',line->>'to_location_id')=(s.item_id,s.uom_id,s.quantity_precision,s.quantity_scaled,s.from_location_id,s.to_location_id)
  AND line->'inventory_lot_id'='null'::jsonb AND line->>'line_number'='1',
  'Transfer must own one exact actual Generated native Draft with approved base UOM and two locations');
 PERFORM reconforge.it1_assert(jsonb_array_length(created->'audit')=1 AND jsonb_array_length(created->'outbox')=1
  AND created#>>'{audit,0,actor_label}'=s.creator_actor_id AND created#>>'{audit,0,action}'='inventory_movement_draft_saved'
  AND created#>'{audit,0,metadata_json}'=jsonb_build_object('movement_number','IT1-'||right(s.id,32),'movement_type','Transfer','line_count',1)
  AND created#>'{outbox,0,payload}'=created#>'{audit,0,metadata_json}',
  'Native transfer creation must retain its actual actor, audit and outbox originals');
 PERFORM reconforge.it1_assert((SELECT count(*) FROM reconforge.inventory_transfer_events WHERE tenant_id=t AND transfer_id=i)=s.row_version
  AND(SELECT count(*) FROM reconforge.inventory_transfer_commands WHERE tenant_id=t AND transfer_id=i)=s.row_version,
  'Transfer source versions require complete original command and event populations');
 FOR v IN 1..s.row_version LOOP
  expected_actor:=reconforge.it1_evidence(t,i,v);
  SELECT * INTO event FROM reconforge.inventory_transfer_events WHERE tenant_id=t AND transfer_id=i AND version=v;
  IF v=1 THEN PERFORM reconforge.it1_assert(event.operation=CASE WHEN s.original_transfer_id IS NULL THEN'create' ELSE'inverse-create' END
   AND expected_actor=s.creator_actor_id,'Transfer starts with its original creator command');
  ELSIF event.operation='review' THEN
   PERFORM reconforge.it1_assert(phase=0 AND v=2 AND expected_actor=s.reviewer_actor_id AND expected_actor<>s.creator_actor_id,'Review must be the independent second human');phase:=1;
  ELSIF event.operation='post' THEN
   PERFORM reconforge.it1_assert(phase=1 AND v=3 AND expected_actor=s.poster_actor_id
    AND expected_actor NOT IN(s.creator_actor_id,s.reviewer_actor_id),'Posting must be the distinct third human');phase:=2;
  ELSIF event.operation='cancel' THEN
   PERFORM reconforge.it1_assert(phase IN(0,1) AND expected_actor<>s.creator_actor_id,'Cancellation retains independent human disposition');phase:=3;
  ELSE PERFORM reconforge.it1_assert(FALSE,'Transfer cannot skip or replay a phase as a new command');END IF;
 END LOOP;
 PERFORM reconforge.it1_assert(phase=s.phase AND(s.reviewer_actor_id IS NOT NULL)=(s.review_cost_json IS NOT NULL)
  AND(s.poster_actor_id IS NOT NULL)=(s.phase=2),'Transfer current phase must equal its complete immutable event history');
 SELECT * INTO c FROM reconforge.inventory_transfer_claims WHERE tenant_id=t AND transfer_id=i;
 SELECT * INTO r FROM reconforge.inventory_transfer_releases WHERE tenant_id=t AND transfer_id=i;
 IF s.reviewer_actor_id IS NULL THEN
  PERFORM reconforge.it1_assert(c.id IS NULL AND r.id IS NULL,'Draft and draft cancellation have no stock reservation');
 ELSE
  PERFORM reconforge.it1_assert(c.id IS NOT NULL
   AND(c.workspace_id,c.organization_id,c.legal_entity_id,c.item_id,c.uom_id,c.quantity_precision,c.location_id,c.quantity_scaled)
   =(s.workspace_id,s.organization_id,s.legal_entity_id,s.item_id,s.uom_id,s.quantity_precision,s.from_location_id,s.quantity_scaled)
   AND EXISTS(SELECT 1 FROM reconforge.inventory_quantity_source_guards g WHERE g.tenant_id=t AND g.id=c.id AND g.owner_namespace='IT1'
    AND(g.workspace_id,g.organization_id,g.legal_entity_id,g.item_id,g.uom_id,g.quantity_precision,g.location_id,g.quantity_scaled)
    =(c.workspace_id,c.organization_id,c.legal_entity_id,c.item_id,c.uom_id,c.quantity_precision,c.location_id,c.quantity_scaled)
    AND g.owner_claim_id=c.id AND g.source_receipt_plan_id IS NULL),
   'Reviewed transfer needs one exact exclusive shared Core quantity claim');
  IF phase=1 THEN PERFORM reconforge.it1_assert(c.state='Active' AND r.id IS NULL
   AND NOT EXISTS(SELECT 1 FROM reconforge.inventory_quantity_source_releases release WHERE release.tenant_id=t AND release.guard_id=c.id),
   'Reviewed quantity must remain exclusively reserved until exact terminal disposition');
   PERFORM reconforge.inventory_quantity_check_capacity(t,s.workspace_id,s.legal_entity_id,s.item_id,s.from_location_id);
  ELSE
   PERFORM reconforge.it1_assert(r.id IS NOT NULL AND r.created_version=3 AND r.claim_id=c.id
    AND r.purpose=CASE phase WHEN 2 THEN'Post' ELSE'Cancel' END
    AND c.state=CASE phase WHEN 2 THEN'Posted' ELSE'Released' END
    AND r.target_movement_id IS NOT DISTINCT FROM CASE phase WHEN 2 THEN s.native_movement_id ELSE NULL END
    AND r.actor_id=(SELECT actor_id FROM reconforge.inventory_transfer_events WHERE tenant_id=t AND transfer_id=i AND version=3)
    AND r.reason=(SELECT reason FROM reconforge.inventory_transfer_events WHERE tenant_id=t AND transfer_id=i AND version=3)
    AND EXISTS(SELECT 1 FROM reconforge.inventory_quantity_source_releases release WHERE release.tenant_id=t AND release.guard_id=c.id AND release.release_id=r.id),
    'Transfer release requires its exact immutable terminal actor, reason and native target');
  END IF;
 END IF;
 IF phase=2 THEN
  PERFORM reconforge.it1_assert(native=s.posted_native_json AND native->'lines'=created->'lines'
   AND((native->'head')-ARRAY['status','posted_by','posted_at','post_reason','updated_at','row_version'])
   =((created->'head')-ARRAY['status','posted_by','posted_at','post_reason','updated_at','row_version'])
   AND native#>>'{head,status}'='Posted' AND native#>>'{head,row_version}'='2' AND native#>>'{head,posted_by}'=s.poster_actor_id
   AND native#>>'{head,post_reason}'=r.reason AND native#>>'{head,posted_at}' IS NOT NULL
   AND jsonb_array_length(native->'audit')=2 AND jsonb_array_length(native->'outbox')=2
   AND native#>'{audit,0}'=created#>'{audit,0}'
   AND native#>>'{audit,1,actor_label}'=s.poster_actor_id AND native#>>'{audit,1,action}'='inventory_movement_posted'
   AND native#>'{audit,1,metadata_json}'=jsonb_build_object('movement_number','IT1-'||right(s.id,32),'reason',r.reason),
   'Posted transfer must retain exact native original lines and independent posting evidence');
  PERFORM reconforge.it1_assert(EXISTS(SELECT 1 FROM jsonb_array_elements(native->'outbox') native_event(value) WHERE native_event.value=created#>'{outbox,0}')
   AND EXISTS(SELECT 1 FROM jsonb_array_elements(native->'outbox') native_event(value) WHERE native_event.value->>'event_type'='inventory_movement_posted'
    AND native_event.value->>'aggregate_type'='inventory_movement' AND native_event.value->>'aggregate_id'=s.native_movement_id
    AND native_event.value->'payload'=native#>'{audit,1,metadata_json}'),'Native posting outbox must exactly bind the retained posting audit and creation original');
 ELSE PERFORM reconforge.it1_assert(native=created AND s.posted_native_json IS NULL,'Unposted or cancelled source retains its original untouched native Draft');END IF;
 PERFORM reconforge.it1_assert(NOT EXISTS(SELECT 1 FROM reconforge.inventory_valuation_documents d WHERE d.tenant_id=t AND d.movement_id=s.native_movement_id)
  AND NOT EXISTS(SELECT 1 FROM reconforge.finance_posting_effects effect WHERE effect.tenant_id=t AND effect.source_id=i),
  'Same-entity transfer owns no additional valuation or GL effect');
END $it1$;
CREATE FUNCTION reconforge.it1_core_claim_close(t TEXT,claim_id TEXT) RETURNS VOID LANGUAGE plpgsql SET search_path=pg_catalog AS $it1$
DECLARE c RECORD;
BEGIN SELECT * INTO c FROM reconforge.inventory_transfer_claims WHERE tenant_id=t AND id=claim_id;
 PERFORM reconforge.it1_assert(c.id IS NOT NULL,'IT1 Core claim must retain its visible complete source owner');PERFORM reconforge.it1_close(t,c.transfer_id);END $it1$;
CREATE FUNCTION reconforge.it1_core_release_close(t TEXT,release_id TEXT) RETURNS VOID LANGUAGE plpgsql SET search_path=pg_catalog AS $it1$
DECLARE r RECORD;
BEGIN SELECT * INTO r FROM reconforge.inventory_transfer_releases WHERE tenant_id=t AND id=release_id;
 PERFORM reconforge.it1_assert(r.id IS NOT NULL,'IT1 Core release must retain its visible complete source owner');PERFORM reconforge.it1_close(t,r.transfer_id);END $it1$;
CREATE FUNCTION reconforge.it1_native_close(t TEXT,movement_id TEXT) RETURNS VOID LANGUAGE plpgsql SET search_path=pg_catalog AS $it1$
DECLARE s RECORD;
BEGIN SELECT * INTO s FROM reconforge.inventory_transfer_sources WHERE tenant_id=t AND native_movement_id=$2;
 PERFORM reconforge.it1_assert(s.id IS NOT NULL,'IT1 native movement must retain its visible complete source owner');PERFORM reconforge.it1_close(t,s.id);END $it1$;
CREATE FUNCTION reconforge.it1_actor(t TEXT,a TEXT,op TEXT,w TEXT,o TEXT,e TEXT) RETURNS VOID
 LANGUAGE plpgsql SET search_path=pg_catalog AS $it1$
DECLARE permission TEXT;permissions TEXT[];
BEGIN
 PERFORM reconforge.it1_assert(op IN('create','inverse-create','review','post','cancel') AND reconforge.irp_scope(t,w,o,e),
  'Transfer writes require an exact current human operation and original hierarchy');
 PERFORM 1 FROM reconforge.identity_users WHERE tenant_id=t AND id=a AND NOT disabled FOR SHARE;
 permissions:=ARRAY['inventory_transfer.read','inventory.read','inventory.valuation.read','finance_core.read',
  CASE WHEN op IN('create','inverse-create') THEN'inventory_transfer.manage' WHEN op='post' THEN'inventory_transfer.post' ELSE'inventory_transfer.approve' END,
  CASE WHEN op='post' THEN'inventory.post' ELSE'inventory.manage' END];
 FOREACH permission IN ARRAY permissions LOOP
  PERFORM reconforge.it1_assert(reconforge.sales_revenue_actor(t,a,permission),'Transfer write requires every current persisted owner and native permission');
 END LOOP;
 PERFORM 1 FROM reconforge.principal_scope_grants WHERE tenant_id=t AND principal_type='user' AND principal_id=a AND revoked_at IS NULL
  AND((scope_type='workspace' AND scope_id=w) OR(scope_type='organization' AND scope_id=o) OR(scope_type='legal_entity' AND scope_id=e)) FOR SHARE;
 PERFORM reconforge.it1_assert((SELECT count(DISTINCT(scope_type,scope_id))=3 FROM reconforge.principal_scope_grants
  WHERE tenant_id=t AND principal_type='user' AND principal_id=a AND revoked_at IS NULL
  AND((scope_type='workspace' AND scope_id=w) OR(scope_type='organization' AND scope_id=o) OR(scope_type='legal_entity' AND scope_id=e))),
  'Transfer requires every current persisted original parent scope grant');
END $it1$;
CREATE FUNCTION reconforge.it1_native_admit(t TEXT,changed JSONB,prior JSONB,action TEXT) RETURNS VOID
 LANGUAGE plpgsql SET search_path=pg_catalog AS $it1$
DECLARE identifier TEXT:=current_setting('app.inventory_transfer_id',true);a TEXT:=current_setting('app.inventory_transfer_actor_id',true);
 op TEXT:=current_setting('app.inventory_transfer_operation',true);s RECORD;head JSONB;
BEGIN
 PERFORM reconforge.it1_assert(action IN('inventory_movements:INSERT','inventory_movements:UPDATE','inventory_movement_lines:INSERT')
  AND identifier~'^IT1-S-[A-F0-9]{32}$' AND changed->>'tenant_id'=t,
  'IT1 native mutations require a closed exact table operation and same-transaction source context');
 IF action='inventory_movement_lines:INSERT' THEN
  SELECT to_jsonb(m) INTO head FROM reconforge.inventory_movements m WHERE m.tenant_id=t AND m.id=changed->>'movement_id';
 ELSE head:=changed;END IF;
 PERFORM reconforge.it1_assert(head->>'source_reference'=identifier AND head->>'movement_number'='IT1-'||right(identifier,32),
  'IT1 native mutation requires the exact caller-owned original source subject');
 IF action='inventory_movement_lines:INSERT' THEN
  PERFORM reconforge.it1_actor(t,a,op,head->>'workspace_id',head->>'organization_id',head->>'legal_entity_id');
  PERFORM reconforge.it1_assert(op IN('create','inverse-create') AND prior IS NULL AND head->>'status'='Draft'
   AND head->>'movement_type'='Transfer' AND head->>'source_type'='Generated' AND head->>'created_by'=a
   AND changed->>'line_number'='1' AND changed->'inventory_lot_id'='null'::jsonb
   AND NOT EXISTS(SELECT 1 FROM reconforge.inventory_transfer_sources WHERE tenant_id=t AND id=identifier),
   'IT1 original single native line may be born only inside its exact creation transaction');RETURN;
 END IF;
 PERFORM reconforge.it1_actor(t,a,op,changed->>'workspace_id',changed->>'organization_id',changed->>'legal_entity_id');
 IF action='inventory_movements:INSERT' THEN
  PERFORM reconforge.it1_assert(op IN('create','inverse-create') AND prior IS NULL AND changed->>'status'='Draft'
   AND changed->>'movement_type'='Transfer' AND changed->>'source_type'='Generated' AND changed->>'created_by'=a
   AND changed->>'row_version'='1' AND NOT EXISTS(SELECT 1 FROM reconforge.inventory_transfer_sources WHERE tenant_id=t AND id=identifier),
   'IT1 native Draft may be born only inside the exact current creation transaction');
 ELSE
  SELECT * INTO s FROM reconforge.inventory_transfer_sources WHERE tenant_id=t AND id=identifier;
  PERFORM reconforge.it1_assert(op='post' AND s.id IS NOT NULL AND s.phase=1 AND s.native_movement_id=changed->>'id'
   AND a NOT IN(s.creator_actor_id,s.reviewer_actor_id) AND prior->>'status'='Draft' AND changed->>'status'='Posted'
   AND prior->>'row_version'='1' AND changed->>'row_version'='2' AND changed->>'posted_by'=a
   AND changed->'posted_at'<>'null'::jsonb
   AND(changed-ARRAY['status','posted_by','posted_at','post_reason','updated_at','row_version'])
    =(prior-ARRAY['status','posted_by','posted_at','post_reason','updated_at','row_version']),
   'IT1 native source cannot be rewritten, directly posted or voided outside its exact third-human owner command');
 END IF;
END $it1$;
CREATE FUNCTION reconforge.it1_protect() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $it1$
DECLARE a TEXT:=current_setting('app.inventory_transfer_actor_id',true);op TEXT:=current_setting('app.inventory_transfer_operation',true);
 identifier TEXT:=current_setting('app.inventory_transfer_id',true);s RECORD;allowed TEXT[];
BEGIN
 PERFORM reconforge.it1_assert(TG_OP<>'DELETE','Transfer originals, custody and complete command history cannot be deleted');
 IF TG_TABLE_NAME='inventory_transfer_sources' THEN s:=NEW;ELSE
 SELECT * INTO s FROM reconforge.inventory_transfer_sources WHERE tenant_id=NEW.tenant_id AND id=NEW.transfer_id;END IF;
 PERFORM reconforge.it1_assert(s.id=identifier,'Transfer mutation requires its exact same-transaction source owner');
 PERFORM reconforge.it1_actor(NEW.tenant_id,a,op,s.workspace_id,s.organization_id,s.legal_entity_id);
 PERFORM 1 FROM reconforge.fiscal_periods WHERE tenant_id=NEW.tenant_id AND id=s.period_id FOR SHARE;
 PERFORM reconforge.it1_assert(EXISTS(SELECT 1 FROM reconforge.fiscal_periods WHERE tenant_id=NEW.tenant_id AND id=s.period_id
  AND application_workspace_id=s.workspace_id AND status='Open' AND s.posting_date BETWEEN start_date AND end_date),
  'New transfer commands require the original current scoped open period');
 IF TG_OP='INSERT' THEN
  IF TG_TABLE_NAME='inventory_transfer_sources' THEN
   PERFORM reconforge.it1_assert(op=CASE WHEN NEW.original_transfer_id IS NULL THEN'create' ELSE'inverse-create' END
    AND NEW.phase=0 AND NEW.row_version=1 AND NEW.creator_actor_id=a AND NEW.reviewer_actor_id IS NULL
    AND NEW.poster_actor_id IS NULL AND NEW.review_cost_json IS NULL AND NEW.posted_native_json IS NULL,'Transfer source starts with its original unreviewed native Draft');
   PERFORM reconforge.inventory_quantity_source_pool_lock(NEW.tenant_id,NEW.workspace_id,NEW.legal_entity_id,NEW.item_id);
   PERFORM reconforge.it1_assert(NEW.payload->'cost_snapshot'=reconforge.it1_cost_snapshot(NEW.tenant_id,NEW.workspace_id,NEW.organization_id,NEW.legal_entity_id,NEW.item_id),
    'Original transfer birth must retain the actual complete current approved FIFO and GL population');
   PERFORM reconforge.it1_assert((SELECT count(*)=2 AND count(DISTINCT warehouse.id)=2 FROM reconforge.inventory_locations location
    JOIN reconforge.inventory_warehouses warehouse ON warehouse.tenant_id=location.tenant_id AND warehouse.id=location.warehouse_id
    WHERE location.tenant_id=NEW.tenant_id AND location.id IN(NEW.from_location_id,NEW.to_location_id)
    AND location.active AND location.location_type='Internal' AND NOT location.allow_negative AND warehouse.active
    AND(warehouse.workspace_id,warehouse.organization_id,warehouse.legal_entity_id)=(NEW.workspace_id,NEW.organization_id,NEW.legal_entity_id)),
    'Original transfer requires two distinct active internal warehouses explicitly in the same entity');
  ELSIF TG_TABLE_NAME='inventory_transfer_claims' THEN
   PERFORM reconforge.it1_assert(op='review' AND s.phase=1 AND NEW.state='Active' AND NEW.created_version=2,'Only original independent review reserves stock');
  ELSIF TG_TABLE_NAME='inventory_transfer_releases' THEN
   PERFORM reconforge.it1_assert(op=CASE NEW.purpose WHEN'Post' THEN'post' ELSE'cancel' END
    AND s.phase=1 AND NEW.actor_id=a,'Release begins inside its exact owner terminal transaction before native stock posting');
  ELSE PERFORM reconforge.it1_assert(NEW.operation=op AND NEW.actor_id=a AND NEW.version=s.row_version,
   'Transfer immutable evidence must bind the current owner actor and exact version');END IF;RETURN NEW;
 END IF;
 IF TG_TABLE_NAME='inventory_transfer_sources' THEN
  allowed:=ARRAY['phase','row_version','reviewer_actor_id','poster_actor_id','review_cost_json','review_cost_digest','posted_native_json'];
  PERFORM reconforge.it1_assert(NEW.row_version=OLD.row_version+1
   AND((op='review' AND OLD.phase=0 AND NEW.phase=1 AND NEW.reviewer_actor_id=a AND a<>OLD.creator_actor_id
      AND OLD.review_cost_json IS NULL AND NEW.review_cost_json IS NOT NULL AND NEW.poster_actor_id IS NULL AND NEW.posted_native_json IS NULL)
    OR(op='post' AND OLD.phase=1 AND NEW.phase=2 AND NEW.poster_actor_id=a AND a NOT IN(OLD.creator_actor_id,OLD.reviewer_actor_id)
      AND NEW.posted_native_json IS NOT NULL)
    OR(op='cancel' AND OLD.phase IN(0,1) AND NEW.phase=3 AND a<>OLD.creator_actor_id AND NEW.poster_actor_id IS NULL AND NEW.posted_native_json IS NULL)),
   'Transfer phase/version cannot skip original three-human governance or terminal disposition');
  IF op<>'review' THEN PERFORM reconforge.it1_assert((NEW.reviewer_actor_id,NEW.review_cost_json,NEW.review_cost_digest)
   IS NOT DISTINCT FROM(OLD.reviewer_actor_id,OLD.review_cost_json,OLD.review_cost_digest),'Original review and approved complete cost snapshot remain immutable');END IF;
  IF op IN('review','post') THEN
   PERFORM reconforge.it1_assert(NEW.review_cost_json=reconforge.it1_cost_snapshot(NEW.tenant_id,NEW.workspace_id,NEW.organization_id,NEW.legal_entity_id,NEW.item_id),
    'Review and post must retain the actual same complete approved FIFO and original GL bytes');END IF;
 ELSIF TG_TABLE_NAME='inventory_transfer_claims' THEN
  allowed:=ARRAY['state'];PERFORM reconforge.it1_assert(OLD.state='Active' AND NEW.state=CASE op WHEN'post' THEN'Posted' WHEN'cancel' THEN'Released' END,
   'Transfer claim disposition must be one exact original terminal owner command');
 ELSE PERFORM reconforge.it1_assert(FALSE,'Transfer releases, commands and event evidence remain immutable');END IF;
 PERFORM reconforge.it1_assert(to_jsonb(NEW)-allowed IS NOT DISTINCT FROM to_jsonb(OLD)-allowed,
  'Transfer original subject, amount/quantity policy, native ownership and source evidence cannot be rewritten');RETURN NEW;
END $it1$;
CREATE FUNCTION reconforge.it1_deferred_close() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $it1$
BEGIN
 IF TG_TABLE_NAME='inventory_transfer_sources' THEN PERFORM reconforge.it1_close(NEW.tenant_id,NEW.id);
 ELSE PERFORM reconforge.it1_close(NEW.tenant_id,NEW.transfer_id);END IF;RETURN NEW;
END $it1$;
DO $it1$ DECLARE n TEXT;BEGIN
 FOREACH n IN ARRAY ARRAY['inventory_transfer_sources','inventory_transfer_claims','inventory_transfer_releases','inventory_transfer_events','inventory_transfer_commands'] LOOP
  EXECUTE format('ALTER TABLE reconforge.%I ENABLE ROW LEVEL SECURITY',n);EXECUTE format('ALTER TABLE reconforge.%I FORCE ROW LEVEL SECURITY',n);
  IF n IN('inventory_transfer_events','inventory_transfer_commands') THEN
   EXECUTE format('CREATE POLICY inventory_transfer_scope ON reconforge.%I USING(reconforge.it1_visible(tenant_id,transfer_id)) WITH CHECK(reconforge.it1_visible(tenant_id,transfer_id))',n);
  ELSE EXECUTE format('CREATE POLICY inventory_transfer_scope ON reconforge.%I USING(reconforge.irp_scope(tenant_id,workspace_id,organization_id,legal_entity_id)) WITH CHECK(reconforge.irp_scope(tenant_id,workspace_id,organization_id,legal_entity_id))',n);END IF;
  EXECUTE format('CREATE TRIGGER inventory_transfer_protect BEFORE INSERT OR UPDATE OR DELETE ON reconforge.%I FOR EACH ROW EXECUTE FUNCTION reconforge.it1_protect()',n);
  EXECUTE format('CREATE CONSTRAINT TRIGGER inventory_transfer_close AFTER INSERT OR UPDATE ON reconforge.%I DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION reconforge.it1_deferred_close()',n);
 END LOOP;
END $it1$;
"""

DOWNGRADE_SQL = r"""
DO $it1$ BEGIN
 IF EXISTS(SELECT 1 FROM reconforge.inventory_transfer_sources) THEN
  RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Populated transfer originals require restore; destructive downgrade is refused';END IF;
END $it1$;
DROP TABLE reconforge.inventory_transfer_commands,reconforge.inventory_transfer_events,reconforge.inventory_transfer_releases,
 reconforge.inventory_transfer_claims,reconforge.inventory_transfer_sources;
DROP FUNCTION reconforge.it1_deferred_close(),reconforge.it1_protect(),reconforge.it1_native_admit(TEXT,JSONB,JSONB,TEXT),
 reconforge.it1_actor(TEXT,TEXT,TEXT,TEXT,TEXT,TEXT),reconforge.it1_native_close(TEXT,TEXT),
 reconforge.it1_core_release_close(TEXT,TEXT),reconforge.it1_core_claim_close(TEXT,TEXT),reconforge.it1_close(TEXT,TEXT),
 reconforge.it1_cost_originals(TEXT,JSONB),reconforge.it1_evidence(TEXT,TEXT,INTEGER),reconforge.it1_public(TEXT,TEXT,INTEGER),
 reconforge.it1_native_snapshot(TEXT,TEXT),reconforge.it1_cost_snapshot(TEXT,TEXT,TEXT,TEXT,TEXT),reconforge.it1_visible(TEXT,TEXT),reconforge.it1_assert(BOOLEAN,TEXT);
"""
