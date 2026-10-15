import { expect, test, type Page, type Locator } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { execFileSync } from "node:child_process";
import type { PartialReturnPlanV2 } from "../src/customer-partial-returns-data";

const base = process.env.RECONFORGE_ERP_LIVE_URL, tenant = process.env.RECONFORGE_ERP_TENANT;
const password = process.env.RECONFORGE_ERP_PASSWORD, source = process.env.RECONFORGE_CUSTOMER_PARTIAL_RETURN_SOURCE;
const selectedCase = process.env.RECONFORGE_PARTIAL_REMAINDER_CASE;
const root = "/api/v2/customer-partial-returns", period = "period", postingDate = "2026-10-15";
async function login(page: Page, username: string) {
  await page.goto(`${base}/admin-audit`);
  await page.getByLabel("Tenant ID", { exact: true }).fill(tenant!);
  await page.getByLabel("Username", { exact: true }).fill(username);
  await page.getByLabel("Password", { exact: true }).fill(password!);
  await page.getByRole("button", { name: "Sign in to administration", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Confirm privileged access", exact: true })).toBeVisible();
  await page.getByLabel("Password", { exact: true }).fill(password!);
  const response = page.waitForResponse(reply => reply.url().endsWith("/auth/step-up"));
  await page.getByRole("button", { name: "Confirm and continue", exact: true }).click(); expect((await response).status()).toBe(200);
}
async function enter(page: Page, id?: string) {
  await page.getByRole("navigation", { name: "Primary navigation" }).getByRole("button", { name: "Customer returns", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Original customer returns and partial refunds", exact: true })).toBeVisible();
  const scope = page.getByRole("form", { name: "Apply scope", exact: true });
  for (const [label, value] of Object.entries({ "Workspace ID": "work", "Organization ID": "org", "Legal entity ID": "entity" })) { const field = scope.getByLabel(label, { exact: true }); await expect(field).toBeEnabled(); await field.fill(value); }
  const original = page.waitForResponse(reply => reply.url().endsWith("/customer-returns/plans") && reply.request().method() === "GET");
  await scope.getByRole("button", { name: "Apply scope", exact: true }).click(); expect((await original).status()).toBe(200);
  const loaded = page.waitForResponse(reply => reply.url().endsWith(`${root}/plans`) && reply.request().method() === "GET");
  await page.getByRole("button", { name: "Partial return with remainder allocation", exact: true }).click(); expect((await loaded).status()).toBe(200);
  await expect(page.getByRole("heading", { name: "Partial customer return with retained remainders", exact: true })).toBeVisible();
  if (id) {
    const lookup = page.getByRole("form", { name: "Load exact retained partial plan", exact: true });
    await lookup.getByLabel("Partial cycle plan ID", { exact: true }).fill(id);
    const exact = page.waitForResponse(reply => reply.url().endsWith(`${root}/plans/${id}`) && reply.request().method() === "GET");
    await lookup.getByRole("button", { name: "Load exact retained partial plan", exact: true }).click(); expect((await exact).status()).toBe(200);
    await expect(page.getByRole("region", { name: "Partial cycle source and posting evidence", exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Native invoice and refund balance", exact: true })).toBeVisible();
  }
}
async function fill(form: Locator, fields: Record<string, string>) {
  for (const [label, value] of Object.entries(fields)) await form.getByLabel(label, { exact: true }).fill(value);
}
async function command(page: Page, path: string, trigger: () => Promise<void>, lose = false): Promise<PartialReturnPlanV2> {
  if (!lose) {
    const response = page.waitForResponse(reply => reply.url().endsWith(path) && reply.request().method() === "POST");
    await trigger(); const reply = await response; expect(reply.status()).toBe(200); return (await reply.json()).plan as PartialReturnPlanV2;
  }
  let originalBody = "", committed: PartialReturnPlanV2 | null = null, status = 0, finish!: () => void;
  const done = new Promise<void>(resolve => { finish = resolve; });
  // This is a real database command; only its already committed response is lost.
  await page.route(`**${path}`, async route => {
    originalBody = route.request().postData() ?? "";
    try { const reply = await route.fetch(); status = reply.status(); if (status === 200) committed = (await reply.json()).plan as PartialReturnPlanV2; await route.abort("failed"); }
    finally { finish(); }
  }, { times: 1 });
  await trigger(); await done; expect(status).toBe(200); expect(Boolean(committed)).toBe(true);
  // Retain the actual committed state before the human retry; post() observes
  // the retained ACK again and must deduplicate this same native history row.
  if (path.endsWith("/post")) captureCommitted(committed!);
  const retry = page.getByRole("button", { name: "Retry retained partial command", exact: true }); await expect(retry).toBeVisible();
  for (const name of ["Whole original tranche", "Partial return cycle", "Partial return with remainder allocation", "Apply scope", "Sign out"]) await expect(page.getByRole("button", { name, exact: true })).toBeDisabled();
  const response = page.waitForResponse(reply => reply.url().endsWith(path) && reply.request().method() === "POST");
  await retry.click(); const reply = await response; expect(reply.status()).toBe(200);
  expect(reply.request().postData() === originalBody).toBe(true);
  const retained = (await reply.json()).plan as PartialReturnPlanV2;
  expect(JSON.stringify(retained) === JSON.stringify(committed)).toBe(true); return retained;
}
async function prepareReturn(page: Page, quantity: string, lose = false) {
  await login(page, "browser-maker"); await enter(page);
  const inspect = page.getByRole("form", { name: "Load original source balance", exact: true });
  await inspect.getByLabel("Partial return original stock order ID", { exact: true }).fill(source!);
  const balance = page.waitForResponse(reply => reply.url().endsWith(`${root}/sources/${source}/balance`) && reply.request().method() === "GET");
  await inspect.getByRole("button", { name: "Load original source balance", exact: true }).click(); expect((await balance).status()).toBe(200);
  const form = page.getByRole("form", { name: "Prepare partial original return", exact: true });
  await fill(form, { "Return quantity in captured scaled units": quantity, "Partial cycle fiscal period ID": period, "Partial cycle posting date": postingDate,
    "Refund cash journal code": "CASH", "Partial refund liability account": "REFUND", "Captured collection cash account": "CASH", "Partial cycle reason": "Actual original FIFO portion" });
  return command(page, `${root}/plans`, () => form.getByRole("button", { name: "Prepare partial original return", exact: true }).click(), lose);
}
async function phase(page: Page, id: string, action: "review" | "post" | "cancel", lose = false) {
  await login(page, action === "review" ? "browser-checker" : "browser-poster"); await enter(page, id);
  const next = page.getByRole("form", { name: action === "review" ? "Review partial cycle plan" : "Post partial cycle plan", exact: true });
  const form = action === "cancel" ? page.getByRole("form", { name: "Post partial cycle plan", exact: true }) : next;
  await fill(form, { "Partial cycle reason": `Actual independent ${action}` });
  const name = action === "cancel" ? "Cancel unposted partial plan" : action === "review" ? "Review partial cycle plan" : "Post partial cycle plan";
  const result = await command(page, `${root}/plans/${id}/${action}`, () => form.getByRole("button", { name, exact: true }).click(), lose);
  expect(result.phase).toBe(action === "review" ? 1 : action === "post" ? 2 : 3); return result;
}
function captureCommitted(plan: PartialReturnPlanV2): void {
  const python = process.env.RECONFORGE_PARTIAL_PYTHON, runtime = process.env.RECONFORGE_PARTIAL_RUNTIME_ROOT;
  expect(Boolean(python && runtime && process.env.RECONFORGE_PARTIAL_REMAINDER_CUSTODY_ROOT), "Owned private native committed-row observer is required.").toBe(true);
  execFileSync(python!, ["-m", "tests.customer_partial_return_remainder_browser", "capture"], { cwd: runtime!,
    env: { ...process.env, RECONFORGE_PARTIAL_POSTED_PLAN: plan.id, RECONFORGE_PARTIAL_POSTED_DIGEST: plan.plan_digest },
    stdio: "pipe", maxBuffer: 16_384, timeout: 30_000 });
}
async function post(page: Page, plan: PartialReturnPlanV2, lose = false) {
  await phase(page, plan.id, "review"); const posted = await phase(page, plan.id, "post", lose);
  // Observe committed SQL through a separate normal-role lease, never a proof API.
  captureCommitted(posted); return posted;
}
async function prepareFromPosted(page: Page, parent: PartialReturnPlanV2, operation: "refund" | "reverse", amount?: string) {
  await login(page, "browser-maker"); await enter(page, parent.id);
  const name = operation === "refund" ? "Prepare governed refund" : "Prepare governed reversal";
  const form = page.getByRole("form", { name, exact: true });
  await fill(form, { "Partial cycle fiscal period ID": period, "Partial cycle posting date": postingDate, "Partial cycle reason": "Actual governed original source correction",
    ...(amount ? { "Refund amount in exact minor units": amount } : {}) });
  return command(page, `${root}/plans/${parent.id}/${operation === "refund" ? "refunds" : "reversals"}`, () => form.getByRole("button", { name, exact: true }).click());
}
async function readCreditAdjustedAging(page: Page, plan: PartialReturnPlanV2, expected: number) {
  // The retained replay observation is already sealed. These read-only audit
  // appends belong to the NEXT economic capture, before its real posting.
  await page.getByRole("navigation", { name: "Primary navigation" }).getByRole("button", { name: "Receivables", exact: true }).click();
  const listed = page.waitForResponse(reply => new URL(reply.url()).pathname === "/api/v1/receivables/invoices" && reply.request().method() === "GET");
  await page.getByRole("combobox", { name: "Authorized workspace", exact: true }).selectOption("work");
  const response = await listed; expect(response.status()).toBe(200);
  const records = await response.json(); const original = records.invoices.find((record: { id: string }) => record.id === plan.invoice_id);
  expect(Boolean(original)).toBe(true);
  await page.getByRole("button", { name: `Review ${original.invoice_number}`, exact: true }).click();
  const cash = page.getByRole("region", { name: "Cash receipts and allocations", exact: true });
  await expect(cash.getByText("Current customer receivable exposure:", { exact: false })).toContainText(`${new Intl.NumberFormat("en").format(expected)} USD`);
  const form = cash.getByRole("form", { name: "Read current receivables aging", exact: true });
  await form.getByLabel("Aging as-of date", { exact: true }).fill(postingDate);
  const loaded = page.waitForResponse(reply => new URL(reply.url()).pathname === "/api/v1/receivables/aging-by-currency" && reply.request().method() === "GET");
  await form.getByRole("button", { name: "Read current receivables aging", exact: true }).click(); expect((await loaded).status()).toBe(200);
  const result = cash.getByRole("region", { name: "Authorized receivables aging result", exact: true }); await expect(result).toBeVisible();
  if (expected) await expect(result.getByText("Open receivables total:", { exact: false })).toContainText(`${expected} USD`);
  else await expect(result.getByText("No approved open invoices were returned in this workspace.", { exact: true })).toBeVisible();
  for (const locale of ["en", "ar"] as const) {
    if (locale === "ar") await page.getByRole("button", { name: "Switch language", exact: true }).click();
    await expect(page.locator("main#main-content")).toHaveAttribute("dir", locale === "ar" ? "rtl" : "ltr");
    await expect(page.getByRole("heading", { name: locale === "ar" ? "أعمار الذمم المدينة في مساحة العمل" : "Workspace receivables aging", exact: true })).toBeVisible();
    for (const width of [320, 768, 1024, 1440]) {
      await page.setViewportSize({ width, height: 900 });
      expect(await page.evaluate(() => Math.max(0, document.documentElement.scrollWidth - document.documentElement.clientWidth))).toBe(0);
      expect((await new AxeBuilder({ page }).analyze()).violations.map(value => value.id)).toEqual([]);
    }
  }
  await page.getByRole("button", { name: "Switch language", exact: true }).click();
  await expect(page.locator("main#main-content")).toHaveAttribute("dir", "ltr");
  // Establish an unmount barrier before any next economic command/capture.
  // This prevents a still-mounted AR reader from appending later policy audit.
  await page.goto("about:blank");
}
test("actual governed v2 remainder and zero-leg customer return cycle", async ({ page }) => {
  test.setTimeout(360_000);
  expect(Boolean(base && tenant && password && source && ["ordinary", "zero", "refund"].includes(selectedCase ?? "")), "Owned migrated native148 HTTPS fixture and fixed case are required.").toBe(true);
  let errors = 0; page.on("pageerror", () => { ++errors; });
  const economic: PartialReturnPlanV2[] = [];
  async function publish(plan: PartialReturnPlanV2, lose = false) {
    const value = await post(page, plan, lose);
    expect(value.schema_version).toBe("customer-partial-return-v2");
    expect(value.allocation_policy).toBe("remaining-original-v1");
    expect(new Set([value.preparer_actor_id, value.reviewer_actor_id, value.poster_actor_id]).size).toBe(3);
    economic.push(value); return value;
  }
  if (selectedCase === "ordinary") {
    for (const [index, cost] of ["334", "334", "333"].entries()) {
      const prepared = await prepareReturn(page, "1");
      expect([prepared.credit_minor, prepared.cogs_restored_minor]).toEqual(["1000", cost]);
      expect(prepared.entries.map(entry => entry.purpose)).toEqual(["RevenueCredit", "CostRestoration"]);
      const posted = await publish(prepared, index === 0);
      if (index === 0) await readCreditAdjustedAging(page, posted, 2000);
    }
  } else if (selectedCase === "zero") {
    const cancelled = await prepareReturn(page, "1"); expect(cancelled.entries).toEqual([]);
    await phase(page, cancelled.id, "review"); const cancellation = await phase(page, cancelled.id, "cancel");
    expect(cancellation.entries).toEqual([]);
    const first = await publish(await prepareReturn(page, "1"), true);
    expect([first.credit_minor, first.cogs_restored_minor, first.entries.length]).toEqual(["0", "0", 0]);
    const inverse = await publish(await prepareFromPosted(page, first, "reverse"));
    expect(inverse.entries).toEqual([]);
    const again = await publish(await prepareReturn(page, "1")); expect(again.entries).toEqual([]);
    const revenue = await publish(await prepareReturn(page, "1"));
    expect([revenue.credit_minor, revenue.cogs_restored_minor]).toEqual(["1", "0"]);
    expect(revenue.entries.map(entry => entry.purpose)).toEqual(["RevenueCredit"]);
    const cost = await publish(await prepareReturn(page, "1"));
    expect([cost.credit_minor, cost.cogs_restored_minor]).toEqual(["0", "1"]);
    expect(cost.entries.map(entry => entry.purpose)).toEqual(["CostRestoration"]);
    const reverseCost = await publish(await prepareFromPosted(page, cost, "reverse"));
    expect(reverseCost.entries.map(entry => entry.purpose)).toEqual(["ReverseCostRestoration"]);
    const final = await publish(await prepareReturn(page, "1"));
    expect(final.entries.map(entry => entry.purpose)).toEqual(["CostRestoration"]);
  } else {
    const first = await prepareReturn(page, "8");
    expect([first.credit_minor, first.cogs_restored_minor, first.receivable_released_minor, first.refund_entitlement_delta_minor]).toEqual(["36000", "9600", "35000", "1000"]);
    await publish(first);
    const last = await prepareReturn(page, "2");
    expect([last.credit_minor, last.cogs_restored_minor, last.receivable_released_minor, last.refund_entitlement_delta_minor]).toEqual(["9000", "2400", "0", "9000"]);
    const parent = await publish(last);
    await publish(await prepareFromPosted(page, parent, "refund", "3000"));
    const refund = await publish(await prepareFromPosted(page, parent, "refund", "7000"), true);
    await readCreditAdjustedAging(page, refund, 0);
    await publish(await prepareFromPosted(page, refund, "reverse"));
    await publish(await prepareFromPosted(page, parent, "refund", "7000"));
  }
  expect(economic).toHaveLength(selectedCase === "ordinary" ? 3 : selectedCase === "zero" ? 7 : 6);
  const last = economic.at(-1)!;
  await login(page, "browser-poster"); await enter(page, last.id);
  const balance = page.getByRole("region", { name: "Native invoice and refund balance", exact: true });
  await expect(balance.getByText("Original quantity still returnable:", { exact: false })).toContainText("0");
  await expect(balance.getByText("Receivable outstanding:", { exact: false })).toContainText("0.00 USD");
  for (const locale of ["en", "ar"] as const) {
    if (locale === "ar") await page.getByRole("button", { name: "Switch language", exact: true }).click();
    await expect(page.locator("main#main-content")).toHaveAttribute("dir", locale === "ar" ? "rtl" : "ltr");
    await expect(page.getByRole("heading", { name: locale === "ar" ? "إرجاع العميل الجزئي مع حفظ البواقي" : "Partial customer return with retained remainders", exact: true })).toBeVisible();
    for (const width of [320, 768, 1024, 1440]) {
      await page.setViewportSize({ width, height: 900 });
      expect(await page.evaluate(() => Math.max(0, document.documentElement.scrollWidth - document.documentElement.clientWidth))).toBe(0);
      const findings = await new AxeBuilder({ page }).analyze(); expect(findings.violations.map(violation => violation.id)).toEqual([]);
    }
  }
  expect(errors).toBe(0);
});
