import { describe, expect, it } from "vitest";
import { prepareScopedCommand, type ScopedJsonValue } from "./scoped-command";

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
