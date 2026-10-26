import { expect, test, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
interface Fixture { tenant: string; password: string; employee_id: string }
const fixture = (): Fixture => JSON.parse(readFileSync(fileURLToPath(new URL("../../../output/release-blocker-20261025/agent-c/browser-fixture.json", import.meta.url)), "utf8"));
async function login(page: Page, user: string) {
  const source = fixture();
  await page.getByLabel("Tenant ID", { exact: true }).fill(source.tenant); await page.getByLabel("Username", { exact: true }).fill(user); await page.getByLabel("Password", { exact: true }).fill(source.password);
  const response = page.waitForResponse(value => new URL(value.url()).pathname === "/api/v1/auth/browser/login");
  await page.getByRole("button", { name: "Sign in", exact: true }).click(); expect((await response).status()).toBe(200);
  const step = page.waitForResponse(value => new URL(value.url()).pathname === "/api/v1/auth/step-up"); await page.getByRole("button", { name: "Confirm privileged access" }).click(); expect((await step).status()).toBe(200);
}
async function scope(page: Page) { await page.getByLabel("Workspace ID", { exact: true }).fill("work"); await page.getByLabel("Organization ID", { exact: true }).fill("org"); await page.getByLabel("Legal entity ID", { exact: true }).fill("entity"); }
async function logout(page: Page) { const response = page.waitForResponse(value => new URL(value.url()).pathname === "/api/v1/auth/logout"); await page.getByRole("button", { name: "Sign out", exact: true }).click(); expect((await response).status()).toBe(200); }
const result = (page: Page) => page.getByRole("region", { name: "Verified server response" });
async function output(page: Page, label: string) { return (await result(page).getByText(label, { exact: true }).locator("..").locator("dd").innerText()).trim(); }

test("native authenticated HCM, CRM and canonical project posting journeys", async ({ page }) => {
  test.setTimeout(120000);
  await page.goto("/e2e/release-product-harness.html");
  await login(page, "maker"); await scope(page);
  await page.getByLabel("Request ID", { exact: true }).fill("REQ-BROWSER"); await page.getByLabel("Employee ID", { exact: true }).fill(fixture().employee_id); await page.getByLabel("Start date", { exact: true }).fill("2026-11-01"); await page.getByLabel("End date", { exact: true }).fill("2026-11-03"); await page.getByLabel("Requested days", { exact: true }).fill("3"); await page.getByLabel("Reason", { exact: true }).fill("Synthetic native browser acceptance");
  await page.getByRole("button", { name: "Submit request", exact: true }).click(); await expect(result(page)).toContainText("Submitted");
  const selfApproval = page.waitForResponse(value => new URL(value.url()).pathname.endsWith("/REQ-BROWSER/approve")); await page.getByRole("button", { name: "Approve request", exact: true }).click(); expect((await selfApproval).status()).toBe(400); await expect(page.getByRole("alert")).toContainText("There is no confirmed result"); await expect(result(page)).toHaveCount(0);
  await logout(page); await login(page, "checker");
  await page.getByRole("button", { name: "Approve request", exact: true }).click(); await expect(result(page)).toContainText("Approved");
  await page.getByRole("button", { name: "Load entitlement balance", exact: true }).click(); await expect(result(page)).toContainText("Available days"); expect(await output(page, "Available days")).toBe("18");
  await page.getByLabel("Employee ID", { exact: true }).fill("CHANGED-EMPLOYEE"); await expect(result(page)).toHaveCount(0);
  await page.getByLabel("Employee ID", { exact: true }).fill(fixture().employee_id);
  await page.getByRole("button", { name: "CRM", exact: true }).click(); await scope(page); await page.getByLabel("Quotation ID", { exact: true }).fill("Q-BROWSER"); await page.getByRole("button", { name: "Load quotation", exact: true }).click(); await expect(result(page)).toContainText("submitted");
  await page.getByRole("button", { name: "Approve quotation", exact: true }).click(); await expect(result(page)).toContainText("approved"); expect(await output(page, "Approved by")).toBe("checker");
  await page.getByLabel("Contract ID", { exact: true }).fill("C-BROWSER"); await page.getByLabel("Suspension reason", { exact: true }).fill("Synthetic native browser control"); await page.getByRole("button", { name: "Suspend contract", exact: true }).click(); await expect(result(page)).toContainText("suspended");
  await page.getByLabel("Suspension reason", { exact: true }).fill("Changed synthetic control reason"); await expect(result(page)).toHaveCount(0);
  await page.getByRole("button", { name: "Resume contract", exact: true }).click(); await expect(result(page)).toContainText("active");
  await page.getByRole("button", { name: "Project", exact: true }).click(); await scope(page); await page.getByLabel("Milestone ID", { exact: true }).fill("MS-BROWSER"); await page.getByRole("button", { name: "Verify deliverable", exact: true }).click(); await expect(result(page)).toContainText("checker");
  await logout(page); await login(page, "maker");
  for (const [label, value] of [["Invoice ID", "INV-BROWSER"], ["Issue timestamp (UTC)", "2026-10-25T00:00:00Z"], ["Customer code", "CUSTOMER"], ["Organization code", "ORG"], ["Entity code", "ENTITY"], ["Fiscal period ID", "period"], ["Posting date", "2026-10-25"], ["Journal code", "STOCK"], ["Command ID (reuse for retry)", "BROWSER-PREPARE"]]) await page.getByLabel(label, { exact: true }).fill(value);
  await page.getByRole("button", { name: "Prepare invoice draft", exact: true }).click(); await expect(result(page)).toContainText("Draft"); const binding = await output(page, "Financial binding ID"), digest = await output(page, "Source digest"); expect(await output(page, "Amount (minor units)")).toBe("3001");
  await page.getByLabel("Invoice ID", { exact: true }).fill("CHANGED-INVOICE"); await expect(result(page)).toHaveCount(0);
  await page.getByLabel("Invoice ID", { exact: true }).fill("INV-BROWSER");
  await page.getByRole("button", { name: "Prepare invoice draft", exact: true }).click(); await expect(result(page)).toContainText(binding);
  await page.getByLabel("Financial binding ID", { exact: true }).fill(binding); await page.getByLabel("Expected source digest", { exact: true }).fill(digest); await page.getByLabel("Command ID (reuse for retry)", { exact: true }).fill("BROWSER-SELF-REVIEW"); await page.getByRole("button", { name: "Review financial draft", exact: true }).click(); await expect(page.getByRole("alert")).toBeVisible(); await expect(result(page)).toHaveCount(0);
  await logout(page); await login(page, "checker"); await page.getByLabel("Command ID (reuse for retry)", { exact: true }).fill("BROWSER-REVIEW"); await page.getByRole("button", { name: "Review financial draft", exact: true }).click(); await expect(result(page)).toContainText("Reviewed");
  await logout(page); await login(page, "poster"); await page.getByLabel("Command ID (reuse for retry)", { exact: true }).fill("BROWSER-POST"); await page.getByRole("button", { name: "Post reviewed entry", exact: true }).click(); await expect(result(page)).toContainText("Posted"); expect(await output(page, "Financial binding ID")).toBe(binding);
  await page.getByRole("button", { name: "Load financial binding", exact: true }).click(); await expect(result(page)).toContainText("Posted");
  const cookies = await page.context().cookies(); expect(cookies.find(cookie => cookie.name === "__Host-reconforge_session")).toMatchObject({ httpOnly: true, secure: true, sameSite: "Strict" });
});

test("native Arabic mobile views reject foreign scope and satisfy focused accessibility checks", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 }); await page.goto("/e2e/release-product-harness.html"); await login(page, "checker"); await scope(page);
  await page.getByRole("button", { name: "Toggle language" }).click(); await expect(page.locator(".financial-reporting")).toHaveAttribute("dir", "rtl");
  await page.getByLabel("رقم الطلب", { exact: true }).fill("REQ-BROWSER"); await page.getByLabel("مساحة العمل", { exact: true }).fill("foreign-workspace");
  const denied = page.waitForResponse(value => new URL(value.url()).pathname.endsWith("/requests/REQ-BROWSER")); await page.getByRole("button", { name: "عرض الطلب", exact: true }).click(); expect((await denied).status()).toBe(403); await expect(page.getByRole("alert")).toContainText("لا توجد نتيجة مؤكدة"); await expect(page.getByRole("region", { name: "النتيجة الموثقة من الخادم" })).toHaveCount(0);
  for (const view of ["HCM", "CRM", "Project"]) { await page.getByRole("button", { name: view, exact: true }).click(); await expect(page.locator(".financial-reporting")).toHaveAttribute("dir", "rtl"); const audit = await new AxeBuilder({ page }).include(".financial-reporting").withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze(); expect(audit.violations).toEqual([]); expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true); }
  await logout(page); await expect(page.getByRole("button", { name: "ترحيل القيد المراجع", exact: true })).toBeDisabled();
});
