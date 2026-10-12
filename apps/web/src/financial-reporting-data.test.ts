import { describe, expect, it } from "vitest";
import { classificationSections, majorToMinor, parseOpening, parseReportingMap, parseStatements, reportingCommand, reportingMoney } from "./financial-reporting-data";
const scope = { workspace_id: "w", organization_id: "o", legal_entity_id: "e" };
describe("exact classified financial data", () => {
  it("preserves large values and requires currency precision without rounding", () => { expect(majorToMinor("90071992547409.93", 2)).toBe("9007199254740993"); expect(reportingMoney("-9007199254740993", 2)).toBe("-90071992547409.93"); expect(majorToMinor("12.345", 3)).toBe("12345"); expect(() => majorToMinor("12.345", 2)).toThrow(); expect(() => majorToMinor("1e3", 2)).toThrow(); expect(() => majorToMinor("NaN", 2)).toThrow(); });
  it("retains nested command bytes after the user's inputs change", () => { const rows = [{ account_code: "CASH", debit_minor: "9007199254740993", credit_minor: "0" }]; const command = reportingCommand("/api/v1/financial-reporting/openings", { lines: rows }); rows[0].debit_minor = "0"; expect(JSON.parse(command.payloadJson).lines[0].debit_minor).toBe("9007199254740993"); expect(Object.isFrozen(command)).toBe(true); });
  it("rejects self-reviewed mappings and cross-entity responses", () => { const map = { ...scope, id: "map", name: "Explicit", map_digest: "a".repeat(64), status: "Reviewed", preparer_actor_id: "maker", reviewer_actor_id: "maker", review_digest: "b".repeat(64), accounts: [{ account_id: "cash", account_code: "CASH", account_name: "Cash", account_type: "Asset", normal_balance: "Debit", section: "CurrentAsset", is_cash: true }] }; expect(() => parseReportingMap(map, scope)).toThrow(); map.reviewer_actor_id = "checker"; expect(parseReportingMap(map, scope).status).toBe("Reviewed"); expect(() => parseReportingMap(map, { ...scope, legal_entity_id: "other" })).toThrow(); });
  it("refuses an opening with a posted label but no real effect or unequal money", () => { const plan = { ...scope, id: "OB1-plan", map_id: "map", entry_id: "entry", plan_digest: "a".repeat(64), status: "Posted", currency_code: "USD", currency_precision: 2, amount_minor: "10000", preparer_actor_id: "maker", reviewer_actor_id: "checker", posting_effect_id: null, lines: [{ account_code: "CASH", debit_minor: "10000", credit_minor: "0" }, { account_code: "EQUITY", debit_minor: "0", credit_minor: "10000" }] }; expect(() => parseOpening(plan, scope)).toThrow(); const valid = { ...plan, posting_effect_id: "posting" }; expect(parseOpening(valid, scope).amount_minor).toBe("10000"); valid.lines[1].credit_minor = "9999"; expect(() => parseOpening(valid, scope)).toThrow(); });
  it("offers only supported classifications of the actual native account type", () => { expect(classificationSections("Asset")).toEqual(["CurrentAsset", "NonCurrentAsset"]); expect(classificationSections("Off Balance")).toEqual([]); });
  it("verifies exact contributions, both periods and classified statements above the JS integer boundary", () => { const report = statementFixture(); expect(parseStatements(report, scope).cash_movements.closing_minor).toBe("9007199254741000"); });
  it("rejects balanced-looking statement tampering and incomplete cash or GL evidence", () => {
    const mutations: ((report: ReturnType<typeof statementFixture>) => void)[] = [
      report => { report.balance_sheet.assets_minor = "9007199254741001"; report.balance_sheet.equity_minor = "9007199254740994"; },
      report => { report.income_statement.income_minor = "8"; report.income_statement.result_minor = "8"; },
      report => { report.trial_balance.accounts[2].postings = []; },
      report => { report.trial_balance.accounts[0].postings[1].posting_date = "2026-11-01"; },
      report => { report.cash_movements.movements[0].counterpart_lines[0].account_id = "OTHER"; },
      report => { report.trial_balance.totals.closing.effect_count = 3; },
    ];
    for (const mutate of mutations) { const report = statementFixture(); mutate(report); expect(() => parseStatements(report, scope)).toThrow("financial_reporting_contract_invalid"); }
  });
});

function statementFixture() {
  const capital = 9007199254740993n, sale = 7n;
  const phase = (dr: bigint, cr: bigint) => ({ debit_minor: String(dr), credit_minor: String(cr), balance_minor: String(dr - cr), debit_balance_minor: String(dr > cr ? dr - cr : 0n), credit_balance_minor: String(cr > dr ? cr - dr : 0n) });
  const startCash = { effect_id: "START", entry_id: "START-ENTRY", period_id: "previous", posting_date: "2026-09-30", phase: "opening", line_number: 1, debit_minor: String(capital), credit_minor: "0" };
  const startEquity = { ...startCash, line_number: 2, debit_minor: "0", credit_minor: String(capital) };
  const saleCash = { effect_id: "SALE", entry_id: "SALE-ENTRY", period_id: "period", posting_date: "2026-10-08", phase: "activity", line_number: 1, debit_minor: "7", credit_minor: "0" };
  const saleIncome = { ...saleCash, line_number: 2, debit_minor: "0", credit_minor: "7" };
  const total = (amount: bigint, effects: number) => ({ effect_count: effects, turnover_totals: { debit_minor: String(amount), credit_minor: String(amount), balanced: true }, balance_totals: { debit_minor: String(amount), credit_minor: String(amount), balanced: true } });
  return { ...scope, contract_version: "financial-reporting-v1", balance_scope: "recorded-postings-business-date-as-of", map_id: "MAP", map_digest: "a".repeat(64), report_digest: "b".repeat(64), balances_digest: "c".repeat(64), period_id: "period", period_start: "2026-10-01", period_end: "2026-10-31", as_of_date: "2026-10-08", effect_count: 2,
    currency_policy: { currency_code: "USD", currency_precision: 2, currency_rounding_policy: "ROUND_HALF_UP", currency_registry_version: "synthetic-v1", currency_registry_digest: "d".repeat(64) },
    trial_balance: { accounts: [
      { account_id: "CASH", account_code: "CASH", account_name: "Cash", account_type: "Asset", normal_balance: "Debit", section: "CurrentAsset", is_cash: true, opening: phase(capital, 0n), activity: phase(sale, 0n), closing: phase(capital + sale, 0n), postings: [startCash, saleCash] },
      { account_id: "EQUITY", account_code: "EQUITY", account_name: "Equity", account_type: "Equity", normal_balance: "Credit", section: "Equity", is_cash: false, opening: phase(0n, capital), activity: phase(0n, 0n), closing: phase(0n, capital), postings: [startEquity] },
      { account_id: "REVENUE", account_code: "REVENUE", account_name: "Revenue", account_type: "Income", normal_balance: "Credit", section: "Income", is_cash: false, opening: phase(0n, 0n), activity: phase(0n, sale), closing: phase(0n, sale), postings: [saleIncome] },
    ], totals: { opening: total(capital, 1), activity: total(sale, 1), closing: total(capital + sale, 2) } },
    sections: { CurrentAsset: { opening_minor: String(capital), activity_minor: "7", closing_minor: String(capital + sale) }, Equity: { opening_minor: String(capital), activity_minor: "0", closing_minor: String(capital) }, Income: { opening_minor: "0", activity_minor: "7", closing_minor: "7" }, ...Object.fromEntries(["NonCurrentAsset", "CurrentLiability", "NonCurrentLiability", "Expense"].map(section => [section, { opening_minor: "0", activity_minor: "0", closing_minor: "0" }])) },
    balance_sheet: { assets_minor: String(capital + sale), liabilities_minor: "0", equity_minor: String(capital), accumulated_unclosed_result_minor: "7", balanced: true }, income_statement: { income_minor: "7", expense_minor: "0", result_minor: "7" },
    cash_movements: { opening_minor: String(capital), activity_minor: "7", closing_minor: String(capital + sale), inflow_minor: "7", outflow_minor: "0", movements: [{ effect_id: "SALE", entry_id: "SALE-ENTRY", posting_date: "2026-10-08", cash_delta_minor: "7", movement_kind: "Inflow", cash_lines: [{ account_id: "CASH", account_code: "CASH", ...saleCash }], counterpart_lines: [{ account_id: "REVENUE", account_code: "REVENUE", ...saleIncome }] }] },
  };
}
