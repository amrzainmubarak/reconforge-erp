import { afterEach, describe, expect, it, vi } from "vitest";
import { executeStockCommand, parseStockOrder, prepareStockCommand, stockFinancialDuties, stockStages } from "./stock-sales-data";

const scope = { workspace_id: "work", organization_id: "org", legal_entity_id: "entity" };
function document() {
  return { ...scope, id: "STSALE-1", number: "PRODUCT-1", status: "Draft", row_version: 1, source_digest: "a".repeat(64), currency_code: "USD", total_minor: "9007199254740993", cogs_minor: null, quantity: "1", quantity_scaled: "1", quantity_precision: 0, unit_price_minor: "9007199254740993", net_unit_price_minor: "9007199254740993", discount_basis_points: 0, description: "Product", customer_code: "C", customer_reference: "PO-1", item_code: "I", warehouse_code: "W", location_code: "L", order_date: "2026-10-09", created_by: "maker", approved_by: null, issue_reviewer_id: null, issue_preparer_id: null, monetary_policy: { precision: 2 }, movement_id: null, valuation_id: null, cogs_entry_id: null, cogs_effect_id: null, invoice_id: null, invoice_plan_id: null, collection_plan_id: null, receipt_id: null, events: [{ version: 1, actor_id: "maker", operation: "create", reason: "Create", status: "Draft", audit_event_id: "audit-1" }] };
}
afterEach(() => vi.unstubAllGlobals());
describe("stock sales exact transport and evidence", () => {
  it("retains integer money above Number precision and rejects foreign scope", () => {
    expect(parseStockOrder(document(), scope).total_minor).toBe("9007199254740993");
    expect(() => parseStockOrder({ ...document(), legal_entity_id: "other" }, scope)).toThrow();
    expect(() => parseStockOrder({ ...document(), total_minor: 9007199254740993 }, scope)).toThrow();
  });
  it("rejects a paid display without complete native stock and settlement links", () => {
    expect(() => parseStockOrder({ ...document(), status: "Paid", events: [{ ...document().events[0], status: "Paid" }] }, scope)).toThrow();
    expect(() => parseStockOrder({ ...document(), events: [] }, scope)).toThrow();
  });
  it("freezes command and scope and retransmits the same packet after lost acknowledgement", async () => {
    const selected = { ...scope }, body = { number: "PRODUCT-1", unit_price_minor: "9007199254740993" };
    const command = prepareStockCommand(selected, "/api/v1/stock-sales/orders", body);
    body.unit_price_minor = "1"; selected.legal_entity_id = "changed";
    const fetchMock = vi.fn().mockRejectedValueOnce(new TypeError("Lost acknowledgement")).mockResolvedValueOnce({ ok: true, json: async () => document() });
    vi.stubGlobal("fetch", fetchMock);
    const session = { tenantId: "t", csrfToken: "csrf" } as Parameters<typeof executeStockCommand>[0];
    await expect(executeStockCommand(session, command)).rejects.toThrow("Lost acknowledgement");
    expect((await executeStockCommand(session, command)).id).toBe("STSALE-1");
    expect(fetchMock.mock.calls[0][1].body).toBe(fetchMock.mock.calls[1][1].body);
    expect(fetchMock.mock.calls[1][1].headers["X-ReconForge-Legal-Entity"]).toBe("entity");
    expect(JSON.parse(fetchMock.mock.calls[1][1].body).unit_price_minor).toBe("9007199254740993");
    expect(fetchMock.mock.calls[1][1].headers["X-ReconForge-CSRF"]).toBe("csrf");
  });
  it("refuses alternate routes and caller supplied idempotency keys", () => {
    expect(() => prepareStockCommand(scope, "/api/v1/finance-core/entries", {})).toThrow();
    expect(() => prepareStockCommand(scope, "/api/v1/stock-sales/orders", { command_id: "spoof" })).toThrow();
  });
  it("derives native-bound duties from immutable stage lineage and refuses same-human publication", () => {
    const statuses = ["Draft", "Submitted", "Approved", "Reserved", "IssuePrepared", "IssueReviewed", "Delivered", "InvoicePrepared", "InvoiceReviewed", "Invoiced"];
    const operations = ["create", "submit", "approve", "reserve", "prepare-issue", "review-issue", "deliver", "prepare-invoice", "review-invoice", "invoice"];
    const actors = ["maker", "maker", "checker", "maker", "maker", "checker", "poster", "maker", "checker", "poster"];
    const events = statuses.map((status, index) => ({ version: index + 1, actor_id: actors[index], operation: operations[index], status, reason: "Verified source", audit_event_id: "AUD-" + index }));
    const posted = { ...document(), status: "Invoiced", row_version: 10, events, cogs_minor: "1", movement_id: "M-1", valuation_id: "V-1", cogs_entry_id: "C-1", cogs_effect_id: "F-1" };
    expect(stockFinancialDuties(parseStockOrder(posted, scope), "invoice")).toEqual({ preparerId: "maker", reviewerId: "checker" });
    expect(() => parseStockOrder({ ...posted, events: events.map((event, index) => index === 9 ? { ...event, actor_id: "checker" } : event) }, scope)).toThrow();
    expect(() => parseStockOrder({ ...posted, events: events.map((event, index) => index === 8 ? { ...event, operation: "review-collection" } : event) }, scope)).toThrow();
  });
});

function restituted(stage: number, cost = "0") {
  const operations = ["create", "submit", "approve", "reserve", "prepare-issue", "review-issue", "deliver", "prepare-invoice", "review-invoice", "invoice"];
  const actors = ["maker", "maker", "checker", "maker", "maker", "checker", "poster", "maker", "checker", "poster"];
  const events = stockStages.slice(0, stage + 1).map((status, index) => ({ version: index + 1, status, operation: operations[index],
    actor_id: actors[index], reason: "Native restituted original", audit_event_id: "AUD-" + index }));
  return { ...document(), status: stockStages[stage], row_version: stage + 1, events,
    cost_admission_policy: "partial-return-restituted-v1", cogs_minor: cost, movement_id: "native-movement", valuation_id: "native-valuation",
    cogs_entry_id: cost === "0" ? null : "native-positive-entry", cogs_effect_id: cost === "0" || stage < 6 ? null : "native-positive-effect" };
}
it.each([4, 5, 6, 9])("reads explicit native zero-total COGS at stage%s without a counterfeit journal", stage => {
  const source = restituted(stage);
  expect(parseStockOrder(source, scope)).toEqual(source);
  for (const patch of [{ cogs_entry_id: "fake-zero-entry" }, { cogs_effect_id: "fake-zero-effect" }, { cogs_minor: null }]) expect(() => parseStockOrder({ ...source, ...patch }, scope)).toThrow();
});
it("keeps positive aggregate COGS on the marked path bound to its actual financial entry and posted effect", () => {
  for (const stage of [4, 5, 6, 9]) {
    const source = restituted(stage, "1");
    expect(parseStockOrder(source, scope)).toEqual(source);
    expect(() => parseStockOrder({ ...source, cogs_entry_id: null }, scope)).toThrow();
    if (stage >= 6) expect(() => parseStockOrder({ ...source, cogs_effect_id: null }, scope)).toThrow();
  }
});
it("retains explicit zero-cost cancellation evidence and all original approval separation", () => {
  const source = restituted(5);
  const cancelled = { ...source, status: "Cancelled", row_version: 7, events: [...source.events,
    { version: 7, actor_id: "poster", operation: "cancel", status: "Cancelled", reason: "Independent cancellation", audit_event_id: "AUD-cancel" }] };
  expect(parseStockOrder(cancelled, scope)).toEqual(cancelled);
  expect(() => parseStockOrder({ ...cancelled, cogs_effect_id: "fake-cancel-effect" }, scope)).toThrow();
  const delivered = restituted(6);
  expect(() => parseStockOrder({ ...delivered, movement_id: null }, scope)).toThrow();
  expect(() => parseStockOrder({ ...delivered, valuation_id: null }, scope)).toThrow();
  expect(() => parseStockOrder({ ...delivered, events: delivered.events.map((event, index) => index === 6 ? { ...event, actor_id: "checker" } : event) }, scope)).toThrow();
});
it.each([null, undefined, true, {}, "partial-return-restituted-v2", " partial-return-restituted-v1"])("refuses an invented native cost admission marker%s", cost_admission_policy => {
  expect(() => parseStockOrder({ ...restituted(6), cost_admission_policy }, scope)).toThrow();
});
it.each([0, 1, 2, 3])("refuses zero-cost admission before original issue preparation at stage%s", stage => {
  expect(() => parseStockOrder(restituted(stage), scope)).toThrow();
});
it("preserves legacy documents and does not accept missing delivered COGS links without the explicit native marker", () => {
  const original = document(), before = structuredClone(original);
  expect(parseStockOrder(original, scope)).toEqual(before);
  expect(original).toEqual(before); expect(original).not.toHaveProperty("cost_admission_policy");
  const { cost_admission_policy: _marker, ...legacy } = restituted(6);
  expect(() => parseStockOrder(legacy, scope)).toThrow();
});

