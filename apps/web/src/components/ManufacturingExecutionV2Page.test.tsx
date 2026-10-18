import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { webcrypto } from "node:crypto";
import { afterEach, expect, it, vi } from "vitest";
import { loadBudgetIdentity } from "../budget-control-data";
import { manufacturingV2Permissions } from "../manufacturing-execution-v2-data";
import { actualManufacturingV2Page, definitionV2 } from "../manufacturing-execution-v2-test-fixtures";
import { ManufacturingExecutionV2Page } from "./ManufacturingExecutionV2Page";
const session = { tenantId: "synthetic", csrfToken: "csrf", expiresAt: "2099-01-01T00:00:00Z" };
vi.mock("../browserSession", () => ({ useBrowserSession: () => ({ session, revision: 1, username: "checker", isCurrent: () => true, recover: () => false }) }));
const identity = { id: "checker", human: true, stepUp: true, workspaces: ["work"], organizations: ["org"], entities: ["entity"], permissions: [...new Set(Object.values(manufacturingV2Permissions).flat())] };
vi.mock("../budget-control-data", () => ({ loadBudgetIdentity: vi.fn(async () => identity) }));
afterEach(() => vi.unstubAllGlobals());
async function enter(locale: "en" | "ar" = "en") {
  vi.stubGlobal("crypto", webcrypto); render(<ManufacturingExecutionV2Page locale={locale} />);
  await waitFor(() => expect(screen.getByLabelText(locale === "en" ? "Workspace ID" : "معرّف مساحة العمل")).toHaveValue("work"));
  fireEvent.click(screen.getByRole("button", { name: locale === "en" ? "Apply scope" : "تطبيق النطاق" }));
  return screen.getByRole("combobox", { name: locale === "en" ? "Retained engineering or production source" : "المصدر الهندسي أو الإنتاجي المحفوظ" });
}
it("disables scope bootstrap until exact deferred identity is initialized", async () => {
  let resolve!: (value: typeof identity) => void;
  vi.mocked(loadBudgetIdentity).mockImplementationOnce(() => new Promise(accept => { resolve = accept; }));
  const fetch = vi.fn(async () => new Response(JSON.stringify({ orders: [], definitions: [] }))); vi.stubGlobal("fetch", fetch);
  vi.stubGlobal("crypto", webcrypto); render(<ManufacturingExecutionV2Page locale="en" />);
  const labels = ["Workspace ID", "Organization ID", "Legal entity ID"];
  for (const label of labels) expect(screen.getByLabelText(label)).toBeDisabled();
  expect(screen.getByRole("button", { name: "Apply scope" })).toBeDisabled(); expect(fetch).not.toHaveBeenCalled();
  await act(async () => resolve({ ...identity, workspaces: ["first", "work"], organizations: ["first", "org"], entities: ["first", "entity"] }));
  act(() => { labels.forEach((label, index) => fireEvent.change(screen.getByLabelText(label), { target: { value: ["work", "org", "entity"][index] } })); });
  fireEvent.click(screen.getByRole("button", { name: "Apply scope" }));
  await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
  expect(fetch).toHaveBeenCalledWith("/api/v1/manufacturing-execution-v2/orders", expect.objectContaining({ headers: expect.objectContaining({ "X-ReconForge-Workspace": "work", "X-ReconForge-Organization": "org", "X-ReconForge-Legal-Entity": "entity" }) }));
});
it.each(["en", "ar"] as const)("shows actual native quality/WIP state and bounded forms in %s", async locale => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(actualManufacturingV2Page(true)))));
  const select = await enter(locale), id = actualManufacturingV2Page(true).orders[0].id;
  await waitFor(() => expect(select.querySelectorAll("option").length).toBeGreaterThan(3)); fireEvent.change(select, { target: { value: id } });
  expect(await screen.findByText(/Quality hold 4 \/ 1520/)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: locale === "en" ? "Prepare production quality hold" : "إعداد إنتاج محجوز للجودة" })).not.toBeInTheDocument();
});
it("retries an exact lost approval ACK and preserves terminal evidence after GET failure", async () => {
  const source = await definitionV2(), approved = await definitionV2(true); const requests: string[] = []; let committed = false;
  vi.stubGlobal("fetch", vi.fn(async (_url: unknown, init?: RequestInit) => {
    if (init?.method === "POST") { requests.push(String(init.body)); if (requests.length === 1) throw new TypeError("lost committed reply"); committed = true; return new Response(JSON.stringify({ definition: approved })); }
    return committed ? new Response("Unavailable", { status: 503 }) : new Response(JSON.stringify({ definitions: [source], orders: [] }));
  }));
  const select = await enter(); await waitFor(() => expect(select.querySelectorAll("option")).toHaveLength(2)); fireEvent.change(select, { target: { value: source.id } });
  const form = screen.getByRole("form", { name: "Approve engineering revision" }); fireEvent.change(within(form).getByLabelText("Reason"), { target: { value: "Independent approval" } });
  fireEvent.click(within(form).getByRole("button", { name: "Approve engineering revision" }));
  fireEvent.click(await screen.findByRole("button", { name: "Retry the same retained command" }));
  await waitFor(() => expect(requests).toHaveLength(2)); expect(requests[0]).toBe(requests[1]);
  await screen.findByText("The command was acknowledged. Refresh native evidence before the next operation.");
  expect(screen.queryByRole("button", { name: "Approve engineering revision" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Retry the same retained command" })).not.toBeInTheDocument();
});
it("holds mutation admission while a real refresh is pending", async () => {
  const source = await definitionV2(); let resolve!: (value: Response) => void, reads = 0;
  const fetch = vi.fn((_url: unknown, init?: RequestInit) => { if (init?.method === "POST") throw new Error("No mutation may overlap this read"); if (++reads === 1) return Promise.resolve(new Response(JSON.stringify({ orders: [], definitions: [source] }))); return new Promise<Response>(accept => { resolve = accept; }); });
  vi.stubGlobal("fetch", fetch); const select = await enter(); await waitFor(() => expect(select.querySelectorAll("option")).toHaveLength(2)); fireEvent.change(select, { target: { value: source.id } });
  const form = screen.getByRole("form", { name: "Approve engineering revision" }); fireEvent.change(within(form).getByLabelText("Reason"), { target: { value: "Current exact authority" } });
  fireEvent.click(screen.getByRole("button", { name: "Refresh original manufacturing evidence" }));
  expect(within(form).getByRole("button", { name: "Approve engineering revision" })).toBeDisabled(); expect(select).toBeDisabled();
  await act(async () => resolve(new Response(JSON.stringify({ orders: [], definitions: [source] }))));
  await waitFor(() => expect(within(form).getByRole("button", { name: "Approve engineering revision" })).toBeEnabled());
});
