import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { loadBudgetIdentity } from "../budget-control-data";
import { manufacturingCompletionFixture, manufacturingFixture } from "../manufacturing-execution-test-fixtures";
import { ManufacturingExecutionPage } from "./ManufacturingExecutionPage";
const session = { tenantId: "synthetic", csrfToken: "csrf", expiresAt: "2099-01-01T00:00:00Z" };
vi.mock("../browserSession", () => ({ useBrowserSession: () => ({ session, revision: 1, username: "poster", isCurrent: () => true }) }));
const identity = { id: "poster", human: true, stepUp: true, workspaces: ["work"], organizations: ["org"], entities: ["entity"], permissions: ["manufacturing_execution.read", "manufacturing_execution.manage", "manufacturing_execution.approve", "manufacturing_execution.post", "inventory.read", "inventory.manage", "inventory.post", "inventory.valuation.manage", "inventory.valuation.approve", "finance_core.read", "finance_core.manage", "finance_core.validate", "finance_core.post"] };
vi.mock("../budget-control-data", () => ({ loadBudgetIdentity: vi.fn(async () => identity) }));
afterEach(() => vi.unstubAllGlobals());
it("blocks scope edits before deferred identity and preserves functional staged edits", async () => {
  let resolve!: (value: typeof identity) => void;
  vi.mocked(loadBudgetIdentity).mockImplementationOnce(() => new Promise<typeof identity>(accept => { resolve = accept; }));
  const fetch = vi.fn(async () => new Response(JSON.stringify({ boms: [], orders: [] }))); vi.stubGlobal("fetch", fetch);
  render(<ManufacturingExecutionPage locale="en" />);
  const fields = ["Workspace ID", "Organization ID", "Legal entity ID"].map(label => screen.getByLabelText(label));
  for (const field of fields) expect(field).toBeDisabled();
  expect(screen.getByRole("button", { name: "Apply scope" })).toBeDisabled(); expect(fetch).not.toHaveBeenCalled();
  await act(async () => resolve({ ...identity, workspaces: ["first-work", "work"], organizations: ["first-org", "org"], entities: ["first-entity", "entity"] }));
  act(() => { for (const [index, value] of ["work", "org", "entity"].entries()) fireEvent.change(fields[index], { target: { value } }); });
  for (const [index, value] of ["work", "org", "entity"].entries()) { expect(fields[index]).toBeEnabled(); expect(fields[index]).toHaveValue(value); }
  fireEvent.click(screen.getByRole("button", { name: "Apply scope" }));
  await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
  expect(fetch).toHaveBeenCalledWith("/api/v1/manufacturing-execution/orders", expect.objectContaining({ method: "GET", headers: expect.objectContaining({ "X-ReconForge-Workspace": "work", "X-ReconForge-Organization": "org", "X-ReconForge-Legal-Entity": "entity" }) }));
});
it("retains exact lost post command and terminal evidence after follow-up GET failure", async () => {
  const source = await manufacturingFixture(2), terminal = await manufacturingFixture(3), requests: string[] = []; let posted = false;
  vi.stubGlobal("fetch", vi.fn(async (_url: unknown, init?: RequestInit) => {
    if (init?.method === "POST") { requests.push(String(init.body)); if (requests.length === 1) throw new TypeError("lost committed response"); posted = true; return new Response(JSON.stringify({ order: terminal })); }
    return posted ? new Response("unavailable", { status: 503 }) : new Response(JSON.stringify({ boms: [], orders: [source] }));
  }));
  render(<ManufacturingExecutionPage locale="en" />);
  await waitFor(() => expect(screen.getByLabelText("Workspace ID")).toHaveValue("work"));
  fireEvent.click(screen.getByRole("button", { name: "Apply scope" }));
  const select = screen.getByRole("combobox", { name: "Retained production order" });
  await waitFor(() => expect(select.querySelectorAll("option")).toHaveLength(2));
  fireEvent.change(select, { target: { value: source.id } });
  fireEvent.change(within(screen.getByRole("form", { name: "Post complete native effects" })).getByLabelText("Reason"), { target: { value: "Third human actual posting" } });
  fireEvent.click(screen.getByRole("button", { name: "Post complete native effects" }));
  fireEvent.click(await screen.findByRole("button", { name: "Retry retained command" }));
  await waitFor(() => expect(requests).toHaveLength(2)); expect(requests[0]).toBe(requests[1]);
  await waitFor(() => expect(screen.getAllByText(/effect-issue/).length).toBeGreaterThan(0));
  expect(screen.queryByRole("button", { name: "Post complete native effects" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Cancel unposted source" })).not.toBeInTheDocument();
});
it("renders explicit manufacturing bounds with Arabic RTL", () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ boms: [], orders: [] }))));
  const view = render(<ManufacturingExecutionPage locale="ar" />);
  expect(view.container.querySelector("main")).toHaveAttribute("dir", "rtl");
  expect(screen.getByRole("heading", { name: "التنفيذ الصناعي بالتكلفة الفعلية" })).toBeInTheDocument();
});
it("retains final posted output ACK, zero WIP and terminal parent when follow-up native GET fails", async () => {
  const parent = await manufacturingFixture(3), reviewed = await manufacturingCompletionFixture(1), posted = await manufacturingCompletionFixture(2);
  let committed = false;
  vi.stubGlobal("fetch", vi.fn(async (_url: unknown, init?: RequestInit) => {
    if (init?.method === "POST") { committed = true; return new Response(JSON.stringify({ completion: posted })); }
    return committed ? new Response("unavailable", { status: 503 }) : new Response(JSON.stringify({ boms: [], orders: [{ ...parent, completions: [reviewed] }] }));
  }));
  render(<ManufacturingExecutionPage locale="en" />);
  await waitFor(() => expect(screen.getByLabelText("Workspace ID")).toHaveValue("work"));
  fireEvent.click(screen.getByRole("button", { name: "Apply scope" }));
  const select = screen.getByRole("combobox", { name: "Retained production order" });
  await waitFor(() => expect(select.querySelectorAll("option")).toHaveLength(2));
  fireEvent.change(select, { target: { value: parent.id } });
  fireEvent.change(screen.getByRole("combobox", { name: "Retained output disposition" }), { target: { value: reviewed.id } });
  const form = screen.getByRole("form", { name: "Post complete native effects" });
  fireEvent.change(within(form).getByLabelText("Reason"), { target: { value: "Final exact native production disposition" } });
  fireEvent.click(within(form).getByRole("button", { name: "Post complete native effects" }));
  await screen.findByRole("alert");
  expect(screen.getByText("0", { selector: "bdi" })).toBeInTheDocument();
  expect(screen.queryByRole("form", { name: "Prepare partial good output and abnormal scrap" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Post complete native effects" })).not.toBeInTheDocument();
  expect(screen.getAllByText(/effect-output/).length).toBeGreaterThan(0);
});
