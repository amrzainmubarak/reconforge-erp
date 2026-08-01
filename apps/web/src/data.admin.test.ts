import { AdminApiError, applyAdminRetentionPolicy, beginBrowserAdminSession, createAdminAccessRole, createAdminRetentionPolicy, disableAdminIntegration, loadAdminAccessPermissions, loadAdminAccessRoles, loadAdminAuditPage, loadAdminIdentitySessions, loadAdminIdentityUsers, loadAdminIntegrations, loadAdminRetentionPolicies, loadAdminSecurityCenter, replaceAdminAccessRolePermissions, replaceAdminUserRoles, revokeAdminIdentitySession, setAdminAccessRoleActive, setAdminIdentityUserDisabled, stepUpBrowserAdminSession, updateAdminRetentionPolicy, verifyAdminAudit } from "./data";

function reply(status: number, body: unknown): Response { return { ok: status >= 200 && status < 300, status, json: async () => body } as Response; }

const session = { tenantId: "tenant-a", csrfToken: "csrf-proof", expiresAt: "2026-07-30T10:00:00Z" };
const event = { source: "domain", event_id: "evt-1", sequence: 1, occurred_at: "2026-07-30T09:00:00Z", action: "identity.user.disabled", object_type: "identity_user", actor_digest: "a".repeat(64), object_digest: "b".repeat(64), metadata_digest: "c".repeat(64), previous_event_hash: "d".repeat(64), event_hash: "e".repeat(64), before_state_hash: null, after_state_hash: null };

test("browser administration login carries tenant but never exposes a bearer token", async () => {
  const fetcher = vi.fn(async () => reply(200, { csrf_token: "csrf-proof", expires_at: "2026-07-30T10:00:00Z" }));
  await expect(beginBrowserAdminSession({ tenantId: "tenant-a", username: "admin", password: "Secret-123", fetcher })).resolves.toEqual(session);
  expect(fetcher).toHaveBeenCalledWith("/api/v1/auth/browser/login", expect.objectContaining({ credentials: "same-origin", cache: "no-store", headers: expect.objectContaining({ "X-ReconForge-Tenant": "tenant-a" }) }));
  expect(JSON.stringify(fetcher.mock.calls)).not.toContain("access_token");
});

test("step-up sends the memory-only CSRF proof and audit reads remain no-store", async () => {
  const stepCalls: RequestInit[] = []; const pageCalls: RequestInit[] = [];
  const stepUp = ((_url: string | URL | Request, init?: RequestInit) => { stepCalls.push(init ?? {}); return Promise.resolve(reply(200, { method: "password_reauthentication", expires_at: "2026-07-30T10:05:00Z" })); }) as typeof fetch;
  const page = ((_url: string | URL | Request, init?: RequestInit) => { pageCalls.push(init ?? {}); return Promise.resolve(reply(200, { events: [event], pagination: { next_cursor: "opaque-next" }, disclosure: "redacted_no_raw_subject_object_reason_or_metadata", chain_model: "independent_source_chains_no_global_chain" })); }) as typeof fetch;
  const verification = (async () => reply(200, { ok: true, chains: [{ source: "domain", ok: true, checked_events: 1, head_hash: "f".repeat(64), issue_codes: [] }, { source: "ledger_control", ok: true, checked_events: 0, head_hash: "0".repeat(64), issue_codes: [] }], chain_model: "independent_source_chains_no_global_chain" })) as typeof fetch;
  await expect(stepUpBrowserAdminSession(session, "Secret-123", stepUp)).resolves.toBe("2026-07-30T10:05:00Z");
  await expect(loadAdminAuditPage(session, undefined, page)).resolves.toMatchObject({ events: [event], nextCursor: "opaque-next" });
  await expect(verifyAdminAudit(session, verification)).resolves.toHaveLength(2);
  expect(stepCalls[0]?.headers).toMatchObject({ "X-ReconForge-CSRF": "csrf-proof" });
  expect(pageCalls[0]).toMatchObject({ cache: "no-store", credentials: "same-origin" });
  expect(pageCalls[0]?.headers).not.toMatchObject({ "X-ReconForge-CSRF": expect.anything() });
});

test.each([[401, "auth_required"], [403, "step_up_required"]])("admin APIs preserve safe %s errors", async (status, code) => {
  await expect(loadAdminAuditPage(session, undefined, async () => reply(Number(status), { error: { code } }))).rejects.toEqual(expect.objectContaining({ name: "Error", status: Number(status), code } satisfies Partial<AdminApiError>));
});

test("rejects expanded audit fields rather than rendering a wider disclosure", async () => {
  await expect(loadAdminAuditPage(session, undefined, async () => reply(200, { events: [{ ...event, actor_label: "not allowed" }], pagination: { next_cursor: null } }))).rejects.toThrow("audit_contract_invalid");
});

test("security center accepts only the declared count-only snapshot", async () => {
  const snapshot = { schema_version: 1, as_of: "2026-07-30T10:00:00Z", tenant_scope_digest: "a".repeat(64), posture: "attention_required", claim_boundary: "operational_snapshot_not_security_assurance", identity: { total_users: 2, active_users: 2, disabled_users: 0, locked_users: 1, active_users_without_roles: 0, roles: 2, permissions: 3, role_permission_bindings: 4 }, sessions: { active_sessions: 2, revoked_sessions: 1, expired_unrevoked_sessions: 0, active_step_up_assertions: 1, active_webauthn_credentials: 1, users_with_active_webauthn: 1 }, integrations: { configured_federation_providers: 0, federation_air_gap_mode: false, linked_federation_providers: 0, active_federation_links: 0, disabled_federation_links: 0, scim_domains: 0, active_scim_users: 0, active_scim_credentials: 0, enabled_service_accounts: 0, active_service_account_credentials: 0, enabled_notification_routes: 0, webauthn_required_for_privileged_actions: false }, policy: { active_scope_grants: 0, pending_emergency_requests: 0, active_emergency_access: 0, overdue_emergency_reviews: 0 }, retention: { evidence_records: 0, evidence_with_retention: 0, evidence_retention_expired: 0, evidence_unverified: 0, evidence_verification_failed: 0 }, audit: { audit_events: 1, chain_verification: "not_evaluated_use_audit_verify_endpoint" }, attention_items: [{ severity: "high", code: "locked_users", count: 1 }], snapshot_digest: "b".repeat(64) };
  await expect(loadAdminSecurityCenter(session, async () => reply(200, snapshot))).resolves.toMatchObject({ posture: "attention_required", attention: [{ code: "locked_users", count: 1 }] });
  await expect(loadAdminSecurityCenter(session, async () => reply(200, { ...snapshot, identity: { ...snapshot.identity, email: "not-allowed" } }))).rejects.toThrow("security_center_contract_invalid");
  await expect(loadAdminSecurityCenter(session, async () => reply(200, { ...snapshot, hidden_operator_note: "not-allowed" }))).rejects.toThrow("security_center_contract_invalid");
  await expect(loadAdminSecurityCenter(session, async () => reply(200, { ...snapshot, attention_items: [{ ...snapshot.attention_items[0], actor_id: "not-allowed" }] }))).rejects.toThrow("security_center_contract_invalid");
});

test("identity pages reject credentials and personal-network disclosure", async () => {
  const user = { id: "user-a", username: "admin", display_name: "Administrator", disabled: false, lifecycle_version: 1, roles: ["role-a"], active_sessions: 1, created_at: "2026-07-30T10:00:00Z", disabled_at: null, state_digest: "a".repeat(64) };
  const identitySession = { id: "session-a", user_id: "user-a", username: "admin", status: "active", lifecycle_version: 1, created_at: "2026-07-30T10:00:00Z", expires_at: "2026-07-30T11:00:00Z", last_used_at: null, revoked_at: null, revocation_reason_code: null, client_ip_recorded: true, user_agent_recorded: true, state_digest: "b".repeat(64) };
  await expect(loadAdminIdentityUsers(session, async () => reply(200, { users: [user], pagination: { limit: 100, returned: 1, next_cursor: null } }))).resolves.toMatchObject([{ username: "admin", displayName: "Administrator" }]);
  await expect(loadAdminIdentitySessions(session, async () => reply(200, { sessions: [identitySession], pagination: { limit: 100, returned: 1, next_cursor: null } }))).resolves.toMatchObject([{ username: "admin", clientIpRecorded: true }]);
  await expect(loadAdminIdentityUsers(session, async () => reply(200, { users: [{ ...user, email: "not-allowed" }], pagination: { limit: 100, returned: 1, next_cursor: null } }))).rejects.toThrow("identity_users_contract_invalid");
  await expect(loadAdminIdentitySessions(session, async () => reply(200, { sessions: [{ ...identitySession, client_ip: "not-allowed" }], pagination: { limit: 100, returned: 1, next_cursor: null } }))).rejects.toThrow("identity_sessions_contract_invalid");
});

test("session revocation sends CSRF, version, and reason and accepts only its closed response", async () => {
  const identitySession = { id: "session-a", user_id: "user-a", username: "admin", status: "active", lifecycle_version: 1, created_at: "2026-07-30T10:00:00Z", expires_at: "2026-07-30T11:00:00Z", last_used_at: null, revoked_at: null, revocation_reason_code: null, client_ip_recorded: true, user_agent_recorded: true, state_digest: "b".repeat(64) };
  const calls: Array<{ url: string | URL | Request; init?: RequestInit }> = [];
  const fetcher = ((url: string | URL | Request, init?: RequestInit) => {
    calls.push({ url, init });
    return Promise.resolve(reply(200, {
      session: { ...identitySession, status: "revoked", lifecycle_version: 2, revoked_at: "2026-07-30T10:10:00Z", revocation_reason_code: "security_response" },
      transitioned: true,
      revoked_current_session: false,
      audit_event_id: "audit-2",
    }));
  }) as typeof fetch;
  await expect(revokeAdminIdentitySession(session, { id: "session-a", lifecycleVersion: 1 }, "security_response", fetcher)).resolves.toMatchObject({ transitioned: true, revokedCurrentSession: false, session: { status: "revoked", lifecycleVersion: 2 } });
  expect(calls).toHaveLength(1);
  expect(String(calls[0]?.url)).toBe("/api/v1/admin/identity/sessions/session-a/revoke");
  expect(calls[0]?.init).toMatchObject({ method: "POST", credentials: "same-origin", cache: "no-store", headers: expect.objectContaining({ "X-ReconForge-Tenant": "tenant-a", "X-ReconForge-CSRF": "csrf-proof", "Content-Type": "application/json" }) });
  expect(calls[0]?.init?.body).toBe(JSON.stringify({ expected_lifecycle_version: 1, reason_code: "security_response" }));
  await expect(revokeAdminIdentitySession(session, { id: "session-a", lifecycleVersion: 1 }, "security_response", async () => reply(200, {
    session: { ...identitySession, status: "revoked", lifecycle_version: 2, revoked_at: "2026-07-30T10:10:00Z", revocation_reason_code: "security_response", client_ip: "not-allowed" },
    transitioned: true,
    revoked_current_session: false,
    audit_event_id: "audit-2",
  }))).rejects.toThrow("identity_session_revocation_contract_invalid");
  await expect(revokeAdminIdentitySession(session, { id: "session-a", lifecycleVersion: 1 }, "security_response", async () => reply(409, { error: { code: "identity_lifecycle_version_conflict" } }))).rejects.toEqual(expect.objectContaining({ code: "identity_lifecycle_version_conflict", status: 409 }));
});

test("user status mutation sends CSRF and lifecycle version and rejects expanded disclosure", async () => {
  const user = { id: "user-target", username: "target", display_name: "Target User", disabled: true, lifecycle_version: 2, roles: ["observer"], active_sessions: 0, created_at: "2026-07-30T10:00:00Z", disabled_at: "2026-07-30T10:10:00Z", state_digest: "a".repeat(64) };
  const calls: Array<{ url: string | URL | Request; init?: RequestInit }> = [];
  const fetcher = ((url: string | URL | Request, init?: RequestInit) => {
    calls.push({ url, init });
    return Promise.resolve(reply(200, { user, transitioned: true, revoked_sessions: 2, audit_event_id: "audit-user-disabled" }));
  }) as typeof fetch;
  await expect(setAdminIdentityUserDisabled(session, { id: "user-target", lifecycleVersion: 1 }, true, fetcher)).resolves.toMatchObject({ user: { username: "target", disabled: true, lifecycleVersion: 2 }, transitioned: true, revokedSessions: 2 });
  expect(String(calls[0]?.url)).toBe("/api/v1/admin/identity/users/user-target/status");
  expect(calls[0]?.init).toMatchObject({ method: "POST", credentials: "same-origin", cache: "no-store", headers: expect.objectContaining({ "X-ReconForge-Tenant": "tenant-a", "X-ReconForge-CSRF": "csrf-proof", "Content-Type": "application/json" }) });
  expect(calls[0]?.init?.body).toBe(JSON.stringify({ disabled: true, expected_lifecycle_version: 1 }));
  await expect(setAdminIdentityUserDisabled(session, { id: "user-target", lifecycleVersion: 1 }, true, async () => reply(200, { user: { ...user, email: "not-allowed" }, transitioned: true, revoked_sessions: 2, audit_event_id: "audit-user-disabled" }))).rejects.toThrow("identity_user_status_contract_invalid");
  await expect(setAdminIdentityUserDisabled(session, { id: "user-target", lifecycleVersion: 1 }, true, async () => reply(409, { error: { code: "identity_last_administrator_forbidden" } }))).rejects.toEqual(expect.objectContaining({ code: "identity_last_administrator_forbidden", status: 409 }));
});

test("access pages reject expanded policy disclosure", async () => {
  const permission = { name: "roles.manage", description: "Manage roles", active_role_count: 1, state_digest: "a".repeat(64) };
  const role = { id: "role-a", name: "Administrator", description: "Administrative role", active: true, lifecycle_version: 1, permissions: ["roles.manage"], active_user_count: 1, created_at: "2026-07-30T10:00:00Z", updated_at: "2026-07-30T10:00:00Z", retired_at: null, state_digest: "b".repeat(64) };
  await expect(loadAdminAccessPermissions(session, async () => reply(200, [permission]))).resolves.toMatchObject([{ name: "roles.manage" }]);
  await expect(loadAdminAccessRoles(session, async () => reply(200, { roles: [role], pagination: { limit: 100, returned: 1, next_cursor: null } }))).resolves.toMatchObject([{ name: "Administrator" }]);
  await expect(loadAdminAccessPermissions(session, async () => reply(200, [{ ...permission, secret: "not-allowed" }]))).rejects.toThrow("access_permissions_contract_invalid");
  await expect(loadAdminAccessRoles(session, async () => reply(200, { roles: [{ ...role, user_email: "not-allowed" }], pagination: { limit: 100, returned: 1, next_cursor: null } }))).rejects.toThrow("access_roles_contract_invalid");
});

test("access mutations preserve exact payloads and reject response expansion", async () => {
  const role = { id: "role-reviewer", name: "reviewer", description: "Reviewer", active: true, lifecycle_version: 2, permissions: ["audit.read"], active_user_count: 1, created_at: "2026-07-30T10:00:00Z", updated_at: "2026-07-30T10:10:00Z", retired_at: null, state_digest: "b".repeat(64) };
  const calls: Array<{ url: string | URL | Request; init?: RequestInit }> = [];
  const roleFetcher = ((url: string | URL | Request, init?: RequestInit) => { calls.push({ url, init }); return Promise.resolve(reply(200, { role, transitioned: true, revoked_sessions: 1, audit_event_id: "audit-role" })); }) as typeof fetch;
  await expect(createAdminAccessRole(session, { name: "reviewer", description: "Reviewer", permissions: ["audit.read"] }, roleFetcher)).resolves.toMatchObject({ role: { name: "reviewer" }, transitioned: true });
  await expect(setAdminAccessRoleActive(session, { id: "role-reviewer", lifecycleVersion: 1 }, false, roleFetcher)).resolves.toMatchObject({ revokedSessions: 1 });
  await expect(replaceAdminAccessRolePermissions(session, { id: "role-reviewer", lifecycleVersion: 1 }, ["audit.read"], roleFetcher)).resolves.toMatchObject({ role: { permissions: ["audit.read"] } });
  expect(calls.map((call) => [String(call.url), call.init?.method, call.init?.body])).toEqual([
    ["/api/v1/admin/access/roles", "POST", JSON.stringify({ name: "reviewer", description: "Reviewer", permissions: ["audit.read"] })],
    ["/api/v1/admin/access/roles/role-reviewer", "PATCH", JSON.stringify({ expected_lifecycle_version: 1, active: false })],
    ["/api/v1/admin/access/roles/role-reviewer/permissions", "PUT", JSON.stringify({ expected_lifecycle_version: 1, permissions: ["audit.read"] })],
  ]);
  expect(calls.every((call) => (call.init?.headers as Record<string, string>)["X-ReconForge-CSRF"] === "csrf-proof")).toBe(true);
  const assignment = { user_id: "user-target", username: "target", lifecycle_version: 2, role_ids: ["role-reviewer"], role_names: ["reviewer"], transitioned: true, revoked_sessions: 1, audit_event_id: "audit-assignment", state_digest: "c".repeat(64) };
  const assignmentCalls: RequestInit[] = [];
  await expect(replaceAdminUserRoles(session, { id: "user-target", lifecycleVersion: 1 }, ["role-reviewer"], ((_url, init) => { assignmentCalls.push(init ?? {}); return Promise.resolve(reply(200, assignment)); }) as typeof fetch)).resolves.toMatchObject({ username: "target", roleNames: ["reviewer"], revokedSessions: 1 });
  expect(assignmentCalls[0]?.body).toBe(JSON.stringify({ expected_user_lifecycle_version: 1, role_ids: ["role-reviewer"] }));
  await expect(createAdminAccessRole(session, { name: "reviewer", description: "Reviewer", permissions: [] }, async () => reply(200, { role: { ...role, secret: "not-allowed" }, transitioned: true, revoked_sessions: 0, audit_event_id: "audit-role" }))).rejects.toThrow("access_role_change_contract_invalid");
  await expect(replaceAdminUserRoles(session, { id: "user-target", lifecycleVersion: 1 }, [], async () => reply(200, { ...assignment, email: "not-allowed" }))).rejects.toThrow("access_user_roles_contract_invalid");
});

test("integration and retention pages reject secret and evidence disclosure", async () => {
  const integration = { kind: "service_account", id: "service-a", status: "active", lifecycle_version: 1, credential_count: 1, active_credential_count: 1, created_at: "2026-07-30T10:00:00Z", expires_at: null, last_used_at: null, scope_digest: "a".repeat(64), state_digest: "b".repeat(64) };
  const policy = { id: "policy-a", name: "retention-1", description: "Retention", data_classification: "confidential", duration_days: 365, active: true, lifecycle_version: 1, created_at: "2026-07-30T10:00:00Z", updated_at: "2026-07-30T10:00:00Z", retired_at: null, state_digest: "c".repeat(64) };
  await expect(loadAdminIntegrations(session, async () => reply(200, { integrations: [integration], pagination: { limit: 100, returned: 1, next_cursor: null } }))).resolves.toMatchObject([{ kind: "service_account" }]);
  await expect(loadAdminRetentionPolicies(session, async () => reply(200, { policies: [policy], pagination: { limit: 100, returned: 1, next_cursor: null } }))).resolves.toMatchObject([{ name: "retention-1" }]);
  await expect(loadAdminIntegrations(session, async () => reply(200, { integrations: [{ ...integration, secret_reference: "not-allowed" }], pagination: { limit: 100, returned: 1, next_cursor: null } }))).rejects.toThrow("integrations_contract_invalid");
  await expect(loadAdminRetentionPolicies(session, async () => reply(200, { policies: [{ ...policy, evidence_id: "not-allowed" }], pagination: { limit: 100, returned: 1, next_cursor: null } }))).rejects.toThrow("retention_policies_contract_invalid");
});

test("governance mutations send CSRF and concurrency proofs through closed contracts", async () => {
  const integrationApi = { kind: "service_account", id: "service/a", status: "disabled", lifecycle_version: 2, credential_count: 1, active_credential_count: 0, created_at: "2026-07-30T10:00:00Z", expires_at: null, last_used_at: null, scope_digest: "a".repeat(64), state_digest: "b".repeat(64) };
  const integration = { kind: "service_account" as const, id: "service/a", status: "active" as const, lifecycleVersion: 1, credentialCount: 1, activeCredentialCount: 1, createdAt: integrationApi.created_at, expiresAt: null, lastUsedAt: null, scopeDigest: "a".repeat(64), stateDigest: "c".repeat(64) };
  const policyApi = { id: "policy/a", name: "audit", description: "Evidence", data_classification: "restricted", duration_days: 365, active: true, lifecycle_version: 2, created_at: "2026-07-30T10:00:00Z", updated_at: "2026-07-30T10:10:00Z", retired_at: null, state_digest: "d".repeat(64) };
  const policy = { id: "policy/a", name: "audit", description: "Evidence", dataClassification: "restricted" as const, durationDays: 365, active: true, lifecycleVersion: 1, createdAt: policyApi.created_at, updatedAt: policyApi.created_at, retiredAt: null, stateDigest: "e".repeat(64) };
  const calls: Array<{ url: string; init?: RequestInit }> = [];
  const responses = [
    { integration: integrationApi, transitioned: true, revoked_credentials: 1, audit_event_id: "audit-disable" },
    { policy: policyApi, transitioned: true, audit_event_id: "audit-create" },
    { policy: policyApi, transitioned: true, audit_event_id: "audit-update" },
    { evidence_id: "evidence/a", policy_id: "policy/a", policy_lifecycle_version: 2, retention_version: 2, previous_retention_until: null, policy_retention_until: "2027-07-30T10:00:00Z", effective_retention_until: "2027-07-30T10:00:00Z", retention_extended: true, transitioned: true, audit_event_id: "audit-apply", state_digest: "f".repeat(64) },
  ];
  const fetcher = ((url: string | URL | Request, init?: RequestInit) => { calls.push({ url: String(url), init }); return Promise.resolve(reply(200, responses.shift())); }) as typeof fetch;
  await disableAdminIntegration(session, integration, "security_response", fetcher);
  await createAdminRetentionPolicy(session, { name: "audit", description: "Evidence", dataClassification: "restricted", durationDays: 365 }, fetcher);
  await updateAdminRetentionPolicy(session, policy, { durationDays: 730 }, fetcher);
  await applyAdminRetentionPolicy(session, policy, "evidence/a", 1, fetcher);
  expect(calls.map((call) => [call.url, call.init?.method, call.init?.body])).toEqual([
    ["/api/v1/admin/security/integrations/service_account/service%2Fa/disable", "POST", JSON.stringify({ expected_state_digest: integration.stateDigest, reason_code: "security_response" })],
    ["/api/v1/admin/security/retention-policies", "POST", JSON.stringify({ name: "audit", description: "Evidence", data_classification: "restricted", duration_days: 365 })],
    ["/api/v1/admin/security/retention-policies/policy%2Fa", "PATCH", JSON.stringify({ expected_lifecycle_version: 1, reason_code: "policy_change", duration_days: 730 })],
    ["/api/v1/admin/security/retention-policies/policy%2Fa/evidence/evidence%2Fa", "POST", JSON.stringify({ expected_retention_version: 1, reason_code: "policy_application" })],
  ]);
  expect(calls.every((call) => (call.init?.headers as Record<string, string>)["X-ReconForge-CSRF"] === "csrf-proof")).toBe(true);
  await expect(disableAdminIntegration(session, integration, "security_response", async () => reply(200, { integration: { ...integrationApi, destination: "not-allowed" }, transitioned: true, revoked_credentials: 1, audit_event_id: "audit" }))).rejects.toThrow("integration_disable_contract_invalid");
  await expect(applyAdminRetentionPolicy(session, policy, "evidence/a", 1, async () => reply(200, { ...responses[3], raw_evidence: "not-allowed" }))).rejects.toThrow("evidence_retention_contract_invalid");
});
