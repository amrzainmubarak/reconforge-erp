import { webcrypto } from "node:crypto";
import { beforeEach, expect, it, vi } from "vitest";
import { parseTransfer, parseTransferAck, transferDigest, transferMoney, transferRoot, type TransferSource } from "./inventory-transfer-data";
import { transferAck, transferBody, transferFixture, transferScope } from "./inventory-transfer-test-fixtures";
import { prepareScopedCommand } from "./scoped-command";

beforeEach(() => { vi.stubGlobal("crypto", webcrypto); Object.assign(transferScope, { workspace_id: "work", organization_id: "org", legal_entity_id: "entity" }); });
it("retains complete original USD36 value and exact base-unit quantity", async () => {
  const source = await transferFixture(); expect(await parseTransfer(source, transferScope, "synthetic")).toEqual(source);
  expect(transferMoney(source.cost_snapshot.remaining_value_minor, 2)).toBe("36.00");
  expect(transferMoney("1001", 3)).toBe("1.001"); expect(transferMoney("1001", 0)).toBe("1001");
});
it.each(["digest", "scope", "native", "remaining", "creator"])("refuses original %s drift before display", async field => {
  const source = await transferFixture();
  if (field === "digest") source.source_digest = "f".repeat(64);
  if (field === "scope") source.scope.legal_entity_id = "sibling";
  if (field === "native") (source.native_response.head as Record<string, unknown>).source_reference = "sibling-source";
  if (field === "remaining") source.cost_snapshot.remaining_value_minor = "0";
  if (field === "creator") source.creator_actor_id = "sibling";
  await expect(parseTransfer(source, transferScope, "synthetic")).rejects.toThrow("invalid");
});
it("binds exact original creation body/creator and historical receipt", async () => {
  const source = await transferFixture(), command = prepareScopedCommand(`${transferRoot}/transfers`, transferBody);
  const ack = await transferAck(source, command, "maker");
  expect(await parseTransferAck(ack, command, transferScope, { actorId: "maker", tenantId: "synthetic", previousVersion: null })).toEqual(source);
  const changed = prepareScopedCommand(`${transferRoot}/transfers`, { ...transferBody, number: "OTHER" });
  await expect(parseTransferAck(ack, changed, transferScope, { actorId: "maker", tenantId: "synthetic", previousVersion: null })).rejects.toThrow("invalid");
});
it.each(["phase", "actor", "body", "command", "native"])("rejects sealed same-source %s ACK drift", async field => {
  const source = await transferFixture(true), command = prepareScopedCommand(`${transferRoot}/transfers/${source.id}/review`, { expected_digest: source.source_digest, expected_version: 1, reason: "Independent original review" });
  const ack = await transferAck(source, command);
  if (field === "phase") { ack.source.phase = 3; ack.source.row_version = 3; }
  if (field === "actor") { ack.command_ack.actor_id = "other-human"; ack.command_ack.request_json.actor_id = "other-human"; ack.command_ack.request_digest = await transferDigest(ack.command_ack.request_json, true); }
  if (field === "body") ack.submitted_request = { ...command.body, reason: "Changed original review" };
  if (field === "command") ack.command_ack.command_id = "another-command";
  if (field === "native") ack.native_response = { ...source.native_response, head: { ...(source.native_response.head as Record<string, unknown>), id: "other-native" } };
  ack.command_ack.response_digest = await transferDigest({ source: ack.source, native_response: ack.native_response });
  ack.submitted_request_digest = await transferDigest(ack.submitted_request);
  await expect(parseTransferAck(ack, command, transferScope, { actorId: "checker", tenantId: "synthetic", previousVersion: 1 })).rejects.toThrow("invalid");
});
it("accepts exact retained review ACK and forbids a changed expected version", async () => {
  const source = await transferFixture(true), command = prepareScopedCommand(`${transferRoot}/transfers/${source.id}/review`, { expected_digest: source.source_digest, expected_version: 1, reason: "Independent original review" });
  const ack = await transferAck(source, command);
  expect(await parseTransferAck(ack, command, transferScope, { actorId: "checker", tenantId: "synthetic", previousVersion: 1 })).toEqual(source);
  await expect(parseTransferAck(ack, command, transferScope, { actorId: "checker", tenantId: "synthetic", previousVersion: 2 })).rejects.toThrow("invalid");
});
it.each(["tenant", "line-parent", "claim-tenant", "claim-precision"])("refuses sealed current-source %s native custody drift", async field => {
  const source = await transferFixture(true), line = source.native_response.lines as Array<Record<string, unknown>>;
  if (field === "tenant") await expect(parseTransfer(source, transferScope, "foreign-tenant")).rejects.toThrow("invalid");
  else {
    if (field === "line-parent") line[0].movement_id = "foreign-movement";
    if (field === "claim-tenant") (source.claim as Record<string, unknown>).tenant_id = "foreign-tenant";
    if (field === "claim-precision") (source.claim as Record<string, unknown>).quantity_precision = 3;
    await expect(parseTransfer(source, transferScope, "synthetic")).rejects.toThrow("invalid");
  }
});

type Row = Record<string, unknown>;
async function reseal(source: TransferSource): Promise<TransferSource> {
  const dynamic = ["source_digest", "phase", "row_version", "reviewer_actor_id", "poster_actor_id", "review_cost_snapshot", "review_cost_digest", "claim", "release", "native_response"];
  source.source_digest = await transferDigest(Object.fromEntries(Object.entries(source).filter(([key]) => !dynamic.includes(key))), true);
  if (source.review_cost_snapshot) source.review_cost_digest = await transferDigest(source.review_cost_snapshot, true);
  return source;
}
async function restitutionCorrection(index: number, direction: 1 | -1 = 1, originalPlan: string | null = null, originalEffect = "original-restoration-effect"): Promise<Row> {
  const id = (direction === 1 ? "CR2-" : "CR2R-") + index.toString(16).padStart(32, "0"), sourceId = "CRS2-" + "b".repeat(32);
  const policy = (await transferFixture()).cost_snapshot.monetary_policy as Row;
  const oldEffect = originalEffect, entryId = `entry-${index}`, effectId = `effect-${index}`, movementId = `movement-${index}`;
  const entry: Row = { id: entryId, tenant_id: "synthetic", workspace_id: "work", journal_id: "STOCK", period_id: "period", entry_number: id.toUpperCase() + "-C",
    posting_date: "2026-10-15", description: "Original FIFO correction", external_reference: direction === 1 ? id : oldEffect, source_type: direction === 1 ? "Manual" : "Generated", status: "Validated",
    ...policy, preparer_actor_id: "maker", validator_actor_id: "checker", validation_contract_version: "finance-entry-review-v1", reverses_posting_id: direction === 1 ? null : oldEffect,
    total_debit_minor: "1200", total_credit_minor: "1200" };
  const lines = ["inventory-account", "cogs-account"].map((account_id, position) => ({ tenant_id: "synthetic", id: `line-${index}-${position}`, entry_id: entryId, line_number: position + 1,
    account_id, description: "Original FIFO correction", currency_code: "USD", debit_minor: (position === 0) === (direction === 1) ? "1200" : "0", credit_minor: (position === 1) === (direction === 1) ? "1200" : "0" }));
  const header = Object.fromEntries(["id", "workspace_id", "journal_id", "period_id", "entry_number", "posting_date", "description", "external_reference", "source_type",
    "currency_code", "currency_precision", "currency_rounding_policy", "currency_registry_version", "currency_registry_digest", "preparer_actor_id", "reverses_posting_id"].map(key => [key, entry[key]]));
  Object.assign(header, { organization_id: "org", legal_entity_id: "entity" });
  const snapshot = { schema_version: "finance-entry-review-v1", entry: header, lines: lines.map(line => ({ line_number: line.line_number, account_id: line.account_id, description: line.description, debit_minor: line.debit_minor, credit_minor: line.credit_minor, dimensions: {} })) };
  entry.validation_digest = await transferDigest(snapshot, true);
  return {
    restoration: { tenant_id: "synthetic", source_id: sourceId, plan_id: id, position: 1, original_consumption_id: "sale-consumption", original_valuation_line_id: "sale-valuation-line", cost_layer_id: "original-layer",
      offset_quantity_scaled: "0", quantity_scaled: "1", value_minor: "1200", direction, physical_movement_id: movementId, original_cogs_effect_id: "original-sale-cost",
      correction_effect_id: effectId, original_restoration_plan_id: originalPlan, consumption_count_at_restore: 1 },
    source: { id: sourceId, source_fingerprint: "f".repeat(64), ...transferScope, item_id: "item", uom_id: "uom", quantity_precision: 0, location_id: "source-location", original_cogs_effect_id: "original-sale-cost" },
    plan: { id, source_id: sourceId, operation: direction === 1 ? "Return" : "ReverseReturn", phase: 2, plan_digest: "d".repeat(64) }, entry,
    effect: { id: effectId, tenant_id: "synthetic", ...transferScope, entry_id: entryId, source_kind: direction === 1 ? "Manual" : "Reversal", source_id: direction === 1 ? entryId : oldEffect,
      purpose: "operational_posting", reverses_effect_id: direction === 1 ? null : oldEffect, validation_digest: entry.validation_digest, validation_contract_version: "finance-entry-review-v1", ...policy, posted_actor_id: "poster", snapshot_json: snapshot },
    lines, dimensions: [], physical: { head: { id: movementId, tenant_id: "synthetic", ...transferScope, source_reference: id, movement_number: id.toUpperCase(), status: "Posted", source_type: "Generated", movement_type: direction === 1 ? "Receipt" : "Delivery" },
      lines: [{ tenant_id: "synthetic", movement_id: movementId, line_number: 1, item_id: "item", uom_id: "uom", quantity_precision: 0, inventory_lot_id: null, quantity_scaled: "1", from_location_id: direction === 1 ? null : "source-location", to_location_id: direction === 1 ? "source-location" : null }], audit: [{}], outbox: [{}] },
  };
}
async function restitutionFixture(reviewed = false, signed = false): Promise<TransferSource> {
  const transfer = await transferFixture(reviewed), original = transfer.cost_snapshot.sources[0];
  Object.assign(original.layer as Row, { quantity_precision: 0, remaining_quantity_scaled: "2", remaining_value_minor: "2400" });
  (original.valuation_line as Row).inventory_account_id = "inventory-account";
  Object.assign(original, { receipt_review: {}, receipt_native: {}, valuation_input: {}, consumptions: [{ id: "sale-consumption", tenant_id: "synthetic", cost_layer_id: "original-layer", valuation_line_id: "sale-valuation-line", quantity_scaled: "2", value_minor: "2400" }] });
  const first = await restitutionCorrection(1), corrections = signed ? [first, await restitutionCorrection(2, -1, String((first.plan as Row).id), String((first.effect as Row).id)), await restitutionCorrection(3)] : [first];
  original.partial_return_corrections = corrections;
  original.exposed_amounts_minor = ["3600", "2400", "3600", "3600", "3600", "3600", "3600", "3600", "0", "0", "3600", ...corrections.map(() => "1200"), ...corrections.map(() => "1200")];
  Object.assign(transfer.cost_snapshot, { schema_version: "inventory-transfer-cost-v2", remaining_quantity_scaled: "2", remaining_value_minor: "2400" });
  if (reviewed) transfer.review_cost_snapshot = structuredClone(transfer.cost_snapshot);
  return reseal(transfer);
}
it.each([false, true])("accepts sealed v2 original and reviewed restitution with signed history=%s", async signed => {
  for (const reviewed of [false, true]) {
    const source = await restitutionFixture(reviewed, signed);
    expect(await parseTransfer(source, transferScope, "synthetic")).toEqual(source);
    expect(transferMoney(source.cost_snapshot.remaining_value_minor, 2)).toBe("24.00");
  }
});
it("accepts a v1 retained creation with an independently sealed v2 current review", async () => {
  const original = await transferFixture(true), current = await restitutionFixture(true);
  original.review_cost_snapshot = current.review_cost_snapshot;
  await reseal(original);
  expect(await parseTransfer(original, transferScope, "synthetic")).toEqual(original);
});
it("accepts another complete layer with an empty correction array inside a genuine v2 pool", async () => {
  const source = await restitutionFixture(), extra = structuredClone(source.cost_snapshot.sources[0]);
  Object.assign(extra.layer as Row, { id: "second-layer", source_valuation_line_id: "second-line", remaining_quantity_scaled: "3", remaining_value_minor: "3600" });
  (extra.valuation_line as Row).id = "second-line";
  (extra.receipt_plan as Row).plan_id = "second-receipt";
  Object.assign(extra.receipt_link as Row, { plan_id: "second-receipt", cost_layer_id: "second-layer" });
  (extra.posting_effect as Row).source_id = "second-receipt";
  Object.assign(extra, { consumptions: [], partial_return_corrections: [], exposed_amounts_minor: Array.from({ length: 11 }, () => "3600") });
  source.cost_snapshot.sources.push(extra); source.cost_snapshot.remaining_quantity_scaled = "5"; source.cost_snapshot.remaining_value_minor = "6000";
  await reseal(source); expect(await parseTransfer(source, transferScope, "synthetic")).toEqual(source);
});
it("admits exactly 200 linked signed corrections without relaxing the 201 refusal", async () => {
  const source = await restitutionFixture(), original = source.cost_snapshot.sources[0], history: Row[] = [];
  for (let pair = 0; pair < 99; ++pair) {
    const first = await restitutionCorrection(pair * 2 + 1); history.push(first);
    history.push(await restitutionCorrection(pair * 2 + 2, -1, String((first.plan as Row).id), String((first.effect as Row).id)));
  }
  history.push(await restitutionCorrection(199), await restitutionCorrection(200));
  (history.at(-1)!.restoration as Row).offset_quantity_scaled = "1";
  Object.assign(original, { partial_return_corrections: history, exposed_amounts_minor: ["3600", "3600", "3600", "3600", "3600", "3600", "3600", "3600", "0", "0", "3600", ...history.map(() => "1200"), ...history.map(() => "1200")] });
  Object.assign(original.layer as Row, { remaining_quantity_scaled: "3", remaining_value_minor: "3600" });
  source.cost_snapshot.remaining_quantity_scaled = "3"; source.cost_snapshot.remaining_value_minor = "3600";
  await reseal(source); expect(await parseTransfer(source, transferScope, "synthetic")).toEqual(source);
});
it("refuses an integral balanced and resealed portion with a different original cost ratio", async () => {
  const source = await restitutionFixture(), original = source.cost_snapshot.sources[0], correction = (original.partial_return_corrections as Row[])[0];
  (correction.restoration as Row).value_minor = "1199";
  const entry = correction.entry as Row, effect = correction.effect as Row, lines = correction.lines as Row[], snapshot = effect.snapshot_json as Row;
  entry.total_debit_minor = entry.total_credit_minor = "1199";
  lines[0].debit_minor = lines[1].credit_minor = "1199";
  const snapshotLines = snapshot.lines as Row[];
  snapshotLines[0].debit_minor = snapshotLines[1].credit_minor = "1199";
  entry.validation_digest = effect.validation_digest = await transferDigest(snapshot, true);
  (original.layer as Row).remaining_value_minor = source.cost_snapshot.remaining_value_minor = "2399";
  const exposures = original.exposed_amounts_minor as string[];
  exposures[11] = exposures[12] = "1199";
  await reseal(source);
  await expect(parseTransfer(source, transferScope, "synthetic")).rejects.toThrow("invalid");
});
it("refuses a sealed inverse linked to a different original correction effect", async () => {
  const source = await restitutionFixture(false, true), reverse = (source.cost_snapshot.sources[0].partial_return_corrections as Row[])[1];
  const effect = reverse.effect as Row, entry = reverse.entry as Row, snapshot = effect.snapshot_json as Row;
  effect.reverses_effect_id = effect.source_id = entry.external_reference = entry.reverses_posting_id = "different-original-effect";
  Object.assign(snapshot.entry as Row, { external_reference: entry.external_reference, reverses_posting_id: entry.reverses_posting_id });
  entry.validation_digest = effect.validation_digest = await transferDigest(snapshot, true);
  await reseal(source); await expect(parseTransfer(source, transferScope, "synthetic")).rejects.toThrow("invalid");
});
it.each([false, true])("binds actual dimension memberships without prototype inheritance, duplicate=%s", async duplicate => {
  const source = await restitutionFixture(), correction = (source.cost_snapshot.sources[0].partial_return_corrections as Row[])[0];
  const effect = correction.effect as Row, entry = correction.entry as Row, snapshot = effect.snapshot_json as Row, line = (correction.lines as Row[])[0];
  const dimension = { tenant_id: "synthetic", entry_line_id: line.id, dimension_id: "__proto__", dimension_value_id: "original-dimension-value" };
  correction.dimensions = duplicate ? [dimension, { ...dimension }] : [dimension];
  (snapshot.lines as Row[])[0].dimensions = Object.fromEntries([[dimension.dimension_id, dimension.dimension_value_id]]);
  entry.validation_digest = effect.validation_digest = await transferDigest(snapshot, true);
  await reseal(source);
  if (duplicate) await expect(parseTransfer(source, transferScope, "synthetic")).rejects.toThrow("invalid");
  else expect(await parseTransfer(source, transferScope, "synthetic")).toEqual(source);
});
it.each(["unknown-version", "extra-top", "extra-source", "extra-correction", "empty-corrections", "duplicate", "tenant", "scope", "layer", "direction", "money", "consumption", "precision", "policy", "effect", "physical", "equation", "exposure", "seal", "count", "net-negative"])("refuses coherently resealed v2 %s drift", async field => {
  const source = await restitutionFixture(), original = source.cost_snapshot.sources[0], correction = (original.partial_return_corrections as Row[])[0], restored = correction.restoration as Row;
  if (field === "unknown-version") source.cost_snapshot.schema_version = "inventory-transfer-cost-v3";
  if (field === "extra-top") source.cost_snapshot.secret = "not-public";
  if (field === "extra-source") original.secret = "not-public";
  if (field === "extra-correction") correction.secret = "not-public";
  if (field === "empty-corrections") original.partial_return_corrections = [];
  if (field === "duplicate") original.partial_return_corrections = [correction, correction];
  if (field === "tenant") restored.tenant_id = "foreign";
  if (field === "scope") (correction.source as Row).legal_entity_id = "foreign";
  if (field === "layer") restored.cost_layer_id = "foreign";
  if (field === "direction") restored.direction = "1";
  if (field === "money") restored.value_minor = 1200;
  if (field === "consumption") restored.original_consumption_id = "foreign";
  if (field === "precision") (correction.source as Row).quantity_precision = 3;
  if (field === "policy") (correction.effect as Row).currency_registry_digest = "e".repeat(64);
  if (field === "effect") (correction.effect as Row).entry_id = "foreign";
  if (field === "physical") (((correction.physical as Row).lines as Row[])[0]).to_location_id = "foreign";
  if (field === "equation") (original.layer as Row).remaining_value_minor = "2399";
  if (field === "exposure") (original.exposed_amounts_minor as string[]).pop();
  if (field === "seal") (correction.entry as Row).validation_digest = (correction.effect as Row).validation_digest = "f".repeat(64);
  if (field === "count") original.partial_return_corrections = Array.from({ length: 201 }, () => correction);
  if (field === "net-negative") original.partial_return_corrections = [await restitutionCorrection(2, -1, String((correction.plan as Row).id))];
  await reseal(source); await expect(parseTransfer(source, transferScope, "synthetic")).rejects.toThrow("invalid");
});
