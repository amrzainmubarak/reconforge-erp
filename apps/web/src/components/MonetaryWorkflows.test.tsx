import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { partialReturnPermissions } from "../customer-partial-returns-data";
import { monetaryPartialRoot, monetaryStockRoot } from "../monetary-paths";
import fixtures from "../monetary-test-fixtures.json";
import { monetaryTranslate as text } from "../monetary-words";
import type { SalesIdentity } from "../sales-revenue-data";
import { MonetaryCustomerReturns } from "./MonetaryCustomerReturns";
import { MonetaryStockPanel } from "./MonetaryStockPanel";

const session = { tenantId: "synthetic", csrfToken: "csrf", expiresAt: "2099-01-01T00:00:00Z" };
const state = { session, revision: 1, username: "poster", isCurrent: vi.fn(() => true), recover: vi.fn(() => false) };
vi.mock("../browserSession", () => ({ useBrowserSession: () => state }));
const permissions = [...new Set([...Object.values(partialReturnPermissions).flat(), "sales.read", "sales.manage", "sales.approve", "inventory.read", "inventory.manage", "inventory.post", "inventory.valuation.manage", "inventory.valuation.approve", "receivables.manage", "receivables.approve"])];
const identity: SalesIdentity = { id: "poster", human: true, stepUp: true, workspaces: ["work"], organizations: ["organization"], entities: ["entity"], permissions };
const scope = fixtures.scope, onLock = vi.fn();
const options = { customers: [], periods: [{ id: "period", name: "October", start_date: "2026-10-01", end_date: "2026-10-31" }], journals: [], accounts: [], items: [], warehouses: [], locations: [], policies: [] };
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status });
const balance = () => ({ ...fixtures.balance, source_fingerprint: fixtures.return.source_fingerprint });
function reviewed(zero = false) {
  const value = structuredClone(zero ? fixtures.zeroReturn : fixtures.return);
  return { ...value, status: "Reviewed", phase: 1, posted_actor_id: null, movement_id: null,
    entries: value.entries.map(entry => ({ ...entry, posting_effect_id: null })) };
}
async function selectPartial(id = fixtures.return.id) {
  const select = screen.getByRole("combobox", { name: text("en", "selectPlan") });
  await waitFor(() => expect(within(select).getAllByRole("option")).toHaveLength(2));
  fireEvent.change(select, { target: { value: id } });
  await screen.findByRole("heading", { name: text("en", "currentBalance") });
}
async function selectStock(origin = true) {
  const select = screen.getByRole("combobox", { name: text("en", "selectStock") });
  await waitFor(() => expect(within(select).getAllByRole("option")).toHaveLength(2));
  fireEvent.change(select, { target: { value: fixtures.stock.id } });
  if (origin) await screen.findByRole("region", { name: text("en", "origin") });
  else await screen.findByRole("heading", { name: /SYNTHETIC-SALE · Draft/ });
}
beforeEach(() => { onLock.mockReset(); state.isCurrent.mockReturnValue(true); state.recover.mockClear(); });
afterEach(() => vi.unstubAllGlobals());

it("keeps the native dual-currency invoice, tax and functional inventory evidence distinct in both languages", async () => {
  const fetcher = vi.fn(async (url: RequestInfo | URL) => json(String(url).endsWith("/options") ? options : String(url).endsWith("/orders") ? { orders: [fixtures.stock] } : fixtures.stock));
  vi.stubGlobal("fetch", fetcher);
  const view = render(<MonetaryStockPanel locale="en" scope={scope} identity={identity} externallyLocked={false} onLockChange={onLock} />);
  await selectStock();
  const origin = screen.getByRole("region", { name: text("en", "origin") });
  expect(within(origin).getByText("12.00 EUR")).toBeInTheDocument();
  expect(within(origin).getByText("15.00 USD")).toBeInTheDocument();
  expect(within(origin).getByText(fixtures.stock.monetary_origin.invoice_number)).toBeInTheDocument();
  expect(screen.getByText(/configured|declared taxes/i)).toBeInTheDocument();
  view.rerender(<MonetaryStockPanel locale="ar" scope={scope} identity={identity} externallyLocked={false} onLockChange={onLock} />);
  expect(screen.getByRole("region", { name: text("ar", "stockTitle") })).toHaveAttribute("dir", "rtl");
  expect(fetcher.mock.calls.every(([, init]: [RequestInfo | URL, RequestInit?]) => !init || init.method === "GET")).toBe(true);
});

it("does not read evidence without the complete native READ union", async () => {
  const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
  render(<MonetaryStockPanel locale="en" scope={scope} identity={{ ...identity, permissions: permissions.filter(value => value !== "inventory.read") }} externallyLocked={false} onLockChange={onLock} />);
  expect(fetcher).not.toHaveBeenCalled();
  expect(screen.queryByRole("button", { name: text("en", "create") })).not.toBeInTheDocument();
});

it("retains the exact versioned post command after response loss, blocks other actions and only retries by a human", async () => {
  let posted = false;
  const attempts: { path: string; body: string }[] = [], value = reviewed();
  const fetcher = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    const path = String(url);
    if (init?.method === "POST") { attempts.push({ path, body: String(init.body) }); if (attempts.length === 1) throw new TypeError("lost reply"); posted = true; return json({ plan: fixtures.return }); }
    return json(path.includes("/balance") ? { balance: balance() } : path.endsWith(value.id) ? { plan: posted ? fixtures.return : value } : { plans: [posted ? fixtures.return : value] });
  });
  vi.stubGlobal("fetch", fetcher);
  const view = render(<MonetaryCustomerReturns locale="en" scope={scope} identity={identity} externallyLocked={false} onLockChange={onLock} />);
  await selectPartial();
  const form = screen.getByRole("form", { name: text("en", "post") });
  fireEvent.change(within(form).getByLabelText(text("en", "reason")), { target: { value: "Third independent person" } });
  fireEvent.click(within(form).getByRole("button", { name: text("en", "post") }));
  await screen.findByRole("button", { name: text("en", "retry") });
  expect(attempts).toHaveLength(1); expect(onLock).toHaveBeenLastCalledWith(true); expect(screen.getByRole("alert")).toHaveFocus();
  expect(screen.getByRole("button", { name: text("en", "refresh") })).toBeDisabled();
  const count = fetcher.mock.calls.length;
  view.rerender(<MonetaryCustomerReturns locale="ar" scope={scope} identity={identity} externallyLocked={false} onLockChange={onLock} />);
  expect(screen.getByRole("region", { name: text("ar", "partialTitle") })).toHaveAttribute("dir", "rtl");
  expect(fetcher).toHaveBeenCalledTimes(count);
  fireEvent.click(screen.getByRole("button", { name: text("ar", "retry") }));
  await screen.findByRole("heading", { name: `${text("ar", "Return")} · ${text("ar", "Posted")}` });
  expect(attempts[0]).toEqual(attempts[1]); expect(attempts[1].path).toBe(`${monetaryPartialRoot}/plans/${value.id}/post`);
  expect(JSON.parse(attempts[1].body)).toMatchObject({ expected_plan_digest: value.plan_digest, reason: "Third independent person" });
  await waitFor(() => expect(onLock).toHaveBeenLastCalledWith(false));
});

it("retains a contended CR3 command for an explicit same-body human retry in both languages", async () => {
  let posted = false;
  const attempts: { path: string; body: string }[] = [], value = reviewed();
  const fetcher = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    const path = String(url);
    if (init?.method === "POST") {
      attempts.push({ path, body: String(init.body) });
      if (attempts.length === 1) return json({ error: { code: "monetary_return_retryable_conflict", message: "The command is contended." } }, 409);
      posted = true; return json({ plan: fixtures.return });
    }
    return json(path.includes("/balance") ? { balance: balance() } : path.endsWith(value.id) ? { plan: posted ? fixtures.return : value } : { plans: [posted ? fixtures.return : value] });
  });
  vi.stubGlobal("fetch", fetcher);
  const view = render(<MonetaryCustomerReturns locale="en" scope={scope} identity={identity} externallyLocked={false} onLockChange={onLock} />);
  await selectPartial();
  const form = screen.getByRole("form", { name: text("en", "post") });
  fireEvent.change(within(form).getByLabelText(text("en", "reason")), { target: { value: "Retain original contended command" } });
  fireEvent.click(within(form).getByRole("button", { name: text("en", "post") }));
  await screen.findByRole("button", { name: text("en", "retry") });
  expect(screen.getByRole("alert")).toHaveTextContent("Another operation is using a required resource.");
  expect(screen.getByRole("alert")).not.toHaveTextContent(text("en", "unknown"));
  expect(screen.getByRole("alert")).toHaveFocus();
  expect(screen.getByRole("button", { name: text("en", "refresh") })).toBeDisabled();
  expect(screen.getByRole("combobox", { name: text("en", "selectPlan") })).toBeDisabled();
  expect(within(form).getByLabelText(text("en", "reason"))).toBeDisabled();
  expect(attempts).toHaveLength(1); expect(onLock).toHaveBeenLastCalledWith(true);
  const count = fetcher.mock.calls.length;
  view.rerender(<MonetaryCustomerReturns locale="ar" scope={scope} identity={identity} externallyLocked={false} onLockChange={onLock} />);
  expect(screen.getByRole("region", { name: text("ar", "partialTitle") })).toHaveAttribute("dir", "rtl");
  expect(screen.getByRole("alert")).toHaveTextContent("يتعذر تنفيذ الأمر الآن لوجود عملية أخرى.");
  expect(fetcher).toHaveBeenCalledTimes(count);
  fireEvent.click(screen.getByRole("button", { name: text("ar", "retry") }));
  await screen.findByRole("heading", { name: `${text("ar", "Return")} · ${text("ar", "Posted")}` });
  expect(attempts).toHaveLength(2); expect(attempts[0]).toEqual(attempts[1]);
  expect(attempts[1].path).toBe(`${monetaryPartialRoot}/plans/${value.id}/post`);
  expect(JSON.parse(attempts[1].body)).toMatchObject({ expected_plan_digest: value.plan_digest, reason: "Retain original contended command" });
  expect(JSON.parse(attempts[1].body).command_id).toEqual(expect.any(String));
  await waitFor(() => expect(onLock).toHaveBeenLastCalledWith(false));
});

it.each([[409, "customer_partial_return_source_changed"], [400, "monetary_return_retryable_conflict"], [403, "monetary_return_retryable_conflict"]])("does not retain a definitive HTTP %s / %s response as a retryable command", async (status, code) => {
  const attempts: string[] = [], value = reviewed();
  vi.stubGlobal("fetch", vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    if (init?.method === "POST") { attempts.push(String(init.body)); return json({ error: { code, message: "Definitive refusal" } }, Number(status)); }
    return json(String(url).includes("/balance") ? { balance: balance() } : String(url).endsWith(value.id) ? { plan: value } : { plans: [value] });
  }));
  render(<MonetaryCustomerReturns locale="en" scope={scope} identity={identity} externallyLocked={false} onLockChange={onLock} />);
  await selectPartial();
  const form = screen.getByRole("form", { name: text("en", "post") });
  fireEvent.change(within(form).getByLabelText(text("en", "reason")), { target: { value: "Definitive refusal" } });
  fireEvent.click(within(form).getByRole("button", { name: text("en", "post") }));
  await waitFor(() => expect(attempts).toHaveLength(1));
  await waitFor(() => expect(onLock).toHaveBeenLastCalledWith(false));
  expect(screen.queryByRole("button", { name: text("en", "retry") })).not.toBeInTheDocument();
});

it("rechecks current authority on a manual contended retry and clears its retained command after 403", async () => {
  const attempts: { path: string; body: string }[] = [], value = reviewed();
  let denied = false;
  vi.stubGlobal("fetch", vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    if (init?.method === "POST") {
      attempts.push({ path: String(url), body: String(init.body) });
      if (attempts.length === 1) return json({ error: { code: "monetary_return_retryable_conflict", message: "Contended" } }, 409);
      denied = true; return json({ error: { code: "monetary_return_permission_denied", message: "Current permission refused" } }, 403);
    }
    return denied ? json({ error: { code: "forbidden", message: "Current permission refused" } }, 403) : json(String(url).includes("/balance") ? { balance: balance() } : String(url).endsWith(value.id) ? { plan: value } : { plans: [value] });
  }));
  render(<MonetaryCustomerReturns locale="en" scope={scope} identity={identity} externallyLocked={false} onLockChange={onLock} />);
  await selectPartial();
  const form = screen.getByRole("form", { name: text("en", "post") });
  fireEvent.change(within(form).getByLabelText(text("en", "reason")), { target: { value: "Recheck current authority" } });
  fireEvent.click(within(form).getByRole("button", { name: text("en", "post") }));
  fireEvent.click(await screen.findByRole("button", { name: text("en", "retry") }));
  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(text("en", "denied")));
  expect(attempts).toHaveLength(2); expect(attempts[0]).toEqual(attempts[1]);
  expect(screen.queryByRole("button", { name: text("en", "retry") })).not.toBeInTheDocument();
  expect(screen.queryByRole("region", { name: text("en", "evidence") })).not.toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: text("en", "currentBalance") })).not.toBeInTheDocument();
  expect(onLock).toHaveBeenLastCalledWith(false);
});

it.each(["maker", "checker"])("requires a third person even when the return has no monetary journal: %s", async id => {
  const value = reviewed(true);
  vi.stubGlobal("fetch", vi.fn(async (url: RequestInfo | URL) => json(String(url).includes("/balance") ? { balance: balance() } : String(url).endsWith(value.id) ? { plan: value } : { plans: [value] })));
  render(<MonetaryCustomerReturns locale="en" scope={scope} identity={{ ...identity, id }} externallyLocked={false} onLockChange={onLock} />);
  await selectPartial(value.id);
  expect(screen.getByText(text("en", "zeroJournal"))).toBeInTheDocument();
  expect(screen.getByRole("button", { name: text("en", "post") })).toBeDisabled();
});

it("derives preparation only from the loaded history and scaled quantity, without user account or allocation authority", async () => {
  const attempts: Record<string, unknown>[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    if (init?.method === "POST") { attempts.push(JSON.parse(String(init.body))); return json({ detail: { code: "customer_partial_return_source_changed" } }, 409); }
    return json(String(url).includes("/balance") ? { balance: fixtures.balance } : { plans: [] });
  }));
  render(<MonetaryCustomerReturns locale="en" scope={scope} identity={identity} externallyLocked={false} onLockChange={onLock} />);
  fireEvent.change(screen.getByLabelText(text("en", "source_order_id")), { target: { value: fixtures.balance.source_order_id } });
  fireEvent.click(screen.getByRole("button", { name: text("en", "sourceLoad") }));
  const form = await screen.findByRole("form", { name: text("en", "prepareReturn") });
  for (const [key, value] of [["quantity_scaled", "5"], ["period_id", "period"], ["posting_date", "2026-10-15"], ["reason", "Captured source quantity"]] as const) fireEvent.change(within(form).getByLabelText(text("en", key)), { target: { value } });
  fireEvent.click(within(form).getByRole("button"));
  await waitFor(() => expect(attempts).toHaveLength(1));
  expect(Object.keys(attempts[0]).sort()).toEqual(["command_id", "expected_history_version", "period_id", "posting_date", "quantity_scaled", "reason", "source_order_id"].sort());
  expect(attempts[0]).toMatchObject({ quantity_scaled: "5", expected_history_version: fixtures.balance.history_version });
  await screen.findByRole("alert"); expect(screen.queryByRole("button", { name: text("en", "retry") })).not.toBeInTheDocument();
});

it("clears sensitive selected evidence when current READ permission is refused", async () => {
  let denied = false;
  vi.stubGlobal("fetch", vi.fn(async (url: RequestInfo | URL) => denied ? json({ detail: { code: "forbidden" } }, 403) : json(String(url).includes("/balance") ? { balance: balance() } : String(url).endsWith(fixtures.return.id) ? { plan: fixtures.return } : { plans: [fixtures.return] })));
  render(<MonetaryCustomerReturns locale="en" scope={scope} identity={identity} externallyLocked={false} onLockChange={onLock} />);
  await selectPartial(); expect(screen.getByRole("region", { name: text("en", "evidence") })).toBeInTheDocument();
  denied = true; fireEvent.click(screen.getByRole("button", { name: text("en", "refresh") }));
  await screen.findByRole("alert");
  expect(screen.queryByRole("region", { name: text("en", "evidence") })).not.toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: text("en", "currentBalance") })).not.toBeInTheDocument();
});

it("discards an old scope's response after unmount rather than showing it in the next scope", async () => {
  let resolveOld: (value: Response) => void = () => { throw new Error("pending request not started"); };
  const requests = vi.fn((url: RequestInfo | URL) => String(url).endsWith("/plans") ? new Promise<Response>(resolve => { resolveOld = resolve; }) : Promise.resolve(json({ plans: [] })));
  vi.stubGlobal("fetch", requests);
  const view = render(<MonetaryCustomerReturns locale="en" scope={scope} identity={identity} externallyLocked={false} onLockChange={onLock} />);
  view.unmount(); state.isCurrent.mockReturnValue(false); resolveOld(json({ plans: [fixtures.return] }));
  await waitFor(() => expect(screen.queryByText(fixtures.return.id)).not.toBeInTheDocument());
  expect(onLock).toHaveBeenLastCalledWith(false);
});

it("requires the NEW AR maker permission for a collection while leaving source evidence readable", async () => {
  const fetcher = vi.fn(async (url: RequestInfo | URL) => json(String(url).endsWith("/options") ? options : String(url).endsWith("/orders") ? { orders: [fixtures.stock] } : fixtures.stock));
  vi.stubGlobal("fetch", fetcher);
  render(<MonetaryStockPanel locale="en" scope={scope} identity={{ ...identity, permissions: permissions.filter(value => value !== "receivables.manage") }} externallyLocked={false} onLockChange={onLock} />);
  await selectStock();
  expect(screen.getByRole("button", { name: text("en", "prepareCollection") })).toBeDisabled();
  expect(fetcher.mock.calls.every(([, init]: [RequestInfo | URL, RequestInit?]) => !init || init.method === "GET")).toBe(true);
});

it("retains a malformed but successful post reply as unknown instead of creating a new command", async () => {
  const value = reviewed();
  const fetcher = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => init?.method === "POST" ? json({ plan: { ...fixtures.return, plan_digest: "f".repeat(64) } }) : json(String(url).includes("/balance") ? { balance: balance() } : String(url).endsWith(value.id) ? { plan: value } : { plans: [value] }));
  vi.stubGlobal("fetch", fetcher);
  render(<MonetaryCustomerReturns locale="en" scope={scope} identity={identity} externallyLocked={false} onLockChange={onLock} />);
  await selectPartial();
  const form = screen.getByRole("form", { name: text("en", "post") });
  fireEvent.change(within(form).getByLabelText(text("en", "reason")), { target: { value: "Explicit reviewed digest" } });
  fireEvent.click(within(form).getByRole("button", { name: text("en", "post") }));
  await screen.findByRole("button", { name: text("en", "retry") });
  expect(fetcher.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1);
  expect(onLock).toHaveBeenLastCalledWith(true);
});

it("refuses a different source fingerprint even when both public objects are independently valid", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url: RequestInfo | URL) => json(String(url).includes("/balance") ? { balance: fixtures.balance } : String(url).endsWith(fixtures.return.id) ? { plan: fixtures.return } : { plans: [fixtures.return] })));
  render(<MonetaryCustomerReturns locale="en" scope={scope} identity={identity} externallyLocked={false} onLockChange={onLock} />);
  const select = screen.getByRole("combobox", { name: text("en", "selectPlan") });
  await waitFor(() => expect(within(select).getAllByRole("option")).toHaveLength(2));
  fireEvent.change(select, { target: { value: fixtures.return.id } });
  await screen.findByRole("alert");
  expect(screen.queryByRole("heading", { name: text("en", "currentBalance") })).not.toBeInTheDocument();
});

it("posts a zero-journal return only through an explicit third-person action and retains its physical evidence", async () => {
  const value = reviewed(true); let posted = false;
  const fetcher = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    if (init?.method === "POST") { posted = true; return json({ plan: fixtures.zeroReturn }); }
    return json(String(url).includes("/balance") ? { balance: balance() } : String(url).endsWith(value.id) ? { plan: posted ? fixtures.zeroReturn : value } : { plans: [posted ? fixtures.zeroReturn : value] });
  });
  vi.stubGlobal("fetch", fetcher);
  render(<MonetaryCustomerReturns locale="en" scope={scope} identity={identity} externallyLocked={false} onLockChange={onLock} />);
  await selectPartial(); expect(fetcher.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(0);
  const form = screen.getByRole("form", { name: text("en", "post") });
  fireEvent.change(within(form).getByLabelText(text("en", "reason")), { target: { value: "Third person accepts native quantity evidence" } });
  fireEvent.click(within(form).getByRole("button", { name: text("en", "post") }));
  await screen.findByRole("heading", { name: "Return · Posted" });
  expect(fetcher.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1);
  expect(screen.getByText(text("en", "zeroJournal"))).toBeInTheDocument();
  expect(screen.getByText(fixtures.zeroReturn.movement_id)).toBeInTheDocument();
});

it("shows the actual collection number, functional carrying release and realized FX separately for review", async () => {
  const stock = { ...fixtures.stock, row_version: 13, balance: { ...fixtures.stock.balance, history_version: 1, transaction_collected_minor: "200", transaction_outstanding_minor: "1000", functional_outstanding_minor: "1250" },
    collection: { id: "FX1-COLLECTION", sequence: 1, status: "Posted", plan_digest: "d".repeat(64), amount_minor: "200", functional_cash_minor: "260", functional_receivable_released_minor: "250", functional_fx_gain_minor: "10", functional_fx_loss_minor: "0",
      settlement_rate: { rate: "1.3", source: "Synthetic settlement observation", effective_at: "2026-10-15T13:00:00Z" }, receipt_number: "FX1-RECEIPT", receipt_date: "2026-10-15", period_id: "period", preparer_actor_id: "maker", reviewer_actor_id: "checker", posted_actor_id: "poster", entry_id: "COLLECTION-ENTRY", posting_effect_id: "COLLECTION-EFFECT", receipt_id: "native-receipt" },
    events: [...fixtures.stock.events, ...[["prepare-collection", "CollectionPrepared", "maker"], ["review-collection", "CollectionReviewed", "checker"], ["collect", "Invoiced", "poster"]].map(([operation, status, actor_id], index) => ({ version: 11 + index, actor_id, operation, reason: "Synthetic collection", status, audit_event_id: `audit-collection-${index}` }))] };
  vi.stubGlobal("fetch", vi.fn(async (url: RequestInfo | URL) => json(String(url).endsWith("/options") ? options : String(url).endsWith("/orders") ? { orders: [stock] } : stock)));
  render(<MonetaryStockPanel locale="en" scope={scope} identity={identity} externallyLocked={false} onLockChange={onLock} />);
  await selectStock();
  const section = screen.getByRole("region", { name: text("en", "collectionEvidence") });
  expect(within(section).getByText("FX1-RECEIPT")).toBeInTheDocument();
  for (const amount of ["2.00 EUR", "2.60 USD", "2.50 USD", "0.10 USD"]) expect(within(section).getByText(amount)).toBeInTheDocument();
  expect(within(section).getByText(/Synthetic settlement observation/)).toBeInTheDocument();
});

it("preserves a Stock command and its version across unknown delivery and a locale change", async () => {
  const submitted = { ...fixtures.draft, status: "Submitted", row_version: 2, events: [...fixtures.draft.events, { version: 2, actor_id: "poster", operation: "submit", reason: "Submit exact source", status: "Submitted", audit_event_id: "audit-submit" }] };
  const attempts: { path: string; body: string }[] = []; let done = false;
  const fetcher = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    if (init?.method === "POST") { attempts.push({ path: String(url), body: String(init.body) }); if (attempts.length === 1) throw new TypeError("lost acknowledgement"); done = true; return json(submitted); }
    return json(String(url).endsWith("/options") ? options : String(url).endsWith("/orders") ? { orders: [done ? submitted : fixtures.draft] } : done ? submitted : fixtures.draft);
  });
  vi.stubGlobal("fetch", fetcher);
  const view = render(<MonetaryStockPanel locale="en" scope={scope} identity={identity} externallyLocked={false} onLockChange={onLock} />);
  await selectStock(false);
  const form = screen.getByRole("form", { name: text("en", "submit") });
  fireEvent.change(within(form).getByLabelText(text("en", "reason")), { target: { value: "Submit exact source" } });
  fireEvent.click(within(form).getByRole("button", { name: text("en", "submit") }));
  await screen.findByRole("button", { name: text("en", "retry") });
  expect(attempts).toHaveLength(1); expect(onLock).toHaveBeenLastCalledWith(true);
  view.rerender(<MonetaryStockPanel locale="ar" scope={scope} identity={identity} externallyLocked={false} onLockChange={onLock} />);
  expect(attempts).toHaveLength(1); fireEvent.click(screen.getByRole("button", { name: text("ar", "retry") }));
  await waitFor(() => expect(attempts).toHaveLength(2)); expect(attempts[0]).toEqual(attempts[1]);
  expect(attempts[1].path).toBe(`${monetaryStockRoot}/orders/${fixtures.draft.id}/submit`);
  expect(JSON.parse(attempts[1].body)).toMatchObject({ expected_version: 1, reason: "Submit exact source" });
  await waitFor(() => expect(onLock).toHaveBeenLastCalledWith(false));
});
