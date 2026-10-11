import { manufacturingCanonical } from "./manufacturing-execution-data";
const hash = async (value: unknown) => [...new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(manufacturingCanonical(value))))].map(v => v.toString(16).padStart(2, "0")).join("");
export async function manufacturingFixture(phase = 0) {
  const body = { workspace_id: "work", organization_id: "org", legal_entity_id: "entity", schema_version: "manufacturing-order-v1", id: "ME1-" + "A".repeat(32), number: "WORK-1", creator_id: "maker", output_quantity_scaled: "10", currency_code: "USD", monetary_policy: { precision: 2 } };
  const source_digest = await hash(body);
  const issue_plan = phase ? { source_digest, total_cost_minor: "9000000000000000000", preparer_actor_id: "maker", entry: { entry_id: "entry-issue" } } : null;
  return { ...body, source_digest, phase, issue_plan, issue_digest: issue_plan ? await hash(issue_plan) : null, issue_reviewer_id: phase >= 2 ? "checker" : null, issue_effect_id: phase >= 3 ? "effect-issue" : null, valuation_id: phase >= 3 ? "valuation" : null, disposed_quantity_scaled: "0", released_cost_minor: "0", completions: [] };
}
export async function manufacturingCompletionFixture(phase = 1, quantity = "10", cost = "9000000000000000000", identity = "B") {
  const order = await manufacturingFixture(3), id = "ME1C-" + identity.repeat(32);
  const native = { plan_id: "IRP-output", source: { number: id, total_value_minor: cost } }, receipt_plan = { ...native, plan_digest: await hash(native) };
  const body = { workspace_id: "work", organization_id: "org", legal_entity_id: "entity", schema_version: "manufacturing-completion-v1", id, order_id: order.id, order_digest: order.source_digest, issue_digest: order.issue_digest, preparer_actor_id: "maker", good_quantity_scaled: quantity, scrap_quantity_scaled: "0", stage_quantity_scaled: quantity, good_cost_minor: cost, scrap_cost_minor: "0", released_cost_minor: cost, disposed_before_scaled: "0", released_before_minor: "0", wip_after_minor: (9000000000000000000n - BigInt(cost)).toString(), receipt_plan };
  const nativeEffect = { plan_id: receipt_plan.plan_id, plan_digest: receipt_plan.plan_digest, effect_id: "effect-output", posted_actor_id: "poster" };
  return { ...body, source_digest: await hash(body), phase, reviewer_id: "checker", receipt_effect: phase === 2 ? { ...nativeEffect, effect_digest: await hash(nativeEffect) } : null, scrap_effect_id: null };
}
