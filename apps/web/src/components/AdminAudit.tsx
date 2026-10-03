import { AlertTriangle, CheckCircle2, KeyRound, RefreshCw, ShieldCheck } from "lucide-react";
import { useEffect, useLayoutEffect, useRef, useState } from "react";

import { AdminApiError, beginBrowserAdminSession, endBrowserAdminSession, loadAdminAccessPermissions, loadAdminAccessRoles, loadAdminAuditPage, loadAdminIdentitySessions, loadAdminIdentityUsers, loadAdminIntegrations, loadAdminRetentionPolicies, loadAdminSecurityCenter, revokeAdminIdentitySession, setAdminIdentityUserDisabled, stepUpBrowserAdminSession, verifyAdminAudit } from "../data";
import type { MessageKey } from "../i18n";
import type { Locale, AdminAccessPermission, AdminAccessRole, AdminAuditEvent, AdminAuditVerification, AdminIdentitySession, AdminIdentityUser, AdminIntegration, AdminRetentionPolicy, AdminSecuritySnapshot, BrowserAdminSession } from "../types";
import { AdminAccessMutations } from "./AdminAccessMutations";
import { formatCount } from "../locale-format";
import { AdminGovernanceMutations } from "./AdminGovernanceMutations";
import { useBrowserSession } from "../browserSession";


function errorKey(error: unknown): MessageKey {
  const code = error instanceof AdminApiError ? error.code : error instanceof Error ? error.message : "adminError";
  if (code === "auth_required" || code === "invalid_token") return "adminAuthRequired";
  if (code === "step_up_required" || code === "mfa_required") return "adminStepUpRequired";
  if (code === "csrf_required") return "adminCsrfRequired";
  if (code === "permission_denied") return "adminPermissionDenied";
  if (code === "identity_lifecycle_version_conflict") return "adminIdentityConflict";
  if (code === "identity_session_not_found") return "adminIdentitySessionUnavailable";
  if (code === "identity_user_not_found") return "adminIdentityUserUnavailable";
  if (code === "identity_self_disable_forbidden") return "adminIdentitySelfDisableForbidden";
  if (code === "identity_last_administrator_forbidden") return "adminIdentityLastAdministratorForbidden";
  if (code === "access_lifecycle_version_conflict") return "adminAccessConflict";
  if (code === "access_last_manager_forbidden") return "adminAccessLastManagerForbidden";
  if (code === "access_role_exists") return "adminAccessRoleExists";
  if (code === "access_role_not_found" || code === "access_user_not_found") return "adminAccessTargetUnavailable";
  if (code === "integration_state_conflict" || code === "retention_policy_lifecycle_version_conflict" || code === "retention_version_conflict") return "adminGovernanceConflict";
  if (code === "integration_not_found" || code === "retention_policy_not_found" || code === "evidence_not_found") return "adminGovernanceTargetUnavailable";
  if (code === "retention_policy_retired") return "adminGovernancePolicyUnavailable";
  return "adminError";
}

function shortDigest(value: string): string { return `${value.slice(0, 12)}…${value.slice(-8)}`; }

const securityHighlights: ReadonlyArray<{ section: AdminSecuritySnapshot["sections"][number]["id"]; key: string; label: MessageKey }> = [
  { section: "identity", key: "active_users", label: "adminSecurityActiveUsers" },
  { section: "sessions", key: "active_sessions", label: "adminSecurityActiveSessions" },
  { section: "integrations", key: "enabled_service_accounts", label: "adminSecurityServiceAccounts" },
  { section: "policy", key: "active_scope_grants", label: "adminSecurityScopeGrants" },
  { section: "retention", key: "evidence_records", label: "adminSecurityEvidenceRecords" },
  { section: "audit", key: "audit_events", label: "adminSecurityAuditEvents" },
];

type SessionRevocationReason = "access_change" | "administrative_cleanup" | "security_response" | "user_request";

function securityValue(snapshot: AdminSecuritySnapshot, sectionId: AdminSecuritySnapshot["sections"][number]["id"], key: string): number {
  const value = snapshot.sections.find((section) => section.id === sectionId)?.values[key];
  return typeof value === "number" ? value : 0;
}

export function AdminAudit({ translate, locale }: { translate: (key: MessageKey) => string; locale: Locale }) {
  const { revision } = useBrowserSession();
  // Changing the security boundary discards every privileged view and pending form.
  return <AdminAuditView key={revision} translate={translate} locale={locale} />;
}

function AdminAuditView({ translate, locale }: { translate: (key: MessageKey) => string; locale: Locale }) {
  const auth = useBrowserSession();
  const { session, stepUpExpiresAt } = auth;
  const [tenantId, setTenantId] = useState(session?.tenantId ?? "");
  const [username, setUsername] = useState(auth.username);
  const [password, setPassword] = useState("");
  const [stepUpPassword, setStepUpPassword] = useState("");
  const [events, setEvents] = useState<AdminAuditEvent[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [verification, setVerification] = useState<AdminAuditVerification[]>([]);
  const [securitySnapshot, setSecuritySnapshot] = useState<AdminSecuritySnapshot | null>(null);
  const [securityUnavailable, setSecurityUnavailable] = useState(false);
  const [securityLoading, setSecurityLoading] = useState(false);
  const [identityUsers, setIdentityUsers] = useState<AdminIdentityUser[] | null>(null);
  const [identitySessions, setIdentitySessions] = useState<AdminIdentitySession[] | null>(null);
  const [identityUnavailable, setIdentityUnavailable] = useState(false);
  const [identityLoading, setIdentityLoading] = useState(false);
  const [identityActionSession, setIdentityActionSession] = useState<AdminIdentitySession | null>(null);
  const [identityActionReason, setIdentityActionReason] = useState<SessionRevocationReason>("security_response");
  const [identityActionConfirmation, setIdentityActionConfirmation] = useState("");
  const [identityActionNotice, setIdentityActionNotice] = useState<MessageKey | null>(null);
  const [identityActionRevokedSessions, setIdentityActionRevokedSessions] = useState<number | null>(null);
  const [identityUserAction, setIdentityUserAction] = useState<{ user: AdminIdentityUser; disabled: boolean } | null>(null);
  const [identityUserConfirmation, setIdentityUserConfirmation] = useState("");
  const [accessPermissions, setAccessPermissions] = useState<AdminAccessPermission[] | null>(null);
  const [accessRoles, setAccessRoles] = useState<AdminAccessRole[] | null>(null);
  const [accessUnavailable, setAccessUnavailable] = useState(false);
  const [accessLoading, setAccessLoading] = useState(false);
  const [integrations, setIntegrations] = useState<AdminIntegration[] | null>(null);
  const [retentionPolicies, setRetentionPolicies] = useState<AdminRetentionPolicy[] | null>(null);
  const [governanceUnavailable, setGovernanceUnavailable] = useState(false);
  const [governanceLoading, setGovernanceLoading] = useState(false);
  const [error, setError] = useState<MessageKey | null>(null);
  const [busy, setBusy] = useState(false);
  const reads = useRef<AbortController | null>(null);
  const mounted = useRef(false);
  // A committed view may receive a command before its passive read effect runs.
  // Its security authority depends on view lifetime and revision, not read setup.
  useLayoutEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; reads.current?.abort(); };
  }, []);
  const current = () => mounted.current && auth.isCurrent(auth.revision);
  const readController = () => {
    if (!reads.current || reads.current.signal.aborted) reads.current = new AbortController();
    return reads.current;
  };
  const fetcher: typeof fetch = (input, options) => {
    if (!current()) return Promise.reject(new DOMException("Session changed.", "AbortError"));
    const safe = !options?.method || ["GET", "HEAD"].includes(options.method);
    return fetch(input, { ...options, ...(safe ? { signal: readController().signal } : {}) });
  };
  const handleError = (caught: unknown) => {
    if (current() && !auth.recover(caught, auth.revision)) setError(errorKey(caught));
  };

  const refresh = async (active: BrowserAdminSession, cursor?: string) => {
    const [page, chains] = await Promise.all([loadAdminAuditPage(active, cursor, fetcher), verifyAdminAudit(active, fetcher)]);
    if (!current()) return;
    setEvents((current) => cursor ? [...current, ...page.events] : page.events);
    setNextCursor(page.nextCursor); setVerification(chains);
    if (!cursor) {
      setSecurityLoading(true); setSecurityUnavailable(false); setSecuritySnapshot(null);
      void loadAdminSecurityCenter(active, fetcher).then((snapshot) => { if (current()) setSecuritySnapshot(snapshot); }).catch((caught) => { if (current()) { handleError(caught); setSecurityUnavailable(true); } }).finally(() => { if (current()) setSecurityLoading(false); });
      setIdentityLoading(true); setIdentityUnavailable(false); setIdentityUsers(null); setIdentitySessions(null);
      void Promise.all([loadAdminIdentityUsers(active, fetcher), loadAdminIdentitySessions(active, fetcher)]).then(([users, sessions]) => { if (current()) { setIdentityUsers(users); setIdentitySessions(sessions); } }).catch((caught) => { if (current()) { handleError(caught); setIdentityUnavailable(true); } }).finally(() => { if (current()) setIdentityLoading(false); });
      setAccessLoading(true); setAccessUnavailable(false); setAccessPermissions(null); setAccessRoles(null);
      void Promise.all([loadAdminAccessPermissions(active, fetcher), loadAdminAccessRoles(active, fetcher)]).then(([permissions, roles]) => { if (current()) { setAccessPermissions(permissions); setAccessRoles(roles); } }).catch((caught) => { if (current()) { handleError(caught); setAccessUnavailable(true); } }).finally(() => { if (current()) setAccessLoading(false); });
      setGovernanceLoading(true); setGovernanceUnavailable(false); setIntegrations(null); setRetentionPolicies(null);
      void Promise.all([loadAdminIntegrations(active, fetcher), loadAdminRetentionPolicies(active, fetcher)]).then(([listedIntegrations, policies]) => { if (current()) { setIntegrations(listedIntegrations); setRetentionPolicies(policies); } }).catch((caught) => { if (current()) { handleError(caught); setGovernanceUnavailable(true); } }).finally(() => { if (current()) setGovernanceLoading(false); });
    }
  };
  useEffect(() => {
    const controller = readController();
    if (session && stepUpExpiresAt) void refresh(session).catch(handleError);
    return () => controller.abort();
  // A security revision remounts this view; locale changes must not restart reads.
  }, []);
  const signIn = async (event: React.FormEvent) => {
    event.preventDefault(); setBusy(true); setError(null);
    try { const active = await beginBrowserAdminSession({ tenantId, username, password, fetcher }); if (current()) auth.begin(active, username, auth.revision); }
    catch (caught) { setError(errorKey(caught)); } finally { setBusy(false); }
  };
  const stepUp = async (event: React.FormEvent) => {
    event.preventDefault(); if (!session) return; setBusy(true); setError(null);
    try { const expires = await stepUpBrowserAdminSession(session, stepUpPassword, fetcher); if (current()) auth.elevate(expires, auth.revision); }
    catch (caught) { handleError(caught); } finally { setBusy(false); }
  };
  const signOut = async () => {
    if (!session) return;
    setBusy(true); setError(null);
    try { await endBrowserAdminSession(session, fetcher); if (current()) auth.clear(auth.revision); }
    catch (caught) { handleError(caught); }
    finally { if (current()) setBusy(false); }
  };
  const revokeSession = async (event: React.FormEvent) => {
    event.preventDefault(); if (!session || !identityActionSession || identityActionConfirmation.trim() !== "REVOKE") return;
    setBusy(true); setError(null); setIdentityActionNotice(null); setIdentityActionRevokedSessions(null);
    try {
      const result = await revokeAdminIdentitySession(session, identityActionSession, identityActionReason, fetcher);
      if (!current()) return;
      if (result.revokedCurrentSession) {
        auth.clear(auth.revision, "adminIdentityCurrentSessionRevoked");
      } else {
        setIdentitySessions((current) => current?.map((item) => item.id === result.session.id ? result.session : item) ?? current);
        setIdentityActionNotice(result.transitioned ? "adminIdentitySessionRevoked" : "adminIdentitySessionAlreadyRevoked");
      }
      setIdentityActionSession(null); setIdentityActionConfirmation("");
    } catch (caught) { handleError(caught); } finally { setBusy(false); }
  };
  const changeUserStatus = async (event: React.FormEvent) => {
    event.preventDefault(); if (!session || !identityUserAction) return;
    const expected = identityUserAction.disabled ? "DISABLE" : "ENABLE";
    if (identityUserConfirmation.trim() !== expected) return;
    setBusy(true); setError(null); setIdentityActionNotice(null); setIdentityActionRevokedSessions(null);
    try {
      const result = await setAdminIdentityUserDisabled(session, identityUserAction.user, identityUserAction.disabled, fetcher);
      if (!current()) return;
      setIdentityUsers((current) => current?.map((item) => item.id === result.user.id ? result.user : item) ?? current);
      setIdentityActionRevokedSessions(result.revokedSessions);
      setIdentityActionNotice(result.transitioned ? (result.user.disabled ? "adminIdentityUserDisabled" : "adminIdentityUserEnabled") : "adminIdentityUserAlreadyInState");
      setIdentityUserAction(null); setIdentityUserConfirmation("");
      try { const sessions = await loadAdminIdentitySessions(session, fetcher); if (current()) { setIdentitySessions(sessions); setIdentityUnavailable(false); } }
      catch (caught) { if (current()) { handleError(caught); setIdentitySessions(null); setIdentityUnavailable(true); } }
    } catch (caught) { handleError(caught); }
    finally { setBusy(false); }
  };
  const refreshAccessAdministration = async () => {
    if (!session) return;
    const [listedPermissions, listedRoles, listedUsers, listedSessions] = await Promise.all([loadAdminAccessPermissions(session, fetcher), loadAdminAccessRoles(session, fetcher), loadAdminIdentityUsers(session, fetcher), loadAdminIdentitySessions(session, fetcher)]);
    if (!current()) return;
    setAccessPermissions(listedPermissions); setAccessRoles(listedRoles); setIdentityUsers(listedUsers); setIdentitySessions(listedSessions); setAccessUnavailable(false); setIdentityUnavailable(false);
  };
  const refreshGovernanceAdministration = async () => {
    if (!session) return;
    const [listedIntegrations, listedPolicies] = await Promise.all([loadAdminIntegrations(session, fetcher), loadAdminRetentionPolicies(session, fetcher)]);
    if (!current()) return;
    setIntegrations(listedIntegrations); setRetentionPolicies(listedPolicies); setGovernanceUnavailable(false);
  };

  return <main id="main-content" className="workbench-content admin-audit">
    <section className="workbench-hero workbench-hero--live" aria-labelledby="admin-audit-title">
      <div><p className="eyebrow">{translate("adminAudit")}</p><h1 id="admin-audit-title">{translate("adminAuditTitle")}</h1><p>{translate("adminAuditIntro")}</p></div>
      <div className="contract-badge"><ShieldCheck size={20} aria-hidden="true" /><span>{translate("adminBoundary")}<strong>/api/v1/admin/audit/*</strong></span></div>
    </section>
    <p className="live-boundary"><KeyRound size={17} aria-hidden="true" />{translate("adminSessionBoundary")}</p>
    {auth.notice ? <p className="mapping-error" role="alert">{translate(auth.notice)}</p> : null}
    {session ? <div className="live-freshness"><span>{translate("adminTenant")}: <strong>{session.tenantId}</strong> · {auth.username}</span><button type="button" className="secondary-button" disabled={busy} onClick={() => void signOut()}>{translate("adminSignOut")}</button></div> : null}
    {error ? <p className="mapping-error" role="alert"><AlertTriangle size={16} aria-hidden="true" />{translate(error)}</p> : null}
    {identityActionNotice ? <p className="admin-security-status" role="status"><CheckCircle2 size={16} aria-hidden="true" />{translate(identityActionNotice)}{identityActionRevokedSessions !== null ? <span>{translate("adminIdentityRevokedSessions")}: {identityActionRevokedSessions}</span> : null}</p> : null}
    {!session ? <section className="panel admin-form"><h2>{translate("adminSignIn")}</h2><form onSubmit={signIn}><label>{translate("adminTenant")}<input required value={tenantId} onChange={(event) => setTenantId(event.target.value)} autoComplete="organization" /></label><label>{translate("adminUsername")}<input required value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="username" /></label><label>{translate("adminPassword")}<input required type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="current-password" /></label><button className="primary-button" disabled={busy}>{translate("adminSignIn")}</button></form></section> : null}
    {session && !stepUpExpiresAt ? <section className="panel admin-form"><h2>{translate("adminStepUp")}</h2><p>{translate("adminStepUpHelp")}</p><form onSubmit={stepUp}><label>{translate("adminPassword")}<input required type="password" value={stepUpPassword} onChange={(event) => setStepUpPassword(event.target.value)} autoComplete="current-password" /></label><button className="primary-button" disabled={busy}>{translate("adminContinue")}</button></form></section> : null}
    {session && stepUpExpiresAt ? <>
      <section className="live-freshness" role="status"><CheckCircle2 size={18} aria-hidden="true" /><strong>{translate("adminStepUpActive")}</strong><span>{stepUpExpiresAt}</span></section>
      <section className="panel live-table-panel" aria-label={translate("adminEvents")}><div className="table-scroll"><table className="live-table"><thead><tr><th>{translate("source")}</th><th>{translate("adminSequence")}</th><th>{translate("adminAction")}</th><th>{translate("adminHashes")}</th></tr></thead><tbody>{events.map((item) => <tr key={`${item.source}:${item.event_id}`}><th scope="row"><strong>{item.source}</strong><code>{item.event_id}</code></th><td>{item.sequence}<small>{item.occurred_at}</small></td><td>{item.action}<small>{item.object_type}</small></td><td><code>{shortDigest(item.event_hash)}</code></td></tr>)}</tbody></table></div>{!events.length ? <p className="admin-empty">{translate("adminNoEvents")}</p> : null}</section>
      <section className="panel admin-verification" aria-label={translate("adminVerification")}><h2>{translate("adminVerification")}</h2>{verification.map((chain) => <p key={chain.source}><CheckCircle2 size={16} aria-hidden="true" /><strong>{chain.source}</strong><span>{chain.ok ? translate("adminVerified") : translate("adminVerificationFailed")}</span><code>{chain.checked_events}</code></p>)}</section>
      <section className="panel admin-security" aria-labelledby="admin-security-title">
        <div><h2 id="admin-security-title">{translate("adminSecurityTitle")}</h2><p>{translate("adminSecurityBoundary")}</p></div>
        {securityLoading ? <p className="admin-security-status" role="status">{translate("adminSecurityLoading")}</p> : null}
        {securityUnavailable ? <p className="admin-security-status" role="status"><AlertTriangle size={16} aria-hidden="true" />{translate("adminSecurityUnavailable")}</p> : null}
        {securitySnapshot ? <>
          <p className={`admin-security-posture admin-security-posture--${securitySnapshot.posture}`}><AlertTriangle size={17} aria-hidden="true" /><strong>{securitySnapshot.posture === "attention_required" ? translate("adminSecurityAttention") : translate("adminSecurityObserved")}</strong><span>{securitySnapshot.asOf}</span></p>
          {securitySnapshot.attention.length ? <ul className="admin-security-attention">{securitySnapshot.attention.map((item) => <li key={`${item.severity}:${item.code}`}><strong>{item.severity}</strong><code>{item.code}</code><span>{formatCount(item.count, locale)}</span></li>)}</ul> : <p className="admin-security-status">{translate("adminSecurityNoAttention")}</p>}
          <div className="admin-security-highlights">{securityHighlights.map((item) => <article key={`${item.section}:${item.key}`}><span>{translate(item.label)}</span><strong>{formatCount(securityValue(securitySnapshot, item.section, item.key), locale)}</strong></article>)}</div>
        </> : null}
      </section>
      <section className="panel admin-identity" aria-labelledby="admin-identity-title">
        <div><h2 id="admin-identity-title">{translate("adminIdentityTitle")}</h2><p>{translate("adminIdentityBoundary")}</p></div>
        {identityLoading ? <p className="admin-security-status" role="status">{translate("adminIdentityLoading")}</p> : null}
        {identityUnavailable ? <p className="admin-security-status" role="status"><AlertTriangle size={16} aria-hidden="true" />{translate("adminIdentityUnavailable")}</p> : null}
        {identityUsers && identitySessions ? <>
          <div className="table-scroll"><table className="live-table"><caption>{translate("adminIdentityUsers")}</caption><thead><tr><th>{translate("adminIdentityUser")}</th><th>{translate("adminIdentityRoles")}</th><th>{translate("adminIdentityActiveSessions")}</th><th>{translate("adminIdentityStatus")}</th><th>{translate("adminIdentityAction")}</th></tr></thead><tbody>{identityUsers.map((user) => <tr key={user.id}><th scope="row"><strong>{user.username}</strong><small>{user.displayName}</small></th><td>{user.roles.join(", ") || translate("adminIdentityNoRoles")}</td><td>{formatCount(user.activeSessions, locale)}</td><td>{user.disabled ? translate("adminIdentityDisabled") : translate("adminIdentityActive")}</td><td>{!user.disabled && user.username.trim().toLocaleLowerCase() === username.trim().toLocaleLowerCase() ? <span>{translate("adminIdentityCurrentOperator")}</span> : <button className={user.disabled ? "secondary-button" : "danger-button"} disabled={busy} onClick={() => { setIdentityUserAction({ user, disabled: !user.disabled }); setIdentityUserConfirmation(""); setIdentityActionSession(null); setIdentityActionNotice(null); setIdentityActionRevokedSessions(null); }}>{user.disabled ? translate("adminIdentityEnableUser") : translate("adminIdentityDisableUser")}</button>}</td></tr>)}</tbody></table></div>
          {identityUserAction ? <form className="admin-form admin-identity-action" aria-label={identityUserAction.disabled ? translate("adminIdentityDisableTitle") : translate("adminIdentityEnableTitle")} onSubmit={changeUserStatus}><h3>{identityUserAction.disabled ? translate("adminIdentityDisableTitle") : translate("adminIdentityEnableTitle")}</h3><p>{identityUserAction.disabled ? translate("adminIdentityDisableHelp") : translate("adminIdentityEnableHelp")}</p><p><strong>{identityUserAction.user.username}</strong></p><label>{identityUserAction.disabled ? translate("adminIdentityDisableConfirmation") : translate("adminIdentityEnableConfirmation")}<input required value={identityUserConfirmation} onChange={(event) => setIdentityUserConfirmation(event.target.value)} autoComplete="off" placeholder={identityUserAction.disabled ? "DISABLE" : "ENABLE"} /></label><p>{translate("adminIdentityUserStatusWarning")}</p><div className="admin-action-row"><button className={identityUserAction.disabled ? "danger-button" : "primary-button"} disabled={busy || identityUserConfirmation.trim() !== (identityUserAction.disabled ? "DISABLE" : "ENABLE")}>{identityUserAction.disabled ? translate("adminIdentityConfirmDisable") : translate("adminIdentityConfirmEnable")}</button><button type="button" className="secondary-button" disabled={busy} onClick={() => { setIdentityUserAction(null); setIdentityUserConfirmation(""); }}>{translate("adminIdentityCancel")}</button></div></form> : null}
          <div className="table-scroll"><table className="live-table"><caption>{translate("adminIdentitySessions")}</caption><thead><tr><th>{translate("adminIdentityUser")}</th><th>{translate("adminIdentityStatus")}</th><th>{translate("adminIdentityCreated")}</th><th>{translate("adminIdentityExpires")}</th><th>{translate("adminIdentityAction")}</th></tr></thead><tbody>{identitySessions.map((item) => <tr key={item.id}><th scope="row">{item.username}</th><td>{item.status}</td><td>{item.createdAt}</td><td>{item.expiresAt}</td><td>{item.status === "active" ? <button className="secondary-button" disabled={busy} onClick={() => { setIdentityActionSession(item); setIdentityActionReason("security_response"); setIdentityActionConfirmation(""); setIdentityUserAction(null); setIdentityUserConfirmation(""); setIdentityActionNotice(null); setIdentityActionRevokedSessions(null); }}>{translate("adminIdentityRevoke")}</button> : <span>{translate("adminIdentityNoAction")}</span>}</td></tr>)}</tbody></table></div>
          {identityActionSession ? <form className="admin-form admin-identity-action" aria-label={translate("adminIdentityRevokeTitle")} onSubmit={revokeSession}><h3>{translate("adminIdentityRevokeTitle")}</h3><p>{translate("adminIdentityRevokeHelp")}</p><p><strong>{identityActionSession.username}</strong></p><label>{translate("adminIdentityRevokeReason")}<select value={identityActionReason} onChange={(event) => setIdentityActionReason(event.target.value as SessionRevocationReason)}><option value="security_response">{translate("adminIdentityReasonSecurity")}</option><option value="access_change">{translate("adminIdentityReasonAccess")}</option><option value="administrative_cleanup">{translate("adminIdentityReasonCleanup")}</option><option value="user_request">{translate("adminIdentityReasonUser")}</option></select></label><label>{translate("adminIdentityRevokeConfirmation")}<input required value={identityActionConfirmation} onChange={(event) => setIdentityActionConfirmation(event.target.value)} autoComplete="off" placeholder="REVOKE" /></label><p>{translate("adminIdentityRevokeWarning")}</p><div className="admin-action-row"><button className="primary-button" disabled={busy || identityActionConfirmation.trim() !== "REVOKE"}>{translate("adminIdentityConfirmRevoke")}</button><button type="button" className="secondary-button" disabled={busy} onClick={() => { setIdentityActionSession(null); setIdentityActionConfirmation(""); }}>{translate("adminIdentityCancel")}</button></div></form> : null}
        </> : null}
      </section>
      <section className="panel admin-identity" aria-labelledby="admin-access-title"><div><h2 id="admin-access-title">{translate("adminAccessTitle")}</h2><p>{translate("adminAccessBoundary")}</p></div>{accessLoading ? <p className="admin-security-status" role="status">{translate("adminAccessLoading")}</p> : null}{accessUnavailable ? <p className="admin-security-status" role="status"><AlertTriangle size={16} aria-hidden="true" />{translate("adminAccessUnavailable")}</p> : null}{accessPermissions && accessRoles && identityUsers ? <AdminAccessMutations session={session} currentUsername={username} permissions={accessPermissions} roles={accessRoles} users={identityUsers} translate={translate} refresh={refreshAccessAdministration} onError={handleError} /> : null}</section>
      <section className="panel admin-identity" aria-labelledby="admin-governance-title"><div><h2 id="admin-governance-title">{translate("adminGovernanceTitle")}</h2><p>{translate("adminGovernanceBoundary")}</p></div>{governanceLoading ? <p className="admin-security-status" role="status">{translate("adminGovernanceLoading")}</p> : null}{governanceUnavailable ? <p className="admin-security-status" role="status"><AlertTriangle size={16} aria-hidden="true" />{translate("adminGovernanceUnavailable")}</p> : null}{integrations && retentionPolicies ? <AdminGovernanceMutations session={session} integrations={integrations} policies={retentionPolicies} translate={translate} refresh={refreshGovernanceAdministration} onError={handleError} /> : null}</section>
      {nextCursor ? <button className="secondary-button" disabled={busy} onClick={() => { setBusy(true); setError(null); void refresh(session, nextCursor).catch(handleError).finally(() => setBusy(false)); }}><RefreshCw size={16} aria-hidden="true" />{translate("adminLoadMore")}</button> : null}
    </> : null}
  </main>;
}
