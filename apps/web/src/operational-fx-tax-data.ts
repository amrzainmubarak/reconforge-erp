import { financeRequest, type FinanceScope } from "./enterprise-finance-data";
import type { PreparedScopedCommand } from "./scoped-command";
import type { BrowserAdminSession } from "./types";

export interface FxPolicy { currency_code: string; currency_precision: number; currency_rounding_policy: string; currency_registry_version: string; currency_registry_digest: string }
export interface FxRate { rate: string; source: string; effective_at: string }
export interface FxTax { rate: string; source: string; policy_id: string; version: string; country_code: string; transaction_class: string; effective_from: string; effective_to: string; account_code: string; policy_digest: string; foreign_tax_minor: string; functional_tax_minor: string }
export interface FxLine { account_id: string; line_number: number; debit_minor: string; credit_minor: string; description: string }
export interface FxPlan extends FinanceScope {
  id: string; source_id: string; entry_id: string; kind: "recognize" | "settle"; phase: number; status: "Prepared" | "Reviewed" | "Posted"; sequence: number;
  currency_code: string; currency_precision: number; posting_date: string; period_id: string; reason: string; amount_minor: string;
  preparer_actor_id: string; reviewer_actor_id: string | null; posting_effect_id: string | null; receipt_id: string | null;
  plan_digest: string; source_digest: string; validation_digest: string; snapshot: { entry: Record<string, unknown>; lines: FxLine[] };
  equation: { foreign_minor?: string; historical_release_minor?: string; functional_cash_minor?: string; realized_fx_minor?: string; settlement_rate?: FxRate };
}
export interface FxSource extends FinanceScope {
  id: string; invoice_id: string; source_digest: string; foreign_policy: FxPolicy; functional_policy: FxPolicy;
  request: { invoice_number: string; customer_code: string; posting_date: string; original_rate: FxRate; country_code: string; transaction_class: string };
  foreign_net_minor: string; foreign_tax_minor: string; foreign_gross_minor: string; functional_net_minor: string; functional_gross_minor: string; tax_components: FxTax[];
}
export interface FxDetail extends FxSource { foreign_outstanding_minor: string; functional_outstanding_minor: string; foreign_paid_minor: string; historical_released_minor: string; plans: FxPlan[] }
export interface FxEvidence { source: FxSource; plan: FxPlan; canonical_source_json: string; canonical_plan_json: string; canonical_snapshot_json: string; native_effect: null | { id: string; entry_id: string; posted_actor_id: string; validation_digest: string; audit_event_id: string; outbox_event_id: string }; phases: { action: string; actor_id: string; audit_event_id: string; outbox_event_id: string }[]; totals: { debit_minor: string; credit_minor: string } }

const object = (value: unknown): value is Record<string, unknown> => value !== null && typeof value === "object" && !Array.isArray(value);
const text = (value: unknown): value is string => typeof value === "string" && value.length > 0 && value.length <= 500 && !/[\x00-\x1f\x7f]/.test(value);
const minor = (value: unknown, signed = false): value is string => typeof value === "string" && (signed ? /^-?(0|[1-9]\d*)$/ : /^(0|[1-9]\d*)$/).test(value) && BigInt(value) >= (signed ? -9000000000000000000n : 0n) && BigInt(value) <= 9000000000000000000n;
const digest = (value: unknown) => typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
const integer = (value: unknown, max: number): value is number => typeof value === "number" && Number.isSafeInteger(value) && value >= 0 && value <= max;
function invalid(): never { throw new Error("fx_contract_invalid"); }
function scoped(value: unknown, scope: FinanceScope): asserts value is Record<string, unknown> {
  if (!object(value) || Object.entries(scope).some(([key, expected]) => value[key] !== expected)) invalid();
}
function policy(value: unknown): asserts value is Record<string, unknown> {
  if (!object(value) || !text(value.currency_code) || !/^[A-Z]{3}$/.test(value.currency_code) || !integer(value.currency_precision, 8) || value.currency_rounding_policy !== "ROUND_HALF_UP" || !text(value.currency_registry_version) || !digest(value.currency_registry_digest)) invalid();
}
export function parseFxSource(value: unknown, scope: FinanceScope): FxSource {
  scoped(value, scope); policy(value.foreign_policy); policy(value.functional_policy);
  if (value.schema_version !== "operational-fx-source-v1" || !text(value.id) || !text(value.invoice_id) || !digest(value.source_digest) || !object(value.request) || !Array.isArray(value.tax_components) || value.tax_components.length > 8 || value.foreign_policy.currency_code === value.functional_policy.currency_code || value.foreign_policy.currency_registry_digest !== value.functional_policy.currency_registry_digest) invalid();
  for (const key of ["foreign_net_minor", "foreign_tax_minor", "foreign_gross_minor", "functional_net_minor", "functional_gross_minor"]) if (!minor(value[key])) invalid();
  if (BigInt(value.foreign_net_minor as string) + BigInt(value.foreign_tax_minor as string) !== BigInt(value.foreign_gross_minor as string) || BigInt(value.foreign_gross_minor as string) <= 0n || BigInt(value.functional_gross_minor as string) <= 0n) invalid();
  const request = value.request;
  if (!["invoice_number", "customer_code", "posting_date", "country_code", "transaction_class"].every(key => text(request[key])) || !object(request.original_rate)) invalid();
  let foreignTax = 0n, functionalTax = 0n;
  for (const tax of value.tax_components) {
    if (!object(tax) || !["policy_id", "version", "source", "rate", "effective_from", "effective_to", "account_code"].every(key => text(tax[key])) || !digest(tax.policy_digest) || tax.country_code !== value.request.country_code || tax.transaction_class !== value.request.transaction_class || !minor(tax.foreign_tax_minor) || !minor(tax.functional_tax_minor)) invalid();
    foreignTax += BigInt(tax.foreign_tax_minor); functionalTax += BigInt(tax.functional_tax_minor);
  }
  if (foreignTax.toString() !== value.foreign_tax_minor || (BigInt(value.functional_net_minor as string) + functionalTax).toString() !== value.functional_gross_minor) invalid();
  return value as unknown as FxSource;
}
export function parseFxPlan(value: unknown, scope: FinanceScope): FxPlan {
  scoped(value, scope);
  if (value.schema_version !== "operational-fx-plan-v1" || !["id", "source_id", "entry_id", "currency_code", "preparer_actor_id", "posting_date", "period_id", "reason"].every(key => text(value[key])) || !["plan_digest", "source_digest", "validation_digest"].every(key => digest(value[key])) || !["recognize", "settle"].includes(String(value.kind)) || !integer(value.sequence, 200) || !integer(value.phase, 2) || ["Prepared", "Reviewed", "Posted"][value.phase] !== value.status || !integer(value.currency_precision, 8) || !minor(value.amount_minor) || !object(value.snapshot) || !Array.isArray(value.snapshot.lines) || value.snapshot.lines.length < 2 || value.snapshot.lines.length > 10 || !object(value.equation)) invalid();
  const header = value.snapshot.entry; scoped(header, scope);
  if (header.id !== value.entry_id || ["currency_code", "currency_precision", "posting_date", "period_id", "preparer_actor_id"].some(key => header[key] !== value[key])) invalid();
  if (value.phase === 0 ? value.reviewer_actor_id !== null : !text(value.reviewer_actor_id) || value.reviewer_actor_id === value.preparer_actor_id) invalid();
  if (value.phase === 2 ? !text(value.posting_effect_id) || (value.kind === "settle" ? !text(value.receipt_id) : value.receipt_id !== null) : value.posting_effect_id !== null || value.receipt_id !== null) invalid();
  let debit = 0n, credit = 0n;
  for (const [index, row] of value.snapshot.lines.entries()) {
    if (!object(row) || row.line_number !== index + 1 || !text(row.account_id) || !minor(row.debit_minor) || !minor(row.credit_minor) || (BigInt(row.debit_minor) === 0n) === (BigInt(row.credit_minor) === 0n)) invalid();
    debit += BigInt(row.debit_minor); credit += BigInt(row.credit_minor);
  }
  if (debit !== credit || debit.toString() !== value.amount_minor || debit <= 0n || debit > 9000000000000000000n) invalid();
  const equation = value.equation;
  if (value.kind === "settle" && (!["foreign_minor", "historical_release_minor", "functional_cash_minor"].every(key => minor(equation[key])) || !minor(equation.realized_fx_minor, true) || BigInt(equation.functional_cash_minor as string) - BigInt(equation.historical_release_minor as string) !== BigInt(equation.realized_fx_minor))) invalid();
  return value as unknown as FxPlan;
}
export function mergeFxPlan(current: FxPlan | null, acknowledgement: FxPlan): FxPlan {
  return current?.id === acknowledgement.id && current.phase > acknowledgement.phase ? current : acknowledgement;
}
export function parseFxDetail(value: unknown, scope: FinanceScope): FxDetail {
  const source = parseFxSource(value, scope); if (!object(value)) invalid();
  if (!["foreign_outstanding_minor", "functional_outstanding_minor", "foreign_paid_minor", "historical_released_minor"].every(key => minor(value[key])) || !Array.isArray(value.plans) || value.plans.length > 201 || BigInt(value.foreign_outstanding_minor as string) + BigInt(value.foreign_paid_minor as string) !== BigInt(source.foreign_gross_minor) || BigInt(value.functional_outstanding_minor as string) + BigInt(value.historical_released_minor as string) !== BigInt(source.functional_gross_minor)) invalid();
  const rows = value.plans;
  const plans = rows.map((row, index) => { const plan = parseFxPlan(row, scope); if (plan.source_id !== source.id || plan.source_digest !== source.source_digest || plan.sequence !== index || (index < rows.length - 1 && plan.phase !== 2)) invalid(); return plan; });
  return { ...value, plans } as unknown as FxDetail;
}
function canonical(value: unknown, key = ""): string {
  if (key.endsWith("_minor") && minor(value, true)) return value;
  if (Array.isArray(value)) return `[${value.map(row => canonical(row)).join(",")}]`;
  if (object(value)) return `{${Object.keys(value).sort().map(field => `${JSON.stringify(field)}:${canonical(value[field], field)}`).join(",")}}`;
  if (value === null || typeof value === "string" || typeof value === "boolean" || (typeof value === "number" && Number.isSafeInteger(value))) return JSON.stringify(value);
  return invalid();
}
async function sha256(value: string): Promise<string> {
  return [...new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value)))].map(byte => byte.toString(16).padStart(2, "0")).join("");
}
export async function verifyFxEvidence(value: unknown, scope: FinanceScope, expected: FxPlan): Promise<FxEvidence> {
  if (!object(value) || value.schema_version !== "operational-fx-native-evidence-v1" || !object(value.source) || !object(value.plan) || !object(value.totals) || !Array.isArray(value.phases)) invalid();
  const source = parseFxSource(value.source, scope), plan = parseFxPlan(value.plan, scope);
  if (source.id !== plan.source_id || source.source_digest !== plan.source_digest || expected.id !== plan.id || expected.plan_digest !== plan.plan_digest || expected.phase !== plan.phase || expected.posting_effect_id !== plan.posting_effect_id) invalid();
  const definition = Object.fromEntries(Object.entries(value.source).filter(([key]) => key !== "source_digest"));
  const retained = Object.fromEntries(Object.entries(value.plan).filter(([key]) => !["phase", "status", "reviewer_actor_id", "posting_effect_id", "receipt_id", "plan_digest", "validation_digest"].includes(key)));
  for (const [field, payload, hash] of [["canonical_source_json", definition, source.source_digest], ["canonical_plan_json", retained, plan.plan_digest], ["canonical_snapshot_json", plan.snapshot, plan.validation_digest]] as const) {
    const content = value[field]; if (typeof content !== "string" || content.length > 131072 || canonical(payload) !== content || await sha256(content) !== hash) invalid();
  }
  const native = value.native_effect;
  if (plan.phase === 2 ? !object(native) || native.id !== plan.posting_effect_id || native.entry_id !== plan.entry_id || native.validation_digest !== plan.validation_digest || !text(native.posted_actor_id) || [plan.preparer_actor_id, plan.reviewer_actor_id].includes(native.posted_actor_id) : native !== null) invalid();
  const actions = ["operational_fx_prepared", "operational_fx_reviewed", "operational_fx_posted", "finance_entry_posted"].slice(0, plan.phase === 2 ? 4 : plan.phase + 1);
  const actors = [plan.preparer_actor_id, plan.reviewer_actor_id, object(native) ? native.posted_actor_id : null], audit = new Set<string>(), outbox = new Set<string>();
  if (value.phases.length !== actions.length || value.totals.debit_minor !== plan.amount_minor || value.totals.credit_minor !== plan.amount_minor) invalid();
  for (const [index, row] of value.phases.entries()) {
    if (!object(row) || row.action !== actions[index] || row.actor_id !== actors[Math.min(index, 2)] || !text(row.audit_event_id) || !text(row.outbox_event_id) || audit.has(row.audit_event_id) || outbox.has(row.outbox_event_id)) invalid();
    audit.add(row.audit_event_id); outbox.add(row.outbox_event_id);
    if (index === 3 && object(native) && (row.audit_event_id !== native.audit_event_id || row.outbox_event_id !== native.outbox_event_id)) invalid();
  }
  return value as unknown as FxEvidence;
}
export async function fxRequest(session: BrowserAdminSession, scope: FinanceScope, path: string, command?: PreparedScopedCommand, signal?: AbortSignal): Promise<Record<string, unknown>> {
  const value = await financeRequest(session, scope, path, command?.body, signal); if (!object(value)) invalid(); return value;
}
