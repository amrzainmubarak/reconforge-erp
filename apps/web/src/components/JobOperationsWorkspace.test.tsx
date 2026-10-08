import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { BrowserSessionProvider, useBrowserSession } from "../browserSession";
import type { Locale } from "../types";
import { JobOperationsWorkspace } from "./JobOperationsWorkspace";
const session = { tenantId: "local", csrfToken: "synthetic-csrf", expiresAt: "2029-01-01T00:00:00Z" };
const job = { id: "job-a", version: 1, status: "queued", tenant_id: "local", workspace_id: "default", organization_id: "", entity_id: "entity-a", completed_units: 0, total_units: 2, retry_count: 0, retry_ceiling: 1, safe_error_code: "", created_at: "2026-10-08T00:00:00Z", updated_at: "2026-10-08T00:00:00Z", started_at: "", completed_at: "" };
const response = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status });
function Controls() { const auth = useBrowserSession(); return <><button onClick={() => auth.begin(session, "operator", auth.revision)}>Session</button><button onClick={() => auth.elevate("2029-01-01T00:00:00Z", auth.revision)}>Elevate</button><button onClick={() => auth.clear(auth.revision)}>Revoke</button></>; }
function setup(fetcher: typeof fetch, locale: Locale = "en") { vi.stubGlobal("fetch", fetcher); render(<BrowserSessionProvider><Controls /><JobOperationsWorkspace locale={locale} /></BrowserSessionProvider>); }
afterEach(() => vi.unstubAllGlobals());
const identity = { id: "user-a", username: "operator", permissions: ["ops.read", "jobs.manage"], authorized_scopes: { workspaces: ["default"] }, principal_type: "user" };
async function selectLane() { fireEvent.click(screen.getByText("Session")); await waitFor(() => expect(screen.getByLabelText("Workspace ID")).toHaveValue("default")); fireEvent.change(screen.getByLabelText("Entity ID"), { target: { value: "entity-a" } }); fireEvent.click(screen.getByRole("button", { name: "Load execution lane" })); }
test("operator inspection is scoped and actions require recent step-up", async () => {
  setup(vi.fn(async (url: RequestInfo | URL) => String(url).endsWith("/auth/me") ? response(identity) : String(url).includes("/job-a?") ? response({ job, transitions: [{ job_version: 1, from_status: "", to_status: "queued", actor_id: "user-a", occurred_at: job.created_at, reason_code: "CREATED" }], history_truncated: false }) : response({ records: [job], next_after_id: "" })));
  await selectLane(); fireEvent.click(await screen.findByRole("button", { name: "Inspect job: job-a" }));
  await screen.findByText("CREATED"); expect(screen.queryByRole("button", { name: "Cancel job" })).not.toBeInTheDocument();
});
test("revocation discards a late job response and clears metadata", async () => {
  let finish!: (value: Response) => void;
  const fetcher = vi.fn(async (url: RequestInfo | URL) => String(url).endsWith("/auth/me") ? response(identity) : new Promise<Response>((resolve) => { finish = resolve; })); setup(fetcher);
  await selectLane(); await waitFor(() => expect(finish).toBeDefined()); fireEvent.click(screen.getByText("Revoke"));
  await act(async () => finish(response({ records: [job], next_after_id: "" })));
  expect(screen.queryByText("job-a")).not.toBeInTheDocument(); expect(screen.getByRole("button", { name: "Sign in" })).toBeVisible();
});
test("Arabic job operations has translated controls and RTL", () => {
  setup(vi.fn(), "ar"); expect(screen.getByRole("main")).toHaveAttribute("dir", "rtl"); expect(screen.getByRole("heading", { name: "إدارة المهام الدائمة" })).toBeVisible();
});
