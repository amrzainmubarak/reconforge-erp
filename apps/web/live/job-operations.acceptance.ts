import { expect, test, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
const base = process.env.RECONFORGE_GFO_LIVE_URL;
if (!base) throw new Error("RECONFORGE_GFO_LIVE_URL must name the owned integrated HTTPS GFO runtime.");
const tenant = process.env.RECONFORGE_GFO_JOB_TENANT ?? "local";
const workspace = process.env.RECONFORGE_GFO_JOB_WORKSPACE ?? "default";
const organization = process.env.RECONFORGE_GFO_JOB_ORGANIZATION ?? "ORG-GFO";
const entity = process.env.RECONFORGE_GFO_JOB_ENTITY ?? "ENTITY-GFO";
const password = process.env.RECONFORGE_GFO_LIVE_PASSWORD ?? "Synthetic-Gfo-2026-Only";

async function signIn(page: Page, username: string, privileged: boolean) {
  await page.getByLabel("Tenant", { exact: true }).fill(tenant);
  await page.getByLabel("Username", { exact: true }).fill(username);
  await page.getByLabel("Password", { exact: true }).fill(password);
  const loginReply = page.waitForResponse(r => r.url().endsWith("/auth/browser/login") && r.request().method() === "POST");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  const login = await loginReply; expect(login.status(), await login.text()).toBe(200);
  await expect(page.getByRole("button", { name: "Sign out", exact: true })).toBeVisible();
  if (privileged) {
    await expect(page.getByRole("heading", { name: "Reauthenticate before operator actions", exact: true })).toBeVisible();
    const elevatedReply = page.waitForResponse(r => r.url().endsWith("/auth/step-up") && r.request().method() === "POST");
    await page.getByLabel("Password", { exact: true }).fill(password);
    await page.getByRole("button", { name: "Reauthenticate", exact: true }).click();
    const elevated = await elevatedReply; expect(elevated.status(), await elevated.text()).toBe(200);
    await expect(page.getByRole("button", { name: "Reauthenticate", exact: true })).toHaveCount(0);
  }
  await page.getByLabel("Workspace ID").selectOption(workspace);
  await page.getByLabel("Organization ID").fill(organization);
  await page.getByLabel("Entity ID").fill(entity);
  await page.getByRole("button", { name: "Load execution lane" }).click();
}

test("real persisted job operator lifecycle, read-only controls and mobile", async ({ page }) => {
  test.setTimeout(120_000);
  await page.goto(`${base}/jobs`);
  await signIn(page, "gfo-reader", false);
  await page.getByRole("button", { name: "Inspect job: GFO-job-queued" }).click();
  await expect(page.getByText("CREATED", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Cancel job", exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await signIn(page, "gfo-admin", true);
  await page.getByRole("button", { name: "Inspect job: GFO-job-queued" }).click();
  const cancelledReply = page.waitForResponse(r => r.url().includes("/durable-jobs/") && r.url().includes("/cancel") && r.request().method() === "POST");
  await page.getByRole("button", { name: "Cancel job", exact: true }).click();
  const cancelled = await cancelledReply; expect(cancelled.status(), await cancelled.text()).toBe(200);
  expect((await cancelled.json()).job.status).toBe("cancelled");
  await page.reload();
  await signIn(page, "gfo-admin", true);
  await page.getByRole("button", { name: "Inspect job: GFO-job-queued" }).click();
  await expect(page.getByText("CANCELLED", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Inspect job: GFO-job-failed" }).click();
  const requeuedReply = page.waitForResponse(r => r.url().includes("/durable-jobs/") && r.url().includes("/requeue") && r.request().method() === "POST");
  await page.getByRole("button", { name: "Requeue job", exact: true }).click();
  const requeued = await requeuedReply; expect(requeued.status(), await requeued.text()).toBe(200);
  expect((await requeued.json()).job.status).toBe("queued");
  await page.getByRole("button", { name: "Inspect job: GFO-job-failed" }).click();
  await expect(page.getByText("REQUEUED", { exact: true })).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole("main")).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  expect((await new AxeBuilder({ page }).include("#main-content").analyze()).violations).toEqual([]);
});
