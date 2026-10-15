import { afterEach, expect, it, vi } from "vitest";
import fixtures from "./monetary-test-fixtures.json";
import { parseMonetaryPartialBalance, parseMonetaryPartialPlan } from "./monetary-partial-returns-data";
import { isMonetaryPartialPath, isMonetaryStockPath, monetaryPartialRoot, monetaryStockRoot } from "./monetary-paths";
import { monetaryDate, monetaryMoney, monetaryObject, monetaryRequest, parseMonetaryRate, prepareMonetaryCommand } from "./monetary-public-data";
import { executeMonetaryStockCommand, parseMonetaryStock } from "./monetary-stock-data";
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
  const body = { ...fixtures.draft, quantity: "10.000", currency_code: fixtures.draft.transaction_policy.currency_code };
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
