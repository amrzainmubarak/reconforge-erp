"""Native physical witnesses for fixed monetary Stock and CR3 corrections.

Existing148 positive/zero valuation admission is copied into a new namespace,
with functional currency explicit. Neither a caller GUC nor a Generated label
alone authorizes stock: actual native plans, actors, consumptions, financial
effects and immutable original layer witnesses must agree.
"""

from reconforge.infrastructure.postgres_customer_partial_return_zero_stock_hooks import ADMISSION_SQL, FACTS_SQL
from reconforge.infrastructure.postgres_monetary_stock_shared_hooks import _definition


def _replace(value: str, old: str, new: str) -> str:
    if value.count(old) != 1:
        raise ValueError("One retained physical-admission anchor is required.")
    return value.replace(old, new, 1)


def _zero_cost() -> str:
    value = _definition("customer_partial_return_zero_stock_cost", ADMISSION_SQL, "$cr148zs$")
    value = _replace(value, "customer_partial_return_zero_stock_cost(", "monetary_stock_zero_cost(")
    value = _replace(value, "LANGUAGE plpgsql STABLE", "LANGUAGE plpgsql VOLATILE")
    value = _replace(value, "cost->>'schema_version'='inventory-transfer-cost-v3'",
        "cost->>'schema_version' IN('inventory-transfer-cost-v3','inventory-transfer-cost-v4')")
    value = _replace(value, "   PERFORM reconforge.it1_assert(net_quantity>0,", """   FOR correction IN SELECT value FROM jsonb_array_elements(COALESCE(pool->'monetary_return_corrections','[]'::jsonb)) LOOP
    net_quantity:=net_quantity+(correction#>>'{restoration,direction}')::numeric*(correction#>>'{restoration,quantity_scaled}')::numeric;
   END LOOP;
   PERFORM reconforge.it1_assert(net_quantity>0,""")
    return value


def _zero_plan() -> str:
    value = _definition("customer_partial_return_zero_stock_plan", ADMISSION_SQL, "$cr148zs$")
    value = _replace(value, "customer_partial_return_zero_stock_plan(", "monetary_stock_zero_plan(")
    value = _replace(value, "LANGUAGE plpgsql STABLE", "LANGUAGE plpgsql VOLATILE")
    value = _replace(value, "owned.id IS NOT NULL AND issue->>'schema_version'", "owned.id IS NOT NULL AND owned.source->>'schema_version'='stock-sales-monetary-order-v2' AND issue->>'schema_version'")
    value = _replace(value, "cost->>'schema_version'='inventory-transfer-cost-v3'",
        "cost->>'schema_version' IN('inventory-transfer-cost-v3','inventory-transfer-cost-v4')")
    value = _replace(value, "=(owned.workspace_id,owned.organization_id,owned.legal_entity_id,owned.currency_code)",
        "=(owned.workspace_id,owned.organization_id,owned.legal_entity_id,owned.source#>>'{functional_policy,currency_code}')")
    value = _replace(value, "   PERFORM reconforge.it1_assert(net_quantity>0,", """   FOR correction IN SELECT value FROM jsonb_array_elements(COALESCE(pool->'monetary_return_corrections','[]'::jsonb)) LOOP
    net_quantity:=net_quantity+(correction#>>'{restoration,direction}')::numeric*(correction#>>'{restoration,quantity_scaled}')::numeric;
   END LOOP;
   PERFORM reconforge.it1_assert(net_quantity>0,""")
    return value


def _zero_active() -> str:
    value = _definition("customer_partial_return_zero_stock_active", ADMISSION_SQL, "$cr148zs$")
    value = _replace(value, "customer_partial_return_zero_stock_active(", "monetary_stock_zero_active(")
    value = _replace(value, "owned.id IS NOT NULL AND owned.status='IssueReviewed'",
        "owned.id IS NOT NULL AND owned.source->>'schema_version'='stock-sales-monetary-order-v2' AND owned.status='IssueReviewed'")
    value = _replace(value, "owned.issue_plan->>'policy_id',owned.currency_code)",
        "owned.issue_plan->>'policy_id',owned.source#>>'{functional_policy,currency_code}')")
    value = _replace(value, "owned.source->'monetary_policy',valuation.currency_code", "owned.source->'functional_policy',valuation.currency_code")
    return _replace(value, " RETURN to_jsonb(owned);", " PERFORM reconforge.monetary_stock_zero_plan(t,owned.id);\n RETURN to_jsonb(owned);")


def _zero_facts() -> str:
    value = _definition("customer_partial_return_zero_stock_facts", FACTS_SQL, "$cr148zs$")
    value = _replace(value, "customer_partial_return_zero_stock_facts(", "monetary_stock_zero_facts(")
    value = _replace(value, "LANGUAGE plpgsql STABLE", "LANGUAGE plpgsql VOLATILE")
    value = _replace(value, "reconforge.customer_partial_return_zero_stock_plan(t,i)", "reconforge.monetary_stock_physical_close(t,i)")
    return _replace(value, "'schema_version','stock-sales-restituted-cost-v1'", "'schema_version','stock-sales-monetary-restituted-cost-v1'")


ZERO_CONSUMPTION_SQL = r"""
CREATE FUNCTION reconforge.monetary_zero_consumption(t TEXT,i TEXT) RETURNS JSONB
 LANGUAGE plpgsql VOLATILE SET search_path=pg_catalog AS $mrphysical$
DECLARE consumed RECORD;detail RECORD;document RECORD;owned RECORD;facts JSONB;result JSONB;
BEGIN
 SELECT * INTO consumed FROM reconforge.inventory_layer_consumptions WHERE tenant_id=t AND id=i;
 SELECT * INTO detail FROM reconforge.inventory_valuation_lines WHERE tenant_id=t AND id=consumed.valuation_line_id;
 SELECT * INTO document FROM reconforge.inventory_valuation_documents WHERE tenant_id=t AND id=detail.valuation_document_id;
 SELECT stock.* INTO owned FROM reconforge.stock_sales_orders stock WHERE stock.tenant_id=t AND stock.valuation_id=document.id;
 IF owned.source->>'schema_version' IS DISTINCT FROM'stock-sales-monetary-order-v2' THEN
  RETURN reconforge.customer_partial_return_zero_consumption(t,i);
 END IF;
 PERFORM reconforge.it1_assert(consumed.id IS NOT NULL AND consumed.value_minor=0
  AND owned.issue_plan->>'cost_admission_policy'='partial-return-restituted-v1',
  'A monetary zero consumption requires its fixed actual restitution owner');
 facts:=reconforge.monetary_stock_zero_facts(t,owned.id);
 PERFORM reconforge.it1_assert(EXISTS(SELECT 1 FROM jsonb_array_elements(facts->'consumptions') original WHERE original=to_jsonb(consumed)),
  'Every monetary zero consumption must retain its exact approved original evidence');
 result:=jsonb_build_object('consumption_id',i,'stock_order_id',owned.id,'cost_admission_policy','partial-return-restituted-v1',
  'issue_plan',owned.issue_plan,'valuation_document',to_jsonb(document),'valuation_line',to_jsonb(detail),
  'posting_effect',facts->'posting_effect','physical',reconforge.it1_native_snapshot(t,owned.movement_id));
 PERFORM reconforge.it1_assert(octet_length(result::text)<=262144,'Monetary zero consumption exceeds its finite original evidence bound');
 RETURN result;
END $mrphysical$;
"""

PHYSICAL_SQL = r"""
CREATE FUNCTION reconforge.monetary_return_physical(t TEXT,i TEXT,posting BOOLEAN) RETURNS JSONB
 LANGUAGE plpgsql VOLATILE SET search_path=pg_catalog AS $mrphysical$
DECLARE owned RECORD;origin RECORD;stock RECORD;movement RECORD;detail RECORD;reviewer TEXT;poster TEXT;
BEGIN
 SELECT * INTO owned FROM reconforge.customer_partial_return_monetary_plans WHERE tenant_id=t AND id=i;
 SELECT * INTO origin FROM reconforge.stock_sales_monetary_origins WHERE tenant_id=t AND id=owned.origin_id;
 SELECT * INTO stock FROM reconforge.stock_sales_orders WHERE tenant_id=t AND id=origin.stock_order_id;
 SELECT * INTO movement FROM reconforge.inventory_movements WHERE tenant_id=t AND id=owned.payload->>'movement_id';
 SELECT * INTO detail FROM reconforge.inventory_movement_lines WHERE tenant_id=t AND movement_id=movement.id;
 SELECT actor_id INTO reviewer FROM reconforge.customer_partial_return_monetary_events WHERE tenant_id=t AND plan_id=i AND operation='review';
 IF posting THEN poster:=current_setting('app.customer_partial_return_monetary_actor_id',true);
 ELSE SELECT actor_id INTO poster FROM reconforge.customer_partial_return_monetary_events WHERE tenant_id=t AND plan_id=i AND operation='post';END IF;
 PERFORM reconforge.it1_assert(owned.id IS NOT NULL AND origin.id IS NOT NULL AND stock.id IS NOT NULL
  AND reconforge.irp_scope(t,origin.workspace_id,origin.organization_id,origin.legal_entity_id)
  AND owned.operation IN('Return','ReverseReturn') AND owned.phase=CASE WHEN posting THEN 1 ELSE 2 END
  AND reviewer IS NOT NULL AND poster IS NOT NULL AND poster<>reviewer AND poster<>owned.payload->>'preparer_actor_id'
  AND reviewer<>owned.payload->>'preparer_actor_id'
  AND(NOT posting OR reconforge.customer_return_authority(t,poster,'post'))
  AND movement.id=owned.payload->>'movement_id' AND movement.source_type='Generated' AND movement.source_reference=i
  AND movement.movement_number=upper(i) AND movement.status='Posted'
  AND movement.posted_by=(SELECT username FROM reconforge.identity_users WHERE tenant_id=t AND id=poster)
  AND(movement.workspace_id,movement.organization_id,movement.legal_entity_id,movement.period_id,movement.movement_date::text)
   =(origin.workspace_id,origin.organization_id,origin.legal_entity_id,owned.payload->>'period_id',owned.payload->>'posting_date')
  AND movement.movement_type=CASE owned.operation WHEN'Return' THEN'Receipt' ELSE'Delivery' END
  AND(SELECT count(*) FROM reconforge.inventory_movement_lines WHERE tenant_id=t AND movement_id=movement.id)=1
  AND(detail.item_id,detail.uom_id,detail.quantity_precision,detail.quantity_scaled)
   =(stock.item_id,stock.uom_id,stock.quantity_precision,(owned.payload->>'quantity_scaled')::bigint)
  AND detail.inventory_lot_id IS NULL
  AND(detail.from_location_id,detail.to_location_id) IS NOT DISTINCT FROM
   (CASE WHEN owned.operation='ReverseReturn' THEN stock.location_id ELSE NULL END,
    CASE WHEN owned.operation='Return' THEN stock.location_id ELSE NULL END),
  'Monetary correction physical effect requires its exact scoped original and three independent native phases');
 RETURN reconforge.it1_native_snapshot(t,movement.id);
END $mrphysical$;
CREATE FUNCTION reconforge.monetary_return_valued_movement(t TEXT,i TEXT) RETURNS BOOLEAN
 LANGUAGE plpgsql VOLATILE SET search_path=pg_catalog AS $mrphysical$
DECLARE physical RECORD;owned RECORD;
BEGIN
 SELECT * INTO physical FROM reconforge.inventory_movements WHERE tenant_id=t AND id=i;
 IF physical.id IS NULL OR physical.movement_number!~'^CR3(R)?-[A-F0-9]{32}$' THEN RETURN FALSE;END IF;
 SELECT * INTO owned FROM reconforge.customer_partial_return_monetary_plans WHERE tenant_id=t AND id=physical.source_reference;
 PERFORM reconforge.it1_assert(owned.id IS NOT NULL AND owned.payload->>'movement_id'=i,
  'A reserved monetary movement cannot borrow another native source');
 PERFORM reconforge.monetary_return_physical(t,owned.id,FALSE);
 PERFORM reconforge.monetary_partial_close(t,owned.id);
 RETURN TRUE;
END $mrphysical$;
CREATE FUNCTION reconforge.monetary_return_zero_layer_admitted(t TEXT,i TEXT,old_row JSONB,new_row JSONB,operation TEXT) RETURNS BOOLEAN
 LANGUAGE plpgsql VOLATILE SET search_path=pg_catalog AS $mrphysical$
DECLARE restoration RECORD;owned RECORD;original_part JSONB;zero_valuation TEXT;poster TEXT:=current_setting('app.customer_partial_return_monetary_actor_id',true);
BEGIN
 IF operation<>'UPDATE' OR old_row IS NULL OR new_row->>'tenant_id' IS DISTINCT FROM t OR new_row->>'id' IS DISTINCT FROM i
 OR(new_row->>'remaining_quantity_scaled')::numeric<=0 OR(new_row->>'remaining_value_minor')::numeric<>0 THEN RETURN FALSE;END IF;
 FOR restoration IN SELECT r.* FROM reconforge.customer_partial_return_monetary_restorations r
 JOIN reconforge.customer_partial_return_monetary_plans p ON(p.tenant_id,p.id)=(r.tenant_id,r.plan_id)
 WHERE r.tenant_id=t AND r.cost_layer_id=i AND p.phase=1 LOOP
  SELECT * INTO owned FROM reconforge.customer_partial_return_monetary_plans WHERE tenant_id=t AND id=restoration.plan_id;
  SELECT value INTO original_part FROM jsonb_array_elements(owned.payload#>'{monetary_event,portions}')
   WHERE(value->>'position')::integer=restoration.position;
  IF(new_row->>'remaining_quantity_scaled')::numeric-(old_row->>'remaining_quantity_scaled')::numeric
    =restoration.direction::numeric*restoration.quantity_scaled
   AND(new_row->>'remaining_value_minor')::numeric-(old_row->>'remaining_value_minor')::numeric
    =restoration.direction::numeric*restoration.value_minor THEN
   PERFORM reconforge.it1_assert(original_part IS NOT NULL AND restoration.direction=CASE owned.operation WHEN'Return' THEN 1 WHEN'ReverseReturn' THEN -1 ELSE 0 END
    AND(restoration.original_consumption_id,restoration.original_valuation_line_id,restoration.cost_layer_id,
      restoration.before_quantity_scaled,restoration.before_value_minor,restoration.quantity_scaled,restoration.value_minor)
     =(original_part->>'original_consumption_id',original_part->>'original_valuation_line_id',original_part->>'cost_layer_id',
       (original_part->>'before_quantity_scaled')::bigint,(original_part->>'before_value_minor')::bigint,
       (original_part->>'quantity_scaled')::bigint,(original_part->>'value_minor')::bigint)
    AND restoration.physical_movement_id=owned.payload->>'movement_id'
    AND restoration.consumption_count_at_restore=(SELECT count(*) FROM reconforge.inventory_layer_consumptions WHERE tenant_id=t AND cost_layer_id=i)
    AND(poster IS NOT NULL AND reconforge.customer_return_authority(t,poster,'post')),
    'Zero-value restitution requires its actual exact native before-witness and current authorized poster');
   PERFORM reconforge.monetary_return_physical(t,owned.id,TRUE);
   RETURN TRUE;
  END IF;
 END LOOP;
 -- The other admissible transition is a real new outbound zero/value-exhausting
 -- Stock slice. Its complete original issue and current three humans are checked
 -- by the new active helper; no free-standing value-zero layer is admitted.
 SELECT document.id INTO zero_valuation FROM reconforge.inventory_layer_consumptions consumed
 JOIN reconforge.inventory_valuation_lines detail ON(detail.tenant_id,detail.id)=(consumed.tenant_id,consumed.valuation_line_id)
 JOIN reconforge.inventory_valuation_documents document ON(document.tenant_id,document.id)=(detail.tenant_id,detail.valuation_document_id)
 JOIN reconforge.inventory_movements movement ON(movement.tenant_id,movement.id)=(document.tenant_id,document.movement_id)
 JOIN reconforge.stock_sales_orders fixed ON(fixed.tenant_id,fixed.id)=(movement.tenant_id,movement.source_reference)
 WHERE consumed.tenant_id=t AND consumed.cost_layer_id=i AND document.status='Draft'
 AND fixed.source->>'schema_version'='stock-sales-monetary-order-v2'
 AND consumed.quantity_scaled=(old_row->>'remaining_quantity_scaled')::numeric-(new_row->>'remaining_quantity_scaled')::numeric
 AND consumed.value_minor=(old_row->>'remaining_value_minor')::numeric-(new_row->>'remaining_value_minor')::numeric;
 IF zero_valuation IS NULL THEN RETURN FALSE;END IF;
 PERFORM reconforge.monetary_stock_zero_active(t,zero_valuation);RETURN TRUE;
END $mrphysical$;
"""

NATIVE_FUNCTION_SQL = _zero_cost() + _zero_plan() + _zero_active() + _zero_facts() + ZERO_CONSUMPTION_SQL + PHYSICAL_SQL
