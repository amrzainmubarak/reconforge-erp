import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { BudgetIdentity } from "../budget-control-data";
import { partialReturnPermissions, partialReturnsRoot, type PartialReturnPlan } from "../customer-partial-returns-data";
import { partialBalanceFixture, partialPlanFixture, partialScope } from "../customer-partial-returns-test-fixtures";
import CustomerPartialReturns from "./CustomerPartialReturns";

const session = { tenantId: "synthetic", csrfToken: "csrf", expiresAt: "2099-01-01T00:00:00Z" };
const state = { session, revision: 1, username: "poster", isCurrent: () => true, recover: vi.fn(() => false) };
vi.mock("../browserSession", () => ({ useBrowserSession: () => state }));
const identity: BudgetIdentity = { id: "poster", human: true, stepUp: true, workspaces: ["work"], organizations: ["org"], entities: ["entity"], permissions: [...new Set(Object.values(partialReturnPermissions).flat())] };
const originalBalance = () => partialBalanceFixture({ history_version: 0, credited_minor: "0", returned_quantity_scaled: "0", remaining_quantity_scaled: "15", outstanding_minor: "57500" });
const onLock = vi.fn();
beforeEach(() => { onLock.mockReset(); state.recover.mockClear(); });
afterEach(() => vi.unstubAllGlobals());
async function select(plan: PartialReturnPlan) {
  const selector = await screen.findByRole("combobox", { name: "Retained partial return, refund or reversal" });
  await waitFor(() => expect(selector.querySelectorAll("option")).toHaveLength(2));
  fireEvent.change(selector, { target: { value: plan.id } });
  await screen.findByRole("heading", { name: "Native invoice and refund balance" });
}
function phaseReason(value = "Independent exact source review") {
  fireEvent.change(within(screen.getByRole("form", { name: /^(Review|Post) partial cycle plan$/ })).getByLabelText("Partial cycle reason"), { target: { value } });
}
it("keeps a lost POST acknowledgement and exact same command until manually retried", async () => {
  const attempts: string[] = []; let posted = false;
  vi.stubGlobal("fetch", vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    if (init?.method === "POST") { attempts.push(String(init.body)); if (attempts.length === 1) throw new TypeError("lost committed response"); posted = true; return new Response(JSON.stringify({ plan: partialPlanFixture(2) })); }
    if (String(url).includes("/balance")) return new Response(JSON.stringify({ balance: posted ? partialBalanceFixture() : originalBalance() }));
    return posted ? new Response("unavailable", { status: 503 }) : new Response(JSON.stringify({ plans: [partialPlanFixture()] }));
  }));
  const view = render(<CustomerPartialReturns locale="en" scope={partialScope} identity={identity} onLockChange={onLock} />);
  await select(partialPlanFixture()); phaseReason(); fireEvent.click(screen.getByRole("button", { name: "Post partial cycle plan" }));
  const retry = await screen.findByRole("button", { name: "Retry retained partial command" });
  expect(attempts).toHaveLength(1); expect(onLock).toHaveBeenLastCalledWith(true); expect(screen.getByRole("button", { name: "Post partial cycle plan" })).toBeDisabled();
  view.rerender(<CustomerPartialReturns locale="ar" scope={partialScope} identity={identity} onLockChange={onLock} />);
  expect(screen.getByRole("button", { name: "إعادة الأمر الجزئي المحفوظ" })).toBeInTheDocument(); expect(attempts).toHaveLength(1);
  view.rerender(<CustomerPartialReturns locale="en" scope={partialScope} identity={identity} onLockChange={onLock} />);
  fireEvent.click(retry); await screen.findByText(/effect-0/); await waitFor(() => expect(attempts).toHaveLength(2)); expect(attempts[0]).toBe(attempts[1]);
  expect(onLock).toHaveBeenLastCalledWith(false); expect(screen.queryByRole("button", { name: "Post partial cycle plan" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Cancel unposted partial plan" })).not.toBeInTheDocument();
});
it("retains an unverifiable acknowledgement without automatic retries or a new financial command", async () => {
  const requests = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    if (init?.method === "POST") return new Response(JSON.stringify({ plan: { ...partialPlanFixture(2), plan_digest: "f".repeat(64) } }));
    return new Response(JSON.stringify(String(url).includes("/balance") ? { balance: originalBalance() } : { plans: [partialPlanFixture()] }));
  });
  vi.stubGlobal("fetch", requests);
  render(<CustomerPartialReturns locale="en" scope={partialScope} identity={identity} onLockChange={onLock} />);
  await select(partialPlanFixture()); phaseReason(); fireEvent.click(screen.getByRole("button", { name: "Post partial cycle plan" }));
  await screen.findByRole("button", { name: "Retry retained partial command" });
  expect(requests.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1);
  expect(onLock).toHaveBeenLastCalledWith(true); expect(screen.getByRole("alert")).toHaveFocus();
});
it("requires an explicit exact source balance and sends the captured history version and scaled quantity", async () => {
  const requests: { url: string; body: Record<string, unknown> }[] = []; let prepared = false;
  vi.stubGlobal("fetch", vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    if (init?.method === "POST") { requests.push({ url: String(url), body: JSON.parse(String(init.body)) as Record<string, unknown> }); prepared = true; return new Response(JSON.stringify({ plan: partialPlanFixture(0) })); }
    return new Response(JSON.stringify(String(url).includes("/balance") ? { balance: originalBalance() } : { plans: prepared ? [partialPlanFixture(0)] : [] }));
  }));
  render(<CustomerPartialReturns locale="en" scope={partialScope} identity={identity} onLockChange={onLock} />);
  expect(screen.queryByRole("button", { name: "Prepare partial original return" })).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Partial return original stock order ID"), { target: { value: "stock-original" } });
  await waitFor(() => expect(screen.getByRole("button", { name: "Load original source balance" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "Load original source balance" }));
  const form = await screen.findByRole("form", { name: "Prepare partial original return" });
  for (const [label, value] of [["Return quantity in captured scaled units", "12"], ["Partial cycle fiscal period ID", "period"], ["Partial cycle posting date", "2026-10-15"], ["Refund cash journal code", "CASH"], ["Partial refund liability account", "REFUND"], ["Captured collection cash account", "CASH"], ["Partial cycle reason", "Original twelve units"]]) fireEvent.change(within(form).getByLabelText(label), { target: { value } });
  fireEvent.click(within(form).getByRole("button")); await waitFor(() => expect(requests).toHaveLength(1));
  expect(requests[0].url).toBe(`${partialReturnsRoot}/plans`); expect(requests[0].body).toMatchObject({ quantity_scaled: "12", expected_history_version: 0, source_order_id: "stock-original" });
  expect(requests[0].body).not.toHaveProperty("actor_id"); expect(requests[0].body).not.toHaveProperty("legal_entity_id");
});
it.each([["maker", 0], ["checker", 1]] as const)("blocks %s from acting as the next independent authority", async (id, phase) => {
  const plan = partialPlanFixture(phase);
  vi.stubGlobal("fetch", vi.fn(async (url: RequestInfo | URL) => new Response(JSON.stringify(String(url).includes("/balance") ? { balance: originalBalance() } : { plans: [plan] }))));
  render(<CustomerPartialReturns locale="en" scope={partialScope} identity={{ ...identity, id }} onLockChange={onLock} />); await select(plan); phaseReason();
  expect(screen.getByRole("button", { name: phase === 0 ? "Review partial cycle plan" : "Post partial cycle plan" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Cancel unposted partial plan" })).toBeDisabled();
});
it("exposes evidence to a reader without showing mutation controls", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url: RequestInfo | URL) => new Response(JSON.stringify(String(url).includes("/balance") ? { balance: partialBalanceFixture() } : { plans: [partialPlanFixture(2)] }))));
  render(<CustomerPartialReturns locale="en" scope={partialScope} identity={{ ...identity, permissions: [...partialReturnPermissions.read] }} onLockChange={onLock} />);
  await select(partialPlanFixture(2)); expect(screen.queryByRole("button", { name: "Prepare partial original return" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Prepare governed reversal" })).not.toBeInTheDocument();
  expect(screen.getByText(/effect-0/)).toBeInTheDocument();
});
it("refuses current authorization withdrawal without retrying the denied command", async () => {
  const requests = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => init?.method === "POST" ? new Response(JSON.stringify({ error: { code: "sales_actor_denied" } }), { status: 403 }) : new Response(JSON.stringify(String(url).includes("/balance") ? { balance: originalBalance() } : { plans: [partialPlanFixture()] })));
  vi.stubGlobal("fetch", requests); render(<CustomerPartialReturns locale="en" scope={partialScope} identity={identity} onLockChange={onLock} />);
  await select(partialPlanFixture()); phaseReason(); fireEvent.click(screen.getByRole("button", { name: "Post partial cycle plan" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Current authority or scope refused");
  expect(screen.queryByRole("button", { name: "Retry retained partial command" })).not.toBeInTheDocument();
  expect(requests.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1); expect(onLock).toHaveBeenLastCalledWith(false);
});
it("prepares a refund from posted native liability and rejects an amount above it locally", async () => {
  const posted = partialPlanFixture(2), due = partialBalanceFixture({ history_version: 2, credited_minor: "67500", returned_quantity_scaled: "15", remaining_quantity_scaled: "0", refund_entitlement_minor: "10000", refund_due_minor: "10000", outstanding_minor: "0" });
  const attempts: Record<string, unknown>[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    if (init?.method === "POST") { attempts.push(JSON.parse(String(init.body)) as Record<string, unknown>); return new Response(JSON.stringify({ plan: { ...partialPlanFixture(0, "Refund"), expected_history_version: 2 } })); }
    return new Response(JSON.stringify(String(url).includes("/balance") ? { balance: due } : { plans: [posted] }));
  }));
  render(<CustomerPartialReturns locale="en" scope={partialScope} identity={identity} onLockChange={onLock} />); await select(posted);
  const form = screen.getByRole("form", { name: "Prepare governed refund" });
  for (const [label, value] of [["Refund amount in exact minor units", "10001"], ["Partial cycle fiscal period ID", "period"], ["Partial cycle posting date", "2026-10-15"], ["Partial cycle reason", "Settled cash refund"]]) fireEvent.change(within(form).getByLabelText(label), { target: { value } });
  fireEvent.click(within(form).getByRole("button")); expect(attempts).toHaveLength(0); expect(screen.getByRole("alert")).toHaveFocus();
  fireEvent.change(within(form).getByLabelText("Refund amount in exact minor units"), { target: { value: "10000" } }); fireEvent.click(within(form).getByRole("button"));
  await waitFor(() => expect(attempts).toHaveLength(1)); expect(attempts[0]).toMatchObject({ amount_minor: "10000", expected_history_version: 2 });
});
it("prepares a governed reversal rather than changing a posted plan or posting automatically", async () => {
  const attempts: { url: string; body: Record<string, unknown> }[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    if (init?.method === "POST") { attempts.push({ url: String(url), body: JSON.parse(String(init.body)) as Record<string, unknown> }); return new Response(JSON.stringify({ plan: { ...partialPlanFixture(0, "ReverseReturn"), expected_history_version: 1 } })); }
    return new Response(JSON.stringify(String(url).includes("/balance") ? { balance: partialBalanceFixture() } : { plans: [partialPlanFixture(2)] }));
  }));
  render(<CustomerPartialReturns locale="en" scope={partialScope} identity={identity} onLockChange={onLock} />); await select(partialPlanFixture(2));
  const form = screen.getByRole("form", { name: "Prepare governed reversal" });
  for (const [label, value] of [["Partial cycle fiscal period ID", "period"], ["Partial cycle posting date", "2026-10-15"], ["Partial cycle reason", "Explicit original correction"]]) fireEvent.change(within(form).getByLabelText(label), { target: { value } });
  fireEvent.click(within(form).getByRole("button")); await waitFor(() => expect(attempts).toHaveLength(1));
  expect(attempts[0].url).toBe(`${partialReturnsRoot}/plans/${partialPlanFixture(2).id}/reversals`); expect(attempts[0].body.expected_history_version).toBe(1);
  await within(screen.getByRole("region", { name: "Partial cycle source and posting evidence" })).findByText("Return reversal · Prepared", { exact: true }); expect(screen.getByRole("button", { name: "Review partial cycle plan" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Post partial cycle plan" })).not.toBeInTheDocument();
});
it("renders bilingual native boundaries with RTL and makes no financial mutations on mount", async () => {
  const requests = vi.fn(async () => new Response(JSON.stringify({ plans: [] }))); vi.stubGlobal("fetch", requests);
  const view = render(<CustomerPartialReturns locale="ar" scope={partialScope} identity={identity} onLockChange={onLock} />);
  expect(screen.getByRole("region", { name: "دورة إرجاع العميل الجزئي" })).toHaveAttribute("dir", "rtl");
  await screen.findByText("لا توجد خطط جزئية في هذا النطاق."); expect(requests).toHaveBeenCalledTimes(1);
  expect(requests.mock.calls[0]).toEqual([`${partialReturnsRoot}/plans`, expect.objectContaining({ method: "GET" })]);
  view.rerender(<CustomerPartialReturns locale="en" scope={partialScope} identity={identity} onLockChange={onLock} />);
  expect(screen.getByRole("region", { name: "Partial customer return cycle" })).toHaveAttribute("dir", "ltr"); expect(requests).toHaveBeenCalledTimes(1);
});
it("loads a retained plan by its exact ID without depending on the bounded list page", async () => {
  const posted = partialPlanFixture(2), requests = vi.fn(async (url: RequestInfo | URL, _init?: RequestInit) => new Response(JSON.stringify(String(url).includes("/balance") ? { balance: partialBalanceFixture() } : String(url).endsWith(posted.id) ? { plan: posted } : { plans: [] })));
  vi.stubGlobal("fetch", requests);
  render(<CustomerPartialReturns locale="en" scope={partialScope} identity={identity} onLockChange={onLock} />);
  fireEvent.change(screen.getByLabelText("Partial cycle plan ID"), { target: { value: posted.id } });
  await waitFor(() => expect(screen.getByRole("button", { name: "Load exact retained partial plan" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "Load exact retained partial plan" }));
  await screen.findByText(/effect-0/);
  expect(requests.mock.calls.some(([url, init]) => String(url) === `${partialReturnsRoot}/plans/${posted.id}` && init?.method === "GET")).toBe(true);
  expect(requests.mock.calls.every(([, init]) => init?.method === "GET")).toBe(true);
});
it("cancels only an unposted plan using its retained digest without claiming a financial posting", async () => {
  let cancelled = false; const attempts: string[] = [], prepared = partialPlanFixture(0);
  vi.stubGlobal("fetch", vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    const value = { ...partialPlanFixture(3), reviewer_actor_id: null };
    if (init?.method === "POST") { attempts.push(String(init.body)); cancelled = true; return new Response(JSON.stringify({ plan: value })); }
    return new Response(JSON.stringify(String(url).includes("/balance") ? { balance: originalBalance() } : { plans: [cancelled ? value : prepared] }));
  }));
  render(<CustomerPartialReturns locale="en" scope={partialScope} identity={identity} onLockChange={onLock} />); await select(prepared); phaseReason("Explicitly cancel unposted source claim");
  fireEvent.click(screen.getByRole("button", { name: "Cancel unposted partial plan" }));
  await within(screen.getByRole("region", { name: "Partial cycle source and posting evidence" })).findByText("Return · Cancelled", { exact: true }); expect(attempts).toHaveLength(1); expect(JSON.parse(attempts[0])).toMatchObject({ expected_plan_digest: prepared.plan_digest });
  expect(screen.queryByRole("button", { name: "Post partial cycle plan" })).not.toBeInTheDocument(); expect(screen.queryByText(/effect-0/)).not.toBeInTheDocument();
});
it("keeps history evidence readable at the finite capacity while disabling a new economic preparation", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url: RequestInfo | URL) => new Response(JSON.stringify(String(url).includes("/balance") ? { balance: { ...originalBalance(), history_version: 256 } } : { plans: [] }))));
  render(<CustomerPartialReturns locale="en" scope={partialScope} identity={identity} onLockChange={onLock} />);
  fireEvent.change(screen.getByLabelText("Partial return original stock order ID"), { target: { value: "stock-original" } });
  await waitFor(() => expect(screen.getByRole("button", { name: "Load original source balance" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "Load original source balance" }));
  await screen.findByText(/This source has reached the supported history limit/); expect(screen.getByRole("button", { name: "Prepare partial original return" })).toBeDisabled();
});
it("waits for the current source balance before admitting a retained partial post", async () => {
  const value = partialPlanFixture();
  let release!: (response: Response) => void;
  const waiting = new Promise<Response>(resolve => { release = resolve; });
  const attempts: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    if (init?.method === "POST") { attempts.push(String(url)); return new Response(JSON.stringify({ plan: partialPlanFixture(2) })); }
    return String(url).includes("/balance") ? waiting : new Response(JSON.stringify({ plans: [value] }));
  }));
  render(<CustomerPartialReturns locale="en" scope={partialScope} identity={identity} onLockChange={onLock} />);
  const selector = screen.getByRole("combobox", { name: "Retained partial return, refund or reversal" });
  await waitFor(() => expect(selector.querySelectorAll("option")).toHaveLength(2));
  fireEvent.change(selector, { target: { value: value.id } });
  const form = await screen.findByRole("form", { name: "Post partial cycle plan" });
  phaseReason();
  const post = within(form).getByRole("button", { name: "Post partial cycle plan" });
  expect(post).toBeDisabled();
  fireEvent.submit(form);
  expect(attempts).toEqual([]);
  release(new Response(JSON.stringify({ balance: originalBalance() })));
  await waitFor(() => expect(post).toBeEnabled());
  expect(attempts).toEqual([]);
});
