import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

test.setTimeout(60_000);

const liveMetric = {
  id: "metric-a11y", workspace_id: "workspace-a11y", metric_key: "match_rate", period_name: "2026-07",
  value: 88, value_text: "88.00", lineage: "approved matches", computed_at: new Date().toISOString(),
  name: "Match rate", description: "Authorized exact match rate",
};

async function mockLiveContract(page: Page) {
  await page.route("**/api/v1/metrics/dashboard", (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({ metrics: [liveMetric] }),
  }));
}

async function expectNoWcagViolations(page: Page) {
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  expect(results.violations.flatMap((violation) => violation.nodes.map((node) => `${violation.id}: ${node.target.join(" ")}`))).toEqual([]);
}

test("critical English and Arabic Studio routes pass the automated WCAG regression gate", async ({ page }) => {
  await mockLiveContract(page);
  const criticalRoutes = ["/", "/exceptions", "/evidence", "/inventory", "/retail-settlement", "/bank-statement", "/manufacturing-cost", "/professional-invoice-payment", "/individual-cashflow", "/mapping", "/rules", "/live", "/admin-audit"];
  for (const path of criticalRoutes) {
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expectNoWcagViolations(page);
  }

  await page.evaluate(() => window.localStorage.setItem("reconforge.locale", "ar"));
  for (const path of criticalRoutes) {
    await page.goto(path);
    await expect(page.locator("html")).toHaveAttribute("lang", "ar");
    await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expectNoWcagViolations(page);
  }
});

test("keyboard focus is visible, trapped in the command dialog, and restored", async ({ page }) => {
  await page.goto("/");
  await page.keyboard.press("Tab");
  const skip = page.getByRole("link", { name: "Skip to main content" });
  await expect(skip).toBeFocused();
  const focusStyle = await skip.evaluate((element) => {
    const style = getComputedStyle(element);
    return { style: style.outlineStyle, width: Number.parseFloat(style.outlineWidth) };
  });
  expect(focusStyle.style).not.toBe("none");
  expect(focusStyle.width).toBeGreaterThanOrEqual(2);

  const search = page.getByRole("button", { name: /Search controls/ });
  await search.focus();
  await search.click();
  const dialog = page.getByRole("dialog", { name: "Command palette" });
  const input = dialog.getByRole("textbox", { name: "Search controls, pages, or actions" });
  await expect(input).toBeFocused();
  await page.keyboard.press("Shift+Tab");
  const lastFocusable = dialog.locator('button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])').last();
  await expect(lastFocusable).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(input).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(search).toBeFocused();
});

test("contrast, reduced motion, color-safe state, and minimum focus remain enforceable", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Accessibility" }).click();
  await page.getByText("High contrast", { exact: true }).click();
  await page.getByText("Color-blind safe", { exact: true }).click();
  await page.getByText("Reduced motion", { exact: true }).click();
  await page.getByText("Strong focus outlines", { exact: true }).click();

  await expect(page.locator("html")).toHaveAttribute("data-high-contrast", "true");
  await expect(page.locator("html")).toHaveAttribute("data-color-safe", "true");
  await expect(page.locator("html")).toHaveAttribute("data-reduced-motion", "true");
  await expect(page.locator("html")).toHaveAttribute("data-focus-outlines", "false");
  const styles = await page.locator(".metric-card").first().evaluate((element) => {
    const card = getComputedStyle(element);
    const root = getComputedStyle(document.documentElement);
    return {
      transitionSeconds: Number.parseFloat(card.transitionDuration),
      text: root.getPropertyValue("--text").trim(),
      critical: root.getPropertyValue("--critical").trim(),
    };
  });
  expect(styles.transitionSeconds).toBeLessThanOrEqual(0.001);
  expect(styles.text).toBe("#000000");
  expect(styles.critical).toBe("#4d3da5");

  await page.reload();
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await page.keyboard.press("Tab");
  const keyboardFocused = page.locator(":focus");
  await expect(keyboardFocused).toHaveCount(1);
  const outline = await keyboardFocused.evaluate((element) => getComputedStyle(element).outlineStyle);
  expect(outline).not.toBe("none");
  await expectNoWcagViolations(page);
});

test("evidence view exposes redaction state without leaking source filesystem paths", async ({ page }) => {
  await page.goto("/evidence");
  await expect(page.getByRole("heading", { level: 1, name: "Evidence binder" })).toBeVisible();
  await expect(page.getByRole("cell", { name: "synthetic", exact: true }).first()).toBeVisible();
  const text = await page.locator("main").innerText();
  expect(text).not.toMatch(/[A-Za-z]:\\/);
  expect(text).not.toMatch(/\/(?:home|Users|var|tmp)\//);
  expect(await page.locator('[data-source-path], [data-raw-record], [data-secret]').count()).toBe(0);
});

test("retail settlement view exposes replay evidence without write or provider claims", async ({ page }) => {
  await page.goto("/retail-settlement");
  await expect(page.getByRole("heading", { level: 1, name: "Retail settlement control center" })).toBeVisible();
  await expect(page.getByText("POS_SETTLEMENT_VARIANCE_ABOVE_TOLERANCE")).toBeVisible();
  await expect(page.locator("p.retail-boundary")).toHaveText("Synthetic, read-only evidence only; no processor call, payment action, accounting posting, or ERP write-back is available from this Studio route.");
  await expect(page.locator("main button")).toHaveCount(0);
  await expect(page.getByRole("combobox", { name: "Settlement status" })).toBeVisible();
  await expect(page.locator("main")).not.toContainText("password");
});

test("bank reconciliation view exposes replay evidence without write or provider claims", async ({ page }) => {
  await page.goto("/bank-statement");
  await expect(page.getByRole("heading", { level: 1, name: "Bank reconciliation control center" })).toBeVisible();
  await expect(page.getByText("BANK_LEDGER_RECONCILED")).toHaveCount(2);
  await expect(page.locator("p.bank-boundary")).toHaveText("Synthetic, read-only evidence only; no bank call, payment initiation, accounting posting, or ERP write-back is available from this Studio route.");
  await expect(page.locator("main button")).toHaveCount(0);
  await expect(page.getByRole("combobox", { name: "Bank status" })).toBeVisible();
  await expect(page.locator("main")).not.toContainText("password");
});

test("manufacturing cost view exposes replay evidence without ERP or posting claims", async ({ page }) => {
  await page.goto("/manufacturing-cost");
  await expect(page.getByRole("heading", { level: 1, name: "Manufacturing cost control center" })).toBeVisible();
  await expect(page.getByText("MATERIAL_COST_VARIANCE")).toBeVisible();
  await expect(page.locator("p.manufacturing-boundary")).toHaveText("Synthetic, read-only evidence only; no MRP/ERP call, inventory posting, accounting posting, or write-back is available from this Studio route.");
  await expect(page.locator("main button")).toHaveCount(0);
  await expect(page.getByRole("combobox", { name: "Manufacturing status" })).toBeVisible();
  await expect(page.locator("main")).not.toContainText("password");
});

test("professional invoice/payment view exposes replay evidence without billing or posting claims", async ({ page }) => {
  await page.goto("/professional-invoice-payment");
  await expect(page.getByRole("heading", { level: 1, name: "Professional invoice and payment control center" })).toBeVisible();
  await expect(page.getByText("MULTIPLE_PAYMENT_CANDIDATES")).toBeVisible();
  await expect(page.locator("p.professional-boundary")).toHaveText("Synthetic, read-only evidence only; no billing/provider call, receivables allocation, accounting posting, or ERP write-back is available from this Studio route.");
  await expect(page.locator("main button")).toHaveCount(0);
  await expect(page.getByRole("combobox", { name: "Professional status" })).toBeVisible();
  await expect(page.locator("main")).not.toContainText("password");
});

test("individual cashflow view exposes replay evidence without bank, tax, or posting claims", async ({ page }) => {
  await page.goto("/individual-cashflow");
  await expect(page.getByRole("heading", { level: 1, name: "Individual and freelancer cashflow control center" })).toBeVisible();
  await expect(page.getByText("CASHFLOW_ACTIVITY_EXCEEDS_BUDGET")).toBeVisible();
  await expect(page.locator("p.individual-boundary")).toHaveText("Synthetic, read-only evidence only; no bank call, tax or legal classification, accounting posting, or ERP write-back is available from this Studio route.");
  await expect(page.locator("main button")).toHaveCount(0);
  await expect(page.getByRole("combobox", { name: "Cashflow status" })).toBeVisible();
  await expect(page.locator("main")).not.toContainText("password");
});

test("mobile English and Arabic landmarks remain usable without serious WCAG violations", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await expect(page.getByRole("navigation", { name: "Mobile navigation" })).toBeVisible();
  await expectNoWcagViolations(page);
  await page.getByTestId("locale-toggle").click();
  await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
  await expect(page.getByRole("navigation", { name: "تنقل الهاتف" })).toBeVisible();
  await expectNoWcagViolations(page);
});
