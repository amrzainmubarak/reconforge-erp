import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page, type Response } from "@playwright/test";

const base = process.env.RECONFORGE_ERP_LIVE_URL, tenant = process.env.RECONFORGE_ERP_TENANT, password = process.env.RECONFORGE_ERP_PASSWORD;
const number = "BROWSER-SUPPLIER-RETURN";
async function acknowledgement(response: Response) {
  expect(response.status(), await response.text()).toBe(200);
  return response.json();
}
async function login(page: Page, username: string) {
  await page.goto(`${base}/admin-audit`);
  await page.getByLabel("Tenant ID", { exact: true }).fill(tenant!);
  await page.getByLabel("Username", { exact: true }).fill(username);
  await page.getByLabel("Password", { exact: true }).fill(password!);
  await page.getByRole("button", { name: "Sign in to administration", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Confirm privileged access", exact: true })).toBeVisible();
  await page.getByLabel("Password", { exact: true }).fill(password!);
  const elevated = page.waitForResponse(reply => reply.url().endsWith("/auth/step-up"));
  await page.getByRole("button", { name: "Confirm and continue", exact: true }).click();
  await acknowledgement(await elevated);
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
  expect(detail.order.multiline).toBe(true);
  await region.getByLabel("Review or posting reason", { exact: true }).fill("Real browser independent enterprise operation");
  return { region, detail };
}
async function action(page: Page, label: string, operation: string) {
  const { region } = await inspect(page);
  const saved = page.waitForResponse(reply => reply.url().endsWith(`/commands/${operation}`) && reply.request().method() === "POST");
  await region.getByRole("button", { name: label, exact: true }).click();
  return acknowledgement(await saved);
}

test("actual HTTPS original supplier debit removes charged FIFO, credits unpaid AP, retains paid charge expense and settles remaining warehouse", async ({ browser }) => {
  test.setTimeout(600_000); expect(base && tenant && password).toBeTruthy();
  const contexts = await Promise.all(["maker", "checker", "poster"].map(() => browser.newContext({ ignoreHTTPSErrors: true })));
  try {
    const [maker, checker, poster] = await Promise.all(contexts.map(context => context.newPage()));
    for (const [page, user] of [[maker, "browser-maker"], [checker, "browser-checker"], [poster, "browser-poster"]] as const) await login(page, user);
    await maker.locator("summary").filter({ hasText: /^New stock purchase$/ }).click();
    const order = maker.getByRole("form", { name: "New stock purchase", exact: true });
    await order.getByLabel("Enterprise order with multiple lines", { exact: true }).check();
    await order.getByRole("button", { name: "Add purchase line", exact: true }).click();
    for (const [label, value] of Object.entries({ "Purchase number": number, "Posting date": "2026-10-12", "Quantity 1": "10", "Unit price in minor units 1": "1200", "Quantity 2": "2.50", "Unit price in minor units 2": "2000" })) await order.getByLabel(label, { exact: true }).fill(value);
    for (const [label, value] of Object.entries({ Supplier: "SUP", "Open fiscal period": "period", "Accrual and payment journal": "STOCK", "Accounts payable": "AP", "Cash account": "CASH", "Item 1": "ITEM", "Receiving location 1": "MAIN/STOCK", "FIFO valuation policy 1": "FIFO", "Item 2": "WEIGHT", "Receiving location 2": "NORTH/STOCK", "FIFO valuation policy 2": "FIFO" })) await order.getByRole("combobox", { name: label, exact: true }).selectOption(value);
    const created = maker.waitForResponse(reply => reply.url().endsWith("/procurement-partial/orders/multiline") && reply.request().method() === "POST");
    await order.getByRole("button", { name: "Create purchase order", exact: true }).click(); expect((await acknowledgement(await created)).order.total_minor).toBe("17000");
    await action(maker, "Submit purchase order", "submit-order"); await action(checker, "Approve purchase order", "approve-order");
    const { region } = await inspect(maker), costs = region.getByRole("form", { name: "Prepare landed cost bundle", exact: true });
    for (const [label, value] of Object.entries({ "Landed cost number": "SR-PAID-CHARGES", "Paid freight in minor units": "777", "Paid duties in minor units": "224", "Posting date": "2026-10-12", "Quantity to receive · ITEM · MAIN/STOCK · EA": "10", "Quantity to receive · WEIGHT · NORTH/STOCK · KG": "2.50" })) await costs.getByLabel(label, { exact: true }).fill(value);
    const prepared = maker.waitForResponse(reply => reply.url().endsWith("/landed-cost/plans") && reply.request().method() === "POST");
    await costs.getByRole("button", { name: "Prepare landed cost bundle", exact: true }).click(); expect((await acknowledgement(await prepared)).amount_minor).toBe("1001");
    for (const [page, label, operation] of [[checker, "Review bundle", "review"], [poster, "Receive bundle and post paid charges", "post"]] as const) {
      const { region: current } = await inspect(page), saved = page.waitForResponse(reply => new RegExp(`/landed-cost/plans/[^/]+/${operation}$`).test(reply.url()));
      await current.getByRole("button", { name: label, exact: true }).click(); await acknowledgement(await saved);
    }
    async function invoice(index: number, quantity: string) {
      const { region: matching } = await inspect(maker), part = matching.getByRole("group", { name: "Quantity for this document", exact: true });
      await part.getByLabel("Posting date", { exact: true }).fill("2026-10-13");
      await part.getByLabel("ITEM · EA", { exact: true }).fill(index === 0 ? quantity : "");
      await part.getByLabel("WEIGHT · KG", { exact: true }).fill(index === 1 ? quantity : "");
      const matched = maker.waitForResponse(reply => reply.url().endsWith("/commands/match-invoice-lines"));
      await part.getByRole("button", { name: "Match partial invoice", exact: true }).click(); const source = await acknowledgement(await matched);
      for (const [page, label, operation] of [[checker, "Approve supplier invoice", "approve-invoice"], [maker, "Prepare invoice accrual", "prepare-accrual"], [checker, "Review invoice accrual", "review-accrual"], [poster, "Post invoice accrual", "post-accrual"]] as const) await action(page, label, operation);
      return source.invoices.at(-1);
    }
    const originalInvoice = await invoice(0, "10");
    async function prepareDebit(returnNumber: string) {
      const { region: returning, detail } = await inspect(maker), form = returning.getByRole("form", { name: "Prepare original supplier debit", exact: true });
      const originalReceipt = detail.receipts.find((r: { order_line_id: string }) => r.order_line_id === detail.lines[0].id);
      expect(originalReceipt.supplier_return_owner_id).toBeFalsy();
      expect(detail.invoices.find((i: { id: string }) => i.id === originalInvoice.id).supplier_return_owner_id).toBeFalsy();
      // A replacement is a fresh complete request; retain every original field.
      await form.getByLabel("Supplier return number", { exact: true }).fill(returnNumber);
      await form.getByLabel("Whole original receipt", { exact: true }).selectOption(originalReceipt.id);
      await form.getByLabel("Exact unpaid supplier invoice", { exact: true }).selectOption(originalInvoice.id);
      await form.getByLabel("Supplier return posting date", { exact: true }).fill("2026-10-13");
      await form.getByLabel("Supplier return fiscal period", { exact: true }).selectOption("period");
      await form.getByLabel("Paid charge expense account", { exact: true }).fill("ADJUSTMENT");
      const supplierPrepared = maker.waitForResponse(reply => reply.url().endsWith("/supplier-returns/plans") && reply.request().method() === "POST");
      await expect(form.getByRole("button", { name: "Prepare original supplier debit", exact: true })).toBeEnabled();
      await form.getByRole("button", { name: "Prepare original supplier debit", exact: true }).click();
      const debit = await acknowledgement(await supplierPrepared);
      expect(debit).toMatchObject({ number: returnNumber, status: "Prepared", credit_minor: "12000", inventory_removed_minor: "12706", charge_expense_minor: "706" });
      return debit;
    }
    async function debitAction(page: Page, debit: { id: string; number: string }, label: string, operation: string) {
      const { region: current } = await inspect(page);
      const row = current.getByRole("listitem").filter({ has: current.getByRole("heading", { name: debit.number, exact: true }) });
      const saved = page.waitForResponse(reply => reply.url().endsWith(`/supplier-returns/plans/${debit.id}/${operation}`) && reply.request().method() === "POST");
      await row.getByRole("button", { name: label, exact: true }).click();
      return acknowledgement(await saved);
    }
    const cancelledDraft = await prepareDebit("SR1-BROWSER-CANCELLED");
    expect((await debitAction(checker, cancelledDraft, "Review supplier debit", "review")).status).toBe("Reviewed");
    const cancelled = await debitAction(poster, cancelledDraft, "Cancel unposted supplier debit", "cancel");
    expect(cancelled).toMatchObject({ status: "Cancelled", posting_effect_ids: [], cancellation_reason: "Real browser independent enterprise operation" });
    expect(cancelled.evidence.cancel_audit_event_id && cancelled.evidence.cancel_outbox_event_id).toBeTruthy();
    const debit = await prepareDebit("SR1-BROWSER"); expect(debit.id).not.toBe(cancelled.id);
    for (const [page, label, operation] of [[checker, "Review supplier debit", "review"], [poster, "Remove original FIFO and credit AP", "post"]] as const) {
      await debitAction(page, debit, label, operation);
    }
    const remainingInvoice = await invoice(1, "2.50");
    for (const amount of ["2000", "3000"]) {
      const { region: current } = await inspect(maker), payment = current.getByRole("form", { name: "Prepare installment", exact: true });
      await payment.getByRole("combobox", { name: "Supplier invoice", exact: true }).selectOption(remainingInvoice.id);
      await payment.getByLabel("Installment amount in minor units", { exact: true }).fill(amount); await payment.getByLabel("Posting date", { exact: true }).fill("2026-10-13");
      const saved = maker.waitForResponse(reply => reply.url().endsWith("/financial-installments/plans") && reply.request().method() === "POST");
      await payment.getByRole("button", { name: "Prepare installment", exact: true }).click(); await acknowledgement(await saved);
      for (const [page, label, operation] of [[checker, "Review installment", "review"], [poster, "Post installment", "post"]] as const) {
        const { region: phased } = await inspect(page), response = page.waitForResponse(reply => new RegExp(`/financial-installments/plans/[^/]+/${operation}$`).test(reply.url()));
        await phased.getByRole("button", { name: label, exact: true }).click(); await acknowledgement(await response);
      }
    }
    const final = await inspect(poster); expect(final.detail.totals).toMatchObject({ accrued_minor: "17000", credited_minor: "12000", paid_minor: "5000", outstanding_minor: "0" });
    await expect(final.region.getByRole("region", { name: "Original receipt supplier debit", exact: true })).toContainText("Posted");
    const retainedCancellation = final.region.getByRole("listitem").filter({ has: final.region.getByRole("heading", { name: cancelledDraft.number, exact: true }) });
    await expect(retainedCancellation).toContainText("Cancelled"); await expect(retainedCancellation.getByRole("button")).toHaveCount(0);
    await poster.setViewportSize({ width: 390, height: 844 }); expect(await poster.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    expect((await new AxeBuilder({ page: poster }).include(".procurement-partial-page").analyze()).violations).toEqual([]);
    await poster.screenshot({ path: test.info().outputPath("supplier-return-390px-en.png"), fullPage: true });
    await poster.getByTestId("locale-toggle").click(); await expect(poster.getByRole("main")).toHaveAttribute("dir", "rtl");
    await expect(poster.getByRole("heading", { name: "إشعار خصم المورد للاستلام الأصلي", exact: true })).toBeVisible();
    expect((await new AxeBuilder({ page: poster }).include(".procurement-partial-page").analyze()).violations).toEqual([]);
    await poster.screenshot({ path: test.info().outputPath("supplier-return-390px-ar.png"), fullPage: true });
  } finally { await Promise.all(contexts.map(context => context.close())); }
});
