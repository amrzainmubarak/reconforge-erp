import { financeRequest, type FinanceScope } from "./enterprise-finance-data";
import type { PreparedScopedCommand } from "./scoped-command";
import type { BrowserAdminSession } from "./types";

export const partialReturnsRoot = "/api/v1/customer-partial-returns";
export const partialReturnsRootV2 = "/api/v2/customer-partial-returns";
export const partialAllocationPolicy = "remaining-original-v1";
export const partialReturnPermissions = {
  read: ["sales.read", "receivables.read", "inventory.read", "finance_core.read"],
  prepare: ["sales.read", "receivables.read", "inventory.read", "finance_core.read", "sales.manage", "receivables.manage", "inventory.valuation.manage", "finance_core.manage", "finance_core.reverse"],
  review: ["sales.read", "receivables.read", "inventory.read", "finance_core.read", "sales.approve", "inventory.valuation.approve", "finance_core.validate", "finance_core.reverse"],
  post: ["sales.read", "receivables.read", "inventory.read", "finance_core.read", "sales.manage", "receivables.manage", "inventory.post", "inventory.valuation.approve", "finance_core.post", "finance_core.reverse"],
  cancel: ["sales.read", "receivables.read", "inventory.read", "finance_core.read", "sales.approve", "finance_core.validate"],
} as const;
interface CapturedPolicy {
  currency_code: string; currency_precision: number; currency_rounding_policy: "ROUND_HALF_UP";
  currency_registry_version: string; currency_registry_digest: string;
}
export interface PartialReturnEntry { entry_id: string; purpose: string; validation_digest: string; posting_effect_id: string | null }
export interface PartialReturnPlan extends FinanceScope, CapturedPolicy {
  schema_version: "customer-partial-return-v1"; id: string; operation: "Return" | "Refund" | "ReverseReturn" | "ReverseRefund";
  phase: 0 | 1 | 2 | 3; status: "Prepared" | "Reviewed" | "Posted" | "Cancelled"; plan_digest: string;
  source_id: string; source_order_id: string; invoice_id: string; quantity_precision: number; quantity_scaled: string;
  credit_minor: string; cogs_restored_minor: string; receivable_released_minor: string; refund_entitlement_delta_minor: string;
  amount_minor: string; expected_history_version: number; posting_date: string; period_id: string;
  preparer_actor_id: string; reviewer_actor_id: string | null; poster_actor_id: string | null; original_id: string | null;
  entries: PartialReturnEntry[]; audit_event_id: string; outbox_event_id: string;
}
export interface PartialReturnBalance extends FinanceScope, CapturedPolicy {
  source_order_id: string; source_id: string | null; source_fingerprint: string; history_fingerprint: string; history_version: number;
  gross_minor: string; collected_minor: string; credited_minor: string; returned_quantity_scaled: string; remaining_quantity_scaled: string;
  quantity_precision: number; refund_entitlement_minor: string; refunded_minor: string; refund_due_minor: string;
  outstanding_minor: string; active_plan_id: string | null;
}
export type PartialReturnPlanV2 = Omit<PartialReturnPlan, "schema_version"> & {
  schema_version: "customer-partial-return-v2"; allocation_policy: typeof partialAllocationPolicy;
};
export type PartialReturnBalanceV2 = PartialReturnBalance & {
  schema_version: "customer-partial-return-balance-v2"; allocation_policy: typeof partialAllocationPolicy;
};
export type AnyPartialReturnPlan = PartialReturnPlan | PartialReturnPlanV2;
export type AnyPartialReturnBalance = PartialReturnBalance | PartialReturnBalanceV2;
const max = 9_000_000_000_000_000_000n;
const policyKeys = ["currency_code", "currency_precision", "currency_rounding_policy", "currency_registry_version", "currency_registry_digest"];
const scopeKeys = ["workspace_id", "organization_id", "legal_entity_id"];
const planKeys = [...scopeKeys, ...policyKeys, "schema_version", "id", "operation", "phase", "status", "plan_digest", "source_id", "source_order_id", "invoice_id", "quantity_precision", "quantity_scaled", "credit_minor", "cogs_restored_minor", "receivable_released_minor", "refund_entitlement_delta_minor", "amount_minor", "expected_history_version", "posting_date", "period_id", "preparer_actor_id", "reviewer_actor_id", "poster_actor_id", "original_id", "entries", "audit_event_id", "outbox_event_id"];
const balanceKeys = [...scopeKeys, ...policyKeys, "source_order_id", "source_id", "source_fingerprint", "history_fingerprint", "history_version", "gross_minor", "collected_minor", "credited_minor", "returned_quantity_scaled", "remaining_quantity_scaled", "quantity_precision", "refund_entitlement_minor", "refunded_minor", "refund_due_minor", "outstanding_minor", "active_plan_id"];
const prefixes = { Return: "CR2", Refund: "CRF2", ReverseReturn: "CR2R", ReverseRefund: "CRF2R" } as const;
const purposes = { Return: ["RevenueCredit", "CostRestoration"], Refund: ["Refund"], ReverseReturn: ["ReverseRevenueCredit", "ReverseCostRestoration"], ReverseRefund: ["ReverseRefund"] } as const;
function invalid(): never { throw new Error("customer_partial_return_response_invalid"); }
function object(value: unknown, keys: readonly string[]): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) invalid();
  const row = value as Record<string, unknown>;
  if (Object.keys(row).length !== keys.length || keys.some(key => !Object.hasOwn(row, key)) || Object.keys(row).some(key => !keys.includes(key))) invalid();
  return row;
}
function text(value: unknown, maximum = 160): string {
  if (typeof value !== "string" || !value.length || value.length > maximum || value !== value.trim() || /[\x00-\x1f\x7f]/.test(value)) invalid();
  return value;
}
function nullableText(value: unknown): string | null { return value === null ? null : text(value); }
function integer(value: unknown, maximum = 2_147_483_647): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 0 || value > maximum) invalid(); return value;
}
export function partialMinor(value: unknown, positive = false): string {
  if (typeof value !== "string" || !/^(0|[1-9]\d{0,18})$/.test(value) || BigInt(value) > max || (positive && value === "0")) invalid(); return value;
}
function digest(value: unknown): string { if (typeof value !== "string" || !/^[a-f0-9]{64}$/.test(value)) invalid(); return value; }
function identity(value: unknown, prefix: string): string { const id = text(value); if (!new RegExp(`^${prefix}-[a-f0-9]{32}$`).test(id)) invalid(); return id; }
function businessDate(value: unknown): void {
  if (typeof value !== "string" || !/^[0-9]{4}-[0-9]{2}-[0-9]{2}$/.test(value)) invalid();
  const year = Number(value.slice(0, 4)), month = Number(value.slice(5, 7)), day = Number(value.slice(8, 10));
  const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  const days = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  if (year < 1 || month < 1 || month > 12 || day < 1 || day > days[month - 1]) invalid();
}
function policy(row: Record<string, unknown>, scope: FinanceScope): void {
  for (const key of scopeKeys) if (text(row[key]) !== scope[key as keyof FinanceScope]) invalid();
  if (!/^[A-Z]{3}$/.test(text(row.currency_code)) || row.currency_rounding_policy !== "ROUND_HALF_UP") invalid();
  integer(row.currency_precision, 8); text(row.currency_registry_version); digest(row.currency_registry_digest);
}
function parsePlan(value: unknown, scope: FinanceScope, remainder: boolean): AnyPartialReturnPlan {
  const row = object(value, remainder ? [...planKeys, "allocation_policy"] : planKeys); policy(row, scope);
  if (row.schema_version !== (remainder ? "customer-partial-return-v2" : "customer-partial-return-v1") || typeof row.operation !== "string" || !Object.hasOwn(prefixes, row.operation)) invalid();
  if (remainder && row.allocation_policy !== partialAllocationPolicy) invalid();
  const operation = row.operation as PartialReturnPlan["operation"];
  identity(row.id, prefixes[operation]); identity(row.source_id, "CRS2"); text(row.source_order_id); text(row.invoice_id);
  digest(row.plan_digest); integer(row.expected_history_version, 255); integer(row.quantity_precision, 6);
  const phase = integer(row.phase, 3); if (["Prepared", "Reviewed", "Posted", "Cancelled"][phase] !== row.status) invalid();
  text(row.period_id); businessDate(row.posting_date);
  text(row.preparer_actor_id); nullableText(row.reviewer_actor_id); nullableText(row.poster_actor_id);
  if (row.reviewer_actor_id !== null && row.reviewer_actor_id === row.preparer_actor_id || phase === 0 && row.reviewer_actor_id !== null) invalid();
  if ([1, 2].includes(phase) && (!row.reviewer_actor_id || row.reviewer_actor_id === row.preparer_actor_id)) invalid();
  if (phase === 2 ? !row.poster_actor_id || [row.preparer_actor_id, row.reviewer_actor_id].includes(row.poster_actor_id) : row.poster_actor_id !== null) invalid();
  const merchandise = operation === "Return" || operation === "ReverseReturn";
  for (const key of ["quantity_scaled", "credit_minor", "cogs_restored_minor", "receivable_released_minor", "refund_entitlement_delta_minor", "amount_minor"]) partialMinor(row[key], key === "amount_minor" && !(remainder && merchandise));
  if (merchandise) {
    partialMinor(row.quantity_scaled, true); partialMinor(row.credit_minor, !remainder); partialMinor(row.cogs_restored_minor, !remainder);
    if (BigInt(String(row.credit_minor)) !== BigInt(String(row.receivable_released_minor)) + BigInt(String(row.refund_entitlement_delta_minor)) ||
        BigInt(String(row.amount_minor)) !== BigInt(String(row.credit_minor)) + BigInt(String(row.cogs_restored_minor))) invalid();
  } else if (["quantity_scaled", "credit_minor", "cogs_restored_minor", "receivable_released_minor", "refund_entitlement_delta_minor"].some(key => row[key] !== "0")) invalid();
  if (operation === "Return") { if (row.original_id !== null) invalid(); }
  else identity(row.original_id, operation === "ReverseRefund" ? "CRF2" : "CR2");
  const expectedPurposes = purposes[operation].filter((_purpose, index) => !remainder || !merchandise || row[index === 0 ? "credit_minor" : "cogs_restored_minor"] !== "0");
  if (!Array.isArray(row.entries) || row.entries.length !== expectedPurposes.length) invalid();
  const entries = row.entries.map((item, index) => {
    const entry = object(item, ["entry_id", "purpose", "validation_digest", "posting_effect_id"]);
    text(entry.entry_id); if (entry.purpose !== expectedPurposes[index]) invalid(); digest(entry.validation_digest); nullableText(entry.posting_effect_id);
    if ((phase === 2) !== (entry.posting_effect_id !== null)) invalid(); return entry as unknown as PartialReturnEntry;
  });
  if (new Set(entries.map(entry => entry.entry_id)).size !== entries.length || (phase === 2 && new Set(entries.map(entry => entry.posting_effect_id)).size !== entries.length)) invalid();
  text(row.audit_event_id); text(row.outbox_event_id);
  return { ...row, entries } as unknown as AnyPartialReturnPlan;
}
export function parsePartialReturnPlan(value: unknown, scope: FinanceScope): PartialReturnPlan {
  return parsePlan(value, scope, false) as PartialReturnPlan;
}
export function parsePartialReturnPlanV2(value: unknown, scope: FinanceScope): PartialReturnPlanV2 {
  return parsePlan(value, scope, true) as PartialReturnPlanV2;
}
export function parsePartialReturnPlanUnion(value: unknown, scope: FinanceScope): AnyPartialReturnPlan {
  return value && typeof value === "object" && (value as Record<string, unknown>).schema_version === "customer-partial-return-v2"
    ? parsePartialReturnPlanV2(value, scope) : parsePartialReturnPlan(value, scope);
}
function parseBalance(value: unknown, scope: FinanceScope, sourceOrderId: string, remainder: boolean): AnyPartialReturnBalance {
  const row = object(value, remainder ? [...balanceKeys, "schema_version", "allocation_policy"] : balanceKeys); policy(row, scope);
  if (remainder && (row.schema_version !== "customer-partial-return-balance-v2" || row.allocation_policy !== partialAllocationPolicy)) invalid();
  if (text(row.source_order_id) !== text(sourceOrderId)) invalid();
  if (row.source_id !== null) identity(row.source_id, "CRS2");
  digest(row.source_fingerprint); digest(row.history_fingerprint); integer(row.history_version, 256); integer(row.quantity_precision, 6);
  if (row.active_plan_id !== null && !/^CR(?:2|F2|2R|F2R)-[a-f0-9]{32}$/.test(text(row.active_plan_id))) invalid();
  if (row.source_id === null && (row.history_version !== 0 || row.active_plan_id !== null)) invalid();
  for (const key of ["gross_minor", "collected_minor", "credited_minor", "returned_quantity_scaled", "remaining_quantity_scaled", "refund_entitlement_minor", "refunded_minor", "refund_due_minor", "outstanding_minor"]) partialMinor(row[key], key === "gross_minor");
  const gross = BigInt(String(row.gross_minor)), collected = BigInt(String(row.collected_minor)), credited = BigInt(String(row.credited_minor));
  const residual = gross - collected - credited, entitlement = collected + credited - gross;
  if (collected > gross || credited > gross || row.outstanding_minor !== (residual > 0n ? residual : 0n).toString() ||
      row.refund_entitlement_minor !== (entitlement > 0n ? entitlement : 0n).toString() ||
      BigInt(String(row.refund_due_minor)) + BigInt(String(row.refunded_minor)) !== BigInt(String(row.refund_entitlement_minor))) invalid();
  return row as unknown as AnyPartialReturnBalance;
}
export function parsePartialReturnBalance(value: unknown, scope: FinanceScope, sourceOrderId: string): PartialReturnBalance {
  return parseBalance(value, scope, sourceOrderId, false) as PartialReturnBalance;
}
export function parsePartialReturnBalanceV2(value: unknown, scope: FinanceScope, sourceOrderId: string): PartialReturnBalanceV2 {
  return parseBalance(value, scope, sourceOrderId, true) as PartialReturnBalanceV2;
}
export function parsePartialReturnBalanceUnion(value: unknown, scope: FinanceScope, sourceOrderId: string): AnyPartialReturnBalance {
  return value && typeof value === "object" && (value as Record<string, unknown>).schema_version === "customer-partial-return-balance-v2"
    ? parsePartialReturnBalanceV2(value, scope, sourceOrderId) : parsePartialReturnBalance(value, scope, sourceOrderId);
}
function matchesCommand(plan: AnyPartialReturnPlan, command: PreparedScopedCommand, root: string): boolean {
  if (command.body.expected_plan_digest !== undefined && plan.plan_digest !== command.body.expected_plan_digest) return false;
  if (command.body.expected_history_version !== undefined && plan.expected_history_version !== command.body.expected_history_version) return false;
  if (command.path === `${root}/plans`) return plan.operation === "Return" && plan.phase === 0 && plan.source_order_id === command.body.source_order_id && plan.quantity_scaled === command.body.quantity_scaled;
  if (command.path.endsWith("/refunds")) return plan.operation === "Refund" && plan.phase === 0 && plan.amount_minor === command.body.amount_minor && command.path === `${root}/plans/${plan.original_id}/refunds`;
  if (command.path.endsWith("/reversals")) return plan.operation.startsWith("Reverse") && plan.phase === 0 && command.path === `${root}/plans/${plan.original_id}/reversals`;
  for (const [action, phase] of [["review", 1], ["post", 2], ["cancel", 3]] as const) if (command.path === `${root}/plans/${plan.id}/${action}`) return plan.phase === phase;
  return false;
}
export function partialPlanMatchesCommand(plan: PartialReturnPlan, command: PreparedScopedCommand): boolean {
  return matchesCommand(plan, command, partialReturnsRoot);
}
export function partialPlanMatchesCommandUnion(plan: AnyPartialReturnPlan, command: PreparedScopedCommand): boolean {
  return matchesCommand(plan, command, plan.schema_version === "customer-partial-return-v2" ? partialReturnsRootV2 : partialReturnsRoot);
}
async function request(session: BrowserAdminSession, scope: FinanceScope, path: string, root: string, command?: PreparedScopedCommand, signal?: AbortSignal): Promise<Record<string, unknown>> {
  const id = "CR(?:2|F2|2R|F2R)-[a-f0-9]{32}";
  let sourceBalance = false;
  const source = new RegExp(`^${root}/sources/([^/?#]+)/balance$`).exec(path);
  if (!command && source) {
    try { const decoded = text(decodeURIComponent(source[1])); sourceBalance = ![".", ".."].includes(decoded) && !/[\\/?#]/.test(decoded) && encodeURIComponent(decoded) === source[1]; }
    catch { invalid(); }
  }
  const allowed = command ? path === `${root}/plans` || new RegExp(`^${root}/plans/${id}/(?:review|post|cancel)$`).test(path) || new RegExp(`^${root}/plans/CR2-[a-f0-9]{32}/refunds$`).test(path) || new RegExp(`^${root}/plans/CR(?:2|F2)-[a-f0-9]{32}/reversals$`).test(path) : path === `${root}/plans` || new RegExp(`^${root}/plans/${id}$`).test(path) || sourceBalance;
  if (!allowed || (command && command.path !== path)) invalid();
  const result = await financeRequest(session, scope, path, command?.body, signal);
  return object(result, [!command && path === `${root}/plans` ? "plans" : path.includes("/sources/") ? "balance" : "plan"]);
}
export async function partialReturnRequest(session: BrowserAdminSession, scope: FinanceScope, path: string, command?: PreparedScopedCommand, signal?: AbortSignal): Promise<Record<string, unknown>> {
  return request(session, scope, path, partialReturnsRoot, command, signal);
}
export async function partialReturnRequestV2(session: BrowserAdminSession, scope: FinanceScope, path: string, command?: PreparedScopedCommand, signal?: AbortSignal): Promise<Record<string, unknown>> {
  return request(session, scope, path, partialReturnsRootV2, command, signal);
}
