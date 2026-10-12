import { useEffect, useRef, useState, type FormEvent } from "react";
import { useBrowserSession } from "../browserSession";
import { loadBudgetIdentity, type BudgetIdentity } from "../budget-control-data";
import { AdminApiError, beginBrowserAdminSession, endBrowserAdminSession, stepUpBrowserAdminSession } from "../data";
import type { FinanceScope } from "../enterprise-finance-data";
import { object, parsePeoplePlan, peopleRequest, peopleRoot, type PeoplePlan } from "../people-project-payroll-data";
import { peopleWords } from "../people-project-payroll-i18n";
import { prepareScopedCommand, type PreparedScopedCommand, type ScopedJsonValue } from "../scoped-command";
import type { Locale } from "../types";
import "./FinancialReportingPage.css";

type Row = Record<string, unknown> & { id: string };
type Word = keyof typeof peopleWords;
type Catalog = "employees" | "projects" | "times" | "payruns" | "payments";
const emptyCatalog: Record<Catalog, Row[]> = { employees: [], projects: [], times: [], payruns: [], payments: [] };
const phaseContracts: Record<string, string[]> = {
  personnel: ["people_project_payroll.personnel", "people_project_payroll.read_sensitive"],
  manage: ["people_project_payroll.manage"], approve_time: ["people_project_payroll.approve_time"],
  prepare: ["people_project_payroll.prepare", "people_project_payroll.read_sensitive", "finance_core.manage", "budget_control.read", "budget_control.manage"],
  review: ["people_project_payroll.review", "people_project_payroll.read_sensitive", "finance_core.validate", "budget_control.read"],
  post: ["people_project_payroll.post", "people_project_payroll.read_sensitive", "finance_core.post", "budget_control.read", "budget_control.manage"],
  pay: ["people_project_payroll.pay", "people_project_payroll.read_sensitive", "finance_core.manage", "budget_control.read"],
};
export function PeopleProjectPayrollPage({ locale }: { locale: Locale }) { const session = useBrowserSession(); return <PeopleSession key={session.revision} locale={locale} />; }
function PeopleSession({ locale }: { locale: Locale }) {
  const auth = useBrowserSession(), t = (key: Word) => peopleWords[key][locale === "ar" ? 1 : 0], generation = auth.revision;
  const [identity, setIdentity] = useState<BudgetIdentity | null>(null), [login, setLogin] = useState({ tenant: "local", username: "", password: "" });
  const [scopeInput, setScopeInput] = useState<FinanceScope>({ workspace_id: "", organization_id: "", legal_entity_id: "" }), [scope, setScope] = useState<FinanceScope | null>(null);
  const [catalog, setCatalog] = useState(emptyCatalog), [refresh, setRefresh] = useState(0), [employee, setEmployee] = useState(""), [time, setTime] = useState("");
  const [plan, setPlan] = useState<PeoplePlan | null>(null), [selectedPlan, setSelectedPlan] = useState(""), [selectedTimes, setSelectedTimes] = useState<string[]>([]);
  const [person, setPerson] = useState({ employee_code: "", display_name: "", linked_user_id: "" });
  const [agreement, setAgreement] = useState({ valid_from: "", valid_through: "", hourly_rate_minor: "", currency_code: "", reason: "" });
  const [project, setProject] = useState({ project_code: "", dimension_code: "", value_code: "" });
  const [timeFields, setTimeFields] = useState({ business_date: "", reason: "" }), [intervals, setIntervals] = useState([{ project_id: "", start_minute: "", end_minute: "" }]);
  const [accrual, setAccrual] = useState({ budget_id: "", expected_budget_version: "", period_id: "", posting_date: "", journal_code: "", expense_account_code: "", liability_account_code: "", cash_account_code: "" });
  const [payment, setPayment] = useState({ period_id: "", posting_date: "" }), [allocations, setAllocations] = useState([{ employee_id: "", amount: "" }]);
  const [evidence, setEvidence] = useState<unknown>(null), [pending, setPending] = useState<PreparedScopedCommand | null>(null), [busy, setBusy] = useState(false);
  const [error, setError] = useState<"invalid" | "denied" | "unavailable" | "unknown" | null>(null), [saved, setSaved] = useState("");
  const lock = useRef(false), epoch = useRef(0), current = (captured = epoch.current) => auth.isCurrent(generation) && captured === epoch.current;
  const locked = busy || pending !== null, has = (permission: string) => Boolean(identity?.permissions.includes("people_project_payroll." + permission));
  const allowed = (permission: string, privatePhase = false) => Boolean(scope && identity?.human && identity.stepUp &&
    phaseContracts[permission]?.every(value => identity.permissions.includes(value)) && (!privatePhase || has("read_sensitive")));
  const invalidate = () => { epoch.current++; setPlan(null); setSelectedPlan(""); setEvidence(null); setSaved(""); };
  function fail(caught: unknown) { if (current()) setError(caught instanceof AdminApiError && [401, 403].includes(caught.status) ? "denied" : caught instanceof AdminApiError ? "unavailable" : "invalid"); }
  useEffect(() => {
    if (!auth.session) return; const abort = new AbortController();
    loadBudgetIdentity(auth.session, abort.signal).then(value => { if (current() && !abort.signal.aborted) { setIdentity(value); setScopeInput({ workspace_id: value.workspaces[0] ?? "", organization_id: value.organizations[0] ?? "", legal_entity_id: value.entities[0] ?? "" }); } }).catch(fail);
    return () => abort.abort();
  }, [auth.session, auth.revision]);
  useEffect(() => {
    if (!auth.session || !scope || !has("read")) return; const abort = new AbortController(), captured = epoch.current;
    Promise.all((Object.keys(emptyCatalog) as Catalog[]).map(async kind => {
      const raw = await peopleRequest(auth.session!, scope, `${peopleRoot}/catalog/${kind}?limit=100`, undefined, abort.signal);
      if (!object(raw) || !Array.isArray(raw.items) || raw.items.length > 100 || raw.items.some(item => !object(item) || typeof item.id !== "string")) throw new Error("people_source_invalid");
      return [kind, raw.items] as const;
    })).then(rows => { if (current(captured) && !abort.signal.aborted) setCatalog(Object.fromEntries(rows) as Record<Catalog, Row[]>); }).catch(caught => { if (!abort.signal.aborted) fail(caught); });
    return () => abort.abort();
  }, [scope, refresh, auth.session]);
  async function authenticate(event: FormEvent, stepUp = false) {
    event.preventDefault(); if (locked) return; setBusy(true); setError(null);
    try { if (stepUp && auth.session) { const proof = await stepUpBrowserAdminSession(auth.session, login.password); if (current()) auth.elevate(proof, generation); }
      else { const value = await beginBrowserAdminSession({ tenantId: login.tenant, username: login.username, password: login.password }); if (current()) auth.begin(value, login.username, generation); } }
    catch (caught) { fail(caught); } finally { if (current()) { setLogin(old => ({ ...old, password: "" })); setBusy(false); } }
  }
  async function loadPlan(id: string) {
    if (!auth.session || !scope || !has("read_sensitive") || locked) return; invalidate(); setSelectedPlan(id); const captured = epoch.current; setBusy(true); setError(null);
    try { const raw = await peopleRequest(auth.session, scope, `${peopleRoot}/plans/${id}/private`); if (!object(raw)) throw new Error("people_source_invalid"); const proof = await parsePeoplePlan(raw.plan, scope);
      if (current(captured) && proof.id === id) setPlan(proof); }
    catch (caught) { fail(caught); } finally { if (current(captured)) setBusy(false); }
  }
  async function send(command: PreparedScopedCommand) {
    if (!auth.session || !scope || lock.current) return; lock.current = true; setPending(command); setBusy(true); setError(null); setSaved(""); const captured = epoch.current;
    try { const raw = await peopleRequest(auth.session, scope, command.path, command); if (!object(raw)) throw new Error("people_source_invalid");
      if (object(raw.plan)) { const id = raw.plan.id; if (typeof id !== "string") throw new Error("people_source_invalid");
        const full = await peopleRequest(auth.session, scope, `${peopleRoot}/plans/${id}/private`); if (!object(full)) throw new Error("people_source_invalid"); const proof = await parsePeoplePlan(full.plan, scope);
        if (!current(captured) || proof.id !== id) return; setPlan(proof); setSelectedPlan(id);
      } else { const row = raw.employee ?? raw.employment ?? raw.project ?? raw.time; if (!object(row) || typeof row.id !== "string") throw new Error("people_source_invalid"); if (!current(captured)) return; setSaved(row.id); }
      setPending(null); setRefresh(old => old + 1);
    } catch (caught) { if (current(captured)) { if (!(caught instanceof AdminApiError) || caught.status >= 500) setError("unknown"); else { setPending(null); fail(caught); } } }
    finally { lock.current = false; if (current(captured)) setBusy(false); }
  }
  function submit(path: string, body: Record<string, ScopedJsonValue>) { try { void send(prepareScopedCommand(peopleRoot + path, body)); } catch { setError("invalid"); } }
  const input = (key: Word, value: string, change: (value: string) => void, required = true) => <label>{t(key)}<input required={required} disabled={locked} value={value} type={key === "password" ? "password" : ["business_date", "valid_from", "valid_through", "posting_date"].includes(key) ? "date" : "text"} maxLength={key === "reason" ? 500 : 160} onChange={event => change(event.target.value)} /></label>;
  const select = (label: Word, value: string, change: (value: string) => void, rows: Row[]) => <label>{t(label)}<select required disabled={locked} value={value} onChange={event => change(event.target.value)}><option value="">—</option>{rows.map(row => <option key={row.id} value={row.id}>{String(row.employee_code ?? row.project_code ?? row.id)}</option>)}</select></label>;
  const approved = catalog.times.filter(row => row.approver_id), selectedTime = catalog.times.find(row => row.id === time);
  const independentReview = plan && identity?.id !== plan.preparer_id, independentPost = independentReview && identity?.id !== plan?.reviewer_id;
  return <main id="main-content" className="financial-reporting" dir={locale === "ar" ? "rtl" : "ltr"}>
    <header><h1>{t("title")}</h1><p>{t("boundary")}</p><p>{t("duties")}</p></header>
    {error && <p role="alert">{t(error)}</p>}{saved && <p role="status">{t("saved")} · <code>{saved}</code></p>}
    {pending && !busy && <aside role="status"><p>{t("unknown")}</p><code>{pending.body.command_id}</code><button onClick={() => void send(pending)}>{t("retry")}</button></aside>}
    {!auth.session ? <form className="panel reporting-form" aria-label={t("login")} onSubmit={event => void authenticate(event)}>{(["tenant", "username", "password"] as const).map(key => <div key={key}>{input(key, login[key], value => setLogin(old => ({ ...old, [key]: value })))}</div>)}<button disabled={locked}>{t("login")}</button></form> : <>
      <section className="panel"><bdi>{auth.username}</bdi><button disabled={locked} onClick={() => { if (auth.session) void endBrowserAdminSession(auth.session).finally(() => auth.clear(generation)); }}>{t("logout")}</button></section>
      {!identity?.stepUp && <form className="panel reporting-form" aria-label={t("stepUp")} onSubmit={event => void authenticate(event, true)}>{input("password", login.password, value => setLogin(old => ({ ...old, password: value })))}<button disabled={locked}>{t("stepUp")}</button></form>}
      <form className="panel reporting-form" aria-label={t("apply")} onSubmit={event => { event.preventDefault(); invalidate(); setCatalog(emptyCatalog); setSelectedTimes([]); setScope({ ...scopeInput }); }}>{(Object.keys(scopeInput) as (keyof FinanceScope)[]).map(key => <div key={key}>{input(key, scopeInput[key], value => { invalidate(); setScope(null); setScopeInput(old => ({ ...old, [key]: value })); })}</div>)}<button disabled={locked || !identity}>{t("apply")}</button></form>
      {scope && <>
        <section className="panel"><button disabled={locked} onClick={() => setRefresh(old => old + 1)}>{t("refresh")}</button>{select("employee", employee, setEmployee, catalog.employees)}{has("read_sensitive") && select("plan", selectedPlan, id => void loadPlan(id), [...catalog.payruns, ...catalog.payments])}</section>
        {has("personnel") && <form className="panel reporting-form" aria-label={t("register")} onSubmit={event => { event.preventDefault(); if (allowed("personnel", true)) submit("/employees", { ...person, linked_user_id: person.linked_user_id || null }); }}>{(Object.keys(person) as (keyof typeof person)[]).map(key => <div key={key}>{input(key, person[key], value => setPerson(old => ({ ...old, [key]: value })), key !== "linked_user_id")}</div>)}<button disabled={locked || !allowed("personnel", true)}>{t("register")}</button></form>}
        {employee && has("personnel") && <form className="panel reporting-form" aria-label={t("employment")} onSubmit={event => { event.preventDefault(); if (allowed("personnel", true)) submit(`/employees/${employee}/employment`, agreement); }}>{(Object.keys(agreement) as (keyof typeof agreement)[]).map(key => <div key={key}>{input(key, agreement[key], value => setAgreement(old => ({ ...old, [key]: value })))}</div>)}<button disabled={locked || !allowed("personnel", true)}>{t("employment")}</button></form>}
        {has("manage") && <form className="panel reporting-form" aria-label={t("registerProject")} onSubmit={event => { event.preventDefault(); if (allowed("manage")) submit("/projects", project); }}>{(Object.keys(project) as (keyof typeof project)[]).map(key => <div key={key}>{input(key, project[key], value => setProject(old => ({ ...old, [key]: value })))}</div>)}<button disabled={locked || !allowed("manage")}>{t("registerProject")}</button></form>}
        {employee && has("manage") && <form className="panel reporting-form" aria-label={t("submitTime")} onSubmit={event => { event.preventDefault(); if (!allowed("manage") || intervals.some(line => !/^\d{1,4}$/.test(line.start_minute) || !/^\d{1,4}$/.test(line.end_minute))) return; submit("/times", { ...timeFields, employee_id: employee, lines: intervals.map(line => ({ project_id: line.project_id, start_minute: Number(line.start_minute), end_minute: Number(line.end_minute) })) }); }}>{(Object.keys(timeFields) as (keyof typeof timeFields)[]).map(key => <div key={key}>{input(key, timeFields[key], value => setTimeFields(old => ({ ...old, [key]: value })))}</div>)}{intervals.map((line, index) => <fieldset key={index}><legend>{index + 1}</legend>{select("project", line.project_id, value => setIntervals(old => old.map((row, i) => i === index ? { ...row, project_id: value } : row)), catalog.projects)}{(["start_minute", "end_minute"] as const).map(key => <div key={key}>{input(key, line[key], value => setIntervals(old => old.map((row, i) => i === index ? { ...row, [key]: value } : row)))}</div>)}</fieldset>)}<button type="button" disabled={locked || intervals.length >= 128} onClick={() => setIntervals(old => [...old, { project_id: "", start_minute: "", end_minute: "" }])}>{t("add")}</button><button disabled={locked || !allowed("manage")}>{t("submitTime")}</button></form>}
        {has("approve_time") && <form className="panel reporting-form" aria-label={t("approveTime")} onSubmit={event => { event.preventDefault(); if (selectedTime && typeof selectedTime.source_digest === "string" && allowed("approve_time")) submit(`/times/${time}/approve`, { expected_digest: selectedTime.source_digest }); }}>{select("time", time, setTime, catalog.times.filter(row => !row.approver_id))}<button disabled={locked || !selectedTime || identity?.id === selectedTime.submitter_id || !allowed("approve_time")}>{t("approveTime")}</button></form>}
        {has("prepare") && <form className="panel reporting-form" aria-label={t("prepare")} onSubmit={event => { event.preventDefault(); if (!allowed("prepare", true) || !/^[1-9]\d{0,14}$/.test(accrual.expected_budget_version)) return; submit("/payruns", { ...accrual, expected_budget_version: Number(accrual.expected_budget_version), time_ids: selectedTimes }); }}><fieldset><legend>{t("selectTimes")}</legend>{approved.map(row => <label key={row.id}><input type="checkbox" disabled={locked} checked={selectedTimes.includes(row.id)} onChange={event => setSelectedTimes(old => event.target.checked ? [...old, row.id] : old.filter(id => id !== row.id))} /><code>{row.id}</code></label>)}</fieldset>{(Object.keys(accrual) as (keyof typeof accrual)[]).map(key => <div key={key}>{input(key, accrual[key], value => setAccrual(old => ({ ...old, [key]: value })))}</div>)}<button disabled={locked || !selectedTimes.length || !allowed("prepare", true)}>{t("prepare")}</button></form>}
        {plan && <section className="panel" aria-label={t("plan")}><h2>{t("plan")}</h2><code>{plan.id} · {plan.plan_digest}</code><p><bdi>{plan.amount_minor} {plan.monetary_policy.currency_code}</bdi> · {plan.phase}</p><pre dir="ltr">{JSON.stringify(plan, null, 2)}</pre>
          {plan.phase === 0 && <button disabled={locked || !allowed("review", true) || !independentReview} onClick={() => submit(`/plans/${plan.id}/review`, { expected_plan_digest: plan.plan_digest })}>{t("review")}</button>}
          {plan.phase === 1 && <button disabled={locked || !allowed("post", true) || !independentPost} onClick={() => submit(`/plans/${plan.id}/post`, { expected_plan_digest: plan.plan_digest })}>{t("post")}</button>}
          {plan.schema_version === "people-payrun-v1" && plan.phase < 2 && <button disabled={locked || !allowed("prepare", true)} onClick={() => submit(`/payruns/${plan.id}/cancel`, { expected_plan_digest: plan.plan_digest })}>{t("cancel")}</button>}
          {plan.schema_version === "people-payrun-v1" && has("read_sensitive") && <button disabled={locked} onClick={async () => { if (!auth.session || !scope) return; const captured = epoch.current; setBusy(true); try { const raw = await peopleRequest(auth.session, scope, `${peopleRoot}/payruns/${plan.id}/evidence`); if (!object(raw)) throw new Error("people_source_invalid"); const verified = await parsePeoplePlan(raw.payrun, scope); if (current(captured) && verified.id === plan.id) setEvidence(raw); } catch (caught) { fail(caught); } finally { if (current(captured)) setBusy(false); } }}>{t("evidence")}</button>}
        </section>}
        {plan?.schema_version === "people-payrun-v1" && plan.phase === 2 && has("pay") && <form className="panel reporting-form" aria-label={t("payment")} onSubmit={event => { event.preventDefault(); if (!allowed("pay", true) || allocations.some(row => !/^[1-9]\d{0,18}$/.test(row.amount)) || new Set(allocations.map(row => row.employee_id)).size !== allocations.length) return; submit(`/payruns/${plan.id}/payments`, { ...payment, employees_minor: Object.fromEntries(allocations.map(row => [row.employee_id, row.amount])) }); }}>{(Object.keys(payment) as (keyof typeof payment)[]).map(key => <div key={key}>{input(key, payment[key], value => setPayment(old => ({ ...old, [key]: value })))}</div>)}{allocations.map((row, index) => <fieldset key={index}><legend>{index + 1}</legend>{select("employee", row.employee_id, value => setAllocations(old => old.map((item, i) => i === index ? { ...item, employee_id: value } : item)), catalog.employees)}{input("amount", row.amount, value => setAllocations(old => old.map((item, i) => i === index ? { ...item, amount: value } : item)))}</fieldset>)}<button type="button" disabled={locked || allocations.length >= 100} onClick={() => setAllocations(old => [...old, { employee_id: "", amount: "" }])}>{t("add")}</button><button disabled={locked || !allowed("pay", true)}>{t("payment")}</button></form>}
        {evidence !== null && <section className="panel" aria-label={t("private")}><h2>{t("private")}</h2><pre dir="ltr">{JSON.stringify(evidence, null, 2)}</pre></section>}
      </>}
    </>}
  </main>;
}
