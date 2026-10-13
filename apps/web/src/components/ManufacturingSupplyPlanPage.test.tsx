import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { webcrypto } from "node:crypto";
import { afterEach, expect, it, vi } from "vitest";
import { loadBudgetIdentity } from "../budget-control-data";
import { supplyOperationPermissions } from "../manufacturing-supply-data";
import { supplyFixture } from "../manufacturing-supply-test-fixtures";
import { ManufacturingSupplyPlanPage } from "./ManufacturingSupplyPlanPage";
const session = { tenantId: "synthetic", csrfToken: "csrf", expiresAt: "2099-01-01T00:00:00Z" };
vi.mock("../browserSession", () => ({ useBrowserSession: () => ({ session, revision: 1, username: "checker", isCurrent: () => true, recover: () => false }) }));
const identity = { id: "checker", human: true, stepUp: true, workspaces: ["work"], organizations: ["org"], entities: ["entity"], permissions: [...new Set(Object.values(supplyOperationPermissions).flat())] };
vi.mock("../budget-control-data", () => ({ loadBudgetIdentity: vi.fn(async () => identity), loadBudgetDetail: vi.fn(async () => ({ row_version: 3 })) }));
afterEach(() => vi.unstubAllGlobals());
async function enter(locale: "en" | "ar" = "en") {
  vi.stubGlobal("crypto", webcrypto); render(<ManufacturingSupplyPlanPage locale={locale} />);
  await waitFor(() => expect(screen.getByLabelText(locale === "en" ? "Workspace ID" : "معرّف مساحة العمل")).toHaveValue("work"));
  fireEvent.click(screen.getByRole("button", { name: locale === "en" ? "Apply scope" : "تطبيق النطاق" }));
  return screen.getByRole("combobox", { name: locale === "en" ? "Retained supply plan" : "خطة الإمداد المحفوظة" });
}
it.each(["en", "ar"] as const)("renders real gross/onhand/shortage quantities and UOM in %s", async locale => {
  vi.stubGlobal("crypto", webcrypto); const source = await supplyFixture(true); vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ records: [source] }))));
  const select = await enter(locale); await waitFor(() => expect(select.querySelectorAll("option")).toHaveLength(2)); await act(async () => fireEvent.change(select, { target: { value: source.id } }));
  const table = screen.getByRole("table"); expect(within(table).getByText("MATERIAL / KG")).toBeInTheDocument(); expect(within(table).getByText("3.000")).toBeInTheDocument(); expect(within(table).getByText("0.500")).toBeInTheDocument(); expect(within(table).getByText("2.500")).toBeInTheDocument();
  expect(screen.getByRole("main")).toHaveAttribute("dir", locale === "ar" ? "rtl" : "ltr");
});
it("prevents scope bootstrap until persisted identity is known", async () => {
  let resolve!: (value: typeof identity) => void; vi.mocked(loadBudgetIdentity).mockImplementationOnce(() => new Promise(done => { resolve = done; }));
  const fetch = vi.fn(); vi.stubGlobal("fetch", fetch); vi.stubGlobal("crypto", webcrypto); render(<ManufacturingSupplyPlanPage locale="en" />);
  expect(screen.getByRole("button", { name: "Apply scope" })).toBeDisabled(); expect(screen.getByLabelText("Workspace ID")).toBeDisabled(); expect(fetch).not.toHaveBeenCalled();
  await act(async () => resolve(identity)); await waitFor(() => expect(screen.getByRole("button", { name: "Apply scope" })).toBeEnabled());
});
it("retries the exact source approval ACK and retains evidence after refresh failure", async () => {
  vi.stubGlobal("crypto", webcrypto); const draft = await supplyFixture(), approved = await supplyFixture(true), calls: string[] = []; let committed = false;
  vi.stubGlobal("fetch", vi.fn(async (_url: unknown, init?: RequestInit) => { if (init?.method === "POST") { calls.push(String(init.body)); if (calls.length === 1) throw new TypeError("lost reply"); committed = true; return new Response(JSON.stringify({ source: approved })); } return committed ? new Response("Unavailable", { status: 503 }) : new Response(JSON.stringify({ records: [draft] })); }));
  const select = await enter(); await waitFor(() => expect(select.querySelectorAll("option")).toHaveLength(2)); fireEvent.change(select, { target: { value: draft.id } });
  const form = screen.getByRole("form", { name: "Approve and reserve original coverage" }); fireEvent.change(within(form).getByLabelText("Reason"), { target: { value: "Independent original demand" } }); fireEvent.click(within(form).getByRole("button", { name: "Approve and reserve original coverage" }));
  fireEvent.click(await screen.findByRole("button", { name: "Retry the same retained command" })); await waitFor(() => expect(calls).toHaveLength(2)); expect(calls[0]).toBe(calls[1]);
  await screen.findByText("Command acknowledged. Refresh original evidence before continuing."); expect(screen.queryByRole("button", { name: "Approve and reserve original coverage" })).not.toBeInTheDocument(); expect(within(screen.getByRole("table")).getByText("2.500")).toBeInTheDocument();
});
