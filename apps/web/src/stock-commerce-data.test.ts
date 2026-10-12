import { expect, it } from "vitest";
import { parseCommerceOrder, prepareCommerceCommand } from "./stock-commerce-data";
import { commerceFixture } from "./stock-commerce-test-fixtures";

const scope = { workspace_id: "work", organization_id: "org", legal_entity_id: "entity" };
it("recomputes commercial line and tranche progress with exact BigInt money", () => {
  const document = commerceFixture("Paid");
  expect(parseCommerceOrder(document, scope).lines[0].collected_minor).toBe("13500");
  const forged = structuredClone(document); forged.lines[0].collected_minor = "13499";
  expect(() => parseCommerceOrder(forged, scope)).toThrow("commerce_contract_invalid");
  const foreign = { ...document, legal_entity_id: "foreign" };
  expect(() => parseCommerceOrder(foreign, scope)).toThrow("commerce_contract_invalid");
});
it("deep freezes commercial line arrays and participant fields for lost acknowledgement retries", () => {
  const source = { number: "ORDER", lines: [{ item_code: "SKU", quantity: "3" }] };
  const command = prepareCommerceCommand(scope, "/api/v1/stock-sales/commerce/orders", source);
  source.lines[0].quantity = "999";
  expect((command.body.lines as typeof source.lines)[0].quantity).toBe("3");
  expect(Object.isFrozen(command.body.lines)).toBe(true);
  expect(Object.isFrozen((command.body.lines as typeof source.lines)[0])).toBe(true);
  expect(command.body.command_id).toBeTruthy();
});
it("refuses additive tranche monetary drift and quantity overcommit", () => {
  const drift = commerceFixture("Paid"); drift.lines[0].tranches[0].total_minor = "13501";
  expect(() => parseCommerceOrder(drift, scope)).toThrow("commerce_contract_invalid");
  const oversold = commerceFixture("Paid"); oversold.lines[0].tranches.push({ ...oversold.lines[0].tranches[0], id: "ANOTHER" });
  expect(() => parseCommerceOrder(oversold, scope)).toThrow("commerce_contract_invalid");
});
it("retains actual partial invoice allocations and rejects a forged residual", () => {
  const document = commerceFixture("Invoiced");
  document.lines[0].collected_minor = "5000";
  Object.assign(document.lines[0].tranches[0], { collected_minor: "5000", outstanding_minor: "8500", invoice_status: "PartiallyPaid" });
  expect(parseCommerceOrder(document, scope).lines[0].collected_minor).toBe("5000");
  Object.assign(document.lines[0].tranches[0], { outstanding_minor: "8499" });
  expect(() => parseCommerceOrder(document, scope)).toThrow("commerce_contract_invalid");
});
it("preserves collected history but accepts zero residual only with a complete native CR1 credit", () => {
  const document = commerceFixture("Invoiced"); document.lines[0].collected_minor = "5000";
  Object.assign(document.lines[0].tranches[0], { collected_minor: "5000", outstanding_minor: "0", invoice_status: "Cancelled", credited_minor: "13500", refund_due_minor: "5000", credit_memo_id: "CR1-" + "a".repeat(32) });
  expect(parseCommerceOrder(document, scope).lines[0].collected_minor).toBe("5000");
  Object.assign(document.lines[0].tranches[0], { credited_minor: "13499" });
  expect(() => parseCommerceOrder(document, scope)).toThrow();
});
