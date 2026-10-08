import { useEffect, useRef, useState, type FormEvent } from "react";
import { useBrowserSession } from "../browserSession";
import { AdminApiError, beginBrowserAdminSession, endBrowserAdminSession, stepUpBrowserAdminSession } from "../data";
import { loadBudgetIdentity, type BudgetIdentity } from "../budget-control-data";
import { executeFinanceCommand, financeMoney, financeRequest, loadSourcePlans, parseTrial, type FinanceScope, type SourcePlan, type TrialBalance } from "../enterprise-finance-data";
import { financeTranslate, type FinanceMessage } from "../enterprise-finance-i18n";
import { formatExactDecimal } from "../locale-format";
import { prepareScopedCommand, type PreparedScopedCommand } from "../scoped-command";
import type { Locale } from "../types";
import "./EnterpriseFinanceWorkspace.css";

export default function EnterpriseFinanceWorkspace({ locale }: { locale: Locale }) { const auth = useBrowserSession(); return <FinanceSession key={auth.revision} locale={locale} />; }
export { EnterpriseFinanceWorkspace };
function FinanceSession({ locale }: { locale: Locale }) {
  const auth = useBrowserSession(), t = (key: FinanceMessage) => financeTranslate(locale, key);
  const [tenant, setTenant] = useState("local"), [username, setUsername] = useState(""), [password, setPassword] = useState("");
  const [identity, setIdentity] = useState<BudgetIdentity | null>(null);
  const [scopeInput, setScopeInput] = useState<FinanceScope>({ workspace_id: "", organization_id: "", legal_entity_id: "" }), [scope, setScope] = useState<FinanceScope | null>(null);
  const [plans, setPlans] = useState<SourcePlan[] | null>(null), [selected, setSelected] = useState<SourcePlan | null>(null), [trial, setTrial] = useState<TrialBalance | null>(null);
  const [reportInput, setReportInput] = useState({ period_id: "", organization_code: "", entity_code: "" }), [reportJson, setReportJson] = useState("");
  const [draft, setDraft] = useState({ source_kind: "ARInvoice", source_id: "", journal_code: "", period_id: "", posting_date: "", debit_account_code: "", credit_account_code: "", reason: "" }), [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false), [pending, setPending] = useState<PreparedScopedCommand | null>(null), [error, setError] = useState<FinanceMessage | null>(null), [refresh, setRefresh] = useState(0);
  const mounted = useRef(true), commandLock = useRef(false), errorRef = useRef<HTMLParagraphElement>(null);
  const current = () => mounted.current && auth.isCurrent(auth.revision);
  const locked = busy || Boolean(pending), human = Boolean(identity?.human), can = (permission: string) => human && identity!.permissions.includes(permission);
  const mutation = Boolean(scope && identity?.stepUp);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => { if (error) errorRef.current?.focus(); }, [error]);
  function fail(caught: unknown) {
    if (!current() || auth.recover(caught, auth.revision)) return;
    setError(caught instanceof AdminApiError && caught.code === "operational_owner_required" ? "ownerRequired" : caught instanceof AdminApiError && [403, 404].includes(caught.status) ? "denied" : caught instanceof AdminApiError && caught.status === 409 ? "conflict" : "unavailable");
    setPlans(null); setSelected(null); setTrial(null); setReportJson("");
  }
  useEffect(() => {
    if (!auth.session) return; const controller = new AbortController();
    loadBudgetIdentity(auth.session, controller.signal).then(value => { if (current() && !controller.signal.aborted) { setIdentity(value); setScopeInput({ workspace_id: value.workspaces[0] ?? "", organization_id: value.organizations[0] ?? "", legal_entity_id: value.entities[0] ?? "" }); } }).catch(caught => { if (!controller.signal.aborted) fail(caught); });
    return () => controller.abort();
  }, [auth.session, auth.revision]);
  useEffect(() => {
    if (!auth.session || !scope || !can("finance_core.read")) return; const controller = new AbortController(); setPlans(null); setSelected(null);
    loadSourcePlans(auth.session, scope, controller.signal).then(value => { if (current() && !controller.signal.aborted) { setPlans(value); setError(null); } }).catch(caught => { if (!controller.signal.aborted) fail(caught); });
    return () => controller.abort();
  }, [auth.session, scope, refresh, identity]);
  async function login(event: FormEvent) {
    event.preventDefault(); if (commandLock.current) return; commandLock.current = true; setBusy(true);
    try { const session = await beginBrowserAdminSession({ tenantId: tenant, username, password }); if (current()) auth.begin(session, username, auth.revision); } catch (caught) { fail(caught); }
    finally { commandLock.current = false; if (current()) { setBusy(false); setPassword(""); } }
  }
  async function stepUp(event: FormEvent) {
    event.preventDefault(); if (!auth.session || commandLock.current) return; commandLock.current = true; setBusy(true);
    try { await stepUpBrowserAdminSession(auth.session, password); const value = await loadBudgetIdentity(auth.session); if (current()) setIdentity(value); } catch (caught) { fail(caught); }
    finally { commandLock.current = false; if (current()) { setBusy(false); setPassword(""); } }
  }
  async function logout() { if (!auth.session || locked) return; setBusy(true); try { await endBrowserAdminSession(auth.session); if (current()) auth.clear(auth.revision); } catch (caught) { fail(caught); } finally { if (current()) setBusy(false); } }
  function apply(event: FormEvent) {
    event.preventDefault(); if (locked || !identity) return;
    for (const [field, grants] of [["workspace_id", identity.workspaces], ["organization_id", identity.organizations], ["legal_entity_id", identity.entities]] as const) if (!scopeInput[field].trim() || (grants.length && !grants.includes(scopeInput[field]))) { setError("denied"); return; }
    setScope({ ...scopeInput }); setPlans(null); setSelected(null); setTrial(null); setReportJson(""); setError(null);
  }
  async function send(command: PreparedScopedCommand) {
    if (!auth.session || !scope || commandLock.current) return; commandLock.current = true; setBusy(true); setPending(command); setError(null);
    try { const result = await executeFinanceCommand(auth.session, scope, command); if (current()) { setPending(null); setSelected(result); setPlans(old => [result, ...(old ?? []).filter(p => p.id !== result.id)]); setTrial(null); setReportJson(""); setReason(""); } }
    catch (caught) { if (!current()) return; if (!(caught instanceof AdminApiError) || caught.status >= 500) setError("unknown"); else { setPending(null); fail(caught); } }
    finally { commandLock.current = false; if (current()) setBusy(false); }
  }
  function prepare(event: FormEvent) { event.preventDefault(); if (!scope || !mutation || !can("finance_core.manage") || locked) return; void send(prepareScopedCommand("/api/v1/operational-finance/plans", draft)); }
  function phase(operation: "review" | "post") { if (!scope || !selected || !mutation || locked) return; void send(prepareScopedCommand(`/api/v1/operational-finance/plans/${encodeURIComponent(selected.id)}/${operation}`, { expected_plan_digest: selected.plan_digest, reason })); }
  async function report(event: FormEvent) {
    event.preventDefault(); if (!auth.session || !scope || locked) return; setBusy(true); setTrial(null); setReportJson(""); setError(null);
    try { const raw = await financeRequest(auth.session, scope, `/api/v1/finance-core/posted-trial-balance?${new URLSearchParams({ ...reportInput, workspace: scope.workspace_id })}`); if (!raw || typeof raw !== "object" || !("trial_balance" in raw)) throw new Error("report_invalid"); const value = parseTrial(raw.trial_balance); if (current()) { setTrial(value); setReportJson(JSON.stringify(raw, null, 2)); } }
    catch (caught) { fail(caught); } finally { if (current()) setBusy(false); }
  }
  function download() { if (!reportJson) return; const url = URL.createObjectURL(new Blob([reportJson], { type: "application/json" })); const anchor = document.createElement("a"); anchor.href = url; anchor.download = "reconforge-posted-trial-balance.json"; anchor.click(); URL.revokeObjectURL(url); }
  const input = (key: FinanceMessage, value: string, change: (v: string) => void, type = "text") => <label>{t(key)}<input required type={type} maxLength={key === "reason" ? 500 : 160} value={value} disabled={locked} onChange={e => change(e.target.value)} /></label>;
  const money = (value: string, precision: number, currency: string) => `${formatExactDecimal(financeMoney(value, precision), locale)} ${currency}`;
  return <main id="main-content" className="enterprise-finance" dir={locale === "ar" ? "rtl" : "ltr"}>
    <header><h1>{t("title")}</h1><p>{t("intro")}</p></header>
    {error && <p role="alert" tabIndex={-1} ref={errorRef}>{t(error)}</p>}
    {pending && !busy && <aside role="status"><p>{t("unknown")}</p><button onClick={() => void send(pending)}>{t("retry")}</button><code dir="ltr">{pending.body.command_id}</code></aside>}
    {!auth.session ? <form className="panel finance-form" onSubmit={e => void login(e)} aria-label={t("signIn")}>{input("tenant", tenant, setTenant)}{input("username", username, setUsername)}{input("password", password, setPassword, "password")}<button disabled={busy}>{t("signIn")}</button></form> : <>
      <section className="panel"><p>{t("identity")}: <bdi>{auth.username}</bdi></p><button disabled={locked} onClick={() => void logout()}>{t("signOut")}</button></section>
      {!identity?.stepUp && human && <form className="panel finance-form" onSubmit={e => void stepUp(e)} aria-label={t("stepUp")}><h2>{t("stepUp")}</h2>{input("password", password, setPassword, "password")}<button disabled={locked}>{t("continue")}</button></form>}
      <form className="panel finance-form" onSubmit={apply} aria-label={t("scope")}><h2>{t("scope")}</h2>{([ ["workspace", "workspace_id"], ["organization", "organization_id"], ["entity", "legal_entity_id"] ] as const).map(([label, field]) => <label key={field}>{t(label)}<input value={scopeInput[field]} required maxLength={160} disabled={locked} onChange={e => { setScopeInput({ ...scopeInput, [field]: e.target.value }); setScope(null); setPlans(null); setSelected(null); setTrial(null); setReportJson(""); }} /></label>)}<button disabled={locked || !identity}>{t("apply")}</button></form>
      {scope && can("finance_core.read") && <>
        <section className="panel"><h2>{t("sources")}</h2><button disabled={locked} onClick={() => { setTrial(null); setReportJson(""); setRefresh(v => v + 1); }}>{t("refresh")}</button>{plans?.length === 0 && <p>{t("empty")}</p>}
          <div className="finance-source-grid">{plans?.map(plan => <article key={plan.id}><h3><bdi>{plan.source_kind}: {plan.source_id}</bdi></h3><p>{t(plan.status === "Draft" ? "draft" : plan.status === "Reviewed" ? "reviewed" : "posted")} · <bdi>{money(plan.amount_minor, plan.currency_precision, plan.currency_code)}</bdi></p><button disabled={locked} onClick={() => { setSelected(plan); setReason(""); }}>{t("inspect")}</button></article>)}</div>
        </section>
        {can("finance_core.manage") && <form className="panel finance-form" onSubmit={prepare} aria-label={t("prepare")}><h2>{t("prepare")}</h2><label>{t("sourceKind")}<select value={draft.source_kind} disabled={locked} onChange={e => setDraft({ ...draft, source_kind: e.target.value })}>{["ARInvoice", "APInvoice"].map(kind => <option key={kind}>{kind}</option>)}</select></label>{([ ["sourceId", "source_id"], ["journal", "journal_code"], ["period", "period_id"], ["date", "posting_date"], ["debit", "debit_account_code"], ["credit", "credit_account_code"], ["reason", "reason"] ] as const).map(([label, field]) => <label key={field}>{t(label)}<input required type={field === "posting_date" ? "date" : "text"} value={draft[field]} maxLength={field === "reason" ? 500 : 160} disabled={locked} onChange={e => setDraft({ ...draft, [field]: e.target.value })} /></label>)}<button disabled={locked || !mutation}>{t("prepare")}</button></form>}
        {selected && <section className="panel finance-evidence"><h2>{t("details")}</h2><p><bdi>{selected.id}</bdi></p><p><bdi>{money(selected.amount_minor, selected.currency_precision, selected.currency_code)}</bdi></p><p>{t("effect")}: <code dir="ltr">{selected.posting_effect_id ?? "—"}</code></p><div className="finance-table"><table><caption>{t("details")}</caption><thead><tr><th>{t("account")}</th><th>{t("debitAmount")}</th><th>{t("creditAmount")}</th></tr></thead><tbody>{selected.lines.map(line => <tr key={line.account_id}><td><bdi>{line.account_id}</bdi></td><td><bdi>{money(line.debit_minor, selected.currency_precision, selected.currency_code)}</bdi></td><td><bdi>{money(line.credit_minor, selected.currency_precision, selected.currency_code)}</bdi></td></tr>)}</tbody></table></div><details><summary>{t("details")}</summary><pre dir="ltr">{selected.source_json}</pre><pre dir="ltr">{selected.snapshot_json}</pre></details>
          {selected.status !== "Posted" && input("reason", reason, setReason)}
          {selected.status === "Draft" && can("finance_core.validate") && <button disabled={locked || !mutation || selected.preparer_actor_id === identity?.id || !reason.trim()} onClick={() => phase("review")}>{t("review")}</button>}
          {selected.status === "Reviewed" && ["ARReceipt", "APPayment"].includes(selected.source_kind) ? <p>{t("owner")}</p> : selected.status === "Reviewed" && can("finance_core.post") && <button disabled={locked || !mutation || selected.preparer_actor_id === identity?.id || !reason.trim()} onClick={() => phase("post")}>{t("post")}</button>}
        </section>}
        <form className="panel finance-form" onSubmit={e => void report(e)} aria-label={t("report")}><h2>{t("report")}</h2><p>{t("reportScope")}</p>{([ ["period", "period_id"], ["orgCode", "organization_code"], ["entityCode", "entity_code"] ] as const).map(([label, field]) => <label key={field}>{t(label)}<input value={reportInput[field]} required disabled={locked} maxLength={160} onChange={e => setReportInput({ ...reportInput, [field]: e.target.value })} /></label>)}<button disabled={locked}>{t("loadReport")}</button></form>
        {trial && <section className="panel"><h2>{t("totals")}</h2>{trial.currency_policy ? <><p><bdi>{money(trial.balance_totals.debit_minor, trial.currency_policy.currency_precision, trial.currency_policy.currency_code)} / {money(trial.balance_totals.credit_minor, trial.currency_policy.currency_precision, trial.currency_policy.currency_code)}</bdi></p><div className="finance-table"><table><caption>{t("report")}</caption><thead><tr><th>{t("account")}</th><th>{t("debitAmount")}</th><th>{t("creditAmount")}</th><th>{t("effect")}</th></tr></thead><tbody>{trial.accounts.map(account => <tr key={account.account_id}><td><bdi>{account.account_id}</bdi></td><td><bdi>{money(account.debit_balance_minor, trial.currency_policy!.currency_precision, trial.currency_policy!.currency_code)}</bdi></td><td><bdi>{money(account.credit_balance_minor, trial.currency_policy!.currency_precision, trial.currency_policy!.currency_code)}</bdi></td><td>{account.postings.map(line => <code key={`${line.effect_id}:${line.line_number}`} dir="ltr">{line.effect_id}</code>)}</td></tr>)}</tbody></table></div></> : <p>{t("noCurrency")}</p>}<button onClick={download}>{t("download")}</button></section>}
      </>}
    </>}
  </main>;
}
