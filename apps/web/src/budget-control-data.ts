import { AdminApiError } from "./data";
import { formatExactDecimal } from "./locale-format";
import { prepareScopedCommand, type PreparedScopedCommand } from "./scoped-command";
import type { BrowserAdminSession, Locale } from "./types";

const root = "/api/v1/budget-control/envelopes";
const maxMinor = 9_000_000_000_000_000_000n;
export interface BudgetScope { workspace_id: string; organization_id: string; legal_entity_id: string }
export interface BudgetPolicy { precision: number; rounding_policy: string; registry_version: string; registry_digest: string }
export interface BudgetEnvelope extends BudgetScope {
  id: string; period_id: string; budget_code: string; name: string; currency_code: string;
  status: "Draft" | "Submitted" | "Approved"; created_by: string; submitted_by: string | null; approved_by: string | null;
  reason: string; created_at: string; updated_at: string; row_version: number;
  limit_minor: string; reserved_minor: string; consumed_minor: string; available_minor: string;
  monetary_policy: BudgetPolicy;
}
export interface BudgetEvent {
  id: string; budget_id: string; commitment_id: string; operation: "Reserve" | "Release" | "Consume";
  amount_minor: string; remaining_minor: string; operation_date: string; source_reference: string; reason: string;
  actor_id: string; created_at: string; budget_version: number; audit_event_id: string; outbox_event_id: string; request_digest: string;
}
export interface BudgetDetail extends BudgetEnvelope { events: BudgetEvent[]; events_has_more: boolean }
export interface BudgetPage { envelopes: BudgetEnvelope[]; pagination: { limit: number; offset: number; has_more: boolean } }
export interface BudgetEvidence { audit_event_id: string; outbox_event_id: string; request_digest: string; event_id?: string }
export interface BudgetReceipt extends BudgetEnvelope { evidence: BudgetEvidence; commitment_id?: string; remaining_minor?: string }
export interface BudgetIdentity { id: string; permissions: string[]; human: boolean; stepUp: boolean; workspaces: string[]; organizations: string[]; entities: string[] }

function invalid(): never { throw new Error("budget_contract_invalid"); }
function object(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) invalid();
  return value as Record<string, unknown>;
}
function exact(value: Record<string, unknown>, fields: string[], optional: string[] = []): void {
  if (fields.some((key) => !Object.hasOwn(value, key)) || Object.keys(value).some((key) => ![...fields, ...optional].includes(key))) invalid();
}
function text(value: unknown, empty = false, maximum = 200): string {
  if (typeof value !== "string" || value.length > maximum || (!empty && !value) || /[\u0000-\u001f\u007f]/.test(value)) invalid();
  return value;
}
function nullable(value: unknown): string | null { return value === null ? null : text(value); }
function integer(value: unknown, min = 1, max = Number.MAX_SAFE_INTEGER): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < min || value > max) invalid();
  return value;
}
function minor(value: unknown, positive = false): string {
  if (typeof value !== "string" || !/^(0|[1-9]\d{0,18})$/.test(value)) invalid();
  const amount = BigInt(value);
  if (amount > maxMinor || (positive && amount === 0n)) invalid();
  return value;
}
function hash(value: unknown): string { if (typeof value !== "string" || !/^[a-f0-9]{64}$/.test(value)) invalid(); return value; }
export function canonicalBudgetScope(scope: BudgetScope): BudgetScope {
  for (const value of Object.values(scope)) if (text(value, false, 160) !== value.trim()) invalid();
  return { workspace_id: scope.workspace_id, organization_id: scope.organization_id, legal_entity_id: scope.legal_entity_id };
}
const envelopeFields = ["id", "workspace_id", "organization_id", "legal_entity_id", "period_id", "budget_code", "name", "currency_code", "status", "created_by", "submitted_by", "approved_by", "reason", "created_at", "updated_at", "row_version", "limit_minor", "reserved_minor", "consumed_minor", "available_minor", "monetary_policy"];
export function parseBudgetEnvelope(value: unknown, scope: BudgetScope, optional: string[] = []): BudgetEnvelope {
  const row = object(value); exact(row, envelopeFields, optional);
  const policy = object(row.monetary_policy); exact(policy, ["precision", "rounding_policy", "registry_version", "registry_digest"]);
  if (!["Draft", "Submitted", "Approved"].includes(String(row.status)) || !/^[A-Z]{3}$/.test(String(row.currency_code))) invalid();
  const result: BudgetEnvelope = {
    id: text(row.id), workspace_id: text(row.workspace_id, false, 160), organization_id: text(row.organization_id, false, 160), legal_entity_id: text(row.legal_entity_id, false, 160),
    period_id: text(row.period_id, false, 160), budget_code: text(row.budget_code, false, 64), name: text(row.name), currency_code: text(row.currency_code), status: row.status as BudgetEnvelope["status"],
    created_by: text(row.created_by), submitted_by: nullable(row.submitted_by), approved_by: nullable(row.approved_by), reason: text(row.reason, true, 500),
    created_at: text(row.created_at), updated_at: text(row.updated_at), row_version: integer(row.row_version),
    limit_minor: minor(row.limit_minor, true), reserved_minor: minor(row.reserved_minor), consumed_minor: minor(row.consumed_minor), available_minor: minor(row.available_minor),
    monetary_policy: { precision: integer(policy.precision, 0, 6), rounding_policy: text(policy.rounding_policy), registry_version: text(policy.registry_version), registry_digest: hash(policy.registry_digest) },
  };
  if (Object.entries(scope).some(([key, expected]) => result[key as keyof BudgetScope] !== expected)) invalid();
  if (BigInt(result.limit_minor) !== BigInt(result.reserved_minor) + BigInt(result.consumed_minor) + BigInt(result.available_minor)) invalid();
  if (result.status !== "Draft" && !result.submitted_by) invalid();
  if (result.status === "Approved" && (!result.approved_by || result.approved_by === result.created_by || result.approved_by === result.submitted_by)) invalid();
  return result;
}
export function parseBudgetDetail(value: unknown, scope: BudgetScope, id: string): BudgetDetail {
  const row = object(value), envelope = parseBudgetEnvelope(row, scope, ["events", "events_has_more"]);
  if (envelope.id !== id || !Array.isArray(row.events) || row.events.length > 100 || typeof row.events_has_more !== "boolean") invalid();
  const events = row.events.map((value): BudgetEvent => {
    const event = object(value); exact(event, ["id", "budget_id", "commitment_id", "operation", "amount_minor", "remaining_minor", "operation_date", "source_reference", "reason", "actor_id", "created_at", "budget_version", "audit_event_id", "outbox_event_id", "request_digest"]);
    if (event.budget_id !== id || !["Reserve", "Release", "Consume"].includes(String(event.operation))) invalid();
    const result = { id: text(event.id), budget_id: id, commitment_id: text(event.commitment_id), operation: event.operation as BudgetEvent["operation"], amount_minor: minor(event.amount_minor, true), remaining_minor: minor(event.remaining_minor), operation_date: text(event.operation_date), source_reference: text(event.source_reference, false, 160), reason: text(event.reason, false, 500), actor_id: text(event.actor_id), created_at: text(event.created_at), budget_version: integer(event.budget_version), audit_event_id: text(event.audit_event_id), outbox_event_id: text(event.outbox_event_id), request_digest: hash(event.request_digest) };
    if (result.budget_version > envelope.row_version || !/^\d{4}-\d{2}-\d{2}$/.test(result.operation_date)) invalid();
    return result;
  });
  if (new Set(events.map((event) => event.id)).size !== events.length || events.some((event, index) => index > 0 && event.budget_version >= events[index - 1].budget_version)) invalid();
  return { ...envelope, events, events_has_more: row.events_has_more };
}
export function budgetMoney(value: string, policy: BudgetPolicy, currency: string, locale: Locale): string {
  const digits = minor(value).padStart(policy.precision + 1, "0");
  const major = policy.precision ? `${digits.slice(0, -policy.precision)}.${digits.slice(-policy.precision)}` : digits;
  return `${formatExactDecimal(major, locale)} ${currency}`;
}
export function budgetInputMinor(value: string, precision: number): string {
  const normalized = value.trim().replace(/[٠-٩]/g, (digit) => String(digit.charCodeAt(0) - 0x660)).replace(/[۰-۹]/g, (digit) => String(digit.charCodeAt(0) - 0x6f0)).replace(/٫/g, ".");
  if (normalized.length > 32 || !/^(0|[1-9]\d*)(?:\.\d+)?$/.test(normalized)) invalid();
  const [whole, fraction = ""] = normalized.split(".");
  if (fraction.length > integer(precision, 0, 6)) invalid();
  return minor(BigInt(whole + fraction.padEnd(precision, "0")).toString(), true);
}
async function request(session: BrowserAdminSession, path: string, workspace = "", body?: object, signal?: AbortSignal, scope?: BudgetScope): Promise<unknown> {
  if (!session.tenantId || (body && !session.csrfToken)) invalid();
  const response = await fetch(path, { method: body ? "POST" : "GET", credentials: "same-origin", cache: "no-store", signal,
    headers: { Accept: "application/json", "X-ReconForge-Tenant": session.tenantId, ...(workspace ? { "X-ReconForge-Workspace": workspace } : {}), ...(scope ? { "X-ReconForge-Organization": scope.organization_id, "X-ReconForge-Legal-Entity": scope.legal_entity_id } : {}), ...(body ? { "Content-Type": "application/json", "X-ReconForge-CSRF": session.csrfToken } : {}) }, ...(body ? { body: JSON.stringify(body) } : {}) });
  if (!response.ok) {
    let code = `http_${response.status}`;
    try { const payload = object(await response.json()); const error = object(payload.error); code = text(error.code); } catch { /* Status is authoritative when no safe API error exists. */ }
    throw new AdminApiError(response.status, code);
  }
  try { return await response.json(); } catch { invalid(); }
}
export async function loadBudgetIdentity(session: BrowserAdminSession, signal?: AbortSignal): Promise<BudgetIdentity> {
  const row = object(await request(session, "/api/v1/auth/me", "", undefined, signal));
  if (!Array.isArray(row.permissions)) invalid();
  const scopes = row.authorized_scopes === undefined ? null : object(row.authorized_scopes);
  const list = (value: unknown) => { if (!Array.isArray(value)) invalid(); return value.map((entry) => text(entry, false, 160)); };
  return { id: text(row.id), permissions: list(row.permissions), human: row.principal_type === "user", stepUp: row.step_up_active === true || scopes === null,
    workspaces: scopes ? list(scopes.workspaces) : [], organizations: scopes ? list(scopes.organizations) : [], entities: scopes ? list(scopes.legal_entities) : [] };
}
function query(scope: BudgetScope) { return new URLSearchParams({ ...canonicalBudgetScope(scope) }); }
export async function loadBudgetPage(session: BrowserAdminSession, scope: BudgetScope, offset = 0, signal?: AbortSignal): Promise<BudgetPage> {
  const search = query(scope); search.set("limit", "25"); search.set("offset", String(integer(offset, 0, 10_000_000)));
  const row = object(await request(session, `${root}?${search}`, scope.workspace_id, undefined, signal, scope)); exact(row, ["envelopes", "pagination"]);
  const page = object(row.pagination); exact(page, ["limit", "offset", "has_more"]);
  if (!Array.isArray(row.envelopes) || row.envelopes.length > 25 || page.limit !== 25 || page.offset !== offset || typeof page.has_more !== "boolean") invalid();
  const envelopes = row.envelopes.map((value) => parseBudgetEnvelope(value, scope));
  if (new Set(envelopes.map((row) => row.id)).size !== envelopes.length) invalid();
  return { envelopes, pagination: { limit: 25, offset, has_more: page.has_more } };
}
export async function loadBudgetDetail(session: BrowserAdminSession, scope: BudgetScope, id: string, signal?: AbortSignal): Promise<BudgetDetail> {
  return parseBudgetDetail(await request(session, `${root}/${encodeURIComponent(text(id))}?${query(scope)}`, scope.workspace_id, undefined, signal, scope), scope, id);
}
export function prepareBudgetCommand(scope: BudgetScope, operation: "create" | "submit" | "approve" | "Reserve" | "Release" | "Consume", fields: Record<string, string | number>, id?: string, commitmentId?: string): PreparedScopedCommand {
  const canonical = canonicalBudgetScope(scope);
  if (["command_id", "workspace_id", "organization_id", "legal_entity_id"].some((key) => Object.hasOwn(fields, key))) invalid();
  const body = { ...canonical, ...fields };
  if (operation === "create") {
    if (id || commitmentId || !/^[A-Z0-9][A-Z0-9._/-]{0,63}$/.test(String(fields.budget_code)) || !/^[A-Z]{3}$/.test(String(fields.currency_code))) invalid();
    exact(body, [...Object.keys(canonical), "budget_code", "name", "period_id", "currency_code", "limit_minor"]);
    text(fields.name); text(fields.period_id, false, 160); minor(fields.limit_minor, true);
    return prepareScopedCommand(root, body);
  }
  text(id); integer(fields.expected_version, 1, Number.MAX_SAFE_INTEGER - 1); text(fields.reason, false, 500);
  const path = `${root}/${encodeURIComponent(id!)}`;
  if (operation === "submit" || operation === "approve") {
    exact(body, [...Object.keys(canonical), "expected_version", "reason"]);
    return prepareScopedCommand(`${path}/${operation}`, body);
  }
  exact(body, [...Object.keys(canonical), "expected_version", "reason", "amount_minor", "operation_date", "source_reference"]);
  minor(fields.amount_minor, true); text(fields.source_reference, false, 160);
  if (typeof fields.operation_date !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(fields.operation_date) || new Date(fields.operation_date).toISOString().slice(0, 10) !== fields.operation_date) invalid();
  const suffix = operation === "Reserve" ? "/commitments" : `/commitments/${encodeURIComponent(text(commitmentId))}/events`;
  return prepareScopedCommand(path + suffix, { ...body, operation });
}
export async function executeBudgetCommand(session: BrowserAdminSession, scope: BudgetScope, command: PreparedScopedCommand): Promise<BudgetReceipt> {
  if (!(command.path === root || command.path.startsWith(root + "/")) || Object.entries(canonicalBudgetScope(scope)).some(([key, value]) => command.body[key] !== value)) invalid();
  const row = object(await request(session, command.path, scope.workspace_id, command.body, undefined, scope));
  const envelope = parseBudgetEnvelope(row, scope, ["evidence", "commitment_id", "remaining_minor"]);
  const evidence = object(row.evidence); exact(evidence, ["audit_event_id", "outbox_event_id", "request_digest"], ["event_id"]);
  const result: BudgetReceipt = { ...envelope, evidence: { audit_event_id: text(evidence.audit_event_id), outbox_event_id: text(evidence.outbox_event_id), request_digest: hash(evidence.request_digest), ...(evidence.event_id === undefined ? {} : { event_id: text(evidence.event_id) }) } };
  if (command.path !== root && !command.path.startsWith(`${root}/${encodeURIComponent(envelope.id)}/`)) invalid();
  const expectedStatus = command.path === root ? "Draft" : command.path.endsWith("/submit") ? "Submitted" : "Approved";
  const expectedVersion = command.path === root ? 1 : Number(command.body.expected_version) + 1;
  if (envelope.status !== expectedStatus || envelope.row_version !== expectedVersion) invalid();
  if (command.body.operation !== undefined) {
    result.commitment_id = text(row.commitment_id); result.remaining_minor = minor(row.remaining_minor);
    if (!result.evidence.event_id) invalid();
  } else if (row.commitment_id !== undefined || row.remaining_minor !== undefined || evidence.event_id !== undefined) invalid();
  return result;
}
