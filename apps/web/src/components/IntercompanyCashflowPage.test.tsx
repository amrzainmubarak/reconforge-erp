import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { BrowserSessionProvider, useBrowserSession } from "../browserSession";
import { cashflowTranslate } from "../intercompany-cashflow-i18n";
import { cashflowFixture } from "../intercompany-cashflow-test-fixture";
import IntercompanyCashflowPage from "./IntercompanyCashflowPage";

const response = (value: unknown) => new Response(JSON.stringify(value), { headers: { "Content-Type": "application/json" } });
function SessionControl({ tenant }: { tenant: string }) { const auth = useBrowserSession(); return <><button onClick={() => auth.begin({ tenantId: tenant, csrfToken: "csrf", expiresAt: "2099-01-01" }, "reader", auth.revision)}>Begin</button><button onClick={() => auth.clear(auth.revision)}>Clear session</button></>; }
type Fixture = Awaited<ReturnType<typeof cashflowFixture>>;
function mount(f: Fixture) { render(<BrowserSessionProvider><SessionControl tenant={f.tenant} /><IntercompanyCashflowPage locale="en" /></BrowserSessionProvider>); fireEvent.click(screen.getByRole("button", { name: "Begin" })); }
async function select(f: Fixture) { const apply = screen.getByRole("button", { name: "Apply organization scope" }); await waitFor(() => expect(apply).toBeEnabled()); fireEvent.click(apply); await screen.findByRole("option", { name: new RegExp(f.detail.id) }); fireEvent.change(screen.getByLabelText("Original paired trade"), { target: { value: f.detail.id } }); await screen.findByLabelText(cashflowTranslate("en", "opening")); }
function install(f: Fixture, override?: (path: string) => Promise<Response | undefined>) {
  const calls: { path: string; init?: RequestInit }[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    const path = String(url); calls.push({ path, init });
    const custom = await override?.(path); if (custom) return custom;
    if (path.endsWith("/auth/me")) return response({ id: "reader", principal_type: "user", permissions: ["intercompany_fx.read", "finance_core.read"], authorized_scopes: { workspaces: [f.scope.workspace_id], organizations: [f.scope.organization_id], legal_entities: ["seller", "buyer", "group"] } });
    if (path.includes("/sources?after=")) return response({ sources: { items: [{ id: f.detail.id, reference: f.detail.request.reference }], next_cursor: null } });
    if (path.includes("/intercompany-source-cashflow/") && path.includes("/evidence/export?")) return new Response(f.bytes, { headers: { "Content-Type": "application/json", "Content-Length": String(f.bytes.length), "X-ReconForge-Evidence-SHA256": f.view.evidence_sha256 } });
    if (path.includes("/intercompany-source-cashflow/")) return response(f.view);
    if (path.endsWith("/report")) return response({ report: f.report });
    if (path.includes("/plans/")) { const stage = f.stages.find(row => path.includes(row.plan.id)); if (!stage) throw new Error("unobserved_plan"); return response({ evidence: stage }); }
    return response({ source: f.detail });
  }));
  return calls;
}
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });
describe("source cashflow governed read Studio", () => {
  it.each(["en", "ar"] as const)("has accessible login, scope and source limitations in %s", locale => { render(<BrowserSessionProvider><IntercompanyCashflowPage locale={locale} /></BrowserSessionProvider>); expect(screen.getByRole("main")).toHaveAttribute("dir", locale === "ar" ? "rtl" : "ltr"); expect(screen.getByRole("form", { name: cashflowTranslate(locale, "login") })).toBeInTheDocument(); expect(screen.getByLabelText(cashflowTranslate(locale, "password"))).toHaveAttribute("type", "password"); expect(screen.getByText(cashflowTranslate(locale, "coverage"))).toBeInTheDocument(); });
  it("requires explicit source opening, verifies every native seal and downloads exact scoped bytes", async () => {
    const f = await cashflowFixture(), calls = install(f); mount(f); await select(f);
    expect(screen.getByRole("button", { name: "Verify source cashflow" })).toBeDisabled(); expect(calls.some(call => call.path.includes("/intercompany-source-cashflow/"))).toBe(false);
    fireEvent.click(screen.getByLabelText(cashflowTranslate("en", "opening"))); fireEvent.click(screen.getByRole("button", { name: "Verify source cashflow" }));
    await screen.findByRole("heading", { name: "Source cash reconciliation" }); expect(screen.getAllByText("1.01 USD").length).toBeGreaterThanOrEqual(2);
    const create = vi.fn((_blob: Blob) => "blob:original-cashflow"), click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {}); Object.defineProperty(URL, "createObjectURL", { configurable: true, value: create }); Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: vi.fn() });
    fireEvent.click(screen.getByRole("button", { name: "Download unchanged original bytes" })); await screen.findByText("Original raw bytes verified and downloaded");
    expect(click).toHaveBeenCalledOnce(); const blob = create.mock.calls[0][0] as Blob; expect(Array.from(new Uint8Array(await blob.arrayBuffer()))).toEqual(Array.from(f.bytes));
    const requests = calls.filter(call => call.path.includes("/intercompany-source-cashflow/")); expect(requests).toHaveLength(2); expect(requests.every(call => call.init?.method === "GET" && !call.init.body)).toBe(true);
    expect((requests[0].init?.headers as Record<string, string>)["X-ReconForge-Tenant"]).toBe(f.tenant); expect((requests[0].init?.headers as Record<string, string>)["X-ReconForge-Legal-Entity"]).toBeUndefined();
  });
  it.each(["scope", "session"])("discards a late verified view after %s changes", async change => {
    const f = await cashflowFixture(); let release!: (value: Response) => void, waiting = false;
    install(f, async path => { if (path.includes("/intercompany-source-cashflow/")) { waiting = true; return new Promise(resolve => { release = resolve; }); } });
    mount(f); await select(f); fireEvent.click(screen.getByLabelText(cashflowTranslate("en", "opening"))); fireEvent.click(screen.getByRole("button", { name: "Verify source cashflow" })); await waitFor(() => expect(waiting).toBe(true));
    if (change === "scope") fireEvent.change(screen.getByLabelText("Workspace"), { target: { value: "different-workspace" } }); else fireEvent.click(screen.getByRole("button", { name: "Clear session" }));
    await act(async () => { release(response(f.view)); });
    expect(screen.queryByRole("heading", { name: "Source cash reconciliation" })).not.toBeInTheDocument(); expect(screen.queryByRole("button", { name: "Download unchanged original bytes" })).not.toBeInTheDocument();
  });
  it("refuses a returned view for another tenant before presenting any amounts", async () => {
    const f = await cashflowFixture(); install(f, async path => path.includes("/intercompany-source-cashflow/") ? response({ ...f.view, qualified_scope: { ...f.view.qualified_scope, tenant_id: "foreign" } }) : undefined);
    mount(f); await select(f); fireEvent.click(screen.getByLabelText(cashflowTranslate("en", "opening"))); fireEvent.click(screen.getByRole("button", { name: "Verify source cashflow" })); await screen.findByRole("alert");
    expect(screen.queryByRole("heading", { name: "Source cash reconciliation" })).not.toBeInTheDocument();
  });
  it("binds source detail to its original source proof before opening selection", async () => {
    const f = await cashflowFixture(); install(f, async path => path.endsWith(f.detail.id) ? response({ source: { ...f.detail, request: { ...f.detail.request, reference: "Forged retained identity" } } }) : undefined);
    mount(f); const apply = screen.getByRole("button", { name: "Apply organization scope" }); await waitFor(() => expect(apply).toBeEnabled()); fireEvent.click(apply); await screen.findByRole("option", { name: new RegExp(f.detail.id) }); fireEvent.change(screen.getByLabelText("Original paired trade"), { target: { value: f.detail.id } }); await screen.findByRole("alert"); expect(screen.queryByLabelText(cashflowTranslate("en", "opening"))).not.toBeInTheDocument();
  });
  it("clears the source and verified values on current authority refusal", async () => {
    const f = await cashflowFixture(); install(f, async path => path.includes("/intercompany-source-cashflow/") ? new Response("{}", { status: 403 }) : undefined);
    mount(f); await select(f); fireEvent.click(screen.getByLabelText(cashflowTranslate("en", "opening"))); fireEvent.click(screen.getByRole("button", { name: "Verify source cashflow" })); await screen.findByRole("alert"); expect(screen.queryByLabelText(cashflowTranslate("en", "opening"))).not.toBeInTheDocument();
  });
});
