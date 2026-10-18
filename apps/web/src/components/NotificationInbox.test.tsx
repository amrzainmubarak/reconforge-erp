import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { BrowserSessionProvider, useBrowserSession } from "../browserSession";
import type { Locale } from "../types";
import { NotificationInbox } from "./NotificationInbox";

const session = { tenantId: "tenant-a", csrfToken: "csrf-proof", expiresAt: "2029-01-01T00:00:00Z" };
const record = { id: "inbox_1", workspace_id: "workspace-a", organization_id: "", legal_entity_id: "", recipient_id: "user-a", topic: "workflow.review_required", resource_type: "approval", resource_id: "APR-1", payload_digest: "1".repeat(64), created_at: "2026-10-03T00:00:00Z", read_at: null };
const response = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json" } });
function SessionControls() {
  const auth = useBrowserSession();
  return <><button onClick={() => auth.begin(session, "reviewer", auth.revision)}>Session A</button><button onClick={() => auth.clear(auth.revision)}>Clear session</button></>;
}
function setup(fetcher: typeof fetch, locale: Locale = "en") {
  vi.stubGlobal("fetch", fetcher);
  render(<BrowserSessionProvider><SessionControls /><NotificationInbox locale={locale} /></BrowserSessionProvider>);
}
afterEach(() => vi.unstubAllGlobals());

test("persisted responses drive translated own-recipient inbox and one acknowledgement", async () => {
  let readAt: string | null = null;
  const fetcher = vi.fn(async (path: RequestInfo | URL, options?: RequestInit) => {
    if (String(path).endsWith("/workspaces")) return response({ workspaces: ["workspace-a"] });
    if (options?.method === "POST") { readAt = "2026-10-03T00:01:00Z"; return response({ ...record, read_at: readAt }); }
    return response({ records: [{ ...record, read_at: readAt }], total: 1, unread_count: readAt ? 0 : 1 });
  });
  setup(fetcher); fireEvent.click(screen.getByText("Session A"));
  await screen.findByRole("heading", { name: "Review required" });
  const button = screen.getByRole("button", { name: "Mark as read: APR-1" });
  fireEvent.click(button); fireEvent.click(button);
  await screen.findByText("Read acknowledgement:", { exact: false });
  expect(fetcher.mock.calls.filter(([, options]) => options?.method === "POST")).toHaveLength(1);
  expect(screen.queryByRole("button", { name: "Mark as read: APR-1" })).not.toBeInTheDocument();
  expect(screen.queryByRole("link")).not.toBeInTheDocument();
});

test("Arabic notification inbox has RTL, translated controls and readable identifiers", async () => {
  const fetcher = vi.fn(async (path: RequestInfo | URL) => String(path).endsWith("/workspaces") ? response({ workspaces: ["workspace-a"] }) : response({ records: [record], total: 1, unread_count: 1 }));
  setup(fetcher, "ar"); fireEvent.click(screen.getByText("Session A"));
  await screen.findByRole("heading", { name: "مراجعة مطلوبة" });
  expect(screen.getByRole("main")).toHaveAttribute("dir", "rtl");
  expect(screen.getByRole("button", { name: "تحديد كمقروء: APR-1" })).toBeEnabled();
  expect(screen.getByRole("combobox", { name: "مساحة العمل" })).toHaveValue("workspace-a");
});

test("session revocation clears displayed records and discards late sensitive responses", async () => {
  let finish!: (response: Response) => void;
  const pending = new Promise<Response>((resolve) => { finish = resolve; });
  const fetcher = vi.fn((path: RequestInfo | URL) => String(path).endsWith("/workspaces") ? Promise.resolve(response({ workspaces: ["workspace-a"] })) : pending);
  setup(fetcher); fireEvent.click(screen.getByText("Session A"));
  await waitFor(() => expect(fetcher.mock.calls.some(([path]) => String(path).includes("/inbox?"))).toBe(true));
  fireEvent.click(screen.getByText("Clear session"));
  await act(async () => finish(response({ records: [record], total: 1, unread_count: 1 })));
  expect(screen.queryByText("APR-1")).not.toBeInTheDocument();
  expect(screen.getByLabelText("Password")).toBeVisible();
});

test("permission loss produces a safe denial with no cached financial reference", async () => {
  setup(vi.fn(async () => response({ error: { code: "permission_denied" } }, 403)));
  fireEvent.click(screen.getByText("Session A"));
  await screen.findByRole("alert");
  expect(screen.getByRole("alert")).toHaveTextContent("does not have access");
  expect(screen.queryByText("APR-1")).not.toBeInTheDocument();
});

test("successful login remounts busy state, permits acknowledgement and permits another login after logout", async () => {
  let readAt: string | null = null;
  const fetcher = vi.fn(async (path: RequestInfo | URL, options?: RequestInit) => {
    if (String(path).endsWith("/auth/browser/login")) return response({ csrf_token: "csrf-proof", expires_at: "2029-01-01T00:00:00Z" });
    if (String(path).endsWith("/auth/logout")) return response({ status: "logged_out" });
    if (String(path).endsWith("/workspaces")) return response({ workspaces: ["workspace-a"] });
    if (options?.method === "POST") { readAt = "2026-10-03T00:01:00Z"; return response({ ...record, read_at: readAt }); }
    return response({ records: [{ ...record, read_at: readAt }], total: 1, unread_count: readAt ? 0 : 1 });
  });
  setup(fetcher);
  async function signIn() {
    fireEvent.change(screen.getByLabelText("Username"), { target: { value: "reviewer" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "Synthetic-123" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await screen.findByRole("heading", { name: "Review required" });
    expect(screen.getByRole("button", { name: "Sign out" })).toBeEnabled();
  }
  await signIn();
  expect(screen.getByRole("button", { name: "Mark as read: APR-1" })).toBeEnabled();
  fireEvent.click(screen.getByRole("button", { name: "Mark as read: APR-1" }));
  await screen.findByText("Read acknowledgement:", { exact: false });
  fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
  await screen.findByLabelText("Password");
  expect(screen.getByRole("button", { name: "Sign in" })).toBeEnabled();
  await signIn();
  expect(fetcher.mock.calls.filter(([path]) => String(path).endsWith("/auth/browser/login"))).toHaveLength(2);
});

test("expired-session recovery while acknowledgement is busy resets private state without retaining references", async () => {
  const fetcher = vi.fn(async (path: RequestInfo | URL, options?: RequestInit) => {
    if (String(path).endsWith("/workspaces")) return response({ workspaces: ["workspace-a"] });
    if (options?.method === "POST") return response({ error: { code: "auth_required" } }, 401);
    return response({ records: [record], total: 1, unread_count: 1 });
  });
  setup(fetcher); fireEvent.click(screen.getByText("Session A"));
  fireEvent.click(await screen.findByRole("button", { name: "Mark as read: APR-1" }));
  await screen.findByLabelText("Password");
  expect(screen.getByRole("button", { name: "Sign in" })).toBeEnabled();
  expect(screen.queryByText("APR-1")).not.toBeInTheDocument();
});

test("permission revoked during acknowledgement discards previously displayed references", async () => {
  const fetcher = vi.fn(async (path: RequestInfo | URL, options?: RequestInit) => {
    if (String(path).endsWith("/workspaces")) return response({ workspaces: ["workspace-a"] });
    if (options?.method === "POST") return response({ error: { code: "permission_denied" } }, 403);
    return response({ records: [record], total: 1, unread_count: 1 });
  });
  setup(fetcher); fireEvent.click(screen.getByText("Session A"));
  fireEvent.click(await screen.findByRole("button", { name: "Mark as read: APR-1" }));
  await screen.findByRole("alert");
  expect(screen.queryByText("APR-1")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Refresh inbox" })).toBeEnabled();
});
