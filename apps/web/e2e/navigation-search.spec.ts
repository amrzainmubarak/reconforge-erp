import { expect, test } from "@playwright/test";
import { translate } from "../src/i18n";

test("search selection restores the complete desktop navigation", async ({ page }) => {
  await page.goto("/");
  const search = page.getByRole("searchbox", { name: "Find a workspace" });
  await search.fill("Inventory controls");
  await page.getByRole("navigation", { name: "Primary navigation" }).getByRole("button", { name: "Inventory controls" }).click();
  await expect(search).toHaveValue("");
  await expect(page.getByRole("heading", { level: 1, name: "Inventory control center" })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Primary navigation" }).getByText("Purchasing & inventory", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Inventory controls" })).toHaveAttribute("aria-current", "page");
});

for (const width of [360, 390, 768]) {
  test(`Arabic mobile search restores navigation when the drawer reopens at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 844 });
    await page.goto("/");
    await page.getByTestId("locale-toggle").click();
    await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
    await page.getByRole("banner").getByRole("button", { name: translate("ar", "menu") }).click();
    const search = page.getByRole("searchbox", { name: translate("ar", "navFilter") });
    await search.fill(translate("ar", "inventory"));
    await page.getByRole("navigation", { name: translate("ar", "primaryNavigation") }).getByRole("button", { name: translate("ar", "inventory") }).click();
    await page.getByRole("banner").getByRole("button", { name: translate("ar", "menu") }).click();
    await expect(search).toHaveValue("");
    await expect(page.getByRole("navigation", { name: translate("ar", "primaryNavigation") }).getByText(translate("ar", "navSupply"), { exact: true })).toBeVisible();
    await testInfo.attach(`arabic-navigation-${width}`, { body: await page.screenshot(), contentType: "image/png" });
  });
}
