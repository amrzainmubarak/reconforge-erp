"""Additive native inventory hierarchy restrictions; no retained row rewrites.

The policy graph runs only from child to native parent. Stable invoker boundaries
retain the caller's ACL, FORCE RLS and statement snapshot. An unbound tenant keeps
the original inventory contract; scoped legacy rows require an actual hierarchy.
PUBLIC execution retains the existing boolean-helper convention: every helper
checks the exact current tenant, exposes no rows, and changes no context or data.
"""
from __future__ import annotations

from typing import Any

INVENTORY_SCOPE_TABLES = (
    "inventory_movements",
    "inventory_movement_lines",
    "inventory_valuation_documents",
    "inventory_valuation_input_costs",
    "inventory_valuation_lines",
    "inventory_cost_layers",
    "inventory_layer_consumptions",
    "inventory_valuation_reversals",
    "inventory_valuation_reversal_effects",
)
INVENTORY_SCOPE_FUNCTION_SIGNATURES = (
    "inventory_scope_unbound(TEXT)", "inventory_scope_header(TEXT,TEXT,TEXT,TEXT)",
    "inventory_scope_location(TEXT,TEXT,TEXT,TEXT,TEXT)", "inventory_scope_movement_line(TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT)",
    "inventory_scope_valuation(TEXT,TEXT,TEXT,TEXT,TEXT)", "inventory_scope_valuation_line(TEXT,TEXT,TEXT)",
    "inventory_scope_layer(TEXT,TEXT,TEXT,TEXT)", "inventory_scope_consumption(TEXT,TEXT,TEXT,TEXT)",
    "inventory_scope_reversal(TEXT,TEXT,TEXT,TEXT,TEXT,TEXT)", "inventory_scope_reversal_effect(TEXT,TEXT,TEXT,TEXT,TEXT)",
)

UPGRADE_SQL = r"""
CREATE FUNCTION reconforge.inventory_scope_unbound(t TEXT) RETURNS BOOLEAN
 LANGUAGE sql STABLE SECURITY INVOKER SET search_path=pg_catalog AS $inv$
 SELECT COALESCE(t=current_setting('app.tenant_id',true),FALSE)
 AND NULLIF(current_setting('app.workspace_id',true),'') IS NULL
 AND NULLIF(current_setting('app.organization_id',true),'') IS NULL
 AND NULLIF(current_setting('app.legal_entity_id',true),'') IS NULL
 AND NULLIF(current_setting('app.entity_id',true),'') IS NULL
$inv$;
CREATE FUNCTION reconforge.inventory_scope_header(t TEXT,w TEXT,o TEXT,e TEXT) RETURNS BOOLEAN
 LANGUAGE plpgsql STABLE SECURITY INVOKER SET search_path=pg_catalog AS $inv$
DECLARE cw TEXT:=NULLIF(current_setting('app.workspace_id',true),'');
 co TEXT:=NULLIF(current_setting('app.organization_id',true),'');
 ce TEXT:=NULLIF(current_setting('app.legal_entity_id',true),'');
 alias_entity TEXT:=NULLIF(current_setting('app.entity_id',true),'');
BEGIN
 IF t IS NULL OR t IS DISTINCT FROM current_setting('app.tenant_id',true) THEN RETURN FALSE;END IF;
 IF reconforge.inventory_scope_unbound(t) THEN RETURN TRUE;END IF;
 IF ce IS DISTINCT FROM alias_entity OR (ce IS NOT NULL AND co IS NULL)
 OR (cw IS NOT NULL AND cw IS DISTINCT FROM w) OR (co IS NOT NULL AND co IS DISTINCT FROM o)
 OR (ce IS NOT NULL AND ce IS DISTINCT FROM e) THEN RETURN FALSE;END IF;
 RETURN EXISTS(SELECT 1 FROM reconforge.organizations org JOIN reconforge.legal_entities entity
 ON entity.tenant_id=org.tenant_id AND entity.organization_id=org.id
 WHERE org.tenant_id=t AND org.id=o AND org.application_workspace_id=w AND entity.id=e);
END $inv$;
CREATE FUNCTION reconforge.inventory_scope_location(t TEXT,i TEXT,w TEXT,o TEXT,e TEXT) RETURNS BOOLEAN
 LANGUAGE plpgsql STABLE SECURITY INVOKER SET search_path=pg_catalog AS $inv$
BEGIN
 IF t IS NULL OR t IS DISTINCT FROM current_setting('app.tenant_id',true) THEN RETURN FALSE;END IF;
 IF i IS NULL THEN RETURN TRUE;END IF;
 RETURN EXISTS(SELECT 1 FROM reconforge.inventory_locations location JOIN reconforge.inventory_warehouses warehouse
 ON warehouse.tenant_id=location.tenant_id AND warehouse.id=location.warehouse_id
 WHERE location.tenant_id=t AND location.id=i AND warehouse.workspace_id=w AND warehouse.organization_id=o
 AND (warehouse.legal_entity_id IS NULL OR warehouse.legal_entity_id=e)
 AND reconforge.inventory_scope_header(t,warehouse.workspace_id,warehouse.organization_id,e));
END $inv$;
CREATE FUNCTION reconforge.inventory_scope_movement_line(t TEXT,i TEXT,f TEXT,d TEXT,item TEXT,uom TEXT,lot TEXT) RETURNS BOOLEAN
 LANGUAGE plpgsql STABLE SECURITY INVOKER SET search_path=pg_catalog AS $inv$
BEGIN
 IF t IS NULL OR t IS DISTINCT FROM current_setting('app.tenant_id',true) THEN RETURN FALSE;END IF;
 IF reconforge.inventory_scope_unbound(t) THEN RETURN TRUE;END IF;
 RETURN EXISTS(SELECT 1 FROM reconforge.inventory_movements movement WHERE movement.tenant_id=t AND movement.id=i
 AND reconforge.inventory_scope_location(t,f,movement.workspace_id,movement.organization_id,movement.legal_entity_id)
 AND reconforge.inventory_scope_location(t,d,movement.workspace_id,movement.organization_id,movement.legal_entity_id)
 AND EXISTS(SELECT 1 FROM reconforge.inventory_items reference_item
 WHERE reference_item.tenant_id=t AND reference_item.id=item AND reference_item.workspace_id=movement.workspace_id
 AND (reference_item.organization_id IS NULL OR reference_item.organization_id=movement.organization_id))
 AND EXISTS(SELECT 1 FROM reconforge.inventory_units_of_measure reference_uom
 WHERE reference_uom.tenant_id=t AND reference_uom.id=uom AND reference_uom.workspace_id=movement.workspace_id)
 AND (lot IS NULL OR EXISTS(SELECT 1 FROM reconforge.inventory_lots reference_lot
 WHERE reference_lot.tenant_id=t AND reference_lot.id=lot AND reference_lot.item_id=item
 AND reference_lot.workspace_id=movement.workspace_id AND reference_lot.organization_id=movement.organization_id)));
END $inv$;
CREATE FUNCTION reconforge.inventory_scope_valuation(t TEXT,w TEXT,o TEXT,e TEXT,m TEXT) RETURNS BOOLEAN
 LANGUAGE plpgsql STABLE SECURITY INVOKER SET search_path=pg_catalog AS $inv$
BEGIN
 IF t IS NULL OR t IS DISTINCT FROM current_setting('app.tenant_id',true) THEN RETURN FALSE;END IF;
 IF reconforge.inventory_scope_unbound(t) THEN RETURN TRUE;END IF;
 RETURN reconforge.inventory_scope_header(t,w,o,e) AND EXISTS(SELECT 1 FROM reconforge.inventory_movements movement
 WHERE movement.tenant_id=t AND movement.id=m
 AND (movement.workspace_id,movement.organization_id,movement.legal_entity_id)=(w,o,e));
END $inv$;
CREATE FUNCTION reconforge.inventory_scope_valuation_line(t TEXT,d TEXT,m TEXT) RETURNS BOOLEAN
 LANGUAGE plpgsql STABLE SECURITY INVOKER SET search_path=pg_catalog AS $inv$
BEGIN
 IF t IS NULL OR t IS DISTINCT FROM current_setting('app.tenant_id',true) THEN RETURN FALSE;END IF;
 IF reconforge.inventory_scope_unbound(t) THEN RETURN TRUE;END IF;
 RETURN EXISTS(SELECT 1 FROM reconforge.inventory_valuation_documents document JOIN reconforge.inventory_movement_lines line
 ON line.tenant_id=document.tenant_id AND line.movement_id=document.movement_id
 WHERE document.tenant_id=t AND document.id=d AND line.id=m);
END $inv$;
CREATE FUNCTION reconforge.inventory_scope_layer(t TEXT,w TEXT,e TEXT,v TEXT) RETURNS BOOLEAN
 LANGUAGE plpgsql STABLE SECURITY INVOKER SET search_path=pg_catalog AS $inv$
BEGIN
 IF t IS NULL OR t IS DISTINCT FROM current_setting('app.tenant_id',true) THEN RETURN FALSE;END IF;
 IF reconforge.inventory_scope_unbound(t) THEN RETURN TRUE;END IF;
 RETURN EXISTS(SELECT 1 FROM reconforge.inventory_valuation_lines line JOIN reconforge.inventory_valuation_documents document
 ON document.tenant_id=line.tenant_id AND document.id=line.valuation_document_id
 WHERE line.tenant_id=t AND line.id=v AND line.flow_direction='Inbound'
 AND document.workspace_id=w AND document.legal_entity_id=e);
END $inv$;
CREATE FUNCTION reconforge.inventory_scope_consumption(t TEXT,w TEXT,v TEXT,l TEXT) RETURNS BOOLEAN
 LANGUAGE plpgsql STABLE SECURITY INVOKER SET search_path=pg_catalog AS $inv$
BEGIN
 IF t IS NULL OR t IS DISTINCT FROM current_setting('app.tenant_id',true) THEN RETURN FALSE;END IF;
 IF reconforge.inventory_scope_unbound(t) THEN RETURN TRUE;END IF;
 RETURN EXISTS(SELECT 1 FROM reconforge.inventory_valuation_lines line JOIN reconforge.inventory_valuation_documents document
 ON document.tenant_id=line.tenant_id AND document.id=line.valuation_document_id
 JOIN reconforge.inventory_cost_layers layer ON layer.tenant_id=line.tenant_id AND layer.id=l
 WHERE line.tenant_id=t AND line.id=v AND line.flow_direction='Outbound'
 AND document.workspace_id=w AND layer.workspace_id=w AND layer.legal_entity_id=document.legal_entity_id);
END $inv$;
CREATE FUNCTION reconforge.inventory_scope_reversal(t TEXT,w TEXT,o TEXT,e TEXT,d TEXT,m TEXT) RETURNS BOOLEAN
 LANGUAGE plpgsql STABLE SECURITY INVOKER SET search_path=pg_catalog AS $inv$
BEGIN
 IF t IS NULL OR t IS DISTINCT FROM current_setting('app.tenant_id',true) THEN RETURN FALSE;END IF;
 IF reconforge.inventory_scope_unbound(t) THEN RETURN TRUE;END IF;
 RETURN reconforge.inventory_scope_valuation(t,w,o,e,m) AND EXISTS(SELECT 1 FROM reconforge.inventory_valuation_documents document
 WHERE document.tenant_id=t AND document.id=d
 AND (document.workspace_id,document.organization_id,document.legal_entity_id)=(w,o,e));
END $inv$;
CREATE FUNCTION reconforge.inventory_scope_reversal_effect(t TEXT,r TEXT,v TEXT,c TEXT,l TEXT) RETURNS BOOLEAN
 LANGUAGE plpgsql STABLE SECURITY INVOKER SET search_path=pg_catalog AS $inv$
BEGIN
 IF t IS NULL OR t IS DISTINCT FROM current_setting('app.tenant_id',true) THEN RETURN FALSE;END IF;
 IF reconforge.inventory_scope_unbound(t) THEN RETURN TRUE;END IF;
 RETURN EXISTS(SELECT 1 FROM reconforge.inventory_valuation_reversals reversal JOIN reconforge.inventory_valuation_lines line
 ON line.tenant_id=reversal.tenant_id AND line.valuation_document_id=reversal.original_valuation_document_id
 JOIN reconforge.inventory_cost_layers layer ON layer.tenant_id=reversal.tenant_id AND layer.id=l
 WHERE reversal.tenant_id=t AND reversal.id=r AND line.id=v
 AND layer.workspace_id=reversal.workspace_id AND layer.legal_entity_id=reversal.legal_entity_id
 AND ((c IS NULL AND layer.source_valuation_line_id=v) OR EXISTS(SELECT 1 FROM reconforge.inventory_layer_consumptions consumption
 WHERE consumption.tenant_id=t AND consumption.id=c AND consumption.valuation_line_id=v AND consumption.cost_layer_id=l)));
END $inv$;

ALTER TABLE reconforge.inventory_movements ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.inventory_movements FORCE ROW LEVEL SECURITY;
CREATE POLICY inventory_hierarchy ON reconforge.inventory_movements AS RESTRICTIVE
 USING(reconforge.inventory_scope_header(tenant_id,workspace_id,organization_id,legal_entity_id))
 WITH CHECK(reconforge.inventory_scope_header(tenant_id,workspace_id,organization_id,legal_entity_id));
ALTER TABLE reconforge.inventory_movement_lines ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.inventory_movement_lines FORCE ROW LEVEL SECURITY;
CREATE POLICY inventory_hierarchy ON reconforge.inventory_movement_lines AS RESTRICTIVE
 USING(reconforge.inventory_scope_movement_line(tenant_id,movement_id,from_location_id,to_location_id,item_id,uom_id,inventory_lot_id))
 WITH CHECK(reconforge.inventory_scope_movement_line(tenant_id,movement_id,from_location_id,to_location_id,item_id,uom_id,inventory_lot_id));
ALTER TABLE reconforge.inventory_valuation_documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.inventory_valuation_documents FORCE ROW LEVEL SECURITY;
CREATE POLICY inventory_hierarchy ON reconforge.inventory_valuation_documents AS RESTRICTIVE
 USING(reconforge.inventory_scope_valuation(tenant_id,workspace_id,organization_id,legal_entity_id,movement_id))
 WITH CHECK(reconforge.inventory_scope_valuation(tenant_id,workspace_id,organization_id,legal_entity_id,movement_id));
ALTER TABLE reconforge.inventory_valuation_input_costs ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.inventory_valuation_input_costs FORCE ROW LEVEL SECURITY;
CREATE POLICY inventory_hierarchy ON reconforge.inventory_valuation_input_costs AS RESTRICTIVE
 USING(reconforge.inventory_scope_valuation_line(tenant_id,valuation_document_id,movement_line_id))
 WITH CHECK(reconforge.inventory_scope_valuation_line(tenant_id,valuation_document_id,movement_line_id));
ALTER TABLE reconforge.inventory_valuation_lines ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.inventory_valuation_lines FORCE ROW LEVEL SECURITY;
CREATE POLICY inventory_hierarchy ON reconforge.inventory_valuation_lines AS RESTRICTIVE
 USING(reconforge.inventory_scope_valuation_line(tenant_id,valuation_document_id,movement_line_id))
 WITH CHECK(reconforge.inventory_scope_valuation_line(tenant_id,valuation_document_id,movement_line_id));
ALTER TABLE reconforge.inventory_cost_layers ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.inventory_cost_layers FORCE ROW LEVEL SECURITY;
CREATE POLICY inventory_hierarchy ON reconforge.inventory_cost_layers AS RESTRICTIVE
 USING(reconforge.inventory_scope_layer(tenant_id,workspace_id,legal_entity_id,source_valuation_line_id))
 WITH CHECK(reconforge.inventory_scope_layer(tenant_id,workspace_id,legal_entity_id,source_valuation_line_id));
ALTER TABLE reconforge.inventory_layer_consumptions ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.inventory_layer_consumptions FORCE ROW LEVEL SECURITY;
CREATE POLICY inventory_hierarchy ON reconforge.inventory_layer_consumptions AS RESTRICTIVE
 USING(reconforge.inventory_scope_consumption(tenant_id,workspace_id,valuation_line_id,cost_layer_id))
 WITH CHECK(reconforge.inventory_scope_consumption(tenant_id,workspace_id,valuation_line_id,cost_layer_id));
ALTER TABLE reconforge.inventory_valuation_reversals ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.inventory_valuation_reversals FORCE ROW LEVEL SECURITY;
CREATE POLICY inventory_hierarchy ON reconforge.inventory_valuation_reversals AS RESTRICTIVE
 USING(reconforge.inventory_scope_reversal(tenant_id,workspace_id,organization_id,legal_entity_id,original_valuation_document_id,reversal_movement_id))
 WITH CHECK(reconforge.inventory_scope_reversal(tenant_id,workspace_id,organization_id,legal_entity_id,original_valuation_document_id,reversal_movement_id));
ALTER TABLE reconforge.inventory_valuation_reversal_effects ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.inventory_valuation_reversal_effects FORCE ROW LEVEL SECURITY;
CREATE POLICY inventory_hierarchy ON reconforge.inventory_valuation_reversal_effects AS RESTRICTIVE
 USING(reconforge.inventory_scope_reversal_effect(tenant_id,reversal_id,original_valuation_line_id,original_consumption_id,cost_layer_id))
 WITH CHECK(reconforge.inventory_scope_reversal_effect(tenant_id,reversal_id,original_valuation_line_id,original_consumption_id,cost_layer_id));
"""

DOWNGRADE_SQL = r"""
DROP POLICY inventory_hierarchy ON reconforge.inventory_valuation_reversal_effects;
DROP POLICY inventory_hierarchy ON reconforge.inventory_valuation_reversals;
DROP POLICY inventory_hierarchy ON reconforge.inventory_layer_consumptions;
DROP POLICY inventory_hierarchy ON reconforge.inventory_cost_layers;
DROP POLICY inventory_hierarchy ON reconforge.inventory_valuation_lines;
DROP POLICY inventory_hierarchy ON reconforge.inventory_valuation_input_costs;
DROP POLICY inventory_hierarchy ON reconforge.inventory_valuation_documents;
DROP POLICY inventory_hierarchy ON reconforge.inventory_movement_lines;
DROP POLICY inventory_hierarchy ON reconforge.inventory_movements;
DROP FUNCTION reconforge.inventory_scope_reversal_effect(TEXT,TEXT,TEXT,TEXT,TEXT);
DROP FUNCTION reconforge.inventory_scope_reversal(TEXT,TEXT,TEXT,TEXT,TEXT,TEXT);
DROP FUNCTION reconforge.inventory_scope_consumption(TEXT,TEXT,TEXT,TEXT);
DROP FUNCTION reconforge.inventory_scope_layer(TEXT,TEXT,TEXT,TEXT);
DROP FUNCTION reconforge.inventory_scope_valuation_line(TEXT,TEXT,TEXT);
DROP FUNCTION reconforge.inventory_scope_valuation(TEXT,TEXT,TEXT,TEXT,TEXT);
DROP FUNCTION reconforge.inventory_scope_movement_line(TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT);
DROP FUNCTION reconforge.inventory_scope_location(TEXT,TEXT,TEXT,TEXT,TEXT);
DROP FUNCTION reconforge.inventory_scope_header(TEXT,TEXT,TEXT,TEXT);
DROP FUNCTION reconforge.inventory_scope_unbound(TEXT);
"""


def install_postgres_inventory_scope(connection: Any) -> None:
    connection.execute(UPGRADE_SQL)
