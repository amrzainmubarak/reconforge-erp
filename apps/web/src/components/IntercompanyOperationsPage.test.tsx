import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { BrowserSessionProvider, useBrowserSession } from "../browserSession";
import * as data from "../intercompany-operations-data";
import { icTranslate } from "../intercompany-operations-i18n";
import { icFixture } from "../intercompany-operations-test-fixture";
import IntercompanyOperationsPage from "./IntercompanyOperationsPage";

const identity = { id: "poster", principal_type: "user", step_up_active: true, permissions: ["intercompany_operations.read", "intercompany_operations.prepare", "intercompany_operations.review", "intercompany_operations.post", "finance_core.read", "finance_core.manage", "finance_core.validate", "finance_core.post"], authorized_scopes: { workspaces: ["work"], organizations: ["org"], legal_entities: ["seller", "buyer", "group"] } };
const catalog = { entities: ["seller", "buyer", "group"].map(id => ({ id, entity_code: id.toUpperCase(), name: id, currency_code: "USD" })), accounts: [], journals: [], periods: [], maps: [] };
const response = (value: object) => new Response(JSON.stringify(value), { status: 200 });
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(done => { resolve = done; }); return { promise, resolve }; }
function BeginSession() { const auth = useBrowserSession(); return <button onClick={() => auth.begin({ tenantId: "synthetic", csrfToken: "csrf", expiresAt: "2099-01-01" }, "poster", auth.revision)}>Begin session</button>; }
function renderSession(locale: "en" | "ar" = "en") { render(<BrowserSessionProvider><BeginSession /><IntercompanyOperationsPage locale={locale} /></BrowserSessionProvider>); fireEvent.click(screen.getByRole("button", { name: "Begin session" })); }
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });
describe("real intercompany Studio controls", () => {
  it.each(["en", "ar"] as const)("exposes the actual accessibility and skip-navigation main landmark in %s", locale => {
    render(<BrowserSessionProvider><IntercompanyOperationsPage locale={locale} /></BrowserSessionProvider>);
    expect(screen.getByRole("form", { name: icTranslate(locale, "login") })).toBeInTheDocument();
    expect(screen.getByRole("main")).toHaveAttribute("id", "main-content"); expect(screen.getByRole("main")).toHaveAttribute("dir", locale === "ar" ? "rtl" : "ltr");
    expect(screen.getByLabelText(icTranslate(locale, "password"))).toHaveAttribute("type", "password"); expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });
  it("holds scope edits until deferred identity has populated both fields", async () => {
    const pending = deferred<Response>(); vi.stubGlobal("fetch", vi.fn(() => pending.promise)); renderSession();
    expect(screen.getByLabelText("Workspace ID")).toBeDisabled(); expect(screen.getByLabelText("Organization ID")).toBeDisabled(); expect(screen.getByRole("button", { name: "Apply scope" })).toBeDisabled();
    await act(async () => pending.resolve(response(identity)));
    expect(screen.getByLabelText("Workspace ID")).toHaveValue("work"); expect(screen.getByLabelText("Organization ID")).toHaveValue("org");
    fireEvent.change(screen.getByLabelText("Workspace ID"), { target: { value: "other-work" } }); fireEvent.change(screen.getByLabelText("Organization ID"), { target: { value: "other-org" } });
    expect(screen.getByLabelText("Workspace ID")).toHaveValue("other-work"); expect(screen.getByLabelText("Organization ID")).toHaveValue("other-org");
  });
  it.each(["en", "ar"] as const)("commits actual WebCrypto verification before exposing download in %s", async locale => {
    const { proof, detail } = await icFixture(), complete = deferred<data.IcEvidence>(); const original = data.verifyIcEvidence;
    const sourceResponse = deferred<Response>(), publish = deferred<data.IcEvidence>();
    vi.spyOn(data, "verifyIcEvidence").mockImplementation(async (...args) => {
      const checked = await original(...args); complete.resolve(checked); return publish.promise;
    });
    vi.stubGlobal("fetch", vi.fn(async (url: RequestInfo | URL) => {
      const path = String(url);
      if (path.endsWith(`/sources/${proof.source.id}`)) return sourceResponse.promise;
      return response(path.endsWith("/auth/me") ? identity : path.endsWith("/catalog") ? { catalog } : path.endsWith("/evidence") ? { evidence: proof } : { sources: [detail] });
    }));
    renderSession(locale); await waitFor(() => expect(screen.getByRole("button", { name: icTranslate(locale, "apply") })).toBeEnabled()); fireEvent.click(screen.getByRole("button", { name: icTranslate(locale, "apply") }));
    await screen.findByRole("form", { name: icTranslate(locale, "prepare") }); fireEvent.change(screen.getByLabelText(icTranslate(locale, "sources")), { target: { value: proof.source.id } });
    // Commit the retained source and its invalidation effects before verification.
    await act(async () => sourceResponse.resolve(response({ source: detail })));
    expect(screen.getByRole("region", { name: icTranslate(locale, "plan") })).toBeInTheDocument();
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: icTranslate(locale, "verify") })); await complete.promise; });
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: icTranslate(locale, "download") })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: icTranslate(locale, "verify") })).toBeDisabled();
    await act(async () => publish.resolve(await complete.promise));
    expect(await screen.findByRole("status")).toHaveTextContent(icTranslate(locale, "verified")); expect(screen.getByRole("button", { name: icTranslate(locale, "download") })).toBeEnabled();
    expect(screen.getByText("effect-buyer")).toBeInTheDocument(); expect(screen.getByText("effect-seller")).toBeInTheDocument();
  });
  it("retains exact route, command and digest after a lost review acknowledgement", async () => {
    const { proof, detail } = await icFixture(); const prepared = { ...proof.plan, phase: 0, status: "Prepared" as const, reviewer_actor_id: null, posted_actor_id: null, posting_effect_ids: {} };
    const reviewed = { ...prepared, phase: 1, status: "Reviewed" as const, reviewer_actor_id: "checker" }; let live: data.IcPlan = prepared; const bodies: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
      const path = String(url);
      if (path.endsWith("/auth/me")) return response({ ...identity, id: "checker" });
      if (path.endsWith("/review")) { bodies.push(String(init?.body)); if (bodies.length === 1) throw new TypeError("Lost native acknowledgement"); live = reviewed; return response({ plan: reviewed }); }
      return response(path.endsWith("/catalog") ? { catalog } : path.endsWith("/sources") ? { sources: [{ ...detail, recognized: live.phase === 2, sequence: 0, plans: [live] }] } : { source: { ...detail, recognized: false, sequence: 0, plans: [live] } });
    }));
    renderSession(); await waitFor(() => expect(screen.getByRole("button", { name: "Apply scope" })).toBeEnabled()); fireEvent.click(screen.getByRole("button", { name: "Apply scope" }));
    await screen.findByRole("form", { name: "Prepare paired service charge" }); fireEvent.change(screen.getByLabelText("Retained sources"), { target: { value: proof.source.id } });
    const region = await screen.findByRole("region", { name: "Native operation" });
    fireEvent.change(region.querySelector("input")!, { target: { value: "Independent review" } }); fireEvent.click(screen.getByRole("button", { name: "Review every native entry" }));
    fireEvent.click(await screen.findByRole("button", { name: "Retry unchanged command" }));
    await waitFor(() => expect(screen.queryByRole("button", { name: "Retry unchanged command" })).not.toBeInTheDocument());
    expect(bodies).toHaveLength(2); expect(bodies[0]).toBe(bodies[1]); expect(JSON.parse(bodies[0]).expected_plan_digest).toBe(prepared.plan_digest);
    expect(screen.getByRole("region", { name: "Native operation" })).toHaveTextContent("Reviewed");
  });
});
