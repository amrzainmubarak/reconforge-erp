import { act, fireEvent, render as renderView, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { BrowserSessionProvider, useBrowserSession } from "../browserSession";
import ConsolidatedStatementsPage from "./ConsolidatedStatementsPage";

function Controls() {
  const auth = useBrowserSession();
  return <><button onClick={() => auth.begin({ tenantId: "tenant-test", csrfToken: "synthetic-csrf", expiresAt: "2099-01-01T00:00:00Z" }, "reviewer", auth.revision)}>Sign in test</button><button onClick={() => auth.clear(auth.revision)}>Sign out test</button></>;
}
function mount(locale: "en" | "ar" = "en") { return renderView(<><Controls /><ConsolidatedStatementsPage locale={locale} /></>, { wrapper: BrowserSessionProvider }); }
async function signIn() { await act(async () => fireEvent.click(screen.getByRole("button", { name: "Sign in test" }))); }
const digest = "a".repeat(64);
const run = { id: "actual-statement-run", period_id: "FY2026", reporting_currency: "JPY", prepared_by: "actual-reviewer", created_at: "2026-10-25T10:00:00Z", report_digest: digest,
  statements: { balance_sheet: { total_assets_minor: 100, total_liabilities_minor: 40, equity: { total_equity_minor: 60 } }, income_statement: { consolidated_net_profit_minor: -7 } } };
function respond(value: unknown = { total_count: 1, runs: [run] }) { const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify(value))); vi.stubGlobal("fetch", fetcher); return fetcher; }
beforeEach(() => vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Offline"))));
afterEach(() => vi.unstubAllGlobals());

describe("ConsolidatedStatementsPage source assurance", () => {
  it("does not invent statements or request data without a browser session", () => {
    mount();
    expect(fetch).not.toHaveBeenCalled();
    expect(screen.queryByText("$4,250,000")).not.toBeInTheDocument();
    expect(screen.queryByText("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855")).not.toBeInTheDocument();
    expect(screen.getByText("Sign in to an authorized workspace to read stored statements.")).toBeInTheDocument();
  });
  it("disables generation until real source balances can be selected", async () => {
    const fetcher = respond(); mount(); await signIn();
    const button = screen.getByRole("button", { name: "Generate Statements" });
    expect(button).toBeDisabled(); fireEvent.click(button);
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(fetcher.mock.calls[0][1].method).toBeUndefined();
    expect(screen.getByText(/real source balances and a currency policy/)).toBeInTheDocument();
  });
  it("reads actual backend field names and displays exact minor units without assuming cents", async () => {
    const fetcher = respond(); mount(); await signIn();
    expect(screen.getByText("100 JPY")).toBeInTheDocument();
    expect(screen.getByText("60 JPY")).toBeInTheDocument();
    expect(screen.getByText("-7 JPY")).toBeInTheDocument();
    expect(screen.getByText(digest)).toBeInTheDocument();
    expect(fetcher.mock.calls[0][1]).toMatchObject({ credentials: "same-origin", cache: "no-store", headers: { "X-ReconForge-Tenant": "tenant-test" } });
    expect(screen.queryByText(/\$/)).not.toBeInTheDocument();
  });
  it.each([401, 403, 503])("clears figures on HTTP%s without exposing server error content", async status => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("Sensitive diagnostic", { status })));
    mount(); await signIn();
    expect(screen.getByRole("alert")).toHaveTextContent("Valid statement runs could not be loaded");
    expect(screen.queryByText("100 JPY")).not.toBeInTheDocument();
    expect(screen.queryByText("$4,250,000")).not.toBeInTheDocument();
    expect(screen.queryByText("Sensitive diagnostic")).not.toBeInTheDocument();
  });
  it.each([
    ["missing result", null],
    ["missing income", { total_count: 1, runs: [{ ...run, statements: { balance_sheet: run.statements.balance_sheet } }] }],
    ["unsafe amount", { total_count: 1, runs: [{ ...run, statements: { ...run.statements, balance_sheet: { ...run.statements.balance_sheet, total_assets_minor: Number.MAX_SAFE_INTEGER + 1 } } }] }],
    ["imbalance", { total_count: 1, runs: [{ ...run, statements: { ...run.statements, balance_sheet: { ...run.statements.balance_sheet, total_assets_minor: 101 } } }] }],
    ["duplicate run", { total_count: 2, runs: [run, run] }],
  ])("fails closed for malformed server results: %s", async (_label, value) => {
    respond(value); mount(); await signIn();
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.queryByText("100 JPY")).not.toBeInTheDocument();
    expect(screen.queryByText(digest)).not.toBeInTheDocument();
  });
  it("renders server empty result without a fake financial posture", async () => {
    respond({ total_count: 0, runs: [] }); mount(); await signIn();
    expect(screen.getByText("No stored statement runs were returned.")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Consolidated Financial Posture" })).not.toBeInTheDocument();
  });
  it("clears financial figures before refresh and after session revocation", async () => {
    const fetcher = respond(); mount(); await signIn();
    expect(screen.getByText("100 JPY")).toBeInTheDocument();
    fetcher.mockRejectedValue(new TypeError("Offline"));
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Refresh" })));
    expect(screen.queryByText("100 JPY")).not.toBeInTheDocument();
    respond(); await act(async () => fireEvent.click(screen.getByRole("button", { name: "Refresh" })));
    expect(screen.getByText("100 JPY")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Sign out test" }));
    expect(screen.queryByText("100 JPY")).not.toBeInTheDocument();
  });
  it("renders Arabic errors and RTL without invented metrics", async () => {
    const view = mount("ar"); await signIn();
    expect(view.container.querySelector(".reporting-workspace")).toHaveAttribute("dir", "rtl");
    expect(screen.getByRole("alert")).toHaveTextContent("تعذر تحميل قوائم صالحة");
  });
});

