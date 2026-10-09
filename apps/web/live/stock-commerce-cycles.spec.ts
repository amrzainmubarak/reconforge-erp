import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

const base = process.env.RECONFORGE_ERP_LIVE_URL, tenant = process.env.RECONFORGE_ERP_TENANT, password = process.env.RECONFORGE_ERP_PASSWORD;
const panel = (page: Page) => page.locator(".stock-commerce");

async function signIn(page: Page, username: string) {
  await page.goto(`${base}/admin-audit`);
  await page.getByLabel("Tenant ID", { exact: true }).fill(tenant!);
  await page.getByLabel("Username", { exact: true }).fill(username);
  await page.getByLabel("Password", { exact: true }).fill(password!);
  await page.getByRole("button", { name: "Sign in to administration", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Confirm privileged access", exact: true })).toBeVisible();
  await page.getByLabel("Password", { exact: true }).fill(password!);
  const stepped = page.waitForResponse(reply => reply.url().endsWith("/auth/step-up"));
  await page.getByRole("button", { name: "Confirm and continue", exact: true }).click();
  expect((await stepped).status()).toBe(200);
  await page.getByRole("navigation", { name: "Primary navigation" }).getByRole("button", { name: "Product sales", exact: true }).click();
  for (const [label, value] of Object.entries({ Workspace: "work", Organization: "org", "Legal entity": "entity" })) await page.getByRole("combobox", { name: label, exact: true }).selectOption(value);
  await page.getByRole("button", { name: "Load selected scope", exact: true }).click();
  await expect(panel(page).getByRole("button", { name: "Refresh commercial orders", exact: true })).toBeVisible();
}

async function inspect(page: Page, trancheId?: string) {
  const area = panel(page);
  const article = area.getByRole("article");
  const opened = await article.isVisible();
  const refreshed = opened ? page.waitForResponse(reply => /\/commerce\/orders\/[^/?]+(?:\?|$)/.test(reply.url()) && reply.request().method() === "GET") : null;
  const listing = page.waitForResponse(reply => /\/commerce\/orders(?:\?|$)/.test(reply.url()) && reply.request().method() === "GET");
  await area.getByRole("button", { name: "Refresh commercial orders", exact: true }).click();
  expect((await listing).status()).toBe(200);
  if (refreshed) expect((await refreshed).status()).toBe(200);
  else await area.getByRole("button", { name: "Open", exact: true }).click();
  await expect(article.getByRole("heading", { name: /^BROWSER-COMMERCE/ })).toBeVisible();
  await article.getByLabel("Reason", { exact: true }).fill("Actual independently governed browser cycle");
  if (trancheId) await article.getByRole("combobox", { name: "Delivery tranche", exact: true }).selectOption(trancheId);
  return article;
}

async function command(page: Page, button: string, operation: string, trancheId?: string, fields: Record<string, string> = {}, choices: Record<string, string> = {}) {
  const article = await inspect(page, trancheId);
  for (const [label, value] of Object.entries(fields)) await article.getByLabel(label, { exact: true }).fill(value);
  for (const [label, value] of Object.entries(choices)) await article.getByRole("combobox", { name: label, exact: true }).selectOption(value);
  const response = page.waitForResponse(reply => reply.url().includes("/commerce/orders/") && reply.url().endsWith(`/${operation}`) && reply.request().method() === "POST");
  await article.getByRole("button", { name: button, exact: true }).click();
  const actual = await response;
  expect(actual.status(), await actual.text()).toBe(200);
  await expect(panel(page).getByRole("button", { name: "Refresh commercial orders", exact: true })).toBeEnabled();
}

test("wire Studio conserves two products and warehouses across four partial cycles and lost final acknowledgement", async ({ browser }) => {
  test.setTimeout(600_000);
  expect(base && tenant && password, "Owned real HTTPS runtime is required").toBeTruthy();
  const contexts = await Promise.all(["maker", "checker", "poster"].map(() => browser.newContext({ ignoreHTTPSErrors: true })));
  try {
    const [maker, checker, poster] = await Promise.all(contexts.map(context => context.newPage()));
    for (const [page, username] of [[maker, "browser-maker"], [checker, "browser-checker"], [poster, "browser-poster"]] as const) await signIn(page, username);
    await panel(maker).locator("summary").filter({ hasText: /^Create commercial order$/ }).click();
    const form = panel(maker).getByRole("form", { name: "Create commercial order", exact: true });
    await form.getByLabel("Order number", { exact: true }).fill("BROWSER-COMMERCE");
    await form.getByRole("combobox", { name: "Customer", exact: true }).selectOption("CUSTOMER");
    await form.getByLabel("Customer reference", { exact: true }).fill("DISTRIBUTOR-PARTIAL");
    await form.getByLabel("Business date", { exact: true }).fill("2026-10-09");
    await form.getByRole("button", { name: "Add line", exact: true }).click();
    for (const [number, product, warehouse, quantity, price, discount] of [[1, "ITEM", "MAIN", "10", "5000", "1000"], [2, "ITEM-B", "SOUTH", "8", "3000", "0"]] as const) {
      const line = form.getByRole("group", { name: `Line ${number}`, exact: true });
      for (const [label, value] of Object.entries({ Product: product, Warehouse: warehouse, Location: "STOCK" })) await line.getByRole("combobox", { name: label, exact: true }).selectOption(value);
      for (const [label, value] of Object.entries({ Quantity: quantity, "Unit price in minor units": price, "Discount basis points": discount, Description: `Product ${number}` })) await line.getByLabel(label, { exact: true }).fill(value);
    }
    const created = maker.waitForResponse(reply => reply.url().endsWith("/commerce/orders") && reply.request().method() === "POST");
    await form.getByRole("button", { name: "Create commercial order", exact: true }).click();
    expect((await created).status()).toBe(201);
    await command(maker, "Submit order", "submit");
    await expect((await inspect(maker)).getByRole("button", { name: "Approve commercial terms", exact: true })).toBeDisabled();
    await command(checker, "Approve commercial terms", "approve");

    await command(maker, "Create partial delivery tranche", "open-tranche", undefined, { Quantity: "10" }, { Line: "1" });
    const reservation = await inspect(maker);
    const cancelledId = (await reservation.getByRole("combobox", { name: "Delivery tranche", exact: true }).locator("option").last().getAttribute("value"))!;
    await command(checker, "Approve and reserve tranche", "approve-tranche", cancelledId);
    await command(maker, "Cancel undelivered tranche and release reservation", "cancel", cancelledId);

    for (const [index, line, quantity] of [[1, "1", "3"], [2, "2", "5"], [3, "1", "7"], [4, "2", "3"]] as const) {
      await command(maker, "Create partial delivery tranche", "open-tranche", undefined, { Quantity: quantity }, { Line: line });
      const view = await inspect(maker);
      const option = view.getByRole("combobox", { name: "Delivery tranche", exact: true }).locator("option").filter({ hasText: new RegExp(`^${line} ·`) }).last();
      const trancheId = (await option.getAttribute("value"))!;
      await command(checker, "Approve and reserve tranche", "approve-tranche", trancheId);
      await command(maker, "Prepare FIFO and COGS", "prepare-issue", trancheId, { "Business date": "2026-10-09" }, { "Fiscal period": "period", "FIFO policy": "FIFO" });
      await command(checker, "Review FIFO and COGS", "review-issue", trancheId);
      await expect((await inspect(checker, trancheId)).getByRole("button", { name: "Post delivery and COGS", exact: true })).toBeDisabled();
      await command(poster, "Post delivery and COGS", "deliver", trancheId);
      await command(maker, "Prepare invoice and revenue", "prepare-invoice", trancheId, { "Invoice number": `BROWSER-COMMERCE-INV-${index}`, "Business date": "2026-10-09", "Due date": "2026-10-31" }, { "Fiscal period": "period", Journal: "SALES", "Receivable account": "AR", "Revenue account": "REVENUE" });
      await command(checker, "Review invoice and revenue", "review-invoice", trancheId);
      await command(poster, "Post invoice and revenue", "invoice", trancheId);
      await command(maker, "Prepare collection", "prepare-collection", trancheId, { "Receipt number": `BROWSER-COMMERCE-CASH-${index}`, "Business date": "2026-10-10" }, { "Fiscal period": "period", Journal: "CASH", "Cash account": "CASH" });
      await command(checker, "Review collection", "review-collection", trancheId);
      if (index < 4) await command(poster, "Post collection", "collect", trancheId);
      else {
        const article = await inspect(poster, trancheId);
        let original = "", replay = "";
        await poster.route("**/commerce/orders/*/collect", async route => { original = route.request().postData() || ""; expect((await route.fetch()).status()).toBe(200); await route.abort("failed"); }, { times: 1 });
        await article.getByRole("button", { name: "Post collection", exact: true }).click();
        await expect(panel(poster).getByRole("button", { name: "Retry exact command", exact: true })).toBeVisible();
        await expect(poster.getByRole("combobox", { name: "Workspace", exact: true })).toBeDisabled();
        const reply = poster.waitForResponse(response => response.url().endsWith("/collect") && response.request().method() === "POST");
        await poster.route("**/commerce/orders/*/collect", async route => { replay = route.request().postData() || ""; await route.continue(); }, { times: 1 });
        await panel(poster).getByRole("button", { name: "Retry exact command", exact: true }).click();
        expect((await reply).status()).toBe(200); expect(replay).toBe(original);
        await expect(panel(poster).getByRole("button", { name: "Refresh commercial orders", exact: true })).toBeEnabled();
      }
    }
    await inspect(poster);
    const rows = panel(poster).getByRole("table").locator("tbody tr");
    await expect(rows).toHaveCount(2);
    await expect(rows.nth(0)).toContainText("45000"); await expect(rows.nth(1)).toContainText("24000");
    await poster.setViewportSize({ width: 390, height: 844 });
    expect(await panel(poster).evaluate(node => node.scrollWidth <= node.clientWidth + 1), "Commercial controls and prose must fit; only the bounded table scrolls").toBe(true);
    expect((await new AxeBuilder({ page: poster }).include(".stock-commerce").analyze()).violations).toEqual([]);
    await panel(poster).screenshot({ path: test.info().outputPath("commerce-en-mobile.png") });
    await poster.getByTestId("locale-toggle").click();
    await expect(panel(poster).getByRole("heading", { name: "أوامر المبيعات التجارية", exact: true })).toBeVisible();
    expect(await panel(poster).getAttribute("dir")).toBe("rtl");
    expect(await panel(poster).evaluate(node => node.scrollWidth <= node.clientWidth + 1), "RTL commercial controls must fit their viewport").toBe(true);
    expect((await new AxeBuilder({ page: poster }).include(".stock-commerce").analyze()).violations).toEqual([]);
    await panel(poster).screenshot({ path: test.info().outputPath("commerce-ar-mobile.png") });
  } finally { for (const context of contexts) await context.close(); }
});
