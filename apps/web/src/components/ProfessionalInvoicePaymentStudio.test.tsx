import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, test, vi } from "vitest";

import { loadProfessionalInvoicePaymentStudio } from "../data";
import { translate } from "../i18n";
import type { ProfessionalInvoicePaymentStudioContract } from "../types";
import { ProfessionalInvoicePaymentStudio } from "./ProfessionalInvoicePaymentStudio";

vi.mock("../data", () => ({
  loadProfessionalInvoicePaymentStudio: vi.fn(),
}));

const contract: ProfessionalInvoicePaymentStudioContract = {
  schema_version: 1,
  synthetic_data_only: true,
  synthetic_data_marker: "SYNTHETIC_PROFESSIONAL_INVOICE_PAYMENT_UI_ONLY",
  generated_at: "2026-08-08T00:00:00Z",
  source: { kind: "reconforge-enterprise-demo", local_first: true, external_calls: false },
  algorithm_version: "professional-invoice-payment-control-v1",
  decision_digest: "b6825150b482612271b76a03bb6414fc5d701c9f8cd4c96bb641cf489421796e",
  artifact_digest: "01e921e1eb5c60ad98bc216205a61071ca6c1d634659c3e1f94c81b8c8f33e06",
  tolerance: "0.01",
  currency: "USD",
  payment_window_days: 3,
  summary: { total: 6, matched: 2, exceptions: 1, unmatched_invoice: 1, unmatched_payment: 1, ambiguous: 1 },
  decisions: [
    { invoice_id: "INV-001", client_id: "ACME", status: "matched", payment_ids: ["PAY-001"], amount_variance: "0.00", days_from_due_date: -1, reason_code: "INVOICE_PAYMENT_RECONCILED" },
    { invoice_id: "INV-002", client_id: "ACME", status: "exception", payment_ids: ["PAY-002"], amount_variance: "10.00", days_from_due_date: 1, reason_code: "INVOICE_PAYMENT_AMOUNT_VARIANCE" },
    { invoice_id: "INV-005", client_id: "ACME", status: "unmatched_invoice", payment_ids: [], amount_variance: null, days_from_due_date: null, reason_code: "INVOICE_HAS_NO_PAYMENT_CANDIDATE" },
    { invoice_id: "PAY-006", client_id: "ACME", status: "unmatched_payment", payment_ids: ["PAY-006"], amount_variance: null, days_from_due_date: null, reason_code: "PAYMENT_HAS_NO_INVOICE_LINE" },
    { invoice_id: "INV-003", client_id: "BETA", status: "matched", payment_ids: ["PAY-003"], amount_variance: "0.00", days_from_due_date: 1, reason_code: "INVOICE_PAYMENT_RECONCILED" },
    { invoice_id: "INV-004", client_id: "BETA", status: "ambiguous", payment_ids: ["PAY-004", "PAY-005"], amount_variance: "0.00", days_from_due_date: 0, reason_code: "MULTIPLE_PAYMENT_CANDIDATES" },
  ],
  notices: [],
};

beforeEach(() => {
  vi.mocked(loadProfessionalInvoicePaymentStudio).mockResolvedValue(contract);
});

describe("ProfessionalInvoicePaymentStudio", () => {
  test("renders exact decisions and filters without arithmetic", async () => {
    render(<ProfessionalInvoicePaymentStudio translate={(key) => translate("en", key)} />);

    expect(await screen.findByRole("heading", { name: "Professional invoice and payment control center" })).toBeInTheDocument();
    expect(screen.getByText("INV-002")).toBeInTheDocument();
    expect(screen.getByText("10.00 USD")).toBeInTheDocument();
    expect(screen.getByText("MULTIPLE_PAYMENT_CANDIDATES")).toBeInTheDocument();
    expect(screen.getByText("b6825150b482612271b76a03bb6414fc5d701c9f8cd4c96bb641cf489421796e")).toBeInTheDocument();

    fireEvent.change(screen.getByRole("combobox", { name: "Professional status" }), { target: { value: "ambiguous" } });
    expect(screen.getByText("INV-004")).toBeInTheDocument();
    expect(screen.queryByText("INV-001")).not.toBeInTheDocument();
  });

  test("surfaces a malformed projection failure from the strict loader", async () => {
    vi.mocked(loadProfessionalInvoicePaymentStudio).mockRejectedValue(new Error("The local Studio professional invoice/payment artifact does not match schema version 1."));
    render(<ProfessionalInvoicePaymentStudio translate={(key) => translate("en", key)} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Studio data is unavailable");
  });

  test("supports Arabic labels in the same read-only view", async () => {
    render(<ProfessionalInvoicePaymentStudio translate={(key) => translate("ar", key)} />);
    expect(await screen.findByRole("heading", { name: "مركز رقابة الفواتير والمدفوعات المهنية" })).toBeInTheDocument();
    expect(screen.getByText("أدلة إعادة التشغيل")).toBeInTheDocument();
  });
});
