import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { BrowserSessionProvider, useBrowserSession } from "../browserSession";
import { ExceptionReviewWorkspace } from "./ExceptionReviewWorkspace";
import type { Locale } from "../types";

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
const response = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json" } });

function SessionControl() {
  const auth = useBrowserSession();
  return <button type="button" onClick={() => auth.begin({ tenantId: "tenant-a", csrfToken: "csrf-proof", expiresAt: new Date(Date.now() + 60_000).toISOString() }, "reviewer", auth.revision)}>Start review session</button>;
}

function setup(fetcher: typeof fetch, locale: Locale = "en") {
  vi.stubGlobal("fetch", fetcher);
  render(<BrowserSessionProvider><SessionControl /><ExceptionReviewWorkspace locale={locale} /></BrowserSessionProvider>);
}

async function enterWorkspace() {
  fireEvent.click(screen.getByRole("button", { name: "Start review session" }));
  const workspace = await screen.findByLabelText("Authorized workspace");
  fireEvent.change(workspace, { target: { value: "workspace-a" } });
  await screen.findByRole("button", { name: "Review" });
}

afterEach(() => vi.unstubAllGlobals());

test("renders the real review record, immutable evidence correlations, assignment, and version-bound transition", async () => {
  let current = { ...record, history: [history], history_page: { limit: 25, has_more: false, next_cursor: null } };
  const fetcher = vi.fn(async (path: RequestInfo | URL, options?: RequestInit) => {
    const url = String(path);
    if (url.endsWith("/auth/me")) return response(identity);
    if (options?.method === "POST" && url.endsWith("/assign")) {
      current = { ...current, owner: "reviewer-2", row_version: 3, history: [{ ...history, id: "EXH-002", to_owner: "reviewer-2", audit_event_id: "AUD-002", outbox_event_id: "OUT-002" }] };
      return response({ exception: current });
    }
    if (options?.method === "POST" && url.endsWith("/status")) {
      current = { ...current, status: "Resolved", row_version: 4, history: [{ ...history, id: "EXH-003", action: "exception_review_transition", from_status: "In Review", to_status: "Resolved", to_owner: "reviewer-2", reason: "Source corrected.", audit_event_id: "AUD-003", outbox_event_id: "OUT-003" }] };
      return response({ exception: current });
    }
    if (url.includes("/EXC-001?")) return response({ exception: current });
    return response({ exceptions: [record], pagination: { limit: 25, returned: 1, has_more: false, next_cursor: null } });
  });
  setup(fetcher);
  await enterWorkspace();

  fireEvent.click(screen.getByRole("button", { name: "Review" }));
  await screen.findByRole("heading", { name: "Exception details" });
  expect(screen.getByText("Amount variance needs a retained decision.")).toBeVisible();
  expect(screen.getAllByText("2").length).toBeGreaterThan(0);
  expect(screen.getByText("AUD-001")).toBeVisible();
  expect(screen.getByText("OUT-001")).toBeVisible();
  expect(screen.queryByText("created_by")).not.toBeInTheDocument();

  fireEvent.change(screen.getByLabelText("Reviewer user ID"), { target: { value: "reviewer-2" } });
  fireEvent.click(screen.getByRole("button", { name: "Assign reviewer" }));
  await screen.findByText("The server confirmed the action and returned the current record version.");
  expect(screen.getAllByText("3").length).toBeGreaterThan(0);
  const assignment = fetcher.mock.calls.find(([path, options]) => String(path).endsWith("/assign") && options?.method === "POST");
  expect(JSON.parse(String(assignment?.[1]?.body))).toEqual({ owner: "reviewer-2", expected_version: 2 });
  expect(new Headers(assignment?.[1]?.headers).get("X-ReconForge-CSRF")).toBe("csrf-proof");

  fireEvent.change(screen.getByLabelText("Recorded reason"), { target: { value: "Source corrected." } });
  fireEvent.click(screen.getByRole("button", { name: "Submit decision" }));
  await waitFor(() => expect(screen.getAllByText("Resolved").length).toBeGreaterThan(0));
  const transition = fetcher.mock.calls.find(([path, options]) => String(path).endsWith("/status") && options?.method === "POST");
  expect(JSON.parse(String(transition?.[1]?.body))).toEqual({ status: "Resolved", expected_version: 3, reason: "Source corrected." });
});

test("refuses a server-rejected terminal decision without fabricating a completed status", async () => {
  const fetcher = vi.fn(async (path: RequestInfo | URL, options?: RequestInit) => {
    const url = String(path);
    if (url.endsWith("/auth/me")) return response(identity);
    if (options?.method === "POST") return response({ error: { code: "exception_reviewer_assignment_required" } }, 409);
    if (url.includes("/EXC-001?")) return response({ exception: { ...record, history: [history], history_page: { limit: 25, has_more: false, next_cursor: null } } });
    return response({ exceptions: [record], pagination: { limit: 25, returned: 1, has_more: false, next_cursor: null } });
  });
  setup(fetcher);
  await enterWorkspace();
  fireEvent.click(screen.getByRole("button", { name: "Review" }));
  await screen.findByRole("heading", { name: "Exception details" });
  fireEvent.click(screen.getByRole("button", { name: "Submit decision" }));
  await screen.findByText("Select an eligible reviewer in the same authorized scope before making that decision.");
  expect(screen.queryByText("The server confirmed the action and returned the current record version.")).not.toBeInTheDocument();
  expect(screen.getAllByText("In Review").length).toBeGreaterThan(0);
});

test("Arabic review surface remains RTL, labeled, focusable, and does not create local fallback records", async () => {
  const fetcher = vi.fn(async (path: RequestInfo | URL) => String(path).endsWith("/auth/me") ? response(identity) : response({ exceptions: [], pagination: { limit: 25, returned: 0, has_more: false, next_cursor: null } }));
  setup(fetcher, "ar");
  expect(screen.getByRole("main")).toHaveAttribute("dir", "rtl");
  expect(screen.getByLabelText("كلمة المرور")).toHaveAttribute("type", "password");
  fireEvent.click(screen.getByRole("button", { name: "Start review session" }));
  fireEvent.change(await screen.findByLabelText("مساحة العمل المصرح بها"), { target: { value: "workspace-a" } });
  await screen.findByText("لا توجد استثناءات تطابق هذا العرض المصرح به.");
  expect(screen.queryByText("Synthetic inventory variance needs evidence.")).not.toBeInTheDocument();
});
