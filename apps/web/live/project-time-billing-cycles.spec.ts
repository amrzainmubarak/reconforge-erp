import { expect, test, type Page, type Locator } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
const base = process.env.RECONFORGE_ERP_LIVE_URL, tenant = process.env.RECONFORGE_ERP_TENANT, password = process.env.RECONFORGE_ERP_PASSWORD;
const root = "/api/v1/project-time-billing";
async function fill(form: Locator, values: Record<string, string>) {
  for (const [label, value] of Object.entries(values)) await form.getByLabel(label, { exact: true }).fill(value);
}
async function login(page: Page, username: string) {
  await page.goto(`${base}/project-time-billing`);
  const logout = page.getByRole("button", { name: "Sign out", exact: true });
  if (await logout.count()) await logout.click();
  const form = page.getByRole("form", { name: "Sign in", exact: true });
  await fill(form, { Tenant: tenant!, Username: username, Password: password! });
  await form.getByRole("button", { name: "Sign in", exact: true }).click();
  const elevated = page.getByRole("form", { name: "Confirm identity", exact: true });
  await elevated.getByLabel("Password", { exact: true }).fill(password!);
  await elevated.getByRole("button", { name: "Confirm identity", exact: true }).click();
  await expect(elevated).toHaveCount(0);
  const scope = page.getByRole("form", { name: "Apply scope", exact: true });
  await expect(scope.getByLabel("Workspace", { exact: true })).toHaveValue("work");
  await scope.getByRole("button", { name: "Apply scope", exact: true }).click();
  await expect(page.getByRole("combobox", { name: "Original source plan", exact: true })).toBeVisible();
}
async function command(page: Page, container: Locator, name: string, path: string, key: "plan" | "price", lose = false) {
  let original: unknown, body = "", finish!: () => void;
  const committed = new Promise<void>(resolve => { finish = resolve; });
  if (lose) await page.route(`**${root}${path}`, async route => {
    if (route.request().method() !== "POST") { await route.continue(); return; }
    body = route.request().postData()!;
    const reply = await route.fetch(); expect(reply.status(), await reply.text()).toBe(200);
    original = (await reply.json())[key]; await route.abort("failed"); finish();
  }, { times: 1 });
  const response = lose ? null : page.waitForResponse(reply => reply.url().endsWith(root + path) && reply.request().method() === "POST");
  await container.getByRole("button", { name, exact: true }).click();
  let value: Record<string, unknown>;
  if (lose) {
    await committed;
    const retry = page.getByRole("button", { name: "Retry exact command", exact: true }); await expect(retry).toBeVisible();
    const replay = page.waitForResponse(reply => reply.url().endsWith(root + path) && reply.request().method() === "POST"); await retry.click();
    const reply = await replay; expect(reply.status(), await reply.text()).toBe(200); expect(reply.request().postData()).toBe(body);
    value = (await reply.json())[key]; expect(value).toEqual(original);
  } else {
    const reply = await response!; expect(reply.status(), await reply.text()).toBe(200); value = (await reply.json())[key];
  }
  await expect(page.getByRole("button", { name: "Retry exact command", exact: true })).toHaveCount(0);
  await expect(page.getByRole("status").filter({ hasText: "Verified source saved" })).toContainText(String(value.id));
  return value;
}
async function selectPlan(page: Page, id: string) {
  const selector = page.getByRole("combobox", { name: "Original source plan", exact: true });
  await expect(selector.locator(`option[value="${id}"]`)).toHaveCount(1); await selector.selectOption(id);
  const source = page.getByRole("region", { name: "Original source plan", exact: true }); await expect(source).toContainText(id);
  return source;
}
async function phase(page: Page, id: string, action: "review" | "post", lose = false) {
  await login(page, action === "review" ? "checker" : "poster");
  const source = await selectPlan(page, id);
  const value = await command(page, source, action === "review" ? "Review exact original source" : "Publish source and native GL", `/plans/${id}/${action}`, "plan", lose);
  await expect(source).toContainText(action === "post" ? "Posted with verified native effect" : "Reviewed");
  return value;
}
test("real approved project time effective prices native AR revenue partial final cash and retained command", async ({ page }) => {
  test.setTimeout(420_000); expect(base && tenant && password, "Owned HTTPS approved-time fixture required").toBeTruthy();
  const errors: string[] = []; page.on("pageerror", error => errors.push(error.message));
  await login(page, "maker");
  const prices: string[] = [];
  for (const [project, rate] of [["P1", "2001"], ["P2", "3001"]]) {
    const form = page.getByRole("form", { name: "Submit effective price", exact: true });
    await expect(form.getByRole("combobox", { name: "Project", exact: true }).getByRole("option", { name: project, exact: true })).toHaveCount(1);
    await form.getByRole("combobox", { name: "Project", exact: true }).selectOption({ label: project });
    await fill(form, { "Customer code": "CUSTOMER", "Effective from": "2026-10-01", "Effective through": "2026-10-31", Currency: "USD", "Hourly customer price (minor units)": rate, "Source reason": "Original synthetic customer Project agreement" });
    const price = await command(page, form, "Submit effective price", "/prices", "price", project === "P1"); prices.push(String(price.id));
    const original = page.locator("section.panel").filter({ has: page.getByRole("heading", { name: "Customer Project price", exact: true }) }).filter({ hasText: String(price.id) });
    await expect(original.getByRole("button", { name: "Approve original price", exact: true })).toBeDisabled();
  }
  await login(page, "checker");
  for (const id of prices) {
    const original = page.locator("section.panel").filter({ has: page.getByRole("heading", { name: "Customer Project price", exact: true }) }).filter({ hasText: id });
    await command(page, original, "Approve original price", `/prices/${id}/approve`, "price");
  }
  await login(page, "maker");
  const form = page.getByRole("form", { name: "Prepare native AR invoice", exact: true });
  await fill(form, { "Customer code": "CUSTOMER", "Invoice number": "BROWSER-TIME-INVOICE", "Fiscal period ID": "period", "Posting date": "2026-10-04", "Due date": "2026-10-15", "Journal code": "STOCK", "AR account": "AR", "Revenue account": "REVENUE", "Cash account": "CASH" });
  for (const name of ["Whole approved time documents", "Approved price versions"]) {
    const group = form.getByRole("group", { name, exact: true }); await expect(group.getByRole("checkbox")).toHaveCount(2);
    for (const checkbox of await group.getByRole("checkbox").all()) await checkbox.check();
  }
  const invoice = await command(page, form, "Prepare native AR invoice", "/invoices", "plan", true); expect(invoice.amount_minor).toBe("6236");
  const prepared = page.getByRole("region", { name: "Original source plan", exact: true });
  await expect(prepared.getByRole("button", { name: "Review exact original source", exact: true })).toBeDisabled();
  await phase(page, String(invoice.id), "review"); await phase(page, String(invoice.id), "post", true);
  for (const [amount, day] of [["1000", "2026-10-05"], ["5236", "2026-10-06"]]) {
    await login(page, "maker"); await selectPlan(page, String(invoice.id));
    const collection = page.getByRole("form", { name: "Prepare partial/final collection", exact: true });
    await fill(collection, { "Collection (minor units)": amount, "Fiscal period ID": "period", "Posting date": day });
    const source = await command(page, collection, "Prepare partial/final collection", `/invoices/${invoice.id}/collections`, "plan");
    await phase(page, String(source.id), "review"); await phase(page, String(source.id), "post", amount === "5236");
  }
  await login(page, "maker"); const source = await selectPlan(page, String(invoice.id));
  const downloaded = page.waitForEvent("download");
  const request = page.waitForResponse(reply => reply.url().endsWith(`/invoices/${invoice.id}/evidence`));
  await source.getByRole("button", { name: "Verify source hashes and download evidence", exact: true }).click();
  const evidence = (await (await request).json()).evidence;
  expect(evidence.invoice.id).toBe(invoice.id); expect(evidence.native_effects).toHaveLength(3);
  expect(evidence.ar_invoice.outstanding_minor).toBe("0"); expect(evidence.observed_native_balances).toEqual({ AR: "0", CASH: "6236", REVENUE: "-6236" });
  await expect((await downloaded).suggestedFilename()).toBe(`${invoice.id}-evidence.json`);
  await test.info().attach("pb1-original-native-financial-evidence", { body: JSON.stringify(evidence), contentType: "application/json" });
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  await page.setViewportSize({ width: 390, height: 844 }); await page.getByRole("button", { name: "Switch language", exact: true }).click();
  await expect(page.getByRole("heading", { name: "فوترة وقت المشاريع والتحصيل", exact: true })).toBeVisible();
  await expect(page.locator("main#main-content")).toHaveAttribute("dir", "rtl");
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]); expect(errors).toEqual([]);
});
