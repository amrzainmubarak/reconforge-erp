import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ProjectMilestoneWorkspace } from "./ProjectMilestoneWorkspace";

describe("ProjectMilestoneWorkspace", () => {
  it("renders correctly in English and Arabic RTL modes", () => {
    const { container: enContainer, unmount } = render(<ProjectMilestoneWorkspace locale="en" />);
    expect(screen.getByRole("heading", { name: "Project WBS & Milestone Billing" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Real-Time Financial Posture" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Work Breakdown Structure (WBS)" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Role Rate Cards" })).toBeInTheDocument();
    expect(enContainer.querySelector(".financial-reporting")).toHaveAttribute("dir", "ltr");
    unmount();

    const { container: arContainer } = render(<ProjectMilestoneWorkspace locale="ar" />);
    expect(screen.getByRole("heading", { name: "هيكل تجزئة المشروع وفوترة المراحل" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "الموقف المالي في الوقت الفعلي" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "هيكل تجزئة العمل (WBS)" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "بطاقات أسعار الأدوار" })).toBeInTheDocument();
    expect(arContainer.querySelector(".financial-reporting")).toHaveAttribute("dir", "rtl");
  });

  it("displays real-time financial posture metrics computed from integer minor units", () => {
    render(<ProjectMilestoneWorkspace locale="en" />);

    const postureRegion = screen.getByRole("region", { name: "Real-Time Financial Posture" });
    const { getByText } = within(postureRegion);

    // Contract value: $500,000.00, Billed: $300,000.00, Unrecognized: $200,000.00, Remaining: $145,000.00
    expect(getByText("$500,000.00")).toBeInTheDocument();
    expect(getByText("$300,000.00")).toBeInTheDocument();
    expect(getByText("$200,000.00")).toBeInTheDocument();
    expect(getByText("$145,000.00")).toBeInTheDocument();
  });

  it("renders WBS hierarchical tasks and work packages with progress and cost metrics", () => {
    render(<ProjectMilestoneWorkspace locale="en" />);

    expect(screen.getByText("1.0")).toBeInTheDocument();
    expect(screen.getByText("Architecture & Requirements Blueprint")).toBeInTheDocument();
    expect(screen.getByText("1.1")).toBeInTheDocument();
    expect(screen.getByText("Financial Database Schema Modeling")).toBeInTheDocument();
    expect(screen.getByText("2.0")).toBeInTheDocument();
    expect(screen.getByText("Core Engine Implementation & Governance")).toBeInTheDocument();
  });

  it("displays role rate cards with standard and overtime hourly rates", () => {
    render(<ProjectMilestoneWorkspace locale="en" />);

    expect(screen.getByText("PRIN_ARCH")).toBeInTheDocument();
    expect(screen.getByText("Principal Financial Systems Architect")).toBeInTheDocument();
    expect(screen.getByText("$250.00")).toBeInTheDocument();
    expect(screen.getByText("$375.00")).toBeInTheDocument();

    expect(screen.getByText("SR_DEV")).toBeInTheDocument();
    expect(screen.getByText("SEC_AUDIT")).toBeInTheDocument();
  });

  it("verifies deliverable for a pending milestone and updates status with accessible feedback", () => {
    render(<ProjectMilestoneWorkspace locale="en" />);

    // Milestone 4 is Pending
    const verifyButtons = screen.getAllByRole("button", { name: "Verify Deliverable ✓" });
    expect(verifyButtons.length).toBe(1);

    fireEvent.click(verifyButtons[0]);

    // Live feedback banner should notify screen reader
    const statusRegion = screen.getByRole("status");
    expect(statusRegion).toHaveAttribute("aria-live", "polite");
    expect(statusRegion).toHaveTextContent("Deliverables verified for MLS-04");

    // MLS-04 should now have Generate Invoice button
    expect(screen.getAllByRole("button", { name: "Generate Invoice 📄" }).length).toBe(2);
  });

  it("generates invoice for verified milestone and updates billed/unrecognized financial posture", () => {
    render(<ProjectMilestoneWorkspace locale="en" />);

    // Milestone 3 is Verified with amount $100,000.00
    const billBtn = screen.getByRole("button", { name: "Generate Invoice 📄" });
    fireEvent.click(billBtn);

    // Live feedback
    const statusRegion = screen.getByRole("status");
    expect(statusRegion).toHaveAttribute("aria-live", "polite");
    expect(statusRegion).toHaveTextContent("Billing invoice generated for MLS-03");

    const postureRegion = screen.getByRole("region", { name: "Real-Time Financial Posture" });
    const { getByText } = within(postureRegion);

    // Billed to date should increase from $300,000.00 to $400,000.00
    expect(getByText("$400,000.00")).toBeInTheDocument();
    // Unrecognized revenue should decrease from $200,000.00 to $100,000.00
    expect(getByText("$100,000.00")).toBeInTheDocument();
  });
});
