"""SR1 forced-scope ownership and complete native FIFO/AP/GL source closure."""
from __future__ import annotations

from typing import Any

_TABLES = r"""
ALTER TABLE reconforge.procurement_partial_receipts ADD COLUMN supplier_return_owner_id TEXT;
ALTER TABLE reconforge.ap_supplier_invoices ADD COLUMN supplier_return_owner_id TEXT;
ALTER TABLE reconforge.ap_supplier_invoices DROP CONSTRAINT ap_supplier_invoices_status_check;
ALTER TABLE reconforge.ap_supplier_invoices ADD CONSTRAINT ap_supplier_invoices_status_check
 CHECK(status IN('Draft','Submitted','Matched','Exception','Approved','Paid','Rejected','Credited'));
CREATE TABLE reconforge.supplier_return_plans(
 tenant_id TEXT NOT NULL,id TEXT NOT NULL CHECK(id~'^SR1-[a-f0-9]{32}$'),workspace_id TEXT NOT NULL,
 organization_id TEXT NOT NULL,legal_entity_id TEXT NOT NULL,order_id TEXT NOT NULL,receipt_id TEXT NOT NULL,
 invoice_id TEXT NOT NULL,native_invoice_id TEXT NOT NULL,number TEXT NOT NULL CHECK(length(number) BETWEEN 5 AND 64 AND left(number,4)='SR1-'),
 phase INTEGER NOT NULL DEFAULT 0 CHECK(phase BETWEEN 0 AND 3),amount_minor BIGINT NOT NULL CHECK(amount_minor BETWEEN 1 AND 9000000000000000000),
 payload JSONB NOT NULL CHECK(octet_length(payload::text)<=262144),audit_event_id TEXT NOT NULL,outbox_event_id TEXT NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(),PRIMARY KEY(tenant_id,id),UNIQUE(tenant_id,workspace_id,number),
 FOREIGN KEY(tenant_id,order_id) REFERENCES reconforge.procurement_partial_orders(tenant_id,id),
 FOREIGN KEY(tenant_id,receipt_id) REFERENCES reconforge.procurement_partial_receipts(tenant_id,id),
 FOREIGN KEY(tenant_id,invoice_id) REFERENCES reconforge.procurement_partial_invoices(tenant_id,id),
 FOREIGN KEY(tenant_id,native_invoice_id) REFERENCES reconforge.ap_supplier_invoices(tenant_id,id),
 FOREIGN KEY(tenant_id,audit_event_id) REFERENCES reconforge.domain_audit_events(tenant_id,id),
 FOREIGN KEY(tenant_id,outbox_event_id) REFERENCES reconforge.outbox_events(tenant_id,event_id)
);
CREATE UNIQUE INDEX supplier_return_active_receipt ON reconforge.supplier_return_plans(tenant_id,receipt_id) WHERE phase<>3;
CREATE UNIQUE INDEX supplier_return_active_invoice ON reconforge.supplier_return_plans(tenant_id,native_invoice_id) WHERE phase<>3;
CREATE INDEX supplier_return_order_page ON reconforge.supplier_return_plans(tenant_id,order_id,created_at DESC,id);
CREATE TABLE reconforge.supplier_return_events(
 tenant_id TEXT NOT NULL,plan_id TEXT NOT NULL,operation TEXT NOT NULL CHECK(operation IN('review','post','cancel')),
 actor_id TEXT NOT NULL,reason TEXT NOT NULL CHECK(length(reason) BETWEEN 1 AND 500),effects JSONB NOT NULL CHECK(jsonb_typeof(effects)='array'),
 audit_event_id TEXT NOT NULL,outbox_event_id TEXT NOT NULL,created_at TIMESTAMPTZ NOT NULL DEFAULT now(),PRIMARY KEY(tenant_id,plan_id,operation),
 FOREIGN KEY(tenant_id,plan_id) REFERENCES reconforge.supplier_return_plans(tenant_id,id),
 FOREIGN KEY(tenant_id,actor_id) REFERENCES reconforge.identity_users(tenant_id,id),
 FOREIGN KEY(tenant_id,audit_event_id) REFERENCES reconforge.domain_audit_events(tenant_id,id),
 FOREIGN KEY(tenant_id,outbox_event_id) REFERENCES reconforge.outbox_events(tenant_id,event_id)
);
CREATE TABLE reconforge.supplier_return_commands(
 tenant_id TEXT NOT NULL,workspace_id TEXT NOT NULL,plan_id TEXT NOT NULL,operation TEXT NOT NULL CHECK(operation IN('prepare','review','post','cancel')),
 command_id TEXT NOT NULL CHECK(length(command_id) BETWEEN 1 AND 140),actor_id TEXT NOT NULL,request_digest TEXT NOT NULL CHECK(request_digest~'^[a-f0-9]{64}$'),
 request_json JSONB NOT NULL,response_json JSONB NOT NULL,created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 PRIMARY KEY(tenant_id,workspace_id,command_id),UNIQUE(tenant_id,plan_id,operation),
 FOREIGN KEY(tenant_id,plan_id) REFERENCES reconforge.supplier_return_plans(tenant_id,id),FOREIGN KEY(tenant_id,actor_id) REFERENCES reconforge.identity_users(tenant_id,id)
);
CREATE TABLE reconforge.ap_supplier_invoice_credits(
 tenant_id TEXT NOT NULL,plan_id TEXT NOT NULL,supplier_invoice_id TEXT NOT NULL,amount_minor BIGINT NOT NULL CHECK(amount_minor>0),
 original_accrual_effect_id TEXT NOT NULL,inverse_accrual_effect_id TEXT NOT NULL,inventory_inverse_effect_id TEXT NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(),PRIMARY KEY(tenant_id,plan_id),UNIQUE(tenant_id,supplier_invoice_id),
 FOREIGN KEY(tenant_id,plan_id) REFERENCES reconforge.supplier_return_plans(tenant_id,id),
 FOREIGN KEY(tenant_id,supplier_invoice_id) REFERENCES reconforge.ap_supplier_invoices(tenant_id,id),
 FOREIGN KEY(tenant_id,original_accrual_effect_id) REFERENCES reconforge.finance_posting_effects(tenant_id,id),
 FOREIGN KEY(tenant_id,inverse_accrual_effect_id) REFERENCES reconforge.finance_posting_effects(tenant_id,id),
 FOREIGN KEY(tenant_id,inventory_inverse_effect_id) REFERENCES reconforge.finance_posting_effects(tenant_id,id)
);
CREATE FUNCTION reconforge.sr_assert(ok BOOLEAN,message TEXT) RETURNS VOID LANGUAGE plpgsql SET search_path=pg_catalog AS $sr$
BEGIN IF ok IS DISTINCT FROM TRUE THEN RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='supplier_return_owner',MESSAGE=message; END IF; END $sr$;
CREATE FUNCTION reconforge.sr_source(t TEXT,o TEXT,r TEXT,i TEXT) RETURNS JSONB LANGUAGE sql STABLE SET search_path=pg_catalog AS $sr$
 SELECT jsonb_build_object('order',to_jsonb(c)-ARRAY['row_version','created_at'],
 'receipt',(to_jsonb(d)-'supplier_return_owner_id')||jsonb_build_object('quantity',d.quantity::text),'invoice',to_jsonb(b)-ARRAY['quantity','quantity_text'],
 'invoice_line',to_jsonb(il)||jsonb_build_object('quantity',il.quantity::text),'order_line',to_jsonb(ol)||jsonb_build_object('quantity',ol.quantity::text),'original_plan',p.plan_json,
 'native_invoice',to_jsonb(h)-ARRAY['supplier_return_owner_id','status','row_version','updated_at'],
 'invoice_status',h.status,'invoice_version',h.row_version,
 'accrual_effect',to_jsonb(f))
 FROM reconforge.procurement_partial_orders c JOIN reconforge.procurement_partial_receipts d ON d.tenant_id=c.tenant_id AND d.order_id=c.id
 JOIN reconforge.procurement_partial_invoices b ON b.tenant_id=c.tenant_id AND b.order_id=c.id
 JOIN reconforge.procurement_partial_invoice_lines il ON il.tenant_id=b.tenant_id AND il.invoice_id=b.id AND il.order_line_id=d.order_line_id
 JOIN reconforge.procurement_partial_order_lines ol ON ol.tenant_id=d.tenant_id AND ol.id=d.order_line_id
 JOIN reconforge.inventory_receipt_plans p ON p.tenant_id=d.tenant_id AND p.id=d.receipt_plan_id
 JOIN reconforge.ap_supplier_invoices h ON h.tenant_id=b.tenant_id AND h.id=b.native_invoice_id
 JOIN reconforge.finance_posting_effects f ON f.tenant_id=b.tenant_id AND f.id=b.accrual_effect_id
 WHERE c.tenant_id=t AND c.id=o AND d.id=r AND b.id=i
$sr$;
CREATE FUNCTION reconforge.sr_available(t TEXT,o TEXT,r TEXT,i TEXT) RETURNS VOID LANGUAGE plpgsql SET search_path=pg_catalog AS $sr$
DECLARE s JSONB;h RECORD;d RECORD;p RECORD;il RECORD;
BEGIN
 s:=reconforge.sr_source(t,o,r,i);
 SELECT * INTO d FROM reconforge.procurement_partial_receipts WHERE tenant_id=t AND id=r;
 SELECT * INTO p FROM reconforge.procurement_partial_orders WHERE tenant_id=t AND id=o;
 SELECT * INTO h FROM reconforge.ap_supplier_invoices WHERE tenant_id=t AND id=s->'native_invoice'->>'id' FOR UPDATE;
 SELECT * INTO il FROM reconforge.procurement_partial_invoice_lines WHERE tenant_id=t AND invoice_id=i;
 PERFORM reconforge.sr_assert(s IS NOT NULL AND p.multiline AND left(p.number,5)<>'BPC1-' AND d.stage=2
  AND(s->'invoice'->>'stage')::integer=4 AND h.status='Approved' AND h.tax_minor=0 AND h.supplier_return_owner_id IS NULL
  AND d.supplier_return_owner_id IS NULL AND il.order_line_id=d.order_line_id AND il.quantity=d.quantity
  AND il.total_minor=d.total_minor AND h.total_minor=d.total_minor
  AND(SELECT count(*) FROM reconforge.procurement_partial_invoice_lines WHERE tenant_id=t AND invoice_id=i)=1
  AND(SELECT count(*) FROM reconforge.procurement_partial_receipts WHERE tenant_id=t AND order_id=o AND order_line_id=d.order_line_id AND stage=2)=1
  AND(SELECT count(*) FROM reconforge.procurement_partial_invoice_lines z JOIN reconforge.procurement_partial_invoices b ON b.tenant_id=z.tenant_id AND b.id=z.invoice_id WHERE z.tenant_id=t AND z.order_line_id=d.order_line_id)=1
  AND NOT EXISTS(SELECT 1 FROM reconforge.ap_payment_links WHERE tenant_id=t AND supplier_invoice_id=h.id)
  AND NOT EXISTS(SELECT 1 FROM reconforge.financial_installment_plans WHERE tenant_id=t AND source_id=h.id)
  AND NOT EXISTS(SELECT 1 FROM reconforge.supplier_return_plans WHERE tenant_id=t AND phase<>3 AND(receipt_id=r OR native_invoice_id=h.id)),
  'Return requires one entire unissued receipt and its exact single-line accrued unpaid AP invoice, excluding appropriations and payment drafts');
 PERFORM reconforge.pp_verify_order(t,o);
END $sr$;
CREATE FUNCTION reconforge.sr_public(t TEXT,i TEXT,selected_phase INTEGER DEFAULT NULL) RETURNS JSONB LANGUAGE plpgsql STABLE SET search_path=pg_catalog AS $sr$
DECLARE p RECORD;r RECORD;l RECORD;c RECORD;stage INTEGER;
BEGIN
 SELECT * INTO p FROM reconforge.supplier_return_plans WHERE tenant_id=t AND id=i;
 SELECT * INTO r FROM reconforge.supplier_return_events WHERE tenant_id=t AND plan_id=i AND operation='review';
 SELECT * INTO l FROM reconforge.supplier_return_events WHERE tenant_id=t AND plan_id=i AND operation='post';
 SELECT * INTO c FROM reconforge.supplier_return_events WHERE tenant_id=t AND plan_id=i AND operation='cancel';
 stage:=COALESCE(selected_phase,p.phase);
 RETURN p.payload||jsonb_build_object('phase',stage,'status',(ARRAY['Prepared','Reviewed','Posted','Cancelled'])[stage+1],
 'credit_minor',p.payload->>'credit_minor','inventory_removed_minor',p.payload->>'inventory_removed_minor',
 'charge_expense_minor',p.payload->>'charge_expense_minor','amount_minor',p.payload->>'amount_minor',
 'reviewer_actor_id',CASE WHEN stage<>0 THEN r.actor_id ELSE NULL END,'posted_actor_id',CASE WHEN stage=2 THEN l.actor_id ELSE NULL END,
 'posting_effect_ids',CASE WHEN stage=2 THEN l.effects ELSE '[]'::jsonb END,'cancelled_actor_id',CASE WHEN stage=3 THEN c.actor_id ELSE NULL END,
 'cancellation_reason',CASE WHEN stage=3 THEN c.reason ELSE NULL END,'canonical_plan_json',reconforge.irp_canonical(p.payload-'plan_digest'),
 'evidence',jsonb_build_object('prepared_audit_event_id',p.audit_event_id,'prepared_outbox_event_id',p.outbox_event_id,
 'review_audit_event_id',CASE WHEN stage<>0 THEN r.audit_event_id ELSE NULL END,'review_outbox_event_id',CASE WHEN stage<>0 THEN r.outbox_event_id ELSE NULL END,
 'post_audit_event_id',CASE WHEN stage=2 THEN l.audit_event_id ELSE NULL END,'post_outbox_event_id',CASE WHEN stage=2 THEN l.outbox_event_id ELSE NULL END,
 'cancel_audit_event_id',CASE WHEN stage=3 THEN c.audit_event_id ELSE NULL END,'cancel_outbox_event_id',CASE WHEN stage=3 THEN c.outbox_event_id ELSE NULL END));
END $sr$;
CREATE FUNCTION reconforge.sr_event(t TEXT,i TEXT,a TEXT,b TEXT,actor TEXT,action TEXT,metadata JSONB) RETURNS BOOLEAN LANGUAGE sql STABLE SET search_path=pg_catalog AS $sr$
 SELECT EXISTS(SELECT 1 FROM reconforge.domain_audit_events x JOIN reconforge.outbox_events y ON y.tenant_id=x.tenant_id
 JOIN reconforge.supplier_return_plans p ON p.tenant_id=x.tenant_id AND p.id=i WHERE x.tenant_id=t AND x.id=a AND y.event_id=b
 AND x.actor_user_id=actor AND x.object_type='operational_finance' AND x.object_id=i AND x.action=action AND x.metadata_json=metadata
 AND y.event_type=action AND y.aggregate_type='operational_finance' AND y.aggregate_id=i AND y.payload=metadata||jsonb_build_object('audit_event_id',a)
 AND(y.workspace_id,y.organization_id,y.legal_entity_id)=(p.workspace_id,p.organization_id,p.legal_entity_id))
$sr$;
CREATE FUNCTION reconforge.sr_authority(t TEXT,a TEXT,operation TEXT,w TEXT,o TEXT,e TEXT) RETURNS BOOLEAN LANGUAGE plpgsql SET search_path=pg_catalog AS $sr$
DECLARE permissions TEXT[]:=ARRAY['payables.read','inventory.read','finance_core.read'];permission TEXT;
BEGIN
 IF operation='prepare' THEN permissions:=permissions||ARRAY['payables.manage','inventory.manage','inventory.valuation.manage','inventory.valuation.reverse.manage','finance_core.manage','finance_core.reverse'];
 ELSIF operation='review' THEN permissions:=permissions||ARRAY['payables.approve','inventory.post','inventory.valuation.approve','inventory.valuation.reverse.approve','finance_core.validate','finance_core.reverse'];
 ELSIF operation='post' THEN permissions:=permissions||ARRAY['payables.manage','inventory.post','inventory.valuation.approve','inventory.valuation.reverse.approve','finance_core.post','finance_core.reverse'];
 ELSIF operation='cancel' THEN permissions:=permissions||ARRAY['payables.approve','inventory.valuation.reverse.approve','finance_core.validate']; ELSE RETURN FALSE; END IF;
 PERFORM 1 FROM reconforge.principal_scope_grants WHERE tenant_id=t AND principal_type='user' AND principal_id=a AND revoked_at IS NULL
 AND((scope_type='workspace' AND scope_id=w) OR(scope_type='organization' AND scope_id=o) OR(scope_type='legal_entity' AND scope_id=e)) FOR SHARE;
 IF(SELECT count(*) FROM reconforge.principal_scope_grants WHERE tenant_id=t AND principal_type='user' AND principal_id=a AND revoked_at IS NULL
 AND((scope_type='workspace' AND scope_id=w) OR(scope_type='organization' AND scope_id=o) OR(scope_type='legal_entity' AND scope_id=e)))<>3 THEN RETURN FALSE; END IF;
 PERFORM 1 FROM reconforge.identity_user_roles u JOIN reconforge.identity_roles r ON r.tenant_id=u.tenant_id AND r.id=u.role_id
 JOIN reconforge.identity_role_permissions p ON p.tenant_id=r.tenant_id AND p.role_id=r.id WHERE u.tenant_id=t AND u.user_id=a AND u.active AND r.active AND p.active FOR SHARE OF u,r,p;
 FOREACH permission IN ARRAY permissions LOOP IF NOT reconforge.sales_revenue_actor(t,a,permission) THEN RETURN FALSE; END IF; END LOOP;
 RETURN TRUE;
END $sr$;
CREATE FUNCTION reconforge.sr_protect() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $sr$
DECLARE p RECORD;a TEXT:=current_setting('app.supplier_return_actor_id',true);
BEGIN
 PERFORM reconforge.sr_assert(TG_OP<>'DELETE' AND(TG_OP<>'UPDATE' OR TG_TABLE_NAME='supplier_return_plans'),'Supplier return source history is immutable');
 IF TG_TABLE_NAME='supplier_return_plans' THEN
  IF TG_OP='INSERT' THEN
   PERFORM reconforge.sr_assert(NEW.phase=0 AND NEW.payload->>'preparer_actor_id'=a AND reconforge.sr_authority(NEW.tenant_id,a,'prepare',NEW.workspace_id,NEW.organization_id,NEW.legal_entity_id),'Return must be born Prepared under current canonical human authority');
  ELSE
   PERFORM reconforge.sr_assert((to_jsonb(NEW)-'phase')=(to_jsonb(OLD)-'phase') AND((OLD.phase=0 AND NEW.phase=1) OR(OLD.phase=1 AND NEW.phase=2) OR(OLD.phase IN(0,1) AND NEW.phase=3)), 'Retained return lifecycle cannot rewrite source evidence');
  END IF;
 ELSE
  SELECT * INTO p FROM reconforge.supplier_return_plans WHERE tenant_id=NEW.tenant_id AND id=NEW.plan_id;
  PERFORM reconforge.sr_assert(p.id IS NOT NULL AND reconforge.sr_authority(NEW.tenant_id,a,CASE WHEN TG_TABLE_NAME='ap_supplier_invoice_credits' THEN'post' ELSE to_jsonb(NEW)->>'operation' END,p.workspace_id,p.organization_id,p.legal_entity_id)
  AND(TG_TABLE_NAME='ap_supplier_invoice_credits' OR to_jsonb(NEW)->>'actor_id'=a),'Retained return command and AP credit require current human authority');
 END IF;
 RETURN NEW;
END $sr$;
DO $sr$ DECLARE n TEXT;BEGIN
 FOREACH n IN ARRAY ARRAY['supplier_return_plans','supplier_return_events','supplier_return_commands','ap_supplier_invoice_credits'] LOOP
  EXECUTE format('ALTER TABLE reconforge.%I ENABLE ROW LEVEL SECURITY',n);
  EXECUTE format('ALTER TABLE reconforge.%I FORCE ROW LEVEL SECURITY',n);
  IF n='supplier_return_plans' THEN EXECUTE format('CREATE POLICY scope ON reconforge.%I USING(reconforge.irp_scope(tenant_id,workspace_id,organization_id,legal_entity_id)) WITH CHECK(reconforge.irp_scope(tenant_id,workspace_id,organization_id,legal_entity_id))',n);
  ELSE EXECUTE format('CREATE POLICY scope ON reconforge.%I USING(EXISTS(SELECT 1 FROM reconforge.supplier_return_plans p WHERE p.tenant_id=%I.tenant_id AND p.id=%I.plan_id)) WITH CHECK(EXISTS(SELECT 1 FROM reconforge.supplier_return_plans p WHERE p.tenant_id=%I.tenant_id AND p.id=%I.plan_id))',n,n,n,n,n); END IF;
  EXECUTE format('CREATE TRIGGER immutable BEFORE INSERT OR UPDATE OR DELETE ON reconforge.%I FOR EACH ROW EXECUTE FUNCTION reconforge.sr_protect()',n);
 END LOOP;
END $sr$;
"""

_NATIVE = r"""
CREATE FUNCTION reconforge.sr_credited(t TEXT,i TEXT) RETURNS BOOLEAN LANGUAGE plpgsql STABLE SET search_path=pg_catalog AS $sr$
DECLARE marker TEXT;
BEGIN
 SELECT supplier_return_owner_id INTO marker FROM reconforge.ap_supplier_invoices WHERE tenant_id=t AND id=i;
 IF marker IS NULL THEN RETURN FALSE; END IF;
 RETURN EXISTS(SELECT 1 FROM reconforge.supplier_return_plans p JOIN reconforge.ap_supplier_invoice_credits c ON c.tenant_id=p.tenant_id AND c.plan_id=p.id
  WHERE p.tenant_id=t AND p.id=marker AND p.phase=2 AND p.native_invoice_id=i AND c.supplier_invoice_id=i AND c.amount_minor=(p.payload->>'credit_minor')::bigint);
END $sr$;
CREATE FUNCTION reconforge.sr_inverse_owned(t TEXT,i TEXT) RETURNS BOOLEAN LANGUAGE plpgsql STABLE SET search_path=pg_catalog AS $sr$
DECLARE native RECORD;
BEGIN
 SELECT * INTO native FROM reconforge.inventory_receipt_plans WHERE tenant_id=t AND id=i;
 IF native.id IS NULL OR left(native.source_number,4)<>'SR1-' THEN RETURN FALSE; END IF;
 RETURN EXISTS(SELECT 1 FROM reconforge.supplier_return_plans p WHERE p.tenant_id=t AND p.payload->'inverse_plan'->>'plan_id'=i
 AND p.payload->'source_snapshot'->'receipt'->>'receipt_plan_id'=native.original_plan_id);
END $sr$;
CREATE FUNCTION reconforge.sr_inverse_entry(t TEXT,s TEXT,e TEXT) RETURNS BOOLEAN LANGUAGE plpgsql STABLE SET search_path=pg_catalog AS $sr$
DECLARE number TEXT;reference TEXT;
BEGIN
 SELECT entry_number,external_reference INTO number,reference FROM reconforge.finance_entries WHERE tenant_id=t AND id=e;
 IF left(upper(number),4) IS DISTINCT FROM'SR1-' OR left(upper(reference),4) IS DISTINCT FROM'SR1-' THEN RETURN FALSE; END IF;
 RETURN EXISTS(SELECT 1 FROM reconforge.supplier_return_plans p CROSS JOIN LATERAL jsonb_array_elements(p.payload->'entries') x
 WHERE p.tenant_id=t AND p.invoice_id=s AND x->>'entry_id'=e AND x->>'original_effect_id' IS NOT NULL);
END $sr$;
CREATE FUNCTION reconforge.sr_invoice_projection(t TEXT,i TEXT) RETURNS JSONB LANGUAGE plpgsql STABLE SET search_path=pg_catalog AS $sr$
DECLARE h RECORD;c RECORD;
BEGIN
 SELECT * INTO h FROM reconforge.ap_supplier_invoices WHERE tenant_id=t AND id=i;
 IF h.supplier_return_owner_id IS NULL THEN RETURN '{}'::jsonb; END IF;
 PERFORM reconforge.sr_close(t,h.supplier_return_owner_id);
 SELECT * INTO c FROM reconforge.ap_supplier_invoice_credits WHERE tenant_id=t AND supplier_invoice_id=i;
 RETURN jsonb_build_object('supplier_return_owner_id',h.supplier_return_owner_id,'supplier_credit_note_id',c.plan_id,
 'credited_minor',COALESCE(c.amount_minor,0)::text,'outstanding_minor',(h.total_minor-COALESCE(c.amount_minor,0))::text);
END $sr$;
CREATE FUNCTION reconforge.sr_native_admit() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $sr$
DECLARE changed JSONB;marker TEXT;p RECORD;invoice TEXT;
BEGIN
 changed:=CASE WHEN TG_OP='DELETE' THEN to_jsonb(OLD) ELSE to_jsonb(NEW) END;
 IF TG_TABLE_NAME IN('ap_supplier_invoices','procurement_partial_receipts') THEN
  marker:=COALESCE(changed->>'supplier_return_owner_id',CASE WHEN TG_OP='UPDATE' THEN to_jsonb(OLD)->>'supplier_return_owner_id' END);
  IF marker IS NULL THEN
   PERFORM reconforge.sr_assert(changed->>'status' IS DISTINCT FROM 'Credited','Native credited AP requires complete retained original supplier debit');
   RETURN COALESCE(NEW,OLD);
  END IF;
  SELECT * INTO p FROM reconforge.supplier_return_plans WHERE tenant_id=changed->>'tenant_id' AND id=marker;
  PERFORM reconforge.sr_assert(p.id IS NOT NULL AND changed->>'id'=(CASE TG_TABLE_NAME WHEN'ap_supplier_invoices' THEN p.native_invoice_id ELSE p.receipt_id END)
   AND(p.phase<>2 OR changed->>'supplier_return_owner_id'=marker)
   AND(changed->>'supplier_return_owner_id' IS NOT NULL OR p.phase=3), 'Supplier receipt and invoice claim require exact owner; posted credit cannot detach');
 ELSE
  invoice:=CASE TG_TABLE_NAME WHEN'ap_payment_links' THEN changed->>'supplier_invoice_id' ELSE changed->>'source_id' END;
  SELECT supplier_return_owner_id INTO marker FROM reconforge.ap_supplier_invoices WHERE tenant_id=changed->>'tenant_id' AND id=invoice FOR UPDATE;
  IF marker IS NULL THEN RETURN COALESCE(NEW,OLD); END IF;
  PERFORM reconforge.sr_assert(FALSE,'Pending or posted whole supplier debit owns this AP residual; extra payment effects and drafts are refused');
 END IF;
 RETURN COALESCE(NEW,OLD);
END $sr$;
CREATE TRIGGER supplier_return_admission BEFORE INSERT OR UPDATE OR DELETE ON reconforge.ap_supplier_invoices FOR EACH ROW EXECUTE FUNCTION reconforge.sr_native_admit();
CREATE TRIGGER supplier_return_admission BEFORE INSERT OR UPDATE OR DELETE ON reconforge.procurement_partial_receipts FOR EACH ROW EXECUTE FUNCTION reconforge.sr_native_admit();
CREATE TRIGGER supplier_return_payment_admission BEFORE INSERT OR UPDATE OR DELETE ON reconforge.ap_payment_links FOR EACH ROW EXECUTE FUNCTION reconforge.sr_native_admit();
CREATE TRIGGER supplier_return_payment_admission BEFORE INSERT ON reconforge.financial_installment_plans FOR EACH ROW EXECUTE FUNCTION reconforge.sr_native_admit();
CREATE FUNCTION reconforge.sr_reverse_close() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $sr$
DECLARE j JSONB;identifier TEXT;entry TEXT;native_plan TEXT;marker TEXT;original_effect TEXT;q RECORD;
BEGIN
 j:=CASE WHEN TG_OP='DELETE' THEN to_jsonb(OLD) ELSE to_jsonb(NEW) END;
 IF TG_TABLE_NAME IN('supplier_return_plans','supplier_return_events','supplier_return_commands','ap_supplier_invoice_credits') THEN
  PERFORM reconforge.sr_close(j->>'tenant_id',COALESCE(j->>'plan_id',j->>'id')); RETURN NULL;
 ELSIF TG_TABLE_NAME IN('ap_supplier_invoices','procurement_partial_receipts') THEN
  marker:=COALESCE(j->>'supplier_return_owner_id',CASE WHEN TG_OP='UPDATE' THEN to_jsonb(OLD)->>'supplier_return_owner_id' END);
  IF marker IS NULL THEN RETURN NULL; END IF;
  PERFORM reconforge.sr_close(j->>'tenant_id',marker); RETURN NULL;
 ELSIF TG_TABLE_NAME IN('domain_audit_events','outbox_events') THEN
  identifier:=COALESCE(j->>'object_id',j->>'aggregate_id');
  IF left(identifier,4) IS DISTINCT FROM'SR1-' THEN RETURN NULL; END IF;
  PERFORM reconforge.sr_close(j->>'tenant_id',identifier); RETURN NULL;
 ELSIF TG_TABLE_NAME IN('inventory_receipt_plans','inventory_receipt_reviews','inventory_receipt_links','inventory_receipt_commands') THEN
  native_plan:=COALESCE(j->>'plan_id',j->>'id');
  SELECT source_number INTO marker FROM reconforge.inventory_receipt_plans WHERE tenant_id=j->>'tenant_id' AND id=native_plan;
  IF left(marker,4) IS DISTINCT FROM'SR1-' THEN RETURN NULL; END IF;
 ELSIF TG_TABLE_NAME='inventory_cost_layers' THEN
  SELECT id INTO native_plan FROM reconforge.inventory_receipt_plans WHERE tenant_id=j->>'tenant_id' AND cost_layer_id=j->>'id' AND left(source_number,4)='SR1-' LIMIT 1;
  IF native_plan IS NULL THEN RETURN NULL; END IF;
 ELSIF TG_TABLE_NAME IN('finance_accounts','finance_journals') THEN
  IF NOT EXISTS(SELECT 1 FROM reconforge.finance_entries e WHERE e.tenant_id=j->>'tenant_id' AND left(e.entry_number,4)='SR1-'
   AND((TG_TABLE_NAME='finance_journals' AND e.journal_id=j->>'id') OR(TG_TABLE_NAME='finance_accounts' AND EXISTS(SELECT 1 FROM reconforge.finance_entry_lines x WHERE x.tenant_id=e.tenant_id AND x.entry_id=e.id AND x.account_id=j->>'id')))) THEN RETURN NULL; END IF;
 ELSE
  entry:=CASE TG_TABLE_NAME WHEN'finance_entries' THEN j->>'id' WHEN'finance_entry_line_dimensions' THEN(SELECT x.entry_id FROM reconforge.finance_entry_lines x WHERE x.tenant_id=j->>'tenant_id' AND x.id=j->>'entry_line_id') ELSE j->>'entry_id' END;
  SELECT reverses_posting_id INTO original_effect FROM reconforge.finance_entries WHERE tenant_id=j->>'tenant_id' AND id=entry;
  original_effect:=COALESCE(original_effect,j->>'reverses_effect_id');
  IF original_effect IS NOT NULL AND EXISTS(
   SELECT 1 FROM reconforge.finance_posting_effects original_posting
   JOIN reconforge.finance_entries original_entry ON original_entry.tenant_id=original_posting.tenant_id AND original_entry.id=original_posting.entry_id
   WHERE original_posting.tenant_id=j->>'tenant_id' AND original_posting.id=original_effect
    AND(upper(left(original_entry.entry_number,5))='OPS1-' OR upper(left(original_entry.id,5))='OPS1-')) THEN
   FOR q IN SELECT order_id FROM reconforge.procurement_partial_invoices WHERE tenant_id=j->>'tenant_id' AND accrual_effect_id=original_effect LOOP
    PERFORM reconforge.pp_verify_order(j->>'tenant_id',q.order_id);
   END LOOP;
  END IF;
  SELECT entry_number INTO marker FROM reconforge.finance_entries WHERE tenant_id=j->>'tenant_id' AND id=entry;
  IF left(marker,4) IS DISTINCT FROM'SR1-' THEN RETURN NULL; END IF;
 END IF;
 FOR q IN SELECT p.id FROM reconforge.supplier_return_plans p WHERE p.tenant_id=j->>'tenant_id'
  AND((native_plan IS NOT NULL AND p.payload->'inverse_plan'->>'plan_id'=native_plan)
   OR(TG_TABLE_NAME='inventory_cost_layers' AND p.payload->'inverse_plan'->'artifacts'->>'cost_layer_id'=j->>'id')
   OR(entry IS NOT NULL AND EXISTS(SELECT 1 FROM jsonb_array_elements(p.payload->'entries') x WHERE x->>'entry_id'=entry))
   OR(TG_TABLE_NAME IN('finance_accounts','finance_journals') AND EXISTS(SELECT 1 FROM jsonb_array_elements(p.payload->'entries') x JOIN reconforge.finance_entries e ON e.tenant_id=p.tenant_id AND e.id=x->>'entry_id'
    WHERE(TG_TABLE_NAME='finance_journals' AND e.journal_id=j->>'id') OR(TG_TABLE_NAME='finance_accounts' AND EXISTS(SELECT 1 FROM reconforge.finance_entry_lines z WHERE z.tenant_id=p.tenant_id AND z.entry_id=e.id AND z.account_id=j->>'id'))))) LOOP
   identifier:=q.id; PERFORM reconforge.sr_close(j->>'tenant_id',q.id);
 END LOOP;
 PERFORM reconforge.sr_assert(identifier IS NOT NULL,'Reserved SR1 native artifact requires complete exact source owner');
 RETURN NULL;
END $sr$;
DO $sr$ DECLARE n TEXT;BEGIN
 FOREACH n IN ARRAY ARRAY['supplier_return_plans','supplier_return_events','supplier_return_commands','ap_supplier_invoice_credits',
 'ap_supplier_invoices','procurement_partial_receipts','inventory_receipt_plans','inventory_receipt_reviews','inventory_receipt_links','inventory_receipt_commands',
 'inventory_cost_layers','finance_entries','finance_entry_lines','finance_entry_line_dimensions','finance_posting_effects','finance_accounts','finance_journals'] LOOP
  EXECUTE format('CREATE CONSTRAINT TRIGGER supplier_return_closure AFTER INSERT OR UPDATE OR DELETE ON reconforge.%I DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION reconforge.sr_reverse_close()',n);
 END LOOP;
END $sr$;
CREATE CONSTRAINT TRIGGER supplier_return_audit_closure AFTER UPDATE OR DELETE ON reconforge.domain_audit_events DEFERRABLE INITIALLY DEFERRED FOR EACH ROW WHEN(left(OLD.object_id,4)='SR1-') EXECUTE FUNCTION reconforge.sr_reverse_close();
CREATE CONSTRAINT TRIGGER supplier_return_outbox_closure AFTER UPDATE OR DELETE ON reconforge.outbox_events DEFERRABLE INITIALLY DEFERRED FOR EACH ROW WHEN(left(OLD.aggregate_id,4)='SR1-') EXECUTE FUNCTION reconforge.sr_reverse_close();
"""

_WRAPPERS = r"""
ALTER FUNCTION reconforge.pp_guard() RENAME TO pp_guard_pre_supplier_return;
ALTER FUNCTION reconforge.pp_verify_multiline(TEXT,TEXT) RENAME TO pp_verify_multiline_pre_supplier_return;
ALTER FUNCTION reconforge.ops_close_plan(TEXT,TEXT) RENAME TO ops_close_plan_pre_supplier_return;
ALTER FUNCTION reconforge.guard_ap_supplier_invoice_payment_status() RENAME TO ap_payment_status_pre_supplier_return;
DO $sr$ DECLARE definition TEXT;anchor TEXT;
BEGIN
 definition:=pg_get_functiondef('reconforge.pp_guard_pre_supplier_return()'::regprocedure);
 definition:=replace(definition,'reconforge.pp_guard_pre_supplier_return','reconforge.pp_guard');
 definition:=replace(definition,'BEGIN',$body$BEGIN
 IF TG_OP='UPDATE' AND TG_TABLE_NAME='procurement_partial_receipts'
 AND NEW.supplier_return_owner_id IS DISTINCT FROM OLD.supplier_return_owner_id
 AND(to_jsonb(NEW)-'supplier_return_owner_id')=(to_jsonb(OLD)-'supplier_return_owner_id') THEN RETURN NEW; END IF;
$body$);
 EXECUTE definition;
 DROP TRIGGER procurement_partial_receipts_guard ON reconforge.procurement_partial_receipts;
 CREATE TRIGGER procurement_partial_receipts_guard BEFORE UPDATE OR DELETE ON reconforge.procurement_partial_receipts FOR EACH ROW EXECUTE FUNCTION reconforge.pp_guard();
 definition:=pg_get_functiondef('reconforge.ap_payment_status_pre_supplier_return()'::regprocedure);
 definition:=replace(definition,'reconforge.ap_payment_status_pre_supplier_return','reconforge.guard_ap_supplier_invoice_payment_status');
 definition:=replace(definition,'BEGIN',$body$BEGIN
 IF TG_OP='UPDATE' AND NEW.supplier_return_owner_id IS DISTINCT FROM OLD.supplier_return_owner_id
 AND(to_jsonb(NEW)-'supplier_return_owner_id')=(to_jsonb(OLD)-'supplier_return_owner_id') THEN RETURN NEW; END IF;
 IF TG_OP='UPDATE' AND OLD.status='Approved' AND NEW.status='Credited' AND NEW.supplier_return_owner_id=OLD.supplier_return_owner_id
 AND NEW.row_version=OLD.row_version+1 AND(to_jsonb(NEW)-ARRAY['status','row_version','updated_at'])=(to_jsonb(OLD)-ARRAY['status','row_version','updated_at'])
 AND EXISTS(SELECT 1 FROM reconforge.ap_supplier_invoice_credits c WHERE c.tenant_id=NEW.tenant_id AND c.supplier_invoice_id=NEW.id AND c.plan_id=NEW.supplier_return_owner_id AND c.amount_minor=NEW.total_minor) THEN RETURN NEW; END IF;
$body$);
 EXECUTE definition;
 DROP TRIGGER ap_supplier_invoice_payment_status_guard ON reconforge.ap_supplier_invoices;
 CREATE TRIGGER ap_supplier_invoice_payment_status_guard BEFORE UPDATE OR DELETE ON reconforge.ap_supplier_invoices FOR EACH ROW EXECUTE FUNCTION reconforge.guard_ap_supplier_invoice_payment_status();
 definition:=pg_get_functiondef('reconforge.pp_verify_multiline_pre_supplier_return(text,text)'::regprocedure);
 definition:=replace(definition,'reconforge.pp_verify_multiline_pre_supplier_return','reconforge.pp_verify_multiline');
 anchor:='OR EXISTS(SELECT 1 FROM reconforge.inventory_receipt_plans x WHERE x.tenant_id=t AND x.original_plan_id=r.id)';
 IF position(anchor IN definition)=0 THEN RAISE EXCEPTION 'Prior multiline receipt inverse guard differs'; END IF;
 definition:=replace(definition,anchor,'OR EXISTS(SELECT 1 FROM reconforge.inventory_receipt_plans x WHERE x.tenant_id=t AND x.original_plan_id=r.id AND NOT reconforge.sr_inverse_owned(t,x.id))');
 definition:=replace(definition,'h.status NOT IN (''Approved'',''Paid'')','(h.status NOT IN (''Approved'',''Paid'') AND NOT reconforge.sr_credited(t,h.id))');
 anchor:='FOR il IN SELECT * FROM reconforge.procurement_partial_invoice_lines WHERE tenant_id=t AND invoice_id=i.id ORDER BY sequence LOOP';
 IF position(anchor IN definition)=0 THEN RAISE EXCEPTION 'Prior multiline invoice allocation guard differs'; END IF;
 definition:=replace(definition,anchor,$inverse$
 IF EXISTS(SELECT 1 FROM reconforge.finance_entries inverse_entry WHERE inverse_entry.tenant_id=t AND inverse_entry.reverses_posting_id=i.accrual_effect_id
 AND NOT reconforge.sr_inverse_entry(t,i.id,inverse_entry.id))
 OR EXISTS(SELECT 1 FROM reconforge.finance_posting_effects inverse_effect WHERE inverse_effect.tenant_id=t AND inverse_effect.reverses_effect_id=i.accrual_effect_id
 AND NOT reconforge.sr_inverse_entry(t,i.id,inverse_effect.entry_id)) THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='supplier_return_owner',MESSAGE='Original procurement AP inverse requires complete supplier debit and inventory closure'; END IF;
$inverse$||anchor);
 EXECUTE definition;
 definition:=pg_get_functiondef('reconforge.ops_close_plan_pre_supplier_return(text,text)'::regprocedure);
 definition:=replace(definition,'reconforge.ops_close_plan_pre_supplier_return','reconforge.ops_close_plan');
 definition:=replace(definition,'status NOT IN (''Approved'',''Paid'')','(status NOT IN (''Approved'',''Paid'') AND NOT reconforge.sr_credited(t,p.source_id))');
 EXECUTE definition;
END $sr$;
"""

DOWNGRADE_SQL = r"""
DO $sr$ BEGIN IF EXISTS(SELECT 1 FROM reconforge.supplier_return_plans) THEN
 RAISE EXCEPTION 'Retained supplier return evidence requires forward correction or verified pre-upgrade restore'; END IF; END $sr$;
DROP TRIGGER supplier_return_audit_closure ON reconforge.domain_audit_events;
DROP TRIGGER supplier_return_outbox_closure ON reconforge.outbox_events;
DO $sr$ DECLARE n TEXT;BEGIN
 FOREACH n IN ARRAY ARRAY['ap_supplier_invoices','procurement_partial_receipts','inventory_receipt_plans','inventory_receipt_reviews','inventory_receipt_links','inventory_receipt_commands',
 'inventory_cost_layers','finance_entries','finance_entry_lines','finance_entry_line_dimensions','finance_posting_effects','finance_accounts','finance_journals'] LOOP
  EXECUTE format('DROP TRIGGER supplier_return_closure ON reconforge.%I',n);
 END LOOP;
END $sr$;
DROP TRIGGER supplier_return_admission ON reconforge.ap_supplier_invoices;
DROP TRIGGER supplier_return_admission ON reconforge.procurement_partial_receipts;
DROP TRIGGER supplier_return_payment_admission ON reconforge.ap_payment_links;
DROP TRIGGER supplier_return_payment_admission ON reconforge.financial_installment_plans;
DROP TRIGGER procurement_partial_receipts_guard ON reconforge.procurement_partial_receipts;
DROP TRIGGER ap_supplier_invoice_payment_status_guard ON reconforge.ap_supplier_invoices;
DROP FUNCTION reconforge.guard_ap_supplier_invoice_payment_status();
ALTER FUNCTION reconforge.ap_payment_status_pre_supplier_return() RENAME TO guard_ap_supplier_invoice_payment_status;
CREATE TRIGGER ap_supplier_invoice_payment_status_guard BEFORE UPDATE OR DELETE ON reconforge.ap_supplier_invoices FOR EACH ROW EXECUTE FUNCTION reconforge.guard_ap_supplier_invoice_payment_status();
DROP FUNCTION reconforge.pp_guard();
ALTER FUNCTION reconforge.pp_guard_pre_supplier_return() RENAME TO pp_guard;
CREATE TRIGGER procurement_partial_receipts_guard BEFORE UPDATE OR DELETE ON reconforge.procurement_partial_receipts FOR EACH ROW EXECUTE FUNCTION reconforge.pp_guard();
DROP FUNCTION reconforge.pp_verify_multiline(TEXT,TEXT);
ALTER FUNCTION reconforge.pp_verify_multiline_pre_supplier_return(TEXT,TEXT) RENAME TO pp_verify_multiline;
DROP FUNCTION reconforge.ops_close_plan(TEXT,TEXT);
ALTER FUNCTION reconforge.ops_close_plan_pre_supplier_return(TEXT,TEXT) RENAME TO ops_close_plan;
DROP TABLE reconforge.ap_supplier_invoice_credits;
DROP TABLE reconforge.supplier_return_commands;
DROP TABLE reconforge.supplier_return_events;
DROP TABLE reconforge.supplier_return_plans;
DROP FUNCTION reconforge.sr_reverse_close();
DROP FUNCTION reconforge.sr_native_admit();
DROP FUNCTION reconforge.sr_invoice_projection(TEXT,TEXT);
DROP FUNCTION reconforge.sr_inverse_entry(TEXT,TEXT,TEXT);
DROP FUNCTION reconforge.sr_inverse_owned(TEXT,TEXT);
DROP FUNCTION reconforge.sr_credited(TEXT,TEXT);
DROP FUNCTION reconforge.sr_close(TEXT,TEXT);
DROP FUNCTION reconforge.sr_protect();
DROP FUNCTION reconforge.sr_authority(TEXT,TEXT,TEXT,TEXT,TEXT,TEXT);
DROP FUNCTION reconforge.sr_event(TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,JSONB);
DROP FUNCTION reconforge.sr_public(TEXT,TEXT,INTEGER);
DROP FUNCTION reconforge.sr_available(TEXT,TEXT,TEXT,TEXT);
DROP FUNCTION reconforge.sr_source(TEXT,TEXT,TEXT,TEXT);
DROP FUNCTION reconforge.sr_assert(BOOLEAN,TEXT);
ALTER TABLE reconforge.ap_supplier_invoices DROP CONSTRAINT ap_supplier_invoices_status_check;
ALTER TABLE reconforge.ap_supplier_invoices ADD CONSTRAINT ap_supplier_invoices_status_check CHECK(status IN('Draft','Submitted','Matched','Exception','Approved','Paid','Rejected'));
ALTER TABLE reconforge.ap_supplier_invoices DROP COLUMN supplier_return_owner_id;
ALTER TABLE reconforge.procurement_partial_receipts DROP COLUMN supplier_return_owner_id;
"""


_CLOSE = r"""
CREATE FUNCTION reconforge.sr_close(t TEXT,i TEXT) RETURNS VOID LANGUAGE plpgsql SET search_path=pg_catalog AS $sr$
DECLARE p RECORD;r RECORD;l RECORD;c RECORD;h RECORD;d RECORD;inverse RECORD;native_review RECORD;native_link RECORD;credit RECORD;
 e RECORD;f RECORD;v RECORD;command RECORD;part JSONB;s JSONB;original JSONB;expected JSONB;maker TEXT;seal TEXT;ordinal INTEGER:=1;stage INTEGER;
BEGIN
 SELECT * INTO p FROM reconforge.supplier_return_plans WHERE tenant_id=t AND id=i;
 PERFORM reconforge.sr_assert(p.id IS NOT NULL,'Native supplier return effect requires its retained complete source owner');
 SELECT * INTO r FROM reconforge.supplier_return_events WHERE tenant_id=t AND plan_id=i AND operation='review';
 SELECT * INTO l FROM reconforge.supplier_return_events WHERE tenant_id=t AND plan_id=i AND operation='post';
 SELECT * INTO c FROM reconforge.supplier_return_events WHERE tenant_id=t AND plan_id=i AND operation='cancel';
 SELECT * INTO h FROM reconforge.ap_supplier_invoices WHERE tenant_id=t AND id=p.native_invoice_id;
 SELECT * INTO d FROM reconforge.procurement_partial_receipts WHERE tenant_id=t AND id=p.receipt_id;
 s:=reconforge.sr_source(t,p.order_id,p.receipt_id,p.invoice_id);original:=p.payload->'source_snapshot';
 maker:=p.payload->>'preparer_actor_id';seal:=p.payload->>'plan_digest';
 PERFORM reconforge.sr_assert(s IS NOT NULL AND h.id IS NOT NULL AND d.id IS NOT NULL AND reconforge.irp_scope(t,p.workspace_id,p.organization_id,p.legal_entity_id)
 AND reconforge.irp_digest(p.payload-'plan_digest')=seal AND p.payload->>'schema_version'='supplier-return-v1'
 AND(p.payload->>'id',p.payload->>'order_id',p.payload->>'receipt_id',p.payload->>'invoice_id',p.payload->>'native_invoice_id',p.payload->>'number')=(p.id,p.order_id,p.receipt_id,p.invoice_id,p.native_invoice_id,p.number)
 AND(p.payload->>'workspace_id',p.payload->>'organization_id',p.payload->>'legal_entity_id')=(p.workspace_id,p.organization_id,p.legal_entity_id)
 AND(original->'original_plan'->'scope'->>'workspace_id',original->'original_plan'->'scope'->>'organization_id',original->'original_plan'->'scope'->>'legal_entity_id')=(p.workspace_id,p.organization_id,p.legal_entity_id)
 AND p.payload->'request'=jsonb_build_object('order_id',p.order_id,'receipt_id',p.receipt_id,'invoice_id',p.invoice_id,'number',p.number,
 'period_id',p.payload->>'period_id','posting_date',p.payload->>'posting_date','expense_account_code',p.payload->>'expense_account_code','reason',p.payload->>'reason')
 AND(s-ARRAY['invoice_status','invoice_version'])=(original-ARRAY['invoice_status','invoice_version'])
 AND original->>'invoice_status'='Approved' AND original->'order'->>'multiline'='true' AND left(original->'order'->>'number',5)<>'BPC1-'
 AND(original->'receipt'->>'stage')::integer=2 AND(original->'invoice'->>'stage')::integer=4
 AND original->'invoice_line'->>'order_line_id'=d.order_line_id AND(original->'invoice_line'->>'quantity')::numeric=d.quantity
 AND(original->'invoice_line'->>'total_minor')::numeric=d.total_minor AND h.total_minor=d.total_minor AND h.tax_minor=0
 AND(p.payload->>'credit_minor')::numeric=h.total_minor AND(p.payload->>'inventory_removed_minor')::numeric=(original->'original_plan'->'source'->>'total_value_minor')::numeric
 AND(p.payload->>'charge_expense_minor')::numeric=(p.payload->>'inventory_removed_minor')::numeric-h.total_minor
 AND(p.payload->>'charge_expense_minor')::numeric>=0 AND(p.payload->>'amount_minor')::numeric=p.amount_minor AND p.amount_minor::numeric=2*(p.payload->>'inventory_removed_minor')::numeric
 AND(p.payload->>'currency_code',p.payload->>'currency_precision')=(original->'original_plan'->'currency_policy'->>'currency_code',original->'original_plan'->'currency_policy'->>'currency_precision')
 AND(p.phase=2)=(l.plan_id IS NOT NULL) AND(p.phase=3)=(c.plan_id IS NOT NULL) AND(p.phase NOT IN(1,2) OR r.plan_id IS NOT NULL) AND(p.phase<>0 OR r.plan_id IS NULL)
 AND reconforge.sr_event(t,i,p.audit_event_id,p.outbox_event_id,maker,'supplier_return_prepared',jsonb_build_object('plan_digest',seal)),
 'Supplier return phase, exact original quantity/cost/source and preparation evidence must agree');
 PERFORM reconforge.sr_assert(jsonb_typeof(p.payload->'entries')='array' AND COALESCE(jsonb_array_length(p.payload->'entries'),0)=(CASE WHEN(p.payload->>'charge_expense_minor')::numeric=0 THEN 1 ELSE 2 END), 'Return must contain its exact AP inverse and optional original charge expense');
 IF p.phase<>3 THEN
  PERFORM reconforge.sr_assert(h.supplier_return_owner_id=i AND d.supplier_return_owner_id=i
   AND NOT EXISTS(SELECT 1 FROM reconforge.ap_payment_links WHERE tenant_id=t AND supplier_invoice_id=h.id)
   AND NOT EXISTS(SELECT 1 FROM reconforge.financial_installment_plans WHERE tenant_id=t AND source_id=h.id)
   AND(SELECT count(*) FROM reconforge.procurement_partial_invoice_lines WHERE tenant_id=t AND invoice_id=p.invoice_id)=1,
   'Retained return reserves its entire original receipt and unpaid AP residual');
  IF p.phase=2 THEN
   PERFORM reconforge.sr_assert(h.status='Credited' AND h.row_version=(original->>'invoice_version')::integer+1,'Posted debit requires terminal native AP credit without rewriting its original money');
  ELSE
   PERFORM reconforge.sr_assert(h.status='Approved' AND h.row_version=(original->>'invoice_version')::integer,'Unposted return cannot change or pay the original AP invoice');
  END IF;
 ELSE PERFORM reconforge.sr_assert(h.supplier_return_owner_id IS DISTINCT FROM i AND d.supplier_return_owner_id IS DISTINCT FROM i,'Cancelled source claims must release while retaining draft evidence'); END IF;
 SELECT * INTO inverse FROM reconforge.inventory_receipt_plans WHERE tenant_id=t AND id=p.payload->'inverse_plan'->>'plan_id';
 SELECT * INTO native_review FROM reconforge.inventory_receipt_reviews WHERE tenant_id=t AND plan_id=inverse.id;
 SELECT * INTO native_link FROM reconforge.inventory_receipt_links WHERE tenant_id=t AND plan_id=inverse.id;
 PERFORM reconforge.sr_assert(inverse.id IS NOT NULL AND inverse.plan_json=p.payload->'inverse_plan' AND inverse.operation='FullReceiptReversal'
 AND inverse.original_plan_id=d.receipt_plan_id AND inverse.source_number=upper(i) AND inverse.preparer_actor_id=maker
 AND inverse.total_value_minor=(p.payload->>'inventory_removed_minor')::bigint AND inverse.posting_date::text=p.payload->>'posting_date'
 AND inverse.period_id=p.payload->>'period_id' AND inverse.plan_json->'scope'=original->'original_plan'->'scope'
 AND inverse.plan_json->'currency_policy'=original->'original_plan'->'currency_policy' AND inverse.plan_json->'mapping'=original->'original_plan'->'mapping'
 AND(native_review.id IS NOT NULL)=(r.plan_id IS NOT NULL) AND(native_link.id IS NOT NULL)=(p.phase=2)
 AND(r.plan_id IS NULL OR native_review.reviewer_actor_id=r.actor_id), 'Native inverse source and human review must match the whole original receipt');
 IF p.phase IN(0,1) THEN
  PERFORM reconforge.sr_assert(EXISTS(SELECT 1 FROM reconforge.inventory_cost_layers WHERE tenant_id=t AND id=inverse.cost_layer_id
   AND remaining_quantity_scaled=inverse.quantity_scaled AND remaining_value_minor=inverse.total_value_minor)
   AND NOT EXISTS(SELECT 1 FROM reconforge.inventory_layer_consumptions WHERE tenant_id=t AND cost_layer_id=inverse.cost_layer_id)
   AND NOT EXISTS(SELECT 1 FROM reconforge.inventory_valuation_reversal_effects WHERE tenant_id=t AND cost_layer_id=inverse.cost_layer_id),
   'Pending whole supplier return requires its exact unissued original FIFO layer');
 ELSIF p.phase=2 THEN
  PERFORM reconforge.irp_assert_complete(t,inverse.id);
  PERFORM reconforge.sr_assert(native_link.posted_actor_id=l.actor_id AND inverse.posting_effect_id=l.effects->>0,'Native inventory Remove must be posted by the third human in the same return');
 END IF;
 SELECT * INTO credit FROM reconforge.ap_supplier_invoice_credits WHERE tenant_id=t AND plan_id=i;
 PERFORM reconforge.sr_assert((credit.plan_id IS NOT NULL)=(p.phase=2) AND(credit.plan_id IS NULL OR(credit.supplier_invoice_id=h.id AND credit.amount_minor=h.total_minor
  AND credit.original_accrual_effect_id=original->'accrual_effect'->>'id' AND credit.inverse_accrual_effect_id=l.effects->>1 AND credit.inventory_inverse_effect_id=inverse.posting_effect_id)),
  'Native supplier debit must exactly link original AP, inverse AP and removed inventory effects');
 FOR part IN SELECT * FROM jsonb_array_elements(p.payload->'entries') LOOP
  SELECT * INTO e FROM reconforge.finance_entries WHERE tenant_id=t AND id=part->>'entry_id';
  SELECT * INTO f FROM reconforge.finance_posting_effects WHERE tenant_id=t AND entry_id=e.id;
  PERFORM reconforge.sr_assert(e.id IS NOT NULL AND part->'snapshot'=reconforge.fr_snapshot(t,e.id,p.organization_id,p.legal_entity_id)
   AND part->>'validation_digest'=reconforge.irp_digest(part->'snapshot') AND e.preparer_actor_id=maker AND e.external_reference=i
   AND e.posting_date=p.payload->>'posting_date' AND e.period_id=p.payload->>'period_id'
   AND(e.currency_code,e.currency_precision,e.currency_rounding_policy,e.currency_registry_version,e.currency_registry_digest)=
    (inverse.currency_code,inverse.currency_precision,inverse.currency_rounding_policy,inverse.currency_registry_version,inverse.currency_registry_digest)
   AND e.status=(CASE WHEN r.plan_id IS NOT NULL THEN'Validated' ELSE'Draft' END)
   AND(r.plan_id IS NULL OR(e.validator_actor_id=r.actor_id AND e.validation_digest=part->>'validation_digest'))
   AND(f.id IS NOT NULL)=(p.phase=2) AND(f.id IS NULL OR(f.id=l.effects->>ordinal AND f.posted_actor_id=l.actor_id AND f.snapshot_json=part->'snapshot')),
   'Supplier debit GL snapshots, original monetary policy, validation and effects must be exact');
  IF ordinal=1 THEN
   expected:=original->'accrual_effect';
   PERFORM reconforge.sr_assert(part->>'original_effect_id'=expected->>'id' AND e.reverses_posting_id=expected->>'id'
    AND e.source_type='Generated' AND e.journal_id=expected->'snapshot_json'->'entry'->>'journal_id'
    AND NOT EXISTS((SELECT x->>'account_id',x->'credit_minor',x->'debit_minor',x->'dimensions' FROM jsonb_array_elements(expected->'snapshot_json'->'lines') x
     EXCEPT ALL SELECT x->>'account_id',x->'debit_minor',x->'credit_minor',x->'dimensions' FROM jsonb_array_elements(part->'snapshot'->'lines') x)
     UNION ALL(SELECT x->>'account_id',x->'credit_minor',x->'debit_minor',x->'dimensions' FROM jsonb_array_elements(part->'snapshot'->'lines') x
     EXCEPT ALL SELECT x->>'account_id',x->'debit_minor',x->'credit_minor',x->'dimensions' FROM jsonb_array_elements(expected->'snapshot_json'->'lines') x)),
    'Supplier debit must exactly invert original AP accounts dimensions quantities and historical money');
  ELSE
   PERFORM reconforge.sr_assert(e.source_type='Manual' AND e.reverses_posting_id IS NULL AND jsonb_array_length(part->'snapshot'->'lines')=2
    AND EXISTS(SELECT 1 FROM reconforge.finance_entry_lines a JOIN reconforge.finance_accounts b ON b.tenant_id=a.tenant_id AND b.id=a.account_id
     WHERE a.tenant_id=t AND a.entry_id=e.id AND a.line_number=1 AND a.debit_minor=(p.payload->>'charge_expense_minor')::bigint AND a.credit_minor=0
     AND b.account_code=p.payload->>'expense_account_code' AND b.account_type='Expense' AND b.normal_balance='Debit')
    AND EXISTS(SELECT 1 FROM reconforge.finance_entry_lines WHERE tenant_id=t AND entry_id=e.id AND line_number=2
     AND account_id=original->'original_plan'->'mapping'->>'receipt_clearing_account_id' AND credit_minor=(p.payload->>'charge_expense_minor')::bigint AND debit_minor=0),
    'Original paid freight and duty must become exact expense against original receipt clearing; cash stays retained');
  END IF;
  ordinal:=ordinal+1;
 END LOOP;
 FOR v IN SELECT * FROM reconforge.supplier_return_events WHERE tenant_id=t AND plan_id=i LOOP
  PERFORM reconforge.sr_assert(v.actor_id<>maker AND(v.operation NOT IN('post','cancel') OR r.plan_id IS NULL OR v.actor_id<>r.actor_id)
   AND(v.operation='post' OR v.effects='[]'::jsonb) AND(v.operation<>'post' OR jsonb_array_length(v.effects)=ordinal)
   AND reconforge.sr_event(t,i,v.audit_event_id,v.outbox_event_id,v.actor_id,'supplier_return_'||v.operation,
    jsonb_build_object('plan_digest',seal,'reason',v.reason,'effects',v.effects)), 'Supplier return lifecycle requires three human duties and exact audit/outbox evidence');
 END LOOP;
 FOR command IN SELECT * FROM reconforge.supplier_return_commands WHERE tenant_id=t AND plan_id=i LOOP
  stage:=CASE command.operation WHEN'prepare' THEN 0 WHEN'review' THEN 1 WHEN'post' THEN 2 ELSE 3 END;
  PERFORM reconforge.sr_assert(command.request_digest=reconforge.irp_digest(command.request_json)
   AND command.request_json->>'operation'=command.operation AND command.request_json->>'actor_id'=command.actor_id AND command.workspace_id=p.workspace_id
   AND command.response_json=reconforge.sr_public(t,i,stage)
   AND command.actor_id=(CASE stage WHEN 0 THEN maker WHEN 1 THEN r.actor_id WHEN 2 THEN l.actor_id ELSE c.actor_id END)
   AND command.request_json->'request'=(CASE WHEN stage=0 THEN p.payload->'request' ELSE jsonb_build_object('plan_id',i,'expected_plan_digest',seal,'reason',
    CASE stage WHEN 1 THEN r.reason WHEN 2 THEN l.reason ELSE c.reason END) END), 'Return replay requires its exact original request acknowledgement and authorized actor');
 END LOOP;
 PERFORM reconforge.sr_assert(EXISTS(SELECT 1 FROM reconforge.supplier_return_commands WHERE tenant_id=t AND plan_id=i AND operation='prepare')
  AND(r.plan_id IS NULL OR EXISTS(SELECT 1 FROM reconforge.supplier_return_commands WHERE tenant_id=t AND plan_id=i AND operation='review'))
  AND(l.plan_id IS NULL OR EXISTS(SELECT 1 FROM reconforge.supplier_return_commands WHERE tenant_id=t AND plan_id=i AND operation='post'))
  AND(c.plan_id IS NULL OR EXISTS(SELECT 1 FROM reconforge.supplier_return_commands WHERE tenant_id=t AND plan_id=i AND operation='cancel')),
  'Every supplier return phase must retain its immutable command');
END $sr$;
"""

UPGRADE_SQL = _TABLES + _CLOSE + _NATIVE + _WRAPPERS


def install_postgres_supplier_returns(connection: Any) -> None:
    if connection.execute("SELECT to_regclass('reconforge.supplier_return_plans') AS installed").fetchone()["installed"] is None:
        with connection.transaction():
            connection.execute(UPGRADE_SQL)
