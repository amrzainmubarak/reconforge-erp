import { AlertTriangle, Building2, CircleDot, Search, ShieldAlert, UserRoundX } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { loadExceptionQueue } from "../data";
import type { MessageKey } from "../i18n";
import type { ExceptionQueueContract } from "../types";
import { ErrorView, LoadingView } from "./StateViews";

interface ExceptionQueueProps {
  translate: (key: MessageKey) => string;
}

function unique(values: string[]): string[] {
  return [...new Set(values)].sort((left, right) => left.localeCompare(right));
}

export function ExceptionQueue({ translate }: ExceptionQueueProps) {
  const [data, setData] = useState<ExceptionQueueContract | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [query, setQuery] = useState("");
  const [risk, setRisk] = useState("");
  const [status, setStatus] = useState("");
  const [source, setSource] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    setData(null);
    setError("");
    loadExceptionQueue(controller.signal)
      .then(setData)
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        setError(reason instanceof Error ? reason.message : "The local exception queue could not be loaded.");
      });
    return () => controller.abort();
  }, [attempt]);

  const filtered = useMemo(() => {
    if (!data) return [];
    const normalized = query.trim().toLocaleLowerCase();
    return data.exceptions.filter((record) => {
      const haystack = [
        record.exception_id,
        record.description,
        record.entity_code,
        record.account_code,
        record.control_code,
        record.owner,
      ].join(" ").toLocaleLowerCase();
      return (
        (!normalized || haystack.includes(normalized)) &&
        (!risk || record.risk_rating === risk) &&
        (!status || record.status === status) &&
        (!source || record.source_type === source)
      );
    });
  }, [data, query, risk, source, status]);

  if (error) return <ErrorView translate={translate} message={error} onRetry={() => setAttempt((value) => value + 1)} />;
  if (!data) return <LoadingView translate={translate} />;

  const statuses = unique(data.exceptions.map((record) => record.status));
  const sources = unique(data.exceptions.map((record) => record.source_type));

  return (
    <main className="workbench-content" id="main-content">
      <header className="workbench-hero">
        <div>
          <div className="eyebrow"><span className="eyebrow-dot" /> {translate("localContract")}</div>
          <h1>{translate("exceptionQueue")}</h1>
          <p>{translate("exceptionQueueIntro")}</p>
        </div>
        <div className="contract-badge"><ShieldAlert size={18} /><span><strong>v{data.schema_version}</strong>{translate("readOnly")}</span></div>
      </header>

      <section className="workbench-stats" aria-label={translate("exceptionQueue")}>
        <article><span className="stat-icon"><CircleDot size={18} /></span><strong>{data.summary.total}</strong><small>{translate("totalRecords")}</small></article>
        <article><span className="stat-icon stat-icon--critical"><AlertTriangle size={18} /></span><strong>{data.summary.high_risk}</strong><small>{translate("highRiskExceptions")}</small></article>
        <article><span className="stat-icon stat-icon--warning"><CircleDot size={18} /></span><strong>{data.summary.open}</strong><small>{translate("openItems")}</small></article>
        <article><span className="stat-icon"><UserRoundX size={18} /></span><strong>{data.summary.unassigned}</strong><small>{translate("unassigned")}</small></article>
        <article><span className="stat-icon"><Building2 size={18} /></span><strong>{data.summary.entity_count}</strong><small>{translate("entities")}</small></article>
      </section>

      <section className="panel workbench-panel">
        <div className="filter-toolbar">
          <label className="filter-search">
            <Search size={17} aria-hidden="true" />
            <input value={query} onChange={(event) => setQuery(event.currentTarget.value)} placeholder={translate("filterExceptions")} aria-label={translate("filterExceptions")} />
          </label>
          <select value={risk} onChange={(event) => setRisk(event.currentTarget.value)} aria-label={translate("risk")}>
            <option value="">{translate("allRisks")}</option>
            {(["critical", "high", "medium", "low"] as const).map((value) => <option value={value} key={value}>{translate(value)}</option>)}
          </select>
          <select value={status} onChange={(event) => setStatus(event.currentTarget.value)} aria-label={translate("status")}>
            <option value="">{translate("allStatuses")}</option>
            {statuses.map((value) => <option value={value} key={value}>{value}</option>)}
          </select>
          <select value={source} onChange={(event) => setSource(event.currentTarget.value)} aria-label={translate("source")}>
            <option value="">{translate("allSources")}</option>
            {sources.map((value) => <option value={value} key={value}>{value}</option>)}
          </select>
          <span className="result-count" aria-live="polite"><strong>{filtered.length}</strong> {translate("results")}</span>
        </div>

        {filtered.length ? (
          <div className="table-scroll workbench-table" tabIndex={0}>
            <table>
              <thead><tr><th>{translate("exception")}</th><th>{translate("entity")}</th><th>{translate("account")}</th><th>{translate("risk")}</th><th>{translate("status")}</th><th>{translate("owner")}</th></tr></thead>
              <tbody>
                {filtered.map((record) => (
                  <tr key={record.exception_id}>
                    <td><span className="exception-title"><ShieldAlert size={15} />{record.description}</span><small>{record.exception_id} · {record.control_code || record.source_type}</small></td>
                    <td>{record.entity_code || "—"}</td>
                    <td>{record.account_code || "—"}</td>
                    <td><span className={`risk-chip risk-chip--${record.risk_rating}`}>{record.risk_rating}</span></td>
                    <td><span className="status-chip">{record.status}</span></td>
                    <td>{record.owner || translate("unassigned")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <p className="empty-panel">{translate("empty")}</p>}
      </section>

      <footer className="data-provenance"><span><span className="status-dot" /> {translate("boundedMetadata")}</span><span>{data.synthetic_data_marker}</span></footer>
    </main>
  );
}
