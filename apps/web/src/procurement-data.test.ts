import { afterEach, describe, expect, it, vi } from "vitest";
import { parseProcurementAcknowledgement, parseProcurementCycle, parseProcurementOptions, procurementSaveSupplier, procurementFetch, procurementActions, procurementStages, type ProcurementScope } from "./procurement-data";
import type { BrowserAdminSession } from "./types";

const scope: ProcurementScope = { workspace_id: "work", organization_id: "org", legal_entity_id: "entity", organization_code: "ORG", entity_code: "ENTITY", organization_name: "Synthetic", entity_name: "Synthetic", currency_code: "USD" };
const cycle = { id: "cycle", ...scope, number: "PO-1", row_version: 1, stage: "Draft", next_action: "submit-order", total_minor: "9000000000000000000", purchase_order_id: "po", receipt_plan_id: null, goods_receipt_id: null, invoice_id: null, accrual_plan_id: null, payment_plan_id: null, accrual_effect_id: null, payment_effect_id: null, payment_link_id: null, request: { organization_code: "ORG", entity_code: "ENTITY", unit_price_minor: "9000000000000000000", quantity: "1", currency_code: "USD" } };

describe("procurement financial response contracts", () => {
  afterEach(() => vi.unstubAllGlobals());
  it("encodes paginated catalog queries separately from scoped paths", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("{}", { status: 200 })); vi.stubGlobal("fetch", fetchMock);
    const session = { tenantId: "tenant", csrfToken: "synthetic-csrf" } as BrowserAdminSession;
    await procurementFetch(session, scope.workspace_id, scope, "/api/v1/procurement-partial/catalog/items", { query: { search: "صنف & bolt", after: "ITEM/1", limit: 25 } });
    const [url, options] = fetchMock.mock.calls[0];
    const parsed = new URL(url, "https://localhost");
    expect(parsed.searchParams.get("search")).toBe("صنف & bolt");
    expect(parsed.searchParams.get("after")).toBe("ITEM/1");
    expect(options).toMatchObject({ method: "GET", credentials: "same-origin", headers: { "X-ReconForge-Legal-Entity": "entity" } });
    await expect(procurementFetch(session, "work", scope, "/api/v1/test?limit=25")).rejects.toThrow("procurement_contract_invalid");
    await expect(procurementFetch(session, "work", scope, "/api/v1/test", { query: { limit: NaN } })).rejects.toThrow("procurement_contract_invalid");
    await expect(procurementFetch(session, "work", scope, "/api/v1/test", { query: { limit: 25 }, body: {} })).rejects.toThrow("procurement_contract_invalid");
  });
  it("retains money greater than JavaScript safe integer as exact text", () => { expect(parseProcurementCycle(cycle, scope).total_minor).toBe("9000000000000000000"); });
  it("rejects numeric money and an action inconsistent with its actual stage", () => {
    expect(() => parseProcurementCycle({ ...cycle, total_minor: 9000000000000000000 }, scope)).toThrow("procurement_contract_invalid");
    expect(() => parseProcurementCycle({ ...cycle, next_action: "pay" }, scope)).toThrow("procurement_contract_invalid");
  });
  it("rejects both hierarchy IDs and business code scope confusion", () => {
    expect(() => parseProcurementCycle({ ...cycle, legal_entity_id: "foreign" }, scope)).toThrow("procurement_contract_invalid");
    expect(() => parseProcurementCycle({ ...cycle, request: { ...cycle.request, entity_code: "FOREIGN" } }, scope)).toThrow("procurement_contract_invalid");
  });
  it("binds every transition acknowledgement to its exact purchase, stage and version", () => {
    for (let index = 0; index < procurementActions.length; index += 1) {
      const command = { path: `/api/v1/procurement-operations/cycles/cycle/commands/${procurementActions[index]}`, body: { expected_version: index + 1, command_id: "retained", reason: "Human review" } };
      const result = { cycle: { ...cycle, row_version: index + 2, stage: procurementStages[index + 1], next_action: procurementActions[index + 1] ?? "" }, receipt: null };
      expect(parseProcurementAcknowledgement(result, scope, command).cycle.row_version).toBe(index + 2);
      expect(() => parseProcurementAcknowledgement({ ...result, cycle: { ...result.cycle, id: "unrelated" } }, scope, command)).toThrow("procurement_contract_invalid");
      expect(() => parseProcurementAcknowledgement({ ...result, cycle }, scope, command)).toThrow("procurement_contract_invalid");
    }
  });
  it("binds a new order to its captured exact quantity, price and catalog references", () => {
    const body = { number: "po-1", supplier_code: "SUP", item_code: "ITEM", currency_code: "USD", quantity: "00010.00", unit_price_minor: "1200", policy_code: "FIFO", journal_code: "STOCK", ap_account_code: "AP", cash_account_code: "CASH", organization_code: "ORG", entity_code: "ENTITY", posting_date: "2026-10-08", period_id: "period", location_code: "MAIN/STOCK", workspace: "work", command_id: "retained" };
    const request = { ...body, quantity: "10.00" };
    const result = { cycle: { ...cycle, request, total_minor: "12000" }, receipt: null }, command = { path: "/api/v1/procurement-operations/cycles", body };
    expect(parseProcurementAcknowledgement(result, scope, command).cycle.number).toBe("PO-1");
    expect(() => parseProcurementAcknowledgement({ ...result, cycle: { ...result.cycle, request: { ...request, quantity: "11" } } }, scope, command)).toThrow("procurement_contract_invalid");
    expect(() => parseProcurementAcknowledgement({ ...result, cycle: { ...result.cycle, request: { ...request, cash_account_code: "OTHER" } } }, scope, command)).toThrow("procurement_contract_invalid");
  });
  it("saves a real scoped supplier through the existing Payables contract without a generated command field", async () => {
    const supplier = { id: "supplier", supplier_code: "VENDOR", name: "Synthetic vendor", currency_code: "USD", tax_identifier: "SYNTHETIC", status: "Active", workspace_id: "work", organization_id: "org", legal_entity_id: "entity" };
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(supplier), { status: 200 })); vi.stubGlobal("fetch", fetchMock);
    const session = { tenantId: "tenant", csrfToken: "synthetic-csrf" } as BrowserAdminSession;
    expect((await procurementSaveSupplier(session, scope, { supplier_code: "vendor", name: "Synthetic vendor", tax_identifier: "SYNTHETIC" })).supplier_code).toBe("VENDOR");
    expect(fetchMock).toHaveBeenCalledWith("/api/v1/payables/suppliers", expect.objectContaining({ method: "POST", credentials: "same-origin", headers: expect.objectContaining({ "X-ReconForge-CSRF": "synthetic-csrf", "X-ReconForge-Legal-Entity": "entity" }) }));
    const sent = JSON.parse(fetchMock.mock.calls[0][1].body); expect(sent).not.toHaveProperty("command_id"); expect(sent).toMatchObject({ workspace: "work", entity_code: "ENTITY", currency_code: "USD", status: "Active" });
    fetchMock.mockResolvedValue(new Response(JSON.stringify({ ...supplier, legal_entity_id: "foreign" }), { status: 200 }));
    await expect(procurementSaveSupplier(session, scope, { supplier_code: "vendor", name: "Synthetic vendor", tax_identifier: "SYNTHETIC" })).rejects.toThrow("procurement_contract_invalid");
  });
  it("accepts only bounded named catalog rows with journal-account chart references", () => {
    const option = { code: "SUP", name: "Synthetic", currency_code: "USD", chart_code: "DEFAULT" };
    const value = { suppliers: [option], items: [option], locations: [option], policies: [option], periods: [{ id: "period", name: "Synthetic", start_date: "2026-10-01", end_date: "2026-10-31" }], journals: [option], accounts: [{ ...option, code: "AP", account_type: "Liability" }] };
    expect(parseProcurementOptions(value).journals[0].chart_code).toBe("DEFAULT");
    expect(() => parseProcurementOptions({ ...value, suppliers: Array.from({ length: 201 }, () => option) })).toThrow("procurement_contract_invalid");
    expect(() => parseProcurementOptions({ ...value, locations: [["MAIN/STOCK", "Synthetic"]] })).toThrow("procurement_contract_invalid");
    expect(() => parseProcurementOptions({ ...value, accounts: [{ code: "AP", account_type: "Liability" }] })).toThrow("procurement_contract_invalid");
  });
});
