import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import { translate } from "../i18n";
import { CommandPalette } from "./Overlays";

it.each(["en", "ar"] as const)("starts ArrowUp at the last permitted command and wraps (%s)", locale => {
  const view = render(<CommandPalette translate={key => translate(locale, key)} onClose={vi.fn()} onNavigate={vi.fn()} canView={page => page !== "hcmLeave"} />);
  const search = screen.getByRole("textbox", { name: translate(locale, "search") });
  const rows = [...view.container.querySelectorAll<HTMLElement>(".command-row:not([aria-disabled])")];
  expect(rows.length).toBeGreaterThan(1);
  expect(screen.queryByRole("button", { name: new RegExp(translate(locale, "hcmLeave")) })).not.toBeInTheDocument();
  fireEvent.keyDown(search, { key: "ArrowUp" });
  expect(rows.at(-1)).toHaveFocus();
  fireEvent.keyDown(rows.at(-1)!, { key: "ArrowUp" });
  expect(rows.at(-2)).toHaveFocus();
  fireEvent.keyDown(rows.at(-2)!, { key: "ArrowDown" });
  expect(rows.at(-1)).toHaveFocus();
  fireEvent.keyDown(rows.at(-1)!, { key: "ArrowDown" });
  expect(rows[0]).toHaveFocus();
});

it("starts ArrowDown at the first result after filtering", () => {
  const view = render(<CommandPalette translate={key => translate("en", key)} onClose={vi.fn()} onNavigate={vi.fn()} />);
  const search = screen.getByRole("textbox", { name: translate("en", "search") });
  fireEvent.change(search, { target: { value: "inventory" } });
  const rows = [...view.container.querySelectorAll<HTMLElement>(".command-row:not([aria-disabled])")];
  expect(rows.length).toBeGreaterThan(1);
  fireEvent.keyDown(search, { key: "ArrowDown" });
  expect(rows[0]).toHaveFocus();
});

it("keeps focus in the search field when filtering leaves no commands", () => {
  const view = render(<CommandPalette translate={key => translate("en", key)} onClose={vi.fn()} onNavigate={vi.fn()} />);
  const search = screen.getByRole("textbox", { name: translate("en", "search") });
  fireEvent.change(search, { target: { value: "no-such-command" } });
  expect(screen.getByText(translate("en", "commandEmpty"))).toBeInTheDocument();
  expect(view.container.querySelectorAll(".command-row:not([aria-disabled])")).toHaveLength(0);
  fireEvent.keyDown(search, { key: "ArrowUp" });
  fireEvent.keyDown(search, { key: "ArrowDown" });
  expect(search).toHaveFocus();
});

it("does not expose or focus a destination denied by the access filter", () => {
  const navigate = vi.fn();
  const view = render(<CommandPalette translate={key => translate("en", key)} onClose={vi.fn()} onNavigate={navigate} canView={page => page !== "hcmLeave"} />);
  const search = screen.getByRole("textbox", { name: translate("en", "search") });
  fireEvent.change(search, { target: { value: translate("en", "hcmLeave") } });
  expect(screen.getByText(translate("en", "commandEmpty"))).toBeInTheDocument();
  expect(view.container.querySelectorAll(".command-row:not([aria-disabled])")).toHaveLength(0);
  fireEvent.keyDown(search, { key: "ArrowUp" });
  expect(search).toHaveFocus();
  expect(navigate).not.toHaveBeenCalled();
});
