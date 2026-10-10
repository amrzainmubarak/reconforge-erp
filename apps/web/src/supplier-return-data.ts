import { procurementFetch, type ProcurementScope } from "./procurement-data";
import type { PreparedScopedCommand } from "./scoped-command";
import type { BrowserAdminSession } from "./types";

export const supplierReturnRoot = "/api/v1/supplier-returns";
export interface SupplierReturnPlan {
  id: string; number: string; order_id: string; receipt_id: string; invoice_id: string; native_invoice_id: string;
  workspace_id: string; organization_id: string; legal_entity_id: string; period_id: string; posting_date: string;
  phase: number; status: "Prepared" | "Reviewed" | "Posted" | "Cancelled"; plan_digest: string; canonical_plan_json: string;
  credit_minor: string; inventory_removed_minor: string; charge_expense_minor: string; amount_minor: string;
  currency_code: string; currency_precision: number; preparer_actor_id: string; reviewer_actor_id: string | null;
  posted_actor_id: string | null; cancelled_actor_id: string | null; cancellation_reason: string | null; posting_effect_ids: string[];
  evidence: Record<string, string | null>;
}
const object = (v: unknown): v is Record<string, unknown> => v !== null && typeof v === "object" && !Array.isArray(v);
const text = (v: unknown): v is string => typeof v === "string" && v.length > 0 && v.length <= 500;
const money = (v: unknown): v is string => typeof v === "string" && /^(0|[1-9][0-9]{0,18})$/.test(v) && BigInt(v) <= 9000000000000000000n;
function invalid(): never { throw new Error("supplier_return_contract_invalid"); }
function retainedExact(canonical: string): Record<string, unknown> {
  // Quote JSON numeric tokens before parsing, preserving large native integers.
  // Strings, escape sequences and every source byte remain in the hashed input.
  let rewritten = "", quoted = false, escaped = false;
  for (let at = 0; at < canonical.length; at++) {
    const char = canonical[at];
    if (quoted) {
      rewritten += char;
      if (escaped) escaped = false;
      else if (char === "\\") escaped = true;
      else if (char === '"') quoted = false;
    } else if (char === '"') { quoted = true; rewritten += char; }
    else if (char === "-" || /[0-9]/.test(char)) {
      const token = /^-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?/.exec(canonical.slice(at));
      if (!token) invalid();
      rewritten += JSON.stringify(token[0]); at += token[0].length - 1;
    } else rewritten += char;
  }
  try { const value: unknown = JSON.parse(rewritten); if (!object(value)) invalid(); return value; }
  catch { return invalid(); }
}
export function parseSupplierReturn(value: unknown, scope: ProcurementScope, orderId: string): SupplierReturnPlan {
  if (!object(value) || value.order_id !== orderId || value.workspace_id !== scope.workspace_id || value.organization_id !== scope.organization_id || value.legal_entity_id !== scope.legal_entity_id || value.currency_code !== scope.currency_code ||
      !["id", "number", "receipt_id", "invoice_id", "native_invoice_id", "period_id", "posting_date", "preparer_actor_id"].every(key => text(value[key])) || !/^SR1-[a-f0-9]{32}$/.test(String(value.id)) || !String(value.number).startsWith("SR1-") ||
      !Number.isInteger(value.phase) || Number(value.phase) < 0 || Number(value.phase) > 3 || value.status !== ["Prepared", "Reviewed", "Posted", "Cancelled"][Number(value.phase)] ||
      !Number.isInteger(value.currency_precision) || Number(value.currency_precision) < 0 || Number(value.currency_precision) > 8 ||
      typeof value.plan_digest !== "string" || !/^[a-f0-9]{64}$/.test(value.plan_digest) || typeof value.canonical_plan_json !== "string" || value.canonical_plan_json.length > 262144 ||
      !["credit_minor", "inventory_removed_minor", "charge_expense_minor", "amount_minor"].every(key => money(value[key])) || value.credit_minor === "0" ||
      BigInt(String(value.credit_minor)) + BigInt(String(value.charge_expense_minor)) !== BigInt(String(value.inventory_removed_minor)) || 2n * BigInt(String(value.inventory_removed_minor)) !== BigInt(String(value.amount_minor)) ||
      ![value.reviewer_actor_id, value.posted_actor_id, value.cancelled_actor_id, value.cancellation_reason].every(v => v === null || text(v)) ||
      (value.phase === 0 && value.reviewer_actor_id !== null) || ([1, 2].includes(Number(value.phase)) && value.reviewer_actor_id === null) || value.reviewer_actor_id === value.preparer_actor_id ||
      (value.phase === 2) !== (value.posted_actor_id !== null) || (value.phase === 3) !== (value.cancelled_actor_id !== null && value.cancellation_reason !== null) ||
      (value.phase === 2 && new Set([value.preparer_actor_id, value.reviewer_actor_id, value.posted_actor_id]).size !== 3) ||
      (value.phase === 3 && [value.preparer_actor_id, value.reviewer_actor_id].includes(value.cancelled_actor_id)) ||
      !Array.isArray(value.posting_effect_ids) || !value.posting_effect_ids.every(text) || new Set(value.posting_effect_ids).size !== value.posting_effect_ids.length ||
      value.posting_effect_ids.length !== (value.phase === 2 ? (value.charge_expense_minor === "0" ? 2 : 3) : 0) || !object(value.evidence)) invalid();
  for (const stage of ["prepared", "review", "post", "cancel"]) {
    const needed = stage === "prepared" || (stage === "review" && value.reviewer_actor_id !== null) || (stage === "post" && value.phase === 2) || (stage === "cancel" && value.phase === 3);
    for (const kind of ["audit", "outbox"]) {
      const reference = value.evidence[`${stage}_${kind}_event_id`];
      if (needed ? !text(reference) : reference !== null) invalid();
    }
  }
  const retained = retainedExact(value.canonical_plan_json);
  for (const key of ["id", "number", "order_id", "receipt_id", "invoice_id", "native_invoice_id", "workspace_id", "organization_id", "legal_entity_id", "period_id", "posting_date", "currency_code", "currency_precision", "preparer_actor_id", "credit_minor", "inventory_removed_minor", "charge_expense_minor", "amount_minor"])
    if (retained[key] !== String(value[key])) invalid();
  return value as unknown as SupplierReturnPlan;
}
async function verified(value: unknown, scope: ProcurementScope, orderId: string): Promise<SupplierReturnPlan> {
  const plan = parseSupplierReturn(value, scope, orderId);
  const hash = [...new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(plan.canonical_plan_json)))].map(byte => byte.toString(16).padStart(2, "0")).join("");
  if (hash !== plan.plan_digest) invalid();
  return plan;
}
export async function supplierReturnPage(session: BrowserAdminSession, scope: ProcurementScope, orderId: string, signal?: AbortSignal): Promise<SupplierReturnPlan[]> {
  const value = await procurementFetch(session, scope.workspace_id, scope, `${supplierReturnRoot}/orders/${encodeURIComponent(orderId)}`, { signal });
  if (!object(value) || !Array.isArray(value.records) || value.records.length > 25) invalid();
  const records = await Promise.all(value.records.map(item => verified(item, scope, orderId)));
  if (new Set(records.map(plan => plan.id)).size !== records.length) invalid();
  return records;
}
export async function supplierReturnCommand(session: BrowserAdminSession, scope: ProcurementScope, orderId: string, command: PreparedScopedCommand): Promise<SupplierReturnPlan> {
  const plan = await verified(await procurementFetch(session, scope.workspace_id, scope, command.path, { body: command.body }), scope, orderId);
  if (command.path === `${supplierReturnRoot}/plans`) {
    if (plan.phase !== 0 || plan.order_id !== command.body.order_id || plan.receipt_id !== command.body.receipt_id || plan.invoice_id !== command.body.invoice_id || plan.number !== String(command.body.number).trim() || plan.posting_date !== command.body.posting_date || plan.period_id !== command.body.period_id) invalid();
  } else {
    const path = /^\/api\/v1\/supplier-returns\/plans\/([^/]+)\/(review|post|cancel)$/.exec(command.path);
    if (!path || decodeURIComponent(path[1]) !== plan.id || plan.plan_digest !== command.body.expected_plan_digest || plan.phase !== ({ review: 1, post: 2, cancel: 3 } as Record<string, number>)[path[2]] || (path[2] === "cancel" && plan.cancellation_reason !== command.body.reason)) invalid();
  }
  return plan;
}
