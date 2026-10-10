import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { loadBudgetIdentity } from "../budget-control-data";
import { returnFixture } from "../customer-returns-test-fixtures";
import CustomerReturnsPage from "./CustomerReturnsPage";
const session = { tenantId: "synthetic", csrfToken: "csrf", expiresAt: "2099-01-01T00:00:00Z" };
const state = { session, revision: 1, username: "poster", isCurrent: () => true, recover: () => false };
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
it("renders the native return boundary in Arabic RTL", () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ plans: [] }))));
  const view = render(<CustomerReturnsPage locale="ar" />);
  expect(view.container.querySelector("main")).toHaveAttribute("dir", "rtl");
  expect(screen.getByRole("heading", { name: "إرجاع العميل الأصلي وردّ النقد على دفعات" })).toBeInTheDocument();
});
