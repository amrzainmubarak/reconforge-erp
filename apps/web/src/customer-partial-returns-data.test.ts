import { afterEach, expect, it, vi } from "vitest";
import { parsePartialReturnBalance, parsePartialReturnPlan, partialPlanMatchesCommand, partialReturnRequest, partialReturnsRoot } from "./customer-partial-returns-data";
import { partialBalanceFixture, partialPlanFixture, partialScope } from "./customer-partial-returns-test-fixtures";
import { prepareScopedCommand } from "./scoped-command";

afterEach(() => vi.unstubAllGlobals());
it.each(["Return", "Refund", "ReverseReturn", "ReverseRefund"] as const)("admits the finite %s DTO in all governed phases", operation => {
  for (const phase of [0, 1, 2, 3] as const) expect(parsePartialReturnPlan(partialPlanFixture(phase, operation), partialScope).operation).toBe(operation);
});
it.each([1, true, 1.5, "01", "1.0", "1e3", "-1", "9000000000000000001"])("refuses ambiguous money or quantity %s", bad => {
  for (const key of ["quantity_scaled", "credit_minor", "cogs_restored_minor", "receivable_released_minor", "refund_entitlement_delta_minor", "amount_minor"]) expect(() => parsePartialReturnPlan({ ...partialPlanFixture(), [key]: bad }, partialScope)).toThrow();
});
it("retains exact original amounts above JavaScript safe-integer limits", () => {
  const credit = "9007199254740993";
  const plan = { ...partialPlanFixture(), credit_minor: credit, receivable_released_minor: credit, amount_minor: (BigInt(credit) + 16000n).toString() };
  expect(parsePartialReturnPlan(plan, partialScope).credit_minor).toBe(credit);
});
it.each(["2026-02-30", "2025-02-29", "1900-02-29", "2026-13-01", "0000-01-01", "20261015"])("refuses an impossible or noncanonical native posting date %s", posting_date => {
  expect(() => parsePartialReturnPlan({ ...partialPlanFixture(), posting_date }, partialScope)).toThrow();
});
it("admits a real leap century and refuses wrong or reordered financial purposes", () => {
  expect(parsePartialReturnPlan({ ...partialPlanFixture(), posting_date: "2000-02-29" }, partialScope).posting_date).toBe("2000-02-29");
  for (const operation of ["Return", "Refund", "ReverseReturn", "ReverseRefund"] as const) {
    const plan = partialPlanFixture(1, operation);
    expect(() => parsePartialReturnPlan({ ...plan, entries: plan.entries.map(entry => ({ ...entry, purpose: "UnboundFinancialPurpose" })) }, partialScope)).toThrow();
  }
  const plan = partialPlanFixture();
  expect(() => parsePartialReturnPlan({ ...plan, entries: [...plan.entries].reverse() }, partialScope)).toThrow();
});
it("refuses impossible over-collection even when residual and refund equations balance", () => {
  expect(() => parsePartialReturnBalance(partialBalanceFixture({ collected_minor: "67501", outstanding_minor: "0", refund_entitlement_minor: "54001", refund_due_minor: "54001" }), partialScope, "stock-original")).toThrow();
});
it.each([
  { legal_entity_id: "foreign" }, { source_id: "CRS2-bad" }, { status: "Posted" }, { reviewer_actor_id: "maker" }, { phase: true },
  { expected_history_version: 0.1 }, { quantity_precision: true }, { currency_precision: 9 }, { currency_registry_digest: "invalid" },
  { currency_rounding_policy: "guess" }, { quantity_scaled: "0" }, { cogs_restored_minor: "0" }, { amount_minor: "70001" },
  { receivable_released_minor: "53999" }, { original_id: "CR2-" + "a".repeat(32) }, { poster_actor_id: "unauthorized" }, { private: "not-public" },
])("refuses source, policy, amount or governance drift %s", patch => expect(() => parsePartialReturnPlan({ ...partialPlanFixture(), ...patch }, partialScope)).toThrow());
it("refuses premature/duplicate posting effects and extra entry fields", () => {
  const prepared = partialPlanFixture(), posted = partialPlanFixture(2);
  for (const entries of [[{ ...prepared.entries[0], posting_effect_id: "premature" }, prepared.entries[1]], [prepared.entries[0], prepared.entries[0]], [{ ...prepared.entries[0], raw_snapshot: "private" }, prepared.entries[1]]]) expect(() => parsePartialReturnPlan({ ...prepared, entries }, partialScope)).toThrow();
  expect(() => parsePartialReturnPlan({ ...posted, entries: posted.entries.map(entry => ({ ...entry, posting_effect_id: "same" })) }, partialScope)).toThrow();
  expect(() => parsePartialReturnPlan({ ...posted, poster_actor_id: "checker" }, partialScope)).toThrow();
});
it("uses prefix-adjusted cash/credit balances without retroactively rejecting legitimate post-credit overpayment", () => {
  expect(parsePartialReturnBalance(partialBalanceFixture(), partialScope, "stock-original").outstanding_minor).toBe("3500");
  const final = partialBalanceFixture({ history_version: 3, collected_minor: "13500", credited_minor: "67500", returned_quantity_scaled: "15", remaining_quantity_scaled: "0", outstanding_minor: "0", refund_entitlement_minor: "13500", refunded_minor: "3500", refund_due_minor: "10000" });
  expect(parsePartialReturnBalance(final, partialScope, "stock-original").refund_due_minor).toBe("10000");
});
it.each([{ outstanding_minor: "0" }, { refund_due_minor: "1" }, { credited_minor: "67501" }, { active_plan_id: "CR1-" + "a".repeat(32) }, { source_id: null }, { history_version: true }, { history_version: 1.5 }, { refund_entitlement_minor: 0 }, { raw_invoice: {} }])("refuses malformed native balance %s", patch => expect(() => parsePartialReturnBalance(partialBalanceFixture(patch as never), partialScope, "stock-original")).toThrow());
it("binds source balances and command receipts to their exact scope, source, version, route and phase", () => {
  expect(() => parsePartialReturnBalance(partialBalanceFixture(), partialScope, "foreign-source")).toThrow();
  expect(() => parsePartialReturnBalance(partialBalanceFixture({ organization_id: "foreign" }), partialScope, "stock-original")).toThrow();
  const plan = partialPlanFixture(0), command = prepareScopedCommand(`${partialReturnsRoot}/plans`, { source_order_id: plan.source_order_id, quantity_scaled: plan.quantity_scaled, expected_history_version: 0 });
  expect(partialPlanMatchesCommand(plan, command)).toBe(true);
  expect(partialPlanMatchesCommand({ ...plan, expected_history_version: 1 }, command)).toBe(false);
  expect(partialPlanMatchesCommand({ ...plan, source_order_id: "foreign" }, command)).toBe(false);
  const post = prepareScopedCommand(`${partialReturnsRoot}/plans/${plan.id}/post`, { expected_plan_digest: plan.plan_digest });
  expect(partialPlanMatchesCommand(partialPlanFixture(2), post)).toBe(true);
  expect(partialPlanMatchesCommand(plan, post)).toBe(false);
  expect(partialPlanMatchesCommand({ ...partialPlanFixture(2), plan_digest: "b".repeat(64) }, post)).toBe(false);
});
it("keeps trusted scope, CSRF and the retained payload at the same-origin transport boundary", async () => {
  const fetcher = vi.fn(async () => new Response(JSON.stringify({ plan: partialPlanFixture(0) })));
  vi.stubGlobal("fetch", fetcher);
  const command = prepareScopedCommand(`${partialReturnsRoot}/plans`, { source_order_id: "stock-original", quantity_scaled: "12", expected_history_version: 0 });
  const session = { tenantId: "synthetic", csrfToken: "csrf", expiresAt: "2099-01-01T00:00:00Z" };
  await partialReturnRequest(session, partialScope, command.path, command);
  expect(fetcher).toHaveBeenCalledWith(command.path, expect.objectContaining({ credentials: "same-origin", cache: "no-store", method: "POST", body: JSON.stringify(command.body), headers: expect.objectContaining({ "X-ReconForge-Workspace": "work", "X-ReconForge-Organization": "org", "X-ReconForge-Legal-Entity": "entity", "X-ReconForge-CSRF": "csrf" }) }));
  await expect(partialReturnRequest(session, partialScope, `${partialReturnsRoot}/plans/x/post`, command)).rejects.toThrow();
  for (const path of [`${partialReturnsRoot}/plans/../finance-core/entries/x/post`, `${partialReturnsRoot}/plans?tenant=foreign`, `${partialReturnsRoot}/sources/../balance`, `${partialReturnsRoot}/sources/%2e%2e/balance`, `${partialReturnsRoot}/sources/a%2Fb/balance`]) {
    await expect(partialReturnRequest(session, partialScope, path)).rejects.toThrow();
  }
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ plans: [], secret: "refuse" }))));
  await expect(partialReturnRequest(session, partialScope, `${partialReturnsRoot}/plans`)).rejects.toThrow();
});
