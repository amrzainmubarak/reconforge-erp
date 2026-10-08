import { afterEach, describe, expect, it, vi } from "vitest";
import { installmentCommand, parseInstallmentPlan, parsePartialDetail, partialCommand, partialRoot, scaledQuantity } from "./procurement-partial-data";
import type { ProcurementScope } from "./procurement-data";
import { prepareScopedCommand } from "./scoped-command";
import type { BrowserAdminSession } from "./types";

const scope: ProcurementScope = { workspace_id: "work", organization_id: "org", legal_entity_id: "entity", organization_code: "ORG", entity_code: "ENTITY", organization_name: "Organization", entity_name: "Entity", currency_code: "USD" };
const session = { tenantId: "tenant", csrfToken: "test-csrf" } as BrowserAdminSession;
function draft() { return { order: { id: "partial-order", number: "ORDER-1", purchase_order_id: "native-po", row_version: 1, stage: "Draft", total_minor: "12000", workspace_id: "work", organization_id: "org", legal_entity_id: "entity", request: { number: "ORDER-1", quantity: "10", unit_price_minor: "1200", currency_code: "USD", organization_code: "ORG", entity_code: "ENTITY" } }, receipts: [], invoices: [], totals: { ordered_quantity: "10", reserved_receipt_quantity: "0", received_quantity: "0", invoiced_quantity: "0", received_minor: "0", accrued_minor: "0", paid_minor: "0", outstanding_minor: "0" } }; }
function plan() { return { id: "FI1-plan", source_kind: "APPayment", source_id: "invoice", workspace_id: "work", organization_id: "org", legal_entity_id: "entity", entry_id: "native-entry", posting_date: "2026-10-03", period_id: "period", currency_code: "USD", currency_precision: 2, status: "Prepared", phase: 0, plan_digest: "a".repeat(64), validation_digest: "b".repeat(64), preparer_actor_id: "maker", reviewer_actor_id: null, posting_effect_id: null, payment_link_id: null, amount_minor: "1000", allocated_before_minor: "0", invoice_version: 5 }; }
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
});
