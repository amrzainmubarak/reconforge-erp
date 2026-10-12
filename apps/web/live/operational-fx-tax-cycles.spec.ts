import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

const base = process.env.RECONFORGE_ERP_LIVE_URL, tenant = process.env.RECONFORGE_ERP_TENANT, password = process.env.RECONFORGE_ERP_PASSWORD;
const root = "/api/v1/operational-fx-tax";
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
  await page.getByRole("navigation", { name: "Primary navigation" }).getByRole("button", { name: "Currency & tax", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Foreign receivables, historical FX and tax", exact: true })).toBeVisible();
  const form = page.getByRole("form", { name: "Apply authorized scope", exact: true });
  for (const [label, value] of Object.entries({ Workspace: "work", Organization: "org", "Legal entity": "entity" })) await form.getByLabel(label, { exact: true }).fill(value);
  await form.getByRole("button", { name: "Apply authorized scope", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Foreign receivable register", exact: true })).toBeVisible();
  if (sourceId) {
    await page.getByRole("combobox", { name: "Foreign receivable register", exact: true }).selectOption(sourceId);
    await expect(page.getByRole("heading", { name: "BROWSER-FX", exact: true })).toBeVisible();
  }
}
async function phase(page: Page, sourceId: string, planId: string, operation: "review" | "post", username: string) {
  await login(page, username); await enter(page, sourceId);
  const region = page.getByRole("region", { name: "Retained operation", exact: true });
  await region.getByLabel("Reason", { exact: true }).fill(`Actual browser independent ${operation}`);
  const reply = page.waitForResponse(response => response.url().endsWith(`${root}/plans/${planId}/${operation}`) && response.request().method() === "POST");
  await region.getByRole("button", { name: operation === "review" ? "Independently review exact plan" : "Post as third human", exact: true }).click();
  const response = await reply; expect(response.status(), await response.text()).toBe(200);
  return (await response.json()).plan;
}

test("real foreign tax source closing valuation inverse partial gain loss native AR closure and bilingual evidence", async ({ page }) => {
  test.setTimeout(360_000);
  expect(base && tenant && password, "Owned HTTPS native fixture must be supplied").toBeTruthy();
  await login(page, "browser-maker"); await enter(page);
  const form = page.getByRole("form", { name: "Prepare foreign invoice", exact: true });
  for (const [label, value] of Object.entries({ "Invoice number": "BROWSER-FX", "Foreign customer code": "FOREIGN", "Foreign currency code": "EUR", "Net invoice amount (foreign minor units)": "10001", "Tax country code": "EG", "Transaction class": "synthetic-service", "Posting date": "2026-10-01", "Due date": "2026-10-31", Reason: "Actual browser retained foreign invoice" })) await form.getByLabel(label, { exact: true }).fill(value);
  await form.getByRole("combobox", { name: "Open accounting period", exact: true }).selectOption("period");
  await form.getByRole("combobox", { name: "Functional journal", exact: true }).selectOption("STOCK");
  for (const [label, value] of Object.entries({ "Functional receivable account": "AR", "Revenue account": "REVENUE", "Functional cash account": "CASH", "Realized FX gain account": "GAIN", "Realized FX loss account": "LOSS" })) await form.getByRole("combobox", { name: label, exact: true }).selectOption(value);
  const rate = form.getByRole("group", { name: "Original historical spot rate", exact: true });
  for (const [label, value] of Object.entries({ "Functional units per foreign unit": "1.25", "Rate observation source": "Browser original spot", "Observed UTC timestamp": "2026-10-01T12:00:00Z" })) await rate.getByLabel(label, { exact: true }).fill(value);
  await form.getByRole("button", { name: "Add tax component", exact: true }).click();
  for (const [label, value] of Object.entries({ "Tax policy identity": "BROWSER-SYNTHETIC-TAX", "Tax policy version": "2026-v1", "Tax fraction of original net": "0.14", "Tax policy source": "Browser reviewed synthetic tax", "Tax effective from": "2026-01-01", "Tax effective to": "2026-12-31" })) await form.getByLabel(label, { exact: true }).fill(value);
  await form.getByRole("combobox", { name: "Tax liability account", exact: true }).selectOption("TAX");
  let lost: Record<string, unknown> | null = null, commandId = "";
  await page.route(`**${root}/invoices`, async route => {
    if (route.request().method() !== "POST") { await route.continue(); return; }
    commandId = route.request().postDataJSON().command_id;
    const response = await route.fetch(); expect(response.status(), await response.text()).toBe(200); lost = (await response.json()).plan;
    await route.abort("failed");
  }, { times: 1 });
  await form.getByRole("button", { name: "Prepare foreign invoice", exact: true }).click();
  await expect(page.getByRole("button", { name: "Retry the same command", exact: true })).toBeVisible();
  expect(commandId).not.toBe("");
  const retry = page.waitForResponse(response => response.url().endsWith(`${root}/invoices`) && response.request().method() === "POST");
  await page.getByRole("button", { name: "Retry the same command", exact: true }).click();
  const response = await retry; expect(response.status(), await response.text()).toBe(200); let plan = (await response.json()).plan;
  expect(plan).toEqual(lost); expect(response.request().postDataJSON().command_id).toBe(commandId);
  const sourceId = plan.source_id as string;
  for (let stage = 0; stage < 5; stage++) {
    plan = await phase(page, sourceId, plan.id, "review", "browser-checker");
    plan = await phase(page, sourceId, plan.id, "post", "browser-poster");
    expect(plan.status).toBe("Posted");
    await expect(page.getByRole("region", { name: "Retained operation", exact: true }).getByRole("heading", { name: "Retained operation · Posted", exact: true })).toBeVisible();
    const evidenceReply = page.waitForResponse(reply => reply.url().endsWith(`${root}/plans/${plan.id}/evidence`) && reply.request().method() === "GET");
    await page.getByRole("button", { name: "Verify source, operation and native journal", exact: true }).click();
    const actual = await evidenceReply; expect(actual.status(), await actual.text()).toBe(200); const proof = (await actual.json()).evidence;
    expect(proof.source.request.original_rate).toEqual({ rate: "1.25", source: "Browser original spot", effective_at: "2026-10-01T12:00:00Z" });
    expect(proof.native_effect.id).toBe(plan.posting_effect_id); expect(proof.native_effect.entry_id).toBe(plan.entry_id);
    expect(proof.native_effect.validation_digest).toBe(plan.validation_digest); expect(proof.plan.plan_digest).toBe(plan.plan_digest);
    expect(proof.totals).toEqual({ debit_minor: ["14251", "5200", "740", "740", "9251"][stage], credit_minor: ["14251", "5200", "740", "740", "9251"][stage] });
    expect(proof.phases.map((row: { actor_id: string }) => row.actor_id)).toEqual(["erp-maker", "erp-checker", "erp-poster", "erp-poster"]);
    expect(new Set(proof.phases.map((row: { audit_event_id: string }) => row.audit_event_id)).size).toBe(4);
    expect(new Set(proof.phases.map((row: { outbox_event_id: string }) => row.outbox_event_id)).size).toBe(4);
    if (stage === 1 || stage === 4) { expect(plan.equation.realized_fx_minor).toBe(stage === 1 ? "200" : "-370"); expect(plan.equation.historical_release_minor).toBe(stage === 1 ? "5000" : "9251"); }
    if (stage === 2 || stage === 3) expect(plan.equation.unrealized_fx_minor).toBe(stage === 2 ? "740" : "-740");
    await expect(page.getByRole("status").filter({ hasText: "Three canonical financial hashes and native human audit references verified in this browser." })).toBeVisible();
    const download = page.waitForEvent("download");
    await page.getByRole("button", { name: "Download verified FX evidence", exact: true }).click();
    await (await download).saveAs(`${process.env.RECONFORGE_ERP_BROWSER_ARTIFACTS}/fx-proof-${stage}.json`);
    if (stage === 4) break;
    await login(page, "browser-maker"); await enter(page, sourceId);
    if (stage === 1 || stage === 2) {
      const reverse = stage === 2, label = reverse ? "Prepare exact valuation reversal" : "Prepare closing valuation";
      const valuation = page.getByRole("form", { name: label, exact: true });
      await valuation.getByLabel("Posting date", { exact: true }).fill(reverse ? "2026-10-04" : "2026-10-03");
      await valuation.getByLabel("Reason", { exact: true }).fill("Actual reviewed closing valuation and exact inverse");
      await valuation.getByRole("combobox", { name: "Open accounting period", exact: true }).selectOption("period");
      if (!reverse) {
        await valuation.getByRole("combobox", { name: "Unrealized FX gain account", exact: true }).selectOption("UGAIN");
        await valuation.getByRole("combobox", { name: "Unrealized FX loss account", exact: true }).selectOption("ULOSS");
        const closing = valuation.getByRole("group", { name: "Retained closing spot rate", exact: true });
        for (const [label, value] of Object.entries({ "Functional units per foreign unit": "1.35", "Rate observation source": "Browser closing spot", "Observed UTC timestamp": "2026-10-03T23:00:00Z" })) await closing.getByLabel(label, { exact: true }).fill(value);
      } else await expect(page.getByRole("form", { name: "Prepare partial foreign receipt", exact: true })).toHaveCount(0);
      const prepared = page.waitForResponse(reply => reply.url().endsWith(`${root}/invoices/${sourceId}/${reverse ? "revaluation-reversals" : "revaluations"}`) && reply.request().method() === "POST");
      await valuation.getByRole("button", { name: label, exact: true }).click();
      const actualPrepare = await prepared; expect(actualPrepare.status(), await actualPrepare.text()).toBe(200); plan = (await actualPrepare.json()).plan;
      continue;
    }
    const settlement = page.getByRole("form", { name: "Prepare partial foreign receipt", exact: true });
    for (const [label, value] of Object.entries({ "Receipt amount (foreign minor units)": stage === 0 ? "4000" : "7401", "Posting date": stage === 0 ? "2026-10-02" : "2026-10-05", Reason: "Actual browser partial original foreign receipt" })) await settlement.getByLabel(label, { exact: true }).fill(value);
    await settlement.getByRole("combobox", { name: "Open accounting period", exact: true }).selectOption("period");
    const spot = settlement.getByRole("group", { name: "Settlement spot rate", exact: true });
    for (const [label, value] of Object.entries({ "Functional units per foreign unit": stage === 0 ? "1.3" : "1.2", "Rate observation source": "Browser settlement spot", "Observed UTC timestamp": stage === 0 ? "2026-10-02T12:00:00Z" : "2026-10-05T12:00:00Z" })) await spot.getByLabel(label, { exact: true }).fill(value);
    const prepared = page.waitForResponse(reply => reply.url().endsWith(`${root}/invoices/${sourceId}/settlements`) && reply.request().method() === "POST");
    await settlement.getByRole("button", { name: "Prepare partial foreign receipt", exact: true }).click();
    const actualPrepare = await prepared; expect(actualPrepare.status(), await actualPrepare.text()).toBe(200); plan = (await actualPrepare.json()).plan;
  }
  await expect(page.getByRole("form", { name: "Prepare partial foreign receipt", exact: true })).toHaveCount(0);
  await page.setViewportSize({ width: 390, height: 844 });
  expect((await new AxeBuilder({ page }).include("#main-content").withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze()).violations).toEqual([]);
  await page.screenshot({ path: `${process.env.RECONFORGE_ERP_BROWSER_ARTIFACTS}/fx-en-390.png`, fullPage: true });
  await page.getByRole("button", { name: "Switch language", exact: true }).click();
  await expect(page.getByRole("heading", { name: "الذمم الأجنبية والعملات التاريخية والضرائب", exact: true })).toBeVisible();
  await page.getByRole("form", { name: "تطبيق النطاق المصرح", exact: true }).getByRole("button", { name: "تطبيق النطاق المصرح", exact: true }).click();
  await page.getByRole("combobox", { name: "سجل الذمم الأجنبية", exact: true }).selectOption(sourceId);
  await expect(page.getByRole("heading", { name: "BROWSER-FX", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "التحقق من المصدر والعملية والقيد الأصلي", exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: "تم التحقق داخل المتصفح من ثلاث بصمات مالية معيارية ومراجع التدقيق البشرية الأصلية." })).toBeVisible();
  const mobileDownload = page.waitForEvent("download");
  await page.getByRole("button", { name: "تنزيل أدلة العملة المتحقق منها", exact: true }).click();
  await (await mobileDownload).saveAs(`${process.env.RECONFORGE_ERP_BROWSER_ARTIFACTS}/fx-proof-ar-mobile.json`);
  expect((await new AxeBuilder({ page }).include("#main-content").withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze()).violations).toEqual([]);
  expect(await page.locator("#main-content").getAttribute("dir")).toBe("rtl");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: `${process.env.RECONFORGE_ERP_BROWSER_ARTIFACTS}/fx-ar-390.png`, fullPage: true });
});
