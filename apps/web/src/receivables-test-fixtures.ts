import type { ArMonetaryPolicy } from "./receivables-money";

/** Synthetic retained-policy contract; never used as a production fallback. */
export function policyFor(currency_code = "USD", precision = 2): ArMonetaryPolicy {
  return { schema_version: 1, status: "captured", currency_code, precision, rounding_policy: "ROUND_HALF_UP", registry_version: "synthetic-v1", registry_digest: "a".repeat(64), policy_digest: "b".repeat(64), source: "Synthetic test registry", source_url: "", published_at: "" };
}
