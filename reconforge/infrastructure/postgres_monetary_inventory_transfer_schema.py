"""Cost-v4 retains both old corrections and monetary CR3 original witnesses.

New capture/read functions extend the exact original receipt/FIFO/GL checks.
They keep signed corrections in the captured equation, rather than relabeling a
corrected source as an observed legacy envelope. Existing cost-v1/v2/v3 readers
and original snapshots are unchanged. All new execution uses the caller.
"""

from reconforge.infrastructure.postgres_customer_partial_return_transfer_hooks import (
    UPGRADED_FUNCTIONS as RETAINED_FUNCTIONS,
)
from reconforge.infrastructure.postgres_inventory_transfer_schema import OWNER_SQL
from reconforge.infrastructure.postgres_monetary_stock_shared_hooks import _definition


def _replace(value: str, old: str, new: str) -> str:
    if value.count(old) != 1:
        raise ValueError("One exact original transfer equation anchor is required.")
    return value.replace(old, new, 1)


CORRECTION_SQL = r"""
CREATE FUNCTION reconforge.monetary_transfer_correction(t TEXT,i TEXT,p INTEGER) RETURNS JSONB
 LANGUAGE plpgsql VOLATILE SET search_path=pg_catalog AS $mrit149$
DECLARE restoration RECORD;owned RECORD;origin RECORD;stock RECORD;post_event RECORD;history_owner RECORD;
 entry_owner RECORD;effect_owner RECORD;entry_part JSONB;result JSONB;physical JSONB;cost NUMERIC;
BEGIN
 SELECT * INTO restoration FROM reconforge.customer_partial_return_monetary_restorations WHERE tenant_id=t AND plan_id=i AND position=p;
 SELECT * INTO owned FROM reconforge.customer_partial_return_monetary_plans WHERE tenant_id=t AND id=i;
 SELECT * INTO origin FROM reconforge.stock_sales_monetary_origins WHERE tenant_id=t AND id=owned.origin_id;
 SELECT * INTO stock FROM reconforge.stock_sales_orders WHERE tenant_id=t AND id=origin.stock_order_id;
 SELECT * INTO post_event FROM reconforge.customer_partial_return_monetary_events WHERE tenant_id=t AND plan_id=i AND operation='post';
 SELECT * INTO history_owner FROM reconforge.customer_partial_return_monetary_history WHERE tenant_id=t AND origin_id=origin.id AND partial_plan_id=i;
 PERFORM reconforge.it1_assert(restoration.plan_id IS NOT NULL AND owned.id IS NOT NULL AND origin.id IS NOT NULL
  AND stock.id IS NOT NULL AND post_event.plan_id IS NOT NULL AND history_owner.partial_plan_id IS NOT NULL
  AND owned.phase=2 AND owned.operation IN('Return','ReverseReturn')
  AND(restoration.origin_id,restoration.workspace_id,restoration.organization_id,restoration.legal_entity_id)
   =(origin.id,origin.workspace_id,origin.organization_id,origin.legal_entity_id)
  AND restoration.direction=CASE owned.operation WHEN'Return' THEN 1 ELSE -1 END,
  'A cost-v4 correction requires its complete actual posted monetary source and immutable ordered history');
 PERFORM reconforge.monetary_partial_close(t,i);
 physical:=reconforge.monetary_return_physical(t,i,FALSE);
 SELECT value INTO entry_part FROM jsonb_array_elements(owned.payload->'entries')
  WHERE value->>'purpose' IN('CostRestoration','ReverseCostRestoration');
 cost:=(owned.payload#>>'{monetary_event,monetary,functional_cost_minor}')::numeric;
 SELECT * INTO entry_owner FROM reconforge.finance_entries WHERE tenant_id=t AND id=entry_part->>'entry_id';
 SELECT * INTO effect_owner FROM reconforge.finance_posting_effects WHERE tenant_id=t AND id=restoration.correction_effect_id;
 PERFORM reconforge.it1_assert((cost=0 AND entry_part IS NULL AND restoration.correction_effect_id IS NULL
   AND entry_owner.id IS NULL AND effect_owner.id IS NULL)
  OR(cost>0 AND entry_owner.id IS NOT NULL AND effect_owner.id IS NOT NULL
   AND effect_owner.entry_id=entry_owner.id AND entry_owner.entry_number=upper(i)||'-C'
   AND effect_owner.snapshot_json=reconforge.fr_snapshot(t,entry_owner.id,origin.organization_id,origin.legal_entity_id)
   AND effect_owner.validation_digest=entry_part->>'validation_digest' AND effect_owner.posted_actor_id=post_event.actor_id),
  'Cost-v4 keeps the exact native cost effect, and no fake financial row for a zero TOTAL restoration');
 result:=jsonb_build_object('restoration',to_jsonb(restoration),
  'source',jsonb_build_object('id',origin.id,'source_digest',origin.source_digest,'stock_order_id',stock.id,
   'workspace_id',origin.workspace_id,'organization_id',origin.organization_id,'legal_entity_id',origin.legal_entity_id,
   'item_id',stock.item_id,'uom_id',stock.uom_id,'quantity_precision',stock.quantity_precision,'location_id',stock.location_id,
   'original_cogs_effect_id',stock.cogs_effect_id,'original_cost_minor',(stock.issue_plan->>'total_cost_minor')::bigint),
  'plan',jsonb_build_object('id',owned.id,'source_id',owned.origin_id,'operation',owned.operation,'phase',owned.phase,
   'plan_digest',owned.plan_digest,'functional_cost_minor',cost::bigint),
  'entry',CASE WHEN cost>0 THEN to_jsonb(entry_owner) ELSE NULL END,'effect',CASE WHEN cost>0 THEN to_jsonb(effect_owner) ELSE NULL END,
  'lines',CASE WHEN cost>0 THEN COALESCE((SELECT jsonb_agg(to_jsonb(detail) ORDER BY detail.line_number,detail.id)
   FROM reconforge.finance_entry_lines detail WHERE detail.tenant_id=t AND detail.entry_id=entry_owner.id),'[]'::jsonb) ELSE'[]'::jsonb END,
  'dimensions',CASE WHEN cost>0 THEN COALESCE((SELECT jsonb_agg(to_jsonb(dimension_link) ORDER BY to_jsonb(dimension_link)::text)
   FROM reconforge.finance_entry_line_dimensions dimension_link JOIN reconforge.finance_entry_lines detail
   ON(detail.tenant_id,detail.id)=(dimension_link.tenant_id,dimension_link.entry_line_id)
   WHERE detail.tenant_id=t AND detail.entry_id=entry_owner.id),'[]'::jsonb) ELSE'[]'::jsonb END,
  'physical',physical,'history_sequence',history_owner.sequence,'allocation_policy','remaining-dual-currency-v1');
 PERFORM reconforge.it1_assert(octet_length(result::text)<=262144,'A monetary FIFO correction exceeds its finite native evidence bound');
 RETURN result;
END $mrit149$;
"""

_CAPTURE_CORRECTIONS = r"""  corrections:='[]'::jsonb;monetary_corrections:='[]'::jsonb;restored_quantity:=0;restored_value:=0;
  SELECT(SELECT count(*) FROM reconforge.customer_partial_return_restorations WHERE tenant_id=t AND cost_layer_id=layer.id)
   +(SELECT count(*) FROM reconforge.customer_partial_return_monetary_restorations WHERE tenant_id=t AND cost_layer_id=layer.id)
   INTO population;
  PERFORM reconforge.it1_assert(population<=256-correction_count,'Cost-v4 correction membership exceeds the finite complete pool');
  IF population>0 THEN
   SELECT COALESCE(jsonb_agg(reconforge.customer_partial_return_transfer_correction_dispatch(t,r.plan_id,r.position)
    ORDER BY r.source_id COLLATE "C",history_owner.sequence,r.position),'[]'::jsonb) INTO corrections
    FROM reconforge.customer_partial_return_restorations r JOIN reconforge.customer_partial_return_history history_owner
    ON(history_owner.tenant_id,history_owner.plan_id)=(r.tenant_id,r.plan_id) WHERE r.tenant_id=t AND r.cost_layer_id=layer.id;
   SELECT COALESCE(jsonb_agg(reconforge.monetary_transfer_correction(t,r.plan_id,r.position)
    ORDER BY r.origin_id COLLATE "C",history_owner.sequence,r.position),'[]'::jsonb) INTO monetary_corrections
    FROM reconforge.customer_partial_return_monetary_restorations r JOIN reconforge.customer_partial_return_monetary_history history_owner
    ON(history_owner.tenant_id,history_owner.partial_plan_id)=(r.tenant_id,r.plan_id) WHERE r.tenant_id=t AND r.cost_layer_id=layer.id;
   PERFORM reconforge.it1_assert(jsonb_array_length(corrections)+jsonb_array_length(monetary_corrections)=population
    AND octet_length((corrections||monetary_corrections)::text)<=1048576,'Every visible correction requires exact retained history ownership');
   correction_count:=correction_count+population;
   FOR correction IN SELECT value FROM jsonb_array_elements(corrections||monetary_corrections) LOOP
    restored_quantity:=restored_quantity+(correction#>>'{restoration,direction}')::numeric*(correction#>>'{restoration,quantity_scaled}')::numeric;
    restored_value:=restored_value+(correction#>>'{restoration,direction}')::numeric*(correction#>>'{restoration,value_minor}')::numeric;
   END LOOP;
  END IF;
"""
_CAPTURE_ORIGINAL = r"""  SELECT amounts||COALESCE(jsonb_agg((value#>>'{entry,total_debit_minor}')::bigint ORDER BY ordinal)
   FILTER(WHERE value->'entry'<>'null'::jsonb),'[]'::jsonb)
   ||COALESCE(jsonb_agg((value#>>'{entry,total_credit_minor}')::bigint ORDER BY ordinal)
   FILTER(WHERE value->'entry'<>'null'::jsonb),'[]'::jsonb) INTO amounts
   FROM jsonb_array_elements(corrections||monetary_corrections) WITH ORDINALITY ordered_corrections(value,ordinal);
  original:=original||jsonb_build_object('partial_return_corrections',corrections,'monetary_return_corrections',monetary_corrections,
   'exposed_amounts_minor',amounts);
  IF EXISTS(SELECT 1 FROM jsonb_array_elements(consumptions) consumed WHERE consumed->>'value_minor'='0') THEN
   original:=original||jsonb_build_object('restituted_consumption_admissions',(SELECT jsonb_agg(
    reconforge.monetary_zero_consumption(t,consumed->>'id') ORDER BY ordinal)
    FROM jsonb_array_elements(consumptions) WITH ORDINALITY retained(consumed,ordinal) WHERE consumed->>'value_minor'='0'));
  END IF;
  sources:=sources||jsonb_build_array(original);quantities:=quantities+layer.remaining_quantity_scaled;values_minor:=values_minor+layer.remaining_value_minor;
  PERFORM reconforge.it1_assert(octet_length(sources::text)<=4194304,'Cost-v4 complete originals exceed the finite native capture bound');
"""


def _snapshot() -> str:
    value = _definition("it1_cost_snapshot", OWNER_SQL, "$it1$")
    value = _replace(value, "reconforge.it1_cost_snapshot(", "reconforge.monetary_transfer_cost_snapshot(")
    value = _replace(value, "LANGUAGE plpgsql STABLE", "LANGUAGE plpgsql VOLATILE")
    value = _replace(value, "history_count INTEGER:=0;", "history_count INTEGER:=0;corrections JSONB;monetary_corrections JSONB;correction JSONB;\n restored_quantity NUMERIC;restored_value NUMERIC;population INTEGER;correction_count INTEGER:=0;")
    anchor = "  PERFORM reconforge.it1_assert(history_count<=200 AND layer.remaining_quantity_scaled=layer.original_quantity_scaled-consumed_quantity"
    value = _replace(value, anchor, _CAPTURE_CORRECTIONS + anchor + "+restored_quantity")
    value = _replace(value, "   AND layer.remaining_value_minor=layer.original_value_minor-consumed_value",
        "   AND layer.remaining_value_minor=layer.original_value_minor-consumed_value+restored_value")
    value = _replace(value, "  sources:=sources||jsonb_build_array(original);quantities:=quantities+layer.remaining_quantity_scaled;values_minor:=values_minor+layer.remaining_value_minor;", _CAPTURE_ORIGINAL)
    value = _replace(value, "PERFORM reconforge.it1_stock_origins(t,w,o,e,i)", "PERFORM reconforge.monetary_transfer_stock_origins(t,w,o,e,i)")
    value = _replace(value, "AND values_minor BETWEEN 1 AND 9000000000000000000", "AND values_minor BETWEEN 0 AND 9000000000000000000")
    return _replace(value, "'schema_version','inventory-transfer-cost-v1'", "'schema_version','inventory-transfer-cost-v4'")


def _quantity_snapshot() -> str:
    """Keep complete cost evidence without re-adopting unrelated movements.

    Only the global FIFO backing checker calls this read helper. Actual IT1
    source birth/review and Stock admission retain the full adoption snapshot.
    """
    value = _replace(_snapshot(), "CREATE FUNCTION reconforge.monetary_transfer_cost_snapshot(",
        "CREATE FUNCTION reconforge.monetary_quantity_cost_snapshot(")
    return _replace(value, " PERFORM reconforge.monetary_transfer_stock_origins(t,w,o,e,i);\n", "")


_READ_CORRECTIONS = r"""  PERFORM reconforge.it1_assert(jsonb_typeof(original->'partial_return_corrections')='array'
   AND jsonb_typeof(original->'monetary_return_corrections')='array'
   AND(SELECT count(DISTINCT(value#>>'{restoration,plan_id}',value#>>'{restoration,position}'))
     FROM jsonb_array_elements((original->'partial_return_corrections')||(original->'monetary_return_corrections')))
    =jsonb_array_length(original->'partial_return_corrections')+jsonb_array_length(original->'monetary_return_corrections'),
   'Cost-v4 captured correction families must retain unique actual native membership');
  restored_quantity:=0;restored_value:=0;
  FOR correction IN SELECT value FROM jsonb_array_elements(original->'partial_return_corrections') LOOP
   correction_count:=correction_count+1;
   PERFORM reconforge.it1_assert(correction_count<=256 AND correction#>>'{restoration,cost_layer_id}'=layer.id
    AND correction=reconforge.customer_partial_return_transfer_correction_dispatch(t,correction#>>'{restoration,plan_id}',
      (correction#>>'{restoration,position}')::integer),'Cost-v4 retains every original legacy correction without relabeling');
   restored_quantity:=restored_quantity+(correction#>>'{restoration,direction}')::numeric*(correction#>>'{restoration,quantity_scaled}')::numeric;
   restored_value:=restored_value+(correction#>>'{restoration,direction}')::numeric*(correction#>>'{restoration,value_minor}')::numeric;
  END LOOP;
  FOR correction IN SELECT value FROM jsonb_array_elements(original->'monetary_return_corrections') LOOP
   correction_count:=correction_count+1;
   PERFORM reconforge.it1_assert(correction_count<=256 AND correction#>>'{restoration,cost_layer_id}'=layer.id
    AND correction=reconforge.monetary_transfer_correction(t,correction#>>'{restoration,plan_id}',
      (correction#>>'{restoration,position}')::integer),'Cost-v4 retains every original monetary correction and its exact posted source');
   restored_quantity:=restored_quantity+(correction#>>'{restoration,direction}')::numeric*(correction#>>'{restoration,quantity_scaled}')::numeric;
   restored_value:=restored_value+(correction#>>'{restoration,direction}')::numeric*(correction#>>'{restoration,value_minor}')::numeric;
  END LOOP;
  IF EXISTS(SELECT 1 FROM jsonb_array_elements(original->'consumptions') consumed WHERE consumed->>'value_minor'='0') THEN
   PERFORM reconforge.it1_assert(original->'restituted_consumption_admissions'=(SELECT jsonb_agg(
    reconforge.monetary_zero_consumption(t,consumed->>'id') ORDER BY ordinal)
    FROM jsonb_array_elements(original->'consumptions') WITH ORDINALITY retained(consumed,ordinal) WHERE consumed->>'value_minor'='0'),
    'Every zero captured consumption retains its exact functional cost admission');
  ELSE PERFORM reconforge.it1_assert(NOT(original ? 'restituted_consumption_admissions'),
    'A positive consumption cannot invent a zero-cost authority');END IF;
"""


def _originals() -> str:
    value = _definition("it1_cost_originals", OWNER_SQL, "$it1$")
    value = _replace(value, "reconforge.it1_cost_originals(", "reconforge.monetary_transfer_cost_originals(")
    value = _replace(value, "LANGUAGE plpgsql STABLE", "LANGUAGE plpgsql VOLATILE")
    value = _replace(value, "history_count INTEGER:=0;", "history_count INTEGER:=0;correction JSONB;restored_quantity NUMERIC;restored_value NUMERIC;correction_count INTEGER:=0;")
    value = _replace(value, "cost->>'schema_version'='inventory-transfer-cost-v1'", "cost->>'schema_version'='inventory-transfer-cost-v4'\n  AND(SELECT array_agg(key ORDER BY key) FROM jsonb_object_keys(cost) key)=ARRAY['monetary_policy','remaining_quantity_scaled','remaining_value_minor','schema_version','sources']::text[]")
    value = _replace(value, "  PERFORM reconforge.it1_assert(history_count<=200 AND(original#>>'{layer,remaining_quantity_scaled}')::numeric",
        _READ_CORRECTIONS + "  PERFORM reconforge.it1_assert(history_count<=200 AND(original#>>'{layer,remaining_quantity_scaled}')::numeric")
    value = _replace(value, "=(original#>>'{layer,original_quantity_scaled}')::numeric-consumed_quantity", "=(original#>>'{layer,original_quantity_scaled}')::numeric-consumed_quantity+restored_quantity")
    value = _replace(value, "=(original#>>'{layer,original_value_minor}')::numeric-consumed_value", "=(original#>>'{layer,original_value_minor}')::numeric-consumed_value+restored_value")
    return _replace(value, "actual=original-ARRAY['layer','receipt_plan','consumptions','exposed_amounts_minor']",
        "actual=original-ARRAY['layer','receipt_plan','consumptions','exposed_amounts_minor','partial_return_corrections','monetary_return_corrections','restituted_consumption_admissions']")


def _origins() -> str:
    value = RETAINED_FUNCTIONS["it1_stock_origins"]
    value = _replace(value, "CREATE OR REPLACE FUNCTION reconforge.it1_stock_origins(", "CREATE FUNCTION reconforge.monetary_transfer_stock_origins(")
    value = _replace(value, "partial_owner RECORD;", "partial_owner RECORD;monetary_stock RECORD;")
    anchor = "  IF physical.head->>'movement_number'~'^CR2(R)?-[A-F0-9]{32}$' THEN"
    return _replace(value, anchor, r"""  IF physical.head->>'movement_number'~'^CR3(R)?-[A-F0-9]{32}$' THEN
   PERFORM reconforge.it1_assert(reconforge.monetary_return_valued_movement(t,physical.movement_id),
    'Cost-v4 monetary physical adoption requires its exact native posted source');
  ELSIF physical.movement_type='Delivery' AND EXISTS(SELECT 1 FROM reconforge.stock_sales_orders fixed
   WHERE fixed.tenant_id=t AND fixed.movement_id=physical.movement_id AND fixed.source->>'schema_version'='stock-sales-monetary-order-v2') THEN
   SELECT * INTO monetary_stock FROM reconforge.stock_sales_orders fixed
    WHERE fixed.tenant_id=t AND fixed.movement_id=physical.movement_id AND fixed.source->>'schema_version'='stock-sales-monetary-order-v2';
   PERFORM reconforge.it1_assert((monetary_stock.workspace_id,monetary_stock.organization_id,monetary_stock.legal_entity_id,
     monetary_stock.item_id,monetary_stock.uom_id,monetary_stock.quantity_precision,monetary_stock.quantity_scaled)
    =(w,o,e,i,physical.uom_id,physical.quantity_precision,physical.quantity_scaled)
    AND physical.head->>'source_type'='Generated' AND physical.head->>'source_reference'=monetary_stock.id
    AND physical.from_location_id=monetary_stock.location_id AND physical.to_location_id IS NULL,
    'Cost-v4 fixed Stock adoption must preserve exact original scope and physical quantity');
   PERFORM reconforge.monetary_stock_source_close(t,monetary_stock.id);
  ELSIF physical.head->>'movement_number'~'^CR2(R)?-[A-F0-9]{32}$' THEN""")


NATIVE_FUNCTION_SQL = CORRECTION_SQL + _snapshot() + _quantity_snapshot() + _originals() + _origins()
