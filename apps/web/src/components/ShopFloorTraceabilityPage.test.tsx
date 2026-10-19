import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import ShopFloorTraceabilityPage from "./ShopFloorTraceabilityPage";

describe("ShopFloorTraceabilityPage", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("renders correctly in English and Arabic RTL modes", () => {
    const { container: enContainer, unmount } = render(<ShopFloorTraceabilityPage locale="en" />);
    expect(screen.getByRole("heading", { name: "Shop Floor Execution & Bidirectional Lot Genealogy" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Genealogy Traversal Parameters" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Lot Genealogy Visual Tree" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Routing Steps for Order: WO_SRV_2026_01" })).toBeInTheDocument();
    expect(enContainer.querySelector(".reporting-workspace")).toHaveAttribute("dir", "ltr");
    unmount();

    const { container: arContainer } = render(<ShopFloorTraceabilityPage locale="ar" />);
    expect(screen.getByRole("heading", { name: "تنفيذ صالة الإنتاج والتتبع الجيني للتشغيل والدفعات" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "البحث والتتبع الجيني للدفعة" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "شجرة الأنساب والتتبع للدفعة" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "خطوات التشغيل وتنفيذ أمر الإنتاج المحفوظ" })).toBeInTheDocument();
    expect(arContainer.querySelector(".reporting-workspace")).toHaveAttribute("dir", "rtl");
  });

  it("renders hierarchical multi-tier lot genealogy visual tree", () => {
    render(<ShopFloorTraceabilityPage locale="en" />);

    // Root node
    expect(screen.getAllByText("LOT_FG_SERVER_001").length).toBeGreaterThan(0);
    expect(screen.getByText("FINISHED_SERVER_RACK")).toBeInTheDocument();

    // Intermediate and leaf nodes
    expect(screen.getByText("LOT_RAW_CHIP_901")).toBeInTheDocument();
    expect(screen.getByText("CPU_MAIN_PROCESSOR")).toBeInTheDocument();
    expect(screen.getByText("LOT_RAW_PCB_402")).toBeInTheDocument();
    expect(screen.getByText("SERVER_MOTHERBOARD")).toBeInTheDocument();
    expect(screen.getByText("LOT_RAW_CAPACITOR_101")).toBeInTheDocument();
    expect(screen.getByText("ELECTROLYTIC_CAPACITOR")).toBeInTheDocument();
  });

  it("renders dispatch routing steps with quantity conservation and scrap reasons", () => {
    render(<ShopFloorTraceabilityPage locale="en" />);

    // Step 1
    expect(screen.getByText("WC_SMT_ASSEMBLY")).toBeInTheDocument();
    expect(screen.getByText("TECH_ALICE")).toBeInTheDocument();
    expect(screen.getByText("42")).toBeInTheDocument();

    // Step 2 with scrap
    expect(screen.getByText("WC_FINAL_TESTING")).toBeInTheDocument();
    expect(screen.getByText("TECH_BOB")).toBeInTheDocument();
    expect(screen.getByText("35")).toBeInTheDocument();
    expect(screen.getByText("495")).toBeInTheDocument();
    expect(screen.getByText("5")).toBeInTheDocument();
    expect(screen.getByText("THERMAL_FAILURE")).toBeInTheDocument();
  });

  it("submits genealogy traversal query and updates tree from API response", async () => {
    const mockTree = {
      tree: {
        lot_id: "LOT_RAW_CHIP_901",
        item_id: "CPU_MAIN_PROCESSOR",
        direction: "forward",
        children: [
          {
            lot_id: "LOT_FG_SERVER_001",
            item_id: "FINISHED_SERVER_RACK",
            direction: "forward",
            children: [],
          },
        ],
      },
    };

    vi.spyOn(globalThis, "fetch").mockImplementation(() => {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve(mockTree),
      } as Response);
    });

    render(<ShopFloorTraceabilityPage locale="en" />);

    const lotInput = screen.getByLabelText("Lot / Batch ID");
    fireEvent.change(lotInput, { target: { value: "LOT_RAW_CHIP_901" } });

    const dirSelect = screen.getByLabelText("Trace Direction");
    fireEvent.change(dirSelect, { target: { value: "forward" } });

    const traceBtn = screen.getByRole("button", { name: "Trace Genealogy" });
    fireEvent.click(traceBtn);

    await waitFor(() => {
      expect(screen.getByText("Lot genealogy tree traced successfully")).toBeInTheDocument();
    });
  });

  it("falls back to local verification message when genealogy API call fails", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() => {
      return Promise.reject(new Error("Network offline"));
    });

    render(<ShopFloorTraceabilityPage locale="en" />);

    const traceBtn = screen.getByRole("button", { name: "Trace Genealogy" });
    fireEvent.click(traceBtn);

    await waitFor(() => {
      expect(screen.getByText("Displaying locally verified lot genealogy")).toBeInTheDocument();
    });
  });
});
