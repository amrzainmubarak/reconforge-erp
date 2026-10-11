import { expect, it } from "vitest";
import { applyManufacturingCompletion, manufacturingCanonical, parseManufacturing } from "./manufacturing-execution-data";
import { manufacturingCompletionFixture, manufacturingFixture } from "./manufacturing-execution-test-fixtures";
const scope = { workspace_id: "work", organization_id: "org", legal_entity_id: "entity" };
it("verifies huge exact original material cost without converting money to JS numbers", async () => {
  const value = await manufacturingFixture(3), parsed = await parseManufacturing(value, scope);
  expect(parsed.issue_plan?.total_cost_minor).toBe("9000000000000000000");
  expect(manufacturingCanonical({ total_cost_minor: "9000000000000000000" })).toBe('{"total_cost_minor":9000000000000000000}');
});
it("advances exact parent counters from posted child ACK and refuses foreign or inconsistent parent evidence", async () => {
  const parent = await parseManufacturing(await manufacturingFixture(3), scope), posted = await parseManufacturing(await manufacturingCompletionFixture(2), scope);
  const terminal = applyManufacturingCompletion(parent, posted);
  expect(terminal).toMatchObject({ phase: 4, disposed_quantity_scaled: "10", released_cost_minor: "9000000000000000000", wip_minor: "0" });
  const historical = await parseManufacturing(await manufacturingCompletionFixture(2, "4", "3600000000000000000", "C"), scope);
  expect(applyManufacturingCompletion(terminal, historical)).toMatchObject({ phase: 4, disposed_quantity_scaled: "10", released_cost_minor: "9000000000000000000" });
  for (const child of [{ ...posted, order_digest: "0".repeat(64) }, { ...posted, wip_after_minor: "1" }]) expect(() => applyManufacturingCompletion(parent, child)).toThrow();
  expect(() => applyManufacturingCompletion(terminal, { ...posted, source_digest: "0".repeat(64) })).toThrow();
  const oldReview = await parseManufacturing(await manufacturingCompletionFixture(1), scope);
  expect(applyManufacturingCompletion(terminal, oldReview).completions?.[0].phase).toBe(2);
});
it("rejects altered original source, issue amount, hierarchy and out-of-range quantity", async () => {
  const value = await manufacturingFixture(3);
  for (const changed of [{ ...value, number: "forged" }, { ...value, issue_plan: { ...value.issue_plan!, total_cost_minor: "8999999999999999999" } }, { ...value, workspace_id: "other" }, { ...value, disposed_quantity_scaled: "11" }]) await expect(parseManufacturing(changed, scope)).rejects.toThrow();
});
it("rejects financial effects on an unposted completion and orphan child populations", async () => {
  const value = await manufacturingFixture(3);
  await expect(parseManufacturing({ ...value, completions: [{ id: "ME1C-" + "B".repeat(32), ...scope, phase: 0, source_digest: "0".repeat(64), preparer_actor_id: "maker", good_quantity_scaled: "1", scrap_quantity_scaled: "0", stage_quantity_scaled: "1", good_cost_minor: "1", scrap_cost_minor: "0", released_cost_minor: "1", receipt_effect: { effect_id: "forged" }, scrap_effect_id: null }] }, scope)).rejects.toThrow();
});
