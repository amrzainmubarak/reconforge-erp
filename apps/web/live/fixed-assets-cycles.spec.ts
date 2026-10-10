import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

const base = process.env.RECONFORGE_ERP_LIVE_URL, tenant = process.env.RECONFORGE_ERP_TENANT, password = process.env.RECONFORGE_ERP_PASSWORD;
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
async function enter(page: Page, assetId = "") {
  await page.getByRole("navigation", { name: "Primary navigation" }).getByRole("button", { name: "Fixed assets", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Fixed assets", exact: true })).toBeVisible();
  const form = page.getByRole("form", { name: "Apply scope", exact: true });
  for (const [label, value] of Object.entries({ Workspace: "work", Organization: "org", "Legal entity": "entity" })) await form.getByLabel(label, { exact: true }).fill(value);
  await form.getByRole("button", { name: "Apply scope", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Asset register", exact: true })).toBeVisible();
  if (assetId) {
    await page.getByRole("combobox", { name: "Asset register", exact: true }).selectOption(assetId);
    await expect(page.getByRole("heading", { name: "BROWSER-ASSET · Browser production equipment", exact: true })).toBeVisible();
  }
}
async function phase(page: Page, assetId: string, planId: string, operation: "review" | "post", username: string) {
  await login(page, username); await enter(page, assetId);
  const region = page.getByRole("region", { name: "Retained plan digest", exact: true });
  await region.getByLabel("Reason", { exact: true }).fill(`Actual browser independent ${operation}`);
  const response = page.waitForResponse(reply => reply.url().endsWith(`/fixed-assets/plans/${planId}/${operation}`) && reply.request().method() === "POST");
  await region.getByRole("button", { name: operation === "review" ? "Review operation" : "Post operation", exact: true }).click();
  const actual = await response; expect(actual.status(), await actual.text()).toBe(200);
  return (await actual.json()).plan;
}
test("real acquisition cumulative depreciation disposal immutable retry and bilingual financial evidence", async ({ page }) => {
  test.setTimeout(240_000);
  expect(base && tenant && password, "Owned HTTPS native fixture must be supplied").toBeTruthy();
  await login(page, "browser-maker"); await enter(page);
  const acquisition = page.getByRole("form", { name: "Prepare acquisition", exact: true });
  for (const [label, value] of Object.entries({ "Asset number": "BROWSER-ASSET", "Asset name": "Browser production equipment", "Acquisition cost": "101.01", "Salvage value": "10.01", "Useful life in months": "3", "Posting date": "2026-10-01", "In-service date": "2026-10-01", Reason: "Actual browser production equipment acquisition" })) await acquisition.getByLabel(label, { exact: true }).fill(value);
  await acquisition.getByRole("combobox", { name: "Open fiscal period", exact: true }).selectOption("period");
  await acquisition.getByRole("combobox", { name: "Journal", exact: true }).selectOption("STOCK");
  for (const [label, value] of Object.entries({ "Historical cost account": "FIXED", "Accumulated depreciation account": "ACCUM", "Depreciation expense account": "DEPRECIATION", "Cash account": "CASH", "Disposal gain account": "GAIN", "Disposal loss account": "LOSS" })) await acquisition.getByRole("combobox", { name: label, exact: true }).selectOption(value);
  let lost: Record<string, unknown> | null = null, commandId = "";
  await page.route("**/api/v1/fixed-assets/assets", async route => {
    if (route.request().method() !== "POST") { await route.continue(); return; }
    commandId = route.request().postDataJSON().command_id;
    const response = await route.fetch(); expect(response.status()).toBe(200); lost = (await response.json()).plan;
    await route.abort("failed");
  }, { times: 1 });
  await acquisition.getByRole("button", { name: "Prepare acquisition", exact: true }).click();
  await expect(page.getByRole("button", { name: "Retry the retained command", exact: true })).toBeVisible();
  expect(commandId).not.toBe("");
  const retry = page.waitForResponse(reply => reply.url().endsWith("/fixed-assets/assets") && reply.request().method() === "POST");
  await page.getByRole("button", { name: "Retry the retained command", exact: true }).click();
  const response = await retry; expect(response.status()).toBe(200); let plan = (await response.json()).plan;
  expect(plan).toEqual(lost); expect(response.request().postDataJSON().command_id).toBe(commandId);
  const assetId = plan.asset_id as string;
  for (let stage = 0; stage < 4; stage++) {
    plan = await phase(page, assetId, plan.id, "review", "browser-checker");
    plan = await phase(page, assetId, plan.id, "post", "browser-poster");
    expect(plan.status).toBe("Posted");
    await expect(page.getByRole("region", { name: "Retained plan digest", exact: true }).getByRole("heading", { name: "Posted", exact: true })).toBeVisible();
    const evidenceReply = page.waitForResponse(reply => reply.url().endsWith(`/fixed-assets/plans/${plan.id}/evidence`) && reply.request().method() === "GET");
    await page.getByRole("button", { name: "Verify source and ledger evidence", exact: true }).click();
    const evidenceResponse = await evidenceReply;
    expect(evidenceResponse.status(), await evidenceResponse.text()).toBe(200);
    const proof = (await evidenceResponse.json()).evidence;
    expect(proof.native_effect.id).toBe(plan.posting_effect_id);
    expect(proof.native_effect.entry_id).toBe(plan.entry_id);
    expect(proof.native_effect.validation_digest).toBe(plan.validation_digest);
    expect(proof.plan.plan_digest).toBe(plan.plan_digest);
    expect(proof.totals).toEqual({ debit_minor: ["10101", "3033", "6067", "10600"][stage], credit_minor: ["10101", "3033", "6067", "10600"][stage] });
    expect(proof.phases.map((row: { actor_id: string }) => row.actor_id)).toEqual(["erp-maker", "erp-checker", "erp-poster", "erp-poster"]);
    expect(new Set(proof.phases.map((row: { audit_event_id: string }) => row.audit_event_id)).size).toBe(4);
    expect(new Set(proof.phases.map((row: { outbox_event_id: string }) => row.outbox_event_id)).size).toBe(4);
    await expect(page.getByRole("status").filter({ hasText: "Source definition, retained operation and native journal hashes verified in this browser." })).toBeVisible();
    const download = page.waitForEvent("download");
    await page.getByRole("button", { name: "Download verified evidence", exact: true }).click();
    await (await download).saveAs(`${process.env.RECONFORGE_ERP_BROWSER_ARTIFACTS}/fixed-asset-proof-${stage}.json`);
    if (stage === 3) break;
    await login(page, "browser-maker"); await enter(page, assetId);
    const operation = page.getByRole("region", { name: "Asset operations", exact: true });
    await operation.getByRole("combobox", { name: "Open fiscal period", exact: true }).selectOption(stage === 0 ? "nov" : "jan");
    await operation.getByLabel("Posting date", { exact: true }).fill(stage === 0 ? "2026-11-01" : stage === 1 ? "2027-01-01" : "2027-01-02");
    await operation.getByLabel("Reason", { exact: true }).fill("Actual browser retained asset accounting");
    if (stage < 2) await operation.getByLabel("Completed service month", { exact: true }).fill(stage === 0 ? "2026-10" : "2026-12");
    else await operation.getByLabel("Disposal proceeds", { exact: true }).fill("15.00");
    const prepared = page.waitForResponse(reply => reply.url().endsWith(`/fixed-assets/assets/${assetId}/operations`) && reply.request().method() === "POST");
    await operation.getByRole("button", { name: stage === 2 ? "Prepare disposal" : "Prepare depreciation", exact: true }).click();
    const actual = await prepared; expect(actual.status(), await actual.text()).toBe(200); plan = (await actual.json()).plan;
    expect(plan.amount_minor).toBe(["3033", "6067", "1001"][stage]);
  }
  await expect(page.getByText("Disposed", { exact: true })).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  expect((await new AxeBuilder({ page }).include("#main-content").withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze()).violations).toEqual([]);
  await page.screenshot({ path: `${process.env.RECONFORGE_ERP_BROWSER_ARTIFACTS}/fixed-assets-en-390.png`, fullPage: true });
  await page.getByRole("button", { name: "Switch language", exact: true }).click();
  await expect(page.getByRole("heading", { name: "الأصول الثابتة", exact: true })).toBeVisible();
  const scope = page.getByRole("form", { name: "تطبيق النطاق", exact: true });
  await scope.getByRole("button", { name: "تطبيق النطاق", exact: true }).click();
  await page.getByRole("combobox", { name: "سجل الأصول", exact: true }).selectOption(assetId);
  await expect(page.getByText("مستبعد", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "التحقق من أدلة المصدر والقيد", exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: "تم التحقق من بصمات تعريف المصدر والعملية المحفوظة والقيد الأصلي داخل هذا المتصفح." })).toBeVisible();
  expect((await new AxeBuilder({ page }).include("#main-content").withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze()).violations).toEqual([]);
  expect(await page.locator("#main-content").getAttribute("dir")).toBe("rtl");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: `${process.env.RECONFORGE_ERP_BROWSER_ARTIFACTS}/fixed-assets-ar-390.png`, fullPage: true });
});
