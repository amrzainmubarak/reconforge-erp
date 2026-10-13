import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { loadBudgetIdentity } from "../budget-control-data";
import original from "../project-source-reconciliation-original-report.json";
import { projectCloseFixture } from "../project-source-close-test-fixture";
import { ProjectSourceReconciliationPage } from "./ProjectSourceReconciliationPage";

const session = { tenantId: original.qualified_scope.tenant_id, csrfToken: "csrf", expiresAt: "2099-01-01T00:00:00Z" }, isCurrent = vi.fn(() => true);
vi.mock("../browserSession", () => ({ useBrowserSession: () => ({ session, revision: 1, isCurrent, recover: () => false }) }));
vi.mock("../budget-control-data", () => ({ loadBudgetIdentity: vi.fn() }));
const identity = { id: "maker", human: true, stepUp: false, workspaces: ["work"], organizations: ["org"], entities: ["entity"], permissions: ["project_time_billing.read", "finance_core.read", "people_project_payroll.read", "receivables.read"] };
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); isCurrent.mockReturnValue(true); });
async function fill(report = original, actor = identity) { vi.mocked(loadBudgetIdentity).mockResolvedValue(actor); vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ report })))); render(<ProjectSourceReconciliationPage locale="en" />);
  await waitFor(() => expect(screen.getByLabelText("Workspace")).toHaveValue("work"));
  for (const [label, value] of [["Original Project ID", original.selection.project_id], ["Original period ID", original.selection.period_id], ["Posted wage source ID", original.selection.payrun_id], ["Posted project invoice ID", original.selection.invoice_id]]) fireEvent.change(screen.getByLabelText(label), { target: { value } });
}
it("shows verified project margin and explicitly separate whole documents", async () => { await fill(); fireEvent.click(screen.getByRole("button", { name: "Verify original sources" })); await screen.findByText("Verified original report"); expect(screen.getByText("12.67 USD")).toBeInTheDocument(); expect(screen.getByText(/cash is not allocated by Project/)).toBeInTheDocument(); expect(screen.getByRole("button", { name: "Download original evidence" })).toBeEnabled(); });
it("holds display/download until actual WebCrypto proof finishes", async () => { const native = crypto.subtle.digest.bind(crypto.subtle); let release!: () => void; vi.spyOn(crypto.subtle, "digest").mockImplementationOnce(async (...args) => { const bytes = await native(...args); return new Promise(resolve => { release = () => resolve(bytes); }); }); await fill(); fireEvent.click(screen.getByRole("button", { name: "Verify original sources" })); await waitFor(() => expect(release).toBeTypeOf("function")); expect(screen.queryByText("Verified original report")).not.toBeInTheDocument(); expect(screen.queryByRole("button", { name: "Download original evidence" })).not.toBeInTheDocument(); release(); await screen.findByText("Verified original report"); });
it("rejects a valid report for a foreign source", async () => { await fill({ ...original, selection: { ...original.selection, invoice_id: "PB1-other" } }); fireEvent.click(screen.getByRole("button", { name: "Verify original sources" })); await screen.findByRole("alert"); expect(screen.queryByText("12.67 USD")).not.toBeInTheDocument(); });
it("invalidates verified output as soon as source selection changes", async () => { await fill(); fireEvent.click(screen.getByRole("button", { name: "Verify original sources" })); await screen.findByText("Verified original report"); fireEvent.change(screen.getByLabelText("Original Project ID"), { target: { value: "other" } }); expect(screen.queryByText("Verified original report")).not.toBeInTheDocument(); });
it("does not expose a delayed proof after the session is revoked", async () => { const native = crypto.subtle.digest.bind(crypto.subtle); let release!: () => void; vi.spyOn(crypto.subtle, "digest").mockImplementationOnce(async (...args) => { const bytes = await native(...args); return new Promise(resolve => { release = () => resolve(bytes); }); }); await fill(); fireEvent.click(screen.getByRole("button", { name: "Verify original sources" })); await waitFor(() => expect(release).toBeTypeOf("function")); isCurrent.mockReturnValue(false); release(); await waitFor(() => expect(screen.queryByText("Verified original report")).not.toBeInTheDocument()); });
it("requires all four current read prerequisites in Studio", async () => { await fill(original, { ...identity, permissions: ["project_time_billing.read"] }); expect(screen.getByRole("button", { name: "Verify original sources" })).toBeDisabled(); expect(fetch).not.toHaveBeenCalled(); });
it("clears the verified financial view immediately after an original export permission refusal", async () => { await fill(); fireEvent.click(screen.getByRole("button", { name: "Verify original sources" })); await screen.findByText("Verified original report");
  vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 403 })));
  fireEvent.click(screen.getByRole("button", { name: "Download original evidence" })); await screen.findByRole("alert");
  expect(screen.queryByText("Verified original report")).not.toBeInTheDocument(); expect(screen.queryByText("12.67 USD")).not.toBeInTheDocument(); expect(screen.queryByRole("button", { name: "Download original evidence" })).not.toBeInTheDocument();
});
it("shows selected source obligations separately from observed native period and formal close", async () => {
  await fill(); fireEvent.click(screen.getByRole("button", { name: "Verify original sources" })); await screen.findByText("Verified original report");
  const diagnostic = await projectCloseFixture(); vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ diagnostic }))));
  fireEvent.click(screen.getByRole("button", { name: "Verify selected source obligations" }));
  await screen.findByText("The selected original wage and invoice obligations are settled.");
  expect(screen.getByText(/Synthetic observed period/)).toBeInTheDocument();
  expect(screen.getByText(/does not assess formal close tasks/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Download source obligation evidence" })).toBeEnabled();
});
it("holds source obligation publication until actual native WebCrypto finishes and invalidates on selection change", async () => {
  await fill(); fireEvent.click(screen.getByRole("button", { name: "Verify original sources" })); await screen.findByText("Verified original report");
  const diagnostic = await projectCloseFixture(); vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ diagnostic }))));
  const native = crypto.subtle.digest.bind(crypto.subtle); let release!: () => void; vi.spyOn(crypto.subtle, "digest").mockImplementationOnce(async (...args) => { const bytes = await native(...args); return new Promise(resolve => { release = () => resolve(bytes); }); });
  fireEvent.click(screen.getByRole("button", { name: "Verify selected source obligations" })); await waitFor(() => expect(release).toBeTypeOf("function"));
  expect(screen.queryByRole("button", { name: "Download source obligation evidence" })).not.toBeInTheDocument(); release(); await screen.findByText("The selected original wage and invoice obligations are settled.");
  fireEvent.change(screen.getByLabelText("Original period ID"), { target: { value: "other" } });
  expect(screen.queryByText("The selected original wage and invoice obligations are settled.")).not.toBeInTheDocument();
});
it("clears source report and obligation evidence after current diagnostic export authority withdrawal", async () => {
  await fill(); fireEvent.click(screen.getByRole("button", { name: "Verify original sources" })); await screen.findByText("Verified original report");
  const diagnostic = await projectCloseFixture(); vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ diagnostic }))));
  fireEvent.click(screen.getByRole("button", { name: "Verify selected source obligations" })); await screen.findByText("The selected original wage and invoice obligations are settled.");
  vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 403 }))); fireEvent.click(screen.getByRole("button", { name: "Download source obligation evidence" }));
  await screen.findByRole("alert"); expect(screen.queryByText("Verified original report")).not.toBeInTheDocument(); expect(screen.queryByText("The selected original wage and invoice obligations are settled.")).not.toBeInTheDocument();
});
