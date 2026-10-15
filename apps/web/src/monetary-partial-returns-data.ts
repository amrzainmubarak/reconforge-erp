import type { FinanceScope } from "./enterprise-finance-data";
import { monetaryPartialRoot } from "./monetary-paths";
import { monetaryBalanceFields, monetaryDate, monetaryDigest, monetaryInteger, monetaryInvalid, monetaryMinor, monetaryNullableText,
  monetaryObject, monetaryRequest, monetaryScope, monetaryText, parseMonetaryPolicyPair, validateMonetaryBalance,
  type MonetaryBalanceFields, type MonetaryPolicy } from "./monetary-public-data";
import type { PreparedScopedCommand } from "./scoped-command";
import type { BrowserAdminSession } from "./types";

export const monetaryAmountFields = ["transaction_net_minor", "transaction_tax_minor", "transaction_credit_minor", "functional_net_minor", "functional_tax_minor", "functional_credit_minor",
  "functional_cost_minor", "transaction_receivable_released_minor", "functional_receivable_released_minor", "transaction_refund_delta_minor", "functional_refund_delta_minor",
  "transaction_refund_minor", "functional_refund_released_minor", "functional_cash_minor", "functional_fx_gain_minor", "functional_fx_loss_minor", "functional_alignment_gain_minor",
  "functional_alignment_loss_minor", "functional_turnover_minor"] as const;
export type MonetaryAmounts = Record<typeof monetaryAmountFields[number], string>;
export type MonetaryPartialOperation = "Return" | "Refund" | "ReverseReturn" | "ReverseRefund";
export interface MonetaryPartialEntry { purpose: string; entry_id: string; posting_effect_id: string | null; validation_digest: string }
export interface MonetaryPartialPlan extends FinanceScope {
  schema_version: "customer-partial-return-monetary-v3"; id: string; source_id: string; source_order_id: string; invoice_id: string;
  operation: MonetaryPartialOperation; status: "Prepared" | "Reviewed" | "Posted" | "Cancelled"; phase: 0 | 1 | 2 | 3;
  quantity_scaled: string; quantity_precision: number; period_id: string; posting_date: string; reason: string;
  source_fingerprint: string; history_fingerprint: string; expected_history_version: number; plan_digest: string;
  allocation_policy: "remaining-dual-currency-v1"; transaction_policy: MonetaryPolicy; functional_policy: MonetaryPolicy; monetary: MonetaryAmounts;
  entries: MonetaryPartialEntry[]; movement_id: string | null; original_id: string | null;
  preparer_actor_id: string; reviewer_actor_id: string | null; posted_actor_id: string | null; cancelled_actor_id: string | null;
}
export interface MonetaryPartialBalance extends MonetaryBalanceFields, FinanceScope {
  schema_version: "customer-partial-return-monetary-balance-v3"; source_id: string; source_order_id: string; invoice_id: string; source_fingerprint: string;
  transaction_policy: MonetaryPolicy; functional_policy: MonetaryPolicy; quantity_precision: number;
  original_quantity_scaled: string; returned_quantity_scaled: string; remaining_quantity_scaled: string;
}
const planFields = ["schema_version", "id", "workspace_id", "organization_id", "legal_entity_id", "source_id", "source_order_id", "invoice_id", "operation", "status", "phase",
  "quantity_scaled", "quantity_precision", "period_id", "posting_date", "reason", "source_fingerprint", "history_fingerprint", "expected_history_version", "plan_digest", "allocation_policy",
  "transaction_policy", "functional_policy", "monetary", "entries", "movement_id", "original_id", "preparer_actor_id", "reviewer_actor_id", "posted_actor_id", "cancelled_actor_id"] as const;
const balanceFields = [...monetaryBalanceFields, "workspace_id", "organization_id", "legal_entity_id", "source_id", "source_order_id", "invoice_id", "source_fingerprint",
  "transaction_policy", "functional_policy", "quantity_precision", "original_quantity_scaled", "returned_quantity_scaled", "remaining_quantity_scaled"] as const;
const prefixes = { Return: "CR3", Refund: "CRF3", ReverseReturn: "CR3R", ReverseRefund: "CRF3R" } as const;
function identifier(value: unknown, prefix: string): string {
  const id = monetaryText(value);
  if (!new RegExp(`^${prefix}-[a-f0-9]{32}$`).test(id)) monetaryInvalid();
  return id;
}
export function parseMonetaryPartialPlan(value: unknown, scope: FinanceScope): MonetaryPartialPlan {
  const row = monetaryObject(value, planFields); monetaryScope(row, scope);
  if (row.schema_version !== "customer-partial-return-monetary-v3" || row.allocation_policy !== "remaining-dual-currency-v1"
      || typeof row.operation !== "string" || !Object.hasOwn(prefixes, row.operation)) monetaryInvalid();
  const operation = row.operation as MonetaryPartialOperation, isReturn = operation === "Return" || operation === "ReverseReturn";
  identifier(row.id, prefixes[operation]);
  for (const key of ["source_id", "source_order_id", "invoice_id", "period_id", "preparer_actor_id"]) monetaryText(row[key]);
  monetaryText(row.reason, 500); monetaryDate(row.posting_date);
  for (const key of ["source_fingerprint", "history_fingerprint", "plan_digest"]) monetaryDigest(row[key]);
  for (const key of ["movement_id", "reviewer_actor_id", "posted_actor_id", "cancelled_actor_id"]) monetaryNullableText(row[key]);
  const phase = monetaryInteger(row.phase, 3); monetaryInteger(row.expected_history_version, 255); monetaryInteger(row.quantity_precision, 6);
  if (["Prepared", "Reviewed", "Posted", "Cancelled"][phase] !== row.status) monetaryInvalid();
  monetaryMinor(row.quantity_scaled, isReturn);
  if (!isReturn && row.quantity_scaled !== "0" || (row.movement_id !== null) !== (phase === 2 && isReturn)
      || (row.posted_actor_id !== null) !== (phase === 2) || (row.cancelled_actor_id !== null) !== (phase === 3)
      || [1, 2].includes(phase) && row.reviewer_actor_id === null || phase === 0 && row.reviewer_actor_id !== null
      || row.reviewer_actor_id !== null && row.reviewer_actor_id === row.preparer_actor_id
      || phase === 2 && [row.preparer_actor_id, row.reviewer_actor_id].includes(row.posted_actor_id)) monetaryInvalid();
  if (operation === "Return") { if (row.original_id !== null) monetaryInvalid(); }
  else if (identifier(row.original_id, operation === "ReverseRefund" ? "CRF3" : "CR3") === row.id) monetaryInvalid();
  [row.transaction_policy, row.functional_policy] = parseMonetaryPolicyPair(row.transaction_policy, row.functional_policy);
  const identity = (row.transaction_policy as MonetaryPolicy).currency_code === (row.functional_policy as MonetaryPolicy).currency_code;
  const amounts = monetaryObject(row.monetary, monetaryAmountFields);
  for (const key of monetaryAmountFields) monetaryMinor(amounts[key]);
  const number = (key: typeof monetaryAmountFields[number]) => BigInt(amounts[key] as string);
  if (number("functional_fx_gain_minor") > 0n && number("functional_fx_loss_minor") > 0n
      || number("functional_alignment_gain_minor") > 0n && number("functional_alignment_loss_minor") > 0n) monetaryInvalid();
  let purposes: string[];
  if (isReturn) {
    if (["transaction_refund_minor", "functional_refund_released_minor", "functional_cash_minor", "functional_fx_gain_minor", "functional_fx_loss_minor"].some(key => amounts[key] !== "0")
        || number("transaction_net_minor") + number("transaction_tax_minor") !== number("transaction_credit_minor")
        || number("functional_net_minor") + number("functional_tax_minor") !== number("functional_credit_minor")
        || number("transaction_receivable_released_minor") + number("transaction_refund_delta_minor") !== number("transaction_credit_minor")) monetaryInvalid();
    if (number("transaction_receivable_released_minor") === 0n && number("functional_receivable_released_minor") !== 0n
        || number("transaction_refund_delta_minor") === 0n && number("functional_refund_delta_minor") !== 0n) monetaryInvalid();
    const merchandise = number("functional_credit_minor") + number("functional_alignment_loss_minor");
    if (merchandise !== number("functional_receivable_released_minor") + number("functional_refund_delta_minor") + number("functional_alignment_gain_minor")
        || merchandise + number("functional_cost_minor") !== number("functional_turnover_minor")) monetaryInvalid();
    const prefix = operation === "ReverseReturn" ? "Reverse" : "";
    purposes = [...(merchandise ? [prefix + "MerchandiseCredit"] : []), ...(number("functional_cost_minor") ? [prefix + "CostRestoration"] : [])];
  } else {
    const allowed = new Set(["transaction_refund_minor", "functional_refund_released_minor", "functional_cash_minor", "functional_fx_gain_minor", "functional_fx_loss_minor", "functional_turnover_minor"]);
    if (monetaryAmountFields.some(key => !allowed.has(key) && amounts[key] !== "0") || number("transaction_refund_minor") <= 0n) monetaryInvalid();
    const turnover = number("functional_refund_released_minor") + number("functional_fx_loss_minor");
    if (turnover !== number("functional_cash_minor") + number("functional_fx_gain_minor") || turnover !== number("functional_turnover_minor")) monetaryInvalid();
    purposes = turnover ? [operation === "ReverseRefund" ? "ReverseRefund" : "Refund"] : [];
  }
  if (identity) {
    const pairs = [["transaction_net_minor", "functional_net_minor"], ["transaction_tax_minor", "functional_tax_minor"], ["transaction_credit_minor", "functional_credit_minor"],
      ["transaction_receivable_released_minor", "functional_receivable_released_minor"], ["transaction_refund_delta_minor", "functional_refund_delta_minor"], ["transaction_refund_minor", "functional_refund_released_minor"]] as const;
    if (pairs.some(([first, second]) => number(first) !== number(second)) || ["functional_fx_gain_minor", "functional_fx_loss_minor", "functional_alignment_gain_minor", "functional_alignment_loss_minor"].some(key => amounts[key] !== "0")
        || !isReturn && number("functional_cash_minor") !== number("transaction_refund_minor")) monetaryInvalid();
  }
  if (!Array.isArray(row.entries) || row.entries.length !== purposes.length) monetaryInvalid();
  const entries = row.entries.map((value, index) => {
    const entry = monetaryObject(value, ["purpose", "entry_id", "posting_effect_id", "validation_digest"]);
    if (entry.purpose !== purposes[index] || (entry.posting_effect_id !== null) !== (phase === 2)) monetaryInvalid();
    monetaryText(entry.entry_id); monetaryNullableText(entry.posting_effect_id); monetaryDigest(entry.validation_digest);
    return entry as unknown as MonetaryPartialEntry;
  });
  if (new Set(entries.map(entry => entry.entry_id)).size !== entries.length || phase === 2 && new Set(entries.map(entry => entry.posting_effect_id)).size !== entries.length) monetaryInvalid();
  return { ...row, entries, monetary: amounts } as unknown as MonetaryPartialPlan;
}
export function parseMonetaryPartialBalance(value: unknown, scope: FinanceScope, sourceOrderId: string): MonetaryPartialBalance {
  const row = monetaryObject(value, balanceFields); monetaryScope(row, scope);
  if (row.schema_version !== "customer-partial-return-monetary-balance-v3" || monetaryText(row.source_order_id) !== monetaryText(sourceOrderId)) monetaryInvalid();
  for (const key of ["source_id", "invoice_id"]) monetaryText(row[key]); monetaryDigest(row.source_fingerprint); monetaryInteger(row.quantity_precision, 6);
  monetaryMinor(row.original_quantity_scaled, true); monetaryMinor(row.returned_quantity_scaled); monetaryMinor(row.remaining_quantity_scaled);
  if (BigInt(row.returned_quantity_scaled as string) + BigInt(row.remaining_quantity_scaled as string) !== BigInt(row.original_quantity_scaled as string)) monetaryInvalid();
  [row.transaction_policy, row.functional_policy] = parseMonetaryPolicyPair(row.transaction_policy, row.functional_policy);
  validateMonetaryBalance(row, (row.transaction_policy as MonetaryPolicy).currency_code === (row.functional_policy as MonetaryPolicy).currency_code);
  return row as unknown as MonetaryPartialBalance;
}
export async function loadMonetaryPartialPlans(session: BrowserAdminSession, scope: FinanceScope, signal?: AbortSignal): Promise<MonetaryPartialPlan[]> {
  const row = monetaryObject(await monetaryRequest(session, scope, `${monetaryPartialRoot}/plans`, undefined, signal), ["plans"]);
  if (!Array.isArray(row.plans) || row.plans.length > 200) monetaryInvalid();
  const plans = row.plans.map(value => parseMonetaryPartialPlan(value, scope));
  if (new Set(plans.map(value => value.id)).size !== plans.length) monetaryInvalid();
  return plans;
}
export async function loadMonetaryPartialBalance(session: BrowserAdminSession, scope: FinanceScope, sourceOrderId: string, signal?: AbortSignal): Promise<MonetaryPartialBalance> {
  const row = monetaryObject(await monetaryRequest(session, scope, `${monetaryPartialRoot}/sources/${encodeURIComponent(sourceOrderId)}/balance`, undefined, signal), ["balance"]);
  return parseMonetaryPartialBalance(row.balance, scope, sourceOrderId);
}
export async function loadMonetaryPartialPlan(session: BrowserAdminSession, scope: FinanceScope, id: string, signal?: AbortSignal): Promise<MonetaryPartialPlan> {
  const row = monetaryObject(await monetaryRequest(session, scope, `${monetaryPartialRoot}/plans/${encodeURIComponent(id)}`, undefined, signal), ["plan"]);
  const plan = parseMonetaryPartialPlan(row.plan, scope);
  if (plan.id !== id) monetaryInvalid();
  return plan;
}
export function monetaryPartialMatchesCommand(plan: MonetaryPartialPlan, command: PreparedScopedCommand): boolean {
  const root = monetaryPartialRoot;
  if (command.body.expected_plan_digest !== undefined && command.body.expected_plan_digest !== plan.plan_digest
      || command.body.expected_history_version !== undefined && command.body.expected_history_version !== plan.expected_history_version) return false;
  if (command.path === `${root}/plans`) return plan.operation === "Return" && plan.phase === 0 && plan.source_order_id === command.body.source_order_id && plan.quantity_scaled === command.body.quantity_scaled;
  if (command.path.endsWith("/refunds")) return plan.operation === "Refund" && plan.phase === 0 && plan.monetary.transaction_refund_minor === command.body.amount_minor
    && command.path === `${root}/plans/${plan.original_id}/refunds`;
  if (command.path.endsWith("/reversals")) return plan.operation.startsWith("Reverse") && plan.phase === 0 && command.path === `${root}/plans/${plan.original_id}/reversals`;
  return ([["review", 1], ["post", 2], ["cancel", 3]] as const).some(([action, phase]) => command.path === `${root}/plans/${plan.id}/${action}` && plan.phase === phase);
}
export async function executeMonetaryPartialCommand(session: BrowserAdminSession, scope: FinanceScope, command: PreparedScopedCommand): Promise<MonetaryPartialPlan> {
  const row = monetaryObject(await monetaryRequest(session, scope, command.path, command), ["plan"]), plan = parseMonetaryPartialPlan(row.plan, scope);
  if (!monetaryPartialMatchesCommand(plan, command)) monetaryInvalid();
  return plan;
}
