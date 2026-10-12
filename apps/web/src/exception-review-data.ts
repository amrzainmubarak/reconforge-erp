import { AdminApiError } from "./data";
import type { BrowserAdminSession } from "./types";

const root = "/api/v1/exceptions";
const authMePath = "/api/v1/auth/me";
const risks = new Set(["low", "medium", "high", "critical"]);
const statuses = new Set(["Open", "In Review", "Resolved", "Accepted Risk", "Closed"]);
const historyActions = new Set(["exception_saved", "exception_review_assigned", "exception_review_transition"]);
const recordFields = new Set([
  "id", "workspace_id", "organization_id", "legal_entity_id", "source_type", "source_id",
  "period_name", "entity_code", "account_code", "control_code", "risk_rating", "owner", "status",
  "escalation_level", "sla_target_date", "description", "created_at", "updated_at", "row_version",
]);
const historyFields = new Set([
  "id", "exception_id", "action", "from_status", "to_status", "from_owner", "to_owner", "actor_label",
  "actor_id", "reason", "occurred_at", "audit_event_id", "outbox_event_id",
]);
const detailFields = new Set([...recordFields, "history", "history_page"]);

export type ExceptionReviewRisk = "low" | "medium" | "high" | "critical";
export type ExceptionReviewStatus = "Open" | "In Review" | "Resolved" | "Accepted Risk" | "Closed";

export interface ExceptionReviewIdentity {
  id: string;
  username: string;
  permissions: string[];
  workspaces: string[];
  human: boolean;
}

export interface ExceptionReviewRecord {
  id: string;
  workspace_id: string;
  organization_id: string | null;
  legal_entity_id: string | null;
  source_type: string;
  source_id: string;
  period_name: string;
  entity_code: string;
  account_code: string;
  control_code: string;
  risk_rating: ExceptionReviewRisk;
  owner: string;
  status: ExceptionReviewStatus;
  escalation_level: string;
  sla_target_date: string | null;
  description: string;
  created_at: string;
  updated_at: string;
  row_version: number;
}

export interface ExceptionReviewHistory {
  id: string;
  exception_id: string;
  action: "exception_saved" | "exception_review_assigned" | "exception_review_transition";
  from_status: string;
  to_status: string;
  from_owner: string;
  to_owner: string;
  actor_label: string;
  actor_id: string;
  reason: string;
  occurred_at: string;
  audit_event_id: string | null;
  outbox_event_id: string | null;
}

export interface ExceptionReviewHistoryPage {
  limit: number;
  has_more: boolean;
  next_cursor: string | null;
}

export interface ExceptionReviewDetail extends ExceptionReviewRecord {
  history: ExceptionReviewHistory[];
  history_page: ExceptionReviewHistoryPage;
}

export interface ExceptionReviewPagination {
  limit: number;
  returned: number;
  has_more: boolean;
  next_cursor: string | null;
}

export interface ExceptionReviewListPage {
  exceptions: ExceptionReviewRecord[];
  pagination: ExceptionReviewPagination;
}

export interface ExceptionReviewFilters {
  risk?: ExceptionReviewRisk;
  status?: ExceptionReviewStatus;
  owner?: string;
  period?: string;
  entity?: string;
  account?: string;
  control?: string;
}

interface RequestOptions {
  body?: Record<string, unknown>;
  signal?: AbortSignal;
  fetcher?: typeof fetch;
}

const isObject = (value: unknown): value is Record<string, unknown> => typeof value === "object" && value !== null && !Array.isArray(value);
const isText = (value: unknown): value is string => typeof value === "string" && value.length <= 2_000;

function invalid(): never {
  throw new Error("exception_review_contract_invalid");
}

function text(value: unknown, { allowEmpty = true, maximum = 2_000 }: { allowEmpty?: boolean; maximum?: number } = {}): string {
  if (typeof value !== "string" || value.length > maximum || (!allowEmpty && !value.trim())) invalid();
  return value;
}

function nullableText(value: unknown, options?: { maximum?: number }): string | null {
  if (value === null || value === undefined) return null;
  return text(value, options);
}

function positiveInteger(value: unknown, maximum = 250): number {
  if (!Number.isSafeInteger(value) || Number(value) < 1 || Number(value) > maximum) invalid();
  return Number(value);
}

function nonnegativeInteger(value: unknown, maximum = 250): number {
  if (!Number.isSafeInteger(value) || Number(value) < 0 || Number(value) > maximum) invalid();
  return Number(value);
}

function onlyFields(value: Record<string, unknown>, allowed: Set<string>): void {
  if (!Object.keys(value).every((key) => allowed.has(key))) invalid();
}

function requiredFields(value: Record<string, unknown>, fields: readonly string[]): void {
  if (!fields.every((field) => Object.hasOwn(value, field))) invalid();
}

function scopeValue(value: string, maximum = 160): string {
  const normalized = value.trim();
  if (!normalized || normalized.length > maximum) invalid();
  return normalized;
}

function cursorValue(value: string | undefined): string | undefined {
  if (value === undefined) return undefined;
  const normalized = value.trim();
  if (!normalized || normalized.length > 200) invalid();
  return normalized;
}

function pageLimit(value: number): number {
  if (!Number.isSafeInteger(value) || value < 1 || value > 250) invalid();
  return value;
}

function parseRecord(value: unknown, allowDetailFields = false): ExceptionReviewRecord {
  if (!isObject(value)) invalid();
  onlyFields(value, allowDetailFields ? detailFields : recordFields);
  requiredFields(value, [
    "id", "workspace_id", "source_type", "source_id", "period_name", "entity_code", "account_code",
    "control_code", "risk_rating", "owner", "status", "escalation_level", "sla_target_date", "description",
    "created_at", "updated_at", "row_version",
  ]);
  const risk = text(value.risk_rating, { allowEmpty: false, maximum: 16 });
  const status = text(value.status, { allowEmpty: false, maximum: 32 });
  if (!risks.has(risk) || !statuses.has(status)) invalid();
  return {
    id: text(value.id, { allowEmpty: false, maximum: 200 }),
    workspace_id: text(value.workspace_id, { allowEmpty: false, maximum: 160 }),
    organization_id: nullableText(value.organization_id, { maximum: 160 }),
    legal_entity_id: nullableText(value.legal_entity_id, { maximum: 160 }),
    source_type: text(value.source_type, { allowEmpty: false, maximum: 120 }),
    source_id: text(value.source_id, { allowEmpty: false, maximum: 200 }),
    period_name: text(value.period_name, { maximum: 160 }),
    entity_code: text(value.entity_code, { maximum: 160 }),
    account_code: text(value.account_code, { maximum: 160 }),
    control_code: text(value.control_code, { maximum: 160 }),
    risk_rating: risk as ExceptionReviewRisk,
    owner: text(value.owner, { maximum: 160 }),
    status: status as ExceptionReviewStatus,
    escalation_level: text(value.escalation_level, { maximum: 80 }),
    sla_target_date: nullableText(value.sla_target_date, { maximum: 200 }),
    description: text(value.description, { allowEmpty: false, maximum: 2_000 }),
    created_at: text(value.created_at, { allowEmpty: false, maximum: 200 }),
    updated_at: text(value.updated_at, { allowEmpty: false, maximum: 200 }),
    row_version: positiveInteger(value.row_version, Number.MAX_SAFE_INTEGER),
  };
}

export function parseExceptionReviewHistory(value: unknown): ExceptionReviewHistory {
  if (!isObject(value)) invalid();
  onlyFields(value, historyFields);
  requiredFields(value, [
    "id", "exception_id", "action", "from_status", "to_status", "from_owner", "to_owner", "actor_label",
    "actor_id", "reason", "occurred_at",
  ]);
  const action = text(value.action, { allowEmpty: false, maximum: 80 });
  if (!historyActions.has(action)) invalid();
  return {
    id: text(value.id, { allowEmpty: false, maximum: 200 }),
    exception_id: text(value.exception_id, { allowEmpty: false, maximum: 200 }),
    action: action as ExceptionReviewHistory["action"],
    from_status: text(value.from_status, { maximum: 32 }),
    to_status: text(value.to_status, { maximum: 32 }),
    from_owner: text(value.from_owner, { maximum: 160 }),
    to_owner: text(value.to_owner, { maximum: 160 }),
    actor_label: text(value.actor_label, { maximum: 200 }),
    actor_id: text(value.actor_id, { maximum: 200 }),
    reason: text(value.reason, { maximum: 1_000 }),
    occurred_at: text(value.occurred_at, { allowEmpty: false, maximum: 200 }),
    audit_event_id: nullableText(value.audit_event_id, { maximum: 200 }),
    outbox_event_id: nullableText(value.outbox_event_id, { maximum: 200 }),
  };
}

export function parseExceptionReviewDetail(value: unknown): ExceptionReviewDetail {
  const record = parseRecord(value, true);
  if (!isObject(value) || !Array.isArray(value.history) || !isObject(value.history_page)) invalid();
  const page = value.history_page;
  onlyFields(page, new Set(["limit", "has_more", "next_cursor"]));
  requiredFields(page, ["limit", "has_more", "next_cursor"]);
  if (typeof page.has_more !== "boolean") invalid();
  const history = value.history.map(parseExceptionReviewHistory);
  const nextCursor = nullableText(page.next_cursor, { maximum: 200 });
  if (history.length > positiveInteger(page.limit) || new Set(history.map((item) => item.id)).size !== history.length) invalid();
  if (page.has_more !== Boolean(nextCursor)) invalid();
  return {
    ...record,
    history,
    history_page: {
      limit: positiveInteger(page.limit),
      has_more: page.has_more,
      next_cursor: nextCursor,
    },
  };
}

export function parseExceptionReviewListPage(value: unknown, workspace: string): ExceptionReviewListPage {
  if (!isObject(value) || !Array.isArray(value.exceptions) || !isObject(value.pagination)) invalid();
  onlyFields(value, new Set(["exceptions", "pagination"]));
  const pagination = value.pagination;
  onlyFields(pagination, new Set(["limit", "returned", "has_more", "next_cursor"]));
  requiredFields(pagination, ["limit", "returned", "has_more", "next_cursor"]);
  if (typeof pagination.has_more !== "boolean") invalid();
  const records = value.exceptions.map((record) => parseRecord(record));
  const limit = positiveInteger(pagination.limit);
  const returned = nonnegativeInteger(pagination.returned);
  const nextCursor = nullableText(pagination.next_cursor, { maximum: 200 });
  if (records.length !== returned || returned > limit || records.some((record) => record.workspace_id !== workspace)) invalid();
  if (new Set(records.map((record) => record.id)).size !== records.length) invalid();
  if (pagination.has_more !== Boolean(nextCursor)) invalid();
  return {
    exceptions: records,
    pagination: {
      limit,
      returned,
      has_more: pagination.has_more,
      next_cursor: nextCursor,
    },
  };
}

function parseIdentity(value: unknown): ExceptionReviewIdentity {
  if (!isObject(value) || !isObject(value.authorized_scopes) || !Array.isArray(value.permissions)) invalid();
  const scopes = value.authorized_scopes;
  if (!Array.isArray(scopes.workspaces) || !value.permissions.every(isText) || !scopes.workspaces.every(isText)) invalid();
  const workspaces = scopes.workspaces.map((workspace) => scopeValue(workspace));
  if (workspaces.length > 1_000 || new Set(workspaces).size !== workspaces.length) invalid();
  const permissions = value.permissions.map((permission) => text(permission, { allowEmpty: false, maximum: 160 }));
  return {
    id: text(value.id, { allowEmpty: false, maximum: 200 }),
    username: text(value.username, { allowEmpty: false, maximum: 200 }),
    permissions,
    workspaces,
    human: value.principal_type === "user",
  };
}

async function apiFetch(
  session: BrowserAdminSession,
  workspace: string,
  path: string,
  options: RequestOptions = {},
): Promise<unknown> {
  if (!(path === authMePath || path === root || path.startsWith(`${root}?`) || path.startsWith(`${root}/`))) invalid();
  const selectedWorkspace = workspace ? scopeValue(workspace) : "";
  const response = await (options.fetcher ?? fetch)(path, {
    method: options.body ? "POST" : "GET",
    credentials: "same-origin",
    cache: "no-store",
    signal: options.signal,
    headers: {
      Accept: "application/json",
      "X-ReconForge-Tenant": scopeValue(session.tenantId),
      ...(selectedWorkspace ? { "X-ReconForge-Workspace": selectedWorkspace } : {}),
      ...(options.body ? { "Content-Type": "application/json", "X-ReconForge-CSRF": session.csrfToken } : {}),
    },
    ...(options.body ? { body: JSON.stringify(options.body) } : {}),
  });
  if (!response.ok) {
    let code = `http_${response.status}`;
    try {
      const body: unknown = await response.json();
      if (isObject(body) && isObject(body.error) && isText(body.error.code)) code = body.error.code;
    } catch {
      // Retain the status-code fallback when a proxy returned no safe API envelope.
    }
    throw new AdminApiError(response.status, code);
  }
  try {
    return await response.json();
  } catch {
    invalid();
  }
}

export async function loadExceptionReviewIdentity(
  session: BrowserAdminSession,
  signal?: AbortSignal,
): Promise<ExceptionReviewIdentity> {
  return parseIdentity(await apiFetch(session, "", authMePath, { signal }));
}

export async function loadExceptionReviewList(
  session: BrowserAdminSession,
  workspace: string,
  filters: ExceptionReviewFilters = {},
  cursor?: string,
  limit = 25,
  signal?: AbortSignal,
): Promise<ExceptionReviewListPage> {
  const selectedWorkspace = scopeValue(workspace);
  const search = new URLSearchParams({ limit: String(pageLimit(limit)) });
  const values: Array<[string, string | undefined]> = [
    ["risk", filters.risk], ["status", filters.status], ["owner", filters.owner], ["period", filters.period],
    ["entity", filters.entity], ["account", filters.account], ["control", filters.control], ["cursor", cursorValue(cursor)],
  ];
  for (const [key, value] of values) if (value?.trim()) search.set(key, value.trim());
  const payload = await apiFetch(session, selectedWorkspace, `${root}?${search.toString()}`, { signal });
  return parseExceptionReviewListPage(payload, selectedWorkspace);
}

export async function loadExceptionReviewDetail(
  session: BrowserAdminSession,
  workspace: string,
  exceptionId: string,
  historyCursor?: string,
  historyLimit = 25,
  signal?: AbortSignal,
): Promise<ExceptionReviewDetail> {
  const selectedWorkspace = scopeValue(workspace);
  const id = scopeValue(exceptionId, 200);
  const search = new URLSearchParams({ history_limit: String(pageLimit(historyLimit)) });
  const cursor = cursorValue(historyCursor);
  if (cursor) search.set("history_cursor", cursor);
  const payload = await apiFetch(session, selectedWorkspace, `${root}/${encodeURIComponent(id)}?${search.toString()}`, { signal });
  if (!isObject(payload) || !Object.hasOwn(payload, "exception") || Object.keys(payload).length !== 1) invalid();
  const detail = parseExceptionReviewDetail(payload.exception);
  if (detail.id !== id || detail.workspace_id !== selectedWorkspace || detail.history.some((item) => item.exception_id !== id)) invalid();
  return detail;
}

async function mutateExceptionReview(
  session: BrowserAdminSession,
  workspace: string,
  exceptionId: string,
  suffix: "assign" | "status",
  body: Record<string, unknown>,
): Promise<ExceptionReviewDetail> {
  const selectedWorkspace = scopeValue(workspace);
  const id = scopeValue(exceptionId, 200);
  const payload = await apiFetch(session, selectedWorkspace, `${root}/${encodeURIComponent(id)}/${suffix}`, { body });
  if (!isObject(payload) || !Object.hasOwn(payload, "exception") || Object.keys(payload).length !== 1) invalid();
  const detail = parseExceptionReviewDetail(payload.exception);
  if (detail.id !== id || detail.workspace_id !== selectedWorkspace) invalid();
  return detail;
}

export async function assignExceptionReview(
  session: BrowserAdminSession,
  workspace: string,
  exceptionId: string,
  owner: string,
  expectedVersion: number,
): Promise<ExceptionReviewDetail> {
  const reviewer = scopeValue(owner);
  return mutateExceptionReview(session, workspace, exceptionId, "assign", {
    owner: reviewer,
    expected_version: positiveInteger(expectedVersion, Number.MAX_SAFE_INTEGER),
  });
}

export async function transitionExceptionReview(
  session: BrowserAdminSession,
  workspace: string,
  exceptionId: string,
  status: ExceptionReviewStatus,
  expectedVersion: number,
  reason = "",
): Promise<ExceptionReviewDetail> {
  if (!statuses.has(status) || reason.length > 1_000) invalid();
  return mutateExceptionReview(session, workspace, exceptionId, "status", {
    status,
    expected_version: positiveInteger(expectedVersion, Number.MAX_SAFE_INTEGER),
    reason,
  });
}
