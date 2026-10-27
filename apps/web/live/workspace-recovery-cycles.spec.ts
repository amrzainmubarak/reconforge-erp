import { expect, test, type Page, type TestInfo } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { writeFile } from "node:fs/promises";

const base = process.env.RECONFORGE_ERP_LIVE_URL;
const tenant = process.env.RECONFORGE_ERP_TENANT;
const password = process.env.RECONFORGE_ERP_PASSWORD;
const source = process.env.RECONFORGE_CUSTOMER_RETURN_SOURCE;
const asset = /\/assets\/CustomerReturnsPage-[A-Za-z0-9_-]+\.js(?:\?.*)?$/;
const financialHeaders = () => ({
  Accept: "application/json", "X-ReconForge-Tenant": tenant!,
  "X-ReconForge-Workspace": "work", "X-ReconForge-Organization": "org", "X-ReconForge-Legal-Entity": "entity",
});
const locales = {
  en: { navigation: "Primary navigation", sales: "Sales & customers", returns: "Customer returns", dashboard: "Dashboard", unavailable: "Workspace unavailable",
    open: "Open dashboard", reload: "Reload page", heading: "Original customer returns and partial refunds", direction: "ltr" },
  ar: { navigation: "التنقل الرئيسي", sales: "المبيعات والعملاء", returns: "مرتجعات العملاء", dashboard: "لوحة المتابعة", unavailable: "مساحة العمل غير متاحة",
    open: "فتح لوحة المتابعة", reload: "إعادة تحميل الصفحة", heading: "إرجاع العميل الأصلي وردّ النقد على دفعات", direction: "rtl" },
} as const;
type ResponsiveCheck = {
  width: number; height: number; direction: "ltr" | "rtl"; overflowPixels: number; seriousCriticalViolationCount: number;
  primaryNavigationAvailable: boolean; usedMobileMenu: boolean; recoveryButtonsVisible: boolean;
};

async function authenticate(page: Page) {
  await page.goto(`${base}/admin-audit`);
  await page.getByLabel("Tenant ID", { exact: true }).fill(tenant!);
  await page.getByLabel("Username", { exact: true }).fill("browser-maker");
  await page.getByLabel("Password", { exact: true }).fill(password!);
  await page.getByRole("button", { name: "Sign in to administration", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Confirm privileged access", exact: true })).toBeVisible();
  await page.getByLabel("Password", { exact: true }).fill(password!);
  const approved = page.waitForResponse(response => response.url().endsWith("/auth/step-up"));
  await page.getByRole("button", { name: "Confirm and continue", exact: true }).click();
  expect((await approved).status()).toBe(200);
}

async function originals(page: Page) {
  const origin = new URL(base!).origin;
  const read = async (path: string): Promise<unknown> => {
    const response = await page.request.get(origin + path, { headers: financialHeaders() });
    expect(response.status(), `Actual scoped financial READ ${path}`).toBe(200);
    return response.json();
  };
  const stock = await read(`/api/v1/stock-sales/orders/${encodeURIComponent(source!)}`);
  const retained = await read("/api/v1/customer-returns/plans");
  expect(retained !== null && typeof retained === "object" && "plans" in retained).toBe(true);
  const plans = (retained as { plans: { id: string; operation: string; phase: number }[] }).plans;
  expect(Array.isArray(plans) && plans.length <= 200).toBe(true);
  const balances: { id: string; original: unknown }[] = [];
  for (const plan of plans) if (plan.operation === "Return" && plan.phase === 2) {
    balances.push({ id: plan.id, original: await read(`/api/v1/customer-returns/plans/${encodeURIComponent(plan.id)}/balance`) });
  }
  return { stock, retained, balances };
}

async function retain(info: TestInfo, name: string, value: unknown) {
  // The owned browser runner places outputPath in its PRIVATE diagnostic tree.
  // No cookies, passwords, headers, request bodies or financial API mocks.
  const path = info.outputPath(name);
  await writeFile(path, JSON.stringify(value, null, 2) + "\n", { flag: "wx" });
  await info.attach(name, { path, contentType: "application/json" });
}

for (const locale of ["en", "ar"] as const) {
  test(`actual rejected lazy workspace preserves ${locale} navigation and manual recovery without financial replay`, async ({ page }, info) => {
    expect(base && tenant && password && source, "Owned native TLS fixture and original source must be supplied").toBeTruthy();
    await authenticate(page);
    const before = await originals(page);
    if (locale === "ar") await page.getByRole("button", { name: "Switch language", exact: true }).click();
    const text = locales[locale];
    const pageErrors: { name: string; message: string; stack: string | null }[] = [];
    const failedRequests: { path: string; method: string; kind: string; failure: string | null }[] = [];
    const mutations: { path: string; method: string }[] = [];
    const abortedAssets: string[] = [];
    const responsiveChecks: ResponsiveCheck[] = [];
    page.on("pageerror", error => pageErrors.push({ name: error.name, message: error.message, stack: error.stack ?? null }));
    page.on("requestfailed", request => failedRequests.push({ path: new URL(request.url()).pathname,
      method: request.method(), kind: request.resourceType(), failure: request.failure()?.errorText ?? null }));
    page.on("request", request => {
      const path = new URL(request.url()).pathname;
      if (path.startsWith("/api/v1/") && !path.startsWith("/api/v1/auth/") && !["GET", "HEAD", "OPTIONS"].includes(request.method())) {
        mutations.push({ path, method: request.method() });
      }
    });
    await page.route(asset, async route => {
      expect(route.request().method()).toBe("GET");
      abortedAssets.push(new URL(route.request().url()).pathname);
      await route.abort("failed");
    }, { times: 1 });
    const navigation = page.getByRole("navigation", { name: text.navigation, exact: true });
    const salesGroup = navigation.locator("summary").filter({ hasText: text.sales });
    let recovered = false;
    try {
      await salesGroup.click();
      await Promise.all([
        page.waitForEvent("requestfailed", request => asset.test(request.url())),
        navigation.getByRole("button", { name: text.returns, exact: true }).click(),
      ]);
      expect(abortedAssets).toHaveLength(1);
      const fallback = page.locator("main#main-content");
      await expect(fallback.getByRole("heading", { name: text.unavailable, exact: true })).toBeVisible();
      await expect(page.getByRole("alert")).toContainText("RF-WORKSPACE-001");
      await expect(fallback).toHaveAttribute("dir", text.direction);
      await expect(navigation).toBeVisible();
      await expect(page.getByRole("button", { name: locale === "en" ? "Switch language" : "تبديل اللغة", exact: true })).toBeVisible();
      expect(mutations).toEqual([]);
      for (const width of [320, 768, 1024, 1440]) {
        await page.setViewportSize({ width, height: 900 });
        await expect(fallback).toHaveAttribute("dir", text.direction);
        const menu = page.locator("header.topbar").getByRole("button", { name: locale === "en" ? "Menu" : "القائمة", exact: true });
        const usedMobileMenu = await menu.isVisible();
        if (usedMobileMenu) { await menu.focus(); await expect(menu).toBeFocused(); await menu.press("Enter"); }
        await expect(navigation).toBeInViewport();
        const primaryNavigationAvailable = await navigation.isVisible();
        if (usedMobileMenu) {
          const close = page.locator("aside.sidebar").getByRole("button", { name: locale === "en" ? "Close dialog" : "إغلاق النافذة", exact: true });
          await close.focus(); await expect(close).toBeFocused(); await close.press("Enter");
        }
        const access = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
        const seriousCriticalViolationCount = access.violations.filter(issue => issue.impact === "serious" || issue.impact === "critical").length;
        const violationIds = access.violations.filter(issue => issue.impact === "serious" || issue.impact === "critical")
          .map(issue => issue.id).filter(id => /^[a-z][a-z0-9-]{0,79}$/.test(id)).slice(0, 32).sort();
        const overflowPixels = await page.evaluate(() => Math.max(0, document.documentElement.scrollWidth - document.documentElement.clientWidth));
        const recoveryButtonsVisible = await fallback.getByRole("button", { name: text.open, exact: true }).isVisible()
          && await fallback.getByRole("button", { name: text.reload, exact: true }).isVisible();
        responsiveChecks.push({ width, height: 900, direction: text.direction, overflowPixels,
          seriousCriticalViolationCount, primaryNavigationAvailable, usedMobileMenu, recoveryButtonsVisible });
        expect(overflowPixels).toBe(0);
        expect(seriousCriticalViolationCount, `Standard Axe rule IDs at ${width}px (${locale}): ${violationIds.join(",")}`).toBe(0);
        expect(primaryNavigationAvailable && recoveryButtonsVisible).toBe(true);
        expect(mutations).toEqual([]); expect(abortedAssets).toHaveLength(1);
      }
      const dashboard = fallback.getByRole("button", { name: text.open, exact: true });
      await dashboard.focus(); await expect(dashboard).toBeFocused(); await dashboard.press("Enter");
      await expect(navigation.getByRole("button", { name: text.dashboard, exact: true })).toHaveAttribute("aria-current", "page");
      await expect(page.getByRole("heading", { name: text.unavailable, exact: true })).toHaveCount(0);
      await salesGroup.click();
      const again = navigation.getByRole("button", { name: text.returns, exact: true });
      await again.focus(); await expect(again).toBeFocused(); await again.press("Enter");
      await expect(fallback.getByRole("heading", { name: text.unavailable, exact: true })).toBeVisible();
      expect(abortedAssets).toHaveLength(1); // Rejected lazy modules cannot be retried just by remounting.
      expect(mutations).toEqual([]);
      const reload = fallback.getByRole("button", { name: text.reload, exact: true });
      await reload.focus(); await expect(reload).toBeFocused();
      const actualAsset = page.waitForResponse(response => asset.test(response.url()) && response.status() === 200);
      await Promise.all([page.waitForNavigation({ waitUntil: "domcontentloaded" }), reload.press("Enter")]);
      await actualAsset;
      await expect(page.getByRole("heading", { name: text.heading, exact: true })).toBeVisible();
      await expect(page.locator("main#main-content")).toHaveAttribute("dir", text.direction);
      await expect(navigation).toBeVisible();
      expect(pageErrors).toEqual([]);
      expect(mutations).toEqual([]);
      recovered = true;
    } finally {
      const after = await originals(page);
      await retain(info, `workspace-recovery-${locale}-original-native-boundary.json`, { schema_version: "workspace-recovery-native-v2",
        locale, injection: "One genuine CustomerReturnsPage JavaScript GET aborted; no API or financial response mocked",
        originalBefore: before, originalAfter: after, pageErrors, failedRequests, abortedAssets, financialMutations: mutations,
        recovered, rawFinancialOriginalsEqual: JSON.stringify(before) === JSON.stringify(after),
        fallbackHeadingCount: await page.getByRole("heading", { name: text.unavailable, exact: true }).count(),
        navigationCount: await navigation.count(), rootMainCount: await page.locator("main#main-content").count(),
        previousBlankScreenCauseProven: false, responsiveChecks });
      expect(after).toEqual(before);
      expect(mutations).toEqual([]);
    }
  });
}
