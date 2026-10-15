import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { loadBudgetIdentity } from "../budget-control-data";
import { returnFixture } from "../customer-returns-test-fixtures";
import { partialBalanceFixture, partialPlanFixture } from "../customer-partial-returns-test-fixtures";
import * as apiData from "../data";
import CustomerReturnsPage from "./CustomerReturnsPage";
const session = { tenantId: "synthetic", csrfToken: "csrf", expiresAt: "2099-01-01T00:00:00Z" };
const state = { session, revision: 1, username: "poster", isCurrent: () => true, recover: () => false, elevate: vi.fn() };
vi.mock("../browserSession", () => ({ useBrowserSession: () => state }));
const identity = { id: "poster", human: true, stepUp: true, workspaces: ["work"], organizations: ["org"], entities: ["entity"], permissions: ["sales.read", "receivables.read", "inventory.read", "finance_core.read", "sales.manage", "receivables.manage", "inventory.post", "inventory.valuation.approve", "finance_core.post", "finance_core.reverse", "sales.approve", "finance_core.validate"] };
vi.mock("../budget-control-data", () => ({ loadBudgetIdentity: vi.fn(async () => identity) }));
afterEach(() => vi.unstubAllGlobals());
async function enter() {
  await waitFor(() => expect(screen.getByLabelText("Workspace ID")).toHaveValue("work"));
  fireEvent.click(screen.getByRole("button", { name: "Apply scope" }));
  const select = await screen.findByRole("combobox", { name: "Retained credit or refund" });
  await waitFor(() => expect(select.querySelectorAll("option")).toHaveLength(2));
  fireEvent.change(select, { target: { value: returnFixture().id } });
}
it("keeps scope edits disabled through deferred identity prefill then preserves staged valid user scope", async () => {
  let resolveIdentity!: (value: typeof identity) => void;
  const deferred = new Promise<typeof identity>(resolve => { resolveIdentity = resolve; });
  vi.mocked(loadBudgetIdentity).mockImplementationOnce(() => deferred);
  const requests = vi.fn(async () => new Response(JSON.stringify({ plans: [] })));
  vi.stubGlobal("fetch", requests);
  render(<CustomerReturnsPage locale="en" />);
  const fields = ["Workspace ID", "Organization ID", "Legal entity ID"].map(label => screen.getByLabelText(label));
  for (const field of fields) { expect(field).toBeDisabled(); expect(field).toHaveValue(""); }
  expect(screen.getByRole("button", { name: "Apply scope" })).toBeDisabled();
  expect(requests).not.toHaveBeenCalled();
  await act(async () => resolveIdentity({ ...identity, workspaces: ["initial-work", "work"], organizations: ["initial-org", "org"], entities: ["initial-entity", "entity"] }));
  for (const [index, value] of ["initial-work", "initial-org", "initial-entity"].entries()) {
    expect(fields[index]).toBeEnabled(); expect(fields[index]).toHaveValue(value);
  }
  expect(screen.getByRole("button", { name: "Apply scope" })).toBeEnabled();
  act(() => {
    for (const [index, value] of ["work", "org", "entity"].entries()) fireEvent.change(fields[index], { target: { value } });
  });
  for (const [index, value] of ["work", "org", "entity"].entries()) expect(fields[index]).toHaveValue(value);
  fireEvent.click(screen.getByRole("button", { name: "Apply scope" }));
  await waitFor(() => expect(requests).toHaveBeenCalledTimes(1));
  expect(requests).toHaveBeenCalledWith("/api/v1/customer-returns/plans", expect.objectContaining({ method: "GET", headers: expect.objectContaining({ "X-ReconForge-Workspace": "work", "X-ReconForge-Organization": "org", "X-ReconForge-Legal-Entity": "entity" }) }));
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});
it("keeps exact retained command on lost ACK then preserves successful post evidence when follow-up list fails", async () => {
  const attempts: string[] = []; let acknowledged = false;
  vi.stubGlobal("fetch", vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    if (init?.method === "POST") {
      attempts.push(String(init.body)); if (attempts.length === 1) throw new TypeError("lost committed ACK");
      acknowledged = true; return new Response(JSON.stringify({ plan: returnFixture(2) }));
    }
    if (String(url).includes("/balance")) return new Response(JSON.stringify({ balance: { return_id: returnFixture().id, plan_digest: returnFixture().plan_digest, credit_minor: returnFixture().credit_minor, refund_entitlement_minor: "0", refunded_minor: "0", refund_due_minor: "0" } }));
    return acknowledged ? new Response("unavailable", { status: 503 }) : new Response(JSON.stringify({ plans: [returnFixture()] }));
  }));
  render(<CustomerReturnsPage locale="en" />); await enter();
  fireEvent.change(screen.getByLabelText("Reason"), { target: { value: "Independent post" } });
  fireEvent.click(screen.getByRole("button", { name: "Post complete native effect" }));
  fireEvent.click(await screen.findByRole("button", { name: "Retry retained command" }));
  await waitFor(() => expect(attempts).toHaveLength(2)); expect(attempts[0]).toBe(attempts[1]);
  await screen.findByText(/effect-C/);
  expect(screen.queryByRole("button", { name: "Post complete native effect" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Cancel unposted plan" })).not.toBeInTheDocument();
});
it("renders the native return boundary in Arabic RTL", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ plans: [] }))));
  const view = render(<CustomerReturnsPage locale="ar" />);
  expect(view.container.querySelector("main")).toHaveAttribute("dir", "rtl");
  expect(screen.getByRole("heading", { name: "إرجاع العميل الأصلي وردّ النقد على دفعات" })).toBeInTheDocument();
  await waitFor(() => expect(screen.getByLabelText("معرّف مساحة العمل")).toHaveValue("work"));
});
it("retains a partial command across the whole-source workspace and scope controls after response loss", async () => {
  const attempts: string[] = []; let posted = false;
  vi.stubGlobal("fetch", vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    if (init?.method === "POST") { attempts.push(String(init.body)); if (attempts.length === 1) throw new TypeError("lost partial ACK"); posted = true; return new Response(JSON.stringify({ plan: partialPlanFixture(2) })); }
    if (String(url).includes("/customer-partial-returns/sources/")) return new Response(JSON.stringify({ balance: posted ? partialBalanceFixture() : partialBalanceFixture({ history_version: 0, credited_minor: "0", returned_quantity_scaled: "0", remaining_quantity_scaled: "15", outstanding_minor: "57500" }) }));
    return new Response(JSON.stringify({ plans: String(url).includes("/customer-partial-returns/") ? [partialPlanFixture()] : [] }));
  }));
  render(<CustomerReturnsPage locale="en" />);
  await waitFor(() => expect(screen.getByLabelText("Workspace ID")).toHaveValue("work"));
  fireEvent.click(screen.getByRole("button", { name: "Apply scope" }));
  fireEvent.click(await screen.findByRole("button", { name: "Partial return cycle" }));
  const selector = await screen.findByRole("combobox", { name: "Retained partial return, refund or reversal" });
  await waitFor(() => expect(selector.querySelectorAll("option")).toHaveLength(2));
  fireEvent.change(selector, { target: { value: partialPlanFixture().id } });
  await screen.findByRole("heading", { name: "Native invoice and refund balance" });
  fireEvent.change(screen.getByLabelText("Partial cycle reason"), { target: { value: "Independent post" } });
  fireEvent.click(screen.getByRole("button", { name: "Post partial cycle plan" }));
  const retry = await screen.findByRole("button", { name: "Retry retained partial command" });
  for (const name of ["Whole original tranche", "Partial return cycle", "Apply scope", "Sign out"]) expect(screen.getByRole("button", { name })).toBeDisabled();
  for (const label of ["Workspace ID", "Organization ID", "Legal entity ID"]) expect(screen.getByLabelText(label)).toBeDisabled();
  fireEvent.click(retry); await screen.findByText(/effect-0/); expect(attempts).toHaveLength(2); expect(attempts[0]).toBe(attempts[1]);
  expect(screen.getByRole("button", { name: "Whole original tranche" })).toBeEnabled();
  fireEvent.click(screen.getByRole("button", { name: "Whole original tranche" }));
  expect(await screen.findByRole("combobox", { name: "Retained credit or refund" })).toBeInTheDocument();
});
it("allows explicit authority re-verification and refreshes the shared assurance without financial commands", async () => {
  const stepUp = vi.spyOn(apiData, "stepUpBrowserAdminSession").mockResolvedValueOnce("2099-01-01T00:00:00Z");
  const requests = vi.fn(async () => new Response(JSON.stringify({ plans: [] }))); vi.stubGlobal("fetch", requests);
  render(<CustomerReturnsPage locale="en" />);
  await waitFor(() => expect(screen.getByRole("button", { name: "Verify financial authority" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "Verify financial authority" }));
  fireEvent.change(screen.getByLabelText("Password"), { target: { value: "synthetic-only" } });
  fireEvent.click(screen.getByRole("button", { name: "Verify financial authority" }));
  await waitFor(() => expect(state.elevate).toHaveBeenCalledWith("2099-01-01T00:00:00Z", 1));
  expect(stepUp).toHaveBeenCalledWith(session, "synthetic-only"); expect(screen.queryByLabelText("Password")).not.toBeInTheDocument(); expect(requests).not.toHaveBeenCalled();
});
