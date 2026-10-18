"""Coordinate accepted Inventory Core hierarchies without changing owner custody.

Only the generic pool/version gate accepts the existing tenant-unbound Core
contract and authoritative workspace-organization associations. MSP source
birth, directory RLS, exact source claims and structural interpretation pins
retain their stricter native financial hierarchy requirements.
"""

import re

from reconforge.infrastructure.postgres_inventory_quantity_source_ownership import UPGRADE_SQL as ORIGINAL_SQL


def _original_function(name: str) -> str:
    match = re.search(r"CREATE FUNCTION reconforge\." + re.escape(name) +
        r"\(.*?END \$quantity\$;", ORIGINAL_SQL, re.S)
    if match is None:
        raise RuntimeError("Original native quantity function contract is absent: " + name)
    return match.group().replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1)


def _compatible_function(name: str) -> str:
    original = _original_function(name)
    predicate = "WHERE o.tenant_id=t AND o.application_workspace_id=w AND entity.id=e;"
    if original.count(predicate) != 1 or original.count("reconforge.irp_scope(t,w,org,e)") != 1:
        raise RuntimeError("Original quantity hierarchy contract changed: " + name)
    return original.replace(predicate,
        "WHERE o.tenant_id=t AND entity.id=e AND(o.application_workspace_id=w OR EXISTS("
        "SELECT 1 FROM reconforge.master_data_workspace_organizations membership "
        "WHERE membership.tenant_id=t AND membership.workspace_id=w AND membership.organization_id=o.id));"
    ).replace("reconforge.irp_scope(t,w,org,e)", "reconforge.inventory_quantity_coordination_scope(t,w,org,e)")


FUNCTIONS = ("inventory_quantity_source_pool_lock", "touch_inventory_quantity_claim_gate")
UPGRADE_SQL = "\n".join((r"""
CREATE FUNCTION reconforge.inventory_quantity_coordination_scope(t TEXT,w TEXT,o TEXT,e TEXT)
 RETURNS BOOLEAN LANGUAGE SQL STABLE SECURITY INVOKER SET search_path=pg_catalog AS $quantity$
 SELECT reconforge.inventory_scope_header(t,w,o,e) AND EXISTS(
 SELECT 1 FROM reconforge.organizations org JOIN reconforge.legal_entities entity
 ON entity.tenant_id=org.tenant_id AND entity.organization_id=org.id
 WHERE org.tenant_id=t AND org.id=o AND entity.id=e
 AND(org.application_workspace_id=w OR EXISTS(
 SELECT 1 FROM reconforge.master_data_workspace_organizations membership
 WHERE membership.tenant_id=t AND membership.workspace_id=w AND membership.organization_id=o)));
 $quantity$;
""", *(_compatible_function(name) for name in FUNCTIONS), r"""
ALTER POLICY inventory_quantity_scope ON reconforge.inventory_quantity_claim_gates
 USING(reconforge.inventory_quantity_coordination_scope(tenant_id,workspace_id,organization_id,legal_entity_id))
 WITH CHECK(reconforge.inventory_quantity_coordination_scope(tenant_id,workspace_id,organization_id,legal_entity_id));
"""))
DOWNGRADE_SQL = "\n".join((r"""
DO $quantity$ BEGIN
 IF EXISTS(SELECT 1 FROM reconforge.inventory_quantity_claim_gates gate
 JOIN reconforge.organizations org ON org.tenant_id=gate.tenant_id AND org.id=gate.organization_id
 WHERE org.application_workspace_id IS DISTINCT FROM gate.workspace_id) THEN
 RAISE EXCEPTION USING ERRCODE='23514',
 MESSAGE='Legacy inventory coordination requires compatible contracts or restore';END IF;
END $quantity$;
""", *(_original_function(name) for name in FUNCTIONS), r"""
ALTER POLICY inventory_quantity_scope ON reconforge.inventory_quantity_claim_gates
 USING(reconforge.irp_scope(tenant_id,workspace_id,organization_id,legal_entity_id))
 WITH CHECK(reconforge.irp_scope(tenant_id,workspace_id,organization_id,legal_entity_id));
DROP FUNCTION reconforge.inventory_quantity_coordination_scope(TEXT,TEXT,TEXT,TEXT);
"""))
