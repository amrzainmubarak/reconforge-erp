import { cashAllocationRequest, cashReceiptRequest, draftRequest, parseCustomer, parseInvoice, parseReceipt } from "./receivables-data";
import { formatArMoney, majorToMinor, minorToMajorText, parseMonetaryPolicy, requireMoneyAffinity } from "./receivables-money";
import { policyFor } from "./receivables-test-fixtures";

const record = (currency_code: string, precision: number) => ({ currency_code, monetary_policy: policyFor(currency_code, precision) });
const customer = { ...record("KWD", 3), id: "cus", customer_code: "CUS", name: "Synthetic", status: "Active", credit_hold: false };
const invoice = { ...record("KWD", 3), id: "inv", customer_id: "cus", invoice_number: "INV", invoice_date: "2026-10-03", due_date: "2026-10-31", status: "Approved", created_by: "maker", approved_by: "checker", row_version: 3, subtotal_minor: 1234, tax_minor: 0, total_minor: 1234, outstanding_minor: 1234, lines: [{ description: "Synthetic", quantity: "1", unit_price_minor: 1234, line_total_minor: 1234, tax_minor: 0 }] };
const receipt = { ...record("KWD", 3), id: "receipt", customer_id: "cus", receipt_number: "R", receipt_date: "2026-10-03", status: "Posted", row_version: 1, amount_minor: 1000, allocated_minor: 500, unallocated_minor: 500, allocations: [{ invoice_id: "inv", amount_minor: 500 }] };

test.each([
  ["JPY", 0, "1234", "1234", "1,234 JPY", "١٬٢٣٤ JPY"],
  ["KWD", 3, "1234", "1.234", "1.234 KWD", "١٫٢٣٤ KWD"],
  ["KWD", 3, "0", "0.000", "0.000 KWD", "٠٫٠٠٠ KWD"],
  ["KWD", 3, "1000", "1.000", "1.000 KWD", "١٫٠٠٠ KWD"],
  ["KWD", 3, "9007199254740993123", "9007199254740993.123", "9,007,199,254,740,993.123 KWD", "٩٬٠٠٧٬١٩٩٬٢٥٤٬٧٤٠٬٩٩٣٫١٢٣ KWD"],
] as const)("retained %s precision %i formats independent exact outcomes for %s", (currency, precision, minor, decimal, en, ar) => {
  const money = record(currency, precision);
  expect(minorToMajorText(minor, money)).toBe(decimal);
  expect(formatArMoney(minor, money, "en", "minor units")).toBe(en);
  expect(formatArMoney(minor, money, "ar", "وحدة صغرى")).toBe(ar);
});

test.each([
  ["JPY", 0, "1234", 1234n], ["KWD", 3, "1.234", 1234n], ["KWD", 3, "1.2", 1200n],
  ["KWD", 3, "١٫٢٣٤", 1234n], ["KWD", 3, "۱٫۲۳۴", 1234n], ["KWD", 3, "0.001", 1n],
  ["KWD", 3, "9007199254740.991", 9007199254740991n],
] as const)("major input for %s/%i converts %s exactly", (currency, precision, text, minor) => {
  expect(majorToMinor(text, record(currency, precision))).toBe(minor);
});

test.each(["1.2345", "9007199254740.992", "1e3", "NaN", "Infinity", "-1", "1,234", "١٬٢٣٤", "1 234", "01", ".1", "1.", "9".repeat(33)])("unsupported major input %s cannot be rounded or sent", (value) => {
  expect(() => majorToMinor(value, record("KWD", 3))).toThrow("ar_major_amount_invalid");
});
test("zero-decimal policies reject fractions even when the excess digit is zero", () => {
  expect(() => majorToMinor("1.0", record("JPY", 0))).toThrow("ar_major_amount_invalid");
});

test("API metadata is closed and malformed or contradictory policy fails before display", () => {
  const valid = policyFor("KWD", 3);
  for (const change of [{ precision: true }, { precision: 3.5 }, { precision: 9 }, { precision: null }, { currency_code: "USD" }, { schema_version: 2 }, { rounding_policy: "ROUND_HALF_EVEN" }, { registry_digest: "short" }, { private_snapshot: {} }, { status: "unverified" }]) expect(() => parseMonetaryPolicy({ ...valid, ...change }, "KWD")).toThrow("ar_contract_invalid");
  expect(parseMonetaryPolicy(valid, "KWD")).toEqual(valid);
});

test("legacy absence remains readable in raw units but cannot create a financial request", () => {
  const legacy = { ...customer, currency_code: "ΔΕΖ", monetary_policy: undefined };
  expect(parseCustomer(legacy)).toEqual(legacy);
  expect(formatArMoney("1234", legacy, "en", "minor units")).toBe("1,234 ΔΕΖ · minor units");
  expect(() => majorToMinor("1234", legacy)).toThrow("ar_monetary_policy_unverified");
  const unverified = { ...policyFor(), status: "unverified", precision: null, rounding_policy: null, registry_version: null, registry_digest: null, policy_digest: null, source: null, source_url: null, published_at: null };
  expect(parseMonetaryPolicy(unverified, "USD")?.status).toBe("unverified");
});

test("same code and scale with different registry evidence never implies affinity", () => {
  expect(() => requireMoneyAffinity(customer, { ...invoice, monetary_policy: { ...invoice.monetary_policy, registry_digest: "c".repeat(64) } })).toThrow("ar_monetary_policy_mismatch");
});

test("KWD draft and cash inputs send independently known minor-unit JSON and no browser policy", () => {
  const draft = draftRequest({ customer, number: "D", invoiceDate: "2026-10-03", dueDate: "2026-10-31", description: "Synthetic", quantity: "1.5", price: "1.001", tax: "0.125" }, "work", "key");
  expect(draft.body).toMatchObject({ tax_minor: 125, lines: [{ unit_price_minor: 1001, line_total_minor: 1502, tax_minor: 125 }] });
  const cash = cashReceiptRequest(invoice, customer, { number: "R", date: "2026-10-03", amount: "1.000", allocation: "0.500" }, "work", "same-key");
  expect(cash.body).toMatchObject({ amount_minor: 1000, allocations: [{ invoice_id: "inv", amount_minor: 500 }] });
  expect(cashAllocationRequest(receipt, invoice, "0.500").body).toEqual({ invoice_id: "inv", amount_minor: 500, expected_version: 1 });
  expect(JSON.stringify([draft.body, cash.body])).not.toMatch(/monetary_policy|registry_digest/);
});

test("exact response companions preserve integers lost by JSON Number parsing", () => {
  const huge = "9007199254740993123";
  const numeric = JSON.parse(huge) as number;
  const line = { ...invoice.lines[0], unit_price_minor: numeric, unit_price_minor_text: huge, line_total_minor: numeric, line_total_minor_text: huge };
  const raw = { ...invoice, subtotal_minor: numeric, subtotal_minor_text: huge, total_minor: numeric, total_minor_text: huge, outstanding_minor: numeric, outstanding_minor_text: huge, lines: [line] };
  const parsed = parseInvoice(raw);
  expect(parsed.total_minor).toBe(huge);
  expect(parsed.lines[0].unit_price_minor).toBe(huge);
  expect(formatArMoney(parsed.total_minor, parsed, "en", "minor units")).toBe("9,007,199,254,740,993.123 KWD");
  expect(() => parseInvoice({ ...raw, total_minor_text: undefined })).toThrow("ar_contract_invalid");
  expect(() => parseInvoice({ ...invoice, total_minor_text: "1235" })).toThrow("ar_contract_invalid");
  expect(() => parseInvoice({ ...raw, total_minor_text: "9e18" })).toThrow("ar_contract_invalid");
  expect(() => parseReceipt({ ...receipt, amount_minor: numeric })).toThrow("ar_contract_invalid");
});

test("an exact companion must agree with the JSON transport's rounded representation", () => {
  expect(() => parseReceipt({ ...receipt, amount_minor: 9007199254740992, amount_minor_text: "1000" })).toThrow("ar_contract_invalid");
});
