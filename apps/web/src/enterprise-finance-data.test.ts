import { describe, expect, it } from "vitest";
import { financeMoney, parseTrial, sourcePlan } from "./enterprise-finance-data";

const scope = { workspace_id: "work", organization_id: "org", legal_entity_id: "entity" };
const plan = () => ({ api_contract_version: "operational-finance-api-v1", id: "OPS1-source", entry_id: "entry", source_kind: "ARInvoice", source_id: "invoice", status: "Draft", amount_minor: "9007199254740993", currency_code: "USD", currency_precision: 2, preparer_actor_id: "maker", reviewer_actor_id: null, review_digest: null, posting_effect_id: null, source_effect_id: null, plan_digest: "a".repeat(64), validation_digest: "b".repeat(64), ...scope, organization_code: "ORG", entity_code: "ENTITY", period_id: "period", posting_date: "2026-10-08", reason: "Actual source", lines: [{ account_id: "ar", debit_minor: "9007199254740993", credit_minor: "0" }, { account_id: "revenue", debit_minor: "0", credit_minor: "9007199254740993" }], source_json: "{}", snapshot_json: "{}" });
const trial = () => ({ api_contract_version: "finance-posting-api-v1", balance_scope: "selected-period-net-activity", accounts: [
  { account_id: "ar", debit_minor: "9007199254740993", credit_minor: "0", balance_minor: "9007199254740993", debit_balance_minor: "9007199254740993", credit_balance_minor: "0", postings: [{ effect_id: "effect", entry_id: "entry", line_number: 1, debit_minor: "9007199254740993", credit_minor: "0" }] },
  { account_id: "revenue", debit_minor: "0", credit_minor: "9007199254740993", balance_minor: "-9007199254740993", debit_balance_minor: "0", credit_balance_minor: "9007199254740993", postings: [{ effect_id: "effect", entry_id: "entry", line_number: 2, debit_minor: "0", credit_minor: "9007199254740993" }] },
], effect_count: 1, currency_policy: { currency_code: "USD", currency_precision: 2 }, turnover_totals: { debit_minor: "9007199254740993", credit_minor: "9007199254740993", balanced: true }, balance_totals: { debit_minor: "9007199254740993", credit_minor: "9007199254740993", balanced: true } });

describe("exact operational financial contracts", () => {
  it("retains integer amounts above JavaScript safe integer and currency precision", () => { expect(sourcePlan(plan(), scope).amount_minor).toBe("9007199254740993"); expect(financeMoney("9007199254740993", 2)).toBe("90071992547409.93"); expect(financeMoney("1", 3)).toBe("0.001"); expect(financeMoney("-1", 0)).toBe("-1"); });
  it("rejects a rounded number, wrong scope, changed debit and self review", () => {
    expect(() => sourcePlan({ ...plan(), amount_minor: 9007199254740993 }, scope)).toThrow();
    expect(() => sourcePlan(plan(), { ...scope, legal_entity_id: "foreign" })).toThrow();
    const changed = plan(); changed.lines[0].debit_minor = "1"; expect(() => sourcePlan(changed, scope)).toThrow();
    expect(() => sourcePlan({ ...plan(), status: "Reviewed", reviewer_actor_id: "maker", review_digest: "c".repeat(64) }, scope)).toThrow();
  });
  it("derives trial totals from exact posted contributions and rejects aggregate drift", () => { expect(parseTrial(trial()).balance_totals.debit_minor).toBe("9007199254740993"); const changed = trial(); changed.accounts[0].postings[0].debit_minor = "9007199254740992"; expect(() => parseTrial(changed)).toThrow(); const falseTotal = trial(); falseTotal.balance_totals.credit_minor = "0"; expect(() => parseTrial(falseTotal)).toThrow(); });
});
