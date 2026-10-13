import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { createHash } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";

test("actual selected original group diagnostic unchanged bytes Arabic mobile and native bridge", async ({ page }) => {
  test.setTimeout(180_000);
  const base = process.env.RECONFORGE_ERP_LIVE_URL, tenant = process.env.RECONFORGE_ERP_TENANT, password = process.env.RECONFORGE_ERP_PASSWORD, artifacts = process.env.RECONFORGE_ERP_BROWSER_ARTIFACTS;
  expect(base && tenant && password && artifacts, "Owned synthetic HTTPS fixture must be supplied").toBeTruthy();
  const mutations: string[] = [];
  const captureReads: { endpoint: string; source_id: string; status: number }[] = [];
  page.on("request", request => { if (request.url().includes("/api/v1/intercompany-") && request.method() !== "GET") mutations.push(request.method() + " " + new URL(request.url()).pathname); });
  await page.goto(`${base}/intercompany-group-diagnostic`);
  await expect(page.getByRole("heading", { name: "Selected-source group reporting diagnostic", exact: true })).toBeVisible();
  await page.getByLabel("Tenant", { exact: true }).fill(tenant!); await page.getByLabel("Username", { exact: true }).fill("browser-poster"); await page.getByLabel("Password", { exact: true }).fill(password!);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  const scope = page.getByRole("form", { name: "Apply organization scope", exact: true });
  await expect(scope.getByLabel("Workspace", { exact: true })).toBeEnabled(); await scope.getByLabel("Workspace", { exact: true }).fill("work"); await scope.getByLabel("Organization", { exact: true }).fill("org");
  await scope.getByRole("button", { name: "Apply organization scope", exact: true }).click();
  const selected = page.getByLabel("Original paired trade", { exact: true }), sourceIds: string[] = [];
  for (const [index, reference] of ["DIAGNOSTIC-BROWSER-GROUP-ONE", "DIAGNOSTIC-BROWSER-GROUP-TWO"].entries()) {
    const option = selected.getByRole("option").filter({ hasText: reference }); await expect(option).toHaveCount(1);
    const id = await option.getAttribute("value"); expect(id).toMatch(/^IC2S-[0-9a-f]{32}$/); sourceIds.push(id!);
    await selected.selectOption(id!);
    const opening = page.getByLabel("I explicitly select the known zero opening for this complete source membership.", { exact: true });
    await expect(opening).not.toBeChecked(); await expect(page.getByRole("button", { name: "Capture and add original source", exact: true })).toBeDisabled();
    await opening.check();
    // Capture includes all original native phase proofs and completes only
    // after this exact source's final current-authorized Cashflow body. Keep
    // the existing 15s action budget and 5s verified-heading assertion.
    const captured = page.waitForResponse(response => new URL(response.url()).pathname === `/api/v1/intercompany-source-cashflow/sources/${id}` && response.request().method() === "GET", { timeout: 15_000 });
    await page.getByRole("button", { name: "Capture and add original source", exact: true }).click();
    const response = await captured;
    captureReads.push({ endpoint: new URL(response.url()).pathname, source_id: id!, status: response.status() });
    await writeFile(join(artifacts!, "group-diagnostic-source-capture-reads.json"), JSON.stringify(captureReads));
    expect(response.status()).toBe(200);
    const currentCash = await response.json();
    expect(currentCash.qualified_scope.tenant_id).toBe(tenant); expect(currentCash.cashflow.source_id).toBe(id);
    expect(currentCash.cashflow.opening_minor).toBe("0"); expect(currentCash.cashflow.elimination_plan_id).toMatch(/^IC2E-[0-9a-f]{32}$/);
    await expect(page.getByRole("heading", { name: `Selected original sources · ${index + 1}/16`, exact: true })).toBeVisible();
  }
  const viewed = page.waitForResponse(response => new URL(response.url()).pathname === "/api/v1/intercompany-group-diagnostic/report");
  await page.getByRole("button", { name: "Verify selected group membership", exact: true }).click();
  const originalView = await viewed; expect(originalView.status(), await originalView.text()).toBe(200); const view = await originalView.json();
  const diagnostic = view.diagnostic;
  expect(diagnostic.qualified_scope.tenant_id).toBe(tenant); expect(diagnostic.selection.pins).toHaveLength(2);
  expect(diagnostic.selection.pins.map((pin: { opening: { source_id: string } }) => pin.opening.source_id)).toEqual([...sourceIds].sort());
  expect(diagnostic.selection.pins.every((pin: { opening: { seller_minor: string; buyer_minor: string; basis: string } }) => pin.opening.seller_minor === "0" && pin.opening.buyer_minor === "0" && pin.opening.basis === "complete-native-source-origin-membership")).toBe(true);
  expect(diagnostic.source_members).toHaveLength(2);
  expect(diagnostic.source_members.flatMap((source: { source_effect_ids: string[]; native_adjustment_effect_ids: string[] }) => [...source.source_effect_ids, ...source.native_adjustment_effect_ids])).toHaveLength(14);
  expect(diagnostic.cash_equation).toEqual({ opening_minor: "0", operating_net_minor: "0", fx_on_cash_minor: "202", closing_minor: "202" });
  const cash = diagnostic.trial_balance_bridge.find((row: { role: string }) => row.role === "cash");
  expect([cash.translated_minor, cash.native_adjustment_minor, cash.combined_minor]).toEqual(["202", "0", "202"]);
  expect(diagnostic.income_statement.result_minor).toBe("784"); expect(diagnostic.balance_sheet.equity_minor).toBe("-582");
  expect(diagnostic.formal_close_workflow_assessed).toBe(false); expect(diagnostic.whole_group_membership_proven).toBe(false); expect(diagnostic.financial_writes).toBe(false);
  expect(diagnostic.native_period_observations.length).toBeGreaterThan(0); expect(diagnostic.native_period_observations.every((period: { tenant_id: string; application_workspace_id: string; status: string }) => period.tenant_id === tenant && period.application_workspace_id === "work" && period.status === "Open")).toBe(true);
  await expect(page.getByRole("heading", { name: "Reporting and native adjustment bridge", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Observed native fiscal periods", exact: true })).toBeVisible();
  await expect(page.getByRole("region", { name: "Reporting and native adjustment bridge", exact: true })).toHaveAttribute("tabindex", "0");
  await writeFile(join(artifacts!, "group-diagnostic-view.json"), JSON.stringify(view));
  const exported = page.waitForResponse(response => new URL(response.url()).pathname === "/api/v1/intercompany-group-diagnostic/evidence"), downloaded = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download unchanged original bytes", exact: true }).click();
  const originalWire = await exported, wireHeaders = originalWire.headers();
  await writeFile(join(artifacts!, "group-diagnostic-original-wire.json"), JSON.stringify({ status: originalWire.status(), content_type: wireHeaders["content-type"], content_length: wireHeaders["content-length"], original_sha256: wireHeaders["x-reconforge-evidence-sha256"] }));
  expect(originalWire.status()).toBe(200); expect(wireHeaders["content-length"]).toBe(String(view.evidence_bytes)); expect(wireHeaders["x-reconforge-evidence-sha256"]).toBe(view.evidence_sha256);
  const path = join(artifacts!, "group-diagnostic-original.json"); await (await downloaded).saveAs(path);
  const raw = await readFile(path); expect(raw.length).toBe(view.evidence_bytes); expect(createHash("sha256").update(raw).digest("hex")).toBe(view.evidence_sha256);
  await expect(page.getByText("Original raw bytes verified and downloaded", { exact: true })).toBeVisible();
  expect((await new AxeBuilder({ page }).include("#main-content").withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze()).violations).toEqual([]);
  await page.setViewportSize({ width: 390, height: 844 }); await page.getByRole("button", { name: "Switch language", exact: true }).click();
  await expect(page.getByRole("heading", { name: "تشخيص تقارير المجموعة للمصادر المحددة", exact: true })).toBeVisible(); await expect(page.getByRole("main")).toHaveAttribute("dir", "rtl");
  await expect(page.getByRole("heading", { name: "جسر التقرير والتعديل الأصلي", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "الفترات المالية الأصلية المرصودة", exact: true })).toBeVisible();
  expect((await new AxeBuilder({ page }).include("#main-content").withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze()).violations).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true); await page.screenshot({ path: join(artifacts!, "group-diagnostic-ar-mobile.png"), fullPage: true });
  expect(mutations).toEqual([]);
  await writeFile(join(artifacts!, "group-diagnostic-browser-read-boundary.json"), JSON.stringify({ selected_source_ids: [...sourceIds].sort(), native_sources_provisioned_by: "governed-native-fixture-three-distinct-test-human-principals", browser_financial_writes: false, intercompany_mutations: mutations, original_sha256: view.evidence_sha256, original_bytes: view.evidence_bytes, independent_FX_conversion_by_browser: false, formal_close_workflow_assessed: false, whole_group_membership_proven: false, statutory_country_packs: 0, performance_comparison_accepted: false }));
});
