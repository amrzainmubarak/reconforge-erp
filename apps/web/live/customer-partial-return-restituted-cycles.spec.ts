import { expect, test, type Page, type Locator } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { execFileSync } from "node:child_process";
import type { PartialReturnPlanV2 } from "../src/customer-partial-returns-data";

const base = process.env.RECONFORGE_ERP_LIVE_URL, tenant = process.env.RECONFORGE_ERP_TENANT;
const password = process.env.RECONFORGE_ERP_PASSWORD, source = process.env.RECONFORGE_CUSTOMER_PARTIAL_RETURN_SOURCE;
let resaleSource: string | undefined;
let checkpoint: "ZeroReturn" | "ResaleInvoiced" | "ResaleReturned" = "ZeroReturn";
const captured = new Set<string>();
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
async function prepareReturn(page: Page, quantity: string, lose = false, selectedSource = source!) {
  await login(page, "browser-maker"); await enter(page);
  const inspect = page.getByRole("form", { name: "Load original source balance", exact: true });
  await inspect.getByLabel("Partial return original stock order ID", { exact: true }).fill(selectedSource);
  const balance = page.waitForResponse(reply => reply.url().endsWith(`${root}/sources/${selectedSource}/balance`) && reply.request().method() === "GET");
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
function captureNative(plan?: PartialReturnPlanV2, observation?: "RetainedReplay" | "DependencyRefusal", refusal?: { method: string; route: string; status: number; code: string }): void {
  const python = process.env.RECONFORGE_PARTIAL_PYTHON, runtime = process.env.RECONFORGE_PARTIAL_RUNTIME_ROOT;
  expect(Boolean(python && runtime && process.env.RECONFORGE_PARTIAL_RESTITUTED_CUSTODY_ROOT), "Owned private restituted committed-row observer is required.").toBe(true);
  execFileSync(python!, ["-m", "tests.customer_partial_return_restituted_browser", "capture"], { cwd: runtime!,
    env: { ...process.env, RECONFORGE_PARTIAL_RESTITUTED_CHECKPOINT: checkpoint,
      RECONFORGE_PARTIAL_RESALE_SOURCE: resaleSource,
      RECONFORGE_PARTIAL_POSTED_PLAN: plan?.id, RECONFORGE_PARTIAL_POSTED_DIGEST: plan?.plan_digest,
      RECONFORGE_PARTIAL_RESTITUTED_OBSERVATION: observation,
      RECONFORGE_PARTIAL_REFUSAL_METHOD: refusal?.method, RECONFORGE_PARTIAL_REFUSAL_ROUTE: refusal?.route,
      RECONFORGE_PARTIAL_REFUSAL_STATUS: refusal ? String(refusal.status) : undefined, RECONFORGE_PARTIAL_REFUSAL_CODE: refusal?.code },
    stdio: "pipe", maxBuffer: 16_384, timeout: 30_000 });
}
function captureCommitted(plan: PartialReturnPlanV2): void {
  const replay = captured.has(checkpoint);
  captureNative(plan, replay ? "RetainedReplay" : undefined); captured.add(checkpoint);
}
async function post(page: Page, plan: PartialReturnPlanV2, lose = false) {
  await phase(page, plan.id, "review"); const posted = await phase(page, plan.id, "post", lose);
  // Observe committed SQL through a separate normal-role lease, never a proof API.
  captureCommitted(posted); return posted;
}
async function openStock(page: Page, username: string, id?: string) {
  await login(page, username);
  await page.getByRole("navigation", { name: "Primary navigation" }).getByRole("button", { name: "Product sales", exact: true }).click();
  const area = page.locator("main.stock-sales");
  for (const [label, value] of Object.entries({ Workspace: "work", Organization: "org", "Legal entity": "entity" })) {
    await area.getByRole("combobox", { name: label, exact: true }).selectOption(value);
  }
  const loaded = page.waitForResponse(reply => reply.url().endsWith("/stock-sales/orders") && reply.request().method() === "GET");
  await area.getByRole("button", { name: "Load selected scope", exact: true }).click(); expect((await loaded).status()).toBe(200);
  if (id) {
    const detail = page.waitForResponse(reply => reply.url().endsWith(`/stock-sales/orders/${id}`) && reply.request().method() === "GET");
    await area.getByRole("button", { name: "Open BROWSER-ZERO-RESALE", exact: true }).click(); expect((await detail).status()).toBe(200);
  }
  return area;
}
async function stockStep(page: Page, username: string, operation: string, button: string, fields: Record<string, string> = {}, choices: Record<string, string> = {}) {
  const area = await openStock(page, username, resaleSource);
  const form = area.locator("form").filter({ has: page.getByLabel("Decision reason", { exact: true }) });
  await form.getByLabel("Decision reason", { exact: true }).fill("Actual governed zero-cost resale");
  await fill(form, fields);
  for (const [label, value] of Object.entries(choices)) await form.getByRole("combobox", { name: label, exact: true }).selectOption(value);
  const response = page.waitForResponse(reply => reply.url().endsWith(`/stock-sales/orders/${resaleSource}/${operation}`) && reply.request().method() === "POST");
  await form.getByRole("button", { name: button, exact: true }).click(); const reply = await response; expect(reply.status()).toBe(200);
  return await reply.json();
}

test("actual zero-cost restituted Stock resale and governed second-source return", async ({ page }) => {
  test.setTimeout(360_000);
  expect(Boolean(base && tenant && password && source), "Owned migrated native148 zero-source HTTPS fixture is required.").toBe(true);
  let errors = 0; page.on("pageerror", () => { ++errors; });
  const oldReturn = await post(page, await prepareReturn(page, "1"));
  expect([oldReturn.credit_minor, oldReturn.cogs_restored_minor, oldReturn.entries.length]).toEqual(["0", "0", 0]);
  const area = await openStock(page, "browser-maker");
  const create = area.getByRole("group", { name: "Create product order", exact: true });
  await fill(create, { "Order number": "BROWSER-ZERO-RESALE", "Customer reference": "BROWSER-ZERO-RESALE-PO", Quantity: "0.1",
    "Unit price in minor units": "1000", "Discount in basis points": "0", "Business date": postingDate, Description: "Real zero-cost restituted inventory resale" });
  for (const [label, value] of Object.entries({ Customer: "CUSTOMER", "Stock item": "ITEM", Warehouse: "MAIN", "Stock location": "STOCK" })) {
    await create.getByRole("combobox", { name: label, exact: true }).selectOption(value);
  }
  const created = page.waitForResponse(reply => reply.url().endsWith("/stock-sales/orders") && reply.request().method() === "POST");
  await create.getByRole("button", { name: "Create product order", exact: true }).click(); const createReply = await created; expect(createReply.status()).toBe(201);
  const createdOrder = await createReply.json(); resaleSource = createdOrder.id;
  expect(typeof resaleSource).toBe("string"); expect(resaleSource).not.toBe(source);
  await stockStep(page, "browser-maker", "submit", "Submit order");
  await stockStep(page, "browser-checker", "approve", "Approve customer terms");
  await stockStep(page, "browser-maker", "reserve", "Reserve stock");
  const issue = await stockStep(page, "browser-maker", "issue/prepare", "Prepare FIFO issue", { "Business date": postingDate }, { "Accounting period": period, "FIFO policy": "FIFO" });
  expect([issue.cost_admission_policy, issue.cogs_minor, issue.cogs_entry_id, issue.cogs_effect_id]).toEqual(["partial-return-restituted-v1", "0", null, null]);
  await stockStep(page, "browser-checker", "issue/review", "Review FIFO and COGS");
  const delivered = await stockStep(page, "browser-poster", "deliver", "Deliver and post COGS");
  expect([delivered.cogs_minor, delivered.cogs_entry_id, delivered.cogs_effect_id]).toEqual(["0", null, null]);
  expect(Boolean(delivered.movement_id && delivered.valuation_id)).toBe(true);
  await expect(page.locator("main.stock-sales").getByText("FIFO COGS", { exact: true })).toBeVisible();
  await expect(page.locator("main.stock-sales").getByText("0.00 USD", { exact: true })).toBeVisible();
  await stockStep(page, "browser-maker", "invoice/prepare", "Prepare AR invoice", { "Invoice number": "BROWSER-ZERO-RESALE-INVOICE", "Business date": postingDate, "Due date": "2026-10-31" },
    { "Accounting period": period, Journal: "SALES", "Receivable account": "AR", "Revenue account": "REVENUE" });
  await stockStep(page, "browser-checker", "invoice/review", "Review revenue");
  const invoiced = await stockStep(page, "browser-poster", "invoice/post", "Post revenue");
  expect(invoiced.total_minor).toBe("100"); expect(invoiced.cogs_effect_id).toBeNull();
  checkpoint = "ResaleInvoiced"; captureNative();
  checkpoint = "ResaleReturned";
  const prepared = await prepareReturn(page, "1", false, resaleSource);
  expect([prepared.credit_minor, prepared.cogs_restored_minor, prepared.receivable_released_minor]).toEqual(["100", "0", "100"]);
  expect(prepared.entries.map(entry => entry.purpose)).toEqual(["RevenueCredit"]);
  const posted = await post(page, prepared, true);
  expect(posted.entries).toHaveLength(1); expect(posted.entries[0].posting_effect_id).not.toBeNull();
  await login(page, "browser-maker"); await enter(page, oldReturn.id);
  const reverse = page.getByRole("form", { name: "Prepare governed reversal", exact: true });
  await fill(reverse, { "Partial cycle fiscal period ID": period, "Partial cycle posting date": postingDate, "Partial cycle reason": "Must refuse consumed original restoration" });
  const refusalReply = page.waitForResponse(reply => reply.url().endsWith(`${root}/plans/${oldReturn.id}/reversals`) && reply.request().method() === "POST");
  await reverse.getByRole("button", { name: "Prepare governed reversal", exact: true }).click(); const refused = await refusalReply;
  expect(refused.status()).toBe(409); const refusalBody = await refused.json(); expect(refusalBody.error.code).toBe("customer_partial_return_reversal_dependency");
  await expect(page.getByRole("alert")).toBeVisible();
  captureNative(oldReturn, "DependencyRefusal", { method: refused.request().method(), route: new URL(refused.url()).pathname, status: refused.status(), code: refusalBody.error.code });
  await login(page, "browser-poster"); await enter(page, posted.id);
  const balance = page.getByRole("region", { name: "Native invoice and refund balance", exact: true });
  await expect(balance.getByText("Receivable outstanding:", { exact: false })).toContainText("0.00 USD");
  for (const locale of ["en", "ar"] as const) {
    if (locale === "ar") await page.getByRole("button", { name: "Switch language", exact: true }).click();
    await expect(page.locator("main#main-content")).toHaveAttribute("dir", locale === "ar" ? "rtl" : "ltr");
    await expect(page.getByRole("heading", { name: locale === "ar" ? "إرجاع العميل الجزئي مع حفظ البواقي" : "Partial customer return with retained remainders", exact: true })).toBeVisible();
    for (const width of [320, 768, 1024, 1440]) {
      await page.setViewportSize({ width, height: 900 });
      expect(await page.evaluate(() => Math.max(0, document.documentElement.scrollWidth - document.documentElement.clientWidth))).toBe(0);
      expect((await new AxeBuilder({ page }).analyze()).violations.map(value => value.id)).toEqual([]);
    }
  }
  expect(errors).toBe(0);
});
