import { salesRequest, type SalesScope } from "./sales-revenue-data";
import { stockStages, type StockStage } from "./stock-sales-data";
import { prepareScopedCommand, type ScopedJsonValue } from "./scoped-command";
import type { BrowserAdminSession } from "./types";

export interface CommerceAck extends SalesScope {
  id: string; number: string; row_version: number; status: "Draft" | "Submitted" | "Approved";
  currency_code: string; total_minor: string; line_count: number; created_by: string;
  approved_by: string | null; source_digest: string; progress_digest?: string;
}
export interface CommerceTranche {
  id: string; stock_order_id: string; quantity_scaled: string; total_minor: string; status: StockStage; row_version: number;
  created_by: string; issue_preparer_id: string | null; issue_reviewer_id: string | null;
  invoice_preparer_id: string | null; invoice_reviewer_id: string | null;
  collection_preparer_id: string | null; collection_reviewer_id: string | null;
  invoice_id: string | null; receipt_id: string | null; movement_id: string | null; cogs_effect_id: string | null;
}
export interface CommerceLine {
  line_number: number; quantity_scaled: string; quantity_precision: number; total_minor: string;
  committed_quantity_scaled: string; delivered_quantity_scaled: string; invoiced_minor: string; collected_minor: string;
  source: { item_code: string; warehouse_code: string; location_code: string; quantity: string; description: string;
    unit_price_minor: string; net_unit_price_minor: string; discount_basis_points: number };
  tranches: CommerceTranche[];
}
export interface CommerceOrder extends CommerceAck { lines: CommerceLine[]; customer_code: string; customer_reference: string; order_date: string }
export interface CommerceCommand { readonly path: string; readonly scope: Readonly<SalesScope>; readonly body: Readonly<Record<string, ScopedJsonValue>> }
function invalid(): never { throw new Error("commerce_contract_invalid"); }
function record(value: unknown): Record<string, unknown> { if (!value || typeof value !== "object" || Array.isArray(value)) invalid(); return value as Record<string, unknown>; }
function exact(value: unknown): bigint { if (typeof value !== "string" || !/^(0|[1-9]\d{0,18})$/.test(value) || BigInt(value) > 9000000000000000000n) invalid(); return BigInt(value); }
function text(value: unknown): string { if (typeof value !== "string" || !value || value.length > 500 || /[\u0000-\u001f\u007f]/.test(value)) invalid(); return value; }
function integer(value: unknown, minimum: number, maximum: number): number { if (!Number.isSafeInteger(value) || (value as number) < minimum || (value as number) > maximum) invalid(); return value as number; }
export function parseCommerceAck(value: unknown, scope: SalesScope): CommerceAck {
  const row = record(value);
  for (const key of ["id", "number", "created_by"]) text(row[key]);
  if (Object.entries(scope).some(([key, expected]) => row[key] !== expected) || !["Draft", "Submitted", "Approved"].includes(String(row.status)) || !/^[A-Z]{3}$/.test(String(row.currency_code)) || !/^[a-f0-9]{64}$/.test(String(row.source_digest))) invalid();
  integer(row.row_version, 1, Number.MAX_SAFE_INTEGER); integer(row.line_count, 1, 1000); exact(row.total_minor);
  if (row.approved_by !== null) text(row.approved_by);
  if (row.progress_digest !== undefined && !/^[a-f0-9]{64}$/.test(String(row.progress_digest))) invalid();
  return row as unknown as CommerceAck;
}
export function parseCommerceOrder(value: unknown, scope: SalesScope): CommerceOrder {
  const order = parseCommerceAck(value, scope) as CommerceOrder;
  if (!Array.isArray(order.lines) || order.lines.length !== order.line_count) invalid();
  let total = 0n;
  order.lines.forEach((line, index) => {
    integer(line.line_number, index + 1, index + 1); integer(line.quantity_precision, 0, 6);
    const quantity = exact(line.quantity_scaled), value = exact(line.total_minor); total += value;
    if (!quantity || !value || !Array.isArray(line.tranches)) invalid();
    const source = record(line.source);
    ["item_code", "warehouse_code", "location_code", "quantity", "description"].forEach((key) => text(source[key]));
    integer(source.discount_basis_points, 0, 9999);
    const gross = exact(source.unit_price_minor), net = exact(source.net_unit_price_minor);
    if ((gross * BigInt(10000 - Number(source.discount_basis_points)) + 5000n) / 10000n !== net || quantity * net !== value * (10n ** BigInt(line.quantity_precision))) invalid();
    let committed = 0n, delivered = 0n, invoiced = 0n, collected = 0n;
    const seen = new Set<string>();
    line.tranches.forEach((tranche) => {
      text(tranche.id); text(tranche.stock_order_id); text(tranche.created_by); integer(tranche.row_version, 1, 13);
      if (seen.has(tranche.id) || !stockStages.includes(tranche.status)) invalid(); seen.add(tranche.id);
      const q = exact(tranche.quantity_scaled), v = exact(tranche.total_minor);
      if (!q || !v || q * net !== v * (10n ** BigInt(line.quantity_precision))) invalid();
      const stage = stockStages.indexOf(tranche.status);
      if (tranche.status !== "Cancelled") committed += q;
      if (stage >= 6 && stage < 13) delivered += q;
      if (stage >= 9 && stage < 13) invoiced += v;
      if (tranche.status === "Paid") collected += v;
      for (const key of ["issue_preparer_id", "issue_reviewer_id", "invoice_preparer_id", "invoice_reviewer_id", "collection_preparer_id", "collection_reviewer_id", "invoice_id", "receipt_id", "movement_id", "cogs_effect_id"] as const) if (tranche[key] !== null) text(tranche[key]);
    });
    if (committed > quantity || delivered > committed || collected > invoiced || invoiced > value ||
      exact(line.committed_quantity_scaled) !== committed || exact(line.delivered_quantity_scaled) !== delivered || exact(line.invoiced_minor) !== invoiced || exact(line.collected_minor) !== collected) invalid();
  });
  if (total !== exact(order.total_minor)) invalid();
  return order;
}
export function prepareCommerceCommand(scope: SalesScope, path: string, body: Record<string, ScopedJsonValue>): CommerceCommand {
  if (!/^\/api\/v1\/stock-sales\/commerce\/orders(?:\/[^/?#]+\/(?:submit|approve|open-tranche|approve-tranche|prepare-issue|review-issue|deliver|prepare-invoice|review-invoice|invoice|prepare-collection|review-collection|collect|cancel))?$/.test(path) || Object.hasOwn(body, "command_id")) invalid();
  return Object.freeze({ ...prepareScopedCommand(path, body), scope: Object.freeze({ ...scope }) });
}
export async function executeCommerceCommand(session: BrowserAdminSession, command: CommerceCommand): Promise<CommerceAck> {
  const result = parseCommerceAck(await salesRequest(session, command.scope, command.path, command.body), command.scope);
  if (command.body.expected_version !== undefined && result.row_version !== Number(command.body.expected_version) + 1) invalid();
  return result;
}
export async function loadCommerceOrder(session: BrowserAdminSession, scope: SalesScope, id: string, signal?: AbortSignal): Promise<CommerceOrder> {
  const result = parseCommerceOrder(await salesRequest(session, scope, `/api/v1/stock-sales/commerce/orders/${encodeURIComponent(id)}`, undefined, signal), scope);
  if (result.id !== id) invalid(); return result;
}
export async function loadCommercePage(session: BrowserAdminSession, scope: SalesScope, after = "", signal?: AbortSignal): Promise<{ orders: Pick<CommerceAck, "id" | "number" | "status" | "row_version" | "total_minor" | "currency_code" | "line_count">[]; next_cursor: string | null }> {
  const row = record(await salesRequest(session, scope, `/api/v1/stock-sales/commerce/orders?after=${encodeURIComponent(after)}`, undefined, signal));
  if (!Array.isArray(row.orders) || row.orders.length > 50 || (row.next_cursor !== null && typeof row.next_cursor !== "string")) invalid();
  row.orders.forEach((value) => { const order = record(value); text(order.id); text(order.number); exact(order.total_minor); integer(order.row_version, 1, Number.MAX_SAFE_INTEGER); });
  return row as unknown as { orders: CommerceAck[]; next_cursor: string | null };
}
export async function searchCommerceCatalog(session: BrowserAdminSession, scope: SalesScope, prefix: string, after = "", signal?: AbortSignal): Promise<{ items: { item_code: string; name: string; uom_code: string; decimal_places: number }[]; next_cursor: string | null }> {
  const row = record(await salesRequest(session, scope, `/api/v1/stock-sales/commerce/catalog?prefix=${encodeURIComponent(prefix)}&after=${encodeURIComponent(after)}`, undefined, signal));
  if (!Array.isArray(row.items) || row.items.length > 50 || (row.next_cursor !== null && typeof row.next_cursor !== "string")) invalid();
  row.items.forEach((value) => { const item = record(value); text(item.item_code); text(item.name); text(item.uom_code); integer(item.decimal_places, 0, 6); });
  return row as unknown as { items: { item_code: string; name: string; uom_code: string; decimal_places: number }[]; next_cursor: string | null };
}
