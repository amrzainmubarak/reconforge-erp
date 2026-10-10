"""Bound planning of recursive financial visibility without changing authority.

STABLE invoker functions retain the caller's privileges, FORCE RLS and the
outer statement snapshot. They create a planner boundary around the existing
parent-visibility predicates; write relationship checks are untouched.
"""
from __future__ import annotations

from typing import Any

POSTGRES_FINANCIAL_READ_PLANS_SQL = r"""
CREATE OR REPLACE FUNCTION reconforge.finance_entry_read_visible(p_tenant TEXT,p_entry TEXT)
 RETURNS BOOLEAN LANGUAGE plpgsql STABLE STRICT SECURITY INVOKER SET search_path=pg_catalog AS $rf$
BEGIN
 RETURN EXISTS (SELECT 1 FROM reconforge.finance_entries e WHERE e.tenant_id=p_tenant AND e.id=p_entry);
END $rf$;
CREATE OR REPLACE FUNCTION reconforge.finance_line_read_visible(p_tenant TEXT,p_line TEXT)
 RETURNS BOOLEAN LANGUAGE plpgsql STABLE STRICT SECURITY INVOKER SET search_path=pg_catalog AS $rf$
BEGIN
 RETURN EXISTS (SELECT 1 FROM reconforge.finance_entry_lines l WHERE l.tenant_id=p_tenant AND l.id=p_line);
END $rf$;
ALTER POLICY finance_hierarchy ON reconforge.finance_entry_lines USING (
 tenant_id=current_setting('app.tenant_id',true)
 AND NULLIF(current_setting('app.legal_entity_id',true),'') IS NOT DISTINCT FROM NULLIF(current_setting('app.entity_id',true),'')
 AND (NULLIF(current_setting('app.legal_entity_id',true),'') IS NULL OR NULLIF(current_setting('app.organization_id',true),'') IS NOT NULL)
 AND reconforge.finance_entry_read_visible(tenant_id,entry_id));
ALTER POLICY finance_hierarchy ON reconforge.finance_entry_line_dimensions USING (
 tenant_id=current_setting('app.tenant_id',true)
 AND NULLIF(current_setting('app.legal_entity_id',true),'') IS NOT DISTINCT FROM NULLIF(current_setting('app.entity_id',true),'')
 AND (NULLIF(current_setting('app.legal_entity_id',true),'') IS NULL OR NULLIF(current_setting('app.organization_id',true),'') IS NOT NULL)
 AND reconforge.finance_line_read_visible(tenant_id,entry_line_id));
"""

POSTGRES_FINANCIAL_READ_PLANS_ROLLBACK_SQL = r"""
ALTER POLICY finance_hierarchy ON reconforge.finance_entry_lines USING (
 tenant_id=current_setting('app.tenant_id',true)
 AND NULLIF(current_setting('app.legal_entity_id',true),'') IS NOT DISTINCT FROM NULLIF(current_setting('app.entity_id',true),'')
 AND (NULLIF(current_setting('app.legal_entity_id',true),'') IS NULL OR NULLIF(current_setting('app.organization_id',true),'') IS NOT NULL)
 AND EXISTS (SELECT 1 FROM reconforge.finance_entries e WHERE e.tenant_id=finance_entry_lines.tenant_id AND e.id=finance_entry_lines.entry_id));
ALTER POLICY finance_hierarchy ON reconforge.finance_entry_line_dimensions USING (
 tenant_id=current_setting('app.tenant_id',true)
 AND NULLIF(current_setting('app.legal_entity_id',true),'') IS NOT DISTINCT FROM NULLIF(current_setting('app.entity_id',true),'')
 AND (NULLIF(current_setting('app.legal_entity_id',true),'') IS NULL OR NULLIF(current_setting('app.organization_id',true),'') IS NOT NULL)
 AND EXISTS (SELECT 1 FROM reconforge.finance_entry_lines l WHERE l.tenant_id=finance_entry_line_dimensions.tenant_id AND l.id=finance_entry_line_dimensions.entry_line_id));
DROP FUNCTION IF EXISTS reconforge.finance_line_read_visible(TEXT,TEXT);
DROP FUNCTION IF EXISTS reconforge.finance_entry_read_visible(TEXT,TEXT);
"""


def install_postgres_financial_read_plans(connection: Any) -> None:
    connection.execute(POSTGRES_FINANCIAL_READ_PLANS_SQL)
