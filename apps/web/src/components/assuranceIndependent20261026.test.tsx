import { act, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { authorize, click, renderWorkspace, respond, setField } from "../test/enterpriseWorkflowSupport";
import { HcmLeaveWorkspace } from "./HcmLeaveWorkspace";
import { CrmSubscriptionWorkspace } from "./CrmSubscriptionWorkspace";
import { ProjectMilestoneWorkspace } from "./ProjectMilestoneWorkspace";

afterEach(() => vi.unstubAllGlobals());

it("invalidates a balance when the selected employee changes", async () => {
  respond({ employee_id: "EMP-A", leave_type: "Annual", accrued_days: 27, consumed_days: 4, available_days: 23 });
  renderWorkspace(<HcmLeaveWorkspace locale="en" />); authorize();
  setField("Employee ID", "EMP-A"); await click("Load entitlement balance");
  expect(screen.getByRole("region", { name: "Verified server response" })).toBeInTheDocument();
  setField("Employee ID", "EMP-B");
  expect(screen.queryByRole("region", { name: "Verified server response" })).not.toBeInTheDocument();
});

it("invalidates a project summary when its reporting currency changes", async () => {
  respond({ project_id: "PROJECT-A", currency: "KWD", budget_cost_minor: 1000, actual_cost_minor: 200, total_billed_minor: 300, unbilled_wip_minor: 100 });
  renderWorkspace(<ProjectMilestoneWorkspace locale="en" />); authorize();
  setField("Project ID", "PROJECT-A"); setField("Reporting currency", "KWD"); await click("Load source billing summary");
  expect(screen.getByRole("region", { name: "Verified server response" })).toBeInTheDocument();
  setField("Reporting currency", "JPY");
  expect(screen.queryByRole("region", { name: "Verified server response" })).not.toBeInTheDocument();
});

it("cannot publish an Annual balance after the selection changes to Sick", async () => {
  let complete!: (response: Response) => void;
  vi.stubGlobal("fetch", vi.fn().mockImplementation(() => new Promise<Response>(resolve => { complete = resolve; })));
  renderWorkspace(<HcmLeaveWorkspace locale="en" />); authorize(); setField("Employee ID", "EMP-A");
  await click("Load entitlement balance"); setField("Leave type", "Sick");
  await act(async () => complete(new Response(JSON.stringify({ employee_id: "EMP-A", leave_type: "Annual", accrued_days: 27, consumed_days: 4, available_days: 23 }))));
  expect(screen.queryByRole("region", { name: "Verified server response" })).not.toBeInTheDocument();
});

it("invalidates a proration quote when its effective date changes", async () => {
  respond({ status: "success", old_plan_id: "OLD", new_plan_id: "NEW", unearned_credit_minor: 333, new_charge_minor: 555, net_payable_minor: 222, currency: "KWD" });
  renderWorkspace(<CrmSubscriptionWorkspace locale="en" />); authorize();
  setField("Current plan ID", "OLD"); setField("New plan ID", "NEW");
  setField("Period start", "2026-10-01"); setField("Period end", "2026-10-31"); setField("Change date", "2026-10-15");
  await click("Calculate from saved plans");
  expect(screen.getByRole("region", { name: "Verified server response" })).toBeInTheDocument();
  setField("Change date", "2026-10-20");
  expect(screen.queryByRole("region", { name: "Verified server response" })).not.toBeInTheDocument();
});

it("does not publish a delayed proration amount after plan selection changes", async () => {
  let complete!: (response: Response) => void;
  vi.stubGlobal("fetch", vi.fn().mockImplementation(() => new Promise<Response>(resolve => { complete = resolve; })));
  renderWorkspace(<CrmSubscriptionWorkspace locale="en" />); authorize();
  setField("Current plan ID", "OLD"); setField("New plan ID", "NEW");
  setField("Period start", "2026-10-01"); setField("Period end", "2026-10-31"); setField("Change date", "2026-10-15");
  await click("Calculate from saved plans"); setField("New plan ID", "OTHER");
  await act(async () => complete(new Response(JSON.stringify({ status: "success", old_plan_id: "OLD", new_plan_id: "NEW", unearned_credit_minor: 333, new_charge_minor: 555, net_payable_minor: 222, currency: "KWD" }))));
  expect(screen.queryByRole("region", { name: "Verified server response" })).not.toBeInTheDocument();
});

it("does not publish a delayed project summary after reporting currency changes", async () => {
  let complete!: (response: Response) => void;
  vi.stubGlobal("fetch", vi.fn().mockImplementation(() => new Promise<Response>(resolve => { complete = resolve; })));
  renderWorkspace(<ProjectMilestoneWorkspace locale="en" />); authorize();
  setField("Project ID", "PROJECT-A"); setField("Reporting currency", "KWD"); await click("Load source billing summary");
  setField("Reporting currency", "JPY");
  await act(async () => complete(new Response(JSON.stringify({ project_id: "PROJECT-A", currency: "KWD", budget_cost_minor: 1000, actual_cost_minor: 200, total_billed_minor: 300, unbilled_wip_minor: 100 }))));
  expect(screen.queryByRole("region", { name: "Verified server response" })).not.toBeInTheDocument();
});
