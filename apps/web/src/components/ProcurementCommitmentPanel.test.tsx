import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { loadBudgetDetail, type BudgetDetail } from "../budget-control-data";
import { procurementCommitmentCommand, procurementCommitmentGet, type ProcurementCommitment } from "../procurement-commitment-data";
import { commitment } from "../test-fixtures/procurement-commitment";
import type { PartialDetail } from "../procurement-partial-data";
import type { ProcurementScope } from "../procurement-data";
import type { BrowserAdminSession } from "../types";
import { ProcurementCommitmentPanel } from "./ProcurementCommitmentPanel";

vi.mock("../procurement-commitment-data", async () => ({ ...await vi.importActual("../procurement-commitment-data"), procurementCommitmentGet: vi.fn(), procurementCommitmentCommand: vi.fn() }));
vi.mock("../budget-control-data", async () => ({ ...await vi.importActual("../budget-control-data"), loadBudgetDetail: vi.fn() }));
const scope = { workspace_id: "work", organization_id: "org", legal_entity_id: "entity", currency_code: "USD" } as ProcurementScope;
const detail = { order: { id: "order", row_version: 12, request: { posting_date: "2026-10-04", period_id: "period" } },
  lines: [], receipts: [], invoices: [] } as unknown as PartialDetail;
const props = { session: { tenantId: "tenant", csrfToken: "csrf" } as BrowserAdminSession, scope, detail, locale: "en" as const,
  actorId: "poster", permissions: ["budget_control.manage", "payables.approve", "payables.manage", "finance_core.post"], elevated: true,
  locked: false, reason: "Independent unreceived closure", initial: null, onState: vi.fn(), onBusy: vi.fn(), onError: vi.fn(), onChanged: vi.fn(async () => {}) };
const released = (): ProcurementCommitment => ({ ...commitment(), budget_version: 5, status: "Released", reserved_minor: "0", remaining_minor: "0", released_minor: "17000", evidence: { ...commitment().evidence, audit_event_id: "confirmed-release-audit" } });
beforeEach(() => { vi.clearAllMocks(); vi.mocked(procurementCommitmentGet).mockResolvedValue(commitment()); vi.mocked(loadBudgetDetail).mockResolvedValue({ row_version: 4 } as BudgetDetail); });

it("blocks original creator release and makes monetary source evidence visible", async () => {
  render(<ProcurementCommitmentPanel {...props} actorId="maker" />);
  expect(await screen.findAllByText("17000 USD")).toHaveLength(2);
  await waitFor(() => expect(screen.getByRole("button", { name: "Release remaining obligation" })).toBeDisabled());
  expect(screen.getByText("reserve-audit")).toBeVisible();
});
it("retries precisely the retained command after response loss without permitting a new action", async () => {
  vi.mocked(procurementCommitmentCommand).mockRejectedValueOnce(new Error("lost response")).mockImplementationOnce(async () => {
    vi.mocked(procurementCommitmentGet).mockResolvedValue(released()); return released();
  });
  render(<ProcurementCommitmentPanel {...props} detail={{ ...detail, lines: [{ received_quantity: "2.50", invoiced_quantity: "2.5" }] } as PartialDetail} />);
  await waitFor(() => expect(screen.getByRole("button", { name: "Release remaining obligation" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "Release remaining obligation" }));
  fireEvent.click(await screen.findByRole("button", { name: "Retry exact appropriation command" }));
  await screen.findByText("Released");
  expect(vi.mocked(procurementCommitmentCommand).mock.calls[0][2]).toEqual(vi.mocked(procurementCommitmentCommand).mock.calls[1][2]);
  expect(screen.queryByRole("button", { name: "Release remaining obligation" })).toBeNull();
  expect(screen.getByText("confirmed-release-audit")).toBeVisible();
});
it("retains confirmed release evidence when its follow-up source read fails", async () => {
  vi.mocked(procurementCommitmentGet).mockResolvedValueOnce(commitment()).mockRejectedValue(new Error("reader unavailable"));
  vi.mocked(procurementCommitmentCommand).mockResolvedValue(released());
  render(<ProcurementCommitmentPanel {...props} />);
  await waitFor(() => expect(screen.getByRole("button", { name: "Release remaining obligation" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "Release remaining obligation" }));
  await screen.findByText("Released"); await screen.findByRole("alert");
  expect(screen.getByText("confirmed-release-audit")).toBeVisible();
  expect(screen.queryByRole("button", { name: "Release remaining obligation" })).toBeNull();
  expect(screen.queryByRole("button", { name: "Retry exact appropriation command" })).toBeNull();
});
it("does not replace a newer terminal read with a delayed AP consumption acknowledgement", async () => {
  let respond!: (value: ProcurementCommitment) => void;
  vi.mocked(procurementCommitmentCommand).mockImplementation(() => new Promise((resolve) => { respond = resolve; }));
  const newer = { ...released(), budget_version: 6, consumed_minor: "7400", released_minor: "9600" };
  vi.mocked(procurementCommitmentGet).mockResolvedValueOnce(commitment()).mockResolvedValueOnce(newer).mockRejectedValue(new Error("follow-up unavailable"));
  const invoiced = { ...detail, invoices: [{ id: "invoice", number: "AP-1", stage: "AccrualReviewed", accrual_preparer_actor_id: "maker", accrual_reviewer_actor_id: "checker" }] } as PartialDetail;
  const view = render(<ProcurementCommitmentPanel {...props} detail={invoiced} />);
  await waitFor(() => expect(screen.getByRole("button", { name: "Post AP and consume appropriation AP-1" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "Post AP and consume appropriation AP-1" }));
  view.rerender(<ProcurementCommitmentPanel {...props} detail={{ ...invoiced, order: { ...invoiced.order, row_version: 13 } }} />);
  await screen.findByText("Released");
  await act(async () => respond({ ...commitment(), budget_version: 5, consumed_minor: "7400", reserved_minor: "9600", remaining_minor: "9600" }));
  await screen.findByRole("alert");
  expect(screen.getByText("Released")).toBeVisible();
  expect(screen.queryByRole("button", { name: /Post AP and consume/ })).toBeNull();
  expect(screen.queryByRole("button", { name: "Release remaining obligation" })).toBeNull();
});
