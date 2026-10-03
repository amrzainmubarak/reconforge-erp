import { formatExactDecimal } from "./locale-format";
import type { Locale } from "./types";

export const MAX_MINOR = 9_007_199_254_740_991n;
export type ArMinor = number | string;
export interface ArMonetaryPolicy {
  schema_version: 1; status: "captured" | "unverified"; currency_code: string;
  precision: number | null; rounding_policy: "ROUND_HALF_UP" | null;
  registry_version: string | null; registry_digest: string | null; policy_digest: string | null;
  source: string | null; source_url: string | null; published_at: string | null;
}
export interface ArMoneyRecord { currency_code: string; monetary_policy?: ArMonetaryPolicy }
const provenance = ["precision", "rounding_policy", "registry_version", "registry_digest", "policy_digest", "source", "source_url", "published_at"] as const;
const fields = ["schema_version", "status", "currency_code", ...provenance];
const digest = (value: unknown) => typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
const bounded = (value: unknown, limit: number) => typeof value === "string" && value.length <= limit;

/** Missing metadata from an older API remains unresolved, never today's currency scale. */
export function parseMonetaryPolicy(value: unknown, currency: string): ArMonetaryPolicy | undefined {
  if (value === undefined) return undefined;
  if (typeof value !== "object" || value === null || Array.isArray(value)) throw new Error("ar_contract_invalid");
  const policy = value as Record<string, unknown>;
  if (Object.keys(policy).length !== fields.length || fields.some((field) => !(field in policy)) || policy.schema_version !== 1 || policy.currency_code !== currency) throw new Error("ar_contract_invalid");
  if (policy.status === "unverified") {
    if (provenance.some((field) => policy[field] !== null)) throw new Error("ar_contract_invalid");
  } else if (policy.status !== "captured" || !/^[A-Z]{3}$/.test(currency) || typeof policy.precision !== "number" || !Number.isInteger(policy.precision) || policy.precision < 0 || policy.precision > 8 || policy.rounding_policy !== "ROUND_HALF_UP" || !bounded(policy.registry_version, 128) || policy.registry_version === "" || !digest(policy.registry_digest) || !digest(policy.policy_digest) || !bounded(policy.source, 500) || !bounded(policy.source_url, 2048) || !bounded(policy.published_at, 32)) throw new Error("ar_contract_invalid");
  return { ...policy } as unknown as ArMonetaryPolicy;
}

export function capturedPolicy(record: ArMoneyRecord): ArMonetaryPolicy & { precision: number } {
  const policy = parseMonetaryPolicy(record.monetary_policy, record.currency_code);
  if (!policy || policy.status !== "captured") throw new Error("ar_monetary_policy_unverified");
  return policy as ArMonetaryPolicy & { precision: number };
}

export function hasCapturedPolicy(record: ArMoneyRecord | null | undefined): boolean {
  return Boolean(record?.monetary_policy?.status === "captured");
}

export function requireMoneyAffinity(...records: ArMoneyRecord[]): void {
  const policies = records.map(capturedPolicy);
  const first = policies[0];
  if (policies.some((policy) => ["currency_code", "precision", "rounding_policy", "registry_version", "registry_digest", "policy_digest"].some((key) => policy[key as keyof ArMonetaryPolicy] !== first[key as keyof ArMonetaryPolicy]))) throw new Error("ar_monetary_policy_mismatch");
}

/** Major-unit input is exact; excess fractional digits are rejected, never rounded. */
export function majorToMinor(value: string, record: ArMoneyRecord): bigint {
  const { precision } = capturedPolicy(record);
  if (value.length > 32) throw new Error("ar_major_amount_invalid");
  const normalized = value.trim().replace(/[٠-٩]/g, (digit) => String(digit.charCodeAt(0) - 0x660)).replace(/[۰-۹]/g, (digit) => String(digit.charCodeAt(0) - 0x6f0)).replace(/٫/g, ".");
  if (!/^(0|[1-9]\d*)(?:\.\d+)?$/.test(normalized)) throw new Error("ar_major_amount_invalid");
  const [whole, fraction = ""] = normalized.split(".");
  if (fraction.length > precision) throw new Error("ar_major_amount_invalid");
  const minor = BigInt(whole + fraction.padEnd(precision, "0"));
  if (minor > MAX_MINOR) throw new Error("ar_major_amount_invalid");
  return minor;
}

export function minorToMajorText(value: ArMinor | bigint, record: ArMoneyRecord): string {
  const { precision } = capturedPolicy(record);
  if (typeof value === "number" && !Number.isSafeInteger(value)) throw new Error("ar_contract_invalid");
  if (typeof value === "string" && !/^-?(0|[1-9]\d{0,127})$/.test(value)) throw new Error("ar_contract_invalid");
  const amount = BigInt(value), negative = amount < 0n;
  const digits = String(negative ? -amount : amount).padStart(precision + 1, "0");
  return `${negative ? "-" : ""}${precision ? `${digits.slice(0, -precision)}.${digits.slice(-precision)}` : digits}`;
}

export function formatArMoney(value: ArMinor | bigint, record: ArMoneyRecord, locale: Locale, minorLabel: string): string {
  if (typeof value === "number" && !Number.isSafeInteger(value)) throw new Error("ar_contract_invalid");
  const captured = hasCapturedPolicy(record);
  const exact = captured ? minorToMajorText(value, record) : String(value);
  return `${formatExactDecimal(exact, locale)} ${record.currency_code}${captured ? "" : ` · ${minorLabel}`}`;
}
