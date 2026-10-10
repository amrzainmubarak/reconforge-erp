import { describe, expect, it } from "vitest";
import fixture from "./operational-fx-tax-fixture.json";
import { mergeFxPlan, parseFxDetail, parseFxPlan, parseFxSource, verifyFxEvidence } from "./operational-fx-tax-data";

const scope = { workspace_id: "work", organization_id: "org", legal_entity_id: "entity" };
describe("native foreign and functional currency response closure", () => {
  it("retains exact currencies, taxes and financial turnover", () => {
    const source = parseFxSource(fixture.source, scope), plan = parseFxPlan(fixture.plan, scope);
    expect(source.foreign_gross_minor).toBe("11401"); expect(source.functional_gross_minor).toBe("14251");
    expect(source.tax_components[0].version).toBe("2026-v1"); expect(plan.amount_minor).toBe("14251");
  });
  it.each(["foreign_gross_minor", "foreign_net_minor", "functional_gross_minor"])("rejects numerical or decimal %s", field => {
    expect(() => parseFxSource({ ...fixture.source, [field]: 11401 }, scope)).toThrow();
    expect(() => parseFxSource({ ...fixture.source, [field]: "114.01" }, scope)).toThrow();
  });
  it("rejects cross-scope source and plan or inconsistent status and journal", () => {
    expect(() => parseFxSource({ ...fixture.source, legal_entity_id: "foreign" }, scope)).toThrow();
    expect(() => parseFxPlan({ ...fixture.plan, phase: 0 }, scope)).toThrow();
    expect(() => parseFxPlan({ ...fixture.plan, snapshot: { ...fixture.plan.snapshot, entry: { ...fixture.plan.snapshot.entry, currency_code: "EUR" } } }, scope)).toThrow();
  });
  it("rejects unbalanced lines and a forged residual while allowing duplicate tax liability account lines", () => {
    expect(() => parseFxPlan({ ...fixture.plan, snapshot: { ...fixture.plan.snapshot, lines: fixture.plan.snapshot.lines.map((row, index) => index === 0 ? { ...row, debit_minor: "1" } : row) } }, scope)).toThrow();
    expect(() => parseFxDetail({ ...fixture.source, foreign_outstanding_minor: "1", foreign_paid_minor: "0", functional_outstanding_minor: "14251", historical_released_minor: "0", plans: [fixture.plan] }, scope)).toThrow();
    const rows = [fixture.plan.snapshot.lines[0], fixture.plan.snapshot.lines[1], { ...fixture.plan.snapshot.lines[2], credit_minor: "875" }, { ...fixture.plan.snapshot.lines[2], line_number: 4, credit_minor: "875" }];
    expect(parseFxPlan({ ...fixture.plan, snapshot: { ...fixture.plan.snapshot, lines: rows } }, scope).snapshot.lines).toHaveLength(4);
  });
  it("does not regress a newer posted GET when a historical review acknowledgement arrives", () => {
    const posted = parseFxPlan(fixture.plan, scope);
    const reviewed = parseFxPlan({ ...fixture.plan, phase: 1, status: "Reviewed", posting_effect_id: null }, scope);
    expect(mergeFxPlan(posted, reviewed)).toBe(posted); expect(mergeFxPlan(reviewed, posted)).toBe(posted);
  });
  it("verifies all three canonical hashes and exact native audit provenance", async () => {
    const result = await verifyFxEvidence(fixture, scope, parseFxPlan(fixture.plan, scope));
    expect(result.phases.map(row => row.actor_id)).toEqual(["maker", "checker", "poster", "poster"]);
    expect(result.native_effect?.id).toBe("effect-synthetic");
  });
  it.each(["canonical_source_json", "canonical_plan_json", "canonical_snapshot_json"])("rejects tampered %s", async field => {
    await expect(verifyFxEvidence({ ...fixture, [field]: "{}" }, scope, parseFxPlan(fixture.plan, scope))).rejects.toThrow();
  });
  it("rejects native seal mismatch or reused audit references", async () => {
    await expect(verifyFxEvidence({ ...fixture, native_effect: { ...fixture.native_effect, posted_actor_id: "maker" } }, scope, parseFxPlan(fixture.plan, scope))).rejects.toThrow();
    await expect(verifyFxEvidence({ ...fixture, phases: fixture.phases.map((row, index) => index === 3 ? { ...row, audit_event_id: "audit-2" } : row) }, scope, parseFxPlan(fixture.plan, scope))).rejects.toThrow();
  });
});
