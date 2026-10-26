import type { StudioPage } from "./types";

export type AppStudioPage = StudioPage | "crmSubscriptions" | "governedAssistant" | "projectMilestones";

export function pageFromPath(pathname: string): AppStudioPage {
  const normalized = pathname.replace(/\/+$/, "");
  if (normalized.endsWith("/exceptions")) return "exceptions";
  if (normalized.endsWith("/evidence")) return "evidence";
  if (normalized.endsWith("/inventory")) return "inventory";
  if (normalized.endsWith("/retail-settlement")) return "retailSettlement";
  if (normalized.endsWith("/bank-statement")) return "bankStatement";
  if (normalized.endsWith("/manufacturing-cost")) return "manufacturingCost";
  if (normalized.endsWith("/professional-invoice-payment")) return "professionalInvoicePayment";
  if (normalized.endsWith("/individual-cashflow")) return "individualCashflow";
  if (normalized.endsWith("/mapping")) return "mapping";
  if (normalized.endsWith("/rules")) return "rules";
  if (normalized.endsWith("/live")) return "live";
  if (normalized.endsWith("/admin-audit")) return "adminAudit";
  if (normalized.endsWith("/notifications")) return "notifications";
  if (normalized.endsWith("/receivables")) return "receivables";
  if (normalized.endsWith("/budget-control")) return "budgetControl";
  if (normalized.endsWith("/inventory-receipts")) return "inventoryReceipt";
  if (normalized.endsWith("/jobs")) return "durableJobs";
  if (normalized.endsWith("/sales-revenue")) return "salesRevenue";
  if (normalized.endsWith("/stock-sales")) return "stockSales";
  if (normalized.endsWith("/procurement-partial")) return "procurementPartial";
  if (normalized.endsWith("/financial-reporting")) return "financialReporting";
  if (normalized.endsWith("/fixed-assets")) return "fixedAssets";
  if (normalized.endsWith("/customer-returns")) return "customerReturns";
  if (normalized.endsWith("/operational-fx-tax")) return "operationalFxTax";
  if (normalized.endsWith("/manufacturing-execution")) return "manufacturingExecution";
  if (normalized.endsWith("/intercompany-operations")) return "intercompanyOperations";
  if (normalized.endsWith("/manufacturing-execution-v2")) return "manufacturingExecutionV2";
  if (normalized.endsWith("/intercompany-fx")) return "intercompanyFx";
  if (normalized.endsWith("/intercompany-group-diagnostic")) return "groupDiagnostic";
  if (normalized.endsWith("/intercompany-source-cashflow")) return "intercompanyCashflow";
  if (normalized.endsWith("/project-source-reconciliation")) return "projectSourceReconciliation";
  if (normalized.endsWith("/people-project-payroll")) return "peopleProjectPayroll";
  if (normalized.endsWith("/project-time-billing")) return "projectTimeBilling";
  if (normalized.endsWith("/accrual-deferral")) return "accrualDeferral";
  if (normalized.endsWith("/manufacturing-supply-plan")) return "manufacturingSupplyPlan";
  if (normalized.endsWith("/inventory-transfer")) return "inventoryTransfer";
  if (normalized.endsWith("/procurement-sourcing")) return "procurementSourcing";
  if (normalized.endsWith("/procurement-operations")) return "procurementOperations";
  if (normalized.endsWith("/enterprise-finance") || normalized.endsWith("/erp")) return "enterpriseFinance";
  if (normalized.endsWith("/consolidated-statements")) return "consolidatedStatements";
  if (normalized.endsWith("/master-production-schedule")) return "masterProductionSchedule";
  if (normalized.endsWith("/shop-floor-traceability")) return "shopFloorTraceability";
  if (normalized.endsWith("/crm-subscriptions") || normalized.endsWith("/crm-contracts")) return "crmSubscriptions";
  if (normalized.endsWith("/hcm-leave")) return "hcmLeave";
  if (normalized.endsWith("/governed-assistant")) return "governedAssistant";
  if (normalized.endsWith("/project-milestones") || normalized.endsWith("/project-milestone-billing")) return "projectMilestones";
  return "dashboard";
}

export function pathForPage(page: AppStudioPage): string {
  const base = import.meta.env.BASE_URL.replace(/\/+$/, "");
  const routeNames: Partial<Record<AppStudioPage, string>> = {
    retailSettlement: "retail-settlement",
    bankStatement: "bank-statement",
    manufacturingCost: "manufacturing-cost",
    professionalInvoicePayment: "professional-invoice-payment",
    individualCashflow: "individual-cashflow",
    adminAudit: "admin-audit",
    budgetControl: "budget-control",
    inventoryReceipt: "inventory-receipts",
    durableJobs: "jobs",
    salesRevenue: "sales-revenue",
    stockSales: "stock-sales",
    procurementPartial: "procurement-partial",
    financialReporting: "financial-reporting",
    fixedAssets: "fixed-assets",
    customerReturns: "customer-returns",
    operationalFxTax: "operational-fx-tax",
    manufacturingExecution: "manufacturing-execution",
    intercompanyOperations: "intercompany-operations",
    manufacturingExecutionV2: "manufacturing-execution-v2",
    intercompanyFx: "intercompany-fx",
    intercompanyCashflow: "intercompany-source-cashflow",
    groupDiagnostic: "intercompany-group-diagnostic",
    projectSourceReconciliation: "project-source-reconciliation",
    peopleProjectPayroll: "people-project-payroll",
    projectTimeBilling: "project-time-billing",
    accrualDeferral: "accrual-deferral",
    manufacturingSupplyPlan: "manufacturing-supply-plan",
    inventoryTransfer: "inventory-transfer",
    procurementSourcing: "procurement-sourcing",
    procurementOperations: "procurement-operations",
    enterpriseFinance: "enterprise-finance",
    consolidatedStatements: "consolidated-statements",
    masterProductionSchedule: "master-production-schedule",
    shopFloorTraceability: "shop-floor-traceability",
    crmSubscriptions: "crm-subscriptions",
    crmContracts: "crm-subscriptions",
    hcmLeave: "hcm-leave",
    governedAssistant: "governed-assistant",
    projectMilestones: "project-milestones",
    projectMilestoneBilling: "project-milestones",
  };
  return page === "dashboard" ? `${base}/` || "/" : `${base}/${routeNames[page] ?? page}`;
}
