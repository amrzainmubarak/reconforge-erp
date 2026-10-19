import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { CrmSubscriptionWorkspace } from "./CrmSubscriptionWorkspace";

describe("CrmSubscriptionWorkspace", () => {
  it("renders correctly in English and Arabic RTL modes", () => {
    const { container: enContainer, unmount } = render(<CrmSubscriptionWorkspace locale="en" />);
    expect(screen.getByRole("heading", { name: "CRM Contracts & Prorated Subscriptions" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Opportunity Pipeline & Stages" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Quotation Governance" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Contract Lifecycle" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Subscription Day-Proration Calculator" })).toBeInTheDocument();
    expect(enContainer.querySelector(".financial-reporting")).toHaveAttribute("dir", "ltr");
    unmount();

    const { container: arContainer } = render(<CrmSubscriptionWorkspace locale="ar" />);
    expect(screen.getByRole("heading", { name: "عقود العملاء والاشتراكات النسبية المحكومة" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "مسار الفرص البيعية (Opportunity Pipeline)" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "حوكمة عروض الأسعار" })).toBeInTheDocument();
    expect(arContainer.querySelector(".financial-reporting")).toHaveAttribute("dir", "rtl");
  });

  it("progresses an opportunity through pipeline stages to Won", () => {
    render(<CrmSubscriptionWorkspace locale="en" />);

    const getOppArticle = () => screen.getByText("Cloud Infrastructure Upgrade").closest("article")!;
    
    // Initial: Prospecting (20%)
    expect(within(getOppArticle()).getByText("20%")).toBeInTheDocument();

    // Advance to Qualified (40%)
    fireEvent.click(within(getOppArticle()).getByRole("button", { name: "Advance Stage →" }));
    expect(within(getOppArticle()).getByText("40%")).toBeInTheDocument();

    // Advance to Proposal (60%)
    fireEvent.click(within(getOppArticle()).getByRole("button", { name: "Advance Stage →" }));
    expect(within(getOppArticle()).getByText("60%")).toBeInTheDocument();

    // Advance to Negotiation (80%)
    fireEvent.click(within(getOppArticle()).getByRole("button", { name: "Advance Stage →" }));
    expect(within(getOppArticle()).getByText("80%")).toBeInTheDocument();

    // Advance to Won (100%)
    fireEvent.click(within(getOppArticle()).getByRole("button", { name: "Advance Stage →" }));
    expect(within(getOppArticle()).getByText("100%")).toBeInTheDocument();
    // Won opportunities have no further advance button
    expect(within(getOppArticle()).queryByRole("button", { name: "Advance Stage →" })).not.toBeInTheDocument();
  });

  it("enforces Separation of Duties (SoD) on quotation discount approvals", () => {
    render(<CrmSubscriptionWorkspace locale="en" />);

    // In fixture, QUO-801 submitter is SALES_USER_01
    // Set approver to SALES_USER_01 to trigger self-approval SoD check
    const approverInput = screen.getByLabelText("Approver User ID:");
    fireEvent.change(approverInput, { target: { value: "SALES_USER_01" } });

    const approveQuoBtn = screen.getByRole("button", { name: "Approve" });
    fireEvent.click(approveQuoBtn);

    // Verify error banner
    const feedback = screen.getByRole("status");
    expect(feedback).toHaveAttribute("aria-live", "polite");
    expect(feedback).toHaveTextContent("Separation of Duties violation: Submitter cannot approve their own quotation!");
  });

  it("approves quotation discount when approver is an independent authority", () => {
    render(<CrmSubscriptionWorkspace locale="en" />);

    // Set an independent approver
    const approverInput = screen.getByLabelText("Approver User ID:");
    fireEvent.change(approverInput, { target: { value: "SALES_VP_INDEPENDENT" } });

    const approveQuoBtn = screen.getByRole("button", { name: "Approve" });
    fireEvent.click(approveQuoBtn);

    const feedback = screen.getByRole("status");
    expect(feedback).toHaveAttribute("aria-live", "polite");
    expect(feedback).toHaveTextContent("approved successfully");
  });

  it("transitions contract lifecycle states correctly", () => {
    render(<CrmSubscriptionWorkspace locale="en" />);

    // Initially CON-2026-01 is Active and CON-2026-02 is Suspended (1 Resume button)
    expect(screen.getAllByRole("button", { name: "Resume" }).length).toBe(1);

    // Suspend CON-2026-01
    const suspendBtn = screen.getByRole("button", { name: "Suspend" });
    fireEvent.click(suspendBtn);

    const feedback = screen.getByRole("status");
    expect(feedback).toHaveTextContent("Action (Suspend) executed on CON-2026-01");

    // Both CON-2026-01 and CON-2026-02 are now Suspended (2 Resume buttons)
    expect(screen.getAllByRole("button", { name: "Resume" }).length).toBe(2);
  });

  it("computes exact integer minor-unit day proration without floating-point math", () => {
    render(<CrmSubscriptionWorkspace locale="en" />);

    // Default: 100,000 minor units, cycle 2026-10-01 to 2026-10-31 (31 days), service start 2026-10-11 (21 active days)
    // 100000 * 21 / 31 = 67741.935... Math.round = 67742 ($677.42)
    // refund = 100000 - 67742 = 32258 ($322.58)
    expect(screen.getByText("677.42")).toBeInTheDocument();
    expect(screen.getByText("322.58")).toBeInTheDocument();

    // Change service start to 2026-10-16 (16 active days)
    // 100000 * 16 / 31 = 51612.9... Math.round = 51613 ($516.13)
    // refund = 100000 - 51613 = 48387 ($483.87)
    const serviceInput = screen.getByLabelText("Effective Service Start");
    fireEvent.change(serviceInput, { target: { value: "2026-10-16" } });

    expect(screen.getByText("516.13")).toBeInTheDocument();
    expect(screen.getByText("483.87")).toBeInTheDocument();
  });
});
