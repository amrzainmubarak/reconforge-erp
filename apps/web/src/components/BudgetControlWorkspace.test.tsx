import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { BrowserSessionProvider, useBrowserSession } from "../browserSession";
import { budgetDetail, budgetEvidence, budgetIdentity, budgetRecord, budgetResponse, budgetSession } from "../budget-control-test-fixtures";
import type { Locale } from "../types";
import { BudgetControlWorkspace } from "./BudgetControlWorkspace";

function Controls() { const auth = useBrowserSession(); return <><button onClick={() => auth.begin(budgetSession, "maker", auth.revision)}>Begin fixture</button><button onClick={() => auth.clear(auth.revision)}>Clear fixture</button></>; }
function setup(fetcher: typeof fetch, locale: Locale = "en") { vi.stubGlobal("fetch", fetcher); render(<BrowserSessionProvider><Controls /><BudgetControlWorkspace locale={locale} /></BrowserSessionProvider>); }
async function load() { fireEvent.click(screen.getByText("Begin fixture")); await waitFor(() => expect(screen.getByLabelText("Workspace ID")).toHaveValue("work-a")); fireEvent.click(screen.getByRole("button", { name: "Load budgets" })); await screen.findByRole("button", { name: "Open budget OPS-A" }); }
afterEach(() => vi.unstubAllGlobals());

test("real current envelope opens with exact retained balances and complete evidence", async () => {
  const fetcher = vi.fn(async (path: RequestInfo | URL) => String(path).endsWith("/auth/me") ? budgetResponse(budgetIdentity) : String(path).includes("/BUD-A?") ? budgetResponse(budgetDetail) : budgetResponse({ envelopes: [budgetRecord], pagination: { limit: 25, offset: 0, has_more: false } }));
  setup(fetcher); await load(); fireEvent.click(screen.getByRole("button", { name: "Open budget OPS-A" }));
  await screen.findByRole("heading", { name: "Budget details · OPS-A" });
  expect(screen.getAllByText("100.00 EGP")).toHaveLength(2);
  expect(screen.getByRole("button", { name: "Record commitment" })).toBeDisabled();
});
test("lost reserve response locks edits and retries one exact payload before reloading current balances", async () => {
  let posted = false; const writes: string[] = [];
  const fetcher = vi.fn(async (path: RequestInfo | URL, options?: RequestInit) => {
    if (String(path).endsWith("/auth/me")) return budgetResponse(budgetIdentity);
    if (options?.method === "POST") { writes.push(String(options.body)); if (!posted) { posted = true; throw new TypeError("lost receipt after commit"); } return budgetResponse({ ...budgetRecord, row_version: 4, reserved_minor: "1376", available_minor: "8624", commitment_id: "COM-A", remaining_minor: "1376", evidence: { ...budgetEvidence, event_id: "EV-A" } }); }
    if (String(path).includes("/BUD-A?")) return budgetResponse({ ...budgetDetail, ...(posted ? { row_version: 4, reserved_minor: "1376", available_minor: "8624" } : {}) });
    return budgetResponse({ envelopes: [budgetRecord], pagination: { limit: 25, offset: 0, has_more: false } });
  });
  setup(fetcher); await load(); fireEvent.click(screen.getByRole("button", { name: "Open budget OPS-A" })); await screen.findByRole("heading", { name: "Budget details · OPS-A" });
  fireEvent.change(screen.getByLabelText("Recorded reason"), { target: { value: "Synthetic purchase" } }); fireEvent.change(screen.getByLabelText("Amount in currency units"), { target: { value: "١٣٫٧٦" } }); fireEvent.change(screen.getByLabelText("Operation date"), { target: { value: "2026-10-08" } }); fireEvent.change(screen.getByLabelText("Source reference"), { target: { value: "PO-A" } });
  const execute = screen.getByRole("button", { name: "Record commitment" }); fireEvent.click(execute); fireEvent.click(execute);
  await screen.findByRole("button", { name: "Retry exact command" }); expect(writes).toHaveLength(1);
  expect(screen.getByLabelText("Workspace ID")).toBeDisabled(); expect(screen.getByLabelText("Amount in currency units")).toBeDisabled(); expect(screen.getByRole("button", { name: "Reload current balances" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Retry exact command" })); await screen.findByText("AUD-A");
  await waitFor(() => expect(screen.queryByRole("button", { name: "Retry exact command" })).not.toBeInTheDocument());
  expect(writes[0]).toBe(writes[1]); expect(JSON.parse(writes[0])).toMatchObject({ expected_version: 3, operation: "Reserve", amount_minor: "1376" });
  await screen.findByText("86.24 EGP");
});
test("maker cannot activate independent approval", async () => {
  const submitted = { ...budgetRecord, status: "Submitted", approved_by: null, row_version: 2 };
  setup(vi.fn(async (path: RequestInfo | URL) => String(path).endsWith("/auth/me") ? budgetResponse(budgetIdentity) : String(path).includes("/BUD-A?") ? budgetResponse({ ...submitted, events: [], events_has_more: false }) : budgetResponse({ envelopes: [submitted], pagination: { limit: 25, offset: 0, has_more: false } })));
  await load(); fireEvent.click(screen.getByRole("button", { name: "Open budget OPS-A" })); await screen.findByRole("heading", { name: "Budget details · OPS-A" });
  fireEvent.change(screen.getByLabelText("Recorded reason"), { target: { value: "Self review" } }); expect(screen.getByRole("button", { name: "Approve budget" })).toBeDisabled();
});
test("read-only identity cannot create drafts or commitment commands", async () => {
  setup(vi.fn(async (path: RequestInfo | URL) => String(path).endsWith("/auth/me") ? budgetResponse({ ...budgetIdentity, permissions: ["budget_control.read"] }) : String(path).includes("/BUD-A?") ? budgetResponse(budgetDetail) : budgetResponse({ envelopes: [budgetRecord], pagination: { limit: 25, offset: 0, has_more: false } })));
  await load(); fireEvent.click(screen.getByRole("button", { name: "Open budget OPS-A" })); await screen.findByRole("heading", { name: "Budget details · OPS-A" });
  expect(screen.queryByRole("button", { name: "Create draft" })).not.toBeInTheDocument(); expect(screen.queryByRole("button", { name: "Record commitment" })).not.toBeInTheDocument();
});
test("session change discards sensitive records and late response", async () => {
  let finish!: (response: Response) => void; const pending = new Promise<Response>((resolve) => { finish = resolve; });
  setup(vi.fn((path: RequestInfo | URL) => String(path).endsWith("/auth/me") ? Promise.resolve(budgetResponse(budgetIdentity)) : pending));
  fireEvent.click(screen.getByText("Begin fixture")); await waitFor(() => expect(screen.getByLabelText("Workspace ID")).toHaveValue("work-a")); fireEvent.click(screen.getByRole("button", { name: "Load budgets" }));
  fireEvent.click(screen.getByText("Clear fixture")); await act(async () => finish(budgetResponse({ envelopes: [budgetRecord], pagination: { limit: 25, offset: 0, has_more: false } })));
  expect(screen.queryByText("OPS-A", { exact: false })).not.toBeInTheDocument(); expect(screen.getByLabelText("Password")).toBeVisible();
});
test("Arabic form uses RTL and authorization denial clears financial state", async () => {
  setup(vi.fn(async (path: RequestInfo | URL) => String(path).endsWith("/auth/me") ? budgetResponse(budgetIdentity) : budgetResponse({ error: { code: "budget_scope_denied" } }, 403)), "ar");
  fireEvent.click(screen.getByText("Begin fixture")); await waitFor(() => expect(screen.getByLabelText("معرف مساحة العمل")).toHaveValue("work-a"));
  expect(screen.getByRole("main")).toHaveAttribute("dir", "rtl"); fireEvent.click(screen.getByRole("button", { name: "تحميل الميزانيات" }));
  await screen.findByRole("alert"); expect(screen.getByRole("alert")).toHaveTextContent("غير مصرح"); expect(screen.queryByRole("button", { name: /OPS-A/ })).not.toBeInTheDocument();
});
