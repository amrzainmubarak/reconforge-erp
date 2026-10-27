import { expect, test, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { mkdirSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { translate } from "../src/i18n";
import { getBrowserFixture } from "./browser-fixture-access";

const evidence = process.env.RECONFORGE_STUDIO_SHELL_OUT ?? fileURLToPath(new URL("../../../output/assurance-20261026/studio-shell/", import.meta.url));
const testPassword = process.env.RECONFORGE_RELEASE_PRODUCT_TEST_PASSWORD;
if (!testPassword) throw new Error("Missing synthetic browser test password");
async function login(page: Page, username: string) {
  await page.goto("/enterprise-finance");
  const form = page.getByRole("form", { name: "Sign in", exact: true });
  await form.getByLabel("Tenant", { exact: true }).fill((await getBrowserFixture()).tenant);
  await form.getByLabel("Username", { exact: true }).fill(username);
  await form.getByLabel("Password", { exact: true }).fill(testPassword);
  const response = page.waitForResponse(value => new URL(value.url()).pathname === "/api/v1/auth/browser/login");
  await form.getByRole("button", { name: "Sign in", exact: true }).click();
  expect((await response).status()).toBe(200);
  await expect(page.locator(".studio-session-identity")).toContainText(username);
  await expect(page.getByText("Checking your access…", { exact: true })).toHaveCount(0);
}

test("actual authenticated App financial table, responsive navigation, themes, RTL and keyboard drawer", async ({ page }) => {
  test.setTimeout(180000); mkdirSync(evidence, { recursive: true });
  await login(page, "maker");
  const stepUp = page.getByRole("form", { name: "Confirm identity for financial commands" });
  await stepUp.getByLabel("Password", { exact: true }).fill(testPassword);
  const reauthenticated = page.waitForResponse(value => new URL(value.url()).pathname === "/api/v1/auth/step-up");
  await stepUp.getByRole("button", { name: "Confirm identity", exact: true }).click(); expect((await reauthenticated).status()).toBe(200);
  const scope = page.getByRole("form", { name: "Select financial scope" });
  await scope.getByLabel("Workspace", { exact: true }).fill("work");
  await scope.getByLabel("Organization", { exact: true }).fill("org");
  await scope.getByLabel("Legal entity", { exact: true }).fill("entity");
  await scope.getByRole("button", { name: "Apply scope" }).click();
  const report = page.getByRole("form", { name: "Posted trial balance" });
  await report.getByLabel("Fiscal period ID", { exact: true }).fill("period");
  await report.getByLabel("Organization code", { exact: true }).fill("ORG");
  await report.getByLabel("Entity code", { exact: true }).fill("ENTITY");
  await report.getByRole("button", { name: "Load recorded report" }).click();
  await expect(page.getByRole("table", { name: "Posted trial balance" })).toContainText("30.01");
  const measurements: unknown[] = [];
  for (const locale of ["en", "ar"] as const) {
    if (locale === "ar") await page.getByTestId("locale-toggle").click();
    await expect(page.locator("html")).toHaveAttribute("dir", locale === "ar" ? "rtl" : "ltr");
    for (const theme of ["light", "dark"] as const) {
      for (let count = 0; count < 3 && await page.locator("html").getAttribute("data-theme") !== theme; count++) await page.getByRole("button", { name: new RegExp(`^${translate(locale, "theme")}:`) }).click();
      await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
      for (const width of [360, 390, 768, 1024, 1440]) {
        await page.setViewportSize({ width, height: 960 });
        const mobile = width <= 840;
        if (!mobile) await expect(page.locator(".nav-item--active")).toBeVisible();
        const filename = `authenticated-${locale}-${theme}-${width}.png`;
        await page.screenshot({ path: `${evidence}/${filename}`, fullPage: true, animations: "disabled" });
        const overflow = await page.evaluate(() => ({ document: document.documentElement.scrollWidth, viewport: innerWidth }));
        expect(overflow.document).toBeLessThanOrEqual(overflow.viewport);
        const audit = await new AxeBuilder({ page }).include(".topbar").include(".studio-session").include(".sidebar").include(".mobile-dock").include(".studio-page-frame").withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze();
        writeFileSync(`${evidence}/axe-${locale}-${theme}-${width}.json`, JSON.stringify(audit, null, 2));
        expect(audit.violations).toEqual([]);
        measurements.push({ capturedAtUTC: new Date().toISOString(), filename, viewport: { width, height: 960 }, locale, theme, overflow, violations: audit.violations.length, navigationItems: await page.locator(".desktop-navigation .nav-item").count() });
        if (mobile) {
          const menu = page.locator(".mobile-menu-button"); await menu.click();
          const drawer = page.getByRole("dialog", { name: translate(locale, "primaryNavigation") });
          await expect(drawer).toBeVisible();
          await expect(drawer.locator(".nav-item--active")).toBeVisible();
          if (width === 390) await page.screenshot({ path: `${evidence}/drawer-${locale}-${theme}-${width}.png`, animations: "disabled" });
          const close = drawer.getByRole("button", { name: translate(locale, "closeDialog") });
          await expect(close).toBeFocused(); await page.keyboard.press("Shift+Tab");
          expect(await drawer.evaluate(element => element.contains(document.activeElement))).toBe(true);
          await page.keyboard.press("Escape"); await expect(drawer).toHaveCount(0); await expect(menu).toBeFocused();
        }
      }
    }
  }
  writeFileSync(`${evidence}/measurements.json`, JSON.stringify(measurements, null, 2));
});

test("real restricted identity cannot discover denied routes through search or mount a denied deep link", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 960 });
  const restricted = (await getBrowserFixture()).restricted_username;
  if (!restricted) throw new Error("Missing synthetic restricted username");
  await login(page, restricted);
  await expect(page.getByText("Your permissions do not include this workspace.")).toBeVisible();
  await expect(page.getByRole("form", { name: "Select financial scope" })).toHaveCount(0);
  for (const width of [360, 390, 768, 1024, 1440]) {
    await page.setViewportSize({ width, height: 960 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: `${evidence}/restricted-long-identity-${width}.png`, animations: "disabled" });
    if (width <= 840) await expect(page.getByRole("navigation", { name: "Mobile navigation" }).getByRole("button", { name: "Finance & reporting" })).toHaveCount(0);
  }
  const nav = page.getByRole("navigation", { name: "Primary navigation" });
  await expect(nav.getByRole("button", { name: "Finance & reporting", exact: true })).toHaveCount(0);
  await page.getByLabel("Find a workspace", { exact: true }).fill("CRM");
  await expect(nav.getByRole("button", { name: /CRM/ })).toHaveCount(0);
  await expect(page.getByText("No destinations match. Try a different search.")).toBeVisible();
  await page.getByRole("button", { name: "Search controls, pages, or actions" }).click();
  const palette = page.getByRole("dialog", { name: "Command palette" });
  await palette.getByRole("textbox").fill("CRM"); await expect(palette.locator(".command-row")).toHaveCount(0);
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "Sign out of Studio", exact: true }).click();
  await expect(page.locator(".studio-session-identity")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Sign in to Studio" })).toBeVisible();
});
