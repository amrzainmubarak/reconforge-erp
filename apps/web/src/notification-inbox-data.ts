import { AdminApiError } from "./data";
import type { BrowserAdminSession } from "./types";

export const inboxTopics = ["workflow.review_required", "job.failed", "control.exception_opened", "evidence.available"] as const;
export type InboxTopic = typeof inboxTopics[number];
export interface InboxNotification {
  id: string; workspace_id: string; organization_id: string; legal_entity_id: string; recipient_id: string;
  topic: InboxTopic; resource_type: string; resource_id: string; payload_digest: string; created_at: string; read_at: string | null;
}
export interface InboxPage { records: InboxNotification[]; total: number; unread_count: number }
const root = "/api/v1/notifications";
const object = (value: unknown): value is Record<string, unknown> => typeof value === "object" && value !== null && !Array.isArray(value);
const identifier = (value: unknown): value is string => typeof value === "string" && /^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$/.test(value);
const timestamp = (value: unknown): value is string => typeof value === "string" && /^\d{4}-\d\d-\d\dT.+(?:Z|\+00:00)$/.test(value) && Number.isFinite(Date.parse(value));
const timestampOrder = (createdAt: unknown, readAt: unknown): boolean => typeof createdAt === "string" && (readAt === null || (typeof readAt === "string" && Date.parse(readAt) >= Date.parse(createdAt)));
const count = (value: unknown): value is number => typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
function invalid(): never { throw new Error("inbox_contract_invalid"); }

export function parseInboxNotification(value: unknown): InboxNotification {
  const fields = ["id", "workspace_id", "organization_id", "legal_entity_id", "recipient_id", "topic", "resource_type", "resource_id", "payload_digest", "created_at", "read_at"];
  if (!object(value) || Object.keys(value).length !== fields.length || !fields.every((field) => field in value) || !["id", "workspace_id", "recipient_id", "resource_type", "resource_id"].every((key) => identifier(value[key])) ||
    !(value.organization_id === "" || identifier(value.organization_id)) || !(value.legal_entity_id === "" || identifier(value.legal_entity_id)) ||
    (value.legal_entity_id !== "" && value.organization_id === "") || !inboxTopics.includes(value.topic as InboxTopic) ||
    typeof value.payload_digest !== "string" || !/^[a-f0-9]{64}$/.test(value.payload_digest) || !timestamp(value.created_at) || !(value.read_at === null || timestamp(value.read_at)) || !timestampOrder(value.created_at, value.read_at)) invalid();
  return value as unknown as InboxNotification;
}

export function parseInboxPage(value: unknown, workspace: string): InboxPage {
  if (!object(value) || !Array.isArray(value.records) || !count(value.total) || !count(value.unread_count) || value.records.length > 25 || value.records.length > value.total || value.unread_count > value.total) invalid();
  const records = value.records.map(parseInboxNotification);
  if (records.some((record) => record.workspace_id !== workspace) || new Set(records.map((record) => record.id)).size !== records.length || records.filter((record) => record.read_at === null).length > value.unread_count) invalid();
  return { records, total: value.total, unread_count: value.unread_count };
}

async function inboxFetch(session: BrowserAdminSession, path: string, workspace: string, options: { post?: boolean; signal?: AbortSignal } = {}): Promise<unknown> {
  if (!(path === `${root}/workspaces` || path.startsWith(`${root}/inbox`))) invalid();
  const response = await fetch(path, {
    method: options.post ? "POST" : "GET", credentials: "same-origin", cache: "no-store", signal: options.signal,
    headers: { Accept: "application/json", "X-ReconForge-Tenant": session.tenantId,
      ...(workspace ? { "X-ReconForge-Workspace": workspace } : {}),
      ...(options.post ? { "X-ReconForge-CSRF": session.csrfToken } : {}) },
  });
  if (!response.ok) {
    let code = `http_${response.status}`;
    try { const error: unknown = await response.json(); if (object(error) && object(error.error) && typeof error.error.code === "string") code = error.error.code; } catch { /* Retain the safe HTTP code. */ }
    throw new AdminApiError(response.status, code);
  }
  return response.json();
}

export async function loadInboxWorkspaces(session: BrowserAdminSession, signal?: AbortSignal): Promise<string[]> {
  const value = await inboxFetch(session, `${root}/workspaces`, "", { signal });
  if (!object(value) || !Array.isArray(value.workspaces) || !value.workspaces.every(identifier) || value.workspaces.length > 1000 || new Set(value.workspaces).size !== value.workspaces.length) invalid();
  return value.workspaces;
}

export async function loadInboxPage(session: BrowserAdminSession, workspace: string, offset: number, unreadOnly: boolean, signal?: AbortSignal): Promise<InboxPage> {
  if (!identifier(workspace) || !count(offset) || offset > 100_000) invalid();
  const query = new URLSearchParams({ workspace, offset: String(offset), limit: "25", unread_only: String(unreadOnly) });
  return parseInboxPage(await inboxFetch(session, `${root}/inbox?${query}`, workspace, { signal }), workspace);
}

export async function acknowledgeInbox(session: BrowserAdminSession, workspace: string, notification: InboxNotification): Promise<InboxNotification> {
  if (!identifier(workspace) || notification.workspace_id !== workspace) invalid();
  const value = parseInboxNotification(await inboxFetch(session, `${root}/inbox/${encodeURIComponent(notification.id)}/read?workspace=${encodeURIComponent(workspace)}`, workspace, { post: true }));
  if ((["id", "workspace_id", "organization_id", "legal_entity_id", "recipient_id", "topic", "resource_type", "resource_id", "payload_digest", "created_at"] as const).some((key) => value[key] !== notification[key]) || !value.read_at) invalid();
  return value;
}
