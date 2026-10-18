import type { PartialReturnBalance, PartialReturnPlan } from "./customer-partial-returns-data";

export const partialScope = { workspace_id: "work", organization_id: "org", legal_entity_id: "entity" };
const policy = { currency_code: "USD", currency_precision: 2, currency_rounding_policy: "ROUND_HALF_UP" as const, currency_registry_version: "synthetic-v1", currency_registry_digest: "c".repeat(64) };
export function partialBalanceFixture(overrides: Partial<PartialReturnBalance> = {}): PartialReturnBalance {
  return { ...partialScope, ...policy, source_order_id: "stock-original", source_id: "CRS2-" + "b".repeat(32), source_fingerprint: "f".repeat(64), history_fingerprint: "e".repeat(64), history_version: 1,
    gross_minor: "67500", collected_minor: "10000", credited_minor: "54000", returned_quantity_scaled: "12", remaining_quantity_scaled: "3", quantity_precision: 0,
    refund_entitlement_minor: "0", refunded_minor: "0", refund_due_minor: "0", outstanding_minor: "3500", active_plan_id: null, ...overrides };
}
export function partialPlanFixture(phase: 0 | 1 | 2 | 3 = 1, operation: PartialReturnPlan["operation"] = "Return"): PartialReturnPlan {
  const merchandise = operation === "Return" || operation === "ReverseReturn", prefix = { Return: "CR2", Refund: "CRF2", ReverseReturn: "CR2R", ReverseRefund: "CRF2R" }[operation];
  return { ...partialScope, ...policy, schema_version: "customer-partial-return-v1", id: prefix + "-" + "a".repeat(32), operation, phase, status: ["Prepared", "Reviewed", "Posted", "Cancelled"][phase] as PartialReturnPlan["status"],
    plan_digest: "d".repeat(64), source_id: "CRS2-" + "b".repeat(32), source_order_id: "stock-original", invoice_id: "invoice-original", quantity_precision: 0,
    quantity_scaled: merchandise ? "12" : "0", credit_minor: merchandise ? "54000" : "0", cogs_restored_minor: merchandise ? "16000" : "0", receivable_released_minor: merchandise ? "54000" : "0",
    refund_entitlement_delta_minor: "0", amount_minor: merchandise ? "70000" : "10000", expected_history_version: 0, posting_date: "2026-10-15", period_id: "period",
    preparer_actor_id: "maker", reviewer_actor_id: phase ? "checker" : null, poster_actor_id: phase === 2 ? "poster" : null,
    original_id: operation === "Return" ? null : (operation === "ReverseRefund" ? "CRF2-" : "CR2-") + "a".repeat(32),
    entries: ({ Return: ["RevenueCredit", "CostRestoration"], Refund: ["Refund"], ReverseReturn: ["ReverseRevenueCredit", "ReverseCostRestoration"], ReverseRefund: ["ReverseRefund"] }[operation]).map((purpose, i) => ({ entry_id: "entry-" + i, purpose, validation_digest: "8".repeat(64), posting_effect_id: phase === 2 ? "effect-" + i : null })), audit_event_id: "audit-native", outbox_event_id: "outbox-native" };
}
