import original from "../../../tests/fixtures/project-time-billing-native-v1.json";

export const billingScope = { workspace_id: "work", organization_id: "org", legal_entity_id: "entity" };
function response(value: unknown, key = ""): unknown {
  if (Array.isArray(value)) return value.map(row => response(row));
  if (value !== null && typeof value === "object") return Object.fromEntries(Object.entries(value).map(([name, item]) => [name, response(item, key === "project_minor" ? "amount_minor" : name)]));
  return typeof value === "number" && key.endsWith("_minor") ? String(value) : value;
}
export function billingEvidenceFixture(): Record<string, unknown> { return response(structuredClone(original)) as Record<string, unknown>; }
export function billingPlanFixture(phase = 2, collection = false): Record<string, unknown> {
  const evidence = billingEvidenceFixture(), plan = structuredClone((collection ? (evidence.collections as Record<string, unknown>[])[0] : evidence.invoice) as Record<string, unknown>);
  plan.phase = phase; plan.status = ["Prepared", "Reviewed", "Posted", "Cancelled"][phase];
  if (phase === 0) plan.reviewer_id = null;
  if (phase !== 2) { plan.posted_actor_id = null; plan.posting_effect_id = null; plan.receipt_id = null; }
  return plan;
}
