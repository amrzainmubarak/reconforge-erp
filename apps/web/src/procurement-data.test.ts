import { describe, expect, it } from "vitest";
import { parseProcurementCycle, type ProcurementScope } from "./procurement-data";

const scope: ProcurementScope = { workspace_id: "work", organization_id: "org", legal_entity_id: "entity", organization_code: "ORG", entity_code: "ENTITY", organization_name: "Synthetic", entity_name: "Synthetic", currency_code: "USD" };
const cycle = { id: "cycle", ...scope, number: "PO-1", row_version: 1, stage: "Draft", next_action: "submit-order", total_minor: "9000000000000000000", purchase_order_id: "po", receipt_plan_id: null, goods_receipt_id: null, invoice_id: null, accrual_plan_id: null, payment_plan_id: null, accrual_effect_id: null, payment_effect_id: null, payment_link_id: null, request: { organization_code: "ORG", entity_code: "ENTITY", unit_price_minor: "9000000000000000000", quantity: "1", currency_code: "USD" } };

describe("procurement financial response contracts", () => {
  it("retains money greater than JavaScript safe integer as exact text", () => { expect(parseProcurementCycle(cycle, scope).total_minor).toBe("9000000000000000000"); });
  it("rejects numeric money and an action inconsistent with its actual stage", () => {
    expect(() => parseProcurementCycle({ ...cycle, total_minor: 9000000000000000000 }, scope)).toThrow("procurement_contract_invalid");
    expect(() => parseProcurementCycle({ ...cycle, next_action: "pay" }, scope)).toThrow("procurement_contract_invalid");
  });
  it("rejects both hierarchy IDs and business code scope confusion", () => {
    expect(() => parseProcurementCycle({ ...cycle, legal_entity_id: "foreign" }, scope)).toThrow("procurement_contract_invalid");
    expect(() => parseProcurementCycle({ ...cycle, request: { ...cycle.request, entity_code: "FOREIGN" } }, scope)).toThrow("procurement_contract_invalid");
  });
});
