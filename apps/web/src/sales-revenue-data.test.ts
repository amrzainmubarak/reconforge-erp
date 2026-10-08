import { describe, expect, it } from "vitest";
import { prepareSalesCommand, salesMoney } from "./sales-revenue-data";

describe("governed sales financial transport", () => {
  it("preserves money above Number precision and non-two-decimal currencies", () => {
    expect(salesMoney("9007199254740993", "USD", 2, "en")).toBe("90,071,992,547,409.93 USD");
    expect(salesMoney("1234", "KWD", 3, "en")).toBe("1.234 KWD");
    expect(salesMoney("1234", "JPY", 0, "en")).toBe("1,234 JPY");
  });
  it("freezes nested financial input and selected hierarchy for lost acknowledgements", () => {
    const scope = { workspace_id: "W", organization_id: "O", legal_entity_id: "E" };
    const lines = [{ unit_price_minor: "9007199254740993", quantity: "1", discount_basis_points: 0 }];
    const command = prepareSalesCommand(scope, "/api/v1/sales-revenue/quotations", { lines });
    lines[0].unit_price_minor = "1"; scope.workspace_id = "OTHER";
    expect((command.body.lines as typeof lines)[0].unit_price_minor).toBe("9007199254740993");
    expect(command.scope.workspace_id).toBe("W");
    expect(Object.isFrozen((command.body.lines as typeof lines)[0])).toBe(true);
  });
  it("rejects alternate endpoint or command identifier injection", () => {
    const scope = { workspace_id: "W", organization_id: "O", legal_entity_id: "E" };
    expect(() => prepareSalesCommand(scope, "/api/v1/other", {})).toThrow();
    expect(() => prepareSalesCommand(scope, "/api/v1/sales-revenue/quotations", { command_id: "spoof" })).toThrow();
  });
});
