import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { landedCommand, landedPage, type LandedPlan } from "../landed-cost-data";
import type { PartialDetail } from "../procurement-partial-data";
import type { ProcurementScope } from "../procurement-data";
import type { BrowserAdminSession } from "../types";
import { LandedCostPanel } from "./LandedCostPanel";

vi.mock("../landed-cost-data", async () => ({ ...await vi.importActual("../landed-cost-data"), landedPage: vi.fn(), landedCommand: vi.fn() }));
const scope = { workspace_id: "work", organization_id: "org", legal_entity_id: "entity", currency_code: "USD" } as ProcurementScope;
const detail = { order: { id: "order", row_version: 3, request: { posting_date: "2026-10-10", period_id: "period" } }, lines: [] } as unknown as PartialDetail;
const permissions = ["payables.manage", "payables.approve", "payables.settle", "inventory.manage", "inventory.post", "inventory.valuation.manage", "inventory.valuation.approve", "finance_core.manage", "finance_core.validate", "finance_core.post"];
function plan(): LandedPlan { return { id: "LC1-source", order_id: "order", number: "COST-1", ...scope, phase: 0, status: "Prepared", plan_digest: "a".repeat(64), freight_minor: "1", duty_minor: "0", amount_minor: "1", entry_id: "entry", preparer_actor_id: "maker", reviewer_actor_id: null, posted_actor_id: null, posting_effect_id: null, allocations: [] }; }
function panel(actorId: string) {
  return render(<LandedCostPanel locale="en" session={{ tenantId: "tenant" } as BrowserAdminSession} scope={scope} detail={detail} actorId={actorId}
    permissions={permissions} elevated locked={false} reason="Replace unreceived source" periods={[]} onChanged={vi.fn().mockResolvedValue(undefined)} onBusy={vi.fn()} onError={vi.fn()} />);
}
beforeEach(() => { vi.clearAllMocks(); vi.mocked(landedPage).mockResolvedValue({ records: [plan()], next_after: null }); });

it("prevents preparer cancellation and exposes the independent human action", async () => {
  panel("maker");
  await waitFor(() => expect(screen.getByRole("button", { name: "Cancel unreceived bundle" })).toBeDisabled());
});

it("keeps the same command through unconfirmed cancellation and displays released reservations", async () => {
  vi.mocked(landedCommand).mockRejectedValueOnce(new Error("lost acknowledgement")).mockImplementationOnce(async (_session, _scope, _order, command) => {
    const cancelled = { ...plan(), status: "Cancelled" as const, cancellation: { actor_id: "checker", reason: String(command.body.reason), command_id: String(command.body.command_id), audit_event_id: "cancel-audit", outbox_event_id: "cancel-outbox" } };
    vi.mocked(landedPage).mockResolvedValue({ records: [cancelled], next_after: null });
    return cancelled;
  });
  panel("checker");
  fireEvent.click(await screen.findByRole("button", { name: "Cancel unreceived bundle" }));
  fireEvent.click(await screen.findByRole("button", { name: "Retry the same command" }));
  await screen.findByText(/Cancelled; receiving reservations released/);
  expect(vi.mocked(landedCommand).mock.calls[0][3]).toEqual(vi.mocked(landedCommand).mock.calls[1][3]);
  expect(screen.queryByRole("button", { name: "Cancel unreceived bundle" })).toBeNull();
  expect(screen.getByText("cancel-audit")).toBeVisible();
});

it("requires a third human to cancel an already reviewed bundle", async () => {
  vi.mocked(landedPage).mockResolvedValue({ records: [{ ...plan(), phase: 1, status: "Reviewed", reviewer_actor_id: "checker" }], next_after: null });
  panel("checker");
  await waitFor(() => expect(screen.getByRole("button", { name: "Cancel unreceived bundle" })).toBeDisabled());
});
