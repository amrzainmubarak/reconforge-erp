import { financeRequest, type FinanceScope } from "./enterprise-finance-data";
import type { PreparedScopedCommand } from "./scoped-command";
import type { BrowserAdminSession } from "./types";

export const peopleRoot = "/api/v1/people-project-payroll";
export interface PeoplePlan extends FinanceScope {
  id: string; schema_version: "people-payrun-v1" | "people-payment-v1"; entry_id: string;
  phase: 0 | 1 | 2 | 3; amount_minor: string; plan_digest: string; validation_digest: string;
  preparer_id: string; reviewer_id: string | null; posted_actor_id: string | null; posting_effect_id: string | null;
  private: Record<string, unknown>; monetary_policy: { currency_code: string; currency_precision: number };
  native_effect: Record<string, unknown> | null;
  project_minor?: Record<string, string>;
}
export const object = (value: unknown): value is Record<string, unknown> => value !== null && typeof value === "object" && !Array.isArray(value);
const minor = (value: unknown): value is string => typeof value === "string" && /^(0|[1-9]\d{0,18})$/.test(value) && BigInt(value) <= 9000000000000000000n;
const digest = (value: unknown) => typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
function invalid(): never { throw new Error("people_source_invalid"); }

function canonical(value: unknown, key = ""): string {
  if (key.endsWith("_minor") && minor(value)) return value;
  if (Array.isArray(value)) return `[${value.map(item => canonical(item)).join(",")}]`;
  if (object(value)) return `{${Object.keys(value).sort().map(field => `${JSON.stringify(field)}:${canonical(value[field], ["project_minor", "employees_minor"].includes(key) ? "amount_minor" : field)}`).join(",")}}`;
  if (value === null || typeof value === "string" || typeof value === "boolean" || typeof value === "number" && Number.isSafeInteger(value)) return JSON.stringify(value);
  return invalid();
}

export async function parsePeoplePlan(value: unknown, scope: FinanceScope): Promise<PeoplePlan> {
  if (!object(value) || !/^HC1P?-[a-f0-9]{32}$/.test(String(value.id)) || !digest(value.plan_digest) || !digest(value.validation_digest) ||
      ![0, 1, 2, 3].includes(Number(value.phase)) || typeof value.phase !== "number" || !minor(value.amount_minor) || BigInt(value.amount_minor) <= 0n ||
      !object(value.private) || !object(value.monetary_policy) || typeof value.monetary_policy.currency_code !== "string" ||
      !/^[A-Z]{3}$/.test(value.monetary_policy.currency_code) || !Number.isInteger(value.monetary_policy.currency_precision) ||
      Number(value.monetary_policy.currency_precision) < 0 || Number(value.monetary_policy.currency_precision) > 8) invalid();
  for (const [field, expected] of Object.entries(scope)) if (value[field] !== expected) invalid();
  const payment = String(value.id).startsWith("HC1P-");
  if (value.schema_version !== (payment ? "people-payment-v1" : "people-payrun-v1") || payment && value.phase === 3) invalid();
  if (typeof value.preparer_id !== "string" || !value.preparer_id) invalid();
  if ([1, 2].includes(value.phase) && (typeof value.reviewer_id !== "string" || value.reviewer_id === value.preparer_id)) invalid();
  if (value.phase === 0 && value.reviewer_id !== null || value.status !== ["Prepared", "Reviewed", "Posted", "Cancelled"][value.phase]) invalid();
  if (value.phase === 2 ? typeof value.posting_effect_id !== "string" || !value.posting_effect_id || typeof value.posted_actor_id !== "string" ||
      [value.preparer_id, value.reviewer_id].includes(value.posted_actor_id) : value.posting_effect_id !== null || value.posted_actor_id !== null) invalid();
  let sum = 0n;
  if (payment) {
    if (!object(value.private.employees_minor) || !minor(value.private.amount_minor)) invalid();
    for (const amount of Object.values(value.private.employees_minor)) { if (!minor(amount) || BigInt(amount) <= 0n) invalid(); sum += BigInt(amount); }
    if (sum !== BigInt(value.private.amount_minor)) invalid();
  } else {
    if (!object(value.project_minor) || !Array.isArray(value.private.employees) || !minor(value.private.gross_minor)) invalid();
    for (const amount of Object.values(value.project_minor)) { if (!minor(amount)) invalid(); sum += BigInt(amount); }
    const employees = new Set<string>(); let employeeSum = 0n;
    for (const employee of value.private.employees) {
      if (!object(employee) || typeof employee.employee_id !== "string" || employees.has(employee.employee_id) || !minor(employee.gross_minor) || !object(employee.project_minor)) invalid();
      employees.add(employee.employee_id); let allocated = 0n;
      for (const amount of Object.values(employee.project_minor)) { if (!minor(amount)) invalid(); allocated += BigInt(amount); }
      if (allocated !== BigInt(employee.gross_minor)) invalid(); employeeSum += allocated;
    }
    if (employeeSum !== sum || sum !== BigInt(value.private.gross_minor)) invalid();
  }
  if (sum !== BigInt(value.amount_minor)) invalid();
  const excluded = new Set(["phase", "status", "reviewer_id", "posted_actor_id", "posting_effect_id", "plan_digest", "native_effect"]);
  const sealed = Object.fromEntries(Object.entries(value).filter(([key]) => !excluded.has(key)));
  const hash = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(canonical(sealed)));
  if ([...new Uint8Array(hash)].map(byte => byte.toString(16).padStart(2, "0")).join("") !== value.plan_digest) invalid();
  if (value.phase === 2) {
    const effect = value.native_effect;
    if (!object(effect) || effect.id !== value.posting_effect_id || effect.entry_id !== value.entry_id || effect.posted_actor_id !== value.posted_actor_id ||
        effect.validation_digest !== value.validation_digest || effect.source_kind !== "Manual" || effect.reverses_effect_id !== null || !object(effect.snapshot) ||
        !object(effect.snapshot.entry) || effect.snapshot.entry.id !== value.entry_id || effect.snapshot.entry.external_reference !== value.id) invalid();
    for (const [field, expected] of Object.entries(scope)) if (effect.snapshot.entry[field] !== expected || effect[field] !== expected) invalid();
    const reviewHash = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(canonical(effect.snapshot)));
    if ([...new Uint8Array(reviewHash)].map(byte => byte.toString(16).padStart(2, "0")).join("") !== value.validation_digest) invalid();
  } else if (value.native_effect !== null) invalid();
  return value as unknown as PeoplePlan;
}

export function peopleRequest(session: BrowserAdminSession, scope: FinanceScope, path: string, command?: PreparedScopedCommand, signal?: AbortSignal) {
  return financeRequest(session, scope, path, command?.body, signal);
}
