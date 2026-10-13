import { financeRequest, type FinanceScope } from "./enterprise-finance-data";
import { formatExactDecimal } from "./locale-format";
import type { PreparedScopedCommand } from "./scoped-command";
import type { BrowserAdminSession, Locale } from "./types";

export const adRoot = "/api/v1/accrual-deferral";
export const adPermissions: Record<string, string[]> = {
  read: ["accrual_deferral.read", "finance_core.read"],
  prepare: ["accrual_deferral.prepare", "finance_core.manage"],
  reverse: ["accrual_deferral.prepare", "finance_core.manage", "finance_core.reverse"],
  review: ["accrual_deferral.review", "finance_core.validate"],
  post: ["accrual_deferral.post", "finance_core.post"],
};
export type AdRecord = Record<string, unknown>;
export interface AdPolicy extends AdRecord { currency_code: string; currency_precision: number; currency_rounding_policy: "ROUND_HALF_UP"; currency_registry_version: string; currency_registry_digest: string }
export interface AdTranche extends AdRecord { id: string; period_id: string; posting_date: string; weight: string; amount_minor: string }
export interface AdPlan extends AdRecord, FinanceScope { id: string; source_id: string; source_digest: string; plan_digest: string; kind: "source" | "release" | "accrue" | "reverse" | "cancel"; phase: 0 | 1 | 2; status: "Prepared" | "Reviewed" | "Posted"; preparer_actor_id: string; reviewer_actor_id: string | null; posted_actor_id: string | null; posting_effect_id: string | null; original_plan_id: string | null; equation: AdRecord & { amount_minor?: string; native_effect_required: boolean }; command_request: AdRecord }
export interface AdSource extends AdRecord { id: string; source_digest: string; request: AdRecord & FinanceScope & { mode: string; amount_minor: string; currency_code: string; reference: string; tranches: AdTranche[] }; policy: AdPolicy; plans: AdPlan[]; claims: AdRecord[]; cancelled: boolean }
export interface AdEvidence extends AdRecord { source: AdSource; native_effects: AdRecord[]; qualified_scope: AdRecord }
export interface AdCatalog extends AdRecord { entity: AdRecord & { currency_code: string }; accounts: AdRecord[]; journals: AdRecord[]; periods: AdRecord[] }
export const adObject = (value: unknown): value is AdRecord => value !== null && typeof value === "object" && !Array.isArray(value);
const text = (value: unknown): value is string => typeof value === "string" && value.length > 0 && value.length <= 500 && !/[\x00-\x1f\x7f]/.test(value);
const seal = (value: unknown): value is string => typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
export const adMinor = (value: unknown): value is string => typeof value === "string" && /^-?(0|[1-9]\d{0,18})$/.test(value) && value !== "-0" && BigInt(value) >= -9000000000000000000n && BigInt(value) <= 9000000000000000000n;
function invalid(): never { throw new Error("accrual_deferral_source_invalid"); }
function scoped(value: AdRecord, scope: FinanceScope) { if (Object.entries(scope).some(([key, expected]) => value[key] !== expected)) invalid(); }
export function canonicalAd(value: unknown): string {
  let nodes = 0;
  const ancestors = new Set<object>();
  function encode(item: unknown, key = "", depth = 0): string {
    if (++nodes > 1_000_000 || depth > 32) invalid();
    if (key.endsWith("_minor") || key === "weight") { if (!adMinor(item) || key === "weight" && BigInt(item) <= 0n) invalid(); return item; }
    if (item === null || typeof item === "boolean" || typeof item === "string") return JSON.stringify(item);
    if (typeof item === "number") { if (!Number.isSafeInteger(item)) invalid(); return String(item); }
    if (typeof item !== "object" || ancestors.has(item)) invalid();
    ancestors.add(item);
    try { if (Array.isArray(item)) return `[${item.map(child => encode(child, "", depth + 1)).join(",")}]`;
      if (!adObject(item) || Object.getPrototypeOf(item) !== Object.prototype) invalid();
      return `{${Object.keys(item).sort().map(field => `${JSON.stringify(field)}:${encode(item[field], field, depth + 1)}`).join(",")}}`;
    } finally { ancestors.delete(item); }
  }
  const result = encode(value); if (new TextEncoder().encode(result).byteLength > 67_108_864) invalid(); return result;
}
export async function adHash(value: unknown): Promise<string> { return [...new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(canonicalAd(value))))].map(byte => byte.toString(16).padStart(2, "0")).join(""); }
export function adAmount(value: string, precision: number, locale: Locale): string {
  if (!adMinor(value) || !Number.isInteger(precision) || precision < 0 || precision > 8) invalid();
  const negative = value.startsWith("-"), digits = (negative ? value.slice(1) : value).padStart(precision + 1, "0");
  return formatExactDecimal(`${negative ? "-" : ""}${precision ? `${digits.slice(0, -precision)}.${digits.slice(-precision)}` : digits}`, locale);
}
function policy(value: unknown): asserts value is AdPolicy { if (!adObject(value) || !/^[A-Z]{3}$/.test(String(value.currency_code)) || !Number.isInteger(value.currency_precision) || Number(value.currency_precision) < 0 || Number(value.currency_precision) > 8 || value.currency_rounding_policy !== "ROUND_HALF_UP" || !text(value.currency_registry_version) || !seal(value.currency_registry_digest)) invalid(); }
export async function parseAdPlan(value: unknown, scope: FinanceScope): Promise<AdPlan> {
  if (!adObject(value) || value.schema_version !== "accrual-deferral-plan-v1" || !/^AD1R?-[a-f0-9]{32}$/.test(String(value.id)) || !/^AD1S-[a-f0-9]{32}$/.test(String(value.source_id)) || !seal(value.source_digest) || !seal(value.plan_digest) || !["source", "release", "accrue", "reverse", "cancel"].includes(String(value.kind)) || typeof value.phase !== "number" || ![0, 1, 2].includes(value.phase) || value.status !== ["Prepared", "Reviewed", "Posted"][value.phase] || !text(value.preparer_actor_id) || !adObject(value.equation) || !adObject(value.command_request)) invalid();
  scoped(value, scope); const phase = value.phase;
  if (phase === 0 ? value.reviewer_actor_id !== null : !text(value.reviewer_actor_id) || value.reviewer_actor_id === value.preparer_actor_id) invalid();
  if (phase === 2 ? !text(value.posted_actor_id) || [value.preparer_actor_id, value.reviewer_actor_id].includes(value.posted_actor_id) : value.posted_actor_id !== null) invalid();
  if ((value.kind === "reverse") !== String(value.id).startsWith("AD1R-") || value.kind === "reverse" && !text(value.original_plan_id) || value.kind !== "reverse" && value.original_plan_id !== null) invalid();
  const excluded = new Set(["phase", "status", "reviewer_actor_id", "posted_actor_id", "posting_effect_id", "plan_digest"]);
  if (await adHash(Object.fromEntries(Object.entries(value).filter(([key]) => !excluded.has(key)))) !== value.plan_digest) invalid();
  const equation = value.equation;
  if (typeof equation.native_effect_required !== "boolean" || !Array.isArray(equation.lines) || equation.lines.length > 2 || equation.operation !== value.kind) invalid();
  if (equation.native_effect_required) {
    if (!text(value.entry_id) || !seal(value.validation_digest) || !adObject(value.snapshot) || value.snapshot.schema_version !== "finance-entry-review-v1" || !adObject(value.snapshot.entry) || !Array.isArray(value.snapshot.lines) || value.snapshot.lines.length !== 2 || equation.lines.length !== 2) invalid();
    if (await adHash(value.snapshot) !== value.validation_digest) invalid(); const header = value.snapshot.entry; scoped(header, scope); policy(header);
    if (header.id !== value.entry_id || header.entry_number !== String(value.id).toUpperCase() || header.period_id !== value.period_id || header.posting_date !== value.posting_date || header.preparer_actor_id !== value.preparer_actor_id || header.source_type !== (value.kind === "reverse" ? "Generated" : "Manual")) invalid();
    let debit = 0n, credit = 0n;
    for (const [index, row] of value.snapshot.lines.entries()) { const expected = equation.lines[index];
      if (!adObject(row) || !adObject(expected) || row.line_number !== index + 1 || !text(row.account_id) || !adObject(row.dimensions) || Object.keys(row.dimensions).length > 8 || !adMinor(row.debit_minor) || !adMinor(row.credit_minor) || BigInt(row.debit_minor) < 0n || BigInt(row.credit_minor) < 0n || (BigInt(row.debit_minor) === 0n) === (BigInt(row.credit_minor) === 0n) || row.debit_minor !== expected.debit_minor || row.credit_minor !== expected.credit_minor) invalid();
      debit += BigInt(row.debit_minor); credit += BigInt(row.credit_minor);
    }
    if (debit !== credit || debit <= 0n || (phase === 2 ? !text(value.posting_effect_id) : value.posting_effect_id !== null)) invalid();
  } else if (equation.lines.length || value.snapshot !== null || value.entry_id !== null || value.validation_digest !== null || value.posting_effect_id !== null) invalid();
  return value as unknown as AdPlan;
}
export async function parseAdSource(value: unknown, scope: FinanceScope): Promise<AdSource> {
  if (!adObject(value) || value.schema_version !== "accrual-deferral-source-v1" || !/^AD1S-[a-f0-9]{32}$/.test(String(value.id)) || !seal(value.source_digest) || !adObject(value.request) || !adObject(value.equation) || !Array.isArray(value.plans) || value.plans.length < 1 || value.plans.length > 160 || !Array.isArray(value.claims) || typeof value.cancelled !== "boolean") invalid();
  scoped(value.request, scope); policy(value.policy); const request = value.request;
  if (!adMinor(request.amount_minor) || BigInt(request.amount_minor) <= 0n || request.currency_code !== value.policy.currency_code || !text(request.reference) || !["new_prepaid_voucher", "attach_paid_expense", "attach_prepaid_voucher", "expense_accrual"].includes(String(request.mode)) || request.allocation_policy !== "native-hamilton-stable-id-v1" || !Array.isArray(request.tranches) || request.tranches.length < 1 || request.tranches.length > 36 || !adObject(request.accounts) || new Set(Object.values(request.accounts)).size !== 4) invalid();
  let total = 0n; const ids = new Set<string>();
  for (const row of request.tranches) { if (!adObject(row) || !text(row.id) || ids.has(row.id) || !text(row.period_id) || !adMinor(row.weight) || BigInt(row.weight) <= 0n || !adMinor(row.amount_minor) || BigInt(row.amount_minor) <= 0n) invalid(); ids.add(row.id); total += BigInt(row.amount_minor); }
  if (total !== BigInt(request.amount_minor) || value.claims.length !== ids.size || new Set(value.claims.map(row => adObject(row) ? row.tranche_id : null)).size !== ids.size || value.claims.some(row => !adObject(row) || row.source_id !== value.id || !ids.has(String(row.tranche_id)))) invalid();
  const base = Object.fromEntries(Object.entries(value).filter(([key]) => !["plans", "claims", "cancelled", "source_digest"].includes(key)));
  if (await adHash(base) !== value.source_digest) invalid();
  const plans = await Promise.all(value.plans.map(row => parseAdPlan(row, scope)));
  if (new Set(plans.map(row => row.id)).size !== plans.length || plans.some(row => row.source_id !== value.id || row.source_digest !== value.source_digest) || plans.filter(row => row.kind === "source").length !== 1 || value.cancelled !== plans.some(row => row.kind === "cancel" && row.phase === 2)) invalid();
  if (!adObject(value.native_accounts) || Object.keys(value.native_accounts).length !== 4) invalid(); const accounts = Object.values(value.native_accounts);
  for (const plan of plans) { if (!plan.equation.native_effect_required) continue; if (!adObject(plan.snapshot) || !adObject(plan.snapshot.entry) || !Array.isArray(plan.snapshot.lines) || !Array.isArray(plan.equation.lines)) invalid();
    if (Object.entries(value.policy).some(([key, expected]) => (plan.snapshot as AdRecord).entry && ((plan.snapshot as AdRecord).entry as AdRecord)[key] !== expected)) invalid();
    for (const [index, line] of plan.snapshot.lines.entries()) { const expected = plan.equation.lines[index]; if (!adObject(line) || !adObject(expected)) invalid(); const matches = accounts.filter(account => adObject(account) && account.id === line.account_id && account.account_code === expected.account_code); if (matches.length !== 1 || canonicalAd(line.dimensions) !== canonicalAd(expected.dimensions)) invalid(); }
    if (plan.kind === "reverse") { const original = plans.find(row => row.id === plan.original_plan_id); if (!original || original.phase !== 2 || plan.equation.original_posting_effect_id !== original.posting_effect_id || plan.snapshot.entry.reverses_posting_id !== original.posting_effect_id) invalid(); }
    else if (plan.snapshot.entry.reverses_posting_id !== null) invalid();
  }
  return { ...value, plans } as unknown as AdSource;
}
export async function parseAdEvidence(value: unknown, scope: FinanceScope, tenant: string): Promise<AdEvidence> {
  if (!adObject(value) || value.schema_version !== "accrual-deferral-native-evidence-v1" || !adObject(value.qualified_scope) || value.qualified_scope.tenant_id !== tenant || !Array.isArray(value.native_effects) || value.native_effects.length > 161 || !seal(value.evidence_digest)) invalid();
  scoped(value.qualified_scope, scope); const source = await parseAdSource(value.source, scope), effects = value.native_effects;
  for (const field of ["account_pins", "calendar_pins", "claims", "commands", "phases", "original_claims", "original_releases", "financial_directory", "financial_directory_releases"] as const) { const rows = value[field]; if (!Array.isArray(rows) || rows.some(row => !adObject(row) || row.tenant_id !== tenant || Object.entries(scope).some(([key, expected]) => key in row && row[key] !== expected) || "source_id" in row && row.source_id !== source.id && field !== "financial_directory" && field !== "financial_directory_releases")) invalid(); }
  const phases = value.phases as AdRecord[], commands = value.commands as AdRecord[], phaseCount = source.plans.reduce((count, plan) => count + plan.phase + 1, 0);
  if (phases.length !== phaseCount || commands.length !== phaseCount || new Set(phases.map(row => `${row.plan_id}:${row.operation}`)).size !== phaseCount || new Set(commands.map(row => `${row.plan_id}:${row.operation}`)).size !== phaseCount) invalid();
  const audit = new Set<string>(), outbox = new Set<string>();
  for (const plan of source.plans) { for (let index = 0; index <= plan.phase; index++) { const operation = ["prepare", "review", "post"][index], actor = [plan.preparer_actor_id, plan.reviewer_actor_id, plan.posted_actor_id][index], phase = phases.find(row => row.plan_id === plan.id && row.operation === operation), command = commands.find(row => row.plan_id === plan.id && row.operation === operation);
    if (!phase || !command || phase.actor_id !== actor || command.actor_id !== actor || !text(phase.audit_event_id) || !text(phase.outbox_event_id) || audit.has(phase.audit_event_id) || outbox.has(phase.outbox_event_id) || phase.posting_effect_id !== (index === 2 ? plan.posting_effect_id : null) || !seal(command.request_digest) || await adHash(command.request_json) !== command.request_digest) invalid();
    audit.add(phase.audit_event_id); outbox.add(phase.outbox_event_id); const receipt = await parseAdPlan(command.response_json, scope); if (receipt.id !== plan.id || receipt.plan_digest !== plan.plan_digest || receipt.phase !== index) invalid();
  } }
  if (await adHash(Object.fromEntries(Object.entries(value).filter(([key]) => key !== "evidence_digest"))) !== value.evidence_digest || effects.some(row => !adObject(row) || row.tenant_id !== tenant || !text(row.id)) || new Set(effects.map(row => (row as AdRecord).id)).size !== effects.length) invalid();
  const used = new Set<string>();
  for (const plan of source.plans) { if (plan.phase !== 2 || !plan.equation.native_effect_required) continue;
    const matched = effects.filter(row => adObject(row) && row.id === plan.posting_effect_id); if (matched.length !== 1 || !adObject(matched[0])) invalid(); const effect = matched[0]; scoped(effect, scope);
    if (effect.entry_id !== plan.entry_id || effect.posted_actor_id !== plan.posted_actor_id || effect.validation_digest !== plan.validation_digest || canonicalAd(effect.snapshot) !== canonicalAd(plan.snapshot) || !text(effect.audit_event_id) || !text(effect.outbox_event_id) || Object.entries(source.policy).some(([key, expected]) => effect[key] !== expected)) invalid();
    if (effect.purpose !== "operational_posting" || effect.source_kind !== (plan.kind === "reverse" ? "Reversal" : "Manual") || effect.reverses_effect_id !== (plan.kind === "reverse" ? plan.equation.original_posting_effect_id : null) || effect.source_id !== (plan.kind === "reverse" ? effect.reverses_effect_id : plan.entry_id)) invalid();
    used.add(String(effect.id));
  }
  if (String(source.request.mode).startsWith("attach_")) { if (!adObject(source.equation) || !adObject(source.equation.external_original_membership)) invalid(); const original = source.equation.external_original_membership; const effect = effects.find(row => adObject(row) && row.id === source.request.original_effect_id); if (!adObject(effect) || effect.validation_digest !== original.original_validation_digest || canonicalAd(effect.snapshot) !== canonicalAd(original.original_snapshot)) invalid(); used.add(String(effect.id)); }
  if (used.size !== effects.length) invalid(); return { ...value, source } as AdEvidence;
}
export function parseAdCatalog(value: unknown, scope: FinanceScope): AdCatalog {
  if (!adObject(value) || value.schema_version !== "accrual-deferral-catalog-v1" || !adObject(value.scope) || !adObject(value.entity) || !text(value.entity.currency_code) || value.backend !== "postgresql" || value.statutory_country_packs !== 0) invalid(); scoped(value.scope, scope);
  for (const [field, max, key] of [["accounts", 1000, "account_code"], ["journals", 200, "journal_code"], ["periods", 200, "id"]] as const) { const rows = value[field]; if (!Array.isArray(rows) || rows.length > max || rows.some(row => !adObject(row) || !text(row[key])) || new Set(rows.map(row => (row as AdRecord)[key])).size !== rows.length) invalid(); }
  return value as AdCatalog;
}
export function adRequest(session: BrowserAdminSession, scope: FinanceScope, path: string, command?: PreparedScopedCommand, signal?: AbortSignal) { return financeRequest(session, scope, path, command?.body, signal); }
export async function parseAdAcknowledgement(command: PreparedScopedCommand, raw: unknown, scope: FinanceScope, actor: string): Promise<AdPlan> {
  if (!actor || !adObject(raw) || !command.path.startsWith(adRoot + "/")) invalid(); const plan = await parseAdPlan(raw.plan, scope), path = command.path.slice(adRoot.length), body = command.body;
  const phase = /^\/plans\/(AD1R?-[a-f0-9]{32})\/(review|post)$/.exec(path);
  if (phase) { if (plan.id !== phase[1] || plan.plan_digest !== body.expected_plan_digest || plan.phase !== (phase[2] === "review" ? 1 : 2) || plan[phase[2] === "review" ? "reviewer_actor_id" : "posted_actor_id"] !== actor) invalid(); }
  else { if (plan.phase !== 0 || plan.preparer_actor_id !== actor) invalid();
    if (path === "/sources") { if (plan.kind !== "source" || !adObject(plan.command_request.original_request)) invalid(); const request = plan.command_request.original_request;
      for (const [key, expected] of Object.entries(body).filter(([key]) => key !== "command_id")) { let retained = request[key];
        if (key === "tranches") { if (!Array.isArray(retained) || !Array.isArray(expected)) invalid(); const cleaned = retained.map(row => { if (!adObject(row)) invalid(); return Object.fromEntries(Object.entries(row).filter(([field]) => field !== "amount_minor")); }); const order = (a: unknown, b: unknown) => adObject(a) && adObject(b) ? `${a.posting_date}:${a.id}`.localeCompare(`${b.posting_date}:${b.id}`, "en") : invalid(); retained = cleaned.sort(order); if (canonicalAd(retained) !== canonicalAd([...expected].sort(order))) invalid(); }
        else if (canonicalAd({ [key]: retained }) !== canonicalAd({ [key]: expected })) invalid(); }
    } else { const route = /^\/sources\/(AD1S-[a-f0-9]{32})\/(tranches|reversals|cancellations)$/.exec(path); if (!route || plan.source_id !== route[1] || plan.kind !== ({ tranches: plan.equation.operation, reversals: "reverse", cancellations: "cancel" }[route[2]]) || route[2] === "tranches" && !["release", "accrue"].includes(plan.kind)) invalid();
      for (const [key, expected] of Object.entries(body).filter(([key]) => key !== "command_id")) if (canonicalAd({ [key]: plan.command_request[key] }) !== canonicalAd({ [key]: expected })) invalid(); }
  }
  return plan;
}
