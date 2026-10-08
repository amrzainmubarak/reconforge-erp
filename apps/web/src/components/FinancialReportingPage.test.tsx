import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { BrowserSessionProvider } from "../browserSession";
import FinancialReportingPage from "./FinancialReportingPage";
describe("financial reporting interface", () => {
  it("starts at real authentication and renders no invented balance", () => { render(<BrowserSessionProvider><FinancialReportingPage locale="en" /></BrowserSessionProvider>); expect(screen.getByRole("heading", { name: "Financial statements" })).toBeInTheDocument(); expect(screen.getByRole("form", { name: "Sign in" })).toBeInTheDocument(); expect(screen.getByLabelText("Password")).toHaveAttribute("type", "password"); expect(screen.queryByRole("table")).not.toBeInTheDocument(); });
  it("presents the actual Arabic authentication path with RTL", () => { const { container } = render(<BrowserSessionProvider><FinancialReportingPage locale="ar" /></BrowserSessionProvider>); expect(screen.getByRole("heading", { name: "القوائم المالية" })).toBeInTheDocument(); expect(container.querySelector("main")).toHaveAttribute("dir", "rtl"); expect(screen.getByLabelText("كلمة المرور")).toHaveAttribute("type", "password"); });
});
