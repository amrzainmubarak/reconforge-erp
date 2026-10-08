import { AdminApiError } from "./data";
import type { BrowserAdminSession } from "./types";
import type { PreparedScopedCommand } from "./scoped-command";

export const procurementActions = ["submit-order", "approve-order", "prepare-receipt", "review-receipt", "receive", "match-invoice", "approve-invoice", "prepare-accrual", "review-accrual", "post-accrual", "prepare-payment", "review-payment", "pay"] as const;
export const procurementStages = ["Draft", "Submitted", "Approved", "ReceiptPrepared", "ReceiptReviewed", "Received", "InvoiceMatched", "InvoiceApproved", "AccrualPrepared", "AccrualReviewed", "Accrued", "PaymentPrepared", "PaymentReviewed", "Paid"] as const;
export interface ProcurementScope { workspace_id: string; organization_id: string; legal_entity_id: string; organization_code: string; entity_code: string; organization_name: string; entity_name: string; currency_code: string }
export interface ProcurementCycle {
  id: string; workspace_id: string; organization_id: string; legal_entity_id: string; number: string; row_version: number;
  stage: typeof procurementStages[number]; next_action: typeof procurementActions[number] | ""; total_minor: string;
  purchase_order_id: string; receipt_plan_id: string | null; goods_receipt_id: string | null; invoice_id: string | null;
  accrual_plan_id: string | null; payment_plan_id: string | null; accrual_effect_id: string | null; payment_effect_id: string | null; payment_link_id: string | null;
  request: Record<string, string>;
}
export interface ProcurementDetail { cycle: ProcurementCycle; receipt: unknown }
export interface ProcurementOption { code: string; name?: string; currency_code?: string; account_type?: string }
export interface ProcurementOptions { suppliers: ProcurementOption[]; items: ProcurementOption[]; locations: ProcurementOption[]; policies: ProcurementOption[]; periods: { id: string; name: string; start_date: string; end_date: string }[]; journals: ProcurementOption[]; accounts: ProcurementOption[] }
const root = "/api/v1/procurement-operations";
const object = (value: unknown): value is Record<string, unknown> => typeof value === "object" && value !== null && !Array.isArray(value);
const text = (value: unknown): value is string => typeof value === "string" && value.length > 0 && value.length <= 500;
function invalid(): never { throw new Error("procurement_contract_invalid"); }

export function parseProcurementCycle(value: unknown, scope: ProcurementScope): ProcurementCycle {
  if (!object(value) || !text(value.id) || !text(value.number) || !Number.isSafeInteger(value.row_version) || Number(value.row_version) < 1 ||
    value.workspace_id !== scope.workspace_id || value.organization_id !== scope.organization_id || value.legal_entity_id !== scope.legal_entity_id ||
    !procurementStages.includes(value.stage as ProcurementCycle["stage"]) || typeof value.total_minor !== "string" || !/^[1-9][0-9]{0,18}$/.test(value.total_minor) ||
    !object(value.request) || !Object.values(value.request).every((item) => typeof item === "string") || value.request.organization_code !== scope.organization_code || value.request.entity_code !== scope.entity_code ||
    value.next_action !== (procurementActions[procurementStages.indexOf(value.stage as ProcurementCycle["stage"])] ?? "") || !text(value.purchase_order_id) ||
    !["receipt_plan_id", "goods_receipt_id", "invoice_id", "accrual_plan_id", "payment_plan_id", "accrual_effect_id", "payment_effect_id", "payment_link_id"].every((key) => value[key] === null || text(value[key]))) invalid();
  return value as unknown as ProcurementCycle;
}

export async function procurementFetch(session: BrowserAdminSession, workspace: string, scope: ProcurementScope | null, path: string,
  options: { body?: object; signal?: AbortSignal } = {}): Promise<unknown> {
  if (!path.startsWith("/api/v1/") || path.includes("?")) invalid();
  const response = await fetch(path, { method: options.body ? "POST" : "GET", credentials: "same-origin", cache: "no-store", signal: options.signal,
    headers: { Accept: "application/json", "X-ReconForge-Tenant": session.tenantId, "X-ReconForge-Workspace": workspace,
      ...(scope ? { "X-ReconForge-Organization": scope.organization_id, "X-ReconForge-Legal-Entity": scope.legal_entity_id } : {}),
      ...(options.body ? { "Content-Type": "application/json", "X-ReconForge-CSRF": session.csrfToken } : {}) },
    ...(options.body ? { body: JSON.stringify(options.body) } : {}) });
  if (!response.ok) {
    let code = `http_${response.status}`;
    try { const error: unknown = await response.json(); if (object(error) && object(error.error) && typeof error.error.code === "string") code = error.error.code; } catch { /* Retain safe HTTP error. */ }
    throw new AdminApiError(response.status, code);
  }
  return response.json();
}

export async function procurementScopes(session: BrowserAdminSession, workspace: string, signal?: AbortSignal): Promise<ProcurementScope[]> {
  const value = await procurementFetch(session, workspace, null, root + "/scopes", { signal });
  if (!object(value) || !Array.isArray(value.records) || value.records.length > 200 || !value.records.every((item) => object(item) &&
    ["organization_id", "legal_entity_id", "organization_code", "entity_code", "organization_name", "entity_name", "currency_code"].every((key) => text(item[key])) && item.workspace_id === workspace)) invalid();
  return value.records as ProcurementScope[];
}

export async function procurementOptions(session: BrowserAdminSession, scope: ProcurementScope, signal?: AbortSignal): Promise<ProcurementOptions> {
  const value = await procurementFetch(session, scope.workspace_id, scope, root + "/options", { signal });
  if (!object(value) || !["suppliers", "items", "locations", "policies", "periods", "journals", "accounts"].every((key) => Array.isArray(value[key]) && (value[key] as unknown[]).length <= 200 &&
    (value[key] as unknown[]).every((item) => object(item) && text(key === "periods" ? item.id : item.code)))) invalid();
  return value as unknown as ProcurementOptions;
}

export async function procurementList(session: BrowserAdminSession, scope: ProcurementScope, signal?: AbortSignal): Promise<ProcurementCycle[]> {
  const value = await procurementFetch(session, scope.workspace_id, scope, root + "/cycles", { signal });
  if (!object(value) || !Array.isArray(value.records) || value.records.length > 50) invalid();
  return value.records.map((item) => parseProcurementCycle(item, scope));
}

export async function procurementDetail(session: BrowserAdminSession, scope: ProcurementScope, id: string, signal?: AbortSignal): Promise<ProcurementDetail> {
  const value = await procurementFetch(session, scope.workspace_id, scope, root + "/cycles/" + encodeURIComponent(id), { signal });
  if (!object(value) || !("receipt" in value)) invalid();
  const cycle = parseProcurementCycle(value.cycle, scope);
  if (cycle.id !== id) invalid();
  return { cycle, receipt: value.receipt };
}

export async function procurementCommand(session: BrowserAdminSession, scope: ProcurementScope, command: PreparedScopedCommand): Promise<ProcurementDetail> {
  const value = await procurementFetch(session, scope.workspace_id, scope, command.path, { body: command.body });
  if (!object(value) || !("receipt" in value)) invalid();
  const cycle = parseProcurementCycle(value.cycle, scope);
  const expected = command.body.expected_version;
  if (expected !== undefined && cycle.row_version !== Number(expected) + 1) invalid();
  return { cycle, receipt: value.receipt };
}
