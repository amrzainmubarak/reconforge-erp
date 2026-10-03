import { policyFor } from "./receivables-test-fixtures";
import { arFetch, draftRequest, invoiceAmounts, minorInteger, parseInvoice, transitionRequest } from "./receivables-data";
import { AdminApiError } from "./data";

export const arCustomer = { id: "cus-1", customer_code: "CUS-1", name: "Synthetic customer", currency_code: "USD", monetary_policy: policyFor(), status: "Active", credit_hold: false };
export const arInvoice = { id: "inv-1", customer_id: "cus-1", invoice_number: "INV-1", invoice_date: "2026-10-03", due_date: "2026-10-31", currency_code: "USD", monetary_policy: policyFor(), status: "Draft", created_by: "maker-id", approved_by: null, row_version: 1, subtotal_minor: 1251, tax_minor: 125, total_minor: 1376, outstanding_minor: 1376, lines: [{ description: "Synthetic service", quantity: "1.25", unit_price_minor: 1001, line_total_minor: 1251, tax_minor: 125 }] };
const session = { tenantId: "tenant-a", csrfToken: "memory-only", expiresAt: "2030-01-01T00:00:00Z" };

test("exact HALF_UP arithmetic and JSON serialization use integer minor units", () => {
  expect(invoiceAmounts("1.25", "1001", "125")).toEqual({ subtotal: 1251n, tax: 125n, total: 1376n });
  expect(invoiceAmounts("0.5", "1", "0").subtotal).toBe(1n);
  expect(invoiceAmounts("0.49999999999", "1", "0").subtotal).toBe(0n);
  const request = draftRequest({ number: "INV-1", customer: arCustomer, invoiceDate: "2026-10-03", dueDate: "2026-10-31", description: "Synthetic service", quantity: "1.25", price: "10.01", tax: "1.25" }, "workspace-a", "fixed-key");
  expect(request.body).toMatchObject({ tax_minor: 125, idempotency_key: "fixed-key", lines: [{ quantity: "1.25", unit_price_minor: 1001, line_total_minor: 1251, tax_minor: 125 }] });
  expect(JSON.stringify(request.body)).not.toContain("e+");
});

test.each(["NaN", "Infinity", "1e3", "-1", "0", "1,25", "1234567890123"])("invalid or unsupported quantity %s fails closed", (quantity) => {
  expect(() => invoiceAmounts(quantity, "1", "0")).toThrow("ar_quantity_invalid");
});

test("safe integer transport boundary includes line and combined totals", () => {
  expect(minorInteger("9007199254740991")).toBe(9007199254740991n);
  expect(() => minorInteger("9007199254740992")).toThrow("ar_amount_invalid");
  expect(() => invoiceAmounts("2", "9007199254740991", "0")).toThrow("ar_amount_invalid");
  expect(() => invoiceAmounts("1", "9007199254740991", "1")).toThrow("ar_amount_invalid");
  expect(() => parseInvoice({ ...arInvoice, total_minor: 9007199254740992 })).toThrow("ar_contract_invalid");
  expect(() => parseInvoice({ ...arInvoice, lines: [{ ...arInvoice.lines[0], unit_price_minor: 9007199254740992 }] })).toThrow("ar_contract_invalid");
});

test("invoice response totals must be consistent and versioned transitions use returned version", () => {
  expect(parseInvoice(arInvoice)).toEqual(arInvoice);
  expect(() => parseInvoice({ ...arInvoice, total_minor: 1377 })).toThrow("ar_contract_invalid");
  expect(() => parseInvoice({ ...arInvoice, outstanding_minor: 1377 })).toThrow("ar_contract_invalid");
  expect(() => parseInvoice({ ...arInvoice, lines: [{ ...arInvoice.lines[0], line_total_minor: 1250 }] })).toThrow("ar_contract_invalid");
  expect(() => parseInvoice({ ...arInvoice, lines: [{ ...arInvoice.lines[0], tax_minor: 124 }] })).toThrow("ar_contract_invalid");
  expect(transitionRequest({ ...arInvoice, row_version: 7 }, "approve")).toMatchObject({ path: "/api/v1/receivables/invoices/inv-1/approve", body: { expected_version: 7 } });
});

test("same-origin reads scope tenant/workspace and writes add only memory CSRF", async () => {
  const fetcher = vi.fn().mockResolvedValue(new Response("{}", { status: 200 }));
  await arFetch(session, "/api/v1/receivables/invoices", "workspace-a", { fetcher });
  expect(fetcher).toHaveBeenCalledWith("/api/v1/receivables/invoices", expect.objectContaining({ credentials: "same-origin", cache: "no-store", headers: { Accept: "application/json", "X-ReconForge-Tenant": "tenant-a", "X-ReconForge-Workspace": "workspace-a" } }));
  fetcher.mockResolvedValue(new Response("{}", { status: 200 }));
  await arFetch(session, "/api/v1/receivables/invoices", "workspace-a", { fetcher, body: { expected_version: 1 } });
  expect(fetcher.mock.lastCall?.[1].headers["X-ReconForge-CSRF"]).toBe("memory-only");
  await expect(arFetch(session, "https://outside.invalid/api/v1/receivables/invoices", "workspace-a", { fetcher })).rejects.toThrow("ar_path_invalid");
  expect(fetcher).toHaveBeenCalledTimes(2);
});

test("unsafe received values and server denial never become financial success", async () => {
  await expect(arFetch(session, "/api/v1/receivables/invoices", "workspace-a", { fetcher: vi.fn().mockResolvedValue(new Response('{"total_minor":9007199254740993}')) })).rejects.toThrow("ar_contract_invalid");
  await expect(arFetch(session, "/api/v1/receivables/invoices", "workspace-a", { fetcher: vi.fn().mockResolvedValue(new Response('{"error":{"code":"permission_denied","message":"private detail"}}', { status: 403 })) })).rejects.toEqual(new AdminApiError(403, "permission_denied"));
});
