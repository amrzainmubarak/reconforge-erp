import { financeRequest, type FinanceScope } from "./enterprise-finance-data";
import type { PreparedScopedCommand } from "./scoped-command";
import type { BrowserAdminSession } from "./types";

export type ManufacturingSource = Record<string, unknown> & FinanceScope & {
  id: string; source_digest: string; phase: number; creator_id?: string; preparer_actor_id?: string;
  reviewer_id?: string | null; issue_reviewer_id?: string | null;
  output_quantity_scaled?: string; disposed_quantity_scaled?: string; released_cost_minor?: string;
  issue_plan?: { total_cost_minor: string; preparer_actor_id: string; entry: { entry_id: string } } | null;
  issue_effect_id?: string | null; monetary_policy?: { precision: number }; currency_code?: string;
  completions?: ManufacturingSource[]; good_quantity_scaled?: string; scrap_quantity_scaled?: string;
  good_cost_minor?: string; scrap_cost_minor?: string; receipt_effect?: Record<string, unknown> | null;
  scrap_effect_id?: string | null;
};
const record = (v: unknown): v is Record<string, unknown> => v !== null && typeof v === "object" && !Array.isArray(v);
const integer = (v: unknown): v is string => typeof v === "string" && /^(0|[1-9]\d{0,18})$/.test(v) && BigInt(v) <= 9000000000000000000n;
const text = (v: unknown): v is string => typeof v === "string" && v.length > 0 && v.length <= 500 && !/[\x00-\x1f\x7f]/.test(v);
const digest = (v: unknown): v is string => typeof v === "string" && /^[a-f0-9]{64}$/.test(v);
function invalid(): never { throw new Error("manufacturing_evidence_invalid"); }
export function manufacturingCanonical(value: unknown, key = ""): string {
  if ((key.endsWith("_minor") || key.endsWith("_scaled")) && integer(value)) return value;
  if (Array.isArray(value)) return `[${value.map(part => manufacturingCanonical(part)).join(",")}]`;
  if (record(value)) return `{${Object.keys(value).sort().map(field => `${JSON.stringify(field)}:${manufacturingCanonical(value[field], field)}`).join(",")}}`;
  if (value === null || typeof value === "string" || typeof value === "boolean" || (typeof value === "number" && Number.isSafeInteger(value))) return JSON.stringify(value);
  return invalid();
}
async function verifyDigest(value: unknown, expected: string) {
  const bytes = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(manufacturingCanonical(value)));
  if ([...new Uint8Array(bytes)].map(v => v.toString(16).padStart(2, "0")).join("") !== expected) invalid();
}
export async function parseManufacturing(value: unknown, scope: FinanceScope): Promise<ManufacturingSource> {
  if (!record(value) || !/^ME1(?:B|C)?-[A-F0-9]{32}$/.test(String(value.id)) || !digest(value.source_digest) || !Number.isInteger(value.phase)) invalid();
  for (const [key, expected] of Object.entries(scope)) if (value[key] !== expected) invalid();
  const bom = String(value.id).startsWith("ME1B-"), child = String(value.id).startsWith("ME1C-");
  const projection = bom ? ["phase", "source_digest", "reviewer_id"] : child ? ["phase", "source_digest", "reviewer_id", "receipt_effect", "scrap_effect_id"] :
    ["phase", "source_digest", "issue_plan", "issue_digest", "issue_reviewer_id", "issue_effect_id", "valuation_id", "disposed_quantity_scaled", "released_cost_minor", "completions", "wip_minor"];
  if (Number(value.phase) < 0 || Number(value.phase) > (bom ? 1 : child ? 3 : 5) || !text(child ? value.preparer_actor_id : value.creator_id)) invalid();
  if (bom) {
    if (!integer(value.output_quantity_scaled) || !Array.isArray(value.components) || value.components.length < 1 || value.components.length > 100 ||
        value.phase === 1 && (!text(value.reviewer_id) || value.reviewer_id === value.creator_id)) invalid();
  } else if (child) {
    for (const key of ["good_quantity_scaled", "scrap_quantity_scaled", "stage_quantity_scaled", "good_cost_minor", "scrap_cost_minor", "released_cost_minor", "disposed_before_scaled", "released_before_minor", "wip_after_minor"]) if (!integer(value[key])) invalid();
    if (BigInt(String(value.good_quantity_scaled)) + BigInt(String(value.scrap_quantity_scaled)) !== BigInt(String(value.stage_quantity_scaled)) ||
        BigInt(String(value.good_cost_minor)) + BigInt(String(value.scrap_cost_minor)) !== BigInt(String(value.released_cost_minor))) invalid();
    if ([1, 2].includes(Number(value.phase)) && (!text(value.reviewer_id) || value.reviewer_id === value.preparer_actor_id)) invalid();
    if (BigInt(String(value.good_quantity_scaled)) > 0n) {
      if (!record(value.receipt_plan) || !digest(value.receipt_plan.plan_digest) || !record(value.receipt_plan.source) || value.receipt_plan.source.number !== value.id || value.receipt_plan.source.total_value_minor !== value.good_cost_minor) invalid();
      await verifyDigest(Object.fromEntries(Object.entries(value.receipt_plan).filter(([key]) => !["plan_digest", "preparation_audit_event_id", "preparation_outbox_event_id"].includes(key))), value.receipt_plan.plan_digest);
    } else if (value.receipt_plan !== null) invalid();
    if (value.phase === 2 && (BigInt(String(value.good_quantity_scaled)) > 0n ? !record(value.receipt_effect) : value.receipt_effect !== null)) invalid();
    if (value.phase === 2 && record(value.receipt_effect)) {
      if (!digest(value.receipt_effect.effect_digest) || !record(value.receipt_plan) || value.receipt_effect.plan_id !== value.receipt_plan.plan_id || value.receipt_effect.plan_digest !== value.receipt_plan.plan_digest) invalid();
      await verifyDigest(Object.fromEntries(Object.entries(value.receipt_effect).filter(([key]) => key !== "effect_digest")), value.receipt_effect.effect_digest);
    }
    if (value.phase === 2 && (BigInt(String(value.scrap_quantity_scaled)) > 0n ? !text(value.scrap_effect_id) : value.scrap_effect_id !== null)) invalid();
    if (value.phase !== 2 && (value.receipt_effect !== null || value.scrap_effect_id !== null)) invalid();
  } else {
    for (const key of ["output_quantity_scaled", "disposed_quantity_scaled", "released_cost_minor"]) if (!integer(value[key])) invalid();
    if (BigInt(String(value.disposed_quantity_scaled)) > BigInt(String(value.output_quantity_scaled))) invalid();
    if (value.issue_plan !== null) {
      if (!record(value.issue_plan) || !integer(value.issue_plan.total_cost_minor) || !digest(value.issue_digest) || value.issue_plan.source_digest !== value.source_digest) invalid();
      await verifyDigest(value.issue_plan, value.issue_digest);
      if (BigInt(String(value.released_cost_minor)) > BigInt(value.issue_plan.total_cost_minor)) invalid();
    } else if (![0, 5].includes(Number(value.phase))) invalid();
    if ([3, 4].includes(Number(value.phase)) && !text(value.issue_effect_id)) invalid();
    if (value.phase === 4 && (value.disposed_quantity_scaled !== value.output_quantity_scaled || !record(value.issue_plan) || value.released_cost_minor !== value.issue_plan.total_cost_minor)) invalid();
  }
  await verifyDigest(Object.fromEntries(Object.entries(value).filter(([key]) => !projection.includes(key))), value.source_digest);
  if (!bom && !child && value.completions !== undefined) {
    if (!Array.isArray(value.completions) || value.completions.length > 200) invalid();
    value.completions = await Promise.all(value.completions.map(part => parseManufacturing(part, scope)));
    for (const part of value.completions as ManufacturingSource[]) if (part.order_id !== value.id || part.order_digest !== value.source_digest || part.issue_digest !== value.issue_digest) invalid();
    const posted = (value.completions as ManufacturingSource[]).filter(part => part.phase === 2);
    if (posted.reduce((sum, part) => sum + BigInt(String(part.stage_quantity_scaled)), 0n) !== BigInt(String(value.disposed_quantity_scaled)) ||
        posted.reduce((sum, part) => sum + BigInt(String(part.released_cost_minor)), 0n) !== BigInt(String(value.released_cost_minor))) invalid();
  }
  return value as ManufacturingSource;
}
export function applyManufacturingCompletion(order: ManufacturingSource, child: ManufacturingSource): ManufacturingSource {
  if (!child.id.startsWith("ME1C-") || child.order_id !== order.id || child.order_digest !== order.source_digest || child.issue_digest !== order.issue_digest || !order.issue_plan) invalid();
  const retained = order.completions?.find(row => row.id === child.id);
  if (retained && retained.source_digest !== child.source_digest) invalid();
  const terminal = retained && retained.phase >= 2 && child.phase < 2 ? retained : child;
  if (retained && retained.phase >= 2 && child.phase >= 2 && retained.phase !== child.phase) invalid();
  const completions = [terminal, ...(order.completions ?? []).filter(row => row.id !== child.id)];
  if (child.phase !== 2) return { ...order, completions };
  const disposed = BigInt(String(child.disposed_before_scaled)) + BigInt(String(child.stage_quantity_scaled));
  const released = BigInt(String(child.released_before_minor)) + BigInt(String(child.released_cost_minor));
  const originalQuantity = BigInt(String(order.output_quantity_scaled)), originalCost = BigInt(order.issue_plan.total_cost_minor);
  if (disposed > originalQuantity || released > originalCost || originalCost - released !== BigInt(String(child.wip_after_minor))) invalid();
  // Historical ACKs cannot reduce a later retained parent projection.
  const currentDisposed = BigInt(String(order.disposed_quantity_scaled)), currentReleased = BigInt(String(order.released_cost_minor));
  if ((disposed < currentDisposed) !== (released < currentReleased)) invalid();
  const finalDisposed = disposed > currentDisposed ? disposed : currentDisposed, finalReleased = released > currentReleased ? released : currentReleased;
  if ((finalDisposed === originalQuantity) !== (finalReleased === originalCost)) invalid();
  return { ...order, completions, disposed_quantity_scaled: finalDisposed.toString(), released_cost_minor: finalReleased.toString(), wip_minor: (originalCost - finalReleased).toString(), phase: finalDisposed === originalQuantity ? 4 : 3 };
}
export async function manufacturingRequest(session: BrowserAdminSession, scope: FinanceScope, path: string, command?: PreparedScopedCommand, signal?: AbortSignal): Promise<Record<string, unknown>> {
  const result = await financeRequest(session, scope, path, command?.body, signal); if (!record(result)) invalid(); return result;
}
