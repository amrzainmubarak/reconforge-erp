import { financeRequest, type FinanceScope } from "./enterprise-finance-data";
import type { BrowserAdminSession } from "./types";
import type { PreparedScopedCommand } from "./scoped-command";

export interface AssetSummary extends FinanceScope {
  id: string; asset_number: string; name: string; cost_minor: string; salvage_minor: string;
  useful_life_months: number; currency_code: string; currency_precision: number; asset_digest: string;
  acquired: boolean; disposed: boolean; accumulated_minor: string; months: number; sequence: number;
}
export interface AssetPlan extends FinanceScope {
  id: string; asset_id: string; entry_id: string; kind: "acquire" | "depreciate" | "dispose";
  phase: number; status: "Prepared" | "Reviewed" | "Posted"; posting_date: string; period_id: string;
  amount_minor: string; accumulated_before_minor: string; proceeds_minor: string; months_after: number;
  sequence: number; currency_code: string; currency_precision: number; plan_digest: string;
  validation_digest: string; preparer_actor_id: string; reviewer_actor_id: string | null; posting_effect_id: string | null;
  snapshot: { lines: { line_number: number; account_id: string; debit_minor: string; credit_minor: string; description: string }[] };
}
export interface AssetDetail extends AssetSummary { status: "PendingAcquisition" | "Active" | "Disposed"; carrying_minor: string; plans: AssetPlan[]; history_before: number | null }
const object = (value: unknown): value is Record<string, unknown> => value !== null && typeof value === "object" && !Array.isArray(value);
const text = (value: unknown): value is string => typeof value === "string" && value.length > 0 && value.length <= 500 && !/[\x00-\x1f\x7f]/.test(value);
const minor = (value: unknown): value is string => typeof value === "string" && /^(0|[1-9]\d{0,18})$/.test(value) && BigInt(value) <= 9000000000000000000n;
const integer = (value: unknown, maximum: number): value is number => typeof value === "number" && Number.isSafeInteger(value) && value >= 0 && value <= maximum;
const digest = (value: unknown) => typeof value === "string" && /^[0-9a-f]{64}$/.test(value);
const date = (value: unknown) => typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value) && Number.isFinite(Date.parse(value)) && new Date(value).toISOString().slice(0, 10) === value;
function invalid(): never { throw new Error("fixed_asset_contract_invalid"); }
function scoped(value: unknown, scope: FinanceScope): asserts value is Record<string, unknown> { if (!object(value) || Object.entries(scope).some(([key, expected]) => value[key] !== expected)) invalid(); }
export function parseAssetSummary(value: unknown, scope: FinanceScope): AssetSummary {
  scoped(value, scope);
  if (!["id", "asset_number", "name", "currency_code"].every(key => text(value[key])) || !digest(value.asset_digest) || !minor(value.cost_minor) || BigInt(value.cost_minor) <= 0n || !minor(value.salvage_minor) || BigInt(value.salvage_minor) >= BigInt(value.cost_minor) || !minor(value.accumulated_minor) || BigInt(value.accumulated_minor) > BigInt(value.cost_minor) - BigInt(value.salvage_minor) || !integer(value.useful_life_months, 1200) || value.useful_life_months < 1 || !integer(value.months, value.useful_life_months) || !integer(value.sequence, 1202) || !integer(value.currency_precision, 8) || !/^[A-Z]{3}$/.test(String(value.currency_code)) || typeof value.acquired !== "boolean" || typeof value.disposed !== "boolean" || (value.disposed && !value.acquired)) invalid();
  return value as unknown as AssetSummary;
}
export function parseAssetPlan(value: unknown, scope: FinanceScope): AssetPlan {
  scoped(value, scope);
  if (!["id", "asset_id", "entry_id", "preparer_actor_id", "currency_code", "posting_date", "period_id"].every(key => text(value[key])) || !digest(value.plan_digest) || !digest(value.validation_digest) || !["acquire", "depreciate", "dispose"].includes(String(value.kind)) || !integer(value.phase, 2) || ["Prepared", "Reviewed", "Posted"][value.phase] !== value.status || !integer(value.sequence, 1201) || !integer(value.months_after, 1200) || !integer(value.currency_precision, 8) || !["amount_minor", "accumulated_before_minor", "proceeds_minor"].every(key => minor(value[key])) || !object(value.snapshot) || !Array.isArray(value.snapshot.lines) || value.snapshot.lines.length < 2 || value.snapshot.lines.length > 5) invalid();
  if (value.phase === 0 ? value.reviewer_actor_id !== null : !text(value.reviewer_actor_id) || value.reviewer_actor_id === value.preparer_actor_id) invalid();
  if (value.phase === 2 ? !text(value.posting_effect_id) : value.posting_effect_id !== null) invalid();
  if (!date(value.posting_date) || !/^[A-Z]{3}$/.test(String(value.currency_code)) || !object(value.snapshot.entry)) invalid();
  const header = value.snapshot.entry;
  scoped(header, scope);
  for (const key of ["currency_code", "currency_precision", "posting_date", "period_id", "preparer_actor_id"])
    if (header[key] !== value[key]) invalid();
  if (header.id !== value.entry_id) invalid();
  let debit = 0n, credit = 0n;
  const accounts = new Set<string>();
  for (const [index, line] of value.snapshot.lines.entries()) {
    if (!object(line) || line.line_number !== index + 1 || !text(line.account_id) || accounts.has(line.account_id) || !minor(line.debit_minor) || !minor(line.credit_minor) || (BigInt(line.debit_minor) === 0n) === (BigInt(line.credit_minor) === 0n)) invalid();
    accounts.add(line.account_id); debit += BigInt(line.debit_minor); credit += BigInt(line.credit_minor);
  }
  if (debit !== credit || debit <= 0n || debit > 9000000000000000000n || (value.kind !== "dispose" && debit.toString() !== value.amount_minor)) invalid();
  return value as unknown as AssetPlan;
}
export function parseAssetDetail(value: unknown, scope: FinanceScope): AssetDetail {
  const summary = parseAssetSummary(value, scope);
  if (!object(value) || value.status !== (summary.disposed ? "Disposed" : summary.acquired ? "Active" : "PendingAcquisition") || !minor(value.carrying_minor) || BigInt(value.carrying_minor) !== (summary.disposed || !summary.acquired ? 0n : BigInt(summary.cost_minor) - BigInt(summary.accumulated_minor)) || !Array.isArray(value.plans) || value.plans.length > 25 || (value.history_before !== null && (!integer(value.history_before, 1201) || value.history_before < 1))) invalid();
  let last = -1;
  const plans = value.plans.map(row => { const plan = parseAssetPlan(row, scope); if (plan.asset_id !== summary.id || plan.sequence <= last) invalid(); last = plan.sequence; return plan; });
  return { ...summary, status: value.status, carrying_minor: value.carrying_minor, plans, history_before: value.history_before } as AssetDetail;
}
export async function assetRequest(session: BrowserAdminSession, scope: FinanceScope, path: string, command?: PreparedScopedCommand, signal?: AbortSignal): Promise<Record<string, unknown>> {
  const value = await financeRequest(session, scope, path, command?.body, signal); if (!object(value)) invalid(); return value;
}
