import type { FinanceScope } from "./enterprise-finance-data";
import type { ClassifiedAccount, Phase } from "./financial-reporting-data";
import { statementSections } from "./financial-reporting-data";

export interface ReportSnapshot extends FinanceScope {
  id: string; map_id: string; map_digest: string; report_digest: string; evidence_digest: string;
  period_id: string; period_start: string; period_end: string; as_of_date: string; captured_at: string;
  effect_count: number; line_count: number; currency_policy: null | { currency_code: string; currency_precision: number };
  trial_balance: { accounts: (ClassifiedAccount & { opening: Phase; activity: Phase; closing: Phase; line_count: number })[] };
  balance_sheet: { assets_minor: string; liabilities_minor: string; equity_minor: string; accumulated_unclosed_result_minor: string };
  income_statement: { income_minor: string; expense_minor: string; result_minor: string };
  cash_movements: { opening_minor: string; activity_minor: string; closing_minor: string; inflow_minor: string; outflow_minor: string; movement_count: number };
}
export interface EvidenceItem {
  ordinal: number; effect_id: string; validation_digest: string; previous_digest: string; chain_digest: string;
  effect: { id: string; entry_id: string; validation_digest: string; snapshot: { entry: { posting_date: string }; lines: { account_id: string; line_number: number; debit_minor: string; credit_minor: string }[] } };
}
export interface EvidencePage { snapshot_id: string; report_digest: string; evidence_digest: string; after: number; previous_digest: string; items: EvidenceItem[]; next_after: number | null; effect_count: number }
const obj = (v: unknown): v is Record<string, unknown> => v !== null && typeof v === "object" && !Array.isArray(v);
const minor = (v: unknown): v is string => typeof v === "string" && /^-?(0|[1-9]\d{0,80})$/.test(v);
const hash = (v: unknown): v is string => typeof v === "string" && /^[0-9a-f]{64}$/.test(v);
const count = (v: unknown): v is number => typeof v === "number" && Number.isSafeInteger(v) && v >= 0;
export const capturedEvidenceSeed = "e3825ae40faab73151eb1ed9d81d9fd5163ce71b24c277f770d1d1f6e78287e7";
function invalid(): never { throw new Error("financial_report_snapshot_invalid"); }
export function snapshotMoney(value: string, places: number): string {
  if (!minor(value) || !Number.isInteger(places) || places < 0 || places > 8) invalid();
  const negative = value.startsWith("-"), digits = (negative ? value.slice(1) : value).padStart(places + 1, "0");
  return `${negative ? "-" : ""}${places ? `${digits.slice(0, -places)}.${digits.slice(-places)}` : digits}`;
}
function parsePhase(v: unknown): asserts v is Phase {
  if (!obj(v) || !["debit_minor", "credit_minor", "balance_minor", "debit_balance_minor", "credit_balance_minor"].every(k => minor(v[k]))) invalid();
  const debit = BigInt(String(v.debit_minor)), credit = BigInt(String(v.credit_minor));
  if (debit < 0n || credit < 0n || v.balance_minor !== (debit - credit).toString() || v.debit_balance_minor !== (debit > credit ? debit - credit : 0n).toString() || v.credit_balance_minor !== (credit > debit ? credit - debit : 0n).toString()) invalid();
}
export function parseReportSnapshot(v: unknown, scope: FinanceScope): ReportSnapshot {
  if (!obj(v) || Object.entries(scope).some(([key, expected]) => v[key] !== expected) || v.contract_version !== "financial-reporting-snapshot-v1" || v.balance_scope !== "immutable-captured-native-postings" || typeof v.id !== "string" || !hash(v.map_digest) || !hash(v.report_digest) || !hash(v.evidence_digest) || !count(v.effect_count) || !count(v.line_count) || !obj(v.trial_balance) || !Array.isArray(v.trial_balance.accounts) || v.trial_balance.accounts.length > 1000 || !obj(v.sections) || !obj(v.balance_sheet) || !obj(v.income_statement) || !obj(v.cash_movements)) invalid();
  if (v.currency_policy !== null && (!obj(v.currency_policy) || !/^[A-Z]{3}$/.test(String(v.currency_policy.currency_code)) || !count(v.currency_policy.currency_precision) || v.currency_policy.currency_precision > 8)) invalid();
  const sums = Object.fromEntries(statementSections.map(section => [section, { opening: 0n, activity: 0n, closing: 0n }])) as Record<string, Record<string, bigint>>;
  const ids = new Set<string>(); let lines = 0, cashOpening = 0n, cashActivity = 0n;
  const phases = ["opening", "activity", "closing"] as const;
  const totals = { opening: [0n, 0n, 0n, 0n], activity: [0n, 0n, 0n, 0n], closing: [0n, 0n, 0n, 0n] };
  for (const row of v.trial_balance.accounts) {
    if (!obj(row) || typeof row.account_id !== "string" || ids.has(row.account_id) || !statementSections.includes(row.section as typeof statementSections[number]) || !count(row.line_count) || !row.line_count || typeof row.is_cash !== "boolean") invalid();
    ids.add(row.account_id); lines += row.line_count;
    const types: Record<string, string> = { CurrentAsset: "Asset", NonCurrentAsset: "Asset", CurrentLiability: "Liability", NonCurrentLiability: "Liability", Equity: "Equity", Income: "Income", Expense: "Expense" };
    if (types[String(row.section)] !== row.account_type || (row.is_cash && row.section !== "CurrentAsset")) invalid();
    for (const phase of phases) { parsePhase(row[phase]); const amount = row[phase] as Phase; sums[String(row.section)][phase] += BigInt(amount.balance_minor) * (["Asset", "Expense"].includes(String(row.account_type)) ? 1n : -1n); [amount.debit_minor, amount.credit_minor, amount.debit_balance_minor, amount.credit_balance_minor].forEach((value, i) => { totals[phase][i] += BigInt(value); }); }
    const opening = row.opening as Phase, activity = row.activity as Phase, closing = row.closing as Phase;
    if (BigInt(closing.debit_minor) !== BigInt(opening.debit_minor) + BigInt(activity.debit_minor) || BigInt(closing.credit_minor) !== BigInt(opening.credit_minor) + BigInt(activity.credit_minor)) invalid();
    if (row.is_cash) { cashOpening += BigInt(opening.balance_minor); cashActivity += BigInt(activity.balance_minor); }
  }
  if (lines !== v.line_count || (v.effect_count === 0) !== (v.currency_policy === null) || !obj(v.trial_balance.totals)) invalid();
  for (const phase of phases) { const total = v.trial_balance.totals[phase]; if (!obj(total) || !count(total.effect_count) || !obj(total.turnover_totals) || !obj(total.balance_totals)) invalid(); for (const [key, offset] of [["turnover_totals", 0], ["balance_totals", 2]] as const) { const part = total[key] as Record<string, unknown>; if (part.balanced !== true || part.debit_minor !== totals[phase][offset].toString() || part.credit_minor !== totals[phase][offset + 1].toString() || totals[phase][offset] !== totals[phase][offset + 1]) invalid(); } }
  if ((v.trial_balance.totals.closing as Record<string, unknown>).effect_count !== v.effect_count || Number((v.trial_balance.totals.opening as Record<string, unknown>).effect_count) + Number((v.trial_balance.totals.activity as Record<string, unknown>).effect_count) !== v.effect_count) invalid();
  for (const section of statementSections) { const part = v.sections[section]; if (!obj(part) || phases.some(phase => part[`${phase}_minor`] !== sums[section][phase].toString())) invalid(); }
  const bs = v.balance_sheet, income = v.income_statement, cash = v.cash_movements;
  const expected = { assets_minor: sums.CurrentAsset.closing + sums.NonCurrentAsset.closing, liabilities_minor: sums.CurrentLiability.closing + sums.NonCurrentLiability.closing, equity_minor: sums.Equity.closing, accumulated_unclosed_result_minor: sums.Income.closing - sums.Expense.closing };
  if (Object.entries(expected).some(([key, value]) => bs[key] !== value.toString()) || bs.balanced !== true || expected.assets_minor !== expected.liabilities_minor + expected.equity_minor + expected.accumulated_unclosed_result_minor || income.income_minor !== sums.Income.activity.toString() || income.expense_minor !== sums.Expense.activity.toString() || income.result_minor !== (sums.Income.activity - sums.Expense.activity).toString() || cash.opening_minor !== cashOpening.toString() || cash.activity_minor !== cashActivity.toString() || cash.closing_minor !== (cashOpening + cashActivity).toString() || !minor(cash.inflow_minor) || !minor(cash.outflow_minor) || BigInt(cash.inflow_minor) < 0n || BigInt(cash.outflow_minor) < 0n || BigInt(cash.inflow_minor) - BigInt(cash.outflow_minor) !== cashActivity || !count(cash.movement_count)) invalid();
  return v as unknown as ReportSnapshot;
}
export function parseEvidencePage(v: unknown, report: ReportSnapshot, after: number): EvidencePage {
  if (!obj(v) || v.snapshot_id !== report.id || v.report_digest !== report.report_digest || v.evidence_digest !== report.evidence_digest || v.effect_count !== report.effect_count || v.after !== after || !hash(v.previous_digest) || (after === 0 && v.previous_digest !== capturedEvidenceSeed) || !Array.isArray(v.items) || v.items.length > 200 || (v.next_after !== null && (!count(v.next_after) || v.next_after <= after))) invalid();
  let previous = v.previous_digest, ordinal = after;
  for (const row of v.items) {
    if (!obj(row) || row.ordinal !== ++ordinal || row.previous_digest !== previous || !hash(row.validation_digest) || !hash(row.chain_digest) || !obj(row.effect) || row.effect.id !== row.effect_id || row.effect.validation_digest !== row.validation_digest || !obj(row.effect.snapshot) || !obj(row.effect.snapshot.entry) || ["workspace_id", "organization_id", "legal_entity_id"].some(key => (row.effect as Record<string, unknown>)[key] !== (report as unknown as Record<string, unknown>)[key]) || !Array.isArray(row.effect.snapshot.lines)) invalid();
    let debit = 0n, credit = 0n;
    for (const line of row.effect.snapshot.lines) { if (!obj(line) || !minor(line.debit_minor) || !minor(line.credit_minor) || BigInt(line.debit_minor) < 0n || BigInt(line.credit_minor) < 0n || (BigInt(line.debit_minor) === 0n) === (BigInt(line.credit_minor) === 0n)) invalid(); debit += BigInt(line.debit_minor); credit += BigInt(line.credit_minor); }
    if (!debit || debit !== credit) invalid(); previous = row.chain_digest;
  }
  if (ordinal > report.effect_count || (ordinal < report.effect_count ? v.next_after !== ordinal : v.next_after !== null || previous !== report.evidence_digest)) invalid();
  return v as unknown as EvidencePage;
}
