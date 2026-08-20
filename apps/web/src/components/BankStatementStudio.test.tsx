import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, test, vi } from "vitest";

import { loadBankStatementStudio } from "../data";
import { translate } from "../i18n";
import type { BankStatementStudioContract } from "../types";
import { BankStatementStudio } from "./BankStatementStudio";

vi.mock("../data", () => ({
  loadBankStatementStudio: vi.fn(),
}));

const contract: BankStatementStudioContract = {
  schema_version: 1,
  synthetic_data_only: true,
  synthetic_data_marker: "SYNTHETIC_BANK_STATEMENT_UI_ONLY",
  generated_at: "2026-08-08T00:00:00Z",
  source: { kind: "reconforge-enterprise-demo", local_first: true, external_calls: false },
  algorithm_version: "bank-statement-control-v1",
  decision_digest: "3bb2924b6af20aeb6285e9dfcbc46ad7dc46b845462f47e5b5d965fba4095d61",
  artifact_digest: "459510a87e4d5408abbc4a22e0b54f072a14edd1e74ed41ea437f63e49aeec86",
  tolerance: "0.01",
  currency: "EUR",
  date_window_days: 1,
  summary: { total: 3, matched: 2, exceptions: 0, unmatched: 1, ambiguous: 0 },
  decisions: [
    { bank_line_id: "BANK-CREDIT-001", account_id: "DE89370400440532013000", status: "matched", ledger_record_ids: ["LEDGER-CREDIT-001"], amount_variance: "0.00", days_variance: 0, reason_code: "BANK_LEDGER_RECONCILED" },
    { bank_line_id: "BANK-DEBIT-001", account_id: "DE89370400440532013000", status: "matched", ledger_record_ids: ["LEDGER-DEBIT-001"], amount_variance: "0.00", days_variance: 0, reason_code: "BANK_LEDGER_RECONCILED" },
    { bank_line_id: "LEDGER-UNMATCHED-001", account_id: "DE89370400440532013000", status: "unmatched_ledger", ledger_record_ids: ["LEDGER-UNMATCHED-001"], amount_variance: null, days_variance: null, reason_code: "LEDGER_RECORD_HAS_NO_BANK_LINE" },
  ],
  notices: [],
};

beforeEach(() => {
  vi.mocked(loadBankStatementStudio).mockResolvedValue(contract);
});

describe("BankStatementStudio", () => {
  test("renders exact decisions and filters without arithmetic", async () => {
    render(<BankStatementStudio translate={(key) => translate("en", key)} />);

    expect(await screen.findByRole("heading", { name: "Bank reconciliation control center" })).toBeInTheDocument();
    expect(screen.getAllByText("BANK_LEDGER_RECONCILED")).toHaveLength(2);
    expect(screen.getByText("LEDGER_RECORD_HAS_NO_BANK_LINE")).toBeInTheDocument();
    expect(screen.getByText("3bb2924b6af20aeb6285e9dfcbc46ad7dc46b845462f47e5b5d965fba4095d61")).toBeInTheDocument();

    fireEvent.change(screen.getByRole("combobox", { name: "Bank status" }), { target: { value: "matched" } });
    expect(screen.getByText("BANK-CREDIT-001")).toBeInTheDocument();
    expect(screen.queryByText("LEDGER-UNMATCHED-001")).not.toBeInTheDocument();
  });

  test("surfaces a malformed projection failure from the strict loader", async () => {
    vi.mocked(loadBankStatementStudio).mockRejectedValue(new Error("The local Studio bank statement artifact does not match schema version 1."));
    render(<BankStatementStudio translate={(key) => translate("en", key)} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Studio data is unavailable");
  });

  test("supports Arabic labels in the same read-only view", async () => {
    render(<BankStatementStudio translate={(key) => translate("ar", key)} />);
    expect(await screen.findByRole("heading", { name: "مركز رقابة مطابقة البنك" })).toBeInTheDocument();
    expect(screen.getByText("دليل الإعادة")).toBeInTheDocument();
  });
});
