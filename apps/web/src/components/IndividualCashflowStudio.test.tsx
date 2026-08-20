import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, test, vi } from "vitest";

import { loadIndividualCashflowStudio } from "../data";
import { translate } from "../i18n";
import type { IndividualCashflowStudioContract } from "../types";
import { IndividualCashflowStudio } from "./IndividualCashflowStudio";

vi.mock("../data", () => ({
  loadIndividualCashflowStudio: vi.fn(),
}));

const contract: IndividualCashflowStudioContract = {
  schema_version: 1,
  synthetic_data_only: true,
  synthetic_data_marker: "SYNTHETIC_INDIVIDUAL_CASHFLOW_UI_ONLY",
  generated_at: "2026-08-10T00:00:00Z",
  source: { kind: "reconforge-enterprise-demo", local_first: true, external_calls: false },
  algorithm_version: "individual-cashflow-control-v1",
  decision_digest: "64d3e7a7e3c9972ac8f9b6c3f4f1cc9d9138b9f7a7edb8c4bc7a8d5afbb5c99a",
  artifact_digest: "9f7c4e2b1a69d8c3f0e5a7b4c2d6e8f90123456789abcdef0123456789abcdef",
  currency: "USD",
  summary: { total: 5, within_budget: 2, over_budget: 1, unbudgeted: 1, no_activity: 1 },
  decisions: [
    { period: "2026-07", flow_type: "income", category: "client-work", status: "within_budget", actual: "1800.00", budget: "2000.00", variance: "-200.00", transaction_ids: ["TX-001"], budget_id: "B-001", reason_code: "CASHFLOW_ACTIVITY_WITHIN_BUDGET" },
    { period: "2026-07", flow_type: "expense", category: "software", status: "within_budget", actual: "40.00", budget: "100.00", variance: "-60.00", transaction_ids: ["TX-002"], budget_id: "B-002", reason_code: "CASHFLOW_ACTIVITY_WITHIN_BUDGET" },
    { period: "2026-07", flow_type: "expense", category: "travel", status: "over_budget", actual: "250.00", budget: "100.00", variance: "150.00", transaction_ids: ["TX-003"], budget_id: "B-003", reason_code: "CASHFLOW_ACTIVITY_EXCEEDS_BUDGET" },
    { period: "2026-08", flow_type: "income", category: "other", status: "unbudgeted", actual: "50.00", budget: null, variance: "50.00", transaction_ids: ["TX-004"], budget_id: null, reason_code: "CASHFLOW_ACTIVITY_HAS_NO_BUDGET" },
    { period: "2026-08", flow_type: "expense", category: "software", status: "no_activity", actual: "0.00", budget: "100.00", variance: "-100.00", transaction_ids: [], budget_id: "B-004", reason_code: "CASHFLOW_BUDGET_HAS_NO_ACTIVITY" },
  ],
  notices: [],
};

beforeEach(() => {
  vi.mocked(loadIndividualCashflowStudio).mockResolvedValue(contract);
});

describe("IndividualCashflowStudio", () => {
  test("renders bounded decisions and filters by status", async () => {
    render(<IndividualCashflowStudio translate={(key) => translate("en", key)} />);

    expect(await screen.findByRole("heading", { name: "Individual and freelancer cashflow control center" })).toBeInTheDocument();
    expect(screen.getByText("client-work")).toBeInTheDocument();
    expect(screen.getByText("CASHFLOW_ACTIVITY_EXCEEDS_BUDGET")).toBeInTheDocument();
    expect(screen.getByText("64d3e7a7e3c9972ac8f9b6c3f4f1cc9d9138b9f7a7edb8c4bc7a8d5afbb5c99a")).toBeInTheDocument();

    fireEvent.change(screen.getByRole("combobox", { name: "Cashflow status" }), { target: { value: "over_budget" } });
    expect(screen.getByText("travel")).toBeInTheDocument();
    expect(screen.queryByText("client-work")).not.toBeInTheDocument();
  });

  test("surfaces malformed projection failures", async () => {
    vi.mocked(loadIndividualCashflowStudio).mockRejectedValue(new Error("individual_cashflow_contract_invalid"));
    render(<IndividualCashflowStudio translate={(key) => translate("en", key)} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Studio data is unavailable");
  });

  test("supports Arabic labels in the same read-only view", async () => {
    render(<IndividualCashflowStudio translate={(key) => translate("ar", key)} />);
    expect(await screen.findByRole("heading", { name: "مركز رقابة التدفق النقدي للفرد والمستقل" })).toBeInTheDocument();
    expect(screen.getByText("أدلة إعادة التشغيل")).toBeInTheDocument();
  });
});
