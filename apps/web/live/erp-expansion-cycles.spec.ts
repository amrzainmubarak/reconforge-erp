import { readFile } from "node:fs/promises";
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

const base = process.env.RECONFORGE_ERP_LIVE_URL;
const tenant = process.env.RECONFORGE_ERP_TENANT;
const password = process.env.RECONFORGE_ERP_PASSWORD;

async function login(page: Page, username: string) {
  await page.goto(`${base}/admin-audit`);
  await page.getByLabel("Tenant ID", { exact: true }).fill(tenant!);
  await page.getByLabel("Username", { exact: true }).fill(username);
  await page.getByLabel("Password", { exact: true }).fill(password!);
  await page.getByRole("button", { name: "Sign in to administration", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Confirm privileged access", exact: true })).toBeVisible();
  await page.getByLabel("Password", { exact: true }).fill(password!);
  const response = page.waitForResponse(reply => reply.url().endsWith("/auth/step-up"));
  await page.getByRole("button", { name: "Confirm and continue", exact: true }).click();
  expect((await response).status()).toBe(200);
  await expect(page.getByText("Privileged access is active", { exact: true })).toBeVisible();
}

async function navigate(page: Page, name: string) {
  await page.getByRole("navigation", { name: "Primary navigation" }).getByRole("button", { name, exact: true }).click();
  await expect(page.getByRole("heading", { name, exact: true }).first()).toBeVisible();
}

async function reporting(page: Page) {
  await navigate(page, "Financial statements");
  const scope = page.getByRole("form", { name: "Authorized scope", exact: true });
  for (const [label, value] of Object.entries({ Workspace: "work", Organization: "org", "Legal entity": "entity" })) await scope.getByLabel(label, { exact: true }).fill(value);
  const response = page.waitForResponse(reply => reply.url().endsWith("/financial-reporting/catalog") && reply.request().method() === "GET");
  await scope.getByRole("button", { name: "Apply scope", exact: true }).click();
  expect((await response).status()).toBe(200);
  await expect(page.getByLabel("Classification version name", { exact: true })).toBeVisible();
}

async function partial(page: Page) {
  await navigate(page, "Partial procurement");
  await page.getByRole("combobox", { name: "Workspace", exact: true }).selectOption("work");
  await page.getByRole("combobox", { name: "Organization and legal entity", exact: true }).selectOption("entity");
  await expect(page.getByRole("heading", { name: "Purchases", exact: true })).toBeVisible();
}

async function inspectPartial(page: Page) {
  const region = page.getByRole("region", { name: "Source and ledger references", exact: true });
  const response = page.waitForResponse(reply => /\/procurement-partial\/orders\/[^/?]+(?:\?|$)/.test(reply.url()) && reply.request().method() === "GET");
  if (await region.isVisible()) await region.getByRole("button", { name: "Refresh this order", exact: true }).click();
  else {
    await page.getByRole("combobox", { name: "Organization and legal entity", exact: true }).selectOption("");
    await page.getByRole("combobox", { name: "Organization and legal entity", exact: true }).selectOption("entity");
    await page.getByRole("button", { name: "Open BROWSER-PARTIAL", exact: true }).click();
  }
  const actual = await response;
  expect(actual.status(), await actual.text()).toBe(200);
  await expect(region).toBeVisible();
  return region;
}

async function partialAction(page: Page, button: string, operation: string) {
  const region = await inspectPartial(page);
  await region.getByLabel("Review or posting reason", { exact: true }).fill(`Actual browser ${operation}`);
  const response = page.waitForResponse(reply => reply.url().endsWith(`/commands/${operation}`) && reply.request().method() === "POST");
  await region.getByRole("button", { name: button, exact: true }).click();
  const actual = await response;
  expect(actual.status(), await actual.text()).toBe(200);
  return actual.json();
}

async function stock(page: Page) {
  await navigate(page, "Product sales");
  for (const [label, value] of Object.entries({ Workspace: "work", Organization: "org", "Legal entity": "entity" })) await page.getByRole("combobox", { name: label, exact: true }).selectOption(value);
  await page.getByRole("button", { name: "Load selected scope", exact: true }).click();
  await expect(page.getByRole("button", { name: "Refresh", exact: true })).toBeVisible();
}

async function inspectStock(page: Page) {
  const hasDetail = await page.getByRole("heading", { name: /^BROWSER-PRODUCT ·/ }).isVisible();
  const response = page.waitForResponse(reply => /\/stock-sales\/orders\/[^/?]+(?:\?|$)/.test(reply.url()) && reply.request().method() === "GET");
  if (hasDetail) await page.getByRole("button", { name: "Refresh", exact: true }).click();
  else {
    await page.getByRole("button", { name: "Refresh", exact: true }).click();
    await page.getByRole("button", { name: "Open BROWSER-PRODUCT", exact: true }).click();
  }
  const actual = await response;
  expect(actual.status(), await actual.text()).toBe(200);
  await expect(page.getByRole("heading", { name: /^BROWSER-PRODUCT ·/ })).toBeVisible();
}

async function stockAction(page: Page, button: string, path: string) {
  await inspectStock(page);
  await page.getByLabel("Decision reason", { exact: true }).fill(`Actual browser ${path}`);
  const response = page.waitForResponse(reply => reply.url().endsWith(path) && reply.request().method() === "POST");
  await page.getByRole("button", { name: button, exact: true }).click();
  const actual = await response;
  expect(actual.status(), await actual.text()).toBe(200);
  return actual.json();
}

test("normal wire HTTPS opening, two stock/AP tranches, four installments and FIFO product revenue share verified statements", async ({ browser }) => {
  test.setTimeout(480_000);
  expect(base && tenant && password, "owned configured wire HTTPS fixture is required").toBeTruthy();
  const contexts = await Promise.all(["maker", "checker", "poster"].map(() => browser.newContext({ ignoreHTTPSErrors: true })));
  try {
    const [maker, checker, poster] = await Promise.all(contexts.map(context => context.newPage()));
    for (const [page, username] of [[maker, "browser-maker"], [checker, "browser-checker"], [poster, "browser-poster"]] as const) { await login(page, username); await reporting(page); }
    await maker.getByLabel("Classification version name", { exact: true }).fill("Browser reviewed chart");
    await maker.getByLabel("Cash account CASH", { exact: true }).check();
    const mapResponse = maker.waitForResponse(reply => reply.url().endsWith("/financial-reporting/maps") && reply.request().method() === "POST");
    await maker.getByRole("button", { name: "Prepare classification", exact: true }).click();
    expect((await mapResponse).status()).toBe(200);
    await reporting(checker);
    await checker.getByLabel("Recorded reason", { exact: true }).fill("Independent browser chart review");
    const mapReviewed = checker.waitForResponse(reply => /\/financial-reporting\/maps\/[^/]+\/review$/.test(reply.url()));
    await checker.getByRole("button", { name: "Review classification", exact: true }).click();
    expect((await mapReviewed).status()).toBe(200);
    await reporting(maker);
    const opening = maker.getByRole("form", { name: "Prepare opening balances", exact: true });
    await opening.getByRole("combobox", { name: "Fiscal period", exact: true }).selectOption("period");
    await opening.getByRole("combobox", { name: "Journal", exact: true }).selectOption("STOCK");
    await opening.getByLabel("Recorded reason", { exact: true }).fill("Reviewed initial cash and equity");
    const first = opening.getByRole("group", { name: "Account 1", exact: true }), second = opening.getByRole("group", { name: "Account 2", exact: true });
    await first.getByRole("combobox", { name: "Account", exact: true }).selectOption("CASH");
    await first.getByLabel("Debit", { exact: true }).fill("1000.00");
    await second.getByRole("combobox", { name: "Account", exact: true }).selectOption("EQUITY");
    await second.getByLabel("Credit", { exact: true }).fill("1000.00");
    const openingPrepared = maker.waitForResponse(reply => reply.url().endsWith("/financial-reporting/openings") && reply.request().method() === "POST");
    await opening.getByRole("button", { name: "Prepare opening balances", exact: true }).click();
    expect((await openingPrepared).status()).toBe(200);
    await reporting(checker);
    await checker.getByLabel("Recorded reason", { exact: true }).fill("Independent opening verification");
    const openingReviewed = checker.waitForResponse(reply => /\/financial-reporting\/openings\/[^/]+\/review$/.test(reply.url()));
    await checker.getByRole("button", { name: "Review opening balances", exact: true }).click();
    expect((await openingReviewed).status()).toBe(200);
    await reporting(poster);
    await poster.getByLabel("Recorded reason", { exact: true }).fill("Publish actual opening balances");
    const openingPosted = poster.waitForResponse(reply => /\/financial-reporting\/openings\/[^/]+\/post$/.test(reply.url()));
    await poster.getByRole("button", { name: "Post opening balances", exact: true }).click();
    expect((await openingPosted).status()).toBe(200);

    for (const page of [maker, checker, poster]) await partial(page);
    await maker.locator("summary").filter({ hasText: /^New stock purchase$/ }).click();
    const order = maker.getByRole("form", { name: "New stock purchase", exact: true });
    for (const [label, value] of Object.entries({ "Purchase number": "BROWSER-PARTIAL", Quantity: "10", "Unit price in minor units": "1200", "Posting date": "2026-10-09" })) await order.getByLabel(label, { exact: true }).fill(value);
    for (const [label, value] of Object.entries({ Supplier: "SUP", Item: "ITEM", "Open fiscal period": "period", "Receiving location": "MAIN/STOCK", "FIFO valuation policy": "FIFO", "Accrual and payment journal": "STOCK", "Accounts payable": "AP", "Cash account": "CASH" })) await order.getByRole("combobox", { name: label, exact: true }).selectOption(value);
    const createdPurchase = maker.waitForResponse(reply => reply.url().endsWith("/procurement-partial/orders") && reply.request().method() === "POST");
    await order.getByRole("button", { name: "Create purchase order", exact: true }).click();
    expect((await createdPurchase).status()).toBe(200);
    await partialAction(maker, "Submit purchase order", "submit-order");
    await partialAction(checker, "Approve purchase order", "approve-order");
    for (const quantity of ["4", "6"]) {
      let region = await inspectPartial(maker);
      await region.getByLabel("Review or posting reason", { exact: true }).fill("Actual tranche " + quantity);
      const part = region.getByRole("group", { name: "Quantity for this document", exact: true });
      await part.getByLabel("Quantity", { exact: true }).fill(quantity);
      await part.getByLabel("Posting date", { exact: true }).fill("2026-10-09");
      await part.getByRole("combobox", { name: "Open fiscal period", exact: true }).selectOption("period");
      const prepared = maker.waitForResponse(reply => reply.url().endsWith("/commands/prepare-receipt"));
      await part.getByRole("button", { name: "Prepare partial receipt", exact: true }).click();
      expect((await prepared).status()).toBe(200);
      await partialAction(checker, "Review receiving", "review-receipt");
      await partialAction(poster, "Post stock receiving and GL", "receive");
      region = await inspectPartial(maker);
      await region.getByLabel("Review or posting reason", { exact: true }).fill("Match actual received tranche " + quantity);
      const invoicePart = region.getByRole("group", { name: "Quantity for this document", exact: true });
      await invoicePart.getByLabel("Quantity", { exact: true }).fill(quantity);
      await invoicePart.getByLabel("Posting date", { exact: true }).fill("2026-10-09");
      const matched = maker.waitForResponse(reply => reply.url().endsWith("/commands/match-invoice"));
      await invoicePart.getByRole("button", { name: "Match partial invoice", exact: true }).click();
      expect((await matched).status()).toBe(200);
      await partialAction(checker, "Approve supplier invoice", "approve-invoice");
      await partialAction(maker, "Prepare invoice accrual", "prepare-accrual");
      await partialAction(checker, "Review invoice accrual", "review-accrual");
      const accrued = await partialAction(poster, "Post invoice accrual", "post-accrual");
      const invoiceId = accrued.invoices.at(-1).id;
      for (let installment = 0; installment < 2; installment++) {
        region = await inspectPartial(maker);
        await region.getByLabel("Review or posting reason", { exact: true }).fill(`Actual tranche ${quantity} installment ${installment}`);
        const payment = region.getByRole("form", { name: "Prepare installment", exact: true });
        await payment.getByRole("combobox", { name: "Supplier invoice", exact: true }).selectOption(invoiceId);
        await payment.getByLabel("Installment amount in minor units", { exact: true }).fill(quantity === "4" ? "2400" : "3600");
        await payment.getByLabel("Posting date", { exact: true }).fill("2026-10-10");
        await payment.getByRole("combobox", { name: "Open fiscal period", exact: true }).selectOption("period");
        const paymentPrepared = maker.waitForResponse(reply => reply.url().endsWith("/financial-installments/plans") && reply.request().method() === "POST");
        await payment.getByRole("button", { name: "Prepare installment", exact: true }).click();
        expect((await paymentPrepared).status()).toBe(200);
        region = await inspectPartial(checker);
        await region.getByLabel("Review or posting reason", { exact: true }).fill("Independent installment verification");
        const paymentReviewed = checker.waitForResponse(reply => /\/financial-installments\/plans\/[^/]+\/review$/.test(reply.url()));
        await region.getByRole("button", { name: "Review installment", exact: true }).click();
        expect((await paymentReviewed).status()).toBe(200);
        region = await inspectPartial(poster);
        await region.getByLabel("Review or posting reason", { exact: true }).fill("Publish exact installment");
        const paymentPosted = poster.waitForResponse(reply => /\/financial-installments\/plans\/[^/]+\/post$/.test(reply.url()));
        await region.getByRole("button", { name: "Post installment", exact: true }).click();
        expect((await paymentPosted).status()).toBe(200);
      }
    }

    for (const page of [maker, checker, poster]) await stock(page);
    const stockForm = maker.getByRole("group", { name: "Create product order", exact: true });
    for (const [label, value] of Object.entries({ "Order number": "BROWSER-PRODUCT", "Customer reference": "BROWSER-CUSTOMER-PO", Quantity: "5", "Unit price in minor units": "5000", "Discount in basis points": "1000", "Business date": "2026-10-10", Description: "Five actual stocked products" })) await stockForm.getByLabel(label, { exact: true }).fill(value);
    for (const [label, value] of Object.entries({ Customer: "CUSTOMER", "Stock item": "ITEM", Warehouse: "MAIN", "Stock location": "STOCK" })) await stockForm.getByRole("combobox", { name: label, exact: true }).selectOption(value);
    const saleCreated = maker.waitForResponse(reply => reply.url().endsWith("/stock-sales/orders") && reply.request().method() === "POST");
    await stockForm.getByRole("button", { name: "Create product order", exact: true }).click();
    expect((await saleCreated).status()).toBe(201);
    await stockAction(maker, "Submit order", "/submit");
    await stockAction(checker, "Approve customer terms", "/approve");
    await stockAction(maker, "Reserve stock", "/reserve");
    await inspectStock(maker);
    let fields = maker.getByRole("group", { name: "Prepare FIFO issue", exact: true });
    await fields.getByLabel("Business date", { exact: true }).fill("2026-10-10");
    await fields.getByRole("combobox", { name: "Accounting period", exact: true }).selectOption("period");
    await fields.getByRole("combobox", { name: "FIFO policy", exact: true }).selectOption("FIFO");
    const issue = await stockAction(maker, "Prepare FIFO issue", "/issue/prepare");
    expect(issue.cogs_minor).toBe("6000");
    await stockAction(checker, "Review FIFO and COGS", "/issue/review");
    await stockAction(poster, "Deliver and post COGS", "/deliver");
    await inspectStock(maker);
    fields = maker.getByRole("group", { name: "Prepare AR invoice", exact: true });
    for (const [label, value] of Object.entries({ "Invoice number": "BROWSER-PRODUCT-INVOICE", "Business date": "2026-10-10", "Due date": "2026-10-31" })) await fields.getByLabel(label, { exact: true }).fill(value);
    for (const [label, value] of Object.entries({ Journal: "SALES", "Accounting period": "period", "Receivable account": "AR", "Revenue account": "REVENUE" })) await fields.getByRole("combobox", { name: label, exact: true }).selectOption(value);
    await stockAction(maker, "Prepare AR invoice", "/invoice/prepare");
    await stockAction(checker, "Review revenue", "/invoice/review");
    await stockAction(poster, "Post revenue", "/invoice/post");
    await inspectStock(maker);
    fields = maker.getByRole("group", { name: "Prepare full collection", exact: true });
    for (const [label, value] of Object.entries({ "Cash receipt number": "BROWSER-PRODUCT-CASH", "Business date": "2026-10-11" })) await fields.getByLabel(label, { exact: true }).fill(value);
    for (const [label, value] of Object.entries({ Journal: "CASH", "Accounting period": "period", "Cash account": "CASH" })) await fields.getByRole("combobox", { name: label, exact: true }).selectOption(value);
    await stockAction(maker, "Prepare full collection", "/collection/prepare");
    await stockAction(checker, "Review collection", "/collection/review");
    await inspectStock(poster);
    await poster.getByLabel("Decision reason", { exact: true }).fill("Actual final collection with lost reply");
    let dropped = false;
    const packets: string[] = [];
    await poster.route("**/stock-sales/orders/*/collection/post", async route => {
      packets.push(route.request().postData()!);
      if (!dropped) { const committed = await route.fetch(); expect(committed.status(), await committed.text()).toBe(200); dropped = true; await route.abort("failed"); }
      else await route.continue();
    });
    await poster.getByRole("button", { name: "Collect and post cash", exact: true }).click();
    await expect(poster.getByLabel("Decision reason", { exact: true })).toBeDisabled();
    await expect(poster.getByRole("combobox", { name: "Legal entity", exact: true })).toBeDisabled();
    await poster.getByRole("button", { name: "Retry original request", exact: true }).click();
    await expect(poster.getByRole("heading", { name: "BROWSER-PRODUCT · Paid", exact: true })).toBeVisible();
    expect(packets).toHaveLength(2); expect(packets[0]).toBe(packets[1]);
    await poster.unroute("**/stock-sales/orders/*/collection/post");

    for (const [name, selector, arabic] of [["Product sales", ".stock-sales", "مبيعات المنتجات"], ["Partial procurement", ".procurement-partial-page", "المشتريات الجزئية"], ["Financial statements", ".financial-reporting", "القوائم المالية"]] as const) {
      if (name === "Financial statements") {
        await reporting(poster);
        const reportForm = poster.getByRole("form", { name: "Load financial statements", exact: true });
        await reportForm.getByRole("combobox", { name: "Fiscal period", exact: true }).selectOption("period");
        await reportForm.getByLabel("As of date", { exact: true }).fill("2026-10-11");
        const reported = poster.waitForResponse(reply => reply.url().includes("/financial-reporting/statements?"));
        await reportForm.getByRole("button", { name: "Load financial statements", exact: true }).click();
        const actual = await reported; expect(actual.status(), await actual.text()).toBe(200);
        const json = await actual.json();
        expect(json.statements.effect_count).toBe(12);
        expect(json.statements.balance_sheet).toEqual({ assets_minor: "116500", liabilities_minor: "0", equity_minor: "100000", accumulated_unclosed_result_minor: "16500", balanced: true });
        expect(json.statements.income_statement).toEqual({ income_minor: "22500", expense_minor: "6000", result_minor: "16500" });
        expect(json.statements.cash_movements.closing_minor).toBe("110500");
        const downloading = poster.waitForEvent("download");
        await poster.getByRole("button", { name: "Download verified statement JSON", exact: true }).click();
        const download = await downloading; expect(download.suggestedFilename()).toBe("reconforge-financial-statements.json");
        expect(JSON.parse(await readFile((await download.path())!, "utf8"))).toEqual(json);
      } else if (name === "Partial procurement") { await partial(poster); await inspectPartial(poster); }
      await poster.setViewportSize({ width: 390, height: 844 });
      expect(await poster.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      expect((await new AxeBuilder({ page: poster }).include(selector).analyze()).violations).toEqual([]);
      await poster.getByTestId("locale-toggle").click();
      await expect(poster.getByRole("main")).toHaveAttribute("dir", "rtl");
      await expect(poster.getByRole("heading", { name: arabic, exact: true }).first()).toBeVisible();
      expect((await new AxeBuilder({ page: poster }).include(selector).analyze()).violations).toEqual([]);
      await poster.getByTestId("locale-toggle").click();
      await poster.setViewportSize({ width: 1440, height: 900 });
    }
  } finally { await Promise.all(contexts.map(context => context.close())); }
});
