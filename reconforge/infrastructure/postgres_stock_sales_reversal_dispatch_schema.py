"""Scope retained stock-sale revenue inverse dispatch to its native original.

The published customer-return migration remains frozen. This additive correction
changes only owner discovery; the existing exact source/inverse closure remains
the authority for every dispatched stock sale.
"""

_PATCH_DECLARATIONS = r"""
DO $stock_dispatch$
DECLARE definition TEXT;
 obsolete TEXT := $obsolete$ OR EXISTS(SELECT 1 FROM reconforge.operational_finance_links l WHERE l.tenant_id=d.tenant_id AND l.plan_id=d.invoice_plan_id AND l.posting_effect_id=reverse_effect)$obsolete$;
 owner_anchor TEXT := $owner$FOR owner IN SELECT d.id FROM reconforge.stock_sales_orders d WHERE d.tenant_id=changed->>'tenant_id'$owner$;
 cogs_anchor TEXT := 'OR d.cogs_effect_id=reverse_effect';
 native_route TEXT := $route$IF reverse_effect IS NOT NULL THEN
     SELECT original_entry.external_reference INTO plan
     FROM reconforge.finance_posting_effects original_effect
     JOIN reconforge.finance_entries original_entry
      ON original_entry.tenant_id=original_effect.tenant_id AND original_entry.id=original_effect.entry_id
     WHERE original_effect.tenant_id=changed->>'tenant_id' AND original_effect.id=reverse_effect
      AND original_entry.external_reference ~ '^OPS1-[a-f0-9]{32}$'
      AND original_entry.entry_number=upper(original_entry.external_reference);
    END IF;
    $route$;
BEGIN
 definition:=pg_get_functiondef('reconforge.stock_sales_native_close()'::regprocedure);
"""

_UPGRADE_BODY = r"""
 IF length(definition)-length(replace(definition,obsolete,''))<>length(obsolete)
 OR length(definition)-length(replace(definition,owner_anchor,''))<>length(owner_anchor)
 OR length(definition)-length(replace(definition,cogs_anchor,''))<>length(cogs_anchor)
 OR position(native_route IN definition)<>0 THEN
  RAISE EXCEPTION 'Retained stock-sale original inverse dispatch differs';
 END IF;
 definition:=replace(definition,obsolete,'');
 definition:=replace(definition,owner_anchor,native_route||owner_anchor);
 EXECUTE definition;
END $stock_dispatch$;
"""

_DOWNGRADE_BODY = r"""
 IF length(definition)-length(replace(definition,native_route,''))<>length(native_route)
 OR length(definition)-length(replace(definition,owner_anchor,''))<>length(owner_anchor)
 OR length(definition)-length(replace(definition,cogs_anchor,''))<>length(cogs_anchor)
 OR position(obsolete IN definition)<>0 THEN
  RAISE EXCEPTION 'Corrected stock-sale original inverse dispatch differs';
 END IF;
 definition:=replace(definition,native_route||owner_anchor,owner_anchor);
 definition:=replace(definition,cogs_anchor,cogs_anchor||obsolete);
 EXECUTE definition;
END $stock_dispatch$;
"""

UPGRADE_SQL = _PATCH_DECLARATIONS + _UPGRADE_BODY
DOWNGRADE_SQL = _PATCH_DECLARATIONS + _DOWNGRADE_BODY
