import { expect, test, type Page } from "@playwright/test";

const enabled = process.env.RECONFORGE_LIVE_BROWSER_METRICS === "1";
const tenant = process.env.RECONFORGE_LIVE_BROWSER_TENANT ?? "browser-baseline-a";
const sibling = process.env.RECONFORGE_LIVE_BROWSER_SIBLING_TENANT ?? "browser-baseline-b";
const username = process.env.RECONFORGE_LIVE_BROWSER_USERNAME ?? "browser-live-admin";
const password = process.env.RECONFORGE_LIVE_BROWSER_PASSWORD ?? "Synthetic-browser-session-123!";

async function signIn(page: Page, selectedTenant: string) {
  await page.getByLabel("Tenant ID").fill(selectedTenant);
  await page.getByLabel("Username").fill(username);
  await page.getByLabel("Password").fill(password);
  const login = page.waitForResponse((response) => new URL(response.url()).pathname === "/api/v1/auth/browser/login");
  await page.getByRole("button", { name: "Sign in" }).click();
  const response = await login;
  expect(response.status()).toBe(200);
  const proof = (await response.json()).csrf_token as string;
  await expect(page.getByRole("heading", { name: "Confirm privileged access" })).toBeVisible();
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Confirm and continue" }).click();
  await expect(page.getByText("Privileged access is active")).toBeVisible();
  return proof;
}

test("real cookie sessions carry tenant scope across routes, recover expiry, and reject sibling access", async ({ page }) => {
  test.skip(!enabled, "requires two explicitly provisioned synthetic PostgreSQL tenants and metric snapshots (PROD-005)");
  await page.clock.install();
  await page.goto("/admin-audit");
  const proof = await signIn(page, tenant);
  const navigation = page.getByRole("navigation", { name: "Primary navigation" });
  const metrics = page.waitForResponse((response) => new URL(response.url()).pathname === "/api/v1/metrics/dashboard");
  await navigation.getByRole("button", { name: /Live Studio/ }).click();
  const response = await metrics;
  expect(response.status()).toBe(200);
  expect(response.request().headers()["x-reconforge-tenant"]).toBe(tenant);
  expect(response.request().headers()["x-reconforge-csrf"]).toBeUndefined();
  await expect(page.getByRole("cell", { name: "2026-10", exact: true })).toHaveCount(8);
  await expect(page.getByRole("cell", { name: "2026-09", exact: true })).toHaveCount(0);
  const denied = await page.evaluate(async (otherTenant) => {
    const response = await fetch("/api/v1/metrics/dashboard", { credentials: "same-origin", headers: { "X-ReconForge-Tenant": otherTenant } });
    const body = await response.json();
    return { status: response.status, code: body.error?.code, exposesMetrics: Object.hasOwn(body, "metrics") };
  }, sibling);
  expect(denied).toEqual({ status: 401, code: "invalid_token", exposesMetrics: false });
  expect(await page.evaluate(() => JSON.stringify({ ...localStorage }))).not.toContain(proof);
  expect(await page.evaluate(() => JSON.stringify({ ...sessionStorage }))).not.toContain(proof);

  await navigation.getByRole("button", { name: /Administration audit/ }).click();
  await expect(page.getByText("Privileged access is active")).toBeVisible();
  // Advance the browser clock to exercise proactive expiry; the server remains authoritative.
  await page.clock.fastForward(610_000);
  await expect(page.getByRole("heading", { name: "Confirm privileged access" })).toBeVisible();
  await expect(page.getByText("Privileged access is active")).toHaveCount(0);
  await navigation.getByRole("button", { name: /Live Studio/ }).click();
  await expect(page.getByRole("cell", { name: "2026-10", exact: true })).toHaveCount(8);
  await navigation.getByRole("button", { name: /Administration audit/ }).click();
  await expect(page.getByRole("heading", { name: "Confirm privileged access" })).toBeVisible();
  await page.clock.setFixedTime(new Date());
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Confirm and continue" }).click();
  await expect(page.getByText("Privileged access is active")).toBeVisible();

  await page.getByRole("button", { name: "Sign out / switch tenant" }).click();
  await expect(page.getByRole("heading", { name: "Sign in to administration" })).toBeVisible();
  const siblingProof = await signIn(page, sibling);
  await navigation.getByRole("button", { name: /Live Studio/ }).click();
  await expect(page.getByRole("cell", { name: "2026-09", exact: true })).toHaveCount(8);
  await expect(page.getByRole("cell", { name: "2026-10", exact: true })).toHaveCount(0);

  // Revoke through the real API to exercise recovery from a server-invalidated cookie.
  const logoutStatus = await page.evaluate(async ({ selectedTenant, csrfToken }) => {
    const response = await fetch("/api/v1/auth/logout", { method: "POST", credentials: "same-origin", headers: { "X-ReconForge-Tenant": selectedTenant, "X-ReconForge-CSRF": csrfToken } });
    return response.status;
  }, { selectedTenant: sibling, csrfToken: siblingProof });
  expect(logoutStatus).toBe(200);
  await navigation.getByRole("button", { name: /Administration audit/ }).click();
  await expect(page.getByRole("heading", { name: "Sign in to administration" })).toBeVisible();
  await expect(page.getByRole("table")).toHaveCount(0);
});
