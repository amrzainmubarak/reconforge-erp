import { useEffect, useRef, useState, type FormEvent } from "react";
import { loadBudgetIdentity, type BudgetIdentity } from "../budget-control-data";
import { useBrowserSession } from "../browserSession";
import { AdminApiError, beginBrowserAdminSession, endBrowserAdminSession, stepUpBrowserAdminSession } from "../data";
import type { FinanceScope } from "../enterprise-finance-data";
import { object, peopleRequest, peopleRoot } from "../people-project-payroll-data";
import { billingAmount, billingPermissions, billingRequest, billingRoot, parseBillingAcknowledgement, parseBillingEvidence, parseBillingPlan, parseBillingPrice, type BillingPlan } from "../project-time-billing-data";
import { billingWords } from "../project-time-billing-i18n";
import { prepareScopedCommand, type PreparedScopedCommand, type ScopedJsonValue } from "../scoped-command";
import type { Locale } from "../types";
import { ProjectTimeBillingForms, type BillingRow, type BillingWord } from "./ProjectTimeBillingForms";
import "./FinancialReportingPage.css";
import "./ProjectTimeBillingPage.css";

export function ProjectTimeBillingPage({ locale }: { locale: Locale }) { const session = useBrowserSession(); return <BillingSession key={session.revision} locale={locale} />; }
function BillingSession({ locale }: { locale: Locale }) {
  const auth = useBrowserSession(), generation = auth.revision, t = (key: BillingWord) => billingWords[key][locale === "ar" ? 1 : 0];
  const [identity, setIdentity] = useState<BudgetIdentity | null>(null), [login, setLogin] = useState({ tenant: "local", username: "", password: "" });
  const [scopeInput, setScopeInput] = useState<FinanceScope>({ workspace_id: "", organization_id: "", legal_entity_id: "" }), [scope, setScope] = useState<FinanceScope | null>(null);
  const [plans, setPlans] = useState<BillingRow[]>([]), [prices, setPrices] = useState<BillingRow[]>([]), [projects, setProjects] = useState<BillingRow[]>([]), [times, setTimes] = useState<BillingRow[]>([]), [after, setAfter] = useState("");
  const [refresh, setRefresh] = useState(0), [plan, setPlan] = useState<BillingPlan | null>(null), [selected, setSelected] = useState("");
  const [busy, setBusy] = useState(false), [pending, setPending] = useState<PreparedScopedCommand | null>(null), [error, setError] = useState<"invalid" | "denied" | "unknown" | "unavailable" | null>(null), [saved, setSaved] = useState("");
  const lock = useRef(false), epoch = useRef(0), current = (captured: number) => auth.isCurrent(generation) && captured === epoch.current;
  const has = (action: string) => Boolean(identity && billingPermissions[action]?.every(permission => identity.permissions.includes(permission)));
  const allowed = (action: string) => Boolean(scope && identity?.human && identity.stepUp && has(action) && has("evidence"));
  const locked = busy || pending !== null;
  function invalidate() { epoch.current++; setPlan(null); setSelected(""); setSaved(""); setError(null); }
  function fail(caught: unknown, captured: number) { if (!current(captured)) return; if (auth.recover(caught, generation)) return; setError(caught instanceof AdminApiError && [401, 403].includes(caught.status) ? "denied" : caught instanceof AdminApiError ? "unavailable" : "invalid"); }
  useEffect(() => { if (!auth.session) return; const abort = new AbortController(), captured = epoch.current;
    loadBudgetIdentity(auth.session, abort.signal).then(value => { if (current(captured) && !abort.signal.aborted) { setIdentity(value); setScopeInput({ workspace_id: value.workspaces[0] ?? "", organization_id: value.organizations[0] ?? "", legal_entity_id: value.entities[0] ?? "" }); } }).catch(caught => { if (!abort.signal.aborted) fail(caught, captured); });
    return () => abort.abort();
  }, [auth.revision]);
  const rows = (value: unknown): BillingRow[] => { if (!Array.isArray(value) || value.length > 100 || value.some(row => !object(row) || typeof row.id !== "string") || new Set(value.map(row => row.id)).size !== value.length) throw new Error("project_billing_source_invalid"); return value as BillingRow[]; };
  async function catalog(cursor = "") {
    if (!auth.session || !scope) return; const captured = epoch.current;
    try { const raw = await billingRequest(auth.session, scope, `${billingRoot}/catalog?limit=100&after=${encodeURIComponent(cursor)}`); if (!object(raw) || typeof raw.has_more !== "boolean" || raw.has_more && (typeof raw.after !== "string" || !raw.after || raw.after === cursor)) throw new Error("project_billing_source_invalid");
      const nextPlans = rows(raw.items), nextPrices = await Promise.all(rows(raw.prices).map(value => parseBillingPrice(value, scope)));
      if (!current(captured)) return; const allPlans = cursor ? [...plans, ...nextPlans] : nextPlans, allPrices = cursor ? [...prices, ...nextPrices] : nextPrices;
      if (allPlans.length > 5000 || allPrices.length > 5000 || new Set(allPlans.map(row => row.id)).size !== allPlans.length || new Set(allPrices.map(row => row.id)).size !== allPrices.length) throw new Error("project_billing_source_invalid");
      setPlans(allPlans); setPrices(allPrices); setAfter(raw.has_more ? raw.after as string : "");
    } catch (caught) { fail(caught, captured); }
  }
  useEffect(() => { if (!scope || !auth.session || !has("read")) return; void catalog(); const captured = epoch.current, abort = new AbortController();
    if (identity?.permissions.includes("people_project_payroll.read")) void Promise.all(["projects", "times"].map(async kind => { const raw = await peopleRequest(auth.session!, scope, `${peopleRoot}/catalog/${kind}?limit=100`, undefined, abort.signal); if (!object(raw)) throw new Error("project_billing_source_invalid"); return rows(raw.items); })).then(([projectRows, timeRows]) => { if (current(captured) && !abort.signal.aborted) { setProjects(projectRows); setTimes(timeRows); } }).catch(caught => { if (!abort.signal.aborted) fail(caught, captured); });
    return () => abort.abort();
  }, [scope, refresh, identity]);
  async function authenticate(event: FormEvent, elevated = false) { event.preventDefault(); if (lock.current) return; lock.current = true; setBusy(true); const captured = epoch.current;
    try { if (elevated && auth.session) { const expires = await stepUpBrowserAdminSession(auth.session, login.password); if (current(captured)) auth.elevate(expires, generation); }
      else { const session = await beginBrowserAdminSession({ tenantId: login.tenant, username: login.username, password: login.password }); if (current(captured)) auth.begin(session, login.username, generation); } }
    catch (caught) { fail(caught, captured); } finally { lock.current = false; if (current(captured)) { setBusy(false); setLogin(old => ({ ...old, password: "" })); } }
  }
  async function original(id: string): Promise<BillingPlan> { if (!auth.session || !scope) throw new Error("project_billing_source_invalid");
    const raw = await billingRequest(auth.session, scope, `${billingRoot}/plans/${id}`); if (!object(raw) || !object(raw.plan)) throw new Error("project_billing_source_invalid");
    let effects: unknown[] = []; if (raw.plan.phase === 2) { const parent = raw.plan.parent_id ?? id; const proof = await billingRequest(auth.session, scope, `${billingRoot}/invoices/${parent}/evidence`); if (!object(proof)) throw new Error("project_billing_source_invalid"); const verified = await parseBillingEvidence(proof.evidence, scope, auth.session.tenantId); effects = verified.native_effects as unknown[]; }
    const verified = await parseBillingPlan(raw.plan, scope, effects); if (verified.id !== id) throw new Error("project_billing_source_invalid"); return verified;
  }
  async function load(id: string) { if (!scope || !has("evidence") || lock.current || pending) return; lock.current = true; invalidate(); setSelected(id); setBusy(true); const captured = epoch.current;
    if (!id) { lock.current = false; setBusy(false); return; }
    try { const verified = await original(id); if (current(captured)) setPlan(verified); } catch (caught) { fail(caught, captured); } finally { lock.current = false; if (current(captured)) setBusy(false); }
  }
  async function send(command: PreparedScopedCommand) { if (!auth.session || !scope || lock.current) return; lock.current = true; setBusy(true); setPending(command); setSaved(""); setError(null); const captured = epoch.current;
    try { const raw = await billingRequest(auth.session, scope, command.path, command), ack = await parseBillingAcknowledgement(command, raw, scope, identity?.id ?? "");
      if (ack.kind === "plan") { const verified = await original(ack.value.id); if (verified.plan_digest !== ack.value.plan_digest || !({ 0: [0, 1, 2, 3], 1: [1, 2, 3], 2: [2], 3: [3] }[ack.value.phase]).includes(verified.phase)) throw new Error("project_billing_source_invalid"); if (!current(captured)) return; setPlan(verified); setSelected(verified.id); setSaved(verified.id); }
      else { if (!current(captured)) return; setSaved(ack.value.id); }
      setPending(null); setRefresh(value => value + 1);
    } catch (caught) { if (current(captured)) { if (!(caught instanceof AdminApiError) || caught.status >= 500) setError("unknown"); else { setPending(null); fail(caught, captured); } } }
    finally { lock.current = false; if (current(captured)) setBusy(false); }
  }
  function submit(path: string, body: Record<string, ScopedJsonValue>) { try { void send(prepareScopedCommand(billingRoot + path, body)); } catch { setError("invalid"); } }
  async function evidence() { if (!auth.session || !scope || !plan || plan.schema_version !== "project-invoice-v1" || lock.current || !has("evidence")) return; lock.current = true; setBusy(true); const captured = epoch.current, id = plan.id;
    try { const raw = await billingRequest(auth.session, scope, `${billingRoot}/invoices/${id}/evidence`); if (!object(raw)) throw new Error("project_billing_source_invalid"); const verified = await parseBillingEvidence(raw.evidence, scope, auth.session.tenantId); if (!current(captured) || !object(verified.invoice) || verified.invoice.id !== id) return;
      const url = URL.createObjectURL(new Blob([JSON.stringify(verified)], { type: "application/json" })), link = document.createElement("a"); link.href = url; link.download = `${id}-evidence.json`; link.click(); URL.revokeObjectURL(url);
    } catch (caught) { fail(caught, captured); } finally { lock.current = false; if (current(captured)) setBusy(false); }
  }
  const input = (key: BillingWord, value: string, change: (value: string) => void) => <label>{t(key)}<input required disabled={locked} maxLength={160} type={key === "password" ? "password" : "text"} value={value} onChange={event => change(event.target.value)} /></label>;
  return <main id="main-content" className="financial-reporting" dir={locale === "ar" ? "rtl" : "ltr"} aria-busy={busy}>
    <header><h1>{t("title")}</h1><p>{t("boundary")}</p><p>{t("duties")}</p></header>
    {error && <p role="alert">{t(error)}</p>}{busy && <p role="status">{t("loading")}</p>}{saved && <p role="status">{t("saved")} · <code>{saved}</code></p>}
    {pending && !busy && <aside role="status"><p>{t("unknown")}</p><code>{pending.body.command_id}</code><button onClick={() => void send(pending)}>{t("retry")}</button></aside>}
    {!auth.session ? <form className="panel reporting-form" aria-label={t("login")} onSubmit={event => void authenticate(event)}>{(["tenant", "username", "password"] as const).map(key => <div key={key}>{input(key, login[key], value => setLogin(old => ({ ...old, [key]: value })))}</div>)}<button disabled={locked}>{t("login")}</button></form> : <>
      <section className="panel"><bdi>{auth.username}</bdi><button disabled={busy} onClick={() => { if (auth.session) void endBrowserAdminSession(auth.session).finally(() => auth.clear(generation)); }}>{t("logout")}</button></section>
      {!identity?.stepUp && <form className="panel reporting-form" aria-label={t("stepUp")} onSubmit={event => void authenticate(event, true)}>{input("password", login.password, value => setLogin(old => ({ ...old, password: value })))}<button disabled={locked}>{t("stepUp")}</button></form>}
      <form className="panel reporting-form" aria-label={t("apply")} onSubmit={event => { event.preventDefault(); if (locked) return; invalidate(); setPlans([]); setPrices([]); setProjects([]); setTimes([]); setScope({ ...scopeInput }); }}>{(Object.keys(scopeInput) as (keyof FinanceScope)[]).map(key => <div key={key}>{input(key, scopeInput[key], value => { invalidate(); setScope(null); setScopeInput(old => ({ ...old, [key]: value })); })}</div>)}<button disabled={locked || !identity}>{t("apply")}</button></form>
      {scope && <>
        <section className="panel"><button disabled={locked} onClick={() => setRefresh(value => value + 1)}>{t("refresh")}</button>{has("evidence") && <label>{t("plan")}<select disabled={locked} value={selected} onChange={event => void load(event.target.value)}><option value="">—</option>{plans.map(row => <option key={row.id} value={row.id}>{row.id}</option>)}</select></label>}{after && <button disabled={locked} onClick={() => void catalog(after)}>{t("loadMore")}</button>}{!plans.length && !prices.length && <p role="status">{t("empty")}</p>}</section>
        <ProjectTimeBillingForms key={[scope.workspace_id, scope.organization_id, scope.legal_entity_id].join(":")} t={t} locked={locked} allowed={allowed} projects={projects} times={times} prices={prices} plan={plan} submit={submit} />
        {prices.filter(row => !row.approver_id).map(price => <section key={price.id} className="panel"><h2>{t("price")}</h2><code>{price.id} · {String(price.source_digest)}</code><button disabled={locked || !allowed("approve_price") || price.preparer_id === identity?.id} onClick={() => submit(`/prices/${price.id}/approve`, { expected_digest: String(price.source_digest) })}>{t("approvePrice")}</button></section>)}
        {plan && <section className="panel" aria-label={t("plan")}><h2>{t("plan")}</h2><code>{plan.id} · {plan.plan_digest}</code><p><bdi>{billingAmount(plan.amount_minor, plan.monetary_policy.currency_precision, locale)} {plan.monetary_policy.currency_code}</bdi> · {t((["prepared", "reviewed", "posted", "cancelled"] as const)[plan.phase])}</p>
          <details><summary>{t("evidence")}</summary><pre className="project-billing-proof" dir="ltr">{JSON.stringify(plan, null, 2)}</pre></details>
          {plan.phase === 0 && <button disabled={locked || !allowed("review") || plan.preparer_id === identity?.id} onClick={() => submit(`/plans/${plan.id}/review`, { expected_plan_digest: plan.plan_digest })}>{t("review")}</button>}
          {plan.phase === 1 && <button disabled={locked || !allowed("post") || [plan.preparer_id, plan.reviewer_id].includes(identity?.id ?? "")} onClick={() => submit(`/plans/${plan.id}/post`, { expected_plan_digest: plan.plan_digest })}>{t("post")}</button>}
          {plan.schema_version === "project-invoice-v1" && plan.phase < 2 && <button disabled={locked || !allowed("prepare")} onClick={() => submit(`/plans/${plan.id}/cancel`, { expected_plan_digest: plan.plan_digest })}>{t("cancel")}</button>}
          {plan.schema_version === "project-invoice-v1" && <button disabled={locked || !has("evidence")} onClick={() => void evidence()}>{t("evidence")}</button>}
        </section>}
      </>}
    </>}
  </main>;
}
