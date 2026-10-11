import { expect, test, type Page, type Locator } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
const base = process.env.RECONFORGE_ERP_LIVE_URL, tenant = process.env.RECONFORGE_ERP_TENANT, password = process.env.RECONFORGE_ERP_PASSWORD;
const root = "/manufacturing-execution";
async function login(page: Page, username: string) {
  await page.goto(`${base}/admin-audit`);
  for (const [label, value] of Object.entries({ "Tenant ID": tenant!, Username: username, Password: password! })) await page.getByLabel(label, { exact: true }).fill(value);
  await page.getByRole("button", { name: "Sign in to administration", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Confirm privileged access", exact: true })).toBeVisible();
  await page.getByLabel("Password", { exact: true }).fill(password!);
  const response = page.waitForResponse(reply => reply.url().endsWith("/auth/step-up"));
  await page.getByRole("button", { name: "Confirm and continue", exact: true }).click(); expect((await response).status()).toBe(200);
}
async function enter(page: Page, order = "", child = "", bom = "") {
  await page.goto(`${base}${root}`);
  await expect(page.getByRole("heading", { name: "Actual manufacturing execution", exact: true })).toBeVisible();
  const form = page.getByRole("form", { name: "Apply scope", exact: true });
  for (const [label, value] of Object.entries({ "Workspace ID": "work", "Organization ID": "org", "Legal entity ID": "entity" })) { const field = form.getByLabel(label, { exact: true }); await expect(field).toBeEnabled(); await field.fill(value); }
  for (const [label, value] of Object.entries({ "Workspace ID": "work", "Organization ID": "org", "Legal entity ID": "entity" })) await expect(form.getByLabel(label, { exact: true })).toHaveValue(value);
  const response = page.waitForResponse(reply => reply.url().endsWith(`${root}/orders`) && reply.request().method() === "GET");
  await form.getByRole("button", { name: "Apply scope", exact: true }).click(); expect((await response).status()).toBe(200);
  if (bom) await page.getByRole("combobox", { name: "Retained BOM version", exact: true }).selectOption(bom);
  if (order) { await page.getByRole("combobox", { name: "Retained production order", exact: true }).selectOption(order); await expect(page.getByRole("region", { name: "Original production and native financial evidence", exact: true })).toBeVisible(); }
  if (child) await page.getByRole("combobox", { name: "Retained output disposition", exact: true }).selectOption(child);
}
async function fill(form: Locator, values: Record<string, string>) { for (const [label, value] of Object.entries(values)) await form.getByLabel(label, { exact: true }).fill(value); }
async function command(page: Page, form: Locator, name: string, path: string, key: "bom" | "order" | "completion", lose = false) {
  let retained: unknown, body = "", finish!: () => void;
  const committed = new Promise<void>(resolve => { finish = resolve; });
  if (lose) await page.route(`**/api/v1${path}`, async route => { if (route.request().method() !== "POST") { await route.continue(); return; } body = route.request().postData()!; const reply = await route.fetch(); expect(reply.status(), await reply.text()).toBe(200); retained = (await reply.json())[key]; await route.abort("failed"); finish(); }, { times: 1 });
  const response = lose ? null : page.waitForResponse(reply => reply.url().endsWith(path) && reply.request().method() === "POST");
  await form.getByRole("button", { name, exact: true }).click();
  if (lose) {
    await committed; const retry = page.getByRole("button", { name: "Retry retained command", exact: true }); await expect(retry).toBeVisible();
    const response = page.waitForResponse(reply => reply.url().endsWith(path) && reply.request().method() === "POST"); await retry.click();
    const reply = await response; expect(reply.status(), await reply.text()).toBe(200); expect(reply.request().postData()).toBe(body);
    const actual = (await reply.json())[key]; expect(actual).toEqual(retained); return actual;
  }
  const reply = await response!; expect(reply.status(), await reply.text()).toBe(200); return (await reply.json())[key];
}
async function phase(page: Page, order: string, action: "prepare" | "review" | "post" | "cancel", child = "", lose = false) {
  await login(page, action === "prepare" ? "browser-maker" : action === "review" ? "browser-checker" : "browser-poster"); await enter(page, order, child);
  const region = page.getByRole("region", { name: "Original production and native financial evidence", exact: true });
  await region.getByLabel("Reason", { exact: true }).fill(`Actual independent ${action}`);
  const name = { prepare: "Prepare original FIFO material issue", review: "Review complete native source", post: "Post complete native effects", cancel: "Cancel unposted source" }[action];
  return command(page, region, name, `${root}/${child ? "completions/" + child : "orders/" + order}/${action}`, child ? "completion" : "order", lose);
}
async function partial(page: Page, order: string, good: string, scrap: string, lose = false) {
  await login(page, "browser-maker"); await enter(page, order);
  const form = page.getByRole("form", { name: "Prepare partial good output and abnormal scrap", exact: true });
  await fill(form, { "Exact good output quantity": good, "Exact abnormal scrap quantity": scrap, "Open fiscal period ID": "period", "Posting date": "2026-10-05", Reason: "Actual original material disposition" });
  return command(page, form, "Prepare partial good output and abnormal scrap", `${root}/orders/${order}/completions`, "completion", lose);
}
test("actual versioned BOM native material WIP partial FG scrap cancelled draft and lost ACK", async ({ page }) => {
  test.setTimeout(360_000); expect(base && tenant && password, "Owned HTTPS native fixture required").toBeTruthy();
  const errors: string[] = []; page.on("pageerror", error => errors.push(error.message));
  await login(page, "browser-maker"); await enter(page);
  const recipe = page.getByRole("form", { name: "Prepare versioned BOM", exact: true });
  await fill(recipe, { "Document number": "BOM-BROWSER", "BOM version": "1", "Finished item code": "PRODUCT", "Exact planned output quantity": "10", Reason: "Versioned exact material recipe" });
  await fill(recipe.getByRole("group").nth(0), { "Component item code": "ITEM", "Exact base-UOM component quantity": "2" });
  await recipe.getByRole("button", { name: "Add component", exact: true }).click();
  await fill(recipe.getByRole("group").nth(1), { "Component item code": "MATERIAL", "Exact base-UOM component quantity": "3.000" });
  const bom = await command(page, recipe, "Prepare versioned BOM", `${root}/boms`, "bom", true);
  await login(page, "browser-checker"); await enter(page, "", "", bom.id);
  const approve = page.getByRole("form", { name: "Approve exact BOM", exact: true }); await fill(approve, { Reason: "Independent exact base-UOM approval" });
  await command(page, approve, "Approve exact BOM", `${root}/boms/${bom.id}/approve`, "bom");
  await login(page, "browser-maker"); await enter(page, "", "", bom.id);
  const reserve = page.getByRole("form", { name: "Reserve whole material order", exact: true });
  await fill(reserve, { "Document number": "WORK-BROWSER", "Exact planned output quantity": "10", "Component location code": "MAIN/STOCK", "Finished location code": "MAIN/STOCK", "Component FIFO policy": "FIFO", "Finished FIFO policy with WIP offset": "MFG", "Native journal code": "STOCK", "WIP asset account": "WIP", "Abnormal scrap expense account": "SCRAP", "Open fiscal period ID": "period", "Posting date": "2026-10-04", Reason: "Actual governed material reservation" });
  const order = await command(page, reserve, "Reserve whole material order", `${root}/orders`, "order");
  const prepared = await phase(page, order.id, "prepare"); expect(prepared.issue_plan.total_cost_minor).toBe("2900");
  await phase(page, order.id, "review"); await phase(page, order.id, "post", "", true);
  const cancelled = await partial(page, order.id, "3", "1"); await phase(page, order.id, "review", cancelled.id); await phase(page, order.id, "cancel", cancelled.id, true);
  for (const [good, scrap] of [["3", "1"], ["6", "0"]]) {
    const child = await partial(page, order.id, good, scrap, good === "3");
    await phase(page, order.id, "review", child.id); const posted = await phase(page, order.id, "post", child.id, good === "6"); expect(posted.receipt_effect.posted_actor_id).toBe("erp-poster");
  }
  await login(page, "browser-maker"); await enter(page, order.id);
  await expect(page.getByRole("region", { name: "Original production and native financial evidence", exact: true })).toContainText("WIP: 0");
  await expect(page.getByRole("form", { name: "Prepare partial good output and abnormal scrap", exact: true })).toHaveCount(0);
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "Switch language", exact: true }).click();
  await expect(page.getByRole("heading", { name: "التنفيذ الصناعي بالتكلفة الفعلية", exact: true })).toBeVisible();
  await expect(page.locator("main#main-content")).toHaveAttribute("dir", "rtl");
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]); expect(errors).toEqual([]);
});
