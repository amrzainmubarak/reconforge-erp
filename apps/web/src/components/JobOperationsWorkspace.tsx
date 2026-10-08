import { useEffect, useRef, useState, type FormEvent } from "react";
import { useBrowserSession } from "../browserSession";
import { AdminApiError, beginBrowserAdminSession, endBrowserAdminSession, stepUpBrowserAdminSession } from "../data";
import { loadExceptionReviewIdentity, type ExceptionReviewIdentity } from "../exception-review-data";
import { commandJob, jobStatuses, loadJobDetail, loadJobPage, type JobDetail, type JobPage, type JobScope, type JobStatus } from "../job-operations-data";
import { jobTranslate, type JobMessage } from "../job-operations-i18n";
import type { Locale } from "../types";
import "./JobOperationsWorkspace.css";

export function JobOperationsWorkspace({ locale }: { locale: Locale }) {
  const auth = useBrowserSession();
  return <JobSession key={auth.revision} locale={locale} />;
}

function JobSession({ locale }: { locale: Locale }) {
  const auth = useBrowserSession(), t = (key: JobMessage) => jobTranslate(locale, key);
  const [tenant, setTenant] = useState("local"), [username, setUsername] = useState(""), [password, setPassword] = useState("");
  const [identity, setIdentity] = useState<ExceptionReviewIdentity | null>(null);
  const [workspace, setWorkspace] = useState(""), [organization, setOrganization] = useState(""), [entity, setEntity] = useState("");
  const [scope, setScope] = useState<JobScope | null>(null), [status, setStatus] = useState<JobStatus | "">("");
  const [page, setPage] = useState<JobPage | null>(null), [detail, setDetail] = useState<JobDetail | null>(null);
  const [cursors, setCursors] = useState([""]), [index, setIndex] = useState(0), [attempt, setAttempt] = useState(0);
  const [busy, setBusy] = useState(false), [error, setError] = useState<JobMessage | null>(null), [unknown, setUnknown] = useState(false);
  const mounted = useRef(true), detailRequest = useRef(0);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const current = () => mounted.current && auth.isCurrent(auth.revision);
  const fail = (caught: unknown) => {
    if (!current() || auth.recover(caught, auth.revision)) return;
    const denied = caught instanceof AdminApiError && [403, 404].includes(caught.status);
    if (denied) { setPage(null); setDetail(null); }
    setError(denied ? "denied" : caught instanceof AdminApiError && caught.status === 409 ? "conflict" : caught instanceof Error && caught.message === "job_operations_contract_invalid" ? "invalid" : "unavailable");
  };
  useEffect(() => {
    if (!auth.session) return;
    const controller = new AbortController();
    loadExceptionReviewIdentity(auth.session, controller.signal).then((value) => {
      if (!controller.signal.aborted && current()) { setIdentity(value); setWorkspace(value.workspaces[0] ?? ""); }
    }).catch((caught: unknown) => { if (!controller.signal.aborted) fail(caught); });
    return () => controller.abort();
  }, [auth.session, auth.revision]);
  useEffect(() => {
    if (!auth.session || !scope) return;
    const controller = new AbortController();
    setPage(null); setDetail(null); setError(null); detailRequest.current += 1;
    loadJobPage(auth.session, scope, status, cursors[index], controller.signal).then((value) => {
      if (!controller.signal.aborted && current()) { setPage(value); setUnknown(false); }
    }).catch((caught: unknown) => { if (!controller.signal.aborted) fail(caught); });
    return () => controller.abort();
  }, [auth.session, auth.revision, scope, status, index, attempt]);

  async function signIn(event: FormEvent) {
    event.preventDefault(); if (busy) return; setBusy(true); setError(null);
    try { const session = await beginBrowserAdminSession({ tenantId: tenant, username, password }); if (current()) auth.begin(session, username, auth.revision); }
    catch (caught) { fail(caught); }
    finally { if (current()) { setBusy(false); setPassword(""); } }
  }
  async function stepUp(event: FormEvent) {
    event.preventDefault(); if (!auth.session || busy) return; setBusy(true); setError(null);
    try { const expiry = await stepUpBrowserAdminSession(auth.session, password); if (current()) auth.elevate(expiry, auth.revision); }
    catch (caught) { fail(caught); }
    finally { if (current()) { setBusy(false); setPassword(""); } }
  }
  async function signOut() {
    if (!auth.session || busy) return; setBusy(true);
    try { await endBrowserAdminSession(auth.session); if (current()) auth.clear(auth.revision); }
    catch (caught) { fail(caught); }
    finally { if (current()) setBusy(false); }
  }
  async function inspect(id: string) {
    if (!auth.session || !scope || busy) return;
    const sequence = ++detailRequest.current; setBusy(true); setError(null); setDetail(null);
    try { const value = await loadJobDetail(auth.session, scope, id); if (current() && sequence === detailRequest.current) setDetail(value); }
    catch (caught) { if (sequence === detailRequest.current) fail(caught); }
    finally { if (current()) setBusy(false); }
  }
  async function act(action: "cancel" | "requeue") {
    if (!auth.session || !scope || !detail || busy || unknown) return;
    setBusy(true); setError(null);
    try { await commandJob(auth.session, scope, detail.job, action); if (current()) { setDetail(null); setAttempt((value) => value + 1); } }
    catch (caught) {
      if (current()) { setDetail(null); setUnknown(!(caught instanceof AdminApiError) || caught.status >= 500); fail(caught); }
    }
    finally { if (current()) setBusy(false); }
  }
  const changeScope = () => { setScope(null); setPage(null); setDetail(null); detailRequest.current += 1; };
  const canManage = identity?.human && identity.permissions.includes("jobs.manage") && Boolean(auth.stepUpExpiresAt);
  return <main id="main-content" className="workbench-content job-operations" dir={locale === "ar" ? "rtl" : "ltr"}>
    <header><h1>{t("title")}</h1><p>{t("description")}</p></header>
    {error ? <p role="alert">{t(error)}</p> : null}{unknown ? <p role="alert">{t("unknown")}</p> : null}
    {!auth.session ? <form className="panel job-form" onSubmit={(event) => void signIn(event)}>
      <label>{t("tenant")}<input value={tenant} autoComplete="organization" required maxLength={64} onChange={(event) => setTenant(event.target.value)} /></label>
      <label>{t("username")}<input value={username} autoComplete="username" required maxLength={160} onChange={(event) => setUsername(event.target.value)} /></label>
      <label>{t("password")}<input type="password" value={password} autoComplete="current-password" required maxLength={512} onChange={(event) => setPassword(event.target.value)} /></label>
      <button disabled={busy}>{t("signIn")}</button>
    </form> : <>
      <section className="panel job-form"><p>{t("signedIn")}: <bdi>{auth.username}</bdi></p><button type="button" disabled={busy} onClick={() => void signOut()}>{t("signOut")}</button></section>
      {identity?.human && identity.permissions.includes("jobs.manage") && !auth.stepUpExpiresAt ? <form className="panel job-form" onSubmit={(event) => void stepUp(event)}>
        <h2>{t("stepUp")}</h2><label>{t("password")}<input type="password" value={password} required autoComplete="current-password" onChange={(event) => setPassword(event.target.value)} /></label><button disabled={busy}>{t("continue")}</button>
      </form> : null}
      <form className="panel job-form" onSubmit={(event) => { event.preventDefault(); setCursors([""]); setIndex(0); setUnknown(false); setScope({ workspaceId: workspace, organizationId: organization, entityId: entity }); }}>
        <label>{t("workspace")}<select value={workspace} required disabled={busy} onChange={(event) => { changeScope(); setWorkspace(event.target.value); }}>
          <option value="">—</option>{identity?.workspaces.map((id) => <option key={id} value={id}>{id}</option>)}</select></label>
        <label>{t("organization")}<input value={organization} maxLength={160} disabled={busy} onChange={(event) => { changeScope(); setOrganization(event.target.value); }} /></label>
        <label>{t("entity")}<input value={entity} required maxLength={160} disabled={busy} onChange={(event) => { changeScope(); setEntity(event.target.value); }} /></label>
        <button disabled={busy || !identity?.permissions.includes("ops.read")}>{t("chooseScope")}</button>
      </form><p>{t("scopeHint")}</p>
      {scope ? <section className="panel job-results" aria-label={t("title")}>
        <div className="job-toolbar"><label>{t("status")}<select value={status} disabled={busy} onChange={(event) => { setStatus(event.target.value as JobStatus | ""); setCursors([""]); setIndex(0); }}><option value="">{t("all")}</option>{jobStatuses.map((value) => <option key={value} value={value}>{value}</option>)}</select></label>
          <button type="button" disabled={busy} onClick={() => setAttempt((value) => value + 1)}>{t("refresh")}</button></div>
        {!page && !error ? <p role="status">{t("loading")}</p> : null}
        {page ? <>{!page.records.length ? <p role="status">{t("empty")}</p> : <ul className="job-list">{page.records.map((job) => <li key={job.id}><bdi>{job.id}</bdi><span>{job.status}</span><span>{t("progress")}: {job.completed_units}/{job.total_units}</span><button type="button" disabled={busy} onClick={() => void inspect(job.id)} aria-label={`${t("details")}: ${job.id}`}>{t("details")}</button></li>)}</ul>}
          <nav aria-label={t("title")}><button type="button" disabled={busy || index === 0} onClick={() => setIndex((value) => value - 1)}>{t("previous")}</button><button type="button" disabled={busy || !page.next_after_id} onClick={() => { setCursors((values) => [...values.slice(0, index + 1), page.next_after_id]); setIndex((value) => value + 1); }}>{t("next")}</button></nav>
        </> : null}
      </section> : null}
      {detail ? <section className="panel job-detail" aria-label={t("evidence")}><h2><bdi>{detail.job.id}</bdi></h2><p>{t("status")}: {detail.job.status} · {t("version")}: {detail.job.version} · {t("retries")}: {detail.job.retry_count}/{detail.job.retry_ceiling}</p>
        {detail.job.safe_error_code ? <p>{t("reason")}: <bdi>{detail.job.safe_error_code}</bdi></p> : null}
        {canManage && ["queued", "paused", "retrying"].includes(detail.job.status) ? <button type="button" disabled={busy || unknown} onClick={() => void act("cancel")}>{t("cancel")}</button> : null}
        {canManage && ["failed", "paused"].includes(detail.job.status) ? <button type="button" disabled={busy || unknown} onClick={() => void act("requeue")}>{t("requeue")}</button> : null}
        <h3>{t("evidence")}</h3>{detail.history_truncated ? <p>{t("truncated")}</p> : null}<ol>{detail.transitions.map((event) => <li key={event.job_version}><span>{event.from_status || "—"} → {event.to_status}</span><span>{t("version")}: {event.job_version}</span><span>{t("actor")}: <bdi>{event.actor_id}</bdi></span><span>{t("reason")}: <bdi>{event.reason_code}</bdi></span><time dateTime={event.occurred_at}><bdi>{event.occurred_at}</bdi></time></li>)}</ol>
      </section> : null}
    </>}
  </main>;
}
