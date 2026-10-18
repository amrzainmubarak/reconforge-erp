import { useEffect, useRef, useState, type FormEvent } from "react";
import { useBrowserSession } from "../browserSession";
import { loadBudgetIdentity, type BudgetIdentity } from "../budget-control-data";
import { AdminApiError, beginBrowserAdminSession, endBrowserAdminSession } from "../data";
import { financeMoney } from "../enterprise-finance-data";
import { canonicalIc } from "../intercompany-operations-data";
import { downloadCashflowOriginal, requestCashflow, verifyCashflowView, type CashflowView } from "../intercompany-cashflow-data";
import { cashflowTranslate, type CashflowWord } from "../intercompany-cashflow-i18n";
import { fxRequest, parseFxDetail, verifyFxEvidence, verifyFxReport, type FxDetail, type FxScope } from "../intercompany-fx-data";
import { formatExactDecimal } from "../locale-format";
import type { Locale } from "../types";
import "./FinancialReportingPage.css";
import "./IntercompanyCashflowPage.css";

export default function IntercompanyCashflowPage({ locale }: { locale: Locale }) { const auth = useBrowserSession(); return <CashflowSession key={auth.revision} locale={locale} />; }
function CashflowSession({ locale }: { locale: Locale }) {
  const auth = useBrowserSession(), revision = auth.revision, t = (key: CashflowWord) => cashflowTranslate(locale, key);
  const [identity, setIdentity] = useState<BudgetIdentity | null>(null), [login, setLogin] = useState({ tenant: "local", username: "", password: "" });
  const [input, setInput] = useState<FxScope>({ workspace_id: "", organization_id: "" }), [scope, setScope] = useState<FxScope | null>(null);
  const [sources, setSources] = useState<{ id: string; reference: string }[]>([]), [cursor, setCursor] = useState<string | null>(null), [selected, setSelected] = useState("");
  const [source, setSource] = useState<FxDetail | null>(null), [confirmed, setConfirmed] = useState(false), [view, setView] = useState<CashflowView | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState<CashflowWord | null>(null), [saved, setSaved] = useState(false);
  const mounted = useRef(true), epoch = useRef(0), active = useRef<AbortController | null>(null);
  const canRead = Boolean(identity?.permissions.includes("intercompany_fx.read") && identity.permissions.includes("finance_core.read"));
  const current = (captured: number) => mounted.current && captured === epoch.current && auth.isCurrent(revision);
  function invalidate() { epoch.current++; active.current?.abort(); active.current = null; setBusy(false); setView(null); setSource(null); setConfirmed(false); setSaved(false); setError(null); }
  function fail(caught: unknown, captured: number) { if (!current(captured) || auth.recover(caught, revision)) return; setView(null); setSaved(false); setConfirmed(false); if (caught instanceof AdminApiError && [403, 404].includes(caught.status)) { setSource(null); setError("denied"); } else setError(caught instanceof AdminApiError && caught.status === 503 ? "unavailable" : "invalid"); }
  async function run(operation: (signal: AbortSignal, captured: number) => Promise<void>) {
    if (active.current) return;
    const abort = new AbortController(), captured = epoch.current; active.current = abort; setBusy(true); setError(null); setSaved(false);
    try { await operation(abort.signal, captured); } catch (caught) { if (!abort.signal.aborted) fail(caught, captured); }
    finally { if (active.current === abort) { active.current = null; if (current(captured)) setBusy(false); } }
  }
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; active.current?.abort(); }; }, []);
  useEffect(() => {
    if (!auth.session) return;
    const abort = new AbortController(), captured = epoch.current;
    loadBudgetIdentity(auth.session, abort.signal).then(value => { if (current(captured) && !abort.signal.aborted) { setIdentity(value); setInput({ workspace_id: value.workspaces[0] ?? "", organization_id: value.organizations[0] ?? "" }); } }).catch(caught => { if (!abort.signal.aborted) fail(caught, captured); });
    return () => abort.abort();
  }, [auth.session, revision]);
  async function list(selectedScope: FxScope, after = "") {
    if (!auth.session || !canRead) return;
    await run(async (signal, captured) => {
      const raw = await fxRequest(auth.session!, selectedScope, "/api/v1/intercompany-fx/sources?after=" + encodeURIComponent(after), undefined, signal), page = raw.sources as { items?: unknown; next_cursor?: unknown };
      if (!page || !Array.isArray(page.items) || page.items.length > 50 || page.next_cursor !== null && typeof page.next_cursor !== "string") throw new Error("invalid_source_page");
      const rows = page.items.map(row => { if (!row || typeof row !== "object" || typeof row.id !== "string" || !/^IC2S-[0-9a-f]{32}$/.test(row.id) || typeof row.reference !== "string" || row.reference.length > 500) throw new Error("invalid_source_page"); return { id: row.id, reference: row.reference }; });
      if (new Set(rows.map(row => row.id)).size !== rows.length) throw new Error("duplicate_source_page");
      if (current(captured)) { setSources(rows); setCursor(page.next_cursor as string | null); }
    });
  }
  function apply(event: FormEvent) { event.preventDefault(); if (!identity || !canRead) return; invalidate(); setSelected(""); setSources([]); setCursor(null); const next = { ...input }; setScope(next); void list(next); }
  async function load(id: string) {
    invalidate(); setSelected(id);
    if (!id || !scope || !auth.session || !canRead) return;
    await run(async (signal, captured) => {
      const raw = await fxRequest(auth.session!, scope, `/api/v1/intercompany-fx/sources/${encodeURIComponent(id)}`, undefined, signal), detail = parseFxDetail(raw.source, scope);
      if (detail.id !== id) throw new Error("source_subject_changed");
      const original = await fxRequest(auth.session!, scope, `/api/v1/intercompany-fx/plans/${encodeURIComponent(detail.plans[0].id)}/evidence`, undefined, signal);
      const proof = await verifyFxEvidence(original.evidence, scope, detail.plans[0]);
      const { state: _state, plans: _plans, ...definition } = detail;
      if (canonicalIc(proof.source) !== canonicalIc(definition)) throw new Error("source_original_seal_changed");
      if (current(captured)) setSource(detail);
    });
  }
  async function verify() {
    if (!auth.session || !scope || !source || !confirmed || !canRead) return;
    const retained = source; setView(null);
    await run(async (signal, captured) => {
      const raw = await requestCashflow(auth.session!, scope, retained, signal);
      for (const plan of retained.plans) { const proof = await fxRequest(auth.session!, scope, `/api/v1/intercompany-fx/plans/${encodeURIComponent(plan.id)}/evidence`, undefined, signal); await verifyFxEvidence(proof.evidence, scope, plan); }
      const translated = await fxRequest(auth.session!, scope, `/api/v1/intercompany-fx/sources/${encodeURIComponent(retained.id)}/report`, undefined, signal), report = await verifyFxReport(translated.report, retained);
      const result = await verifyCashflowView(raw, retained, report, auth.session!.tenantId);
      if (current(captured)) setView(result);
    });
  }
  async function download() {
    if (!auth.session || !scope || !source || !view || !confirmed || !canRead) return;
    const retained = source, expected = view;
    await run(async (signal, captured) => {
      const blob = await downloadCashflowOriginal(auth.session!, scope, retained, expected, signal);
      if (!current(captured)) return;
      const url = URL.createObjectURL(blob), link = document.createElement("a"); link.href = url; link.download = `${retained.id}-original-cashflow.json`;
      try { link.click(); } finally { URL.revokeObjectURL(url); }
      setSaved(true);
    });
  }
  async function authenticate(event: FormEvent) { event.preventDefault(); await run(async (_signal, captured) => { const session = await beginBrowserAdminSession({ tenantId: login.tenant, username: login.username, password: login.password }); if (current(captured)) { setLogin(old => ({ ...old, password: "" })); auth.begin(session, login.username, revision); } }); }
  const money = (minor: string, policy: { currency_precision: number; currency_code: string }) => `${formatExactDecimal(financeMoney(minor, policy.currency_precision), locale)} ${policy.currency_code}`;
  const fields = [["openingValue", "opening_minor"], ["inflow", "operating_inflow_minor"], ["outflow", "operating_outflow_minor"], ["operating", "operating_net_minor"], ["exchange", "fx_on_cash_minor"], ["closing", "closing_minor"]] as const;
  return <main id="main-content" className="financial-reporting source-cashflow" dir={locale === "ar" ? "rtl" : "ltr"} aria-busy={busy}>
    <header><h1>{t("title")}</h1><p>{t("boundary")}</p><p>{t("coverage")}</p></header>
    {error && <p role="alert">{t(error)}</p>}{busy && <p role="status">{t("loading")}</p>}{saved && <p role="status">{t("saved")}</p>}
    {!auth.session ? <form className="panel reporting-form" aria-label={t("login")} onSubmit={event => void authenticate(event)}>{(["tenant", "username", "password"] as const).map(key => <label key={key}>{t(key)}<input aria-label={t(key)} type={key === "password" ? "password" : "text"} autoComplete={key === "password" ? "current-password" : key === "username" ? "username" : "off"} required disabled={busy} value={login[key]} onChange={event => setLogin(old => ({ ...old, [key]: event.target.value }))} /></label>)}<button disabled={busy}>{t("login")}</button></form> : <>
      <section className="panel"><bdi>{auth.username}</bdi><button disabled={busy} onClick={() => void run(async (_signal, captured) => { try { await endBrowserAdminSession(auth.session!); } finally { if (current(captured)) auth.clear(revision); } })}>{t("logout")}</button></section>
      <form className="panel reporting-form" aria-label={t("apply")} onSubmit={apply}>{([["workspace", "workspace_id"], ["organization", "organization_id"]] as const).map(([label, key]) => <label key={key}>{t(label)}<input aria-label={t(label)} required disabled={!identity} value={input[key]} onChange={event => { invalidate(); setScope(null); setSelected(""); setSources([]); setInput(old => ({ ...old, [key]: event.target.value })); }} /></label>)}<button disabled={!identity || !canRead || busy}>{t("apply")}</button></form>
      {scope && canRead && <section className="panel"><label>{t("source")}<select aria-label={t("source")} value={selected} onChange={event => void load(event.target.value)}><option value="">—</option>{sources.map(row => <option key={row.id} value={row.id}>{row.reference} · {row.id}</option>)}</select></label><button disabled={busy || !selected} onClick={() => void load(selected)}>{t("refresh")}</button>{cursor && <button disabled={busy} onClick={() => { invalidate(); setSelected(""); void list(scope, cursor); }}>{t("more")}</button>}{!busy && !sources.length && <p role="status">{t("empty")}</p>}</section>}
      {source && <section className="panel"><h2>{t("origin")}</h2><p><bdi>{source.request.reference}</bdi></p><code>{source.id} · {source.source_digest}</code><p><code>{source.plans[0].id} · {source.plans[0].plan_digest}</code></p>{source.state.closed ? <><label className="cashflow-opening"><input type="checkbox" aria-label={t("opening")} checked={confirmed} disabled={busy} onChange={event => { setConfirmed(event.target.checked); setView(null); setSaved(false); }} />{t("opening")}</label><button disabled={busy || !confirmed} onClick={() => void verify()}>{t("verify")}</button></> : <p role="status">{t("incomplete")}</p>}</section>}
      {view && <>
        <section className="panel"><h2>{t("statement")}</h2><dl className="cashflow-totals">{fields.map(([label, key]) => <div key={key}><dt>{t(label)}</dt><dd><bdi>{money(view.cashflow[key], view.cashflow.reporting_policy)}</bdi></dd></div>)}</dl><p>{t("policy")}: {view.cashflow.reporting_policy.currency_rounding_policy} · {view.cashflow.reporting_policy.currency_registry_version}</p><code>{view.cashflow.report_digest} · {view.cashflow.elimination_plan_digest}</code></section>
        {(["seller", "buyer"] as const).map(book => { const value = view.cashflow.books[book]; return <section className="panel" key={book}><h2>{t(book)}</h2><p><bdi>{value.legal_entity_id}</bdi> · {t("native")}: <bdi>{money(value.native_cash_minor, value.functional_policy)}</bdi></p><p>{t("rates")}: <bdi>{value.closing_rate.rate} · {value.closing_rate.source} · {value.closing_rate.effective_at}</bdi></p><div className="reporting-table" role="region" aria-label={`${t(book)} · ${t("movements")}`} tabIndex={0}><table><caption>{t("movements")}</caption><thead><tr><th>{t("date")}</th><th>{t("effect")}</th><th>{t("native")}</th><th>{t("historical")}</th><th>{t("operating")}</th></tr></thead><tbody>{value.movements.map(row => <tr key={row.effect_id + ":" + row.line_number}><td><bdi>{row.posting_date}</bdi></td><td><code>{row.effect_id}<br />{row.entry_id} · {row.line_number}</code><br /><bdi>{row.account_code}</bdi></td><td><bdi>{money(row.native_minor, value.functional_policy)}</bdi></td><td><bdi>{row.historical_rate.rate} · {row.historical_rate.source} · {row.historical_rate.effective_at}</bdi></td><td><bdi>{money(row.operating_minor, view.cashflow.reporting_policy)}</bdi></td></tr>)}</tbody></table></div></section>; })}
        <section className="panel"><h2>{t("raw")}</h2><code>{view.evidence_sha256}</code><p><bdi>{view.evidence_bytes}</bdi></p><p>{t("cli")}</p><button disabled={busy} onClick={() => void download()}>{t("download")}</button></section>
      </>}
    </>}
  </main>;
}
