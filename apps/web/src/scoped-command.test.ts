import { describe, expect, it } from "vitest";
import { isPartialReturnV2Path, prepareScopedCommand, type ScopedJsonValue } from "./scoped-command";

it("admits only the finite partial-return v2 command routes without broadening other v2 domains", () => {
  const root = "/api/v2/customer-partial-returns", id = "a".repeat(32);
  const paths = [`${root}/plans`, `${root}/plans/CR2-${id}/refunds`, `${root}/plans/CR2-${id}/reversals`, `${root}/plans/CRF2-${id}/reversals`,
    ...["CR2", "CRF2", "CR2R", "CRF2R"].flatMap(prefix => ["review", "post", "cancel"].map(action => `${root}/plans/${prefix}-${id}/${action}`))];
  for (const path of paths) {
    const body = { expected_history_version: 1, reason: "Original retained command" }, command = prepareScopedCommand(path, body);
    body.expected_history_version = 2;
    expect(command.path).toBe(path); expect(command.body.expected_history_version).toBe(1); expect(Object.isFrozen(command.body)).toBe(true);
  }
  for (const path of ["/api/v2/finance-core/entries/x/post", `${root}/plans/../finance-core/entries/x/post`, `${root}/plans?mode=legacy`, `${root}/plans/CR2R-${id}/refunds`, `${root}/plans/CR2R-${id}/reversals`, `${root}/sources/x/balance`, `${root}/plans/${id}/post`, `${root}/plans#fragment`]) expect(() => prepareScopedCommand(path, {})).toThrow();
  for (const path of [`${root}/sources/../balance`, `${root}/sources/%2e%2e/balance`, `${root}/sources/a%2Fb/balance`, `${root}/sources/%00/balance`]) expect(isPartialReturnV2Path(path, false)).toBe(false);
});

describe("captured multiline command retries", () => {
  it("retains nested exact amounts and quantities after caller edits", () => {
    const line = { quantity: "1.234", unit_price_minor: "9000000000000000000" };
    const body = { lines: [line], expected_version: 1 };
    const command = prepareScopedCommand("/api/v1/procurement-partial/orders/multiline", body);
    const sent = JSON.stringify(command.body);
    line.quantity = "999"; body.lines.push(line); body.expected_version = 2;
    expect(JSON.stringify(command.body)).toBe(sent);
    expect(Object.isFrozen(command.body.lines)).toBe(true);
    expect(Object.isFrozen((command.body.lines as readonly object[])[0])).toBe(true);
    expect(command.body.command_id).toBeTruthy();
  });
  it("rejects cycles, non-JSON objects, non-finite numbers and unsafe integers", () => {
    const cycle: Record<string, ScopedJsonValue> = {}; cycle.self = cycle;
    for (const body of [cycle, { amount: NaN }, { amount: Infinity }, { amount: Number.MAX_SAFE_INTEGER + 1 }, { value: new Date() as unknown as ScopedJsonValue }]) {
      expect(() => prepareScopedCommand("/api/v1/test", body)).toThrow("scoped_command_invalid");
    }
  });
  it("bounds depth and nodes before retaining a command", () => {
    let value: ScopedJsonValue = "leaf";
    for (let index = 0; index < 13; index++) value = [value];
    expect(() => prepareScopedCommand("/api/v1/test", { value })).toThrow("scoped_command_invalid");
    expect(() => prepareScopedCommand("/api/v1/test", { lines: Array(20000).fill("line") })).toThrow("scoped_command_invalid");
  });
});
