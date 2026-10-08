import { useEffect, useRef, useState, type FormEvent } from "react";
import { useBrowserSession } from "../browserSession";
import { AdminApiError, beginBrowserAdminSession, endBrowserAdminSession, stepUpBrowserAdminSession } from "../data";
import { loadExceptionReviewIdentity, type ExceptionReviewIdentity } from "../exception-review-data";
import { procurementCommand, procurementDetail, procurementList, procurementOptions, procurementScopes, type ProcurementCycle, type ProcurementDetail, type ProcurementOption, type ProcurementOptions, type ProcurementScope } from "../procurement-data";
import { procurementTranslate, type ProcurementMessage } from "../procurement-i18n";
import { prepareScopedCommand, type PreparedScopedCommand } from "../scoped-command";
import type { Locale } from "../types";
import "./ProcurementWorkspace.css";

export function ProcurementWorkspace({ locale }: { locale: Locale }) {
  const auth = useBrowserSession();
  return <ProcurementSession key={auth.revision} locale={locale} />;
}

function ProcurementSession({ locale }: { locale: Locale }) {
  const auth = useBrowserSession(), t = (key: ProcurementMessage) => procurementTranslate(locale, key);
  const [tenant, setTenant] = useState(""), [username, setUsername] = useState(""), [password, setPassword] = useState("");
  const [identity, setIdentity] = useState<ExceptionReviewIdentity | null>(null), [workspace, setWorkspace] = useState("");
  const [scopes, setScopes] = useState<ProcurementScope[]>([]), [scope, setScope] = useState<ProcurementScope | null>(null);
  const [options, setOptions] = useState<ProcurementOptions | null>(null), [cycles, setCycles] = useState<ProcurementCycle[]>([]);
  const [detail, setDetail] = useState<ProcurementDetail | null>(null), [reason, setReason] = useState("");
  const [draft, setDraft] = useState<Record<string, string>>({ number: "", supplier_code: "", item_code: "", quantity: "", unit_price_minor: "", posting_date: "", period_id: "", location_code: "", policy_code: "", journal_code: "", ap_account_code: "", cash_account_code: "" });
  const [busy, setBusy] = useState(false), [error, setError] = useState<ProcurementMessage | null>(null), [pending, setPending] = useState<PreparedScopedCommand | null>(null), [refresh, setRefresh] = useState(0);
  const mounted = useRef(true), lock = useRef(false), errorRef = useRef<HTMLDivElement>(null), savedRef = useRef<HTMLParagraphElement>(null);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const current = () => mounted.current && auth.isCurrent(auth.revision);
  const fail = (caught: unknown) => {
    if (!current() || auth.recover(caught, auth.revision)) return;
    setError(caught instanceof AdminApiError && caught.status === 403 ? "denied" : caught instanceof AdminApiError && caught.status < 500 ? "conflict" : "unavailable");
    if (caught instanceof AdminApiError && caught.status === 403) { setDetail(null); setCycles([]); }
  };
  useEffect(() => { if (error) errorRef.current?.focus(); }, [error]);
  useEffect(() => {
    if (!auth.session) return;
    const controller = new AbortController();
    loadExceptionReviewIdentity(auth.session, controller.signal).then((value) => { if (!controller.signal.aborted && current()) { setIdentity(value); setWorkspace(value.workspaces[0] ?? ""); } }).catch((caught) => { if (!controller.signal.aborted) fail(caught); });
    return () => controller.abort();
  }, [auth.session, auth.revision]);
  useEffect(() => {
    if (!auth.session || !workspace) return;
    const controller = new AbortController(); setScopes([]); setScope(null); setOptions(null); setDetail(null); setCycles([]);
    procurementScopes(auth.session, workspace, controller.signal).then((value) => { if (!controller.signal.aborted && current()) setScopes(value); }).catch((caught) => { if (!controller.signal.aborted) fail(caught); });
    return () => controller.abort();
  }, [auth.session, workspace]);
  useEffect(() => {
    if (!auth.session || !scope) return;
    const controller = new AbortController(); setOptions(null); setCycles([]);
    Promise.all([procurementOptions(auth.session, scope, controller.signal), procurementList(auth.session, scope, controller.signal)]).then(([references, records]) => {
      if (!controller.signal.aborted && current()) { setOptions(references); setCycles(records); }
    }).catch((caught) => { if (!controller.signal.aborted) fail(caught); });
    return () => controller.abort();
  }, [auth.session, scope, refresh]);
  const locked = busy || pending !== null;
  async function login(event: FormEvent) {
    event.preventDefault(); if (lock.current) return; lock.current = true; setBusy(true); setError(null);
    try { const session = await beginBrowserAdminSession({ tenantId: tenant, username, password }); if (current()) auth.begin(session, username, auth.revision); }
    catch (caught) { fail(caught); } finally { lock.current = false; if (current()) { setBusy(false); setPassword(""); } }
  }
  async function stepUp(event: FormEvent) {
    event.preventDefault(); if (!auth.session || lock.current || pending) return; lock.current = true; setBusy(true); setError(null);
    try { const expiry = await stepUpBrowserAdminSession(auth.session, password); if (current()) auth.elevate(expiry, auth.revision); }
    catch (caught) { fail(caught); } finally { lock.current = false; if (current()) { setBusy(false); setPassword(""); } }
  }
  async function logout() {
    if (!auth.session || locked) return; setBusy(true);
    try { await endBrowserAdminSession(auth.session); if (current()) auth.clear(auth.revision); }
    catch (caught) { fail(caught); } finally { if (current()) setBusy(false); }
  }
  async function inspect(id: string) {
    if (!auth.session || !scope || locked) return; setBusy(true); setError(null); setDetail(null);
    try { const value = await procurementDetail(auth.session, scope, id); if (current()) setDetail(value); }
    catch (caught) { fail(caught); } finally { if (current()) setBusy(false); }
  }
  async function send(command: PreparedScopedCommand) {
    if (!auth.session || !scope || lock.current) return; lock.current = true; setBusy(true); setError(null); setPending(command);
    try { const value = await procurementCommand(auth.session, scope, command); if (current()) { setDetail(value); setPending(null); setReason(""); setRefresh((count) => count + 1); requestAnimationFrame(() => savedRef.current?.focus()); } }
    catch (caught) {
      if (!current()) return;
      if (!(caught instanceof AdminApiError) || caught.status >= 500) setError("unknown");
      else { setPending(null); setDetail(null); setRefresh((count) => count + 1); fail(caught); }
    } finally { lock.current = false; if (current()) setBusy(false); }
  }
  function create(event: FormEvent) {
    event.preventDefault(); if (!scope || locked) return;
    const supplier = options?.suppliers.find((item) => item.code === draft.supplier_code);
    if (!supplier?.currency_code) { setError("conflict"); return; }
    void send(prepareScopedCommand("/api/v1/procurement-operations/cycles", { ...draft, workspace: scope.workspace_id, organization_code: scope.organization_code, entity_code: scope.entity_code, currency_code: supplier.currency_code }));
  }
  function act(event: FormEvent) {
    event.preventDefault(); if (!detail || !scope || locked || !detail.cycle.next_action) return;
    void send(prepareScopedCommand(`/api/v1/procurement-operations/cycles/${encodeURIComponent(detail.cycle.id)}/commands/${detail.cycle.next_action}`, { expected_version: detail.cycle.row_version, reason }));
  }
  const input = (key: ProcurementMessage, value: string, change: (value: string) => void, type = "text") => <label>{t(key)}<input required type={type} maxLength={key === "reason" ? 500 : key === "number" ? 60 : 160} disabled={locked} value={value} onChange={(event) => change(event.target.value)} /></label>;
  const choose = (label: ProcurementMessage, field: string, values: ProcurementOption[]) => <label>{t(label)}<select required disabled={locked} value={draft[field]} onChange={(event) => setDraft({ ...draft, [field]: event.target.value })}><option value="">—</option>{values.map((option) => <option value={option.code} key={option.code}>{option.code} · {option.name ?? option.currency_code ?? ""}</option>)}</select></label>;
  const manageable = identity?.human && identity.permissions.includes("payables.manage") && Boolean(auth.stepUpExpiresAt);
  return <main id="main-content" className="procurement-workspace" dir={locale === "ar" ? "rtl" : "ltr"}>
    <header><h1>{t("title")}</h1><p>{t("intro")}</p></header>
    {error && <div role="alert" tabIndex={-1} ref={errorRef}>{t(error)}</div>}
    {pending && !busy && <aside role="status"><p>{t("unknown")}</p><button onClick={() => void send(pending)}>{t("retry")}</button><code>{String(pending.body.command_id)}</code></aside>}
    {!auth.session ? <form onSubmit={(event) => void login(event)} aria-label={t("signIn")}>{input("tenant", tenant, setTenant)}{input("username", username, setUsername)}{input("password", password, setPassword, "password")}<button disabled={busy}>{t("signIn")}</button></form> : <>
      <div className="procurement-toolbar"><bdi>{auth.username}</bdi><button type="button" disabled={locked} onClick={() => void logout()}>{t("signOut")}</button></div>
      {!auth.stepUpExpiresAt && <form onSubmit={(event) => void stepUp(event)} aria-label={t("stepUp")}>{input("password", password, setPassword, "password")}<button disabled={locked}>{t("stepUp")}</button></form>}
      <div className="procurement-scope"><label>{t("workspace")}<select disabled={locked} value={workspace} onChange={(event) => setWorkspace(event.target.value)}><option value="">—</option>{identity?.workspaces.map((value) => <option key={value}>{value}</option>)}</select></label>
        <label>{t("scope")}<select disabled={locked} value={scope?.legal_entity_id ?? ""} onChange={(event) => { setScope(scopes.find((row) => row.legal_entity_id === event.target.value) ?? null); setDetail(null); setError(null); }}><option value="">—</option>{scopes.map((row) => <option value={row.legal_entity_id} key={row.legal_entity_id}>{row.organization_name} · {row.entity_name} · {row.currency_code}</option>)}</select></label></div>
      {scope && <><section><div className="procurement-toolbar"><h2>{t("cycles")}</h2><button disabled={locked} onClick={() => { setDetail(null); setRefresh((value) => value + 1); }}>{t("refresh")}</button></div>
        <ul className="procurement-cycles">{cycles.map((cycle) => <li key={cycle.id}><strong>{cycle.number}</strong><span>{t(cycle.stage)} · {cycle.total_minor} {cycle.request.currency_code}</span><button disabled={locked} onClick={() => void inspect(cycle.id)}>{t("open")} {cycle.number}</button></li>)}</ul>{cycles.length === 0 && <p>{t("empty")}</p>}</section>
        {options && manageable && <form onSubmit={create} aria-label={t("newOrder")}><fieldset disabled={locked}><legend>{t("newOrder")}</legend>
          {!options.suppliers.length || !options.items.length || !options.policies.length || !options.periods.length ? <p>{t("noReferences")}</p> : null}
          {input("number", draft.number, (value) => setDraft({ ...draft, number: value }))}{choose("supplier", "supplier_code", options.suppliers)}{choose("item", "item_code", options.items)}{input("quantity", draft.quantity, (value) => setDraft({ ...draft, quantity: value }))}{input("unitPrice", draft.unit_price_minor, (value) => setDraft({ ...draft, unit_price_minor: value }))}{input("date", draft.posting_date, (value) => setDraft({ ...draft, posting_date: value }), "date")}
          <label>{t("period")}<select value={draft.period_id} required onChange={(event) => setDraft({ ...draft, period_id: event.target.value })}><option value="">—</option>{options.periods.map((period) => <option value={period.id} key={period.id}>{period.name} · {period.start_date} / {period.end_date}</option>)}</select></label>
          {choose("location", "location_code", options.locations)}{choose("policy", "policy_code", options.policies)}{choose("journal", "journal_code", options.journals)}{choose("ap", "ap_account_code", options.accounts.filter((item) => item.account_type === "Liability"))}{choose("cash", "cash_account_code", options.accounts.filter((item) => item.account_type === "Asset"))}<button>{t("create")}</button>
        </fieldset></form>}
        {detail && <section aria-label={t("evidence")}><h2>{detail.cycle.number}</h2><p role="status" tabIndex={-1} ref={savedRef}>{t("stage")}: {t(detail.cycle.stage)} · {detail.cycle.row_version}</p><p>{t("amount")}: <bdi>{detail.cycle.total_minor} {detail.cycle.request.currency_code}</bdi></p><p>{t("independent")}</p>
          {detail.cycle.next_action && <form onSubmit={act}>{input("reason", reason, setReason)}<button disabled={locked || !auth.stepUpExpiresAt || !reason.trim()}>{t(detail.cycle.next_action)}</button></form>}
          <dl>{["purchase_order_id", "receipt_plan_id", "goods_receipt_id", "invoice_id", "accrual_effect_id", "payment_effect_id", "payment_link_id"].map((key) => <div key={key}><dt>{key.replaceAll("_", " ")}</dt><dd><code dir="ltr">{String(detail.cycle[key as keyof ProcurementCycle] ?? "—")}</code></dd></div>)}</dl>
        </section>}
      </>}
    </>}
  </main>;
}
