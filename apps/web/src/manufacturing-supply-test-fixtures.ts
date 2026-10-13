import { supplyCanonical, supplyPlainCanonical } from "./manufacturing-supply-data";
import type { PreparedScopedCommand } from "./scoped-command";
export const supplyScope = { workspace_id: "work", organization_id: "org", legal_entity_id: "entity" };
const hash = async (value: unknown) => [...new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(supplyCanonical(value))))].map(part => part.toString(16).padStart(2, "0")).join("");
const plainHash = async (value: unknown) => [...new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(supplyPlainCanonical(value))))].map(part => part.toString(16).padStart(2, "0")).join("");
export async function supplyApprovalAck(command: PreparedScopedCommand, source: Awaited<ReturnType<typeof supplyFixture>>, actorId = "checker") {
  const request = { operation: "approve", actor_id: actorId, request: { id: source.id, expected_digest: command.body.expected_digest, reason: command.body.reason } };
  return { source, command_ack: { schema_version: "manufacturing-supply-command-ack-v1", command_id: command.body.command_id, plan_id: source.id,
    source_digest: source.source_digest, operation: "approve", actor_id: actorId, version: 2, scope: supplyScope, request_json: request,
    request_digest: await hash(request), response_digest: await plainHash({ source }), native_kind: null, native_owner_id: null, native_command_id: null },
    submitted_request: command.body, submitted_request_digest: await plainHash(command.body) };
}
export async function supplyCreateAck(command: PreparedScopedCommand, source: Awaited<ReturnType<typeof supplyFixture>>) {
  const request = { operation: "create", actor_id: source.creator_id, request: source.command_request };
  return { source, command_ack: { schema_version: "manufacturing-supply-command-ack-v1", command_id: command.body.command_id, plan_id: source.id,
    source_digest: source.source_digest, operation: "create", actor_id: source.creator_id, version: 1, scope: supplyScope, request_json: request,
    request_digest: await hash(request), response_digest: await plainHash({ source }), native_kind: null, native_owner_id: null, native_command_id: null },
    submitted_request: command.body, submitted_request_digest: await plainHash(command.body) };
}
export async function supplyFixture(approved = false) {
  const identifier = `MSP1-${"A".repeat(32)}`, requirementId = `MSP1D-${"B".repeat(32)}`;
  const material = { schema_version: "manufacturing-order-v1", number: "SYN-DEMAND", bom_version_id: "SYN-BOM", output_quantity: "10", component_location_code: "MAIN/STOCK", finished_location_code: "MAIN/STOCK", component_policy_code: "FIFO", finished_policy_code: "MFG", journal_code: "STOCK", wip_account_code: "WIP", scrap_account_code: "SCRAP", period_id: "period", posting_date: "2026-10-04", reason: "Original synthetic demand", ...supplyScope, organization_code: "ORG", entity_code: "ENTITY" };
  const source = { ...material, schema_version: "manufacturing-supply-plan-v1", id: identifier, creator_id: "maker", routing_id: "SYN-ROUTE", budget_id: "SYN-BUDGET", bom_digest: "c".repeat(64), routing_digest: "d".repeat(64), currency_code: "USD", monetary_policy: { precision: 2 }, ceiling_minor: "300", unit_price_ceilings_minor: { MATERIAL: "100" }, command_request: { schema_version: "manufacturing-supply-plan-v1", material, routing_id: "SYN-ROUTE", budget_id: "SYN-BUDGET", unit_price_ceilings_minor: { MATERIAL: "100" } }, requirements: [{ requirement_id: requirementId, item_id: "MAT", uom_id: "KG", required_quantity_scaled: "3000", quantity_precision: 3 }] };
  const sourceDigest = await hash(source);
  const requirement = { schema_version: "manufacturing-planned-requirement-v1", id: requirementId, plan_id: identifier, plan_digest: sourceDigest, bom_version_id: "SYN-BOM", bom_digest: source.bom_digest, routing_id: "SYN-ROUTE", routing_digest: source.routing_digest, scope: supplyScope, sequence: 1, location_id: "STOCK", item_id: "MAT", item_code: "MATERIAL", uom_id: "KG", uom_code: "KG", quantity_precision: 3, inventory_account_id: "INVENTORY", gross_quantity_scaled: "3000", gross_quantity: "3.000" };
  const requirementDigest = await hash(requirement);
  const coverage = { schema_version: "manufacturing-supply-coverage-v1", requirement_id: requirementId, requirement_digest: requirementDigest, gross_quantity_scaled: "3000", observed_available_scaled: "500", observed_reserved_scaled: "0", observed_fifo_free_scaled: "500", onhand_reserved_scaled: "500", shortage_quantity_scaled: "2500" };
  return { ...source, source_digest: sourceDigest, phase: approved ? 1 : 0, row_version: approved ? 2 : 1, reviewer_actor_id: approved ? "checker" : null, material_order_id: null, manufacturing_order_id: null, planned_requirements: [{ ...requirement, source_digest: requirementDigest, coverage: approved ? coverage : null, coverage_digest: approved ? await hash(coverage) : null }], stock_claims: approved ? [{ id: `MSP1K-${"E".repeat(32)}`, requirement_id: requirementId, quantity_scaled: "500", origin: "OnHand", native_receipt_plan_id: null, state: "Active" }] : [], procurement_claims: [] };
}
