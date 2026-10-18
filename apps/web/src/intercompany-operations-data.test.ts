import { afterEach, describe, expect, it, vi } from "vitest";
import { canonicalIc, icRequest, mergeIcPlan, parseIcDetail, parseIcPlan, verifyIcEvidence } from "./intercompany-operations-data";
import { icFixture } from "./intercompany-operations-test-fixture";
const scope = { workspace_id: "work", organization_id: "org" };
afterEach(() => vi.restoreAllMocks());
describe("three-book exact source contract", () => {
  it("verifies every source, native entry, independent actor and audit/outbox seal", async () => {
    const { proof, detail } = await icFixture();
    expect(await verifyIcEvidence(proof, scope, proof.plan)).toEqual(proof);
    expect(parseIcDetail(detail, scope).outstanding_minor).toBe("10001");
    expect(canonicalIc({ amount_minor: "4500000000000000000", phase: 2 })).toBe('{"amount_minor":4500000000000000000,"phase":2}');
  });
  it.each(["half", "entity", "money", "status", "actor", "effect", "snapshot", "outbox"])("rejects %s tampering", async attack => {
    const { proof } = await icFixture(); const damaged = structuredClone(proof);
    if (attack === "half") damaged.plan.entries.pop();
    if (attack === "entity") damaged.plan.buyer_entity_id = "seller";
    if (attack === "money") damaged.plan.entries[0].snapshot.lines[0].debit_minor = "10002";
    if (attack === "status") damaged.plan.status = "Reviewed";
    if (attack === "actor") damaged.plan.posted_actor_id = "checker";
    if (attack === "effect") damaged.native_effects[0].id = "unique-unbound-effect";
    if (attack === "snapshot") damaged.canonical_snapshot_jsons[0] += " ";
    if (attack === "outbox") damaged.phases[2].outbox_event_id = damaged.phases[0].outbox_event_id;
    await expect(verifyIcEvidence(damaged, scope, proof.plan)).rejects.toThrow();
  });
  it("does not let a delayed prepared acknowledgement overwrite the posted native pair", async () => {
    const { proof } = await icFixture(), prepared = { ...proof.plan, phase: 0, status: "Prepared" as const, reviewer_actor_id: null, posted_actor_id: null, posting_effect_ids: {} };
    expect(parseIcPlan(prepared, scope).phase).toBe(0);
    expect(mergeIcPlan(proof.plan, prepared)).toEqual(proof.plan);
  });
  it("uses organization context without a fabricated or cleared entity grant header", async () => {
    const fetch = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("{}", { status: 200 }));
    await icRequest({ tenantId: "synthetic", csrfToken: "csrf", expiresAt: "2099-01-01" }, scope, "/api/v1/intercompany-operations/sources", { command_id: "unchanged" });
    const options = fetch.mock.calls[0][1], headers = new Headers(options?.headers);
    expect(headers.get("X-ReconForge-Organization")).toBe("org"); expect(headers.has("X-ReconForge-Legal-Entity")).toBe(false);
    expect(headers.get("X-ReconForge-CSRF")).toBe("csrf"); expect(options?.credentials).toBe("same-origin");
  });
});
