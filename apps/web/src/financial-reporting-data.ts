import { AdminApiError } from "./data";
import type { BrowserAdminSession } from "./types";
import type { FinanceScope } from "./enterprise-finance-data";

export type Section = "CurrentAsset" | "NonCurrentAsset" | "CurrentLiability" | "NonCurrentLiability" | "Equity" | "Income" | "Expense";
export const statementSections: readonly Section[] = ["CurrentAsset", "NonCurrentAsset", "CurrentLiability", "NonCurrentLiability", "Equity", "Income", "Expense"];
export interface ClassifiedAccount { account_id: string; account_code: string; account_name: string; account_type: string; normal_balance: string; section: Section; is_cash: boolean }
export interface ReportingMap extends FinanceScope { id: string; name: string; map_digest: string; status: "Draft" | "Reviewed"; preparer_actor_id: string; reviewer_actor_id: string | null; review_digest: string | null; accounts: ClassifiedAccount[] }
export interface Opening extends FinanceScope { id: string; map_id: string; entry_id: string; plan_digest: string; status: "Draft" | "Reviewed" | "Posted"; currency_code: string; currency_precision: number; amount_minor: string; preparer_actor_id: string; reviewer_actor_id: string | null; posting_effect_id: string | null; lines: { account_code: string; debit_minor: string; credit_minor: string }[] }
export interface Catalog extends FinanceScope { currency_code: string; currency_precision: number; accounts: Omit<ClassifiedAccount, "section" | "is_cash">[]; periods: { id: string; name: string; start_date: string; end_date: string; status: string }[]; journals: { journal_code: string; name: string; currency_code: string }[] }
export interface Phase { debit_minor: string; credit_minor: string; balance_minor: string; debit_balance_minor: string; credit_balance_minor: string }
export interface Contribution { effect_id: string; entry_id: string; period_id: string; posting_date: string; phase: "opening" | "activity"; line_number: number; debit_minor: string; credit_minor: string }
export interface StatementAccount extends ClassifiedAccount { opening: Phase; activity: Phase; closing: Phase; postings: Contribution[] }
export interface Statements extends FinanceScope { map_id: string; map_digest: string; report_digest: string; balances_digest: string; period_start: string; as_of_date: string; effect_count: number; currency_policy: null | { currency_code: string; currency_precision: number }; trial_balance: { accounts: StatementAccount[]; totals: unknown }; balance_sheet: { assets_minor: string; liabilities_minor: string; equity_minor: string; accumulated_unclosed_result_minor: string; balanced: boolean }; income_statement: { income_minor: string; expense_minor: string; result_minor: string }; cash_movements: { opening_minor: string; activity_minor: string; closing_minor: string; inflow_minor: string; outflow_minor: string; movements: { effect_id: string; entry_id: string; posting_date: string; movement_kind: string; cash_delta_minor: string; cash_lines: Contribution[]; counterpart_lines: Contribution[] }[] } }
export interface ReportingCommand { readonly path: string; readonly payloadJson: string; readonly commandId: string }
const object = (v: unknown): v is Record<string, unknown> => v !== null && typeof v === "object" && !Array.isArray(v);
const text = (v: unknown): v is string => typeof v === "string" && v.length > 0 && v.length <= 500 && !/[\x00-\x1f\x7f]/.test(v);
const minor = (v: unknown): v is string => typeof v === "string" && /^-?(0|[1-9]\d{0,30})$/.test(v);
const digest = (v: unknown): v is string => typeof v === "string" && /^[a-f0-9]{64}$/.test(v);
const precision = (v: unknown): v is number => typeof v === "number" && Number.isInteger(v) && v >= 0 && v <= 8;
function invalid(): never { throw new Error("financial_reporting_contract_invalid"); }
function scoped(v: unknown, scope: FinanceScope): asserts v is Record<string, unknown> { if (!object(v) || Object.entries(scope).some(([key, expected]) => v[key] !== expected)) invalid(); }
function classified(v: unknown): asserts v is Record<string, unknown> { if (!object(v) || !["account_id", "account_code", "account_name", "account_type", "normal_balance"].every(key => text(v[key])) || !statementSections.includes(v.section as Section) || typeof v.is_cash !== "boolean" || (v.is_cash && v.section !== "CurrentAsset") || !["Debit", "Credit"].includes(String(v.normal_balance)) || sectionType[v.section as Section] !== v.account_type) invalid(); }
const sectionType: Record<Section, string> = { CurrentAsset: "Asset", NonCurrentAsset: "Asset", CurrentLiability: "Liability", NonCurrentLiability: "Liability", Equity: "Equity", Income: "Income", Expense: "Expense" };
export const classificationSections = (accountType: string): Section[] => statementSections.filter(section => sectionType[section] === accountType);
const date = (v: unknown): v is string => typeof v === "string" && /^\d{4}-\d{2}-\d{2}$/.test(v) && Number.isFinite(Date.parse(v)) && new Date(v).toISOString().slice(0, 10) === v;
export function parseReportingMap(v: unknown, scope: FinanceScope): ReportingMap {
  scoped(v, scope); if (!text(v.id) || !text(v.name) || !digest(v.map_digest) || !text(v.preparer_actor_id) || !Array.isArray(v.accounts) || !v.accounts.length || v.accounts.length > 1000 || !["Draft", "Reviewed"].includes(String(v.status))) invalid();
  const ids = new Set<string>(); for (const row of v.accounts) { classified(row); if (ids.has(String(row.account_id))) invalid(); ids.add(String(row.account_id)); }
  if (v.status === "Draft" ? v.reviewer_actor_id !== null || v.review_digest !== null : !text(v.reviewer_actor_id) || v.reviewer_actor_id === v.preparer_actor_id || !digest(v.review_digest)) invalid();
  return v as unknown as ReportingMap;
}
export function parseOpening(v: unknown, scope: FinanceScope): Opening {
  scoped(v, scope); if (!text(v.id) || !text(v.map_id) || !text(v.entry_id) || !digest(v.plan_digest) || !text(v.currency_code) || !precision(v.currency_precision) || !minor(v.amount_minor) || BigInt(v.amount_minor) <= 0n || !["Draft", "Reviewed", "Posted"].includes(String(v.status)) || !text(v.preparer_actor_id) || !Array.isArray(v.lines) || v.lines.length < 2 || v.lines.length > 64) invalid();
  let dr = 0n, cr = 0n; const codes = new Set<string>(); for (const line of v.lines) { if (!object(line) || !text(line.account_code) || codes.has(line.account_code) || !minor(line.debit_minor) || !minor(line.credit_minor) || BigInt(line.debit_minor) < 0n || BigInt(line.credit_minor) < 0n || (BigInt(line.debit_minor) === 0n) === (BigInt(line.credit_minor) === 0n)) invalid(); codes.add(line.account_code); dr += BigInt(line.debit_minor); cr += BigInt(line.credit_minor); }
  if (dr !== cr || dr.toString() !== v.amount_minor || (v.status === "Posted" ? !text(v.posting_effect_id) : v.posting_effect_id !== null) || (v.status === "Draft" ? v.reviewer_actor_id !== null : !text(v.reviewer_actor_id) || v.reviewer_actor_id === v.preparer_actor_id)) invalid();
  return v as unknown as Opening;
}
export function parseCatalog(v: unknown, scope: FinanceScope): Catalog {
  scoped(v, scope); if (!text(v.currency_code) || !/^[A-Z]{3}$/.test(v.currency_code) || !precision(v.currency_precision) || !Array.isArray(v.accounts) || v.accounts.length > 1000 || !Array.isArray(v.periods) || v.periods.length > 200 || !Array.isArray(v.journals) || v.journals.length > 200) invalid();
  for (const row of v.accounts) if (!object(row) || !["account_id", "account_code", "account_name", "account_type", "normal_balance"].every(k => text(row[k]))) invalid();
  for (const row of v.periods) if (!object(row) || !["id", "name", "start_date", "end_date", "status"].every(k => text(row[k]))) invalid();
  for (const row of v.journals) if (!object(row) || !["journal_code", "name", "currency_code"].every(k => text(row[k]))) invalid();
  return v as unknown as Catalog;
}
function phase(v: unknown): asserts v is Phase { if (!object(v) || !["debit_minor", "credit_minor", "balance_minor", "debit_balance_minor", "credit_balance_minor"].every(k => minor(v[k]))) invalid(); const dr = BigInt(String(v.debit_minor)), cr = BigInt(String(v.credit_minor)); if (dr < 0n || cr < 0n || (dr - cr).toString() !== v.balance_minor || (dr > cr ? dr - cr : 0n).toString() !== v.debit_balance_minor || (cr > dr ? cr - dr : 0n).toString() !== v.credit_balance_minor) invalid(); }
export function parseStatements(v: unknown, scope: FinanceScope): Statements {
  scoped(v, scope); if (v.contract_version !== "financial-reporting-v1" || v.balance_scope !== "recorded-postings-business-date-as-of" || !digest(v.report_digest) || !digest(v.map_digest) || !digest(v.balances_digest) || !text(v.map_id) || !text(v.period_id) || !date(v.period_start) || !date(v.period_end) || !date(v.as_of_date) || v.period_start > v.as_of_date || v.as_of_date > v.period_end || typeof v.effect_count !== "number" || !Number.isInteger(v.effect_count) || v.effect_count < 0 || v.effect_count > 1000 || !object(v.trial_balance) || !Array.isArray(v.trial_balance.accounts) || v.trial_balance.accounts.length > 1000 || !object(v.trial_balance.totals) || !object(v.sections) || !object(v.balance_sheet) || !object(v.income_statement) || !object(v.cash_movements) || !Array.isArray(v.cash_movements.movements)) invalid();
  if (v.currency_policy !== null && (!object(v.currency_policy) || typeof v.currency_policy.currency_code !== "string" || !/^[A-Z]{3}$/.test(v.currency_policy.currency_code) || !precision(v.currency_policy.currency_precision) || v.currency_policy.currency_rounding_policy !== "ROUND_HALF_UP" || !text(v.currency_policy.currency_registry_version) || !digest(v.currency_policy.currency_registry_digest))) invalid();
  const phases = ["opening", "activity", "closing"] as const;
  const aggregates = { opening: [0n, 0n, 0n, 0n], activity: [0n, 0n, 0n, 0n], closing: [0n, 0n, 0n, 0n] };
  const sectionSums = Object.fromEntries(statementSections.map(section => [section, { opening_minor: 0n, activity_minor: 0n, closing_minor: 0n }])) as Record<Section, { opening_minor: bigint; activity_minor: bigint; closing_minor: bigint }>;
  const phaseEffects = { opening: new Set<string>(), activity: new Set<string>() };
  const effects = new Map<string, { entry: string; period: string; day: string; phase: string; dr: bigint; cr: bigint; cash: bigint; cashLines: Record<string, unknown>[]; otherLines: Record<string, unknown>[] }>();
  let cashOpening = 0n, cashClosing = 0n; const ids = new Set<string>(), lines = new Set<string>();
  for (const row of v.trial_balance.accounts) {
    classified(row); if (ids.has(String(row.account_id)) || !Array.isArray(row.postings) || !row.postings.length) invalid(); ids.add(String(row.account_id));
    const expected = { opening: [0n, 0n], activity: [0n, 0n], closing: [0n, 0n] };
    for (const line of row.postings) {
      if (!object(line) || Object.keys(line).length !== 8 || !text(line.effect_id) || !text(line.entry_id) || !text(line.period_id) || !date(line.posting_date) || typeof line.line_number !== "number" || !Number.isInteger(line.line_number) || line.line_number < 1 || line.line_number > 10000 || !minor(line.debit_minor) || !minor(line.credit_minor)) invalid();
      const dr = BigInt(line.debit_minor), cr = BigInt(line.credit_minor), linePhase = line.posting_date < v.period_start ? "opening" : "activity";
      const key = JSON.stringify([line.effect_id, line.line_number]);
      if (dr < 0n || cr < 0n || (dr === 0n) === (cr === 0n) || lines.has(key) || line.posting_date > v.as_of_date || line.phase !== linePhase || (linePhase === "activity" && line.period_id !== v.period_id)) invalid();
      lines.add(key); if (lines.size > 10000) invalid(); phaseEffects[linePhase].add(line.effect_id);
      expected[linePhase][0] += dr; expected[linePhase][1] += cr;
      let effect = effects.get(line.effect_id);
      if (!effect) { effect = { entry: line.entry_id, period: line.period_id, day: line.posting_date, phase: linePhase, dr: 0n, cr: 0n, cash: 0n, cashLines: [], otherLines: [] }; effects.set(line.effect_id, effect); }
      if (effect.entry !== line.entry_id || effect.period !== line.period_id || effect.day !== line.posting_date || effect.phase !== linePhase) invalid();
      effect.dr += dr; effect.cr += cr;
      if (linePhase === "activity") { const retained = { account_id: row.account_id, account_code: row.account_code, ...line }; if (row.is_cash) { effect.cash += dr - cr; effect.cashLines.push(retained); } else effect.otherLines.push(retained); }
    }
    expected.closing = expected.opening.map((amount, i) => amount + expected.activity[i]);
    for (const name of phases) { phase(row[name]); const retained = row[name] as Phase, sums = expected[name]; if (BigInt(retained.debit_minor) !== sums[0] || BigInt(retained.credit_minor) !== sums[1]) invalid(); const amounts = [retained.debit_minor, retained.credit_minor, retained.debit_balance_minor, retained.credit_balance_minor]; amounts.forEach((amount, i) => { aggregates[name][i] += BigInt(amount); }); sectionSums[row.section as Section][`${name}_minor`] += BigInt(retained.balance_minor) * (["Asset", "Expense"].includes(String(row.account_type)) ? 1n : -1n); }
    if (row.is_cash) { cashOpening += BigInt((row.opening as Phase).balance_minor); cashClosing += BigInt((row.closing as Phase).balance_minor); }
  }
  if (effects.size !== v.effect_count || (effects.size === 0) !== (v.currency_policy === null) || [...effects.values()].some(effect => effect.dr !== effect.cr)) invalid();
  for (const name of phases) { const total = v.trial_balance.totals[name], sums = aggregates[name]; if (!object(total) || total.effect_count !== (name === "closing" ? effects.size : phaseEffects[name].size)) invalid(); for (const [part, offset] of [["turnover_totals", 0], ["balance_totals", 2]] as const) { const retained = total[part]; if (!object(retained) || !minor(retained.debit_minor) || !minor(retained.credit_minor) || BigInt(retained.debit_minor) !== sums[offset] || BigInt(retained.credit_minor) !== sums[offset + 1] || retained.balanced !== true || sums[offset] !== sums[offset + 1]) invalid(); } }
  for (const section of statementSections) { const retained = v.sections[section]; if (!object(retained) || phases.some(name => !minor(retained[`${name}_minor`]) || BigInt(String(retained[`${name}_minor`])) !== sectionSums[section][`${name}_minor`])) invalid(); }
  for (const [row, keys] of [[v.balance_sheet, ["assets_minor", "liabilities_minor", "equity_minor", "accumulated_unclosed_result_minor"]], [v.income_statement, ["income_minor", "expense_minor", "result_minor"]], [v.cash_movements, ["opening_minor", "activity_minor", "closing_minor", "inflow_minor", "outflow_minor"]]] as const) if (keys.some(k => !minor(row[k]))) invalid();
  const bs = v.balance_sheet, income = v.income_statement, cash = v.cash_movements;
  if (bs.balanced !== true || BigInt(String(bs.assets_minor)) !== BigInt(String(bs.liabilities_minor)) + BigInt(String(bs.equity_minor)) + BigInt(String(bs.accumulated_unclosed_result_minor)) || BigInt(String(income.result_minor)) !== BigInt(String(income.income_minor)) - BigInt(String(income.expense_minor)) || cashOpening.toString() !== cash.opening_minor || cashClosing.toString() !== cash.closing_minor || (cashClosing - cashOpening).toString() !== cash.activity_minor) invalid();
  if (BigInt(String(bs.assets_minor)) !== sectionSums.CurrentAsset.closing_minor + sectionSums.NonCurrentAsset.closing_minor || BigInt(String(bs.liabilities_minor)) !== sectionSums.CurrentLiability.closing_minor + sectionSums.NonCurrentLiability.closing_minor || BigInt(String(bs.equity_minor)) !== sectionSums.Equity.closing_minor || BigInt(String(bs.accumulated_unclosed_result_minor)) !== sectionSums.Income.closing_minor - sectionSums.Expense.closing_minor || BigInt(String(income.income_minor)) !== sectionSums.Income.activity_minor || BigInt(String(income.expense_minor)) !== sectionSums.Expense.activity_minor) invalid();
  const expectedMovements = [...effects.entries()].filter(([, effect]) => effect.cashLines.length).sort(([idA, a], [idB, b]) => a.day < b.day ? -1 : a.day > b.day ? 1 : idA < idB ? -1 : idA > idB ? 1 : 0);
  const cashRows = cash.movements as unknown[];
  if (cashRows.length !== expectedMovements.length) invalid();
  let movement = 0n, inflow = 0n, outflow = 0n;
  for (let i = 0; i < expectedMovements.length; i++) { const [effectId, effect] = expectedMovements[i], row = cashRows[i]; const kind = !effect.otherLines.length ? "InternalTransfer" : effect.cash > 0n ? "Inflow" : effect.cash < 0n ? "Outflow" : "ZeroNet";
    if (!object(row) || row.effect_id !== effectId || row.entry_id !== effect.entry || row.posting_date !== effect.day || row.cash_delta_minor !== effect.cash.toString() || row.movement_kind !== kind) invalid();
    for (const [field, expected] of [["cash_lines", effect.cashLines], ["counterpart_lines", effect.otherLines]] as const) { expected.sort((a, b) => Number(a.line_number) - Number(b.line_number)); const retained = row[field]; if (!Array.isArray(retained) || retained.length !== expected.length) invalid(); for (let j = 0; j < expected.length; j++) { const line = retained[j]; if (!object(line) || Object.keys(line).length !== 10 || Object.entries(expected[j]).some(([key, amount]) => line[key] !== amount)) invalid(); } }
    movement += effect.cash; if (effect.cash > 0n) inflow += effect.cash; else outflow -= effect.cash;
  }
  if (movement.toString() !== cash.activity_minor || inflow.toString() !== cash.inflow_minor || outflow.toString() !== cash.outflow_minor) invalid();
  return v as unknown as Statements;
}
export function majorToMinor(value: string, places: number): string { if (!precision(places) || !/^(0|[1-9]\d*)(\.\d+)?$/.test(value)) invalid(); const [whole, fraction = ""] = value.split("."); if (fraction.length > places) invalid(); const result = BigInt(whole) * 10n ** BigInt(places) + BigInt(fraction.padEnd(places, "0") || "0"); if (result > 9000000000000000000n) invalid(); return result.toString(); }
export function reportingMoney(value: string, places: number): string { if (!minor(value) || !precision(places)) invalid(); const negative = value.startsWith("-"), digits = (negative ? value.slice(1) : value).padStart(places + 1, "0"); return `${negative ? "-" : ""}${places ? `${digits.slice(0, -places)}.${digits.slice(-places)}` : digits}`; }
export function reportingCommand(path: string, body: Readonly<Record<string, unknown>>): ReportingCommand { if (!path.startsWith("/api/v1/financial-reporting/")) invalid(); const commandId = crypto.randomUUID(); return Object.freeze({ path, commandId, payloadJson: JSON.stringify({ ...body, command_id: commandId }) }); }
export async function reportingRequest(session: BrowserAdminSession, scope: FinanceScope, path: string, command?: ReportingCommand, signal?: AbortSignal): Promise<Record<string, unknown>> {
  if (!Object.values(scope).every(text) || !path.startsWith("/api/v1/financial-reporting/") || (command && (!session.csrfToken || command.path !== path))) invalid();
  const response = await fetch(path, { credentials: "same-origin", cache: "no-store", signal, method: command ? "POST" : "GET", headers: { Accept: "application/json", "X-ReconForge-Tenant": session.tenantId, "X-ReconForge-Workspace": scope.workspace_id, "X-ReconForge-Organization": scope.organization_id, "X-ReconForge-Legal-Entity": scope.legal_entity_id, ...(command ? { "Content-Type": "application/json", "X-ReconForge-CSRF": session.csrfToken } : {}) }, ...(command ? { body: command.payloadJson } : {}) });
  if (!response.ok) { let code = `http_${response.status}`; try { const value: unknown = await response.json(); if (object(value) && object(value.error) && text(value.error.code)) code = value.error.code; } catch { /* HTTP status remains authoritative. */ } throw new AdminApiError(response.status, code); }
  const value: unknown = await response.json(); if (!object(value) || value.api_contract_version !== "financial-reporting-api-v1") invalid(); return value;
}
