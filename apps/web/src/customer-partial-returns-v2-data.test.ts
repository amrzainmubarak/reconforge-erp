import { afterEach, expect, it, vi } from "vitest";
import { parsePartialReturnBalance, parsePartialReturnBalanceUnion, parsePartialReturnBalanceV2, parsePartialReturnPlan, parsePartialReturnPlanUnion, parsePartialReturnPlanV2, partialPlanMatchesCommandUnion, partialReturnRequest, partialReturnRequestV2, partialReturnsRoot, partialReturnsRootV2 } from "./customer-partial-returns-data";
import { partialBalanceFixture, partialPlanFixture, partialScope } from "./customer-partial-returns-test-fixtures";
import { remainderBalanceFixture, remainderPlanFixture } from "./customer-partial-returns-v2-test-fixtures";
import { prepareScopedCommand } from "./scoped-command";

afterEach(() => vi.unstubAllGlobals());
it.each([["0", "0"], ["0", "334"], ["1000", "0"], ["1000", "334"]])("admits only the real monetary legs for credit %s and cost %s", (credit, cost) => {
  for (const operation of ["Return", "ReverseReturn"] as const) for (const phase of [0, 1, 2, 3] as const) {
    const plan = remainderPlanFixture(credit, cost, phase, operation);
    expect(parsePartialReturnPlanV2(plan, partialScope)).toEqual(plan);
    expect(plan.entries).toHaveLength(Number(credit !== "0") + Number(cost !== "0"));
    expect(() => parsePartialReturnPlan(plan, partialScope)).toThrow();
  }
});
it("keeps zero-cost and zero-revenue operations governed without a phantom financial entry", () => {
  for (const plan of [remainderPlanFixture("0", "0", 2), remainderPlanFixture("0", "334", 2), remainderPlanFixture("1000", "0", 2)]) {
    for (const patch of [{ entries: partialPlanFixture(2).entries }, { poster_actor_id: "checker" }, { poster_actor_id: null }, { reviewer_actor_id: "maker" }, { quantity_scaled: "0" }, { amount_minor: "1335" }]) expect(() => parsePartialReturnPlanV2({ ...plan, ...patch }, partialScope)).toThrow();
    if (plan.entries.length) expect(() => parsePartialReturnPlanV2({ ...plan, entries: plan.entries.map(entry => ({ ...entry, purpose: entry.purpose === "RevenueCredit" ? "CostRestoration" : "RevenueCredit" })) }, partialScope)).toThrow();
  }
});
it.each(["Refund", "ReverseRefund"] as const)("keeps %s positive and tied to exactly one real effect", operation => {
  const plan = remainderPlanFixture("0", "0", 2, operation);
  expect(parsePartialReturnPlanV2(plan, partialScope).entries).toHaveLength(1);
  for (const patch of [{ amount_minor: "0" }, { entries: [] }, { quantity_scaled: "1" }, { credit_minor: "1" }]) expect(() => parsePartialReturnPlanV2({ ...plan, ...patch }, partialScope)).toThrow();
});
it.each([null, true, 1, {}, [], "ROUND_HALF_UP", "remaining-original-v2", " remaining-original-v1"])("refuses an invented allocation rule %s", allocation_policy => {
  expect(() => parsePartialReturnPlanV2({ ...remainderPlanFixture(), allocation_policy }, partialScope)).toThrow();
  expect(() => parsePartialReturnBalanceV2({ ...remainderBalanceFixture(), allocation_policy }, partialScope, "stock-original")).toThrow();
});
it("keeps the public union closed and the legacy readers unchanged", () => {
  const old = partialPlanFixture(), current = remainderPlanFixture();
  expect(parsePartialReturnPlanUnion(old, partialScope)).toEqual(old);
  expect(parsePartialReturnPlanUnion(current, partialScope)).toEqual(current);
  expect(() => parsePartialReturnPlan({ ...old, allocation_policy: "remaining-original-v1" }, partialScope)).toThrow();
  for (const patch of [{ schema_version: "customer-partial-return-v3" }, { domain_plan: { before_value_minor: "1001" } }, { source_snapshot: {} }]) expect(() => parsePartialReturnPlanUnion({ ...current, ...patch }, partialScope)).toThrow();
  expect(parsePartialReturnBalanceUnion(partialBalanceFixture(), partialScope, "stock-original")).toEqual(partialBalanceFixture());
  expect(parsePartialReturnBalanceUnion(remainderBalanceFixture(), partialScope, "stock-original")).toEqual(remainderBalanceFixture());
  expect(() => parsePartialReturnBalance(remainderBalanceFixture(), partialScope, "stock-original")).toThrow();
  expect(() => parsePartialReturnBalanceUnion({ ...remainderBalanceFixture(), schema_version: "unknown" }, partialScope, "stock-original")).toThrow();
});
it("uses exact amounts beyond the JavaScript safe integer boundary and refuses coercion", () => {
  const plan = remainderPlanFixture("9007199254740993", "334");
  expect(parsePartialReturnPlanV2(plan, partialScope).amount_minor).toBe("9007199254741327");
  for (const value of [0, true, 0.1, "00", "0.0", "1e3", "-1", "9000000000000000001"]) expect(() => parsePartialReturnPlanV2({ ...plan, cogs_restored_minor: value }, partialScope)).toThrow();
});
it("pins every retained command to the original plan protocol as well as its scope and digest", () => {
  for (const [plan, root, other] of [[partialPlanFixture(2), partialReturnsRoot, partialReturnsRootV2], [remainderPlanFixture("0", "0", 2), partialReturnsRootV2, partialReturnsRoot]] as const) {
    const body = { expected_plan_digest: plan.plan_digest, reason: "Independent source review" };
    expect(partialPlanMatchesCommandUnion(plan, prepareScopedCommand(`${root}/plans/${plan.id}/post`, body))).toBe(true);
    expect(partialPlanMatchesCommandUnion(plan, prepareScopedCommand(`${other}/plans/${plan.id}/post`, body))).toBe(false);
    expect(partialPlanMatchesCommandUnion(plan, prepareScopedCommand(`${root}/plans/${plan.id}/post`, { ...body, expected_plan_digest: "f".repeat(64) }))).toBe(false);
  }
});
it("does not let a v2 transport silently submit a legacy mutation or another-domain URL", async () => {
  const session = { tenantId: "synthetic", csrfToken: "csrf", expiresAt: "2099-01-01T00:00:00Z" };
  const fetcher = vi.fn(async () => new Response(JSON.stringify({ plan: remainderPlanFixture("0", "0", 0) })));
  vi.stubGlobal("fetch", fetcher);
  const command = prepareScopedCommand(`${partialReturnsRootV2}/plans`, { source_order_id: "stock-original", quantity_scaled: "1", expected_history_version: 0 });
  await partialReturnRequestV2(session, partialScope, command.path, command);
  expect(fetcher).toHaveBeenCalledWith(command.path, expect.objectContaining({ credentials: "same-origin", body: JSON.stringify(command.body), headers: expect.objectContaining({ "X-ReconForge-CSRF": "csrf", "X-ReconForge-Workspace": "work" }) }));
  await expect(partialReturnRequest(session, partialScope, command.path, command)).rejects.toThrow();
  const legacy = prepareScopedCommand(`${partialReturnsRoot}/plans`, { source_order_id: "stock-original", quantity_scaled: "1", expected_history_version: 0 });
  await expect(partialReturnRequestV2(session, partialScope, legacy.path, legacy)).rejects.toThrow();
  for (const path of [`${partialReturnsRootV2}/sources/%2e%2e/balance`, `${partialReturnsRootV2}/plans?mode=legacy`, "/api/v2/finance-core/entries/x/post"]) await expect(partialReturnRequestV2(session, partialScope, path)).rejects.toThrow();
  expect(fetcher).toHaveBeenCalledTimes(1);
});
