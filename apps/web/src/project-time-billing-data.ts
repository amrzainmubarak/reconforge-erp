import { financeRequest, type FinanceScope } from "./enterprise-finance-data";
import { object } from "./people-project-payroll-data";
import { formatExactDecimal } from "./locale-format";
import type { PreparedScopedCommand } from "./scoped-command";
import type { BrowserAdminSession, Locale } from "./types";

export const billingRoot = "/api/v1/project-time-billing";
export const billingPermissions: Record<string, string[]> = {
  read: ["project_time_billing.read"],
  evidence: ["project_time_billing.read", "finance_core.read", "people_project_payroll.read", "receivables.read"],
  manage: ["project_time_billing.manage", "receivables.read"], approve_price: ["project_time_billing.approve_price"],
  prepare: ["project_time_billing.prepare", "finance_core.manage", "receivables.manage", "people_project_payroll.read"],
  collect: ["project_time_billing.collect", "finance_core.manage", "receivables.receive"],
  review: ["project_time_billing.review", "finance_core.validate", "receivables.manage"],
  post: ["project_time_billing.post", "finance_core.post", "receivables.approve", "receivables.receive"],
};
export interface BillingPlan extends FinanceScope {
  id: string; schema_version: "project-invoice-v1" | "project-collection-v1"; phase: 0 | 1 | 2 | 3;
  status: "Prepared" | "Reviewed" | "Posted" | "Cancelled"; entry_id: string; ar_invoice_id: string; parent_id?: string;
  amount_minor: string; plan_digest: string; validation_digest: string; preparer_id: string; reviewer_id: string | null;
  posted_actor_id: string | null; posting_effect_id: string | null; receipt_id: string | null;
  monetary_policy: { currency_code: string; currency_precision: number; currency_rounding_policy: string;
    currency_registry_version: string; currency_registry_digest: string };
  calculation: { project_minor?: Record<string, string>; time_ids?: string[]; price_ids?: string[] } & Record<string, unknown>;
  command_request: Record<string, unknown>;
  snapshot: Record<string, unknown>;
}
function invalid(): never { throw new Error("project_billing_source_invalid"); }
const minor = (value: unknown): value is string => typeof value === "string" && /^(0|[1-9]\d{0,18})$/.test(value) && BigInt(value) <= 4500000000000000000n;
const hash = (value: unknown): value is string => typeof value === "string" && /^[0-9a-f]{64}$/.test(value);
export function billingAmount(value: string, precision: number, locale: Locale): string {
  if (!minor(value) || !Number.isInteger(precision) || precision < 0 || precision > 8) invalid();
  const exact = value.padStart(precision + 1, "0");
  return formatExactDecimal(precision ? exact.slice(0, -precision) + "." + exact.slice(-precision) : exact, locale);
}
export function canonicalBilling(value: unknown, key = ""): string {
  if (key.endsWith("_minor") && minor(value)) return value;
  if (Array.isArray(value)) return `[${value.map(item => canonicalBilling(item)).join(",")}]`;
  if (object(value)) return `{${Object.keys(value).sort().map(field => `${JSON.stringify(field)}:${canonicalBilling(value[field], key === "project_minor" ? "amount_minor" : field)}`).join(",")}}`;
  if (value === null || typeof value === "string" || typeof value === "boolean" || typeof value === "number" && Number.isSafeInteger(value)) return JSON.stringify(value);
  return invalid();
}
async function sha(value: unknown) {
  const raw = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(canonicalBilling(value)));
  return [...new Uint8Array(raw)].map(byte => byte.toString(16).padStart(2, "0")).join("");
}
export async function parseBillingPrice(value: unknown, scope: FinanceScope): Promise<Record<string, unknown> & { id: string }> {
  if (!object(value) || !/^PBP-[0-9a-f]{32}$/.test(String(value.id)) || !hash(value.source_digest) || !minor(value.hourly_price_minor) || BigInt(value.hourly_price_minor) <= 0n) invalid();
  for (const [key, expected] of Object.entries(scope)) if (value[key] !== expected) invalid();
  if (typeof value.preparer_id !== "string" || !value.preparer_id || (value.approver_id !== null && (typeof value.approver_id !== "string" || !value.approver_id || value.approver_id === value.preparer_id)) ||
      value.status !== (value.approver_id === null ? "Submitted" : "Approved")) invalid();
  const sealed = Object.fromEntries(Object.entries(value).filter(([key]) => !["status", "source_digest", "approver_id"].includes(key)));
  if (await sha(sealed) !== value.source_digest) invalid();
  return value as Record<string, unknown> & { id: string };
}
async function parsePlan(value: unknown, scope: FinanceScope, nativeEffects: unknown[] | null): Promise<BillingPlan> {
  if (!object(value) || !/^PB1C?-[0-9a-f]{32}$/.test(String(value.id)) || !hash(value.plan_digest) || !hash(value.validation_digest) || !minor(value.amount_minor) || BigInt(value.amount_minor) <= 0n ||
      typeof value.phase !== "number" || ![0, 1, 2, 3].includes(value.phase) || value.status !== ["Prepared", "Reviewed", "Posted", "Cancelled"][value.phase] ||
      !object(value.monetary_policy) || !object(value.calculation) || !object(value.snapshot) || !object(value.command_request)) invalid();
  for (const [key, expected] of Object.entries(scope)) if (value[key] !== expected) invalid();
  const collection = String(value.id).startsWith("PB1C-");
  if (value.schema_version !== (collection ? "project-collection-v1" : "project-invoice-v1") || collection && (value.phase === 3 || !/^PB1-[0-9a-f]{32}$/.test(String(value.parent_id)))) invalid();
  if (typeof value.preparer_id !== "string" || !value.preparer_id || typeof value.entry_id !== "string" || !value.entry_id || typeof value.ar_invoice_id !== "string" || !value.ar_invoice_id) invalid();
  if (value.phase === 0 ? value.reviewer_id !== null : [1, 2].includes(value.phase) && (typeof value.reviewer_id !== "string" || !value.reviewer_id || value.reviewer_id === value.preparer_id)) invalid();
  if (value.phase === 2 ? typeof value.posted_actor_id !== "string" || !value.posted_actor_id || [value.preparer_id, value.reviewer_id].includes(value.posted_actor_id) || typeof value.posting_effect_id !== "string" || !value.posting_effect_id : value.posted_actor_id !== null || value.posting_effect_id !== null) invalid();
  if (collection && value.phase === 2 ? typeof value.receipt_id !== "string" || !value.receipt_id : value.receipt_id !== null) invalid();
  const policy = value.monetary_policy;
  if (!/^[A-Z]{3}$/.test(String(policy.currency_code)) || !Number.isInteger(policy.currency_precision) || Number(policy.currency_precision) < 0 || Number(policy.currency_precision) > 8 ||
      policy.currency_rounding_policy !== "ROUND_HALF_UP" || !hash(policy.currency_registry_digest) || typeof policy.currency_registry_version !== "string" || !policy.currency_registry_version) invalid();
  if (value.calculation.amount_minor !== value.amount_minor) invalid();
  if (!collection) {
    if (!object(value.calculation.project_minor) || !Array.isArray(value.calculation.time_ids) || !value.calculation.time_ids.length || value.calculation.time_ids.length > 1000 ||
        new Set(value.calculation.time_ids).size !== value.calculation.time_ids.length || !Array.isArray(value.calculation.price_ids) || !value.calculation.price_ids.length) invalid();
    let sum = 0n; for (const amount of Object.values(value.calculation.project_minor)) { if (!minor(amount) || BigInt(amount) <= 0n) invalid(); sum += BigInt(amount); }
    if (sum !== BigInt(value.amount_minor)) invalid();
  }
  const excluded = new Set(["phase", "status", "reviewer_id", "posted_actor_id", "posting_effect_id", "receipt_id", "plan_digest"]);
  const sealed = Object.fromEntries(Object.entries(value).filter(([key]) => !excluded.has(key)));
  if (await sha(sealed) !== value.plan_digest || await sha(value.snapshot) !== value.validation_digest || !object(value.snapshot.entry)) invalid();
  const header = value.snapshot.entry;
  if (header.id !== value.entry_id || header.external_reference !== value.id || header.entry_number !== String(value.id).toUpperCase() || header.source_type !== "Manual" || header.reverses_posting_id !== null || header.preparer_actor_id !== value.preparer_id) invalid();
  for (const [key, expected] of [...Object.entries(scope), ...Object.entries(policy)]) if (header[key] !== expected) invalid();
  if (value.phase === 2 && nativeEffects !== null) {
    const effects = nativeEffects.filter(effect => object(effect) && effect.id === value.posting_effect_id);
    if (effects.length !== 1 || !object(effects[0])) invalid();
    const effect = effects[0];
    if (effect.entry_id !== value.entry_id || effect.posted_actor_id !== value.posted_actor_id || effect.validation_digest !== value.validation_digest || effect.source_kind !== "Manual" || effect.source_id !== value.entry_id || effect.reverses_effect_id !== null || !object(effect.snapshot)) invalid();
    for (const [key, expected] of [...Object.entries(scope), ...Object.entries(policy)]) if (effect[key] !== expected) invalid();
    if (await sha(effect.snapshot) !== value.validation_digest || canonicalBilling(effect.snapshot) !== canonicalBilling(value.snapshot)) invalid();
  }
  return value as unknown as BillingPlan;
}
export function parseBillingPlan(value: unknown, scope: FinanceScope, nativeEffects: unknown[] = []): Promise<BillingPlan> {
  return parsePlan(value, scope, nativeEffects);
}
export async function parseBillingAcknowledgement(command: PreparedScopedCommand, raw: unknown, scope: FinanceScope, actorId: string): Promise<
  { kind: "plan"; value: BillingPlan } | { kind: "price"; value: Record<string, unknown> & { id: string } }> {
  if (!object(raw) || !actorId) invalid();
  const path = command.path.slice(billingRoot.length), body = Object.fromEntries(Object.entries(command.body).filter(([key]) => key !== "command_id"));
  if (!command.path.startsWith(billingRoot + "/")) invalid();
  if (path === "/prices" || /^\/prices\/PBP-[a-f0-9]{32}\/approve$/.test(path)) {
    const value = await parseBillingPrice(raw.price, scope);
    if (path === "/prices") {
      if (value.approver_id !== null || value.preparer_id !== actorId || Object.entries(body).some(([key, expected]) => canonicalBilling({ [key]: value[key] }) !== canonicalBilling({ [key]: expected }))) invalid();
    } else if (value.id !== path.split("/")[2] || value.source_digest !== body.expected_digest || value.approver_id !== actorId || value.status !== "Approved") invalid();
    return { kind: "price", value };
  }
  // This validates ACK source hashes, never grants a native-effect proof.
  // The caller must independently verify the subsequent authoritative GET.
  const value = await parsePlan(raw.plan, scope, null), phase = /^\/plans\/(PB1C?-[a-f0-9]{32})\/(review|post|cancel)$/.exec(path);
  if (phase) {
    const expectedPhase = { review: 1, post: 2, cancel: 3 }[phase[2]];
    if (value.id !== phase[1] || value.plan_digest !== body.expected_plan_digest || value.phase !== expectedPhase ||
        phase[2] === "review" && value.reviewer_id !== actorId || phase[2] === "post" && value.posted_actor_id !== actorId) invalid();
  } else {
    const collection = /^\/invoices\/(PB1-[a-f0-9]{32})\/collections$/.exec(path);
    if (path !== "/invoices" && !collection || value.phase !== 0 || value.preparer_id !== actorId ||
        value.schema_version !== (collection ? "project-collection-v1" : "project-invoice-v1") || collection && value.parent_id !== collection[1] || !object(value.command_request)) invalid();
    const request = value.command_request;
    if (Object.entries(body).some(([key, expected]) => canonicalBilling({ [key]: request[key] }) !== canonicalBilling({ [key]: expected })) ||
        collection && request.invoice_id !== collection[1]) invalid();
  }
  return { kind: "plan", value };
}
export function billingRequest(session: BrowserAdminSession, scope: FinanceScope, path: string, command?: PreparedScopedCommand, signal?: AbortSignal) {
  return financeRequest(session, scope, path, command?.body, signal);
}
export async function parseBillingEvidence(value: unknown, scope: FinanceScope, tenantId: string): Promise<Record<string, unknown>> {
  if (!object(value) || value.schema_version !== "project-billing-evidence-v1" || !object(value.qualified_scope) || value.qualified_scope.tenant_id !== tenantId ||
      !Array.isArray(value.native_effects) || value.native_effects.length > 201 || !Array.isArray(value.collections) || value.collections.length > 200) invalid();
  for (const [key, expected] of Object.entries(scope)) if (value.qualified_scope[key] !== expected) invalid();
  const invoice = await parseBillingPlan(value.invoice, scope, value.native_effects);
  if (invoice.schema_version !== "project-invoice-v1") invalid();
  const sources = [invoice, ...await Promise.all(value.collections.map(row => parseBillingPlan(row, scope, value.native_effects as unknown[])))];
  if (new Set(sources.map(row => row.id)).size !== sources.length || sources.slice(1).some(row => row.parent_id !== invoice.id || row.ar_invoice_id !== invoice.ar_invoice_id)) invalid();
  const effects = value.native_effects;
  if (effects.some(row => !object(row) || typeof row.id !== "string") || new Set(effects.map(row => row.id)).size !== effects.length ||
      effects.length !== sources.filter(row => row.phase === 2).length) invalid();
  if (new TextEncoder().encode(JSON.stringify(value)).byteLength > 16_777_216) invalid();
  return value;
}
