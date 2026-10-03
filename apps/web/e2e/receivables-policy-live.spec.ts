import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { writeFileSync } from "node:fs";
import { join } from "node:path";

const base = process.env.RECONFORGE_POLICY_UI_BASE_URL;
const password = process.env.RECONFORGE_CASH_UI_PASSWORD;
const output = process.env.RECONFORGE_CASH_UI_OUTPUT;
test.skip(!base || !password || !output, "PROD033 requires the explicit synthetic PostgreSQL 0099 HTTPS policy fixture; review 2026-10-10");
test.use({ ignoreHTTPSErrors: true });

test("retained JPY/KWD inputs write exact minor units; huge and unresolved history remain truthful", async ({ page }) => {
  test.setTimeout(120_000);
  const evidence: Record<string, unknown> = { synthetic_only: true, currencies: [] };
  await page.goto(`${base}/receivables`);
  async function signIn() {
    await page.getByLabel("Tenant ID").fill("cash-a"); await page.getByLabel("Username").fill("cashier"); await page.getByLabel("Password", { exact: true }).fill(password!);
    await page.getByRole("button", { name: "Sign in", exact: true }).click();
    await expect(page.getByRole("button", { name: "Reauthenticate for cash actions", exact: true })).toBeVisible();
  }
  await signIn();
  await page.getByLabel("Password", { exact: true }).fill(password!);
  await page.getByRole("button", { name: "Reauthenticate for cash actions", exact: true }).click();
  await expect(page.getByText(/Recent verification is active/)).toBeVisible();
  await page.getByRole("combobox", { name: "Authorized workspace", exact: true }).selectOption("cash-work");
  const writes: string[] = [];
  page.on("request", (request) => { if (request.method() === "POST" && request.url().includes("/receivables/")) writes.push(request.postData()!); });
  for (const [currency, precision, price, invalid, amount, allocation] of [["JPY", 0, "1234", "1.1", "1000", "500"], ["KWD", 3, "1.234", "1.2345", "1.000", "0.500"]] as const) {
    const disclosure = page.locator("details.ar-draft > summary").first();
    if ((await disclosure.locator("..").getAttribute("open")) === null) { await disclosure.focus(); await page.keyboard.press("Enter"); }
    const another = page.getByRole("button", { name: "Start another draft", exact: true });
    if (await another.isVisible()) await another.click();
    await page.getByRole("combobox", { name: "Customer", exact: true }).selectOption({ label: `CUS-POLICY-${currency} · Synthetic policy ${currency} · ${currency}` });
    await page.getByLabel("Invoice number", { exact: true }).fill(`UI-POLICY-${currency}`);
    await page.getByLabel("Invoice date", { exact: true }).fill("2026-10-03"); await page.getByLabel("Due date", { exact: true }).fill("2026-10-31");
    await page.getByLabel("Line description", { exact: true }).fill("Synthetic major-unit entry");
    const priceInput = page.getByLabel(`Unit price · ${currency}`, { exact: true });
    await priceInput.fill(invalid); const before = writes.length;
    await page.getByRole("button", { name: "Save draft", exact: true }).click();
    await expect(page.getByRole("alert")).toContainText("recorded decimal places"); expect(writes).toHaveLength(before);
    await priceInput.fill(price);
    const createdResponse = page.waitForResponse((response) => response.url().endsWith("/receivables/invoices") && response.request().method() === "POST");
    await page.getByRole("button", { name: "Save draft", exact: true }).click();
    const created = await createdResponse; expect(created.status()).toBe(200);
    const draft = await created.json();
    expect(draft).toMatchObject({ total_minor: 1234, total_minor_text: "1234", monetary_policy: { status: "captured", currency_code: currency, precision } });
    expect(JSON.parse(created.request().postData()!).lines[0]).toMatchObject({ unit_price_minor: 1234, line_total_minor: 1234 });
    await page.getByRole("button", { name: `Review INV-POLICY-${currency}`, exact: true }).click();
    const cash = page.getByRole("region", { name: "Cash receipts and allocations", exact: true });
    await cash.getByLabel("Receipt number", { exact: true }).fill(`R-POLICY-${currency}`); await cash.getByLabel("Receipt date", { exact: true }).fill("2026-10-03");
    await cash.getByLabel(`Received amount · ${currency}`, { exact: true }).fill(amount);
    await cash.getByLabel(`Apply now to this invoice · ${currency}`, { exact: true }).fill(allocation);
    await cash.getByRole("button", { name: "Review cash action", exact: true }).click();
    await expect(cash.getByRole("region", { name: "Review cash action", exact: true })).toBeFocused();
    const postedResponse = page.waitForResponse((response) => response.url().endsWith("/receivables/receipts") && response.request().method() === "POST");
    await cash.getByRole("button", { name: "Confirm financial action", exact: true }).click();
    const posted = await postedResponse; expect(posted.status()).toBe(200);
    const receipt = await posted.json();
    expect(receipt).toMatchObject({ amount_minor: 1000, amount_minor_text: "1000", allocated_minor: 500, unallocated_minor: 500, monetary_policy: { currency_code: currency, precision } });
    await expect(cash).toContainText("server confirmed the cash action");
    const expectedBalance = currency === "JPY" ? "734 JPY" : "0.734 KWD";
    await expect(cash).toContainText(expectedBalance);
    await page.reload();
    await signIn();
    await page.getByRole("combobox", { name: "Authorized workspace", exact: true }).selectOption("cash-work");
    await page.getByRole("button", { name: `Review INV-POLICY-${currency}`, exact: true }).click();
    await expect(page.locator(".ar-cash")).toContainText(expectedBalance);
    (evidence.currencies as unknown[]).push({ currency, precision, draft, receipt, reload_balance: expectedBalance });
    // Reload drops in-memory authority; the new login is elevated explicitly before another write.
    if (currency === "JPY") {
      await page.getByLabel("Password", { exact: true }).fill(password!);
      await page.getByRole("button", { name: "Reauthenticate for cash actions", exact: true }).click();
      await expect(page.getByText(/Recent verification is active/)).toBeVisible();
      await page.getByRole("combobox", { name: "Authorized workspace", exact: true }).selectOption("cash-work");
    }
  }
  await page.getByRole("button", { name: "Review INV-POLICY-HUGE", exact: true }).click();
  await expect(page.getByRole("region", { name: "Invoice review", exact: true })).toContainText("8,999,999,999,999,999.123 KWD");
  await expect(page.locator(".ar-cash")).toContainText("8,999,999,999,999,999,123 KWD · minor units");
  evidence.huge_exact_display = "8999999999999999.123 KWD";
  for (const locale of ["en", "ar"] as const) {
    if (locale === "ar") await page.getByTestId("locale-toggle").click();
    await expect(page.getByRole("main")).toHaveAttribute("dir", locale === "ar" ? "rtl" : "ltr");
    expect((await new AxeBuilder({ page }).include("main").withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze()).violations).toEqual([]);
    await page.setViewportSize({ width: 390, height: 844 });
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    const summary = page.locator(".ar-review details summary");
    await summary.focus(); await page.keyboard.press("Enter");
    await expect(page.locator(".ar-review details")).toHaveAttribute("open");
    await page.keyboard.press("Space"); await expect(page.locator(".ar-review details")).not.toHaveAttribute("open");
    await page.screenshot({ path: join(output!, `policy-huge-mobile-${locale}.png`), fullPage: true });
    await page.setViewportSize({ width: 1440, height: 1024 });
  }
  await page.getByTestId("locale-toggle").click();
  await page.getByRole("button", { name: "Review INV-POLICY-LEGACY", exact: true }).click();
  const legacy = page.getByRole("region", { name: "Invoice review", exact: true });
  await expect(legacy).toContainText("1,234 KWD · minor units"); await expect(legacy).toContainText("Historical currency precision is unverified");
  await expect(page.locator(".ar-cash").getByLabel("Receipt number", { exact: true })).toHaveCount(0);
  evidence.legacy = { raw_minor: "1234", no_precision_inferred: true, cash_mutation_unavailable: true };
  await page.screenshot({ path: join(output!, "policy-legacy-en.png"), fullPage: true });
  evidence.accessibility = { en: "no axe violations", ar: "no axe violations", mobile: 390, keyboard_disclosure: true };
  writeFileSync(join(output!, "policy-browser.json"), JSON.stringify(evidence, null, 2));
});
