import { webcrypto } from "node:crypto";
import { afterEach, expect, it, vi } from "vitest";
import { manufacturingV2Canonical, parseManufacturingV2, parseManufacturingV2Page } from "./manufacturing-execution-v2-data";
import { actualManufacturingV2Page, definitionV2, scopeV2 } from "./manufacturing-execution-v2-test-fixtures";
vi.stubGlobal("crypto", webcrypto); afterEach(() => vi.stubGlobal("crypto", webcrypto));
it("verifies actual original full expense-backed inspected source and exact native monetary strings", async () => {
  const page = await parseManufacturingV2Page(actualManufacturingV2Page(), scopeV2);
  expect(page.orders[0].wip_minor).toBe("0"); expect(page.orders[0].total_cost_minor).toBe("3800");
  expect(page.orders[0].inspections?.map(row => row.phase)).toEqual([2, 2]);
});
it("keeps actual uninspected output held in WIP with zero FG disposition", async () => {
  const page = await parseManufacturingV2Page(actualManufacturingV2Page(true), scopeV2);
  expect(page.orders[0].held_quantity_scaled).toBe("4"); expect(page.orders[0].held_cost_minor).toBe("1520"); expect(page.orders[0].wip_minor).toBe("3800");
});
it.each(["en", "ar"])("retains approved engineering source digest independently of %s presentation", async () => {
  const source = await definitionV2(true); expect(await parseManufacturingV2(source, scopeV2)).toEqual(source);
});
it("rejects a modified native source body and sibling hierarchy before displaying it", async () => {
  const source = await definitionV2(); await expect(parseManufacturingV2({ ...source, name: "Forged" }, scopeV2)).rejects.toThrow();
  await expect(parseManufacturingV2({ ...source, workspace_id: "foreign" }, scopeV2)).rejects.toThrow();
});
it.each([true, 3800, 3800.1])("rejects malformed monetary wire token %s", async value => {
  const page = actualManufacturingV2Page(); page.orders[0].total_cost_minor = value;
  await expect(parseManufacturingV2Page(page, scopeV2)).rejects.toThrow();
});
it("refuses detached material source and duplicate quality disposition", async () => {
  const page = actualManufacturingV2Page(); page.orders[0].material.output_quantity_scaled = "100";
  await expect(parseManufacturingV2Page(page, scopeV2)).rejects.toThrow();
  const duplicate = actualManufacturingV2Page(); duplicate.orders[0].inspections.push(duplicate.orders[0].inspections[0]);
  await expect(parseManufacturingV2Page(duplicate, scopeV2)).rejects.toThrow();
});
it("keeps values above JavaScript safe integers exact when sealing original rate and money", () => {
  expect(manufacturingV2Canonical({ amount_minor: "9000000000000000000", rate_minor_per_hour: "9000000000000000000" })).toBe('{"amount_minor":9000000000000000000,"rate_minor_per_hour":9000000000000000000}');
  expect(() => manufacturingV2Canonical({ value: 0.1 })).toThrow();
});
