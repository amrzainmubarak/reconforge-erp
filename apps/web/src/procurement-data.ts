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
export interface ProcurementOption { code: string; name?: string; currency_code?: string; account_type?: string; chart_code?: string }
export interface ProcurementOptions { suppliers: ProcurementOption[]; items: ProcurementOption[]; locations: ProcurementOption[]; policies: ProcurementOption[]; periods: { id: string; name: string; start_date: string; end_date: string }[]; journals: ProcurementOption[]; accounts: ProcurementOption[] }
export interface ProcurementSupplier { id: string; supplier_code: string; name: string; currency_code: string; tax_identifier: string; status: "Draft" | "Active" | "Suspended" | "Closed" }
export interface ProcurementSupplierInput { supplier_code: string; name: string; tax_identifier: string }
const root = "/api/v1/procurement-operations";
const object = (value: unknown): value is Record<string, unknown> => typeof value === "object" && value !== null && !Array.isArray(value);
const text = (value: unknown): value is string => typeof value === "string" && value.length > 0 && value.length <= 500;
function invalid(): never { throw new Error("procurement_contract_invalid"); }

export function parseProcurementCycle(value: unknown, scope: ProcurementScope): ProcurementCycle {
  if (!object(value) || !text(value.id) || !text(value.number) || !Number.isSafeInteger(value.row_version) || Number(value.row_version) < 1 ||
    value.workspace_id !== scope.workspace_id || value.organization_id !== scope.organization_id || value.legal_entity_id !== scope.legal_entity_id ||
    !procurementStages.includes(value.stage as ProcurementCycle["stage"]) || value.row_version !== procurementStages.indexOf(value.stage as ProcurementCycle["stage"]) + 1 ||
    typeof value.total_minor !== "string" || !/^[1-9][0-9]{0,18}$/.test(value.total_minor) || BigInt(value.total_minor) > 9000000000000000000n ||
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
  return parseProcurementOptions(value);
}

export function parseProcurementOptions(value: unknown): ProcurementOptions {
  if (!object(value) || !["suppliers", "items", "locations", "policies", "periods", "journals", "accounts"].every((key) => Array.isArray(value[key]) && (value[key] as unknown[]).length <= 200 &&
    (value[key] as unknown[]).every((item) => object(item) && text(key === "periods" ? item.id : item.code) &&
      (!["journals", "accounts"].includes(key) || text(item.chart_code))))) invalid();
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

export function parseProcurementAcknowledgement(value: unknown, scope: ProcurementScope, command: PreparedScopedCommand): ProcurementDetail {
  if (!object(value) || !("receipt" in value)) invalid();
  const cycle = parseProcurementCycle(value.cycle, scope);
  if (command.path === root + "/cycles") {
    if (cycle.row_version !== 1 || cycle.stage !== "Draft" || cycle.number !== String(command.body.number).trim().toUpperCase()) invalid();
    const codes = ["supplier_code", "item_code", "currency_code", "policy_code", "journal_code", "ap_account_code", "cash_account_code", "organization_code", "entity_code"];
    const exact = ["unit_price_minor", "posting_date", "period_id", "location_code", "workspace"];
    if (!codes.every((key) => cycle.request[key] === String(command.body[key]).trim().toUpperCase()) ||
      !exact.every((key) => cycle.request[key] === String(command.body[key]).trim())) invalid();
    const quantity = String(command.body.quantity).trim();
    if (!/^[0-9]+(?:\.[0-9]+)?$/.test(quantity) || cycle.request.quantity !== quantity.replace(/^0+(?=[0-9])/, "")) invalid();
  } else {
    const match = /^\/api\/v1\/procurement-operations\/cycles\/([^/]+)\/commands\/([^/]+)$/.exec(command.path);
    if (!match || !procurementActions.includes(match[2] as typeof procurementActions[number]) ||
      !Number.isSafeInteger(command.body.expected_version) || cycle.id !== decodeURIComponent(match[1]) ||
      cycle.row_version !== Number(command.body.expected_version) + 1 || cycle.stage !== procurementStages[procurementActions.indexOf(match[2] as typeof procurementActions[number]) + 1]) invalid();
  }
  return { cycle, receipt: value.receipt };
}

export async function procurementCommand(session: BrowserAdminSession, scope: ProcurementScope, command: PreparedScopedCommand): Promise<ProcurementDetail> {
  return parseProcurementAcknowledgement(await procurementFetch(session, scope.workspace_id, scope, command.path, { body: command.body }), scope, command);
}

function parseSupplier(value: unknown, scope: ProcurementScope): ProcurementSupplier {
  if (!object(value) || !["id", "supplier_code", "name"].every((key) => text(value[key])) || typeof value.tax_identifier !== "string" ||
    value.workspace_id !== scope.workspace_id || value.organization_id !== scope.organization_id || value.legal_entity_id !== scope.legal_entity_id ||
    typeof value.currency_code !== "string" || !/^[A-Z]{3}$/.test(value.currency_code) || !["Draft", "Active", "Suspended", "Closed"].includes(String(value.status))) invalid();
  return value as unknown as ProcurementSupplier;
}

export async function procurementSuppliers(session: BrowserAdminSession, scope: ProcurementScope, signal?: AbortSignal): Promise<ProcurementSupplier[]> {
  const value = await procurementFetch(session, scope.workspace_id, scope, "/api/v1/payables/suppliers", { signal });
  if (!object(value) || !Array.isArray(value.suppliers) || value.suppliers.length > 100) invalid();
  return value.suppliers.map((supplier) => parseSupplier(supplier, scope));
}

export async function procurementSaveSupplier(session: BrowserAdminSession, scope: ProcurementScope, input: ProcurementSupplierInput): Promise<ProcurementSupplier> {
  const body = { ...input, workspace: scope.workspace_id, organization_code: scope.organization_code, entity_code: scope.entity_code, currency_code: scope.currency_code, status: "Active" };
  const supplier = parseSupplier(await procurementFetch(session, scope.workspace_id, scope, "/api/v1/payables/suppliers", { body }), scope);
  if (supplier.supplier_code !== input.supplier_code.trim().toUpperCase() || supplier.name !== input.name.trim() || supplier.tax_identifier !== input.tax_identifier.trim() ||
    supplier.currency_code !== scope.currency_code || supplier.status !== "Active") invalid();
  return supplier;
}
