import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";

import { translate } from "../i18n";
import { LiveStudio } from "./LiveStudio";
import { BrowserSessionProvider, useBrowserSession } from "../browserSession";
import { AdminApiError } from "../data";

const metric = { id: "m1", workspace_id: "w1", metric_key: "match_rate", period_name: "2026-07", value: 88, value_text: "88.00", lineage: "approved matches", computed_at: new Date().toISOString(), name: "Match rate", description: "Rate" };
const response = (status: number, body: unknown) => ({ ok: status >= 200 && status < 300, status, json: async () => body });

afterEach(() => vi.unstubAllGlobals());

test("renders loading then live exact metric and lineage", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => response(200, { metrics: [metric] })));
  render(<BrowserSessionProvider><LiveStudio locale="en" translate={(key) => translate("en", key)} /></BrowserSessionProvider>);
  expect(screen.getByText("Loading authorized metrics…")).toBeInTheDocument();
  expect(await screen.findByText("Match rate")).toBeInTheDocument();
  expect(screen.getByText("88.00")).toBeInTheDocument();
  expect(screen.getByText("approved matches")).toBeInTheDocument();
});

test("renders an explicit empty authorized state", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => response(200, { metrics: [] })));
  render(<BrowserSessionProvider><LiveStudio locale="en" translate={(key) => translate("en", key)} /></BrowserSessionProvider>);
  expect(await screen.findByText("The authorized workspace returned no metrics.")).toBeInTheDocument();
});

test("renders permission failure and retries only the guarded endpoint", async () => {
  const fetcher = vi.fn()
    .mockResolvedValueOnce(response(403, {}))
    .mockResolvedValueOnce(response(200, { metrics: [metric] }));
  vi.stubGlobal("fetch", fetcher);
  render(<BrowserSessionProvider><LiveStudio locale="en" translate={(key) => translate("en", key)} /></BrowserSessionProvider>);
  expect(await screen.findByText("Live Studio metrics.read permission is required.")).toBeInTheDocument();
  expect(screen.queryByText("Synthetic local demo data only")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Retry authorized request" }));
  await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(2));
  expect(await screen.findByText("Match rate")).toBeInTheDocument();
  expect(fetcher.mock.calls.every(([url]) => String(url).includes("/api/v1/metrics/dashboard"))).toBe(true);
});

function TenantControls() {
  const auth = useBrowserSession();
  const select = (tenantId: string) => auth.begin({ tenantId, csrfToken: `proof-${tenantId}`, expiresAt: new Date(Date.now() + 60_000).toISOString() }, tenantId, auth.revision);
  return <><button onClick={() => select("tenant-a")}>Select A</button><button onClick={() => select("tenant-b")}>Select B</button><button onClick={() => auth.recover(new AdminApiError(403, "step_up_required"), auth.revision)}>Expire step-up</button></>;
}

test("expired privileged access retains authorized tenant-scoped metrics reads", async () => {
  const fetcher = vi.fn(async (_input: RequestInfo | URL, options?: RequestInit) => response(200, { metrics: new Headers(options?.headers).has("X-ReconForge-Tenant") ? [metric] : [] }));
  vi.stubGlobal("fetch", fetcher);
  render(<BrowserSessionProvider><TenantControls /><LiveStudio locale="en" translate={(key) => translate("en", key)} /></BrowserSessionProvider>);
  await screen.findByText("The authorized workspace returned no metrics.");
  fireEvent.click(screen.getByRole("button", { name: "Select A" }));
  await screen.findByText("Match rate");
  fireEvent.click(screen.getByRole("button", { name: "Expire step-up" }));
  expect(await screen.findByText("Match rate")).toBeInTheDocument();
  expect(new Headers(fetcher.mock.lastCall?.[1]?.headers).get("X-ReconForge-Tenant")).toBe("tenant-a");
  expect(screen.queryByRole("button", { name: "Sign in to administration" })).not.toBeInTheDocument();
});

test("switching tenant aborts prior reads and rejects late responses even when transport ignores abort", async () => {
  let resolveA!: (value: ReturnType<typeof response>) => void;
  const pendingA = new Promise<ReturnType<typeof response>>((resolve) => { resolveA = resolve; });
  let signalA: AbortSignal | null | undefined;
  const fetcher = vi.fn((_input: RequestInfo | URL, options?: RequestInit) => {
    const tenant = new Headers(options?.headers).get("X-ReconForge-Tenant");
    if (tenant === "tenant-a") { signalA = options?.signal; return pendingA; }
    return Promise.resolve(response(200, { metrics: tenant === "tenant-b" ? [{ ...metric, name: "Tenant B metric" }] : [] }));
  });
  vi.stubGlobal("fetch", fetcher);
  render(<BrowserSessionProvider><TenantControls /><LiveStudio locale="en" translate={(key) => translate("en", key)} /></BrowserSessionProvider>);
  await screen.findByText("The authorized workspace returned no metrics.");
  fireEvent.click(screen.getByRole("button", { name: "Select A" }));
  await waitFor(() => expect(signalA).toBeDefined());
  fireEvent.click(screen.getByRole("button", { name: "Select B" }));
  expect(signalA?.aborted).toBe(true);
  expect(await screen.findByText("Tenant B metric")).toBeInTheDocument();
  await act(async () => { resolveA(response(200, { metrics: [{ ...metric, name: "Tenant A private metric" }] })); });
  expect(screen.queryByText("Tenant A private metric")).not.toBeInTheDocument();
  expect(screen.getByText("Tenant B metric")).toBeInTheDocument();
});

test.each([{ status: 401, code: "invalid_token" }, { status: 400, code: "tenant_required" }])("$code offers sign-in without retrying authentication or rendering cached metrics", async ({ status, code }) => {
  const fetcher = vi.fn(async () => response(status, { error: { code } }));
  vi.stubGlobal("fetch", fetcher);
  const signIn = vi.fn();
  render(<BrowserSessionProvider><LiveStudio locale="en" translate={(key) => translate("en", key)} onSignIn={signIn} /></BrowserSessionProvider>);
  fireEvent.click(await screen.findByRole("button", { name: "Sign in to administration" }));
  expect(signIn).toHaveBeenCalledOnce();
  expect(fetcher).toHaveBeenCalledOnce();
  expect(screen.queryByRole("button", { name: "Retry authorized request" })).not.toBeInTheDocument();
});
