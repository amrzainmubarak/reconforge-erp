import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { loadBudgetPage } from "../budget-control-data";
import { loadExceptionReviewIdentity } from "../exception-review-data";
import { procurementOptions, procurementScopes } from "../procurement-data";
import { sourcingGet, sourcingList, sourcingCommand, type SourcingDetail } from "../procurement-sourcing-data";
import { ProcurementSourcingPage } from "./ProcurementSourcingPage";
vi.mock("../browserSession", () => {
  const auth = { session: { tenantId: "tenant", csrfToken: "csrf", expiresAt: "2999-01-01T00:00:00Z" }, username: "checker", stepUpExpiresAt: "2999-01-01T00:00:00Z", revision: 1, isCurrent: () => true, recover: () => false };
  return { useBrowserSession: () => auth };
});
vi.mock("../exception-review-data", () => ({ loadExceptionReviewIdentity: vi.fn() }));
vi.mock("../procurement-data", () => ({ procurementOptions: vi.fn(), procurementScopes: vi.fn() }));
vi.mock("../budget-control-data", () => ({ loadBudgetPage: vi.fn(), loadBudgetDetail: vi.fn() }));
vi.mock("../procurement-sourcing-data", async () => ({ ...await vi.importActual("../procurement-sourcing-data"), sourcingGet: vi.fn(), sourcingList: vi.fn(), sourcingCommand: vi.fn() }));
const scope = { workspace_id: "work", organization_id: "org", legal_entity_id: "entity", organization_code: "ORG", entity_code: "ENTITY", organization_name: "Organization", entity_name: "Entity", currency_code: "USD" };
const draft = {
  head: { schema_version: "procurement-sourcing-v1", id: "source", number: "SRC5-1", row_version: 1, status: "Draft", ...scope, budget_id: "budget", ceiling_minor: "12000",
    source_digest: "a".repeat(64), creator_actor_id: "maker", rfq_approver_actor_id: null, selection_reviewer_actor_id: null, award_actor_id: null, selected_quote_id: null, order_id: null,
    evidence: { audit_event_id: "source-audit", outbox_event_id: "source-outbox", request_digest: "b".repeat(64) } },
  source: { request: { order: { posting_date: "2026-10-12", lines: [{ item_code: "ITEM", quantity: "10", unit_price_minor: "1200" }] } } }, quotations: [],
} as unknown as SourcingDetail;
const open = { ...draft, head: { ...draft.head, row_version: 2, status: "OpenRFQ" as const, rfq_approver_actor_id: "checker" } };
beforeEach(() => {
  vi.mocked(loadExceptionReviewIdentity).mockResolvedValue({ id: "checker", human: true, workspaces: ["work"], permissions: ["procurement_sourcing.read", "procurement_sourcing.approve"] } as never);
  vi.mocked(procurementScopes).mockResolvedValue([scope]);
  vi.mocked(procurementOptions).mockResolvedValue({ suppliers: [], items: [], locations: [], policies: [], periods: [], journals: [], accounts: [] });
  vi.mocked(loadBudgetPage).mockResolvedValue({ envelopes: [], pagination: { limit: 25, offset: 0, has_more: false } });
  vi.mocked(sourcingList).mockResolvedValue([draft.head]); vi.mocked(sourcingGet).mockResolvedValue(draft);
});
async function inspected() {
  await screen.findByRole("option", { name: "Organization · Entity · USD" });
  fireEvent.change(await screen.findByRole("combobox", { name: "Organization and legal entity" }), { target: { value: "entity" } });
  fireEvent.click(await screen.findByRole("button", { name: "Open SRC5-1" }));
  await screen.findByRole("heading", { name: "SRC5-1" });
  fireEvent.change(screen.getByLabelText("Review or award reason"), { target: { value: "Independent exact RFQ approval" } });
}
it("reads native budgets with only canonical hierarchy IDs and exposes original evidence", async () => {
  render(<ProcurementSourcingPage locale="en" />); await inspected();
  expect(vi.mocked(loadBudgetPage).mock.calls[0][1]).toEqual({ workspace_id: "work", organization_id: "org", legal_entity_id: "entity" });
  expect(screen.getByText("source-audit")).toBeVisible(); expect(screen.getByRole("button", { name: "Open RFQ independently" })).toBeEnabled();
});
it("retains exactly one original pending command and blocks new operations after lost response", async () => {
  vi.mocked(sourcingCommand).mockRejectedValueOnce(new Error("lost acknowledgment")).mockImplementationOnce(async () => { vi.mocked(sourcingGet).mockResolvedValue(open); return open.head; });
  render(<ProcurementSourcingPage locale="en" />); await inspected();
  fireEvent.click(screen.getByRole("button", { name: "Open RFQ independently" }));
  const retry = await screen.findByRole("button", { name: "Retry exact sourcing command" });
  expect(screen.getByRole("button", { name: "Open RFQ independently" })).toBeDisabled();
  fireEvent.click(retry); await screen.findByText("OpenRFQ");
  expect(vi.mocked(sourcingCommand).mock.calls[0][2]).toEqual(vi.mocked(sourcingCommand).mock.calls[1][2]);
  expect(screen.queryByRole("button", { name: "Retry exact sourcing command" })).toBeNull();
});
it("ignores a command acknowledgment and following reads after its page is unmounted", async () => {
  let finish: (value: typeof open.head) => void = () => {};
  vi.mocked(sourcingCommand).mockImplementation(() => new Promise(resolve => { finish = resolve; }));
  const view = render(<ProcurementSourcingPage locale="en" />); await inspected();
  fireEvent.click(screen.getByRole("button", { name: "Open RFQ independently" })); await waitFor(() => expect(sourcingCommand).toHaveBeenCalled());
  view.unmount(); await act(async () => { finish(open.head); });
  expect(screen.queryByText("OpenRFQ")).toBeNull();
});
