import { afterEach, describe, expect, it, vi } from "vitest";
import { cashflowSha } from "./intercompany-cashflow-data";
import { canonicalIc } from "./intercompany-operations-data";
import { downloadGroupOriginal, groupSelection, verifyGroupView } from "./group-diagnostic-data";
import { groupFixture } from "./group-diagnostic-test-fixture";

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });
describe("selected original group bridge and raw custody", () => {
  it("binds two actual original source reports and separate translated/native adjustment Cash", async () => {
    const f = await groupFixture(); expect(await verifyGroupView(f.view, f.originals, f.scope, f.tenant)).toBe(f.view);
    const cash = f.view.diagnostic.trial_balance_bridge.find(row => row.role === "cash")!;
    expect([cash.translated_minor, cash.native_adjustment_minor, cash.combined_minor]).toEqual(["202", "0", "202"]);
    expect(groupSelection([...f.originals].reverse()).pins).toEqual(f.originals.map(row => row.pin));
  });
  it.each(["tenant", "scope", "pins", "source", "effect", "cash_compensation", "bridge_compensation", "period_extra", "period_omit", "period_scope", "close_claim", "money_type", "source_evidence"])("refuses rehashed %s display", async attack => {
    const f = await groupFixture(), value = structuredClone(f.view), v = value.diagnostic;
    if (attack === "tenant") v.qualified_scope.tenant_id = "foreign";
    if (attack === "scope") v.qualified_scope.workspace_id = "foreign";
    if (attack === "pins") v.selection.pins[0].report_digest = "0".repeat(64);
    if (attack === "source") v.source_members[0].source_id = v.source_members[1].source_id;
    if (attack === "effect") v.source_members[0].source_effect_ids.push("uncovered");
    if (attack === "source_evidence") v.source_members[0].source_evidence_digest = "0".repeat(64);
    if (attack === "cash_compensation") { v.cash_equation.operating_net_minor = "1"; v.cash_equation.fx_on_cash_minor = "201"; }
    if (attack === "bridge_compensation") { const rows = Object.fromEntries(v.trial_balance_bridge.map(row => [row.role, row])); rows.cash.translated_minor = "203"; rows.cash.native_adjustment_minor = "-1"; rows.cta.translated_minor = "581"; rows.cta.native_adjustment_minor = "1"; }
    if (attack === "period_extra") v.native_period_observations.push({ ...v.native_period_observations[0], id: "unrelated" });
    if (attack === "period_omit") v.native_period_observations = [];
    if (attack === "period_scope") v.native_period_observations[0].application_workspace_id = "foreign";
    if (attack === "close_claim") (v as unknown as Record<string, unknown>).formal_close_workflow_assessed = true;
    if (attack === "money_type") (v.trial_balance_bridge[0] as unknown as Record<string, unknown>).combined_minor = 202;
    v.diagnostic_digest = await cashflowSha(new TextEncoder().encode(canonicalIc(Object.fromEntries(Object.entries(v).filter(([key]) => key !== "diagnostic_digest")))));
    await expect(verifyGroupView(value, f.originals, f.scope, f.tenant)).rejects.toThrow();
  });
  it("refuses duplicate selected native source and drifted frozen opening pins", async () => {
    const f = await groupFixture(); expect(() => groupSelection([f.originals[0], f.originals[0]])).toThrow();
    const changed = structuredClone(f.originals); changed[0].pin.opening.origin_plan_id = changed[0].pin.elimination_plan_id;
    expect(() => groupSelection(changed)).toThrow();
  });
  it("preserves exact native bytes without JSON parsing or BigInt reserialization", async () => {
    const f = await groupFixture();
    vi.stubGlobal("fetch", vi.fn(async () => new Response(f.bytes, { headers: { "Content-Type": "application/json", "Content-Length": String(f.bytes.length), "X-ReconForge-Evidence-SHA256": f.view.evidence_sha256 } })));
    const blob = await downloadGroupOriginal({ tenantId: f.tenant, csrfToken: "", expiresAt: "2099-01-01" }, f.scope, f.originals, f.view);
    expect(Array.from(new Uint8Array(await blob.arrayBuffer()))).toEqual(Array.from(f.bytes));
  });
  it.each(["header", "length", "bytes", "oversized", "authority"])("refuses %s original export drift", async attack => {
    const f = await groupFixture(), bytes = new Uint8Array(f.bytes); if (attack === "bytes") bytes[0] ^= 1;
    vi.stubGlobal("fetch", vi.fn(async () => attack === "authority" ? new Response("{}", { status: 403 }) : new Response(attack === "oversized" ? new Uint8Array(bytes.length + 1) : bytes, { headers: { "Content-Type": "application/json", "Content-Length": attack === "length" ? "1" : String(bytes.length), "X-ReconForge-Evidence-SHA256": attack === "header" ? "0".repeat(64) : f.view.evidence_sha256 } })));
    await expect(downloadGroupOriginal({ tenantId: f.tenant, csrfToken: "", expiresAt: "2099-01-01" }, f.scope, f.originals, f.view)).rejects.toThrow();
  });
});
