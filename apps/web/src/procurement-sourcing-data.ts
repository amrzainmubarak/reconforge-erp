import { procurementFetch, type ProcurementScope } from "./procurement-data";
import { sameProcurementQuantity } from "./procurement-commitment-data";
import type { BrowserAdminSession } from "./types";
import type { PreparedScopedCommand } from "./scoped-command";

export const sourcingRoot = "/api/v1/procurement-sourcing/requisitions";
export const sourcingStatuses = ["Draft", "OpenRFQ", "SelectionReviewed", "Awarded", "Cancelled"] as const;
export interface SourcingHead {
  schema_version: "procurement-sourcing-v1"; id: string; number: string; row_version: number; status: typeof sourcingStatuses[number];
  workspace_id: string; organization_id: string; legal_entity_id: string; currency_code: string; ceiling_minor: string; budget_id: string; source_digest: string;
  creator_actor_id: string; rfq_approver_actor_id: string | null; selection_reviewer_actor_id: string | null; award_actor_id: string | null;
  selected_quote_id: string | null; order_id: string | null; evidence: { audit_event_id: string; outbox_event_id: string; request_digest: string };
}
export interface SourcingLine { item_code: string; quantity: string; unit_price_minor: string; location_code: string; policy_code: string }
export interface SourcingOrder { number: string; supplier_code: string; currency_code: string; posting_date: string; period_id: string; journal_code: string; ap_account_code: string; cash_account_code: string; workspace: string; organization_code: string; entity_code: string; lines: SourcingLine[] }
export interface SourcingQuote { id: string; quote_digest: string; created_version: number; payload: {
  schema_version: "supplier-quotation-v1"; requisition_id: string; source_digest: string; supplier_id: string; registrar_actor_id: string;
  total_minor: string; order: SourcingOrder; quotation: { supplier_code: string; unit_prices_minor: string[]; valid_until: string; reason: string };
}; canonical_quote_json: string }
export interface SourcingDetail { head: SourcingHead; source: {
  schema_version: "procurement-sourcing-v1"; creator_actor_id: string; ceiling_minor: string; currency_precision: number;
  scope: { workspace_id: string; organization_id: string; legal_entity_id: string };
  request: { budget_id: string; reason: string; order: SourcingOrder; requirements: ({ requirement_id: string; requirement_digest: string } | null)[] };
  demand_masters: Record<string, unknown>[]; manufacturing_requirements: (Record<string, unknown> | null)[];
}; quotations: SourcingQuote[]; canonical_source_json: string }
const object = (v: unknown): v is Record<string, unknown> => v !== null && typeof v === "object" && !Array.isArray(v);
const text = (v: unknown): v is string => typeof v === "string" && v.length > 0 && v.length <= 500 && !/[\x00-\x1f\x7f]/.test(v);
const minor = (v: unknown): v is string => typeof v === "string" && /^[1-9][0-9]{0,18}$/.test(v) && BigInt(v) <= 9000000000000000000n;
const hash = (v: unknown): v is string => typeof v === "string" && /^[a-f0-9]{64}$/.test(v);
const version = (v: unknown): v is number => typeof v === "number" && Number.isSafeInteger(v) && v >= 1 && v <= 38;
function invalid(): never { throw new Error("procurement_sourcing_contract_invalid"); }
export function sourcingLineMinor(quantity: string, price: string): bigint {
  if (!minor(price) || quantity.length > 64 || !/^(0|[1-9]\d*)(?:\.\d+)?$/.test(quantity)) invalid();
  const [whole, fraction = ""] = quantity.split(".");
  const product = BigInt(whole + fraction) * BigInt(price), divisor = 10n ** BigInt(fraction.length);
  if (product <= 0n || product % divisor || product / divisor > 9000000000000000000n) invalid();
  return product / divisor;
}
function order(value: unknown, scope: ProcurementScope): SourcingOrder {
  if (!object(value) || !["number", "supplier_code", "posting_date", "period_id", "journal_code", "ap_account_code", "cash_account_code"].every(key => text(value[key])) ||
    value.workspace !== scope.workspace_id || value.organization_code !== scope.organization_code || value.entity_code !== scope.entity_code || value.currency_code !== scope.currency_code ||
    !Array.isArray(value.lines) || !value.lines.length || value.lines.length > 128) invalid();
  for (const row of value.lines) if (!object(row) || !["item_code", "quantity", "location_code", "policy_code"].every(key => text(row[key])) || !minor(row.unit_price_minor)) invalid();
  return value as unknown as SourcingOrder;
}
export function parseSourcingHead(value: unknown, scope: ProcurementScope): SourcingHead {
  if (!object(value) || value.schema_version !== "procurement-sourcing-v1" || !["id", "number", "budget_id", "creator_actor_id"].every(key => text(value[key])) ||
    !version(value.row_version) || !sourcingStatuses.includes(value.status as SourcingHead["status"]) || !minor(value.ceiling_minor) || !hash(value.source_digest) ||
    value.workspace_id !== scope.workspace_id || value.organization_id !== scope.organization_id || value.legal_entity_id !== scope.legal_entity_id || value.currency_code !== scope.currency_code ||
    !String(value.number).startsWith("SRC5-") || !object(value.evidence) || !text(value.evidence.audit_event_id) || !text(value.evidence.outbox_event_id) || !hash(value.evidence.request_digest)) invalid();
  for (const key of ["rfq_approver_actor_id", "selection_reviewer_actor_id", "award_actor_id", "selected_quote_id", "order_id"]) if (value[key] !== null && !text(value[key])) invalid();
  if ((value.status === "Draft") !== (value.row_version === 1) || (value.status !== "Draft" && value.status !== "Cancelled" && !value.rfq_approver_actor_id) ||
    (value.rfq_approver_actor_id !== null && value.rfq_approver_actor_id === value.creator_actor_id) ||
    ((["SelectionReviewed", "Awarded"].includes(String(value.status))) && (!value.selected_quote_id || !value.selection_reviewer_actor_id || value.selection_reviewer_actor_id === value.creator_actor_id)) ||
    (value.status === "Awarded" ? !value.order_id || !value.award_actor_id || [value.creator_actor_id, value.rfq_approver_actor_id, value.selection_reviewer_actor_id].includes(value.award_actor_id) : value.order_id !== null || value.award_actor_id !== null)) invalid();
  return value as unknown as SourcingHead;
}
function canonical(value: unknown, key = ""): string {
  if ((key.endsWith("_minor") || key.endsWith("_scaled")) && minor(value)) return value;
  if (Array.isArray(value)) return "[" + value.map(row => canonical(row, key === "unit_prices_minor" ? "unit_price_minor" : "")).join(",") + "]";
  if (object(value)) return "{" + Object.keys(value).sort().map(field => JSON.stringify(field) + ":" + canonical(value[field], field)).join(",") + "}";
  if (value === null || typeof value === "string" || typeof value === "boolean" || (typeof value === "number" && Number.isSafeInteger(value))) return JSON.stringify(value);
  return invalid();
}
async function verifyCanonical(payload: unknown, raw: unknown, digest: string) {
  if (typeof raw !== "string" || raw.length > 262144 || canonical(payload) !== raw) invalid();
  const actual = [...new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(raw)))].map(byte => byte.toString(16).padStart(2, "0")).join("");
  if (actual !== digest) invalid();
}
export async function parseSourcingDetail(value: unknown, scope: ProcurementScope, identifier: string): Promise<SourcingDetail> {
  if (!object(value) || !object(value.source) || !Array.isArray(value.quotations) || value.quotations.length > 32) invalid();
  const head = parseSourcingHead(value.head, scope), source = value.source;
  if (head.id !== identifier || source.schema_version !== head.schema_version || source.creator_actor_id !== head.creator_actor_id || source.ceiling_minor !== head.ceiling_minor ||
    !Number.isSafeInteger(source.currency_precision) || Number(source.currency_precision) < 0 || Number(source.currency_precision) > 6 || !object(source.scope) ||
    !["workspace_id", "organization_id", "legal_entity_id"].every(key => source.scope && (source.scope as Record<string, unknown>)[key] === head[key as keyof SourcingHead]) ||
    !object(source.request) || source.request.budget_id !== head.budget_id || !text(source.request.reason)) invalid();
  const demand = order(source.request.order, scope), n = demand.lines.length;
  if (demand.number !== head.number || demand.lines.reduce((sum, line) => sum + sourcingLineMinor(line.quantity, line.unit_price_minor), 0n).toString() !== head.ceiling_minor ||
    !Array.isArray(source.request.requirements) || source.request.requirements.length !== n || !Array.isArray(source.demand_masters) || source.demand_masters.length !== n ||
    !Array.isArray(source.manufacturing_requirements) || source.manufacturing_requirements.length !== n) invalid();
  await verifyCanonical(source, value.canonical_source_json, head.source_digest);
  const suppliers = new Set<string>(), ids = new Set<string>(), versions = new Set<number>();
  const quotations: SourcingQuote[] = [];
  for (const record of value.quotations) {
    if (!object(record) || !text(record.id) || !hash(record.quote_digest) || !version(record.created_version) || record.created_version < 3 || record.created_version >= head.row_version + (head.status === "OpenRFQ" ? 1 : 0) ||
      !object(record.payload)) invalid();
    const payload = record.payload;
    if (payload.schema_version !== "supplier-quotation-v1" || payload.requisition_id !== head.id || payload.source_digest !== head.source_digest || !text(payload.supplier_id) ||
      !text(payload.registrar_actor_id) || payload.registrar_actor_id === head.selection_reviewer_actor_id || !minor(payload.total_minor) || !object(payload.quotation) ||
      !text(payload.quotation.valid_until) || payload.quotation.valid_until < demand.posting_date || !text(payload.quotation.reason) || !Array.isArray(payload.quotation.unit_prices_minor)) invalid();
    const quoted = order(payload.order, scope);
    if (quoted.number !== "BPC1-" + demand.number || quoted.supplier_code !== payload.quotation.supplier_code || quoted.lines.length !== n ||
      payload.quotation.unit_prices_minor.length !== n || suppliers.has(quoted.supplier_code) || ids.has(record.id) || versions.has(record.created_version)) invalid();
    for (const key of ["currency_code", "posting_date", "period_id", "journal_code", "ap_account_code", "cash_account_code", "workspace", "organization_code", "entity_code"] as const) if (quoted[key] !== demand[key]) invalid();
    for (const [index, line] of quoted.lines.entries()) {
      if (line.unit_price_minor !== payload.quotation.unit_prices_minor[index] ||
        !["item_code", "quantity", "location_code", "policy_code"].every(key => line[key as keyof SourcingLine] === demand.lines[index][key as keyof SourcingLine])) invalid();
    }
    if (quoted.lines.reduce((sum, line) => sum + sourcingLineMinor(line.quantity, line.unit_price_minor), 0n).toString() !== payload.total_minor) invalid();
    await verifyCanonical(payload, record.canonical_quote_json, record.quote_digest);
    suppliers.add(quoted.supplier_code); ids.add(record.id); versions.add(record.created_version); quotations.push(record as unknown as SourcingQuote);
  }
  const sorted = [...quotations].sort((a, b) => BigInt(a.payload.total_minor) < BigInt(b.payload.total_minor) ? -1 : BigInt(a.payload.total_minor) > BigInt(b.payload.total_minor) ? 1 : a.payload.order.supplier_code < b.payload.order.supplier_code ? -1 : 1);
  if (head.selected_quote_id !== null && (!sorted.length || sorted[0].id !== head.selected_quote_id || BigInt(sorted[0].payload.total_minor) > BigInt(head.ceiling_minor) ||
    sorted[0].payload.registrar_actor_id === head.award_actor_id)) invalid();
  return value as unknown as SourcingDetail;
}
export function parseSourcingAcknowledgement(value: unknown, scope: ProcurementScope, command: PreparedScopedCommand): SourcingHead {
  const head = parseSourcingHead(value, scope), match = /^\/api\/v1\/procurement-sourcing\/requisitions\/([^/]+)\/(quotes|open-rfq|review-selection|award|cancel)$/.exec(command.path);
  if (command.path === sourcingRoot ? head.row_version !== 1 || head.number !== String(command.body.number).trim().toUpperCase() || head.budget_id !== command.body.budget_id :
    !match || head.id !== decodeURIComponent(match[1]) || head.row_version !== Number(command.body.expected_version) + 1 ||
      head.status !== ({ quotes: "OpenRFQ", "open-rfq": "OpenRFQ", "review-selection": "SelectionReviewed", award: "Awarded", cancel: "Cancelled" }[match[2]])) invalid();
  return head;
}
export function verifySourcingCommandDetail(detail: SourcingDetail, acknowledgment: SourcingHead, command: PreparedScopedCommand): void {
  if (detail.head.id !== acknowledgment.id || detail.head.row_version < acknowledgment.row_version || detail.head.source_digest !== acknowledgment.source_digest) invalid();
  const body = command.body;
  if (command.path === sourcingRoot) {
    const source = detail.source.request, original = source.order;
    if (source.budget_id !== body.budget_id || source.reason !== String(body.reason).trim() || !Array.isArray(body.lines) || body.lines.length !== original.lines.length) invalid();
    for (const key of ["number", "supplier_code", "currency_code", "organization_code", "entity_code", "journal_code", "ap_account_code", "cash_account_code"] as const) if (original[key] !== String(body[key]).trim().toUpperCase()) invalid();
    for (const key of ["workspace", "posting_date", "period_id"] as const) if (original[key] !== String(body[key]).trim()) invalid();
    for (const [index, line] of original.lines.entries()) {
      const sent = body.lines[index]; if (!object(sent)) invalid();
      if (line.item_code !== String(sent.item_code).trim().toUpperCase() || line.policy_code !== String(sent.policy_code).trim().toUpperCase() || line.location_code !== String(sent.location_code).trim() || line.unit_price_minor !== String(sent.unit_price_minor).trim() ||
        !sameProcurementQuantity(line.quantity, String(sent.quantity).trim())) invalid();
    }
    const expected = Array.isArray(body.requirements) && body.requirements.length ? body.requirements : original.lines.map(() => null);
    if (canonical(source.requirements) !== canonical(expected)) invalid();
  } else if (command.path.endsWith("/quotes")) {
    const quote = detail.quotations.find(q => q.created_version === acknowledgment.row_version)?.payload.quotation;
    if (!quote || quote.supplier_code !== body.supplier_code || quote.valid_until !== body.valid_until || quote.reason !== body.reason || canonical(quote.unit_prices_minor, "unit_prices_minor") !== canonical(body.unit_prices_minor, "unit_prices_minor")) invalid();
  }
}
export async function sourcingGet(session: BrowserAdminSession, scope: ProcurementScope, id: string, signal?: AbortSignal): Promise<SourcingDetail> {
  return parseSourcingDetail(await procurementFetch(session, scope.workspace_id, scope, sourcingRoot + "/" + encodeURIComponent(id), { signal }), scope, id);
}
export async function sourcingList(session: BrowserAdminSession, scope: ProcurementScope, signal?: AbortSignal): Promise<SourcingHead[]> {
  const value = await procurementFetch(session, scope.workspace_id, scope, sourcingRoot, { signal });
  if (!object(value) || !Array.isArray(value.records) || value.records.length > 25) invalid();
  const heads = value.records.map(row => parseSourcingHead(row, scope));
  if (new Set(heads.map(head => head.id)).size !== heads.length) invalid();
  return heads;
}
export async function sourcingCommand(session: BrowserAdminSession, scope: ProcurementScope, command: PreparedScopedCommand): Promise<SourcingHead> {
  return parseSourcingAcknowledgement(await procurementFetch(session, scope.workspace_id, scope, command.path, { body: command.body }), scope, command);
}

