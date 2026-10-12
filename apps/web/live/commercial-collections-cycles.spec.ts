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
  const replies = await Promise.all(refreshed ? [listing, refreshed] : [listing]);
  for (const reply of replies) expect(reply.status()).toBe(200);
  if (!refreshed) await area.getByRole("button", { name: "Open", exact: true }).click();
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

test("wire Studio collects twelve reviewed installments inside four native invoices across two warehouses", async ({ browser }) => {
  test.setTimeout(600_000);
  expect(base && tenant && password, "Owned real HTTPS runtime is required").toBeTruthy();
  const contexts = await Promise.all(["maker", "checker", "poster"].map(() => browser.newContext({ ignoreHTTPSErrors: true })));
  const network: unknown[] = [];
  try {
    const [maker, checker, poster] = await Promise.all(contexts.map(context => context.newPage()));
    for (const [index, page] of [maker, checker, poster].entries()) {
      page.on("response", reply => {
        if (reply.url().includes("/api/v1/")) network.push({ actor: index, method: reply.request().method(), path: new URL(reply.url()).pathname,
          status: reply.status(), timing: reply.request().timing() });
      });
      page.on("requestfailed", request => network.push({ actor: index, method: request.method(), path: new URL(request.url()).pathname, failure: request.failure()?.errorText }));
    }
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
      const amounts = [[3000, 4500, 6000], [2000, 5000, 8000], [8000, 10000, 13500], [2000, 3000, 4000]][index - 1];
      if (index === 1) {
        const originalArea = (await inspect(maker, trancheId)).getByRole("region", { name: "Collect this invoice in installments", exact: true });
        const preparation = originalArea.getByRole("form", { name: "Prepare invoice installment", exact: true });
        for (const [label, value] of Object.entries({ "Collection in minor units": "3000", "Unique receipt number": "BROWSER-COMMERCE-CASH-1-0", "Collection date": "2026-10-10", "Collection reason": "Release original reviewed collection before replacement" })) await preparation.getByLabel(label, { exact: true }).fill(value);
        for (const [label, value] of Object.entries({ "Open period": "period", "Cash journal": "CASH", "Cash asset account": "CASH" })) await preparation.getByRole("combobox", { name: label, exact: true }).selectOption(value);
        let response = maker.waitForResponse(reply => reply.url().endsWith("/commercial-collections/plans") && reply.request().method() === "POST");
        await preparation.getByRole("button", { name: "Prepare invoice installment", exact: true }).click();
        expect((await response).status()).toBe(200);
        await expect(originalArea.getByRole("button", { name: "Cancel unposted invoice installment", exact: true })).toBeDisabled();
        const reviewArea = (await inspect(checker, trancheId)).getByRole("region", { name: "Collect this invoice in installments", exact: true });
        await reviewArea.getByLabel("Collection reason", { exact: true }).fill("Independent review before original claim release");
        response = checker.waitForResponse(reply => /commercial-collections\/plans\/[^/]+\/review$/.test(reply.url()) && reply.request().method() === "POST");
        await reviewArea.getByRole("button", { name: "Review invoice installment", exact: true }).click();
        expect((await response).status()).toBe(200);
        await expect(reviewArea.getByRole("button", { name: "Cancel unposted invoice installment", exact: true })).toBeDisabled();
        const releaseArea = (await inspect(poster, trancheId)).getByRole("region", { name: "Collect this invoice in installments", exact: true });
        await releaseArea.getByLabel("Collection reason", { exact: true }).fill("Third-person unposted claim release");
        let original = "", replay = "";
        await poster.route("**/commercial-collections/plans/*/cancel", async route => { original = route.request().postData() || ""; expect((await route.fetch()).status()).toBe(200); await route.abort("failed"); }, { times: 1 });
        const lostRelease = poster.waitForEvent("requestfailed", { predicate: request => /commercial-collections\/plans\/[^/]+\/cancel$/.test(request.url()) });
        await releaseArea.getByRole("button", { name: "Cancel unposted invoice installment", exact: true }).click();
        expect((await lostRelease).failure()?.errorText).toBe("net::ERR_FAILED");
        await expect(poster.getByRole("combobox", { name: "Workspace", exact: true })).toBeDisabled();
        response = poster.waitForResponse(reply => /commercial-collections\/plans\/[^/]+\/cancel$/.test(reply.url()) && reply.request().method() === "POST");
        await poster.route("**/commercial-collections/plans/*/cancel", async route => { replay = route.request().postData() || ""; await route.continue(); }, { times: 1 });
        await releaseArea.getByRole("button", { name: "Retry retained collection command", exact: true }).click();
        expect((await response).status()).toBe(200); expect(replay).toBe(original);
        await expect(panel(poster).getByRole("button", { name: "Refresh commercial orders", exact: true })).toBeEnabled();
      }
      for (let installment = 0; installment < amounts.length; installment += 1) {
        const makerArticle = await inspect(maker, trancheId);
        const area = makerArticle.getByRole("region", { name: "Collect this invoice in installments", exact: true });
        const form = area.getByRole("form", { name: "Prepare invoice installment", exact: true });
        for (const [label, value] of Object.entries({ "Collection in minor units": String(amounts[installment]), "Unique receipt number": `BROWSER-COMMERCE-CASH-${index}-${installment}`, "Collection date": "2026-10-10", "Collection reason": "Reviewed exact partial allocation" })) await form.getByLabel(label, { exact: true }).fill(value);
        for (const [label, value] of Object.entries({ "Open period": "period", "Cash journal": "CASH", "Cash asset account": "CASH" })) await form.getByRole("combobox", { name: label, exact: true }).selectOption(value);
        let response = maker.waitForResponse(reply => reply.url().endsWith("/commercial-collections/plans") && reply.request().method() === "POST");
        await form.getByRole("button", { name: "Prepare invoice installment", exact: true }).click();
        expect((await response).status()).toBe(200);
        await expect(area.getByRole("button", { name: "Review invoice installment", exact: true })).toBeDisabled();
        const checkerArea = (await inspect(checker, trancheId)).getByRole("region", { name: "Collect this invoice in installments", exact: true });
        await checkerArea.getByLabel("Collection reason", { exact: true }).fill("Independent installment review");
        response = checker.waitForResponse(reply => /commercial-collections\/plans\/[^/]+\/review$/.test(reply.url()) && reply.request().method() === "POST");
        await checkerArea.getByRole("button", { name: "Review invoice installment", exact: true }).click();
        expect((await response).status()).toBe(200);
        await expect(checkerArea.getByRole("button", { name: "Post invoice installment", exact: true })).toBeDisabled();
        const posterArea = (await inspect(poster, trancheId)).getByRole("region", { name: "Collect this invoice in installments", exact: true });
        await posterArea.getByLabel("Collection reason", { exact: true }).fill("Third-person cash posting");
        if (index === 4 && installment === 2) {
          let original = "", replay = "";
          await poster.route("**/commercial-collections/plans/*/post", async route => { original = route.request().postData() || ""; expect((await route.fetch()).status()).toBe(200); await route.abort("failed"); }, { times: 1 });
          const lostAcknowledgement = poster.waitForEvent("requestfailed", { predicate: request => /commercial-collections\/plans\/[^/]+\/post$/.test(request.url()) });
          await posterArea.getByRole("button", { name: "Post invoice installment", exact: true }).click();
          expect((await lostAcknowledgement).failure()?.errorText).toBe("net::ERR_FAILED");
          await expect(posterArea.getByRole("button", { name: "Retry retained collection command", exact: true })).toBeVisible();
          await expect(poster.getByRole("combobox", { name: "Workspace", exact: true })).toBeDisabled();
          response = poster.waitForResponse(reply => /commercial-collections\/plans\/[^/]+\/post$/.test(reply.url()) && reply.request().method() === "POST");
          await poster.route("**/commercial-collections/plans/*/post", async route => { replay = route.request().postData() || ""; await route.continue(); }, { times: 1 });
          await posterArea.getByRole("button", { name: "Retry retained collection command", exact: true }).click();
          expect((await response).status()).toBe(200); expect(replay).toBe(original);
        } else {
          response = poster.waitForResponse(reply => /commercial-collections\/plans\/[^/]+\/post$/.test(reply.url()) && reply.request().method() === "POST");
          await posterArea.getByRole("button", { name: "Post invoice installment", exact: true }).click();
          expect((await response).status()).toBe(200);
        }
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
    await panel(poster).screenshot({ path: test.info().outputPath("collections-en-mobile.png") });
    await poster.getByTestId("locale-toggle").click();
    await expect(panel(poster).getByRole("heading", { name: "أوامر المبيعات التجارية", exact: true })).toBeVisible();
    expect(await panel(poster).getAttribute("dir")).toBe("rtl");
    expect(await panel(poster).evaluate(node => node.scrollWidth <= node.clientWidth + 1), "RTL commercial controls must fit their viewport").toBe(true);
    expect((await new AxeBuilder({ page: poster }).include(".stock-commerce").analyze()).violations).toEqual([]);
    await panel(poster).screenshot({ path: test.info().outputPath("collections-ar-mobile.png") });
  } finally {
    await test.info().attach("wire-request-timings", { body: JSON.stringify(network, null, 2), contentType: "application/json" });
    await Promise.allSettled(contexts.map(context => context.close()));
  }
});
