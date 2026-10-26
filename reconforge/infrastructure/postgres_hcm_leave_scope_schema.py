"""Bind leave records to the selected canonical employee entity without inference."""

UPGRADE_SQL = r"""
DROP POLICY IF EXISTS tenant_scope ON reconforge.hcm_leave_entitlement_balances;
CREATE POLICY tenant_scope ON reconforge.hcm_leave_entitlement_balances
USING (
 tenant_id=current_setting('app.tenant_id',true)
 AND workspace_id=current_setting('app.workspace_id',true)
 AND EXISTS(SELECT 1 FROM reconforge.hc_employees employee
  WHERE employee.tenant_id=hcm_leave_entitlement_balances.tenant_id
   AND employee.workspace_id=hcm_leave_entitlement_balances.workspace_id
   AND employee.id=hcm_leave_entitlement_balances.employee_id
   AND employee.organization_id=current_setting('app.organization_id',true)
   AND employee.legal_entity_id=current_setting('app.legal_entity_id',true))
)
WITH CHECK (
 tenant_id=current_setting('app.tenant_id',true)
 AND workspace_id=current_setting('app.workspace_id',true)
 AND EXISTS(SELECT 1 FROM reconforge.hc_employees employee
  WHERE employee.tenant_id=hcm_leave_entitlement_balances.tenant_id
   AND employee.workspace_id=hcm_leave_entitlement_balances.workspace_id
   AND employee.id=hcm_leave_entitlement_balances.employee_id
   AND employee.organization_id=current_setting('app.organization_id',true)
   AND employee.legal_entity_id=current_setting('app.legal_entity_id',true))
);
DROP POLICY IF EXISTS tenant_scope ON reconforge.hcm_leave_requests;
CREATE POLICY tenant_scope ON reconforge.hcm_leave_requests
USING (
 tenant_id=current_setting('app.tenant_id',true)
 AND workspace_id=current_setting('app.workspace_id',true)
 AND EXISTS(SELECT 1 FROM reconforge.hc_employees employee
  WHERE employee.tenant_id=hcm_leave_requests.tenant_id
   AND employee.workspace_id=hcm_leave_requests.workspace_id
   AND employee.id=hcm_leave_requests.employee_id
   AND employee.organization_id=current_setting('app.organization_id',true)
   AND employee.legal_entity_id=current_setting('app.legal_entity_id',true))
)
WITH CHECK (
 tenant_id=current_setting('app.tenant_id',true)
 AND workspace_id=current_setting('app.workspace_id',true)
 AND EXISTS(SELECT 1 FROM reconforge.hc_employees employee
  WHERE employee.tenant_id=hcm_leave_requests.tenant_id
   AND employee.workspace_id=hcm_leave_requests.workspace_id
   AND employee.id=hcm_leave_requests.employee_id
   AND employee.organization_id=current_setting('app.organization_id',true)
   AND employee.legal_entity_id=current_setting('app.legal_entity_id',true))
);
"""

DOWNGRADE_SQL = r"""
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM reconforge.hcm_leave_entitlement_balances)
 OR EXISTS(SELECT 1 FROM reconforge.hcm_leave_requests) THEN
  RAISE EXCEPTION 'Populated leave records prevent scope downgrade; retain data and use forward recovery';
 END IF;
END $$;
DROP POLICY IF EXISTS tenant_scope ON reconforge.hcm_leave_entitlement_balances;
CREATE POLICY tenant_scope ON reconforge.hcm_leave_entitlement_balances
 USING(tenant_id=current_setting('app.tenant_id',true) AND workspace_id=current_setting('app.workspace_id',true))
 WITH CHECK(tenant_id=current_setting('app.tenant_id',true) AND workspace_id=current_setting('app.workspace_id',true));
DROP POLICY IF EXISTS tenant_scope ON reconforge.hcm_leave_requests;
CREATE POLICY tenant_scope ON reconforge.hcm_leave_requests
 USING(tenant_id=current_setting('app.tenant_id',true) AND workspace_id=current_setting('app.workspace_id',true))
 WITH CHECK(tenant_id=current_setting('app.tenant_id',true) AND workspace_id=current_setting('app.workspace_id',true));
"""
