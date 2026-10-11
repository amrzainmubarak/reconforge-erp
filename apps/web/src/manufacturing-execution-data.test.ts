import { expect, it } from "vitest";
import { manufacturingCanonical, parseManufacturing } from "./manufacturing-execution-data";
import { manufacturingFixture } from "./manufacturing-execution-test-fixtures";
const scope = { workspace_id: "work", organization_id: "org", legal_entity_id: "entity" };
it("verifies huge exact original material cost without converting money to JS numbers", async () => {
  const value = await manufacturingFixture(3), parsed = await parseManufacturing(value, scope);
  expect(parsed.issue_plan?.total_cost_minor).toBe("9000000000000000000");
  expect(manufacturingCanonical({ total_cost_minor: "9000000000000000000" })).toBe('{"total_cost_minor":9000000000000000000}');
});
it("rejects altered original source, issue amount, hierarchy and out-of-range quantity", async () => {
  const value = await manufacturingFixture(3);
  for (const changed of [{ ...value, number: "forged" }, { ...value, issue_plan: { ...value.issue_plan!, total_cost_minor: "8999999999999999999" } }, { ...value, workspace_id: "other" }, { ...value, disposed_quantity_scaled: "11" }]) await expect(parseManufacturing(changed, scope)).rejects.toThrow();
});
it("rejects financial effects on an unposted completion and orphan child populations", async () => {
  const value = await manufacturingFixture(3);
  await expect(parseManufacturing({ ...value, completions: [{ id: "ME1C-" + "B".repeat(32), ...scope, phase: 0, source_digest: "0".repeat(64), preparer_actor_id: "maker", good_quantity_scaled: "1", scrap_quantity_scaled: "0", stage_quantity_scaled: "1", good_cost_minor: "1", scrap_cost_minor: "0", released_cost_minor: "1", receipt_effect: { effect_id: "forged" }, scrap_effect_id: null }] }, scope)).rejects.toThrow();
});
