import { procurementFetch, type ProcurementScope } from "./procurement-data";
import type { BrowserAdminSession } from "./types";
import type { PreparedScopedCommand } from "./scoped-command";

export const landedRoot = "/api/v1/landed-cost";
export interface LandedAllocation { sequence: number; order_line_id: string; quantity_text: string; base_minor: string; freight_minor: string; duty_minor: string; receipt_id: string; receipt_plan_id: string; stage: number }
export interface LandedPlan { id: string; order_id: string; number: string; workspace_id: string; organization_id: string; legal_entity_id: string; phase: number; status: "Prepared" | "Reviewed" | "Posted"; plan_digest: string; freight_minor: string; duty_minor: string; amount_minor: string; currency_code: string; entry_id: string; preparer_actor_id: string; reviewer_actor_id: string | null; posted_actor_id: string | null; posting_effect_id: string | null; allocations: LandedAllocation[] }
const object = (value: unknown): value is Record<string, unknown> => value !== null && typeof value === "object" && !Array.isArray(value);
const text = (value: unknown): value is string => typeof value === "string" && value.length > 0 && value.length <= 500;
const money = (value: unknown): value is string => typeof value === "string" && /^(0|[1-9][0-9]{0,18})$/.test(value) && BigInt(value) <= 9000000000000000000n;
function invalid(): never { throw new Error("landed_cost_contract_invalid"); }

export function parseLandedPlan(value: unknown, scope: ProcurementScope, orderId: string): LandedPlan {
  if (!object(value) || value.order_id !== orderId || value.workspace_id !== scope.workspace_id || value.organization_id !== scope.organization_id || value.legal_entity_id !== scope.legal_entity_id ||
      !["id", "number", "entry_id", "preparer_actor_id"].every((key) => text(value[key])) || !Number.isInteger(value.phase) || Number(value.phase) < 0 || Number(value.phase) > 2 ||
      value.status !== ["Prepared", "Reviewed", "Posted"][Number(value.phase)] || typeof value.plan_digest !== "string" || !/^[0-9a-f]{64}$/.test(value.plan_digest) ||
      value.currency_code !== scope.currency_code || !["freight_minor", "duty_minor", "amount_minor"].every((key) => money(value[key])) ||
      BigInt(String(value.amount_minor)) === 0n || BigInt(String(value.freight_minor)) + BigInt(String(value.duty_minor)) !== BigInt(String(value.amount_minor)) ||
      ![value.reviewer_actor_id, value.posted_actor_id, value.posting_effect_id].every((item) => item === null || text(item)) ||
      (value.phase === 0) !== (value.reviewer_actor_id === null) || (value.phase === 2) !== (value.posted_actor_id !== null) || (value.phase === 2) !== (value.posting_effect_id !== null) ||
      value.reviewer_actor_id === value.preparer_actor_id || (value.phase === 2 && new Set([value.preparer_actor_id, value.reviewer_actor_id, value.posted_actor_id]).size !== 3) ||
      !Array.isArray(value.allocations) || value.allocations.length < 1 || value.allocations.length > 128) invalid();
  let freight = 0n, duty = 0n;
  const sources = new Set<string>(), receipts = new Set<string>();
  for (const [index, allocation] of value.allocations.entries()) {
    if (!object(allocation) || allocation.sequence !== index + 1 || allocation.stage !== value.phase ||
        !["order_line_id", "receipt_id", "receipt_plan_id"].every((key) => text(allocation[key])) ||
        typeof allocation.quantity_text !== "string" || allocation.quantity_text.length > 64 || !/^(0|[1-9][0-9]*)(\.[0-9]{1,6})?$/.test(allocation.quantity_text) || /^0(\.0+)?$/.test(allocation.quantity_text) ||
        !["base_minor", "freight_minor", "duty_minor"].every((key) => money(allocation[key])) || allocation.base_minor === "0" ||
        BigInt(String(allocation.base_minor)) + BigInt(String(allocation.freight_minor)) + BigInt(String(allocation.duty_minor)) > 9000000000000000000n ||
        sources.has(String(allocation.order_line_id)) || receipts.has(String(allocation.receipt_id))) invalid();
    sources.add(String(allocation.order_line_id)); receipts.add(String(allocation.receipt_id));
    freight += BigInt(String(allocation.freight_minor)); duty += BigInt(String(allocation.duty_minor));
  }
  if (freight !== BigInt(String(value.freight_minor)) || duty !== BigInt(String(value.duty_minor))) invalid();
  return value as unknown as LandedPlan;
}

export async function landedPage(session: BrowserAdminSession, scope: ProcurementScope, orderId: string, after = "", signal?: AbortSignal): Promise<{ records: LandedPlan[]; next_after: string | null }> {
  const value = await procurementFetch(session, scope.workspace_id, scope, `${landedRoot}/orders/${encodeURIComponent(orderId)}?after=${encodeURIComponent(after)}`, { signal });
  if (!object(value) || !Array.isArray(value.records) || value.records.length > 4 || !(value.next_after === null || text(value.next_after))) invalid();
  const records = value.records.map((item) => parseLandedPlan(item, scope, orderId));
  if (new Set(records.map((plan) => plan.id)).size !== records.length || records.some((plan, index) => plan.id <= (index ? records[index - 1].id : after)) ||
      (value.next_after !== null && (records.length !== 4 || value.next_after !== records[3].id))) invalid();
  return { records, next_after: value.next_after as string | null };
}

export async function landedCommand(session: BrowserAdminSession, scope: ProcurementScope, orderId: string, command: PreparedScopedCommand): Promise<LandedPlan> {
  const plan = parseLandedPlan(await procurementFetch(session, scope.workspace_id, scope, command.path, { body: command.body }), scope, orderId);
  if (command.path === `${landedRoot}/plans`) {
    if (plan.phase !== 0 || command.body.order_id !== orderId || plan.number !== String(command.body.number).trim() ||
        plan.freight_minor !== command.body.freight_minor || plan.duty_minor !== command.body.duty_minor ||
        !Array.isArray(command.body.lines) || command.body.lines.length !== plan.allocations.length) invalid();
    const scale = (value: unknown) => {
      if (typeof value !== "string" || value.length > 64 || !/^(0|[1-9][0-9]*)(\.[0-9]{1,6})?$/.test(value.trim())) invalid();
      const [whole, fraction = ""] = value.trim().split(".");
      return BigInt(whole) * 1000000n + BigInt(fraction.padEnd(6, "0"));
    };
    const seen = new Set<string>();
    for (const line of command.body.lines) {
      if (!object(line) || !text(line.line_id) || seen.has(line.line_id)) invalid();
      seen.add(line.line_id);
      const allocation = plan.allocations.find((item) => item.order_line_id === line.line_id);
      if (!allocation || scale(allocation.quantity_text) !== scale(line.quantity)) invalid();
    }
  } else {
    const path = /^\/api\/v1\/landed-cost\/plans\/([^/]+)\/(review|post)$/.exec(command.path);
    if (!path || decodeURIComponent(path[1]) !== plan.id || plan.plan_digest !== command.body.expected_plan_digest ||
        plan.phase !== (path[2] === "review" ? 1 : 2)) invalid();
  }
  return plan;
}
