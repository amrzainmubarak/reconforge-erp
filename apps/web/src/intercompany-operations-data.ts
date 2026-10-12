import { AdminApiError } from "./data";
import type { BrowserAdminSession } from "./types";

export interface IcScope { workspace_id: string; organization_id: string }
export type IcBook = "seller" | "buyer" | "adjustment";
export interface IcPolicy { currency_code: string; currency_precision: number; currency_rounding_policy: string; currency_registry_version: string; currency_registry_digest: string }
export interface IcLine { line_number: number; account_id: string; description: string; debit_minor: string; credit_minor: string; dimensions: Record<string, string> }
export interface IcSnapshot { schema_version: string; entry: Record<string, unknown>; lines: IcLine[] }
export interface IcEntry { book: IcBook; entry_id: string; validation_digest: string; snapshot: IcSnapshot }
export interface IcPlan extends IcScope {
  id: string; source_id: string; seller_entity_id: string; buyer_entity_id: string; adjustment_entity_id: string;
  kind: "recognize" | "settle" | "eliminate"; phase: number; status: "Prepared" | "Reviewed" | "Posted"; sequence: number;
  amount_minor: string; currency_code: string; currency_precision: number; period_id: string; posting_date: string; reason: string;
  preparer_actor_id: string; reviewer_actor_id: string | null; posted_actor_id: string | null;
  source_digest: string; plan_digest: string; entries: IcEntry[]; posting_effect_ids: Partial<Record<IcBook, string>>;
  equation: { kind: string; original_minor: string; settled_before_minor: string; settlement_minor: string; outstanding_before_minor: string; amount_minor: string;
    books: Partial<Record<IcBook, { account_code: string; debit_minor: string; credit_minor: string }[]>> };
}
export interface IcSource { id: string; source_digest: string; monetary_policy: IcPolicy; preparer_actor_id: string; request: IcScope & Record<string, string> }
export interface IcDetail extends IcSource { recognized: boolean; closed: boolean; sequence: number; settled_minor: string; outstanding_minor: string; plans: IcPlan[] }
export interface IcEvidence { schema_version: string; source: IcSource; plan: IcPlan; canonical_source_json: string; canonical_plan_json: string; canonical_snapshot_jsons: string[];
  native_effects: { id: string; entry_id: string; posted_actor_id: string; audit_event_id: string; outbox_event_id: string; validation_digest: string; snapshot: IcSnapshot }[];
  phases: { action: string; actor_id: string; audit_event_id: string; outbox_event_id: string }[] }
export interface IcCatalog { entities: { id: string; entity_code: string; name: string; currency_code: string }[]; accounts: { account_code: string; account_type: string }[];
  journals: { journal_code: string }[]; periods: { id: string; name: string; status: string }[]; maps: { id: string; legal_entity_id: string; name: string }[] }
export interface IcGroupReport { report_digest: string; effect_count: number; currency_policy: IcPolicy; income_statement: { income_minor: string; expense_minor: string; result_minor: string };
  balance_sheet: { assets_minor: string; liabilities_minor: string; equity_minor: string; accumulated_unclosed_result_minor: string; balanced: boolean };
  cash_net_movements: { opening_minor: string; activity_minor: string; closing_minor: string }; trial_balance: { account_id: string; account_code: string; closing: { balance_minor: string };
    postings: { legal_entity_id: string; effect_id: string; entry_id: string; line_number: number; debit_minor: string; credit_minor: string }[] }[] }

const books = ["seller", "buyer", "adjustment"] as const;
const object = (v: unknown): v is Record<string, unknown> => v !== null && typeof v === "object" && !Array.isArray(v);
const text = (v: unknown): v is string => typeof v === "string" && v.length > 0 && v.length <= 500 && !/[\x00-\x1f\x7f]/.test(v);
const hash = (v: unknown): v is string => typeof v === "string" && /^[a-f0-9]{64}$/.test(v);
const minor = (v: unknown, signed = false): v is string => typeof v === "string" && (signed ? /^-?(0|[1-9]\d*)$/ : /^(0|[1-9]\d*)$/).test(v) && BigInt(v) >= (signed ? -9000000000000000000n : 0n) && BigInt(v) <= 9000000000000000000n;
const integer = (v: unknown, max: number): v is number => typeof v === "number" && Number.isSafeInteger(v) && v >= 0 && v <= max;
function invalid(): never { throw new Error("intercompany_contract_invalid"); }
function scoped(v: unknown, scope: IcScope): asserts v is Record<string, unknown> { if (!object(v) || Object.entries(scope).some(([k, expected]) => v[k] !== expected)) invalid(); }
function policy(v: unknown): asserts v is IcPolicy & Record<string, unknown> {
  if (!object(v) || !text(v.currency_code) || !/^[A-Z]{3}$/.test(v.currency_code) || !integer(v.currency_precision, 8) || v.currency_rounding_policy !== "ROUND_HALF_UP" || !text(v.currency_registry_version) || !hash(v.currency_registry_digest)) invalid();
}
function party(v: Record<string, unknown>) {
  if (!books.every(book => text(v[`${book}_entity_id`])) || new Set(books.map(book => v[`${book}_entity_id`])).size !== 3) invalid();
}
export function parseIcSource(v: unknown, scope: IcScope): IcSource {
  if (!object(v) || v.schema_version !== "intercompany-native-source-v1" || !text(v.id) || !/^IC-[a-f0-9]{32}$/.test(v.id) || !hash(v.source_digest) || !text(v.preparer_actor_id)) invalid();
  scoped(v.request, scope); party(v.request); policy(v.monetary_policy);
  if (!minor(v.request.amount_minor) || BigInt(v.request.amount_minor) <= 0n || BigInt(v.request.amount_minor) > 4500000000000000000n || !text(v.request.reference)) invalid();
  return v as unknown as IcSource;
}
export function parseIcPlan(v: unknown, scope: IcScope): IcPlan {
  scoped(v, scope); party(v);
  if (v.schema_version !== "intercompany-native-plan-v1" || !text(v.id) || !/^IC1-[a-f0-9]{32}$/.test(v.id) || !text(v.source_id) || !hash(v.source_digest) || !hash(v.plan_digest)
      || !integer(v.phase, 2) || ["Prepared", "Reviewed", "Posted"][v.phase] !== v.status || !integer(v.sequence, 33) || !["recognize", "settle", "eliminate"].includes(String(v.kind))
      || !integer(v.currency_precision, 8) || !text(v.currency_code) || !text(v.preparer_actor_id) || !text(v.period_id) || !text(v.posting_date) || !text(v.reason) || !minor(v.amount_minor)
      || !Array.isArray(v.entries) || v.entries.length !== (v.kind === "eliminate" ? 1 : 2) || !object(v.posting_effect_ids) || !object(v.equation) || !object(v.equation.books)) invalid();
  if ((v.phase === 0 ? v.reviewer_actor_id !== null : !text(v.reviewer_actor_id) || v.reviewer_actor_id === v.preparer_actor_id)
      || (v.phase === 2 ? !text(v.posted_actor_id) || [v.preparer_actor_id, v.reviewer_actor_id].includes(v.posted_actor_id) : v.posted_actor_id !== null)) invalid();
  const expectedBooks = v.kind === "eliminate" ? ["adjustment"] : ["buyer", "seller"], found = new Set<string>(), ids = new Set<string>(), effects = new Set<string>();
  const eq = v.equation; if (!object(eq.books)) invalid(); const equationBooks = eq.books;
  if (!["original_minor", "settled_before_minor", "settlement_minor", "outstanding_before_minor", "amount_minor"].every(key => minor(eq[key]))
      || eq.kind !== v.kind || eq.amount_minor !== v.amount_minor || BigInt(eq.original_minor as string) - BigInt(eq.settled_before_minor as string) !== BigInt(eq.outstanding_before_minor as string)
      || BigInt(eq.settlement_minor as string) > BigInt(eq.outstanding_before_minor as string) || Object.keys(equationBooks).sort().join() !== expectedBooks.join()) invalid();
  let maximum = 0n;
  for (const entry of v.entries) {
    if (!object(entry) || !text(entry.book) || !expectedBooks.includes(entry.book) || found.has(entry.book) || !text(entry.entry_id) || ids.has(entry.entry_id) || !hash(entry.validation_digest) || !object(entry.snapshot)) invalid();
    found.add(entry.book); ids.add(entry.entry_id); const snapshot = entry.snapshot; scoped(snapshot.entry, scope); const header = snapshot.entry;
    if (snapshot.schema_version !== "finance-entry-review-v1" || header.id !== entry.entry_id || header.legal_entity_id !== v[`${entry.book}_entity_id`]
        || header.entry_number !== `${v.id.toUpperCase()}-${{ seller: "A", buyer: "B", adjustment: "G" }[entry.book as IcBook]}` || header.source_type !== "Manual" || header.reverses_posting_id !== null
        || ["currency_code", "currency_precision", "period_id", "posting_date", "preparer_actor_id"].some(key => header[key] !== v[key]) || !Array.isArray(snapshot.lines) || snapshot.lines.length < 2 || snapshot.lines.length > 4) invalid();
    const expected = equationBooks[entry.book]; if (!Array.isArray(expected) || expected.length !== snapshot.lines.length) invalid();
    let dr = 0n, cr = 0n;
    for (const [index, line] of snapshot.lines.entries()) {
      const wanted = expected[index];
      if (!object(line) || !object(wanted) || line.line_number !== index + 1 || !text(line.account_id) || !object(line.dimensions) || !minor(line.debit_minor) || !minor(line.credit_minor)
          || line.debit_minor !== wanted.debit_minor || line.credit_minor !== wanted.credit_minor || (BigInt(line.debit_minor) === 0n) === (BigInt(line.credit_minor) === 0n)) invalid();
      dr += BigInt(line.debit_minor); cr += BigInt(line.credit_minor);
    }
    if (dr !== cr || dr <= 0n) invalid(); maximum = dr > maximum ? dr : maximum;
    const effect = v.posting_effect_ids[entry.book];
    if (v.phase === 2 ? !text(effect) || effects.has(effect) : effect !== undefined) invalid();
    if (typeof effect === "string") effects.add(effect);
  }
  if (maximum.toString() !== v.amount_minor || Object.keys(v.posting_effect_ids).length !== (v.phase === 2 ? v.entries.length : 0)) invalid();
  return v as unknown as IcPlan;
}
export function mergeIcPlan(current: IcPlan | null, ack: IcPlan): IcPlan { return current?.id === ack.id && current.phase > ack.phase ? current : ack; }
export function parseIcDetail(v: unknown, scope: IcScope): IcDetail {
  const source = parseIcSource(v, scope); if (!object(v) || !Array.isArray(v.plans) || v.plans.length < 1 || v.plans.length > 34 || !minor(v.settled_minor) || !minor(v.outstanding_minor) || typeof v.closed !== "boolean" || typeof v.recognized !== "boolean" || !integer(v.sequence, 34)) invalid();
  const rows = v.plans;
  const plans = rows.map((row, index) => { const p = parseIcPlan(row, scope); if (p.source_id !== source.id || p.source_digest !== source.source_digest || p.sequence !== index || (index < rows.length - 1 && p.phase !== 2)) invalid(); return p; });
  const paid = plans.filter(p => p.phase === 2 && p.kind === "settle").reduce((sum, p) => sum + BigInt(p.equation.settlement_minor), 0n);
  if (paid.toString() !== v.settled_minor || (BigInt(source.request.amount_minor) - paid).toString() !== v.outstanding_minor || plans.filter(p => p.phase === 2).length !== v.sequence
      || v.closed !== (plans.at(-1)?.kind === "eliminate" && plans.at(-1)?.phase === 2)) invalid();
  return { ...v, plans } as unknown as IcDetail;
}
export function parseIcCatalog(v: unknown): IcCatalog {
  if (!object(v) || !Array.isArray(v.entities) || v.entities.length > 100 || !Array.isArray(v.accounts) || !Array.isArray(v.journals) || !Array.isArray(v.periods) || !Array.isArray(v.maps)) invalid();
  if (v.entities.some(row => !object(row) || !["id", "entity_code", "name", "currency_code"].every(key => text(row[key])))) invalid();
  for (const [rows, key] of [[v.accounts, "account_code"], [v.journals, "journal_code"], [v.periods, "id"], [v.maps, "id"]] as const) if (rows.length > 1000 || rows.some(row => !object(row) || !text(row[key]))) invalid();
  return v as unknown as IcCatalog;
}
export function canonicalIc(v: unknown, key = ""): string {
  if (key.endsWith("_minor") && minor(v, true)) return v;
  if (Array.isArray(v)) return `[${v.map(row => canonicalIc(row)).join(",")}]`;
  if (object(v)) return `{${Object.keys(v).sort().map(field => `${JSON.stringify(field)}:${canonicalIc(v[field], field)}`).join(",")}}`;
  if (v === null || typeof v === "string" || typeof v === "boolean" || (typeof v === "number" && Number.isSafeInteger(v))) return JSON.stringify(v);
  return invalid();
}
async function sha(v: string) { return [...new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(v)))].map(byte => byte.toString(16).padStart(2, "0")).join(""); }
export async function verifyIcEvidence(v: unknown, scope: IcScope, expected: IcPlan): Promise<IcEvidence> {
  if (!object(v) || v.schema_version !== "intercompany-native-evidence-v1" || !Array.isArray(v.canonical_snapshot_jsons) || !Array.isArray(v.native_effects) || !Array.isArray(v.phases)) invalid();
  const source = parseIcSource(v.source, scope), p = parseIcPlan(v.plan, scope);
  if (source.id !== p.source_id || source.source_digest !== p.source_digest || canonicalIc(p) !== canonicalIc(expected) || books.some(book => source.request[`${book}_entity_id`] !== p[`${book}_entity_id`])) invalid();
  const definition = Object.fromEntries(Object.entries(source).filter(([key]) => key !== "source_digest"));
  const retained = Object.fromEntries(Object.entries(p).filter(([key]) => !["phase", "status", "reviewer_actor_id", "posted_actor_id", "posting_effect_ids", "plan_digest"].includes(key)));
  for (const [field, payload, digest] of [["canonical_source_json", definition, source.source_digest], ["canonical_plan_json", retained, p.plan_digest]] as const) {
    const raw = v[field]; if (typeof raw !== "string" || raw.length > 131072 || raw !== canonicalIc(payload) || await sha(raw) !== digest) invalid();
  }
  if (p.equation.original_minor !== source.request.amount_minor || source.monetary_policy.currency_precision !== p.currency_precision || source.monetary_policy.currency_code !== p.currency_code || v.canonical_snapshot_jsons.length !== p.entries.length || v.native_effects.length !== (p.phase === 2 ? p.entries.length : 0)) invalid();
  const gross = BigInt(source.request.amount_minor), paid = BigInt(p.equation.settled_before_minor), amount = BigInt(p.equation.settlement_minor), remaining = gross - paid;
  const line = (account_code: string, debit_minor: bigint, credit_minor: bigint) => ({ account_code, debit_minor: debit_minor.toString(), credit_minor: credit_minor.toString() });
  const q = source.request;
  const originalBooks = { seller: [line(q.receivable_account_code, gross, 0n), line(q.revenue_account_code, 0n, gross)], buyer: [line(q.expense_account_code, gross, 0n), line(q.payable_account_code, 0n, gross)] };
  const settlementBooks = { seller: [line(q.cash_account_code, amount, 0n), line(q.receivable_account_code, 0n, amount)], buyer: [line(q.payable_account_code, amount, 0n), line(q.cash_account_code, 0n, amount)] };
  const adjustmentBooks = { adjustment: [line(q.revenue_account_code, gross, 0n), line(q.expense_account_code, 0n, gross), ...(remaining > 0n ? [line(q.payable_account_code, remaining, 0n), line(q.receivable_account_code, 0n, remaining)] : [])] };
  if (remaining < 0n || (p.kind === "recognize" ? paid !== 0n || amount !== 0n || p.sequence !== 0 : p.kind === "settle" ? amount <= 0n || amount > remaining : amount !== 0n)
      || canonicalIc(p.equation.books) !== canonicalIc(p.kind === "recognize" ? originalBooks : p.kind === "settle" ? settlementBooks : adjustmentBooks)) invalid();
  const audits = new Set<string>(), outboxes = new Set<string>(), actors = [p.preparer_actor_id, p.reviewer_actor_id, p.posted_actor_id];
  if (v.phases.length !== p.phase + 1) invalid();
  for (const [index, row] of v.phases.entries()) {
    if (!object(row) || row.action !== ["intercompany_operation_prepared", "intercompany_operation_reviewed", "intercompany_operation_posted"][index] || row.actor_id !== actors[index]
        || !text(row.audit_event_id) || !text(row.outbox_event_id) || audits.has(row.audit_event_id) || outboxes.has(row.outbox_event_id)) invalid();
    audits.add(row.audit_event_id); outboxes.add(row.outbox_event_id);
  }
  for (const [index, entry] of p.entries.entries()) {
    const raw = v.canonical_snapshot_jsons[index];
    if (typeof raw !== "string" || raw !== canonicalIc(entry.snapshot) || await sha(raw) !== entry.validation_digest || Object.entries(source.monetary_policy).some(([key, value]) => entry.snapshot.entry[key] !== value)) invalid();
    if (p.phase === 2) {
      const effect = v.native_effects[index];
      if (!object(effect) || effect.id !== p.posting_effect_ids[entry.book] || effect.entry_id !== entry.entry_id || effect.validation_digest !== entry.validation_digest || effect.posted_actor_id !== p.posted_actor_id
          || canonicalIc(effect.snapshot) !== raw || !text(effect.audit_event_id) || !text(effect.outbox_event_id) || audits.has(effect.audit_event_id) || outboxes.has(effect.outbox_event_id)) invalid();
      audits.add(effect.audit_event_id); outboxes.add(effect.outbox_event_id);
    }
  }
  return v as unknown as IcEvidence;
}
export async function verifyIcReport(v: unknown, scope: IcScope, source: IcDetail): Promise<IcGroupReport> {
  scoped(v, scope); if (v.schema_version !== "intercompany-native-group-report-v1" || v.reporting_scope !== "explicit-three-book-management" || v.source_digest !== source.source_digest || !hash(v.report_digest)
      || !integer(v.effect_count, 3000) || !Array.isArray(v.trial_balance) || v.trial_balance.length > 10000 || !object(v.balance_sheet) || !object(v.income_statement) || !object(v.cash_net_movements)) invalid();
  if (await sha(canonicalIc(Object.fromEntries(Object.entries(v).filter(([key]) => key !== "report_digest")))) !== v.report_digest) invalid();
  const effectIds = new Set<string>(); let net = 0n;
  for (const row of v.trial_balance) {
    if (!object(row) || !text(row.account_id) || !text(row.account_code) || !object(row.closing) || !minor(row.closing.balance_minor, true) || !Array.isArray(row.postings)) invalid();
    net += BigInt(row.closing.balance_minor); let expected = 0n;
    for (const line of row.postings) { if (!object(line) || !text(line.effect_id) || !text(line.entry_id) || !books.some(book => line.legal_entity_id === source.request[`${book}_entity_id`]) || !minor(line.debit_minor) || !minor(line.credit_minor)) invalid(); effectIds.add(line.effect_id); expected += BigInt(line.debit_minor) - BigInt(line.credit_minor); }
    if (expected.toString() !== row.closing.balance_minor) invalid();
  }
  if (net !== 0n || effectIds.size !== v.effect_count || source.plans.some(p => Object.values(p.posting_effect_ids).some(id => !id || !effectIds.has(id))) || v.balance_sheet.balanced !== true) invalid();
  return v as unknown as IcGroupReport;
}
export async function icRequest(session: BrowserAdminSession, scope: IcScope, path: string, body?: object, signal?: AbortSignal): Promise<Record<string, unknown>> {
  if (!Object.values(scope).every(text) || !path.startsWith("/api/v1/intercompany-operations") || (body && !session.csrfToken)) invalid();
  const response = await fetch(path, { credentials: "same-origin", cache: "no-store", signal, method: body ? "POST" : "GET",
    headers: { Accept: "application/json", "X-ReconForge-Tenant": session.tenantId, "X-ReconForge-Workspace": scope.workspace_id, "X-ReconForge-Organization": scope.organization_id,
      ...(body ? { "Content-Type": "application/json", "X-ReconForge-CSRF": session.csrfToken } : {}) }, ...(body ? { body: JSON.stringify(body) } : {}) });
  if (!response.ok) { let code = `http_${response.status}`; try { const error: unknown = await response.json(); if (object(error) && object(error.error) && text(error.error.code)) code = error.error.code; } catch { /* HTTP status remains authoritative. */ } throw new AdminApiError(response.status, code); }
  const raw: unknown = await response.json(); if (!object(raw)) invalid(); return raw;
}
