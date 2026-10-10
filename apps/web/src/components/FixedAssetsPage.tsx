import { useEffect, useRef, useState, type FormEvent } from "react";
import { useBrowserSession } from "../browserSession";
import { AdminApiError, beginBrowserAdminSession, endBrowserAdminSession, stepUpBrowserAdminSession } from "../data";
import { loadBudgetIdentity, type BudgetIdentity } from "../budget-control-data";
import { financeMoney, type FinanceScope } from "../enterprise-finance-data";
import { majorToMinor, parseCatalog, reportingRequest, type Catalog } from "../financial-reporting-data";
import { assetRequest, parseAssetDetail, parseAssetPlan, parseAssetSummary, type AssetDetail, type AssetPlan, type AssetSummary } from "../fixed-assets-data";
import { assetTranslate, type AssetMessage } from "../fixed-assets-i18n";
import { formatExactDecimal } from "../locale-format";
import { prepareScopedCommand, type PreparedScopedCommand } from "../scoped-command";
import type { Locale } from "../types";
import "./FinancialReportingPage.css";
import FixedAssetEvidencePanel from "./FixedAssetEvidencePanel";

export default function FixedAssetsPage({ locale }: { locale: Locale }) {
  const auth = useBrowserSession();
  return <AssetSession key={auth.revision} locale={locale} />;
}

function AssetSession({ locale }: { locale: Locale }) {
  const auth = useBrowserSession(), t = (key: AssetMessage) => assetTranslate(locale, key);
  const [identity, setIdentity] = useState<BudgetIdentity | null>(null), [login, setLogin] = useState({ tenant: "local", username: "", password: "" });
  const [scopeInput, setScopeInput] = useState<FinanceScope>({ workspace_id: "", organization_id: "", legal_entity_id: "" }), [scope, setScope] = useState<FinanceScope | null>(null);
  const [catalog, setCatalog] = useState<Catalog | null>(null), [assets, setAssets] = useState<AssetSummary[]>([]), [next, setNext] = useState<string | null>(null);
  const [selected, setSelected] = useState(""), [detail, setDetail] = useState<AssetDetail | null>(null), [plan, setPlan] = useState<AssetPlan | null>(null);
  const [busy, setBusy] = useState(false), [pending, setPending] = useState<PreparedScopedCommand | null>(null), [error, setError] = useState<AssetMessage | null>(null), [refresh, setRefresh] = useState(0);
  const [definition, setDefinition] = useState({ asset_number: "", name: "", journal_code: "", period_id: "", posting_date: "", in_service_date: "", cost: "", salvage: "0", useful_life_months: "36", asset_account_code: "", accumulated_account_code: "", expense_account_code: "", cash_account_code: "", gain_account_code: "", loss_account_code: "", reason: "" });
  const [operation, setOperation] = useState({ period_id: "", posting_date: "", through_month: "", proceeds: "0", reason: "" }), [reason, setReason] = useState("");
  const mounted = useRef(true), commandLock = useRef(false), alert = useRef<HTMLParagraphElement>(null);
  const current = () => mounted.current && auth.isCurrent(auth.revision), locked = busy || Boolean(pending);
  const can = (permission: string) => Boolean(identity?.human && identity.permissions.includes(permission));
  const mutation = Boolean(scope && identity?.stepUp);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => { if (error) alert.current?.focus(); }, [error]);
  function clear() { setCatalog(null); setAssets([]); setDetail(null); setPlan(null); setSelected(""); setNext(null); }
  function fail(caught: unknown) { if (!current() || auth.recover(caught, auth.revision)) return; setError(caught instanceof AdminApiError && [403, 404].includes(caught.status) ? "denied" : caught instanceof AdminApiError && caught.status === 409 ? "conflict" : "unavailable"); }
  useEffect(() => {
    if (!auth.session) return; const controller = new AbortController();
    loadBudgetIdentity(auth.session, controller.signal).then(value => { if (current() && !controller.signal.aborted) { setIdentity(value); setScopeInput({ workspace_id: value.workspaces[0] ?? "", organization_id: value.organizations[0] ?? "", legal_entity_id: value.entities[0] ?? "" }); } }).catch(caught => { if (!controller.signal.aborted) fail(caught); });
    return () => controller.abort();
  }, [auth.session, auth.revision]);
  useEffect(() => {
    if (!auth.session || !scope || !can("finance_core.read")) return; const controller = new AbortController();
    Promise.all([reportingRequest(auth.session, scope, "/api/v1/financial-reporting/catalog", undefined, controller.signal), assetRequest(auth.session, scope, "/api/v1/fixed-assets/assets", undefined, controller.signal)]).then(([raw, page]) => {
      if (!current() || controller.signal.aborted) return;
      setCatalog(parseCatalog(raw.catalog, scope));
      if (!Array.isArray(page.assets) || page.assets.length > 25 || (page.next_after !== null && typeof page.next_after !== "string")) throw new Error("asset_page_invalid");
      setAssets(page.assets.map(value => parseAssetSummary(value, scope))); setNext(page.next_after as string | null); setError(null);
    }).catch(caught => { if (!controller.signal.aborted) fail(caught); });
    return () => controller.abort();
  }, [scope, refresh, identity, auth.session]);
  useEffect(() => {
    if (!auth.session || !scope || !selected || !can("finance_core.read")) return; const controller = new AbortController();
    assetRequest(auth.session, scope, `/api/v1/fixed-assets/assets/${encodeURIComponent(selected)}`, undefined, controller.signal).then(raw => {
      if (!current() || controller.signal.aborted) return;
      const value = parseAssetDetail(raw.asset, scope); setDetail(value); setPlan(value.plans.find(row => row.status !== "Posted") ?? value.plans.at(-1) ?? null);
    }).catch(caught => { if (!controller.signal.aborted) { setDetail(null); setPlan(null); fail(caught); } });
    return () => controller.abort();
  }, [scope, selected, refresh, auth.session]);
  async function authenticate(event: FormEvent, stepUp = false) {
    event.preventDefault(); if (commandLock.current) return; commandLock.current = true; setBusy(true); setError(null);
    try {
      if (stepUp && auth.session) { await stepUpBrowserAdminSession(auth.session, login.password); const value = await loadBudgetIdentity(auth.session); if (current()) setIdentity(value); }
      else { const session = await beginBrowserAdminSession({ tenantId: login.tenant, username: login.username, password: login.password }); if (current()) auth.begin(session, login.username, auth.revision); }
    } catch (caught) { fail(caught); }
    finally { commandLock.current = false; if (current()) { setBusy(false); setLogin(old => ({ ...old, password: "" })); } }
  }
  function apply(event: FormEvent) {
    event.preventDefault(); if (locked || !identity) return;
    for (const [key, grants] of [["workspace_id", identity.workspaces], ["organization_id", identity.organizations], ["legal_entity_id", identity.entities]] as const) if (!scopeInput[key].trim() || (grants.length && !grants.includes(scopeInput[key]))) { setError("denied"); return; }
    clear(); setScope({ ...scopeInput }); setError(null);
  }
  async function send(command: PreparedScopedCommand) {
    if (!auth.session || !scope || commandLock.current) return; commandLock.current = true; setBusy(true); setPending(command); setError(null);
    try {
      const response = await assetRequest(auth.session, scope, command.path, command);
      if (!current()) return; const value = parseAssetPlan(response.plan, scope); setPlan(value); setSelected(value.asset_id); setPending(null); setRefresh(old => old + 1); setReason("");
    } catch (caught) {
      if (!current()) return;
      if (!(caught instanceof AdminApiError) || caught.status >= 500) setError("unknown");
      else { setPending(null); fail(caught); }
    } finally { commandLock.current = false; if (current()) setBusy(false); }
  }
  function acquire(event: FormEvent) {
    event.preventDefault(); if (!catalog || !mutation || locked) return;
    try {
      if (!/^[1-9]\d{0,3}$/.test(definition.useful_life_months) || Number(definition.useful_life_months) > 1200) throw new Error("invalid_life");
      const { cost, salvage, ...fields } = definition;
      void send(prepareScopedCommand("/api/v1/fixed-assets/assets", { ...fields, useful_life_months: Number(fields.useful_life_months), cost_minor: majorToMinor(cost, catalog.currency_precision), salvage_minor: majorToMinor(salvage, catalog.currency_precision) }));
    } catch { setError("invalid"); }
  }
  function prepare(kind: "depreciate" | "dispose") {
    if (!detail || !mutation || locked) return;
    try {
      const { proceeds, through_month, ...fields } = operation;
      void send(prepareScopedCommand(`/api/v1/fixed-assets/assets/${encodeURIComponent(detail.id)}/operations`, { ...fields, kind, through_month: kind === "depreciate" ? through_month : "", proceeds_minor: kind === "dispose" ? majorToMinor(proceeds, detail.currency_precision) : "0" }));
    } catch { setError("invalid"); }
  }
  async function pageAssets() {
    if (!auth.session || !scope || !next || locked) return; setBusy(true);
    try { const raw = await assetRequest(auth.session, scope, `/api/v1/fixed-assets/assets?after=${encodeURIComponent(next)}`); if (!current()) return; if (!Array.isArray(raw.assets) || raw.assets.length > 25 || (raw.next_after !== null && typeof raw.next_after !== "string")) throw new Error("invalid_page"); setAssets(raw.assets.map(row => parseAssetSummary(row, scope))); setNext(raw.next_after as string | null); }
    catch (caught) { fail(caught); } finally { if (current()) setBusy(false); }
  }
  async function earlierHistory() {
    if (!auth.session || !scope || !detail?.history_before || locked) return; setBusy(true);
    try { const raw = await assetRequest(auth.session, scope, `/api/v1/fixed-assets/assets/${encodeURIComponent(detail.id)}?before_sequence=${detail.history_before}`); if (current()) setDetail(parseAssetDetail(raw.asset, scope)); }
    catch (caught) { fail(caught); } finally { if (current()) setBusy(false); }
  }
  const input = (key: AssetMessage, value: string, change: (value: string) => void, type = "text") => <label>{t(key)}<input required type={type} maxLength={key === "reason" ? 500 : 160} value={value} disabled={locked} onChange={event => change(event.target.value)} /></label>;
  const money = (value: string, policy: { currency_precision: number; currency_code: string } | null = detail ?? catalog) => policy ? `${formatExactDecimal(financeMoney(value, policy.currency_precision), locale)} ${policy.currency_code}` : "—";
  const period = (value: string, change: (value: string) => void) => <label>{t("period_id")}<select required disabled={locked} value={value} onChange={event => change(event.target.value)}><option value="">—</option>{catalog?.periods.filter(row => row.status === "Open").map(row => <option key={row.id} value={row.id}>{row.name} · {row.start_date} / {row.end_date}</option>)}</select></label>;
  return <main id="main-content" className="financial-reporting" dir={locale === "ar" ? "rtl" : "ltr"}>
    <header><h1>{t("title")}</h1><p>{t("intro")}</p><p>{t("permission")}</p></header>
    {error && <p role="alert" ref={alert} tabIndex={-1}>{t(error)}</p>}
    {pending && !busy && <aside role="status"><p>{t("unknown")}</p><button onClick={() => void send(pending)}>{t("retry")}</button><code dir="ltr">{pending.body.command_id}</code></aside>}
    {!auth.session ? <form className="panel reporting-form" aria-label={t("signIn")} onSubmit={event => void authenticate(event)}>{input("tenant", login.tenant, value => setLogin({ ...login, tenant: value }))}{input("username", login.username, value => setLogin({ ...login, username: value }))}{input("password", login.password, value => setLogin({ ...login, password: value }), "password")}<button disabled={locked}>{t("signIn")}</button></form> : <>
      <section className="panel"><bdi>{auth.username}</bdi><button disabled={locked} onClick={() => { if (!auth.session) return; setBusy(true); void endBrowserAdminSession(auth.session).then(() => { if (current()) auth.clear(auth.revision); }).catch(fail).finally(() => { if (current()) setBusy(false); }); }}>{t("signOut")}</button></section>
      {!identity?.stepUp && identity?.human && <form className="panel reporting-form" aria-label={t("stepUp")} onSubmit={event => void authenticate(event, true)}>{input("password", login.password, value => setLogin({ ...login, password: value }), "password")}<button disabled={locked}>{t("stepUp")}</button></form>}
      <form className="panel reporting-form" onSubmit={apply} aria-label={t("apply")}>{([["workspace", "workspace_id"], ["organization", "organization_id"], ["entity", "legal_entity_id"]] as const).map(([label, field]) => <label key={field}>{t(label)}<input required maxLength={160} disabled={locked || !identity} value={scopeInput[field]} onChange={event => { setScopeInput({ ...scopeInput, [field]: event.target.value }); setScope(null); clear(); }} /></label>)}<button disabled={locked || !identity}>{t("apply")}</button></form>
      {scope && catalog && <>
        <section className="panel"><h2>{t("assets")}</h2><button disabled={locked} onClick={() => setRefresh(old => old + 1)}>{t("refresh")}</button><label>{t("assets")}<select disabled={locked} value={selected} onChange={event => { setSelected(event.target.value); setDetail(null); setPlan(null); }}><option value="">—</option>{assets.map(row => <option key={row.id} value={row.id}>{row.asset_number} · {row.name}</option>)}</select></label>{!assets.length && <p>{t("empty")}</p>}{next && <button disabled={locked} onClick={() => void pageAssets()}>{t("next")}</button>}</section>
        {can("finance_core.manage") && <form className="panel" aria-label={t("acquire")} onSubmit={acquire}><h2>{t("acquire")}</h2><div className="reporting-form">{(["asset_number", "name", "cost", "salvage", "useful_life_months", "reason"] as const).map(key => <div key={key}>{input(key, definition[key], value => setDefinition({ ...definition, [key]: value }))}</div>)}{(["posting_date", "in_service_date"] as const).map(key => <div key={key}>{input(key, definition[key], value => setDefinition({ ...definition, [key]: value }), "date")}</div>)}{period(definition.period_id, value => setDefinition({ ...definition, period_id: value }))}<label>{t("journal_code")}<select required disabled={locked} value={definition.journal_code} onChange={event => setDefinition({ ...definition, journal_code: event.target.value })}><option value="">—</option>{catalog.journals.filter(row => row.currency_code === catalog.currency_code).map(row => <option key={row.journal_code}>{row.journal_code}</option>)}</select></label>{(["asset_account_code", "accumulated_account_code", "expense_account_code", "cash_account_code", "gain_account_code", "loss_account_code"] as const).map(key => <label key={key}>{t(key)}<select required disabled={locked} value={definition[key]} onChange={event => setDefinition({ ...definition, [key]: event.target.value })}><option value="">—</option>{catalog.accounts.filter(row => row.account_type === (key === "gain_account_code" ? "Income" : ["expense_account_code", "loss_account_code"].includes(key) ? "Expense" : "Asset")).map(row => <option key={row.account_id} value={row.account_code}>{row.account_code} · {row.account_name}</option>)}</select></label>)}</div><button disabled={locked || !mutation}>{t("acquire")}</button></form>}
        {detail && <section className="panel"><h2><bdi>{detail.asset_number} · {detail.name}</bdi></h2><p>{t(detail.status)}</p><p>{t("cost")}: <bdi>{money(detail.cost_minor)}</bdi></p><p>{t("accumulated")}: <bdi>{money(detail.accumulated_minor)}</bdi></p><p>{t("carrying")}: <bdi>{money(detail.carrying_minor)}</bdi></p><p>{t("months")}: {detail.months} / {detail.useful_life_months}</p>
          <h3>{t("history")}</h3><div className="reporting-table" role="region" tabIndex={0} aria-label={t("history")}><table><caption>{t("history")}</caption><thead><tr><th>{t("posting_date")}</th><th>{t("lifecycle")}</th><th>{t("accumulated")}</th><th>{t("effect")}</th></tr></thead><tbody>{detail.plans.map(row => <tr key={row.id}><td>{row.posting_date}</td><td><button disabled={locked} onClick={() => setPlan(row)}>{t(row.kind === "acquire" ? "acquire" : row.kind === "depreciate" ? "depreciate" : "dispose")} · {t(row.status)}</button></td><td><bdi>{money(row.amount_minor)}</bdi></td><td><code dir="ltr">{row.posting_effect_id ?? "—"}</code></td></tr>)}</tbody></table></div>{detail.history_before !== null && <button disabled={locked} onClick={() => void earlierHistory()}>{t("previousHistory")}</button>}
          {detail.status === "Active" && !detail.plans.some(row => row.status !== "Posted") && can("finance_core.manage") && <section aria-label={t("lifecycle")}><h3>{t("lifecycle")}</h3><div className="reporting-form">{period(operation.period_id, value => setOperation({ ...operation, period_id: value }))}{input("posting_date", operation.posting_date, value => setOperation({ ...operation, posting_date: value }), "date")}{input("through_month", operation.through_month, value => setOperation({ ...operation, through_month: value }), "month")}{input("proceeds", operation.proceeds, value => setOperation({ ...operation, proceeds: value }))}{input("reason", operation.reason, value => setOperation({ ...operation, reason: value }))}</div><button disabled={locked || !mutation || !operation.period_id || !operation.posting_date || !operation.reason || !operation.through_month} onClick={() => prepare("depreciate")}>{t("depreciation")}</button><button disabled={locked || !mutation || !operation.period_id || !operation.posting_date || !operation.reason} onClick={() => prepare("dispose")}>{t("dispose")}</button></section>}
        </section>}
        {plan && <section className="panel" aria-label={t("digest")}><h2>{t(plan.status)}</h2><p>{t("digest")}: <code dir="ltr">{plan.plan_digest}</code></p><p>{t("effect")}: <code dir="ltr">{plan.posting_effect_id ?? "—"}</code></p><div className="reporting-table" role="region" tabIndex={0} aria-label={t("account")}><table><caption>{t("account")}</caption><thead><tr><th>{t("account")}</th><th>{t("debit")}</th><th>{t("credit")}</th></tr></thead><tbody>{plan.snapshot.lines.map(row => <tr key={row.line_number}><td><code dir="ltr">{row.account_id}</code></td><td><bdi>{money(row.debit_minor, plan)}</bdi></td><td><bdi>{money(row.credit_minor, plan)}</bdi></td></tr>)}</tbody></table></div>{plan.status !== "Posted" && input("reason", reason, setReason)}{plan.status === "Prepared" && can("finance_core.validate") && <button disabled={locked || !mutation || !reason.trim() || plan.preparer_actor_id === identity?.id} onClick={() => void send(prepareScopedCommand(`/api/v1/fixed-assets/plans/${encodeURIComponent(plan.id)}/review`, { expected_plan_digest: plan.plan_digest, reason }))}>{t("review")}</button>}{plan.status === "Reviewed" && can("finance_core.post") && <button disabled={locked || !mutation || !reason.trim() || [plan.preparer_actor_id, plan.reviewer_actor_id].includes(identity?.id ?? "")} onClick={() => void send(prepareScopedCommand(`/api/v1/fixed-assets/plans/${encodeURIComponent(plan.id)}/post`, { expected_plan_digest: plan.plan_digest, reason }))}>{t("post")}</button>}{auth.session && scope && <FixedAssetEvidencePanel key={`${plan.id}:${plan.phase}`} locale={locale} session={auth.session} scope={scope} plan={plan} locked={locked} isCurrent={current} onError={fail} />}</section>}
      </>}
    </>}
  </main>;
}
