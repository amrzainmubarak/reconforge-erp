import { useState } from "react";
import { LogOut, LogIn, Building2 } from "lucide-react";
import { useBrowserSession } from "../browserSession";
import { endBrowserAdminSession } from "../data";
import type { MessageKey } from "../i18n";

export function StudioSessionControls({ translate, workspaces, onSignIn }: { translate: (key: MessageKey) => string; workspaces: string[]; onSignIn: () => void }) {
  const auth = useBrowserSession();
  const [pending, setPending] = useState(false), [error, setError] = useState(false);
  async function signOut() {
    if (!auth.session || pending) return;
    const revision = auth.revision;
    setPending(true); setError(false);
    try { await endBrowserAdminSession(auth.session); auth.clear(revision); }
    catch { if (auth.isCurrent(revision)) setError(true); }
    finally { setPending(false); }
  }
  return <section className="studio-session" aria-label={translate("studioSession")}>
    {auth.session ? <><span className="studio-session-identity"><strong><bdi>{auth.username}</bdi></strong><span>{translate("studioTenant")}: <bdi>{auth.session.tenantId}</bdi></span></span>
      <details className="studio-scope-details"><summary><Building2 size={15} aria-hidden="true" />{translate("studioWorkspaces")} ({workspaces.length})</summary><div><p>{translate("studioWorkspaceHint")}</p><ul>{workspaces.map(workspace => <li key={workspace}><bdi>{workspace}</bdi></li>)}</ul></div></details>
      <button type="button" disabled={pending} onClick={() => void signOut()}><LogOut size={15} aria-hidden="true" />{translate("studioSignOut")}</button></> : <><span>{translate("navSignedOut")}</span><button type="button" onClick={onSignIn}><LogIn size={15} aria-hidden="true" />{translate("studioSignIn")}</button></>}
    {error && <p role="alert">{translate("studioLogoutError")}</p>}
  </section>;
}
