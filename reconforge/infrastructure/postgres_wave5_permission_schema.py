"""Additive permission catalogs without implicit grants to existing roles."""

from __future__ import annotations

_CATALOGS = {
    "manufacturing_execution": ("read", "manage", "approve", "post"),
    "intercompany_operations": ("read", "prepare", "review", "post"),
    "procurement_sourcing": ("read", "manage", "approve", "award"),
}


def permission_upgrade_sql(module: str) -> str:
    """Use only an internal fixed catalog; no caller-controlled SQL identifier."""
    actions = _CATALOGS[module]
    values = ",".join(f"('{module}.{action}','Governed {module} {action}')" for action in actions)
    return f"""
INSERT INTO reconforge.identity_permissions(tenant_id,name,description)
 SELECT t.id,p.name,p.description FROM reconforge.tenants t
 CROSS JOIN (VALUES {values}) p(name,description) ON CONFLICT DO NOTHING;
CREATE FUNCTION reconforge.seed_{module}_permissions() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 INSERT INTO reconforge.identity_permissions(tenant_id,name,description)
 SELECT NEW.id,p.name,p.description FROM (VALUES {values}) p(name,description)
 ON CONFLICT DO NOTHING;
 RETURN NEW;
END $$;
CREATE TRIGGER {module}_permission_tenant_seed AFTER INSERT ON reconforge.tenants
 FOR EACH ROW EXECUTE FUNCTION reconforge.seed_{module}_permissions();
"""


def permission_downgrade_sql(module: str) -> str:
    names = ",".join(f"'{module}.{action}'" for action in _CATALOGS[module])
    return f"""
DO $permission$ BEGIN
 IF EXISTS(SELECT 1 FROM reconforge.identity_role_permissions WHERE permission_name IN ({names}))
 OR EXISTS(SELECT 1 FROM reconforge.identity_role_permission_scopes WHERE permission_name IN ({names})) THEN
  RAISE EXCEPTION USING ERRCODE='23514',
   MESSAGE='Retained permission grants prevent downgrade; restore a verified pre-upgrade backup.';
 END IF;
END $permission$;
DROP TRIGGER {module}_permission_tenant_seed ON reconforge.tenants;
DROP FUNCTION reconforge.seed_{module}_permissions();
DELETE FROM reconforge.identity_permissions WHERE name IN ({names});
"""
