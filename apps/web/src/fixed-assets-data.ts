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
  sequence: number; currency_code: string; currency_precision: number; plan_digest: string; asset_digest: string;
  validation_digest: string; preparer_actor_id: string; reviewer_actor_id: string | null; posting_effect_id: string | null;
  snapshot: { lines: { line_number: number; account_id: string; debit_minor: string; credit_minor: string; description: string }[] };
}
export interface AssetDetail extends AssetSummary { status: "PendingAcquisition" | "Active" | "Disposed"; carrying_minor: string; plans: AssetPlan[]; history_before: number | null }
export interface AssetEvidence {
  schema_version: "fixed-asset-native-evidence-v1"; plan: AssetPlan; asset_definition: Record<string, unknown>;
  canonical_asset_json: string; canonical_plan_json: string; canonical_snapshot_json: string;
  native_effect: { id: string; entry_id: string; validation_digest: string; posted_actor_id: string; posted_at: string; audit_event_id: string; outbox_event_id: string } | null;
  phases: { action: string; actor_id: string; audit_event_id: string; outbox_event_id: string }[];
  totals: { debit_minor: string; credit_minor: string };
}
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

function canonicalExact(value: unknown, key = ""): string {
  if (key.endsWith("_minor") && minor(value)) return value;
  if (Array.isArray(value)) return `[${value.map(item => canonicalExact(item)).join(",")}]`;
  if (object(value)) return `{${Object.keys(value).sort().map(field => `${JSON.stringify(field)}:${canonicalExact(value[field], field)}`).join(",")}}`;
  if (value === null || typeof value === "string" || typeof value === "boolean" || (typeof value === "number" && Number.isSafeInteger(value))) return JSON.stringify(value);
  return invalid();
}
async function sha256(value: string): Promise<string> {
  return [...new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value)))].map(byte => byte.toString(16).padStart(2, "0")).join("");
}
export async function verifyAssetEvidence(value: unknown, scope: FinanceScope, expected: AssetPlan): Promise<AssetEvidence> {
  if (!object(value) || value.schema_version !== "fixed-asset-native-evidence-v1" || !object(value.asset_definition) || !Array.isArray(value.phases) || !object(value.totals)) invalid();
  const plan = parseAssetPlan(value.plan, scope), asset = value.asset_definition;
  scoped(asset, scope);
  if (plan.id !== expected.id || plan.plan_digest !== expected.plan_digest || plan.phase !== expected.phase || plan.posting_effect_id !== expected.posting_effect_id || asset.id !== plan.asset_id || !digest(asset.asset_digest) || plan.asset_digest !== asset.asset_digest) invalid();
  const source = Object.fromEntries(Object.entries(asset).filter(([key]) => key !== "asset_digest"));
  const retained = Object.fromEntries(Object.entries(value.plan as Record<string, unknown>).filter(([key]) => !["phase", "status", "reviewer_actor_id", "posting_effect_id", "plan_digest", "validation_digest"].includes(key)));
  for (const [key, payload, expectedDigest] of [
    ["canonical_asset_json", source, asset.asset_digest], ["canonical_plan_json", retained, plan.plan_digest], ["canonical_snapshot_json", plan.snapshot, plan.validation_digest],
  ] as const) {
    const canonical = value[key];
    if (typeof canonical !== "string" || canonical.length > 65536 || canonicalExact(payload) !== canonical || await sha256(canonical) !== expectedDigest) invalid();
  }
  let debit = 0n, credit = 0n;
  for (const line of plan.snapshot.lines) { debit += BigInt(line.debit_minor); credit += BigInt(line.credit_minor); }
  if (value.totals.debit_minor !== debit.toString() || value.totals.credit_minor !== credit.toString()) invalid();
  const actions = ["fixed_asset_prepared", "fixed_asset_reviewed", "fixed_asset_posted", "finance_entry_posted"].slice(0, plan.phase === 2 ? 4 : plan.phase + 1);
  if (value.phases.length !== actions.length) invalid();
  const native = value.native_effect;
  if (plan.phase === 2) {
    if (!object(native) || !["id", "entry_id", "posted_actor_id", "posted_at", "audit_event_id", "outbox_event_id"].every(key => text(native[key])) || native.id !== plan.posting_effect_id || native.entry_id !== plan.entry_id || native.validation_digest !== plan.validation_digest || [plan.preparer_actor_id, plan.reviewer_actor_id].includes(String(native.posted_actor_id))) invalid();
  } else if (native !== null) invalid();
  const actors = [plan.preparer_actor_id, plan.reviewer_actor_id, object(native) ? native.posted_actor_id : null];
  const auditIds = new Set<string>(), outboxIds = new Set<string>();
  for (const [index, phase] of value.phases.entries()) {
    if (!object(phase) || phase.action !== actions[index] || phase.actor_id !== actors[Math.min(index, 2)] || !text(phase.audit_event_id) || !text(phase.outbox_event_id) || auditIds.has(phase.audit_event_id) || outboxIds.has(phase.outbox_event_id)) invalid();
    auditIds.add(phase.audit_event_id); outboxIds.add(phase.outbox_event_id);
    if (index === 3 && object(native) && (phase.audit_event_id !== native.audit_event_id || phase.outbox_event_id !== native.outbox_event_id)) invalid();
  }
  return value as unknown as AssetEvidence;
}
export async function assetRequest(session: BrowserAdminSession, scope: FinanceScope, path: string, command?: PreparedScopedCommand, signal?: AbortSignal): Promise<Record<string, unknown>> {
  const value = await financeRequest(session, scope, path, command?.body, signal); if (!object(value)) invalid(); return value;
}
