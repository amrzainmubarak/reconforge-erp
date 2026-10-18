import { describe, expect, it } from "vitest";
import { parseReceiptView, receiptMoney } from "./inventory-receipt-data";
import { receiptFixture } from "./inventory-receipt-fixtures";
const scope = { workspace: "work", organization: "org", entity: "entity" };
describe("receipt browser contract", () => {
 it("keeps values above JS integer range exact and formats retained precision", () => { const v = parseReceiptView({ receipt: receiptFixture() }, scope); expect(v.total_value_minor).toBe("9007199254740993"); expect(receiptMoney(v.total_value_minor, 2)).toBe("90071992547409.93"); expect(receiptMoney("12000", 3)).toBe("12.000"); });
 it("refuses scope substitution, numeric money, self review, imbalance and unknown fields", () => { for (const patch of [{ scope: { ...receiptFixture().scope, workspace_id: "sibling" } }, { total_value_minor: 9007199254740993 }, { reviewer_id: "maker" }, { lines: [{ account_id: "stock", debit_minor: "1", credit_minor: "0" }, { account_id: "clearing", debit_minor: "0", credit_minor: "1" }] }, { hidden: "field" }]) expect(() => parseReceiptView({ receipt: { ...receiptFixture("Reviewed"), ...patch } }, scope)).toThrow("inventory_receipt_contract_invalid"); });
 it("requires complete reviewed effect evidence before showing committed", () => { expect(parseReceiptView({ receipt: receiptFixture("Committed") }, scope).status).toBe("Committed"); expect(() => parseReceiptView({ receipt: { ...receiptFixture("Committed"), effect_json: null } }, scope)).toThrow(); });
});
