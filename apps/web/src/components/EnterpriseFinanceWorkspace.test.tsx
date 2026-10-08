import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { BrowserSessionProvider } from "../browserSession";
import EnterpriseFinanceWorkspace from "./EnterpriseFinanceWorkspace";

describe("enterprise financial workspace", () => {
  it("starts with real identity authentication and no unverified balances", () => { render(<BrowserSessionProvider><EnterpriseFinanceWorkspace locale="en" /></BrowserSessionProvider>); expect(screen.getByRole("heading", { name: "Enterprise finance" })).toBeInTheDocument(); expect(screen.getByRole("form", { name: "Sign in" })).toBeInTheDocument(); expect(screen.getByLabelText("Password")).toHaveAttribute("type", "password"); expect(screen.queryByRole("table")).not.toBeInTheDocument(); });
  it("uses Arabic labels and RTL for the actual financial path", () => { const { container } = render(<BrowserSessionProvider><EnterpriseFinanceWorkspace locale="ar" /></BrowserSessionProvider>); expect(screen.getByRole("heading", { name: "المالية المؤسسية" })).toBeInTheDocument(); expect(container.querySelector("main")).toHaveAttribute("dir", "rtl"); expect(screen.getByLabelText("كلمة المرور")).toHaveAttribute("type", "password"); });
});
