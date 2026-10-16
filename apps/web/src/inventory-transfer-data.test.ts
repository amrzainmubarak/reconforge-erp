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

interface RemainingStep {
  beforeQuantity: string; beforeValue: string; quantity: string; value: string;
  sequence: number; reverse?: number; total?: string;
}
async function remainingFixture(quantity: string, value: string, steps: RemainingStep[], reviewed = false): Promise<TransferSource> {
  const transfer = await restitutionFixture(), source = transfer.cost_snapshot.sources[0], history: Row[] = [];
  let netQuantity = 0n, netValue = 0n;
  for (const [index, step] of steps.entries()) {
    const previous = step.reverse === undefined ? null : history[step.reverse];
    const correction = await restitutionCorrection(index + 1, previous ? -1 : 1,
      previous ? String((previous.plan as Row).id) : null, previous?.effect ? String((previous.effect as Row).id) : "original-restoration-effect");
    const restored = correction.restoration as Row, plan = correction.plan as Row;
    Object.assign(correction, { history_sequence: step.sequence, allocation_policy: "remaining-original-v1",
      allocation_witness: { before_quantity_scaled: step.beforeQuantity, before_value_minor: step.beforeValue } });
    Object.assign(restored, { offset_quantity_scaled: (BigInt(quantity) - BigInt(step.beforeQuantity)).toString(), quantity_scaled: step.quantity, value_minor: step.value });
    const total = step.total ?? step.value;
    plan.cogs_restored_minor = total;
    (((correction.physical as Row).lines as Row[])[0]).quantity_scaled = step.quantity;
    if (total === "0") {
      restored.correction_effect_id = correction.entry = correction.effect = null;
      correction.lines = []; correction.dimensions = [];
    } else {
      const entry = correction.entry as Row, effect = correction.effect as Row, lines = correction.lines as Row[], snapshot = effect.snapshot_json as Row;
      entry.total_debit_minor = entry.total_credit_minor = total;
      for (const line of lines) {
        if (line.debit_minor !== "0") line.debit_minor = total;
        if (line.credit_minor !== "0") line.credit_minor = total;
      }
      for (const line of snapshot.lines as Row[]) {
        if (line.debit_minor !== "0") line.debit_minor = total;
        if (line.credit_minor !== "0") line.credit_minor = total;
      }
      entry.validation_digest = effect.validation_digest = await transferDigest(snapshot, true);
    }
    history.push(correction);
    netQuantity += (previous ? -1n : 1n) * BigInt(step.quantity);
    netValue += (previous ? -1n : 1n) * BigInt(step.value);
  }
  Object.assign(source.layer as Row, { original_quantity_scaled: quantity, original_value_minor: value, remaining_quantity_scaled: netQuantity.toString(), remaining_value_minor: netValue.toString() });
  Object.assign(source.valuation_line as Row, { quantity_scaled: quantity, value_minor: value });
  (source.valuation_document as Row).total_value_minor = value;
  Object.assign(source.finance_entry as Row, { total_debit_minor: value, total_credit_minor: value });
  source.finance_lines = [{ debit_minor: value, credit_minor: "0" }, { debit_minor: "0", credit_minor: value }];
  source.consumptions = [{ id: "sale-consumption", tenant_id: "synthetic", cost_layer_id: "original-layer", valuation_line_id: "sale-valuation-line", quantity_scaled: quantity, value_minor: value }];
  const entryAmounts = history.filter(row => row.entry !== null).map(row => String((row.entry as Row).total_debit_minor));
  source.partial_return_corrections = history;
  source.exposed_amounts_minor = [value, netValue.toString(), value, value, value, value, value, value, "0", "0", value, ...entryAmounts, ...entryAmounts];
  Object.assign(transfer.cost_snapshot, { schema_version: "inventory-transfer-cost-v3", remaining_quantity_scaled: netQuantity.toString(), remaining_value_minor: netValue.toString() });
  if (reviewed) {
    transfer.phase = 1; transfer.row_version = 2; transfer.reviewer_actor_id = "checker";
    transfer.review_cost_snapshot = structuredClone(transfer.cost_snapshot);
    transfer.claim = (await transferFixture(true)).claim;
  }
  return reseal(transfer);
}

async function monetaryCostFixture(steps: RemainingStep[], reviewed = false, quantity = "3", value = "1001"): Promise<TransferSource> {
  const transfer = await remainingFixture(quantity, value, steps, reviewed), source = transfer.cost_snapshot.sources[0];
  const rows = source.partial_return_corrections as Row[], origin = "MSO-" + "a".repeat(32);
  for (const row of rows) {
    const restored = row.restoration as Row, original = row.source as Row, plan = row.plan as Row, witness = row.allocation_witness as Row;
    const id = String(plan.id).replace(/^CR2/, "CR3");
    row.source = { id: origin, source_digest: original.source_fingerprint, stock_order_id: "monetary-stock", ...transferScope,
      item_id: original.item_id, uom_id: original.uom_id, quantity_precision: original.quantity_precision, location_id: original.location_id,
      original_cogs_effect_id: original.original_cogs_effect_id, original_cost_minor: value };
    row.plan = { id, source_id: origin, operation: plan.operation, phase: plan.phase, plan_digest: plan.plan_digest, functional_cost_minor: plan.cogs_restored_minor };
    delete restored.source_id; delete restored.offset_quantity_scaled; delete restored.original_cogs_effect_id;
    Object.assign(restored, transferScope, { origin_id: origin, plan_id: id, before_quantity_scaled: witness.before_quantity_scaled, before_value_minor: witness.before_value_minor,
      original_restoration_plan_id: restored.original_restoration_plan_id === null ? null : String(restored.original_restoration_plan_id).replace(/^CR2/, "CR3") });
    row.allocation_policy = "remaining-dual-currency-v1"; delete row.allocation_witness;
    const physical = row.physical as Row;
    Object.assign(physical.head as Row, { source_reference: id, movement_number: id.toUpperCase() });
    if (row.entry !== null) {
      const entry = row.entry as Row, effect = row.effect as Row, snapshot = effect.snapshot_json as Row;
      entry.entry_number = id.toUpperCase() + "-C";
      if (restored.direction === 1) entry.external_reference = id;
      Object.assign(snapshot.entry as Row, { entry_number: entry.entry_number, external_reference: entry.external_reference });
      entry.validation_digest = effect.validation_digest = await transferDigest(snapshot, true);
    }
  }
  source.monetary_return_corrections = rows; source.partial_return_corrections = [];
  transfer.cost_snapshot.schema_version = "inventory-transfer-cost-v4";
  if (reviewed) transfer.review_cost_snapshot = structuredClone(transfer.cost_snapshot);
  return reseal(transfer);
}

const monetaryThree = [
  { sequence: 1, beforeQuantity: "3", beforeValue: "1001", quantity: "1", value: "334" },
  { sequence: 4, beforeQuantity: "2", beforeValue: "667", quantity: "1", value: "334" },
  { sequence: 7, beforeQuantity: "1", beforeValue: "333", quantity: "1", value: "333" },
];
it.each([false, true])("reads closed v4 monetary remaining values and independent reviewed seal, review=%s", async reviewed => {
  const transfer = await monetaryCostFixture(monetaryThree, reviewed);
  expect(await parseTransfer(transfer, transferScope, "synthetic")).toEqual(transfer);
  expect(transfer.cost_snapshot.remaining_value_minor).toBe("1001");
});
it("admits a v4 monetary consumption before any Return without fabricating correction history", async () => {
  const transfer = await restitutionFixture(), source = transfer.cost_snapshot.sources[0];
  source.partial_return_corrections = []; source.monetary_return_corrections = [];
  Object.assign(source.layer as Row, { remaining_quantity_scaled: "1", remaining_value_minor: "1200" });
  source.exposed_amounts_minor = ["3600", "1200", "3600", "3600", "3600", "3600", "3600", "3600", "0", "0", "3600"];
  Object.assign(transfer.cost_snapshot, { schema_version: "inventory-transfer-cost-v4", remaining_quantity_scaled: "1", remaining_value_minor: "1200" });
  await reseal(transfer); expect(await parseTransfer(transfer, transferScope, "synthetic")).toEqual(transfer);
});
it("keeps both legacy and monetary native correction families in one v4 pool", async () => {
  const transfer = await monetaryCostFixture(monetaryThree), legacy = await restitutionFixture(), extra = legacy.cost_snapshot.sources[0];
  Object.assign(extra.layer as Row, { id: "legacy-layer", source_valuation_line_id: "legacy-original-line" });
  (extra.valuation_line as Row).id = "legacy-original-line";
  (extra.receipt_link as Row).cost_layer_id = "legacy-layer";
  (extra.consumptions as Row[])[0].cost_layer_id = "legacy-layer";
  ((extra.partial_return_corrections as Row[])[0].restoration as Row).cost_layer_id = "legacy-layer";
  extra.monetary_return_corrections = [];
  transfer.cost_snapshot.sources.push(extra);
  transfer.cost_snapshot.remaining_quantity_scaled = "5"; transfer.cost_snapshot.remaining_value_minor = "3401";
  await reseal(transfer); expect(await parseTransfer(transfer, transferScope, "synthetic")).toEqual(transfer);
});
it("retains an exact monetary inverse without rerounding the copied original witness", async () => {
  const transfer = await monetaryCostFixture([
    { sequence: 1, beforeQuantity: "3", beforeValue: "1001", quantity: "1", value: "334" },
    { sequence: 3, beforeQuantity: "3", beforeValue: "1001", quantity: "1", value: "334", reverse: 0 },
    { sequence: 5, beforeQuantity: "3", beforeValue: "1001", quantity: "1", value: "334" },
  ]);
  expect(await parseTransfer(transfer, transferScope, "synthetic")).toEqual(transfer);
});
it("keeps zero TOTAL journals absent while physical portions and copied inverse remain mandatory", async () => {
  const transfer = await monetaryCostFixture([
    { sequence: 1, beforeQuantity: "3", beforeValue: "1", quantity: "1", value: "0" },
    { sequence: 2, beforeQuantity: "3", beforeValue: "1", quantity: "1", value: "0", reverse: 0 },
    { sequence: 3, beforeQuantity: "3", beforeValue: "1", quantity: "1", value: "0" },
    { sequence: 4, beforeQuantity: "2", beforeValue: "1", quantity: "1", value: "0" },
    { sequence: 5, beforeQuantity: "1", beforeValue: "1", quantity: "1", value: "1" },
  ], false, "3", "1");
  expect(await parseTransfer(transfer, transferScope, "synthetic")).toEqual(transfer);
  const rows = transfer.cost_snapshot.sources[0].monetary_return_corrections as Row[];
  expect(rows.map(row => row.entry === null)).toEqual([true, true, true, true, false]);
  delete (rows[0].physical as Row).lines;
  await reseal(transfer); await expect(parseTransfer(transfer, transferScope, "synthetic")).rejects.toThrow("invalid");
});
it("does not suppress a positive shared plan journal merely because its visible portion is zero", async () => {
  const transfer = await monetaryCostFixture([{ sequence: 1, beforeQuantity: "3", beforeValue: "1", quantity: "1", value: "0", total: "1" }], false, "3", "1");
  expect(await parseTransfer(transfer, transferScope, "synthetic")).toEqual(transfer);
  const row = (transfer.cost_snapshot.sources[0].monetary_return_corrections as Row[])[0];
  row.entry = row.effect = (row.restoration as Row).correction_effect_id = null; row.lines = []; row.dimensions = [];
  await reseal(transfer); await expect(parseTransfer(transfer, transferScope, "synthetic")).rejects.toThrow("invalid");
});
it("pins one shared positive TOTAL effect across zero and positive portions on different layers", async () => {
  const transfer = await monetaryCostFixture([{ sequence: 1, beforeQuantity: "3", beforeValue: "1", quantity: "1", value: "0", total: "1" }], false, "3", "1");
  const source = transfer.cost_snapshot.sources[0], first = (source.monetary_return_corrections as Row[])[0];
  (first.source as Row).original_cost_minor = "2";
  (((first.physical as Row).lines as Row[])[0]).quantity_scaled = "2";
  const extra = structuredClone(source), second = (extra.monetary_return_corrections as Row[])[0];
  Object.assign(extra.layer as Row, { id: "other-layer", source_valuation_line_id: "other-receipt-line", original_quantity_scaled: "1", original_value_minor: "1", remaining_quantity_scaled: "1", remaining_value_minor: "1" });
  Object.assign(extra.valuation_line as Row, { id: "other-receipt-line", quantity_scaled: "1", value_minor: "1" });
  (extra.receipt_link as Row).cost_layer_id = "other-layer";
  extra.consumptions = [{ id: "other-consumption", tenant_id: "synthetic", cost_layer_id: "other-layer", valuation_line_id: "other-sale-line", quantity_scaled: "1", value_minor: "1" }];
  Object.assign(second.restoration as Row, { position: 2, original_consumption_id: "other-consumption", original_valuation_line_id: "other-sale-line", cost_layer_id: "other-layer", before_quantity_scaled: "1", before_value_minor: "1", value_minor: "1" });
  extra.exposed_amounts_minor = ["1", "1", "1", "1", "1", "1", "1", "1", "0", "0", "1", "1", "1"];
  transfer.cost_snapshot.sources.push(extra);
  transfer.cost_snapshot.remaining_quantity_scaled = "2"; transfer.cost_snapshot.remaining_value_minor = "1";
  await reseal(transfer); expect(await parseTransfer(transfer, transferScope, "synthetic")).toEqual(transfer);
  const entry = second.entry as Row, effect = second.effect as Row, snapshot = effect.snapshot_json as Row;
  entry.id = effect.entry_id = (snapshot.entry as Row).id = "other-balanced-journal";
  effect.id = (second.restoration as Row).correction_effect_id = "other-balanced-effect";
  for (const line of second.lines as Row[]) line.entry_id = entry.id;
  entry.validation_digest = effect.validation_digest = await transferDigest(snapshot, true);
  await reseal(transfer); await expect(parseTransfer(transfer, transferScope, "synthetic")).rejects.toThrow("invalid");
});
it("bounds the combined native correction byte population even when every individual row is small", async () => {
  const transfer = await monetaryCostFixture(Array.from({ length: 7 }, (_, index) => ({ sequence: index + 1, beforeQuantity: String(7 - index), beforeValue: String(7 - index), quantity: "1", value: "1" })), false, "7", "7");
  expect(await parseTransfer(transfer, transferScope, "synthetic")).toEqual(transfer);
  const rows = transfer.cost_snapshot.sources[0].monetary_return_corrections as Row[];
  for (const row of rows) {
    const entry = row.entry as Row, effect = row.effect as Row, snapshot = effect.snapshot_json as Row;
    // Each repeated string remains below the per-correction bound. Across the
    // array, native jsonb spacing and all retained originals exceed one MiB.
    const description = "s".repeat(30000);
    entry.description = (snapshot.entry as Row).description = description;
    for (const line of row.lines as Row[]) line.description = description;
    for (const line of snapshot.lines as Row[]) line.description = description;
    entry.validation_digest = effect.validation_digest = await transferDigest(snapshot, true);
  }
  await reseal(transfer); await expect(parseTransfer(transfer, transferScope, "synthetic")).rejects.toThrow("invalid");
});
it("admits the finite 256 monetary zero journals then refuses a 257th legacy correction across layers", async () => {
  const steps: RemainingStep[] = [];
  for (let index = 0; index < 127; index++) {
    steps.push({ sequence: index * 2 + 1, beforeQuantity: "3", beforeValue: "1", quantity: "1", value: "0" });
    steps.push({ sequence: index * 2 + 2, beforeQuantity: "3", beforeValue: "1", quantity: "1", value: "0", reverse: index * 2 });
  }
  steps.push({ sequence: 255, beforeQuantity: "3", beforeValue: "1", quantity: "1", value: "0" });
  steps.push({ sequence: 256, beforeQuantity: "2", beforeValue: "1", quantity: "1", value: "0" });
  const transfer = await monetaryCostFixture(steps, false, "3", "1");
  expect(await parseTransfer(transfer, transferScope, "synthetic")).toEqual(transfer);
  const legacy = (await restitutionFixture()).cost_snapshot.sources[0];
  Object.assign(legacy.layer as Row, { id: "extra-layer", source_valuation_line_id: "extra-original-line" });
  (legacy.valuation_line as Row).id = "extra-original-line";
  (legacy.receipt_link as Row).cost_layer_id = "extra-layer";
  (legacy.consumptions as Row[])[0].cost_layer_id = "extra-layer";
  ((legacy.partial_return_corrections as Row[])[0].restoration as Row).cost_layer_id = "extra-layer";
  legacy.monetary_return_corrections = [];
  transfer.cost_snapshot.sources.push(legacy);
  transfer.cost_snapshot.remaining_quantity_scaled = "4"; transfer.cost_snapshot.remaining_value_minor = "2400";
  await reseal(transfer); await expect(parseTransfer(transfer, transferScope, "synthetic")).rejects.toThrow("invalid");
});
it.each(["old-version", "missing-family", "missing-total", "extra-envelope", "extra-source", "origin", "scope", "plan-total", "numeric-total", "policy", "before-value", "sequence-bool", "direction", "effect-null", "exposure", "copied-inverse"])("refuses coherently sealed v4 %s corruption", async damage => {
  const steps = damage === "copied-inverse" ? [monetaryThree[0], { ...monetaryThree[0], sequence: 2, reverse: 0 }] : monetaryThree;
  const transfer = await monetaryCostFixture(steps), source = transfer.cost_snapshot.sources[0];
  const rows = source.monetary_return_corrections as Row[], row = rows.at(-1)!, restored = row.restoration as Row, plan = row.plan as Row;
  if (damage === "old-version") transfer.cost_snapshot.schema_version = "inventory-transfer-cost-v3";
  if (damage === "missing-family") delete source.partial_return_corrections;
  if (damage === "missing-total") delete plan.functional_cost_minor;
  if (damage === "extra-envelope") row.allocation_witness = {};
  if (damage === "extra-source") (row.source as Row).secret = "not-public";
  if (damage === "origin") restored.origin_id = "MSO-" + "b".repeat(32);
  if (damage === "scope") restored.workspace_id = "other";
  if (damage === "plan-total") plan.functional_cost_minor = "0";
  if (damage === "numeric-total") plan.functional_cost_minor = 333;
  if (damage === "policy") row.allocation_policy = "remaining-original-v1";
  if (damage === "before-value") restored.before_value_minor = "334";
  if (damage === "sequence-bool") row.history_sequence = true;
  if (damage === "direction") restored.direction = "1";
  if (damage === "effect-null") row.entry = row.effect = restored.correction_effect_id = null;
  if (damage === "exposure") (source.exposed_amounts_minor as string[]).pop();
  if (damage === "copied-inverse") restored.before_value_minor = "1000";
  await reseal(transfer); await expect(parseTransfer(transfer, transferScope, "synthetic")).rejects.toThrow("invalid");
});
it.each([false, true])("retains v3 remaining-value 1001/3 allocations and final residual with review=%s", async reviewed => {
  const source = await remainingFixture("3", "1001", [
    { sequence: 1, beforeQuantity: "3", beforeValue: "1001", quantity: "1", value: "334" },
    { sequence: 4, beforeQuantity: "2", beforeValue: "667", quantity: "1", value: "334" },
    { sequence: 7, beforeQuantity: "1", beforeValue: "333", quantity: "1", value: "333" },
  ], reviewed);
  expect(await parseTransfer(source, transferScope, "synthetic")).toEqual(source);
});
it("uses captured FIFO half-even and carries a zero-cost physical portion without a fake journal", async () => {
  const source = await remainingFixture("2", "1", [
    { sequence: 1, beforeQuantity: "2", beforeValue: "1", quantity: "1", value: "0" },
    { sequence: 3, beforeQuantity: "1", beforeValue: "1", quantity: "1", value: "1" },
  ]);
  expect(await parseTransfer(source, transferScope, "synthetic")).toEqual(source);
  expect((source.cost_snapshot.sources[0].exposed_amounts_minor as string[]).slice(11)).toEqual(["1", "1"]);
});
it("retains a positive remaining quantity after all original minor units were allocated and exhausts it at zero", async () => {
  const source = await remainingFixture("3", "1", [
    { sequence: 1, beforeQuantity: "3", beforeValue: "1", quantity: "2", value: "1" },
    { sequence: 2, beforeQuantity: "1", beforeValue: "0", quantity: "1", value: "0" },
  ]);
  expect(await parseTransfer(source, transferScope, "synthetic")).toEqual(source);
  expect(((source.cost_snapshot.sources[0].partial_return_corrections as Row[])[1]).effect).toBeNull();
});
it("reverses exact zero-cost original witnesses and then readmits the same remaining basis", async () => {
  const source = await remainingFixture("2", "1", [
    { sequence: 1, beforeQuantity: "2", beforeValue: "1", quantity: "1", value: "0" },
    { sequence: 2, beforeQuantity: "2", beforeValue: "1", quantity: "1", value: "0", reverse: 0 },
    { sequence: 3, beforeQuantity: "2", beforeValue: "1", quantity: "1", value: "0" },
  ]);
  expect(await parseTransfer(source, transferScope, "synthetic")).toEqual(source);
});
it("reverses the copied 334-minor portion instead of rerounding it on the later remaining basis", async () => {
  const source = await remainingFixture("3", "1001", [
    { sequence: 1, beforeQuantity: "3", beforeValue: "1001", quantity: "1", value: "334" },
    { sequence: 2, beforeQuantity: "3", beforeValue: "1001", quantity: "1", value: "334", reverse: 0 },
    { sequence: 5, beforeQuantity: "3", beforeValue: "1001", quantity: "2", value: "667" },
  ]);
  expect(await parseTransfer(source, transferScope, "synthetic")).toEqual(source);
});
it("keeps a zero-valued portion bound to its positive plan-total cost effect", async () => {
  const source = await remainingFixture("2", "1", [{ sequence: 1, beforeQuantity: "2", beforeValue: "1", quantity: "1", value: "0", total: "1" }]);
  const original = source.cost_snapshot.sources[0], correction = (original.partial_return_corrections as Row[])[0];
  expect(correction.effect).not.toBeNull();
  expect(await parseTransfer(source, transferScope, "synthetic")).toEqual(source);
});
it("accepts legacy exact corrections beside a separate immutable v2-owner source in a v3 pool", async () => {
  const source = await remainingFixture("3", "1001", [{ sequence: 1, beforeQuantity: "3", beforeValue: "1001", quantity: "1", value: "334" }]);
  const extra = (await restitutionFixture()).cost_snapshot.sources[0];
  const legacy = (extra.partial_return_corrections as Row[])[0];
  const newId = "CRS2-" + "a".repeat(32);
  Object.assign(legacy.source as Row, { id: newId }); (legacy.plan as Row).source_id = newId;
  // Keep the legacy envelope exact; it remains in its own layer and source.
  const layer = extra.layer as Row; layer.id = "legacy-layer";
  (extra.receipt_link as Row).cost_layer_id = layer.id;
  (extra.consumptions as Row[])[0].cost_layer_id = layer.id;
  Object.assign(legacy.restoration as Row, { cost_layer_id: layer.id, source_id: newId });
  source.cost_snapshot.sources.push(extra);
  source.cost_snapshot.remaining_quantity_scaled = "3"; source.cost_snapshot.remaining_value_minor = "2734";
  // The new plan uses another id, avoiding the cross-pool immutable plan-position key.
  const current = (source.cost_snapshot.sources[0].partial_return_corrections as Row[])[0];
  await changeRemainingPlanIdentity(current, 9);
  await reseal(source); expect(await parseTransfer(source, transferScope, "synthetic")).toEqual(source);
});
it("rejects coherently resealed half-up cost where captured FIFO requires half-even", async () => {
  const wrong = await remainingFixture("2", "5", [{ sequence: 1, beforeQuantity: "2", beforeValue: "5", quantity: "1", value: "3" }]);
  // The pool, actual lines, reviewed snapshot, validation seal and exposures all
  // agree with 3. The captured remaining-value policy alone must refuse it.
  await expect(parseTransfer(wrong, transferScope, "synthetic")).rejects.toThrow("invalid");
  const right = await remainingFixture("2", "5", [{ sequence: 1, beforeQuantity: "2", beforeValue: "5", quantity: "1", value: "2" }]);
  expect(await parseTransfer(right, transferScope, "synthetic")).toEqual(right);
});
it.each([1, 2])("keeps retained cost-v%s creation evidence when the current review is cost-v3", async version => {
  const retained = version === 1 ? await transferFixture(true) : await restitutionFixture(true);
  const current = await remainingFixture("3", "1001", [{ sequence: 1, beforeQuantity: "3", beforeValue: "1001", quantity: "1", value: "334" }], true);
  retained.review_cost_snapshot = current.review_cost_snapshot;
  await reseal(retained); expect(await parseTransfer(retained, transferScope, "synthetic")).toEqual(retained);
});
it("replays independent remaining bases for two original sources that share one physical layer", async () => {
  const source = await remainingFixture("3", "1001", [
    { sequence: 1, beforeQuantity: "3", beforeValue: "1001", quantity: "1", value: "334" },
    { sequence: 1, beforeQuantity: "3", beforeValue: "1001", quantity: "2", value: "667" },
  ]);
  const layer = source.cost_snapshot.sources[0], rows = layer.partial_return_corrections as Row[];
  Object.assign(layer.layer as Row, { original_quantity_scaled: "6", original_value_minor: "2002" });
  const second = structuredClone((layer.consumptions as Row[])[0]); second.id = "second-sale-consumption";
  (layer.consumptions as Row[]).push(second);
  (rows[1].restoration as Row).original_consumption_id = second.id;
  const firstId = "CRS2-" + "a".repeat(32);
  (rows[0].source as Row).id = (rows[0].restoration as Row).source_id = (rows[0].plan as Row).source_id = firstId;
  await reseal(source); expect(await parseTransfer(source, transferScope, "synthetic")).toEqual(source);
});
it("refuses reversing an earlier return while a later return of the same source stays active on another layer", async () => {
  const source = await remainingFixture("3", "1001", [
    { sequence: 1, beforeQuantity: "3", beforeValue: "1001", quantity: "1", value: "334" },
    { sequence: 3, beforeQuantity: "3", beforeValue: "1001", quantity: "1", value: "334", reverse: 0 },
  ]);
  const extra = (await remainingFixture("3", "1001", [{ sequence: 2, beforeQuantity: "3", beforeValue: "1001", quantity: "1", value: "334" }])).cost_snapshot.sources[0];
  const row = (extra.partial_return_corrections as Row[])[0];
  await changeRemainingPlanIdentity(row, 9);
  Object.assign(extra.layer as Row, { id: "second-layer", source_valuation_line_id: "second-inbound-line" });
  (extra.valuation_line as Row).id = "second-inbound-line";
  (extra.receipt_link as Row).cost_layer_id = "second-layer";
  Object.assign((extra.consumptions as Row[])[0], { id: "second-consumption", cost_layer_id: "second-layer", valuation_line_id: "second-sale-line" });
  Object.assign(row.restoration as Row, { cost_layer_id: "second-layer", original_consumption_id: "second-consumption", original_valuation_line_id: "second-sale-line" });
  source.cost_snapshot.sources.push(extra);
  source.cost_snapshot.remaining_quantity_scaled = "1"; source.cost_snapshot.remaining_value_minor = "334";
  await reseal(source);
  await expect(parseTransfer(source, transferScope, "synthetic")).rejects.toThrow("invalid");
});
async function changeRemainingPlanIdentity(correction: Row, index: number): Promise<void> {
  const plan = correction.plan as Row, restored = correction.restoration as Row, physical = correction.physical as Row;
  const id = "CR2-" + index.toString(16).padStart(32, "0");
  plan.id = restored.plan_id = id;
  restored.physical_movement_id = `movement-${index}`;
  Object.assign(physical.head as Row, { id: restored.physical_movement_id, source_reference: id, movement_number: id.toUpperCase() });
  ((physical.lines as Row[])[0]).movement_id = restored.physical_movement_id;
  if (correction.entry !== null) {
    const entry = correction.entry as Row, effect = correction.effect as Row, snapshot = effect.snapshot_json as Row;
    entry.id = `entry-${index}`; effect.id = restored.correction_effect_id = `effect-${index}`;
    effect.entry_id = effect.source_id = entry.id;
    for (const [position, line] of (correction.lines as Row[]).entries()) { line.id = `line-${index}-${position}`; line.entry_id = entry.id; }
    entry.external_reference = id; entry.entry_number = id.toUpperCase() + "-C";
    Object.assign(snapshot.entry as Row, { id: entry.id, external_reference: entry.external_reference, entry_number: entry.entry_number });
    entry.validation_digest = effect.validation_digest = await transferDigest(snapshot, true);
  }
}
it.each(["before-quantity", "before-value", "policy", "extra-witness", "numeric-witness", "boolean-sequence", "late-sequence", "sequence-order", "zero-effect", "nonzero-null", "physical", "wrong-rounding", "source-drift"])("refuses sealed v3 %s drift", async field => {
  const source = await remainingFixture("3", "1001", [
    { sequence: 1, beforeQuantity: "3", beforeValue: "1001", quantity: "1", value: "334" },
    { sequence: 4, beforeQuantity: "2", beforeValue: "667", quantity: "1", value: "334" },
  ]);
  const rows = source.cost_snapshot.sources[0].partial_return_corrections as Row[], first = rows[0], second = rows[1], witness = second.allocation_witness as Row;
  if (field === "before-quantity") witness.before_quantity_scaled = "3";
  if (field === "before-value") witness.before_value_minor = "668";
  if (field === "policy") second.allocation_policy = "caller-priced";
  if (field === "extra-witness") witness.current_cost = "334";
  if (field === "numeric-witness") witness.before_value_minor = 667;
  if (field === "boolean-sequence") second.history_sequence = true;
  if (field === "late-sequence") second.history_sequence = 257;
  if (field === "sequence-order") first.history_sequence = 5;
  if (field === "zero-effect") { (second.plan as Row).cogs_restored_minor = "0"; (second.restoration as Row).value_minor = "0"; }
  if (field === "nonzero-null") { second.entry = second.effect = null; second.lines = []; second.dimensions = []; }
  if (field === "physical") (((second.physical as Row).lines as Row[])[0]).quantity_scaled = "0";
  if (field === "wrong-rounding") (second.restoration as Row).value_minor = "333";
  if (field === "source-drift") (second.source as Row).source_fingerprint = "e".repeat(64);
  await reseal(source); await expect(parseTransfer(source, transferScope, "synthetic")).rejects.toThrow("invalid");
});

async function restitutedZeroConsumptionFixture(mixed = false): Promise<TransferSource> {
  const transfer = await remainingFixture("3", "1", [{ sequence: 1, beforeQuantity: "3", beforeValue: "1", quantity: "1", value: "0" }]);
  const source = transfer.cost_snapshot.sources[0], layer = source.layer as Row;
  Object.assign(layer, { row_version: 2, workspace_id: "work", legal_entity_id: "entity" });
  const before = structuredClone(transfer.cost_snapshot);
  if (mixed) {
    const extra = structuredClone(source);
    Object.assign(extra.layer as Row, { id: "extra-layer", source_valuation_line_id: "extra-inbound", original_quantity_scaled: "1", original_value_minor: "10", remaining_quantity_scaled: "1", remaining_value_minor: "10" });
    (extra.valuation_line as Row).id = "extra-inbound"; (extra.receipt_link as Row).cost_layer_id = "extra-layer";
    extra.consumptions = []; extra.partial_return_corrections = [];
    before.sources.push(extra); before.remaining_quantity_scaled = "2"; before.remaining_value_minor = "10";
  }
  const stockId = "genuine-resale", entryNumber = "SS1-" + (await transferDigest(["synthetic", stockId], true)).slice(0, 32).toUpperCase();
  const policy = transfer.cost_snapshot.monetary_policy as Row;
  const allocations: Row[] = [{ cost_layer_id: layer.id, row_version: 2, remaining_quantity_scaled: "1", remaining_value_minor: "0", quantity_scaled: "1", value_minor: "0" }];
  if (mixed) allocations.push({ cost_layer_id: "extra-layer", row_version: 2, remaining_quantity_scaled: "1", remaining_value_minor: "10", quantity_scaled: "1", value_minor: "10" });
  const issue: Row = { schema_version: "stock-sales-issue-v2", preparer_actor_id: "maker", preparer_username: "maker-name", source_digest: "a".repeat(64),
    request: { posting_date: "2026-10-15", period_id: "period", policy_code: "FIFO", reason: "Actual original native plan" }, allocations, total_cost_minor: mixed ? "10" : "0",
    policy_id: "policy", inventory_account_id: "inventory-account", cogs_account_id: "cogs-account", entry_id: mixed ? "resale-entry" : null, entry_number: entryNumber, journal_id: "STOCK",
    currency_policy: { currency_code: policy.currency_code, precision: policy.currency_precision, rounding_policy: policy.currency_rounding_policy, registry_version: policy.currency_registry_version, registry_digest: policy.currency_registry_digest },
    cost_admission_policy: "partial-return-restituted-v1", restitution_cost_snapshot: before };
  const document: Row = { id: "resale-valuation", tenant_id: "synthetic", ...transferScope, status: "Approved", ...policy, total_value_minor: issue.total_cost_minor, finance_entry_id: issue.entry_id,
    policy_id: "policy", period_id: "period", valuation_date: "2026-10-15", valuation_number: entryNumber, movement_id: "resale-physical" };
  const valuationLine: Row = { id: "zero-sale-valuation-line", tenant_id: "synthetic", valuation_document_id: document.id, flow_direction: "Outbound", line_number: 1, item_id: layer.item_id,
    uom_id: layer.uom_id, quantity_precision: layer.quantity_precision, quantity_scaled: mixed ? "2" : "1", value_minor: issue.total_cost_minor, inventory_account_id: issue.inventory_account_id, offset_account_id: issue.cogs_account_id, movement_line_id: "resale-physical-line" };
  let effect: Row | null = null;
  if (mixed) {
    const snapshot = { schema_version: "finance-entry-review-v1", entry: { id: issue.entry_id, ...transferScope, journal_id: issue.journal_id, period_id: "period", posting_date: "2026-10-15", entry_number: entryNumber,
      external_reference: stockId, source_type: "Manual", preparer_actor_id: "maker", reverses_posting_id: null, ...policy }, lines: [
      { line_number: 1, account_id: "cogs-account", description: "Native total COGS", debit_minor: "10", credit_minor: "0", dimensions: {} },
      { line_number: 2, account_id: "inventory-account", description: "Native total COGS", debit_minor: "0", credit_minor: "10", dimensions: {} }] };
    effect = { id: "resale-cost-effect", tenant_id: "synthetic", ...transferScope, entry_id: issue.entry_id, source_kind: "Manual", source_id: issue.entry_id, purpose: "operational_posting", reverses_effect_id: null,
      validation_contract_version: "finance-entry-review-v1", validation_digest: await transferDigest(snapshot, true), snapshot_json: snapshot, ...policy };
  }
  const admission: Row = { consumption_id: "zero-consumption", stock_order_id: stockId, cost_admission_policy: "partial-return-restituted-v1", issue_plan: issue, valuation_document: document, valuation_line: valuationLine, posting_effect: effect,
    physical: { head: { id: "resale-physical", tenant_id: "synthetic", ...transferScope, source_reference: stockId, movement_number: entryNumber, status: "Posted", source_type: "Generated", movement_type: "Delivery", period_id: "period", movement_date: "2026-10-15" },
      lines: [{ id: "resale-physical-line", tenant_id: "synthetic", movement_id: "resale-physical", line_number: 1, item_id: layer.item_id, uom_id: layer.uom_id, quantity_precision: layer.quantity_precision, inventory_lot_id: null,
        quantity_scaled: valuationLine.quantity_scaled, from_location_id: "source-location", to_location_id: null }], audit: [{}], outbox: [{}] } };
  const correction = await restitutionCorrection(9), original = correction.source as Row, plan = correction.plan as Row, restored = correction.restoration as Row;
  const sourceId = "CRS2-" + "c".repeat(32);
  Object.assign(original, { id: sourceId, original_cogs_effect_id: effect?.id ?? null, original_cost_minor: issue.total_cost_minor, cost_admission_digest: "e".repeat(64) });
  Object.assign(plan, { source_id: sourceId, cogs_restored_minor: "0" });
  Object.assign(restored, { source_id: sourceId, original_consumption_id: "zero-consumption", original_valuation_line_id: valuationLine.id, value_minor: "0", correction_effect_id: null, original_cogs_effect_id: original.original_cogs_effect_id });
  Object.assign(correction, { history_sequence: 1, allocation_policy: "remaining-original-v1", allocation_witness: { before_quantity_scaled: "1", before_value_minor: "0" }, entry: null, effect: null, lines: [], dimensions: [] });
  (source.consumptions as Row[]).push({ id: "zero-consumption", tenant_id: "synthetic", cost_layer_id: layer.id, valuation_line_id: valuationLine.id, quantity_scaled: "1", value_minor: "0" });
  source.restituted_consumption_admissions = [admission];
  (source.partial_return_corrections as Row[]).push(correction);
  return reseal(transfer);
}
it.each([false, true])("admits only explicit restituted zero-consumption ownership with mixed total=%s", async mixed => {
  const source = await restitutedZeroConsumptionFixture(mixed);
  expect(await parseTransfer(source, transferScope, "synthetic")).toEqual(source);
});
it.each([false, true])("keeps a v4 monetary zero consumption bound to its actual functional Stock admission, mixed=%s", async mixed => {
  const transfer = await restitutedZeroConsumptionFixture(mixed), pool = transfer.cost_snapshot.sources[0];
  const rows = pool.partial_return_corrections as Row[], row = rows.pop()!, restored = row.restoration as Row, original = row.source as Row;
  const admission = (pool.restituted_consumption_admissions as Row[])[0], issue = admission.issue_plan as Row;
  const before = issue.restitution_cost_snapshot as TransferSource["cost_snapshot"];
  before.schema_version = "inventory-transfer-cost-v4";
  for (const source of before.sources) source.monetary_return_corrections = [];
  const id = String((row.plan as Row).id).replace(/^CR2/, "CR3"), origin = "MSO-" + "c".repeat(32);
  row.source = { id: origin, source_digest: original.source_fingerprint, stock_order_id: admission.stock_order_id, ...transferScope,
    item_id: original.item_id, uom_id: original.uom_id, quantity_precision: original.quantity_precision, location_id: original.location_id,
    original_cogs_effect_id: original.original_cogs_effect_id, original_cost_minor: original.original_cost_minor };
  row.plan = { id, source_id: origin, operation: "Return", phase: 2, plan_digest: (row.plan as Row).plan_digest, functional_cost_minor: "0" };
  delete restored.source_id; delete restored.offset_quantity_scaled; delete restored.original_cogs_effect_id;
  Object.assign(restored, transferScope, { origin_id: origin, plan_id: id, before_quantity_scaled: "1", before_value_minor: "0" });
  row.allocation_policy = "remaining-dual-currency-v1"; delete row.allocation_witness;
  Object.assign((row.physical as Row).head as Row, { source_reference: id, movement_number: id.toUpperCase() });
  pool.monetary_return_corrections = [row];
  transfer.cost_snapshot.schema_version = "inventory-transfer-cost-v4";
  await reseal(transfer); expect(await parseTransfer(transfer, transferScope, "synthetic")).toEqual(transfer);
  (row.source as Row).stock_order_id = "different-stock";
  await reseal(transfer); await expect(parseTransfer(transfer, transferScope, "synthetic")).rejects.toThrow("invalid");
});
it.each(["missing", "extra", "foreign-consumption", "stock", "policy", "zero-effect", "nonzero-absence", "physical", "valuation", "valuation-amount", "original-cost", "original-effect", "admission-digest", "historical-pool", "allocation", "rounding", "policy-context", "scope", "extra-issue", "effect-seal"])("refuses resealed restituted zero-consumption %s drift", async variant => {
  const source = await restitutedZeroConsumptionFixture(variant === "nonzero-absence" || variant === "effect-seal"), pool = source.cost_snapshot.sources[0];
  const admission = (pool.restituted_consumption_admissions as Row[])[0], issue = admission.issue_plan as Row, corrections = pool.partial_return_corrections as Row[], correction = corrections[1];
  if (variant === "missing") delete pool.restituted_consumption_admissions;
  if (variant === "extra") admission.secret = "unknown";
  if (variant === "foreign-consumption") admission.consumption_id = "foreign";
  if (variant === "stock") admission.stock_order_id = "foreign-stock";
  if (variant === "policy") admission.cost_admission_policy = "unproved-zero";
  if (variant === "zero-effect") admission.posting_effect = { id: "counterfeit-zero" };
  if (variant === "nonzero-absence") admission.posting_effect = null;
  if (variant === "physical") (((admission.physical as Row).lines as Row[])[0]).from_location_id = null;
  if (variant === "valuation") (admission.valuation_line as Row).id = "foreign";
  if (variant === "valuation-amount") (admission.valuation_document as Row).total_value_minor = "1";
  if (variant === "original-cost") (correction.source as Row).original_cost_minor = "1";
  if (variant === "original-effect") (correction.source as Row).original_cogs_effect_id = "invented";
  if (variant === "admission-digest") delete (correction.source as Row).cost_admission_digest;
  if (variant === "historical-pool") (issue.restitution_cost_snapshot as Row).remaining_value_minor = "999";
  if (variant === "allocation") (issue.allocations as Row[])[0].row_version = 77;
  if (variant === "rounding") (issue.allocations as Row[])[0].value_minor = "1";
  if (variant === "policy-context") (issue.currency_policy as Row).precision = 3;
  if (variant === "scope") (admission.valuation_document as Row).legal_entity_id = "foreign";
  if (variant === "extra-issue") issue.unknown = "extra";
  if (variant === "effect-seal") (admission.posting_effect as Row).validation_digest = "0".repeat(64);
  await reseal(source); await expect(parseTransfer(source, transferScope, "synthetic")).rejects.toThrow("invalid");
});
it.each([1, 2])("keeps cost-v%s zero-consumption refusal despite a copied new admission", async version => {
  const source = await restitutedZeroConsumptionFixture(); source.cost_snapshot.schema_version = `inventory-transfer-cost-v${version}`;
  await reseal(source); await expect(parseTransfer(source, transferScope, "synthetic")).rejects.toThrow("invalid");
});
