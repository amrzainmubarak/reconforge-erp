import { describe, expect, it } from "vitest";

import { emptyMapping, parsePreview, validateMapping } from "./mapping";

describe("Mapping Studio safe preview", () => {
  it("parses quoted CSV deterministically without numeric coercion", () => {
    const table = parsePreview('id,amount,currency,date,note\nA-1,"1,250.00",USD,2026-07-01,"quoted, note"\n');
    expect(table.headers).toEqual(["id", "amount", "currency", "date", "note"]);
    expect(table.rows[0]).toEqual(["A-1", "1,250.00", "USD", "2026-07-01", "quoted, note"]);
  });

  it("keeps missing and malformed amounts visible instead of converting them to zero", () => {
    const table = parsePreview("id,amount,currency,date\nA-1,,USD,2026-07-01\nA-2,nope,EUR,2026-07-02\nA-3,0,JPY,2026-07-03\n");
    const issues = validateMapping(table, {
      transaction_id: "id", amount: "amount", currency: "currency", business_date: "date",
    });
    expect(table.rows[0][1]).toBe("");
    expect(issues.map((issue) => issue.code)).toEqual(["missing_value", "malformed_amount"]);
    expect(issues.some((issue) => issue.row === 3 && issue.field === "amount")).toBe(false);
  });

  it("fails closed for unsafe shape and requires every canonical mapping", () => {
    expect(() => parsePreview("id,id\n1,2\n")).toThrow("unique");
    expect(() => parsePreview('id,amount\n1,"unclosed\n')).toThrow("unclosed");
    const issues = validateMapping(parsePreview("id,amount\n1,2\n"), emptyMapping());
    expect(issues).toHaveLength(4);
    expect(issues.every((issue) => issue.code === "missing_mapping")).toBe(true);
  });

  it("rejects duplicate source mappings and impossible calendar dates", () => {
    const table = parsePreview("id,amount,currency,date\nA-1,12.00,USD,2026-02-30\n");
    const issues = validateMapping(table, {
      transaction_id: "id", amount: "amount", currency: "currency", business_date: "date",
    });
    expect(issues).toContainEqual({ row: 1, field: "business_date", code: "invalid_date", value: "2026-02-30" });
    const duplicates = validateMapping(table, {
      transaction_id: "id", amount: "amount", currency: "currency", business_date: "currency",
    });
    expect(duplicates.filter((issue) => issue.code === "duplicate_mapping")).toHaveLength(2);
  });
});
