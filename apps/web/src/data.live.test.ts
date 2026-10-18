import { classifyStudioDataProvenance, loadLiveStudioContract } from "./data";

const metric = {
  id: "met-1", workspace_id: "workspace-1", metric_key: "period_readiness", period_name: "2026-07",
  value: 91, value_text: "91.00", lineage: "period controls", computed_at: "2026-07-28T09:58:00Z",
  name: "Period readiness", description: "Governed close readiness",
};

function reply(status: number, body: unknown): Response {
  return { ok: status >= 200 && status < 300, status, json: async () => body } as Response;
}

test("loads the guarded same-origin live contract with exact values", async () => {
  const fetcher = vi.fn(async () => reply(200, { metrics: [metric] }));
  const result = await loadLiveStudioContract({ fetcher, period: "2026-07", now: new Date("2026-07-28T10:00:00Z"), staleAfterSeconds: 300 });
  expect(fetcher).toHaveBeenCalledOnce();
  expect(fetcher).toHaveBeenCalledWith("/api/v1/metrics/dashboard?period=2026-07", expect.objectContaining({ cache: "no-store", credentials: "same-origin" }));
  expect(result).toMatchObject({
    mode: "live",
    empty: false,
    stale: false,
    generated_at: metric.computed_at,
    provenance: { state: "live", source: "same_origin_authorized_api", operational_evidence: "unverified" },
  });
  expect(result.metrics[0].value_text).toBe("91.00");
});

test("authenticated live metrics carry the selected tenant without disclosing a CSRF proof on reads", async () => {
  const fetcher = vi.fn(async () => reply(200, { metrics: [metric] }));
  await loadLiveStudioContract({ fetcher, session: { tenantId: "tenant-a", csrfToken: "private-proof", expiresAt: "2026-10-03T11:00:00Z" } });
  expect(fetcher).toHaveBeenCalledWith("/api/v1/metrics/dashboard", expect.objectContaining({ credentials: "same-origin", headers: { Accept: "application/json", "X-ReconForge-Tenant": "tenant-a" } }));
  expect(JSON.stringify(fetcher.mock.calls)).not.toContain("private-proof");
});

test("tenant context cannot be sent to an external metrics origin", async () => {
  const fetcher = vi.fn();
  await expect(loadLiveStudioContract({ fetcher, baseUrl: "https://outside.invalid", session: { tenantId: "tenant-a", csrfToken: "private-proof", expiresAt: "2026-10-03T11:00:00Z" } })).rejects.toThrow("same origin");
  expect(fetcher).not.toHaveBeenCalled();
});

test("keeps unclassified data out of the live operational-evidence state", () => {
  expect(classifyStudioDataProvenance({ metrics: [] })).toEqual({
    state: "unknown",
    source: "unknown",
    operational_evidence: "unknown",
  });
});

test("distinguishes empty and stale authorized responses", async () => {
  const empty = await loadLiveStudioContract({ fetcher: async () => reply(200, { metrics: [] }) });
  const stale = await loadLiveStudioContract({ fetcher: async () => reply(200, { metrics: [metric] }), now: new Date("2026-07-28T10:10:00Z"), staleAfterSeconds: 300 });
  expect(empty).toMatchObject({ empty: true, stale: false, generated_at: null });
  expect(stale.stale).toBe(true);
});

test.each([[401, "authentication"], [403, "metrics.read"], [500, "500"]])("reports HTTP %s without trying a fallback", async (status, message) => {
  const fetcher = vi.fn(async () => reply(Number(status), {}));
  await expect(loadLiveStudioContract({ fetcher })).rejects.toThrow(String(message));
  expect(fetcher).toHaveBeenCalledOnce();
});

test.each([
  { metricz: [] },
  { metrics: [{ ...metric, value_text: "NaN" }] },
  { metrics: [{ ...metric, secret: "unexpected" }] },
])("rejects malformed or expanded live contracts", async (body) => {
  await expect(loadLiveStudioContract({ fetcher: async () => reply(200, body) })).rejects.toThrow("authorized metrics contract");
});

test("rejects an unsafe freshness policy before making a request", async () => {
  const fetcher = vi.fn();
  await expect(loadLiveStudioContract({ fetcher, staleAfterSeconds: 1 })).rejects.toThrow("stale threshold");
  expect(fetcher).not.toHaveBeenCalled();
});
