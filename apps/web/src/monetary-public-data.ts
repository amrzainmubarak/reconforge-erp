import type { FinanceScope } from "./enterprise-finance-data";
import { formatExactDecimal } from "./locale-format";
import { isMonetaryPath } from "./monetary-paths";
import { salesRequest } from "./sales-revenue-data";
import { prepareScopedCommand, type PreparedScopedCommand, type ScopedJsonValue } from "./scoped-command";
import type { BrowserAdminSession, Locale } from "./types";

export interface MonetaryPolicy {
  currency_code: string; currency_precision: number; currency_rounding_policy: "ROUND_HALF_UP";
  currency_registry_version: string; currency_registry_digest: string;
}
export interface MonetaryRate { rate: string; source: string; effective_at: string }
export interface MonetaryBalanceFields {
  schema_version: string; history_version: number; history_fingerprint: string;
  transaction_original_gross_minor: string; functional_original_gross_minor: string;
  transaction_collected_minor: string; transaction_credited_minor: string; transaction_outstanding_minor: string; functional_outstanding_minor: string;
  transaction_refund_entitlement_minor: string; functional_refund_entitlement_minor: string;
  transaction_refunded_minor: string; functional_refund_released_minor: string; transaction_refund_due_minor: string; functional_refund_due_minor: string;
  active_plan_id: string | null; active_revaluation_plan_id: string | null;
}
export const monetaryPolicyFields = ["currency_code", "currency_precision", "currency_rounding_policy", "currency_registry_version", "currency_registry_digest"] as const;
export const monetaryBalanceFields = ["schema_version", "history_version", "history_fingerprint", "transaction_original_gross_minor", "functional_original_gross_minor",
  "transaction_collected_minor", "transaction_credited_minor", "transaction_outstanding_minor", "functional_outstanding_minor", "transaction_refund_entitlement_minor",
  "functional_refund_entitlement_minor", "transaction_refunded_minor", "functional_refund_released_minor", "transaction_refund_due_minor", "functional_refund_due_minor",
  "active_plan_id", "active_revaluation_plan_id"] as const;

export function monetaryInvalid(): never { throw new Error("monetary_response_invalid"); }
export function monetaryObject(value: unknown, fields: readonly string[]): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)
      || ![Object.prototype, null].includes(Object.getPrototypeOf(value))) monetaryInvalid();
  const row = value as Record<string, unknown>, descriptors = Object.getOwnPropertyDescriptors(row);
  if (Object.getOwnPropertySymbols(row).length || Object.keys(descriptors).length !== fields.length || fields.some(key => !Object.hasOwn(descriptors, key))
      || Object.entries(descriptors).some(([key, descriptor]) => !fields.includes(key) || !descriptor.enumerable || !("value" in descriptor))) monetaryInvalid();
  return { ...row };
}
export function monetaryText(value: unknown, maximum = 160): string {
  if (typeof value !== "string" || !value || value.length > maximum || value !== value.trim() || /[\x00-\x1f\x7f]/.test(value)) monetaryInvalid();
  return value;
}
export function monetaryNullableText(value: unknown): string | null { return value === null ? null : monetaryText(value); }
export function monetaryInteger(value: unknown, maximum: number, minimum = 0): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < minimum || value > maximum) monetaryInvalid();
  return value;
}
export function monetaryMinor(value: unknown, positive = false): string {
  if (typeof value !== "string" || !/^(0|[1-9][0-9]{0,18})$/.test(value)) monetaryInvalid();
  const amount = BigInt(value);
  if (amount > 9000000000000000000n || positive && amount === 0n) monetaryInvalid();
  return value;
}
export function monetaryDigest(value: unknown): string {
  if (typeof value !== "string" || !/^[a-f0-9]{64}$/.test(value)) monetaryInvalid();
  return value;
}
export function monetaryDate(value: unknown): string {
  if (typeof value !== "string" || !/^[0-9]{4}-[0-9]{2}-[0-9]{2}$/.test(value) || value.slice(0, 4) === "0000") monetaryInvalid();
  const day = new Date(value + "T00:00:00Z");
  if (!Number.isFinite(day.getTime()) || day.toISOString().slice(0, 10) !== value) monetaryInvalid();
  return value;
}
export function monetaryScope(row: Record<string, unknown>, scope: FinanceScope): void {
  for (const key of ["workspace_id", "organization_id", "legal_entity_id"] as const) if (monetaryText(row[key]) !== monetaryText(scope[key])) monetaryInvalid();
}
export function parseMonetaryPolicy(value: unknown): MonetaryPolicy {
  const row = monetaryObject(value, monetaryPolicyFields);
  if (!/^[A-Z]{3}$/.test(monetaryText(row.currency_code)) || row.currency_rounding_policy !== "ROUND_HALF_UP") monetaryInvalid();
  monetaryInteger(row.currency_precision, 8); monetaryText(row.currency_registry_version); monetaryDigest(row.currency_registry_digest);
  return row as unknown as MonetaryPolicy;
}
export function parseMonetaryPolicyPair(transaction: unknown, functional: unknown): [MonetaryPolicy, MonetaryPolicy] {
  const first = parseMonetaryPolicy(transaction), second = parseMonetaryPolicy(functional);
  if (first.currency_registry_version !== second.currency_registry_version || first.currency_registry_digest !== second.currency_registry_digest
      || first.currency_code === second.currency_code && monetaryPolicyFields.some(key => first[key] !== second[key])) monetaryInvalid();
  return [first, second];
}
export function monetaryDecimal(value: unknown, tax = false): string {
  if (typeof value !== "string" || !/^(0|[1-9][0-9]{0,11})(\.[0-9]{1,12})?$/.test(value)) monetaryInvalid();
  const [whole, part = ""] = value.split("."), scaled = BigInt(whole + part), base = 10n ** BigInt(part.length);
  if (tax ? scaled > base : scaled === 0n) monetaryInvalid();
  return value;
}
export function parseMonetaryRate(value: unknown, day: string, identity: boolean): MonetaryRate | null {
  if (identity) { if (value !== null) monetaryInvalid(); return null; }
  const row = monetaryObject(value, ["rate", "source", "effective_at"]);
  monetaryDecimal(row.rate); monetaryText(row.source, 200);
  const at = monetaryText(row.effective_at);
  if (!/^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$/.test(at) || at.slice(0, 10) !== monetaryDate(day)) monetaryInvalid();
  const date = new Date(at);
  if (!Number.isFinite(date.getTime()) || date.toISOString() !== at.replace("Z", ".000Z")) monetaryInvalid();
  return row as unknown as MonetaryRate;
}
export function validateMonetaryBalance(row: Record<string, unknown>, identity = false): void {
  monetaryInteger(row.history_version, 256); monetaryDigest(row.history_fingerprint);
  for (const key of monetaryBalanceFields.filter(key => key.endsWith("_minor"))) monetaryMinor(row[key]);
  monetaryNullableText(row.active_plan_id); monetaryNullableText(row.active_revaluation_plan_id);
  if (BigInt(row.transaction_original_gross_minor as string) <= 0n || BigInt(row.functional_original_gross_minor as string) <= 0n
      || BigInt(row.transaction_credited_minor as string) > BigInt(row.transaction_original_gross_minor as string)
      || BigInt(row.transaction_collected_minor as string) > BigInt(row.transaction_original_gross_minor as string)
      || BigInt(row.functional_refund_entitlement_minor as string) > BigInt(row.functional_original_gross_minor as string)
      || BigInt(row.transaction_refunded_minor as string) + BigInt(row.transaction_refund_due_minor as string) !== BigInt(row.transaction_refund_entitlement_minor as string)
      || BigInt(row.functional_refund_released_minor as string) + BigInt(row.functional_refund_due_minor as string) !== BigInt(row.functional_refund_entitlement_minor as string)) monetaryInvalid();
  const residual = BigInt(row.transaction_original_gross_minor as string) - BigInt(row.transaction_collected_minor as string) - BigInt(row.transaction_credited_minor as string);
  if (row.transaction_outstanding_minor !== (residual > 0n ? residual : 0n).toString() || row.transaction_refund_entitlement_minor !== (residual < 0n ? -residual : 0n).toString()
      || row.transaction_outstanding_minor === "0" && row.functional_outstanding_minor !== "0"
      || row.transaction_refund_due_minor === "0" && row.functional_refund_due_minor !== "0"
      || row.transaction_refund_entitlement_minor === "0" && row.functional_refund_entitlement_minor !== "0"
      || row.transaction_refunded_minor === "0" && row.functional_refund_released_minor !== "0") monetaryInvalid();
  if (identity && [["transaction_original_gross_minor", "functional_original_gross_minor"], ["transaction_outstanding_minor", "functional_outstanding_minor"],
    ["transaction_refund_entitlement_minor", "functional_refund_entitlement_minor"], ["transaction_refund_due_minor", "functional_refund_due_minor"],
    ["transaction_refunded_minor", "functional_refund_released_minor"]].some(([first, second]) => row[first] !== row[second])) monetaryInvalid();
}
export function monetaryMoney(value: string, policy: MonetaryPolicy, locale: Locale): string {
  monetaryMinor(value); const precision = monetaryInteger(policy.currency_precision, 8);
  const padded = value.padStart(precision + 1, "0");
  return `${formatExactDecimal(precision ? padded.slice(0, -precision) + "." + padded.slice(-precision) : padded, locale)} ${policy.currency_code}`;
}
export function prepareMonetaryCommand(path: string, body: Record<string, ScopedJsonValue>): PreparedScopedCommand {
  if (!isMonetaryPath(path, true)) monetaryInvalid();
  return prepareScopedCommand(path, body);
}
export async function monetaryRequest(session: BrowserAdminSession, scope: FinanceScope, path: string, command?: PreparedScopedCommand, signal?: AbortSignal): Promise<unknown> {
  if (!isMonetaryPath(path, Boolean(command)) || command && command.path !== path) monetaryInvalid();
  if (command) monetaryText(session.csrfToken);
  for (const value of Object.values(scope)) monetaryText(value);
  return salesRequest(session, scope, path, command?.body, signal);
}
