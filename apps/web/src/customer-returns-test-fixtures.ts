export const returnScope = { workspace_id: "work", organization_id: "org", legal_entity_id: "entity" };
function canonical(value: unknown, key = ""): string {
  if (key.endsWith("_minor")) return String(value);
  if (Array.isArray(value)) return `[${value.map(item => canonical(item)).join(",")}]`;
  if (value !== null && typeof value === "object") return `{${Object.keys(value).sort().map(k => `${JSON.stringify(k)}:${canonical((value as Record<string, unknown>)[k], k)}`).join(",")}}`;
  return JSON.stringify(value);
}
export function returnFixture(phase = 1) {
  const id = "CR1-" + "a".repeat(32), credit = "9007199254740993";
  const source = { ...returnScope, id, operation: "Return", source_order_id: "original-stock", invoice_id: "original-invoice", amount_minor: "9007199254752993",
    credit_minor: credit, cogs_restored_minor: "12000", receivable_released_minor: credit, refund_entitlement_minor: "0", preparer_actor_id: "maker",
    currency_code: "USD", currency_precision: 2, posting_date: "2026-10-10", period_id: "period", entries: ["COGS", "REVENUE"].map((role, index) => ({
      entry_id: "entry-" + index, original_effect_id: "original-" + role, validation_digest: "b".repeat(64), snapshot: {
        entry: { ...returnScope, id: "entry-" + index, external_reference: id }, lines: [
          { line_number: 1, account_id: role, debit_minor: index === 0 ? "12000" : credit, credit_minor: "0" },
          { line_number: 2, account_id: index === 0 ? "INVENTORY" : "AR", debit_minor: "0", credit_minor: index === 0 ? "12000" : credit },
        ],
      },
    })) };
  const raw = canonical(source);
  return { ...source, phase, status: ["Prepared", "Reviewed", "Posted", "Cancelled"][phase], plan_digest: "bac4962fb6819fe1c5943eb9c5622378e264c183c0a2c807c2ed0bf95bc147ce", canonical_plan_json: raw,
    reviewer_actor_id: phase ? "checker" : null, posted_actor_id: phase === 2 ? "poster" : null, cancelled_actor_id: phase === 3 ? "poster" : null,
    cancellation_reason: phase === 3 ? "Release original claim" : null, posting_effect_ids: phase === 2 ? ["effect-C", "effect-R"] : [],
    evidence: { prepared_audit_event_id: "audit-prepared", prepared_outbox_event_id: "outbox-prepared", review_audit_event_id: phase ? "audit-review" : null,
      review_outbox_event_id: phase ? "outbox-review" : null, post_audit_event_id: phase === 2 ? "audit-post" : null, post_outbox_event_id: phase === 2 ? "outbox-post" : null,
      cancel_audit_event_id: phase === 3 ? "audit-cancel" : null, cancel_outbox_event_id: phase === 3 ? "outbox-cancel" : null } };
}
