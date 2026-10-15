"""Finite CR2 restitution evidence for new IT1 cost-pool adoption.

The original v1 historical reader is retained below an early v2 dispatch. A v2
capture adds immutable signed corrections to the SAME original FIFO layers;
it creates no quantity, cost, or financial ledger. Ordinary v1 capture neither
reads nor depends on private CR2 rows. Root owns ordered migration installation.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from typing import Any

from reconforge.infrastructure.postgres_inventory_transfer_schema import OWNER_SQL

ORIGINAL_BODY_HASHES = {
    "it1_cost_snapshot": "16df901eab160f1aed036f38482b47d6e07693722365e8eb4912f69f8a9f5e09",
    "it1_cost_originals": "77d9401b2ac2ad12e8176b86ace94adf0469e8e0f03e35826af120db44e5ba4a",
    "it1_stock_origins": "79f13e1f690df97adf282797dc8549887fc846e1c2ccbd30583809e84c91b6e5",
}


def _original(name: str) -> str:
    found = re.findall(r"CREATE FUNCTION reconforge\." + re.escape(name) + r"\(.*?END \$it1\$;", OWNER_SQL, re.S)
    if len(found) != 1 or hashlib.sha256(found[0].split("$it1$")[1].encode()).hexdigest() != ORIGINAL_BODY_HASHES[name]:
        raise RuntimeError("Original IT1 source contract changed")
    return found[0].replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1)


def _replace(source: str, before: str, after: str) -> str:
    if source.count(before) != 1:
        raise RuntimeError("Original IT1 integration anchor changed")
    return source.replace(before, after, 1)


CORRECTION_SQL = r"""
CREATE OR REPLACE FUNCTION reconforge.customer_partial_return_transfer_correction(t TEXT,i TEXT,n INTEGER) RETURNS JSONB
 LANGUAGE plpgsql STABLE SET search_path=pg_catalog AS $cr2it$
DECLARE restoration RECORD;owned RECORD;source_owner RECORD;layer_owner RECORD;effect_owner RECORD;entry_owner RECORD;
 movement_owner RECORD;movement_line RECORD;post_event RECORD;result JSONB;
BEGIN
 SELECT * INTO restoration FROM reconforge.customer_partial_return_restorations WHERE tenant_id=t AND plan_id=i AND position=n;
 SELECT * INTO owned FROM reconforge.customer_partial_return_plans WHERE tenant_id=t AND id=i;
 SELECT * INTO source_owner FROM reconforge.customer_partial_return_sources WHERE tenant_id=t AND id=restoration.source_id;
 SELECT * INTO layer_owner FROM reconforge.inventory_cost_layers WHERE tenant_id=t AND id=restoration.cost_layer_id;
 SELECT * INTO effect_owner FROM reconforge.finance_posting_effects WHERE tenant_id=t AND id=restoration.correction_effect_id;
 SELECT * INTO entry_owner FROM reconforge.finance_entries WHERE tenant_id=t AND id=effect_owner.entry_id;
 SELECT * INTO movement_owner FROM reconforge.inventory_movements WHERE tenant_id=t AND id=restoration.physical_movement_id;
 SELECT * INTO post_event FROM reconforge.customer_partial_return_events WHERE tenant_id=t AND plan_id=i AND operation='post';
 PERFORM reconforge.it1_assert(restoration.plan_id IS NOT NULL AND owned.id IS NOT NULL AND source_owner.id IS NOT NULL
  AND layer_owner.id IS NOT NULL AND effect_owner.id IS NOT NULL AND entry_owner.id IS NOT NULL AND movement_owner.id IS NOT NULL
  AND post_event.plan_id IS NOT NULL AND owned.phase=2 AND owned.operation IN('Return','ReverseReturn')
  AND restoration.direction=CASE owned.operation WHEN'Return' THEN 1 ELSE -1 END
  AND(restoration.source_id,restoration.original_cogs_effect_id)=(owned.source_id,source_owner.original_cogs_effect_id)
  AND(layer_owner.workspace_id,layer_owner.legal_entity_id,layer_owner.item_id,layer_owner.uom_id,layer_owner.quantity_precision)
   =(source_owner.workspace_id,source_owner.legal_entity_id,source_owner.item_id,source_owner.uom_id,source_owner.quantity_precision)
  AND layer_owner.inventory_lot_id IS NULL AND layer_owner.currency_code=source_owner.currency_code
  AND effect_owner.id=post_event.effects->>1 AND effect_owner.entry_id=owned.payload#>>'{entries,1,entry_id}'
  AND entry_owner.entry_number=upper(owned.id)||'-C'
  AND entry_owner.external_reference=CASE owned.operation WHEN'Return' THEN owned.id ELSE effect_owner.reverses_effect_id END
  AND entry_owner.source_type=CASE owned.operation WHEN'Return' THEN'Manual' ELSE'Generated' END
  AND entry_owner.status='Validated' AND effect_owner.snapshot_json=reconforge.fr_snapshot(t,entry_owner.id,source_owner.organization_id,source_owner.legal_entity_id)
  AND effect_owner.validation_digest=owned.payload#>>'{entries,1,validation_digest}'
  AND effect_owner.posted_actor_id=post_event.actor_id
  AND movement_owner.id=owned.payload->>'movement_id' AND movement_owner.source_reference=owned.id
  AND movement_owner.source_type='Generated' AND movement_owner.movement_number=upper(owned.id) AND movement_owner.status='Posted'
  AND movement_owner.movement_type=CASE owned.operation WHEN'Return' THEN'Receipt' ELSE'Delivery' END
  AND(movement_owner.workspace_id,movement_owner.organization_id,movement_owner.legal_entity_id)
   =(source_owner.workspace_id,source_owner.organization_id,source_owner.legal_entity_id)
  AND(SELECT count(*) FROM reconforge.inventory_movement_lines detail WHERE detail.tenant_id=t AND detail.movement_id=movement_owner.id)=1,
  'Transfer restitution requires its complete visible immutable original partial-return owner');
 SELECT * INTO movement_line FROM reconforge.inventory_movement_lines WHERE tenant_id=t AND movement_id=movement_owner.id;
 PERFORM reconforge.it1_assert((movement_line.item_id,movement_line.uom_id,movement_line.quantity_precision,movement_line.quantity_scaled)
   =(source_owner.item_id,source_owner.uom_id,source_owner.quantity_precision,owned.quantity_scaled)
  AND movement_line.inventory_lot_id IS NULL
  AND(movement_line.from_location_id,movement_line.to_location_id) IS NOT DISTINCT FROM
   (CASE WHEN owned.operation='ReverseReturn' THEN source_owner.location_id ELSE NULL END,
    CASE WHEN owned.operation='Return' THEN source_owner.location_id ELSE NULL END),
  'Transfer restitution retains its exact original-scope physical receipt or governed removal');
 PERFORM reconforge.customer_partial_return_close(t,i);
 result:=jsonb_build_object('restoration',to_jsonb(restoration),
  'source',jsonb_build_object('id',source_owner.id,'source_fingerprint',source_owner.source_fingerprint,
   'workspace_id',source_owner.workspace_id,'organization_id',source_owner.organization_id,'legal_entity_id',source_owner.legal_entity_id,
   'item_id',source_owner.item_id,'uom_id',source_owner.uom_id,'quantity_precision',source_owner.quantity_precision,
   'location_id',source_owner.location_id,'original_cogs_effect_id',source_owner.original_cogs_effect_id),
  'plan',jsonb_build_object('id',owned.id,'source_id',owned.source_id,'operation',owned.operation,'phase',owned.phase,'plan_digest',owned.plan_digest),
  'entry',to_jsonb(entry_owner),'effect',to_jsonb(effect_owner),
  'lines',COALESCE((SELECT jsonb_agg(to_jsonb(detail) ORDER BY detail.line_number,detail.id)
   FROM reconforge.finance_entry_lines detail WHERE detail.tenant_id=t AND detail.entry_id=entry_owner.id),'[]'::jsonb),
  'dimensions',COALESCE((SELECT jsonb_agg(to_jsonb(dimension_link) ORDER BY to_jsonb(dimension_link)::text)
   FROM reconforge.finance_entry_line_dimensions dimension_link JOIN reconforge.finance_entry_lines detail
   ON(detail.tenant_id,detail.id)=(dimension_link.tenant_id,dimension_link.entry_line_id)
   WHERE detail.tenant_id=t AND detail.entry_id=entry_owner.id),'[]'::jsonb),
  'physical',reconforge.it1_native_snapshot(t,movement_owner.id));
 PERFORM reconforge.it1_assert(octet_length(result::text)<=262144,'A transfer restitution original exceeds the finite evidence bound');
 RETURN result;
END $cr2it$;
CREATE OR REPLACE FUNCTION reconforge.customer_partial_return_transfer_originals(t TEXT,cost JSONB) RETURNS VOID
 LANGUAGE plpgsql STABLE SET search_path=pg_catalog AS $cr2it$
DECLARE original JSONB;correction JSONB;normalized JSONB;normalized_sources JSONB:='[]'::jsonb;quantity_delta NUMERIC;value_delta NUMERIC;
 quantity_total NUMERIC:=0;value_total NUMERIC:=0;base_quantity NUMERIC:=0;base_value NUMERIC:=0;correction_count INTEGER:=0;
BEGIN
 PERFORM reconforge.it1_assert(cost->>'schema_version'='inventory-transfer-cost-v2'
  AND(SELECT array_agg(key ORDER BY key) FROM jsonb_object_keys(cost) key)=ARRAY['monetary_policy','remaining_quantity_scaled','remaining_value_minor','schema_version','sources']::text[]
  AND jsonb_typeof(cost->'sources')='array' AND jsonb_array_length(cost->'sources') BETWEEN 1 AND 32
  AND(SELECT count(DISTINCT value#>>'{layer,id}') FROM jsonb_array_elements(cost->'sources'))=jsonb_array_length(cost->'sources'),
  'Transfer v2 retains a finite exact original pool and signed restitution evidence');
 FOR original IN SELECT value FROM jsonb_array_elements(cost->'sources') LOOP
  PERFORM reconforge.it1_assert(jsonb_typeof(original->'partial_return_corrections')='array'
   AND(SELECT count(DISTINCT(value#>>'{restoration,plan_id}',value#>>'{restoration,position}'))
    FROM jsonb_array_elements(original->'partial_return_corrections'))=jsonb_array_length(original->'partial_return_corrections'),
   'Captured transfer restitution membership must be finite and duplicate free');
  quantity_delta:=0;value_delta:=0;
  FOR correction IN SELECT value FROM jsonb_array_elements(original->'partial_return_corrections') LOOP
   correction_count:=correction_count+1;
   PERFORM reconforge.it1_assert(correction_count<=200 AND correction#>>'{restoration,cost_layer_id}'=original#>>'{layer,id}'
    AND correction=reconforge.customer_partial_return_transfer_correction(t,correction#>>'{restoration,plan_id}',(correction#>>'{restoration,position}')::integer),
    'Each captured restitution must retain its exact immutable signed native membership');
   quantity_delta:=quantity_delta+(correction#>>'{restoration,direction}')::numeric*(correction#>>'{restoration,quantity_scaled}')::numeric;
   value_delta:=value_delta+(correction#>>'{restoration,direction}')::numeric*(correction#>>'{restoration,value_minor}')::numeric;
  END LOOP;
  quantity_total:=quantity_total+(original#>>'{layer,remaining_quantity_scaled}')::numeric;
  value_total:=value_total+(original#>>'{layer,remaining_value_minor}')::numeric;
  normalized:=(original-'partial_return_corrections')||jsonb_build_object('layer',(original->'layer')||jsonb_build_object(
   'remaining_quantity_scaled',(original#>>'{layer,remaining_quantity_scaled}')::numeric-quantity_delta,
   'remaining_value_minor',(original#>>'{layer,remaining_value_minor}')::numeric-value_delta));
  base_quantity:=base_quantity+(normalized#>>'{layer,remaining_quantity_scaled}')::numeric;
  base_value:=base_value+(normalized#>>'{layer,remaining_value_minor}')::numeric;
  normalized_sources:=normalized_sources||jsonb_build_array(normalized);
 END LOOP;
 PERFORM reconforge.it1_assert(correction_count BETWEEN 1 AND 200
  AND quantity_total=(cost->>'remaining_quantity_scaled')::numeric AND value_total=(cost->>'remaining_value_minor')::numeric,
  'Transfer v2 captured pool totals require complete retained signed equations');
 -- This is an internal equation normalization, never an observed/persisted v1
 -- original. The unchanged v1 reader checks all original IRP/GL and captured
 -- consumptions while later current populations may legitimately grow.
 PERFORM reconforge.it1_cost_originals(t,cost||jsonb_build_object('schema_version','inventory-transfer-cost-v1',
  'sources',normalized_sources,'remaining_quantity_scaled',base_quantity,'remaining_value_minor',base_value));
END $cr2it$;
"""


def _snapshot() -> str:
    source = _original("it1_cost_snapshot")
    source = _replace(source, " consumed_quantity NUMERIC;consumed_value NUMERIC;history_count INTEGER:=0;", """ consumed_quantity NUMERIC;consumed_value NUMERIC;history_count INTEGER:=0;
 corrections JSONB;correction JSONB;restored_quantity NUMERIC;restored_value NUMERIC;has_restitution BOOLEAN:=FALSE;correction_count INTEGER:=0;""")
    anchor = "  PERFORM reconforge.it1_assert(history_count<=200 AND layer.remaining_quantity_scaled=layer.original_quantity_scaled-consumed_quantity"
    source = _replace(source, anchor, r"""  corrections:='[]'::jsonb;restored_quantity:=0;restored_value:=0;
  IF layer.remaining_quantity_scaled<>layer.original_quantity_scaled-consumed_quantity
   OR layer.remaining_value_minor<>layer.original_value_minor-consumed_value THEN
   has_restitution:=TRUE;
   SELECT count(*) INTO restored_quantity FROM reconforge.customer_partial_return_restorations r
    WHERE r.tenant_id=t AND r.cost_layer_id=layer.id;
   PERFORM reconforge.it1_assert(restored_quantity BETWEEN 1 AND 200-correction_count,
    'Current transfer restitution exceeds the bounded original membership');
   restored_quantity:=0;
   SELECT COALESCE(jsonb_agg(reconforge.customer_partial_return_transfer_correction(t,r.plan_id,r.position)
    ORDER BY r.plan_id,r.position),'[]'::jsonb) INTO corrections FROM reconforge.customer_partial_return_restorations r
    WHERE r.tenant_id=t AND r.cost_layer_id=layer.id;
   correction_count:=correction_count+jsonb_array_length(corrections);
   PERFORM reconforge.it1_assert(correction_count BETWEEN 1 AND 200 AND octet_length(corrections::text)<=1048576,
    'Current transfer restitution requires a complete bounded visible correction population');
   FOR correction IN SELECT value FROM jsonb_array_elements(corrections) LOOP
    restored_quantity:=restored_quantity+(correction#>>'{restoration,direction}')::numeric*(correction#>>'{restoration,quantity_scaled}')::numeric;
    restored_value:=restored_value+(correction#>>'{restoration,direction}')::numeric*(correction#>>'{restoration,value_minor}')::numeric;
   END LOOP;
  END IF;
  PERFORM reconforge.it1_assert(history_count<=200 AND layer.remaining_quantity_scaled=layer.original_quantity_scaled-consumed_quantity+restored_quantity""")
    source = _replace(source, "   AND layer.remaining_value_minor=layer.original_value_minor-consumed_value", "   AND layer.remaining_value_minor=layer.original_value_minor-consumed_value+restored_value")
    source = _replace(source, "  sources:=sources||jsonb_build_array(original);quantities:=quantities+layer.remaining_quantity_scaled;values_minor:=values_minor+layer.remaining_value_minor;", r"""  IF jsonb_array_length(corrections)>0 THEN
   SELECT amounts||COALESCE(jsonb_agg((value#>>'{entry,total_debit_minor}')::bigint ORDER BY ordinal),'[]'::jsonb)
    ||COALESCE(jsonb_agg((value#>>'{entry,total_credit_minor}')::bigint ORDER BY ordinal),'[]'::jsonb) INTO amounts
    FROM jsonb_array_elements(corrections) WITH ORDINALITY ordered_corrections(value,ordinal);
   original:=original||jsonb_build_object('partial_return_corrections',corrections,'exposed_amounts_minor',amounts);
  END IF;
  sources:=sources||jsonb_build_array(original);quantities:=quantities+layer.remaining_quantity_scaled;values_minor:=values_minor+layer.remaining_value_minor;
  PERFORM reconforge.it1_assert(octet_length(sources::text)<=4194304,'Transfer current originals exceed the finite capture bound');""")
    source = _replace(source, " RETURN jsonb_build_object('schema_version','inventory-transfer-cost-v1','monetary_policy',policy,", r""" IF has_restitution THEN
  SELECT jsonb_agg(value||jsonb_build_object('partial_return_corrections',COALESCE(value->'partial_return_corrections','[]'::jsonb)) ORDER BY ordinal)
   INTO sources FROM jsonb_array_elements(sources) WITH ORDINALITY originals(value,ordinal);
 END IF;
 RETURN jsonb_build_object('schema_version',CASE WHEN has_restitution THEN'inventory-transfer-cost-v2' ELSE'inventory-transfer-cost-v1' END,'monetary_policy',policy,""")
    return source


def _reader() -> str:
    return _replace(_original("it1_cost_originals"), "BEGIN\n", r"""BEGIN
 IF cost->>'schema_version'='inventory-transfer-cost-v2' THEN
  PERFORM reconforge.customer_partial_return_transfer_originals(t,cost);RETURN;
 END IF;
""")


def _origins() -> str:
    source = _replace(_original("it1_stock_origins"), "DECLARE physical RECORD;source RECORD;receipt RECORD;consumed RECORD;seen INTEGER:=0;", "DECLARE physical RECORD;source RECORD;receipt RECORD;consumed RECORD;seen INTEGER:=0;partial_owner RECORD;")
    return _replace(source, "  IF physical.movement_type='Receipt' THEN", r"""  IF physical.head->>'movement_number'~'^CR2(R)?-[A-F0-9]{32}$' THEN
   SELECT partial_plan.* INTO partial_owner FROM reconforge.customer_partial_return_plans partial_plan
    JOIN reconforge.customer_partial_return_sources partial_source ON(partial_source.tenant_id,partial_source.id)=(partial_plan.tenant_id,partial_plan.source_id)
    WHERE partial_plan.tenant_id=t AND partial_plan.id=physical.head->>'source_reference'
    AND partial_plan.payload->>'movement_id'=physical.movement_id
    AND(partial_source.workspace_id,partial_source.organization_id,partial_source.legal_entity_id,partial_source.item_id,
     partial_source.uom_id,partial_source.quantity_precision)=(w,o,e,i,physical.uom_id,physical.quantity_precision);
   PERFORM reconforge.it1_assert(partial_owner.id IS NOT NULL AND partial_owner.phase=2
    AND partial_owner.operation IN('Return','ReverseReturn') AND physical.quantity_scaled=partial_owner.quantity_scaled
    AND physical.head->>'source_type'='Generated' AND physical.head->>'movement_number'=upper(partial_owner.id)
    AND physical.movement_type=CASE partial_owner.operation WHEN'Return' THEN'Receipt' ELSE'Delivery' END,
    'New transfer adoption requires exact posted original partial-return physical ownership');
   PERFORM reconforge.customer_partial_return_close(t,partial_owner.id);
  ELSIF physical.movement_type='Receipt' THEN""")


ORIGINAL_FUNCTIONS = {name: _original(name) for name in ORIGINAL_BODY_HASHES}
UPGRADED_FUNCTIONS = {"it1_cost_snapshot": _snapshot(), "it1_cost_originals": _reader(), "it1_stock_origins": _origins()}


def _preflight(*, upgraded_only: bool = False) -> str:
    clauses = []
    for name in ORIGINAL_FUNCTIONS:
        hashes = [hashlib.sha256(UPGRADED_FUNCTIONS[name].split("$it1$")[1].encode()).hexdigest()]
        if not upgraded_only:
            hashes.append(ORIGINAL_BODY_HASHES[name])
        signature = "text,jsonb" if name == "it1_cost_originals" else "text,text,text,text,text"
        returns = "jsonb" if name == "it1_cost_snapshot" else "void"
        volatility = "v" if name == "it1_stock_origins" else "s"
        arguments = "ARRAY['t','cost']::text[]" if name == "it1_cost_originals" else "ARRAY['t','w','o','e','i']::text[]"
        clause = """ SELECT * INTO native FROM pg_proc WHERE oid=to_regprocedure('reconforge.@@NAME@@(@@SIGNATURE@@)');
 IF native.oid IS NULL OR native.prosecdef OR native.proretset OR native.proleakproof OR native.prokind<>'f'
 OR native.prolang<>(SELECT oid FROM pg_language WHERE lanname='plpgsql') OR native.prorettype<>'@@RETURNS@@'::regtype
 OR native.provolatile<>'@@VOLATILITY@@' OR native.proparallel<>'u' OR native.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog']::text[]
 OR native.proargnames IS DISTINCT FROM @@ARGUMENTS@@ OR native.proargmodes IS NOT NULL OR native.pronargdefaults<>0
 OR encode(sha256(convert_to(native.prosrc,'UTF8')),'hex') NOT IN(@@HASHES@@) THEN
 RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Original IT1 execution contract drift';END IF;"""
        for token, value in (("NAME", name), ("SIGNATURE", signature), ("RETURNS", returns), ("VOLATILITY", volatility),
                             ("ARGUMENTS", arguments), ("HASHES", ",".join(repr(value) for value in hashes))):
            clause = clause.replace("@@" + token + "@@", value)
        clauses.append(clause)
    return "DO $cr2it$ DECLARE native RECORD;BEGIN\n" + "\n".join(clauses) + "\nEND $cr2it$;"


UPGRADE_SQL = _preflight() + CORRECTION_SQL + "\n".join(UPGRADED_FUNCTIONS.values())
DOWNGRADE_SQL = "\n".join((_preflight(), r"""
DO $cr2it$ BEGIN
 IF EXISTS(SELECT 1 FROM reconforge.inventory_transfer_sources WHERE payload#>>'{cost_snapshot,schema_version}'='inventory-transfer-cost-v2'
  OR review_cost_json->>'schema_version'='inventory-transfer-cost-v2') THEN
 RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Retained transfer restitution evidence prevents destructive downgrade';END IF;
END $cr2it$;
""", "\n".join(ORIGINAL_FUNCTIONS.values()), r"""
DROP FUNCTION IF EXISTS reconforge.customer_partial_return_transfer_originals(TEXT,JSONB),
 reconforge.customer_partial_return_transfer_correction(TEXT,TEXT,INTEGER);
"""))


def install_postgres_customer_partial_return_transfer_hooks(connection: Any) -> None:
    """Replay after original installers only when the CR2 owner is installed."""
    row = connection.execute("SELECT to_regclass('reconforge.customer_partial_return_restorations') owner_relation").fetchone()
    if row is None:
        raise RuntimeError("Native partial-return installation lookup failed")
    owner_relation = row["owner_relation"] if isinstance(row, Mapping) else row[0]
    if owner_relation is None:
        return
    marker = connection.execute(
        "SELECT to_regprocedure('reconforge.customer_partial_return_rounding_version()') rounding_owner"
    ).fetchone()
    if marker is None:
        raise RuntimeError("Native partial-return version lookup failed")
    rounding_owner = marker["rounding_owner"] if isinstance(marker, Mapping) else marker[0]
    if rounding_owner is not None:
        from reconforge.infrastructure.postgres_customer_partial_return_rounding_schema import (
            install_customer_partial_return_rounding,
        )

        install_customer_partial_return_rounding(connection)
        return
    connection.execute(UPGRADE_SQL)
