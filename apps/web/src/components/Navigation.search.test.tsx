import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import { translate } from "../i18n";
import { Sidebar } from "./Navigation";

const base = { collapsed: false, mobileOpen: false, onCollapse: vi.fn(), onMobileClose: vi.fn(), activePage: "enterpriseFinance" as const, onNavigate: vi.fn() };

it.each(["en", "ar"] as const)("restores navigation after choosing a search result (%s)", locale => {
  const view = render(<Sidebar {...base} translate={key => translate(locale, key)} />);
  const search = screen.getByRole("searchbox", { name: translate(locale, "navFilter") });
  fireEvent.change(search, { target: { value: translate(locale, "hcmLeave") } });
  fireEvent.click(screen.getByRole("button", { name: translate(locale, "hcmLeave") }));
  expect(base.onNavigate).toHaveBeenLastCalledWith("hcmLeave");
  expect(search).toHaveValue("");
  expect(view.container.querySelectorAll(".nav-group")).toHaveLength(8);
  view.rerender(<Sidebar {...base} activePage="hcmLeave" translate={key => translate(locale, key)} />);
  expect(screen.getByRole("button", { name: translate(locale, "hcmLeave") })).toHaveAttribute("aria-current", "page");
});

it("restores the selected section when searching for the current page", () => {
  const view = render(<Sidebar {...base} translate={key => translate("en", key)} />);
  fireEvent.click(screen.getByText("People & projects", { selector: "summary" }));
  const search = screen.getByRole("searchbox", { name: "Find a workspace" });
  fireEvent.change(search, { target: { value: "Finance & reporting" } });
  fireEvent.click(screen.getByRole("button", { name: "Finance & reporting" }));
  expect(search).toHaveValue("");
  expect(view.container.querySelector(".nav-item--active")?.closest("details")).toHaveAttribute("open");
});

it("never exposes a denied page after a permitted search result is selected", () => {
  const canView = (page: Parameters<NonNullable<React.ComponentProps<typeof Sidebar>["canView"]>>[0]) => page !== "hcmLeave";
  render(<Sidebar {...base} canView={canView} translate={key => translate("en", key)} />);
  const search = screen.getByRole("searchbox", { name: "Find a workspace" });
  fireEvent.change(search, { target: { value: "Finance & reporting" } });
  fireEvent.click(screen.getByRole("button", { name: "Finance & reporting" }));
  expect(screen.queryByRole("button", { name: translate("en", "hcmLeave"), hidden: true })).not.toBeInTheDocument();
});

it("keeps denied pages hidden when a mobile search is cleared for the icon rail", () => {
  const canView = (page: Parameters<NonNullable<React.ComponentProps<typeof Sidebar>["canView"]>>[0]) => page !== "hcmLeave";
  const properties = { ...base, canView, translate: (key: Parameters<typeof translate>[1]) => translate("en", key) };
  const view = render(<Sidebar {...properties} mobileOpen />);
  const search = screen.getByRole("searchbox", { name: "Find a workspace" });
  fireEvent.change(search, { target: { value: "no matching workspace" } });
  view.rerender(<Sidebar {...properties} collapsed mobileOpen={false} />);
  expect(search).toHaveValue("");
  expect(screen.queryByRole("button", { name: translate("en", "hcmLeave"), hidden: true })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Finance & reporting" })).toHaveAttribute("aria-current", "page");
});

it("reopens the mobile drawer without retaining the previous destination search", () => {
  const onMobileClose = vi.fn();
  const props = { ...base, onMobileClose, translate: (key: Parameters<typeof translate>[1]) => translate("en", key) };
  const view = render(<Sidebar {...props} mobileOpen />);
  fireEvent.change(screen.getByRole("searchbox", { name: "Find a workspace" }), { target: { value: "Inventory controls" } });
  fireEvent.click(screen.getByRole("button", { name: "Inventory controls" }));
  expect(onMobileClose).toHaveBeenCalledTimes(1);
  view.rerender(<Sidebar {...props} activePage="inventory" mobileOpen={false} />);
  view.rerender(<Sidebar {...props} activePage="inventory" mobileOpen />);
  expect(screen.getByRole("searchbox", { name: "Find a workspace" })).toHaveValue("");
  expect(view.container.querySelectorAll(".nav-group")).toHaveLength(8);
});

it("restores the current section after opening an external search result", () => {
  const view = render(<Sidebar {...base} translate={key => translate("en", key)} />);
  const search = screen.getByRole("searchbox", { name: "Find a workspace" });
  fireEvent.change(search, { target: { value: translate("en", "reports") } });
  const result = screen.getByRole("link", { name: translate("en", "reports") });
  expect(result).toHaveAttribute("target", "_blank");
  fireEvent.click(result);
  expect(search).toHaveValue("");
  expect(view.container.querySelector(".nav-item--active")?.closest("details")).toHaveAttribute("open");
});
