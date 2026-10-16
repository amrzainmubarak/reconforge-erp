import type { FinanceScope } from "./enterprise-finance-data";
import { isMonetaryValuationPath, monetaryStockRoot } from "./monetary-paths";
import { monetaryDate, monetaryDigest, monetaryInteger, monetaryInvalid, monetaryMinor, monetaryNullableText, monetaryObject,
  monetaryPolicyFields, monetaryRequest, monetaryScope, monetaryText, parseMonetaryPolicyPair, parseMonetaryRate,
  type MonetaryPolicy, type MonetaryRate } from "./monetary-public-data";
import type { MonetaryStock } from "./monetary-stock-data";
import type { PreparedScopedCommand } from "./scoped-command";
import type { BrowserAdminSession } from "./types";

export const monetaryValuationAmounts = ["transaction_outstanding_minor", "functional_historical_outstanding_minor", "functional_valued_outstanding_minor",
  "functional_unrealized_gain_minor", "functional_unrealized_loss_minor", "functional_turnover_minor"] as const;
export interface MonetaryValuation extends FinanceScope {
  schema_version: "stock-monetary-valuation-v1"; id: string; source_order_id: string; fx_source_id: string; fx_source_digest: string; origin_digest: string;
  kind: "revalue" | "reverse_revaluation"; status: "Prepared" | "Reviewed" | "Posted"; phase: 0 | 1 | 2; plan_digest: string;
  period_id: string; posting_date: string; reason: string; transaction_policy: MonetaryPolicy; functional_policy: MonetaryPolicy;
  monetary: Record<typeof monetaryValuationAmounts[number], string>; closing_rate: MonetaryRate;
  unrealized_gain_account_code: string; unrealized_loss_account_code: string; original_id: string | null;
  entry_id: string; validation_digest: string; posting_effect_id: string | null; preparer_actor_id: string; reviewer_actor_id: string | null; posted_actor_id: string | null;
}
const fields = ["schema_version", "id", "source_order_id", "fx_source_id", "workspace_id", "organization_id", "legal_entity_id", "fx_source_digest", "origin_digest",
  "kind", "status", "phase", "plan_digest", "period_id", "posting_date", "reason", "transaction_policy", "functional_policy", "monetary", "closing_rate",
  "unrealized_gain_account_code", "unrealized_loss_account_code", "original_id", "entry_id", "validation_digest", "posting_effect_id", "preparer_actor_id", "reviewer_actor_id", "posted_actor_id"] as const;

export function parseMonetaryValuation(value: unknown, scope: FinanceScope, sourceId: string, planId?: string): MonetaryValuation {
  const row = monetaryObject(value, fields); monetaryScope(row, scope);
  if (row.schema_version !== "stock-monetary-valuation-v1" || row.source_order_id !== sourceId || planId && row.id !== planId
      || !/^FX1-[a-f0-9]{32}$/.test(monetaryText(row.id))) monetaryInvalid();
  for (const key of ["source_order_id", "fx_source_id", "period_id", "entry_id", "preparer_actor_id"]) monetaryText(row[key]);
  for (const key of ["fx_source_digest", "origin_digest", "plan_digest", "validation_digest"]) monetaryDigest(row[key]);
  for (const key of ["unrealized_gain_account_code", "unrealized_loss_account_code"]) if (!/^[A-Z0-9][A-Z0-9._-]{0,63}$/.test(monetaryText(row[key], 64))) monetaryInvalid();
  if (row.unrealized_gain_account_code === row.unrealized_loss_account_code) monetaryInvalid();
  monetaryText(row.reason, 500); monetaryDate(row.posting_date); monetaryInteger(row.phase, 2);
  if (row.status !== ["Prepared", "Reviewed", "Posted"][row.phase as number] || !["revalue", "reverse_revaluation"].includes(row.kind as string)) monetaryInvalid();
  [row.transaction_policy, row.functional_policy] = parseMonetaryPolicyPair(row.transaction_policy, row.functional_policy);
  if ((row.transaction_policy as MonetaryPolicy).currency_code === (row.functional_policy as MonetaryPolicy).currency_code) monetaryInvalid();
  const inverse = row.kind === "reverse_revaluation";
  if (inverse ? !/^FX1-[a-f0-9]{32}$/.test(monetaryText(row.original_id)) || row.original_id === row.id : row.original_id !== null) monetaryInvalid();
  const rate = monetaryObject(row.closing_rate, ["rate", "source", "effective_at"]);
  const day = inverse ? monetaryText(rate.effective_at).slice(0, 10) : row.posting_date as string;
  row.closing_rate = parseMonetaryRate(rate, day, false);
  if (inverse && day > (row.posting_date as string)) monetaryInvalid();
  const amounts = monetaryObject(row.monetary, monetaryValuationAmounts);
  for (const key of monetaryValuationAmounts) monetaryMinor(amounts[key], key === "transaction_outstanding_minor");
  const gain = BigInt(amounts.functional_unrealized_gain_minor as string), loss = BigInt(amounts.functional_unrealized_loss_minor as string);
  if ((gain === 0n) === (loss === 0n) || BigInt(amounts.functional_valued_outstanding_minor as string) - BigInt(amounts.functional_historical_outstanding_minor as string) !== gain - loss
      || BigInt(amounts.functional_turnover_minor as string) !== gain + loss) monetaryInvalid();
  for (const key of ["reviewer_actor_id", "posted_actor_id", "posting_effect_id"]) monetaryNullableText(row[key]);
  if ((row.reviewer_actor_id !== null) !== ((row.phase as number) >= 1) || (row.posted_actor_id !== null) !== (row.phase === 2)
      || (row.posting_effect_id !== null) !== (row.phase === 2) || row.phase !== 0 && row.reviewer_actor_id === row.preparer_actor_id
      || row.phase === 2 && [row.preparer_actor_id, row.reviewer_actor_id].includes(row.posted_actor_id)) monetaryInvalid();
  return { ...row, monetary: amounts } as unknown as MonetaryValuation;
}

export function monetaryValuationSource(plan: MonetaryValuation, stock: MonetaryStock): void {
  if (!stock.monetary_origin || plan.source_order_id !== stock.id || plan.fx_source_id !== stock.monetary_origin.fx_source_id
      || plan.origin_digest !== stock.monetary_origin.source_digest || monetaryPolicyFields.some(key => plan.transaction_policy[key] !== stock.transaction_policy[key] || plan.functional_policy[key] !== stock.functional_policy[key])) monetaryInvalid();
  const origin = stock.monetary_origin;
  const originalRoles = [origin.receivable_account_code, origin.revenue_account_code, origin.cash_account_code, origin.refund_liability_account_code,
    origin.gain_account_code, origin.loss_account_code, ...origin.tax_components.map(tax => tax.account_code)];
  if (originalRoles.includes(plan.unrealized_gain_account_code) || originalRoles.includes(plan.unrealized_loss_account_code)) monetaryInvalid();
}
const equalRate = (first: MonetaryRate, second: unknown) => {
  const row = monetaryObject(second, ["rate", "source", "effective_at"]);
  return first.rate === row.rate && first.source === row.source && first.effective_at === row.effective_at;
};
export function monetaryValuationMatchesCommand(plan: MonetaryValuation, command: PreparedScopedCommand, sourceId: string, original?: MonetaryValuation | null): void {
  const root = `${monetaryStockRoot}/orders/${encodeURIComponent(sourceId)}`, body = command.body;
  if (command.path === `${root}/valuations` || command.path === `${root}/valuation-reversals`) {
    const inverse = command.path.endsWith("/valuation-reversals");
    if (plan.phase !== 0 || plan.kind !== (inverse ? "reverse_revaluation" : "revalue") || plan.period_id !== body.period_id || plan.posting_date !== body.posting_date || plan.reason !== body.reason) monetaryInvalid();
    if (inverse ? plan.original_id !== body.original_revaluation_id : !equalRate(plan.closing_rate, body.closing_rate)
        || plan.unrealized_gain_account_code !== body.unrealized_gain_account_code || plan.unrealized_loss_account_code !== body.unrealized_loss_account_code) monetaryInvalid();
    if (inverse && (!original || original.phase !== 2 || original.kind !== "revalue" || original.id !== plan.original_id || original.source_order_id !== plan.source_order_id
        || !equalRate(plan.closing_rate, original.closing_rate) || plan.unrealized_gain_account_code !== original.unrealized_gain_account_code
        || plan.unrealized_loss_account_code !== original.unrealized_loss_account_code || monetaryValuationAmounts.some(key => plan.monetary[key] !== original.monetary[key]))) monetaryInvalid();
  } else {
    const expected = `${root}/fx-plans/${plan.id}/`;
    if (command.path !== expected + "review" && command.path !== expected + "post" || plan.phase !== (command.path.endsWith("/review") ? 1 : 2) || plan.plan_digest !== body.expected_plan_digest) monetaryInvalid();
  }
}
export async function loadMonetaryValuation(session: BrowserAdminSession, scope: FinanceScope, stock: MonetaryStock, planId: string, signal?: AbortSignal): Promise<MonetaryValuation> {
  const path = `${monetaryStockRoot}/orders/${encodeURIComponent(stock.id)}/fx-plans/${encodeURIComponent(planId)}`;
  if (!isMonetaryValuationPath(path, false)) monetaryInvalid();
  const result = monetaryObject(await monetaryRequest(session, scope, path, undefined, signal), ["plan"]);
  const plan = parseMonetaryValuation(result.plan, scope, stock.id, planId); monetaryValuationSource(plan, stock); return plan;
}
export async function executeMonetaryValuationCommand(session: BrowserAdminSession, scope: FinanceScope, stock: MonetaryStock, command: PreparedScopedCommand, original?: MonetaryValuation | null): Promise<MonetaryValuation> {
  if (!isMonetaryValuationPath(command.path, true)) monetaryInvalid();
  const result = monetaryObject(await monetaryRequest(session, scope, command.path, command), ["plan"]);
  const plan = parseMonetaryValuation(result.plan, scope, stock.id); monetaryValuationSource(plan, stock); monetaryValuationMatchesCommand(plan, command, stock.id, original); return plan;
}
