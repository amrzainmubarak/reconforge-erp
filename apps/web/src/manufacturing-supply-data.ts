import type { FinanceScope } from "./enterprise-finance-data";
import { financeRequest } from "./enterprise-finance-data";
import type { PreparedScopedCommand } from "./scoped-command";
import type { BrowserAdminSession } from "./types";

export const supplyRoot = "/api/v1/manufacturing-supply-plan";
export const supplyRead = ["manufacturing_supply_plan.read", "manufacturing_execution.read", "manufacturing_execution_v2.read", "inventory.read", "finance_core.read", "budget_control.read"];
export const supplyPermissions = {
  create: [...supplyRead, "manufacturing_supply_plan.manage"],
  approve: [...supplyRead, "manufacturing_supply_plan.approve", "inventory.manage"],
  cancel: [...supplyRead, "manufacturing_supply_plan.approve", "inventory.manage"],
  handoff: [...supplyRead, "manufacturing_supply_plan.manage", "manufacturing_execution.manage", "manufacturing_execution_v2.manage", "inventory.manage"],
};
export const supplyObject = (value: unknown): value is Record<string, unknown> => value !== null && typeof value === "object" && !Array.isArray(value);
const exact = (value: unknown): value is string => typeof value === "string" && /^(0|[1-9]\d{0,18})$/.test(value) && BigInt(value) <= 9000000000000000000n;
const digest = (value: unknown): value is string => typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
function invalid(): never { throw new Error("manufacturing_supply_evidence_invalid"); }
export function supplyCanonical(value: unknown, key = ""): string {
  if ((key.endsWith("_minor") || key.endsWith("_scaled") || key === "rate_minor_per_hour") && exact(value)) return value;
  if (key === "unit_prices_minor" && Array.isArray(value)) return `[${value.map(part => { if (!exact(part)) invalid(); return part; }).join(",")}]`;
  if (key === "unit_price_ceilings_minor" && supplyObject(value)) return `{${Object.keys(value).sort().map(name => { if (!exact(value[name])) invalid(); return `${JSON.stringify(name)}:${value[name]}`; }).join(",")}}`;
  if (Array.isArray(value)) return `[${value.map(part => supplyCanonical(part)).join(",")}]`;
  if (supplyObject(value)) return `{${Object.keys(value).sort().map(name => `${JSON.stringify(name)}:${supplyCanonical(value[name], name)}`).join(",")}}`;
  if (value === null || typeof value === "string" || typeof value === "boolean" || typeof value === "number" && Number.isSafeInteger(value)) return JSON.stringify(value);
  return invalid();
}
export async function supplySeal(value: unknown, expected: unknown) {
  if (!digest(expected)) invalid();
  const hash = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(supplyCanonical(value)));
  if ([...new Uint8Array(hash)].map(part => part.toString(16).padStart(2, "0")).join("") !== expected) invalid();
}
export function supplyPlainCanonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(supplyPlainCanonical).join(",")}]`;
  if (supplyObject(value)) return `{${Object.keys(value).sort().map(key => `${JSON.stringify(key)}:${supplyPlainCanonical(value[key])}`).join(",")}}`;
  if (value === null || typeof value === "string" || typeof value === "boolean" || typeof value === "number" && Number.isSafeInteger(value)) return JSON.stringify(value);
  return invalid();
}
async function plainSeal(value: unknown, expected: unknown) {
  if (!digest(expected)) invalid();
  const hash = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(supplyPlainCanonical(value)));
  if ([...new Uint8Array(hash)].map(part => part.toString(16).padStart(2, "0")).join("") !== expected) invalid();
}
export interface SupplyRequirement extends Record<string, unknown> {
  id: string; item_code: string; uom_code: string; quantity_precision: number; gross_quantity_scaled: string;
  gross_quantity: string; source_digest: string; coverage: { onhand_reserved_scaled: string; shortage_quantity_scaled: string } | null;
}
export interface SupplyPlan extends Record<string, unknown>, FinanceScope {
  id: string; number: string; phase: number; row_version: number; source_digest: string; creator_id: string;
  reviewer_actor_id: string | null; planned_requirements: SupplyRequirement[]; stock_claims: Array<Record<string, unknown>>;
  procurement_claims: Array<Record<string, unknown>>; manufacturing_order_id: string | null; material_order_id: string | null;
  unit_price_ceilings_minor: Record<string, string>; command_request: { material: Record<string, unknown> }; routing_id: string; budget_id: string;
  monetary_policy: { precision: number }; currency_code: string;
}
export async function parseSupplyPlan(value: unknown, scope: FinanceScope): Promise<SupplyPlan> {
  if (!supplyObject(value) || value.schema_version !== "manufacturing-supply-plan-v1" || !/^MSP1-[A-F0-9]{32}$/.test(String(value.id)) || !digest(value.source_digest)
      || !Number.isInteger(value.phase) || ![0, 1, 2, 3].includes(Number(value.phase)) || !Number.isInteger(value.row_version)
      || Number(value.row_version) < 1 || typeof value.creator_id !== "string" || !supplyObject(value.command_request)
      || !supplyObject(value.command_request.material) || !supplyObject(value.unit_price_ceilings_minor) || !supplyObject(value.monetary_policy)
      || !Number.isInteger(value.monetary_policy.precision) || Number(value.monetary_policy.precision) < 0 || Number(value.monetary_policy.precision) > 8
      || typeof value.currency_code !== "string" || !/^[A-Z]{3}$/.test(value.currency_code)) invalid();
  for (const [key, expected] of Object.entries(scope)) if (value[key] !== expected) invalid();
  const dynamic = ["source_digest", "phase", "row_version", "reviewer_actor_id", "material_order_id", "manufacturing_order_id", "planned_requirements", "stock_claims", "procurement_claims"];
  await supplySeal(Object.fromEntries(Object.entries(value).filter(([key]) => !dynamic.includes(key))), value.source_digest);
  if (!Array.isArray(value.planned_requirements) || !Array.isArray(value.requirements) || value.planned_requirements.length !== value.requirements.length
      || value.planned_requirements.length < 1 || value.planned_requirements.length > 100 || !Array.isArray(value.stock_claims)
      || !Array.isArray(value.procurement_claims) || value.stock_claims.length > 2000 || value.procurement_claims.length > 10000) invalid();
  if (value.phase === 0 && value.reviewer_actor_id !== null || [1, 2].includes(Number(value.phase)) && (typeof value.reviewer_actor_id !== "string" || value.reviewer_actor_id === value.creator_id)) invalid();
  const ids = new Set<string>();
  for (const row of value.planned_requirements) {
    if (!supplyObject(row) || row.schema_version !== "manufacturing-planned-requirement-v1" || typeof row.id !== "string" || ids.has(row.id) || row.plan_id !== value.id || row.plan_digest !== value.source_digest
        || !supplyObject(row.scope) || Object.entries(scope).some(([key, expected]) => row.scope && (row.scope as Record<string, unknown>)[key] !== expected)
        || !exact(row.gross_quantity_scaled) || !Number.isInteger(row.quantity_precision) || Number(row.quantity_precision) < 0 || Number(row.quantity_precision) > 6) invalid();
    ids.add(row.id);
    await supplySeal(Object.fromEntries(Object.entries(row).filter(([key]) => !["source_digest", "coverage", "coverage_digest"].includes(key))), row.source_digest);
    if (value.reviewer_actor_id !== null) {
      if (!supplyObject(row.coverage) || row.coverage.schema_version !== "manufacturing-supply-coverage-v1" || row.coverage.requirement_id !== row.id || row.coverage.requirement_digest !== row.source_digest || row.coverage.gross_quantity_scaled !== row.gross_quantity_scaled || !exact(row.coverage.onhand_reserved_scaled) || !exact(row.coverage.shortage_quantity_scaled)
          || BigInt(row.coverage.onhand_reserved_scaled) + BigInt(row.coverage.shortage_quantity_scaled) !== BigInt(row.gross_quantity_scaled)) invalid();
      await supplySeal(row.coverage, row.coverage_digest);
    } else if (row.coverage !== null) invalid();
  }
  const claimIds = new Set<string>();
  for (const claim of value.stock_claims) {
    if (!supplyObject(claim) || typeof claim.id !== "string" || claimIds.has(claim.id) || !ids.has(String(claim.requirement_id)) || !exact(claim.quantity_scaled)
        || claim.state !== (value.phase === 2 ? "HandedOff" : value.phase === 3 ? "Released" : "Active")) invalid();
    claimIds.add(claim.id);
  }
  if (value.phase === 2 ? !/^ME2-[A-F0-9]{32}$/.test(String(value.manufacturing_order_id)) || typeof value.material_order_id !== "string"
      : value.manufacturing_order_id !== null || value.material_order_id !== null) invalid();
  return value as SupplyPlan;
}
export async function supplyRequest(session: BrowserAdminSession, scope: FinanceScope, path: string, command?: PreparedScopedCommand, signal?: AbortSignal) {
  return financeRequest(session, scope, path, command?.body, signal);
}
export interface SupplyCommandBinding { actorId: string; previousVersion: number | null; }
function quantityRequestText(value: unknown): string {
  if (typeof value !== "string" || !/^\d+(?:\.\d{1,6})?$/.test(value.trim())) invalid();
  const [whole, fraction = ""] = value.trim().split("."); const part = fraction.replace(/0+$/, "");
  return `${BigInt(whole)}${part ? "." + part : ""}`;
}
function retainedOperationRequest(operation: string, command: PreparedScopedCommand, source: SupplyPlan, nativeOwner: unknown): Record<string, unknown> {
  const body = Object.fromEntries(Object.entries(command.body).filter(([key]) => key !== "command_id"));
  const reason = typeof body.reason === "string" ? body.reason.trim() : body.reason;
  if (["approve", "cancel"].includes(operation)) return { id: source.id, ...body, reason };
  if (operation === "handoff") return { id: source.id, expected_digest: body.expected_digest, reason,
    native_request: { schema_version: "manufacturing-order-v2", material: { ...source.command_request.material, posting_date: body.posting_date },
      routing_id: source.routing_id, claims: body.claims, ...Object.fromEntries(["workspace_id", "organization_id", "legal_entity_id", "organization_code", "entity_code"].map(key => [key, source[key]])) } };
  if (operation === "source-create") {
    const order: Record<string, unknown> = Object.fromEntries(Object.entries(body).filter(([key]) => !["expected_digest", "budget_id", "reason", "requirement_ids"].includes(key)));
    order.workspace = source.workspace_id; order.organization_code = source.organization_code; order.entity_code = source.entity_code;
    if (!Array.isArray(body.lines)) invalid();
    return { id: source.id, expected_digest: body.expected_digest, requirement_ids: body.requirement_ids,
      native_request: { budget_id: body.budget_id, order, reason, requirements: body.lines.map(() => null) } };
  }
  if (operation.startsWith("source-")) return { id: source.id, native_request: operation === "source-quote"
    ? { requisition_id: nativeOwner, expected_version: body.expected_version, quotation: { supplier_code: body.supplier_code, unit_prices_minor: body.unit_prices_minor, valid_until: body.valid_until, reason } }
    : { requisition_id: nativeOwner, ...body, reason } };
  const nativeOperation = ({ "purchase-submit": "submit-order", "purchase-approve": "approve-order", "receive-prepare": "prepare-receipt-line",
    "receive-review": "review-receipt", "receive-commit": "receive", "invoice-match": "match-invoice-lines", "invoice-approve": "approve-invoice",
    "invoice-prepare": "prepare-accrual", "invoice-review": "review-accrual", "invoice-post": "post-accrual" } as Record<string, string>)[operation];
  if (!nativeOperation) invalid();
  let native: Record<string, unknown> = { ...body, reason };
  if (operation === "receive-prepare") native.quantity = quantityRequestText(body.quantity);
  else if (operation === "invoice-match") { if (!Array.isArray(body.lines)) invalid(); native.lines = body.lines.map(line => { if (!supplyObject(line)) invalid(); return { ...line, quantity: quantityRequestText(line.quantity) }; }); }
  else if (operation === "invoice-post") native = { order_id: nativeOwner, invoice_id: body.document_id, expected_order_version: body.expected_version, expected_budget_version: body.expected_budget_version, reason };
  else if (!Object.hasOwn(native, "document_id")) native.document_id = null;
  return { id: source.id, order_id: nativeOwner, native_operation: nativeOperation, native_request: native };
}
export async function parseSupplyCommandAck(value: unknown, command: PreparedScopedCommand, scope: FinanceScope, binding: SupplyCommandBinding): Promise<SupplyPlan> {
  if (!supplyObject(value) || !supplyObject(value.command_ack) || !supplyObject(value.submitted_request)
      || supplyPlainCanonical(value.submitted_request) !== supplyPlainCanonical(command.body)) invalid();
  const ack = value.command_ack, source = await parseSupplyPlan(value.source, scope);
  await plainSeal(value.submitted_request, value.submitted_request_digest);
  await plainSeal({ source: value.source, ...(Object.hasOwn(value, "native_response") ? { native_response: value.native_response } : {}) }, ack.response_digest);
  if (ack.schema_version !== "manufacturing-supply-command-ack-v1" || ack.command_id !== command.body.command_id || ack.actor_id !== binding.actorId
      || ack.plan_id !== source.id || ack.source_digest !== source.source_digest || ack.version !== source.row_version
      || !supplyObject(ack.scope) || Object.entries(scope).some(([key, expected]) => (ack.scope as Record<string, unknown>)[key] !== expected)
      || !supplyObject(ack.request_json) || ack.request_json.actor_id !== binding.actorId || ack.request_json.operation !== ack.operation) invalid();
  await supplySeal(ack.request_json, ack.request_digest);
  const relative = command.path.slice(supplyRoot.length), create = command.path === `${supplyRoot}/plans`;
  const subject = /^\/plans\/(MSP1-[A-F0-9]{32})\/(.+)$/.exec(relative);
  if (!create && (!subject || subject[1] !== source.id)) invalid();
  let operation = create ? "create" : subject![2];
  if (operation === "requisitions") operation = "source-create";
  else if (operation.startsWith("requisitions/")) operation = "source-" + operation.split("/")[2];
  else if (operation.startsWith("purchases/")) operation = operation.split("/")[2];
  const phase = operation === "create" ? 0 : operation === "cancel" ? 3 : operation === "handoff" ? 2 : 1;
  if (ack.operation !== operation || source.phase !== phase || source.row_version !== (create ? 1 : (binding.previousVersion ?? -2) + 1)
      || command.body.expected_digest !== undefined && command.body.expected_digest !== source.source_digest) invalid();
  if (operation === "create") {
    if (source.creator_id !== binding.actorId || !Array.isArray(command.body.unit_price_ceilings_minor)) invalid();
    const ceilings: Record<string, unknown> = {};
    for (const line of command.body.unit_price_ceilings_minor) { if (!supplyObject(line) || typeof line.item_code !== "string") invalid(); ceilings[line.item_code.trim()] = line.unit_price_minor; }
    if (supplyPlainCanonical(ceilings) !== supplyPlainCanonical(source.unit_price_ceilings_minor)
        || command.body.routing_id !== source.routing_id || command.body.budget_id !== source.budget_id) invalid();
    const implicit = new Set(["schema_version", "workspace_id", "organization_id", "legal_entity_id", "organization_code", "entity_code"]);
    for (const [key, original] of Object.entries(source.command_request.material)) if (!implicit.has(key)
        && (typeof command.body[key] === "string" ? String(command.body[key]).trim() : command.body[key]) !== original) invalid();
    if (supplyCanonical(ack.request_json.request) !== supplyCanonical(source.command_request)) invalid();
  } else {
    if (!supplyObject(ack.request_json.request) || ack.request_json.request.id !== source.id) invalid();
    if (supplyCanonical(ack.request_json.request) !== supplyCanonical(retainedOperationRequest(operation, command, source, ack.native_owner_id))) invalid();
    if (operation === "approve" && source.reviewer_actor_id !== binding.actorId) invalid();
  }
  const kind = operation.startsWith("source-") ? "SRC" : operation === "handoff" ? "ME2" : operation === "invoice-post" ? "BPC" : ["create", "approve", "cancel"].includes(operation) ? null : "PP";
  if (ack.native_kind !== kind) invalid();
  if (kind === null) { if (ack.native_owner_id !== null || ack.native_command_id !== null || Object.hasOwn(value, "native_response")) invalid(); }
  else {
    if (typeof ack.native_owner_id !== "string" || typeof ack.native_command_id !== "string" || !supplyObject(value.native_response)) invalid();
    const native = value.native_response;
    if (kind === "PP") { if (!supplyObject(native.order) || native.order.id !== ack.native_owner_id) invalid(); }
    else if (native.id !== ack.native_owner_id) invalid();
    if (kind === "ME2" && (native.id !== source.manufacturing_order_id || native.material_order_id !== source.material_order_id || native.creator_id !== binding.actorId || native.phase !== 0)) invalid();
    if (subject && subject[2].includes("/")) { const owner = subject[2].split("/")[1]; if (owner && owner !== ack.native_owner_id) invalid(); }
  }
  return source;
}
export function scaledSupplyText(value: string, precision: number) {
  if (!exact(value) || !Number.isInteger(precision) || precision < 0 || precision > 6) invalid();
  const digits = value.padStart(precision + 1, "0"); return precision ? `${digits.slice(0, -precision)}.${digits.slice(-precision)}` : digits;
}

export const supplyOperationPermissions: Record<string, string[]> = {
  "approve": ["budget_control.read", "finance_core.read", "inventory.manage", "inventory.read", "manufacturing_execution.read", "manufacturing_execution_v2.read", "manufacturing_supply_plan.approve", "manufacturing_supply_plan.read"],
  "cancel": ["budget_control.read", "finance_core.read", "inventory.manage", "inventory.read", "manufacturing_execution.read", "manufacturing_execution_v2.read", "manufacturing_supply_plan.approve", "manufacturing_supply_plan.read"],
  "create": ["budget_control.read", "finance_core.read", "inventory.read", "manufacturing_execution.read", "manufacturing_execution_v2.read", "manufacturing_supply_plan.manage", "manufacturing_supply_plan.read"],
  "handoff": ["budget_control.read", "finance_core.read", "inventory.manage", "inventory.read", "manufacturing_execution.manage", "manufacturing_execution.read", "manufacturing_execution_v2.manage", "manufacturing_execution_v2.read", "manufacturing_supply_plan.manage", "manufacturing_supply_plan.read"],
  "invoice-approve": ["budget_control.manage", "budget_control.read", "finance_core.read", "inventory.read", "manufacturing_execution.read", "manufacturing_execution_v2.read", "manufacturing_supply_plan.approve", "manufacturing_supply_plan.read", "payables.approve"],
  "invoice-match": ["budget_control.manage", "budget_control.read", "finance_core.read", "inventory.read", "manufacturing_execution.read", "manufacturing_execution_v2.read", "manufacturing_supply_plan.manage", "manufacturing_supply_plan.read", "payables.manage", "payables.match"],
  "invoice-post": ["budget_control.manage", "budget_control.read", "finance_core.post", "finance_core.read", "inventory.read", "manufacturing_execution.read", "manufacturing_execution_v2.read", "manufacturing_supply_plan.post", "manufacturing_supply_plan.read", "payables.approve"],
  "invoice-prepare": ["budget_control.manage", "budget_control.read", "finance_core.manage", "finance_core.read", "inventory.read", "manufacturing_execution.read", "manufacturing_execution_v2.read", "manufacturing_supply_plan.manage", "manufacturing_supply_plan.read", "payables.manage"],
  "invoice-review": ["budget_control.manage", "budget_control.read", "finance_core.read", "finance_core.validate", "inventory.read", "manufacturing_execution.read", "manufacturing_execution_v2.read", "manufacturing_supply_plan.approve", "manufacturing_supply_plan.read", "payables.approve"],
  "purchase-approve": ["budget_control.manage", "budget_control.read", "finance_core.read", "inventory.read", "manufacturing_execution.read", "manufacturing_execution_v2.read", "manufacturing_supply_plan.approve", "manufacturing_supply_plan.read", "payables.approve"],
  "purchase-submit": ["budget_control.manage", "budget_control.read", "finance_core.read", "inventory.read", "manufacturing_execution.read", "manufacturing_execution_v2.read", "manufacturing_supply_plan.manage", "manufacturing_supply_plan.read", "payables.manage"],
  "receive": ["budget_control.read", "finance_core.read", "inventory.post", "inventory.read", "manufacturing_execution.read", "manufacturing_execution_v2.read", "manufacturing_supply_plan.post", "manufacturing_supply_plan.read", "payables.read"],
  "receive-commit": ["budget_control.manage", "budget_control.read", "finance_core.post", "finance_core.read", "inventory.post", "inventory.read", "inventory.valuation.approve", "manufacturing_execution.read", "manufacturing_execution_v2.read", "manufacturing_supply_plan.post", "manufacturing_supply_plan.read", "payables.manage"],
  "receive-prepare": ["budget_control.manage", "budget_control.read", "finance_core.manage", "finance_core.read", "inventory.manage", "inventory.read", "inventory.valuation.manage", "manufacturing_execution.read", "manufacturing_execution_v2.read", "manufacturing_supply_plan.manage", "manufacturing_supply_plan.read", "payables.manage"],
  "receive-review": ["budget_control.manage", "budget_control.read", "finance_core.read", "finance_core.validate", "inventory.post", "inventory.read", "inventory.valuation.approve", "manufacturing_execution.read", "manufacturing_execution_v2.read", "manufacturing_supply_plan.approve", "manufacturing_supply_plan.read", "payables.approve"],
  "source": ["budget_control.read", "finance_core.read", "inventory.read", "manufacturing_execution.read", "manufacturing_execution_v2.read", "manufacturing_supply_plan.manage", "manufacturing_supply_plan.read", "procurement_sourcing.read"],
  "source-award": ["budget_control.manage", "budget_control.read", "finance_core.read", "inventory.read", "manufacturing_execution.read", "manufacturing_execution_v2.read", "manufacturing_supply_plan.post", "manufacturing_supply_plan.read", "payables.manage", "payables.read", "procurement_sourcing.award", "procurement_sourcing.read"],
  "source-cancel": ["budget_control.read", "finance_core.read", "inventory.read", "manufacturing_execution.read", "manufacturing_execution_v2.read", "manufacturing_supply_plan.approve", "manufacturing_supply_plan.read", "payables.read", "procurement_sourcing.approve", "procurement_sourcing.read"],
  "source-create": ["budget_control.read", "finance_core.read", "inventory.read", "manufacturing_execution.read", "manufacturing_execution_v2.read", "manufacturing_supply_plan.manage", "manufacturing_supply_plan.read", "payables.read", "procurement_sourcing.manage", "procurement_sourcing.read"],
  "source-open-rfq": ["budget_control.read", "finance_core.read", "inventory.read", "manufacturing_execution.read", "manufacturing_execution_v2.read", "manufacturing_supply_plan.approve", "manufacturing_supply_plan.read", "payables.read", "procurement_sourcing.approve", "procurement_sourcing.read"],
  "source-quote": ["budget_control.read", "finance_core.read", "inventory.read", "manufacturing_execution.read", "manufacturing_execution_v2.read", "manufacturing_supply_plan.manage", "manufacturing_supply_plan.read", "payables.read", "procurement_sourcing.manage", "procurement_sourcing.read"],
  "source-review-selection": ["budget_control.read", "finance_core.read", "inventory.read", "manufacturing_execution.read", "manufacturing_execution_v2.read", "manufacturing_supply_plan.approve", "manufacturing_supply_plan.read", "payables.read", "procurement_sourcing.approve", "procurement_sourcing.read"],
};
