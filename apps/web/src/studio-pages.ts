import type { MessageKey } from "./i18n";
import type { StudioPage } from "./types";

const operationalLabels: Partial<Record<StudioPage, MessageKey>> = {
  salesRevenue: "salesRevenue",
  procurementOperations: "procurementOperations",
  enterpriseFinance: "enterpriseFinance",
  receivables: "receivables",
  notifications: "notifications",
  budgetControl: "budgetControl",
  inventoryReceipt: "inventoryReceipt",
  durableJobs: "durableJobs",
  exceptions: "exceptions",
};

/** Live pages share browser identity and never display bundled demo totals. */
export function isLiveOperationalPage(page: StudioPage): boolean {
  return operationalLabels[page] !== undefined;
}

export function operationalPageLabel(page: StudioPage): MessageKey | undefined {
  return operationalLabels[page];
}
