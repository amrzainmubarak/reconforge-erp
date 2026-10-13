import { useEffect, useRef, useState, type FormEvent } from "react";
import { loadBudgetIdentity, type BudgetIdentity } from "../budget-control-data";
import { useBrowserSession } from "../browserSession";
import { AdminApiError, beginBrowserAdminSession } from "../data";
import type { FinanceScope } from "../enterprise-finance-data";
import { loadProjectCloseDiagnostic, loadProjectCloseEvidence, loadProjectEvidence, loadProjectReport, projectMoney, projectReconciliationPermissions, type ProjectCloseDiagnostic, type ProjectReport, type ProjectSelection } from "../project-source-reconciliation-data";
import { projectReconciliationWords } from "../project-source-reconciliation-i18n";
import type { Locale } from "../types";
import "./ProjectSourceReconciliationPage.css";

export function ProjectSourceReconciliationPage({ locale }: { locale: Locale }) { const auth = useBrowserSession(); return <ProjectSourceSession key={auth.revision} locale={locale} />; }
function ProjectSourceSession({ locale }: { locale: Locale }) {
  const auth = useBrowserSession(), generation = auth.revision, word = (k: keyof typeof projectReconciliationWords) => projectReconciliationWords[k][locale === "ar" ? 1 : 0];
  const [identity, setIdentity] = useState<BudgetIdentity | null>(null), [scope, setScope] = useState<FinanceScope>({ workspace_id: "", organization_id: "", legal_entity_id: "" });
  const [selection, setSelection] = useState<ProjectSelection>({ project_id: "", period_id: "", payrun_id: "", invoice_id: "" });
  const [report, setReport] = useState<ProjectReport | null>(null), [busy, setBusy] = useState(false), [error, setError] = useState<"invalid" | "denied" | "unavailable" | null>(null), [evidenceSha, setEvidenceSha] = useState("");
  const [closeDiagnostic, setCloseDiagnostic] = useState<ProjectCloseDiagnostic | null>(null), [closeEvidenceSha, setCloseEvidenceSha] = useState("");
  const [login, setLogin] = useState({ tenant: "local", username: "", password: "" });
  const epoch = useRef(0), lock = useRef(false), current = (version: number) => epoch.current === version && auth.isCurrent(generation);
  const allowed = Boolean(auth.session && identity?.human && projectReconciliationPermissions.every(p => identity.permissions.includes(p)) && identity.workspaces.includes(scope.workspace_id) && identity.organizations.includes(scope.organization_id) && identity.entities.includes(scope.legal_entity_id));
  const failure = (caught: unknown) => caught instanceof AdminApiError && [401, 403].includes(caught.status) ? "denied" : caught instanceof AdminApiError && caught.status === 503 ? "unavailable" : "invalid";
  function invalidate() { epoch.current++; setReport(null); setEvidenceSha(""); setCloseDiagnostic(null); setCloseEvidenceSha(""); setError(null); }
  async function authenticate(event: FormEvent) { event.preventDefault(); if (lock.current) return; lock.current = true; setBusy(true); const captured = epoch.current;
    try { const session = await beginBrowserAdminSession({ tenantId: login.tenant, username: login.username, password: login.password }); if (current(captured)) auth.begin(session, login.username, generation); }
    catch (caught) { if (current(captured) && !auth.recover(caught, generation)) setError(failure(caught)); }
    finally { lock.current = false; if (current(captured)) { setBusy(false); setLogin(old => ({ ...old, password: "" })); } }
  }
  useEffect(() => { if (!auth.session) return; const abort = new AbortController(); loadBudgetIdentity(auth.session, abort.signal).then(value => { if (!abort.signal.aborted && auth.isCurrent(generation)) { setIdentity(value); setScope({ workspace_id: value.workspaces[0] ?? "", organization_id: value.organizations[0] ?? "", legal_entity_id: value.entities[0] ?? "" }); } }).catch(caught => { if (!abort.signal.aborted && !auth.recover(caught, generation)) setError(failure(caught)); }); return () => { epoch.current++; abort.abort(); }; }, [auth.revision]);
  async function verify(event: FormEvent) { event.preventDefault(); if (!allowed || !auth.session || lock.current || Object.values(selection).some(v => !v)) return; lock.current = true; invalidate(); const captured = epoch.current; setBusy(true);
    try { const value = await loadProjectReport(auth.session, { ...scope }, { ...selection }); if (current(captured)) setReport(value); } catch (caught) { if (current(captured) && !auth.recover(caught, generation)) setError(failure(caught)); } finally { lock.current = false; if (current(captured)) setBusy(false); }
  }
  async function download() { if (!report || !auth.session || !allowed || lock.current) return; lock.current = true; setBusy(true); const captured = epoch.current;
    try { const value = await loadProjectEvidence(auth.session, { ...scope }, { ...selection }, report.report_digest); if (!current(captured)) return;
      const blob = new Blob([new Uint8Array(value.bytes)], { type: "application/json" }), url = URL.createObjectURL(blob), a = document.createElement("a"); a.href = url; a.download = "project-source-evidence.json"; a.click(); URL.revokeObjectURL(url); setEvidenceSha(value.sha256);
    } catch (caught) { if (current(captured)) { invalidate(); if (caught instanceof AdminApiError) auth.recover(caught, generation); setError(failure(caught)); } } finally { lock.current = false; if (auth.isCurrent(generation)) setBusy(false); }
  }
  async function diagnose() { if (!report || !auth.session || !allowed || lock.current) return; lock.current = true; setBusy(true); setCloseDiagnostic(null); setCloseEvidenceSha(""); const captured = epoch.current;
    try { const value = await loadProjectCloseDiagnostic(auth.session, { ...scope }, { ...selection }, report); if (current(captured)) setCloseDiagnostic(value); }
    catch (caught) { if (current(captured)) { invalidate(); if (caught instanceof AdminApiError) auth.recover(caught, generation); setError(failure(caught)); } }
    finally { lock.current = false; if (auth.isCurrent(generation)) setBusy(false); }
  }
  async function downloadClose() { if (!report || !closeDiagnostic || !auth.session || !allowed || lock.current) return; lock.current = true; setBusy(true); const captured = epoch.current;
    try { const value = await loadProjectCloseEvidence(auth.session, { ...scope }, { ...selection }, report, closeDiagnostic); if (!current(captured)) return;
      const url = URL.createObjectURL(new Blob([new Uint8Array(value.bytes)], { type: "application/json" })), a = document.createElement("a"); a.href = url; a.download = "project-source-close-evidence.json"; a.click(); URL.revokeObjectURL(url); setCloseEvidenceSha(value.sha256);
    } catch (caught) { if (current(captured)) { invalidate(); if (caught instanceof AdminApiError) auth.recover(caught, generation); setError(failure(caught)); } } finally { lock.current = false; if (auth.isCurrent(generation)) setBusy(false); }
  }
  const fields = [["project_id", "project"], ["period_id", "period"], ["payrun_id", "payrun"], ["invoice_id", "invoice"]] as const;
  const money = (amount: string) => `${projectMoney(amount, report!.currency_policy.currency_precision, locale)} ${report!.currency_policy.currency_code}`;
  return <main id="main-content" aria-busy={busy} className="project-source-page" dir={locale === "ar" ? "rtl" : "ltr"}><h1>{word("title")}</h1><p>{word("subtitle")}</p>
    {!auth.session && <form aria-label={word("login")} onSubmit={authenticate}><p>{word("signin")}</p><div className="project-source-fields">
      {([["tenant", "tenant"], ["username", "username"], ["password", "password"]] as const).map(([key, label]) => <label key={key}>{word(label)}<input required type={key === "password" ? "password" : "text"} autoComplete={key === "password" ? "current-password" : key === "username" ? "username" : "off"} value={login[key]} onChange={e => setLogin(old => ({ ...old, [key]: e.target.value }))} /></label>)}
      </div><button disabled={busy} type="submit">{word("login")}</button></form>}
    <form aria-label={word("read")} onSubmit={verify}><fieldset disabled={busy || !identity}><legend>{word("scope")}</legend><div className="project-source-fields">
      {([["workspace_id", "workspace"], ["organization_id", "organization"], ["legal_entity_id", "entity"]] as const).map(([key, label]) => <label key={key}>{word(label)}<input maxLength={160} value={scope[key]} onChange={e => { invalidate(); setScope(old => ({ ...old, [key]: e.target.value })); }} /></label>)}
      {fields.map(([key, label]) => <label key={key}>{word(label)}<input required maxLength={160} value={selection[key]} onChange={e => { invalidate(); setSelection(old => ({ ...old, [key]: e.target.value })); }} /></label>)}
      </div><button disabled={!allowed || busy} type="submit">{word("read")}</button></fieldset></form>
    {busy && <p role="status">{word("pending")}</p>}{error && <p role="alert">{word(error)}</p>}{identity && !allowed && <p>{word("denied")}</p>}
    {report && <div><p role="status">{word("verified")}</p><h2>{report.project.project_code}</h2><dl className="project-source-totals">
      {([["wage_cost_minor", "cost"], ["revenue_minor", "revenue"], ["source_margin_minor", "margin"]] as const).map(([key, label]) => <div key={key}><dt>{word(label)}</dt><dd>{money(report.project_totals[key])}</dd></div>)}</dl>
      <h2>{word("whole")}</h2><dl className="project-source-totals">{([["wage_accrued_minor", "accrued"], ["wage_paid_minor", "paid"], ["wage_liability_minor", "liability"], ["invoice_minor", "invoiced"], ["collected_minor", "collected"], ["ar_outstanding_minor", "outstanding"]] as const).map(([key, label]) => <div key={key}><dt>{word(label)}</dt><dd>{money(report.whole_source_settlement[key])}</dd></div>)}</dl>
      <details><summary>{word("evidence")}</summary><code>{report.report_digest}</code><ul>{report.source_membership.map(source => <li key={source.id}><code>{source.id}</code> · <code>{source.effect_id}</code></li>)}</ul></details>
      <button type="button" disabled={busy || !allowed} onClick={() => void download()}>{word("download")}</button>{evidenceSha && <p><code>{evidenceSha}</code></p>}
      <section aria-label={word("closeTitle")}><h2>{word("closeTitle")}</h2><button type="button" disabled={busy || !allowed} onClick={() => void diagnose()}>{word("closeRead")}</button>
        {closeDiagnostic && <><p>{word(closeDiagnostic.source_obligations_settled ? "closeSettled" : "closeOutstanding")}</p><p>{word("closeTime")}: {closeDiagnostic.whole_time_claims.length}</p>
          <dl>{closeDiagnostic.observed_native_periods.map(period => <div key={period.id}><dt>{word("closePeriod")}</dt><dd>{period.name} · {period.status} · <time>{period.start_date}</time> — <time>{period.end_date}</time></dd></div>)}</dl>
          <code>{closeDiagnostic.diagnostic_digest}</code><button type="button" disabled={busy || !allowed} onClick={() => void downloadClose()}>{word("closeDownload")}</button>{closeEvidenceSha && <p><code>{closeEvidenceSha}</code></p>}</>}
        <p>{word("closeLimit")}</p></section>
      </div>}<p className="project-source-limit">{word("limits")}</p></main>;
}
