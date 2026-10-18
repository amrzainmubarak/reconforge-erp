import { expect, it } from "vitest";
import { parsePeoplePlan } from "./people-project-payroll-data";
import { peoplePlanFixture, peopleScope } from "./people-project-payroll-test-fixture";

it("verifies actual SHA proof and exact employee/project conservation", async () => {
  const parsed = await parsePeoplePlan(await peoplePlanFixture(2), peopleScope);
  expect(parsed.amount_minor).toBe("2501"); expect(parsed.posting_effect_id).toBe("native-effect");
});
it.each([0, 1, 3])("verifies unposted phase %s without fabricating effects", async phase => {
  expect((await parsePeoplePlan(await peoplePlanFixture(phase), peopleScope)).phase).toBe(phase);
});
it("refuses changed money, private allocation, native seal or foreign scope", async () => {
  const plan = await peoplePlanFixture(2), mutated = [
    { ...plan, amount_minor: "2502" }, { ...plan, workspace_id: "foreign" }, { ...plan, plan_digest: "0".repeat(64) },
    { ...plan, project_minor: { P1: "1267", P2: "1234" } }, { ...plan, posted_actor_id: "maker" },
    { ...plan, native_effect: { ...(plan.native_effect as object), entry_id: "foreign" } },
    { ...plan, native_effect: { ...(plan.native_effect as object), validation_digest: "0".repeat(64) } },
    { ...plan, phase: 0, status: "Prepared" }, { ...plan, native_effect: null },
  ];
  for (const value of mutated) await expect(parsePeoplePlan(value, peopleScope)).rejects.toThrow();
});
it("does not admit a retained digest without a complete private source", async () => {
  await expect(parsePeoplePlan({ ...await peoplePlanFixture(0), private: null }, peopleScope)).rejects.toThrow();
});
