import { StrictMode } from "react";
import { fireEvent, render, screen } from "@testing-library/react";

import { BrowserSessionProvider } from "../browserSession";
import { translate, type MessageKey } from "../i18n";
import { AdminAudit } from "./AdminAudit";

const t = (key: MessageKey) => translate("en", key);
const reply = (status: number, body: unknown) => ({ ok: status >= 200 && status < 300, status, json: async () => body });

function setup(error?: { status: number; code: string }) {
  let events = 0;
  const fetcher = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.endsWith("/browser/login")) return reply(200, { csrf_token: "memory-only-proof", expires_at: new Date(Date.now() + 60_000).toISOString() });
    if (url.endsWith("/step-up")) return reply(200, { method: "password_reauthentication", expires_at: new Date(Date.now() + 30_000).toISOString() });
    if (url.endsWith("/logout")) return reply(200, { revoked: true, username: "alice" });
    if (url.includes("/audit/events")) {
      if (error && events++ === 0) return reply(error.status, { error: { code: error.code } });
      return reply(200, { events: [], pagination: { next_cursor: null } });
    }
    if (url.endsWith("/audit/verify")) return reply(200, { ok: true, chains: [] });
    return reply(403, { error: { code: "permission_denied" } });
  });
  vi.stubGlobal("fetch", fetcher);
  render(<StrictMode><BrowserSessionProvider><AdminAudit locale="en" translate={t} /></BrowserSessionProvider></StrictMode>);
  return fetcher;
}

async function signIn() {
  fireEvent.change(screen.getByLabelText("Tenant ID"), { target: { value: "tenant-a" } });
  fireEvent.change(screen.getByLabelText("Username"), { target: { value: "alice" } });
  fireEvent.change(screen.getByLabelText("Password"), { target: { value: "Synthetic-test-only-123!" } });
  fireEvent.click(screen.getByRole("button", { name: "Sign in to administration" }));
  await screen.findByRole("heading", { name: "Confirm privileged access" });
}

async function elevate() {
  fireEvent.change(screen.getByLabelText("Password"), { target: { value: "Synthetic-test-only-123!" } });
  fireEvent.click(screen.getByRole("button", { name: "Confirm and continue" }));
}

afterEach(() => vi.unstubAllGlobals());

test("server step-up expiry reopens reauthentication and succeeds without reloading the page", async () => {
  const fetcher = setup({ status: 403, code: "step_up_required" });
  await signIn();
  await elevate();
  expect(await screen.findByText("Recent human reauthentication is required.")).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Confirm privileged access" })).toBeInTheDocument();
  expect(screen.queryByRole("table")).not.toBeInTheDocument();
  await elevate();
  expect(await screen.findByText("Privileged access is active")).toBeInTheDocument();
  expect(await screen.findByRole("table")).toBeInTheDocument();
  expect(fetcher.mock.calls.filter(([url]) => String(url).endsWith("/step-up"))).toHaveLength(2);
});

test.each([{ status: 401, code: "invalid_token" }, { status: 403, code: "csrf_required" }])("$code clears privileged views and returns to sign-in", async (error) => {
  setup(error);
  await signIn();
  await elevate();
  expect(await screen.findByRole("heading", { name: "Sign in to administration" })).toBeInTheDocument();
  expect(screen.queryByText("Privileged access is active")).not.toBeInTheDocument();
  expect(screen.queryByRole("table")).not.toBeInTheDocument();
});

test("sign-out revokes the cookie session with the selected tenant and CSRF proof", async () => {
  const fetcher = setup();
  await signIn();
  fireEvent.click(screen.getByRole("button", { name: "Sign out / switch tenant" }));
  expect(await screen.findByRole("heading", { name: "Sign in to administration" })).toBeInTheDocument();
  expect(fetcher).toHaveBeenCalledWith("/api/v1/auth/logout", expect.objectContaining({ method: "POST", credentials: "same-origin", headers: { Accept: "application/json", "X-ReconForge-Tenant": "tenant-a", "X-ReconForge-CSRF": "memory-only-proof" } }));
  expect(window.localStorage.getItem("reconforge.session")).toBeNull();
});
