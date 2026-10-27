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

it.each(["en", "ar"] as const)("does not turn missing parent quality evidence into zero totals in %s", async locale => {
  const page = actualManufacturingV2Page(true);
  delete page.orders[0].material; delete page.orders[0].wip_minor;
  delete page.orders[0].held_quantity_scaled; delete page.orders[0].held_cost_minor;
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(page))));
  const select = await enter(locale);
  await waitFor(() => expect(select.querySelectorAll("option").length).toBeGreaterThan(3));
  fireEvent.change(select, { target: { value: page.orders[0].id } });
  expect(screen.queryByText(/WIP 0 · Quality hold 0 \/ 0/)).not.toBeInTheDocument();
  expect(screen.getByText(locale === "en" ? "Current parent inventory and WIP totals are unverified. Refresh original manufacturing evidence before continuing." : "إجماليات مخزون الأمر الأصلي وتحت التشغيل غير موثقة حالياً. حدّث أدلة التصنيع الأصلية قبل المتابعة.")).toBeInTheDocument();
  fireEvent.change(select, { target: { value: page.orders[0].productions[0].id } });
  expect(screen.getByRole("button", { name: locale === "en" ? "Prepare complete held-tranche inspection" : "إعداد فحص الدفعة المحجوزة بالكامل" })).toBeDisabled();
});

it.each(["en", "ar"] as const)("preserves actual verified zero parent totals in %s", async locale => {
  const page = actualManufacturingV2Page();
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(page))));
  const select = await enter(locale);
  await waitFor(() => expect(select.querySelectorAll("option").length).toBeGreaterThan(3));
  fireEvent.change(select, { target: { value: page.orders[0].id } });
  expect(screen.getByText(/WIP 0 · Quality hold 0 \/ 0 · Total 3800 USD/)).toBeInTheDocument();
});

it.each(["en", "ar"] as const)("stops presenting old quality totals as current after a failed refresh in %s", async locale => {
  const page = actualManufacturingV2Page(true);
  vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(new Response(JSON.stringify(page))).mockResolvedValueOnce(new Response("Unavailable", { status: 503 })).mockResolvedValueOnce(new Response(JSON.stringify(page))));
  const select = await enter(locale);
  await waitFor(() => expect(select.querySelectorAll("option").length).toBeGreaterThan(3));
  fireEvent.change(select, { target: { value: page.orders[0].id } });
  expect(await screen.findByText(/Quality hold 4 \/ 1520/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: locale === "en" ? "Refresh original manufacturing evidence" : "تحديث أدلة التصنيع الأصلية" }));
  await screen.findByRole("alert");
  expect(screen.queryByText(/Quality hold 4 \/ 1520/)).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: locale === "en" ? "Refresh original manufacturing evidence" : "تحديث أدلة التصنيع الأصلية" }));
  expect(await screen.findByText(/Quality hold 4 \/ 1520/)).toBeInTheDocument();
});

it("does not carry a different order's quality totals into an engineering source selection", async () => {
  const page = actualManufacturingV2Page(true);
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(page))));
  const select = await enter();
  await waitFor(() => expect(select.querySelectorAll("option").length).toBeGreaterThan(3));
  fireEvent.change(select, { target: { value: page.orders[0].id } });
  expect(await screen.findByText(/Quality hold 4 \/ 1520/)).toBeInTheDocument();
  fireEvent.change(select, { target: { value: page.definitions[0].id } });
  expect(screen.queryByText(/Quality hold/)).not.toBeInTheDocument();
});

it.each(["en", "ar"] as const)("retains a posted inspection ACK without presenting an old parent hold after read failure in %s", async locale => {
  const page = actualManufacturingV2Page(true), posted = actualManufacturingV2Page().orders[0].inspections[0];
  page.orders[0].inspections = [{ ...posted, phase: 1, receipt_effect: null, loss_effect_id: null }];
  vi.mocked(loadBudgetIdentity).mockResolvedValueOnce({ ...identity, id: "poster" });
  let acknowledged = false;
  vi.stubGlobal("fetch", vi.fn(async (_url: unknown, init?: RequestInit) => {
    if (init?.method === "POST") { acknowledged = true; return new Response(JSON.stringify({ inspection: posted })); }
    return acknowledged ? new Response("Unavailable", { status: 503 }) : new Response(JSON.stringify(page));
  }));
  const select = await enter(locale);
  await waitFor(() => expect(select.querySelectorAll("option").length).toBeGreaterThan(3));
  fireEvent.change(select, { target: { value: posted.id } });
  const form = screen.getByRole("form", { name: locale === "en" ? "Post complete original effects" : "ترحيل الآثار الأصلية بالكامل" });
  fireEvent.change(within(form).getByLabelText(locale === "en" ? "Reason" : "السبب"), { target: { value: "Independent native inspection posting" } });
  fireEvent.click(within(form).getByRole("button", { name: locale === "en" ? "Post complete original effects" : "ترحيل الآثار الأصلية بالكامل" }));
  await screen.findByText(locale === "en" ? "The command was acknowledged. Refresh native evidence before the next operation." : "وصل إقرار الأمر. حدّث الأدلة الأصلية قبل العملية التالية.");
  expect(screen.queryByText(/Quality hold 4 \/ 1520/)).not.toBeInTheDocument();
  expect(screen.getByText(/"receipt_effect": \{/)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: locale === "en" ? "Retry the same retained command" : "إعادة الأمر المحفوظ نفسه" })).not.toBeInTheDocument();
});

it("does not present old parent totals after a different inspection is returned for the command", async () => {
  const page = actualManufacturingV2Page(true), posted = actualManufacturingV2Page().orders[0].inspections[0];
  const wrong = actualManufacturingV2Page().orders[0].inspections[1];
  page.orders[0].inspections = [{ ...posted, phase: 1, receipt_effect: null, loss_effect_id: null }];
  vi.mocked(loadBudgetIdentity).mockResolvedValueOnce({ ...identity, id: "poster" });
  vi.stubGlobal("fetch", vi.fn(async (_url: unknown, init?: RequestInit) => new Response(JSON.stringify(init?.method === "POST" ? { inspection: wrong } : page))));
  const select = await enter(); await waitFor(() => expect(select.querySelectorAll("option").length).toBeGreaterThan(3));
  fireEvent.change(select, { target: { value: posted.id } });
  const form = screen.getByRole("form", { name: "Post complete original effects" });
  fireEvent.change(within(form).getByLabelText("Reason"), { target: { value: "Independent inspection" } });
  fireEvent.click(within(form).getByRole("button", { name: "Post complete original effects" }));
  await screen.findByRole("button", { name: "Retry the same retained command" });
  expect(screen.queryByText(/Quality hold 4 \/ 1520/)).not.toBeInTheDocument();
  expect(screen.queryByText(new RegExp(wrong.id))).not.toBeInTheDocument();
});
