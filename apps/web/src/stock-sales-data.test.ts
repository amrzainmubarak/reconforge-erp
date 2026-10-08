import { afterEach, describe, expect, it, vi } from "vitest";
import { executeStockCommand, parseStockOrder, prepareStockCommand } from "./stock-sales-data";

const scope = { workspace_id: "work", organization_id: "org", legal_entity_id: "entity" };
function document() {
  return { ...scope, id: "STSALE-1", number: "PRODUCT-1", status: "Draft", row_version: 1, source_digest: "a".repeat(64), currency_code: "USD", total_minor: "9007199254740993", cogs_minor: null, quantity: "1", quantity_scaled: "1", quantity_precision: 0, unit_price_minor: "9007199254740993", net_unit_price_minor: "9007199254740993", discount_basis_points: 0, description: "Product", customer_code: "C", customer_reference: "PO-1", item_code: "I", warehouse_code: "W", location_code: "L", order_date: "2026-10-09", created_by: "maker", approved_by: null, issue_reviewer_id: null, monetary_policy: { precision: 2 }, movement_id: null, valuation_id: null, cogs_entry_id: null, cogs_effect_id: null, invoice_id: null, invoice_plan_id: null, collection_plan_id: null, receipt_id: null, events: [{ version: 1, actor_id: "maker", operation: "create", reason: "Create", status: "Draft", audit_event_id: "audit-1" }] };
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
});
