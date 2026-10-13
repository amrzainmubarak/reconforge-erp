import { useEffect, useRef, useState, type FormEvent } from "react";
import { adAmount, adObject, adPermissions, adRequest, adRoot, canonicalAd, parseAdAcknowledgement, parseAdCatalog, parseAdEvidence, type AdCatalog, type AdEvidence, type AdRecord } from "../accrual-deferral-data";
import { adWords, type AdWord } from "../accrual-deferral-i18n";
import { loadBudgetIdentity, type BudgetIdentity } from "../budget-control-data";
import { useBrowserSession } from "../browserSession";
import { AdminApiError, beginBrowserAdminSession, endBrowserAdminSession, stepUpBrowserAdminSession } from "../data";
import type { FinanceScope } from "../enterprise-finance-data";
import { prepareScopedCommand, type PreparedScopedCommand, type ScopedJsonValue } from "../scoped-command";
import type { Locale } from "../types";
import { AccrualDeferralForms } from "./AccrualDeferralForms";
import "./FinancialReportingPage.css";
import "./AccrualDeferralPage.css";

export function AccrualDeferralPage({ locale }: { locale: Locale }) { const auth = useBrowserSession(); return <ScheduleSession key={auth.revision} locale={locale} />; }
function ScheduleSession({ locale }: { locale: Locale }) {
  const auth = useBrowserSession(), revision = auth.revision, t = (key: AdWord) => adWords[key][locale === "ar" ? 1 : 0];
  const [identity, setIdentity] = useState<BudgetIdentity | null>(null), [login, setLogin] = useState({ tenant: "local", username: "", password: "" });
  const [scopeInput, setScopeInput] = useState<FinanceScope>({ workspace_id: "", organization_id: "", legal_entity_id: "" }), [scope, setScope] = useState<FinanceScope | null>(null);
  const [catalog, setCatalog] = useState<AdCatalog | null>(null), [sources, setSources] = useState<AdRecord[]>([]), [cursor, setCursor] = useState<string | null>(null);
  const [proof, setProof] = useState<AdEvidence | null>(null), [selectedSource, setSelectedSource] = useState(""), [selectedPlan, setSelectedPlan] = useState("");
  const [busy, setBusy] = useState(false), [pending, setPending] = useState<PreparedScopedCommand | null>(null), [error, setError] = useState<AdWord | null>(null), [saved, setSaved] = useState("");
  const lock = useRef(false), epoch = useRef(0), current = (captured: number) => auth.isCurrent(revision) && captured === epoch.current;
  const has = (action: string) => Boolean(identity && adPermissions[action]?.every(value => identity.permissions.includes(value)));
  const allowed = (action: string) => Boolean(scope && identity?.human && identity.stepUp && has("read") && has(action));
  const locked = busy || pending !== null, source = proof?.source ?? null, plan = source?.plans.find(row => row.id === selectedPlan) ?? null;
  function invalidate() { epoch.current++; setProof(null); setSelectedSource(""); setSelectedPlan(""); setCatalog(null); setSources([]); setCursor(null); setSaved(""); setError(null); }
  function fail(caught: unknown, captured: number) { if (!current(captured)) return; if (auth.recover(caught, revision)) return; setError(caught instanceof AdminApiError ? [401, 403].includes(caught.status) ? "denied" : "unavailable" : "invalid"); }
  useEffect(() => { if (!auth.session) return; const captured = epoch.current, abort = new AbortController();
    loadBudgetIdentity(auth.session, abort.signal).then(value => { if (current(captured) && !abort.signal.aborted) { setIdentity(value); setScopeInput({ workspace_id: value.workspaces[0] ?? "", organization_id: value.organizations[0] ?? "", legal_entity_id: value.entities[0] ?? "" }); } }).catch(caught => { if (!abort.signal.aborted) fail(caught, captured); });
    return () => abort.abort();
  }, [auth.revision]);
  async function original(id: string): Promise<AdEvidence> { if (!auth.session || !scope) throw new Error("accrual_deferral_source_invalid"); const value = await adRequest(auth.session, scope, `${adRoot}/sources/${id}/evidence`); const verified = await parseAdEvidence(value, scope, auth.session.tenantId); if (verified.source.id !== id) throw new Error("accrual_deferral_source_invalid"); return verified; }
  async function readCatalog(after: string | null = null) {
    if (!auth.session || !scope) throw new Error("accrual_deferral_source_invalid");
    const [native, listing] = await Promise.all([adRequest(auth.session, scope, `${adRoot}/catalog`), adRequest(auth.session, scope, `${adRoot}/sources${after ? `?after=${encodeURIComponent(after)}` : ""}`)]);
    const parsed = parseAdCatalog(native, scope);
    if (!adObject(listing) || !Array.isArray(listing.items) || listing.items.length > 50 || listing.items.some(row => !adObject(row) || !/^AD1S-[a-f0-9]{32}$/.test(String(row.id)) || Object.entries(scope).some(([key, expected]) => row[key] !== expected)) || listing.next_cursor !== null && (typeof listing.next_cursor !== "string" || !listing.next_cursor || listing.next_cursor === after)) throw new Error("accrual_deferral_source_invalid");
    const items = after ? [...sources, ...listing.items] : listing.items; if (items.length > 5000 || new Set(items.map(row => (row as AdRecord).id)).size !== items.length) throw new Error("accrual_deferral_source_invalid");
    return { catalog: parsed, sources: items as AdRecord[], cursor: listing.next_cursor as string | null };
  }
  async function refresh(after: string | null = null) { if (lock.current || pending || !scope || !has("read")) return; lock.current = true; setBusy(true); setError(null); const captured = epoch.current, id = selectedSource; setProof(null);
    try { const next = await readCatalog(after), originalProof = id ? await original(id) : null; if (!current(captured)) return; setCatalog(next.catalog); setSources(next.sources); setCursor(next.cursor); setProof(originalProof); }
    catch (caught) { fail(caught, captured); } finally { lock.current = false; if (current(captured)) setBusy(false); }
  }
  useEffect(() => { if (scope && auth.session && has("read")) void refresh(); }, [scope]);
  async function load(id: string) { if (lock.current || pending || !scope || !has("read")) return; lock.current = true; epoch.current++; const captured = epoch.current; setSelectedSource(id); setSelectedPlan(""); setProof(null); setSaved(""); setError(null); setBusy(true);
    try { if (!id) return; const verified = await original(id); if (current(captured)) { setProof(verified); setSelectedPlan(verified.source.plans.find(row => row.kind === "source")!.id); } }
    catch (caught) { fail(caught, captured); } finally { lock.current = false; if (current(captured)) setBusy(false); }
  }
  async function send(command: PreparedScopedCommand) { if (lock.current || !scope || !auth.session || !identity) return; lock.current = true; setBusy(true); setPending(command); setError(null); setSaved(""); const captured = epoch.current; setProof(null);
    try { const raw = await adRequest(auth.session, scope, command.path, command), ack = await parseAdAcknowledgement(command, raw, scope, identity.id);
      const verified = await original(ack.source_id), latest = verified.source.plans.find(row => row.id === ack.id);
      if (!latest || latest.plan_digest !== ack.plan_digest || latest.phase < ack.phase || canonicalAd(latest.command_request) !== canonicalAd(ack.command_request)) throw new Error("accrual_deferral_source_invalid");
      if (!current(captured)) return; setProof(verified); setSelectedSource(verified.source.id); setSelectedPlan(latest.id); setSaved(ack.id); setPending(null);
      setSources(old => old.some(row => row.id === verified.source.id) ? old : [...old, { id: verified.source.id, reference: verified.source.request.reference, ...scope }]);
    } catch (caught) { if (current(captured)) { if (!(caught instanceof AdminApiError) || caught.status >= 500) setError("unknown"); else { setPending(null); fail(caught, captured); } } }
    finally { lock.current = false; if (current(captured)) setBusy(false); }
  }
  function submit(path: string, body: Record<string, ScopedJsonValue>) { try { if (locked || !scope) return; void send(prepareScopedCommand(adRoot + path, body)); } catch { setError("invalid"); } }
  async function authenticate(event: FormEvent, elevated = false) { event.preventDefault(); if (lock.current || pending) return; lock.current = true; setBusy(true); const captured = epoch.current;
    try { if (elevated && auth.session) { const expires = await stepUpBrowserAdminSession(auth.session, login.password); if (current(captured)) auth.elevate(expires, revision); } else { const session = await beginBrowserAdminSession({ tenantId: login.tenant, username: login.username, password: login.password }); if (current(captured)) auth.begin(session, login.username, revision); } }
    catch (caught) { fail(caught, captured); } finally { lock.current = false; if (current(captured)) { setBusy(false); setLogin(old => ({ ...old, password: "" })); } }
  }
  async function download() { if (lock.current || pending || !source || !scope || !auth.session || !has("read")) return; lock.current = true; setBusy(true); const id = source.id, captured = epoch.current;
    try { const verified = await original(id); if (!current(captured)) return; const url = URL.createObjectURL(new Blob([JSON.stringify(verified)], { type: "application/json" })), anchor = document.createElement("a"); anchor.href = url; anchor.download = `${id}-evidence.json`; anchor.click(); URL.revokeObjectURL(url); setProof(verified); }
    catch (caught) { setProof(null); fail(caught, captured); } finally { lock.current = false; if (current(captured)) setBusy(false); }
  }
  const input = (key: AdWord, value: string, change: (value: string) => void, bootstrap = false) => <label>{t(key)}<input aria-label={t(key)} required disabled={locked || bootstrap && !identity} value={value} maxLength={160} type={key === "password" ? "password" : "text"} onChange={event => change(event.target.value)} /></label>;
  return <main id="main-content" className="financial-reporting" dir={locale === "ar" ? "rtl" : "ltr"} aria-busy={busy}>
    <header><h1>{t("title")}</h1><p>{t("boundary")}</p><p>{t("duties")}</p></header>
    {error && <p role="alert">{t(error)}</p>}{busy && <p role="status">{t("loading")}</p>}{saved && <p role="status">{t("saved")} · <code>{saved}</code></p>}
    {pending && !busy && <aside role="status"><p>{t("unknown")}</p><code>{pending.body.command_id}</code><button onClick={() => void send(pending)}>{t("retry")}</button></aside>}
    {!auth.session ? <form className="panel reporting-form" aria-label={t("login")} onSubmit={event => void authenticate(event)}>{(["tenant", "username", "password"] as const).map(key => <div key={key}>{input(key, login[key], value => setLogin(old => ({ ...old, [key]: value })))}</div>)}<button disabled={locked}>{t("login")}</button></form> : <>
      <section className="panel"><bdi>{auth.username}</bdi><button disabled={locked} onClick={() => { if (auth.session) void endBrowserAdminSession(auth.session).finally(() => auth.clear(revision)); }}>{t("logout")}</button></section>
      {!identity?.stepUp && <form className="panel reporting-form" aria-label={t("stepUp")} onSubmit={event => void authenticate(event, true)}>{input("password", login.password, value => setLogin(old => ({ ...old, password: value })))}<button disabled={locked}>{t("stepUp")}</button></form>}
      <form className="panel reporting-form" aria-label={t("apply")} onSubmit={event => { event.preventDefault(); if (locked || !identity) return; invalidate(); setScope({ ...scopeInput }); }}>{(Object.keys(scopeInput) as (keyof FinanceScope)[]).map(key => <div key={key}>{input(key, scopeInput[key], value => { invalidate(); setScope(null); setScopeInput(old => ({ ...old, [key]: value })); }, true)}</div>)}<button disabled={locked || !identity}>{t("apply")}</button></form>
      {scope && has("read") && <>
        <section className="panel"><button disabled={locked} onClick={() => void refresh()}>{t("refresh")}</button><label>{t("source")}<select aria-label={t("source")} disabled={locked} value={selectedSource} onChange={event => void load(event.target.value)}><option value="">—</option>{sources.map(row => <option key={String(row.id)} value={String(row.id)}>{String(row.reference)} · {String(row.id)}</option>)}</select></label>{cursor && <button disabled={locked} onClick={() => void refresh(cursor)}>{t("more")}</button>}{!sources.length && <p role="status">{t("empty")}</p>}</section>
        {catalog && <AccrualDeferralForms key={Object.values(scope).join(":")} t={t} locked={locked} allowed={allowed} catalog={catalog} source={source} plan={plan} submit={submit} />}
        {source && <section className="panel"><h2><bdi>{source.request.reference}</bdi></h2><code>{source.id} · {source.source_digest}</code><p><bdi>{adAmount(source.request.amount_minor, source.policy.currency_precision, locale)} {source.policy.currency_code}</bdi> · {source.policy.currency_rounding_policy}</p>{source.cancelled && <p role="status">{t("sourceCancelled")}</p>}
          <label>{t("plan")}<select aria-label={t("plan")} value={selectedPlan} disabled={locked} onChange={event => { setSelectedPlan(event.target.value); setSaved(""); }}>{source.plans.map(row => <option key={row.id} value={row.id}>{row.kind} · {row.tranche_id ? String(row.tranche_id) + " · " : ""}{row.id}</option>)}</select></label>
          {plan && <><p>{t((["prepared", "reviewed", "posted"] as const)[plan.phase])} · <code>{plan.plan_digest}</code></p>{plan.phase === 0 && <button disabled={locked || !allowed("review") || plan.preparer_actor_id === identity?.id || plan.kind === "reverse" && !has("reverse")} onClick={() => submit(`/plans/${plan.id}/review`, { expected_plan_digest: plan.plan_digest, reason: t("review") })}>{t("review")}</button>}{plan.phase === 1 && <button disabled={locked || !allowed("post") || [plan.preparer_actor_id, plan.reviewer_actor_id].includes(identity?.id ?? "") || plan.kind === "reverse" && !has("reverse")} onClick={() => submit(`/plans/${plan.id}/post`, { expected_plan_digest: plan.plan_digest, reason: t("post") })}>{t("post")}</button>}</>}
          <div className="ad-source-table"><table><caption>{t("allocation")}</caption><thead><tr><th>{t("tranche")}</th><th>{t("period_id")}</th><th>{t("amount_minor")}</th></tr></thead><tbody>{source.request.tranches.map(row => <tr key={row.id}><td><bdi>{row.id}</bdi></td><td><bdi>{row.period_id}</bdi></td><td><bdi>{adAmount(row.amount_minor, source.policy.currency_precision, locale)} {source.policy.currency_code}</bdi></td></tr>)}</tbody></table></div>
          <button disabled={locked} onClick={() => void download()}>{t("evidence")}</button><details><summary>{t("details")}</summary><pre className="ad-proof" dir="ltr">{JSON.stringify(proof, null, 2)}</pre></details>
        </section>}
      </>}
    </>}
  </main>;
}
