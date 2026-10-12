import { financeRequest, type FinanceScope } from "./enterprise-finance-data";
import type { PreparedScopedCommand } from "./scoped-command";
import type { BrowserAdminSession } from "./types";

export interface ReturnEntry { entry_id: string; validation_digest: string; original_effect_id: string | null; snapshot: { entry: Record<string, unknown>; lines: { account_id: string; line_number: number; debit_minor: string; credit_minor: string }[] } }
export interface ReturnPlan extends FinanceScope {
  id: string; operation: "Return" | "Refund"; phase: 0 | 1 | 2 | 3; status: "Prepared" | "Reviewed" | "Posted" | "Cancelled";
  plan_digest: string; source_order_id: string; invoice_id: string; return_id?: string; amount_minor: string;
  credit_minor?: string; cogs_restored_minor?: string; refund_entitlement_minor?: string; receivable_released_minor?: string;
  currency_code: string; currency_precision: number; posting_date: string; period_id: string;
  preparer_actor_id: string; reviewer_actor_id: string | null; posted_actor_id: string | null; cancelled_actor_id: string | null;
  cancellation_reason: string | null; posting_effect_ids: string[]; entries: ReturnEntry[];
  canonical_plan_json: string; evidence: Record<string, string | null>;
}
export interface RefundBalance { return_id: string; plan_digest: string; credit_minor: string; refund_entitlement_minor: string; refunded_minor: string; refund_due_minor: string }
const object = (v: unknown): v is Record<string, unknown> => v !== null && typeof v === "object" && !Array.isArray(v);
const text = (v: unknown): v is string => typeof v === "string" && v.length > 0 && v.length <= 500 && !/[\x00-\x1f\x7f]/.test(v);
const digest = (v: unknown): v is string => typeof v === "string" && /^[a-f0-9]{64}$/.test(v);
const minor = (v: unknown): v is string => typeof v === "string" && /^(0|[1-9]\d{0,18})$/.test(v) && BigInt(v) <= 9000000000000000000n;
function invalid(): never { throw new Error("customer_return_response_invalid"); }
function canonical(value: unknown, key = ""): string {
  if ((key.endsWith("_minor") || key.endsWith("_scaled")) && minor(value)) return value;
  if (Array.isArray(value)) return `[${value.map(item => canonical(item)).join(",")}]`;
  if (object(value)) return `{${Object.keys(value).sort().map(k => `${JSON.stringify(k)}:${canonical(value[k], k)}`).join(",")}}`;
  if (value === null || typeof value === "string" || typeof value === "boolean" || (typeof value === "number" && Number.isSafeInteger(value))) return JSON.stringify(value);
  return invalid();
}
const projection = new Set(["phase", "status", "reviewer_actor_id", "posted_actor_id", "cancelled_actor_id", "cancellation_reason", "posting_effect_ids", "canonical_plan_json", "evidence", "plan_digest"]);
export async function parseReturnPlan(value: unknown, scope: FinanceScope): Promise<ReturnPlan> {
  if (!object(value) || !/^CR(?:F)?1-[a-f0-9]{32}$/.test(String(value.id)) || !["Return", "Refund"].includes(String(value.operation)) ||
      (value.operation === "Return") !== String(value.id).startsWith("CR1-") || !digest(value.plan_digest) || !Number.isInteger(value.phase) ||
      Number(value.phase) < 0 || Number(value.phase) > 3 || ["Prepared", "Reviewed", "Posted", "Cancelled"][Number(value.phase)] !== value.status ||
      !text(value.preparer_actor_id) || !minor(value.amount_minor) || BigInt(value.amount_minor) <= 0n || !/^[A-Z]{3}$/.test(String(value.currency_code)) ||
      !Number.isInteger(value.currency_precision) || Number(value.currency_precision) < 0 || Number(value.currency_precision) > 8 ||
      !text(value.source_order_id) || !text(value.invoice_id) || !text(value.period_id) || !/^\d{4}-\d{2}-\d{2}$/.test(String(value.posting_date)) ||
      !Array.isArray(value.entries) || value.entries.length !== (value.operation === "Refund" ? 1 : value.refund_entitlement_minor === "0" ? 2 : 3) ||
      !Array.isArray(value.posting_effect_ids) || new Set(value.posting_effect_ids).size !== value.posting_effect_ids.length || !object(value.evidence)) invalid();
  for (const [key, expected] of Object.entries(scope)) if (value[key] !== expected) invalid();
  if (value.operation === "Return") {
    for (const key of ["credit_minor", "cogs_restored_minor", "refund_entitlement_minor", "receivable_released_minor"]) if (!minor(value[key])) invalid();
    if (BigInt(String(value.credit_minor)) !== BigInt(String(value.refund_entitlement_minor)) + BigInt(String(value.receivable_released_minor)) ||
        BigInt(value.amount_minor) !== BigInt(String(value.credit_minor)) + BigInt(String(value.refund_entitlement_minor)) + BigInt(String(value.cogs_restored_minor))) invalid();
  } else if (!/^CR1-[a-f0-9]{32}$/.test(String(value.return_id))) invalid();
  if ([1, 2].includes(Number(value.phase)) && (!text(value.reviewer_actor_id) || value.reviewer_actor_id === value.preparer_actor_id)) invalid();
  if (value.phase === 2 ? !text(value.posted_actor_id) || [value.preparer_actor_id, value.reviewer_actor_id].includes(value.posted_actor_id) || value.posting_effect_ids.length !== value.entries.length : value.posted_actor_id !== null || value.posting_effect_ids.length !== 0) invalid();
  if (value.phase === 3 && (!text(value.cancelled_actor_id) || !text(value.cancellation_reason) || [value.preparer_actor_id, value.reviewer_actor_id].includes(value.cancelled_actor_id))) invalid();
  for (const part of value.entries) {
    if (!object(part) || !text(part.entry_id) || !digest(part.validation_digest) || !object(part.snapshot) || !object(part.snapshot.entry) || !Array.isArray(part.snapshot.lines) || part.snapshot.lines.length < 2 || part.snapshot.lines.length > 1000) invalid();
    if (part.snapshot.entry.id !== part.entry_id || part.snapshot.entry.external_reference !== value.id) invalid();
    for (const [key, expected] of Object.entries(scope)) if (part.snapshot.entry[key] !== expected) invalid();
    let debit = 0n, credit = 0n;
    for (const [index, line] of part.snapshot.lines.entries()) {
      if (!object(line) || line.line_number !== index + 1 || !text(line.account_id) || !minor(line.debit_minor) || !minor(line.credit_minor) || (BigInt(line.debit_minor) === 0n) === (BigInt(line.credit_minor) === 0n)) invalid();
      debit += BigInt(line.debit_minor); credit += BigInt(line.credit_minor);
    }
    if (debit !== credit || debit <= 0n || debit > 9000000000000000000n) invalid();
  }
  const retained = Object.fromEntries(Object.entries(value).filter(([key]) => !projection.has(key)));
  if (typeof value.canonical_plan_json !== "string" || value.canonical_plan_json.length > 2000000 || canonical(retained) !== value.canonical_plan_json) invalid();
  const bytes = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value.canonical_plan_json));
  if ([...new Uint8Array(bytes)].map(v => v.toString(16).padStart(2, "0")).join("") !== value.plan_digest) invalid();
  for (const key of ["prepared_audit_event_id", "prepared_outbox_event_id", ...(value.phase === 1 || value.phase === 2 ? ["review_audit_event_id", "review_outbox_event_id"] : []), ...(value.phase === 2 ? ["post_audit_event_id", "post_outbox_event_id"] : []), ...(value.phase === 3 ? ["cancel_audit_event_id", "cancel_outbox_event_id"] : [])]) if (!text(value.evidence[key])) invalid();
  return value as unknown as ReturnPlan;
}
export function parseRefundBalance(value: unknown, parent: ReturnPlan): RefundBalance {
  if (!object(value) || parent.operation !== "Return" || parent.phase !== 2 || value.return_id !== parent.id || value.plan_digest !== parent.plan_digest || value.credit_minor !== parent.credit_minor || value.refund_entitlement_minor !== parent.refund_entitlement_minor) invalid();
  for (const key of ["refunded_minor", "refund_due_minor"]) if (!minor(value[key])) invalid();
  if (BigInt(String(value.refunded_minor)) + BigInt(String(value.refund_due_minor)) !== BigInt(String(value.refund_entitlement_minor))) invalid();
  return value as unknown as RefundBalance;
}
export async function returnRequest(session: BrowserAdminSession, scope: FinanceScope, path: string, command?: PreparedScopedCommand, signal?: AbortSignal): Promise<Record<string, unknown>> {
  const value = await financeRequest(session, scope, path, command?.body, signal); if (!object(value)) invalid(); return value;
}
