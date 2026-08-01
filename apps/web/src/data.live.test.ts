import { loadLiveStudioContract } from "./data";

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
  expect(result).toMatchObject({ mode: "live", empty: false, stale: false, generated_at: metric.computed_at });
  expect(result.metrics[0].value_text).toBe("91.00");
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
