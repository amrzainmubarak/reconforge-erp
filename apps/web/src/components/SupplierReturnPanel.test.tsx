import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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

it.each(["en", "ar"] as const)("prepares the exact populated original receipt and AP invoice through named comboboxes in %s", async locale => {
  const source = { ...detail,
    receipts: [{ id: "receipt", number: "Receipt EA", stage: "Posted", quantity_text: "10", total_minor: "12000", order_line_id: "line-ea" }, { id: "receipt-kg", number: "Receipt KG", stage: "Posted", quantity_text: "2.50", total_minor: "5000", order_line_id: "line-kg" }],
    invoices: [{ id: "invoice", number: "Invoice EA", stage: "Accrued", native_status: "Approved", paid_minor: "0", outstanding_minor: "12000", total_minor: "12000", installment_plans: [], lines: [{ line_id: "line-ea", quantity_text: "10" }] }, { id: "invoice-kg", number: "Invoice KG", stage: "Accrued", native_status: "Approved", paid_minor: "0", outstanding_minor: "5000", total_minor: "5000", installment_plans: [], lines: [{ line_id: "line-kg", quantity_text: "2.50" }] }],
  } as unknown as PartialDetail;
  vi.mocked(supplierReturnPage).mockResolvedValue([]);
  vi.mocked(supplierReturnCommand).mockResolvedValue(supplierReturn());
  render(<SupplierReturnPanel {...props} locale={locale} actorId="maker" detail={source} permissions={[...props.permissions, "payables.manage", "inventory.manage", "inventory.valuation.manage", "inventory.valuation.reverse.manage", "finance_core.manage"]} />);
  const labels = locale === "en" ? { form: "Prepare original supplier debit", number: "Supplier return number", receipt: "Whole original receipt", invoice: "Exact unpaid supplier invoice", period: "Supplier return fiscal period", date: "Supplier return posting date", expense: "Paid charge expense account" } : { form: "إعداد إشعار خصم المورد الأصلي", number: "رقم مرتجع المورد", receipt: "الاستلام الأصلي الكامل", invoice: "فاتورة المورد غير المدفوعة المطابقة", period: "الفترة المالية للمرتجع", date: "تاريخ قيد مرتجع المورد", expense: "حساب مصروف التكاليف المدفوعة" };
  const form = screen.getByRole("form", { name: labels.form });
  const controls = within(form);
  fireEvent.change(controls.getByLabelText(labels.number, { exact: true }), { target: { value: "SR1-POPULATED" } });
  fireEvent.change(controls.getByRole("combobox", { name: labels.receipt }), { target: { value: "receipt" } });
  expect(controls.queryByRole("option", { name: "Invoice KG · 5000" })).toBeNull();
  fireEvent.change(controls.getByRole("combobox", { name: labels.invoice }), { target: { value: "invoice" } });
  fireEvent.change(controls.getByRole("combobox", { name: labels.period }), { target: { value: "period" } });
  fireEvent.change(controls.getByLabelText(labels.date, { exact: true }), { target: { value: "2026-10-13" } });
  fireEvent.change(controls.getByLabelText(labels.expense, { exact: true }), { target: { value: "ADJUSTMENT" } });
  expect(controls.getByRole("button", { name: labels.form })).toBeEnabled();
  fireEvent.submit(form);
  await waitFor(() => expect(supplierReturnCommand).toHaveBeenCalledTimes(1));
  expect(vi.mocked(supplierReturnCommand).mock.calls[0][3].body).toMatchObject({ order_id: "order", receipt_id: "receipt", invoice_id: "invoice", number: "SR1-POPULATED", posting_date: "2026-10-13", period_id: "period", expense_account_code: "ADJUSTMENT", reason: props.reason });
});
