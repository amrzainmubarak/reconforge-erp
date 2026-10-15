"""IT1 cost-v3 read/capture for versioned signed remaining-value corrections.

Legacy cost-v1/v2 readers/capture bytes remain below their explicit dispatch.
The new envelope is a closed legacy8/new11-key union; zero TOTAL cost has no GL.
"""

from __future__ import annotations

import hashlib

from reconforge.infrastructure.postgres_customer_partial_return_transfer_hooks import (
    CORRECTION_SQL,
)
from reconforge.infrastructure.postgres_customer_partial_return_transfer_hooks import (
    UPGRADED_FUNCTIONS as RETAINED_FUNCTIONS,
)


def _replace(value: str, old: str, new: str) -> str:
    if value.count(old) != 1:
        raise ValueError("One exact retained transfer-v2 anchor is required.")
    return value.replace(old, new)


CORRECTION_V3_SQL = r"""
CREATE FUNCTION reconforge.customer_partial_return_transfer_correction_v3(t TEXT,i TEXT,p INTEGER) RETURNS JSONB
 LANGUAGE plpgsql STABLE SET search_path=pg_catalog AS $cr148it$
DECLARE restoration RECORD;witness RECORD;owned RECORD;source_owner RECORD;post_event RECORD;history_owner RECORD;
 entry_owner RECORD;effect_owner RECORD;movement_owner RECORD;cost_part JSONB;result JSONB;
BEGIN
 SELECT * INTO owned FROM reconforge.customer_partial_return_plans WHERE tenant_id=t AND id=i;
 SELECT * INTO source_owner FROM reconforge.customer_partial_return_sources WHERE tenant_id=t AND id=owned.source_id;
 SELECT * INTO restoration FROM reconforge.customer_partial_return_restorations WHERE tenant_id=t AND plan_id=i AND position=p;
 SELECT * INTO witness FROM reconforge.customer_partial_return_allocation_witnesses WHERE tenant_id=t AND plan_id=i AND position=p;
 SELECT * INTO post_event FROM reconforge.customer_partial_return_events WHERE tenant_id=t AND plan_id=i AND operation='post';
 SELECT * INTO history_owner FROM reconforge.customer_partial_return_history WHERE tenant_id=t AND plan_id=i AND source_id=source_owner.id;
 PERFORM reconforge.it1_assert(owned.id IS NOT NULL AND source_owner.id IS NOT NULL AND restoration.plan_id IS NOT NULL
  AND witness.plan_id IS NOT NULL AND post_event.plan_id IS NOT NULL AND history_owner.plan_id IS NOT NULL
  AND owned.phase=2 AND owned.operation IN('Return','ReverseReturn')
  AND source_owner.source_payload->>'allocation_policy'='remaining-original-v1'
  AND owned.payload->>'allocation_policy'='remaining-original-v1',
  'A v3 correction requires its complete visible native remaining-original ownership');
 PERFORM reconforge.customer_partial_return_close(t,i);
 SELECT value INTO cost_part FROM jsonb_array_elements(owned.payload->'entries')
  WHERE value->>'purpose' IN('CostRestoration','ReverseCostRestoration');
 SELECT * INTO entry_owner FROM reconforge.finance_entries WHERE tenant_id=t AND id=cost_part->>'entry_id';
 SELECT * INTO effect_owner FROM reconforge.finance_posting_effects WHERE tenant_id=t AND id=restoration.correction_effect_id;
 IF owned.cogs_restored_minor>0 THEN
  PERFORM reconforge.it1_assert(entry_owner.id IS NOT NULL AND effect_owner.id IS NOT NULL
   AND effect_owner.entry_id=entry_owner.id AND entry_owner.entry_number=upper(i)||'-C'
   AND effect_owner.snapshot_json=reconforge.fr_snapshot(t,entry_owner.id,source_owner.organization_id,source_owner.legal_entity_id)
   AND effect_owner.validation_digest=cost_part->>'validation_digest' AND effect_owner.posted_actor_id=post_event.actor_id,
   'A positive TOTAL cost correction retains its exact shared native reviewed cost effect');
 ELSE
  PERFORM reconforge.it1_assert(cost_part IS NULL AND restoration.correction_effect_id IS NULL,
   'Zero TOTAL cost retains physical evidence without a counterfeit zero financial entry');
 END IF;
 SELECT * INTO movement_owner FROM reconforge.inventory_movements WHERE tenant_id=t AND id=restoration.physical_movement_id;
 PERFORM reconforge.it1_assert(movement_owner.id=owned.payload->>'movement_id' AND movement_owner.status='Posted'
  AND movement_owner.source_reference=i AND movement_owner.movement_number=upper(i),
  'V3 correction physical source must remain exact');
 result:=jsonb_build_object('restoration',to_jsonb(restoration),
  'source',jsonb_build_object('id',source_owner.id,'source_fingerprint',source_owner.source_fingerprint,
   'workspace_id',source_owner.workspace_id,'organization_id',source_owner.organization_id,'legal_entity_id',source_owner.legal_entity_id,
   'item_id',source_owner.item_id,'uom_id',source_owner.uom_id,'quantity_precision',source_owner.quantity_precision,
   'location_id',source_owner.location_id,'original_cogs_effect_id',source_owner.original_cogs_effect_id),
  'plan',jsonb_build_object('id',owned.id,'source_id',owned.source_id,'operation',owned.operation,'phase',owned.phase,
   'plan_digest',owned.plan_digest,'cogs_restored_minor',owned.cogs_restored_minor),
  'entry',CASE WHEN owned.cogs_restored_minor>0 THEN to_jsonb(entry_owner) ELSE NULL END,
  'effect',CASE WHEN owned.cogs_restored_minor>0 THEN to_jsonb(effect_owner) ELSE NULL END,
  'lines',CASE WHEN owned.cogs_restored_minor>0 THEN COALESCE((SELECT jsonb_agg(to_jsonb(detail) ORDER BY detail.line_number,detail.id)
   FROM reconforge.finance_entry_lines detail WHERE detail.tenant_id=t AND detail.entry_id=entry_owner.id),'[]'::jsonb) ELSE'[]'::jsonb END,
  'dimensions',CASE WHEN owned.cogs_restored_minor>0 THEN COALESCE((SELECT jsonb_agg(to_jsonb(dimension_link) ORDER BY to_jsonb(dimension_link)::text)
   FROM reconforge.finance_entry_line_dimensions dimension_link JOIN reconforge.finance_entry_lines detail
   ON(detail.tenant_id,detail.id)=(dimension_link.tenant_id,dimension_link.entry_line_id)
   WHERE detail.tenant_id=t AND detail.entry_id=entry_owner.id),'[]'::jsonb) ELSE'[]'::jsonb END,
  'physical',reconforge.it1_native_snapshot(t,movement_owner.id),'history_sequence',history_owner.sequence,
  'allocation_policy','remaining-original-v1','allocation_witness',jsonb_build_object(
   'before_quantity_scaled',witness.before_quantity_scaled,'before_value_minor',witness.before_value_minor));
 PERFORM reconforge.it1_assert(octet_length(result::text)<=262144,'V3 restitution original exceeds the finite evidence bound');
 RETURN result;
END $cr148it$;
CREATE FUNCTION reconforge.customer_partial_return_transfer_correction_dispatch(t TEXT,i TEXT,p INTEGER) RETURNS JSONB
 LANGUAGE plpgsql STABLE SET search_path=pg_catalog AS $cr148it$
BEGIN
 IF EXISTS(SELECT 1 FROM reconforge.customer_partial_return_plans WHERE tenant_id=t AND id=i AND payload ? 'allocation_policy') THEN
  RETURN reconforge.customer_partial_return_transfer_correction_v3(t,i,p);
 END IF;
 RETURN reconforge.customer_partial_return_transfer_correction(t,i,p);
END $cr148it$;
"""


def _snapshot() -> str:
    value = RETAINED_FUNCTIONS["it1_cost_snapshot"].replace("reconforge.it1_cost_snapshot(", "reconforge.customer_partial_return_it1_snapshot_v3(", 1)
    value = _replace(value, "has_restitution BOOLEAN:=FALSE;", "has_restitution BOOLEAN:=FALSE;has_rounding BOOLEAN:=FALSE;")
    value = _replace(value, "reconforge.customer_partial_return_transfer_correction(t,r.plan_id,r.position)",
                     "reconforge.customer_partial_return_transfer_correction_dispatch(t,r.plan_id,r.position)")
    value = _replace(value, "ORDER BY r.plan_id,r.position),'[]'::jsonb) INTO corrections FROM reconforge.customer_partial_return_restorations r",
        "ORDER BY r.source_id COLLATE \"C\",history_owner.sequence,r.position),'[]'::jsonb) INTO corrections FROM reconforge.customer_partial_return_restorations r JOIN reconforge.customer_partial_return_history history_owner ON(history_owner.tenant_id,history_owner.plan_id)=(r.tenant_id,r.plan_id)")
    value = _replace(value, "   correction_count:=correction_count+jsonb_array_length(corrections);", r"""   IF EXISTS(SELECT 1 FROM jsonb_array_elements(corrections) correction_value WHERE correction_value ? 'allocation_policy') THEN has_rounding:=TRUE;END IF;
   correction_count:=correction_count+jsonb_array_length(corrections);""")
    value = value.replace("jsonb_agg((value#>>'{entry,total_debit_minor}')::bigint ORDER BY ordinal)",
        "jsonb_agg((value#>>'{entry,total_debit_minor}')::bigint ORDER BY ordinal) FILTER(WHERE value->'entry'<>'null'::jsonb)")
    value = value.replace("jsonb_agg((value#>>'{entry,total_credit_minor}')::bigint ORDER BY ordinal)",
        "jsonb_agg((value#>>'{entry,total_credit_minor}')::bigint ORDER BY ordinal) FILTER(WHERE value->'entry'<>'null'::jsonb)")
    value = _replace(value, "AND values_minor BETWEEN 1 AND 9000000000000000000", "AND values_minor BETWEEN 0 AND 9000000000000000000 AND(values_minor>0 OR has_rounding)")
    value = _replace(value, "CASE WHEN has_restitution THEN'inventory-transfer-cost-v2' ELSE'inventory-transfer-cost-v1' END",
        "CASE WHEN has_rounding THEN'inventory-transfer-cost-v3' WHEN has_restitution THEN'inventory-transfer-cost-v2' ELSE'inventory-transfer-cost-v1' END")
    return value


def _reader() -> str:
    return _replace(RETAINED_FUNCTIONS["it1_cost_originals"], "BEGIN\n", r"""BEGIN
 IF cost->>'schema_version'='inventory-transfer-cost-v3' THEN
  PERFORM reconforge.customer_partial_return_transfer_originals_v3(t,cost);RETURN;
 END IF;
""")


def _originals_v3() -> str:
    start = CORRECTION_SQL.index("CREATE OR REPLACE FUNCTION reconforge.customer_partial_return_transfer_originals")
    value = CORRECTION_SQL[start:]
    value = _replace(value, "customer_partial_return_transfer_originals(", "customer_partial_return_transfer_originals_v3(")
    value = _replace(value, "cost->>'schema_version'='inventory-transfer-cost-v2'", "cost->>'schema_version'='inventory-transfer-cost-v3'")
    return _replace(value, "correction=reconforge.customer_partial_return_transfer_correction(", "correction=reconforge.customer_partial_return_transfer_correction_dispatch(")


def _snapshot_dispatch() -> str:
    return _replace(RETAINED_FUNCTIONS["it1_cost_snapshot"], "BEGIN\n", r"""BEGIN
 -- Ordinary147 capture does not require private partial-return ACLs when no
 -- restitution changes its already-permitted original layer equations.
 IF EXISTS(SELECT 1 FROM reconforge.inventory_cost_layers native_layer WHERE native_layer.tenant_id=t
  AND native_layer.workspace_id=w AND native_layer.legal_entity_id=e AND native_layer.item_id=i
  AND(native_layer.remaining_quantity_scaled<>native_layer.original_quantity_scaled-(SELECT COALESCE(sum(quantity_scaled),0)
    FROM reconforge.inventory_layer_consumptions WHERE tenant_id=t AND cost_layer_id=native_layer.id)
   OR native_layer.remaining_value_minor<>native_layer.original_value_minor-(SELECT COALESCE(sum(value_minor),0)
    FROM reconforge.inventory_layer_consumptions WHERE tenant_id=t AND cost_layer_id=native_layer.id))) THEN
  IF EXISTS(SELECT 1 FROM reconforge.customer_partial_return_restorations restoration
   JOIN reconforge.customer_partial_return_plans owned ON(owned.tenant_id,owned.id)=(restoration.tenant_id,restoration.plan_id)
   JOIN reconforge.inventory_cost_layers native_layer ON(native_layer.tenant_id,native_layer.id)=(restoration.tenant_id,restoration.cost_layer_id)
   WHERE restoration.tenant_id=t AND native_layer.workspace_id=w AND native_layer.legal_entity_id=e AND native_layer.item_id=i
   AND owned.payload ? 'allocation_policy') THEN
   RETURN reconforge.customer_partial_return_it1_snapshot_v3(t,w,o,e,i);
  END IF;
 END IF;
""")


UPGRADED_FUNCTIONS = {"it1_cost_snapshot": _snapshot_dispatch(), "it1_cost_originals": _reader()}


def _preflight(*, upgraded_only: bool = False) -> str:
    clauses = []
    for name, original in RETAINED_FUNCTIONS.items():
        if name not in UPGRADED_FUNCTIONS:
            continue
        definitions = [UPGRADED_FUNCTIONS[name]] if upgraded_only else [original, UPGRADED_FUNCTIONS[name]]
        hashes = ",".join(repr(hashlib.sha256(value.split("$it1$")[1].encode()).hexdigest()) for value in definitions)
        signature = "text,jsonb" if name == "it1_cost_originals" else "text,text,text,text,text"
        template = """ SELECT * INTO native FROM pg_proc WHERE oid=to_regprocedure('reconforge.@@NAME@@(@@SIGNATURE@@)');
 IF native.oid IS NULL OR native.prosecdef OR native.provolatile<>'s' OR native.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog']::text[]
 OR encode(sha256(convert_to(native.prosrc,'UTF8')),'hex') NOT IN(@@HASHES@@) THEN
 RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Original transfer v2 execution contract drift';END IF;"""
        clauses.append(template.replace("@@NAME@@", name).replace("@@SIGNATURE@@", signature).replace("@@HASHES@@", hashes))
    return "DO $cr148it$ DECLARE native RECORD;BEGIN\n" + "\n".join(clauses) + "\nEND $cr148it$;"


UPGRADE_SQL = _preflight() + CORRECTION_V3_SQL + _originals_v3() + _snapshot() + "\n".join(UPGRADED_FUNCTIONS.values())
DOWNGRADE_PREFLIGHT_SQL = r"""
DO $cr148it$ BEGIN
 IF EXISTS(SELECT 1 FROM reconforge.inventory_transfer_sources WHERE payload#>>'{cost_snapshot,schema_version}'='inventory-transfer-cost-v3'
  OR review_cost_json->>'schema_version'='inventory-transfer-cost-v3') THEN
  RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Retained transfer v3 prevents destructive downgrade';END IF;
END $cr148it$;
"""
DOWNGRADE_SQL = DOWNGRADE_PREFLIGHT_SQL + _preflight(upgraded_only=True) + "\n".join(
    value for name, value in RETAINED_FUNCTIONS.items() if name in UPGRADED_FUNCTIONS) + r"""
DROP FUNCTION reconforge.customer_partial_return_transfer_originals_v3(TEXT,JSONB);
DROP FUNCTION reconforge.customer_partial_return_transfer_correction_dispatch(TEXT,TEXT,INTEGER);
DROP FUNCTION reconforge.customer_partial_return_transfer_correction_v3(TEXT,TEXT,INTEGER);
DROP FUNCTION reconforge.customer_partial_return_it1_snapshot_v3(TEXT,TEXT,TEXT,TEXT,TEXT);
"""
