import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { BrowserSessionProvider, useBrowserSession } from "../browserSession";
import { ProcurementPartialPage } from "./ProcurementPartialPage";
import { procurementTranslate } from "../procurement-i18n";
import { partialTranslate } from "../procurement-partial-i18n";

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
    if (String(path).includes("/orders/page?")) return response({ records: [{ ...source.order, multiline: false, line_count: 1 }], next_after: null, page_size: 25 });
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
    if (String(path).includes("/orders/page?")) return response({ records: [{ ...source.order, multiline: false, line_count: 1 }], next_after: null, page_size: 25 });
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

it.each(["en", "ar"] as const)("writes a real nested multiwarehouse purchase command and retains its exact retry in %s", async (locale) => {
  const t = (key: Parameters<typeof procurementTranslate>[1]) => procurementTranslate(locale, key);
  const p = (key: Parameters<typeof partialTranslate>[1]) => partialTranslate(locale, key);
  const writes: string[] = [];
  const references = { suppliers: [{ code: "SUP", currency_code: "USD" }], items: [], locations: [{ code: "MAIN/STOCK" }, { code: "NORTH/STOCK" }], policies: [{ code: "FIFO" }], periods: [{ id: "period", name: "October", start_date: "2026-10-01", end_date: "2026-10-31" }], journals: [{ code: "STOCK", chart_code: "CHART" }], accounts: [{ code: "AP", chart_code: "CHART", account_type: "Liability" }, { code: "CASH", chart_code: "CHART", account_type: "Asset" }] };
  vi.stubGlobal("fetch", vi.fn(async (path: RequestInfo | URL, request?: RequestInit) => {
    if (String(path).endsWith("/auth/me")) return response({ id: "id-maker", username: "maker", principal_type: "user", permissions, authorized_scopes: { workspaces: ["work"] } });
    if (request?.method === "POST") { writes.push(String(request.body)); return response({ unverified: true }); }
    if (String(path).endsWith("/scopes")) return response({ records: [scope] });
    if (String(path).endsWith("/options")) return response(references);
    if (String(path).includes("/catalog/items?")) return response({ records: [{ code: "ITEM", name: "Each product", uom_code: "EA", decimal_places: 0 }, { code: "WEIGHT", name: "Weighted product", uom_code: "KG", decimal_places: 2 }], next_after: null });
    return response({ records: [], next_after: null, page_size: 25 });
  }));
  render(<BrowserSessionProvider><Begin actor="maker" /><ProcurementPartialPage locale={locale} /></BrowserSessionProvider>);
  fireEvent.click(screen.getByRole("button", { name: "Begin fixture" }));
  fireEvent.click(screen.getByRole("button", { name: "Elevate fixture" }));
  await screen.findByRole("option", { name: "Organization · Entity · USD" });
  fireEvent.change(screen.getByLabelText(t("scope")), { target: { value: "entity" } });
  const form = await screen.findByRole("form", { name: t("newOrder") });
  fireEvent.click(form.closest("details")!.querySelector("summary")!);
  fireEvent.click(within(form).getByLabelText(p("enterpriseOrder")));
  await screen.findByRole("option", { name: "WEIGHT · Weighted product" });
  fireEvent.click(within(form).getByRole("button", { name: p("addLine") }));
  for (const [label, value] of [[t("number"), "UI-MULTI"], [t("supplier"), "SUP"], [t("date"), "2026-10-03"], [t("period"), "period"], [t("journal"), "STOCK"], [t("ap"), "AP"], [t("cash"), "CASH"],
    [t("item") + " 1", "ITEM"], [t("quantity") + " 1", "10"], [t("unitPrice") + " 1", "1200"], [t("location") + " 1", "MAIN/STOCK"], [t("policy") + " 1", "FIFO"],
    [t("item") + " 2", "WEIGHT"], [t("quantity") + " 2", "2.50"], [t("unitPrice") + " 2", "2000"], [t("location") + " 2", "NORTH/STOCK"], [t("policy") + " 2", "FIFO"]]) {
    fireEvent.change(within(form).getByLabelText(label), { target: { value } });
  }
  fireEvent.submit(form);
  await screen.findByRole("button", { name: t("retry") });
  expect(writes).toHaveLength(1);
  const command = JSON.parse(writes[0]);
  expect(command).toMatchObject({ number: "UI-MULTI", supplier_code: "SUP", organization_code: "ORG", entity_code: "ENTITY", workspace: "work", currency_code: "USD", lines: [{ item_code: "ITEM", quantity: "10", unit_price_minor: "1200", location_code: "MAIN/STOCK", policy_code: "FIFO" }, { item_code: "WEIGHT", quantity: "2.50", unit_price_minor: "2000", location_code: "NORTH/STOCK", policy_code: "FIFO" }] });
  expect(command.command_id).toEqual(expect.any(String));
  expect(within(form).getByLabelText(t("quantity") + " 2")).toBeDisabled();
  expect(screen.getByRole("main")).toHaveAttribute("dir", locale === "ar" ? "rtl" : "ltr");
  fireEvent.click(screen.getByRole("button", { name: t("retry") }));
  await waitFor(() => expect(writes).toHaveLength(2));
  expect(writes[1]).toBe(writes[0]);
});
