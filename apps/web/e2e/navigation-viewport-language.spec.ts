import { expect, test } from "@playwright/test";

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
