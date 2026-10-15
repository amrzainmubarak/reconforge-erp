"""Finite native Stock admission for governed v2 restituted FIFO zero slices.

The original Stock/valuation functions keep their bodies below explicit new
dispatch. No original layer or journal is invented: zero-cost physical issues
retain native Approved valuations and immutable consumption rows without GL.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from reconforge.infrastructure.postgres_commercial_collections_extension import UPGRADE_SQL as COLLECTION_EXTENSION
from reconforge.infrastructure.postgres_customer_partial_returns_schema import STORAGE_SQL
from reconforge.infrastructure.postgres_customer_returns_schema import _FORWARD_SQL as RETURN_EXTENSION
from reconforge.infrastructure.postgres_finance_posting import records
from reconforge.infrastructure.postgres_inventory_valuation import POSTGRES_INVENTORY_VALUATION_SCHEMA_SQL
from reconforge.infrastructure.postgres_stock_sales_schema import POSTGRES_STOCK_SALES_SCHEMA_SQL


def _replace(value: str, old: str, new: str) -> str:
    if value.count(old) != 1:
        raise ValueError("The retained zero-stock execution anchor differs.")
    return value.replace(old, new)


def _original(name: str, sql: str, *, delimiter: str = "$$") -> str:
    matches = re.findall(r"CREATE(?: OR REPLACE)? FUNCTION reconforge\." + re.escape(name) + r"\(.*?" + re.escape(delimiter) + ";", sql, re.S)
    if len(matches) != 1:
        raise ValueError("One exact original Stock function is required.")
    return matches[0]


def _stock_original() -> str:
    """Reproduce the audited146 body, then its sole additive147 status pin."""
    value = _original("stock_sales_close", POSTGRES_STOCK_SALES_SCHEMA_SQL)
    section = COLLECTION_EXTENSION.split("definition:=pg_get_functiondef('reconforge.stock_sales_close(text,text)'::regprocedure);original:=definition;", 1)[1].split("EXECUTE definition;", 1)[0]
    for old, new in re.findall(r"definition:=replace\(definition,\s*'((?:[^']|'')*)',\s*'((?:[^']|'')*)'\);", section, re.S):
        value = _replace(value, old.replace("''", "'"), new.replace("''", "'"))
    value = _replace(value,
        "OR EXISTS(SELECT 1 FROM reconforge.finance_entries WHERE tenant_id=t AND reverses_posting_id=d.cogs_effect_id)",
        "OR EXISTS(SELECT 1 FROM reconforge.finance_entries WHERE tenant_id=t AND reverses_posting_id=d.cogs_effect_id AND NOT reconforge.customer_return_inverse_entry(t,d.id,id))")
    value = _replace(value,
        "OR EXISTS(SELECT 1 FROM reconforge.finance_posting_effects WHERE tenant_id=t AND reverses_effect_id=d.cogs_effect_id)",
        "OR EXISTS(SELECT 1 FROM reconforge.finance_posting_effects WHERE tenant_id=t AND reverses_effect_id=d.cogs_effect_id AND NOT reconforge.customer_return_inverse_entry(t,d.id,entry_id))")
    value = _replace(value, "invoice.status IS DISTINCT FROM(CASE WHEN s=7 THEN'Submitted' WHEN s=12 THEN'Paid' ELSE'Approved' END)",
        "(NOT reconforge.customer_return_credited(t,d.invoice_id) AND invoice.status IS DISTINCT FROM(CASE WHEN s=7 THEN'Submitted' WHEN s=12 THEN'Paid' ELSE'Approved' END))")
    value = _replace(value, "invoice.status IN('Approved','PartiallyPaid','Paid')", "(invoice.status IN('Approved','PartiallyPaid','Paid') OR reconforge.customer_return_credited(t,d.invoice_id))")
    anchor = "posted:=EXISTS(SELECT 1 FROM reconforge.operational_finance_links WHERE tenant_id=t AND plan_id=p.id);"
    if value.count(anchor) != 2:
        raise ValueError("The retained original invoice/cash closure differs.")
    value = value.replace(anchor, anchor + RETURN_EXTENSION.split("$inverse$")[1])
    if hashlib.sha256(value.split("$$")[1].encode()).hexdigest() != "8e510df4c82daa5ab3964748d6878573777b55eadbf1e9c394783dd11b86cd39":
        raise ValueError("The reconstructed audited146 Stock body differs.")
    return _replace(value, "NOT reconforge.customer_return_credited(t,d.invoice_id)",
        "NOT reconforge.customer_return_credited(t,d.invoice_id) AND NOT reconforge.customer_partial_return_invoice_credited(t,d.invoice_id)")


ORIGINAL_FUNCTIONS = {
    "stock_sales_close": _stock_original(),
    "stock_sales_public": _original("stock_sales_public", POSTGRES_STOCK_SALES_SCHEMA_SQL),
    "inventory_valuation_guard": _original("inventory_valuation_guard", POSTGRES_INVENTORY_VALUATION_SCHEMA_SQL),
    "customer_partial_return_protect": _original("customer_partial_return_protect", STORAGE_SQL, delimiter="$cr2$"),
}

ADMISSION_SQL = r"""
CREATE FUNCTION reconforge.customer_partial_return_zero_stock_cost(t TEXT,w TEXT,o TEXT,e TEXT,i TEXT,allocations JSONB)
 RETURNS JSONB LANGUAGE plpgsql STABLE SET search_path=pg_catalog AS $cr148zs$
DECLARE cost JSONB;selected JSONB;pool JSONB;correction JSONB;net_quantity NUMERIC;needed BOOLEAN:=FALSE;
BEGIN
 cost:=reconforge.it1_cost_snapshot(t,w,o,e,i);
 PERFORM reconforge.it1_assert(cost->>'schema_version'='inventory-transfer-cost-v3'
  AND jsonb_typeof(allocations)='array' AND jsonb_array_length(allocations) BETWEEN 1 AND 32,
  'Restituted Stock issue requires its explicit native v3 cost pool');
 FOR selected IN SELECT value FROM jsonb_array_elements(allocations) LOOP
  SELECT value INTO pool FROM jsonb_array_elements(cost->'sources') WHERE value#>>'{layer,id}'=selected->>'cost_layer_id';
  PERFORM reconforge.it1_assert(pool IS NOT NULL
   AND(pool#>'{layer,row_version}',pool#>'{layer,remaining_quantity_scaled}',pool#>'{layer,remaining_value_minor}')
    IS NOT DISTINCT FROM(selected->'row_version',selected->'remaining_quantity_scaled',selected->'remaining_value_minor')
   AND selected->'value_minor'=to_jsonb(reconforge.customer_partial_return_v2_fifo((selected->>'remaining_value_minor')::bigint,
    (selected->>'remaining_quantity_scaled')::bigint,(selected->>'quantity_scaled')::bigint)),
   'Restituted issue slices must match their exact captured native FIFO residual');
  IF selected->>'value_minor'='0' OR((selected->>'quantity_scaled')::bigint<(selected->>'remaining_quantity_scaled')::bigint
   AND selected->'value_minor'=selected->'remaining_value_minor') THEN
   needed:=TRUE;net_quantity:=0;
   FOR correction IN SELECT value FROM jsonb_array_elements(pool->'partial_return_corrections') LOOP
    IF correction->>'allocation_policy'='remaining-original-v1' THEN
     net_quantity:=net_quantity+(correction#>>'{restoration,direction}')::numeric*(correction#>>'{restoration,quantity_scaled}')::numeric;
    END IF;
   END LOOP;
   PERFORM reconforge.it1_assert(net_quantity>0,'A zero or value-exhausting slice requires active original v2 restitution in that exact layer');
  END IF;
 END LOOP;
 PERFORM reconforge.it1_assert(needed,'The versioned restituted issue is reserved for a real unsupported zero/value-exhausting original slice');
 RETURN cost;
END $cr148zs$;
CREATE FUNCTION reconforge.customer_partial_return_zero_stock_plan(t TEXT,i TEXT) RETURNS VOID
 LANGUAGE plpgsql STABLE SET search_path=pg_catalog AS $cr148zs$
DECLARE owned RECORD;issue JSONB;cost JSONB;selected JSONB;pool JSONB;correction JSONB;net_quantity NUMERIC;needed BOOLEAN:=FALSE;
BEGIN
 SELECT * INTO owned FROM reconforge.stock_sales_orders WHERE tenant_id=t AND id=i;issue:=owned.issue_plan;cost:=issue->'restitution_cost_snapshot';
 PERFORM reconforge.it1_assert(owned.id IS NOT NULL AND issue->>'schema_version'='stock-sales-issue-v2'
  AND issue->>'cost_admission_policy'='partial-return-restituted-v1' AND issue->>'source_digest'=owned.source_digest
  AND issue->>'entry_number'='SS1-'||upper(substr(reconforge.irp_digest(jsonb_build_array(t,i)),1,32))
  AND cost->>'schema_version'='inventory-transfer-cost-v3'
  AND jsonb_build_object('currency_code',cost#>>'{monetary_policy,currency_code}',
   'precision',cost#>'{monetary_policy,currency_precision}',
   'rounding_policy',cost#>>'{monetary_policy,currency_rounding_policy}',
   'registry_version',cost#>>'{monetary_policy,currency_registry_version}',
   'registry_digest',cost#>>'{monetary_policy,currency_registry_digest}')=issue->'currency_policy'
  AND jsonb_typeof(issue->'allocations')='array' AND jsonb_array_length(issue->'allocations') BETWEEN 1 AND 32
  AND NOT EXISTS(SELECT 1 FROM jsonb_array_elements(cost->'sources') captured WHERE
   (captured#>>'{layer,workspace_id}',captured#>>'{layer,legal_entity_id}',captured#>>'{layer,item_id}',captured#>>'{layer,uom_id}',
    (captured#>>'{layer,quantity_precision}')::integer) IS DISTINCT FROM
    (owned.workspace_id,owned.legal_entity_id,owned.item_id,owned.uom_id,owned.quantity_precision)),
  'Restituted issue retains its explicit complete original policy, scope and bounded native cost population');
 PERFORM reconforge.it1_cost_originals(t,cost);
 PERFORM reconforge.it1_assert(EXISTS(SELECT 1 FROM reconforge.inventory_valuation_policies policy
  JOIN reconforge.inventory_items item ON item.tenant_id=policy.tenant_id AND item.id=owned.item_id
  JOIN reconforge.finance_accounts cogs ON(cogs.tenant_id,cogs.id)=(policy.tenant_id,policy.cogs_account_id)
  JOIN reconforge.finance_accounts inventory ON(inventory.tenant_id,inventory.id)=(item.tenant_id,item.inventory_account_id)
  WHERE policy.tenant_id=t AND policy.id=issue->>'policy_id' AND(policy.workspace_id,policy.organization_id,policy.legal_entity_id,policy.currency_code)
   =(owned.workspace_id,owned.organization_id,owned.legal_entity_id,owned.currency_code)
  AND(policy.finance_journal_id,policy.cogs_account_id,item.inventory_account_id)
   =(issue->>'journal_id',issue->>'cogs_account_id',issue->>'inventory_account_id')
  AND cogs.account_type='Expense' AND inventory.account_type='Asset'),
  'Restituted issue uses original native inventory/COGS roles and valuation policy');
 FOR selected IN SELECT value FROM jsonb_array_elements(issue->'allocations') LOOP
  SELECT value INTO pool FROM jsonb_array_elements(cost->'sources') WHERE value#>>'{layer,id}'=selected->>'cost_layer_id';
  PERFORM reconforge.it1_assert(pool IS NOT NULL AND
   (pool#>'{layer,row_version}',pool#>'{layer,remaining_quantity_scaled}',pool#>'{layer,remaining_value_minor}')
    IS NOT DISTINCT FROM(selected->'row_version',selected->'remaining_quantity_scaled',selected->'remaining_value_minor'),
   'Historical restitution issue slices retain their captured native before-state');
  IF selected->>'value_minor'='0' OR((selected->>'quantity_scaled')::bigint<(selected->>'remaining_quantity_scaled')::bigint
   AND selected->'value_minor'=selected->'remaining_value_minor') THEN
   needed:=TRUE;net_quantity:=0;
   FOR correction IN SELECT value FROM jsonb_array_elements(pool->'partial_return_corrections') LOOP
    IF correction->>'allocation_policy'='remaining-original-v1' THEN
     net_quantity:=net_quantity+(correction#>>'{restoration,direction}')::numeric*(correction#>>'{restoration,quantity_scaled}')::numeric;
    END IF;
   END LOOP;
   PERFORM reconforge.it1_assert(net_quantity>0,'Historical zero slice requires its exact captured active v2 restitution');
  END IF;
 END LOOP;
 PERFORM reconforge.it1_assert(needed,'A versioned issue cannot relabel an ordinary legacy positive FIFO plan');
END $cr148zs$;
CREATE FUNCTION reconforge.customer_partial_return_zero_stock_active(t TEXT,d TEXT) RETURNS JSONB
 LANGUAGE plpgsql VOLATILE SET search_path=pg_catalog AS $cr148zs$
DECLARE owned RECORD;valuation RECORD;movement RECORD;claim RECORD;actor TEXT:=current_setting('app.stock_sales_actor_id',true);identity RECORD;
BEGIN
 SELECT * INTO valuation FROM reconforge.inventory_valuation_documents WHERE tenant_id=t AND id=d;
 SELECT * INTO movement FROM reconforge.inventory_movements WHERE tenant_id=t AND id=valuation.movement_id;
 SELECT * INTO owned FROM reconforge.stock_sales_orders WHERE tenant_id=t AND id=movement.source_reference;
 SELECT * INTO claim FROM reconforge.stock_sales_issue_claims WHERE tenant_id=t AND order_id=owned.id;
 SELECT * INTO identity FROM reconforge.identity_users WHERE tenant_id=t AND id=actor AND NOT disabled;
 PERFORM reconforge.it1_assert(owned.id IS NOT NULL AND owned.status='IssueReviewed' AND claim.state='Active'
  AND claim.payload=owned.issue_plan AND claim.plan_digest=reconforge.irp_digest(owned.issue_plan)
  AND owned.issue_plan->>'cost_admission_policy'='partial-return-restituted-v1'
  AND identity.id IS NOT NULL AND actor<>owned.issue_reviewer_id AND actor<>owned.issue_plan->>'preparer_actor_id'
  AND owned.issue_reviewer_id<>owned.issue_plan->>'preparer_actor_id'
  AND reconforge.sales_revenue_actor(t,actor,'sales.manage') AND reconforge.sales_revenue_actor(t,actor,'inventory.post')
  AND reconforge.sales_revenue_actor(t,actor,'inventory.valuation.approve') AND reconforge.sales_revenue_actor(t,actor,'finance_core.post')
  AND movement.status='Posted' AND movement.movement_type='Delivery' AND movement.source_type='Generated'
  AND movement.movement_number=owned.issue_plan->>'entry_number' AND movement.posted_by=identity.username
  AND valuation.status='Draft' AND valuation.movement_id=movement.id AND valuation.valuation_number=movement.movement_number
  AND(valuation.workspace_id,valuation.organization_id,valuation.legal_entity_id,valuation.period_id,valuation.valuation_date::text,valuation.policy_id,valuation.currency_code)
   =(owned.workspace_id,owned.organization_id,owned.legal_entity_id,owned.issue_plan#>>'{request,period_id}',
     owned.issue_plan#>>'{request,posting_date}',owned.issue_plan->>'policy_id',owned.currency_code)
  AND reconforge.sales_revenue_policy_matches(t,owned.source->'monetary_policy',valuation.currency_code,valuation.currency_precision,
    valuation.currency_rounding_policy,valuation.currency_registry_version,valuation.currency_registry_digest),
  'Zero-valued native stock requires its current exact third-human reviewed restitution issue');
 RETURN to_jsonb(owned);
END $cr148zs$;
CREATE FUNCTION reconforge.customer_partial_return_zero_stock_child() RETURNS trigger
 LANGUAGE plpgsql SET search_path=pg_catalog AS $cr148zs$
DECLARE owned JSONB;line RECORD;selected JSONB;
BEGIN
 IF NEW.value_minor<>0 THEN RETURN NEW;END IF;
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='stock_sales_owner_phase',MESSAGE='Zero stock evidence is immutable';END IF;
 IF TG_TABLE_NAME='inventory_valuation_lines' THEN
  owned:=reconforge.customer_partial_return_zero_stock_active(NEW.tenant_id,NEW.valuation_document_id);
  PERFORM reconforge.it1_assert(NEW.flow_direction='Outbound' AND NEW.inventory_lot_id IS NULL
   AND(NEW.item_id,NEW.uom_id,NEW.quantity_precision,NEW.quantity_scaled,NEW.inventory_account_id,NEW.offset_account_id)
    =(owned->>'item_id',owned->>'uom_id',(owned->>'quantity_precision')::integer,(owned->>'quantity_scaled')::bigint,
      owned#>>'{issue_plan,inventory_account_id}',owned#>>'{issue_plan,cogs_account_id}')
   AND owned#>>'{issue_plan,total_cost_minor}'='0','Zero valuation line must own the exact whole reviewed zero stock issue');
 ELSE
  SELECT * INTO line FROM reconforge.inventory_valuation_lines WHERE tenant_id=NEW.tenant_id AND id=NEW.valuation_line_id;
  owned:=reconforge.customer_partial_return_zero_stock_active(NEW.tenant_id,line.valuation_document_id);
  SELECT value INTO selected FROM jsonb_array_elements(owned#>'{issue_plan,allocations}') WHERE value->>'cost_layer_id'=NEW.cost_layer_id;
  PERFORM reconforge.it1_assert(NEW.workspace_id=owned->>'workspace_id' AND selected IS NOT NULL
   AND selected->'quantity_scaled'=to_jsonb(NEW.quantity_scaled) AND selected->'value_minor'=to_jsonb(NEW.value_minor),
   'Zero original consumption requires its exact current reviewed allocation');
 END IF;
 RETURN NEW;
END $cr148zs$;
CREATE TRIGGER customer_partial_return_zero_stock BEFORE INSERT ON reconforge.inventory_valuation_lines
 FOR EACH ROW EXECUTE FUNCTION reconforge.customer_partial_return_zero_stock_child();
CREATE TRIGGER customer_partial_return_zero_stock BEFORE INSERT ON reconforge.inventory_layer_consumptions
 FOR EACH ROW EXECUTE FUNCTION reconforge.customer_partial_return_zero_stock_child();
CREATE FUNCTION reconforge.customer_partial_return_null_origin_guard() RETURNS trigger
 LANGUAGE plpgsql SET search_path=pg_catalog AS $cr148zs$
DECLARE source_owner RECORD;owned RECORD;native RECORD;actor TEXT:=current_setting('app.customer_partial_return_actor_id',true);
BEGIN
 IF NEW.original_cogs_effect_id IS NOT NULL THEN RETURN NEW;END IF;
 SELECT * INTO source_owner FROM reconforge.customer_partial_return_sources WHERE tenant_id=NEW.tenant_id AND id=NEW.source_id;
 SELECT * INTO owned FROM reconforge.customer_partial_return_plans WHERE tenant_id=NEW.tenant_id AND id=NEW.plan_id;
 SELECT consumed.* INTO native FROM reconforge.inventory_layer_consumptions consumed
  JOIN reconforge.inventory_valuation_lines detail ON(detail.tenant_id,detail.id)=(consumed.tenant_id,consumed.valuation_line_id)
  WHERE consumed.tenant_id=NEW.tenant_id AND consumed.id=NEW.original_consumption_id
  AND detail.valuation_document_id=source_owner.original_valuation_document_id;
 PERFORM reconforge.it1_assert(TG_OP='INSERT' AND source_owner.id IS NOT NULL AND owned.id IS NOT NULL
  AND source_owner.original_cogs_effect_id IS NULL AND owned.source_id=source_owner.id AND owned.phase=1
  AND source_owner.source_payload->>'allocation_policy'='remaining-original-v1'
  AND source_owner.source_payload#>>'{fingerprint_payload,contract}'='customer-partial-return-original-v2'
  AND source_owner.source_payload#>'{typed_source,original_cogs}'='null'::jsonb
  AND source_owner.source_payload#>'{original_source,cost_admission,issue_plan,total_cost_minor}'='0'::jsonb
  AND source_owner.source_payload#>'{original_source,cost_admission}'=reconforge.customer_partial_return_zero_stock_facts(NEW.tenant_id,source_owner.source_order_id)
  AND owned.payload->>'allocation_policy'='remaining-original-v1' AND owned.operation IN('Return','ReverseReturn')
  AND owned.cogs_restored_minor=0 AND NEW.value_minor=0 AND NEW.correction_effect_id IS NULL
  AND native.id IS NOT NULL AND native.value_minor=0 AND native.cost_layer_id=NEW.cost_layer_id
  AND native.valuation_line_id=NEW.original_valuation_line_id
  AND reconforge.customer_return_authority(NEW.tenant_id,actor,'post') AND owned.preparer_actor_id<>actor
  AND EXISTS(SELECT 1 FROM reconforge.customer_partial_return_events reviewed WHERE reviewed.tenant_id=owned.tenant_id
   AND reviewed.plan_id=owned.id AND reviewed.operation='review' AND reviewed.actor_id<>actor AND reviewed.actor_id<>owned.preparer_actor_id),
  'Absent original COGS restitution requires the exact visible zero-cost factual source and current third-human owner');
 RETURN NEW;
END $cr148zs$;
CREATE TRIGGER customer_partial_return_null_origin BEFORE INSERT ON reconforge.customer_partial_return_restorations
 FOR EACH ROW EXECUTE FUNCTION reconforge.customer_partial_return_null_origin_guard();
"""


def _stock_close() -> str:
    value = ORIGINAL_FUNCTIONS["stock_sales_close"].replace("stock_sales_close(", "customer_partial_return_zero_stock_close(", 1)
    value = _replace(value, " s:=reconforge.stock_sales_stage(d.status);", " s:=reconforge.stock_sales_stage(d.status);\n PERFORM reconforge.customer_partial_return_zero_stock_plan(t,target);")
    value = _replace(value, " IF claim IS NOT NULL THEN", r""" IF s>=5 AND d.issue_reviewer_id=d.issue_plan->>'preparer_actor_id' THEN
  RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='stock_sales_owner_phase',MESSAGE='Restituted Stock issue requires its independent second human';END IF;
 IF claim IS NOT NULL THEN""")
    value = _replace(value, "d.issue_plan IS NOT NULL AND d.cogs_entry_id IS NOT NULL", "d.issue_plan IS NOT NULL AND((d.issue_plan->>'total_cost_minor'='0' AND d.cogs_entry_id IS NULL) OR((d.issue_plan->>'total_cost_minor')::bigint>0 AND d.cogs_entry_id IS NOT NULL))")
    value = _replace(value, "d.movement_id IS NOT NULL AND d.valuation_id IS NOT NULL AND d.cogs_effect_id IS NOT NULL", "d.movement_id IS NOT NULL AND d.valuation_id IS NOT NULL AND((d.issue_plan->>'total_cost_minor'='0' AND d.cogs_effect_id IS NULL) OR((d.issue_plan->>'total_cost_minor')::bigint>0 AND d.cogs_effect_id IS NOT NULL))")
    value = _replace(value, "  IF entry IS NULL OR entry.id IS DISTINCT FROM claim.entry_id", "  IF(d.issue_plan->>'total_cost_minor')::bigint>0 THEN\n  IF entry IS NULL OR entry.id IS DISTINCT FROM claim.entry_id")
    value = _replace(value, "  FOR x IN SELECT * FROM jsonb_array_elements(d.issue_plan->'allocations') LOOP", r"""  ELSE
   IF entry.id IS NOT NULL OR d.cogs_entry_id IS NOT NULL OR d.cogs_effect_id IS NOT NULL OR claim.entry_id IS NOT NULL
   OR d.issue_plan->'entry_id' IS DISTINCT FROM'null'::jsonb
   OR EXISTS(SELECT 1 FROM reconforge.finance_entries WHERE tenant_id=t AND workspace_id=d.workspace_id
    AND entry_number=d.issue_plan->>'entry_number') THEN
    RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='stock_sales_owner_phase',MESSAGE='Zero stock cost must not invent a finance entry or posting effect';END IF;
  END IF;
  FOR x IN SELECT * FROM jsonb_array_elements(d.issue_plan->'allocations') LOOP""")
    value = _replace(value, "reconforge.stock_sales_fifo_value((x->>'remaining_value_minor')::bigint,", "reconforge.customer_partial_return_v2_fifo((x->>'remaining_value_minor')::bigint,")
    value = _replace(value, "total IS DISTINCT FROM entry.total_debit_minor::numeric", "total IS DISTINCT FROM(d.issue_plan->>'total_cost_minor')::numeric")
    # The positive entry checks above remain exact. Physical zero issues bind
    # directly to the reviewed request rather than a fabricated entry record.
    value = value.replace("m.period_id=entry.period_id AND m.movement_date::text=entry.posting_date::text", "m.period_id=d.issue_plan#>>'{request,period_id}' AND m.movement_date::text=d.issue_plan#>>'{request,posting_date}'")
    value = value.replace("v.finance_entry_id=d.cogs_entry_id AND v.total_value_minor=entry.total_debit_minor", "v.finance_entry_id IS NOT DISTINCT FROM d.cogs_entry_id AND v.total_value_minor=(d.issue_plan->>'total_cost_minor')::bigint")
    value = value.replace("v.period_id=entry.period_id AND v.valuation_date::text=entry.posting_date::text", "v.period_id=d.issue_plan#>>'{request,period_id}' AND v.valuation_date::text=d.issue_plan#>>'{request,posting_date}'")
    value = _replace(value, "  OR NOT EXISTS(SELECT 1 FROM reconforge.finance_posting_effects f WHERE f.tenant_id=t AND f.id=d.cogs_effect_id", "  OR((d.issue_plan->>'total_cost_minor')::bigint>0 AND NOT EXISTS(SELECT 1 FROM reconforge.finance_posting_effects f WHERE f.tenant_id=t AND f.id=d.cogs_effect_id")
    value = _replace(value, "AND f.validation_digest=entry.validation_digest)", "AND f.validation_digest=entry.validation_digest))")
    value = _replace(value, " IF s>=6 THEN\n  IF NOT EXISTS", r""" IF s>=6 THEN
  IF NOT EXISTS(SELECT 1 FROM reconforge.stock_sales_events delivered JOIN reconforge.inventory_movements physical
   ON(physical.tenant_id,physical.id)=(delivered.tenant_id,d.movement_id)
   JOIN reconforge.identity_users identity ON(identity.tenant_id,identity.id)=(delivered.tenant_id,delivered.actor_id)
   WHERE delivered.tenant_id=t AND delivered.order_id=target AND delivered.operation='deliver'
   AND delivered.actor_id<>d.issue_reviewer_id AND delivered.actor_id<>d.issue_plan->>'preparer_actor_id'
   AND d.issue_reviewer_id<>d.issue_plan->>'preparer_actor_id' AND physical.posted_by=identity.username) THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='stock_sales_owner_phase',MESSAGE='Restituted zero stock retains its exact third-human physical poster';END IF;
  IF NOT EXISTS""")
    return value


def _dispatch() -> str:
    return _replace(ORIGINAL_FUNCTIONS["stock_sales_close"], "BEGIN\n", r"""BEGIN
 IF EXISTS(SELECT 1 FROM reconforge.stock_sales_orders owned WHERE owned.tenant_id=t AND owned.id=target
  AND owned.issue_plan ? 'cost_admission_policy') THEN
  PERFORM reconforge.customer_partial_return_zero_stock_close(t,target);RETURN;
 END IF;
""").replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1)


def _public() -> str:
    value = ORIGINAL_FUNCTIONS["stock_sales_public"].replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1)
    return _replace(value, "FROM reconforge.stock_sales_events e WHERE e.tenant_id=d.tenant_id AND e.order_id=d.id),'[]'::jsonb)) $$;",
        "FROM reconforge.stock_sales_events e WHERE e.tenant_id=d.tenant_id AND e.order_id=d.id),'[]'::jsonb))\n ||CASE WHEN d.issue_plan ? 'cost_admission_policy' THEN jsonb_build_object('cost_admission_policy',d.issue_plan->>'cost_admission_policy') ELSE '{}'::jsonb END $$;")


def _valuation_guard() -> str:
    value = ORIGINAL_FUNCTIONS["inventory_valuation_guard"]
    return _replace(value, "BEGIN\n", r"""BEGIN
 IF TG_TABLE_NAME='inventory_valuation_documents' AND TG_OP='UPDATE' AND OLD.status='Draft' AND NEW.status='Approved'
 AND NEW.total_value_minor=0 THEN
  PERFORM reconforge.customer_partial_return_zero_stock_active(NEW.tenant_id,NEW.id);
  IF NEW.finance_entry_id IS NOT NULL OR NEW.approved_by IS DISTINCT FROM(SELECT username FROM reconforge.identity_users
   WHERE tenant_id=NEW.tenant_id AND id=current_setting('app.stock_sales_actor_id',true))
  OR NEW.approved_at IS NULL OR NEW.approval_reason='' OR NEW.row_version<>OLD.row_version+1
  OR(to_jsonb(NEW)-ARRAY['status','total_value_minor','finance_entry_id','approved_by','approved_at','approval_reason','row_version'])
   IS DISTINCT FROM(to_jsonb(OLD)-ARRAY['status','total_value_minor','finance_entry_id','approved_by','approved_at','approval_reason','row_version'])
  OR(SELECT count(*) FROM reconforge.inventory_valuation_lines WHERE tenant_id=NEW.tenant_id AND valuation_document_id=NEW.id)<>1
  OR EXISTS(SELECT 1 FROM reconforge.inventory_valuation_lines detail WHERE detail.tenant_id=NEW.tenant_id AND detail.valuation_document_id=NEW.id
   AND(detail.flow_direction<>'Outbound' OR detail.value_minor<>0 OR detail.quantity_scaled<>(SELECT COALESCE(sum(quantity_scaled),0)
    FROM reconforge.inventory_layer_consumptions WHERE tenant_id=detail.tenant_id AND valuation_line_id=detail.id)
    OR EXISTS(SELECT 1 FROM reconforge.inventory_layer_consumptions WHERE tenant_id=detail.tenant_id AND valuation_line_id=detail.id AND value_minor<>0))) THEN
   RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='stock_sales_owner_phase',MESSAGE='Zero approved valuation requires its exact complete current native restitution issue';END IF;
  RETURN NEW;
 END IF;
""")


UPGRADED_FUNCTIONS = {
    "stock_sales_close": _dispatch(), "stock_sales_public": _public(), "inventory_valuation_guard": _valuation_guard(),
    "customer_partial_return_protect": _replace(ORIGINAL_FUNCTIONS["customer_partial_return_protect"],
        "reconforge.customer_partial_return_native_source(NEW.tenant_id,NEW.source_order_id)",
        "reconforge.customer_partial_return_source_dispatch(NEW.tenant_id,NEW.source_order_id)").replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1),
}

FACTS_SQL = r"""
CREATE FUNCTION reconforge.customer_partial_return_zero_stock_facts(t TEXT,i TEXT) RETURNS JSONB
 LANGUAGE plpgsql STABLE SET search_path=pg_catalog AS $cr148zs$
DECLARE owned RECORD;document RECORD;effect RECORD;details JSONB;consumptions JSONB;facts JSONB;
BEGIN
 SELECT * INTO owned FROM reconforge.stock_sales_orders WHERE tenant_id=t AND id=i;
 PERFORM reconforge.it1_assert(owned.id IS NOT NULL AND reconforge.stock_sales_stage(owned.status)>=6,
  'Factual restituted Stock source requires its actual delivered native owner');
 PERFORM reconforge.customer_partial_return_zero_stock_plan(t,i);
 SELECT * INTO document FROM reconforge.inventory_valuation_documents WHERE tenant_id=t AND id=owned.valuation_id;
 SELECT * INTO effect FROM reconforge.finance_posting_effects WHERE tenant_id=t AND id=owned.cogs_effect_id;
 SELECT COALESCE(jsonb_agg(to_jsonb(detail) ORDER BY detail.line_number,detail.id),'[]'::jsonb) INTO details
  FROM reconforge.inventory_valuation_lines detail WHERE detail.tenant_id=t AND detail.valuation_document_id=document.id;
 SELECT COALESCE(jsonb_agg(to_jsonb(consumed) ORDER BY ordinal),'[]'::jsonb) INTO consumptions
  FROM jsonb_array_elements(owned.issue_plan->'allocations') WITH ORDINALITY selected(value,ordinal)
  JOIN reconforge.inventory_layer_consumptions consumed ON consumed.tenant_id=t AND consumed.cost_layer_id=value->>'cost_layer_id'
  JOIN reconforge.inventory_valuation_lines detail ON(detail.tenant_id,detail.id)=(consumed.tenant_id,consumed.valuation_line_id)
  WHERE detail.valuation_document_id=document.id;
 PERFORM reconforge.it1_assert(document.id IS NOT NULL AND document.status='Approved' AND document.movement_id=owned.movement_id
  AND document.total_value_minor=(owned.issue_plan->>'total_cost_minor')::bigint
  AND document.finance_entry_id IS NOT DISTINCT FROM owned.cogs_entry_id
  AND jsonb_array_length(details)=1 AND details#>>'{0,flow_direction}'='Outbound'
  AND jsonb_array_length(consumptions)=jsonb_array_length(owned.issue_plan->'allocations')
  AND(SELECT sum((value->>'quantity_scaled')::numeric) FROM jsonb_array_elements(consumptions))=owned.quantity_scaled
  AND(SELECT sum((value->>'value_minor')::numeric) FROM jsonb_array_elements(consumptions))=document.total_value_minor
  AND NOT EXISTS(SELECT 1 FROM jsonb_array_elements(owned.issue_plan->'allocations') WITH ORDINALITY selected(value,ordinal)
   WHERE(value->>'cost_layer_id',value->'quantity_scaled',value->'value_minor') IS DISTINCT FROM
    (consumptions->(ordinal-1)::integer->>'cost_layer_id',consumptions->(ordinal-1)::integer->'quantity_scaled',consumptions->(ordinal-1)::integer->'value_minor'))
  AND((document.total_value_minor=0 AND owned.cogs_entry_id IS NULL AND owned.cogs_effect_id IS NULL AND effect.id IS NULL)
   OR(document.total_value_minor>0 AND effect.id IS NOT NULL AND effect.entry_id=owned.cogs_entry_id
    AND effect.snapshot_json=reconforge.fr_snapshot(t,effect.entry_id,owned.organization_id,owned.legal_entity_id))),
  'Factual zero-cost admission requires its exact approved valuation and actual-or-absent native COGS effect');
 facts:=jsonb_build_object('schema_version','stock-sales-restituted-cost-v1','stock_order_id',i,'issue_plan',owned.issue_plan,
  'valuation_document',to_jsonb(document),'valuation_lines',details,'consumptions',consumptions,
  'posting_effect',CASE WHEN effect.id IS NULL THEN NULL ELSE to_jsonb(effect) END);
 PERFORM reconforge.it1_assert(octet_length(facts::text)<=6291456,'Factual restitution source exceeds its finite retained evidence bound');
 RETURN facts;
END $cr148zs$;
CREATE FUNCTION reconforge.customer_partial_return_zero_stock_source(t TEXT,i TEXT) RETURNS JSONB
 LANGUAGE plpgsql STABLE SET search_path=pg_catalog AS $cr148zs$
DECLARE original JSONB;facts JSONB;
BEGIN
 original:=reconforge.customer_partial_return_native_source(t,i);
 IF original IS NULL OR original#>>'{stock,issue_plan,cost_admission_policy}' IS DISTINCT FROM'partial-return-restituted-v1' THEN
  RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='customer_partial_return_owner',MESSAGE='Versioned zero-cost source requires explicit original native restitution ownership';END IF;
 facts:=reconforge.customer_partial_return_zero_stock_facts(t,i);
 RETURN original||jsonb_build_object('cost_admission',facts,'consumptions',facts->'consumptions');
END $cr148zs$;
CREATE FUNCTION reconforge.customer_partial_return_source_dispatch(t TEXT,i TEXT) RETURNS JSONB
 LANGUAGE plpgsql STABLE SET search_path=pg_catalog AS $cr148zs$
BEGIN
 IF EXISTS(SELECT 1 FROM reconforge.stock_sales_orders WHERE tenant_id=t AND id=i AND issue_plan ? 'cost_admission_policy') THEN
  RETURN reconforge.customer_partial_return_zero_stock_source(t,i);END IF;
 RETURN reconforge.customer_partial_return_native_source(t,i);
END $cr148zs$;
CREATE FUNCTION reconforge.customer_partial_return_zero_consumption(t TEXT,i TEXT) RETURNS JSONB
 LANGUAGE plpgsql STABLE SET search_path=pg_catalog AS $cr148zs$
DECLARE consumed RECORD;detail RECORD;document RECORD;owned RECORD;facts JSONB;result JSONB;
BEGIN
 SELECT * INTO consumed FROM reconforge.inventory_layer_consumptions WHERE tenant_id=t AND id=i;
 SELECT * INTO detail FROM reconforge.inventory_valuation_lines WHERE tenant_id=t AND id=consumed.valuation_line_id;
 SELECT * INTO document FROM reconforge.inventory_valuation_documents WHERE tenant_id=t AND id=detail.valuation_document_id;
 SELECT stock.* INTO owned FROM reconforge.stock_sales_orders stock WHERE stock.tenant_id=t AND stock.valuation_id=document.id;
 PERFORM reconforge.it1_assert(consumed.id IS NOT NULL AND consumed.value_minor=0 AND owned.id IS NOT NULL
  AND owned.issue_plan->>'cost_admission_policy'='partial-return-restituted-v1',
  'A zero historical consumption requires its explicit actual native restituted Stock owner');
 PERFORM reconforge.customer_partial_return_zero_stock_close(t,owned.id);
 facts:=reconforge.customer_partial_return_zero_stock_facts(t,owned.id);
 PERFORM reconforge.it1_assert(EXISTS(SELECT 1 FROM jsonb_array_elements(facts->'consumptions') original WHERE original=to_jsonb(consumed)),
  'Zero consumption must belong to the exact original factual cost evidence');
 result:=jsonb_build_object('consumption_id',i,'stock_order_id',owned.id,'cost_admission_policy','partial-return-restituted-v1',
  'issue_plan',owned.issue_plan,'valuation_document',to_jsonb(document),'valuation_line',to_jsonb(detail),
  'posting_effect',facts->'posting_effect','physical',reconforge.it1_native_snapshot(t,owned.movement_id));
 PERFORM reconforge.it1_assert(octet_length(result::text)<=262144,'A zero-consumption admission exceeds its finite native evidence bound');
 RETURN result;
END $cr148zs$;
"""


def _preflight(*, upgraded_only: bool = False) -> str:
    clauses = []
    for name, original in ORIGINAL_FUNCTIONS.items():
        choices = [UPGRADED_FUNCTIONS[name]] if upgraded_only else [original, UPGRADED_FUNCTIONS[name]]
        hashes_list = []
        for value in choices:
            match = re.search(r"AS (\$[a-z0-9]*\$)(.*?)\1", value, re.S)
            if match is None:
                raise ValueError("One exact native executable body is required.")
            hashes_list.append(repr(hashlib.sha256(match[2].encode()).hexdigest()))
        hashes = ",".join(hashes_list)
        signature = "text,text" if name == "stock_sales_close" else "reconforge.stock_sales_orders" if name == "stock_sales_public" else ""
        # Trigger metadata is the original historical invoker contract, which
        # deliberately has no function-local search_path configuration.
        arguments = "ARRAY['t','target']::text[]" if name == "stock_sales_close" else "ARRAY['d']::text[]" if name == "stock_sales_public" else "NULL::text[]"
        returns = "void" if name == "stock_sales_close" else "jsonb" if name == "stock_sales_public" else "trigger"
        language = "sql" if name == "stock_sales_public" else "plpgsql"
        configuration = "IS NOT NULL" if name == "inventory_valuation_guard" else "IS DISTINCT FROM ARRAY['search_path=pg_catalog']::text[]"
        template = """ SELECT * INTO native FROM pg_proc WHERE oid=to_regprocedure('reconforge.@@NAME@@(@@SIGNATURE@@)');
 IF native.oid IS NULL OR native.prosecdef OR native.proretset OR native.proleakproof OR native.proisstrict OR native.prokind<>'f'
 OR native.prolang<>(SELECT oid FROM pg_language WHERE lanname='@@LANGUAGE@@') OR native.prorettype<>'@@RETURNS@@'::regtype
 OR native.provolatile<>'@@VOLATILITY@@' OR native.proparallel<>'u' OR native.provariadic<>0
 OR native.proargnames IS DISTINCT FROM @@ARGUMENTS@@ OR native.proargmodes IS NOT NULL OR native.pronargdefaults<>0
 OR native.proconfig @@CONFIGURATION@@ OR encode(sha256(convert_to(native.prosrc,'UTF8')),'hex') NOT IN(@@HASHES@@) THEN
 RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Original zero-stock executable metadata or body drift';END IF;"""
        for key, selected in (("NAME", name), ("SIGNATURE", signature), ("LANGUAGE", language), ("RETURNS", returns),
                              ("VOLATILITY", "s" if name == "stock_sales_public" else "v"), ("ARGUMENTS", arguments),
                              ("CONFIGURATION", configuration), ("HASHES", hashes)):
            template = template.replace("@@" + key + "@@", selected)
        clauses.append(template)
    return "DO $cr148zs$ DECLARE native RECORD;BEGIN\n" + "\n".join(clauses) + "\nEND $cr148zs$;"


UPGRADE_SQL = _preflight() + ADMISSION_SQL + _stock_close() + "\n".join(UPGRADED_FUNCTIONS.values()) + FACTS_SQL
DOWNGRADE_PREFLIGHT_SQL = r"""
DO $cr148zs$ BEGIN
 IF EXISTS(SELECT 1 FROM reconforge.stock_sales_orders WHERE issue_plan ? 'cost_admission_policy') THEN
  RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Retained restituted Stock issue prevents destructive zero-cost downgrade';END IF;
END $cr148zs$;
"""
DOWNGRADE_SQL = DOWNGRADE_PREFLIGHT_SQL + _preflight(upgraded_only=True) + "\n".join(
    value.replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1) for value in ORIGINAL_FUNCTIONS.values()) + r"""
DROP TRIGGER customer_partial_return_zero_stock ON reconforge.inventory_valuation_lines;
DROP TRIGGER customer_partial_return_zero_stock ON reconforge.inventory_layer_consumptions;
DROP TRIGGER customer_partial_return_null_origin ON reconforge.customer_partial_return_restorations;
DROP FUNCTION reconforge.customer_partial_return_null_origin_guard();
DROP FUNCTION reconforge.customer_partial_return_zero_stock_child();
DROP FUNCTION reconforge.customer_partial_return_source_dispatch(TEXT,TEXT);
DROP FUNCTION reconforge.customer_partial_return_zero_consumption(TEXT,TEXT);
DROP FUNCTION reconforge.customer_partial_return_zero_stock_source(TEXT,TEXT);
DROP FUNCTION reconforge.customer_partial_return_zero_stock_facts(TEXT,TEXT);
DROP FUNCTION reconforge.customer_partial_return_zero_stock_active(TEXT,TEXT);
DROP FUNCTION reconforge.customer_partial_return_zero_stock_cost(TEXT,TEXT,TEXT,TEXT,TEXT,JSONB);
DROP FUNCTION reconforge.customer_partial_return_zero_stock_close(TEXT,TEXT);
DROP FUNCTION reconforge.customer_partial_return_zero_stock_plan(TEXT,TEXT);
"""


def _helpers_preflight() -> str:
    statements = re.findall(r"CREATE(?: OR REPLACE)? FUNCTION reconforge\.([a-z0-9_]+)\(([^)]*)\)\s+RETURNS ([A-Za-z]+)\s+"
        r"LANGUAGE (plpgsql|sql)([^$]+)AS (\$[a-z0-9]*\$)(.*?)\6;", UPGRADE_SQL, re.S)
    clauses = []
    for name, arguments, returns, language, attributes, _delimiter, body in statements:
        if name in ORIGINAL_FUNCTIONS:
            continue
        pairs = [argument.strip().split() for argument in arguments.split(",")] if arguments.strip() else []
        signature = ",".join(pair[1].lower() for pair in pairs)
        names = "ARRAY[" + ",".join(repr(pair[0]) for pair in pairs) + "]::text[]" if pairs else "NULL::text[]"
        template = """ SELECT * INTO native FROM pg_proc WHERE oid=to_regprocedure('reconforge.@@NAME@@(@@SIGNATURE@@)');
 IF native.oid IS NULL OR native.prosecdef OR native.proretset OR native.proleakproof OR native.proisstrict OR native.prokind<>'f'
 OR native.prolang<>(SELECT oid FROM pg_language WHERE lanname='@@LANGUAGE@@') OR native.prorettype<>'@@RETURNS@@'::regtype
 OR native.provolatile<>'@@VOLATILITY@@' OR native.proparallel<>'u' OR native.provariadic<>0
 OR native.proargnames IS DISTINCT FROM @@ARGUMENTS@@ OR native.proargmodes IS NOT NULL OR native.pronargdefaults<>0
 OR native.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog']::text[]
 OR encode(sha256(convert_to(native.prosrc,'UTF8')),'hex')<>'@@HASH@@' THEN
 RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Versioned zero-stock native helper drift';END IF;"""
        for key, selected in (("NAME", name), ("SIGNATURE", signature), ("LANGUAGE", language), ("RETURNS", returns.lower()),
                              ("VOLATILITY", "s" if "STABLE" in attributes else "v"), ("ARGUMENTS", names),
                              ("HASH", hashlib.sha256(body.encode()).hexdigest())):
            template = template.replace("@@" + key + "@@", selected)
        clauses.append(template)
    if len(clauses) != 10:
        raise ValueError("The finite zero-stock native helper membership differs.")
    return "DO $cr148zs$ DECLARE native RECORD;BEGIN\n" + "\n".join(clauses) + "\nEND $cr148zs$;"


def verify_zero_stock_functions(connection: Any) -> None:
    if not records(connection.execute("SELECT to_regprocedure('reconforge.customer_partial_return_zero_stock_plan(text,text)') present"))[0]["present"]:
        raise ValueError("The complete versioned zero-stock native contract is required.")
    connection.execute(_preflight(upgraded_only=True))
    connection.execute(_helpers_preflight())
