import { describe, expect, it } from "vitest";
import { parseEvidencePage, parseReportSnapshot, snapshotMoney } from "./financial-reporting-snapshots";
import { snapshotFixture } from "./financial-reporting-snapshot-fixture";

const scope = { workspace_id: "work", organization_id: "org", legal_entity_id: "entity" };
describe("captured financial statements", () => {
  it("folds summary totals independently with BigInt beyond old effect and money limits", () => {
    const result = parseReportSnapshot(snapshotFixture(), scope);
    expect(result.effect_count).toBe(1001);
    expect(snapshotMoney(result.balance_sheet.assets_minor, 2)).toBe("900719925474099300000000000000000.01");
  });
  it.each(["scope", "line_count", "cash", "section", "equation", "turnover"])("refuses changed %s", change => {
    const v = snapshotFixture();
    if (change === "scope") v.legal_entity_id = "other";
    if (change === "line_count") v.line_count++;
    if (change === "cash") v.cash_movements.inflow_minor = "1";
    if (change === "section") v.sections.Income.closing_minor = "0";
    if (change === "equation") v.balance_sheet.equity_minor = "1";
    if (change === "turnover") v.trial_balance.totals.closing.turnover_totals.debit_minor = "1";
    expect(() => parseReportSnapshot(v, scope)).toThrow();
  });
  it("refuses cursor from another report or missing evidence", () => {
    const report = parseReportSnapshot(snapshotFixture(), scope);
    expect(() => parseEvidencePage({ snapshot_id: report.id, report_digest: "d".repeat(64), evidence_digest: report.evidence_digest, effect_count: 1001, after: 0, previous_digest: "a".repeat(64), items: [], next_after: 1 }, report, 0)).toThrow();
    expect(() => parseEvidencePage({ snapshot_id: report.id, report_digest: report.report_digest, evidence_digest: report.evidence_digest, effect_count: 1001, after: 0, previous_digest: "a".repeat(64), items: [], next_after: 0 }, report, 0)).toThrow();
  });
});
