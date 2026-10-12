import { describe, expect, it } from "vitest";
import fixture from "./fixed-asset-evidence-fixture.json";
import { parseAssetPlan, verifyAssetEvidence } from "./fixed-assets-data";

const scope = { workspace_id: "work", organization_id: "org", legal_entity_id: "entity" };
const expected = parseAssetPlan(fixture.plan, scope);
describe("independent asset evidence verification", () => {
  it("checks Python-generated SHA-256 seals without rounding JS-unsafe minor units", async () => {
    const proof = await verifyAssetEvidence(fixture, scope, expected);
    expect(proof.totals.debit_minor).toBe("9007199254740993");
    expect(proof.native_effect?.posted_actor_id).toBe("poster");
  });
  it("rejects altered source, original operation, native amounts and false canonical seals", async () => {
    for (const corrupt of [
      { ...fixture, asset_definition: { ...fixture.asset_definition, cost_minor: "9007199254740992" } },
      { ...fixture, canonical_plan_json: fixture.canonical_plan_json.replace("Synthetic asset", "Another asset") },
      { ...fixture, canonical_snapshot_json: fixture.canonical_snapshot_json.replace("9007199254740993", "9007199254740992") },
      { ...fixture, totals: { debit_minor: "9007199254740992", credit_minor: "9007199254740992" } },
    ]) await expect(verifyAssetEvidence(corrupt, scope, expected)).rejects.toThrow("fixed_asset_contract_invalid");
  });
  it("rejects a substituted effect, self posting, reused evidence or a foreign entity", async () => {
    for (const corrupt of [
      { ...fixture, native_effect: { ...fixture.native_effect, id: "foreign-effect" } },
      { ...fixture, native_effect: { ...fixture.native_effect, posted_actor_id: "checker" } },
      { ...fixture, phases: fixture.phases.map((row, index) => index === 1 ? { ...row, audit_event_id: fixture.phases[0].audit_event_id } : row) },
      { ...fixture, plan: { ...fixture.plan, legal_entity_id: "foreign" } },
    ]) await expect(verifyAssetEvidence(corrupt, scope, expected)).rejects.toThrow("fixed_asset_contract_invalid");
  });
  it("rejects current phase drift and a response for a different selected operation", async () => {
    await expect(verifyAssetEvidence(fixture, scope, { ...expected, phase: 1 })).rejects.toThrow();
    await expect(verifyAssetEvidence(fixture, scope, { ...expected, id: "another-plan" })).rejects.toThrow();
  });
});
