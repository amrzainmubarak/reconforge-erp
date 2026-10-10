import { procurementFetch, type ProcurementScope } from "./procurement-data";
import type { PreparedScopedCommand } from "./scoped-command";
import type { BrowserAdminSession } from "./types";

export const commitmentRoot = "/api/v1/procurement-commitments";
export interface ProcurementCommitment {
  id: string; order_id: string; number: string; budget_id: string; commitment_id: string;
  workspace_id: string; organization_id: string; legal_entity_id: string; preparer_actor_id: string;
  currency_code: string; original_minor: string; reserved_minor: string; consumed_minor: string; released_minor: string;
  remaining_minor: string; budget_version: number; status: "Reserved" | "Consumed" | "Released";
  evidence: { budget_event_id: string; audit_event_id: string; outbox_event_id: string; request_digest: string };
}
const object = (value: unknown): value is Record<string, unknown> => value !== null && typeof value === "object" && !Array.isArray(value);
const text = (value: unknown): value is string => typeof value === "string" && value.length > 0 && value.length <= 160 && !/[\u0000-\u001f\u007f]/.test(value);
const money = (value: unknown): value is string => typeof value === "string" && /^(0|[1-9][0-9]{0,18})$/.test(value) && BigInt(value) <= 9000000000000000000n;
function invalid(): never { throw new Error("procurement_commitment_contract_invalid"); }

export function sameProcurementQuantity(left: string, right: string): boolean {
  const scaled = (value: string) => {
    if (!/^(0|[1-9][0-9]*)(\.[0-9]{1,6})?$/.test(value) || value.length > 64) invalid();
    const [whole, fraction = ""] = value.split(".");
    return BigInt(whole) * 1000000n + BigInt(fraction.padEnd(6, "0"));
  };
  return scaled(left) === scaled(right);
}

export function parseProcurementCommitment(value: unknown, scope: ProcurementScope, orderId?: string): ProcurementCommitment {
  if (!object(value) || !["id", "order_id", "number", "budget_id", "commitment_id", "preparer_actor_id"].every((key) => text(value[key])) ||
      value.id !== value.order_id || (orderId !== undefined && value.order_id !== orderId) ||
      value.workspace_id !== scope.workspace_id || value.organization_id !== scope.organization_id || value.legal_entity_id !== scope.legal_entity_id ||
      value.currency_code !== scope.currency_code || !String(value.number).startsWith("BPC1-") ||
      !Number.isSafeInteger(value.budget_version) || Number(value.budget_version) < 4 ||
      !["original_minor", "reserved_minor", "consumed_minor", "released_minor", "remaining_minor"].every((key) => money(value[key])) ||
      value.original_minor === "0" || value.reserved_minor !== value.remaining_minor ||
      BigInt(String(value.original_minor)) !== BigInt(String(value.consumed_minor)) + BigInt(String(value.released_minor)) + BigInt(String(value.remaining_minor)) ||
      !["Reserved", "Consumed", "Released"].includes(String(value.status)) ||
      (value.status === "Reserved" ? value.remaining_minor === "0" || value.released_minor !== "0" : value.remaining_minor !== "0") ||
      (value.status === "Consumed" && value.released_minor !== "0") || (value.status === "Released" && value.released_minor === "0") ||
      !object(value.evidence) || !["budget_event_id", "audit_event_id", "outbox_event_id"].every((key) => text((value.evidence as Record<string, unknown>)[key])) ||
      typeof value.evidence.request_digest !== "string" || !/^[0-9a-f]{64}$/.test(value.evidence.request_digest)) invalid();
  return value as unknown as ProcurementCommitment;
}

export function newestCommitment(current: ProcurementCommitment | null, incoming: ProcurementCommitment): ProcurementCommitment {
  if (!current || current.id !== incoming.id) return incoming;
  if (current.budget_version > incoming.budget_version || current.status === "Released") return current;
  if (current.budget_version === incoming.budget_version &&
      ((Object.keys(current) as (keyof ProcurementCommitment)[]).some((key) => key !== "evidence" && current[key] !== incoming[key]) ||
      (Object.keys(current.evidence) as (keyof ProcurementCommitment["evidence"])[]).some((key) => current.evidence[key] !== incoming.evidence[key]))) invalid();
  return incoming;
}

export async function procurementCommitmentGet(session: BrowserAdminSession, scope: ProcurementScope, orderId: string, signal?: AbortSignal): Promise<ProcurementCommitment> {
  return parseProcurementCommitment(await procurementFetch(session, scope.workspace_id, scope,
    `${commitmentRoot}/orders/${encodeURIComponent(orderId)}`, { signal }), scope, orderId);
}

export async function procurementCommitmentCommand(session: BrowserAdminSession, scope: ProcurementScope, command: PreparedScopedCommand): Promise<ProcurementCommitment> {
  const match = /^\/api\/v1\/procurement-commitments\/orders\/([^/]+)\/(consume|release)$/.exec(command.path);
  if (command.path !== `${commitmentRoot}/orders` && !match) invalid();
  const result = parseProcurementCommitment(await procurementFetch(session, scope.workspace_id, scope, command.path, { body: command.body }), scope,
    match ? decodeURIComponent(match[1]) : undefined);
  if (command.path === `${commitmentRoot}/orders`) {
    if (result.status !== "Reserved" || result.number !== String(command.body.number).trim() || result.budget_id !== command.body.budget_id ||
        result.budget_version !== Number(command.body.expected_budget_version) + 1 || result.consumed_minor !== "0" || result.released_minor !== "0") invalid();
  } else if (result.budget_version !== Number(command.body.expected_budget_version) + 1 ||
      (match?.[2] === "release" ? result.status !== "Released" : result.released_minor !== "0")) invalid();
  return result;
}
