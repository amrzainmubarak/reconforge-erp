import { manufacturingCanonical } from "./manufacturing-execution-data";
export async function manufacturingFixture(phase = 0) {
  const body = { workspace_id: "work", organization_id: "org", legal_entity_id: "entity", schema_version: "manufacturing-order-v1", id: "ME1-" + "A".repeat(32), number: "WORK-1", creator_id: "maker", output_quantity_scaled: "10", currency_code: "USD", monetary_policy: { precision: 2 } };
  const hash = async (value: unknown) => [...new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(manufacturingCanonical(value))))].map(v => v.toString(16).padStart(2, "0")).join("");
  const source_digest = await hash(body);
  const issue_plan = phase ? { source_digest, total_cost_minor: "9000000000000000000", preparer_actor_id: "maker", entry: { entry_id: "entry-issue" } } : null;
  return { ...body, source_digest, phase, issue_plan, issue_digest: issue_plan ? await hash(issue_plan) : null, issue_reviewer_id: phase >= 2 ? "checker" : null, issue_effect_id: phase >= 3 ? "effect-issue" : null, valuation_id: phase >= 3 ? "valuation" : null, disposed_quantity_scaled: "0", released_cost_minor: "0", completions: [] };
}
