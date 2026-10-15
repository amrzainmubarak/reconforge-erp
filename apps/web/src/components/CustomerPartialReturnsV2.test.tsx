import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { BudgetIdentity } from "../budget-control-data";
import { partialReturnPermissions, partialReturnsRoot, partialReturnsRootV2, type AnyPartialReturnPlan } from "../customer-partial-returns-data";
import { partialBalanceFixture, partialPlanFixture, partialScope } from "../customer-partial-returns-test-fixtures";
import { remainderBalanceFixture, remainderPlanFixture } from "../customer-partial-returns-v2-test-fixtures";
import CustomerPartialReturns from "./CustomerPartialReturns";

const session = { tenantId: "synthetic", csrfToken: "csrf", expiresAt: "2099-01-01T00:00:00Z" };
const state = { session, revision: 1, isCurrent: () => true, recover: vi.fn(() => false) };
vi.mock("../browserSession", () => ({ useBrowserSession: () => state }));
const identity: BudgetIdentity = { id: "poster", human: true, stepUp: true, workspaces: ["work"], organizations: ["org"], entities: ["entity"], permissions: [...new Set(Object.values(partialReturnPermissions).flat())] };
const onLock = vi.fn();
beforeEach(() => { onLock.mockReset(); state.recover.mockClear(); });
afterEach(() => vi.unstubAllGlobals());
async function select(plan: AnyPartialReturnPlan) {
  const selector = await screen.findByRole("combobox", { name: "Retained partial return, refund or reversal" });
  await waitFor(() => expect(selector.querySelectorAll("option")).toHaveLength(2));
  fireEvent.change(selector, { target: { value: plan.id } });
  await screen.findByRole("heading", { name: "Native invoice and refund balance" });
}
function reason() {
  fireEvent.change(within(screen.getByRole("form", { name: "Post partial cycle plan" })).getByLabelText("Partial cycle reason"), { target: { value: "Independent governed quantity effect" } });
}
it("posts a zero-leg quantity operation only on human action and retains the exact v2 command after a lost reply", async () => {
  const attempts: Array<{ path: string; body: string }> = []; let posted = false;
  vi.stubGlobal("fetch", vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    if (init?.method === "POST") {
      attempts.push({ path: String(url), body: String(init.body) });
      if (attempts.length === 1) throw new TypeError("Lost response after native commit");
      posted = true; return new Response(JSON.stringify({ plan: remainderPlanFixture("0", "0", 2) }));
    }
    if (String(url).endsWith("/balance")) return new Response(JSON.stringify({ balance: remainderBalanceFixture({ gross_minor: "1", outstanding_minor: "1", ...(posted ? { history_version: 1, returned_quantity_scaled: "1", remaining_quantity_scaled: "2" } : {}) }) }));
    return new Response(JSON.stringify({ plans: [remainderPlanFixture("0", "0", posted ? 2 : 1)] }));
  }));
  const view = render(<CustomerPartialReturns locale="en" scope={partialScope} identity={identity} onLockChange={onLock} protocolVersion={2} />);
  await select(remainderPlanFixture("0", "0"));
  expect(screen.getByText(/without creating a zero journal/)).toBeInTheDocument();
  expect(attempts).toHaveLength(0); reason(); fireEvent.click(screen.getByRole("button", { name: "Post partial cycle plan" }));
  await screen.findByRole("button", { name: "Retry retained partial command" });
  expect(onLock).toHaveBeenLastCalledWith(true); expect(attempts).toHaveLength(1);
  view.rerender(<CustomerPartialReturns locale="ar" scope={partialScope} identity={identity} onLockChange={onLock} protocolVersion={2} />);
  expect(screen.getByRole("heading", { name: "إرجاع العميل الجزئي مع حفظ البواقي" })).toBeInTheDocument();
  expect(screen.getByText(/دون إنشاء قيد صفري/)).toBeInTheDocument();
  expect(attempts).toHaveLength(1);
  fireEvent.click(screen.getByRole("button", { name: "إعادة الأمر الجزئي المحفوظ" }));
  await waitFor(() => expect(onLock).toHaveBeenLastCalledWith(false));
  expect(attempts).toHaveLength(2); expect(attempts[0]).toEqual(attempts[1]);
  expect(attempts[0].path).toBe(`${partialReturnsRootV2}/plans/${remainderPlanFixture().id}/post`);
  expect(screen.queryByText(/effect-0/)).not.toBeInTheDocument();
});
it("uses the original v1 route when a retained legacy plan is selected in the v2 read union", async () => {
  const attempts: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    if (init?.method === "POST") { attempts.push(String(url)); return new Response(JSON.stringify({ plan: partialPlanFixture(2) })); }
    return new Response(JSON.stringify(String(url).endsWith("/balance") ? { balance: partialBalanceFixture() } : { plans: [partialPlanFixture()] }));
  }));
  render(<CustomerPartialReturns locale="en" scope={partialScope} identity={identity} onLockChange={onLock} protocolVersion={2} />);
  await select(partialPlanFixture());
  expect(screen.getAllByText(/Legacy exact-portion policy/)).toHaveLength(2);
  reason(); fireEvent.click(screen.getByRole("button", { name: "Post partial cycle plan" }));
  await screen.findByText(/effect-0/);
  expect(attempts).toEqual([`${partialReturnsRoot}/plans/${partialPlanFixture().id}/post`]);
});
it("prepares a new v2 source without sending a caller-selected allocation rule or financial amount", async () => {
  const attempts: Array<{ path: string; body: Record<string, unknown> }> = [];
  vi.stubGlobal("fetch", vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    if (init?.method === "POST") { attempts.push({ path: String(url), body: JSON.parse(String(init.body)) }); return new Response(JSON.stringify({ plan: remainderPlanFixture("1000", "334", 0) })); }
    return new Response(JSON.stringify(String(url).endsWith("/balance") ? { balance: remainderBalanceFixture({ source_id: null }) } : { plans: [] }));
  }));
  render(<CustomerPartialReturns locale="en" scope={partialScope} identity={identity} onLockChange={onLock} protocolVersion={2} />);
  fireEvent.change(screen.getByLabelText("Partial return original stock order ID"), { target: { value: "stock-original" } });
  fireEvent.click(screen.getByRole("button", { name: "Load original source balance" }));
  const form = await screen.findByRole("form", { name: "Prepare partial original return" });
  for (const [label, value] of [["Return quantity in captured scaled units", "1"], ["Partial cycle fiscal period ID", "period"], ["Partial cycle posting date", "2026-10-15"], ["Refund cash journal code", "CASH"], ["Partial refund liability account", "REFUND"], ["Captured collection cash account", "CASH"], ["Partial cycle reason", "Original remaining portion"]]) fireEvent.change(within(form).getByLabelText(label), { target: { value } });
  fireEvent.click(within(form).getByRole("button")); await waitFor(() => expect(attempts).toHaveLength(1));
  expect(attempts[0].path).toBe(`${partialReturnsRootV2}/plans`);
  expect(attempts[0].body).toMatchObject({ quantity_scaled: "1", expected_history_version: 0, source_order_id: "stock-original" });
  for (const key of ["allocation_policy", "protocol_version", "credit_minor", "cogs_restored_minor", "actor_id", "legal_entity_id"]) expect(attempts[0].body).not.toHaveProperty(key);
});
it("retains a protocol-mismatched acknowledgement without resubmitting through another API version", async () => {
  const attempts: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    if (init?.method === "POST") { attempts.push(String(url)); return new Response(JSON.stringify({ plan: partialPlanFixture(2) })); }
    return new Response(JSON.stringify(String(url).endsWith("/balance") ? { balance: remainderBalanceFixture() } : { plans: [remainderPlanFixture()] }));
  }));
  render(<CustomerPartialReturns locale="en" scope={partialScope} identity={identity} onLockChange={onLock} protocolVersion={2} />);
  await select(remainderPlanFixture()); reason(); fireEvent.click(screen.getByRole("button", { name: "Post partial cycle plan" }));
  await screen.findByRole("button", { name: "Retry retained partial command" });
  expect(screen.getByRole("alert")).toHaveFocus(); expect(onLock).toHaveBeenLastCalledWith(true);
  expect(attempts).toEqual([`${partialReturnsRootV2}/plans/${remainderPlanFixture().id}/post`]);
});
