import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { BrowserSessionProvider, useBrowserSession } from "../browserSession";
import fixture from "../operational-fx-tax-fixture.json";
import { fxTranslate } from "../operational-fx-tax-i18n";
import OperationalFxTaxPage from "./OperationalFxTaxPage";

const scope = { workspace_id: "work", organization_id: "org", legal_entity_id: "entity" };
const catalog = { ...scope, currency_code: "USD", currency_precision: 2, accounts: [], periods: [], journals: [] };
const detail = (plan = fixture.plan) => ({ ...fixture.source, foreign_outstanding_minor: "11401", foreign_paid_minor: "0", functional_outstanding_minor: "14251", historical_released_minor: "0", plans: [plan] });
const identity = { id: "poster", principal_type: "user", step_up_active: true, permissions: ["finance_core.read", "finance_core.manage", "finance_core.validate", "finance_core.post", "receivables.read", "receivables.manage", "receivables.approve"], authorized_scopes: { workspaces: ["work"], organizations: ["org"], legal_entities: ["entity"] } };
const response = (value: object) => new Response(JSON.stringify(value), { status: 200 });
function BeginSession() { const auth = useBrowserSession(); return <button onClick={() => auth.begin({ tenantId: "synthetic", csrfToken: "csrf", expiresAt: "2099-01-01T00:00:00Z" }, "poster", auth.revision)}>Begin session</button>; }
async function open(locale: "en" | "ar" = "en") {
  render(<BrowserSessionProvider><BeginSession /><OperationalFxTaxPage locale={locale} /></BrowserSessionProvider>);
  fireEvent.click(screen.getByRole("button", { name: "Begin session" }));
  const apply = await screen.findByRole("button", { name: fxTranslate(locale, "apply") });
  await waitFor(() => expect(apply).toBeEnabled()); fireEvent.click(apply);
  await screen.findByRole("form", { name: fxTranslate(locale, "prepare") });
  fireEvent.change(screen.getByLabelText(fxTranslate(locale, "invoices")), { target: { value: fixture.source.id } });
  await screen.findByRole("region", { name: fxTranslate(locale, "plan") });
}
afterEach(() => vi.unstubAllGlobals());
describe("actual foreign receivable Studio workflow", () => {
  it("renders real login and Arabic RTL without fabricated financial balances", () => {
    const { container } = render(<BrowserSessionProvider><OperationalFxTaxPage locale="ar" /></BrowserSessionProvider>);
    expect(screen.getByRole("form", { name: "تسجيل الدخول" })).toBeInTheDocument(); expect(container.querySelector("main")).toHaveAttribute("dir", "rtl");
    expect(screen.getByLabelText("كلمة المرور")).toHaveAttribute("type", "password"); expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });
  it.each(["en", "ar"] as const)("verifies original foreign tax and native three-human evidence in %s", async locale => {
    const reads: Headers[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
      if (String(url).endsWith("/auth/me")) return response(identity);
      reads.push(new Headers(init?.headers));
      return response(String(url).endsWith("/catalog") ? { api_contract_version: "financial-reporting-api-v1", catalog } : String(url).endsWith("/evidence") ? { evidence: fixture } : String(url).endsWith("/invoices") ? { invoices: [fixture.source], next_after: null } : { invoice: detail() });
    }));
    await open(locale); fireEvent.click(screen.getByRole("button", { name: fxTranslate(locale, "verify") }));
    expect(await screen.findByRole("status")).toHaveTextContent(fxTranslate(locale, "verified"));
    expect(screen.getByRole("button", { name: fxTranslate(locale, "download") })).toBeEnabled();
    expect(screen.getByText("2026-v1")).toBeInTheDocument(); expect(screen.getAllByText("poster")).toHaveLength(3);
    for (const headers of reads) { expect(headers.get("X-ReconForge-Workspace")).toBe("work"); expect(headers.get("X-ReconForge-Legal-Entity")).toBe("entity"); }
  });
  it("preserves exact post command after malformed acknowledgement and locks editing until its same-command retry", async () => {
    const reviewed = { ...fixture.plan, phase: 1, status: "Reviewed", posting_effect_id: null } as unknown as typeof fixture.plan;
    const commands: { url: string; body: string; csrf: string | null }[] = []; let posted = false;
    vi.stubGlobal("fetch", vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
      if (String(url).endsWith("/auth/me")) return response(identity);
      if (init?.method === "POST") { commands.push({ url: String(url), body: String(init.body), csrf: new Headers(init.headers).get("X-ReconForge-CSRF") });
        if (commands.length === 1) return response({ plan: {} }); posted = true; return response({ plan: fixture.plan }); }
      if (String(url).endsWith("/catalog")) return response({ api_contract_version: "financial-reporting-api-v1", catalog });
      if (String(url).endsWith("/invoices")) return response({ invoices: [fixture.source], next_after: null });
      return response({ invoice: detail(posted ? fixture.plan : reviewed) });
    }));
    await open(); const region = screen.getByRole("region", { name: "Retained operation" });
    fireEvent.change(within(region).getByLabelText("Reason"), { target: { value: "Independent publication" } });
    fireEvent.click(screen.getByRole("button", { name: "Post as third human" }));
    const retry = await screen.findByRole("button", { name: "Retry the same command" });
    expect(screen.getByRole("button", { name: "Post as third human" })).toBeDisabled();
    expect(screen.getByLabelText("Invoice number")).toBeDisabled(); fireEvent.click(retry);
    await waitFor(() => expect(commands).toHaveLength(2)); expect(commands[0]).toEqual(commands[1]); expect(commands[0].csrf).toBe("csrf");
    await waitFor(() => expect(screen.queryByRole("button", { name: "Post as third human" })).not.toBeInTheDocument());
    expect(screen.queryByRole("button", { name: "Retry the same command" })).not.toBeInTheDocument(); expect(screen.getByText("effect-synthetic")).toBeInTheDocument();
  });
});
