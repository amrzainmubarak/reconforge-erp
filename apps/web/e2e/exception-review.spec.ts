import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const identity = {
  id: "reviewer-1",
  username: "reviewer",
  permissions: ["exceptions.read", "exceptions.manage"],
  principal_type: "user",
  authorized_scopes: { workspaces: ["workspace-a"], organizations: [], legal_entities: [] },
};
const record = {
  id: "EXC-001", workspace_id: "workspace-a", organization_id: "org-a", legal_entity_id: "entity-a",
  source_type: "control_run", source_id: "RUN-001", period_name: "2026-10", entity_code: "ENTITY-A", account_code: "1100", control_code: "MATCH-DIFF",
  risk_rating: "high", owner: "reviewer-1", status: "In Review", escalation_level: "standard", sla_target_date: "2026-10-31",
  description: "Amount variance needs a retained decision.", created_at: "2026-10-03T10:00:00Z", updated_at: "2026-10-03T11:00:00Z", row_version: 2,
};
const history = {
  id: "EXH-001", exception_id: "EXC-001", action: "exception_review_assigned", from_status: "Open", to_status: "In Review", from_owner: "", to_owner: "reviewer-1",
  actor_label: "manager", actor_id: "manager-1", reason: "", occurred_at: "2026-10-03T11:00:00Z", audit_event_id: "AUD-001", outbox_event_id: "OUT-001",
};

test("exception review signs in, enforces browser scope and CSRF, and preserves authoritative evidence links", async ({ page }) => {
  let current = { ...record, history: [history], history_page: { limit: 25, has_more: false, next_cursor: null } };
  await page.route("**/api/v1/auth/browser/login", async (route) => {
    expect(route.request().method()).toBe("POST");
    expect(route.request().postDataJSON()).toEqual({ username: "reviewer", password: "Synthetic-123" });
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ csrf_token: "csrf-proof", expires_at: "2029-01-01T00:00:00Z" }) });
  });
  await page.route("**/api/v1/auth/me", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(identity) }));
  await page.route("**/api/v1/exceptions**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const headers = request.headers();
    expect(headers["x-reconforge-tenant"]).toBe("local");
    expect(headers["x-reconforge-workspace"]).toBe("workspace-a");
    if (url.pathname.endsWith("/assign")) {
      expect(request.method()).toBe("POST");
      expect(headers["x-reconforge-csrf"]).toBe("csrf-proof");
      expect(request.postDataJSON()).toEqual({ owner: "reviewer-2", expected_version: 2 });
      current = { ...current, owner: "reviewer-2", row_version: 3, history: [{ ...history, id: "EXH-002", to_owner: "reviewer-2", audit_event_id: "AUD-002", outbox_event_id: "OUT-002" }] };
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ exception: current }) });
      return;
    }
    if (url.pathname.endsWith("/status")) {
      expect(request.method()).toBe("POST");
      expect(headers["x-reconforge-csrf"]).toBe("csrf-proof");
      expect(request.postDataJSON()).toEqual({ status: "Resolved", expected_version: 3, reason: "Source corrected." });
      current = { ...current, status: "Resolved", row_version: 4, history: [{ ...history, id: "EXH-003", action: "exception_review_transition", from_status: "In Review", to_status: "Resolved", to_owner: "reviewer-2", reason: "Source corrected.", audit_event_id: "AUD-003", outbox_event_id: "OUT-003" }] };
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ exception: current }) });
      return;
    }
    if (url.pathname === "/api/v1/exceptions/EXC-001") {
      expect(request.method()).toBe("GET");
      expect(headers["x-reconforge-csrf"]).toBeUndefined();
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ exception: current }) });
      return;
    }
    expect(url.pathname).toBe("/api/v1/exceptions");
    expect(request.method()).toBe("GET");
    expect(headers["x-reconforge-csrf"]).toBeUndefined();
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ exceptions: [record], pagination: { limit: 25, returned: 1, has_more: false, next_cursor: null } }) });
  });

  await page.goto("/exceptions");
  await expect(page.getByRole("heading", { name: "Exception review" })).toBeVisible();
  await page.getByLabel("Tenant").fill("local");
  await page.getByLabel("Username").fill("reviewer");
  await page.getByLabel("Password").fill("Synthetic-123");
  await page.getByRole("button", { name: "Sign in to review exceptions" }).click();
  await page.getByRole("button", { name: "Review" }).click();
  await expect(page.getByRole("heading", { name: "Exception details" })).toBeVisible();
  await expect(page.getByText("AUD-001", { exact: true })).toBeVisible();
  await expect(page.getByText("OUT-001", { exact: true })).toBeVisible();

  await page.getByLabel("Reviewer user ID").fill("reviewer-2");
  await page.getByRole("button", { name: "Assign reviewer" }).click();
  await expect(page.getByText("The server confirmed the action and returned the current record version.")).toBeVisible();
  await page.getByLabel("Recorded reason").fill("Source corrected.");
  await page.getByRole("button", { name: "Submit decision" }).click();
  await expect(page.getByRole("cell", { name: "Resolved", exact: true })).toBeVisible();
  await expect(page.getByText("AUD-003", { exact: true })).toBeVisible();
  await expect(page.getByText("OUT-003", { exact: true })).toBeVisible();
  const accessibility = await new AxeBuilder({ page }).include(".exception-review-workspace").analyze();
  expect(accessibility.violations).toEqual([]);
});

test("exception review stays responsive, accessible, and RTL-aware", async ({ page }) => {
  await page.route("**/api/v1/auth/browser/login", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ csrf_token: "csrf-proof", expires_at: "2029-01-01T00:00:00Z" }) }));
  await page.route("**/api/v1/auth/me", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(identity) }));
  await page.route("**/api/v1/exceptions**", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ exceptions: [record], pagination: { limit: 25, returned: 1, has_more: false, next_cursor: null } }) }));
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/exceptions");
  await page.getByLabel("Tenant").fill("local");
  await page.getByLabel("Username").fill("reviewer");
  await page.getByLabel("Password").fill("Synthetic-123");
  await page.getByRole("button", { name: "Sign in to review exceptions" }).click();
  const table = page.locator(".exception-review-table");
  await expect(table).toBeVisible();
  await expect(table).toHaveAttribute("tabindex", "0");
  await expect(table).toHaveCSS("overflow-x", "auto");
  const accessibility = await new AxeBuilder({ page }).include(".exception-review-workspace").analyze();
  expect(accessibility.violations).toEqual([]);
  await page.getByTestId("locale-toggle").click();
  await expect(page.getByRole("main")).toHaveAttribute("dir", "rtl");
  await expect(page.getByRole("heading", { name: "مراجعة الاستثناءات" })).toBeVisible();
});
