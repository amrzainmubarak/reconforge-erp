"""Additive permission catalogs without implicit grants to existing roles."""

from __future__ import annotations

_CATALOGS = {
    "manufacturing_execution": ("read", "manage", "approve", "post"),
    "intercompany_operations": ("read", "prepare", "review", "post"),
    "procurement_sourcing": ("read", "manage", "approve", "award"),
    "manufacturing_execution_v2": ("read", "manage", "approve", "post"),
    "intercompany_fx": ("read", "prepare", "review", "post"),
    "accrual_deferral": ("read", "prepare", "review", "post"),
    "manufacturing_supply_plan": ("read", "manage", "approve", "post"),
    "project_time_billing": ("read", "manage", "approve_price", "prepare", "collect", "review", "post"),
    "people_project_payroll": (
        "read", "read_sensitive", "personnel", "manage", "approve_time", "prepare", "review", "post", "pay",
    ),
}


def permission_upgrade_sql(module: str) -> str:
    """Use only an internal fixed catalog; no caller-controlled SQL identifier."""
    actions = _CATALOGS[module]
    from psycopg import sql

    values = sql.SQL(",").join(
        sql.SQL("({},{})").format(sql.Literal(f"{module}.{action}"), sql.Literal(f"Governed {module} {action}"))
        for action in actions
    )
    return sql.SQL("""
INSERT INTO reconforge.identity_permissions(tenant_id,name,description)
 SELECT t.id,p.name,p.description FROM reconforge.tenants t
 CROSS JOIN (VALUES {values}) p(name,description) ON CONFLICT DO NOTHING;
CREATE FUNCTION {seed}() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 INSERT INTO reconforge.identity_permissions(tenant_id,name,description)
 SELECT NEW.id,p.name,p.description FROM (VALUES {values}) p(name,description)
 ON CONFLICT DO NOTHING;
 RETURN NEW;
END $$;
CREATE TRIGGER {trigger} AFTER INSERT ON reconforge.tenants
 FOR EACH ROW EXECUTE FUNCTION {seed}();
""").format(values=values, seed=sql.Identifier("reconforge", f"seed_{module}_permissions"),
             trigger=sql.Identifier(f"{module}_permission_tenant_seed")).as_string()


def permission_downgrade_sql(module: str) -> str:
    actions = _CATALOGS[module]
    from psycopg import sql

    names = sql.SQL(",").join(sql.Literal(f"{module}.{action}") for action in actions)
    return sql.SQL("""
DO $permission$ BEGIN
 IF EXISTS(SELECT 1 FROM reconforge.identity_role_permissions WHERE permission_name IN ({names}))
 OR EXISTS(SELECT 1 FROM reconforge.identity_role_permission_scopes WHERE permission_name IN ({names})) THEN
  RAISE EXCEPTION USING ERRCODE='23514',
   MESSAGE='Retained permission grants prevent downgrade; restore a verified pre-upgrade backup.';
 END IF;
END $permission$;
DROP TRIGGER {trigger} ON reconforge.tenants;
DROP FUNCTION {seed}();
DELETE FROM reconforge.identity_permissions WHERE name IN ({names});
""").format(names=names, seed=sql.Identifier("reconforge", f"seed_{module}_permissions"),
             trigger=sql.Identifier(f"{module}_permission_tenant_seed")).as_string()
