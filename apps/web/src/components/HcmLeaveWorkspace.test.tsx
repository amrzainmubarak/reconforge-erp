import { act, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { authorize, click, renderWorkspace, respond, session, setField } from "../test/enterpriseWorkflowSupport";
import { HcmLeaveWorkspace } from "./HcmLeaveWorkspace";

const saved = { request_id: "REQ-SOURCE-1", employee_id: "EMP-SOURCE-1", employee_user_id: "source-owner", leave_type: "Annual", start_date: "2026-11-01", end_date: "2026-11-03", requested_days: 3, status: "Submitted", reason: "Synthetic regression" };
beforeEach(() => vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("Unexpected request"))));
afterEach(() => vi.unstubAllGlobals());
function ready() { renderWorkspace(<HcmLeaveWorkspace locale="en" />); authorize(); setField("Request ID", saved.request_id); }

describe("HCM actual API workflows", () => {
  it.each(["en", "ar"] as const)("starts empty with accessible controls in %s", locale => {
    const { container } = renderWorkspace(<HcmLeaveWorkspace locale={locale} />);
    expect(container.querySelector(".financial-reporting")).toHaveAttribute("dir", locale === "ar" ? "rtl" : "ltr");
    expect(screen.queryByText("LR-2026-001")).not.toBeInTheDocument();
    expect(screen.queryByText("EMP-1001")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: locale === "en" ? "Approve request" : "اعتماد الطلب" })).toBeDisabled();
    expect(fetch).not.toHaveBeenCalled();
  });
  it("loads persisted request using the current tenant and complete business scope", async () => {
    const fetcher = respond(saved); ready(); await click("Load request");
    expect(fetcher.mock.calls[0]).toMatchObject(["/api/v1/hcm/leave/requests/REQ-SOURCE-1", { method: "GET", credentials: "same-origin", cache: "no-store", headers: { "X-ReconForge-Tenant": session.tenantId, "X-ReconForge-Workspace": "synthetic-workspace", "X-ReconForge-Organization": "synthetic-organization", "X-ReconForge-Legal-Entity": "synthetic-entity" } }]);
    expect(screen.getByText("source-owner")).toBeInTheDocument(); expect(screen.getByText("Submitted")).toBeInTheDocument();
  });
  it("submits the explicit source ID and day count without forging an employee user identity", async () => {
    const fetcher = respond({ status: "success", request_id: saved.request_id, leave_status: "Submitted" }); ready();
    setField("Employee ID", saved.employee_id); setField("Start date", saved.start_date); setField("End date", saved.end_date); setField("Requested days", "3"); setField("Reason", saved.reason);
    await click("Submit request");
    const [path, init] = fetcher.mock.calls[0] as [string, RequestInit];
    expect(path).toBe("/api/v1/hcm/leave/requests");
    expect(init.headers).toMatchObject({ "X-ReconForge-CSRF": session.csrfToken });
    expect(JSON.parse(init.body as string)).toEqual({ request_id: saved.request_id, employee_id: saved.employee_id, leave_type: "Annual", start_date: saved.start_date, end_date: saved.end_date, requested_days: 3, reason: saved.reason });
    expect(screen.getByText("Submitted")).toBeInTheDocument();
  });
  it.each([["Approve request", "approve", "Approved"], ["Withdraw own request", "withdraw", "Cancelled"]])("%s uses server authority and confirms only the returned transition", async (button, action, status) => {
    const fetcher = respond({ status: "success", request_id: saved.request_id, leave_status: status }); ready(); await click(button);
    const [path, init] = fetcher.mock.calls[0] as [string, RequestInit];
    expect(path).toBe(`/api/v1/hcm/leave/requests/${saved.request_id}/${action}`); expect(JSON.parse(init.body as string)).toEqual({});
    expect(screen.getByText(status)).toBeInTheDocument(); expect(screen.queryByLabelText("Approver User ID")).not.toBeInTheDocument();
  });
  it("loads the persisted balance instead of decrementing a local balance on approval", async () => {
    const fetcher = respond({ employee_id: saved.employee_id, leave_type: "Annual", accrued_days: 27, consumed_days: 4, available_days: 23 }); ready(); setField("Employee ID", saved.employee_id); await click("Load entitlement balance");
    expect(fetcher.mock.calls[0][0]).toBe(`/api/v1/hcm/leave/balances/${saved.employee_id}/Annual`); expect(screen.getByText("23")).toBeInTheDocument();
  });
  it.each([401, 403, 409, 422, 503])("HTTP %s cannot produce a successful approval", async status => {
    respond({ error: { code: "permission_denied", message: "private diagnostic" } }, status); ready(); await click("Approve request");
    expect(screen.queryByText("Approved")).not.toBeInTheDocument(); expect(screen.queryByText("private diagnostic")).not.toBeInTheDocument(); expect(screen.queryByRole("region", { name: "Verified server response" })).not.toBeInTheDocument();
    if (status !== 401) expect(screen.getByRole("alert")).toHaveTextContent("There is no confirmed result");
  });
  it.each([{ ...saved, request_id: "OTHER-REQUEST" }, { ...saved, requested_days: true }, { ...saved, requested_days: Number.MAX_SAFE_INTEGER + 1 }, { status: "success" }])("rejects malformed or mismatched source data %#", async value => {
    respond(value); ready(); await click("Load request"); expect(screen.getByRole("alert")).toBeInTheDocument(); expect(screen.queryByRole("region", { name: "Verified server response" })).not.toBeInTheDocument();
  });
  it("removes prior private data when the workspace changes", async () => {
    respond(saved); ready(); await click("Load request"); expect(screen.getByText("source-owner")).toBeInTheDocument(); setField("Workspace ID", "different-workspace"); expect(screen.queryByText("source-owner")).not.toBeInTheDocument();
  });
  it("does not publish a delayed prior-workspace response under a new scope", async () => {
    let complete!: (response: Response) => void;
    vi.stubGlobal("fetch", vi.fn().mockImplementation(() => new Promise<Response>(resolve => { complete = resolve; })));
    ready(); await click("Load request"); setField("Workspace ID", "different-workspace");
    await act(async () => complete(new Response(JSON.stringify(saved))));
    expect(screen.queryByText("source-owner")).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Verified server response" })).not.toBeInTheDocument();
  });
  it("does not publish a delayed server result after logout", async () => {
    let complete!: (response: Response) => void;
    vi.stubGlobal("fetch", vi.fn().mockImplementation(() => new Promise<Response>(resolve => { complete = resolve; })));
    ready(); await click("Load request"); await click("End test session");
    await act(async () => complete(new Response(JSON.stringify(saved))));
    expect(screen.queryByText("source-owner")).not.toBeInTheDocument(); expect(screen.getByRole("button", { name: "Approve request" })).toBeDisabled();
  });
  it("a superseded error body cannot revoke the session after a successor request succeeds", async () => {
    let complete!: (value: unknown) => void;
    const fetcher = vi.fn().mockResolvedValueOnce({ ok: false, status: 401, json: () => new Promise(resolve => { complete = resolve; }) })
      .mockResolvedValueOnce(new Response(JSON.stringify({ ...saved, request_id: "REQ-SOURCE-2" })));
    vi.stubGlobal("fetch", fetcher);
    ready(); await click("Load request"); setField("Request ID", "REQ-SOURCE-2"); await click("Load request");
    expect(screen.getByText("source-owner")).toBeInTheDocument();
    await act(async () => complete({ error: { code: "csrf_required" } }));
    expect(screen.getByText("source-owner")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Approve request" })).toBeEnabled();
  });
});
