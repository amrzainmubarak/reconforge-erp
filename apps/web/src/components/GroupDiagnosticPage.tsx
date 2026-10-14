import { useEffect, useRef, useState, type FormEvent } from "react";
import { useBrowserSession } from "../browserSession";
import { loadBudgetIdentity, type BudgetIdentity } from "../budget-control-data";
import { AdminApiError, beginBrowserAdminSession, endBrowserAdminSession } from "../data";
import { financeMoney } from "../enterprise-finance-data";
import { captureGroupOriginal, downloadGroupOriginal, requestGroupView, verifyGroupView, type GroupOriginal, type GroupView } from "../group-diagnostic-data";
import { groupTranslate, type GroupWord } from "../group-diagnostic-i18n";
import { fxRequest, type FxScope } from "../intercompany-fx-data";
import { canonicalIc } from "../intercompany-operations-data";
import { formatExactDecimal } from "../locale-format";
import type { Locale } from "../types";
import "./FinancialReportingPage.css";
import "./GroupDiagnosticPage.css";

export default function GroupDiagnosticPage({ locale }: { locale: Locale }) { const auth = useBrowserSession(); return <GroupSession key={auth.revision} locale={locale} />; }
function GroupSession({ locale }: { locale: Locale }) {
  const auth = useBrowserSession(), revision = auth.revision, t = (key: GroupWord) => groupTranslate(locale, key);
  const [identity, setIdentity] = useState<BudgetIdentity | null>(null), [login, setLogin] = useState({ tenant: "local", username: "", password: "" });
  const [input, setInput] = useState<FxScope>({ workspace_id: "", organization_id: "" }), [scope, setScope] = useState<FxScope | null>(null);
  const [catalog, setCatalog] = useState<{ id: string; reference: string }[]>([]), [cursor, setCursor] = useState<string | null>(null), [candidate, setCandidate] = useState("");
  const [confirmed, setConfirmed] = useState(false), [originals, setOriginals] = useState<GroupOriginal[]>([]), [view, setView] = useState<GroupView | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState<GroupWord | null>(null), [saved, setSaved] = useState(false);
  const epoch = useRef(0), mounted = useRef(true), active = useRef<AbortController | null>(null);
  const canRead = Boolean(identity?.permissions.includes("intercompany_fx.read") && identity.permissions.includes("finance_core.read"));
  const current = (captured: number) => mounted.current && epoch.current === captured && auth.isCurrent(revision);
  function invalidate(clearSources = false) { epoch.current++; active.current?.abort(); active.current = null; setBusy(false); setView(null); setSaved(false); setError(null); if (clearSources) { setOriginals([]); setConfirmed(false); setCandidate(""); } }
  function failed(caught: unknown, captured: number) { if (!current(captured) || auth.recover(caught, revision)) return; setView(null); setSaved(false); if (caught instanceof AdminApiError && [403, 404].includes(caught.status)) { setOriginals([]); setCatalog([]); setCandidate(""); setConfirmed(false); setError("denied"); } else setError(caught instanceof AdminApiError && caught.status === 503 ? "unavailable" : "invalid"); }
  async function run(operation: (signal: AbortSignal, captured: number) => Promise<void>) {
    if (active.current) return; const abort = new AbortController(), captured = epoch.current; active.current = abort; setBusy(true); setSaved(false); setError(null);
    try { await operation(abort.signal, captured); } catch (caught) { if (!abort.signal.aborted) failed(caught, captured); }
    finally { if (active.current === abort) { active.current = null; if (current(captured)) setBusy(false); } }
  }
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; active.current?.abort(); }; }, []);
  useEffect(() => { if (!auth.session) return; const abort = new AbortController(), captured = epoch.current; loadBudgetIdentity(auth.session, abort.signal).then(value => { if (current(captured) && !abort.signal.aborted) { setIdentity(value); setInput({ workspace_id: value.workspaces[0] ?? "", organization_id: value.organizations[0] ?? "" }); } }).catch(caught => { if (!abort.signal.aborted) failed(caught, captured); }); return () => abort.abort(); }, [auth.session, revision]);
  async function list(next: FxScope, after = "") {
    if (!auth.session || !canRead) return;
    await run(async (signal, captured) => { const raw = await fxRequest(auth.session!, next, "/api/v1/intercompany-fx/sources?after=" + encodeURIComponent(after), undefined, signal), page = raw.sources as { items?: unknown; next_cursor?: unknown }; if (!page || !Array.isArray(page.items) || page.items.length > 50 || page.next_cursor !== null && typeof page.next_cursor !== "string") throw new Error("group_source_catalog_invalid"); const rows = page.items.map(row => { if (!row || typeof row !== "object" || typeof row.id !== "string" || !/^IC2S-[0-9a-f]{32}$/.test(row.id) || typeof row.reference !== "string" || row.reference.length > 500) throw new Error("group_source_catalog_invalid"); return { id: row.id, reference: row.reference }; }); if (new Set(rows.map(row => row.id)).size !== rows.length) throw new Error("group_source_catalog_duplicate"); if (current(captured)) { setCatalog(rows); setCursor(page.next_cursor as string | null); } });
  }
  function apply(event: FormEvent) { event.preventDefault(); if (!identity || !canRead) return; invalidate(true); setCatalog([]); setCursor(null); const next = { ...input }; setScope(next); void list(next); }
  async function add() {
    if (!auth.session || !scope || !candidate || !confirmed || !canRead || originals.length >= 16 || originals.some(row => row.detail.id === candidate)) return;
    const id = candidate, retained = originals; invalidate();
    await run(async (signal, captured) => { const value = await captureGroupOriginal(auth.session!, scope, id, true, signal); if (current(captured)) { setOriginals([...retained, value].sort((a, b) => a.detail.id < b.detail.id ? -1 : 1)); setCandidate(""); setConfirmed(false); } });
  }
  async function refresh() {
    if (!auth.session || !scope || !originals.length || !canRead) return; const retained = originals; invalidate();
    await run(async (signal, captured) => { const refreshed = []; for (const row of retained) { const next = await captureGroupOriginal(auth.session!, scope, row.detail.id, true, signal); if (canonicalIc(next.pin) !== canonicalIc(row.pin)) throw new Error("group_original_pin_changed"); refreshed.push(next); } if (current(captured)) setOriginals(refreshed); });
  }
  async function verify() {
    if (!auth.session || !scope || !originals.length || !canRead) return; const retained = originals; setView(null);
    await run(async (signal, captured) => { const raw = await requestGroupView(auth.session!, scope, retained, signal), result = await verifyGroupView(raw, retained, scope, auth.session!.tenantId); if (current(captured)) setView(result); });
  }
  async function download() {
    if (!auth.session || !scope || !view || !canRead) return; const retained = originals, expected = view;
    await run(async (signal, captured) => { const blob = await downloadGroupOriginal(auth.session!, scope, retained, expected, signal); if (!current(captured)) return; const url = URL.createObjectURL(blob), link = document.createElement("a"); link.href = url; link.download = "selected-original-group-diagnostic.json"; document.body.append(link); try { link.click(); } finally { link.remove(); setTimeout(() => URL.revokeObjectURL(url), 0); } setSaved(true); });
  }
  async function authenticate(event: FormEvent) { event.preventDefault(); await run(async (_signal, captured) => { const session = await beginBrowserAdminSession({ tenantId: login.tenant, username: login.username, password: login.password }); if (current(captured)) { setLogin(old => ({ ...old, password: "" })); auth.begin(session, login.username, revision); } }); }
  const money = (minor: string) => { const policy = view!.diagnostic.reporting_policy; return `${formatExactDecimal(financeMoney(minor, policy.currency_precision), locale)} ${policy.currency_code}`; };
  return <main id="main-content" className="financial-reporting group-diagnostic" dir={locale === "ar" ? "rtl" : "ltr"} aria-busy={busy}>
    <header><h1>{t("title")}</h1><p>{t("boundary")}</p><p>{t("coverage")}</p></header>
    {error && <p role="alert">{t(error)}</p>}{busy && <p role="status">{t("loading")}</p>}{saved && <p role="status">{t("saved")}</p>}
    {!auth.session ? <form className="panel reporting-form" aria-label={t("login")} onSubmit={event => void authenticate(event)}>{(["tenant", "username", "password"] as const).map(key => <label key={key}>{t(key)}<input aria-label={t(key)} type={key === "password" ? "password" : "text"} autoComplete={key === "password" ? "current-password" : key === "username" ? "username" : "off"} required disabled={busy} value={login[key]} onChange={event => setLogin(old => ({ ...old, [key]: event.target.value }))} /></label>)}<button disabled={busy}>{t("login")}</button></form> : <>
      <section className="panel"><bdi>{auth.username}</bdi><button disabled={busy} onClick={() => void run(async (_signal, captured) => { try { await endBrowserAdminSession(auth.session!); } finally { if (current(captured)) auth.clear(revision); } })}>{t("logout")}</button></section>
      <form className="panel reporting-form" aria-label={t("apply")} onSubmit={apply}>{([["workspace", "workspace_id"], ["organization", "organization_id"]] as const).map(([label, key]) => <label key={key}>{t(label)}<input aria-label={t(label)} required disabled={!identity} value={input[key]} onChange={event => { invalidate(true); setScope(null); setCatalog([]); setInput(old => ({ ...old, [key]: event.target.value })); }} /></label>)}<button disabled={!identity || !canRead || busy}>{t("apply")}</button></form>
      {scope && canRead && <section className="panel"><label>{t("source")}<select aria-label={t("source")} value={candidate} onChange={event => { invalidate(); setCandidate(event.target.value); setConfirmed(false); }}><option value="">—</option>{catalog.map(row => <option key={row.id} value={row.id} disabled={originals.some(item => item.detail.id === row.id)}>{row.reference} · {row.id}</option>)}</select></label><label className="group-opening"><input type="checkbox" aria-label={t("opening")} checked={confirmed} disabled={!candidate || busy} onChange={event => { setConfirmed(event.target.checked); setView(null); setSaved(false); }} />{t("opening")}</label><button disabled={busy || !candidate || !confirmed || originals.length >= 16} onClick={() => void add()}>{t("add")}</button>{cursor && <button disabled={busy} onClick={() => { invalidate(); setCandidate(""); setConfirmed(false); void list(scope, cursor); }}>{t("more")}</button>}</section>}
      <section className="panel"><h2>{t("selected")} · <bdi>{originals.length}/16</bdi></h2>{originals.length ? <><ul className="group-originals">{originals.map(row => <li key={row.detail.id}><bdi>{row.detail.request.reference}</bdi><code>{row.detail.id} · {row.detail.source_digest}<br />{row.pin.elimination_plan_id} · {row.pin.elimination_plan_digest}<br />{row.pin.report_digest}</code><button disabled={busy} onClick={() => { invalidate(); setOriginals(old => old.filter(item => item.detail.id !== row.detail.id)); }}>{t("remove")}</button></li>)}</ul><button disabled={busy} onClick={() => void refresh()}>{t("refresh")}</button><button disabled={busy} onClick={() => void verify()}>{t("verify")}</button></> : <p>{t("empty")}</p>}</section>
      {view && <>
        <section className="panel"><h2>{t("bridge")}</h2><p>{t("policy")}: <bdi>{view.diagnostic.reporting_policy.currency_code} · {view.diagnostic.reporting_policy.currency_rounding_policy} · {view.diagnostic.reporting_policy.currency_registry_version}</bdi></p><div className="reporting-table" role="region" aria-label={t("bridge")} tabIndex={0}><table><caption>{t("bridge")}</caption><thead><tr>{(["role", "account", "translated", "native", "combined"] as const).map(key => <th key={key}>{t(key)}</th>)}</tr></thead><tbody>{view.diagnostic.trial_balance_bridge.map(row => <tr key={row.role}><th scope="row"><bdi>{row.role}</bdi></th><td><bdi>{row.account_code}</bdi></td><td><bdi>{money(row.translated_minor)}</bdi></td><td><bdi>{money(row.native_adjustment_minor)}</bdi></td><td><bdi>{money(row.combined_minor)}</bdi></td></tr>)}</tbody></table></div></section>
        <section className="panel"><h2>{t("cash")}</h2><dl className="group-totals">{([["operating", view.diagnostic.cash_equation.operating_net_minor], ["exchange", view.diagnostic.cash_equation.fx_on_cash_minor], ["closing", view.diagnostic.cash_equation.closing_minor], ["result", view.diagnostic.income_statement.result_minor], ["equity", view.diagnostic.balance_sheet.equity_minor]] as const).map(([label, amount]) => <div key={label}><dt>{t(label)}</dt><dd><bdi>{money(amount)}</bdi></dd></div>)}</dl></section>
        <section className="panel"><h2>{t("periods")}</h2><p>{t("observed")}</p><div className="reporting-table" role="region" aria-label={t("periods")} tabIndex={0}><table><caption>{t("periods")}</caption><thead><tr>{(["period", "dates", "status", "reason"] as const).map(key => <th key={key}>{t(key)}</th>)}</tr></thead><tbody>{view.diagnostic.native_period_observations.map(row => <tr key={row.id}><th scope="row"><bdi>{row.name} · {row.id}</bdi></th><td><bdi>{row.start_date} — {row.end_date}</bdi></td><td>{t(row.status === "Open" ? "open" : row.status === "Soft Closed" ? "softClosed" : "closed")}</td><td>{row.status_reason}</td></tr>)}</tbody></table></div></section>
        <section className="panel"><h2>{t("drilldown")}</h2>{view.diagnostic.source_members.map(row => <details key={row.source_id}><summary><bdi>{row.source_id}</bdi></summary><code>{row.source_digest}<br />{row.elimination_plan_id} · {row.elimination_plan_digest}<br />{row.report_digest}<br />{row.source_evidence_digest}</code><ul>{[...row.source_effect_ids, ...row.native_adjustment_effect_ids].map(id => <li key={id}><code>{id}</code></li>)}</ul></details>)}</section>
        <section className="panel"><h2>{t("raw")}</h2><code>{view.evidence_sha256}</code><p><bdi>{view.evidence_bytes}</bdi></p><p>{t("cli")}</p><button disabled={busy} onClick={() => void download()}>{t("download")}</button></section>
      </>}
    </>}
  </main>;
}
