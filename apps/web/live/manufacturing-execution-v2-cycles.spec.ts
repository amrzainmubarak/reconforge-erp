import { openStudioDestination } from "./studio-navigation";
import { expect, test, type Locator, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
const base = process.env.RECONFORGE_ERP_LIVE_URL, tenant = process.env.RECONFORGE_ERP_TENANT, password = process.env.RECONFORGE_ERP_PASSWORD;
const root = "/manufacturing-execution-v2";
const source = JSON.parse(process.env.RECONFORGE_MANUFACTURING_V2_SOURCE ?? "null");
async function login(page: Page, username: string) {
  await page.goto(`${base}/admin-audit`);
  for (const [label, value] of Object.entries({ "Tenant ID": tenant!, Username: username, Password: password! })) await page.getByLabel(label, { exact: true }).fill(value);
  await page.getByRole("button", { name: "Sign in to administration", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Confirm privileged access", exact: true })).toBeVisible();
  await page.getByLabel("Password", { exact: true }).fill(password!);
  const response = page.waitForResponse(reply => reply.url().endsWith("/auth/step-up"));
  await page.getByRole("button", { name: "Confirm and continue", exact: true }).click(); expect((await response).status()).toBe(200);
}
async function enter(page: Page, identifier = "") {
  await openStudioDestination(page, "Manufacturing execution v2");
  await expect(page.getByRole("heading", { name: "Expense-backed manufacturing and quality", exact: true })).toBeVisible();
  const form = page.getByRole("form", { name: "Apply scope", exact: true });
  for (const [label, value] of Object.entries({ "Workspace ID": "work", "Organization ID": "org", "Legal entity ID": "entity" })) { const field = form.getByLabel(label, { exact: true }); await expect(field).toBeEnabled(); await field.fill(value); }
  for (const [label, value] of Object.entries({ "Workspace ID": "work", "Organization ID": "org", "Legal entity ID": "entity" })) await expect(form.getByLabel(label, { exact: true })).toHaveValue(value);
  const response = page.waitForResponse(reply => reply.url().endsWith(`${root}/orders`) && reply.request().method() === "GET");
  await form.getByRole("button", { name: "Apply scope", exact: true }).click(); expect((await response).status()).toBe(200);
  const select = page.getByRole("combobox", { name: "Retained engineering or production source", exact: true });
  await expect(select).toBeEnabled(); if (identifier) await select.selectOption(identifier);
}
async function fill(form: Locator, fields: Record<string, string>) { for (const [label, value] of Object.entries(fields)) await form.getByLabel(label, { exact: true }).fill(value); }
async function command(page: Page, form: Locator, name: string, path: string, key: string, lose = false) {
  let retained: unknown, body = "", finish!: () => void;
  const done = new Promise<void>(resolve => { finish = resolve; });
  if (lose) await page.route(`**/api/v1${path}`, async route => { if (route.request().method() !== "POST") { await route.continue(); return; } body = route.request().postData()!; const reply = await route.fetch(); expect(reply.status(), await reply.text()).toBe(200); retained = (await reply.json())[key]; await route.abort("failed"); finish(); }, { times: 1 });
  const response = lose ? null : page.waitForResponse(reply => reply.url().endsWith(path) && reply.request().method() === "POST");
  await form.getByRole("button", { name, exact: true }).click();
  if (lose) { await done; const retry = page.getByRole("button", { name: "Retry the same retained command", exact: true }); await expect(retry).toBeVisible(); const response = page.waitForResponse(reply => reply.url().endsWith(path) && reply.request().method() === "POST"); await retry.click(); const reply = await response; expect(reply.status(), await reply.text()).toBe(200); expect(reply.request().postData()).toBe(body); const value = (await reply.json())[key]; expect(value).toEqual(retained); return value; }
  const reply = await response!; expect(reply.status(), await reply.text()).toBe(200); return (await reply.json())[key];
}
async function phase(page: Page, identifier: string, kind: "definition" | "order" | "production" | "inspection", action: "approve" | "prepare" | "review" | "post" | "cancel", lose = false) {
  await login(page, action === "prepare" ? "browser-maker" : action === "post" ? "browser-poster" : "browser-checker"); await enter(page, identifier);
  const region = page.getByRole("region", { name: "Original source and native financial evidence", exact: true });
  await fill(region, { Reason: `Actual independent ${action}` });
  const label = { approve: "Approve engineering revision", prepare: "Prepare full material and cost allocation", review: "Review complete original source", post: "Post complete original effects", cancel: "Cancel unposted source" }[action];
  return command(page, region, label, `${root}/${kind === "definition" ? "definitions" : kind + "s"}/${identifier}/${action}`, kind, lose);
}
async function inspect(page: Page, production: string, accepted: string, rejected: string, day: string, lose = false) {
  await login(page, "browser-maker"); await enter(page, production);
  const form = page.getByRole("form", { name: "Prepare complete held-tranche inspection", exact: true });
  await fill(form, { "Exact accepted quantity": accepted, "Exact rejected quantity": rejected, "Inspection evidence reference": "SYN-QC-" + day, "Open fiscal period ID": "period", "Posting date": day, Reason: "Complete actual held-tranche inspection" });
  return command(page, form, "Prepare complete held-tranche inspection", `${root}/productions/${production}/inspections`, "inspection", lose);
}
test("actual effective engineering expense claims held WIP quality cancellation partial FG and restored oracle", async ({ page }) => {
  test.setTimeout(420_000); expect(base && tenant && password && source?.bom_version_id && source?.cost_claims?.length === 2, "Original owned native fixture/config required").toBeTruthy();
  const errors: string[] = []; page.on("pageerror", error => errors.push(error.message));
  await login(page, "browser-maker"); await enter(page);
  const centerForm = page.getByRole("form", { name: "Prepare effective workcenter", exact: true });
  await fill(centerForm, { "Workcenter code": "ASSEMBLY-BROWSER", "Effective revision": "1", "Workcenter or operation name": "Actual assembly and inspection", "Effective from": "2026-10-01", "Effective until": "2026-10-31", Reason: "Actual engineering revision" });
  const center = await command(page, centerForm, "Prepare effective workcenter", `${root}/workcenters`, "definition", true);
  await phase(page, center.id, "definition", "approve");
  await login(page, "browser-maker"); await enter(page);
  const routeForm = page.getByRole("form", { name: "Prepare ordered engineering routing", exact: true });
  await fill(routeForm, { "Document number": "ROUTE-BROWSER", "Effective revision": "1", "Approved BOM version ID": source.bom_version_id, "Effective from": "2026-10-01", "Effective until": "2026-10-31", Reason: "Actual original ordered operation" });
  await fill(routeForm.getByRole("group").nth(0), { "Approved workcenter ID": center.id, "Workcenter or operation name": "Actual assembly and check", "Planned operation minutes per batch": "60" });
  const routing = await command(page, routeForm, "Prepare ordered engineering routing", `${root}/routings`, "definition"); await phase(page, routing.id, "definition", "approve");
  await login(page, "browser-maker"); await enter(page);
  const orderForm = page.getByRole("form", { name: "Reserve expense-backed material order", exact: true });
  await fill(orderForm, { "Document number": "WORK-BROWSER-V2", "Approved routing ID": routing.id, "Approved BOM version ID": source.bom_version_id, "Exact output quantity": "10", "Component location code": "MAIN/STOCK", "Finished location code": "MAIN/STOCK", "Component FIFO policy": "FIFO", "Finished FIFO policy with WIP offset": "MFG", "Native journal code": "STOCK", "WIP asset account": "WIP", "Abnormal loss expense account": "SCRAP", "Open fiscal period ID": "period", "Posting date": "2026-10-04", Reason: "Actual original expense backed production" });
  await orderForm.getByRole("button", { name: "Add original expense claim", exact: true }).click();
  for (const [index, claim] of source.cost_claims.entries()) { const group = orderForm.getByRole("group").nth(index); await fill(group, { "Original expense posting effect ID": claim.effect_id, "Original positive expense debit line ID": claim.line_id, "Routing operation sequence": "1", "Exact actual minutes": String(claim.minutes), "Exact minor units per hour": claim.rate_minor_per_hour }); await group.getByRole("combobox", { name: "Cost type" }).selectOption(claim.kind); }
  const order = await command(page, orderForm, "Reserve expense-backed material order", `${root}/orders`, "order");
  const prepared = await phase(page, order.id, "order", "prepare"); expect(prepared.total_cost_minor).toBe("3800");
  await phase(page, order.id, "order", "review"); await phase(page, order.id, "order", "post", true);
  for (const [index, produced, accepted, rejected] of [[1, "4", "3", "1"], [2, "6", "6", "0"]] as const) {
    const day = `2026-10-0${4 + index}`;
    await login(page, "browser-maker"); await enter(page, order.id);
    const form = page.getByRole("form", { name: "Prepare production quality hold", exact: true });
    await fill(form, { "Exact output quantity": produced, "Open fiscal period ID": "period", "Posting date": day, Reason: "Actual original production held for inspection" });
    await fill(form.getByRole("group").nth(0), { "Exact actual minutes": index === 1 ? "24" : "36", "Operation evidence reference": "SYN-OP-" + index });
    const hold = await command(page, form, "Prepare production quality hold", `${root}/orders/${order.id}/productions`, "production");
    await phase(page, hold.id, "production", "review"); await phase(page, hold.id, "production", "post");
    await login(page, "browser-maker"); await enter(page, order.id); await expect(page.getByRole("region", { name: "Original source and native financial evidence", exact: true })).toContainText(`Quality hold ${produced}`);
    if (index === 1) { const cancelled = await inspect(page, hold.id, accepted, rejected, day); await phase(page, cancelled.id, "inspection", "review"); const terminal = await phase(page, cancelled.id, "inspection", "cancel", true); expect(terminal.phase).toBe(3); expect(terminal.receipt_effect).toBeNull(); }
    const inspection = await inspect(page, hold.id, accepted, rejected, day, index === 1); await phase(page, inspection.id, "inspection", "review");
    const posted = await phase(page, inspection.id, "inspection", "post", index === 2); expect(posted.receipt_effect.posted_actor_id).toBe("erp-poster");
  }
  await login(page, "browser-maker"); await enter(page, order.id);
  await expect(page.getByRole("region", { name: "Original source and native financial evidence", exact: true })).toContainText("WIP 0");
  await expect(page.getByRole("form", { name: "Prepare production quality hold", exact: true })).toHaveCount(0);
  const select = page.getByRole("combobox", { name: "Retained engineering or production source", exact: true }); await select.focus(); await expect(select).toBeFocused(); await page.keyboard.press("Tab");
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  await page.setViewportSize({ width: 390, height: 844 }); await page.getByRole("button", { name: "Switch language", exact: true }).click();
  await expect(page.getByRole("heading", { name: "التصنيع بالتكلفة الأصلية وفحص الجودة", exact: true })).toBeVisible(); await expect(page.locator("main#main-content")).toHaveAttribute("dir", "rtl");
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]); expect(errors).toEqual([]);
});
