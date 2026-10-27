import { useEffect, useRef, useState } from "react";
import { useBrowserSession } from "../browserSession";
import { AdminApiError } from "../data";
import type { Locale } from "../types";

export interface EnterpriseScope { workspace: string; organization: string; entity: string }
export type BusinessRecord = Record<string, unknown>;
export interface ResultField { label: string; value: string | number }
export const object = (value: unknown): value is BusinessRecord => value !== null && typeof value === "object" && !Array.isArray(value);
export function requireRecord(value: unknown): BusinessRecord {
  if (!object(value)) throw new Error("invalid_response");
  return value;
}
export function requireText(record: BusinessRecord, key: string, expected?: string): string {
  const value = record[key];
  if (typeof value !== "string" || !value.trim() || value.length > 1000 || (expected !== undefined && value !== expected)) throw new Error("invalid_response");
  return value;
}
export function requireCount(record: BusinessRecord, key: string): number {
  const value = record[key];
  if (typeof value !== "number" || !Number.isSafeInteger(value)) throw new Error("invalid_response");
  return value;
}

/** One current authenticated request owns a result. Failed/stale requests cannot publish it. */
export function useEnterpriseWorkflow(locale: Locale, scope: EnterpriseScope) {
  const auth = useBrowserSession();
  const [result, setResult] = useState<{ context: string; fields: ResultField[] } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState<string | null>(null);
  const sequence = useRef(0), active = useRef<AbortController | null>(null);
  const scopeKey = JSON.stringify(scope);
  const contextKey = JSON.stringify([auth.revision, locale, scopeKey]);
  const currentContext = useRef(contextKey);
  currentContext.current = contextKey;
  const clear = () => { sequence.current++; active.current?.abort(); setResult(null); setError(null); setLoading(null); };
  useEffect(() => {
    clear();
    return () => { sequence.current++; active.current?.abort(); };
  }, [auth.revision, locale, scopeKey]);
  async function execute(path: string, parse: (value: unknown) => ResultField[], body?: object) {
    clear();
    if (!auth.session || !scope.workspace.trim()) { setError(contextKey); return; }
    const controller = new AbortController(); active.current = controller;
    const request = ++sequence.current, revision = auth.revision;
    setLoading(contextKey);
    try {
      const response = await fetch(`/api/v1/${path}`, {
        method: body === undefined ? "GET" : "POST", credentials: "same-origin", cache: "no-store", signal: controller.signal,
        headers: { Accept: "application/json", "X-ReconForge-Tenant": auth.session.tenantId,
          "X-ReconForge-Workspace": scope.workspace.trim(),
          ...(scope.organization.trim() ? { "X-ReconForge-Organization": scope.organization.trim() } : {}),
          ...(scope.entity.trim() ? { "X-ReconForge-Legal-Entity": scope.entity.trim() } : {}),
          ...(body === undefined ? {} : { "Content-Type": "application/json", "X-ReconForge-CSRF": auth.session.csrfToken }) },
        ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      });
      if (!response.ok) {
        let code = "request_failed";
        try { const value: unknown = await response.json(); if (object(value) && object(value.error) && typeof value.error.code === "string") code = value.error.code; } catch { /* Never display raw server text. */ }
        if (sequence.current === request && !controller.signal.aborted && auth.isCurrent(revision) && currentContext.current === contextKey) {
          auth.recover(new AdminApiError(response.status, code), revision);
        }
        throw new Error("request_failed");
      }
      const fields = parse(await response.json());
      if (sequence.current === request && !controller.signal.aborted && auth.isCurrent(revision) && currentContext.current === contextKey) setResult({ context: contextKey, fields });
    } catch {
      if (sequence.current === request && !controller.signal.aborted && auth.isCurrent(revision) && currentContext.current === contextKey) { setResult(null); setError(contextKey); }
    } finally {
      if (sequence.current === request && !controller.signal.aborted && auth.isCurrent(revision) && currentContext.current === contextKey) setLoading(null);
    }
  }
  return { result: result?.context === contextKey ? result.fields : null, error: error === contextKey, loading: loading === contextKey, execute, clear, signedIn: auth.session !== null };
}

export function EnterpriseScopeFields({ locale, scope, onChange }: { locale: Locale; scope: EnterpriseScope; onChange: (scope: EnterpriseScope) => void }) {
  const isAr = locale === "ar";
  return <fieldset className="panel reporting-form"><legend>{isAr ? "نطاق العمل المصرح" : "Authorized business scope"}</legend>
    {([['workspace', isAr ? 'مساحة العمل' : 'Workspace ID'], ['organization', isAr ? 'المنظمة' : 'Organization ID'], ['entity', isAr ? 'الكيان القانوني' : 'Legal entity ID']] as const).map(([key, label]) => <label key={key}>{label}<input value={scope[key]} maxLength={160} onChange={event => onChange({ ...scope, [key]: event.target.value })} /></label>)}
  </fieldset>;
}

export function EnterpriseResult({ locale, workflow }: { locale: Locale; workflow: ReturnType<typeof useEnterpriseWorkflow> }) {
  const isAr = locale === "ar";
  return <>
    {!workflow.signedIn && <p role="status">{isAr ? "سجّل الدخول للوصول إلى السجلات المخولة. لم يُنفذ أي إجراء." : "Sign in to access authorized records. No action has been performed."}</p>}
    {workflow.loading && <p role="status" aria-live="polite">{isAr ? "جارٍ انتظار استجابة الخادم…" : "Waiting for the server response…"}</p>}
    {workflow.error && <p role="alert">{isAr ? "تعذر التحقق من استجابة صالحة. تحقق من الجلسة والصلاحيات والنطاق ثم أعد المحاولة. لا توجد نتيجة مؤكدة لهذا الطلب." : "A valid response could not be verified. Check your session, permissions and scope, then retry. There is no confirmed result for this request."}</p>}
    {workflow.result && <section className="panel" aria-label={isAr ? "النتيجة الموثقة من الخادم" : "Verified server response"}><p role="status" aria-live="polite">{isAr ? "استُلمت استجابة الخادم." : "Server response received."}</p><dl>{workflow.result.map((field, index) => <div key={index}><dt>{field.label}</dt><dd>{field.value}</dd></div>)}</dl></section>}
  </>;
}
