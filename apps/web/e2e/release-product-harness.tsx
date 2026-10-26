import { useState } from "react";
import { createRoot } from "react-dom/client";
import { BrowserSessionProvider, useBrowserSession } from "../src/browserSession";
import { beginBrowserAdminSession, endBrowserAdminSession, stepUpBrowserAdminSession } from "../src/data";
import { HcmLeaveWorkspace } from "../src/components/HcmLeaveWorkspace";
import { CrmSubscriptionWorkspace } from "../src/components/CrmSubscriptionWorkspace";
import { ProjectMilestoneWorkspace } from "../src/components/ProjectMilestoneWorkspace";
function Harness() {
  const auth = useBrowserSession();
  const [tenant, setTenant] = useState(""), [username, setUsername] = useState(""), [password, setPassword] = useState(""), [error, setError] = useState(false);
  const [page, setPage] = useState("hcm"), [locale, setLocale] = useState<"en" | "ar">("en");
  return <><form onSubmit={async event => { event.preventDefault(); const revision = auth.revision; try { const session = await beginBrowserAdminSession({ tenantId: tenant, username, password }); auth.begin(session, username, revision); setError(false); } catch { setError(true); } }}><label>Tenant ID<input value={tenant} onChange={event => setTenant(event.target.value)} /></label><label>Username<input value={username} onChange={event => setUsername(event.target.value)} /></label><label>Password<input type="password" value={password} onChange={event => setPassword(event.target.value)} /></label><button>Sign in</button></form>
    {error && <p role="alert">Sign in failed</p>}
    <button onClick={async () => { const revision = auth.revision; if (auth.session) { const expires = await stepUpBrowserAdminSession(auth.session, password); auth.elevate(expires, revision); } }}>Confirm privileged access</button>
    <button onClick={async () => { const revision = auth.revision; if (auth.session) await endBrowserAdminSession(auth.session); auth.clear(revision); }}>Sign out</button>
    <nav aria-label="Acceptance workspace"><button onClick={() => setPage("hcm")}>HCM</button><button onClick={() => setPage("crm")}>CRM</button><button onClick={() => setPage("project")}>Project</button><button onClick={() => setLocale(locale === "en" ? "ar" : "en")}>Toggle language</button></nav>
    {page === "hcm" ? <HcmLeaveWorkspace locale={locale} /> : page === "crm" ? <CrmSubscriptionWorkspace locale={locale} /> : <ProjectMilestoneWorkspace locale={locale} />}
  </>;
}
createRoot(document.getElementById("root")!).render(<BrowserSessionProvider><Harness /></BrowserSessionProvider>);
