import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page, type Response } from "@playwright/test";

const base = process.env.RECONFORGE_ERP_LIVE_URL, tenant = process.env.RECONFORGE_ERP_TENANT, password = process.env.RECONFORGE_ERP_PASSWORD;
const number = "BROWSER-LANDED";
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

test("real HTTPS Studio capitalizes paid freight and duties, receives two warehouses atomically and settles merchandise AP", async ({ browser }) => {
  test.setTimeout(600_000);
  expect(base && tenant && password, "owned real HTTPS backend and synthetic masters are required").toBeTruthy();
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
    await order.getByRole("button", { name: "Create purchase order", exact: true }).click();
    const source = await acknowledgement(await created);
    expect(source.order.total_minor).toBe("17000");
    expect(source.lines.map((line: { uom_code: string; location_code: string }) => [line.uom_code, line.location_code])).toEqual([["EA", "MAIN/STOCK"], ["KG", "NORTH/STOCK"]]);
    await action(maker, "Submit purchase order", "submit-order");
    await action(checker, "Approve purchase order", "approve-order");
    const { region: initial } = await inspect(maker);
    const bundle = initial.getByRole("region", { name: "Paid landed cost receiving", exact: true });
    const costs = bundle.getByRole("form", { name: "Prepare landed cost bundle", exact: true });
    await costs.getByLabel("Landed cost number", { exact: true }).fill("BROWSER-REJECTED-COST");
    await costs.getByLabel("Paid freight in minor units", { exact: true }).fill("777");
    await costs.getByLabel("Paid duties in minor units", { exact: true }).fill("224");
    await costs.getByLabel("Quantity to receive · ITEM · MAIN/STOCK · EA", { exact: true }).fill("10");
    await costs.getByLabel("Quantity to receive · WEIGHT · NORTH/STOCK · KG", { exact: true }).fill("2.50");
    const paid = maker.waitForResponse(reply => reply.url().endsWith("/landed-cost/plans") && reply.request().method() === "POST");
    await costs.getByRole("button", { name: "Prepare landed cost bundle", exact: true }).click();
    const retained = await acknowledgement(await paid);
    expect(retained.amount_minor).toBe("1001");
    expect(retained.allocations.map((allocation: { base_minor: string; freight_minor: string; duty_minor: string }) =>
      [allocation.base_minor, allocation.freight_minor, allocation.duty_minor]).sort()).toEqual([["12000", "548", "158"], ["5000", "229", "66"]]);
    await expect(bundle.getByRole("button", { name: "Cancel unreceived bundle", exact: true })).toBeDisabled();
    const { region: cancelling } = await inspect(checker);
    const rejected = checker.waitForResponse(reply => reply.url().endsWith(`/landed-cost/plans/${retained.id}/cancel`));
    await cancelling.getByRole("button", { name: "Cancel unreceived bundle", exact: true }).click();
    const cancelled = await acknowledgement(await rejected);
    expect(cancelled.status).toBe("Cancelled");
    expect(cancelled.phase).toBe(0);
    expect(cancelled.allocations).toEqual(retained.allocations);
    const { region: replacement, detail: released } = await inspect(maker);
    expect(released.lines.map((line: { reserved_receipt_quantity: string }) => line.reserved_receipt_quantity)).toEqual(["0", "0"]);
    const corrected = replacement.getByRole("form", { name: "Prepare landed cost bundle", exact: true });
    await corrected.getByLabel("Landed cost number", { exact: true }).fill("BROWSER-PAID-COST");
    const reprepare = maker.waitForResponse(reply => reply.url().endsWith("/landed-cost/plans") && reply.request().method() === "POST");
    await corrected.getByRole("button", { name: "Prepare landed cost bundle", exact: true }).click();
    const accepted = await acknowledgement(await reprepare);
    expect(accepted.status).toBe("Prepared");
    const { region: checking } = await inspect(checker);
    const reviewed = checker.waitForResponse(reply => reply.url().endsWith(`/landed-cost/plans/${accepted.id}/review`));
    await checking.getByRole("button", { name: "Review bundle", exact: true }).click();
    await acknowledgement(await reviewed);
    await expect(checking.getByRole("button", { name: "Receive bundle and post paid charges", exact: true })).toBeDisabled();
    const { region: posting } = await inspect(poster);
    const posted = poster.waitForResponse(reply => reply.url().endsWith(`/landed-cost/plans/${accepted.id}/post`));
    await posting.getByRole("button", { name: "Receive bundle and post paid charges", exact: true }).click();
    const published = await acknowledgement(await posted);
    expect(published.phase).toBe(2);
    expect(published.posting_effect_id).toBeTruthy();
    expect(published.allocations.every((allocation: { stage: number }) => allocation.stage === 2)).toBe(true);
    for (const [batch, date] of [[0, "2026-10-12"], [1, "2026-10-13"]] as const) {
      const { region } = await inspect(maker);
      const part = region.getByRole("group", { name: "Quantity for this document", exact: true });
      await part.getByLabel("Posting date", { exact: true }).fill(date);
      await part.getByLabel("ITEM · EA", { exact: true }).fill(batch === 0 ? "3" : "7");
      await part.getByLabel("WEIGHT · KG", { exact: true }).fill(batch === 0 ? "1" : "1.50");
      const matched = maker.waitForResponse(reply => reply.url().endsWith("/commands/match-invoice-lines"));
      await part.getByRole("button", { name: "Match partial invoice", exact: true }).click();
      const invoice = (await acknowledgement(await matched)).invoices.at(-1);
      expect(invoice.quantity_text).toBe(null);
      expect(invoice.lines).toHaveLength(2);
      expect(invoice.total_minor).toBe(batch === 0 ? "5600" : "11400");
      await action(checker, "Approve supplier invoice", "approve-invoice");
      await action(maker, "Prepare invoice accrual", "prepare-accrual");
      await action(checker, "Review invoice accrual", "review-accrual");
      await expect(checker.getByRole("button", { name: "Post invoice accrual", exact: true })).toBeDisabled();
      await action(poster, "Post invoice accrual", "post-accrual");
      for (const amount of batch === 0 ? ["2000", "3600"] : ["4000", "7400"]) {
        const { region: current } = await inspect(maker);
        const payment = current.getByRole("form", { name: "Prepare installment", exact: true });
        await payment.getByRole("combobox", { name: "Supplier invoice", exact: true }).selectOption(invoice.id);
        await payment.getByLabel("Installment amount in minor units", { exact: true }).fill(amount);
        await payment.getByLabel("Posting date", { exact: true }).fill(date);
        await payment.getByRole("combobox", { name: "Open fiscal period", exact: true }).selectOption("period");
        const prepared = maker.waitForResponse(reply => reply.url().endsWith("/financial-installments/plans") && reply.request().method() === "POST");
        await payment.getByRole("button", { name: "Prepare installment", exact: true }).click();
        await acknowledgement(await prepared);
        const { region: review } = await inspect(checker);
        const reviewed = checker.waitForResponse(reply => /\/financial-installments\/plans\/[^/]+\/review$/.test(reply.url()));
        await review.getByRole("button", { name: "Review installment", exact: true }).click();
        await acknowledgement(await reviewed);
        await expect(review.getByRole("button", { name: "Post installment", exact: true })).toBeDisabled();
        const { region: publish } = await inspect(poster);
        const posted = poster.waitForResponse(reply => /\/financial-installments\/plans\/[^/]+\/post$/.test(reply.url()));
        await publish.getByRole("button", { name: "Post installment", exact: true }).click();
        const settled = (await acknowledgement(await posted)).plan;
        expect(settled.amount_minor).toBe(amount);
        expect(settled.posting_effect_id && settled.payment_link_id).toBeTruthy();
      }
    }
    const { region, detail } = await inspect(poster);
    expect(detail.totals).toMatchObject({ received_minor: "17000", accrued_minor: "17000", paid_minor: "17000", outstanding_minor: "0" });
    expect(detail.lines.map((line: { received_quantity: string; invoiced_quantity: string }) => [line.received_quantity, line.invoiced_quantity])).toEqual([["10", "10"], ["2.5", "2.5"]]);
    expect(detail.invoices.map((invoice: { native_status: string }) => invoice.native_status)).toEqual(["Paid", "Paid"]);
    await expect(region.locator("table tbody tr")).toHaveCount(2);
    const history = poster.waitForResponse(reply => /\/procurement-partial\/orders\/[^/]+\/invoices\/[^/]+\/payments\?after=$/.test(reply.url()));
    await region.getByRole("button", { name: "Payment evidence " + detail.invoices[0].number, exact: true }).click();
    const evidence = await acknowledgement(await history);
    expect(evidence.records).toHaveLength(2);
    expect(evidence.records.every((plan: { phase: number }) => plan.phase === 2)).toBe(true);
    await poster.setViewportSize({ width: 390, height: 844 });
    expect(await poster.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    expect((await new AxeBuilder({ page: poster }).include(".procurement-partial-page").analyze()).violations).toEqual([]);
    await poster.screenshot({ path: test.info().outputPath("landed-cost-390px-en.png"), fullPage: true });
    await poster.getByTestId("locale-toggle").click();
    await expect(poster.getByRole("main")).toHaveAttribute("dir", "rtl");
    await expect(poster.getByRole("heading", { name: "المشتريات الجزئية", exact: true }).first()).toBeVisible();
    await expect(poster.getByRole("heading", { name: "استلام بتكاليف وصول مدفوعة", exact: true })).toBeVisible();
    expect((await new AxeBuilder({ page: poster }).include(".procurement-partial-page").analyze()).violations).toEqual([]);
    await poster.screenshot({ path: test.info().outputPath("landed-cost-390px-ar-rtl.png"), fullPage: true });
  } finally { await Promise.all(contexts.map(context => context.close())); }
});
