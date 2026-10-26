import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { translate } from "../i18n";
import { MobileDock, Sidebar, navigationGroupForPage } from "./Navigation";

const props = { translate: (key: Parameters<typeof translate>[1]) => translate("en", key), collapsed: false, mobileOpen: false, onCollapse: vi.fn(), onMobileClose: vi.fn(), activePage: "enterpriseFinance" as const, onNavigate: vi.fn() };

it("keeps the active section expanded through collapse and expansion", () => {
  const view = render(<Sidebar {...props} />);
  const active = () => screen.getByRole("button", { name: "Finance & reporting" }).closest("details");
  expect(active()).toHaveAttribute("open");
  view.rerender(<Sidebar {...props} collapsed />);
  expect(view.container.querySelectorAll(".nav-group[open]")).toHaveLength(8);
  view.rerender(<Sidebar {...props} />);
  expect(active()).toHaveAttribute("open");
  expect(view.container.querySelectorAll(".nav-group[open]")).toHaveLength(1);
});

it("lets users open a task section and opens every matching section while searching", () => {
  const view = render(<Sidebar {...props} />);
  fireEvent.click(screen.getByText("People & projects", { selector: "summary" }));
  expect(screen.getByRole("button", { name: "Project WBS & milestone billing" }).closest("details")).toHaveAttribute("open");
  fireEvent.change(screen.getByRole("searchbox"), { target: { value: "financial" } });
  for (const group of view.container.querySelectorAll(".nav-group")) expect(group).toHaveAttribute("open");
  fireEvent.change(screen.getByRole("searchbox"), { target: { value: "no-such-destination" } });
  expect(screen.getByRole("status")).toHaveTextContent("No destinations match");
});

it("filters denied destinations before either grouping or searching", () => {
  render(<Sidebar {...props} canView={page => page === "hcmLeave"} />);
  fireEvent.change(screen.getByRole("searchbox"), { target: { value: "CRM" } });
  expect(screen.queryByRole("button", { name: "CRM contracts & prorated subscriptions" })).not.toBeInTheDocument();
  expect(screen.getByRole("status")).toHaveTextContent("No destinations match");
});

it("uses the same group for canonical and retained project/CRM aliases", () => {
  expect(navigationGroupForPage("crmContracts")).toBe(navigationGroupForPage("crmSubscriptions"));
  expect(navigationGroupForPage("projectMilestoneBilling")).toBe(navigationGroupForPage("projectMilestones"));
});

it("applies the same capability filter to mobile shortcuts", () => {
  render(<MobileDock translate={props.translate} onMenu={vi.fn()} onQuickAction={vi.fn()} activePage="enterpriseFinance" onNavigate={vi.fn()} canView={() => false} />);
  expect(screen.getAllByRole("button")).toHaveLength(1);
  expect(screen.getByRole("button", { name: "Menu" })).toBeInTheDocument();
});
