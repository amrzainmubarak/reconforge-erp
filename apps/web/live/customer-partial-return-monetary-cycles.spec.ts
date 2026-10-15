import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Locator, type Page } from "@playwright/test";
import { execFileSync } from "node:child_process";
import type { MonetaryPartialPlan } from "../src/monetary-partial-returns-data";
import type { MonetaryStock } from "../src/monetary-stock-data";
import { monetaryTranslate as text, type MonetaryWord } from "../src/monetary-words";

const base = process.env.RECONFORGE_ERP_LIVE_URL, tenant = process.env.RECONFORGE_ERP_TENANT, password = process.env.RECONFORGE_ERP_PASSWORD;
const selected = process.env.RECONFORGE_MONETARY_CASE, foreign = selected === "foreign";
const stockRoot = "/api/v2/stock-sales", returnRoot = "/api/v3/customer-partial-returns", day = "2026-10-15";
const rate = (value: string) => ({ rate: value, source: "Synthetic witnessed monetary spot", effective_at: day + "T12:00:00Z" });
let source = "", capture = 0;

async function login(page: Page, person: "maker" | "checker" | "poster") {
  await page.goto(`${base}/admin-audit`);
  for (const [label, value] of [["Tenant ID", tenant!], ["Username", "browser-" + person], ["Password", password!]]) await page.getByLabel(label, { exact: true }).fill(value);
  await page.getByRole("button", { name: "Sign in to administration", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Confirm privileged access", exact: true })).toBeVisible();
  await page.getByLabel("Password", { exact: true }).fill(password!);
  const elevated = page.waitForResponse(value => value.url().endsWith("/auth/step-up"));
  await page.getByRole("button", { name: "Confirm and continue", exact: true }).click(); expect((await elevated).status()).toBe(200);
}
async function fields(form: Locator, values: Partial<Record<MonetaryWord, string>>) {
  for (const [key, value] of Object.entries(values)) {
    const input = form.getByLabel(text("en", key as MonetaryWord), { exact: true });
    if (await input.evaluate(node => node.tagName === "SELECT")) await input.selectOption(value!);
    else await input.fill(value!);
  }
}
async function stockPage(page: Page, id?: string) {
  await page.getByRole("navigation", { name: "Primary navigation", exact: true }).getByRole("button", { name: "Product sales", exact: true }).click();
  const scope = page.getByRole("group", { name: "Working scope", exact: true });
  for (const [label, value] of [["Workspace", "work"], ["Organization", "org"], ["Legal entity", "entity"]]) await scope.getByLabel(label, { exact: true }).selectOption(value);
  const initial = page.waitForResponse(reply => new URL(reply.url()).pathname === "/api/v1/stock-sales/orders" && reply.request().method() === "GET");
  await scope.getByRole("button", { name: "Load selected scope", exact: true }).click(); expect((await initial).status()).toBe(200);
  const loaded = page.waitForResponse(reply => new URL(reply.url()).pathname === `${stockRoot}/orders` && reply.request().method() === "GET");
  await page.getByRole("button", { name: text("en", "openStock"), exact: true }).click(); expect((await loaded).status()).toBe(200);
  const section = page.getByRole("region", { name: text("en", "stockTitle"), exact: true });
  await expect(section.getByText(text("en", "loading"), { exact: true })).toHaveCount(0);
  if (id) {
    const response = page.waitForResponse(reply => new URL(reply.url()).pathname === `${stockRoot}/orders/${id}` && reply.request().method() === "GET");
    await section.getByLabel(text("en", "selectStock"), { exact: true }).selectOption(id); expect((await response).status()).toBe(200);
    await expect(section.getByText(text("en", "loading"), { exact: true })).toHaveCount(0);
  }
  return section;
}
async function partialPage(page: Page, plan?: MonetaryPartialPlan) {
  await page.getByRole("navigation", { name: "Primary navigation", exact: true }).getByRole("button", { name: "Customer returns", exact: true }).click();
  const scope = page.getByRole("form", { name: "Apply scope", exact: true });
  for (const [label, value] of [["Workspace ID", "work"], ["Organization ID", "org"], ["Legal entity ID", "entity"]]) await scope.getByLabel(label, { exact: true }).fill(value);
  const initial = page.waitForResponse(reply => new URL(reply.url()).pathname === "/api/v1/customer-returns/plans" && reply.request().method() === "GET");
  await scope.getByRole("button", { name: "Apply scope", exact: true }).click(); expect((await initial).status()).toBe(200);
  const loaded = page.waitForResponse(reply => new URL(reply.url()).pathname === `${returnRoot}/plans` && reply.request().method() === "GET");
  await page.getByRole("button", { name: text("en", "partialTitle"), exact: true }).click(); expect((await loaded).status()).toBe(200);
  const section = page.getByRole("region", { name: text("en", "partialTitle"), exact: true });
  if (plan) {
    const form = section.getByRole("form", { name: text("en", "loadPlan"), exact: true });
    await form.getByLabel(text("en", "planId"), { exact: true }).fill(plan.id);
    const exact = page.waitForResponse(reply => new URL(reply.url()).pathname === `${returnRoot}/plans/${plan.id}` && reply.request().method() === "GET");
    await form.getByRole("button", { name: text("en", "loadPlan"), exact: true }).click(); expect((await exact).status()).toBe(200);
    await expect(section.getByRole("heading", { name: text("en", "currentBalance"), exact: true })).toBeVisible();
  }
  return section;
}
async function stockCommand(page: Page, path: string, action: () => Promise<void>, status = 200): Promise<MonetaryStock> {
  const response = page.waitForResponse(reply => new URL(reply.url()).pathname === path && reply.request().method() === "POST");
  await action(); const reply = await response; expect(reply.status()).toBe(status);
  const result = await reply.json() as MonetaryStock; expect(result.schema_version).toBe("stock-sales-monetary-v2"); return result;
}
function observe(kind?: "RetainedReplay" | "ScopeRefusal", plan?: MonetaryPartialPlan, refusal?: { status: number; code: string }) {
  const python = process.env.RECONFORGE_MONETARY_PYTHON, runtime = process.env.RECONFORGE_MONETARY_RUNTIME_ROOT;
  expect(Boolean(python && runtime && process.env.RECONFORGE_MONETARY_CUSTODY_ROOT), "Owned private ordinary-role monetary observer is required.").toBe(true);
  execFileSync(python!, ["-m", "tests.customer_partial_return_monetary_browser", "capture"], { cwd: runtime!, stdio: "pipe", timeout: 30_000, maxBuffer: 16_384,
    env: { ...process.env, RECONFORGE_MONETARY_STOCK_SOURCE: source, RECONFORGE_MONETARY_CAPTURE: String(capture), RECONFORGE_MONETARY_OBSERVATION: kind,
      RECONFORGE_MONETARY_POSTED_PLAN: kind === "RetainedReplay" ? plan!.id : undefined, RECONFORGE_MONETARY_POSTED_DIGEST: kind === "RetainedReplay" ? plan!.plan_digest : undefined,
      RECONFORGE_MONETARY_REFUSAL_STATUS: refusal ? String(refusal.status) : undefined, RECONFORGE_MONETARY_REFUSAL_CODE: refusal?.code } });
}
async function partialCommand(page: Page, path: string, action: () => Promise<void>, lose = false): Promise<MonetaryPartialPlan> {
  if (!lose) {
    const response = page.waitForResponse(reply => new URL(reply.url()).pathname === path && reply.request().method() === "POST");
    await action(); const reply = await response; expect(reply.status()).toBe(200); return (await reply.json()).plan as MonetaryPartialPlan;
  }
  let originalBody = "", committed: MonetaryPartialPlan | undefined, status = 0, finish!: () => void;
  const done = new Promise<void>(resolve => { finish = resolve; });
  await page.route(`**${path}`, async route => {
    originalBody = route.request().postData() ?? "";
    try { const reply = await route.fetch(); status = reply.status(); if (status === 200) committed = (await reply.json()).plan as MonetaryPartialPlan; await route.abort("failed"); }
    finally { finish(); }
  }, { times: 1 });
  await action(); await done; expect(status).toBe(200); expect(Boolean(committed)).toBe(true);
  observe();
  const retry = page.getByRole("button", { name: text("en", "retry"), exact: true }); await expect(retry).toBeVisible();
  await expect(page.getByRole("button", { name: "Apply scope", exact: true })).toBeDisabled();
  await expect(page.getByRole("button", { name: text("en", "partialTitle"), exact: true })).toBeDisabled();
  const response = page.waitForResponse(reply => new URL(reply.url()).pathname === path && reply.request().method() === "POST");
  await retry.click(); const reply = await response; expect(reply.status()).toBe(200); expect(reply.request().postData()).toBe(originalBody);
  const retained = (await reply.json()).plan as MonetaryPartialPlan; expect(retained).toEqual(committed); observe("RetainedReplay", retained); return retained;
}
async function stockPhase(page: Page, order: MonetaryStock, person: "maker" | "checker" | "poster", path: string, label: MonetaryWord, values: Partial<Record<MonetaryWord, string>> = {}) {
  await login(page, person); const section = await stockPage(page, order.id), form = section.getByRole("form", { name: text("en", label), exact: true });
  await fields(form, { reason: "Actual original monetary " + path, ...values });
  return stockCommand(page, `${stockRoot}/orders/${order.id}/${path}`, () => form.getByRole("button", { name: text("en", label), exact: true }).click());
}
async function prepareReturn(page: Page, quantity: string) {
  await login(page, "maker"); const section = await partialPage(page);
  const sourceForm = section.getByRole("form", { name: text("en", "sourceLoad"), exact: true });
  await fields(sourceForm, { source_order_id: source });
  const balance = page.waitForResponse(reply => new URL(reply.url()).pathname === `${returnRoot}/sources/${source}/balance` && reply.request().method() === "GET");
  await sourceForm.getByRole("button", { name: text("en", "sourceLoad"), exact: true }).click(); expect((await balance).status()).toBe(200);
  const form = section.getByRole("form", { name: text("en", "prepareReturn"), exact: true });
  await fields(form, { quantity_scaled: quantity, period_id: "period", posting_date: day, reason: "Actual remaining original tax and cost" });
  return partialCommand(page, `${returnRoot}/plans`, () => form.getByRole("button", { name: text("en", "prepareReturn"), exact: true }).click());
}
async function partialPhase(page: Page, plan: MonetaryPartialPlan, action: "review" | "post" | "cancel", lose = false) {
  await login(page, action === "review" ? "checker" : "poster"); const section = await partialPage(page, plan);
  const form = section.getByRole("form", { name: text("en", plan.phase === 0 ? "review" : "post"), exact: true });
  await fields(form, { reason: "Independent actual monetary " + action });
  return partialCommand(page, `${returnRoot}/plans/${plan.id}/${action}`, () => form.getByRole("button", { name: text("en", action), exact: true }).click(), lose);
}
async function publish(page: Page, plan: MonetaryPartialPlan, lose = false) {
  const reviewed = await partialPhase(page, plan, "review"); const posted = await partialPhase(page, reviewed, "post", lose);
  expect(posted.phase).toBe(2); expect(new Set([posted.preparer_actor_id, posted.reviewer_actor_id, posted.posted_actor_id]).size).toBe(3);
  if (!lose) observe();
  return posted;
}
async function child(page: Page, plan: MonetaryPartialPlan, kind: "refund" | "reverse", amount?: string, spot?: string) {
  await login(page, "maker"); const section = await partialPage(page, plan), label = kind === "refund" ? "prepareRefund" : "prepareReverse";
  const form = section.getByRole("form", { name: text("en", label), exact: true });
  await fields(form, { period_id: "period", posting_date: day, reason: "Actual captured monetary correction", ...(amount ? { amount_minor: amount } : {}) });
  if (foreign && kind === "refund") await fields(form, { rate: spot!, rateSource: rate(spot!).source, effective_at: rate(spot!).effective_at });
  return partialCommand(page, `${returnRoot}/plans/${plan.id}/${kind === "refund" ? "refunds" : "reversals"}`, () => form.getByRole("button", { name: text("en", label), exact: true }).click());
}
async function readAging(page: Page, plan: MonetaryPartialPlan) {
  await page.getByRole("navigation", { name: "Primary navigation", exact: true }).getByRole("button", { name: "Receivables", exact: true }).click();
  const listed = page.waitForResponse(reply => new URL(reply.url()).pathname === "/api/v1/receivables/invoices" && reply.request().method() === "GET");
  await page.getByRole("combobox", { name: "Authorized workspace", exact: true }).selectOption("work");
  const result = await listed; expect(result.status()).toBe(200);
  const record = (await result.json()).invoices.find((value: { id: string }) => value.id === plan.invoice_id);
  expect(record && String(record.outstanding_minor)).toBe("560"); expect(String(record.total_minor)).toBe("11400"); expect(record.currency_code).toBe(foreign ? "EUR" : "USD");
  await page.getByRole("button", { name: `Review ${record.invoice_number}`, exact: true }).click();
  const cash = page.getByRole("region", { name: "Cash receipts and allocations", exact: true });
  await expect(cash.getByText("Current customer receivable exposure:", { exact: false })).toContainText(`560 ${foreign ? "EUR" : "USD"}`);
  const form = cash.getByRole("form", { name: "Read current receivables aging", exact: true });
  await form.getByLabel("Aging as-of date", { exact: true }).fill(day);
  const response = page.waitForResponse(reply => new URL(reply.url()).pathname === "/api/v1/receivables/aging-by-currency" && reply.request().method() === "GET");
  await form.getByRole("button", { name: "Read current receivables aging", exact: true }).click(); const aging = await response; expect(aging.status()).toBe(200);
  const group = (await aging.json()).currency_groups.find((value: { currency_code: string }) => value.currency_code === (foreign ? "EUR" : "USD"));
  expect(group.items.find((value: { invoice_id: string }) => value.invoice_id === plan.invoice_id).outstanding_minor).toBe(560);
  await expect(cash.getByRole("region", { name: "Authorized receivables aging result", exact: true })).toContainText(`560 ${foreign ? "EUR" : "USD"}`);
  await page.goto("about:blank"); // All AR reads unmount before the next economic capture.
}

test("actual monetary Stock v2 and CR3 identity or foreign tax cycle", async ({ page }) => {
  test.setTimeout(600_000);
  expect(Boolean(base && tenant && password && ["identity", "foreign"].includes(selected ?? "")), "Owned native149 HTTPS fixture and fixed case are required.").toBe(true);
  let pageErrors = 0; page.on("pageerror", () => { ++pageErrors; });
  await login(page, "maker"); const section = await stockPage(page), create = section.getByRole("form", { name: text("en", "create"), exact: true });
  await fields(create, { number: "MONETARY-" + selected!.toUpperCase(), customer_code: foreign ? "FOREIGN" : "CUSTOMER", customer_reference: "MONETARY-PO", item_code: "ITEM", warehouse_code: "MAIN", location_code: "STOCK", quantity: "10", unit_price_minor: "1000", discount_basis_points: "0", description: "Synthetic original taxed merchandise", order_date: day });
  let order = await stockCommand(page, `${stockRoot}/orders`, () => create.getByRole("button", { name: text("en", "create"), exact: true }).click(), 201);
  source = order.id; capture = 0; observe();
  for (const [person, path, label] of [["maker", "submit", "submit"], ["checker", "approve", "approve"], ["maker", "reserve", "reserve"]] as const) order = await stockPhase(page, order, person, path, label);
  order = await stockPhase(page, order, "maker", "issue/prepare", "prepareIssue", { posting_date: day, period_id: "period", policy_code: "FIFO" });
  order = await stockPhase(page, order, "checker", "issue/review", "reviewIssue"); order = await stockPhase(page, order, "poster", "deliver", "deliver");
  expect(order.functional_cogs_minor).toBe("12000"); capture = 1; observe();
  await login(page, "maker"); const invoiceSection = await stockPage(page, source), invoice = invoiceSection.getByRole("form", { name: text("en", "prepareInvoice"), exact: true });
  await fields(invoice, { reason: "Actual original tax and captured FX", invoice_number: "MONETARY-INVOICE", invoice_date: day, due_date: "2026-10-31", period_id: "period", journal_code: "SALES", receivable_account_code: "AR", revenue_account_code: "REVENUE", cash_account_code: "CASH", refund_liability_account_code: "REFUND", gain_account_code: "GAIN", loss_account_code: "LOSS", country_code: "ZZ", transaction_class: "synthetic-merchandise" });
  if (foreign) await fields(invoice, { rate: "1.25", rateSource: rate("1.25").source, effective_at: rate("1.25").effective_at });
  await invoice.getByRole("button", { name: text("en", "addTax"), exact: true }).click();
  const tax = invoice.getByRole("group", { name: "Tax 1", exact: true });
  await fields(tax, { policy_id: "SYNTHETIC-VAT", version: "1", effective_from: "2026-01-01", effective_to: "2026-12-31", taxRate: "0.14", taxSource: "Synthetic reviewed tax fraction", account_code: "TAX" });
  order = await stockCommand(page, `${stockRoot}/orders/${source}/invoice/prepare`, () => invoice.getByRole("button", { name: text("en", "prepareInvoice"), exact: true }).click());
  expect(order.monetary_origin?.transaction_gross_minor).toBe("11400"); expect(order.monetary_origin?.functional_gross_minor).toBe(foreign ? "14250" : "11400");
  order = await stockPhase(page, order, "checker", "invoice/review", "reviewInvoice"); order = await stockPhase(page, order, "poster", "invoice/post", "postInvoice"); capture = 2; observe();
  order = await stockPhase(page, order, "maker", "collection/prepare", "prepareCollection", { receipt_number: "MONETARY-CASH", receipt_date: day, period_id: "period", amount_minor: "4000", ...(foreign ? { rate: "1.3", rateSource: rate("1.3").source, effective_at: rate("1.3").effective_at } : {}) });
  order = await stockPhase(page, order, "checker", "collection/review", "reviewCollection"); order = await stockPhase(page, order, "poster", "collection/post", "postCollection"); capture = 3; observe();
  expect(order.collection?.functional_fx_gain_minor).toBe(foreign ? "200" : "0");
  const unposted = await prepareReturn(page, "1"), reviewed = await partialPhase(page, unposted, "review"); const cancelled = await partialPhase(page, reviewed, "cancel"); expect(cancelled.phase).toBe(3);
  capture = 4; const first = await publish(page, await prepareReturn(page, "6"));
  expect([first.monetary.transaction_credit_minor, first.monetary.functional_cost_minor]).toEqual(["6840", "7200"]);
  await readAging(page, first);
  capture = 5; const parent = await publish(page, await prepareReturn(page, "4"));
  expect([parent.monetary.transaction_credit_minor, parent.monetary.transaction_refund_delta_minor, parent.monetary.functional_refund_delta_minor]).toEqual(["4560", "4000", foreign ? "5000" : "4000"]);
  capture = 6; await publish(page, await child(page, parent, "refund", "1500", "1.2"));
  capture = 7; const refund = await publish(page, await child(page, parent, "refund", "2500", "1.3"), true);
  capture = 8; await publish(page, await child(page, refund, "reverse"));
  capture = 9; const final = await publish(page, await child(page, parent, "refund", "2500", "1.3"));
  await login(page, "poster"); const finalSection = await partialPage(page, final);
  const residual = finalSection.getByRole("region", { name: text("en", "currentBalance"), exact: true });
  await expect(residual).toContainText(`0.00 ${foreign ? "EUR" : "USD"}`); await expect(residual).toContainText("0.00 USD");
  const refused = await page.request.get(`${base}${returnRoot}/sources/${source}/balance`, { headers: { "X-ReconForge-Tenant": tenant!, "X-ReconForge-Workspace": "work", "X-ReconForge-Organization": "org", "X-ReconForge-Legal-Entity": "ungranted-entity" } });
  expect(refused.status()).toBe(403); const refusedBody = await refused.json(); expect(refusedBody.error.code).toMatch(/^[a-z][a-z0-9_]{0,119}$/);
  observe("ScopeRefusal", undefined, { status: refused.status(), code: refusedBody.error.code });
  for (const locale of ["en", "ar"] as const) {
    if (locale === "ar") await page.getByRole("button", { name: "Switch language", exact: true }).click();
    await expect(page.locator("main#main-content")).toHaveAttribute("dir", locale === "ar" ? "rtl" : "ltr");
    await expect(page.getByRole("heading", { name: text(locale, "partialTitle"), exact: true })).toBeVisible();
    for (const width of [320, 768, 1024, 1440]) {
      await page.setViewportSize({ width, height: 900 });
      expect(await page.evaluate(() => Math.max(0, document.documentElement.scrollWidth - document.documentElement.clientWidth))).toBe(0);
      expect((await new AxeBuilder({ page }).analyze()).violations.map(value => value.id)).toEqual([]);
    }
  }
  expect(pageErrors).toBe(0);
});
