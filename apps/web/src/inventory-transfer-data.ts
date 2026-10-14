import { financeRequest, type FinanceScope } from "./enterprise-finance-data";
import type { PreparedScopedCommand } from "./scoped-command";
import type { BrowserAdminSession } from "./types";

export const transferRoot = "/api/v1/inventory-transfer";
export const transferRead = ["inventory_transfer.read", "inventory.read", "inventory.valuation.read", "finance_core.read"];
export const transferPermissions: Record<string, string[]> = {
  create: [...transferRead, "inventory_transfer.manage", "inventory.manage"],
  "inverse-create": [...transferRead, "inventory_transfer.manage", "inventory.manage"],
  review: [...transferRead, "inventory_transfer.approve", "inventory.manage"],
  post: [...transferRead, "inventory_transfer.post", "inventory.post"],
  cancel: [...transferRead, "inventory_transfer.approve", "inventory.manage"],
};
export const transferObject = (value: unknown): value is Record<string, unknown> => value !== null && typeof value === "object" && !Array.isArray(value);
const digest = (value: unknown): value is string => typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
const text = (value: unknown): value is string => typeof value === "string" && value.length > 0 && value.length <= 500 && value === value.trim() && !/[\x00-\x1f\x7f]/.test(value);
const exact = (value: unknown): value is string => typeof value === "string" && /^(0|[1-9]\d{0,18})$/.test(value) && BigInt(value) <= 9000000000000000000n;
function invalid(): never { throw new Error("inventory_transfer_evidence_invalid"); }
export function transferCanonical(value: unknown, originals = false, key = ""): string {
  if (originals && (key.endsWith("_minor") || key.endsWith("_scaled")) && exact(value)) return value;
  if (originals && key === "exposed_amounts_minor" && Array.isArray(value)) return `[${value.map(part => { if (!exact(part)) invalid(); return part; }).join(",")}]`;
  if (Array.isArray(value)) return `[${value.map(part => transferCanonical(part, originals)).join(",")}]`;
  if (transferObject(value)) return `{${Object.keys(value).sort().map(name => `${JSON.stringify(name)}:${transferCanonical(value[name], originals, name)}`).join(",")}}`;
  if (value === null || typeof value === "string" || typeof value === "boolean" || typeof value === "number" && Number.isSafeInteger(value)) return JSON.stringify(value);
  return invalid();
}
export async function transferDigest(value: unknown, originals = false): Promise<string> {
  const hash = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(transferCanonical(value, originals)));
  return [...new Uint8Array(hash)].map(part => part.toString(16).padStart(2, "0")).join("");
}
async function seal(value: unknown, expected: unknown, originals = true) {
  if (!digest(expected) || await transferDigest(value, originals) !== expected) invalid();
}
function scoped(value: unknown, scope: FinanceScope): value is FinanceScope {
  return transferObject(value) && Object.keys(value).length === 3 && Object.entries(scope).every(([key, expected]) => value[key] === expected);
}
export interface TransferCost extends Record<string, unknown> {
  monetary_policy: { currency_code: string; currency_precision: number };
  remaining_quantity_scaled: string; remaining_value_minor: string; sources: Array<Record<string, unknown>>;
}
export interface TransferSource extends Record<string, unknown> {
  id: string; number: string; scope: FinanceScope; item_code: string; uom_id: string; quantity: string; quantity_scaled: string;
  quantity_precision: number; from_location: string; to_location: string; from_location_id: string; to_location_id: string;
  native_movement_id: string; source_digest: string; row_version: number; phase: number; creator_actor_id: string;
  reviewer_actor_id: string | null; poster_actor_id: string | null; cost_snapshot: TransferCost; review_cost_snapshot: TransferCost | null;
  review_cost_digest: string | null; native_response: Record<string, unknown>; original: Record<string, unknown> | null;
  command_request: Record<string, unknown>;
}
function cost(value: unknown, scope: FinanceScope, tenantId: string): TransferCost {
  if (!transferObject(value) || value.schema_version !== "inventory-transfer-cost-v1" || !transferObject(value.monetary_policy)
      || !/^[A-Z]{3}$/.test(String(value.monetary_policy.currency_code)) || !Number.isInteger(value.monetary_policy.currency_precision)
      || Number(value.monetary_policy.currency_precision) < 0 || Number(value.monetary_policy.currency_precision) > 8
      || !exact(value.remaining_quantity_scaled) || !exact(value.remaining_value_minor) || !Array.isArray(value.sources)
      || value.sources.length < 1 || value.sources.length > 32) invalid();
  const ids = new Set<string>(); let quantity = 0n, minor = 0n;
  for (const source of value.sources) {
    if (!transferObject(source) || !transferObject(source.layer) || source.layer.tenant_id !== tenantId || !text(source.layer.id) || ids.has(source.layer.id)
        || !transferObject(source.receipt_plan) || source.receipt_plan.operation !== "Receipt" || !transferObject(source.receipt_plan.scope)
        || Object.entries(scope).some(([key, expected]) => (source.receipt_plan as Record<string, Record<string, unknown>>).scope[key] !== expected)
        || !transferObject(source.receipt_link) || source.receipt_link.cost_layer_id !== source.layer.id
        || source.receipt_link.plan_id !== source.receipt_plan.plan_id || !transferObject(source.valuation_document)
        || source.valuation_document.status !== "Approved" || !transferObject(source.valuation_line)
        || source.valuation_line.flow_direction !== "Inbound" || source.valuation_line.id !== source.layer.source_valuation_line_id
        || !transferObject(source.finance_entry) || source.finance_entry.status !== "Validated" || !transferObject(source.posting_effect)
        || source.posting_effect.entry_id !== source.finance_entry.id || source.posting_effect.source_id !== source.receipt_plan.plan_id
        || !Array.isArray(source.finance_lines) || source.finance_lines.length !== 2 || !Array.isArray(source.exposed_amounts_minor)
        || !source.exposed_amounts_minor.every(exact) || !exact(source.layer.remaining_quantity_scaled) || !exact(source.layer.remaining_value_minor)) invalid();
    if (transferCanonical(source.receipt_plan.currency_policy) !== transferCanonical(value.monetary_policy)) invalid();
    ids.add(source.layer.id); quantity += BigInt(source.layer.remaining_quantity_scaled); minor += BigInt(source.layer.remaining_value_minor);
  }
  if (quantity !== BigInt(value.remaining_quantity_scaled) || minor !== BigInt(value.remaining_value_minor)) invalid();
  return value as TransferCost;
}
export async function parseTransfer(value: unknown, scope: FinanceScope, tenantId: string): Promise<TransferSource> {
  if (!transferObject(value) || value.schema_version !== "inventory-transfer-v1" || !/^IT1-S-[A-F0-9]{32}$/.test(String(value.id))
      || !scoped(value.scope, scope) || !text(value.number) || !text(value.creator_actor_id) || !digest(value.source_digest)
      || ![0, 1, 2, 3].includes(Number(value.phase)) || !Number.isInteger(value.phase) || !Number.isInteger(value.row_version)
      || Number(value.row_version) < 1 || Number(value.row_version) > 3 || !exact(value.quantity_scaled) || value.quantity_scaled === "0"
      || !Number.isInteger(value.quantity_precision) || Number(value.quantity_precision) < 0 || Number(value.quantity_precision) > 6
      || !text(value.item_code) || !text(value.uom_id) || !text(value.native_movement_id) || !text(value.from_location_id)
      || !text(value.to_location_id) || value.from_location_id === value.to_location_id || !transferObject(value.command_request)
      || !transferObject(value.native_response) || !transferObject(value.native_response.head) || !Array.isArray(value.native_response.lines)
      || value.native_response.lines.length !== 1) invalid();
  const dynamic = ["source_digest", "phase", "row_version", "reviewer_actor_id", "poster_actor_id", "review_cost_snapshot", "review_cost_digest", "claim", "release", "native_response"];
  await seal(Object.fromEntries(Object.entries(value).filter(([key]) => !dynamic.includes(key))), value.source_digest);
  const originalCost = cost(value.cost_snapshot, scope, tenantId);
  if (value.phase === 0 && value.row_version !== 1 || value.phase === 1 && value.row_version !== 2
      || value.phase === 2 && value.row_version !== 3 || value.phase === 3 && value.row_version !== (value.reviewer_actor_id === null ? 2 : 3)) invalid();
  if (value.reviewer_actor_id === null) {
    if (![0, 3].includes(Number(value.phase)) || value.review_cost_snapshot !== null || value.review_cost_digest !== null || value.claim !== null || value.release !== null) invalid();
  } else {
    if (value.phase === 0 || !text(value.reviewer_actor_id) || value.reviewer_actor_id === value.creator_actor_id || !digest(value.review_cost_digest)) invalid();
    const reviewed = cost(value.review_cost_snapshot, scope, tenantId);
    if (transferCanonical(reviewed.monetary_policy) !== transferCanonical(originalCost.monetary_policy)) invalid();
    await seal(reviewed, value.review_cost_digest);
    if (!transferObject(value.claim) || !/^IT1-K-[A-F0-9]{32}$/.test(String(value.claim.id)) || value.claim.tenant_id !== tenantId
        || Object.entries(scope).some(([key, expected]) => (value.claim as Record<string, unknown>)[key] !== expected)
        || value.claim.transfer_id !== value.id || value.claim.quantity_scaled !== value.quantity_scaled
        || value.claim.location_id !== value.from_location_id || value.claim.item_id !== value.item_id || value.claim.uom_id !== value.uom_id
        || value.claim.quantity_precision !== value.quantity_precision || value.claim.created_version !== 2
        || value.claim.state !== (value.phase === 2 ? "Posted" : value.phase === 3 ? "Released" : "Active")) invalid();
    if (value.phase === 1 ? value.release !== null : !transferObject(value.release) || !/^IT1-R-[A-F0-9]{32}$/.test(String(value.release.id))
        || value.release.tenant_id !== tenantId || value.release.transfer_id !== value.id || value.release.created_version !== 3
        || Object.entries(scope).some(([key, expected]) => (value.release as Record<string, unknown>)[key] !== expected) || value.release.claim_id !== value.claim.id
        || value.release.purpose !== (value.phase === 2 ? "Post" : "Cancel") || value.release.target_movement_id !== (value.phase === 2 ? value.native_movement_id : null)) invalid();
  }
  const head = value.native_response.head, line = value.native_response.lines[0];
  if (!transferObject(line) || line.tenant_id !== tenantId || line.movement_id !== value.native_movement_id || !text(line.id)
      || head.tenant_id !== tenantId || Object.entries(scope).some(([key, expected]) => head[key] !== expected)
      || head.id !== value.native_movement_id || head.source_reference !== value.id || head.movement_type !== "Transfer"
      || head.source_type !== "Generated" || head.created_by !== value.creator_actor_id || head.status !== (value.phase === 2 ? "Posted" : "Draft")
      || line.item_id !== value.item_id || line.uom_id !== value.uom_id || line.quantity_scaled !== value.quantity_scaled
      || head.movement_number !== `IT1-${String(value.id).slice(-32)}` || head.period_id !== value.period_id || head.movement_date !== value.posting_date
      || head.row_version !== (value.phase === 2 ? 2 : 1) || line.inventory_lot_id !== null || line.line_number !== 1
      || line.quantity_precision !== value.quantity_precision || line.from_location_id !== value.from_location_id || line.to_location_id !== value.to_location_id) invalid();
  if (value.phase === 2 ? !text(value.poster_actor_id) || [value.creator_actor_id, value.reviewer_actor_id].includes(value.poster_actor_id)
      || head.posted_by !== value.poster_actor_id : value.poster_actor_id !== null) invalid();
  if (value.original !== null && (!transferObject(value.original) || !/^IT1-S-[A-F0-9]{32}$/.test(String(value.original.id)) || !digest(value.original.source_digest))) invalid();
  return value as TransferSource;
}
export interface TransferCommandBinding { actorId: string; tenantId: string; previousVersion: number | null; originalId?: string; }
export async function parseTransferAck(value: unknown, command: PreparedScopedCommand, scope: FinanceScope, binding: TransferCommandBinding): Promise<TransferSource> {
  if (!transferObject(value) || !transferObject(value.command_ack) || !transferObject(value.submitted_request)
      || transferCanonical(value.submitted_request) !== transferCanonical(command.body)) invalid();
  const ack = value.command_ack, source = await parseTransfer(value.source, scope, binding.tenantId);
  await seal(value.submitted_request, value.submitted_request_digest, false);
  await seal({ source: value.source, native_response: value.native_response }, ack.response_digest, false);
  if (transferCanonical(value.native_response) !== transferCanonical(source.native_response) || ack.schema_version !== "inventory-transfer-command-ack-v1"
      || ack.command_id !== command.body.command_id || ack.actor_id !== binding.actorId || ack.transfer_id !== source.id
      || ack.source_digest !== source.source_digest || ack.version !== source.row_version || !scoped(ack.scope, scope)
      || ack.native_movement_id !== source.native_movement_id || !transferObject(ack.request_json)
      || ack.request_json.actor_id !== binding.actorId || ack.request_json.operation !== ack.operation) invalid();
  await seal(ack.request_json, ack.request_digest);
  const body = Object.fromEntries(Object.entries(command.body).filter(([key]) => key !== "command_id"));
  const normalized = Object.fromEntries(Object.entries(body).map(([key, part]) => [key, typeof part === "string" ? part.trim() : part]));
  const create = command.path === `${transferRoot}/transfers`, subject = /^\/transfers\/(IT1-S-[A-F0-9]{32})\/(review|post|cancel|inverse)$/.exec(command.path.slice(transferRoot.length));
  if (!create && !subject) invalid();
  const operation = create ? "create" : subject![2] === "inverse" ? "inverse-create" : subject![2];
  const phase = ["create", "inverse-create"].includes(operation) ? 0 : operation === "review" ? 1 : operation === "post" ? 2 : 3;
  if (ack.operation !== operation || source.phase !== phase || source.row_version !== (["create", "inverse-create"].includes(operation) ? 1 : (binding.previousVersion ?? -2) + 1)) invalid();
  if (create) {
    const expected = { schema_version: "inventory-transfer-v1", ...normalized, scope };
    if (source.creator_actor_id !== binding.actorId || source.original !== null || transferCanonical(source.command_request) !== transferCanonical(expected)
        || transferCanonical(ack.request_json.request) !== transferCanonical(expected)) invalid();
  } else if (operation === "inverse-create") {
    const expected = { original_id: subject![1], ...normalized };
    if (binding.originalId !== subject![1] || source.creator_actor_id !== binding.actorId || source.original?.id !== subject![1]
        || source.original.source_digest !== body.expected_digest || source.original.version !== body.expected_version
        || transferCanonical(source.command_request) !== transferCanonical(expected) || transferCanonical(ack.request_json.request) !== transferCanonical(expected)) invalid();
  } else {
    if (subject![1] !== source.id || body.expected_digest !== source.source_digest || body.expected_version !== binding.previousVersion
        || transferCanonical(ack.request_json.request) !== transferCanonical({ id: source.id, ...normalized })) invalid();
    if (operation === "review" && source.reviewer_actor_id !== binding.actorId || operation === "post" && source.poster_actor_id !== binding.actorId) invalid();
    if (["post", "cancel"].includes(operation) && transferObject(source.release) && source.release.actor_id !== binding.actorId) invalid();
  }
  return source;
}
export function transferRequest(session: BrowserAdminSession, scope: FinanceScope, path: string, command?: PreparedScopedCommand, signal?: AbortSignal) {
  return financeRequest(session, scope, path, command?.body, signal);
}
export function transferMoney(minor: string, precision: number): string {
  if (!exact(minor) || !Number.isInteger(precision) || precision < 0 || precision > 8) invalid();
  const digits = minor.padStart(precision + 1, "0"); return precision ? `${digits.slice(0, -precision)}.${digits.slice(-precision)}` : digits;
}
