import { afterEach, describe, expect, it, vi } from "vitest";
import { canonicalIc } from "./intercompany-operations-data";
import { cashflowMaximumBytes, cashflowQuery, cashflowSha, downloadCashflowOriginal, verifyCashflowView } from "./intercompany-cashflow-data";
import { cashflowFixture } from "./intercompany-cashflow-test-fixture";

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });
describe("source cashflow exact display and original byte custody", () => {
  it("verifies native membership, original currencies, known opening and the source cash equation", async () => {
    const f = await cashflowFixture(); expect(await verifyCashflowView(f.view, f.detail, f.report, f.tenant)).toBe(f.view);
    expect(f.view.cashflow.operating_net_minor).toBe("0"); expect(f.view.cashflow.fx_on_cash_minor).toBe("101");
    const query = new URLSearchParams(cashflowQuery(f.detail)); expect(query.get("seller_opening_minor")).toBe("0"); expect(query.get("opening_basis")).toBe("complete-native-source-origin-membership");
  });
  it.each(["tenant", "scope", "source", "origin", "report", "elimination", "policy", "unknown_opening", "effect", "native_amount", "rate", "movement", "equation", "numeric_money", "export_bound"])("refuses rehashed %s admission", async attack => {
    const f = await cashflowFixture(), value = structuredClone(f.view), flow = value.cashflow;
    if (attack === "tenant") value.qualified_scope.tenant_id = "foreign";
    if (attack === "scope") value.qualified_scope.legal_entity_ids.buyer = "foreign";
    if (attack === "source") flow.source_id = "IC2S-" + "a".repeat(32);
    if (attack === "origin") flow.opening_origin_plan_id = flow.elimination_plan_id;
    if (attack === "report") flow.report_digest = "0".repeat(64);
    if (attack === "elimination") flow.elimination_plan_digest = "0".repeat(64);
    if (attack === "policy") flow.reporting_policy.currency_precision = 0;
    if (attack === "unknown_opening") flow.opening_minor = "1";
    if (attack === "effect") flow.source_effect_ids.push("uncovered");
    if (attack === "native_amount") flow.books.seller.movements[0].native_minor = "3901";
    if (attack === "rate") flow.books.seller.movements[0].historical_rate.source = "uncaptured";
    if (attack === "movement") flow.books.seller.movements.push(flow.books.seller.movements[0]);
    if (attack === "equation") flow.operating_inflow_minor = "1";
    if (attack === "numeric_money") (flow.books.seller as unknown as Record<string, unknown>).native_cash_minor = 3900;
    if (attack === "export_bound") value.evidence_bytes = cashflowMaximumBytes + 1;
    flow.cashflow_digest = await cashflowSha(new TextEncoder().encode(canonicalIc(Object.fromEntries(Object.entries(flow).filter(([key]) => key !== "cashflow_digest")))));
    await expect(verifyCashflowView(value, f.detail, f.report, f.tenant)).rejects.toThrow();
  });
  it("preserves original 64-bit integer byte spelling without parsing or reserializing", async () => {
    const f = await cashflowFixture(), bytes = new TextEncoder().encode('{"native_minor":4500000000000000000,"source":"synthetic byte custody probe"}');
    const expected = { ...f.view, evidence_sha256: await cashflowSha(bytes), evidence_bytes: bytes.length };
    vi.stubGlobal("fetch", vi.fn(async () => new Response(bytes, { headers: { "Content-Type": "application/json", "Content-Length": String(bytes.length), "X-ReconForge-Evidence-SHA256": expected.evidence_sha256 } })));
    const blob = await downloadCashflowOriginal({ tenantId: f.tenant, csrfToken: "", expiresAt: "2099-01-01" }, f.scope, f.detail, expected);
    expect(Array.from(new Uint8Array(await blob.arrayBuffer()))).toEqual(Array.from(bytes));
  });
  it.each(["header", "length", "bytes", "oversized_stream", "tenant"])("refuses original %s drift without a download", async attack => {
    const f = await cashflowFixture(), expected = structuredClone(f.view), bytes = new Uint8Array(f.bytes);
    if (attack === "tenant") expected.qualified_scope.tenant_id = "foreign";
    if (attack === "bytes") bytes[0] ^= 1;
    const body = attack === "oversized_stream" ? new Uint8Array(bytes.length + 1) : bytes;
    vi.stubGlobal("fetch", vi.fn(async () => new Response(body, { headers: { "Content-Type": "application/json", "Content-Length": attack === "length" ? "1" : String(bytes.length), "X-ReconForge-Evidence-SHA256": attack === "header" ? "0".repeat(64) : expected.evidence_sha256 } })));
    await expect(downloadCashflowOriginal({ tenantId: f.tenant, csrfToken: "", expiresAt: "2099-01-01" }, f.scope, f.detail, expected)).rejects.toThrow();
  });
});
