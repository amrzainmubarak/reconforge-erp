import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import source from "../monetary-test-fixtures.json";
import fixture from "../monetary-valuation-test-fixture.json";
import { parseMonetaryStock, type MonetaryStockOptions } from "../monetary-stock-data";
import { monetaryTranslate as text } from "../monetary-words";
import type { SalesIdentity } from "../sales-revenue-data";
import { MonetaryStockValuation } from "./MonetaryStockValuation";

const session = { tenantId: "synthetic", csrfToken: "csrf", expiresAt: "2099-01-01T00:00:00Z" };
const auth = { session, revision: 1, isCurrent: vi.fn(() => true), recover: vi.fn(() => false) };
vi.mock("../browserSession", () => ({ useBrowserSession: () => auth }));
const stock = parseMonetaryStock(source.stock, source.scope), onLock = vi.fn(), onChanged = vi.fn();
const identity: SalesIdentity = { id: "poster", human: true, stepUp: true, workspaces: ["work"], organizations: ["organization"], entities: ["entity"], permissions: ["sales.read", "inventory.read", "receivables.read", "finance_core.read", "finance_core.manage", "finance_core.validate", "finance_core.post", "finance_core.reverse", "receivables.manage", "receivables.approve"] };
const options: MonetaryStockOptions = { customers: [], periods: [{ id: "period", name: "October", start_date: "2026-10-01", end_date: "2026-10-31" }], journals: [], accounts: [{ account_code: "UGAIN", name: "Gain", account_type: "Income", chart_id: "chart" }, { account_code: "ULOSS", name: "Loss", account_type: "Expense", chart_id: "chart" }], items: [], warehouses: [], locations: [], policies: [] };
const reviewed = { ...fixture, phase: 1, status: "Reviewed", posted_actor_id: null, posting_effect_id: null };
const json = (plan: unknown, status = 200) => new Response(JSON.stringify(status === 200 ? { plan } : { error: { code: "forbidden", message: "Denied" } }), { status });
function view(id = identity) { return render(<MonetaryStockValuation locale="en" scope={source.scope} stock={stock} options={options} identity={id} externallyLocked={false} readOnly={false} onLockChange={onLock} onChanged={onChanged} />); }
async function load() {
  const form = screen.getByRole("form", { name: text("en", "loadValuation") });
  fireEvent.change(within(form).getByLabelText(text("en", "valuationId")), { target: { value: fixture.id } });
  fireEvent.click(within(form).getByRole("button"));
  await screen.findByRole("region", { name: text("en", "evidence") });
}
beforeEach(() => { onLock.mockReset(); onChanged.mockReset(); auth.revision = 1; auth.isCurrent.mockReturnValue(true); auth.recover.mockReturnValue(false); });
afterEach(() => vi.unstubAllGlobals());

it("keeps identity sources outside the FX workflow without any request or fabricated rate", () => {
  const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
  render(<MonetaryStockValuation locale="ar" scope={source.scope} stock={{ ...stock, transaction_policy: stock.functional_policy }} options={options} identity={identity} externallyLocked={false} readOnly={false} onLockChange={onLock} onChanged={onChanged} />);
  expect(screen.getByRole("region", { name: text("ar", "valuationTitle") })).toHaveAttribute("dir", "rtl");
  expect(screen.getByText(text("ar", "identityValuation"))).toBeInTheDocument();
  expect(screen.queryByRole("form")).not.toBeInTheDocument(); expect(fetcher).not.toHaveBeenCalled();
});

it("submits only a human closing observation and roles, without any client amount or source policy", async () => {
  const attempts: Record<string, unknown>[] = [];
  const prepared = { ...fixture, status: "Prepared", phase: 0, reviewer_actor_id: null, posted_actor_id: null, posting_effect_id: null };
  vi.stubGlobal("fetch", vi.fn(async (_url: RequestInfo | URL, init?: RequestInit) => { attempts.push(JSON.parse(String(init?.body))); return json(prepared); }));
  view();
  const form = screen.getByRole("form", { name: text("en", "prepareValuation") });
  for (const [key, value] of [["period_id", "period"], ["posting_date", fixture.posting_date], ["reason", fixture.reason], ["unrealized_gain_account_code", "UGAIN"], ["unrealized_loss_account_code", "ULOSS"], ["rate", fixture.closing_rate.rate], ["rateSource", fixture.closing_rate.source], ["effective_at", fixture.closing_rate.effective_at]] as const) fireEvent.change(within(form).getByLabelText(text("en", key)), { target: { value } });
  fireEvent.submit(form);
  await screen.findByRole("heading", { name: `${text("en", "revalue")} · ${text("en", "Prepared")}` });
  expect(Object.keys(attempts[0]).sort()).toEqual(["command_id", "closing_rate", "unrealized_gain_account_code", "unrealized_loss_account_code", "period_id", "posting_date", "reason"].sort());
  expect(attempts[0]).toMatchObject({ closing_rate: fixture.closing_rate, reason: fixture.reason });
  expect(onChanged).toHaveBeenCalledOnce(); expect(onLock).toHaveBeenLastCalledWith(false);
});

it.each(["maker", "checker"])("requires a third human to post a source-owned valuation: %s", async actor => {
  vi.stubGlobal("fetch", vi.fn(async () => json(reviewed))); view({ ...identity, id: actor }); await load();
  expect(screen.getByRole("button", { name: text("en", "postValuation") })).toBeDisabled();
});

it("retains exactly one command across a lost reply, blocks sibling actions and allows only explicit retry", async () => {
  const attempts: { path: string; body: string }[] = [];
  const fetcher = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    if (init?.method === "POST") { attempts.push({ path: String(url), body: String(init.body) }); if (attempts.length === 1) throw new TypeError("Lost reply"); return json(fixture); }
    return json(reviewed);
  }); vi.stubGlobal("fetch", fetcher); const rendered = view(); await load();
  const form = screen.getByRole("form", { name: text("en", "postValuation") });
  fireEvent.change(within(form).getByLabelText(text("en", "reason")), { target: { value: "Third-person audit intent" } }); fireEvent.submit(form);
  await screen.findByRole("button", { name: text("en", "retry") });
  expect(attempts).toHaveLength(1); expect(onLock).toHaveBeenLastCalledWith(true); expect(screen.getByRole("alert")).toHaveFocus();
  expect(screen.getByRole("button", { name: text("en", "loadValuation") })).toBeDisabled();
  expect(screen.getByRole("button", { name: text("en", "prepareValuation") })).toBeDisabled();
  const calls = fetcher.mock.calls.length;
  rendered.rerender(<MonetaryStockValuation locale="en" scope={source.scope} stock={stock} options={options} identity={{ ...identity, id: "another-human" }} externallyLocked={false} readOnly={false} onLockChange={onLock} onChanged={onChanged} />);
  expect(screen.getByRole("button", { name: text("en", "retry") })).toBeDisabled(); expect(fetcher).toHaveBeenCalledTimes(calls);
  rendered.rerender(<MonetaryStockValuation locale="ar" scope={source.scope} stock={stock} options={options} identity={identity} externallyLocked={false} readOnly={false} onLockChange={onLock} onChanged={onChanged} />);
  expect(fetcher).toHaveBeenCalledTimes(calls); fireEvent.click(screen.getByRole("button", { name: text("ar", "retry") }));
  await screen.findByRole("heading", { name: `${text("ar", "revalue")} · ${text("ar", "Posted")}` });
  expect(attempts[0]).toEqual(attempts[1]); expect(JSON.parse(attempts[1].body)).toMatchObject({ expected_plan_digest: fixture.plan_digest, reason: "Third-person audit intent" });
});

it("clears retained valuation evidence when a current read is denied", async () => {
  let denied = false; vi.stubGlobal("fetch", vi.fn(async () => denied ? json(null, 403) : json(reviewed))); view(); await load();
  denied = true; fireEvent.submit(screen.getByRole("form", { name: text("en", "loadValuation") }));
  await screen.findByRole("alert"); expect(screen.queryByRole("region", { name: text("en", "evidence") })).not.toBeInTheDocument();
});

it("aborts an outstanding evidence read on unmount and never renders its stale response", async () => {
  let resolve: (value: Response) => void = () => { throw new Error("No read"); }, signal: AbortSignal | undefined;
  vi.stubGlobal("fetch", vi.fn((_url: RequestInfo | URL, init?: RequestInit) => { signal = init?.signal as AbortSignal; return new Promise<Response>(done => { resolve = done; }); }));
  const rendered = view();
  fireEvent.change(screen.getByLabelText(text("en", "valuationId")), { target: { value: fixture.id } }); fireEvent.submit(screen.getByRole("form", { name: text("en", "loadValuation") }));
  await waitFor(() => expect(signal).toBeDefined()); rendered.unmount(); expect(signal?.aborted).toBe(true);
  resolve(json(fixture)); await waitFor(() => expect(screen.queryByText(fixture.id)).not.toBeInTheDocument()); expect(onLock).toHaveBeenLastCalledWith(false);
});

it("clears selected evidence across an authentication revision and hides it without the full read union", async () => {
  const fetcher = vi.fn(async () => json(reviewed)); vi.stubGlobal("fetch", fetcher); const rendered = view(); await load();
  auth.revision = 2;
  rendered.rerender(<MonetaryStockValuation locale="en" scope={source.scope} stock={stock} options={options} identity={identity} externallyLocked={false} readOnly={false} onLockChange={onLock} onChanged={onChanged} />);
  expect(screen.queryByRole("region", { name: text("en", "evidence") })).not.toBeInTheDocument(); expect(fetcher).toHaveBeenCalledTimes(1);
  rendered.rerender(<MonetaryStockValuation locale="en" scope={source.scope} stock={stock} options={options} identity={{ ...identity, permissions: identity.permissions.filter(permission => permission !== "inventory.read") }} externallyLocked={false} readOnly={false} onLockChange={onLock} onChanged={onChanged} />);
  expect(screen.queryByRole("form")).not.toBeInTheDocument(); expect(screen.getByRole("alert")).toHaveTextContent(text("en", "denied")); expect(fetcher).toHaveBeenCalledTimes(1);
});
