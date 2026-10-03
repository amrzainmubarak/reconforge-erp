import { expect, test, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

const base = process.env.RECONFORGE_AR_UI_BASE_URL;
const password = process.env.RECONFORGE_AR_UI_PASSWORD;
const tenant = process.env.RECONFORGE_AR_UI_TENANT;
const workspace = process.env.RECONFORGE_AR_UI_WORKSPACE;
test.skip(!base || !password || !tenant || !workspace, "PROD012: explicitly provisioned synthetic PostgreSQL HTTPS fixture required; reviewed 2026-10-03");
test.use({ ignoreHTTPSErrors: true });

test("real cookie sessions prepare, submit and independently approve an exact receivable", async ({ page, browser }) => {
  test.setTimeout(90_000);
  const number = `UI-${Date.now()}`;
  async function login(target: Page, username: string) {
    await target.goto(`${base}/receivables`);
    await target.getByLabel("Tenant ID").fill(tenant!);
    await target.getByLabel("Username").fill(username);
    await target.getByLabel("Password", { exact: true }).fill(password!);
    const authentication = target.waitForResponse((response) => response.url().endsWith("/auth/browser/login"));
    await target.getByRole("button", { name: "Sign in", exact: true }).click();
    const response = await authentication;
    expect(response.status()).toBe(200);
    const proof = (await response.json()).csrf_token as string;
    await target.getByRole("combobox", { name: "Authorized workspace", exact: true }).selectOption(workspace!);
    await expect(target.getByRole("heading", { name: "Recorded invoices" })).toBeVisible();
    return proof;
  }
  const proof = await login(page, "maker");
  await page.getByRole("combobox", { name: "Customer", exact: true }).selectOption({ label: "CUS-UI-001 · Synthetic UI customer · USD" });
  await page.getByLabel("Invoice number", { exact: true }).fill(number);
  await page.getByLabel("Invoice date", { exact: true }).fill("2026-10-03");
  await page.getByLabel("Due date", { exact: true }).fill("2026-10-31");
  await page.getByLabel("Line description", { exact: true }).fill("Synthetic reviewed service");
  await page.getByLabel("Quantity", { exact: true }).fill("1.25");
  await page.getByLabel("Unit price · minor units", { exact: true }).fill("10000000000000000");
  await expect(page.getByLabel("Unit price · minor units", { exact: true })).toHaveValue("10000000000000000");
  await page.getByRole("button", { name: "Save draft", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("whole nonnegative minor-unit amount");
  await page.getByLabel("Unit price · minor units", { exact: true }).fill("1001");
  await page.getByLabel("Line tax · minor units", { exact: true }).fill("125");
  await expect(page.getByRole("group", { name: "New invoice draft", exact: true }).locator("..").getByText("1,376 USD · minor units", { exact: true })).toBeVisible();
  const createResponse = page.waitForResponse((response) => response.url().endsWith("/receivables/invoices") && response.request().method() === "POST");
  await page.getByRole("button", { name: "Save draft", exact: true }).click();
  const created = await createResponse;
  expect(created.status()).toBe(200);
  const invoice = await created.json();
  expect(invoice).toMatchObject({ status: "Draft", row_version: 1, total_minor: 1376, subtotal_minor: 1251, tax_minor: 125, created_by: "ar-ui-maker" });
  expect(invoice.lines[0]).toMatchObject({ quantity: "1.25", unit_price_minor: 1001, line_total_minor: 1251, tax_minor: 125 });
  const region = page.getByRole("region", { name: "Invoice review", exact: true });
  await expect(region).toContainText("Draft");
  await page.getByRole("button", { name: "Submit for review", exact: true }).click();
  await expect(region).toContainText("Submitted");
  await expect(page.getByText("A different person must approve this invoice.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Approve invoice", exact: true })).toHaveCount(0);
  const negative = await page.evaluate(async ({ id, tenantId, workspaceId, csrf }) => {
    const headers = { "X-ReconForge-Tenant": tenantId, "X-ReconForge-Workspace": workspaceId, "Content-Type": "application/json" };
    const approve = `/api/v1/receivables/invoices/${encodeURIComponent(id)}/approve`;
    const self = await fetch(approve, { method: "POST", headers: { ...headers, "X-ReconForge-CSRF": csrf }, body: JSON.stringify({ expected_version: 2 }) });
    const noCsrf = await fetch(approve, { method: "POST", headers, body: JSON.stringify({ expected_version: 2 }) });
    const foreign = await fetch("/api/v1/receivables/invoices", { headers: { ...headers, "X-ReconForge-Tenant": "ar-ui-b" } });
    const noScope = await fetch("/api/v1/receivables/invoices", { headers: { "X-ReconForge-Tenant": tenantId } });
    return { self: self.status, noCsrf: noCsrf.status, foreign: foreign.status, noScope: noScope.status };
  }, { id: invoice.id, tenantId: tenant!, workspaceId: workspace!, csrf: proof });
  expect(negative.self).toBe(400);
  expect(negative.noCsrf).toBe(403);
  expect([401, 403]).toContain(negative.foreign);
  expect(negative.noScope).toBe(400);

  const checkerContext = await browser.newContext({ ignoreHTTPSErrors: true });
  try {
    const checker = await checkerContext.newPage();
    const checkerProof = await login(checker, "checker");
    await expect(checker.getByRole("button", { name: "Save draft", exact: true })).toHaveCount(0);
    await checker.getByRole("button", { name: `Review ${number}`, exact: true }).click();
    await checker.getByRole("button", { name: "Approve invoice", exact: true }).click();
    const approvedResponse = checker.waitForResponse((response) => response.url().endsWith(`/${invoice.id}/approve`));
    await checker.getByRole("button", { name: "Confirm approval", exact: true }).click();
    const approved = await approvedResponse;
    expect(approved.status()).toBe(200);
    expect(await approved.json()).toMatchObject({ status: "Approved", row_version: 3, approved_by: "ar-ui-checker", total_minor: 1376 });
    const staleStatus = await checker.evaluate(async ({ id, csrf, tenantId, workspaceId }) => (await fetch(`/api/v1/receivables/invoices/${encodeURIComponent(id)}/approve`, { method: "POST", headers: { "Content-Type": "application/json", "X-ReconForge-Tenant": tenantId, "X-ReconForge-Workspace": workspaceId, "X-ReconForge-CSRF": csrf }, body: JSON.stringify({ expected_version: 2 }) })).status, { id: invoice.id, csrf: checkerProof, tenantId: tenant!, workspaceId: workspace! });
    expect(staleStatus).toBe(400);
    await expect(checker.getByRole("region", { name: "Invoice review", exact: true })).toContainText("Approved");
    const accessibility = await new AxeBuilder({ page: checker }).include("main").withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
    expect(accessibility.violations).toEqual([]);
    await checker.evaluate(() => window.scrollTo(0, 0));
    await checker.screenshot({ path: "../../output/verification-2026-10-03/ar-ui-approved-en.png", fullPage: true });
    await checker.getByRole("button", { name: "Switch language", exact: true }).click();
    await expect(checker.getByRole("main")).toHaveAttribute("dir", "rtl");
    await checker.evaluate(() => window.scrollTo(0, 0));
    await checker.screenshot({ path: "../../output/verification-2026-10-03/ar-ui-approved-ar.png", fullPage: true });
    const arabicAccessibility = await new AxeBuilder({ page: checker }).include("main").withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
    expect(arabicAccessibility.violations).toEqual([]);
    await checker.setViewportSize({ width: 390, height: 844 });
    for (const locale of ["ar", "en"] as const) {
      if (locale === "en") await checker.getByTestId("locale-toggle").click();
      await expect(checker.locator("html")).toHaveAttribute("dir", locale === "ar" ? "rtl" : "ltr");
      // Wait for the actual closed-drawer geometry, including resize/RTL transitions.
      await expect.poll(() => checker.locator("aside.sidebar").evaluate((element) => {
        const rect = element.getBoundingClientRect();
        return rect.right <= 0 || rect.left >= window.innerWidth;
      })).toBe(true);
      expect(await checker.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
      const scrollRegion = checker.getByRole("region", { name: locale === "ar" ? "جدول الفواتير" : "Invoice table", exact: true });
      await expect(scrollRegion).toHaveAttribute("tabindex", "0");
      expect(await scrollRegion.evaluate((element) => element.scrollWidth > element.clientWidth)).toBe(true);
      await scrollRegion.focus();
      await expect(scrollRegion).toBeFocused();
      const before = await scrollRegion.evaluate((element) => element.scrollLeft);
      await checker.keyboard.press(locale === "ar" ? "ArrowLeft" : "ArrowRight");
      await expect.poll(() => scrollRegion.evaluate((element) => element.scrollLeft)).not.toBe(before);
      await checker.keyboard.press("Tab");
      const review = scrollRegion.getByRole("button").first();
      await expect(review).toBeFocused();
      // Native focus must scroll the Review action wholly into the visible region.
      await expect.poll(() => review.evaluate((element) => {
        const button = element.getBoundingClientRect();
        const region = element.closest("[role=region]")!.getBoundingClientRect();
        return button.left >= region.left && button.right <= region.right && button.left >= 0 && button.right <= window.innerWidth;
      })).toBe(true);
      await checker.keyboard.press("Enter");
      await expect(checker.getByRole("region", { name: locale === "ar" ? "مراجعة الفاتورة" : "Invoice review", exact: true })).toBeVisible();
      await checker.evaluate(() => window.scrollTo(0, 0));
      await checker.screenshot({ path: `../../output/verification-2026-10-03/ar-ui-approved-mobile-${locale}.png`, fullPage: true });
    }
  } finally { await checkerContext.close(); }
});
