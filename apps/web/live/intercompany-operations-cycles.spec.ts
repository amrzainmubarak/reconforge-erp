import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

const base = process.env.RECONFORGE_ERP_LIVE_URL, tenant = process.env.RECONFORGE_ERP_TENANT, password = process.env.RECONFORGE_ERP_PASSWORD;
const root = "/api/v1/intercompany-operations";
async function login(page: Page, username: string) {
  await page.goto(`${base}/admin-audit`);
  await page.getByLabel("Tenant ID", { exact: true }).fill(tenant!);
  await page.getByLabel("Username", { exact: true }).fill(username);
  await page.getByLabel("Password", { exact: true }).fill(password!);
  await page.getByRole("button", { name: "Sign in to administration", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Confirm privileged access", exact: true })).toBeVisible();
  await page.getByLabel("Password", { exact: true }).fill(password!);
  const response = page.waitForResponse(reply => reply.url().endsWith("/auth/step-up"));
  await page.getByRole("button", { name: "Confirm and continue", exact: true }).click();
  expect((await response).status()).toBe(200);
}
async function enter(page: Page, sourceId = "") {
  await page.getByRole("navigation", { name: "Primary navigation" }).getByRole("button", { name: "Intercompany operations", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Intercompany operations", exact: true })).toBeVisible();
  const form = page.getByRole("form", { name: "Organization scope", exact: true });
  for (const [label, value] of Object.entries({ "Workspace ID": "work", "Organization ID": "org" })) {
    await expect(form.getByLabel(label, { exact: true })).toBeEnabled();
    await form.getByLabel(label, { exact: true }).fill(value);
    await expect(form.getByLabel(label, { exact: true })).toHaveValue(value);
  }
  await form.getByRole("button", { name: "Apply scope", exact: true }).click();
  await expect(page.getByRole("form", { name: "Prepare paired service charge", exact: true })).toBeVisible();
  if (sourceId) {
    await page.getByRole("combobox", { name: "Retained sources", exact: true }).selectOption(sourceId);
    await expect(page.getByRole("heading", { name: "BROWSER-IC1", exact: true })).toBeVisible();
  }
}
async function phase(page: Page, sourceId: string, planId: string, operation: "review" | "post") {
  await login(page, operation === "review" ? "browser-checker" : "browser-poster"); await enter(page, sourceId);
  const region = page.getByRole("region", { name: "Native operation", exact: true });
  await region.getByLabel("Reason", { exact: true }).fill(`Actual independent native ${operation}`);
  const reply = page.waitForResponse(response => response.url().endsWith(`${root}/plans/${planId}/${operation}`) && response.request().method() === "POST");
  await region.getByRole("button", { name: operation === "review" ? "Review every native entry" : "Post whole native operation", exact: true }).click();
  const response = await reply; expect(response.status(), await response.text()).toBe(200); return (await response.json()).plan;
}

test("real atomic paired partial cash native elimination and bilingual three-book evidence", async ({ page }) => {
  test.setTimeout(300_000);
  expect(base && tenant && password && process.env.RECONFORGE_ERP_BROWSER_ARTIFACTS, "Owned HTTPS native fixture must be supplied").toBeTruthy();
  await login(page, "browser-maker"); await enter(page);
  const form = page.getByRole("form", { name: "Prepare paired service charge", exact: true });
  for (const [label, value] of Object.entries({ "Source reference": "BROWSER-IC1", "Original minor units": "10001", "Posting date": "2026-10-03", Reason: "Actual paired original service charge" })) await form.getByLabel(label, { exact: true }).fill(value);
  for (const [label, value] of Object.entries({ "Seller entity": "entity", "Buyer entity": "buyer", "Group adjustment scope": "group", "Fiscal period": "period", "Native journal": "STOCK", "IC receivable account": "IC_AR", "IC payable account": "IC_AP", "IC income account": "IC_REVENUE", "IC expense account": "IC_EXPENSE", "Cash account": "CASH" })) await form.getByRole("combobox", { name: label, exact: true }).selectOption(value);
  let lost: unknown = null, commandId = "";
  await page.route(`**${root}/sources`, async route => {
    if (route.request().method() !== "POST") { await route.continue(); return; }
    commandId = route.request().postDataJSON().command_id;
    const response = await route.fetch(); expect(response.status(), await response.text()).toBe(200); lost = (await response.json()).plan;
    await route.abort("failed");
  }, { times: 1 });
  await form.getByRole("button", { name: "Prepare paired service charge", exact: true }).click();
  await expect(page.getByRole("button", { name: "Retry unchanged command", exact: true })).toBeVisible();
  const retried = page.waitForResponse(response => response.url().endsWith(`${root}/sources`) && response.request().method() === "POST");
  await page.getByRole("button", { name: "Retry unchanged command", exact: true }).click();
  const retry = await retried; expect(retry.status(), await retry.text()).toBe(200); let plan = (await retry.json()).plan;
  expect(plan).toEqual(lost); expect(commandId).not.toBe(""); expect(retry.request().postDataJSON().command_id).toBe(commandId);
  const sourceId = plan.source_id, effects: string[] = [];
  for (let stage = 0; stage < 3; stage++) {
    plan = await phase(page, sourceId, plan.id, "review"); plan = await phase(page, sourceId, plan.id, "post");
    expect(plan.status).toBe("Posted"); expect(plan.amount_minor).toBe(["10001", "3000", "17002"][stage]);
    await expect(page.getByRole("region", { name: "Native operation", exact: true }).getByRole("heading", { name: "Native operation · Posted", exact: true })).toBeVisible();
    const replied = page.waitForResponse(response => response.url().endsWith(`${root}/plans/${plan.id}/evidence`) && response.request().method() === "GET");
    await page.getByRole("button", { name: "Verify canonical native evidence", exact: true }).click();
    const actual = await replied; expect(actual.status(), await actual.text()).toBe(200); const evidence = (await actual.json()).evidence;
    expect(evidence.source.request.amount_minor).toBe("10001"); expect(evidence.plan.plan_digest).toBe(plan.plan_digest);
    expect(evidence.phases.map((row: { actor_id: string }) => row.actor_id)).toEqual(["erp-maker", "erp-checker", "erp-poster"]);
    expect(new Set(evidence.phases.map((row: { audit_event_id: string }) => row.audit_event_id)).size).toBe(3);
    expect(new Set(evidence.phases.map((row: { outbox_event_id: string }) => row.outbox_event_id)).size).toBe(3);
    expect(evidence.native_effects).toHaveLength(stage === 2 ? 1 : 2);
    for (const [index, native] of evidence.native_effects.entries()) {
      const entry = plan.entries[index]; expect(native.id).toBe(plan.posting_effect_ids[entry.book]); expect(native.entry_id).toBe(entry.entry_id);
      expect(native.validation_digest).toBe(entry.validation_digest); expect(native.posted_actor_id).toBe("erp-poster");
      expect(native.audit_event_id).toBeTruthy(); expect(native.outbox_event_id).toBeTruthy(); effects.push(native.id);
    }
    await expect(page.getByRole("status").filter({ hasText: "Verified original source, plan and native seals" })).toBeVisible();
    const download = page.waitForEvent("download"); await page.getByRole("button", { name: "Download verified evidence", exact: true }).click();
    await (await download).saveAs(`${process.env.RECONFORGE_ERP_BROWSER_ARTIFACTS}/ic-proof-${stage}.json`);
    if (stage === 2) break;
    await login(page, "browser-maker"); await enter(page, sourceId);
    const label = stage === 0 ? "Prepare paired cash settlement" : "Prepare final group adjustment";
    const progress = page.getByRole("form", { name: label, exact: true });
    if (stage === 0) await progress.getByLabel("Cash installment minor units", { exact: true }).fill("3000");
    await progress.getByLabel("Posting date", { exact: true }).fill(stage === 0 ? "2026-10-04" : "2026-10-05");
    await progress.getByLabel("Reason", { exact: true }).fill("Actual reviewed paired cash and final group adjustment");
    await progress.getByRole("combobox", { name: "Fiscal period", exact: true }).selectOption("period");
    const prepared = page.waitForResponse(response => response.url().endsWith(`${root}/sources/${sourceId}/${stage === 0 ? "settlements" : "eliminations"}`) && response.request().method() === "POST");
    await progress.getByRole("button", { name: label, exact: true }).click();
    const response = await prepared; expect(response.status(), await response.text()).toBe(200); plan = (await response.json()).plan;
  }
  expect(new Set(effects).size).toBe(5);
  const reporting = page.getByRole("form", { name: "Verify consolidated native report", exact: true });
  for (const label of ["Reviewed seller map", "Reviewed buyer map", "Reviewed group map"]) await reporting.getByRole("combobox", { name: label, exact: true }).selectOption({ index: 1 });
  await reporting.getByRole("combobox", { name: "Fiscal period", exact: true }).selectOption("period");
  await reporting.getByLabel("Reporting cutoff", { exact: true }).fill("2026-10-05");
  const reported = page.waitForResponse(response => response.url().includes(`${root}/sources/${sourceId}/report?`) && response.request().method() === "GET");
  await reporting.getByRole("button", { name: "Verify consolidated native report", exact: true }).click();
  const actualReport = await reported; expect(actualReport.status(), await actualReport.text()).toBe(200); const report = (await actualReport.json()).report;
  expect(report.effect_count).toBe(5);
  expect([...new Set(report.trial_balance.flatMap((row: { postings: { effect_id: string }[] }) => row.postings.map(line => line.effect_id)))].sort()).toEqual(effects.slice().sort());
  expect(report.trial_balance.every((row: { closing: { balance_minor: string } }) => row.closing.balance_minor === "0")).toBe(true);
  expect(report.income_statement).toEqual({ income_minor: "0", expense_minor: "0", result_minor: "0" });
  expect(report.cash_net_movements).toEqual({ opening_minor: "0", activity_minor: "0", closing_minor: "0" });
  await expect(page.getByRole("status").filter({ hasText: "Verified three-book native report" })).toBeVisible();
  const reportDownload = page.waitForEvent("download"); await page.getByRole("button", { name: "Download verified group report", exact: true }).click();
  await (await reportDownload).saveAs(`${process.env.RECONFORGE_ERP_BROWSER_ARTIFACTS}/ic-group-report.json`);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "Switch language", exact: true }).click();
  await expect(page.getByRole("heading", { name: "عمليات الشركات المرتبطة", exact: true })).toBeVisible();
  const arabicScope = page.getByRole("form", { name: "نطاق المؤسسة", exact: true });
  await expect(arabicScope.getByRole("button", { name: "تطبيق النطاق", exact: true })).toBeEnabled();
  await arabicScope.getByRole("button", { name: "تطبيق النطاق", exact: true }).click();
  await page.getByRole("combobox", { name: "المصادر المحفوظة", exact: true }).selectOption(sourceId);
  await expect(page.getByRole("heading", { name: "BROWSER-IC1", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "التحقق من أدلة القيود الأصلية", exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: "تم التحقق من أختام المصدر والخطة والقيود" })).toBeVisible();
  const arabicDownload = page.waitForEvent("download"); await page.getByRole("button", { name: "تنزيل الأدلة المتحقق منها", exact: true }).click();
  await (await arabicDownload).saveAs(`${process.env.RECONFORGE_ERP_BROWSER_ARTIFACTS}/ic-proof-ar-mobile.json`);
  expect((await new AxeBuilder({ page }).include("#main-content").withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze()).violations).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: `${process.env.RECONFORGE_ERP_BROWSER_ARTIFACTS}/ic-ar-mobile.png`, fullPage: true });
});
