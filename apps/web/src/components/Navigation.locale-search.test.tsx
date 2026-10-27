import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import { translate, type MessageKey } from "../i18n";
import { Sidebar } from "./Navigation";

const base = { collapsed: false, mobileOpen: false, onCollapse: vi.fn(), onMobileClose: vi.fn(), activePage: "enterpriseFinance" as const, onNavigate: vi.fn() };

it.each([["en", "ar"], ["ar", "en"]] as const)("keeps a permitted result discoverable across %s to %s language changes", (before, after) => {
  const view = render(<Sidebar {...base} translate={key => translate(before, key)} />);
  fireEvent.change(screen.getByRole("searchbox", { name: translate(before, "navFilter") }), { target: { value: translate(before, "enterpriseFinance") } });
  view.rerender(<Sidebar {...base} translate={key => translate(after, key)} />);
  expect(screen.getByRole("searchbox", { name: translate(after, "navFilter") })).toHaveValue(translate(before, "enterpriseFinance"));
  expect(screen.getByRole("button", { name: translate(after, "enterpriseFinance") })).toHaveAttribute("aria-current", "page");
});

it("does not expose denied destinations through the alternate language", () => {
  render(<Sidebar {...base} translate={key => translate("ar", key)} canView={page => page !== "enterpriseFinance"} />);
  fireEvent.change(screen.getByRole("searchbox", { name: translate("ar", "navFilter") }), { target: { value: translate("en", "enterpriseFinance") } });
  expect(screen.queryByRole("button", { name: translate("ar", "enterpriseFinance") })).not.toBeInTheDocument();
  expect(screen.getByRole("status")).toHaveTextContent(translate("ar", "navNoResults"));
});

it("finds a permitted destination by its section name in the other language", () => {
  render(<Sidebar {...base} translate={key => translate("ar", key)} canView={page => page === "hcmLeave"} />);
  fireEvent.change(screen.getByRole("searchbox", { name: translate("ar", "navFilter") }), { target: { value: translate("en", "navPeople") } });
  expect(screen.getByRole("button", { name: translate("ar", "hcmLeave") })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: translate("ar", "enterpriseFinance") })).not.toBeInTheDocument();
});

it("preserves custom translation search and the empty state", () => {
  const customized = (key: MessageKey) => key === "enterpriseFinance" ? "Custom ledger" : translate("en", key);
  render(<Sidebar {...base} translate={customized} />);
  const search = screen.getByRole("searchbox", { name: translate("en", "navFilter") });
  fireEvent.change(search, { target: { value: "Custom ledger" } });
  expect(screen.getByRole("button", { name: "Custom ledger" })).toBeInTheDocument();
  fireEvent.change(search, { target: { value: "unmatched-destination-9847" } });
  expect(screen.getByRole("status")).toHaveTextContent(translate("en", "navNoResults"));
});
