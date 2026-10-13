import { webcrypto } from "node:crypto";
import { beforeEach, expect, it, vi } from "vitest";
import { parseTransfer, parseTransferAck, transferDigest, transferMoney, transferRoot } from "./inventory-transfer-data";
import { transferAck, transferBody, transferFixture, transferScope } from "./inventory-transfer-test-fixtures";
import { prepareScopedCommand } from "./scoped-command";

beforeEach(() => vi.stubGlobal("crypto", webcrypto));
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
