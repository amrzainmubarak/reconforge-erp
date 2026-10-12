import { act, renderHook } from "@testing-library/react";

import { BrowserSessionProvider, useBrowserSession } from "./browserSession";
import { AdminApiError } from "./data";

const now = new Date("2026-10-03T10:00:00Z");
const session = (tenantId = "tenant-a") => ({ tenantId, csrfToken: `proof-${tenantId}`, expiresAt: new Date(Date.now() + 60_000).toISOString() });

beforeEach(() => { vi.useFakeTimers(); vi.setSystemTime(now); window.localStorage.clear(); });
afterEach(() => vi.useRealTimers());

test("session and elevation expire independently without persisting credentials", () => {
  const { result } = renderHook(useBrowserSession, { wrapper: BrowserSessionProvider });
  act(() => result.current.begin(session(), "alice", result.current.revision));
  act(() => result.current.elevate(new Date(Date.now() + 5_000).toISOString(), result.current.revision));
  act(() => vi.advanceTimersByTime(5_000));
  expect(result.current).toMatchObject({ session: { tenantId: "tenant-a" }, stepUpExpiresAt: "", notice: "adminStepUpRequired" });
  act(() => vi.advanceTimersByTime(55_000));
  expect(result.current).toMatchObject({ session: null, username: "", stepUpExpiresAt: "", notice: "adminAuthRequired" });
  expect(window.localStorage.length).toBe(0);
});

test("old-tenant authentication failures cannot clear a newer session", () => {
  const { result } = renderHook(useBrowserSession, { wrapper: BrowserSessionProvider });
  act(() => result.current.begin(session(), "alice", result.current.revision));
  const oldRevision = result.current.revision;
  act(() => result.current.begin(session("tenant-b"), "bob", result.current.revision));
  act(() => { result.current.recover(new AdminApiError(401, "invalid_token"), oldRevision); result.current.elevate(new Date(Date.now() + 20_000).toISOString(), oldRevision); });
  expect(result.current).toMatchObject({ session: { tenantId: "tenant-b" }, username: "bob", stepUpExpiresAt: "", notice: null });
});

test.each([[401, "invalid_token"], [403, "csrf_required"], [400, "tenant_required"]])("HTTP %s %s discards the memory-only session", (status, code) => {
  const { result } = renderHook(useBrowserSession, { wrapper: BrowserSessionProvider });
  act(() => result.current.begin(session(), "alice", result.current.revision));
  act(() => { result.current.recover(new AdminApiError(status, code), result.current.revision); });
  expect(result.current.session).toBeNull();
});

test("step-up failure retains tenant while ordinary permission denial retains the session", () => {
  const { result } = renderHook(useBrowserSession, { wrapper: BrowserSessionProvider });
  act(() => result.current.begin(session(), "alice", result.current.revision));
  act(() => result.current.elevate(new Date(Date.now() + 20_000).toISOString(), result.current.revision));
  act(() => { result.current.recover(new AdminApiError(403, "permission_denied"), result.current.revision); });
  expect(result.current.stepUpExpiresAt).not.toBe("");
  act(() => { result.current.recover(new AdminApiError(403, "step_up_required"), result.current.revision); });
  expect(result.current).toMatchObject({ session: { tenantId: "tenant-a" }, stepUpExpiresAt: "", notice: "adminStepUpRequired" });
});

test("returning to a suspended tab checks expiry before privileged use", () => {
  const { result } = renderHook(useBrowserSession, { wrapper: BrowserSessionProvider });
  act(() => result.current.begin(session(), "alice", result.current.revision));
  act(() => { vi.setSystemTime(new Date(now.getTime() + 120_000)); window.dispatchEvent(new Event("focus")); });
  expect(result.current.session).toBeNull();
});

test.each(["invalid", "2020-01-01T00:00:00Z"])("rejects unusable session expiry %s", (expiresAt) => {
  const { result } = renderHook(useBrowserSession, { wrapper: BrowserSessionProvider });
  act(() => result.current.begin({ ...session(), expiresAt }, "alice", result.current.revision));
  expect(result.current).toMatchObject({ session: null, notice: "adminAuthRequired" });
});
