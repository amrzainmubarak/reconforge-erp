import { describe, expect, it } from "vitest";

import { approveTestedRule, diffRuleSpecs, parseRuleSpec, runRuleTests } from "./ruleStudio";

const rule = (overrides: Record<string, unknown> = {}) => JSON.stringify({
  schema_version: 1,
  reconciliation_id: "cash_daily",
  strategy: "tolerance",
  amount_tolerance: "0.01",
  test_cases: [
    { id: "within", left_amount: "9007199254740993.00", right_amount: "9007199254740993.01", expected_match: true },
    { id: "outside", left_amount: "1.00", right_amount: "1.02", expected_match: false },
  ],
  ...overrides,
});

describe("Rule Studio governance", () => {
  it("runs exact-decimal golden cases beyond binary-float integer precision", async () => {
    const result = await runRuleTests(rule());
    expect(result.passed).toBe(true);
    expect(result.passedCount).toBe(2);
    expect(result.digest).toMatch(/^[a-f0-9]{64}$/);
  });

  it("rejects unsafe or ambiguous rule shapes", () => {
    expect(() => parseRuleSpec(rule({ amount_tolerance: 0.01 }))).toThrow("exact decimal text");
    expect(() => parseRuleSpec(rule({ amount_tolerance: "1e-2" }))).toThrow("exact decimal text");
    expect(() => parseRuleSpec(rule({ execute: "alert(1)" }))).toThrow("unsupported fields");
    expect(() => parseRuleSpec(rule({ test_cases: [] }))).toThrow("1-100");
  });

  it("produces deterministic structural paths", () => {
    const changed = rule({ amount_tolerance: "0.02", strategy: "exact" });
    expect(diffRuleSpecs(rule(), changed)).toEqual(["amount_tolerance", "strategy"]);
  });

  it("requires passed same-digest tests, a different reviewer, and a reason", async () => {
    const result = await runRuleTests(rule());
    expect(() => approveTestedRule({ version: 1, author: "Preparer", reviewer: " preparer ", reason: "reviewed", currentDigest: result.digest, testResult: result })).toThrow("own rule");
    expect(() => approveTestedRule({ version: 1, author: "preparer", reviewer: "reviewer", reason: "", currentDigest: result.digest, testResult: result })).toThrow("reason");
    expect(() => approveTestedRule({ version: 1, author: "preparer", reviewer: "reviewer", reason: "reviewed", currentDigest: "0".repeat(64), testResult: result })).toThrow("does not match");
    expect(approveTestedRule({ version: 1, author: "preparer", reviewer: "reviewer", reason: "evidence reviewed", currentDigest: result.digest, testResult: result })).toMatchObject({ status: "approved", version: 1, reviewer: "reviewer" });
  });
});
