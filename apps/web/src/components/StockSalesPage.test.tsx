import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { BrowserSessionProvider, useBrowserSession } from "../browserSession";
import { StockSalesPage } from "./StockSalesPage";

const scope = { workspace_id: "work", organization_id: "org", legal_entity_id: "entity" };
const identity = { id: "maker", principal_type: "user", step_up_active: true, permissions: ["sales.read", "sales.manage", "sales.approve", "inventory.read", "inventory.manage", "receivables.read", "finance_core.read", "finance_core.manage"], authorized_scopes: { workspaces: ["work"], organizations: ["org"], legal_entities: ["entity"] } };
const options = { customers: [{ customer_code: "CUSTOMER", name: "Synthetic customer", currency_code: "USD" }], periods: [], journals: [], accounts: [], items: [{ item_code: "ITEM", name: "Physical item", uom_code: "EA", decimal_places: 0 }], warehouses: [{ warehouse_code: "MAIN", name: "Main warehouse" }], locations: [{ warehouse_code: "MAIN", location_code: "STOCK", name: "Stock" }], policies: [] };
function document(reserved = false) {
  const events = ["Draft", "Submitted", "Approved", ...(reserved ? ["Reserved"] : [])].map((status, index) => ({ version: index + 1, actor_id: index === 2 ? "checker" : "maker", operation: ["create", "submit", "approve", "reserve"][index], reason: "Retained decision", status, audit_event_id: "AUD-" + index }));
  return { ...scope, id: "STSALE-1", number: "PRODUCT-1", status: reserved ? "Reserved" : "Approved", row_version: events.length, source_digest: "a".repeat(64), currency_code: "USD", total_minor: "22500", cogs_minor: null, quantity: "5", quantity_scaled: "5", quantity_precision: 0, unit_price_minor: "5000", net_unit_price_minor: "4500", discount_basis_points: 1000, description: "Physical products", customer_code: "CUSTOMER", customer_reference: "PO-1", item_code: "ITEM", warehouse_code: "MAIN", location_code: "STOCK", order_date: "2026-10-09", created_by: "maker", approved_by: "checker", issue_reviewer_id: null, issue_preparer_id: null, monetary_policy: { precision: 2 }, movement_id: null, valuation_id: null, cogs_entry_id: null, cogs_effect_id: null, invoice_id: null, invoice_plan_id: null, collection_plan_id: null, receipt_id: null, events };
}
function Begin() { const auth = useBrowserSession(); return <button onClick={() => auth.begin({ tenantId: "tenant", csrfToken: "csrf", expiresAt: "2099-01-01T00:00:00Z" }, "maker", auth.revision)}>Begin fixture</button>; }
const response = (value: unknown) => new Response(JSON.stringify(value), { status: 200, headers: { "Content-Type": "application/json" } });
afterEach(() => vi.unstubAllGlobals());

it("locks a lost reservation packet, retries unchanged and retains immediately typed next review reason", async () => {
  const writes: string[] = []; let committed = false;
  vi.stubGlobal("fetch", vi.fn(async (path: RequestInfo | URL, request?: RequestInit) => {
    if (String(path).endsWith("/auth/me")) return response(identity);
    if (request?.method === "POST") { writes.push(String(request.body)); if (!committed) { committed = true; throw new TypeError("Lost reservation acknowledgement"); } return response(document(true)); }
    if (String(path).endsWith("/options")) return response(options);
    if (String(path).endsWith("/orders")) return response({ orders: [document(committed)] });
    return response(document(committed));
  }));
  render(<BrowserSessionProvider><Begin /><StockSalesPage locale="en" /></BrowserSessionProvider>);
  fireEvent.click(screen.getByRole("button", { name: "Begin fixture" }));
  await waitFor(() => expect(screen.getByLabelText("Workspace")).toHaveValue("work"));
  fireEvent.click(screen.getByRole("button", { name: "Load selected scope" }));
  fireEvent.click(await screen.findByRole("button", { name: "Open PRODUCT-1" }));
  await screen.findByRole("heading", { name: "PRODUCT-1 · Approved" });
  fireEvent.change(screen.getByLabelText("Decision reason"), { target: { value: "Reserve exact customer goods" } });
  fireEvent.click(screen.getByRole("button", { name: "Reserve stock" }));
  await screen.findByRole("button", { name: "Retry original request" });
  expect(screen.getByLabelText("Workspace")).toBeDisabled();
  expect(screen.getByLabelText("Decision reason")).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Retry original request" }));
  await screen.findByRole("heading", { name: "PRODUCT-1 · Reserved" });
  fireEvent.change(screen.getByLabelText("Decision reason"), { target: { value: "Next exact FIFO decision" } });
  await waitFor(() => expect(screen.getByLabelText("Decision reason")).toHaveValue("Next exact FIFO decision"));
  expect(writes).toHaveLength(2); expect(writes[0]).toBe(writes[1]);
  expect(JSON.parse(writes[0])).toMatchObject({ expected_version: 3, reason: "Reserve exact customer goods" });
});

it("refuses COGS delivery for its reviewer even with all delivery permissions", async () => {
  const reserved = document(true);
  const reviewed = { ...reserved, status: "IssueReviewed", row_version: 6, issue_preparer_id: "maker", issue_reviewer_id: "checker", cogs_minor: "6000", events: [...reserved.events,
    { version: 5, actor_id: "maker", operation: "prepare-issue", reason: "Frozen FIFO cost", status: "IssuePrepared", audit_event_id: "AUD-4" },
    { version: 6, actor_id: "checker", operation: "review-issue", reason: "Independent FIFO review", status: "IssueReviewed", audit_event_id: "AUD-5" }] };
  const reviewer = { ...identity, id: "checker", permissions: [...identity.permissions, "inventory.post", "inventory.valuation.approve", "finance_core.post"] };
  const writes: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (path: RequestInfo | URL, request?: RequestInit) => {
    if (String(path).endsWith("/auth/me")) return response(reviewer);
    if (request?.method === "POST") { writes.push(String(request.body)); return response(reviewed); }
    if (String(path).endsWith("/options")) return response(options);
    if (String(path).endsWith("/orders")) return response({ orders: [reviewed] });
    return response(reviewed);
  }));
  render(<BrowserSessionProvider><Begin /><StockSalesPage locale="en" /></BrowserSessionProvider>);
  fireEvent.click(screen.getByRole("button", { name: "Begin fixture" }));
  await waitFor(() => expect(screen.getByLabelText("Workspace")).toHaveValue("work"));
  fireEvent.click(screen.getByRole("button", { name: "Load selected scope" }));
  fireEvent.click(await screen.findByRole("button", { name: "Open PRODUCT-1" }));
  await screen.findByRole("heading", { name: "PRODUCT-1 · FIFO reviewed" });
  fireEvent.change(screen.getByLabelText("Decision reason"), { target: { value: "Review completed by this human" } });
  expect(screen.getByRole("button", { name: "Deliver and post COGS" })).toBeDisabled();
  expect(screen.getByText(/requires a third human distinct/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Deliver and post COGS" }));
  expect(writes).toHaveLength(0);
});

it("exposes Arabic RTL and native profile boundaries before authentication", () => {
  render(<BrowserSessionProvider><StockSalesPage locale="ar" /></BrowserSessionProvider>);
  expect(screen.getByRole("main")).toHaveAttribute("dir", "rtl");
  expect(screen.getByLabelText("اسم المستخدم")).toBeRequired();
  expect(screen.getByLabelText("كلمة المرور")).toHaveAttribute("type", "password");
  expect(screen.getByText(/الضريبة صفر صراحةً/)).toBeInTheDocument();
});
