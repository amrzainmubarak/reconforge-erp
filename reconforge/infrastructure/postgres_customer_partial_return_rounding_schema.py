"""Additive revision148: source-birth allocation v2 and exact v1 dispatch.

Historical147 constants are imported, never edited. CREATE OR REPLACE retains
existing function OIDs/owners/ACLs; downgrade refuses every retained v2 source.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from reconforge.infrastructure.postgres_customer_partial_return_rounding_transfer_hooks import (
    DOWNGRADE_PREFLIGHT_SQL as TRANSFER_DOWNGRADE_PREFLIGHT_SQL,
)
from reconforge.infrastructure.postgres_customer_partial_return_rounding_transfer_hooks import (
    DOWNGRADE_SQL as TRANSFER_DOWNGRADE_SQL,
)
from reconforge.infrastructure.postgres_customer_partial_return_rounding_transfer_hooks import (
    UPGRADE_SQL as TRANSFER_UPGRADE_SQL,
)
from reconforge.infrastructure.postgres_customer_partial_return_rounding_transfer_hooks import (
    _preflight as transfer_preflight,
)
from reconforge.infrastructure.postgres_customer_partial_returns_schema import (
    CLOSURE_SQL,
    COLLECTION_SQL,
    PLAN_SQL,
)
from reconforge.infrastructure.postgres_finance_posting import records


def _original(name: str) -> str:
    matches = re.findall(r"CREATE FUNCTION reconforge\." + re.escape(name) + r"\([^$]+\$cr2\$.*?END \$cr2\$;",
                         CLOSURE_SQL + PLAN_SQL + COLLECTION_SQL, re.S)
    if len(matches) != 1:
        raise ValueError("One exact retained partial-return function is required.")
    return matches[0]


def _replace(value: str, old: str, new: str) -> str:
    if value.count(old) != 1:
        raise ValueError("The retained partial-return function anchor differs.")
    return value.replace(old, new)


ORIGINAL_FUNCTIONS = {name: _original(name) for name in (
    "customer_partial_return_balance", "customer_partial_return_public", "customer_partial_return_source_close",
    "customer_partial_return_close",
)}

VALUES_SQL = r"""
CREATE FUNCTION reconforge.customer_partial_return_rounding_version() RETURNS TEXT LANGUAGE sql IMMUTABLE
 SET search_path=pg_catalog AS $cr148$ SELECT 'remaining-original-v1'::text $cr148$;
CREATE FUNCTION reconforge.customer_partial_return_v2_fifo(v BIGINT,q BIGINT,selected BIGINT) RETURNS BIGINT
 LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog AS $cr148$
DECLARE quotient NUMERIC;remainder NUMERIC;
BEGIN
 IF v IS NULL OR q IS NULL OR selected IS NULL OR v<0 OR q<=0 OR selected<=0 OR selected>q THEN
  RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='customer_partial_return_owner',MESSAGE='Remaining original FIFO arguments differ'; END IF;
 IF selected=q THEN RETURN v; END IF;
 -- Same integer HALF_EVEN rule as stock_sales_fifo_value; v2 explicitly
 -- permits zero/value-exhaustion because financial zero legs are omitted.
 quotient:=div(v::numeric*selected,q);remainder:=mod(v::numeric*selected,q);
 IF remainder*2>q OR(remainder*2=q AND mod(quotient,2)=1) THEN quotient:=quotient+1; END IF;
 RETURN quotient::bigint;
END $cr148$;
CREATE FUNCTION reconforge.customer_partial_return_v2_values(t TEXT,i TEXT,selected BIGINT,version INTEGER) RETURNS JSONB
 LANGUAGE plpgsql VOLATILE SET search_path=pg_catalog AS $cr148$
DECLARE source_owner RECORD;prior RECORD;cons JSONB;parts JSONB:='[]'::jsonb;remaining_q NUMERIC;remaining_v NUMERIC;
 returned NUMERIC;credited NUMERIC;collected NUMERIC;old_q NUMERIC;old_v NUMERIC;take NUMERIC;pending NUMERIC;
 credit NUMERIC;cost NUMERIC:=0;part_cost BIGINT;release NUMERIC;
BEGIN
 SELECT * INTO source_owner FROM reconforge.customer_partial_return_sources WHERE tenant_id=t AND id=i;
 IF source_owner IS NULL OR source_owner.source_payload->>'allocation_policy' IS DISTINCT FROM'remaining-original-v1'
 OR source_owner.currency_rounding_policy<>'ROUND_HALF_UP' OR selected IS NULL OR selected<=0 OR version NOT BETWEEN 0 AND 255 THEN
  RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='customer_partial_return_owner',MESSAGE='Remaining allocation requires its exact visible source-birth policy'; END IF;
 SELECT count(*) n,
 COALESCE(sum(CASE kind WHEN'Return' THEN quantity_scaled WHEN'ReverseReturn' THEN-quantity_scaled ELSE 0 END),0) quantities,
 COALESCE(sum(CASE kind WHEN'Return' THEN credit_minor WHEN'ReverseReturn' THEN-credit_minor ELSE 0 END),0) credits,
 COALESCE(sum(CASE kind WHEN'Collection' THEN amount_minor ELSE 0 END),0) cash INTO prior
 FROM reconforge.customer_partial_return_history WHERE tenant_id=t AND source_id=i AND sequence<=version;
 returned:=prior.quantities;credited:=prior.credits;collected:=source_owner.initial_collected_minor+prior.cash;
 remaining_q:=source_owner.original_quantity_scaled-returned;remaining_v:=source_owner.gross_minor-credited;
 IF prior.n<>version OR remaining_q<=0 OR selected>remaining_q OR remaining_v<0 THEN
  RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='customer_partial_return_owner',MESSAGE='Remaining allocation prefix or quantity differs'; END IF;
 credit:=CASE WHEN selected=remaining_q THEN remaining_v ELSE div(remaining_v*selected,remaining_q)
  +CASE WHEN mod(remaining_v*selected,remaining_q)*2>=remaining_q THEN 1 ELSE 0 END END;
 pending:=selected;
 FOR cons IN SELECT value FROM jsonb_array_elements(source_owner.source_payload->'typed_source'->'consumptions') LOOP
  SELECT COALESCE(sum(CASE h.kind WHEN'Return' THEN (part->>'quantity_scaled')::numeric ELSE-(part->>'quantity_scaled')::numeric END),0),
   COALESCE(sum(CASE h.kind WHEN'Return' THEN (part->>'value_minor')::numeric ELSE-(part->>'value_minor')::numeric END),0)
   INTO old_q,old_v FROM reconforge.customer_partial_return_history h
   CROSS JOIN LATERAL jsonb_array_elements(h.payload->'return_values'->'portions') part
   WHERE h.tenant_id=t AND h.source_id=i AND h.sequence<=version AND h.kind IN('Return','ReverseReturn')
   AND part->>'original_consumption_id'=cons->>'consumption_id';
  remaining_q:=(cons->>'quantity_scaled')::numeric-old_q;remaining_v:=(cons->>'value_minor')::numeric-old_v;
  IF remaining_q<0 OR remaining_v<0 OR(remaining_q=0 AND remaining_v<>0) OR old_q<0 OR old_v<0 THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='customer_partial_return_owner',MESSAGE='Original consumption active signed prefix differs'; END IF;
  take:=least(pending,remaining_q);
  IF take>0 THEN
   part_cost:=reconforge.customer_partial_return_v2_fifo(remaining_v::bigint,remaining_q::bigint,take::bigint);
   parts:=parts||jsonb_build_array(jsonb_build_object('position',cons->'position','original_consumption_id',cons->>'consumption_id',
    'original_valuation_line_id',cons->>'valuation_line_id','cost_layer_id',cons->>'cost_layer_id',
    'offset_quantity_scaled',old_q,'quantity_scaled',take,'value_minor',part_cost,
    'before_quantity_scaled',remaining_q,'before_value_minor',remaining_v));
   pending:=pending-take;cost:=cost+part_cost;
  END IF;
  EXIT WHEN pending=0;
 END LOOP;
 IF pending<>0 THEN RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='customer_partial_return_owner',MESSAGE='Remaining original FIFO membership is incomplete'; END IF;
 release:=least(credit,greatest(source_owner.gross_minor-credited-collected,0));
 RETURN jsonb_build_object('quantity_before_scaled',returned,'quantity_scaled',selected,'returned_quantity_scaled',returned+selected,
 'credit_minor',credit,'cogs_restored_minor',cost,'receivable_released_minor',release,'refund_entitlement_delta_minor',credit-release,
 'outstanding_after_minor',greatest(source_owner.gross_minor-credited-credit-collected,0),'portions',parts,
 'allocation_policy','remaining-original-v1','revenue_before_quantity_scaled',source_owner.original_quantity_scaled-returned,
 'revenue_before_value_minor',source_owner.gross_minor-credited);
END $cr148$;
"""


def _source_v2() -> str:
    value = ORIGINAL_FUNCTIONS["customer_partial_return_source_close"].replace(
        "customer_partial_return_source_close(", "customer_partial_return_source_close_v2(", 1)
    value = _replace(value, " IF s IS NULL THEN", " IF s IS NULL OR s.source_payload->>'allocation_policy' IS DISTINCT FROM'remaining-original-v1' THEN")
    value = _replace(value,
        "chain:=reconforge.irp_digest(jsonb_build_object('contract','customer-partial-return-domain-v1','source',s.source_fingerprint));cash:=s.initial_collected_minor;",
        "chain:=reconforge.irp_digest(jsonb_build_object('contract','customer-partial-return-domain-v2','source',s.source_fingerprint,'allocation_policy','remaining-original-v1'));cash:=s.initial_collected_minor;")
    start = value.index("    IF p.quantity_scaled>s.original_quantity_scaled-q")
    end = value.index("    q:=q+p.quantity_scaled", start)
    value = value[:start] + r"""    IF p.payload->>'allocation_policy' IS DISTINCT FROM'remaining-original-v1'
    OR p.payload->'domain_plan'->>'schema_version' IS DISTINCT FROM'customer-partial-return-domain-v2'
    OR p.payload->'domain_plan'->>'source_fingerprint' IS DISTINCT FROM s.source_fingerprint
    OR p.payload->'domain_plan'->>'history_fingerprint' IS DISTINCT FROM chain
    OR p.payload->'domain_plan'->'expected_version' IS DISTINCT FROM to_jsonb(h.sequence-1)
    OR ((p.payload->'domain_plan')-ARRAY['schema_version','source_fingerprint','history_fingerprint','expected_version'])
     IS DISTINCT FROM reconforge.customer_partial_return_v2_values(t,i,p.quantity_scaled,h.sequence-1)
    OR row->'return_values' IS DISTINCT FROM((p.payload->'domain_plan')-ARRAY['schema_version','source_fingerprint','history_fingerprint','expected_version'])
    OR(h.quantity_scaled,h.credit_minor,h.cogs_minor) IS DISTINCT FROM(p.quantity_scaled,p.credit_minor,p.cogs_restored_minor) THEN
     RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='customer_partial_return_owner',MESSAGE='V2 return must retain the exact active original before-value allocation'; END IF;
""" + value[end:]
    return value


def _plan_v2() -> str:
    value = ORIGINAL_FUNCTIONS["customer_partial_return_close"].replace("customer_partial_return_close(", "customer_partial_return_close_v2(", 1)
    value = _replace(value, "'customer-partial-return-v1'", "'customer-partial-return-v2'")
    value = _replace(value, " IF p.original_id IS NOT NULL THEN", r""" IF p.payload->>'allocation_policy' IS DISTINCT FROM'remaining-original-v1'
 OR s.source_payload->>'allocation_policy' IS DISTINCT FROM'remaining-original-v1' THEN
  RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='customer_partial_return_owner',MESSAGE='V2 plan and original source policy must agree'; END IF;
 IF p.operation='Return' AND(p.payload->'domain_plan'->>'schema_version' IS DISTINCT FROM'customer-partial-return-domain-v2'
 OR p.payload->'domain_plan'->>'source_fingerprint' IS DISTINCT FROM s.source_fingerprint
 OR p.payload->'domain_plan'->'expected_version' IS DISTINCT FROM to_jsonb(p.expected_history_version)
 OR (p.credit_minor,p.cogs_restored_minor,p.receivable_released_minor,p.refund_entitlement_delta_minor) IS DISTINCT FROM
 ((p.payload#>>'{domain_plan,credit_minor}')::bigint,(p.payload#>>'{domain_plan,cogs_restored_minor}')::bigint,
 (p.payload#>>'{domain_plan,receivable_released_minor}')::bigint,(p.payload#>>'{domain_plan,refund_entitlement_delta_minor}')::bigint)
 OR ((p.payload->'domain_plan')-ARRAY['schema_version','source_fingerprint','history_fingerprint','expected_version'])
 IS DISTINCT FROM reconforge.customer_partial_return_v2_values(t,s.id,p.quantity_scaled,p.expected_history_version)) THEN
  RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='customer_partial_return_owner',MESSAGE='V2 prepared allocation must retain its exact original prefix'; END IF;
 IF p.original_id IS NOT NULL THEN""")
    value = _replace(value, "CASE WHEN p.operation IN('Return','ReverseReturn') THEN 2 ELSE 1 END",
                     "CASE WHEN p.operation IN('Return','ReverseReturn') THEN (p.credit_minor>0)::integer+(p.cogs_restored_minor>0)::integer ELSE 1 END")
    value = _replace(value, "  entry_number:=upper(p.id)||CASE WHEN p.operation='Refund' THEN'' WHEN ordinal=0 THEN'-R' ELSE'-C' END;",
        "  entry_number:=upper(p.id)||CASE WHEN p.operation='Refund' THEN'' WHEN part->>'purpose' IN('CostRestoration','ReverseCostRestoration') THEN'-C' ELSE'-R' END;")
    value = value.replace("CASE ordinal WHEN 0 THEN'RevenueCredit' ELSE'CostRestoration' END",
        "CASE WHEN ordinal=0 AND p.credit_minor>0 THEN'RevenueCredit' ELSE'CostRestoration' END")
    value = value.replace("CASE ordinal WHEN 0 THEN'ReverseRevenueCredit' ELSE'ReverseCostRestoration' END",
        "CASE WHEN ordinal=0 AND p.credit_minor>0 THEN'ReverseRevenueCredit' ELSE'ReverseCostRestoration' END")
    value = _replace(value, "IF p.operation='Return' AND ordinal=0 THEN", "IF p.operation='Return' AND part->>'purpose'='RevenueCredit' THEN")
    value = _replace(value, " ar:=s.source_payload->'original_source'", r""" IF p.operation IN('ReverseReturn','ReverseRefund') THEN
 IF(
 (p.amount_minor,p.quantity_scaled,p.credit_minor,p.cogs_restored_minor,p.receivable_released_minor,p.refund_entitlement_delta_minor)
 IS DISTINCT FROM(o.amount_minor,o.quantity_scaled,o.credit_minor,o.cogs_restored_minor,o.receivable_released_minor,o.refund_entitlement_delta_minor)
 OR(p.operation='ReverseReturn' AND p.payload->'domain_plan' IS DISTINCT FROM o.payload->'domain_plan')) THEN
  RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='customer_partial_return_owner',MESSAGE='Reverse plan must preserve its exact original quantities amounts and allocation witness'; END IF;
 END IF;
 ar:=s.source_payload->'original_source'""")
    value = _replace(value, "  OR command.request_json->>'operation'", "  OR command.request_json->'protocol_version' IS DISTINCT FROM'2'::jsonb\n  OR command.request_json->>'operation'")
    value = _replace(value, "FROM reconforge.customer_partial_return_restorations z JOIN reconforge.finance_posting_effects owned_effect",
                           "FROM reconforge.customer_partial_return_restorations z LEFT JOIN reconforge.finance_posting_effects owned_effect")
    value = _replace(value, "   AND owned_effect.entry_id=p.payload->'entries'->1->>'entry_id'", r"""   AND EXISTS(SELECT 1 FROM reconforge.customer_partial_return_allocation_witnesses witness
    WHERE witness.tenant_id=z.tenant_id AND witness.plan_id=z.plan_id AND witness.position=z.position
    AND to_jsonb(witness.before_quantity_scaled)=x->'before_quantity_scaled' AND to_jsonb(witness.before_value_minor)=x->'before_value_minor')
   AND ((p.cogs_restored_minor=0 AND z.correction_effect_id IS NULL) OR(p.cogs_restored_minor>0 AND EXISTS(
    SELECT 1 FROM jsonb_array_elements(p.payload->'entries') cost_part
    WHERE cost_part->>'purpose' IN('CostRestoration','ReverseCostRestoration') AND owned_effect.entry_id=cost_part->>'entry_id')))""")
    return value


def _dispatch(name: str, target: str, selector: str) -> str:
    value = ORIGINAL_FUNCTIONS[name].replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1)
    return _replace(value, "BEGIN\n", "BEGIN\n IF " + selector + " THEN PERFORM reconforge." + target + "(t,i);RETURN;END IF;\n")


def _balance() -> str:
    value = ORIGINAL_FUNCTIONS["customer_partial_return_balance"].replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1)
    value = _replace(value, " RETURN jsonb_build_object('source_id'", " RETURN CASE WHEN s.source_payload->>'allocation_policy'='remaining-original-v1' THEN jsonb_build_object('schema_version','customer-partial-return-balance-v2','allocation_policy','remaining-original-v1') ELSE'{}'::jsonb END||jsonb_build_object('source_id'")
    return _replace(value, "reconforge.irp_digest(jsonb_build_object('contract','customer-partial-return-domain-v1','source',s.source_fingerprint))",
        "reconforge.irp_digest(CASE WHEN s.source_payload->>'allocation_policy'='remaining-original-v1' THEN jsonb_build_object('contract','customer-partial-return-domain-v2','source',s.source_fingerprint,'allocation_policy','remaining-original-v1') ELSE jsonb_build_object('contract','customer-partial-return-domain-v1','source',s.source_fingerprint) END)")


def _public() -> str:
    value = ORIGINAL_FUNCTIONS["customer_partial_return_public"].replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1)
    return _replace(value, "'expected_history_version','posting_date'", "'allocation_policy','expected_history_version','posting_date'")


UPGRADED_FUNCTIONS = {
    "customer_partial_return_balance": _balance(), "customer_partial_return_public": _public(),
    "customer_partial_return_source_close": _dispatch("customer_partial_return_source_close", "customer_partial_return_source_close_v2",
        "EXISTS(SELECT 1 FROM reconforge.customer_partial_return_sources WHERE tenant_id=t AND id=i AND source_payload ? 'allocation_policy')"),
    "customer_partial_return_close": _dispatch("customer_partial_return_close", "customer_partial_return_close_v2",
        "EXISTS(SELECT 1 FROM reconforge.customer_partial_return_plans owned JOIN reconforge.customer_partial_return_sources source_owner ON(source_owner.tenant_id,source_owner.id)=(owned.tenant_id,owned.source_id) WHERE owned.tenant_id=t AND owned.id=i AND(owned.payload ? 'allocation_policy' OR source_owner.source_payload ? 'allocation_policy'))"),
}


WITNESS_SQL = r"""
CREATE TABLE reconforge.customer_partial_return_allocation_witnesses (
 tenant_id TEXT NOT NULL,plan_id TEXT NOT NULL,position INTEGER NOT NULL CHECK(position BETWEEN 1 AND 32),
 before_quantity_scaled BIGINT NOT NULL CHECK(before_quantity_scaled>0),before_value_minor BIGINT NOT NULL CHECK(before_value_minor>=0),
 PRIMARY KEY(tenant_id,plan_id,position),FOREIGN KEY(tenant_id,plan_id,position)
 REFERENCES reconforge.customer_partial_return_restorations(tenant_id,plan_id,position)
);
ALTER TABLE reconforge.customer_partial_return_allocation_witnesses ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.customer_partial_return_allocation_witnesses FORCE ROW LEVEL SECURITY;
CREATE POLICY scope ON reconforge.customer_partial_return_allocation_witnesses USING(EXISTS(
 SELECT 1 FROM reconforge.customer_partial_return_plans p WHERE p.tenant_id=customer_partial_return_allocation_witnesses.tenant_id
 AND p.id=customer_partial_return_allocation_witnesses.plan_id)) WITH CHECK(EXISTS(
 SELECT 1 FROM reconforge.customer_partial_return_plans p WHERE p.tenant_id=customer_partial_return_allocation_witnesses.tenant_id
 AND p.id=customer_partial_return_allocation_witnesses.plan_id));
CREATE FUNCTION reconforge.customer_partial_return_witness_protect() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $cr148$
DECLARE owned RECORD;portion JSONB;
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='customer_partial_return_owner',MESSAGE='Original allocation witness is immutable'; END IF;
 SELECT * INTO owned FROM reconforge.customer_partial_return_plans WHERE tenant_id=NEW.tenant_id AND id=NEW.plan_id;
 SELECT value INTO portion FROM jsonb_array_elements(owned.payload->'domain_plan'->'portions') WHERE(value->>'position')::integer=NEW.position;
 IF owned IS NULL OR owned.operation NOT IN('Return','ReverseReturn') OR owned.phase<>1
 OR owned.payload->>'allocation_policy' IS DISTINCT FROM'remaining-original-v1'
 OR NOT reconforge.customer_return_authority(NEW.tenant_id,current_setting('app.customer_partial_return_actor_id',true),'post')
 OR portion IS NULL OR to_jsonb(NEW.before_quantity_scaled) IS DISTINCT FROM portion->'before_quantity_scaled'
 OR to_jsonb(NEW.before_value_minor) IS DISTINCT FROM portion->'before_value_minor' THEN
  RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='customer_partial_return_owner',MESSAGE='Allocation witness requires its exact native v2 portion and current poster'; END IF;
 RETURN NEW;
END $cr148$;
CREATE TRIGGER immutable BEFORE INSERT OR UPDATE OR DELETE ON reconforge.customer_partial_return_allocation_witnesses
 FOR EACH ROW EXECUTE FUNCTION reconforge.customer_partial_return_witness_protect();
CREATE CONSTRAINT TRIGGER native_close AFTER INSERT ON reconforge.customer_partial_return_allocation_witnesses
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION reconforge.customer_partial_return_deferred_close();
CREATE FUNCTION reconforge.customer_partial_return_zero_layer_guard() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $cr148$
BEGIN
 IF NEW.remaining_quantity_scaled>0 AND NEW.remaining_value_minor=0 THEN
  IF TG_OP='INSERT' OR NOT EXISTS(SELECT 1 FROM reconforge.customer_partial_return_restorations restoration
   JOIN reconforge.customer_partial_return_allocation_witnesses witness ON(witness.tenant_id,witness.plan_id,witness.position)
    =(restoration.tenant_id,restoration.plan_id,restoration.position)
   JOIN reconforge.customer_partial_return_plans owned ON(owned.tenant_id,owned.id)=(restoration.tenant_id,restoration.plan_id)
   JOIN reconforge.customer_partial_return_sources source_owner ON(source_owner.tenant_id,source_owner.id)=(owned.tenant_id,owned.source_id)
   WHERE restoration.tenant_id=NEW.tenant_id AND restoration.cost_layer_id=NEW.id AND owned.phase=1
   AND reconforge.customer_return_authority(NEW.tenant_id,current_setting('app.customer_partial_return_actor_id',true),'post')
   AND owned.preparer_actor_id IS DISTINCT FROM current_setting('app.customer_partial_return_actor_id',true)
   AND EXISTS(SELECT 1 FROM reconforge.customer_partial_return_events reviewed WHERE reviewed.tenant_id=owned.tenant_id
    AND reviewed.plan_id=owned.id AND reviewed.operation='review'
    AND reviewed.actor_id IS DISTINCT FROM current_setting('app.customer_partial_return_actor_id',true))
   AND NEW.remaining_quantity_scaled-OLD.remaining_quantity_scaled=restoration.direction::bigint*restoration.quantity_scaled
   AND NEW.remaining_value_minor-OLD.remaining_value_minor=restoration.direction::bigint*restoration.value_minor
   AND source_owner.source_payload->>'allocation_policy'='remaining-original-v1'
   AND owned.payload->>'allocation_policy'='remaining-original-v1') THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='customer_partial_return_owner',MESSAGE='A zero-value physical layer requires its exact visible native allocation witness'; END IF;
 END IF;
 RETURN NEW;
END $cr148$;
CREATE TRIGGER customer_partial_return_zero_layer BEFORE INSERT OR UPDATE ON reconforge.inventory_cost_layers
 FOR EACH ROW EXECUTE FUNCTION reconforge.customer_partial_return_zero_layer_guard();
"""


def _check(table: str, columns: tuple[str, ...], expression: str) -> str:
    names = ",".join(repr(column) for column in sorted(columns))
    template = """DO $cr148$ DECLARE owned RECORD;n INTEGER;BEGIN
 SELECT count(*) INTO n FROM pg_constraint c WHERE c.conrelid='reconforge.@@TABLE@@'::regclass AND c.contype='c'
 AND(SELECT array_agg(a.attname::text ORDER BY a.attname) FROM unnest(c.conkey) key
 JOIN pg_attribute a ON a.attrelid=c.conrelid AND a.attnum=key)=ARRAY[@@COLUMNS@@]::text[];
 IF n<>1 THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Original allocation constraint membership drift'; END IF;
 SELECT c.conname INTO owned FROM pg_constraint c WHERE c.conrelid='reconforge.@@TABLE@@'::regclass AND c.contype='c'
 AND(SELECT array_agg(a.attname::text ORDER BY a.attname) FROM unnest(c.conkey) key
 JOIN pg_attribute a ON a.attrelid=c.conrelid AND a.attnum=key)=ARRAY[@@COLUMNS@@]::text[];
 EXECUTE format('ALTER TABLE reconforge.@@TABLE@@ DROP CONSTRAINT %I',owned.conname);
 EXECUTE format('ALTER TABLE reconforge.@@TABLE@@ ADD CONSTRAINT %I CHECK(@@EXPRESSION@@)',owned.conname);
END $cr148$;"""
    return template.replace("@@TABLE@@", table).replace("@@COLUMNS@@", names).replace("@@EXPRESSION@@", expression.replace("'", "''"))


PLAN_MAGNITUDE_V1 = "(operation IN('Return','ReverseReturn') AND quantity_scaled>0 AND credit_minor>0 AND cogs_restored_minor>0 AND credit_minor=receivable_released_minor+refund_entitlement_delta_minor AND amount_minor=credit_minor+cogs_restored_minor) OR(operation IN('Refund','ReverseRefund') AND quantity_scaled=0 AND credit_minor=0 AND cogs_restored_minor=0 AND receivable_released_minor=0 AND refund_entitlement_delta_minor=0)"
PLAN_MAGNITUDE_V2 = "(operation IN('Return','ReverseReturn') AND quantity_scaled>0 AND credit_minor>=0 AND cogs_restored_minor>=0 AND credit_minor=receivable_released_minor+refund_entitlement_delta_minor AND amount_minor=credit_minor+cogs_restored_minor AND((payload->>'allocation_policy' IS NOT DISTINCT FROM'remaining-original-v1' AND payload->>'schema_version' IS NOT DISTINCT FROM'customer-partial-return-v2') OR(credit_minor>0 AND cogs_restored_minor>0))) OR(operation IN('Refund','ReverseRefund') AND quantity_scaled=0 AND credit_minor=0 AND cogs_restored_minor=0 AND receivable_released_minor=0 AND refund_entitlement_delta_minor=0 AND amount_minor>0)"
MAGNITUDE_COLUMNS = ("operation", "quantity_scaled", "credit_minor", "cogs_restored_minor", "receivable_released_minor", "refund_entitlement_delta_minor", "amount_minor")


def _constraints(*, upgraded: bool) -> str:
    result = _check("customer_partial_return_plans", ("amount_minor",),
        "amount_minor BETWEEN 0 AND 9000000000000000000" if upgraded else "amount_minor BETWEEN 1 AND 9000000000000000000")
    # The v2 expression has one additional payload column, so use that exact
    # catalog membership on downgrade rather than accidentally selecting a
    # different financial constraint.
    result += _check("customer_partial_return_plans", MAGNITUDE_COLUMNS if upgraded else (*MAGNITUDE_COLUMNS, "payload"),
                     PLAN_MAGNITUDE_V2 if upgraded else PLAN_MAGNITUDE_V1)
    result += _check("customer_partial_return_restorations", ("value_minor",), "value_minor>=0" if upgraded else "value_minor>0")
    result += _check("inventory_cost_layers", ("remaining_quantity_scaled", "remaining_value_minor"),
        "(remaining_quantity_scaled=0 AND remaining_value_minor=0) OR(remaining_quantity_scaled>0 AND remaining_value_minor>=0)" if upgraded
        else "(remaining_quantity_scaled=0 AND remaining_value_minor=0) OR(remaining_quantity_scaled>0 AND remaining_value_minor>0)")
    return result + ("ALTER TABLE reconforge.customer_partial_return_restorations ALTER COLUMN correction_effect_id DROP NOT NULL;" if upgraded else
                     "ALTER TABLE reconforge.customer_partial_return_restorations ALTER COLUMN correction_effect_id SET NOT NULL;")


def _preflight(*, upgraded_only: bool = False) -> str:
    clauses = []
    for name, original in ORIGINAL_FUNCTIONS.items():
        definitions = [UPGRADED_FUNCTIONS[name]] if upgraded_only else [original, UPGRADED_FUNCTIONS[name]]
        hashes = ",".join(repr(hashlib.sha256(value.split("$cr2$")[1].encode()).hexdigest()) for value in definitions)
        signature = "text,text,integer" if name.endswith("_public") else "text,text"
        template = """ SELECT * INTO native FROM pg_proc WHERE oid=to_regprocedure('reconforge.@@NAME@@(@@SIGNATURE@@)');
 IF native.oid IS NULL OR native.prosecdef OR native.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog']::text[]
 OR encode(sha256(convert_to(native.prosrc,'UTF8')),'hex') NOT IN(@@HASHES@@) THEN
 RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Original partial allocation execution contract drift'; END IF;"""
        clauses.append(template.replace("@@NAME@@", name).replace("@@SIGNATURE@@", signature).replace("@@HASHES@@", hashes))
    return "DO $cr148$ DECLARE native RECORD;BEGIN\n" + "\n".join(clauses) + "\nEND $cr148$;"


UPGRADE_SQL = _preflight() + VALUES_SQL + WITNESS_SQL + _constraints(upgraded=True) + _source_v2() + _plan_v2() + "\n".join(UPGRADED_FUNCTIONS.values()) + TRANSFER_UPGRADE_SQL
DOWNGRADE_PREFLIGHT_SQL = r"""
DO $cr148$ BEGIN
 IF EXISTS(SELECT 1 FROM reconforge.customer_partial_return_sources WHERE source_payload ? 'allocation_policy')
 OR EXISTS(SELECT 1 FROM reconforge.customer_partial_return_plans WHERE payload ? 'allocation_policy')
 OR EXISTS(SELECT 1 FROM reconforge.customer_partial_return_allocation_witnesses) THEN
  RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Remaining-original downgrade refuses retained v2 evidence; restore the verified backup'; END IF;
END $cr148$;
"""
DOWNGRADE_SQL = DOWNGRADE_PREFLIGHT_SQL + TRANSFER_DOWNGRADE_PREFLIGHT_SQL + _preflight(upgraded_only=True) + TRANSFER_DOWNGRADE_SQL + _constraints(upgraded=False) + "\n".join(
    value.replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1) for value in ORIGINAL_FUNCTIONS.values()) + r"""
DROP TRIGGER customer_partial_return_zero_layer ON reconforge.inventory_cost_layers;
DROP FUNCTION reconforge.customer_partial_return_zero_layer_guard();
DROP TABLE reconforge.customer_partial_return_allocation_witnesses;
DROP FUNCTION reconforge.customer_partial_return_witness_protect();
DROP FUNCTION reconforge.customer_partial_return_close_v2(TEXT,TEXT);
DROP FUNCTION reconforge.customer_partial_return_source_close_v2(TEXT,TEXT);
DROP FUNCTION reconforge.customer_partial_return_v2_values(TEXT,TEXT,BIGINT,INTEGER);
DROP FUNCTION reconforge.customer_partial_return_v2_fifo(BIGINT,BIGINT,BIGINT);
DROP FUNCTION reconforge.customer_partial_return_rounding_version();
"""


def install_customer_partial_return_rounding(connection: Any) -> None:
    """Idempotent retained148 verifier; no legacy body is overwritten here."""
    exists = records(connection.execute("SELECT to_regprocedure('reconforge.customer_partial_return_rounding_version()') present"))[0]["present"]
    if exists is None:
        return
    connection.execute(_preflight(upgraded_only=True))
    connection.execute(transfer_preflight(upgraded_only=True))
