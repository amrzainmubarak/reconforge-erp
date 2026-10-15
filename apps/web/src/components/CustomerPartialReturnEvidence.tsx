import type { PartialReturnBalance, PartialReturnPlan } from "../customer-partial-returns-data";
import { partialReturnWords, type PartialReturnWord } from "../customer-partial-returns-words";
import { financeMoney } from "../enterprise-finance-data";
import { formatExactDecimal } from "../locale-format";
import type { Locale } from "../types";

export function PartialBalanceEvidence({ balance, locale }: { balance: PartialReturnBalance; locale: Locale }) {
  const t = (word: PartialReturnWord) => partialReturnWords[word][locale === "ar" ? 1 : 0];
  const money = (value: string) => `${formatExactDecimal(financeMoney(value, balance.currency_precision), locale)} ${balance.currency_code}`;
  return <section className="panel" aria-label={t("balance")}>
    <h3>{t("balance")}</h3>
    {([["gross", balance.gross_minor], ["collected", balance.collected_minor], ["credited", balance.credited_minor], ["outstanding", balance.outstanding_minor], ["liability", balance.refund_entitlement_minor], ["refunded", balance.refunded_minor], ["due", balance.refund_due_minor]] as const).map(([label, value]) => <p key={label}>{t(label)}: <bdi>{money(value)}</bdi></p>)}
    <p>{t("remaining")}: <bdi>{formatExactDecimal(financeMoney(balance.remaining_quantity_scaled, balance.quantity_precision), locale)}</bdi></p>
    <p>{t("scale")}: <bdi>{balance.quantity_precision}</bdi> · {t("history")}: <bdi>{balance.history_version}</bdi></p>
    <p>{t("unitsPerBase")}: <bdi>{formatExactDecimal("1" + "0".repeat(balance.quantity_precision), locale)}</bdi></p>
    {balance.history_version === 256 && <p role="status">{t("historyLimit")}</p>}
    {balance.active_plan_id && <p role="status">{t("active")} <code dir="ltr">{balance.active_plan_id}</code></p>}
    <details><summary>{t("evidence")}</summary><p><code dir="ltr">{balance.source_id ?? "—"}</code></p><p><code dir="ltr">{balance.source_fingerprint}</code></p><p><code dir="ltr">{balance.history_fingerprint}</code></p><p><code dir="ltr">{balance.currency_registry_version} · {balance.currency_registry_digest}</code></p></details>
  </section>;
}
export function PartialPlanEvidence({ plan, locale }: { plan: PartialReturnPlan; locale: Locale }) {
  const t = (word: PartialReturnWord) => partialReturnWords[word][locale === "ar" ? 1 : 0];
  const money = (value: string) => `${formatExactDecimal(financeMoney(value, plan.currency_precision), locale)} ${plan.currency_code}`;
  return <section className="panel" aria-label={t("evidence")}>
    <h3>{t("evidence")}</h3><p><bdi>{t(plan.operation)} · {t(plan.status)}</bdi> · <code dir="ltr">{plan.id}</code></p>
    {plan.operation.startsWith("Reverse") && <p>{t("reverseMeaning")}</p>}
    <p><code dir="ltr">{plan.source_order_id} → {plan.source_id} → {plan.invoice_id}</code></p>
    {(plan.operation === "Return" || plan.operation === "ReverseReturn") && <>
      <p>{t("quantity")}: <bdi>{formatExactDecimal(financeMoney(plan.quantity_scaled, plan.quantity_precision), locale)}</bdi></p>
      {([["credit", plan.credit_minor], ["cost", plan.cogs_restored_minor], ["released", plan.receivable_released_minor], ["entitlement", plan.refund_entitlement_delta_minor]] as const).map(([label, value]) => <p key={label}>{t(label)}: <bdi>{money(value)}</bdi></p>)}
    </>}
    {(plan.operation === "Refund" || plan.operation === "ReverseRefund") && <p>{t("amount_minor")}: <bdi>{money(plan.amount_minor)}</bdi></p>}
    {plan.original_id && <p>{t("original")}: <code dir="ltr">{plan.original_id}</code></p>}
    <p>{t("actors")}: <bdi>{plan.preparer_actor_id} / {plan.reviewer_actor_id ?? "—"} / {plan.poster_actor_id ?? "—"}</bdi></p>
    <p>{t("history")}: <bdi>{plan.expected_history_version}</bdi></p><p><code dir="ltr">{plan.plan_digest}</code></p>
    {plan.entries.map(entry => <p key={entry.entry_id}><code dir="ltr">{entry.purpose}: {entry.entry_id} → {entry.posting_effect_id ?? "—"}</code><br /><code dir="ltr">{entry.validation_digest}</code></p>)}
    <p><code dir="ltr">{plan.audit_event_id} · {plan.outbox_event_id}</code></p>
  </section>;
}
