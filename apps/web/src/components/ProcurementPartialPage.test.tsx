import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { BrowserSessionProvider, useBrowserSession } from "../browserSession";
import { ProcurementPartialPage } from "./ProcurementPartialPage";

const scope = { workspace_id: "work", organization_id: "org", legal_entity_id: "entity", organization_code: "ORG", entity_code: "ENTITY", organization_name: "Organization", entity_name: "Entity", currency_code: "USD" };
const permissions = ["payables.read", "payables.manage", "payables.approve", "payables.settle", "inventory.read", "inventory.manage", "inventory.post", "inventory.valuation.manage", "inventory.valuation.approve", "finance_core.read", "finance_core.manage", "finance_core.validate", "finance_core.post"];
const options = { suppliers: [], items: [], locations: [], policies: [], periods: [], journals: [], accounts: [] };
type Phase = "receipt" | "accrual" | "payment";
function detail(phase: Phase) {
  const received = phase !== "receipt", accrued = phase === "payment";
  const receipt = { id: "part-receipt", order_id: "partial-order", number: "PPR-ORDER-1-1", sequence: 1, quantity_text: "4", total_minor: "4800", posting_date: "2026-10-03", period_id: "period", receipt_plan_id: "native-receipt-plan", goods_receipt_id: received ? "native-goods-receipt" : null, stage: received ? "Posted" : "Reviewed", created_version: 4, reviewed_version: 5, posted_version: received ? 6 : null, preparer_actor_id: "id-maker", reviewer_actor_id: "id-checker", posted_actor_id: received ? "id-poster" : null };
  const payment = { id: "FI1-plan", workspace_id: "work", organization_id: "org", legal_entity_id: "entity", source_kind: "APPayment", source_id: "native-invoice", entry_id: "payment-entry", period_id: "period", posting_date: "2026-10-03", currency_code: "USD", currency_precision: 2, status: "Reviewed", phase: 1, plan_digest: "a".repeat(64), validation_digest: "b".repeat(64), preparer_actor_id: "id-maker", reviewer_actor_id: "id-checker", posting_effect_id: null, payment_link_id: null, amount_minor: "1500", allocated_before_minor: "0", invoice_version: 3 };
  const invoice = { id: "part-invoice", order_id: "partial-order", number: "PPI-ORDER-1-1", sequence: 1, quantity_text: "3", total_minor: "3600", posting_date: "2026-10-03", period_id: "period", native_invoice_id: "native-invoice", accrual_plan_id: "native-accrual-plan", accrual_effect_id: accrued ? "accrual-effect" : null, stage: accrued ? "Accrued" : "AccrualReviewed", created_version: 7, approved_version: 8, prepared_version: 9, reviewed_version: 10, posted_version: accrued ? 11 : null, accrual_preparer_actor_id: "id-maker", accrual_reviewer_actor_id: "id-checker", accrual_posted_actor_id: accrued ? "id-poster" : null, native_status: "Approved", native_version: 3, paid_minor: "0", outstanding_minor: "3600", payment_links: [], installment_plans: accrued ? [payment] : [] };
  return { order: { id: "partial-order", number: "ORDER-1", purchase_order_id: "native-po", row_version: phase === "receipt" ? 5 : accrued ? 11 : 10, stage: "Approved", total_minor: "12000", ...scope, request: { quantity: "10", unit_price_minor: "1200", currency_code: "USD", organization_code: "ORG", entity_code: "ENTITY", posting_date: "2026-10-03", period_id: "period", journal_code: "STOCK", ap_account_code: "AP", cash_account_code: "CASH" } }, receipts: [receipt], invoices: received ? [invoice] : [], totals: { ordered_quantity: "10", reserved_receipt_quantity: "4", received_quantity: received ? "4" : "0", invoiced_quantity: received ? "3" : "0", received_minor: received ? "4800" : "0", accrued_minor: accrued ? "3600" : "0", paid_minor: "0", outstanding_minor: accrued ? "3600" : "0" } };
}
function Begin({ actor }: { actor: string }) {
  const auth = useBrowserSession();
  return <><button onClick={() => auth.begin({ tenantId: "tenant", csrfToken: "csrf", expiresAt: "2099-01-01T00:00:00Z" }, actor, auth.revision)}>Begin fixture</button><button onClick={() => auth.elevate("2099-01-01T00:00:00Z", auth.revision)}>Elevate fixture</button></>;
}
const response = (value: unknown) => new Response(JSON.stringify(value), { status: 200, headers: { "Content-Type": "application/json" } });
afterEach(() => vi.unstubAllGlobals());

it.each(["receipt", "accrual", "payment"] as const)("requires a third canonical human for %s publication even with all permissions", async (phase) => {
  const writes: string[] = [], source = detail(phase);
  vi.stubGlobal("fetch", vi.fn(async (path: RequestInfo | URL, request?: RequestInit) => {
    if (String(path).endsWith("/auth/me")) return response({ id: "id-checker", username: "checker", principal_type: "user", permissions, authorized_scopes: { workspaces: ["work"] } });
    if (request?.method === "POST") { writes.push(String(request.body)); return response(source); }
    if (String(path).endsWith("/scopes")) return response({ records: [scope] });
    if (String(path).endsWith("/options")) return response(options);
    if (String(path).endsWith("/orders")) return response({ records: [source] });
    return response(source);
  }));
  render(<BrowserSessionProvider><Begin actor="checker" /><ProcurementPartialPage locale="en" /></BrowserSessionProvider>);
  fireEvent.click(screen.getByRole("button", { name: "Begin fixture" }));
  fireEvent.click(screen.getByRole("button", { name: "Elevate fixture" }));
  await screen.findByRole("option", { name: "Organization · Entity · USD" });
  fireEvent.change(screen.getByLabelText("Organization and legal entity"), { target: { value: "entity" } });
  fireEvent.click(await screen.findByRole("button", { name: "Open ORDER-1" }));
  await screen.findByRole("heading", { name: "ORDER-1" });
  fireEvent.change(screen.getByLabelText("Review or posting reason"), { target: { value: "My review is already retained" } });
  const label = { receipt: "Post stock receiving and GL", accrual: "Post invoice accrual", payment: "Post installment" }[phase];
  expect(screen.getByRole("button", { name: label })).toBeDisabled();
  expect(screen.getByText("Publication requires a third human distinct from the preparer and reviewer.")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: label }));
  expect(writes).toHaveLength(0);
});

it.each(["receipt", "accrual", "payment"] as const)("allows the authorized third poster to continue %s publication", async (phase) => {
  const source = detail(phase);
  vi.stubGlobal("fetch", vi.fn(async (path: RequestInfo | URL) => {
    if (String(path).endsWith("/auth/me")) return response({ id: "id-poster", username: "poster", principal_type: "user", permissions, authorized_scopes: { workspaces: ["work"] } });
    if (String(path).endsWith("/scopes")) return response({ records: [scope] });
    if (String(path).endsWith("/options")) return response(options);
    if (String(path).endsWith("/orders")) return response({ records: [source] });
    return response(source);
  }));
  render(<BrowserSessionProvider><Begin actor="poster" /><ProcurementPartialPage locale="en" /></BrowserSessionProvider>);
  fireEvent.click(screen.getByRole("button", { name: "Begin fixture" }));
  fireEvent.click(screen.getByRole("button", { name: "Elevate fixture" }));
  await screen.findByRole("option", { name: "Organization · Entity · USD" });
  fireEvent.change(screen.getByLabelText("Organization and legal entity"), { target: { value: "entity" } });
  fireEvent.click(await screen.findByRole("button", { name: "Open ORDER-1" }));
  await screen.findByRole("heading", { name: "ORDER-1" });
  fireEvent.change(screen.getByLabelText("Review or posting reason"), { target: { value: "Third human publication" } });
  await waitFor(() => expect(screen.getByRole("button", { name: { receipt: "Post stock receiving and GL", accrual: "Post invoice accrual", payment: "Post installment" }[phase] })).toBeEnabled());
});
