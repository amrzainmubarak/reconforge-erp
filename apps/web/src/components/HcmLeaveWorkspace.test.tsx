import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { HcmLeaveWorkspace } from "./HcmLeaveWorkspace";

describe("HcmLeaveWorkspace", () => {
  it("renders correctly in English and Arabic RTL modes", () => {
    const { container: enContainer, unmount } = render(<HcmLeaveWorkspace locale="en" />);
    expect(screen.getByRole("heading", { name: "Employee Leave & Absence Governance" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Employee Leave Balances" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Submit Leave Request" })).toBeInTheDocument();
    expect(enContainer.querySelector(".financial-reporting")).toHaveAttribute("dir", "ltr");
    unmount();

    const { container: arContainer } = render(<HcmLeaveWorkspace locale="ar" />);
    expect(screen.getByRole("heading", { name: "إدارة إجازات وغيابات الموظفين" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "أرصدة إجازات الموظف" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "تقديم طلب إجازة" })).toBeInTheDocument();
    expect(arContainer.querySelector(".financial-reporting")).toHaveAttribute("dir", "rtl");
  });

  it("submits a new leave request with valid parameters and renders status feedback", () => {
    render(<HcmLeaveWorkspace locale="en" />);
    
    // Fill form
    const empInput = screen.getByLabelText("Employee ID");
    fireEvent.change(empInput, { target: { value: "EMP-2005" } });
    
    const reasonInput = screen.getByLabelText("Reason");
    fireEvent.change(reasonInput, { target: { value: "Professional development workshop" } });

    const submitBtn = screen.getByRole("button", { name: "Submit Leave Request" });
    fireEvent.click(submitBtn);

    const feedback = screen.getByRole("status");
    expect(feedback).toHaveAttribute("aria-live", "polite");
    expect(feedback).toHaveTextContent("Leave request submitted successfully");
    expect(screen.getByText("Professional development workshop")).toBeInTheDocument();
  });

  it("enforces Separation of Duties (SoD) by rejecting approval when approver equals requester", () => {
    render(<HcmLeaveWorkspace locale="en" />);

    // In the fixture, LR-2026-001 has employee_user_id "EMP-1001"
    // Set current approver user ID to match the requester
    const approverInput = screen.getByLabelText("Current Approver:");
    fireEvent.change(approverInput, { target: { value: "EMP-1001" } });

    // Find the row for LR-2026-001 and click Approve
    const approveButtons = screen.getAllByRole("button", { name: "Approve" });
    expect(approveButtons.length).toBeGreaterThan(0);
    fireEvent.click(approveButtons[0]);

    // Verify SoD rejection feedback
    const feedback = screen.getByRole("status");
    expect(feedback).toHaveAttribute("aria-live", "polite");
    expect(feedback).toHaveTextContent("Separation of Duties violation: Approver cannot be the employee requesting leave!");
  });

  it("approves leave when approver differs from requester and deducts from remaining balance", () => {
    render(<HcmLeaveWorkspace locale="en" />);

    // Ensure distinct approver
    const approverInput = screen.getByLabelText("Current Approver:");
    fireEvent.change(approverInput, { target: { value: "MGR-AUDIT-99" } });

    // Initial annual balance is 14 remaining
    expect(screen.getByText(/14\s+days/)).toBeInTheDocument();

    const approveButtons = screen.getAllByRole("button", { name: "Approve" });
    fireEvent.click(approveButtons[0]);

    const feedback = screen.getByRole("status");
    expect(feedback).toHaveTextContent("approved successfully");

    // After approving 5 days of annual leave, remaining days should decrease from 14 to 9
    expect(screen.getByText(/9\s+days/)).toBeInTheDocument();
  });

  it("cancels an approved request and restores deducted balance", () => {
    render(<HcmLeaveWorkspace locale="en" />);

    // LR-2026-002 is already approved for 2 days of sick leave
    // Initial remaining sick days is 12
    expect(screen.getByText(/12\s+days/)).toBeInTheDocument();

    const cancelBtn = screen.getByRole("button", { name: "Cancel" });
    fireEvent.click(cancelBtn);

    const feedback = screen.getByRole("status");
    expect(feedback).toHaveTextContent("cancelled and balance restored");

    // Restitution adds 2 days back to remaining sick days (12 + 2 = 14), so both annual and sick now show 14 days
    expect(screen.getAllByText(/14\s+days/).length).toBe(2);
  });

  it("allows withdrawal of a submitted request", () => {
    render(<HcmLeaveWorkspace locale="en" />);

    const withdrawBtn = screen.getByRole("button", { name: "Withdraw" });
    fireEvent.click(withdrawBtn);

    const feedback = screen.getByRole("status");
    expect(feedback).toHaveTextContent("withdrawn");
  });
});
