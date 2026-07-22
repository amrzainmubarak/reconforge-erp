import { expect, test } from "@playwright/test";

const screenshotRoot = "../../docs/assets/screenshots";

test("captures the real desktop workspace pages and Arabic RTL mode", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Control room");
  await expect(page.getByText("Local-first workspace", { exact: true }).last()).toBeVisible();
  await expect(page.getByText("Guided control story", { exact: true })).toBeVisible();
  await expect(page.getByText("Close readiness", { exact: true })).toBeVisible();
  await expect(page.getByText("Entity readiness", { exact: true })).toBeVisible();
  await page.screenshot({ path: `${screenshotRoot}/dashboard.png`, fullPage: true, animations: "disabled" });

  const primaryNavigation = page.getByRole("navigation", { name: "Primary navigation" });
  await primaryNavigation.getByRole("button", { name: /Exceptions/ }).click();
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Exception queue");
  await expect(page.getByText(/SYN-EXC-/).first()).toBeVisible();
  await page.screenshot({ path: `${screenshotRoot}/exception-queue.png`, fullPage: true, animations: "disabled" });

  await primaryNavigation.getByRole("button", { name: /Evidence binder/ }).click();
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Evidence binder");
  await expect(page.getByText(/EVD-SYN-/).first()).toBeVisible();
  await page.screenshot({ path: `${screenshotRoot}/evidence-binder.png`, fullPage: true, animations: "disabled" });

  await primaryNavigation.getByRole("button", { name: /Inventory controls/ }).click();
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Inventory control center");
  await expect(page.getByText("SYN-PART-001")).toBeVisible();
  await page.screenshot({ path: `${screenshotRoot}/inventory-control.png`, fullPage: true, animations: "disabled" });
  await page.getByRole("tab", { name: "Counts" }).click();
  await expect(page.getByText("COUNT/SYN/0024")).toBeVisible();
  await page.screenshot({ path: `${screenshotRoot}/inventory-planning.png`, fullPage: true, animations: "disabled" });
  await page.getByRole("tab", { name: "FIFO valuation" }).click();
  await expect(page.getByRole("tabpanel").getByText("VAL/SYN/0048", { exact: true })).toBeVisible();
  await expect(page.getByText("IV-VAL/SYN/0048")).toBeVisible();
  await expect(page.getByText("IVR/SYN/0032", { exact: true })).toBeVisible();
  await expect(page.getByRole("cell", { name: /^IVR-IVR\/SYN\/0032/ })).toBeVisible();
  await page.screenshot({ path: `${screenshotRoot}/inventory-valuation.png`, fullPage: true, animations: "disabled" });

  await primaryNavigation.getByRole("button", { name: /^Dashboard/ }).click();
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Control room");

  await page.getByTestId("locale-toggle").click();
  await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("مركز الرقابة");
  await page.screenshot({ path: `${screenshotRoot}/rtl-arabic.png`, fullPage: true, animations: "disabled" });
});

test("captures the real mobile dashboard", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await expect(page.getByRole("navigation", { name: "Mobile navigation" })).toBeVisible();
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Control room");
  await page.screenshot({ path: `${screenshotRoot}/mobile-dashboard.png`, fullPage: false, animations: "disabled" });
});
