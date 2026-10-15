import { useEffect, useRef, useState, type FormEvent } from "react";
import { useBrowserSession } from "../browserSession";
import type { BudgetIdentity } from "../budget-control-data";
import { parsePartialReturnBalance, parsePartialReturnPlan, partialMinor, partialPlanMatchesCommand, partialReturnPermissions, partialReturnRequest, partialReturnsRoot, type PartialReturnBalance, type PartialReturnPlan } from "../customer-partial-returns-data";
import { partialReturnWords, type PartialReturnWord } from "../customer-partial-returns-words";
import { AdminApiError } from "../data";
import type { FinanceScope } from "../enterprise-finance-data";
import { prepareScopedCommand, type PreparedScopedCommand } from "../scoped-command";
import type { Locale } from "../types";
import { PartialBalanceEvidence, PartialPlanEvidence } from "./CustomerPartialReturnEvidence";

interface Props { locale: Locale; scope: FinanceScope; identity: BudgetIdentity; onLockChange: (locked: boolean) => void; externallyLocked?: boolean }
export default function CustomerPartialReturns({ locale, scope, identity, onLockChange, externallyLocked = false }: Props) {
  const auth = useBrowserSession(), t = (word: PartialReturnWord) => partialReturnWords[word][locale === "ar" ? 1 : 0];
  const [plans, setPlans] = useState<PartialReturnPlan[]>([]), [plan, setPlan] = useState<PartialReturnPlan | null>(null);
  const [source, setSource] = useState(""), [balance, setBalance] = useState<PartialReturnBalance | null>(null);
  const [lookupId, setLookupId] = useState("");
  const [fields, setFields] = useState({ quantity_scaled: "", period_id: "", posting_date: "", journal_code: "", refund_liability_account_code: "", cash_account_code: "", reason: "" });
  const [refund, setRefund] = useState({ amount_minor: "", period_id: "", posting_date: "", reason: "" });
  const [reversal, setReversal] = useState({ period_id: "", posting_date: "", reason: "" }), [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false), [pending, setPending] = useState<PreparedScopedCommand | null>(null), [error, setError] = useState<PartialReturnWord | null>(null), [refresh, setRefresh] = useState(0);
  const mounted = useRef(true), lock = useRef(false), readGeneration = useRef(0), alert = useRef<HTMLParagraphElement>(null);
  const current = () => mounted.current && auth.isCurrent(auth.revision), locked = busy || Boolean(pending) || externallyLocked;
  const has = (operation: keyof typeof partialReturnPermissions) => identity.human && partialReturnPermissions[operation].every(name => identity.permissions.includes(name));
  const allowed = (operation: keyof typeof partialReturnPermissions) => identity.stepUp && has(operation);
  const preparationBlocked = !balance || Boolean(balance.active_plan_id) || balance.history_version >= 256;
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; onLockChange(false); }; }, [onLockChange]);
  useEffect(() => { if (error) alert.current?.focus(); }, [error]);
  function fail(caught: unknown) {
    if (!current() || auth.recover(caught, auth.revision)) return;
    setError(caught instanceof AdminApiError && [403, 404].includes(caught.status) ? "denied" : caught instanceof AdminApiError && caught.status === 409 ? "conflict" : "unavailable");
  }
  useEffect(() => {
    if (!auth.session || !has("read")) return; const controller = new AbortController();
    partialReturnRequest(auth.session, scope, `${partialReturnsRoot}/plans`, undefined, controller.signal).then(raw => {
      if (!Array.isArray(raw.plans) || raw.plans.length > 200) throw new Error("partial_plan_page_invalid");
      const values = raw.plans.map(value => parsePartialReturnPlan(value, scope));
      if (new Set(values.map(value => value.id)).size !== values.length) throw new Error("partial_plan_page_invalid");
      if (!current() || controller.signal.aborted) return; setPlans(values); setPlan(old => old ? values.find(value => value.id === old.id) ?? old : null);
    }).catch(caught => { if (!controller.signal.aborted) fail(caught); }); return () => controller.abort();
  }, [auth.session, scope, identity, refresh]);
  async function loadBalance(sourceId: string, signal?: AbortSignal) {
    if (!auth.session || !has("read")) return; const generation = ++readGeneration.current;
    const raw = await partialReturnRequest(auth.session, scope, `${partialReturnsRoot}/sources/${encodeURIComponent(sourceId)}/balance`, undefined, signal);
    const value = parsePartialReturnBalance(raw.balance, scope, sourceId);
    if (current() && !signal?.aborted && generation === readGeneration.current) setBalance(value);
  }
  useEffect(() => {
    setBalance(null); if (!plan) return; const controller = new AbortController();
    void loadBalance(plan.source_order_id, controller.signal).catch(caught => { if (!controller.signal.aborted) fail(caught); });
    return () => controller.abort();
  }, [plan?.id, plan?.phase, refresh]);
  async function inspect(event: FormEvent) {
    event.preventDefault(); if (locked || lock.current || !source.trim()) return;
    lock.current = true; setBusy(true); onLockChange(true); setError(null); setBalance(null);
    try { await loadBalance(source); } catch (caught) { fail(caught); }
    finally { lock.current = false; if (current()) { setBusy(false); onLockChange(false); } }
  }
  async function inspectPlan(event: FormEvent) {
    event.preventDefault(); if (locked || lock.current || !auth.session) return;
    if (!/^CR(?:2|F2|2R|F2R)-[a-f0-9]{32}$/.test(lookupId)) { setError("invalid"); return; }
    lock.current = true; setBusy(true); onLockChange(true); setError(null);
    try {
      const raw = await partialReturnRequest(auth.session, scope, `${partialReturnsRoot}/plans/${lookupId}`), value = parsePartialReturnPlan(raw.plan, scope);
      if (value.id !== lookupId) throw new Error("partial_plan_identity_invalid");
      if (current()) { setPlan(value); setSource(value.source_order_id); setBalance(null); setPlans(old => [value, ...old.filter(row => row.id !== value.id)]); setRefresh(old => old + 1); }
    } catch (caught) { fail(caught); }
    finally { lock.current = false; if (current()) { setBusy(false); onLockChange(false); } }
  }
  async function send(command: PreparedScopedCommand) {
    if (!auth.session || lock.current || externallyLocked) return; lock.current = true; setBusy(true); onLockChange(true); setPending(command); setError(null);
    try {
      const raw = await partialReturnRequest(auth.session, scope, command.path, command), value = parsePartialReturnPlan(raw.plan, scope);
      if (!partialPlanMatchesCommand(value, command)) throw new Error("partial_command_receipt_mismatch");
      if (!current()) return; setPlan(value); setSource(value.source_order_id); setPlans(old => [value, ...old.filter(row => row.id !== value.id)]);
      setBalance(null); setPending(null); setReason(""); setRefresh(old => old + 1); onLockChange(false);
    } catch (caught) {
      if (!current()) return;
      if (!(caught instanceof AdminApiError) || caught.status >= 500) setError("unknown");
      else { setPending(null); onLockChange(false); fail(caught); }
    } finally { lock.current = false; if (current()) setBusy(false); }
  }
  function prepare(event: FormEvent) {
    event.preventDefault(); if (locked || !allowed("prepare") || !balance || preparationBlocked) return;
    try {
      partialMinor(fields.quantity_scaled, true);
      if (BigInt(fields.quantity_scaled) > BigInt(balance.remaining_quantity_scaled)) throw new Error("overreturn");
      void send(prepareScopedCommand(`${partialReturnsRoot}/plans`, { ...fields, source_order_id: balance.source_order_id, expected_history_version: balance.history_version }));
    } catch { setError("invalid"); }
  }
  function prepareRefund(event: FormEvent) {
    event.preventDefault(); if (locked || !allowed("prepare") || !balance || preparationBlocked || plan?.operation !== "Return" || plan.phase !== 2) return;
    try {
      partialMinor(refund.amount_minor, true); if (BigInt(refund.amount_minor) > BigInt(balance.refund_due_minor)) throw new Error("overrefund");
      void send(prepareScopedCommand(`${partialReturnsRoot}/plans/${plan.id}/refunds`, { ...refund, expected_history_version: balance.history_version }));
    } catch { setError("invalid"); }
  }
  function prepareReverse(event: FormEvent) {
    event.preventDefault(); if (locked || !allowed("prepare") || !balance || preparationBlocked || !plan || plan.phase !== 2 || plan.operation.startsWith("Reverse")) return;
    try { void send(prepareScopedCommand(`${partialReturnsRoot}/plans/${plan.id}/reversals`, { ...reversal, expected_history_version: balance.history_version })); }
    catch { setError("invalid"); }
  }
  const input = (key: PartialReturnWord, value: string, change: (value: string) => void) => <label>{t(key)}<input required disabled={locked} maxLength={key === "reason" ? 500 : 160} type={key === "posting_date" ? "date" : "text"} inputMode={key === "quantity_scaled" || key === "amount_minor" ? "numeric" : undefined} value={value} onChange={event => change(event.target.value)} /></label>;
  const independent = plan && identity.id !== plan.preparer_actor_id, third = independent && identity.id !== plan?.reviewer_actor_id;
  return <section aria-label={t("title")} dir={locale === "ar" ? "rtl" : "ltr"}>
    <h2>{t("title")}</h2><p>{t("boundary")}</p><p>{t("duties")}</p>
    {error && <p role="alert" ref={alert} tabIndex={-1}>{t(error)}</p>}{busy && <p role="status">{t("busy")}</p>}
    {pending && !busy && <aside role="status"><p>{t("unknown")}</p><button onClick={() => void send(pending)}>{t("retry")}</button><code dir="ltr">{pending.body.command_id}</code></aside>}
    <section className="panel"><button disabled={locked} onClick={() => { setError(null); setRefresh(old => old + 1); }}>{t("refresh")}</button><label>{t("select")}<select disabled={locked} value={plan?.id ?? ""} onChange={event => { const selected = plans.find(value => value.id === event.target.value) ?? null; setPlan(selected); setSource(selected?.source_order_id ?? ""); setBalance(null); setError(null); }}><option value="">—</option>{plans.map(value => <option key={value.id} value={value.id}>{t(value.operation)} · {t(value.status)} · {value.id}</option>)}</select></label>{!plans.length && <p>{t("empty")}</p>}</section>
    <form className="panel reporting-form" aria-label={t("loadPlan")} onSubmit={event => void inspectPlan(event)}>{input("planId", lookupId, setLookupId)}<button disabled={locked || !lookupId}>{t("loadPlan")}</button></form>
    <form className="panel reporting-form" aria-label={t("load")} onSubmit={event => void inspect(event)}>{input("source_order_id", source, value => { ++readGeneration.current; setSource(value); setBalance(null); setPlan(null); })}<button disabled={locked || !source.trim()}>{t("load")}</button></form>
    {balance && <PartialBalanceEvidence balance={balance} locale={locale} />}
    {balance && has("prepare") && BigInt(balance.remaining_quantity_scaled) > 0n && <form className="panel reporting-form" aria-label={t("prepare")} onSubmit={prepare}>{(Object.keys(fields) as (keyof typeof fields)[]).map(key => <div key={key}>{input(key, fields[key], value => setFields({ ...fields, [key]: value }))}</div>)}<button disabled={locked || !allowed("prepare") || preparationBlocked}>{t("prepare")}</button></form>}
    {plan && <>
      <PartialPlanEvidence plan={plan} locale={locale} />
      {[0, 1].includes(plan.phase) && <form className="panel reporting-form" aria-label={t(plan.phase === 0 ? "review" : "post")} onSubmit={event => { event.preventDefault(); const action = plan.phase === 0 ? "review" : "post"; if (!locked && reason.trim() && allowed(action) && (action === "review" ? independent : third)) void send(prepareScopedCommand(`${partialReturnsRoot}/plans/${plan.id}/${action}`, { expected_plan_digest: plan.plan_digest, reason })); }}>{input("reason", reason, setReason)}<button disabled={locked || !reason.trim() || !allowed(plan.phase === 0 ? "review" : "post") || !(plan.phase === 0 ? independent : third)}>{t(plan.phase === 0 ? "review" : "post")}</button><button type="button" disabled={locked || !reason.trim() || !allowed("cancel") || !third} onClick={() => void send(prepareScopedCommand(`${partialReturnsRoot}/plans/${plan.id}/cancel`, { expected_plan_digest: plan.plan_digest, reason }))}>{t("cancel")}</button></form>}
      {plan.phase === 2 && plan.operation === "Return" && balance && BigInt(balance.refund_due_minor) > 0n && has("prepare") && <form className="panel reporting-form" aria-label={t("refund")} onSubmit={prepareRefund}>{(Object.keys(refund) as (keyof typeof refund)[]).map(key => <div key={key}>{input(key, refund[key], value => setRefund({ ...refund, [key]: value }))}</div>)}<button disabled={locked || !allowed("prepare") || preparationBlocked}>{t("refund")}</button></form>}
      {plan.phase === 2 && !plan.operation.startsWith("Reverse") && balance && has("prepare") && <form className="panel reporting-form" aria-label={t("reverse")} onSubmit={prepareReverse}>{(Object.keys(reversal) as (keyof typeof reversal)[]).map(key => <div key={key}>{input(key, reversal[key], value => setReversal({ ...reversal, [key]: value }))}</div>)}<button disabled={locked || !allowed("prepare") || preparationBlocked}>{t("reverse")}</button></form>}
    </>}
  </section>;
}
