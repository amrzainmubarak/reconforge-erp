import { prepareScopedCommand, type PreparedScopedCommand } from "./scoped-command";
import { salesRequest, type SalesScope, type SalesOptions } from "./sales-revenue-data";
import type { BrowserAdminSession } from "./types";

export const stockStages = ["Draft", "Submitted", "Approved", "Reserved", "IssuePrepared", "IssueReviewed", "Delivered", "InvoicePrepared", "InvoiceReviewed", "Invoiced", "CollectionPrepared", "CollectionReviewed", "Paid", "Cancelled"] as const;
export type StockStage = typeof stockStages[number];
export interface StockOrder extends SalesScope {
  id: string; number: string; status: StockStage; row_version: number; source_digest: string;
  currency_code: string; total_minor: string; cogs_minor: string | null; quantity: string; quantity_scaled: string; quantity_precision: number;
  unit_price_minor: string; net_unit_price_minor: string; discount_basis_points: number; description: string;
  customer_code: string; customer_reference: string; item_code: string; warehouse_code: string; location_code: string; order_date: string;
  created_by: string; approved_by: string | null; issue_preparer_id: string | null; issue_reviewer_id: string | null; monetary_policy: { precision: number };
  movement_id: string | null; valuation_id: string | null; cogs_entry_id: string | null; cogs_effect_id: string | null;
  invoice_id: string | null; invoice_plan_id: string | null; collection_plan_id: string | null; receipt_id: string | null;
  events: { version: number; actor_id: string; operation: string; reason: string; status: StockStage; audit_event_id: string }[];
}
export interface StockOptions extends SalesOptions {
  items: { item_code: string; name: string; uom_code: string; decimal_places: number }[];
  warehouses: { warehouse_code: string; name: string }[];
  locations: { warehouse_code: string; location_code: string; name: string }[];
  policies: { policy_code: string; name: string; journal_code: string }[];
}
export interface StockCommand extends PreparedScopedCommand { readonly scope: Readonly<SalesScope> }
function invalid(): never { throw new Error("stock_sales_contract_invalid"); }
function object(value: unknown): Record<string, unknown> { if (!value || typeof value !== "object" || Array.isArray(value)) invalid(); return value as Record<string, unknown>; }
function text(value: unknown): string { if (typeof value !== "string" || !value || value.length > 500 || /[\u0000-\u001f\u007f]/.test(value)) invalid(); return value; }
function minor(value: unknown): string { if (typeof value !== "string" || !/^(0|[1-9]\d{0,18})$/.test(value) || BigInt(value) > 9000000000000000000n) invalid(); return value; }
function integer(value: unknown, min = 0, max = Number.MAX_SAFE_INTEGER): number { if (typeof value !== "number" || !Number.isSafeInteger(value) || value < min || value > max) invalid(); return value; }
export function parseStockOrder(value: unknown, scope: SalesScope, identifier?: string): StockOrder {
  const row = object(value), policy = object(row.monetary_policy);
  if (!stockStages.includes(row.status as StockStage) || !/^[A-Z]{3}$/.test(String(row.currency_code)) || !/^[a-f0-9]{64}$/.test(String(row.source_digest)) || !Array.isArray(row.events) || row.events.length > 13) invalid();
  for (const key of ["id", "number", "customer_code", "customer_reference", "item_code", "warehouse_code", "location_code", "quantity", "description", "created_by", "order_date"]) text(row[key]);
  if (identifier && row.id !== identifier) invalid();
  if (Object.entries(scope).some(([key, expected]) => row[key] !== expected)) invalid();
  for (const key of ["total_minor", "unit_price_minor", "net_unit_price_minor", "quantity_scaled"]) minor(row[key]);
  integer(row.row_version, 1, 13); integer(row.quantity_precision, 0, 6); integer(row.discount_basis_points, 0, 9999); integer(policy.precision, 0, 8);
  if (row.cogs_minor !== null) minor(row.cogs_minor);
  for (const key of ["approved_by", "issue_preparer_id", "issue_reviewer_id", "movement_id", "valuation_id", "cogs_entry_id", "cogs_effect_id", "invoice_id", "invoice_plan_id", "collection_plan_id", "receipt_id"]) if (row[key] !== null) text(row[key]);
  row.events.forEach((value, index) => { const event = object(value); if (integer(event.version, 1, 13) !== index + 1 || !stockStages.includes(event.status as StockStage)) invalid(); for (const key of ["actor_id", "operation", "reason", "audit_event_id"]) text(event[key]); });
  if (row.events.length !== row.row_version || object(row.events.at(-1)).status !== row.status) invalid();
  const stage = stockStages.indexOf(row.status as StockStage);
  if (stage >= 6 && stage < 13 && ["movement_id", "valuation_id", "cogs_entry_id", "cogs_effect_id"].some((key) => !row[key])) invalid();
  if (row.status === "Paid" && (!row.invoice_id || !row.receipt_id || !row.collection_plan_id)) invalid();
  return row as unknown as StockOrder;
}
export async function loadStockOrders(session: BrowserAdminSession, scope: SalesScope, signal?: AbortSignal): Promise<StockOrder[]> {
  const row = object(await salesRequest(session, scope, "/api/v1/stock-sales/orders", undefined, signal));
  if (!Array.isArray(row.orders) || row.orders.length > 100) invalid();
  return row.orders.map((value) => parseStockOrder(value, scope));
}
export async function loadStockOrder(session: BrowserAdminSession, scope: SalesScope, id: string, signal?: AbortSignal): Promise<StockOrder> {
  return parseStockOrder(await salesRequest(session, scope, `/api/v1/stock-sales/orders/${encodeURIComponent(id)}`, undefined, signal), scope, id);
}
export async function loadStockOptions(session: BrowserAdminSession, scope: SalesScope, signal?: AbortSignal): Promise<StockOptions> {
  const row = object(await salesRequest(session, scope, "/api/v1/stock-sales/options", undefined, signal));
  for (const [key, bound, fields] of [["customers",100,["customer_code","name","currency_code"]], ["periods",50,["id","name","start_date","end_date"]], ["journals",100,["journal_code","name","currency_code"]], ["accounts",200,["account_code","name","account_type","chart_id"]], ["items",100,["item_code","name","uom_code"]], ["warehouses",100,["warehouse_code","name"]], ["locations",200,["warehouse_code","location_code","name"]], ["policies",100,["policy_code","name","journal_code"]]] as const) {
    const values = row[key]; if (!Array.isArray(values) || values.length > bound) invalid();
    values.forEach((value) => { const entry = object(value); fields.forEach((field) => text(entry[field])); if (key === "items") integer(entry.decimal_places, 0, 6); });
  }
  return row as unknown as StockOptions;
}
export function prepareStockCommand(scope: SalesScope, path: string, body: Record<string, string | number>): StockCommand {
  if (!/^\/api\/v1\/stock-sales\/orders(?:\/[^/?#]+\/(?:submit|approve|reserve|deliver|cancel|(?:issue|invoice|collection)\/(?:prepare|review|post)))?$/.test(path) || Object.values(scope).some((value) => !value || value !== value.trim())) invalid();
  const command = prepareScopedCommand(path, body);
  return Object.freeze({ ...command, scope: Object.freeze({ ...scope }) });
}
export async function executeStockCommand(session: BrowserAdminSession, command: StockCommand): Promise<StockOrder> {
  const id = command.path.split("/")[5];
  const result = parseStockOrder(await salesRequest(session, command.scope, command.path, command.body), command.scope, id ? decodeURIComponent(id) : undefined);
  if (command.body.expected_version !== undefined && result.row_version !== Number(command.body.expected_version) + 1) invalid();
  return result;
}
