import { AdminApiError } from "./data";
import { formatExactDecimal } from "./locale-format";
import type { BrowserAdminSession, Locale } from "./types";
import type { BudgetIdentity, BudgetScope } from "./budget-control-data";
export { loadBudgetIdentity as loadSalesIdentity } from "./budget-control-data";
export type SalesIdentity = BudgetIdentity;
export type SalesScope = BudgetScope;
export const salesStages = ["Draft", "Submitted", "Approved", "Ordered", "Fulfilled", "InvoicePrepared", "InvoiceReviewed", "Invoiced", "CollectionPrepared", "CollectionReviewed", "Paid", "Cancelled"] as const;
export type SalesStage = typeof salesStages[number];
export interface SalesSummary { id: string; number: string; status: SalesStage; currency_code: string; total_minor: string; row_version: number; created_by: string }
export interface SalesLine { description: string; quantity: string; unit_price_minor: string; discount_basis_points: number }
export interface SalesDocument extends SalesSummary, SalesScope {
  quotation_digest: string; quotation: { customer_code: string; business_date: string; valid_until: string; monetary_policy: { precision: number }; lines: { description: string; quantity: string; unit_price_minor: string; line_total_minor: string; discount_basis_points: number }[] };
  approved_by: string | null; invoice_id: string | null; receipt_id: string | null;
  invoice?: { id: string; status: string; total_minor: string; outstanding_minor: string; allocated_minor: string };
  invoice_plan?: { id: string; entry_id: string; plan_digest: string; status: string; posting_effect_id?: string };
  collection_plan?: { id: string; entry_id: string; plan_digest: string; status: string; posting_effect_id?: string };
  events: { version: number; operation: string; actor_id: string; reason: string; audit_event_id: string }[];
}
export interface SalesPage { documents: SalesSummary[]; next_cursor: string | null }
export interface SalesCommand { readonly path: string; readonly scope: Readonly<SalesScope>; readonly body: Readonly<Record<string, unknown>> }

function object(value: unknown): Record<string, unknown> { if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("sales_contract_invalid"); return value as Record<string, unknown>; }
function text(value: unknown): string { if (typeof value !== "string" || !value || value.length > 500 || /[\u0000-\u001f\u007f]/.test(value)) throw new Error("sales_contract_invalid"); return value; }
function minor(value: unknown): string { if (typeof value !== "string" || !/^(0|[1-9]\d{0,18})$/.test(value) || BigInt(value) > 9223372036854775807n) throw new Error("sales_contract_invalid"); return value; }
function version(value: unknown): number { if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 1) throw new Error("sales_contract_invalid"); return value; }
function summary(value: unknown): SalesSummary {
  const row = object(value);
  if (!salesStages.includes(row.status as SalesStage) || !/^[A-Z]{3}$/.test(String(row.currency_code))) throw new Error("sales_contract_invalid");
  return { id: text(row.id), number: text(row.number), status: row.status as SalesStage, currency_code: text(row.currency_code), total_minor: minor(row.total_minor), row_version: version(row.row_version), created_by: text(row.created_by) };
}
export function parseSalesDocument(value: unknown, scope: SalesScope, id?: string): SalesDocument {
  const row = object(value), base = summary(row), quote = object(row.quotation), policy = object(quote.monetary_policy);
  if ((id && base.id !== id) || Object.entries(scope).some(([key, value]) => row[key] !== value) || !/^[a-f0-9]{64}$/.test(String(row.quotation_digest)) || !Array.isArray(quote.lines) || !Array.isArray(row.events) || quote.lines.length > 100 || row.events.length > 20 || !Number.isInteger(policy.precision) || Number(policy.precision) < 0 || Number(policy.precision) > 8) throw new Error("sales_contract_invalid");
  const lines = quote.lines.map((value) => { const line = object(value); const bps = line.discount_basis_points; if (!Number.isInteger(bps) || Number(bps) < 0 || Number(bps) >= 10000) throw new Error("sales_contract_invalid"); return { description: text(line.description), quantity: text(line.quantity), unit_price_minor: minor(line.unit_price_minor), line_total_minor: minor(line.line_total_minor), discount_basis_points: Number(bps) }; });
  if (lines.reduce((sum, line) => sum + BigInt(line.line_total_minor), 0n) !== BigInt(base.total_minor)) throw new Error("sales_contract_invalid");
  const events = row.events.map((value) => { const event = object(value); return { version: version(event.version), operation: text(event.operation), actor_id: text(event.actor_id), reason: text(event.reason), audit_event_id: text(event.audit_event_id) }; });
  if (events.some((event, i) => event.version !== i + 1) || events.length !== base.row_version) throw new Error("sales_contract_invalid");
  const invoice = row.invoice === undefined ? undefined : object(row.invoice);
  if (invoice && (BigInt(minor(invoice.total_minor)) !== BigInt(base.total_minor) || BigInt(minor(invoice.outstanding_minor)) + BigInt(minor(invoice.allocated_minor)) !== BigInt(base.total_minor))) throw new Error("sales_contract_invalid");
  if (base.status === "Paid" && (!invoice || invoice.status !== "Paid" || invoice.outstanding_minor !== "0" || !row.receipt_id)) throw new Error("sales_contract_invalid");
  return { ...row, ...base, ...scope, quotation: { ...quote, lines, monetary_policy: { precision: Number(policy.precision) } }, events } as unknown as SalesDocument;
}
export function salesMoney(value: string, currency: string, precision: number, locale: Locale): string {
  const digits = minor(value).padStart(precision + 1, "0"), amount = precision ? `${digits.slice(0, -precision)}.${digits.slice(-precision)}` : digits;
  return `${formatExactDecimal(amount, locale)} ${currency}`;
}
export async function salesRequest(session: BrowserAdminSession, scope: SalesScope, path: string, body?: Readonly<Record<string, unknown>>, signal?: AbortSignal): Promise<unknown> {
  const response = await fetch(path, { method: body ? "POST" : "GET", credentials: "same-origin", cache: "no-store", signal,
    headers: { Accept: "application/json", "X-ReconForge-Tenant": session.tenantId, "X-ReconForge-Workspace": scope.workspace_id,
      "X-ReconForge-Organization": scope.organization_id, "X-ReconForge-Legal-Entity": scope.legal_entity_id,
      ...(body ? { "Content-Type": "application/json", "X-ReconForge-CSRF": session.csrfToken } : {}) }, ...(body ? { body: JSON.stringify(body) } : {}) });
  if (!response.ok) { let code = `http_${response.status}`; try { code = text(object(object(await response.json()).error).code); } catch { /* Keep authoritative status. */ } throw new AdminApiError(response.status, code); }
  return await response.json();
}
export async function loadSalesPage(session: BrowserAdminSession, scope: SalesScope, after = "", signal?: AbortSignal): Promise<SalesPage> {
  const row = object(await salesRequest(session, scope, `/api/v1/sales-revenue/documents?after=${encodeURIComponent(after)}`, undefined, signal));
  if (!Array.isArray(row.documents) || row.documents.length > 25 || !(row.next_cursor === null || typeof row.next_cursor === "string")) throw new Error("sales_contract_invalid");
  return { documents: row.documents.map(summary), next_cursor: row.next_cursor as string | null };
}
export async function loadSalesDocument(session: BrowserAdminSession, scope: SalesScope, id: string, signal?: AbortSignal): Promise<SalesDocument> {
  return parseSalesDocument(object(await salesRequest(session, scope, `/api/v1/sales-revenue/documents/${encodeURIComponent(id)}`, undefined, signal)).document, scope, id);
}
export function prepareSalesCommand(scope: SalesScope, path: string, body: Record<string, unknown>): SalesCommand {
  if (!path.startsWith("/api/v1/sales-revenue/") || Object.hasOwn(body, "command_id") || Object.values(scope).some((value) => !value || value !== value.trim())) throw new Error("sales_command_invalid");
  const frozen = JSON.parse(JSON.stringify({ ...body, command_id: crypto.randomUUID() })) as Record<string, unknown>;
  function freeze(value: unknown) { if (value && typeof value === "object") { Object.values(value).forEach(freeze); Object.freeze(value); } }
  freeze(frozen);
  return Object.freeze({ path, scope: Object.freeze({ ...scope }), body: frozen });
}
export async function executeSalesCommand(session: BrowserAdminSession, command: SalesCommand): Promise<SalesDocument> {
  const result = parseSalesDocument(object(await salesRequest(session, command.scope, command.path, command.body)).document, command.scope);
  const id = command.path.split("/")[5];
  if (command.path.includes("/documents/") && decodeURIComponent(id) !== result.id) throw new Error("sales_contract_invalid");
  if (command.body.expected_version !== undefined && result.row_version !== Number(command.body.expected_version) + 1) throw new Error("sales_contract_invalid");
  return result;
}
