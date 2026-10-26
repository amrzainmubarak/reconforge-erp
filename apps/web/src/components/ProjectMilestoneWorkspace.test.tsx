import { screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { authorize, click, renderWorkspace, respond, session, setField } from "../test/enterpriseWorkflowSupport";
import { ProjectMilestoneWorkspace } from "./ProjectMilestoneWorkspace";

const digest = "b".repeat(64);
const financialBinding = { binding_id: "BIND-SOURCE", source_kind: "ProjectMilestone", source_id: "INV-SOURCE", phase: "Draft", entry_id: "FINANCE-ENTRY-SOURCE", source_digest: digest, amount_minor: "9007199254740993", currency_code: "KWD", currency_precision: 3 };
beforeEach(() => vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("Unexpected request"))));
afterEach(() => vi.unstubAllGlobals());
function ready() { renderWorkspace(<ProjectMilestoneWorkspace locale="en" />); authorize(); setField("Milestone ID", "MS-SOURCE"); }
function context() { setField("Invoice ID", "INV-SOURCE"); setField("Issue timestamp (UTC)", "2026-10-25T00:00:00Z"); setField("Customer code", "CUSTOMER"); setField("Organization code", "ORG"); setField("Entity code", "ENTITY"); setField("Fiscal period ID", "PERIOD"); setField("Posting date", "2026-10-25"); setField("Journal code", "SALES"); setField("Command ID (reuse for retry)", "CMD-PREPARE-1"); }
function phase() { setField("Financial binding ID", "BIND-SOURCE"); setField("Expected source digest", digest); setField("Command ID (reuse for retry)", "CMD-PHASE-1"); }

describe("Project milestone authoritative financial workflows", () => {
  it.each(["en", "ar"] as const)("starts without fabricated financial posture in %s", locale => {
    const { container } = renderWorkspace(<ProjectMilestoneWorkspace locale={locale} />);
    expect(container.querySelector(".financial-reporting")).toHaveAttribute("dir", locale === "ar" ? "rtl" : "ltr"); expect(screen.queryByText("$500,000.00")).not.toBeInTheDocument(); expect(screen.queryByText("MLS-03")).not.toBeInTheDocument(); expect(screen.queryByText("INV-2026-042")).not.toBeInTheDocument(); expect(fetch).not.toHaveBeenCalled();
  });
  it("loads original WBS tasks and preserves the currency and integer amounts", async () => {
    const fetcher = respond({ project_id: "PROJECT", tasks: [{ task_id: "TASK-SOURCE", task_code: "1.1", name: "Saved task", status: "in_progress", budget_cost_minor: 41001, currency: "JPY" }] }); ready(); setField("Project ID", "PROJECT"); await click("Load WBS tasks");
    expect(fetcher.mock.calls[0][0]).toBe("/api/v1/projects/billing/tasks/PROJECT"); expect(screen.getByText("1.1 — Saved task")).toBeInTheDocument(); expect(screen.getByText("41001")).toBeInTheDocument(); expect(screen.getByText("JPY")).toBeInTheDocument();
  });
  it("loads operational source totals without claiming canonical posted balances", async () => {
    respond({ project_id: "PROJECT", currency: "KWD", budget_cost_minor: 40123, actual_cost_minor: 2011, total_billed_minor: 1234, unbilled_wip_minor: 543 }); ready(); setField("Project ID", "PROJECT"); setField("Reporting currency", "KWD"); await click("Load source billing summary"); expect(screen.getByText("1234")).toBeInTheDocument(); expect(screen.getByText(/source summary is operational/)).toBeInTheDocument(); expect(screen.queryByText("Real-Time Financial Posture")).not.toBeInTheDocument();
  });
  it("verifies a deliverable using the authenticated actor instead of a hardcoded approver", async () => {
    const fetcher = respond({ status: "verified", milestone_id: "MS-SOURCE", verified_by: "server-reviewer" }); ready(); await click("Verify deliverable"); expect(fetcher.mock.calls[0][0]).toBe("/api/v1/projects/billing/milestones/MS-SOURCE/verify"); expect(JSON.parse(fetcher.mock.calls[0][1].body)).toEqual({}); expect(screen.getByText("server-reviewer")).toBeInTheDocument();
  });
  it("prepares an exact Finance Core draft with period, source and retry identity", async () => {
    const fetcher = respond({ status: "prepared", invoice_id: "INV-SOURCE", financial_binding: financialBinding }); ready(); context(); await click("Prepare invoice draft");
    const [path, init] = fetcher.mock.calls[0] as [string, RequestInit]; expect(path).toBe("/api/v1/projects/billing/milestones/MS-SOURCE/bill"); expect(init.headers).toMatchObject({ "X-ReconForge-CSRF": session.csrfToken, "X-ReconForge-Workspace": "synthetic-workspace", "X-ReconForge-Organization": "synthetic-organization", "X-ReconForge-Legal-Entity": "synthetic-entity" }); expect(JSON.parse(init.body as string)).toEqual({ invoice_id: "INV-SOURCE", issued_at: "2026-10-25T00:00:00Z", customer_code: "CUSTOMER", financial_context: { command_id: "CMD-PREPARE-1", organization_code: "ORG", entity_code: "ENTITY", period_id: "PERIOD", posting_date: "2026-10-25", journal_code: "SALES" } }); expect(screen.getByText("Draft")).toBeInTheDocument(); expect(screen.getByText("FINANCE-ENTRY-SOURCE")).toBeInTheDocument(); expect(screen.getByText("9007199254740993")).toBeInTheDocument(); expect(screen.queryByText("Posted")).not.toBeInTheDocument();
  });
  it.each([["Review financial draft", "review", "Reviewed"], ["Post reviewed entry", "post", "Posted"]])("%s requires an explicit unchanged source digest and idempotency key", async (button, action, state) => {
    const fetcher = respond({ ...financialBinding, phase: state }); ready(); phase(); await click(button); expect(fetcher.mock.calls[0][0]).toBe(`/api/v1/projects/billing/finance/BIND-SOURCE/${action}`); expect(JSON.parse(fetcher.mock.calls[0][1].body)).toEqual({ command_id: "CMD-PHASE-1", expected_source_digest: digest }); expect(screen.getByText(state)).toBeInTheDocument();
  });
  it("prepares a reversal draft without claiming the inverse has posted", async () => {
    const fetcher = respond({ ...financialBinding, binding_id: "REVERSAL-SOURCE", source_kind: "Reversal", source_id: "BIND-SOURCE", phase: "Draft" }); ready(); context(); phase(); setField("Reversal reason", "Synthetic correction"); await click("Prepare reversal draft"); expect(fetcher.mock.calls[0][0]).toBe("/api/v1/projects/billing/finance/BIND-SOURCE/reversal"); expect(JSON.parse(fetcher.mock.calls[0][1].body)).toEqual({ command_id: "CMD-PHASE-1", expected_source_digest: digest, period_id: "PERIOD", posting_date: "2026-10-25", reason: "Synthetic correction" }); expect(screen.getByText("Draft")).toBeInTheDocument(); expect(screen.queryByText("Posted")).not.toBeInTheDocument();
  });
  it.each([401, 403, 409, 422, 503])("refused invoice preparation HTTP %s creates no local invoice reference or totals", async status => {
    respond({ error: { code: "financial_refused", message: "private database diagnostic" } }, status); ready(); context(); await click("Prepare invoice draft"); expect(screen.queryByRole("region", { name: "Verified server response" })).not.toBeInTheDocument(); expect(screen.queryByText("FINANCE-ENTRY-SOURCE")).not.toBeInTheDocument(); expect(screen.queryByText("private database diagnostic")).not.toBeInTheDocument(); expect(screen.queryByText("$400,000.00")).not.toBeInTheDocument();
  });
  it("rejects a false Posted prepare result rather than upgrading the financial phase", async () => {
    respond({ status: "prepared", invoice_id: "INV-SOURCE", financial_binding: { ...financialBinding, phase: "Posted" } }); ready(); context(); await click("Prepare invoice draft"); expect(screen.getByRole("alert")).toBeInTheDocument(); expect(screen.queryByText("Posted")).not.toBeInTheDocument();
  });
  it("rejects a source binding from an unrelated adapter", async () => {
    respond({ ...financialBinding, source_kind: "IntercompanyProfitInStock" }); ready(); phase(); await click("Load financial binding"); expect(screen.getByRole("alert")).toBeInTheDocument(); expect(screen.queryByText("FINANCE-ENTRY-SOURCE")).not.toBeInTheDocument();
  });
});
