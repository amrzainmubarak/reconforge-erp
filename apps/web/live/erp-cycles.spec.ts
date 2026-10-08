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
  const elevated = page.waitForResponse((response) => response.url().endsWith("/auth/step-up"));
  await page.getByRole("button", { name: "Confirm and continue", exact: true }).click();
  expect((await elevated).status()).toBe(200);
  await expect(page.getByText("Privileged access is active", { exact: true })).toBeVisible();
}

async function sales(page: Page) {
  await page.getByRole("navigation", { name: "Primary navigation" }).getByRole("button", { name: "Sales & revenue", exact: true }).click();
  await page.getByRole("combobox", { name: "Workspace", exact: true }).selectOption("work");
  await page.getByRole("combobox", { name: "Organization", exact: true }).selectOption("org");
  await page.getByRole("combobox", { name: "Legal entity", exact: true }).selectOption("entity");
  await page.getByRole("button", { name: "Load sales", exact: true }).click();
  await expect(page.getByRole("button", { name: "Refresh", exact: true })).toBeVisible();
}

async function openSale(page: Page, number: string) {
  const hasDetail = await page.locator(".sales-detail").isVisible();
  const inspected = hasDetail ? page.waitForResponse((response) => /\/sales-revenue\/documents\/[^/?]+$/.test(response.url()) && response.request().method() === "GET") : null;
  const refreshed = page.waitForResponse((response) => response.url().includes("/sales-revenue/documents?") && response.request().method() === "GET");
  await page.getByRole("button", { name: "Refresh", exact: true }).click();
  expect((await refreshed).status()).toBe(200);
  if (inspected) expect((await inspected).status()).toBe(200);
  else {
    const opened = page.waitForResponse((response) => /\/sales-revenue\/documents\/[^/?]+$/.test(response.url()) && response.request().method() === "GET");
    await page.getByRole("button", { name: `Open ${number}`, exact: true }).click();
    expect((await opened).status()).toBe(200);
  }
  await expect(page.locator(".sales-detail")).toBeVisible();
}

async function saleAction(page: Page, button: string, endpoint: string) {
  await page.locator(".sales-detail").getByLabel("Decision reason", { exact: true }).fill("Actual browser independent decision");
  const reply = page.waitForResponse((response) => response.url().endsWith(endpoint) && response.request().method() === "POST");
  await page.locator(".sales-detail").getByRole("button", { name: button, exact: true }).click();
  const response = await reply;
  expect(response.status(), await response.text()).toBe(200);
  return (await response.json()).document;
}

async function procurement(page: Page) {
  await page.getByRole("navigation", { name: "Primary navigation" }).getByRole("button", { name: "Procurement & payments", exact: true }).click();
  await page.getByRole("combobox", { name: "Workspace", exact: true }).selectOption("work");
  await page.getByRole("combobox", { name: "Organization and legal entity", exact: true }).selectOption("entity");
  await expect(page.getByRole("heading", { name: "Purchases", exact: true })).toBeVisible();
}

async function openPurchase(page: Page, number: string) {
  const refreshed = page.waitForResponse((response) => response.url().endsWith("/procurement-operations/cycles") && response.request().method() === "GET");
  await page.getByRole("button", { name: "Refresh", exact: true }).click();
  expect((await refreshed).status()).toBe(200);
  const inspected = page.waitForResponse((response) => /\/procurement-operations\/cycles\/[^/?]+$/.test(response.url()) && response.request().method() === "GET");
  await page.getByRole("button", { name: `Open ${number}`, exact: true }).click();
  expect((await inspected).status()).toBe(200);
  await expect(page.getByRole("region", { name: "Source and ledger references", exact: true })).toBeVisible();
}

test("normal HTTPS ERP service revenue and stock purchase share exact reviewed GL and recover a lost payment reply", async ({ browser }) => {
  test.setTimeout(240_000);
  expect(base && tenant && password, "owned live fixture is required").toBeTruthy();
  const contexts = await Promise.all(["maker", "checker", "poster"].map(() => browser.newContext({ ignoreHTTPSErrors: true })));
  try {
    const [maker, checker, poster] = await Promise.all(contexts.map((context) => context.newPage()));
    for (const [page, name] of [[maker, "browser-maker"], [checker, "browser-checker"], [poster, "browser-poster"]] as const) {
      await login(page, name);
      await sales(page);
    }
    const number = "BROWSER-SALE";
    await maker.locator("summary").filter({ hasText: /^Customers & credit$/ }).click();
    for (const [label, value] of Object.entries({ "Customer code": "BROWSER-CUSTOMER", "Customer name": "Actual browser customer", Currency: "USD", "Credit limit (minor units)": "1000000", "Payment terms (days)": "30" })) await maker.getByLabel(label, { exact: true }).fill(value);
    const customerSaved = maker.waitForResponse(response => response.url().endsWith("/receivables/customers") && response.request().method() === "POST");
    await maker.getByRole("button", { name: "Save customer", exact: true }).click();
    expect((await customerSaved).status()).toBe(200);
    await maker.getByRole("button", { name: "Load active customers", exact: true }).click();
    await maker.getByRole("combobox", { name: "Customer", exact: true }).selectOption("BROWSER-CUSTOMER");
    for (const [label, value] of Object.entries({ "Quotation number": number, "Business date": "2026-10-08", "Valid until": "2026-10-20", "Service description": "Completed professional service", Quantity: "2", "Unit price (minor units)": "5000", "Discount (basis points)": "200" })) {
      await maker.getByLabel(label, { exact: true }).fill(value);
    }
    const created = maker.waitForResponse((response) => response.url().endsWith("/sales-revenue/quotations") && response.request().method() === "POST");
    await maker.getByRole("button", { name: "Create quotation", exact: true }).click();
    const createdResponse = await created;
    expect(createdResponse.status(), await createdResponse.text()).toBe(200);
    expect((await createdResponse.json()).document.total_minor).toBe("9800");
    await saleAction(maker, "Submit for approval", "/submit");
    await openSale(checker, number);
    await saleAction(checker, "Approve quotation", "/approve");
    await openSale(maker, number);
    for (const [button, path] of [["Confirm customer order", "/order"], ["Record service completion", "/fulfill"]]) {
      await maker.locator(".sales-detail").getByLabel("Customer order / completion reference", { exact: true }).fill(`ACTUAL-${path.slice(1)}`);
      await maker.locator(".sales-detail").getByLabel("Business date", { exact: true }).fill("2026-10-08");
      await saleAction(maker, button, path);
    }
    for (const [label, value] of Object.entries({ "Invoice number": "BROWSER-INVOICE", "Business date": "2026-10-08", "Due date": "2026-10-20" })) {
      await maker.locator(".sales-detail").getByLabel(label, { exact: true }).fill(value);
    }
    for (const [label, value] of Object.entries({ Journal: "SALES", "Fiscal period": "period", "Receivable account": "AR", "Revenue account": "REVENUE" })) await maker.locator(".sales-detail").getByRole("combobox", { name: label, exact: true }).selectOption(value);
    await saleAction(maker, "Prepare invoice", "/invoice/prepare");
    await openSale(checker, number);
    await saleAction(checker, "Review invoice & GL", "/invoice/review");
    await openSale(poster, number);
    await saleAction(poster, "Post revenue", "/invoice/post");
    await openSale(maker, number);
    for (const [label, value] of Object.entries({ "Receipt number": "BROWSER-COLLECTION", "Business date": "2026-10-08" })) {
      await maker.locator(".sales-detail").getByLabel(label, { exact: true }).fill(value);
    }
    for (const [label, value] of Object.entries({ Journal: "CASH", "Fiscal period": "period", "Cash account": "CASH" })) await maker.locator(".sales-detail").getByRole("combobox", { name: label, exact: true }).selectOption(value);
    await saleAction(maker, "Prepare full collection", "/collection/prepare");
    await openSale(checker, number);
    await saleAction(checker, "Review collection", "/collection/review");
    await openSale(poster, number);
    const paidSale = await saleAction(poster, "Post collection & GL", "/collection/post");
    expect(paidSale.status).toBe("Paid");
    expect(paidSale.invoice.outstanding_minor).toBe("0");

    for (const page of [maker, checker, poster]) await procurement(page);
    await maker.locator("summary").filter({ hasText: /^Supplier management$/ }).click();
    const supplier = maker.getByRole("form", { name: "Supplier management", exact: true });
    for (const [label, value] of Object.entries({ "Supplier code": "BROWSER-SUPPLIER", "Supplier name": "Actual browser supplier", "Tax identifier (optional)": "SYNTHETIC-BROWSER-ID" })) await supplier.getByLabel(label, { exact: true }).fill(value);
    const supplierSaved = maker.waitForResponse(response => response.url().endsWith("/payables/suppliers") && response.request().method() === "POST");
    await supplier.getByRole("button", { name: "Save active supplier", exact: true }).click();
    expect((await supplierSaved).status()).toBe(200);
    await expect(supplier.getByRole("status")).toHaveText("Supplier saved and available for purchases.");
    const purchaseNumber = "BROWSER-PURCHASE";
    const order = maker.getByRole("form", { name: "New stock purchase", exact: true });
    for (const [label, value] of Object.entries({ "Purchase number": purchaseNumber, Quantity: "10", "Unit price in minor units": "1200", "Posting date": "2026-10-08" })) await order.getByLabel(label, { exact: true }).fill(value);
    for (const [label, value] of Object.entries({ Supplier: "BROWSER-SUPPLIER", Item: "ITEM", "Open fiscal period": "period", "Receiving location": "MAIN/STOCK", "FIFO valuation policy": "FIFO", "Accrual and payment journal": "STOCK", "Accounts payable": "AP", "Cash account": "CASH" })) await order.getByRole("combobox", { name: label, exact: true }).selectOption(value);
    const purchaseCreated = maker.waitForResponse((response) => response.url().endsWith("/procurement-operations/cycles") && response.request().method() === "POST");
    await order.getByRole("button", { name: "Create purchase order", exact: true }).click();
    const purchaseReply = await purchaseCreated;
    expect(purchaseReply.status(), await purchaseReply.text()).toBe(200);
    const operations = [
      [maker, "Submit purchase order", "submit-order"], [checker, "Approve purchase order", "approve-order"],
      [maker, "Prepare receiving", "prepare-receipt"], [checker, "Review receiving", "review-receipt"],
      [poster, "Post stock receiving and GL", "receive"], [maker, "Create and match supplier invoice", "match-invoice"],
      [checker, "Approve supplier invoice", "approve-invoice"], [maker, "Prepare invoice accrual", "prepare-accrual"],
      [checker, "Review invoice accrual", "review-accrual"], [poster, "Post invoice accrual", "post-accrual"],
      [maker, "Prepare payment", "prepare-payment"], [checker, "Review payment", "review-payment"],
    ] as const;
    for (const [page, button, action] of operations) {
      await openPurchase(page, purchaseNumber);
      const evidence = page.getByRole("region", { name: "Source and ledger references", exact: true });
      await evidence.getByLabel("Review or posting reason", { exact: true }).fill("Actual browser independent financial decision");
      const response = page.waitForResponse((reply) => reply.url().endsWith(`/commands/${action}`));
      await evidence.getByRole("button", { name: button, exact: true }).click();
      const result = await response;
      expect(result.status(), await result.text()).toBe(200);
    }
    await openPurchase(poster, purchaseNumber);
    const evidence = poster.getByRole("region", { name: "Source and ledger references", exact: true });
    await evidence.getByLabel("Review or posting reason", { exact: true }).fill("Actual browser final payment");
    let dropped = false;
    const attempts: string[] = [];
    await poster.route("**/procurement-operations/cycles/*/commands/pay", async (route) => {
      attempts.push(route.request().postData()!);
      if (!dropped) {
        const committed = await route.fetch();
        expect(committed.status(), await committed.text()).toBe(200);
        dropped = true;
        await route.abort("failed");
      } else await route.continue();
    });
    await evidence.getByRole("button", { name: "Post payment and settle AP", exact: true }).click();
    await poster.getByRole("button", { name: "Retry the same command", exact: true }).click();
    await expect(evidence.getByRole("status")).toHaveText("Stage: Paid · 14");
    expect(attempts.length).toBe(2);
    expect(attempts[0]).toBe(attempts[1]);
    await poster.unroute("**/procurement-operations/cycles/*/commands/pay");
    await expect(evidence.getByRole("status")).toBeFocused();
    await poster.setViewportSize({ width: 390, height: 844 });
    expect(await poster.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    expect((await new AxeBuilder({ page: poster }).include("#main-content").analyze()).violations).toEqual([]);
    await poster.getByRole("button", { name: "Switch language", exact: true }).click();
    await expect(poster.getByRole("main")).toHaveAttribute("dir", "rtl");
    await expect(poster.getByRole("heading", { name: "من الشراء إلى السداد", exact: true })).toBeVisible();
    expect((await new AxeBuilder({ page: poster }).include("#main-content").analyze()).violations).toEqual([]);
    await poster.getByTestId("locale-toggle").click();
    await poster.setViewportSize({ width: 1440, height: 900 });
    await poster.getByRole("navigation", { name: "Primary navigation" }).getByRole("button", { name: "Finance & reporting", exact: true }).click();
    await expect(poster.getByRole("heading", { name: "Enterprise finance", exact: true })).toBeVisible();
    const financeScope = poster.getByRole("form", { name: "Select financial scope", exact: true });
    for (const [label, value] of Object.entries({ Workspace: "work", Organization: "org", "Legal entity": "entity" })) await financeScope.getByLabel(label, { exact: true }).fill(value);
    await financeScope.getByRole("button", { name: "Apply scope", exact: true }).click();
    await expect(poster.getByRole("button", { name: "Inspect source", exact: true })).toHaveCount(4);
    const report = poster.getByRole("form", { name: "Posted trial balance", exact: true });
    for (const [label, value] of Object.entries({ "Fiscal period ID": "period", "Organization code": "ORG", "Entity code": "ENTITY" })) await report.getByLabel(label, { exact: true }).fill(value);
    const reportReply = poster.waitForResponse(response => response.url().includes("/finance-core/posted-trial-balance?"));
    await report.getByRole("button", { name: "Load recorded report", exact: true }).click();
    const actualReport = await reportReply;
    expect(actualReport.status(), await actualReport.text()).toBe(200);
    const actual = await actualReport.json();
    expect(actual.trial_balance.effect_count).toBe(5);
    expect(actual.trial_balance.balance_totals).toEqual({ debit_minor: "12000", credit_minor: "12000", balanced: true });
    await expect(poster.getByRole("heading", { name: "Recorded balances", exact: true })).toBeVisible();
    await expect(poster.getByRole("table", { name: "Posted trial balance", exact: true })).toBeVisible();
    const downloaded = poster.waitForEvent("download");
    await poster.getByRole("button", { name: "Download report JSON", exact: true }).click();
    const download = await downloaded;
    expect(download.suggestedFilename()).toBe("reconforge-posted-trial-balance.json");
    expect(JSON.parse(await readFile((await download.path())!, "utf8"))).toEqual(actual);
    expect((await new AxeBuilder({ page: poster }).include("#main-content").analyze()).violations).toEqual([]);
    await expect(poster.getByText("Synthetic preview", { exact: true })).toHaveCount(0);
    await poster.reload();
    await expect(poster.getByRole("button", { name: "Sign in", exact: true })).toBeVisible();
  } catch (error) {
    // The browser fixture owns failure cleanup after diagnostic screenshots.
    throw error;
  }
  await Promise.all(contexts.map((context) => context.close()));
});
