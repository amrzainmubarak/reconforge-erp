import { AdminApiError } from "./data";
import type { BrowserAdminSession } from "./types";
import type { PreparedScopedCommand } from "./scoped-command";

export interface FinanceScope { workspace_id: string; organization_id: string; legal_entity_id: string }
export interface SourcePlan extends FinanceScope {
  api_contract_version: "operational-finance-api-v1"; id: string; entry_id: string;
  source_kind: "ARInvoice" | "ARReceipt" | "APInvoice" | "APPayment"; source_id: string;
  status: "Draft" | "Reviewed" | "Posted"; amount_minor: string; currency_code: string; currency_precision: number;
  preparer_actor_id: string; reviewer_actor_id: string | null; plan_digest: string; validation_digest: string;
  posting_effect_id: string | null; source_effect_id: string | null; review_digest: string | null;
  organization_code: string; entity_code: string; period_id: string; posting_date: string; reason: string;
  lines: { account_id: string; debit_minor: string; credit_minor: string }[]; source_json: string; snapshot_json: string;
}
export interface TrialBalance {
  currency_policy: null | { currency_code: string; currency_precision: number };
  accounts: { account_id: string; debit_minor: string; credit_minor: string; balance_minor: string; debit_balance_minor: string; credit_balance_minor: string; postings: { effect_id: string; entry_id: string; line_number: number; debit_minor: string; credit_minor: string }[] }[];
  effect_count: number; turnover_totals: { debit_minor: string; credit_minor: string; balanced: boolean }; balance_totals: { debit_minor: string; credit_minor: string; balanced: boolean };
}
const object = (v: unknown): v is Record<string, unknown> => v !== null && typeof v === "object" && !Array.isArray(v);
const text = (v: unknown): v is string => typeof v === "string" && v.length > 0 && v.length <= 500 && !/[\x00-\x1f\x7f]/.test(v);
const minor = (v: unknown): v is string => typeof v === "string" && /^-?(0|[1-9]\d*)$/.test(v) && BigInt(v) >= -9000000000000000000n && BigInt(v) <= 9000000000000000000n;
const digest = (v: unknown) => typeof v === "string" && /^[a-f0-9]{64}$/.test(v);
function invalid(): never { throw new Error("enterprise_finance_contract_invalid"); }
export function sourcePlan(value: unknown, scope: FinanceScope): SourcePlan {
  if (!object(value) || value.api_contract_version !== "operational-finance-api-v1" || !text(value.id) || !text(value.entry_id) || !["ARInvoice", "ARReceipt", "APInvoice", "APPayment"].includes(String(value.source_kind)) || !["Draft", "Reviewed", "Posted"].includes(String(value.status)) || !minor(value.amount_minor) || BigInt(value.amount_minor) <= 0n || !digest(value.plan_digest) || !digest(value.validation_digest) || !text(value.preparer_actor_id) || !text(value.currency_code) || !/^[A-Z]{3}$/.test(value.currency_code) || typeof value.currency_precision !== "number" || !Number.isInteger(value.currency_precision) || value.currency_precision < 0 || value.currency_precision > 8 || !Array.isArray(value.lines) || value.lines.length !== 2 || typeof value.source_json !== "string" || value.source_json.length > 131072 || typeof value.snapshot_json !== "string" || value.snapshot_json.length > 131072) invalid();
  for (const [key, expected] of Object.entries(scope)) if (value[key] !== expected) invalid();
  for (const key of ["source_id", "organization_code", "entity_code", "period_id", "posting_date", "reason"]) if (!text(value[key])) invalid();
  const lines = value.lines;
  for (const line of lines) if (!object(line) || !text(line.account_id) || !minor(line.debit_minor) || !minor(line.credit_minor) || BigInt(line.debit_minor) < 0n || BigInt(line.credit_minor) < 0n) invalid();
  if (lines[0].account_id === lines[1].account_id || lines[0].debit_minor !== value.amount_minor || lines[0].credit_minor !== "0" || lines[1].credit_minor !== value.amount_minor || lines[1].debit_minor !== "0") invalid();
  if (value.status === "Draft" ? value.reviewer_actor_id !== null || value.review_digest !== null : !text(value.reviewer_actor_id) || value.reviewer_actor_id === value.preparer_actor_id || !digest(value.review_digest)) invalid();
  if (value.status === "Posted" ? !text(value.posting_effect_id) || !text(value.source_effect_id) : value.posting_effect_id !== null || value.source_effect_id !== null) invalid();
  return value as unknown as SourcePlan;
}
export function parseTrial(value: unknown): TrialBalance {
  if (!object(value) || value.api_contract_version !== "finance-posting-api-v1" || value.balance_scope !== "selected-period-net-activity" || !Array.isArray(value.accounts) || value.accounts.length > 10000 || typeof value.effect_count !== "number" || !Number.isInteger(value.effect_count) || value.effect_count < 0 || !object(value.turnover_totals) || !object(value.balance_totals)) invalid();
  let debits = 0n, credits = 0n, debitBalances = 0n, creditBalances = 0n;
  const accounts = new Set<string>();
  for (const account of value.accounts) {
    if (!object(account) || !text(account.account_id) || accounts.has(account.account_id) || !["debit_minor", "credit_minor", "balance_minor", "debit_balance_minor", "credit_balance_minor"].every(k => minor(account[k])) || !Array.isArray(account.postings)) invalid();
    accounts.add(account.account_id); let dr = 0n, cr = 0n;
    for (const line of account.postings) { if (!object(line) || !text(line.effect_id) || !text(line.entry_id) || !minor(line.debit_minor) || !minor(line.credit_minor)) invalid(); dr += BigInt(line.debit_minor); cr += BigInt(line.credit_minor); }
    if (dr.toString() !== account.debit_minor || cr.toString() !== account.credit_minor || (dr - cr).toString() !== account.balance_minor || (dr > cr ? dr - cr : 0n).toString() !== account.debit_balance_minor || (cr > dr ? cr - dr : 0n).toString() !== account.credit_balance_minor) invalid();
    debits += dr; credits += cr; debitBalances += dr > cr ? dr - cr : 0n; creditBalances += cr > dr ? cr - dr : 0n;
  }
  for (const [row, dr, cr] of [[value.turnover_totals, debits, credits], [value.balance_totals, debitBalances, creditBalances]] as const) if (row.debit_minor !== dr.toString() || row.credit_minor !== cr.toString() || row.balanced !== (dr === cr)) invalid();
  if (value.currency_policy !== null && (!object(value.currency_policy) || !text(value.currency_policy.currency_code) || typeof value.currency_policy.currency_precision !== "number" || !Number.isInteger(value.currency_policy.currency_precision) || value.currency_policy.currency_precision < 0 || value.currency_policy.currency_precision > 8)) invalid();
  return value as unknown as TrialBalance;
}
export function financeMoney(value: string, precision: number): string {
  if (!minor(value) || !Number.isInteger(precision) || precision < 0 || precision > 8) invalid();
  const negative = value.startsWith("-"); const digits = (negative ? value.slice(1) : value).padStart(precision + 1, "0");
  return `${negative ? "-" : ""}${precision ? `${digits.slice(0, -precision)}.${digits.slice(-precision)}` : digits}`;
}
export async function financeRequest(session: BrowserAdminSession, scope: FinanceScope, path: string, body?: Readonly<Record<string, string | number>>, signal?: AbortSignal): Promise<unknown> {
  if (!Object.values(scope).every(text) || !path.startsWith("/api/v1/") || (body && !session.csrfToken)) invalid();
  const response = await fetch(path, { credentials: "same-origin", cache: "no-store", signal, method: body ? "POST" : "GET", headers: { Accept: "application/json", "X-ReconForge-Tenant": session.tenantId, "X-ReconForge-Workspace": scope.workspace_id, "X-ReconForge-Organization": scope.organization_id, "X-ReconForge-Legal-Entity": scope.legal_entity_id, ...(body ? { "Content-Type": "application/json", "X-ReconForge-CSRF": session.csrfToken } : {}) }, ...(body ? { body: JSON.stringify(body) } : {}) });
  if (!response.ok) { let code = `http_${response.status}`; try { const error: unknown = await response.json(); if (object(error) && object(error.error) && text(error.error.code)) code = error.error.code; } catch { /* HTTP remains authoritative. */ } throw new AdminApiError(response.status, code); }
  return response.json();
}
export async function loadSourcePlans(session: BrowserAdminSession, scope: FinanceScope, signal?: AbortSignal): Promise<SourcePlan[]> { const value = await financeRequest(session, scope, "/api/v1/operational-finance/plans?limit=50", undefined, signal); if (!object(value) || !Array.isArray(value.plans) || value.plans.length > 50) invalid(); return value.plans.map(v => sourcePlan(v, scope)); }
export async function executeFinanceCommand(session: BrowserAdminSession, scope: FinanceScope, command: PreparedScopedCommand): Promise<SourcePlan> { const value = await financeRequest(session, scope, command.path, command.body); if (!object(value)) invalid(); return sourcePlan(value.plan, scope); }
