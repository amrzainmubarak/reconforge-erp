import { expect, test, type Locator, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { createHash } from "node:crypto";
import { writeFile } from "node:fs/promises";
import { join } from "node:path";
const base = process.env.RECONFORGE_ERP_LIVE_URL, tenant = process.env.RECONFORGE_ERP_TENANT, password = process.env.RECONFORGE_ERP_PASSWORD;
const root = "/api/v1/manufacturing-supply-plan", execution = "/api/v1/manufacturing-execution-v2";
const source = JSON.parse(process.env.RECONFORGE_MANUFACTURING_SUPPLY_SOURCE ?? "null");
const transportLosses: { path: string; mode: string; original_request_sha256: string; immutable_ack_replayed: boolean }[] = [];
async function fill(form: Locator, fields: Record<string, string>) { for (const [label, value] of Object.entries(fields)) await form.getByLabel(label, { exact: true }).fill(value); }
async function login(page: Page, username: string) {
  await page.goto(`${base}/admin-audit`);
  await fill(page.locator("main"), { "Tenant ID": tenant!, Username: username, Password: password! });
  await page.getByRole("button", { name: "Sign in to administration", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Confirm privileged access", exact: true })).toBeVisible();
  await page.getByLabel("Password", { exact: true }).fill(password!);
  const response = page.waitForResponse(reply => reply.url().endsWith("/auth/step-up"));
  await page.getByRole("button", { name: "Confirm and continue", exact: true }).click(); expect((await response).status()).toBe(200);
}
async function enter(page: Page, identifier = "", production = false) {
  await page.getByRole("navigation", { name: "Primary navigation", exact: true }).getByRole("button", {
    name: production ? "Manufacturing execution v2" : "Manufacturing supply and planned procurement", exact: true,
  }).click();
  await expect(page.getByRole("heading", { name: production ? "Expense-backed manufacturing and quality" : "Manufacturing supply planning", exact: true })).toBeVisible();
  const form = page.getByRole("form", { name: "Apply scope", exact: true });
  for (const [label, value] of Object.entries({ "Workspace ID": "work", "Organization ID": "org", "Legal entity ID": "entity" })) { const field = form.getByLabel(label, { exact: true }); await expect(field).toBeEnabled(); await field.fill(value); }
  const response = page.waitForResponse(reply => reply.url().endsWith(`${production ? execution : root}/${production ? "orders" : "plans"}`) && reply.request().method() === "GET");
  await form.getByRole("button", { name: "Apply scope", exact: true }).click(); expect((await response).status()).toBe(200);
  const select = page.getByRole("combobox", { name: production ? "Retained engineering or production source" : "Retained supply plan", exact: true });
  await expect(select).toBeEnabled(); if (identifier) await select.selectOption(identifier);
}
async function refresh(page: Page) {
  const button = page.getByRole("button", { name: "Refresh original supply evidence", exact: true });
  await expect(button).toBeEnabled();
  const response = page.waitForResponse(reply => reply.url().endsWith(`${root}/plans`) && reply.request().method() === "GET");
  await button.click(); expect((await response).status()).toBe(200);
}
async function command(page: Page, form: Locator, label: string, path: string, key: string, lose = false, supply = true) {
  let retained: unknown, body = "", lossMode = "suppressed-committed-response", finish!: () => void;
  const done = new Promise<void>(resolve => { finish = resolve; });
  if (lose) await page.route(`**${path}`, async route => {
    if (route.request().method() !== "POST") { await route.continue(); return; }
    body = route.request().postData()!;
    try {
      const reply = await route.fetch(); expect(reply.status(), await reply.text()).toBe(200);
      retained = await reply.json();
    } catch (error) {
      // The server outcome is unknown until the original retained POST resolves.
      // Keep the original20s transport bound; all other failures remain failures.
      if (!(error instanceof Error) || !/^route\.fetch: Timeout 20000ms exceeded\./.test(error.message)) throw error;
      lossMode = "transport-timeout-outcome-unknown";
    }
    await route.abort("failed"); finish();
  }, { times: 1 });
  let response = lose ? null : page.waitForResponse(reply => reply.url().endsWith(path) && reply.request().method() === "POST");
  await expect(form.getByRole("button", { name: label, exact: true })).toBeEnabled(); await form.getByRole("button", { name: label, exact: true }).click();
  if (lose) { await done; const retry = page.getByRole("button", { name: "Retry the same retained command", exact: true }); await expect(retry).toBeVisible(); response = page.waitForResponse(reply => reply.url().endsWith(path) && reply.request().method() === "POST"); await retry.click(); }
  const reply = await response!; expect(reply.status(), await reply.text()).toBe(200);
  const received = await reply.json(), value = received[key];
  if (lose) {
    expect(reply.request().postData()).toBe(body);
    if (retained !== undefined) expect(received).toEqual(retained);
    // A fresh same-command replay proves the complete immutable receipt, rather
    // than substituting a later GET or assuming the timeout committed.
    const replay = await page.request.fetch(reply.request()); expect(replay.status(), await replay.text()).toBe(200);
    expect(await replay.json()).toEqual(received);
    transportLosses.push({ path, mode: lossMode, original_request_sha256: createHash("sha256").update(body).digest("hex"), immutable_ack_replayed: true });
  }
  if (supply) await refresh(page);
  return value;
}
async function purchaseAction(page: Page, plan: string, purchase: string, person: string, operation: string, label: string, lose = false) {
  await login(page, person); await enter(page, plan);
  const region = page.getByRole("region", { name: "Actual sourcing and partial receiving", exact: true });
  await expect(region.getByLabel("Reason", { exact: true }).first()).toBeEnabled(); await region.getByLabel("Reason", { exact: true }).first().fill("Actual independent " + operation);
  return command(page, region, label, `${root}/plans/${plan}/purchases/${purchase}/${operation}`, "native_response", lose);
}
async function executionPhase(page: Page, identifier: string, kind: "order" | "production" | "inspection", action: "prepare" | "review" | "post", lose = false) {
  await login(page, action === "prepare" ? "browser-maker" : action === "post" ? "browser-poster" : "browser-checker"); await enter(page, identifier, true);
  const region = page.getByRole("region", { name: "Original source and native financial evidence", exact: true });
  await fill(region, { Reason: "Actual original " + action });
  return command(page, region, { prepare: "Prepare full material and cost allocation", review: "Review complete original source", post: "Post complete original effects" }[action], `${execution}/${kind}s/${identifier}/${action}`, kind, lose, false);
}

test("actual original partial-stock supply RFQ three-human award two receipts AP handoff issue QC FG and restored source oracle", async ({ page }) => {
  test.setTimeout(660_000);
  const artifacts = process.env.RECONFORGE_ERP_BROWSER_ARTIFACTS;
  expect(artifacts, "Owned browser artifact directory required").toBeTruthy();
  expect(base && tenant && password && source?.bom_version_id && source?.routing_id && source?.budget_id && source?.cost_claims?.length === 2, "Original native fixture and owned source configuration required").toBeTruthy();
  const errors: string[] = []; page.on("pageerror", error => errors.push(error.message));
  await login(page, "browser-maker"); await enter(page);
  const demand = page.getByRole("form", { name: "Prepare original demand", exact: true });
  await fill(demand, { "Document number": "SUPPLY-BROWSER", "Approved BOM version ID": source.bom_version_id, "Approved routing ID": source.routing_id, "Approved budget ID": source.budget_id,
    "Exact output quantity": "10", "Component location": "MAIN/STOCK", "Finished product location": "MAIN/STOCK", "Component FIFO policy": "FIFO", "Finished product policy": "MFG", "Journal code": "STOCK",
    "WIP account": "WIP", "Abnormal loss account": "SCRAP", "Open fiscal period ID": "period", "Business date": "2026-10-04", Reason: "Actual original partial stock demand" });
  await demand.getByRole("button", { name: "Add component ceiling", exact: true }).click();
  for (const [index, item, price] of [[0, "ITEM", "1200"], [1, "MATERIAL", "100"]] as const) await fill(demand.getByRole("group").nth(index), { "Component item code": item, "Exact unit price ceiling in minor units": price });
  const plan = await command(page, demand, "Prepare original demand", `${root}/plans`, "source", true);
  await login(page, "browser-checker"); await enter(page, plan.id);
  const approval = page.getByRole("form", { name: "Approve and reserve original coverage", exact: true }); await fill(approval, { Reason: "Independent original net coverage" });
  const approved = await command(page, approval, "Approve and reserve original coverage", `${root}/plans/${plan.id}/approve`, "source");
  expect(approved.planned_requirements.map((row: { item_code: string; coverage: { onhand_reserved_scaled: string; shortage_quantity_scaled: string } }) => [row.item_code, row.coverage.onhand_reserved_scaled, row.coverage.shortage_quantity_scaled])).toEqual([["ITEM", "1", "1"], ["MATERIAL", "500", "2500"]]);
  await login(page, "browser-maker"); await enter(page, plan.id);
  const request = page.getByRole("form", { name: "Create exact shortage requisition", exact: true });
  await fill(request, { "Supplier code": "SUP", "AP liability account": "AP", "Cash account": "CASH", Reason: "Original exact shortage only" });
  const requisition = await command(page, request, "Create exact shortage requisition", `${root}/plans/${plan.id}/requisitions`, "native_response");
  await login(page, "browser-checker"); await enter(page, plan.id);
  let region = page.getByRole("region", { name: "Actual sourcing and partial receiving", exact: true }); await region.getByLabel("Reason", { exact: true }).first().fill("Independent original RFQ");
  await command(page, region, "Approve RFQ", `${root}/plans/${plan.id}/requisitions/${requisition.id}/open-rfq`, "native_response");
  await login(page, "browser-maker"); await enter(page, plan.id);
  const quotation = page.getByRole("form", { name: "Record original quotation", exact: true });
  await fill(quotation, { "Supplier code": "SUP", "Quote valid until": "2026-10-31", "ITEM · Unit price in minor units": "1200", "MATERIAL · Unit price in minor units": "100", Reason: "Original supplier offer" });
  await command(page, quotation, "Record original quotation", `${root}/plans/${plan.id}/requisitions/${requisition.id}/quote`, "native_response");
  let awarded: { order_id: string } | null = null;
  for (const [person, operation, label] of [["browser-checker", "review-selection", "Review deterministic supplier selection"], ["browser-poster", "award", "Publish independent budget-backed award"]]) {
    await login(page, person); await enter(page, plan.id); region = page.getByRole("region", { name: "Actual sourcing and partial receiving", exact: true });
    await region.getByLabel("Reason", { exact: true }).first().fill("Independent original " + operation);
    const result = await command(page, region, label, `${root}/plans/${plan.id}/requisitions/${requisition.id}/${operation}`, "native_response", operation === "award");
    if (operation === "award") awarded = result;
  }
  await expect(page.getByRole("region", { name: "Actual sourcing and partial receiving", exact: true }).getByRole("heading", { name: "Actual native purchase and AP", exact: true })).toBeVisible();
  const purchase = awarded!.order_id;
  expect(purchase, "Original awarded native purchase identity required").toBeTruthy();
  await purchaseAction(page, plan.id, purchase, "browser-maker", "purchase-submit", "Submit actual purchase");
  await purchaseAction(page, plan.id, purchase, "browser-checker", "purchase-approve", "Approve actual purchase");
  for (const [item, quantity, day] of [["ITEM", "1", "2026-10-05"], ["MATERIAL", "2.500", "2026-10-06"]]) {
    await login(page, "browser-maker"); await enter(page, plan.id);
    const receipt = page.getByRole("form", { name: "Prepare actual partial receipt", exact: true });
    const lineSelect = receipt.getByRole("combobox", { name: "Original purchase line", exact: true });
    await expect(lineSelect).toBeEnabled();
    const originalLine = lineSelect.getByRole("option", { name: new RegExp(`^${item} /`) });
    await expect(originalLine).toHaveCount(1);
    const originalLineId = await originalLine.getAttribute("value"); expect(originalLineId, "Exact original native purchase line required").toBeTruthy();
    await lineSelect.selectOption(originalLineId!); await expect(lineSelect).toHaveValue(originalLineId!);
    await fill(receipt, { "Exact received quantity": quantity, "Receipt date": day, Reason: "Actual original shortage receipt" });
    const request = page.waitForRequest(value => value.url().endsWith(`${root}/plans/${plan.id}/purchases/${purchase}/receive-prepare`) && value.method() === "POST");
    const prepared = await command(page, receipt, "Prepare actual partial receipt", `${root}/plans/${plan.id}/purchases/${purchase}/receive-prepare`, "native_response");
    expect((await request).postDataJSON()).toMatchObject({ line_id: originalLineId, quantity });
    expect(prepared.receipts.at(-1).order_line_id).toBe(originalLineId);
    await purchaseAction(page, plan.id, purchase, "browser-checker", "receive-review", "Review original receipt");
    await purchaseAction(page, plan.id, purchase, "browser-poster", "receive-commit", "Post actual stock and custody", true);
    await login(page, "browser-maker"); await enter(page, plan.id);
    const invoice = page.getByRole("form", { name: "Match original received invoice", exact: true });
    await fill(invoice, { [`${item} · Exact invoiced quantity`]: quantity, "Invoice date": day, Reason: "Actual original received invoice" });
    await command(page, invoice, "Match original received invoice", `${root}/plans/${plan.id}/purchases/${purchase}/invoice-match`, "native_response");
    for (const [person, operation, label] of [["browser-checker", "invoice-approve", "Approve original invoice"], ["browser-maker", "invoice-prepare", "Prepare original AP accrual"], ["browser-checker", "invoice-review", "Review original AP accrual"], ["browser-poster", "invoice-post", "Post AP and consume actual budget"]])
      await purchaseAction(page, plan.id, purchase, person, operation, label, operation === "invoice-post");
  }
  await login(page, "browser-maker"); await enter(page, plan.id);
  const handoff = page.getByRole("form", { name: "Hand off actual covered production", exact: true });
  await fill(handoff, { "Business date": "2026-10-07", Reason: "Full actual receipt and accrued AP into native production" });
  await handoff.getByRole("button", { name: "Add original expense claim", exact: true }).click();
  for (const [index, claim] of source.cost_claims.entries()) { const group = handoff.getByRole("group").nth(index); await fill(group, { "Original expense effect ID": claim.effect_id, "Original expense debit line ID": claim.line_id, "Routing operation sequence": "1", "Exact actual minutes": String(claim.minutes), "Minor units per hour": claim.rate_minor_per_hour }); await group.getByRole("combobox", { name: "Cost type", exact: true }).selectOption(claim.kind); }
  const production = await command(page, handoff, "Hand off actual covered production", `${root}/plans/${plan.id}/handoff`, "native_response", true);
  const issued = await executionPhase(page, production.id, "order", "prepare"); expect(issued.total_cost_minor).toBe("3600");
  await executionPhase(page, production.id, "order", "review"); await executionPhase(page, production.id, "order", "post", true);
  await login(page, "browser-maker"); await enter(page, production.id, true);
  const holdForm = page.getByRole("form", { name: "Prepare production quality hold", exact: true });
  await fill(holdForm, { "Exact output quantity": "10", "Open fiscal period ID": "period", "Posting date": "2026-10-08", Reason: "Original complete production held for QC" });
  await fill(holdForm.getByRole("group").nth(0), { "Exact actual minutes": "60", "Operation evidence reference": "SUPPLY-BROWSER-OP" });
  const hold = await command(page, holdForm, "Prepare production quality hold", `${execution}/orders/${production.id}/productions`, "production", false, false);
  await executionPhase(page, hold.id, "production", "review"); await executionPhase(page, hold.id, "production", "post");
  await login(page, "browser-maker"); await enter(page, hold.id, true);
  const quality = page.getByRole("form", { name: "Prepare complete held-tranche inspection", exact: true });
  await fill(quality, { "Exact accepted quantity": "9", "Exact rejected quantity": "1", "Inspection evidence reference": "SUPPLY-BROWSER-QC", "Open fiscal period ID": "period", "Posting date": "2026-10-08", Reason: "Original full-tranche actual quality" });
  const inspection = await command(page, quality, "Prepare complete held-tranche inspection", `${execution}/productions/${hold.id}/inspections`, "inspection", false, false);
  await executionPhase(page, inspection.id, "inspection", "review"); const finished = await executionPhase(page, inspection.id, "inspection", "post", true);
  expect(finished.accepted_cost_minor).toBe("3240"); expect(finished.rejected_cost_minor).toBe("360");
  await login(page, "browser-maker"); await enter(page, production.id, true); await expect(page.getByRole("region", { name: "Original source and native financial evidence", exact: true })).toContainText("WIP 0");
  await enter(page, plan.id); const select = page.getByRole("combobox", { name: "Retained supply plan", exact: true }); await select.focus(); await expect(select).toBeFocused(); await page.keyboard.press("Tab");
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  await page.setViewportSize({ width: 390, height: 844 }); await page.getByRole("button", { name: "Switch language", exact: true }).click();
  await expect(page.getByRole("heading", { name: "تخطيط إمداد التصنيع", exact: true })).toBeVisible(); await expect(page.locator("main#main-content")).toHaveAttribute("dir", "rtl");
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]); expect(errors).toEqual([]);
  expect(transportLosses).toHaveLength(9);
  expect(transportLosses.every(value => value.immutable_ack_replayed)).toBe(true);
  await writeFile(join(artifacts!, "manufacturing-supply-original-replay-custody.json"), JSON.stringify({
    schema_version: "manufacturing-supply-transport-replay-custody-v1", original_transport_timeout_ms: 20000,
    losses: transportLosses, financial_accuracy_proven_by: "independent-original-native-cycle-oracle",
    latency_slo_accepted: false, performance_comparison_accepted: false,
  }));
});
