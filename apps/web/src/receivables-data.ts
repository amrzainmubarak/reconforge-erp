import { AdminApiError } from "./data";
import type { BrowserAdminSession } from "./types";

import { MAX_MINOR, capturedPolicy, majorToMinor, parseMonetaryPolicy, requireMoneyAffinity, type ArMinor, type ArMoneyRecord } from "./receivables-money";
export { MAX_MINOR } from "./receivables-money";
export interface ReceivablesIdentity { id: string; username: string; permissions: string[]; workspaces: string[]; human: boolean }
export interface ArCustomer extends ArMoneyRecord { id: string; customer_code: string; name: string; currency_code: string; status: string; credit_hold: boolean }
export interface ArLine { description: string; quantity: string; unit_price_minor: ArMinor; line_total_minor: ArMinor; tax_minor: ArMinor }
export interface ArInvoice extends ArMoneyRecord {
  id: string; customer_id: string; invoice_number: string; invoice_date: string; due_date: string; currency_code: string;
  status: string; created_by: string; approved_by: string | null; row_version: number;
  subtotal_minor: ArMinor; tax_minor: ArMinor; total_minor: ArMinor; outstanding_minor: ArMinor; lines: ArLine[];
}
export interface ArPage<T> { records: T[]; total: number }
export interface InvoiceDraft { number: string; customer: ArCustomer; invoiceDate: string; dueDate: string; description: string; quantity: string; price: string; tax: string }
export interface ArRequest { path: string; body: object; kind: "draft" | "submit" | "approve" }
export interface ArReceipt extends ArMoneyRecord {
  id: string; customer_id: string; receipt_number: string; receipt_date: string; currency_code: string;
  amount_minor: ArMinor; allocated_minor: ArMinor; unallocated_minor: ArMinor; row_version: number; status: string;
  allocations: { invoice_id: string; amount_minor: ArMinor }[];
}
export interface CashRequest { path: string; body: object; kind: "receipt" | "allocation"; amount: bigint; allocation: bigint; receiptId?: string }
const root = "/api/v1/receivables";
const object = (value: unknown): value is Record<string, unknown> => typeof value === "object" && value !== null && !Array.isArray(value);
const text = (value: unknown): value is string => typeof value === "string";
const strings = (value: unknown): value is string[] => Array.isArray(value) && value.every(text);
const safe = (value: unknown): value is number => typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
function invalid(): never { throw new Error("ar_contract_invalid"); }

/** Money stays text/BigInt until the validated, exactly representable JSON boundary. */
export function minorInteger(value: string): bigint {
  if (!/^(0|[1-9]\d{0,15})$/.test(value)) throw new Error("ar_amount_invalid");
  const amount = BigInt(value);
  if (amount > MAX_MINOR) throw new Error("ar_amount_invalid");
  return amount;
}

export function invoiceAmounts(quantity: string, price: string, tax: string) {
  // This bounded UI also stays within the existing AR adapter's decimal precision.
  // General arbitrary-precision quantity support is a separate backend contract.
  if (!/^(0|[1-9]\d*)(\.\d+)?$/.test(quantity) || quantity.replace(".", "").length > 12) throw new Error("ar_quantity_invalid");
  const [whole, fraction = ""] = quantity.split(".");
  const coefficient = BigInt(whole + fraction);
  if (coefficient <= 0n) throw new Error("ar_quantity_invalid");
  const denominator = 10n ** BigInt(fraction.length);
  const product = coefficient * minorInteger(price);
  if (product >= 10n ** 28n) throw new Error("ar_amount_invalid");
  const subtotal = (product * 2n + denominator) / (denominator * 2n);
  const taxAmount = minorInteger(tax);
  const total = subtotal + taxAmount;
  if (subtotal > MAX_MINOR || total > MAX_MINOR) throw new Error("ar_amount_invalid");
  return { subtotal, tax: taxAmount, total };
}

/** Exact companions are authoritative for magnitudes outside JavaScript's integer range. */
function readMinor(record: Record<string, unknown>, key: string, signed = false): ArMinor {
  const raw = record[key], exact = record[`${key}_text`];
  if (exact !== undefined) {
    if (typeof exact !== "string" || !(signed ? /^(0|-?[1-9]\d{0,127})$/ : /^(0|[1-9]\d{0,127})$/).test(exact) || typeof raw !== "number" || !Number.isInteger(raw) || (!signed && raw < 0)) invalid();
    // Only a transport consistency check: exact text/BigInt remains the monetary authority.
    if (Number(exact) !== raw) invalid();
    if (Number.isSafeInteger(raw) && BigInt(raw) !== BigInt(exact)) invalid();
    return exact;
  }
  if (typeof raw !== "number" || !Number.isSafeInteger(raw) || (!signed && raw < 0)) invalid();
  return raw;
}
function validateNumbers(value: unknown): void {
  if (Array.isArray(value)) value.forEach(validateNumbers);
  else if (object(value)) Object.entries(value).forEach(([key, item]) => {
    if (key.endsWith("_minor") && typeof item === "number") readMinor(value, key, true);
    else validateNumbers(item);
  });
  else if (typeof value === "number" && !Number.isSafeInteger(value)) invalid();
}
function policyFields(record: Record<string, unknown>) {
  const policy = parseMonetaryPolicy(record.monetary_policy, String(record.currency_code));
  return policy === undefined ? {} : { monetary_policy: policy };
}

export function parseCustomer(value: unknown): ArCustomer {
  if (!object(value) || !["id", "customer_code", "name", "currency_code", "status"].every((key) => text(value[key])) || !/^\p{L}{3}$/u.test(String(value.currency_code)) || typeof value.credit_hold !== "boolean") invalid();
  validateNumbers(value);
  return { ...value, ...policyFields(value) } as unknown as ArCustomer;
}

export function parseInvoice(value: unknown): ArInvoice {
  if (!object(value) || !["id", "customer_id", "invoice_number", "invoice_date", "due_date", "currency_code", "status", "created_by"].every((key) => text(value[key])) || !/^\p{L}{3}$/u.test(String(value.currency_code)) || !safe(value.row_version) || value.row_version < 1 || !Array.isArray(value.lines) || !(value.approved_by === null || text(value.approved_by))) invalid();
  validateNumbers(value);
  const lines = value.lines.map((raw) => {
    if (!object(raw) || !text(raw.description) || !text(raw.quantity_text ?? raw.quantity)) invalid();
    const quantity = String(raw.quantity_text ?? raw.quantity);
    if (!/^\d+(\.\d+)?$/.test(quantity)) invalid();
    return { description: raw.description, quantity, unit_price_minor: readMinor(raw, "unit_price_minor"), line_total_minor: readMinor(raw, "line_total_minor"), tax_minor: readMinor(raw, "tax_minor") } as ArLine;
  });
  const money = Object.fromEntries(["subtotal_minor", "tax_minor", "total_minor", "outstanding_minor"].map((key) => [key, readMinor(value, key)]));
  if (BigInt(money.subtotal_minor) + BigInt(money.tax_minor) !== BigInt(money.total_minor)) invalid();
  if (!lines.length || lines.reduce((sum, line) => sum + BigInt(line.line_total_minor), 0n) !== BigInt(money.subtotal_minor) || lines.reduce((sum, line) => sum + BigInt(line.tax_minor), 0n) !== BigInt(money.tax_minor) || BigInt(money.outstanding_minor) > BigInt(money.total_minor)) invalid();
  return { ...value, ...money, ...policyFields(value), lines } as unknown as ArInvoice;
}

export function parseReceipt(value: unknown): ArReceipt {
  if (!object(value) || !["id", "customer_id", "receipt_number", "receipt_date", "currency_code", "status"].every((key) => text(value[key])) || !/^\p{L}{3}$/u.test(String(value.currency_code)) || !safe(value.row_version) || value.row_version < 1 || !Array.isArray(value.allocations)) invalid();
  validateNumbers(value);
  const ids = new Set<string>();
  const allocations = value.allocations.map((raw) => {
    if (!object(raw) || !text(raw.invoice_id) || ids.has(raw.invoice_id) || BigInt(readMinor(raw, "amount_minor")) <= 0n) invalid();
    ids.add(raw.invoice_id); return { invoice_id: raw.invoice_id, amount_minor: readMinor(raw, "amount_minor") };
  });
  const money = Object.fromEntries(["amount_minor", "allocated_minor", "unallocated_minor"].map((key) => [key, readMinor(value, key)]));
  if (BigInt(money.amount_minor) === 0n || allocations.reduce((sum, item) => sum + BigInt(item.amount_minor), 0n) !== BigInt(money.allocated_minor) || BigInt(money.allocated_minor) + BigInt(money.unallocated_minor) !== BigInt(money.amount_minor)) invalid();
  return { ...value, ...money, ...policyFields(value), allocations } as unknown as ArReceipt;
}

function openInvoice(invoice: ArInvoice) {
  if (!["Approved", "PartiallyPaid"].includes(invoice.status) || BigInt(invoice.outstanding_minor) <= 0n) throw new Error("cash_balance_invalid");
}

export function cashReceiptRequest(invoice: ArInvoice, customer: ArCustomer, fields: { number: string; date: string; amount: string; allocation: string }, workspace: string, key: string): CashRequest {
  openInvoice(invoice);
  requireMoneyAffinity(invoice, customer);
  const amount = majorToMinor(fields.amount, customer), allocation = majorToMinor(fields.allocation, invoice);
  if (amount <= 0n || allocation > amount || allocation > BigInt(invoice.outstanding_minor) || invoice.customer_id !== customer.id || invoice.currency_code !== customer.currency_code) throw new Error("cash_balance_invalid");
  return { kind: "receipt", path: `${root}/receipts`, amount, allocation, body: { receipt_number: fields.number, customer_code: customer.customer_code, receipt_date: fields.date, currency_code: customer.currency_code, amount_minor: Number(amount), allocations: allocation > 0n ? [{ invoice_id: invoice.id, amount_minor: Number(allocation) }] : [], workspace, idempotency_key: key } };
}

export function cashAllocationRequest(receipt: ArReceipt, invoice: ArInvoice, amountText: string): CashRequest {
  openInvoice(invoice);
  requireMoneyAffinity(receipt, invoice);
  const amount = majorToMinor(amountText, receipt);
  if (receipt.status !== "Posted" || receipt.customer_id !== invoice.customer_id || receipt.currency_code !== invoice.currency_code || amount <= 0n || amount > BigInt(receipt.unallocated_minor) || amount > BigInt(invoice.outstanding_minor)) throw new Error("cash_balance_invalid");
  return { kind: "allocation", path: `${root}/receipts/${encodeURIComponent(receipt.id)}/allocate`, receiptId: receipt.id, amount, allocation: amount, body: { invoice_id: invoice.id, amount_minor: Number(amount), expected_version: receipt.row_version } };
}

export async function loadReceipt(session: BrowserAdminSession, workspace: string, id: string, signal?: AbortSignal): Promise<ArReceipt> {
  const record = parseReceipt(await arFetch(session, `${root}/receipts/${encodeURIComponent(id)}`, workspace, { signal }));
  if (record.id !== id) invalid();
  return record;
}

export async function loadCashInvoice(session: BrowserAdminSession, workspace: string, id: string, signal?: AbortSignal): Promise<ArInvoice> {
  const record = parseInvoice(await arFetch(session, `${root}/invoices/${encodeURIComponent(id)}`, workspace, { signal }));
  if (record.id !== id) invalid();
  return record;
}

export async function loadCashCustomer(session: BrowserAdminSession, workspace: string, id: string, signal?: AbortSignal): Promise<ArCustomer> {
  const record = parseCustomer(await arFetch(session, `${root}/customers/${encodeURIComponent(id)}`, workspace, { signal }));
  if (record.id !== id) invalid();
  return record;
}

export async function loadCashExposure(session: BrowserAdminSession, workspace: string, customer: ArCustomer, signal?: AbortSignal): Promise<ArMinor> {
  const value = await arFetch(session, `${root}/credit-exposure/${encodeURIComponent(customer.customer_code)}`, workspace, { signal });
  if (!object(value) || value.customer_id !== customer.id || value.currency_code !== customer.currency_code) invalid();
  return readMinor(value, "exposure_minor");
}

export async function loadCashPage(session: BrowserAdminSession, workspace: string, customerId: string, offset: number, signal?: AbortSignal): Promise<ArPage<ArReceipt>> {
  const value = await arFetch(session, `${root}/receipts?customer_id=${encodeURIComponent(customerId)}&limit=25&offset=${offset}`, workspace, { signal });
  if (!object(value) || !Array.isArray(value.receipts) || !object(value.pagination) || !safe(value.pagination.total)) invalid();
  const records = value.receipts.map(parseReceipt);
  if (records.some((record) => record.customer_id !== customerId)) invalid();
  return { records, total: value.pagination.total };
}

export async function arFetch(session: BrowserAdminSession, path: string, workspace = "", options: { body?: object; signal?: AbortSignal; fetcher?: typeof fetch } = {}): Promise<unknown> {
  if (!(path === "/api/v1/auth/me" || path.startsWith(`${root}/`))) throw new Error("ar_path_invalid");
  const response = await (options.fetcher ?? fetch)(path, {
    method: options.body ? "POST" : "GET", credentials: "same-origin", cache: "no-store", signal: options.signal,
    headers: { Accept: "application/json", "X-ReconForge-Tenant": session.tenantId, ...(workspace ? { "X-ReconForge-Workspace": workspace } : {}), ...(options.body ? { "Content-Type": "application/json", "X-ReconForge-CSRF": session.csrfToken } : {}) },
    ...(options.body ? { body: JSON.stringify(options.body) } : {}),
  });
  if (!response.ok) {
    let code = `http_${response.status}`;
    try { const error: unknown = await response.json(); if (object(error) && object(error.error) && text(error.error.code)) code = error.error.code; } catch { /* Preserve safe status fallback. */ }
    throw new AdminApiError(response.status, code);
  }
  const value: unknown = await response.json();
  validateNumbers(value);
  return value;
}

export async function loadArIdentity(session: BrowserAdminSession, signal?: AbortSignal): Promise<ReceivablesIdentity> {
  const value = await arFetch(session, "/api/v1/auth/me", "", { signal });
  if (!object(value) || !text(value.id) || !text(value.username) || !strings(value.permissions) || !object(value.authorized_scopes) || !strings(value.authorized_scopes.workspaces)) invalid();
  return { id: value.id, username: value.username, permissions: value.permissions, workspaces: value.authorized_scopes.workspaces, human: value.principal_type === "user" };
}

export async function loadArPage<T>(session: BrowserAdminSession, workspace: string, kind: "customers" | "invoices", offset: number, parse: (value: unknown) => T, signal?: AbortSignal): Promise<ArPage<T>> {
  const value = await arFetch(session, `${root}/${kind}?limit=25&offset=${offset}`, workspace, { signal });
  if (!object(value) || !Array.isArray(value[kind]) || !object(value.pagination) || !safe(value.pagination.total)) invalid();
  return { records: value[kind].map(parse), total: value.pagination.total };
}

export function draftRequest(draft: InvoiceDraft, workspace: string, idempotencyKey: string): ArRequest {
  const price = majorToMinor(draft.price, draft.customer), tax = majorToMinor(draft.tax, draft.customer);
  const amounts = invoiceAmounts(draft.quantity, String(price), String(tax));
  return { kind: "draft", path: `${root}/invoices`, body: {
    invoice_number: draft.number, customer_code: draft.customer.customer_code, currency_code: draft.customer.currency_code,
    invoice_date: draft.invoiceDate, due_date: draft.dueDate, workspace, tax_minor: Number(amounts.tax), idempotency_key: idempotencyKey,
    lines: [{ description: draft.description, quantity: draft.quantity, unit_price_minor: Number(price), line_total_minor: Number(amounts.subtotal), tax_minor: Number(amounts.tax) }],
  } };
}

export function transitionRequest(invoice: ArInvoice, action: "submit" | "approve"): ArRequest {
  capturedPolicy(invoice);
  return { kind: action, path: `${root}/invoices/${encodeURIComponent(invoice.id)}/${action}`, body: { expected_version: invoice.row_version } };
}
