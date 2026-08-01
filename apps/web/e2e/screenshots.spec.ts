import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const screenshotRoot = "../../docs/assets/screenshots";

async function capture(page: import("@playwright/test").Page, filename: string, fullPage: boolean) {
  if (process.env.RECONFORGE_UPDATE_SCREENSHOTS === "1") {
    await page.screenshot({ path: `${screenshotRoot}/${filename}`, fullPage, animations: "disabled" });
    return;
  }
  const image = await page.screenshot({ fullPage, animations: "disabled" });
  expect(image.byteLength).toBeGreaterThan(1_000);
}

test("captures the real desktop workspace pages and Arabic RTL mode", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Control room");
  await expect(page.getByText("Local-first workspace", { exact: true }).last()).toBeVisible();
  await expect(page.getByText("Guided control story", { exact: true })).toBeVisible();
  await expect(page.getByText("Close readiness", { exact: true })).toBeVisible();
  await expect(page.getByText("Entity readiness", { exact: true })).toBeVisible();
  await capture(page, "dashboard.png", true);

  const primaryNavigation = page.getByRole("navigation", { name: "Primary navigation" });
  await primaryNavigation.getByRole("button", { name: /Exceptions/ }).click();
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Exception queue");
  await expect(page.getByText(/SYN-EXC-/).first()).toBeVisible();
  await capture(page, "exception-queue.png", true);

  await primaryNavigation.getByRole("button", { name: /Evidence binder/ }).click();
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Evidence binder");
  await expect(page.getByText(/EVD-SYN-/).first()).toBeVisible();
  await capture(page, "evidence-binder.png", true);

  await primaryNavigation.getByRole("button", { name: /Inventory controls/ }).click();
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Inventory control center");
  await expect(page.getByText("SYN-PART-001")).toBeVisible();
  await capture(page, "inventory-control.png", true);
  await page.getByRole("tab", { name: "Counts" }).click();
  await expect(page.getByText("COUNT/SYN/0024")).toBeVisible();
  await capture(page, "inventory-planning.png", true);
  await page.getByRole("tab", { name: "FIFO valuation" }).click();
  await expect(page.getByRole("tabpanel").getByText("VAL/SYN/0048", { exact: true })).toBeVisible();
  await expect(page.getByText("IV-VAL/SYN/0048")).toBeVisible();
  await expect(page.getByText("IVR/SYN/0032", { exact: true })).toBeVisible();
  await expect(page.getByRole("cell", { name: /^IVR-IVR\/SYN\/0032/ })).toBeVisible();
  await capture(page, "inventory-valuation.png", true);

  await primaryNavigation.getByRole("button", { name: /^Dashboard/ }).click();
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Control room");

  await page.getByTestId("locale-toggle").click();
  await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("مركز الرقابة");
  await capture(page, "rtl-arabic.png", true);
});

test("captures the real mobile dashboard", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await expect(page.getByRole("navigation", { name: "Mobile navigation" })).toBeVisible();
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Control room");
  await capture(page, "mobile-dashboard.png", false);
});

test("Mapping Studio keeps invalid financial inputs visible through keyboard flow", async ({ page }) => {
  await page.goto("/mapping");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Map source columns");
  const mappings = page.getByRole("combobox");
  await expect(mappings).toHaveCount(4);
  await mappings.nth(0).selectOption("txn_id");
  await mappings.nth(1).selectOption("amount_text");
  await mappings.nth(2).selectOption("currency_code");
  await mappings.nth(3).selectOption("posting_date");
  await expect(page.getByText("2 issues", { exact: true })).toBeVisible();
  await expect(page.getByText(/Row 2: amount — missing value/)).toBeVisible();
  await expect(page.getByText(/Row 3: amount — malformed amount/)).toBeVisible();
  await mappings.nth(0).focus();
  await expect(mappings.nth(0)).toBeFocused();
  await page.getByTestId("locale-toggle").click();
  await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("اربط أعمدة المصدر");
});

test("Rule Studio requires same-version tests and independent human approval", async ({ page }) => {
  await page.goto("/rules");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Test and approve rules");
  await expect(page.getByText("Disabled", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Run tests" }).click();
  await expect(page.getByText("2/2", { exact: true })).toBeVisible();
  await page.getByLabel("Reviewer").fill("reviewer");
  await page.getByLabel("Approval reason").fill("Synthetic evidence reviewed");
  await page.getByRole("button", { name: "Approve tested draft" }).click();
  await expect(page.getByText("Approved by reviewer")).toBeVisible();
  await page.getByRole("button", { name: "Create new version" }).click();
  await expect(page.getByText(/v2/)).toBeVisible();
  await expect(page.getByText("Approved by reviewer")).toHaveCount(0);
});

test("Live Studio uses the authorized contract and never masks permission failure", async ({ page }) => {
  let permitted = false;
  await page.route("**/api/v1/metrics/dashboard", async (route) => {
    if (!permitted) return route.fulfill({ status: 403, contentType: "application/json", body: JSON.stringify({ detail: "forbidden" }) });
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ metrics: [{ id: "m1", workspace_id: "w1", metric_key: "match_rate", period_name: "2026-07", value: 88, value_text: "88.00", lineage: "approved matches", computed_at: new Date().toISOString(), name: "Match rate", description: "Rate" }] }) });
  });
  await page.goto("/live");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Authorized operational metrics");
  await expect(page.getByText("Live Studio metrics.read permission is required.")).toBeVisible();
  await expect(page.getByText("Synthetic local demo data only")).toHaveCount(0);
  permitted = true;
  await page.getByRole("button", { name: "Retry authorized request" }).click();
  await expect(page.getByRole("row", { name: /Match rate/ })).toContainText("88.00");
  await expect(page.getByRole("row", { name: /Match rate/ })).toContainText("approved matches");
});

test("Administration audit requires sign-in and step-up before rendering only redacted fields", async ({ page }) => {
  let sessionRevoked = false;
  let targetDisabled = false;
  let targetLifecycleVersion = 1;
  let targetSessionRevoked = false;
  let targetRoleNames = ["observer"];
  let customRole: Record<string, unknown> | null = null;
  let integrationDisabled = false;
  let retentionPolicy: Record<string, unknown> | null = null;
  let evidenceRetentionVersion = 1;
  await page.route("**/api/v1/auth/browser/login", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ csrf_token: "csrf-proof", expires_at: "2026-07-30T10:00:00Z" }) }));
  await page.route("**/api/v1/auth/step-up", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ method: "password_reauthentication", expires_at: "2026-07-30T10:05:00Z" }) }));
  await page.route("**/api/v1/admin/audit/events?*", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ events: [{ source: "domain", event_id: "evt-redacted", sequence: 1, occurred_at: "2026-07-30T09:00:00Z", action: "identity.user.disabled", object_type: "identity_user", actor_digest: "a".repeat(64), object_digest: "b".repeat(64), metadata_digest: "c".repeat(64), previous_event_hash: "d".repeat(64), event_hash: "e".repeat(64), before_state_hash: null, after_state_hash: null }], pagination: { next_cursor: null }, disclosure: "redacted_no_raw_subject_object_reason_or_metadata", chain_model: "independent_source_chains_no_global_chain" }) }));
  await page.route("**/api/v1/admin/audit/verify", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true, chains: [{ source: "domain", ok: true, checked_events: 1, head_hash: "f".repeat(64), issue_codes: [] }, { source: "ledger_control", ok: true, checked_events: 0, head_hash: "0".repeat(64), issue_codes: [] }], chain_model: "independent_source_chains_no_global_chain" }) }));
  await page.route("**/api/v1/admin/security/overview", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ schema_version: 1, as_of: "2026-07-30T10:00:00Z", tenant_scope_digest: "a".repeat(64), posture: "attention_required", claim_boundary: "operational_snapshot_not_security_assurance", identity: { total_users: 2, active_users: 2, disabled_users: 0, locked_users: 1, active_users_without_roles: 0, roles: 2, permissions: 3, role_permission_bindings: 4 }, sessions: { active_sessions: 2, revoked_sessions: 1, expired_unrevoked_sessions: 0, active_step_up_assertions: 1, active_webauthn_credentials: 1, users_with_active_webauthn: 1 }, integrations: { configured_federation_providers: 0, federation_air_gap_mode: false, linked_federation_providers: 0, active_federation_links: 0, disabled_federation_links: 0, scim_domains: 0, active_scim_users: 0, active_scim_credentials: 0, enabled_service_accounts: 0, active_service_account_credentials: 0, enabled_notification_routes: 0, webauthn_required_for_privileged_actions: false }, policy: { active_scope_grants: 0, pending_emergency_requests: 0, active_emergency_access: 0, overdue_emergency_reviews: 0 }, retention: { evidence_records: 3, evidence_with_retention: 0, evidence_retention_expired: 0, evidence_unverified: 0, evidence_verification_failed: 0 }, audit: { audit_events: 1, chain_verification: "not_evaluated_use_audit_verify_endpoint" }, attention_items: [{ severity: "high", code: "locked_users", count: 1 }], snapshot_digest: "b".repeat(64) }) }));
  await page.route("**/api/v1/admin/identity/users**", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ users: [{ id: "user-a", username: "admin", display_name: "Administrator", disabled: false, lifecycle_version: 1, roles: ["administrator"], active_sessions: 1, created_at: "2026-07-30T09:00:00Z", disabled_at: null, state_digest: "c".repeat(64) }, { id: "user-target", username: "target", display_name: "Target User", disabled: targetDisabled, lifecycle_version: targetLifecycleVersion, roles: targetRoleNames, active_sessions: targetSessionRevoked ? 0 : 1, created_at: "2026-07-30T09:05:00Z", disabled_at: targetDisabled ? "2026-07-30T10:07:00Z" : null, state_digest: (targetDisabled ? "4" : "5").repeat(64) }], pagination: { limit: 100, returned: 2, next_cursor: null } }) }));
  await page.route("**/api/v1/admin/identity/sessions**", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ sessions: [{ id: "session-a", user_id: "user-a", username: "admin", status: "active", lifecycle_version: 1, created_at: "2026-07-30T09:00:00Z", expires_at: "2026-07-30T11:00:00Z", last_used_at: null, revoked_at: null, revocation_reason_code: null, client_ip_recorded: true, user_agent_recorded: true, state_digest: "d".repeat(64) }, { id: "session-target", user_id: "user-target", username: "target", status: targetSessionRevoked ? "revoked" : "active", lifecycle_version: targetSessionRevoked ? 2 : 1, created_at: "2026-07-30T09:05:00Z", expires_at: "2026-07-30T11:05:00Z", last_used_at: null, revoked_at: targetSessionRevoked ? "2026-07-30T10:07:00Z" : null, revocation_reason_code: targetSessionRevoked ? "user_disabled" : null, client_ip_recorded: true, user_agent_recorded: true, state_digest: (targetSessionRevoked ? "6" : "7").repeat(64) }], pagination: { limit: 100, returned: 2, next_cursor: null } }) }));
  await page.route("**/api/v1/admin/identity/users/user-target/status", async (route) => {
    const payload = route.request().postDataJSON() as { disabled: boolean; expected_lifecycle_version: number };
    expect(route.request().headers()["x-reconforge-csrf"]).toBe("csrf-proof");
    expect(payload.expected_lifecycle_version).toBe(targetLifecycleVersion);
    targetDisabled = payload.disabled;
    targetLifecycleVersion += 1;
    if (targetDisabled) targetSessionRevoked = true;
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ user: { id: "user-target", username: "target", display_name: "Target User", disabled: targetDisabled, lifecycle_version: targetLifecycleVersion, roles: targetRoleNames, active_sessions: 0, created_at: "2026-07-30T09:05:00Z", disabled_at: targetDisabled ? "2026-07-30T10:07:00Z" : null, state_digest: (targetDisabled ? "8" : "9").repeat(64) }, transitioned: true, revoked_sessions: targetDisabled ? 1 : 0, audit_event_id: targetDisabled ? "audit-user-disabled" : "audit-user-enabled" }) });
  });
  await page.route("**/api/v1/admin/identity/sessions/session-a/revoke", async (route) => {
    expect(route.request().method()).toBe("POST");
    expect(route.request().headers()["x-reconforge-csrf"]).toBe("csrf-proof");
    expect(route.request().postDataJSON()).toEqual({ expected_lifecycle_version: 1, reason_code: "security_response" });
    sessionRevoked = true;
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ session: { id: "session-a", user_id: "user-a", username: "admin", status: "revoked", lifecycle_version: 2, created_at: "2026-07-30T09:00:00Z", expires_at: "2026-07-30T11:00:00Z", last_used_at: null, revoked_at: "2026-07-30T10:06:00Z", revocation_reason_code: "security_response", client_ip_recorded: true, user_agent_recorded: true, state_digest: "f".repeat(64) }, transitioned: true, revoked_current_session: false, audit_event_id: "audit-session-revoked" }) });
  });
  await page.route("**/api/v1/admin/access/permissions", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify([{ name: "audit.read", description: "Read audit evidence", active_role_count: customRole && (customRole.permissions as string[]).includes("audit.read") ? 1 : 0, state_digest: "a".repeat(64) }, { name: "audit.verify", description: "Verify audit chains", active_role_count: customRole && (customRole.permissions as string[]).includes("audit.verify") ? 1 : 0, state_digest: "b".repeat(64) }, { name: "roles.manage", description: "Manage roles", active_role_count: 1, state_digest: "e".repeat(64) }]) }));
  await page.route("**/api/v1/admin/access/roles**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const administrator = { id: "role-a", name: "administrator", description: "Administrative role", active: true, lifecycle_version: 1, permissions: ["roles.manage"], active_user_count: 1, created_at: "2026-07-30T09:00:00Z", updated_at: "2026-07-30T09:00:00Z", retired_at: null, state_digest: "f".repeat(64) };
    if (request.method() === "GET") { const roles = customRole ? [administrator, customRole] : [administrator]; return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ roles, pagination: { limit: 100, returned: roles.length, next_cursor: null } }) }); }
    expect(request.headers()["x-reconforge-csrf"]).toBe("csrf-proof");
    if (request.method() === "POST" && path.endsWith("/roles")) {
      expect(request.postDataJSON()).toEqual({ name: "reviewer", description: "Controlled reviewer", permissions: ["audit.read"] });
      customRole = { id: "role-reviewer", name: "reviewer", description: "Controlled reviewer", active: true, lifecycle_version: 1, permissions: ["audit.read"], active_user_count: 0, created_at: "2026-07-30T10:10:00Z", updated_at: "2026-07-30T10:10:00Z", retired_at: null, state_digest: "1".repeat(64) };
    } else if (request.method() === "PUT" && path.endsWith("/permissions") && customRole) {
      expect(request.postDataJSON()).toEqual({ expected_lifecycle_version: customRole.lifecycle_version, permissions: ["audit.read", "audit.verify"] });
      customRole = { ...customRole, lifecycle_version: Number(customRole.lifecycle_version) + 1, permissions: ["audit.read", "audit.verify"], updated_at: "2026-07-30T10:11:00Z", state_digest: "2".repeat(64) };
    } else if (request.method() === "PATCH" && customRole) {
      const payload = request.postDataJSON() as { expected_lifecycle_version: number; active: boolean };
      expect(payload.expected_lifecycle_version).toBe(customRole.lifecycle_version);
      customRole = { ...customRole, lifecycle_version: Number(customRole.lifecycle_version) + 1, active: payload.active, active_user_count: 0, retired_at: payload.active ? null : "2026-07-30T10:13:00Z", updated_at: "2026-07-30T10:13:00Z", state_digest: (payload.active ? "4" : "3").repeat(64) };
      if (!payload.active) targetRoleNames = [];
    } else throw new Error(`Unexpected access role request: ${request.method()} ${path}`);
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ role: customRole, transitioned: true, revoked_sessions: 0, audit_event_id: "audit-access-role" }) });
  });
  await page.route("**/api/v1/admin/access/users/user-target/roles", async (route) => {
    expect(route.request().headers()["x-reconforge-csrf"]).toBe("csrf-proof");
    expect(route.request().postDataJSON()).toEqual({ expected_user_lifecycle_version: targetLifecycleVersion, role_ids: ["role-reviewer"] });
    targetLifecycleVersion += 1; targetRoleNames = ["reviewer"];
    if (customRole) customRole = { ...customRole, active_user_count: 1 };
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ user_id: "user-target", username: "target", lifecycle_version: targetLifecycleVersion, role_ids: ["role-reviewer"], role_names: ["reviewer"], transitioned: true, revoked_sessions: 0, audit_event_id: "audit-access-assignment", state_digest: "5".repeat(64) }) });
  });
  await page.route("**/api/v1/admin/security/integrations**", async (route) => {
    const request = route.request(); const item = { kind: "service_account", id: "service-a", status: integrationDisabled ? "disabled" : "active", lifecycle_version: integrationDisabled ? 2 : 1, credential_count: 1, active_credential_count: integrationDisabled ? 0 : 1, created_at: "2026-07-30T09:00:00Z", expires_at: null, last_used_at: null, scope_digest: "1".repeat(64), state_digest: (integrationDisabled ? "4" : "2").repeat(64) };
    if (request.method() === "GET") return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ integrations: [item], pagination: { limit: 100, returned: 1, next_cursor: null } }) });
    expect(request.headers()["x-reconforge-csrf"]).toBe("csrf-proof"); expect(request.postDataJSON()).toEqual({ expected_state_digest: "2".repeat(64), reason_code: "security_response" }); integrationDisabled = true;
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ integration: { ...item, status: "disabled", lifecycle_version: 2, active_credential_count: 0, state_digest: "4".repeat(64) }, transitioned: true, revoked_credentials: 1, audit_event_id: "audit-integration" }) });
  });
  await page.route("**/api/v1/admin/security/retention-policies**", async (route) => {
    const request = route.request(); const path = new URL(request.url()).pathname;
    if (request.method() === "GET") { const policies = retentionPolicy ? [retentionPolicy] : []; return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ policies, pagination: { limit: 100, returned: policies.length, next_cursor: null } }) }); }
    expect(request.headers()["x-reconforge-csrf"]).toBe("csrf-proof");
    if (request.method() === "POST" && path.endsWith("/retention-policies")) { expect(request.postDataJSON()).toEqual({ name: "audit-evidence", description: "Controlled evidence policy", data_classification: "restricted", duration_days: 365 }); retentionPolicy = { id: "policy-a", name: "audit-evidence", description: "Controlled evidence policy", data_classification: "restricted", duration_days: 365, active: true, lifecycle_version: 1, created_at: "2026-07-30T10:20:00Z", updated_at: "2026-07-30T10:20:00Z", retired_at: null, state_digest: "3".repeat(64) }; }
    else if (request.method() === "PATCH" && retentionPolicy) { const payload = request.postDataJSON() as { expected_lifecycle_version: number; active?: boolean; duration_days?: number }; expect(payload.expected_lifecycle_version).toBe(retentionPolicy.lifecycle_version); retentionPolicy = { ...retentionPolicy, lifecycle_version: Number(retentionPolicy.lifecycle_version) + 1, ...(payload.active === undefined ? {} : { active: payload.active, retired_at: payload.active ? null : "2026-07-30T10:22:00Z" }), ...(payload.duration_days === undefined ? {} : { duration_days: payload.duration_days }), state_digest: "5".repeat(64) }; }
    else if (request.method() === "POST" && path.includes("/evidence/") && retentionPolicy) { expect(request.postDataJSON()).toEqual({ expected_retention_version: evidenceRetentionVersion, reason_code: "policy_application" }); evidenceRetentionVersion += 1; return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ evidence_id: "evidence-a", policy_id: "policy-a", policy_lifecycle_version: retentionPolicy.lifecycle_version, retention_version: evidenceRetentionVersion, previous_retention_until: null, policy_retention_until: "2027-07-30T10:20:00Z", effective_retention_until: "2027-07-30T10:20:00Z", retention_extended: true, transitioned: true, audit_event_id: "audit-retention", state_digest: "6".repeat(64) }) }); }
    else throw new Error(`Unexpected retention request: ${request.method()} ${path}`);
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ policy: retentionPolicy, transitioned: true, audit_event_id: "audit-policy" }) });
  });
  await page.goto("/admin-audit");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Redacted audit administration");
  await page.getByLabel("Tenant ID").fill("tenant-a");
  await page.getByLabel("Username").fill("admin");
  await page.getByLabel("Password", { exact: true }).fill("Synthetic-password-123");
  await page.getByRole("button", { name: "Sign in to administration" }).click();
  await expect(page.getByRole("heading", { level: 2, name: "Confirm privileged access" })).toBeVisible();
  await page.getByLabel("Password", { exact: true }).fill("Synthetic-password-123");
  await page.getByRole("button", { name: "Confirm and continue" }).click();
  await expect(page.getByText("evt-redacted", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { level: 2, name: "Security control snapshot" })).toBeVisible();
  await expect(page.getByText("Count-based attention requires review")).toBeVisible();
  await expect(page.getByText("locked_users", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { level: 2, name: "Identity and session snapshot" })).toBeVisible();
  await expect(page.getByText("Authorized users", { exact: true })).toBeVisible();
  await expect(page.getByLabel("Identity and session snapshot").getByText("administrator", { exact: true })).toBeVisible();
  await expect(page.getByLabel("Identity and session snapshot").getByText("Current operator", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Disable user" }).click();
  await expect(page.getByRole("button", { name: "Disable selected user" })).toBeDisabled();
  await page.getByLabel("Type DISABLE to confirm").fill("DISABLE");
  await page.getByRole("button", { name: "Disable selected user" }).click();
  await expect(page.getByText("The user was disabled and audit evidence was recorded.")).toBeVisible();
  await expect(page.getByText("Sessions revoked: 1")).toBeVisible();
  await page.getByRole("button", { name: "Enable user" }).click();
  await page.getByLabel("Type ENABLE to confirm").fill("ENABLE");
  await page.getByRole("button", { name: "Enable selected user" }).click();
  await expect(page.getByText("The user was enabled and audit evidence was recorded.")).toBeVisible();
  await expect(page.getByRole("table", { name: "Authorized users" }).getByRole("row", { name: /target/ })).toContainText("0");
  await page.getByRole("button", { name: "Revoke session" }).click();
  await expect(page.getByRole("heading", { level: 3, name: "Revoke authorized session" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Revoke selected session" })).toBeDisabled();
  await page.getByLabel("Type REVOKE to confirm").fill("REVOKE");
  await page.getByRole("button", { name: "Revoke selected session" }).click();
  await expect(page.getByText("The session was revoked and audit evidence was recorded.")).toBeVisible();
  expect(sessionRevoked).toBe(true);
  await expect(page.getByRole("heading", { level: 2, name: "Access-policy snapshot" })).toBeVisible();
  await expect(page.getByText("Authorized roles", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Create role" }).click();
  await page.getByLabel("Role name").fill("reviewer");
  await page.getByLabel("Description", { exact: true }).fill("Controlled reviewer");
  await page.getByRole("checkbox", { name: /audit\.read/ }).check();
  await page.getByPlaceholder("CREATE").fill("CREATE");
  await page.getByRole("button", { name: "Apply governed change" }).click();
  await expect(page.getByText("The role was created and audit evidence was recorded.")).toBeVisible();
  const rolesTable = page.getByRole("table", { name: "Authorized roles" });
  const reviewerRole = rolesTable.getByRole("row", { name: /reviewer/ });
  await reviewerRole.getByRole("button", { name: "Edit permissions" }).click();
  await page.getByRole("checkbox", { name: /audit\.verify/ }).check();
  await page.getByPlaceholder("APPLY").fill("APPLY");
  await page.getByRole("button", { name: "Apply governed change" }).click();
  await expect(reviewerRole).toContainText("audit.verify");
  const assignmentsTable = page.getByRole("table", { name: "User role assignments" });
  const targetAssignment = assignmentsTable.getByRole("row", { name: /target/ });
  await targetAssignment.getByRole("button", { name: "Manage roles" }).click();
  await page.getByRole("checkbox", { name: /reviewer/ }).check();
  await page.getByPlaceholder("ASSIGN").fill("ASSIGN");
  await page.getByRole("button", { name: "Apply governed change" }).click();
  await expect(targetAssignment).toContainText("reviewer");
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
  await expect(page.getByRole("heading", { level: 2, name: "Integration and retention snapshot" })).toBeVisible();
  await expect(page.getByText("Authorized integrations", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Disable", exact: true }).click();
  await page.getByPlaceholder("DISABLE").fill("DISABLE");
  await page.getByRole("button", { name: "Apply governed change" }).click();
  await expect(page.getByText("The integration and its active credentials were disabled; audit evidence was recorded.")).toBeVisible();
  await page.getByRole("button", { name: "Create retention policy" }).click();
  await page.getByLabel("Policy name").fill("audit-evidence"); await page.getByLabel("Description", { exact: true }).fill("Controlled evidence policy"); await page.getByLabel("Classification").selectOption("restricted");
  await page.getByPlaceholder("CREATE").fill("CREATE"); await page.getByRole("button", { name: "Apply governed change" }).click();
  const policyRow = page.getByRole("table", { name: "Retention policies" }).getByRole("row", { name: /audit-evidence/ }); await expect(policyRow).toBeVisible();
  await policyRow.getByRole("button", { name: "Apply to evidence" }).click(); await page.getByLabel(/Evidence identifier/).fill("evidence-a"); await page.getByPlaceholder("APPLY").fill("APPLY"); await page.getByRole("button", { name: "Apply governed change" }).click();
  await expect(page.getByText("Evidence retention was extended and the governed assignment was recorded.")).toBeVisible();
  await policyRow.getByRole("button", { name: "Retire" }).click(); await page.getByPlaceholder("RETIRE").fill("RETIRE"); await page.getByRole("button", { name: "Apply governed change" }).click(); await expect(policyRow).toContainText("Retired");
  await policyRow.getByRole("button", { name: "Reactivate" }).click(); await page.getByPlaceholder("REACTIVATE").fill("REACTIVATE"); await page.getByRole("button", { name: "Apply governed change" }).click(); await expect(policyRow).toContainText("Active");
  const text = await page.locator("main").innerText();
  expect(text).not.toContain("actor_label");
  expect(text).not.toContain("Synthetic-password-123");
  expect(text).not.toContain("client_ip");
  expect(text).not.toContain("secret_reference");
  expect(text).not.toContain("audit-session-revoked");
  expect(text).not.toContain("audit-user-disabled");
  expect(text).not.toContain("audit-user-enabled");
  expect(text).not.toContain("audit-access-role");
  expect(text).not.toContain("audit-access-assignment");
  expect(text).not.toContain("evidence-a");
  const englishAccessibility = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
  expect(englishAccessibility.violations.flatMap((violation) => violation.nodes.map((node) => `${violation.id}: ${node.target.join(" ")}`))).toEqual([]);
  await page.getByTestId("locale-toggle").click();
  await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("إدارة سجل التدقيق");
  const arabicAccessibility = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
  expect(arabicAccessibility.violations.flatMap((violation) => violation.nodes.map((node) => `${violation.id}: ${node.target.join(" ")}`))).toEqual([]);
});
