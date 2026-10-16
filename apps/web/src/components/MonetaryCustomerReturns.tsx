import { useEffect, useRef, useState, type FormEvent } from "react";
import type { BudgetIdentity } from "../budget-control-data";
import { useBrowserSession } from "../browserSession";
import { partialReturnPermissions } from "../customer-partial-returns-data";
import { AdminApiError } from "../data";
import type { FinanceScope } from "../enterprise-finance-data";
import { executeMonetaryPartialCommand, loadMonetaryPartialBalance, loadMonetaryPartialPlan, loadMonetaryPartialPlans,
  type MonetaryPartialBalance, type MonetaryPartialPlan } from "../monetary-partial-returns-data";
import { monetaryPartialRoot } from "../monetary-paths";
import { monetaryMinor, prepareMonetaryCommand } from "../monetary-public-data";
import { monetaryTranslate, type MonetaryWord } from "../monetary-words";
import type { PreparedScopedCommand } from "../scoped-command";
import type { Locale } from "../types";
import { MonetaryPartialEvidence } from "./MonetaryEvidence";

interface Props { locale: Locale; scope: FinanceScope; identity: BudgetIdentity; externallyLocked: boolean; onLockChange: (locked: boolean) => void }
export function MonetaryCustomerReturns({ locale, scope, identity, externallyLocked, onLockChange }: Props) {
  const auth = useBrowserSession(), t = (key: MonetaryWord) => monetaryTranslate(locale, key);
  const [plans, setPlans] = useState<MonetaryPartialPlan[]>([]), [plan, setPlan] = useState<MonetaryPartialPlan | null>(null), [balance, setBalance] = useState<MonetaryPartialBalance | null>(null);
  const [source, setSource] = useState(""), [planId, setPlanId] = useState(""), [refresh, setRefresh] = useState(0);
  const [busy, setBusy] = useState(false), [loading, setLoading] = useState(false), [pending, setPending] = useState<PreparedScopedCommand | null>(null), [stale, setStale] = useState(false), [error, setError] = useState<MonetaryWord | null>(null);
  const [fields, setFields] = useState({ quantity_scaled: "", period_id: "", posting_date: "", reason: "" });
  const [refund, setRefund] = useState({ amount_minor: "", period_id: "", posting_date: "", reason: "" }), [rate, setRate] = useState({ rate: "", source: "", effective_at: "" });
  const [reversal, setReversal] = useState({ period_id: "", posting_date: "", reason: "" }), [reason, setReason] = useState("");
  const mounted = useRef(true), lock = useRef(false), generation = useRef(0), alert = useRef<HTMLParagraphElement>(null);
  const current = () => mounted.current && auth.isCurrent(auth.revision), locked = externallyLocked || busy || Boolean(pending);
  const has = (operation: keyof typeof partialReturnPermissions) => identity.human && partialReturnPermissions[operation].every(permission => identity.permissions.includes(permission));
  const allowed = (operation: keyof typeof partialReturnPermissions) => identity.stepUp && !stale && has(operation);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; ++generation.current; onLockChange(false); }; }, [onLockChange]);
  useEffect(() => { if (error) alert.current?.focus(); }, [error]);
  function fail(caught: unknown) {
    if (!current() || auth.recover(caught, auth.revision)) return;
    setStale(true); setError(caught instanceof AdminApiError && [403, 404].includes(caught.status) ? "denied" : caught instanceof AdminApiError && caught.status === 409 ? "conflict" : "unavailable");
    if (caught instanceof AdminApiError && [403, 404].includes(caught.status)) { setPlans([]); setPlan(null); setBalance(null); }
  }
  useEffect(() => {
    if (!auth.session || !has("read") || pending || externallyLocked) return;
    const controller = new AbortController(); setLoading(true);
    Promise.all([loadMonetaryPartialPlans(auth.session, scope, controller.signal), plan ? loadMonetaryPartialPlan(auth.session, scope, plan.id, controller.signal) : Promise.resolve(null)]).then(([values, selected]) => {
      if (!current() || controller.signal.aborted) return;
      setPlans(selected && !values.some(value => value.id === selected.id) ? [selected, ...values] : values); setPlan(selected); setStale(false); setError(null);
    }).catch(caught => { if (!controller.signal.aborted) fail(caught); }).finally(() => { if (current() && !controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [auth.session, auth.revision, scope, identity, plan?.id, refresh, pending, externallyLocked]);
  async function readBalance(sourceId: string, signal?: AbortSignal) {
    if (!auth.session || !has("read")) return;
    const epoch = ++generation.current, result = await loadMonetaryPartialBalance(auth.session, scope, sourceId, signal);
    if (!current() || signal?.aborted || epoch !== generation.current) return;
    if (plan && plan.source_order_id === sourceId && (plan.source_id !== result.source_id || plan.source_fingerprint !== result.source_fingerprint)) throw new Error("monetary_source_affinity_invalid");
    setBalance(result); setStale(false); setError(null);
  }
  useEffect(() => {
    setBalance(null); if (!plan || pending || externallyLocked) return;
    const controller = new AbortController();
    void readBalance(plan.source_order_id, controller.signal).catch(caught => { if (!controller.signal.aborted) fail(caught); });
    return () => { controller.abort(); ++generation.current; };
  }, [plan?.id, plan?.phase, plan?.source_id, plan?.source_order_id, plan?.source_fingerprint, refresh, pending, externallyLocked]);
  async function inspect(event: FormEvent, lookupPlan = false) {
    event.preventDefault(); if (!auth.session || locked || lock.current || !has("read")) return;
    lock.current = true; setBusy(true); onLockChange(true); setError(null); setBalance(null);
    try {
      if (lookupPlan) {
        const value = await loadMonetaryPartialPlan(auth.session, scope, planId);
        if (current()) { setPlan(value); setSource(value.source_order_id); setPlans(old => [value, ...old.filter(item => item.id !== value.id)]); }
      } else await readBalance(source);
    } catch (caught) { fail(caught); }
    finally { lock.current = false; if (current()) { setBusy(false); onLockChange(false); } }
  }
  async function send(command: PreparedScopedCommand) {
    if (!auth.session || lock.current || externallyLocked) return;
    lock.current = true; ++generation.current; setBusy(true); setLoading(false); setPending(command); setError(null); onLockChange(true);
    try {
      const result = await executeMonetaryPartialCommand(auth.session, scope, command);
      if (!current()) return;
      setPlan(result); setSource(result.source_order_id); setPlans(old => [result, ...old.filter(value => value.id !== result.id)]);
      setBalance(null); setPending(null); setReason(""); setStale(false); setRefresh(old => old + 1); onLockChange(false);
    } catch (caught) {
      if (!current()) return;
      if (caught instanceof AdminApiError && caught.status === 409 && caught.code === "monetary_return_retryable_conflict") { setError("retryableConflict"); setStale(true); }
      else if (!(caught instanceof AdminApiError) || caught.status >= 500) { setError("unknown"); setStale(true); }
      else { setPending(null); onLockChange(false); fail(caught); }
    } finally { lock.current = false; if (current()) setBusy(false); }
  }
  const preparationBlocked = !balance || Boolean(balance.active_plan_id || balance.active_revaluation_plan_id) || balance.history_version >= 256;
  function prepare(event: FormEvent) {
    event.preventDefault(); if (locked || lock.current || !allowed("prepare") || !balance || preparationBlocked) return;
    try {
      monetaryMinor(fields.quantity_scaled, true); if (BigInt(fields.quantity_scaled) > BigInt(balance.remaining_quantity_scaled)) throw new Error("overreturn");
      void send(prepareMonetaryCommand(`${monetaryPartialRoot}/plans`, { ...fields, source_order_id: balance.source_order_id, expected_history_version: balance.history_version }));
    } catch { setError("invalid"); }
  }
  function prepareRefund(event: FormEvent) {
    event.preventDefault(); if (locked || lock.current || !allowed("prepare") || !balance || preparationBlocked || plan?.operation !== "Return" || plan.phase !== 2) return;
    try {
      monetaryMinor(refund.amount_minor, true); if (BigInt(refund.amount_minor) > BigInt(balance.transaction_refund_due_minor)) throw new Error("overrefund");
      const identityCurrency = balance.transaction_policy.currency_code === balance.functional_policy.currency_code;
      void send(prepareMonetaryCommand(`${monetaryPartialRoot}/plans/${plan.id}/refunds`, { ...refund, settlement_rate: identityCurrency ? null : { ...rate }, expected_history_version: balance.history_version }));
    } catch { setError("invalid"); }
  }
  const input = (key: MonetaryWord, value: string, change: (value: string) => void) => <label>{t(key)}<input required disabled={locked} maxLength={key === "reason" ? 500 : 200} type={key === "posting_date" ? "date" : "text"} inputMode={key === "quantity_scaled" || key === "amount_minor" ? "numeric" : undefined} value={value} onChange={event => change(event.target.value)} /></label>;
  const independent = plan && plan.preparer_actor_id !== identity.id, third = independent && plan.reviewer_actor_id !== identity.id;
  return <section aria-label={t("partialTitle")} dir={locale === "ar" ? "rtl" : "ltr"}><h2>{t("partialTitle")}</h2><p>{t("partialBoundary")}</p><p>{t("duties")}</p>
    {error && <p role="alert" ref={alert} tabIndex={-1}>{t(error)}</p>}{(loading || busy) && <p role="status">{t("loading")}</p>}
    {pending && !busy && <aside role="status"><p>{t(error === "retryableConflict" ? "retryableConflict" : "unknown")}</p><button disabled={externallyLocked} onClick={() => void send(pending)}>{t("retry")}</button></aside>}
    <section className="panel"><button disabled={locked} onClick={() => setRefresh(old => old + 1)}>{t("refresh")}</button><label>{t("selectPlan")}<select disabled={locked} value={plan?.id ?? ""} onChange={event => { ++generation.current; const value = plans.find(item => item.id === event.target.value) ?? null; setPlan(value); setSource(value?.source_order_id ?? ""); setBalance(null); setError(null); }}><option value="">—</option>{plans.map(value => <option key={value.id} value={value.id}>{t(value.operation)} · {t(value.status)} · {value.id}</option>)}</select></label>{!plans.length && !loading && <p>{t("emptyPlans")}</p>}</section>
    <form className="panel reporting-form" aria-label={t("sourceLoad")} onSubmit={event => void inspect(event)}>{input("source_order_id", source, value => { ++generation.current; setSource(value); setPlan(null); setBalance(null); })}<button disabled={locked || !source.trim() || !has("read")}>{t("sourceLoad")}</button></form>
    <form className="panel reporting-form" aria-label={t("loadPlan")} onSubmit={event => void inspect(event, true)}><label>{t("planId")}<input value={planId} maxLength={160} disabled={locked} onChange={event => setPlanId(event.target.value)} /></label><button disabled={locked || !planId.trim() || !has("read")}>{t("loadPlan")}</button></form>
    <MonetaryPartialEvidence plan={plan} balance={balance} locale={locale} />
    {balance && has("prepare") && BigInt(balance.remaining_quantity_scaled) > 0n && <form className="panel reporting-form" aria-label={t("prepareReturn")} onSubmit={prepare}><h3>{t("prepareReturn")}</h3><p>{t("quantityPolicy")}</p>{(Object.keys(fields) as (keyof typeof fields)[]).map(key => <div key={key}>{input(key, fields[key], value => setFields({ ...fields, [key]: value }))}</div>)}<button disabled={locked || !allowed("prepare") || preparationBlocked}>{t("prepareReturn")}</button></form>}
    {plan && [0, 1].includes(plan.phase) && <form className="panel reporting-form" aria-label={t(plan.phase === 0 ? "review" : "post")} onSubmit={event => {
      event.preventDefault(); const action = plan.phase === 0 ? "review" : "post";
      if (!locked && allowed(action) && (action === "review" ? independent : third)) void send(prepareMonetaryCommand(`${monetaryPartialRoot}/plans/${plan.id}/${action}`, { expected_plan_digest: plan.plan_digest, reason }));
    }}>{input("reason", reason, setReason)}<button disabled={locked || !reason.trim() || !allowed(plan.phase === 0 ? "review" : "post") || !(plan.phase === 0 ? independent : third)}>{t(plan.phase === 0 ? "review" : "post")}</button><button type="button" disabled={locked || !reason.trim() || !allowed("cancel")} onClick={() => void send(prepareMonetaryCommand(`${monetaryPartialRoot}/plans/${plan.id}/cancel`, { expected_plan_digest: plan.plan_digest, reason }))}>{t("cancel")}</button></form>}
    {balance && plan?.phase === 2 && plan.operation === "Return" && BigInt(balance.transaction_refund_due_minor) > 0n && <form className="panel reporting-form" aria-label={t("prepareRefund")} onSubmit={prepareRefund}><h3>{t("prepareRefund")}</h3>{(Object.keys(refund) as (keyof typeof refund)[]).map(key => <div key={key}>{input(key, refund[key], value => setRefund({ ...refund, [key]: value }))}</div>)}
      <fieldset><legend>{t("settlementRate")}</legend>{balance.transaction_policy.currency_code === balance.functional_policy.currency_code ? <p>{t("identityRate")}</p> : <>{input("rate", rate.rate, value => setRate({ ...rate, rate: value }))}{input("rateSource", rate.source, source => setRate({ ...rate, source }))}{input("effective_at", rate.effective_at, effective_at => setRate({ ...rate, effective_at }))}</>}</fieldset><button disabled={locked || !allowed("prepare") || preparationBlocked}>{t("prepareRefund")}</button></form>}
    {balance && plan?.phase === 2 && !plan.operation.startsWith("Reverse") && <form className="panel reporting-form" aria-label={t("prepareReverse")} onSubmit={event => {
      event.preventDefault(); if (locked || !allowed("prepare") || preparationBlocked) return;
      void send(prepareMonetaryCommand(`${monetaryPartialRoot}/plans/${plan.id}/reversals`, { ...reversal, expected_history_version: balance.history_version }));
    }}><h3>{t("prepareReverse")}</h3>{(Object.keys(reversal) as (keyof typeof reversal)[]).map(key => <div key={key}>{input(key, reversal[key], value => setReversal({ ...reversal, [key]: value }))}</div>)}<button disabled={locked || !allowed("prepare") || preparationBlocked}>{t("prepareReverse")}</button></form>}
  </section>;
}
