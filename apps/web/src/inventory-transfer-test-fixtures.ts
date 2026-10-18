/** Synthetic protocol fixtures for consumer tests; never browser seed documents. */
import { transferDigest, type TransferSource } from "./inventory-transfer-data";
import type { PreparedScopedCommand } from "./scoped-command";
export const transferScope = { workspace_id: "work", organization_id: "org", legal_entity_id: "entity" };
export const transferBody = { number: "T-1", item_code: "ITEM", quantity: "1", from_location: "MAIN/STOCK", to_location: "SECOND/STOCK", period_id: "period", posting_date: "2026-10-14", reason: "Original source transfer" };
export async function transferFixture(reviewed = false): Promise<TransferSource> {
  const policy = { currency_code: "USD", currency_precision: 2, currency_rounding_policy: "ROUND_HALF_UP", currency_registry_version: "original-registry", currency_registry_digest: "a".repeat(64) };
  const cost = { schema_version: "inventory-transfer-cost-v1", monetary_policy: policy, remaining_quantity_scaled: "3", remaining_value_minor: "3600", sources: [{
    layer: { tenant_id: "synthetic", id: "original-layer", item_id: "item", uom_id: "uom", source_valuation_line_id: "original-valuation-line", original_quantity_scaled: "3", original_value_minor: "3600", remaining_quantity_scaled: "3", remaining_value_minor: "3600" },
    receipt_plan: { plan_id: "original-receipt", operation: "Receipt", scope: transferScope, currency_policy: policy },
    receipt_link: { cost_layer_id: "original-layer", plan_id: "original-receipt" }, valuation_document: { status: "Approved", total_value_minor: "3600" },
    valuation_line: { id: "original-valuation-line", flow_direction: "Inbound", quantity_scaled: "3", value_minor: "3600" },
    finance_entry: { id: "original-entry", status: "Validated", total_debit_minor: "3600", total_credit_minor: "3600" },
    finance_lines: [{ debit_minor: "3600", credit_minor: "0" }, { debit_minor: "0", credit_minor: "3600" }],
    posting_effect: { entry_id: "original-entry", source_id: "original-receipt" }, consumptions: [], exposed_amounts_minor: ["3600", "3600"],
  }] };
  const id = "IT1-S-" + "A".repeat(32), nativeId = "native-movement";
  const base = { schema_version: "inventory-transfer-v1", ...transferBody, id, scope: transferScope, creator_actor_id: "maker", item_id: "item", uom_id: "uom",
    quantity_precision: 0, quantity_scaled: "1", inventory_account_id: "inventory-account", organization_code: "ORG", entity_code: "ENTITY",
    from_location_id: "source-location", to_location_id: "destination-location", native_movement_id: nativeId,
    cost_snapshot: cost, command_request: { schema_version: "inventory-transfer-v1", ...transferBody, scope: transferScope }, original: null };
  return { ...base, source_digest: await transferDigest(base, true), phase: reviewed ? 1 : 0, row_version: reviewed ? 2 : 1,
    reviewer_actor_id: reviewed ? "checker" : null, poster_actor_id: null, review_cost_snapshot: reviewed ? structuredClone(cost) : null,
    review_cost_digest: reviewed ? await transferDigest(cost, true) : null,
    claim: reviewed ? { tenant_id: "synthetic", id: "IT1-K-" + "B".repeat(32), transfer_id: id, ...transferScope, item_id: "item", uom_id: "uom", quantity_precision: 0,
      location_id: "source-location", quantity_scaled: "1", state: "Active", created_version: 2 } : null, release: null,
    native_response: { head: { tenant_id: "synthetic", id: nativeId, ...transferScope, source_reference: id, movement_number: "IT1-" + "A".repeat(32), movement_type: "Transfer",
      source_type: "Generated", status: "Draft", row_version: 1, created_by: "maker", description: transferBody.reason, period_id: "period", movement_date: transferBody.posting_date },
    lines: [{ tenant_id: "synthetic", id: "native-original-line", movement_id: nativeId, item_id: "item", uom_id: "uom", inventory_lot_id: null, quantity_precision: 0, quantity_scaled: "1", line_number: 1,
      from_location_id: "source-location", to_location_id: "destination-location" }], audit: [], outbox: [] },
  } as TransferSource;
}
export async function transferAck(source: TransferSource, command: PreparedScopedCommand, actorId = "checker") {
  const body = Object.fromEntries(Object.entries(command.body).filter(([key]) => key !== "command_id"));
  const operation = command.path.endsWith("/transfers") ? "create" : command.path.split("/").at(-1)!;
  const request = operation === "create" ? source.command_request : { id: source.id, ...body };
  const wire = { operation, actor_id: actorId, request }, response = { source, native_response: source.native_response };
  return { ...response, command_ack: { schema_version: "inventory-transfer-command-ack-v1", command_id: command.body.command_id, transfer_id: source.id,
    source_digest: source.source_digest, scope: transferScope, version: source.row_version, operation, actor_id: actorId,
    native_movement_id: source.native_movement_id, request_json: wire, request_digest: await transferDigest(wire, true), response_digest: await transferDigest(response) },
    submitted_request: command.body, submitted_request_digest: await transferDigest(command.body) };
}
