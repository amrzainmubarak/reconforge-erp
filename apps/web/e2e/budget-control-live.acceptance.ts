import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";

test("populated HTTPS budget workflow persists maker-checker decisions, exact retry and conserved immutable history", async ({ page }) => {
  test.setTimeout(120000);
  const fixture = JSON.parse(readFileSync(resolve("../../output/budget-ui/runtime/fixture.json"), "utf8"));
  const password = "Synthetic-Amr-Budget-Browser-2026!";
  const scope = { workspace_id: fixture.workspace_id, organization_id: fixture.organization_id, legal_entity_id: fixture.legal_entity_id };
  const evidence: Record<string, unknown> = { synthetic_only: true, backend: "SQLite", scope };
  const label = (name: string) => page.getByLabel(name, { exact: true });
  async function signIn(username: string) { await label("Username").fill(username); await label("Password").fill(password); await page.getByRole("button", { name: "Sign in", exact: true }).click(); await expect(label("Workspace ID")).toBeVisible(); }
  async function load() { await label("Workspace ID").fill(scope.workspace_id); await label("Organization ID").fill(scope.organization_id); await label("Legal entity ID").fill(scope.legal_entity_id); await page.getByRole("button", { name: "Load budgets", exact: true }).click(); }
  await page.goto(`${process.env.RECONFORGE_BUDGET_UI_BASE_URL ?? ""}${process.env.RECONFORGE_BUDGET_UI_PATH ?? "/e2e/budget-control-harness.html"}`); await signIn("maker"); await load();
  await label("Budget code").fill("OPS-BROWSER"); await label("Budget name").fill("Synthetic browser operations"); await label("Fiscal period ID").fill(fixture.period_id); await label("Currency code").fill("EGP"); await label("Limit in exact minor units").fill("10000");
  const createdResponse = page.waitForResponse((response) => response.url().endsWith("/budget-control/envelopes") && response.request().method() === "POST");
  await page.getByRole("button", { name: "Create draft", exact: true }).click(); const created = await createdResponse; expect(created.status()).toBe(200); evidence.created = await created.json();
  await expect(page.getByRole("heading", { name: "Budget details · OPS-BROWSER" })).toBeVisible();
  await label("Recorded reason").fill("Synthetic independent review requested"); await page.getByRole("button", { name: "Submit for independent approval", exact: true }).click();
  await expect(page.getByRole("button", { name: "Approve budget", exact: true })).toBeDisabled();
  await page.getByRole("button", { name: "Sign out", exact: true }).click(); await signIn("checker"); await load(); await page.getByRole("button", { name: "Open budget OPS-BROWSER", exact: true }).click();
  await label("Recorded reason").fill("Synthetic independent approval"); await page.getByRole("button", { name: "Approve budget", exact: true }).click();
  await expect(page.getByRole("form", { name: "Commitment command", exact: true })).toBeVisible();
  await label("Recorded reason").fill("Reserve synthetic procurement capacity"); await label("Amount in currency units").fill("٤٠٫٠٠"); await label("Operation date").fill("2026-10-08"); await label("Source reference").fill("PO/SYN/UI/1");
  const writes: string[] = [];
  await page.route("**/api/v1/budget-control/envelopes/*/commitments", async (route) => { writes.push(route.request().postData()!); const result = await route.fetch(); expect(result.status()).toBe(200); evidence.lost_reserve_receipt = await result.json(); await route.abort("failed"); });
  await page.getByRole("button", { name: "Record commitment", exact: true }).click(); await expect(page.getByRole("button", { name: "Retry exact command", exact: true })).toBeEnabled();
  await expect(label("Workspace ID")).toBeDisabled(); await expect(label("Amount in currency units")).toBeDisabled(); await expect(page.getByRole("button", { name: "Reload current balances", exact: true })).toBeDisabled();
  await page.unroute("**/api/v1/budget-control/envelopes/*/commitments"); const retryResponse = page.waitForResponse((response) => response.url().endsWith("/commitments") && response.request().method() === "POST");
  await page.getByRole("button", { name: "Retry exact command", exact: true }).click(); const retried = await retryResponse; expect(retried.status()).toBe(200); expect(retried.request().postData()).toBe(writes[0]); evidence.retry_receipt = await retried.json(); evidence.exact_retry_same_payload = true;
  await expect(page.getByRole("button", { name: "Retry exact command", exact: true })).not.toBeVisible();
  await expect(page.getByRole("region", { name: "Budget details", exact: true })).toContainText("60.00 EGP");
  await page.getByRole("combobox", { name: "Operation", exact: true }).selectOption("Consume"); await label("Recorded reason").fill("Synthetic consumption"); await label("Amount in currency units").fill("15.00"); await page.getByRole("button", { name: "Record commitment", exact: true }).click();
  await expect(page.getByRole("region", { name: "Budget details", exact: true })).toContainText("25.00 EGP");
  await page.getByRole("combobox", { name: "Operation", exact: true }).selectOption("Release"); await label("Recorded reason").fill("Release remaining synthetic capacity"); await label("Amount in currency units").fill("25.00"); await page.getByRole("button", { name: "Record commitment", exact: true }).click();
  await expect(page.getByRole("region", { name: "Budget details", exact: true })).toContainText("85.00 EGP");
  const accessibility = await new AxeBuilder({ page }).include(".budget-control-workspace").analyze(); expect(accessibility.violations).toEqual([]); evidence.accessibility_violations = accessibility.violations;
  await page.setViewportSize({ width: 390, height: 844 }); await page.getByRole("button", { name: "Toggle acceptance language", exact: true }).click(); await expect(page.getByRole("main")).toHaveAttribute("dir", "rtl");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true); evidence.mobile_rtl_no_horizontal_overflow = true;
  const result = await page.evaluate(async ({ selectedScope }) => {
    const headers = { "X-ReconForge-Tenant": "local", "X-ReconForge-Workspace": selectedScope.workspace_id, "X-ReconForge-Organization": selectedScope.organization_id, "X-ReconForge-Legal-Entity": selectedScope.legal_entity_id };
    const query = new URLSearchParams({ ...selectedScope, limit: "25", offset: "0" });
    const listed = await (await fetch(`/api/v1/budget-control/envelopes?${query}`, { headers })).json();
    const budget = listed.envelopes[0];
    const detail = await (await fetch(`/api/v1/budget-control/envelopes/${budget.id}?${new URLSearchParams(selectedScope)}`, { headers })).json();
    const foreign = await fetch(`/api/v1/budget-control/envelopes/${budget.id}?${new URLSearchParams({ ...selectedScope, legal_entity_id: "foreign-entity" })}`, { headers });
    const noCsrf = await fetch(`/api/v1/budget-control/envelopes/${budget.id}/commitments`, { method: "POST", headers: { ...headers, "Content-Type": "application/json" }, body: JSON.stringify({ ...selectedScope, expected_version: budget.row_version, command_id: "no-csrf", reason: "Synthetic denied", operation: "Reserve", amount_minor: "1", source_reference: "DENIED", operation_date: "2026-10-08" }) });
    return { detail, foreign_status: foreign.status, no_csrf_status: noCsrf.status };
  }, { selectedScope: scope });
  expect(result.detail).toMatchObject({ status: "Approved", row_version: 6, limit_minor: "10000", reserved_minor: "0", consumed_minor: "1500", available_minor: "8500" }); expect(result.detail.events).toHaveLength(3); expect(result.foreign_status).toBe(409); expect(result.no_csrf_status).toBe(403);
  evidence.final = result; writeFileSync(resolve("../../output/budget-ui/runtime/browser-evidence.json"), JSON.stringify(evidence, null, 2));
  await page.reload(); await signIn("checker"); await load(); await page.getByRole("button", { name: "Open budget OPS-BROWSER", exact: true }).click(); await expect(page.getByRole("region", { name: "Budget details", exact: true })).toContainText("85.00 EGP");
});
