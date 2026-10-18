export const peopleScope = { workspace_id: "work", organization_id: "org", legal_entity_id: "entity" };
function ordered(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(ordered);
  if (value !== null && typeof value === "object") return Object.fromEntries(Object.entries(value).sort(([a], [b]) => a.localeCompare(b, "en")).map(([key, item]) => [key, ordered(item)]));
  return value;
}
async function seal(value: unknown): Promise<string> {
  const bytes = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(JSON.stringify(ordered(value))));
  return [...new Uint8Array(bytes)].map(byte => byte.toString(16).padStart(2, "0")).join("");
}
function response(value: unknown, key = ""): unknown {
  if (Array.isArray(value)) return value.map(item => response(item));
  if (value !== null && typeof value === "object") return Object.fromEntries(Object.entries(value).map(([field, item]) => [field, response(item, ["project_minor", "employees_minor"].includes(key) ? "amount_minor" : field)]));
  return typeof value === "number" && key.endsWith("_minor") ? String(value) : value;
}
export async function peoplePlanFixture(phase = 0): Promise<Record<string, unknown>> {
  const id = "HC1-" + "a".repeat(32), policy = { currency_code: "USD", currency_precision: 2, currency_rounding_policy: "ROUND_HALF_UP", currency_registry_version: "synthetic-v1", currency_registry_digest: "b".repeat(64) };
  const snapshot = { schema_version: "finance-entry-review-v1", entry: { id: "native-entry", ...peopleScope, entry_number: id.toUpperCase(), external_reference: id, preparer_actor_id: "maker", period_id: "period", posting_date: "2026-10-03", ...policy }, lines: [{ line_number: 1, account_id: "labor", debit_minor: 2501, credit_minor: 0, dimensions: { PROJECT: "P1" } }, { line_number: 2, account_id: "wages", debit_minor: 0, credit_minor: 2501, dimensions: {} }] };
  const validation = await seal(snapshot), privateValue = { contract_version: "people-project-payroll-v1", gross_minor: 2501, project_minor: { P1: 1268, P2: 1233 }, employees: [{ employee_id: "E1", gross_minor: 1502, project_minor: { P1: 1018, P2: 484 } }, { employee_id: "E2", gross_minor: 999, project_minor: { P1: 250, P2: 749 } }] };
  const payload = { schema_version: "people-payrun-v1", id, ...peopleScope, entry_id: "native-entry", amount_minor: 2501, project_minor: { P1: 1268, P2: 1233 }, monetary_policy: policy, earnings_rounding: "HALF_EVEN", validation_digest: validation, preparer_id: "maker", private: privateValue };
  const digest = await seal(payload);
  return response({ ...payload, plan_digest: digest, phase, status: ["Prepared", "Reviewed", "Posted", "Cancelled"][phase], reviewer_id: phase === 0 ? null : "checker", posted_actor_id: phase === 2 ? "poster" : null, posting_effect_id: phase === 2 ? "native-effect" : null,
    native_effect: phase === 2 ? { id: "native-effect", ...peopleScope, entry_id: "native-entry", posted_actor_id: "poster", validation_digest: validation, source_kind: "Manual", reverses_effect_id: null, snapshot } : null }) as Record<string, unknown>;
}
