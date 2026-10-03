import { afterEach, expect, test, vi } from "vitest";
import { acknowledgeInbox, loadInboxPage, loadInboxWorkspaces, parseInboxNotification, parseInboxPage, type InboxNotification } from "./notification-inbox-data";

const session = { tenantId: "tenant-a", csrfToken: "csrf-proof", expiresAt: "2029-01-01T00:00:00Z" };
const record: InboxNotification = { id: "inbox_1", workspace_id: "workspace-a", organization_id: "", legal_entity_id: "", recipient_id: "user-a", topic: "job.failed", resource_type: "job", resource_id: "JOB-1", payload_digest: "1".repeat(64), created_at: "2026-10-03T00:00:00Z", read_at: null };
const response = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json" } });
afterEach(() => vi.unstubAllGlobals());

test("closed inbox contracts reject unsafe references, wrong scope and unsupported topics", () => {
  expect(parseInboxNotification(record)).toEqual(record);
  for (const unsafe of [{ ...record, resource_id: "https://untrusted.invalid" }, { ...record, topic: "approve.payment" }, { ...record, payload_digest: "invalid" }, { ...record, read_at: "unknown" }, { ...record, read_at: "2026-10-02T23:59:59Z" }, { ...record, legal_entity_id: "entity-a" }]) expect(() => parseInboxNotification(unsafe)).toThrow("inbox_contract_invalid");
  expect(() => parseInboxPage({ records: [record], total: 1, unread_count: 1 }, "workspace-b")).toThrow();
  expect(() => parseInboxPage({ records: [record, record], total: 2, unread_count: 2 }, "workspace-a")).toThrow();
  expect(() => parseInboxPage({ records: [record], total: 1, unread_count: 0 }, "workspace-a")).toThrow();
});

test("real request contract uses browser cookie, tenant, workspace, bounded pages and CSRF on acknowledgement", async () => {
  const fetcher = vi.fn(async (path: RequestInfo | URL, _options?: RequestInit) => String(path).endsWith("/workspaces") ? response({ workspaces: ["workspace-a"] }) : String(path).includes("/read?") ? response({ ...record, read_at: "2026-10-03T00:01:00Z" }) : response({ records: [record], total: 1, unread_count: 1 }));
  vi.stubGlobal("fetch", fetcher);
  expect(await loadInboxWorkspaces(session)).toEqual(["workspace-a"]);
  await loadInboxPage(session, "workspace-a", 0, false);
  await acknowledgeInbox(session, "workspace-a", record);
  expect(fetcher.mock.calls[1][0]).toContain("unread_only=false");
  const options = fetcher.mock.calls[2][1] as RequestInit;
  expect(options).toMatchObject({ method: "POST", credentials: "same-origin", cache: "no-store", headers: { "X-ReconForge-CSRF": "csrf-proof", "X-ReconForge-Workspace": "workspace-a", "X-ReconForge-Tenant": "tenant-a" } });
  expect(options.body).toBeUndefined();
});

test("acknowledgement never accepts another recipient, publication digest or resource identity", async () => {
  for (const changed of [{ recipient_id: "other" }, { payload_digest: "2".repeat(64) }, { id: "inbox_other" }, { resource_id: "APR-2" }]) {
    vi.stubGlobal("fetch", vi.fn(async () => response({ ...record, ...changed, read_at: "2026-10-03T00:01:00Z" })));
    await expect(acknowledgeInbox(session, "workspace-a", record)).rejects.toThrow("inbox_contract_invalid");
  }
});
