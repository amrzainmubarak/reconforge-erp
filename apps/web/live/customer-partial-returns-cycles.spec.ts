import { expect, test, type Page, type Locator } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { execFileSync } from "node:child_process";
import type { PartialReturnPlan } from "../src/customer-partial-returns-data";

const base = process.env.RECONFORGE_ERP_LIVE_URL, tenant = process.env.RECONFORGE_ERP_TENANT;
const password = process.env.RECONFORGE_ERP_PASSWORD, source = process.env.RECONFORGE_CUSTOMER_PARTIAL_RETURN_SOURCE;
const root = "/customer-partial-returns", period = "period", postingDate = "2026-10-15";
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
  await page.getByRole("button", { name: "Partial return cycle", exact: true }).click(); expect((await loaded).status()).toBe(200);
  await expect(page.getByRole("heading", { name: "Partial customer return cycle", exact: true })).toBeVisible();
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
async function command(page: Page, path: string, trigger: () => Promise<void>, lose = false): Promise<PartialReturnPlan> {
  if (!lose) {
    const response = page.waitForResponse(reply => reply.url().endsWith(path) && reply.request().method() === "POST");
    await trigger(); const reply = await response; expect(reply.status()).toBe(200); return (await reply.json()).plan as PartialReturnPlan;
  }
  let originalBody = "", committed: PartialReturnPlan | null = null, status = 0, finish!: () => void;
  const done = new Promise<void>(resolve => { finish = resolve; });
  // This is a real database command; only its already committed response is lost.
  await page.route(`**/api/v1${path}`, async route => {
    originalBody = route.request().postData() ?? "";
    try { const reply = await route.fetch(); status = reply.status(); if (status === 200) committed = (await reply.json()).plan as PartialReturnPlan; await route.abort("failed"); }
    finally { finish(); }
  }, { times: 1 });
  await trigger(); await done; expect(status).toBe(200); expect(Boolean(committed)).toBe(true);
  // Retain the actual committed state before the human retry; post() observes
  // the retained ACK again and must deduplicate this same native history row.
  if (path.endsWith("/post")) captureCommitted(committed!);
  const retry = page.getByRole("button", { name: "Retry retained partial command", exact: true }); await expect(retry).toBeVisible();
  for (const name of ["Whole original tranche", "Partial return cycle", "Apply scope", "Sign out"]) await expect(page.getByRole("button", { name, exact: true })).toBeDisabled();
  const response = page.waitForResponse(reply => reply.url().endsWith(path) && reply.request().method() === "POST");
  await retry.click(); const reply = await response; expect(reply.status()).toBe(200);
  expect(reply.request().postData() === originalBody).toBe(true);
  const retained = (await reply.json()).plan as PartialReturnPlan;
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
function captureCommitted(plan: PartialReturnPlan): void {
  const python = process.env.RECONFORGE_PARTIAL_PYTHON, runtime = process.env.RECONFORGE_PARTIAL_RUNTIME_ROOT;
  expect(Boolean(python && runtime && process.env.RECONFORGE_PARTIAL_CUSTODY_ROOT), "Owned private native committed-row observer is required.").toBe(true);
  execFileSync(python!, ["-m", "tests.customer_partial_returns_browser", "capture"], { cwd: runtime!,
    env: { ...process.env, RECONFORGE_PARTIAL_POSTED_PLAN: plan.id, RECONFORGE_PARTIAL_POSTED_DIGEST: plan.plan_digest },
    stdio: "pipe", maxBuffer: 16_384, timeout: 30_000 });
}
async function post(page: Page, plan: PartialReturnPlan, lose = false) {
  await phase(page, plan.id, "review"); const posted = await phase(page, plan.id, "post", lose);
  // Observe committed SQL through a separate normal-role lease, never a proof API.
  captureCommitted(posted); return posted;
}
async function prepareFromPosted(page: Page, parent: PartialReturnPlan, operation: "refund" | "reverse", amount?: string) {
  await login(page, "browser-maker"); await enter(page, parent.id);
  const name = operation === "refund" ? "Prepare governed refund" : "Prepare governed reversal";
  const form = page.getByRole("form", { name, exact: true });
  await fill(form, { "Partial cycle fiscal period ID": period, "Partial cycle posting date": postingDate, "Partial cycle reason": "Actual governed original source correction",
    ...(amount ? { "Refund amount in exact minor units": amount } : {}) });
  return command(page, `${root}/plans/${parent.id}/${operation === "refund" ? "refunds" : "reversals"}`, () => form.getByRole("button", { name, exact: true }).click());
}
test("actual partial FIFO credits refunds reversals cancellation replay and bilingual evidence", async ({ page }) => {
  test.setTimeout(360_000);
  expect(Boolean(base && tenant && password && source), "Owned migrated native HTTPS fixture is required; no mock or skip path.").toBe(true);
  let errors = 0; page.on("pageerror", () => { ++errors; });
  const cancelled = await prepareReturn(page, "12", true); await phase(page, cancelled.id, "review"); await phase(page, cancelled.id, "cancel");
  const first = await prepareReturn(page, "12"); expect([first.credit_minor, first.cogs_restored_minor, first.receivable_released_minor, first.refund_entitlement_delta_minor]).toEqual(["54000", "16000", "54000", "0"]);
  const firstPosted = await post(page, first, true); await post(page, await prepareFromPosted(page, firstPosted, "reverse"));
  await post(page, await prepareReturn(page, "12"));
  const last = await prepareReturn(page, "3"); expect([last.credit_minor, last.cogs_restored_minor, last.receivable_released_minor, last.refund_entitlement_delta_minor]).toEqual(["13500", "6000", "3500", "10000"]);
  const lastPosted = await post(page, last);
  await post(page, await prepareFromPosted(page, lastPosted, "refund", "3000"));
  const refund = await post(page, await prepareFromPosted(page, lastPosted, "refund", "7000"), true);
  await post(page, await prepareFromPosted(page, refund, "reverse"));
  await post(page, await prepareFromPosted(page, lastPosted, "refund", "7000"));
  await login(page, "browser-poster"); await enter(page, lastPosted.id);
  const balance = page.getByRole("region", { name: "Native invoice and refund balance", exact: true });
  await expect(balance.getByText("Refund due:", { exact: false })).toContainText("0.00 USD");
  await expect(page.getByRole("form", { name: "Prepare governed refund", exact: true })).toHaveCount(0);
  for (const locale of ["en", "ar"] as const) {
    if (locale === "ar") await page.getByRole("button", { name: "Switch language", exact: true }).click();
    await expect(page.locator("main#main-content")).toHaveAttribute("dir", locale === "ar" ? "rtl" : "ltr");
    await expect(page.getByRole("heading", { name: locale === "ar" ? "دورة إرجاع العميل الجزئي" : "Partial customer return cycle", exact: true })).toBeVisible();
    for (const width of [320, 768, 1024, 1440]) {
      await page.setViewportSize({ width, height: 900 });
      expect(await page.evaluate(() => Math.max(0, document.documentElement.scrollWidth - document.documentElement.clientWidth))).toBe(0);
      const findings = await new AxeBuilder({ page }).analyze(); expect(findings.violations.map(violation => violation.id)).toEqual([]);
    }
  }
  expect(errors).toBe(0);
});
