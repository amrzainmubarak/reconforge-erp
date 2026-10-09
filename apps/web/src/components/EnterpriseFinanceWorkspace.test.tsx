import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { BrowserSessionProvider, useBrowserSession } from "../browserSession";
import { budgetIdentity, budgetResponse, budgetScope, budgetSession } from "../budget-control-test-fixtures";
import { financeTranslate } from "../enterprise-finance-i18n";
import EnterpriseFinanceWorkspace from "./EnterpriseFinanceWorkspace";

function Controls() {
  const auth = useBrowserSession();
  return <button onClick={() => auth.begin(budgetSession, "checker", auth.revision)}>Begin fixture</button>;
}
afterEach(() => vi.unstubAllGlobals());

describe("enterprise financial workspace", () => {
  it("starts with real identity authentication and no unverified balances", () => { render(<BrowserSessionProvider><EnterpriseFinanceWorkspace locale="en" /></BrowserSessionProvider>); expect(screen.getByRole("heading", { name: "Enterprise finance" })).toBeInTheDocument(); expect(screen.getByRole("form", { name: "Sign in" })).toBeInTheDocument(); expect(screen.getByLabelText("Password")).toHaveAttribute("type", "password"); expect(screen.queryByRole("table")).not.toBeInTheDocument(); });
  it("uses Arabic labels and RTL for the actual financial path", () => { const { container } = render(<BrowserSessionProvider><EnterpriseFinanceWorkspace locale="ar" /></BrowserSessionProvider>); expect(screen.getByRole("heading", { name: "المالية المؤسسية" })).toBeInTheDocument(); expect(container.querySelector("main")).toHaveAttribute("dir", "rtl"); expect(screen.getByLabelText("كلمة المرور")).toHaveAttribute("type", "password"); });
  it("keeps scope input disabled until the authenticated identity prefill commits", async () => {
    let resolveIdentity!: (value: Response) => void;
    const fetchIdentity = vi.fn(() => new Promise<Response>(resolve => { resolveIdentity = resolve; }));
    vi.stubGlobal("fetch", fetchIdentity);
    render(<BrowserSessionProvider><Controls /><EnterpriseFinanceWorkspace locale="en" /></BrowserSessionProvider>);
    fireEvent.click(screen.getByText("Begin fixture"));
    await waitFor(() => expect(fetchIdentity).toHaveBeenCalledOnce());
    for (const label of ["Workspace", "Organization", "Legal entity"]) expect(screen.getByLabelText(label)).toBeDisabled();
    expect(screen.getByRole("button", { name: "Apply scope" })).toBeDisabled();
    await act(async () => resolveIdentity(budgetResponse(budgetIdentity)));
    for (const [label, value] of [["Workspace", budgetScope.workspace_id], ["Organization", budgetScope.organization_id], ["Legal entity", budgetScope.legal_entity_id]]) {
      expect(screen.getByLabelText(label)).toBeEnabled();
      expect(screen.getByLabelText(label)).toHaveValue(value);
    }
    expect(screen.getByRole("button", { name: "Apply scope" })).toBeEnabled();
  });
  it.each(["en", "ar"] as const)("%s owner refusal explains where to approve without offering an unsafe retry", async locale => {
    const t = (key: Parameters<typeof financeTranslate>[1]) => financeTranslate(locale, key);
    const plan = { api_contract_version: "operational-finance-api-v1", id: "OPS1-source", entry_id: "entry", source_kind: "ARInvoice", source_id: "invoice", status: "Draft", amount_minor: "12000", currency_code: "USD", currency_precision: 2, preparer_actor_id: "maker", reviewer_actor_id: null, review_digest: null, posting_effect_id: null, source_effect_id: null, plan_digest: "a".repeat(64), validation_digest: "b".repeat(64), ...budgetScope, organization_code: "ORG", entity_code: "ENTITY", period_id: "period", posting_date: "2026-10-08", reason: "Actual source", lines: [{ account_id: "ar", debit_minor: "12000", credit_minor: "0" }, { account_id: "revenue", debit_minor: "0", credit_minor: "12000" }], source_json: "{}", snapshot_json: "{}" };
    const writes: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (path: RequestInfo | URL, options?: RequestInit) => {
      if (String(path).endsWith("/auth/me")) return budgetResponse({ ...budgetIdentity, id: "checker", permissions: ["finance_core.read", "finance_core.validate"] });
      if (options?.method === "POST") { writes.push(String(options.body)); return budgetResponse({ error: { code: "operational_owner_required", message: "Complete the owner cycle" } }, 409); }
      return budgetResponse({ plans: [plan] });
    }));
    render(<BrowserSessionProvider><Controls /><EnterpriseFinanceWorkspace locale={locale} /></BrowserSessionProvider>);
    fireEvent.click(screen.getByText("Begin fixture"));
    await waitFor(() => expect(screen.getByLabelText(t("workspace"))).toHaveValue(budgetScope.workspace_id));
    fireEvent.click(screen.getByRole("button", { name: t("apply") }));
    fireEvent.click(await screen.findByRole("button", { name: t("inspect") }));
    fireEvent.change(screen.getByLabelText(t("reason")), { target: { value: "Independent financial review" } });
    fireEvent.click(screen.getByRole("button", { name: t("review") }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(t("ownerRequired"));
    expect(alert).not.toHaveTextContent(t("conflict"));
    await waitFor(() => expect(alert).toHaveFocus());
    expect(screen.queryByRole("button", { name: t("retry") })).not.toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(writes).toHaveLength(1);
    expect(JSON.parse(writes[0])).toMatchObject({ expected_plan_digest: plan.plan_digest, reason: "Independent financial review" });
  });
});
