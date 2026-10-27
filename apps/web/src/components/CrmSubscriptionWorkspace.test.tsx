import { screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { authorize, click, renderWorkspace, respond, session, setField } from "../test/enterpriseWorkflowSupport";
import { CrmSubscriptionWorkspace } from "./CrmSubscriptionWorkspace";

beforeEach(() => vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("Unexpected request"))));
afterEach(() => vi.unstubAllGlobals());
function ready() { renderWorkspace(<CrmSubscriptionWorkspace locale="en" />); authorize(); }
describe("CRM server-backed workflow integrity", () => {
  it.each(["en", "ar"] as const)("renders an empty accessible workspace in %s", locale => {
    const { container } = renderWorkspace(<CrmSubscriptionWorkspace locale={locale} />);
    expect(container.querySelector(".financial-reporting")).toHaveAttribute("dir", locale === "ar" ? "rtl" : "ltr");
    expect(screen.queryByText("Apex Global LLC")).not.toBeInTheDocument(); expect(screen.queryByText("Nordic Tech AB")).not.toBeInTheDocument(); expect(screen.queryByText("QUO-801")).not.toBeInTheDocument(); expect(fetch).not.toHaveBeenCalled();
  });
  it("loads a genuine opportunity without inventing stage changes", async () => {
    const fetcher = respond({ opportunity_id: "OP-SOURCE", title: "Saved opportunity", stage: "qualified", currency: "KWD", projected_amount_minor: 12345, weighted_pipeline_value_minor: 4567 }); ready(); setField("Opportunity ID", "OP-SOURCE"); await click("Load opportunity");
    expect(fetcher.mock.calls[0][0]).toBe("/api/v1/crm/contracts/opportunities/OP-SOURCE"); expect(screen.getByText("Saved opportunity")).toBeInTheDocument(); expect(screen.getByText("KWD")).toBeInTheDocument(); expect(screen.getByText("12345")).toBeInTheDocument(); expect(screen.queryByRole("button", { name: /Advance Stage/ })).not.toBeInTheDocument();
  });
  it("loads the quotation source owner and exact minor units", async () => {
    respond({ quote_id: "Q-SOURCE", customer_id: "C-SOURCE", submitter_user_id: "source-maker", status: "Draft", currency: "JPY", total_net_minor: 987, effective_discount_bps: 2000 }); ready(); setField("Quotation ID", "Q-SOURCE"); await click("Load quotation"); expect(screen.getByText("source-maker")).toBeInTheDocument(); expect(screen.getByText("987")).toBeInTheDocument();
  });
  it("submits an approval request without accepting a forged reviewer identity", async () => {
    const fetcher = respond({ status: "success", quote_id: "Q-SOURCE", quote_status: "approved", approved_by: "server-reviewer" }); ready(); setField("Quotation ID", "Q-SOURCE"); setField("Requested approval role", "cfo"); await click("Approve quotation");
    const [path, init] = fetcher.mock.calls[0] as [string, RequestInit]; expect(path).toBe("/api/v1/crm/contracts/quotations/Q-SOURCE/approve"); expect(JSON.parse(init.body as string)).toEqual({ approver_role: "cfo" }); expect(init.headers).toMatchObject({ "X-ReconForge-CSRF": session.csrfToken }); expect(screen.getByText("server-reviewer")).toBeInTheDocument();
  });
  it.each([403, 409, 422, 503])("server rejection %s never approves a quotation locally", async status => {
    respond({ error: { code: "quotation_role_denied" } }, status); ready(); setField("Quotation ID", "Q-SOURCE"); await click("Approve quotation"); expect(screen.getByRole("alert")).toBeInTheDocument(); expect(screen.queryByText("approved")).not.toBeInTheDocument();
  });
  it("suspends and resumes only after the persisted server response", async () => {
    const fetcher = respond({ status: "success", contract_id: "C-SOURCE", contract_status: "suspended" }); ready(); setField("Contract ID", "C-SOURCE"); setField("Suspension reason", "Synthetic acceptance"); await click("Suspend contract");
    expect(fetcher.mock.calls[0][0]).toBe("/api/v1/crm/contracts/contracts/C-SOURCE/suspend"); expect(JSON.parse(fetcher.mock.calls[0][1].body)).toEqual({ reason: "Synthetic acceptance" }); expect(screen.getByText("suspended")).toBeInTheDocument();
    fetcher.mockResolvedValueOnce(new Response(JSON.stringify({ status: "success", contract_id: "C-SOURCE", contract_status: "active" }))); await click("Resume contract"); expect(screen.getByText("active")).toBeInTheDocument(); expect(screen.queryByText("suspended")).not.toBeInTheDocument();
  });
  it("calculates proration using saved plans on the server, preserving currency and exact returned amounts", async () => {
    const fetcher = respond({ status: "success", old_plan_id: "PLAN-OLD", new_plan_id: "PLAN-NEW", unearned_credit_minor: 333, new_charge_minor: 555, net_payable_minor: 222, currency: "KWD" }); ready(); setField("Current plan ID", "PLAN-OLD"); setField("New plan ID", "PLAN-NEW"); setField("Period start", "2026-10-01"); setField("Period end", "2026-10-31"); setField("Change date", "2026-10-15"); await click("Calculate from saved plans");
    expect(fetcher.mock.calls[0][0]).toBe("/api/v1/crm/contracts/subscriptions/proration"); expect(JSON.parse(fetcher.mock.calls[0][1].body)).toEqual({ old_plan_id: "PLAN-OLD", new_plan_id: "PLAN-NEW", period_start: "2026-10-01", period_end: "2026-10-31", change_date: "2026-10-15" }); expect(screen.getByText("222")).toBeInTheDocument(); expect(screen.getByText("KWD")).toBeInTheDocument();
  });
  it("refuses mismatched quotation IDs instead of displaying another source", async () => {
    respond({ status: "success", quote_id: "OTHER-QUOTE", quote_status: "approved", approved_by: "server-reviewer" }); ready(); setField("Quotation ID", "Q-SOURCE"); await click("Approve quotation"); expect(screen.getByRole("alert")).toBeInTheDocument(); expect(screen.queryByText("server-reviewer")).not.toBeInTheDocument();
  });
});
