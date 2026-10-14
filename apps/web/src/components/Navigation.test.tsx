import { fireEvent, render, screen, within } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import { translate } from "../i18n";
import { navigationGroups, Sidebar } from "./Navigation";

it.each([
  ["en", false],
  ["en", true],
  ["ar", false],
  ["ar", true],
] as const)("preserves every %s navigation name when the icon rail hides text (collapsed=%s)", (locale, collapsed) => {
  const onNavigate = vi.fn(), onMobileClose = vi.fn(), onCollapse = vi.fn();
  const text = (key: Parameters<typeof translate>[1]) => translate(locale, key);
  const view = render(<Sidebar translate={text} collapsed={collapsed} mobileOpen={false}
    onCollapse={onCollapse} onMobileClose={onMobileClose} activePage="customerReturns" onNavigate={onNavigate} />);
  const navigation = screen.getByRole("navigation", { name: text("primaryNavigation") });
  const items = navigationGroups.flatMap(group => group.items);
  const names = items.map(item => text(item.label));
  expect(new Set(names).size).toBe(items.length);
  expect(navigation.querySelectorAll(".nav-item")).toHaveLength(items.length);
  for (const control of navigation.querySelectorAll(".nav-item")) expect(control).toHaveAccessibleName();

  // Both the <=1060px rail and manual collapse remove text from the accessibility
  // tree. JSDOM does not apply viewport media queries, so reproduce that condition
  // on the real children rather than claiming a responsive browser check here.
  for (const label of navigation.querySelectorAll<HTMLElement>(".nav-item-label, .nav-status")) label.style.display = "none";
  let navigationCalls = 0, closeCalls = 0;
  for (const item of items) {
    const control = within(navigation).getByRole(item.href ? "link" : "button", { name: text(item.label) });
    expect(control).toHaveAccessibleName(text(item.label));
    expect(control.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
    if (item.page) {
      expect(control).toBeEnabled();
      expect(control.getAttribute("aria-current")).toBe(item.page === "customerReturns" ? "page" : null);
      fireEvent.click(control);
      navigationCalls += 1; closeCalls += 1;
      expect(onNavigate).toHaveBeenLastCalledWith(item.page);
      expect(onNavigate).toHaveBeenCalledTimes(navigationCalls);
      expect(onMobileClose).toHaveBeenCalledTimes(closeCalls);
    } else if (item.href) {
      expect(control).toHaveAttribute("href", item.href);
      expect(control).toHaveAttribute("target", "_blank");
      expect(control).toHaveAttribute("rel", "noreferrer");
      control.addEventListener("click", event => event.preventDefault(), { once: true });
      fireEvent.click(control);
      closeCalls += 1;
      expect(onNavigate).toHaveBeenCalledTimes(navigationCalls);
      expect(onMobileClose).toHaveBeenCalledTimes(closeCalls);
    } else {
      expect(control).toBeDisabled();
      expect(control).toHaveAttribute("title", text("planned"));
      const previousCalls = onNavigate.mock.calls.length;
      fireEvent.click(control);
      expect(onNavigate).toHaveBeenCalledTimes(previousCalls);
      expect(onMobileClose).toHaveBeenCalledTimes(closeCalls);
    }
  }
  expect(onNavigate).toHaveBeenCalledTimes(items.filter(item => item.page).length);
  expect(onCollapse).not.toHaveBeenCalled();
  expect(view.container.querySelector(".sidebar")?.classList.contains("sidebar--collapsed")).toBe(collapsed);
});

it("refreshes localized icon-only navigation names without firing a route or command", () => {
  const onNavigate = vi.fn(), onMobileClose = vi.fn();
  const properties = { collapsed: true, mobileOpen: false, onCollapse: vi.fn(), onMobileClose,
    activePage: "customerReturns" as const, onNavigate };
  const view = render(<Sidebar {...properties} translate={key => translate("en", key)} />);
  expect(screen.getByRole("button", { name: "Customer returns" })).toHaveAttribute("aria-current", "page");
  view.rerender(<Sidebar {...properties} translate={key => translate("ar", key)} />);
  const navigation = screen.getByRole("navigation", { name: "التنقل الرئيسي" });
  for (const label of navigation.querySelectorAll<HTMLElement>(".nav-item-label, .nav-status")) label.style.display = "none";
  expect(within(navigation).getByRole("button", { name: "مرتجعات العملاء" })).toHaveAttribute("aria-current", "page");
  expect(within(navigation).queryByRole("button", { name: "Customer returns" })).not.toBeInTheDocument();
  expect(onNavigate).not.toHaveBeenCalled();
  expect(onMobileClose).not.toHaveBeenCalled();
});
