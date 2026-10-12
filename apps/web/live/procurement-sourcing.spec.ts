import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page, type Response } from "@playwright/test";
const base = process.env.RECONFORGE_ERP_LIVE_URL, tenant = process.env.RECONFORGE_ERP_TENANT, password = process.env.RECONFORGE_ERP_PASSWORD;
const number = "BPC1-SRC5-BROWSER";
async function acknowledgement(response: Response) { expect(response.status(), await response.text()).toBe(200); return response.json(); }
async function login(page: Page, user: string) {
  await page.goto(`${base}/admin-audit`);
  await page.getByLabel("Tenant ID", { exact: true }).fill(tenant!);
  await page.getByLabel("Username", { exact: true }).fill(user);
  await page.getByLabel("Password", { exact: true }).fill(password!);
  await page.getByRole("button", { name: "Sign in to administration", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Confirm privileged access", exact: true })).toBeVisible();
  await page.getByLabel("Password", { exact: true }).fill(password!);
  const elevated = page.waitForResponse(reply => reply.url().endsWith("/auth/step-up"));
  await page.getByRole("button", { name: "Confirm and continue", exact: true }).click(); await acknowledgement(await elevated);
}
async function budgetScope(page: Page) {
  await page.getByRole("navigation", { name: "Primary navigation" }).getByRole("button", { name: "Budget control", exact: true }).click();
  for (const [label, value] of Object.entries({ "Workspace ID": "work", "Organization ID": "org", "Legal entity ID": "entity" })) await page.getByLabel(label, { exact: true }).fill(value);
  await page.getByRole("button", { name: "Load budgets", exact: true }).click();
}
async function purchaseScope(page: Page) {
  await page.getByRole("navigation", { name: "Primary navigation" }).getByRole("button", { name: "Partial procurement", exact: true }).click();
  await page.getByRole("combobox", { name: "Workspace", exact: true }).selectOption("work");
  await page.getByRole("combobox", { name: "Organization and legal entity", exact: true }).selectOption("entity");
}
async function inspect(page: Page) {
  const region = page.getByRole("region", { name: "Source and ledger references", exact: true });
  const loaded = page.waitForResponse(reply => /\/procurement-partial\/orders\/PPORDER-[^/?]+$/.test(reply.url()) && reply.request().method() === "GET");
  if (await region.isVisible()) await region.getByRole("button", { name: "Refresh this order", exact: true }).click();
  else {
    await page.getByRole("combobox", { name: "Organization and legal entity", exact: true }).selectOption("");
    await page.getByRole("combobox", { name: "Organization and legal entity", exact: true }).selectOption("entity");
    await page.getByRole("button", { name: "Open " + number, exact: true }).click();
  }
  const detail = await acknowledgement(await loaded);
  await expect(region.getByRole("heading", { name: number, exact: true })).toBeVisible();
  await region.getByLabel("Review or posting reason", { exact: true }).fill("Actual independent appropriated procurement operation");
  return { region, detail };
}
async function action(page: Page, label: string, operation: string) {
  const { region } = await inspect(page);
  const saved = page.waitForResponse(reply => reply.url().endsWith(`/commands/${operation}`) && reply.request().method() === "POST");
  await region.getByRole("button", { name: label, exact: true }).click(); return acknowledgement(await saved);
}

test("actual HTTPS PR, RFQ, retained supplier quotations, independent award and native budget/AP/cash/GL survive restore", async ({ browser }) => {
  test.setTimeout(600_000); expect(base && tenant && password).toBeTruthy();
  const contexts = await Promise.all(["maker", "checker", "poster"].map(() => browser.newContext({ ignoreHTTPSErrors: true })));
  try {
    const [maker, checker, poster] = await Promise.all(contexts.map(context => context.newPage()));
    for (const [page, user] of [[maker, "browser-maker"], [checker, "browser-checker"], [poster, "browser-poster"]] as const) await login(page, user);
    await budgetScope(maker);
    const budgetForm = maker.getByRole("form", { name: "Create budget draft", exact: true });
    for (const [label, value] of Object.entries({ "Budget code": "BROWSER-PC", "Budget name": "Actual approved purchase appropriation", "Fiscal period ID": "period", "Currency code": "USD", "Limit in exact minor units": "20000" })) await budgetForm.getByLabel(label, { exact: true }).fill(value);
    const createdBudget = maker.waitForResponse(reply => reply.url().endsWith("/budget-control/envelopes") && reply.request().method() === "POST");
    await budgetForm.getByRole("button", { name: "Create draft", exact: true }).click();
    const budget = await acknowledgement(await createdBudget);
    await maker.getByLabel("Recorded reason", { exact: true }).fill("Independent reviewed native purchase budget");
    const submitted = maker.waitForResponse(reply => reply.url().endsWith(`/envelopes/${budget.id}/submit`));
    await maker.getByRole("button", { name: "Submit for independent approval", exact: true }).click(); await acknowledgement(await submitted);
    await budgetScope(checker); await checker.getByRole("button", { name: "Open budget BROWSER-PC", exact: true }).click();
    await checker.getByLabel("Recorded reason", { exact: true }).fill("Independent appropriation approval");
    const approved = checker.waitForResponse(reply => reply.url().endsWith(`/envelopes/${budget.id}/approve`));
    await checker.getByRole("button", { name: "Approve budget", exact: true }).click(); expect((await acknowledgement(await approved)).status).toBe("Approved");
    async function sourcingScope(page: Page) {
      await page.getByRole("navigation", { name: "Primary navigation" }).getByRole("button", { name: "Procurement sourcing", exact: true }).click();
      await page.getByRole("combobox", { name: "Workspace", exact: true }).selectOption("work");
      await page.getByRole("combobox", { name: "Organization and legal entity", exact: true }).selectOption("entity");
    }
    async function inspectSource(page: Page) {
      await page.getByRole("button", { name: "Refresh requisitions", exact: true }).click();
      await page.getByRole("button", { name: "Open SRC5-BROWSER", exact: true }).click();
      const region = page.getByRole("region", { name: "Original sourcing evidence", exact: true });
      await expect(region.getByRole("heading", { name: "SRC5-BROWSER", exact: true })).toBeVisible();
      await region.getByLabel("Review or award reason", { exact: true }).fill("Actual independent retained source selection");
      return region;
    }
    async function sourceAction(page: Page, operation: string, label: string) {
      const region = await inspectSource(page);
      const saved = page.waitForResponse(reply => reply.url().endsWith("/" + operation) && reply.request().method() === "POST");
      await region.getByRole("button", { name: label, exact: true }).click();
      return acknowledgement(await saved);
    }
    for (const page of [maker, checker, poster]) await sourcingScope(page);
    await maker.locator("summary").filter({ hasText: /^New purchase requisition$/ }).click();
    const sourceForm = maker.getByRole("form", { name: "New purchase requisition", exact: true });
    await sourceForm.getByRole("button", { name: "Add demand line", exact: true }).click();
    for (const [label, value] of Object.entries({ "Requisition number": "SRC5-BROWSER", "Posting date": "2026-10-12", "Quantity 1": "10", "Ceiling unit price in minor units 1": "1200", "Quantity 2": "2.50", "Ceiling unit price in minor units 2": "2000", "Creation reason": "Original exact mixed-unit operational demand" })) await sourceForm.getByLabel(label, { exact: true }).fill(value);
    for (const [label, value] of Object.entries({ "Approved appropriation": budget.id, "Reference supplier": "SUP", "Open fiscal period": "period", "Accrual and payment journal": "STOCK", "Accounts payable": "AP", "Cash account": "CASH", "Item 1": "ITEM", "Receiving location 1": "MAIN/STOCK", "FIFO valuation policy 1": "FIFO", "Item 2": "WEIGHT", "Receiving location 2": "NORTH/STOCK", "FIFO valuation policy 2": "FIFO" })) await sourceForm.getByRole("combobox", { name: label, exact: true }).selectOption(value);
    const createdSource = maker.waitForResponse(reply => reply.url().endsWith("/procurement-sourcing/requisitions") && reply.request().method() === "POST");
    await sourceForm.getByRole("button", { name: "Create requisition", exact: true }).click();
    expect((await acknowledgement(await createdSource)).ceiling_minor).toBe("17000");
    await sourceAction(checker, "open-rfq", "Open RFQ independently");
    for (const [supplier, price] of [["ALT", "1300"], ["SUP", "1200"]] as const) {
      const region = await inspectSource(maker), quotation = region.getByRole("form", { name: "Retain supplier quotation", exact: true });
      await quotation.getByRole("combobox", { name: "Quotation supplier", exact: true }).selectOption(supplier);
      await quotation.getByLabel("Offer valid until", { exact: true }).fill("2026-10-31");
      await quotation.getByLabel("Quoted unit price in minor units 1 · ITEM", { exact: true }).fill(price);
      await quotation.getByLabel("Quoted unit price in minor units 2 · WEIGHT", { exact: true }).fill("2000");
      const retained = maker.waitForResponse(reply => reply.url().endsWith("/quotes") && reply.request().method() === "POST");
      await quotation.getByRole("button", { name: "Retain exact supplier offer", exact: true }).click(); await acknowledgement(await retained);
    }
    expect((await sourceAction(checker, "review-selection", "Review deterministic lowest-cost selection")).status).toBe("SelectionReviewed");
    const owner = await sourceAction(poster, "award", "Award native budget-backed purchase");
    expect(owner.status).toBe("Awarded"); expect(owner.order_id).toMatch(/^PPORDER-/);
    const sourceRegion = poster.getByRole("region", { name: "Original sourcing evidence", exact: true });
    await expect(sourceRegion.getByText("Reviewed winner", { exact: true })).toBeVisible();
    expect((await new AxeBuilder({ page: poster }).include(".procurement-sourcing-page").analyze()).violations).toEqual([]);
    await poster.setViewportSize({ width: 390, height: 844 }); expect(await poster.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await poster.screenshot({ path: test.info().outputPath("sourcing-390px-en.png"), fullPage: true });
    await poster.getByTestId("locale-toggle").click();
    await expect(poster.getByRole("main")).toHaveAttribute("dir", "rtl");
    await expect(poster.getByRole("heading", { name: "طلبات الشراء والمنافسات", exact: true })).toBeVisible();
    expect((await new AxeBuilder({ page: poster }).include(".procurement-sourcing-page").analyze()).violations).toEqual([]);
    await poster.screenshot({ path: test.info().outputPath("sourcing-390px-ar.png"), fullPage: true });
    await poster.getByTestId("locale-toggle").click(); await poster.setViewportSize({ width: 1280, height: 800 });
    for (const page of [maker, checker, poster]) await purchaseScope(page);
    await action(poster, "Submit purchase order", "submit-order"); await action(checker, "Approve purchase order", "approve-order");
    for (const [lineIndex, quantity] of [[0, "2"], [1, "2.50"]] as const) {
      const { region, detail } = await inspect(maker);
      const part = region.getByRole("group", { name: "Quantity for this document", exact: true });
      await part.getByRole("combobox", { name: "Purchase line for receiving", exact: true }).selectOption(detail.lines[lineIndex].id);
      await part.getByLabel("Quantity", { exact: true }).fill(quantity); await part.getByLabel("Posting date", { exact: true }).fill("2026-10-12");
      const prepared = maker.waitForResponse(reply => reply.url().endsWith("/commands/prepare-receipt-line"));
      await part.getByRole("button", { name: "Prepare partial receipt", exact: true }).click(); await acknowledgement(await prepared);
      await action(checker, "Review receiving", "review-receipt"); await action(poster, "Post stock receiving and GL", "receive");
    }
    const { region: matching } = await inspect(maker), part = matching.getByRole("group", { name: "Quantity for this document", exact: true });
    await part.getByLabel("ITEM · EA", { exact: true }).fill("2"); await part.getByLabel("WEIGHT · KG", { exact: true }).fill("2.50");
    const matched = maker.waitForResponse(reply => reply.url().endsWith("/commands/match-invoice-lines"));
    await part.getByRole("button", { name: "Match partial invoice", exact: true }).click(); const invoice = (await acknowledgement(await matched)).invoices[0];
    await action(checker, "Approve supplier invoice", "approve-invoice"); await action(maker, "Prepare invoice accrual", "prepare-accrual"); await action(checker, "Review invoice accrual", "review-accrual");
    const { region: publishing } = await inspect(poster);
    const consumed = poster.waitForResponse(reply => reply.url().endsWith(`/procurement-commitments/orders/${owner.order_id}/consume`));
    await publishing.getByRole("button", { name: "Post AP and consume appropriation " + invoice.number, exact: true }).click();
    expect((await acknowledgement(await consumed)).consumed_minor).toBe("7400");
    const { region: releasing } = await inspect(checker);
    await releasing.getByLabel("Release posting date", { exact: true }).fill("2026-10-13");
    const released = checker.waitForResponse(reply => reply.url().endsWith(`/procurement-commitments/orders/${owner.order_id}/release`));
    await releasing.getByRole("button", { name: "Release remaining obligation", exact: true }).click();
    expect((await acknowledgement(await released)).released_minor).toBe("9600");
    await expect(releasing.getByRole("button", { name: "Prepare partial receipt", exact: true })).toHaveCount(0);
    for (const amount of ["2400", "5000"]) {
      const { region } = await inspect(maker), payment = region.getByRole("form", { name: "Prepare installment", exact: true });
      await payment.getByRole("combobox", { name: "Supplier invoice", exact: true }).selectOption(invoice.id);
      await payment.getByLabel("Installment amount in minor units", { exact: true }).fill(amount); await payment.getByLabel("Posting date", { exact: true }).fill("2026-10-13");
      const prepared = maker.waitForResponse(reply => reply.url().endsWith("/financial-installments/plans") && reply.request().method() === "POST");
      await payment.getByRole("button", { name: "Prepare installment", exact: true }).click(); await acknowledgement(await prepared);
      const { region: reviewing } = await inspect(checker), reviewed = checker.waitForResponse(reply => /\/financial-installments\/plans\/[^/]+\/review$/.test(reply.url()));
      await reviewing.getByRole("button", { name: "Review installment", exact: true }).click(); await acknowledgement(await reviewed);
      const { region: posting } = await inspect(poster), posted = poster.waitForResponse(reply => /\/financial-installments\/plans\/[^/]+\/post$/.test(reply.url()));
      await posting.getByRole("button", { name: "Post installment", exact: true }).click(); expect((await acknowledgement(await posted)).plan.amount_minor).toBe(amount);
    }
    const { region, detail } = await inspect(poster); expect(detail.totals).toMatchObject({ accrued_minor: "7400", paid_minor: "7400", outstanding_minor: "0" });
    await expect(region.getByRole("region", { name: "Purchase appropriation", exact: true })).toContainText("Released");
    await poster.setViewportSize({ width: 390, height: 844 }); expect(await poster.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    expect((await new AxeBuilder({ page: poster }).include(".procurement-partial-page").analyze()).violations).toEqual([]);
    await poster.screenshot({ path: test.info().outputPath("appropriation-390px-en.png"), fullPage: true });
    await poster.getByTestId("locale-toggle").click(); await expect(poster.getByRole("main")).toHaveAttribute("dir", "rtl");
    await expect(poster.getByRole("heading", { name: "اعتماد أمر الشراء", exact: true })).toBeVisible();
    expect((await new AxeBuilder({ page: poster }).include(".procurement-partial-page").analyze()).violations).toEqual([]);
    await poster.screenshot({ path: test.info().outputPath("appropriation-390px-ar.png"), fullPage: true });
  } finally { await Promise.all(contexts.map(context => context.close())); }
});
