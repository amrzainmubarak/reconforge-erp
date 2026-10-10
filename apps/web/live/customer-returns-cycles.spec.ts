import { expect, test, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
const base = process.env.RECONFORGE_ERP_LIVE_URL, tenant = process.env.RECONFORGE_ERP_TENANT, password = process.env.RECONFORGE_ERP_PASSWORD, source = process.env.RECONFORGE_CUSTOMER_RETURN_SOURCE;
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
async function enter(page: Page, id = "") {
  await page.getByRole("navigation", { name: "Primary navigation" }).getByRole("button", { name: "Customer returns", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Original customer returns and partial refunds", exact: true })).toBeVisible();
  const form = page.getByRole("form", { name: "Apply scope", exact: true });
  for (const [label, value] of Object.entries({ "Workspace ID": "work", "Organization ID": "org", "Legal entity ID": "entity" })) await form.getByLabel(label, { exact: true }).fill(value);
  const loaded = page.waitForResponse(reply => reply.url().endsWith("/customer-returns/plans") && reply.request().method() === "GET");
  await form.getByRole("button", { name: "Apply scope", exact: true }).click(); expect((await loaded).status()).toBe(200);
  if (id) { await page.getByRole("combobox", { name: "Retained credit or refund", exact: true }).selectOption(id); await expect(page.getByRole("region", { name: "Original source and native financial evidence", exact: true })).toBeVisible(); }
}
async function prepare(page: Page, lose = false) {
  await login(page, "browser-maker"); await enter(page);
  const form = page.getByRole("form", { name: "Prepare whole original return", exact: true });
  for (const [label, value] of Object.entries({ "Original delivered stock order ID": source!, "Open fiscal period ID": "period", "Posting date": "2026-10-10", "Cash journal code": "CASH", "Customer refund liability account": "REFUND", "Original collected cash account": "CASH", Reason: "Actual original whole delivered source" })) await form.getByLabel(label, { exact: true }).fill(value);
  let lost: Record<string, unknown> | null = null, originalBody = "";
  let finishLoss!: () => void;
  const committedLoss = new Promise<void>(resolve => { finishLoss = resolve; });
  if (lose) await page.route("**/api/v1/customer-returns/plans", async route => {
    if (route.request().method() !== "POST") { await route.continue(); return; }
    originalBody = route.request().postData()!; const reply = await route.fetch(); expect(reply.status()).toBe(200); lost = (await reply.json()).plan; await route.abort("failed"); finishLoss();
  }, { times: 1 });
  const result = lose ? null : page.waitForResponse(reply => reply.url().endsWith("/customer-returns/plans") && reply.request().method() === "POST");
  await form.getByRole("button", { name: "Prepare whole original return", exact: true }).click();
  if (lose) {
    await committedLoss;
    await expect(page.getByRole("button", { name: "Retry retained command", exact: true })).toBeVisible();
    const retried = page.waitForResponse(reply => reply.url().endsWith("/customer-returns/plans") && reply.request().method() === "POST");
    await page.getByRole("button", { name: "Retry retained command", exact: true }).click(); const reply = await retried;
    expect(reply.status(), await reply.text()).toBe(200); expect(reply.request().postData()).toBe(originalBody); const actual = (await reply.json()).plan; expect(actual).toEqual(lost); return actual;
  }
  const reply = await result!; expect(reply.status(), await reply.text()).toBe(200); return (await reply.json()).plan;
}
async function phase(page: Page, id: string, action: "review" | "post" | "cancel", lose = false) {
  await login(page, action === "review" ? "browser-checker" : "browser-poster"); await enter(page, id);
  const region = page.getByRole("region", { name: "Original source and native financial evidence", exact: true });
  await region.getByLabel("Reason", { exact: true }).fill(`Actual browser independent ${action}`);
  const path = `/customer-returns/plans/${id}/${action}`, name = action === "review" ? "Review source inverse" : action === "post" ? "Post complete native effect" : "Cancel unposted plan";
  let lost: Record<string, unknown> | null = null, originalBody = "";
  let finishLoss!: () => void;
  const committedLoss = new Promise<void>(resolve => { finishLoss = resolve; });
  if (lose) await page.route(`**/api/v1${path}`, async route => { originalBody = route.request().postData()!; const reply = await route.fetch(); expect(reply.status()).toBe(200); lost = (await reply.json()).plan; await route.abort("failed"); finishLoss(); }, { times: 1 });
  const response = lose ? null : page.waitForResponse(reply => reply.url().endsWith(path) && reply.request().method() === "POST");
  await region.getByRole("button", { name, exact: true }).click();
  if (lose) {
    await committedLoss;
    await expect(page.getByRole("button", { name: "Retry retained command", exact: true })).toBeVisible();
    const again = page.waitForResponse(reply => reply.url().endsWith(path) && reply.request().method() === "POST");
    await page.getByRole("button", { name: "Retry retained command", exact: true }).click(); const reply = await again; expect(reply.status()).toBe(200);
    expect(reply.request().postData()).toBe(originalBody); const actual = (await reply.json()).plan; expect(actual).toEqual(lost); return actual;
  }
  const reply = await response!; expect(reply.status(), await reply.text()).toBe(200); return (await reply.json()).plan;
}
test("actual original credit release partial cash refunds lost responses and bilingual native evidence", async ({ page }) => {
  test.setTimeout(360_000); expect(base && tenant && password && source, "Owned native HTTPS fixture and source ID must be provided").toBeTruthy();
  const errors: string[] = []; page.on("pageerror", error => errors.push(error.message));
  const cancelled = await prepare(page, true); await phase(page, cancelled.id, "review"); await phase(page, cancelled.id, "cancel", true);
  const credit = await prepare(page); expect([credit.credit_minor, credit.cogs_restored_minor, credit.refund_entitlement_minor, credit.receivable_released_minor]).toEqual(["45000", "12000", "10000", "35000"]);
  await phase(page, credit.id, "review"); const posted = await phase(page, credit.id, "post", true); expect(posted.posting_effect_ids).toHaveLength(3);
  for (const amount of ["3000", "7000"]) {
    await login(page, "browser-maker"); await enter(page, credit.id);
    const form = page.getByRole("form", { name: "Prepare partial cash refund", exact: true }); await expect(form).toBeVisible();
    for (const [label, value] of Object.entries({ "Refund in exact minor units": amount, "Open fiscal period ID": "period", "Posting date": "2026-10-10", Reason: "Actual native partial cash refund" })) await form.getByLabel(label, { exact: true }).fill(value);
    const response = page.waitForResponse(reply => reply.url().endsWith(`/customer-returns/plans/${credit.id}/refunds`));
    await form.getByRole("button", { name: "Prepare partial cash refund", exact: true }).click(); const reply = await response; expect(reply.status(), await reply.text()).toBe(200);
    const installment = (await reply.json()).plan; expect(installment.amount_minor).toBe(amount);
    await phase(page, installment.id, "review"); await phase(page, installment.id, "post", amount === "7000");
  }
  await login(page, "browser-maker"); await enter(page, credit.id);
  await expect(page.getByText("Refund liability remaining:", { exact: false })).toContainText("0.00 USD");
  await expect(page.getByRole("form", { name: "Prepare partial cash refund", exact: true })).toHaveCount(0);
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  await page.getByRole("button", { name: "Switch language", exact: true }).click();
  await expect(page.getByRole("heading", { name: "إرجاع العميل الأصلي وردّ النقد على دفعات", exact: true })).toBeVisible();
  await expect(page.locator("main#main-content")).toHaveAttribute("dir", "rtl");
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]); expect(errors).toEqual([]);
});
