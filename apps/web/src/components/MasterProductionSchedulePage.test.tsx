import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import MasterProductionSchedulePage from "./MasterProductionSchedulePage";

describe("MasterProductionSchedulePage", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("renders correctly in English and Arabic RTL modes", async () => {
    const { container: enContainer, unmount } = render(<MasterProductionSchedulePage locale="en" />);
    expect(screen.getByRole("heading", { name: "Master Production Schedule & Shortage Sourcing" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "MPS Planning Parameters" })).toBeInTheDocument();
    expect(enContainer.querySelector(".reporting-workspace")).toHaveAttribute("dir", "ltr");
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "MPS Plan & Procurement Summary" })).toBeInTheDocument();
    });
    unmount();

    const { container: arContainer } = render(<MasterProductionSchedulePage locale="ar" />);
    expect(screen.getByRole("heading", { name: "جدول الإنتاج الرئيسي وإدارة العجز المورّد (MPS & Sourcing)" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "معايير الجدولة والطلب" })).toBeInTheDocument();
    expect(arContainer.querySelector(".reporting-workspace")).toHaveAttribute("dir", "rtl");
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "ملخص الخطة والطلبات الناتجة" })).toBeInTheDocument();
    });
  });

  it("renders time-phased planning grid and automated shortage requisitions from initial seed plan", async () => {
    render(<MasterProductionSchedulePage locale="en" />);

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "MPS Time-Phased Planning Grid" })).toBeInTheDocument();
      expect(screen.getByRole("heading", { name: "Automated Shortage Purchase Requisitions" })).toBeInTheDocument();
    });

    // Schedule grid checks
    expect(screen.getByText("#0")).toBeInTheDocument();
    expect(screen.getAllByText("2026-11-01").length).toBeGreaterThan(0);
    expect(screen.getAllByText("1200").length).toBeGreaterThan(0);
    expect(screen.getAllByText("50").length).toBeGreaterThan(0);

    // Requisitions checks
    expect(screen.getByText("PR_MPS_2026_Q4_B0")).toBeInTheDocument();
    expect(screen.getAllByText("SUP_GLOBAL_PARTS").length).toBeGreaterThan(0);
    expect(screen.getAllByText("$450.00").length).toBeGreaterThan(0);
    expect(screen.getAllByText("APPROVED").length).toBeGreaterThan(0);
  });

  it("submits planning parameters to compute MPS schedule and updates view", async () => {
    const mockComputedPlan = {
      plan: {
        id: "mps_MPS_NEW_rev2",
        plan_id: "MPS_NEW",
        plan_name: "Automated Production Schedule",
        revision: "rev2",
        item_id: "SERVER_CHASSIS_X1",
        unit_of_measure: "EA",
        safety_stock_scaled: 600,
        lot_size_multiple_scaled: 1200,
        opening_inventory_scaled: 300,
        plan_digest: "new_mps_digest_abcdef1234567890abcdef1234567890abcdef1234567890",
        schedule_rows: [
          {
            bucket_index: 0,
            bucket_start_date: "2026-12-01",
            bucket_end_date: "2026-12-07",
            sales_orders_scaled: 1400,
            forecast_demand_scaled: 1100,
            net_demand_scaled: 1400,
            scheduled_receipts_scaled: 0,
            projected_available_balance_scaled: 100,
            net_requirement_scaled: 1100,
            planned_order_receipts_scaled: 1200,
            available_to_promise_scaled: 100,
          },
        ],
        sourcing_requisitions: [
          {
            requisition_id: "PR_MPS_NEW_B0",
            item_id: "SERVER_CHASSIS_X1",
            bucket_index: 0,
            required_date: "2026-12-01",
            shortage_quantity_scaled: 1100,
            order_quantity_scaled: 1200,
            preferred_supplier_id: "SUP_GLOBAL_PARTS",
            unit_price_ceiling_minor: 48000,
            currency: "USD",
          },
        ],
      },
    };

    vi.spyOn(globalThis, "fetch").mockImplementation((url) => {
      if (typeof url === "string" && url.includes("/compute")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(mockComputedPlan),
        } as Response);
      }
      return Promise.reject(new Error("Not found"));
    });

    render(<MasterProductionSchedulePage locale="en" />);

    // Wait for initial mount to settle
    await waitFor(() => {
      expect(screen.getByText("PR_MPS_2026_Q4_B0")).toBeInTheDocument();
    });

    const computeBtn = screen.getByRole("button", { name: "Compute MPS Schedule" });
    fireEvent.click(computeBtn);

    await waitFor(() => {
      expect(screen.getByText("MPS schedule and requisitions computed successfully")).toBeInTheDocument();
    });

    expect(screen.getByText("PR_MPS_NEW_B0")).toBeInTheDocument();
    expect(screen.getByText("$480.00")).toBeInTheDocument();
    expect(screen.getByText("new_mps_digest_abcdef1234567890abcdef1234567890abcdef1234567890")).toBeInTheDocument();
  });

  it("handles compute error with failure alert banner", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((url) => {
      if (typeof url === "string" && url.includes("/compute")) {
        return Promise.resolve({
          ok: false,
          status: 500,
        } as Response);
      }
      return Promise.reject(new Error("Not found"));
    });

    render(<MasterProductionSchedulePage locale="en" />);

    const computeBtn = screen.getByRole("button", { name: "Compute MPS Schedule" });
    fireEvent.click(computeBtn);

    await waitFor(() => {
      expect(screen.getByText("Failed to compute MPS schedule")).toBeInTheDocument();
    });
  });
});
