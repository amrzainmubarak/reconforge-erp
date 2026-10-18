import { AdminApiError } from "./data";
import { canonicalIc } from "./intercompany-operations-data";
import { fxMinor, type FxDetail, type FxPolicy, type FxRate, type FxReport, type FxScope } from "./intercompany-fx-data";
import type { BrowserAdminSession } from "./types";

export const cashflowRoot = "/api/v1/intercompany-source-cashflow";
export const cashflowMaximumBytes = 67_108_864;
export interface CashMovement { effect_id: string; entry_id: string; line_number: number; account_id: string; account_code: string; posting_date: string; native_minor: string; operating_minor: string; historical_rate: FxRate }
export interface CashBook { legal_entity_id: string; functional_policy: FxPolicy; opening_minor: string; native_cash_minor: string; operating_minor: string; fx_on_cash_minor: string; closing_minor: string; closing_rate: FxRate; movements: CashMovement[] }
export interface SourceCashflow { schema_version: string; source_id: string; source_digest: string; cashflow_digest: string; report_digest: string; reporting_policy: FxPolicy; opening_minor: string; operating_inflow_minor: string; operating_outflow_minor: string; operating_net_minor: string; fx_on_cash_minor: string; closing_minor: string; opening_origin_plan_id: string; opening_origin_plan_digest: string; elimination_plan_id: string; elimination_plan_digest: string; source_effect_ids: string[]; native_adjustment_effect_ids: string[]; books: Record<"seller" | "buyer", CashBook> }
export interface CashflowView { cashflow: SourceCashflow; evidence_digest: string; evidence_sha256: string; evidence_bytes: number; qualified_scope: { tenant_id: string; workspace_id: string; organization_id: string; legal_entity_ids: Record<"seller" | "buyer" | "adjustment", string> } }
const object = (value: unknown): value is Record<string, unknown> => value !== null && typeof value === "object" && !Array.isArray(value);
const hash = (value: unknown): value is string => typeof value === "string" && /^[0-9a-f]{64}$/.test(value);
const text = (value: unknown): value is string => typeof value === "string" && value.length > 0 && value.length <= 500 && !/[\x00-\x1f\x7f]/.test(value);
function invalid(): never { throw new Error("intercompany_cashflow_contract_invalid"); }
export async function cashflowSha(bytes: Uint8Array): Promise<string> { return [...new Uint8Array(await crypto.subtle.digest("SHA-256", new Uint8Array(bytes).buffer))].map(value => value.toString(16).padStart(2, "0")).join(""); }
function rate(value: unknown): asserts value is FxRate { if (!object(value) || !text(value.rate) || !/^[0-9]+(?:\.[0-9]+)?$/.test(value.rate) || /^0(?:\.0+)?$/.test(value.rate) || !text(value.source) || !text(value.effective_at)) invalid(); }
export function cashflowQuery(source: FxDetail): string {
  const origin = source.plans[0];
  if (!source.state.closed || source.plans.some(plan => plan.phase !== 2) || origin?.kind !== "recognize") invalid();
  return new URLSearchParams({ source_digest: source.source_digest, origin_plan_id: origin.id, origin_plan_digest: origin.plan_digest, seller_opening_minor: "0", buyer_opening_minor: "0", opening_basis: "complete-native-source-origin-membership" }).toString();
}

/** Verify exact display values against the already verified native source/report.
 * FX conversion stays in the canonical server engine and independent CLI. */
export async function verifyCashflowView(value: unknown, source: FxDetail, report: FxReport, tenant: string): Promise<CashflowView> {
  if (!object(value) || !object(value.cashflow) || !hash(value.evidence_digest) || !hash(value.evidence_sha256) || !Number.isSafeInteger(value.evidence_bytes) || (value.evidence_bytes as number) < 1 || (value.evidence_bytes as number) > cashflowMaximumBytes) invalid();
  const qualified = { tenant_id: tenant, workspace_id: source.request.workspace_id, organization_id: source.request.organization_id, legal_entity_ids: Object.fromEntries((["seller", "buyer", "adjustment"] as const).map(book => [book, source.request[book].legal_entity_id])) };
  if (canonicalIc(value.qualified_scope) !== canonicalIc(qualified)) invalid();
  const flow = value.cashflow, origin = source.plans[0], elimination = source.plans.at(-1)!;
  if (!source.state.closed || source.plans.some(plan => plan.phase !== 2) || flow.schema_version !== "intercompany-source-cashflow-v1" || flow.scope !== "explicit-paired-trade-native-source-membership" || flow.source_id !== source.id || flow.source_digest !== source.source_digest || flow.opening_basis !== "complete-native-source-origin-membership" || flow.opening_minor !== "0" || flow.opening_origin_plan_id !== origin.id || flow.opening_origin_plan_digest !== origin.plan_digest || elimination.kind !== "eliminate" || flow.elimination_plan_id !== elimination.id || flow.elimination_plan_digest !== elimination.plan_digest || flow.report_digest !== report.report_digest || canonicalIc(flow.reporting_policy) !== canonicalIc(report.currency_policy) || !hash(flow.cashflow_digest) || !object(flow.books) || Object.keys(flow.books).sort().join() !== "buyer,seller") invalid();
  if (await cashflowSha(new TextEncoder().encode(canonicalIc(Object.fromEntries(Object.entries(flow).filter(([key]) => key !== "cashflow_digest"))))) !== flow.cashflow_digest) invalid();
  if (canonicalIc(flow.source_effect_ids) !== canonicalIc(report.source_effect_ids) || canonicalIc(flow.native_adjustment_effect_ids) !== canonicalIc(report.native_adjustment_effect_ids)) invalid();
  const totals = { inflow: 0n, outflow: 0n, operating: 0n, fx: 0n, closing: 0n };
  for (const book of ["seller", "buyer"] as const) {
    const captured = flow.books[book];
    if (!object(captured) || captured.legal_entity_id !== source.request[book].legal_entity_id || canonicalIc(captured.functional_policy) !== canonicalIc(source.policies[book]) || captured.opening_minor !== "0" || !["native_cash_minor", "operating_minor", "fx_on_cash_minor", "closing_minor"].every(key => fxMinor(captured[key])) || !Array.isArray(captured.movements) || captured.movements.length > 62) invalid();
    rate(captured.closing_rate);
    const retainedRequest = elimination as unknown as { command_request: { closing_rates: Record<string, FxRate>; income_rates: Record<string, Record<string, FxRate>> } };
    if (canonicalIc(captured.closing_rate) !== canonicalIc(retainedRequest.command_request.closing_rates[book])) invalid();
    const settlements = source.plans.filter(plan => plan.kind === "settle"), expected = settlements.map(plan => {
      const entry = plan.entries.find(row => row.book === book)!;
      const rows = plan.equation.books[book]!;
      const index = rows.findIndex(row => row.account_code === source.request[book].accounts.cash);
      if (!entry || index < 0) invalid();
      return { plan, entry, line: entry.snapshot.lines[index] };
    });
    if (captured.movements.length !== expected.length) invalid();
    let native = 0n, operating = 0n;
    for (const [index, movement] of captured.movements.entries()) {
      if (!object(movement) || !fxMinor(movement.native_minor) || !fxMinor(movement.operating_minor)) invalid();
      const { plan, entry, line } = expected[index];
      if (movement.effect_id !== plan.posting_effect_ids[book] || movement.entry_id !== entry.entry_id || movement.line_number !== line.line_number || movement.account_id !== line.account_id || movement.account_code !== source.request[book].accounts.cash || movement.posting_date !== plan.posting_date || BigInt(movement.native_minor) !== BigInt(line.debit_minor) - BigInt(line.credit_minor) || (book === "seller" ? BigInt(movement.native_minor) <= 0n || BigInt(movement.operating_minor) <= 0n : BigInt(movement.native_minor) >= 0n || BigInt(movement.operating_minor) >= 0n)) invalid();
      rate(movement.historical_rate);
      if (canonicalIc(movement.historical_rate) !== canonicalIc(retainedRequest.command_request.income_rates[book][plan.posting_date])) invalid();
      native += BigInt(movement.native_minor); operating += BigInt(movement.operating_minor);
      totals.inflow += BigInt(movement.operating_minor) > 0n ? BigInt(movement.operating_minor) : 0n;
      totals.outflow += BigInt(movement.operating_minor) < 0n ? -BigInt(movement.operating_minor) : 0n;
    }
    if (native.toString() !== captured.native_cash_minor || operating.toString() !== captured.operating_minor || operating + BigInt(captured.fx_on_cash_minor as string) !== BigInt(captured.closing_minor as string)) invalid();
    totals.operating += operating; totals.fx += BigInt(captured.fx_on_cash_minor as string); totals.closing += BigInt(captured.closing_minor as string);
  }
  for (const [key, expected] of [["operating_inflow_minor", totals.inflow], ["operating_outflow_minor", totals.outflow], ["operating_net_minor", totals.operating], ["fx_on_cash_minor", totals.fx], ["closing_minor", totals.closing]] as const) if (!fxMinor(flow[key]) || flow[key] !== expected.toString()) invalid();
  if (totals.inflow - totals.outflow !== totals.operating || totals.operating + totals.fx !== totals.closing || flow.closing_minor !== report.cash_net_movement_minor) invalid();
  return value as unknown as CashflowView;
}

function headers(session: BrowserAdminSession, scope: FxScope): Record<string, string> {
  if (![session.tenantId, scope.workspace_id, scope.organization_id].every(text)) invalid();
  return { Accept: "application/json", "X-ReconForge-Tenant": session.tenantId, "X-ReconForge-Workspace": scope.workspace_id, "X-ReconForge-Organization": scope.organization_id };
}
async function accepted(response: Response): Promise<void> { if (!response.ok) throw new AdminApiError(response.status, `http_${response.status}`); }
export async function requestCashflow(session: BrowserAdminSession, scope: FxScope, source: FxDetail, signal?: AbortSignal): Promise<unknown> {
  const response = await fetch(`${cashflowRoot}/sources/${encodeURIComponent(source.id)}?${cashflowQuery(source)}`, { method: "GET", credentials: "same-origin", cache: "no-store", signal, headers: headers(session, scope) });
  await accepted(response); return response.json();
}
export async function downloadCashflowOriginal(session: BrowserAdminSession, scope: FxScope, source: FxDetail, expected: CashflowView, signal?: AbortSignal): Promise<Blob> {
  if (expected.qualified_scope.tenant_id !== session.tenantId || expected.qualified_scope.workspace_id !== scope.workspace_id || expected.qualified_scope.organization_id !== scope.organization_id || source.request.workspace_id !== scope.workspace_id || source.request.organization_id !== scope.organization_id || expected.cashflow.source_id !== source.id || expected.cashflow.source_digest !== source.source_digest || !hash(expected.evidence_sha256) || !Number.isSafeInteger(expected.evidence_bytes) || expected.evidence_bytes < 1 || expected.evidence_bytes > cashflowMaximumBytes) invalid();
  const response = await fetch(`${cashflowRoot}/sources/${encodeURIComponent(source.id)}/evidence/export?${cashflowQuery(source)}`, { method: "GET", credentials: "same-origin", cache: "no-store", signal, headers: headers(session, scope) });
  await accepted(response);
  if (response.headers.get("X-ReconForge-Evidence-SHA256") !== expected.evidence_sha256 || response.headers.get("Content-Length") !== String(expected.evidence_bytes) || !response.headers.get("Content-Type")?.startsWith("application/json") || !response.body) { await response.body?.cancel(); invalid(); }
  const reader = response.body.getReader(), bytes = new Uint8Array(expected.evidence_bytes); let position = 0;
  try { while (true) { const chunk = await reader.read(); if (chunk.done) break; if (position + chunk.value.length > bytes.length || signal?.aborted) invalid(); bytes.set(chunk.value, position); position += chunk.value.length; } }
  catch (caught) { await reader.cancel(); throw caught; }
  finally { reader.releaseLock(); }
  if (position !== bytes.length || signal?.aborted || await cashflowSha(bytes) !== expected.evidence_sha256) invalid();
  return new Blob([bytes.buffer], { type: "application/json" });
}
