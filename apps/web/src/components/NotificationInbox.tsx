import { useEffect, useRef, useState, type FormEvent } from "react";
import { useBrowserSession } from "../browserSession";
import { AdminApiError, beginBrowserAdminSession, endBrowserAdminSession } from "../data";
import { acknowledgeInbox, loadInboxPage, loadInboxWorkspaces, type InboxNotification, type InboxPage } from "../notification-inbox-data";
import { inboxTranslate, type InboxMessage } from "../notification-inbox-i18n";
import type { Locale } from "../types";
import "./NotificationInbox.css";

export function NotificationInbox({ locale }: { locale: Locale }) {
  const auth = useBrowserSession();
  return <InboxSession key={auth.revision} locale={locale} />;
}

function InboxSession({ locale }: { locale: Locale }) {
  const auth = useBrowserSession();
  const t = (key: InboxMessage) => inboxTranslate(locale, key);
  const [tenant, setTenant] = useState("local"), [username, setUsername] = useState(""), [password, setPassword] = useState("");
  const [workspaces, setWorkspaces] = useState<string[] | null>(null), [workspace, setWorkspace] = useState("");
  const [page, setPage] = useState<InboxPage | null>(null), [offset, setOffset] = useState(0), [unreadOnly, setUnreadOnly] = useState(false);
  const [attempt, setAttempt] = useState(0), [busy, setBusy] = useState(false), [error, setError] = useState<InboxMessage | null>(null);
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const current = () => mounted.current && auth.isCurrent(auth.revision);
  const fail = (caught: unknown) => {
    if (current() && !auth.recover(caught, auth.revision)) {
      if (caught instanceof AdminApiError && [403, 404].includes(caught.status)) { setPage(null); setWorkspace(""); setWorkspaces(null); }
      setError(caught instanceof AdminApiError && caught.status === 403 ? "denied" : "unavailable");
    }
  };
  useEffect(() => {
    if (!auth.session) return;
    const controller = new AbortController();
    loadInboxWorkspaces(auth.session, controller.signal).then((values) => {
      if (!controller.signal.aborted && current()) { setWorkspaces(values); setWorkspace((selected) => values.includes(selected) ? selected : values[0] ?? ""); }
    }).catch((caught: unknown) => { if (!controller.signal.aborted) fail(caught); });
    return () => controller.abort();
  }, [auth.session, auth.revision, attempt]);
  useEffect(() => {
    if (!auth.session || !workspace) return;
    const controller = new AbortController();
    setPage(null); setError(null);
    loadInboxPage(auth.session, workspace, offset, unreadOnly, controller.signal).then((value) => {
      if (!controller.signal.aborted && current()) {
        if (offset && offset >= value.total) setOffset(Math.max(0, Math.floor(Math.max(0, value.total - 1) / 25) * 25));
        else setPage(value);
      }
    }).catch((caught: unknown) => { if (!controller.signal.aborted) fail(caught); });
    return () => controller.abort();
  }, [auth.session, auth.revision, workspace, offset, unreadOnly, attempt]);

  async function signIn(event: FormEvent) {
    event.preventDefault(); if (busy) return; setBusy(true); setError(null);
    try { const session = await beginBrowserAdminSession({ tenantId: tenant, username, password }); if (current()) auth.begin(session, username, auth.revision); }
    catch (caught) { fail(caught); }
    finally { if (current()) { setBusy(false); setPassword(""); } }
  }
  async function signOut() {
    if (!auth.session || busy) return; setBusy(true);
    try { await endBrowserAdminSession(auth.session); if (current()) auth.clear(auth.revision); }
    catch (caught) { fail(caught); }
    finally { if (current()) setBusy(false); }
  }
  async function read(notification: InboxNotification) {
    if (!auth.session || busy) return; setBusy(true); setError(null);
    try { await acknowledgeInbox(auth.session, workspace, notification); if (current()) setAttempt((value) => value + 1); }
    catch (caught) { fail(caught); }
    finally { if (current()) setBusy(false); }
  }

  return <main id="main-content" className="workbench-content inbox-workspace" dir={locale === "ar" ? "rtl" : "ltr"}>
    <header><h1>{t("title")}</h1><p>{t("description")}</p></header>
    {error ? <p role="alert">{t(error)}</p> : null}
    {!auth.session ? <form className="panel inbox-login" onSubmit={(event) => void signIn(event)}>
      <label>{t("tenant")}<input autoComplete="organization" value={tenant} onChange={(event) => setTenant(event.target.value)} required maxLength={64} /></label>
      <label>{t("username")}<input autoComplete="username" value={username} onChange={(event) => setUsername(event.target.value)} required maxLength={160} /></label>
      <label>{t("password")}<input type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} required maxLength={512} /></label>
      <button type="submit" disabled={busy}>{t("signIn")}</button>
    </form> : <>
      <section className="panel inbox-toolbar" aria-label={t("workspace")}>
        <p>{t("signedIn")} <bdi>{auth.username}</bdi></p><button type="button" disabled={busy} onClick={() => void signOut()}>{t("signOut")}</button>
        <label>{t("workspace")}<select disabled={busy} value={workspace} onChange={(event) => { setPage(null); setOffset(0); setWorkspace(event.target.value); }}>
          <option value="">{t("chooseWorkspace")}</option>{workspaces?.map((id) => <option key={id} value={id}>{id}</option>)}</select></label>
        <label className="inbox-check"><input type="checkbox" checked={unreadOnly} disabled={busy} onChange={(event) => { setOffset(0); setUnreadOnly(event.target.checked); }} />{t("unreadOnly")}</label>
        <button type="button" disabled={busy} onClick={() => setAttempt((value) => value + 1)}>{t("refresh")}</button>
      </section>
      <p className="inbox-hint">{t("scopeHint")}</p>
      {workspaces && !workspaces.length ? <p role="status">{t("noWorkspaces")}</p> : null}
      {(!workspaces || (workspace && !page)) && !error ? <p role="status">{t("loading")}</p> : null}
      {page ? <section className="panel inbox-results" aria-label={t("title")}>
        <p role="status">{t("total")}: {page.total} · {t("unread")}: {page.unread_count}</p>
        {!page.records.length ? <p>{t("empty")}</p> : <ul className="inbox-list">{page.records.map((record) => <li key={record.id}>
          <article><h2>{inboxTranslate(locale, record.topic)}</h2><p>{record.read_at ? t("read") : t("unread")}</p>
            <p>{t("resource")}: <bdi>{record.resource_type}</bdi> / <bdi>{record.resource_id}</bdi></p>
            <p>{t("createdAt")}: <time dateTime={record.created_at}><bdi>{record.created_at}</bdi></time></p>
            {!record.read_at ? <button type="button" disabled={busy} aria-label={`${t("markRead")}: ${record.resource_id}`} onClick={() => void read(record)}>{t("markRead")}</button> : <p>{t("readAt")}: <time dateTime={record.read_at}><bdi>{record.read_at}</bdi></time></p>}
            <details><summary>{t("evidence")}</summary><p>{t("digest")}: <bdi className="inbox-digest">{record.payload_digest}</bdi></p></details>
          </article>
        </li>)}</ul>}
        <nav className="inbox-pages" aria-label={t("title")}><button type="button" disabled={busy || offset === 0} onClick={() => setOffset((value) => Math.max(0, value - 25))}>{t("previous")}</button>
          <button type="button" disabled={busy || offset + 25 >= page.total || offset >= 100_000} onClick={() => setOffset((value) => value + 25)}>{t("next")}</button></nav>
      </section> : null}
    </>}
  </main>;
}
