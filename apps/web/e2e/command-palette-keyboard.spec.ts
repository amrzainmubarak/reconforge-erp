import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { translate } from "../src/i18n";

for (const [locale, width] of [["en", 1440], ["ar", 390]] as const) {
  test(`command palette starts upward navigation at the last permitted item (${locale}, ${width}px)`, async ({ page }) => {
    await page.setViewportSize({ width, height: 844 });
    await page.goto("/");
    if (locale === "ar") {
      await page.getByTestId("locale-toggle").click();
      await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
    }
    const trigger = page.getByRole("banner").getByRole("button", { name: translate(locale, "search") });
    await trigger.click();
    const dialog = page.getByRole("dialog", { name: translate(locale, "commandPalette") });
    expect((await new AxeBuilder({ page }).include(".command-dialog").analyze()).violations).toEqual([]);
    const search = dialog.getByRole("textbox", { name: translate(locale, "search") });
    await expect(search).toBeFocused();
    const rows = dialog.locator(".command-row:not([aria-disabled])");
    expect(await rows.count()).toBeGreaterThan(1);
    await page.keyboard.press("ArrowUp");
    await expect(rows.last()).toBeFocused();
    await page.keyboard.press("ArrowDown");
    await expect(rows.first()).toBeFocused();
    await search.fill("no-such-command");
    await expect(dialog.getByText(translate(locale, "commandEmpty"))).toBeVisible();
    await expect(rows).toHaveCount(0);
    await page.keyboard.press("ArrowUp");
    await page.keyboard.press("ArrowDown");
    await expect(search).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(dialog).not.toBeVisible();
    await expect(trigger).toBeFocused();
  });
}
