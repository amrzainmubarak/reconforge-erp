import { useEffect, useRef, useState, type FormEvent } from "react";
import { useBrowserSession } from "../browserSession";
import { loadBudgetIdentity, type BudgetIdentity } from "../budget-control-data";
import { AdminApiError, beginBrowserAdminSession, endBrowserAdminSession, stepUpBrowserAdminSession } from "../data";
import { financeMoney, type FinanceScope } from "../enterprise-finance-data";
import { parseCatalog, reportingRequest, type Catalog } from "../financial-reporting-data";
import { formatExactDecimal } from "../locale-format";
import { fxRequest, mergeFxPlan, parseFxDetail, parseFxPlan, parseFxSource, verifyFxEvidence, type FxDetail, type FxEvidence, type FxPlan, type FxPolicy, type FxSource } from "../operational-fx-tax-data";
import { fxTranslate, type FxMessage } from "../operational-fx-tax-i18n";
import { prepareScopedCommand, type PreparedScopedCommand } from "../scoped-command";
import type { Locale } from "../types";
import "./FinancialReportingPage.css";

const root = "/api/v1/operational-fx-tax";
const blankTax = () => ({ policy_id: "", version: "", rate: "", effective_from: "", effective_to: "", account_code: "", source: "" });
export default function OperationalFxTaxPage({ locale }: { locale: Locale }) {
  const auth = useBrowserSession(); return <FxSession key={auth.revision} locale={locale} />;
}
function FxSession({ locale }: { locale: Locale }) {
  const auth = useBrowserSession(), t = (key: FxMessage) => fxTranslate(locale, key);
  const [identity, setIdentity] = useState<BudgetIdentity | null>(null), [login, setLogin] = useState({ tenant: "local", username: "", password: "" });
  const [scopeInput, setScopeInput] = useState<FinanceScope>({ workspace_id: "", organization_id: "", legal_entity_id: "" }), [scope, setScope] = useState<FinanceScope | null>(null);
  const [catalog, setCatalog] = useState<Catalog | null>(null), [sources, setSources] = useState<FxSource[]>([]), [next, setNext] = useState<string | null>(null);
  const [selected, setSelected] = useState(""), [detail, setDetail] = useState<FxDetail | null>(null), [plan, setPlan] = useState<FxPlan | null>(null), [proof, setProof] = useState<FxEvidence | null>(null);
  const [definition, setDefinition] = useState({ invoice_number: "", customer_code: "", foreign_currency_code: "", net_minor: "", posting_date: "", due_date: "", period_id: "", journal_code: "", country_code: "", transaction_class: "", receivable_account_code: "", revenue_account_code: "", cash_account_code: "", gain_account_code: "", loss_account_code: "", reason: "" });
  const [originalRate, setOriginalRate] = useState({ rate: "", source: "", effective_at: "" }), [taxes, setTaxes] = useState<ReturnType<typeof blankTax>[]>([]);
  const [settlement, setSettlement] = useState({ foreign_minor: "", posting_date: "", period_id: "", reason: "" }), [settlementRate, setSettlementRate] = useState({ rate: "", source: "", effective_at: "" }), [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false), [pending, setPending] = useState<PreparedScopedCommand | null>(null), [error, setError] = useState<FxMessage | null>(null), [refresh, setRefresh] = useState(0);
  const mounted = useRef(true), lock = useRef(false), alert = useRef<HTMLParagraphElement>(null), proofEpoch = useRef(0), downloadUrl = useRef<string | null>(null);
  const current = () => mounted.current && auth.isCurrent(auth.revision), locked = busy || Boolean(pending), can = (permission: string) => Boolean(identity?.human && identity.permissions.includes(permission));
  const mutation = Boolean(scope && identity?.stepUp), money = (value: string, policy: Pick<FxPolicy, "currency_precision" | "currency_code">) => `${formatExactDecimal(financeMoney(value, policy.currency_precision), locale)} ${policy.currency_code}`;
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; if (downloadUrl.current) URL.revokeObjectURL(downloadUrl.current); }; }, []);
  useEffect(() => { if (error) alert.current?.focus(); }, [error]);
  function clear() { setCatalog(null); setSources([]); setDetail(null); setPlan(null); setSelected(""); setProof(null); setNext(null); proofEpoch.current++; }
  function fail(caught: unknown) { if (!current() || auth.recover(caught, auth.revision)) return; const denied = caught instanceof AdminApiError && [403, 404].includes(caught.status);
    if (denied) { setSources([]); setDetail(null); setPlan(null); setProof(null); proofEpoch.current++; }
    setError(denied ? "denied" : caught instanceof AdminApiError && caught.status === 409 ? "conflict" : "unavailable"); }
  useEffect(() => {
    if (!auth.session) return; const controller = new AbortController();
    loadBudgetIdentity(auth.session, controller.signal).then(value => { if (current() && !controller.signal.aborted) { setIdentity(value); setScopeInput({ workspace_id: value.workspaces[0] ?? "", organization_id: value.organizations[0] ?? "", legal_entity_id: value.entities[0] ?? "" }); } }).catch(caught => { if (!controller.signal.aborted) fail(caught); });
    return () => controller.abort();
  }, [auth.session, auth.revision]);
  useEffect(() => {
    if (!auth.session || !scope || !can("finance_core.read") || !can("receivables.read")) return; const controller = new AbortController();
    Promise.all([reportingRequest(auth.session, scope, "/api/v1/financial-reporting/catalog", undefined, controller.signal), fxRequest(auth.session, scope, root + "/invoices", undefined, controller.signal)]).then(([raw, page]) => {
      if (!current() || controller.signal.aborted) return; setCatalog(parseCatalog(raw.catalog, scope));
      if (!Array.isArray(page.invoices) || page.invoices.length > 25 || (page.next_after !== null && typeof page.next_after !== "string")) throw new Error("fx_page_invalid");
      setSources(page.invoices.map(row => parseFxSource(row, scope))); setNext(page.next_after as string | null);
    }).catch(caught => { if (!controller.signal.aborted) fail(caught); }); return () => controller.abort();
  }, [scope, identity, refresh, auth.session]);
  useEffect(() => {
    if (!auth.session || !scope || !selected) return; const controller = new AbortController();
    fxRequest(auth.session, scope, `${root}/invoices/${encodeURIComponent(selected)}`, undefined, controller.signal).then(raw => {
      if (!current() || controller.signal.aborted) return; const value = parseFxDetail(raw.invoice, scope); setDetail(value);
      setPlan(old => { const retained = old ? value.plans.find(row => row.id === old.id) : null; return retained ? mergeFxPlan(old, retained) : value.plans.find(row => row.phase < 2) ?? value.plans.at(-1) ?? null; });
    }).catch(caught => { if (!controller.signal.aborted) fail(caught); }); return () => controller.abort();
  }, [scope, selected, refresh, auth.session]);
  useEffect(() => { setProof(null); proofEpoch.current++; }, [plan?.id, plan?.phase, scope, auth.revision]);
  async function authenticate(event: FormEvent, stepUp = false) {
    event.preventDefault(); if (lock.current) return; lock.current = true; setBusy(true); setError(null);
    try { if (stepUp && auth.session) { await stepUpBrowserAdminSession(auth.session, login.password); const value = await loadBudgetIdentity(auth.session); if (current()) setIdentity(value); }
      else { const session = await beginBrowserAdminSession({ tenantId: login.tenant, username: login.username, password: login.password }); if (current()) auth.begin(session, login.username, auth.revision); } }
    catch (caught) { fail(caught); } finally { lock.current = false; if (current()) { setBusy(false); setLogin(old => ({ ...old, password: "" })); } }
  }
  function apply(event: FormEvent) {
    event.preventDefault(); if (locked || !identity) return;
    for (const [key, grants] of [["workspace_id", identity.workspaces], ["organization_id", identity.organizations], ["legal_entity_id", identity.entities]] as const) if (!scopeInput[key].trim() || (grants.length && !grants.includes(scopeInput[key]))) { setError("denied"); return; }
    clear(); setScope({ ...scopeInput }); setError(null);
  }
  async function send(command: PreparedScopedCommand) {
    if (!auth.session || !scope || lock.current) return; lock.current = true; setBusy(true); setPending(command); setError(null);
    try { const raw = await fxRequest(auth.session, scope, command.path, command); if (!current()) return;
      const value = parseFxPlan(raw.plan, scope); setPlan(old => mergeFxPlan(old, value)); setSelected(value.source_id); setPending(null); setRefresh(old => old + 1); setReason(""); }
    catch (caught) { if (!current()) return; if (!(caught instanceof AdminApiError) || caught.status >= 500) setError("unknown"); else { setPending(null); fail(caught); } }
    finally { lock.current = false; if (current()) setBusy(false); }
  }
  function prepare(event: FormEvent) {
    event.preventDefault(); if (!mutation || locked) return;
    try { if (!/^[1-9]\d{0,18}$/.test(definition.net_minor) || BigInt(definition.net_minor) > 9000000000000000000n) throw new Error("exact_minor_invalid");
      void send(prepareScopedCommand(root + "/invoices", { ...definition, original_rate: { ...originalRate }, taxes: taxes.map(row => ({ ...row, country_code: definition.country_code, transaction_class: definition.transaction_class })) })); }
    catch { setError("invalid"); }
  }
  function settle(event: FormEvent) {
    event.preventDefault(); if (!detail || !mutation || locked) return;
    try { if (!/^[1-9]\d{0,18}$/.test(settlement.foreign_minor) || BigInt(settlement.foreign_minor) > BigInt(detail.foreign_outstanding_minor)) throw new Error("exact_minor_invalid");
      void send(prepareScopedCommand(`${root}/invoices/${encodeURIComponent(detail.id)}/settlements`, { ...settlement, settlement_rate: { ...settlementRate } })); }
    catch { setError("invalid"); }
  }
  async function verify() {
    if (!auth.session || !scope || !plan || lock.current || locked) return; const epoch = ++proofEpoch.current; lock.current = true; setBusy(true); setProof(null);
    try { const raw = await fxRequest(auth.session, scope, `${root}/plans/${encodeURIComponent(plan.id)}/evidence`); const evidence = await verifyFxEvidence(raw.evidence, scope, plan);
      if (current() && epoch === proofEpoch.current) setProof(evidence); }
    catch (caught) { if (current() && epoch === proofEpoch.current) fail(caught); } finally { lock.current = false; if (current()) setBusy(false); }
  }
  function download() { if (!proof || !current()) return; if (downloadUrl.current) URL.revokeObjectURL(downloadUrl.current); downloadUrl.current = URL.createObjectURL(new Blob([JSON.stringify(proof, null, 2) + "\n"], { type: "application/json" })); const link = document.createElement("a"); link.href = downloadUrl.current; link.download = proof.plan.id + "-fx-evidence.json"; link.click(); }
  async function nextPage() {
    if (!auth.session || !scope || !next || locked) return; setBusy(true);
    try { const raw = await fxRequest(auth.session, scope, `${root}/invoices?after=${encodeURIComponent(next)}`); if (!current()) return;
      if (!Array.isArray(raw.invoices) || raw.invoices.length > 25 || (raw.next_after !== null && typeof raw.next_after !== "string")) throw new Error("fx_page_invalid"); setSources(raw.invoices.map(row => parseFxSource(row, scope))); setNext(raw.next_after as string | null); }
    catch (caught) { fail(caught); } finally { if (current()) setBusy(false); }
  }
  const input = (label: FxMessage, value: string, change: (value: string) => void, type = "text") => <label>{t(label)}<input required type={type} disabled={locked} maxLength={label === "reason" ? 500 : 200} value={value} onChange={event => change(event.target.value)} /></label>;
  const period = (value: string, change: (value: string) => void) => <label>{t("period_id")}<select required disabled={locked} value={value} onChange={event => change(event.target.value)}><option value="">—</option>{catalog?.periods.filter(row => row.status === "Open").map(row => <option key={row.id} value={row.id}>{row.name} · {row.start_date} / {row.end_date}</option>)}</select></label>;
  const account = (label: FxMessage, value: string, change: (value: string) => void, kind: string) => <label>{t(label)}<select required disabled={locked} value={value} onChange={event => change(event.target.value)}><option value="">—</option>{catalog?.accounts.filter(row => row.account_type === kind).map(row => <option key={row.account_id} value={row.account_code}>{row.account_code} · {row.account_name}</option>)}</select></label>;
  return <main id="main-content" className="financial-reporting" dir={locale === "ar" ? "rtl" : "ltr"}>
    <header><h1>{t("title")}</h1><p>{t("intro")}</p><p>{t("boundary")}</p></header>
    {error && <p role="alert" tabIndex={-1} ref={alert}>{t(error)}</p>}
    {pending && !busy && <aside role="status"><p>{t("unknown")}</p><button onClick={() => void send(pending)}>{t("retry")}</button><code dir="ltr">{pending.body.command_id}</code></aside>}
    {!auth.session ? <form className="panel reporting-form" aria-label={t("signIn")} onSubmit={event => void authenticate(event)}>{input("tenant", login.tenant, value => setLogin({ ...login, tenant: value }))}{input("username", login.username, value => setLogin({ ...login, username: value }))}{input("password", login.password, value => setLogin({ ...login, password: value }), "password")}<button disabled={locked}>{t("signIn")}</button></form> : <>
      <section className="panel"><bdi>{auth.username}</bdi><button disabled={locked} onClick={() => { if (!auth.session) return; setBusy(true); void endBrowserAdminSession(auth.session).then(() => { if (current()) auth.clear(auth.revision); }).catch(fail).finally(() => { if (current()) setBusy(false); }); }}>{t("signOut")}</button></section>
      {!identity?.stepUp && identity?.human && <form className="panel reporting-form" aria-label={t("stepUp")} onSubmit={event => void authenticate(event, true)}>{input("password", login.password, value => setLogin({ ...login, password: value }), "password")}<button disabled={locked}>{t("stepUp")}</button></form>}
      <form className="panel reporting-form" aria-label={t("apply")} onSubmit={apply}>{([["workspace", "workspace_id"], ["organization", "organization_id"], ["entity", "legal_entity_id"]] as const).map(([label, field]) => <label key={field}>{t(label)}<input required maxLength={160} disabled={locked || !identity} value={scopeInput[field]} onChange={event => { setScopeInput({ ...scopeInput, [field]: event.target.value }); setScope(null); clear(); }} /></label>)}<button disabled={locked || !identity}>{t("apply")}</button></form>
      {scope && catalog && <>
        <section className="panel"><h2>{t("invoices")}</h2><button disabled={locked} onClick={() => setRefresh(old => old + 1)}>{t("refresh")}</button><label>{t("invoices")}<select value={selected} disabled={locked} onChange={event => { setSelected(event.target.value); setDetail(null); setPlan(null); setProof(null); }}><option value="">—</option>{sources.map(row => <option key={row.id} value={row.id}>{row.request.invoice_number} · {row.foreign_policy.currency_code}</option>)}</select></label>{!sources.length && <p>{t("empty")}</p>}{next && <button disabled={locked} onClick={() => void nextPage()}>{t("next")}</button>}</section>
        {can("finance_core.manage") && can("receivables.manage") && <form className="panel" aria-label={t("prepare")} onSubmit={prepare}><h2>{t("prepare")}</h2><div className="reporting-form">
          {(["invoice_number", "customer_code", "foreign_currency_code", "net_minor", "country_code", "transaction_class", "reason"] as const).map(key => <div key={key}>{input(key, definition[key], value => setDefinition({ ...definition, [key]: value }))}</div>)}
          {(["posting_date", "due_date"] as const).map(key => <div key={key}>{input(key, definition[key], value => setDefinition({ ...definition, [key]: value }), "date")}</div>)}{period(definition.period_id, value => setDefinition({ ...definition, period_id: value }))}
          <label>{t("journal_code")}<select required disabled={locked} value={definition.journal_code} onChange={event => setDefinition({ ...definition, journal_code: event.target.value })}><option value="">—</option>{catalog.journals.map(row => <option key={row.journal_code} value={row.journal_code}>{row.journal_code} · {row.name}</option>)}</select></label>
          {([["receivable_account_code", "Asset"], ["revenue_account_code", "Income"], ["cash_account_code", "Asset"], ["gain_account_code", "Income"], ["loss_account_code", "Expense"]] as const).map(([key, kind]) => <div key={key}>{account(key, definition[key], value => setDefinition({ ...definition, [key]: value }), kind)}</div>)}
        </div><fieldset><legend>{t("originalRate")}</legend><div className="reporting-form">{(["rate", "source", "effective_at"] as const).map(key => <div key={key}>{input(key, originalRate[key], value => setOriginalRate({ ...originalRate, [key]: value }))}</div>)}</div></fieldset>
        <fieldset><legend>{t("taxes")}</legend>{taxes.map((tax, index) => <fieldset key={index}><legend>{t("tax")} {index + 1}</legend><div className="reporting-form">{(["policy_id", "version", "rate", "source", "effective_from", "effective_to"] as const).map(key => <div key={key}>{input(key === "rate" ? "taxRate" : key === "source" ? "taxSource" : key, tax[key], value => setTaxes(old => old.map((row, at) => at === index ? { ...row, [key]: value } : row)), key.startsWith("effective_") ? "date" : "text")}</div>)}{account("account_code", tax.account_code, value => setTaxes(old => old.map((row, at) => at === index ? { ...row, account_code: value } : row)), "Liability")}</div><button type="button" disabled={locked} onClick={() => setTaxes(old => old.filter((_, at) => at !== index))}>{t("removeTax")}</button></fieldset>)}<button type="button" disabled={locked || taxes.length >= 8} onClick={() => setTaxes(old => [...old, blankTax()])}>{t("addTax")}</button></fieldset><button disabled={locked || !mutation}>{t("prepare")}</button></form>}
        {detail && <section className="panel"><h2><bdi>{detail.request.invoice_number}</bdi></h2><dl>{([["originalGross", detail.foreign_gross_minor, detail.foreign_policy], ["functionalGross", detail.functional_gross_minor, detail.functional_policy], ["foreignResidual", detail.foreign_outstanding_minor, detail.foreign_policy], ["functionalResidual", detail.functional_outstanding_minor, detail.functional_policy]] as const).map(([key, value, policy]) => <div key={key}><dt>{t(key)}</dt><dd><bdi>{money(value, policy)}</bdi></dd></div>)}</dl><p>{t("originalRate")}: <bdi>{detail.request.original_rate.rate}</bdi> · <bdi>{detail.request.original_rate.source}</bdi> · <bdi>{detail.request.original_rate.effective_at}</bdi></p>
          <div className="reporting-table" role="region" tabIndex={0} aria-label={t("taxes")}><table><caption>{t("taxes")}</caption><thead><tr><th>{t("policy_id")}</th><th>{t("version")}</th><th>{t("taxRate")}</th><th>{t("foreign_currency_code")}</th><th>{t("tax")}</th></tr></thead><tbody>{detail.tax_components.map(row => <tr key={row.policy_id}><td>{row.policy_id}</td><td>{row.version}</td><td>{row.rate}</td><td><bdi>{money(row.foreign_tax_minor, detail.foreign_policy)}</bdi></td><td><bdi>{money(row.functional_tax_minor, detail.functional_policy)}</bdi></td></tr>)}</tbody></table></div>
          <h3>{t("plans")}</h3>{detail.plans.map(row => <button key={row.id} disabled={locked} onClick={() => { setPlan(row); setProof(null); }}>{row.sequence} · {t(row.kind === "recognize" ? "recognize" : "settlement")} · {t(row.status)}</button>)}
          {can("finance_core.manage") && can("receivables.manage") && BigInt(detail.foreign_outstanding_minor) > 0n && detail.plans.every(row => row.phase === 2) && (!plan || plan.source_id !== detail.id || plan.phase === 2) && <form aria-label={t("settle")} onSubmit={settle}><h3>{t("settle")}</h3><div className="reporting-form">{input("foreign_minor", settlement.foreign_minor, value => setSettlement({ ...settlement, foreign_minor: value }))}{input("posting_date", settlement.posting_date, value => setSettlement({ ...settlement, posting_date: value }), "date")}{period(settlement.period_id, value => setSettlement({ ...settlement, period_id: value }))}{input("reason", settlement.reason, value => setSettlement({ ...settlement, reason: value }))}</div><fieldset><legend>{t("settlementRate")}</legend><div className="reporting-form">{(["rate", "source", "effective_at"] as const).map(key => <div key={key}>{input(key, settlementRate[key], value => setSettlementRate({ ...settlementRate, [key]: value }))}</div>)}</div></fieldset><button disabled={locked || !mutation}>{t("settle")}</button></form>}
        </section>}
        {plan && <section className="panel" aria-label={t("plan")}><h2>{t("plan")} · {t(plan.status)}</h2><code dir="ltr">{plan.plan_digest}</code><p>{t("effect")}: <code dir="ltr">{plan.posting_effect_id ?? "—"}</code></p><p>{t("receipt")}: <code dir="ltr">{plan.receipt_id ?? "—"}</code></p>
          {plan.kind === "settle" && <dl>{([["historical", plan.equation.historical_release_minor], ["cash", plan.equation.functional_cash_minor], ["realized", plan.equation.realized_fx_minor]] as const).map(([key, value]) => <div key={key}><dt>{t(key)}</dt><dd><bdi>{money(String(value), plan)}</bdi></dd></div>)}</dl>}
          <div className="reporting-table" role="region" tabIndex={0} aria-label={t("nativeAccount")}><table><caption>{t("plan")}</caption><thead><tr><th>{t("nativeAccount")}</th><th>{t("debit")}</th><th>{t("credit")}</th></tr></thead><tbody>{plan.snapshot.lines.map(row => <tr key={row.line_number}><td><code dir="ltr">{row.account_id}</code></td><td><bdi>{money(row.debit_minor, plan)}</bdi></td><td><bdi>{money(row.credit_minor, plan)}</bdi></td></tr>)}</tbody></table></div>
          {plan.phase < 2 && input("reason", reason, setReason)}{plan.phase === 0 && can("finance_core.validate") && can("receivables.approve") && identity?.id !== plan.preparer_actor_id && <button disabled={locked || !mutation || !reason.trim()} onClick={() => void send(prepareScopedCommand(`${root}/plans/${encodeURIComponent(plan.id)}/review`, { expected_plan_digest: plan.plan_digest, reason }))}>{t("review")}</button>}
          {plan.phase === 1 && can("finance_core.post") && can("receivables.manage") && ![plan.preparer_actor_id, plan.reviewer_actor_id].includes(identity?.id ?? "") && <button disabled={locked || !mutation || !reason.trim()} onClick={() => void send(prepareScopedCommand(`${root}/plans/${encodeURIComponent(plan.id)}/post`, { expected_plan_digest: plan.plan_digest, reason }))}>{t("post")}</button>}
          <button disabled={locked} onClick={() => void verify()}>{t("verify")}</button>{proof && <><p role="status">{t("verified")}</p><div className="reporting-table" role="region" tabIndex={0} aria-label={t("audit")}><table><caption>{t("verified")}</caption><thead><tr><th>{t("action")}</th><th>{t("actor")}</th><th>{t("audit")}</th><th>{t("outbox")}</th></tr></thead><tbody>{proof.phases.map(row => <tr key={row.action}><td>{row.action}</td><td>{row.actor_id}</td><td><code dir="ltr">{row.audit_event_id}</code></td><td><code dir="ltr">{row.outbox_event_id}</code></td></tr>)}</tbody></table></div><button disabled={locked} onClick={download}>{t("download")}</button></>}
        </section>}
      </>}
    </>}
  </main>;
}
