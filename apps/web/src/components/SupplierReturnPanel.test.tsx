import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { supplierReturnCommand, supplierReturnPage, type SupplierReturnPlan } from "../supplier-return-data";
import { supplierReturn } from "../test-fixtures/supplier-return";
import type { PartialDetail } from "../procurement-partial-data";
import type { ProcurementScope } from "../procurement-data";
import type { BrowserAdminSession } from "../types";
import { SupplierReturnPanel } from "./SupplierReturnPanel";
vi.mock("../supplier-return-data", async () => ({ ...await vi.importActual("../supplier-return-data"), supplierReturnCommand: vi.fn(), supplierReturnPage: vi.fn() }));
const detail = { order: { id: "order", row_version: 12, request: { posting_date: "2026-10-05", period_id: "period" } }, receipts: [], invoices: [] } as unknown as PartialDetail;
const props = { locale: "en" as const, session: { tenantId: "tenant", csrfToken: "csrf" } as BrowserAdminSession, scope: { workspace_id: "work", organization_id: "org", legal_entity_id: "entity", currency_code: "USD" } as ProcurementScope, detail, actorId: "checker", permissions: ["payables.read", "inventory.read", "finance_core.read", "payables.approve", "inventory.valuation.reverse.approve", "finance_core.validate", "inventory.post", "inventory.valuation.approve", "finance_core.reverse"], elevated: true, locked: false, reason: "Independent rejected original source", periods: [{ id: "period", name: "October" }], onChanged: vi.fn(async () => {}), onBusy: vi.fn(), onError: vi.fn() };
beforeEach(() => { vi.clearAllMocks(); vi.mocked(supplierReturnPage).mockResolvedValue([supplierReturn()]); });
it("requires independent canonical humans even with full current review permissions", async () => {
  render(<SupplierReturnPanel {...props} actorId="maker" />);
  await screen.findByText("9007199254740993 USD");
  expect(screen.getByRole("button", { name: "Review supplier debit" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Cancel unposted supplier debit" })).toBeDisabled();
});
it("retains confirmed cancellation after a failing list refresh and removes progression actions", async () => {
  vi.mocked(supplierReturnPage).mockResolvedValueOnce([supplierReturn()]).mockRejectedValue(new Error("list unavailable"));
  vi.mocked(supplierReturnCommand).mockResolvedValue(supplierReturn(3));
  render(<SupplierReturnPanel {...props} />);
  fireEvent.click(await screen.findByRole("button", { name: "Cancel unposted supplier debit" }));
  await screen.findByText("Cancelled"); await screen.findByRole("alert");
  expect(screen.getByText("cancel-audit")).toBeVisible();
  expect(screen.queryByRole("button", { name: "Review supplier debit" })).toBeNull();
  expect(screen.queryByRole("button", { name: "Cancel unposted supplier debit" })).toBeNull();
});
it("reuses exact retained command and expected digest after response loss", async () => {
  vi.mocked(supplierReturnCommand).mockRejectedValueOnce(new Error("lost response")).mockImplementationOnce(async () => { vi.mocked(supplierReturnPage).mockResolvedValue([supplierReturn(3)]); return supplierReturn(3); });
  render(<SupplierReturnPanel {...props} />);
  fireEvent.click(await screen.findByRole("button", { name: "Cancel unposted supplier debit" }));
  fireEvent.click(await screen.findByRole("button", { name: "Retry the same supplier return command" }));
  await screen.findByText("Cancelled");
  expect(vi.mocked(supplierReturnCommand).mock.calls[0][3]).toEqual(vi.mocked(supplierReturnCommand).mock.calls[1][3]);
});
it("preserves terminal current evidence when an older review acknowledgement arrives late", async () => {
  let respond!: (v: SupplierReturnPlan) => void;
  vi.mocked(supplierReturnCommand).mockImplementation(() => new Promise(resolve => { respond = resolve; }));
  vi.mocked(supplierReturnPage).mockResolvedValueOnce([supplierReturn()]).mockResolvedValueOnce([supplierReturn(2)]).mockRejectedValue(new Error("refresh unavailable"));
  const view = render(<SupplierReturnPanel {...props} />);
  fireEvent.click(await screen.findByRole("button", { name: "Review supplier debit" }));
  view.rerender(<SupplierReturnPanel {...props} detail={{ ...detail, order: { ...detail.order, row_version: 13 } }} />);
  await screen.findByText("Posted");
  await act(async () => respond(supplierReturn(1))); await screen.findByRole("alert");
  expect(screen.getByText("post-audit")).toBeVisible();
  expect(screen.queryByRole("button", { name: "Remove original FIFO and credit AP" })).toBeNull();
});
