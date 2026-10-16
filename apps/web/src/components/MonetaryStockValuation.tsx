import { useEffect, useRef, useState, type FormEvent } from "react";
import { useBrowserSession } from "../browserSession";
import { AdminApiError } from "../data";
import type { FinanceScope } from "../enterprise-finance-data";
import { monetaryStockRoot } from "../monetary-paths";
import { monetaryMoney, prepareMonetaryCommand } from "../monetary-public-data";
import type { MonetaryStock, MonetaryStockOptions } from "../monetary-stock-data";
import { executeMonetaryValuationCommand, loadMonetaryValuation, monetaryValuationAmounts, type MonetaryValuation } from "../monetary-valuation-data";
import { monetaryTranslate, type MonetaryWord } from "../monetary-words";
import type { SalesIdentity } from "../sales-revenue-data";
import type { PreparedScopedCommand, ScopedJsonValue } from "../scoped-command";
import type { Locale } from "../types";

const READ = ["sales.read", "inventory.read", "receivables.read", "finance_core.read"];
interface Props { locale: Locale; scope: FinanceScope; stock: MonetaryStock; options: MonetaryStockOptions | null; identity: SalesIdentity;
  externallyLocked: boolean; readOnly: boolean; onLockChange: (value: boolean) => void; onChanged: () => void }

export function MonetaryStockValuation({ locale, scope, stock, options, identity, externallyLocked, readOnly, onLockChange, onChanged }: Props) {
  const auth = useBrowserSession(), t = (key: MonetaryWord) => monetaryTranslate(locale, key);
  const [plan, setPlan] = useState<MonetaryValuation | null>(null), [id, setId] = useState(stock.balance?.active_revaluation_plan_id ?? "");
  const [busy, setBusy] = useState(false), [pending, setPending] = useState<PreparedScopedCommand | null>(null), [stale, setStale] = useState(false), [error, setError] = useState<MonetaryWord | null>(null);
  const [fields, setFields] = useState({ period_id: "", posting_date: "", reason: "", unrealized_gain_account_code: "", unrealized_loss_account_code: "" });
  const [closing, setClosing] = useState({ rate: "", source: "", effective_at: "" });
  const mounted = useRef(true), epoch = useRef(0), inFlight = useRef(false), pendingActor = useRef<string | null>(null), controller = useRef<AbortController | null>(null), alert = useRef<HTMLParagraphElement>(null), heading = useRef<HTMLHeadingElement>(null);
  const has = (...permissions: string[]) => identity.human && [...READ, ...permissions].every(permission => identity.permissions.includes(permission));
  const current = () => mounted.current && auth.isCurrent(auth.revision), locked = busy || Boolean(pending) || externallyLocked;
  const writable = !readOnly && !stale && !locked && has() && identity.stepUp;
  const foreign = stock.transaction_policy.currency_code !== stock.functional_policy.currency_code;
  const root = `${monetaryStockRoot}/orders/${encodeURIComponent(stock.id)}`;
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; ++epoch.current; controller.current?.abort(); onLockChange(false); }; }, [onLockChange]);
  useEffect(() => { ++epoch.current; controller.current?.abort(); setPlan(null); setBusy(false); }, [auth.revision, identity.id]);
  useEffect(() => { if (error) alert.current?.focus(); }, [error]);
  function failure(caught: unknown) {
    if (!current() || auth.recover(caught, auth.revision)) return;
    setStale(true); setError(caught instanceof AdminApiError && [403, 404].includes(caught.status) ? "denied" : caught instanceof AdminApiError && caught.status === 409 ? "conflict" : "unavailable");
    if (caught instanceof AdminApiError && [403, 404].includes(caught.status)) setPlan(null);
  }
  async function load(event: FormEvent) {
    event.preventDefault(); if (locked || inFlight.current || !auth.session || !has() || !foreign) return;
    const generation = ++epoch.current, abort = new AbortController(); controller.current?.abort(); controller.current = abort; setBusy(true); setError(null);
    try {
      const value = await loadMonetaryValuation(auth.session, scope, stock, id, abort.signal);
      if (current() && generation === epoch.current && !abort.signal.aborted) { setPlan(value); setStale(false); heading.current?.focus(); }
    } catch (caught) { if (generation === epoch.current && !abort.signal.aborted) failure(caught); }
    finally { if (current() && generation === epoch.current) setBusy(false); }
  }
  async function send(command: PreparedScopedCommand) {
    if (!auth.session || externallyLocked || inFlight.current || !has() || pendingActor.current !== null && pendingActor.current !== identity.id) return;
    pendingActor.current = identity.id; inFlight.current = true; ++epoch.current; controller.current?.abort(); setBusy(true); setPending(command); setError(null); onLockChange(true);
    try {
      const value = await executeMonetaryValuationCommand(auth.session, scope, stock, command);
      if (!current()) return;
      setPlan(value); setId(value.id); setPending(null); pendingActor.current = null; setStale(false); setFields(old => ({ ...old, reason: "" })); onLockChange(false); onChanged(); heading.current?.focus();
    } catch (caught) {
      if (!current()) return;
      if (!(caught instanceof AdminApiError) || caught.status >= 500) { setError("unknown"); setStale(true); }
      else { setPending(null); pendingActor.current = null; onLockChange(false); failure(caught); }
    } finally { inFlight.current = false; if (current()) setBusy(false); }
  }
  function submit(path: string, body: Record<string, ScopedJsonValue>) {
    if (!writable || inFlight.current || !fields.reason.trim()) return;
    try { void send(prepareMonetaryCommand(path, body)); } catch { setError("invalid"); }
  }
  const input = (key: MonetaryWord, value: string, change: (value: string) => void, type = "text") => <label>{t(key)}<input required disabled={locked} maxLength={key === "reason" ? 500 : 200} type={type} value={value} onChange={event => change(event.target.value)} /></label>;
  const intent = () => <>{input("reason", fields.reason, reason => setFields({ ...fields, reason }))}{input("posting_date", fields.posting_date, posting_date => setFields({ ...fields, posting_date }), "date")}<label>{t("period_id")}<select required disabled={locked} value={fields.period_id} onChange={event => setFields({ ...fields, period_id: event.target.value })}><option value="">—</option>{options?.periods.map(period => <option key={period.id} value={period.id}>{period.name}</option>)}</select></label></>;
  const account = (key: "unrealized_gain_account_code" | "unrealized_loss_account_code", kind: string) => <label>{t(key)}<select required disabled={locked} value={fields[key]} onChange={event => setFields({ ...fields, [key]: event.target.value })}><option value="">—</option>{options?.accounts.filter(row => row.account_type === kind).map(account => <option key={account.account_code} value={account.account_code}>{account.name} · {account.account_code}</option>)}</select></label>;
  const available = Boolean(stock.balance && BigInt(stock.balance.transaction_outstanding_minor) > 0n && !stock.balance.active_plan_id && !stock.balance.active_revaluation_plan_id);
  const phasePermission = plan?.phase === 0 ? ["finance_core.validate", "receivables.approve"] : ["finance_core.post", "receivables.manage"];
  const phaseAllowed = plan && writable && plan.phase < 2 && has(...phasePermission) && (plan.kind !== "reverse_revaluation" || has("finance_core.reverse"))
    && (plan.phase === 0 ? plan.preparer_actor_id !== identity.id : ![plan.preparer_actor_id, plan.reviewer_actor_id].includes(identity.id));
  return <section className="panel" aria-label={t("valuationTitle")} dir={locale === "ar" ? "rtl" : "ltr"}><h3 tabIndex={-1} ref={heading}>{t("valuationTitle")}</h3><p>{t("valuationBoundary")}</p>
    {!has() ? <p role="alert">{t("denied")}</p> : !foreign ? <p>{t("identityValuation")}</p> : <>
      {error && <p ref={alert} role="alert" tabIndex={-1}>{t(error)}</p>}{busy && <p role="status">{t("loading")}</p>}
      {pending && !busy && <aside role="status"><p>{t("unknown")}</p><button disabled={externallyLocked || pendingActor.current !== identity.id} onClick={() => void send(pending)}>{t("retry")}</button></aside>}
      {stock.balance?.active_revaluation_plan_id && <p>{t("valuationId")}: <bdi>{stock.balance.active_revaluation_plan_id}</bdi></p>}
      <form aria-label={t("loadValuation")} className="reporting-form" onSubmit={load}>{input("valuationId", id, setId)}<button disabled={locked || !has()}>{t("loadValuation")}</button></form>
      <details><summary>{t("prepareValuation")}</summary><form aria-label={t("prepareValuation")} className="reporting-form" onSubmit={event => { event.preventDefault(); submit(`${root}/valuations`, { ...fields, closing_rate: { ...closing } }); }}>{intent()}
        {account("unrealized_gain_account_code", "Income")}{account("unrealized_loss_account_code", "Expense")}{input("rate", closing.rate, rate => setClosing({ ...closing, rate }))}{input("rateSource", closing.source, source => setClosing({ ...closing, source }))}{input("effective_at", closing.effective_at, effective_at => setClosing({ ...closing, effective_at }))}
        <button disabled={!writable || !available || !has("finance_core.manage", "receivables.manage")}>{t("prepareValuation")}</button></form></details>
      {plan && <section aria-label={t("evidence")}><h4>{t(plan.kind)} · {t(plan.status)}</h4><dl><dt>{t("valuationId")}</dt><dd><bdi>{plan.id}</bdi></dd>
        {monetaryValuationAmounts.map(key => <div key={key}><dt>{t(key)}</dt><dd><bdi>{monetaryMoney(plan.monetary[key], key.startsWith("transaction_") ? plan.transaction_policy : plan.functional_policy, locale)}</bdi></dd></div>)}
        <dt>{t("closingRate")}</dt><dd><bdi>{plan.closing_rate.rate}</bdi> · {plan.closing_rate.source} · <time dateTime={plan.closing_rate.effective_at}>{plan.closing_rate.effective_at}</time></dd>
        <dt>{t("preparedBy")}</dt><dd><bdi>{plan.preparer_actor_id}</bdi></dd><dt>{t("reviewedBy")}</dt><dd><bdi>{plan.reviewer_actor_id ?? "—"}</bdi></dd><dt>{t("postedBy")}</dt><dd><bdi>{plan.posted_actor_id ?? "—"}</bdi></dd><dt>GL</dt><dd><bdi>{plan.entry_id}</bdi> · <bdi>{plan.posting_effect_id ?? "—"}</bdi></dd></dl>
        {plan.phase < 2 && <form aria-label={t(plan.phase === 0 ? "reviewValuation" : "postValuation")} onSubmit={event => { event.preventDefault(); submit(`${root}/fx-plans/${plan.id}/${plan.phase === 0 ? "review" : "post"}`, { expected_plan_digest: plan.plan_digest, reason: fields.reason }); }}>{input("reason", fields.reason, reason => setFields({ ...fields, reason }))}<button disabled={!phaseAllowed}>{t(plan.phase === 0 ? "reviewValuation" : "postValuation")}</button></form>}
        {plan.phase === 2 && plan.kind === "revalue" && <form aria-label={t("reverseValuation")} className="reporting-form" onSubmit={event => { event.preventDefault(); submit(`${root}/valuation-reversals`, { original_revaluation_id: plan.id, period_id: fields.period_id, posting_date: fields.posting_date, reason: fields.reason }); }}>{intent()}<button disabled={!writable || stock.balance?.active_revaluation_plan_id !== plan.id || Boolean(stock.balance?.active_plan_id) || !has("finance_core.manage", "receivables.manage", "finance_core.reverse")}>{t("reverseValuation")}</button></form>}
      </section>}
    </>}
  </section>;
}
