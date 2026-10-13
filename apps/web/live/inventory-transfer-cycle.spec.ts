import { expect, test, type Locator, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { createHash } from "node:crypto";
import { writeFile } from "node:fs/promises";
import { join } from "node:path";

const base = process.env.RECONFORGE_ERP_LIVE_URL, tenant = process.env.RECONFORGE_ERP_TENANT, password = process.env.RECONFORGE_ERP_PASSWORD;
const source = JSON.parse(process.env.RECONFORGE_INVENTORY_TRANSFER_SOURCE ?? "null"), root = "/api/v1/inventory-transfer";
const losses: Array<{ path: string; mode: string; original_request_sha256: string; original_ack_sha256: string }> = [];
async function fill(form: Locator, values: Record<string, string>) { for (const [label, value] of Object.entries(values)) await form.getByLabel(label, { exact: true }).fill(value); }
async function login(page: Page, username: string) {
  await page.goto(`${base}/admin-audit`);
  await fill(page.locator("main"), { "Tenant ID": tenant!, Username: username, Password: password! });
  await page.getByRole("button", { name: "Sign in to administration", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Confirm privileged access", exact: true })).toBeVisible();
  await page.getByLabel("Password", { exact: true }).fill(password!);
  const response = page.waitForResponse(reply => reply.url().endsWith("/auth/step-up"));
  await page.getByRole("button", { name: "Confirm and continue", exact: true }).click();
  expect((await response).status()).toBe(200);
}
async function enter(page: Page, identifier = "") {
  await page.getByRole("navigation", { name: "Primary navigation", exact: true }).getByRole("button", { name: "Warehouse transfer", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Warehouse transfer", exact: true })).toBeVisible();
  const form = page.getByRole("form", { name: "Apply scope", exact: true });
  for (const [label, value] of Object.entries({ "Workspace ID": "work", "Organization ID": "org", "Legal entity ID": "entity" })) {
    const input = form.getByLabel(label, { exact: true }); await expect(input).toBeEnabled(); await input.fill(value);
  }
  const response = page.waitForResponse(reply => reply.url().endsWith(`${root}/transfers`) && reply.request().method() === "GET");
  await form.getByRole("button", { name: "Apply scope", exact: true }).click(); expect((await response).status()).toBe(200);
  const select = page.getByRole("combobox", { name: "Retained transfer", exact: true }); await expect(select).toBeEnabled();
  if (identifier) { await expect(select.locator(`option[value="${identifier}"]`)).toHaveCount(1); await select.selectOption(identifier); }
}
async function command(page: Page, form: Locator, label: string, path: string, lost = false) {
  let body = "", retained: unknown, mode = "suppressed-committed-response", finish!: () => void;
  const done = new Promise<void>(resolve => { finish = resolve; });
  if (lost) await page.route(`**${path}`, async route => {
    if (route.request().method() !== "POST") { await route.continue(); return; }
    body = route.request().postData()!;
    try { const response = await route.fetch(); expect(response.status()).toBe(200); retained = await response.json(); }
    catch (caught) { if (!(caught instanceof Error) || !/^route\.fetch: Timeout 20000ms exceeded\./.test(caught.message)) throw caught; mode = "transport-timeout-outcome-unknown"; }
    await route.abort("failed"); finish();
  }, { times: 1 });
  let response = lost ? null : page.waitForResponse(reply => reply.url().endsWith(path) && reply.request().method() === "POST");
  const button = form.getByRole("button", { name: label, exact: true }); await expect(button).toBeEnabled(); await button.click();
  if (lost) {
    await done; const retry = page.getByRole("button", { name: "Retry original command", exact: true }); await expect(retry).toBeVisible();
    response = page.waitForResponse(reply => reply.url().endsWith(path) && reply.request().method() === "POST"); await retry.click();
  }
  const reply = await response!; expect(reply.status()).toBe(200); const received = await reply.json();
  expect(received.command_ack.transfer_id).toBe(received.source.id); expect(received.command_ack.actor_id).toBe(received.source[{ create: "creator_actor_id", "inverse-create": "creator_actor_id", review: "reviewer_actor_id", post: "poster_actor_id" }[received.command_ack.operation as "create" | "inverse-create" | "review" | "post"]]);
  if (lost) {
    expect(reply.request().postData()).toBe(body); if (retained !== undefined) expect(received).toEqual(retained);
    const replay = await page.request.fetch(reply.request()); expect(replay.status()).toBe(200); expect(await replay.json()).toEqual(received);
    losses.push({ path, mode, original_request_sha256: createHash("sha256").update(body).digest("hex"), original_ack_sha256: createHash("sha256").update(JSON.stringify(received)).digest("hex") });
  }
  const refresh = page.getByRole("button", { name: "Refresh original transfers", exact: true }); await expect(refresh).toBeEnabled();
  const current = page.waitForResponse(value => value.url().endsWith(`${root}/transfers`) && value.request().method() === "GET"); await refresh.click();
  const read = await current; expect(read.status()).toBe(200);
  expect((await read.json()).transfers.find((row: { id: string }) => row.id === received.source.id)).toEqual(received.source);
  await expect(page.getByRole("heading", { name: `${received.source.number} · ${["Draft", "Reviewed", "Posted", "Cancelled"][received.source.phase]}`, exact: true })).toBeVisible();
  return received;
}
async function phase(page: Page, id: string, operation: "review" | "post", lost = false) {
  await login(page, operation === "review" ? "browser-checker" : "browser-poster"); await enter(page, id);
  const form = page.getByRole("form", { name: "Review and reserve original stock", exact: true });
  await fill(form, { Reason: `Actual independent ${operation}` });
  return command(page, form, operation === "review" ? "Review and reserve original stock" : "Post reviewed transfer", `${root}/transfers/${id}/${operation}`, lost);
}

test("actual same-entity two-warehouse transfer and independent original inverse preserve FIFO GL and retained replies", async ({ page }) => {
  test.setTimeout(240_000);
  const artifacts = process.env.RECONFORGE_ERP_BROWSER_ARTIFACTS;
  expect(base && tenant && password && artifacts && source?.schema_version === "inventory-transfer-browser-v1" && source?.transfer?.quantity === "1", "Original approved IRP fixture and private runtime configuration required").toBeTruthy();
  const errors: string[] = []; page.on("pageerror", error => errors.push(error.message));
  await login(page, "browser-maker"); await enter(page);
  const prepare = page.getByRole("form", { name: "Prepare warehouse transfer", exact: true });
  await fill(prepare, { "Transfer number": source.transfer.number, "Item code": source.transfer.item_code, "Exact base-unit quantity": source.transfer.quantity,
    "Source warehouse/location": source.transfer.from_location, "Destination warehouse/location": source.transfer.to_location,
    "Open fiscal period ID": source.transfer.period_id, "Business date": source.transfer.posting_date, Reason: source.transfer.reason });
  const created = await command(page, prepare, "Prepare warehouse transfer", `${root}/transfers`, true);
  expect(created.source.cost_snapshot.remaining_quantity_scaled).toBe("3"); expect(created.source.cost_snapshot.remaining_value_minor).toBe("3600");
  const reviewed = await phase(page, created.source.id, "review"); expect(reviewed.source.claim.state).toBe("Active");
  const posted = await phase(page, created.source.id, "post", true); expect(posted.source.claim.state).toBe("Posted");
  expect(posted.source.native_response.head.status).toBe("Posted"); expect(posted.source.release.target_movement_id).toBe(posted.source.native_movement_id);
  await login(page, "browser-maker"); await enter(page, posted.source.id);
  const inverse = page.getByRole("form", { name: "Prepare independent inverse", exact: true });
  await fill(inverse, { "Inverse number": "TRANSFER-BROWSER-INVERSE", "Open fiscal period ID": "period", "Business date": "2026-10-14", Reason: "Actual independently governed physical compensation" });
  const child = await command(page, inverse, "Prepare independent inverse", `${root}/transfers/${posted.source.id}/inverse`, true);
  expect(child.source.original.id).toBe(posted.source.id); expect(child.source.from_location_id).toBe(posted.source.to_location_id); expect(child.source.to_location_id).toBe(posted.source.from_location_id);
  await phase(page, child.source.id, "review"); const compensated = await phase(page, child.source.id, "post", true);
  expect(compensated.source.cost_snapshot).toEqual(posted.source.cost_snapshot); expect(compensated.source.review_cost_snapshot).toEqual(posted.source.review_cost_snapshot);
  const originals: Array<{ subject: string; bytes: number; sha256: string }> = [];
  for (const id of [posted.source.id, compensated.source.id]) {
    const response = await page.request.get(`${base}${root}/transfers/${id}/evidence`, { headers: { "X-ReconForge-Tenant": tenant!, "X-ReconForge-Workspace": "work", "X-ReconForge-Organization": "org", "X-ReconForge-Legal-Entity": "entity" } });
    expect(response.status()).toBe(200); const raw = await response.body(), evidence = JSON.parse(raw.toString("utf8"));
    expect(evidence.source.id).toBe(id); expect(evidence.events).toHaveLength(3); expect(evidence.commands).toHaveLength(3);
    await writeFile(join(artifacts!, `inventory-transfer-${id}-evidence.json`), raw, { flag: "wx" });
    originals.push({ subject: id, bytes: raw.length, sha256: createHash("sha256").update(raw).digest("hex") });
  }
  await writeFile(join(artifacts!, "inventory-transfer-browser-wire.json"), JSON.stringify({ schema_version: "inventory-transfer-browser-wire-v1", originals, retained_losses: losses, current_scope: source.scope,
    forward_subject: posted.source.id, inverse_subject: compensated.source.id, browser_inventory_writes: true, transfer_new_gl_effects: 0, browser_only_fixture_documents_created: true }, null, 2) + "\n", { flag: "wx" });
  expect(losses).toHaveLength(4); expect(errors).toEqual([]);
  const accessibility = await new AxeBuilder({ page }).include("main").analyze(); expect(accessibility.violations.filter(row => ["critical", "serious"].includes(row.impact ?? ""))).toEqual([]);
});
