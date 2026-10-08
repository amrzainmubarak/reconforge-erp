import { useEffect, useRef, useState, type FormEvent } from "react";
import { useBrowserSession } from "../browserSession";
import { AdminApiError, beginBrowserAdminSession, endBrowserAdminSession, stepUpBrowserAdminSession } from "../data";
import { budgetInputMinor, budgetMoney, canonicalBudgetScope, executeBudgetCommand, loadBudgetDetail, loadBudgetIdentity, loadBudgetPage, prepareBudgetCommand, type BudgetDetail, type BudgetIdentity, type BudgetPage, type BudgetReceipt, type BudgetScope } from "../budget-control-data";
import { budgetTranslate, type BudgetMessage } from "../budget-control-i18n";
import type { PreparedScopedCommand } from "../scoped-command";
import type { Locale } from "../types";
import "./BudgetControlWorkspace.css";

export function BudgetControlWorkspace({ locale }: { locale: Locale }) {
  const { revision } = useBrowserSession();
  return <BudgetControlSession key={revision} locale={locale} />;
}

function BudgetControlSession({ locale }: { locale: Locale }) {
  const auth = useBrowserSession(), t = (key: BudgetMessage) => budgetTranslate(locale, key);
  const [tenant, setTenant] = useState("local"), [username, setUsername] = useState(""), [password, setPassword] = useState(""), [stepPassword, setStepPassword] = useState("");
  const [identity, setIdentity] = useState<BudgetIdentity | null>(null);
  const [scopeInput, setScopeInput] = useState<BudgetScope>({ workspace_id: "", organization_id: "", legal_entity_id: "" });
  const [scope, setScope] = useState<BudgetScope | null>(null), [offset, setOffset] = useState(0), [page, setPage] = useState<BudgetPage | null>(null);
  const [detail, setDetail] = useState<BudgetDetail | null>(null), [selectedId, setSelectedId] = useState(""), [refresh, setRefresh] = useState(0);
  const [error, setError] = useState<BudgetMessage | null>(null), [busy, setBusy] = useState(false), [loading, setLoading] = useState(false), [stale, setStale] = useState(false);
  const [pending, setPending] = useState<PreparedScopedCommand | null>(null), [receipt, setReceipt] = useState<BudgetReceipt | null>(null);
  const [draft, setDraft] = useState({ budget_code: "", name: "", period_id: "", currency_code: "", limit_minor: "" });
  const [reason, setReason] = useState(""), [operation, setOperation] = useState<"Reserve" | "Release" | "Consume">("Reserve"), [amount, setAmount] = useState(""), [date, setDate] = useState(""), [source, setSource] = useState(""), [commitmentId, setCommitmentId] = useState("");
  const mounted = useRef(true), lock = useRef(false), errorRef = useRef<HTMLDivElement>(null);
  const active = () => mounted.current && auth.isCurrent(auth.revision);
  const locked = busy || Boolean(pending);
  const readable = identity?.human && identity.permissions.includes("budget_control.read");
  const manageable = Boolean(readable && identity?.permissions.includes("budget_control.manage") && identity.stepUp && scope && !stale);
  const approvable = Boolean(readable && identity?.permissions.includes("budget_control.approve") && identity.stepUp && scope && !stale && detail && detail.created_by !== identity.id && detail.submitted_by !== identity.id);

  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => { if (error) errorRef.current?.focus(); }, [error]);

  function fail(caught: unknown): void {
    if (!active() || auth.recover(caught, auth.revision)) return;
    setError(caught instanceof Error && caught.message === "budget_contract_invalid" ? "contract" : caught instanceof AdminApiError && caught.status === 403 ? "denied" : "unavailable");
    setPage(null); setDetail(null); setReceipt(null); setStale(true);
  }
  async function identify(): Promise<void> {
    if (!auth.session) return;
    try {
      const value = await loadBudgetIdentity(auth.session);
      if (active()) { setIdentity(value); setScope(null); setPage(null); setDetail(null); setSelectedId(""); setReceipt(null); setScopeInput((old) => ({ workspace_id: old.workspace_id || value.workspaces[0] || "", organization_id: old.organization_id || value.organizations[0] || "", legal_entity_id: old.legal_entity_id || value.entities[0] || "" })); }
    } catch (caught) { fail(caught); }
  }
  useEffect(() => { void identify(); }, [auth.session]);
  useEffect(() => {
    if (!auth.session || !readable || !scope) return;
    const controller = new AbortController();
    setPage(null); setDetail(null); setLoading(true);
    Promise.all([loadBudgetPage(auth.session, scope, offset, controller.signal), selectedId ? loadBudgetDetail(auth.session, scope, selectedId, controller.signal) : Promise.resolve(null)]).then(([next, record]) => {
      if (controller.signal.aborted || !active()) return;
      setPage(next); setDetail(record); setStale(false); setError(null); setLoading(false);
    }).catch((caught) => { if (!controller.signal.aborted && active()) { fail(caught); setLoading(false); } });
    return () => controller.abort();
  }, [auth.session, readable, scope, selectedId, offset, refresh]);

  async function login(event: FormEvent) {
    event.preventDefault(); if (lock.current) return; lock.current = true; setBusy(true); setError(null);
    try { const session = await beginBrowserAdminSession({ tenantId: tenant, username, password }); if (active()) auth.begin(session, username, auth.revision); }
    catch (caught) { fail(caught); }
    finally { lock.current = false; if (active()) { setBusy(false); setPassword(""); } }
  }
  async function logout() {
    if (!auth.session || lock.current) return; lock.current = true; setBusy(true);
    try { await endBrowserAdminSession(auth.session); if (active()) auth.clear(auth.revision); }
    catch (caught) { fail(caught); }
    finally { lock.current = false; if (active()) setBusy(false); }
  }
  async function stepUp(event: FormEvent) {
    event.preventDefault(); if (!auth.session || lock.current) return; lock.current = true; setBusy(true); setError(null);
    try { await stepUpBrowserAdminSession(auth.session, stepPassword); if (active()) await identify(); }
    catch (caught) { fail(caught); }
    finally { lock.current = false; if (active()) { setBusy(false); setStepPassword(""); } }
  }
  function applyScope(event: FormEvent) {
    event.preventDefault(); if (lock.current || pending || !identity) return;
    try {
      const next = canonicalBudgetScope(scopeInput);
      if ([[next.workspace_id, identity.workspaces], [next.organization_id, identity.organizations], [next.legal_entity_id, identity.entities]].some(([id, grants]) => (grants as string[]).length > 0 && !(grants as string[]).includes(id as string))) { setError("denied"); return; }
      setScope(next); setSelectedId(""); setOffset(0); setReceipt(null); setError(null); setReason(""); setAmount(""); setCommitmentId(""); setSource("");
    } catch { setError("invalid"); }
  }
  function changeScope(field: keyof BudgetScope, value: string) {
    if (locked || lock.current) return;
    setScopeInput({ ...scopeInput, [field]: value }); setScope(null); setPage(null); setDetail(null); setSelectedId(""); setReceipt(null);
  }
  async function send(command: PreparedScopedCommand) {
    if (!auth.session || !scope || lock.current) return;
    lock.current = true; setBusy(true); setError(null); setReceipt(null); setPending(command);
    try {
      const result = await executeBudgetCommand(auth.session, scope, command);
      if (!active()) return;
      setReceipt(result); setPending(null); setSelectedId(result.id); setRefresh((count) => count + 1); setReason(""); setAmount("");
      if (result.commitment_id) setCommitmentId(result.commitment_id);
    } catch (caught) {
      if (!active()) return;
      // Any 5xx, lost response, or malformed 2xx may follow a committed transaction.
      // Recovery resends this frozen command; it cannot allocate a second effect.
      if (!(caught instanceof AdminApiError) || caught.status >= 500) { setError("unknown"); setStale(true); }
      else {
        setPending(null); setStale(true); setError(caught.status === 403 ? "denied" : "conflict");
        if (caught.status === 401 || caught.code === "csrf_required") auth.recover(caught, auth.revision);
        if (caught.status === 403) { setDetail(null); setPage(null); }
      }
    } finally { lock.current = false; if (active()) setBusy(false); }
  }
  function create(event: FormEvent) {
    event.preventDefault(); if (!scope || !manageable || locked) return;
    try { void send(prepareBudgetCommand(scope, "create", draft)); } catch { setError("invalid"); }
  }
  function review(action: "submit" | "approve") {
    if (!scope || !detail || locked || (action === "approve" ? !approvable : !manageable)) return;
    try { void send(prepareBudgetCommand(scope, action, { expected_version: detail.row_version, reason }, detail.id)); } catch { setError("invalid"); }
  }
  function record(event: FormEvent) {
    event.preventDefault(); if (!scope || !detail || !manageable || locked) return;
    try { void send(prepareBudgetCommand(scope, operation, { expected_version: detail.row_version, reason, amount_minor: budgetInputMinor(amount, detail.monetary_policy.precision), operation_date: date, source_reference: source }, detail.id, commitmentId)); } catch { setError("invalid"); }
  }
  const input = (label: BudgetMessage, value: string, change: (value: string) => void, maximum = 160, type = "text") => <label>{t(label)}<input required type={type} value={value} maxLength={maximum} disabled={locked} onChange={(event) => change(event.target.value)} /></label>;
  const money = (value: string) => detail ? budgetMoney(value, detail.monetary_policy, detail.currency_code, locale) : "";

  return <main className="budget-control-workspace" dir={locale === "ar" ? "rtl" : "ltr"}>
    <header><h1>{t("title")}</h1><p>{t("intro")}</p></header>
    {error && <div role="alert" tabIndex={-1} ref={errorRef}>{t(error)}</div>}
    {pending && !busy && <aside role="status"><p>{t("unknown")}</p><button type="button" onClick={() => void send(pending)}>{t("retry")}</button><code dir="ltr">{String(pending.body.command_id)}</code></aside>}
    {!auth.session ? <form onSubmit={(event) => void login(event)} aria-label={t("signIn")}>
      {input("tenant", tenant, setTenant)}{input("username", username, setUsername)}{input("password", password, setPassword, 200, "password")}<button disabled={busy}>{t("signIn")}</button>
    </form> : <>
      <div className="budget-control-toolbar"><span>{auth.username}</span><button type="button" disabled={busy} onClick={() => void logout()}>{t("signOut")}</button><button type="button" disabled={locked} onClick={() => void identify()}>{t("reloadIdentity")}</button></div>
      {identity && !readable && <p role="status">{t("access")}</p>}
      {readable && <>
        {!identity?.stepUp && <form onSubmit={(event) => void stepUp(event)}><p>{t("required")}</p>{input("stepPassword", stepPassword, setStepPassword, 200, "password")}<button disabled={locked}>{t("stepUp")}</button></form>}
        <form onSubmit={applyScope} aria-label={t("scope")}><fieldset disabled={locked}><legend>{t("scope")}</legend><p>{t("missing")}</p>
          {input("workspace", scopeInput.workspace_id, (value) => changeScope("workspace_id", value))}
          {input("organization", scopeInput.organization_id, (value) => changeScope("organization_id", value))}
          {input("entity", scopeInput.legal_entity_id, (value) => changeScope("legal_entity_id", value))}<button>{t("load")}</button>
        </fieldset></form>
        {scope && <>
          <div className="budget-control-toolbar"><h2>{t("envelopes")}</h2><button type="button" disabled={locked || loading} onClick={() => setRefresh((count) => count + 1)}>{t("refresh")}</button></div>
          {loading && <p role="status">{t("loading")}</p>}
          {page && <><ul className="budget-control-list">{page.envelopes.map((row) => <li key={row.id}><strong>{row.budget_code} · {row.name}</strong><span>{t(row.status)} · {budgetMoney(row.available_minor, row.monetary_policy, row.currency_code, locale)}</span><button type="button" disabled={locked} onClick={() => { setSelectedId(row.id); setReceipt(null); setReason(""); setCommitmentId(""); setSource(""); setAmount(""); }}>{t("open")} {row.budget_code}</button></li>)}</ul>
            {page.envelopes.length === 0 && <p>{t("empty")}</p>}<nav aria-label={t("envelopes")}><button type="button" disabled={locked || offset === 0} onClick={() => { setOffset(offset - 25); setSelectedId(""); }}>{t("previous")}</button><button type="button" disabled={locked || !page.pagination.has_more} onClick={() => { setOffset(offset + 25); setSelectedId(""); }}>{t("next")}</button></nav></>}
          {identity?.permissions.includes("budget_control.manage") && <form onSubmit={create} aria-label={t("draft")}><fieldset disabled={locked || !manageable}><legend>{t("draft")}</legend>
            {input("code", draft.budget_code, (value) => setDraft({ ...draft, budget_code: value }), 64)}{input("name", draft.name, (value) => setDraft({ ...draft, name: value }), 200)}{input("period", draft.period_id, (value) => setDraft({ ...draft, period_id: value }))}{input("currency", draft.currency_code, (value) => setDraft({ ...draft, currency_code: value }), 3)}
            {input("limit", draft.limit_minor, (value) => setDraft({ ...draft, limit_minor: value }), 19)}<p>{t("minorHint")}</p><button>{t("create")}</button>
          </fieldset></form>}
          {detail && <section aria-label={t("details")}><h2>{t("details")} · {detail.budget_code}</h2><code dir="ltr">{detail.id}</code><dl className="budget-control-balances">
            <dt>{t("status")}</dt><dd>{t(detail.status)}</dd><dt>{t("version")}</dt><dd>{detail.row_version}</dd>
            {([ ["total", detail.limit_minor], ["available", detail.available_minor], ["reserved", detail.reserved_minor], ["consumed", detail.consumed_minor] ] as const).map(([key, value]) => <div key={key}><dt>{t(key)}</dt><dd>{money(value)}</dd></div>)}
          </dl><details><summary>{t("policy")}</summary><p>{t("precision")}: {detail.monetary_policy.precision} · {detail.monetary_policy.rounding_policy} · <bdi>{detail.monetary_policy.registry_version}</bdi></p><code dir="ltr">{detail.monetary_policy.registry_digest}</code></details>
            {input("reason", reason, setReason, 500)}
            {detail.status === "Draft" && <button type="button" disabled={locked || !manageable || !reason.trim()} onClick={() => review("submit")}>{t("submit")}</button>}
            {detail.status === "Submitted" && <><p>{t("independent")}</p><button type="button" disabled={locked || !approvable || !reason.trim()} onClick={() => review("approve")}>{t("approve")}</button></>}
            {detail.status === "Approved" && identity?.permissions.includes("budget_control.manage") && <form onSubmit={record} aria-label={t("commitment")}><fieldset disabled={locked || !manageable}><legend>{t("commitment")}</legend>
              <label>{t("operation")}<select value={operation} onChange={(event) => setOperation(event.target.value as typeof operation)}>{(["Reserve", "Release", "Consume"] as const).map((value) => <option value={value} key={value}>{t(value)}</option>)}</select></label>
              {input("amount", amount, setAmount, 32)}{input("date", date, setDate, 10, "date")}{input("source", source, setSource)}{operation !== "Reserve" && input("commitmentId", commitmentId, setCommitmentId, 200)}<button disabled={!reason.trim()}>{t("execute")}</button>
            </fieldset></form>}
            <h3>{t("history")}</h3>{detail.events_has_more && <p role="status">{t("truncated")}</p>}
            <ol className="budget-control-history">{detail.events.map((event) => <li key={event.id}><strong>{t(event.operation)} · {money(event.amount_minor)}</strong><p>{t("remaining")}: {money(event.remaining_minor)} · <bdi>{event.operation_date}</bdi> · {t("version")}: {event.budget_version}</p><dl><dt>{t("commitmentId")}</dt><dd><bdi>{event.commitment_id}</bdi></dd><dt>{t("source")}</dt><dd><bdi>{event.source_reference}</bdi></dd><dt>{t("reason")}</dt><dd>{event.reason}</dd><dt>{t("actor")}</dt><dd><bdi>{event.actor_id}</bdi></dd><dt>{t("event")}</dt><dd><code dir="ltr">{event.id}</code></dd><dt>{t("audit")}</dt><dd><code dir="ltr">{event.audit_event_id}</code></dd><dt>{t("outbox")}</dt><dd><code dir="ltr">{event.outbox_event_id}</code></dd><dt>{t("digest")}</dt><dd><code dir="ltr">{event.request_digest}</code></dd></dl></li>)}</ol>
          </section>}
          {receipt && <section aria-label={t("evidence")}><p role="status">{t("saved")}</p><dl><dt>{t("audit")}</dt><dd><code dir="ltr">{receipt.evidence.audit_event_id}</code></dd><dt>{t("outbox")}</dt><dd><code dir="ltr">{receipt.evidence.outbox_event_id}</code></dd><dt>{t("digest")}</dt><dd><code dir="ltr">{receipt.evidence.request_digest}</code></dd>{receipt.commitment_id && <><dt>{t("commitmentId")}</dt><dd><code dir="ltr">{receipt.commitment_id}</code></dd></>}</dl></section>}
        </>}
      </>}
    </>}
  </main>;
}
