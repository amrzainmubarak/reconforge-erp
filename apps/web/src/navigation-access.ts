import { useEffect, useState } from "react";
import { useBrowserSession } from "./browserSession";
import type { AppStudioPage } from "./studio-routes";

/** Visibility is a convenience. Every server operation still authorizes its scope. */
export const pagePermissions: Partial<Record<AppStudioPage, readonly string[]>> = {
  enterpriseFinance: ["finance_core.read", "finance_core.manage", "finance_core.validate"],
  financialReporting: ["finance_core.read"], fixedAssets: ["finance_core.read"],
  salesRevenue: ["sales.read", "receivables.read", "finance_core.read"],
  receivables: ["receivables.read", "receivables.manage", "receivables.approve", "receivables.credit_override"], budgetControl: ["budget_control.read"],
  crmSubscriptions: ["sales.manage", "sales.approve"], crmContracts: ["sales.manage", "sales.approve"],
  hcmLeave: ["people_project_payroll.personnel", "people_project_payroll.manage", "people_project_payroll.approve_time"],
  peopleProjectPayroll: ["people_project_payroll.read", "people_project_payroll.personnel", "people_project_payroll.manage", "people_project_payroll.read_sensitive"],
  projectMilestones: ["project_time_billing.read", "project_time_billing.manage"],
  projectMilestoneBilling: ["project_time_billing.read", "project_time_billing.manage"],
  projectTimeBilling: ["project_time_billing.read", "finance_core.read"],
  projectSourceReconciliation: ["project_source_reconciliation.read", "finance_core.read"],
  procurementOperations: ["procurement.read", "payables.read", "finance_core.read"],
  procurementPartial: ["procurement_partial.read", "finance_core.read"],
  procurementSourcing: ["procurement_sourcing.read", "finance_core.read"],
  stockSales: ["stock_sales.read", "sales.read", "finance_core.read"],
  customerReturns: ["customer_returns.read", "finance_core.read"],
  operationalFxTax: ["finance_core.read"], accrualDeferral: ["accrual_deferral.read", "finance_core.read"],
  inventoryReceipt: ["inventory.read", "inventory.receipt.read", "finance_core.read"],
  inventoryTransfer: ["inventory_transfer.read", "inventory.read", "finance_core.read"],
  manufacturingExecution: ["manufacturing_execution.read", "finance_core.read"],
  manufacturingExecutionV2: ["manufacturing_execution_v2.read", "finance_core.read"],
  manufacturingSupplyPlan: ["manufacturing_supply_plan.read", "finance_core.read"],
  masterProductionSchedule: ["manufacturing_supply_plan.read", "manufacturing_supply_plan.manage"],
  shopFloorTraceability: ["manufacturing_execution.read", "manufacturing_execution.manage"],
  intercompanyOperations: ["intercompany_operations.read", "finance_core.read"],
  intercompanyFx: ["intercompany_fx.read", "finance_core.read"],
  groupDiagnostic: ["finance_core.read"], intercompanyCashflow: ["finance_core.read"],
  consolidatedStatements: ["finance_core.read", "finance_core.manage"],
  exceptions: ["exceptions.read", "exceptions.manage"], notifications: ["notifications.read"],
  live: ["metrics.read"], durableJobs: ["ops.read"],
  governedAssistant: ["ai.query", "finance_core.read"],
};
// These route dependencies require all listed capabilities, not an OR of role labels.
export const pageAllPermissions: Partial<Record<AppStudioPage, readonly string[]>> = {
  salesRevenue: ["sales.read", "receivables.read", "finance_core.read"],
  stockSales: ["sales.read", "inventory.read", "receivables.read", "finance_core.read"],
  customerReturns: ["sales.read", "receivables.read", "inventory.read", "finance_core.read"],
  procurementOperations: ["finance_core.read", "inventory.read", "payables.read"],
  procurementPartial: ["finance_core.read", "inventory.read", "payables.read"],
  procurementSourcing: ["budget_control.read", "finance_core.read", "inventory.read", "payables.read", "procurement_sourcing.read"],
  inventoryReceipt: ["finance_core.read", "inventory.read"],
  inventoryTransfer: ["finance_core.read", "inventory.read", "inventory.valuation.read", "inventory_transfer.read"],
  manufacturingExecution: ["finance_core.read", "inventory.read", "manufacturing_execution.read"],
  manufacturingExecutionV2: ["finance_core.read", "inventory.read", "manufacturing_execution.read", "manufacturing_execution_v2.read"],
  manufacturingSupplyPlan: ["budget_control.read", "finance_core.read", "inventory.read", "manufacturing_execution.read", "manufacturing_execution_v2.read", "manufacturing_supply_plan.read"],
  projectSourceReconciliation: ["people_project_payroll.read", "project_time_billing.read", "finance_core.read", "receivables.read"],
  projectTimeBilling: ["project_time_billing.read"],
  accrualDeferral: ["accrual_deferral.read", "finance_core.read"],
  intercompanyOperations: ["intercompany_operations.read", "finance_core.read"],
  intercompanyFx: ["intercompany_fx.read", "finance_core.read"],
  groupDiagnostic: ["intercompany_fx.read", "finance_core.read"],
  intercompanyCashflow: ["intercompany_fx.read", "finance_core.read"],
};
export function canViewPage(page: AppStudioPage, permissions: readonly string[] | null): boolean {
  // The identity workspace remains reachable for login, reauthentication and sign out.
  if (page === "adminAudit") return true;
  const all = pageAllPermissions[page];
  if (all) return permissions !== null && all.every(permission => permissions.includes(permission));
  const required = pagePermissions[page];
  return !required || (permissions !== null && required.some(permission => permissions.includes(permission)));
}
export function useNavigationAccess() {
  const auth = useBrowserSession();
  const [attempt, retry] = useState(0);
  const [state, setState] = useState<{ revision: number; permissions: string[] | null; workspaces?: string[]; error: boolean }>({ revision: -1, permissions: null, error: false });
  useEffect(() => {
    if (!auth.session) return;
    const controller = new AbortController(), revision = auth.revision;
    fetch("/api/v1/auth/me", { credentials: "same-origin", cache: "no-store", signal: controller.signal, headers: { Accept: "application/json", "X-ReconForge-Tenant": auth.session.tenantId } })
      .then(async response => {
        if (!response.ok) throw new Error("access_unavailable");
        const body: unknown = await response.json();
        if (body === null || typeof body !== "object" || !("permissions" in body) || !Array.isArray(body.permissions) || !body.permissions.every(item => typeof item === "string" && item.length > 0)) throw new Error("access_invalid");
        if (!controller.signal.aborted && auth.isCurrent(revision)) setState({ revision, permissions: body.permissions, workspaces: "authorized_scopes" in body && body.authorized_scopes !== null && typeof body.authorized_scopes === "object" && "workspaces" in body.authorized_scopes && Array.isArray(body.authorized_scopes.workspaces) && body.authorized_scopes.workspaces.every(item => typeof item === "string") ? body.authorized_scopes.workspaces : [], error: false });
      }).catch(() => { if (!controller.signal.aborted && auth.isCurrent(revision)) setState({ revision, permissions: null, error: true }); });
    return () => controller.abort();
  }, [auth.revision, auth.session, auth.isCurrent, attempt]);
  const current = state.revision === auth.revision;
  return { signedIn: !!auth.session, loading: !!auth.session && !current, error: !!auth.session && current && state.error,
    permissions: current ? state.permissions : null, workspaces: current ? state.workspaces ?? [] : [], retry: () => { setState({ revision: -1, permissions: null, error: false }); retry(value => value + 1); },
    canView: (page: AppStudioPage) => !auth.session || canViewPage(page, current ? state.permissions : null) };
}
