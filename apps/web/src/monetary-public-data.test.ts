import { afterEach, expect, it, vi } from "vitest";
import fixtures from "./monetary-test-fixtures.json";
import { monetaryPartialMatchesCommand, parseMonetaryPartialBalance, parseMonetaryPartialPlan } from "./monetary-partial-returns-data";
import { isMonetaryPartialPath, isMonetaryStockPath, monetaryPartialRoot, monetaryStockRoot } from "./monetary-paths";
import { monetaryDate, monetaryMoney, monetaryObject, monetaryRequest, parseMonetaryRate, prepareMonetaryCommand } from "./monetary-public-data";
import { executeMonetaryStockCommand, monetaryStockMatchesCommand, parseMonetaryStock } from "./monetary-stock-data";
import type { ScopedJsonValue } from "./scoped-command";

const scope = fixtures.scope, session = { tenantId: "synthetic", csrfToken: "csrf", expiresAt: "2099-01-01T00:00:00Z" };
afterEach(() => vi.unstubAllGlobals());

it("reads closed dual-currency public DTOs without a legacy fallback or numeric money coercion", () => {
  expect(parseMonetaryStock(fixtures.stock, scope).monetary_origin?.transaction_gross_minor).toBe("1200");
  expect(parseMonetaryPartialPlan(fixtures.return, scope).monetary.functional_turnover_minor).toBe("950");
  expect(parseMonetaryPartialBalance(fixtures.balance, scope, "monetary-stock").transaction_outstanding_minor).toBe("1200");
  expect(parseMonetaryPartialPlan(fixtures.zeroReturn, scope).entries).toEqual([]);
  expect(() => parseMonetaryStock({ ...fixtures.stock, total_minor: "1200" }, scope)).toThrow();
  expect(() => parseMonetaryPartialPlan({ ...fixtures.return, schema_version: "customer-partial-return-v2" }, scope)).toThrow();
});

it.each([true, false, 1, 1.0, null, "01", "+1", "1.0", "1e3", "9000000000000000001"])("refuses malformed new money %s", value => {
  expect(() => parseMonetaryStock({ ...fixtures.draft, transaction_net_minor: value }, scope)).toThrow();
});

it("preserves and formats >2^53 minor units and actual zero/three-decimal currency scales", () => {
  const raw = { ...fixtures.draft, quantity: "1", quantity_scaled: "1", unit_price_minor: "9007199254740993", net_unit_price_minor: "9007199254740993", transaction_net_minor: "9007199254740993" };
  const stock = parseMonetaryStock(raw, scope);
  expect(monetaryMoney(stock.transaction_net_minor, stock.transaction_policy, "en")).toContain("90,071,992,547,409.93 EUR");
  expect(monetaryMoney("1234", { ...stock.transaction_policy, currency_code: "JPY", currency_precision: 0 }, "en")).toBe("1,234 JPY");
  expect(monetaryMoney("1234", { ...stock.transaction_policy, currency_code: "KWD", currency_precision: 3 }, "en")).toBe("1.234 KWD");
});

it.each(["private", "gross", "tax", "rate", "reviewer", "entry", "policy"])("refuses inconsistent original monetary evidence: %s", mutation => {
  const raw = structuredClone(fixtures.stock) as unknown as Record<string, unknown>, source = raw.monetary_origin as Record<string, unknown>;
  if (mutation === "private") source.snapshot = { private: "body" };
  if (mutation === "gross") source.transaction_gross_minor = "1201";
  if (mutation === "tax") (source.tax_components as Record<string, unknown>[])[0].functional_tax_minor = "249";
  if (mutation === "rate") source.original_rate = null;
  if (mutation === "reviewer") raw.issue_reviewer_id = "maker";
  if (mutation === "entry") raw.cogs_effect_id = null;
  if (mutation === "policy") (raw.functional_policy as Record<string, unknown>).currency_registry_digest = "f".repeat(64);
  expect(() => parseMonetaryStock(raw, scope)).toThrow();
});

it("requires explicit restituted admission for zero functional stock cost", () => {
  const raw = { ...fixtures.stock, functional_cogs_minor: "0", cogs_entry_id: null, cogs_effect_id: null };
  expect(() => parseMonetaryStock(raw, scope)).toThrow();
  expect(parseMonetaryStock({ ...raw, cost_admission_policy: "partial-return-restituted-v1" }, scope).functional_cogs_minor).toBe("0");
});

it("refuses a coherent identity-currency carrying mismatch and accepts equal amounts", () => {
  const raw = structuredClone(fixtures.balance);
  raw.transaction_policy = structuredClone(raw.functional_policy);
  expect(() => parseMonetaryPartialBalance(raw, scope, raw.source_order_id)).toThrow();
  raw.functional_original_gross_minor = "1200"; raw.functional_outstanding_minor = "1200";
  expect(parseMonetaryPartialBalance(raw, scope, raw.source_order_id).functional_outstanding_minor).toBe("1200");
});

it.each(["credit", "alignment", "unused", "purpose", "reviewer", "zero-entry"])("refuses counterfeit v3 plan evidence: %s", mutation => {
  const raw = structuredClone(mutation === "zero-entry" ? fixtures.zeroReturn : fixtures.return) as unknown as Record<string, unknown>;
  const amounts = raw.monetary as Record<string, unknown>;
  if (mutation === "credit") amounts.transaction_credit_minor = "601";
  if (mutation === "alignment") { amounts.functional_alignment_gain_minor = "1"; amounts.functional_alignment_loss_minor = "1"; }
  if (mutation === "unused") amounts.functional_fx_gain_minor = "1";
  if (mutation === "purpose") (raw.entries as unknown[]).reverse();
  if (mutation === "reviewer") raw.posted_actor_id = "checker";
  if (mutation === "zero-entry") raw.entries = structuredClone(fixtures.return.entries);
  expect(() => parseMonetaryPartialPlan(raw, scope)).toThrow();
});

it("rejects accessor and symbol payloads before reading untrusted properties", () => {
  const getter = vi.fn(() => "value"), value = Object.defineProperty({}, "field", { get: getter, enumerable: true });
  expect(() => monetaryObject(value, ["field"])).toThrow(); expect(getter).not.toHaveBeenCalled();
  expect(() => monetaryObject({ field: "value", [Symbol("private")]: "extra" }, ["field"])).toThrow();
});

it.each(["2026-02-30", "0000-01-01", "2026-1-01", "2026-10-15T00:00:00Z"])("refuses a noncanonical business date %s", value => {
  expect(() => monetaryDate(value)).toThrow();
});

it("pins rate evidence to the real UTC posting date, with explicit null for identity currency", () => {
  const rate = { rate: "1.25", source: "Synthetic observation", effective_at: "2026-10-15T12:00:00Z" };
  expect(parseMonetaryRate(rate, "2026-10-15", false)).toEqual(rate);
  expect(parseMonetaryRate(null, "2026-10-15", true)).toBeNull();
  for (const raw of [undefined, { ...rate, rate: 1.25 }, { ...rate, effective_at: "2026-10-14T12:00:00Z" }, { ...rate, effective_at: "2026-10-15T24:00:00Z" }]) expect(() => parseMonetaryRate(raw, "2026-10-15", false)).toThrow();
  expect(() => parseMonetaryRate(rate, "2026-10-15", true)).toThrow();
});

it("admits only the fixed v2/v3 resource paths and refuses source upgrade/query/path tricks", async () => {
  const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
  expect(isMonetaryStockPath(`${monetaryStockRoot}/orders`, true)).toBe(true);
  expect(isMonetaryPartialPath(`${monetaryPartialRoot}/plans`, true)).toBe(true);
  for (const path of ["/api/v1/stock-sales/orders", "/api/v2/customer-partial-returns/plans", `${monetaryStockRoot}/commerce/orders`, `${monetaryStockRoot}/orders/x/issue/post`, `${monetaryPartialRoot}/plans?protocol=2`, `${monetaryPartialRoot}/sources/%2e%2e/balance`, `${monetaryPartialRoot}/sources/a%2Fb/balance`]) {
    expect(() => prepareMonetaryCommand(path, {})).toThrow();
    await expect(monetaryRequest(session, scope, path)).rejects.toThrow();
  }
  expect(fetcher).not.toHaveBeenCalled();
});

it("retains exact nested taxes/rates and the original route/body after response loss", async () => {
  const body = { number: fixtures.draft.number, customer_code: fixtures.draft.customer_code, customer_reference: fixtures.draft.customer_reference,
    item_code: fixtures.draft.item_code, warehouse_code: fixtures.draft.warehouse_code, location_code: fixtures.draft.location_code, quantity: "10", unit_price_minor: "100",
    currency_code: "EUR", order_date: fixtures.draft.order_date, description: fixtures.draft.description, discount_basis_points: 0 };
  const command = prepareMonetaryCommand(`${monetaryStockRoot}/orders`, body);
  body.unit_price_minor = "1";
  const fetcher = vi.fn().mockRejectedValueOnce(new TypeError("Lost reply")).mockResolvedValueOnce(new Response(JSON.stringify(fixtures.draft)));
  vi.stubGlobal("fetch", fetcher);
  await expect(executeMonetaryStockCommand(session, scope, command)).rejects.toThrow("Lost reply");
  expect((await executeMonetaryStockCommand(session, scope, command)).transaction_net_minor).toBe("1000");
  expect(fetcher.mock.calls[0][1].body).toBe(fetcher.mock.calls[1][1].body);
  expect(fetcher.mock.calls[1][1].headers).toMatchObject({ "X-ReconForge-CSRF": "csrf", "X-ReconForge-Legal-Entity": scope.legal_entity_id });
  const rate = { rate: "1.25", source: "Synthetic source", effective_at: "2026-10-15T12:00:00Z" }, taxes = [{ policy_id: "SYNTHETIC" }];
  const nested = prepareMonetaryCommand(`${monetaryStockRoot}/orders/source/invoice/prepare`, { original_rate: rate, taxes } as Record<string, ScopedJsonValue>);
  rate.rate = "9"; taxes[0].policy_id = "changed";
  expect(nested.body.original_rate).toEqual({ rate: "1.25", source: "Synthetic source", effective_at: "2026-10-15T12:00:00Z" });
  expect(nested.body.taxes).toEqual([{ policy_id: "SYNTHETIC" }]); expect(Object.isFrozen(nested.body.taxes)).toBe(true);
});

it("matches an exactly equivalent request quantity without rounding or rewriting its retained text", async () => {
  const source = fixtures.draft;
  const body = { number: source.number, customer_code: source.customer_code, customer_reference: source.customer_reference, item_code: source.item_code,
    warehouse_code: source.warehouse_code, location_code: source.location_code, quantity: "10.000", unit_price_minor: source.unit_price_minor,
    currency_code: source.transaction_policy.currency_code, order_date: source.order_date, description: source.description, discount_basis_points: source.discount_basis_points };
  const command = prepareMonetaryCommand(`${monetaryStockRoot}/orders`, body);
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(fixtures.draft))));
  expect((await executeMonetaryStockCommand(session, scope, command)).quantity_scaled).toBe("10");
  expect(command.body.quantity).toBe("10.000");
  await expect(executeMonetaryStockCommand(session, scope, prepareMonetaryCommand(`${monetaryStockRoot}/orders`, { ...body, quantity: "10.001" }))).rejects.toThrow();
});

it("refuses a mutation without CSRF proof before sending a network request", async () => {
  const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
  const command = prepareMonetaryCommand(`${monetaryPartialRoot}/plans`, {});
  await expect(monetaryRequest({ ...session, csrfToken: "" }, scope, command.path, command)).rejects.toThrow();
  expect(fetcher).not.toHaveBeenCalled();
});

it.each(["overcollection", "overentitlement", "zero-entitlement", "zero-refunded"])("refuses a coherent impossible public balance: %s", mutation => {
  const raw = { ...fixtures.balance, transaction_collected_minor: "1200", transaction_credited_minor: "600", transaction_outstanding_minor: "0", functional_outstanding_minor: "0",
    transaction_refund_entitlement_minor: "600", functional_refund_entitlement_minor: "750", transaction_refunded_minor: "0", functional_refund_released_minor: "0",
    transaction_refund_due_minor: "600", functional_refund_due_minor: "750" };
  if (mutation === "overcollection") Object.assign(raw, { transaction_collected_minor: "1201", transaction_credited_minor: "0", transaction_refund_entitlement_minor: "1", transaction_refund_due_minor: "1", functional_refund_entitlement_minor: "1", functional_refund_due_minor: "1" });
  if (mutation === "overentitlement") Object.assign(raw, { transaction_credited_minor: "1200", transaction_refund_entitlement_minor: "1200", transaction_refund_due_minor: "1200", functional_refund_entitlement_minor: "1501", functional_refund_due_minor: "1501" });
  if (mutation === "zero-entitlement") Object.assign(raw, { transaction_credited_minor: "0", transaction_refund_entitlement_minor: "0", transaction_refund_due_minor: "0", functional_refund_entitlement_minor: "1", functional_refund_released_minor: "1", functional_refund_due_minor: "0" });
  if (mutation === "zero-refunded") Object.assign(raw, { functional_refund_released_minor: "1", functional_refund_due_minor: "749" });
  expect(() => parseMonetaryPartialBalance(raw, scope, raw.source_order_id)).toThrow();
});

it("preserves valid collected-plus-credit above original gross and positive foreign amounts with zero functional legs", () => {
  const raw = { ...fixtures.balance, transaction_collected_minor: "1200", transaction_credited_minor: "600", transaction_outstanding_minor: "0", functional_outstanding_minor: "0",
    transaction_refund_entitlement_minor: "600", functional_refund_entitlement_minor: "750", transaction_refunded_minor: "100", functional_refund_released_minor: "125",
    transaction_refund_due_minor: "500", functional_refund_due_minor: "625" };
  expect(parseMonetaryPartialBalance(raw, scope, raw.source_order_id)).toEqual(raw);
  Object.assign(raw, { functional_refund_entitlement_minor: "0", functional_refund_released_minor: "0", functional_refund_due_minor: "0" });
  expect(parseMonetaryPartialBalance(raw, scope, raw.source_order_id)).toEqual(raw);
});

function collectionFixture(phase: 0 | 1 | 2) {
  const steps = [["prepare-collection", "CollectionPrepared", "maker"], ["review-collection", "CollectionReviewed", "checker"], ["collect", "Invoiced", "poster"]];
  return { ...structuredClone(fixtures.stock), row_version: 11 + phase, status: steps[phase][1],
    balance: { ...fixtures.stock.balance, active_plan_id: phase < 2 ? "collection-plan" : null, transaction_collected_minor: phase === 2 ? "200" : "0", transaction_outstanding_minor: phase === 2 ? "1000" : "1200", functional_outstanding_minor: phase === 2 ? "1250" : "1500" },
    collection: { id: "collection-plan", sequence: 1, status: ["Prepared", "Reviewed", "Posted"][phase], plan_digest: "d".repeat(64), amount_minor: "200", functional_cash_minor: "260", functional_receivable_released_minor: "250", functional_fx_gain_minor: "10", functional_fx_loss_minor: "0",
      settlement_rate: { rate: "1.3", source: "Synthetic settlement", effective_at: "2026-10-15T12:00:00Z" }, receipt_number: "FX1-SYNTHETIC-RECEIPT", receipt_date: "2026-10-15", period_id: "PERIOD", preparer_actor_id: "maker", reviewer_actor_id: phase > 0 ? "checker" : null, posted_actor_id: phase === 2 ? "poster" : null,
      entry_id: "collection-entry", posting_effect_id: phase === 2 ? "collection-effect" : null, receipt_id: phase === 2 ? "native-receipt" : null },
    events: [...fixtures.stock.events, ...steps.slice(0, phase + 1).map(([operation, status, actor_id], index) => ({ version: 11 + index, actor_id, operation, reason: "Synthetic collection", status, audit_event_id: `cash-audit-${index}` }))] };
}

it.each([0, 1, 2] as const)("binds current collection phase and presence to Stock event history: %s", phase => {
  const raw = collectionFixture(phase);
  expect(parseMonetaryStock(raw, scope).collection?.status).toBe(raw.collection.status);
  expect(() => parseMonetaryStock({ ...raw, collection: null }, scope)).toThrow();
  const different = { ...raw, balance: { ...raw.balance, active_plan_id: "collection-plan" }, collection: { ...raw.collection, status: phase ? "Prepared" : "Reviewed", reviewer_actor_id: phase ? null : "checker", posted_actor_id: null, posting_effect_id: null, receipt_id: null } };
  expect(() => parseMonetaryStock(different, scope)).toThrow();
});

it.each(["Return", "Refund", "ReverseReturn"] as const)("binds immutable preparation intent to the retained v3 request: %s", operation => {
  const original = structuredClone(operation === "Refund" ? fixtures.refund : fixtures.return);
  const raw = { ...original, operation, id: (operation === "Refund" ? "CRF3" : operation === "ReverseReturn" ? "CR3R" : "CR3") + "-" + "1".repeat(32),
    original_id: operation === "Return" ? null : fixtures.return.id, phase: 0, status: "Prepared", movement_id: null, reviewer_actor_id: null, posted_actor_id: null,
    entries: original.entries.map(entry => ({ ...entry, posting_effect_id: null, purpose: operation === "ReverseReturn" ? "Reverse" + entry.purpose : entry.purpose })) };
  const plan = parseMonetaryPartialPlan(raw, scope);
  const path = operation === "Return" ? `${monetaryPartialRoot}/plans` : `${monetaryPartialRoot}/plans/${raw.original_id}/${operation === "Refund" ? "refunds" : "reversals"}`;
  const command = prepareMonetaryCommand(path, { period_id: plan.period_id, posting_date: plan.posting_date, reason: plan.reason, expected_history_version: plan.expected_history_version,
    ...(operation === "Return" ? { source_order_id: plan.source_order_id, quantity_scaled: plan.quantity_scaled } : operation === "Refund" ? { amount_minor: plan.monetary.transaction_refund_minor } : {}) });
  expect(monetaryPartialMatchesCommand(plan, command)).toBe(true);
  for (const [key, value] of [["period_id", "different-period"], ["posting_date", "2026-10-16"], ["reason", "Different immutable preparation intent"]] as const) {
    expect(monetaryPartialMatchesCommand(parseMonetaryPartialPlan({ ...raw, [key]: value }, scope), command)).toBe(false);
  }
  expect(monetaryPartialMatchesCommand(parseMonetaryPartialPlan(fixtures.return, scope), prepareMonetaryCommand(`${monetaryPartialRoot}/plans/${fixtures.return.id}/post`, { expected_plan_digest: fixtures.return.plan_digest, reason: "A different posting audit reason" }))).toBe(true);
});

it.each(["invoice_number", "period_id", "cash_account_code", "country_code", "original_rate", "taxes", "event-reason"])("binds exposed invoice preparation evidence to the exact retained request: %s", mutation => {
  const raw = { ...structuredClone(fixtures.stock), status: "InvoicePrepared", row_version: 8, balance: null,
    events: fixtures.stock.events.slice(0, 8), monetary_origin: { ...structuredClone(fixtures.stock.monetary_origin), invoice_number: "FX1-SYNTHETIC-INVOICE", reviewer_actor_id: null, posted_actor_id: null, posting_effect_id: null } };
  const original = raw.monetary_origin;
  const { policy_digest: _digest, transaction_tax_minor: _foreign, functional_tax_minor: _functional, ...tax } = original.tax_components[0];
  const command = prepareMonetaryCommand(`${monetaryStockRoot}/orders/${raw.id}/invoice/prepare`, { invoice_number: "SYNTHETIC-INVOICE", expected_version: 7, reason: raw.events.at(-1)!.reason,
    invoice_date: original.invoice_date, due_date: original.due_date, journal_code: original.journal_code, period_id: original.period_id,
    receivable_account_code: original.receivable_account_code, revenue_account_code: original.revenue_account_code, cash_account_code: original.cash_account_code,
    refund_liability_account_code: original.refund_liability_account_code, gain_account_code: original.gain_account_code, loss_account_code: original.loss_account_code,
    country_code: original.country_code, transaction_class: original.transaction_class, original_rate: { ...original.original_rate }, taxes: [tax] });
  expect(monetaryStockMatchesCommand(parseMonetaryStock(raw, scope), command)).toBe(true);
  const different = structuredClone(raw);
  if (mutation === "original_rate") different.monetary_origin.original_rate.rate = "1.26";
  else if (mutation === "taxes") different.monetary_origin.tax_components[0].source = "Different declared provenance";
  else if (mutation === "event-reason") different.events[different.events.length - 1].reason = "Different event reason";
  else if (mutation === "country_code") { different.monetary_origin.country_code = "XY"; different.monetary_origin.tax_components[0].country_code = "XY"; }
  else different.monetary_origin[mutation as "invoice_number" | "period_id" | "cash_account_code"] = "OTHER";
  expect(monetaryStockMatchesCommand(parseMonetaryStock(different, scope), command)).toBe(false);
});

it.each(["amount_minor", "period_id", "receipt_number", "receipt_date", "settlement_rate", "event-reason"])("binds collection preparation to its retained F amount and literal intent: %s", mutation => {
  const raw = collectionFixture(0), current = raw.collection;
  const command = prepareMonetaryCommand(`${monetaryStockRoot}/orders/${raw.id}/collection/prepare`, { amount_minor: current.amount_minor, period_id: current.period_id, receipt_number: "SYNTHETIC-RECEIPT", receipt_date: current.receipt_date, settlement_rate: current.settlement_rate, expected_version: 10, reason: raw.events.at(-1)!.reason });
  expect(monetaryStockMatchesCommand(parseMonetaryStock(raw, scope), command)).toBe(true);
  const different = structuredClone(raw);
  if (mutation === "settlement_rate") different.collection.settlement_rate.source = "Different spot observation";
  else if (mutation === "event-reason") different.events[different.events.length - 1].reason = "Different audit reason";
  else if (mutation === "amount_minor") different.collection.amount_minor = "201";
  else if (mutation === "receipt_date") { different.collection.receipt_date = "2026-10-16"; different.collection.settlement_rate.effective_at = "2026-10-16T12:00:00Z"; }
  else different.collection[mutation as "period_id" | "receipt_number"] = "OTHER";
  expect(monetaryStockMatchesCommand(parseMonetaryStock(different, scope), command)).toBe(false);
});
