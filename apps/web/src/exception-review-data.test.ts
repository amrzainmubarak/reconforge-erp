import { afterEach, expect, test, vi } from "vitest";

import {
  assignExceptionReview,
  loadExceptionReviewDetail,
  loadExceptionReviewIdentity,
  loadExceptionReviewList,
  parseExceptionReviewListPage,
  transitionExceptionReview,
} from "./exception-review-data";

const session = { tenantId: "tenant-a", csrfToken: "csrf-proof", expiresAt: "2029-01-01T00:00:00Z" };
const identity = {
  id: "reviewer-1",
  username: "reviewer",
  permissions: ["exceptions.read", "exceptions.manage"],
  principal_type: "user",
  authorized_scopes: { workspaces: ["workspace-a"], organizations: [], legal_entities: [] },
};
const record = {
  id: "EXC-001",
  workspace_id: "workspace-a",
  organization_id: "org-a",
  legal_entity_id: "entity-a",
  source_type: "control_run",
  source_id: "RUN-001",
  period_name: "2026-10",
  entity_code: "ENTITY-A",
  account_code: "1100",
  control_code: "MATCH-DIFF",
  risk_rating: "high",
  owner: "reviewer-1",
  status: "In Review",
  escalation_level: "standard",
  sla_target_date: "2026-10-31",
  description: "Amount variance needs a retained decision.",
  created_at: "2026-10-03T10:00:00Z",
  updated_at: "2026-10-03T11:00:00Z",
  row_version: 2,
};
const history = {
  id: "EXH-001",
  exception_id: "EXC-001",
  action: "exception_review_assigned",
  from_status: "Open",
  to_status: "In Review",
  from_owner: "",
  to_owner: "reviewer-1",
  actor_label: "manager",
  actor_id: "manager-1",
  reason: "",
  occurred_at: "2026-10-03T11:00:00Z",
  audit_event_id: "AUD-001",
  outbox_event_id: "OUT-001",
};
const detail = { ...record, history: [history], history_page: { limit: 25, has_more: false, next_cursor: null } };
const response = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json" } });

afterEach(() => vi.unstubAllGlobals());

test("server exception review adapter reads only the authenticated tenant and selected workspace", async () => {
  const fetcher = vi.fn(async (path: RequestInfo | URL, _options?: RequestInit) => {
    const url = String(path);
    if (url.endsWith("/auth/me")) return response(identity);
    if (url.includes("/EXC-001?")) return response({ exception: detail });
    return response({ exceptions: [record], pagination: { limit: 25, returned: 1, has_more: false, next_cursor: null } });
  });
  vi.stubGlobal("fetch", fetcher);

  await expect(loadExceptionReviewIdentity(session)).resolves.toMatchObject({ id: "reviewer-1", workspaces: ["workspace-a"] });
  await expect(loadExceptionReviewList(session, "workspace-a", { risk: "high", status: "In Review" })).resolves.toMatchObject({ exceptions: [record] });
  await expect(loadExceptionReviewDetail(session, "workspace-a", "EXC-001")).resolves.toMatchObject({ id: "EXC-001", history: [history] });

  const listOptions = fetcher.mock.calls[1][1] as RequestInit;
  const listHeaders = new Headers(listOptions.headers);
  expect(String(fetcher.mock.calls[1][0])).toContain("limit=25&risk=high&status=In+Review");
  expect(listOptions).toMatchObject({ method: "GET", credentials: "same-origin", cache: "no-store" });
  expect(listHeaders.get("X-ReconForge-Tenant")).toBe("tenant-a");
  expect(listHeaders.get("X-ReconForge-Workspace")).toBe("workspace-a");
  expect(listHeaders.get("X-ReconForge-CSRF")).toBeNull();
});

test("assignment and transition send one version-bound CSRF-protected request", async () => {
  const assigned = { ...detail, owner: "reviewer-2", row_version: 3, history: [{ ...history, id: "EXH-002", to_owner: "reviewer-2" }] };
  const transitioned = { ...assigned, status: "Resolved", row_version: 4, history: [{ ...history, id: "EXH-003", action: "exception_review_transition", from_status: "In Review", to_status: "Resolved", to_owner: "reviewer-2", reason: "Source corrected." }] };
  const fetcher = vi.fn(async (path: RequestInfo | URL, _options?: RequestInit) => String(path).endsWith("/assign") ? response({ exception: assigned }) : response({ exception: transitioned }));
  vi.stubGlobal("fetch", fetcher);

  await expect(assignExceptionReview(session, "workspace-a", "EXC-001", "reviewer-2", 2)).resolves.toMatchObject({ owner: "reviewer-2", row_version: 3 });
  await expect(transitionExceptionReview(session, "workspace-a", "EXC-001", "Resolved", 3, "Source corrected.")).resolves.toMatchObject({ status: "Resolved", row_version: 4 });

  const assignment = fetcher.mock.calls[0][1] as RequestInit;
  const transition = fetcher.mock.calls[1][1] as RequestInit;
  expect(assignment).toMatchObject({ method: "POST", credentials: "same-origin", cache: "no-store", body: JSON.stringify({ owner: "reviewer-2", expected_version: 2 }) });
  expect(transition).toMatchObject({ method: "POST", credentials: "same-origin", cache: "no-store", body: JSON.stringify({ status: "Resolved", expected_version: 3, reason: "Source corrected." }) });
  for (const options of [assignment, transition]) {
    const headers = new Headers(options.headers);
    expect(headers.get("X-ReconForge-CSRF")).toBe("csrf-proof");
    expect(headers.get("X-ReconForge-Tenant")).toBe("tenant-a");
    expect(headers.get("X-ReconForge-Workspace")).toBe("workspace-a");
  }
});

test("closed field projection rejects leaked creator data, unexpected records, and cross-workspace pages", () => {
  const page = { exceptions: [record], pagination: { limit: 25, returned: 1, has_more: false, next_cursor: null } };
  expect(parseExceptionReviewListPage(page, "workspace-a")).toMatchObject({ exceptions: [record] });
  expect(() => parseExceptionReviewListPage({ ...page, exceptions: [{ ...record, created_by: "mutable-label" }] }, "workspace-a")).toThrow("exception_review_contract_invalid");
  expect(() => parseExceptionReviewListPage({ ...page, exceptions: [{ ...record, workspace_id: "workspace-b" }] }, "workspace-a")).toThrow("exception_review_contract_invalid");
  expect(() => parseExceptionReviewListPage({ ...page, pagination: { ...page.pagination, returned: 2 } }, "workspace-a")).toThrow("exception_review_contract_invalid");
  expect(() => parseExceptionReviewListPage({ ...page, pagination: { ...page.pagination, has_more: true } }, "workspace-a")).toThrow("exception_review_contract_invalid");
});

test("server rejection preserves the typed API error code for the review surface", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => response({ error: { code: "exception_self_review_refused" } }, 409)));
  await expect(transitionExceptionReview(session, "workspace-a", "EXC-001", "Resolved", 2)).rejects.toMatchObject({ status: 409, code: "exception_self_review_refused" });
});
