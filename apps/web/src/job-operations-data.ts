import { AdminApiError } from "./data";
import type { BrowserAdminSession } from "./types";

export const jobStatuses = ["queued", "running", "paused", "retrying", "failed", "completed", "cancelled"] as const;
export type JobStatus = typeof jobStatuses[number];
export interface JobScope { workspaceId: string; organizationId: string; entityId: string }
export interface OperatorJob {
  id: string; version: number; status: JobStatus; tenant_id: string; workspace_id: string; organization_id: string; entity_id: string;
  completed_units: number; total_units: number; retry_count: number; retry_ceiling: number; safe_error_code: string;
  created_at: string; updated_at: string; started_at: string; completed_at: string;
}
export interface JobTransition { job_version: number; from_status: string; to_status: JobStatus; actor_id: string; occurred_at: string; reason_code: string }
export interface JobDetail { job: OperatorJob; transitions: JobTransition[]; history_truncated: boolean }
export interface JobPage { records: OperatorJob[]; next_after_id: string }
const root = "/api/v1/ops/durable-jobs";
const object = (value: unknown): value is Record<string, unknown> => typeof value === "object" && value !== null && !Array.isArray(value);
const identifier = (value: unknown): value is string => typeof value === "string" && /^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,159}$/.test(value);
const count = (value: unknown): value is number => typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
const timestamp = (value: unknown): value is string => typeof value === "string" && /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$/.test(value) && Number.isFinite(Date.parse(value));
const closed = (value: Record<string, unknown>, fields: string[]) => Object.keys(value).length === fields.length && fields.every((key) => key in value);
function invalid(): never { throw new Error("job_operations_contract_invalid"); }

export function parseOperatorJob(value: unknown, session: BrowserAdminSession, scope: JobScope): OperatorJob {
  const fields = ["id", "version", "status", "tenant_id", "workspace_id", "organization_id", "entity_id", "completed_units", "total_units", "retry_count", "retry_ceiling", "safe_error_code", "created_at", "updated_at", "started_at", "completed_at"];
  if (!object(value) || !closed(value, fields) || !identifier(value.id) || !count(value.version) || value.version < 1 || !jobStatuses.includes(value.status as JobStatus) ||
      value.tenant_id !== session.tenantId || value.workspace_id !== scope.workspaceId || value.organization_id !== scope.organizationId || value.entity_id !== scope.entityId ||
      !["completed_units", "total_units", "retry_count", "retry_ceiling"].every((key) => count(value[key])) || Number(value.completed_units) > Number(value.total_units) || Number(value.retry_count) > Number(value.retry_ceiling) ||
      typeof value.safe_error_code !== "string" || !/^(?:|[A-Z][A-Z0-9_]{0,63})$/.test(value.safe_error_code) || !timestamp(value.created_at) || !timestamp(value.updated_at) || Date.parse(value.updated_at) < Date.parse(value.created_at) ||
      !["started_at", "completed_at"].every((key) => value[key] === "" || timestamp(value[key]))) invalid();
  return value as unknown as OperatorJob;
}

function parseTransition(value: unknown): JobTransition {
  const fields = ["job_version", "from_status", "to_status", "actor_id", "occurred_at", "reason_code"];
  if (!object(value) || !closed(value, fields) || !count(value.job_version) || value.job_version < 1 ||
      !(value.from_status === "" || jobStatuses.includes(value.from_status as JobStatus)) || !jobStatuses.includes(value.to_status as JobStatus) || !identifier(value.actor_id) || !timestamp(value.occurred_at) ||
      typeof value.reason_code !== "string" || !/^[A-Z][A-Z0-9_]{0,63}$/.test(value.reason_code)) invalid();
  return value as unknown as JobTransition;
}

function validateScope(scope: JobScope): void {
  if (!identifier(scope.workspaceId) || !identifier(scope.entityId) || !(scope.organizationId === "" || identifier(scope.organizationId))) invalid();
}

async function jobFetch(session: BrowserAdminSession, scope: JobScope, path: string, options: { body?: object; signal?: AbortSignal } = {}): Promise<unknown> {
  validateScope(scope);
  const query = new URLSearchParams({ tenant_id: session.tenantId, workspace_id: scope.workspaceId, organization_id: scope.organizationId, entity_id: scope.entityId });
  const response = await fetch(`${root}${path}${path.includes("?") ? "&" : "?"}${query}`, {
    method: options.body ? "POST" : "GET", credentials: "same-origin", cache: "no-store", signal: options.signal,
    headers: { Accept: "application/json", "X-ReconForge-Tenant": session.tenantId, "X-ReconForge-Workspace": scope.workspaceId,
      ...(scope.organizationId ? { "X-ReconForge-Organization": scope.organizationId } : {}), "X-ReconForge-Legal-Entity": scope.entityId,
      ...(options.body ? { "Content-Type": "application/json", "X-ReconForge-CSRF": session.csrfToken } : {}) },
    ...(options.body ? { body: JSON.stringify(options.body) } : {}),
  });
  if (!response.ok) {
    let code = `http_${response.status}`;
    try { const error: unknown = await response.json(); if (object(error) && object(error.error) && typeof error.error.code === "string") code = error.error.code; } catch { /* Keep the bounded HTTP code. */ }
    throw new AdminApiError(response.status, code);
  }
  return response.json();
}

export async function loadJobPage(session: BrowserAdminSession, scope: JobScope, status: JobStatus | "", afterId = "", signal?: AbortSignal): Promise<JobPage> {
  if ((status && !jobStatuses.includes(status)) || (afterId && !identifier(afterId))) invalid();
  const query = new URLSearchParams({ after_id: afterId, limit: "25", ...(status ? { status } : {}) });
  const value = await jobFetch(session, scope, `?${query}`, { signal });
  if (!object(value) || !closed(value, ["records", "next_after_id"]) || !Array.isArray(value.records) || value.records.length > 25 || !(value.next_after_id === "" || identifier(value.next_after_id))) invalid();
  const records = value.records.map((record) => parseOperatorJob(record, session, scope));
  if (new Set(records.map((record) => record.id)).size !== records.length || records.some((record, index) => record.id <= (index ? records[index - 1].id : afterId) || (status && record.status !== status)) ||
      (value.next_after_id && (records.length !== 25 || value.next_after_id !== records.at(-1)?.id))) invalid();
  return { records, next_after_id: String(value.next_after_id) };
}

export async function loadJobDetail(session: BrowserAdminSession, scope: JobScope, id: string, signal?: AbortSignal): Promise<JobDetail> {
  if (!identifier(id)) invalid();
  const value = await jobFetch(session, scope, `/${encodeURIComponent(id)}`, { signal });
  if (!object(value) || !closed(value, ["job", "transitions", "history_truncated"]) || !Array.isArray(value.transitions) || value.transitions.length > 200 || typeof value.history_truncated !== "boolean") invalid();
  const job = parseOperatorJob(value.job, session, scope), transitions = value.transitions.map(parseTransition);
  if (job.id !== id || !transitions.length || transitions.some((event, index) => event.job_version > job.version || (index && event.job_version !== transitions[index - 1].job_version + 1)) ||
      transitions.at(-1)?.job_version !== job.version || transitions.at(-1)?.to_status !== job.status) invalid();
  return { job, transitions, history_truncated: value.history_truncated };
}

export async function commandJob(session: BrowserAdminSession, scope: JobScope, job: OperatorJob, action: "cancel" | "requeue"): Promise<OperatorJob> {
  parseOperatorJob(job, session, scope);
  if (!["cancel", "requeue"].includes(action)) invalid();
  const value = await jobFetch(session, scope, `/${encodeURIComponent(job.id)}/${action}`, { body: { expected_version: job.version } });
  if (!object(value) || !closed(value, ["job"])) invalid();
  const result = parseOperatorJob(value.job, session, scope);
  if (result.id !== job.id || result.version !== job.version + 1 || result.status !== (action === "cancel" ? "cancelled" : "queued")) invalid();
  return result;
}
