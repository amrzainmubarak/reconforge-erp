import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";

import { AdminApiError } from "./data";
import type { BrowserAdminSession } from "./types";

type SessionNotice = "adminAuthRequired" | "adminStepUpRequired" | "adminCsrfRequired" | "adminIdentityCurrentSessionRevoked" | null;
interface SessionState {
  session: BrowserAdminSession | null;
  username: string;
  stepUpExpiresAt: string;
  notice: SessionNotice;
  revision: number;
}
interface BrowserSessionContext extends SessionState {
  begin: (session: BrowserAdminSession, username: string, revision: number) => void;
  elevate: (expiresAt: string, revision: number) => void;
  clear: (revision: number, notice?: SessionNotice) => void;
  recover: (error: unknown, revision: number) => boolean;
  isCurrent: (revision: number) => boolean;
}

const SessionContext = createContext<BrowserSessionContext | null>(null);
const emptyState: SessionState = { session: null, username: "", stepUpExpiresAt: "", notice: null, revision: 0 };

/** Tenant selection and CSRF proof live only in this mounted application. */
export function BrowserSessionProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<SessionState>(emptyState);
  const current = useRef(state);
  const update = useCallback((next: Omit<SessionState, "revision">) => {
    current.current = { ...next, revision: current.current.revision + 1 };
    setState(current.current);
  }, []);
  const isCurrent = useCallback((revision: number) => current.current.revision === revision, []);
  const clear = useCallback((revision: number, notice: SessionNotice = null) => {
    if (current.current.revision !== revision) return;
    update({ session: null, username: "", stepUpExpiresAt: "", notice });
  }, [update]);
  const begin = useCallback((session: BrowserAdminSession, username: string, revision: number) => {
    if (current.current.revision !== revision) return;
    if (!Number.isFinite(Date.parse(session.expiresAt)) || Date.parse(session.expiresAt) <= Date.now()) {
      clear(revision, "adminAuthRequired");
      return;
    }
    update({ session, username, stepUpExpiresAt: "", notice: null });
  }, [clear, update]);
  const elevate = useCallback((expiresAt: string, revision: number) => {
    if (current.current.revision !== revision || !current.current.session) return;
    const valid = Number.isFinite(Date.parse(expiresAt)) && Date.parse(expiresAt) > Date.now();
    update({ ...current.current, stepUpExpiresAt: valid ? expiresAt : "", notice: valid ? null : "adminStepUpRequired" });
  }, [update]);
  const recover = useCallback((error: unknown, revision: number) => {
    if (current.current.revision !== revision || !(error instanceof AdminApiError)) return false;
    if (error.status === 401 || error.code === "invalid_token" || error.code === "auth_required" || error.code === "tenant_required" || error.code === "csrf_required") {
      clear(revision, error.code === "csrf_required" ? "adminCsrfRequired" : "adminAuthRequired");
      return true;
    }
    if (error.code === "step_up_required" || error.code === "mfa_required") {
      update({ ...current.current, stepUpExpiresAt: "", notice: "adminStepUpRequired" });
      return true;
    }
    return false;
  }, [clear, update]);

  useEffect(() => {
    const check = () => {
      const active = current.current;
      if (active.revision !== state.revision || !active.session) return;
      if (Date.parse(active.session.expiresAt) <= Date.now()) clear(active.revision, "adminAuthRequired");
      else if (active.stepUpExpiresAt && Date.parse(active.stepUpExpiresAt) <= Date.now()) {
        update({ ...active, stepUpExpiresAt: "", notice: "adminStepUpRequired" });
      }
    };
    const deadlines = [state.session?.expiresAt, state.stepUpExpiresAt].filter(Boolean).map((value) => Date.parse(value!));
    const timer = deadlines.length ? window.setTimeout(check, Math.min(2_147_483_647, Math.max(0, Math.min(...deadlines) - Date.now()))) : undefined;
    document.addEventListener("visibilitychange", check);
    window.addEventListener("focus", check);
    return () => {
      window.clearTimeout(timer);
      document.removeEventListener("visibilitychange", check);
      window.removeEventListener("focus", check);
    };
  }, [state, clear, update]);

  return <SessionContext.Provider value={{ ...state, begin, elevate, clear, recover, isCurrent }}>{children}</SessionContext.Provider>;
}

export function useBrowserSession(): BrowserSessionContext {
  const context = useContext(SessionContext);
  if (!context) throw new Error("BrowserSessionProvider is required.");
  return context;
}
