import { procurementFetch, type ProcurementScope } from "./procurement-data";
import type { PreparedScopedCommand } from "./scoped-command";
import type { BrowserAdminSession } from "./types";

export const partialRoot = "/api/v1/procurement-partial";
export interface PartialOrder { id: string; number: string; workspace_id: string; organization_id: string; legal_entity_id: string; purchase_order_id: string; row_version: number; stage: "Draft" | "Submitted" | "Approved"; total_minor: string; request: Record<string, string>; multiline?: boolean; line_count?: number }
export interface PartialReceipt { id: string; number: string; sequence: number; quantity_text: string; total_minor: string; posting_date: string; period_id: string; receipt_plan_id: string; goods_receipt_id: string | null; preparer_actor_id: string; reviewer_actor_id: string | null; posted_actor_id: string | null; stage: "Prepared" | "Reviewed" | "Posted"; created_version: number; reviewed_version: number | null; posted_version: number | null; order_line_id?: string }
export interface InstallmentPlan { id: string; workspace_id: string; organization_id: string; legal_entity_id: string; source_kind: "APPayment"; source_id: string; entry_id: string; period_id: string; posting_date: string; currency_code: string; currency_precision: number; status: "Prepared" | "Reviewed" | "Posted"; phase: number; plan_digest: string; validation_digest: string; preparer_actor_id: string; reviewer_actor_id: string | null; posting_effect_id: string | null; payment_link_id: string | null; amount_minor: string; allocated_before_minor: string; invoice_version: number }
export interface PartialInvoice { id: string; number: string; sequence: number; quantity_text: string | null; total_minor: string; posting_date: string; period_id: string; native_invoice_id: string; accrual_plan_id: string | null; accrual_effect_id: string | null; accrual_preparer_actor_id: string | null; accrual_reviewer_actor_id: string | null; accrual_posted_actor_id: string | null; stage: "Matched" | "Approved" | "AccrualPrepared" | "AccrualReviewed" | "Accrued"; created_version: number; approved_version: number | null; prepared_version: number | null; reviewed_version: number | null; posted_version: number | null; native_status: "Matched" | "Approved" | "Paid"; native_version: number; paid_minor: string; outstanding_minor: string; payment_links: { id: string; finance_effect_id: string; amount_minor: string; created_at: string }[]; installment_plans: InstallmentPlan[]; lines?: { id: string; line_id: string; sequence: number; quantity_text: string; total_minor: string; item_code: string; location_code: string; uom_id: string }[]; payment_history_count?: number }
export interface EnterprisePurchaseLine { id: string; sequence: number; item_code: string; uom_id: string; uom_code: string; quantity_precision: number; location_code: string; policy_code: string; quantity_text: string; unit_price_minor: string; total_minor: string; reserved_receipt_quantity: string; received_quantity: string; invoiced_quantity: string }
export interface PartialPages { receipt_after: number; invoice_after: number; page_size: number; receipt_count: number; invoice_count: number; next_receipt_after: number | null; next_invoice_after: number | null }
export interface PartialDetail { order: PartialOrder; receipts: PartialReceipt[]; invoices: PartialInvoice[]; totals: { ordered_quantity: string; reserved_receipt_quantity: string; received_quantity: string; invoiced_quantity: string; received_minor: string; accrued_minor: string; paid_minor: string; outstanding_minor: string }; lines?: EnterprisePurchaseLine[]; pages?: PartialPages }
export type PartialOrderSummary = Omit<PartialOrder, "request">;
export interface PartialOrderPage { records: PartialOrderSummary[]; next_after: string | null; page_size: number }

const object = (value: unknown): value is Record<string, unknown> => typeof value === "object" && value !== null && !Array.isArray(value);
const text = (value: unknown): value is string => typeof value === "string" && value.length > 0 && value.length <= 500;
const money = (value: unknown): value is string => typeof value === "string" && /^(?:0|[1-9][0-9]{0,18})$/.test(value) && BigInt(value) <= 9000000000000000000n;
const version = (value: unknown): value is number => Number.isSafeInteger(value) && Number(value) > 0;
function invalid(): never { throw new Error("procurement_partial_contract_invalid"); }
export function distinctPartialPoster(preparer: string | null, reviewer: string | null, poster: string | null): boolean {
  return text(preparer) && text(reviewer) && text(poster) && new Set([preparer, reviewer, poster]).size === 3;
}
export function parseInstallmentPlan(value: unknown, scope: ProcurementScope, invoiceId: string): InstallmentPlan {
  if (!object(value) || !["id", "entry_id", "period_id", "posting_date", "preparer_actor_id"].every((key) => text(value[key])) ||
    value.workspace_id !== scope.workspace_id || value.organization_id !== scope.organization_id || value.legal_entity_id !== scope.legal_entity_id ||
    value.source_kind !== "APPayment" || value.source_id !== invoiceId || value.currency_code !== scope.currency_code ||
    !Number.isInteger(value.currency_precision) || Number(value.currency_precision) < 0 || Number(value.currency_precision) > 8 ||
    !Number.isInteger(value.phase) || ![0, 1, 2].includes(Number(value.phase)) || value.status !== ["Prepared", "Reviewed", "Posted"][Number(value.phase)] ||
    typeof value.plan_digest !== "string" || !/^[0-9a-f]{64}$/.test(value.plan_digest) || typeof value.validation_digest !== "string" || !/^[0-9a-f]{64}$/.test(value.validation_digest) ||
    !money(value.amount_minor) || value.amount_minor === "0" || !money(value.allocated_before_minor) || !version(value.invoice_version) ||
    ![value.reviewer_actor_id, value.posting_effect_id, value.payment_link_id].every((item) => item === null || text(item)) ||
    value.reviewer_actor_id === value.preparer_actor_id ||
    (value.phase === 0) !== (value.reviewer_actor_id === null) || (value.phase === 2) !== (value.posting_effect_id !== null && value.payment_link_id !== null)) invalid();
  return value as unknown as InstallmentPlan;
}
export function scaledQuantity(value: unknown): bigint {
  if (typeof value !== "string" || value.length > 64 || !/^[0-9]+(?:\.[0-9]{1,6})?$/.test(value)) invalid();
  const [whole, fraction = ""] = value.split(".");
  return BigInt(whole) * 1000000n + BigInt(fraction.padEnd(6, "0"));
}

export function parsePartialDetail(value: unknown, scope: ProcurementScope): PartialDetail {
  if (!object(value) || !object(value.order) || !object(value.totals) || !Array.isArray(value.receipts) || !Array.isArray(value.invoices) || value.receipts.length > 32 || value.invoices.length > 32) invalid();
  const order = value.order;
  const multiline = order.multiline === true;
  if (!["id", "number", "purchase_order_id"].every((key) => text(order[key])) || !version(order.row_version) || !money(order.total_minor) || order.total_minor === "0" ||
    order.workspace_id !== scope.workspace_id || order.organization_id !== scope.organization_id || order.legal_entity_id !== scope.legal_entity_id ||
    !["Draft", "Submitted", "Approved"].includes(String(order.stage)) || !object(order.request) || !Object.values(order.request).every((item) => typeof item === "string") ||
    order.request.organization_code !== scope.organization_code || order.request.entity_code !== scope.entity_code || order.request.currency_code !== scope.currency_code || !money(order.request.unit_price_minor)) invalid();
  const request = order.request as Record<string, string>;
  let lines: EnterprisePurchaseLine[] | undefined;
  let pages: PartialPages | undefined;
  if (multiline) {
    if (!Array.isArray(value.lines) || !Number.isInteger(order.line_count) || value.lines.length !== order.line_count || value.lines.length < 1 || value.lines.length > 128 || !object(value.pages)) invalid();
    lines = value.lines.map((line, index) => {
      if (!object(line) || !["id", "item_code", "uom_id", "uom_code", "location_code", "policy_code"].every((key) => text(line[key])) || line.sequence !== index + 1 ||
        !Number.isInteger(line.quantity_precision) || Number(line.quantity_precision) < 0 || Number(line.quantity_precision) > 6 || !money(line.unit_price_minor) || line.unit_price_minor === "0" || !money(line.total_minor) || line.total_minor === "0" ||
        scaledQuantity(line.quantity_text) <= 0n || scaledQuantity(line.quantity_text) * BigInt(line.unit_price_minor) !== BigInt(line.total_minor) * 1000000n ||
        scaledQuantity(line.quantity_text) % (10n ** BigInt(6 - Number(line.quantity_precision))) !== 0n ||
        scaledQuantity(line.reserved_receipt_quantity) > scaledQuantity(line.quantity_text) || scaledQuantity(line.received_quantity) > scaledQuantity(line.reserved_receipt_quantity) ||
        scaledQuantity(line.invoiced_quantity) > scaledQuantity(line.received_quantity)) invalid();
      return line as unknown as EnterprisePurchaseLine;
    });
    if (new Set(lines.map((line) => line.id)).size !== lines.length || lines.reduce((total, line) => total + BigInt(line.total_minor), 0n) !== BigInt(String(order.total_minor))) invalid();
    const raw = value.pages;
    const pageSize = Math.min(25, Math.max(1, Math.floor(512 / lines.length)));
    if (!["receipt_after", "invoice_after", "receipt_count", "invoice_count"].every((key) => Number.isInteger(raw[key]) && Number(raw[key]) >= 0 && Number(raw[key]) <= 1024) || raw.page_size !== pageSize ||
      ![raw.next_receipt_after, raw.next_invoice_after].every((cursor) => cursor === null || Number.isInteger(cursor) && Number(cursor) > 0 && Number(cursor) <= 1024) || value.receipts.length > 25 || value.invoices.length > 25) invalid();
    pages = raw as unknown as PartialPages;
    for (const [kind, documents] of [["receipt", value.receipts], ["invoice", value.invoices]] as const) {
      const after = Number(raw[kind + "_after"]), count = Number(raw[kind + "_count"]);
      const next = raw["next_" + kind + "_after"];
      if (after > count || documents.length !== Math.min(pageSize, count - after) ||
        next !== (after + documents.length < count ? after + documents.length : null)) invalid();
    }
  } else if (scaledQuantity(request.quantity) * BigInt(request.unit_price_minor) !== BigInt(String(order.total_minor)) * 1000000n) invalid();
  const receipts = value.receipts.map((part, index) => {
    if (!object(part) || !["id", "number", "receipt_plan_id", "posting_date", "period_id", "preparer_actor_id"].every((key) => text(part[key])) ||
      part.order_id !== order.id || part.sequence !== (pages?.receipt_after ?? 0) + index + 1 || !["Prepared", "Reviewed", "Posted"].includes(String(part.stage)) || !version(part.created_version) || Number(part.created_version) > Number(order.row_version) ||
      !money(part.total_minor) || part.total_minor === "0" || scaledQuantity(part.quantity_text) <= 0n ||
      ![part.reviewed_version, part.posted_version].every((item) => item === null || version(item)) || (part.goods_receipt_id !== null && !text(part.goods_receipt_id)) ||
      (part.stage === "Prepared") !== (part.reviewed_version === null) || (part.stage === "Posted") !== (part.posted_version !== null && part.goods_receipt_id !== null) ||
      ![part.reviewer_actor_id, part.posted_actor_id].every((item) => item === null || text(item)) ||
      (part.stage === "Prepared") !== (part.reviewer_actor_id === null) || (part.stage === "Posted") !== (part.posted_actor_id !== null) ||
      part.reviewer_actor_id === part.preparer_actor_id ||
      (part.stage === "Posted" && !distinctPartialPoster(String(part.preparer_actor_id), String(part.reviewer_actor_id), String(part.posted_actor_id)))) invalid();
    const line = multiline ? lines?.find((candidate) => candidate.id === part.order_line_id) : null;
    if (multiline && !line || scaledQuantity(part.quantity_text) * BigInt(line?.unit_price_minor ?? request.unit_price_minor) !== BigInt(part.total_minor) * 1000000n) invalid();
    return part as unknown as PartialReceipt;
  });
  const invoices = value.invoices.map((part, index) => {
    if (!object(part) || !["id", "number", "native_invoice_id", "posting_date", "period_id"].every((key) => text(part[key])) || part.order_id !== order.id || part.sequence !== (pages?.invoice_after ?? 0) + index + 1 ||
      !["Matched", "Approved", "AccrualPrepared", "AccrualReviewed", "Accrued"].includes(String(part.stage)) || !version(part.created_version) || !version(part.native_version) || Number(part.created_version) > Number(order.row_version) ||
      !["Matched", "Approved", "Paid"].includes(String(part.native_status)) || !money(part.total_minor) || part.total_minor === "0" || !money(part.paid_minor) || !money(part.outstanding_minor) ||
      BigInt(part.paid_minor) + BigInt(part.outstanding_minor) !== BigInt(part.total_minor) ||
      (part.native_status === "Paid") !== (part.outstanding_minor === "0") || !Array.isArray(part.payment_links) || part.payment_links.length > 200 ||
      !part.payment_links.every((link) => object(link) && text(link.id) && text(link.finance_effect_id) && money(link.amount_minor) && link.amount_minor !== "0" && text(link.created_at)) ||
      ![part.approved_version, part.prepared_version, part.reviewed_version, part.posted_version].every((item) => item === null || version(item)) ||
      ![part.accrual_plan_id, part.accrual_effect_id, part.accrual_preparer_actor_id, part.accrual_reviewer_actor_id, part.accrual_posted_actor_id].every((item) => item === null || text(item)) || !Array.isArray(part.installment_plans) || part.installment_plans.length > 200) invalid();
    const plans = part.installment_plans.map((plan) => parseInstallmentPlan(plan, scope, String(part.native_invoice_id)));
    const projectedPaid = plans.filter((plan) => plan.phase === 2).reduce((total, plan) => total + BigInt(plan.amount_minor), 0n);
    if (plans.filter((plan) => plan.phase < 2).length > 1 || (multiline ? projectedPaid > BigInt(part.paid_minor) : projectedPaid !== BigInt(part.paid_minor)) ||
      plans.some((plan) => plan.phase === 2 && !(part.payment_links as Record<string, unknown>[]).some((link) => link.id === plan.payment_link_id && link.finance_effect_id === plan.posting_effect_id && link.amount_minor === plan.amount_minor))) invalid();
    const stage = ["Matched", "Approved", "AccrualPrepared", "AccrualReviewed", "Accrued"].indexOf(String(part.stage));
    if ([part.approved_version, part.prepared_version, part.reviewed_version, part.posted_version].some((item, i) => (stage > i) !== (item !== null)) ||
      (stage >= 2) !== (part.accrual_plan_id !== null) || (stage === 4) !== (part.accrual_effect_id !== null) ||
      (stage >= 2) !== (part.accrual_preparer_actor_id !== null) || (stage >= 3) !== (part.accrual_reviewer_actor_id !== null) || (stage === 4) !== (part.accrual_posted_actor_id !== null) ||
      (stage >= 3 && part.accrual_preparer_actor_id === part.accrual_reviewer_actor_id) ||
      (stage === 4 && !distinctPartialPoster(String(part.accrual_preparer_actor_id), String(part.accrual_reviewer_actor_id), String(part.accrual_posted_actor_id))) ||
      (stage === 0) !== (part.native_status === "Matched") || (stage < 4 && part.paid_minor !== "0") ||
      (!multiline && scaledQuantity(part.quantity_text) * BigInt(request.unit_price_minor) !== BigInt(part.total_minor) * 1000000n) ||
      (multiline ? part.payment_links.reduce((total, link) => total + BigInt(String(link.amount_minor)), 0n) > BigInt(part.paid_minor) : part.payment_links.reduce((total, link) => total + BigInt(String(link.amount_minor)), 0n) !== BigInt(part.paid_minor))) invalid();
    if (multiline) {
      if (part.quantity_text !== null || !Array.isArray(part.lines) || part.lines.length < 1 || part.lines.length > 128 ||
        !Number.isInteger(part.payment_history_count) || Number(part.payment_history_count) < part.payment_links.length || Number(part.payment_history_count) > 200) invalid();
      const allocated = new Set<string>();
      let total = 0n;
      for (const [allocationIndex, allocation] of part.lines.entries()) {
        if (!object(allocation) || !text(allocation.id) || !text(allocation.line_id) || allocation.sequence !== allocationIndex + 1 || !money(allocation.total_minor) || allocation.total_minor === "0") invalid();
        const line = lines?.find((candidate) => candidate.id === allocation.line_id);
        if (!line || allocated.has(line.id) || allocation.item_code !== line.item_code || allocation.location_code !== line.location_code || allocation.uom_id !== line.uom_id ||
          scaledQuantity(allocation.quantity_text) <= 0n || scaledQuantity(allocation.quantity_text) > scaledQuantity(line.invoiced_quantity) ||
          scaledQuantity(allocation.quantity_text) * BigInt(line.unit_price_minor) !== BigInt(allocation.total_minor) * 1000000n) invalid();
        allocated.add(line.id); total += BigInt(allocation.total_minor);
      }
      if (total !== BigInt(part.total_minor)) invalid();
    }
    return part as unknown as PartialInvoice;
  });
  const totals = value.totals;
  const sumQuantity = (parts: (PartialReceipt | PartialInvoice)[]) => parts.reduce((total, part) => total + scaledQuantity(part.quantity_text), 0n);
  const sumMoney = (parts: (PartialReceipt | PartialInvoice)[], field: "total_minor" | "paid_minor" | "outstanding_minor" = "total_minor") => parts.reduce((total, part) => total + BigInt(String((part as unknown as Record<string, unknown>)[field])), 0n);
  if (multiline) {
    const receivedCost = lines!.reduce((total, line) => total + scaledQuantity(line.received_quantity) * BigInt(line.unit_price_minor), 0n);
    const invoicedCost = lines!.reduce((total, line) => total + scaledQuantity(line.invoiced_quantity) * BigInt(line.unit_price_minor), 0n);
    if (!["received_minor", "accrued_minor", "paid_minor", "outstanding_minor"].every((key) => money(totals[key])) ||
      BigInt(String(totals.received_minor)) * 1000000n !== receivedCost || BigInt(String(totals.accrued_minor)) * 1000000n > invoicedCost ||
      !["ordered_quantity", "reserved_receipt_quantity", "received_quantity", "invoiced_quantity"].every((key) => totals[key] === "0") ||
      BigInt(String(totals.paid_minor)) + BigInt(String(totals.outstanding_minor)) !== BigInt(String(totals.accrued_minor)) ||
      sumMoney(receipts.filter((part) => part.stage === "Posted")) > BigInt(String(totals.received_minor)) || sumMoney(invoices.filter((part) => part.stage === "Accrued")) > BigInt(String(totals.accrued_minor)) ||
      sumMoney(invoices, "paid_minor") > BigInt(String(totals.paid_minor)) || sumMoney(invoices.filter((part) => part.stage === "Accrued"), "outstanding_minor") > BigInt(String(totals.outstanding_minor))) invalid();
    return { order: order as unknown as PartialOrder, receipts, invoices, totals: totals as unknown as PartialDetail["totals"], lines, pages };
  }
  if (!["received_minor", "accrued_minor", "paid_minor", "outstanding_minor"].every((key) => money(totals[key])) ||
    scaledQuantity(totals.ordered_quantity) !== scaledQuantity(request.quantity) || scaledQuantity(totals.reserved_receipt_quantity) !== sumQuantity(receipts) ||
    scaledQuantity(totals.received_quantity) !== sumQuantity(receipts.filter((part) => part.stage === "Posted")) || scaledQuantity(totals.invoiced_quantity) !== sumQuantity(invoices) ||
    scaledQuantity(totals.invoiced_quantity) > scaledQuantity(totals.received_quantity) || scaledQuantity(totals.reserved_receipt_quantity) > scaledQuantity(totals.ordered_quantity) ||
    BigInt(String(totals.received_minor)) !== sumMoney(receipts.filter((part) => part.stage === "Posted")) || BigInt(String(totals.accrued_minor)) !== sumMoney(invoices.filter((part) => part.stage === "Accrued")) ||
    BigInt(String(totals.paid_minor)) !== sumMoney(invoices, "paid_minor") || BigInt(String(totals.outstanding_minor)) !== sumMoney(invoices.filter((part) => part.stage === "Accrued"), "outstanding_minor")) invalid();
  return { order: order as unknown as PartialOrder, receipts, invoices, totals: totals as unknown as PartialDetail["totals"] };
}

export async function partialList(session: BrowserAdminSession, scope: ProcurementScope, signal?: AbortSignal): Promise<PartialDetail[]> {
  const value = await procurementFetch(session, scope.workspace_id, scope, partialRoot + "/orders", { signal });
  if (!object(value) || !Array.isArray(value.records) || value.records.length > 50) invalid();
  return value.records.map((item) => parsePartialDetail(item, scope));
}
export async function partialGet(session: BrowserAdminSession, scope: ProcurementScope, id: string, signal?: AbortSignal): Promise<PartialDetail> {
  const value = parsePartialDetail(await procurementFetch(session, scope.workspace_id, scope, partialRoot + "/orders/" + encodeURIComponent(id), { signal }), scope);
  if (value.order.id !== id) invalid();
  return value;
}

export async function partialOrderPage(session: BrowserAdminSession, scope: ProcurementScope, after = "", signal?: AbortSignal): Promise<PartialOrderPage> {
  const value = await procurementFetch(session, scope.workspace_id, scope, partialRoot + "/orders/page", { query: { after }, signal });
  if (!object(value) || !Array.isArray(value.records) || value.records.length > 25 || value.page_size !== 25 || !(value.next_after === null || text(value.next_after))) invalid();
  let previous = after;
  for (const row of value.records) {
    if (!object(row) || !["id", "number", "purchase_order_id"].every((key) => text(row[key])) || !version(row.row_version) || !money(row.total_minor) || row.total_minor === "0" ||
      row.workspace_id !== scope.workspace_id || row.organization_id !== scope.organization_id || row.legal_entity_id !== scope.legal_entity_id || !["Draft", "Submitted", "Approved"].includes(String(row.stage)) ||
      !Number.isInteger(row.line_count) || Number(row.line_count) < 1 || Number(row.line_count) > 128 || typeof row.multiline !== "boolean" || String(row.id) <= previous) invalid();
    previous = String(row.id);
  }
  if (value.next_after !== null && value.next_after !== previous) invalid();
  return value as unknown as PartialOrderPage;
}

export async function partialDocumentPage(session: BrowserAdminSession, scope: ProcurementScope, id: string, receiptAfter: number, invoiceAfter: number): Promise<PartialDetail> {
  const value = parsePartialDetail(await procurementFetch(session, scope.workspace_id, scope,
    `${partialRoot}/orders/${encodeURIComponent(id)}/documents`, { query: { receipt_after: receiptAfter, invoice_after: invoiceAfter } }), scope);
  if (value.order.id !== id || value.pages?.receipt_after !== receiptAfter || value.pages?.invoice_after !== invoiceAfter) invalid();
  return value;
}

export async function partialItemCatalog(session: BrowserAdminSession, scope: ProcurementScope, search: string, after = "", signal?: AbortSignal): Promise<{ records: { code: string; name: string; uom_code: string; decimal_places: number }[]; next_after: string | null }> {
  const value = await procurementFetch(session, scope.workspace_id, scope,
    `${partialRoot}/catalog/items`, { query: { search, after }, signal });
  if (!object(value) || !Array.isArray(value.records) || value.records.length > 50 || !(value.next_after === null || text(value.next_after)) ||
    !value.records.every((item) => object(item) && text(item.code) && text(item.name) && text(item.uom_code) && Number.isInteger(item.decimal_places) && Number(item.decimal_places) >= 0 && Number(item.decimal_places) <= 6)) invalid();
  return value as unknown as { records: { code: string; name: string; uom_code: string; decimal_places: number }[]; next_after: string | null };
}

export async function partialPaymentPage(session: BrowserAdminSession, scope: ProcurementScope, orderId: string, invoice: PartialInvoice, after = ""): Promise<{ records: InstallmentPlan[]; next_after: string | null }> {
  const value = await procurementFetch(session, scope.workspace_id, scope,
    `${partialRoot}/orders/${encodeURIComponent(orderId)}/invoices/${encodeURIComponent(invoice.id)}/payments`, { query: { after } });
  if (!object(value) || value.order_id !== orderId || value.invoice_id !== invoice.id || value.native_invoice_id !== invoice.native_invoice_id || !Array.isArray(value.records) || value.records.length > 25 || !(value.next_after === null || text(value.next_after))) invalid();
  const records = value.records.map((plan) => parseInstallmentPlan(plan, scope, invoice.native_invoice_id));
  let previous = after;
  for (const plan of records) { if (plan.id <= previous) invalid(); previous = plan.id; }
  if (value.next_after !== null && value.next_after !== previous) invalid();
  return { records, next_after: value.next_after };
}

export async function installmentCommand(session: BrowserAdminSession, scope: ProcurementScope, invoice: PartialInvoice,
                                         command: PreparedScopedCommand): Promise<InstallmentPlan> {
  const value = await procurementFetch(session, scope.workspace_id, scope, command.path, { body: command.body });
  if (!object(value)) invalid();
  const plan = parseInstallmentPlan(value.plan, scope, invoice.native_invoice_id);
  if (command.path === "/api/v1/financial-installments/plans") {
    if (plan.phase !== 0 || plan.amount_minor !== command.body.amount_minor || plan.source_id !== command.body.source_id ||
      plan.period_id !== command.body.period_id || plan.posting_date !== command.body.posting_date) invalid();
  } else {
    const path = /^\/api\/v1\/financial-installments\/plans\/([^/]+)\/(review|post)$/.exec(command.path);
    if (!path || decodeURIComponent(path[1]) !== plan.id || plan.plan_digest !== command.body.expected_plan_digest || plan.phase !== (path[2] === "review" ? 1 : 2)) invalid();
  }
  return plan;
}
export async function partialCommand(session: BrowserAdminSession, scope: ProcurementScope, command: PreparedScopedCommand): Promise<PartialDetail> {
  const value = parsePartialDetail(await procurementFetch(session, scope.workspace_id, scope, command.path, { body: command.body }), scope);
  if (command.path === partialRoot + "/orders/multiline") {
    if (!value.order.multiline || value.order.row_version !== 1 || value.order.stage !== "Draft" || value.order.number !== String(command.body.number).trim().toUpperCase() || !Array.isArray(command.body.lines) || value.lines?.length !== command.body.lines.length) invalid();
    for (const [index, raw] of command.body.lines.entries()) {
      const line = value.lines[index];
      if (!object(raw) || line.item_code !== String(raw.item_code).trim().toUpperCase() || line.location_code !== String(raw.location_code).trim() || line.policy_code !== String(raw.policy_code).trim().toUpperCase() ||
        scaledQuantity(line.quantity_text) !== scaledQuantity(raw.quantity) || line.unit_price_minor !== raw.unit_price_minor) invalid();
    }
  } else if (command.path === partialRoot + "/orders") {
    if (value.order.row_version !== 1 || value.order.stage !== "Draft" || value.order.number !== String(command.body.number).trim().toUpperCase()) invalid();
    if (scaledQuantity(value.order.request.quantity) !== scaledQuantity(command.body.quantity) || value.order.request.unit_price_minor !== command.body.unit_price_minor) invalid();
  } else {
    const path = /^\/api\/v1\/procurement-partial\/orders\/([^/]+)\/commands\/([^/]+)$/.exec(command.path);
    if (!path || decodeURIComponent(path[1]) !== value.order.id || value.order.row_version !== Number(command.body.expected_version) + 1) invalid();
    const operation = path[2];
    if (operation === "prepare-receipt-line" || operation === "match-invoice-lines") {
      const part = (operation === "prepare-receipt-line" ? value.receipts : value.invoices).find((item) => item.created_version === value.order.row_version);
      if (!part || !value.order.multiline || part.posting_date !== command.body.posting_date || part.period_id !== command.body.period_id) invalid();
      if (operation === "prepare-receipt-line") {
        if ((part as PartialReceipt).order_line_id !== command.body.line_id || scaledQuantity(part.quantity_text) !== scaledQuantity(command.body.quantity)) invalid();
      } else {
        const allocations = (part as PartialInvoice).lines;
        const requestedLines = command.body.lines;
        if (!allocations || !Array.isArray(requestedLines) || allocations.length !== requestedLines.length || allocations.some((line, index) => {
          const raw = requestedLines[index]; return !object(raw) || line.line_id !== raw.line_id || scaledQuantity(line.quantity_text) !== scaledQuantity(raw.quantity);
        })) invalid();
      }
    } else if (operation === "prepare-receipt" || operation === "match-invoice") {
      const part = (operation === "prepare-receipt" ? value.receipts : value.invoices).find((item) => item.created_version === value.order.row_version);
      if (!part || scaledQuantity(part.quantity_text) !== scaledQuantity(command.body.quantity) || part.posting_date !== command.body.posting_date || part.period_id !== command.body.period_id) invalid();
    } else if (operation === "submit-order" || operation === "approve-order") {
      if (value.order.stage !== (operation === "submit-order" ? "Submitted" : "Approved")) invalid();
    } else {
      const receipts = operation === "review-receipt" || operation === "receive";
      const part = (receipts ? value.receipts : value.invoices).find((item) => item.id === command.body.document_id);
      const stages: Record<string, string> = { "review-receipt": "Reviewed", receive: "Posted", "approve-invoice": "Approved", "prepare-accrual": "AccrualPrepared", "review-accrual": "AccrualReviewed", "post-accrual": "Accrued" };
      const stage = stages[operation];
      if (!stage || !part || part.stage !== stage) invalid();
    }
  }
  return value;
}
