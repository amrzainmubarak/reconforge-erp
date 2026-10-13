import { AdminApiError } from "./data";
import { cashflowMaximumBytes, cashflowSha, requestCashflow, verifyCashflowView, type CashflowView } from "./intercompany-cashflow-data";
import { canonicalIc } from "./intercompany-operations-data";
import { fxMinor, fxRequest, parseFxDetail, verifyFxEvidence, verifyFxReport, type FxDetail, type FxPolicy, type FxReport, type FxScope } from "./intercompany-fx-data";
import type { BrowserAdminSession } from "./types";

export interface GroupPin { opening: { source_id: string; source_digest: string; origin_plan_id: string; origin_plan_digest: string; seller_minor: 0; buyer_minor: 0; basis: "complete-native-source-origin-membership" }; elimination_plan_id: string; elimination_plan_digest: string; report_digest: string }
export interface GroupPinView extends Omit<GroupPin, "opening"> { opening: Omit<GroupPin["opening"], "seller_minor" | "buyer_minor"> & { seller_minor: "0"; buyer_minor: "0" } }
export interface GroupOriginal { detail: FxDetail; report: FxReport; cashflowView: CashflowView; pin: GroupPin }
export interface GroupBridgeMember { source_id: string; report_digest: string; translated_minor: string; native_adjustment_minor: string; combined_minor: string }
export interface GroupBridge { role: string; account_code: string; translated_minor: string; native_adjustment_minor: string; combined_minor: string; source_membership: GroupBridgeMember[] }
export interface GroupPeriod { tenant_id: string; id: string; application_workspace_id: string; name: string; start_date: string; end_date: string; status: "Open" | "Soft Closed" | "Closed"; status_reason: string; fiscal_year: number; period_number: number; updated_at: string }
export interface GroupDiagnostic { schema_version: string; diagnostic_digest: string; qualified_scope: { tenant_id: string; workspace_id: string; organization_id: string; legal_entity_ids: Record<"seller" | "buyer" | "adjustment", string> }; reporting_policy: FxPolicy; group_journal_id: string; selection: { pins: GroupPinView[] }; source_members: { source_id: string; source_digest: string; elimination_plan_id: string; elimination_plan_digest: string; report_digest: string; source_evidence_digest: string; source_effect_ids: string[]; native_adjustment_effect_ids: string[] }[]; trial_balance_bridge: GroupBridge[]; native_period_observations: GroupPeriod[]; income_statement: { income_minor: string; expense_minor: string; result_minor: string }; balance_sheet: { assets_minor: string; liabilities_minor: string; equity_minor: string; unclosed_result_minor: string; balanced: true }; cash_equation: { opening_minor: string; operating_net_minor: string; fx_on_cash_minor: string; closing_minor: string } }
export interface GroupView { diagnostic: GroupDiagnostic; evidence_digest: string; evidence_sha256: string; evidence_bytes: number }
export const groupRoot = "/api/v1/intercompany-group-diagnostic";
const object = (v: unknown): v is Record<string, unknown> => v !== null && typeof v === "object" && !Array.isArray(v);
const text = (v: unknown): v is string => typeof v === "string" && v.length > 0 && v.length <= 500 && !/[\x00-\x1f\x7f]/.test(v);
const hash = (v: unknown): v is string => typeof v === "string" && /^[0-9a-f]{64}$/.test(v);
const money = (v: unknown): v is string => fxMinor(v) && v !== "-0";
function invalid(): never { throw new Error("intercompany_group_contract_invalid"); }
function displayMoney(value: unknown) {
  const pending = [value]; let nodes = 0;
  while (pending.length) { const item = pending.pop(); if (++nodes > 1_000_000) invalid(); if (Array.isArray(item)) { for (const member of item) pending.push(member); } else if (object(item)) for (const [key, member] of Object.entries(item)) { if (key.endsWith("_minor") && !money(member)) invalid(); pending.push(member); } }
}
function ordered(originals: readonly GroupOriginal[]): GroupOriginal[] {
  if (originals.length < 1 || originals.length > 16 || new Set(originals.map(row => row.detail.id)).size !== originals.length) invalid();
  for (const row of originals) {
    const origin = row.detail.plans[0], final = row.detail.plans.at(-1);
    if (!row.detail.state.closed || origin?.kind !== "recognize" || final?.kind !== "eliminate" || row.detail.plans.some(plan => plan.phase !== 2) || canonicalIc(row.pin) !== canonicalIc({ opening: { source_id: row.detail.id, source_digest: row.detail.source_digest, origin_plan_id: origin.id, origin_plan_digest: origin.plan_digest, seller_minor: 0, buyer_minor: 0, basis: "complete-native-source-origin-membership" }, elimination_plan_id: final.id, elimination_plan_digest: final.plan_digest, report_digest: row.report.report_digest })) invalid();
  }
  return [...originals].sort((a, b) => a.detail.id < b.detail.id ? -1 : a.detail.id > b.detail.id ? 1 : 0);
}
export function groupSelection(originals: readonly GroupOriginal[]): { pins: GroupPin[] } { return { pins: ordered(originals).map(row => row.pin) }; }
export function groupQuery(originals: readonly GroupOriginal[]): string { const raw = JSON.stringify(groupSelection(originals)); if (raw.length > 32768) invalid(); return new URLSearchParams({ selection: raw }).toString(); }

/** Original source/report/phase seals, never a browser FX calculator. */
export async function captureGroupOriginal(session: BrowserAdminSession, scope: FxScope, id: string, knownZero: true, signal?: AbortSignal): Promise<GroupOriginal> {
  if (knownZero !== true) invalid();
  const raw = await fxRequest(session, scope, `/api/v1/intercompany-fx/sources/${encodeURIComponent(id)}`, undefined, signal), detail = parseFxDetail(raw.source, scope);
  if (detail.id !== id || !detail.state.closed || detail.plans.some(plan => plan.phase !== 2) || detail.plans[0]?.kind !== "recognize" || detail.plans.at(-1)?.kind !== "eliminate") invalid();
  const { plans: _plans, state: _state, ...source } = detail;
  for (const plan of detail.plans) {
    const proof = await fxRequest(session, scope, `/api/v1/intercompany-fx/plans/${encodeURIComponent(plan.id)}/evidence`, undefined, signal), verified = await verifyFxEvidence(proof.evidence, scope, plan);
    if (canonicalIc(verified.source) !== canonicalIc(source)) invalid();
  }
  const reported = await fxRequest(session, scope, `/api/v1/intercompany-fx/sources/${encodeURIComponent(id)}/report`, undefined, signal), report = await verifyFxReport(reported.report, detail);
  const cashflowView = await verifyCashflowView(await requestCashflow(session, scope, detail, signal), detail, report, session.tenantId);
  const origin = detail.plans[0], final = detail.plans.at(-1)!;
  return { detail, report, cashflowView, pin: { opening: { source_id: detail.id, source_digest: detail.source_digest, origin_plan_id: origin.id, origin_plan_digest: origin.plan_digest, seller_minor: 0, buyer_minor: 0, basis: "complete-native-source-origin-membership" }, elimination_plan_id: final.id, elimination_plan_digest: final.plan_digest, report_digest: report.report_digest } };
}

/** Bind the displayed bridge to already authorized original report membership.
 * Original native FX conversion is verified by the server/independent CLI. */
export async function verifyGroupView(value: unknown, originals: readonly GroupOriginal[], scope: FxScope, tenant: string): Promise<GroupView> {
  const selected = ordered(originals), first = selected[0], firstSource = first.detail;
  if (!object(value) || !object(value.diagnostic) || !hash(value.evidence_digest) || !hash(value.evidence_sha256) || !Number.isSafeInteger(value.evidence_bytes) || (value.evidence_bytes as number) < 1 || (value.evidence_bytes as number) > cashflowMaximumBytes) invalid();
  const v = value.diagnostic;
  displayMoney(v);
  const qualified = { tenant_id: tenant, workspace_id: scope.workspace_id, organization_id: scope.organization_id, legal_entity_ids: Object.fromEntries((["seller", "buyer", "adjustment"] as const).map(book => [book, firstSource.request[book].legal_entity_id])) };
  if (v.schema_version !== "intercompany-group-diagnostic-v1" || v.reporting_scope !== "explicit-selected-complete-paired-trade-sources" || v.source_elimination_complete !== true || v.formal_close_workflow_assessed !== false || v.whole_group_membership_proven !== false || v.financial_writes !== false || canonicalIc(v.qualified_scope) !== canonicalIc(qualified) || canonicalIc(v.reporting_policy) !== canonicalIc(firstSource.policies.adjustment) || canonicalIc(v.selection) !== canonicalIc(groupSelection(selected)) || !hash(v.diagnostic_digest) || !Array.isArray(v.source_members) || v.source_members.length !== selected.length || !Array.isArray(v.trial_balance_bridge) || v.trial_balance_bridge.length > 10 || !Array.isArray(v.native_period_observations) || v.native_period_observations.length < 1 || v.native_period_observations.length > 1024) invalid();
  if (await cashflowSha(new TextEncoder().encode(canonicalIc(Object.fromEntries(Object.entries(v).filter(([key]) => key !== "diagnostic_digest"))))) !== v.diagnostic_digest) invalid();
  const expected = new Map<string, GroupBridge>(), allEffects = new Set<string>(), periods = new Map<string, string[]>();
  const expectedCash = { opening_minor: 0n, operating_net_minor: 0n, fx_on_cash_minor: 0n, closing_minor: 0n };
  for (const [index, original] of selected.entries()) {
    const detail = original.detail, report = original.report, final = detail.plans.at(-1)!, member = v.source_members[index];
    if (detail.request.workspace_id !== scope.workspace_id || detail.request.organization_id !== scope.organization_id) invalid();
    const accountMap = (source: FxDetail) => (source as unknown as { native_accounts: Record<string, unknown> }).native_accounts?.adjustment;
    if (!object(accountMap(detail)) || canonicalIc(accountMap(detail)) !== canonicalIc(accountMap(firstSource))) invalid();
    const capturedCash = await verifyCashflowView(original.cashflowView, detail, report, tenant);
    for (const key of Object.keys(expectedCash) as (keyof typeof expectedCash)[]) expectedCash[key] += BigInt(capturedCash.cashflow[key]);
    if (!object(member) || member.source_evidence_digest !== capturedCash.evidence_digest || member.source_id !== detail.id || member.source_digest !== detail.source_digest || member.elimination_plan_id !== final.id || member.elimination_plan_digest !== final.plan_digest || member.report_digest !== report.report_digest || canonicalIc(member.source_effect_ids) !== canonicalIc(report.source_effect_ids) || canonicalIc(member.native_adjustment_effect_ids) !== canonicalIc(report.native_adjustment_effect_ids) || canonicalIc(report.currency_policy) !== canonicalIc(first.report.currency_policy) || v.group_journal_id !== final.entries[0].snapshot.entry.journal_id || !text(v.group_journal_id)) invalid();
    for (const book of ["seller", "buyer", "adjustment"] as const) if (detail.request[book].legal_entity_id !== qualified.legal_entity_ids[book]) invalid();
    const cfg = (source: FxDetail) => Object.fromEntries(Object.entries(source.request.adjustment).filter(([key]) => key !== "period_id"));
    if (canonicalIc(cfg(detail)) !== canonicalIc(cfg(firstSource))) invalid();
    for (const id of [...report.source_effect_ids, ...report.native_adjustment_effect_ids]) { if (allEffects.has(id)) invalid(); allEffects.add(id); }
    for (const plan of detail.plans) for (const entry of plan.entries) { const header = entry.snapshot.entry; if (!text(header.period_id) || !text(header.posting_date)) invalid(); const dates = periods.get(header.period_id) ?? []; dates.push(header.posting_date); periods.set(header.period_id, dates); }
    for (const row of report.trial_balance) {
      let translated = 0n, native = 0n;
      for (const item of row.translated_membership) { if (!money(item.balance_minor)) invalid(); translated += BigInt(item.balance_minor); }
      for (const item of row.native_adjustment_membership) { if (!money(item.debit_minor) || !money(item.credit_minor)) invalid(); native += BigInt(item.debit_minor) - BigInt(item.credit_minor); }
      if (!money(row.balance_minor) || translated + native !== BigInt(row.balance_minor)) invalid();
      const retained = expected.get(row.role) ?? { role: row.role, account_code: firstSource.request.adjustment.accounts[row.role], translated_minor: "0", native_adjustment_minor: "0", combined_minor: "0", source_membership: [] };
      retained.translated_minor = (BigInt(retained.translated_minor) + translated).toString(); retained.native_adjustment_minor = (BigInt(retained.native_adjustment_minor) + native).toString(); retained.combined_minor = (BigInt(retained.combined_minor) + BigInt(row.balance_minor)).toString();
      retained.source_membership.push({ source_id: detail.id, report_digest: report.report_digest, translated_minor: translated.toString(), native_adjustment_minor: native.toString(), combined_minor: row.balance_minor }); expected.set(row.role, retained);
    }
  }
  const expectedRows = [...expected.values()].sort((a, b) => a.role < b.role ? -1 : a.role > b.role ? 1 : 0);
  if (canonicalIc(v.trial_balance_bridge) !== canonicalIc(expectedRows)) invalid();
  for (const column of ["translated_minor", "native_adjustment_minor", "combined_minor"] as const) { if (expectedRows.some(row => !money(row[column])) || expectedRows.reduce((sum, row) => sum + BigInt(row[column]), 0n) !== 0n) invalid(); }
  const seenPeriods = new Set<string>();
  for (const row of v.native_period_observations) {
    if (!object(row) || !text(row.id) || seenPeriods.has(row.id) || row.tenant_id !== tenant || row.application_workspace_id !== scope.workspace_id || !text(row.name) || !text(row.start_date) || !/^\d{4}-\d{2}-\d{2}$/.test(row.start_date) || !text(row.end_date) || !/^\d{4}-\d{2}-\d{2}$/.test(row.end_date) || typeof row.status_reason !== "string" || row.status_reason.length > 4000 || !text(row.updated_at) || !Number.isSafeInteger(row.fiscal_year) || !Number.isSafeInteger(row.period_number) || !["Open", "Soft Closed", "Closed"].includes(String(row.status)) || !periods.has(row.id) || periods.get(row.id)!.some(date => date < String(row.start_date) || date > String(row.end_date))) invalid(); seenPeriods.add(row.id);
  }
  if (seenPeriods.size !== periods.size) invalid();
  if (canonicalIc(v.cash_equation) !== canonicalIc(Object.fromEntries(Object.entries(expectedCash).map(([key, amount]) => [key, amount.toString()])))) invalid();
  const amount = (role: string) => BigInt(expected.get(role)?.combined_minor ?? "0"), income = -amount("revenue") - amount("realized_gain") - amount("unrealized_gain"), expense = amount("expense") + amount("realized_loss") + amount("unrealized_loss"), assets = amount("receivable") + amount("cash"), liabilities = -amount("payable"), equity = -amount("cta");
  if (canonicalIc(v.income_statement) !== canonicalIc({ income_minor: income.toString(), expense_minor: expense.toString(), result_minor: (income - expense).toString() }) || canonicalIc(v.balance_sheet) !== canonicalIc({ assets_minor: assets.toString(), liabilities_minor: liabilities.toString(), equity_minor: equity.toString(), unclosed_result_minor: (income - expense).toString(), balanced: true }) || assets !== liabilities + equity + income - expense || !object(v.cash_equation) || !["opening_minor", "operating_net_minor", "fx_on_cash_minor", "closing_minor"].every(key => money(v.cash_equation && (v.cash_equation as Record<string, unknown>)[key])) || v.cash_equation.opening_minor !== "0" || BigInt(v.cash_equation.operating_net_minor as string) + BigInt(v.cash_equation.fx_on_cash_minor as string) !== amount("cash") || v.cash_equation.closing_minor !== amount("cash").toString()) invalid();
  return value as unknown as GroupView;
}

function headers(session: BrowserAdminSession, scope: FxScope): Record<string, string> { if (![session.tenantId, scope.workspace_id, scope.organization_id].every(text)) invalid(); return { Accept: "application/json", "X-ReconForge-Tenant": session.tenantId, "X-ReconForge-Workspace": scope.workspace_id, "X-ReconForge-Organization": scope.organization_id }; }
async function accepted(response: Response) { if (!response.ok) throw new AdminApiError(response.status, `http_${response.status}`); }
export async function requestGroupView(session: BrowserAdminSession, scope: FxScope, originals: readonly GroupOriginal[], signal?: AbortSignal): Promise<unknown> { const response = await fetch(`${groupRoot}/report?${groupQuery(originals)}`, { method: "GET", credentials: "same-origin", cache: "no-store", signal, headers: headers(session, scope) }); await accepted(response); return response.json(); }
export async function downloadGroupOriginal(session: BrowserAdminSession, scope: FxScope, originals: readonly GroupOriginal[], expected: GroupView, signal?: AbortSignal): Promise<Blob> {
  await verifyGroupView(expected, originals, scope, session.tenantId);
  const response = await fetch(`${groupRoot}/evidence?${groupQuery(originals)}`, { method: "GET", credentials: "same-origin", cache: "no-store", signal, headers: headers(session, scope) }); await accepted(response);
  if (response.headers.get("X-ReconForge-Evidence-SHA256") !== expected.evidence_sha256 || response.headers.get("Content-Length") !== String(expected.evidence_bytes) || !response.headers.get("Content-Type")?.startsWith("application/json") || !response.body) { await response.body?.cancel(); invalid(); }
  const reader = response.body.getReader(), bytes = new Uint8Array(expected.evidence_bytes); let position = 0;
  try { while (true) { const chunk = await reader.read(); if (chunk.done) break; if (signal?.aborted || position + chunk.value.length > bytes.length) invalid(); bytes.set(chunk.value, position); position += chunk.value.length; } }
  catch (caught) { await reader.cancel(); throw caught; } finally { reader.releaseLock(); }
  if (signal?.aborted || position !== bytes.length || await cashflowSha(bytes) !== expected.evidence_sha256) invalid();
  return new Blob([bytes.buffer], { type: "application/json" });
}
