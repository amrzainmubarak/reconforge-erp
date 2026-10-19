import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import ConsolidatedStatementsPage from "./ConsolidatedStatementsPage";

describe("ConsolidatedStatementsPage", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("renders correctly in English and Arabic RTL modes", async () => {
    const { container: enContainer, unmount } = render(<ConsolidatedStatementsPage locale="en" />);
    expect(screen.getByRole("heading", { name: "Group Consolidated Financial Statements" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Consolidation Parameters" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Consolidated Statement Run Ledger" })).toBeInTheDocument();
    expect(enContainer.querySelector(".reporting-workspace")).toHaveAttribute("dir", "ltr");
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Consolidated Financial Posture" })).toBeInTheDocument();
    });
    unmount();

    const { container: arContainer } = render(<ConsolidatedStatementsPage locale="ar" />);
    expect(screen.getByRole("heading", { name: "القوائم المالية الموحدة للمجموعة" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "معايير التوحيد المالي" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "سجل التشغيل والأدلة المحفوظة" })).toBeInTheDocument();
    expect(arContainer.querySelector(".reporting-workspace")).toHaveAttribute("dir", "rtl");
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "الملخص المالي الموحد" })).toBeInTheDocument();
    });
  });

  it("displays fallback consolidated financial posture metrics and cryptographic digest", async () => {
    render(<ConsolidatedStatementsPage locale="en" />);

    // Wait for fallback metrics to be mounted
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Consolidated Financial Posture" })).toBeInTheDocument();
    });

    expect(screen.getByText("$4,250,000")).toBeInTheDocument();
    expect(screen.getByText("$1,500,000")).toBeInTheDocument();
    expect(screen.getByText("$2,750,000")).toBeInTheDocument();
    expect(screen.getByText("$320,000")).toBeInTheDocument();
    expect(screen.getByText("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855")).toBeInTheDocument();
  });

  it("submits consolidation form and renders success notification", async () => {
    const mockRun = {
      run_id: "csr_GRP_GLOBAL_CORP_FY2026_Q3_NEW",
      id: "csr_GRP_GLOBAL_CORP_FY2026_Q3_NEW",
      group_id: "GRP_GLOBAL_CORP",
      organization_id: "ORG_HOLDING",
      reporting_currency: "USD",
      period_id: "FY2026_Q3",
      period_start: "2026-07-01",
      period_end: "2026-09-30",
      as_of_date: "2026-09-30",
      report_digest: "new_digest_1234567890abcdef1234567890abcdef1234567890abcdef1234567890ab",
      prepared_by: "enterprise_auditor",
      created_at: "2026-10-19T12:00:00Z",
      statements: {
        balance_sheet: {
          total_assets_minor: 500000000,
          total_liabilities_minor: 200000000,
          total_equity_minor: 300000000,
          nci_equity_minor: 30000000,
        },
        income_statement: {
          gross_profit_minor: 90000000,
          operating_income_minor: 50000000,
          consolidated_net_income_minor: 40000000,
          parent_net_income_minor: 36000000,
          nci_net_income_minor: 4000000,
        },
      },
    };

    vi.spyOn(globalThis, "fetch").mockImplementation((url) => {
      if (typeof url === "string" && url.includes("/generate")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(mockRun),
        } as Response);
      }
      return Promise.reject(new Error("Not found"));
    });

    render(<ConsolidatedStatementsPage locale="en" />);

    const generateBtn = screen.getByRole("button", { name: "Generate Statements" });
    fireEvent.click(generateBtn);

    await waitFor(() => {
      expect(screen.getByText("Consolidated financial statements generated successfully")).toBeInTheDocument();
    });

    expect(screen.getByText("$5,000,000")).toBeInTheDocument();
    expect(screen.getByText("new_digest_1234567890abcdef1234567890abcdef1234567890abcdef1234567890ab")).toBeInTheDocument();
  });

  it("handles generation error gracefully with failure alert", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((url) => {
      if (typeof url === "string" && url.includes("/generate")) {
        return Promise.resolve({
          ok: false,
          status: 500,
        } as Response);
      }
      return Promise.reject(new Error("Not found"));
    });

    render(<ConsolidatedStatementsPage locale="en" />);

    const generateBtn = screen.getByRole("button", { name: "Generate Statements" });
    fireEvent.click(generateBtn);

    await waitFor(() => {
      expect(screen.getByText("Statement generation failed")).toBeInTheDocument();
    });
  });

  it("allows selecting a historical run from the ledger to inspect statements", async () => {
    render(<ConsolidatedStatementsPage locale="en" />);

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Inspect" })).toBeInTheDocument();
    });

    const inspectBtn = screen.getByRole("button", { name: "Inspect" });
    fireEvent.click(inspectBtn);

    expect(screen.getByText("csr_GRP_GLOBAL_CORP_FY2026_Q3_a1b2c3d4")).toBeInTheDocument();
    expect(screen.getByText("$4,250,000")).toBeInTheDocument();
  });
});
