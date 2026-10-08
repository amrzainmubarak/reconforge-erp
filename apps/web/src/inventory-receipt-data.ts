import { AdminApiError } from "./data";
import type { BrowserAdminSession } from "./types";
export interface ReceiptScope { workspace: string; organization: string; entity: string }
export interface ReceiptView {
  api_contract_version: "inventory-receipt-api-v1"; plan_id: string; operation: "Receipt" | "FullReceiptReversal";
  status: "Prepared" | "Reviewed" | "Committed"; scope: { workspace_id: string; organization_id: string; legal_entity_id: string; organization_code: string; entity_code: string };
  number: string; posting_date: string; period_id: string; quantity: string; total_value_minor: string; currency_code: string; currency_precision: number;
  preparer_id: string; reviewer_id: string | null; plan_digest: string; review_digest: string | null;
  effect_id: string | null; effect_digest: string | null; movement_id: string | null; entry_id: string | null; cost_layer_id: string | null;
  lines: { account_id: string; debit_minor: string; credit_minor: string }[]; plan_json: string; review_json: string | null; effect_json: string | null;
}
const object = (value: unknown): value is Record<string, unknown> => typeof value === "object" && value !== null && !Array.isArray(value);
const text = (value: unknown): value is string => typeof value === "string" && value.length > 0 && value.length <= 160 && !/[\x00-\x1f\x7f]/.test(value);
const digest = (value: unknown): value is string => typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
const minor = (value: unknown): value is string => typeof value === "string" && /^(0|[1-9][0-9]{0,18})$/.test(value) && BigInt(value) <= 9_000_000_000_000_000_000n;
const invalid = (): never => { throw new Error("inventory_receipt_contract_invalid"); };
export function parseReceiptView(value: unknown, scope: ReceiptScope): ReceiptView {
  if (!object(value) || !object(value.receipt)) return invalid();
  const v = value.receipt;
  const fields = ["api_contract_version", "plan_id", "operation", "status", "scope", "number", "posting_date", "period_id", "quantity", "total_value_minor", "currency_code", "currency_precision", "preparer_id", "reviewer_id", "plan_digest", "review_digest", "effect_id", "effect_digest", "movement_id", "entry_id", "cost_layer_id", "lines", "plan_json", "review_json", "effect_json"];
  if (Object.keys(v).length !== fields.length || !fields.every(k => k in v) || v.api_contract_version !== "inventory-receipt-api-v1" || !text(v.plan_id) || !["Receipt", "FullReceiptReversal"].includes(String(v.operation)) || !["Prepared", "Reviewed", "Committed"].includes(String(v.status)) || !object(v.scope) || Object.keys(v.scope).length !== 5 || !Object.values(v.scope).every(text) || v.scope.workspace_id !== scope.workspace || (scope.organization && v.scope.organization_id !== scope.organization) || (scope.entity && v.scope.legal_entity_id !== scope.entity) || !text(v.number) || !text(v.period_id) || !text(v.preparer_id) || !digest(v.plan_digest) || typeof v.quantity !== "string" || !/^[1-9][0-9]*(?:\.[0-9]+)?$|^0\.[0-9]*[1-9][0-9]*$/.test(v.quantity) || !minor(v.total_value_minor) || v.total_value_minor === "0" || typeof v.currency_code !== "string" || !/^[A-Z]{3}$/.test(v.currency_code) || typeof v.currency_precision !== "number" || !Number.isInteger(v.currency_precision) || v.currency_precision < 0 || v.currency_precision > 8 || typeof v.posting_date !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(v.posting_date) || !Array.isArray(v.lines) || v.lines.length !== 2) return invalid();
  for (const line of v.lines) if (!object(line) || Object.keys(line).length !== 3 || !text(line.account_id) || !minor(line.debit_minor) || !minor(line.credit_minor)) return invalid();
  const lines = v.lines as ReceiptView["lines"];
  if (lines[0].account_id === lines[1].account_id || lines.some(line => BigInt(line.debit_minor) > 0n && BigInt(line.credit_minor) > 0n) || lines.reduce((a, line) => a + BigInt(line.debit_minor), 0n) !== BigInt(v.total_value_minor) || lines.reduce((a, line) => a + BigInt(line.credit_minor), 0n) !== BigInt(v.total_value_minor)) return invalid();
  if (typeof v.plan_json !== "string" || v.plan_json.length > 65536 || (v.status === "Prepared" ? [v.review_digest, v.reviewer_id, v.review_json].some(x => x !== null) : !digest(v.review_digest) || !text(v.reviewer_id) || v.reviewer_id === v.preparer_id || typeof v.review_json !== "string")) return invalid();
  const effectFields = [v.effect_id, v.effect_digest, v.movement_id, v.entry_id, v.cost_layer_id, v.effect_json];
  if (v.status === "Committed" ? !effectFields.every(x => typeof x === "string" && x.length > 0) || !digest(v.effect_digest) : effectFields.some(x => x !== null)) return invalid();
  return v as unknown as ReceiptView;
}
export function receiptMoney(minorUnits: string, precision: number): string {
  if (!minor(minorUnits) || !Number.isInteger(precision) || precision < 0 || precision > 8) return invalid();
  const digits = minorUnits.padStart(precision + 1, "0");
  return precision ? `${digits.slice(0, -precision)}.${digits.slice(-precision)}` : digits;
}
export async function receiptRequest(session: BrowserAdminSession, scope: ReceiptScope, suffix: string, body?: Record<string, string>): Promise<ReceiptView> {
  if (!/^\/plans(?:\/[A-Za-z0-9._:-]+(?:\/(review|commit|reversal))?)?$/.test(suffix) || !text(scope.workspace) || !text(scope.organization) || !text(scope.entity)) return invalid();
  const response = await fetch(`/api/v1/inventory-receipt-posting${suffix}`, { method: body ? "POST" : "GET", credentials: "same-origin", cache: "no-store", headers: { Accept: "application/json", "X-ReconForge-Tenant": session.tenantId, "X-ReconForge-Workspace": scope.workspace, "X-ReconForge-Organization": scope.organization, "X-ReconForge-Legal-Entity": scope.entity, ...(body ? { "Content-Type": "application/json", "X-ReconForge-CSRF": session.csrfToken } : {}) }, ...(body ? { body: JSON.stringify(body) } : {}) });
  if (!response.ok) { let code = `http_${response.status}`; try { const v: unknown = await response.json(); if (object(v) && object(v.error) && typeof v.error.code === "string") code = v.error.code; } catch { /* preserve safe HTTP code */ } throw new AdminApiError(response.status, code); }
  return parseReceiptView(await response.json(), scope);
}

