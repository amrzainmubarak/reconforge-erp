import { webcrypto } from "node:crypto";
import { beforeEach, expect, it, vi } from "vitest";
import { parseSupplyCommandAck, parseSupplyPlan, scaledSupplyText, supplyPlainCanonical } from "./manufacturing-supply-data";
import { supplyApprovalAck, supplyCreateAck, supplyFixture, supplyScope } from "./manufacturing-supply-test-fixtures";
import originalNativeHandoff from "./fixtures/manufacturing-supply-original-handoff.json";
import originalNativeCommandAcks from "./fixtures/manufacturing-supply-original-command-acks.json";
import type { PreparedScopedCommand } from "./scoped-command";
beforeEach(() => vi.stubGlobal("crypto", webcrypto));
it.each(originalNativeCommandAcks.records)("qualifies actual original native $operation command $command.body.command_id", async record => {
  expect(originalNativeCommandAcks.origin_proof_sha256).toBe("9f49c6c5c523a0f0d7e65a457c727fc741bcec367cd3d6b98ce6098f90476590");
  const value = await parseSupplyCommandAck(record.response, record.command as unknown as PreparedScopedCommand, supplyScope, record.binding);
  expect(value.id).toBe(record.response.source.id); expect(value.row_version).toBe(record.response.source.row_version);
});
const plainHash = async (value: unknown) => [...new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(supplyPlainCanonical(value))))].map(part => part.toString(16).padStart(2, "0")).join("");
it("refuses a changed quote body even when the echoed body is freshly sealed against the original same-source native receipt", async () => {
  const record = structuredClone(originalNativeCommandAcks.records.find(row => row.operation === "source-quote")!);
  const command = record.command as unknown as PreparedScopedCommand;
  const changed = { ...command, body: { ...command.body, unit_prices_minor: ["1199", "100"] } };
  record.response.submitted_request = changed.body as never;
  record.response.submitted_request_digest = await plainHash(changed.body);
  await expect(parseSupplyCommandAck(record.response, changed, supplyScope, record.binding)).rejects.toThrow("manufacturing_supply_evidence_invalid");
});
it("refuses a correct sealed source when its native receipt belongs to a different selected requisition", async () => {
  const record = structuredClone(originalNativeCommandAcks.records.find(row => row.operation === "source-quote")!);
  const command = record.command as unknown as PreparedScopedCommand;
  const foreign = { ...command, path: command.path.replace(String(record.response.command_ack.native_owner_id), "PSREQ-FOREIGN") };
  await expect(parseSupplyCommandAck(record.response, foreign, supplyScope, record.binding)).rejects.toThrow("manufacturing_supply_evidence_invalid");
});
it("verifies the original retained nonowner PostgreSQL full-cycle handoff artifact", async () => {
  const source = await parseSupplyPlan(originalNativeHandoff.source, supplyScope);
  expect(source.source_digest).toBe("83168181ab5117bd761d25e3b9a861d9d63b8f32ec095a7eb281d35620b1785d");
  expect(source.phase).toBe(2); expect(source.stock_claims).toHaveLength(5);
  expect(source.manufacturing_order_id).toBe("ME2-2181CB7D9D52454C873CE198AC999074");
});
it.each(["actor", "command", "body", "request_digest", "native_response", "version", "scope", "reviewer", "missing_receipt"])("refuses unqualified retained original command ACK %s", async mutation => {
  const draft = await supplyFixture(), source = await supplyFixture(true);
  const command = { path: `/api/v1/manufacturing-supply-plan/plans/${draft.id}/approve`, body: { command_id: "original-command", expected_digest: draft.source_digest, reason: "Original exact approval" } };
  const ack: Record<string, any> = await supplyApprovalAck(command, source);
  if (mutation === "actor") ack.command_ack.actor_id = "foreign-human";
  if (mutation === "command") ack.command_ack.command_id = "other-command";
  if (mutation === "body") ack.submitted_request = { ...ack.submitted_request, reason: "Other business intent" };
  if (mutation === "request_digest") ack.command_ack.request_digest = "0".repeat(64);
  if (mutation === "native_response") ack.native_response = { id: "DETACHED-NATIVE-OWNER" };
  if (mutation === "version") ack.command_ack.version = 3;
  if (mutation === "scope") ack.command_ack.scope = { ...supplyScope, workspace_id: "sibling" };
  if (mutation === "reviewer") ack.source = { ...ack.source, reviewer_actor_id: "foreign-human" };
  if (mutation === "missing_receipt") delete ack.command_ack;
  await expect(parseSupplyCommandAck(ack, command, supplyScope, { actorId: "checker", previousVersion: 1 })).rejects.toThrow("manufacturing_supply_evidence_invalid");
});
it("accepts the exact historical native command receipt repeatedly before a later authoritative source read", async () => {
  const source = await supplyFixture(true);
  const command = { path: `/api/v1/manufacturing-supply-plan/plans/${source.id}/approve`, body: { command_id: "original-command", expected_digest: source.source_digest, reason: "Original exact approval" } };
  const ack = await supplyApprovalAck(command, source);
  const binding = { actorId: "checker", previousVersion: 1 };
  expect(await parseSupplyCommandAck(ack, command, supplyScope, binding)).toEqual(source);
  expect(await parseSupplyCommandAck(ack, command, supplyScope, binding)).toEqual(source);
});
it("binds sealed creation to the actual retained maker body rather than an unrelated sealed demand", async () => {
  const source = await supplyFixture();
  const implicit = new Set(["schema_version", "workspace_id", "organization_id", "legal_entity_id", "organization_code", "entity_code"]);
  const material = Object.fromEntries(Object.entries(source.command_request.material).filter(([key]) => !implicit.has(key)));
  const body = { ...material, command_id: "create-original", routing_id: source.routing_id, budget_id: source.budget_id,
    unit_price_ceilings_minor: [{ item_code: "MATERIAL", unit_price_minor: "100" }] };
  const command = { path: "/api/v1/manufacturing-supply-plan/plans", body };
  const ack = await supplyCreateAck(command, source);
  expect(await parseSupplyCommandAck(ack, command, supplyScope, { actorId: "maker", previousVersion: null })).toEqual(source);
  const altered = { ...command, body: { ...body, number: "OTHER-ORIGINAL-DEMAND" } };
  const changedEcho = await supplyCreateAck(altered, source);
  await expect(parseSupplyCommandAck(changedEcho, altered, supplyScope, { actorId: "maker", previousVersion: null })).rejects.toThrow("manufacturing_supply_evidence_invalid");
});
it("keeps original engineering gross, actual custody and exact net shortage independently verifiable", async () => {
  const source = await parseSupplyPlan(await supplyFixture(true), supplyScope);
  expect(source.planned_requirements[0].coverage).toMatchObject({ onhand_reserved_scaled: "500", shortage_quantity_scaled: "2500" });
  expect(scaledSupplyText("2500", 3)).toBe("2.500"); expect(scaledSupplyText("9000000000000000000", 6)).toBe("9000000000000.000000");
});
it.each(["scope", "digest", "coverage", "unknown_schema", "unsafe_number"])("refuses a changed original %s", async mutation => {
  const source = await supplyFixture(true);
  if (mutation === "scope") source.workspace_id = "sibling";
  if (mutation === "digest") source.source_digest = "0".repeat(64);
  if (mutation === "coverage") source.planned_requirements[0].coverage!.shortage_quantity_scaled = "2499";
  if (mutation === "unknown_schema") source.schema_version = "future-schema";
  if (mutation === "unsafe_number") (source.requirements[0] as unknown as Record<string, unknown>).required_quantity_scaled = Number.MAX_SAFE_INTEGER + 1;
  await expect(parseSupplyPlan(source, supplyScope)).rejects.toThrow("manufacturing_supply_evidence_invalid");
});
