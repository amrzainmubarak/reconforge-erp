"""Additive CR2 custody over the existing AR, FIFO and source-owned GL.

New-owner storage/closure is installed by the same migration. These invoker
helpers classify ownership through the original invoice FK, never by an empty
private-plan lookup. The existing cost-layer definer retains its owner and ACL;
only its immutable-history equation is extended, with invoker deferred closure.
"""

HEADER_SQL = r"""
ALTER TABLE reconforge.ar_invoices ADD COLUMN customer_partial_return_source_id TEXT;
ALTER TABLE reconforge.ar_invoices ADD CONSTRAINT ar_invoice_partial_return_source
 FOREIGN KEY(tenant_id,customer_partial_return_source_id)
 REFERENCES reconforge.customer_partial_return_sources(tenant_id,id);
CREATE FUNCTION reconforge.customer_partial_return_credit(t TEXT,i TEXT) RETURNS NUMERIC
 LANGUAGE plpgsql VOLATILE SET search_path=pg_catalog AS $cr2shared$
DECLARE h RECORD;s RECORD;credited NUMERIC;
BEGIN
 SELECT * INTO h FROM reconforge.ar_invoices WHERE tenant_id=t AND id=i;
 IF h IS NULL THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Invoice is outside current source authority'; END IF;
 IF h.customer_partial_return_source_id IS NULL THEN RETURN 0; END IF;
 SELECT * INTO s FROM reconforge.customer_partial_return_sources WHERE tenant_id=t AND id=h.customer_partial_return_source_id;
 IF s IS NULL OR(s.invoice_id,s.customer_id,s.workspace_id,s.organization_id,s.legal_entity_id,s.gross_minor)
 IS DISTINCT FROM(h.id,h.customer_id,h.workspace_id,h.organization_id,h.legal_entity_id,h.total_minor)
 OR NOT reconforge.irp_scope(t,s.workspace_id,s.organization_id,s.legal_entity_id)
 OR h.customer_return_owner_id IS NOT NULL THEN
  RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Partial invoice requires its exact visible structural source'; END IF;
 SELECT COALESCE(sum(CASE kind WHEN 'Return' THEN credit_minor WHEN 'ReverseReturn' THEN -credit_minor ELSE 0 END),0)
 INTO credited FROM reconforge.customer_partial_return_history WHERE tenant_id=t AND source_id=s.id;
 IF credited<0 OR credited>h.total_minor THEN
  RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Partial invoice credit exceeds its original economic source'; END IF;
 RETURN credited;
END $cr2shared$;
CREATE FUNCTION reconforge.customer_partial_return_outstanding(t TEXT,i TEXT) RETURNS NUMERIC
 LANGUAGE plpgsql VOLATILE SET search_path=pg_catalog AS $cr2shared$
DECLARE gross NUMERIC;collected NUMERIC;credited NUMERIC;
BEGIN
 credited:=reconforge.customer_partial_return_credit(t,i);
 SELECT total_minor INTO gross FROM reconforge.ar_invoices WHERE tenant_id=t AND id=i;
 SELECT COALESCE(sum(amount_minor),0) INTO collected FROM reconforge.ar_receipt_allocations WHERE tenant_id=t AND invoice_id=i;
 RETURN greatest(gross-collected-credited,0);
END $cr2shared$;
CREATE FUNCTION reconforge.customer_partial_return_invoice_credited(t TEXT,i TEXT) RETURNS BOOLEAN
 LANGUAGE plpgsql VOLATILE SET search_path=pg_catalog AS $cr2shared$
DECLARE marker TEXT;
BEGIN
 SELECT customer_partial_return_source_id INTO marker FROM reconforge.ar_invoices WHERE tenant_id=t AND id=i;
 IF marker IS NULL THEN RETURN FALSE; END IF;
 RETURN reconforge.customer_partial_return_credit(t,i)>0;
END $cr2shared$;
CREATE FUNCTION reconforge.customer_partial_return_settle_invoice(t TEXT,sid TEXT) RETURNS VOID
 LANGUAGE plpgsql VOLATILE SET search_path=pg_catalog AS $cr2shared$
DECLARE s RECORD;h RECORD;collected NUMERIC;credited NUMERIC;state TEXT;
BEGIN
 SELECT * INTO s FROM reconforge.customer_partial_return_sources WHERE tenant_id=t AND id=sid;
 IF s IS NULL OR NOT reconforge.irp_scope(t,s.workspace_id,s.organization_id,s.legal_entity_id) THEN
  RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Partial settlement needs its current original source'; END IF;
 PERFORM id FROM reconforge.ar_customers WHERE tenant_id=t AND id=s.customer_id FOR UPDATE;
 SELECT * INTO h FROM reconforge.ar_invoices WHERE tenant_id=t AND id=s.invoice_id FOR UPDATE;
 IF h.customer_partial_return_source_id IS DISTINCT FROM sid OR h.status NOT IN('Approved','PartiallyPaid','Paid') THEN
  RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Partial settlement cannot discard approved original invoice history'; END IF;
 credited:=reconforge.customer_partial_return_credit(t,h.id);
 SELECT COALESCE(sum(amount_minor),0) INTO collected FROM reconforge.ar_receipt_allocations WHERE tenant_id=t AND invoice_id=h.id;
 state:=CASE WHEN collected+credited>=h.total_minor THEN 'Paid' WHEN collected+credited>0 THEN 'PartiallyPaid' ELSE 'Approved' END;
 UPDATE reconforge.ar_invoices SET status=state,row_version=row_version+1,updated_at=now() WHERE tenant_id=t AND id=h.id;
END $cr2shared$;
CREATE FUNCTION reconforge.customer_partial_return_invoice_guard() RETURNS trigger
 LANGUAGE plpgsql VOLATILE SET search_path=pg_catalog AS $cr2shared$
DECLARE s RECORD;marker TEXT;
BEGIN
 marker:=NEW.customer_partial_return_source_id;
 IF TG_OP='UPDATE' AND OLD.customer_partial_return_source_id IS NOT NULL
 AND marker IS DISTINCT FROM OLD.customer_partial_return_source_id THEN
  RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Original partial-return source ownership is immutable'; END IF;
 IF marker IS NULL THEN RETURN NEW; END IF;
 SELECT * INTO s FROM reconforge.customer_partial_return_sources WHERE tenant_id=NEW.tenant_id AND id=marker;
 IF s IS NULL OR(s.invoice_id,s.customer_id,s.workspace_id,s.organization_id,s.legal_entity_id,s.gross_minor)
 IS DISTINCT FROM(NEW.id,NEW.customer_id,NEW.workspace_id,NEW.organization_id,NEW.legal_entity_id,NEW.total_minor)
 OR NEW.customer_return_owner_id IS NOT NULL OR NEW.status NOT IN('Approved','PartiallyPaid','Paid') THEN
  RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Partial and whole credits require separate exact original source ownership'; END IF;
 RETURN NEW;
END $cr2shared$;
CREATE TRIGGER customer_partial_return_invoice_guard BEFORE INSERT OR UPDATE ON reconforge.ar_invoices
 FOR EACH ROW EXECUTE FUNCTION reconforge.customer_partial_return_invoice_guard();
CREATE FUNCTION reconforge.customer_partial_return_allocation_guard() RETURNS trigger
 LANGUAGE plpgsql VOLATILE SET search_path=pg_catalog AS $cr2shared$
DECLARE h RECORD;r RECORD;delta NUMERIC;allocated NUMERIC;credited NUMERIC;receipt_allocated NUMERIC;
BEGIN
 IF TG_OP='DELETE' THEN
  SELECT * INTO h FROM reconforge.ar_invoices WHERE tenant_id=OLD.tenant_id AND id=OLD.invoice_id;
 ELSE
  SELECT * INTO h FROM reconforge.ar_invoices WHERE tenant_id=NEW.tenant_id AND id=NEW.invoice_id;
 END IF;
 IF h IS NULL THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Allocation requires a visible original invoice'; END IF;
 IF TG_OP='UPDATE' THEN
  IF NOT EXISTS(SELECT 1 FROM reconforge.ar_invoices WHERE tenant_id=OLD.tenant_id AND id=OLD.invoice_id) THEN
   RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Allocation cannot move hidden original source history'; END IF;
  IF EXISTS(SELECT 1 FROM reconforge.ar_invoices WHERE tenant_id=OLD.tenant_id AND id=OLD.invoice_id
   AND customer_partial_return_source_id IS NOT NULL) OR h.customer_partial_return_source_id IS NOT NULL THEN
   IF(to_jsonb(NEW)-'amount_minor') IS DISTINCT FROM(to_jsonb(OLD)-'amount_minor') OR NEW.amount_minor<=OLD.amount_minor THEN
    RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Partial-source allocations allow only positive same-source deltas'; END IF;
  END IF;
 END IF;
 IF h.customer_partial_return_source_id IS NULL THEN RETURN COALESCE(NEW,OLD); END IF;
 IF TG_OP='DELETE' THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Partial-source allocations are immutable history'; END IF;
 PERFORM id FROM reconforge.ar_customers WHERE tenant_id=h.tenant_id AND id=h.customer_id FOR UPDATE;
 SELECT * INTO h FROM reconforge.ar_invoices WHERE tenant_id=NEW.tenant_id AND id=NEW.invoice_id FOR UPDATE;
 SELECT * INTO r FROM reconforge.ar_receipts WHERE tenant_id=NEW.tenant_id AND id=NEW.receipt_id FOR UPDATE;
 IF r IS NULL OR h.status NOT IN('Approved','PartiallyPaid') OR r.status<>'Posted'
 OR(NEW.workspace_id,r.workspace_id,r.organization_id,r.legal_entity_id,r.customer_id,r.currency_code)
 IS DISTINCT FROM(h.workspace_id,h.workspace_id,h.organization_id,h.legal_entity_id,h.customer_id,h.currency_code)
 OR(r.currency_precision,r.currency_rounding_policy,r.currency_registry_version,r.currency_registry_digest)
 IS DISTINCT FROM(h.currency_precision,h.currency_rounding_policy,h.currency_registry_version,h.currency_registry_digest)
 OR EXISTS(SELECT 1 FROM reconforge.customer_partial_return_plans WHERE tenant_id=h.tenant_id
 AND source_id=h.customer_partial_return_source_id AND phase IN(0,1)) THEN
  RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Collection needs the original open invoice policy and no competing partial command'; END IF;
 delta:=NEW.amount_minor-CASE WHEN TG_OP='UPDATE' THEN OLD.amount_minor ELSE 0 END;
 credited:=reconforge.customer_partial_return_credit(h.tenant_id,h.id);
 SELECT COALESCE(sum(amount_minor),0) INTO allocated FROM reconforge.ar_receipt_allocations WHERE tenant_id=h.tenant_id AND invoice_id=h.id;
 SELECT COALESCE(sum(amount_minor),0) INTO receipt_allocated FROM reconforge.ar_receipt_allocations WHERE tenant_id=r.tenant_id AND receipt_id=r.id;
 IF delta<=0 OR delta>greatest(h.total_minor-credited-allocated,0) OR receipt_allocated+delta>r.amount_minor THEN
  RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Collection delta exceeds its prefix-time invoice or receipt residual'; END IF;
 RETURN NEW;
END $cr2shared$;
CREATE TRIGGER customer_partial_return_allocation_guard BEFORE INSERT OR UPDATE OR DELETE ON reconforge.ar_receipt_allocations
 FOR EACH ROW EXECUTE FUNCTION reconforge.customer_partial_return_allocation_guard();
CREATE FUNCTION reconforge.customer_partial_return_allocation_history() RETURNS trigger
 LANGUAGE plpgsql VOLATILE SET search_path=pg_catalog AS $cr2shared$
DECLARE sid TEXT;delta BIGINT;
BEGIN
 SELECT customer_partial_return_source_id INTO sid FROM reconforge.ar_invoices WHERE tenant_id=NEW.tenant_id AND id=NEW.invoice_id;
 IF sid IS NULL THEN RETURN NEW; END IF;
 delta:=NEW.amount_minor-CASE WHEN TG_OP='UPDATE' THEN OLD.amount_minor ELSE 0 END;
 PERFORM reconforge.customer_partial_return_history_append_collection(NEW.tenant_id,sid,NEW.receipt_id,NEW.id,delta);
 RETURN NEW;
END $cr2shared$;
CREATE TRIGGER customer_partial_return_allocation_history AFTER INSERT OR UPDATE ON reconforge.ar_receipt_allocations
 FOR EACH ROW EXECUTE FUNCTION reconforge.customer_partial_return_allocation_history();
CREATE FUNCTION reconforge.customer_partial_return_header_close() RETURNS trigger
 LANGUAGE plpgsql SET search_path=pg_catalog AS $cr2shared$
DECLARE sid TEXT;
BEGIN
 IF TG_TABLE_NAME='ar_invoices' THEN sid:=NEW.customer_partial_return_source_id;
 ELSE SELECT customer_partial_return_source_id INTO sid FROM reconforge.ar_invoices WHERE tenant_id=NEW.tenant_id AND id=NEW.invoice_id;
 END IF;
 IF sid IS NOT NULL THEN PERFORM reconforge.customer_partial_return_source_close(NEW.tenant_id,sid); END IF;
 RETURN NULL;
END $cr2shared$;
CREATE CONSTRAINT TRIGGER customer_partial_return_header_close AFTER INSERT OR UPDATE ON reconforge.ar_invoices
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION reconforge.customer_partial_return_header_close();
CREATE CONSTRAINT TRIGGER customer_partial_return_allocation_close AFTER INSERT OR UPDATE ON reconforge.ar_receipt_allocations
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION reconforge.customer_partial_return_header_close();
"""

NATIVE_SOURCE_SQL = r"""
DO $cr2clone$ DECLARE definition TEXT;anchor TEXT:='reconforge.customer_return_source(';
 invoice_anchor TEXT:='''customer_return_owner_id'',''status''';
BEGIN
 definition:=pg_get_functiondef('reconforge.customer_return_source(text,text)'::regprocedure);
 IF length(definition)-length(replace(definition,anchor,''))<>length(anchor)
 OR length(definition)-length(replace(definition,invoice_anchor,''))<>length(invoice_anchor) THEN
 RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Original partial native source contract differs'; END IF;
 definition:=replace(definition,invoice_anchor,'''customer_return_owner_id'',''customer_partial_return_source_id'',''status''');
 EXECUTE replace(definition,anchor,'reconforge.customer_partial_return_native_source(');
END $cr2clone$;
"""

NATIVE_DISPATCH_SQL = r"""
CREATE FUNCTION reconforge.customer_partial_return_native_close() RETURNS trigger
 LANGUAGE plpgsql SET search_path=pg_catalog AS $cr2native$
DECLARE changes JSONB[];changed JSONB;candidate TEXT;entry_id TEXT;movement_id TEXT;original_effect TEXT;original_owner TEXT;
 number TEXT;p RECORD;
BEGIN
 changes:=CASE TG_OP WHEN 'INSERT' THEN ARRAY[to_jsonb(NEW)] WHEN 'DELETE' THEN ARRAY[to_jsonb(OLD)] ELSE ARRAY[to_jsonb(OLD),to_jsonb(NEW)] END;
 FOREACH changed IN ARRAY changes LOOP
  candidate:=NULL;entry_id:=NULL;movement_id:=NULL;original_effect:=NULL;original_owner:=NULL;number:=NULL;
  IF TG_TABLE_NAME IN('domain_audit_events','outbox_events') THEN
   candidate:=CASE TG_TABLE_NAME WHEN 'domain_audit_events' THEN changed->>'object_id' ELSE changed->>'aggregate_id' END;
  ELSIF TG_TABLE_NAME='inventory_movements' THEN
   candidate:=changed->>'source_reference';number:=changed->>'movement_number';movement_id:=changed->>'id';
  ELSIF TG_TABLE_NAME='inventory_movement_lines' THEN
   movement_id:=changed->>'movement_id';
   SELECT source_reference,movement_number INTO candidate,number FROM reconforge.inventory_movements
   WHERE tenant_id=changed->>'tenant_id' AND id=changed->>'movement_id';
  ELSE
   IF TG_TABLE_NAME='finance_entries' THEN
    entry_id:=changed->>'id';candidate:=changed->>'external_reference';number:=changed->>'entry_number';
    original_effect:=changed->>'reverses_posting_id';
   ELSIF TG_TABLE_NAME='finance_entry_line_dimensions' THEN
    SELECT detail.entry_id INTO entry_id FROM reconforge.finance_entry_lines detail
    WHERE detail.tenant_id=changed->>'tenant_id' AND detail.id=changed->>'entry_line_id';
   ELSE entry_id:=changed->>'entry_id'; END IF;
   IF TG_TABLE_NAME<>'finance_entries' THEN
    SELECT e.external_reference,e.entry_number,e.reverses_posting_id INTO candidate,number,original_effect
    FROM reconforge.finance_entries e WHERE e.tenant_id=changed->>'tenant_id' AND e.id=entry_id;
   END IF;
   IF TG_TABLE_NAME='finance_posting_effects' THEN original_effect:=COALESCE(changed->>'reverses_effect_id',original_effect); END IF;
   IF original_effect IS NOT NULL THEN
    SELECT e.external_reference INTO original_owner FROM reconforge.finance_posting_effects f
    JOIN reconforge.finance_entries e ON(e.tenant_id,e.id)=(f.tenant_id,f.entry_id)
    WHERE f.tenant_id=changed->>'tenant_id' AND f.id=original_effect;
    IF COALESCE(original_owner,'')~'^(CR2|CRF2|CR2R|CRF2R)-[a-f0-9]{32}$' THEN
     SELECT plan.* INTO p FROM reconforge.customer_partial_return_plans plan
     WHERE plan.tenant_id=changed->>'tenant_id' AND plan.original_id=original_owner AND plan.operation IN('ReverseReturn','ReverseRefund')
     AND EXISTS(SELECT 1 FROM jsonb_array_elements(plan.payload->'entries') x
      WHERE x->>'entry_id'=entry_id AND x->>'original_effect_id'=original_effect);
     IF p IS NULL THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Partial correction inverse requires its complete native reverse owner'; END IF;
     PERFORM reconforge.customer_partial_return_close(p.tenant_id,p.id);
     PERFORM reconforge.customer_partial_return_close(p.tenant_id,original_owner);
     candidate:=p.id;
    END IF;
   END IF;
  END IF;
  IF COALESCE(candidate,'')~'^(CR2|CRF2|CR2R|CRF2R)-[a-f0-9]{32}$' THEN
   SELECT * INTO p FROM reconforge.customer_partial_return_plans WHERE tenant_id=changed->>'tenant_id' AND id=candidate;
   IF p IS NULL OR(entry_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM jsonb_array_elements(p.payload->'entries') x WHERE x->>'entry_id'=entry_id))
   OR(movement_id IS NOT NULL AND p.payload->>'movement_id' IS DISTINCT FROM movement_id) THEN
    RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Extra native rows cannot borrow an existing partial source reference'; END IF;
   PERFORM reconforge.customer_partial_return_close(changed->>'tenant_id',candidate);
  ELSIF COALESCE(number,'')~*'^(CR2|CRF2|CR2R|CRF2R)-' THEN
   RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Reserved partial native namespace requires its exact source owner';
  END IF;
 END LOOP;
 RETURN NULL;
END $cr2native$;
DO $cr2native$ DECLARE n TEXT; BEGIN
 FOREACH n IN ARRAY ARRAY['finance_entries','finance_entry_lines','finance_entry_line_dimensions','finance_posting_effects',
 'inventory_movements','inventory_movement_lines','domain_audit_events','outbox_events'] LOOP
  EXECUTE format('CREATE CONSTRAINT TRIGGER customer_partial_return_native_close AFTER INSERT OR UPDATE OR DELETE ON reconforge.%I DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION reconforge.customer_partial_return_native_close()',n);
 END LOOP;
END $cr2native$;
"""

# Each exact replacement refuses absent/duplicated/drifted anchors. Neither an
# owner ACL nor the privileged scope/volatility contract is replaced by this patch.
_PATCHES = (
    ("reconforge.inventory_cost_layer_guard()",
     "(SELECT COALESCE(SUM(CASE effect_type WHEN 'Restore' THEN quantity_scaled ELSE -quantity_scaled END),0) FROM reconforge.inventory_valuation_reversal_effects WHERE tenant_id=OLD.tenant_id AND cost_layer_id=OLD.id)",
     "+(SELECT COALESCE(SUM(direction::numeric*quantity_scaled),0) FROM reconforge.customer_partial_return_restorations WHERE tenant_id=OLD.tenant_id AND cost_layer_id=OLD.id)"),
    ("reconforge.inventory_cost_layer_guard()",
     "(SELECT COALESCE(SUM(CASE effect_type WHEN 'Restore' THEN value_minor ELSE -value_minor END),0) FROM reconforge.inventory_valuation_reversal_effects WHERE tenant_id=OLD.tenant_id AND cost_layer_id=OLD.id)",
     "+(SELECT COALESCE(SUM(direction::numeric*value_minor),0) FROM reconforge.customer_partial_return_restorations WHERE tenant_id=OLD.tenant_id AND cost_layer_id=OLD.id)"),
    ("reconforge.guard_inventory_receipt_layer_history_complete()",
     " IF layer IS NULL OR (layer.remaining_quantity_scaled::numeric,layer.remaining_value_minor::numeric) IS DISTINCT FROM (expected_quantity,expected_value) THEN",
     ""),
)

_HISTORY_ADDITION = r"""
 SELECT expected_quantity+COALESCE(sum(direction::numeric*quantity_scaled),0),
 expected_value+COALESCE(sum(direction::numeric*value_minor),0) INTO expected_quantity,expected_value
 FROM reconforge.customer_partial_return_restorations WHERE tenant_id=NEW.tenant_id AND cost_layer_id=NEW.cost_layer_id;
"""


def _literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _patch_sql(function: str, before: str, after: str) -> str:
    return """DO $cr2patch$ DECLARE definition TEXT;anchor TEXT:=""" + _literal(before) + ";replacement TEXT:=" + _literal(after) + r""";
BEGIN
 definition:=pg_get_functiondef(""" + _literal(function) + r"""::regprocedure);
 IF length(definition)-length(replace(definition,anchor,''))<>length(anchor) THEN
 RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Original CR2 shared native function contract differs'; END IF;
 EXECUTE replace(definition,anchor,replacement);
END $cr2patch$;
"""


APPROVED_ORIGINAL_BODIES = {
    "reconforge.collection_close(text,text)": "6c64c9f2f9c3e1deb6ae4e358a0c84b538217fcb00f5e80c2100c7092aa7715c",
    "reconforge.collection_invoice_close(text,text)": "49eccc83586e47cbeb176423e0ead385714fd45d9dd5fda791033c4618704266",
    "reconforge.customer_return_source(text,text)": "7ebddc85f30c68a20d28d05ec0a6c27548a33c79fca125488e00024498a15acf",
    "reconforge.guard_inventory_receipt_layer_history_complete()": "bf9128eee5cd9b8b5924d5d27682e7c74a953902c0821b3cc7946cc84a1c7360",
    "reconforge.inventory_cost_layer_guard()": "4a40f02d67eb6eb9486880ee4b44876fc163eafb8d0a2ef8c32cc4912c10981b",
    "reconforge.stock_sales_close(text,text)": "8e510df4c82daa5ab3964748d6878573777b55eadbf1e9c394783dd11b86cd39",
    "reconforge.customer_return_projection(text,text)": "4a7b602dc01751dad68c0b066114764664f813e829652a5997c295a1655b8e85",
}


def _original_function_preflight() -> str:
    clauses = []
    for signature, body_digest in APPROVED_ORIGINAL_BODIES.items():
        definer = signature == "reconforge.inventory_cost_layer_guard()"
        stable = signature in {"reconforge.customer_return_source(text,text)", "reconforge.customer_return_projection(text,text)"}
        configuration = "search_path=pg_catalog, reconforge" if definer else "search_path=pg_catalog"
        clauses.append("SELECT * INTO f FROM pg_proc WHERE oid=to_regprocedure(" + _literal(signature) + ");\n"
                       + "IF f.oid IS NULL OR f.prosecdef IS DISTINCT FROM " + ("TRUE" if definer else "FALSE")
                       + " OR f.provolatile<>" + _literal("s" if stable else "v")
                       + " OR f.proconfig IS DISTINCT FROM ARRAY[" + _literal(configuration) + "]::text[]"
                       + " OR encode(sha256(convert_to(f.prosrc,'UTF8')),'hex')<>" + _literal(body_digest)
                       + " THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Original partial correction shared function drift'; END IF;\n")
    return "DO $cr2pin$ DECLARE f RECORD; BEGIN\n" + "".join(clauses) + "END $cr2pin$;\n"


_FORWARD = tuple((function, anchor, anchor + addition) for function, anchor, addition in _PATCHES[:2]) + (
    (_PATCHES[2][0], _PATCHES[2][1], _HISTORY_ADDITION + _PATCHES[2][1]),
    ("reconforge.customer_return_source(text,text)", "WHERE s.tenant_id=t AND s.id=i\n",
     "WHERE s.tenant_id=t AND s.id=i AND h.customer_partial_return_source_id IS NULL\n"),
    ("reconforge.customer_return_source(text,text)", "'customer_return_owner_id','status'",
     "'customer_return_owner_id','customer_partial_return_source_id','status'"),
    ("reconforge.collection_close(text,text)", "OR allocated+p.amount_minor>h.total_minor THEN",
     "OR p.amount_minor>reconforge.customer_partial_return_outstanding(t,p.source_id) THEN"),
    ("reconforge.collection_invoice_close(text,text)",
     "CASE WHEN paid=0 THEN'Approved' WHEN paid=h.total_minor THEN'Paid' ELSE'PartiallyPaid' END",
     "CASE WHEN paid+reconforge.customer_partial_return_credit(t,i)>=h.total_minor THEN'Paid' WHEN paid+reconforge.customer_partial_return_credit(t,i)=0 THEN'Approved' ELSE'PartiallyPaid' END"),
    ("reconforge.stock_sales_close(text,text)", "NOT reconforge.customer_return_credited(t,d.invoice_id)",
     "NOT reconforge.customer_return_credited(t,d.invoice_id) AND NOT reconforge.customer_partial_return_invoice_credited(t,d.invoice_id)"),
    ("reconforge.customer_return_projection(text,text)",
     " SELECT customer_return_owner_id INTO marker FROM reconforge.ar_invoices WHERE tenant_id=t AND id=i;",
     r""" SELECT customer_partial_return_source_id INTO marker FROM reconforge.ar_invoices WHERE tenant_id=t AND id=i;
 IF marker IS NOT NULL THEN
  PERFORM reconforge.customer_partial_return_source_close(t,marker);
  RETURN reconforge.customer_partial_return_balance(t,marker)||jsonb_build_object('partial_return_source_id',marker,'pending_return_id',
   (SELECT id FROM reconforge.customer_partial_return_plans WHERE tenant_id=t AND source_id=marker AND phase IN(0,1)));
 END IF;
 SELECT customer_return_owner_id INTO marker FROM reconforge.ar_invoices WHERE tenant_id=t AND id=i;"""),
)

UPGRADE_SQL = _original_function_preflight() + HEADER_SQL + NATIVE_SOURCE_SQL + NATIVE_DISPATCH_SQL + "".join(_patch_sql(*patch) for patch in _FORWARD)

# Existing receipt bootstrap is also used after a completed migration. Preserve
# the additive history equation when that original installer recreates its own
# function; never accept duplicate additions or an unknown invoker contract.
RECEIPT_REINSTALL_SQL = r"""DO $cr2receipt$ DECLARE definition TEXT;f RECORD;
 anchor TEXT:=""" + _literal(_PATCHES[2][1]) + ";addition TEXT:=" + _literal(_HISTORY_ADDITION) + r""";
BEGIN
 IF to_regclass('reconforge.customer_partial_return_restorations') IS NULL THEN RETURN; END IF;
 SELECT * INTO f FROM pg_proc WHERE oid='reconforge.guard_inventory_receipt_layer_history_complete()'::regprocedure;
 IF f.prosecdef OR f.provolatile<>'v' OR f.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog']::text[] THEN
  RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Receipt partial history needs its original invoker function contract'; END IF;
 IF encode(sha256(convert_to(f.prosrc,'UTF8')),'hex') NOT IN
 ('bf9128eee5cd9b8b5924d5d27682e7c74a953902c0821b3cc7946cc84a1c7360',
 '36bb52aa1f57f289d8ea3b2cd8bc1ad03c074918670a6b2d4e65646fd7da609c') THEN
  RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Receipt partial history refuses an unrecognized function body'; END IF;
 definition:=pg_get_functiondef(f.oid);
 IF position(addition IN definition)>0 THEN
  IF length(definition)-length(replace(definition,addition,''))<>length(addition) THEN
   RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Partial receipt history addition is duplicated'; END IF;
  RETURN;
 END IF;
 IF length(definition)-length(replace(definition,anchor,''))<>length(anchor) THEN
  RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Original receipt layer closure drifted during reinstallation'; END IF;
 EXECUTE replace(definition,anchor,addition||anchor);
END $cr2receipt$;
"""

DOWNGRADE_PREFLIGHT_SQL = r"""
DO $cr2shared$ BEGIN
 IF EXISTS(SELECT 1 FROM reconforge.customer_partial_return_sources)
 OR EXISTS(SELECT 1 FROM reconforge.ar_invoices WHERE customer_partial_return_source_id IS NOT NULL) THEN
 RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Retained partial source history prevents destructive downgrade; restore the compatible backup'; END IF;
END $cr2shared$;
"""

DOWNGRADE_SQL = "".join(_patch_sql(function, after, before) for function, before, after in reversed(_FORWARD)) + _original_function_preflight() + r"""
DO $cr2native$ DECLARE n TEXT; BEGIN
 FOREACH n IN ARRAY ARRAY['finance_entries','finance_entry_lines','finance_entry_line_dimensions','finance_posting_effects',
 'inventory_movements','inventory_movement_lines','domain_audit_events','outbox_events'] LOOP
  EXECUTE format('DROP TRIGGER customer_partial_return_native_close ON reconforge.%I',n);
 END LOOP;
END $cr2native$;
DROP FUNCTION reconforge.customer_partial_return_native_close();
DROP TRIGGER customer_partial_return_allocation_close ON reconforge.ar_receipt_allocations;
DROP TRIGGER customer_partial_return_header_close ON reconforge.ar_invoices;
DROP TRIGGER customer_partial_return_allocation_history ON reconforge.ar_receipt_allocations;
DROP TRIGGER customer_partial_return_allocation_guard ON reconforge.ar_receipt_allocations;
DROP TRIGGER customer_partial_return_invoice_guard ON reconforge.ar_invoices;
DROP FUNCTION reconforge.customer_partial_return_header_close();
DROP FUNCTION reconforge.customer_partial_return_allocation_history();
DROP FUNCTION reconforge.customer_partial_return_allocation_guard();
DROP FUNCTION reconforge.customer_partial_return_invoice_guard();
DROP FUNCTION reconforge.customer_partial_return_settle_invoice(TEXT,TEXT);
DROP FUNCTION reconforge.customer_partial_return_invoice_credited(TEXT,TEXT);
DROP FUNCTION reconforge.customer_partial_return_outstanding(TEXT,TEXT);
DROP FUNCTION reconforge.customer_partial_return_credit(TEXT,TEXT);
DROP FUNCTION reconforge.customer_partial_return_native_source(TEXT,TEXT);
ALTER TABLE reconforge.ar_invoices DROP CONSTRAINT ar_invoice_partial_return_source;
ALTER TABLE reconforge.ar_invoices DROP COLUMN customer_partial_return_source_id;
"""
