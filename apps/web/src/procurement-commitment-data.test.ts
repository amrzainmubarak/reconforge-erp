import { expect, it } from "vitest";
import { newestCommitment, parseProcurementCommitment, sameProcurementQuantity, type ProcurementCommitment } from "./procurement-commitment-data";
import type { ProcurementScope } from "./procurement-data";
import { commitment } from "./test-fixtures/procurement-commitment";

const scope = { workspace_id: "work", organization_id: "org", legal_entity_id: "entity", currency_code: "USD" } as ProcurementScope;
it("compares native mixed-scale quantity projections with exact integer arithmetic", () => {
  expect(sameProcurementQuantity("2.50", "2.5")).toBe(true);
  expect(sameProcurementQuantity("9000000000000000.000001", "9000000000000000.000002")).toBe(false);
  expect(() => sameProcurementQuantity("NaN", "0")).toThrow();
});
it("conserves large exact appropriation money without number arithmetic", () => {
  const row = { ...commitment(), original_minor: "9000000000000000000", reserved_minor: "1", remaining_minor: "1", consumed_minor: "8999999999999999999" };
  expect(parseProcurementCommitment(row, scope, "order")).toEqual(row);
  expect(() => parseProcurementCommitment({ ...row, consumed_minor: "8999999999999999998" }, scope, "order")).toThrow();
});
it("rejects wrong source and canonical scope, float amounts and terminal conservation gaps", () => {
  for (const row of [{ ...commitment(), order_id: "foreign" }, { ...commitment(), legal_entity_id: "foreign" },
    { ...commitment(), original_minor: 17000 }, { ...commitment(), status: "Released" }, { ...commitment(), budget_version: true }]) {
    expect(() => parseProcurementCommitment(row, scope, "order")).toThrow();
  }
});
it("preserves terminal release against delayed historical consumption acknowledgements", () => {
  const released = { ...commitment(), budget_version: 6, status: "Released" as const, remaining_minor: "0", reserved_minor: "0", consumed_minor: "7400", released_minor: "9600" };
  expect(newestCommitment(released, { ...commitment(), budget_version: 5, consumed_minor: "7400", reserved_minor: "9600", remaining_minor: "9600" })).toBe(released);
});
it("accepts equivalent retained evidence irrespective of JSON property ordering", () => {
  const original = commitment();
  const reordered = Object.fromEntries(Object.entries(original).reverse()) as unknown as ProcurementCommitment;
  expect(newestCommitment(original, reordered)).toEqual(original);
  expect(() => newestCommitment(original, { ...reordered, evidence: { ...original.evidence, request_digest: "b".repeat(64) } })).toThrow();
});
