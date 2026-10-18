import { expect, it } from "vitest";
import { parseReturnPlan, parseRefundBalance } from "./customer-returns-data";
import { returnFixture, returnScope } from "./customer-returns-test-fixtures";
it("verifies canonical original-source plan hash and exact amounts beyond JS safe integers", async () => {
  const plan = await parseReturnPlan(returnFixture(2), returnScope);
  expect(plan.credit_minor).toBe("9007199254740993");
  expect(plan.posting_effect_ids).toEqual(["effect-C", "effect-R"]);
});
it("refuses source/hash/money tampering and foreign scope before accepting financial evidence", async () => {
  await expect(parseReturnPlan({ ...returnFixture(), credit_minor: "9007199254740994" }, returnScope)).rejects.toThrow();
  await expect(parseReturnPlan({ ...returnFixture(), amount_minor: 9007199254752993 }, returnScope)).rejects.toThrow();
  await expect(parseReturnPlan({ ...returnFixture(), canonical_plan_json: "{}" }, returnScope)).rejects.toThrow();
  await expect(parseReturnPlan(returnFixture(), { ...returnScope, legal_entity_id: "foreign" })).rejects.toThrow();
});
it("refuses self posting missing native effects and duplicated effect IDs", async () => {
  for (const patch of [{ posted_actor_id: "maker" }, { posting_effect_ids: [] }, { posting_effect_ids: ["same", "same"] }, { evidence: {} }])
    await expect(parseReturnPlan({ ...returnFixture(2), ...patch }, returnScope)).rejects.toThrow();
});
it("refuses unbalanced original inverse lines and forged current refund balance", async () => {
  const bad = returnFixture(); bad.entries[0].snapshot.lines[0].debit_minor = "12001";
  await expect(parseReturnPlan(bad, returnScope)).rejects.toThrow();
  const parent = await parseReturnPlan(returnFixture(2), returnScope);
  expect(() => parseRefundBalance({ return_id: parent.id, plan_digest: parent.plan_digest, credit_minor: parent.credit_minor, refund_entitlement_minor: "0", refunded_minor: "0", refund_due_minor: "1" }, parent)).toThrow();
});
