import { act, fireEvent, render as renderView, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { BrowserSessionProvider, useBrowserSession } from "../browserSession";
import ShopFloorTraceabilityPage from "./ShopFloorTraceabilityPage";
function Controls() { const auth = useBrowserSession(); return <><button onClick={() => auth.begin({ tenantId: "tenant-test", csrfToken: "synthetic", expiresAt: "2099-01-01T00:00:00Z" }, "operator", auth.revision)}>Sign in test</button><button onClick={() => auth.clear(auth.revision)}>Sign out test</button></>; }
function mount(locale: "en" | "ar" = "en") { return renderView(<><Controls /><ShopFloorTraceabilityPage locale={locale} /></>, { wrapper: BrowserSessionProvider }); }
function signIn() { fireEvent.click(screen.getByRole("button", { name: "Sign in test" })); }
const tree = { lot_id: "LOT-REAL", item_id: "ITEM-REAL", direction: "backward", children: [{ lot_id: "LOT-COMPONENT", item_id: "ITEM-COMPONENT", direction: "backward", children: [] }] };
function respond(value: unknown = { root_lot_id: "LOT-REAL", genealogy: tree }) { const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify(value))); vi.stubGlobal("fetch", fetcher); return fetcher; }
async function trace(lot = "LOT-REAL", label = "Trace Genealogy") { fireEvent.change(screen.getByRole("textbox"), { target: { value: lot } }); await act(async () => fireEvent.click(screen.getByRole("button", { name: label }))); }
beforeEach(() => vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Offline"))));
afterEach(() => vi.unstubAllGlobals());

describe("ShopFloorTraceabilityPage source assurance", () => {
  it("does not display invented initial genealogy or completed operation records", () => {
    mount(); expect(fetch).not.toHaveBeenCalled();
    expect(screen.queryByText("LOT_RAW_CHIP_901")).not.toBeInTheDocument();
    expect(screen.queryByText("TECH_ALICE")).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Lot Genealogy Visual Tree" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Trace Genealogy" })).toBeDisabled();
  });
  it.each([401, 403, 503])("does not assert local verification after HTTP%s", async status => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("Private diagnostic", { status })));
    mount(); signIn(); await trace();
    expect(screen.queryByText("Displaying locally verified lot genealogy")).not.toBeInTheDocument();
    expect(screen.queryByText("LOT_RAW_CHIP_901")).not.toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("Valid genealogy could not be retrieved");
    expect(screen.queryByText("Private diagnostic")).not.toBeInTheDocument();
  });
  it("uses the actual directional API route, response envelope and current tenant", async () => {
    const fetcher = respond(); mount(); signIn(); await trace();
    expect(fetcher.mock.calls[0][0]).toBe("/api/v1/manufacturing/traceability/genealogy/backward/LOT-REAL");
    expect(fetcher.mock.calls[0][1]).toMatchObject({ credentials: "same-origin", cache: "no-store", headers: { "X-ReconForge-Tenant": "tenant-test" } });
    expect(screen.getByText("LOT-COMPONENT")).toBeInTheDocument();
    expect(screen.getByText("Genealogy returned by the server.")).toBeInTheDocument();
    expect(screen.queryByText("TECH_ALICE")).not.toBeInTheDocument();
  });
  it("binds a forward trace to the requested root and direction", async () => {
    respond({ root_lot_id: "LOT-REAL", genealogy: { ...tree, direction: "forward", children: [] } });
    mount(); signIn(); fireEvent.change(screen.getByRole("combobox"), { target: { value: "forward" } }); await trace();
    expect(vi.mocked(fetch).mock.calls[0][0]).toBe("/api/v1/manufacturing/traceability/genealogy/forward/LOT-REAL");
    expect(screen.getByRole("heading", { name: "Lot Genealogy Visual Tree" })).toBeInTheDocument();
  });
  it.each([
    ["missing data", null],
    ["wrong root envelope", { root_lot_id: "OTHER", genealogy: tree }],
    ["wrong tree root", { root_lot_id: "LOT-REAL", genealogy: { ...tree, lot_id: "OTHER" } }],
    ["wrong direction", { root_lot_id: "LOT-REAL", genealogy: { ...tree, direction: "forward" } }],
    ["missing children", { root_lot_id: "LOT-REAL", genealogy: { ...tree, children: undefined } }],
    ["ancestor cycle", { root_lot_id: "LOT-REAL", genealogy: { ...tree, children: [tree] } }],
    ["too many nodes", { root_lot_id: "LOT-REAL", genealogy: { ...tree, children: Array.from({ length: 1001 }, (_value, index) => ({ ...tree, lot_id: `CHILD-${index}`, children: [] })) } }],
  ])("rejects malformed server genealogy: %s", async (_label, value) => {
    respond(value); mount(); signIn(); await trace();
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Lot Genealogy Visual Tree" })).not.toBeInTheDocument();
  });
  it("rejects an excessively deep genealogy tree", async () => {
    let deep = { ...tree, children: [] };
    for (let index = 15; index > 0; index--) deep = { ...tree, lot_id: `CHILD-${index}`, children: [deep] } as typeof deep;
    respond({ root_lot_id: "LOT-REAL", genealogy: { ...tree, children: [deep] } });
    mount(); signIn(); await trace(); expect(screen.getByRole("alert")).toBeInTheDocument();
  });
  it("clears prior genealogy when the selected lot or direction changes", async () => {
    respond(); mount(); signIn(); await trace(); expect(screen.getByText("LOT-COMPONENT")).toBeInTheDocument();
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "forward" } });
    expect(screen.queryByText("LOT-COMPONENT")).not.toBeInTheDocument();
  });
  it("rejects a late response from a revoked browser session", async () => {
    let finish: ((value: Response) => void) | undefined;
    vi.stubGlobal("fetch", vi.fn().mockImplementation(() => new Promise<Response>(resolve => { finish = resolve; })));
    mount(); signIn(); await trace();
    fireEvent.click(screen.getByRole("button", { name: "Sign out test" }));
    await act(async () => finish!(new Response(JSON.stringify({ root_lot_id: "LOT-REAL", genealogy: tree }))));
    expect(screen.queryByText("LOT-COMPONENT")).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Lot Genealogy Visual Tree" })).not.toBeInTheDocument();
  });
  it("rejects a late response after an input change even when transport ignores abort", async () => {
    let finish: ((value: Response) => void) | undefined;
    vi.stubGlobal("fetch", vi.fn().mockImplementation(() => new Promise<Response>(resolve => { finish = resolve; })));
    mount(); signIn(); await trace();
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "NEW-LOT" } });
    await act(async () => finish!(new Response(JSON.stringify({ root_lot_id: "LOT-REAL", genealogy: tree }))));
    expect(screen.queryByText("LOT-COMPONENT")).not.toBeInTheDocument();
  });
  it("shows actionable Arabic network errors in RTL", async () => {
    const view = mount("ar"); signIn(); await trace("LOT-REAL", "تتبع الشجرة الجينية");
    expect(view.container.querySelector(".reporting-workspace")).toHaveAttribute("dir", "rtl");
    expect(screen.getByRole("alert")).toHaveTextContent("تعذر استرجاع شجرة صالحة");
  });
});
