import { partialAllocationPolicy, type PartialReturnBalanceV2, type PartialReturnPlanV2 } from "./customer-partial-returns-data";
import { partialBalanceFixture, partialPlanFixture } from "./customer-partial-returns-test-fixtures";

export function remainderPlanFixture(credit = "1000", cost = "334", phase: 0 | 1 | 2 | 3 = 1, operation: PartialReturnPlanV2["operation"] = "Return"): PartialReturnPlanV2 {
  const original = partialPlanFixture(phase, operation), merchandise = operation === "Return" || operation === "ReverseReturn";
  return { ...original, schema_version: "customer-partial-return-v2", allocation_policy: partialAllocationPolicy,
    ...(merchandise ? { quantity_scaled: "1", credit_minor: credit, cogs_restored_minor: cost, receivable_released_minor: credit,
      refund_entitlement_delta_minor: "0", amount_minor: (BigInt(credit) + BigInt(cost)).toString(),
      entries: original.entries.filter((_entry, index) => [credit, cost][index] !== "0") } : {}) };
}
export function remainderBalanceFixture(overrides: Partial<PartialReturnBalanceV2> = {}): PartialReturnBalanceV2 {
  return { ...partialBalanceFixture(), schema_version: "customer-partial-return-balance-v2", allocation_policy: partialAllocationPolicy,
    history_version: 0, gross_minor: "3000", collected_minor: "0", credited_minor: "0", returned_quantity_scaled: "0",
    remaining_quantity_scaled: "3", outstanding_minor: "3000", ...overrides };
}
