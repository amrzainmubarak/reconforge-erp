import { salesRequest, type SalesScope } from "./sales-revenue-data";
import { prepareScopedCommand, type ScopedJsonValue } from "./scoped-command";
import type { BrowserAdminSession } from "./types";

export interface PendingCollection { id: string; plan_digest: string; phase: 0 | 1; amount_minor: string; preparer_actor_id: string; reviewer_actor_id: string | null }
export interface CollectionPlan extends SalesScope {
  id: string; source_id: string; amount_minor: string; allocated_before_minor: string; status: "Prepared" | "Reviewed" | "Posted" | "Cancelled";
  phase: 0 | 1 | 2 | 3;
  plan_digest: string; preparer_actor_id: string; reviewer_actor_id: string | null; posting_effect_id: string | null; receipt_id: string | null;
  cancelled_actor_id?: string; cancellation_reason?: string;
}
export interface CollectionCommand { readonly path: string; readonly scope: Readonly<SalesScope>; readonly body: Readonly<Record<string, ScopedJsonValue>> }
export function prepareCollectionCommand(scope: SalesScope, path: string, fields: Record<string, ScopedJsonValue>): CollectionCommand {
  if (!/^\/api\/v1\/commercial-collections\/plans(?:\/[^/?#]+\/(?:review|post|cancel))?$/.test(path) || Object.hasOwn(fields, "command_id")) throw new Error("collection_command_invalid");
  return Object.freeze({ ...prepareScopedCommand(path, fields), scope: Object.freeze({ ...scope }) });
}
export async function executeCollectionCommand(session: BrowserAdminSession, command: CollectionCommand): Promise<CollectionPlan> {
  const response = await salesRequest(session, command.scope, command.path, command.body) as { plan?: CollectionPlan };
  const plan = response.plan;
  if (!plan || Object.entries(command.scope).some(([key, value]) => plan[key as keyof SalesScope] !== value) ||
      !/^CA1-[a-f0-9]{32}$/.test(plan.id) || !/^[a-f0-9]{64}$/.test(plan.plan_digest) ||
      !Number.isInteger(plan.phase) || plan.phase < 0 || plan.phase > 3 || ["Prepared", "Reviewed", "Posted", "Cancelled"][plan.phase] !== plan.status || !/^[1-9]\d{0,18}$/.test(plan.amount_minor) ||
      !/^(0|[1-9]\d{0,18})$/.test(plan.allocated_before_minor) || BigInt(plan.amount_minor) > 9000000000000000000n ||
      (command.body.source_id !== undefined && plan.source_id !== command.body.source_id) ||
      (command.body.expected_plan_digest !== undefined && plan.plan_digest !== command.body.expected_plan_digest)) throw new Error("collection_response_invalid");
  if (plan.status === "Posted" && (!plan.receipt_id || !plan.posting_effect_id || !plan.reviewer_actor_id)) throw new Error("collection_response_invalid");
  if (plan.status === "Cancelled" && (!plan.cancelled_actor_id || !plan.cancellation_reason?.trim() || plan.receipt_id !== null || plan.posting_effect_id !== null)) throw new Error("collection_response_invalid");
  if (command.path.endsWith("/cancel") && plan.status !== "Cancelled") throw new Error("collection_response_invalid");
  return plan;
}
