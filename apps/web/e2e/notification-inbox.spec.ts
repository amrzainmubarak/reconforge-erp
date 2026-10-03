import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const notification = {
  id: "inbox_1",
  workspace_id: "default",
  organization_id: "",
  legal_entity_id: "",
  recipient_id: "reviewer",
  topic: "workflow.review_required",
  resource_type: "approval",
  resource_id: "APR-1",
  payload_digest: "1".repeat(64),
  created_at: "2026-10-03T00:00:00Z",
  read_at: null,
};

test("notification inbox signs in, reads a retained item, and remains accessible", async ({ page }) => {
  let acknowledged = false;
  await page.route("**/api/v1/auth/browser/login", async (route) => {
    expect(route.request().method()).toBe("POST");
    expect(route.request().postDataJSON()).toEqual({ username: "reviewer", password: "Synthetic-123" });
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ csrf_token: "csrf-proof", expires_at: "2029-01-01T00:00:00Z" }),
    });
  });
  await page.route("**/api/v1/notifications/workspaces", (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({ workspaces: ["default"] }),
  }));
  await page.route("**/api/v1/notifications/inbox?*", (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({
      records: [{ ...notification, read_at: acknowledged ? "2026-10-03T00:01:00Z" : null }],
      total: 1,
      unread_count: acknowledged ? 0 : 1,
    }),
  }));
  await page.route("**/api/v1/notifications/inbox/inbox_1/read?*", async (route) => {
    expect(route.request().method()).toBe("POST");
    expect(route.request().headers()["x-reconforge-csrf"]).toBe("csrf-proof");
    acknowledged = true;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ ...notification, read_at: "2026-10-03T00:01:00Z" }),
    });
  });

  await page.goto("/notifications");
  await expect(page.getByRole("heading", { name: "Notification inbox" })).toBeVisible();
  await page.getByLabel("Tenant").fill("local");
  await page.getByLabel("Username").fill("reviewer");
  await page.getByLabel("Password").fill("Synthetic-123");
  await page.getByRole("button", { name: "Sign in" }).click();

  await expect(page.locator(".inbox-results [role=status]")).toHaveText("Notifications: 1 · Unread: 1");
  await expect(page.getByText("APR-1", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Mark as read: APR-1" }).click();
  await expect(page.locator(".inbox-results [role=status]")).toHaveText("Notifications: 1 · Unread: 0");
  await expect(page.getByText("Read acknowledgement: 2026-10-03T00:01:00Z")).toBeVisible();

  const accessibility = await new AxeBuilder({ page }).include(".inbox-workspace").analyze();
  expect(accessibility.violations).toEqual([]);
});
