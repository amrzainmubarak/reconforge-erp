import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { BrowserSessionProvider, useBrowserSession } from "../browserSession";
import { groupTranslate } from "../group-diagnostic-i18n";
import { groupFixture } from "../group-diagnostic-test-fixture";
import GroupDiagnosticPage from "./GroupDiagnosticPage";

const response = (value: unknown) => new Response(JSON.stringify(value), { headers: { "Content-Type": "application/json" } });
type Fixture = Awaited<ReturnType<typeof groupFixture>>;
function SessionControl({ tenant }: { tenant: string }) { const auth = useBrowserSession(); return <><button onClick={() => auth.begin({ tenantId: tenant, csrfToken: "csrf", expiresAt: "2099-01-01" }, "reader", auth.revision)}>Begin</button><button onClick={() => auth.clear(auth.revision)}>Clear session</button></>; }
function mount(f: Fixture) { render(<BrowserSessionProvider><SessionControl tenant={f.tenant} /><GroupDiagnosticPage locale="en" /></BrowserSessionProvider>); fireEvent.click(screen.getByRole("button", { name: "Begin" })); }
function install(f: Fixture, override?: (path: string) => Promise<Response | undefined>) {
  const calls: { path: string; init?: RequestInit }[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    const path = String(url); calls.push({ path, init }); const custom = await override?.(path); if (custom) return custom;
    if (path.endsWith("/auth/me")) return response({ id: "reader", principal_type: "user", permissions: ["intercompany_fx.read", "finance_core.read"], authorized_scopes: { workspaces: [f.scope.workspace_id], organizations: [f.scope.organization_id], legal_entities: ["seller", "buyer", "group"] } });
    if (path.includes("/sources?after=")) return response({ sources: { items: f.sources.map(row => ({ id: row.detail.id, reference: row.detail.request.reference })), next_cursor: null } });
    if (path.includes("/intercompany-group-diagnostic/evidence?")) return new Response(f.bytes, { headers: { "Content-Type": "application/json", "Content-Length": String(f.bytes.length), "X-ReconForge-Evidence-SHA256": f.view.evidence_sha256 } });
    if (path.includes("/intercompany-group-diagnostic/report?")) return response(f.view);
    const selected = f.sources.find(row => path.includes(row.detail.id) || row.stages.some(stage => path.includes(stage.plan.id)));
    if (!selected) throw new Error("unknown_original_request");
    if (path.includes("/intercompany-source-cashflow/")) return response(selected.cashflowView);
    if (path.endsWith("/report")) return response({ report: selected.report });
    if (path.includes("/plans/")) return response({ evidence: selected.stages.find(stage => path.includes(stage.plan.id)) });
    return response({ source: selected.detail });
  })); return calls;
}
async function selectTwo(f: Fixture) {
  const apply = screen.getByRole("button", { name: "Apply organization scope" }); await waitFor(() => expect(apply).toBeEnabled()); fireEvent.click(apply); await screen.findByRole("option", { name: new RegExp(f.sources[0].detail.id) });
  for (const [index, row] of f.sources.entries()) { fireEvent.change(screen.getByLabelText("Original paired trade"), { target: { value: row.detail.id } }); const add = screen.getByRole("button", { name: "Capture and add original source" }); expect(add).toBeDisabled(); fireEvent.click(screen.getByLabelText(groupTranslate("en", "opening"))); fireEvent.click(add); await screen.findByRole("heading", { name: `Selected original sources · ${index + 1}/16` }); }
}
async function verify(f: Fixture) { await selectTwo(f); fireEvent.click(screen.getByRole("button", { name: "Verify selected group membership" })); await screen.findByRole("heading", { name: "Reporting and native adjustment bridge" }); }
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });
describe("group diagnostic original read Studio", () => {
  it.each(["en", "ar"] as const)("provides explicit read-only accessible scope and limitations in %s", locale => { render(<BrowserSessionProvider><GroupDiagnosticPage locale={locale} /></BrowserSessionProvider>); expect(screen.getByRole("main")).toHaveAttribute("dir", locale === "ar" ? "rtl" : "ltr"); expect(screen.getByRole("form", { name: groupTranslate(locale, "login") })).toBeInTheDocument(); expect(screen.getByText(groupTranslate(locale, "coverage"))).toBeInTheDocument(); });
  it("selects two explicit known openings, binds every native original and downloads byte-exact evidence", async () => {
    const f = await groupFixture(), calls = install(f); mount(f); await verify(f);
    expect(screen.getByRole("region", { name: "Reporting and native adjustment bridge" })).toHaveAttribute("tabIndex", "0");
    expect(screen.getByRole("heading", { name: "Observed native fiscal periods" })).toBeInTheDocument(); expect(screen.getByText(groupTranslate("en", "observed"))).toBeInTheDocument();
    const cash = screen.getByRole("rowheader", { name: /^cash$/ }).closest("tr")!; expect(cash).toHaveTextContent("2.02 USD"); expect(cash).toHaveTextContent("0.00 USD");
    expect(screen.queryByRole("button", { name: /Post|Close period|Change permission/ })).not.toBeInTheDocument();
    const create = vi.fn((_blob: Blob) => "blob:group-original"), click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {}); Object.defineProperty(URL, "createObjectURL", { configurable: true, value: create }); Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: vi.fn() });
    fireEvent.click(screen.getByRole("button", { name: "Download unchanged original bytes" })); await screen.findByText("Original raw bytes verified and downloaded");
    expect(click).toHaveBeenCalledOnce(); expect(Array.from(new Uint8Array(await create.mock.calls[0][0].arrayBuffer()))).toEqual(Array.from(f.bytes));
    expect(calls.every(row => row.init?.method === "GET" && !row.init?.body)).toBe(true);
    const request = calls.find(row => row.path.includes("/intercompany-group-diagnostic/report?"))!; const selected = JSON.parse(new URL(request.path, "https://localhost").searchParams.get("selection")!); expect(selected.pins).toHaveLength(2); expect(selected.pins.every((pin: { opening: { seller_minor: number; buyer_minor: number } }) => pin.opening.seller_minor === 0 && pin.opening.buyer_minor === 0)).toBe(true);
  });
  it.each(["scope", "session"])("drops late group money after %s changes", async change => {
    const f = await groupFixture(); let release!: (value: Response) => void, waiting = false;
    install(f, async path => { if (path.includes("/intercompany-group-diagnostic/report?")) { waiting = true; return new Promise(resolve => { release = resolve; }); } }); mount(f); await selectTwo(f); fireEvent.click(screen.getByRole("button", { name: "Verify selected group membership" })); await waitFor(() => expect(waiting).toBe(true));
    if (change === "scope") fireEvent.change(screen.getByLabelText("Workspace"), { target: { value: "foreign" } }); else fireEvent.click(screen.getByRole("button", { name: "Clear session" }));
    await act(async () => { release(response(f.view)); }); expect(screen.queryByRole("heading", { name: "Reporting and native adjustment bridge" })).not.toBeInTheDocument(); expect(screen.queryByRole("button", { name: "Download unchanged original bytes" })).not.toBeInTheDocument();
  });
  it("clears previous verified money and selected sources on current denied export", async () => {
    const f = await groupFixture(); install(f, async path => path.includes("/intercompany-group-diagnostic/evidence?") ? new Response("{}", { status: 403 }) : undefined); mount(f); await verify(f);
    fireEvent.click(screen.getByRole("button", { name: "Download unchanged original bytes" })); await screen.findByRole("alert"); expect(screen.queryByRole("heading", { name: "Reporting and native adjustment bridge" })).not.toBeInTheDocument(); expect(screen.queryByRole("button", { name: "Download unchanged original bytes" })).not.toBeInTheDocument(); expect(screen.getByRole("heading", { name: "Selected original sources · 0/16" })).toBeInTheDocument();
  });
  it.each(["scope", "session"])("never downloads stale original bytes after %s changes", async change => {
    const f = await groupFixture(); let release!: (value: Response) => void, waiting = false;
    install(f, async path => { if (path.includes("/intercompany-group-diagnostic/evidence?")) { waiting = true; return new Promise(resolve => { release = resolve; }); } }); mount(f); await verify(f);
    const create = vi.fn((_blob: Blob) => "blob:stale-group-original"), click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    Object.defineProperty(URL, "createObjectURL", { configurable: true, value: create }); Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: vi.fn() });
    fireEvent.click(screen.getByRole("button", { name: "Download unchanged original bytes" })); await waitFor(() => expect(waiting).toBe(true));
    if (change === "scope") fireEvent.change(screen.getByLabelText("Workspace"), { target: { value: "foreign" } }); else fireEvent.click(screen.getByRole("button", { name: "Clear session" }));
    await act(async () => { release(new Response(f.bytes, { headers: { "Content-Type": "application/json", "Content-Length": String(f.bytes.length), "X-ReconForge-Evidence-SHA256": f.view.evidence_sha256 } })); });
    expect(create).not.toHaveBeenCalled(); expect(click).not.toHaveBeenCalled(); expect(screen.queryByText("Original raw bytes verified and downloaded")).not.toBeInTheDocument(); expect(screen.queryByRole("heading", { name: "Reporting and native adjustment bridge" })).not.toBeInTheDocument();
  });
  it("invalidates the verified bridge when a selected original is removed", async () => {
    const f = await groupFixture(); install(f); mount(f); await verify(f); fireEvent.click(screen.getAllByRole("button", { name: "Remove selected source" })[0]); expect(screen.queryByRole("heading", { name: "Reporting and native adjustment bridge" })).not.toBeInTheDocument(); expect(screen.getByRole("heading", { name: "Selected original sources · 1/16" })).toBeInTheDocument();
  });
});
