import { useEffect, useRef, useState, type FormEvent } from "react";
import { useBrowserSession } from "../browserSession";
import { loadBudgetIdentity, type BudgetIdentity } from "../budget-control-data";
import { AdminApiError, beginBrowserAdminSession, endBrowserAdminSession, stepUpBrowserAdminSession } from "../data";
import { financeMoney } from "../enterprise-finance-data";
import { icRequest, mergeIcPlan, parseIcCatalog, parseIcDetail, parseIcPlan, verifyIcEvidence, verifyIcReport, type IcCatalog, type IcDetail, type IcEvidence, type IcGroupReport, type IcPlan, type IcScope } from "../intercompany-operations-data";
import { icTranslate, type IcMessage } from "../intercompany-operations-i18n";
import { formatExactDecimal } from "../locale-format";
import { prepareScopedCommand, type PreparedScopedCommand, type ScopedJsonValue } from "../scoped-command";
import type { Locale } from "../types";
import "./FinancialReportingPage.css";

const root = "/api/v1/intercompany-operations";
const blankDefinition = { seller_entity_id: "", buyer_entity_id: "", adjustment_entity_id: "", reference: "", amount_minor: "", period_id: "", posting_date: "", journal_code: "", receivable_account_code: "", payable_account_code: "", revenue_account_code: "", expense_account_code: "", cash_account_code: "", reason: "" };
export default function IntercompanyOperationsPage({ locale }: { locale: Locale }) {
  const auth = useBrowserSession(); return <IntercompanySession key={auth.revision} locale={locale} />;
}
function IntercompanySession({ locale }: { locale: Locale }) {
  const auth = useBrowserSession(), t = (key: IcMessage) => icTranslate(locale, key);
  const [identity, setIdentity] = useState<BudgetIdentity | null>(null), [login, setLogin] = useState({ tenant: "local", username: "", password: "" });
  const [scopeInput, setScopeInput] = useState<IcScope>({ workspace_id: "", organization_id: "" }), [scope, setScope] = useState<IcScope | null>(null);
  const [catalog, setCatalog] = useState<IcCatalog | null>(null), [sources, setSources] = useState<IcDetail[]>([]), [selected, setSelected] = useState("");
  const [detail, setDetail] = useState<IcDetail | null>(null), [plan, setPlan] = useState<IcPlan | null>(null), [proof, setProof] = useState<IcEvidence | null>(null), [report, setReport] = useState<IcGroupReport | null>(null);
  const [definition, setDefinition] = useState(blankDefinition), [progress, setProgress] = useState({ amount_minor: "", period_id: "", posting_date: "", reason: "" });
  const [mapping, setMapping] = useState({ seller_map_id: "", buyer_map_id: "", adjustment_map_id: "", period_id: "", as_of_date: "" }), [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false), [pending, setPending] = useState<PreparedScopedCommand | null>(null), [error, setError] = useState<IcMessage | null>(null), [refresh, setRefresh] = useState(0);
  const mounted = useRef(true), lock = useRef(false), epoch = useRef(0), alert = useRef<HTMLParagraphElement>(null), url = useRef<string | null>(null);
  const current = () => mounted.current && auth.isCurrent(auth.revision), locked = busy || Boolean(pending), can = (permission: string) => Boolean(identity?.human && identity.permissions.includes(permission));
  const mutation = Boolean(identity?.stepUp && scope), money = (value: string, precision: number, currency: string) => `${formatExactDecimal(financeMoney(value, precision), locale)} ${currency}`;
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; if (url.current) URL.revokeObjectURL(url.current); }; }, []);
  useEffect(() => { if (error) alert.current?.focus(); }, [error]);
  function clear() { setSources([]); setCatalog(null); setSelected(""); setDetail(null); setPlan(null); setProof(null); setReport(null); epoch.current++; }
  function fail(caught: unknown) {
    if (!current() || auth.recover(caught, auth.revision)) return;
    const denied = caught instanceof AdminApiError && [403, 404].includes(caught.status);
    if (denied) clear(); setError(denied ? "denied" : "error");
  }
  useEffect(() => {
    if (!auth.session) return; const abort = new AbortController();
    loadBudgetIdentity(auth.session, abort.signal).then(value => { if (current() && !abort.signal.aborted) {
      // Prefill before enabling scope inputs; edits never race a deferred identity response.
      setScopeInput({ workspace_id: value.workspaces[0] ?? "", organization_id: value.organizations[0] ?? "" }); setIdentity(value);
    } }).catch(caught => { if (!abort.signal.aborted) fail(caught); }); return () => abort.abort();
  }, [auth.session, auth.revision]);
  useEffect(() => {
    if (!auth.session || !scope || !identity) return; const abort = new AbortController();
    Promise.all([icRequest(auth.session, scope, root + "/catalog", undefined, abort.signal), icRequest(auth.session, scope, root + "/sources", undefined, abort.signal)]).then(([masters, page]) => {
      if (!current() || abort.signal.aborted) return; if (!Array.isArray(page.sources) || page.sources.length > 25) throw new Error("intercompany_contract_invalid");
      setCatalog(parseIcCatalog(masters.catalog)); setSources(page.sources.map(row => parseIcDetail(row, scope)));
    }).catch(caught => { if (!abort.signal.aborted) fail(caught); }); return () => abort.abort();
  }, [scope, identity, refresh, auth.session]);
  useEffect(() => {
    if (!auth.session || !scope || !selected) return; const abort = new AbortController();
    icRequest(auth.session, scope, `${root}/sources/${encodeURIComponent(selected)}`, undefined, abort.signal).then(raw => {
      if (!current() || abort.signal.aborted) return; const retained = parseIcDetail(raw.source, scope); setDetail(retained);
      setPlan(old => { const updated = old ? retained.plans.find(row => row.id === old.id) : null; return updated ? mergeIcPlan(old, updated) : retained.plans.find(row => row.phase < 2) ?? retained.plans.at(-1) ?? null; });
    }).catch(caught => { if (!abort.signal.aborted) fail(caught); }); return () => abort.abort();
  }, [scope, selected, refresh, auth.session]);
  useEffect(() => { setProof(null); setReport(null); epoch.current++; }, [plan?.id, plan?.phase, scope, auth.revision]);
  async function authenticate(event: FormEvent, stepUp = false) {
    event.preventDefault(); if (lock.current) return; lock.current = true; setBusy(true); setError(null);
    try { if (stepUp && auth.session) { await stepUpBrowserAdminSession(auth.session, login.password); const value = await loadBudgetIdentity(auth.session); if (current()) setIdentity(value); }
      else { const session = await beginBrowserAdminSession({ tenantId: login.tenant, username: login.username, password: login.password }); if (current()) auth.begin(session, login.username, auth.revision); } }
    catch (caught) { fail(caught); } finally { lock.current = false; if (current()) { setBusy(false); setLogin(old => ({ ...old, password: "" })); } }
  }
  async function logout() { if (!auth.session || lock.current) return; lock.current = true; try { await endBrowserAdminSession(auth.session); } catch (caught) { fail(caught); } finally { lock.current = false; auth.clear(auth.revision); } }
  async function send(command: PreparedScopedCommand) {
    if (!auth.session || !scope || lock.current) return; lock.current = true; setBusy(true); setPending(command); setError(null); setProof(null); setReport(null); epoch.current++;
    try {
      const raw = await icRequest(auth.session, scope, command.path, command.body), ack = parseIcPlan(raw.plan, scope);
      if (!current()) return; setPlan(old => mergeIcPlan(old, ack)); setSelected(ack.source_id); setPending(null);
      setDetail(old => old?.id === ack.source_id && ack.kind === "eliminate" && ack.phase === 2 ? { ...old, closed: true } : old);
      setRefresh(old => old + 1);
    } catch (caught) {
      if (current()) {
        if (caught instanceof AdminApiError && caught.status < 500) { setPending(null); fail(caught); }
        else { if (!auth.recover(caught, auth.revision)) setError("unknown"); }
      }
    } finally { lock.current = false; if (current()) setBusy(false); }
  }
  function prepare(event: FormEvent) { event.preventDefault(); if (mutation && !locked) void send(prepareScopedCommand(root + "/sources", definition)); }
  function progressSource(event: FormEvent, elimination: boolean) {
    event.preventDefault(); if (!detail || !mutation || locked) return;
    const body: Record<string, ScopedJsonValue> = { period_id: progress.period_id, posting_date: progress.posting_date, reason: progress.reason };
    if (!elimination) body.amount_minor = progress.amount_minor;
    void send(prepareScopedCommand(`${root}/sources/${encodeURIComponent(detail.id)}/${elimination ? "eliminations" : "settlements"}`, body));
  }
  async function verify() {
    if (!auth.session || !scope || !plan || lock.current) return; const expected = plan, generation = epoch.current; lock.current = true; setBusy(true); setError(null); setProof(null);
    try { const raw = await icRequest(auth.session, scope, `${root}/plans/${encodeURIComponent(plan.id)}/evidence`), checked = await verifyIcEvidence(raw.evidence, scope, expected);
      if (current() && generation === epoch.current) setProof(checked); }
    catch (caught) { fail(caught); } finally { lock.current = false; if (current()) setBusy(false); }
  }
  async function loadReport(event: FormEvent) {
    event.preventDefault(); if (!auth.session || !scope || !detail || lock.current) return; const generation = epoch.current; lock.current = true; setBusy(true); setError(null); setReport(null);
    try { const raw = await icRequest(auth.session, scope, `${root}/sources/${encodeURIComponent(detail.id)}/report?${new URLSearchParams(mapping)}`), checked = await verifyIcReport(raw.report, scope, detail);
      if (current() && generation === epoch.current) setReport(checked); }
    catch (caught) { fail(caught); } finally { lock.current = false; if (current()) setBusy(false); }
  }
  function download(value: IcEvidence | IcGroupReport, filename: string) {
    if (url.current) URL.revokeObjectURL(url.current);
    url.current = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2)], { type: "application/json" })); const anchor = document.createElement("a");
    anchor.href = url.current; anchor.download = filename; anchor.click();
  }
  const input = (key: IcMessage, value: string, changed: (value: string) => void, type = "text", extraDisabled = false) => <label>{t(key)}<input type={type} value={value} disabled={locked || extraDisabled} required onChange={event => changed(event.target.value)} /></label>;
  const choices = (key: IcMessage, value: string, changed: (value: string) => void, rows: { value: string; label: string }[]) => <label>{t(key)}<select value={value} disabled={locked} required onChange={event => changed(event.target.value)}><option value="">—</option>{rows.map(row => <option key={row.value} value={row.value}>{row.label}</option>)}</select></label>;
  const periods = catalog?.periods.map(row => ({ value: row.id, label: `${row.name} · ${row.status}` })) ?? [];
  const nativeAccount = (key: keyof typeof blankDefinition & IcMessage, kind: string) => choices(key, definition[key], value => setDefinition(old => ({ ...old, [key]: value })), catalog?.accounts.filter(row => row.account_type === kind).map(row => ({ value: row.account_code, label: row.account_code })) ?? []);
  return <main id="main-content" className="financial-reporting" dir={locale === "ar" ? "rtl" : "ltr"} style={{ paddingBottom: "calc(6rem + env(safe-area-inset-bottom))", overflowWrap: "anywhere" }}>
    <h1>{t("title")}</h1><p>{t("boundary")}</p>{error && <p role="alert" tabIndex={-1} ref={alert}>{t(error)}</p>}
    {!auth.session ? <form aria-label={t("login")} onSubmit={event => void authenticate(event)}><div className="reporting-form">{input("tenant", login.tenant, value => setLogin(old => ({ ...old, tenant: value })))}{input("username", login.username, value => setLogin(old => ({ ...old, username: value })))}{input("password", login.password, value => setLogin(old => ({ ...old, password: value })), "password")}</div><button disabled={locked}>{t("login")}</button></form> : <>
      <p><bdi>{auth.username}</bdi> <button disabled={locked} onClick={() => void logout()}>{t("logout")}</button></p>
      {identity && !identity.stepUp && <form aria-label={t("stepUp")} onSubmit={event => void authenticate(event, true)}>{input("password", login.password, value => setLogin(old => ({ ...old, password: value })), "password")}<button disabled={locked}>{t("stepUp")}</button></form>}
      <form aria-label={t("scope")} onSubmit={event => { event.preventDefault(); if (!identity || locked) return; clear(); setScope({ ...scopeInput }); }}><div className="reporting-form">
        {input("workspace_id", scopeInput.workspace_id, value => setScopeInput(old => ({ ...old, workspace_id: value })), "text", !identity)}{input("organization_id", scopeInput.organization_id, value => setScopeInput(old => ({ ...old, organization_id: value })), "text", !identity)}
      </div><button disabled={locked || !identity || !can("intercompany_operations.read") || !can("finance_core.read")}>{t("apply")}</button></form>
      {pending && <button disabled={busy} onClick={() => void send(pending)}>{t("retry")}</button>}
      {scope && catalog && <>
        {can("intercompany_operations.prepare") && can("finance_core.manage") && <form aria-label={t("prepare")} onSubmit={prepare}><h2>{t("prepare")}</h2><div className="reporting-form">
          {(["seller_entity_id", "buyer_entity_id", "adjustment_entity_id"] as const).map(key => <div key={key}>{choices(key, definition[key], value => setDefinition(old => ({ ...old, [key]: value })), catalog.entities.map(row => ({ value: row.id, label: `${row.entity_code} · ${row.currency_code}` })))}</div>)}
          {(["reference", "amount_minor", "reason"] as const).map(key => <div key={key}>{input(key, definition[key], value => setDefinition(old => ({ ...old, [key]: value })))}</div>)}
          {input("posting_date", definition.posting_date, value => setDefinition(old => ({ ...old, posting_date: value })), "date")}{choices("period_id", definition.period_id, value => setDefinition(old => ({ ...old, period_id: value })), periods)}
          {choices("journal_code", definition.journal_code, value => setDefinition(old => ({ ...old, journal_code: value })), catalog.journals.map(row => ({ value: row.journal_code, label: row.journal_code })))}
          {nativeAccount("receivable_account_code", "Asset")}{nativeAccount("payable_account_code", "Liability")}{nativeAccount("revenue_account_code", "Income")}{nativeAccount("expense_account_code", "Expense")}{nativeAccount("cash_account_code", "Asset")}
        </div><button disabled={locked || !mutation}>{t("prepare")}</button></form>}
        {choices("sources", selected, value => { setSelected(value); setDetail(null); setPlan(null); setProof(null); setReport(null); epoch.current++; }, sources.map(row => ({ value: row.id, label: row.request.reference })))}
        {detail && <section className="panel" aria-label={t("history")}><h2>{detail.request.reference}</h2><p>{t("residual")}: <bdi>{money(detail.outstanding_minor, detail.monetary_policy.currency_precision, detail.monetary_policy.currency_code)}</bdi></p>
          <p>{["seller", "buyer", "adjustment"].map(book => `${detail.request[`${book}_entity_code`]} (${detail.request[`${book}_entity_id`]})`).join(" · ")}</p>
          {detail.plans.map(row => <button key={row.id} disabled={locked} onClick={() => { setPlan(row); setProof(null); epoch.current++; }}>{row.sequence} · {t(row.kind === "recognize" ? "recognize" : row.kind)} · {t(row.status)}</button>)}
          {detail.closed ? <p>{t("sealed")}</p> : detail.recognized && detail.plans.every(row => row.phase === 2) && plan?.phase === 2 && can("intercompany_operations.prepare") && can("finance_core.manage") && <>
            <form aria-label={t("settle")} onSubmit={event => progressSource(event, false)}><h3>{t("settle")}</h3><div className="reporting-form">{input("settlement_minor", progress.amount_minor, value => setProgress(old => ({ ...old, amount_minor: value })))}{input("posting_date", progress.posting_date, value => setProgress(old => ({ ...old, posting_date: value })), "date")}{choices("period_id", progress.period_id, value => setProgress(old => ({ ...old, period_id: value })), periods)}{input("reason", progress.reason, value => setProgress(old => ({ ...old, reason: value })))}</div><button disabled={locked || !mutation || BigInt(detail.outstanding_minor) === 0n}>{t("settle")}</button></form>
            <form aria-label={t("eliminate")} onSubmit={event => progressSource(event, true)}><h3>{t("eliminate")}</h3><div className="reporting-form">{input("posting_date", progress.posting_date, value => setProgress(old => ({ ...old, posting_date: value })), "date")}{choices("period_id", progress.period_id, value => setProgress(old => ({ ...old, period_id: value })), periods)}{input("reason", progress.reason, value => setProgress(old => ({ ...old, reason: value })))}</div><button disabled={locked || !mutation}>{t("eliminate")}</button></form>
          </>}
        </section>}
        {plan && <section className="panel" aria-label={t("plan")}><h2>{t("plan")} · {t(plan.status)}</h2><code dir="ltr">{plan.plan_digest}</code>
          {plan.entries.map(entry => <div key={entry.entry_id}><h3>{entry.book} · <code dir="ltr">{entry.entry_id}</code></h3><p>{t("effect")}: <code dir="ltr">{plan.posting_effect_ids[entry.book] ?? "—"}</code></p><div className="reporting-table" role="region" tabIndex={0} aria-label={`${t("book")} ${entry.book}`}><table><caption>{entry.book}</caption><thead><tr><th>{t("account")}</th><th>{t("debit")}</th><th>{t("credit")}</th></tr></thead><tbody>{entry.snapshot.lines.map(line => <tr key={line.line_number}><td><code dir="ltr">{line.account_id}</code></td><td><bdi>{money(line.debit_minor, plan.currency_precision, plan.currency_code)}</bdi></td><td><bdi>{money(line.credit_minor, plan.currency_precision, plan.currency_code)}</bdi></td></tr>)}</tbody></table></div></div>)}
          {plan.phase < 2 && input("reason", reason, setReason)}
          {plan.phase === 0 && can("intercompany_operations.review") && can("finance_core.validate") && identity?.id !== plan.preparer_actor_id && <button disabled={locked || !mutation || !reason.trim()} onClick={() => void send(prepareScopedCommand(`${root}/plans/${encodeURIComponent(plan.id)}/review`, { expected_plan_digest: plan.plan_digest, reason }))}>{t("review")}</button>}
          {plan.phase === 1 && can("intercompany_operations.post") && can("finance_core.post") && ![plan.preparer_actor_id, plan.reviewer_actor_id].includes(identity?.id ?? "") && <button disabled={locked || !mutation || !reason.trim()} onClick={() => void send(prepareScopedCommand(`${root}/plans/${encodeURIComponent(plan.id)}/post`, { expected_plan_digest: plan.plan_digest, reason }))}>{t("post")}</button>}
          <button disabled={locked} onClick={() => void verify()}>{t("verify")}</button>{proof && <><p role="status">{t("verified")}</p><div className="reporting-table" role="region" tabIndex={0} aria-label={t("audit")}><table><thead><tr><th>{t("actor")}</th><th>{t("audit")}</th><th>{t("outbox")}</th></tr></thead><tbody>{proof.phases.map(row => <tr key={row.action}><td>{row.actor_id}</td><td><code dir="ltr">{row.audit_event_id}</code></td><td><code dir="ltr">{row.outbox_event_id}</code></td></tr>)}</tbody></table></div><button disabled={locked} onClick={() => download(proof, `${proof.plan.id}-evidence.json`)}>{t("download")}</button></>}
        </section>}
        {detail?.closed && <form aria-label={t("report")} onSubmit={event => void loadReport(event)}><h2>{t("report")}</h2><div className="reporting-form">
          {(["seller", "buyer", "adjustment"] as const).map(book => { const key = `${book}_map_id` as "seller_map_id" | "buyer_map_id" | "adjustment_map_id"; return <div key={key}>{choices(key, mapping[key], value => setMapping(old => ({ ...old, [key]: value })), catalog.maps.filter(row => row.legal_entity_id === detail.request[`${book}_entity_id`]).map(row => ({ value: row.id, label: row.name })))}</div>; })}
          {choices("period_id", mapping.period_id, value => setMapping(old => ({ ...old, period_id: value })), periods)}{input("as_of_date", mapping.as_of_date, value => setMapping(old => ({ ...old, as_of_date: value })), "date")}
        </div><button disabled={locked}>{t("report")}</button></form>}
        {report && <section className="panel" aria-label={t("reportVerified")}><p role="status">{t("reportVerified")}</p><code dir="ltr">{report.report_digest}</code><dl>{(["income", "expense", "cash"] as const).map(key => <div key={key}><dt>{t(key)}</dt><dd>{money(key === "cash" ? report.cash_net_movements.activity_minor : report.income_statement[`${key}_minor`], report.currency_policy.currency_precision, report.currency_policy.currency_code)}</dd></div>)}</dl>
          <div className="reporting-table" role="region" tabIndex={0} aria-label={t("drilldown")}><table><thead><tr><th>{t("account")}</th><th>{t("balance")}</th><th>{t("drilldown")}</th></tr></thead><tbody>{report.trial_balance.map(row => <tr key={row.account_id}><td>{row.account_code}</td><td>{money(row.closing.balance_minor, report.currency_policy.currency_precision, report.currency_policy.currency_code)}</td><td><details><summary>{t("drilldown")} ({row.postings.length})</summary>{row.postings.map(line => <p key={`${line.effect_id}:${line.line_number}`}><bdi>{line.legal_entity_id}</bdi> · <code dir="ltr">{line.effect_id}</code> · {line.debit_minor}/{line.credit_minor}</p>)}</details></td></tr>)}</tbody></table></div><button disabled={locked} onClick={() => download(report, `${detail?.id}-group-report.json`)}>{t("downloadReport")}</button>
        </section>}
      </>}
    </>}
  </main>;
}
