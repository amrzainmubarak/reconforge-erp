import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import App from "./App";

const overviewLoad = vi.hoisted(() => vi.fn(async () => ({ notices: [] })));
vi.mock("./data", async importOriginal => ({ ...await importOriginal<typeof import("./data")>(), loadStudioOverview: overviewLoad }));
vi.mock("./components/CustomerReturnsPage", () => { throw new Error("PRIVATE_FINANCIAL_DATA_IN_REJECTED_MODULE"); });
vi.mock("./components/Dashboard", () => ({ Dashboard: () => <main id="main-content"><h1>Recovered read-only dashboard</h1></main> }));

beforeEach(() => {
  window.localStorage.clear();
  window.history.replaceState({}, "", "/customer-returns");
  overviewLoad.mockClear();
});
afterEach(() => { vi.unstubAllGlobals(); window.history.replaceState({}, "", "/"); });

it("the real App keeps shell navigation outside failed lazy workspaces and recovers only through explicit navigation", async () => {
  const caught: unknown[] = [], network = vi.fn();
  vi.stubGlobal("fetch", network);
  render(<App />, { onCaughtError: error => caught.push(error) });
  await screen.findByRole("heading", { level: 1, name: "Workspace unavailable" });
  expect(caught.length).toBeGreaterThan(0);
  const navigation = screen.getByRole("navigation", { name: "Primary navigation" });
  expect(within(navigation).getByRole("button", { name: "Customer returns" })).toBeInTheDocument();
  expect(document.querySelector(".topbar")).toBeInTheDocument();
  expect(document.querySelector(".mobile-dock")).toBeInTheDocument();
  expect(screen.getByRole("alert")).toHaveFocus();
  expect(document.body.textContent).not.toContain("PRIVATE_FINANCIAL_DATA_IN_REJECTED_MODULE");
  expect(overviewLoad).not.toHaveBeenCalled(); expect(network).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Open dashboard" }));
  await screen.findByRole("heading", { level: 1, name: "Recovered read-only dashboard" });
  expect(window.location.pathname).toBe("/");
  expect(overviewLoad).toHaveBeenCalledTimes(1);
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  fireEvent.click(within(navigation).getByRole("button", { name: "Customer returns" }));
  await waitFor(() => expect(screen.getByRole("alert")).toHaveFocus());
  expect(screen.getByRole("heading", { level: 1, name: "Workspace unavailable" })).toBeInTheDocument();
  expect(window.location.pathname).toBe("/customer-returns");
  expect(network).not.toHaveBeenCalled();
});
