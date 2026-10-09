import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { BrowserSessionProvider, useBrowserSession } from "../browserSession";
import { reportingTranslate } from "../financial-reporting-i18n";
import FinancialReportingPage from "./FinancialReportingPage";

function BeginSession() {
  const auth = useBrowserSession();
  return <button onClick={() => auth.begin({ tenantId: "synthetic", csrfToken: "csrf", expiresAt: "2099-01-01T00:00:00Z" }, "reader", auth.revision)}>Begin session</button>;
}
afterEach(() => vi.unstubAllGlobals());

describe("financial reporting interface", () => {
  it("starts at real authentication and renders no invented balance", () => { render(<BrowserSessionProvider><FinancialReportingPage locale="en" /></BrowserSessionProvider>); expect(screen.getByRole("heading", { name: "Financial statements" })).toBeInTheDocument(); expect(screen.getByRole("form", { name: "Sign in" })).toBeInTheDocument(); expect(screen.getByLabelText("Password")).toHaveAttribute("type", "password"); expect(screen.queryByRole("table")).not.toBeInTheDocument(); });
  it("presents the actual Arabic authentication path with RTL", () => { const { container } = render(<BrowserSessionProvider><FinancialReportingPage locale="ar" /></BrowserSessionProvider>); expect(screen.getByRole("heading", { name: "القوائم المالية" })).toBeInTheDocument(); expect(container.querySelector("main")).toHaveAttribute("dir", "rtl"); expect(screen.getByLabelText("كلمة المرور")).toHaveAttribute("type", "password"); });
  it.each(["en", "ar"] as const)("waits for current identity before editing or applying scope in %s", async locale => {
    const t = (key: Parameters<typeof reportingTranslate>[1]) => reportingTranslate(locale, key);
    const scope = { workspace_id: "work", organization_id: "org", legal_entity_id: "entity" };
    let resolveIdentity!: (value: Response) => void;
    const identity = new Promise<Response>(resolve => { resolveIdentity = resolve; });
    const reads: Headers[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
      if (String(url).endsWith("/auth/me")) return identity;
      reads.push(new Headers(init?.headers));
      return new Response(JSON.stringify({ api_contract_version: "financial-reporting-api-v1", ...(String(url).endsWith("/catalog") ? { catalog: { ...scope, currency_code: "USD", currency_precision: 2, accounts: [], periods: [], journals: [] } } : String(url).endsWith("/maps") ? { maps: [] } : { openings: [] }) }), { status: 200 });
    }));
    render(<BrowserSessionProvider><BeginSession /><FinancialReportingPage locale={locale} /></BrowserSessionProvider>);
    fireEvent.click(screen.getByRole("button", { name: "Begin session" }));
    const fields = ["workspace", "organization", "entity"] as const;
    for (const field of fields) expect(screen.getByLabelText(t(field))).toBeDisabled();
    expect(screen.getByRole("button", { name: t("apply") })).toBeDisabled();
    expect(reads).toHaveLength(0);
    await act(async () => resolveIdentity(new Response(JSON.stringify({ id: "reader", principal_type: "user", step_up_active: true, permissions: ["finance_core.read", "finance_core.manage"], authorized_scopes: { workspaces: ["work"], organizations: ["org"], legal_entities: ["entity"] } }), { status: 200 })));
    await waitFor(() => {
      for (const field of fields) expect(screen.getByLabelText(t(field))).toBeEnabled();
    });
    for (const [field, value] of [["workspace", "work"], ["organization", "org"], ["entity", "entity"]] as const) {
      expect(screen.getByLabelText(t(field))).toHaveValue(value);
      fireEvent.change(screen.getByLabelText(t(field)), { target: { value } });
    }
    fireEvent.click(screen.getByRole("button", { name: t("apply") }));
    await screen.findByRole("form", { name: t("prepareMap") });
    expect(reads).toHaveLength(3);
    for (const headers of reads) {
      expect(headers.get("X-ReconForge-Workspace")).toBe("work");
      expect(headers.get("X-ReconForge-Organization")).toBe("org");
      expect(headers.get("X-ReconForge-Legal-Entity")).toBe("entity");
    }
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
