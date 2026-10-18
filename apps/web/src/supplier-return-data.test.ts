/// <reference types="node" />
import { webcrypto } from "node:crypto";
import { afterEach, expect, it, vi } from "vitest";
import { parseSupplierReturn, supplierReturnCommand, supplierReturnPage, supplierReturnRoot } from "./supplier-return-data";
import { supplierReturn } from "./test-fixtures/supplier-return";
import type { ProcurementScope } from "./procurement-data";
import type { BrowserAdminSession } from "./types";
const scope = { workspace_id: "work", organization_id: "org", legal_entity_id: "entity", currency_code: "USD" } as ProcurementScope;
const session = { tenantId: "tenant", csrfToken: "csrf" } as BrowserAdminSession;
afterEach(() => vi.unstubAllGlobals());
it("keeps original large financial integers exact and rejects display values detached from canonical source", () => {
  const plan = supplierReturn(); expect(parseSupplierReturn(plan, scope, "order").credit_minor).toBe("9007199254740993");
  for (const bad of [{ ...plan, credit_minor: 9007199254740993 }, { ...plan, credit_minor: "9007199254740992", charge_expense_minor: "707" }, { ...plan, legal_entity_id: "foreign" }, { ...plan, phase: 1, status: "Reviewed", reviewer_actor_id: "maker" }]) expect(() => parseSupplierReturn(bad, scope, "order")).toThrow("contract_invalid");
});
it("requires whole original native effects and retained distinct cancellation evidence", () => {
  expect(parseSupplierReturn(supplierReturn(2), scope, "order").posting_effect_ids).toHaveLength(3);
  expect(parseSupplierReturn(supplierReturn(3), scope, "order").evidence.cancel_audit_event_id).toBe("cancel-audit");
  for (const bad of [{ ...supplierReturn(2), posting_effect_ids: ["one"] }, { ...supplierReturn(3), cancelled_actor_id: "maker" }, { ...supplierReturn(3), posting_effect_ids: ["illegal-post"] }]) expect(() => parseSupplierReturn(bad, scope, "order")).toThrow("contract_invalid");
});
it("verifies canonical source digest and refuses a malformed successful response for exact replay", async () => {
  vi.stubGlobal("crypto", webcrypto);
  vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce({ ok: true, json: async () => ({ records: [supplierReturn()] }) }).mockResolvedValueOnce({ ok: true, json: async () => ({ records: [{ ...supplierReturn(), canonical_plan_json: supplierReturn().canonical_plan_json.replace("9007199254740993", "9007199254740992") }] }) }));
  expect((await supplierReturnPage(session, scope, "order"))[0].credit_minor).toBe("9007199254740993");
  await expect(supplierReturnPage(session, scope, "order")).rejects.toThrow("contract_invalid");
});
it("binds retained command acknowledgement to exact original receipt and invoice", async () => {
  vi.stubGlobal("crypto", webcrypto);
  const plan = supplierReturn();
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => plan }));
  const command = { path: supplierReturnRoot + "/plans", body: { command_id: "retained", order_id: "order", receipt_id: "receipt", invoice_id: "invoice", number: plan.number, period_id: "period", posting_date: plan.posting_date } };
  expect((await supplierReturnCommand(session, scope, "order", command)).id).toBe(plan.id);
  await expect(supplierReturnCommand(session, scope, "order", { ...command, body: { ...command.body, receipt_id: "different" } })).rejects.toThrow("contract_invalid");
});
