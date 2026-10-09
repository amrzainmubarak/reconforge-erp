import { afterEach, describe, expect, it, vi } from "vitest";
import { distinctPartialPoster, installmentCommand, parseInstallmentPlan, parsePartialDetail, partialCommand, partialDocumentPage, partialItemCatalog, partialOrderPage, partialRoot, scaledQuantity } from "./procurement-partial-data";
import type { ProcurementScope } from "./procurement-data";
import { prepareScopedCommand } from "./scoped-command";
import type { BrowserAdminSession } from "./types";

const scope: ProcurementScope = { workspace_id: "work", organization_id: "org", legal_entity_id: "entity", organization_code: "ORG", entity_code: "ENTITY", organization_name: "Organization", entity_name: "Entity", currency_code: "USD" };
const session = { tenantId: "tenant", csrfToken: "test-csrf" } as BrowserAdminSession;
function draft() { return { order: { id: "partial-order", number: "ORDER-1", purchase_order_id: "native-po", row_version: 1, stage: "Draft", total_minor: "12000", workspace_id: "work", organization_id: "org", legal_entity_id: "entity", request: { number: "ORDER-1", quantity: "10", unit_price_minor: "1200", currency_code: "USD", organization_code: "ORG", entity_code: "ENTITY" } }, receipts: [], invoices: [], totals: { ordered_quantity: "10", reserved_receipt_quantity: "0", received_quantity: "0", invoiced_quantity: "0", received_minor: "0", accrued_minor: "0", paid_minor: "0", outstanding_minor: "0" } }; }
function plan() { return { id: "FI1-plan", source_kind: "APPayment", source_id: "invoice", workspace_id: "work", organization_id: "org", legal_entity_id: "entity", entry_id: "native-entry", posting_date: "2026-10-03", period_id: "period", currency_code: "USD", currency_precision: 2, status: "Prepared", phase: 0, plan_digest: "a".repeat(64), validation_digest: "b".repeat(64), preparer_actor_id: "maker", reviewer_actor_id: null, posting_effect_id: null, payment_link_id: null, amount_minor: "1000", allocated_before_minor: "0", invoice_version: 5 }; }
function multilineDraft() {
  const source = draft();
  return { ...source, order: { ...source.order, multiline: true, line_count: 2, total_minor: "17000" },
    lines: [
      { id: "line-each", sequence: 1, item_code: "ITEM", uom_id: "unit-each", uom_code: "EA", quantity_precision: 0, location_code: "MAIN/STOCK", policy_code: "FIFO", quantity_text: "10", unit_price_minor: "1200", total_minor: "12000", reserved_receipt_quantity: "0", received_quantity: "0", invoiced_quantity: "0" },
      { id: "line-weight", sequence: 2, item_code: "WEIGHT", uom_id: "unit-kg", uom_code: "KG", quantity_precision: 2, location_code: "NORTH/STOCK", policy_code: "FIFO", quantity_text: "2.50", unit_price_minor: "2000", total_minor: "5000", reserved_receipt_quantity: "0", received_quantity: "0", invoiced_quantity: "0" },
    ], totals: { ...source.totals, ordered_quantity: "0" },
    pages: { receipt_after: 0, invoice_after: 0, page_size: 25, receipt_count: 0, invoice_count: 0, next_receipt_after: null as number | null, next_invoice_after: null as number | null } };
}
afterEach(() => vi.unstubAllGlobals());

describe("partial procurement exact source contract", () => {
  it("conserves quantity above JS safe integer range without floating point", () => {
    expect(scaledQuantity("9007199254740993.001")).toBe(9007199254740993001000n);
    expect(parsePartialDetail(draft(), scope).totals.ordered_quantity).toBe("10");
  });
  it("rejects cross-entity responses and inconsistent current capacity totals", () => {
    const cross = draft(); cross.order.legal_entity_id = "outside";
    expect(() => parsePartialDetail(cross, scope)).toThrow("contract_invalid");
    const wrong = draft(); wrong.totals.received_quantity = "1";
    expect(() => parsePartialDetail(wrong, scope)).toThrow("contract_invalid");
    const rounded = draft(); rounded.order.total_minor = "12001";
    expect(() => parsePartialDetail(rounded, scope)).toThrow("contract_invalid");
  });
  it("requires exact native invoice, phase and effects on installments", () => {
    expect(parseInstallmentPlan(plan(), scope, "invoice").phase).toBe(0);
    expect(() => parseInstallmentPlan(plan(), scope, "other")).toThrow("contract_invalid");
    expect(() => parseInstallmentPlan({ ...plan(), phase: 2, status: "Posted", reviewer_actor_id: "reviewer" }, scope, "invoice")).toThrow("contract_invalid");
    expect(() => parseInstallmentPlan({ ...plan(), phase: 1, status: "Reviewed", reviewer_actor_id: "maker" }, scope, "invoice")).toThrow("contract_invalid");
  });
  it("compares canonical actor IDs and fails closed without both retained identities", () => {
    expect(distinctPartialPoster("id-maker", "id-checker", "id-poster")).toBe(true);
    for (const poster of [null, "", "id-maker", "id-checker"]) expect(distinctPartialPoster("id-maker", "id-checker", poster)).toBe(false);
    expect(distinctPartialPoster("id-maker", null, "id-poster")).toBe(false);
  });
  it("requires phase-consistent retained receipt provenance and rejects a reviewer-posted receipt", () => {
    const base = draft();
    const receipt = { id: "part", order_id: "partial-order", number: "PPR-ORDER-1-1", sequence: 1, quantity_text: "4", total_minor: "4800", posting_date: "2026-10-03", period_id: "period", receipt_plan_id: "native-plan", goods_receipt_id: "native-receipt", stage: "Posted", created_version: 4, reviewed_version: 5, posted_version: 6, preparer_actor_id: "id-maker", reviewer_actor_id: "id-checker", posted_actor_id: "id-poster" };
    const detail = { ...base, order: { ...base.order, stage: "Approved", row_version: 6 }, receipts: [receipt], totals: { ...base.totals, reserved_receipt_quantity: "4", received_quantity: "4", received_minor: "4800" } };
    expect(parsePartialDetail(detail, scope).receipts[0].posted_actor_id).toBe("id-poster");
    expect(() => parsePartialDetail({ ...detail, receipts: [{ ...receipt, posted_actor_id: "id-checker" }] }, scope)).toThrow("contract_invalid");
    expect(() => parsePartialDetail({ ...detail, receipts: [{ ...receipt, reviewer_actor_id: null }] }, scope)).toThrow("contract_invalid");
  });
  it("binds cookies, CSRF, entity scope and exact frozen command through a lost acknowledgement retry", async () => {
    const command = prepareScopedCommand(partialRoot + "/orders", { number: "ORDER-1", quantity: "10", unit_price_minor: "1200" });
    const fetch = vi.fn().mockResolvedValueOnce({ ok: true, json: async () => ({ unrelated: true }) }).mockResolvedValueOnce({ ok: true, json: async () => draft() });
    vi.stubGlobal("fetch", fetch);
    await expect(partialCommand(session, scope, command)).rejects.toThrow("contract_invalid");
    expect((await partialCommand(session, scope, command)).order.id).toBe("partial-order");
    expect(fetch.mock.calls[0][1].body).toBe(fetch.mock.calls[1][1].body);
    expect(fetch.mock.calls[0][1]).toMatchObject({ method: "POST", credentials: "same-origin", headers: { "X-ReconForge-CSRF": "test-csrf", "X-ReconForge-Legal-Entity": "entity", "X-ReconForge-Workspace": "work" } });
    expect(Object.isFrozen(command.body)).toBe(true);
  });
  it("rejects an acknowledgement for a different source quantity", async () => {
    const command = prepareScopedCommand(partialRoot + "/orders", { number: "ORDER-1", quantity: "9", unit_price_minor: "1200" });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => draft() }));
    await expect(partialCommand(session, scope, command)).rejects.toThrow("contract_invalid");
  });
  it("binds installment acknowledgement to the selected native invoice and exact amount", async () => {
    const command = prepareScopedCommand("/api/v1/financial-installments/plans", { source_id: "invoice", source_kind: "APPayment", amount_minor: "1000", period_id: "period", posting_date: "2026-10-03" });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ plan: plan() }) }));
    const invoice = { native_invoice_id: "invoice" } as Parameters<typeof installmentCommand>[2];
    expect((await installmentCommand(session, scope, invoice, command)).amount_minor).toBe("1000");
    await expect(installmentCommand(session, scope, { ...invoice, native_invoice_id: "different" }, command)).rejects.toThrow("contract_invalid");
  });
  it("keeps each unit and warehouse authoritative and never adds heterogeneous quantities", () => {
    const source = multilineDraft();
    expect(parsePartialDetail(source, scope).lines?.map((line) => [line.uom_code, line.quantity_text, line.location_code])).toEqual([["EA", "10", "MAIN/STOCK"], ["KG", "2.50", "NORTH/STOCK"]]);
    source.totals.ordered_quantity = "12.50";
    expect(() => parsePartialDetail(source, scope)).toThrow("contract_invalid");
  });
  it("rejects line precision, cost, duplicate identity and capacity corruption", () => {
    for (const change of [
      (value: ReturnType<typeof multilineDraft>) => { value.lines[0].quantity_text = "10.01"; },
      (value: ReturnType<typeof multilineDraft>) => { value.lines[1].total_minor = "5001"; },
      (value: ReturnType<typeof multilineDraft>) => { value.lines[1].id = value.lines[0].id; },
      (value: ReturnType<typeof multilineDraft>) => { value.lines[1].invoiced_quantity = "1"; },
    ]) { const source = multilineDraft(); change(source); expect(() => parsePartialDetail(source, scope)).toThrow("contract_invalid"); }
  });
  it("rejects missing document pages rather than showing truncated history as complete", () => {
    const source = multilineDraft(); source.pages.receipt_count = 30; source.pages.next_receipt_after = 25;
    expect(() => parsePartialDetail(source, scope)).toThrow("contract_invalid");
  });
  it("retains nested exact purchase lines across an unverified acknowledgement retry", async () => {
    const lines = multilineDraft().lines.map((line) => ({ item_code: line.item_code, location_code: line.location_code, policy_code: line.policy_code, quantity: line.quantity_text, unit_price_minor: line.unit_price_minor }));
    const command = prepareScopedCommand(partialRoot + "/orders/multiline", { number: "ORDER-1", lines });
    lines[1].quantity = "999";
    const fetch = vi.fn().mockResolvedValueOnce({ ok: true, json: async () => ({ unrelated: true }) }).mockResolvedValueOnce({ ok: true, json: async () => multilineDraft() });
    vi.stubGlobal("fetch", fetch);
    await expect(partialCommand(session, scope, command)).rejects.toThrow("contract_invalid");
    expect((await partialCommand(session, scope, command)).order.line_count).toBe(2);
    expect(fetch.mock.calls[0][1].body).toBe(fetch.mock.calls[1][1].body);
    expect(JSON.parse(fetch.mock.calls[1][1].body).lines[1].quantity).toBe("2.50");
    expect(Object.isFrozen(command.body.lines)).toBe(true);
  });
  it("encodes authenticated bounded page queries independently of command paths", async () => {
    const fetch = vi.fn().mockResolvedValueOnce({ ok: true, json: async () => ({ records: [], next_after: null, page_size: 25 }) }).mockResolvedValueOnce({ ok: true, json: async () => multilineDraft() }).mockResolvedValueOnce({ ok: true, json: async () => ({ records: [], next_after: null }) });
    vi.stubGlobal("fetch", fetch);
    await partialOrderPage(session, scope, "parent/one");
    await partialDocumentPage(session, scope, "partial-order", 0, 0);
    await partialItemCatalog(session, scope, "x&after=foreign", "ITEM/1");
    expect(fetch.mock.calls.map((call) => call[0])).toEqual([partialRoot + "/orders/page?after=parent%2Fone", partialRoot + "/orders/partial-order/documents?receipt_after=0&invoice_after=0", partialRoot + "/catalog/items?search=x%26after%3Dforeign&after=ITEM%2F1"]);
    expect(fetch.mock.calls.every((call) => call[1].method === "GET" && call[1].body === undefined)).toBe(true);
  });
});
