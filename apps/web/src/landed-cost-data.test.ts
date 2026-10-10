import { afterEach, expect, it, vi } from "vitest";
import { landedCommand, landedPage, parseLandedPlan } from "./landed-cost-data";
import type { ProcurementScope } from "./procurement-data";
import { prepareScopedCommand } from "./scoped-command";
import type { BrowserAdminSession } from "./types";

const scope: ProcurementScope = { workspace_id: "work", organization_id: "org", legal_entity_id: "entity", organization_code: "ORG", entity_code: "ENTITY", organization_name: "Organization", entity_name: "Entity", currency_code: "USD" };
function plan() { return { id: "LC1-plan", order_id: "order", number: "PAID-1", workspace_id: "work", organization_id: "org", legal_entity_id: "entity", phase: 0, status: "Prepared", plan_digest: "a".repeat(64), freight_minor: "9007199254740993", duty_minor: "0", amount_minor: "9007199254740993", currency_code: "USD", entry_id: "native-entry", preparer_actor_id: "maker", reviewer_actor_id: null, posted_actor_id: null, posting_effect_id: null, allocations: [{ sequence: 1, order_line_id: "line", quantity_text: "1", base_minor: "1", freight_minor: "9007199254740993", duty_minor: "0", receipt_id: "receipt", receipt_plan_id: "native-receipt", stage: 0 }] }; }
afterEach(() => vi.unstubAllGlobals());

it("conserves paid charges above JavaScript safe integer range", () => {
  expect(parseLandedPlan(plan(), scope, "order").amount_minor).toBe("9007199254740993");
  const source = plan(); source.allocations[0].freight_minor = "9007199254740992";
  expect(() => parseLandedPlan(source, scope, "order")).toThrow("contract_invalid");
});

it("refuses cross-scope and detached third-person posting projections", () => {
  expect(() => parseLandedPlan({ ...plan(), legal_entity_id: "outside" }, scope, "order")).toThrow("contract_invalid");
  expect(() => parseLandedPlan({ ...plan(), phase: 2, status: "Posted", reviewer_actor_id: "checker", posted_actor_id: "checker", posting_effect_id: "effect" }, scope, "order")).toThrow("contract_invalid");
  expect(() => parseLandedPlan(plan(), scope, "wrong-order")).toThrow("contract_invalid");
});

it("keeps exact nested request and scoped CSRF command through lost acknowledgement retry", async () => {
  const source = { order_id: "order", number: "PAID-1", freight_minor: "9007199254740993", duty_minor: "0", lines: [{ line_id: "line", quantity: "1" }] };
  const command = prepareScopedCommand("/api/v1/landed-cost/plans", source);
  source.lines[0].quantity = "999";
  const fetch = vi.fn().mockResolvedValueOnce({ ok: true, json: async () => ({ unrelated: true }) }).mockResolvedValueOnce({ ok: true, json: async () => plan() });
  vi.stubGlobal("fetch", fetch);
  const session = { tenantId: "tenant", csrfToken: "synthetic-csrf" } as BrowserAdminSession;
  await expect(landedCommand(session, scope, "order", command)).rejects.toThrow("contract_invalid");
  expect((await landedCommand(session, scope, "order", command)).id).toBe("LC1-plan");
  expect(fetch.mock.calls[0][1].body).toBe(fetch.mock.calls[1][1].body);
  expect(JSON.parse(fetch.mock.calls[0][1].body).lines[0].quantity).toBe("1");
  expect(fetch.mock.calls[0][1]).toMatchObject({ method: "POST", credentials: "same-origin", headers: { "X-ReconForge-CSRF": "synthetic-csrf", "X-ReconForge-Legal-Entity": "entity", "X-ReconForge-Workspace": "work" } });
});


it("refuses a well-formed response for another requested quantity or owner stage", async () => {
  const session = { tenantId: "tenant", csrfToken: "synthetic-csrf" } as BrowserAdminSession;
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => plan() }));
  await expect(landedCommand(session, scope, "order", prepareScopedCommand("/api/v1/landed-cost/plans", {
    order_id: "order", number: "PAID-1", freight_minor: "9007199254740993", duty_minor: "0", lines: [{ line_id: "line", quantity: "2" }]
  }))).rejects.toThrow("contract_invalid");
  await expect(landedCommand(session, scope, "order", prepareScopedCommand("/api/v1/landed-cost/plans/LC1-plan/review", {
    expected_plan_digest: "a".repeat(64), reason: "Review"
  }))).rejects.toThrow("contract_invalid");
  expect(() => parseLandedPlan({ ...plan(), posting_effect_id: "detached" }, scope, "order")).toThrow("contract_invalid");
});


it("loads scoped bundle evidence through the strict query transport", async () => {
  const fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ records: [plan()], next_after: null }) });
  vi.stubGlobal("fetch", fetch);
  const session = { tenantId: "tenant", csrfToken: "synthetic-csrf" } as BrowserAdminSession;
  expect((await landedPage(session, scope, "order")).records[0].id).toBe("LC1-plan");
  expect(fetch.mock.calls[0][0]).toBe("/api/v1/landed-cost/orders/order?after=");
  expect(fetch.mock.calls[0][1]).toMatchObject({ method: "GET", credentials: "same-origin", headers: { "X-ReconForge-Tenant": "tenant", "X-ReconForge-Workspace": "work", "X-ReconForge-Organization": "org", "X-ReconForge-Legal-Entity": "entity" } });
});
