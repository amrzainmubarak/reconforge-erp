import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Locator, type Page } from "@playwright/test";
import { join } from "node:path";
const base = process.env.RECONFORGE_ERP_LIVE_URL, tenant = process.env.RECONFORGE_ERP_TENANT, password = process.env.RECONFORGE_ERP_PASSWORD, artifacts = process.env.RECONFORGE_ERP_BROWSER_ARTIFACTS;
const root = "/api/v1/accrual-deferral";
async function login(page: Page, actor: string, source = "", plan = "") {
  await page.goto(`${base}/accrual-deferral`);
  const logout = page.getByRole("button", { name: "Sign out", exact: true }); if (await logout.count()) await logout.click();
  const form = page.getByRole("form", { name: "Sign in", exact: true });
  for (const [label, value] of Object.entries({ Tenant: tenant!, Username: actor, Password: password! })) await form.getByLabel(label, { exact: true }).fill(value);
  await form.getByRole("button", { name: "Sign in", exact: true }).click();
  const stepup = page.getByRole("form", { name: "Confirm sensitive actions", exact: true });
  await stepup.getByLabel("Password", { exact: true }).fill(password!); await stepup.getByRole("button", { name: "Confirm sensitive actions", exact: true }).click(); await expect(stepup).toHaveCount(0);
  const scope = page.getByRole("form", { name: "Apply scope", exact: true }); await expect(scope.getByLabel("Workspace", { exact: true })).toHaveValue("work"); await scope.getByRole("button", { name: "Apply scope", exact: true }).click();
  const original = page.getByRole("combobox", { name: "Original source", exact: true }); await expect(original).toBeEnabled();
  if (source) { await original.selectOption(source); const plans = page.getByRole("combobox", { name: "Original source plan", exact: true }); await expect(plans).toBeEnabled(); if (plan) await plans.selectOption(plan); }
}
async function command(page: Page, container: Locator, label: string, path: string, lose = false) {
  let original: unknown, body = ""; let committed!: () => void; const completed = new Promise<void>(resolve => { committed = resolve; });
  if (lose) await page.route(`**${root}${path}`, async route => { if (route.request().method() !== "POST") { await route.continue(); return; } body = route.request().postData()!; const reply = await route.fetch(); expect(reply.status(), await reply.text()).toBe(200); original = (await reply.json()).plan; await route.abort("failed"); committed(); }, { times: 1 });
  const response = lose ? null : page.waitForResponse(reply => reply.url().endsWith(root + path) && reply.request().method() === "POST");
  await container.getByRole("button", { name: label, exact: true }).click();
  let plan: Record<string, unknown>;
  if (lose) { await completed; const retry = page.getByRole("button", { name: "Retry exact command", exact: true }); await expect(retry).toBeVisible(); const replay = page.waitForResponse(reply => reply.url().endsWith(root + path) && reply.request().method() === "POST"); await retry.click(); const reply = await replay; expect(reply.status(), await reply.text()).toBe(200); expect(reply.request().postData()).toBe(body); plan = (await reply.json()).plan; expect(plan).toEqual(original); }
  else { const reply = await response!; expect(reply.status(), await reply.text()).toBe(200); plan = (await reply.json()).plan; }
  await expect(page.getByRole("status").filter({ hasText: "Original acknowledgement and current source verified" })).toContainText(String(plan.id)); await expect(page.getByRole("button", { name: "Retry exact command", exact: true })).toHaveCount(0); return plan;
}
async function publish(page: Page, source: string, plan: Record<string, unknown>, lose = false) {
  for (const [actor, operation, label] of [["checker", "review", "Review exact plan"], ["poster", "post", "Publish source and native GL"]]) { await login(page, actor, source, String(plan.id)); plan = await command(page, page.getByRole("main"), label, `/plans/${plan.id}/${operation}`, lose && operation === "post"); }
  return plan;
}
test("real original cash voucher fiscal tranches exact inverse replacement and retained native source", async ({ page }) => {
  test.setTimeout(420_000); expect(base && tenant && password && artifacts, "Owned synthetic HTTPS fixture required").toBeTruthy(); const errors: string[] = []; page.on("pageerror", error => errors.push(error.message));
  await login(page, "maker"); const form = page.getByRole("form", { name: "Prepare source voucher or estimate", exact: true }); await expect(form).toBeVisible();
  await form.getByRole("combobox", { name: "Business path", exact: true }).selectOption("new_prepaid_voucher");
  for (const [label, value] of Object.entries({ "Scoped external reference": "BROWSER-AD1-PREPAID", "Amount in exact minor units": "10001", "Posting date": "2026-10-03", Reason: "Actual reviewed original prepaid service cycle" })) await form.getByLabel(label, { exact: true }).fill(value);
  for (const [label, value] of Object.entries({ "Native journal": "AD1_NATIVE", "Original source · Fiscal period": "period", "Prepaid asset account": "PREPAID", "Expense account": "EXPENSE", "Accrued liability account": "ACCRUAL", "Cash asset account": "CASH" })) await form.getByRole("combobox", { name: label, exact: true }).selectOption(value);
  await form.getByRole("button", { name: "Add tranche", exact: true }).click(); await form.getByRole("button", { name: "Add tranche", exact: true }).click();
  for (const [index, period, day] of [[1, "period", "2026-10-28"], [2, "p2", "2026-11-28"], [3, "p3", "2026-12-28"]] as const) { const prefix = `Tranche ${index} · `; await form.getByLabel(prefix + "Stable tranche ID", { exact: true }).fill("T" + index); await form.getByLabel(prefix + "Posting date", { exact: true }).fill(day); await form.getByLabel(prefix + "Exact allocation weight", { exact: true }).fill("9000000000000000000"); await form.getByRole("combobox", { name: prefix + "Fiscal period", exact: true }).selectOption(period); }
  let original = await command(page, form, "Prepare source voucher or estimate", "/sources", true); const source = String(original.source_id);
  await expect(page.getByRole("button", { name: "Review exact plan", exact: true })).toBeDisabled(); original = await publish(page, source, original, true);
  let second: Record<string, unknown> | null = null;
  for (const tranche of ["T1", "T2", "T3"]) { await login(page, "maker", source); const retained = page.getByRole("form", { name: "Prepare retained tranche", exact: true }); await retained.getByRole("combobox", { name: "Tranche", exact: true }).selectOption(tranche); let plan = await command(page, retained, "Prepare retained tranche", `/sources/${source}/tranches`); plan = await publish(page, source, plan); if (tranche === "T2") second = plan; }
  expect(second).not.toBeNull(); await login(page, "maker", source, String(second!.id)); const inverse = page.getByRole("form", { name: "Prepare exact original inverse", exact: true });
  await inverse.getByRole("combobox", { name: "Prepare exact original inverse · Fiscal period", exact: true }).selectOption("p3"); await inverse.getByLabel("Prepare exact original inverse · Posting date", { exact: true }).fill("2026-12-30"); await inverse.getByLabel("Prepare exact original inverse · Reason", { exact: true }).fill("Original second tranche reviewed exact correction");
  const reversal = await command(page, inverse, "Prepare exact original inverse", `/sources/${source}/reversals`); await publish(page, source, reversal, true);
  await login(page, "maker", source); const replacement = page.getByRole("form", { name: "Prepare retained tranche", exact: true }); await replacement.getByRole("combobox", { name: "Tranche", exact: true }).selectOption("T2"); const replaced = await command(page, replacement, "Prepare retained tranche", `/sources/${source}/tranches`); await publish(page, source, replaced);
  await login(page, "maker", source); const downloaded = page.waitForEvent("download"), proofResponse = page.waitForResponse(reply => reply.url().endsWith(`/sources/${source}/evidence`)); await page.getByRole("button", { name: "Download original evidence", exact: true }).click(); const response = await proofResponse; expect(response.status(), await response.text()).toBe(200); const proof = await response.json(); expect(proof.native_effects).toHaveLength(6); expect(proof.source.request.tranches.map((row: { weight: string }) => row.weight)).toEqual(["9000000000000000000", "9000000000000000000", "9000000000000000000"]); await (await downloaded).saveAs(join(artifacts!, "accrual-deferral-native-proof-en.json"));
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]); await page.setViewportSize({ width: 390, height: 844 }); await page.getByRole("button", { name: "Switch language", exact: true }).click(); await expect(page.getByRole("heading", { name: "جداول المصروفات المقدمة والاستحقاقات", exact: true })).toBeVisible(); await expect(page.getByRole("main")).toHaveAttribute("dir", "rtl");
  expect((await new AxeBuilder({ page }).include("#main-content").withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze()).violations).toEqual([]); expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true); expect(errors).toEqual([]); await page.screenshot({ path: join(artifacts!, "accrual-deferral-ar-mobile.png"), fullPage: true });
});
