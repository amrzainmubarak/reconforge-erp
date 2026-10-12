import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { commerceFixture } from "../stock-commerce-test-fixtures";
import { StockCommercePanel } from "./StockCommercePanel";

afterEach(() => vi.unstubAllGlobals());
const scope = { workspace_id: "work", organization_id: "org", legal_entity_id: "entity" };
const session = { tenantId: "tenant", csrfToken: "csrf", expiresAt: "2099-01-01T00:00:00Z" };
const identity = { id: "checker", human: true, stepUp: true, permissions: ["sales.read", "sales.manage", "sales.approve", "inventory.read", "inventory.manage", "receivables.read", "receivables.approve", "finance_core.read", "finance_core.post"], workspaces: ["work"], organizations: ["org"], entities: ["entity"] };
const response = (value: unknown) => new Response(JSON.stringify(value), { headers: { "Content-Type": "application/json" } });
it("disables reviewed revenue posting for its reviewer and exposes retained native evidence", async () => {
  const document = commerceFixture();
  vi.stubGlobal("fetch", vi.fn(async (path: RequestInfo | URL) => String(path).includes("catalog") ? response({ items: [], next_cursor: null }) : String(path).includes("?after=") ? response({ orders: [document], next_cursor: null }) : response(document)));
  render(<StockCommercePanel locale="en" session={session} scope={scope} identity={identity} options={null} disabled={false} onPendingChange={() => {}} />);
  fireEvent.click(await screen.findByRole("button", { name: "Open" }));
  await screen.findByRole("heading", { name: "COMMERCIAL-1 · Approved" });
  fireEvent.change(screen.getByLabelText("Delivery tranche"), { target: { value: "COMTR-1" } });
  fireEvent.change(screen.getByLabelText("Reason"), { target: { value: "Publish reviewed revenue" } });
  expect(screen.getByRole("button", { name: "Post invoice and revenue" })).toBeDisabled();
  expect(screen.getByText(/three distinct humans/)).toBeInTheDocument();
  expect(screen.getByText("GL-1")).toBeInTheDocument();
});
it("renders Arabic RTL commercial scope and exact partial settlement support", () => {
  vi.stubGlobal("fetch", vi.fn(async (path: RequestInfo | URL) => String(path).includes("catalog") ? response({ items: [], next_cursor: null }) : response({ orders: [], next_cursor: null })));
  render(<StockCommercePanel locale="ar" session={session} scope={scope} identity={identity} options={null} disabled={false} onPendingChange={() => {}} />);
  expect(screen.getByRole("region", { name: "أوامر المبيعات التجارية" })).toHaveAttribute("dir", "rtl");
  expect(screen.getByText(/دفعات تحصيل مستقلة المراجعة/)).toBeInTheDocument();
});
