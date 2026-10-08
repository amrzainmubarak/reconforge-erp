import { procurementFetch, type ProcurementScope } from "./procurement-data";
import type { PreparedScopedCommand } from "./scoped-command";
import type { BrowserAdminSession } from "./types";

export const partialRoot = "/api/v1/procurement-partial";
export interface PartialOrder { id: string; number: string; workspace_id: string; organization_id: string; legal_entity_id: string; purchase_order_id: string; row_version: number; stage: "Draft" | "Submitted" | "Approved"; total_minor: string; request: Record<string, string> }
export interface PartialReceipt { id: string; number: string; sequence: number; quantity_text: string; total_minor: string; posting_date: string; period_id: string; receipt_plan_id: string; goods_receipt_id: string | null; stage: "Prepared" | "Reviewed" | "Posted"; created_version: number; reviewed_version: number | null; posted_version: number | null }
export interface InstallmentPlan { id: string; workspace_id: string; organization_id: string; legal_entity_id: string; source_kind: "APPayment"; source_id: string; entry_id: string; period_id: string; posting_date: string; currency_code: string; currency_precision: number; status: "Prepared" | "Reviewed" | "Posted"; phase: number; plan_digest: string; validation_digest: string; preparer_actor_id: string; reviewer_actor_id: string | null; posting_effect_id: string | null; payment_link_id: string | null; amount_minor: string; allocated_before_minor: string; invoice_version: number }
export interface PartialInvoice { id: string; number: string; sequence: number; quantity_text: string; total_minor: string; posting_date: string; period_id: string; native_invoice_id: string; accrual_plan_id: string | null; accrual_effect_id: string | null; stage: "Matched" | "Approved" | "AccrualPrepared" | "AccrualReviewed" | "Accrued"; created_version: number; approved_version: number | null; prepared_version: number | null; reviewed_version: number | null; posted_version: number | null; native_status: "Matched" | "Approved" | "Paid"; native_version: number; paid_minor: string; outstanding_minor: string; payment_links: { id: string; finance_effect_id: string; amount_minor: string; created_at: string }[]; installment_plans: InstallmentPlan[] }
export interface PartialDetail { order: PartialOrder; receipts: PartialReceipt[]; invoices: PartialInvoice[]; totals: { ordered_quantity: string; reserved_receipt_quantity: string; received_quantity: string; invoiced_quantity: string; received_minor: string; accrued_minor: string; paid_minor: string; outstanding_minor: string } }

const object = (value: unknown): value is Record<string, unknown> => typeof value === "object" && value !== null && !Array.isArray(value);
const text = (value: unknown): value is string => typeof value === "string" && value.length > 0 && value.length <= 500;
const money = (value: unknown): value is string => typeof value === "string" && /^(?:0|[1-9][0-9]{0,18})$/.test(value) && BigInt(value) <= 9000000000000000000n;
const version = (value: unknown): value is number => Number.isSafeInteger(value) && Number(value) > 0;
function invalid(): never { throw new Error("procurement_partial_contract_invalid"); }
export function parseInstallmentPlan(value: unknown, scope: ProcurementScope, invoiceId: string): InstallmentPlan {
  if (!object(value) || !["id", "entry_id", "period_id", "posting_date", "preparer_actor_id"].every((key) => text(value[key])) ||
    value.workspace_id !== scope.workspace_id || value.organization_id !== scope.organization_id || value.legal_entity_id !== scope.legal_entity_id ||
    value.source_kind !== "APPayment" || value.source_id !== invoiceId || value.currency_code !== scope.currency_code ||
    !Number.isInteger(value.currency_precision) || Number(value.currency_precision) < 0 || Number(value.currency_precision) > 8 ||
    !Number.isInteger(value.phase) || ![0, 1, 2].includes(Number(value.phase)) || value.status !== ["Prepared", "Reviewed", "Posted"][Number(value.phase)] ||
    typeof value.plan_digest !== "string" || !/^[0-9a-f]{64}$/.test(value.plan_digest) || typeof value.validation_digest !== "string" || !/^[0-9a-f]{64}$/.test(value.validation_digest) ||
    !money(value.amount_minor) || value.amount_minor === "0" || !money(value.allocated_before_minor) || !version(value.invoice_version) ||
    ![value.reviewer_actor_id, value.posting_effect_id, value.payment_link_id].every((item) => item === null || text(item)) ||
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
  if (!["id", "number", "purchase_order_id"].every((key) => text(order[key])) || !version(order.row_version) || !money(order.total_minor) || order.total_minor === "0" ||
    order.workspace_id !== scope.workspace_id || order.organization_id !== scope.organization_id || order.legal_entity_id !== scope.legal_entity_id ||
    !["Draft", "Submitted", "Approved"].includes(String(order.stage)) || !object(order.request) || !Object.values(order.request).every((item) => typeof item === "string") ||
    order.request.organization_code !== scope.organization_code || order.request.entity_code !== scope.entity_code || order.request.currency_code !== scope.currency_code || !money(order.request.unit_price_minor)) invalid();
  const request = order.request as Record<string, string>;
  if (scaledQuantity(request.quantity) * BigInt(request.unit_price_minor) !== BigInt(String(order.total_minor)) * 1000000n) invalid();
  const receipts = value.receipts.map((part, index) => {
    if (!object(part) || !["id", "number", "receipt_plan_id", "posting_date", "period_id"].every((key) => text(part[key])) ||
      part.order_id !== order.id || part.sequence !== index + 1 || !["Prepared", "Reviewed", "Posted"].includes(String(part.stage)) || !version(part.created_version) || Number(part.created_version) > Number(order.row_version) ||
      !money(part.total_minor) || part.total_minor === "0" || scaledQuantity(part.quantity_text) <= 0n ||
      ![part.reviewed_version, part.posted_version].every((item) => item === null || version(item)) || (part.goods_receipt_id !== null && !text(part.goods_receipt_id)) ||
      (part.stage === "Prepared") !== (part.reviewed_version === null) || (part.stage === "Posted") !== (part.posted_version !== null && part.goods_receipt_id !== null)) invalid();
    if (scaledQuantity(part.quantity_text) * BigInt(request.unit_price_minor) !== BigInt(part.total_minor) * 1000000n) invalid();
    return part as unknown as PartialReceipt;
  });
  const invoices = value.invoices.map((part, index) => {
    if (!object(part) || !["id", "number", "native_invoice_id", "posting_date", "period_id"].every((key) => text(part[key])) || part.order_id !== order.id || part.sequence !== index + 1 ||
      !["Matched", "Approved", "AccrualPrepared", "AccrualReviewed", "Accrued"].includes(String(part.stage)) || !version(part.created_version) || !version(part.native_version) || Number(part.created_version) > Number(order.row_version) ||
      !["Matched", "Approved", "Paid"].includes(String(part.native_status)) || !money(part.total_minor) || part.total_minor === "0" || !money(part.paid_minor) || !money(part.outstanding_minor) ||
      BigInt(part.paid_minor) + BigInt(part.outstanding_minor) !== BigInt(part.total_minor) ||
      (part.native_status === "Paid") !== (part.outstanding_minor === "0") || !Array.isArray(part.payment_links) || part.payment_links.length > 200 ||
      !part.payment_links.every((link) => object(link) && text(link.id) && text(link.finance_effect_id) && money(link.amount_minor) && link.amount_minor !== "0" && text(link.created_at)) ||
      ![part.approved_version, part.prepared_version, part.reviewed_version, part.posted_version].every((item) => item === null || version(item)) ||
      ![part.accrual_plan_id, part.accrual_effect_id].every((item) => item === null || text(item)) || !Array.isArray(part.installment_plans) || part.installment_plans.length > 200) invalid();
    const plans = part.installment_plans.map((plan) => parseInstallmentPlan(plan, scope, String(part.native_invoice_id)));
    if (plans.filter((plan) => plan.phase < 2).length > 1 || plans.filter((plan) => plan.phase === 2).reduce((total, plan) => total + BigInt(plan.amount_minor), 0n) !== BigInt(part.paid_minor) ||
      plans.some((plan) => plan.phase === 2 && !(part.payment_links as Record<string, unknown>[]).some((link) => link.id === plan.payment_link_id && link.finance_effect_id === plan.posting_effect_id && link.amount_minor === plan.amount_minor))) invalid();
    const stage = ["Matched", "Approved", "AccrualPrepared", "AccrualReviewed", "Accrued"].indexOf(String(part.stage));
    if ([part.approved_version, part.prepared_version, part.reviewed_version, part.posted_version].some((item, i) => (stage > i) !== (item !== null)) ||
      (stage >= 2) !== (part.accrual_plan_id !== null) || (stage === 4) !== (part.accrual_effect_id !== null) ||
      (stage === 0) !== (part.native_status === "Matched") || (stage < 4 && part.paid_minor !== "0") ||
      scaledQuantity(part.quantity_text) * BigInt(request.unit_price_minor) !== BigInt(part.total_minor) * 1000000n ||
      part.payment_links.reduce((total, link) => total + BigInt(String(link.amount_minor)), 0n) !== BigInt(part.paid_minor)) invalid();
    return part as unknown as PartialInvoice;
  });
  const totals = value.totals;
  const sumQuantity = (parts: (PartialReceipt | PartialInvoice)[]) => parts.reduce((total, part) => total + scaledQuantity(part.quantity_text), 0n);
  const sumMoney = (parts: (PartialReceipt | PartialInvoice)[], field: "total_minor" | "paid_minor" | "outstanding_minor" = "total_minor") => parts.reduce((total, part) => total + BigInt(String((part as unknown as Record<string, unknown>)[field])), 0n);
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
  if (command.path === partialRoot + "/orders") {
    if (value.order.row_version !== 1 || value.order.stage !== "Draft" || value.order.number !== String(command.body.number).trim().toUpperCase()) invalid();
    if (scaledQuantity(value.order.request.quantity) !== scaledQuantity(command.body.quantity) || value.order.request.unit_price_minor !== command.body.unit_price_minor) invalid();
  } else {
    const path = /^\/api\/v1\/procurement-partial\/orders\/([^/]+)\/commands\/([^/]+)$/.exec(command.path);
    if (!path || decodeURIComponent(path[1]) !== value.order.id || value.order.row_version !== Number(command.body.expected_version) + 1) invalid();
    const operation = path[2];
    if (operation === "prepare-receipt" || operation === "match-invoice") {
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
