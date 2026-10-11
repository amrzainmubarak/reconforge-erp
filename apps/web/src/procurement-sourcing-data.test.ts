import { createHash } from "node:crypto";
import { describe, expect, it } from "vitest";
import { parseSourcingAcknowledgement, parseSourcingDetail, parseSourcingHead, sourcingLineMinor, sourcingRoot } from "./procurement-sourcing-data";
import type { ProcurementScope } from "./procurement-data";
import { prepareScopedCommand } from "./scoped-command";
const scope = { workspace_id: "work", organization_id: "org", legal_entity_id: "entity", organization_code: "ORG", entity_code: "ENTITY", currency_code: "USD" } as ProcurementScope;
function canonical(v: unknown, key = ""): string {
  if (typeof v === "string" && key.endsWith("_minor")) return v;
  if (Array.isArray(v)) return "[" + v.map(row => canonical(row, key === "unit_prices_minor" ? "unit_price_minor" : "")).join(",") + "]";
  if (v && typeof v === "object") return "{" + Object.entries(v).sort(([a], [b]) => a < b ? -1 : 1).map(([k, row]) => JSON.stringify(k) + ":" + canonical(row, k)).join(",") + "}";
  return JSON.stringify(v);
}
const digest = (raw: string) => createHash("sha256").update(raw, "utf8").digest("hex");
function fixture() {
  const demand = { number: "SRC5-FIXTURE", supplier_code: "SUP", currency_code: "USD", posting_date: "2026-10-12", period_id: "period", journal_code: "STOCK", ap_account_code: "AP", cash_account_code: "CASH", workspace: "work", organization_code: "ORG", entity_code: "ENTITY",
    lines: [{ item_code: "ITEM", quantity: "10", unit_price_minor: "1200", location_code: "MAIN/STOCK", policy_code: "FIFO" }] };
  const source = { schema_version: "procurement-sourcing-v1", creator_actor_id: "maker", ceiling_minor: "12000", currency_precision: 2, scope: { workspace_id: "work", organization_id: "org", legal_entity_id: "entity" },
    request: { budget_id: "budget", reason: "Original exact requirement", order: demand, requirements: [null] }, demand_masters: [{ item_id: "item", uom_id: "unit", location_id: "location", policy_id: "policy", quantity_precision: 0 }], manufacturing_requirements: [null] };
  const raw = canonical(source), seal = digest(raw);
  const offer = { schema_version: "supplier-quotation-v1", requisition_id: "source", source_digest: seal, supplier_id: "supplier", registrar_actor_id: "maker", total_minor: "9000",
    order: { ...demand, number: "BPC1-SRC5-FIXTURE", lines: [{ ...demand.lines[0], unit_price_minor: "900" }] },
    quotation: { supplier_code: "SUP", unit_prices_minor: ["900"], valid_until: "2026-10-31", reason: "Original exact supplier offer" } };
  const quoteRaw = canonical(offer);
  return { head: { schema_version: "procurement-sourcing-v1", id: "source", number: demand.number, row_version: 4, status: "SelectionReviewed", workspace_id: "work", organization_id: "org", legal_entity_id: "entity", currency_code: "USD", ceiling_minor: "12000", budget_id: "budget", source_digest: seal,
    creator_actor_id: "maker", rfq_approver_actor_id: "checker", selection_reviewer_actor_id: "checker", award_actor_id: null, selected_quote_id: "quote", order_id: null, evidence: { audit_event_id: "audit", outbox_event_id: "outbox", request_digest: "a".repeat(64) } },
    source, canonical_source_json: raw, quotations: [{ id: "quote", quote_digest: digest(quoteRaw), created_version: 3, payload: offer, canonical_quote_json: quoteRaw }] };
}
describe("actual retained source financial and evidence contract", () => {
  it("verifies both independent Node SHA-256 seals and exact original demand/offer conservation", async () => {
    const value = fixture(); const verified = await parseSourcingDetail(value, scope, "source");
    expect(verified.source.ceiling_minor).toBe("12000"); expect(verified.quotations[0].payload.total_minor).toBe("9000");
  });
  it("retains 19-digit money without Number or ambient decimal rounding", () => {
    expect(sourcingLineMinor("1", "8999999999999999999")).toBe(8999999999999999999n);
    expect(sourcingLineMinor("2.50", "2000")).toBe(5000n);
    for (const [q, p] of [["0.01", "1"], ["NaN", "1"], ["Infinity", "1"], ["0", "1"], ["1", "9000000000000000001"]]) expect(() => sourcingLineMinor(q, p)).toThrow();
  });
  it.each(["currency_code", "workspace_id", "legal_entity_id"])("rejects forged current %s", field => {
    expect(() => parseSourcingHead({ ...fixture().head, [field]: "foreign" }, scope)).toThrow();
  });
  it("awaits the real asynchronous digest and rejects altered source or quotation seals", async () => {
    const value = fixture();
    await expect(parseSourcingDetail({ ...value, canonical_source_json: value.canonical_source_json + " " }, scope, "source")).rejects.toThrow();
    await expect(parseSourcingDetail({ ...value, head: { ...value.head, source_digest: "b".repeat(64) } }, scope, "source")).rejects.toThrow();
    await expect(parseSourcingDetail({ ...value, quotations: [{ ...value.quotations[0], quote_digest: "b".repeat(64) }] }, scope, "source")).rejects.toThrow();
  });
  it("rejects copied line membership and fractional/native monetary projections", async () => {
    const value = fixture();
    value.quotations[0].payload.order.lines[0].quantity = "9";
    await expect(parseSourcingDetail(value, scope, "source")).rejects.toThrow();
    const changed = fixture(); changed.source.request.order.lines[0].unit_price_minor = "1200.0";
    await expect(parseSourcingDetail(changed, scope, "source")).rejects.toThrow();
  });
  it("refuses duplicate retained candidate identity and same-human independent review", async () => {
    const value = fixture();
    await expect(parseSourcingDetail({ ...value, quotations: [...value.quotations, value.quotations[0]] }, scope, "source")).rejects.toThrow();
    await expect(parseSourcingDetail({ ...value, head: { ...value.head, selection_reviewer_actor_id: "maker" } }, scope, "source")).rejects.toThrow();
  });
  it("binds lost-response acknowledgments to exact original route and source version", () => {
    const value = fixture(); const command = prepareScopedCommand(sourcingRoot + "/source/review-selection", { expected_version: 3, reason: "Review" });
    expect(parseSourcingAcknowledgement(value.head, scope, command)).toEqual(value.head);
    expect(() => parseSourcingAcknowledgement({ ...value.head, row_version: 5 }, scope, command)).toThrow();
    expect(() => parseSourcingAcknowledgement({ ...value.head, id: "foreign" }, scope, command)).toThrow();
  });
});

