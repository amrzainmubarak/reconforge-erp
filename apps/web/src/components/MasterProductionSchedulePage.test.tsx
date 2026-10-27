import { act, fireEvent, render as renderView, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { BrowserSessionProvider, useBrowserSession } from "../browserSession";
import MasterProductionSchedulePage from "./MasterProductionSchedulePage";
function Controls() { const auth = useBrowserSession(); return <><button onClick={() => auth.begin({ tenantId: "tenant-test", csrfToken: "synthetic", expiresAt: "2099-01-01T00:00:00Z" }, "planner", auth.revision)}>Sign in test</button><button onClick={() => auth.clear(auth.revision)}>Sign out test</button></>; }
function mount(locale: "en" | "ar" = "en") { return renderView(<><Controls /><MasterProductionSchedulePage locale={locale} /></>, { wrapper: BrowserSessionProvider }); }
async function signIn() { await act(async () => fireEvent.click(screen.getByRole("button", { name: "Sign in test" }))); }
const digest = "b".repeat(64);
const metadata = { id: "mps-stored", plan_id: "PLAN-REAL", revision: "r2", item_id: "ITEM-REAL", unit_of_measure: "EA", plan_digest: digest };
const plan = { ...metadata, quantity_scale: 1000, safety_stock_scaled: 0, lot_size_multiple_scaled: 10, opening_inventory_scaled: 0,
  schedule_rows: [{ bucket_index: 0, bucket_start_date: "2026-11-01", bucket_end_date: "2026-11-07", sales_orders_scaled: 20, forecast_demand_scaled: 10, net_demand_scaled: 20, scheduled_receipts_scaled: 0, planned_production_scaled: 30, projected_inventory_scaled: 10, available_to_promise_scaled: 10, shortage_scaled: 20 }],
  sourcing_requisitions: [{ requisition_id: "REQ-REAL", plan_id: metadata.plan_id, plan_revision: metadata.revision, item_id: metadata.item_id, bucket_index: 0, required_date: "2026-11-01", shortage_quantity_scaled: 20, order_quantity_scaled: 30, preferred_supplier_id: "SUP-REAL", unit_price_ceiling_minor: 100, currency: "JPY" }] };
const record = { ...metadata, plan };
function respond(value: unknown = { total_count: 1, plans: [record] }) { const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify(value))); vi.stubGlobal("fetch", fetcher); return fetcher; }
beforeEach(() => vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Offline"))));
afterEach(() => vi.unstubAllGlobals());

describe("MasterProductionSchedulePage source assurance", () => {
  it("does not invent plans or requisitions without a session", () => {
    mount(); expect(fetch).not.toHaveBeenCalled();
    expect(screen.queryByText("PR_MPS_2026_Q4_B0")).not.toBeInTheDocument();
    expect(screen.queryByText("d7a8fbb307d7809469ca9abcb0082e4f8d5651e46d3cdb762d02d0bf37c9e592")).not.toBeInTheDocument();
  });
  it("disables source-less computation and never posts sample demand or supplier details", async () => {
    const fetcher = respond(); mount(); await signIn();
    const button = screen.getByRole("button", { name: "Compute MPS Schedule" });
    expect(button).toBeDisabled(); fireEvent.click(button);
    expect(fetcher).toHaveBeenCalledTimes(1); expect(fetcher.mock.calls[0][1].method).toBeUndefined();
    expect(screen.getByText(/real demand, inventory, supplier and currency inputs/)).toBeInTheDocument();
  });
  it("reads the actual nested backend plan and does not invent procurement approval or cents", async () => {
    const fetcher = respond(); mount(); await signIn();
    expect(screen.getByText("REQ-REAL")).toBeInTheDocument();
    expect(screen.getByText("100 JPY")).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Projected Inventory" })).toBeInTheDocument();
    expect(screen.getByText(digest)).toBeInTheDocument();
    expect(screen.queryByText("APPROVED")).not.toBeInTheDocument();
    expect(screen.queryByText(/\$/)).not.toBeInTheDocument();
    expect(fetcher.mock.calls[0][1]).toMatchObject({ credentials: "same-origin", cache: "no-store", headers: { "X-ReconForge-Tenant": "tenant-test" } });
  });
  it.each([401, 403, 503])("fails closed on HTTP%s without inventing a stored plan", async status => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("Private diagnostic", { status })));
    mount(); await signIn(); expect(screen.getByRole("alert")).toHaveTextContent("Valid production plans could not be loaded");
    expect(screen.queryByText("PR_MPS_2026_Q4_B0")).not.toBeInTheDocument();
    expect(screen.queryByText("Private diagnostic")).not.toBeInTheDocument();
  });
  it.each([
    ["missing list", null],
    ["missing nested plan", { total_count: 1, plans: [metadata] }],
    ["wrong plan binding", { total_count: 1, plans: [{ ...record, plan: { ...plan, plan_id: "DIFFERENT" } }] }],
    ["unsafe quantity", { total_count: 1, plans: [{ ...record, plan: { ...plan, quantity_scale: Number.MAX_SAFE_INTEGER + 1 } }] }],
    ["unsafe money", { total_count: 1, plans: [{ ...record, plan: { ...plan, sourcing_requisitions: [{ ...plan.sourcing_requisitions[0], unit_price_ceiling_minor: Number.MAX_SAFE_INTEGER + 1 }] } }] }],
    ["unbound requisition bucket", { total_count: 1, plans: [{ ...record, plan: { ...plan, sourcing_requisitions: [{ ...plan.sourcing_requisitions[0], bucket_index: 100 }] } }] }],
  ])("rejects invalid successful result: %s", async (_label, value) => {
    respond(value); mount(); await signIn(); expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.queryByText("REQ-REAL")).not.toBeInTheDocument(); expect(screen.queryByText(digest)).not.toBeInTheDocument();
  });
  it("displays genuine empty state and Arabic RTL errors", async () => {
    respond({ total_count: 0, plans: [] }); const view = mount(); await signIn();
    expect(screen.getByText("No stored production plans were returned.")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "MPS Plan & Procurement Summary" })).not.toBeInTheDocument();
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Offline")));
    view.rerender(<><Controls /><MasterProductionSchedulePage locale="ar" /></>);
    await act(async () => {});
    expect(view.container.querySelector(".reporting-workspace")).toHaveAttribute("dir", "rtl");
    expect(screen.getByRole("alert")).toHaveTextContent("تعذر تحميل خطط صالحة");
  });
  it("removes prior requisitions after refresh failure or authority revocation", async () => {
    const fetcher = respond(); mount(); await signIn(); expect(screen.getByText("REQ-REAL")).toBeInTheDocument();
    fetcher.mockRejectedValue(new TypeError("Offline")); await act(async () => fireEvent.click(screen.getByRole("button", { name: "Refresh" })));
    expect(screen.queryByText("REQ-REAL")).not.toBeInTheDocument();
    respond(); await act(async () => fireEvent.click(screen.getByRole("button", { name: "Refresh" })));
    expect(screen.getByText("REQ-REAL")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Sign out test" })); expect(screen.queryByText("REQ-REAL")).not.toBeInTheDocument();
  });
});
