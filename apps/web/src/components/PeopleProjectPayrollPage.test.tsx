import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { loadBudgetIdentity } from "../budget-control-data";
import { peoplePlanFixture } from "../people-project-payroll-test-fixture";
import { PeopleProjectPayrollPage } from "./PeopleProjectPayrollPage";

const session = { tenantId: "synthetic", csrfToken: "csrf", expiresAt: "2099-01-01T00:00:00Z" };
vi.mock("../browserSession", () => ({ useBrowserSession: () => ({ session, revision: 1, username: "poster", isCurrent: () => true }) }));
vi.mock("../budget-control-data", () => ({ loadBudgetIdentity: vi.fn() }));
const identity = { id: "poster", human: true, stepUp: true, workspaces: ["work"], organizations: ["org"], entities: ["entity"], permissions: ["people_project_payroll.read", "people_project_payroll.read_sensitive", "people_project_payroll.review", "people_project_payroll.post", "finance_core.read", "finance_core.validate", "finance_core.post", "budget_control.read", "budget_control.manage"] };
afterEach(() => { vi.unstubAllGlobals(); vi.mocked(loadBudgetIdentity).mockReset(); });
async function selectPlan(plan: Record<string, unknown>, privateValue: unknown = plan) {
  vi.mocked(loadBudgetIdentity).mockResolvedValue(identity);
  vi.stubGlobal("fetch", vi.fn(async (url: unknown) => new Response(JSON.stringify(String(url).includes("/private") ? { plan: privateValue } : { items: String(url).includes("/payruns?") ? [{ id: plan.id, phase: plan.phase }] : [], has_more: false }))));
  render(<PeopleProjectPayrollPage locale="en" />);
  await waitFor(() => expect(screen.getByLabelText("Workspace ID")).toHaveValue("work"));
  fireEvent.click(screen.getByRole("button", { name: "Apply scope" }));
  const select = screen.getByRole("combobox", { name: "Financial source" });
  await waitFor(() => expect(select.querySelectorAll("option")).toHaveLength(2));
  fireEvent.change(select, { target: { value: plan.id } });
}
it("rejects corrupted private financial proof before exposing post action", async () => {
  const plan = await peoplePlanFixture(1);
  await selectPlan(plan, { ...plan, plan_digest: "0".repeat(64) });
  await screen.findByRole("alert");
  expect(screen.queryByRole("button", { name: "Post native GL effect" })).not.toBeInTheDocument();
});
it("retains exact lost post command and uses same command ID on retry", async () => {
  const source = await peoplePlanFixture(1), posted = await peoplePlanFixture(2), requests: string[] = [];
  await selectPlan(source);
  await screen.findByRole("button", { name: "Post native GL effect" });
  vi.stubGlobal("fetch", vi.fn(async (url: unknown, init?: RequestInit) => {
    if (init?.method === "POST") { requests.push(String(init.body)); if (requests.length === 1) throw new TypeError("lost synthetic response"); return new Response(JSON.stringify({ plan: posted })); }
    return new Response(JSON.stringify(String(url).includes("/private") ? { plan: posted } : { items: [], has_more: false }));
  }));
  fireEvent.click(screen.getByRole("button", { name: "Post native GL effect" }));
  fireEvent.click(await screen.findByRole("button", { name: "Retry same retained command" }));
  await waitFor(() => expect(requests).toHaveLength(2)); expect(requests[0]).toBe(requests[1]);
  await waitFor(() => expect(screen.queryByRole("button", { name: "Post native GL effect" })).not.toBeInTheDocument());
});
it("renders Arabic RTL and explicit statutory-zero boundary", () => {
  vi.mocked(loadBudgetIdentity).mockResolvedValue(identity);
  const view = render(<PeopleProjectPayrollPage locale="ar" />);
  expect(view.container.querySelector("main")).toHaveAttribute("dir", "rtl");
  expect(screen.getByText(/حزم الرواتب والضرائب القانونية المدعومة: صفر/)).toBeInTheDocument();
});
