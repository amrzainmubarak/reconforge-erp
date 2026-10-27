import { expect, test } from "@playwright/test";
import { translate } from "../src/i18n";

test("desktop search remains usable after switching language on mobile", async ({ page }) => {
  await page.goto("/");
  const search = page.getByRole("searchbox", { name: "Find a workspace", exact: true });
  await search.fill("Inventory controls");
  await page.getByRole("navigation", { name: "Primary navigation", exact: true }).getByRole("button", { name: "Inventory controls", exact: true }).click();
  await expect(search).toHaveValue("");
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "Switch language", exact: true }).click();
  await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
  await page.getByTestId("locale-toggle").click();
  await page.setViewportSize({ width: 1440, height: 900 });
  await search.fill("Finance & reporting");
  await expect(search).toHaveValue("Finance & reporting");
  await expect(page.getByRole("navigation", { name: "Primary navigation", exact: true }).getByRole("button", { name: "Finance & reporting", exact: true })).toBeVisible();
});

for (const locale of ["en", "ar"] as const) for (const { width, collapsed } of [{ width: 1024, collapsed: false }, { width: 1440, collapsed: false }, { width: 1440, collapsed: true }]) test(`an open ${locale} mobile drawer releases focus at ${width}px (collapsed=${collapsed})`, async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  if (collapsed) await page.addInitScript(() => localStorage.setItem("reconforge.studio.sidebar-collapsed", "true"));
  await page.goto("/");
  if (locale === "ar") await page.getByTestId("locale-toggle").click();
  const menu = page.getByRole("banner").getByRole("button", { name: translate(locale, "menu"), exact: true });
  await page.evaluate(() => { document.body.style.overflow = "auto"; });
  await menu.click();
  const sidebar = page.locator("aside.sidebar");
  await expect(sidebar).toHaveAttribute("role", "dialog");
  await expect(sidebar).toHaveAttribute("aria-modal", "true");
  expect(await page.evaluate(() => document.body.style.overflow)).toBe("hidden");

  const search = sidebar.getByRole("searchbox", { name: translate(locale, "navFilter"), exact: true });
  await search.focus();
  await page.setViewportSize({ width, height: 900 });
  await expect(sidebar).not.toHaveAttribute("aria-modal");
  await expect(sidebar).not.toHaveAttribute("role", "dialog");
  await expect.poll(() => page.evaluate(() => document.body.style.overflow)).toBe("auto");
  if (width === 1024 || collapsed) await expect(sidebar.locator('[aria-current="page"]')).toBeFocused();
  else await expect(search).toBeFocused();
  const controls = sidebar.locator('button:not([disabled]), a[href], input, summary');
  const lastVisibleIndex = await controls.evaluateAll(elements => elements.reduce((last, element, index) => {
    const hiddenGroup = element.tagName !== "SUMMARY" && element.closest("details:not([open])");
    return element.getClientRects().length && !hiddenGroup ? index : last;
  }, -1));
  expect(lastVisibleIndex).toBeGreaterThanOrEqual(0);
  const lastControl = controls.nth(lastVisibleIndex);
  await lastControl.focus();
  await expect(lastControl).toBeFocused();
  await page.keyboard.press("Tab");
  expect(await page.evaluate(() => !document.activeElement?.closest("aside.sidebar"))).toBe(true);

  await page.setViewportSize({ width: 390, height: 844 });
  await menu.click();
  await expect(sidebar).toHaveAttribute("aria-modal", "true");
  await page.keyboard.press("Escape");
  await expect(sidebar).not.toHaveAttribute("aria-modal");
  await expect(menu).toBeFocused();
  expect(await page.evaluate(() => document.body.style.overflow)).toBe("auto");
});

for (const locale of ["en", "ar"] as const) for (const { width, collapsed } of [{ width: 1024, collapsed: false }, { width: 1440, collapsed: true }]) test(`an empty ${locale} mobile search cannot hide navigation at ${width}px`, async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  if (collapsed) await page.addInitScript(() => localStorage.setItem("reconforge.studio.sidebar-collapsed", "true"));
  await page.goto("/");
  if (locale === "ar") await page.getByTestId("locale-toggle").click();
  await page.getByRole("banner").getByRole("button", { name: translate(locale, "menu"), exact: true }).click();
  const sidebar = page.locator("aside.sidebar");
  await sidebar.getByRole("searchbox", { name: translate(locale, "navFilter"), exact: true }).fill("unmatched-navigation-query-98374");
  await expect(sidebar.getByRole("status")).toBeVisible();
  await page.setViewportSize({ width, height: 900 });
  await expect(sidebar.locator('[aria-current="page"]')).toBeVisible();
  expect(await page.evaluate(() => !!document.activeElement?.closest("aside.sidebar"))).toBe(true);
  await sidebar.getByRole("button", { name: translate(locale, "inventory"), exact: true }).click();
  await expect(sidebar.getByRole("button", { name: translate(locale, "inventory"), exact: true })).toHaveAttribute("aria-current", "page");
});

for (const locale of ["en", "ar"] as const) for (const width of [1024, 1440]) test(`resizing ${locale} navigation from ${width}px to mobile retains keyboard focus`, async ({ page }) => {
  await page.setViewportSize({ width, height: 900 });
  await page.goto("/");
  if (locale === "ar") await page.getByTestId("locale-toggle").click();
  const sidebar = page.locator("aside.sidebar");
  const current = sidebar.locator('[aria-current="page"]');
  await current.focus();
  await expect(current).toBeFocused();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(sidebar).toHaveAttribute("inert");
  const menu = page.getByRole("banner").getByRole("button", { name: translate(locale, "menu"), exact: true });
  await expect(menu).toBeFocused();
  await menu.press("Enter");
  await expect(sidebar).toHaveAttribute("aria-modal", "true");
  await page.keyboard.press("Escape");
  await expect(menu).toBeFocused();
});

test("resizing to mobile does not move focus from a visible header control", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  const language = page.getByTestId("locale-toggle");
  await language.focus();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(language).toBeFocused();
});
