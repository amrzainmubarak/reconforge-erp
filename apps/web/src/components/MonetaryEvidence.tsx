import { monetaryAmountFields, type MonetaryPartialBalance, type MonetaryPartialPlan } from "../monetary-partial-returns-data";
import { monetaryMoney, type MonetaryBalanceFields, type MonetaryPolicy } from "../monetary-public-data";
import type { MonetaryStock } from "../monetary-stock-data";
import { monetaryTranslate, type MonetaryWord } from "../monetary-words";
import type { Locale } from "../types";

export function MonetaryBalanceEvidence({ balance, transaction, functional, locale }: { balance: MonetaryBalanceFields; transaction: MonetaryPolicy; functional: MonetaryPolicy; locale: Locale }) {
  const t = (key: MonetaryWord) => monetaryTranslate(locale, key);
  return <section aria-label={t("currentBalance")}><h3>{t("currentBalance")}</h3><dl>
    <dt>{t("transaction")} · {t("outstanding")}</dt><dd><bdi>{monetaryMoney(balance.transaction_outstanding_minor, transaction, locale)}</bdi></dd>
    <dt>{t("functional")} · {t("outstanding")}</dt><dd><bdi>{monetaryMoney(balance.functional_outstanding_minor, functional, locale)}</bdi></dd>
    <dt>{t("transaction")} · {t("refundDue")}</dt><dd><bdi>{monetaryMoney(balance.transaction_refund_due_minor, transaction, locale)}</bdi></dd>
    <dt>{t("functional")} · {t("refundDue")}</dt><dd><bdi>{monetaryMoney(balance.functional_refund_due_minor, functional, locale)}</bdi></dd>
  </dl></section>;
}
export function MonetaryStockEvidence({ stock, locale }: { stock: MonetaryStock; locale: Locale }) {
  const t = (key: MonetaryWord) => monetaryTranslate(locale, key), source = stock.monetary_origin, collection = stock.collection;
  return <><dl><dt>{t("transaction")} · {t("net")}</dt><dd><bdi>{monetaryMoney(stock.transaction_net_minor, stock.transaction_policy, locale)}</bdi></dd>
    {stock.functional_cogs_minor !== null && <><dt>{t("cost")}</dt><dd><bdi>{monetaryMoney(stock.functional_cogs_minor, stock.functional_policy, locale)}</bdi></dd></>}
  </dl>{source && <section aria-label={t("origin")}><h3>{t("origin")}</h3><p><bdi>{source.invoice_number}</bdi> · {source.invoice_date} · {source.due_date}</p><dl>
    {(["transaction", "functional"] as const).flatMap(prefix => (["net", "tax", "gross"] as const).map(kind => <div key={`${prefix}-${kind}`}><dt>{t(prefix)} · {t(kind)}</dt><dd><bdi>{monetaryMoney(source[`${prefix}_${kind}_minor`], prefix === "transaction" ? stock.transaction_policy : stock.functional_policy, locale)}</bdi></dd></div>))}
  </dl>{source.original_rate ? <p>{t("originalRate")}: <bdi>{source.original_rate.rate}</bdi> · {source.original_rate.source} · <time dateTime={source.original_rate.effective_at}>{source.original_rate.effective_at}</time></p> : <p>{t("identityRate")}</p>}
    <div className="reporting-table" role="region" tabIndex={0} aria-label={t("taxes")}><table><caption>{t("taxes")}</caption><thead><tr><th>{t("policy_id")}</th><th>{t("taxRate")}</th><th>{t("transaction")}</th><th>{t("functional")}</th></tr></thead><tbody>{source.tax_components.map(component => <tr key={component.policy_id}><td><bdi>{component.policy_id}</bdi> · {component.version}<br />{component.source}<br />{component.country_code} · {component.transaction_class}<br />{component.effective_from} — {component.effective_to}</td><td><bdi>{component.rate}</bdi></td><td><bdi>{monetaryMoney(component.transaction_tax_minor, stock.transaction_policy, locale)}</bdi></td><td><bdi>{monetaryMoney(component.functional_tax_minor, stock.functional_policy, locale)}</bdi></td></tr>)}</tbody></table></div>
  </section>}{stock.balance && <MonetaryBalanceEvidence balance={stock.balance} transaction={stock.transaction_policy} functional={stock.functional_policy} locale={locale} />}
  {collection && <section aria-label={t("collectionEvidence")}><h3>{t("collectionEvidence")} · {t(collection.status)}</h3><p><bdi>{collection.receipt_number}</bdi> · {collection.receipt_date}</p><dl>
    <dt>{t("collectionAmount")}</dt><dd><bdi>{monetaryMoney(collection.amount_minor, stock.transaction_policy, locale)}</bdi></dd>
    {(["functional_cash_minor", "functional_receivable_released_minor", "functional_fx_gain_minor", "functional_fx_loss_minor"] as const).map(key => <div key={key}><dt>{t(key)}</dt><dd><bdi>{monetaryMoney(collection[key], stock.functional_policy, locale)}</bdi></dd></div>)}
    <dt>{t("preparedBy")}</dt><dd><bdi>{collection.preparer_actor_id}</bdi></dd><dt>{t("reviewedBy")}</dt><dd><bdi>{collection.reviewer_actor_id ?? "—"}</bdi></dd><dt>{t("postedBy")}</dt><dd><bdi>{collection.posted_actor_id ?? "—"}</bdi></dd>
    <dt>GL</dt><dd><bdi>{collection.entry_id ?? "—"}</bdi> · <bdi>{collection.posting_effect_id ?? "—"}</bdi></dd>
  </dl>{collection.settlement_rate ? <p>{t("settlementRate")}: <bdi>{collection.settlement_rate.rate}</bdi> · {collection.settlement_rate.source} · <time dateTime={collection.settlement_rate.effective_at}>{collection.settlement_rate.effective_at}</time></p> : <p>{t("identityRate")}</p>}</section>}
  <details><summary>{t("evidence")}</summary><dl><dt>{t("selectStock")}</dt><dd><bdi>{stock.id}</bdi></dd><dt>{t("functional")} · FIFO</dt><dd><bdi>{stock.valuation_id ?? "—"}</bdi></dd>{source && <><dt>{t("origin")}</dt><dd><bdi>{source.id}</bdi></dd><dt>GL</dt><dd><bdi>{source.entry_id}</bdi> · <bdi>{source.posting_effect_id ?? "—"}</bdi></dd></>}
    {([stock.transaction_policy, stock.functional_policy]).map((policy, index) => <div key={index}><dt>{t("capturedPolicy")} · {t(index ? "functional" : "transaction")}</dt><dd><bdi>{policy.currency_code} · {policy.currency_precision} · {policy.currency_rounding_policy} · {policy.currency_registry_version} · {policy.currency_registry_digest}</bdi></dd></div>)}
  </dl></details></>;
}
export function MonetaryPartialEvidence({ plan, balance, locale }: { plan: MonetaryPartialPlan | null; balance: MonetaryPartialBalance | null; locale: Locale }) {
  const t = (key: MonetaryWord) => monetaryTranslate(locale, key);
  return <>{balance && <><MonetaryBalanceEvidence balance={balance} transaction={balance.transaction_policy} functional={balance.functional_policy} locale={locale} /><p>{t("quantity_scaled")}: <bdi>{balance.returned_quantity_scaled}/{balance.original_quantity_scaled}</bdi> · 10<sup>−{balance.quantity_precision}</sup></p></>}
    {plan && <section aria-label={t("evidence")}><h3>{t(plan.operation)} · {t(plan.status)}</h3><p>{plan.reason}</p><dl>{monetaryAmountFields.filter(key => plan.monetary[key] !== "0" || ["transaction_credit_minor", "functional_credit_minor", "functional_cost_minor"].includes(key)).map(key => <div key={key}><dt>{t(key)}</dt><dd><bdi>{monetaryMoney(plan.monetary[key], key.startsWith("transaction_") ? plan.transaction_policy : plan.functional_policy, locale)}</bdi></dd></div>)}</dl>
      {!plan.entries.length && <p role="status">{t("zeroJournal")}</p>}<details><summary>{t("evidence")}</summary><p><bdi>{plan.id}</bdi> · <bdi>{plan.plan_digest}</bdi></p><p><bdi>{plan.movement_id ?? "—"}</bdi></p><ul>{plan.entries.map(entry => <li key={entry.entry_id}><bdi>{entry.purpose}</bdi> · <bdi>{entry.entry_id}</bdi> · <bdi>{entry.posting_effect_id ?? "—"}</bdi></li>)}</ul></details>
    </section>}</>;
}
