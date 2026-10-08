import { afterEach, expect, test, vi } from "vitest";
import { commandJob, loadJobDetail, loadJobPage, parseOperatorJob, type OperatorJob } from "./job-operations-data";
const session = { tenantId: "local", csrfToken: "synthetic-csrf", expiresAt: "2029-01-01T00:00:00Z" };
const scope = { workspaceId: "default", organizationId: "", entityId: "entity-a" };
const job: OperatorJob = { id: "job-a", version: 1, status: "queued", tenant_id: "local", workspace_id: "default", organization_id: "", entity_id: "entity-a", completed_units: 0, total_units: 2, retry_count: 0, retry_ceiling: 1, safe_error_code: "", created_at: "2026-10-08T00:00:00Z", updated_at: "2026-10-08T00:00:00Z", started_at: "", completed_at: "" };
const response = (value: unknown) => new Response(JSON.stringify(value), { status: 200 });
afterEach(() => vi.unstubAllGlobals());
test("closed job metadata rejects financial material, foreign scope, unsafe integers and impossible progress", () => {
  expect(parseOperatorJob(job, session, scope)).toEqual(job);
  for (const changed of [{ idempotency_key: "secret" }, { tenant_id: "sibling" }, { entity_id: "other" }, { version: Number.MAX_SAFE_INTEGER + 1 }, { completed_units: 3 }, { retry_count: 2 }]) {
    expect(() => parseOperatorJob({ ...job, ...changed }, session, scope)).toThrow("job_operations_contract_invalid");
  }
});
test("keyset order and status filter are independently checked", async () => {
  const fetcher = vi.fn(async (_url: RequestInfo | URL) => response({ records: [job], next_after_id: "" })); vi.stubGlobal("fetch", fetcher);
  expect((await loadJobPage(session, scope, "queued")).records).toEqual([job]);
  expect(String(fetcher.mock.calls[0][0])).toContain("entity_id=entity-a");
  await expect(loadJobPage(session, scope, "failed")).rejects.toThrow("job_operations_contract_invalid");
  await expect(loadJobPage(session, scope, "", "job-z")).rejects.toThrow("job_operations_contract_invalid");
});
test("commands send reviewed version and CSRF then verify the exact resulting job", async () => {
  const fetcher = vi.fn(async (_url: RequestInfo | URL, _options?: RequestInit) => response({ job: { ...job, status: "cancelled", version: 2 } })); vi.stubGlobal("fetch", fetcher);
  expect((await commandJob(session, scope, job, "cancel")).version).toBe(2);
  const [, options] = fetcher.mock.calls[0];
  expect(options?.method).toBe("POST"); expect(options?.credentials).toBe("same-origin");
  expect(options?.body).toBe('{"expected_version":1}'); expect(options?.headers).toMatchObject({ "X-ReconForge-CSRF": session.csrfToken, "X-ReconForge-Workspace": "default" });
});
test("detail rejects missing or inconsistent retained transitions", async () => {
  const event = { job_version: 1, from_status: "", to_status: "queued", actor_id: "user-a", occurred_at: job.created_at, reason_code: "CREATED" };
  vi.stubGlobal("fetch", vi.fn(async () => response({ job, transitions: [event], history_truncated: false })));
  expect((await loadJobDetail(session, scope, job.id)).transitions).toHaveLength(1);
  vi.stubGlobal("fetch", vi.fn(async () => response({ job, transitions: [{ ...event, job_version: 2 }], history_truncated: false })));
  await expect(loadJobDetail(session, scope, job.id)).rejects.toThrow("job_operations_contract_invalid");
});
