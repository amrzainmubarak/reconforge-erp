import { AdminApiError } from "./data";
import { canonicalIc } from "./intercompany-operations-data";
import type { BrowserAdminSession } from "./types";

export interface FxScope { workspace_id: string; organization_id: string }
export type FxBook = "seller" | "buyer" | "adjustment";
export type FxKind = "recognize" | "settle" | "revalue" | "reverse_revaluation" | "eliminate";
export interface FxRate { rate: string; source: string; effective_at: string }
export interface FxPolicy { currency_code: string; currency_precision: number; currency_rounding_policy: "ROUND_HALF_UP"; currency_registry_version: string; currency_registry_digest: string }
export interface FxBookConfig { legal_entity_id: string; entity_code: string; currency_code: string; journal_code: string; period_id: string; accounts: Record<string, string> }
export interface FxSource { id: string; source_digest: string; policies: Record<FxBook | "transaction", FxPolicy>; request: FxScope & { reference: string; posting_date: string; transaction_currency_code: string; transaction_minor: string; seller: FxBookConfig; buyer: FxBookConfig; adjustment: FxBookConfig } }
export interface FxLine { line_number: number; account_id: string; debit_minor: string; credit_minor: string; dimensions: Record<string, string> }
export interface FxEntry { book: FxBook; entry_id: string; snapshot: { schema_version: string; entry: Record<string, unknown>; lines: FxLine[] }; validation_digest: string; reverses_effect_id: string | null }
export interface FxPlan extends FxScope { id: string; source_id: string; source_digest: string; plan_digest: string; kind: FxKind; phase: number; status: "Prepared" | "Reviewed" | "Posted"; sequence: number; posting_date: string; reason: string; preparer_actor_id: string; reviewer_actor_id: string | null; posted_actor_id: string | null; entries: FxEntry[]; posting_effect_ids: Partial<Record<FxBook, string>>; seller_entity_id: string; buyer_entity_id: string; adjustment_entity_id: string; equation: Record<string, unknown> & { books: Partial<Record<FxBook, { account_code: string; debit_minor: string; credit_minor: string }[]>> } }
export interface FxDetail extends FxSource { state: { sequence: number; recognized: boolean; closed: boolean; transaction_paid_minor: string; active_revaluation_id: string | null }; plans: FxPlan[] }
export interface FxCatalog { entities: { id: string; entity_code: string; name: string; currency_code: string }[]; accounts: { account_code: string; account_type: string }[]; journals: { journal_code: string; currency_code: string }[]; currencies: { code: string; minor_units: number }[]; periods: { id: string; name: string; status: string }[] }
export interface FxEvidence { schema_version: string; source: FxSource; plan: FxPlan; phases: { action: string; actor_id: string; audit_event_id: string; outbox_event_id: string }[]; native_effects: { id: string; entry_id: string; validation_digest: string; posted_actor_id: string; snapshot: FxEntry["snapshot"]; audit_event_id: string; outbox_event_id: string; reverses_effect_id: string | null }[] }
export interface FxReport { report_digest: string; source_id: string; source_digest: string; adjustment_plan_digest: string; currency_policy: FxPolicy; cash_net_movement_minor: string; cta_minor: string; source_effect_ids: string[]; native_adjustment_effect_ids: string[]; income_statement: { income_minor: string; expense_minor: string; result_minor: string }; balance_sheet: { assets_minor: string; liabilities_minor: string; equity_minor: string; accumulated_unclosed_result_minor: string; balanced: boolean }; trial_balance: { role: string; account_code: string; balance_minor: string; translated_membership: { book: FxBook; balance_minor: string; contributions: Record<string, unknown>[]; derived_from_effect_ids?: string[] }[]; native_adjustment_membership: Record<string, unknown>[] }[] }

const object = (v: unknown): v is Record<string, unknown> => v !== null && typeof v === "object" && !Array.isArray(v);
const text = (v: unknown): v is string => typeof v === "string" && v.length > 0 && v.length <= 500 && !/[\x00-\x1f\x7f]/.test(v);
const hash = (v: unknown): v is string => typeof v === "string" && /^[a-f0-9]{64}$/.test(v);
export const fxMinor = (v: unknown): v is string => typeof v === "string" && /^-?(0|[1-9]\d*)$/.test(v) && BigInt(v) >= -9000000000000000000n && BigInt(v) <= 9000000000000000000n;
const integer = (v: unknown, maximum: number): v is number => typeof v === "number" && Number.isSafeInteger(v) && v >= 0 && v <= maximum;
const books: FxBook[] = ["seller", "buyer", "adjustment"];
function invalid(): never { throw new Error("intercompany_fx_contract_invalid"); }
function scopeOf(v: unknown, scope: FxScope): asserts v is Record<string, unknown> { if (!object(v) || Object.entries(scope).some(([key, value]) => v[key] !== value)) invalid(); }
function policy(v: unknown): asserts v is FxPolicy & Record<string, unknown> { if (!object(v) || !text(v.currency_code) || !integer(v.currency_precision, 8) || v.currency_rounding_policy !== "ROUND_HALF_UP" || !text(v.currency_registry_version) || !hash(v.currency_registry_digest)) invalid(); }
export function parseFxSource(v: unknown, scope: FxScope): FxSource {
  if (!object(v) || v.schema_version !== "intercompany-fx-source-v2" || !text(v.id) || !/^IC2S-[a-f0-9]{32}$/.test(v.id) || !hash(v.source_digest) || !object(v.policies)) invalid();
  scopeOf(v.request, scope); const request = v.request; const policies = v.policies;
  if (!fxMinor(request.transaction_minor) || BigInt(request.transaction_minor) <= 0n || BigInt(request.transaction_minor) > 4500000000000000000n) invalid();
  for (const book of ["transaction", ...books]) policy(policies[book]);
  const entities = new Set<string>();
  for (const book of books) { const cfg = request[book]; if (!object(cfg) || !["legal_entity_id", "entity_code", "currency_code", "journal_code", "period_id"].every(key => text(cfg[key])) || !object(cfg.accounts)) invalid(); entities.add(String(cfg.legal_entity_id)); if ((policies[book] as FxPolicy).currency_code !== cfg.currency_code) invalid(); }
  if (entities.size !== 3 || (request.seller as FxBookConfig).currency_code === (request.buyer as FxBookConfig).currency_code || new Set(Object.values(policies).map(p => (p as FxPolicy).currency_registry_digest)).size !== 1) invalid();
  return v as unknown as FxSource;
}
export function parseFxPlan(v: unknown, scope: FxScope): FxPlan {
  scopeOf(v, scope);
  if (v.schema_version !== "intercompany-fx-plan-v2" || !text(v.id) || !/^IC2[SRE]?-[a-f0-9]{32}$/.test(v.id) || !text(v.source_id) || !hash(v.plan_digest) || !hash(v.source_digest) || !integer(v.phase, 2) || !integer(v.sequence, 63) || ["Prepared", "Reviewed", "Posted"][v.phase] !== v.status || !["recognize", "settle", "revalue", "reverse_revaluation", "eliminate"].includes(String(v.kind)) || !Array.isArray(v.entries) || v.entries.length < 1 || v.entries.length > 2 || !object(v.equation) || !object(v.equation.books) || !object(v.posting_effect_ids)) invalid();
  if (!text(v.preparer_actor_id) || (v.phase > 0 ? !text(v.reviewer_actor_id) || v.reviewer_actor_id === v.preparer_actor_id : v.reviewer_actor_id !== null) || (v.phase === 2 ? !text(v.posted_actor_id) || [v.preparer_actor_id, v.reviewer_actor_id].includes(v.posted_actor_id) : v.posted_actor_id !== null)) invalid();
  const found = new Set<string>(); const ids = new Set<string>(); const equation = v.equation.books;
  for (const entry of v.entries) {
    if (!object(entry) || !text(entry.book) || !books.includes(entry.book as FxBook) || found.has(entry.book) || !text(entry.entry_id) || ids.has(entry.entry_id) || !hash(entry.validation_digest) || !object(entry.snapshot) || !Array.isArray(entry.snapshot.lines) || entry.snapshot.lines.length < 2 || entry.snapshot.lines.length > 4) invalid();
    found.add(entry.book); ids.add(entry.entry_id); const snapshot = entry.snapshot; scopeOf(snapshot.entry, scope); const header = snapshot.entry;
    if (header.id !== entry.entry_id || header.legal_entity_id !== v[`${entry.book}_entity_id`] || header.entry_number !== `${v.id.toUpperCase()}-${{ seller: "A", buyer: "B", adjustment: "G" }[entry.book as FxBook]}` || header.posting_date !== v.posting_date || header.preparer_actor_id !== v.preparer_actor_id || header.source_type !== (v.kind === "reverse_revaluation" ? "Generated" : "Manual") || header.reverses_posting_id !== entry.reverses_effect_id) invalid();
    policy(header); const rows = equation[entry.book]; const lines = snapshot.lines; if (!Array.isArray(rows) || !Array.isArray(lines) || rows.length !== lines.length) invalid();
    let debit = 0n, credit = 0n;
    for (const [index, line] of lines.entries()) { const expected = rows[index]; if (!object(line) || !object(expected) || line.line_number !== index + 1 || !text(line.account_id) || !object(line.dimensions) || !fxMinor(line.debit_minor) || !fxMinor(line.credit_minor) || BigInt(line.debit_minor) < 0n || BigInt(line.credit_minor) < 0n || (BigInt(line.debit_minor) === 0n) === (BigInt(line.credit_minor) === 0n) || line.debit_minor !== expected.debit_minor || line.credit_minor !== expected.credit_minor) invalid(); debit += BigInt(line.debit_minor); credit += BigInt(line.credit_minor); }
    if (debit !== credit || debit <= 0n || (v.phase === 2 ? !text(v.posting_effect_ids[entry.book]) : v.posting_effect_ids[entry.book] !== undefined)) invalid();
  }
  if (Object.keys(equation).sort().join() !== [...found].sort().join() || Object.keys(v.posting_effect_ids).length !== (v.phase === 2 ? found.size : 0) || (v.kind === "eliminate" ? found.size !== 1 || !found.has("adjustment") : found.has("adjustment"))) invalid();
  return v as unknown as FxPlan;
}
export function mergeFxPlan(old: FxPlan | null, ack: FxPlan): FxPlan { if (old?.id === ack.id && old.plan_digest !== ack.plan_digest) invalid(); return old?.id === ack.id && old.phase > ack.phase ? old : ack; }
export function parseFxDetail(v: unknown, scope: FxScope): FxDetail {
  const source = parseFxSource(v, scope); if (!object(v) || !object(v.state) || !Array.isArray(v.plans) || v.plans.length < 1 || v.plans.length > 64 || !fxMinor(v.state.transaction_paid_minor)) invalid();
  const plans = v.plans.map((row, sequence) => { const plan = parseFxPlan(row, scope); if (plan.sequence !== sequence || plan.source_id !== source.id || plan.source_digest !== source.source_digest) invalid(); return plan; });
  const paid = plans.filter(p => p.phase === 2 && p.kind === "settle").reduce((value, p) => { if (!fxMinor(p.equation.transaction_minor)) invalid(); return value + BigInt(p.equation.transaction_minor); }, 0n);
  if (paid.toString() !== v.state.transaction_paid_minor || paid > BigInt(source.request.transaction_minor) || v.state.sequence !== plans.filter(p => p.phase === 2).length || v.state.closed !== (plans.at(-1)?.kind === "eliminate" && plans.at(-1)?.phase === 2)) invalid();
  return { ...v, plans } as unknown as FxDetail;
}
export function parseFxCatalog(v: unknown): FxCatalog { if (!object(v) || !Array.isArray(v.entities) || v.entities.length > 100 || !Array.isArray(v.accounts) || !Array.isArray(v.journals) || !Array.isArray(v.periods) || !Array.isArray(v.currencies)) invalid(); for (const [rows, key] of [[v.entities, "id"], [v.accounts, "account_code"], [v.journals, "journal_code"], [v.periods, "id"], [v.currencies, "code"]] as const) if (rows.length > 1000 || rows.some(row => !object(row) || !text(row[key]))) invalid(); return v as unknown as FxCatalog; }
async function sha(value: string) { return [...new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value)))].map(byte => byte.toString(16).padStart(2, "0")).join(""); }
export async function verifyFxEvidence(v: unknown, scope: FxScope, expected: FxPlan): Promise<FxEvidence> {
  if (!object(v) || v.schema_version !== "intercompany-fx-native-evidence-v2" || !Array.isArray(v.phases) || !Array.isArray(v.native_effects) || !Array.isArray(v.canonical_snapshot_jsons)) invalid();
  const source = parseFxSource(v.source, scope), plan = parseFxPlan(v.plan, scope); if (canonicalIc(plan) !== canonicalIc(expected) || plan.source_id !== source.id || plan.source_digest !== source.source_digest) invalid();
  for (const [field, value, seal] of [["canonical_source_json", Object.fromEntries(Object.entries(source).filter(([k]) => k !== "source_digest")), source.source_digest], ["canonical_plan_json", Object.fromEntries(Object.entries(plan).filter(([k]) => !["phase", "status", "reviewer_actor_id", "posted_actor_id", "posting_effect_ids", "plan_digest"].includes(k))), plan.plan_digest]] as const) { if (typeof v[field] !== "string" || v[field] !== canonicalIc(value) || await sha(v[field] as string) !== seal) invalid(); }
  const actors = [plan.preparer_actor_id, plan.reviewer_actor_id, plan.posted_actor_id]; const auditIds = new Set<string>(), outboxIds = new Set<string>();
  if (v.phases.length !== plan.phase + 1 || v.canonical_snapshot_jsons.length !== plan.entries.length || v.native_effects.length !== (plan.phase === 2 ? plan.entries.length : 0)) invalid();
  for (const [index, phase] of v.phases.entries()) { if (!object(phase) || phase.action !== ["intercompany_fx_prepared", "intercompany_fx_reviewed", "intercompany_fx_posted"][index] || phase.actor_id !== actors[index] || !text(phase.audit_event_id) || !text(phase.outbox_event_id) || auditIds.has(phase.audit_event_id) || outboxIds.has(phase.outbox_event_id)) invalid(); auditIds.add(phase.audit_event_id); outboxIds.add(phase.outbox_event_id); }
  for (const [index, entry] of plan.entries.entries()) { const raw = v.canonical_snapshot_jsons[index]; if (typeof raw !== "string" || raw !== canonicalIc(entry.snapshot) || await sha(raw) !== entry.validation_digest || Object.entries(source.policies[entry.book]).some(([k, value]) => entry.snapshot.entry[k] !== value)) invalid(); if (plan.phase === 2) { const effect = v.native_effects[index]; if (!object(effect) || effect.id !== plan.posting_effect_ids[entry.book] || effect.entry_id !== entry.entry_id || effect.posted_actor_id !== plan.posted_actor_id || effect.validation_digest !== entry.validation_digest || canonicalIc(effect.snapshot) !== raw || effect.reverses_effect_id !== entry.reverses_effect_id || !text(effect.audit_event_id) || !text(effect.outbox_event_id)) invalid(); } }
  return v as unknown as FxEvidence;
}
export async function verifyFxReport(v: unknown, source: FxDetail): Promise<FxReport> {
  if (!object(v) || v.schema_version !== "intercompany-fx-management-report-v2" || v.reporting_scope !== "explicit-paired-trade-native-management" || v.source_id !== source.id || v.source_digest !== source.source_digest || !hash(v.report_digest) || !Array.isArray(v.trial_balance) || v.trial_balance.length > 10 || !object(v.balance_sheet) || v.balance_sheet.balanced !== true || !object(v.income_statement) || !fxMinor(v.cta_minor) || !fxMinor(v.cash_net_movement_minor) || !Array.isArray(v.source_effect_ids) || !Array.isArray(v.native_adjustment_effect_ids)) invalid();
  policy(v.currency_policy); if (canonicalIc(v.currency_policy) !== canonicalIc(source.policies.adjustment) || await sha(canonicalIc(Object.fromEntries(Object.entries(v).filter(([k]) => k !== "report_digest")))) !== v.report_digest) invalid();
  const elimination = source.plans.find(p => p.kind === "eliminate" && p.phase === 2); if (!elimination || v.adjustment_plan_digest !== elimination.plan_digest) invalid();
  const originalIds = source.plans.filter(p => p.phase === 2 && p.kind !== "eliminate").flatMap(p => Object.values(p.posting_effect_ids)).sort();
  if (canonicalIc(v.source_effect_ids) !== canonicalIc(originalIds) || canonicalIc(v.native_adjustment_effect_ids) !== canonicalIc(Object.values(elimination.posting_effect_ids).sort())) invalid();
  const effects = new Map(source.plans.filter(p => p.phase === 2).flatMap(p => p.entries.map(entry => [p.posting_effect_ids[entry.book], { entry, plan: p }] as const)));
  const seen = new Set<string>(); let net = 0n;
  function contribution(value: unknown, book: FxBook, account: string) {
    if (!object(value) || !text(value.effect_id) || !integer(value.line_number, 4) || !fxMinor(value.debit_minor) || !fxMinor(value.credit_minor)) invalid();
    const original = effects.get(value.effect_id); const line = original?.entry.snapshot.lines.find(line => line.line_number === value.line_number);
    if (!original || original.entry.book !== book || original.entry.entry_id !== value.entry_id || original.plan.posting_date !== value.posting_date || value.legal_entity_id !== source.request[book].legal_entity_id || value.account_code !== account || !line || line.account_id !== value.account_id || line.debit_minor !== value.debit_minor || line.credit_minor !== value.credit_minor) invalid();
    const key = value.effect_id + ":" + value.line_number; if (seen.has(key)) invalid(); seen.add(key); return BigInt(value.debit_minor) - BigInt(value.credit_minor);
  }
  for (const row of v.trial_balance) {
    if (!object(row) || !text(row.role) || !text(row.account_code) || !fxMinor(row.balance_minor) || !Array.isArray(row.translated_membership) || !Array.isArray(row.native_adjustment_membership)) invalid();
    let expected = 0n;
    for (const membership of row.translated_membership) {
      if (!object(membership) || !["seller", "buyer"].includes(String(membership.book)) || !fxMinor(membership.balance_minor) || !Array.isArray(membership.contributions)) invalid();
      expected += BigInt(membership.balance_minor);
      if (row.role === "cta") { const ids = source.plans.flatMap(p => p.phase === 2 && p.kind !== "eliminate" && p.posting_effect_ids[membership.book as FxBook] ? [p.posting_effect_ids[membership.book as FxBook]] : []).sort(); if (canonicalIc(membership.derived_from_effect_ids) !== canonicalIc(ids) || membership.contributions.length !== 0) invalid(); }
      else { if (!text(membership.native_account_code)) invalid(); for (const line of membership.contributions) contribution(line, membership.book as FxBook, membership.native_account_code); }
    }
    for (const line of row.native_adjustment_membership) expected += contribution(line, "adjustment", row.account_code);
    if (expected.toString() !== row.balance_minor) invalid(); net += BigInt(row.balance_minor);
  }
  if (seen.size !== source.plans.filter(p => p.phase === 2).reduce((total, p) => total + p.entries.reduce((count, entry) => count + entry.snapshot.lines.length, 0), 0)) invalid();
  if (net !== 0n) invalid(); return v as unknown as FxReport;
}
export async function fxRequest(session: BrowserAdminSession, scope: FxScope, path: string, body?: object, signal?: AbortSignal): Promise<Record<string, unknown>> {
  if (!Object.values(scope).every(text) || !path.startsWith("/api/v1/intercompany-fx") || (body && !session.csrfToken)) invalid();
  const response = await fetch(path, { credentials: "same-origin", cache: "no-store", signal, method: body ? "POST" : "GET", headers: { Accept: "application/json", "X-ReconForge-Tenant": session.tenantId, "X-ReconForge-Workspace": scope.workspace_id, "X-ReconForge-Organization": scope.organization_id, ...(body ? { "Content-Type": "application/json", "X-ReconForge-CSRF": session.csrfToken } : {}) }, ...(body ? { body: JSON.stringify(body) } : {}) });
  if (!response.ok) { let code = `http_${response.status}`; try { const raw: unknown = await response.json(); if (object(raw) && object(raw.error) && text(raw.error.code)) code = raw.error.code; } catch { /* Status remains authoritative. */ } throw new AdminApiError(response.status, code); }
  const raw: unknown = await response.json(); if (!object(raw)) invalid(); return raw;
}
