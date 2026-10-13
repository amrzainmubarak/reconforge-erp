import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Locator, type Page } from "@playwright/test";
import { writeFile } from "node:fs/promises";
import { join } from "node:path";

const base = process.env.RECONFORGE_ERP_LIVE_URL, tenant = process.env.RECONFORGE_ERP_TENANT, password = process.env.RECONFORGE_ERP_PASSWORD;
const root = "/api/v1/intercompany-fx";
async function login(page: Page, username: string) {
  await page.goto(`${base}/admin-audit`);
  await page.getByLabel("Tenant ID", { exact: true }).fill(tenant!);
  await page.getByLabel("Username", { exact: true }).fill(username);
  await page.getByLabel("Password", { exact: true }).fill(password!);
  await page.getByRole("button", { name: "Sign in to administration", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Confirm privileged access", exact: true })).toBeVisible();
  await page.getByLabel("Password", { exact: true }).fill(password!);
  const reply = page.waitForResponse(response => response.url().endsWith("/auth/step-up"));
  await page.getByRole("button", { name: "Confirm and continue", exact: true }).click();
  expect((await reply).status()).toBe(200);
}
async function enter(page: Page, sourceId = "") {
  await page.getByRole("navigation", { name: "Primary navigation" }).getByRole("button", { name: "Intercompany foreign trade", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Intercompany foreign trade", exact: true })).toBeVisible();
  const form = page.getByRole("form", { name: "Apply organization scope", exact: true });
  for (const [label, value] of Object.entries({ "Workspace ID": "work", "Organization ID": "org" })) {
    await expect(form.getByLabel(label, { exact: true })).toBeEnabled();
    await form.getByLabel(label, { exact: true }).fill(value);
  }
  await form.getByRole("button", { name: "Apply organization scope", exact: true }).click();
  await expect(page.getByRole("form", { name: "Prepare paired trade", exact: true })).toBeVisible();
  if (sourceId) { await page.getByLabel("Retained trade sources", { exact: true }).selectOption(sourceId); await expect(page.getByRole("heading", { name: "BROWSER-ICFX2", exact: true })).toBeVisible(); }
}
async function rateFields(region: Locator, book: string, rate: string, day: string, label = book) {
  await region.getByLabel(label + " · Exact rate", { exact: true }).fill(rate);
  await region.getByLabel(label + " · Rate source", { exact: true }).fill("reviewed-synthetic-ICFX2");
  await region.getByLabel(label + " · Effective at UTC", { exact: true }).fill(day + "T12:00:00Z");
}
async function phase(page: Page, source: string, id: string, operation: "review" | "post") {
  await login(page, "browser-" + (operation === "review" ? "checker" : "poster")); await enter(page, source);
  const region = page.getByRole("region", { name: "Native operation", exact: true });
  await region.getByLabel("Reason", { exact: true }).fill("Actual complete functional-books " + operation);
  const reply = page.waitForResponse(response => response.url().endsWith(`${root}/plans/${id}/${operation}`));
  await region.getByRole("button", { name: operation === "review" ? "Review complete native operation" : "Post complete native operation", exact: true }).click();
  const response = await reply; expect(response.status(), await response.text()).toBe(200); return (await response.json()).plan;
}

test("real paired EUR GBP settlement closing CTA native group elimination and retained browser retry", async ({ page }) => {
  test.setTimeout(300_000);
  expect(base && tenant && password && process.env.RECONFORGE_ERP_BROWSER_ARTIFACTS, "Owned synthetic HTTPS fixture must be supplied").toBeTruthy();
  await login(page, "browser-maker"); await enter(page);
  const form = page.getByRole("form", { name: "Prepare paired trade", exact: true });
  for (const [label, value] of Object.entries({ "Source reference": "BROWSER-ICFX2", "Transaction minor units": "10001", "Posting date": "2026-10-03", Reason: "Actual paired foreign trade" })) await form.getByLabel(label, { exact: true }).fill(value);
  await form.getByLabel("Transaction currency", { exact: true }).selectOption("USD");
  const maps = { "Seller functional book": { entity: "seller", currency: "EUR", party: "IC2_AR", trade: "IC2_REV" }, "Buyer functional book": { entity: "buyer", currency: "GBP", party: "IC2_AP", trade: "IC2_EXP" }, "Group reporting adjustment": { entity: "group", currency: "USD", party: "", trade: "" } };
  for (const [book, config] of Object.entries(maps)) {
    for (const [label, value] of Object.entries({ "Legal entity": config.entity, "Native journal": "IC2_" + config.currency, "Fiscal period": "period" })) await form.getByLabel(book + " · " + label, { exact: true }).selectOption(value);
    const accounts = { Cash: "IC2_CASH", "Realized FX gain": "IC2_RGAIN", "Realized FX loss": "IC2_RLOSS", "Unrealized FX gain": "IC2_UGAIN", "Unrealized FX loss": "IC2_ULOSS", ...(config.party ? { "Party receivable/payable": config.party, "Trade revenue/expense": config.trade } : { "Group receivable": "IC2_AR", "Group payable": "IC2_AP", "Group revenue": "IC2_REV", "Group expense": "IC2_EXP", "Translation adjustment (CTA)": "IC2_CTA" }) };
    for (const [label, value] of Object.entries(accounts)) await form.getByLabel(book + " · " + label, { exact: true }).selectOption(value);
  }
  await rateFields(form, "Seller functional book", "1.25", "2026-10-03"); await rateFields(form, "Buyer functional book", "0.8", "2026-10-03");
  let lost: unknown, originalBody = "";
  await page.route(`**${root}/sources`, async route => { if (route.request().method() !== "POST") { await route.continue(); return; } originalBody = route.request().postData()!; const response = await route.fetch(); expect(response.status(), await response.text()).toBe(200); lost = (await response.json()).plan; await route.abort("failed"); }, { times: 1 });
  await form.getByRole("button", { name: "Prepare paired trade", exact: true }).click();
  await expect(page.getByRole("button", { name: "Retry unchanged command", exact: true })).toBeVisible();
  const retried = page.waitForResponse(response => response.url().endsWith(root + "/sources") && response.request().method() === "POST");
  await page.getByRole("button", { name: "Retry unchanged command", exact: true }).click();
  const reply = await retried; expect(reply.status(), await reply.text()).toBe(200); let plan = (await reply.json()).plan;
  expect(plan).toEqual(lost); expect(reply.request().postData()).toBe(originalBody);
  const sourceId = plan.source_id;
  for (let stage = 0; stage < 4; stage++) {
    plan = await phase(page, sourceId, plan.id, "review"); plan = await phase(page, sourceId, plan.id, "post");
    const evidenceReply = page.waitForResponse(response => response.url().endsWith(`${root}/plans/${plan.id}/evidence`));
    await page.getByRole("button", { name: "Verify original native evidence", exact: true }).click();
    const evidence = await evidenceReply; expect(evidence.status(), await evidence.text()).toBe(200);
    await expect(page.getByRole("status")).toContainText("Source, plan and every native effect seal verified");
    await writeFile(join(process.env.RECONFORGE_ERP_BROWSER_ARTIFACTS!, `intercompany-fx-stage-${stage}.json`), JSON.stringify((await evidence.json()).evidence));
    if (stage === 3) break;
    await login(page, "browser-maker"); await enter(page, sourceId);
    const history = page.getByRole("region", { name: "Original operation history", exact: true });
    const day = ["2026-10-04", "2026-10-05", "2026-10-06"][stage];
    await history.getByLabel("Posting date", { exact: true }).fill(day); await history.getByLabel("Reason", { exact: true }).fill("Actual captured reviewed progression");
    for (const book of Object.keys(maps)) await history.getByLabel(book + " · Fiscal period", { exact: true }).selectOption("period");
    const sellerRate = stage === 0 ? "1.3" : "1.32", buyerRate = stage === 0 ? "0.78" : "0.82";
    await rateFields(history, "Seller functional book", sellerRate, day); await rateFields(history, "Buyer functional book", buyerRate, day);
    if (stage === 0) await history.getByLabel("Transaction minor units", { exact: true }).fill("3000");
    if (stage === 2) {
      for (const [eventDay, seller, buyer] of [["2026-10-03", "1.25", "0.8"], ["2026-10-04", "1.3", "0.78"], ["2026-10-05", "1.32", "0.82"]]) {
        await rateFields(history, "Seller functional book", seller, eventDay, "Seller functional book · " + eventDay);
        await rateFields(history, "Buyer functional book", buyer, eventDay, "Buyer functional book · " + eventDay);
      }
    }
    const suffix = ["settlements", "revaluations", "eliminations"][stage], action = ["Prepare cash installment", "Prepare closing revaluation", "Prepare native group elimination"][stage];
    const progressed = page.waitForResponse(response => response.url().endsWith(`${root}/sources/${sourceId}/${suffix}`));
    await history.getByRole("button", { name: action, exact: true }).click();
    const response = await progressed; expect(response.status(), await response.text()).toBe(200); plan = (await response.json()).plan;
  }
  const reporting = page.waitForResponse(response => response.url().endsWith(`${root}/sources/${sourceId}/report`));
  await page.getByRole("button", { name: "Verify translated management report", exact: true }).click();
  const result = await reporting; expect(result.status(), await result.text()).toBe(200); const report = (await result.json()).report;
  expect(report.cash_net_movement_minor).toBe("101"); expect(report.cta_minor).toBe("-291"); expect(report.income_statement.result_minor).toBe("392");
  await expect(page.getByRole("region", { name: "Translated and native group membership verified", exact: true })).toBeVisible();
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  await writeFile(join(process.env.RECONFORGE_ERP_BROWSER_ARTIFACTS!, "intercompany-fx-management-report.json"), JSON.stringify(report));
  const downloaded = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download verified report", exact: true }).click();
  await (await downloaded).saveAs(join(process.env.RECONFORGE_ERP_BROWSER_ARTIFACTS!, "intercompany-fx-report-download.json"));
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "Switch language", exact: true }).click();
  await expect(page.getByRole("heading", { name: "التجارة بين الشركات بعملات مختلفة", exact: true })).toBeVisible();
  await expect(page.getByRole("main")).toHaveAttribute("dir", "rtl");
  const arabicScope = page.getByRole("form", { name: "تطبيق نطاق المؤسسة", exact: true });
  await arabicScope.getByRole("button", { name: "تطبيق نطاق المؤسسة", exact: true }).click();
  await page.getByLabel("مصادر التجارة المحفوظة", { exact: true }).selectOption(sourceId);
  await page.getByRole("button", { name: "التحقق من الأدلة الأصلية", exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: "تم التحقق من أختام المصدر والخطة وكل الآثار الأصلية" })).toBeVisible();
  const arabicDownload = page.waitForEvent("download");
  await page.getByRole("button", { name: "تنزيل الأدلة المتحقق منها", exact: true }).click();
  await (await arabicDownload).saveAs(join(process.env.RECONFORGE_ERP_BROWSER_ARTIFACTS!, "intercompany-fx-proof-ar-mobile.json"));
  expect((await new AxeBuilder({ page }).include("#main-content").withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze()).violations).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: join(process.env.RECONFORGE_ERP_BROWSER_ARTIFACTS!, "intercompany-fx-ar-mobile.png"), fullPage: true });
});
