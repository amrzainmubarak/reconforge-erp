import { act, fireEvent, render, screen } from "@testing-library/react";
import { lazy, Suspense, type ReactNode } from "react";
import { afterEach, expect, it, vi } from "vitest";

import { WorkspaceErrorBoundary } from "./WorkspaceErrorBoundary";

afterEach(() => vi.unstubAllGlobals());

it("renders a healthy workspace without executing recovery actions", () => {
  const onDashboard = vi.fn(), onReload = vi.fn();
  render(<WorkspaceErrorBoundary locale="en" onDashboard={onDashboard} onReload={onReload}><main>Healthy native workspace</main></WorkspaceErrorBoundary>);
  expect(screen.getByRole("main")).toHaveTextContent("Healthy native workspace");
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(onDashboard).not.toHaveBeenCalled(); expect(onReload).not.toHaveBeenCalled();
});

it.each([
  ["en", "ltr", "Workspace unavailable", "Open dashboard", "Reload page"],
  ["ar", "rtl", "مساحة العمل غير متاحة", "فتح لوحة المتابعة", "إعادة تحميل الصفحة"],
] as const)("contains a synchronous failure safely in %s with focused native recovery controls", (locale, direction, title, dashboard, reload) => {
  const caught: unknown[] = [], onDashboard = vi.fn(), onReload = vi.fn(), network = vi.fn();
  vi.stubGlobal("fetch", network);
  const privateError = new Error("PRIVATE_ACCOUNT_123456; token=PRIVATE_SECRET; <script id=PRIVATE_SCRIPT>");
  function FailedWorkspace(): ReactNode { throw privateError; }
  render(<>
    <nav aria-label="Existing navigation">Existing sidebar</nav>
    <WorkspaceErrorBoundary locale={locale} onDashboard={onDashboard} onReload={onReload}><FailedWorkspace /></WorkspaceErrorBoundary>
    <footer>Existing mobile dock</footer>
  </>, { onCaughtError: error => caught.push(error) });
  // Root-specific expected-error capture leaves console.error globally intact.
  expect(caught).toContain(privateError);
  expect(screen.getByRole("navigation")).toHaveTextContent("Existing sidebar");
  expect(screen.getByText("Existing mobile dock")).toBeInTheDocument();
  expect(screen.getByRole("heading", { level: 1, name: title })).toBeInTheDocument();
  expect(screen.getByRole("main")).toHaveAttribute("id", "main-content");
  expect(screen.getByRole("main")).toHaveAttribute("dir", direction);
  expect(screen.getByRole("alert")).toHaveFocus();
  expect(screen.getByRole("alert")).toHaveTextContent("RF-WORKSPACE-001");
  for (const secret of ["PRIVATE_ACCOUNT_123456", "PRIVATE_SECRET", "PRIVATE_SCRIPT", privateError.stack!]) expect(document.body.textContent).not.toContain(secret);
  expect(document.getElementById("PRIVATE_SCRIPT")).toBeNull();
  const dashboardButton = screen.getByRole("button", { name: dashboard }), reloadButton = screen.getByRole("button", { name: reload });
  dashboardButton.focus(); expect(dashboardButton).toHaveFocus(); reloadButton.focus(); expect(reloadButton).toHaveFocus();
  expect(onDashboard).not.toHaveBeenCalled(); expect(onReload).not.toHaveBeenCalled(); expect(network).not.toHaveBeenCalled();
  fireEvent.click(dashboardButton); expect(onDashboard).toHaveBeenCalledTimes(1); expect(onReload).not.toHaveBeenCalled();
  fireEvent.click(reloadButton); expect(onReload).toHaveBeenCalledTimes(1); expect(network).not.toHaveBeenCalled();
});

it("contains a rejected lazy workspace while preserving Suspense and makes no automatic retry", async () => {
  let reject!: (reason: unknown) => void;
  const loader = vi.fn(() => new Promise<{ default: () => ReactNode }>((_resolve, rejectModule) => { reject = rejectModule; }));
  const LazyWorkspace = lazy(loader), caught: unknown[] = [], onDashboard = vi.fn(), onReload = vi.fn();
  const view = render(<WorkspaceErrorBoundary key="customerReturns" locale="en" onDashboard={onDashboard} onReload={onReload}>
    <Suspense fallback={<p role="status">Loading workspace</p>}><LazyWorkspace /></Suspense>
  </WorkspaceErrorBoundary>, { onCaughtError: error => caught.push(error) });
  expect(screen.getByRole("status")).toHaveTextContent("Loading workspace");
  const failure = new Error("Failed lazy asset with PRIVATE_FINANCIAL_DETAILS");
  await act(async () => reject(failure));
  expect(caught).toContain(failure);
  expect(screen.getByRole("alert")).toHaveFocus();
  expect(document.body.textContent).not.toContain("PRIVATE_FINANCIAL_DETAILS");
  expect(loader).toHaveBeenCalledTimes(1); expect(onDashboard).not.toHaveBeenCalled(); expect(onReload).not.toHaveBeenCalled();
  view.rerender(<WorkspaceErrorBoundary key="customerReturns" locale="ar" onDashboard={onDashboard} onReload={onReload}>
    <Suspense fallback={<p role="status">Loading workspace</p>}><LazyWorkspace /></Suspense>
  </WorkspaceErrorBoundary>);
  expect(screen.getByRole("heading", { name: "مساحة العمل غير متاحة" })).toBeInTheDocument();
  expect(loader).toHaveBeenCalledTimes(1);
  view.rerender(<WorkspaceErrorBoundary key="dashboard" locale="ar" onDashboard={onDashboard} onReload={onReload}>
    <main>Authorized read workspace</main>
  </WorkspaceErrorBoundary>);
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(screen.getByRole("main")).toHaveTextContent("Authorized read workspace");
});
