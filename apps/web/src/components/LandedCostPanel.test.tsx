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
function panel(actorId: string, current: PartialDetail = detail) {
  return render(<LandedCostPanel locale="en" session={{ tenantId: "tenant" } as BrowserAdminSession} scope={scope} detail={current} actorId={actorId}
    permissions={permissions} elevated locked={false} reason="Replace unreceived source" periods={[{ id: "period", name: "October" }]} onChanged={vi.fn().mockResolvedValue(undefined)} onBusy={vi.fn()} onError={vi.fn()} />);
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

it("requires fresh quantities and paid charges after cancelled source evidence is reloaded", async () => {
  const cancelled = { ...plan(), status: "Cancelled" as const, cancellation: { actor_id: "checker", reason: "Replace source", command_id: "cancel", audit_event_id: "audit", outbox_event_id: "outbox" } };
  vi.mocked(landedPage).mockResolvedValue({ records: [cancelled], next_after: null });
  vi.mocked(landedCommand).mockResolvedValue({ ...plan(), id: "LC1-replacement", number: "CORRECTED" });
  const refreshed = { ...detail, order: { ...detail.order, row_version: 5 }, lines: [
    { id: "each", item_code: "ITEM", location_code: "MAIN/STOCK", uom_code: "EA", reserved_receipt_quantity: "0" },
    { id: "weight", item_code: "WEIGHT", location_code: "NORTH/STOCK", uom_code: "KG", reserved_receipt_quantity: "0" },
  ] } as unknown as PartialDetail;
  panel("maker", refreshed);
  await screen.findByText(/Cancelled; receiving reservations released/);
  const form = screen.getByRole("form", { name: "Prepare landed cost bundle" });
  fireEvent.change(screen.getByLabelText("Landed cost number"), { target: { value: "CORRECTED" } });
  fireEvent.submit(form);
  expect(screen.getByRole("alert")).toHaveTextContent("Enter a receiving quantity for at least one purchase line.");
  expect(landedCommand).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText("Quantity to receive · ITEM · MAIN/STOCK · EA"), { target: { value: "10" } });
  fireEvent.change(screen.getByLabelText("Quantity to receive · WEIGHT · NORTH/STOCK · KG"), { target: { value: "2.50" } });
  fireEvent.submit(form);
  expect(screen.getByRole("alert")).toHaveTextContent("Enter positive paid freight or duties");
  expect(landedCommand).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText("Paid freight in minor units"), { target: { value: "777" } });
  fireEvent.change(screen.getByLabelText("Paid duties in minor units"), { target: { value: "224" } });
  fireEvent.submit(form);
  await waitFor(() => expect(landedCommand).toHaveBeenCalledOnce());
  expect(vi.mocked(landedCommand).mock.calls[0][3].body).toMatchObject({ number: "CORRECTED", order_id: "order", expected_version: 5,
    freight_minor: "777", duty_minor: "224", lines: [{ line_id: "each", quantity: "10" }, { line_id: "weight", quantity: "2.50" }] });
  expect(screen.queryByRole("alert")).toBeNull();
});
