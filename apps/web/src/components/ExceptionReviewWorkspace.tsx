import { RefreshCw, ShieldCheck } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent } from "react";

import { useBrowserSession } from "../browserSession";
import { AdminApiError, beginBrowserAdminSession, endBrowserAdminSession } from "../data";
import {
  assignExceptionReview,
  loadExceptionReviewDetail,
  loadExceptionReviewIdentity,
  loadExceptionReviewList,
  transitionExceptionReview,
  type ExceptionReviewDetail,
  type ExceptionReviewFilters,
  type ExceptionReviewListPage,
  type ExceptionReviewRecord,
  type ExceptionReviewStatus,
} from "../exception-review-data";
import { exceptionReviewTranslate, type ExceptionReviewMessage } from "../exception-review-i18n";
import type { Locale } from "../types";
import "./ExceptionReviewWorkspace.css";

const transitionTargets: Record<ExceptionReviewStatus, ExceptionReviewStatus[]> = {
  Open: ["In Review"],
  "In Review": ["Resolved", "Accepted Risk"],
  Resolved: ["Closed"],
  "Accepted Risk": ["Closed"],
  Closed: [],
};

function errorKey(error: unknown): ExceptionReviewMessage {
  if (error instanceof Error && error.message === "exception_review_contract_invalid") return "contract";
  if (!(error instanceof AdminApiError)) return "unavailable";
  if (error.code === "csrf_required") return "csrf";
  if (error.code === "exception_review_conflict") return "conflict";
  if (error.code === "exception_self_review_refused") return "selfReview";
  if (error.code === "exception_reviewer_ineligible" || error.code === "exception_reviewer_assignment_required") return "reviewerRequired";
  if (error.code === "exception_creator_identity_required") return "creatorIdentity";
  if (error.code === "exception_review_invalid" || error.code === "exception_review_expected_version_required") return "invalid";
  if (error.status === 401 || error.code === "auth_required" || error.code === "invalid_token") return "expired";
  if (error.status === 403 || error.code === "tenant_required") return "denied";
  return error.status >= 500 ? "unavailable" : "invalid";
}

function recordFromDetail(value: ExceptionReviewDetail): ExceptionReviewRecord {
  const { history: _history, history_page: _historyPage, ...record } = value;
  return record;
}

function transitionLabel(from: string, to: string): string {
  return from === to ? to || "—" : `${from || "—"} → ${to || "—"}`;
}

export function ExceptionReviewWorkspace({ locale }: { locale: Locale }) {
  const { revision } = useBrowserSession();
  return <ExceptionReviewSession key={revision} locale={locale} />;
}

function ExceptionReviewSession({ locale }: { locale: Locale }) {
  const auth = useBrowserSession();
  const t = (key: ExceptionReviewMessage) => exceptionReviewTranslate(locale, key);
  const [tenant, setTenant] = useState("local");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [identity, setIdentity] = useState<Awaited<ReturnType<typeof loadExceptionReviewIdentity>> | null>(null);
  const [workspace, setWorkspace] = useState("");
  const [filters, setFilters] = useState<ExceptionReviewFilters>({});
  const [page, setPage] = useState<ExceptionReviewListPage | null>(null);
  const [listCursors, setListCursors] = useState<Array<string | undefined>>([undefined]);
  const [listIndex, setListIndex] = useState(0);
  const [selectedId, setSelectedId] = useState("");
  const [detail, setDetail] = useState<ExceptionReviewDetail | null>(null);
  const [historyCursors, setHistoryCursors] = useState<Array<string | undefined>>([undefined]);
  const [historyIndex, setHistoryIndex] = useState(0);
  const [reviewer, setReviewer] = useState("");
  const [targetStatus, setTargetStatus] = useState<ExceptionReviewStatus | "">("");
  const [reason, setReason] = useState("");
  const [identityAttempt, setIdentityAttempt] = useState(0);
  const [listAttempt, setListAttempt] = useState(0);
  const [detailAttempt, setDetailAttempt] = useState(0);
  const [busy, setBusy] = useState(false);
  const [unknownOutcome, setUnknownOutcome] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<ExceptionReviewMessage | null>(null);
  const mounted = useRef(true);
  const errorRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);
  useEffect(() => { if (error) errorRef.current?.focus(); }, [error]);

  const current = () => mounted.current && auth.isCurrent(auth.revision);
  const resetList = () => {
    setPage(null);
    setListCursors([undefined]);
    setListIndex(0);
    setSelectedId("");
    setDetail(null);
    setHistoryCursors([undefined]);
    setHistoryIndex(0);
  };
  const fail = (caught: unknown, mutation = false) => {
    if (!current() || auth.recover(caught, auth.revision)) return;
    const next = errorKey(caught);
    setError(next);
    setSaved(false);
    if (mutation && next === "unavailable") setUnknownOutcome(true);
  };

  useEffect(() => {
    if (!auth.session) return;
    const controller = new AbortController();
    setIdentity(null);
    setError(null);
    loadExceptionReviewIdentity(auth.session, controller.signal).then((value) => {
      if (!controller.signal.aborted && current()) setIdentity(value);
    }).catch((caught: unknown) => {
      if (!controller.signal.aborted) fail(caught);
    });
    return () => controller.abort();
  }, [auth.session, auth.revision, identityAttempt]);

  useEffect(() => {
    if (!identity) return;
    setWorkspace((selected) => identity.workspaces.includes(selected) ? selected : identity.workspaces[0] ?? "");
  }, [identity]);

  useEffect(() => {
    if (!auth.session || !identity || !workspace || !identity.permissions.some((permission) => permission === "exceptions.read" || permission === "exceptions.manage")) return;
    const controller = new AbortController();
    const cursor = listCursors[listIndex];
    setPage(null);
    setError(null);
    loadExceptionReviewList(auth.session, workspace, filters, cursor, 25, controller.signal).then((value) => {
      if (!controller.signal.aborted && current()) setPage(value);
    }).catch((caught: unknown) => {
      if (!controller.signal.aborted) fail(caught);
    });
    return () => controller.abort();
  }, [auth.session, auth.revision, identity, workspace, filters, listCursors, listIndex, listAttempt]);

  useEffect(() => {
    if (!auth.session || !workspace || !selectedId) return;
    const controller = new AbortController();
    const cursor = historyCursors[historyIndex];
    setDetail(null);
    setError(null);
    loadExceptionReviewDetail(auth.session, workspace, selectedId, cursor, 25, controller.signal).then((value) => {
      if (!controller.signal.aborted && current()) {
        setReviewer(value.owner);
        setTargetStatus(transitionTargets[value.status][0] ?? "");
        setReason("");
        setDetail(value);
      }
    }).catch((caught: unknown) => {
      if (!controller.signal.aborted) fail(caught);
    });
    return () => controller.abort();
  }, [auth.session, auth.revision, workspace, selectedId, historyCursors, historyIndex, detailAttempt]);

  async function signIn(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const session = await beginBrowserAdminSession({ tenantId: tenant, username, password });
      if (current()) auth.begin(session, username, auth.revision);
    } catch (caught) {
      if (current()) setError(errorKey(caught));
    } finally {
      if (current()) { setBusy(false); setPassword(""); }
    }
  }

  async function signOut() {
    if (!auth.session || busy) return;
    setBusy(true);
    try {
      await endBrowserAdminSession(auth.session);
      if (current()) auth.clear(auth.revision);
    } catch (caught) {
      fail(caught);
    } finally {
      if (current()) setBusy(false);
    }
  }

  function selectWorkspace(value: string) {
    setWorkspace(value);
    setError(null);
    setSaved(false);
    setUnknownOutcome(false);
    resetList();
  }

  function updateFilters(next: ExceptionReviewFilters) {
    setFilters(next);
    setError(null);
    setSaved(false);
    setUnknownOutcome(false);
    resetList();
  }

  function selectRecord(id: string) {
    if (busy || unknownOutcome) return;
    setSelectedId(id);
    setDetail(null);
    setHistoryCursors([undefined]);
    setHistoryIndex(0);
    setError(null);
    setSaved(false);
  }

  function refresh() {
    if (busy) return;
    setError(null);
    setSaved(false);
    setUnknownOutcome(false);
    setIdentityAttempt((value) => value + 1);
    setListAttempt((value) => value + 1);
    if (selectedId) setDetailAttempt((value) => value + 1);
  }

  function applyUpdated(value: ExceptionReviewDetail) {
    const updated = recordFromDetail(value);
    setReviewer(value.owner);
    setTargetStatus(transitionTargets[value.status][0] ?? "");
    setReason("");
    setDetail(value);
    setPage((previous) => previous ? {
      ...previous,
      exceptions: previous.exceptions.map((record) => record.id === updated.id ? updated : record),
    } : previous);
    // The mutation already returns the authoritative first history page.
    // Preserve its cursor identity to avoid clearing that result and a newly
    // entered decision reason through an unnecessary detail fetch.
    setHistoryCursors((previous) => previous.length === 1 && previous[0] === undefined ? previous : [undefined]);
    setHistoryIndex(0);
    setUnknownOutcome(false);
    setSaved(true);
    setError(null);
  }

  async function assign(event: FormEvent) {
    event.preventDefault();
    if (!auth.session || !detail || busy || unknownOutcome) return;
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      const value = await assignExceptionReview(auth.session, workspace, detail.id, reviewer, detail.row_version);
      if (current()) applyUpdated(value);
    } catch (caught) {
      fail(caught, true);
    } finally {
      if (current()) setBusy(false);
    }
  }

  async function transition(event: FormEvent) {
    event.preventDefault();
    if (!auth.session || !detail || !targetStatus || busy || unknownOutcome) return;
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      const value = await transitionExceptionReview(auth.session, workspace, detail.id, targetStatus, detail.row_version, reason);
      if (current()) applyUpdated(value);
    } catch (caught) {
      fail(caught, true);
    } finally {
      if (current()) setBusy(false);
    }
  }

  const readable = Boolean(identity?.permissions.some((permission) => permission === "exceptions.read" || permission === "exceptions.manage"));
  const manageable = Boolean(identity?.permissions.includes("exceptions.manage"));
  const hasNextListPage = Boolean(page?.pagination.has_more && page.pagination.next_cursor);
  const hasNextHistoryPage = Boolean(detail?.history_page.has_more && detail.history_page.next_cursor);
  const transitionOptions = detail ? transitionTargets[detail.status] : [];

  return <main id="main-content" className="workbench-content exception-review-workspace" dir={locale === "ar" ? "rtl" : "ltr"}>
    <header className="workbench-hero workbench-hero--live exception-review-hero">
      <div><p className="eyebrow">{t("live")}</p><h1>{t("title")}</h1><p>{t("intro")}</p></div>
      <ShieldCheck size={36} aria-hidden="true" />
    </header>
    <p className="live-boundary">{t("boundary")}</p>
    {auth.notice && !auth.session ? <p role="alert">{t("expired")}</p> : null}
    {error ? <div ref={errorRef} tabIndex={-1} className="exception-review-error" role="alert"><p>{t(error)}</p>{auth.session ? <button className="secondary-button" type="button" disabled={busy} onClick={refresh}>{t("refresh")}</button> : null}</div> : null}
    {saved ? <p className="exception-review-saved" role="status">{t("saved")}</p> : null}
    {unknownOutcome ? <p className="exception-review-stale" role="alert">{t("stale")}</p> : null}

    {!auth.session ? <section className="panel admin-form exception-review-login"><h2>{t("signIn")}</h2><form onSubmit={(event) => void signIn(event)}>
      <label>{t("tenant")}<input required maxLength={160} value={tenant} onChange={(event) => setTenant(event.target.value)} autoComplete="organization" /></label>
      <label>{t("username")}<input required maxLength={160} value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="username" /></label>
      <label>{t("password")}<input required type="password" maxLength={512} value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="current-password" /></label>
      <button className="primary-button" disabled={busy}>{t("signIn")}</button>
    </form></section> : <>
      <section className="panel exception-review-toolbar" aria-label={t("session")}>
        <p>{t("session")}: <strong><bdi>{identity?.username ?? auth.username}</bdi></strong> · <bdi>{auth.session.tenantId}</bdi></p>
        <label>{t("workspace")}<select value={workspace} disabled={busy || !identity || unknownOutcome} onChange={(event) => selectWorkspace(event.target.value)}>
          <option value="">{t("chooseWorkspace")}</option>{identity?.workspaces.map((id) => <option key={id} value={id}>{id}</option>)}
        </select></label>
        <label>{t("risk")}<select value={filters.risk ?? ""} disabled={busy || unknownOutcome} onChange={(event) => updateFilters({ ...filters, risk: (event.target.value || undefined) as ExceptionReviewFilters["risk"] })}>
          <option value="">{t("allRisk")}</option><option value="critical">critical</option><option value="high">high</option><option value="medium">medium</option><option value="low">low</option>
        </select></label>
        <label>{t("status")}<select value={filters.status ?? ""} disabled={busy || unknownOutcome} onChange={(event) => updateFilters({ ...filters, status: (event.target.value || undefined) as ExceptionReviewFilters["status"] })}>
          <option value="">{t("allStatus")}</option>{(["Open", "In Review", "Resolved", "Accepted Risk", "Closed"] as ExceptionReviewStatus[]).map((value) => <option key={value} value={value}>{value}</option>)}
        </select></label>
        <button className="secondary-button" type="button" disabled={busy} onClick={refresh}><RefreshCw size={16} aria-hidden="true" />{t("refresh")}</button>
        <button className="secondary-button" type="button" disabled={busy} onClick={() => void signOut()}>{t("signOut")}</button>
      </section>
      {!identity && !error ? <p role="status">{t("loading")}</p> : null}
      {identity && !identity.workspaces.length ? <p role="status">{t("noWorkspaces")}</p> : null}
      {identity && !readable ? <p role="alert">{t("noRead")}</p> : null}
      {identity && readable && workspace ? <section className="exception-review-content">
        <section className="panel exception-review-list" aria-labelledby="exception-review-list-heading">
          <div className="exception-review-section-heading"><div><h2 id="exception-review-list-heading">{t("records")}</h2><p>{t("workspace")}: <bdi>{workspace}</bdi></p></div><p role="status">{page ? `${page.pagination.returned} · ${t("page")} ${listIndex + 1}` : t("loading")}</p></div>
          {!page ? <p role="status">{t("loading")}</p> : !page.exceptions.length ? <p>{t("noRecords")}</p> : <div className="table-scroll exception-review-table" role="region" tabIndex={0} aria-label={t("recordsTable")} aria-describedby="exception-review-table-help">
            <p id="exception-review-table-help" className="sr-only">{t("selectRecord")}</p>
            <table><thead><tr><th scope="col">{t("identifier")}</th><th scope="col">{t("risk")}</th><th scope="col">{t("status")}</th><th scope="col">{t("control")}</th><th scope="col">{t("owner")}</th><th scope="col">{t("version")}</th><th scope="col"><span className="sr-only">{t("review")}</span></th></tr></thead>
              <tbody>{page.exceptions.map((record) => <tr key={record.id} data-selected={record.id === selectedId ? "true" : "false"}><td><bdi>{record.id}</bdi></td><td><span className={`exception-review-risk exception-review-risk--${record.risk_rating}`}>{record.risk_rating}</span></td><td>{record.status}</td><td><bdi>{record.control_code}</bdi></td><td><bdi>{record.owner || "—"}</bdi></td><td>{record.row_version}</td><td><button type="button" className="secondary-button" aria-pressed={record.id === selectedId} disabled={busy || unknownOutcome} onClick={() => selectRecord(record.id)}>{t("review")}</button></td></tr>)}</tbody>
            </table>
          </div>}
          {page ? <nav className="exception-review-pages" aria-label={t("records")}><button className="secondary-button" type="button" disabled={busy || unknownOutcome || listIndex === 0} onClick={() => setListIndex((value) => value - 1)}>{t("previous")}</button><button className="secondary-button" type="button" disabled={busy || unknownOutcome || !hasNextListPage} onClick={() => {
            const cursor = page.pagination.next_cursor; if (!cursor) return;
            setListCursors((values) => [...values.slice(0, listIndex + 1), cursor]); setListIndex((value) => value + 1);
          }}>{t("next")}</button></nav> : null}
        </section>

        <section className="panel exception-review-detail" aria-labelledby="exception-review-detail-heading">
          <div className="exception-review-section-heading"><div><h2 id="exception-review-detail-heading">{t("details")}</h2><p>{t("selectRecord")}</p></div>{selectedId ? <button className="secondary-button" type="button" disabled={busy} onClick={() => { setUnknownOutcome(false); setError(null); setSaved(false); setDetailAttempt((value) => value + 1); }}><RefreshCw size={16} aria-hidden="true" />{t("refreshRecord")}</button> : null}</div>
          {!selectedId ? <p>{t("selectRecord")}</p> : !detail ? <p role="status">{t("loading")}</p> : <>
            <dl className="exception-review-facts">
              <div><dt>{t("identifier")}</dt><dd><bdi>{detail.id}</bdi></dd></div><div><dt>{t("status")}</dt><dd>{detail.status}</dd></div><div><dt>{t("risk")}</dt><dd>{detail.risk_rating}</dd></div><div><dt>{t("version")}</dt><dd>{detail.row_version}</dd></div>
              <div><dt>{t("workspaceId")}</dt><dd><bdi>{detail.workspace_id}</bdi></dd></div><div><dt>{t("organization")}</dt><dd><bdi>{detail.organization_id || "—"}</bdi></dd></div><div><dt>{t("legalEntity")}</dt><dd><bdi>{detail.legal_entity_id || "—"}</bdi></dd></div><div><dt>{t("period")}</dt><dd><bdi>{detail.period_name || "—"}</bdi></dd></div>
              <div><dt>{t("entity")}</dt><dd><bdi>{detail.entity_code || "—"}</bdi></dd></div><div><dt>{t("account")}</dt><dd><bdi>{detail.account_code || "—"}</bdi></dd></div><div><dt>{t("control")}</dt><dd><bdi>{detail.control_code || "—"}</bdi></dd></div><div><dt>{t("owner")}</dt><dd><bdi>{detail.owner || "—"}</bdi></dd></div>
              <div><dt>{t("source")}</dt><dd><bdi>{detail.source_type} / {detail.source_id}</bdi></dd></div><div><dt>{t("sla")}</dt><dd><bdi>{detail.sla_target_date || "—"}</bdi></dd></div><div><dt>{t("created")}</dt><dd><time dateTime={detail.created_at}><bdi>{detail.created_at}</bdi></time></dd></div><div><dt>{t("updated")}</dt><dd><time dateTime={detail.updated_at}><bdi>{detail.updated_at}</bdi></time></dd></div>
            </dl>
            <section className="exception-review-description" aria-labelledby="exception-review-description-heading"><h3 id="exception-review-description-heading">{t("description")}</h3><p>{detail.description}</p></section>
            {manageable ? <div className="exception-review-actions">
              <form className="exception-review-form" onSubmit={(event) => void assign(event)}><h3>{t("assignment")}</h3><label>{t("reviewer")}<input required maxLength={160} value={reviewer} disabled={busy || unknownOutcome || detail.status === "Closed"} onChange={(event) => setReviewer(event.target.value)} autoComplete="off" aria-describedby="exception-review-reviewer-help" /></label><p id="exception-review-reviewer-help">{t("reviewerHelp")}</p><button className="primary-button" disabled={busy || unknownOutcome || detail.status === "Closed"}>{t("assign")}</button></form>
              <form className="exception-review-form" onSubmit={(event) => void transition(event)}><h3>{t("transition")}</h3>{transitionOptions.length ? <><label>{t("transitionTo")}<select value={targetStatus} disabled={busy || unknownOutcome} onChange={(event) => setTargetStatus(event.target.value as ExceptionReviewStatus)}>{transitionOptions.map((status) => <option key={status} value={status}>{status}</option>)}</select></label><label>{t("reason")}<textarea maxLength={1_000} value={reason} disabled={busy || unknownOutcome} required={targetStatus === "Accepted Risk"} onChange={(event) => setReason(event.target.value)} aria-describedby="exception-review-reason-help" /></label><p id="exception-review-reason-help">{t("reasonHelp")}</p><button className="primary-button" disabled={busy || unknownOutcome || !targetStatus}>{t("submitDecision")}</button></> : <p>{detail.status === "Closed" ? t("notAllowed") : "—"}</p>}</form>
            </div> : <p className="exception-review-read-only">{t("notAllowed")}</p>}
            <section className="exception-review-history" aria-labelledby="exception-review-history-heading"><div className="exception-review-section-heading"><div><h3 id="exception-review-history-heading">{t("history")}</h3><p>{t("evidenceHelp")}</p></div><p role="status">{t("page")} {historyIndex + 1}</p></div>
              {!detail.history.length ? <p>{t("noEvidence")}</p> : <div className="table-scroll exception-review-history-table" role="region" tabIndex={0} aria-label={t("historyTable")}><table><thead><tr><th scope="col">{t("historyAction")}</th><th scope="col">{t("historyTransition")}</th><th scope="col">{t("historyActor")}</th><th scope="col">{t("historyReason")}</th><th scope="col">{t("historyAt")}</th><th scope="col">{t("evidence")}</th></tr></thead><tbody>{detail.history.map((item) => <tr key={item.id}><td><bdi>{item.action}</bdi></td><td>{transitionLabel(item.from_status, item.to_status)}</td><td><bdi>{item.actor_label}</bdi></td><td>{item.reason || "—"}</td><td><time dateTime={item.occurred_at}><bdi>{item.occurred_at}</bdi></time></td><td><dl className="exception-review-evidence"><div><dt>{t("auditEvent")}</dt><dd><bdi>{item.audit_event_id || "—"}</bdi></dd></div><div><dt>{t("outboxEvent")}</dt><dd><bdi>{item.outbox_event_id || "—"}</bdi></dd></div></dl></td></tr>)}</tbody></table></div>}
              <nav className="exception-review-pages" aria-label={t("history")}><button className="secondary-button" type="button" disabled={busy || unknownOutcome || historyIndex === 0} onClick={() => setHistoryIndex((value) => value - 1)}>{t("previous")}</button><button className="secondary-button" type="button" disabled={busy || unknownOutcome || !hasNextHistoryPage} onClick={() => {
                const cursor = detail.history_page.next_cursor; if (!cursor) return;
                setHistoryCursors((values) => [...values.slice(0, historyIndex + 1), cursor]); setHistoryIndex((value) => value + 1);
              }}>{t("next")}</button></nav>
            </section>
          </>}
        </section>
      </section> : null}
    </>}
  </main>;
}
