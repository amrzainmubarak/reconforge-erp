import { cashAllocationRequest, cashReceiptRequest, MAX_MINOR, parseReceipt, type ArInvoice } from "./receivables-data";

const customer = { id: "cus", customer_code: "CUS", name: "Synthetic", currency_code: "USD", status: "Active", credit_hold: false };
const invoice: ArInvoice = { id: "inv", customer_id: "cus", invoice_number: "INV", invoice_date: "2026-10-03", due_date: "2026-10-03", currency_code: "USD", status: "Approved", created_by: "maker", approved_by: "checker", row_version: 3, subtotal_minor: 1376, tax_minor: 0, total_minor: 1376, outstanding_minor: 1376, lines: [{ description: "Synthetic", quantity: "1", unit_price_minor: 1376, line_total_minor: 1376, tax_minor: 0 }] };
const receipt = { id: "rct", customer_id: "cus", receipt_number: "RCT", receipt_date: "2026-10-03", currency_code: "USD", amount_minor: 1000, allocated_minor: 400, unallocated_minor: 600, row_version: 2, status: "Posted", allocations: [{ invoice_id: "inv", amount_minor: 400 }] };

test("receipt arithmetic uses independently stated integer outcomes and exact safe transport ceiling", () => {
  const request = cashReceiptRequest(invoice, customer, { number: "RCT", date: "2026-10-03", amount: String(MAX_MINOR), allocation: "1376" }, "workspace", "frozen-key");
  expect(request.amount).toBe(9007199254740991n);
  expect(request.allocation).toBe(1376n);
  expect(request.body).toEqual({ receipt_number: "RCT", customer_code: "CUS", receipt_date: "2026-10-03", currency_code: "USD", amount_minor: 9007199254740991, allocations: [{ invoice_id: "inv", amount_minor: 1376 }], workspace: "workspace", idempotency_key: "frozen-key" });
  expect(cashReceiptRequest(invoice, customer, { number: "RCT", date: "2026-10-03", amount: "1000", allocation: "0" }, "workspace", "key").body).toMatchObject({ allocations: [] });
});

test.each(["0", "-1", "1.5", "1e3", "NaN", "9007199254740992"])("invalid receipt amount %s never reaches JSON transport", (amount) => {
  expect(() => cashReceiptRequest(invoice, customer, { number: "RCT", date: "2026-10-03", amount, allocation: "0" }, "workspace", "key")).toThrow();
});

test("allocation enforces both balances, currency, customer and lifecycle with frozen CAS", () => {
  expect(cashAllocationRequest(receipt, invoice, "600").body).toEqual({ invoice_id: "inv", amount_minor: 600, expected_version: 2 });
  for (const altered of [{ ...receipt, unallocated_minor: 599 }, { ...receipt, currency_code: "JPY" }, { ...receipt, customer_id: "sibling" }, { ...receipt, status: "Cancelled" }]) expect(() => cashAllocationRequest(altered, invoice, "600")).toThrow("cash_balance_invalid");
  expect(() => cashAllocationRequest(receipt, { ...invoice, outstanding_minor: 599 }, "600")).toThrow();
  expect(() => cashAllocationRequest(receipt, { ...invoice, status: "Draft" }, "1")).toThrow();
  expect(() => cashReceiptRequest(invoice, customer, { number: "RCT", date: "2026-10-03", amount: "100", allocation: "101" }, "workspace", "key")).toThrow();
});

test("receipt readback rejects inconsistent sums, unsafe values and duplicated invoice allocations", () => {
  expect(parseReceipt(receipt)).toEqual(receipt);
  for (const altered of [{ ...receipt, amount_minor: 1001 }, { ...receipt, allocated_minor: 401 }, { ...receipt, unallocated_minor: -1 }, { ...receipt, amount_minor: 9007199254740992 }, { ...receipt, row_version: 1.5 }, { ...receipt, allocations: [...receipt.allocations, ...receipt.allocations] }]) expect(() => parseReceipt(altered)).toThrow("ar_contract_invalid");
});
