import { expect, test } from "@playwright/test";

const enabled = process.env.RECONFORGE_LIVE_BROWSER_SESSION === "1";
const mutationEnabled = process.env.RECONFORGE_LIVE_BROWSER_SESSION_REVOCATION === "1";
const userStatusMutationEnabled = process.env.RECONFORGE_LIVE_BROWSER_USER_STATUS === "1";
const accessMutationEnabled = process.env.RECONFORGE_LIVE_BROWSER_ACCESS_MUTATIONS === "1";
const tenantId = process.env.RECONFORGE_LIVE_BROWSER_TENANT ?? "browser-live-tenant";
const username = process.env.RECONFORGE_LIVE_BROWSER_USERNAME ?? "browser-live-admin";
const password = process.env.RECONFORGE_LIVE_BROWSER_PASSWORD ?? "Synthetic-browser-session-123!";
const targetUsername = process.env.RECONFORGE_LIVE_BROWSER_TARGET_USERNAME ?? "browser-live-target";

test.skip(!enabled, "requires an explicitly provisioned local API proxy target");

test("same-origin browser sign-in uses the HttpOnly session cookie without a bearer token", async ({ page }) => {
  const statusByPath = new Map<string, number>();
  page.on("response", (response) => {
    const path = new URL(response.url()).pathname;
    if (path.startsWith("/api/v1/")) statusByPath.set(path, response.status());
  });
  await page.goto("/admin-audit");
  await page.getByLabel("Tenant ID").fill(tenantId);
  await page.getByLabel("Username").fill(username);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Confirm privileged access" })).toBeVisible();
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Confirm and continue" }).click();
  await expect(page.getByRole("heading", { name: "Security control snapshot" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Identity and session snapshot" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Access-policy snapshot" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Integration and retention snapshot" })).toBeVisible();
  await expect(
    page.getByLabel("Identity and session snapshot").getByText(username, { exact: true }).first(),
  ).toBeVisible();
  await expect(page.getByText("roles.manage", { exact: true })).toBeVisible();
  await expect(page.getByText("Authorized integrations", { exact: true })).toBeVisible();

  const cookies = await page.context().cookies();
  const session = cookies.find((cookie) => cookie.name === "__Host-reconforge_session");
  expect(session).toMatchObject({ httpOnly: true, secure: true, sameSite: "Strict", path: "/" });

  const currentUser = await page.evaluate(async (requestedTenant) => {
    const response = await fetch("/api/v1/auth/me", {
      credentials: "same-origin",
      headers: { "X-ReconForge-Tenant": requestedTenant },
    });
    return { status: response.status, body: await response.json() };
  }, tenantId);
  expect(currentUser.status).toBe(200);
  expect(currentUser.body).toMatchObject({ username });
  expect(JSON.stringify(currentUser.body)).not.toContain("access_token");
  for (const path of [
    "/api/v1/auth/browser/login",
    "/api/v1/auth/step-up",
    "/api/v1/admin/audit/events",
    "/api/v1/admin/audit/verify",
    "/api/v1/admin/security/overview",
    "/api/v1/admin/identity/users",
    "/api/v1/admin/identity/sessions",
    "/api/v1/admin/access/permissions",
    "/api/v1/admin/access/roles",
    "/api/v1/admin/security/integrations",
    "/api/v1/admin/security/retention-policies",
    "/api/v1/auth/me",
  ]) expect(statusByPath.get(path)).toBe(200);
});

test("same-origin browser revokes its current synthetic session only after explicit confirmation", async ({ page }) => {
  test.skip(!mutationEnabled, "requires explicit opt-in because this revokes the current synthetic session");
  const statusByPath = new Map<string, number>();
  page.on("response", (response) => {
    const path = new URL(response.url()).pathname;
    if (path.startsWith("/api/v1/")) statusByPath.set(path, response.status());
  });
  await page.goto("/admin-audit");
  await page.getByLabel("Tenant ID").fill(tenantId);
  await page.getByLabel("Username").fill(username);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Confirm privileged access" })).toBeVisible();
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Confirm and continue" }).click();
  await expect(page.getByRole("heading", { name: "Identity and session snapshot" })).toBeVisible();
  await page.getByRole("button", { name: "Revoke session" }).first().click();
  await expect(page.getByRole("heading", { level: 3, name: "Revoke authorized session" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Revoke selected session" })).toBeDisabled();
  await page.getByLabel("Type REVOKE to confirm").fill("REVOKE");
  await page.getByRole("button", { name: "Revoke selected session" }).click();
  await expect(page.getByText("Your current session was revoked. Sign in again to continue.")).toBeVisible();
  await expect(page.getByRole("heading", { level: 2, name: "Sign in to administration" })).toBeVisible();
  expect(statusByPath.get("/api/v1/admin/identity/sessions")).toBe(200);
  expect(statusByPath.get("/api/v1/admin/identity/sessions/")).toBeUndefined();
  expect([...statusByPath.entries()].find(([path]) => path.endsWith("/revoke"))?.[1]).toBe(200);
  const rendered = await page.locator("main").innerText();
  expect(rendered).not.toMatch(/audit_event_id|state_digest|[a-f0-9]{64}/i);
});

test("same-origin browser disables and re-enables one synthetic target without restoring its sessions", async ({ page }) => {
  test.skip(!userStatusMutationEnabled, "requires an explicitly provisioned synthetic target user");
  const statusResponses: number[] = [];
  page.on("response", (response) => {
    if (new URL(response.url()).pathname.endsWith("/status")) statusResponses.push(response.status());
  });
  await page.goto("/admin-audit");
  await page.getByLabel("Tenant ID").fill(tenantId);
  await page.getByLabel("Username").fill(username);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Confirm privileged access" })).toBeVisible();
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Confirm and continue" }).click();
  const usersTable = page.getByRole("table", { name: "Authorized users" });
  const targetUser = usersTable.getByRole("row", { name: new RegExp(targetUsername) });
  await targetUser.getByRole("button", { name: "Disable user" }).click();
  await expect(page.getByRole("button", { name: "Disable selected user" })).toBeDisabled();
  await page.getByLabel("Type DISABLE to confirm").fill("DISABLE");
  await page.getByRole("button", { name: "Disable selected user" }).click();
  await expect(page.getByText("The user was disabled and audit evidence was recorded.")).toBeVisible();
  await expect(targetUser).toContainText("Disabled");
  await expect(targetUser).toContainText("0");
  const targetSession = page.getByRole("table", { name: "Authorized sessions" }).getByRole("row", { name: new RegExp(targetUsername) }).first();
  await expect(targetSession).toContainText("revoked");
  await targetUser.getByRole("button", { name: "Enable user" }).click();
  await page.getByLabel("Type ENABLE to confirm").fill("ENABLE");
  await page.getByRole("button", { name: "Enable selected user" }).click();
  await expect(page.getByText("The user was enabled and audit evidence was recorded.")).toBeVisible();
  await expect(targetUser).toContainText("Active");
  await expect(targetUser).toContainText("0");
  await expect(targetSession).toContainText("revoked");
  expect(statusResponses).toEqual([200, 200]);
  const rendered = await page.locator("main").innerText();
  expect(rendered).not.toMatch(/audit_event_id|state_digest|[a-f0-9]{64}/i);
});

test("same-origin browser governs a synthetic role lifecycle and exact target assignment", async ({ page }) => {
  test.skip(!accessMutationEnabled, "requires an explicitly provisioned synthetic access target");
  const mutationStatuses: number[] = [];
  page.on("response", (response) => {
    const path = new URL(response.url()).pathname;
    if (path.startsWith("/api/v1/admin/access/") && response.request().method() !== "GET") mutationStatuses.push(response.status());
  });
  await page.goto("/admin-audit");
  await page.getByLabel("Tenant ID").fill(tenantId);
  await page.getByLabel("Username").fill(username);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Confirm privileged access" })).toBeVisible();
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Confirm and continue" }).click();
  await expect(page.getByRole("heading", { name: "Access-policy snapshot" })).toBeVisible();
  await page.getByRole("button", { name: "Create role" }).click();
  await page.getByLabel("Role name").fill("browser_reviewer");
  await page.getByLabel("Description", { exact: true }).fill("Synthetic browser reviewer");
  await page.getByRole("checkbox", { name: /audit\.read/ }).check();
  await page.getByPlaceholder("CREATE").fill("CREATE");
  await page.getByRole("button", { name: "Apply governed change" }).click();
  const rolesTable = page.getByRole("table", { name: "Authorized roles" });
  const reviewerRole = rolesTable.getByRole("row", { name: /browser_reviewer/ });
  await expect(reviewerRole).toBeVisible();
  await reviewerRole.getByRole("button", { name: "Edit permissions" }).click();
  await page.getByRole("checkbox", { name: /audit\.verify/ }).check();
  await page.getByPlaceholder("APPLY").fill("APPLY");
  await page.getByRole("button", { name: "Apply governed change" }).click();
  await expect(reviewerRole).toContainText("audit.verify");
  const assignmentsTable = page.getByRole("table", { name: "User role assignments" });
  const targetAssignment = assignmentsTable.getByRole("row", { name: new RegExp(targetUsername) });
  await targetAssignment.getByRole("button", { name: "Manage roles" }).click();
  await page.getByRole("checkbox", { name: /observer/ }).uncheck();
  await page.getByRole("checkbox", { name: /browser_reviewer/ }).check();
  await page.getByPlaceholder("ASSIGN").fill("ASSIGN");
  await page.getByRole("button", { name: "Apply governed change" }).click();
  await expect(targetAssignment).toContainText("browser_reviewer");
  const targetSession = page.getByRole("table", { name: "Authorized sessions" }).getByRole("row", { name: new RegExp(targetUsername) }).first();
  await expect(targetSession).toContainText("revoked");
  await reviewerRole.getByRole("button", { name: "Retire role" }).click();
  await page.getByPlaceholder("RETIRE").fill("RETIRE");
  await page.getByRole("button", { name: "Apply governed change" }).click();
  await expect(reviewerRole).toContainText("Retired");
  await expect(targetAssignment).toContainText("No roles");
  await reviewerRole.getByRole("button", { name: "Reactivate role" }).click();
  await page.getByPlaceholder("REACTIVATE").fill("REACTIVATE");
  await page.getByRole("button", { name: "Apply governed change" }).click();
  await expect(reviewerRole).toContainText("Active");
  await expect(targetAssignment).toContainText("No roles");
  await expect(targetSession).toContainText("revoked");
  expect(mutationStatuses).toEqual([200, 200, 200, 200, 200]);
  const rendered = await page.locator("main").innerText();
  expect(rendered).not.toMatch(/audit_event_id|state_digest|[a-f0-9]{64}/i);
});
