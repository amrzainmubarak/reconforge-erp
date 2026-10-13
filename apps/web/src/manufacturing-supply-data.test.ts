import { webcrypto } from "node:crypto";
import { beforeEach, expect, it, vi } from "vitest";
import { parseSupplyPlan, scaledSupplyText } from "./manufacturing-supply-data";
import { supplyFixture, supplyScope } from "./manufacturing-supply-test-fixtures";
import originalNativeHandoff from "./fixtures/manufacturing-supply-original-handoff.json";
beforeEach(() => vi.stubGlobal("crypto", webcrypto));
it("verifies the original retained nonowner PostgreSQL full-cycle handoff artifact", async () => {
  const source = await parseSupplyPlan(originalNativeHandoff.source, supplyScope);
  expect(source.source_digest).toBe("83168181ab5117bd761d25e3b9a861d9d63b8f32ec095a7eb281d35620b1785d");
  expect(source.phase).toBe(2); expect(source.stock_claims).toHaveLength(5);
  expect(source.manufacturing_order_id).toBe("ME2-2181CB7D9D52454C873CE198AC999074");
});
it("keeps original engineering gross, actual custody and exact net shortage independently verifiable", async () => {
  const source = await parseSupplyPlan(await supplyFixture(true), supplyScope);
  expect(source.planned_requirements[0].coverage).toMatchObject({ onhand_reserved_scaled: "500", shortage_quantity_scaled: "2500" });
  expect(scaledSupplyText("2500", 3)).toBe("2.500"); expect(scaledSupplyText("9000000000000000000", 6)).toBe("9000000000000.000000");
});
it.each(["scope", "digest", "coverage", "unknown_schema", "unsafe_number"])("refuses a changed original %s", async mutation => {
  const source = await supplyFixture(true);
  if (mutation === "scope") source.workspace_id = "sibling";
  if (mutation === "digest") source.source_digest = "0".repeat(64);
  if (mutation === "coverage") source.planned_requirements[0].coverage!.shortage_quantity_scaled = "2499";
  if (mutation === "unknown_schema") source.schema_version = "future-schema";
  if (mutation === "unsafe_number") (source.requirements[0] as unknown as Record<string, unknown>).required_quantity_scaled = Number.MAX_SAFE_INTEGER + 1;
  await expect(parseSupplyPlan(source, supplyScope)).rejects.toThrow("manufacturing_supply_evidence_invalid");
});
