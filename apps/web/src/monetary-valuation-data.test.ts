import { afterEach, expect, it, vi } from "vitest";
import source from "./monetary-test-fixtures.json";
import fixture from "./monetary-valuation-test-fixture.json";
import { isMonetaryValuationPath, monetaryStockRoot } from "./monetary-paths";
import { prepareMonetaryCommand } from "./monetary-public-data";
import { parseMonetaryStock } from "./monetary-stock-data";
import { executeMonetaryValuationCommand, monetaryValuationMatchesCommand, monetaryValuationSource, parseMonetaryValuation } from "./monetary-valuation-data";

const scope = source.scope, stock = parseMonetaryStock(source.stock, scope), root = `${monetaryStockRoot}/orders/${stock.id}`;
afterEach(() => vi.unstubAllGlobals());

it("reads a foreign current-residual valuation and preserves the original observation on a later inverse", () => {
  expect(parseMonetaryValuation(fixture, scope, stock.id).monetary.functional_unrealized_gain_minor).toBe("140");
  const inverse = { ...structuredClone(fixture), id: `FX1-${"2".repeat(32)}`, kind: "reverse_revaluation", original_id: fixture.id, posting_date: "2026-10-16" };
  expect(parseMonetaryValuation(inverse, scope, stock.id).closing_rate).toEqual(fixture.closing_rate);
  expect(() => parseMonetaryValuation({ ...inverse, posting_date: "2026-10-14" }, scope, stock.id)).toThrow();
});

it.each(["extra", "scope", "source", "identity", "registry", "gain-loss", "turnover", "residual", "float", "bool", "zero", "reviewer", "poster", "effect", "phase", "original", "rate"]) ("refuses malformed valuation evidence %s", mutation => {
  const row = structuredClone(fixture) as unknown as Record<string, unknown>, money = row.monetary as Record<string, unknown>;
  if (mutation === "extra") row.snapshot = { private: "no publication" };
  if (mutation === "scope") row.legal_entity_id = "other";
  if (mutation === "source") row.source_order_id = "other";
  if (mutation === "identity") row.transaction_policy = row.functional_policy;
  if (mutation === "registry") (row.transaction_policy as Record<string, unknown>).currency_registry_version = "other";
  if (mutation === "gain-loss") money.functional_unrealized_loss_minor = "1";
  if (mutation === "turnover") money.functional_turnover_minor = "141";
  if (mutation === "residual") money.functional_valued_outstanding_minor = "841";
  if (mutation === "float") money.functional_turnover_minor = 140;
  if (mutation === "bool") money.functional_turnover_minor = true;
  if (mutation === "zero") Object.assign(money, { functional_unrealized_gain_minor: "0", functional_turnover_minor: "0", functional_valued_outstanding_minor: "700" });
  if (mutation === "reviewer") row.reviewer_actor_id = row.preparer_actor_id;
  if (mutation === "poster") row.posted_actor_id = row.reviewer_actor_id;
  if (mutation === "effect") row.posting_effect_id = null;
  if (mutation === "phase") row.phase = true;
  if (mutation === "original") row.original_id = fixture.id;
  if (mutation === "rate") (row.closing_rate as Record<string, unknown>).effective_at = "2026-10-16T12:00:00Z";
  expect(() => parseMonetaryValuation(row, scope, stock.id)).toThrow();
});

it("binds the exact source origin, captured policy and retained prepare intent", () => {
  const prepared = parseMonetaryValuation({ ...fixture, phase: 0, status: "Prepared", reviewer_actor_id: null, posted_actor_id: null, posting_effect_id: null }, scope, stock.id);
  monetaryValuationSource(prepared, stock);
  const body = { period_id: prepared.period_id, posting_date: prepared.posting_date, reason: prepared.reason, closing_rate: { ...fixture.closing_rate }, unrealized_gain_account_code: prepared.unrealized_gain_account_code, unrealized_loss_account_code: prepared.unrealized_loss_account_code };
  const command = prepareMonetaryCommand(`${root}/valuations`, body);
  monetaryValuationMatchesCommand(prepared, command, stock.id);
  for (const key of ["period_id", "posting_date", "reason", "unrealized_gain_account_code", "unrealized_loss_account_code"]) expect(() => monetaryValuationMatchesCommand(prepared, prepareMonetaryCommand(command.path, { ...body, [key]: "different" }), stock.id)).toThrow();
  expect(() => monetaryValuationSource({ ...prepared, origin_digest: "f".repeat(64) }, stock)).toThrow();
  expect(() => monetaryValuationMatchesCommand(prepared, prepareMonetaryCommand(command.path, { ...body, closing_rate: { ...fixture.closing_rate, rate: "1.51" } }), stock.id)).toThrow();
});

it("binds review and post to the same retained plan digest, independent of preparation reason", () => {
  const value = parseMonetaryValuation(fixture, scope, stock.id);
  monetaryValuationMatchesCommand(value, prepareMonetaryCommand(`${root}/fx-plans/${value.id}/post`, { expected_plan_digest: value.plan_digest, reason: "Independent poster audit reason" }), stock.id);
  expect(() => monetaryValuationMatchesCommand(value, prepareMonetaryCommand(`${root}/fx-plans/${value.id}/post`, { expected_plan_digest: "f".repeat(64), reason: "Other audit reason" }), stock.id)).toThrow();
});

it("admits only the five finite source-bound paths, never generic FX commands or escaped source aliases", () => {
  expect(isMonetaryValuationPath(`${root}/valuations`, true)).toBe(true);
  expect(isMonetaryValuationPath(`${root}/valuation-reversals`, true)).toBe(true);
  expect(isMonetaryValuationPath(`${root}/fx-plans/${fixture.id}`, false)).toBe(true);
  for (const path of [`${root}/fx-plans/${fixture.id}?raw=true`, `${root}/fx-plans/${fixture.id}/cancel`, `${monetaryStockRoot}/orders/%2E%2E/valuations`, "/api/v1/operational-fx-tax/invoices"]) expect(isMonetaryValuationPath(path, true)).toBe(false);
  expect(isMonetaryValuationPath(`${root}/valuations`, false)).toBe(false);
  expect(isMonetaryValuationPath(`${root}/fx-plans/${fixture.id}`, true)).toBe(false);
});

it("retains canonical large monetary values and rejects an ACK outside the exact command route", async () => {
  const raw = { ...fixture, monetary: { ...fixture.monetary, functional_historical_outstanding_minor: "9007199254740993", functional_valued_outstanding_minor: "9007199254741133" } };
  expect(parseMonetaryValuation(raw, scope, stock.id).monetary.functional_historical_outstanding_minor).toBe("9007199254740993");
  const fetcher = vi.fn(async () => new Response(JSON.stringify({ plan: fixture }), { status: 200 })); vi.stubGlobal("fetch", fetcher);
  const session = { tenantId: "synthetic", csrfToken: "csrf", expiresAt: "2099-01-01T00:00:00Z" };
  const command = prepareMonetaryCommand(`${root}/fx-plans/${fixture.id}/post`, { expected_plan_digest: fixture.plan_digest, reason: "Post current valuation" });
  expect((await executeMonetaryValuationCommand(session, scope, stock, command)).id).toBe(fixture.id);
  expect(fetcher).toHaveBeenCalledTimes(1);
});
