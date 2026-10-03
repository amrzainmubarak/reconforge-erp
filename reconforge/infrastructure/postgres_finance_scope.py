"""Additive Finance natural-key authority and relationship restrictions."""
from __future__ import annotations

from typing import Any

POSTGRES_FINANCE_SCOPE_SCHEMA_SQL = r"""
-- Additive restrictions: original tenant/workspace policies remain in place.
ALTER TABLE reconforge.finance_charts ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.finance_charts FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS finance_hierarchy ON reconforge.finance_charts;
CREATE POLICY finance_hierarchy ON reconforge.finance_charts AS RESTRICTIVE
 USING (tenant_id=current_setting('app.tenant_id',true) AND (NULLIF(current_setting('app.legal_entity_id',true),'') IS NOT DISTINCT FROM NULLIF(current_setting('app.entity_id',true),'')) AND (NULLIF(current_setting('app.legal_entity_id',true),'') IS NULL OR NOT (NULLIF(current_setting('app.organization_id',true),'') IS NULL)) AND (NULLIF(current_setting('app.workspace_id',true),'') IS NULL OR workspace_id=current_setting('app.workspace_id',true)) AND ((NULLIF(current_setting('app.workspace_id',true),'') IS NULL AND NULLIF(current_setting('app.organization_id',true),'') IS NULL AND NULLIF(current_setting('app.legal_entity_id',true),'') IS NULL) OR (organization_code='' AND (NULLIF(current_setting('app.organization_id',true),'') IS NULL OR EXISTS (SELECT 1 FROM reconforge.organizations o WHERE o.tenant_id=finance_charts.tenant_id AND o.application_workspace_id=finance_charts.workspace_id AND o.id=current_setting('app.organization_id',true)))) OR EXISTS (SELECT 1 FROM reconforge.organizations o WHERE o.tenant_id=finance_charts.tenant_id AND o.application_workspace_id=finance_charts.workspace_id AND o.organization_code=finance_charts.organization_code AND (NULLIF(current_setting('app.organization_id',true),'') IS NULL OR o.id=current_setting('app.organization_id',true)))))
 WITH CHECK (tenant_id=current_setting('app.tenant_id',true) AND (NULLIF(current_setting('app.legal_entity_id',true),'') IS NOT DISTINCT FROM NULLIF(current_setting('app.entity_id',true),'')) AND (NULLIF(current_setting('app.legal_entity_id',true),'') IS NULL OR NOT (NULLIF(current_setting('app.organization_id',true),'') IS NULL)) AND (NULLIF(current_setting('app.workspace_id',true),'') IS NULL OR workspace_id=current_setting('app.workspace_id',true)) AND (organization_code='' OR EXISTS (SELECT 1 FROM reconforge.organizations o WHERE o.tenant_id=finance_charts.tenant_id AND o.application_workspace_id=finance_charts.workspace_id AND o.organization_code=finance_charts.organization_code AND (NULLIF(current_setting('app.organization_id',true),'') IS NULL OR o.id=current_setting('app.organization_id',true)) FOR SHARE OF o)));
DROP POLICY IF EXISTS finance_reference_insert ON reconforge.finance_charts;
CREATE POLICY finance_reference_insert ON reconforge.finance_charts AS RESTRICTIVE FOR INSERT
 WITH CHECK (NULLIF(current_setting('app.legal_entity_id',true),'') IS NULL AND (NULLIF(current_setting('app.organization_id',true),'') IS NULL OR (organization_code<>'')));
DROP POLICY IF EXISTS finance_reference_update ON reconforge.finance_charts;
CREATE POLICY finance_reference_update ON reconforge.finance_charts AS RESTRICTIVE FOR UPDATE
 USING (NULLIF(current_setting('app.legal_entity_id',true),'') IS NULL AND (NULLIF(current_setting('app.organization_id',true),'') IS NULL OR (organization_code<>'')))
 WITH CHECK (NULLIF(current_setting('app.legal_entity_id',true),'') IS NULL AND (NULLIF(current_setting('app.organization_id',true),'') IS NULL OR (organization_code<>'')));
DROP POLICY IF EXISTS finance_reference_delete ON reconforge.finance_charts;
CREATE POLICY finance_reference_delete ON reconforge.finance_charts AS RESTRICTIVE FOR DELETE
 USING (NULLIF(current_setting('app.legal_entity_id',true),'') IS NULL AND (NULLIF(current_setting('app.organization_id',true),'') IS NULL OR (organization_code<>'')));
ALTER TABLE reconforge.finance_dimensions ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.finance_dimensions FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS finance_hierarchy ON reconforge.finance_dimensions;
CREATE POLICY finance_hierarchy ON reconforge.finance_dimensions AS RESTRICTIVE
 USING (tenant_id=current_setting('app.tenant_id',true) AND (NULLIF(current_setting('app.legal_entity_id',true),'') IS NOT DISTINCT FROM NULLIF(current_setting('app.entity_id',true),'')) AND (NULLIF(current_setting('app.legal_entity_id',true),'') IS NULL OR NOT (NULLIF(current_setting('app.organization_id',true),'') IS NULL)) AND (NULLIF(current_setting('app.workspace_id',true),'') IS NULL OR workspace_id=current_setting('app.workspace_id',true)) AND ((NULLIF(current_setting('app.workspace_id',true),'') IS NULL AND NULLIF(current_setting('app.organization_id',true),'') IS NULL AND NULLIF(current_setting('app.legal_entity_id',true),'') IS NULL) OR (organization_code='' AND (NULLIF(current_setting('app.organization_id',true),'') IS NULL OR EXISTS (SELECT 1 FROM reconforge.organizations o WHERE o.tenant_id=finance_dimensions.tenant_id AND o.application_workspace_id=finance_dimensions.workspace_id AND o.id=current_setting('app.organization_id',true)))) OR EXISTS (SELECT 1 FROM reconforge.organizations o WHERE o.tenant_id=finance_dimensions.tenant_id AND o.application_workspace_id=finance_dimensions.workspace_id AND o.organization_code=finance_dimensions.organization_code AND (NULLIF(current_setting('app.organization_id',true),'') IS NULL OR o.id=current_setting('app.organization_id',true)))))
 WITH CHECK (tenant_id=current_setting('app.tenant_id',true) AND (NULLIF(current_setting('app.legal_entity_id',true),'') IS NOT DISTINCT FROM NULLIF(current_setting('app.entity_id',true),'')) AND (NULLIF(current_setting('app.legal_entity_id',true),'') IS NULL OR NOT (NULLIF(current_setting('app.organization_id',true),'') IS NULL)) AND (NULLIF(current_setting('app.workspace_id',true),'') IS NULL OR workspace_id=current_setting('app.workspace_id',true)) AND (organization_code='' OR EXISTS (SELECT 1 FROM reconforge.organizations o WHERE o.tenant_id=finance_dimensions.tenant_id AND o.application_workspace_id=finance_dimensions.workspace_id AND o.organization_code=finance_dimensions.organization_code AND (NULLIF(current_setting('app.organization_id',true),'') IS NULL OR o.id=current_setting('app.organization_id',true)) FOR SHARE OF o)));
DROP POLICY IF EXISTS finance_reference_insert ON reconforge.finance_dimensions;
CREATE POLICY finance_reference_insert ON reconforge.finance_dimensions AS RESTRICTIVE FOR INSERT
 WITH CHECK (NULLIF(current_setting('app.legal_entity_id',true),'') IS NULL AND (NULLIF(current_setting('app.organization_id',true),'') IS NULL OR (organization_code<>'')));
DROP POLICY IF EXISTS finance_reference_update ON reconforge.finance_dimensions;
CREATE POLICY finance_reference_update ON reconforge.finance_dimensions AS RESTRICTIVE FOR UPDATE
 USING (NULLIF(current_setting('app.legal_entity_id',true),'') IS NULL AND (NULLIF(current_setting('app.organization_id',true),'') IS NULL OR (organization_code<>'')))
 WITH CHECK (NULLIF(current_setting('app.legal_entity_id',true),'') IS NULL AND (NULLIF(current_setting('app.organization_id',true),'') IS NULL OR (organization_code<>'')));
DROP POLICY IF EXISTS finance_reference_delete ON reconforge.finance_dimensions;
CREATE POLICY finance_reference_delete ON reconforge.finance_dimensions AS RESTRICTIVE FOR DELETE
 USING (NULLIF(current_setting('app.legal_entity_id',true),'') IS NULL AND (NULLIF(current_setting('app.organization_id',true),'') IS NULL OR (organization_code<>'')));
ALTER TABLE reconforge.finance_accounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.finance_accounts FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS finance_hierarchy ON reconforge.finance_accounts;
CREATE POLICY finance_hierarchy ON reconforge.finance_accounts AS RESTRICTIVE
 USING (tenant_id=current_setting('app.tenant_id',true) AND (NULLIF(current_setting('app.legal_entity_id',true),'') IS NOT DISTINCT FROM NULLIF(current_setting('app.entity_id',true),'')) AND (NULLIF(current_setting('app.legal_entity_id',true),'') IS NULL OR NOT (NULLIF(current_setting('app.organization_id',true),'') IS NULL)) AND (NULLIF(current_setting('app.workspace_id',true),'') IS NULL OR workspace_id=current_setting('app.workspace_id',true)) AND (EXISTS (SELECT 1 FROM reconforge.finance_charts c WHERE c.tenant_id=finance_accounts.tenant_id AND c.id=finance_accounts.chart_id AND c.workspace_id=finance_accounts.workspace_id)))
 WITH CHECK (tenant_id=current_setting('app.tenant_id',true) AND (NULLIF(current_setting('app.legal_entity_id',true),'') IS NOT DISTINCT FROM NULLIF(current_setting('app.entity_id',true),'')) AND (NULLIF(current_setting('app.legal_entity_id',true),'') IS NULL OR NOT (NULLIF(current_setting('app.organization_id',true),'') IS NULL)) AND (NULLIF(current_setting('app.workspace_id',true),'') IS NULL OR workspace_id=current_setting('app.workspace_id',true)) AND (EXISTS (SELECT 1 FROM reconforge.finance_charts c WHERE c.tenant_id=finance_accounts.tenant_id AND c.id=finance_accounts.chart_id AND c.workspace_id=finance_accounts.workspace_id)));
DROP POLICY IF EXISTS finance_reference_insert ON reconforge.finance_accounts;
CREATE POLICY finance_reference_insert ON reconforge.finance_accounts AS RESTRICTIVE FOR INSERT
 WITH CHECK (NULLIF(current_setting('app.legal_entity_id',true),'') IS NULL AND (NULLIF(current_setting('app.organization_id',true),'') IS NULL OR (EXISTS (SELECT 1 FROM reconforge.finance_charts c WHERE c.tenant_id=finance_accounts.tenant_id AND c.id=finance_accounts.chart_id AND c.organization_code<>''))));
DROP POLICY IF EXISTS finance_reference_update ON reconforge.finance_accounts;
CREATE POLICY finance_reference_update ON reconforge.finance_accounts AS RESTRICTIVE FOR UPDATE
 USING (NULLIF(current_setting('app.legal_entity_id',true),'') IS NULL AND (NULLIF(current_setting('app.organization_id',true),'') IS NULL OR (EXISTS (SELECT 1 FROM reconforge.finance_charts c WHERE c.tenant_id=finance_accounts.tenant_id AND c.id=finance_accounts.chart_id AND c.organization_code<>''))))
 WITH CHECK (NULLIF(current_setting('app.legal_entity_id',true),'') IS NULL AND (NULLIF(current_setting('app.organization_id',true),'') IS NULL OR (EXISTS (SELECT 1 FROM reconforge.finance_charts c WHERE c.tenant_id=finance_accounts.tenant_id AND c.id=finance_accounts.chart_id AND c.organization_code<>''))));
DROP POLICY IF EXISTS finance_reference_delete ON reconforge.finance_accounts;
CREATE POLICY finance_reference_delete ON reconforge.finance_accounts AS RESTRICTIVE FOR DELETE
 USING (NULLIF(current_setting('app.legal_entity_id',true),'') IS NULL AND (NULLIF(current_setting('app.organization_id',true),'') IS NULL OR (EXISTS (SELECT 1 FROM reconforge.finance_charts c WHERE c.tenant_id=finance_accounts.tenant_id AND c.id=finance_accounts.chart_id AND c.organization_code<>''))));
ALTER TABLE reconforge.finance_dimension_values ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.finance_dimension_values FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS finance_hierarchy ON reconforge.finance_dimension_values;
CREATE POLICY finance_hierarchy ON reconforge.finance_dimension_values AS RESTRICTIVE
 USING (tenant_id=current_setting('app.tenant_id',true) AND (NULLIF(current_setting('app.legal_entity_id',true),'') IS NOT DISTINCT FROM NULLIF(current_setting('app.entity_id',true),'')) AND (NULLIF(current_setting('app.legal_entity_id',true),'') IS NULL OR NOT (NULLIF(current_setting('app.organization_id',true),'') IS NULL)) AND (NULLIF(current_setting('app.workspace_id',true),'') IS NULL OR workspace_id=current_setting('app.workspace_id',true)) AND (EXISTS (SELECT 1 FROM reconforge.finance_dimensions d WHERE d.tenant_id=finance_dimension_values.tenant_id AND d.id=finance_dimension_values.dimension_id AND d.workspace_id=finance_dimension_values.workspace_id)))
 WITH CHECK (tenant_id=current_setting('app.tenant_id',true) AND (NULLIF(current_setting('app.legal_entity_id',true),'') IS NOT DISTINCT FROM NULLIF(current_setting('app.entity_id',true),'')) AND (NULLIF(current_setting('app.legal_entity_id',true),'') IS NULL OR NOT (NULLIF(current_setting('app.organization_id',true),'') IS NULL)) AND (NULLIF(current_setting('app.workspace_id',true),'') IS NULL OR workspace_id=current_setting('app.workspace_id',true)) AND (EXISTS (SELECT 1 FROM reconforge.finance_dimensions d WHERE d.tenant_id=finance_dimension_values.tenant_id AND d.id=finance_dimension_values.dimension_id AND d.workspace_id=finance_dimension_values.workspace_id)));
DROP POLICY IF EXISTS finance_reference_insert ON reconforge.finance_dimension_values;
CREATE POLICY finance_reference_insert ON reconforge.finance_dimension_values AS RESTRICTIVE FOR INSERT
 WITH CHECK (NULLIF(current_setting('app.legal_entity_id',true),'') IS NULL AND (NULLIF(current_setting('app.organization_id',true),'') IS NULL OR (EXISTS (SELECT 1 FROM reconforge.finance_dimensions d WHERE d.tenant_id=finance_dimension_values.tenant_id AND d.id=finance_dimension_values.dimension_id AND d.organization_code<>''))));
DROP POLICY IF EXISTS finance_reference_update ON reconforge.finance_dimension_values;
CREATE POLICY finance_reference_update ON reconforge.finance_dimension_values AS RESTRICTIVE FOR UPDATE
 USING (NULLIF(current_setting('app.legal_entity_id',true),'') IS NULL AND (NULLIF(current_setting('app.organization_id',true),'') IS NULL OR (EXISTS (SELECT 1 FROM reconforge.finance_dimensions d WHERE d.tenant_id=finance_dimension_values.tenant_id AND d.id=finance_dimension_values.dimension_id AND d.organization_code<>''))))
 WITH CHECK (NULLIF(current_setting('app.legal_entity_id',true),'') IS NULL AND (NULLIF(current_setting('app.organization_id',true),'') IS NULL OR (EXISTS (SELECT 1 FROM reconforge.finance_dimensions d WHERE d.tenant_id=finance_dimension_values.tenant_id AND d.id=finance_dimension_values.dimension_id AND d.organization_code<>''))));
DROP POLICY IF EXISTS finance_reference_delete ON reconforge.finance_dimension_values;
CREATE POLICY finance_reference_delete ON reconforge.finance_dimension_values AS RESTRICTIVE FOR DELETE
 USING (NULLIF(current_setting('app.legal_entity_id',true),'') IS NULL AND (NULLIF(current_setting('app.organization_id',true),'') IS NULL OR (EXISTS (SELECT 1 FROM reconforge.finance_dimensions d WHERE d.tenant_id=finance_dimension_values.tenant_id AND d.id=finance_dimension_values.dimension_id AND d.organization_code<>''))));
ALTER TABLE reconforge.finance_journals ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.finance_journals FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS finance_hierarchy ON reconforge.finance_journals;
CREATE POLICY finance_hierarchy ON reconforge.finance_journals AS RESTRICTIVE
 USING (tenant_id=current_setting('app.tenant_id',true) AND (NULLIF(current_setting('app.legal_entity_id',true),'') IS NOT DISTINCT FROM NULLIF(current_setting('app.entity_id',true),'')) AND (NULLIF(current_setting('app.legal_entity_id',true),'') IS NULL OR NOT (NULLIF(current_setting('app.organization_id',true),'') IS NULL)) AND (NULLIF(current_setting('app.workspace_id',true),'') IS NULL OR workspace_id=current_setting('app.workspace_id',true)) AND (((NULLIF(current_setting('app.workspace_id',true),'') IS NULL AND NULLIF(current_setting('app.organization_id',true),'') IS NULL AND NULLIF(current_setting('app.legal_entity_id',true),'') IS NULL) OR EXISTS (SELECT 1 FROM reconforge.organizations o WHERE o.tenant_id=finance_journals.tenant_id AND o.application_workspace_id=finance_journals.workspace_id AND o.organization_code=finance_journals.organization_code AND (NULLIF(current_setting('app.organization_id',true),'') IS NULL OR o.id=current_setting('app.organization_id',true)))) AND EXISTS (SELECT 1 FROM reconforge.finance_charts c WHERE c.tenant_id=finance_journals.tenant_id AND c.id=finance_journals.chart_id AND c.workspace_id=finance_journals.workspace_id AND (c.organization_code='' OR c.organization_code=finance_journals.organization_code))))
 WITH CHECK (tenant_id=current_setting('app.tenant_id',true) AND (NULLIF(current_setting('app.legal_entity_id',true),'') IS NOT DISTINCT FROM NULLIF(current_setting('app.entity_id',true),'')) AND (NULLIF(current_setting('app.legal_entity_id',true),'') IS NULL OR NOT (NULLIF(current_setting('app.organization_id',true),'') IS NULL)) AND (NULLIF(current_setting('app.workspace_id',true),'') IS NULL OR workspace_id=current_setting('app.workspace_id',true)) AND (EXISTS (SELECT 1 FROM reconforge.organizations o WHERE o.tenant_id=finance_journals.tenant_id AND o.application_workspace_id=finance_journals.workspace_id AND o.organization_code=finance_journals.organization_code AND (NULLIF(current_setting('app.organization_id',true),'') IS NULL OR o.id=current_setting('app.organization_id',true)) FOR SHARE OF o) AND EXISTS (SELECT 1 FROM reconforge.finance_charts c WHERE c.tenant_id=finance_journals.tenant_id AND c.id=finance_journals.chart_id AND c.workspace_id=finance_journals.workspace_id AND (c.organization_code='' OR c.organization_code=finance_journals.organization_code))));
DROP POLICY IF EXISTS finance_reference_insert ON reconforge.finance_journals;
CREATE POLICY finance_reference_insert ON reconforge.finance_journals AS RESTRICTIVE FOR INSERT
 WITH CHECK (NULLIF(current_setting('app.legal_entity_id',true),'') IS NULL AND (NULLIF(current_setting('app.organization_id',true),'') IS NULL OR (TRUE)));
DROP POLICY IF EXISTS finance_reference_update ON reconforge.finance_journals;
CREATE POLICY finance_reference_update ON reconforge.finance_journals AS RESTRICTIVE FOR UPDATE
 USING (NULLIF(current_setting('app.legal_entity_id',true),'') IS NULL AND (NULLIF(current_setting('app.organization_id',true),'') IS NULL OR (TRUE)))
 WITH CHECK (NULLIF(current_setting('app.legal_entity_id',true),'') IS NULL AND (NULLIF(current_setting('app.organization_id',true),'') IS NULL OR (TRUE)));
DROP POLICY IF EXISTS finance_reference_delete ON reconforge.finance_journals;
CREATE POLICY finance_reference_delete ON reconforge.finance_journals AS RESTRICTIVE FOR DELETE
 USING (NULLIF(current_setting('app.legal_entity_id',true),'') IS NULL AND (NULLIF(current_setting('app.organization_id',true),'') IS NULL OR (TRUE)));
ALTER TABLE reconforge.finance_entries ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.finance_entries FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS finance_hierarchy ON reconforge.finance_entries;
CREATE POLICY finance_hierarchy ON reconforge.finance_entries AS RESTRICTIVE
 USING (tenant_id=current_setting('app.tenant_id',true) AND (NULLIF(current_setting('app.legal_entity_id',true),'') IS NOT DISTINCT FROM NULLIF(current_setting('app.entity_id',true),'')) AND (NULLIF(current_setting('app.legal_entity_id',true),'') IS NULL OR NOT (NULLIF(current_setting('app.organization_id',true),'') IS NULL)) AND (NULLIF(current_setting('app.workspace_id',true),'') IS NULL OR workspace_id=current_setting('app.workspace_id',true)) AND (((NULLIF(current_setting('app.workspace_id',true),'') IS NULL AND NULLIF(current_setting('app.organization_id',true),'') IS NULL AND NULLIF(current_setting('app.legal_entity_id',true),'') IS NULL) OR (EXISTS (SELECT 1 FROM reconforge.organizations o JOIN reconforge.legal_entities e ON e.tenant_id=o.tenant_id AND e.organization_id=o.id WHERE o.tenant_id=finance_entries.tenant_id AND o.application_workspace_id=finance_entries.workspace_id AND o.organization_code=finance_entries.organization_code AND e.entity_code=finance_entries.entity_code AND (NULLIF(current_setting('app.organization_id',true),'') IS NULL OR o.id=current_setting('app.organization_id',true)) AND (NULLIF(current_setting('app.legal_entity_id',true),'') IS NULL OR e.id=current_setting('app.legal_entity_id',true))) AND EXISTS (SELECT 1 FROM reconforge.fiscal_periods p WHERE p.tenant_id=finance_entries.tenant_id AND p.id=finance_entries.period_id AND p.application_workspace_id=finance_entries.workspace_id))) AND EXISTS (SELECT 1 FROM reconforge.finance_journals j WHERE j.tenant_id=finance_entries.tenant_id AND j.id=finance_entries.journal_id AND j.workspace_id=finance_entries.workspace_id AND j.organization_code=finance_entries.organization_code)))
 WITH CHECK (tenant_id=current_setting('app.tenant_id',true) AND (NULLIF(current_setting('app.legal_entity_id',true),'') IS NOT DISTINCT FROM NULLIF(current_setting('app.entity_id',true),'')) AND (NULLIF(current_setting('app.legal_entity_id',true),'') IS NULL OR NOT (NULLIF(current_setting('app.organization_id',true),'') IS NULL)) AND (NULLIF(current_setting('app.workspace_id',true),'') IS NULL OR workspace_id=current_setting('app.workspace_id',true)) AND (EXISTS (SELECT 1 FROM reconforge.organizations o JOIN reconforge.legal_entities e ON e.tenant_id=o.tenant_id AND e.organization_id=o.id WHERE o.tenant_id=finance_entries.tenant_id AND o.application_workspace_id=finance_entries.workspace_id AND o.organization_code=finance_entries.organization_code AND e.entity_code=finance_entries.entity_code AND (NULLIF(current_setting('app.organization_id',true),'') IS NULL OR o.id=current_setting('app.organization_id',true)) AND (NULLIF(current_setting('app.legal_entity_id',true),'') IS NULL OR e.id=current_setting('app.legal_entity_id',true)) FOR SHARE OF o,e) AND EXISTS (SELECT 1 FROM reconforge.fiscal_periods p WHERE p.tenant_id=finance_entries.tenant_id AND p.id=finance_entries.period_id AND p.application_workspace_id=finance_entries.workspace_id FOR SHARE OF p) AND EXISTS (SELECT 1 FROM reconforge.finance_journals j WHERE j.tenant_id=finance_entries.tenant_id AND j.id=finance_entries.journal_id AND j.workspace_id=finance_entries.workspace_id AND j.organization_code=finance_entries.organization_code)));
ALTER TABLE reconforge.finance_entry_lines ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.finance_entry_lines FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS finance_hierarchy ON reconforge.finance_entry_lines;
CREATE POLICY finance_hierarchy ON reconforge.finance_entry_lines AS RESTRICTIVE
 USING (tenant_id=current_setting('app.tenant_id',true) AND (NULLIF(current_setting('app.legal_entity_id',true),'') IS NOT DISTINCT FROM NULLIF(current_setting('app.entity_id',true),'')) AND (NULLIF(current_setting('app.legal_entity_id',true),'') IS NULL OR NOT (NULLIF(current_setting('app.organization_id',true),'') IS NULL)) AND (EXISTS (SELECT 1 FROM reconforge.finance_entries e WHERE e.tenant_id=finance_entry_lines.tenant_id AND e.id=finance_entry_lines.entry_id)))
 WITH CHECK (tenant_id=current_setting('app.tenant_id',true) AND (NULLIF(current_setting('app.legal_entity_id',true),'') IS NOT DISTINCT FROM NULLIF(current_setting('app.entity_id',true),'')) AND (NULLIF(current_setting('app.legal_entity_id',true),'') IS NULL OR NOT (NULLIF(current_setting('app.organization_id',true),'') IS NULL)) AND (EXISTS (SELECT 1 FROM reconforge.finance_entries e
 JOIN reconforge.finance_journals j ON j.tenant_id=e.tenant_id AND j.id=e.journal_id
 JOIN reconforge.finance_accounts a ON a.tenant_id=e.tenant_id AND a.id=finance_entry_lines.account_id
 WHERE e.tenant_id=finance_entry_lines.tenant_id AND e.id=finance_entry_lines.entry_id
 AND a.workspace_id=e.workspace_id AND a.chart_id=j.chart_id
 AND finance_entry_lines.currency_code=e.currency_code FOR SHARE OF e)));
ALTER TABLE reconforge.finance_entry_line_dimensions ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.finance_entry_line_dimensions FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS finance_hierarchy ON reconforge.finance_entry_line_dimensions;
CREATE POLICY finance_hierarchy ON reconforge.finance_entry_line_dimensions AS RESTRICTIVE
 USING (tenant_id=current_setting('app.tenant_id',true) AND (NULLIF(current_setting('app.legal_entity_id',true),'') IS NOT DISTINCT FROM NULLIF(current_setting('app.entity_id',true),'')) AND (NULLIF(current_setting('app.legal_entity_id',true),'') IS NULL OR NOT (NULLIF(current_setting('app.organization_id',true),'') IS NULL)) AND (EXISTS (SELECT 1 FROM reconforge.finance_entry_lines l WHERE l.tenant_id=finance_entry_line_dimensions.tenant_id AND l.id=finance_entry_line_dimensions.entry_line_id)))
 WITH CHECK (tenant_id=current_setting('app.tenant_id',true) AND (NULLIF(current_setting('app.legal_entity_id',true),'') IS NOT DISTINCT FROM NULLIF(current_setting('app.entity_id',true),'')) AND (NULLIF(current_setting('app.legal_entity_id',true),'') IS NULL OR NOT (NULLIF(current_setting('app.organization_id',true),'') IS NULL)) AND (EXISTS (SELECT 1 FROM reconforge.finance_entry_lines l
 JOIN reconforge.finance_entries e ON e.tenant_id=l.tenant_id AND e.id=l.entry_id
 JOIN reconforge.finance_dimensions d ON d.tenant_id=e.tenant_id AND d.id=finance_entry_line_dimensions.dimension_id
 JOIN reconforge.finance_dimension_values v ON v.tenant_id=d.tenant_id AND v.id=finance_entry_line_dimensions.dimension_value_id
 WHERE l.tenant_id=finance_entry_line_dimensions.tenant_id AND l.id=finance_entry_line_dimensions.entry_line_id
 AND d.workspace_id=e.workspace_id AND v.workspace_id=d.workspace_id AND v.dimension_id=d.id
 AND (d.organization_code='' OR d.organization_code=e.organization_code) FOR SHARE OF l,e)));

-- Identity cannot be relabelled to move retained code-bound financial records.
-- Metadata identity uses OLD/NEW; draft reparenting requires empty locked children.
CREATE OR REPLACE FUNCTION reconforge.guard_finance_scope_identity() RETURNS trigger
 LANGUAGE plpgsql SET search_path=pg_catalog AS $reconforge$
DECLARE field_name TEXT;
BEGIN
 IF TG_TABLE_NAME='finance_entries' THEN
 IF
   ((OLD.status='Validated' AND NEW.status NOT IN ('Validated','Voided')) OR
    (OLD.status='Voided' AND NEW.status<>'Voided')) THEN
  RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Posted finance scope cannot return to Draft.';
 END IF;
 IF OLD.status='Draft' THEN
  IF (NEW.workspace_id,NEW.journal_id,NEW.organization_code,NEW.entity_code,NEW.period_id)
    IS DISTINCT FROM (OLD.workspace_id,OLD.journal_id,OLD.organization_code,OLD.entity_code,OLD.period_id) THEN
   IF current_setting('transaction_isolation')<>'read committed' OR EXISTS (
    SELECT 1 FROM reconforge.finance_entry_lines l WHERE l.tenant_id=OLD.tenant_id AND l.entry_id=OLD.id
   ) THEN
    RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Draft scope replacement requires an empty entry in a fresh read committed transaction.';
   END IF;
  END IF;
  IF (NEW.tenant_id,NEW.id) IS DISTINCT FROM (OLD.tenant_id,OLD.id) THEN
   RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Finance scope identity is immutable.';
  END IF;
  RETURN NEW;
 END IF;
 END IF;
 FOREACH field_name IN ARRAY TG_ARGV LOOP
  IF to_jsonb(NEW)->field_name IS DISTINCT FROM to_jsonb(OLD)->field_name THEN
   RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Finance scope identity is immutable.';
  END IF;
 END LOOP;
 RETURN NEW;
END $reconforge$;

DROP TRIGGER IF EXISTS finance_scope_identity ON reconforge.organizations;
CREATE TRIGGER finance_scope_identity BEFORE UPDATE ON reconforge.organizations
 FOR EACH ROW EXECUTE FUNCTION reconforge.guard_finance_scope_identity('tenant_id','id','application_workspace_id','organization_code');
DROP TRIGGER IF EXISTS finance_scope_identity ON reconforge.legal_entities;
CREATE TRIGGER finance_scope_identity BEFORE UPDATE ON reconforge.legal_entities
 FOR EACH ROW EXECUTE FUNCTION reconforge.guard_finance_scope_identity('tenant_id','id','organization_id','entity_code');
DROP TRIGGER IF EXISTS finance_scope_identity ON reconforge.fiscal_periods;
CREATE TRIGGER finance_scope_identity BEFORE UPDATE ON reconforge.fiscal_periods
 FOR EACH ROW EXECUTE FUNCTION reconforge.guard_finance_scope_identity('tenant_id','id','application_workspace_id');
DROP TRIGGER IF EXISTS finance_scope_identity ON reconforge.finance_charts;
CREATE TRIGGER finance_scope_identity BEFORE UPDATE ON reconforge.finance_charts
 FOR EACH ROW EXECUTE FUNCTION reconforge.guard_finance_scope_identity('tenant_id','id','workspace_id','organization_code','chart_code');
DROP TRIGGER IF EXISTS finance_scope_identity ON reconforge.finance_accounts;
CREATE TRIGGER finance_scope_identity BEFORE UPDATE ON reconforge.finance_accounts
 FOR EACH ROW EXECUTE FUNCTION reconforge.guard_finance_scope_identity('tenant_id','id','workspace_id','chart_id','account_code');
DROP TRIGGER IF EXISTS finance_scope_identity ON reconforge.finance_dimensions;
CREATE TRIGGER finance_scope_identity BEFORE UPDATE ON reconforge.finance_dimensions
 FOR EACH ROW EXECUTE FUNCTION reconforge.guard_finance_scope_identity('tenant_id','id','workspace_id','organization_code','dimension_code');
DROP TRIGGER IF EXISTS finance_scope_identity ON reconforge.finance_dimension_values;
CREATE TRIGGER finance_scope_identity BEFORE UPDATE ON reconforge.finance_dimension_values
 FOR EACH ROW EXECUTE FUNCTION reconforge.guard_finance_scope_identity('tenant_id','id','workspace_id','dimension_id','value_code');
DROP TRIGGER IF EXISTS finance_scope_identity ON reconforge.finance_journals;
CREATE TRIGGER finance_scope_identity BEFORE UPDATE ON reconforge.finance_journals
 FOR EACH ROW EXECUTE FUNCTION reconforge.guard_finance_scope_identity('tenant_id','id','workspace_id','chart_id','organization_code','journal_code','currency_code');
DROP TRIGGER IF EXISTS finance_scope_identity ON reconforge.finance_entries;
CREATE TRIGGER finance_scope_identity BEFORE UPDATE ON reconforge.finance_entries
 FOR EACH ROW EXECUTE FUNCTION reconforge.guard_finance_scope_identity('tenant_id','id','workspace_id','journal_id','organization_code','entity_code','period_id');
DROP TRIGGER IF EXISTS finance_scope_identity ON reconforge.finance_entry_lines;
CREATE TRIGGER finance_scope_identity BEFORE UPDATE ON reconforge.finance_entry_lines
 FOR EACH ROW EXECUTE FUNCTION reconforge.guard_finance_scope_identity('tenant_id','id','entry_id');

-- Parent accounts share chart authority. Composite integrity avoids recursive RLS
-- self-queries and preserves native COPY restore ordering for parent/child rows.
CREATE UNIQUE INDEX IF NOT EXISTS finance_accounts_scope_key
 ON reconforge.finance_accounts(tenant_id,id,workspace_id,chart_id);
DO $reconforge$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='finance_accounts_parent_scope_fk'
  AND conrelid='reconforge.finance_accounts'::regclass) THEN
  ALTER TABLE reconforge.finance_accounts ADD CONSTRAINT finance_accounts_parent_scope_fk
   FOREIGN KEY (tenant_id,parent_account_id,workspace_id,chart_id)
   REFERENCES reconforge.finance_accounts(tenant_id,id,workspace_id,chart_id) NOT VALID;
 END IF;
END $reconforge$;


-- This installed trigger only checks existence and never returns stored data.
-- Writers lock canonical parents FOR SHARE through WITH CHECK. At READ COMMITTED,
-- a deleting parent that waited for a writer sees its newly committed reference.
-- Refuse stale-snapshot deletion rather than permitting a check/insert race.
CREATE OR REPLACE FUNCTION reconforge.guard_finance_scope_parent_delete() RETURNS trigger
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog SET row_security=off AS $reconforge$
DECLARE referenced BOOLEAN;
BEGIN
 IF NOT EXISTS (SELECT 1 FROM reconforge.tenants WHERE id=OLD.tenant_id) THEN
  RETURN OLD; -- A tenant-wide cascading deletion cannot reassign surviving history.
 END IF;
 IF current_setting('transaction_isolation')<>'read committed' THEN
  RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Finance parent deletion requires a fresh read committed transaction.';
 END IF;
 IF TG_TABLE_NAME='organizations' THEN
  SELECT EXISTS (SELECT 1 FROM reconforge.finance_charts f WHERE f.tenant_id=OLD.tenant_id AND f.organization_code=OLD.organization_code AND (OLD.application_workspace_id IS NULL OR f.workspace_id=OLD.application_workspace_id))
   OR EXISTS (SELECT 1 FROM reconforge.finance_dimensions f WHERE f.tenant_id=OLD.tenant_id AND f.organization_code=OLD.organization_code AND (OLD.application_workspace_id IS NULL OR f.workspace_id=OLD.application_workspace_id))
   OR EXISTS (SELECT 1 FROM reconforge.finance_journals f WHERE f.tenant_id=OLD.tenant_id AND f.organization_code=OLD.organization_code AND (OLD.application_workspace_id IS NULL OR f.workspace_id=OLD.application_workspace_id))
   OR EXISTS (SELECT 1 FROM reconforge.finance_entries f WHERE f.tenant_id=OLD.tenant_id AND f.organization_code=OLD.organization_code AND (OLD.application_workspace_id IS NULL OR f.workspace_id=OLD.application_workspace_id)) INTO referenced;
 ELSIF TG_TABLE_NAME='legal_entities' THEN
  SELECT EXISTS (SELECT 1 FROM reconforge.finance_entries f JOIN reconforge.organizations o ON o.tenant_id=f.tenant_id AND o.organization_code=f.organization_code
   WHERE o.tenant_id=OLD.tenant_id AND o.id=OLD.organization_id AND f.entity_code=OLD.entity_code AND (o.application_workspace_id IS NULL OR f.workspace_id=o.application_workspace_id)) INTO referenced;
 ELSE
  SELECT EXISTS (SELECT 1 FROM reconforge.finance_entries f WHERE f.tenant_id=OLD.tenant_id AND f.period_id=OLD.id) INTO referenced;
 END IF;
 IF referenced THEN
  RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Finance history prevents canonical parent deletion; deactivate the reference instead.';
 END IF;
 RETURN OLD;
END $reconforge$;

DROP TRIGGER IF EXISTS finance_scope_parent_delete ON reconforge.organizations;
CREATE TRIGGER finance_scope_parent_delete BEFORE DELETE ON reconforge.organizations
 FOR EACH ROW EXECUTE FUNCTION reconforge.guard_finance_scope_parent_delete();
DROP TRIGGER IF EXISTS finance_scope_parent_delete ON reconforge.legal_entities;
CREATE TRIGGER finance_scope_parent_delete BEFORE DELETE ON reconforge.legal_entities
 FOR EACH ROW EXECUTE FUNCTION reconforge.guard_finance_scope_parent_delete();
DROP TRIGGER IF EXISTS finance_scope_parent_delete ON reconforge.fiscal_periods;
CREATE TRIGGER finance_scope_parent_delete BEFORE DELETE ON reconforge.fiscal_periods
 FOR EACH ROW EXECUTE FUNCTION reconforge.guard_finance_scope_parent_delete();
"""


def install_postgres_finance_scope_schema(connection: Any) -> None:
    """Require the complete master-data application schema before installation."""
    connection.execute(POSTGRES_FINANCE_SCOPE_SCHEMA_SQL)
